"""R2 experiment: can the SOURCE design identify the objective's weights? (moderator open problem 1)

Idea under test: "the source is a solved instance of the designer's objective -> fit the energy
weights so the source is the argmin at its own canvas (inverse optimization), then solve at the
target." That only works if the weights that matter at the TARGET are constrained by optimality
at the SOURCE canvas. Test with OPTIMIZER's energy (the only spike with an explicit weight dict):

  draw 40 random weight vectors (each weight x exp(N(0, 0.7)), i.e. roughly x0.25..x4)
  for each design: solve at (a) the source canvas, (b) 728x90, (c) 1080x1920, (d) 300x250
  record whether the chosen layout changes vs. the default weights (visible set, or any visible
  box moved > 2% of the canvas diagonal)

v2 (the real test): keep only weight draws whose output at the SOURCE canvas is an acceptable
fixed point (every source-visible element visible, every centre within 3% of the diagonal), i.e.
weights 'consistent with the source'. If those draws still disagree about the 728x90 / story /
300x250 layouts, the source does not pin the decisions that matter there.

Run from repo root:  .venv/bin/python design/debate/spikes/judge/r2_inverse_identifiability.py
"""
from __future__ import annotations

import copy
import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BENCH = ROOT / "design" / "debate" / "bench"
OUT = Path(__file__).resolve().parent / "r2_out"
DESIGNS = ["L1_warmup", "L2_core", "L3_advanced", "S01_split_photo", "S05_rotated_sticker_bleed", "S09_banner_source"]
TARGETS = {"source": None, "leaderboard": (728, 90), "story": (1080, 1920), "med_rect": (300, 250)}
N_DRAWS = 60


def visible(e):
    if float(e.get("opacity", 1)) <= 0.001:
        return False
    return not (e.get("type") == "text" and str(e.get("color", "")).replace(" ", "").endswith(",0)"))


def changed(a: dict, b: dict) -> tuple[bool, bool]:
    W, H = a["canvas"]["width"], a["canvas"]["height"]
    diag = math.hypot(W, H)
    A = {e["id"]: e for e in a["elements"]}
    vis_changed, moved = False, False
    for e in b["elements"]:
        o = A[e["id"]]
        if visible(o) != visible(e):
            vis_changed = True
        elif visible(o):
            ca = (o["x"] + o["width"] / 2, o["y"] + o["height"] / 2)
            cb = (e["x"] + e["width"] / 2, e["y"] + e["height"] / 2)
            if math.hypot(ca[0] - cb[0], ca[1] - cb[1]) > 0.02 * diag or abs(o["width"] - e["width"]) > 0.02 * diag:
                moved = True
    return vis_changed, moved


def _solve(opt, src, W, H):
    """Clear OPTIMIZER's id()-keyed caches first: they go stale across solves (see r2_stale_cache_probe.py)."""
    for c in (opt._mod._cw, opt._mod._met, opt._mod._wk):
        c.clear()
    return opt.resize(copy.deepcopy(src), {"width": W, "height": H})


def fixed_point_ok(src: dict, out: dict) -> bool:
    """Is this output an acceptable reproduction of the SOURCE at its own canvas?"""
    W, H = src["canvas"]["width"], src["canvas"]["height"]
    diag = math.hypot(W, H)
    O = {e["id"]: e for e in out["elements"]}
    for e in src["elements"]:
        o = O[e["id"]]
        if visible(e) and not visible(o):
            return False
        if visible(e):
            d = math.hypot(o["x"] + o["width"] / 2 - e["x"] - e["width"] / 2, o["y"] + o["height"] / 2 - e["y"] - e["height"] / 2)
            if d > 0.03 * diag:
                return False
    return True


def signature(out: dict) -> tuple:
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    q = 0.03 * math.hypot(W, H)
    return tuple(sorted((e["id"], visible(e), round((e["x"] + e["width"] / 2) / q), round((e["y"] + e["height"] / 2) / q))
                        for e in out["elements"] if visible(e)))


def run_design(name: str) -> dict:
    import os
    from collections import Counter
    os.chdir(ROOT)
    sys.path.insert(0, str(BENCH))
    sys.path.insert(0, str(ROOT))
    from designs import load_all
    import adapters.optimizer as opt
    src = load_all()[name]["source"]
    base_w = dict(opt._mod.W)
    rng = random.Random(sum(map(ord, name)))
    draws = [None] + [{k: v * math.exp(rng.gauss(0, 0.7)) for k, v in base_w.items()} for _ in range(N_DRAWS)]
    recs = []
    for w in draws:
        opt._mod.W.clear()
        opt._mod.W.update(w or base_w)
        rec = {}
        for tname, size in TARGETS.items():
            W, H = size or (src["canvas"]["width"], src["canvas"]["height"])
            try:
                out = _solve(opt, src, W, H)
            except Exception:  # noqa: BLE001
                rec[tname] = None
                continue
            rec[tname] = {"sig": signature(out), "vis": tuple(sorted(e["id"] for e in out["elements"] if visible(e)))}
            if tname == "source":
                rec["fp_ok"] = fixed_point_ok(src, out)
        recs.append(rec)
    opt._mod.W.clear()
    opt._mod.W.update(base_w)
    res = {"design": name, "default_fixed_point_ok": recs[0].get("fp_ok"),
           "n_draws": N_DRAWS, "n_fixed_point_ok": sum(1 for r in recs[1:] if r.get("fp_ok"))}
    ok = [r for r in recs[1:] if r.get("fp_ok")]
    for tname in TARGETS:
        if tname == "source":
            continue
        sigs = Counter(r[tname]["sig"] for r in ok if r.get(tname))
        viss = Counter(r[tname]["vis"] for r in ok if r.get(tname))
        n = sum(sigs.values())
        res[tname] = {"distinct_layouts_among_fp_ok": len(sigs), "distinct_visible_sets": len(viss),
                      "share_not_majority_layout": round(1 - (sigs.most_common(1)[0][1] / n), 2) if n else None}
    return res


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    with ProcessPoolExecutor(max_workers=len(DESIGNS), max_tasks_per_child=1) as ex:
        rows = list(ex.map(run_design, DESIGNS))
    (OUT / "inverse_identifiability.json").write_text(json.dumps(rows, indent=1))
    print(json.dumps(rows, indent=1))
