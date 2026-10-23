"""R2 probe: OPTIMIZER's width cache is keyed by (id(el), font_size). Python reuses id() of
garbage-collected dicts, so in a long-running process (the scorer batch-runs hundreds of tasks)
a NEW element can hit a STALE width list measured for a DIFFERENT string.

We run the optimizer over all 26 catalogue sizes of two designs in ONE process (as main.py would)
and audit every wrap_text call it makes: are the widths it passes the true widths of that text?

Run from repo root:  .venv/bin/python design/debate/spikes/judge/r2_stale_cache_probe.py
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "design" / "debate" / "bench"))
sys.path.insert(0, str(ROOT))

from catalogue import CATALOGUE  # noqa: E402
from designs import load_all  # noqa: E402

import adapters.optimizer as opt  # noqa: E402

M = opt._mod
stats = {"calls": 0, "stale": 0, "short": 0, "examples": []}
orig_wrap = M.wrap_text


def audited_wrap(text, widths, max_w):
    stats["calls"] += 1
    if len(widths) != len(text):
        stats["short" if len(widths) < len(text) else "stale"] += 1
        if len(stats["examples"]) < 4:
            stats["examples"].append(f"len(text)={len(text)} len(widths)={len(widths)} text={text[:40]!r}")
    return orig_wrap(text, widths, max_w)


M.wrap_text = audited_wrap
tasks = load_all()
crashes = []
for name in ["S04_long_copy_editorial", "S12_many_badges", "L3_advanced", "S03_multi_product_grid"]:
    for size, (W, H) in CATALOGUE.items():
        try:
            opt.resize(copy.deepcopy(tasks[name]["source"]), {"width": W, "height": H})
        except Exception as exc:  # noqa: BLE001
            crashes.append(f"{name}/{size}: {type(exc).__name__}")
print(f"wrap calls audited: {stats['calls']}, width-list length mismatches: "
      f"{stats['stale'] + stats['short']} (longer={stats['stale']}, shorter={stats['short']} -> IndexError)")
for e in stats["examples"]:
    print("   ", e)
print("crashes:", crashes or "none")
print("NB: a mismatch with EQUAL length (same-length different string) is silent and not even counted here.")
