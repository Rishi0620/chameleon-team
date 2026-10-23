"""JUDGE safe floor: uniform contain-scale of the whole design, centred; full-bleed layers stretched
to the canvas; missing assets hidden (opacity 0); rotated AABBs clamped; integer fonts; pure Python.
Structurally safe by construction, visually 'small but faithful'. Never raises."""
import copy
import math
from pathlib import Path

from ._load import BENCH_ASSETS

NAME = "safe_floor"


def _rot_aabb(e):
    r = math.radians(float(e.get("rotation", 0) or 0))
    cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
    hw = abs(e["width"] / 2 * math.cos(r)) + abs(e["height"] / 2 * math.sin(r))
    hh = abs(e["width"] / 2 * math.sin(r)) + abs(e["height"] / 2 * math.cos(r))
    return cx - hw, cy - hh, cx + hw, cy + hh


def _clamp(e, W, H):
    x0, y0, x1, y1 = _rot_aabb(e)
    k = min(1.0, W / max(x1 - x0, 1e-6), H / max(y1 - y0, 1e-6), W / max(e["width"], 1e-6), H / max(e["height"], 1e-6))
    if k < 1.0:
        cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
        e["width"], e["height"] = max(1.0, e["width"] * k), max(1.0, e["height"] * k)
        e["x"], e["y"] = cx - e["width"] / 2, cy - e["height"] / 2
        if e["type"] == "text":
            e["font_size"] = max(1, int(e["font_size"] * k))
    x0, y0, x1, y1 = _rot_aabb(e)
    e["x"] += -x0 if x0 < 0 else (W - x1 if x1 > W else 0.0)
    e["y"] += -y0 if y0 < 0 else (H - y1 if y1 > H else 0.0)
    e["x"] = round(min(max(0.0, e["x"]), W - e["width"]), 2)
    e["y"] = round(min(max(0.0, e["y"]), H - e["height"]), 2)


def resize(source, target_canvas):
    W, H = int(target_canvas["width"]), int(target_canvas["height"])
    cw, ch = source["canvas"]["width"], source["canvas"]["height"]
    s = min(W / cw, H / ch)
    ox, oy = (W - cw * s) / 2, (H - ch * s) / 2
    out = []
    for el in source["elements"]:
        e = copy.deepcopy(el)
        if el["width"] * el["height"] >= 0.8 * cw * ch:
            e.update(x=0.0, y=0.0, width=float(W), height=float(H))
        else:
            e.update(x=ox + el["x"] * s, y=oy + el["y"] * s,
                     width=max(1.0, el["width"] * s), height=max(1.0, el["height"] * s))
            if e["type"] == "text":
                e["font_size"] = max(1, int(round(float(el["font_size"]) * s)))
        if e["type"] == "image" and not (Path(BENCH_ASSETS) / str(e.get("asset_id"))).is_file():
            e["opacity"] = 0.0
        _clamp(e, W, H)
        out.append(e)
    return {"canvas": {"width": W, "height": H}, "elements": out}
