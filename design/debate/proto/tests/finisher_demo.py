"""DESIGNER — before/after evidence for the finisher on existing engine outputs.

    .venv/bin/python -m design.debate.proto.tests.finisher_demo [engine ...]

Writes design/debate/proto/out/finisher_<engine>.png (before | after, official renderer) and
design/debate/proto/out/finisher_counts.txt (rule violations before -> after, per output and per rule).
"""
from __future__ import annotations

import collections
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from design.debate.proto import finisher as F
from design.debate.proto import rules as R
from design.debate.proto.tests.test_finisher import corpus
from renderer.converter.convert import render_design_to_png

OUT = Path(__file__).resolve().parents[1] / "out"
CELL_W, CELL_H = 600, 300


def _render(doc, path):
    render_design_to_png(doc, "brand_kit/assets", str(path))
    return Image.open(path).convert("RGB")


def _fit(im):
    s = min(CELL_W / im.width, CELL_H / im.height, 1.0)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)


def main(engines):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = collections.defaultdict(list)
    lines, per_rule_b, per_rule_a = [], collections.Counter(), collections.Counter()
    tot = collections.Counter()
    tmp = Path(tempfile.mkdtemp())
    for name, src, out in corpus():
        eng = name.split(":")[0]
        if engines and eng not in engines:
            continue
        rep = []
        fin = F.finish(src, out, {}, report=rep)
        vb, va = R.check(src, out, {}), R.check(src, fin, {})
        hb, sb = sum(v.severity == "hard" for v in vb), sum(v.severity == "soft" for v in vb)
        ha, sa = sum(v.severity == "hard" for v in va), sum(v.severity == "soft" for v in va)
        tot[(eng, "hard_b")] += hb
        tot[(eng, "soft_b")] += sb
        tot[(eng, "hard_a")] += ha
        tot[(eng, "soft_a")] += sa
        tot[(eng, "n")] += 1
        tot[(eng, "changed")] += fin != out
        per_rule_b.update(v.rule for v in vb)
        per_rule_a.update(v.rule for v in va)
        applied = sorted({r.split()[1] for r in rep if "applied" in r})
        lines.append(f"{name:45s} hard {hb}->{ha}  soft {sb}->{sa}  passes={','.join(applied)}")
        for v in va:
            lines.append(f"      after: {v}")
        stem = name.replace(":", "_")
        before = _render(out, tmp / f"{stem}_b.png")
        after = _render(fin, tmp / f"{stem}_a.png")
        rows[eng].append((name, f"hard {hb}->{ha} soft {sb}->{sa}", _fit(before), _fit(after)))
    for eng, rs in rows.items():
        h = sum(max(b.height, a.height) + 24 for _, _, b, a in rs) + 10
        sheet = Image.new("RGB", (2 * CELL_W + 30, h), (236, 236, 236))
        d = ImageDraw.Draw(sheet)
        y = 5
        for name, sc, b, a in rs:
            d.text((10, y), f"{name}   BEFORE | AFTER finisher   ({sc})", fill=(0, 0, 0))
            sheet.paste(b, (10, y + 14))
            sheet.paste(a, (20 + CELL_W, y + 14))
            y += max(b.height, a.height) + 24
        sheet.save(OUT / f"finisher_{eng}.png")
    lines.append("\nTOTALS (outputs, changed, hard before->after, soft before->after)")
    for eng in sorted({k[0] for k in tot}):
        lines.append(f"  {eng:10s} n={tot[(eng, 'n')]:3d} changed={tot[(eng, 'changed')]:3d}  "
                     f"hard {tot[(eng, 'hard_b')]}->{tot[(eng, 'hard_a')]}  soft {tot[(eng, 'soft_b')]}->{tot[(eng, 'soft_a')]}")
    lines.append("\nPER RULE (before -> after)")
    for r in sorted(set(per_rule_b) | set(per_rule_a)):
        lines.append(f"  {r:22s} {per_rule_b[r]:3d} -> {per_rule_a[r]:3d}")
    (OUT / "finisher_counts.txt").write_text("\n".join(lines))
    print("\n".join(lines[-40:]))


if __name__ == "__main__":
    main(set(sys.argv[1:]))
