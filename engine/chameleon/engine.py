"""engine.py: resize(source, target_canvas) for the merged bracketed-galley prototype (owner: OPTIMIZER).

Pipeline
  decompile -> live areas (full canvas + overlay calm regions on photo backgrounds)
  -> search (patterns x omissions x shared z) -> top-K realised -> contract repair/validate
  -> finisher.finish -> critic.critique + rules.check -> lexicographic pick -> contract
  -> fallback ladder (relaxed search -> safe_fit -> last_resort).
Hooks (overlay, finisher, critic, rules) are optional; a missing module or an exception skips the hook.
"""
from __future__ import annotations

import copy
import importlib
import math
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

from . import contract as C
from . import decompile as D
from . import search as S
from . import textfit as T

ROOT = Path(__file__).resolve().parents[2]
HIDE_MODE = os.environ.get("CHAMELEON_HIDE_MODE", "never")          # never (stage one) | alpha | z_under_bg | never_text
DISJOINT_BOXES = os.environ.get("CHAMELEON_DISJOINT", "1") != "0"
TOP_K = int(os.environ.get("CHAMELEON_TOP_K", "6"))
USE_HOOKS = os.environ.get("CHAMELEON_HOOKS", "1") != "0"
NEAR_TIE = 0.03
SEARCH_BUDGET = float(os.environ.get("CHAMELEON_BUDGET", "8"))
LAST_REPORT: dict = {}


# ----------------------------------------------------------------------------- hooks
def _hook(name):
    if not USE_HOOKS:
        return None
    try:
        return importlib.import_module(f"{__package__}.{name}")
    except Exception:  # noqa: BLE001
        return None


def _call(mod, fn, *args, default=None, report=None, tag=""):
    if mod is None or not hasattr(mod, fn):
        return default
    t = time.time()
    try:
        return getattr(mod, fn)(*args)
    except Exception as ex:  # noqa: BLE001
        if report is not None:
            report.setdefault("hook_errors", []).append(f"{tag}{mod.__name__}.{fn}: {type(ex).__name__}: {ex}")
        return default
    finally:
        if report is not None:
            report.setdefault("hook_time", {}).setdefault(fn, 0.0)
            report["hook_time"][fn] += time.time() - t


# ----------------------------------------------------------------------------- entry points
def resize(source, target_canvas, assets_dir=None):
    out, info, report = resize_with_info(source, target_canvas, assets_dir)
    return out


def resize_with_info(source, target_canvas, assets_dir=None):
    global LAST_REPORT
    t0 = time.time()
    src = source["source"] if isinstance(source, dict) and "source" in source and "elements" not in source else source
    assets_dir = str(assets_dir or os.environ.get("CHAMELEON_ASSETS") or (ROOT / "brand_kit" / "assets"))
    target = {"width": int(round(float(target_canvas["width"]))), "height": int(round(float(target_canvas["height"])))}
    report = {"stage": "start", "assets_dir": assets_dir}
    T.reset_caches()
    try:
        src = _normalize(src)
        out, info = _run(src, target, assets_dir, report)
    except Exception as ex:  # noqa: BLE001
        report["error"] = f"{type(ex).__name__}: {ex}"
        report["traceback"] = traceback.format_exc()[-2000:]
        out, info = _floor(src if isinstance(src, dict) else source, target, assets_dir, report)
    report["time"] = round(time.time() - t0, 3)
    LAST_REPORT = report
    return out, info, report


def _normalize(src):
    src = copy.deepcopy(src)
    src["canvas"] = {"width": float(src["canvas"]["width"]), "height": float(src["canvas"]["height"])}
    for e in src["elements"]:
        for k, d in (("x", 0.0), ("y", 0.0), ("width", 1.0), ("height", 1.0)):
            try:
                e[k] = float(e.get(k, d))
            except (TypeError, ValueError):
                e[k] = d
        if e["type"] == "text":
            try:
                e["font_size"] = float(e.get("font_size", 24))
            except (TypeError, ValueError):
                e["font_size"] = 24.0
            fs = max(1.0, e["font_size"])
            if str(e.get("content", "")).strip() and (e["width"] < 1.5 * fs or e["height"] < fs):
                try:                                  # degenerate text box: use the natural one-line width
                    nat = T.W_k(e, int(fs), 1)
                except Exception:  # noqa: BLE001
                    nat = 0.6 * fs * len(str(e["content"]))
                w1 = min(max(e["width"], nat), 0.9 * src["canvas"]["width"])
                h1 = max(e["height"], 1.25 * fs)
                e["x"] -= (w1 - e["width"]) / 2           # grow about the centre: relations to shapes survive
                e["y"] -= (h1 - e["height"]) / 2
                e["width"], e["height"] = w1, h1
    return src


# ----------------------------------------------------------------------------- main run
def _run(src, target, assets_dir, report):
    """Search at the first ladder level that yields plans; if the winner is still vetoed (clipped,
    illegible, lost backdrop), escalate to the next relaxation level and keep the less vetoed result."""
    S.NEVER_DROP = D.KEEP_ALL = (HIDE_MODE == "never")
    best, level = None, 0
    while level < 11:
        rep = {}
        res = _run_from(src, target, assets_dir, rep, level)
        nveto = len((rep.get("chosen") or {}).get("vetoes") or []) if rep.get("stage") == "ok" else 99
        if best is None or nveto < best[0]:
            best = (nveto, res, rep)
        if nveto == 0 or rep.get("stage") != "ok":
            break
        level = int(rep.get("relax_level", level)) + 1
    report.update(best[2])
    return best[1]


def _run_from(src, target, assets_dir, report, start_level=0):
    W, H = target["width"], target["height"]
    W0, H0 = src["canvas"]["width"], src["canvas"]["height"]
    g = D.decompile(src, assets_dir)
    base = _base_info(src, g, assets_dir, W, H)
    report["program_source"] = base["program"]["source"]
    src_cov = _src_cov(g, W0, H0)

    # live areas: full canvas, plus calm regions of a photo background (INVENTOR overlay)
    lives = [(0.0, 0.0, float(W), float(H), None)]
    overlay = _hook("overlay") if base["bg_kind"] == "photo" else None
    calm = None
    if overlay is not None:
        res = _call(overlay, "analyze", src, target, base, assets_dir, default=None, report=report)
        if isinstance(res, dict):
            calm = {k: res.get(k) for k in ("status", "tolerance", "threshold", "calm_share")}
            if res.get("status") in ("ok",):
                for (x, y, w, h, sc) in (res.get("regions") or [])[:3]:
                    if w >= 0.25 * W and h >= 0.25 * H and not (w >= 0.98 * W and h >= 0.98 * H):
                        lives.append((float(x), float(y), float(w), float(h), sc))
    report["live_areas"] = [tuple(round(v, 1) for v in la[:4]) for la in lives]

    plans = []
    deadline = time.time() + SEARCH_BUDGET
    regime = S.band(W, H)
    k0 = {"strip": 4, "wide": 5, "squareish": 6, "tall": 8}[regime]
    ladder = [(k0, 1.0, 0.8, False), (k0 + 2, 0.85, 0.8, False), (k0 + 4, 0.72, 0.8, False),
              (k0 + 4, 0.70, 0.95, False), (k0 + 4, 0.70, 0.95, True)]       # last: brand-reminder mode
    hier_flags = [False] * len(ladder)
    if HIDE_MODE == "never":
        # nothing may be dropped: relax the legibility floors step by step (keeping the type hierarchy),
        # and only when even that fails let the hierarchy go too
        ladder = [(k0, 1.0, 0.8, False), (k0 + 2, 0.85, 0.8, False), (k0 + 4, 0.72, 0.8, False),
                  (k0 + 4, 0.60, 0.8, False), (k0 + 4, 0.50, 0.8, False), (k0 + 4, 0.42, 0.8, False),
                  (k0 + 4, 0.35, 0.8, False), (k0 + 4, 0.28, 0.8, False),
                  (k0 + 4, 0.50, 0.8, False), (k0 + 4, 0.35, 0.8, False), (k0 + 4, 0.28, 0.8, False)]
        hier_flags = [False] * 8 + [True] * 3
    for level, (kmax, floor_mult, must_thr, brand) in enumerate(ladder):
        if level < start_level:
            continue
        if brand:
            for u in g.stream:
                if u.rent >= D.INF:
                    u.rent = 4.0                    # headline droppable only when copy is impossible
        for (lx, ly, lw, lh, sc) in lives:
            ctx = S.Ctx(g, lw, lh, W, H, W0, H0, assets_dir, DISJOINT_BOXES, kmax=kmax)
            ctx._live = (lx, ly, lw, lh)
            if floor_mult != 1.0:
                ctx.js = ctx.js / floor_mult       # lower judge-px floors (relaxation)
                ctx.rec = ctx.rec * min(1.0, floor_mult / 0.7)
                ctx.hier_relax = hier_flags[level]
            ps = S.search(g, ctx, src_cov, must_thr=must_thr, deadline=deadline + (2.0 if level else 0.0),
                          never_drop_text=(HIDE_MODE == "never_text"), ox=lx, oy=ly)
            for p in ps:
                p.ctx, p.level, p.live_score = ctx, level, sc
            plans += ps
        if plans:
            report["relax_level"] = level
            break
    if not plans:
        report["stage"] = "no plan"
        return _floor(src, target, assets_dir, report)

    # busyness on photo backgrounds (source-relative, via overlay.busy_ratio)
    if overlay is not None:
        plans.sort(key=lambda p: p.energy)
        for p in plans[: 3 * TOP_K]:
            boxes = [(it.x, it.y, it.x + it.w, it.y + it.h) for it in S.all_items(p)
                     if it.unit.kind in ("text", "pill", "chips") and not _on_host(it, p)]
            if boxes:
                br = _call(overlay, "busy_ratio", src, target, boxes, base, assets_dir, default=None, report=report)
                if br:
                    b = max(br)
                    p.terms["busy"] = S.W["busy"] * max(0.0, b - 1.0)
                    p.energy = sum(p.terms.values())
    plans.sort(key=lambda p: p.energy)
    top = plans[:TOP_K]

    finisher, critic, rules = _hook("finisher"), _hook("critic"), _hook("rules")
    evaluated = []
    for rank, p in enumerate(top):
        out, info = realize(p, g, src, target, assets_dir, base)
        out = C.repair(src, out, target, assets_dir, HIDE_MODE)
        hard, warn = C.validate(src, out, target, assets_dir)
        info["candidate"] = rank
        if calm:
            info["calm"] = calm
        rec = {"rank": rank, "program": p.program(), "z": round(p.z, 3), "E": round(p.energy, 3),
               "contract_pre": len(hard)}
        if hard:
            rec["contract_hard"] = hard[:4]
            evaluated.append((rec, out, info, (1, 0, 0, p.energy)))
            continue
        if finisher is not None:
            fin = _call(finisher, "finish", src, copy.deepcopy(out), copy.deepcopy(info), default=None,
                        report=report, tag=f"[{rank}] ")
            if isinstance(fin, dict) and "elements" in fin:
                fin = C.repair(src, fin, target, assets_dir, HIDE_MODE)
                h2, _ = C.validate(src, fin, target, assets_dir)
                if not h2:
                    out = fin
                    info["ink"] = _ink_map(out, assets_dir)
                    rec["finished"] = True
                else:
                    rec["finisher_reverted"] = h2[:2]
        crit = _call(critic, "critique", src, out, info, None, default=None, report=report, tag=f"[{rank}] ") \
            if critic is not None else None
        vetoes = list((crit or {}).get("vetoes") or [])
        if HIDE_MODE == "never":     # an unresolvable source asset must stay visible: its placeholder is the source's own
            vetoes = [v for v in vetoes if not _vname(v).startswith("PLACEHOLDER")]
        penalty = float((crit or {}).get("penalty") or 0.0)
        viols = _call(rules, "check", src, out, info, default=[], report=report, tag=f"[{rank}] ") or []
        n_hard = sum(1 for v in viols if _sev(v) == "hard")
        n_soft = sum(1 for v in viols if _sev(v) != "hard")
        rec.update(vetoes=[_vname(v) for v in vetoes][:6], rules_hard=n_hard, rules_soft=n_soft,
                   critic_penalty=round(penalty, 3))
        crash = any("RENDER_CRASH" in _vname(v) for v in vetoes)
        e_adj = p.energy + S.W["soft"] * n_soft
        rec["E_adj"] = round(e_adj, 3)
        evaluated.append((rec, out, info, (1 if crash else 0, len(vetoes) + n_hard, 0, e_adj, penalty)))
    report["candidates"] = [e[0] for e in evaluated]
    clean = [e for e in evaluated if e[3][0] == 0]
    if not clean:
        report["stage"] = "all candidates failed contract"
        return _floor(src, target, assets_dir, report)
    best_key = min(e[3][:3] for e in clean)
    pool = [e for e in clean if e[3][:3] == best_key]
    e_min = min(e[3][3] for e in pool)
    near = [e for e in pool if e[3][3] <= e_min + NEAR_TIE]
    chosen = min(near, key=lambda e: (e[3][4], e[3][3]))
    rec, out, info, key = chosen
    report["chosen"] = rec
    report["stage"] = "ok"
    hard, warn = C.validate(src, out, target, assets_dir)
    report["contract_final"] = {"hard": hard, "warn": warn[:6]}
    if hard:
        return _floor(src, target, assets_dir, report)
    return out, info


def _sev(v):
    return (v.get("severity") if isinstance(v, dict) else getattr(v, "severity", "soft")) or "soft"


def _vname(v):
    if isinstance(v, dict):
        return v.get("code") or v.get("rule") or str(v)[:40]
    return getattr(v, "code", None) or getattr(v, "rule", None) or str(v)[:40]


def _on_host(it, plan):
    return False


def _floor(src, target, assets_dir, report):
    """Fallback ladder floor: uniform contain (structurally perfect), then last resort."""
    try:
        out = C.safe_fit(src, target, assets_dir, HIDE_MODE)
        hard, _ = C.validate(src, out, target, assets_dir)
        report["floor"] = "safe_fit" + (" (contract issues)" if hard else "")
        if not hard:
            return out, {"assets_dir": assets_dir, "hidden": [], "scale": None, "fallback": "safe_fit"}
    except Exception as ex:  # noqa: BLE001
        report["floor_error"] = f"{type(ex).__name__}: {ex}"
    report["floor"] = "last_resort"
    return C.last_resort(src, target), {"assets_dir": assets_dir, "hidden": [], "fallback": "last_resort"}


# ----------------------------------------------------------------------------- info
def _src_cov(g, W0, H0):
    inks = [u.ink for u in g.stream]
    if not inks:
        return 0.0
    return D.area(D.union(inks)) / (W0 * H0)


def _base_info(src, g, assets_dir, W, H):
    roles = D.element_roles(g)
    for e in src["elements"]:
        roles.setdefault(e["id"], "unknown")
    pri = {}
    for u, gg in D.all_units(g):
        for e in u.els:
            pri.setdefault(e["id"], 1e9 if u.rent >= D.INF else round(u.rent, 3))
    groups = {}
    for e in src["elements"]:
        if e.get("group_id"):
            groups.setdefault(e["group_id"], []).append(e["id"])
    bg = g.background[0] if g.background else None
    bg_kind = "none"
    if bg is not None:
        bg_kind = "photo" if bg["type"] == "image" and bg.get("fit", "contain") in ("cover", "fill") else "flat"
    src_ink = {}
    for e in src["elements"]:
        try:
            x0, y0, x1, y1 = T.ink_rect(e, assets_dir)
        except Exception:  # noqa: BLE001
            x0, y0, x1, y1 = e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]
        src_ink[e["id"]] = [round(x0, 2), round(y0, 2), round(x1 - x0, 2), round(y1 - y0, 2)]
    units = [{"name": u.name, "kind": u.kind, "ids": [e["id"] for e in u.els], "role": u.role,
              "rent": 1e9 if u.rent >= D.INF else round(u.rent, 3)} for u, _ in D.all_units(g)]
    return {
        "roles": roles, "priority": pri, "hidden": [], "containers": D.containers(g), "groups": groups,
        "bg_id": bg["id"] if bg is not None else None, "ink": {}, "src_ink": src_ink, "scale": None,
        "assets_dir": assets_dir, "bg_kind": bg_kind, "regime": S.band(W, H),
        "canvas": {"src": [src["canvas"]["width"], src["canvas"]["height"]], "dst": [W, H]},
        "units": units, "program": {"source": D.program(g.stream, g.labels), "chosen": None},
        "gamma": {"up": dict(D.GAMMA_UP), "down": dict(D.GAMMA_DOWN)},
        "font_src": {e["id"]: e["font_size"] for e in src["elements"] if e["type"] == "text"},
        "floors_px": {}, "hide_mode": HIDE_MODE,
    }


def _ink_map(out, assets_dir):
    ink = {}
    for e in out["elements"]:
        if C.visible(e):
            try:
                x0, y0, x1, y1 = T.ink_rect(e, assets_dir)
            except Exception:  # noqa: BLE001
                x0, y0, x1, y1 = e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]
            ink[e["id"]] = [round(x0, 2), round(y0, 2), round(x1 - x0, 2), round(y1 - y0, 2)]
    return ink


# ----------------------------------------------------------------------------- realisation
def realize(plan, g, src, target, assets_dir, base):
    W, H = target["width"], target["height"]
    W0, H0 = src["canvas"]["width"], src["canvas"]["height"]
    out = {e["id"]: copy.deepcopy(e) for e in src["elements"]}
    placed = set()
    hidden = set()
    min_z = min([int(e.get("z_index", 0) or 0) for e in src["elements"]] or [0])
    ctx = plan.ctx
    for e in g.background:
        out[e["id"]].update(x=0.0, y=0.0, width=float(W), height=float(H))
        placed.add(e["id"])
    occupied = []
    _realize_plan(plan, g, ctx, out, placed, hidden, occupied, assets_dir, top=True)
    # furniture: source corner if collision-free (rotated AABB), else mirrored corner, else hidden
    for u in g.furniture:
        if not _place_furniture(u, plan, ctx, out, occupied, W, H):
            for e in u.els:
                hidden.add(e["id"])
        else:
            placed.update(e["id"] for e in u.els)
    # texture: re-anchored relative position, kept round/aspect, in-bounds
    k = math.sqrt(min(W / W0, H / H0)) * math.sqrt(min(1.0, max(W / W0, H / H0)))
    for e in g.texture:
        o = out[e["id"]]
        w = min(e["width"] * k, W)
        h = min(e["height"] * k, H)
        if e.get("shape_type") == "ellipse":
            d = min(w, h, W, H)
            if abs(e["width"] - e["height"]) < 1:
                w = h = d
        cx, cy = (e["x"] + e["width"] / 2) / W0 * W, (e["y"] + e["height"] / 2) / H0 * H
        nx, ny = min(max(cx - w / 2, 0.0), W - w), min(max(cy - h / 2, 0.0), H - h)
        if min(w, h) <= 8 and any(_overlap((nx, ny, nx + w, ny + h), o, -1) for o in occupied):
            spot = None                 # a rule or divider must not strike through content: nearest free spot
            for step in range(1, 60):
                for dy, dx in ((step, 0), (-step, 0), (0, step), (0, -step)):
                    cy2 = ny + dy * 0.01 * H if dy else ny
                    cx2 = nx + dx * 0.01 * W if dx else nx
                    cy2, cx2 = min(max(cy2, 0.0), H - h), min(max(cx2, 0.0), W - w)
                    if not any(_overlap((cx2, cy2, cx2 + w, cy2 + h), o, -1) for o in occupied):
                        spot = (cx2, cy2)
                        break
                if spot:
                    break
            if spot is None:
                if HIDE_MODE != "never":
                    continue
            else:
                nx, ny = spot
        o.update(x=nx, y=ny, width=max(1.0, w), height=max(1.0, h))
        placed.add(e["id"])
    # everything else: hidden (dropped units, hidden assets, empty text, unplaced furniture)
    for e in src["elements"]:
        if e["id"] not in placed:
            hidden.add(e["id"])
    for eid in hidden:
        _hide(out[eid], src, W, H, min_z)
    elements = [out[e["id"]] for e in src["elements"]]
    result = {"canvas": {"width": int(W), "height": int(H)}, "elements": elements}
    info = copy.deepcopy(base)
    info["hidden"] = sorted(hidden, key=str)
    info["ink"] = _ink_map(result, assets_dir)
    info["scale"] = round(plan.z, 4)
    info["live_area"] = [round(v, 2) for v in plan.live]
    info["program"]["chosen"] = plan.program()
    info["energy"] = round(plan.energy, 4)
    info["energy_terms"] = {k: round(v, 4) for k, v in plan.terms.items() if abs(v) > 1e-9}
    info["floors_px"] = {e["id"]: int(math.ceil(D.FLOOR_JPX.get(S.text_role(u), 10) / ctx.js))
                         for it in S.all_items(plan) for u in [it.unit]
                         for e in ([u.text_el()] if u.text_el() is not None else [])}
    info["relax_level"] = getattr(plan, "level", 0)
    head_ids = [i for i, r in info["roles"].items() if r == "headline"]
    if head_ids and all(i in hidden for i in head_ids):
        info["mode"] = "brand_reminder"
    return result, info


def _realize_plan(plan, g, ctx, out, placed, hidden, occupied, assets_dir, top=False):
    for u in plan.dropped:
        for e in u.els:
            hidden.add(e["id"])
    for it in plan.items:
        _realize_item(it, ctx, out, placed, hidden, occupied, assets_dir)


def _realize_item(it, ctx, out, placed, hidden, occupied, assets_dir):
    u = it.unit
    if u.kind == "text":
        el = out[u.head["id"]]
        el.update(x=it.x, y=it.y, width=max(1.0, it.w), height=max(1.0, it.h), font_size=int(it.f))
        placed.add(el["id"])
        occupied.append((it.x, it.y, it.x + it.w, it.y + it.h))
    elif u.kind == "image":
        el = out[u.head["id"]]
        s = it.s
        bw, bh = u.head["width"] * s, u.head["height"] * s
        if ctx.disjoint:
            bx, by = it.x, it.y
        else:
            l, t, r, b = T.image_pad(u.head, bw, bh, assets_dir)
            bx, by = it.x - l, it.y - t
        el.update(x=bx, y=by, width=bw, height=bh)
        placed.add(el["id"])
        occupied.append((bx, by, bx + bw, by + bh) if ctx.disjoint else (it.x, it.y, it.x + it.w, it.y + it.h))
    elif u.kind == "pill":
        _pill(u, it.x, it.y, it.w, it.h, it.f, out)
        placed.update(e["id"] for e in u.els)
        occupied.append((it.x, it.y, it.x + it.w, it.y + it.h))
    elif u.kind == "chips":
        ws, hs = it.extra.get("ws", []), it.extra.get("hs", [])
        gap = u.gap_src * it.s
        total = sum(ws) + gap * (len(ws) - 1)
        x = it.x + max(0.0, (it.w - total) / 2)
        for p, w, h in zip(u.members, ws, hs):
            _pill(p, x, it.y + (it.h - h) / 2, w, h, it.f, out)
            x += w + gap
        placed.update(e["id"] for e in u.els)
        occupied.append((it.x, it.y, it.x + it.w, it.y + it.h))
    elif u.kind == "rigid":
        _rigid(u, it.x, it.y, it.s, out)
        placed.update(e["id"] for e in u.els)
        occupied.append((it.x, it.y, it.x + it.w, it.y + it.h))
    elif u.kind == "bracket":
        host = out[u.els[0]["id"]]
        x0, y0, x1, y1 = it.x, it.y, it.x + it.w, it.y + it.h
        lx, ly, lw, lh = it.sub.live if it.sub is not None else (x0, y0, it.w, it.h)
        if ctx.top:
            L, Tt, R, B = u.bleed
            px, py, pw, ph = ctx_live(ctx)
            if L and x0 <= px + ctx.m + 1:
                x0 = px
            if R and x1 >= px + pw - ctx.m - 1:
                x1 = px + pw
            if Tt and y0 <= py + ctx.m + 1:
                y0 = py
            if B and y1 >= py + ph - ctx.m - 1:
                y1 = py + ph
        r = float(u.els[0].get("corner_radius", 0) or 0)
        host.update(x=x0, y=y0, width=max(1.0, x1 - x0), height=max(1.0, y1 - y0))
        if r:
            host["corner_radius"] = min(r * ctx_scale(it), (x1 - x0) / 2, (y1 - y0) / 2)
        placed.add(host["id"])
        occupied.append((x0, y0, x1, y1))
        if it.sub is not None:
            sub_occ = []
            _realize_plan(it.sub, u.sub, ctx, out, placed, hidden, sub_occ, assets_dir)
            for e in u.sub.texture:
                o = out[e["id"]]
                sx, sy = (x1 - x0) / max(1.0, u.sub.W0), (y1 - y0) / max(1.0, u.sub.H0)
                k = min(sx, sy)
                w, h = max(1.0, e["width"] * k), max(1.0, e["height"] * k)
                cx = x0 + (e["x"] + e["width"] / 2) * sx
                cy = y0 + (e["y"] + e["height"] / 2) * sy
                o.update(x=min(max(cx - w / 2, x0), x1 - w), y=min(max(cy - h / 2, y0), y1 - h), width=w, height=h)
                placed.add(e["id"])
            for e in u.sub.hidden:
                hidden.add(e["id"])


def ctx_live(ctx):
    return getattr(ctx, "_live", (0.0, 0.0, ctx.W, ctx.H))


def ctx_scale(it):
    return it.sub.z if it.sub is not None else 1.0


def _pill(u, x, y, w, h, f, out):
    sh, lab = u.shape_el(), u.text_el()
    o = out[sh["id"]]
    o.update(x=x, y=y, width=max(1.0, w), height=max(1.0, h))
    r = float(sh.get("corner_radius", 0) or 0)
    if r:
        o["corner_radius"] = min(r * h / max(1.0, sh["height"]), h / 2, w / 2)
    asc, desc, cap, _ = T.metrics(lab, f)
    lh = T.text_h(lab, f, 1)
    lo = out[lab["id"]]
    ly = y + h / 2 - asc + cap / 2                       # optical: caps centred on the pill
    lo.update(x=x, y=ly, width=max(1.0, w), height=max(1.0, lh), font_size=int(f))


def _rigid(u, x, y, s, out):
    bx0, by0 = u.box[0], u.box[1]
    for e in u.els:
        o = out[e["id"]]
        ex0, ey0, _, _ = T.rot_aabb(e["x"], e["y"], e["width"], e["height"], float(e.get("rotation", 0) or 0))
        dx, dy = e["x"] - ex0, e["y"] - ey0
        o.update(x=x + (ex0 - bx0) * s + dx * s, y=y + (ey0 - by0) * s + dy * s,
                 width=max(1.0, e["width"] * s), height=max(1.0, e["height"] * s))
        if e["type"] == "text":
            o["font_size"] = max(1, int(float(e["font_size"]) * s))
        if e.get("corner_radius"):
            o["corner_radius"] = float(e["corner_radius"]) * s


def _place_furniture(u, plan, ctx, out, occupied, W, H):
    d = S.unit_dims(u, plan.zi, ctx)
    if d is None:
        return False
    m = 0.6 * ctx.m
    corners = [u.corner, u.corner[0] + ("R" if u.corner[1] == "L" else "L"),
               ("B" if u.corner[0] == "T" else "T") + u.corner[1]]
    rot = max((abs(float(e.get("rotation", 0) or 0)) for e in u.els), default=0.0)
    never = HIDE_MODE == "never"
    shrinks = (1.0, 0.8, 0.64, 0.5, 0.4, 0.3) if never else (1.0, 0.8, 0.64)
    for legible, overlap_ok in ((True, False), (False, False), (False, True)) if never else ((True, False),):
        for shrink in shrinks:
            bw, bh = d.extra.get("w_pref", d.w) * shrink, d.h * shrink
            if bw > 0.45 * W or bh > 0.45 * H:
                continue
            if legible:
                if u.kind == "rigid":
                    fs = [float(e["font_size"]) * d.s * shrink for e in u.els if e["type"] == "text"]
                else:
                    fs = [d.f * shrink]
                if fs and min(int(f) for f in fs) * ctx.js < S.FLOOR_JPX["badge_label"]:
                    continue                      # furniture text below the legibility floor: try smaller placements later
            rx0, ry0, rx1, ry1 = T.rot_aabb(0, 0, bw, bh, rot)
            aw, ah = rx1 - rx0, ry1 - ry0
            best = None
            for cn in corners:
                ax = m if cn[1] == "L" else W - m - aw
                ay = m if cn[0] == "T" else H - m - ah
                rect = (ax, ay, ax + aw, ay + ah)
                if ax < 0 or ay < 0:
                    continue
                hits = sum(max(0.0, min(rect[2], o[2]) - max(rect[0], o[0])) * max(0.0, min(rect[3], o[3]) - max(rect[1], o[1]))
                           for o in occupied if _overlap(rect, o, 4 if not overlap_ok else -1))
                if hits == 0 or overlap_ok:
                    if best is None or hits < best[0]:
                        best = (hits, rect, aw, ah)
                    if hits == 0:
                        break
            if best is None:
                continue
            _, rect, aw, ah = best
            ax, ay = rect[0], rect[1]
            bx, by = ax + (aw - bw) / 2, ay + (ah - bh) / 2          # unrotated box centred in the AABB
            if u.kind == "pill":
                _pill(u, bx, by, bw, bh, max(1, int(d.f * shrink)), out)
            elif u.kind == "chips":
                f = max(1, int(d.f * shrink))
                x = bx
                for p, w, h in zip(u.members, d.extra["ws"], d.extra["hs"]):
                    _pill(p, x, by + (bh - h * shrink) / 2, w * shrink, h * shrink, f, out)
                    x += w * shrink + u.gap_src * d.s * shrink
            else:
                _rigid(u, bx, by, d.s * shrink, out)
            occupied.append(rect)
            return True
    return False


def _overlap(a, b, pad=0.0):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def _hide(el, src, W, H, min_z):
    W0, H0 = src["canvas"]["width"], src["canvas"]["height"]
    s = min(W / W0, H / H0)
    cx, cy = (el["x"] + el["width"] / 2) * W / W0, (el["y"] + el["height"] / 2) * H / H0
    w, h = max(1.0, min(W, el["width"] * s)), max(1.0, min(H, el["height"] * s))
    el.update(x=min(max(cx - w / 2, 0.0), W - w), y=min(max(cy - h / 2, 0.0), H - h), width=w, height=h)
    if el["type"] == "text":
        el["font_size"] = max(1, int(float(el.get("font_size", 12)) * s))
    if el.get("rotation"):
        el["rotation"] = el["rotation"]          # unchanged; hidden elements are exempt from the AABB rule
    C.hide_el(el, "alpha" if HIDE_MODE == "never_text" else HIDE_MODE, min_z)
