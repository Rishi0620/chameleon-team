"""search.py: break patterns × omissions × one shared type scale (owner: OPTIMIZER).

Grammar: the kept stream units are joined by labels S ('/', stack in a column), C ('|', new column)
and R ('¶', new row). A bracket unit is a nested galley typeset inside its host.

For a pattern and a type scale z:
  * each COLUMN has an exact Pareto frontier (width -> minimal height), built from the text breakpoints
    W_k(f) (the renderer's own wrap), image/pill/chip widths and bracket width menus;
  * each ROW gets the min-max allocation: the smallest row height h* such that the columns' minimal
    widths at h* fit the row width;
  * the pattern fits iff the rows plus glue fit the live height.
Fonts grow monotonically with z (font = f_src * z**gamma_role, floored), so feasibility is monotone in z
and the largest feasible z is found by bisection on a geometric grid (the grid makes memoisation
across patterns work).

Search space:
  * omission subsets of optional units (rent < must), cheapest first, with a lower-bound prune;
  * patterns limited by regime;
  * n_kept > 9 falls back to enumerating labels between source stacks (documented; no DP yet).
Energy: capped concave size utility, legibility hinge, copy budget, line/break/one-word terms, Occam,
faithfulness (transpositions, bonds, image/type ratio, image order, fill vs source). Hard: ordinal
hierarchy incl. cross-type (logo ink <= 0.8 x headline ink).
"""
from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, field

from . import textfit as T
from .decompile import FLOOR_JPX, GAMMA_DOWN, GAMMA_UP, INF, Galley, Unit, area, union

ZGRID = [0.02 * (1.03 ** i) for i in range(260)]
TIME_BUDGET = 8.0
W = dict(drop=1.6, size=1.0, leg=4.0, copy=3.0, lines=0.12, strip_lines=0.6, breaks=0.15, oneword=0.2,
         slots=0.06, rows=0.03, trans=0.05, bond=0.15, ratio=0.25, imgord=0.5, fill=0.8, busy=0.6, hier=0.5, tiny=1.2, soft=0.15)


def band(Wc, Hc):
    r = Wc / Hc
    return "strip" if r >= 4.0 else "wide" if r >= 1.6 else "squareish" if r >= 0.7 else "tall"


class Ctx:
    """Typesetting context for one galley in one live area."""

    def __init__(self, g: Galley, W_live, H_live, CW, CH, W0, H0, assets_dir, disjoint=True,
                 kmax=4, pad=None, top=True):
        self.g, self.W, self.H = g, float(W_live), float(H_live)
        self.CW, self.CH, self.W0, self.H0 = float(CW), float(CH), float(W0), float(H0)
        self.assets_dir, self.disjoint, self.kmax, self.top = assets_dir, disjoint, kmax, top
        self.regime = band(CW, CH)
        self.js = T.judge_scale(CW, CH)
        mn = min(self.W, self.H)
        if pad is not None:
            self.m = pad
        elif self.regime == "strip":
            self.m = max(6.0, min(0.13 * CH, 0.04 * CW))
        else:
            self.m = max(8.0, min(72.0, 0.065 * min(CW, CH)))
            if g.depth == 0 and g.stream and pad is None:
                # near the source canvas the designer's own tightest edge margin is the margin
                m_src = min(min(u.ink[0], u.ink[1], g.W0 - u.ink[2], g.H0 - u.ink[3]) for u in g.stream)
                m_src *= math.sqrt(CW * CH / (g.W0 * g.H0))
                m_tgt = min(self.m, max(0.02 * min(CW, CH), m_src))
                d_src = abs(math.log(CW / g.W0)) + abs(math.log(CH / g.H0))
                self.m = self.m + math.exp(-d_src / 0.2) * (m_tgt - self.m)
        self.Wa, self.Ha = max(1.0, self.W - 2 * self.m), max(1.0, self.H - 2 * self.m)
        self.z_cap = max(1.0, math.sqrt(CW * CH / (W0 * H0)))
        self.s_sat = 0.85 * self.z_cap
        self.zi_cap = max(i for i, z in enumerate(ZGRID) if z <= self.z_cap + 1e-9)
        self.rec = max(14.0, 0.035 * max(CW, CH))           # recognisable image: min visible side (px)
        self.memo: dict = {}


# ----------------------------------------------------------------------------- per-unit sizing
def text_role(u: Unit):
    if u.kind == "text":
        return u.role if u.role in GAMMA_DOWN else "body"
    if u.kind == "pill":
        return "cta_label" if u.role == "cta" else "badge_label"
    if u.kind == "chips":
        return "badge_label"
    return "unknown"


def font_at(el, role, z, ctx):
    g = (GAMMA_UP if z >= 1 else GAMMA_DOWN).get(role, 0.7)
    f = int(round(float(el.get("font_size", 12)) * z ** g))
    floor = int(math.ceil(FLOOR_JPX.get(role, 10) / ctx.js))
    floor = min(floor, int(float(el.get("font_size", 12)) * max(1.0, ctx.z_cap)))   # never above source*cap
    return max(1, f, floor)


@dataclass
class Dims:
    kind: str                 # "fixed" | "flex"
    w: float = 0.0
    h: float = 0.0
    opts: list = field(default_factory=list)   # flex: [(w, h)], w ascending, h descending
    minw: float = 0.0
    f: int = 0
    s: float = 1.0
    extra: dict = field(default_factory=dict)


def _img_vis1(el, assets_dir):
    l, t, r, b = T.image_pad(el, el["width"], el["height"], assets_dir)
    return max(1.0, el["width"] - l - r), max(1.0, el["height"] - t - b)


def unit_dims(u: Unit, zi: int, ctx: Ctx):
    key = ("dims", u.name, zi, ctx.Wa, ctx.Ha)
    if key in ctx.memo:
        return ctx.memo[key]
    z = ZGRID[zi]
    d = None
    if u.kind == "text":
        el = u.head
        f = font_at(el, text_role(u), z, ctx)
        raw = []
        for k in range(1, ctx.kmax + 1):
            w = T.W_k(el, f, k)
            if w <= ctx.Wa + 1e-6:
                raw.append((w, T.text_h(el, f, k)))
        opts = []
        for w, h in sorted(raw):                 # Pareto: wider -> strictly shorter
            if not opts or h < opts[-1][1] - 1e-6:
                opts.append((w, h))
        if opts:
            d = Dims("flex", opts=opts, minw=opts[0][0], f=f, s=f / float(el["font_size"]))
    elif u.kind == "image":
        el = u.head
        vw, vh = _img_vis1(el, ctx.assets_dir)
        s_rec = ctx.rec / min(vw, vh)
        s_min = max(0.5 * z, s_rec)
        s_fit = min(ctx.Wa / el["width"], ctx.Ha / el["height"])
        if s_min <= s_fit + 1e-9:
            w, h = el["width"] * s_min, el["height"] * s_min
            if not ctx.disjoint:
                w, h = vw * s_min, vh * s_min
            d = Dims("fixed", w=w, h=h, s=s_min, extra={"s_fit": s_fit})
    elif u.kind == "pill":
        sh, lab = u.shape_el(), u.text_el()
        f = font_at(lab, text_role(u), z, ctx)
        s = f / float(lab["font_size"])
        h = sh["height"] * s
        w = T.one_line(lab, f) + 0.6 * h + 2          # min-content pill: rounded ends clear the caps
        if w <= ctx.Wa and h <= ctx.Ha:
            d = Dims("fixed", w=w, h=h, f=f, s=s, extra={"w_pref": max(w, sh["width"] * s)})
    elif u.kind == "chips":
        f = font_at(u.members[0].text_el(), "badge_label", z, ctx)
        s = f / float(u.members[0].text_el()["font_size"])
        ws, hs = [], []
        for p in u.members:
            sh, lab = p.shape_el(), p.text_el()
            fh = sh["height"] * s
            ws.append(max(sh["width"] * s * 0.85, T.one_line(lab, f) + 0.6 * fh + 2))
            hs.append(fh)
        w = sum(ws) + u.gap_src * s * (len(ws) - 1)
        if w <= ctx.Wa and max(hs) <= ctx.Ha:
            d = Dims("fixed", w=w, h=max(hs), f=f, s=s, extra={"ws": ws, "hs": hs})
    elif u.kind == "rigid":
        x0, y0, x1, y1 = u.box
        labels = [e for e in u.els if e["type"] == "text"]
        s = z
        for e in labels:
            s = max(s, (FLOOR_JPX["unknown"] / ctx.js) / float(e["font_size"]))
        s = min(s, ctx.Wa / max(1.0, x1 - x0), ctx.Ha / max(1.0, y1 - y0))
        if labels and min(int(float(e["font_size"]) * s) for e in labels) < 1:
            d = None
        else:
            d = Dims("fixed", w=(x1 - x0) * s, h=(y1 - y0) * s, s=s)
    elif u.kind == "bracket":
        d = bracket_dims(u, zi, ctx)
    ctx.memo[key] = d
    return d


def bracket_pad(u: Unit, z, ctx):
    host = u.els[0]
    hb = (host["x"], host["y"], host["x"] + host["width"], host["y"] + host["height"])
    ink = union([v.ink for v in u.sub.stream]) if u.sub.stream else hb
    sub_ink = (ink[0] + hb[0], ink[1] + hb[1], ink[2] + hb[0], ink[3] + hb[1])   # sub coords -> source
    src_pad = max(4.0, min(sub_ink[0] - hb[0], sub_ink[1] - hb[1], hb[2] - sub_ink[2], hb[3] - sub_ink[3]))
    return max(6.0, min(src_pad * z ** 0.8, 0.12 * min(ctx.W, ctx.H)))


def sub_ctx(u: Unit, cw, ch, ctx: Ctx, pad):
    return Ctx(u.sub, cw, ch, ctx.CW, ctx.CH, ctx.W0, ctx.H0, ctx.assets_dir, ctx.disjoint, ctx.kmax,
               pad=pad, top=False)


def bracket_dims(u: Unit, zi, ctx: Ctx):
    """Flex options (outer w, outer h) for a container: min height of its nested galley per width."""
    z = ZGRID[zi]
    pad = bracket_pad(u, z, ctx)
    optional = sorted([v for v in u.sub.stream if v.rent < INF], key=lambda v: v.rent)
    opts = []
    for k in range(len(optional) + 1):         # riders may be omitted, lowest rent first, never the headline
        drop = optional[:k]
        kept = [v for v in u.sub.stream if v not in drop]
        if not kept:
            break
        for frac in (0.25, 0.32, 0.4, 0.5, 0.6, 0.72, 0.85, 1.0):
            cw = ctx.Wa * frac
            sc = sub_ctx(u, cw, ctx.Ha, ctx, pad)
            best = None
            for labels in patterns(kept, sc, limit=200):
                rows = build(kept, labels)
                fr = fit(rows, zi, sc)
                if fr is not None:
                    hh = fr[1] + 2 * pad
                    if best is None or hh < best:
                        best = hh
            if best is not None and best <= ctx.Ha + 1e-6:
                if not opts or best < opts[-1][1] - 1e-6:
                    opts.append((cw, best))
        if opts:
            break
    if not opts:
        return None
    return Dims("flex", opts=opts, minw=opts[0][0], extra={"pad": pad})


# ----------------------------------------------------------------------------- glue
def g_stack(ctx, z):
    return max(3.0, 0.6 * ctx.g.base_gap * z)


def g_row(ctx, z):
    return max(4.0, ctx.g.base_gap * z)


def g_col(ctx, z):
    return max(8.0, 1.5 * ctx.g.base_gap * z, 0.02 * ctx.W)


# ----------------------------------------------------------------------------- fitting
def col_frontier(col, zi, ctx: Ctx):
    key = ("col", tuple(u.name for u in col), zi, ctx.Wa, ctx.Ha)
    if key in ctx.memo:
        return ctx.memo[key]
    z = ZGRID[zi]
    lo, fixed_h, flex, cands = 0.0, 0.0, [], set()
    res = None
    ok = True
    for u in col:
        d = unit_dims(u, zi, ctx)
        if d is None:
            ok = False
            break
        if d.kind == "flex":
            lo = max(lo, d.minw)
            flex.append(d)
            cands.update(w for w, _ in d.opts)
        else:
            lo = max(lo, d.w)
            fixed_h += d.h
    if ok:
        gaps = g_stack(ctx, z) * (len(col) - 1)
        cands.add(lo)
        out = []
        for c in sorted(x for x in cands if lo - 1e-6 <= x <= ctx.Wa + 1e-6):
            h = fixed_h + gaps
            good = True
            for d in flex:
                hh = next((oh for ow, oh in reversed(d.opts) if ow <= c + 1e-6), None)
                if hh is None:
                    good = False
                    break
                h += hh
            if good and (not out or h < out[-1][1] - 1e-6):
                out.append((c, h))
        res = out or None
    ctx.memo[key] = res
    return res


def fit_row(row, zi, ctx: Ctx):
    frs = []
    for col in row:
        fr = col_frontier(col, zi, ctx)
        if fr is None:
            return None
        frs.append(fr)
    budget = ctx.Wa - g_col(ctx, ZGRID[zi]) * (len(row) - 1)
    hs = sorted({h for fr in frs for _, h in fr})
    for h in hs:
        ws = []
        for fr in frs:
            w = next((c for c, hh in fr if hh <= h + 1e-6), None)
            if w is None:
                break
            ws.append(w)
        else:
            if sum(ws) <= budget + 1e-6:
                return h, ws
    return None


def fit(rows, zi, ctx: Ctx):
    res, total = [], 0.0
    for row in rows:
        fr = fit_row(row, zi, ctx)
        if fr is None:
            return None
        res.append(fr)
        total += fr[0]
    total += g_row(ctx, ZGRID[zi]) * (len(rows) - 1)
    if total > ctx.Ha + 1e-6:
        return None
    return res, total


def max_zi(rows, ctx: Ctx):
    lo, hi = 0, ctx.zi_cap
    if fit(rows, hi, ctx) is not None:
        return hi
    if fit(rows, lo, ctx) is None:
        return None
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if fit(rows, mid, ctx) is not None:
            lo = mid
        else:
            hi = mid
    return lo


# ----------------------------------------------------------------------------- grammar
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


def limits(ctx: Ctx):
    r = ctx.W / ctx.H
    if r >= 4.0:
        return 1, 5           # rows, cols per row
    if r >= 1.6:
        return 2, 4
    if r >= 0.7:
        return 5, 3
    return 99, 2


def patterns(kept, ctx: Ctx, limit=None, source_labels=None):
    n = len(kept)
    if n <= 1:
        yield ()
        return
    max_rows, max_cols = limits(ctx)
    alphabet = "SC" if max_rows == 1 else "SCR"
    count = 0
    seed = None
    if source_labels:
        sl = {(a, b): l for a, b, l in source_labels}
        seed = tuple(sl.get((a.name, b.name), "R") for a, b in zip(kept, kept[1:]))
        if "C" in seed and max_rows == 1:
            seed = None
    if n > 9:
        if seed is not None:
            yield seed                      # the designer's own structure is always a candidate
        yield from _grouped_patterns(kept, ctx, source_labels, alphabet, max_rows, max_cols)
        return
    if seed is not None:
        yield seed
    for labels in itertools.product(alphabet, repeat=n - 1):
        if labels == seed:
            continue
        rows = 1 + labels.count("R")
        if rows > max_rows:
            continue
        cols, bad = 1, False
        for l in labels:
            if l == "R":
                cols = 1
            elif l == "C":
                cols += 1
                if cols > max_cols:
                    bad = True
                    break
        if bad or not _canonical(labels):
            continue
        yield labels
        count += 1
        if limit and count >= limit:
            return


def _canonical(labels):
    """A row holding a single column of >1 units equals separate rows; keep only the ¶ spelling."""
    seg = []
    for l in labels + ("R",):
        if l == "R":
            if seg and "C" not in seg and "S" in seg:
                return False
            seg = []
        else:
            seg.append(l)
    return True


def _grouped_patterns(kept, ctx, source_labels, alphabet, max_rows, max_cols):
    """Fallback for long streams (documented): keep the SOURCE's stacks ('/' runs) together and enumerate
    labels between them only."""
    src = {}
    if source_labels:
        for a, b, l in source_labels:
            src[(a, b)] = l
    inner = []
    for a, b in zip(kept, kept[1:]):
        inner.append(src.get((a.name, b.name)) == "S")
    gaps = [i for i, s in enumerate(inner) if not s]
    if len(gaps) > 8:
        gaps = gaps[:8]
    seen = set()
    for combo in itertools.product(alphabet, repeat=len(gaps)):
        labels = ["S"] * (len(kept) - 1)
        for i, l in zip(gaps, combo):
            labels[i] = l
        t = tuple(labels)
        if t not in seen and 1 + t.count("R") <= max_rows:
            seen.add(t)
            yield t
    for t in (tuple("R" * (len(kept) - 1)), tuple("S" * (len(kept) - 1))):
        if t not in seen and (1 + t.count("R") <= max_rows):
            yield t


# ----------------------------------------------------------------------------- plans
@dataclass
class Item:
    unit: Unit
    x: float
    y: float
    w: float
    h: float
    f: int = 0
    k: int = 0
    s: float = 1.0
    sub: object = None        # bracket: (Plan of nested galley, pad)
    extra: dict = field(default_factory=dict)


@dataclass
class Plan:
    z: float
    zi: int
    kept: list
    dropped: list
    labels: tuple
    items: list
    content_box: tuple
    energy: float = 0.0
    terms: dict = field(default_factory=dict)
    live: tuple = (0, 0, 0, 0)
    rows: int = 1
    cols: int = 1

    def program(self):
        if not self.kept:
            return ""
        s = self.kept[0].name.split("+")[0]
        for u, l in zip(self.kept[1:], self.labels):
            s += {"S": " / ", "C": " | ", "R": " ¶ "}[l] + u.name.split("+")[0]
        return s


def make_plan(kept, labels, zi, ctx: Ctx, ox=0.0, oy=0.0, dropped=()):
    """Turn a fitted pattern into absolute item geometry (live area origin ox, oy)."""
    rows = build(kept, labels)
    fr = fit(rows, zi, ctx)
    if fr is None:
        return None
    z = ZGRID[zi]
    row_fits, total = fr
    gs, gr, gc = g_stack(ctx, z), g_row(ctx, z), g_col(ctx, z)
    # column contents at the fitted widths
    layout_rows = []
    for row, (h_row, ws) in zip(rows, row_fits):
        cols = []
        for col, c in zip(row, ws):
            its = []
            for u in col:
                d = unit_dims(u, zi, ctx)
                if d.kind == "flex" and u.kind == "text":
                    k = next(i + 1 for i in range(ctx.kmax) if T.W_k(u.head, d.f, i + 1) <= c + 1e-6)
                    it = Item(u, 0, 0, c, T.text_h(u.head, d.f, k), f=d.f, k=k, s=d.s)
                elif u.kind == "bracket":
                    hh = next(oh for ow, oh in reversed(d.opts) if ow <= c + 1e-6)
                    it = Item(u, 0, 0, c, hh, extra={"pad": d.extra["pad"]})
                else:
                    it = Item(u, 0, 0, d.w, d.h, f=d.f, s=d.s, extra=dict(d.extra))
                its.append(it)
            cols.append([c, its, _stack_h(its, gs, ctx)])
        layout_rows.append([cols, max(cc[2] for cc in cols)])
    total_h = sum(rh for _, rh in layout_rows) + gr * (len(layout_rows) - 1)
    slack = ctx.Ha - total_h
    # 1) grow images into slack first (pictures fill the cross axis: GALLEY max_boost / DESIGNER fill)
    n_img_rows = sum(1 for cols, _ in layout_rows if any(i.unit.kind == "image" for cc in cols for i in cc[1]))
    for lr in layout_rows:
        cols, rh = lr
        if not any(i.unit.kind == "image" for cc in cols for i in cc[1]):
            continue
        share = max(0.0, slack) * (0.75 / max(1, n_img_rows)) if len(layout_rows) > 1 else max(0.0, slack)
        avail_h = rh + share
        row_left = (ctx.Wa - gc * (len(cols) - 1)) - sum(cc[0] for cc in cols)
        img_cols = [cc for cc in cols if any(i.unit.kind == "image" for i in cc[1])]
        for cc in cols:
            for it in cc[1]:
                if it.unit.kind != "image":
                    continue
                el = it.unit.head
                other = cc[2] - it.h
                cap_role = 1.3 if it.unit.role == "logo" else 1.8
                s_max = min(cap_role * z, it.extra.get("s_fit", 9e9))
                w_room = cc[0] + max(0.0, row_left) / max(1, len(img_cols))
                bw1, bh1 = (el["width"], el["height"]) if ctx.disjoint else _img_vis1(el, ctx.assets_dir)
                s_new = max(it.s, min(s_max, (avail_h - other) / bh1, w_room / bw1))
                if s_new > it.s:
                    gw, gh = bw1 * s_new, bh1 * s_new
                    if gw > cc[0]:
                        row_left -= gw - cc[0]
                        cc[0] = gw
                    it.w, it.h, it.s = gw, gh, s_new
                    cc[2] = _stack_h(cc[1], gs, ctx)
        lr[1] = max(cc[2] for cc in cols)
    # 2) spend leftover row width on fewer text lines (toward the source's own line counts)
    for lr in layout_rows:
        cols, _ = lr
        budget = ctx.Wa - gc * (len(cols) - 1)
        while True:
            left = budget - sum(cc[0] for cc in cols)
            best = None
            for cc in cols:
                for it in cc[1]:
                    u = it.unit
                    if u.kind != "text" or it.k <= max(1, u.k_pref):
                        continue
                    need = T.W_k(u.head, it.f, it.k - 1) - cc[0]
                    if 0 < need <= left + 1e-6 and (best is None or need < best[0]):
                        best = (need, cc)
            if best is None:
                break
            need, cc = best
            cc[0] += need
            for it in cc[1]:
                if it.unit.kind == "text":
                    it.k = next(i + 1 for i in range(ctx.kmax) if T.W_k(it.unit.head, it.f, i + 1) <= cc[0] + 1e-6)
                    it.h = T.text_h(it.unit.head, it.f, it.k)
            cc[2] = _stack_h(cc[1], gs, ctx)
        lr[1] = max(cc[2] for cc in cols)
    # vertical: ink-to-ink rhythm (transparent image padding counts as gap), glue stretched toward
    # 2x, rest split above/below in the source's ratio rho
    row_gaps = []
    for (ca, _), (cb_, _) in zip(layout_rows, layout_rows[1:]):
        pb = min(_pad_last(cc[1], ctx)[3] for cc in ca)
        pt = min(_pad_first(cc[1], ctx)[1] for cc in cb_)
        row_gaps.append(max(2.0, gr - pb - pt))
    total_h = sum(rh for _, rh in layout_rows) + sum(row_gaps)
    slack = max(0.0, ctx.Ha - total_h)
    if row_gaps:
        extra = min(slack / (len(layout_rows) + 1), 2.0 * gr)
        row_gaps = [g + extra for g in row_gaps]
        slack -= extra * len(row_gaps)
    rho = ctx.g.rho if (len(layout_rows) > 1 and ctx.top) else 0.5
    y = oy + ctx.m + slack * rho
    items = []
    n_cols_total = 0
    for ri, (cols, rh) in enumerate(layout_rows):
        n = len(cols)
        n_cols_total += n
        col_gaps = [max(4.0, gc - _col_pad(cols[j][1], ctx, "r") - _col_pad(cols[j + 1][1], ctx, "l"))
                    for j in range(n - 1)]
        used = sum(cc[0] for cc in cols)
        left = ctx.Wa - used - sum(col_gaps)
        if n >= 3 and left > 0:
            add = min(left / (n - 1), 3.0 * gc)
        elif n == 2 and left > 0:
            add = min(left / 3.0, 2.0 * gc)
        else:
            add = 0.0
        col_gaps = [g + add for g in col_gaps]
        x = ox + ctx.m + max(0.0, (ctx.Wa - used - sum(col_gaps)) / 2)
        for j, (c, its, ch) in enumerate(cols):
            if n > 1 and len(its) == 1:
                its[0].alone_in_col = True
            texts = [i.unit.head.get("text_align", "center") for i in its if i.unit.kind == "text"]
            align = texts[0] if texts and len(set(texts)) == 1 and len(its) > 1 else "center"
            cy = y + (rh - ch) / 2
            for idx, it in enumerate(its):
                if it.unit.kind == "text":
                    it.x, it.w = x, c
                elif align == "left":
                    it.x = x
                elif align == "right":
                    it.x = x + c - it.w
                else:
                    it.x = x + (c - it.w) / 2
                if it.unit.kind in ("pill",):
                    it.w = min(max(it.w, it.extra.get("w_pref", it.w)), c)
                    if align == "center":
                        it.x = x + (c - it.w) / 2
                    elif align == "right":
                        it.x = x + c - it.w
                it.y = cy
                if idx + 1 < len(its):
                    cy += it.h + _pair_gap(it, its[idx + 1], gs, ctx)
                items.append(it)
            x += c + (col_gaps[j] if j < len(col_gaps) else 0.0)
        y += rh + (row_gaps[ri] if ri < len(row_gaps) else 0.0)
    if not items:
        return None
    cb = union([(i.x, i.y, i.x + i.w, i.y + i.h) for i in items])
    p = Plan(z=z, zi=zi, kept=list(kept), dropped=list(dropped), labels=tuple(labels), items=items,
             content_box=cb, live=(ox, oy, ctx.W, ctx.H), rows=len(layout_rows), cols=n_cols_total)
    # nested galleys: typeset each bracket's riders inside its box at the same z
    for it in items:
        if it.unit.kind == "bracket":
            pad = it.extra["pad"]
            sc = sub_ctx(it.unit, it.w, it.h, ctx, pad)
            sp = best_plan_fixed_z(it.unit.sub, sc, zi, it.x, it.y)
            if sp is None:
                return None
            it.sub = sp
    return p


def _pads(it, ctx):
    if it.unit.kind != "image" or not ctx.disjoint:
        return (0.0, 0.0, 0.0, 0.0)
    return T.image_pad(it.unit.head, it.w, it.h, ctx.assets_dir)


def _pad_first(its, ctx):
    return _pads(its[0], ctx) if its else (0.0, 0.0, 0.0, 0.0)


def _pad_last(its, ctx):
    return _pads(its[-1], ctx) if its else (0.0, 0.0, 0.0, 0.0)


def _col_pad(its, ctx, side):
    """Transparent side padding shared by every item of a column (only image-only columns have any)."""
    if not its or any(i.unit.kind != "image" for i in its):
        return 0.0
    k = 0 if side == "l" else 2
    return min(_pads(i, ctx)[k] + (0.0 if side == "l" else 0.0) for i in its)


def _pair_gap(a, b, gs, ctx):
    return max(2.0, gs - _pads(a, ctx)[3] - _pads(b, ctx)[1])


def _stack_h(its, gs, ctx):
    return sum(i.h for i in its) + sum(_pair_gap(a, b, gs, ctx) for a, b in zip(its, its[1:]))


def best_plan_fixed_z(g: Galley, ctx: Ctx, zi, ox, oy):
    """Nested galley at a fixed type scale: best pattern by energy (riders all kept; relax by
    dropping the lowest-rent riders if nothing fits)."""
    stream = list(g.stream)
    optional = sorted([u for u in stream if u.rent < INF], key=lambda u: u.rent)
    for k in range(len(optional) + 1):
        drop = optional[:k]
        kept = [u for u in stream if u not in drop]
        if not kept:
            break
        best = None
        for labels in patterns(kept, ctx, limit=400):
            p = make_plan(kept, labels, zi, ctx, ox, oy, dropped=drop)
            if p is None:
                continue
            E, terms = energy(p, g, ctx, src_cov=None)
            p.energy, p.terms = E, terms
            if best is None or E < best.energy:
                best = p
        if best is not None:
            return best
    return None


# ----------------------------------------------------------------------------- energy + hard checks
def _imp(u):
    return 1.0 if u.rent >= INF else min(1.0, u.rent)


def utility(s, ctx):
    s = max(s, 1e-6)
    return math.log(min(s, ctx.s_sat) / ctx.s_sat) + 0.2 * math.log(max(s, ctx.s_sat) / ctx.s_sat)


def all_items(plan):
    out = []
    for it in plan.items:
        out.append(it)
        if it.sub is not None:
            out += all_items(it.sub)
    return out


def text_items(plan):
    """[(source element, target font, role)] of every visible text-bearing unit incl. nested."""
    res = []
    for it in all_items(plan):
        u = it.unit
        if u.kind == "text":
            res.append((u.head, it.f, text_role(u), it))
        elif u.kind == "pill":
            res.append((u.text_el(), it.f, text_role(u), it))
        elif u.kind == "chips":
            res.append((u.members[0].text_el(), it.f, "badge_label", it))
    return res


def hierarchy_ok(plan, ctx):
    tx = text_items(plan)
    for (ea, fa, ra, _), (eb, fb, rb, _) in itertools.permutations(tx, 2):
        r_src = T.eff_size(ea) / max(1e-6, T.eff_size(eb))
        if r_src >= 1.1:
            # ordinal hierarchy with a margin that floors can still meet (soft compression term in energy)
            need = min(1.15, 1 + (r_src - 1) / 3)
            if T.eff_size(ea, fa) < need * T.eff_size(eb, fb) - 1e-6:
                return False
    # cross-type: logo ink <= 0.8 x headline ink (DESIGNER R6)
    head = [it for (e, f, r, it) in tx if r == "headline"]
    logos = [it for it in all_items(plan) if it.unit.kind == "image" and it.unit.role == "logo"]
    if head and logos:
        h = head[0]
        lw = max(T.line_widths(h.unit.head, h.f, h.w))
        h_ink = lw * T.text_h(h.unit.head, h.f, h.k)
        for lg in logos:
            vw, vh = _img_vis1(lg.unit.head, ctx.assets_dir)
            s = lg.s if ctx.disjoint else lg.s
            if vw * vh * s * s > 0.8 * h_ink:
                return False
    return True


def energy(plan, g: Galley, ctx: Ctx, src_cov=None, busy=None):
    t = dict.fromkeys(W, 0.0)
    t["drop"] = W["drop"] * drop_mult(g, ctx) * sum(min(u.rent, 5.0) for u in plan.dropped)
    chars = 0
    f_c = max(14.0, 0.018 * max(ctx.CW, ctx.CH))
    strip = ctx.regime == "strip"
    for it in all_items(plan):
        u = it.unit
        imp = _imp(u)
        if u.kind == "text":
            el = u.head
            s = it.f / float(el["font_size"])
            chars += len(str(el.get("content", "")))
            role = text_role(u)
            floor = FLOOR_JPX.get(role, 10)
            comf = 1.35 * floor
            jpx = it.f * ctx.js
            t["leg"] += W["leg"] * imp * max(0.0, (comf - jpx) / comf) ** 2
            if role in ("headline", "subhead"):
                t["lines"] += W["lines"] * imp * max(0, it.k - 2)
                t["breaks"] += W["breaks"] * imp * max(0, it.k - u.k_pref)
                if strip and role == "headline":
                    t["strip_lines"] += W["strip_lines"] * max(0, it.k - 3)
            if it.k >= 2 and role in ("headline", "subhead", "body"):
                lines = T.line_texts(el, it.f, it.w)
                t["oneword"] += W["oneword"] * imp * sum(1 for ln in lines if len(ln.split()) == 1)
            t["size"] -= W["size"] * imp * utility(s, ctx)
        elif u.kind == "image":
            t["size"] -= W["size"] * imp * utility(it.s, ctx)
            t["ratio"] += W["ratio"] * imp * abs(math.log(max(it.s, 1e-6) / plan.z))
        elif u.kind in ("pill", "chips"):
            lab = u.text_el()
            chars += len(str(lab.get("content", "")))
            t["size"] -= W["size"] * imp * utility(it.f / float(lab["font_size"]), ctx)
            jpx = it.f * ctx.js
            comf = 1.35 * FLOOR_JPX.get(text_role(u), 10)
            t["leg"] += W["leg"] * imp * max(0.0, (comf - jpx) / comf) ** 2
        elif u.kind == "rigid":
            t["size"] -= W["size"] * imp * utility(it.s, ctx)
    tx = text_items(plan)
    head = [x for x in tx if x[2] == "headline"]
    if head:
        eh, fh = head[0][0], head[0][1]
        for (e, f, r, _) in tx:
            if r == "headline":
                continue
            r_src = T.eff_size(eh) / max(1e-6, T.eff_size(e))
            r_tgt = T.eff_size(eh, fh) / max(1e-6, T.eff_size(e, f))
            if r_src > 1.0:
                t["hier"] += W["hier"] * max(0.0, math.log(min(1.3, r_src)) - math.log(max(r_tgt, 1e-6)))
    load = chars * f_c * f_c * 0.55 / (ctx.CW * ctx.CH)
    t["copy"] = W["copy"] * max(0.0, load - 0.5)
    t["slots"] = W["slots"] * (6.0 if ctx.regime == "tall" else 1.0) * max(0, plan.cols - plan.rows)
    if ctx.regime != "strip" and plan.cols > plan.rows:
        # a side column holding only a small mark or fine print reads as an accident off the strip format
        for it in plan.items:
            u = it.unit
            if getattr(it, "alone_in_col", False) and (u.role == "logo" or text_role(u) == "legal"):
                t["tiny"] += W["tiny"]
    t["rows"] = W["rows"] * max(0, plan.rows - 1)
    src = {(a.name, b.name): l for a, b, l in zip(g.stream, g.stream[1:], g.labels)}
    d_src = abs(math.log(ctx.W / g.W0)) + abs(math.log(ctx.H / g.H0))
    trans_mult = 1.0 + 25.0 * math.exp(-d_src / 0.12)         # near the source canvas the source structure wins
    for a, b, l in zip(plan.kept, plan.kept[1:], plan.labels):
        sl = src.get((a.name, b.name))
        if sl is not None and (sl == "C") != (l == "C"):
            t["trans"] += W["trans"] * trans_mult
        if l == "C" and a.kind == "text" and b.kind == "text" and sl != "C":
            t["bond"] += W["bond"]
    imgs = [it for it in plan.items if it.unit.kind == "image"]
    for a, b in itertools.permutations(imgs, 2):
        sa = a.unit.head["width"] * a.unit.head["height"]
        sb = b.unit.head["width"] * b.unit.head["height"]
        if sa >= 1.5 * sb and sa * a.s ** 2 < sb * b.s ** 2:
            t["imgord"] += W["imgord"]
    if src_cov is not None:
        cb = plan.content_box
        cov = area(cb) / (ctx.W * ctx.H)
        t["fill"] = W["fill"] * max(0.0, 0.6 * src_cov - cov)
    if busy is not None:
        t["busy"] = W["busy"] * max(0.0, busy - 1.0)
    return sum(t.values()), t


def drop_mult(g, ctx):
    """Omissions get dearer near the source canvas: the designer kept everything there."""
    d_src = abs(math.log(ctx.W / g.W0)) + abs(math.log(ctx.H / g.H0))
    return 1.0 + 4.0 * math.exp(-d_src / 0.12)


# ----------------------------------------------------------------------------- driver
def search(g: Galley, ctx: Ctx, src_cov, must_thr=0.8, top_n=24, deadline=None, never_drop_text=False,
           ox=0.0, oy=0.0):
    """Ranked plans (best first, structurally distinct)."""
    t_end = deadline or (time.time() + TIME_BUDGET)
    stream = list(g.stream)
    if not stream:
        return []
    must = [u for u in stream if u.rent >= must_thr or (never_drop_text and u.kind == "text")]
    optional = sorted([u for u in stream if u not in must], key=lambda u: u.rent)
    if len(optional) <= 7:
        subsets = [list(c) for r in range(len(optional) + 1) for c in itertools.combinations(optional, r)]
    else:
        subsets = [optional[:k] for k in range(len(optional) + 1)]
        subsets += [optional[:k] + [optional[k + 1]] for k in range(len(optional) - 1)]
    subsets.sort(key=lambda s: sum(u.rent for u in s))
    u_max = sum(_imp(u) * 0.2 * math.log(max(ctx.z_cap, ctx.s_sat) / ctx.s_sat + 1e-9) for u in stream)
    src_labels = [(a.name, b.name, l) for a, b, l in zip(g.stream, g.stream[1:], g.labels)]
    results, best_E = [], math.inf
    for sub in subsets:
        drop_cost = W["drop"] * drop_mult(g, ctx) * sum(min(u.rent, 5.0) for u in sub)
        if drop_cost - u_max > best_E + 0.5:
            continue
        kept = [u for u in stream if u not in sub]
        if not kept:
            continue
        for labels in patterns(kept, ctx, source_labels=src_labels):
            if time.time() > t_end and results:
                break
            rows = build(kept, labels)
            zi = max_zi(rows, ctx)
            if zi is None:
                continue
            plan = make_plan(kept, labels, zi, ctx, ox, oy, dropped=sub)
            # floors can flatten the hierarchy at max z: walk z down a few steps before giving up
            tries = 0
            while plan is not None and not hierarchy_ok(plan, ctx) and tries < 6 and zi > 0:
                zi -= 3
                tries += 1
                plan = make_plan(kept, labels, zi, ctx, ox, oy, dropped=sub) if zi >= 0 else None
            if plan is None or not hierarchy_ok(plan, ctx):
                continue
            E, terms = energy(plan, g, ctx, src_cov=src_cov)
            plan.energy, plan.terms = E, terms
            results.append(plan)
            best_E = min(best_E, E)
        if time.time() > t_end and results:
            break
    results.sort(key=lambda p: p.energy)
    out, seen = [], set()
    for p in results:
        key = (p.program(), round(p.z, 2))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= top_n:
            break
    return out
