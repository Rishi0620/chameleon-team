"""Round-2 spike: fixed-point test  resize(src, src.canvas) ~= src  for every engine variant.
This is the 'source is the argmin at its own canvas' condition from r2_inverse.py, checked on the
engines' actual outputs. Metric (same as GALLEY's): mean / max centre drift of visible elements in %
of the canvas diagonal, mean |font change| of visible text, and how many source-visible ids got hidden.
Variants: GALLEY; OPTIMIZER with z_cap = 1.5*z_ref (round 1) and 1.0*z_ref (GALLEY's s_cap);
MERGED prototype with both caps.
"""
from __future__ import annotations

import io
import contextlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import r2_merged as M  # noqa: E402

H, OPT = M.H, M.OPT


def drift(src, out):
    Wc, Hc = src["canvas"]["width"], src["canvas"]["height"]
    diag = math.hypot(Wc, Hc)
    o = {e["id"]: e for e in out["elements"]}
    dc, ds, hid = [], [], 0
    for e in src["elements"]:
        f = o[e["id"]]
        if not H.visible(f):
            hid += H.visible(e)
            continue
        dc.append(math.hypot(e["x"] + e["width"] / 2 - f["x"] - f["width"] / 2,
                             e["y"] + e["height"] / 2 - f["y"] - f["height"] / 2) / diag)
        if e["type"] == "text":
            ds.append(abs(f["font_size"] / e["font_size"] - 1))
    return 100 * sum(dc) / len(dc), 100 * max(dc), 100 * (sum(ds) / len(ds) if ds else 0), hid


def main():
    rows = ["design  variant              mean_drift%  max_drift%  mean_font_change%  hidden"]
    for name, src in H.DESIGNS.items():
        Wc, Hc = src["canvas"]["width"], src["canvas"]["height"]
        variants = [("GALLEY", lambda: H.run_galley(src, Wc, Hc)[0])]
        for mult in (1.5, 1.0):
            def opt(mult=mult):
                OPT.Z_CAP_MULT = mult
                return OPT.solve(src, Wc, Hc)[0]

            def mrg(mult=mult):
                OPT.Z_CAP_MULT = mult
                return M.solve_merged(src, Wc, Hc)[0]
            variants += [(f"OPT cap={mult}", opt), (f"MERGED cap={mult}", mrg)]
        for label, fn in variants:
            with contextlib.redirect_stdout(io.StringIO()):
                out = fn()
            md, xd, fc, hid = drift(src, out)
            rows.append(f"{name:6s}  {label:18s} {md:11.1f} {xd:11.1f} {fc:18.1f} {hid:7d}")
            print(rows[-1], flush=True)
    OPT.Z_CAP_MULT = 1.5
    (H.OUT / "fixedpoint_log.txt").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    main()
