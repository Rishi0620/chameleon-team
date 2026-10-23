"""DESIGNER — rules: taste as measurable, SOURCE-RELATIVE checks.

    check(source, output, info) -> list[Violation]

A Violation has `.rule`, `.severity` ("hard" | "soft"), `.ids`, `.detail`. Everything is measured with
the renderer's own metrics (wrap_text/char_widths at int font sizes, skia ascent/cap height) and asset
alpha bboxes, so "ink" here is what the PNG will show. Thresholds that a source design can itself
violate (empty bands, coverage, decoration overlap, logo weight, CTA rank, edge clearance) are judged
RELATIVE to the source: a property the designer chose is a style, not a defect.

Roles come from info["roles"] (OPTIMIZER's decompiler) when present; fallback: finisher.infer_roles.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

try:
    from . import finisher as F
except ImportError:  # pragma: no cover - script mode
    import finisher as F  # type: ignore


@dataclass
class Violation:
    rule: str
    severity: str
    ids: list = field(default_factory=list)
    detail: str = ""

    def as_dict(self):
        return {"rule": self.rule, "severity": self.severity, "ids": list(self.ids), "detail": self.detail}

    def __str__(self):
        return f"[{self.severity}] {self.rule} {self.ids}: {self.detail}"


FLOOR_JUDGE = {"headline": 14, "subhead": 11, "body": 11, "cta_label": 12, "badge_label": 9, "legal": 9}

# ============================================================================ measurements


class _View:
    """One design (source or output) seen through the canonical roles."""

    def __init__(self, ctx, doc):
        self.ctx, self.doc = ctx, doc
        self.W, self.H = doc["canvas"]["width"], doc["canvas"]["height"]
        self.els = {e["id"]: e for e in doc["elements"]}
        self.R = ctx.roles
        self.vis = {i: e for i, e in self.els.items() if F.visible(e)}
        self.content = {i: e for i, e in self.vis.items()
                        if self.R.get(i) not in ("background", "decoration", "panel", "unknown")}
        self.ink = {}
        for i, e in self.content.items():
            try:
                self.ink[i] = F.ink(e, ctx.assets)
            except Exception:
                self.ink[i] = F.box(e)

    def first(self, role):
        return next((i for i in self.content if self.R.get(i) == role), None)

    def empty_band(self):
        if not self.ink:
            return 1.0
        if self.H >= self.W:
            spans, L = sorted((r[1], r[3]) for r in self.ink.values()), self.H
        else:
            spans, L = sorted((r[0], r[2]) for r in self.ink.values()), self.W
        gaps, last = [], 0.0
        for a, b in spans:
            if a > last:
                gaps.append(a - last)
            last = max(last, b)
        gaps.append(L - last)
        return max(gaps) / L

    def coverage(self):
        if not self.ink:
            return 0.0
        rs = list(self.ink.values())
        U = (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))
        return F.area(U) / (self.W * self.H)

    def deco_overlap(self):
        """{(deco_id, protected_id): fraction of protected ink covered}"""
        out = {}
        for d, de in self.vis.items():
            if self.R.get(d) != "decoration":
                continue
            for i, r in self.ink.items():
                if self.R.get(i) in ("cta_shape", "headline", "subhead", "logo", "cta_label"):
                    out[(d, i)] = F.inter(F.box(de), r) / max(1.0, F.area(r))
        return out

    def logo_ratio(self):
        h, lg = self.first("headline"), self.first("logo")
        if not h or not lg:
            return None
        return F.area(self.ink[lg]) / max(1.0, F.text_ink_area(self.els[h]))

    def cap_px(self, i):
        e = self.els[i]
        return int(e["font_size"]) * F.vmetrics(e)[1]

    def rank_ratio(self):
        """headline cap-height / largest other visible text cap-height."""
        h = self.first("headline")
        if not h:
            return None
        others = [self.cap_px(i) for i, e in self.content.items() if e["type"] == "text" and i != h
                  and self.R.get(i) != "legal"]
        return self.cap_px(h) / max(others) if others else None

    def edge_clearance(self):
        return min((min(r[0], r[1], self.W - r[2], self.H - r[3]) for r in self.ink.values()), default=1e9)


def _lines(e):
    return F.wrap_lines(e, int(e["font_size"]), e["width"])

# ============================================================================ check


def check(source, output, info=None):
    try:
        return _check(source, output, info or {})
    except Exception as ex:  # a checker must never take the engine down
        return [Violation("RULES_ERROR", "soft", [], f"{type(ex).__name__}: {ex}")]


def _check(source, output, info):
    ctx = F.Ctx(source, output, info)
    out, src = _View(ctx, output), _View(ctx, source)
    W, H = out.W, out.H
    js = F.judge_scale(W, H)
    V = []
    add = lambda r, s, ids, d: V.append(Violation(r, s, list(ids), d))  # noqa: E731

    # ---- contract-level (hard) -----------------------------------------------------------------
    sids = [e["id"] for e in source["elements"]]
    oids = [e["id"] for e in output["elements"]]
    if sorted(sids) != sorted(oids):
        add("C0_ids", "hard", sorted(set(sids) ^ set(oids)), "ids added/removed")
    for i, e in out.els.items():
        b = F.box(e)
        if b[0] < -0.5 or b[1] < -0.5 or b[2] > W + 0.5 or b[3] > H + 0.5:
            add("C1_off_canvas", "hard", [i], f"box {tuple(round(v) for v in b)}")
        if e["type"] == "text":
            if not isinstance(e.get("font_size"), int) and float(e.get("font_size", 1)) != int(e.get("font_size", 1)):
                add("C2_int_font", "hard", [i], f"font_size {e.get('font_size')} drawn as int")
            if e["width"] < 1 or e["height"] < 1:
                add("C3_text_wh", "hard", [i], "text width/height < 1 crashes the renderer")
        if e["type"] == "image" and e.get("fit", "contain") != "cover" and i in ctx.byid_src:
            s = ctx.byid_src[i]
            if s["height"] > 0 and e["height"] > 0 and abs((e["width"] / e["height"]) / (s["width"] / s["height"]) - 1) > 0.05:
                add("C4_aspect", "hard", [i], "image aspect drift > 5%")
        if i in out.vis and abs(e.get("rotation", 0) or 0) > 0.01:
            r = F.rot_aabb(e)
            if r[0] < -0.5 or r[1] < -0.5 or r[2] > W + 0.5 or r[3] > H + 0.5:
                add("C5_rot_clip", "hard", [i], "rotated corners clipped by the canvas")
        if i in out.vis and e["type"] == "image" and F.asset_bbox(ctx.assets, e.get("asset_id")) is None:
            add("C6_placeholder", "hard", [i], "missing asset renders a grey placeholder")

    # ---- R0: P0 presence -------------------------------------------------------------------------
    brand_reminder = info.get("mode") == "brand_reminder"
    for role in ("headline", "logo"):
        have = [i for i in out.els if ctx.roles.get(i) == role]
        if role == "headline" and brand_reminder:
            continue
        if have and not any(i in out.vis for i in have):
            add("R0_missing_P0", "hard", have, f"{role} hidden")
    cta = [i for i in out.els if ctx.roles.get(i) in ("cta_shape", "cta_label")]
    if cta and not any(i in out.vis for i in cta):
        add("R0_missing_P0", "hard", cta, "CTA hidden")

    # ---- R15 new box overlaps between flow elements; R16 label spill -----------------------------
    src_pairs = F.overlap_pairs(ctx, source)
    for a, b in sorted(F.overlap_pairs(ctx, output) - src_pairs):
        add("R15_box_overlap", "hard", [a, b], "JSON boxes of two flow elements overlap")
    for host, riders in ctx.containers.items():
        hs = out.els.get(host)
        if hs is None or hs["id"] not in out.vis or hs["type"] != "shape" or abs(hs.get("rotation", 0) or 0) > 0.01:
            continue
        hb = F.box(hs)
        for r in riders:
            if r in out.ink and out.els[r]["type"] == "text":
                ri = out.ink[r]
                spill = max(hb[0] - ri[0], ri[2] - hb[2], hb[1] - ri[1], ri[3] - hb[3])
                if spill > 1.0:
                    add("R16_label_spill", "hard", [r, host], f"label ink escapes its container by {spill:.0f}px")

    # ---- R1 edge clearance (relative) / R2 optical margins --------------------------------------
    unit = max(6.0, 0.04 * min(W, H))
    src_cl = src.edge_clearance() / max(1.0, 0.04 * min(src.W, src.H))
    for i, r in out.ink.items():
        cl = min(r[0], r[1], W - r[2], H - r[3])
        if cl < min(unit, unit * src_cl) - 0.5:
            add("R1_edge", "soft", [i], f"ink {cl:.0f}px from the canvas edge")
    if W / H >= 2 and out.ink:
        lm = min(r[0] for r in out.ink.values())
        rm = W - max(r[2] for r in out.ink.values())
        if max(lm, rm) > 2 * max(1.0, min(lm, rm)) and abs(lm - rm) > 12:
            add("R2_margins", "soft", [], f"optical left {lm:.0f}px vs right {rm:.0f}px")

    # ---- R3 CTA label / R10 smudges ---------------------------------------------------------------
    for i, e in out.content.items():
        if e["type"] != "text":
            continue
        jp = int(e["font_size"]) * js
        if ctx.roles.get(i) == "cta_label" and jp < 12:
            add("R3_cta_label", "hard", [i], f"{int(e['font_size'])}px = {jp:.1f} judge-px < 12")
        if jp < 9:
            add("R10_smudge", "hard", [i], f"visible text at {jp:.1f} judge-px")

    # ---- R4 strip headline, R5 rag ----------------------------------------------------------------
    for i, e in out.content.items():
        if e["type"] != "text" or ctx.roles.get(i) not in ("headline", "subhead"):
            continue
        lines = _lines(e)
        n, words = len(lines), len(e.get("content", "").split())
        if ctx.roles.get(i) == "headline" and H <= 120 and n > 2:
            add("R4_strip_lines", "hard" if n > 3 else "soft", [i], f"{n} lines at {int(e['font_size'])}px in a strip")
        if n >= 2 and words >= 3:
            wmax = max(lw for _, lw in lines)
            if lines[-1][1] < 0.35 * wmax:
                add("R5_widow", "soft", [i], f"last line '{lines[-1][0].strip()}' = {lines[-1][1] / wmax:.0%} of measure")
            singles = [t.strip() for t, _ in lines if len(t.split()) == 1]
            if ctx.roles.get(i) == "headline" and singles and (words >= 4 or len(singles) == n):
                add("R5_one_word_lines", "hard" if len(singles) == n else "soft", [i], f"{singles}")
            for t, _ in lines[:-1]:
                w = t.strip().split()[-1].lower().strip(",.;:") if t.strip() else ""
                if w in F.FUNCTION_WORDS:
                    add("R5_dangling_word", "soft", [i], f"line ends on '{w}'")

    # ---- R6 logo dominance / R7 hierarchy (both relative) -----------------------------------------
    lr, lr_src = out.logo_ratio(), src.logo_ratio()
    if lr is not None and lr > max(0.8, 1.2 * (lr_src or 0)):
        add("R6_logo_dominance", "hard", [out.first("logo"), out.first("headline")], f"logo ink = {lr:.1f}x headline ink")
    rr, rr_src = out.rank_ratio(), src.rank_ratio()
    if rr is not None and rr < 1.2 and (rr_src is None or rr_src >= 1.2 or rr < rr_src - 0.05):
        add("R7_hierarchy", "hard", [out.first("headline")], f"headline cap only {rr:.2f}x the next text")

    # ---- R8/R9 density, R11 decoration crossing (relative) ---------------------------------------
    eb, eb_s = out.empty_band(), src.empty_band()
    if eb > max(0.30, eb_s + 0.05) and out.ink:
        add("R8_empty_band", "soft", [], f"{eb:.0%} of the long axis empty (source {eb_s:.0%})")
    cov, cov_s = out.coverage(), src.coverage()
    if cov < min(0.35, cov_s - 0.05) and out.ink:
        add("R9_island", "soft", [], f"content covers {cov:.0%} of canvas (source {cov_s:.0%})")
    so = src.deco_overlap()
    for (d, i), f in out.deco_overlap().items():
        if f > so.get((d, i), 0.0) + 0.10:
            add("R11_deco_crossing", "soft", [d, i], f"translucent shape covers {f:.0%} of {ctx.roles.get(i)}")

    # ---- R12 rhythm, R13 strip padding, R14 timid headline ----------------------------------------
    if H >= 1.2 * W and len(out.ink) >= 4:
        rows = sorted(out.ink.values(), key=lambda r: r[1])
        merged = []
        for r in rows:
            if merged and r[1] < merged[-1][3] - 2:
                q = merged[-1]
                merged[-1] = (min(q[0], r[0]), q[1], max(q[2], r[2]), max(q[3], r[3]))
            else:
                merged.append(r)
        gaps = [b[1] - a[3] for a, b in zip(merged, merged[1:]) if b[1] - a[3] > 0]
        if len(gaps) >= 3 and max(gaps) > 4 * max(min(gaps), 0.01 * H):
            add("R12_rhythm", "soft", [], f"stack gaps {min(gaps):.0f}..{max(gaps):.0f}px")
    h = out.first("headline")
    if h and H <= 120:
        r = out.ink[h]
        pad = min(r[1], H - r[3])
        if pad < 0.12 * H - 0.5:
            add("R13_strip_padding", "soft", [h], f"headline ink {pad:.0f}px from top/bottom")
    if h and H >= W and len(out.els[h].get("content", "").split()) <= 5:
        hw = out.ink[h][2] - out.ink[h][0]
        if hw < 0.5 * (W - 2 * unit):
            add("R14_timid_headline", "soft", [h], f"short headline spans {hw / (W - 2 * unit):.0%} of measure")
    return V


def summary(vs):
    hard = sum(1 for v in vs if (v.severity if hasattr(v, "severity") else v["severity"]) == "hard")
    return {"hard": hard, "soft": len(vs) - hard, "rules": sorted({v.rule for v in vs})}
