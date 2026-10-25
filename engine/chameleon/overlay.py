"""overlay.py -- calm live areas on a full-bleed background photo (owner: INVENTOR).

Public interface (see round3/SPEC_v1.md, stage 2b "OVERLAY live areas"):

    calm_regions(source, target_canvas, info=None, assets_dir="brand_kit/assets")
        -> list[(x, y, w, h, score)]          # target-canvas px, best first, score in (0, 1]

    busy_ratio(source, target_canvas, boxes, info=None, assets_dir="brand_kit/assets")
        -> list[float] | None                 # per box: busyness / designer's tolerance (<=1 good)

Semantics
---------
* The background is the element `info["bg_id"]` if given, else the lowest-z image covering
  >= 85 % of the source canvas.  At the target it is drawn full-canvas, so we emulate EXACTLY
  what the renderer draws there (renderer.converter.assets.load_asset_image: cover = scale to
  fill + centre crop; contain = letterbox; fill = stretch).
* Busyness = box-blurred luminance-gradient energy in canvas-pixel units (window ~ glyph size).
* The calm threshold is SOURCE-RELATIVE: 1.5 x the 90th-percentile busyness under the designer's
  own free-standing text in the source (text on an opaque shape/pill is excluded -- the shape is
  its backdrop).  What the designer accepted under type is, by definition, calm enough.
* Calm cells form a grid; maximal all-calm rectangles (overall + per half) are returned as
  candidate live areas for the galley.  score = sqrt(area share) * (1 - mean busy / threshold).

Return conventions (never raises):
* no photo background (no bg, a shape, or a non-cover/flat image) -> [(0, 0, W, H, 1.0)]
* photo present but nothing is calm                                   -> []
* any error / unresolvable asset                                       -> []
  (callers that need to tell "nothing calm" from "error" can call `analyze()`, which returns a
  dict with "status": "no_photo" | "ok" | "none_calm" | "error", plus the regions and threshold.)

Cost: busy maps are cached per (asset, mtime, fit, W, H); a cold call is ~20-80 ms, warm <5 ms.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

ANALYSIS_LONG_SIDE = 640      # analysis resolution (canvas px are rescaled to this long side)
TOL_MULT = 1.5                # calm threshold = TOL_MULT x designer tolerance
ABS_FLOOR = 0.006             # never stricter than this (busy units: luminance-gradient / 255 per px)
GRID_LONG = 40                # calm-grid cells along the long side
MIN_AREA_SHARE = 0.06         # ignore calm rectangles smaller than this share of the canvas
_REPO = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------------------- public
def calm_regions(source, target_canvas, info=None, assets_dir="brand_kit/assets"):
    try:
        return analyze(source, target_canvas, info, assets_dir)["regions"]
    except Exception:  # noqa: BLE001 -- contract: never raise
        return []


def busy_ratio(source, target_canvas, boxes, info=None, assets_dir="brand_kit/assets"):
    """Mean busyness under each (x0, y0, x1, y1) box divided by the designer's tolerance."""
    try:
        a = analyze(source, target_canvas, info, assets_dir, want_map=True)
        if a["status"] in ("no_photo",):
            return [0.0 for _ in boxes]
        if a["status"] == "error":
            return None
        m, k, tol = a["_map"], a["_k"], a["tolerance"]
        return [float(_mean_in(m, [v * k for v in b]) / tol) for b in boxes]
    except Exception:  # noqa: BLE001
        return None


def analyze(source, target_canvas, info=None, assets_dir="brand_kit/assets", want_map=False):
    W, H = int(target_canvas["width"]), int(target_canvas["height"])
    out = {"status": "error", "regions": [], "tolerance": None, "threshold": None, "calm_share": 0.0}
    try:
        bg = _find_bg(source, info)
        if bg is None or bg.get("type") != "image":
            out.update(status="no_photo", regions=[(0.0, 0.0, float(W), float(H), 1.0)])
            return out
        path = _asset_path(assets_dir, bg.get("asset_id"))
        if path is None:
            return out                                   # unresolvable asset: we know nothing
        fit = bg.get("fit", "contain")
        # source side: designer's tolerance
        sw, sh = max(1, int(round(bg["width"]))), max(1, int(round(bg["height"])))
        smap, sk = _busy_map(str(path), path.stat().st_mtime, fit, sw, sh)
        vals = []
        for b in _free_text_boxes(source, info):
            bb = (b[0] - bg["x"], b[1] - bg["y"], b[2] - bg["x"], b[3] - bg["y"])
            vals.append(_mean_in(smap, [v * sk for v in bb]))
        tol = max(float(np.percentile(vals, 90)) if vals else ABS_FLOOR, ABS_FLOOR / TOL_MULT)
        thr = max(TOL_MULT * tol, ABS_FLOOR)
        # target side: what the renderer will draw full-canvas
        tmap, tk = _busy_map(str(path), path.stat().st_mtime, fit, W, H)
        if float(np.percentile(tmap, 98)) <= thr:        # calm everywhere -> behaves like no photo
            out.update(status="ok", regions=[(0.0, 0.0, float(W), float(H), 1.0)], tolerance=tol, threshold=thr, calm_share=1.0)
        else:
            regs, share = _calm_rects(tmap, tk, thr, W, H)
            if share >= 0.85:      # mostly calm (scattered specks): the whole canvas is a fine live area;
                regs = [(0.0, 0.0, float(W), float(H), round(share, 4))] + regs   # busy_ratio() checks placements
            out.update(status="ok" if regs else "none_calm", regions=regs, tolerance=tol, threshold=thr, calm_share=share)
        if want_map:
            out.update(_map=tmap, _k=tk)
        return out
    except Exception as ex:  # noqa: BLE001
        out["error"] = f"{type(ex).__name__}: {ex}"
        return out


def ground(source, target_canvas, info=None, assets_dir="brand_kit/assets"):
    """Photo ground for text placement: (luminance map 0..1, busy map, k, tolerance) at the busy map's analysis
    resolution, or None when there is no photo background (then nothing needs nudging)."""
    try:
        W, H = int(target_canvas["width"]), int(target_canvas["height"])
        bg = _find_bg(source, info)
        if bg is None or bg.get("type") != "image":
            return None
        path = _asset_path(assets_dir, bg.get("asset_id"))
        if path is None:
            return None
        a = analyze(source, target_canvas, info, assets_dir, want_map=True)
        if a.get("status") in ("no_photo", "error") or "_map" not in a:
            return None
        im = _render_bg_analysis(str(path), bg.get("fit", "contain"), W, H, a["_map"].shape[1], a["_map"].shape[0])
        arr = np.asarray(im, dtype=np.float32)[..., :3] / 255.0
        c = np.where(arr <= 0.03928, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)
        lum = c @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        return lum, a["_map"], a["_k"], a["tolerance"]
    except Exception:  # noqa: BLE001
        return None


def text_cost(gr, box, text_lum):
    """Cost of text of relative luminance `text_lum` on `box` (canvas px): busyness over the designer's tolerance
    plus a contrast deficit against the 10th-percentile-worst ground (WCAG ratio, 3:1 wanted)."""
    lum, busy, k, tol = gr
    h, w = lum.shape
    x0, y0, x1, y1 = [int(round(v * k)) for v in box]
    x0, y0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
    x1, y1 = min(w, max(x0 + 1, x1)), min(h, max(y0 + 1, y1))
    reg = lum[y0:y1, x0:x1].ravel()
    ratios = (np.maximum(reg, text_lum) + 0.05) / (np.minimum(reg, text_lum) + 0.05)
    worst = float(np.percentile(ratios, 10))
    return float(busy[y0:y1, x0:x1].mean() / max(tol, 1e-6)) + 3.0 * max(0.0, 1.0 - worst / 3.0)


# ----------------------------------------------------------------------------- internals
def _find_bg(source, info):
    els = source.get("elements", [])
    if info and info.get("bg_id") is not None:
        for e in els:
            if e.get("id") == info["bg_id"]:
                return e
    W0, H0 = source["canvas"]["width"], source["canvas"]["height"]
    cands = []
    for e in els:
        if e.get("type") not in ("image", "shape"):
            continue
        cx = max(0, min(e["x"] + e["width"], W0) - max(e["x"], 0))
        cy = max(0, min(e["y"] + e["height"], H0) - max(e["y"], 0))
        if cx * cy >= 0.85 * W0 * H0 and float(e.get("opacity", 1)) > 0.5:
            cands.append(e)
    return min(cands, key=lambda e: e.get("z_index", 0)) if cands else None


def _asset_path(assets_dir, asset_id):
    if not asset_id:
        return None
    for base in (Path(assets_dir), _REPO / assets_dir):
        p = base / str(asset_id)
        if p.is_file():
            return p
    return None


@lru_cache(maxsize=8)
def _decoded(path, mtime):
    return Image.open(path).convert("RGBA")


def _render_bg(path, fit, w, h):
    """Exactly the pixels the renderer draws for this element at w x h
    (same arithmetic as renderer/converter/assets._fit_image; decoded asset cached)."""
    src = _decoded(str(path), Path(path).stat().st_mtime)
    w, h = max(1, round(w)), max(1, round(h))
    if fit == "cover":
        s = max(w / src.width, h / src.height)
        nw, nh = max(1, round(src.width * s)), max(1, round(src.height * s))
        r = src.resize((nw, nh), Image.LANCZOS)
        l, t = (nw - w) // 2, (nh - h) // 2
        return r.crop((l, t, l + w, t + h))
    if fit == "contain":
        s = min(w / src.width, h / src.height)
        nw, nh = max(1, round(src.width * s)), max(1, round(src.height * s))
        r = src.resize((nw, nh), Image.LANCZOS)
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        im.paste(r, ((w - nw) // 2, (h - nh) // 2), r)
        return im
    return src.resize((w, h), Image.LANCZOS)


def _render_bg_analysis(path, fit, w, h, aw, ah):
    """Same geometry as _render_bg (renderer-exact crop/letterbox), resampled straight to the
    analysis resolution: avoids a full-size LANCZOS pass on big photos (cold cost ~5x lower)."""
    src = _decoded(str(path), Path(path).stat().st_mtime)
    w, h = max(1, round(w)), max(1, round(h))
    kx, ky = aw / w, ah / h
    if fit == "cover":
        s = max(w / src.width, h / src.height)
        nw, nh = max(1, round(src.width * s)), max(1, round(src.height * s))
        l, t = (nw - w) // 2, (nh - h) // 2
        box = (l * src.width / nw, t * src.height / nh, (l + w) * src.width / nw, (t + h) * src.height / nh)
        return src.resize((aw, ah), Image.BILINEAR, box=box, reducing_gap=2.0)
    if fit == "contain":
        s = min(w / src.width, h / src.height)
        nw, nh = max(1, round(src.width * s)), max(1, round(src.height * s))
        r = src.resize((max(1, round(nw * kx)), max(1, round(nh * ky))), Image.BILINEAR, reducing_gap=2.0)
        im = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
        im.paste(r, (round((w - nw) // 2 * kx), round((h - nh) // 2 * ky)), r)
        return im
    return src.resize((aw, ah), Image.BILINEAR, reducing_gap=2.0)


@lru_cache(maxsize=64)
def _busy_map(path, mtime, fit, w, h):
    """-> (busy map at analysis resolution, k = analysis px per canvas px)."""
    k = min(1.0, ANALYSIS_LONG_SIDE / max(w, h))
    aw, ah = max(1, round(w * k)), max(1, round(h * k))
    im = _render_bg_analysis(path, fit, w, h, aw, ah)
    a = np.asarray(im, dtype=np.float32)
    lum = (a[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)) * (a[..., 3] / 255.0)
    gy, gx = np.gradient(lum)
    mag = np.hypot(gx, gy) / 255.0 * k                  # per CANVAS pixel
    win = max(3, int(round(max(3.0, min(w, h) / 40.0) * k)))
    return _box_blur(mag, win), k


def _box_blur(m, k):
    ii = np.pad(m, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    H, W = m.shape
    r = k // 2
    y0 = np.clip(np.arange(H) - r, 0, H); y1 = np.clip(np.arange(H) + r + 1, 0, H)
    x0 = np.clip(np.arange(W) - r, 0, W); x1 = np.clip(np.arange(W) + r + 1, 0, W)
    s = ii[y1][:, x1] - ii[y0][:, x1] - ii[y1][:, x0] + ii[y0][:, x0]
    return s / ((y1 - y0)[:, None] * (x1 - x0)[None, :])


def _mean_in(m, box):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, min(x0, m.shape[1] - 1)), max(0, min(y0, m.shape[0] - 1))
    x1, y1 = min(m.shape[1], max(x0 + 1, x1)), min(m.shape[0], max(y0 + 1, y1))
    return float(m[y0:y1, x0:x1].mean())


def _alpha(c):
    try:
        return float(str(c).split("(")[1].rstrip(")").split(",")[3])
    except (IndexError, ValueError):
        return 1.0


def _free_text_boxes(source, info):
    """Ink boxes of visible text that stands directly on the background (not on a shape)."""
    els = source.get("elements", [])
    src_ink = (info or {}).get("src_ink") or {}
    riders = {r for rs in ((info or {}).get("containers") or {}).values() for r in rs}
    shapes = [e for e in els if e.get("type") == "shape" and float(e.get("opacity", 1)) * _alpha(e.get("fill_color")) >= 0.5]
    boxes = []
    for e in els:
        if e.get("type") != "text" or float(e.get("opacity", 1)) == 0 or _alpha(e.get("color")) == 0:
            continue
        if e.get("id") in riders:
            continue
        if e.get("id") in src_ink:
            x, y, w, h = src_ink[e["id"]]
            box = (x, y, x + w, y + h)
        else:
            box = _estimate_text_ink(e)
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        on_shape = any(s.get("z_index", 0) <= e.get("z_index", 0) and s["x"] <= cx <= s["x"] + s["width"]
                       and s["y"] <= cy <= s["y"] + s["height"] for s in shapes)
        if not on_shape:
            boxes.append(box)
    return boxes


def _estimate_text_ink(e):
    """Renderer-exact when the renderer is importable, else a conservative estimate."""
    fs = max(1, int(e.get("font_size", 12)))
    lh = float(e.get("line_height", 1.2))
    try:
        from renderer.converter.convert import _get_renderer
        from renderer.converter.wrap import char_widths, wrap_text
        fm = _get_renderer(str(_REPO / "brand_kit" / "fonts")).font_manager
        bold = e.get("font_weight") == "bold"
        it = e.get("font_style") == "italic"
        style = "bolditalic" if bold and it else "bold" if bold else "italic" if it else "regular"
        ws = char_widths(fm, e["font_family"], "bold" if bold else "regular", style, fs, e["content"])
        lines = wrap_text(e["content"], ws, float(e["width"])).split("\n")
        widths, i = [], 0
        for ln in lines:
            widths.append(sum(ws[i:i + len(ln)])); i += len(ln) + 1
        mw = max(widths) if widths else 0
    except Exception:  # noqa: BLE001
        n_chars = len(e.get("content", ""))
        mw = min(float(e["width"]), 0.55 * fs * n_chars)
        lines = [0] * max(1, math.ceil(0.55 * fs * n_chars / max(1.0, float(e["width"]))))
    al = e.get("text_align", "left")
    x0 = e["x"] + ((e["width"] - mw) / 2 if al == "center" else (e["width"] - mw) if al == "right" else 0)
    return (x0, e["y"], x0 + mw, e["y"] + len(lines) * fs * lh)


def _max_rect(mask):
    R, C = mask.shape
    h = np.zeros(C, int)
    best = (0, 0, 0, 0, 0)
    for r in range(R):
        h = np.where(mask[r], h + 1, 0)
        st = []
        for c in range(C + 1):
            cur = h[c] if c < C else 0
            start = c
            while st and st[-1][1] >= cur:
                start, hh = st.pop()
                if hh * (c - start) > best[0]:
                    best = (hh * (c - start), start, r - hh + 1, c - start, hh)
            st.append((start, cur))
    return best[1:]


def _calm_rects(m, k, thr, W, H):
    gw = max(4, round(GRID_LONG * W / max(W, H))); gh = max(4, round(GRID_LONG * H / max(W, H)))
    ys = np.linspace(0, m.shape[0], gh + 1).astype(int); xs = np.linspace(0, m.shape[1], gw + 1).astype(int)
    cell = np.array([[m[ys[i]:max(ys[i] + 1, ys[i + 1]), xs[j]:max(xs[j] + 1, xs[j + 1])].max()
                      for j in range(gw)] for i in range(gh)])
    calm = cell <= thr
    share = float(calm.mean())
    regs = []
    halves = [(slice(None), slice(None)), (slice(0, gh // 2 + 1), slice(None)), (slice(gh // 2, None), slice(None)),
              (slice(None), slice(0, gw // 2 + 1)), (slice(None), slice(gw // 2, None))]
    for sy, sx in halves:
        sub = calm[sy, sx]
        if not sub.any():
            continue
        c, r, nc, nr = _max_rect(sub)
        r += sy.start or 0; c += sx.start or 0
        x0, y0 = xs[c] / k, ys[r] / k
        x1, y1 = xs[c + nc] / k, ys[r + nr] / k
        w, h = min(W, x1) - x0, min(H, y1) - y0
        if w * h < MIN_AREA_SHARE * W * H or w < min(120, 0.25 * W) or h < min(40, 0.4 * H):
            continue
        mean = float(cell[r:r + nr, c:c + nc].mean())
        score = math.sqrt(w * h / (W * H)) * max(0.05, 1 - mean / thr)
        regs.append((round(float(x0), 1), round(float(y0), 1), round(float(w), 1), round(float(h), 1), round(float(score), 4)))
    uniq = {}
    for rg in regs:
        uniq.setdefault(rg[:4], rg)
    return sorted(uniq.values(), key=lambda t: -t[4]), share
