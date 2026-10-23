"""Spike r2 (open problem #5): ink vs box packing.
(1) Audit every engine output: pairs of VISIBLE content elements whose JSON boxes overlap (not same group, not bg/deco,
    not overlapping in the source either) - and whether their INK actually touches.
(2) Price the box-disjoint policy: headline fit in a 728x90 strip when the logo's transparent margin may / may not
    be shared with the headline box."""
import json, sys, glob
from pathlib import Path
import numpy as np
HERE = Path(__file__).parent; ROOT = HERE.parents[3]; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from r2_critic import measure
from roles import infer_roles, asset_stats
from critic import FM
from renderer.converter.wrap import char_widths, wrap_text
import importlib.util
spec = importlib.util.spec_from_file_location("x", HERE / "r2_cross_engine.py")
src_txt = (HERE / "r2_cross_engine.py").read_text().split("tasks = set()")[0]
g = {"__file__": str(HERE / "r2_cross_engine.py")}; exec(compile(src_txt, "r2ce", "exec"), g)
LV = g["LV"]; candidates = g["candidates"]; remap = g["remap"]
def box(e): return (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"])
def inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0]); h = min(a[3], b[3]) - max(a[1], b[1]); return max(0, w) * max(0, h)
audit = {}; lines = []
for (n, W, H) in [(2, 1600, 400), (2, 728, 90), (3, 728, 90), (3, 1600, 400), (1, 1080, 1350), (2, 300, 250), (3, 160, 600)]:
    src = json.loads((ROOT / f"input/chameleon_sample_{LV[n]}.json").read_text())["source"]; roles = infer_roles(src)
    S = {e["id"]: e for e in src["elements"]}
    for eng, d in candidates(n, W, H).items():
        d = remap(src, d); f = measure(d, roles); E = {e["id"]: e for e in d["elements"]}
        vis = [k for k in E if f["els"][k].get("visible") and roles[k] not in ("background", "decoration")]
        hits = []
        for i in range(len(vis)):
            for j in range(i + 1, len(vis)):
                a, b = E[vis[i]], E[vis[j]]
                if a.get("group_id") and a.get("group_id") == b.get("group_id"): continue
                if inter(box(S[a["id"]]), box(S[b["id"]])) > 0: continue          # overlap already in the source = intentional
                ov = inter(box(a), box(b)) / max(1, min(a["width"] * a["height"], b["width"] * b["height"]))
                if ov > 0.01:
                    ink = (f["els"][a["id"]]["mask"] & f["els"][b["id"]]["mask"]).sum()
                    hits.append(f"{a['id']}×{b['id']} box {ov:.0%}{' INK' if ink > 20 else ''}")
        audit[f"L{n}->{W}x{H} {eng}"] = hits
        lines.append(f"L{n}->{W}x{H:<5} {eng:11s} {len(hits)} box-overlaps: {hits}")
print("\n".join(lines))
(HERE / "r2_out" / "ink_vs_box_audit.json").write_text(json.dumps(audit, indent=1))

# (2) price of box-disjointness in a 728x90 strip: logo | headline | CTA
def fit(el, width, height=74):
    best = None
    for fs in range(6, 60):
        w = char_widths(FM, el["font_family"], "bold", "bold", fs, el["content"])
        ls = wrap_text(el["content"], w, width).split("\n")
        widths = []; off = 0
        for l in ls: widths.append(sum(w[off:off + len(l)])); off += len(l) + 1
        if len(ls) * fs * 1.2 <= height and max(widths) <= width: best = (fs, len(ls))
    return best
st = asset_stats("solstice_logo_lockup.png"); logo_h = 44; logo_w = logo_h * 3.2
s = min(logo_w / st["w"], logo_h / st["h"]); dw = st["w"] * s; ox = (logo_w - dw) / 2
ink_l, ink_r = ox + dw * st["ink"][0], ox + dw * st["ink"][2]
print(f"\nlogo box {logo_w:.0f}x{logo_h} at x=0: visible ink spans x={ink_l:.0f}..{ink_r:.0f} (transparent margins {ink_l:.0f}px | {logo_w-ink_r:.0f}px)")
gap, cta_w, m = 16, 170, 12
col_end = 728 - m - cta_w - gap
for lvl in (3, 2):
    src = json.loads((ROOT / f"input/chameleon_sample_{LV[lvl]}.json").read_text())["source"]
    hl = next(e for e in src["elements"] if e["id"] == "headline")
    x_ink, x_box = ink_r + gap, max(logo_w, ink_r + gap)
    a, b = fit(hl, col_end - x_ink), fit(hl, col_end - x_box)
    print(f"L{lvl} headline column: ink-packed {col_end-x_ink:.0f}px -> {a[0]}px font/{a[1]} lines | box-disjoint {col_end-x_box:.0f}px -> {b[0]}px font/{b[1]} lines "
          f"| logo->headline visible gap: ink {gap}px vs box {x_box-ink_r:.0f}px")
