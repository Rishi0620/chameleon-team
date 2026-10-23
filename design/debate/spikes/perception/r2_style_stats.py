"""Spike r2 (open problem #1, perception side): 'style-statistics transfer'. Is matching the SOURCE render's
statistics a good objective? For each stat we ask two questions on the 8 eye-ranked tasks:
  (a) INVARIANCE  - does the eye-best output preserve it? (log ratio output/source, median and spread across tasks)
  (b) PREFERENCE  - among designed outputs of the same task, is the one closer to the source preferred by the eye?
                    (pairwise agreement over designed-vs-designed pairs; 50% = useless)"""
import json, sys, itertools
from pathlib import Path
import numpy as np
HERE = Path(__file__).parent; ROOT = HERE.parents[3]; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from r2_critic import measure
from critic import render
from roles import infer_roles
src_txt = (HERE / "r2_cross_engine.py").read_text().split("tasks = set()")[0]
g = {"__file__": str(HERE / "r2_cross_engine.py")}; exec(compile(src_txt, "r2ce", "exec"), g)
LV, candidates, remap = g["LV"], g["candidates"], g["remap"]
eye = {k: v for k, v in json.loads((HERE / "r2_out/eye_rankings.json").read_text()).items() if not k.startswith("_")}
BRAND = {"orange": (232, 106, 58), "white": (255, 255, 255), "gold": (240, 178, 66)}

def stats(d, roles):
    f = measure(d, roles); W, H = f["cw"], f["ch"]; full = render(d)[..., :3].astype(int)
    vis = [k for k, v in f["els"].items() if v.get("visible") and roles[k] not in ("background", "decoration")]
    fg = np.zeros((H, W), bool)
    for k in vis: fg |= f["els"][k]["mask"]
    ys, xs = np.nonzero(fg)
    tot = max(1, sum(f["els"][k]["mask"].sum() for k in vis))
    share = lambda pred: sum(f["els"][k]["mask"].sum() for k in vis if pred(roles[k])) / tot
    caps = {k: f["els"][k]["cap"] for k in vis if "cap" in f["els"][k]}
    head = next(k for k, v in roles.items() if v == "headline")
    others = [c for k, c in caps.items() if k != head and roles[k] != "legal"]
    gy, gx = np.gradient(full.mean(-1))
    s = {
        "ink density": fg.mean(),
        "whitespace (1-content bbox)": 1 - (np.ptp(xs) * np.ptp(ys) / (W * H) if len(xs) else 0),
        "headline weight share": share(lambda r: r == "headline"),
        "logo weight share": share(lambda r: r == "logo"),
        "hero weight share": share(lambda r: r == "hero") + 1e-3,
        "CTA weight share": share(lambda r: r.startswith("cta")),
        "type ramp (head cap / next cap)": caps.get(head, 0) / max(others) if others and head in caps else np.nan,
        "headline contrast": f["els"][head].get("contrast", np.nan),
        "edge density": (np.hypot(gx, gy) > 12).mean(),
        "orange area": (np.abs(full - BRAND["orange"]).sum(-1) < 40).mean() + 1e-4,
        "white area": (np.abs(full - BRAND["white"]).sum(-1) < 40).mean() + 1e-4,
        "gold area": (np.abs(full - BRAND["gold"]).sum(-1) < 40).mean() + 1e-4,
        "ink centroid x": xs.mean() / W if len(xs) else .5,
        "ink centroid y": ys.mean() / H if len(ys) else .5,
    }
    return s

res = {}
for task, order in eye.items():
    n, (W, H) = int(task[1]), map(int, task.split(">")[1].split("x"))
    src = json.loads((ROOT / f"input/chameleon_sample_{LV[n]}.json").read_text())["source"]; roles = infer_roles(src)
    c = candidates(n, W, H); designed = [e for e in order if e in c]
    res[task] = {"source": stats(src, roles), **{e: stats(remap(src, c[e]), roles) for e in designed}}
    res[task]["_order"] = designed
keys = list(res[next(iter(res))]["source"].keys())
print(f"{'statistic':32s} | eye-best/source: median log2 ratio [min,max] | closer-to-source preferred (designed pairs)")
rows = []
for k in keys:
    lr = []; ok = tot = 0
    for task, r in res.items():
        o = r["_order"]; sv = r["source"][k]
        if not np.isfinite(sv) or sv == 0: continue
        lr.append(np.log2(r[o[0]][k] / sv) if np.isfinite(r[o[0]][k]) and r[o[0]][k] > 0 else np.nan)
        for a, b in itertools.combinations(o, 2):           # eye prefers a
            da, db = abs(np.log2(r[a][k] / sv)), abs(np.log2(r[b][k] / sv))
            if np.isfinite(da) and np.isfinite(db) and da != db: tot += 1; ok += da < db
    lr = np.array([x for x in lr if np.isfinite(x)])
    rows.append((k, float(np.median(lr)), float(lr.min()), float(lr.max()), ok, tot))
    print(f"{k:32s} | {np.median(lr):+5.2f} [{lr.min():+5.2f},{lr.max():+5.2f}]                  | {ok}/{tot} = {ok/max(1,tot):.0%}")
(HERE / "r2_out" / "style_stats.json").write_text(json.dumps(rows, indent=1, default=float))
# (c) is there a TRANSFER FUNCTION? correlate the eye-best log-ratio with how much the canvas changed
print("\nSpearman of eye-best log2(stat ratio) vs log2(target area / source area) and vs |log2 aspect change|:")
from itertools import combinations
def spear(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b)); return float(np.corrcoef(ra, rb)[0, 1])
for k in keys:
    xs_a, xs_r, ys_ = [], [], []
    for task, r in res.items():
        n, (W, H) = int(task[1]), map(int, task.split(">")[1].split("x"))
        S = json.loads((ROOT / f"input/chameleon_sample_{LV[n]}.json").read_text())["source"]["canvas"]
        sv, bv = r["source"][k], r[r["_order"][0]][k]
        if not (np.isfinite(sv) and np.isfinite(bv)) or sv <= 0 or bv <= 0: continue
        xs_a.append(np.log2(W * H / (S["width"] * S["height"]))); xs_r.append(abs(np.log2((W / H) / (S["width"] / S["height"])))); ys_.append(np.log2(bv / sv))
    if len(ys_) >= 5:
        print(f"  {k:32s} vs area {spear(xs_a, ys_):+.2f}   vs aspect change {spear(xs_r, ys_):+.2f}   (n={len(ys_)})")
