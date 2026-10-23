"""The starter repo's uniform stretch (engine/resize.py), unmodified."""
from ._load import ROOT, load

NAME = "baseline_stretch"
_mod = load(ROOT / "engine" / "resize.py", "bench_engine_baseline")


def resize(source, target_canvas):
    return _mod.resize(source, target_canvas)
