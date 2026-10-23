"""Role inference WITHOUT ids: geometry + typography + z-order + groups + asset PIXELS (alpha ink stats)."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT = Path(__file__).resolve().parents[4]
ASSETS = ROOT / "brand_kit/assets"
_cache = {}

def asset_stats(asset_id):
    if asset_id in _cache: return _cache[asset_id]
    p = ASSETS / str(asset_id)
    if not p.is_file():
        _cache[asset_id] = None; return None
    im = Image.open(p); a = np.asarray(im.convert("RGBA"))[..., 3]
    has_alpha = im.mode in ("RGBA", "LA", "PA") and (a < 250).mean() > 0.01
    ys, xs = np.nonzero(a > 8)
    x0, y0, x1, y1 = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(xs) else (0, 0, a.shape[1], a.shape[0])
    fill = (a[y0:y1, x0:x1] > 8).mean()
    s = dict(w=im.width, h=im.height, alpha=has_alpha, ink=(x0 / im.width, y0 / im.height, x1 / im.width, y1 / im.height), fill=fill)
    _cache[asset_id] = s; return s

def infer_roles(src):
    cw, ch = src["canvas"]["width"], src["canvas"]["height"]; A = cw * ch
    els = src["elements"]; roles = {}
    groups = {}
    for e in els:
        if e.get("group_id"): groups.setdefault(e["group_id"], []).append(e)
    for e in els:
        area = e["width"] * e["height"]
        if e["type"] in ("image", "shape") and area >= 0.9 * A and e.get("z_index", 0) == min(x.get("z_index", 0) for x in els):
            roles[e["id"]] = "background"
    texts = [e for e in els if e["type"] == "text" and not e.get("group_id")]
    texts.sort(key=lambda e: (-e["font_size"], -len(e["content"])))
    if texts: roles[texts[0]["id"]] = "headline"
    def rgb(c): return [float(v) for v in c[c.index("(") + 1:-1].split(",")[:3]]
    head_rgb = rgb(texts[0]["color"]) if texts else None
    for e in texts[1:]:
        small = e["font_size"] <= 0.4 * texts[0]["font_size"]
        bottomish = e["y"] > 0.85 * ch
        c = rgb(e["color"]); sat = (max(c) - min(c)) / 255
        if small and bottomish and len(e["content"]) > 50:
            roles[e["id"]] = "legal"
        elif len(e["content"].split()) <= 5 and e.get("font_weight") == "bold" and sat > 0.3 and c != head_rgb:
            roles[e["id"]] = "cta_text"          # text-only call to action (accent colour, short, bold)
        else:
            roles[e["id"]] = "subhead"
    pills = []
    for gid, mem in groups.items():
        shp = [m for m in mem if m["type"] == "shape"]; txt = [m for m in mem if m["type"] == "text"]
        rot = any(abs(m.get("rotation", 0)) > 1 for m in mem)
        if rot:
            for m in mem: roles[m["id"]] = "sticker"
            continue
        if shp and txt: pills.append((gid, shp[0], txt[0]))
    if pills:
        # CTA = largest pill (area), tie-break lower on canvas; rest are badges
        pills.sort(key=lambda t: (-t[1]["width"] * t[1]["height"], -t[1]["y"]))
        for i, (gid, s, t) in enumerate(pills):
            r = "cta" if i == 0 else "badge"
            roles[s["id"]] = r + "_bg"; roles[t["id"]] = r + "_label"
    imgs = [e for e in els if e["type"] == "image" and e["id"] not in roles]
    scored = []
    for e in imgs:
        st = asset_stats(e.get("asset_id"))
        if st is None:
            roles[e["id"]] = "unseen_image"; continue
        asp = e["width"] / e["height"]
        logo_score = int(st["fill"] < 0.4) + int(asp >= 2) + int(e["y"] + e["height"] / 2 < 0.3 * ch) + int(e["width"] * e["height"] < 0.08 * A)
        scored.append((logo_score, e))
    scored.sort(key=lambda t: -t[0])
    for i, (sc, e) in enumerate(scored):
        roles[e["id"]] = "logo" if i == 0 and sc >= 3 else "hero"
    for e in els:
        if e["id"] in roles: continue
        if e["type"] == "shape":
            alpha = e.get("opacity", 1.0) * float(e["fill_color"].split(",")[-1].strip(" )"))
            roles[e["id"]] = "decoration" if alpha <= 0.35 or e["x"] < 0 or e["y"] < 0 else "panel"
        else:
            roles[e["id"]] = "other"
    return roles

if __name__ == "__main__":
    import json
    for p in sorted((ROOT / "input").glob("*.json")):
        src = json.loads(p.read_text())["source"]
        r = infer_roles(src)
        ok = sum(1 for k, v in r.items() if v.split("_")[0] in k or (k.startswith("ribbon") and v == "sticker")
                 or (k == "product" and v == "hero") or (k.startswith("deco") and v == "decoration")
                 or (k == "holiday_watermark" and v == "unseen_image") or (k == "legal_text" and v == "legal")
                 or (k.startswith("badge") and v.startswith("badge")))
        print(f"{p.stem}: {ok}/{len(r)} roles match id semantics ->", r)
