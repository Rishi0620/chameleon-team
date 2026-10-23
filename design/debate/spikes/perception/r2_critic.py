"""Round-2 pixel critic (v2). Everything is measured on rendered pixels and, where possible, relative
to the SOURCE render. Additions vs v1: pixel-true visibility (catches text hidden under the bg),
rotated-corner clipping, glyphs-over-busy-backdrop, palette fidelity, cramped edges, component breakdown."""
import sys, re
from pathlib import Path
import numpy as np, skia
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
from critic import render, lum, x_height, text_lines, FM          # official renderer code path
from renderer.converter.colorutil import parse_rgba
from roles import infer_roles

DROP = {"headline": 20, "logo": 10, "cta_bg": 5, "cta_label": 5, "cta_text": 8, "hero": 4, "subhead": 3,
        "badge_bg": 0.5, "badge_label": 0.5, "sticker": 0.5, "legal": 0.75, "unseen_image": 0, "decoration": 0.3,
        "panel": 1, "other": 1, "background": 30}
_M = {}

def _mask(design, el, pad=0):
    cw, ch = design["canvas"]["width"], design["canvas"]["height"]
    key = (cw, ch, pad, repr(sorted(el.items())))
    if key not in _M:
        e = dict(el, x=el["x"] + pad, y=el["y"] + pad)
        _M[key] = render({"canvas": {"width": cw + 2 * pad, "height": ch + 2 * pad}, "elements": [e]}, transparent=True)[..., 3] > 40
    return _M[key]

def cap_height(el):
    w = "bold" if el.get("font_weight") == "bold" else "regular"
    tf = skia.Typeface.MakeFromData(FM.lookup(el["font_family"], w, w))
    return skia.Font(tf, int(el["font_size"])).getMetrics().fCapHeight

V21 = True   # round-2 calibration fixes (see round2/perception.md section B)

def _edges(gray):
    gy, gx = np.gradient(gray); return np.hypot(gx, gy) > 12

def measure(design, roles):
    """Pixel-true visibility: an element is visible iff removing it from the list changes the render.
    Its backdrop (for contrast/busyness) is the render WITHOUT it - exactly what lies beneath its glyphs."""
    cw, ch = design["canvas"]["width"], design["canvas"]["height"]
    els = design["elements"]
    full = render(design)[..., :3].astype(np.int16)
    f = {"els": {}, "cw": cw, "ch": ch}
    fg = np.zeros((ch, cw), bool)
    for el in els:
        r = roles[el["id"]]
        if r == "background":
            f["els"][el["id"]] = {"visible": True, "mask": np.ones((ch, cw), bool)}; continue
        without = render({"canvas": design["canvas"], "elements": [e for e in els if e["id"] != el["id"]]})[..., :3].astype(np.int16)
        m = _mask(design, el)
        changed = (np.abs(full - without).sum(-1) > 24)
        if m.sum() == 0 or (changed & m).sum() < 0.05 * m.sum():
            f["els"][el["id"]] = {"visible": False}; continue
        if el["type"] == "text":
            R, G, B, A = parse_rgba(el["color"])
            bgL = lum(without[m]); tL = lum(np.array([[R, G, B]], float))[0] * A + bgL * (1 - A)
            cr = (np.maximum(tL, bgL) + .05) / (np.minimum(tL, bgL) + .05)
            k = max(2, round(int(el["font_size"]) * 0.15)); dm = m.copy()
            for dy in (-k, 0, k):
                for dx in (-k, 0, k): dm |= np.roll(np.roll(m, dy, 0), dx, 1)
            ring = dm & ~m; edges = _edges(without.mean(-1))
            lines, lw = text_lines(el)
            bottom = el["y"] + len(lines) * el["font_size"] * el.get("line_height", 1.2)
            f["els"][el["id"]] = dict(visible=True, mask=m, contrast=float(np.percentile(cr, 10)),
                                      xh=x_height(dict(el, font_size=int(el["font_size"]))), cap=cap_height(el), lines=lines,
                                      busy=float(edges[ring].mean()) if ring.any() else 0.0,
                                      cut=max(0.0, bottom - ch), wide=max(0.0, max(lw) - el["width"]) if lw else 0.0)
        else:
            clip = 0.0
            if abs(el.get("rotation", 0)) > 0.5:
                big = _mask(design, el, pad=200); clip = 1 - m.sum() / max(1, big.sum())
            f["els"][el["id"]] = dict(visible=True, mask=m, clip=clip,
                                      placeholder=el["type"] == "image" and r == "unseen_image")
        if r not in ("background", "decoration"):
            fg |= f["els"][el["id"]]["mask"]
    f["coverage"] = float(fg.mean())
    h = np.histogramdd(full.reshape(-1, 3) // 64, bins=(4, 4, 4), range=((0, 4),) * 3)[0].ravel()
    f["palette"] = h / h.sum()
    return f

def structural(design, src):
    """JSON-side checks the official structural scorer will certainly run (pixels can hide these)."""
    cw, ch = design["canvas"]["width"], design["canvas"]["height"]; S = {e["id"]: e for e in src["elements"]}; out = []
    if sorted(S) != sorted(e["id"] for e in design["elements"]): out.append("id mismatch")
    for e in design["elements"]:
        if e["x"] < -0.5 or e["y"] < -0.5 or e["x"] + e["width"] > cw + 0.5 or e["y"] + e["height"] > ch + 0.5:
            out.append(f"{e['id']} off-canvas")
        if e["type"] == "image" and e.get("fit", "contain") != "cover":
            a0 = S[e["id"]]["width"] / S[e["id"]]["height"]; a1 = e["width"] / e["height"]
            if abs(a1 / a0 - 1) > 0.05: out.append(f"{e['id']} aspect {abs(a1/a0-1):.0%} off")
    return out

def score(design, src_design, src_f=None, roles=None, verbose=False):
    roles = roles or infer_roles(src_design)
    src_f = src_f or measure(src_design, roles)
    f = measure(design, roles)
    cw, ch = f["cw"], f["ch"]; short = min(cw, ch)
    st = structural(design, src_design)
    groups = {e["id"]: e.get("group_id") for e in design["elements"]}
    comp = {k: 0.0 for k in ("hard", "legibility", "contrast", "collision", "busy", "hierarchy", "typography",
                             "drops", "faithful_weight", "palette", "headline_size", "edges")}
    notes = list(st); comp["hard"] += 10 * len(st)
    head = next(k for k, v in roles.items() if v == "headline")
    hxh = f["els"][head]["xh"] if f["els"][head].get("visible") else 0
    hcap = f["els"][head]["cap"] if f["els"][head].get("visible") else 0
    for e in design["elements"]:
        i, r, m = e["id"], roles[e["id"]], f["els"][e["id"]]
        if not m.get("visible"):
            comp["drops"] += DROP.get(r, 1) * (0.5 if V21 and DROP.get(r, 1) < 5 else 1.0); continue
        if m.get("placeholder"): comp["hard"] += 15; notes.append(f"placeholder visible: {i}")
        if m.get("clip", 0) > 0.02: comp["hard"] += 6; notes.append(f"{i} clipped {m['clip']:.0%} at canvas edge")
        if e["type"] != "text": continue
        if m["cut"] > 1: comp["hard"] += 10; notes.append(f"{i} runs {m['cut']:.0f}px off canvas")
        if m["wide"] > 1: comp["hard"] += 5; notes.append(f"{i} word wider than box by {m['wide']:.0f}px")
        floor = 7.0 if r in ("headline", "cta_label", "cta_text") else 5.5
        if m["xh"] < floor: comp["legibility"] += 3 * (floor - m["xh"]); notes.append(f"{i} x-height {m['xh']:.1f}px")
        s = src_f["els"].get(i, {}); base = min(4.5, 0.95 * s.get("contrast", 4.5)); base = max(base, 3.0) if s.get("contrast", 9) >= 3 else base
        if m["contrast"] < base: comp["contrast"] += 2 * (base - m["contrast"]); notes.append(f"{i} contrast {m['contrast']:.2f} < {base:.2f}")
        sb = s.get("busy", 0.0)
        if m["busy"] > sb + 0.05: comp["busy"] += 10 * (m["busy"] - sb - 0.05); notes.append(f"{i} glyphs over busy backdrop {m['busy']:.2f}")
        if V21:
            if i != head and r not in ("legal",) and m["cap"] > hcap * 1.10: comp["hierarchy"] += 6; notes.append(f"{i} out-shouts headline")
        elif i != head and r not in ("legal",) and m["xh"] > hxh * 1.02: comp["hierarchy"] += 6; notes.append(f"{i} out-shouts headline")
        if i == head and len(m["lines"]) > 1 and min(len(l.split()) for l in m["lines"]) < 2:
            comp["typography"] += 2; notes.append("headline has a one-word line")
    vis = [e["id"] for e in design["elements"] if f["els"][e["id"]].get("visible") and roles[e["id"]] not in ("background", "decoration")]
    for a in range(len(vis)):
        for b in range(a + 1, len(vis)):
            x, y = vis[a], vis[b]
            if groups[x] and groups[x] == groups[y]: continue
            sx, sy = src_f["els"].get(x, {}), src_f["els"].get(y, {})
            if V21 and sx.get("visible") and sy.get("visible") and (sx["mask"] & sy["mask"]).sum() > 20:
                continue        # SOURCE-RELATIVE collision: layering the designer already had (text on its panel) is intent, not a defect
            inter = (f["els"][x]["mask"] & f["els"][y]["mask"]).sum()
            if inter:
                fr = inter / max(1, min(f["els"][x]["mask"].sum(), f["els"][y]["mask"].sum()))
                if fr > 0.003: comp["collision"] += 20 * fr + 2; notes.append(f"ink collision {x}×{y} {fr:.1%}")
        m = f["els"][vis[a]]["mask"]; ys, xs = np.nonzero(m)
        if len(xs):
            gap = min(xs.min(), ys.min(), cw - 1 - xs.max(), ch - 1 - ys.max())
            if gap < 0.02 * short: comp["edges"] += 1.0; notes.append(f"{vis[a]} ink touches edge ({gap}px)")
    if V21:
        for e in design["elements"]:     # a group's label must stay inside its container shape
            if e["type"] != "text" or not e.get("group_id") or not f["els"][e["id"]].get("visible"): continue
            shp = [x for x in design["elements"] if x.get("group_id") == e["group_id"] and x["type"] == "shape" and f["els"][x["id"]].get("visible")]
            if not shp: continue
            box = f["els"][shp[0]["id"]]["mask"]; tm = f["els"][e["id"]]["mask"]
            out = (tm & ~box).sum() / max(1, tm.sum())
            if out > 0.02: comp["hard"] += 8; notes.append(f"{e['id']} spills out of its shape ({out:.0%} of ink)")
        def content_area(ff, ids):
            ys, xs = [], []
            for k in ids:
                if ff["els"].get(k, {}).get("visible"):
                    yy, xx = np.nonzero(ff["els"][k]["mask"]); ys += [yy.min(), yy.max()] if len(yy) else []; xs += [xx.min(), xx.max()] if len(xx) else []
            return ((max(xs) - min(xs)) * (max(ys) - min(ys)) / (ff["cw"] * ff["ch"])) if xs else 0
        sv = [k for k in src_f["els"] if roles[k] not in ("background", "decoration")]
        r_fill = content_area(f, vis) / max(1e-6, content_area(src_f, sv))
        if r_fill < 0.6: comp["underfill"] = 15 * (0.6 - r_fill); notes.append(f"content block fills {r_fill:.0%} of the source's share")
    share = {k: float(f["els"][k]["mask"].sum()) for k in vis}
    sshare = {k: float(src_f["els"][k]["mask"].sum()) for k in vis if src_f["els"].get(k, {}).get("visible")}
    zs, zo = sum(sshare.values()) or 1, sum(share.values()) or 1
    comp["faithful_weight"] = (0 if V21 else 8) * sum(abs(sshare.get(k, 0) / zs - share[k] / zo) for k in share)
    comp["palette"] = 5 * float(np.abs(f["palette"] - src_f["palette"]).sum())
    comfort = float(np.clip(0.06 * short, 8, 40))
    comp["headline_size"] = -6 * min(1.0, hxh / comfort)
    total = sum(comp.values())
    return total, comp, notes, f
