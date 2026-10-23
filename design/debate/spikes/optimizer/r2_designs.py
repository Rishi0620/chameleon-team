"""Round-2 test designs with OPAQUE ids that neither GALLEY nor OPTIMIZER was tuned on.

  S  "split"  1080x1080: opaque plum colour-block panel on the left half carrying WHITE copy
             (logo, headline, subhead, CTA pill); product on the cream right half; dark fine print
             on cream. The panel is an ungrouped shape -> the container relation is implicit.
  B  "busy"   1200x628: full-bleed busy photo-like background (generated bokeh/foliage texture,
             written to r2_kit/assets/), copy sits on a translucent dark scrim card (ungrouped) placed
             over the photo; product on the right over the busy region.
  U  inventor's unseen split link-ad (imported from spikes/inventor/unseen.py) for reference.

r2_kit/ = copies of brand_kit/{assets,fonts} + the generated photo (brand_kit is never modified).
Run: .venv/bin/python design/debate/spikes/optimizer/r2_designs.py   (renders sources)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ASSETS2 = HERE / "r2_kit" / "assets"   # fonts are copied to r2_kit/fonts (renderer looks next to assets)
OUT = HERE / "r2_out"


def build_assets():
    ASSETS2.mkdir(parents=True, exist_ok=True)
    (ASSETS2.parent / "fonts").mkdir(exist_ok=True)
    for sub, dst in (("assets", ASSETS2), ("fonts", ASSETS2.parent / "fonts")):
        for p in (ROOT / "brand_kit" / sub).iterdir():
            if p.is_file() and not (dst / p.name).exists():
                shutil.copy(p, dst / p.name)
    photo = ASSETS2 / "r2_busy_photo.png"
    if photo.exists():
        return
    rng = np.random.default_rng(7)
    W, H = 1600, 1000
    yy, xx = np.mgrid[0:H, 0:W]
    base = np.stack([90 + 60 * xx / W, 70 + 50 * yy / H, 60 + 40 * (1 - xx / W)], -1)
    im = Image.fromarray(base.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(900):  # foliage strokes
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        L = rng.uniform(20, 120)
        a = rng.uniform(0, np.pi)
        c = tuple(int(v) for v in rng.integers(30, 200, 3)) + (200,)
        d.line([x, y, x + L * np.cos(a), y + L * np.sin(a)], fill=c, width=int(rng.integers(3, 12)))
    for _ in range(260):  # bokeh
        x, y, r = rng.uniform(0, W), rng.uniform(0, H), rng.uniform(8, 60)
        c = tuple(int(v) for v in rng.integers(150, 255, 3)) + (int(rng.integers(90, 200)),)
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    im.save(photo)


SPLIT = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "q0", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "z_index": 0,
         "shape_type": "rectangle", "fill_color": "rgba(246,236,222,1)"},
        {"id": "q1", "type": "shape", "x": 0, "y": 0, "width": 500, "height": 1080, "z_index": 1,
         "shape_type": "rectangle", "fill_color": "rgba(43,27,46,1)"},
        {"id": "q2", "type": "image", "x": 60, "y": 70, "width": 300, "height": 100, "z_index": 3,
         "asset_id": "solstice_logo_lockup.png", "fit": "contain"},
        {"id": "q3", "type": "text", "x": 60, "y": 300, "width": 400, "height": 200, "z_index": 3,
         "content": "Bottled at golden hour", "font_family": "Solstice Serif", "font_size": 60,
         "font_weight": "bold", "color": "rgba(255,255,255,1)", "text_align": "left",
         "style_runs": [{"start": 11, "end": 21, "color": "rgba(240,178,66,1)"}]},
        {"id": "q4", "type": "text", "x": 60, "y": 560, "width": 380, "height": 120, "z_index": 3,
         "content": "Small-batch sparkling botanicals with blood orange and wild honey.",
         "font_family": "Solstice Sans", "font_size": 24, "color": "rgba(255,255,255,0.85)", "text_align": "left"},
        {"id": "q5", "type": "shape", "x": 60, "y": 760, "width": 300, "height": 80, "z_index": 2,
         "shape_type": "rectangle", "fill_color": "rgba(232,106,58,1)", "corner_radius": 40, "group_id": "k9"},
        {"id": "q6", "type": "text", "x": 60, "y": 782, "width": 300, "height": 36, "z_index": 3,
         "content": "Shop now", "font_family": "Solstice Sans", "font_size": 26, "font_weight": "bold",
         "color": "rgba(255,255,255,1)", "text_align": "center", "group_id": "k9"},
        {"id": "q7", "type": "image", "x": 540, "y": 220, "width": 520, "height": 520, "z_index": 2,
         "asset_id": "solstice_bottle.png", "fit": "contain"},
        {"id": "q8", "type": "text", "x": 560, "y": 960, "width": 480, "height": 40, "z_index": 3,
         "content": "Available at select retailers.", "font_family": "Solstice Sans", "font_size": 20,
         "color": "rgba(43,27,46,1)", "text_align": "center"},
    ],
}

BUSY = {
    "canvas": {"width": 1200, "height": 628},
    "elements": [
        {"id": "p0", "type": "image", "x": 0, "y": 0, "width": 1200, "height": 628, "z_index": 0,
         "asset_id": "r2_busy_photo.png", "fit": "cover"},
        {"id": "p1", "type": "shape", "x": 40, "y": 130, "width": 640, "height": 370, "z_index": 1,
         "shape_type": "rectangle", "fill_color": "rgba(20,12,24,0.78)", "corner_radius": 24},
        {"id": "p2", "type": "image", "x": 70, "y": 160, "width": 210, "height": 70, "z_index": 3,
         "asset_id": "solstice_logo_lockup.png", "fit": "contain"},
        {"id": "p3", "type": "text", "x": 74, "y": 250, "width": 580, "height": 70, "z_index": 3,
         "content": "Nights made golden.", "font_family": "Solstice Serif", "font_size": 54,
         "font_weight": "bold", "color": "rgba(255,255,255,1)", "text_align": "left"},
        {"id": "p4", "type": "text", "x": 74, "y": 330, "width": 580, "height": 36, "z_index": 3,
         "content": "Botanical sparkling, poured after dark.", "font_family": "Solstice Sans",
         "font_size": 24, "color": "rgba(255,255,255,0.9)", "text_align": "left"},
        {"id": "p5", "type": "shape", "x": 74, "y": 395, "width": 230, "height": 66, "z_index": 2,
         "shape_type": "rectangle", "fill_color": "rgba(232,106,58,1)", "corner_radius": 33, "group_id": "m3"},
        {"id": "p6", "type": "text", "x": 74, "y": 413, "width": 230, "height": 32, "z_index": 3,
         "content": "Find a bar", "font_family": "Solstice Sans", "font_size": 24, "font_weight": "bold",
         "color": "rgba(255,255,255,1)", "text_align": "center", "group_id": "m3"},
        {"id": "p7", "type": "image", "x": 720, "y": 70, "width": 480, "height": 480, "z_index": 2,
         "asset_id": "solstice_bottle.png", "fit": "contain"},
    ],
}


def unseen():
    sys.path.insert(0, str(ROOT / "design/debate/spikes/inventor"))
    import importlib
    mod = importlib.import_module("unseen")
    return mod.design


DESIGNS = {"S": SPLIT, "B": BUSY}

if __name__ == "__main__":
    build_assets()
    OUT.mkdir(exist_ok=True)
    sys.path.insert(0, str(ROOT))
    from renderer.converter.convert import render_design_to_png
    for k, d in DESIGNS.items():
        render_design_to_png(d, str(ASSETS2), str(OUT / f"{k}_source.png"))
        print("rendered", OUT / f"{k}_source.png")
