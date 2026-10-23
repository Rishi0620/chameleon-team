"""Evaluate proto/critic.py (owner: PERCEPTION) on tests/critic_pairs.json.
Reports: render parity vs the official renderer, veto precision/recall (per output and per defect kind),
pairwise agreement on defect pairs and taste pairs, ms per call, never-raise checks.
Run from repo root:  .venv/bin/python design/debate/proto/tests/test_critic.py   (writes tests/critic_eval.txt)"""
import io
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from design.debate.proto import critic as K  # noqa: E402
from renderer.converter.convert import render_design_to_png  # noqa: E402

T = Path(__file__).resolve().parent
lines = []


def log(s=""):
    print(s)
    lines.append(s)


S = json.loads((T / "critic_pairs.json").read_text())
src_cache = {}


def load_src(key):
    if key not in src_cache:
        d = json.loads((ROOT / S["sources"][key]["path"]).read_text())
        src_cache[key] = d.get("source", d)
    return src_cache[key]


# ---------------------------------------------------------------- 1. parity with the official renderer
log("== 1. render parity: critic's in-process replica vs official render_design_to_png ==")
for oid in ["r2:L2->1600x400:designer", "r2:L3->728x90:optimizer", "inv:topo_F1_1600x400_v1", "mut:L3_1600_rotclip"]:
    o = next(x for x in S["outputs"] if x["id"] == oid)
    d = json.loads((ROOT / o["output"]).read_text())
    ad = K._assets_dir({"assets_dir": S["sources"][o["source"]]["assets_dir"]})
    tmp = T / "data" / "_parity.png"
    render_design_to_png(d, ad, str(tmp), fonts_dir=str(ROOT / "brand_kit/fonts"))
    from PIL import Image
    off = np.asarray(Image.open(tmp).convert("RGB")).astype(int)
    rep = K._draw(d, ad)[..., :3].astype(int)
    diff = np.abs(off - rep).max(-1)
    log(f"  {oid:32s} max|diff|={diff.max():3d}  pixels differing >8: {(diff > 8).mean():.4%}")

# ---------------------------------------------------------------- 2. run the critic on every labelled output
log("\n== 2. critic on every labelled output ==")
res, ms = {}, []
for o in S["outputs"]:
    src = load_src(o["source"])
    out = json.loads((ROOT / o["output"]).read_text())
    info = dict(S["sources"][o["source"]]["info"])
    info["hidden"] = [e["id"] for e in out["elements"] if float(e.get("opacity", 1.0)) <= 0.01]
    t0 = time.perf_counter()
    r = K.critique(src, out, info)
    ms.append((time.perf_counter() - t0) * 1000)
    if r["features"].get("error"):
        log(f"  ERROR {o['id']}: {r['features']['error']}")
    res[o["id"]] = r
warm = sorted(ms)[len(ms) // 2]
log(f"  {len(ms)} calls; median {warm:.1f} ms, p90 {sorted(ms)[int(0.9 * len(ms))]:.1f} ms, max {max(ms):.1f} ms "
    f"(first-call/source-analysis costs included in max); cache {K._STATS}")

# ---------------------------------------------------------------- 3. veto precision / recall
log("\n== 3. veto precision / recall (positive = labelled defect; predicted = >=1 veto) ==")
tp = fp = fn = tn = 0
fps, fns = [], []
for o in S["outputs"]:
    pred = len(res[o["id"]]["vetoes"]) > 0
    lab = o["label"] == "defect"
    tp += pred and lab
    fp += pred and not lab
    fn += lab and not pred
    tn += (not lab) and (not pred)
    if pred and not lab:
        fps.append((o["id"], [(v["code"], v["ids"]) for v in res[o["id"]]["vetoes"]][:3]))
    if lab and not pred:
        fns.append((o["id"], o["defect_kinds"]))
prec = tp / max(1, tp + fp)
rec = tp / max(1, tp + fn)
log(f"  TP {tp}  FP {fp}  FN {fn}  TN {tn}   precision {prec:.0%}   recall {rec:.0%}")
for k, v in fps:
    log(f"  false positive: {k}: {v}")
for k, v in fns:
    log(f"  false negative: {k}: labelled {v}")
log("\n  per defect kind (recall of the matching veto code on outputs labelled with that kind):")
kinds = sorted({k for o in S["outputs"] for k in o["defect_kinds"]})
for kd in kinds:
    labelled = [o for o in S["outputs"] if kd in o["defect_kinds"]]
    hit = [o for o in labelled if any(v["code"] == kd for v in res[o["id"]]["vetoes"])]
    log(f"    {kd:14s} {len(hit)}/{len(labelled)}")
log("\n  veto codes fired on CLEAN outputs (false-positive sources):")
fpc = {}
for o in S["outputs"]:
    if o["label"] == "clean":
        for v in res[o["id"]]["vetoes"]:
            fpc[v["code"]] = fpc.get(v["code"], 0) + 1
log("    " + (", ".join(f"{k}: {v}" for k, v in sorted(fpc.items())) or "none"))

# ---------------------------------------------------------------- 4. pairwise
log("\n== 4. pairwise agreement (critic prefers lower (n_vetoes, penalty)) ==")
for kind in ("defect", "taste"):
    P = [p for p in S["pairs"] if p["kind"] == kind]
    ok = sum((len(res[p["better"]]["vetoes"]), res[p["better"]]["penalty"]) <
             (len(res[p["worse"]]["vetoes"]), res[p["worse"]]["penalty"]) for p in P)
    ties = sum((len(res[p["better"]]["vetoes"]), res[p["better"]]["penalty"]) ==
               (len(res[p["worse"]]["vetoes"]), res[p["worse"]]["penalty"]) for p in P)
    log(f"  {kind:6s} pairs: {ok}/{len(P)} = {ok / max(1, len(P)):.0%} agree ({ties} exact ties)")
    for by in sorted({p["by"] for p in P}):
        Q = [p for p in P if p["by"] == by]
        okq = sum((len(res[p["better"]]["vetoes"]), res[p["better"]]["penalty"]) <
                  (len(res[p["worse"]]["vetoes"]), res[p["worse"]]["penalty"]) for p in Q)
        log(f"      {by:36s} {okq}/{len(Q)}")
inv = [p for p in S["pairs"] if p["by"].startswith("inventor")]
log("  INVENTOR's 4 eye-known pairs (round-1 critic: 0/4):")
for p in inv:
    b, w = res[p["better"]], res[p["worse"]]
    good = (len(b["vetoes"]), b["penalty"]) < (len(w["vetoes"]), w["penalty"])
    log(f"    {p['better']:34s} vs {p['worse']:34s} -> {'AGREES' if good else 'disagrees'} "
        f"(vetoes {len(b['vetoes'])}/{len(w['vetoes'])}, penalty {b['penalty']:.2f}/{w['penalty']:.2f})")

# ---------------------------------------------------------------- 5. never raises
log("\n== 5. never-raise checks ==")
src = load_src("L2")
for name, args in [("output=None", (src, None, {})), ("empty elements", (src, {"canvas": {"width": 10, "height": 10}, "elements": []}, {})),
                   ("text width 0", (src, {"canvas": {"width": 300, "height": 100}, "elements": [dict(src["elements"][5], x=1, y=1, width=0, height=0)]}, {})),
                   ("info=None", (src, json.loads((ROOT / S['outputs'][0]['output']).read_text()), None))]:
    try:
        r = K.critique(*args)
        log(f"  {name:16s} -> ok: vetoes {len(r['vetoes'])}, penalty {r['penalty']}, error={r['features'].get('error', '-')[:70]}")
    except Exception as exc:  # pragma: no cover
        log(f"  {name:16s} -> RAISED {exc!r}")
(T / "critic_eval.txt").write_text("\n".join(lines))
