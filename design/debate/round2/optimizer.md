# OPTIMIZER — Round 2

**In short.**
- **Head-to-head.** I ran GALLEY and my R1 solver on 6 designs × 7 catalogue sizes, scored by one neutral pixel critic. Two of the designs are new, with opaque ids: a split colour block and a scrim card over a busy photo.
- **Result.** GALLEY has the better *search formulation*; mine has the better *inner solver and energy*. All three stream engines (GALLEY, mine, DESIGNER) fail the new designs, because none of them models **containers**.
- **Prototype.** "Containers as nested designs" takes lost-backdrop / on-busy-pixel outputs from 12 / 6 to **0 / 0**.
- **Inverse optimization from the source** is mathematically sound and found a real bug in my energy. But it provably *cannot* identify the trade-offs that decide 728×90.

All spikes are in `spikes/optimizer/r2_*.py`, outputs in `r2_out/`.

---

## A. Critiques

### A1. INVENTOR / GALLEY — head-to-head (`r2_h2h.py`)

**Setup.**
- **Designs:** L1–L3, INVENTOR's unseen split ad **U**, and two new opaque-id designs:
  - **S** (1080²): a plum colour-block panel, an *ungrouped* shape, carrying white copy, with the product on cream.
  - **B** (1200×628): copy on a translucent scrim card over a generated busy photo.
- **Sizes:** 728×90, 320×50, 1600×400, 1080×1920, 1080², 300×250, 160×600.
- **Critic** (official render; neither engine's own objective):
  - An underlay render without text tells it what each glyph sits on.
  - **crel** = contrast relative to the *source's* own contrast for that text; below 0.5 means the backdrop is lost.
  - **busy** = edge density under the glyphs.
  - Plus minimum px, clipped or overlapping ink, and coverage.

| failures / 42 runs (`h2h_log.txt`) | crash | text <10px | lost backdrop | on busy | clipped / overlap | tiny island |
|---|---|---|---|---|---|---|
| GALLEY | **1** | **13** | 0 | 1 | **1 / 1** | 2 |
| OPTIMIZER R1 | 0 | 4 | **12** | **6** | 0 / 0 | 0 |

**Sample-like designs (L1–L3, U).** Mine is more legible: mean minimum text 21.4 px vs 17.1, with no clip or overlap. GALLEY's failures here all come from sizing columns by proportional shrink instead of exact breakpoints:
- the L3→320×50 headline runs below the canvas;
- the L3→160×600 subhead sits on the CTA;
- S→320×50 emits `font_size 0`, which **crashes the official renderer** (pydantic `gt=0`).

**S and B.** The engines fail in opposite ways (`h2h_S.png`, `h2h_B.png`):
- **GALLEY:** the XY-cut correctly sees panel + copy as an overlapping "island", but keeps it *rigid*. You get 1–7 px type in a mostly empty canvas.
- **Mine:** the panel is classified as decoration and re-anchored alone. White copy lands on cream (crel 0.07), or on the busy photo (busy 0.30–0.44).

**Formulation verdict.**
- **Expressiveness.** The ordered stream with ¶ (row) / | (column) / / (stack) labels is a 3-level tree. It *strictly contains* my "row of stacks / single column" templates and adds header rows.
  - The extra power rarely won, and once it lost: U→1080×1920 put the product beside the logo.
  - Neither formulation has **brackets** (nesting) or **layering**. Those are the real gaps.
- **Scalability.** Both are exponential when enumerated: 0–0.9 s vs 0–2.9 s per case here. The right way to scale is GALLEY's Knuth–Plass view:
  - For fixed z, rows are independent, so DP over stream position works.
  - *Omission folds into the DP as a skip transition costing the unit's rent.* That is exact and not prefix-limited.
- **Omission.** GALLEY's rent-prefix is fragile: in R1 one infeasible image killed every superset for me, and it forces "product before subhead" everywhere. My all-subsets costs 2^k. DP skips beat both.
- **Energy.** `s` and `z` are the same idea.
  - GALLEY's utility is concave and **capped at s ≤ max(1, √area-ratio)**. That cap is why it nearly reproduces the source at the source canvas: 0.8–6% centre drift on L1–L3, S and B, and 0% font change except 14% on S. Mine inflates fonts by 27–50% (see C).
  - Mine has what GALLEY lacks: a legibility hinge, a copy budget, line-break and image/type faithfulness, and a *hard* ordinal hierarchy. GALLEY's floors don't reach rigid groups, which is why its CTA labels come out at 8 px.

**Stolen:**
- the XY-cut decompiler (my y-sort reading order gives U 20–22% fixed-point drift);
- TeX glue;
- the capped concave utility;
- DP with skips.

**Verdict:** right skeleton; it needs my column solver, my energy, and brackets.

### A2. DESIGNER (`r2_others.py`, `designer_vs_merged_S.png`)

**Steal:**
- **per-role elasticity `k^γ`**: it generalises my shared z to z^γ_role, stays monotone, so bisection survives;
- "legible or absent";
- cap-height optical placement and balanced wrap.

**Most serious flaw:** a hard-coded archetype tree over a role taxonomy that has **no container role**. I ran `compose.py` unmodified:
- The S panel becomes "decoration → halo", so white copy lands on cream at 728×90, 320×50 and 1600×400 (crel 0.07).
- At 160×600, S and B render a cropped logo with *every text hidden* and boxes off-canvas.
- B's strips put copy on the photo (busy 0.33–0.45).

A decision tree degrades discontinuously outside its taxonomy; a search with an energy degrades gracefully.

**Verdict:** keep its constants (γ, floors, chip anatomy) as terms and priors inside the search.

### A3. PERCEPTION

**Steal:**
- the render-in-the-loop critic with **source-relative** thresholds. My 80-line copy of it exposed every failure above that geometry could not see;
- **Crello format priors** (leaderboard headline ≈ 0.30·H). Section C shows these are *exactly* what the source cannot supply.

**Flaw:**
- **A critic only ranks what the generator proposes.** The archetype generator has A2's blind spot. My critic flagged all 12 lost backdrops, but re-ranking fixed none; a new *candidate type* did.
- **Cost.** 72 renders per banner is 4.6–14 s native, times 2–5 under emulation.

**Verdict:** essential as verifier and as the source of weights and priors; insufficient as the generator.

### A4. JUDGE

**Steal everything structural:** the invariant contract, repair, fallback ladder and metamorphic tests. My head-to-head found exactly the bug class JUDGE predicts (`font_size 0` crash, text below the canvas). The fixed-point metamorphic test caught the biggest defect in *my* engine (C).

**Flaws:**
1. **Hiding text under the background (I10)** edits `z_index` and inverts relative z-order, which JUDGE itself lists as a possible check. It also needs an opaque background. Colour alpha 0 (keeping z) is the safer default.
2. **The safe floor isn't VLM-safe.** JUDGE's own sweep found 217 unreadable texts. The floor should be the best *legible* candidate.

**Verdict:** the outer shell, unchanged.

---

## B. v2 position: a *bracketed galley* with an exact inner solver

```
decompile  XY-cut on ink boxes → ordered stream + layers (bg/texture/furniture, as GALLEY);
           brackets = CONTAINERS: shape, α ≥ .5, ≥ 4% canvas, holding ≥ 2 content units
grammar    units joined by / | ¶  plus ( … )[panel]; a bracket is a NESTED DESIGN whose background is
           the container: bleeds to target edges if the source panel touched ≥ 2 edges, else inset card
inner      shared z with role exponents γ; bisection; column min-width = exact text-frontier breakpoint
           (renderer's own wrap); widen toward source line counts; PAVA positions; int fonts; hard hierarchy
search     n ≤ 10 enumerate; n > 10 Knuth–Plass DP per z with skip transitions (omission at rent cost);
           brackets solved recursively over a menu of region sizes; z-consistency term across brackets
energy     capped concave size utility + legibility hinge + copy budget + faithfulness terms + Crello
           format prior; weights fit as in C
verify     top-K render → pixel critic (source-relative) → repair → contract → fallback ladder (JUDGE)
```

**Prototype (`r2_merged.py`).**
- **How it works.** A container is cut out as a sub-design and solved *recursively by the same solver*. The outer level searches orientation × split fraction × keep/drop the rest, with a z-consistency term. No-container designs fall through unchanged.
- **Scores** (`merged_log.txt`):

| S + B, 14 runs | crash | text <10px | lost backdrop | on busy | clipped |
|---|---|---|---|---|---|
| GALLEY | 1 | 7 | 0 | 1 | 0 |
| OPTIMIZER R1 | 0 | 0 | 12 | 6 | 0 |
| DESIGNER | 0 | 2 (no text left) | 5 | 2 | 0 (+3 off-canvas) |
| **MERGED** | **0** | 3 (8–9 px at 320×50 / 160×600) | **0** | **0** | 1 |

- **Renders** (`merged_S.png`, `merged_B.png`):
  - the split becomes a full-height plum column on banners and a full-width band on stories, with copy re-typeset inside;
  - the scrim card reflows to `logo | headline/subhead | CTA` *inside the card* at 728×90;
  - the product is dropped at 728×90, 320×50 and 300×250;
  - the split is reproduced at the source canvas (1.7% drift).

**Open problems this answers:**
- **#2 Containers.** Solved for panels and cards (split blocks, scrims, boxed CTAs). Text on a full-bleed photo *without* a scrim needs a calm-region cost from the critic's underlay (per-target cover crop × edge density). That is the next spike, not built.
- **#4 Near-ties.** C shows many are *undecidable from the source*: both candidates lie inside the identified weight set. Break them deterministically: first by format-prior likelihood, then by structural distance to the source program.
- **#5 Ink vs box packing.** Keep ink packing behind a flag. Containers shrink the issue, because the panel box *is* the visual box.

---

## C. Open problem #1: inverse optimization from the source (`r2_inverse.py`, `r2_fixedpoint.py`)

**Formalisation.** E_w(L) = w·φ(L) is linear in w. "The source S is the designer's argmin at its own canvas" means w·(φ(L) − φ(S)) ≥ 0 for every alternative L. That defines a polyhedral cone K = {w ≥ 0 : Aw ≥ 0}: inverse LP (Ahuja–Orlin), equivalently a structured-SVM constraint set from **one demonstration**.

**Method.** I generated alternatives with my own search space, extended below max-zoom so the source (z = 1) is a candidate. That gives 3,403 constraints pooled over L1, L2, L3 and the S-panel and B-card sub-designs. I then computed the exact projection w* = argmin‖w − w₀‖ subject to w ∈ K (Hildreth), and for each weight the exact interval [lb, ub] that keeps every source optimal.

**Result 1: a misspecification detector.**
- Under my hand weights, the source ranks **#15–#165** at its *own* canvas; the argmin is max-zoom.
- The projection forces **w_size → 0.000 (ub 0.001)**: no monotone size reward is consistent with any source. The same holds for GALLEY's increasing utility, which survives only because of its cap.
- Adding a density term (deviation of type scale from the area reference) plus a concave utility lifts the source to #3–#16.
- On real outputs (`fixedpoint_log.txt`): R1 fonts inflate 27–50%. The cap brings that to 0–1.7% for my solver. MERGED + cap reproduces S with 1.7% drift.

**Result 2: what one demonstration can identify.** Alternatives *worse* on a term give lower bounds; alternatives *better* on it give upper bounds.

| term | interval (others at w*) | why |
|---|---|---|
| size utility, legibility, fill, lines | **upper bound only** (0.74, 3.9, 1.2, 1.5) | departing from the source *gains* on these |
| drop, density, ratio, breaks, slots | **lower bound only** (drop ≥ 0.57, dens ≥ 0.68, ratio ≥ 0.86) | the source is never worse on them |
| copy budget, image order, reading order | **nothing**: 3,403 ties | never active at the source canvas |

**No weight is pinned on both sides.** One-demonstration inverse optimization also "explains" the source by inflating whatever feature separates it: w_ratio went from 0.25 to 1.05.

**Result 3: the decisions that matter are not identified.** Solving unseen targets with weights *inside* the identified set:
- **L3→728×90:** drop = 0.57 hides product and subhead; drop = 1.6 keeps the product; drop ≥ 6.4, or legibility/copy weight 0, keeps the 190-character subhead at 10 px.
- **L2→728×90:** drop = 0.57 drops the product, as the brief's reference does; drop = 1.6 keeps it.
- **S-panel→300×250:** legibility weight 0 takes the subhead from 12 to 9 px.

All of these are equally consistent with every source. At the source canvas nothing is dropped, floors never bind and the copy budget never fills, so the exchange rates that govern extreme formats are **unobservable**. That includes density vs legibility: the √area reference pulls a 728×90 headline toward 9 px.

**Verdict: neither genius nor nonsense.** It is sound and cheap, with three jobs:
1. **CI test:** the source must be the argmin, with fixed-point drift within 3%. It caught my R1 engine's worst bug.
2. **Hard constraints in the population weight fit.** VLM pairwise labels (Bradley–Terry) supply extreme-format exchange rates; Crello priors supply each format's absolute operating point; each source adds its cone.
3. **Per-design calibration**, only of the terms it identifies (image/type ratio, density near the source aspect).

Never the sole source of taste.

---

## D. Experiments (`design/debate/spikes/optimizer/`, outputs in `r2_out/`)

| spike | finding |
|---|---|
| `r2_designs.py` | Opaque-id designs S and B. Assets are copied to `r2_kit/`; brand_kit is untouched. |
| `r2_h2h.py` | GALLEY: renderer crash, clip, overlap, 13 runs with text under 10 px. OPT: 12 lost backdrops. Sheets in `h2h_*.png`. |
| `r2_others.py` | DESIGNER: 5 lost backdrops, 2 on busy pixels, 3 off-canvas, all text hidden at 160×600. |
| `r2_merged.py` | Containers as nested designs: lost backdrop / busy 12 / 6 → 0 / 0. |
| `r2_inverse.py` | w_size → 0; bounds only one-sided; drop, legibility and copy unidentified; decisions flip inside the set. |
| `r2_fixedpoint.py` | GALLEY 0.8–6% drift (U 12%). OPT R1 fonts +27–50%; with the cap, 0–1.7%. |

**Limits.**
- The prototype handles one container per design; nested containers are untested.
- No calm-region placement yet.
- 320×50 and 160×600 still reach 8–9 px, because those floors need the Crello priors.
