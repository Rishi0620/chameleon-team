"""R2 spike: run OPTIMIZER's solver and INVENTOR's GALLEY on the same UNSEEN design
(the 1200x628 split 'link ad' from unseen.py, opaque ids, left-aligned copy) and on
the r2 topology fixtures, render both, and put them side by side.

Run from repo root:  .venv/bin/python design/debate/spikes/inventor/r2_vs_optimizer.py
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import galley as G  # noqa: E402
from unseen import design as UNSEEN  # noqa: E402

spec = importlib.util.spec_from_file_location("opt_solver", ROOT / "design/debate/spikes/optimizer/solver.py")
OPT = importlib.util.module_from_spec(spec)
sys.modules["opt_solver"] = OPT          # dataclasses need the module registered
spec.loader.exec_module(OPT)

OUT = HERE / "out_r2"
OUT.mkdir(exist_ok=True)
TARGETS = [(1080, 1920), (1080, 1080), (728, 90), (1600, 400), (300, 250), (160, 600)]


def run_galley(src, W, H):
    g = G.decompile(src)
    ctx, res = G.solve(g, W, H, verbose=False)
    out = G.emit(g, src, ctx, res[0])
    return out, G.render_struct(res[0][2], res[0][3])


def run_opt(src, W, H):
    out, best, atoms, top = OPT.solve(src, W, H)
    desc = "FALLBACK" if best.get("fallback") else OPT.describe_sol(best)
    return out, desc


def main(design=UNSEEN, tag="U"):
    names, log = [], []
    for W, H in TARGETS:
        for who, fn in (("galley", run_galley), ("optimizer", run_opt)):
            t = time.time()
            try:
                out, desc = fn(design, W, H)
            except Exception as ex:  # noqa: BLE001 -- spike: record crashes honestly
                log.append(f"{tag} {W}x{H} {who}: CRASH {type(ex).__name__}: {ex}")
                print(log[-1])
                continue
            dt = time.time() - t
            name = f"{tag}_{W}x{H}_{who}"
            (OUT / f"{name}.json").write_text(json.dumps(out, indent=1))
            G.render_design_to_png(out, str(G.ASSETS), str(OUT / f"{name}.png"))
            bad = G.bounds_report(out)
            log.append(f"{tag} {W}x{H} {who:9s} {dt:5.2f}s off={bad} :: {desc}")
            print(log[-1])
            names.append(name)
    (OUT / f"{tag}_vs_optimizer_log.txt").write_text("\n".join(log) + "\n")
    # contact sheet into out_r2
    G.OUT, old = OUT, G.OUT
    try:
        G.contact_sheet(names, OUT / f"sheet_{tag}_galley_vs_optimizer.png", width=1500)
    finally:
        G.OUT = old


if __name__ == "__main__":
    main()
