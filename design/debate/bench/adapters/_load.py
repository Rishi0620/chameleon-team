"""Import a spike module by file path under a unique module name (avoids roles.py name clashes)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SPIKES = ROOT / "design" / "debate" / "spikes"
BENCH_ASSETS = Path(__file__).resolve().parents[1] / "assets"


def load(path: Path, name: str, extra_path: Path | None = None):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if extra_path is not None and str(extra_path) not in sys.path:
        sys.path.insert(0, str(extra_path))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
