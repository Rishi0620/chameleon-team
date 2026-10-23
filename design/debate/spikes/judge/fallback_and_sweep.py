"""JUDGE spike: (1) a guaranteed-safe fallback layout, (2) a sweep over a
real platform-size catalogue comparing baseline-stretch vs safe-fit with the
proxy scorer, (3) can a dropped TEXT element be hidden in the render at all?

Run from repo root:
    .venv/bin/python design/debate/spikes/judge/fallback_and_sweep.py
"""
import copy
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, ".")
sys.path.insert(0, "design/debate/spikes/judge")
from engine.resize import resize as baseline_resize  # noqa: E402
from proxy_scorer import rotated_aabb, score  # noqa: E402
from renderer.converter.assets import asset_path  # noqa: E402
from renderer.converter.convert import render_design_to_png  # noqa: E402

OUT = Path("design/debate/spikes/judge/out")
ASSETS = "brand_kit/assets"

CATALOGUE = {  # name: (w, h) - common published platform specs
    "Instagram Post": (1080, 1080), "Instagram Portrait": (1080, 1350),
    "Instagram Story/Reel": (1080, 1920), "Instagram Landscape": (1080, 566),
    "Facebook Post (link)": (1200, 630), "Facebook Cover": (820, 312),
    "Facebook Event Cover": (1920, 1005), "X/Twitter Post": (1600, 900),
    "X/Twitter Header": (1500, 500), "LinkedIn Post": (1200, 627),
    "LinkedIn Banner": (1584, 396), "Pinterest Pin": (1000, 1500),
    "YouTube Thumbnail": (1280, 720), "YouTube Channel Art": (2560, 1440),
    "Presentation 16:9": (1920, 1080), "IAB Leaderboard": (728, 90),
    "IAB Large Leaderboard": (970, 90), "IAB Billboard": (970, 250),
    "IAB Medium Rectangle": (300, 250), "IAB Large Rectangle": (336, 280),
    "IAB Half Page": (300, 600), "IAB Wide Skyscraper": (160, 600),
    "IAB Mobile Banner": (320, 50), "IAB Large Mobile Banner": (320, 100),
    "Email Header": (600, 200), "US Letter Flyer @150dpi": (1275, 1650),
}


def is_full_bleed(el, cw, ch):
    return el["x"] <= 0.02 * cw and el["y"] <= 0.02 * ch and \
        el["width"] * el["height"] >= 0.9 * cw * ch


def safe_fit(source, target):
    """Fallback L2: uniform 'contain' scale of the whole design, centred; full-bleed
    layers stretched to the new canvas; missing assets hidden; rotated AABBs clamped.
    Structurally safe by construction, visually 'small but faithful'."""
    W, H = target["width"], target["height"]
    cw, ch = source["canvas"]["width"], source["canvas"]["height"]
    s = min(W / cw, H / ch)
    ox, oy = (W - cw * s) / 2, (H - ch * s) / 2
    out = []
    for el in source["elements"]:
        e = copy.deepcopy(el)
        if is_full_bleed(el, cw, ch):
            e.update(x=0.0, y=0.0, width=float(W), height=float(H))
        else:
            e.update(x=ox + el["x"] * s, y=oy + el["y"] * s,
                     width=max(1.0, el["width"] * s), height=max(1.0, el["height"] * s))
            if e["type"] == "text":
                e["font_size"] = max(1, int(round(float(el["font_size"]) * s)))
        if e["type"] == "image" and asset_path(ASSETS, e.get("asset_id")) is None:
            e["opacity"] = 0.0  # 'skip' a missing asset (works for image/shape, NOT text)
        clamp_inside(e, W, H)
        out.append(e)
    return {"canvas": {"width": W, "height": H}, "elements": out}


def clamp_inside(e, W, H):
    """Shrink (aspect-preserving) then translate so BOTH the unrotated box and the
    rotated AABB are inside the canvas."""
    x0, y0, x1, y1 = rotated_aabb(e)
    k = min(1.0, W / max(x1 - x0, 1e-6), H / max(y1 - y0, 1e-6),
            W / max(e["width"], 1e-6), H / max(e["height"], 1e-6))
    if k < 1.0:
        cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
        e["width"], e["height"] = max(1.0, e["width"] * k), max(1.0, e["height"] * k)
        e["x"], e["y"] = cx - e["width"] / 2, cy - e["height"] / 2
        if e["type"] == "text":
            e["font_size"] = max(1, int(e["font_size"] * k))
    x0, y0, x1, y1 = rotated_aabb(e)
    dx = -x0 if x0 < 0 else (W - x1 if x1 > W else 0.0)
    dy = -y0 if y0 < 0 else (H - y1 if y1 > H else 0.0)
    e["x"] = min(max(0.0, e["x"] + dx), W - e["width"])
    e["y"] = min(max(0.0, e["y"] + dy), H - e["height"])


def sweep():
    tasks = {p.stem.replace("chameleon_sample_", ""): json.loads(p.read_text())
             for p in sorted(Path("input").glob("*.json"))}
    rows, tally = [], {"baseline": Counter(), "safe_fit": Counter()}
    crashes = Counter()
    for lvl, task in tasks.items():
        for name, (w, h) in CATALOGUE.items():
            tgt = {"width": w, "height": h}
            for eng_name, eng in (("baseline", baseline_resize), ("safe_fit", safe_fit)):
                t0 = time.time()
                try:
                    out = eng(copy.deepcopy(task["source"]), tgt)
                except Exception as exc:  # noqa: BLE001
                    crashes[eng_name] += 1
                    print("CRASH", eng_name, lvl, name, exc)
                    continue
                r = score(task["source"], out)
                dt = time.time() - t0
                tally[eng_name]["cases"] += 1
                tally[eng_name]["cases_with_hard"] += bool(r["hard"])
                tally[eng_name]["hard_issues"] += len(r["hard"])
                tally[eng_name]["soft_issues"] += len(r["soft"])
                tally[eng_name]["unreadable_text"] += sum("perceived font" in s for s in r["soft"])
                tally[eng_name]["clipped_rotation"] += sum("rotated corners" in s for s in r["soft"])
                rows.append({"level": lvl, "target": name, "size": [w, h], "engine": eng_name,
                             "hard": r["hard"], "soft": r["soft"], "secs": round(dt, 3)})
    # render-crash check on every safe_fit output (the renderer is the real gate)
    render_fail = 0
    for row in rows:
        if row["engine"] != "safe_fit":
            continue
        task = tasks[row["level"]]
        out = safe_fit(copy.deepcopy(task["source"]), {"width": row["size"][0], "height": row["size"][1]})
        try:
            render_design_to_png(out, ASSETS, str(OUT / "sweep_tmp.png"), max_size=512)
        except Exception as exc:  # noqa: BLE001
            render_fail += 1
            print("RENDER CRASH", row["level"], row["target"], exc)
    (OUT.parent / "sweep_results.json").write_text(json.dumps(rows, indent=1))
    print("\n=== sweep: 3 samples x", len(CATALOGUE), "catalogue sizes ===")
    for k, c in tally.items():
        print(f"{k:<9} {dict(c)}  engine-crashes={crashes[k]}")
    print("safe_fit render crashes:", render_fail)
    worst = Counter()
    for row in rows:
        if row["engine"] == "safe_fit":
            worst[row["target"]] += sum("perceived font" in s for s in row["soft"])
    print("safe_fit unreadable-text count by target (top 8):", worst.most_common(8))


def hide_text_experiment():
    """Can a 'dropped' text element be made invisible without touching colour?"""
    W, H = 728, 90
    base = {"id": "bg", "type": "image", "x": 0, "y": 0, "width": W, "height": H, "z_index": 0,
            "asset_id": "solstice_bg_gradient.png", "fit": "cover"}
    txt = {"id": "legal", "type": "text", "x": 20, "y": 20, "width": 600, "height": 40,
           "content": "Please drink responsibly.", "font_family": "Solstice Sans", "font_size": 30,
           "color": "rgba(255,255,255,1)", "text_align": "left"}
    variants = {
        "a_visible": dict(txt, z_index=5),
        "b_opacity0": dict(txt, z_index=5, opacity=0),
        "c_opacity0_under_bg": dict(txt, z_index=-1, opacity=0),
        "d_fontsize1": dict(txt, z_index=5, font_size=1),
    }
    ref = None
    for name, t in variants.items():
        p = OUT / f"hide_{name}.png"
        render_design_to_png({"canvas": {"width": W, "height": H}, "elements": [base, t]}, ASSETS, str(p))
        a = np.asarray(Image.open(p).convert("RGB")).astype(int)
        if ref is None:
            only_bg = OUT / "hide_ref_bg.png"
            render_design_to_png({"canvas": {"width": W, "height": H}, "elements": [base]}, ASSETS, str(only_bg))
            ref = np.asarray(Image.open(only_bg).convert("RGB")).astype(int)
        changed = int((np.abs(a - ref).sum(axis=2) > 24).sum())
        print(f"hide-text {name:<22} pixels differing from bg-only render: {changed}")


if __name__ == "__main__":
    hide_text_experiment()
    sweep()
