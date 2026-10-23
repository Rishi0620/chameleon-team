"""Pixel critic: renders a candidate with the OFFICIAL renderer code path and measures what a VLM
judge would 'see'. Layers: full render, under-text render (render_text=False), solo alpha mask per
element (transparent canvas). All metrics are computed on those pixels, not on JSON boxes."""
import sys, time
from pathlib import Path
import numpy as np
import skia
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT))
from renderer.converter import convert as C
from renderer.converter.colorutil import parse_rgba
from renderer.converter.wrap import char_widths, wrap_text
from cr_renderer import renderer as CR

ASSETS = str(ROOT / "brand_kit/assets"); FONTS = str(ROOT / "brand_kit/fonts")
R = C._get_renderer(FONTS); FM = R.font_manager

def _surface_rgba(example, render_text=True, transparent=False):
    ex = CR._decode_class_label(R.features, example)
    png = CR._render_to_surface(FM, ex, 4096, render_text, "png", None if transparent else skia.ColorWHITE)
    img = skia.Image.DecodeToRaster(png) if hasattr(skia.Image, "DecodeToRaster") else skia.Image.MakeFromEncoded(png)
    return np.asarray(img.toarray(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType))

def render(design, render_text=True, transparent=False):
    ex, _ = C.convert_chameleon_to_crello(design, FM, ASSETS)
    return _surface_rgba(ex, render_text, transparent)

def lum(rgb):
    c = rgb.astype(np.float64) / 255.0
    l = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * l[..., 0] + 0.7152 * l[..., 1] + 0.0722 * l[..., 2]

def visible(el):
    if el.get("opacity", 1.0) <= 0.01 and el["type"] != "text":
        return False
    if el["type"] == "text":
        return parse_rgba(el.get("color"))[3] > 0.01   # renderer ignores text opacity, honours colour alpha
    return True

def text_lines(el):
    w = char_widths(FM, el["font_family"], "bold" if el.get("font_weight") == "bold" else "regular",
                    "bold" if el.get("font_weight") == "bold" else "regular", el["font_size"], el["content"])
    wrapped = wrap_text(el["content"], w, el["width"])
    lines = wrapped.split("\n"); off = 0; widths = []
    for ln in lines:
        widths.append(sum(w[off:off + len(ln)])); off += len(ln) + 1
    return lines, widths

def x_height(el):
    tf = skia.Typeface.MakeFromData(FM.lookup(el["font_family"], "bold" if el.get("font_weight") == "bold" else "regular",
                                              "bold" if el.get("font_weight") == "bold" else "regular"))
    return skia.Font(tf, el["font_size"]).getMetrics().fXHeight

_MASKS = {}

def critique(design, roles=None, verbose=False):
    t0 = time.perf_counter()
    cw, ch = design["canvas"]["width"], design["canvas"]["height"]
    els = design["elements"]
    full = render(design)[..., :3]
    under = render(design, render_text=False)[..., :3]
    masks = {}
    for el in els:
        if not visible(el):
            continue
        key = (design["canvas"]["width"], design["canvas"]["height"], repr(sorted(el.items())))
        if key not in _MASKS:
            solo = {"canvas": design["canvas"], "elements": [el]}
            _MASKS[key] = render(solo, transparent=True)[..., 3] > 40
        masks[el["id"]] = _MASKS[key]
    t_render = time.perf_counter() - t0
    m = {"render_ms": round(t_render * 1000)}
    pen = []
    groups = {e["id"]: e.get("group_id") for e in els}
    deco = set((roles or {}).get("decoration", [])) | set((roles or {}).get("background", []))
    # 1. text contrast + size + cut-off
    for el in els:
        if el["type"] != "text" or not visible(el) or el["id"] not in masks:
            continue
        gm = masks[el["id"]]
        r, g, b, a = parse_rgba(el["color"])
        if gm.sum() == 0:
            pen.append((f"{el['id']}: no ink on canvas", 5)); continue
        bgL = lum(under[gm]); tL = lum(np.array([[r, g, b]], float))[0] * a + bgL * (1 - a)
        cr = (np.maximum(tL, bgL) + 0.05) / (np.minimum(tL, bgL) + 0.05)
        p10 = float(np.percentile(cr, 10))
        xh = x_height(el)
        lines, lw = text_lines(el)
        bottom = el["y"] + len(lines) * el["font_size"] * el.get("line_height", 1.2)
        over_w = max(lw) - el["width"] if lw else 0
        m[f"{el['id']}.contrast_p10"] = round(p10, 2)
        m[f"{el['id']}.xheight_px"] = round(xh, 1)
        m[f"{el['id']}.lines"] = len(lines)
        if p10 < 4.5: pen.append((f"{el['id']}: contrast p10 {p10:.2f}<4.5", (4.5 - p10) * 2))
        if xh < 6: pen.append((f"{el['id']}: x-height {xh:.1f}px unreadable", (6 - xh) * 3))
        if bottom > ch + 0.5: pen.append((f"{el['id']}: text runs off canvas by {bottom-ch:.0f}px", 10))
        if bottom > el["y"] + el["height"] + 1: pen.append((f"{el['id']}: text overflows its box by {bottom-el['y']-el['height']:.0f}px", 3))
        if over_w > 1: pen.append((f"{el['id']}: word wider than box by {over_w:.0f}px", 5))
    # 2. ink collisions between non-grouped, non-decoration elements
    ids = [i for i in masks if i not in deco]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a_, b_ = ids[i], ids[j]
            if groups[a_] and groups[a_] == groups[b_]:
                continue
            inter = (masks[a_] & masks[b_]).sum()
            if inter > 0:
                frac = inter / max(1, min(masks[a_].sum(), masks[b_].sum()))
                if frac > 0.002:
                    pen.append((f"collision {a_} x {b_}: {frac:.1%} of smaller ink", 20 * frac + 2))
    # 3. missing-asset placeholder visible (grey 214 box)
    ph = ((np.abs(full.astype(int) - 214).max(-1) < 3)).mean()
    if ph > 0.002: pen.append((f"missing-asset placeholder visible ({ph:.1%} of canvas)", 15))
    # 4. foreground balance: ink centroid offset & coverage
    fg = np.zeros((ch, cw), bool)
    for k, v in masks.items():
        if k not in deco: fg |= v
    cov = fg.mean()
    if cov > 0:
        ys, xs = np.nonzero(fg)
        off = np.hypot(xs.mean() / cw - 0.5, ys.mean() / ch - 0.5)
        m["ink_coverage"] = round(float(cov), 3); m["ink_centroid_off"] = round(float(off), 3)
        if off > 0.12: pen.append((f"visual weight off-centre {off:.2f}", (off - 0.12) * 20))
        if cov < 0.08: pen.append((f"canvas looks empty (ink {cov:.0%})", (0.08 - cov) * 50))
    m["ink_share"] = {k: float(v.sum()) for k, v in masks.items() if k not in deco}
    m["penalty"] = round(sum(p for _, p in pen), 2)
    m["issues"] = [s for s, _ in pen]
    m["critic_ms"] = round((time.perf_counter() - t0) * 1000)
    return m, full
