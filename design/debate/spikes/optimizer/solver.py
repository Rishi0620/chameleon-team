"""OPTIMIZER spike v2: structured-search retargeting solver.

NOT production code. It exists to de-risk the claims in round1/optimizer.md:
  1. Text becomes an exact discrete (width,height) frontier via the renderer's
     own wrap.py + skia metrics, cheaply.
  2. With a shared type scale `z`, feasibility is monotone in z, so for a fixed
     discrete topology the best continuous solution is found by bisection.
  3. Enumerating discrete structure (slot partition x visible set x image
     scale) is cheap enough to be (nearly) exhaustive for real ad designs.
  4. Dropping emerges from the energy (copy budget, legibility, hierarchy),
     not from per-size if/else rules.

v1 (solver_v1.py, out_v1/) is kept on purpose: it shows the classic
"technically valid but ugly" failure of a pure max-zoom objective.

Role inference here is crude feature heuristics (never ids).

Run from repo root:
    .venv/bin/python design/debate/spikes/optimizer/solver.py          # 3 official targets
    .venv/bin/python design/debate/spikes/optimizer/solver.py --all    # + 7 extra catalogue sizes each
"""
from __future__ import annotations

import itertools
import json
import math
import re
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
OUT = Path(__file__).resolve().parent / "out"

KMAX = 4  # max lines considered for any text block
Z_CAP_MULT = 1.5  # round 2: 1.0 reproduces GALLEY's s_cap and restores the fixed point

# energy weights (hand-set for the spike; production: fitted to VLM pairwise preferences)
W = dict(
    drop=1.6,     # per unit importance of a hidden atom
    size=1.0,     # per unit importance: log(scale / z_ref)
    leg=4.0,      # legibility hinge below comfortable px size
    copy=3.0,     # visible copy exceeds the canvas' reading budget
    lines=0.12,   # per line beyond 2 for primary text
    breaks=0.15,  # per line beyond the source's own line count (line-break faithfulness)
    widow=0.08,   # last line < 30% of longest
    slots=0.06,   # per extra slot (Occam)
    ratio=0.25,   # |log(image scale / type scale)|: image-vs-type proportion drift
    imgord=0.5,   # source-larger image became smaller
    fill=0.8,     # content covers too little of the canvas
    order=0.1,    # per inversion of source reading order
)


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
    out, cur = [], 0.0
    for c, w in zip(wrap_text(el["content"], ws, width), ws):
        if c == "\n":
            out.append(cur)
            cur = 0.0
        else:
            cur += w
    return out + [cur]


def max_word(el, f):
    best = cur = 0.0
    for c, w in zip(el["content"], cwidths(el, f)):
        cur = 0.0 if c == " " else cur + w
        best = max(best, cur)
    return best


def W_k(el, f, k):
    """Minimal box width so greedy wrap at integer font f yields <= k lines (to 0.25px)."""
    key = (id(el), f, k)
    if key in _wk:
        return _wk[key]
    total = sum(cwidths(el, f)) + 0.5
    lo = max_word(el, f) + 0.5
    if k == 1:
        res = total
    elif n_lines(el, f, lo) <= k:
        res = lo
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


def eff(el, f):
    """Perceived size: bold reads ~15% larger."""
    return f * (1.15 if _normalize_weight(el.get("font_weight")) in _BOLD_WEIGHTS else 1.0)


# ----------------------------------------------------------------------------
# atoms
# ----------------------------------------------------------------------------
_bbox_cache = {}


def asset_alpha_bbox(asset_id):
    if asset_id in _bbox_cache:
        return _bbox_cache[asset_id]
    p = ASSETS / str(asset_id)
    res = None
    if p.is_file():
        im = Image.open(p)
        bb = im.getchannel("A").getbbox() if im.mode == "RGBA" else (0, 0, *im.size)
        res = (im.size, bb or (0, 0, *im.size))
    _bbox_cache[asset_id] = res
    return res


@dataclass(eq=False)
class Atom:
    kind: str                      # text | image | pill | cluster | rigid | sticker
    els: list
    imp: float = 0.5
    order: float = 0.0
    anchored: tuple | None = None  # (hx, vy) corner for overlay atoms
    members: list = field(default_factory=list)
    floor: int = 10
    fsrc: float = 1.0
    gap_src: float = 0.0
    k_pref: int = 1

    @property
    def name(self):
        return "+".join(e["id"] for e in self.els)

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


def label_el(atom):
    if atom.kind == "text":
        return atom.els[0]
    if atom.kind == "pill":
        return pill_parts(atom)[1]
    if atom.kind == "cluster":
        return pill_parts(atom.members[0])[1]
    return None


def pill_font(atom, z):
    return max(atom.floor, round(z * pill_parts(atom)[1]["font_size"]))


def font_of(atom, z):
    if atom.kind == "text":
        return max(atom.floor, round(z * atom.fsrc))
    if atom.kind == "pill":
        return pill_font(atom, z)
    if atom.kind == "cluster":
        return pill_font(atom.members[0], z)
    return None


def image_box(e, rho):
    """box w,h and transparent padding (l,t,r,b) for a contain-fit image at absolute scale rho."""
    w, h = e["width"] * rho, e["height"] * rho
    info = asset_alpha_bbox(e.get("asset_id"))
    if info is None or e.get("fit", "contain") != "contain":
        return w, h, (0.0, 0.0, 0.0, 0.0)
    (aw, ah), (bx0, by0, bx1, by1) = info
    s = min(w / aw, h / ah)
    ox, oy = (w - aw * s) / 2, (h - ah * s) / 2
    return w, h, (ox + bx0 * s, oy + by0 * s, w - (ox + bx1 * s), h - (oy + by1 * s))


def rigid_size(atom, z, rho=None):
    """(box_w, box_h, vis_w, vis_h, pad) of a non-text atom."""
    if atom.kind == "image":
        w, h, pad = image_box(atom.els[0], rho)
        return w, h, w - pad[0] - pad[2], h - pad[1] - pad[3], pad
    if atom.kind == "pill":
        shape, label = pill_parts(atom)
        f = pill_font(atom, z)
        s = f / label["font_size"]
        h = shape["height"] * s
        w = sum(cwidths(label, f)) + 0.9 * h   # min-content width (label + end caps)
        return w, h, w, h, (0.0, 0.0, 0.0, 0.0)
    if atom.kind == "cluster":
        sizes = [rigid_size(m, z) for m in atom.members]
        s = font_of(atom, z) / label_el(atom)["font_size"]
        w = sum(sz[0] for sz in sizes) + atom.gap_src * s * (len(sizes) - 1)
        h = max(sz[1] for sz in sizes)
        return w, h, w, h, (0.0, 0.0, 0.0, 0.0)
    x, y, w, h = atom.src_box()
    texts = [e for e in atom.els if e["type"] == "text"]
    s = z
    if texts:
        s = max(s, max(atom.floor / t["font_size"] for t in texts))
    return w * s, h * s, w * s, h * s, (0.0, 0.0, 0.0, 0.0)


def rigid_scale(atom, z, rho=None):
    if atom.kind == "image":
        return rho
    if atom.kind in ("pill", "cluster"):
        return font_of(atom, z) / label_el(atom)["font_size"]
    return rigid_size(atom, z)[0] / atom.src_box()[2]


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
        if e["width"] * e["height"] >= 0.85 * cw * ch and e["type"] in ("image", "shape"):
            bg.append(e)
        elif e["type"] == "shape":
            decor.append(e)
        elif e["type"] == "image" and asset_alpha_bbox(e.get("asset_id")) is None:
            hidden.append(e)  # missing asset: never show a broken placeholder
        else:
            atoms.append(Atom(e["type"], [e], floor=main_floor))

    texts = [a for a in atoms if a.kind == "text"]
    pmax = max((eff(a.els[0], a.els[0]["font_size"]) for a in texts), default=1)
    for a in atoms:
        x, y, w, h = a.src_box()
        a.order = (y + h / 2) / ch + 0.001 * (x / cw)
        if a.kind == "text":
            e = a.els[0]
            p = eff(e, e["font_size"]) / pmax
            a.fsrc = e["font_size"]
            a.k_pref = n_lines(e, int(e["font_size"]), e["width"])
            if p < 0.4 and len(e["content"]) > 60:
                a.imp, a.floor = 0.12, fine_floor
            else:
                a.imp = 0.35 + 0.65 * p ** 1.5
        elif a.kind == "image":
            a.imp = 0.9 if (w / h >= 2.0 or w * h < 0.06 * cw * ch) else 0.65
        elif a.kind == "sticker":
            a.imp = 0.25
        else:
            a.imp = 0.3
    pills = [a for a in atoms if a.kind == "pill"]
    if pills:
        max(pills, key=lambda a: pill_parts(a)[0]["width"] * pill_parts(a)[0]["height"]).imp = 0.85
    rest = sorted([a for a in pills if a.imp < 0.85], key=lambda a: a.src_box()[0])
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
            c = Atom("cluster", [e for b in row for e in b.els], imp=0.3, floor=main_floor, members=row)
            bx = [b.src_box() for b in row]
            c.gap_src = sum(bx[i + 1][0] - (bx[i][0] + bx[i][2]) for i in range(len(bx) - 1)) / (len(bx) - 1)
            x, y, w, h = c.src_box()
            c.order = (y + h / 2) / ch
            atoms.append(c)
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
def slot_at(slot, z, rhos, c, H_av, m, gap):
    """Heights/details of a slot laid out at width c. Returns (vis_h, det) or None."""
    h, det = gap * (len(slot) - 1), {}
    for i, a in enumerate(slot):
        if a.kind == "text":
            f = font_of(a, z)
            if max_word(a.els[0], f) + 0.5 > c:
                return None
            k = lines_at(a.els[0], f, c)
            if k is None:
                return None
            th = text_h(a.els[0], f, k)
            det[id(a)] = ("t", f, k, th)
            h += th
        else:
            bw, bh, vw, vh, pad = rigid_size(a, z, rhos.get(id(a)))
            if vw > c + 0.01:
                return None
            det[id(a)] = ("r", bw, bh, vw, vh, pad)
            h += vh
            if i == 0:
                h += max(0.0, pad[1] - m)       # transparent top padding must stay on canvas
            if i == len(slot) - 1:
                h += max(0.0, pad[3] - m)
    return (h, det) if h <= H_av else None


def min_slot_width(slot, z, rhos, H_av, W_av, m, gap):
    lo = 0.0
    for a in slot:
        if a.kind == "text":
            lo = max(lo, max_word(a.els[0], font_of(a, z)) + 0.5)
        else:
            bw, bh, vw, vh, pad = rigid_size(a, z, rhos.get(id(a)))
            if bh > H_av + 2 * m or bw > W_av + 2 * m:
                return None
            lo = max(lo, vw)
    cands = {lo}
    for a in slot:
        if a.kind == "text":
            f = font_of(a, z)
            cands.update(W_k(a.els[0], f, k) for k in range(1, KMAX + 1))
    for c in sorted(x for x in cands if x >= lo):
        if c > W_av:
            return None
        r = slot_at(slot, z, rhos, c, H_av, m, gap)
        if r is not None:
            return c
    return None


def overhang(slot, z, rhos, c):
    """How far transparent image padding pokes out of the slot's left/right edge."""
    ol = orr = 0.0
    for a in slot:
        if a.kind == "image":
            bw, bh, vw, vh, pad = rigid_size(a, z, rhos.get(id(a)))
            slack = (c - vw) / 2
            ol, orr = max(ol, pad[0] - slack), max(orr, pad[2] - slack)
    return ol, orr


def row_feasible(slots, z, rhos, Wc, Hc, m, gap):
    H_av, W_av = Hc - 2 * m, Wc - 2 * m
    widths = []
    for s in slots:
        c = min_slot_width(s, z, rhos, H_av, W_av, m, gap)
        if c is None:
            return None
        widths.append(c)
    ol = overhang(slots[0], z, rhos, widths[0])[0]
    orr = overhang(slots[-1], z, rhos, widths[-1])[1]
    need = sum(widths) + 1.5 * gap * (len(slots) - 1) + max(m, ol) + max(m, orr)
    return widths if need <= Wc else None


def max_zoom(slots, rhos, Wc, Hc, m_fn, z_cap):
    def feas(z):
        m, g = m_fn(z)
        return row_feasible(slots, z, rhos, Wc, Hc, m, g)

    lo, hi = 0.03, z_cap
    if feas(lo) is None:
        return None
    if feas(hi) is not None:
        return hi
    for _ in range(14):
        mid = math.sqrt(lo * hi)
        if feas(mid) is None:
            hi = mid
        else:
            lo = mid
    return lo


def widen(slots, widths, z, rhos, Wc, Hc, m, gap):
    """Spend leftover row width on fewer text lines (toward source line counts)."""
    widths = list(widths)
    H_av = Hc - 2 * m

    def leftover():
        ol = overhang(slots[0], z, rhos, widths[0])[0]
        orr = overhang(slots[-1], z, rhos, widths[-1])[1]
        return Wc - (sum(widths) + 1.5 * gap * (len(slots) - 1) + max(m, ol) + max(m, orr))

    while True:
        best = None
        for j, s in enumerate(slots):
            for a in s:
                if a.kind != "text":
                    continue
                f = font_of(a, z)
                k = lines_at(a.els[0], f, widths[j])
                if k is None or k <= a.k_pref:
                    continue
                need = W_k(a.els[0], f, k - 1)
                cost = need - widths[j]
                if cost <= leftover() and (best is None or cost < best[0]):
                    best = (cost, j, need)
        if best is None:
            return widths
        widths[best[1]] = best[2]
        if slot_at(slots[best[1]], z, rhos, widths[best[1]], H_av, m, gap) is None:
            return widths


# ----------------------------------------------------------------------------
# energy
# ----------------------------------------------------------------------------
def hierarchy_ok(vis, z):
    """Hard ordinal constraint: if A read clearly bigger than B in the source, it still must."""
    items = [(a, label_el(a), font_of(a, z)) for a in vis if label_el(a) is not None]
    for (a, ea, fa), (b, eb, fb) in itertools.permutations(items, 2):
        r_src = eff(ea, ea["font_size"]) / eff(eb, eb["font_size"])
        if r_src >= 1.1:
            need = min(1.25, 1 + 0.5 * (r_src - 1))
            if eff(ea, fa) < need * eff(eb, fb) - 1e-6:
                return False
    return True


def energy(sol, flow_all, Wc, Hc, z_ref):
    slots, z, rhos, dets = sol["slots"], sol["z"], sol["rhos"], sol["dets"]
    vis = [a for s in slots for a in s]
    t = dict.fromkeys(W, 0.0)
    t["drop"] = W["drop"] * sum(a.imp for a in flow_all if a not in vis)
    f_comf = max(14.0, 0.018 * max(Wc, Hc))
    chars = 0
    for s, (c, det) in zip(slots, dets):
        for a in s:
            d = det[id(a)]
            if a.kind == "text":
                _, f, k, _ = d
                scale = f / a.fsrc
                chars += len(a.els[0]["content"])
                if a.imp > 0.3:
                    t["lines"] += W["lines"] * max(0, k - 2) * a.imp
                    t["breaks"] += W["breaks"] * max(0, k - a.k_pref) * a.imp
                if k > 1:
                    lw = line_widths(a.els[0], f, c)
                    if lw[-1] < 0.3 * max(lw):
                        t["widow"] += W["widow"] * a.imp
            else:
                scale = rigid_scale(a, z, rhos.get(id(a)))
                if a.kind == "image":
                    t["ratio"] += W["ratio"] * abs(math.log(scale / z)) * a.imp
            lab = label_el(a)
            if lab is not None:
                f = font_of(a, z)
                if a.kind != "text":
                    chars += len(lab["content"])
                floor_c = f_comf if a.imp > 0.2 else 0.7 * f_comf
                t["leg"] += W["leg"] * a.imp * max(0.0, (floor_c - f) / floor_c) ** 2
            t["size"] -= W["size"] * a.imp * math.log(scale / z_ref)
    # copy budget: characters x comfortable glyph area vs half the canvas
    load = chars * f_comf * f_comf * 0.55 / (Wc * Hc)
    t["copy"] = W["copy"] * max(0.0, load - 0.5)
    t["slots"] = W["slots"] * (len(slots) - 1)
    seq = [a.order for a in vis]
    t["order"] = W["order"] * sum(1 for i in range(len(seq)) for j in range(i + 1, len(seq)) if seq[i] > seq[j])
    imgs = [a for a in vis if a.kind == "image"]
    for a, b in itertools.permutations(imgs, 2):
        sa = a.els[0]["width"] * a.els[0]["height"]
        sb = b.els[0]["width"] * b.els[0]["height"]
        ta = sa * rhos[id(a)] ** 2
        tb = sb * rhos[id(b)] ** 2
        if sa >= 1.5 * sb and ta < tb:
            t["imgord"] += W["imgord"] * math.log(tb / ta + 1)
    cov = 0.0
    for s, (c, det) in zip(slots, dets):
        cov += c * sum(d[3] if d[0] == "t" else d[4] for d in (det[id(a)] for a in s))
    t["fill"] = W["fill"] * max(0.0, 0.3 - cov / (Wc * Hc))
    return sum(t.values()), t


# ----------------------------------------------------------------------------
# search
# ----------------------------------------------------------------------------
def partitions(seq, k):
    n = len(seq)
    for cuts in itertools.combinations(range(1, n), k - 1):
        b = (0,) + cuts + (n,)
        yield [seq[b[i]:b[i + 1]] for i in range(k)]


def image_options(a, Wc, Hc, m, z_ref):
    e = a.els[0]
    fit_max = min((Wc - 2 * m) / e["width"], (Hc - 2 * m) / e["height"])
    fl = lambda v: math.floor(v * 1e4) / 1e4  # never round UP past the canvas
    opts = {fl(z_ref * k) for k in (0.5, 0.7, 1.0, 1.4, 2.0)} | {fl(fit_max), fl(0.8 * fit_max)}
    min_side = max(16.0, 0.04 * max(Wc, Hc))  # recognisability floor on VISIBLE pixels
    good = []
    for r in sorted(opts):
        if r > fit_max * 1.0001:
            continue
        w, h, pad = image_box(e, r)
        if min(w - pad[0] - pad[2], h - pad[1] - pad[3]) >= min_side:
            good.append(r)
    return good


def solve(src, Wc, Hc, keep_top=6):
    """Lexicographic relaxation: try strict constraints first, relax only if nothing is feasible."""
    global KMAX
    t0 = time.time()
    for level, (kmax, floor_mult, must_imp) in enumerate([(4, 1.0, 0.8), (6, 0.85, 0.8), (6, 0.85, 0.95)]):
        KMAX = kmax
        _wk.clear()
        res = _solve(src, Wc, Hc, keep_top, floor_mult, must_imp)
        if res is not None:
            res[1]["relax_level"] = level
            res[1]["time"] = time.time() - t0
            return res
    return fallback(src, Wc, Hc)


def fallback(src, Wc, Hc):
    """Never fail: contain-fit the whole source composition (uniform scale, centred), bg = cover."""
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    s = min(Wc / Ws, Hc / Hs)
    ox, oy = (Wc - Ws * s) / 2, (Hc - Hs * s) / 2
    els = []
    for e in src["elements"]:
        if e["width"] * e["height"] >= 0.85 * Ws * Hs:
            els.append(dict(e, x=0, y=0, width=Wc, height=Hc))
            continue
        ne = dict(e, x=ox + e["x"] * s, y=oy + e["y"] * s, width=e["width"] * s, height=e["height"] * s)
        if e["type"] == "text":
            ne["font_size"] = max(1, round(e["font_size"] * s))
        els.append(clamp(ne, Wc, Hc))
    return {"canvas": {"width": Wc, "height": Hc}, "elements": els}, {"fallback": True}, [], []


def _solve(src, Wc, Hc, keep_top, floor_mult, must_imp):
    t0 = time.time()
    bg, decor, hidden_els, atoms = build_atoms(src, Wc, Hc)
    for a in atoms:
        a.floor = max(6, round(a.floor * floor_mult))
    flow = [a for a in atoms if a.anchored is None]
    overlays = [a for a in atoms if a.anchored is not None]
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    z_ref = math.sqrt(Wc * Hc / (Ws * Hs))
    z_cap = max(Z_CAP_MULT * z_ref, 1.0)  # area-scale is a bad text reference at extreme ratios; feasibility bounds it anyway
    base = 0.03 * min(Ws, Hs)

    def m_fn(z):
        g = max(4.0, base * z)
        return max(g, 0.035 * min(Wc, Hc)), g

    must = [a for a in flow if a.imp >= must_imp]
    optional = sorted([a for a in flow if a.imp < must_imp], key=lambda a: -a.imp)
    aspect = Wc / Hc
    max_slots = 1 if aspect < 0.8 else (2 if aspect < 1.6 else (3 if aspect < 3 else 4))
    m0 = m_fn(z_ref)[0]
    cands, n_cfg = [], 0
    if len(optional) <= 6:   # all subsets (<= 64); production: prefix + 1-swap neighbourhood beyond that
        subsets = [list(c) for r in range(len(optional) + 1) for c in itertools.combinations(optional, r)]
    else:
        subsets = [optional[:k] for k in range(len(optional) + 1)]
    for sub in subsets:
        vis = sorted(must + sub, key=lambda a: a.order)
        vis_imgs = [a for a in vis if a.kind == "image"]
        opts = [image_options(a, Wc, Hc, m0, z_ref) for a in vis_imgs]
        if any(not o for o in opts):
            continue  # an image that can't be shown recognisably can't be in this visible set
        for combo in itertools.product(*opts):
            rhos = {id(a): r for a, r in zip(vis_imgs, combo)}
            for k in range(1, min(max_slots, len(vis)) + 1):
                for slots in partitions(vis, k):
                    n_cfg += 1
                    z = max_zoom(slots, rhos, Wc, Hc, m_fn, z_cap)
                    if z is None or not hierarchy_ok(vis, z):
                        continue
                    m, g = m_fn(z)
                    widths = row_feasible(slots, z, rhos, Wc, Hc, m, g)
                    widths = widen(slots, widths, z, rhos, Wc, Hc, m, g)
                    dets = []
                    for s, c in zip(slots, widths):
                        h, det = slot_at(s, z, rhos, c, Hc - 2 * m, m, g)
                        dets.append((c, det))
                    sol = dict(slots=slots, z=z, rhos=rhos, widths=widths, dets=dets, m=m, gap=g)
                    sol["E"], sol["terms"] = energy(sol, flow, Wc, Hc, z_ref)
                    cands.append(sol)
    if not cands:
        return None
    cands.sort(key=lambda s: s["E"])
    best = cands[0]
    elements, shown = realize(best, Wc, Hc, src, bg, decor, overlays)
    best["E_overlay"] = W["drop"] * sum(a.imp for a in overlays if a not in shown)
    best.update(time=time.time() - t0, n_cfg=n_cfg, overlays_shown=[a.name for a in shown])
    return {"canvas": {"width": Wc, "height": Hc}, "elements": elements}, best, atoms, cands[:keep_top]


# ----------------------------------------------------------------------------
# placement
# ----------------------------------------------------------------------------
def pill_pref_width(a, z, avail):
    """Elastic pill: grow from min-content toward the source's proportions, never past `avail`."""
    shape, label = pill_parts(a)
    f = pill_font(a, z)
    tight = rigid_size(a, z)[0]
    return max(tight, min(shape["width"] * f / label["font_size"], avail))


def place_pill(a, bx, by, bw, bh, z, out):
    shape, label = pill_parts(a)
    f = pill_font(a, z)
    asc, desc, cap = metrics(label, f)
    out[shape["id"]] = dict(shape, x=bx, y=by, width=bw, height=bh,
                            corner_radius=shape.get("corner_radius", 0) * bh / shape["height"])
    ly = by + bh / 2 - asc + cap / 2  # optical centring on cap height (real font metrics)
    out[label["id"]] = dict(label, x=bx, y=ly, width=bw, height=asc + desc, font_size=f)


def place_rigid(a, bx, by, bw, bh, z, out):
    if a.kind == "image":
        out[a.els[0]["id"]] = dict(a.els[0], x=bx, y=by, width=bw, height=bh)
    elif a.kind == "pill":
        place_pill(a, bx, by, bw, bh, z, out)
    elif a.kind == "cluster":
        s = font_of(a, z) / label_el(a)["font_size"]
        cx = bx
        for mbr in a.members:
            w, h, *_ = rigid_size(mbr, z)
            place_pill(mbr, cx, by + (bh - h) / 2, w, h, z, out)
            cx += w + a.gap_src * s
    else:
        x0, y0, w0, h0 = a.src_box()
        s = bw / w0
        for e in a.els:
            ne = dict(e, x=bx + (e["x"] - x0) * s, y=by + (e["y"] - y0) * s, width=e["width"] * s, height=e["height"] * s)
            if e["type"] == "text":
                ne["font_size"] = max(1, round(e["font_size"] * s))
            if e.get("corner_radius"):
                ne["corner_radius"] = e["corner_radius"] * s
            out[e["id"]] = ne


def transparent(color):
    m = re.match(r"rgba?\(([^,]+),([^,]+),([^,)]+)", (color or "rgba(0,0,0,1)").replace(" ", ""))
    return f"rgba({m.group(1)},{m.group(2)},{m.group(3)},0)" if m else "rgba(0,0,0,0)"


def hide(e, src, Wc, Hc):
    """Honest drop. NB: the renderer IGNORES `opacity` on text (spike hide_test.py),
    so text also needs a fully transparent colour (incl. style_runs)."""
    sx, sy = Wc / src["canvas"]["width"], Hc / src["canvas"]["height"]
    s = min(sx, sy)
    cx, cy = (e["x"] + e["width"] / 2) * sx, (e["y"] + e["height"] / 2) * sy
    ne = dict(e, x=cx - e["width"] * s / 2, y=cy - e["height"] * s / 2, width=e["width"] * s, height=e["height"] * s, opacity=0)
    if e["type"] == "text":
        ne["font_size"] = max(1, round(e["font_size"] * s))
        ne["color"] = transparent(e.get("color"))
        if e.get("style_runs"):
            ne["style_runs"] = [dict(r, color=transparent(r["color"])) if "color" in r else r for r in e["style_runs"]]
    return clamp(ne, Wc, Hc)


def realize(sol, Wc, Hc, src, bg, decor, overlays):
    slots, z, rhos, m, gap = sol["slots"], sol["z"], sol["rhos"], sol["m"], sol["gap"]
    out = {}
    for e in bg:
        out[e["id"]] = dict(e, x=0, y=0, width=Wc, height=Hc)
    widths = [c for c, _ in sol["dets"]]
    n = len(slots)
    ol = overhang(slots[0], z, rhos, widths[0])[0]
    orr = overhang(slots[-1], z, rhos, widths[-1])[1]
    ml, mr = max(m, ol), max(m, orr)
    left = Wc - ml - mr - sum(widths) - 1.5 * gap * (n - 1)
    xg = 1.5 * gap + (min(left / (n + 1), 3 * gap) if n > 1 else 0)
    x = ml + (Wc - ml - mr - sum(widths) - xg * (n - 1)) / 2
    vis_boxes = []
    src_h = src["canvas"]["height"]
    near_aspect = abs(math.log((Wc / Hc) / (src["canvas"]["width"] / src_h))) < math.log(2)
    for s, (c, det) in zip(slots, sol["dets"]):
        hs = [det[id(a)][3] if det[id(a)][0] == "t" else det[id(a)][4] for a in s]
        used = gap * (len(s) - 1) + sum(hs)
        H_av = Hc - 2 * m
        ex = H_av - used
        eg = min(ex / (len(s) + 1), gap) if len(s) > 1 else 0
        y = m + (ex - eg * (len(s) - 1)) / 2
        ys = None
        if n == 1 and near_aspect and len(s) > 1:
            # keep each atom near its SOURCE relative height: exact isotonic regression (PAVA)
            targets = [((a.src_box()[1] + a.src_box()[3] / 2) / src_h) * Hc for a in s]
            ys = pava_stack(targets, hs, gap, m, Hc - m, [a.imp for a in s])
        for i, a in enumerate(s):
            if ys is not None:
                y = ys[i]
            d = det[id(a)]
            if d[0] == "t":
                _, f, k, th = d
                out[a.els[0]["id"]] = dict(a.els[0], x=x, y=y, width=c, height=th, font_size=f)
                lw = max(line_widths(a.els[0], f, c))
                vis_boxes.append((x + (c - lw) / 2, y, lw, th))
                h = th
            else:
                _, bw, bh, vw, vh, pad = d
                if a.kind == "pill":
                    bw = vw = pill_pref_width(a, z, c)
                vx = x + (c - vw) / 2
                place_rigid(a, vx - pad[0], y - pad[1], bw, bh, z, out)
                vis_boxes.append((vx, y, vw, vh))
                h = vh
            y += h + gap + eg
        x += c + xg
    shown = []
    for a in overlays:
        bw, bh, *_ = rigid_size(a, z)
        ang = math.radians(max((abs(e.get("rotation", 0) or 0) for e in a.els), default=0))
        aw, ah = bw * math.cos(ang) + bh * math.sin(ang), bw * math.sin(ang) + bh * math.cos(ang)
        ox = m + (aw - bw) / 2 if a.anchored[0] == 0 else Wc - m - (aw + bw) / 2
        oy = 0.6 * m + (ah - bh) / 2 if a.anchored[1] == 0 else Hc - 0.6 * m - (ah + bh) / 2
        rect = (ox - (aw - bw) / 2, oy - (ah - bh) / 2, aw, ah)
        if not any(_overlap(rect, b) > 0 for b in vis_boxes) and aw <= Wc - 2 * m and ah <= Hc - m:
            place_rigid(a, ox, oy, bw, bh, z, out)
            shown.append(a)
    sx, sy = Wc / src["canvas"]["width"], Hc / src["canvas"]["height"]
    smin = min(sx, sy)
    for e in decor:
        cx, cy = (e["x"] + e["width"] / 2) * sx, (e["y"] + e["height"] / 2) * sy
        w, h = e["width"] * smin, e["height"] * smin
        out[e["id"]] = clamp(dict(e, x=cx - w / 2, y=cy - h / 2, width=w, height=h), Wc, Hc)
    for e in src["elements"]:
        if e["id"] not in out:
            out[e["id"]] = hide(e, src, Wc, Hc)
    for e in out.values():  # final safety: never off-canvas
        clamp(e, Wc, Hc)
    return [out[e["id"]] for e in src["elements"]], shown


def pava_stack(targets, hs, gap, lo, hi, wts):
    """argmin sum w_i (c_i - t_i)^2  s.t.  c_{i+1} - c_i >= (h_i + h_{i+1})/2 + gap,  stack within [lo, hi].
    Substituting s_i = c_i - off_i turns the separation constraints into s_1 <= s_2 <= ... (isotonic
    regression), solved exactly by pool-adjacent-violators; the common box bound is then a clip.
    Returns TOP y of each item."""
    off = [0.0]
    for i in range(1, len(hs)):
        off.append(off[-1] + (hs[i - 1] + hs[i]) / 2 + gap)
    blocks = []  # [mean, weight, count]
    for t, o, w in zip(targets, off, wts):
        blocks.append([t - o, w, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            b = blocks.pop()
            a = blocks[-1]
            a[0] = (a[0] * a[1] + b[0] * b[1]) / (a[1] + b[1])
            a[1] += b[1]
            a[2] += b[2]
    s = [b[0] for b in blocks for _ in range(b[2])]
    L, U = lo + hs[0] / 2, hi - hs[-1] / 2 - off[-1]
    s = [min(max(v, L), U) for v in s]
    return [v + o - h / 2 for v, o, h in zip(s, off, hs)]


def clamp(e, Wc, Hc):
    if e["width"] > Wc or e["height"] > Hc:
        s = min(Wc / e["width"], Hc / e["height"])
        e["width"] *= s
        e["height"] *= s
    e["x"] = min(max(e["x"], 0), Wc - e["width"])
    e["y"] = min(max(e["y"], 0), Hc - e["height"])
    return e


def _overlap(a, b):
    return max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])) * max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))


# ----------------------------------------------------------------------------
# reporting
# ----------------------------------------------------------------------------
def describe_sol(sol):
    parts = []
    for i, (s, (c, det)) in enumerate(zip(sol["slots"], sol["dets"])):
        items = []
        for a in s:
            d = det[id(a)]
            if d[0] == "t":
                items.append(f"{a.name}[f={d[1]},{d[2]}L]")
            elif a.kind == "image":
                items.append(f"{a.name}[x{sol['rhos'][id(a)]:.2f}]")
            else:
                items.append(f"{a.name}[f={font_of(a, sol['z'])}]")
        parts.append(f"S{i}({c:.0f}px): " + ", ".join(items))
    return " | ".join(parts)


def check(out, src):
    Wc, Hc = out["canvas"]["width"], out["canvas"]["height"]
    probs = []
    assert [e["id"] for e in out["elements"]] == [e["id"] for e in src["elements"]]
    by = {e["id"]: e for e in src["elements"]}
    for e in out["elements"]:
        if e["x"] < -0.5 or e["y"] < -0.5 or e["x"] + e["width"] > Wc + 0.5 or e["y"] + e["height"] > Hc + 0.5:
            probs.append(f"off-canvas {e['id']}")
        s = by[e["id"]]
        if e["type"] == "image" and s.get("fit", "contain") != "cover":
            r0, r1 = s["width"] / s["height"], e["width"] / e["height"]
            if abs(r1 / r0 - 1) > 0.05:
                probs.append(f"aspect {e['id']} {r0:.3f}->{r1:.3f}")
        if e["type"] == "text" and e["font_size"] < 1:
            probs.append(f"font<1 {e['id']}")
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
        tw, th = task["target_canvas"]["width"], task["target_canvas"]["height"]
        jobs.append((tag, task["source"], tw, th, True))
        if "--all" in sys.argv:
            jobs += [(tag, task["source"], w, h, False) for w, h in extra if (w, h) != (tw, th)]
    log = []
    for tag, src, Wc, Hc, primary in jobs:
        out, best, atoms, top = solve(src, Wc, Hc)
        name = f"{tag}_{Wc}x{Hc}"
        if best.get("fallback"):
            (OUT / f"{name}.json").write_text(json.dumps(out, indent=1))
            render_design_to_png(out, str(ASSETS), str(OUT / f"{name}.png"))
            log.append(f"{name}: FALLBACK (uniform contain-fit)")
            print(log[-1])
            continue
        (OUT / f"{name}.json").write_text(json.dumps(out, indent=1))
        t = time.time()
        render_design_to_png(out, str(ASSETS), str(OUT / f"{name}.png"))
        probs = check(out, src)
        vis = {a.name for s in best["slots"] for a in s} | set(best["overlays_shown"])
        lines = [
            f"{name}{'  (official target)' if primary else ''}: solve={best['time']:.2f}s configs={best['n_cfg']} relax={best['relax_level']} "
            f"render={time.time() - t:.2f}s checks={'OK' if not probs else probs}",
            f"  best  E={best['E']:.3f} (+{best['E_overlay']:.2f} hidden overlays) z={best['z']:.3f}  {describe_sol(best)}",
            f"  overlays shown: {best['overlays_shown'] or '-'};  hidden: {', '.join(a.name for a in atoms if a.name not in vis) or '-'}",
            "  terms: " + ", ".join(f"{k}={v:.2f}" for k, v in best["terms"].items() if abs(v) > 1e-9),
        ]
        seen = {describe_sol(best)}
        for s in top[1:]:
            d = describe_sol(s)
            if d not in seen:
                seen.add(d)
                lines.append(f"  alt   E={s['E']:.3f} z={s['z']:.3f}  {d}")
        print("\n".join(lines), flush=True)
        log += lines
    (OUT / ("log_all.txt" if "--all" in sys.argv else "log.txt")).write_text("\n".join(log) + "\n")


if __name__ == "__main__":
    main()
