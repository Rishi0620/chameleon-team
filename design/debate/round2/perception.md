# PERCEPTION, Round 2: one ruler for every engine, and where the ruler is wrong

All spike code and outputs are in `design/debate/spikes/perception/r2_*` and `r2_out/`. Engine labels: DES = designer, OPT = optimizer, GAL = inventor/GALLEY, PER = mine, JDG = judge (hand mock, and its `safe_fit` floor).

## A. Critiques of the other four

**DESIGNER**
- **Steal:** "legible or absent", and the per-role elasticity exponents γ. Section E supports γ with data: as canvas area shrinks, weight flows from pictures to words to the action.
- **Taste:** DES has the best-designed banners, eye-best on 3 of 8 tasks.
- **Flaw:** one deterministic answer per aspect band leaves nothing to re-rank when the band rule is wrong.
  - Its L2→300×250 has the smallest designed headline of the field.
  - Its L2→728×90 has a 79% logo×product *box* overlap (section D).
- **Its critique of me stands.** My round-1 generator was the weakest engine: 4th by eye on all three tasks it entered, with an orphaned "Chase" and a 4-line subhead in a 250 px measure.
- **Verdict:** the typography and optics layer.

**OPTIMIZER**
- **Steal:** the exact text frontier plus bisection. OPT is my eye-best on **5 of 8** tasks, making it the most consistently good engine.
- **Flaws:**
  - Box overlaps in 6 of its 7 audited outputs (logo×product 26–38%; logo×badge 45% at 300×250).
  - Cross-type hierarchy (DESIGNER's R6).
  - At L3→160×600 the headline has a 5.5 px x-height at **native** resolution. My critic flagged it; my eye missed it on the 2.25×-upscaled contact sheet.
- **Verdict:** the inner solver.

**INVENTOR / GALLEY**
- **Steal:** break-pattern enumeration. It gives the most *diverse* top-10 on the table, which is the ideal substrate for a verifier.
- **Flaw:** J has no notion of a pixel defect.
  - At U→1080×1920, **4 of its top-5 candidates** set the headline one word per line ("Golden / hour, / bottled.").
  - In blind tests, J's top pick matched my favourite in only 1 of 4 near-tie cases (section C).
  - At L3→1600×400 it keeps all 3 badges and crowds the frame (eye rank 3 of 3 among designed outputs).
- **Its 4/4 critique of my critic** is answered in section B: 3/4 after the round-2 fixes.
- **Verdict:** the candidate generator, but it needs a defect veto.

**JUDGE**
- **Steal:** the contract, the fallback ladder and metamorphic tests.
- **Flaws, each with evidence:**
  1. Its own hand-made leaderboard has the CTA label "Shop the Summer / **Line**" spilling out of the pill. None of the 12 invariants catches a label escaping its container. Add **I13: a group label's ink must lie inside its container shape's ink.** Critic v2.1 now checks this.
  2. `safe_fit` ranks **#1 at L3→1080×1920** under my v2 critic. Uniform scaling maximises every "match the source" statistic (ink share, palette), yet the result is visibly an under-filled island. **The floor must be chosen only by hard-fail fallback, never by a score.**
  3. Hiding text under the background edits z-order (OPTIMIZER's point) and fooled my round-1 critic. Colour alpha 0 keeps z. `r2_hide_leaks.py` checked all **142 intended-hidden elements across 7 tasks and every engine: 0 leak a single pixel**, so both encodings work, and colour alpha is the safer one.

## B. Cross-engine critic: one ruler for all outputs (`r2_cross_engine.py`)

**Method.**
- Inputs: 66 outputs (all engines, plus `safe_fit` and the stretch baseline) across 14 shared tasks.
- Ids are remapped by list order and verified on type, content and asset.
- Every output is re-rendered with the official renderer and scored by **critic v2**.
- Critic v2 uses **pixel-true visibility**: an element is visible only if deleting it changes the render, and its backdrop is the render *without* it.
- It also checks JSON structure, rotated clipping, glyphs over a busy backdrop, and palette.
- Full tables are in `r2_out/tables.md`; labelled sheets are `r2_out/sheet_*.png`.

| task | critic v2 ranking (lower = better) | my eyes |
|---|---|---|
| L2→1600×400 | DES −2.5 > GAL −1.1 > OPT 0.0 > PER 2.3 > safe_fit 15 > stretch 53 | DES > OPT > GAL > PER > safe_fit > stretch |
| L2→728×90 | PER 4.4 > OPT 4.7 > GAL 7.2 > DES 8.6 > safe_fit 72 > stretch 111 | DES > GAL > OPT > PER > … |
| L3→728×90 | JDG-mock 10 > OPT 12.8 > PER 15 > GAL 16.5 > DES 17.7 > safe_fit 161 > stretch 216 | OPT > DES > GAL > PER > JDG-mock > … |
| L1→1080×1350 | DES −4.5 > safe_fit −4.1 > OPT −4.0 > GAL −3.6 > stretch 6.1 | OPT > DES > GAL > stretch > safe_fit |
| L3→1600×400 | GAL 1.3 > OPT 3.2 > DES 4.6 > safe_fit 68 > stretch 131 | DES > OPT > GAL > … |
| L3→1080×1920 | safe_fit −1.7 > GAL 1.9 > OPT 3.9 > stretch 49 | OPT > GAL > safe_fit > stretch |
| L2→300×250 | OPT 2.1 > GAL 9.4 > DES 10.7 > safe_fit 34 > stretch 65 | OPT > DES > GAL > … |
| L3→160×600 | GAL 19.6 > OPT 26.7 > safe_fit 112 > stretch 158 | OPT > GAL > … |

My eye rankings were frozen in `r2_out/eye_rankings.json` *before* any fix. Agreement (`r2_agreement.py`):

| pair type | v2 | v2.1/v2.2 (in-sample fixes) |
|---|---|---|
| designed vs broken | 55/60 = 92% | 59/60 = 98% |
| **designed vs designed** | **12/33 = 36%** (worse than a coin) | **21/33 = 64%** |
| top-1 | 2/8 | 4/8 |

**That calibration gap is the finding: a pixel critic is an excellent floor detector and a poor taste judge.** It failed in five specific ways:
1. **No label-spill feature.** JDG's spilling CTA ranked #1.
2. **Omission over-punished.** It preferred GAL's crowded 3-badge banner, and ranked DES's reference-like leaderboard last of four.
3. **"Faithfulness" stats reward the letterbox island** (`safe_fit` #1 at a story size).
4. **Goodhart.** My own leaderboards rank #1 because they were *selected* by this critic. A selector cannot also be the evaluator.
5. **Eye-side bias.** Upscaled sheets flatter small text. Dev-time VLM labels must be made on native-resolution PNGs.

Fixes:
- **v2.1:** label-spill as a hard fault; under-fill relative to the source; hierarchy by **cap-height**, because Sans has a larger x-height than Serif at the same size, which falsely flagged DES's equal-size CTA; ink-share term removed; optional drop costs halved.
- **v2.2:** source-relative collisions (below).

**INVENTOR's "4/4 disagreement".** INVENTOR ran my *round-1* `critic.py`, which used absolute contrast, had no busy-backdrop term, charged every intended overlap as a collision, and had an off-centre term. I re-ran its exact four pairs on its private photo assets (`r2_inventor_pairs.py`):

| INVENTOR pair (eye choice first) | round-1 | v2.2 |
|---|---|---|
| F1 calm sky band vs text on striped trees | wrong | **right** (5.1 vs 8.9): "glyphs over busy backdrop 0.71" |
| F2 copy on its own panel vs floating island | wrong (100% "collisions") | **right** (−3.2 vs −1.2) |
| U 1600×400 GAL vs OPT | wrong | **right** |
| U 1080×1920 OPT vs GAL | wrong | wrong: it flags a one-word line in OPT's headline |

That is **3 of 4**. INVENTOR's diagnosis was right: the critic must consume relations. The cheapest way to do that is to make them **source-relative**: a collision only counts if those two inks did *not* overlap in the source. Text on its own panel, a badge on a product, and a halo behind a bottle all become intent, not defects.

**DESIGNER's source-relative rules (−22–31% false flags)** are the same principle applied to its 15 typographic rules, so we now agree it should apply to *every* threshold. v2.2 makes contrast, busyness, collisions and under-fill all relative to the source. The L1 "empty bottom" (38–44%, against 39% in the source) is no longer flagged by either of us.

## C. Near-ties, open problem #4 (`r2_near_ties.py`, `r2_tiebreak_policies.py`)

**Setup.**
- GALLEY's own top-10 on U→1080×1920, U→1080×1080, L2→1080×1920 and L3→1080×1350. The J spread across each top-10 is **0.030–0.087**.
- For each case I made a **blind** A–J contact sheet and froze my picks (`near_ties_eye_BLIND.json`) before opening the key.
- I also measured the critic's noise floor: the score change under an invisible 1 px global shift.

**The critic is decisive:** its spread is 2.2–8.4 against a noise floor of ≤ 0.005. Being decisive does not make it right:

| tie-break policy (33 eye-good vs eye-bad pairs) | pairs right | pick = my best | pick in my top-3 |
|---|---|---|---|
| J only | 26/33 = 79% | 1/4 | 3/4 |
| critic continuous score only | 26/33 = 79% | 1/4 | 3/4 |
| rank-sum | 27/33 = 82% | 2/4 | 4/4 |
| **critic defect count first, then J** | **30/33 = 91%** | **2/4** | **4/4** |

**They fail on different candidates.** J happily ranks one-word-per-line headlines as #2–#5. The critic's continuous score likes a side-by-side split that J correctly demotes.

**Who decides:**
1. **Pixels decide defects.** These are countable facts: one-word lines, label spill, new ink collisions, sub-floor x-height, under-fill, placeholder, clipping. Fewer defects wins, full stop.
2. **The generator's energy decides structure** among defect-free candidates.
3. **The critic's continuous score breaks only ties with ΔJ < ε.** It is right about 64% of the time, which beats list order.
4. **Weights come from offline VLM pairwise labels.** About 100 pairs labelled this round already exposed the gross failures, so the budget is hours, not weeks.

OPTIMIZER's order (format prior, then structural distance) is a fine fallback for step 3. Caveat: n = 4 cases, one labeller.

## D. Ink vs box packing, open problem #5 (`r2_ink_vs_box.py`)

**Audit.** I took 24 outputs from all four layout engines on 7 tasks. I counted pairs of visible content elements whose JSON boxes overlap, excluding same-group pairs, pairs that already overlapped in the source, and background/decoration.
- **16 of 24 outputs overlap, and every layout engine does it**, mine included.
- **None of the overlaps involve ink.** All of them are transparent padding, almost always the logo's (30% transparent on each side).
- So the pixels are clean today. The only risk is a JSON box-overlap check.

**Price of playing safe**, measured with exact wrap in a 728×90 strip (logo box 141×44, visible ink at x = 44..97):

| | ink-packed | box-disjoint |
|---|---|---|
| L3 headline | 417 px column → 17 px, 3 lines | 389 px → **16 px** |
| L2 headline | 55 px, 1 line | **52 px** |
| visible logo→headline gap | 16 px | 44 px |

**The payoff is asymmetric:**
- About **5% of type size** is lost if no box check exists.
- About **two-thirds of outputs fail** if one does. JUDGE predicts a generator-based checker, and box IoU is the first thing anyone writes.

**Safe policy:**
1. **Hard rule.** Visible content boxes are pairwise disjoint. Exceptions: same group, pairs already overlapping in the source, and background or decoration.
2. **Gaps are ink-to-ink, realised box-to-box.** `g_box = max(0, g_ink − pad_a − pad_b)`, so padded boxes simply abut.
3. **Pack padded assets on their tight axis.** Padding is anisotropic: the logo is 30% padding left and right, 0.7% top, 27% bottom. A logo *above* a headline costs nothing; *beside* it costs 44 px. This favours DES's "logo over headline", which was the eye-best L2→1600×400.
4. **Shrink-wrap text boxes** to their balanced ink width.
5. **Mirror the forced visible margin onto the opposite canvas edge.** Ink sharing stays a flag, enabled only if the organisers confirm that overlap is judged on pixels.

## E. Style-statistics transfer from the source render, open problem #1 (`r2_style_stats.py`)

**Idea under test.** Measure the source's own statistics (density, whitespace, per-role weight share, type ramp, contrast, brand-colour areas, edges, centroid) and make the target match them, Gram-style. Using the eye-best output of each of the 8 tasks as "a good resize", I asked two questions.

**(a) Invariance: is the stat preserved?** The table shows the median log₂(eye-best ÷ source), with the range across tasks.

| preserved (≈0, tight) | systematically changed |
|---|---|
| type ramp −0.04 [−0.40, +0.03] | ink density **+0.71** (good resizes are about 1.6× denser) |
| headline contrast −0.02 [−0.48, +0.17] | logo weight share **+1.21** |
| centroid x +0.05 | gold area +1.50, white area +0.89, edges +0.84 |

**(b) Preference: among designed outputs, is the one closer to the source preferred?** For 11 of 14 stats it is a coin flip (42–64%). Only centroid-y reaches 73%.

**Verdict.**
- **Raw statistics matching is the wrong objective.** Good resizes are *denser and bolder* than the source, so matching density and whitespace pulls toward the `safe_fit` island. This is section B's failure 3 again, and INVENTOR saw the same thing (E2: a 10 px banner headline).
- **The stats that do transfer** (type ramp, contrast) are ones the converged core already holds by construction: a shared type scale and source-relative contrast.

**The refined version works.** The *changes* are lawful: the log-ratios correlate with the area change.
- CTA weight share: ρ = **−1.00**
- headline weight share: ρ = −0.90
- edge density: ρ = −0.83
- hero weight share: ρ = +0.71

So the right per-design objective is:

`target_stat = source_stat × g(Δarea, Δaspect)`, anchored to Crello format priors.

Here g is a small learned **transfer law**, fitted on dev-time VLM-preferred outputs. This identifies exactly the exchange rates that OPTIMIZER's inverse optimisation proved *unobservable* from the source alone (drop vs size at extreme formats). Status: suggestive on n = 8, and it needs the corpus.

## F. v2 position

**The converged core is right.** I adopt it:
- GALLEY enumerates break patterns × omissions;
- OPTIMIZER's exact bisection solves each one (with containers as brackets);
- DESIGNER's typography and optics, including γ, which section E now supports with data;
- JUDGE's contract and fallback ladder.

**My parts, re-scoped by this round's evidence:**
1. **Pixel verifier, not taste oracle.** Render the top-K and veto on **defects**, all source-relative: label spill (new I13), new ink collisions, sub-floor x-height in native pixels, busy backdrop, under-fill, clipping, placeholder, and hidden-element leaks (0 of 142 today; keep it as a regression test).
2. **Near-tie policy:** defects first, then J, then critic score (section C).
3. **Ink-aware, box-safe packing** with tight-axis orientation (section D).
4. **Objective anchoring:** source invariants (ramp, contrast) + Crello format priors + a learned transfer law (section E). Weights are fitted offline by Bradley–Terry on native-resolution VLM pairs, with each source's inverse-optimisation cone as hard constraints (OPTIMIZER and INVENTOR).
5. **No runtime model.** Unchanged.

**Open problems:**

| # | status |
|---|---|
| #4 near-ties | answered, with evidence |
| #5 ink vs box | answered, with evidence and a price |
| #7 hide encoding | verified pixel-clean |
| #1 taste | partially answered: what the source can and can't supply, plus the transfer-law proposal |
| #2 / #6 topologies, decoration | I contribute only source-relative collision, which makes host/rider layering and halos legal by construction |
