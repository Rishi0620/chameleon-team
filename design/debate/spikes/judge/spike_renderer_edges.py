"""JUDGE spike: probe the official renderer + main.py self_check on adversarial inputs.

Run from repo root:
    .venv/bin/python design/debate/spikes/judge/spike_renderer_edges.py

Writes PNGs + a findings log next to this file. Each probe is isolated so one
crash does not hide the others.
"""
import json
import sys
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, ".")
from engine.main import self_check  # noqa: E402
from renderer.converter.convert import render_design_to_png  # noqa: E402

OUT = Path("design/debate/spikes/judge/out")
OUT.mkdir(parents=True, exist_ok=True)
ASSETS = "brand_kit/assets"
BG = (40, 40, 40)


def bg_rect(w, h):
    return {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": w, "height": h, "z_index": 0,
            "shape_type": "rectangle", "fill_color": "rgba(40,40,40,1)"}


def text(id_, content, x, y, w, h, fs=40, **kw):
    el = {"id": id_, "type": "text", "x": x, "y": y, "width": w, "height": h, "z_index": 5,
          "content": content, "font_family": "Solstice Sans", "font_size": fs,
          "font_weight": "bold", "color": "rgba(255,255,255,1)", "text_align": "left"}
    el.update(kw)
    return el


def ink_bbox(png, bg=BG, tol=30):
    """Bounding box of pixels that differ from the flat background colour."""
    a = np.asarray(Image.open(png).convert("RGB")).astype(int)
    diff = np.abs(a - np.array(bg)).sum(axis=2) > tol
    ys, xs = np.nonzero(diff)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def probe(name, design, region=None):
    """Render one design, report crash / warnings / ink bbox (optionally inside region)."""
    png = OUT / f"{name}.png"
    rec = {"probe": name}
    try:
        warns = render_design_to_png(design, ASSETS, str(png))
        rec["render"] = "ok"
        rec["warnings"] = warns
        if region is not None:
            x0, y0, x1, y1 = region
            a = np.asarray(Image.open(png).convert("RGB")).astype(int)[y0:y1, x0:x1]
            diff = np.abs(a - np.array(BG)).sum(axis=2) > 30
            rec["ink_pixels_in_region"] = int(diff.sum())
        rec["ink_bbox"] = ink_bbox(png)
    except Exception as exc:  # noqa: BLE001 - spike: we want every failure mode
        rec["render"] = f"CRASH {type(exc).__name__}: {str(exc)[:200]}"
        rec["trace_tail"] = traceback.format_exc().splitlines()[-3:]
    rec["self_check"] = self_check(design, design)
    return rec


W, H = 800, 400
results = []

# 1. opacity 0 on text vs image vs shape: does "drop via opacity 0" work?
results.append(probe("01_text_opacity0", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "HIDDEN?", 50, 50, 700, 80, fs=60, opacity=0)]}))
results.append(probe("02_image_opacity0", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), {"id": "p", "type": "image", "x": 50, "y": 50, "width": 300, "height": 300,
                    "z_index": 3, "asset_id": "solstice_bottle.png", "opacity": 0}]}))
results.append(probe("03_shape_opacity0", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), {"id": "s", "type": "shape", "x": 50, "y": 50, "width": 300, "height": 100,
                    "z_index": 3, "shape_type": "rectangle", "fill_color": "rgba(232,106,58,1)",
                    "opacity": 0}]}))
results.append(probe("04_text_color_alpha0", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "HIDDEN?", 50, 50, 700, 80, fs=60, color="rgba(255,255,255,0)")]}))

# 2. rotated element whose UNROTATED box is inside but rotated corners leave the canvas
results.append(probe("05_rotated_near_edge", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), {"id": "r", "type": "shape", "x": 500, "y": 0, "width": 300, "height": 60,
                    "z_index": 3, "rotation": -12, "shape_type": "rectangle",
                    "fill_color": "rgba(220,60,50,1)"}]}))

# 3. word wider than its box (no spaces -> greedy wrap cannot break it)
results.append(probe("06_word_wider_than_box", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "Supercalifragilistic", 300, 150, 120, 60, fs=40, text_align="center")]}))

# 4. empty string / whitespace-only / newline-only content
results.append(probe("07_empty_string", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "", 50, 50, 300, 60)]}))
results.append(probe("08_newlines_only", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "\n\n", 50, 50, 300, 60)]}))

# 5. emoji + non-Latin scripts (brand fonts are Lora/Poppins renames)
results.append(probe("09_emoji_cjk_arabic", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "Sale \U0001F525 50% 日本語 العربية café — ©",
                        20, 50, 760, 80, fs=40)]}))

# 6. degenerate sizes: text width 0, text height 0, font_size 0.5, image width 0
results.append(probe("10_text_width0", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "zero width", 50, 50, 0, 60)]}))
results.append(probe("11_text_height0", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "zero height", 50, 50, 300, 0)]}))
results.append(probe("12_font_size_0p5", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "tiny font", 50, 50, 300, 60, fs=0.5)]}))
results.append(probe("13_image_width0", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), {"id": "p", "type": "image", "x": 50, "y": 50, "width": 0, "height": 100,
                    "z_index": 3, "asset_id": "solstice_bottle.png"}]}))

# 7. html entity in content: renderer html.unescape()s AFTER wrapping -> index shift?
results.append(probe("14_html_entity", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "Salt &amp; Pepper &lt;3 and more words here", 50, 50, 300, 60, fs=36,
                        style_runs=[{"start": 18, "end": 27, "color": "rgba(240,178,66,1)"}])]}))

# 8. letter_spacing: wrap measures WITHOUT it, render draws WITH it
results.append(probe("15_letter_spacing", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "WIDE TRACKING HERE", 100, 150, 400, 60, fs=36, letter_spacing=12)]}))
results.append(probe("15b_no_letter_spacing", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "WIDE TRACKING HERE", 100, 150, 400, 60, fs=36)]}))

# 9. shape stroke on a rectangle (ignored?) and a zero-height line
results.append(probe("16_rect_stroke", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), {"id": "s", "type": "shape", "x": 50, "y": 50, "width": 300, "height": 100,
                    "z_index": 3, "shape_type": "rectangle", "fill_color": "rgba(40,40,40,0)",
                    "stroke_color": "rgba(255,255,255,1)", "stroke_width": 6}]}))
results.append(probe("17_line_h0", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), {"id": "l", "type": "shape", "x": 50, "y": 200, "width": 700, "height": 0,
                    "z_index": 3, "shape_type": "line", "fill_color": "rgba(255,255,255,1)",
                    "stroke_color": "rgba(255,255,255,1)", "stroke_width": 4}]}))

# 10. style_runs end: schema says end-exclusive; renderer uses range(start, end+1)
results.append(probe("18_style_run_end", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "AAAABBBB", 50, 50, 700, 80, fs=60,
                        style_runs=[{"start": 0, "end": 4, "color": "rgba(240,178,66,1)"}])]}))

# 11. unknown font family + unknown weight
results.append(probe("19_unknown_font", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "Unknown family", 50, 50, 700, 80, fs=50, font_family="Helvetica Neue",
                        font_weight="semibold")]}))

# 12. text color as hex / named color (renderer parse path)
results.append(probe("20_named_color", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "Named colour", 50, 50, 700, 80, fs=50, color="white")]}))
results.append(probe("21_hex_color", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "Hex colour", 50, 50, 700, 80, fs=50, color="#ffcc00")]}))

# 13. non-integer font size: measured at float, rendered at int(fs)
results.append(probe("22_float_font_size", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "MMMMMMMMMM", 0, 50, 800, 80, fs=59.9)]}))
results.append(probe("22b_int_font_size", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "MMMMMMMMMM", 0, 50, 800, 80, fs=59)]}))

# 14. extra/unknown keys + missing optional keys + null group_id
results.append(probe("23_extra_keys", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), dict(text("t", "Extra keys", 50, 50, 700, 80, fs=50), _note="x",
                        group_id=None, max_lines=None, custom={"a": 1})]}))

# 15. right-aligned text with an over-long word: does it bleed LEFT of x?
results.append(probe("24_right_align_overflow", {"canvas": {"width": W, "height": H}, "elements": [
    bg_rect(W, H), text("t", "Unbreakableverylongword", 600, 150, 150, 60, fs=40, text_align="right")]}))

# 16. multi-line text height vs. box height (box height ignored)
results.append(probe("25_text_overflows_down", {"canvas": {"width": W, "height": 200}, "elements": [
    bg_rect(W, 200), text("t", "one two three four five six seven eight nine ten eleven twelve",
                          50, 20, 200, 30, fs=36)]}))

# 17. big canvas -> render downscale (max_size 2048)
results.append(probe("26_big_canvas_2560x1440", {"canvas": {"width": 2560, "height": 1440}, "elements": [
    bg_rect(2560, 1440), text("t", "Big canvas", 100, 100, 1000, 100, fs=80)]}))

log = OUT.parent / "findings.json"
log.write_text(json.dumps(results, indent=2, default=str))
for r in results:
    print(f"{r['probe']:<28} render={r['render'][:70]:<70} ink={r.get('ink_bbox')} "
          f"region_ink={r.get('ink_pixels_in_region', '-')} self_check={len(r['self_check'])}")
    for w in r.get("warnings", []) or []:
        print("      warn:", w)
    for p in r["self_check"]:
        print("      self_check:", p)
