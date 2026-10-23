"""DESIGNER spike: spikes/designer/compose.py -> compose({source, target_canvas})[0]."""
import os

from ._load import BENCH_ASSETS, ROOT, SPIKES, load

NAME = "designer"
os.chdir(ROOT)                                   # compose.py loads fonts via a cwd-relative path
_mod = load(SPIKES / "designer" / "compose.py", "bench_engine_designer", extra_path=SPIKES / "designer")
_mod.ASSETS = str(BENCH_ASSETS)


def resize(source, target_canvas):
    design, _arche = _mod.compose({"source": source, "target_canvas": dict(target_canvas)})
    return design
