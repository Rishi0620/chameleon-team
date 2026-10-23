"""Held-out cross-check (owner: PERCEPTION): critic.py vs JUDGE's independent bench proxy on designs the critic was
never tuned on (12 adversarial bench designs + 3 samples, x 26 catalogue sizes), using DESIGNER's engine (fast,
deterministic) to regenerate the outputs the bench already scored (bench/results/designer/*.jsonl).
Two automated raters, so this measures AGREEMENT, not accuracy; disagreements are listed for eyeballing.
    .venv/bin/python design/debate/proto/tests/critic_vs_bench.py      (writes tests/critic_vs_bench.txt)"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
BENCH = ROOT / "design/debate/bench"
sys.path.insert(0, str(BENCH))
from design.debate.proto import critic as K  # noqa: E402
from designs import load_all  # noqa: E402
from catalogue import CATALOGUE  # noqa: E402
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("perception_roles", ROOT / "design/debate/spikes/perception/roles.py")
PR = importlib.util.module_from_spec(_spec)   # loaded under a private name: DESIGNER's compose.py imports its own `roles`
_spec.loader.exec_module(PR)
from adapters import designer as DES  # noqa: E402

MAP = {"background": "background", "headline": "headline", "subhead": "subhead", "legal": "legal",
       "cta_bg": "cta_shape", "cta_label": "cta_label", "cta_text": "cta_label", "badge_bg": "badge_shape",
       "badge_label": "badge_label", "sticker": "furniture", "logo": "logo", "hero": "hero",
       "decoration": "decoration", "panel": "panel", "unseen_image": "unknown", "other": "unknown"}
ASSETS = str(BENCH / "assets")
# bench issue class -> critic veto code(s) that should co-fire
PAIRS = {"unreadable_text": {"ILLEGIBLE"}, "text_overflow": {"TEXT_OVERFLOW", "CLIPPED"}, "text_off_canvas": {"CLIPPED"}, "rotated_clip": {"CLIPPED"},
         "placeholder_visible": {"PLACEHOLDER"}, "hidden_leak": {"HIDDEN_LEAK"},
         "text_collision": {"INK_COLLISION", "SPILL"}, "image_collision": {"INK_COLLISION"},
         "low_contrast": {"LOST_BACKDROP"}, "busy_under_text": {"BUSY_BACKDROP"}}


def info_for(src):
    PR.ASSETS = Path(ASSETS)
    PR._cache.clear()
    r = {k: MAP.get(v, "unknown") for k, v in PR.infer_roles(src).items()}
    groups = {}
    for e in src["elements"]:
        if e.get("group_id"):
            groups.setdefault(e["group_id"], []).append(e["id"])
    return {"roles": r, "groups": groups, "containers": {}, "assets_dir": ASSETS}


stored = {}
for p in (BENCH / "results/designer").glob("*.jsonl"):
    for line in p.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            stored[(rec["design"], rec["size"])] = rec
out_lines, conf, cat, ms, n = [], Counter(), Counter(), [], 0
disagree = []
t_all = time.perf_counter()
for name, task in sorted(load_all().items()):
    src = task["source"]
    info = info_for(src)
    for size, (W, H) in CATALOGUE.items():
        rec = stored.get((name, size))
        if rec is None or rec.get("status") != "ok":
            continue
        try:
            out = DES.resize(src, {"width": W, "height": H})
        except Exception as exc:
            print("engine error", name, size, repr(exc)[:120])
            continue
        inf = dict(info, hidden=[e["id"] for e in out["elements"] if float(e.get("opacity", 1.0)) <= 0.01])
        t0 = time.perf_counter()
        r = K.critique(src, out, inf)
        ms.append((time.perf_counter() - t0) * 1000)
        n += 1
        codes = {v["code"] for v in r["vetoes"]}
        bench = set(rec.get("issues", {}).keys()) | {w.split(":")[0] for w in rec.get("warn", [])}
        bench_hard = bench & set(PAIRS)
        conf[(bool(codes), bool(bench_hard))] += 1
        for bc, cc in PAIRS.items():
            cat[(bc, bc in bench, bool(codes & cc))] += 1
        if bool(codes) != bool(bench_hard):
            disagree.append((name, size, sorted(codes), sorted(bench_hard)))
log = out_lines.append
log(f"{n} cases (DESIGNER outputs regenerated, bench issues as stored); critic median {sorted(ms)[len(ms)//2]:.0f} ms, "
    f"p90 {sorted(ms)[int(.9*len(ms))]:.0f} ms, max {max(ms):.0f} ms; total {time.perf_counter()-t_all:.0f} s")
log("case level (critic any-veto vs bench any veto-class issue):")
log(f"  both {conf[(True, True)]}, critic only {conf[(True, False)]}, bench only {conf[(False, True)]}, neither {conf[(False, False)]}"
    f"  -> agreement {(conf[(True, True)] + conf[(False, False)]) / max(1, n):.0%}")
log("per class (bench class: cases flagged by bench | of those, critic co-fires | critic fires when bench silent):")
for bc in PAIRS:
    fb = cat[(bc, True, True)] + cat[(bc, True, False)]
    log(f"  {bc:20s} bench {fb:3d} | critic agrees {cat[(bc, True, True)]:3d} | critic-only {cat[(bc, False, True)]:3d}")
log(f"disagreements ({len(disagree)}):")
for d in disagree:
    log(f"  {d[0]:28s} {d[1]:18s} critic={d[2]} bench={d[3]}")
txt = "\n".join(out_lines)
print(txt)
(Path(__file__).parent / "critic_vs_bench.txt").write_text(txt)
