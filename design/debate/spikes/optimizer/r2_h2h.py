"""Round-2 head-to-head: INVENTOR's GALLEY vs OPTIMIZER's slot solver on identical cases,
scored by one neutral pixel critic (not either engine's own objective).

Designs: L1, L2, L3 (samples), U (inventor's unseen split link-ad), S (opaque split colour-block),
B (copy on a translucent scrim over a busy photo). Sizes: a catalogue spread incl. extremes.

Critic (measured on the official renderer's output, relative to the SOURCE where it matters):
  struct   : off-canvas / image aspect >5% / non-int or <1 font sizes          (count)
  minpx    : smallest visible text font size (px)
  busy     : max edge density under any visible text ink box (underlay render, no text)
  crel     : min over visible texts of contrast(target)/contrast(source)  (1.0 = as legible as the
             designer made it; <0.5 = text lost its backdrop, e.g. white copy off its panel)
  ovl      : visible text ink overlapping other visible text / image ink (count of pairs)
  kept     : visible content elements / content elements
Run: .venv/bin/python design/debate/spikes/optimizer/r2_h2h.py [--quick]
"""
from __future__ import annotations

import io
import json
import math
import re
import sys
import time
import contextlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "design/debate/spikes/inventor"))

import r2_designs as D  # noqa: E402
import solver as OPT  # noqa: E402
import galley as GAL  # noqa: E402
from renderer.converter.convert import render_design_to_png  # noqa: E402

KIT = D.ASSETS2
OPT.ASSETS = KIT
GAL.ASSETS = KIT
OUT = HERE / "r2_out"
OUT.mkdir(exist_ok=True)


def load(fn):
    return json.loads((ROOT / "input" / fn).read_text())["source"]


DESIGNS = {
    "L1": load("chameleon_sample_level1_warmup.json"),
    "L2": load("chameleon_sample_level2_core.json"),
    "L3": load("chameleon_sample_level3_advanced.json"),
    "U": D.unseen(),
    "S": D.SPLIT,
    "B": D.BUSY,
}
SIZES = [(728, 90), (320, 50), (1600, 400), (1080, 1920), (1080, 1080), (300, 250), (160, 600)]


# ----------------------------------------------------------------------------- engines
def run_galley(src, W, H):
    with contextlib.redirect_stdout(io.StringIO()):
        g = GAL.decompile(src)
        ctx, res = GAL.solve(g, W, H, verbose=False)
        if not res:
            return None, "no feasible"
        out = GAL.emit(g, src, ctx, res[0])
    return out, GAL.render_struct(res[0][2], res[0][3])


def run_opt(src, W, H):
    out, best, atoms, top = OPT.solve(src, W, H)
    if best.get("fallback"):
        return out, "FALLBACK"
    return out, OPT.describe_sol(best)


# ----------------------------------------------------------------------------- critic
def rgba(c):
    m = re.match(r"rgba?\(([\d.]+),([\d.]+),([\d.]+)(?:,([\d.]+))?\)", (c or "").replace(" ", ""))
    return (0.0, 0.0, 0.0, 1.0) if not m else (float(m[1]), float(m[2]), float(m[3]), float(m[4] or 1))


def rel_lum(rgb):
    c = np.asarray(rgb, dtype=float) / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def visible(e):
    if e.get("opacity", 1) <= 0.01:
        return False
    if e["type"] == "text" and rgba(e.get("color"))[3] <= 0.01:
        return False
    return True


def text_ink(e):
    f = max(1, int(e["font_size"]))
    lw = OPT.line_widths(e, f, e["width"])
    h = (len(lw) - 1) * f * float(e.get("line_height", 1.2)) + 1.28 * f
    mw = max(lw)
    al = e.get("text_align", "left")
    x0 = e["x"] + ((e["width"] - mw) / 2 if al == "center" else (e["width"] - mw) if al == "right" else 0)
    return (x0, e["y"], x0 + mw, e["y"] + h)


def image_ink(e):
    w, h, pad = OPT.image_box(e, 1.0)
    return (e["x"] + pad[0], e["y"] + pad[1], e["x"] + e["width"] - pad[2], e["y"] + e["height"] - pad[3])


def underlay(design, tag):
    under = dict(design, elements=[e for e in design["elements"] if e["type"] != "text"])
    p = OUT / f"_under_{tag}.png"
    render_design_to_png(under, str(KIT), str(p))
    img = np.asarray(Image.open(p).convert("RGB")).astype(float)
    lum = rel_lum(img)
    gy, gx = np.gradient(lum)
    return lum, np.hypot(gx, gy) > 0.02


def text_stats(design, lum, edges):
    H, W = lum.shape
    res = {}
    for e in design["elements"]:
        if e["type"] != "text" or not visible(e):
            continue
        x0, y0, x1, y1 = text_ink(e)
        xa, ya, xb, yb = int(max(0, x0)), int(max(0, y0)), int(min(W, x1)), int(min(H, y1))
        if xb <= xa or yb <= ya:
            res[e["id"]] = (1.0, 0.0)
            continue
        bg = float(np.median(lum[ya:yb, xa:xb]))
        fg = float(rel_lum(np.array(rgba(e["color"])[:3])))
        res[e["id"]] = ((max(bg, fg) + 0.05) / (min(bg, fg) + 0.05), float(edges[ya:yb, xa:xb].mean()))
    return res


def overlaps(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1


def critique(out, src, src_stats, tag):
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    by = {e["id"]: e for e in src["elements"]}
    struct = 0
    for e in out["elements"]:
        if e["x"] < -0.5 or e["y"] < -0.5 or e["x"] + e["width"] > W + 0.5 or e["y"] + e["height"] > H + 0.5:
            struct += 1
        s = by[e["id"]]
        if e["type"] == "image" and s.get("fit", "contain") != "cover":
            if abs((e["width"] / e["height"]) / (s["width"] / s["height"]) - 1) > 0.05:
                struct += 1
        if e["type"] == "text" and (e["font_size"] < 1 or e["font_size"] != int(e["font_size"])):
            struct += 1
    lum, edges = underlay(out, tag)
    st = text_stats(out, lum, edges)
    vis_txt = [e for e in out["elements"] if e["type"] == "text" and visible(e)]
    minpx = min((int(e["font_size"]) for e in vis_txt), default=0)
    busy = max((v[1] for v in st.values()), default=0.0)
    crel = min((st[k][0] / max(1e-6, src_stats[k][0]) for k in st if k in src_stats), default=1.0)
    inks = [(e["id"], e.get("group_id"), text_ink(e)) for e in vis_txt]
    imgs = [(e["id"], e.get("group_id"), image_ink(e)) for e in out["elements"]
            if e["type"] == "image" and visible(e) and e.get("fit", "contain") != "cover"]
    clip = sum(1 for _, _, b in inks if b[0] < -1 or b[1] < -1 or b[2] > W + 1 or b[3] > H + 1)
    allink = [b for _, _, b in inks] + [b for _, _, b in imgs]
    cov = 0.0
    if allink:
        ux0, uy0 = max(0, min(b[0] for b in allink)), max(0, min(b[1] for b in allink))
        ux1, uy1 = min(W, max(b[2] for b in allink)), min(H, max(b[3] for b in allink))
        cov = max(0.0, (ux1 - ux0) * (uy1 - uy0)) / (W * H)
    ovl = 0
    for i, (a, ga, ba) in enumerate(inks):
        for b, gb, bb in inks[i + 1:] + imgs:
            if not (ga and ga == gb) and overlaps(ba, bb):
                ovl += 1
    content = [e for e in src["elements"] if not (e["width"] * e["height"] >= 0.85 * src["canvas"]["width"] * src["canvas"]["height"])]
    kept = sum(1 for e in out["elements"] if e["id"] in {c["id"] for c in content} and visible(e))
    return dict(struct=struct, minpx=minpx, busy=round(busy, 3), crel=round(crel, 2), ovl=ovl, clip=clip,
                cov=round(cov, 2), kept=f"{kept}/{len(content)}")


# ----------------------------------------------------------------------------- sheets
def sheet(rows, path, colw=520, labels=("GALLEY (inventor)", "OPTIMIZER (slots)")):
    tiles = []
    for label, pa, pb in rows:
        ims = []
        for p in (pa, pb):
            im = Image.open(p).convert("RGB") if p and Path(p).exists() else Image.new("RGB", (100, 60), (255, 200, 200))
            k = min(1.0, colw / im.width, 300 / im.height)
            ims.append(im.resize((max(1, int(im.width * k)), max(1, int(im.height * k)))))
        tiles.append((label, ims))
    Wt = 2 * colw + 40
    Ht = sum(max(i.height for i in ims) + 26 for _, ims in tiles) + 30
    sh = Image.new("RGB", (Wt, Ht), (245, 245, 245))
    d = ImageDraw.Draw(sh)
    d.text((10, 6), labels[0], fill=(0, 0, 0))
    d.text((colw + 30, 6), labels[1], fill=(0, 0, 0))
    y = 24
    for label, ims in tiles:
        d.text((10, y), label, fill=(120, 0, 0))
        d.text((colw + 30, y), label, fill=(120, 0, 0))
        sh.paste(ims[0], (10, y + 14))
        sh.paste(ims[1], (colw + 30, y + 14))
        y += max(i.height for i in ims) + 26
    sh.save(path)


def summarize(table):
    """Failure counts per engine: a case FAILS a row if the neutral critic sees it."""
    rows = ["engine design  n  crash  illegible(minpx<10)  lost_backdrop(crel<.5)  on_busy(busy>.1)  text_clipped  text_overlap  tiny_island(cov<.15)  mean_minpx"]
    for eng in [e for e in ("GAL", "OPT", "MRG", "DES") if any(t["engine"] == e for t in table)]:
        for dsg in sorted({t["design"] for t in table}) + ["ALL"]:
            ts = [t for t in table if t["engine"] == eng and (dsg == "ALL" or t["design"] == dsg)]
            ok = [t for t in ts if "minpx" in t]
            rows.append(f"{eng:4s}  {dsg:4s} {len(ts):3d} {len(ts) - len(ok):5d} "
                        f"{sum(t['minpx'] < 10 for t in ok):12d} {sum(t['crel'] < 0.5 for t in ok):20d} "
                        f"{sum(t['busy'] > 0.1 for t in ok):16d} {sum(t['clip'] > 0 for t in ok):13d} "
                        f"{sum(t['ovl'] > 0 for t in ok):13d} {sum(t['cov'] < 0.15 for t in ok):18d} "
                        f"{(sum(t['minpx'] for t in ok) / max(1, len(ok))):12.1f}")
    return "\n".join(rows)


def main():
    D.build_assets()
    sizes = SIZES[:3] if "--quick" in sys.argv else SIZES
    log, table = [], []
    for name, src in DESIGNS.items():
        lum, edges = underlay(src, f"{name}_src")
        src_stats = text_stats(src, lum, edges)
        render_design_to_png(src, str(KIT), str(OUT / f"{name}_source.png"))
        rows = []
        for W, H in sizes:
            res = {}
            for eng, fn in (("GAL", run_galley), ("OPT", run_opt)):
                t = time.time()
                try:
                    out, desc = fn(src, W, H)
                except Exception as ex:  # an engine crash is a result too
                    out, desc = None, f"CRASH {type(ex).__name__}: {ex}"
                dt = time.time() - t
                png = OUT / f"{name}_{W}x{H}_{eng}.png"
                if out is not None:
                    (OUT / f"{name}_{W}x{H}_{eng}.json").write_text(json.dumps(out, indent=1))
                    try:
                        render_design_to_png(out, str(KIT), str(png))
                        c = critique(out, src, src_stats, f"{name}_{W}x{H}_{eng}")
                    except Exception as ex:
                        c, png = {"render": f"CRASH {ex}"}, None
                else:
                    c, png = {"result": desc}, None
                res[eng] = (png, c, dt, desc)
                table.append(dict(design=name, size=f"{W}x{H}", engine=eng, t=round(dt, 2), **c))
                line = f"{name} {W}x{H} {eng} {dt:5.2f}s {c}  | {desc}"
                print(line, flush=True)
                log.append(line)
            rows.append((f"{name} {W}x{H}", res["GAL"][0], res["OPT"][0]))
        sheet(rows, OUT / f"h2h_{name}.png")
    summ = summarize(table)
    print(summ)
    (OUT / "h2h_log.txt").write_text("\n".join(log) + "\n\n" + summ + "\n")
    (OUT / "h2h_table.json").write_text(json.dumps(table, indent=1))
    for p in OUT.glob("_under_*.png"):
        p.unlink()


if __name__ == "__main__":
    main()
