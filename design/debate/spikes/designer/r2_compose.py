"""Spike: DESIGNER re-layout engine (archetype composer + elastic type + tier dropping).

Not production code. Purpose: show that the rules in round1/designer.md produce
intentional-looking renders on the official renderer, with roles inferred from
ANONYMISED inputs (ids replaced by random tokens, see roles.py). Run from repo root:
    .venv/bin/python design/debate/spikes/designer/compose.py
"""
from __future__ import annotations

import copy
import json
import math
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).parent))

import skia  # noqa: E402
from renderer.converter.brand_fonts import load_brand_font_manager  # noqa: E402
from renderer.converter.convert import render_design_to_png  # noqa: E402
from renderer.converter.wrap import char_widths, wrap_text  # noqa: E402
from roles import asset_stats, infer_roles  # noqa: E402
import r2_ground as G  # noqa: E402

ASSETS = "brand_kit/assets"
ALLOW_RECOLOR = True
_last_log = []
OUT = Path(__file__).parent
FM = load_brand_font_manager("brand_kit/fonts")

# =============================================================== type metrics

def _fontargs(el):
    bold = el.get("font_weight") == "bold"
    ital = el.get("font_style") == "italic"
    weight = "bold" if bold else "regular"
    style = "bolditalic" if bold and ital else "bold" if bold else "italic" if ital else "regular"
    return el["font_family"], weight, style


_MC = {}


def metrics(el):
    key = _fontargs(el)
    if key not in _MC:
        tf = skia.Typeface.MakeFromData(FM.lookup(*key))
        m = skia.Font(tf, 100).getMetrics()
        _MC[key] = (-m.fAscent / 100, m.fCapHeight / 100, m.fDescent / 100)
    return _MC[key]  # ascent, cap height, descent (em)


def wrap(el, fs, width):
    """Exactly what the official renderer will do -> (lines, widest line px)."""
    fam, w, s = _fontargs(el)
    widths = char_widths(FM, fam, w, s, int(fs), el["content"])
    wrapped = wrap_text(el["content"], widths, width)
    lines, start, widest = [], 0, 0.0
    for i, c in enumerate(wrapped + "\n"):
        if c == "\n":
            lines.append(wrapped[start:i])
            widest = max(widest, sum(widths[start:i]))
            start = i + 1
    return lines, widest


def balanced_width(el, fs, maxw):
    """CSS `text-wrap: balance`, emulated by bisecting the box width (renderer wraps greedily)."""
    lines, widest = wrap(el, fs, maxw)
    n = len(lines)
    if n <= 1:
        return min(maxw, widest + 4)
    lo, hi = maxw / n * 0.9, maxw
    for _ in range(16):
        mid = (lo + hi) / 2
        if len(wrap(el, fs, mid)[0]) <= n:
            hi = mid
        else:
            lo = mid
    return min(maxw, hi + 1)


def text_block(el, fs, width):
    lines, widest = wrap(el, fs, width)
    asc, cap, desc = metrics(el)
    lh = el.get("line_height", 1.2)
    return {"n": len(lines), "widest": widest, "fs": int(fs),
            "opt_h": (len(lines) - 1) * lh * fs + cap * fs,  # cap-top -> last baseline
            "top_off": (asc - cap) * fs}


def place_text(el, fs, width, opt_top, anchor_x, align="center", H=None):
    """Geometry such that line 1's cap-top sits exactly at opt_top (optical alignment)."""
    b = text_block(el, fs, width)
    asc, cap, desc = metrics(el)
    lh = el.get("line_height", 1.2)
    el["font_size"] = int(fs)
    el["width"] = round(width, 2)
    el["x"] = round({"center": anchor_x - width / 2, "left": anchor_x, "right": anchor_x - width}[align], 2)
    el["y"] = round(opt_top - b["top_off"], 2)
    el["height"] = round((b["n"] - 1) * lh * fs + (asc + desc) * fs, 2)
    if H is not None:
        el["height"] = round(max(1.0, min(el["height"], H - el["y"])), 2)
    return b


def fit_text(el, maxw, max_opt_h, fs_hi, fs_lo, max_lines):
    for fs in range(int(fs_hi), int(fs_lo) - 1, -1):
        b = text_block(el, fs, maxw)
        if b["n"] <= max_lines and b["opt_h"] <= max_opt_h and b["widest"] <= maxw:
            return b
    return None

# =============================================================== images (optical bounds)


def optics(el):
    """Visible-content rectangle of a contain-fit image, as fractions of its box."""
    st = asset_stats(ASSETS, el.get("asset_id"))
    if st is None:
        return (0.0, 0.0, 1.0, 1.0)
    iw, ih = st["size"]
    bw, bh = el["width"], el["height"]
    s = min(bw / iw, bh / ih)
    ox, oy = (bw - iw * s) / 2, (bh - ih * s) / 2
    x0, y0, x1, y1 = st["bbox"]
    return ((ox + x0 * s) / bw, (oy + y0 * s) / bh, (ox + x1 * s) / bw, (oy + y1 * s) / bh)


def place_image(out_el, src_el, vis_h, vis_cx, vis_cy, W, H):
    """Size an image by its VISIBLE height, keep source box aspect, then keep the BOX in-canvas
    (shrinking if the transparent padding would push the box off-canvas)."""
    fr = optics(src_el)
    ar = src_el["width"] / src_el["height"]
    for _ in range(40):
        bh = vis_h / (fr[3] - fr[1])
        bw = bh * ar
        x = vis_cx - (fr[0] + fr[2]) / 2 * bw
        y = vis_cy - (fr[1] + fr[3]) / 2 * bh
        x = min(max(0.0, x), W - bw)
        y = min(max(0.0, y), H - bh)
        if bw <= W + 0.01 and bh <= H + 0.01 and x >= -0.01 and y >= -0.01:
            break
        vis_h *= 0.97
    out_el.update(x=round(x, 2), y=round(y, 2), width=round(bw, 2), height=round(bh, 2))
    return (x + fr[0] * bw, y + fr[1] * bh, x + fr[2] * bw, y + fr[3] * bh)  # visible rect

# =============================================================== legibility & elasticity

FLOOR_JUDGE = {"headline": 14, "subhead": 11, "chip": 11, "legal": 9, "body": 11}
GAMMA = {"headline": 1.0, "subhead": 0.75, "body": 0.75, "chip": 0.6, "legal": 0.35}


def floor_px(role, W, H):
    judge_scale = min(1.0, 1024 / max(W, H))  # judge sees ~1k px on the long side
    return math.ceil(FLOOR_JUDGE[role] / judge_scale)


GAMMA_DOWN = {"headline": 0.8, "subhead": 0.6, "body": 0.6, "chip": 0.5, "legal": 0.3}


def elastic(fs_src, k, role):
    """Display type is elastic, text type is stubborn; when shrinking, pictures give way before words."""
    return fs_src * (k ** (GAMMA if k >= 1 else GAMMA_DOWN)[role])

# =============================================================== tier dropping


def _transparent(color):
    m = re.match(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", color or "")
    return f"rgba({m.group(1)},{m.group(2)},{m.group(3)},0)" if m else "rgba(0,0,0,0)"


def hide(el, src_canvas, W, H):
    """Element dropped for this format: opacity 0 (intent) + text colour alpha 0 (the official
    renderer IGNORES text opacity - verified). RGB kept, so the palette is unchanged. Geometry is
    a proportional, in-bounds 'parking' spot so the JSON stays sane."""
    s = min(W / src_canvas["width"], H / src_canvas["height"])
    w, h = max(1.0, el["width"] * s), max(1.0, el["height"] * s)
    w, h = min(w, W), min(h, H)
    cx = (el["x"] + el["width"] / 2) / src_canvas["width"] * W
    cy = (el["y"] + el["height"] / 2) / src_canvas["height"] * H
    el.update(width=round(w, 2), height=round(h, 2),
              x=round(min(max(0, cx - w / 2), W - w), 2), y=round(min(max(0, cy - h / 2), H - h), 2))
    el["opacity"] = 0
    if el["type"] == "text":
        el["font_size"] = max(1, int(el["font_size"] * s))
        el["color"] = _transparent(el.get("color"))
        if el.get("style_runs"):
            el["style_runs"] = [dict(r, color=_transparent(r["color"])) if "color" in r else r
                                for r in el["style_runs"]]
    return el

# =============================================================== chips (button / badge anatomy)


def chip_anatomy(shape_src, label_src):
    lab_w = wrap(label_src, label_src["font_size"], 1e5)[1]
    fs = label_src["font_size"]
    return {"h": shape_src["height"] / fs,
            "padx": max(0.0, (shape_src["width"] - lab_w) / 2 / fs),
            "radius": shape_src.get("corner_radius", 0) / max(1, min(shape_src["width"], shape_src["height"]))}


def chip_size(label, an, fs, h_band=(2.2, 3.4), pad_band=(1.0, 2.2)):
    lab_w = wrap(label, fs, 1e5)[1]
    h = fs * min(max(an["h"], h_band[0]), h_band[1])
    return lab_w + 2 * fs * min(max(an["padx"], pad_band[0]), pad_band[1]), h


def build_chip(shape, label, an, fs, x, cy, w, h):
    shape.update(x=round(x, 2), y=round(cy - h / 2, 2), width=round(w, 2), height=round(h, 2))
    shape["corner_radius"] = round(an["radius"] * min(w, h), 2)  # a pill stays a pill
    asc, cap, desc = metrics(label)
    label.update(font_size=int(fs), width=round(w, 2), x=round(x, 2),
                 y=round(cy - (asc - cap / 2) * fs, 2))           # caps optically centred
    label["height"] = round(min((asc + desc) * fs, h), 2)

# =============================================================== archetypes


def archetype(W, H):
    r = W / H
    if r >= 4.5 or (r >= 3 and H <= 120):
        return "strip"
    if r >= 1.3:
        return "split"
    return "stack"


class Ctx:
    def __init__(self, task):
        self.src = task["source"]
        self.W, self.H = task["target_canvas"]["width"], task["target_canvas"]["height"]
        self.sW, self.sH = self.src["canvas"]["width"], self.src["canvas"]["height"]
        self.roles, self.meta = infer_roles(self.src, ASSETS)
        self.panels = G.find_panels(self.src, self.roles)
        self.group_y = {}
        for pid, p in self.panels.items():
            self.roles[pid] = "panel"
            gy = min(e["y"] for e in self.src["elements"] if e["id"] in p["riders"])
            for r in p["riders"]:
                self.group_y[r] = gy
        heads = [e for e in self.src["elements"] if self.roles[e["id"]] in ("headline", "subhead")]
        self.axis = "left" if heads and all(e.get("text_align", "left") == "left" for e in heads) else "center"
        self.byid = {e["id"]: e for e in self.src["elements"]}
        self.by_role = {}
        for e in self.src["elements"]:
            self.by_role.setdefault(self.roles[e["id"]], []).append(e)
        self.out = {e["id"]: copy.deepcopy(e) for e in self.src["elements"]}
        self.placed = set()
        self.visible_rects = {}  # id -> optical rect of placed content (for decoration anchoring)

    def okey(self, eid, y):
        return (self.group_y.get(eid, y), y)   # riders of one panel stay contiguous in reading order

    def one(self, role):
        lst = self.by_role.get(role, [])
        return lst[0] if lst else None

    def chips(self, kind):
        return [(s, self.byid[self.meta[s["id"]]["partner"]]) for s in self.by_role.get(kind + "_bg", [])]


def compose(task):
    c = Ctx(task)
    W, H = c.W, c.H
    for bg in c.by_role.get("background", []):
        c.out[bg["id"]].update(x=0, y=0, width=W, height=H)
        c.placed.add(bg["id"])
    arche = archetype(W, H)
    if arche == "split" and not c.one("hero"):
        arche = "stack"       # no hero to put beside the message: a centred stack is the honest layout
    c.tall = H / W >= 1.5
    {"strip": compose_strip, "split": compose_split, "stack": compose_stack}[arche](c)
    if arche != "strip":
        place_decorations(c)
    c.ground_log = G.apply_grounds(sys.modules[__name__], c, arche, allow_recolor=ALLOW_RECOLOR)
    global _last_log
    _last_log = c.ground_log
    for eid, el in c.out.items():
        if eid not in c.placed:
            hide(el, c.src["canvas"], W, H)
    return {"canvas": {"width": W, "height": H}, "elements": [c.out[e["id"]] for e in c.src["elements"]]}, arche


# ---------------------------------------------------------------- strip (leaderboard / mobile banner)

def compose_strip(c):
    W, H, out = c.W, c.H, c.out
    m = max(8, round(0.13 * H))
    cy = H / 2
    left, right = m, W - m
    logo = c.one("logo")
    if logo:
        fr = optics(logo)
        vis = place_image(out[logo["id"]], logo, 0.62 * H, m + 1e3, cy, W, H)  # provisional
        vis_w = vis[2] - vis[0]
        vis = place_image(out[logo["id"]], logo, vis[3] - vis[1], m + vis_w / 2, cy, W, H)
        c.placed.add(logo["id"])
        left = vis[2] + 0.9 * m
    cta = c.chips("cta")
    if cta:
        s, t = cta[0]
        an = chip_anatomy(s, t)
        fs = max(floor_px("chip", W, H), round(0.16 * H))
        w, h = chip_size(t, an, fs, h_band=(2.2, 2.8), pad_band=(1.0, 1.6))
        h = min(h, H - 2 * m)
        build_chip(out[s["id"]], out[t["id"]], an, fs, right - w, cy, w, h)
        c.placed.update({s["id"], t["id"]})
        right = right - w - 0.9 * m
    elif c.one("cta_text"):
        t = c.one("cta_text")
        b = fit_text(t, 0.3 * W, H - 2 * m, round(0.2 * H), floor_px("chip", W, H), 1)
        if b:
            place_text(out[t["id"]], b["fs"], b["widest"] + 4, cy - b["opt_h"] / 2, right, "right", H)
            c.placed.add(t["id"])
            right -= b["widest"] + 0.9 * m
    head, sub, hero = c.one("headline"), c.one("subhead"), c.one("hero")
    avail = H - 2 * m

    def message(col_l, col_r, dry=False):
        col_w, col_cx = col_r - col_l, (col_l + col_r) / 2
        hf = floor_px("headline", W, H)
        b = fit_text(head, col_w, avail, min(head["font_size"], round(0.36 * H)), hf, 3) or \
            fit_text(head, col_w, avail, hf, max(10, hf - 2), 4)
        if not b:
            return None
        sb = None
        if sub:
            gap = 0.4 * b["fs"]
            cand = fit_text(sub, col_w, avail - b["opt_h"] - gap, min(sub["font_size"], int(b["fs"] / 1.3)),
                            floor_px("subhead", W, H), 1)
            if cand and cand["fs"] * 1.25 <= b["fs"]:   # hierarchy guard: never flatten
                sb = cand
        if dry:
            return b
        total = b["opt_h"] + ((0.4 * b["fs"] + sb["opt_h"]) if sb else 0)
        top = cy - total / 2
        place_text(out[head["id"]], b["fs"], balanced_width(head, b["fs"], col_w), top, col_cx, "center", H)
        c.placed.add(head["id"])
        if sb:
            place_text(out[sub["id"]], sb["fs"], balanced_width(sub, sb["fs"], col_w),
                       top + b["opt_h"] + 0.4 * b["fs"], col_cx, "center", H)
            c.placed.add(sub["id"])
        return b

    if not head:
        return
    # Optional hero slot: only if the message still reads comfortably with it (priority test).
    if hero:
        fr = optics(hero)
        vis_h = 0.84 * H
        vis_w = vis_h * (fr[2] - fr[0]) / (fr[3] - fr[1]) * (hero["width"] / hero["height"]) / 1.0
        bw_ratio = (fr[2] - fr[0]) / (fr[3] - fr[1]) * hero["width"] / hero["height"]
        vis_w = vis_h * bw_ratio
        trial = message(left + vis_w + 0.9 * m, right, dry=True)
        if trial and trial["n"] <= 2 and trial["fs"] >= max(floor_px("headline", W, H), 0.2 * H):
            place_image(out[hero["id"]], hero, vis_h, left + vis_w / 2, cy, W, H)
            c.placed.add(hero["id"])
            left += vis_w + 0.9 * m
    message(left, right)
    if hero and hero["id"] in c.placed and (hero["x"] + hero["width"] / 2) > 0.6 * c.sW:
        hv = c.out[hero["id"]]
        fr = optics(hv)
        vis_w = (fr[2] - fr[0]) * hv["width"]
        delta = vis_w + 0.9 * m
        for e in c.src["elements"]:
            if e["id"] in c.placed and c.roles[e["id"]] in ("headline", "subhead", "cta_bg", "cta_label", "cta_text"):
                out[e["id"]]["x"] = round(out[e["id"]]["x"] - delta, 2)
        hv["x"] = round(min(W - m - fr[2] * hv["width"], W - hv["width"]), 2)   # hero to the far right, like the source


# ---------------------------------------------------------------- vertical stack measuring (shared)

def measure_item(c, kind, k, col_w):
    W, H = c.W, c.H
    if kind == "logo":
        lg = c.one("logo")
        fr = optics(lg)
        floor = 24 / min(1.0, 1024 / max(W, H))
        return {"kind": kind, "el": lg, "h": max(floor, lg["height"] * (fr[3] - fr[1]) * k)}
    if kind == "hero":
        hr = c.one("hero")
        fr = optics(hr)
        vis_h = hr["height"] * (fr[3] - fr[1]) * k
        vis_w = hr["width"] * (fr[2] - fr[0]) * k
        if vis_w > col_w:
            return None
        return {"kind": kind, "el": hr, "h": vis_h}
    if kind in ("headline", "subhead", "body", "cta_text", "legal"):
        el = c.one(kind)
        role = {"cta_text": "chip"}.get(kind, kind)
        fs = max(floor_px(role, W, H), round(elastic(el["font_size"], k, role)))
        meas = min(col_w, max(el["width"] * W / c.sW, 0.5 * col_w))
        b = text_block(el, fs, meas)
        src_lines = text_block(el, el["font_size"], el["width"])["n"]
        grow_extra = 1 if (k < 1 or getattr(c, "tall", False)) else 0
        max_lines = src_lines + grow_extra if kind == "headline" else max(src_lines + 1, 2 if kind != "legal" else 3)
        if b["widest"] > meas or b["n"] > max_lines:
            return None
        return {"kind": kind, "el": el, "b": b, "meas": meas, "h": b["opt_h"]}
    if kind == "cta":
        s, t = c.chips("cta")[0]
        an = chip_anatomy(s, t)
        fs = max(floor_px("chip", W, H), round(elastic(t["font_size"], k, "chip")))
        w, h = chip_size(t, an, fs)
        if w > col_w:
            return None
        return {"kind": kind, "pair": (s, t), "an": an, "fs": fs, "w": w, "h": h}
    if kind == "badges":
        pairs = [p for p in c.chips("badge") if not _cornered(c, p[0]) and p[0]["id"] not in c.placed]
        if not pairs:
            return None
        fs = max(floor_px("chip", W, H), round(elastic(pairs[0][1]["font_size"], k, "chip")))
        sizes = []
        for s, t in pairs:
            sizes.append(chip_size(t, chip_anatomy(s, t), fs, h_band=(2.3, 3.4), pad_band=(0.8, 2.0)))
        g = 0.8 * fs
        keep = len(sizes)
        while keep > 0 and sum(w for w, _ in sizes[:keep]) + g * (keep - 1) > col_w:
            keep -= 1          # N-of-M: a variable badge set degrades from its tail
        if keep == 0:
            return None
        return {"kind": kind, "pairs": pairs[:keep], "fs": fs, "sizes": sizes[:keep], "g": g,
                "h": max(h for _, h in sizes[:keep])}
    raise ValueError(kind)


def emit_item(c, it, cx, top):
    out, W, H = c.out, c.W, c.H
    kind = it["kind"]
    if getattr(c, "axis", "center") == "left" and getattr(c, "axis_x", None) is not None:
        if kind in ("headline", "subhead", "body", "cta_text", "legal"):
            el, b = it["el"], it["b"]
            if kind == "headline":
                c.head_fs = b["fs"]
            bw = balanced_width(el, b["fs"], it["meas"]) if b["n"] > 1 else b["widest"] + 4
            place_text(out[el["id"]], b["fs"], bw, top, c.axis_x, el.get("text_align", "left"), H)
            c.visible_rects[el["id"]] = (c.axis_x, top, c.axis_x + b["widest"], top + b["opt_h"])
            c.placed.add(el["id"])
            return
        cx = c.axis_x + item_width(it) / 2
    if kind in ("logo", "hero"):
        vis = place_image(out[it["el"]["id"]], it["el"], it["h"], cx, top + it["h"] / 2, W, H)
        c.visible_rects[it["el"]["id"]] = vis
        c.placed.add(it["el"]["id"])
    elif kind in ("headline", "subhead", "body", "cta_text", "legal"):
        el, b = it["el"], it["b"]
        if kind == "headline":
            c.head_fs = b["fs"]
        bw = balanced_width(el, b["fs"], it["meas"])
        place_text(out[el["id"]], b["fs"], bw, top, cx, "center", H)
        c.visible_rects[el["id"]] = (cx - b["widest"] / 2, top, cx + b["widest"] / 2, top + b["opt_h"])
        c.placed.add(el["id"])
    elif kind == "cta":
        s, t = it["pair"]
        build_chip(out[s["id"]], out[t["id"]], it["an"], it["fs"], cx - it["w"] / 2, top + it["h"] / 2, it["w"], it["h"])
        c.visible_rects[s["id"]] = (cx - it["w"] / 2, top, cx + it["w"] / 2, top + it["h"])
        c.placed.update({s["id"], t["id"]})
    elif kind == "badges":
        tot = sum(w for w, _ in it["sizes"]) + it["g"] * (len(it["sizes"]) - 1)
        x = cx - tot / 2
        for (s, t), (w, h) in zip(it["pairs"], it["sizes"]):
            build_chip(out[s["id"]], out[t["id"]], chip_anatomy(s, t), it["fs"], x, top + it["h"] / 2, w, it["h"])
            c.visible_rects[s["id"]] = (x, top, x + w, top + it["h"])
            c.placed.update({s["id"], t["id"]})
            x += w + it["g"]


def item_width(it):
    if "b" in it:
        return it["b"]["widest"]
    if it["kind"] in ("logo", "hero"):
        fr = optics(it["el"])
        return it["h"] * (fr[2] - fr[0]) / (fr[3] - fr[1]) * it["el"]["width"] / it["el"]["height"]
    if it["kind"] == "cta":
        return it["w"]
    if it["kind"] == "badges":
        return sum(w for w, _ in it["sizes"]) + it["g"] * (len(it["sizes"]) - 1)
    return 0.0


def _fs(it):
    if "b" in it:
        return it["b"]["fs"]
    return it.get("fs", 0)


def min_gap(a, b):
    """A typographer never lets two blocks kiss: descender room + half an em of the larger size."""
    desc = 0.25 * a["b"]["fs"] if "b" in a else 0.0
    return desc + 0.8 * max(_fs(a), _fs(b), 8)


def hierarchy_ok(items):
    """The headline must still out-rank every other text (>= 1.2x) after floors are applied."""
    head = next((i for i in items if i["kind"] == "headline"), None)
    if head is None:
        return True
    others = [_fs(i) for i in items if i["kind"] in ("subhead", "body", "cta_text", "cta", "badges")]
    return all(head["b"]["fs"] >= 1.2 * f for f in others)


def stack_height(items, gaps):
    return sum(it["h"] for it in items) + sum(gaps)


def solve_stack(c, kinds, col_w, avail_h, gap_fn, k_lo=0.15, k_hi=4.0, target_h=None):
    """Largest elasticity k (ratio-preserving) whose stack fits avail_h (or matches target_h)."""
    best = None
    lo, hi = k_lo, k_hi
    for _ in range(22):
        k = (lo + hi) / 2
        items = [measure_item(c, kd, k, col_w) for kd in kinds]
        if any(i is None for i in items):
            hi = k
            continue
        if not hierarchy_ok(items):
            lo = k          # floors flattened the hierarchy: need a bigger k (or a dropped tier)
            continue
        gaps = [max(g, min_gap(a, b)) for g, a, b in zip(gap_fn(items, k), items, items[1:])]
        tot = stack_height(items, gaps)
        if tot <= (target_h or avail_h) and tot <= avail_h:
            best, lo = (k, items, gaps, tot), k
        else:
            hi = k
    return best


# ---------------------------------------------------------------- split (landscape / wide banner)

def compose_split(c):
    W, H, out = c.W, c.H, c.out
    short = min(W, H)
    m = max(16, round(0.08 * short))
    hero = c.one("hero")
    hero_col, side = 0.0, "right"
    if hero:
        side = "left" if (hero["x"] + hero["width"] / 2) < 0.4 * c.sW else "right"
        fr = optics(hero)
        vis_h = 0.9 * (H - 2 * m)
        vis_w = vis_h * (fr[2] - fr[0]) / (fr[3] - fr[1]) * hero["width"] / hero["height"]
        hero_col = min(0.42 * W, vis_w + 3 * m)
        hcx = (W - m - hero_col / 2) if side == "right" else (m + hero_col / 2)
        c.visible_rects[hero["id"]] = place_image(out[hero["id"]], hero, vis_h, hcx, H / 2, W, H)
        c.placed.add(hero["id"])
    col_l = m if side == "right" else m + hero_col
    col_r = W - m - hero_col if side == "right" else W - m
    col_w = col_r - col_l
    top_band = 0.0
    before = set(c.placed)
    place_corner_chips(c, m, exclude_side=side if hero else None)
    if set(c.placed) - before:
        top_band = max(r[3] for i, r in c.visible_rects.items() if i in set(c.placed) - before) - m * 0.8 + 0.5 * m
    kinds = [k for k in ("logo", "headline", "subhead", "badges", "cta", "cta_text")
             if (c.chips(k[:-1] if k == "badges" else k) if k in ("cta", "badges") else c.one(k))]
    if "badges" in kinds and (W / H > 2.2 or all(p[0]["id"] in c.placed for p in c.chips("badge"))):
        kinds.remove("badges")   # wide banners: the badge row competes with the message, it goes first
    GAP = {"logo": 0.55, "headline": 0.45, "subhead": 0.7, "badges": 0.5, "cta_text": 0.4, "cta": 0.5}

    def gaps(items, k):
        hf = next((i["b"]["fs"] for i in items if i["kind"] == "headline"), 30)
        return [GAP[i["kind"]] * hf for i in items[:-1]]

    def logo_capped(items):
        return items

    claimed = [c.visible_rects[i] for i in set(c.placed) - before if i in c.visible_rects]

    def solve(band):
        ks = list(kinds)
        avail = H - 2 * m - 2 * band   # keep the stack optically centred under a corner badge
        while ks:
            b = solve_stack(c, ks, col_w, avail, gaps, target_h=0.9 * avail)
            if b:
                return b
            ks.remove(next((k for k in ("badges", "subhead", "cta_text", "logo") if k in ks), ks[-1]))
        return None

    def collides(b):
        y = (H - b[3]) / 2
        cx = (col_l + col_r) / 2
        for it, g in zip(b[1], b[2] + [0]):
            w = item_width(it)
            if any(_overlap((cx - w / 2, y, cx + w / 2, y + it["h"]), r) for r in claimed):
                return True
            y += it["h"] + g
        return False

    best = solve(0.0)
    if best and claimed and collides(best):
        best = solve(top_band)   # only pay for the corner badge when it actually gets in the way
    if not best:
        return
    k, items, gs, tot = best
    # logo in a wide format: cap its visible height relative to the canvas, recentre
    for it in items:
        if it["kind"] == "logo":
            it["h"] = min(it["h"], 0.2 * H)
    tot = stack_height(items, gs)
    y = (H - tot) / 2
    cx = (col_l + col_r) / 2
    c.axis_x = col_l + (m if c.panels else 0)
    for it, g in zip(items, gs + [0]):
        emit_item(c, it, cx, y)
        y += it["h"] + g


def place_corner_chips(c, m, exclude_side=None):
    """Badges/stickers that sat in a source corner go back to the same corner if it is free."""
    W, H, out = c.W, c.H, c.out
    for kind in ("badge", "sticker"):
        for s, t in c.chips(kind):
            if s["id"] in c.placed:
                continue
            cxs, cys = (s["x"] + s["width"] / 2) / c.sW, (s["y"] + s["height"] / 2) / c.sH
            if not _cornered(c, s):
                continue
            right = cxs > 0.5
            if exclude_side and (exclude_side == "right") == right:
                continue
            an = chip_anatomy(s, t)
            fs = max(floor_px("chip", W, H), round(t["font_size"] * (min(W, H) / min(c.sW, c.sH)) ** 0.6))
            head = c.one("headline")
            if head and getattr(c, "head_fs", None) and fs > 0.75 * c.head_fs:
                continue   # a badge that would out-shout the headline is dropped, not shrunk to mush
            w, h = chip_size(t, an, fs, h_band=(2.2, 3.0), pad_band=(1.0, 1.6))
            if w * h > 0.04 * W * H:
                continue   # on a small canvas a sticker would dominate: drop it
            x = W - m - w if right else m
            y = m * 0.8 if cys < 0.5 else H - m * 0.8 - h
            rect = (x, y, x + w, y + h)
            if any(_overlap(rect, r) for r in c.visible_rects.values()):
                continue
            build_chip(out[s["id"]], out[t["id"]], an, fs, x, y + h / 2, w, h)
            if abs(s.get("rotation", 0)) > 0:
                # rotated sticker: keep its angle, pull it in so the ROTATED corners stay on canvas
                ang = math.radians(abs(s["rotation"]))
                ex = (w * math.cos(ang) + h * math.sin(ang) - w) / 2
                ey = (w * math.sin(ang) + h * math.cos(ang) - h) / 2
                dx = -ex if right else ex
                dy = ey if cys < 0.5 else -ey
                for el in (out[s["id"]], out[t["id"]]):
                    el["x"] = round(el["x"] + dx, 2)
                    el["y"] = round(el["y"] + dy, 2)
            c.visible_rects[s["id"]] = rect
            c.placed.update({s["id"], t["id"]})


def _cornered(c, s):
    cxs, cys = (s["x"] + s["width"] / 2) / c.sW, (s["y"] + s["height"] / 2) / c.sH
    return (cxs < 0.3 or cxs > 0.7) and (cys < 0.2 or cys > 0.8)


def _overlap(a, b, pad=4):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


# ---------------------------------------------------------------- stack (square / portrait / story)

def compose_stack(c):
    W, H, out = c.W, c.H, c.out
    short = min(W, H)
    m = max(16, round(0.065 * short))
    col_w = W - 2 * m
    top_limit, bottom_limit = m, H - m
    # bottom-pinned legal (legible or absent)
    legal = c.one("legal")
    if legal:
        fs = max(floor_px("legal", W, H), round(elastic(legal["font_size"], short / min(c.sW, c.sH), "legal")))
        b = fit_text(legal, col_w, 3 * fs, fs, fs, 2)
        if b:
            place_text(out[legal["id"]], b["fs"], balanced_width(legal, b["fs"], col_w), H - m - b["opt_h"], W / 2, "center", H)
            c.placed.add(legal["id"])
            bottom_limit = H - m - b["opt_h"] - 1.2 * m
    # reading-order stack: everything in source order of optical top
    order = []
    for kind in ("logo", "hero", "headline", "subhead", "body", "badges", "cta", "cta_text"):
        if kind == "badges":
            pairs = [p for p in c.chips("badge") if p[0]["id"] not in c.placed and not _cornered(c, p[0])]
            if pairs:
                order.append((c.okey(pairs[0][0]["id"], min(p[0]["y"] for p in pairs)), kind))
        elif kind == "cta":
            if c.chips("cta"):
                order.append((c.okey(c.chips("cta")[0][0]["id"], c.chips("cta")[0][0]["y"]), kind))
        elif c.one(kind):
            order.append((c.okey(c.one(kind)["id"], c.one(kind)["y"]), kind))
    kinds = [k for _, k in sorted(order)]
    # source rhythm: optical gaps between consecutive items, normalised by the source short side
    src_top = {}
    for kd in kinds:
        it = measure_item(c, kd, 1.0, 1e5)
        el = it.get("el") or (it.get("pair") or it.get("pairs", [[None]])[0])[0]
        if kd == "badges":
            el = it["pairs"][0][0]
        if kd in ("logo", "hero"):
            fr = optics(el)
            src_top[kd] = (el["y"] + fr[1] * el["height"], el["y"] + fr[3] * el["height"])
        elif kd in ("cta", "badges"):
            src_top[kd] = (el["y"], el["y"] + el["height"])
        else:
            b = text_block(el, el["font_size"], el["width"])
            src_top[kd] = (el["y"] + b["top_off"], el["y"] + b["top_off"] + b["opt_h"])
    src_gaps = [max(0.0, src_top[b][0] - src_top[a][1]) for a, b in zip(kinds, kinds[1:])]
    span_src = src_top[kinds[-1]][1] - src_top[kinds[0]][0]
    # preserve the source's vertical density; small canvases get more fill (floors + gaps eat space)
    fill = min(0.92, span_src / c.sH + 0.25 * max(0.0, 1 - short / 800))

    def gaps(items, k):
        return [g * k for g in src_gaps]

    avail = bottom_limit - top_limit
    best = None
    while kinds:
        best = solve_stack(c, kinds, col_w, avail, gaps, target_h=fill * H)
        if best:
            head = next((i for i in best[1] if i["kind"] == "headline"), None)
            starving = head and head["b"]["fs"] < max(1.5 * floor_px("subhead", W, H), 0.025 * short)
            victim = next((k for k in ("badges", "body", "subhead") if k in kinds), None)
            if starving and victim:
                i = kinds.index(victim)
                trial = [k for k in kinds if k != victim]
                tg = src_gaps[:i] + src_gaps[i + 1:] if i < len(src_gaps) else src_gaps[:-1]
                saved = list(src_gaps)
                src_gaps[:] = tg
                alt = solve_stack(c, trial, col_w, avail, gaps, target_h=fill * H)
                if alt and next(x for x in alt[1] if x["kind"] == "headline")["b"]["fs"] > head["b"]["fs"]:
                    best, kinds = alt, trial
                else:
                    src_gaps[:] = saved
            break
        drop = next((k for k in ("badges", "body", "subhead", "hero") if k in kinds), kinds[-1])
        i = kinds.index(drop)
        kinds.pop(i)
        if i < len(src_gaps):
            src_gaps.pop(i if i < len(src_gaps) else -1)
    if not best:
        return
    k, items, gs, tot = best
    # vertical position: keep the source's optical centre ratio, clamped to the free band
    src_c = (src_top[kinds[0]][0] + src_top[kinds[-1]][1]) / 2 / c.sH
    y = min(max(top_limit, src_c * H - tot / 2), bottom_limit - tot)
    # logo stays pinned near the top like in the source if it led the stack
    c.axis_x = m
    for it, g in zip(items, gs + [0]):
        emit_item(c, it, W / 2, y)
        y += it["h"] + g
    # corner stickers / badges claim their source corner only if it is free and they don't out-shout
    place_corner_chips(c, m)


# ---------------------------------------------------------------- decorations

def place_decorations(c):
    """A decoration travels with the content element it overlapped most in the source (keeps the
    designer's intentional layering); if it overlapped nothing, it re-anchors to its corner."""
    W, H, out = c.W, c.H, c.out
    content = [e for e in c.src["elements"] if c.roles[e["id"]] not in ("background", "decoration", "broken")
               and e["id"] in c.visible_rects]
    halo_used = set()
    decos = sorted(c.by_role.get("decoration", []), key=lambda d: -d["width"] * d["height"])
    for d in decos:
        def ov(e):
            ix = max(0, min(d["x"] + d["width"], e["x"] + e["width"]) - max(d["x"], e["x"]))
            iy = max(0, min(d["y"] + d["height"], e["y"] + e["height"]) - max(d["y"], e["y"]))
            return ix * iy
        anchor = max(content, key=ov, default=None)
        o = out[d["id"]]
        if anchor is not None and ov(anchor) > 0 and anchor["type"] == "image" and anchor["id"] not in halo_used:
            halo_used.add(anchor["id"])
            vr = c.visible_rects[anchor["id"]]
            size = min(1.12 * (vr[3] - vr[1]), 0.98 * min(W, H))
            dcx, dcy = (vr[0] + vr[2]) / 2, (vr[1] + vr[3]) / 2
        elif anchor is not None and ov(anchor) > 0:
            a_src = anchor
            vr = c.visible_rects[anchor["id"]]
            sx = (vr[2] - vr[0]) / max(1, a_src["width"])
            sy = (vr[3] - vr[1]) / max(1, a_src["height"])
            s = math.sqrt(max(1e-6, sx * sy)) if c.roles[anchor["id"]] != "hero" else (vr[3] - vr[1]) / (a_src["height"] * (optics(a_src)[3] - optics(a_src)[1]))
            size = min(d["width"] * s, 0.95 * min(W, H))
            acx = (vr[0] + vr[2]) / 2
            acy = (vr[1] + vr[3]) / 2
            dcx = acx + 0.5 * ((d["x"] + d["width"] / 2) - (a_src["x"] + a_src["width"] / 2)) * s
            dcy = acy + 0.5 * ((d["y"] + d["height"] / 2) - (a_src["y"] + a_src["height"] / 2)) * s
        else:
            size = d["width"] * min(W, H) / min(c.sW, c.sH)
            size = min(size, 0.95 * min(W, H))
            dcx = size / 2 if (d["x"] + d["width"] / 2) < c.sW / 2 else W - size / 2
            dcy = size / 2 if (d["y"] + d["height"] / 2) < c.sH / 2 else H - size / 2
        ar = d["height"] / max(1, d["width"])
        w, h = size, size * ar
        o.update(width=round(w, 2), height=round(h, 2),
                 x=round(min(max(0, dcx - w / 2), W - w), 2), y=round(min(max(0, dcy - h / 2), H - h), 2))
        c.placed.add(d["id"])


# =============================================================== driver

def anonymise(task, seed=11):
    t = copy.deepcopy(task)
    rnd = random.Random(seed)
    gmap = {}
    for e in t["source"]["elements"]:
        e["_orig_id"] = e["id"]
        e["id"] = f"n{rnd.randrange(10**6):06d}"
        if e.get("group_id"):
            gmap.setdefault(e["group_id"], f"g{len(gmap)}")
            e["group_id"] = gmap[e["group_id"]]
    return t


def check(design, src):
    W, H = design["canvas"]["width"], design["canvas"]["height"]
    probs = []
    if sorted(e["id"] for e in design["elements"]) != sorted(e["id"] for e in src["elements"]):
        probs.append("id mismatch")
    srcmap = {e["id"]: e for e in src["elements"]}
    for e in design["elements"]:
        if e["x"] < -0.5 or e["y"] < -0.5 or e["x"] + e["width"] > W + 0.5 or e["y"] + e["height"] > H + 0.5:
            probs.append(f"off-canvas {e.get('_orig_id')}")
        if e["type"] == "image" and e.get("fit", "contain") != "cover":
            s = srcmap[e["id"]]
            a0, a1 = s["width"] / s["height"], e["width"] / e["height"]
            if abs(a1 / a0 - 1) > 0.05:
                probs.append(f"aspect {e.get('_orig_id')} {a0:.3f}->{a1:.3f}")
    return probs


if __name__ == "__main__":
    runs = [
        ("level1_warmup", None), ("level2_core", None), ("level3_advanced", None),
        ("level2_core", (728, 90)), ("level3_advanced", (1600, 400)), ("level2_core", (1080, 1920)),
        ("level1_warmup", (1920, 1080)), ("level3_advanced", (1080, 1080)), ("level2_core", (300, 250)),
        ("level3_advanced", (320, 50)), ("level2_core", (1280, 720)),
    ]
    only = sys.argv[1:]
    for name, size in runs:
        task = anonymise(json.load(open(f"input/chameleon_sample_{name}.json")))
        if size:
            task["target_canvas"] = {"width": size[0], "height": size[1]}
        W, H = task["target_canvas"]["width"], task["target_canvas"]["height"]
        tag = f"{name}_{W}x{H}"
        if only and tag not in only:
            continue
        design, arche = compose(task)
        probs = check(design, task["source"])
        clean = {"canvas": design["canvas"],
                 "elements": [{k: v for k, v in e.items() if k != "_orig_id"} for e in design["elements"]]}
        (OUT / f"out_{tag}.json").write_text(json.dumps(clean, indent=1))
        render_design_to_png(clean, ASSETS, str(OUT / f"out_{tag}.png"))
        vis = [e["_orig_id"] for e in design["elements"] if e.get("opacity", 1) > 0]
        print(f"{tag:34s} {arche:6s} visible={vis} problems={probs}")
