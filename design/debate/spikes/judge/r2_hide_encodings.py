"""R2 experiment: which HIDE encoding for text is safest? (moderator open problem #7)

Takes real bench outputs that hide >=1 text element (designer / galley / optimizer / perception) and
re-encodes every hidden text four ways, keeping everything else identical:

  E1 alpha    opacity 0 + colour (and style_run colours) alpha 0, RGB kept       <- R2 team default
  E2 z-under  opacity 0 + source colour + z_index = min_z - 1 (under the opaque full-bleed layer)
  E3 opacity  opacity 0 only, source colour (the naive encoding)
  E4 tiny     opacity 0 + source colour + font_size 1 + 1x1 box (still in bounds)

and measures (a) pixel truth: changed pixels vs. a render with the hidden elements deleted, and
(b) which PLAUSIBLE structural-checker rules each encoding trips:
  C1 colour string unchanged (strict)      C2 colour RGB unchanged
  C3 relative z-order unchanged, all pairs C4 relative z-order unchanged, opacity>0 pairs only
  C5 font_size >= 9 judge-px, all text     C6 font_size >= 9 judge-px, opacity>0 text only
Plus (c) applicability of E2: is there an opaque full-bleed layer at the bottom of the stack?

Run from repo root:  .venv/bin/python design/debate/spikes/judge/r2_hide_encodings.py
"""
from __future__ import annotations

import copy
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
BENCH = ROOT / "design" / "debate" / "bench"
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(ROOT))
from common import ASSETS, render_rgba  # noqa: E402
from contract import declared_hidden  # noqa: E402
from designs import load_all  # noqa: E402
from PIL import Image  # noqa: E402
from renderer.converter.assets import asset_path  # noqa: E402
from renderer.converter.colorutil import parse_rgba  # noqa: E402

OUT = Path(__file__).resolve().parent / "r2_out"
ENGINES = ["designer", "galley", "optimizer", "perception"]
N_PER_ENGINE = 30


def opaque_full_bleed_bottom(design: dict) -> bool:
    W, H = design["canvas"]["width"], design["canvas"]["height"]
    els = sorted(enumerate(design["elements"]), key=lambda t: (t[1].get("z_index", 0), t[0]))
    for _, e in els:
        if float(e["width"]) * float(e["height"]) < 0.98 * W * H or float(e.get("opacity", 1)) < 0.999:
            continue
        if e["type"] == "shape" and e.get("shape_type", "rectangle") == "rectangle" \
                and parse_rgba(e.get("fill_color"))[3] >= 0.999 and not e.get("corner_radius"):
            return True
        if e["type"] == "image" and e.get("fit") in ("cover", "fill"):
            p = asset_path(ASSETS, e.get("asset_id"))
            if p is not None and Image.open(p).mode == "RGB":
                return True
    return False


def encode(out: dict, src: dict, hidden: set[str], how: str) -> dict:
    d = copy.deepcopy(out)
    S = {e["id"]: e for e in src["elements"]}
    min_z = min(int(e.get("z_index", 0)) for e in d["elements"])
    for e in d["elements"]:
        if e["id"] not in hidden:
            continue
        s = S[e["id"]]
        e["opacity"] = 0.0
        e["color"] = s["color"]
        if "style_runs" in s:
            e["style_runs"] = copy.deepcopy(s["style_runs"])
        if how == "alpha":
            r, g, b, _ = parse_rgba(s["color"])
            e["color"] = f"rgba({r},{g},{b},0)"
            for run in e.get("style_runs") or []:
                if "color" in run:
                    rr, gg, bb, _ = parse_rgba(run["color"])
                    run["color"] = f"rgba({rr},{gg},{bb},0)"
        elif how == "z_under":
            e["z_index"] = min_z - 1
        elif how == "tiny":
            e.update(font_size=1, width=1.0, height=1.0)
    return d


def z_order(design: dict, only_visible: bool) -> list[str]:
    els = [(int(e.get("z_index", 0)), i, e["id"]) for i, e in enumerate(design["elements"])
           if not only_visible or float(e.get("opacity", 1)) > 0]
    return [x[2] for x in sorted(els)]


def checks(d: dict, src: dict) -> set[str]:
    S = {e["id"]: e for e in src["elements"]}
    W, H = d["canvas"]["width"], d["canvas"]["height"]
    k = min(1.0, 1024 / max(W, H))
    tripped = set()
    for e in d["elements"]:
        s = S[e["id"]]
        if e["type"] == "text":
            if e.get("color") != s.get("color") or [r.get("color") for r in e.get("style_runs") or []] != \
                    [r.get("color") for r in s.get("style_runs") or []]:
                tripped.add("C1 strict colour")
            if parse_rgba(e.get("color"))[:3] != parse_rgba(s.get("color"))[:3]:
                tripped.add("C2 colour RGB")
            if str(e.get("content", "")).strip() and int(float(e["font_size"])) * k < 9:
                tripped.add("C5 font floor (all)")
                if float(e.get("opacity", 1)) > 0:
                    tripped.add("C6 font floor (opacity>0)")
    for only_vis, name in ((False, "C3 z-order (all)"), (True, "C4 z-order (opacity>0)")):
        src_rank = {i: n for n, i in enumerate(z_order(src, False))}
        seq = [src_rank[i] for i in z_order(d, only_vis)]
        if seq != sorted(seq):
            tripped.add(name)
    return tripped


def leak(d: dict, hidden: set[str]) -> int:
    a = render_rgba(d, max_size=1024)[..., :3].astype(int)
    b = render_rgba({"canvas": d["canvas"], "elements": [e for e in d["elements"] if e["id"] not in hidden]},
                    max_size=1024)[..., :3].astype(int)
    return int((np.abs(a - b).sum(axis=2) > 30).sum())


def main() -> None:
    tasks = load_all()
    rng = random.Random(3)
    cases = []
    for eng in ENGINES:
        pool = []
        for f in sorted((BENCH / "results" / eng / "json").glob("*.json")):
            design, size = f.stem.split("__")
            out = json.loads(f.read_text())
            src = tasks[design]["source"]
            S = {e["id"]: e for e in src["elements"]}
            hid = {e["id"] for e in out.get("elements", []) if e.get("type") == "text"
                   and str(S.get(e["id"], {}).get("content", "")).strip() and declared_hidden(e)}
            if hid:
                pool.append((eng, design, size, out, src, hid))
        rng.shuffle(pool)
        cases += pool[:N_PER_ENGINE]
    res = defaultdict(lambda: {"cases": 0, "leaking_cases": 0, "leak_px": 0, "trips": Counter()})
    applic = Counter()
    for eng, design, size, out, src, hid in cases:
        has_bg = opaque_full_bleed_bottom(out)
        applic["with_opaque_full_bleed"] += has_bg
        applic["total"] += 1
        for how in ("alpha", "z_under", "opacity", "tiny"):
            d = encode(out, src, hid, how)
            px = leak(d, hid)
            r = res[how]
            r["cases"] += 1
            r["leaking_cases"] += px > 10
            r["leak_px"] += px
            r["trips"].update(checks(d, src))
    # E2 applicability over every bench design source
    designs_ok = {n: opaque_full_bleed_bottom(t["source"]) for n, t in tasks.items()}
    report = {"n_cases": len(cases), "by_engine": dict(Counter(c[0] for c in cases)),
              "e2_applicable_in_sampled_outputs": dict(applic),
              "designs_with_opaque_full_bleed_bottom": designs_ok,
              "encodings": {k: {"cases": v["cases"], "leaking_cases": v["leaking_cases"],
                                "mean_leak_px": round(v["leak_px"] / max(1, v["cases"]), 1),
                                "trips_cases": dict(v["trips"])} for k, v in res.items()}}
    OUT.mkdir(exist_ok=True)
    (OUT / "hide_encodings.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
