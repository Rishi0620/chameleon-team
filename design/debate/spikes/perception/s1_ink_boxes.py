"""Spike 1: 'ink boxes' - the real visual extent of each brand asset vs its pixel box,
plus a cheap role fingerprint (alpha coverage, colourfulness, # connected blobs, aspect)."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parents[4] / "brand_kit" / "assets"

def ink_bbox(alpha, thr=8):
    ys, xs = np.nonzero(alpha > thr)
    if len(xs) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1

def blobs(mask):
    # tiny 4-connected component count without scipy
    h, w = mask.shape
    seen = np.zeros_like(mask, bool); n = 0
    sm = mask[::4, ::4]; seen = np.zeros_like(sm, bool); H, W = sm.shape
    for y in range(H):
        for x in range(W):
            if sm[y, x] and not seen[y, x]:
                n += 1; stack = [(y, x)]; seen[y, x] = True
                while stack:
                    cy, cx = stack.pop()
                    for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
                        ny, nx = cy+dy, cx+dx
                        if 0 <= ny < H and 0 <= nx < W and sm[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True; stack.append((ny, nx))
    return n

for p in sorted(ASSETS.glob("*.png")):
    im = Image.open(p)
    rgba = np.asarray(im.convert("RGBA")).astype(np.float32)
    h, w = rgba.shape[:2]
    has_alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
    a = rgba[..., 3]
    bb = ink_bbox(a) if has_alpha else (0, 0, w, h)
    x0, y0, x1, y1 = bb
    cov = (a > 8).mean()
    fill_in_bb = (a[y0:y1, x0:x1] > 8).mean()
    rgb = rgba[..., :3][a > 8]
    sat = (rgb.max(1) - rgb.min(1)).mean() / 255 if len(rgb) else 0
    white_frac = ((rgb.min(1) > 230).mean()) if len(rgb) else 0
    print(f"{p.name:28s} {w}x{h} alpha={has_alpha} ink_bbox={bb} "
          f"ink_wh=({x1-x0},{y1-y0}) ink_frac_w={(x1-x0)/w:.2f} ink_frac_h={(y1-y0)/h:.2f} "
          f"ink_centre_off=({((x0+x1)/2-w/2)/w:+.3f},{((y0+y1)/2-h/2)/h:+.3f}) "
          f"coverage={cov:.2f} fill_in_inkbox={fill_in_bb:.2f} sat={sat:.2f} white_ink={white_frac:.2f} "
          f"blobs={blobs(a > 8) if has_alpha else 1}")
