"""run.py — CLI for the proto engine (owner: OPTIMIZER). Run from the repo root:

  .venv/bin/python -m design.debate.proto.run samples fixtures --sizes std --fixedpoint
  .venv/bin/python -m design.debate.proto.run input/chameleon_sample_level3_advanced.json --sizes 728x90

TASK: a task JSON ({source, target_canvas[, assets_dir]}) or bare design, or keywords
      samples | fixtures | bench | all (= samples + fixtures).
--sizes: official | std (official + 728x90,320x50,160x600,300x250,1080x1920,1080x1080,1600x400) | WxH,WxH
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROTO = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from . import contract as C  # noqa: E402
from . import engine as E  # noqa: E402

STD = [(728, 90), (320, 50), (160, 600), (300, 250), (1080, 1920), (1080, 1080), (1600, 400)]
FONTS = str(ROOT / "brand_kit" / "fonts")


def load_tasks(names):
    tasks = []
    for n in names:
        if n in ("samples", "all"):
            for p in sorted((ROOT / "input").glob("chameleon_sample_*.json")):
                tasks.append(_task(p))
        if n in ("fixtures", "all"):
            for p in sorted((PROTO / "fixtures").glob("*.json")):
                tasks.append(_task(p))
        if n == "bench":
            for p in sorted((ROOT / "design/debate/bench/designs").glob("*.json")):
                if p.name == "id_legend.json":
                    continue
                t = _task(p)
                t["assets_dir"] = str(ROOT / "design/debate/bench/assets")
                tasks.append(t)
        if n not in ("samples", "fixtures", "all", "bench"):
            tasks.append(_task(Path(n)))
    return tasks


def _task(p):
    d = json.loads(Path(p).read_text())
    name = p.stem.replace("chameleon_sample_", "").replace("level1_warmup", "L1").replace(
        "level2_core", "L2").replace("level3_advanced", "L3")
    if "source" in d:
        src, tgt = d["source"], d.get("target_canvas")
        ad = d.get("assets_dir")
    else:
        src, tgt, ad = d, None, None
    if ad:
        ad = str((ROOT / ad).resolve()) if not os.path.isabs(ad) else ad
    return {"name": name, "source": src, "target": tgt, "assets_dir": ad}


def parse_sizes(spec, official):
    out = []
    if spec in ("official", "std"):
        if official:
            out.append((int(official["width"]), int(official["height"])))
        if spec == "std":
            out += [s for s in STD if s not in out]
        return out
    for tok in spec.split(","):
        w, h = tok.lower().split("x")
        out.append((int(w), int(h)))
    return out


def render(design, assets_dir, path):
    from renderer.converter.convert import render_design_to_png
    render_design_to_png(design, assets_dir, str(path), fonts_dir=FONTS)


def sheet(tiles, path, max_w=560, max_h=300, cols=4):
    from PIL import Image, ImageDraw
    ims = []
    for label, p in tiles:
        try:
            im = Image.open(p).convert("RGB")
        except Exception:  # noqa: BLE001
            im = Image.new("RGB", (120, 60), (255, 200, 200))
        k = min(1.0, max_w / im.width, max_h / im.height)
        ims.append((label, im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))))
    rows = [ims[i:i + cols] for i in range(0, len(ims), cols)]
    pad = 12
    Wt = max(sum(im.width for _, im in r) + pad * (len(r) + 1) for r in rows)
    Ht = sum(max(im.height for _, im in r) + pad + 16 for r in rows) + pad
    sh = Image.new("RGB", (Wt, Ht), (244, 244, 244))
    d = ImageDraw.Draw(sh)
    y = pad
    for r in rows:
        x = pad
        for label, im in r:
            d.text((x, y), label, fill=(0, 0, 0))
            sh.paste(im, (x, y + 14))
            x += im.width + pad
        y += max(im.height for _, im in r) + pad + 16
    sh.save(path)


def drift(src, out):
    Wc, Hc = src["canvas"]["width"], src["canvas"]["height"]
    diag = math.hypot(Wc, Hc)
    o = {e["id"]: e for e in out["elements"]}
    dc, ds, hid = [], [], 0
    for e in src["elements"]:
        f = o[e["id"]]
        if not C.visible(f):
            hid += int(C.visible(e))
            continue
        dc.append(math.hypot(e["x"] + e["width"] / 2 - f["x"] - f["width"] / 2,
                             e["y"] + e["height"] / 2 - f["y"] - f["height"] / 2) / diag)
        if e["type"] == "text":
            ds.append(abs(f["font_size"] / e["font_size"] - 1))
    return (100 * sum(dc) / max(1, len(dc)), 100 * max(dc or [0]), 100 * (sum(ds) / len(ds) if ds else 0), hid)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks", nargs="+")
    ap.add_argument("--sizes", default="official")
    ap.add_argument("--out", default=str(PROTO / "out"))
    ap.add_argument("--assets", default=None)
    ap.add_argument("--fixedpoint", action="store_true")
    ap.add_argument("--no-hooks", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.no_hooks:
        E.USE_HOOKS = False
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log, fp_rows = [], ["design   mean_drift%  max_drift%  mean_font_change%  hidden_visible_src  stage"]
    summary = {"runs": 0, "fallback": 0, "contract_hard": 0, "vetoed": 0, "time": 0.0, "max_time": 0.0}
    for t in load_tasks(a.tasks):
        assets = a.assets or t["assets_dir"] or str(ROOT / "brand_kit" / "assets")
        src = t["source"]
        tiles = []
        try:
            render(src, assets, out_dir / f"{t['name']}_source.png")
            tiles.append((f"{t['name']} source {int(src['canvas']['width'])}x{int(src['canvas']['height'])}",
                          out_dir / f"{t['name']}_source.png"))
        except Exception as ex:  # noqa: BLE001
            log.append(f"{t['name']}: source render failed: {ex}")
        for (Wt, Ht) in parse_sizes(a.sizes, t["target"]):
            t0 = time.time()
            out, info, rep = E.resize_with_info(src, {"width": Wt, "height": Ht}, assets)
            dt = time.time() - t0
            hard, warn = C.validate(src, out, {"width": Wt, "height": Ht}, assets)
            name = f"{t['name']}_{Wt}x{Ht}"
            (out_dir / f"{name}.json").write_text(json.dumps(out, indent=1))
            try:
                render(out, assets, out_dir / f"{name}.png")
                rend = "ok"
            except Exception as ex:  # noqa: BLE001
                rend = f"RENDER CRASH {type(ex).__name__}: {ex}"
            ch = rep.get("chosen") or {}
            line = (f"{name:28s} {dt:5.2f}s stage={rep.get('stage')} relax={rep.get('relax_level')} "
                    f"floor={rep.get('floor', '-')} hard={len(hard)} render={rend} | {ch.get('program')} "
                    f"z={ch.get('z')} E={ch.get('E')} vetoes={ch.get('vetoes')} rules={ch.get('rules_hard')}/"
                    f"{ch.get('rules_soft')} fin={ch.get('finished', False)} hidden={len(info.get('hidden', []))}")
            if rep.get("hook_errors"):
                line += f"\n      hook_errors: {rep['hook_errors'][:3]}"
            if rep.get("error"):
                line += f"\n      ERROR: {rep['error']}"
            if hard:
                line += f"\n      contract: {hard[:3]}"
            log.append(line)
            if not a.quiet:
                print(line, flush=True)
            summary["runs"] += 1
            summary["fallback"] += int(rep.get("stage") != "ok")
            summary["contract_hard"] += int(bool(hard))
            summary["vetoed"] += int(bool(ch.get("vetoes")))
            summary["time"] += dt
            summary["max_time"] = max(summary["max_time"], dt)
            tiles.append((f"{Wt}x{Ht}  {(ch.get('program') or rep.get('floor') or '')[:60]}", out_dir / f"{name}.png"))
        sheet(tiles, out_dir / f"sheet_{t['name']}.png")
        if a.fixedpoint:
            cw, chh = int(src["canvas"]["width"]), int(src["canvas"]["height"])
            out, info, rep = E.resize_with_info(src, {"width": cw, "height": chh}, assets)
            md, xd, fc, hid = drift(E._normalize(src), out)
            fp_rows.append(f"{t['name']:8s} {md:11.1f} {xd:11.1f} {fc:18.1f} {hid:18d}  {rep.get('stage')} "
                           f"{(rep.get('chosen') or {}).get('program')}")
            render(out, assets, out_dir / f"{t['name']}_fixedpoint.png")
            if not a.quiet:
                print(fp_rows[-1], flush=True)
    summ = (f"runs={summary['runs']} fallback={summary['fallback']} contract_hard={summary['contract_hard']} "
            f"vetoed_chosen={summary['vetoed']} mean_time={summary['time'] / max(1, summary['runs']):.2f}s "
            f"max_time={summary['max_time']:.2f}s")
    log.append(summ)
    print(summ)
    (out_dir / "run_log.txt").write_text("\n".join(log) + "\n")
    if a.fixedpoint:
        (out_dir / "fixedpoint.txt").write_text("\n".join(fp_rows) + "\n")


if __name__ == "__main__":
    main()
