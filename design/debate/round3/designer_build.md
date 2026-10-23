# DESIGNER — Round 3 build notes

**What I own:**
- `proto/finisher.py` and `proto/rules.py`.
- In `proto/tests/`: `test_finisher.py` (8 checks, all passing) and `finisher_demo.py`, which produces the before/after sheets and counts.
- Fixtures `proto/fixtures/designer_{photo,split}.json`, plus the asset `fixtures/assets/designer_busy_photo.png`.
- Requests to OPTIMIZER are appended in `proto/REQUESTS.md`.

**How to run** (from the repo root):
```
.venv/bin/python -m design.debate.proto.tests.test_finisher      # 8/8 PASS
.venv/bin/python -m design.debate.proto.tests.finisher_demo      # proto/out/finisher_*.png + finisher_counts.txt
```

## rules.py: `check(source, output, info) -> list[Violation]`

A Violation has the fields `.rule`, `.severity` (`hard` or `soft`), `.ids` and `.detail`. `summary()` gives the counts.
- **Roles:** taken from `info["roles"]` when present. Otherwise `finisher.infer_roles` provides them, using the round-3 canonical vocabulary; it scores 32/32 on the samples.
- **Measurement:** everything is measured with the renderer's own `char_widths`/`wrap_text` at `int(font_size)`, skia ascent and cap height, and the asset alpha bboxes.
- **Robustness:** it never raises. On error it returns a single soft `RULES_ERROR`.

**Contract rules (all hard):**
- C0 ids; C1 off-canvas; C2 integer font sizes; C3 text w/h < 1; C4 image aspect > 5%;
- C5 rotated corners clipped; C6 visible missing-asset placeholder.

**Taste rules:**

| rule | what it checks | severity |
|---|---|---|
| R0 | P0 elements present; the headline is exempt if `info["mode"] == "brand_reminder"` | hard |
| R1 | edge clearance | soft |
| R2 | optical margins | soft |
| R3 | CTA label ≥ 12 judge-px | hard |
| R4 | strip headline lines | soft at 3, hard above 3 |
| R5 | widow / one-word lines / line ending on a function word | soft (all-single-word headline is hard) |
| R6 | logo weight vs headline weight (Σ line width × cap height) | hard |
| R7 | hierarchy by cap height | hard |
| R8 / R9 | empty band / island | soft |
| R10 | smudge < 9 judge-px | hard |
| R11 | decoration over text, CTA or logo | soft |
| R12 | rhythm | soft |
| R13 | strip padding | soft |
| R14 | timid headline | soft |
| R15 | new box overlap between flow elements, excluding related pairs and pairs that already overlapped in the source | hard |
| R16 | label spill (perception's I13) | hard |

**Source-relative rules** (R1, R6, R7, R8, R9, R11) never flag a source against itself. The test suite checks this on all 3 samples.

## finisher.py: `finish(source, output, info) -> output`

- **Pure:** inputs are never mutated, and it returns the same object if nothing changed.
- **Never raises:** if anything throws, the input comes back unchanged.
- **Mandatory normalisation first:** integer font sizes and honest text-box heights.
- **Then 11 passes, iterated to a fixed point** (max 4 rounds):
  1. `logo_weight`: logo ink ≤ 0.75 × headline weight, source-relative, with a 24 judge-px floor.
  2. `pills`: label caps optically centred in the pill. The CTA label is grown to ≥ 12 judge-px by growing the pill, which slides inward to stay in-canvas. Labels are capped at headline cap / 1.2.
  3. `balance`: the narrowest **integer** width that keeps the line count. Deterministic, which is why the result is idempotent.
  4. `rag`: removes widows, one-word lines and lines ending on a function word by trying font size −0..−14% × line count n−1..n+1 within free space and a side margin.
  5. `strip_lines`: a strip headline goes to ≤ 3 lines, preferring 2, without breaking hierarchy.
  6. `strip_unit`: the headline and subhead become one tight unit centred on the midline, and the logo, pill and hero are centred on the same midline.
  7. `margins`: columns are redistributed for equal optical outer margins and gutters that are **box-disjoint by construction** (gutter ≥ transparent-padding overhang on both sides). Halos travel with their image and are never de-centred.
  8. `rhythm`: on tall canvases, stack gaps snap to {1, 2, 3} × the median gap, preserving the total span.
  9. `decorations`: translucent discs must not cover the logo, CTA or text by more than the source overlap + 5 pts. A disc becomes a concentric halo behind the hero (only if it fits **without clamping**) or moves to a free corner. An existing halo is kept unless it covers more than 25%.
  10. `furniture`: a *visible* sticker that is clipped or colliding keeps its angle and tries source corner → mirrored corner → hero shoulder (≤ 20% of hero ink). **Un-hiding engine-hidden furniture is OFF**, because visibility is the engine's call.
  11. `separate`: when two flow boxes overlap only through transparent image padding, the image slides away by the smallest move (its halo follows), or its box shrinks about its ink (≥ 0.8×).
- **Acceptance of each pass:** the pass result is kept only if:
  - the contract versus the finisher's input holds: same ids and order, in-bounds with the rotated AABB, image aspect within 1%, integer sizes, w/h ≥ 1, content and font unchanged, **no new flow-box overlap**;
  - it introduces **no new hard (rule, ids)**;
  - and the score (hard count, then soft count) strictly improves.

  So the finisher cannot make any engine's output worse by its own rules.
- **Compatibility:** tested with OPTIMIZER's real `decompile` output as `info` (roles + containers), as well as with `{}`. Chip containers are derived from shape+text groups, because the decompiler's `containers` only lists panels.

## Evidence

The before/after sheets are `proto/out/finisher_{designer,inventor,optimizer}.png`. The before set is 48 existing engine outputs:
- **my R1 outputs:** 11
- **inventor's:** 15
- **optimizer's:** 22

| engine | changed | hard before → after | soft before → after |
|---|---|---|---|
| designer R1 | 6/11 | 18 → 9 | 12 → 7 |
| inventor | 15/15 | 35 → 21 | 36 → 14 |
| optimizer | 16/22 | 62 → 40 | 33 → 13 |
| **total** | 37/48 | **115 → 70 (−39%)** | **81 → 34 (−58%)** |

Per rule (before → after):

| rule | before → after |
|---|---|
| R11 decoration crossing | 30 → 0 |
| R6 logo dominance | 9 → 0 |
| R15 box overlap | 72 → 43 |
| R3 CTA label | 11 → 4 |
| R5 widow | 5 → 1 |
| R5 dangling word | 19 → 14 |
| R5 one-word lines | 4 → 3 |
| R13 strip padding | 1 → 0 |
| R2 margins | 13 → 9 |
| R12 rhythm | 4 → 2 |

**Unchanged, by design (engine decisions the finisher must not take):**
- R10 smudges (17): fixing them needs hiding or a larger scale.
- R4 lines on L3 728×90 (3): the engine must drop the product or subhead, per the message-first policy.
- R0 (1): my R1 L3 at 320×50 hid the headline.
- R7 (1): my L3 728×90 has the CTA label equal to the headline; the 12 px floor conflicts with a 14 px headline.

**What I checked by eye** on the sheets:
- Decoration discs move off logos and CTAs into concentric halos behind the bottle (inventor L2 1080/1600, optimizer L2).
- Oversized logos shrink to sit under the headline (optimizer L1 1280×720 and 1600×400 are visibly better).
- Inventor's L3 728×90 widow "Gatherings" is fixed, the message is vertically centred, and the CTA label goes from 10 to 12 px.
- No regressions spotted. One bug the eye caught and I fixed: a halo that was clamped off-centre at the canvas edge. The fix: halos are concentric or nothing.

**Properties:**
- **Idempotent** on all 48 outputs: `finish(finish(x)) == finish(x)`.
- **Never mutates** its inputs.
- **Hidden elements untouched.**
- **Speed:** about 1–10 ms per call after a warm-up of ~0.6 s for font loading.

## Limits and next steps
- **Remaining box overlaps:** R15 still has 43, mostly logo×product or headline×product padding in dense engine layouts with no free space. They need the engine's box-disjoint packing, which is `DISJOINT_BOXES` in INTERFACES.
- **Rag repair is local.** It can't fix "Chase / the / Light" at 160×600 without exceeding the side margins; that one needs a smaller scale chosen by the engine.
- **Rhythm snapping** acts only when rows are cleanly separable.
- **Decoration relocation** is heuristic: halo, then the four corners at sizes 1, 0.75 and 0.5.
- **The rules are my own taste encoded.** Perception's critic is the independent check; a dev-time VLM should calibrate R-thresholds.
- **Discrepancy with OPTIMIZER's decompiler** (reported in REQUESTS):
  - L3 product → "logo";
  - photo subhead → "legal";
  - L2 corner badge → "furniture" (fine: p9 handles unrotated furniture too).
