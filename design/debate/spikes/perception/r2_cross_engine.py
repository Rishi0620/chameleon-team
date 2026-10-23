"""Spike r2: run the v2 pixel critic on EVERY engine's existing outputs for shared tasks.
Ids are remapped by list order (verified by type/content/asset), every JSON is re-rendered with the
official renderer path, and a ranked table + labelled contact sheet is written per task."""
import json, sys, glob, re, importlib.util, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
HERE = Path(__file__).parent; ROOT = HERE.parents[3]; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from r2_critic import score, measure
from critic import render
from roles import infer_roles
SP = HERE.parent; OUT = HERE / "r2_out"; OUT.mkdir(exist_ok=True)
LV = {1: "level1_warmup", 2: "level2_core", 3: "level3_advanced"}
spec = importlib.util.spec_from_file_location("judge_fb", SP / "judge" / "fallback_and_sweep.py")
jfb = importlib.util.module_from_spec(spec); spec.loader.exec_module(jfb)

def remap(src, out):
    se, oe = src["elements"], out["elements"]
    if len(se) != len(oe): return None
    if [e["id"] for e in se] == [e["id"] for e in oe]: return out
    byid = {e["id"]: e for e in oe}
    if set(byid) == {e["id"] for e in se}: return {"canvas": out["canvas"], "elements": [byid[e["id"]] for e in se]}
    res = []
    for s, o in zip(se, oe):
        if s["type"] != o["type"] or s.get("content") != o.get("content") or s.get("asset_id") != o.get("asset_id"): return None
        res.append(dict(o, id=s["id"], **({"group_id": s["group_id"]} if s.get("group_id") else {})))
    return {"canvas": out["canvas"], "elements": res}

def stretch(src, W, H):
    sx, sy = W / src["canvas"]["width"], H / src["canvas"]["height"]; els = []
    for e in src["elements"]:
        e = dict(e, x=e["x"] * sx, y=e["y"] * sy, width=e["width"] * sx, height=e["height"] * sy)
        if e["type"] == "text": e["font_size"] = max(1.0, e["font_size"] * min(sx, sy))
        els.append(e)
    return {"canvas": {"width": W, "height": H}, "elements": els}

def candidates(n, W, H):
    c = {}
    p = SP / "designer" / f"out_{LV[n]}_{W}x{H}.json"
    if p.exists(): c["designer"] = json.loads(p.read_text())
    for eng in ("inventor", "optimizer"):
        p = SP / eng / "out" / f"L{n}_{W}x{H}.json"
        if p.exists(): c[eng] = json.loads(p.read_text())
    for p in [HERE / "out" / f"s4b_level{n}_best.json", OUT / f"perception_L{n}_{W}x{H}.json"]:
        if p.exists():
            d = json.loads(p.read_text())
            if (d["canvas"]["width"], d["canvas"]["height"]) == (W, H): c["perception"] = d
    if (n, W, H) == (3, 728, 90): c["judge_mock"] = json.loads((SP / "judge/out/mock_l3_leaderboard.json").read_text())
    return c

tasks = set()
for f in glob.glob(str(SP / "*/out/L*_*x*.json")) + glob.glob(str(SP / "designer/out_level*_*x*.json")):
    m = re.search(r"L(\d)_(\d+)x(\d+)", f) or re.search(r"level(\d)_\w+?_(\d+)x(\d+)", f)
    tasks.add(tuple(int(v) for v in m.groups()))
tasks.add((2, 1600, 400)); tasks.add((3, 728, 90))
rows_all = {}; md = []
for (n, W, H) in sorted(tasks):
    task = json.loads((ROOT / f"input/chameleon_sample_{LV[n]}.json").read_text()); src = task["source"]
    if (src["canvas"]["width"], src["canvas"]["height"]) == (W, H): continue          # fixed-point tasks: skip
    cands = candidates(n, W, H)
    if len(cands) < 2: continue
    cands["judge_safefit"] = jfb.safe_fit(src, {"width": W, "height": H})
    cands["baseline_stretch"] = stretch(src, W, H)
    roles = infer_roles(src); sf = measure(src, roles); rows = []
    for eng, d in cands.items():
        d2 = remap(src, d)
        if d2 is None: print("remap failed", eng, n, W, H); continue
        t0 = time.perf_counter(); tot, comp, notes, f = score(d2, src, sf, roles); dt = time.perf_counter() - t0
        img = render(d2)[..., :3]
        rows.append(dict(engine=eng, total=round(tot, 2), comp={k: round(v, 2) for k, v in comp.items()}, notes=notes,
                         hidden=[e["id"] for e in d2["elements"] if not f["els"][e["id"]].get("visible")], ms=round(dt * 1000), img=img))
    rows.sort(key=lambda r: r["total"])
    key = f"L{n}->{W}x{H}"; rows_all[key] = [{k: v for k, v in r.items() if k != "img"} for r in rows]
    md.append(f"\n### {key}\n\n| rank | engine | score (lower=better) | worst components | top issues |\n|---|---|---|---|---|")
    for i, r in enumerate(rows):
        worst = ", ".join(f"{k} {v:+.1f}" for k, v in sorted(r["comp"].items(), key=lambda kv: -kv[1])[:3] if v > 0.05)
        md.append(f"| {i+1} | {r['engine']} | {r['total']:.1f} | {worst} | {'; '.join(r['notes'][:3])} |")
    # contact sheet: each render scaled to fit a 900x(...) tile, labelled with rank/score
    tw = 900 if W >= H else 360; tiles = []
    for i, r in enumerate(rows):
        im = Image.fromarray(r["img"].astype(np.uint8)); s = tw / im.width; im = im.resize((tw, max(1, round(im.height * s))))
        t = Image.new("RGB", (tw, im.height + 22), "white"); t.paste(im, (0, 22))
        ImageDraw.Draw(t).text((4, 5), f"#{i+1} {r['engine']}  score {r['total']:.1f}", fill="black"); tiles.append(t)
    if W >= H:
        sheet = Image.new("RGB", (tw, sum(t.height for t in tiles)), "white"); y = 0
        for t in tiles: sheet.paste(t, (0, y)); y += t.height
    else:
        sheet = Image.new("RGB", (tw * len(tiles), max(t.height for t in tiles)), "white")
        for j, t in enumerate(tiles): sheet.paste(t, (j * tw, 0))
    sheet.save(OUT / f"sheet_L{n}_{W}x{H}.png")
    print(key, [(r["engine"], r["total"]) for r in rows])
(OUT / "scores.json").write_text(json.dumps(rows_all, indent=1))
(OUT / "tables.md").write_text("\n".join(md))
