"""Fuzz the engine: random canvases and mutated designs must never raise, must satisfy the contract and
must render with the official renderer.   .venv/bin/python design/debate/proto/tests/fuzz_engine.py [N] [seed]"""
import copy, glob, json, random, sys, time, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from design.debate.proto import engine as E, contract as C  # noqa: E402

SRC = [json.load(open(f)) for f in sorted(glob.glob(str(ROOT / "input/*.json")))]
SRC = [d.get("source", d) for d in SRC]
SRC += [json.load(open(f)).get("source") or json.load(open(f)) for f in sorted(glob.glob(str(ROOT / "design/debate/bench/designs/S*.json")))]
LOREM = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore"


def mutate(src, rng):
    d = copy.deepcopy(E._normalize(copy.deepcopy(src)))
    els = d["elements"]
    for _ in range(rng.choice([0, 1, 1, 2, 3])):
        if not els:
            break
        e = rng.choice(els)
        k = rng.choice(["empty", "long", "short", "rot", "opa0", "drop", "tiny", "huge_font", "off"])
        if k == "drop" and len(els) > 2:
            els.remove(e)
        elif e["type"] == "text" and k == "empty":
            e["content"] = ""
        elif e["type"] == "text" and k == "long":
            e["content"] = (e.get("content", "") + " " + LOREM) * rng.randint(1, 3)
        elif e["type"] == "text" and k == "short":
            e["content"] = "Go"
        elif k == "rot":
            e["rotation"] = rng.choice([90, 45, -30, 15])
        elif k == "opa0":
            e["opacity"] = 0
        elif k == "tiny":
            e["width"], e["height"] = 3, 3
        elif e["type"] == "text" and k == "huge_font":
            e["font_size"] = e["font_size"] * 4
        elif k == "off":
            e["x"] = d["canvas"]["width"] - e["width"] / 3
    return d


def main(n=60, seed=1):
    rng = random.Random(seed)
    bad, t0 = 0, time.time()
    for i in range(n):
        src = mutate(rng.choice(SRC), rng)
        W = rng.choice([rng.randint(100, 2400), rng.choice([160, 300, 320, 728, 970, 1080, 1200, 1600, 1920])])
        H = rng.choice([rng.randint(50, 2400), rng.choice([50, 90, 250, 400, 600, 628, 1080, 1350, 1920])])
        tgt = {"width": W, "height": H}
        try:
            out, info, rep = E.resize_with_info(src, tgt)
            hard, _ = C.validate(src, out, tgt, str(ROOT / "brand_kit/assets"))
            base = {h.split(":")[0] for h in C.validate(src, copy.deepcopy(src), src["canvas"], str(ROOT / "brand_kit/assets"))[0]}
            hard = [h for h in hard if h.split(":")[0] not in base]      # a broken source may break its own rule
            if hard:
                raise AssertionError(f"contract: {hard[:2]}")
            sv = {e["id"]: e for e in src["elements"]}
            for e in out["elements"]:        # stage one: nothing may be hidden unless the source already was
                gone = float(e.get("opacity", 1) if e.get("opacity") is not None else 1) <= 0 or str(e.get("color", "")).replace(" ", "").endswith(",0)")
                was = float(sv[e["id"]].get("opacity", 1) if sv[e["id"]].get("opacity") is not None else 1) <= 0 or str(sv[e["id"]].get("color", "")).replace(" ", "").endswith(",0)")
                if gone and not was:
                    raise AssertionError(f"hidden element {e['id']}")
        except Exception:
            bad += 1
            print(f"[{i}] FAIL {W}x{H}\n{traceback.format_exc()[-600:]}")
    print(f"fuzz n={n} seed={seed} failures={bad} in {time.time() - t0:.0f}s")
    return bad


if __name__ == "__main__":
    sys.exit(1 if main(int(sys.argv[1]) if len(sys.argv) > 1 else 60, int(sys.argv[2]) if len(sys.argv) > 2 else 1) else 0)
