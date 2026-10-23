"""INVENTOR spike: spikes/inventor/galley.py -> decompile / solve / emit (top-1)."""
import contextlib
import io

from ._load import BENCH_ASSETS, SPIKES, load

NAME = "galley"
_mod = load(SPIKES / "inventor" / "galley.py", "bench_engine_galley")
_mod.ASSETS = BENCH_ASSETS


def resize(source, target_canvas):
    W, H = int(target_canvas["width"]), int(target_canvas["height"])
    with contextlib.redirect_stdout(io.StringIO()):          # the spike prints its search log
        g = _mod.decompile(source)
        ctx, res = _mod.solve(g, W, H, top_k=3, verbose=False)
        return _mod.emit(g, source, ctx, res[0])
