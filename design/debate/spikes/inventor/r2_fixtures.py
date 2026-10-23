"""R2 test fixtures for topologies GALLEY v1 cannot express.

Writes a private assets dir (copies of the brand assets + ONE synthetic test photo) under
spikes/inventor/r2_assets/ -- brand_kit/ is never touched.  The photo is a procedural
'landscape' (smooth sky over a busy textured ground) used only as a test input.

F1  photo-overlay: full-bleed busy photo, copy stack set in the calm sky, logo in a corner.
F2  split colour block: an opaque full-height panel holding logo+copy+CTA, product on the right.
"""
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ASSETS2 = HERE / "r2_assets"


def build_assets():
    ASSETS2.mkdir(exist_ok=True)
    for f in (ROOT / "brand_kit" / "assets").iterdir():
        if f.suffix == ".png" and not (ASSETS2 / f.name).exists():
            shutil.copy(f, ASSETS2 / f.name)
    p = ASSETS2 / "r2_photo_landscape.png"
    if p.exists():
        return
    W, H = 1600, 1200
    rng = np.random.default_rng(7)
    y = np.linspace(0, 1, H)[:, None]
    sky_top, sky_bot = np.array([38, 52, 104]), np.array([236, 160, 118])
    img = (sky_top + (sky_bot - sky_top) * (y / 0.45).clip(0, 1)[..., None]) * np.ones((H, W, 1))
    # busy ground below the horizon: noise + stripes + 'trees'
    horizon = int(0.45 * H)
    ground = rng.integers(0, 90, size=(H - horizon, W, 1)) + np.array([30, 70, 35])
    stripes = (np.sin(np.linspace(0, 260, W))[None, :, None] * 35).astype(int)
    img[horizon:] = (ground + stripes).clip(0, 255)
    im = Image.fromarray(img.astype(np.uint8), "RGB")
    d = ImageDraw.Draw(im)
    for _ in range(140):
        x0 = int(rng.integers(0, W)); y0 = int(rng.integers(horizon - 40, H))
        s = int(rng.integers(20, 90))
        d.polygon([(x0, y0 - s), (x0 - s // 2, y0 + s // 2), (x0 + s // 2, y0 + s // 2)],
                  fill=tuple(int(v) for v in rng.integers(10, 70, 3)))
    d.ellipse([1150, 330, 1290, 470], fill=(255, 226, 150))           # low sun near the horizon
    im.save(p)


F1 = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "p0", "type": "image", "x": 0, "y": 0, "width": 1080, "height": 1080, "z_index": 0,
         "asset_id": "r2_photo_landscape.png", "fit": "cover"},
        {"id": "p1", "type": "text", "x": 80, "y": 90, "width": 640, "height": 160, "z_index": 2,
         "content": "Taste the last light of summer.", "font_family": "Solstice Serif", "font_size": 64,
         "font_weight": "bold", "color": "rgba(255,255,255,1)", "text_align": "left"},
        {"id": "p2", "type": "text", "x": 80, "y": 270, "width": 600, "height": 40, "z_index": 2,
         "content": "Limited-batch botanical spritz, out now.", "font_family": "Solstice Sans",
         "font_size": 28, "color": "rgba(255,255,255,0.9)", "text_align": "left"},
        {"id": "p3", "type": "shape", "x": 80, "y": 340, "width": 260, "height": 72, "z_index": 2,
         "shape_type": "rectangle", "fill_color": "rgba(232,106,58,1)", "corner_radius": 36, "group_id": "q"},
        {"id": "p4", "type": "text", "x": 80, "y": 359, "width": 260, "height": 34, "z_index": 3,
         "content": "Shop now", "font_family": "Solstice Sans", "font_size": 26, "font_weight": "bold",
         "color": "rgba(255,255,255,1)", "text_align": "center", "group_id": "q"},
        {"id": "p5", "type": "image", "x": 800, "y": 960, "width": 240, "height": 80, "z_index": 2,
         "asset_id": "solstice_logo_lockup.png", "fit": "contain"},
    ],
}

F2 = {
    "canvas": {"width": 1200, "height": 628},
    "elements": [
        {"id": "s0", "type": "image", "x": 0, "y": 0, "width": 1200, "height": 628, "z_index": 0,
         "asset_id": "solstice_bg_gradient.png", "fit": "cover"},
        {"id": "s1", "type": "shape", "x": 0, "y": 0, "width": 560, "height": 628, "z_index": 1,
         "shape_type": "rectangle", "fill_color": "rgba(43,27,46,1)"},
        {"id": "s2", "type": "image", "x": 60, "y": 60, "width": 210, "height": 70, "z_index": 2,
         "asset_id": "solstice_logo_lockup.png", "fit": "contain"},
        {"id": "s3", "type": "text", "x": 60, "y": 190, "width": 440, "height": 130, "z_index": 2,
         "content": "Golden hour, bottled.", "font_family": "Solstice Serif", "font_size": 54,
         "font_weight": "bold", "color": "rgba(255,255,255,1)", "text_align": "left",
         "style_runs": [{"start": 13, "end": 21, "color": "rgba(240,178,66,1)"}]},
        {"id": "s4", "type": "text", "x": 60, "y": 350, "width": 440, "height": 70, "z_index": 2,
         "content": "Four new botanical infusions, in stores this June.", "font_family": "Solstice Sans",
         "font_size": 24, "color": "rgba(255,255,255,0.85)", "text_align": "left"},
        {"id": "s5", "type": "shape", "x": 60, "y": 470, "width": 240, "height": 66, "z_index": 2,
         "shape_type": "rectangle", "fill_color": "rgba(232,106,58,1)", "corner_radius": 33, "group_id": "k"},
        {"id": "s6", "type": "text", "x": 60, "y": 487, "width": 240, "height": 32, "z_index": 3,
         "content": "Find a store", "font_family": "Solstice Sans", "font_size": 24, "font_weight": "bold",
         "color": "rgba(255,255,255,1)", "text_align": "center", "group_id": "k"},
        {"id": "s7", "type": "image", "x": 640, "y": 40, "width": 520, "height": 548, "z_index": 2,
         "asset_id": "solstice_bottle.png", "fit": "contain"},
    ],
}

if __name__ == "__main__":
    build_assets()
    print("assets ->", ASSETS2)
