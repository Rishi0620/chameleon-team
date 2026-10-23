"""Synthesise a photo-like BUSY test asset (test fixture only, not engine output).
Top 35% = calm sky gradient, bottom 65% = high-frequency 'foliage' texture."""
import numpy as np
from PIL import Image, ImageFilter
rng = np.random.default_rng(3)
W, H = 1600, 1067
y = np.linspace(0, 1, H)[:, None]
sky = np.stack([200 - 80*y, 170 - 60*y, 230 - 40*y], -1) * np.ones((H, W, 1))
noise = rng.normal(0, 1, (H // 4, W // 4, 3))
tex = np.array(Image.fromarray(((noise - noise.min()) / np.ptp(noise) * 255).astype("uint8")).resize((W, H), Image.BICUBIC)).astype(float)
foliage = np.stack([40 + 0.5*tex[..., 0], 70 + 0.6*tex[..., 1], 30 + 0.3*tex[..., 2]], -1)
# sharp highlights (leaves / bokeh)
for _ in range(900):
    cx, cy, r = rng.integers(0, W), rng.integers(int(0.3*H), H), rng.integers(3, 18)
    yy, xx = np.ogrid[-cy:H-cy, -cx:W-cx]
    m = xx*xx + yy*yy <= r*r
    foliage[m] = rng.integers(150, 255, 3)
horizon = (0.35 + 0.05*np.sin(np.linspace(0, 9, W)))[None, :]
mask = (y > horizon)[..., None]
img = np.where(mask, foliage, sky).clip(0, 255).astype("uint8")
Image.fromarray(img).save("design/debate/spikes/designer/r2_assets/r2_busy_photo.jpg".replace(".jpg", ".png"))
print("ok")
