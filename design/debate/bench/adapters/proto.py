"""Round-4 adapter: the merged prototype `design.debate.proto.engine.resize` (owner: OPTIMIZER).

Imported lazily so the bench works before the prototype exists (the runner then records an
import 'crash' per case instead of dying). Per proto/INTERFACES.md:
    resize(source, target_canvas, assets_dir=None) -> dict      (never raises, by contract)
    engine.HIDE_MODE in {"alpha", "z_under_bg", "never_text"}    (default "alpha")
    engine.DISJOINT_BOXES, engine.TOP_K
We pass the bench asset dir explicitly (brand_kit copies + bench_photo_busy.png + bench_can.png).
Variants for the hide-policy A/B live in proto_zunder.py / proto_nevertext.py; any switch can also
be forced with env BENCH_PROTO_HIDE_MODE / BENCH_PROTO_DISJOINT / BENCH_PROTO_TOP_K.
"""
from __future__ import annotations

import importlib
import os

from ._load import BENCH_ASSETS, ROOT  # noqa: F401  (puts the repo root on sys.path)

NAME = "proto"
HIDE_MODE: str | None = None          # subclasses (variant adapters) override
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        os.chdir(ROOT)                                    # proto resolves paths from the repo root
        _engine = importlib.import_module("design.debate.proto.engine")
    return _engine


def configure(hide_mode: str | None = None) -> None:
    eng = _get_engine()
    mode = os.environ.get("BENCH_PROTO_HIDE_MODE") or hide_mode
    if mode:
        eng.HIDE_MODE = mode
    if os.environ.get("BENCH_PROTO_DISJOINT") is not None:
        eng.DISJOINT_BOXES = os.environ["BENCH_PROTO_DISJOINT"] not in ("0", "false", "False")
    if os.environ.get("BENCH_PROTO_TOP_K"):
        eng.TOP_K = int(os.environ["BENCH_PROTO_TOP_K"])


def resize(source, target_canvas, hide_mode: str | None = None):
    configure(hide_mode or HIDE_MODE)
    return _get_engine().resize(source, dict(target_canvas), assets_dir=str(BENCH_ASSETS))
