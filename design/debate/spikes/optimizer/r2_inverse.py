"""Round-2 spike: is inverse optimization from the SOURCE design sound for a linear energy?

Setting. OPTIMIZER's energy is linear in its weights: E_w(L) = w . phi(L), phi = unweighted term
values. If the source S is the designer's argmin at its own canvas, then for every alternative
layout L in the candidate set C(source canvas):      w . (phi(L) - phi(S)) >= 0.
That is inverse linear optimization (Ahuja & Orlin 2001) / a structured-SVM constraint set from ONE
demonstration. The feasible weights form a polyhedral cone K = {w >= 0 : A w >= 0}.

What we compute (pooled over 5 demonstrations: L1, L2, L3 sources + the S-panel and B-card
sub-designs of round-2's new designs, all solved at their own canvas):
  1. consistency: how many alternatives beat the source under the hand weights w0;
  2. the minimal correction w* = argmin ||w - w0||^2 s.t. A w >= 0 (exact projection by Hildreth's
     method = coordinate ascent on the dual), i.e. inverse-LP with an L2-to-prior objective;
  3. per-term identifiability: holding the others at w*, the interval [lb_k, ub_k] of w_k that
     keeps the source optimal (exact, from the constraints);
  4. two energy models: A = round-1 energy (monotone size reward), B = A with a concave size
     utility + a "density" moment term  sum imp*log(scale/z_ref)^2  (deviation from the area-
     reference scale, which equals the source scale at the source canvas);
  5. transfer: solve unseen targets with weights drawn from INSIDE the identified set and check
     whether decisions (drops, type size) change -> what the source can and cannot pin down.
Run: .venv/bin/python design/debate/spikes/optimizer/r2_inverse.py
"""
from __future__ import annotations

import itertools
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import r2_merged as M  # noqa: E402

H = M.H
OPT = M.OPT
OUT = HERE / "r2_out"

BASE = ["drop", "size", "leg", "copy", "lines", "breaks", "widow", "slots", "ratio", "imgord", "fill", "order"]
MODEL_A = BASE
MODEL_B = [k for k in BASE if k != "size"] + ["sizecc", "dens"]
W0 = dict(OPT.W, sizecc=OPT.W["size"], dens=0.5)


# ----------------------------------------------------------------------------- candidates
def features(sol, flow, Wc, Hc, z_ref):
    E, t = OPT.energy(sol, flow, Wc, Hc, z_ref)
    phi = {k: t[k] / OPT.W[k] for k in BASE}
    cc = dens = 0.0
    for imp, s in M.vis_scales(sol):
        r = math.log(max(s, 1e-6) / z_ref)
        cc -= imp * (min(r, 0.0) + 0.2 * max(r, 0.0))
        dens += imp * r * r
    phi["sizecc"], phi["dens"] = cc, dens
    return phi


def candidates(src, Wc, Hc, rho_mult=(0.7, 1.0, 1.4), zrel=(0.6, 0.75, 0.9, 1.0, 1.15, 1.3)):
    """OPTIMIZER's search space, but each structure is also evaluated BELOW its max zoom, so that
    the source itself (z = 1) is a member of the candidate set at the source canvas."""
    OPT.KMAX = 4
    OPT._wk.clear()
    bg, decor, hid, atoms = OPT.build_atoms(src, Wc, Hc)
    flow = [a for a in atoms if a.anchored is None]
    Ws, Hs = src["canvas"]["width"], src["canvas"]["height"]
    z_ref = math.sqrt(Wc * Hc / (Ws * Hs))
    z_cap = max(1.5 * z_ref, 1.0)
    base = 0.03 * min(Ws, Hs)

    def m_fn(z):
        g = max(4.0, base * z)
        return max(g, 0.035 * min(Wc, Hc)), g

    must = [a for a in flow if a.imp >= 0.8]
    optional = sorted([a for a in flow if a.imp < 0.8], key=lambda a: -a.imp)
    subsets = [list(c) for r in range(len(optional) + 1) for c in itertools.combinations(optional, r)]
    aspect = Wc / Hc
    max_slots = 1 if aspect < 0.8 else (2 if aspect < 1.6 else (3 if aspect < 3 else 4))
    out = []
    for sub in subsets:
        vis = sorted(must + sub, key=lambda a: a.order)
        imgs = [a for a in vis if a.kind == "image"]
        for combo in itertools.product(rho_mult, repeat=len(imgs)):
            rhos = {id(a): z_ref * r for a, r in zip(imgs, combo)}
            for k in range(1, min(max_slots, len(vis)) + 1):
                for slots in OPT.partitions(vis, k):
                    zs = OPT.max_zoom(slots, rhos, Wc, Hc, m_fn, z_cap)
                    if zs is None:
                        continue
                    for z in sorted({zs, 0.85 * zs, 0.7 * zs} | {z_ref * g for g in zrel if z_ref * g <= zs}):
                        if not OPT.hierarchy_ok(vis, z):
                            continue
                        m, g = m_fn(z)
                        widths = OPT.row_feasible(slots, z, rhos, Wc, Hc, m, g)
                        if widths is None:
                            continue
                        widths = OPT.widen(slots, widths, z, rhos, Wc, Hc, m, g)
                        dets = []
                        for s, c in zip(slots, widths):
                            r = OPT.slot_at(s, z, rhos, c, Hc - 2 * m, m, g)
                            if r is None:
                                break
                            dets.append((c, r[1]))
                        if len(dets) != len(slots):
                            continue
                        sol = dict(slots=slots, z=z, rhos=rhos, widths=widths, dets=dets, m=m, gap=g)
                        sol["phi"] = features(sol, flow, Wc, Hc, z_ref)
                        sol["key"] = (len(vis) == len(flow), k, round(z / z_ref, 3),
                                      tuple(sorted(round(r, 3) for r in combo)))
                        out.append(sol)
    return out, (bg, decor, hid, atoms, flow, overlays_of(atoms))


def overlays_of(atoms):
    return [a for a in atoms if a.anchored is not None]


def source_candidate(cands, n_imgs):
    key = (True, 1, 1.0, tuple([1.0] * n_imgs))
    hits = [c for c in cands if c["key"] == key]
    return hits[0] if hits else None


# ----------------------------------------------------------------------------- inverse LP
def constraint_rows(cands, src_c, terms):
    ps = np.array([src_c["phi"][k] for k in terms])
    rows = []
    for c in cands:
        d = np.array([c["phi"][k] for k in terms]) - ps
        if np.abs(d).max() > 1e-9:
            rows.append(d)
    return np.array(rows)


def hildreth(A, w0, iters=400):
    """Exact Euclidean projection of w0 onto {w : A w >= 0, w >= 0} (dual coordinate ascent)."""
    A = np.vstack([A, np.eye(A.shape[1])])
    n2 = (A * A).sum(1)
    lam = np.zeros(len(A))
    w = w0.astype(float).copy()
    for _ in range(iters):
        moved = 0.0
        for i in range(len(A)):
            new = max(0.0, lam[i] - (A[i] @ w) / n2[i])
            dl = new - lam[i]
            if dl:
                w += dl * A[i]
                lam[i] = new
                moved = max(moved, abs(dl))
        if moved < 1e-10:
            break
    return w


def intervals(A, w, terms):
    res = {}
    for k in range(len(terms)):
        r = -(A @ w - A[:, k] * w[k])
        dk = A[:, k]
        pos, neg = dk > 1e-12, dk < -1e-12
        lb = max([0.0] + list(r[pos] / dk[pos]))
        ub = min(list(r[neg] / dk[neg])) if neg.any() else math.inf
        res[terms[k]] = (lb, ub, int(pos.sum()), int(neg.sum()), int((~pos & ~neg).sum()))
    return res


# ----------------------------------------------------------------------------- transfer
def solve_with(src, Wc, Hc, w, terms):
    cands, (bg, decor, hid, atoms, flow, ovl) = candidates(src, Wc, Hc)
    best = min(cands, key=lambda c: sum(w[k] * c["phi"][k] for k in terms))
    vis = [a.name.split("+")[0] for s in best["slots"] for a in s]
    hidden = [a.name.split("+")[0] for a in flow if a.name.split("+")[0] not in vis]
    fonts = {a.name.split("+")[0]: d[1] for s, (c, det) in zip(best["slots"], best["dets"]) for a in s
             for d in [det[id(a)]] if d[0] == "t"}
    return best, hidden, fonts, len(best["slots"]), (bg, decor, hid, atoms, flow, ovl)


def demos():
    out = {}
    for k in ("L1", "L2", "L3"):
        out[k] = H.DESIGNS[k]
    for k in ("S", "B"):
        src = H.DESIGNS[k]
        panel, members = M.find_panel(src)
        out[k + "-panel"] = M.sub_design(members, panel["x"], panel["y"], panel["width"], panel["height"], bg=panel)
    return out


def main():
    t0 = time.time()
    lines = []

    def say(s=""):
        print(s, flush=True)
        lines.append(s)

    rows = {"A": [], "B": []}
    say("== 1. Consistency of hand weights at the SOURCE canvas (is the source the argmin?) ==")
    for name, src in demos().items():
        Wc, Hc = src["canvas"]["width"], src["canvas"]["height"]
        cands, info = candidates(src, Wc, Hc)
        n_img = sum(1 for a in info[4] if a.kind == "image")
        sc = source_candidate(cands, n_img)
        if sc is None:
            say(f"{name}: source not representable in the candidate set (skipped)")
            continue
        for model, terms in (("A", MODEL_A), ("B", MODEL_B)):
            A = constraint_rows(cands, sc, terms)
            rows[model].append(A)
            w0 = np.array([W0[k] for k in terms])
            viol = A @ w0 < -1e-9
            rank = 1 + int(viol.sum())
            say(f"{name:8s} model {model}: {len(A):5d} alternatives, source ranks #{rank} under w0"
                + (f"  (best alternative beats it by {-(A @ w0).min():.3f})" if viol.any() else ""))
        best_alt = min(cands, key=lambda c: sum(W0[k] * c["phi"][k] for k in MODEL_A))
        say(f"          model A argmin: z={best_alt['z']:.2f} slots={len(best_alt['slots'])} "
            f"vis={sum(len(s) for s in best_alt['slots'])}/{len(info[4])}  (source: z=1.00, 1 slot, all visible)")
    say(f"   candidate generation: {time.time() - t0:.1f}s")

    say("\n== 2. Minimal correction w* = argmin ||w - w0|| s.t. every source is optimal (pooled) ==")
    wstar = {}
    for model, terms in (("A", MODEL_A), ("B", MODEL_B)):
        A = np.vstack(rows[model])
        w0 = np.array([W0[k] for k in terms])
        w = hildreth(A, w0)
        wstar[model] = dict(zip(terms, w))
        viol = int((A @ w < -1e-6).sum())
        say(f"model {model}: {len(A)} constraints; violations after projection: {viol}")
        say("   term      w0      w*     lb      ub    #alt-worse #alt-better #tie")
        iv = intervals(A, w, terms)
        for k, wk, w0k in zip(terms, w, w0):
            lb, ub, npos, nneg, nzero = iv[k]
            ubs = "inf" if math.isinf(ub) else f"{ub:6.3f}"
            say(f"   {k:8s} {w0k:6.3f} {wk:7.3f} {lb:6.3f} {ubs:>7s} {npos:10d} {nneg:11d} {nzero:5d}")
    say("   (#alt-worse = alternatives worse than the source on that term -> they only give LOWER bounds;"
        " #alt-better -> UPPER bounds; ub=inf means the source cannot say how large this weight is)")

    say("\n== 3. Transfer: weights INSIDE the identified set, solved at unseen targets ==")
    terms = MODEL_B
    base = dict(wstar["B"])
    probes = [("L3", 728, 90), ("L2", 728, 90), ("L2", 1080, 1920), ("S-panel", 300, 250)]
    dm = demos()
    A = np.vstack(rows["B"])
    iv = intervals(A, np.array([base[k] for k in terms]), terms)
    for name, Wc, Hc in probes:
        src = dm[name]
        say(f"{name} -> {Wc}x{Hc}")
        for k in ("drop", "leg", "copy", "dens"):
            lb, ub = iv[k][0], iv[k][1]
            vals = sorted({max(lb, 1e-3), base[k], 4 * max(base[k], lb, 0.05), 16 * max(base[k], lb, 0.05)})
            vals = [v for v in vals if v <= ub + 1e-9]
            res = []
            for v in vals:
                w = dict(base, **{k: v})
                best, hidden, fonts, nslots, _ = solve_with(src, Wc, Hc, w, terms)
                res.append(f"{k}={v:.2f}: hide{hidden} fonts{fonts} slots={nslots}")
            say("   " + "\n   ".join(res))
    (OUT / "inverse_log.txt").write_text("\n".join(lines) + "\n")
    json.dump({m: {k: float(v) for k, v in ws.items()} for m, ws in wstar.items()},
              open(OUT / "inverse_wstar.json", "w"), indent=1)
    say(f"\ntotal {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
