"""hierarchy.py: type-order repair on a finished layout (owner: OPTIMIZER).

Legibility floors, per-role elasticity and the corner stickers can leave a smaller source text bigger than a larger
one (a 12 px CTA under a 9 px headline, a 2 px sticker label under 5 px badges). A designer keeps the source's order
of importance: when two texts differ by >= 1.2x in the source, the larger one is never drawn smaller than the other.

Repair, per violating pair (a larger in the source, b smaller, font_a < font_b):
  * a is a sticker (corner furniture): grow the whole sticker about its centre to b's size, if it stays on the canvas
    and clear of other ink; otherwise lower b;
  * else lower b to font_a (a tie is fine). Lowering only shrinks what is already set, so it can never overflow.
A label on a pill shrinks its pill about the centre with it. Nothing is hidden, moved off-canvas or restyled.
"""
from __future__ import annotations

import copy

from . import textfit as T

RATIO = 1.2
MIN_KEEP = 0.6                    # a text is lowered to match a larger one only if that keeps >= 60% of its size
MAX_SWEEPS = 6


def _visible(e):
    from . import contract as C
    return C.visible(e)


def _ink(e, assets_dir):
    return T.ink_rect(e, assets_dir)


def _overlap(a, b, pad=0.0):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def repair(source, out, info, assets_dir):
    """Returns a new output dict (the input is never mutated); the input itself when nothing needs fixing."""
    src = {e["id"]: e for e in source["elements"]}
    cur = copy.deepcopy(out)
    by = {e["id"]: e for e in cur["elements"]}
    roles = (info or {}).get("roles") or {}
    host_of = {}
    for h, rs in ((info or {}).get("containers") or {}).items():
        hs = by.get(h)
        if hs is not None and hs["type"] == "shape" and roles.get(h) in ("cta_shape", "badge_shape") and len(rs) == 1:
            host_of[rs[0]] = h
    groups = {}
    for e in cur["elements"]:
        if e.get("group_id") and roles.get(e["id"]) == "furniture":
            groups.setdefault(e["group_id"], []).append(e)
    furn_of = {e["id"]: g for g, mem in groups.items() for e in mem if e["type"] == "text"}
    W, H = cur["canvas"]["width"], cur["canvas"]["height"]
    changed = False
    for _ in range(MAX_SWEEPS):
        texts = [e for e in cur["elements"] if e["type"] == "text" and str(e.get("content", "")).strip()
                 and e["id"] in src and _visible(e)]
        fixed = False
        for a in sorted(texts, key=lambda e: -float(src[e["id"]]["font_size"])):
            sa = float(src[a["id"]]["font_size"])
            for b in texts:
                sb = float(src[b["id"]]["font_size"])
                fa, fb = int(a["font_size"]), int(b["font_size"])
                if a is b or sa < RATIO * sb or fa >= fb:
                    continue
                if a["id"] in furn_of:                       # a sticker: grow it as far as it stays clear
                    for f_to in sorted({fb, int(fa + 0.75 * (fb - fa)), int(fa + 0.5 * (fb - fa))}, reverse=True):
                        if f_to > fa and _grow_sticker(cur, groups[furn_of[a["id"]]], a, f_to, W, H, assets_dir):
                            fixed = changed = True
                            break
                    fa = int(a["font_size"])
                if fa < fb and fa >= MIN_KEEP * fb:          # a modest step down; never crush text to match a sliver
                    _lower(cur, by, host_of, b, fa)
                    fixed = changed = True
        if not fixed:
            break
    return cur if changed else out


def _lower(cur, by, host_of, e, f):
    f = max(1, int(f))
    host = by.get(host_of.get(e["id"]))
    if host is not None:
        k = f / float(e["font_size"])
        cx, cy = host["x"] + host["width"] / 2, host["y"] + host["height"] / 2
        w, h = max(1.0, host["width"] * k), max(1.0, host["height"] * k)
        host.update(x=round(cx - w / 2, 2), y=round(cy - h / 2, 2), width=round(w, 2), height=round(h, 2))
        if host.get("corner_radius"):
            host["corner_radius"] = round(float(host["corner_radius"]) * k, 2)
        e["font_size"] = f
        asc, desc, cap, _ = T.metrics(e, f)
        lh = T.text_h(e, f, 1)
        e.update(x=host["x"], width=host["width"], height=round(lh, 2), y=round(cy - asc + cap / 2, 2))
        return
    n = T.n_lines(e, f, e["width"])
    h = T.text_h(e, f, n)
    dy = (e["height"] - h) / 2
    e["font_size"] = f
    e["y"] = round(e["y"] + max(0.0, dy), 2)
    e["height"] = round(max(1.0, h), 2)


def _grow_sticker(cur, members, label, f_to, W, H, assets_dir):
    """Scale a sticker group about its own centre so its label reaches f_to; False if it would not stay clear."""
    k = f_to / float(label["font_size"])
    if k <= 1.0:
        return False
    boxes = [(m["x"], m["y"], m["x"] + m["width"], m["y"] + m["height"]) for m in members]
    cx = (min(b[0] for b in boxes) + max(b[2] for b in boxes)) / 2
    cy = (min(b[1] for b in boxes) + max(b[3] for b in boxes)) / 2
    trial = copy.deepcopy(members)
    for m in trial:
        mx, my = m["x"] + m["width"] / 2, m["y"] + m["height"] / 2
        nx, ny = cx + (mx - cx) * k, cy + (my - cy) * k
        m["width"], m["height"] = m["width"] * k, m["height"] * k
        m["x"], m["y"] = nx - m["width"] / 2, ny - m["height"] / 2
        if m["type"] == "text":
            m["font_size"] = int(f_to)
        if m.get("corner_radius"):
            m["corner_radius"] = float(m["corner_radius"]) * k
    # the sticker must stay on the canvas (rotated corners included) and off every other visible element's ink
    rects = [T.rot_aabb(m["x"], m["y"], m["width"], m["height"], float(m.get("rotation", 0) or 0)) for m in trial]
    r = (min(q[0] for q in rects), min(q[1] for q in rects), max(q[2] for q in rects), max(q[3] for q in rects))
    if r[0] < 0 or r[1] < 0 or r[2] > W or r[3] > H:
        # slide it back inside before giving up
        dx = (-r[0] if r[0] < 0 else 0.0) + (W - r[2] if r[2] > W else 0.0)
        dy = (-r[1] if r[1] < 0 else 0.0) + (H - r[3] if r[3] > H else 0.0)
        if r[2] - r[0] > W or r[3] - r[1] > H:
            return False
        for m in trial:
            m["x"] += dx
            m["y"] += dy
        r = (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)
    ids = {m["id"] for m in members}
    for o in cur["elements"]:
        if o["id"] in ids or not _visible(o) or o["type"] == "image" and o["width"] * o["height"] >= 0.8 * W * H:
            continue
        if o["type"] == "shape" and o["width"] * o["height"] >= 0.8 * W * H:
            continue
        try:
            oi = _ink(o, assets_dir)
        except Exception:  # noqa: BLE001
            oi = (o["x"], o["y"], o["x"] + o["width"], o["y"] + o["height"])
        if _overlap(r, oi, 0.5):
            return False
    for m, t in zip(members, trial):
        m.update(x=round(t["x"], 2), y=round(t["y"], 2), width=round(t["width"], 2), height=round(t["height"], 2))
        if m["type"] == "text":
            m["font_size"] = int(f_to)
        if t.get("corner_radius"):
            m["corner_radius"] = round(t["corner_radius"], 2)
    return True
