"""Spike 4a: run the pixel critic on (a) each SOURCE design at its source size and (b) the naive
uniform-stretch baseline outputs. The critic should find the source clean-ish and the baseline broken."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from critic import critique, ROOT
for p in sorted((ROOT / "input").glob("*.json")):
    task = json.loads(p.read_text())
    base = json.loads((ROOT / "output" / f"{p.stem}_output.json").read_text())
    roles = {"background": ["bg"], "decoration": ["deco_circle_1", "deco_circle_2"]}  # spike only; engine infers these
    for tag, d in (("SOURCE", task["source"]), ("BASELINE", base)):
        m, _ = critique(d, roles)
        print(f"\n[{p.stem.split('_')[2]} {tag} {d['canvas']['width']}x{d['canvas']['height']}] penalty={m['penalty']} "
              f"render+critic={m['critic_ms']}ms")
        for k, v in m.items():
            if k.endswith(("contrast_p10", "xheight_px")): print(f"     {k}={v}", end="")
        print()
        for s in m["issues"]: print("   -", s)
