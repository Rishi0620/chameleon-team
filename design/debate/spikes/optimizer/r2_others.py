"""Round-2 evidence for the critiques: run DESIGNER's compose.py (archetype engine) on the new
opaque-id designs S (split colour-block) and B (scrim card on a busy photo) plus inventor's U,
score with the same neutral critic as r2_h2h.py, and tile DESIGNER vs MERGED.
"""
from __future__ import annotations

import copy
import io
import contextlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "design/debate/spikes/designer"))
import r2_merged as M  # noqa: E402

H = M.H
import compose as DES  # noqa: E402

DES.ASSETS = str(H.KIT)


def main():
    table, log = [], []
    for name in ("S", "B", "U"):
        src = H.DESIGNS[name]
        lum, edges = H.underlay(src, f"{name}_src")
        sst = H.text_stats(src, lum, edges)
        rows = []
        for Wc, Hc in H.SIZES:
            task = {"source": copy.deepcopy(src), "target_canvas": {"width": Wc, "height": Hc}}
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    out, arche = DES.compose(task)
                out = {"canvas": out["canvas"], "elements": [{k: v for k, v in e.items() if k != "_orig_id"} for e in out["elements"]]}
                png = H.OUT / f"{name}_{Wc}x{Hc}_DES.png"
                (H.OUT / f"{name}_{Wc}x{Hc}_DES.json").write_text(json.dumps(out, indent=1))
                H.render_design_to_png(out, str(H.KIT), str(png))
                c = H.critique(out, src, sst, f"{name}_{Wc}x{Hc}_DES")
            except Exception as ex:
                arche, c, png = "-", {"crash": f"{type(ex).__name__}: {ex}"}, None
            table.append(dict(design=name, size=f"{Wc}x{Hc}", engine="DES", **c))
            line = f"{name} {Wc}x{Hc} DES [{arche}] {c}"
            print(line, flush=True)
            log.append(line)
            rows.append((f"{name} {Wc}x{Hc}", png, H.OUT / f"{name}_{Wc}x{Hc}_MRG.png"))
        H.sheet(rows, H.OUT / f"designer_vs_merged_{name}.png", labels=("DESIGNER (archetypes)", "MERGED prototype"))
    summ = H.summarize(table)
    print(summ)
    (H.OUT / "designer_log.txt").write_text("\n".join(log) + "\n\n" + summ + "\n")
    for p in H.OUT.glob("_under_*.png"):
        p.unlink()


if __name__ == "__main__":
    main()
