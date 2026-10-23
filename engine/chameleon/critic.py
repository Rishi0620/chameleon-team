"""PERCEPTION's pixel critic for the merged prototype (owner: PERCEPTION).

    critique(source, output, info, render_png_path=None) -> {"vetoes": [...], "penalty": float, "features": {...}}

Job (Round-2 conclusion): a VETO detector for broken-vs-designed (~92-98% agreement with the eye), NOT a taste
oracle (36-64% on designed-vs-designed). Every threshold is SOURCE-RELATIVE: the source render is the per-design
reference for contrast, busyness, collisions (layering the designer already had is intent), spill and legibility.
Relation-aware: text on its own host panel (info["containers"]) or inside its group is never a collision;
decoration/background layering is never a collision.

Cheap: no PNG encode/decode, no per-element "without" renders. Images/shapes are drawn from a decoded-skia-image
cache with the SAME PIL fit/rasterisation code and the SAME skia draw calls as the official renderer
(renderer/converter + cr_renderer._render_to_surface), so pixels match the official path (see tests/test_critic.py
parity check). Per candidate: one underlay pass (non-text) + one full pass + one small cropped pass per text.

Never raises: on internal error returns {"vetoes": [], "penalty": 0.0, "features": {"error": ...}}.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
import traceback
from collections import OrderedDict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ----------------------------------------------------------------------------------------------- constants
# Calibration targets: see design/debate/round3/perception_calibration.md. Defaults below are Round-2 values.
JUDGE_LONG_SIDE = 1024          # assumed evaluator viewing size (JUDGE); judge_px = px * min(1, 1024/long side)
FLOOR_PX = {"headline": 12, "cta_label": 11, "subhead": 10, "body": 10, "badge_label": 9, "legal": 8}
DEFAULT_FLOOR_PX = 9
LOST_BACKDROP_RATIO = 0.5       # veto if contrast_p10 < 0.5 x the source's own contrast for that text AND < 2.0:1,
LOST_BACKDROP_ABS = 1.5         # ... or < 1.5:1 outright (text effectively invisible)
LOST_BACKDROP_GUARD = 2.0       # large text (>= 18 judge-px): never veto at >= 2.0:1; small text: guard 3.0:1
LOST_BACKDROP_GUARD_SMALL = 3.0
LOST_BACKDROP_DEFICIT = 0.55    # veto if contrast < 0.55 x min(WCAG need for its size, source's own contrast)
ILLEGIBLE_VETO = 0.75           # veto below 0.75 x floor (clearly unreadable); 0.75-1.25 x floor is a penalty band
BUSY_VETO_ABS = 0.25            # veto if edge density around glyphs > 0.25 AND > 2x source + 0.10
BUSY_VETO_REL = 2.0
BUSY_VETO_ADD = 0.10
EDGE_GRAD = 12.0                # |grad| on 0-255 grey that counts as an edge
COLLISION_MIN_PX = 24           # ink-overlap veto: >= max(24 px, 1% of the smaller ink)
COLLISION_FRAC = 0.01
CLIP_FRAC = 0.02                # rotated element: >2% of its ink outside the canvas
SPILL_FRAC = 0.01               # rider/label: >1% of its ink outside its host / group shape (and worse than source)
LEAK_MIN_PX = 20                # hidden element showing >= 20 px
MASK_ALPHA = 40                 # solo-render alpha that counts as ink
OCCLUDER_ALPHA = 0.9            # an element hides what is below it only where its effective alpha >= 0.9
NON_FLOW = {"background", "decoration", "texture"}
CACHE_MAX = 512

_IMG_CACHE: "OrderedDict[tuple, object]" = OrderedDict()     # key -> (skia.Image, alpha float array)
_TXT_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()       # key -> solo text result
_SRC_CACHE: "OrderedDict[str, dict]" = OrderedDict()         # source hash -> source analysis
_STATS = {"img_hit": 0, "img_miss": 0, "txt_hit": 0, "txt_miss": 0, "src_hit": 0, "src_miss": 0}


def _lru_put(cache, key, val):
    cache[key] = val
    cache.move_to_end(key)
    while len(cache) > CACHE_MAX:
        cache.popitem(last=False)


# ----------------------------------------------------------------------------------------------- renderer glue
_R = None


def _renderer():
    global _R
    if _R is None:
        from renderer.converter.convert import _get_renderer
        _R = _get_renderer(str(ROOT / "brand_kit" / "fonts"))
    return _R


def _assets_dir(info):
    a = (info or {}).get("assets_dir") or "brand_kit/assets"
    p = Path(a)
    return str(p if p.is_absolute() else ROOT / p)


def _rgba(s, default=(0, 0, 0, 1.0)):
    from renderer.converter.colorutil import parse_rgba
    return parse_rgba(s, default=default)


def _image_entry(el, assets_dir):
    """(skia.Image, effective-alpha float32 HxW at PIL size) for an image/shape, cached; same PIL code as converter."""
    import skia  # noqa: F401
    from cr_renderer import image_utils
    from renderer.converter.assets import load_asset_image
    from renderer.converter.shapes import render_shape
    w, h = max(1, round(el.get("width", 1))), max(1, round(el.get("height", 1)))
    if el.get("type") == "image":
        key = ("img", assets_dir, el.get("asset_id"), w, h, el.get("fit", "contain"))
    elif el.get("type") == "shape":
        key = ("shp", el.get("shape_type"), el.get("fill_color"), el.get("stroke_color"), el.get("stroke_width"),
               el.get("corner_radius"), w, h)
    else:
        key = ("blank", w, h)
    hit = _IMG_CACHE.get(key)
    if hit is not None:
        _STATS["img_hit"] += 1
        _IMG_CACHE.move_to_end(key)
        return hit
    _STATS["img_miss"] += 1
    from PIL import Image
    if el.get("type") == "image":
        pil = load_asset_image(assets_dir, el.get("asset_id"), el.get("width", 1.0), el.get("height", 1.0),
                               el.get("fit", "contain"))
    elif el.get("type") == "shape":
        pil = render_shape(el)
    else:
        pil = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    entry = (image_utils.convert_pil_image_to_skia_image(pil), np.asarray(pil.convert("RGBA"))[..., 3] / 255.0)
    _lru_put(_IMG_CACHE, key, entry)
    return entry


def _paint_alpha(el):
    a = float(el.get("opacity", 1.0))
    if el.get("type") == "shape":
        a *= _rgba(el.get("fill_color"), default=(0, 0, 0, 1.0))[3]
    return a


def _text_element(el):
    """Build cr_renderer TextElement exactly as convert_chameleon_to_crello + _render_to_surface do."""
    from cr_renderer import text_utils as TU
    from cr_renderer.schema import TextElement
    from renderer.converter.convert import _append_text
    keys = ["text", "font_size", "font", "line_height", "text_align", "capitalize", "letter_spacing", "font_bold",
            "font_italic", "text_color", "text_line"]
    out = {k: [] for k in keys}
    _append_text(out, el, _renderer().font_manager)
    te = TextElement(uuid="", type="textElement", width=float(el.get("width", 1.0)), height=float(el.get("height", 1.0)),
                     text=str(out["text"][0]), fontSize=float(out["font_size"][0]), font=str(out["font"][0]),
                     lineHeight=float(out["line_height"][0]), textAlign=str(out["text_align"][0]),
                     capitalize=bool(out["capitalize"][0]), letterSpacing=float(out["letter_spacing"][0]),
                     boldMap=TU.generate_map(out["font_bold"][0]), italicMap=TU.generate_map(out["font_italic"][0]),
                     colorMap=TU.generate_map(out["text_color"][0]), lineMap=TU.generate_map(out["text_line"][0]))
    return te, out["text"][0]


def _draw(design, assets_dir, include_text=True, include_nontext=True, transparent=False, offset=(0, 0), size=None,
          only=None):
    """Replica of cr_renderer._render_to_surface at scale 1 (no PNG round-trip). Returns HxWx4 uint8 (unpremul)."""
    import skia
    from cr_renderer import text_utils as TU
    W = int(round(design["canvas"]["width"])) if size is None else size[0]
    H = int(round(design["canvas"]["height"])) if size is None else size[1]
    surface = skia.Surface(max(1, W), max(1, H))
    fm = _renderer().font_manager
    with surface as canvas:
        if not transparent:
            canvas.clear(skia.ColorWHITE)
        canvas.translate(-offset[0], -offset[1])
        for el in sorted(design["elements"], key=lambda e: e.get("z_index", 0)):
            if only is not None and el.get("id") not in only:
                continue
            is_text = el.get("type") == "text"
            if (is_text and not include_text) or (not is_text and not include_nontext):
                continue
            with skia.AutoCanvasRestore(canvas):
                canvas.translate(float(el.get("x", 0.0)), float(el.get("y", 0.0)))
                ang = float(el.get("rotation", 0.0) or 0.0)
                if ang != 0.0:
                    canvas.rotate(ang, float(el.get("width", 1.0)) / 2.0, float(el.get("height", 1.0)) / 2.0)
                if is_text:
                    te, _ = _text_element(el)
                    TU.render_text(canvas, fm, te)
                else:
                    img, _a = _image_entry(el, assets_dir)
                    paint = skia.Paint(Alphaf=_paint_alpha(el), AntiAlias=True)
                    canvas.drawImageRect(img, skia.Rect(img.width(), img.height()),
                                         skia.Rect(float(el.get("width", 1.0)), float(el.get("height", 1.0))), paint=paint)
    return surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType)


# ----------------------------------------------------------------------------------------------- per-element geometry
def _wrap_lines(el):
    from renderer.converter.convert import _normalize_weight, _weight_style_to_font_style, _BOLD_WEIGHTS, _is_italic
    from renderer.converter.wrap import char_widths, wrap_text
    content = str(el.get("content", ""))
    weight = _normalize_weight(el.get("font_weight"))
    style = _weight_style_to_font_style(weight in _BOLD_WEIGHTS, _is_italic(el.get("font_style") or el.get("italic")))
    fs = float(el.get("font_size", 24))
    widths = char_widths(_renderer().font_manager, el.get("font_family", "Montserrat"), weight, style, fs, content)
    lines = wrap_text(content, widths, float(el.get("width", 1.0))).split("\n")
    lw, off = [], 0
    for ln in lines:
        lw.append(sum(widths[off:off + len(ln)]) + float(el.get("letter_spacing", 0.0) or 0.0) * len(ln))
        off += len(ln) + 1
    return lines, lw


def _metrics(el):
    import skia
    from renderer.converter.convert import _normalize_weight, _weight_style_to_font_style, _BOLD_WEIGHTS, _is_italic
    weight = _normalize_weight(el.get("font_weight"))
    style = _weight_style_to_font_style(weight in _BOLD_WEIGHTS, _is_italic(el.get("font_style") or el.get("italic")))
    tf = skia.Typeface.MakeFromData(_renderer().font_manager.lookup(el.get("font_family", "Montserrat"), weight, style))
    m = skia.Font(tf, int(float(el.get("font_size", 24)))).getMetrics()
    return {"cap": float(m.fCapHeight), "xh": float(m.fXHeight)}


def _text_solo(el, W, H):
    """Glyph mask (canvas coords, bool HxW) + core mask + geometry facts; cropped render, cached by element+canvas."""
    key = (W, H, json.dumps(el, sort_keys=True, default=str))
    hit = _TXT_CACHE.get(key)
    if hit is not None:
        _STATS["txt_hit"] += 1
        _TXT_CACHE.move_to_end(key)
        return hit
    _STATS["txt_miss"] += 1
    fs = float(el.get("font_size", 24))
    lh = float(el.get("line_height", 1.2) or 1.2)
    lines, lw = _wrap_lines(el)
    bw = float(el.get("width", 1.0))
    maxw = max(lw) if lw else 0.0
    align = el.get("text_align", "left")
    over = max(0.0, maxw - bw)
    left_ext = over if align == "right" else (over / 2 if align == "center" else 0.0)
    x0 = float(el["x"]) - left_ext - fs
    y0 = float(el["y"]) - fs
    w_reg = bw + over + 2 * fs + 2
    h_reg = len(lines) * fs * lh + 2 * fs + 2
    rotated = abs(float(el.get("rotation", 0.0) or 0.0)) > 0.01
    if rotated:                                    # rare: render on a padded full canvas
        pad = int(max(W, H) * 0.25)
        arr = _draw({"canvas": {"width": W, "height": H}, "elements": [el]}, None, include_nontext=False,
                    transparent=True, offset=(-pad, -pad), size=(W + 2 * pad, H + 2 * pad))
        ox, oy = -pad, -pad
    else:
        ox, oy = int(math.floor(x0)), int(math.floor(y0))
        arr = _draw({"canvas": {"width": W, "height": H}, "elements": [el]}, None, include_nontext=False,
                    transparent=True, offset=(ox, oy), size=(int(math.ceil(w_reg)) + 2, int(math.ceil(h_reg)) + 2))
    a = arr[..., 3]
    ink_total = int((a > MASK_ALPHA).sum())
    mask = np.zeros((H, W), bool)
    core = np.zeros((H, W), bool)
    ys0, xs0 = max(0, oy), max(0, ox)
    ys1, xs1 = min(H, oy + a.shape[0]), min(W, ox + a.shape[1])
    if ys1 > ys0 and xs1 > xs0:
        sub = a[ys0 - oy:ys1 - oy, xs0 - ox:xs1 - ox]
        mask[ys0:ys1, xs0:xs1] = sub > MASK_ALPHA
        core[ys0:ys1, xs0:xs1] = sub > 200
    res = {"mask": mask, "core": core, "ink_total": ink_total, "ink_in": int(mask.sum()), "lines": lines, "lw": lw,
           "bottom": float(el["y"]) + len(lines) * fs * lh, "over_x": over, "x_left": float(el["x"]) - left_ext,
           "x_right": float(el["x"]) - left_ext + max(bw, maxw)}
    _lru_put(_TXT_CACHE, key, res)
    return res


def _nontext_mask(el, W, H, assets_dir):
    """Effective alpha (float HxW) of an image/shape in canvas coords; rotated ones via a padded skia draw."""
    eff = _paint_alpha(el)
    out = np.zeros((H, W), np.float32)
    clip = 0.0
    if eff <= 0.0:
        return out, 0.0
    if abs(float(el.get("rotation", 0.0) or 0.0)) > 0.01:
        pad = int(max(W, H) * 0.5)
        arr = _draw({"canvas": {"width": W, "height": H}, "elements": [dict(el, opacity=1.0)]}, assets_dir,
                    include_text=False, transparent=True, offset=(-pad, -pad), size=(W + 2 * pad, H + 2 * pad))
        a = arr[..., 3] / 255.0 * eff
        tot = float((a > 0.15).sum())
        inside = a[pad:pad + H, pad:pad + W]
        clip = 0.0 if tot == 0 else 1.0 - float((inside > 0.15).sum()) / tot
        return inside.astype(np.float32), clip
    _img, alpha = _image_entry(el, assets_dir)
    x, y = int(round(float(el.get("x", 0)))), int(round(float(el.get("y", 0))))
    h, w = alpha.shape
    ys0, xs0, ys1, xs1 = max(0, y), max(0, x), min(H, y + h), min(W, x + w)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = alpha[ys0 - y:ys1 - y, xs0 - x:xs1 - x] * eff
    return out, 0.0


# ----------------------------------------------------------------------------------------------- pixel measures
def _lum(rgb):
    c = rgb.astype(np.float64) / 255.0
    lin = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def _dilate(m, k):
    if k <= 0:
        return m
    out = m.copy()
    for _ in range(k):               # 3x3 max filter iterated k times (cross-shaped growth is enough here)
        g = out.copy()
        g[1:, :] |= out[:-1, :]
        g[:-1, :] |= out[1:, :]
        g[:, 1:] |= out[:, :-1]
        g[:, :-1] |= out[:, 1:]
        out = g
    return out


def _bbox(m):
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _text_pixels(full, under, solo, el):
    """Observed contrast (rendered glyph colour vs backdrop) and busyness of the backdrop ring around the glyphs."""
    core = solo["core"] if solo["core"].any() else solo["mask"]
    if not core.any():
        return None, None
    bb = _bbox(solo["mask"])
    fs = float(el.get("font_size", 24))
    k = max(2, int(round(fs * 0.15)))
    x0, y0, x1, y1 = bb
    x0, y0 = max(0, x0 - k - 1), max(0, y0 - k - 1)
    x1, y1 = min(full.shape[1], x1 + k + 1), min(full.shape[0], y1 + k + 1)
    m = solo["mask"][y0:y1, x0:x1]
    c = core[y0:y1, x0:x1]
    U = under[y0:y1, x0:x1, :3]
    F = full[y0:y1, x0:x1, :3]
    tl, bl = _lum(F[c]), _lum(U[c])
    cr = (np.maximum(tl, bl) + 0.05) / (np.minimum(tl, bl) + 0.05)
    ring = _dilate(m, k) & ~m
    g = U.astype(np.float32).mean(-1)
    gy, gx = np.gradient(g)
    edges = np.hypot(gx, gy) > EDGE_GRAD
    busy = float(edges[ring].mean()) if ring.any() else 0.0
    return float(np.percentile(cr, 10)), busy


# ----------------------------------------------------------------------------------------------- analysis
def _fallback_roles(design):
    """Minimal id-free role guess when info has no roles (never used by the engine; keeps the critic usable alone)."""
    cw, ch = design["canvas"]["width"], design["canvas"]["height"]
    els = design["elements"]
    roles = {}
    zmin = min((e.get("z_index", 0) for e in els), default=0)
    texts = [e for e in els if e.get("type") == "text"]
    top = max((float(e.get("font_size", 0)) * (1.15 if e.get("font_weight") == "bold" else 1) for e in texts), default=0)
    for e in els:
        t, area = e.get("type"), float(e.get("width", 0)) * float(e.get("height", 0))
        if t != "text" and area >= 0.85 * cw * ch and e.get("z_index", 0) == zmin:
            roles[e["id"]] = "background"
        elif t == "shape" and not e.get("group_id") and (_paint_alpha(e) < 0.5):
            roles[e["id"]] = "decoration"
        elif t == "text":
            f = float(e.get("font_size", 0)) * (1.15 if e.get("font_weight") == "bold" else 1)
            roles[e["id"]] = "headline" if f >= top - 1e-6 else ("cta_label" if e.get("group_id") else "body")
        elif t == "shape":
            roles[e["id"]] = "cta_shape" if e.get("group_id") else "panel"
        else:
            roles[e["id"]] = "unknown"
    return roles


def _analyse(design, roles, assets_dir, hidden_ids):
    W, H = int(round(design["canvas"]["width"])), int(round(design["canvas"]["height"]))
    t0 = time.perf_counter()
    under = _draw(design, assets_dir, include_text=False)
    full = _draw(design, assets_dir)
    t_render = time.perf_counter() - t0
    els = sorted(design["elements"], key=lambda e: e.get("z_index", 0))
    order = {e["id"]: i for i, e in enumerate(els)}
    occl = {}     # cumulative opaque coverage ABOVE each element (stable z order)
    nontext = {}
    above = np.zeros((H, W), bool)
    clip = {}
    for e in reversed(els):
        occl[e["id"]] = above.copy() if e.get("type") == "text" or True else None
        if e.get("type") != "text":
            a, c = _nontext_mask(e, W, H, assets_dir)
            nontext[e["id"]] = a
            clip[e["id"]] = c
            above |= a >= OCCLUDER_ALPHA
    per = {}
    for e in design["elements"]:
        i = e["id"]
        r = roles.get(i, "unknown")
        if e.get("type") == "text":
            solo = _text_solo(e, W, H)
            colour_a = _rgba(e.get("color"))[3]
            vis_mask = solo["mask"] & ~occl[i]
            per[i] = {"type": "text", "role": r, "solo": solo, "mask": vis_mask, "px": int(vis_mask.sum()), "raw": solo["mask"],
                      "alpha_colour": colour_a, "visible": int(vis_mask.sum()) >= 5,
                      "fs": float(e.get("font_size", 24))}
            if per[i]["visible"]:
                cr, busy = _text_pixels(full, under, dict(solo, mask=vis_mask, core=solo["core"] & vis_mask), e)
                per[i].update(contrast=cr, busy=busy, **_metrics(e))
        else:
            a = nontext[i]
            m = (a > 0.15) & ~occl[i]
            per[i] = {"type": e.get("type"), "role": r, "mask": m, "px": int(m.sum()), "visible": int(m.sum()) >= 5, "raw": a > 0.15,
                      "clip": clip.get(i, 0.0), "alpha": a}
    return {"W": W, "H": H, "under": under, "full": full, "per": per, "t_render": t_render, "order": order}


def _src_analysis(source, roles, assets_dir):
    key = hashlib.sha1((json.dumps(source, sort_keys=True, default=str) + assets_dir).encode()).hexdigest()
    hit = _SRC_CACHE.get(key)
    if hit is not None:
        _STATS["src_hit"] += 1
        return hit
    _STATS["src_miss"] += 1
    a = _analyse(source, roles, assets_dir, [])
    _lru_put(_SRC_CACHE, key, a)
    return a


def _judge_scale(W, H):
    return min(1.0, JUDGE_LONG_SIDE / float(max(W, H)))


# ----------------------------------------------------------------------------------------------- main entry
def critique(source, output, info, render_png_path=None):
    t0 = time.perf_counter()
    try:
        return _critique(source, output, info or {}, render_png_path, t0)
    except Exception as exc:  # never raise
        return {"vetoes": [], "penalty": 0.0,
                "features": {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=4),
                             "ms": round((time.perf_counter() - t0) * 1000, 1)}}


def _veto(code, ids, detail):
    return {"code": code, "ids": list(ids), "detail": detail}


def _crash_risks(output):
    """Outputs the OFFICIAL renderer would crash on (pydantic gt=0 on text w/h, unparsable colours, NaN)."""
    import re
    bad = []
    ok_col = re.compile(r"^\s*rgba?\(")
    for e in output.get("elements", []):
        try:
            nums = [float(e.get(k, 0)) for k in ("x", "y", "width", "height")]
            if any(not math.isfinite(v) for v in nums):
                bad.append((e.get("id"), "non-finite geometry"))
            if e.get("type") == "text":
                if float(e.get("width", 0)) <= 0 or float(e.get("height", 0)) <= 0:
                    bad.append((e.get("id"), "text width/height <= 0"))
                cols = [e.get("color")] + [r.get("color") for r in (e.get("style_runs") or []) if "color" in r]
                if any(c is not None and not ok_col.match(str(c)) for c in cols):
                    bad.append((e.get("id"), "non-rgba colour string"))
        except Exception:
            bad.append((e.get("id"), "unparsable element"))
    return bad


def _critique(source, output, info, render_png_path, t0):
    crash = _crash_risks(output)
    if crash:
        return {"vetoes": [_veto("RENDER_CRASH", [i], d) for i, d in crash], "penalty": 0.0,
                "features": {"note": "official renderer would crash; pixel checks skipped",
                             "ms": round((time.perf_counter() - t0) * 1000, 1)}}
    assets_dir = _assets_dir(info)
    roles = dict(_fallback_roles(source))
    roles.update(info.get("roles") or {})
    hidden = set(info.get("hidden") or [])
    groups = {}
    for e in output["elements"]:
        if e.get("group_id"):
            groups.setdefault(e["group_id"], set()).add(e["id"])
    for g, ids in (info.get("groups") or {}).items():
        groups.setdefault(g, set()).update(ids)
    gid = {i: g for g, ids in groups.items() for i in ids}
    host_of = {}
    for host, riders in (info.get("containers") or {}).items():
        for rd in riders:
            host_of[rd] = host

    S = _src_analysis(source, roles, assets_dir)
    O = _analyse(output, roles, assets_dir, hidden)
    if render_png_path:
        try:
            from PIL import Image
            png = np.asarray(Image.open(render_png_path).convert("RGBA"))
            if png.shape[0] == O["H"] and png.shape[1] == O["W"]:
                O["full"] = png
        except Exception:
            pass
    W, H = O["W"], O["H"]
    js_out, js_src = _judge_scale(W, H), _judge_scale(S["W"], S["H"])
    E = {e["id"]: e for e in output["elements"]}
    SE = {e["id"]: e for e in source["elements"]}
    vetoes, pen, feats = [], {}, {"per_text": {}, "collisions": [], "near_collisions": []}

    def add_pen(k, v):
        pen[k] = pen.get(k, 0.0) + float(v)

    # ---- per element checks
    head_cap = None
    heads = [i for i, r in roles.items() if r == "headline" and O["per"].get(i, {}).get("visible")]
    if heads:
        head_cap = max(O["per"][i].get("cap", 0.0) for i in heads)
    for i, p in O["per"].items():
        e, r, sp = E[i], p["role"], S["per"].get(i, {})
        intended_hidden = (i in hidden or float(e.get("opacity", 1.0)) <= 0.01
                           or (e.get("type") == "text" and p.get("alpha_colour", 1.0) <= 0.01))
        if intended_hidden:
            if p["px"] >= LEAK_MIN_PX:
                vetoes.append(_veto("HIDDEN_LEAK", [i], f"{p['px']} px of an intended-hidden {e.get('type')} still render"))
            continue
        if e.get("type") == "image" and p["visible"]:
            from renderer.converter.assets import asset_path
            if e.get("asset_id") and asset_path(assets_dir, e.get("asset_id")) is None:
                vetoes.append(_veto("PLACEHOLDER", [i], f"missing asset '{e.get('asset_id')}' renders a grey placeholder"))
        if e.get("type") != "text" and p.get("clip", 0.0) > CLIP_FRAC:
            vetoes.append(_veto("CLIPPED", [i], f"{p['clip']:.0%} of the rotated ink is outside the canvas"))
        if e.get("type") != "text" or not p["visible"]:
            continue
        solo = p["solo"]
        fs = p["fs"]
        tf = {"contrast_p10": p.get("contrast"), "busy": p.get("busy"), "judge_px": round(int(fs) * js_out, 1),
              "lines": len(solo["lines"]), "cap": p.get("cap")}
        feats["per_text"][i] = tf
        # clipped / overflowing ink
        if solo["bottom"] > H + 1:
            vetoes.append(_veto("CLIPPED", [i], f"text runs {solo['bottom'] - H:.0f}px below the canvas"))
        if solo["x_left"] < -1 or solo["x_right"] > W + 1:
            vetoes.append(_veto("CLIPPED", [i], "text ink runs past the canvas side"))
        if solo["over_x"] > 2:
            vetoes.append(_veto("TEXT_OVERFLOW", [i], f"a word is {solo['over_x']:.0f}px wider than its box"))
        box_over = solo["bottom"] - (float(e["y"]) + float(e["height"]))
        if box_over > 0.5 * fs:
            add_pen("box_overflow", 1.0)
        # legibility (judge pixels), source-relative floor
        floor = FLOOR_PX.get(r, DEFAULT_FLOOR_PX)
        if i in SE and sp.get("visible"):
            floor = min(floor, 0.9 * int(float(SE[i].get("font_size", 24))) * js_src)
        if int(fs) * js_out < ILLEGIBLE_VETO * floor - 1e-6:
            vetoes.append(_veto("ILLEGIBLE", [i], f"{int(fs) * js_out:.1f} judge-px < {ILLEGIBLE_VETO} x floor {floor:.1f} ({r})"))
        elif int(fs) * js_out < 1.25 * floor:
            add_pen("small_text", (1.25 * floor - int(fs) * js_out) / floor)
        # contrast vs the source's own contrast for this text
        c, cs = p.get("contrast"), sp.get("contrast")
        if c is not None:
            large = int(fs) * js_out >= 18
            need = min(3.0 if large else 4.5, cs if cs is not None else 4.5)
            guard = LOST_BACKDROP_GUARD if large else LOST_BACKDROP_GUARD_SMALL
            if c < LOST_BACKDROP_ABS or (c < LOST_BACKDROP_DEFICIT * need and c < guard) or \
                    (cs is not None and c < LOST_BACKDROP_RATIO * cs and c < guard):
                vetoes.append(_veto("LOST_BACKDROP", [i], f"contrast p10 {c:.2f} vs source {cs if cs is None else round(cs, 2)}"))
            elif cs is not None:
                add_pen("contrast", max(0.0, min(4.5, 0.95 * cs) - c))
        # busy backdrop vs the source's own backdrop for this text
        b, bs = p.get("busy"), sp.get("busy")
        if b is not None:
            base = bs if bs is not None else 0.05
            if b > BUSY_VETO_ABS and b > BUSY_VETO_REL * base + BUSY_VETO_ADD:
                vetoes.append(_veto("BUSY_BACKDROP", [i], f"glyph-ring edge density {b:.2f} vs source {base:.2f}"))
            else:
                add_pen("busy", 5.0 * max(0.0, b - base - 0.05))
        # typography
        if r == "headline" and len(solo["lines"]) > 1 and min(len(ln.split()) for ln in solo["lines"]) < 2:
            add_pen("one_word_line", 2.0)
        if head_cap and r not in ("headline", "legal") and p.get("cap", 0) > 1.10 * head_cap:
            add_pen("hierarchy", 3.0)

    # ---- spill: riders / group labels must stay inside their host or group shape
    for i, p in O["per"].items():
        if p["type"] != "text" or not p["visible"]:
            continue
        host = host_of.get(i)
        if host is None and gid.get(i):
            shapes = [j for j in groups[gid[i]] if j in E and E[j].get("type") == "shape" and O["per"][j]["visible"]]
            host = shapes[0] if shapes else None
        if host is None or host not in O["per"] or not O["per"][host]["visible"]:
            continue
        hm = _dilate(O["per"][host]["alpha"] > 0.15, 1)
        out_frac = float((p["mask"] & ~hm).sum()) / max(1, p["px"])
        src_frac = 0.0
        if i in S["per"] and host in S["per"] and S["per"][i].get("visible") and S["per"][host].get("visible"):
            shm = _dilate(S["per"][host]["alpha"] > 0.15, 1)
            src_frac = float((S["per"][i]["mask"] & ~shm).sum()) / max(1, S["per"][i]["px"])
        if out_frac > SPILL_FRAC and out_frac > src_frac + SPILL_FRAC:
            vetoes.append(_veto("SPILL", [i, host], f"{out_frac:.0%} of the label/rider ink is outside its host"))

    # ---- ink collisions between flow elements (relation-aware, source-relative)
    flow = [i for i, p in O["per"].items() if p["visible"] and p["role"] not in NON_FLOW
            and not (i in hidden or float(E[i].get("opacity", 1.0)) <= 0.01)]
    for a_i in range(len(flow)):
        for b_i in range(a_i + 1, len(flow)):
            a, b = flow[a_i], flow[b_i]
            if gid.get(a) and gid.get(a) == gid.get(b):
                continue
            if host_of.get(a) == b or host_of.get(b) == a:
                continue
            ov = int((O["per"][a]["raw"] & O["per"][b]["raw"]).sum())     # drawn ink: an occluding pill still collides
            if ov == 0:
                continue
            sa, sb = S["per"].get(a, {}), S["per"].get(b, {})
            if sa.get("visible") and sb.get("visible") and int((sa["raw"] & sb["raw"]).sum()) > COLLISION_MIN_PX:
                continue                  # the designer already layered these two: intent, not a defect
            smaller = max(1, min(int(O["per"][a]["raw"].sum()), int(O["per"][b]["raw"].sum())))
            rec = {"ids": [a, b], "px": ov, "frac": round(ov / smaller, 4)}
            if ov >= max(COLLISION_MIN_PX, COLLISION_FRAC * smaller):
                feats["collisions"].append(rec)
                vetoes.append(_veto("INK_COLLISION", [a, b], f"{ov} px ({ov / smaller:.1%} of the smaller ink) overlap"))
            else:
                feats["near_collisions"].append(rec)
                add_pen("near_collision", 1.0)

    # ---- under-fill relative to the source (content block share), cramped edges
    def content_share(A, ids):
        m = np.zeros((A["H"], A["W"]), bool)
        for j in ids:
            if j in A["per"] and A["per"][j]["visible"] and A["per"][j]["role"] not in NON_FLOW:
                m |= A["per"][j]["mask"]
        bb = _bbox(m)
        return 0.0 if bb is None else (bb[2] - bb[0]) * (bb[3] - bb[1]) / float(A["W"] * A["H"])
    r_fill = content_share(O, flow) / max(1e-6, content_share(S, list(S["per"].keys())))
    feats["fill_ratio_vs_source"] = round(r_fill, 3)
    if r_fill < 0.6:
        add_pen("underfill", 10.0 * (0.6 - r_fill))
    short = min(W, H)
    for i in flow:
        bb = _bbox(O["per"][i]["mask"])
        if bb and min(bb[0], bb[1], W - bb[2], H - bb[3]) < 0.01 * short:
            sbb = _bbox(S["per"][i]["mask"]) if i in S["per"] and S["per"][i]["visible"] else None
            if not sbb or min(sbb[0], sbb[1], S["W"] - sbb[2], S["H"] - sbb[3]) >= 0.01 * min(S["W"], S["H"]):
                add_pen("edge_touch", 0.5)

    penalty = round(sum(pen.values()), 3)
    feats["penalty_terms"] = {k: round(v, 3) for k, v in pen.items()}
    feats["n_vetoes"] = len(vetoes)
    feats["render_ms"] = round(O["t_render"] * 1000, 1)
    feats["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    feats["cache"] = dict(_STATS)
    return {"vetoes": vetoes, "penalty": penalty, "features": feats}
