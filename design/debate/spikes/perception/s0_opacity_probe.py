"""Spike 0: does the official renderer honour element `opacity` on TEXT?
Renders a white text element with opacity 1.0 / 0.0 and color-alpha 0 on a dark rect,
measures how many pixels in the text box changed vs the empty background."""
import json, sys, io
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from renderer.converter.convert import render_design_to_png

OUT = Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
ASSETS = "brand_kit/assets"

def design(text_el=None, img_op=None):
    els = [{"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 400, "height": 120, "z_index": 0,
            "shape_type": "rectangle", "fill_color": "rgba(40,20,40,1)"}]
    if text_el:
        els.append({"id": "t", "type": "text", "x": 20, "y": 30, "width": 360, "height": 60, "z_index": 2,
                    "content": "Chase the Light", "font_family": "Solstice Serif", "font_size": 40,
                    "font_weight": "bold", "color": "rgba(255,255,255,1)", "text_align": "center", **text_el})
    if img_op is not None:
        els.append({"id": "logo", "type": "image", "x": 20, "y": 10, "width": 360, "height": 100, "z_index": 1,
                    "asset_id": "solstice_logo_lockup.png", "fit": "contain", "opacity": img_op})
    return {"canvas": {"width": 400, "height": 120}, "elements": els}

def lit(name, d):
    p = OUT / f"s0_{name}.png"
    render_design_to_png(d, ASSETS, str(p))
    a = np.asarray(Image.open(p).convert("RGB")).astype(int)
    return a

base = lit("empty", design())
cases = {
    "text_opacity_1": design({"opacity": 1.0}),
    "text_opacity_0": design({"opacity": 0.0}),
    "text_color_alpha_0": design({"color": "rgba(255,255,255,0)"}),
    "text_color_alpha_0.3": design({"color": "rgba(255,255,255,0.3)"}),
    "image_opacity_1": design(img_op=1.0),
    "image_opacity_0": design(img_op=0.0),
}
for k, d in cases.items():
    a = lit(k, d)
    changed = (np.abs(a - base).sum(-1) > 30).sum()
    print(f"{k:22s} changed_pixels={changed:6d}  max_lum={a.max()}")
