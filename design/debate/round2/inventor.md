# INVENTOR — Round 2: the source is a constraint, not an oracle. Layouts are relations, not templates.

Spikes are in `design/debate/spikes/inventor/r2_*.py`, with renders, sheets and logs in `spikes/inventor/out_r2/`. All of them run from the repo root with `.venv/bin/python`.

## A. Critiques (each backed by a run on a new case)

I ran three things in `r2_crosscheck.py` and `r2_vs_optimizer.py`:
- DESIGNER's `compose.py` and OPTIMIZER's `solver.py`, unmodified, on three designs none of us tuned on. **U** is a 1200×628 split link ad with opaque ids and left-aligned copy. **F1** is text over a busy full-bleed photo. **F2** is an opaque colour panel holding logo, copy and CTA, with a product on the right.
- PERCEPTION's pixel critic on four layout pairs where the better one is obvious by eye.
- JUDGE's proxy scorer on every output produced in this round.

### DESIGNER

**Steal:**
- Balanced wrap: bisect the box width down to the narrowest width that keeps the same line count.
- Cap-height optical placement.
- The imperative-verb CTA cue.
- Halos for decorations.
- "Legible or absent" as the drop rule.

**Most serious flaw:** archetype bands have no concept of a *container*. On F2 the opaque panel is treated as decoration:
- At 1600×400 the panel stays its source width while the centred message grows, so "Golden hour, bottled." spills past both edges of the dark panel (`out_r2/sheet_xc_designer.png`).
- At 1080×1920 the headline is wider than its box by 124 px (JUDGE's proxy flags it).
- At 728×90 the panel is hidden.

Its stack archetype is also underfilled on tall canvases. U at 1080×1920 is a small cluster in the middle of the story.

On the other hand, its U strip (728×90) is the best leaderboard any of us produced.

**Verdict:** the best typesetting layer, but too few grammar types. Merge it into the search core as the "realize" stage.

### OPTIMIZER

**Steal:**
- The exact W_k text frontier.
- **Discrete image tiers.** These are why it fills tall canvases. On U it beat GALLEY at 1080×1920, 1080×1080 and 160×600: headline 129 px, product ×4.18.
- The copy budget.
- PAVA (isotonic regression for vertical faithfulness).

**Most serious flaw:** contiguous partitions of the reading order with no notion of a *bond*. On U at 1600×400 it chooses logo+headline | product | body+CTA, so the product splits the message in half (`sheet_U_galley_vs_optimizer.png`). Its grammar also has only one row of columns of stacks: it can't produce rows of columns, and it has no containers.

**Verdict:** its energy terms beat GALLEY's on tall targets, and I would adopt them wholesale. It needs bonds (consecutive text units can't be split by a picture) and relations.

### PERCEPTION

**Steal:**
- Ink boxes.
- Crello **format priors**, which are exactly what my E2 density experiment lacked (C2).
- Source-relative thresholds. My calm-region detector uses the same idea.

**Most serious flaw:** the pixel critic is blind to structure. On four pairs whose answer is obvious by eye, run with background roles supplied, **it disagreed with the eye 4/4 times** (`crosscheck_log.txt`):

| Pair (eye's choice first) | Critic penalty | What went wrong |
|---|---|---|
| F1 1600×400: calm sky band vs. text over striped trees | 19.1 vs **11.0** | It has no texture/busyness term, and contrast p10 is 2.4–2.7 in both, so text on trees looks fine to it. It then punishes the calm band as "visual weight off-centre". |
| F2 1600×400: panel with nested riders vs. floating island | 112.6 vs **90.6** | It scores every intentional text-on-panel as a 100% "collision". |
| U 1080×1920 and U 1600×400 | 0.03–0.1 apart | Decided by an off-centre term that punishes faithful asymmetric splits. |

This is the hand-weighted v1 critic. D2 calibration can fix its weights, but **calibration can't add features it doesn't have**: host/rider, furniture, texture.

**Verdict:** the critic has to consume the decompiled relations, or it will fight intentional layering. It isn't yet a valid near-tie breaker.

### JUDGE

**Steal:**
- The output contract, the repair pass and the fallback ladder.
- The metamorphic tests. "Target = source canvas gives ≈ the source" is my fixed point, and C2 shows it's also the cheapest taste signal we have.
- The parametric-generator hypothesis.

**Most serious flaw:** its own proxy marks the team's agreed hide encoding (colour alpha 0) as a **HARD "changed color"**. That hit 5 of my outputs and 1 of DESIGNER's. Meanwhile its invariant I10 hides text by z-under-background, which only works when there's an opaque full-bleed background. The hide policy is still unresolved even inside JUDGE's own proposal.

**Verdict:** essential infrastructure. Implement hiding as a policy switch: colour-alpha, z-under-background, or never hide text.

## B. v2 position

The core has converged: a reading-order stream, a discrete set of arrangements, omissions, one type scale found by bisection, and rendering in the loop. I agree with that and would merge GALLEY's and OPTIMIZER's search. GALLEY's 3-level ¶ | / labels are a superset of OPTIMIZER's one-row partitions; OPTIMIZER's energy and image tiers are better. What GALLEY v2 adds is the *program*, the thing that is decompiled from the source, along two axes.

### 1. Relations, not templates (open problem #2)

The galley stays a tree of rows, columns and stacks, but it gains two relation types. The decompiler infers both from containment and pixels, never from a list of layouts.

**HOST/RIDER.** An opaque, ungrouped, non-background shape that contains text is a container.
- Its riders form a **nested galley**, typeset inside the host's cell by the same solver.
- The host bleeds to the canvas edges it touched in the source. Shapes may stretch; images may not.
- At the outer level, the host is just one unit with its own split axis, order and share.
- On F2 this produced a correct split banner, leaderboard, square, 300×250 and story band. v1 (rigid island) and DESIGNER (panel as decoration) both fail visibly.
- The same relation covers a button (pill + label), a photo with text on it, and a product with a badge on its shoulder (the rider's anchor stored in the host's ink coordinates).

**OVERLAY live area.** A full-bleed photo is a host whose *pixels* decide where the galley may go:
- emulate the renderer's exact centre-crop at the target;
- compute busyness;
- set the calm threshold to 1.5× the busyness under the **designer's own text** in the source;
- turn maximal calm rectangles into candidate live areas.

On F1 at 1600×400 it moves the copy into the 120 px sky band that survives the crop.

**Limit, shown honestly:** at 728×90 the crop leaves no calm pixels at all (1%). Nothing short of a source-provided scrim or panel, or hiding copy, can fix that. The host relation then handles the scrim automatically.

Split colour blocks, text over a photo, buttons and stickers all become one mechanism: **typeset a galley inside a host's cell or calm region.** Z-patterns and multi-product grids are already line breaks: a 2×2 grid re-breaks to 1×4 in a banner.

### 2. The source as a constraint (open problems #1 and #4)

At its own canvas, the designer's layout must beat everything the engine could have produced there. Each design gives hundreds of free inequalities `w·φ(source) ≥ w·φ(alt) + Δ`. C2 tests three ways of using them.

**Kept: per-design trust-region calibration of structure and faithfulness weights only**, at runtime, in under 0.5 s per design:
- It repaired every fixed point that the fragile fill weight broke. L2 drift went 6.0% → 2.5%; U went 12.2% → 3.7%.
- U's wide and square outputs inherited the designer's split, and the decision margins grew from 0.006–0.009 to 0.016–0.050.
- This is my answer to near-ties *in the source's own regime*: the source decides.

**Kept: non-separability as a model-deficiency detector.** Under round-1 features, 14 alternatives beat U's source, and calibration could not remove 4 of them for any weights. That pointed straight at a missing feature (stack-in-column vs. separate rows). I added it and the problem became separable (0 left). This belongs in the dev harness: any corpus design the engine can't reproduce at its own canvas is a bug report.

**Kept: dev-time use.** Fit the weights with Bradley–Terry on VLM pairs (PERCEPTION/OPTIMIZER plan) *subject to* the fixed-point constraints of every corpus design. The VLM supplies taste across regimes; the sources guarantee faithfulness.

**Demolished: the source as the whole objective.**
- The source never exercises banner trade-offs. L1's 728×90 CTA drop got no information from it.
- Full per-design calibration *extrapolates*. Designers keep everything at moderate scale, which "reveals" low appetite for type size (w_logs 1 → 0.24–0.44).
- Pure source-relative density shrinks banner type until coverage equals the poster's: L2 728×90 headline ≈10 px under a huge CTA.

Density depends on the format. So use Crello format priors × source deviation, not source density alone.

### 3. Far-regime near-ties and tall canvases (open problem #3)

In the far regime (the unseen story, top 10 within 0.006–0.04), neither the source nor PERCEPTION's v1 critic decides correctly. What fixed it in practice is OPTIMIZER's image tiers plus format priors. So the v2 rule is: **source constraints decide in the near regime; Crello priors and the VLM-fitted critic decide in the far regime, and only after the critic can see relations.**

### 4. Other agents' parts in v2

| Agent | What v2 takes |
|---|---|
| DESIGNER | Typography and optics layer |
| OPTIMIZER | Energy terms and image tiers |
| PERCEPTION | Ink boxes and priors |
| JUDGE | Contract, harness and hide-policy switch |

The fixed-point check is the first metamorphic test.

## C. Experiments (all new in this round)

### C1 — `r2_vs_optimizer.py`: GALLEY vs. OPTIMIZER on U, 6 sizes

All 12 outputs are in-bounds, and each solve takes 0.01–0.14 s.

| Target | Winner | Why |
|---|---|---|
| 1600×400 | GALLEY | Keeps the designer's split, product \| left-aligned copy. |
| 728×90 | Tie | — |
| 1080×1920, 1080×1080, 160×600 | **OPTIMIZER** | Fills the canvas; GALLEY leaves product\|logo pairs and dead space. |
| 300×250 | Split | — |

GALLEY's single real deficit is fill on tall targets. That is an objective problem, not a search problem.

### C2 — `r2_taste.py`: inverse optimisation from the source

**Setup:**
- GALLEY's J becomes w·φ over 18 features.
- At the source canvas, every GALLEY alternative is enumerated: break patterns × omissions × scale variants with the cap lifted, 62–1,792 per design.
- A max-margin inverse problem moves w as little as possible (natural-gradient projected hinge).
- Log: `out_r2/taste_log.txt`. Sheets: `sheet_taste_E1/E2/E3*.png`, `sheet_taste_focus.png`.

| Run | Calibrated | Fixed points | Targets |
|---|---|---|---|
| E1: round-1 weights + fill 0.25 | All weights | L2 repaired (the subhead\|CTA row disappears); U non-separable → missing feature found | L1 728×90 CTA still dropped |
| E2: source-relative density, no caps | All weights | All restored | **Harmful at banners** (10 px headline); story unchanged |
| E3: + `restack` feature, trust region (structure weights only) | Structure weights only | All 4 restored | Wide/square inherit the split with larger margins; banners unchanged; story still a weak near-tie |

The first solver I wrote was numerically unstable: a step size of 8× on small-prior features clipped weights to 0 and made calibration look harmful. Preconditioning fixed it, and every number above is from the fixed run.

### C3 — `r2_topology.py` + `r2_fixtures.py`: host/rider and overlay live area

Sheets: `out_r2/sheet_topo_F1.png`, `sheet_topo_F2.png`.

**F2 (host/rider)** beats v1 on all 5 sizes:

| Target | Chosen layout |
|---|---|
| 1600×400 | panel \| product, share 0.75 |
| 728×90 | panel[logo \| headline \| CTA] \| product |
| 1080×1080 | panel \| product |
| 300×250 | panel \| product |
| 1080×1920 | panel band ¶ product |

The first version shifted the bottle's ink onto the panel copy when clamping its transparent-padded box. I fixed it by limiting the image scale so the box fits with its ink centred in its cell.

**F1 (overlay):**
- 1600×400: picks the calm sky band (busy penalty 0) over the full canvas (busy penalty 8.9).
- Story and 4:5: the full canvas is already calm, so the result is the same as v1.
- 728×90: no calm region exists, so this one is unsolved.

The F1 test photo is synthetic, procedural and used only as a test input. It lives in my folder; `brand_kit` is untouched.

### C4 — `r2_crosscheck.py`: evidence for section A

- DESIGNER on U, F2 and F1.
- PERCEPTION's critic on 4 eye-known pairs: disagreed 4/4.
- JUDGE's proxy on all outputs: 6 HARD "changed color" flags, all from the alpha-0 hide encoding.

Logs: `out_r2/crosscheck_log.txt`, `U_vs_optimizer_log.txt`, `taste_log.txt`, `topology_log.txt`.
