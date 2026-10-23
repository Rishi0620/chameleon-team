"""Spike r2 (open problem #7): does every engine's 'hide' actually hide? Intended-hidden = opacity 0, or text colour
alpha 0, or z below an opaque full-bleed bg. Pixel-visible = removing it changes the render (r2_critic.measure)."""
import json, sys
from pathlib import Path
HERE = Path(__file__).parent; ROOT = HERE.parents[3]; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from r2_critic import measure
from roles import infer_roles
from renderer.converter.colorutil import parse_rgba
src_txt = (HERE / "r2_cross_engine.py").read_text().split("tasks = set()")[0]
g = {"__file__": str(HERE / "r2_cross_engine.py")}; exec(compile(src_txt, "r2ce", "exec"), g)
tot_hidden = leaks = 0
for (n, W, H) in [(3, 728, 90), (2, 728, 90), (3, 300, 250), (3, 160, 600), (2, 300, 250), (3, 1600, 400), (2, 1600, 400)]:
    src = json.loads((ROOT / f"input/chameleon_sample_{g['LV'][n]}.json").read_text())["source"]; roles = infer_roles(src)
    for eng, d in g["candidates"](n, W, H).items():
        d = g["remap"](src, d); f = measure(d, roles); bgz = min(e.get("z_index", 0) for e in d["elements"])
        for e in d["elements"]:
            intended = e.get("opacity", 1) <= 0.01 or (e["type"] == "text" and parse_rgba(e.get("color"))[3] <= 0.01) or (e.get("z_index", 0) < bgz)
            if intended:
                tot_hidden += 1
                if f["els"][e["id"]].get("visible"): leaks += 1; print(f"LEAK L{n}->{W}x{H} {eng}: {e['id']} intended hidden but visible")
print(f"intended-hidden elements checked: {tot_hidden}; pixel leaks: {leaks}")
