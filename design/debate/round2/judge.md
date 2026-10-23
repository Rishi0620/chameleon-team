# JUDGE: Round 2. One ruler for everyone, and what it found

I built the shared benchmark, `design/debate/bench/`:
- **15 designs.** The 3 samples plus 12 adversarial designs with opaque ids and shuffled order (photo split, text on a busy photo, product grid, long editorial copy, bleeding rotated sticker, ungrouped text backgrounds, lines with z-ties and letter-spacing, a missing hero with empty, emoji and `&amp;` text, leaderboard and story sources, a card on an overlay, 6 badge groups).
- **26 platform sizes**, so **390 cases per engine**.
- **Engines.** Every spike through thin adapters (no edits to their files), plus my safe floor and the stretch baseline.
- **Per case.** Structural contract, pixel-verified renderer-gap checks, proxy metrics, render and JSON.

Tables: `bench/SCOREBOARD.md`. Sheets: `bench/sheets/`.

**Headline (390 cases each; hard fail, crash or timeout scores 0).**

| engine | hard fail | crash / timeout | mean | p10 | primary text dropped |
|---|---|---|---|---|---|
| designer | 4 | 0 / 0 | 86.5 | 69.7 | **15** |
| optimizer | 0 | **5** / 0 | 88.9 | 79.3 | 0 |
| optimizer + 1-line cache fix | 0 | 0 / 0 | **90.4** | **79.9** | 0 |
| galley | 6 | 3 / 1 | 88.1 | 73.2 | 0 |
| perception (strip sizes only, 135) | 0 | **50** / 0 | 52.3 | 0.0 | 0 |
| safe floor (mine) | 0 | 0 / 0 | 71.9 | 43.5 | 0 |
| uniform stretch | 343 | 0 / 0 | 9.9 | 0.0 | 0 |

The composite is a **triage tool, not a taste ranking**. It reliably separates broken from designed. Among designed outputs it is roughly a coin-flip-plus, consistent with PERCEPTION's 36–64% agreement for a similar critic. I quote failure *counts* below, not composite deltas.

---

## A. Critiques

### DESIGNER (`compose.py`)
- **Steal:**
  - balanced wrap by bisecting box width;
  - cap-height optics;
  - "legible or absent";
  - above all, the R2 rule set R0–R14 with **source-relative** tolerances. It is the best written-down taste spec we have.
- **Most serious flaw: the archetype tree degrades into blank canvases, and the contract doesn't stop it.**
  - 15/386 outputs drop the **primary text**. Every other engine drops it in 0.
  - S09 (banner source) at 160×600 renders *only the background*: every id is hidden, score 23.
  - S04 at 320×50 shows a lone "Read more" pill.
  - 4 hard fails, all off-canvas boxes: the logo at 160×600 three times (L3, S07, S10), and the S02 scrim at 600×200.
  - Containers are missing, which the other agents also found. S11's dark card copy lands on the dark background at strips: p10 contrast 1.04, against 15.0 in the source. Scrims become stray boxes (S02, S10).
  - The renderer gap bites too: **41 of its 48 text overflows are letter-spaced kickers**, and all 7 off-canvas inks are kickers. Its wrap ignores `letter_spacing`.
  - **It is not order-blind.** Renaming ids and permuting the list (render order unchanged, C3) changes 4/75 outputs, all on S06 (shapes behind text without `group_id`). The chip pairing follows list order, so the same design gives the price tag moved 327 px, or the highlight bar hidden, depending on the order.
- **Verdict:** the finisher (typography layer), not the generator. R0 ("P0 present") has to be a contract invariant, not an archetype habit.

### OPTIMIZER (`solver.py`)
- **Steal:**
  - the exact W_k frontier plus monotone bisection;
  - the copy budget;
  - PAVA;
  - the R2 inverse-cone analysis, the cleanest answer to open problem #1.
- **Most serious flaw: a cache keyed by `id(element)`.**
  - **The bug.** Python reuses `id()` after garbage collection, so a *new* element can read *another string's* glyph widths.
  - **Probe** (`r2_stale_cache_probe.py`, 104 solves in one process, as `main.py` runs tasks): **109 mismatched width lists in 594,883 wrap calls.**
    - 106 of them are *silently wrong*. One example: a 174-character width list used to wrap "Words by the Solstice field team".
    - 3 raise `IndexError`.
  - **On the bench:** all **5 crashes** come from this bug (S12 ×3, S03, S04). The bench runs 26 sizes per process, and the official batch runs hundreds of tasks per process, so it would be worse there.
  - **The fix is one line.** Applied from outside (`adapters/optimizer_fixed.py`), it gives **0 crashes in 390**, mean 88.9 → 90.4 and strip-band p10 74.4 → 77.2. Text overflows drop from 24 to 16, so some of the "overflows" were stale widths.
  - Its id-invariance only holds *with* the fix: 75/75 identical.
- **Second flaw: runtime tail.** Median 0.17 s but max 82 s (S03 at 1280×720 took 44 s), before a 2–5× emulation factor.
- **Third flaw: most low-contrast and text-collision flags of any engine** (155 / 63). This is the container blind spot it diagnosed itself, plus 12 letter-spacing overflows.
  - S11 card copy spills past its unchanged card ("ers get early access").
  - Pseudo-groups (S06, S07) come apart: the highlight bar strikes through the headline, "$5" leaves its tag, and "Get tickets" leaves its pill.
- **Verdict:** the best core. Ship it only behind the contract, with value-keyed caches.

### INVENTOR / GALLEY (`galley.py`)
- **Steal:**
  - the XY-cut stream IR;
  - rent;
  - the fixed-point test;
  - the R2 host/rider relation, which unifies split blocks, cards, scrims and buttons.
- **Most serious flaw: no never-fail path, and an exponential search.**
  - **3 crashes:** no candidate survives, so `res[0]` raises (L3 at 320×50, S10 at 300×250 and 336×280).
  - **1 renderer crash:** a rigid sticker group scales to `font_size 0` (S10 at 320×50). In strips the same "NEW" label is emitted at **1 px**, because floors don't reach rigid units.
  - **5 hard fails:** S07's vertical rule is a 600 px line rotated 90°. Its *unrotated* box can't fit a ≤336 px-wide canvas even though the rotated one does. Only a contract that knows both boxes catches this.
  - **Scale blow-up:** S12 (24 elements) takes **82–180 s per size, with 1 timeout over 180 s**. That is `3^(n−1)·(n+1)` in practice.
  - 88 unreadable-text instances.
  - It is also order-sensitive: at L3 160×600, a renamed and permuted copy moves the headline 62 px and changes its size from 20 to 19 px.
  - On the card design (S11) the card stays a rigid island and becomes unreadable at strips. The busy-photo designs (S02, S10) put text on foliage. As things stand, host/rider would fix the first of these but not the second.
- **Verdict:** keep the IR, replace the enumerator with OPTIMIZER's DP plus skips, and cap the work.

### PERCEPTION (strip generator + critic)
- **Steal:**
  - source-relative thresholds (the bench uses them);
  - pixel-true visibility;
  - box-disjoint as the default;
  - Crello priors;
  - and the line "a critic used for selection cannot also be the evaluator."
- **Most serious flaw: the only generator crashes the renderer on 50/135 strip cases.**
  - When logo + hero + CTA exceed W, the text column width goes **negative**, and `TextElement` fails pydantic `gt=0`.
  - Rendering in the loop doesn't protect you when the candidates themselves crash the renderer. **Every candidate must pass the contract before it is rendered.**
  - It also emits 174 float font sizes, so the measured wrap ≠ the drawn one.
  - It averages about 6 s per case for 72 renders.
- **Verdict:** a gate and tie-breaker (its own 36% → 64% agreement says the same), not the objective and not the generator.

### JUDGE (self)
- **INVENTOR is right about the colour flag.** My R1 proxy froze `color` and flagged alpha-0 hiding as HARD (6 hits). My bug, now fixed. The bench contract allows alpha-only changes and only warns on RGB changes.
- **My safe floor is the letterbox island:** mean ~72, and 936 unreadable-text instances. It is the only engine with **0 hard / 0 crash in 390**, and that is all it is for.
- **Two scorer bugs, found by reading the contact sheets:**
  - a giant text box was classed as a background layer (GALLEY's S04 at 300×600 scored 21 while showing a 47 px headline);
  - there was no label-spill-out-of-pill check (PERCEPTION's finding).

  Both fixed and re-scored (`bench/rescore.py`). Keep treating the metric as suspect.

---

## B. v2 position: contract-first portfolio search

```
decompile (GALLEY XY-cut + host/rider) ─► generate (OPTIMIZER frontier + bisection, DP with skips;
DESIGNER γ-elasticity)  ─► finish (DESIGNER balanced wrap / optics) ─► CONTRACT + REPAIR (every candidate,
BEFORE render) ─► rule vetoes (DESIGNER R0–R14, source-relative) ─► render top-K ─► pixel critic as
veto + tie-break (PERCEPTION) ─► lexicographic pick ─► fallback ladder ─► plain-JSON emit
```

**What changed in my view since R1:**

1. **The contract runs before rendering, not only after.** Every crash class the bench found is mechanical and checkable before any pixel exists:
   negative or zero text width/height, `font_size` 0, an unrotated box that can't fit while the rotated one can, unmeasured `letter_spacing` (add `ls·(n−1)` per line), a stale cache, an empty candidate list.

   These are **I1–I12 plus three new invariants**:
   - **I13 value-keyed caches only, and no state carried between `resize()` calls;**
   - **I14 a line shape's unrotated box must fit** (scale its length to the canvas);
   - **I15 the primary text is visible unless brand-reminder mode is logged.**
2. **The floor must be legible, not just valid.** OPTIMIZER is right. Ladder:
   1. best contract-passing candidate;
   2. a role-free "legible-or-absent" fallback: OPTIMIZER's contain-fit plus hiding every text below the floor except the primary, which takes priority space;
   3. the letterbox, only as a last resort;
   4. identity-clamped output, in pure Python.
3. **Near-ties (#4):** deterministic and lexicographic: contract → R0–R14 vetoes → count of rule violations → energy → Crello format prior → structural distance to the source program → stable id-free order. No critic-weight soup decides a tie.
4. **Taste (#1):** I agree with OPTIMIZER and INVENTOR. Fit weights with Bradley–Terry on VLM pairs shown at **native** resolution, constrained by every source's fixed-point cone. Use Crello priors for the far regime.

   My perturbation experiment (C4) points the same way, but it is **inconclusive on identifiability**:
   - **Fixed point.** OPTIMIZER's R1 energy does not reproduce the source at its own canvas for any of the 6 designs: drift is over 3%, or an element is hidden. Only 5/360 random weight draws do so, all on L1. So the "source-consistent" weight set is nearly empty before we can ask what it pins down.
   - **Sensitivity.** The weights clearly move the source-canvas layout: it changes in 5–85% of draws, and L3 hides source elements *at its own size* in 62%.

   The fixed point is a sharp **misspecification detector**, which matches OPTIMIZER's w_size → 0. I take their exact cone analysis as the identifiability answer.

   The fixed-point and round-trip checks become CI tests, never the objective. Per-design calibration is allowed only for the terms the source identifies.
5. **Ink vs box (#5):** PERCEPTION's default. Visible content boxes are disjoint, except same group, pairs that already overlapped in the source, and background or decoration. Gaps are specified ink-to-ink.
6. **The bench is the CI gate.** Every change re-runs the 390 cases; a merge needs 0 crashes, 0 hard fails, p10 not lower, no new rule-veto class, and id-invariance (C3) still green.

### Hide encoding (#7): recommendation

`r2_hide_encodings.py` took **120 real outputs that hide text** (30 each from DESIGNER, GALLEY, OPTIMIZER and PERCEPTION) and re-encoded every hidden text four ways, holding everything else fixed.

| encoding | leak (cases / mean px) | plausible checker rules it trips |
|---|---|---|
| E1 `opacity 0` + colour alpha 0 (RGB kept, style_runs too) | **0 / 0** | strict colour-*string* equality (120/120); RGB check: none |
| E2 `opacity 0` + z under the opaque full-bleed bottom layer | **0 / 0** (only because all 15 designs have one) | relative z-order over all elements (120/120); visible-only z-order: none |
| E3 `opacity 0` only | **109 / 1,987 px** | none: it fails on pixels instead |
| E4 `opacity 0` + `font_size 1` + 1×1 box | 77 / 45 px of specks | legibility floor applied to all text (120/120) |
| never hide text | n/a | DESIGNER hides ≥1 text in 214/390 outputs, OPTIMIZER 133/385, GALLEY 113/386; the floor that never hides has 936 unreadable smudges |

**Recommendation: E1 as the default**, behind proto's `HIDE_MODE` switch.

E1 vs E2:
- **Both are pixel-clean** in the bench.
- **E1 needs nothing from the design.** E2 needs an opaque, unrotated, full-canvas bottom layer. All 15 bench designs have one; a transparent, contain-fit or alpha background won't, and then E2 leaks like E3 (by construction; not measured).
- **E1's only exposure is a checker that string-compares `color`.** Any palette or "on brand" check that parses RGB passes.
- **E2's exposure is a checker that verifies relative z-order across all elements.** That is the most natural way to test "intentional layering preserved", which is a rubric row.
- **E1 is local and self-describing**: "this text is transparent". E2 makes the JSON say "this text sits behind the background", which is also what a viewer would see in the Express add-on.

Never combine E1 and E2: that stacks both exposures for no pixel gain.

The switch states:
- **`alpha`** (default).
- **`z_under_bg`**: only if the organisers say colour is frozen, and only when an opaque bottom layer exists. Otherwise fall through.
- **`never_text`**: legal for near-aspect targets only; at strips it produces smudges.

E4 is never used.

This is question #1 for the organisers, asked as a pair: *Is `opacity:0` accepted as "dropped"? Is a hidden element's colour alpha allowed to change?*

---

## C. New experiments (all in `spikes/judge/r2_*`, outputs in `r2_out/`)

1. **The bench** (`bench/`): `designs.py` (with an id legend), `contract.py`, `score.py`, `run.py` (resumable, one process per engine×design, timeouts), `rescore.py`, `report.py`, `adapters/*`.
2. **`r2_stale_cache_probe.py`**: OPTIMIZER's `id()`-keyed cache. 109 / 594,883 wrap calls get another string's widths, and 2 crashes reproduce in one process.
3. **`r2_id_invariance.py`**: rename ids and permute the list without changing render order (equal-z elements keep their relative order), then compare outputs.

   | engine | identical | notes |
   |---|---|---|
   | designer | 71/75 | the 4 differences are all S06 chip pairing |
   | optimizer | 75/75 | only after isolating its caches |
   | galley | 68/69 | L3 160×600 differs; 1 crash; S12 skipped |
   | perception | 15/15 | |
   | safe floor | 75/75 | |

   Pseudo-group inference is the hot spot: heuristics tie-break on list position.
4. **`r2_inverse_identifiability.py`**: OPTIMIZER's energy under 40–60 random re-weightings (×0.25–4), conditioned on reproducing the source at its own canvas. The consistent set is empty except 5 draws on L1 (see B4). The v1 sensitivity table is in `r2_out/inverse_sensitivity_v1.json`.
5. **`r2_hide_encodings.py`**: the table above.
6. **`r2_rank_stability.py`**: 2,000 random re-weightings of every composite weight (×0.3–3).
   - Across all sizes, the cache-fixed OPTIMIZER ranks #1 in 90% of weightings and GALLEY in 10%.
   - On strips it is OPTIMIZER-fixed 52% vs DESIGNER 47%.
   - Conclusion: the composite robustly says "fixed OPTIMIZER ≥ the rest overall". Strip quality is a coin flip that only eyes or a VLM can settle.
7. **Round-4 prep:**
   - `bench/adapters/proto.py`, plus `proto_zunder.py` / `proto_nevertext.py`, wrap `design.debate.proto.engine.resize` with the bench assets. It is lazily imported, so the bench records import errors until the engine lands.
   - The hide-policy A/B is then one command: `run.py --engines proto,proto_zunder,proto_nevertext`.
