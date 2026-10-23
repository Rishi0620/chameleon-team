"""Spike 3: where is the background calm enough for text, and what contrast will brand text colours get?
Replicates the renderer's cover crop exactly (assets._fit_image) for each target canvas, then computes
 - busyness = local luminance std (window ~ text x-height) + edge density (|grad| > thr)
 - WCAG contrast of the 3 brand text colours vs the local mean luminance (worst case = brightest dot)
Writes heatmaps to out/."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT))
from renderer.converter.assets import _fit_image

OUT = Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
BG = Image.open(ROOT / "brand_kit/assets/solstice_bg_gradient.png").convert("RGBA")

def srgb_lin(c):
    c = c / 255.0
    return np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def rel_lum(rgb):
    l = srgb_lin(rgb.astype(np.float64))
    return 0.2126 * l[..., 0] + 0.7152 * l[..., 1] + 0.0722 * l[..., 2]

def contrast(l1, l2):
    hi, lo = np.maximum(l1, l2), np.minimum(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

def box_mean(a, r):
    # integral-image box filter, window (2r+1)^2
    p = np.pad(a, r + 1, mode="edge").cumsum(0).cumsum(1)
    k = 2 * r + 1
    s = p[k:, k:] - p[:-k, k:] - p[k:, :-k] + p[:-k, :-k]
    return s[: a.shape[0], : a.shape[1]] / (k * k)

TEXT = {"white": (255, 255, 255), "gold": (240, 178, 66), "orange": (232, 106, 58), "plum": (43, 27, 46)}

for (cw, ch) in [(1080, 1080), (1080, 1350), (1600, 400), (728, 90)]:
    crop = np.asarray(_fit_image(BG, cw, ch, "cover"))[..., :3].astype(np.float64)
    L = rel_lum(crop)
    gray = crop.mean(-1)
    r = max(3, round(min(cw, ch) * 0.02))
    mu = box_mean(gray, r); var = np.maximum(box_mean(gray ** 2, r) - mu ** 2, 0); std = np.sqrt(var)
    gy, gx = np.gradient(gray); edges = (np.hypot(gx, gy) > 6).astype(float)
    edge_den = box_mean(edges, r)
    busy = 0.5 * np.clip(std / 25, 0, 1) + 0.5 * np.clip(edge_den / 0.15, 0, 1)
    calm_frac = (busy < 0.15).mean()
    print(f"\n== cover-crop to {cw}x{ch}: lum range {L.min():.3f}-{L.max():.3f}  mean {L.mean():.3f}  "
          f"busy p50={np.median(busy):.3f} p95={np.percentile(busy,95):.3f}  calm(<0.15) area={calm_frac:.1%}")
    Lloc = rel_lum(np.stack([box_mean(crop[..., i], r) for i in range(3)], -1))
    for name, c in TEXT.items():
        lt = rel_lum(np.array(c, float)[None, None, :])[0, 0]
        cr_local = contrast(lt, Lloc); cr_worst = contrast(lt, L)
        print(f"   {name:6s} vs local-mean bg: min={cr_local.min():5.2f} median={np.median(cr_local):5.2f}  "
              f"| vs brightest pixel (dot): {cr_worst.min():5.2f}   WCAG-AA(4.5) pass area={(cr_local>=4.5).mean():.0%}")
    hm = (np.clip(busy, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(hm).save(OUT / f"s3_busy_{cw}x{ch}.png")
