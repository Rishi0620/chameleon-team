"""Structural validator (JSON side of the scorer) + renderer-exact text measurement.

hard  -> things a structural checker will almost certainly fail (or that crash the renderer)
warn  -> renderer-gap / honesty issues a checker *might* flag and the VLM often sees
Every check is role-free (no ids, no semantics) so it runs on any design.
"""
from __future__ import annotations

import json
import math
from typing import Any

from common import ASSETS, renderer  # noqa: F401  (sets sys.path)
from renderer.converter.assets import asset_path
from renderer.converter.colorutil import parse_rgba
from renderer.converter.convert import _BOLD_WEIGHTS, _is_italic, _normalize_weight, _weight_style_to_font_style
from renderer.converter.wrap import char_widths, wrap_text

REQ_COMMON = ["id", "type", "x", "y", "width", "height"]
REQ_TYPE = {"text": ["content", "font_family", "font_size", "color"], "image": ["asset_id"],
            "shape": ["shape_type", "fill_color"]}
FROZEN = ("type", "content", "font_family", "asset_id", "group_id")
ASPECT_TOL = 0.05


# ---------------------------------------------------------------- measurement
def text_layout(el: dict[str, Any]) -> dict[str, Any]:
    """Emulate converter wrap (float size) + renderer draw (int size, + letter spacing)."""
    fm = renderer().font_manager
    content = str(el.get("content", ""))
    if el.get("capitalize"):
        content_draw = content.upper()
    else:
        content_draw = content
    fs = float(el.get("font_size", 24))
    weight = _normalize_weight(el.get("font_weight"))
    style = _weight_style_to_font_style(weight in _BOLD_WEIGHTS, _is_italic(el.get("font_style") or el.get("italic")))
    fam = el.get("font_family", "")
    box_w = float(el.get("width", 1))
    wrapped = wrap_text(content, char_widths(fm, fam, weight, style, fs, content), box_w)
    draw_w = char_widths(fm, fam, weight, style, int(fs), content_draw) if int(fs) > 0 else []
    ls = float(el.get("letter_spacing", 0) or 0)
    widths, start = [], 0
    for i, c in enumerate(wrapped + "\n"):
        if c == "\n":
            seg = [j for j in range(start, i)]
            widths.append(sum(draw_w[j] for j in seg if j < len(draw_w)) + ls * max(0, len(seg) - 1))
            start = i + 1
    n = len(widths) if content.strip() else 0
    lh = float(el.get("line_height", 1.2) or 1.2)
    align = el.get("text_align", "left")
    offs = [0.0 if align == "left" else (box_w - w) / 2 if align == "center" else box_w - w for w in widths]
    x0 = el["x"] + min(offs, default=0.0)
    x1 = el["x"] + max((o + w for o, w in zip(offs, widths)), default=0.0)
    return {"n_lines": n, "max_line_w": max(widths, default=0.0),
            "ink": (x0, float(el["y"]), x1, float(el["y"]) + n * fs * lh), "block_h": n * fs * lh}


def rotated_aabb(el: dict[str, Any]) -> tuple[float, float, float, float]:
    x, y, w, h = float(el["x"]), float(el["y"]), float(el["width"]), float(el["height"])
    r = math.radians(float(el.get("rotation", 0) or 0))
    cx, cy = x + w / 2, y + h / 2
    hw = abs(w / 2 * math.cos(r)) + abs(h / 2 * math.sin(r))
    hh = abs(w / 2 * math.sin(r)) + abs(h / 2 * math.cos(r))
    return cx - hw, cy - hh, cx + hw, cy + hh


def declared_hidden(el: dict[str, Any]) -> bool:
    """What the JSON *claims*: opacity 0, or (text) colour alpha 0, or empty text."""
    if float(el.get("opacity", 1) if el.get("opacity") is not None else 1) <= 0.001:
        return True
    if el.get("type") == "text":
        if not str(el.get("content", "")).strip():
            return True
        return parse_rgba(el.get("color"))[3] <= 0.001
    if el.get("type") == "shape":
        return parse_rgba(el.get("fill_color"))[3] * float(el.get("opacity", 1)) <= 0.001
    return False


def renders_visible(el: dict[str, Any]) -> bool:
    """What the RENDERER will actually draw (text ignores opacity!)."""
    if el.get("type") == "text":
        return bool(str(el.get("content", "")).strip()) and parse_rgba(el.get("color"))[3] > 0.001 \
            and int(float(el.get("font_size", 0))) >= 1
    if el.get("type") == "shape":
        if el.get("shape_type") == "line" and float(el.get("height", 0)) < 1:
            return False
        return parse_rgba(el.get("fill_color"))[3] * float(el.get("opacity", 1)) > 0.001
    return float(el.get("opacity", 1)) > 0.001 and el.get("width", 0) >= 1 and el.get("height", 0) >= 1


def is_full_bleed(el: dict[str, Any], cw: float, ch: float) -> bool:
    return float(el["width"]) * float(el["height"]) >= 0.8 * cw * ch


# ---------------------------------------------------------------- structural checks
def structural(source: dict, out: Any, target: dict) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    warn: list[str] = []
    if not isinstance(out, dict) or "canvas" not in out or "elements" not in out:
        return ["output missing canvas/elements"], warn
    extra = set(out) - {"canvas", "elements"}
    if extra:
        hard.append(f"schema: extra top-level keys {sorted(extra)}")
    cv = out["canvas"]
    if set(cv) != {"width", "height"} or not all(isinstance(cv.get(k), int) for k in ("width", "height")):
        hard.append(f"schema: canvas must be exactly integer width/height, got {cv}")
    if cv.get("width") != target["width"] or cv.get("height") != target["height"]:
        hard.append("canvas != target")
    try:
        json.dumps(out, allow_nan=False)
    except (TypeError, ValueError) as exc:
        hard.append(f"not JSON-serialisable: {type(exc).__name__}: {str(exc)[:60]}")
    src = {e["id"]: e for e in source["elements"]}
    ids = [e.get("id") for e in out["elements"]]
    if sorted(map(str, ids)) != sorted(src) or len(ids) != len(set(ids)):
        hard.append("id set/count mismatch")
    W, H = float(cv.get("width", 1)), float(cv.get("height", 1))
    cw, ch = source["canvas"]["width"], source["canvas"]["height"]
    for el in out["elements"]:
        eid, s = el.get("id"), src.get(el.get("id"), {})
        missing = [f for f in REQ_COMMON + REQ_TYPE.get(el.get("type"), []) if f not in el]
        if missing:
            hard.append(f"{eid}: missing {missing}")
            continue
        try:
            geo = [float(el[k]) for k in ("x", "y", "width", "height")]
        except (TypeError, ValueError):
            hard.append(f"{eid}: non-numeric geometry")
            continue
        if not all(math.isfinite(v) for v in geo):
            hard.append(f"{eid}: non-finite geometry")
            continue
        for k in FROZEN:
            if k in s and el.get(k) != s.get(k):
                hard.append(f"{eid}: changed frozen field '{k}'")
        if "z_index" in el and not isinstance(el["z_index"], int):
            hard.append(f"{eid}: z_index not int ({el['z_index']!r})")
        op = el.get("opacity", 1)
        if op is not None and not (0 <= float(op) <= 1):
            hard.append(f"{eid}: opacity out of [0,1]")
        if el["type"] == "text":
            if el["width"] <= 0 or el["height"] <= 0:
                hard.append(f"{eid}: text w/h <= 0 (renderer crash)")
            if float(el["font_size"]) < 1:
                hard.append(f"{eid}: font_size < 1")
            elif float(el["font_size"]) != int(float(el["font_size"])):
                warn.append(f"nonint_font: {eid} font_size {el['font_size']} (drawn at int, wrapped at float)")
        if el["x"] < -0.5 or el["y"] < -0.5 or el["x"] + el["width"] > W + 0.5 or el["y"] + el["height"] > H + 0.5:
            hard.append(f"{eid}: off-canvas (unrotated box)")
        if el["type"] == "image" and el.get("fit", "contain") != "cover" and s and not is_full_bleed(s, cw, ch):
            a_src = s["width"] / max(s["height"], 1e-6)
            a_out = el["width"] / max(el["height"], 1e-6)
            if abs(a_out / a_src - 1) > ASPECT_TOL:
                hard.append(f"{eid}: image aspect {a_out:.2f} vs source {a_src:.2f}")
        if s:
            if el.get("fit", "contain") != s.get("fit", "contain") and el["type"] == "image":
                warn.append(f"fit_changed: {eid}")
            if float(el.get("rotation", 0) or 0) != float(s.get("rotation", 0) or 0) and renders_visible(el) \
                    and not declared_hidden(el):
                warn.append(f"rotation_changed: {eid}")
            for ck in ("color", "fill_color"):
                if ck in s and el.get(ck) != s.get(ck):
                    a, b = parse_rgba(el.get(ck)), parse_rgba(s.get(ck))
                    if a[:3] != b[:3]:
                        warn.append(f"colour_changed: {eid} {ck}")
        if renders_visible(el) and not declared_hidden(el):
            rx0, ry0, rx1, ry1 = rotated_aabb(el)
            if (rx0 < -1 or ry0 < -1 or rx1 > W + 1 or ry1 > H + 1) and abs(float(el.get("rotation", 0) or 0)) > 0.1:
                warn.append(f"rotated_clip: {eid} rotated corners leave canvas")
        if el["type"] == "text" and renders_visible(el) and el["width"] > 0:
            lay = text_layout(el)
            if lay["max_line_w"] > el["width"] + 1:
                ls = " (letter_spacing)" if el.get("letter_spacing") else ""
                warn.append(f"text_overflow_w: {eid} line {lay['max_line_w']:.0f} > box {el['width']:.0f}{ls}")
            if lay["block_h"] > el["height"] + 2:
                warn.append(f"text_overflow_h: {eid} {lay['n_lines']} lines need {lay['block_h']:.0f} > box {el['height']:.0f}")
            x0, y0, x1, y1 = lay["ink"]
            if x0 < -1 or x1 > W + 1 or y1 > H + 1:
                warn.append(f"text_off_canvas: {eid} ink ({x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f})")
            mx = s.get("max_lines") if s else None
            if mx and lay["n_lines"] > mx:
                warn.append(f"max_lines: {eid} {lay['n_lines']} > {mx}")
        if el["type"] == "image" and renders_visible(el) and asset_path(ASSETS, el.get("asset_id")) is None:
            warn.append(f"placeholder_visible: {eid} ({el['width']:.0f}x{el['height']:.0f})")
    warn += group_checks(source, out)
    return hard, warn


def group_checks(source: dict, out: dict) -> list[str]:
    """Groups travel together: all-or-nothing visibility; a label inside its shape stays inside."""
    issues = []
    src = {e["id"]: e for e in source["elements"]}
    groups: dict[str, list[dict]] = {}
    for e in out["elements"]:
        if e.get("group_id"):
            groups.setdefault(e["group_id"], []).append(e)
    for gid, mem in groups.items():
        meaningful = [m for m in mem if not (m["type"] == "text" and not str(m.get("content", "")).strip())]
        vis = [renders_visible(m) and not declared_hidden(m) for m in meaningful]
        if len(meaningful) > 1 and any(vis) and not all(vis):
            issues.append(f"group_partial: {gid} partially hidden")
            continue
        if not any(vis):
            continue
        shapes = [m for m in mem if m["type"] == "shape"]
        texts = [m for m in mem if m["type"] == "text"]
        for t in texts:
            for sh in shapes:
                st, ss = src.get(t["id"]), src.get(sh["id"])
                if not st or not ss:
                    continue
                inside_src = _center_inside(st, ss)
                if inside_src and not _center_inside(t, sh):
                    issues.append(f"group_broken: label {t['id']} left its shape {sh['id']}")
    return issues


def _center_inside(a: dict, b: dict) -> bool:
    cx, cy = a["x"] + a["width"] / 2, a["y"] + a["height"] / 2
    return b["x"] - 1 <= cx <= b["x"] + b["width"] + 1 and b["y"] - 1 <= cy <= b["y"] + b["height"] + 1
