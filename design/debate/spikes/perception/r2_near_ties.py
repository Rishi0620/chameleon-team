"""Spike r2 near-ties (open problem #4). GALLEY's own top-10 for several tasks -> J spread, critic v2.1 spread,
critic noise floor (score change under an invisible 1-px global shift), and a BLIND contact sheet (letters only)
so the eye ranking can be made before looking at either score. Key in r2_out/near_ties_key.json."""
import json, sys, importlib.util, random
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
HERE = Path(__file__).parent; ROOT = HERE.parents[3]; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from r2_critic import score, measure
from critic import render
from roles import infer_roles
G_DIR = HERE.parent / "inventor"; sys.path.insert(0, str(G_DIR))
import galley as G
spec = importlib.util.spec_from_file_location("unseen", G_DIR / "unseen.py"); U = importlib.util.module_from_spec(spec); spec.loader.exec_module(U)
OUT = HERE / "r2_out"
LV = {1: "level1_warmup", 2: "level2_core", 3: "level3_advanced"}
cases = [("U", U.design, 1080, 1920), ("U", U.design, 1080, 1080), ("L2", None, 1080, 1920), ("L3", None, 728, 90), ("L3", None, 1080, 1350)]
key = {}; rng = random.Random(7)
for name, src, W, H in cases:
    if src is None: src = json.loads((ROOT / f"input/chameleon_sample_{LV[int(name[1])]}.json").read_text())["source"]
    g = G.decompile(src); ctx, res = G.solve(g, W, H, top_k=10, verbose=False)
    roles = infer_roles(src); sf = measure(src, roles); rows = []
    for rank, cand in enumerate(res[:10]):
        d = G.emit(g, src, ctx, cand)
        tot, comp, notes, _ = score(d, src, sf, roles)
        sh = {"canvas": d["canvas"], "elements": [dict(e, x=min(max(0, e["x"] + 1), W - e["width"])) for e in d["elements"]]}
        tot_sh, _, _, _ = score(sh, src, sf, roles)
        rows.append(dict(galley_rank=rank + 1, J=round(cand[0], 4), struct=G.render_struct(cand[2], cand[3]), critic=round(tot, 2),
                         noise=round(abs(tot_sh - tot), 3), notes=notes[:4], img=render(d)[..., :3].astype(np.uint8)))
    letters = list("ABCDEFGHIJ")[:len(rows)]; order = list(range(len(rows))); rng.shuffle(order)
    tag = f"{name}_{W}x{H}"; key[tag] = {}
    tw = 700 if W >= H else 250; tiles = []
    for L, i in zip(letters, order):
        r = rows[i]; key[tag][L] = {k: v for k, v in r.items() if k != "img"}
        im = Image.fromarray(r["img"]); im = im.resize((tw, max(1, round(im.height * tw / im.width))))
        t = Image.new("RGB", (tw, im.height + 20), "white"); t.paste(im, (0, 20)); ImageDraw.Draw(t).text((4, 4), L, fill="black"); tiles.append(t)
    if W >= H:
        sheet = Image.new("RGB", (tw * 2, sum(t.height for t in tiles[::2]) + 10), "white"); y = [0, 0]
        for j, t in enumerate(tiles): sheet.paste(t, ((j % 2) * tw, y[j % 2])); y[j % 2] += t.height
    else:
        cols = 5; th = max(t.height for t in tiles); sheet = Image.new("RGB", (tw * cols, th * ((len(tiles) + cols - 1) // cols)), "white")
        for j, t in enumerate(tiles): sheet.paste(t, ((j % cols) * tw, (j // cols) * th))
    sheet.save(OUT / f"near_ties_{tag}_BLIND.png")
    Js = [r["J"] for r in rows]; cs = [r["critic"] for r in rows]
    print(f"{tag}: J spread top10 = {max(Js)-min(Js):.3f}; critic spread = {max(cs)-min(cs):.2f}; critic noise (1px shift) max = {max(r['noise'] for r in rows):.3f}")
(OUT / "near_ties_key.json").write_text(json.dumps(key, indent=1))
