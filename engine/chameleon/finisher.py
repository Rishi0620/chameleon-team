"""DESIGNER — finisher: the typesetting & optics pass of the bracketed-galley prototype.

    finish(source, output, info) -> output

Pure: never mutates its arguments. Safe on ANY engine's output: every pass is applied to a copy and
kept only if (a) the output contract still holds (same ids/order, in-bounds incl. rotated AABB,
image aspect unchanged, integer font sizes, text w/h >= 1, no NEW box overlap between flow elements)
and (b) the designer rule score (rules.check: hard count, then soft count) does not get worse.
If anything unexpected raises, the input is returned unchanged.

Passes (in order):
  P1 normalise      integer font sizes; honest text box heights (only when they fit)
  P2 pills          caps optically centred in pills; CTA label >= 12 judge-px (pill grows); label <= headline/1.2
  P3 balance        balanced wrap: narrowest integer width keeping the line count (text-wrap: balance)
  P4 rag            headline: no widow, no one-word lines (3+ words), no line ending on a function word
  P5 strip unit     H<=120: message stack tight (headline+subhead as one unit), centred on the midline
  P6 margins        W/H>=2: columns redistributed for equal optical outer margins and equal gutters
  P7 rhythm         H/W>=1.2: stack gaps snapped to {1,2,3}x a rhythm unit (span preserved)
  P8 decorations    translucent discs never over the logo / under the CTA / over text: halo or corner
  P9 furniture      rotated stickers keep their angle: source corner -> mirrored corner -> hero shoulder

Exactness: text is measured with the renderer's own `char_widths`/`wrap_text` at int(font_size).
"""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path
from typing import Any

# ============================================================================ renderer metrics

_FM = None
_FM_DIR = None
_WCACHE: dict = {}
_MCACHE: dict = {}
_ASSET_CACHE: dict = {}


def _fm(fonts_dir: str = "brand_kit/fonts"):
    global _FM, _FM_DIR
    if _FM is None or _FM_DIR != fonts_dir:
        from renderer.converter.brand_fonts import load_brand_font_manager
        _FM, _FM_DIR = load_brand_font_manager(fonts_dir), fonts_dir
    return _FM


def font_args(e):
    bold = (e.get("font_weight") or "regular").lower() in ("bold", "semibold", "extrabold", "black")
    ital = e.get("font_style") == "italic"
    weight = "bold" if bold else "regular"
    style = "bolditalic" if bold and ital else "bold" if bold else "italic" if ital else "regular"
    return e.get("font_family", "Solstice Sans"), weight, style


def char_w(e, fs):
    from renderer.converter.wrap import char_widths
    key = (font_args(e), int(fs), e.get("content", ""))
    if key not in _WCACHE:
        _WCACHE[key] = char_widths(_fm(), *font_args(e), int(fs), e.get("content", "")) if e.get("content") else []
    return _WCACHE[key]


def vmetrics(e):
    """(ascent, cap height, descent) in em, from skia, exactly as the renderer's font."""
    key = font_args(e)
    if key not in _MCACHE:
        import skia
        tf = skia.Typeface.MakeFromData(_fm().lookup(*key))
        m = skia.Font(tf, 100).getMetrics()
        cap = m.fCapHeight / 100 if m.fCapHeight > 0 else 0.7
        _MCACHE[key] = (-m.fAscent / 100, cap, m.fDescent / 100)
    return _MCACHE[key]


def wrap_lines(e, fs, width):
    """[(text, width_px)] exactly as the converter wraps and the renderer draws."""
    from renderer.converter.wrap import wrap_text
    content = e.get("content", "")
    if not content:
        return [("", 0.0)]
    ws = char_w(e, fs)
    wrapped = wrap_text(content, ws, float(width))
    out, start = [], 0
    for i, ch in enumerate(wrapped + "\n"):
        if ch == "\n":
            out.append((wrapped[start:i], float(sum(ws[start:i]))))
            start = i + 1
    return out


def text_height(e, fs, n):
    asc, cap, desc = vmetrics(e)
    return (n - 1) * e.get("line_height", 1.2) * fs + (asc + desc) * fs


def text_ink(e):
    fs = int(e["font_size"])
    lines = wrap_lines(e, fs, e["width"])
    asc, cap, desc = vmetrics(e)
    w = max(lw for _, lw in lines) if lines else 0.0
    al = e.get("text_align", "left")
    x0 = {"center": e["x"] + (e["width"] - w) / 2, "right": e["x"] + e["width"] - w}.get(al, e["x"])
    top = e["y"] + (asc - cap) * fs
    bottom = e["y"] + (len(lines) - 1) * e.get("line_height", 1.2) * fs + asc * fs + 0.21 * fs
    return (x0, top, x0 + w, bottom)


def text_ink_area(e):
    """Typographic weight: sum over lines of line width x (cap height + descender) - independent of
    how the lines are broken (a bbox would double when a headline breaks into a ragged second line)."""
    fs = int(e["font_size"])
    asc, cap, desc = vmetrics(e)
    return sum(lw for _, lw in wrap_lines(e, fs, e["width"])) * (cap + 0.21) * fs


def asset_bbox(assets_dir, asset_id):
    key = (assets_dir, asset_id)
    if key not in _ASSET_CACHE:
        p = Path(assets_dir or "brand_kit/assets") / (asset_id or "")
        val = None
        if asset_id and p.is_file():
            import numpy as np
            from PIL import Image
            im = Image.open(p).convert("RGBA")
            a = np.asarray(im)[..., 3]
            ys, xs = np.where(a > 10)
            bb = (0, 0, im.width, im.height) if len(xs) == 0 else (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            val = {"size": im.size, "bbox": bb, "opaque": float((a > 10).mean())}
        _ASSET_CACHE[key] = val
    return _ASSET_CACHE[key]


def image_ink(e, assets_dir):
    st = asset_bbox(assets_dir, e.get("asset_id"))
    if st is None or e.get("fit") in ("cover", "fill"):
        return (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"])
    iw, ih = st["size"]
    bw, bh = max(1e-6, e["width"]), max(1e-6, e["height"])
    s = min(bw / iw, bh / ih)
    ox, oy = (bw - iw * s) / 2, (bh - ih * s) / 2
    x0, y0, x1, y1 = st["bbox"]
    return (e["x"] + ox + x0 * s, e["y"] + oy + y0 * s, e["x"] + ox + x1 * s, e["y"] + oy + y1 * s)


def ink(e, assets_dir):
    if e["type"] == "text":
        return text_ink(e)
    if e["type"] == "image":
        return image_ink(e, assets_dir)
    return box(e)


def box(e):
    return (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"])


def rot_aabb(e):
    r = math.radians(e.get("rotation", 0) or 0)
    if abs(r) < 1e-9:
        return box(e)
    c, s = abs(math.cos(r)), abs(math.sin(r))
    w, h = e["width"] * c + e["height"] * s, e["width"] * s + e["height"] * c
    cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def inter(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def alpha_of(c):
    m = re.match(r"\s*rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*([\d.]+)\s*\)", c or "")
    return float(m.group(1)) if m else 1.0


def visible(e):
    if float(e.get("opacity", 1) or 0) <= 0.01:
        return False
    if e["type"] == "text" and alpha_of(e.get("color")) <= 0.01:
        return False
    if e["type"] == "shape" and alpha_of(e.get("fill_color")) <= 0.01:
        return False
    return True


def judge_scale(W, H):
    return min(1.0, 1024 / max(W, H))

# ============================================================================ roles (canonical vocabulary)

CTA_VERBS = {"shop", "buy", "order", "get", "try", "learn", "discover", "explore", "book", "sign", "join",
             "start", "download", "subscribe", "register", "claim", "see", "find", "watch", "play", "save",
             "call", "visit", "reserve", "apply", "donate", "taste"}
FUNCTION_WORDS = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "&", "with", "at", "by", "or", "from",
                  "your", "our", "its", "this", "that", "into"}


def infer_roles(src, assets_dir):
    """Fallback role inference (no ids). Canonical vocabulary of the round-3 brief."""
    W, H = src["canvas"]["width"], src["canvas"]["height"]
    A = W * H
    els = src["elements"]
    roles, partner = {}, {}
    fill_a = lambda s: alpha_of(s.get("fill_color")) * float(s.get("opacity", 1))  # noqa: E731
    cover = [e for e in els if e["type"] in ("image", "shape") and area(box(e)) >= 0.9 * A
             and e["x"] <= 0.05 * W and e["y"] <= 0.05 * H]
    if cover:
        roles[min(cover, key=lambda e: e.get("z_index", 0))["id"]] = "background"
    texts = [e for e in els if e["type"] == "text"]
    shapes = [e for e in els if e["type"] == "shape" and e["id"] not in roles]
    used = set()

    def inside(t, s):
        cx, cy = t["x"] + t["width"] / 2, t["y"] + t["height"] / 2
        return s["x"] <= cx <= s["x"] + s["width"] and s["y"] <= cy <= s["y"] + s["height"]
    chips = []
    for s in sorted(shapes, key=lambda s: 0 if s.get("group_id") else 1):
        g = [t for t in texts if t["id"] not in used and s.get("group_id") and t.get("group_id") == s.get("group_id")]
        c = [t for t in texts if t["id"] not in used and fill_a(s) >= 0.5 and inside(t, s)]
        cand = g or c
        if cand and area(box(s)) < 0.06 * A:
            t = max(cand, key=lambda t: t.get("font_size", 0))
            used.add(t["id"])
            chips.append((s, t))
    chip_ids = {s["id"] for s, _ in chips}
    # panels: big opaque shapes holding content above them
    content = [e for e in els if e["id"] not in roles]
    for s in shapes:
        if s["id"] in chip_ids:
            continue
        if fill_a(s) >= 0.5 and area(box(s)) >= 0.06 * A and any(
                e is not s and e.get("z_index", 0) >= s.get("z_index", 0) and inside(e, s) for e in content):
            roles[s["id"]] = "panel"
        else:
            roles[s["id"]] = "decoration"
    imgs = [e for e in els if e["type"] == "image" and e["id"] not in roles]
    live = []
    for im in imgs:
        st = asset_bbox(assets_dir, im.get("asset_id"))
        if st is None:
            roles[im["id"]] = "unknown"          # unresolvable asset
        elif float(im.get("opacity", 1)) < 0.3:
            roles[im["id"]] = "decoration"
        else:
            live.append((im, st))
    if live:
        top_z = max(e.get("z_index", 0) for e in els)

        def logo_score(im, st):
            cy = (im["y"] + im["height"] / 2) / H
            return ((1.0 if area(box(im)) < 0.08 * A else -1.0) + (1.0 if st["opaque"] < 0.35 else 0.0)
                    + (0.7 if cy < 0.2 or cy > 0.85 else 0.0) + (0.5 if im["width"] / max(1, im["height"]) > 1.8 else 0.0)
                    + (0.3 if im.get("z_index", 0) >= top_z - 1 else 0.0))
        hero = max(live, key=lambda p: area(box(p[0])))[0]
        logo = max(live, key=lambda p: logo_score(*p))[0]
        if len(live) == 1:
            roles[live[0][0]["id"]] = "logo" if logo_score(*live[0]) >= 1.5 else "hero"
        else:
            if logo["id"] == hero["id"]:
                logo = min(live, key=lambda p: area(box(p[0])))[0]
            roles[logo["id"]], roles[hero["id"]] = "logo", "hero"
            for im, _ in live:
                roles.setdefault(im["id"], "hero")

    def cta_score(s, t):
        words = re.findall(r"[A-Za-z]+", t.get("content", ""))
        return ((2.0 if words and words[0].lower() in CTA_VERBS else 0.0) + (1.0 if not t["content"].isupper() else 0.0)
                + area(box(s)) / A * 20 + 0.5 * (s["y"] + s["height"] / 2) / H - (3.0 if abs(s.get("rotation", 0) or 0) > 2 else 0))
    if chips:
        best = max(chips, key=lambda p: cta_score(*p))
        for s, t in chips:
            if s is best[0] and cta_score(s, t) >= 1.5:
                roles[s["id"]], roles[t["id"]] = "cta_shape", "cta_label"
            elif abs(s.get("rotation", 0) or 0) > 2:
                roles[s["id"]], roles[t["id"]] = "furniture", "furniture"
            else:
                roles[s["id"]], roles[t["id"]] = "badge_shape", "badge_label"
            partner[s["id"]], partner[t["id"]] = t["id"], s["id"]
    free = [t for t in texts if t["id"] not in used]
    if free:
        prom = lambda t: t["font_size"] * (1.25 if (t.get("font_weight") == "bold") else 1.0)  # noqa: E731
        head = max(free, key=prom)
        roles[head["id"]] = "headline"
        smallest = min(t["font_size"] for t in free)
        have_sub = False
        for t in sorted(free, key=lambda t: t["y"]):
            if t is head:
                continue
            low = (t["y"] + t["height"] / 2) > 0.85 * H
            faint = alpha_of(t.get("color")) * float(t.get("opacity", 1)) < 0.75
            if t["font_size"] <= 0.55 * head["font_size"] and t["font_size"] <= smallest and t["font_size"] < 16 and (
                    low or faint or len(t["content"]) > 60):
                roles[t["id"]] = "legal"
            elif re.findall(r"[A-Za-z]+", t["content"])[:1] and re.findall(r"[A-Za-z]+", t["content"])[0].lower() in CTA_VERBS \
                    and len(t["content"]) < 32:
                roles[t["id"]] = "cta_label"
            elif not have_sub:
                roles[t["id"]], have_sub = "subhead", True
            else:
                roles[t["id"]] = "body"
    for e in els:
        roles.setdefault(e["id"], "unknown")
    return roles, partner


class Ctx:
    """Everything a pass needs, built once from (source, output, info)."""

    def __init__(self, source, output, info):
        info = info or {}
        self.info = info
        self.src = source
        self.W, self.H = output["canvas"]["width"], output["canvas"]["height"]
        self.sW, self.sH = source["canvas"]["width"], source["canvas"]["height"]
        self.assets = info.get("assets_dir") or "brand_kit/assets"
        fb_roles, partner = infer_roles(source, self.assets)
        roles = dict(fb_roles)
        for k, v in (info.get("roles") or {}).items():
            roles[k] = v
        # normalise a few aliases other modules might emit
        alias = {"cta_bg": "cta_shape", "badge_bg": "badge_shape", "sticker_bg": "furniture", "sticker_label": "furniture",
                 "cta_text": "cta_label", "broken": "unknown", "secondary_image": "hero"}
        self.roles = {k: alias.get(v, v) for k, v in roles.items()}
        # containers: host -> riders (info first, else chips + panels from fallback inference)
        cont = {k: list(v) for k, v in (info.get("containers") or {}).items()}
        # chips (pill + label) are containers too, whether or not the decompiler lists them: take them
        # from shared group_ids (shape + text) and from the fallback pairing
        typ = {e["id"]: e["type"] for e in source["elements"]}
        grp = {}
        for e in source["elements"]:
            if e.get("group_id"):
                grp.setdefault(e["group_id"], []).append(e["id"])
        for ids_ in grp.values():
            shapes_ = [i for i in ids_ if typ[i] == "shape"]
            texts_ = [i for i in ids_ if typ[i] == "text"]
            if len(shapes_) == 1 and texts_ and shapes_[0] not in cont:
                cont[shapes_[0]] = texts_
        for a, b in partner.items():
            if typ.get(a) == "shape" and a not in cont and not any(b in v for v in cont.values()):
                cont[a] = [b]
        if not info.get("containers"):
            for e in source["elements"]:
                if self.roles.get(e["id"]) == "panel" and e["id"] not in cont:
                    cont[e["id"]] = [o["id"] for o in source["elements"] if o is not e and _center_in(o, e)
                                     and o.get("z_index", 0) >= e.get("z_index", 0)]
        self.containers = cont
        self.host_of = {r: h for h, rs in cont.items() for r in rs}
        groups = {k: list(v) for k, v in (info.get("groups") or {}).items()}
        if not groups:
            for e in source["elements"]:
                if e.get("group_id"):
                    groups.setdefault(e["group_id"], []).append(e["id"])
        self.group_of = {i: g for g, ids in groups.items() for i in ids}
        self.byid_src = {e["id"]: e for e in source["elements"]}
        self.layered = set(info.get("layered") or [])      # fine-print band: obstacles, never movers
        self.src_like = source

    def _type(self, i):
        e = next((x for x in self.src["elements"] if x["id"] == i), None)
        return e["type"] if e else None

    def related(self, a, b):
        """Pairs allowed to overlap: same group, host/rider (either way), same host."""
        if a == b:
            return True
        ga, gb = self.group_of.get(a), self.group_of.get(b)
        if ga is not None and ga == gb:
            return True
        if self.host_of.get(a) == b or self.host_of.get(b) == a:
            return True
        ha, hb = self.host_of.get(a), self.host_of.get(b)
        return ha is not None and ha == hb and self.roles.get(ha) != "panel"

    def is_flow(self, e):
        return visible(e) and self.roles.get(e["id"]) not in ("background", "decoration", "panel", "unknown")


def _center_in(o, s):
    cx, cy = o["x"] + o["width"] / 2, o["y"] + o["height"] / 2
    return s["x"] <= cx <= s["x"] + s["width"] and s["y"] <= cy <= s["y"] + s["height"]

# ============================================================================ contract


def overlap_pairs(ctx, doc):
    els = [e for e in doc["elements"] if ctx.is_flow(e)]
    pairs = set()
    for i in range(len(els)):
        for j in range(i + 1, len(els)):
            a, b = els[i], els[j]
            if ctx.related(a["id"], b["id"]):
                continue
            if inter(box(a), box(b)) > 0.5:
                pairs.add(tuple(sorted((a["id"], b["id"]))))
    return pairs


def contract_problems(ctx, base, cand):
    """Hard contract of the finisher relative to its INPUT `base`."""
    probs = []
    if [e["id"] for e in base["elements"]] != [e["id"] for e in cand["elements"]]:
        return ["ids/order changed"]
    W, H = cand["canvas"]["width"], cand["canvas"]["height"]
    for b, c in zip(base["elements"], cand["elements"]):
        for k in ("x", "y", "width", "height"):
            v = c.get(k)
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                probs.append(f"{c['id']}: bad {k}")
        if c["type"] == "text":
            if not isinstance(c.get("font_size"), int) or c["font_size"] < 1:
                probs.append(f"{c['id']}: font_size not int>=1")
            if c["width"] < 1 or c["height"] < 1:
                probs.append(f"{c['id']}: text w/h < 1")
            if c.get("content") != b.get("content") or c.get("font_family") != b.get("font_family"):
                probs.append(f"{c['id']}: content/font changed")
        moved = any(abs(c[k] - b[k]) > 1e-6 for k in ("x", "y", "width", "height")) or c.get("rotation") != b.get("rotation")
        bx = box(c)
        if moved and (bx[0] < -0.5 or bx[1] < -0.5 or bx[2] > W + 0.5 or bx[3] > H + 0.5):
            probs.append(f"{c['id']}: off-canvas")
        if moved and visible(c) and abs(c.get("rotation", 0) or 0) > 0.01:
            r = rot_aabb(c)
            if r[0] < -0.5 or r[1] < -0.5 or r[2] > W + 0.5 or r[3] > H + 0.5:
                probs.append(f"{c['id']}: rotated corners clipped")
        if c["type"] == "image" and c.get("fit", "contain") != "cover" and b["height"] > 0 and c["height"] > 0:
            if abs((c["width"] / c["height"]) / (b["width"] / b["height"]) - 1) > 0.01:
                probs.append(f"{c['id']}: image aspect changed")
    new = overlap_pairs(ctx, cand) - overlap_pairs(ctx, base)
    probs += [f"new box overlap {a}x{b}" for a, b in sorted(new)]
    return probs

# ============================================================================ helpers for passes


def els_by_role(ctx, doc, *roles_):
    return [e for e in doc["elements"] if ctx.roles.get(e["id"]) in roles_ and visible(e)]


def by_id(doc):
    return {e["id"]: e for e in doc["elements"]}


def balanced_int_width(e, fs, maxw, n_target=None):
    """Narrowest INTEGER width giving `n_target` lines (default: the count at maxw). Deterministic."""
    n = len(wrap_lines(e, fs, maxw)) if n_target is None else n_target
    lo = max(1, int(max(sum(char_w(e, fs)) / max(1, n) * 0.6, 1)))
    hi = int(math.ceil(maxw))
    if len(wrap_lines(e, fs, hi)) > n:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if len(wrap_lines(e, fs, mid)) <= n:
            hi = mid
        else:
            lo = mid + 1
    return hi


def anchored_x(e, new_w):
    al = e.get("text_align", "left")
    if al == "center":
        return e["x"] + (e["width"] - new_w) / 2
    if al == "right":
        return e["x"] + e["width"] - new_w
    return e["x"]


def set_text_geom(e, fs, width, x=None, y=None, W=None, H=None):
    e["font_size"] = int(fs)
    e["width"] = round(float(width), 2)
    if x is not None:
        e["x"] = round(float(x), 2)
    if y is not None:
        e["y"] = round(float(y), 2)
    n = len(wrap_lines(e, fs, width))
    h = text_height(e, fs, n)
    if H is not None:
        h = min(h, H - e["y"])
    e["height"] = round(max(1.0, h), 2)


def shift(e, dx=0.0, dy=0.0):
    e["x"] = round(e["x"] + dx, 2)
    e["y"] = round(e["y"] + dy, 2)


def rag_penalty(e, lines):
    words = e.get("content", "").split()
    n = len(lines)
    if n <= 1:
        return 0.0
    pen = 0.0
    wmax = max(lw for _, lw in lines)
    if lines[-1][1] < 0.35 * wmax and len(words) >= 3:
        pen += 1.0                                            # widow
    singles = [t for t, _ in lines if len(t.split()) == 1]
    if singles and (len(words) >= 4 or len(singles) == n):
        pen += 1.0 * len(singles)                             # one-word lines
    for t, _ in lines[:-1]:
        last = t.strip().split()[-1].lower().strip(",.;:") if t.strip() else ""
        if last in FUNCTION_WORDS:
            pen += 0.6                                        # line ends on a function word
    return pen

# ============================================================================ passes


def p1_normalise(ctx, doc):
    for e in doc["elements"]:
        if e["type"] != "text":
            continue
        fs = e.get("font_size", 12)
        e["font_size"] = max(1, int(round(fs))) if not isinstance(fs, int) else max(1, fs)
        if visible(e):
            n = len(wrap_lines(e, e["font_size"], e["width"]))
            h = text_height(e, e["font_size"], n)
            if e["y"] + h <= ctx.H + 0.5 and abs(h - e["height"]) > 0.5:
                e["height"] = round(max(1.0, h), 2)
    return doc


def _label_fs_cap(ctx, doc, label=None):
    """Largest label size whose CAP HEIGHT stays <= headline cap / 1.2 (hierarchy by cap height)."""
    heads = els_by_role(ctx, doc, "headline")
    if not heads:
        return 10 ** 6
    h = heads[0]
    hc = int(h["font_size"]) * vmetrics(h)[1]
    lc = vmetrics(label)[1] if label is not None else 0.7
    return int(math.floor(hc / 1.2 / lc + 1e-9))


def p2_pills(ctx, doc):
    W, H = ctx.W, ctx.H
    ids = by_id(doc)
    floor_px = math.ceil(12 / judge_scale(W, H))
    for host, riders in ctx.containers.items():
        s = ids.get(host)
        if s is None or s["type"] != "shape" or not visible(s) or ctx.roles.get(host) == "panel":
            continue
        labels = [ids[r] for r in riders if r in ids and ids[r]["type"] == "text" and visible(ids[r])]
        if len(labels) != 1:
            continue
        t = labels[0]
        cap = _label_fs_cap(ctx, doc, t)
        fs = int(t["font_size"])
        role = ctx.roles.get(t["id"])
        want = fs
        if role == "cta_label" and fs < floor_px:
            want = min(floor_px, cap) if cap >= floor_px else floor_px
        if role in ("cta_label", "badge_label") and fs > cap and cap >= floor_px:
            want = cap
        cx, cy = s["x"] + s["width"] / 2, s["y"] + s["height"] / 2
        lw = sum(char_w(t, want))
        if want != fs:
            src_s, src_t = ctx.byid_src.get(host), ctx.byid_src.get(t["id"])
            h_ratio = (src_s["height"] / max(1, src_t["font_size"])) if src_s and src_t else 2.6
            h_ratio = min(max(h_ratio, 2.2), 3.4)
            pad = max(0.0, (s["width"] - sum(char_w(t, fs))) / 2) / max(1, fs)
            pad = min(max(pad, 1.0), 2.2)
            nw, nh = lw + 2 * pad * want, h_ratio * want
            rr = (s.get("corner_radius", 0) or 0) / max(1, min(s["width"], s["height"]))
            mx = min(max(6.0, 0.04 * min(W, H)), max(0.0, (W - nw) / 2))
            my = min(max(0.0, 0.1 * H), max(0.0, (H - nh) / 2))
            nx = min(max(mx, cx - nw / 2), W - mx - nw)       # slide inward rather than leave the canvas
            ny = min(max(my, cy - nh / 2), H - my - nh)
            s.update(x=round(nx, 2), y=round(ny, 2), width=round(nw, 2), height=round(nh, 2))
            if s.get("shape_type", "rectangle") == "rectangle":
                s["corner_radius"] = round(rr * min(nw, nh), 2)
            t["font_size"] = int(want)
        # label fills the pill width and sits with its caps optically centred
        if t.get("text_align", "center") == "center":
            t["x"], t["width"] = s["x"], s["width"]
        if len(wrap_lines(t, t["font_size"], t["width"])) > 1 and lw + 4 > t["width"]:
            continue  # label would wrap: leave it to the engine
        asc, capf, desc = vmetrics(t)
        cy = s["y"] + s["height"] / 2
        if abs(s.get("rotation", 0) or 0) > 0.01:
            t["rotation"] = s.get("rotation")
        t["y"] = round(cy - (asc - capf / 2) * t["font_size"], 2)
        t["height"] = round(max(1.0, min(text_height(t, t["font_size"], 1), H - t["y"])), 2)
    return doc


def _scale_image_about_ink(ctx, e, k):
    """Uniformly scale an image box by k keeping its INK centre fixed (aspect exact)."""
    r = ink(e, ctx.assets)
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    fx, fy = (cx - e["x"]) / e["width"], (cy - e["y"]) / e["height"]
    w, h = e["width"] * k, e["height"] * k
    e.update(x=round(cx - fx * w, 2), y=round(cy - fy * h, 2), width=round(w, 2), height=round(h, 2))


def p2b_logo_weight(ctx, doc):
    """The brand mark never out-weighs the message: logo ink <= 0.75 x headline ink (unless the
    source itself was logo-heavier), never below a recognisability floor of 24 judge-px ink height."""
    logos, heads = els_by_role(ctx, doc, "logo"), els_by_role(ctx, doc, "headline")
    if not logos or not heads:
        return doc
    lg, hd = logos[0], heads[0]
    a_l, a_h = area(ink(lg, ctx.assets)), text_ink_area(hd)
    s_l, s_h = ctx.byid_src.get(lg["id"]), ctx.byid_src.get(hd["id"])
    src_ratio = area(ink(s_l, ctx.assets)) / max(1.0, text_ink_area(s_h)) if s_l and s_h else 0.0
    target = max(0.75, 1.1 * src_ratio)
    if a_l <= max(0.8, 1.2 * src_ratio) * a_h:
        return doc
    k = math.sqrt(target * a_h / max(1.0, a_l))
    r = ink(lg, ctx.assets)
    floor_h = 24 / judge_scale(ctx.W, ctx.H)
    k = max(k, floor_h / max(1.0, r[3] - r[1]))
    if k < 0.999:
        _scale_image_about_ink(ctx, lg, k)
    return doc


def halo_followers(ctx, doc, img):
    """Decorations concentric with an image (a halo) travel with it."""
    if img["type"] != "image":
        return []
    r = ink(img, ctx.assets)
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    tol = 0.12 * max(r[2] - r[0], r[3] - r[1])
    out = []
    for d in doc["elements"]:
        if ctx.roles.get(d["id"]) == "decoration" and visible(d):
            dx, dy = d["x"] + d["width"] / 2, d["y"] + d["height"] / 2
            if abs(dx - cx) <= tol and abs(dy - cy) <= tol:
                out.append(d)
    return out


def p10_separate(ctx, doc):
    """Box-disjoint by default: when two flow boxes overlap only through transparent image padding,
    slide the image away (smallest move), else shrink its box about its ink (>= 0.8x)."""
    for _ in range(3):
        pairs = sorted(overlap_pairs(ctx, doc) - overlap_pairs(ctx, ctx.src_like))
        if not pairs:
            break
        ids = by_id(doc)
        moved = False
        for a, b in pairs:
            A, B = ids[a], ids[b]
            img = A if A["type"] == "image" else B if B["type"] == "image" else None
            if img is None:
                continue
            other = B if img is A else A
            if inter(ink(img, ctx.assets), ink(other, ctx.assets)) > 0.5:
                continue                                   # real ink collision: not ours to fix
            bi, bo = box(img), box(other)
            opts = [(bo[0] - bi[2], 0), (bo[2] - bi[0], 0), (0, bo[1] - bi[3]), (0, bo[3] - bi[1])]
            for dx, dy in sorted(opts, key=lambda d: abs(d[0]) + abs(d[1])):
                trial = dict(img)
                shift(trial, dx, dy)
                fol = halo_followers(ctx, doc, img)
                if any(d["x"] + dx < -0.5 or d["y"] + dy < -0.5 or d["x"] + d["width"] + dx > ctx.W + 0.5
                       or d["y"] + d["height"] + dy > ctx.H + 0.5 for d in fol):
                    continue                              # its halo could not follow: try another move
                if _free_box_ok(ctx, doc, img["id"], box(trial)):
                    for d in fol:
                        shift(d, dx, dy)
                    img.update(x=trial["x"], y=trial["y"])
                    moved = True
                    break
            else:
                for k in (0.95, 0.9, 0.85, 0.8):
                    trial = dict(img)
                    _scale_image_about_ink(ctx, trial, k)
                    if _free_box_ok(ctx, doc, img["id"], box(trial)):
                        img.update(x=trial["x"], y=trial["y"], width=trial["width"], height=trial["height"])
                        moved = True
                        break
        if not moved:
            break
    return doc


def p3_balance(ctx, doc):
    for e in els_by_role(ctx, doc, "headline", "subhead", "body", "legal", "cta_label"):
        if ctx.host_of.get(e["id"]) and ctx.roles.get(ctx.host_of[e["id"]]) != "panel":
            continue  # pill labels are owned by p2
        fs = int(e["font_size"])
        lines = wrap_lines(e, fs, e["width"])
        if len(lines) < 2:
            continue
        w = balanced_int_width(e, fs, e["width"])
        if w is None or w >= e["width"] - 0.5:
            continue
        set_text_geom(e, fs, w, x=anchored_x(e, w), H=ctx.H)
    return doc


def _free_box_ok(ctx, doc, eid, bx, margin=0.0):
    """In-canvas (optionally inside a side margin, never tighter than the element already was) and
    no overlap with an unrelated flow box."""
    if margin > 0:
        cur = next((box(o) for o in doc["elements"] if o["id"] == eid), None)
        lm = min(margin, cur[0]) if cur else margin
        rm = min(margin, ctx.W - cur[2]) if cur else margin
        if bx[0] < lm - 0.5 or bx[2] > ctx.W - rm + 0.5:
            return False
    if bx[0] < -0.5 or bx[1] < -0.5 or bx[2] > ctx.W + 0.5 or bx[3] > ctx.H + 0.5:
        return False
    for o in doc["elements"]:
        if o["id"] == eid or not ctx.is_flow(o) or ctx.related(eid, o["id"]):
            continue
        if inter(bx, box(o)) > 0.5:
            return False
    return True


def p4_rag(ctx, doc):
    W, H = ctx.W, ctx.H
    for e in els_by_role(ctx, doc, "headline", "subhead"):
        fs0 = int(e["font_size"])
        lines0 = wrap_lines(e, fs0, e["width"])
        pen0 = rag_penalty(e, lines0)
        if pen0 <= 0 or len(e.get("content", "").split()) < 3:
            continue
        floor_px = math.ceil((14 if ctx.roles.get(e["id"]) == "headline" else 11) / judge_scale(W, H))
        n0 = len(lines0)
        asc, cap, desc = vmetrics(e)
        al = e.get("text_align", "left")
        cx = e["x"] + e["width"] / 2
        top_opt = e["y"] + (asc - cap) * fs0             # keep the cap-top where it was
        best = None
        for fs in range(fs0, max(floor_px, int(fs0 * 0.86)) - 1, -1):
            for n in range(max(1, n0 - 1), n0 + 2):
                full = sum(char_w(e, fs))
                wmax = min(W, full + 2)
                w = balanced_int_width(e, fs, wmax, n)
                if w is None:
                    continue
                lines = wrap_lines(e, fs, w)
                if len(lines) != n:
                    continue
                pen = rag_penalty(e, lines) + 0.25 * abs(n - n0) + 0.12 * (fs0 - fs)
                if pen >= pen0 - 0.2:
                    continue
                x = {"center": cx - w / 2, "right": e["x"] + e["width"] - w}.get(al, e["x"])
                y = top_opt - (asc - cap) * fs
                h = text_height(e, fs, n)
                bx = (x, y, x + w, y + h)
                if not _free_box_ok(ctx, doc, e["id"], bx, margin=max(6.0, 0.04 * min(W, H))):
                    continue
                if best is None or pen < best[0]:
                    best = (pen, fs, w, x, y)
        if best:
            _, fs, w, x, y = best
            set_text_geom(e, fs, w, x=x, y=y, H=H)
    return doc


def p4b_strip_lines(ctx, doc):
    """Strips: headline <= 3 lines (2 preferred) by widening into free space, then -1/-2 font steps."""
    W, H = ctx.W, ctx.H
    if H > 120:
        return doc
    for e in els_by_role(ctx, doc, "headline"):
        fs0 = int(e["font_size"])
        n0 = len(wrap_lines(e, fs0, e["width"]))
        if n0 <= 2:
            continue
        floor_px = math.ceil(14 / judge_scale(W, H))
        others = [int(o["font_size"]) * vmetrics(o)[1] for o in doc["elements"]
                  if o["type"] == "text" and o is not e and visible(o) and ctx.roles.get(o["id"]) != "legal"]
        asc, cap, desc = vmetrics(e)
        if others:
            floor_px = max(floor_px, math.ceil(1.2 * max(others) / cap - 1e-9))
        cx = e["x"] + e["width"] / 2
        mid = e["y"] + (asc - cap) * fs0 + (text_ink(e)[3] - text_ink(e)[1]) / 2
        best = None
        for fs in range(fs0, max(floor_px, fs0 - 2) - 1, -1):
            for n in (2, 3):
                if n >= n0 and fs == fs0:
                    continue
                w = balanced_int_width(e, fs, sum(char_w(e, fs)) + 2, n)
                if w is None:
                    continue
                h_ink = (n - 1) * e.get("line_height", 1.2) * fs + cap * fs + 0.21 * fs
                if h_ink > H - 2 * 0.12 * H + 0.5:
                    continue
                y = mid - h_ink / 2 - (asc - cap) * fs
                x = cx - w / 2
                bx = (x, y, x + w, y + text_height(e, fs, n))
                if not _free_box_ok(ctx, doc, e["id"], bx, margin=max(6.0, 0.04 * min(W, H))):
                    continue
                key = (n, -fs)
                if best is None or key < best[0]:
                    best = (key, fs, w, x, y)
        if best:
            _, fs, w, x, y = best
            set_text_geom(e, fs, w, x=x, y=y, H=H)
    return doc


def _units_in_strip(ctx, doc):
    """Columns of a strip = x-clusters of flow ink (groups/hosts travel with their riders)."""
    items = []
    for e in doc["elements"]:
        if not ctx.is_flow(e) or ctx.roles.get(e["id"]) in ("furniture",) or e["id"] in ctx.layered:
            continue
        items.append((e, ink(e, ctx.assets)))
    items.sort(key=lambda p: p[1][0])
    cols = []
    for e, r in items:
        if cols and r[0] < cols[-1]["ink"][2] - 1:
            c = cols[-1]
            c["els"].append(e)
            c["ink"] = (min(c["ink"][0], r[0]), min(c["ink"][1], r[1]), max(c["ink"][2], r[2]), max(c["ink"][3], r[3]))
        else:
            cols.append({"els": [e], "ink": r})
    return cols


def p5_strip_unit(ctx, doc):
    W, H = ctx.W, ctx.H
    if H > 120 or W / H < 3:
        return doc
    texts = [e for e in els_by_role(ctx, doc, "headline", "subhead", "body") if not ctx.host_of.get(e["id"])]
    texts.sort(key=lambda e: e["y"])
    if not texts:
        return doc
    # stack only the texts that share a column with the headline
    head = next((e for e in texts if ctx.roles.get(e["id"]) == "headline"), texts[0])
    hx = text_ink(head)
    col = [e for e in texts if not (text_ink(e)[2] < hx[0] or text_ink(e)[0] > hx[2])]
    inks = [text_ink(e) for e in col]
    fs_head = int(head["font_size"])
    gap = round(0.4 * fs_head, 2)
    total = sum(r[3] - r[1] for r in inks) + gap * (len(col) - 1)
    pad = 0.12 * H
    if total > H - 2 * pad + 0.5:
        pad = max(0.0, (H - total) / 2)
    y = (H - total) / 2
    for e, r in zip(col, inks):
        dy = y - r[1]
        shift(e, 0, dy)
        y += (r[3] - r[1]) + gap
    # shared midline: logo / hero / pill columns are optically centred on H/2
    for e in doc["elements"]:
        if not ctx.is_flow(e) or e in col or ctx.roles.get(e["id"]) in ("furniture", "badge_shape", "badge_label")                 or e["id"] in ctx.layered:
            continue
        if ctx.host_of.get(e["id"]):
            continue
        r = ink(e, ctx.assets)
        dy = H / 2 - (r[1] + r[3]) / 2
        if abs(dy) < 0.5:
            continue
        riders = ctx.containers.get(e["id"], [])
        movers = [e] + [o for o in doc["elements"] if o["id"] in riders]
        if all(0 <= o["y"] + dy and o["y"] + o["height"] + dy <= H for o in movers):
            for o in movers:
                shift(o, 0, dy)
    return doc


def p6_margins(ctx, doc):
    W, H = ctx.W, ctx.H
    if W / H < 2.0 or els_by_role(ctx, doc, "panel"):
        return doc
    cols = _units_in_strip(ctx, doc)
    if len(cols) < 2:
        return doc
    # include riders/hosts of each column so containers travel together
    ids = by_id(doc)
    for c in cols:
        extra = []
        for e in c["els"]:
            for r in ctx.containers.get(e["id"], []):
                if r in ids:
                    extra.append(ids[r])
            h = ctx.host_of.get(e["id"])
            if h in ids and ctx.roles.get(h) != "panel":
                extra.append(ids[h])
        seen = {e["id"] for e in c["els"]}
        c["els"] += [x for x in extra if x["id"] not in seen and not seen.add(x["id"])]
    widths = [c["ink"][2] - c["ink"][0] for c in cols]
    need = []
    for a, b in zip(cols, cols[1:]):
        ra = max(e["x"] + e["width"] for e in a["els"]) - a["ink"][2]     # box overhang right of ink
        lb = b["ink"][0] - min(e["x"] for e in b["els"])                  # box overhang left of ink
        need.append(max(0.0, ra) + max(0.0, lb))
    # how far left/right each column's BOXES let its ink go
    lpad = min(e["x"] for e in cols[0]["els"]) - cols[0]["ink"][0]
    rpad = cols[-1]["ink"][2] - max(e["x"] + e["width"] for e in cols[-1]["els"])
    min_m = max(6.0, 0.13 * min(W, H) if H <= 120 else 0.06 * min(W, H))
    M = max(min_m, -lpad, -rpad)
    free = W - sum(widths) - 2 * M
    gmin = max(8.0, 0.6 * min_m)
    if free < gmin * (len(cols) - 1):
        return doc
    gut = [max(gmin, n + 2.0) for n in need]                 # box-disjoint by construction
    spare = free - sum(gut)
    if spare < 0:
        return doc
    extra = spare / len(gut)
    if H > 120:
        extra = min(extra, max(0.0, 0.25 * W - max(gut)))     # wide-but-tall canvases: no exploding gutters
        M = (W - sum(widths) - sum(gut) - extra * len(gut)) / 2
    x = M
    gaps_ = [g + extra for g in gut] + [0.0]
    for c, w, g in zip(cols, widths, gaps_):
        dx = x - c["ink"][0]
        fol = {id(d): d for e in c["els"] for d in halo_followers(ctx, doc, e)}
        for d in fol.values():                       # a halo must stay concentric: limit the move
            dx = min(max(dx, -d["x"]), ctx.W - d["x"] - d["width"])
        if abs(dx) >= 0.5:
            for e in list(c["els"]) + list(fol.values()):
                shift(e, dx, 0)
        x = c["ink"][0] + (dx if abs(dx) >= 0.5 else 0.0) + w + g
    # decorations attached to a moved column (halos) follow it
    return doc


def _rows(ctx, doc):
    items = []
    for e in doc["elements"]:
        if not ctx.is_flow(e) or ctx.roles.get(e["id"]) == "furniture" or ctx.host_of.get(e["id"])                 or e["id"] in ctx.layered:
            continue
        r = ink(e, ctx.assets)
        # corner-pinned small chips (badges) are furniture-like: not part of the stack
        if ctx.roles.get(e["id"]) == "badge_shape" and (r[1] < 0.12 * ctx.H or r[3] > 0.88 * ctx.H):
            continue
        items.append((e, r))
    items.sort(key=lambda p: p[1][1])
    rows = []
    for e, r in items:
        if rows and r[1] < rows[-1]["ink"][3] - 1:
            q = rows[-1]
            q["els"].append(e)
            q["ink"] = (min(q["ink"][0], r[0]), min(q["ink"][1], r[1]), max(q["ink"][2], r[2]), max(q["ink"][3], r[3]))
        else:
            rows.append({"els": [e], "ink": r})
    return rows


def p7_rhythm(ctx, doc):
    W, H = ctx.W, ctx.H
    if H / W < 1.2:
        return doc
    rows = _rows(ctx, doc)
    if len(rows) < 4:
        return doc
    gaps = [b["ink"][1] - a["ink"][3] for a, b in zip(rows, rows[1:])]
    if min(gaps) <= 0:
        return doc
    if max(gaps) <= 3 * min(gaps):
        return doc
    unit = sorted(gaps)[len(gaps) // 2]
    snapped = [min(3, max(1, round(g / unit))) * unit for g in gaps]
    total = sum(gaps)
    snapped = [s * total / sum(snapped) for s in snapped]
    ids = by_id(doc)
    y = rows[0]["ink"][3]
    for row, s in zip(rows[1:], snapped):
        y += s
        dy = y - row["ink"][1]
        movers = list(row["els"])
        for e in row["els"]:
            movers += [ids[r] for r in ctx.containers.get(e["id"], []) if r in ids]
        # halos: decorations centred on a moved image travel with it
        for d in els_by_role(ctx, doc, "decoration"):
            for e in row["els"]:
                if e["type"] == "image" and _center_in(d, e) and _center_in(e, d):
                    movers.append(d)
        for e in {id(m): m for m in movers}.values():
            shift(e, 0, dy)
        y = row["ink"][3] + dy
    return doc


def p8_decorations(ctx, doc):
    W, H = ctx.W, ctx.H
    if abs(W - ctx.sW) <= 0.03 * ctx.sW and abs(H - ctx.sH) <= 0.03 * ctx.sH:
        return doc                      # same canvas as the source: the designer's decorations stay put
    ids = by_id(doc)
    protect = [e for e in doc["elements"] if visible(e) and ctx.roles.get(e["id"]) in
               ("logo", "cta_shape", "headline", "subhead", "body", "cta_label")]
    src_ov = {}
    for d in ctx.src["elements"]:
        if ctx.roles.get(d["id"]) != "decoration":
            continue
        for p in protect:
            sp = ctx.byid_src.get(p["id"])
            if sp is not None:
                rp = ink(sp, ctx.assets)
                src_ov[(d["id"], p["id"])] = inter(box(d), rp) / max(1.0, area(rp))
    heroes = [e for e in doc["elements"] if visible(e) and ctx.roles.get(e["id"]) == "hero"]
    used_halo = {d["id"] for d in els_by_role(ctx, doc, "decoration") for h in heroes
                 if _center_in(d, h) and _center_in(h, d)}

    def bad(d, bx, slack=0.05):
        for p in protect:
            rp = ink(p, ctx.assets)
            allowed = src_ov.get((d["id"], p["id"]), 0.0) + slack
            if inter(bx, rp) / max(1.0, area(rp)) > allowed:
                return True
        return False
    for d in els_by_role(ctx, doc, "decoration"):
        if d["type"] != "shape" or alpha_of(d.get("fill_color")) * float(d.get("opacity", 1)) > 0.6:
            continue
        is_halo = d["id"] in used_halo
        if not bad(d, box(d), 0.25 if is_halo else 0.05):
            continue
        if is_halo:
            used_halo.discard(d["id"])
        ar = d["height"] / max(1.0, d["width"])
        cands = []
        for h in heroes:
            if used_halo:
                break
            hr = ink(h, ctx.assets)
            cx, cy = (hr[0] + hr[2]) / 2, (hr[1] + hr[3]) / 2
            room = 2 * min(cx, W - cx, cy / max(ar, 1e-6), (H - cy) / max(ar, 1e-6))
            dd = min(1.12 * (hr[3] - hr[1]), room)          # concentric or nothing: never clamp a halo
            if dd >= 0.9 * (hr[3] - hr[1]):
                cands.append((cx - dd / 2, cy - dd * ar / 2, dd, dd * ar, "halo"))
        size = d["width"]
        for s in (size, 0.75 * size, 0.5 * size):
            for (cx, cy) in ((0, 0), (W, 0), (0, H), (W, H)):
                x = 0 if cx == 0 else W - s
                y = 0 if cy == 0 else H - s * ar
                cands.append((x, y, s, s * ar, "corner"))
        for x, y, w, h, kind in cands:
            bx = (max(0.0, x), max(0.0, y), max(0.0, x) + w, max(0.0, y) + h)
            if bx[2] > W + 0.5 or bx[3] > H + 0.5 or bad(d, bx):
                continue
            d.update(x=round(bx[0], 2), y=round(bx[1], 2), width=round(w, 2), height=round(h, 2))
            if kind == "halo":
                used_halo.add(d["id"])
            break
    return doc


def p9_furniture(ctx, doc):
    """Visible rotated stickers keep their angle; if clipped or colliding they try: source corner ->
    mirrored corner -> hero shoulder. (Un-hiding engine-hidden furniture is OFF: visibility is the
    engine's call.)"""
    W, H = ctx.W, ctx.H
    ids = by_id(doc)
    m = max(6.0, 0.04 * min(W, H))
    flow = [e for e in doc["elements"] if ctx.is_flow(e) and ctx.roles.get(e["id"]) != "furniture"]
    for host, riders in ctx.containers.items():
        s = ids.get(host)
        if s is None or ctx.roles.get(host) != "furniture" or not visible(s):
            continue
        group = [s] + [ids[r] for r in riders if r in ids]
        r0 = rot_aabb(s)
        clipped = r0[0] < -0.5 or r0[1] < -0.5 or r0[2] > W + 0.5 or r0[3] > H + 0.5
        hit = any(inter(r0, ink(o, ctx.assets)) > 0.5 for o in flow if not ctx.related(o["id"], host))
        if not (clipped or hit):
            continue
        src = ctx.byid_src.get(host, s)
        right = (src["x"] + src["width"] / 2) > ctx.sW / 2
        top = (src["y"] + src["height"] / 2) < ctx.sH / 2
        hw, hh = (r0[2] - r0[0]) / 2, (r0[3] - r0[1]) / 2
        cands = []
        for rr in (right, not right):
            cx = W - m - hw if rr else m + hw
            cy = m + hh if top else H - m - hh
            cands.append((cx, cy))
        for hro in [e for e in flow if ctx.roles.get(e["id"]) == "hero"]:
            hr = ink(hro, ctx.assets)
            cands.append((hr[2] - 0.15 * (hr[2] - hr[0]), hr[1] + hh * 0.6))
        for cx, cy in cands:
            dx, dy = cx - (r0[0] + r0[2]) / 2, cy - (r0[1] + r0[3]) / 2
            nr = (r0[0] + dx, r0[1] + dy, r0[2] + dx, r0[3] + dy)
            if nr[0] < -0.5 or nr[1] < -0.5 or nr[2] > W + 0.5 or nr[3] > H + 0.5:
                continue
            ok = True
            for o in flow:
                if ctx.related(o["id"], host):
                    continue
                ov = inter(nr, ink(o, ctx.assets))
                lim = 0.2 * area(ink(o, ctx.assets)) if ctx.roles.get(o["id"]) == "hero" else 0.5
                if ov > lim:
                    ok = False
                    break
            if ok:
                for e in group:
                    shift(e, dx, dy)
                break
    return doc

# ============================================================================ driver

MAX_ROUNDS = 4
PASSES = [("logo_weight", p2b_logo_weight), ("pills", p2_pills), ("balance", p3_balance), ("rag", p4_rag),
          ("strip_lines", p4b_strip_lines),
          ("strip_unit", p5_strip_unit), ("margins", p6_margins), ("rhythm", p7_rhythm),
          ("decorations", p8_decorations), ("furniture", p9_furniture), ("separate", p10_separate)]


def _score(source, doc, info_eff):
    try:
        from . import rules as R
    except ImportError:  # pragma: no cover - script mode
        import rules as R  # type: ignore
    vs = R.check(source, doc, info_eff)
    return (sum(1 for v in vs if v.severity == "hard"), sum(1 for v in vs if v.severity == "soft")), vs


def finish(source: dict[str, Any], output: dict[str, Any], info: dict[str, Any] | None = None,
           report: list | None = None) -> dict[str, Any]:
    """Typesetting & optics pass. Returns a NEW dict; on any failure returns `output` unchanged."""
    try:
        ctx = Ctx(source, output, info)
        info_eff = dict(info or {})
        info_eff.setdefault("roles", ctx.roles)
        info_eff.setdefault("containers", ctx.containers)
        info_eff.setdefault("assets_dir", ctx.assets)
        cur = copy.deepcopy(output)
        try:                                     # integer sizes + honest boxes are mandatory, not scored
            norm = p1_normalise(ctx, copy.deepcopy(cur))
            if not [p for p in contract_problems(ctx, output, norm) if "font_size" not in p]:
                cur = norm
        except Exception:
            pass
        cur_score, vs0 = _score(source, cur, info_eff)
        cur_hard = {(v.rule, tuple(v.ids)) for v in vs0 if v.severity == "hard"}
        start_score = cur_score
        for rnd in range(MAX_ROUNDS):            # iterate to a fixed point => idempotent by construction
            changed = False
            for name, fn in PASSES:
                try:
                    cand = fn(ctx, copy.deepcopy(cur))
                except Exception as ex:  # a pass may fail; the finisher must not
                    if report is not None:
                        report.append(f"r{rnd} {name}: skipped ({type(ex).__name__}: {ex})")
                    continue
                if cand == cur:
                    continue
                probs = contract_problems(ctx, output, cand)
                if probs:
                    if report is not None:
                        report.append(f"r{rnd} {name}: rejected (contract: {probs[:3]})")
                    continue
                sc, vs = _score(source, cand, info_eff)
                hard = {(v.rule, tuple(v.ids)) for v in vs if v.severity == "hard"}
                if not (hard - cur_hard) and (sc[0] < cur_score[0] or sc < cur_score):
                    cur, cur_score, cur_hard, changed = cand, sc, hard, True
                    if report is not None:
                        report.append(f"r{rnd} {name}: applied {sc}")
                elif report is not None:
                    report.append(f"r{rnd} {name}: rejected (rules {cur_score} -> {sc})")
            if not changed:
                break
        if report is not None:
            report.append(f"score {start_score} -> {cur_score}")
        return output if cur == output else cur
    except Exception as ex:  # never break the pipeline
        if report is not None:
            report.append(f"finish aborted: {type(ex).__name__}: {ex}")
        return output
