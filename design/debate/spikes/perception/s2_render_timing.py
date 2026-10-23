"""Spike 2: is render-in-the-loop affordable? Time the official renderer per candidate
(cold vs warm, full-res vs downscaled preview, convert vs rasterise), on the 3 baseline outputs."""
import json, sys, time, statistics as st
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT))
import os; os.chdir(ROOT)

t0 = time.perf_counter()
from renderer.converter import convert as C
t_import = time.perf_counter() - t0

ASSETS = "brand_kit/assets"
OUT = Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
designs = {p.stem.replace("chameleon_sample_", "").replace("_output", ""): json.loads(p.read_text())
           for p in sorted(Path("output").glob("*_output.json"))}

def once(d, max_size=None, fmt="png"):
    r = C._get_renderer("brand_kit/fonts")
    t = time.perf_counter(); ex, _ = C.convert_chameleon_to_crello(d, r.font_manager, ASSETS); tc = time.perf_counter() - t
    t = time.perf_counter(); b = r.render(ex, max_size=max_size or 2048, format=fmt); tr = time.perf_counter() - t
    return tc, tr, len(b)

print(f"import renderer: {t_import*1000:.0f} ms")
t = time.perf_counter(); C._get_renderer("brand_kit/fonts"); print(f"first font-manager build: {(time.perf_counter()-t)*1000:.0f} ms")
for name, d in designs.items():
    cw, ch = d["canvas"]["width"], d["canvas"]["height"]
    for ms in (None, 512):
        rows = [once(d, ms) for _ in range(7)]
        tc = st.median(r[0] for r in rows) * 1000; tr = st.median(r[1] for r in rows) * 1000
        print(f"{name:18s} {cw}x{ch} max_size={ms or 'full':>4} n_el={len(d['elements']):2d} "
              f"convert={tc:6.1f} ms  rasterise+encode={tr:6.1f} ms  total={tc+tr:6.1f} ms")
