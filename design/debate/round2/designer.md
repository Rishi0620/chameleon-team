# DESIGNER — Round 2: the taste authority's review

All evidence is in `spikes/designer/r2_*`:
- `r2_rules.py`: 15 measurable taste rules that run on any engine's JSON. Reports: `r2_rules_report*.txt`.
- `r2_ground.py` + `r2_compose.py`: ground-binding spike.
- `r2_lb_sheet.png`: three leaderboard policies side by side.
- Contact sheets: `r2_sheet_*` (my R1 engine on unseen designs), `r2v2_sheet_*` (v2), `r2x_sheet_extremes.png`.

## A. Critique: what a senior designer sees in the renders

I first turned "my eye" into code. `r2_rules.py` takes ink rects from the renderer's own wrap/skia metrics and asset alpha bboxes, then flags 15 defects a designer would circle in red (§B1). I ran it over 51 outputs from all agents. "Source-relative" counts a defect only when the output is worse than the source itself (§B2).

| agent | outputs | flags/output (absolute) | flags/output (source-relative) |
|---|---|---|---|
| optimizer | 22 | 2.45 | 1.91 |
| inventor | 15 | 3.40 | 2.93 |
| perception | 2 | 4.50 | 4.50 |
| judge (mock) | 1 | 2.0 | 2.0 |
| designer R1 | 11 | 1.45 | 1.00 |

My own number is a lower bound, for two reasons: the rules are mine, and my R1 set skipped 160×600, where I fail worst (see Self).

**OPTIMIZER**
- **Steal:** the exact text frontier + bisection over discrete topologies, the cleanest search core on the table. Also the *copy budget* ("can this canvas be read?"), which is a genuinely designerly test.
- **Worst flaw:** nothing enforces hierarchy *across element types*. Images scale by tiers that are independent of the type scale, so the logo wins (R6, 7 of 22 outputs):
  - L1 1600×400: logo ink is 3.5× the headline; optical margins 427 vs 114 px.
  - L1 1280×720: logo ink is 2.0× the headline, and "Light" is stranded on line 2.
- **Decorations ignore type** (R11, 13 hits). `deco_circle_2` covers 36% of the CTA pill at L2 1280×720.
- **Extremes and strips:**
  - 160×600: 8 px CTA labels, a 7 px legal smudge, and "Chase / the / Light" one word per line.
  - Leaderboard: CTA label at the 10 px floor.
- **Verdict:** keep the core. The logo/headline ratio and "no decoration under type" must be hard constraints, not energy weights.

**PERCEPTION**
- **Steal:** render-in-the-loop with source-relative thresholds, the calm map of the *cover crop*, and the Crello priors.
- **Worst flaw:** the critic has no typographic taste, and its own rank-1 picks show it.
  - L2 1600×400:
    - logo ink equals headline ink;
    - "Chase" is orphaned on line 1;
    - the subhead runs 4 lines in a ~250 px measure while ~100 px of canvas sits unused;
    - `deco_circle_2` covers 46% of the CTA;
    - optical margins are 170 vs 36 px.
  - L3 728×90: CTA label 15 px = headline 15 px (R7), with the pill 8 px from the edge.
-
- **Verdict:** right loop, wrong objective. Feed it the rule set as vetoes and features.

**JUDGE**
- **Steal:** the invariant contract + repair, the 26-size sweep, and above all the **identity metamorphic test** (target = source ⇒ source). My R1 engine fails it on a colour-block design.
- **Worst flaw:** `safe_fit` as a layout is the letterbox island (R9 territory). 
- **Hiding:** "z under an opaque background" breaks on designs without a full-bleed background. Colour alpha does not.
- **Verdict:** this is the QA and gatekeeper layer, and the last fallback only.

**INVENTOR (GALLEY)**
- **Steal:** the XY-cut reading stream (column-major). It is exactly the fix for my R1 bug where the logo landed *under* the product on inventor's own unseen split design (`r2_sheet_unseen.png`). Also designer gaps as glue, and the fixed-point test.
- **Worst flaw:** micro-typography. Optimal search doesn't show up as polish.
  - L3 728×90:
    - the headline ends on the one-word widow "Gatherings" (23% of the measure);
    - its ink sits 9 px from the top/bottom edges;
    - the CTA label is 10 px (R3, 5 outputs);
    - optical margins are 46 vs 8 px.
  - L1/L2 728×90: glue stretches the headline to the top and the subhead to the bottom, so the message reads as two loose items rather than a unit.
  - L2 300×250: "Chase / the / Light" set one word per line *beside* the logo.
  - Decorations: `deco_circle_1` covers 87–100% of the logo (grey disc), and `deco_circle_2` crosses the CTA.
  - L2 story: stack gaps run 23–281 px (R12).
- **Verdict:** the best IR. It needs a typesetting finisher: balanced wrap, a vertically centred message unit, label floors.

**Self (DESIGNER R1)** (`r2x_sheet_extremes.png`)
- **160×600 is catastrophic.**
  - L3 drops the *headline* and pushes the logo off-canvas, so only "CE" is visible (R0).
  - L2 drops the CTA. My tiering was enforced in strip and split but not in stack.
- **L3 728×90** ties the CTA label with the headline at 14 px over 4 lines (R7).
- **Stories:** gaps run 31–355 px.
- **Unseen designs, R1 engine unchanged (`r2_run.py`):**
  - The busy **photo** puts the logo and headline on foliage at every size.
  - The **split colour block** loses its panel, because I classed it as "decoration".
    - At 728×90 the dark headline sits on a dark background and is invisible.
    - At 1600×400 the text spills off the panel and reads as clipped.
    - Same-size 1200×628 is not a fixed point.
- My taste rules were right; my coverage was not.

## B. v2 position

**Architecture.** I endorse the converged skeleton:
1. GALLEY's XY-cut stream
2. → OPTIMIZER's exact search over topologies with one shared scale
3. → PERCEPTION render-verify of the top K
4. → JUDGE contract, repair and fallback.

My v2 adds the layer that decides *which* valid layout is designed, as four pieces:
- the designer contract: measurable, source-relative rules, used as vetoes and then as features;
- **ground binding** for topologies beyond stacks;
- an extreme-format policy;
- a furniture policy.

### B1. Taste as measurable rules (`r2_rules.py`, engine-agnostic)

| # | rule | threshold |
|---|---|---|
| R0 | P0 present (headline, logo, CTA); nothing off-canvas | hard |
| R1 | ink clearance from canvas edge | ≥ max(6 px, 4% of short side) |
| R2 | optical side margins balanced (≥ 2:1 formats) | ratio ≤ 2 or Δ ≤ 12 px |
| R3 | CTA label size | ≥ 12 judge-px¹ |
| R4 | headline lines in strips (H ≤ 120) | ≤ 2 preferred, ≤ 3 hard |
| R5 | rag: no widow < 35% of measure; no one-word lines in a 3+ word headline | hard |
| R6 | logo never out-weighs the message | logo ink ≤ 0.8 × headline ink |
| R7 | hierarchy: every other text ≤ headline/1.2, **CTA label included** | hard |
| R8 / R9 | empty band along the long axis / content coverage | within ±5 pts of the **source** |
| R10 | no smudges | visible text ≥ 9 judge-px, else hide |
| R11 | translucent decoration over text or CTA ink | ≤ source overlap + 5 pts |
| R12 | stack rhythm in tall formats | max gap / min gap ≤ 4 |
| R13 | strip text padding, top and bottom | ≥ 12% of H |
| R14 | a ≤5-word headline owns ≥ 50% of the measure on tall canvases | soft |
| G1 / G2 | ground binding (§B4) | hard |

¹ judge-px = px × min(1, 1024 / long side).

**Near-ties (open problem #4)** are broken lexicographically: hard vetoes, then the count of rule violations, then energy. 

### B2. Taste without ground truth (#1): source-relative thresholds

Full inverse optimization looks ill-posed to me:
- One positive example against unbounded negatives leaves about 25 weights unidentified.
- The source is optimal only at *its own* canvas.

The cheap version is proven: **use the source's own metric values as per-design tolerances.**
- The L1 source itself has a 39% empty band and 23% coverage.
- The L2 source puts `deco_circle_2` over 25% of its subhead.

Absolute rules would "fix" the designer's intent. Source-relative rules cut flags by 22–31% and remove exactly those false positives:
- Everyone's "empty bottom" in L1 1080×1350 (38–44%, against 39% in the source) is **faithful, not a defect**. That includes the instance in my own render, so I withdraw that criticism.
- The real defects survive: 160×600 smudges, logo dominance, widows, decorations under the CTA.

Perception already did this for contrast. Do it for every rule.

### B3. Extreme targets (#3): message-first collapse

**Would a designer ship a 4-line, 14 px run-on headline at 728×90? No.** It's a paragraph pretending to be a banner, and beside a 14 px CTA it has no hierarchy (my R1 output fails R4 and R7). **Would they keep only the logo and CTA? Also no.** Policy C (`r2_lb_sheet.png`) is clean but says nothing, and the brief's reference keeps a headline. The policy I now hold:

1. **P0 = {headline, CTA, logo}.**
   - Lower tiers drop first: legal → badges and stickers → subhead → hero → decoration.
   - The logo shrinks to its recognisability floor (visible mark ≈ 0.5H in strips).
   - The CTA label is ≤ headline/1.2 but ≥ 12 judge-px.
   - **The headline gets every remaining pixel.**
2. **Strips cap the headline at 3 balanced lines**, with ≥ 12% H padding.
   - Policy B on L3 at 728×90: **15 px × 3 lines**, CTA label 12 px, product dropped, right margin = min(logo's optical left margin, 32).
   - B passes every rule except the soft "≤2 lines preferred"; A fails three.
3. **Brand-reminder mode**, the *only* case where the headline is absent, and logged.
   - Trigger: headline below floor in ≤ 3 lines with everything else at floor (L3 at 320×50 needs ~10 px).
   - Output: logo | hero | CTA.
   - Inventor's unseen design, with a short headline, *does* fit 320×50 in 2 lines. So the mode only fires on genuinely impossible copy.
4. **Skyscraper (160×600)**
   - The headline must average ≥ 2 words per line. If it can't at its floor, drop the hero first.
   - CTA labels wrap to 2 optically centred lines before going below 12 px.
5. **Stories (9:16)**
   - The headline may gain one line when growing (the brief: 150 px over 2 lines).
   - The message group sits at an optical centre of ≈ 0.45H, with the logo pinned to the top band.
   - Gaps snap to {1, 2, 3}× a rhythm unit in rank order, which fixes the 31–355 px stacks.
   - Soft prior: keep text and CTA out of the bottom 15% (platform UI).

### B4. Topologies beyond stacks (#2): ground binding (`r2_ground.py`, spike `r2v2_*`)

The concept every engine lacks, mine included, is the **ground**: what each text or logo stands on.

A **panel** is a non-background shape with alpha ≥ 0.5, covering ≥ 6% of the canvas, that holds at least one content element above it. Examples: a colour block, a footer bar, a card.

- **G1.** Riders keep their panel. After layout, the panel is re-cut to the union of the riders' ink plus padding, extended to the edges it touched in the source:
  - full-height columns in strips and splits;
  - full-width bands in stacks;
  - cut back so it never slides under non-riders (the hero).
- **G2.** Text standing on the background must land on calm, contrasting pixels of the **exact target crop** (cover = centre crop, emulated). Fallbacks, in order:
  1. relocate it into the calmest band on its own ground;
  2. scrim reuse, i.e. move it onto a contrasting panel;
  3. palette swap to an in-design colour (**gated**: a question for the organisers);
  4. flag it.

**Results**
- **Split colour block**
  - 728×90 goes from an invisible headline to a real leaderboard: an orange panel carries logo, headline, subhead and dark CTA; the product sits far right on dark, its source side.
  - 1200×628 is now close to identity. The panel is 470 px wide instead of 600, so the re-cut should keep the source proportion when there is free space.
- **Photo**
  - 1080×1920: the subhead is relocated 22 px back onto the calm sky.
  - 728×90: no sky exists in the crop, so the footer bar becomes the whole strip and the headline is swapped to white. Clean, but it relies on the gated swap.
- **Honest failures**
  - **Panel takeover** on the photo at 1600×400 and 300×250: the bar covers 86–98% of the canvas and the photo is lost. Fix: cap panel growth at 50% outside strips, and prefer a side panel on wide formats.
  - **Split stories** leave a small hero in a large dark field.

### B5. Furniture and decoration (#6)

- **Rotated stickers and ribbons keep their angle**: the rotation *is* their identity.
  - Placement order: source corner → mirrored top corner → the hero's "shoulder" (≤ 20% overlap with hero ink, 0% with text) → drop.
  - The rotated AABB must stay in-canvas, because the renderer clips rotated corners.
  - "Always dropped" is right only for strips under 120 px tall.
- **Translucent circles are atmosphere:**
  - image-attached → concentric **halo** (reads as intentional in my renders and in perception's);
  - off-canvas bleeders → corner-tangent;
  - text-attached → relocate so the overlap stays ≤ source + 5 pts (R11), else drop.
  - Never a disc around a logo (it looks like a placeholder badge), never under a CTA pill (it looks like a smudge).
- **`cover` is centre-crop only.** We can't choose the crop, so we choose where the type goes inside it (G2 relocation).
- **Ink vs box (#5):** pack by ink; allow box overlap only over fully transparent pixels, behind a structural-safety flag.
- **Hide (#7):** opacity 0 plus colour alpha 0, with an in-bounds parking spot. Never hide a P0 element outside logged brand-reminder mode.

## C. Experiments this round

1. **`r2_rules.py`** over 51 outputs from all agents plus the sources.
   - The sources themselves violate R8, R9 and R11, which led to source-relative thresholds (−22–31% false positives).
   - Limits: the thresholds and roles are mine (`roles.py`), and rotated ink is approximated by the unrotated box.
2. **R1 engine, unchanged, on inventor's unseen design and two new opaque-id designs** (`r2_designs.py`). The busy photo is a *synthetic* fixture: a calm lavender top over high-frequency texture.
   - Unseen: good at 728×90, 320×50 and 1600×400. In stacks the logo lands below the product (a y-sort bug) and left-aligned text sits in centred boxes.
   - Photo and split: catastrophic (see Self).
3. **Ground binding v2** (`r2_run_v2.py`).
   - Fixes: split at 728×90 and 1200×628; photo at 1080×1920 (relocation) and 728×90 (gated swap).
   - New problem: panel takeover on wide and small photo targets.
   - Also adds contiguous panel riders in reading order and a left text axis for left-aligned sources.
4. **Leaderboard policies A/B/C** (`r2_leaderboard_policy.py`): message-first B is the only variant that is both faithful and passes the hierarchy rules.
5. **R1 on 160×600 and stories** (`r2x_*`): exposed my P0-drop bug. Every engine's stack path must assert R0.
