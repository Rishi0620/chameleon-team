"""R2 spike: "the SOURCE is a solved instance of the designer's objective".

GALLEY's objective is rewritten as a linear model  J_w(c) = w . phi(c)  over a candidate c =
(stream order, kept set, break pattern, type scale s).  Per design, at the SOURCE canvas, we
enumerate GALLEY's own alternatives (every break pattern x omission prefix x scale variant)
and solve a max-margin INVERSE problem:

    min_w  1/2 sum_i d_i (w_i - w0_i)^2  +  C/N sum_a max(0, Delta(src,a) - w.(phi_src - phi_a)),  w >= 0

i.e. move the prior weights as little as possible so that the designer's own layout beats
every layout GALLEY could have produced instead (revealed preference).  The calibrated w is
then used at the target canvas.

Experiments
  E1  fragile prior: round-1 weights with the canvas-fill bonus at 0.25 (the setting that broke
      the L2 fixed point and dropped L1's CTA in round 1).  Does calibration repair it?
  E2  source-relative prior: replace absolute fill/caps by density measured RELATIVE to the
      source (ink coverage / source ink coverage).  Does it fix GALLEY's underfilled tall
      targets (unseen story 1080x1920, skyscraper 160x600)?  What does calibration learn?

Run from repo root:  .venv/bin/python design/debate/spikes/inventor/r2_taste.py
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
import galley as G  # noqa: E402
from unseen import design as UNSEEN  # noqa: E402

ROOT = HERE.parents[3]
OUT = HERE / "out_r2"
OUT.mkdir(exist_ok=True)

FEATS = ["logs", "over_r1", "fill", "dens", "trans", "restack", "tsplit", "imgstack", "clutter", "perm",
         "k_mark", "k_picture", "k_secondary", "k_accent", "k_button", "k_chip", "k_fine", "k_cluster"]
IDX = {f: i for i, f in enumerate(FEATS)}
CLASS_OF = {"mark": "k_mark", "picture": "k_picture", "secondary-text": "k_secondary",
            "accent-text": "k_accent", "button": "k_button", "chip-row": "k_chip",
            "fine-print": "k_fine", "cluster": "k_cluster"}

# round-1 GALLEY weights expressed in this feature basis
W_R1 = dict(logs=1.0, over_r1=5.0, fill=0.06, dens=0.0, trans=0.05, restack=0.0, tsplit=0.15, imgstack=0.05,
            clutter=0.2, perm=0.03, k_mark=0.8, k_picture=1.0, k_secondary=0.2, k_accent=0.6,
            k_button=1.0, k_chip=0.06, k_fine=0.03, k_cluster=0.3)
W_BAD = dict(W_R1, fill=0.25)                                   # E1 prior
W_V2 = dict(W_R1, over_r1=0.0, fill=0.0, dens=1.5)              # E2 prior (source-relative)
SCALE_VARIANTS = (1.0, 0.93, 0.86, 0.8, 0.7, 0.6)


def vec(d):
    return np.array([d[f] for f in FEATS], dtype=float)


def rent_class(u):
    h = u.role_hint
    for k, v in CLASS_OF.items():
        if h.startswith(k):
            return v
    return None


def ink_coverage(rows, s, ctx):
    f = G.fit(rows, s, ctx)
    if not f:
        return None, None
    area = 0.0
    for row_w, row_h, cols, gap_c, ovl in f[0]:
        for cw, ch, items, gaps in cols:
            for u, w, h, tw in items:
                area += w * h
    block = max(r[0] for r in f[0]) * f[2]
    return area / (ctx.Wl * ctx.Hl), block / (ctx.Wl * ctx.Hl)


def phi(g, ctx, kept, labels, s, perm, cov_src, s_cap_r1):
    rows = G.build(kept, labels)
    cov, fill = ink_coverage(rows, s, ctx)
    if cov is None:
        return None
    d = dict.fromkeys(FEATS, 0.0)
    d["logs"] = math.log(s)
    comf = 0.85 * s_cap_r1
    d["over_r1"] = -max(0.0, math.log(s / s_cap_r1))           # round-1 hard cap, softened
    d["fill"] = min(fill, 0.9)
    d["dens"] = -abs(math.log(max(cov, 1e-6) / cov_src))
    src = {(id(a), id(b)): l for a, b, l in zip(g.stream, g.stream[1:], g.src_labels)}
    for a, b, l in zip(kept, kept[1:], labels):
        sl = src.get((id(a), id(b)))
        if sl is not None and (sl == "C") != (l == "C"):
            d["trans"] -= 1
        elif sl is not None and sl != l:
            d["restack"] -= 1                                       # stack-in-column <-> separate rows
        if l == "C" and sl != "C" and a.kind == "text" and b.kind == "text":
            d["tsplit"] -= 1
        if l == "S" and a.kind == "image" and b.kind == "image":
            d["imgstack"] -= 1
    for r in rows:
        d["clutter"] -= max(0, len(r) - 5)
    d["perm"] = -perm
    for u in kept:
        c = rent_class(u)
        if c == "k_picture":
            d[c] += 0.12 + (u.ink[2] - u.ink[0]) * (u.ink[3] - u.ink[1]) / (g.W0 * g.H0)
        elif c:
            d[c] += 1
    # round-1 utility had log(min(s, comf)) + 0.2 log+(s/comf): fold the knee into over_r1? keep simple:
    d["logs"] = math.log(min(s, comf)) + 0.2 * max(0.0, math.log(s / comf)) if ctx.r1_utility else math.log(s)
    return vec(d), cov


def candidates(g, W, H, s_hi_mult=2.0, r1_utility=False):
    """Every GALLEY candidate at canvas W x H, with scale variants; yields (phi, meta)."""
    ctx = G.Ctx(g, W, H)
    s_cap_r1 = ctx.s_cap
    ctx.s_cap = s_hi_mult * s_cap_r1            # lift the cap: let the objective decide the size
    ctx.r1_utility = r1_utility
    src_rows = G.build(g.stream, g.src_labels)
    sctx = G.Ctx(g, g.W0, g.H0)
    sctx.r1_utility = r1_utility
    cov_src, _ = ink_coverage(src_rows, 1.0, sctx)
    streams = [(g.stream, 0)]
    for u in g.stream[1:]:
        if u.role_hint.startswith("mark"):
            streams.append(([u] + [v for v in g.stream if v is not u], 1))
    out = []
    for stream, perm in streams:
        optional = sorted([u for u in stream if u.rent != G.INF], key=lambda u: u.rent)
        for k in range(len(optional) + 1):
            dropped = set(id(u) for u in optional[:k])
            kept = [u for u in stream if id(u) not in dropped]
            for labels in itertools.product("SCR", repeat=len(kept) - 1):
                if not G.canonical(kept, labels):
                    continue
                rows = G.build(kept, labels)
                smax = G.max_scale(rows, ctx)
                if smax is None:
                    continue
                svals = sorted({smax * m for m in SCALE_VARIANTS} | ({1.0} if smax > 1.0 else set()))
                for s in svals:
                    r = phi(g, ctx, kept, labels, s, perm, cov_src, s_cap_r1)
                    if r is None:
                        continue
                    out.append((r[0], dict(s=s, kept=kept, labels=labels, perm=perm, cov=r[1],
                                           dropped=[u for u in stream if id(u) in dropped])))
    return ctx, cov_src, out


def source_phi(g, r1_utility=False):
    ctx = G.Ctx(g, g.W0, g.H0)
    s_cap_r1 = ctx.s_cap
    ctx.r1_utility = r1_utility
    cov_src, _ = ink_coverage(G.build(g.stream, g.src_labels), 1.0, ctx)
    return phi(g, ctx, g.stream, tuple(g.src_labels), 1.0, 0, cov_src, s_cap_r1)[0]


def delta(g, meta):
    """Structured loss between the source and an alternative (how different it is)."""
    src = {(id(a), id(b)): l for a, b, l in zip(g.stream, g.stream[1:], g.src_labels)}
    ch = sum(1 for a, b, l in zip(meta["kept"], meta["kept"][1:], meta["labels"])
             if src.get((id(a), id(b)), "?") != l)
    return 0.1 * len(meta["dropped"]) + 0.05 * ch + 0.5 * abs(math.log(meta["s"])) + 0.03 * meta["perm"]


FREE_ALL = None
FREE_STRUCT = ["fill", "trans", "restack", "tsplit", "imgstack", "perm"]   # E3: only faithfulness/structure terms move


def calibrate(g, w0, r1_utility=False, C=200.0, iters=6000, free=None):
    ctx, cov_src, cands = candidates(g, g.W0, g.H0, r1_utility=r1_utility)
    f_src = source_phi(g, r1_utility)
    D = np.array([f_src - p for p, m in cands])            # margins must be >= delta
    dl = np.array([delta(g, m) for p, m in cands])
    keep = dl > 1e-9                                         # the source itself (delta 0) is not a constraint
    D, dl = D[keep], dl[keep]
    w = w0.copy()
    reg = 1.0 / np.maximum(np.abs(w0), 0.05) ** 2          # relative change is what costs
    n = len(dl)
    viol0 = int(np.sum(D @ w0 < dl - 1e-9))
    hard0 = int(np.sum(D @ w0 < -1e-9))                     # alternatives that strictly BEAT the source
    # preconditioned (natural-gradient) projected subgradient: stable for any prior scale
    for t in range(iters):
        v = (dl - D @ w) > 0
        g_hinge = -(C / max(1, n)) * D[v].sum(axis=0)
        step = 0.05 / math.sqrt(1 + t / 500)
        w = np.maximum(0.0, w - step * ((w - w0) + g_hinge / reg))
        if free is not None:
            mask = np.array([f in free for f in FEATS])
            w = np.where(mask, w, w0)
    m = D @ w
    viol1 = int(np.sum(m < dl - 1e-9))
    hard1 = int(np.sum(m < -1e-9))
    return w, dict(n=n, viol0=viol0, hard0=hard0, viol1=viol1, hard1=hard1, cov_src=cov_src)


def choose(g, W, H, w, r1_utility=False):
    ctx, cov_src, cands = candidates(g, W, H, r1_utility=r1_utility)
    scored = sorted(((float(w @ p), m) for p, m in cands), key=lambda t: -t[0])
    return ctx, scored


def emit_choice(g, design, ctx, J, m):
    ctx.s_cap = max(ctx.s_cap, m["s"])
    return G.emit(g, design, ctx, (J, m["s"], m["kept"], m["labels"], m["dropped"]))


def fmt_w(w, w0):
    parts = []
    for f in FEATS:
        a, b = w0[IDX[f]], w[IDX[f]]
        if abs(a - b) > 0.01:
            parts.append(f"{f}:{a:.2f}->{b:.2f}")
    return ", ".join(parts) or "(unchanged)"


def run_case(tag, design, targets, prior_name, w0, r1_utility, log, names, free=None):
    g = G.decompile(design)
    t = time.time()
    w, info = calibrate(g, w0, r1_utility, free=free)
    log.append(f"[{prior_name}] {tag}: {info['n']} source-canvas alternatives; prior: {info['hard0']} beat the source "
               f"outright, {info['viol0']} inside the margin -> calibrated: {info['hard1']} / {info['viol1']}  "
               f"({time.time()-t:.1f}s)  src ink coverage={info['cov_src']:.3f}")
    log.append(f"      weights: {fmt_w(w, w0)}")
    for (W, H) in targets:
        for wname, ww in (("prior", w0), ("calib", w)):
            ctx, scored = choose(g, W, H, ww, r1_utility)
            J, m = scored[0]
            gap = J - next((j for j, mm in scored[1:] if G.render_struct(mm["kept"], mm["labels"]) != G.render_struct(m["kept"], m["labels"])), J)
            out = emit_choice(g, design, ctx, J, m)
            name = f"taste_{prior_name}_{tag}_{W}x{H}_{wname}"
            (OUT / f"{name}.json").write_text(json.dumps(out, indent=1))
            G.render_design_to_png(out, str(G.ASSETS), str(OUT / f"{name}.png"))
            names.append(name)
            fp = ""
            if (W, H) == (g.W0, g.H0):
                fp = "  | " + G.fixed_point_report(design, out)
            log.append(f"      {W}x{H} {wname:5s}: s={m['s']:.3f} cov={m['cov']:.2f} gap-to-next-structure={gap:.3f}  "
                       f"{G.render_struct(m['kept'], m['labels'])}  omit={[u.name.split('+')[0] for u in m['dropped']]}{fp}")
        print("\n".join(log[-2:]), flush=True)


def main():
    load = lambda f: json.loads((ROOT / "input" / f).read_text())["source"]  # noqa: E731
    L1, L2, L3 = (load(f) for f in ("chameleon_sample_level1_warmup.json", "chameleon_sample_level2_core.json",
                                    "chameleon_sample_level3_advanced.json"))
    log, names1, names2 = [], [], []
    # E1: fragile prior (round-1 + fill .25), round-1 utility shape
    run_case("L1", L1, [(1080, 1080), (728, 90), (1080, 1350)], "E1", vec(W_BAD), True, log, names1)
    run_case("L2", L2, [(1080, 1080), (728, 90), (1600, 400)], "E1", vec(W_BAD), True, log, names1)
    run_case("L3", L3, [(1080, 1350), (728, 90)], "E1", vec(W_BAD), True, log, names1)
    run_case("U", UNSEEN, [(1200, 628), (1080, 1920)], "E1", vec(W_BAD), True, log, names1)
    # E2: source-relative density prior, plain log-scale utility (no caps)
    run_case("U", UNSEEN, [(1200, 628), (1080, 1920), (1080, 1080), (160, 600), (728, 90), (1600, 400)], "E2", vec(W_V2), False, log, names2)
    run_case("L2", L2, [(1080, 1080), (1080, 1920), (728, 90), (1600, 400)], "E2", vec(W_V2), False, log, names2)
    run_case("L3", L3, [(1080, 1350), (728, 90), (1080, 1920)], "E2", vec(W_V2), False, log, names2)
    run_case("L1", L1, [(1080, 1080), (1080, 1350), (728, 90)], "E2", vec(W_V2), False, log, names2)
    # E3: fragile prior again, but a TRUST REGION: only structure/faithfulness weights may move,
    #     scale & rent weights stay frozen (they are regime-specific and need corpus data)
    names3 = []
    for tag, d, tg in (("L1", L1, [(1080, 1080), (728, 90)]), ("L2", L2, [(1080, 1080), (728, 90), (1600, 400)]),
                       ("L3", L3, [(1080, 1350), (728, 90)]),
                       ("U", UNSEEN, [(1200, 628), (1080, 1920), (1080, 1080), (160, 600), (728, 90), (1600, 400)])):
        run_case(tag, d, tg, "E3", vec(W_BAD), True, log, names3, free=FREE_STRUCT)
    (OUT / "taste_log.txt").write_text("\n".join(log) + "\n")
    G.OUT, old = OUT, G.OUT
    try:
        G.contact_sheet(names1, OUT / "sheet_taste_E1.png", width=1500)
        G.contact_sheet(names2, OUT / "sheet_taste_E2.png", width=1500)
        G.contact_sheet(names3, OUT / "sheet_taste_E3.png", width=1500)
    finally:
        G.OUT = old


if __name__ == "__main__":
    main()
