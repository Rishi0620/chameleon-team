"""Which tie-break policy best matches the blind eye picks on GALLEY's near-tie top-10s?"""
import json
from pathlib import Path
O = Path(__file__).parent / "r2_out"
key = json.loads((O / "near_ties_key.json").read_text()); eye = json.loads((O / "near_ties_eye_BLIND.json").read_text())
def flags(v): return sum(1 for n in v["notes"] if "one-word line" in n or "fills" in n or "spills" in n or "x-height" in n or "collision" in n)
pol = {
 "J only (generator energy)": lambda k, L: (k[L]["galley_rank"],),
 "critic only (continuous score)": lambda k, L: (k[L]["critic"],),
 "lexicographic: critic DEFECT count, then J": lambda k, L: (flags(k[L]), k[L]["galley_rank"]),
 "rank-sum (J rank + critic rank)": None,
}
for name, f in pol.items():
    pairs = ok = best = top3 = 0
    for tag, e in eye.items():
        if tag.startswith("_"): continue
        k = key[tag]
        if f is None:
            cr = {L: i for i, L in enumerate(sorted(k, key=lambda L: k[L]["critic"]))}
            keyf = lambda L: (k[L]["galley_rank"] + cr[L], k[L]["galley_rank"])
        else:
            keyf = lambda L: f(k, L)
        order = sorted(k, key=keyf)
        best += order[0] == e["best"]; top3 += order[0] in e["top3"]
        for a in e["top3"]:
            for b in e["worst"]:
                pairs += 1; ok += keyf(a) < keyf(b)
    print(f"{name:45s} good-vs-bad pairs {ok}/{pairs} = {ok/pairs:.0%} | pick == eye-best {best}/4 | pick in eye-top3 {top3}/4")
