"""CHAMELEON merged prototype: the bracketed galley (owner of this file: OPTIMIZER).

    from design.debate.proto import resize
    out = resize(source, {"width": 728, "height": 90})
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from .engine import resize, resize_with_info  # noqa: E402,F401
