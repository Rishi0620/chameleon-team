"""R2 experiment: are the engines really id- and order-blind? (metamorphic test)

Every round-1 engine claims "roles from features, never ids". Hidden data uses opaque ids and an
arbitrary element order, so an engine whose output changes when we rename ids and permute the
list (keeping render order identical: only elements with EQUAL z keep their relative order) has a
hidden dependence that the 3 samples cannot reveal.

For each engine x design x size: run on the original task and on a renamed+permuted copy, map ids
back, and compare visibility, geometry (>0.5px) and font sizes.

Run from repo root:  .venv/bin/python design/debate/spikes/judge/r2_id_invariance.py
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BENCH = ROOT / "design" / "debate" / "bench"
OUT = Path(__file__).resolve().parent / "r2_out"
SIZES = ["leaderboard", "ig_story", "yt_thumb", "med_rect", "skyscraper"]
ENGINES = ["designer", "optimizer", "galley", "perception", "safe_floor"]


def scramble(task: dict, seed: int) -> tuple[dict, dict]:
    rng = random.Random(seed)
    src = copy.deepcopy(task["source"])
    fwd = {e["id"]: "q" + hashlib.md5(f"{seed}{e['id']}".encode()).hexdigest()[:9] for e in src["elements"]}
    gfwd = {}
    for e in src["elements"]:
        e["id"] = fwd[e["id"]]
        if e.get("group_id"):
            gfwd.setdefault(e["group_id"], "h" + hashlib.md5(f"{seed}{e['group_id']}".encode()).hexdigest()[:6])
            e["group_id"] = gfwd[e["group_id"]]
    # permute while keeping the relative order of equal-z elements (render order unchanged)
    els = src["elements"]
    keyed = [(e.get("z_index", 0), i, e) for i, e in enumerate(els)]
    slots = list(range(len(els)))
    rng.shuffle(slots)
    by_z: dict = {}
    for z, i, e in keyed:
        by_z.setdefault(z, []).append(e)
    order = sorted(range(len(els)), key=lambda k: slots[k])
    zs_in_slot = [keyed[k][0] for k in order]
    pools = {z: list(v) for z, v in by_z.items()}
    src["elements"] = [pools[z].pop(0) for z in zs_in_slot]
    return src, {v: k for k, v in fwd.items()}


def visible(e: dict) -> bool:
    if float(e.get("opacity", 1)) <= 0.001:
        return False
    c = str(e.get("color", ""))
    return not (e.get("type") == "text" and c.replace(" ", "").endswith(",0)"))


def compare(a: dict, b: dict, back: dict) -> list[str]:
    A = {e["id"]: e for e in a["elements"]}
    diffs = []
    for e in b["elements"]:
        o = A.get(back.get(e["id"]))
        if o is None:
            diffs.append(f"unmapped {e['id']}")
            continue
        if visible(o) != visible(e):
            diffs.append(f"{o['id']}: visibility {visible(o)}->{visible(e)}")
            continue
        if not visible(o):
            continue
        d = max(abs(float(o[k]) - float(e[k])) for k in ("x", "y", "width", "height"))
        if d > 0.5:
            diffs.append(f"{o['id']}: geometry moved {d:.0f}px")
        if o.get("type") == "text" and abs(float(o.get("font_size", 0)) - float(e.get("font_size", 0))) > 0.01:
            diffs.append(f"{o['id']}: font {o.get('font_size')}->{e.get('font_size')}")
    return diffs


def run_engine(engine: str) -> dict:
    import os
    os.chdir(ROOT)
    sys.path.insert(0, str(BENCH))
    sys.path.insert(0, str(ROOT))
    from catalogue import CATALOGUE
    from designs import load_all
    ad = importlib.import_module({"designer": "adapters.designer", "optimizer": "adapters.optimizer",
                                  "galley": "adapters.galley", "perception": "adapters.perception",
                                  "safe_floor": "adapters.safe_floor"}[engine])
    res = {"engine": engine, "cases": 0, "identical": 0, "errors": 0, "examples": []}
    for i, (name, task) in enumerate(sorted(load_all().items())):
        if engine == "galley" and name == "S12_many_badges":
            res["examples"].append("S12_many_badges skipped for galley (100-180 s per solve)")
            continue
        for size in SIZES:
            W, H = CATALOGUE[size]
            if hasattr(ad, "applies") and not ad.applies(W, H):
                continue
            tgt = {"width": W, "height": H}

            def fresh():  # OPTIMIZER's id()-keyed caches go stale across solves; isolate each call
                if engine == "optimizer":
                    for c in (ad._mod._cw, ad._mod._met, ad._mod._wk):
                        c.clear()
            try:
                fresh()
                a = ad.resize(copy.deepcopy(task["source"]), tgt)
                s2, back = scramble(task, seed=1000 + i)
                fresh()
                b = ad.resize(s2, tgt)
            except Exception as exc:  # noqa: BLE001
                res["errors"] += 1
                res["examples"].append(f"{name}/{size}: ERROR {type(exc).__name__}: {str(exc)[:80]}")
                continue
            d = compare(a, b, back)
            res["cases"] += 1
            res["identical"] += not d
            if d:
                res["examples"].append(f"{name}/{size}: {len(d)} diffs, e.g. {d[:3]}")
    return res


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    with ProcessPoolExecutor(max_workers=len(ENGINES), max_tasks_per_child=1) as ex:
        results = list(ex.map(run_engine, ENGINES))
    (OUT / "id_invariance.json").write_text(json.dumps(results, indent=1))
    for r in results:
        print(f"{r['engine']:<11} identical {r['identical']}/{r['cases']}  errors {r['errors']}")
        for e in r["examples"][:6]:
            print("    ", e)
