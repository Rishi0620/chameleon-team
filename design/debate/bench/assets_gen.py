"""Build bench/assets: copies of brand_kit/assets + two procedurally generated test assets.

- bench_photo_busy.png  1600x1200 RGB: calm sky-like top third, high-frequency 'foliage'
  texture with bright/dark speckle below (stands in for a photo; text over the bottom must lose).
- bench_can.png         600x800 RGBA: a second product (can) with transparent padding.
Generated, never 'redrawn' engine output - these are TEST INPUTS only.
Run from repo root: .venv/bin/python design/debate/bench/assets_gen.py
"""
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "assets"


def busy_photo(w=1600, h=1200, seed=7):
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, h)[:, None]
    sky = np.stack([180 - 60 * y, 200 - 50 * y, 235 - 40 * y], axis=2) * np.ones((1, w, 1))
    noise = rng.normal(0, 1, (h // 4, w // 4, 3))
    noise = np.asarray(Image.fromarray(((noise - noise.min()) / np.ptp(noise) * 255).astype(np.uint8))
                       .resize((w, h), Image.BICUBIC)).astype(float)
    fine = rng.integers(0, 255, (h, w, 3)).astype(float)
    foliage = 0.55 * noise * np.array([0.45, 0.8, 0.35]) + 0.45 * fine * np.array([0.5, 0.6, 0.3])
    mask = np.clip((y - 0.33) * 6, 0, 1)[:, :, None]           # calm top third, busy below
    img = sky * (1 - mask) + foliage * mask
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    for _ in range(140):                                          # bright/dark blobs ("flowers", "shadows")
        cx, cy = rng.integers(0, w), rng.integers(int(h * 0.4), h)
        r = int(rng.integers(6, 28))
        col = tuple(int(c) for c in (rng.choice([[250, 240, 120], [30, 40, 25], [240, 90, 90]])))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    return im.filter(ImageFilter.GaussianBlur(0.6))


def can(w=600, h=800):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([170, 120, 430, 700], radius=40, fill=(40, 120, 170, 255))
    d.rectangle([170, 330, 430, 470], fill=(250, 245, 230, 255))
    d.ellipse([170, 95, 430, 150], fill=(200, 205, 210, 255))
    d.ellipse([200, 380, 400, 420], fill=(232, 106, 58, 255))
    return im


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for p in (ROOT / "brand_kit" / "assets").glob("*"):
        shutil.copy2(p, OUT / p.name)
    busy_photo().save(OUT / "bench_photo_busy.png")
    can().save(OUT / "bench_can.png")
    print(sorted(x.name for x in OUT.iterdir()))
