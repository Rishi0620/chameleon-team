"""Round-2: TASTE AS MEASURABLE RULES. Runs on ANY engine's output JSON (+ its source), no engine code.

Each rule is something a senior designer flags at a glance; each is computed from exact renderer
metrics (wrap/skia) and asset ink. Run from repo root:
    .venv/bin/python design/debate/spikes/designer/r2_rules.py
"""
from __future__ import annotations

import glob
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
RELATIVE = list(sys.argv[1:])
sys.argv = sys.argv[:1]
import compose as C  # noqa: E402  (measurement helpers only)
from roles import infer_roles  # noqa: E402

ROOT = HERE.parents[3]
SAMPLES = {"L1": "level1_warmup", "L2": "level2_core", "L3": "level3_advanced"}


def alpha_of(c):
    m = re.match(r"rgba\([^)]*,\s*([\d.]+)\s*\)", c or "")
    return float(m.group(1)) if m else 1.0


def visible(e):
    if e.get("opacity", 1) <= 0.01:
        return False
    if e["type"] == "text" and alpha_of(e.get("color")) <= 0.01:
        return False
    return True


def text_lines(e):
    fam, w, s = C._fontargs(e)
    widths = C.char_widths(C.FM, fam, w, s, int(e["font_size"]), e["content"])
    wrapped = C.wrap_text(e["content"], widths, e["width"])
    out, start = [], 0
    for i, ch in enumerate(wrapped + "\n"):
        if ch == "\n":
            out.append((wrapped[start:i], sum(widths[start:i])))
            start = i + 1
    return out


def ink(e):
    if e["type"] == "text":
        lines = text_lines(e)
        asc, cap, desc = C.metrics(e)
        fs, lh = int(e["font_size"]), e.get("line_height", 1.2)
        w = max(lw for _, lw in lines)
        al = e.get("text_align", "left")
        x0 = {"left": e["x"], "center": e["x"] + (e["width"] - w) / 2, "right": e["x"] + e["width"] - w}.get(al, e["x"])
        top = e["y"] + (asc - cap) * fs
        return (x0, top, x0 + w, top + (len(lines) - 1) * lh * fs + cap * fs + 0.22 * fs)
    if e["type"] == "image":
        fr = C.optics(e)
        return (e["x"] + fr[0] * e["width"], e["y"] + fr[1] * e["height"],
                e["x"] + fr[2] * e["width"], e["y"] + fr[3] * e["height"])
    return (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"])


def area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def inter(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def judge_px(fs, W, H):
    return fs * min(1.0, 1024 / max(W, H))


def check(out, src):
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    short = min(W, H)
    roles, meta = infer_roles(src, C.ASSETS)
    els = {e["id"]: e for e in out["elements"]}
    vis = {i: e for i, e in els.items() if visible(e)}
    R = {i: roles.get(i, "?") for i in els}
    content = {i: e for i, e in vis.items() if R[i] not in ("background", "decoration", "broken")}
    inks = {i: ink(e) for i, e in content.items()}
    flags = []

    # R0 P0 presence: the message, the brand and the action must survive every format
    for need in ("headline", "logo", "cta_bg", "cta_text"):
        have = [i for i in els if R[i] == need]
        if have and not any(i in vis for i in have):
            flags.append(f"R0 missing-P0: {need} hidden")
    for i, e in vis.items():
        x0, y0, x1, y1 = e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]
        if x0 < -0.5 or y0 < -0.5 or x1 > W + 0.5 or y1 > H + 0.5:
            flags.append(f"R0 off-canvas: {i}")

    # R1 edge clearance (ink, not box)
    unit = max(6.0, 0.04 * short)
    for i, r in inks.items():
        cl = min(r[0], r[1], W - r[2], H - r[3])
        if cl < unit - 0.5:
            flags.append(f"R1 edge: {i} ink {cl:.0f}px from edge (< {unit:.0f})")
    # R2 optical side-margin balance (wide formats)
    if W / H >= 2 and inks:
        lm = min(r[0] for r in inks.values())
        rm = W - max(r[2] for r in inks.values())
        if max(lm, rm) > 2 * max(1.0, min(lm, rm)) and abs(lm - rm) > 12:
            flags.append(f"R2 margins: optical left {lm:.0f}px vs right {rm:.0f}px")
    # R3 CTA label legibility
    for i, e in content.items():
        if R[i] in ("cta_label",) and judge_px(int(e["font_size"]), W, H) < 12:
            flags.append(f"R3 cta-label: {int(e['font_size'])}px (< 12 judge-px)")
    # R4 strip headline line count / R5 rag: widows & one-word lines
    for i, e in content.items():
        if e["type"] != "text" or R[i] not in ("headline", "subhead", "cta_text"):
            continue
        lines = text_lines(e)
        n = len(lines)
        if R[i] == "headline" and H <= 120 and n > 2:
            flags.append(f"R4 strip-headline: {n} lines at {int(e['font_size'])}px")
        if n >= 2:
            wmax = max(lw for _, lw in lines)
            words = len(e["content"].split())
            if lines[-1][1] < 0.35 * wmax and words >= 3:
                flags.append(f"R5 widow: {i} last line '{lines[-1][0].strip()}' = {lines[-1][1] / wmax:.0%} of measure")
            singles = [t.strip() for t, _ in lines if len(t.split()) == 1 and words >= 3]
            if singles and R[i] == "headline":
                flags.append(f"R5 one-word line(s) in headline: {singles}")
    # R6 logo dominance
    head = next((i for i in content if R[i] == "headline"), None)
    logo = next((i for i in content if R[i] == "logo"), None)
    if head and logo:
        ratio = area(inks[logo]) / max(1, area(inks[head]))
        if ratio > 0.8:
            flags.append(f"R6 logo-dominance: logo ink = {ratio:.1f}x headline ink")
    # R7 hierarchy
    if head:
        hf = int(content[head]["font_size"])
        for i, e in content.items():
            if e["type"] == "text" and i != head and int(e["font_size"]) * 1.2 > hf:
                flags.append(f"R7 hierarchy: {i} {int(e['font_size'])}px vs headline {hf}px")
    # R8 empty band along the long axis
    if inks:
        if H >= W:
            spans = sorted((r[1], r[3]) for r in inks.values())
            edges, cur = [0.0], 0.0
            gaps = []
            last = 0.0
            for a, b in spans:
                if a > last:
                    gaps.append(a - last)
                last = max(last, b)
            gaps.append(H - last)
            g = max(gaps) / H
            if g > 0.30:
                flags.append(f"R8 empty-band: {g:.0%} of height has no content")
        else:
            spans = sorted((r[0], r[2]) for r in inks.values())
            gaps, last = [], 0.0
            for a, b in spans:
                if a > last:
                    gaps.append(a - last)
                last = max(last, b)
            gaps.append(W - last)
            g = max(gaps) / W
            if g > 0.25:
                flags.append(f"R8 empty-band: {g:.0%} of width has no content")
    # R9 island: content bbox coverage
    if inks:
        U = (min(r[0] for r in inks.values()), min(r[1] for r in inks.values()),
             max(r[2] for r in inks.values()), max(r[3] for r in inks.values()))
        cov = area(U) / (W * H)
        if cov < 0.35:
            flags.append(f"R9 island: content occupies {cov:.0%} of canvas")
    # R10 smudges: visible text below 9 judge-px
    for i, e in content.items():
        if e["type"] == "text" and judge_px(int(e["font_size"]), W, H) < 9:
            flags.append(f"R10 smudge: {i} at {int(e['font_size'])}px")
    # R11 translucent decoration crossing CTA / text ink
    for d, de in vis.items():
        if R[d] != "decoration":
            continue
        dr = ink(de)
        for i, r in inks.items():
            if (R[i] in ("cta_bg", "headline", "subhead", "logo")) and inter(dr, r) > 0.15 * area(r):
                flags.append(f"R11 deco-crossing: {d} covers {inter(dr, r) / area(r):.0%} of {i}")
    # R12 rhythm (tall formats): consecutive vertical gaps between stacked content units
    if H >= W and len(inks) >= 4:
        units = sorted(inks.values(), key=lambda r: r[1])
        merged = []
        for r in units:   # merge units sharing a row (e.g. a chip row) or overlapping vertically
            if merged and r[1] < merged[-1][3] - 2:
                q = merged[-1]
                merged[-1] = (min(q[0], r[0]), q[1], max(q[2], r[2]), max(q[3], r[3]))
            else:
                merged.append(r)
        gaps = [b[1] - a[3] for a, b in zip(merged, merged[1:])]
        gaps = [g for g in gaps if g > 0]
        if len(gaps) >= 3 and max(gaps) > 4 * max(min(gaps), 0.01 * H):
            flags.append(f"R12 rhythm: stack gaps {min(gaps):.0f}..{max(gaps):.0f}px (ratio {max(gaps) / max(min(gaps), 1):.1f})")
    # R14 presence (tall formats): a short headline should own the measure
    if head and H >= W and len(content[head]["content"].split()) <= 5:
        hw = inks[head][2] - inks[head][0]
        if hw < 0.5 * (W - 2 * unit):
            flags.append(f"R14 timid-headline: short headline spans {hw / (W - 2 * unit):.0%} of the measure")
    # R13 strip vertical padding of text
    if H <= 120:
        for i, e in content.items():
            if e["type"] == "text" and R[i] == "headline":
                r = inks[i]
                pad = min(r[1], H - r[3])
                if pad < 0.12 * H:
                    flags.append(f"R13 strip-padding: headline ink {pad:.0f}px from top/bottom (< {0.12 * H:.0f})")
    return flags


def collect():
    runs = []
    for p in sorted(glob.glob(str(ROOT / "design/debate/spikes/optimizer/out/L*_*.json"))):
        runs.append(("optimizer", p))
    for p in sorted(glob.glob(str(ROOT / "design/debate/spikes/inventor/out/L*_*.json"))):
        runs.append(("inventor", p))
    for p in sorted(glob.glob(str(ROOT / "design/debate/spikes/perception/out/s4b_level*_best.json"))):
        runs.append(("perception", p))
    for p in sorted(glob.glob(str(ROOT / "design/debate/spikes/judge/out/mock_l3_leaderboard.json"))):
        runs.append(("judge", p))
    for p in sorted(glob.glob(str(HERE / "out_level*.json"))):
        runs.append(("designer", p))
    return runs


def source_for(path):
    name = Path(path).name
    for k, v in SAMPLES.items():
        if name.startswith(k + "_") or v in name or f"level{k[1]}" in name or ("l3" in name and k == "L3"):
            return json.load(open(ROOT / f"input/chameleon_sample_{v}.json"))["source"]
    return None


def _pct(f):
    m = re.search(r"(\d+)%", f)
    return int(m.group(1)) / 100 if m else None


def source_relative(flags, src_flags):
    """The source is a solved instance of the designer's objective: a 'defect' the source itself
    exhibits is a style, not a defect. Keep an R8/R9/R11 flag only if the output is >5pts worse."""
    keep = []
    for f in flags:
        cls = f.split(":")[0]
        if cls.startswith(("R8", "R9", "R11")):
            ref = [_pct(g) for g in src_flags if g.split(":")[0] == cls]
            v = _pct(f)
            if ref and v is not None:
                worse = (v > max(ref) + 0.05) if not cls.startswith("R9") else (v < min(ref) - 0.05)
                if not worse:
                    continue
        keep.append(f)
    return keep


if __name__ == "__main__":
    import collections
    tally = collections.Counter()
    per_agent = collections.defaultdict(lambda: [0, 0])
    lines = []
    for agent, p in collect():
        src = source_for(p)
        out = json.load(open(p))
        if "canvas" not in out:
            out = out.get("design") or out.get("output") or out
        sid = [e["id"] for e in src["elements"]]
        if {e["id"] for e in out["elements"]} != set(sid) and len(out["elements"]) == len(sid):
            for e, i in zip(out["elements"], sid):   # anonymised run: same order as source
                e["id"] = i
        try:
            flags = check(out, src)
            if "--relative" in RELATIVE:
                flags = source_relative(flags, check(json.loads(json.dumps(src)), src))
        except Exception as ex:
            flags = [f"ERR {type(ex).__name__}: {ex}"]
        tag = f"{agent}:{Path(p).stem}"
        per_agent[agent][0] += 1
        per_agent[agent][1] += len(flags)
        for f in flags:
            tally[(agent, f.split(":")[0])] += 1
        lines.append(f"{tag:46s} {len(flags):2d}  " + " | ".join(flags))
    report = "\n".join(lines)
    (HERE / ("r2_rules_report_relative.txt" if RELATIVE else "r2_rules_report.txt")).write_text(report)
    print(report)
    print("\nper agent (outputs, flags, flags/output):")
    for a, (n, f) in per_agent.items():
        print(f"  {a:10s} {n:3d} {f:4d} {f / n:5.2f}")
    print("\nrule x agent:")
    for (a, r), n in sorted(tally.items()):
        print(f"  {a:10s} {r:22s} {n}")
