"""Render critic-vs-bench disagreement cases for eyeballing (owner: PERCEPTION)."""
import json, sys, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT))
BENCH = ROOT / "design/debate/bench"; sys.path.insert(0, str(BENCH))
from design.debate.proto import critic as K
from designs import load_all
from catalogue import CATALOGUE
from adapters import designer as DES
from PIL import Image, ImageDraw
spec = importlib.util.spec_from_file_location("vb", Path(__file__).parent / "critic_vs_bench.py")
code = (Path(__file__).parent / "critic_vs_bench.py").read_text().split("stored = {}")[0]
g = {"__file__": str(Path(__file__).parent / "critic_vs_bench.py")}; exec(compile(code, "vb", "exec"), g)
cases = [a.split("@") for a in sys.argv[1:]]
tiles = []
for name, size in cases:
    src = load_all()[name]["source"]; W, H = CATALOGUE[size]
    out = DES.resize(src, {"width": W, "height": H}); info = g["info_for"](src)
    info["hidden"] = [e["id"] for e in out["elements"] if float(e.get("opacity", 1)) <= 0.01]
    r = K.critique(src, out, info)
    img = Image.fromarray(K._draw(out, K._assets_dir(info))[..., :3]); s = 700 / max(img.size); img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))))
    t = Image.new("RGB", (720, img.height + 60), "white"); t.paste(img, (0, 60))
    d = ImageDraw.Draw(t); d.text((4, 4), f"{name} {size}", fill="black")
    d.text((4, 20), "; ".join(f"{v['code']} {v['ids']} {v['detail'][:60]}" for v in r["vetoes"])[:200], fill="red")
    tiles.append(t); print(name, size, [(v["code"], v["ids"], v["detail"]) for v in r["vetoes"]])
sheet = Image.new("RGB", (720, sum(t.height for t in tiles)), "white"); y = 0
for t in tiles: sheet.paste(t, (0, y)); y += t.height
sheet.save(Path(__file__).parent / "data" / "disagree_sheet.png")
