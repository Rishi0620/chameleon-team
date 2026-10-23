"""Round-2 spike: GROUND BINDING — every piece of text/logo knows what it stands on.

Claim under test: the catastrophic failures of the R1 engine on unseen designs (text over busy
photo, dark text that lost its colour block) are all one missing concept: the *ground* of a text.
  * panel   = an opaque-ish (alpha>=.5) non-background shape covering >=6% of the canvas that holds
              the centre of >=1 content element above it in z (colour block, footer bar, card).
  * riders  = the content elements standing on that panel in the source.
  * rule G1 : riders keep their ground. After layout the panel is re-cut to the union of its riders'
              ink (+pad), extended to the canvas edges it touched in the source along the free axis.
  * rule G2 : a text whose source ground is the background must land on a CALM, CONTRASTING patch of
              the *target crop* (cover = centre crop, emulated exactly). If not, it is moved onto a panel
              whose fill contrasts with it ('scrim reuse'); if no panel contrasts, (gated) palette swap
              to the in-design colour with the best contrast; else it is flagged.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
from PIL import Image

# ------------------------------------------------------------------ colour / contrast

def rgba(s):
    m = re.match(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+))?", s or "")
    if not m:
        return (0, 0, 0, 1.0)
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4) or 1))


def rel_lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = rel_lum(a), rel_lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

# ------------------------------------------------------------------ background crop emulation

_IMG = {}


def bg_crop(assets, el, W, H):
    """Exactly what the renderer shows for a full-canvas cover/fill image: returns HxWx3 float."""
    key = (el.get("asset_id"), W, H, el.get("fit"))
    if key in _IMG:
        return _IMG[key]
    p = Path(assets) / el.get("asset_id", "")
    if not p.is_file():
        return None
    im = Image.open(p).convert("RGB")
    if el.get("fit", "contain") == "cover":
        s = max(W / im.width, H / im.height)
        nw, nh = max(1, round(im.width * s)), max(1, round(im.height * s))
        im = im.resize((nw, nh), Image.BILINEAR)
        l, t = (nw - W) // 2, (nh - H) // 2
        im = im.crop((l, t, l + W, t + H))
    else:
        im = im.resize((W, H), Image.BILINEAR)
    arr = np.asarray(im).astype(float)
    _IMG[key] = arr
    return arr


def patch_stats(arr, rect):
    x0, y0, x1, y1 = [int(round(v)) for v in rect]
    H, W = arr.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0.0, (0, 0, 0)
    p = arr[y0:y1, x0:x1]
    lum = p.mean(axis=2)
    gx = np.abs(np.diff(lum, axis=1)).mean()
    gy = np.abs(np.diff(lum, axis=0)).mean()
    busy = (gx + gy) / 2 + 0.25 * lum.std()          # edge energy + texture, in grey levels
    return float(busy), tuple(p.reshape(-1, 3).mean(axis=0))

# ------------------------------------------------------------------ role extension


def find_panels(design, roles):
    W, H = design["canvas"]["width"], design["canvas"]["height"]
    els = design["elements"]
    content = [e for e in els if roles.get(e["id"]) not in ("background", "decoration", "broken")
               and e["type"] in ("text", "image") or roles.get(e["id"], "").endswith("_bg")]
    panels = {}
    for s in els:
        if s["type"] != "shape" or roles.get(s["id"]) == "background":
            continue
        a = rgba(s.get("fill_color"))[3] * float(s.get("opacity", 1))
        if a < 0.5 or s["width"] * s["height"] < 0.06 * W * H or roles.get(s["id"], "").endswith("_bg"):
            continue
        riders = []
        for e in content:
            if e is s or e.get("z_index", 0) < s.get("z_index", 0):
                continue
            cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
            if s["x"] <= cx <= s["x"] + s["width"] and s["y"] <= cy <= s["y"] + s["height"]:
                riders.append(e["id"])
        if riders:
            touched = {"left": s["x"] <= 1, "top": s["y"] <= 1,
                       "right": s["x"] + s["width"] >= W - 1, "bottom": s["y"] + s["height"] >= H - 1}
            panels[s["id"]] = {"riders": riders, "touched": touched, "fill": rgba(s["fill_color"])}
    return panels

# ------------------------------------------------------------------ post-layout pass


def text_ink_rect(C, el):
    b = C.text_block(el, el["font_size"], el["width"])
    asc, cap, desc = C.metrics(el)
    top = el["y"] + b["top_off"]
    align = el.get("text_align", "left")
    w = b["widest"]
    x0 = {"left": el["x"], "center": el["x"] + (el["width"] - w) / 2, "right": el["x"] + el["width"] - w}[align]
    return (x0, top, x0 + w, top + b["opt_h"] + 0.25 * el["font_size"])


def visible_rect(C, el):
    if el["type"] == "text":
        return text_ink_rect(C, el)
    if el["type"] == "image":
        fr = C.optics(el)
        return (el["x"] + fr[0] * el["width"], el["y"] + fr[1] * el["height"],
                el["x"] + fr[2] * el["width"], el["y"] + fr[3] * el["height"])
    return (el["x"], el["y"], el["x"] + el["width"], el["y"] + el["height"])


def union(rects):
    return (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))


def apply_grounds(C, c, arche, allow_recolor=True, log=None):
    """Mutates c.out in place (spike). Returns list of human-readable decisions."""
    log = log if log is not None else []
    W, H, out = c.W, c.H, c.out
    panels = getattr(c, "panels", {})
    bg = next((e for e in c.src["elements"] if c.roles[e["id"]] == "background"), None)
    crop_t = bg_crop(C.ASSETS, out[bg["id"]], W, H) if bg is not None and bg["type"] == "image" else None
    crop_s = bg_crop(C.ASSETS, bg, c.sW, c.sH) if bg is not None and bg["type"] == "image" else None
    bg_rgb = rgba(bg.get("fill_color"))[:3] if bg is not None and bg["type"] == "shape" else None
    m = max(8, round(0.06 * min(W, H)))
    extra = {pid: [] for pid in panels}

    # G2: free text (ground = background) must sit on calm, contrasting pixels of the TARGET crop
    rider_ids = {r for p in panels.values() for r in p["riders"]}
    for e in c.src["elements"]:
        o = out[e["id"]]
        if e["type"] != "text" or e["id"] in rider_ids or o.get("opacity", 1) == 0 or crop_t is None:
            continue
        if c.roles[e["id"]].endswith("_label"):
            continue
        r_t = text_ink_rect(C, o)
        busy_t, mean_t = patch_stats(crop_t, r_t)
        busy_s, mean_s = patch_stats(crop_s, text_ink_rect(C, e))
        col = rgba(o["color"])
        con_t, con_s = contrast(col, mean_t), contrast(col, mean_s)
        ok = busy_t <= max(6.0, 1.5 * busy_s) and con_t >= min(4.5, 0.9 * con_s)
        log.append(f"{e['id']}: busy {busy_s:.1f}->{busy_t:.1f}, contrast {con_s:.1f}->{con_t:.1f} {'OK' if ok else 'FAIL'}")
        if ok:
            continue
        # 1st resort: slide the text (with its free-text siblings) vertically into the calmest band that
        # holds it on its own ground, without touching other content (designers move type, not grounds)
        moved = relocate_calm(C, c, e["id"], crop_t, col, con_s, busy_s, log)
        if moved:
            continue
        # scrim reuse: the panel whose fill contrasts best with this text
        best = max(panels.items(), key=lambda kv: contrast(col, kv[1]["fill"]), default=None)
        if best and contrast(col, best[1]["fill"]) >= 4.5:
            extra[best[0]].append(e["id"])
            log.append(f"   -> moved onto panel {best[0]} (contrast {contrast(col, best[1]['fill']):.1f})")
        elif best and allow_recolor:
            palette = {tuple(rgba(x.get('color'))[:3]) for x in c.src["elements"] if x["type"] == "text"}
            pick = max(palette, key=lambda p: contrast(p, best[1]["fill"]))
            if contrast(pick, best[1]["fill"]) >= 4.5:
                o["color"] = f"rgba({int(pick[0])},{int(pick[1])},{int(pick[2])},{col[3]})"
                extra[best[0]].append(e["id"])
                log.append(f"   -> palette swap to in-design colour {pick} on panel {best[0]} (GATED)")
        else:
            log.append("   -> NO calm/contrasting ground available: flag")

    # G1: re-cut every panel around its (visible) riders + adopted texts
    for pid, p in panels.items():
        ids = [i for i in p["riders"] + extra[pid] if out[i].get("opacity", 1) > 0
               and not (out[i]["type"] == "text" and rgba(out[i]["color"])[3] == 0)]
        if not ids:
            continue
        U = union([visible_rect(C, out[i]) for i in ids])
        pad = 0.8 * m
        x0, y0, x1, y1 = U[0] - pad, U[1] - pad, U[2] + pad, U[3] + pad
        t = p["touched"]
        if arche == "strip" or arche == "split":
            y0, y1 = 0, H                                    # columns are full-height grounds
            if t["left"] and x0 < 0.5 * W:
                x0 = 0
            if t["right"] and x1 > 0.5 * W:
                x1 = W
        else:
            x0, x1 = 0, W                                    # stacks: full-width bands
            if t["top"] and y0 < 0.5 * H:
                y0 = 0
            if t["bottom"] and y1 > 0.5 * H:
                y1 = H
        # a ground never slides under content that does not stand on it (e.g. the hero): cut it back
        others = [e for e in c.src["elements"] if e["id"] not in ids and e["id"] != pid
                  and c.roles[e["id"]] in ("hero", "logo", "secondary_image") and out[e["id"]].get("opacity", 1) > 0]
        gap = 0.5 * m
        for e in others:
            r = visible_rect(C, out[e["id"]])
            if r[2] <= x0 or r[0] >= x1 or r[3] <= y0 or r[1] >= y1:
                continue
            if arche in ("strip", "split"):
                if (r[0] + r[2]) / 2 > (U[0] + U[2]) / 2:
                    x1 = min(x1, r[0] - gap)
                else:
                    x0 = max(x0, r[2] + gap)
            else:
                if (r[1] + r[3]) / 2 > (U[1] + U[3]) / 2:
                    y1 = min(y1, r[1] - gap)
                else:
                    y0 = max(y0, r[3] + gap)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        o = out[pid]
        src = next(e for e in c.src["elements"] if e["id"] == pid)
        o.update(x=round(x0, 2), y=round(y0, 2), width=round(x1 - x0, 2), height=round(y1 - y0, 2))
        o["opacity"] = src.get("opacity", 1)
        c.placed.add(pid)
        log.append(f"panel {pid} re-cut to ({x0:.0f},{y0:.0f},{x1 - x0:.0f}x{y1 - y0:.0f}) around {ids}")
    return log


def relocate_calm(C, c, eid, crop, col, con_s, busy_s, log):
    W, H, out = c.W, c.H, c.out
    free = [e["id"] for e in c.src["elements"] if e["type"] == "text" and c.roles[e["id"]] in
            ("headline", "subhead", "body") and out[e["id"]].get("opacity", 1) > 0]
    if eid not in free:
        return False
    rects = {i: text_ink_rect(C, out[i]) for i in free}
    U = union(list(rects.values()))
    others = [visible_rect(C, out[o["id"]]) for o in c.src["elements"]
              if o["id"] not in free and o["id"] in c.placed and c.roles[o["id"]] not in ("background", "decoration", "panel")
              and out[o["id"]].get("opacity", 1) > 0]
    m = max(8, round(0.05 * min(W, H)))
    best = None
    for y in range(int(m), int(H - (U[3] - U[1]) - m) + 1, 4):
        dy = y - U[1]
        ok = True
        for i, r in rects.items():
            rr = (r[0], r[1] + dy, r[2], r[3] + dy)
            b, mean = patch_stats(crop, rr)
            if b > max(6.0, 1.5 * busy_s) or contrast(col, mean) < min(4.5, 0.9 * con_s):
                ok = False
                break
            if any(not (rr[2] <= o[0] or rr[0] >= o[2] or rr[3] <= o[1] or rr[1] >= o[3]) for o in others):
                ok = False
                break
        if ok and (best is None or abs(dy) < abs(best)):
            best = dy
    if best is None:
        return False
    for i in free:
        out[i]["y"] = round(out[i]["y"] + best, 2)
    log.append(f"   -> relocated free text group by dy={best:.0f} into a calm band (kept its own ground)")
    return True
