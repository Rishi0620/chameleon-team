"""contract.py: output contract, repair and safe floors (owner: OPTIMIZER; invariants ported from
JUDGE's spikes/judge + bench/contract.py).

validate(source, out, target, assets_dir) -> (hard: list[str], warn: list[str])
repair(source, out, target, assets_dir)   -> out        (pure: returns a new dict)
safe_fit(source, target, assets_dir)      -> out        (uniform contain; structurally perfect)
last_resort(source, target)               -> out        (no measurement, no imports beyond stdlib)

Invariants (JUDGE I1-I12 + PERCEPTION I13):
 I1  shape {"canvas": {width:int, height:int}, "elements": [...]}; ids exactly the source ids, source order
 I2  frozen: type, content, font_family, asset_id, group_id (unknown keys pass through)
 I3  finite numbers; font_size int >= 1; z_index int when the source's is
 I4  unrotated box inside the canvas (+-0.5); visible rotated elements: rotated AABB inside too
 I5  non-cover, non-full-bleed images keep the source box aspect within 1%
 I6  visible text: box h >= n_lines * fs * lh, drawn line widths <= box w + 1, w,h >= 1
 I8  groups all-or-nothing visibility
 I12 renderable (no named colours written, no w/h 0 text)
 I13 a group label whose centre was inside its shape in the source stays inside it
"""
from __future__ import annotations

import copy
import math
import re

from . import textfit as T

FROZEN = ("type", "content", "font_family", "asset_id", "group_id")
REQ_COMMON = ("id", "type", "x", "y", "width", "height")
REQ_TYPE = {"text": ("content", "font_family", "font_size", "color"), "image": ("asset_id",),
            "shape": ("shape_type", "fill_color")}


def _rgba(c):
    m = re.match(r"rgba?\(([^)]*)\)", str(c or "").replace(" ", ""))
    if not m:
        return None
    p = m.group(1).split(",")
    try:
        r, g, b = (float(v) for v in p[:3])
        a = float(p[3]) if len(p) > 3 else 1.0
    except ValueError:
        return None
    return r, g, b, a


def visible(el):
    try:
        if float(el.get("opacity", 1) if el.get("opacity") is not None else 1) <= 0.001:
            return False
    except (TypeError, ValueError):
        pass
    if el.get("type") == "text":
        c = _rgba(el.get("color"))
        return bool(str(el.get("content", "")).strip()) and (c is None or c[3] > 0.001)
    if el.get("type") == "shape":
        c = _rgba(el.get("fill_color"))
        return c is None or c[3] > 0.001
    return True


def full_bleed(el, cw, ch):
    return float(el["width"]) * float(el["height"]) >= 0.8 * cw * ch


def rot_aabb(el):
    return T.rot_aabb(float(el["x"]), float(el["y"]), float(el["width"]), float(el["height"]),
                      float(el.get("rotation", 0) or 0))


def _center_inside(a, b, tol=1.0):
    cx, cy = a["x"] + a["width"] / 2, a["y"] + a["height"] / 2
    return b["x"] - tol <= cx <= b["x"] + b["width"] + tol and b["y"] - tol <= cy <= b["y"] + b["height"] + tol


# ----------------------------------------------------------------------------- validate
def validate(source, out, target, assets_dir=None):
    hard, warn = [], []
    if not isinstance(out, dict) or "canvas" not in out or "elements" not in out:
        return ["I1: missing canvas/elements"], warn
    cv = out["canvas"]
    if set(cv) != {"width", "height"} or not all(isinstance(cv.get(k), int) for k in ("width", "height")):
        hard.append("I1: canvas must be exactly integer width/height")
    if cv.get("width") != int(target["width"]) or cv.get("height") != int(target["height"]):
        hard.append("I1: canvas != target")
    src_ids = [e["id"] for e in source["elements"]]
    ids = [e.get("id") for e in out["elements"]]
    if ids != src_ids:
        hard.append("I1: ids/order differ from source")
    src = {e["id"]: e for e in source["elements"]}
    W, H = float(cv.get("width", 1)), float(cv.get("height", 1))
    cw, ch = float(source["canvas"]["width"]), float(source["canvas"]["height"])
    for el in out["elements"]:
        eid, s = el.get("id"), src.get(el.get("id"), {})
        miss = [f for f in REQ_COMMON + REQ_TYPE.get(el.get("type"), ()) if f not in el]
        if miss:
            hard.append(f"I1: {eid} missing {miss}")
            continue
        try:
            geo = [float(el[k]) for k in ("x", "y", "width", "height")]
        except (TypeError, ValueError):
            hard.append(f"I3: {eid} non-numeric geometry")
            continue
        if not all(math.isfinite(v) for v in geo):
            hard.append(f"I3: {eid} non-finite geometry")
            continue
        for k in FROZEN:
            if k in s and el.get(k) != s.get(k):
                hard.append(f"I2: {eid} changed frozen '{k}'")
        if isinstance(s.get("z_index"), int) and not isinstance(el.get("z_index"), int):
            hard.append(f"I3: {eid} z_index not int")
        if el["x"] < -0.5 or el["y"] < -0.5 or el["x"] + el["width"] > W + 0.5 or el["y"] + el["height"] > H + 0.5:
            hard.append(f"I4: {eid} off-canvas")
        if el["width"] <= 0 or el["height"] <= 0:
            hard.append(f"I12: {eid} w/h <= 0")
        if visible(el) and abs(float(el.get("rotation", 0) or 0)) > 0.1:
            x0, y0, x1, y1 = rot_aabb(el)
            if x0 < -1 or y0 < -1 or x1 > W + 1 or y1 > H + 1:
                hard.append(f"I4: {eid} rotated corners leave canvas")
        if el["type"] == "image" and el.get("fit", "contain") != "cover" and s and not full_bleed(s, cw, ch):
            a0 = s["width"] / max(1e-6, s["height"])
            a1 = el["width"] / max(1e-6, el["height"])
            if abs(a1 / a0 - 1) > 0.01:
                hard.append(f"I5: {eid} aspect {a1:.3f} vs {a0:.3f}")
        if el["type"] == "text":
            try:
                fs = float(el["font_size"])
            except (TypeError, ValueError):
                hard.append(f"I3: {eid} bad font_size")
                continue
            if fs < 1 or fs != int(fs):
                hard.append(f"I3: {eid} font_size {fs} not int >= 1")
            if visible(el) and fs >= 1:
                n = T.n_lines(el, int(fs), el["width"])
                need = n * int(fs) * T.line_height(el)
                if el["height"] + 1 < need:
                    hard.append(f"I6: {eid} box h {el['height']:.0f} < {need:.0f}")
                dw = max(T.drawn_widths(el, int(fs), el["width"]))
                if dw > el["width"] + 1:
                    warn.append(f"I6w: {eid} drawn line {dw:.0f} > box {el['width']:.0f}")
                if el["y"] + need > H + 1:
                    hard.append(f"I4: {eid} text ink below canvas")
    groups = {}
    for el in out["elements"]:
        if el.get("group_id"):
            groups.setdefault(el["group_id"], []).append(el)
    for gid, mem in groups.items():
        meaningful = [m for m in mem if not (m["type"] == "text" and not str(m.get("content", "")).strip())]
        vis = [visible(m) for m in meaningful]
        if len(meaningful) > 1 and any(vis) and not all(vis):
            hard.append(f"I8: group {gid} partially hidden")
            continue
        if any(vis):
            for t in [m for m in mem if m["type"] == "text"]:
                for sh in [m for m in mem if m["type"] == "shape"]:
                    st, ss = src.get(t["id"]), src.get(sh["id"])
                    if st and ss and _center_inside(st, ss) and not _center_inside(t, sh):
                        hard.append(f"I13: label {t['id']} left its shape {sh['id']}")
    return hard, warn


# ----------------------------------------------------------------------------- repair
def _num(v, d=0.0):
    try:
        v = float(v)
        return v if math.isfinite(v) else d
    except (TypeError, ValueError):
        return d


def hide_el(el, mode="alpha", min_z=0):
    el["opacity"] = 0.0
    if el["type"] == "text":
        if mode == "z_under_bg":
            el["z_index"] = int(min_z) - 1
        else:
            el["color"] = transparent(el.get("color"))
            if el.get("style_runs"):
                el["style_runs"] = [dict(r, color=transparent(r["color"])) if "color" in r else dict(r)
                                    for r in el["style_runs"]]
    return el


def transparent(c):
    v = _rgba(c)
    if v is None:
        return "rgba(0,0,0,0)"
    r, g, b, _ = v
    return f"rgba({int(r)},{int(g)},{int(b)},0)"


def repair(source, out, target, assets_dir=None, hide_mode="alpha"):
    out = copy.deepcopy(out)
    W, H = int(target["width"]), int(target["height"])
    out = {"canvas": {"width": W, "height": H}, "elements": out.get("elements", [])}
    by = {e.get("id"): e for e in out["elements"]}
    els = []
    for s in source["elements"]:
        el = by.get(s["id"])
        if el is None:
            el = copy.deepcopy(s)
            el["opacity"] = 0.0
        for k in FROZEN:
            if k in s:
                el[k] = s[k]
        els.append(el)
    min_z = min([int(_num(e.get("z_index", 0))) for e in source["elements"]] or [0])
    for el, s in zip(els, source["elements"]):
        for k in ("x", "y", "width", "height"):
            el[k] = _num(el.get(k), _num(s.get(k), 1.0))
        el["width"], el["height"] = max(1.0, el["width"]), max(1.0, el["height"])
        if isinstance(s.get("z_index"), int):
            el["z_index"] = int(_num(el.get("z_index", s["z_index"]), s["z_index"]))
        if el["type"] == "text":
            el["font_size"] = max(1, int(round(_num(el.get("font_size"), _num(s.get("font_size"), 12)))))
        _clamp(el, W, H)
        if el["type"] == "text" and visible(el):
            _honest_text(el, W, H)
        if visible(el) and abs(float(el.get("rotation", 0) or 0)) > 0.1:
            _clamp_rot(el, W, H)
    # groups all-or-nothing; labels back inside their shapes
    groups = {}
    for el in els:
        if el.get("group_id"):
            groups.setdefault(el["group_id"], []).append(el)
    src = {e["id"]: e for e in source["elements"]}
    for mem in groups.values():
        meaningful = [m for m in mem if not (m["type"] == "text" and not str(m.get("content", "")).strip())]
        vis = [visible(m) for m in meaningful]
        if any(vis) and not all(vis):
            for m in mem:
                hide_el(m, hide_mode, min_z)
        elif any(vis):
            for t in [m for m in mem if m["type"] == "text"]:
                for sh in [m for m in mem if m["type"] == "shape"]:
                    st, ss = src.get(t["id"]), src.get(sh["id"])
                    if st and ss and _center_inside(st, ss) and not _center_inside(t, sh):
                        t["x"] = sh["x"] + (sh["width"] - t["width"]) / 2
                        t["y"] = sh["y"] + (sh["height"] - t["height"]) / 2
                        _clamp(t, W, H)
    for el in els:
        for k in ("x", "y", "width", "height"):
            el[k] = round(float(el[k]), 2)
        if el["x"] + el["width"] > W:
            el["x"] = round(max(0.0, W - el["width"]), 2)
        if el["y"] + el["height"] > H:
            el["y"] = round(max(0.0, H - el["height"]), 2)
        if "opacity" in el:
            el["opacity"] = float(min(1.0, max(0.0, _num(el["opacity"], 1.0))))
    out["elements"] = els
    return out


def _clamp(el, W, H):
    if el["width"] > W or el["height"] > H:
        k = min(W / el["width"], H / el["height"])
        if el["type"] == "image":
            el["width"] *= k
            el["height"] *= k
        else:
            el["width"] = min(el["width"], W)
            el["height"] = min(el["height"], H)
    el["x"] = min(max(el["x"], 0.0), W - el["width"])
    el["y"] = min(max(el["y"], 0.0), H - el["height"])


def _honest_text(el, W, H):
    for _ in range(60):
        fs = int(el["font_size"])
        n = T.n_lines(el, fs, el["width"])
        need = n * fs * T.line_height(el)
        dw = max(T.drawn_widths(el, fs, el["width"]))
        if need <= H and dw <= el["width"] + 1 and (T.max_word(el, fs) <= el["width"] + 1 or el["width"] >= W):
            h0 = el["height"]
            el["height"] = max(min(H, max(h0, need)), 1.0)
            if el["height"] > h0:
                el["y"] -= (el["height"] - h0) / 2          # grow about the centre: a label stays on its shape
            if el["y"] < 0:
                el["y"] = 0.0
            if el["y"] + el["height"] > H:
                el["y"] = max(0.0, H - el["height"])
            return
        if fs <= 1:
            break
        el["font_size"] = fs - 1
    el["height"] = max(1.0, min(H, el["height"]))
    el["y"] = min(max(0.0, el["y"]), H - el["height"])


def _clamp_rot(el, W, H):
    for _ in range(20):
        x0, y0, x1, y1 = rot_aabb(el)
        if x1 - x0 > W or y1 - y0 > H:
            k = 0.9 * min(W / (x1 - x0), H / (y1 - y0))
            cx, cy = el["x"] + el["width"] / 2, el["y"] + el["height"] / 2
            el["width"] *= k
            el["height"] *= k
            el["x"], el["y"] = cx - el["width"] / 2, cy - el["height"] / 2
            if el["type"] == "text":
                el["font_size"] = max(1, int(el["font_size"] * k))
            continue
        dx = (-x0 if x0 < 0 else 0) + (W - x1 if x1 > W else 0)
        dy = (-y0 if y0 < 0 else 0) + (H - y1 if y1 > H else 0)
        el["x"] += dx
        el["y"] += dy
        if not dx and not dy:
            break
    _clamp(el, W, H)


# ----------------------------------------------------------------------------- floors
def safe_fit(source, target, assets_dir, hide_mode="alpha"):
    """Uniform contain-scale of the whole design (JUDGE's structurally perfect floor)."""
    W, H = int(target["width"]), int(target["height"])
    cw, ch = float(source["canvas"]["width"]), float(source["canvas"]["height"])
    s = min(W / cw, H / ch)
    ox, oy = (W - cw * s) / 2, (H - ch * s) / 2
    any_asset = any(T.asset_info(assets_dir, e.get("asset_id")) for e in source["elements"] if e["type"] == "image")
    els = []
    for e in source["elements"]:
        el = copy.deepcopy(e)
        if e["type"] in ("image", "shape") and float(e["width"]) * float(e["height"]) >= 0.85 * cw * ch \
                and not e.get("group_id"):
            el.update(x=0.0, y=0.0, width=float(W), height=float(H))
        else:
            el.update(x=ox + float(e["x"]) * s, y=oy + float(e["y"]) * s,
                      width=max(1.0, float(e["width"]) * s), height=max(1.0, float(e["height"]) * s))
            if e["type"] == "text":
                el["font_size"] = max(1, int(float(e["font_size"]) * s))
        if e["type"] == "image" and any_asset and T.asset_info(assets_dir, e.get("asset_id")) is None:
            hide_el(el, hide_mode)
        els.append(el)
    return repair(source, {"canvas": {"width": W, "height": H}, "elements": els}, target, assets_dir, hide_mode)


def last_resort(source, target):
    W, H = int(target["width"]), int(target["height"])
    cw, ch = float(source["canvas"]["width"]), float(source["canvas"]["height"])
    s = min(W / cw, H / ch)
    ox, oy = (W - cw * s) / 2, (H - ch * s) / 2
    els = []
    for e in source["elements"]:
        el = copy.deepcopy(e)
        w, h = max(1.0, float(e["width"]) * s), max(1.0, float(e["height"]) * s)
        x = min(max(0.0, ox + float(e["x"]) * s), max(0.0, W - w))
        y = min(max(0.0, oy + float(e["y"]) * s), max(0.0, H - h))
        el.update(x=round(x, 2), y=round(y, 2), width=round(min(w, W), 2), height=round(min(h, H), 2))
        if e["type"] == "text":
            el["font_size"] = max(1, int(float(e.get("font_size", 12)) * s))
        els.append(el)
    return {"canvas": {"width": W, "height": H}, "elements": els}
