"""Bench runner: N designs x M catalogue sizes x K engines, one fresh process per (engine, design).

    .venv/bin/python design/debate/bench/run.py                       # all engines, designs, sizes
    .venv/bin/python design/debate/bench/run.py --engines galley --designs S03_multi_product_grid --force
    .venv/bin/python design/debate/bench/run.py --module my_pkg.my_engine   # any module exposing resize()

Per case it records: crash / timeout / n/a, wall time, structural hard+warn, pixel issues, metrics,
composite score, the output JSON and a 420px thumbnail. Results are written incrementally to
bench/results/<engine>/<design>.jsonl, so an interrupted run resumes where it stopped.
"""
from __future__ import annotations

import argparse
import copy
import importlib
import json
import signal
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parents[2]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(ROOT))

from catalogue import CATALOGUE, band  # noqa: E402

ENGINES = {"baseline": "adapters.baseline", "safe_floor": "adapters.safe_floor",
           "optimizer": "adapters.optimizer", "galley": "adapters.galley",
           "designer": "adapters.designer", "perception": "adapters.perception",
           "optimizer_fixed": "adapters.optimizer_fixed",
           # Round 4: the merged prototype (+ hide-policy variants). Not in the default set until it exists.
           "proto": "adapters.proto", "proto_zunder": "adapters.proto_zunder",
           "proto_nevertext": "adapters.proto_nevertext"}
DEFAULT = ["baseline", "safe_floor", "optimizer", "galley", "designer", "perception"]
RESULTS = BENCH / "results"


class _Timeout(Exception):
    pass


def _alarm(_sig, _frm):
    raise _Timeout()


def run_pair(engine_key: str, module: str, design: str, sizes: list[str], timeout: int, force: bool) -> str:
    import os
    os.chdir(ROOT)
    sys.path.insert(0, str(BENCH))
    from designs import load_all
    from score import evaluate
    out_dir = RESULTS / engine_key
    (out_dir / "json").mkdir(parents=True, exist_ok=True)
    (out_dir / "png").mkdir(parents=True, exist_ok=True)
    log = out_dir / f"{design}.jsonl"
    done = set()
    if log.exists() and not force:
        done = {json.loads(line)["size"] for line in log.read_text().splitlines() if line.strip()}
    elif log.exists():
        log.unlink()
    todo = [s for s in sizes if s not in done]
    if not todo:
        return f"{engine_key}/{design}: cached"
    task = load_all()[design]
    t_imp = time.time()
    try:
        adapter = importlib.import_module(module)
        import_err = None
    except Exception as exc:  # noqa: BLE001
        adapter, import_err = None, f"{type(exc).__name__}: {exc}"
    t_imp = time.time() - t_imp
    signal.signal(signal.SIGALRM, _alarm)
    with log.open("a") as fh:
        for size in todo:
            W, H = CATALOGUE[size]
            rec = {"engine": engine_key, "design": design, "size": size, "W": W, "H": H, "band": band(W, H),
                   "status": "ok", "secs": None, "import_secs": round(t_imp, 2)}
            if adapter is None:
                rec.update(status="crash", error=f"import: {import_err}")
            elif hasattr(adapter, "applies") and not adapter.applies(W, H):
                rec.update(status="n/a")
            else:
                src = copy.deepcopy(task["source"])
                snapshot = json.dumps(src, sort_keys=True)
                t0 = time.time()
                out = None
                signal.alarm(timeout)
                try:
                    out = adapter.resize(src, {"width": W, "height": H})
                except _Timeout:
                    rec.update(status="timeout", error=f">{timeout}s")
                except Exception as exc:  # noqa: BLE001
                    rec.update(status="crash", error=f"{type(exc).__name__}: {str(exc)[:160]}",
                               trace=traceback.format_exc().splitlines()[-4:])
                finally:
                    signal.alarm(0)
                rec["secs"] = round(time.time() - t0, 3)
                if out is not None:
                    rec["mutated_input"] = json.dumps(src, sort_keys=True) != snapshot
                    try:
                        (out_dir / "json" / f"{design}__{size}.json").write_text(json.dumps(out, indent=1, default=str))
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        ev = evaluate(design, task["source"], out, {"width": W, "height": H},
                                      str(out_dir / "png" / f"{design}__{size}.png"))
                        rec.update(ev)
                        if ev["hard"]:
                            rec["status"] = "hard_fail"
                    except Exception as exc:  # noqa: BLE001
                        rec.update(status="score_error", error=f"{type(exc).__name__}: {str(exc)[:160]}",
                                   trace=traceback.format_exc().splitlines()[-4:])
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
    return f"{engine_key}/{design}: {len(todo)} sizes"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default=",".join(DEFAULT))
    ap.add_argument("--module", default=None, help="extra engine: importable module exposing resize()")
    ap.add_argument("--designs", default="all")
    ap.add_argument("--sizes", default="all")
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    from designs import load_all
    designs = sorted(load_all()) if a.designs == "all" else a.designs.split(",")
    sizes = list(CATALOGUE) if a.sizes == "all" else a.sizes.split(",")
    engines = {k: ENGINES[k] for k in a.engines.split(",") if k}
    if a.module:
        engines[a.module.split(".")[-1]] = a.module
    jobs = [(k, m, d) for k, m in engines.items() for d in designs]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers, max_tasks_per_child=1) as ex:
        futs = [ex.submit(run_pair, k, m, d, sizes, a.timeout, a.force) for k, m, d in jobs]
        for f in as_completed(futs):
            try:
                print(f.result(), f"[{time.time() - t0:.0f}s]", flush=True)
            except Exception as exc:  # noqa: BLE001
                print("WORKER ERROR", type(exc).__name__, exc, flush=True)


if __name__ == "__main__":
    main()
