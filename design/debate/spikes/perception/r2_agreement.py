"""Pairwise agreement between the pixel critic and the eye ranking. Pairs are split into
'designed vs broken' (any pair touching baseline_stretch / judge_safefit) and 'designed vs designed'."""
import json, sys, itertools
from pathlib import Path
O = Path(__file__).parent / "r2_out"
scores = json.loads((O / (sys.argv[1] if len(sys.argv) > 1 else "scores.json")).read_text())
eye = {k: v for k, v in json.loads((O / "eye_rankings.json").read_text()).items() if not k.startswith("_")}
FLOOR = {"baseline_stretch", "judge_safefit"}
agg = {"easy": [0, 0], "hard": [0, 0]}; top1 = 0
for task, order in eye.items():
    s = {r["engine"]: r["total"] for r in scores[task]}
    critic_best = min((e for e in order), key=lambda e: s[e])
    top1 += critic_best == order[0]
    for a, b in itertools.combinations(order, 2):           # eye says a > b
        kind = "easy" if (a in FLOOR or b in FLOOR) else "hard"
        agg[kind][1] += 1; agg[kind][0] += s[a] < s[b]
    print(f"{task:15s} eye-best={order[0]:10s} critic-best={critic_best:12s} critic order={sorted(order, key=lambda e: s[e])}")
for k, (ok, n) in agg.items():
    print(f"{k:5s} pairs ({'involving a floor/baseline' if k=='easy' else 'designed vs designed'}): critic agrees {ok}/{n} = {ok/n:.0%}")
print(f"top-1 agreement: {top1}/{len(eye)}")
