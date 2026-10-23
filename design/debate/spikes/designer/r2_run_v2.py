"""Round-2: run the UNCHANGED round-1 compose.py on designs it never saw. Honest test.
Run from repo root: .venv/bin/python design/debate/spikes/designer/r2_run.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.argv = sys.argv[:1]
import r2_compose as C  # noqa: E402
import roles as R  # noqa: E402
from r2_designs import PHOTO, SPLIT, unseen  # noqa: E402

C.ASSETS = str(HERE / "r2_assets")   # brand assets + the synthetic busy photo

CASES = {
    "unseen": (unseen(), [(1080, 1920), (1080, 1080), (728, 90), (1600, 400), (320, 50), (160, 600)]),
    "photo": (PHOTO, [(1080, 1350), (728, 90), (1080, 1920), (1600, 400), (300, 250)]),
    "split": (SPLIT, [(1200, 628), (1080, 1920), (1080, 1080), (728, 90), (1600, 400)]),
}

if __name__ == "__main__":
    only = set(sys.argv[1:])
    for name, (design, sizes) in CASES.items():
        if only and name not in only:
            continue
        roles, _ = R.infer_roles(design, C.ASSETS)
        print(f"== {name} roles:", {k: v for k, v in roles.items()})
        C.render_design_to_png(design, C.ASSETS, str(HERE / f"r2v2_{name}_source.png"), fonts_dir="brand_kit/fonts")
        for W, H in sizes:
            task = {"source": json.loads(json.dumps(design)), "target_canvas": {"width": W, "height": H}}
            for e in task["source"]["elements"]:
                e["_orig_id"] = e["id"]
            try:
                out, arche = C.compose(task)
            except Exception as ex:  # report, don't hide
                print(f"   {W}x{H}: CRASH {type(ex).__name__}: {ex}")
                continue
            probs = C.check(out, task["source"])
            clean = {"canvas": out["canvas"],
                     "elements": [{k: v for k, v in e.items() if k != "_orig_id"} for e in out["elements"]]}
            tag = f"r2v2_{name}_{W}x{H}"
            (HERE / f"{tag}.json").write_text(json.dumps(clean, indent=1))
            C.render_design_to_png(clean, C.ASSETS, str(HERE / f"{tag}.png"), fonts_dir="brand_kit/fonts")
            vis = [e["id"] for e in out["elements"] if e.get("opacity", 1) > 0]
            print(f"   {W}x{H}: {arche:6s} visible={vis} problems={probs}")
            for line in getattr(C, "_last_log", []): print("        ", line)
