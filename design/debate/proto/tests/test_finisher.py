"""DESIGNER — unit-style checks for finisher.py and rules.py.

Runs with plain Python (no pytest needed), from the repo root:
    .venv/bin/python -m design.debate.proto.tests.test_finisher
pytest-compatible as well (test_* functions, plain asserts).
"""
from __future__ import annotations

import copy
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from design.debate.proto import finisher as F  # noqa: E402
from design.debate.proto import rules as R  # noqa: E402

SAMPLES = {"L1": "level1_warmup", "L2": "level2_core", "L3": "level3_advanced"}


def _src(level):
    return json.load(open(ROOT / f"input/chameleon_sample_{SAMPLES[level]}.json"))["source"]


def corpus():
    """(name, source, output) for existing engine outputs: designer R1, optimizer, inventor."""
    items = []
    for p in sorted(glob.glob(str(ROOT / "design/debate/spikes/optimizer/out/L*_*.json"))):
        items.append(("optimizer:" + Path(p).stem, _src(Path(p).stem[:2]), json.load(open(p))))
    for p in sorted(glob.glob(str(ROOT / "design/debate/spikes/inventor/out/L*_*.json"))):
        items.append(("inventor:" + Path(p).stem, _src(Path(p).stem[:2]), json.load(open(p))))
    for p in sorted(glob.glob(str(ROOT / "design/debate/spikes/designer/out_level*.json"))):
        stem = Path(p).stem.replace("out_", "")
        lv = next(k for k, v in SAMPLES.items() if stem.startswith(v))
        src, out = _src(lv), json.load(open(p))
        for e, s in zip(out["elements"], src["elements"]):   # R1 runs were id-anonymised, same order
            e["id"] = s["id"]
        items.append(("designer:" + stem, src, out))
    return items


def _score(src, out):
    vs = R.check(src, out, {})
    return sum(v.severity == "hard" for v in vs), sum(v.severity == "soft" for v in vs)


# ---------------------------------------------------------------------------------------------- tests

def test_contract_and_monotone_on_corpus():
    """On every existing engine output: contract holds, rule score never gets worse, inputs untouched."""
    for name, src, out in corpus():
        before = copy.deepcopy(out)
        src_before = copy.deepcopy(src)
        fin = F.finish(src, out, {})
        assert out == before and src == src_before, f"{name}: finish mutated its inputs"
        ctx = F.Ctx(src, fin, {})
        probs = [p for p in F.contract_problems(ctx, out, fin) if "font_size" not in p]
        assert not probs, f"{name}: contract broken {probs}"
        assert all(isinstance(e["font_size"], int) for e in fin["elements"] if e["type"] == "text"), name
        assert _score(src, fin) <= _score(src, out), f"{name}: rules got worse {_score(src, out)} -> {_score(src, fin)}"


def test_idempotent():
    for name, src, out in corpus()[::3]:
        a = F.finish(src, out, {})
        b = F.finish(src, a, {})
        assert a == b, f"{name}: not idempotent"


def test_never_raises_returns_input():
    src = _src("L2")
    bad = {"canvas": {"width": 728, "height": 90}, "elements": [{"id": "x", "type": "text"}]}
    assert F.finish(src, bad, {}) is bad                     # broken input -> returned unchanged
    assert F.finish(src, {"canvas": {}}, None) == {"canvas": {}}


def test_hidden_elements_untouched():
    src = _src("L3")
    out = json.load(open(ROOT / "design/debate/spikes/inventor/out/L3_728x90.json"))
    fin = F.finish(src, out, {})
    for a, b in zip(out["elements"], fin["elements"]):
        if not F.visible(a):
            assert a == b, f"hidden element {a['id']} was modified"


def test_balanced_wrap_and_widow():
    src = _src("L3")
    W, H = 1080, 1080
    head = copy.deepcopy(next(e for e in src["elements"] if e["id"] == "headline"))
    head.update(x=40, y=300, width=1000, font_size=40)     # 1000px measure -> ragged greedy wrap
    doc = {"canvas": {"width": W, "height": H}, "elements": [
        dict(next(e for e in src["elements"] if e["id"] == "bg"), x=0, y=0, width=W, height=H), head]}
    s2 = {"canvas": src["canvas"], "elements": [next(e for e in src["elements"] if e["id"] == "bg"),
                                               next(e for e in src["elements"] if e["id"] == "headline")]}
    fin = F.finish(s2, doc, {})
    h2 = next(e for e in fin["elements"] if e["id"] == "headline")
    lines0 = F.wrap_lines(head, 40, head["width"])
    lines1 = F.wrap_lines(h2, h2["font_size"], h2["width"])
    w0 = max(w for _, w in lines0)
    assert len(lines1) <= len(lines0)
    assert lines1[-1][1] / max(w for _, w in lines1) >= lines0[-1][1] / w0 - 1e-6
    assert h2["width"] <= head["width"]


def test_pill_caps_optically_centred_and_cta_floor():
    src = _src("L3")
    out = json.load(open(ROOT / "design/debate/spikes/inventor/out/L3_728x90.json"))
    fin = F.finish(src, out, {})
    d = {e["id"]: e for e in fin["elements"]}
    s, t = d["cta_bg"], d["cta_label"]
    asc, cap, desc = F.vmetrics(t)
    cap_mid = t["y"] + (asc - cap) * t["font_size"] + cap * t["font_size"] / 2
    assert abs(cap_mid - (s["y"] + s["height"] / 2)) < 0.6, "caps not optically centred in the pill"
    assert t["font_size"] >= 12, "CTA label below 12 judge-px"
    ink = F.text_ink(t)
    assert ink[0] >= s["x"] - 0.5 and ink[2] <= s["x"] + s["width"] + 0.5, "label spills out of the pill"


def test_rules_source_relative_and_api():
    for lv in SAMPLES:
        src = _src(lv)
        vs = R.check(src, src, {})
        rel = [v for v in vs if v.rule in ("R8_empty_band", "R9_island", "R11_deco_crossing", "R6_logo_dominance",
                                            "R7_hierarchy", "R1_edge")]
        assert not rel, f"{lv}: the source flags itself on a relative rule: {rel}"
        for v in vs:
            assert v.severity in ("hard", "soft") and isinstance(v.ids, list) and v.rule
    # broken baseline is caught
    base = json.load(open(ROOT / "output/chameleon_sample_level3_advanced_output.json"))
    hard = [v for v in R.check(_src("L3"), base, {}) if v.severity == "hard"]
    assert len(hard) >= 3, hard


def test_uses_info_roles():
    src = _src("L1")
    out = json.load(open(ROOT / "design/debate/spikes/optimizer/out/L1_728x90.json"))
    info = {"roles": {"bg": "background", "logo": "logo", "headline": "headline", "cta": "cta_label"}}
    vs = R.check(src, out, info)
    assert all(v.rule != "RULES_ERROR" for v in vs)


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    fails = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as ex:
            fails += 1
            print(f"FAIL {t.__name__}: {ex}")
    print(f"{len(TESTS) - fails}/{len(TESTS)} passed")
    sys.exit(1 if fails else 0)
