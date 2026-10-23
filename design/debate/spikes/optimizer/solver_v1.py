"""OPTIMIZER spike: structured-search retargeting solver.

NOT production code. Purpose: de-risk the claims in round1/optimizer.md:
  1. Text can be turned into an exact discrete (width,height) frontier using the
     renderer's own wrap.py + skia metrics, cheaply.
  2. With a shared type/zoom scale `z`, feasibility is monotone in z, so for a
     fixed discrete topology the best continuous solution is found by bisection.
  3. Enumerating discrete topologies (template x slot partition x visible set x
     image boost) is cheap enough to be exhaustive for real ad designs.
  4. "Dropping" emerges from the energy (legibility floors + drop cost), not
     from per-size hand rules.

Role inference here is deliberately crude (feature heuristics, never ids).

Run from repo root:
    .venv/bin/python design/debate/spikes/optimizer/solver.py
"""
from __future__ import annotations

import itertools
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import skia
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from renderer.converter.convert import (  # noqa: E402
    _BOLD_WEIGHTS,
    _get_renderer,
    _normalize_weight,
    _weight_style_to_font_style,
    render_design_to_png,
)
from renderer.converter.wrap import char_widths, wrap_text  # noqa: E402

FM = _get_renderer(str(ROOT / "brand_kit/fonts")).font_manager
ASSETS = ROOT / "brand_kit/assets"
OUT = Path(__file__).resolve().parent / "out_v1"

KMAX = 4  # max lines considered for any text block

# energy weights (hand-set for the spike; production: fitted to VLM preferences)
W_DROP = 1.6      # cost per unit importance of hiding an atom
W_SIZE = 1.0      # reward per unit importance for log(scale / z_ref)
W_FLOOR = 0.25    # text clamped at legibility floor (hierarchy compression)
W_LINES = 0.12    # per line beyond 2 for primary text
W_WIDOW = 0.08    # last line shorter than 30% of the longest line
W_SLOTS = 0.06    # per extra slot (Occam: prefer simpler topologies)
W_BOOST = 0.15    # |log b| image boost away from the shared zoom (relative-scale faithfulness)
W_FILL = 0.8      # content bbox covers too little of the canvas
W_ORDER = 0.1     # per inversion of source reading order


# ----------------------------------------------------------------------------
# text measurement (exactly what the renderer will do)
# ----------------------------------------------------------------------------
def _font_args(el):
    weight = _normalize_weight(el.get("font_weight"))
    italic = el.get("font_style") == "italic"
    style = _weight_style_to_font_style(weight in _BOLD_WEIGHTS, italic)
    return el.get("font_family", "Montserrat"), weight, style


_cw, _met, _wk = {}, {}, {}


def cwidths(el, f):
    key = (id(el), f)
    if key not in _cw:
        fam, w, s = _font_args(el)
        _cw[key] = char_widths(FM, fam, w, s, f, el["content"])
    return _cw[key]


def metrics(el, f):
    key = (_font_args(el), f)
    if key not in _met:
        fam, w, s = _font_args(el)
        m = skia.Font(skia.Typeface.MakeFromData(FM.lookup(fam, w, s)), f).getMetrics()
        _met[key] = (-m.fAscent, m.fDescent, m.fCapHeight)
    return _met[key]


def n_lines(el, f, width):
    return wrap_text(el["content"], cwidths(el, f), width).count("\n") + 1


def line_widths(el, f, width):
    ws = cwidths(el, f)
    wrapped = wrap_text(el["content"], ws, width)
    out, cur = [], 0.0
    for c, w in zip(wrapped, ws):
        if c == "\n":
            out.append(cur)
            cur = 0.0
        else:
            cur += w
    out.append(cur)
    return out


def max_word(el, f):
    ws, best, cur = cwidths(el, f), 0.0, 0.0
    for c, w in zip(el["content"], ws):
        cur = 0.0 if c == " " else cur + w
        best = max(best, cur)
    return best


def W_k(el, f, k):
    """Minimal box width so that greedy wrap at font f gives <= k lines (exact up to 0.25px)."""
    key = (id(el), f, k)
    if key in _wk:
        return _wk[key]
    total = sum(cwidths(el, f)) + 0.5
    lo = max_word(el, f) + 0.5
    if k == 1 or n_lines(el, f, lo) <= k:
        res = total if k == 1 else lo
    else:
        hi = total
        while hi - lo > 0.25:
            mid = (lo + hi) / 2
            if n_lines(el, f, mid) <= k:
                hi = mid
            else:
                lo = mid
        res = hi
    _wk[key] = res
    return res


def text_h(el, f, k):
    asc, desc, _ = metrics(el, f)
    return (k - 1) * f * float(el.get("line_height", 1.2)) + asc + desc


def lines_at(el, f, c):
    for k in range(1, KMAX + 1):
        if W_k(el, f, k) <= c:
            return k
    return None


# ----------------------------------------------------------------------------
# atoms
# ----------------------------------------------------------------------------
def asset_alpha_bbox(asset_id):
    p = ASSETS / str(asset_id)
    if not p.is_file():
        return None
    im = Image.open(p)
    bb = im.getchannel("A").getbbox() if im.mode == "RGBA" else (0, 0, *im.size)
    return im.size, bb or (0, 0, *im.size)


@dataclass(eq=False)
class Atom:
    kind: str                      # text | image | pill | cluster | rigid | sticker
    els: list
    imp: float = 0.5
    order: float = 0.0
    anchored: tuple | None = None  # (hx, vy) in {0,1} corner, for overlay atoms
    members: list = field(default_factory=list)  # for cluster: list of pill atoms
    floor: int = 10
    fsrc: float = 1.0

    @property
    def name(self):
        return "+".join(e["id"] for e in self.els)

    # union box in source
    def src_box(self):
        xs = [e["x"] for e in self.els]
        ys = [e["y"] for e in self.els]
        x1 = [e["x"] + e["width"] for e in self.els]
        y1 = [e["y"] + e["height"] for e in self.els]
        return min(xs), min(ys), max(x1) - min(xs), max(y1) - min(ys)


def pill_parts(atom):
    shape = next(e for e in atom.els if e["type"] == "shape")
    label = next(e for e in atom.els if e["type"] == "text")
    return shape, label


def pill_font(atom, z):
    _, label = pill_parts(atom)
    return max(atom.floor, round(z * label["font_size"]))


def rigid_size(atom, z, b=1.0):
    """(box_w, box_h, vis_w, vis_h, pad=(l,t,r,b)) of a rigid atom at zoom z."""
    if atom.kind == "image":
        e = atom.els[0]
        w, h = e["width"] * z * b, e["height"] * z * b
        info = asset_alpha_bbox(e.get("asset_id"))
        if info is None or e.get("fit", "contain") != "contain":
            return w, h, w, h, (0, 0, 0, 0)
        (aw, ah), (bx0, by0, bx1, by1) = info
        s = min(w / aw, h / ah)
        ox, oy = (w - aw * s) / 2, (h - ah * s) / 2
        l, t = ox + bx0 * s, oy + by0 * s
        r, bt = w - (ox + bx1 * s), h - (oy + by1 * s)
        return w, h, w - l - r, h - t - bt, (l, t, r, bt)
    if atom.kind == "pill":
        shape, label = pill_parts(atom)
        f = pill_font(atom, z)
        s = f / label["font_size"]
        h = shape["height"] * s
        lw = sum(cwidths(label, f))
        w = max(shape["width"] * s, lw + 0.9 * h)
        return w, h, w, h, (0, 0, 0, 0)
    if atom.kind == "cluster":
        sizes = [rigid_size(m, z) for m in atom.members]
        f = pill_font(atom.members[0], z)
        s = f / pill_parts(atom.members[0])[1]["font_size"]
        g = atom.gap_src * s
        w = sum(sz[0] for sz in sizes) + g * (len(sizes) - 1)
        h = max(sz[1] for sz in sizes)
        return w, h, w, h, (0, 0, 0, 0)
    # rigid group / sticker: uniform scale, labels respect floor
    x, y, w, h = atom.src_box()
    texts = [e for e in atom.els if e["type"] == "text"]
    s = z * b
    if texts:
        s = max(s, max(atom.floor / t["font_size"] for t in texts))
    return w * s, h * s, w * s, h * s, (0, 0, 0, 0)


def rigid_scale(atom, z, b=1.0):
    if atom.kind in ("pill", "cluster"):
        a = atom if atom.kind == "pill" else atom.members[0]
        return pill_font(a, z) / pill_parts(a)[1]["font_size"]
    if atom.kind == "image":
        return z * b
    x, y, w, h = atom.src_box()
    return rigid_size(atom, z, b)[0] / w


# ----------------------------------------------------------------------------
# role-ish inference (features only, never ids)
# ----------------------------------------------------------------------------
def build_atoms(src, W, H):
    cw, ch = src["canvas"]["width"], src["canvas"]["height"]
    els = src["elements"]
    bg, decor, hidden, atoms = [], [], [], []
    groups = {}
    for e in els:
        if e.get("group_id"):
            groups.setdefault(e["group_id"], []).append(e)
    seen = set()
    main_floor = max(10, round(0.0095 * max(W, H)))
    fine_floor = max(8, round(0.75 * main_floor))
    for e in els:
        if e["id"] in seen:
            continue
        area = e["width"] * e["height"]
        if e.get("group_id"):
            g = groups[e["group_id"]]
            seen.update(x["id"] for x in g)
            shapes = [x for x in g if x["type"] == "shape"]
            texts = [x for x in g if x["type"] == "text"]
            rot = any(abs(x.get("rotation", 0) or 0) > 0.5 for x in g)
            kind = "sticker" if rot else ("pill" if len(shapes) == 1 and len(texts) == 1 and len(g) == 2 else "rigid")
            atoms.append(Atom(kind, g, floor=main_floor))
            continue
        seen.add(e["id"])
        if area >= 0.85 * cw * ch and e["type"] in ("image", "shape"):
            bg.append(e)
        elif e["type"] == "shape":
            decor.append(e)
        elif e["type"] == "image" and asset_alpha_bbox(e.get("asset_id")) is None:
            hidden.append(e)  # missing asset: never show a broken placeholder
        else:
            atoms.append(Atom(e["type"], [e], floor=main_floor))

    # prominence of free text
    texts = [a for a in atoms if a.kind == "text"]
    pmax = max((a.els[0]["font_size"] * (1.15 if a.els[0].get("font_weight") == "bold" else 1) for a in texts), default=1)
    for a in atoms:
        x, y, w, h = a.src_box()
        a.order = (y + h / 2) / ch + 0.001 * (x / cw)
        if a.kind == "text":
            e = a.els[0]
            p = e["font_size"] * (1.15 if e.get("font_weight") == "bold" else 1) / pmax
            a.fsrc = e["font_size"]
            if p < 0.4 and len(e["content"]) > 60:
                a.imp, a.floor = 0.12, fine_floor
            else:
                a.imp = 0.35 + 0.65 * p ** 1.5
        elif a.kind == "image":
            ar = w / h
            a.imp = 0.9 if (ar >= 2.0 or w * h < 0.06 * cw * ch) else 0.65
        elif a.kind == "sticker":
            a.imp = 0.25
        else:
            a.imp = 0.3
    pills = [a for a in atoms if a.kind == "pill"]
    if pills:
        cta = max(pills, key=lambda a: pill_parts(a)[0]["width"] * pill_parts(a)[0]["height"])
        cta.imp = 0.85
    # cluster non-CTA pills that share a source row
    rest = [a for a in pills if a.imp < 0.85]
    rest.sort(key=lambda a: a.src_box()[0])
    used = set()
    for a in rest:
        if id(a) in used:
            continue
        ay = a.src_box()[1] + a.src_box()[3] / 2
        row = [b for b in rest if id(b) not in used and abs(b.src_box()[1] + b.src_box()[3] / 2 - ay) < 0.5 * a.src_box()[3]]
        if len(row) >= 2:
            for b in row:
                used.add(id(b))
                atoms.remove(b)
            c = Atom("cluster", [e for b in row for e in b.els], imp=0.3, floor=main_floor)
            c.members = row
            xs = [b.src_box() for b in row]
            c.gap_src = sum(xs[i + 1][0] - (xs[i][0] + xs[i][2]) for i in range(len(xs) - 1)) / (len(xs) - 1)
            x, y, w, h = c.src_box()
            c.order = (y + h / 2) / ch
            atoms.append(c)
    # corner-anchored overlays: small, off the main axis, near two edges
    for a in atoms:
        x, y, w, h = a.src_box()
        cx = x + w / 2
        near_h = x < 0.12 * cw or x + w > 0.88 * cw
        near_v = y < 0.12 * ch or y + h > 0.88 * ch
        if a.kind in ("pill", "sticker") and a.imp < 0.85 and abs(cx - cw / 2) > 0.25 * cw and near_h and near_v:
            a.anchored = (0 if cx < cw / 2 else 1, 0 if y + h / 2 < ch / 2 else 1)
    return bg, decor, hidden, atoms


# ----------------------------------------------------------------------------
# slot / row evaluation
# ----------------------------------------------------------------------------
def eval_slot(slot, z, boosts, H_av, gap, c_max, m):
    """Minimal slot width that fits all atoms stacked vertically within H_av.
    Returns (c, used_h, detail) or None."""
    fixed_h, c_rigid, texts, det = 0.0, 0.0, [], {}
    for a in slot:
        if a.kind == "text":
            f = max(a.floor, round(z * a.fsrc))
            texts.append((a, f))
        else:
            bw, bh, vw, vh, pad = rigid_size(a, z, boosts.get(id(a), 1.0))
            if bh > H_av + 2 * m or bw > c_max + 2 * m:  # full box must fit the canvas
                return None
            fixed_h += vh
            c_rigid = max(c_rigid, vw)
            det[id(a)] = (bw, bh, vw, vh, pad)
    fixed_h += gap * (len(slot) - 1)
    if fixed_h > H_av:
        return None
    if not texts:
        return (c_rigid, fixed_h, det) if c_rigid <= c_max else None
    lo = max([c_rigid] + [max_word(a.els[0], f) + 0.5 for a, f in texts])
    cands = sorted({lo} | {W_k(a.els[0], f, k) for a, f in texts for k in range(1, KMAX + 1)})
    for c in cands:
        if c < lo:
            continue
        if c > c_max:
            break
        h, ok, td = fixed_h, True, {}
        for a, f in texts:
            k = lines_at(a.els[0], f, c)
            if k is None:
                ok = False
                break
            th = text_h(a.els[0], f, k)
            h += th
            td[id(a)] = (f, k, th)
        if ok and h <= H_av:
            det.update(td)
            return c, h, det
    return None


def eval_layout(slots, z, boosts, W, H, m, gap):
    H_av, W_av = H - 2 * m, W - 2 * m
    res = []
    for s in slots:
        r = eval_slot(s, z, boosts, H_av, gap, W_av, m)
        if r is None:
            return None
        res.append(r)
    total = sum(r[0] for r in res) + gap * 1.5 * (len(slots) - 1)
    return res if total <= W_av else None


def max_zoom(slots, boosts, W, H, m_fn, z_cap):
    def feas(z):
        m, g = m_fn(z)
        return eval_layout(slots, z, boosts, W, H, m, g)

    lo, hi = 0.03, z_cap
    if feas(lo) is None:
        return None
    if feas(hi) is not None:
        return hi
    for _ in range(16):
        mid = math.sqrt(lo * hi)
        if feas(mid) is None:
            hi = mid
        else:
            lo = mid
    return lo


# ----------------------------------------------------------------------------
# placement (turn the abstract solution into element boxes)
# ----------------------------------------------------------------------------
def place_atom(a, x, y, c, z, b, det, out):
    """x,y = top-left of the atom's VISIBLE box inside a slot of width c (centered)."""
    if a.kind == "text":
        f, k, th = det[id(a)]
        e = dict(a.els[0], x=x, y=y, width=c, height=th, font_size=f)
        out[e["id"]] = e
        return th
    bw, bh, vw, vh, pad = det[id(a)] if id(a) in det else rigid_size(a, z, b)
    vx = x + (c - vw) / 2
    bx, by = vx - pad[0], y - pad[1]
    place_rigid(a, bx, by, bw, bh, z, b, out)
    return vh


def place_pill(a, bx, by, bw, bh, z, out):
    shape, label = pill_parts(a)
    f = pill_font(a, z)
    asc, desc, cap = metrics(label, f)
    out[shape["id"]] = dict(shape, x=bx, y=by, width=bw, height=bh,
                            corner_radius=shape.get("corner_radius", 0) * bh / shape["height"])
    ly = by + bh / 2 - asc + cap / 2  # optical centring on cap height
    out[label["id"]] = dict(label, x=bx, y=ly, width=bw, height=asc + desc, font_size=f)


def place_rigid(a, bx, by, bw, bh, z, b, out):
    if a.kind == "image":
        out[a.els[0]["id"]] = dict(a.els[0], x=bx, y=by, width=bw, height=bh)
    elif a.kind == "pill":
        place_pill(a, bx, by, bw, bh, z, out)
    elif a.kind == "cluster":
        f = pill_font(a.members[0], z)
        s = f / pill_parts(a.members[0])[1]["font_size"]
        cx = bx
        for mbr in a.members:
            w, h, *_ = rigid_size(mbr, z)
            place_pill(mbr, cx, by + (bh - h) / 2, w, h, z, out)
            cx += w + a.gap_src * s
    else:  # rigid / sticker: uniform scale about union box
        x0, y0, w0, h0 = a.src_box()
        s = bw / w0
        for e in a.els:
            ne = dict(e, x=bx + (e["x"] - x0) * s, y=by + (e["y"] - y0) * s,
                      width=e["width"] * s, height=e["height"] * s)
            if e["type"] == "text":
                ne["font_size"] = max(1, round(e["font_size"] * s))
            if e.get("corner_radius"):
                ne["corner_radius"] = e["corner_radius"] * s
            out[e["id"]] = ne


def realize(sol, W, H, src, bg, decor, hidden, overlays):
    slots, z, boosts, res, m, gap = sol["slots"], sol["z"], sol["boosts"], sol["res"], sol["m"], sol["gap"]
    out = {}
    for e in bg:
        out[e["id"]] = dict(e, x=0, y=0, width=W, height=H)
    W_av = W - 2 * m
    widths = [r[0] for r in res]
    n = len(slots)
    left = W_av - sum(widths) - gap * 1.5 * (n - 1)
    extra = min(left / (n + 1), 2.5 * gap) if n > 1 else 0
    xg = gap * 1.5 + extra
    x = m + (W_av - sum(widths) - xg * (n - 1)) / 2
    vis_boxes = []
    for s, (c, used, det) in zip(slots, res):
        H_av = H - 2 * m
        k = len(s)
        ex = H_av - used
        eg = min(ex / (k + 1), 1.0 * gap) if k > 1 else 0
        y = m + (ex - eg * (k - 1)) / 2
        for a in s:
            h = place_atom(a, x, y, c, z, boosts.get(id(a), 1.0), det, out)
            vis_boxes.append((x, y, c, h, a))
            y += h + gap + eg
        x += c + xg
    # overlays: corner anchored atoms; keep only if no collision with flow content
    shown_overlays = []
    for a in overlays:
        bw, bh, *_ = rigid_size(a, z)
        ang = max((abs(e.get("rotation", 0) or 0) for e in a.els), default=0)
        rad = math.radians(ang)
        aw = bw * math.cos(rad) + bh * math.sin(rad)
        ah = bw * math.sin(rad) + bh * math.cos(rad)
        ox = m + (aw - bw) / 2 if a.anchored[0] == 0 else W - m - (aw + bw) / 2
        oy = m * 0.6 + (ah - bh) / 2 if a.anchored[1] == 0 else H - m * 0.6 - (ah + bh) / 2
        rect = (ox - (aw - bw) / 2, oy - (ah - bh) / 2, aw, ah)
        hit = any(_overlap(rect, (vx, vy, vw, vh)) > 0 for vx, vy, vw, vh, _ in vis_boxes)
        if not hit and aw <= W - 2 * m and ah <= H - m:
            place_rigid(a, ox, oy, bw, bh, z, 1.0, out)
            shown_overlays.append(a)
    sx, sy = W / src["canvas"]["width"], H / src["canvas"]["height"]
    smin = min(sx, sy)
    for e in decor:
        cx, cy = (e["x"] + e["width"] / 2) * sx, (e["y"] + e["height"] / 2) * sy
        w, h = e["width"] * smin, e["height"] * smin
        out[e["id"]] = clamp(dict(e, x=cx - w / 2, y=cy - h / 2, width=w, height=h), W, H)
    # hidden: honest drop = opacity 0, proportional, in-bounds
    for e in src["elements"]:
        if e["id"] not in out:
            cx, cy = (e["x"] + e["width"] / 2) * sx, (e["y"] + e["height"] / 2) * sy
            w, h = e["width"] * smin, e["height"] * smin
            out[e["id"]] = clamp(dict(e, x=cx - w / 2, y=cy - h / 2, width=w, height=h, opacity=0), W, H)
    return [out[e["id"]] for e in src["elements"]], shown_overlays, vis_boxes


def clamp(e, W, H):
    if e["width"] > W or e["height"] > H:
        s = min(W / e["width"], H / e["height"])
        e["width"] *= s
        e["height"] *= s
    e["x"] = min(max(e["x"], 0), W - e["width"])
    e["y"] = min(max(e["y"], 0), H - e["height"])
    return e


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))


# ----------------------------------------------------------------------------
# energy + search
# ----------------------------------------------------------------------------
def energy(sol, flow_all, W, H, z_ref):
    slots, z, boosts, res = sol["slots"], sol["z"], sol["boosts"], sol["res"]
    vis = [a for s in slots for a in s]
    E, terms = 0.0, {}
    hidden = [a for a in flow_all if a not in vis]
    terms["drop"] = W_DROP * sum(a.imp for a in hidden)
    size = 0.0
    floor_pen = lines_pen = widow_pen = boost_pen = 0.0
    for s, (c, used, det) in zip(slots, res):
        for a in s:
            if a.kind == "text":
                f, k, _ = det[id(a)]
                scale = f / a.fsrc
                if f == a.floor and round(z * a.fsrc) < a.floor:
                    floor_pen += W_FLOOR * a.imp
                if a.imp > 0.3:
                    lines_pen += W_LINES * max(0, k - 2) * a.imp
                if k > 1:
                    lw = line_widths(a.els[0], f, c)
                    if lw[-1] < 0.3 * max(lw):
                        widow_pen += W_WIDOW * a.imp
            else:
                b = boosts.get(id(a), 1.0)
                scale = rigid_scale(a, z, b)
                boost_pen += W_BOOST * abs(math.log(b)) * a.imp
            size += W_SIZE * a.imp * math.log(scale / z_ref)
    terms["size"] = -size
    terms["floor"] = floor_pen
    terms["lines"] = lines_pen
    terms["widow"] = widow_pen
    terms["boost"] = boost_pen
    terms["slots"] = W_SLOTS * (len(slots) - 1)
    # reading-order inversions (slot order then stack order)
    seq = [a.order for s in slots for a in s]
    inv = sum(1 for i in range(len(seq)) for j in range(i + 1, len(seq)) if seq[i] > seq[j])
    terms["order"] = W_ORDER * inv
    # fill: visible content area vs canvas
    cov = sum(r[0] * r[1] for r in res) / (W * H)
    terms["fill"] = W_FILL * max(0.0, 0.35 - cov)
    E = sum(terms.values())
    return E, terms


def partitions(seq, k):
    n = len(seq)
    for cuts in itertools.combinations(range(1, n), k - 1):
        bounds = (0,) + cuts + (n,)
        yield [seq[bounds[i]:bounds[i + 1]] for i in range(k)]


def solve(src, W, H, verbose=False):
    t0 = time.time()
    bg, decor, hidden_els, atoms = build_atoms(src, W, H)
    flow = [a for a in atoms if a.anchored is None]
    overlays = [a for a in atoms if a.anchored is not None]
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    z_ref = math.sqrt(W * H / (Ws * Hs))
    z_cap = 1.5 * z_ref
    base = 0.03 * min(Ws, Hs)

    def m_fn(z):
        g = max(4.0, base * z)
        return max(g, 0.035 * min(W, H)), g

    must = [a for a in flow if a.imp >= 0.8]
    optional = sorted([a for a in flow if a.imp < 0.8], key=lambda a: -a.imp)
    aspect = W / H
    max_slots = 1 if aspect < 0.8 else (2 if aspect < 1.6 else (3 if aspect < 3 else 4))
    images = [a for a in flow if a.kind == "image"]
    best, n_cfg = None, 0
    for kopt in range(len(optional) + 1):
        vis = sorted(must + optional[:kopt], key=lambda a: a.order)
        vis_imgs = [a for a in vis if a.kind == "image"]
        boost_opts = [0.7, 1.0, 1.4, 2.0]
        for bcombo in itertools.product(boost_opts, repeat=len(vis_imgs)):
            boosts = {id(a): b for a, b in zip(vis_imgs, bcombo)}
            for k in range(1, min(max_slots, len(vis)) + 1):
                for slots in partitions(vis, k):
                    n_cfg += 1
                    z = max_zoom(slots, boosts, W, H, m_fn, z_cap)
                    if z is None:
                        continue
                    m, g = m_fn(z)
                    res = eval_layout(slots, z, boosts, W, H, m, g)
                    sol = dict(slots=slots, z=z, boosts=boosts, res=res, m=m, gap=g)
                    E, terms = energy(sol, flow, W, H, z_ref)
                    sol["E"], sol["terms"] = E, terms
                    if best is None or E < best["E"]:
                        best = sol
    elements, shown, vis_boxes = realize(best, W, H, src, bg, decor, hidden_els, overlays)
    # overlay drop cost (post-hoc)
    best["E"] += W_DROP * sum(a.imp for a in overlays if a not in shown)
    best["time"] = time.time() - t0
    best["n_cfg"] = n_cfg
    best["overlays_shown"] = [a.name for a in shown]
    return {"canvas": {"width": W, "height": H}, "elements": elements}, best, atoms


def describe(best, atoms):
    lines = [f"  configs={best['n_cfg']}  time={best['time']:.2f}s  z={best['z']:.3f}  E={best['E']:.3f}"]
    for i, (s, (c, used, det)) in enumerate(zip(best["slots"], best["res"])):
        parts = []
        for a in s:
            if a.kind == "text":
                f, k, _ = det[id(a)]
                parts.append(f"{a.name}[f={f},lines={k}]")
            else:
                parts.append(f"{a.name}[x{rigid_scale(a, best['z'], best['boosts'].get(id(a), 1.0)):.2f}]")
        lines.append(f"  slot{i} w={c:.0f}: " + ", ".join(parts))
    vis = {a.name for s in best["slots"] for a in s} | set(best["overlays_shown"])
    lines.append("  hidden: " + ", ".join(a.name for a in atoms if a.name not in vis))
    lines.append("  terms: " + ", ".join(f"{k}={v:.2f}" for k, v in best["terms"].items()))
    return "\n".join(lines)


def check(out, src):
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    probs = []
    assert [e["id"] for e in out["elements"]] == [e["id"] for e in src["elements"]]
    by = {e["id"]: e for e in src["elements"]}
    for e in out["elements"]:
        if e["x"] < -0.5 or e["y"] < -0.5 or e["x"] + e["width"] > W + 0.5 or e["y"] + e["height"] > H + 0.5:
            probs.append(f"off-canvas {e['id']}")
        s = by[e["id"]]
        if e["type"] == "image" and s.get("fit", "contain") != "cover":
            r0, r1 = s["width"] / s["height"], e["width"] / e["height"]
            if abs(r1 / r0 - 1) > 0.05:
                probs.append(f"aspect {e['id']} {r0:.3f}->{r1:.3f}")
    return probs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    samples = {
        "L1": "chameleon_sample_level1_warmup.json",
        "L2": "chameleon_sample_level2_core.json",
        "L3": "chameleon_sample_level3_advanced.json",
    }
    extra = [(728, 90), (1600, 400), (1080, 1920), (1080, 1080), (300, 250), (1280, 720), (160, 600)]
    jobs = []
    for tag, fn in samples.items():
        task = json.loads((ROOT / "input" / fn).read_text())
        jobs.append((tag, task["source"], task["target_canvas"]["width"], task["target_canvas"]["height"], True))
        if "--all" in sys.argv:
            for W, H in extra:
                if (W, H) != (task["target_canvas"]["width"], task["target_canvas"]["height"]):
                    jobs.append((tag, task["source"], W, H, False))
    for tag, src, W, H, primary in jobs:
        out, best, atoms = solve(src, W, H)
        name = f"{tag}_{W}x{H}"
        (OUT / f"{name}.json").write_text(json.dumps(out, indent=1))
        t = time.time()
        render_design_to_png(out, str(ASSETS), str(OUT / f"{name}.png"))
        probs = check(out, src)
        print(f"{name}{' (official target)' if primary else ''}  render={time.time() - t:.2f}s  checks={'OK' if not probs else probs}")
        print(describe(best, atoms))


if __name__ == "__main__":
    main()
