"""Spike: how can an element be 'dropped' honestly, given ids can't be removed?
Renders the same text/shape/image with opacity 0 and with a transparent colour."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from renderer.converter.convert import render_design_to_png  # noqa: E402
import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
base = {"id": "t", "type": "text", "x": 10, "y": 10, "width": 380, "height": 60, "content": "HIDE ME",
        "font_family": "Solstice Sans", "font_size": 40, "font_weight": "bold", "color": "rgba(20,20,20,1)"}
cases = {
    "text_opacity0": dict(base, opacity=0),
    "text_visible": dict(base),
    "text_coloralpha0": dict(base, color="rgba(20,20,20,0)", opacity=0),
    "shape_opacity0": {"id": "s", "type": "shape", "x": 10, "y": 10, "width": 380, "height": 60, "shape_type": "rectangle",
                        "fill_color": "rgba(232,106,58,1)", "opacity": 0},
    "image_opacity0": {"id": "i", "type": "image", "x": 10, "y": 10, "width": 380, "height": 60,
                        "asset_id": "solstice_logo_lockup.png", "opacity": 0},
    "missing_opacity0": {"id": "m", "type": "image", "x": 10, "y": 10, "width": 380, "height": 60,
                          "asset_id": "nope.png", "opacity": 0},
}
for name, el in cases.items():
    d = {"canvas": {"width": 400, "height": 80}, "elements": [el]}
    p = OUT / f"hide_{name}.png"
    render_design_to_png(d, str(ROOT / "brand_kit/assets"), str(p))
    a = np.asarray(Image.open(p).convert("RGB")).astype(int)
    print(f"{name:20s} non-white pixels: {(a.sum(axis=2) < 760).sum()}")
