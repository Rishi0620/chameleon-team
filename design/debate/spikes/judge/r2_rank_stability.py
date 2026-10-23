"""R2 experiment: is the bench ranking an artefact of my hand-set scorer weights?

Re-scores every recorded case under 2,000 random re-weightings of the composite (every penalty's
per-instance cost and cap, and the faithfulness / fill / dead-band weights, each multiplied by
exp(N(0, 0.6)) ~ x0.3..x3) and reports how often each engine ranks #1 by mean score:
  (a) all 26 sizes, perception excluded (it only runs on strips)
  (b) the strip band only, all engines
Hard failures stay at 0 under every weighting (they are not a weight choice).

Run after bench/run.py:  .venv/bin/python design/debate/spikes/judge/r2_rank_stability.py
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BENCH = ROOT / "design" / "debate" / "bench"
sys.path.insert(0, str(BENCH))
from score import PENALTY, W_DEAD, W_FAITH_INK, W_FAITH_PRIMARY, W_FILL  # noqa: E402

OUT = Path(__file__).resolve().parent / "r2_out"


def composite(r: dict, k: dict) -> float:
    if r["status"] != "ok":
        return 0.0
    pen = 0.0
    for cls, msgs in (r.get("issues") or {}).items():
        if cls in PENALTY:
            per, cap = PENALTY[cls]
            pen += min(cap * k[cls], per * k[cls] * len(msgs))
    m = r["metrics"]
    pen += W_FAITH_INK * k["faith"] * (1 - m["kept_ink"]) + (0 if m["primary_kept"] else W_FAITH_PRIMARY * k["prim"])
    pen += W_FILL * k["fill"] * max(0.0, 1 - m["fill_rel"] / 0.7)
    pen += W_DEAD * k["dead"] * max(0.0, m["dead_band"] - max(0.2, m["src_dead_band"] + 0.1))
    return max(0.0, 100 - pen)


def main() -> None:
    rows = []
    for p in sorted((BENCH / "results").glob("*/*.jsonl")):
        rows += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    rows = [r for r in rows if r["status"] != "n/a" and r["engine"] != "baseline"]
    keys = list(PENALTY) + ["faith", "prim", "fill", "dead"]
    rng = random.Random(0)
    wins = {"all_sizes": Counter(), "strip_band": Counter()}
    for _ in range(2000):
        k = {c: math.exp(rng.gauss(0, 0.6)) for c in keys}
        for view in wins:
            agg = defaultdict(list)
            for r in rows:
                if view == "all_sizes" and r["engine"] == "perception":
                    continue
                if view == "strip_band" and r["band"] != "strip":
                    continue
                agg[r["engine"]].append(composite(r, k))
            means = {e: sum(v) / len(v) for e, v in agg.items()}
            wins[view][max(means, key=means.get)] += 1
    unit = {c: 1.0 for c in keys}
    out = {}
    for view in wins:
        agg = defaultdict(list)
        for r in rows:
            if (view == "all_sizes" and r["engine"] == "perception") or (view == "strip_band" and r["band"] != "strip"):
                continue
            agg[r["engine"]].append(composite(r, unit))
        out[view] = {"default_means": {e: round(sum(v) / len(v), 1) for e, v in agg.items()},
                     "p_rank1": {e: round(c / 2000, 3) for e, c in wins[view].most_common()}}
    OUT.mkdir(exist_ok=True)
    (OUT / "rank_stability.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
