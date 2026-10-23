"""R2 spike: topologies beyond rows/columns/stacks, as GALLEY *relations*, not templates.

1. HOST/OVERLAY on a full-bleed photo (fixture F1).  The canvas-layer image is a host whose
   pixels decide WHERE the galley may be typeset: we emulate the renderer's exact centre-crop
   at the target, compute a busyness map, derive the calm threshold from the SOURCE (how busy
   was it under the designer's own text?), extract maximal calm rectangles, and typeset the
   galley into each candidate live area.  Score = GALLEY J - busy-under-text penalty.
2. HOST/RIDER panel (fixture F2).  An opaque non-background shape that contains text is a
   container: its riders are decompiled into a NESTED galley typeset inside the panel's cell;
   the panel itself is a unit of the outer galley and bleeds to the canvas edges it touched
   in the source (a shape may stretch; images may not).

Run from repo root:  .venv/bin/python design/debate/spikes/inventor/r2_topology.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import galley as G  # noqa: E402
import r2_fixtures as FX  # noqa: E402

FX.build_assets()
G.ASSETS = FX.ASSETS2          # private asset dir (brand copies + the synthetic test photo)
G._ink.clear()
OUT = HERE / "out_r2"
OUT.mkdir(exist_ok=True)


# ----------------------------------------------------------------------------- pixels
def cover_crop(asset_id, W, H):
    """Exactly what assets._fit_image does for fit=cover (scale-to-fill + centre crop)."""
    im = Image.open(FX.ASSETS2 / asset_id).convert("RGB")
    s = max(W / im.width, H / im.height)
    nw, nh = max(1, round(im.width * s)), max(1, round(im.height * s))
    im = im.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - W) // 2, (nh - H) // 2
    return np.asarray(im.crop((left, top, left + W, top + H)), dtype=float)


def busy_map(rgb, win):
    L = rgb @ np.array([0.299, 0.587, 0.114])
    gy, gx = np.gradient(L)
    mag = np.hypot(gx, gy) / 255.0
    k = max(3, int(win))                      # box blur via integral image
    ii = np.pad(mag, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    H, W = mag.shape
    y0 = np.clip(np.arange(H) - k // 2, 0, H); y1 = np.clip(np.arange(H) + k // 2 + 1, 0, H)
    x0 = np.clip(np.arange(W) - k // 2, 0, W); x1 = np.clip(np.arange(W) + k // 2 + 1, 0, W)
    s = ii[y1][:, x1] - ii[y0][:, x1] - ii[y1][:, x0] + ii[y0][:, x0]
    area = (y1 - y0)[:, None] * (x1 - x0)[None, :]
    return s / area


def mean_in(m, box):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(m.shape[1], max(x0 + 1, x1)), min(m.shape[0], max(y0 + 1, y1))
    return float(m[y0:y1, x0:x1].mean())


def text_inks(design):
    boxes = []
    for e in design["elements"]:
        if e.get("opacity", 1) == 0:
            continue
        if e["type"] == "text" or (e["type"] == "shape" and e.get("group_id")):
            boxes.append(G.ink_box(e))
    return boxes


def max_rect(mask):
    """Largest all-True axis-aligned rectangle in a boolean grid (histogram/stack method)."""
    R, C = mask.shape
    h = np.zeros(C, int)
    best = (0, 0, 0, 0, 0)
    for r in range(R):
        h = np.where(mask[r], h + 1, 0)
        st = []
        for c in range(C + 1):
            cur = h[c] if c < C else 0
            start = c
            while st and st[-1][1] >= cur:
                start, hh = st.pop()
                area = hh * (c - start)
                if area > best[0]:
                    best = (area, start, r - hh + 1, c - start, hh)
            st.append((start, cur))
    return best[1:]  # col, row, ncols, nrows


def calm_live_areas(busy, thr, W, H, grid=40):
    gh, gw = max(4, int(grid * H / max(W, H))), max(4, int(grid * W / max(W, H)))
    cell = busy[: H - H % gh or H, : W - W % gw or W]
    ys = np.linspace(0, H, gh + 1).astype(int); xs = np.linspace(0, W, gw + 1).astype(int)
    m = np.array([[busy[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].max() <= thr for j in range(gw)] for i in range(gh)])
    areas = [("full", (0, 0, W, H))]
    for name, sl in (("calm", (slice(None), slice(None))), ("calm-top", (slice(0, gh // 2 + 1), slice(None))),
                     ("calm-bottom", (slice(gh // 2, None), slice(None))), ("calm-left", (slice(None), slice(0, gw // 2 + 1))),
                     ("calm-right", (slice(None), slice(gw // 2, None)))):
        sub = m[sl]
        if not sub.any():
            continue
        c, r, nc, nr = max_rect(sub)
        r += sl[0].start or 0; c += sl[1].start or 0
        x0, y0, x1, y1 = xs[c], ys[r], xs[c + nc], ys[r + nr]
        if (x1 - x0) * (y1 - y0) >= 0.08 * W * H and (x1 - x0) >= 120 and (y1 - y0) >= 60:
            areas.append((name, (x0, y0, x1 - x0, y1 - y0)))
    seen, uniq = set(), []
    for n, a in areas:
        if a not in seen:
            seen.add(a); uniq.append((n, a))
    return uniq, m


# ----------------------------------------------------------------------------- 1. overlay
def typeset_in_area(g, src, W, H, area):
    ax, ay, aw, ah = [int(v) for v in area]
    ctx, res = G.solve(g, aw, ah, verbose=False)
    if not res:
        return None
    best = res[0]
    sub = G.emit(g, src, ctx, best)
    bg_ids = {e["id"] for e in g.background}
    furn_ids = {e["id"] for u in g.furniture for e in u.els}
    out = []
    for e in sub["elements"]:
        e = dict(e)
        if e["id"] in bg_ids:
            e.update(x=0, y=0, width=W, height=H)
        else:
            e["x"] += ax; e["y"] += ay
        out.append(e)
    design = {"canvas": {"width": W, "height": H}, "elements": out}
    # furniture belongs to the CANVAS corners, not the live area's
    flow_ink = [G.ink_box(e) for e in out if e["id"] not in bg_ids | furn_ids and e.get("opacity", 1) != 0]
    m = G.Ctx(g, W, H).m * 0.6
    for u in g.furniture:
        els = [e for e in out if e["id"] in {x["id"] for x in u.els}]
        if not els or any(e.get("opacity", 1) == 0 for e in els):
            continue
        bx0, by0 = min(e["x"] for e in els), min(e["y"] for e in els)
        bw = max(e["x"] + e["width"] for e in els) - bx0; bh = max(e["y"] + e["height"] for e in els) - by0
        nx = m if u.corner[1] == "L" else W - m - bw
        ny = m if u.corner[0] == "T" else H - m - bh
        cand = [G.ink_box(dict(e, x=e["x"] - bx0 + nx, y=e["y"] - by0 + ny)) for e in els]
        if not any(G.overlap(c, f, pad=4) for c in cand for f in flow_ink):
            for e in els:
                e["x"] += nx - bx0; e["y"] += ny - by0
    return best, design


def overlay_solve(src, W, H, tag, lam=0.6, log=None):
    g = G.decompile(src)
    bg = g.background[0]
    # source-relative calm threshold: how busy was it under the designer's own text?
    sbusy = busy_map(cover_crop(bg["asset_id"], g.W0, g.H0), min(g.W0, g.H0) / 40)
    b_src = max(np.percentile([mean_in(sbusy, b) for b in text_inks(src)], 90), 0.004)
    busy = busy_map(cover_crop(bg["asset_id"], W, H), min(W, H) / 40)
    thr = max(1.5 * b_src, 0.006)
    areas, mask = calm_live_areas(busy, thr, W, H)
    rows = []
    for name, area in areas:
        r = typeset_in_area(g, src, W, H, area)
        if r is None:
            continue
        best, design = r
        b = np.mean([mean_in(busy, x) for x in text_inks(design)]) if text_inks(design) else 0
        pen = lam * max(0.0, b / b_src - 1.0)
        rows.append((best[0] - pen, best[0], pen, b, name, area, best, design))
    rows.sort(key=lambda t: -t[0])
    lines = [f"{tag} {W}x{H}: b_src={b_src:.4f} thr={thr:.4f} calm-cells={mask.mean():.0%}"]
    for tot, J, pen, b, name, area, best, design in rows:
        lines.append(f"   {name:11s} area={tuple(int(v) for v in area)}  J={J:+.3f} busy-pen={pen:.3f} -> {tot:+.3f}  "
                     f"busy={b:.4f}  {G.render_struct(best[2], best[3])}")
    if log is not None:
        log += lines
    print("\n".join(lines))
    return rows[0][-1], rows[0][4], [r[-1] for r in rows]


# ----------------------------------------------------------------------------- 2. panel host
def find_panels(src):
    W0, H0 = src["canvas"]["width"], src["canvas"]["height"]
    panels = []
    for e in src["elements"]:
        if e["type"] != "shape" or e.get("group_id") or G.eff_alpha(e) < 0.9:
            continue
        a = e["width"] * e["height"] / (W0 * H0)
        if not 0.12 <= a <= 0.85:
            continue
        box = (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"])
        riders = []
        for r in src["elements"]:
            if r is e or r.get("z_index", 0) <= e.get("z_index", 0):
                continue
            ib = G.ink_box(r)
            cx, cy = (ib[0] + ib[2]) / 2, (ib[1] + ib[3]) / 2
            if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]:
                riders.append(r)
        if any(r["type"] == "text" for r in riders):
            touches = dict(L=e["x"] <= 1, T=e["y"] <= 1, R=box[2] >= W0 - 1, B=box[3] >= H0 - 1)
            panels.append((e, riders, touches))
    return panels


def panel_solve(src, W, H, tag, log=None):
    W0, H0 = src["canvas"]["width"], src["canvas"]["height"]
    (panel, riders, touches), = find_panels(src)
    rider_ids = {r["id"] for r in riders}
    bg = [e for e in src["elements"] if e["width"] * e["height"] >= 0.85 * W0 * H0]
    others = [e for e in src["elements"] if e["id"] not in rider_ids and e is not panel and e not in bg]
    hero = max((e for e in others if e["type"] == "image"), key=lambda e: e["width"] * e["height"])
    inner_src = {"canvas": {"width": int(panel["width"]), "height": int(panel["height"])},
                 "elements": [dict(r, x=r["x"] - panel["x"], y=r["y"] - panel["y"]) for r in riders]}
    gi = G.decompile(inner_src)
    side_src = "C" if (touches["T"] and touches["B"]) else "R"
    fx0, fy0, fx1, fy1 = G.image_ink_rel(hero)
    ink_w0, ink_h0 = (fx1 - fx0) * hero["width"], (fy1 - fy0) * hero["height"]
    cands = []
    for orient in ("C", "R"):
        for hero_first in (False, True):
            for p in (0.34, 0.42, 0.5, 0.58, 0.66, 0.75):
                if orient == "C":
                    pw, ph = W * p, H
                    pc = (W - pw, 0, pw, ph) if hero_first else (0, 0, pw, ph)
                    hc = (0, 0, W - pw, H) if hero_first else (pw, 0, W - pw, H)
                else:
                    pw, ph = W, H * p
                    pc = (0, H - ph, pw, ph) if hero_first else (0, 0, pw, ph)
                    hc = (0, 0, W, H - ph) if hero_first else (0, ph, W, H - ph)
                if pc[2] < 60 or pc[3] < 40:
                    continue
                ctx, res = G.solve(gi, int(pc[2]), int(pc[3]), verbose=False)
                if not res:
                    continue
                m = 0.06 * min(hc[2], hc[3]) + 4
                s_img = min((hc[2] - 2 * m) / ink_w0, (hc[3] - 2 * m) / ink_h0)
                # the (transparent-padded) BOX must stay on canvas with its ink centred in the cell:
                # never shift the ink into the neighbouring cell (round-1 lesson: clamping moves ink)
                icx, icy = hc[0] + hc[2] / 2, hc[1] + hc[3] / 2
                cxf, cyf = fx0 + (fx1 - fx0) / 2, fy0 + (fy1 - fy0) / 2
                bw1, bh1 = ink_w0 / (fx1 - fx0), ink_h0 / (fy1 - fy0)       # box size at s=1
                lim = [icx / (cxf * bw1), (W - icx) / ((1 - cxf) * bw1), icy / (cyf * bh1), (H - icy) / ((1 - cyf) * bh1)]
                s_img = min([s_img] + lim)
                if s_img <= 0.05:
                    continue
                s_txt = res[0][1]
                # outer galley objective: the inner J, picture size, balance of the two scales,
                # faithfulness of the split axis and order -- same terms as GALLEY, one level up
                J = (res[0][0] + 0.35 * math.log(s_img)
                     - 0.5 * abs(math.log(s_img / max(s_txt, 1e-3)))
                     - (0.05 if orient != side_src else 0.0) - (0.03 if hero_first else 0.0))
                cands.append((J, orient, hero_first, p, pc, hc, ctx, res[0], s_img))
    cands.sort(key=lambda t: -t[0])
    J, orient, hero_first, p, pc, hc, ctx, best, s_img = cands[0]
    inner = G.emit(gi, inner_src, ctx, best)
    out = {e["id"]: dict(e) for e in src["elements"]}
    for e in bg:
        out[e["id"]].update(x=0, y=0, width=W, height=H)
    out[panel["id"]].update(x=pc[0], y=pc[1], width=pc[2], height=pc[3])     # a shape may stretch: bleed
    for e in inner["elements"]:
        out[e["id"]] = dict(e, x=e["x"] + pc[0], y=e["y"] + pc[1])
    bw, bh = ink_w0 * s_img / (fx1 - fx0), ink_h0 * s_img / (fy1 - fy0)
    icx, icy = hc[0] + hc[2] / 2, hc[1] + hc[3] / 2
    out[hero["id"]].update(x=icx - (fx0 + (fx1 - fx0) / 2) * bw, y=icy - (fy0 + (fy1 - fy0) / 2) * bh, width=bw, height=bh)
    h = out[hero["id"]]
    h["x"] = float(np.clip(h["x"], 0, W - bw)); h["y"] = float(np.clip(h["y"], 0, H - bh))
    design = {"canvas": {"width": W, "height": H}, "elements": [out[e["id"]] for e in src["elements"]]}
    lines = [f"{tag} {W}x{H}: panel touches={''.join(k for k, v in touches.items() if v)} source split={side_src}  "
             f"chosen: panel {'|' if orient == 'C' else '¶'} hero (hero first={hero_first}) share={p:.2f} "
             f"inner: {G.render_struct(best[2], best[3])} s_txt={best[1]:.2f} s_img={s_img:.2f} J={J:+.3f}"]
    for alt in cands[1:4]:
        lines.append(f"      alt J={alt[0]:+.3f} {alt[1]} hero_first={alt[2]} share={alt[3]:.2f} inner={G.render_struct(alt[7][2], alt[7][3])}")
    if log is not None:
        log += lines
    print("\n".join(lines))
    return design


def render(design, name):
    (OUT / f"{name}.json").write_text(json.dumps(design, indent=1))
    G.render_design_to_png(design, str(FX.ASSETS2), str(OUT / f"{name}.png"), fonts_dir=str(FX.ROOT / "brand_kit" / "fonts"))
    return name


def main():
    log, names = [], []
    names.append(render(FX.F1, "topo_F1_source"))
    names.append(render(FX.F2, "topo_F2_source"))
    for W, H in [(1080, 1920), (1600, 400), (728, 90), (1080, 1350)]:
        design, chosen, _ = overlay_solve(FX.F1, W, H, "F1", log=log)
        names.append(render(design, f"topo_F1_{W}x{H}_{chosen}"))
        # v1 behaviour for comparison: typeset in the full canvas, pixels ignored
        g = G.decompile(FX.F1)
        ctx, res = G.solve(g, W, H, verbose=False)
        names.append(render(G.emit(g, FX.F1, ctx, res[0]), f"topo_F1_{W}x{H}_v1"))
    for W, H in [(1080, 1920), (1080, 1080), (728, 90), (1600, 400), (300, 250)]:
        design = panel_solve(FX.F2, W, H, "F2", log=log)
        names.append(render(design, f"topo_F2_{W}x{H}"))
        g = G.decompile(FX.F2)
        ctx, res = G.solve(g, W, H, verbose=False)
        names.append(render(G.emit(g, FX.F2, ctx, res[0]), f"topo_F2_{W}x{H}_v1"))
    (OUT / "topology_log.txt").write_text("\n".join(log) + "\n")
    G.OUT, old = OUT, G.OUT
    try:
        G.contact_sheet([n for n in names if n.startswith("topo_F1")], OUT / "sheet_topo_F1.png", width=1500)
        G.contact_sheet([n for n in names if n.startswith("topo_F2")], OUT / "sheet_topo_F2.png", width=1500)
    finally:
        G.OUT = old


if __name__ == "__main__":
    main()
