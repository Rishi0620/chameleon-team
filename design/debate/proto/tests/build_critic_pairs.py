"""Build proto/tests/critic_pairs.json, the labelled set for critic.py (owner: PERCEPTION).

Sources of labels (never the critic itself):
  1. PERCEPTION's Round-2 eye rankings of all engines' outputs (spikes/perception/r2_out/eye_rankings.json),
     plus per-output defect labels made by eye from the Round-2 contact sheets and native-resolution PNGs.
  2. INVENTOR's 4 eye-known pairs (spikes/inventor/out_r2, Round 2 crosscheck).
  3. PERCEPTION's BLIND near-tie picks on GALLEY top-10s (r2_out/near_ties_eye_BLIND.json; candidates regenerated).
  4. Synthetic mutations of clean outputs, one per veto type (label = defect by construction).
Run from repo root:  .venv/bin/python design/debate/proto/tests/build_critic_pairs.py
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
T = Path(__file__).resolve().parent
DATA = T / "data"
DATA.mkdir(exist_ok=True)
SP = ROOT / "design/debate/spikes"
LV = {1: "level1_warmup", 2: "level2_core", 3: "level3_advanced"}
BRAND = "brand_kit/assets"
FIX_ASSETS = "design/debate/proto/fixtures/assets"
rel = lambda p: str(Path(p).resolve().relative_to(ROOT))

# ---------------------------------------------------------------- info (roles in the proto vocabulary)
sys.path.insert(0, str(SP / "perception"))
import roles as PR  # noqa: E402

MAP = {"background": "background", "headline": "headline", "subhead": "subhead", "legal": "legal",
       "cta_bg": "cta_shape", "cta_label": "cta_label", "cta_text": "cta_label", "badge_bg": "badge_shape",
       "badge_label": "badge_label", "sticker": "furniture", "logo": "logo", "hero": "hero",
       "decoration": "decoration", "panel": "panel", "unseen_image": "unknown", "other": "unknown"}


def make_info(src, assets_dir):
    PR.ASSETS = ROOT / assets_dir
    PR._cache.clear()
    r = {k: MAP.get(v, "unknown") for k, v in PR.infer_roles(src).items()}
    groups, containers = {}, {}
    for e in src["elements"]:
        if e.get("group_id"):
            groups.setdefault(e["group_id"], []).append(e["id"])
    for h in src["elements"]:
        if r.get(h["id"]) != "panel":
            continue
        riders = [e["id"] for e in src["elements"] if e["id"] != h["id"] and e.get("z_index", 0) > h.get("z_index", 0)
                  and h["x"] <= e["x"] + e["width"] / 2 <= h["x"] + h["width"]
                  and h["y"] <= e["y"] + e["height"] / 2 <= h["y"] + h["height"]]
        if riders:
            containers[h["id"]] = riders
    return {"roles": r, "groups": groups, "containers": containers, "hidden": [], "assets_dir": assets_dir,
            "_note": "built by build_critic_pairs.py from PERCEPTION's spike role inference (engine info stand-in)"}


outputs, pairs, sources = [], [], {}


def add_source(key, src, assets_dir, path):
    sources[key] = {"path": path, "assets_dir": assets_dir, "info": make_info(src, assets_dir)}


def add_out(oid, skey, path, label, kinds, note, by):
    outputs.append({"id": oid, "source": skey, "output": path, "label": label, "defect_kinds": kinds, "note": note,
                    "labeller": by})


# ---------------------------------------------------------------- 1. Round-2 cross-engine, eye labels
for n in (1, 2, 3):
    p = ROOT / f"input/chameleon_sample_{LV[n]}.json"
    add_source(f"L{n}", json.loads(p.read_text())["source"], BRAND, rel(p))
eye = {k: v for k, v in json.loads((SP / "perception/r2_out/eye_rankings.json").read_text()).items()
       if not k.startswith("_")}
# per-output defect labels made by eye (Round-2 sheets; native PNGs for 160x600). "clean" = no veto-worthy defect.
DEFECT = {
    ("L2->1600x400", "judge_safefit"): ["ILLEGIBLE"], ("L2->1600x400", "baseline_stretch"): ["ILLEGIBLE"],
    ("L2->728x90", "judge_safefit"): ["ILLEGIBLE"], ("L2->728x90", "baseline_stretch"): ["ILLEGIBLE"],
    ("L3->728x90", "judge_mock"): ["SPILL"], ("L3->728x90", "judge_safefit"): ["ILLEGIBLE"],
    ("L3->728x90", "baseline_stretch"): ["ILLEGIBLE", "CLIPPED", "PLACEHOLDER"],
    ("L3->1600x400", "judge_safefit"): ["ILLEGIBLE"], ("L3->1600x400", "baseline_stretch"): ["ILLEGIBLE", "PLACEHOLDER"],
    ("L3->1080x1920", "baseline_stretch"): ["PLACEHOLDER"],
    ("L2->300x250", "judge_safefit"): ["ILLEGIBLE"], ("L2->300x250", "baseline_stretch"): ["ILLEGIBLE"],
    ("L3->160x600", "judge_safefit"): ["ILLEGIBLE"], ("L3->160x600", "baseline_stretch"): ["ILLEGIBLE", "PLACEHOLDER"],
    ("L3->160x600", "optimizer"): ["ILLEGIBLE"],    # 8 px CTA label + 7 px legal at native 160 px (DESIGNER R-rules agree)
    ("L3->160x600", "inventor"): ["ILLEGIBLE"],     # ~7 px CTA label at native resolution
}
spec = importlib.util.spec_from_file_location("jfb", SP / "judge/fallback_and_sweep.py")
jfb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jfb)
code = (SP / "perception/r2_cross_engine.py").read_text().split("tasks = set()")[0]
g = {"__file__": str(SP / "perception/r2_cross_engine.py")}
exec(compile(code, "r2ce", "exec"), g)
for task, order in eye.items():
    n, (W, H) = int(task[1]), map(int, task.split(">")[1].split("x"))
    src = json.loads((ROOT / sources[f"L{n}"]["path"]).read_text())["source"]
    c = g["candidates"](n, W, H)
    c["judge_safefit"] = jfb.safe_fit(src, {"width": W, "height": H})
    c["baseline_stretch"] = g["stretch"](src, W, H)
    for eng in order:
        d = g["remap"](src, c[eng])
        path = DATA / f"r2_L{n}_{W}x{H}_{eng}.json"
        path.write_text(json.dumps(d))
        kinds = DEFECT.get((task, eng), [])
        add_out(f"r2:{task}:{eng}", f"L{n}", rel(path), "defect" if kinds else "clean", kinds, "",
                "perception-eye (round 2)")
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            la, lb = DEFECT.get((task, a)), DEFECT.get((task, b))
            kind = "defect" if (lb and not la) else ("taste" if not la and not lb else "skip")
            if kind != "skip":
                pairs.append({"better": f"r2:{task}:{a}", "worse": f"r2:{task}:{b}", "kind": kind,
                              "by": "perception-eye (round 2)"})

# ---------------------------------------------------------------- 2. INVENTOR's 4 eye-known pairs
INV = SP / "inventor/out_r2"
for key, f in (("F1", "inventor_F1.json"), ("F2", "inventor_F2.json"), ("U", "inventor_U.json")):
    p = ROOT / "design/debate/proto/fixtures" / f
    d = json.loads(p.read_text())
    add_source(key, d.get("source", d), FIX_ASSETS, rel(p))
for skey, a, b, kind, kinds_b in (("F1", "topo_F1_1600x400_calm", "topo_F1_1600x400_v1", "defect", ["BUSY_BACKDROP"]),
                                  ("F2", "topo_F2_1600x400", "topo_F2_1600x400_v1", "taste", []),
                                  ("U", "U_1080x1920_optimizer", "U_1080x1920_galley", "taste", []),
                                  ("U", "U_1600x400_galley", "U_1600x400_optimizer", "taste", [])):
    add_out(f"inv:{a}", skey, rel(INV / f"{a}.json"), "clean", [], "", "inventor-eye (round 2)")
    add_out(f"inv:{b}", skey, rel(INV / f"{b}.json"), "defect" if kinds_b else "clean", kinds_b,
            "text set over striped trees" if kinds_b else "", "inventor-eye (round 2)")
    pairs.append({"better": f"inv:{a}", "worse": f"inv:{b}", "kind": kind, "by": "inventor-eye (round 2)"})

# ---------------------------------------------------------------- 3. blind near-tie picks (GALLEY top-10, regenerated)
sys.path.insert(0, str(SP / "inventor"))
import galley as G  # noqa: E402
key = json.loads((SP / "perception/r2_out/near_ties_key.json").read_text())
blind = {k: v for k, v in json.loads((SP / "perception/r2_out/near_ties_eye_BLIND.json").read_text()).items()
         if not k.startswith("_")}
uspec = importlib.util.spec_from_file_location("unseen", SP / "inventor/unseen.py")
U = importlib.util.module_from_spec(uspec)
uspec.loader.exec_module(U)
for tag, pick in blind.items():
    name, (W, H) = tag.split("_")[0], map(int, tag.split("_")[1].split("x"))
    src = U.design if name == "U" else json.loads((ROOT / sources[name]["path"]).read_text())["source"]
    skey = "U_galley_src" if name == "U" else name
    if skey not in sources:
        p = DATA / "U_galley_source.json"
        p.write_text(json.dumps(src))
        add_source(skey, src, BRAND, rel(p))
    gg = G.decompile(src)
    ctx, res = G.solve(gg, W, H, top_k=10, verbose=False)
    for L in set(pick["top3"]) | set(pick["worst"]):
        cand = res[key[tag][L]["galley_rank"] - 1]
        d = G.emit(gg, src, ctx, cand)
        p = DATA / f"nt_{tag}_{L}.json"
        p.write_text(json.dumps(d))
        add_out(f"nt:{tag}:{L}", skey, rel(p), "clean", [], "near-tie candidate (taste only)", "perception-eye BLIND")
    for a in pick["top3"]:
        for b in pick["worst"]:
            pairs.append({"better": f"nt:{tag}:{a}", "worse": f"nt:{tag}:{b}", "kind": "taste",
                          "by": "perception-eye BLIND (round 2)"})

# ---------------------------------------------------------------- 4. synthetic mutations (one per veto type)
def mutate(base_id, new_id, fn, kinds, note):
    b = next(o for o in outputs if o["id"] == base_id)
    d = json.loads((ROOT / b["output"]).read_text())
    d2 = copy.deepcopy(d)
    fn({e["id"]: e for e in d2["elements"]}, d2)
    p = DATA / f"mut_{new_id}.json"
    p.write_text(json.dumps(d2))
    add_out(f"mut:{new_id}", b["source"], rel(p), "defect", kinds, note, "synthetic mutation")
    pairs.append({"better": base_id, "worse": f"mut:{new_id}", "kind": "defect", "by": "synthetic mutation"})


def leak(E, d):
    E["subhead"]["color"] = "rgba(255,255,255,0.9)"              # opacity stays 0: the renderer ignores text opacity


def placeholder(E, d):
    E["holiday_watermark"].update(opacity=1.0, x=600, y=70, width=36, height=16)


def clipped(E, d):
    E["headline"].update(width=150.0)                            # re-wraps to many lines that run off the canvas


def illegible(E, d):
    E["subhead"]["font_size"] = 5


def collide(E, d):
    hl = E["headline"]
    dx, dy = hl["x"] + 20 - E["badge_bg"]["x"], hl["y"] + 5 - E["badge_bg"]["y"]
    for k in ("badge_bg", "badge_label"):
        E[k]["x"] += dx
        E[k]["y"] += dy


def spill(E, d):
    E["cta_label"]["y"] += 0.8 * E["cta_bg"]["height"]


def lost(E, d):
    E["p2"].update(x=840.0, y=340.0, width=200.0)                # white subhead onto the pale sun


def rotclip(E, d):
    W = d["canvas"]["width"]
    for k in ("ribbon_bg", "ribbon_label"):          # un-hide the ribbon and park it in the top-right corner
        E[k].update(x=W - 241.0, y=1.0, width=240.0, height=44.0, opacity=1.0, rotation=-12)
    E["ribbon_label"].update(color="rgba(255,255,255,1)", font_size=20, y=8.0, height=28.0)


mutate("r2:L3->728x90:optimizer", "L3_728_leak", leak, ["HIDDEN_LEAK"], "subhead hidden by opacity only")
mutate("r2:L3->728x90:optimizer", "L3_728_placeholder", placeholder, ["PLACEHOLDER"], "missing-asset image shown")
mutate("r2:L3->728x90:optimizer", "L3_728_clipped", clipped, ["CLIPPED"], "headline narrowed until it runs off canvas")
mutate("r2:L2->728x90:optimizer", "L2_728_illegible", illegible, ["ILLEGIBLE"], "subhead at 5 px")
mutate("r2:L2->1600x400:designer", "L2_1600_collide", collide, ["INK_COLLISION"], "badge dropped onto the headline")
mutate("r2:L2->1600x400:optimizer", "L2_1600_spill", spill, ["SPILL"], "CTA label pushed out of its pill")
mutate("r2:L3->1600x400:optimizer", "L3_1600_rotclip", rotclip, ["CLIPPED"], "ribbon kept, rotated corner off canvas")
# F1 at its own canvas (target = source canvas): white subhead moved onto the pale sun
f1 = json.loads((ROOT / sources["F1"]["path"]).read_text())["source"]
p = DATA / "F1_identity.json"
p.write_text(json.dumps(f1))
add_out("fx:F1_identity", "F1", rel(p), "clean", [], "source as output (fixed point)", "by construction")
mutate("fx:F1_identity", "F1_lost_backdrop", lost, ["LOST_BACKDROP"], "white subhead on the pale sun")

json.dump({"_doc": __doc__, "sources": sources, "outputs": outputs, "pairs": pairs},
          open(T / "critic_pairs.json", "w"), indent=1)
print(f"{len(sources)} sources, {len(outputs)} outputs "
      f"({sum(o['label'] == 'defect' for o in outputs)} defect / {sum(o['label'] == 'clean' for o in outputs)} clean), "
      f"{len(pairs)} pairs ({sum(p['kind'] == 'defect' for p in pairs)} defect, {sum(p['kind'] == 'taste' for p in pairs)} taste)")
