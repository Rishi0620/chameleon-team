"""R2 spike: evidence for the critiques -- run the OTHER agents' spike code on NEW cases.

  * DESIGNER compose.py on the unseen split ad (U), the split-panel fixture (F2) and the
    busy-photo fixture (F1, whose background asset lives outside brand_kit -- as hidden-test
    assets may).
  * PERCEPTION's pixel critic on pairs where we know the right answer by eye.
  * JUDGE's proxy scorer on every output produced here (hard / soft issues).

Run from repo root:  .venv/bin/python design/debate/spikes/inventor/r2_crosscheck.py
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SP = ROOT / "design/debate/spikes"
sys.path.insert(0, str(HERE))
import galley as G  # noqa: E402
import r2_fixtures as FX  # noqa: E402
from unseen import design as UNSEEN  # noqa: E402

OUT = HERE / "out_r2"
FX.build_assets()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    sys.path.insert(0, str(SP / "designer"))
    DES = load("des_compose", SP / "designer/compose.py")
    CRIT = load("perc_critic", SP / "perception/critic.py")
    JUD = load("judge_proxy", SP / "judge/proxy_scorer.py")
    log, names = [], []
    cases = [("U", UNSEEN, [(1080, 1920), (1600, 400), (728, 90)]),
             ("F2", FX.F2, [(1080, 1920), (1600, 400), (728, 90)]),
             ("F1", FX.F1, [(1600, 400), (1080, 1920)])]
    for tag, src, targets in cases:
        for W, H in targets:
            task = {"source": copy.deepcopy(src), "target_canvas": {"width": W, "height": H}}
            try:
                design, arche = DES.compose(task)
            except Exception as ex:  # noqa: BLE001
                log.append(f"DESIGNER {tag} {W}x{H}: CRASH {type(ex).__name__}: {ex}")
                print(log[-1]); continue
            design = {"canvas": design["canvas"],
                      "elements": [{k: v for k, v in e.items() if k != "_orig_id"} for e in design["elements"]]}
            name = f"xc_designer_{tag}_{W}x{H}"
            (OUT / f"{name}.json").write_text(json.dumps(design, indent=1))
            G.render_design_to_png(design, str(FX.ASSETS2), str(OUT / f"{name}.png"),
                                   fonts_dir=str(ROOT / "brand_kit/fonts"))
            hidden = [e["id"] for e in design["elements"] if e.get("opacity", 1) == 0]
            JUD.ASSETS = str(FX.ASSETS2)
            r = JUD.score(src, design)
            log.append(f"DESIGNER {tag} {W}x{H}: archetype={arche} hidden={hidden} judge hard={r['hard']} soft={r['soft'][:3]}")
            print(log[-1]); names.append(name)
    # PERCEPTION critic on pairs with a known answer
    CRIT.ASSETS = str(FX.ASSETS2)
    pairs = [("F1 1600x400 calm-band vs v1 text-on-trees", "topo_F1_1600x400_calm", "topo_F1_1600x400_v1"),
             ("F2 1600x400 host/rider vs v1 floating island", "topo_F2_1600x400", "topo_F2_1600x400_v1"),
             ("U 1080x1920 optimizer vs galley", "U_1080x1920_optimizer", "U_1080x1920_galley"),
             ("U 1600x400 galley vs optimizer", "U_1600x400_galley", "U_1600x400_optimizer")]
    for label, a, b in pairs:
        res = []
        for n in (a, b):
            d = json.loads((OUT / f"{n}.json").read_text())
            bg_ids = [e["id"] for e in d["elements"] if e["width"] * e["height"] >= 0.85 * d["canvas"]["width"] * d["canvas"]["height"]]
            m, _ = CRIT.critique(d, roles={"background": bg_ids})
            res.append((n, m["penalty"], m["issues"][:4]))
        better = "AGREES with eye" if res[0][1] < res[1][1] else ("TIE" if res[0][1] == res[1][1] else "DISAGREES with eye")
        log.append(f"PERCEPTION critic [{label}]: eye-preferred {res[0][0]} pen={res[0][1]} vs {res[1][0]} pen={res[1][1]} -> {better}")
        log.append(f"      issues A: {res[0][2]}")
        log.append(f"      issues B: {res[1][2]}")
        print("\n".join(log[-3:]))
    # JUDGE proxy on every r2 output of ours
    JUD.ASSETS = str(FX.ASSETS2)
    srcs = {"topo_F1": FX.F1, "topo_F2": FX.F2, "U_": UNSEEN}
    tot_h = 0
    for p in sorted(OUT.glob("*.json")):
        src = next((v for k, v in srcs.items() if p.stem.startswith(k)), None)
        if src is None or "source" in p.stem:
            continue
        r = JUD.score(src, json.loads(p.read_text()))
        tot_h += len(r["hard"])
        if r["hard"]:
            log.append(f"JUDGE proxy {p.stem}: HARD {r['hard']}")
            print(log[-1])
    log.append(f"JUDGE proxy over our r2 outputs: total hard issues = {tot_h}")
    print(log[-1])
    (OUT / "crosscheck_log.txt").write_text("\n".join(log) + "\n")
    G.OUT, old = OUT, G.OUT
    try:
        G.contact_sheet(names, OUT / "sheet_xc_designer.png", width=1500)
    finally:
        G.OUT = old


if __name__ == "__main__":
    main()
