"""Re-score saved engine outputs after a scorer change (engines are NOT re-run).
Keeps crash / timeout / n/a records and timings; recomputes evaluate() for every saved output JSON.
    .venv/bin/python design/debate/bench/rescore.py [--engines a,b] [--workers 10]
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
RES = BENCH / "results"


def rescore(path: str) -> str:
    import os
    os.chdir(BENCH.parents[2])
    sys.path.insert(0, str(BENCH))
    from designs import load_all
    from score import evaluate
    p = Path(path)
    engine, design = p.parent.name, p.stem
    task = load_all()[design]
    out_lines = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        jp = p.parent / "json" / f"{design}__{r['size']}.json"
        if r["status"] in ("ok", "hard_fail", "score_error") and jp.exists():
            out = json.loads(jp.read_text())
            keep = {k: r[k] for k in ("engine", "design", "size", "W", "H", "band", "secs", "import_secs", "mutated_input") if k in r}
            ev = evaluate(design, task["source"], out, {"width": r["W"], "height": r["H"]},
                          str(p.parent / "png" / f"{design}__{r['size']}.png"))
            r = {**keep, "status": "hard_fail" if ev["hard"] else "ok", **ev}
        out_lines.append(json.dumps(r, default=str))
    p.write_text("\n".join(out_lines) + "\n")
    return f"{engine}/{design}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="")
    ap.add_argument("--workers", type=int, default=10)
    a = ap.parse_args()
    files = sorted(RES.glob("*/*.jsonl"))
    if a.engines:
        files = [f for f in files if f.parent.name in a.engines.split(",")]
    with ProcessPoolExecutor(max_workers=a.workers, max_tasks_per_child=1) as ex:
        for f in as_completed([ex.submit(rescore, str(x)) for x in files]):
            print(f.result(), flush=True)
