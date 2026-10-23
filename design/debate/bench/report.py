"""Aggregate bench/results -> scoreboard.csv, scoreboard_by_band.csv, SCOREBOARD.md and contact sheets.

    .venv/bin/python design/debate/bench/report.py
"""
from __future__ import annotations

import csv
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
from catalogue import CATALOGUE, SHEET_SIZES, band  # noqa: E402

RES = BENCH / "results"
SHEETS = BENCH / "sheets"
ORDER = ["proto", "proto_zunder", "proto_nevertext", "designer", "optimizer", "optimizer_fixed", "galley",
         "perception", "safe_floor", "baseline"]
GAP_CLASSES = ["hidden_leak", "nonint_font", "rotated_clip", "text_overflow", "text_off_canvas", "placeholder_visible"]
VIS_CLASSES = ["unreadable_text", "small_text", "text_collision", "image_collision", "low_contrast", "busy_under_text",
               "hierarchy_inversion", "group_broken", "orphaned_text", "unaligned", "edge_cramped"]


def load() -> list[dict]:
    rows = []
    for p in sorted(RES.glob("*/*.jsonl")):
        rows += [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    return rows


def pct(v: list[float], q: float) -> float:
    if not v:
        return float("nan")
    v = sorted(v)
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


def summarise(rows: list[dict]) -> dict:
    app = [r for r in rows if r["status"] != "n/a"]
    scores = [float(r.get("score") or 0.0) if r["status"] == "ok" else 0.0 for r in app]
    secs = [r["secs"] for r in app if r.get("secs") is not None]
    cls = Counter()
    for r in app:
        for k, v in (r.get("issues") or {}).items():
            cls[k] += len(v)
    st_ = Counter(r["status"] for r in rows)
    return {"cases": len(rows), "applicable": len(app), "ok": st_["ok"], "hard_fail": st_["hard_fail"],
            "crash": st_["crash"], "timeout": st_["timeout"], "score_error": st_["score_error"], "n/a": st_["n/a"],
            "mean": round(st.mean(scores), 1) if scores else float("nan"),
            "p10": round(pct(scores, 0.10), 1) if scores else float("nan"),
            "median": round(st.median(scores), 1) if scores else float("nan"),
            "min": round(min(scores), 1) if scores else float("nan"),
            "secs_med": round(st.median(secs), 3) if secs else float("nan"),
            "secs_max": round(max(secs), 2) if secs else float("nan"),
            "kept_ink": round(st.mean([r["metrics"]["kept_ink"] for r in app if r.get("metrics", {}).get("kept_ink") is not None]), 3)
            if any(r.get("metrics", {}).get("kept_ink") is not None for r in app) else float("nan"),
            "classes": cls}


def write_csvs(rows: list[dict]) -> dict:
    by_eng = defaultdict(list)
    for r in rows:
        by_eng[r["engine"]].append(r)
    engines = [e for e in ORDER if e in by_eng] + [e for e in by_eng if e not in ORDER]
    summ = {e: summarise(by_eng[e]) for e in engines}
    cols = ["cases", "applicable", "ok", "hard_fail", "crash", "timeout", "n/a", "mean", "p10", "median", "min",
            "secs_med", "secs_max", "kept_ink"]
    with (BENCH / "scoreboard.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["engine"] + cols + GAP_CLASSES + VIS_CLASSES)
        for e in engines:
            s = summ[e]
            w.writerow([e] + [s[c] for c in cols] + [s["classes"][k] for k in GAP_CLASSES + VIS_CLASSES])
    with (BENCH / "scoreboard_by_band.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["engine", "band", "applicable", "mean", "p10", "hard_fail", "crash", "timeout"])
        for e in engines:
            for b in ["strip", "wide", "squareish", "tall"]:
                s = summarise([r for r in by_eng[e] if r["band"] == b])
                w.writerow([e, b, s["applicable"], s["mean"], s["p10"], s["hard_fail"], s["crash"], s["timeout"]])
    with (BENCH / "scoreboard_cases.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["engine", "design", "size", "W", "H", "band", "status", "score", "secs", "n_hidden", "kept_ink",
                    "issues", "hard", "error"])
        for r in rows:
            w.writerow([r["engine"], r["design"], r["size"], r["W"], r["H"], r["band"], r["status"], r.get("score"),
                        r.get("secs"), (r.get("metrics") or {}).get("n_hidden"), (r.get("metrics") or {}).get("kept_ink"),
                        "; ".join(f"{k}x{len(v)}" for k, v in (r.get("issues") or {}).items()),
                        " | ".join((r.get("hard") or [])[:3]), r.get("error", "")])
    return {"engines": engines, "summ": summ, "by_eng": by_eng}


def tile(path: Path, label: str, size: int = 240, status: str = "ok") -> Image.Image:
    t = Image.new("RGB", (size, size + 18), (235, 235, 235))
    if path.exists():
        im = Image.open(path).convert("RGB")
        k = min(size / im.width, size / im.height)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))
        t.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    else:
        ImageDraw.Draw(t).text((8, size // 2), status.upper(), fill=(180, 0, 0))
    ImageDraw.Draw(t).text((3, size + 3), label[:40], fill=(0, 0, 0))
    return t


def engine_sheet(engine: str, rows: list[dict], designs: list[str]) -> Path:
    idx = {(r["design"], r["size"]): r for r in rows}
    size = 200
    cols = SHEET_SIZES
    sheet = Image.new("RGB", (130 + len(cols) * (size + 6), 22 + len(designs) * (size + 24)), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for j, c in enumerate(cols):
        d.text((130 + j * (size + 6) + 4, 4), f"{c} {CATALOGUE[c][0]}x{CATALOGUE[c][1]}", fill=(0, 0, 0))
    for i, des in enumerate(designs):
        y = 22 + i * (size + 24)
        d.text((4, y + size // 2), des[:20], fill=(0, 0, 0))
        for j, c in enumerate(cols):
            r = idx.get((des, c))
            status = r["status"] if r else "missing"
            lab = f"{r.get('score')}" if r and r["status"] == "ok" else status
            sheet.paste(tile(RES / engine / "png" / f"{des}__{c}.png", lab, size, status), (130 + j * (size + 6), y))
    p = SHEETS / f"sheet_{engine}.png"
    sheet.save(p)
    return p


def head_to_head(cases: list[tuple[str, str]], engines: list[str], by_eng: dict) -> Path:
    size = 220
    sheet = Image.new("RGB", (190 + len(engines) * (size + 6), 22 + len(cases) * (size + 24)), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    src_dir = BENCH / "designs"
    d.text((190 - size // 2, 4), "source", fill=(0, 0, 0))
    for j, e in enumerate(engines):
        d.text((190 + j * (size + 6) + 4, 4), e, fill=(0, 0, 0))
    for i, (des, sz) in enumerate(cases):
        y = 22 + i * (size + 24)
        s = tile(src_dir / f"src_{des}.png", f"{des[:14]}->{sz}", 180)
        sheet.paste(s, (4, y))
        for j, e in enumerate(engines):
            r = next((x for x in by_eng.get(e, []) if x["design"] == des and x["size"] == sz), None)
            status = r["status"] if r else "missing"
            lab = f"{r.get('score')}" if r and r["status"] == "ok" else status
            sheet.paste(tile(RES / e / "png" / f"{des}__{sz}.png", lab, size, status), (190 + j * (size + 6), y))
    p = SHEETS / "head_to_head.png"
    sheet.save(p)
    return p


def markdown(info: dict, rows: list[dict]) -> str:
    engines, summ, by_eng = info["engines"], info["summ"], info["by_eng"]
    designs = sorted({r["design"] for r in rows})
    L = ["# CHAMELEON debate bench — SCOREBOARD", "",
         f"{len(designs)} designs (3 official samples + {len(designs) - 3} adversarial synthetic, opaque ids) x "
         f"{len(CATALOGUE)} platform sizes = {len(designs) * len(CATALOGUE)} cases per engine. "
         "Generated by `bench/report.py` from `bench/results/`. Composite = proxy score (0-100), hard failures "
         "(structural / crash / timeout) count as 0. **Read the caveats at the bottom before quoting a number.**", "",
         "## Headline", "",
         "| engine | applicable | ok | hard fail | crash | timeout | mean | p10 | median | min | kept ink | median s | max s |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in engines:
        s = summ[e]
        L.append(f"| {e} | {s['applicable']} | {s['ok']} | {s['hard_fail']} | {s['crash']} | {s['timeout']} | "
                 f"**{s['mean']}** | {s['p10']} | {s['median']} | {s['min']} | {s['kept_ink']} | {s['secs_med']} | {s['secs_max']} |")
    L += ["", "`optimizer_fixed` is the OPTIMIZER spike with one fix applied from outside the file: its glyph-width "
          "caches are keyed by `id(element)`, which Python reuses after garbage collection, so a later element can be "
          "wrapped with another string's widths (`spikes/judge/r2_stale_cache_probe.py`: 109 / 594,883 wrap calls). "
          "All 5 `optimizer` crashes are that bug; the adapter clears the caches per call."]
    rs = BENCH.parent / "spikes" / "judge" / "r2_out" / "rank_stability.json"
    if rs.exists():
        r = json.loads(rs.read_text())
        L += ["", "**Rank stability** (`spikes/judge/r2_rank_stability.py`, 2,000 random re-weightings of every penalty x0.3..x3): "
              "P(rank #1 by mean) over all sizes (perception excluded) = "
              + ", ".join(f"{k} {v:.0%}" for k, v in r["all_sizes"]["p_rank1"].items())
              + "; strip band only = " + ", ".join(f"{k} {v:.0%}" for k, v in r["strip_band"]["p_rank1"].items())
              + ". Differences of a few points between designed engines are inside the weighting noise."]
    L += ["", "`perception_strip` only has a horizontal-strip generator in its spike, so it is run on the 9 "
          "banner-shaped sizes (W/H >= 2.5) and marked n/a elsewhere; compare it on the strip band below.", "",
          "## By shape band (mean / p10 of composite)", "", "| engine | strip | wide | squareish | tall |", "|---|---|---|---|---|"]
    for e in engines:
        cells = []
        for b in ["strip", "wide", "squareish", "tall"]:
            s = summarise([r for r in by_eng[e] if r["band"] == b])
            cells.append("n/a" if not s["applicable"] else f"{s['mean']} / {s['p10']}")
        L.append(f"| {e} | " + " | ".join(cells) + " |")
    L += ["", "## Renderer-gap checks (instances over all applicable cases)", "",
          "| engine | " + " | ".join(GAP_CLASSES) + " |", "|---|" + "---|" * len(GAP_CLASSES)]
    for e in engines:
        L.append(f"| {e} | " + " | ".join(str(summ[e]['classes'][k]) for k in GAP_CLASSES) + " |")
    L += ["", "## Visual-proxy issues (instances)", "", "| engine | " + " | ".join(VIS_CLASSES) + " |",
          "|---|" + "---|" * len(VIS_CLASSES)]
    for e in engines:
        L.append(f"| {e} | " + " | ".join(str(summ[e]['classes'][k]) for k in VIS_CLASSES) + " |")
    L += ["", "## By design (mean composite over applicable sizes)", "", "| design | " + " | ".join(engines) + " |",
          "|---|" + "---|" * len(engines)]
    for des in designs:
        cells = []
        for e in engines:
            s = summarise([r for r in by_eng[e] if r["design"] == des])
            cells.append("n/a" if not s["applicable"] else f"{s['mean']}")
        L.append(f"| {des} | " + " | ".join(cells) + " |")
    leg_p = BENCH / "designs" / "id_legend.json"
    legend = json.loads(leg_p.read_text()) if leg_p.exists() else {}
    fails = [r for r in rows if r["status"] in ("crash", "timeout", "hard_fail", "score_error") and r["engine"] != "baseline"]
    n_base = sum(1 for r in rows if r["engine"] == "baseline" and r["status"] != "ok")
    L += ["", "## Failures (crash / timeout / hard structural)", "",
          f"baseline_stretch: {n_base} hard failures (almost all non-cover image aspect + the bleeding L2 circle) - "
          "not listed. Every other engine's failures:", ""]
    if not fails:
        L.append("none")
    else:
        L += ["| engine | design | size | status | first reason |", "|---|---|---|---|---|"]
        for r in sorted(fails, key=lambda r: (r["engine"], r["design"], r["size"]))[:80]:
            why = str(r.get("error") or "; ".join((r.get("hard") or [])[:2]))
            why = " ".join(why.split())
            for oid, (_d, nm) in legend.items():
                why = why.replace(oid, f"{oid}({nm})")
            L.append(f"| {r['engine']} | {r['design']} | {r['size']} | {r['status']} | {why[:130].replace('|', '/')} |")
        if len(fails) > 80:
            L.append(f"| ... | {len(fails) - 80} more in scoreboard_cases.csv | | | |")
    inv = BENCH.parent / "spikes" / "judge" / "r2_out" / "id_invariance.json"
    if inv.exists():
        L += ["", "## Metamorphic test: id renaming + order permutation (render order unchanged)", "",
              "From `spikes/judge/r2_id_invariance.py` (15 designs x 5 sizes; outputs must be identical up to the renaming).", "",
              "| engine | identical / compared | errors | first difference |", "|---|---|---|---|"]
        for r in json.loads(inv.read_text()):
            ex = next((x for x in r["examples"] if "skipped" not in x), "-")
            L.append(f"| {r['engine']} | {r['identical']}/{r['cases']} | {r['errors']} | {ex[:120].replace('|', '/')} |")
    L += ["", "## How to run", "", "```",
          "# from the repo root",
          ".venv/bin/python design/debate/bench/assets_gen.py      # once: bench/assets (brand copies + 2 test assets)",
          ".venv/bin/python design/debate/bench/designs.py         # once: bench/designs/*.json + source renders",
          ".venv/bin/python design/debate/bench/run.py --engines proto --workers 9 --timeout 180   # resumable",
          ".venv/bin/python design/debate/bench/run.py --module my_pkg.my_engine                   # any resize()",
          ".venv/bin/python design/debate/bench/rescore.py         # after a scorer change (engines not re-run)",
          ".venv/bin/python design/debate/bench/report.py          # CSVs + this file + sheets",
          "```", "",
          "Engines: `baseline, safe_floor, optimizer, optimizer_fixed, galley, designer, perception` and, for Round 4, "
          "`proto` (= `design.debate.proto.engine.resize`, HIDE_MODE alpha), `proto_zunder`, `proto_nevertext`. "
          "Env `BENCH_PROTO_HIDE_MODE`, `BENCH_PROTO_DISJOINT`, `BENCH_PROTO_TOP_K` override proto switches.", ""]
    L += ["", "## Files", "",
          "- `scoreboard.csv` (per engine), `scoreboard_by_band.csv`, `scoreboard_cases.csv` (every case, issues, errors)",
          "- `sheets/sheet_<engine>.png` — 15 designs x 8 representative sizes, composite under each tile",
          "- `sheets/head_to_head.png` — hard cases, all engines side by side with the source",
          "- `results/<engine>/json|png/` — every output JSON + 420px render; `results/<engine>/<design>.jsonl` — raw records",
          "", "## What the proxy scorer can and cannot measure (read this)", "",
          "Measures well (deterministic, renderer-exact): structural hard checks (ids, schema-ish canvas/z/finite, "
          "frozen fields, unrotated bounds, non-cover image aspect, renderer-crash conditions); renderer gaps "
          "(pixel-verified hidden-element leaks, int-font mismatch, letter-spacing/line overflow vs the box, text ink "
          "off canvas, rotated-corner clipping, visible missing-asset placeholder); perceived text size at a 1024px "
          "judge view; glyph-ink collisions excluding group-mates, translucent decor and pairs already overlapping in "
          "the source; contrast and busyness under glyphs relative to the source's own values.", "",
          "Measures crudely (heuristic proxies, weights hand-set, NOT calibrated against a VLM): hierarchy (font-size "
          "order only), alignment (shared ink edges/centres), orphaned small text (source proximity partner hidden), "
          "fill and dead bands relative to the source, faithfulness as source-ink share kept + 'largest text kept'.", "",
          "Cannot measure: taste (balance, rhythm, whether a layout 'looks designed'), semantic correctness of role "
          "choices (e.g. a product caption promoted to subhead), whether a drop was the *right* drop, brand feel, "
          "photo subject cropping under `cover`, and anything a VLM would weigh holistically. Two layouts can both "
          "score 100 and look very different — use the contact sheets. The composite is a regression and triage tool, "
          "not a ranking of design quality. EVAL_SIDE=1024 and the 9px floor are assumptions.", ""]
    return "\n".join(L)


def main() -> None:
    rows = load()
    info = write_csvs(rows)
    SHEETS.mkdir(exist_ok=True)
    designs = sorted({r["design"] for r in rows})
    for e in info["engines"]:
        engine_sheet(e, info["by_eng"][e], designs)
    hard_cases = [("L3_advanced", "leaderboard"), ("L2_core", "li_banner"), ("S02_text_over_photo", "leaderboard"),
                  ("S03_multi_product_grid", "billboard"), ("S04_long_copy_editorial", "x_header"),
                  ("S05_rotated_sticker_bleed", "email_header"), ("S08_missing_and_empty", "large_mobile"),
                  ("S10_story_source", "leaderboard"), ("S12_many_badges", "billboard"),
                  ("S09_banner_source", "ig_story"), ("L3_advanced", "skyscraper"), ("S07_lines_zties_spacing", "ig_story")]
    head_to_head(hard_cases, info["engines"], info["by_eng"])
    (BENCH / "SCOREBOARD.md").write_text(markdown(info, rows))
    print((BENCH / "SCOREBOARD.md").read_text()[:4000])


if __name__ == "__main__":
    main()
