"""Pixel-side proxy scorer: renders the output with the official renderer code path and measures
what a VLM judge would see. Role-free. Thresholds are SOURCE-RELATIVE where the brand itself
sets the bar (contrast, busyness, fill), per PERCEPTION's round-1 finding.

evaluate(source, out, target) -> {"hard": [...], "warn": [...], "issues": {cls: [...]}, "metrics": {...}, "score": float}
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
from PIL import Image

from common import ASSETS, render_rgba  # noqa: F401
from contract import declared_hidden, renders_visible, rotated_aabb, structural
from renderer.converter.colorutil import parse_rgba

EVAL_SIDE = 1024          # assumed judge resolution (long side); renderer never upscales
UNREADABLE_PX = 9.0       # perceived font px below which text is unreadable at EVAL_SIDE
SMALL_PX = 11.0

# per-instance penalty, cap  (composite = 100 - sum, floored at 0; hard failure = 0)
PENALTY = {
    "hidden_leak": (10, 30), "unreadable_text": (8, 32), "small_text": (2, 8),
    "text_overflow": (3, 12), "text_off_canvas": (8, 24), "rotated_clip": (5, 15),
    "placeholder_visible": (15, 15), "text_collision": (8, 32), "image_collision": (4, 12),
    "low_contrast": (5, 15), "busy_under_text": (4, 12), "hierarchy_inversion": (5, 15),
    "group_broken": (6, 18), "edge_cramped": (2, 6), "nonint_font": (1, 3),
    "unaligned": (4, 16), "orphaned_text": (4, 12),
}
W_FAITH_INK, W_FAITH_PRIMARY, W_FILL, W_DEAD = 20.0, 15.0, 25.0, 25.0

_SRC_CACHE: dict[str, dict] = {}


# ---------------------------------------------------------------- helpers
def _scale(W: int, H: int) -> float:
    return min(1.0, EVAL_SIDE / max(W, H))


def _sub(design: dict, keep) -> dict:
    return {"canvas": design["canvas"], "elements": [e for e in design["elements"] if keep(e)]}


def _render(design: dict, transparent: bool = False) -> np.ndarray:
    return render_rgba(design, transparent=transparent, max_size=EVAL_SIDE)


def _mask(design: dict, el: dict) -> np.ndarray:
    a = _render({"canvas": design["canvas"], "elements": [el]}, transparent=True)[..., 3]
    return a > 40


def _lum(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(float) / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def _bg_layer(el: dict, W: float, H: float) -> bool:
    """Background-like layer: a NON-text element covering >= 80% of the canvas (a big text box is not a bg)."""
    return el.get("type") != "text" and float(el["width"]) * float(el["height"]) >= 0.8 * W * H


def _eff_alpha(el: dict) -> float:
    a = float(el.get("opacity", 1) if el.get("opacity") is not None else 1)
    if el["type"] == "shape":
        a *= parse_rgba(el.get("fill_color"))[3]
    return a


def _boxes_touch(a: dict, b: dict, pad: float = 0.0) -> bool:
    ax0, ay0, ax1, ay1 = rotated_aabb(a)
    bx0, by0, bx1, by1 = rotated_aabb(b)
    return ax0 - pad < bx1 and bx0 - pad < ax1 and ay0 - pad < by1 and by0 - pad < ay1


def _text_pixel_stats(el: dict, mask: np.ndarray, backdrop: np.ndarray, s: float) -> tuple[float, float]:
    """(p10 WCAG contrast of glyph colour vs pixels under the glyphs, edge density under the text)."""
    if mask.sum() < 4:
        return 21.0, 0.0
    r, g, b, a = parse_rgba(el.get("color"))
    bd = backdrop[..., :3][mask].astype(float)
    col = a * np.array([r, g, b], float) + (1 - a) * bd
    lt, lb = _lum(col[None])[0], _lum(bd[None])[0]
    ratio = (np.maximum(lt, lb) + 0.05) / (np.minimum(lt, lb) + 0.05)
    contrast = float(np.percentile(ratio, 10))
    ys, xs = np.nonzero(mask)
    pad = max(2, int(0.25 * float(el["font_size"]) * s))
    y0, y1 = max(0, ys.min() - pad), min(mask.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(mask.shape[1], xs.max() + pad + 1)
    L = _lum(backdrop[y0:y1, x0:x1, :3])
    if L.shape[0] < 3 or L.shape[1] < 3:
        return contrast, 0.0
    gy, gx = np.abs(np.diff(L, axis=0))[:, :-1], np.abs(np.diff(L, axis=1))[:-1, :]
    busy = float(((gx + gy) > 0.06).mean())
    return contrast, busy


def _text_stats(design: dict, masks: dict[str, np.ndarray], texts: list[dict], s: float) -> dict[str, tuple]:
    backdrop = _render(_sub(design, lambda e: e["type"] != "text"))
    return {t["id"]: _text_pixel_stats(t, masks[t["id"]], backdrop, s) for t in texts if t["id"] in masks}


def source_profile(name: str, source: dict) -> dict:
    """Cached per design: ink shares, text contrast/busyness, fill, centroid (all at EVAL scale)."""
    if name in _SRC_CACHE:
        return _SRC_CACHE[name]
    W, H = source["canvas"]["width"], source["canvas"]["height"]
    s = _scale(W, H)
    vis = [e for e in source["elements"] if renders_visible(e) and not declared_hidden(e)]
    fg = [e for e in vis if not _bg_layer(e, W, H)]
    masks = {e["id"]: _mask(source, e) for e in fg}
    area = {k: float(m.sum()) for k, m in masks.items()}
    tot = sum(area.values()) or 1.0
    texts = [e for e in fg if e["type"] == "text"]
    prof = {"share": {k: v / tot for k, v in area.items()},
            "text": _text_stats(source, masks, texts, s),
            "fill": _fill(masks, W, H, s), "centroid": _centroid(masks),
            "edge_ids": {k for k, m in masks.items() if _touches_edge(m, W, H, s)},
            "unaligned": len(_unaligned(masks, {e["id"] for e in fg if _eff_alpha(e) >= 0.35})),
            "dead": _dead_band({k: m for k, m in masks.items() if _eff_alpha(next(e for e in fg if e["id"] == k)) >= 0.35}),
            "partners": _partners(source, {e["id"] for e in fg}),
            "primary_text": max(texts, key=lambda e: float(e["font_size"]))["id"] if texts else None}
    _SRC_CACHE[name] = prof
    return prof


def _fill(masks: dict[str, np.ndarray], W: int, H: int, s: float) -> float:
    if not masks:
        return 0.0
    u = np.zeros_like(next(iter(masks.values())))
    for m in masks.values():
        u |= m
    ys, xs = np.nonzero(u)
    if len(xs) == 0:
        return 0.0
    return float((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)) / (u.shape[0] * u.shape[1])


def _centroid(masks: dict[str, np.ndarray]) -> tuple[float, float]:
    if not masks:
        return 0.5, 0.5
    u = sum(m.astype(float) for m in masks.values())
    ys, xs = np.nonzero(u)
    if len(xs) == 0:
        return 0.5, 0.5
    return float(xs.mean() / u.shape[1]), float(ys.mean() / u.shape[0])


def _touches_edge(m: np.ndarray, W: int, H: int, s: float) -> bool:
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return False
    tol = max(1, int(0.006 * min(m.shape)))
    return xs.min() < tol or ys.min() < tol or xs.max() > m.shape[1] - 1 - tol or ys.max() > m.shape[0] - 1 - tol


def _bbox(m: np.ndarray):
    ys, xs = np.nonzero(m)
    return None if len(xs) == 0 else (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)


def _unaligned(masks: dict[str, np.ndarray], keep: set[str]) -> set[str]:
    """Elements whose ink box shares no edge/centre line with any other element or the canvas centre."""
    boxes = {k: _bbox(m) for k, m in masks.items() if k in keep}
    boxes = {k: b for k, b in boxes.items() if b is not None}
    if len(boxes) < 2:
        return set()
    h, w = next(iter(masks.values())).shape
    tx, ty = max(2.0, 0.008 * w), max(2.0, 0.008 * h)
    lines = {k: ((b[0], b[2], (b[0] + b[2]) / 2), (b[1], b[3], (b[1] + b[3]) / 2)) for k, b in boxes.items()}
    out = set()
    for k, (lx, ly) in lines.items():
        ok = abs(lx[2] - w / 2) <= tx or abs(ly[2] - h / 2) <= ty
        for j, (mx, my) in lines.items():
            if ok or j == k:
                continue
            ok = any(abs(a - b) <= tx for a, b in zip(lx, mx)) or any(abs(a - b) <= ty for a, b in zip(ly, my))
        if not ok:
            out.add(k)
    return out


def _dead_band(masks: dict[str, np.ndarray]) -> float:
    """Largest empty full-width row band or full-height column band, as a fraction of that dimension."""
    if not masks:
        return 1.0
    u = np.zeros_like(next(iter(masks.values())))
    for m in masks.values():
        u |= m
    def run(v):
        best = cur = 0
        for x in v:
            cur = 0 if x else cur + 1
            best = max(best, cur)
        return best / max(1, len(v))
    return max(run(u.any(axis=1)), run(u.any(axis=0)))


def _partners(source: dict, fg_ids: set[str]) -> dict[str, str]:
    """Gestalt proximity in the SOURCE: small text -> its tightly-associated nearest neighbour."""
    W, H = source["canvas"]["width"], source["canvas"]["height"]
    els = [e for e in source["elements"] if e["id"] in fg_ids]
    texts = [e for e in els if e["type"] == "text"]
    if not texts:
        return {}
    top = max(float(t["font_size"]) for t in texts)
    res = {}
    from renderer.converter.assets import asset_path
    cands = [o for o in els if _eff_alpha(o) >= 0.35 and not o.get("group_id")
             and not (o["type"] == "image" and asset_path(ASSETS, o.get("asset_id")) is None)]
    for t in texts:
        if float(t["font_size"]) >= 0.75 * top or t.get("group_id"):
            continue
        best, bd = None, 0.035 * min(W, H)
        for o in cands:
            if o["id"] == t["id"]:
                continue
            gx = max(0.0, max(o["x"] - (t["x"] + t["width"]), t["x"] - (o["x"] + o["width"])))
            gy = max(0.0, max(o["y"] - (t["y"] + t["height"]), t["y"] - (o["y"] + o["height"])))
            d = max(gx, gy) if min(gx, gy) == 0 else 1e9
            if d < bd:
                best, bd = o["id"], d
        if best:
            res[t["id"]] = best
    return res


# ---------------------------------------------------------------- main entry
def evaluate(name: str, source: dict, out: Any, target: dict, thumb_path: str | None = None) -> dict:
    res: dict[str, Any] = {"hard": [], "warn": [], "issues": {}, "metrics": {}, "score": 0.0}
    hard, warn = structural(source, out, target)
    res["hard"], res["warn"] = hard, warn
    if not isinstance(out, dict) or "elements" not in out or any(h.startswith("output missing") for h in hard):
        return res
    issues: dict[str, list[str]] = {}

    def add(cls: str, msg: str) -> None:
        issues.setdefault(cls, []).append(msg)

    for w in warn:
        cls = w.split(":")[0]
        add({"text_overflow_w": "text_overflow", "text_overflow_h": "text_overflow", "group_partial": "group_broken",
             "group_broken": "group_broken"}.get(cls, cls), w)
    W, H = int(out["canvas"]["width"]), int(out["canvas"]["height"])
    s = _scale(W, H)
    try:
        full = _render(out)
    except Exception as exc:  # noqa: BLE001
        res["hard"].append(f"render crash: {type(exc).__name__}: {str(exc)[:80]}")
        res["issues"] = issues
        return res
    if thumb_path:
        im = Image.fromarray(full[..., :3])
        k = min(1.0, 420 / max(im.size))
        im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS).save(thumb_path)
    els = out["elements"]
    # 1) renderer-gap: do declared-hidden elements really vanish? (text ignores opacity)
    hidden = [e for e in els if declared_hidden(e) and not (e["type"] == "text" and not str(e.get("content", "")).strip())]
    leak_ids: set[str] = set()
    if hidden:
        hid = {e["id"] for e in hidden}
        without = _render(_sub(out, lambda e: e["id"] not in hid))
        leak_px = int((np.abs(full[..., :3].astype(int) - without[..., :3].astype(int)).sum(axis=2) > 30).sum())
        res["metrics"]["leak_px"] = leak_px
        if leak_px > 10:
            suspects = [e for e in hidden if e["type"] == "text" and renders_visible(e)] or hidden
            for e in suspects:
                leak_ids.add(e["id"])
                add("hidden_leak", f"{e['id']} declared hidden but rendered ({leak_px}px leak)")
    vis = [e for e in els if renders_visible(e) and (not declared_hidden(e) or e["id"] in leak_ids)]
    fg = [e for e in vis if not _bg_layer(e, W, H)]
    masks = {e["id"]: _mask(out, e) for e in fg}
    texts = [e for e in fg if e["type"] == "text"]
    src = {e["id"]: e for e in source["elements"]}
    prof = source_profile(name, source)
    # 2) legibility at judge resolution
    for t in texts:
        px = int(float(t["font_size"])) * s
        if px < UNREADABLE_PX:
            add("unreadable_text", f"{t['id']} {px:.1f}px")
        elif px < SMALL_PX:
            add("small_text", f"{t['id']} {px:.1f}px")
    res["metrics"]["min_text_px"] = round(min((int(float(t["font_size"])) * s for t in texts), default=0), 1)
    # 3) contrast + busyness under glyphs, relative to the source's own choice
    tstats = _text_stats(out, masks, texts, s) if texts else {}
    for tid, (con, busy) in tstats.items():
        sc, sb = prof["text"].get(tid, (4.5, 0.05))
        if con < min(4.5, 0.9 * sc):
            add("low_contrast", f"{tid} p10 {con:.2f} vs source {sc:.2f}")
        if busy > max(0.15, 1.6 * sb):
            add("busy_under_text", f"{tid} edge density {busy:.2f} vs source {sb:.2f}")
    # 4) collisions on INK (masks), ignoring group-mates, background layers, translucent decor,
    #    and pairs that already overlapped in the source (intentional layering)
    def allowed(a: dict, b: dict) -> bool:
        if a.get("group_id") and a.get("group_id") == b.get("group_id"):
            return True
        if _eff_alpha(a) < 0.35 or _eff_alpha(b) < 0.35:
            return True
        sa, sb_ = src.get(a["id"]), src.get(b["id"])
        return bool(sa and sb_ and _boxes_touch(sa, sb_, pad=2))
    for t in texts:
        mt = masks[t["id"]]
        if mt.sum() == 0:
            continue
        for o in fg:
            if o["id"] == t["id"] or allowed(t, o):
                continue
            ov = int((mt & masks[o["id"]]).sum())
            if ov > 0.02 * mt.sum() and ov > 6:
                add("text_collision", f"{t['id']} x {o['id']} ({ov / mt.sum():.0%} of glyph ink)")
    others = [e for e in fg if e["type"] != "text"]
    for i, a in enumerate(others):
        for b in others[i + 1:]:
            if allowed(a, b):
                continue
            ov = int((masks[a["id"]] & masks[b["id"]]).sum())
            small = min(masks[a["id"]].sum(), masks[b["id"]].sum())
            if small and ov > 0.05 * small:
                add("image_collision", f"{a['id']} x {b['id']} ({ov / small:.0%})")
    # 4b) label ink spilling out of its group shape (perception R2: the pill-spill blind spot)
    by_gid: dict[str, list[dict]] = {}
    for e in fg:
        if e.get("group_id"):
            by_gid.setdefault(e["group_id"], []).append(e)
    for mem in by_gid.values():
        for t in (m for m in mem if m["type"] == "text" and m["id"] in masks):
            for sh in (m for m in mem if m["type"] == "shape" and not m.get("rotation")):
                st, ss = src.get(t["id"]), src.get(sh["id"])
                if not (st and ss and ss["x"] <= st["x"] + st["width"] / 2 <= ss["x"] + ss["width"]
                        and ss["y"] <= st["y"] + st["height"] / 2 <= ss["y"] + ss["height"]):
                    continue
                b = _bbox(masks[t["id"]])
                if b is None:
                    continue
                x0, y0, x1, y1 = (v / s for v in b)
                tol = 2.0
                if x0 < sh["x"] - tol or y0 < sh["y"] - tol or x1 > sh["x"] + sh["width"] + tol \
                        or y1 > sh["y"] + sh["height"] + tol:
                    add("group_broken", f"label ink {t['id']} spills out of its shape {sh['id']}")
    # 5) hierarchy among visible texts (source font-size order, >=1.2x gaps must not invert)
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            sa, sb_ = float(src[a["id"]]["font_size"]), float(src[b["id"]]["font_size"])
            fa, fb = int(float(a["font_size"])), int(float(b["font_size"]))
            if sa >= 1.2 * sb_ and fa < fb or sb_ >= 1.2 * sa and fb < fa:
                add("hierarchy_inversion", f"{a['id']}({sa:.0f}->{fa}) vs {b['id']}({sb_:.0f}->{fb})")
    # 6) edges: foreground ink jammed against the canvas edge when it was not in the source
    for e in fg:
        if e["id"] not in prof["edge_ids"] and _eff_alpha(e) >= 0.35 and _touches_edge(masks[e["id"]], W, H, s):
            add("edge_cramped", f"{e['id']}")
    # 7) alignment (ink edges/centres) and proximity groups, source-relative
    solid = {e["id"] for e in fg if _eff_alpha(e) >= 0.35}
    una = _unaligned(masks, solid)
    excess = len(una) - prof["unaligned"]
    for k in sorted(una)[:max(0, excess)]:
        add("unaligned", k)
    for t, partner in prof["partners"].items():
        if t in masks and partner not in masks:
            add("orphaned_text", f"{t} shown without its source neighbour {partner}")
    dead = _dead_band({k: v for k, v in masks.items() if k in solid})
    # 8) faithfulness + fill (source-relative)
    kept = sum(v for k, v in prof["share"].items() if k in masks)
    prim = prof["primary_text"]
    primary_kept = prim is None or prim in masks
    fill = _fill(masks, W, H, s)
    fill_rel = fill / prof["fill"] if prof["fill"] else 1.0
    m = res["metrics"]
    m.update(kept_ink=round(kept, 3), primary_kept=primary_kept, fill=round(fill, 3), fill_rel=round(fill_rel, 3),
             dead_band=round(dead, 3), src_dead_band=round(prof["dead"], 3),
             n_visible=len(vis), n_hidden=len(els) - len(vis))
    # composite
    pen = 0.0
    for cls, msgs in issues.items():
        if cls in PENALTY:
            per, cap = PENALTY[cls]
            pen += min(cap, per * len(msgs))
    pen += W_FAITH_INK * (1 - kept) + (0 if primary_kept else W_FAITH_PRIMARY)
    pen += W_FILL * max(0.0, 1 - fill_rel / 0.7)
    pen += W_DEAD * max(0.0, dead - max(0.2, prof["dead"] + 0.1))
    res["issues"] = issues
    res["score"] = 0.0 if res["hard"] else round(max(0.0, 100.0 - pen), 1)
    return res


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from designs import load_all
    tasks = load_all()
    t = tasks["L3_advanced"]
    print(json.dumps(evaluate("L3_advanced", t["source"], t["source"], t["source"]["canvas"]), indent=1)[:3000])
