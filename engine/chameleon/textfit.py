"""textfit.py: exact measurement with the renderer's own code (owner: OPTIMIZER).

Everything the engine knows about text and image extents comes from here.
* Text is wrapped by `renderer.converter.wrap.wrap_text` with skia advances at INTEGER font sizes.
  The renderer draws at int(font_size), and the engine only ever emits integers.
* W_k(el, f, k) is the minimal box width that makes the greedy wrap give <= k lines.
  Greedy line count is monotone in width, so bisection is exact to 0.25 px.
* text_h is an honest box height: max(ink height, n * f * line_height). The second term is the
  number JUDGE's validator checks.
* Image ink is the alpha bbox of the asset under contain-fit, as `renderer/converter/assets.py` draws it.
"""
from __future__ import annotations

import math
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer.converter.convert import (  # noqa: E402
    _BOLD_WEIGHTS, _get_renderer, _is_italic, _normalize_weight, _weight_style_to_font_style)
from renderer.converter.wrap import char_widths, wrap_text  # noqa: E402

FONTS_DIR = str(ROOT / "brand_kit" / "fonts")
_FM = None


def fm():
    global _FM
    if _FM is None:
        _FM = _get_renderer(FONTS_DIR).font_manager
    return _FM


# ----------------------------------------------------------------------------- fonts
def font_args(el):
    weight = _normalize_weight(el.get("font_weight"))
    style = _weight_style_to_font_style(weight in _BOLD_WEIGHTS, _is_italic(el.get("font_style") or el.get("italic")))
    return el.get("font_family", "Montserrat"), weight, style


def is_bold(el):
    return _normalize_weight(el.get("font_weight")) in _BOLD_WEIGHTS


def eff_size(el, f=None):
    """Perceived size: bold reads ~15% larger."""
    f = el.get("font_size", 12) if f is None else f
    return float(f) * (1.15 if is_bold(el) else 1.0)


_CW: dict = {}
CACHE_MAX = 200_000


def reset_caches():
    """Called at the start of every resize(): no state carried between calls beyond pure value caches,
    and those are bounded."""
    for c in (_CW, _WK):
        if len(c) > CACHE_MAX:
            c.clear()


def _ls(el, f):
    """letter_spacing scales with the font size (the source value belongs to the source size)."""
    ls = float(el.get("letter_spacing", 0) or 0)
    if not ls:
        return 0.0
    try:
        return ls * float(f) / max(1.0, float(el.get("font_size", f)))
    except (TypeError, ValueError):
        return ls


def cwidths(el, f):
    """Per-char advances used for WRAPPING. If `capitalize` is set the renderer draws upper-case, so
    the larger of lower- and upper-case advances is used (conservative), and letter_spacing is added."""
    f = max(1, int(f))
    content = str(el.get("content", ""))
    ls = _ls(el, f)
    key = (font_args(el), f, content, bool(el.get("capitalize")), ls)
    if key not in _CW:
        if not content:
            _CW[key] = []
        else:
            fam, w, s = font_args(el)
            ws = char_widths(fm(), fam, w, s, f, content)
            if el.get("capitalize"):
                up = char_widths(fm(), fam, w, s, f, content.upper())
                ws = [max(a, b) for a, b in zip(ws, up)]
            if ls:
                ws = [x + ls for x in ws]
            _CW[key] = list(ws)
    return _CW[key]


_MET: dict = {}


def metrics(el, f):
    """(ascent, descent, cap_height, x_height) in px at integer size f."""
    f = max(1, int(f))
    key = (font_args(el), f)
    if key not in _MET:
        import skia
        fam, w, s = font_args(el)
        m = skia.Font(skia.Typeface.MakeFromData(fm().lookup(fam, w, s)), f).getMetrics()
        cap = m.fCapHeight if m.fCapHeight > 0 else 0.7 * f
        xh = m.fXHeight if m.fXHeight > 0 else 0.5 * f
        _MET[key] = (-m.fAscent, m.fDescent, cap, xh)
    return _MET[key]


def line_height(el):
    try:
        return float(el.get("line_height", 1.2) or 1.2)
    except (TypeError, ValueError):
        return 1.2


# ----------------------------------------------------------------------------- wrapping
def wrapped(el, f, width):
    return wrap_text(str(el.get("content", "")), cwidths(el, f), float(width))


def n_lines(el, f, width):
    if not str(el.get("content", "")).strip():
        return 0
    return wrapped(el, f, width).count("\n") + 1


def line_widths(el, f, width):
    ws = cwidths(el, f)
    out, cur = [], 0.0
    for c, w in zip(wrapped(el, f, width), ws):
        if c == "\n":
            out.append(cur)
            cur = 0.0
        else:
            cur += w
    return out + [cur]


def line_texts(el, f, width):
    return wrapped(el, f, width).split("\n")


def max_word(el, f):
    best = cur = 0.0
    for c, w in zip(str(el.get("content", "")), cwidths(el, f)):
        cur = 0.0 if c in " \n" else cur + w
        best = max(best, cur)
    return best


def one_line(el, f):
    return sum(cwidths(el, f))


_WK: dict = {}


def W_k(el, f, k):
    """Minimal box width so that the greedy wrap at int font f yields <= k lines."""
    f = max(1, int(f))
    # keyed by VALUE only (never id(): ids are recycled after GC -> wrong widths; JUDGE r3 finding)
    key = (str(el.get("content", "")), font_args(el), f, k, _ls(el, f),
           bool(el.get("capitalize")))
    if key in _WK:
        return _WK[key]
    total = one_line(el, f) + 0.5
    lo = max_word(el, f) + 0.5
    if k <= 1 or "\n" in str(el.get("content", "")):
        res = total if k <= 1 else max(lo, _hardbreak_width(el, f, k))
    elif n_lines(el, f, lo) <= k:
        res = lo
    else:
        hi = total
        while hi - lo > 0.25:
            mid = (lo + hi) / 2
            if n_lines(el, f, mid) <= k:
                hi = mid
            else:
                lo = mid
        res = hi
    _WK[key] = res
    return res


def _hardbreak_width(el, f, k):
    """Content with explicit newlines: width of its widest hard line (if that already meets k)."""
    widths = []
    ws = cwidths(el, f)
    cur = 0.0
    for c, w in zip(str(el.get("content", "")), ws):
        if c == "\n":
            widths.append(cur)
            cur = 0.0
        else:
            cur += w
    widths.append(cur)
    return max(widths) + 0.5


def text_h(el, f, k):
    """Honest box height for k lines at int font f."""
    f = max(1, int(f))
    if k <= 0:
        return max(1.0, f * line_height(el))
    asc, desc, _, _ = metrics(el, f)
    return max((k - 1) * f * line_height(el) + asc + desc, k * f * line_height(el))


def lines_at(el, f, c, kmax):
    for k in range(1, kmax + 1):
        if W_k(el, f, k) <= c + 1e-6:
            return k
    return None


def balanced_width(el, f, c):
    """Narrowest width <= c that keeps the line count obtained at width c (text-wrap: balance)."""
    k = n_lines(el, f, c)
    if k <= 1:
        return min(c, one_line(el, f) + 1.0)
    return min(c, W_k(el, f, k) + 1.0)


def drawn_widths(el, f, box_w):
    """Widths the renderer will DRAW: the converter wraps at the float size with plain advances, and
    the renderer adds letter_spacing and upper-cases when capitalize is set."""
    fam, w, s = font_args(el)
    content = str(el.get("content", ""))
    if not content:
        return [0.0]
    wrap_ws = char_widths(fm(), fam, w, s, float(f), content)
    lines = wrap_text(content, wrap_ws, float(box_w))
    draw = char_widths(fm(), fam, w, s, int(f), content.upper() if el.get("capitalize") else content)
    ls = _ls(el, f)
    out, cur, n = [], 0.0, 0
    for c, dw in zip(lines, draw):
        if c == "\n":
            out.append(cur + ls * max(0, n - 1))
            cur, n = 0.0, 0
        else:
            cur += dw
            n += 1
    out.append(cur + ls * max(0, n - 1))
    return out


# ----------------------------------------------------------------------------- images
_ASSET: dict = {}


def asset_info(assets_dir, asset_id):
    """((w, h), alpha bbox) or None when the asset file is missing."""
    key = (str(assets_dir), str(asset_id))
    if key in _ASSET:
        return _ASSET[key]
    res = None
    try:
        p = Path(assets_dir) / str(asset_id)
        if asset_id and p.is_file():
            from PIL import Image
            im = Image.open(p)
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                bb = im.convert("RGBA").getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
            else:
                bb = (0, 0, im.width, im.height)
            res = ((im.width, im.height), bb or (0, 0, im.width, im.height))
    except Exception:  # noqa: BLE001
        res = None
    _ASSET[key] = res
    return res


def image_pad(el, w, h, assets_dir):
    """Transparent padding (l, t, r, b) of a contain-fit image drawn in a w x h box."""
    info = asset_info(assets_dir, el.get("asset_id"))
    if info is None or el.get("fit", "contain") != "contain" or w <= 0 or h <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    (aw, ah), (x0, y0, x1, y1) = info
    s = min(w / aw, h / ah)
    ox, oy = (w - aw * s) / 2, (h - ah * s) / 2
    return (ox + x0 * s, oy + y0 * s, w - (ox + x1 * s), h - (oy + y1 * s))


def ink_rect_image(el, assets_dir):
    l, t, r, b = image_pad(el, el["width"], el["height"], assets_dir)
    return (el["x"] + l, el["y"] + t, el["x"] + el["width"] - r, el["y"] + el["height"] - b)


def ink_rect_text(el):
    f = max(1, int(el.get("font_size", 12)))
    if not str(el.get("content", "")).strip():
        return (el["x"], el["y"], el["x"], el["y"])
    lw = line_widths(el, f, el["width"])
    k = len(lw)
    asc, desc, cap, _ = metrics(el, f)
    mw = max(lw)
    al = el.get("text_align", "left")
    x0 = el["x"] + ((el["width"] - mw) / 2 if al == "center" else (el["width"] - mw) if al == "right" else 0.0)
    top = el["y"] + (asc - cap)                      # cap-top of the first line
    bot = el["y"] + (k - 1) * f * line_height(el) + asc + desc
    return (x0, top, x0 + mw, bot)


def rot_aabb(x, y, w, h, deg):
    if not deg:
        return (x, y, x + w, y + h)
    t = math.radians(deg)
    c, s = abs(math.cos(t)), abs(math.sin(t))
    W, H = w * c + h * s, w * s + h * c
    cx, cy = x + w / 2, y + h / 2
    return (cx - W / 2, cy - H / 2, cx + W / 2, cy + H / 2)


def ink_rect(el, assets_dir):
    if el["type"] == "text":
        r = ink_rect_text(el)
    elif el["type"] == "image":
        r = ink_rect_image(el, assets_dir)
    else:
        r = (el["x"], el["y"], el["x"] + el["width"], el["y"] + el["height"])
    rot = float(el.get("rotation", 0) or 0)
    if rot:
        r = rot_aabb(r[0], r[1], r[2] - r[0], r[3] - r[1], rot)
    return r


def judge_scale(W, H):
    """Evaluator viewing scale: judge_px = px * min(1, 1024 / long side) (JUDGE / PERCEPTION)."""
    return min(1.0, 1024.0 / max(W, H))
