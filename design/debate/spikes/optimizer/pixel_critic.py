"""Spike: render-in-the-loop pixel critic. For each visible text element, render the
design WITHOUT text (the 'underlay') and measure what the glyphs actually sit on:
WCAG contrast vs. median underlay luminance, and edge density (busy-ness).
Also reports render cost, to size a top-K verification budget."""
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from renderer.converter.convert import render_design_to_png  # noqa: E402

TMP = Path(__file__).resolve().parent / "out" / "_underlay.png"


def rgba(c):
    m = re.match(r"rgba?\(([\d.]+),([\d.]+),([\d.]+)(?:,([\d.]+))?\)", (c or "").replace(" ", ""))
    return (0, 0, 0, 1.0) if not m else (float(m[1]), float(m[2]), float(m[3]), float(m[4] or 1))


def rel_lum(rgb):
    c = np.asarray(rgb, dtype=float) / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def critique(design):
    texts = [e for e in design["elements"] if e["type"] == "text" and rgba(e.get("color"))[3] > 0 and e.get("opacity", 1) > 0]
    under = dict(design, elements=[e for e in design["elements"] if e["type"] != "text"])
    t = time.time()
    render_design_to_png(under, str(ROOT / "brand_kit/assets"), str(TMP))
    dt = time.time() - t
    img = np.asarray(Image.open(TMP).convert("RGB")).astype(float)
    H, W = img.shape[:2]
    lum = rel_lum(img)
    gy, gx = np.gradient(lum)
    edges = np.hypot(gx, gy) > 0.02
    rows = []
    for e in texts:
        x0, y0 = int(max(0, e["x"])), int(max(0, e["y"]))
        x1 = int(min(W, e["x"] + e["width"]))
        y1 = int(min(H, e["y"] + max(e["height"], e["font_size"] * 1.2)))
        if x1 <= x0 or y1 <= y0:
            continue
        bg = float(np.median(lum[y0:y1, x0:x1]))
        fg = float(rel_lum(np.array(rgba(e["color"])[:3])))
        hi, lo = max(bg, fg), min(bg, fg)
        rows.append((e["id"], round((hi + 0.05) / (lo + 0.05), 1), round(float(edges[y0:y1, x0:x1].mean()), 3)))
    return rows, dt


if __name__ == "__main__":
    pairs = [
        ("baseline L2", ROOT / "output/chameleon_sample_level2_core_output.json"),
        ("optimizer L2", ROOT / "design/debate/spikes/optimizer/out/L2_1600x400.json"),
        ("baseline L3", ROOT / "output/chameleon_sample_level3_advanced_output.json"),
        ("optimizer L3", ROOT / "design/debate/spikes/optimizer/out/L3_728x90.json"),
    ]
    for name, p in pairs:
        rows, dt = critique(json.loads(p.read_text()))
        worst = min(rows, key=lambda r: r[1])
        busiest = max(rows, key=lambda r: r[2])
        print(f"{name:13s} underlay render {dt * 1000:.0f}ms | min contrast {worst[1]}:1 ({worst[0]}) | max edge density {busiest[2]} ({busiest[0]})")
        for r in rows:
            print(f"    {r[0]:14s} contrast {r[1]:5.1f}:1  edges {r[2]:.3f}")
