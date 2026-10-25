"""layers.py: controlled layering for dense small formats (owner: OPTIMIZER).

On strips and other tiny canvases the minor units (legal line, badge chips, the visible placeholder of a
missing asset) used to be typeset in the same flow as the headline, logo, CTA and hero. They then
claimed strip width, forced the type scale down and inverted the hierarchy. Here they are carved out of
the flow and set as ONE fine-print group (the footer band) that runs along the bottom edge on its own
calm ground, so the flow above gets the freed height and width.

Nothing is hidden or dropped: every carved unit is realised, visible and on-canvas, at the largest
common scale `t` that fits the band (font = source font x t, aspect kept, letter_spacing scaled by the
renderer-side contract repair like any other text). The band never out-sizes the flow: its fonts are
capped under the smallest running text of the chosen plan.
"""
from __future__ import annotations

import dataclasses
import math

from . import search as S
from . import textfit as T
from .decompile import FLOOR_JPX, INF

BAND_FRAC = {"strip": 0.30, "wide": 0.22, "squareish": 0.24, "tall": 0.22}
SMALL_AREA = 110_000                  # px^2: tiny canvases (300x250, 160x600, 336x280 ...) are dense too
T_MIN, T_MAX = 0.04, 1.0
CAP_RATIO = 0.9                       # band font <= 0.9 x the smallest running-text font of the flow


def applies(CW, CH):
    return S.band(CW, CH) == "strip" or CW * CH <= SMALL_AREA


def is_minor(u, assets_dir):
    """Fine print, badge chips and the placeholder of an unresolvable asset: never the message itself."""
    if u.kind == "text":
        return u.role == "legal"
    if u.kind in ("pill", "chips"):
        return u.role in ("badge", "badges")
    if u.kind == "image":
        return T.asset_info(assets_dir, u.head.get("asset_id")) is None
    return False


def pick(g, assets_dir):
    return [u for u in g.stream if is_minor(u, assets_dir)]


def carve(g, units):
    """A copy of the galley without `units` (labels re-joined with the stronger separation)."""
    rank = {"S": 0, "C": 1, "R": 2}
    gone = {id(u) for u in units}
    stream, labels = [], []
    pending = None
    for i, u in enumerate(g.stream):
        lab = g.labels[i - 1] if i > 0 else None
        if id(u) in gone:
            if lab is not None:
                pending = lab if pending is None or rank[lab] > rank[pending] else pending
            continue
        if stream:
            cand = [x for x in (pending, lab) if x is not None]
            labels.append(max(cand, key=lambda x: rank[x]) if cand else "R")
        stream.append(u)
        pending = None
    return dataclasses.replace(g, stream=stream, labels=labels, src_gaps=[], gap_axes=[])


def _src_key(u):
    return (round(u.ink[1] / 20.0), u.ink[0])


class Band:
    """Fine-print band solver for one set of carved units on one canvas."""

    def __init__(self, units, g, CW, CH, assets_dir):
        self.units = sorted(units, key=_src_key)
        self.fixed = [u for u in self.units if u.kind != "text"]
        self.legal = [u for u in self.units if u.kind == "text"]
        self.CW, self.CH, self.assets = float(CW), float(CH), assets_dir
        self.strip = S.band(CW, CH) == "strip"
        self.js = T.judge_scale(CW, CH)
        self.mx = max(6.0, min(0.04 * CW, 0.13 * CH if self.strip else 0.065 * min(CW, CH)))
        self.mb = max(2.0, 0.05 * CH) if self.strip else max(4.0, 0.03 * CH)
        self.Wa = CW - 2 * self.mx
        self.budget = max(8.0, BAND_FRAC[S.band(CW, CH)] * CH)

    # -- sizes of one unit at scale t
    def measure(self, u, t, row_h=None):
        if u.kind == "pill":
            lab, sh = u.text_el(), u.shape_el()
            f = max(1, int(round(float(lab["font_size"]) * t)))
            s = f / float(lab["font_size"])
            h = sh["height"] * s
            w = max(T.one_line(lab, f) + 0.6 * h + 2, 1.0)
            return {"w": w, "h": h, "f": f, "s": s, "extra": {"w_pref": w}}
        if u.kind == "chips":
            lab0 = u.members[0].text_el()
            f = max(1, int(round(float(lab0["font_size"]) * t)))
            s = f / float(lab0["font_size"])
            ws, hs = [], []
            for p in u.members:
                sh, lab = p.shape_el(), p.text_el()
                fh = sh["height"] * s
                ws.append(max(sh["width"] * s * 0.85, T.one_line(lab, f) + 0.6 * fh + 2))
                hs.append(fh)
            w = sum(ws) + u.gap_src * s * (len(ws) - 1)
            return {"w": w, "h": max(hs), "f": f, "s": s, "extra": {"ws": ws, "hs": hs}}
        if u.kind == "image":
            el = u.head
            h = min(max(t * el["height"], 6.0), 0.9 * self.budget)
            s = h / el["height"]
            return {"w": el["width"] * s, "h": h, "f": 0, "s": s, "extra": {"s_fit": s}}
        return None

    def text_at(self, u, t, avail_w, max_h):
        """(f, k, w, h) of a legal line at scale t within a width and a height; None if it cannot fit."""
        el = u.head
        f = max(1, int(round(float(el["font_size"]) * t)))
        for k in (1, 2, 3):
            w = T.W_k(el, f, k)
            h = T.text_h(el, f, k)
            if w <= avail_w + 1e-6 and h <= max_h + 1e-6:
                return f, k, w, h
        return None

    # -- layout at scale t: rows of placed specs, total height; None when it does not fit the budget
    def layout(self, t, budget=None):
        budget = self.budget if budget is None else budget
        gap = max(4.0, 0.012 * self.CW) if self.strip else max(3.0, 0.02 * self.CH)
        meas = [(u, self.measure(u, t)) for u in self.fixed]
        if any(m["w"] > self.Wa + 1e-6 or m["h"] > budget + 1e-6 for _, m in meas):
            return None
        rows = []                               # each row: [(unit, spec)]
        if self.strip:
            row, used = [], 0.0
            for u, m in meas:
                row.append((u, m))
                used += m["w"] + (gap if len(row) > 1 else 0.0)
            if used > self.Wa + 1e-6:
                return None
            rows = [row]
        else:
            row, used = [], 0.0
            for u, m in meas:
                need = m["w"] + (gap if row else 0.0)
                if row and used + need > self.Wa + 1e-6:
                    rows.append(row)
                    row, used = [], 0.0
                    need = m["w"]
                row.append((u, m))
                used += need
            if row:
                rows.append(row)
        # legal text: in a strip it fills the row's remaining width; otherwise it takes rows of its own
        for u in self.legal:
            if self.strip:
                row = rows[0] if rows else []
                used = sum(m["w"] for _, m in row) + gap * len(row)
                avail = self.Wa - used
                hrow = max([m["h"] for _, m in row] + [0.0])
                r = self.text_at(u, t, avail, budget)
                if r is None:
                    return None
                f, k, w, h = r
                spec = {"w": avail, "h": h, "f": f, "s": f / float(u.head["font_size"]), "k": k, "tw": w, "extra": {}}
                if rows:
                    rows[0].append((u, spec))
                else:
                    rows.append([(u, spec)])
            else:
                r = self.text_at(u, t, self.Wa, budget)
                if r is None:
                    return None
                f, k, w, h = r
                rows.append([(u, {"w": self.Wa, "h": h, "f": f, "s": f / float(u.head["font_size"]), "k": k,
                                  "tw": w, "extra": {}})])
        heights = [max(m["h"] for _, m in r) for r in rows]
        total = sum(heights) + gap * (len(rows) - 1)
        if total > budget + 1e-6:
            return None
        return {"rows": rows, "heights": heights, "h": total, "gap": gap, "t": t}

    def solve(self, t_max=T_MAX, budget=None):
        """Largest t <= t_max whose layout fits (bisection: widths and heights grow with t)."""
        lo, hi = T_MIN, max(T_MIN, t_max)
        if self.layout(hi, budget) is not None:
            return self.layout(hi, budget)
        if self.layout(lo, budget) is None:
            return None
        for _ in range(14):
            mid = (lo + hi) / 2
            if self.layout(mid, budget) is not None:
                lo = mid
            else:
                hi = mid
        return self.layout(lo, budget)

    def place(self, lay, y_bottom):
        """Concrete Items (absolute coordinates): rows stacked upward from y_bottom, centred on the canvas."""
        items = []
        y = y_bottom - lay["h"]
        for row, rh in zip(lay["rows"], lay["heights"]):
            widths = [m["w"] for _, m in row]
            total = sum(widths) + lay["gap"] * (len(row) - 1)
            x = self.mx + max(0.0, (self.Wa - total) / 2)
            for (u, m), w in zip(row, widths):
                h = m["h"]
                it = S.Item(u, x, y + (rh - h) / 2, w, h, f=m.get("f", 0), k=m.get("k", 0), s=m.get("s", 1.0),
                            extra=dict(m.get("extra", {})))
                if u.kind == "text":                           # a legal line keeps its alignment inside its box
                    pass
                items.append(it)
                x += w + lay["gap"]
            y += rh + lay["gap"]
        return items


def cap_for(plan, ctx):
    """Largest band font allowed under the flow's own running text (a footer never out-sizes the message)."""
    fs = [f for (e, f, r, it) in S.text_items(plan) if r in ("headline", "subhead", "body")]
    return max(1, int(math.floor(CAP_RATIO * min(fs)))) if fs else 10 ** 6


def finalize(band, plan, ctx, y_bottom):
    """Band Items for one plan (fonts capped under the plan's running text) + their energy terms."""
    cap = cap_for(plan, ctx)
    lay = band.solve()
    if lay is None:
        return None
    guard = 0
    while lay is not None and guard < 24 and _max_font(lay) > cap and lay["t"] > T_MIN * 1.05:
        lay = band.solve(t_max=lay["t"] * 0.94)
        guard += 1
    if lay is None:
        return None
    items = band.place(lay, y_bottom)
    return items, lay


def _max_font(lay):
    return max([m.get("f", 0) for r in lay["rows"] for _, m in r] + [0])


def energy(items, ctx):
    """Per-unit energy terms (the same as search.energy's size and legibility terms) of the band items."""
    tot = 0.0
    for it in items:
        u = it.unit
        imp = S._imp(u)
        if u.kind == "text":
            s = it.f / float(u.head["font_size"])
            role = S.text_role(u)
            comf = 1.35 * FLOOR_JPX.get(role, 10)
            tot -= S.W["size"] * imp * S.utility(s, ctx)
            tot += S.W["leg"] * imp * max(0.0, (comf - it.f * ctx.js) / comf) ** 2
        elif u.kind in ("pill", "chips"):
            lab = u.text_el()
            comf = 1.35 * FLOOR_JPX.get(S.text_role(u), 10)
            tot -= S.W["size"] * imp * S.utility(it.f / float(lab["font_size"]), ctx)
            tot += S.W["leg"] * imp * max(0.0, (comf - it.f * ctx.js) / comf) ** 2
        elif u.kind == "image":
            tot -= S.W["size"] * imp * S.utility(it.s, ctx)
    return tot


# ----------------------------------------------------------------------------- variant comparison
_W_ROLE = {"headline": 3.0, "cta_label": 2.0, "subhead": 1.5, "body": 1.0, "badge_label": 0.7, "legal": 0.5,
           "unknown": 0.7}


def quality(source, out, info):
    """How readable and how well ordered the type of one finished output is, in [0, 1] (higher is better).
    Role-weighted perceived size against the legibility floors, minus hierarchy inversions against the source.
    Independent of the search energy, so layered and unlayered variants (different floors) are comparable."""
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    js = T.judge_scale(W, H)
    roles = (info or {}).get("roles") or {}
    src = {e["id"]: e for e in source["elements"]}
    rows = []
    for e in out["elements"]:
        if e["type"] != "text" or not str(e.get("content", "")).strip() or e["id"] not in src:
            continue
        r = roles.get(e["id"], "unknown")
        r = r if r in _W_ROLE else "unknown"
        f = float(e.get("font_size", 1))
        rows.append((e["id"], r, f, float(src[e["id"]].get("font_size", 12))))
    if not rows:
        return 1.0
    tot = sum(_W_ROLE[r] for _, r, _, _ in rows)
    good = sum(_W_ROLE[r] * min(1.0, f * js / FLOOR_JPX.get(r, 10)) for _, r, f, _ in rows)
    bad = 0.0
    for (_, ra, fa, sa) in rows:
        for (_, rb, fb, sb) in rows:
            if sa >= 1.1 * sb and fa < fb:
                bad += 0.5 * min(_W_ROLE[ra], _W_ROLE[rb]) * min(1.0, (fb - fa) / max(1.0, fb))
    return max(0.0, (good - bad) / tot)
