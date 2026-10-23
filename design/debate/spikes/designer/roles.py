"""Spike: label-free role inference (DESIGNER proposal).

Infers semantic roles from geometry, typography, z-order, grouping and asset
pixels only. Ids are NEVER read (the test harness renames them to e0..eN).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

CTA_VERBS = {
    "shop", "buy", "order", "get", "try", "learn", "discover", "explore", "book",
    "sign", "join", "start", "download", "subscribe", "register", "claim", "see",
    "find", "watch", "play", "save", "call", "visit", "reserve", "apply", "donate",
}


def _alpha(el):
    m = re.search(r"rgba?\([^)]*,\s*([\d.]+)\s*\)", el.get("fill_color") or el.get("color") or "")
    a = float(m.group(1)) if m and (el.get("fill_color") or "").count(",") == 3 else 1.0
    return a * float(el.get("opacity", 1.0))


def _area(el):
    return max(0.0, el["width"]) * max(0.0, el["height"])


def _inside(inner, outer, tol=0.25):
    """True if inner's centre is inside outer and inner mostly overlaps it."""
    cx, cy = inner["x"] + inner["width"] / 2, inner["y"] + inner["height"] / 2
    if not (outer["x"] <= cx <= outer["x"] + outer["width"] and outer["y"] <= cy <= outer["y"] + outer["height"]):
        return False
    ix = max(0, min(inner["x"] + inner["width"], outer["x"] + outer["width"]) - max(inner["x"], outer["x"]))
    iy = max(0, min(inner["y"] + inner["height"], outer["y"] + outer["height"]) - max(inner["y"], outer["y"]))
    return ix * iy >= (1 - tol) * min(_area(inner), _area(outer))


def asset_stats(assets_dir: str, asset_id: str):
    p = Path(assets_dir) / (asset_id or "")
    if not asset_id or not p.is_file():
        return None
    im = Image.open(p).convert("RGBA")
    a = np.asarray(im)
    alpha = a[..., 3]
    ys, xs = np.where(alpha > 10)
    if len(xs) == 0:
        return {"size": im.size, "opaque": 0.0, "bbox": (0, 0, im.width, im.height)}
    return {
        "size": im.size,
        "opaque": float((alpha > 10).mean()),
        "bbox": (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
    }


def infer_roles(design: dict, assets_dir: str) -> dict:
    W, H = design["canvas"]["width"], design["canvas"]["height"]
    A = W * H
    els = design["elements"]
    roles: dict[str, str] = {}
    meta: dict[str, dict] = {}

    # 1. background: covers >= 90% of the canvas, lowest z among such.
    covering = [e for e in els if e["type"] in ("image", "shape")
                and _area(e) >= 0.9 * A and e["x"] <= 0.05 * W and e["y"] <= 0.05 * H]
    if covering:
        bg = min(covering, key=lambda e: e.get("z_index", 0))
        roles[bg["id"]] = "background"

    # 2. chips: a shape that contains a text (shared group_id OR geometric containment).
    texts = [e for e in els if e["type"] == "text"]
    shapes = [e for e in els if e["type"] == "shape" and e["id"] not in roles]
    chips = []  # (shape, text)
    used_text = set()
    # grouped pairs first (designer-declared), then solid shapes that geometrically hold a text.
    ordered = sorted(shapes, key=lambda s: 0 if s.get("group_id") else 1)
    for s in ordered:
        grouped = [t for t in texts if t["id"] not in used_text and s.get("group_id")
                   and t.get("group_id") == s.get("group_id")]
        contained = [t for t in texts if t["id"] not in used_text and _alpha(s) >= 0.5 and _inside(t, s)]
        cands = grouped or contained
        if cands and _area(s) < 0.25 * A:
            t = max(cands, key=lambda t: t.get("font_size", 0))
            used_text.add(t["id"])
            chips.append((s, t))

    # 3. decorations: remaining shapes (no label), or anything faint.
    chip_shape_ids = {s["id"] for s, _ in chips}
    for s in shapes:
        if s["id"] not in chip_shape_ids:
            roles[s["id"]] = "decoration"

    # 4. images: broken / logo / hero.
    imgs = [e for e in els if e["type"] == "image" and e["id"] not in roles]
    live = []
    for im in imgs:
        st = asset_stats(assets_dir, im.get("asset_id"))
        meta[im["id"]] = {"asset": st}
        if st is None:
            roles[im["id"]] = "broken"
        elif _alpha(im) < 0.3:
            roles[im["id"]] = "decoration"
        else:
            live.append((im, st))
    if live:
        def logo_score(im, st):
            w, h = st["size"]
            bx0, by0, bx1, by1 = st["bbox"]
            content_ar = (bx1 - bx0) / max(1, by1 - by0)
            s = 0.0
            s += 1.0 if _area(im) < 0.08 * A else -1.0          # small
            s += 1.0 if st["opaque"] < 0.35 else 0.0              # cut-out / mark
            s += 0.7 if (im["y"] + im["height"] / 2) < 0.2 * H or (im["y"] + im["height"] / 2) > 0.85 * H else 0.0
            s += 0.5 if im["width"] / max(1, im["height"]) > 1.8 else 0.0  # lockups are wide
            s += 0.3 if im.get("z_index", 0) >= max(e.get("z_index", 0) for e in els) - 1 else 0.0
            return s
        ranked = sorted(live, key=lambda p: -_area(p[0]))
        hero = ranked[0][0]
        logo = max(live, key=lambda p: logo_score(*p))[0]
        if len(live) == 1:
            if logo_score(*live[0]) >= 1.5:
                roles[live[0][0]["id"]] = "logo"
            else:
                roles[live[0][0]["id"]] = "hero"
        else:
            if logo["id"] == hero["id"]:
                logo = ranked[-1][0]
            roles[logo["id"]] = "logo"
            roles[hero["id"]] = "hero"
            for im, _ in live:
                roles.setdefault(im["id"], "secondary_image")

    # 5. chips -> cta / badge / sticker
    def cta_score(s, t):
        words = re.findall(r"[A-Za-z]+", t["content"])
        first = words[0].lower() if words else ""
        sc = 0.0
        sc += 2.0 if first in CTA_VERBS else 0.0
        sc += 1.0 if not t["content"].isupper() else 0.0
        sc += _area(s) / A * 20
        sc += 0.5 * ((s["y"] + s["height"] / 2) / H)   # actions live low
        sc -= 3.0 if abs(s.get("rotation", 0)) > 2 else 0.0
        return sc
    if chips:
        best = max(chips, key=lambda p: cta_score(*p))
        for s, t in chips:
            if s["id"] == best[0]["id"] and cta_score(s, t) >= 1.5:
                r = "cta"
            elif abs(s.get("rotation", 0)) > 2:
                r = "sticker"
            else:
                r = "badge"
            roles[s["id"]], roles[t["id"]] = r + "_bg", r + "_label"
            meta[s["id"]] = {"partner": t["id"]}
            meta[t["id"]] = {"partner": s["id"]}

    # 6. free text: headline / subhead / legal / body by typographic prominence.
    free = [t for t in texts if t["id"] not in used_text]
    if free:
        def prom(t):
            return t["font_size"] * (1.25 if t.get("font_weight") == "bold" else 1.0)
        head = max(free, key=prom)
        roles[head["id"]] = "headline"
        sizes = sorted(t["font_size"] for t in free)
        for t in free:
            if t is head:
                continue
            low = (t["y"] + t["height"] / 2) > 0.85 * H
            small = t["font_size"] <= 0.55 * head["font_size"] and t["font_size"] <= sizes[0]
            faint = _alpha_text(t) < 0.75
            if (small and (low or faint or len(t["content"]) > 60)) and t["font_size"] < 16:
                roles[t["id"]] = "legal"
            elif any(w.lower() in CTA_VERBS for w in re.findall(r"[A-Za-z]+", t["content"])[:1]) and len(t["content"]) < 32:
                roles[t["id"]] = "cta_text"
            else:
                roles[t["id"]] = "subhead" if "subhead" not in roles.values() else "body"
    for e in els:
        roles.setdefault(e["id"], "unknown")
    return roles, meta


def _alpha_text(t):
    m = re.search(r"rgba\([^)]*,\s*([\d.]+)\s*\)", t.get("color", ""))
    return (float(m.group(1)) if m else 1.0) * float(t.get("opacity", 1.0))


if __name__ == "__main__":
    import json, random
    for name in ["level1_warmup", "level2_core", "level3_advanced"]:
        task = json.load(open(f"input/chameleon_sample_{name}.json"))
        src = task["source"]
        # Anonymise ids AND group ids so nothing semantic leaks.
        rnd = random.Random(7)
        els = [dict(e) for e in src["elements"]]
        rnd.shuffle(els)
        idmap, gmap = {}, {}
        for i, e in enumerate(els):
            idmap[e["id"]] = f"e{i}"
            e["id"] = f"e{i}"
            if e.get("group_id"):
                gmap.setdefault(e["group_id"], f"g{len(gmap)}")
                e["group_id"] = gmap[e["group_id"]]
        roles, _ = infer_roles({"canvas": src["canvas"], "elements": els}, "brand_kit/assets")
        inv = {v: k for k, v in idmap.items()}
        print(f"--- {name}")
        for k in sorted(roles, key=lambda k: inv[k]):
            print(f"   {inv[k]:20s} -> {roles[k]}")
