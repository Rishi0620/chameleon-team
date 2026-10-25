"""decompile.py — source design -> bracketed galley (owner: OPTIMIZER).

Layers:   background (full-bleed, stretched) | texture (ungrouped decorative shapes)
          | furniture (small corner/rotated groups) | hidden (unresolvable assets)
Stream:   content UNITS in reading order (recursive XY-cut on ink boxes, after INVENTOR's GALLEY),
          with the source program (¶ row / | column / / stack) between neighbours and TeX glue.
Units:    text | image | pill (shape+label, re-fittable button) | chips (row of look-alike pills)
          | rigid (other groups, uniform scale) | bracket (CONTAINER: a shape with riders on it,
          decompiled recursively as a nested galley whose background is the host shape).
Roles + rent (priority) come from features only (never ids). The headline is mandatory (rent=INF).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import textfit as T

INF = 1e9
IMPERATIVE = {"shop", "buy", "get", "learn", "order", "find", "discover", "try", "start", "join", "sign",
              "book", "download", "subscribe", "explore", "see", "view", "claim", "save", "play", "watch",
              "call", "visit", "apply", "register", "donate", "read", "reserve", "grab", "taste", "enjoy"}

# DESIGNER's per-role elasticity: font = f_src * z**gamma  (gamma_up for z>=1, gamma_down for z<1)
GAMMA_UP = {"headline": 1.0, "subhead": 0.75, "body": 0.75, "cta_label": 0.6, "badge_label": 0.6,
            "legal": 0.35, "unknown": 0.75}
GAMMA_DOWN = {"headline": 0.8, "subhead": 0.6, "body": 0.6, "cta_label": 0.5, "badge_label": 0.5,
              "legal": 0.3, "unknown": 0.6}
# legibility floors in JUDGE pixels (px * min(1, 1024/long side)); moderator: CTA label >= 12
# aligned with DESIGNER rules.FLOOR_JUDGE (the stricter of rules/critic)
KEEP_ALL = False                    # set by the engine: never hide an unresolvable asset

FLOOR_JPX = {"headline": 14, "cta_label": 12, "subhead": 11, "body": 11, "badge_label": 9, "legal": 9,
             "unknown": 10}


@dataclass(eq=False)
class Unit:
    kind: str                       # text | image | pill | chips | rigid | bracket
    els: list                       # source elements (bracket: host first, then riders)
    role: str = "unknown"
    rent: float = 0.3
    ink: tuple = (0.0, 0.0, 0.0, 0.0)
    box: tuple = (0.0, 0.0, 0.0, 0.0)
    members: list = field(default_factory=list)   # chips: pill units
    sub: object = None              # bracket: nested Galley
    bleed: tuple = (False, False, False, False)   # bracket: host touched L, T, R, B canvas edges
    corner: str = ""                # furniture corner "TL" ...
    k_pref: int = 1
    gap_src: float = 0.0            # chips: source gap between pills

    @property
    def name(self):
        return "+".join(str(e["id"]) for e in self.els)

    @property
    def head(self):
        return self.els[0]

    def text_el(self):
        if self.kind == "text":
            return self.els[0]
        if self.kind == "pill":
            return next(e for e in self.els if e["type"] == "text")
        if self.kind == "chips":
            return self.members[0].text_el()
        return None

    def shape_el(self):
        return next((e for e in self.els if e["type"] == "shape"), None)


@dataclass
class Galley:
    W0: float
    H0: float
    background: list = field(default_factory=list)
    texture: list = field(default_factory=list)
    furniture: list = field(default_factory=list)
    hidden: list = field(default_factory=list)
    stream: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    src_gaps: list = field(default_factory=list)
    gap_axes: list = field(default_factory=list)
    base_gap: float = 30.0
    rho: float = 0.5
    depth: int = 0
    host: dict | None = None        # for nested galleys: the host shape (= this galley's background)


# ----------------------------------------------------------------------------- helpers
def _alpha(c):
    m = re.match(r"rgba?\(([^)]*)\)", str(c or "").replace(" ", ""))
    if not m:
        return 1.0
    parts = m.group(1).split(",")
    try:
        return float(parts[3]) if len(parts) > 3 else 1.0
    except ValueError:
        return 1.0


def eff_alpha(e):
    a = float(e.get("opacity", 1.0) if e.get("opacity") is not None else 1.0)
    if e["type"] == "shape":
        a *= _alpha(e.get("fill_color"))
    return a


def _saturation(c):
    m = re.match(r"rgba?\(([^)]*)\)", str(c or "").replace(" ", ""))
    if not m:
        return 0.0
    try:
        r, g, b = [float(v) for v in m.group(1).split(",")[:3]]
    except ValueError:
        return 0.0
    return max(r, g, b) - min(r, g, b)


def box_of(e):
    return (float(e["x"]), float(e["y"]), float(e["x"]) + float(e["width"]), float(e["y"]) + float(e["height"]))


def union(rs):
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))


def area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def inter(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def inside_frac(inner, outer):
    return inter(inner, outer) / max(1e-6, area(inner))


def canvas_cover(e, W0, H0):
    x0, y0, x1, y1 = box_of(e)
    return max(0.0, min(x1, W0) - max(x0, 0)) * max(0.0, min(y1, H0) - max(y0, 0)) / (W0 * H0)


def el_ink(e, assets_dir):
    try:
        return T.ink_rect(e, assets_dir)
    except Exception:  # noqa: BLE001
        return box_of(e)


# ----------------------------------------------------------------------------- roles of text (global)
def text_roles(src, assets_dir, group_of):
    """Global text roles by perceived size, so nested galleys agree on which text is the headline."""
    texts = [e for e in src["elements"] if e["type"] == "text" and str(e.get("content", "")).strip()]
    free = [e for e in texts if not _is_label(e, src, group_of)]
    pool = free or texts
    roles = {}
    if not pool:
        return roles
    pmax = max(T.eff_size(e) for e in pool)
    headline = None
    for e in sorted(pool, key=lambda e: (-T.eff_size(e), e["y"], e["x"])):
        headline = e
        break
    roles[headline["id"]] = "headline"
    secondary = []
    for e in pool:
        if e is headline:
            continue
        p = T.eff_size(e) / pmax
        words = str(e.get("content", "")).split()
        W0, H0 = float(src["canvas"]["width"]), float(src["canvas"]["height"])
        jpx = float(e.get("font_size", 12)) * T.judge_scale(W0, H0)
        low = (float(e["y"]) + float(e["height"]) / 2) > 0.8 * H0
        faint = _alpha(e.get("color")) < 0.75 or float(e.get("opacity", 1) or 1) < 0.75
        hl_fs = float(headline.get("font_size", 12))
        # DESIGNER's rule: legal <=> small relative to the headline AND small absolutely AND (low|faint|long)
        if (float(e.get("font_size", 12)) <= 0.45 * hl_fs and jpx <= 16
                and (low or faint or len(str(e.get("content", ""))) > 60)):
            roles[e["id"]] = "legal"
        elif T.is_bold(e) and _saturation(e.get("color")) > 90 and len(words) <= 5:
            roles[e["id"]] = "cta_label"
        elif words and words[0].lower().strip(".,!") in IMPERATIVE and len(words) <= 5 and T.is_bold(e):
            roles[e["id"]] = "cta_label"
        else:
            secondary.append(e)
    secondary.sort(key=lambda e: (-T.eff_size(e), e["y"]))
    for i, e in enumerate(secondary):
        roles[e["id"]] = "subhead" if i == 0 else "body"
    return roles


def _is_label(e, src, group_of):
    gid = e.get("group_id")
    if not gid:
        return False
    return any(o["type"] == "shape" for o in group_of.get(gid, []))


# ----------------------------------------------------------------------------- decompile
def decompile(src, assets_dir, depth=0, role_map=None, host=None):
    W0, H0 = float(src["canvas"]["width"]), float(src["canvas"]["height"])
    els = [e for e in src["elements"]]
    g = Galley(W0, H0, depth=depth, host=host)
    group_of: dict = {}
    for e in els:
        if e.get("group_id"):
            group_of.setdefault(e["group_id"], []).append(e)
    if role_map is None:
        role_map = text_roles(src, assets_dir, group_of)

    # 1. background layers (ungrouped, image/shape, >= 85% of the canvas)
    rest = []
    any_asset = any(T.asset_info(assets_dir, e.get("asset_id")) for e in els if e["type"] == "image")
    for e in sorted(els, key=lambda e: e.get("z_index", 0)):
        if (e["type"] in ("image", "shape") and not e.get("group_id") and canvas_cover(e, W0, H0) >= 0.85
                and not (rest and any(r["type"] != "shape" or eff_alpha(r) > 0.3 for r in rest))):
            if e["type"] == "image" and any_asset and not KEEP_ALL and T.asset_info(assets_dir, e.get("asset_id")) is None:
                g.hidden.append(e)
            else:
                g.background.append(e)
        else:
            rest.append(e)

    # 2. unresolvable assets -> hidden (never show the grey placeholder), unless NO asset resolves
    #    at all (then our assets dir is probably wrong and hiding would wipe the design)
    flow_els = []
    for e in rest:
        if e["type"] == "image" and any_asset and not KEEP_ALL and T.asset_info(assets_dir, e.get("asset_id")) is None:
            g.hidden.append(e)
        elif e["type"] == "text" and not str(e.get("content", "")).strip():
            g.hidden.append(e)      # empty text: nothing to typeset (kept in place, honest box)
        else:
            flow_els.append(e)

    # 3. containers (host/rider): opaque-ish shape (ungrouped) holding >= 1 text + something / >= 2 units
    hosts = []
    taken = set()
    cand = [e for e in flow_els if e["type"] == "shape" and not e.get("group_id") and eff_alpha(e) >= 0.45
            and area(box_of(e)) >= 0.03 * W0 * H0 and e.get("shape_type", "rectangle") != "line"]
    for h in sorted(cand, key=lambda e: -area(box_of(e))):
        if h["id"] in taken:
            continue
        hb = box_of(h)
        riders = [e for e in flow_els if e is not h and e["id"] not in taken
                  and e.get("z_index", 0) >= h.get("z_index", 0) and inside_frac(box_of(e), hb) >= 0.8
                  and area(box_of(e)) < 0.95 * area(hb)]
        gids = {e.get("group_id") for e in riders if e.get("group_id")}
        riders += [e for e in flow_els if e.get("group_id") in gids and e not in riders]
        n_text = sum(1 for e in riders if e["type"] == "text")
        if n_text == 0:
            continue
        if len(riders) == 1 and area(hb) < 0.08 * W0 * H0:
            continue            # a lone label on a small shape is a pseudo-pill (step 4)
        hosts.append((h, riders))
        taken.add(h["id"])
        taken.update(e["id"] for e in riders)

    # 4. pseudo-pills: ungrouped small shape + exactly one text centred on it
    pseudo = {}
    for s in flow_els:
        if s["type"] != "shape" or s.get("group_id") or s["id"] in taken or eff_alpha(s) < 0.45:
            continue
        sb = box_of(s)
        lab = [t for t in flow_els if t["type"] == "text" and not t.get("group_id") and t["id"] not in taken
               and inside_frac(box_of(t), sb) >= 0.6 and t.get("z_index", 0) >= s.get("z_index", 0)]
        if len(lab) == 1 and area(sb) < 0.08 * W0 * H0:
            pseudo[s["id"]] = lab[0]
            taken.update([s["id"], lab[0]["id"]])

    # 5. texture: remaining ungrouped shapes
    units = []
    for h, riders in hosts:
        units.append(_bracket(h, riders, src, assets_dir, depth, role_map, W0, H0))
    for sid, lab in pseudo.items():
        s = next(e for e in flow_els if e["id"] == sid)
        units.append(_unit("pill", [s, lab], assets_dir))
    seen_groups = set()
    for e in flow_els:
        if e["id"] in taken:
            continue
        gid = e.get("group_id")
        if gid:
            if gid in seen_groups:
                continue
            seen_groups.add(gid)
            mem = [m for m in group_of[gid] if m in flow_els and m["id"] not in taken]
            shapes = [m for m in mem if m["type"] == "shape"]
            texts = [m for m in mem if m["type"] == "text"]
            rotated = any(abs(float(m.get("rotation", 0) or 0)) > 0.5 for m in mem)
            if (len(mem) == 2 and len(shapes) == 1 and len(texts) == 1 and not rotated
                    and inside_frac(box_of(texts[0]), box_of(shapes[0])) >= 0.5):
                units.append(_unit("pill", [shapes[0], texts[0]], assets_dir))
            else:
                units.append(_unit("rigid", mem, assets_dir))
            continue
        if e["type"] == "shape":
            g.texture.append(e)
        else:
            units.append(_unit(e["type"], [e], assets_dir))

    # 6. roles + rents
    _assign_roles(units, role_map, assets_dir, W0, H0)

    # 7. chips: >= 2 non-CTA pills on one source row
    pills = sorted([u for u in units if u.kind == "pill" and u.role != "cta"], key=lambda u: u.box[0])
    used = set()
    for u in pills:
        if id(u) in used:
            continue
        cy, hh = (u.box[1] + u.box[3]) / 2, u.box[3] - u.box[1]
        row = [v for v in pills if id(v) not in used and abs((v.box[1] + v.box[3]) / 2 - cy) < 0.5 * hh]
        if len(row) >= 2:
            for v in row:
                used.add(id(v))
                units.remove(v)
            c = _unit("chips", [e for v in row for e in v.els], assets_dir)
            c.members = row
            c.gap_src = sum(row[i + 1].box[0] - row[i].box[2] for i in range(len(row) - 1)) / (len(row) - 1)
            c.role, c.rent = "badges", 0.25
            units.append(c)

    # 8. furniture: small non-text groups hugging a corner off the main axis, or rotated
    if units:
        tot = sum(area(u.ink) for u in units) or 1.0
        axis = sum((u.ink[0] + u.ink[2]) / 2 * area(u.ink) for u in units) / tot
    flow = []
    for u in units:
        x0, y0, x1, y1 = u.ink
        small = area(u.ink) < 0.08 * W0 * H0
        near_l, near_r = x0 < 0.12 * W0, x1 > 0.88 * W0
        near_t, near_b = y0 < 0.12 * H0, y1 > 0.88 * H0
        off_axis = abs((x0 + x1) / 2 - axis) > 0.15 * W0
        rotated = any(abs(float(e.get("rotation", 0) or 0)) > 1 for e in u.els)
        missing = (u.kind == "image" and small and u.role != "logo"
                   and T.asset_info(assets_dir, u.head.get("asset_id")) is None)
        if missing and KEEP_ALL:
            # the visible placeholder of a missing asset is a small corner mark, not a unit of the flow
            u.corner = ("T" if (y0 + y1) / 2 < H0 / 2 else "B") + ("L" if (x0 + x1) / 2 < W0 / 2 else "R")
            u.role, u.rent = "furniture", min(u.rent, 0.2)
            g.furniture.append(u)
            continue
        if (u.kind in ("pill", "rigid", "chips") and u.rent < INF and u.role != "cta" and small
                and ((near_l or near_r) and (near_t or near_b) and (off_axis or rotated) or rotated)):
            u.corner = ("T" if (y0 + y1) / 2 < H0 / 2 else "B") + ("L" if (x0 + x1) / 2 < W0 / 2 else "R")
            u.role, u.rent = "furniture", min(u.rent, 0.2)
            g.furniture.append(u)
        else:
            flow.append(u)

    # 9. reading order: recursive XY-cut over flow ink -> stream + source program
    if flow:
        tree = _xycut(flow, W0, H0)
        stream, labels = _flatten(tree, "row")
    else:
        stream, labels = [], []
    g.stream, g.labels = stream, labels
    for i, u in enumerate(stream):
        u.order = i
    gaps, axes = [], []
    for a, b, l in zip(stream, stream[1:], labels):
        if l == "C":
            gaps.append(max(0.0, b.ink[0] - a.ink[2]))
            axes.append("x")
        else:
            gaps.append(max(0.0, b.ink[1] - a.ink[3]))
            axes.append("y")
    g.src_gaps, g.gap_axes = gaps, axes
    vg = sorted(x for x, ax in zip(gaps, axes) if ax == "y")
    mn = min(W0, H0)
    base = vg[len(vg) // 2] if vg else 0.03 * mn
    g.base_gap = min(max(base, 0.015 * mn), 0.06 * mn)
    if stream:
        m0 = min(max(0.06 * mn, 8), 72)
        fy0 = min(u.ink[1] for u in stream) - m0
        fy1 = H0 - m0 - max(u.ink[3] for u in stream)
        g.rho = min(max(fy0 / max(1e-6, fy0 + fy1), 0.0), 1.0) if fy0 + fy1 > 1 else 0.5
    return g


def _unit(kind, els, assets_dir):
    ink = union([el_ink(e, assets_dir) for e in els])
    box = union([T.rot_aabb(e["x"], e["y"], e["width"], e["height"], float(e.get("rotation", 0) or 0)) for e in els])
    u = Unit(kind=kind, els=els, ink=ink, box=box)
    if kind == "text":
        e = els[0]
        try:
            u.k_pref = max(1, T.n_lines(e, int(e["font_size"]), e["width"]))
        except Exception:  # noqa: BLE001
            u.k_pref = 1
    return u


def _bracket(h, riders, src, assets_dir, depth, role_map, W0, H0):
    hb = box_of(h)
    x0, y0 = max(0.0, hb[0]), max(0.0, hb[1])
    x1, y1 = min(W0, hb[2]), min(H0, hb[3])
    sub = {"canvas": {"width": x1 - x0, "height": y1 - y0},
           "elements": [dict(h, x=0.0, y=0.0, width=x1 - x0, height=y1 - y0)]
           + [dict(e, x=float(e["x"]) - x0, y=float(e["y"]) - y0) for e in riders]}
    sub_g = decompile(sub, assets_dir, depth + 1, role_map, host=h)
    tol = 0.01 * max(W0, H0)
    u = Unit(kind="bracket", els=[h] + riders, ink=hb, box=hb, sub=sub_g,
             bleed=(hb[0] <= tol, hb[1] <= tol, hb[2] >= W0 - tol, hb[3] >= H0 - tol))
    return u


def _assign_roles(units, role_map, assets_dir, W0, H0):
    pills = [u for u in units if u.kind == "pill"]
    cta = None
    if pills:
        def cta_score(u):
            t = u.text_el()
            w = str(t.get("content", "")).split()
            verb = 2.0 if w and w[0].lower().strip(".,!") in IMPERATIVE else 0.0
            caps = 0.0 if str(t.get("content", "")).isupper() else 0.5
            return verb + caps + 3.0 * area(u.box) / (W0 * H0) + 0.5 * (u.box[3] / H0)
        cta = max(pills, key=cta_score)
    for u in units:
        if u.kind == "text":
            r = role_map.get(u.head["id"], "body")
            u.role = r
            e = u.head
            if r == "headline":
                u.rent = INF
            elif r == "legal":
                u.rent = 0.08
            elif r == "cta_label":
                u.rent = 0.85          # a text-only call to action is as important as a CTA button
            else:
                p = T.eff_size(e) / max(1e-6, max((T.eff_size(v.head) for v in units if v.kind == "text"), default=1))
                u.rent = (0.35 + 0.65 * p ** 1.5) if r == "subhead" else 0.3
        elif u.kind == "image":
            w, h = u.ink[2] - u.ink[0], u.ink[3] - u.ink[1]
            a = w * h / (W0 * H0)
            u.role, u.rent = "hero", 0.55 + min(0.15, a)
        elif u.kind == "pill":
            u.role, u.rent = ("cta", 0.85) if u is cta else ("badge", 0.3)
        elif u.kind == "rigid":
            labels = [e for e in u.els if e["type"] == "text"]
            if any(role_map.get(e["id"]) == "headline" for e in labels):
                u.role, u.rent = "headline_group", INF
            else:
                u.role, u.rent = "group", 0.3
        elif u.kind == "bracket":
            r = [v.rent for v in u.sub.stream] or [0.3]
            u.role, u.rent = "panel", max(r)
    # one logo (brand mark) at most: small, wide-or-sparse, near an edge, smallest picture wins ties
    best, best_s = None, 1.5
    for u in units:
        if u.kind != "image":
            continue
        e = u.head
        w, h = u.ink[2] - u.ink[0], u.ink[3] - u.ink[1]
        a = w * h / (W0 * H0)
        if a >= 0.08:
            continue
        info = T.asset_info(assets_dir, e.get("asset_id"))
        sparse = False
        if info is not None and e.get("fit", "contain") == "contain":
            (aw, ah), bb = info
            sparse = (bb[2] - bb[0]) * (bb[3] - bb[1]) < 0.35 * aw * ah
        cy = (u.ink[1] + u.ink[3]) / 2 / H0
        sc = 2.0 * (w / max(h, 1) >= 1.4) + 0.8 * sparse + 1.0 * (cy < 0.2 or cy > 0.8) - 10 * a \
            + 0.6 * (float(e["width"]) / max(1.0, float(e["height"])) >= 2.0)
        if sc > best_s:
            best, best_s = u, sc
    if best is not None:
        best.role, best.rent = "logo", 0.9


# ----------------------------------------------------------------------------- XY-cut (after GALLEY)
def _split(atoms, axis):
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


def _xycut(atoms, W0, H0):
    if len(atoms) == 1:
        return ("leaf", atoms[0])
    gy, gapy = _split(atoms, 1)
    gx, gapx = _split(atoms, 0)
    sy = max(gapy) / H0 if gapy else -1
    sx = max(gapx) / W0 if gapx else -1
    if sy < 0 and sx < 0:
        # overlapping cluster: read top-down by centre (no rigid island: units stay re-typesettable)
        return ("Y", [("leaf", a) for a in sorted(atoms, key=lambda a: ((a.ink[1] + a.ink[3]) / 2, a.ink[0]))])
    if sy >= sx:
        return ("Y", [_xycut(c, W0, H0) for c in gy])
    return ("X", [_xycut(c, W0, H0) for c in gx])


def _flatten(node, level):
    kind = node[0]
    if kind == "leaf":
        return [node[1]], []
    kids = node[1]
    if kind == "Y":
        sep, child = ("R", "row") if level == "row" else ("S", "stk")
    else:
        sep, child = "C", "col"
    units, labels = [], []
    for i, k in enumerate(kids):
        u, l = _flatten(k, child)
        if i:
            labels.append(sep)
        units += u
        labels += l
    return units, labels


SYM = {"S": "/", "C": "|", "R": "¶"}


def program(units, labels):
    if not units:
        return ""
    s = units[0].name.split("+")[0]
    for u, l in zip(units[1:], labels):
        s += f" {SYM[l]} " + u.name.split("+")[0]
    return s


# ----------------------------------------------------------------------------- info
def element_roles(g, out=None):
    """{id: role} for every element of the galley tree (moderator vocabulary)."""
    out = {} if out is None else out
    for e in g.background:
        out[e["id"]] = "background" if g.depth == 0 else "panel"
    if g.host is not None:
        out[g.host["id"]] = "panel"
    for e in g.texture:
        out[e["id"]] = "decoration"
    for e in g.hidden:
        out.setdefault(e["id"], "unknown")
    for u in g.furniture:
        for e in u.els:
            out[e["id"]] = "furniture"
    for u in g.stream:
        _unit_roles(u, out)
    return out


def _unit_roles(u, out):
    if u.kind == "text":
        out[u.head["id"]] = u.role if u.role in ("headline", "subhead", "body", "legal", "cta_label") else "body"
    elif u.kind == "image":
        out[u.head["id"]] = u.role
    elif u.kind in ("pill", "chips"):
        is_cta = u.role == "cta"
        for e in u.els:
            out[e["id"]] = ("cta_" if is_cta else "badge_") + ("shape" if e["type"] == "shape" else "label")
    elif u.kind == "rigid":
        for e in u.els:
            out[e["id"]] = "headline" if u.role == "headline_group" and e["type"] == "text" else "unknown"
    elif u.kind == "bracket":
        element_roles(u.sub, out)
        out[u.els[0]["id"]] = "panel"


def all_units(g):
    """Flat list of (unit, galley) over the whole tree."""
    res = []
    for u in g.stream:
        res.append((u, g))
        if u.kind == "bracket":
            res += all_units(u.sub)
    for u in g.furniture:
        res.append((u, g))
    return res


def containers(g, out=None):
    out = {} if out is None else out
    for u in g.stream:
        if u.kind == "bracket":
            out[u.els[0]["id"]] = [e["id"] for e in u.els[1:]]
            containers(u.sub, out)
    for u in g.stream + g.furniture:
        if u.kind in ("pill", "chips"):
            for p in (u.members or [u]):
                s = p.shape_el()
                t = p.text_el()
                if s is not None and t is not None and not s.get("group_id"):
                    out[s["id"]] = [t["id"]]
    return out
