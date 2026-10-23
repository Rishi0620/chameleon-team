"""OPTIMIZER spike with ONE fix applied from outside: its width/metric/frontier caches are keyed by
id(element dict), which Python reuses after garbage collection -> stale widths for a different string
(see spikes/judge/r2_stale_cache_probe.py). Clearing them per call isolates each solve."""
from . import optimizer as _o

NAME = "optimizer_fixed"


def resize(source, target_canvas):
    for c in (_o._mod._cw, _o._mod._met, _o._mod._wk):
        c.clear()
    return _o.resize(source, target_canvas)
