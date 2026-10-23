"""Shared paths + render helpers for the bench (official renderer code path, bench asset dir)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BENCH = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ASSETS = str(BENCH / "assets")            # brand_kit/assets copies + 2 generated test assets
FONTS = str(ROOT / "brand_kit" / "fonts")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from renderer.converter.convert import (  # noqa: E402
    _get_renderer, convert_chameleon_to_crello, render_design_to_png)


def renderer():
    return _get_renderer(FONTS)


def render_png(design: dict, path: str, max_size: int | None = None) -> list[str]:
    return render_design_to_png(design, ASSETS, path, fonts_dir=FONTS, max_size=max_size)


def render_rgba(design: dict, transparent: bool = False, max_size: int = 2048) -> np.ndarray:
    """Render through the official converter + CrelloV5Renderer; returns HxWx4 uint8."""
    r = renderer()
    example, _ = convert_chameleon_to_crello(design, r.font_manager, ASSETS)
    import skia
    data = r.render(example, max_size=max_size, format="png",
                    canvas_color=None if transparent else skia.ColorWHITE)
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))
