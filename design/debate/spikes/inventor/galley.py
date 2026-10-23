"""GALLEY spike (INVENTOR agent) -- "a design is a paragraph".

Decompile a source design into a typesetting galley:
  canvas layer (background)  |  texture (ornaments)  |  furniture (corner stickers)
  and a STREAM of content units in reading order, each with a 'rent'
  (how much type-scale it is allowed to cost before it is deferred/omitted).
Then re-typeset the stream for a target canvas by enumerating every
order-preserving 3-level break pattern (stack '/', column '|', row '¶') and every
priority-ordered omission set, fitting each with a max type-scale bisection,
and choosing the best by  J = log(s*) + sum(rent of kept) - penalties.

Spike quality: no ids are used for decisions (only printed); all thresholds are
hand-set. Run from anywhere:  .venv/bin/python design/debate/spikes/inventor/galley.py
"""
from __future__ import annotations

import itertools
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from renderer.converter.brand_fonts import load_brand_font_manager  # noqa: E402
from renderer.converter.convert import render_design_to_png  # noqa: E402
from renderer.converter.wrap import char_widths, wrap_text  # noqa: E402

FM = load_brand_font_manager(str(ROOT / "brand_kit" / "fonts"))
ASSETS = ROOT / "brand_kit" / "assets"
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

INF = float("inf")

# ----------------------------------------------------------------------------
# Measurement (exactly what the renderer will draw)
# ----------------------------------------------------------------------------

def style_of(el):
    bold = el.get("font_weight") == "bold"
    it = el.get("font_style") == "italic"
    weight = "bold" if bold else "regular"
    style = "bolditalic" if bold and it else "bold" if bold else "italic" if it else "regular"
    return weight, style


_cw: dict = {}


def widths_of(el, fs):
    weight, style = style_of(el)
    key = (el["font_family"], weight, style, fs, el["content"])
    if key not in _cw:
        _cw[key] = char_widths(FM, el["font_family"], weight, style, fs, el["content"])
    return _cw[key]


_mt: dict = {}


def measure(el, fs, width):
    """-> (n_lines, max_line_width, height). fs is truncated to int like skia does."""
    fs = max(1, int(fs))
    width = int(width)
    key = (el["id"], fs, width)
    if key in _mt:
        return _mt[key]
    ws = widths_of(el, fs)
    wrapped = wrap_text(el["content"], ws, width)
    lines = [0.0]
    for c, w in zip(wrapped, ws):
        if c == "\n":
            lines.append(0.0)
        else:
            lines[-1] += w
    lh = float(el.get("line_height", 1.2))
    res = (len(lines), max(lines), len(lines) * fs * lh)
    _mt[key] = res
    return res


def min_word_w(el, fs):
    ws = widths_of(el, max(1, int(fs)))
    best = cur = 0.0
    for c, w in zip(el["content"], ws):
        if c == " ":
            best, cur = max(best, cur), 0.0
        else:
            cur += w
    return max(best, cur)


def one_line_w(el, fs):
    return sum(widths_of(el, max(1, int(fs))))


_ink: dict = {}


def asset_info(asset_id):
    if asset_id in _ink:
        return _ink[asset_id]
    p = ASSETS / str(asset_id)
    if not p.is_file():
        _ink[asset_id] = None
        return None
    im = Image.open(p).convert("RGBA")
    a = np.array(im)[..., 3]
    ys, xs = np.nonzero(a > 8)
    W, H = im.size
    info = ((xs.min() / W, ys.min() / H, (xs.max() + 1) / W, (ys.max() + 1) / H), (W, H))
    _ink[asset_id] = info
    return info


def image_ink_rel(el):
    """Ink rect of an image element as fractions of its own box."""
    info = asset_info(el.get("asset_id"))
    if info is None or el.get("fit", "contain") != "contain":
        return (0.0, 0.0, 1.0, 1.0)
    (ax0, ay0, ax1, ay1), (aw, ah) = info
    bw, bh = el["width"], el["height"]
    sc = min(bw / aw, bh / ah)
    rw, rh = aw * sc, ah * sc
    ox, oy = (bw - rw) / 2, (bh - rh) / 2
    return ((ox + ax0 * rw) / bw, (oy + ay0 * rh) / bh, (ox + ax1 * rw) / bw, (oy + ay1 * rh) / bh)


def rot_aabb(x, y, w, h, deg):
    if not deg:
        return (x, y, x + w, y + h)
    t = math.radians(deg)
    c, s = abs(math.cos(t)), abs(math.sin(t))
    W, H = w * c + h * s, w * s + h * c
    cx, cy = x + w / 2, y + h / 2
    return (cx - W / 2, cy - H / 2, cx + W / 2, cy + H / 2)


def ink_box(el):
    x, y, w, h = el["x"], el["y"], el["width"], el["height"]
    if el["type"] == "text":
        n, mw, th = measure(el, el["font_size"], w)
        al = el.get("text_align", "left")
        x0 = x + (w - mw) / 2 if al == "center" else x + (w - mw) if al == "right" else x
        return (x0, y, x0 + mw, y + th)
    if el["type"] == "image":
        fx0, fy0, fx1, fy1 = image_ink_rel(el)
        return rot_aabb(x + fx0 * w, y + fy0 * h, (fx1 - fx0) * w, (fy1 - fy0) * h, el.get("rotation", 0))
    return rot_aabb(x, y, w, h, el.get("rotation", 0))


def union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def overlap(a, b, pad=0.0):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def is_accent(el):
    """Short bold text in a saturated (non-neutral) colour -- a text-only call to action."""
    try:
        r, g_, b = [float(v) for v in el.get("color", "").split("(")[1].split(",")[:3]]
    except (IndexError, ValueError):
        return False
    return el.get("font_weight") == "bold" and (max(r, g_, b) - min(r, g_, b)) > 90


def eff_alpha(el):
    a = float(el.get("opacity", 1.0))
    fc = el.get("fill_color", "")
    if fc.startswith("rgba"):
        try:
            a *= float(fc.rsplit(",", 1)[1].strip(" )"))
        except ValueError:
            pass
    return a


# ----------------------------------------------------------------------------
# Decompiler: design -> galley
# ----------------------------------------------------------------------------

@dataclass
class Unit:
    name: str
    kind: str                 # text | image | rigid
    els: list
    ink: tuple                # source ink box
    box: tuple                # source element-union box (rigid)
    rent: float = 0.0
    role_hint: str = ""
    corner: str = ""          # for furniture

    @property
    def fs0(self):
        fss = [e["font_size"] for e in self.els if e["type"] == "text"]
        return min(fss) if fss else None


@dataclass
class Galley:
    W0: int
    H0: int
    background: list = field(default_factory=list)
    texture: list = field(default_factory=list)
    furniture: list = field(default_factory=list)
    stream: list = field(default_factory=list)
    hidden: list = field(default_factory=list)   # e.g. unresolvable assets
    src_labels: list = field(default_factory=list)
    base_gap: float = 30.0
    rho: float = 0.5
    src_gap_axes: list = field(default_factory=list)
    src_gaps: list = field(default_factory=list)


def _split(atoms, axis):
    """Project ink boxes on an axis (0: x, 1: y); return groups separated by empty gaps."""
    lo, hi = (0, 2) if axis == 0 else (1, 3)
    items = sorted(atoms, key=lambda a: a.ink[lo])
    groups, cur, end, gaps = [], [items[0]], items[0].ink[hi], []
    for a in items[1:]:
        if a.ink[lo] >= end - 2:
            groups.append(cur)
            gaps.append(a.ink[lo] - end)
            cur = [a]
        else:
            cur.append(a)
        end = max(end, a.ink[hi])
    groups.append(cur)
    return groups, gaps


def xycut(atoms, W0, H0):
    if len(atoms) == 1:
        return ("leaf", atoms[0])
    gy, gapy = _split(atoms, 1)
    gx, gapx = _split(atoms, 0)
    sy = max(gapy) / H0 if gapy else -1
    sx = max(gapx) / W0 if gapx else -1
    if sy < 0 and sx < 0:
        return ("island", atoms)                     # overlapping cluster: keep rigid
    if sy >= sx:
        return ("Y", [xycut(c, W0, H0) for c in gy])
    return ("X", [xycut(c, W0, H0) for c in gx])


def _atoms(node):
    if node[0] == "leaf":
        return [node[1]]
    if node[0] == "island":
        return list(node[1])
    return [a for k in node[1] for a in _atoms(k)]


def _compound(atoms, label):
    atoms = sorted(atoms, key=lambda u: (u.ink[1], u.ink[0]))
    return Unit(name=f"{label}(" + ",".join(u.name for u in atoms) + ")", kind="rigid",
                els=[e for u in atoms for e in u.els], ink=union([u.ink for u in atoms]),
                box=union([u.box for u in atoms]))


def _chip_like(kids):
    """Side-by-side siblings that look like a set (badges, icons): same kind, similar height."""
    if not all(k[0] == "leaf" for k in kids):
        return False
    us = [k[1] for k in kids]
    hs = [u.ink[3] - u.ink[1] for u in us]
    return len({u.kind for u in us}) == 1 and max(hs) <= 1.4 * min(hs) and us[0].kind != "text"


def flatten(node, level):
    """Map an XY-cut tree onto rows(R) > columns(C) > stacks(S). Returns (units, labels)."""
    kind = node[0]
    if kind == "leaf":
        return [node[1]], []
    if kind == "island":
        return [_compound(node[1], "island")], []
    kids = node[1]
    if kind == "X" and (level == "stk" or _chip_like(kids)):
        return [_compound(_atoms(node), "row")], []
    if kind == "Y":
        sep, child = ("R", "row") if level == "row" else ("S", "stk")
    else:
        sep, child = "C", "col"
    units, labels = [], []
    for i, k in enumerate(kids):
        u, l = flatten(k, child)
        if i:
            labels.append(sep)
        units += u
        labels += l
    return units, labels


def decompile(design) -> Galley:
    W0, H0 = design["canvas"]["width"], design["canvas"]["height"]
    els = design["elements"]
    g = Galley(W0, H0)
    area0 = W0 * H0
    have_assets = ASSETS.is_dir() and any(ASSETS.iterdir())

    # 1. canvas layer: biggest, lowest, covers the canvas
    rest = []
    for e in sorted(els, key=lambda e: e.get("z_index", 0)):
        cover = max(0, min(e["x"] + e["width"], W0) - max(e["x"], 0)) * max(0, min(e["y"] + e["height"], H0) - max(e["y"], 0))
        if e["type"] in ("image", "shape") and cover >= 0.85 * area0 and not g.background and not e.get("group_id"):
            g.background.append(e)
        else:
            rest.append(e)

    # 2. texture: ungrouped translucent shapes, or shapes that bleed off canvas
    atoms_src = []
    for e in rest:
        bleeds = e["x"] < 0 or e["y"] < 0 or e["x"] + e["width"] > W0 or e["y"] + e["height"] > H0
        if e["type"] == "shape" and not e.get("group_id") and (eff_alpha(e) < 0.4 or bleeds):
            g.texture.append(e)
        elif e["type"] == "image" and have_assets and asset_info(e.get("asset_id")) is None:
            g.hidden.append(e)   # would render as a grey 'missing asset' box
        else:
            atoms_src.append(e)

    # 3. atoms: group_id -> rigid unit
    groups: dict = {}
    order = []
    for e in atoms_src:
        k = e.get("group_id") or ("__" + e["id"])
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(e)
    atoms = []
    for k in order:
        members = groups[k]
        ink = union([ink_box(e) for e in members])
        box = union([rot_aabb(e["x"], e["y"], e["width"], e["height"], e.get("rotation", 0)) for e in members])
        if len(members) == 1 and members[0]["type"] in ("text", "image"):
            kind = members[0]["type"]
        else:
            kind = "rigid"
        atoms.append(Unit(name="+".join(m["id"] for m in members), kind=kind, els=members, ink=ink, box=box))

    # 4. furniture: small atoms hugging a canvas corner, off the main axis, or rotated
    cxs = [((a.ink[0] + a.ink[2]) / 2, (a.ink[2] - a.ink[0]) * (a.ink[3] - a.ink[1])) for a in atoms]
    tot = sum(w for _, w in cxs) or 1
    axis = sum(c * w for c, w in cxs) / tot
    flow = []
    for a in atoms:
        x0, y0, x1, y1 = a.ink
        small = (x1 - x0) * (y1 - y0) < 0.08 * area0
        near_l, near_r = x0 < 0.12 * W0, x1 > 0.88 * W0
        near_t, near_b = y0 < 0.12 * H0, y1 > 0.88 * H0
        off_axis = abs((x0 + x1) / 2 - axis) > 0.15 * W0
        rotated = any(abs(e.get("rotation", 0)) > 1 for e in a.els)
        if small and (near_l or near_r) and (near_t or near_b) and (off_axis or rotated):
            a.corner = ("T" if near_t else "B") + ("L" if near_l else "R")
            g.furniture.append(a)
        else:
            flow.append(a)

    # 5. reading order + source program: recursive XY-cut over flow atoms (Nagy & Seth),
    #    flattened into the 3-level galley (rows ¶ / columns | / stacks /).
    tree = xycut(flow, W0, H0)
    stream, labels = flatten(tree, "row")
    g.stream, g.src_labels = stream, labels

    # 6. glue: the source designer's gap between stream neighbours = natural glue width
    gaps, axes = [], []
    for a, b, l in zip(stream, stream[1:], labels):
        if l == "C":
            gaps.append(max(0.0, b.ink[0] - a.ink[2])); axes.append("x")
        else:
            gaps.append(max(0.0, b.ink[1] - a.ink[3])); axes.append("y")
    g.src_gaps, g.src_gap_axes = gaps, axes
    vg = [x for x, ax in zip(gaps, axes) if ax == "y"]
    g.base_gap = float(np.clip(np.median(vg) if vg else 0.03 * min(W0, H0), 0.015 * min(W0, H0), 0.06 * min(W0, H0)))
    m0 = float(np.clip(0.06 * min(W0, H0), 8, 72))
    fy0 = min(u.ink[1] for u in stream) - m0
    fy1 = H0 - m0 - max(u.ink[3] for u in stream)
    g.rho = float(np.clip(fy0 / max(1e-6, fy0 + fy1), 0.0, 1.0)) if fy0 + fy1 > 1 else 0.5

    # 7. rent (priority) from features only -- never from ids
    texts = [u for u in stream if u.kind == "text"]
    top_fs = max((u.els[0]["font_size"] * (1.15 if u.els[0].get("font_weight") == "bold" else 1)) for u in texts) if texts else 0
    for i, u in enumerate(stream):
        area = (u.ink[2] - u.ink[0]) * (u.ink[3] - u.ink[1]) / area0
        if u.kind == "text":
            e = u.els[0]
            f = e["font_size"] * (1.15 if e.get("font_weight") == "bold" else 1)
            if f >= top_fs - 1e-6:
                u.rent, u.role_hint = INF, "primary-text"
            elif e["font_size"] <= 13 or f < 0.3 * top_fs:
                u.rent, u.role_hint = 0.03, "fine-print"
            elif is_accent(e) and len(e["content"].split()) <= 5:
                u.rent, u.role_hint = 0.60, "accent-text(cta?)"
            else:
                u.rent, u.role_hint = 0.20, "secondary-text"
        elif u.kind == "image":
            w, h = u.ink[2] - u.ink[0], u.ink[3] - u.ink[1]
            if w / max(h, 1) >= 1.6 and area < 0.06:
                u.rent, u.role_hint = 0.80, "mark(logo-like)"
            else:
                u.rent, u.role_hint = 0.12 + area, "picture"
        else:
            has_shape = any(e["type"] == "shape" for e in u.els)
            n_text = sum(e["type"] == "text" for e in u.els)
            top_inside = any(e["type"] == "text" and e["font_size"] * (1.15 if e.get("font_weight") == "bold" else 1) >= top_fs - 1e-6
                             for e in u.els)
            if top_inside and not any(v.kind == "text" and v.rent == INF for v in stream):
                u.rent, u.role_hint = INF, "cluster(primary)"
            elif u.name.startswith("row("):
                u.rent, u.role_hint = 0.06, "chip-row"
            elif has_shape and n_text == 1:
                u.rent, u.role_hint = 1.00, "button"
            else:
                u.rent, u.role_hint = 0.30, "cluster"
    for f in g.furniture:
        f.rent, f.role_hint = 0.10, "sticker@" + f.corner
    return g


def describe(g: Galley) -> str:
    out = [f"GALLEY  source {g.W0}x{g.H0}   base glue={g.base_gap:.0f}px"]
    out.append("  canvas  : " + ", ".join(f"{e['id']}({e['type']},{e.get('fit','')})" for e in g.background))
    out.append("  texture : " + ", ".join(f"{e['id']}({e.get('shape_type')},a={eff_alpha(e):.2f})" for e in g.texture))
    out.append("  furnit. : " + ", ".join(f"{u.name}@{u.corner}" for u in g.furniture))
    out.append("  hidden  : " + ", ".join(f"{e['id']}(asset not resolvable)" for e in g.hidden))
    out.append("  stream  :")
    for i, u in enumerate(g.stream):
        r = "MANDATORY" if u.rent == INF else f"rent {u.rent:.2f}"
        x0, y0, x1, y1 = u.ink
        glue = f"   glue↓ {g.src_gaps[i]:.0f}px" if i < len(g.src_gaps) else ""
        out.append(f"    [{i}] {u.kind:5s} {u.role_hint:16s} {r:10s} ink=({x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f})  {u.name}{glue}")
    out.append("  source program: " + render_struct([u for u in g.stream], g.src_labels))
    return "\n".join(out)


def render_struct(units, labels):
    s = units[0].name.split("+")[0]
    for u, l in zip(units[1:], labels):
        s += {"S": " / ", "C": " | ", "R": " ¶ "}[l] + u.name.split("+")[0]
    return s


# ----------------------------------------------------------------------------
# Typesetter: fit a break pattern at type-scale s
# ----------------------------------------------------------------------------

class Ctx:
    def __init__(self, g: Galley, W, H):
        self.g, self.W, self.H = g, W, H
        self.m = float(np.clip(0.06 * min(W, H), 8, 72))
        self.Wl, self.Hl = W - 2 * self.m, H - 2 * self.m
        self.floor = max(10.0, 0.012 * min(W, H))   # legibility floor, px (tunable)
        self.s_cap = max(1.0, math.sqrt(W * H / (g.W0 * g.H0)))


def unit_scale(u: Unit, s, ctx: Ctx):
    """Cartographic exaggeration: text-bearing units never drop below the floor."""
    fs0 = u.fs0
    if fs0 is None:
        return s
    su = max(s, ctx.floor / fs0)
    if u.kind == "rigid":   # never exaggerate a rigid cluster past the live area
        su = min(su, ctx.Wl / max(1.0, u.box[2] - u.box[0]), ctx.Hl / max(1.0, u.box[3] - u.box[1]))
        su = max(su, s) if s * (u.box[2] - u.box[0]) <= ctx.Wl else su
    return su


def unit_dims(u: Unit, s, ctx: Ctx, width=None, boost=None):
    """Return (w, h, text_width_used) of a unit's INK at scale s."""
    su = unit_scale(u, s, ctx)
    boost = (boost or {}).get(id(u), 1.0)
    if u.kind == "image":
        iw, ih = (u.ink[2] - u.ink[0]) * s * boost, (u.ink[3] - u.ink[1]) * s * boost
        if u.role_hint.startswith("mark"):   # a logo is exaggerated to stay readable, like type
            floor = min(36.0, 0.45 * min(ctx.Wl, ctx.Hl))
            if ih < floor:
                iw, ih = iw * floor / ih, floor
        return (iw, ih, None)
    if u.kind == "rigid":
        return ((u.box[2] - u.box[0]) * su, (u.box[3] - u.box[1]) * su, None)
    e = u.els[0]
    fs = int(e["font_size"] * su)
    w = width if width is not None else min(e["width"] * su, one_line_w(e, fs) + 2)
    n, mw, h = measure(e, fs, w)
    return (mw, h, w)


def text_bounds(u, s, ctx):
    su = unit_scale(u, s, ctx)
    e = u.els[0]
    fs = int(e["font_size"] * su)
    return min_word_w(e, fs) + 1, max(min_word_w(e, fs) + 1, min(e["width"] * su, one_line_w(e, fs) + 2)), one_line_w(e, fs) + 2


def build(units, labels):
    rows = [[[units[0]]]]
    for u, l in zip(units[1:], labels):
        if l == "S":
            rows[-1][-1].append(u)
        elif l == "C":
            rows[-1].append([u])
        else:
            rows.append([[u]])
    return rows


def glue_nat(ctx, s, a, b):
    """TeX-style glue: natural size = the source designer's gap (if the two units were
    neighbours in the source), else the base rhythm."""
    g = ctx.g
    try:
        i = g.stream.index(a)
        if i + 1 < len(g.stream) and g.stream[i + 1] is b and g.src_gap_axes[i] == "y":
            return max(g.src_gaps[i], 0.35 * g.base_gap) * s
    except ValueError:
        pass
    return g.base_gap * s


def glue_v(ctx, s, a, b):
    """Shrunk glue used while fitting (stretched back toward natural when emitting)."""
    return min(glue_nat(ctx, s, a, b), ctx.g.base_gap * s)


def fit_row(row, s, ctx: Ctx, boost=None):
    """Lay out one row (list of columns). Returns (row_w, row_h, colinfo) or None."""
    gap_c = max(ctx.g.base_gap * s * 1.5, 0.02 * ctx.W)
    avail = ctx.Wl - gap_c * (len(row) - 1)
    lo, nat, hi = [], [], []
    for col in row:
        fixed = max([unit_dims(u, s, ctx, boost=boost)[0] for u in col if u.kind != "text"] or [0.0])
        tb = [text_bounds(u, s, ctx) for u in col if u.kind == "text"]
        lo.append(max([fixed] + [t[0] for t in tb]))
        nat.append(max([fixed] + [t[1] for t in tb]))
        hi.append(max([fixed] + [t[2] for t in tb]))
    # transparent padding of edge images must stay on canvas: reserve it before allocating
    def pre_overhang(col, side):
        worst = 0.0
        for u in col:
            if u.kind == "image":
                w, h, _ = unit_dims(u, s, ctx, boost=boost)
                fx0, fy0, fx1, fy1 = image_ink_rel(u.els[0])
                bw = w / (fx1 - fx0)
                worst = max(worst, fx0 * bw if side == "L" else (1 - fx1) * bw)
        return max(0.0, worst - ctx.m)
    ovl, ovr = pre_overhang(row[0], "L"), pre_overhang(row[-1], "R")
    avail -= ovl + ovr
    if sum(lo) > avail + 0.5:
        return None
    widths = list(nat)
    if sum(widths) > avail:      # shrink text columns toward their min-word width
        need = sum(widths) - avail
        room = [n - l for n, l in zip(nat, lo)]
        tr = sum(room) or 1
        widths = [n - need * r / tr for n, r in zip(nat, room)]
    else:                         # grow text columns toward single-line width (fewer lines)
        spare = avail - sum(widths)
        room = [h - n for h, n in zip(hi, nat)]
        tr = sum(room)
        if tr > 0:
            k = min(1.0, spare / tr)
            widths = [n + k * r for n, r in zip(nat, room)]
    cols = []
    for col, cw in zip(row, widths):
        hs, items = [], []
        for u in col:
            if u.kind == "text":
                w, h, tw = unit_dims(u, s, ctx, width=cw)
            else:
                w, h, tw = unit_dims(u, s, ctx, boost=boost)
            hs.append(h)
            items.append((u, w, h, tw))
        gaps = [glue_v(ctx, s, col[i], col[i + 1]) * 0.6 for i in range(len(col) - 1)]
        cols.append((cw, sum(hs) + sum(gaps), items, gaps))
    row_w = sum(c[0] for c in cols) + gap_c * (len(cols) - 1)
    row_h = max(c[1] for c in cols)
    row_w += ovl + ovr
    return row_w, row_h, cols, gap_c, ovl


def edge_overhang(col, side):
    cw, ch, items, gaps = col
    worst = 0.0
    for u, w, h, tw in items:
        if u.kind != "image":
            continue
        fx0, fy0, fx1, fy1 = image_ink_rel(u.els[0])
        bw = w / (fx1 - fx0)
        pad = fx0 * bw if side == "L" else (1 - fx1) * bw
        worst = max(worst, pad - (cw - w) / 2)
    return worst


def fit(rows, s, ctx: Ctx, boost=None):
    fitted = []
    for r in rows:
        fr = fit_row(r, s, ctx, boost)
        if fr is None or fr[0] > ctx.Wl + 0.5:
            return None
        fitted.append(fr)
    vg = [glue_v(ctx, s, rows[i][-1][-1], rows[i + 1][0][0]) for i in range(len(rows) - 1)]
    total_h = sum(f[1] for f in fitted) + sum(vg)
    if total_h > ctx.Hl + 0.5:
        return None
    return fitted, vg, total_h


def max_scale(rows, ctx: Ctx):
    lo, hi = 0.02, ctx.s_cap
    if fit(rows, hi, ctx):
        return hi
    if not fit(rows, lo, ctx):
        return None
    for _ in range(22):
        mid = math.sqrt(lo * hi)
        if fit(rows, mid, ctx):
            lo = mid
        else:
            hi = mid
    return lo


def max_boost(rows, s, ctx: Ctx):
    """Cross-axis fill: each image (most valuable first) grows into leftover space,
    marks (logo-like) to at most 60% of their row height, pictures up to 1.8x."""
    boosts = {}
    imgs = [(u, r) for r in rows for c in r for u in c if u.kind == "image"]
    imgs.sort(key=lambda t: -t[0].rent)
    for u, r in imgs:
        cap = 1.3 if u.role_hint.startswith("mark") else 1.8

        def ok(b):
            trial = dict(boosts)
            trial[id(u)] = b
            f = fit(rows, s, ctx, trial)
            if not f:
                return False
            if u.role_hint.startswith("mark") and len(r) > 1:
                row_h = f[0][rows.index(r)][1]
                return (u.ink[3] - u.ink[1]) * s * b <= 0.45 * row_h + 1e-6
            return True
        lo, hi = 1.0, cap
        if ok(hi):
            lo = hi
        else:
            for _ in range(12):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if ok(mid) else (lo, mid)
        boosts[id(u)] = lo
    return boosts


# ----------------------------------------------------------------------------
# Search: every omission prefix x every canonical break pattern
# ----------------------------------------------------------------------------

def canonical(units, labels):
    rows = build(units, labels)
    for r in rows:
        if len(r) == 1 and len(r[0]) > 1:
            return False        # a lone stack == separate rows; keep one spelling
    return True


def penalties(units, labels, g: Galley):
    p = 0.0
    src = {}
    for a, b, l in zip(g.stream, g.stream[1:], g.src_labels):
        src[(id(a), id(b))] = l
    for a, b, l in zip(units, units[1:], labels):
        sl = src.get((id(a), id(b)))
        if sl is not None and (sl == "C") != (l == "C"):
            p += 0.05                                       # faithfulness: each transposition costs a little
        if l == "C" and sl != "C" and a.kind == "text" and b.kind == "text":
            p += 0.15                                       # tight text bond broken sideways
        if l == "S" and a.kind == "image" and b.kind == "image":
            p += 0.05
    rows = build(units, labels)
    for r in rows:
        if len(r) > 5:
            p += 0.2 * (len(r) - 5)                          # clutter
    return p


def utility(s, ctx):
    """log type-scale, but once the design is 'comfortably' large, extra scale is worth little --
    so roomy canvases keep everything instead of dropping elements to grow the type."""
    comf = 0.85 * ctx.s_cap
    return math.log(min(s, comf)) + (0.2 * math.log(s / comf) if s > comf else 0.0)


def solve(g: Galley, W, H, top_k=5, verbose=True):
    ctx = Ctx(g, W, H)
    results = []
    t0 = time.time()
    n_fits = 0
    streams = [(g.stream, 0.0)]
    for u in g.stream[1:]:
        if u.role_hint.startswith("mark"):          # permitted move: brand mark leads the stream
            streams.append(([u] + [v for v in g.stream if v is not u], 0.03))
    for stream, perm_cost in streams:
        optional = sorted([u for u in stream if u.rent != INF], key=lambda u: u.rent)
        results += _search(g, ctx, stream, optional, perm_cost)
        n_fits += len(optional) + 1
    results.sort(key=lambda r: -r[0])
    if verbose:
        print(f"  searched {len(streams)} stream order(s) in {time.time() - t0:.2f}s; floor={ctx.floor:.1f}px s_cap={ctx.s_cap:.2f}")
        for J, s, kept, labels, dropped in results[:top_k]:
            print(f"   J={J:+.3f} s*={s:.3f}  {render_struct(kept, labels):70s}  omit={[u.name.split('+')[0] for u in dropped]}")
    return ctx, results


def _search(g, ctx, stream, optional, perm_cost):
    results = []
    n_fits = 0
    for k in range(len(optional) + 1):
        dropped = set(id(u) for u in optional[:k])
        kept = [u for u in stream if id(u) not in dropped]
        if not kept:
            continue
        rent = sum(u.rent for u in kept if u.rent != INF)
        for labels in itertools.product("SCR", repeat=len(kept) - 1):
            if not canonical(kept, labels):
                continue
            rows = build(kept, labels)
            s = max_scale(rows, ctx)
            n_fits += 1
            if s is None:
                continue
            f = fit(rows, s, ctx)
            fill = (max(r[0] for r in f[0]) * f[2]) / (ctx.Wl * ctx.Hl)   # block area / live area
            J = utility(s, ctx) + rent - penalties(kept, labels, g) - perm_cost + 0.06 * min(fill, 0.9)
            results.append((J, s, kept, labels, [u for u in stream if id(u) in dropped]))
    return results


# ----------------------------------------------------------------------------
# Emit: place the chosen typesetting into element geometry
# ----------------------------------------------------------------------------

def emit(g: Galley, design, ctx: Ctx, best):
    J, s, kept, labels, dropped = best
    W, H = ctx.W, ctx.H
    rows = build(kept, labels)
    boost = max_boost(rows, s, ctx)
    fitted, vg, total_h = fit(rows, s, ctx, boost)
    out = {e["id"]: dict(e) for e in design["elements"]}
    placed_ink = []

    # vertical justification (TeX glue): stretch row glue toward its natural (source) size,
    # then split the leftover above/below the block in the SOURCE's proportion.
    slack = ctx.Hl - total_h
    nat = [glue_nat(ctx, s, rows[i][-1][-1], rows[i + 1][0][0]) for i in range(len(rows) - 1)]
    want = sum(n - v for n, v in zip(nat, vg))
    if want > 0:
        k = min(1.0, slack / want)
        vg = [v + k * (n - v) for n, v in zip(nat, vg)]
        slack -= k * want
    rho = g.rho if len(rows) > 1 else 0.5
    y = ctx.m + slack * rho
    for ri, (row_w, row_h, cols, gap_c, ovl) in enumerate(fitted):
        hslack = ctx.Wl - row_w
        hslack -= 0
        if len(cols) >= 3 and hslack > 0:
            gap_c2 = gap_c + hslack / (len(cols) - 1)      # space-between for wide rows
            gap_c2 = min(gap_c2, gap_c * 4)
        elif len(cols) == 2 and hslack > 0:
            gap_c2 = min(gap_c + hslack / 3, gap_c * 3)
        else:
            gap_c2 = gap_c
        used = sum(c[0] for c in cols) + gap_c2 * (len(cols) - 1)
        x = ctx.m + ovl + max(0.0, (ctx.Wl - used - 2 * ovl) / 2)
        for cw, ch, items, gaps in cols:
            cy = y + (row_h - ch) / 2
            aligns = {u.els[0].get("text_align", "left") for u, *_ in items if u.kind == "text"}
            col_align = aligns.pop() if len(aligns) == 1 and len(items) > 1 else "center"
            for idx, (u, w, h, tw) in enumerate(items):
                off = 0.0 if col_align == "left" else (cw - w) if col_align == "right" else (cw - w) / 2
                place_unit(u, x, cy, cw, w, h, tw, s, boost, ctx, out, off)
                placed_ink.append((x + off, cy, x + off + w, cy + h))
                cy += h + (gaps[idx] if idx < len(gaps) else 0)
            x += cw + gap_c2
        y += row_h + (vg[ri] if ri < len(vg) else 0)

    # canvas layer
    for e in g.background:
        o = out[e["id"]]
        o.update(x=0, y=0, width=W, height=H)
    # texture: keep aspect, re-anchor to nearest corner, scale by sqrt(area ratio), clamp inside
    k = min(W / g.W0, H / g.H0) ** 0.5 * min(1.0, max(W / g.W0, H / g.H0)) ** 0.5
    for e in g.texture:
        o = out[e["id"]]
        w = min(e["width"] * k, W, H * e["width"] / e["height"])
        h = w * e["height"] / e["width"]
        cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
        nx = cx / g.W0 * W - w / 2
        ny = cy / g.H0 * H - h / 2
        o.update(x=float(np.clip(nx, 0, W - w)), y=float(np.clip(ny, 0, H - h)), width=w, height=h)
    # furniture: same corner, collision-checked against placed flow ink; else omitted
    for f in g.furniture:
        ok = False
        for shrink in (1.0, 0.8, 0.64):
            sf = unit_scale(f, s, ctx) * shrink
            bw, bh = (f.box[2] - f.box[0]) * sf, (f.box[3] - f.box[1]) * sf
            if bw > 0.45 * W or bh > 0.45 * H:
                continue
            mx = ctx.m * 0.6
            bx = mx if f.corner[1] == "L" else W - mx - bw
            by = mx if f.corner[0] == "T" else H - mx - bh
            cand = (bx, by, bx + bw, by + bh)
            if not any(overlap(cand, p, pad=4) for p in placed_ink):
                place_rigid(f, bx, by, sf, out, ctx)
                placed_ink.append(cand)
                ok = True
                break
        if not ok:
            dropped = dropped + [f]
    # omitted / hidden: honest opacity-0, geometry = letterboxed source position (in bounds)
    fit_k = min(W / g.W0, H / g.H0)
    ox, oy = (W - g.W0 * fit_k) / 2, (H - g.H0 * fit_k) / 2
    for u in list(dropped) + [Unit(e["id"], e["type"], [e], (0, 0, 0, 0), (0, 0, 0, 0)) for e in g.hidden]:
        for e in u.els:
            o = out[e["id"]]
            w, h = max(1.0, e["width"] * fit_k), max(1.0, e["height"] * fit_k)
            o.update(x=float(np.clip(ox + e["x"] * fit_k, 0, W - w)), y=float(np.clip(oy + e["y"] * fit_k, 0, H - h)),
                     width=w, height=h, opacity=0.0)
            if e["type"] == "text":
                o["font_size"] = max(1, int(e["font_size"] * fit_k))
                # cr-renderer IGNORES text opacity (Paint.setColor overrides Alphaf);
                # only the colour alpha hides glyphs.
                o["color"] = transparent(e.get("color", "rgba(0,0,0,1)"))
                if e.get("style_runs"):
                    o["style_runs"] = [dict(r, color=transparent(r["color"])) if "color" in r else r for r in e["style_runs"]]
            o.pop("rotation", None) if e.get("rotation") else None
    return {"canvas": {"width": W, "height": H}, "elements": [out[e["id"]] for e in design["elements"]]}


def transparent(c):
    try:
        r, g_, b = c.split("(")[1].split(",")[:3]
        return f"rgba({r.strip()},{g_.strip()},{b.strip()},0)"
    except IndexError:
        return "rgba(0,0,0,0)"


def place_unit(u, x, y, cw, w, h, tw, s, boost, ctx, out, off=None):
    off = (cw - w) / 2 if off is None else off
    if u.kind == "text":
        e = u.els[0]
        su = unit_scale(u, s, ctx)
        o = out[e["id"]]
        o.update(x=x, y=y, width=float(int(cw)), height=h, font_size=int(e["font_size"] * su))
        return
    if u.kind == "image":
        e = u.els[0]
        fx0, fy0, fx1, fy1 = image_ink_rel(e)
        ix = x + off
        bw, bh = w / (fx1 - fx0), h / (fy1 - fy0)
        bx, by = ix - fx0 * bw, y - fy0 * bh
        # keep the (transparent) box inside the canvas: shrink about the ink centre if needed
        cx, cy = ix + w / 2, y + h / 2
        k = 1.0
        for _ in range(30):
            if bx >= 0 and by >= 0 and bx + bw <= ctx.W and by + bh <= ctx.H:
                break
            k *= 0.97
            bw, bh = bw * 0.97, bh * 0.97
            bx = cx - (fx0 + (fx1 - fx0) / 2) * bw
            by = cy - (fy0 + (fy1 - fy0) / 2) * bh
        o = out[e["id"]]
        o.update(x=float(np.clip(bx, 0, ctx.W - bw)), y=float(np.clip(by, 0, ctx.H - bh)), width=bw, height=bh)
        return
    su = unit_scale(u, s, ctx)
    place_rigid(u, x + off, y, su, out, ctx)


def place_rigid(u, x, y, su, out, ctx):
    bx0, by0 = u.box[0], u.box[1]
    for e in u.els:
        o = out[e["id"]]
        # rotated members: box is AABB-based; offset the element by its own unrotated box
        ex0, ey0, _, _ = rot_aabb(e["x"], e["y"], e["width"], e["height"], e.get("rotation", 0))
        dx, dy = e["x"] - ex0, e["y"] - ey0
        nx = x + (ex0 - bx0) * su + dx * su
        ny = y + (ey0 - by0) * su + dy * su
        o.update(x=nx, y=ny, width=e["width"] * su, height=e["height"] * su)
        if e["type"] == "text":
            o["font_size"] = int(e["font_size"] * su)
            # guard: int truncation must not add a line
            n0 = measure(e, e["font_size"], e["width"])[0]
            if measure(e, o["font_size"], o["width"])[0] > n0:
                o["width"] = e["width"] * su * 1.06


def bounds_report(design):
    W, H = design["canvas"]["width"], design["canvas"]["height"]
    bad = []
    for e in design["elements"]:
        if e["x"] < -0.5 or e["y"] < -0.5 or e["x"] + e["width"] > W + 0.5 or e["y"] + e["height"] > H + 0.5:
            bad.append(e["id"])
    return bad


def fixed_point_report(src, out):
    """resize(src, src.canvas) should ~= src : the decompiled program re-executed at its own size."""
    W, H = src["canvas"]["width"], src["canvas"]["height"]
    diag = math.hypot(W, H)
    o = {e["id"]: e for e in out["elements"]}
    dc, ds = [], []
    for e in src["elements"]:
        f = o[e["id"]]
        if f.get("opacity", 1) == 0:
            continue
        dc.append(math.hypot(e["x"] + e["width"] / 2 - f["x"] - f["width"] / 2, e["y"] + e["height"] / 2 - f["y"] - f["height"] / 2) / diag)
        if e["type"] == "text":
            ds.append(abs(f["font_size"] / e["font_size"] - 1))
    return f"fixed-point drift: mean centre shift {100*np.mean(dc):.1f}% of diagonal (max {100*max(dc):.1f}%), mean font change {100*np.mean(ds) if ds else 0:.1f}%"


def run(task_path, targets, tag):
    task = json.loads(Path(task_path).read_text())
    src = task["source"]
    g = decompile(src)
    print("=" * 110)
    print(Path(task_path).name)
    print(describe(g))
    for (W, H) in targets:
        print(f"\n -> target {W}x{H}")
        ctx, res = solve(g, W, H)
        if not res:
            print("   NO FEASIBLE LAYOUT")
            continue
        out = emit(g, src, ctx, res[0])
        bad = bounds_report(out)
        name = f"{tag}_{W}x{H}"
        (OUT / f"{name}.json").write_text(json.dumps(out, indent=1))
        render_design_to_png(out, str(ASSETS), str(OUT / f"{name}.png"))
        print(f"   chosen: {render_struct(res[0][2], res[0][3])}   off-canvas={bad}  -> out/{name}.png")
        if (W, H) == (src["canvas"]["width"], src["canvas"]["height"]):
            print("   " + fixed_point_report(src, out))


def contact_sheet(names, path, width=1400):
    from PIL import ImageDraw
    tiles = []
    for n in names:
        im = Image.open(OUT / f"{n}.png").convert("RGB")
        k = min(1.0, (width - 20) / im.width, 420 / im.height)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))
        tiles.append((n, im))
    rows, cur, cw, ch = [], [], 0, 0
    for n, im in tiles:
        if cur and cw + im.width + 10 > width:
            rows.append((cur, ch)); cur, cw, ch = [], 0, 0
        cur.append((n, im)); cw += im.width + 10; ch = max(ch, im.height + 22)
    rows.append((cur, ch))
    sheet = Image.new("RGB", (width, sum(h for _, h in rows) + 10), (245, 245, 245))
    d = ImageDraw.Draw(sheet)
    y = 5
    for cur, h in rows:
        x = 5
        for n, im in cur:
            d.text((x, y), n, fill=(0, 0, 0))
            sheet.paste(im, (x, y + 14))
            x += im.width + 10
        y += h
    sheet.save(path)


if __name__ == "__main__":
    run("input/chameleon_sample_level1_warmup.json", [(1080, 1350), (1080, 1080), (1920, 1080), (728, 90)], "L1")
    run("input/chameleon_sample_level2_core.json", [(1600, 400), (728, 90), (1080, 1920), (1080, 1080), (300, 250)], "L2")
    run("input/chameleon_sample_level3_advanced.json", [(728, 90), (1080, 1350), (1080, 1920), (1600, 400), (300, 250), (160, 600)], "L3")
    contact_sheet(["L2_728x90", "L3_728x90", "L1_728x90"], OUT / "sheet_leaderboards.png")
    contact_sheet(["L2_1600x400", "L3_1600x400"], OUT / "sheet_wide.png")
    contact_sheet(["L1_1080x1350", "L2_1080x1920", "L3_1080x1920", "L3_160x600", "L2_300x250", "L3_300x250"], OUT / "sheet_tall_small.png")
    contact_sheet(["L1_1080x1080", "L2_1080x1080", "L3_1080x1350"], OUT / "sheet_fixed_point.png")
