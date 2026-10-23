"""OPTIMIZER spike: spikes/optimizer/solver.py -> solve(src, W, H)[0]."""
from ._load import BENCH_ASSETS, SPIKES, load

NAME = "optimizer"
_mod = load(SPIKES / "optimizer" / "solver.py", "bench_engine_optimizer")
_mod.ASSETS = BENCH_ASSETS


def resize(source, target_canvas):
    out = _mod.solve(source, int(target_canvas["width"]), int(target_canvas["height"]))[0]
    return out
