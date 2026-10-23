"""Spike 4b: render-in-the-loop on the two extreme banners (L2 1600x400, L3 728x90).
A tiny parametric 'strip' generator enumerates candidates (which optional roles are shown, logo size,
text alignment); every candidate is RENDERED with the official renderer and ranked by the pixel critic
using SOURCE-RELATIVE thresholds. No ids are used: roles come from roles.infer_roles()."""
import json, sys, copy, itertools, time
from pathlib import Path
import numpy as np, skia
from PIL import Image
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
from critic import critique, FM, ROOT, x_height
from renderer.converter.wrap import char_widths, wrap_text
from roles import infer_roles, asset_stats

OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
DROP_COST = {"hero": 6, "subhead": 4, "badge": 1.5, "sticker": 1.5, "legal": 1.0, "unseen_image": 0, "decoration": 0.5}

def wt(e): return "bold" if e.get("font_weight") == "bold" else "regular"
def measure(e, fs, width):
    w = char_widths(FM, e["font_family"], wt(e), wt(e), fs, e["content"])
    lines = wrap_text(e["content"], w, width).split("\n"); off = 0; lw = []
    for ln in lines: lw.append(sum(w[off:off + len(ln)])); off += len(ln) + 1
    return len(lines), max(lw)
def fit_font(e, width, height, fs_max, fs_min=6.0):
    lo, hi, best = fs_min, fs_max, None
    for _ in range(18):
        mid = (lo + hi) / 2; n, mw = measure(e, mid, width)
        if n * mid * e.get("line_height", 1.2) <= height and mw <= width: best, lo = mid, mid
        else: hi = mid
    return best
def metrics(e, fs):
    tf = skia.Typeface.MakeFromData(FM.lookup(e["font_family"], wt(e), wt(e))); m = skia.Font(tf, fs).getMetrics()
    return -m.fAscent, m.fCapHeight

def hide(e, cw, ch):
    e = dict(e); s = min(1.0, cw / e["width"], ch / e["height"]) * 0.5
    e["width"], e["height"] = e["width"] * s, e["height"] * s; e["x"], e["y"] = 0.0, 0.0
    if e["type"] == "text":
        r = e["color"][e["color"].index("(") + 1:-1].split(",")[:3]
        e["color"] = f"rgba({','.join(x.strip() for x in r)},0)"   # renderer ignores text opacity; colour alpha hides
    e["opacity"] = 0.0; e["rotation"] = 0
    return e

def ink_place(e, box_h, cx, cy):
    """size image by box height, keep source aspect, position so the visible INK (alpha bbox) is centred on (cx,cy)."""
    asp = e["width"] / e["height"]; bw, bh = box_h * asp, box_h
    st = asset_stats(e["asset_id"]); s = min(bw / st["w"], bh / st["h"])     # contain scale
    dw, dh = st["w"] * s, st["h"] * s; ox, oy = (bw - dw) / 2, (bh - dh) / 2
    ix = ox + dw * (st["ink"][0] + st["ink"][2]) / 2; iy = oy + dh * (st["ink"][1] + st["ink"][3]) / 2
    ink_w = dw * (st["ink"][2] - st["ink"][0])
    return dict(e, x=cx - ix, y=cy - iy, width=bw, height=bh), ink_w, ox + dw * st["ink"][0]

def strip(src, tgt, roles, opt):
    cw, ch = tgt["width"], tgt["height"]; els = {e["id"]: e for e in src["elements"]}; out = {}
    by = lambda r: [k for k, v in roles.items() if v == r]
    m = max(6, round(0.09 * ch)); H = ch - 2 * m; gap = max(10, round(0.3 * H)); x = m
    for k in by("background"):
        e = els[k]; out[k] = dict(e, x=0, y=0, width=cw, height=ch)
    for i, k in enumerate(by("decoration")):  # keep translucent circles as corner accents, in-bounds, aspect kept
        e = els[k]; d = ch * (0.9 if i == 0 else 0.6)
        out[k] = dict(e, x=0 if i == 0 else cw - d, y=0 if i == 0 else ch - d, width=d, height=d)
    # logo, ink-aware: box may extend left into its own transparent margin, but stays on canvas
    for k in by("logo"):
        e = els[k]; bh = H * opt["logo_h"]
        placed, ink_w, ink_l = ink_place(e, bh, 0, ch / 2)
        placed["x"] = max(0.0, x - ink_l); placed["y"] = min(max(0.0, placed["y"]), ch - bh)
        out[k] = placed; x = placed["x"] + ink_l + ink_w + gap
    if opt["hero"]:
        for k in by("hero"):
            e = els[k]; bh = ch * 0.98
            placed, ink_w, ink_l = ink_place(e, bh, 0, ch / 2)
            placed["x"] = max(0.0, x - ink_l); placed["y"] = (ch - bh) / 2
            out[k] = placed; x = placed["x"] + ink_l + ink_w + gap
    # CTA pill on the right, sized from its label
    right = cw - m
    cl = [k for k in by("cta_label")]; cb = [k for k in by("cta_bg")]
    if cl:
        lab = els[cl[0]]; fs = min(lab["font_size"] * opt["cta_fs"], H * 0.36); fs = max(fs, 11)
        n, tw = measure(lab, fs, 10 ** 6); ph = min(H * 0.75, fs * 2.4); pw = tw + 2 * ph * 0.6
        px, py = right - pw, (ch - ph) / 2
        bg = els[cb[0]]; r = bg.get("corner_radius", 0) / max(1, bg["height"]) * ph
        out[cb[0]] = dict(bg, x=px, y=py, width=pw, height=ph, corner_radius=r)
        asc, cap = metrics(lab, fs)
        out[cl[0]] = dict(lab, x=px, y=py + ph / 2 + cap / 2 - asc, width=pw, height=fs * 1.2, font_size=fs)
        right = px - gap
    # text column
    col_w = right - x; hl = els[by("headline")[0]]; sub = [els[k] for k in by("subhead")]
    show_sub = opt["sub"] and sub
    h_head = H * (0.62 if show_sub else 1.0)
    fs_h = fit_font(hl, col_w, h_head, fs_max=hl["font_size"] * 1.5) or 6
    n_h, _ = measure(hl, fs_h, col_w); used = n_h * fs_h * 1.2
    blocks = [(hl, fs_h, used)]
    if show_sub:
        s = sub[0]; rem = H - used - 0.15 * fs_h
        fs_s = fit_font(s, col_w, rem, fs_max=min(s["font_size"] * 1.3, fs_h * 0.6)) or 0
        if fs_s >= 7:
            n_s, _ = measure(s, fs_s, col_w); blocks.append((s, fs_s, n_s * fs_s * 1.2))
    total = sum(b[2] for b in blocks) + 0.15 * fs_h * (len(blocks) - 1); y = (ch - total) / 2
    for e, fs, h in blocks:
        out[e["id"]] = dict(e, x=x, y=y, width=col_w, height=h + 1, font_size=fs, text_align=opt["align"]); y += h + 0.15 * fs_h
    # badges: first one rides on the hero's top-left (keeps its group intact) if hero is shown
    if opt["badge"] and opt["hero"] and by("hero"):
        hb = out[by("hero")[0]]; bgs = by("badge_bg"); labs = by("badge_label")
        if bgs:
            b, l = els[bgs[0]], [els[k] for k in labs if els[k].get("group_id") == els[bgs[0]].get("group_id")][0]
            fs = max(10, H * 0.14); n, tw = measure(l, fs, 10 ** 6); bh = fs * 2; bw = tw + bh
            bx = max(0, hb["x"] + hb["width"] * 0.5 - bw / 2); by_ = 2
            out[b["id"]] = dict(b, x=bx, y=by_, width=bw, height=bh, corner_radius=bh / 2)
            asc, cap = metrics(l, fs); out[l["id"]] = dict(l, x=bx, y=by_ + bh / 2 + cap / 2 - asc, width=bw, height=fs * 1.2, font_size=fs)
    for e in src["elements"]:
        if e["id"] not in out: out[e["id"]] = hide(e, cw, ch)
    return {"canvas": dict(tgt), "elements": [out[e["id"]] for e in src["elements"]]}

def score(m, src_m, design, roles):
    pen = 0.0; why = []
    for s in m["issues"]:
        if "contrast" in s:  # source-relative: only penalise if worse than the source's own choice
            k = s.split(":")[0]; base = src_m.get(f"{k}.contrast_p10", 4.5)
            if m.get(f"{k}.contrast_p10", 0) >= min(4.5, base * 0.95): continue
        if "canvas looks empty" in s or "off-centre" in s: continue   # needs source-relative calibration; skipped here
        pen += 5; why.append(s)
    for e in design["elements"]:
        hidden = e.get("opacity", 1) == 0
        r = roles[e["id"]].split("_")[0] if roles[e["id"]] not in DROP_COST else roles[e["id"]]
        if hidden: pen += DROP_COST.get(r, 3); why.append(f"hid {e['id']}")
    hid = [k for k, v in roles.items() if v == 'headline'][0]
    hx = m.get(f"{hid}.xheight_px", 0); cw, ch = design["canvas"]["width"], design["canvas"]["height"]
    # (a) hierarchy: no other text may out-shout the headline (source order preserved)
    for e in design["elements"]:
        if e["type"] == "text" and e["id"] != hid and m.get(f"{e['id']}.xheight_px", 0) > hx * 1.0 and e.get("opacity", 1) > 0:
            pen += 6; why.append(f"hierarchy inverted: {e['id']} > headline")
    # (b) typographic widows: a line holding a single word in a multi-line headline
    el = {e["id"]: e for e in design["elements"]}[hid]
    from critic import text_lines
    lines, _ = text_lines(el)
    if len(lines) > 1 and min(len(l.split()) for l in lines) < 2:
        pen += 4; why.append("headline has a one-word line")
    # (c) faithfulness of relative visual weight: ink-share vector of shown elements vs source
    sh = {k: v for k, v in m["ink_share"].items()}; ss = {k: v for k, v in src_m["ink_share"].items() if k in sh}
    zs, zo = sum(ss.values()) or 1, sum(sh.values()) or 1
    l1 = sum(abs(ss.get(k, 0) / zs - sh[k] / zo) for k in sh)
    pen += 12 * l1; why.append(f"ink-share L1 vs source {l1:.2f}")
    # (d) saturating headline-size reward
    tgt = 0.07 * min(cw, ch) + 4
    pen -= 8 * min(1.0, hx / tgt); why.append(f"headline x-height {hx}px (target {tgt:.0f})")
    return round(pen, 2), why

for task_file in ("chameleon_sample_level3_advanced.json", "chameleon_sample_level2_core.json"):
    task = json.loads((ROOT / "input" / task_file).read_text()); src, tgt = task["source"], task["target_canvas"]
    roles = infer_roles(src)
    deco = {"decoration": [k for k, v in roles.items() if v == "decoration"], "background": [k for k, v in roles.items() if v == "background"]}
    src_m, _ = critique(src, deco)
    grid = dict(hero=[False, True], sub=[False, True], badge=[False, True], logo_h=[0.6, 0.9], align=["left", "center"], cta_fs=[0.7, 1.0, 1.4])
    t0 = time.perf_counter(); res = []
    for vals in itertools.product(*grid.values()):
        opt = dict(zip(grid, vals))
        if opt["badge"] and not opt["hero"]: continue
        d = strip(src, tgt, roles, opt); m, img = critique(d, deco); p, why = score(m, src_m, d, roles)
        res.append((p, opt, m, why, img, d))
    dt = time.perf_counter() - t0
    res.sort(key=lambda r: r[0]); tag = task_file.split("_")[2]
    print(f"\n=== {tag} {tgt['width']}x{tgt['height']}: {len(res)} candidates rendered+critiqued in {dt:.1f}s "
          f"({dt/len(res)*1000:.0f} ms each, solo masks cached across candidates)")
    for rank, (p, opt, m, why, img, d) in enumerate(res):
        if rank < 4 or rank == len(res) - 1:
            print(f"  #{rank+1:2d} score={p:6.2f} {opt}")
            print("        issues:", [w for w in why if not w.startswith("headline")][:6], "|", why[-1])
    for rank in (0, 1, len(res) - 1):
        Image.fromarray(res[rank][4]).save(OUT / f"s4b_{tag}_rank{rank+1}.png")
    (OUT / f"s4b_{tag}_best.json").write_text(json.dumps(res[0][5], indent=1))
