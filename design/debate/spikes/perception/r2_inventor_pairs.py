"""Re-run INVENTOR's 4 'obvious by eye' pairs (round-2 r2_crosscheck.py, where the round-1 critic lost 4/4)
with critic v2.1 + source-relative collisions. Uses INVENTOR's private asset dir (synthetic busy photo)."""
import json, sys, importlib.util
from pathlib import Path
HERE = Path(__file__).parent; ROOT = HERE.parents[3]; sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
INV = HERE.parent / "inventor"; ASSETS2 = INV / "r2_assets"
import critic, roles as R
critic.ASSETS = str(ASSETS2); R.ASSETS = ASSETS2; R._cache.clear()
from r2_critic import score, measure
spec = importlib.util.spec_from_file_location("unseen", INV / "unseen.py"); U = importlib.util.module_from_spec(spec); spec.loader.exec_module(U)
O = INV / "out_r2"
srcs = {"topo_F1": json.loads((O / "topo_F1_source.json").read_text()), "topo_F2": json.loads((O / "topo_F2_source.json").read_text()), "U_": U.design}
pairs = [("F1 1600x400 calm band vs text on trees", "topo_F1_1600x400_calm", "topo_F1_1600x400_v1"),
         ("F2 1600x400 panel host/rider vs floating island", "topo_F2_1600x400", "topo_F2_1600x400_v1"),
         ("U 1080x1920 optimizer vs galley", "U_1080x1920_optimizer", "U_1080x1920_galley"),
         ("U 1600x400 galley vs optimizer", "U_1600x400_galley", "U_1600x400_optimizer")]
agree = 0
for label, a, b in pairs:
    src = next(v for k, v in srcs.items() if a.startswith(k)); rl = R.infer_roles(src); sf = measure(src, rl)
    res = []
    for name in (a, b):
        tot, comp, notes, _ = score(json.loads((O / f"{name}.json").read_text()), src, sf, rl); res.append((tot, notes))
    ok = res[0][0] < res[1][0]; agree += ok
    print(f"[{label}] eye-preferred {res[0][0]:.2f} vs other {res[1][0]:.2f} -> {'AGREES' if ok else 'DISAGREES'}")
    print(f"     eye-pick issues: {res[0][1][:4]}\n     other issues:    {res[1][1][:4]}")
print(f"critic v2.1 agrees with the eye on {agree}/4 (round-1 critic: 0/4)")
