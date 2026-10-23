"""JUDGE spike: prototype structural + geometric proxy scorer.

Stricter than engine/main.py self_check. Measures text with the renderer's
own wrap functions (char_widths + wrap_text) and models the renderer quirks
found in spike_renderer_edges.py:
  - text box height ignored; lines overflow downward
  - letter_spacing NOT included in wrap measurement but IS drawn
  - glyphs drawn at int(font_size)
  - text `opacity` ignored by renderer (text is visible unless colour alpha == 0)
  - text width/height <= 0 crashes the renderer (pydantic gt=0)
  - rotated corners can leave the canvas while the unrotated box passes self_check

Usage (repo root):
    .venv/bin/python design/debate/spikes/judge/proxy_scorer.py
"""
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, ".")
from renderer.converter.assets import asset_path  # noqa: E402
from renderer.converter.colorutil import parse_rgba  # noqa: E402
from renderer.converter.convert import (  # noqa: E402
    _BOLD_WEIGHTS, _get_renderer, _is_italic, _normalize_weight, _weight_style_to_font_style)
from renderer.converter.wrap import char_widths, wrap_text  # noqa: E402
from PIL import Image  # noqa: E402

ASSETS = "brand_kit/assets"
FM = _get_renderer("brand_kit/fonts").font_manager
REQ = {"text": ["content", "font_family", "font_size", "color"], "image": ["asset_id"],
       "shape": ["shape_type", "fill_color"]}
EVAL_MAX_SIDE = 1024      # assumed VLM input resolution (long side) - calibrate later
MIN_PERCEIVED_PX = 9.0    # visible text below this (after VLM downscale) is "unreadable"
ASPECT_TOL = 0.05


def text_layout(el: dict[str, Any]) -> dict[str, float]:
    """Emulate converter wrap + renderer draw: returns n_lines, ink box (x0,y0,x1,y1)."""
    content = str(el.get("content", ""))
    fs = float(el.get("font_size", 24))
    weight = _normalize_weight(el.get("font_weight"))
    style = _weight_style_to_font_style(weight in _BOLD_WEIGHTS,
                                        _is_italic(el.get("font_style") or el.get("italic")))
    fam = el.get("font_family", "")
    box_w = float(el.get("width", 1))
    wrapped = wrap_text(content, char_widths(FM, fam, weight, style, fs, content), box_w)
    draw_w = char_widths(FM, fam, weight, style, int(fs), content) if int(fs) > 0 else []
    ls = float(el.get("letter_spacing", 0) or 0)
    lines, start = [], 0
    for i, c in enumerate(wrapped + "\n"):
        if c == "\n":
            seg = range(start, i)
            w = sum(draw_w[j] for j in seg if j < len(draw_w)) + ls * max(0, len(seg) - 1)
            lines.append(w)
            start = i + 1
    lh = float(el.get("line_height", 1.2) or 1.2)
    n = len(lines) if content.strip() else 0
    align = el.get("text_align", "left")
    offs = [0.0 if align == "left" else (box_w - w) / 2 if align == "center" else box_w - w
            for w in lines]
    x0 = el["x"] + min((o for o in offs), default=0)
    x1 = el["x"] + max((o + w for o, w in zip(offs, lines)), default=0)
    height = n * fs * lh
    return {"n_lines": n, "max_line_w": max(lines, default=0), "ink": (x0, el["y"], x1, el["y"] + height)}


def rotated_aabb(el: dict[str, Any]) -> tuple[float, float, float, float]:
    x, y, w, h = el["x"], el["y"], el["width"], el["height"]
    r = math.radians(float(el.get("rotation", 0) or 0))
    cx, cy = x + w / 2, y + h / 2
    hw = abs(w / 2 * math.cos(r)) + abs(h / 2 * math.sin(r))
    hh = abs(w / 2 * math.sin(r)) + abs(h / 2 * math.cos(r))
    return cx - hw, cy - hh, cx + hw, cy + hh


def _opaque_cover(o: dict[str, Any], el: dict[str, Any], order: dict[str, int]) -> bool:
    """True if `o` is an opaque layer painted above `el` that fully covers el's box."""
    if o is el or float(o.get("opacity", 1)) < 0.999:
        return False
    above = (o.get("z_index", 0), order[o["id"]]) > (el.get("z_index", 0), order[el["id"]])
    covers = o["x"] <= el["x"] and o["y"] <= el["y"] and \
        o["x"] + o["width"] >= el["x"] + el["width"] and o["y"] + o["height"] >= el["y"] + el["height"]
    if not (above and covers and not o.get("rotation")):
        return False
    if o["type"] == "shape":
        return o.get("shape_type", "rectangle") == "rectangle" and parse_rgba(o.get("fill_color"))[3] >= 0.999
    if o["type"] == "image" and o.get("fit") in ("cover", "fill"):
        p = asset_path(ASSETS, o.get("asset_id"))
        return p is not None and Image.open(p).mode == "RGB"
    return False


def is_visible(el: dict[str, Any], design: dict[str, Any] | None = None) -> bool:
    if design is not None:
        order = {e["id"]: i for i, e in enumerate(design["elements"])}
        if any(_opaque_cover(o, el, order) for o in design["elements"]):
            return False
    if el["type"] == "text":  # renderer ignores text opacity!
        return bool(str(el.get("content", "")).strip()) and parse_rgba(el.get("color"))[3] > 0.02 \
            and int(float(el.get("font_size", 0))) >= 1
    alpha = float(el.get("opacity", 1) or 0)
    if el["type"] == "shape":
        alpha *= parse_rgba(el.get("fill_color"))[3]
    return alpha > 0.02 and el["width"] >= 1 and el["height"] >= 1


def overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def score(source: dict, out: dict) -> dict[str, Any]:
    """Return {'hard': [...], 'soft': [...], 'metrics': {...}}. Any hard issue = likely zero."""
    hard, soft = [], []
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    src = {e["id"]: e for e in source["elements"]}
    ids = [e.get("id") for e in out["elements"]]
    if sorted(ids) != sorted(src):
        hard.append("id set/count mismatch")
    for el in out["elements"]:
        eid, s = el.get("id"), src.get(el.get("id"), {})
        for f in ["id", "type", "x", "y", "width", "height"] + REQ.get(el.get("type"), []):
            if f not in el:
                hard.append(f"{eid}: missing {f}")
        if any(not math.isfinite(float(el.get(k, 0))) for k in ("x", "y", "width", "height")):
            hard.append(f"{eid}: non-finite geometry")
            continue
        for k in ("content", "font_family", "asset_id", "type", "fit", "group_id"):
            if k in s and el.get(k) != s.get(k):
                hard.append(f"{eid}: changed '{k}'")
        # R2 fix: an alpha-only colour change is the team's hide encoding, not a brand violation.
        # Only an RGB change is flagged (soft). Superseded by bench/contract.py.
        if "color" in s and parse_rgba(el.get("color"))[:3] != parse_rgba(s.get("color"))[:3]:
            soft.append(f"{eid}: colour RGB changed")
        if el["type"] == "text" and (el["width"] <= 0 or el["height"] <= 0):
            hard.append(f"{eid}: text w/h <= 0 -> renderer CRASH")
        if el["x"] < -0.5 or el["y"] < -0.5 or el["x"] + el["width"] > W + 0.5 or el["y"] + el["height"] > H + 0.5:
            hard.append(f"{eid}: off-canvas (unrotated box)")
        rx0, ry0, rx1, ry1 = rotated_aabb(el)
        if is_visible(el, out) and (rx0 < -1 or ry0 < -1 or rx1 > W + 1 or ry1 > H + 1):
            soft.append(f"{eid}: rotated corners leave canvas (visually clipped)")
        if el["type"] == "image" and el.get("fit", "contain") != "cover" and s:
            full_bleed = s["width"] * s["height"] >= 0.9 * source["canvas"]["width"] * source["canvas"]["height"]
            a_src = s["width"] / max(s["height"], 1e-6)
            a_out = el["width"] / max(el["height"], 1e-6)
            if not full_bleed and abs(a_out / a_src - 1) > ASPECT_TOL:
                hard.append(f"{eid}: image aspect {a_out:.2f} vs src {a_src:.2f}")
        if el["type"] == "image" and is_visible(el, out) and asset_path(ASSETS, el.get("asset_id")) is None:
            soft.append(f"{eid}: visible MISSING-ASSET placeholder ({el['width']:.0f}x{el['height']:.0f})")
    # text-specific: overflow, legibility, collisions
    scale = min(1.0, EVAL_MAX_SIDE / max(W, H))
    vis = [e for e in out["elements"] if is_visible(e, out)]
    inks = {}
    for el in vis:
        if el["type"] != "text":
            continue
        lay = text_layout(el)
        inks[el["id"]] = lay["ink"]
        x0, y0, x1, y1 = lay["ink"]
        if lay["max_line_w"] > el["width"] + 1:
            soft.append(f"{el['id']}: line wider than box by {lay['max_line_w'] - el['width']:.0f}px")
        if y1 > el["y"] + el["height"] + 2:
            soft.append(f"{el['id']}: {lay['n_lines']} lines overflow box height by {y1 - el['y'] - el['height']:.0f}px")
        if x0 < -1 or x1 > W + 1 or y1 > H + 1:
            soft.append(f"{el['id']}: text ink leaves canvas")
        mx = src.get(el["id"], {}).get("max_lines")
        if mx and lay["n_lines"] > mx:
            soft.append(f"{el['id']}: {lay['n_lines']} lines > max_lines {mx}")
        perceived = int(float(el["font_size"])) * scale
        if perceived < MIN_PERCEIVED_PX:
            soft.append(f"{el['id']}: perceived font {perceived:.1f}px < {MIN_PERCEIVED_PX}")
    # collisions: text ink vs any other visible element, ignoring group-mates and pairs overlapping in source
    canvas_area = W * H
    for tid, ink in inks.items():
        t = next(e for e in out["elements"] if e["id"] == tid)
        for o in vis:
            if o["id"] == tid or (t.get("group_id") and t.get("group_id") == o.get("group_id")):
                continue
            ob = inks.get(o["id"]) or (o["x"], o["y"], o["x"] + o["width"], o["y"] + o["height"])
            if (ob[2] - ob[0]) * (ob[3] - ob[1]) >= 0.8 * canvas_area:
                continue  # background layer
            ov = overlap(ink, ob)
            if ov <= 0:
                continue
            s1, s2 = src.get(tid), src.get(o["id"])
            src_ov = overlap((s1["x"], s1["y"], s1["x"] + s1["width"], s1["y"] + s1["height"]),
                             (s2["x"], s2["y"], s2["x"] + s2["width"], s2["y"] + s2["height"])) if s1 and s2 else 0
            if src_ov == 0 and ov > 0.05 * max(1.0, (ink[2] - ink[0]) * (ink[3] - ink[1])):
                soft.append(f"collision: text '{tid}' x '{o['id']}'")
    n_hidden = sum(1 for e in out["elements"] if not is_visible(e, out))
    return {"hard": hard, "soft": soft,
            "metrics": {"visible": len(vis), "hidden": n_hidden, "eval_scale": round(scale, 3)}}


if __name__ == "__main__":
    import json
    for lvl in ["level1_warmup", "level2_core", "level3_advanced"]:
        task = json.loads(Path(f"input/chameleon_sample_{lvl}.json").read_text())
        out = json.loads(Path(f"output/chameleon_sample_{lvl}_output.json").read_text())
        r = score(task["source"], out)
        print(f"== baseline {lvl}: {len(r['hard'])} hard, {len(r['soft'])} soft  {r['metrics']}")
        for p in r["hard"] + r["soft"]:
            print("   -", p)
