"""Round-2 prototype of the MERGED formulation's key new construct: containers as nested designs.

Both GALLEY and OPTIMIZER fail on designs where copy lives on an implicit container
(an ungrouped opaque/translucent shape): GALLEY's XY-cut sees an overlapping cluster and keeps it
as a RIGID island (tiny type, crash at 320x50); OPTIMIZER treats the shape as decoration and
re-flows the copy off its backdrop (white-on-cream, text on a busy photo). See r2_h2h.py.

Construct: a PANEL is a shape (alpha >= .5, >= 4% of canvas, not background) that contains >= 2
content elements. The design is cut at the panel boundary (one XY-cut), and each side is a
SUB-DESIGN solved recursively by the same solver:
    panel sub-design = panel shape as its background + its members      (re-typeset, not rigid)
    rest  sub-design = everything on the other side of the cut
The panel is a bracket in the galley: ( logo | headline / subhead | cta )[panel] | product.
Edge-attached panels (touch >= 2 canvas edges) bleed to the target edges as a band/column;
floating panels (cards) are inset by the margin and keep their corner radius.
The outer search is over orientation x split fraction x {keep rest, drop rest}; scores add the
sub-energies, re-reference the size reward to the GLOBAL canvas, and add a type-scale
consistency term |log z_panel - log z_rest| so hierarchy holds across the cut.
Designs without panels fall through to the plain solver unchanged.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import r2_h2h as H  # noqa: E402  (sets OPT/GAL asset dirs, gives the neutral critic)

OPT = H.OPT
W_CONSIST = 1.0
W_ORIENT = 0.3


def eff_alpha(e):
    a = float(e.get("opacity", 1.0))
    c = H.rgba(e.get("fill_color"))
    return a * c[3]


def inside_frac(e, p):
    ix = max(0, min(e["x"] + e["width"], p["x"] + p["width"]) - max(e["x"], p["x"]))
    iy = max(0, min(e["y"] + e["height"], p["y"] + p["height"]) - max(e["y"], p["y"]))
    return ix * iy / max(1e-6, e["width"] * e["height"])


def find_panel(src):
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    best = None
    for p in src["elements"]:
        if p["type"] != "shape" or p.get("group_id"):
            continue
        area = p["width"] * p["height"]
        if area >= 0.85 * Ws * Hs or area < 0.04 * Ws * Hs or eff_alpha(p) < 0.5:
            continue
        mem = [e for e in src["elements"] if e is not p and e.get("z_index", 0) >= p.get("z_index", 0)
               and e["width"] * e["height"] < 0.85 * Ws * Hs and inside_frac(e, p) >= 0.8]
        gids = {e.get("group_id") for e in mem if e.get("group_id")}
        mem += [e for e in src["elements"] if e.get("group_id") in gids and e not in mem]
        if len(mem) >= 2 and any(e["type"] == "text" for e in mem) and (best is None or area > best[0]):
            best = (area, p, mem)
    return None if best is None else (best[1], best[2])


def sub_design(els, x0, y0, w, h, bg=None):
    out = []
    if bg is not None:
        out.append(dict(bg, x=0, y=0, width=w, height=h))
    for e in els:
        out.append(dict(e, x=e["x"] - x0, y=e["y"] - y0))
    return {"canvas": {"width": w, "height": h}, "elements": out}


def vis_scales(best):
    """[(imp, scale)] for the visible flow atoms of an OPTIMIZER solution."""
    res = []
    for s, (c, det) in zip(best["slots"], best["dets"]):
        for a in s:
            d = det[id(a)]
            sc = d[1] / a.fsrc if d[0] == "t" else OPT.rigid_scale(a, best["z"], best["rhos"].get(id(a)))
            res.append((a.imp, sc))
    return res


def score(bests, Wc, Hc, Ws, Hs):
    z_ref = math.sqrt(Wc * Hc / (Ws * Hs))
    E = 0.0
    for b in bests:
        if b is None:
            continue
        E += b["E"] - b["terms"]["size"]
        # concave size utility (stolen from GALLEY): growth past the area-reference scale is worth
        # only 20%, so a roomy canvas keeps content instead of dropping it to inflate type
        E -= OPT.W["size"] * sum(i * (math.log(min(s, z_ref) / z_ref) + 0.2 * math.log(max(s, z_ref) / z_ref))
                                 for i, s in vis_scales(b))
    zs = [b["z"] for b in bests if b is not None]
    if len(zs) == 2:
        E += W_CONSIST * abs(math.log(zs[0] / zs[1]))
    return E


def place(out_sub, dx, dy, into):
    for e in out_sub["elements"]:
        into[e["id"]] = dict(e, x=e["x"] + dx, y=e["y"] + dy)


def solve_merged(src, Wc, Hc):
    found = find_panel(src)
    if found is None:
        out, best, _, _ = OPT.solve(src, Wc, Hc)
        return out, "plain solver (no panel)"
    panel, members = found
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    ids_m = {e["id"] for e in members} | {panel["id"]}
    bg = [e for e in src["elements"] if e["width"] * e["height"] >= 0.85 * Ws * Hs]
    rest = [e for e in src["elements"] if e["id"] not in ids_m and e not in bg]
    px, py, pw, ph = panel["x"], panel["y"], panel["width"], panel["height"]
    tol = 0.01 * max(Ws, Hs)
    edges = sum([px <= tol, py <= tol, px + pw >= Ws - tol, py + ph >= Hs - tol])
    bleed = edges >= 2
    if rest:
        rx0 = min(e["x"] for e in rest); rx1 = max(e["x"] + e["width"] for e in rest)
        ry0 = min(e["y"] for e in rest); ry1 = max(e["y"] + e["height"] for e in rest)
        side = ("left" if rx0 >= px + pw - tol else "right" if rx1 <= px + tol else
                "top" if ry0 >= py + ph - tol else "bottom" if ry1 <= py + tol else None)
    else:
        side = "left"
    if side is None:  # rest overlaps the panel: not a clean cut -> plain solver
        out, best, _, _ = OPT.solve(src, Wc, Hc)
        return out, "plain solver (panel not separable)"
    # source sub-designs
    pdesign = sub_design([e for e in members], px, py, pw, ph, bg=panel)
    if side in ("left", "right"):
        rx, rw = (px + pw, Ws - (px + pw)) if side == "left" else (0, px)
        rdesign = sub_design(rest, rx, 0, rw, Hs)
    else:
        ry, rh = (py + ph, Hs - (py + ph)) if side == "top" else (0, py)
        rdesign = sub_design(rest, 0, ry, Ws, rh)
    first = side in ("left", "top")             # panel comes first in reading order
    m = max(8.0, 0.035 * min(Wc, Hc))
    aspect = Wc / Hc
    orients = (["h"] if aspect >= 1.6 else ["v"] if aspect < 0.8 else ["h", "v"])
    cands = []
    for o in orients:
        for f in (0.33, 0.4, 0.47, 0.55, 0.62, 0.7, 1.0):
            if f == 1.0 or not rest:
                if f != 1.0:
                    continue
            L = Wc if o == "h" else Hc
            pl = f * L
            # panel region (bleeds for edge-attached panels, inset card otherwise)
            if o == "h":
                preg = (0 if first else Wc - pl, 0, pl, Hc)
                rreg = (pl if first else 0, 0, Wc - pl, Hc)
            else:
                preg = (0, 0 if first else Hc - pl, Wc, pl)
                rreg = (0, pl if first else 0, Wc, Hc - pl)
            if not bleed:
                preg = (preg[0] + m, preg[1] + m, preg[2] - (2 * m if f == 1.0 else 1.5 * m), preg[3] - 2 * m) \
                    if o == "h" else (preg[0] + m, preg[1] + m, preg[2] - 2 * m, preg[3] - (2 * m if f == 1.0 else 1.5 * m))
            if min(preg[2], preg[3]) < 20:
                continue
            pout, pbest, _, _ = OPT.solve(pdesign, preg[2], preg[3])
            if pbest.get("fallback"):
                continue
            rout = rbest = None
            if f < 1.0:
                if min(rreg[2], rreg[3]) < 20:
                    continue
                rout, rbest, _, _ = OPT.solve(rdesign, rreg[2], rreg[3])
                if rbest.get("fallback"):
                    continue
            E = score([pbest, rbest], Wc, Hc, Ws, Hs)
            src_o = "h" if side in ("left", "right") else "v"
            E += W_ORIENT * (o != src_o)                      # faithfulness: keep the source's cut axis
            if f == 1.0 and rest:
                ratoms = OPT.build_atoms(rdesign, Wc, Hc)[3]
                E += OPT.W["drop"] * sum(a.imp for a in ratoms)
            cands.append((E, o, f, preg, rreg, pout, rout))
    if not cands:
        out, best, _, _ = OPT.solve(src, Wc, Hc)
        return out, "plain solver (no panel candidate)"
    cands.sort(key=lambda c: c[0])
    E, o, f, preg, rreg, pout, rout = cands[0]
    out = {}
    for e in bg:
        out[e["id"]] = dict(e, x=0, y=0, width=Wc, height=Hc)
    place(pout, preg[0], preg[1], out)
    if rout is not None:
        place(rout, rreg[0], rreg[1], out)
    hidden_src = {"canvas": src["canvas"], "elements": [e for e in src["elements"] if e["id"] not in out]}
    for e in hidden_src["elements"]:
        out[e["id"]] = OPT.hide(e, src, Wc, Hc)
    for e in out.values():
        OPT.clamp(e, Wc, Hc)
    desc = f"panel[{'bleed' if bleed else 'card'}] {o} f={f:.2f} E={E:.2f}" + ("" if rout is not None else " (rest dropped)")
    return {"canvas": {"width": Wc, "height": Hc}, "elements": [out[e["id"]] for e in src["elements"]]}, desc


def main():
    OPT.Z_CAP_MULT = 1.0   # GALLEY's s_cap: needed for the fixed point (see r2_inverse / r2_fixedpoint)
    designs = {k: H.DESIGNS[k] for k in ("S", "B", "L2", "U")}
    table, rows_by = [], {}
    for name, src in designs.items():
        lum, edges = H.underlay(src, f"{name}_src")
        sstats = H.text_stats(src, lum, edges)
        rows = []
        for Wc, Hc in H.SIZES:
            t = time.time()
            out, desc = solve_merged(src, Wc, Hc)
            dt = time.time() - t
            png = H.OUT / f"{name}_{Wc}x{Hc}_MRG.png"
            (H.OUT / f"{name}_{Wc}x{Hc}_MRG.json").write_text(json.dumps(out, indent=1))
            H.render_design_to_png(out, str(H.KIT), str(png))
            c = H.critique(out, src, sstats, f"{name}_{Wc}x{Hc}_MRG")
            table.append(dict(design=name, size=f"{Wc}x{Hc}", engine="MRG", t=round(dt, 2), **c))
            print(f"{name} {Wc}x{Hc} MRG {dt:5.2f}s {c} | {desc}", flush=True)
            rows.append((f"{name} {Wc}x{Hc}", H.OUT / f"{name}_{Wc}x{Hc}_GAL.png", png))
        rows_by[name] = rows
        H.sheet(rows, H.OUT / f"merged_{name}.png", labels=("GALLEY (inventor)", "MERGED prototype (panels as nested designs)"))
    old = json.loads((H.OUT / "h2h_table.json").read_text())
    allt = [t for t in old if t["design"] in designs] + table
    lines = H.summarize(allt).splitlines()
    summ = "\n".join(lines[:1] + [l for l in lines[1:] if " 0     0 " not in l[:14]])
    print(summ)
    (H.OUT / "merged_log.txt").write_text(summ + "\n")
    for p in H.OUT.glob("_under_*.png"):
        p.unlink()


if __name__ == "__main__":
    main()
