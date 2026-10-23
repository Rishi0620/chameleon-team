"""PERCEPTION spike: the render-in-the-loop STRIP generator of spikes/perception/s4b_render_in_loop.py.

s4b is a script (its experiment loop runs at import), so we exec only its definitions
(everything above the `for task_file in` loop) and re-create its selection loop verbatim:
infer roles -> enumerate the 72-candidate grid -> render + critique each -> lowest penalty wins.
The generator only knows ONE archetype (a horizontal strip), so the bench applies it only to
banner-shaped targets (W/H >= 2.5); other sizes are reported as 'n/a', not as failures."""
import itertools
import sys
import types

from ._load import BENCH_ASSETS, SPIKES

NAME = "perception_strip"
_dir = SPIKES / "perception"
sys.path.insert(0, str(_dir))
import critic as _critic  # noqa: E402
import roles as _roles  # noqa: E402

_critic.ASSETS = str(BENCH_ASSETS)
_roles.ASSETS = BENCH_ASSETS
_src = (_dir / "s4b_render_in_loop.py").read_text()
_mod = types.ModuleType("bench_engine_perception")
_mod.__file__ = str(_dir / "s4b_render_in_loop.py")
exec(compile(_src.split("\nfor task_file in")[0], _mod.__file__, "exec"), _mod.__dict__)

GRID = dict(hero=[False, True], sub=[False, True], badge=[False, True], logo_h=[0.6, 0.9],
            align=["left", "center"], cta_fs=[0.7, 1.0, 1.4])


def applies(W, H):
    return W / H >= 2.5


def resize(source, target_canvas):
    roles = _mod.infer_roles(source)
    deco = {"decoration": [k for k, v in roles.items() if v == "decoration"],
            "background": [k for k, v in roles.items() if v == "background"]}
    src_m, _ = _mod.critique(source, deco)
    best = None
    for vals in itertools.product(*GRID.values()):
        opt = dict(zip(GRID, vals))
        if opt["badge"] and not opt["hero"]:
            continue
        d = _mod.strip(source, dict(target_canvas), roles, opt)
        m, _img = _mod.critique(d, deco)
        p, _why = _mod.score(m, src_m, d, roles)
        if best is None or p < best[0]:
            best = (p, d)
    return best[1]
