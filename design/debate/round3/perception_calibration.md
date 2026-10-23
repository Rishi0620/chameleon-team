# PERCEPTION — calibration plan (dev-time only; nothing here ships a model)

**Goal:** replace hand-set constants with fitted ones, reproducibly, without overfitting to our own taste or our own critic. The deliverables are JSON files of floats committed to the repo:
- `proto/calib/weights.json`: energy weights w, per-role γ, and critic penalty weights;
- `proto/calib/priors.json`: format priors;
- `proto/calib/critic_thresholds.json`.

The runtime cost is zero: no model is in the container.

## 0. What gets calibrated, and by what

| quantity | owner | fitted from | why that source |
|---|---|---|---|
| format operating points (headline scale, lines, fill, margins, image share per format) | OPTIMIZER energy prior terms | **Crello format priors** (§1) | the source can't tell you what a leaderboard looks like (OPTIMIZER C: exchange rates are unobservable at the source canvas) |
| energy weights w (≈15–25 terms) + γ | OPTIMIZER/DESIGNER | **Bradley–Terry on pairwise VLM labels** (§2), constrained by the **source fixed-point cone** (§3) | VLM labels supply cross-format taste; the cone guarantees faithfulness at the source canvas |
| critic veto thresholds (floors, contrast, busy, collision, spill) | PERCEPTION | **VLM defect labels + VLM transcription test** (§4) | vetoes override the energy, so they are tuned for precision first |
| critic penalty weights | PERCEPTION | BT on the same pairs, near-tie pairs only | the penalty only breaks ties (ΔE < 0.03) |

## 1. Crello format priors, for every catalogue format

**Data.**
- cyberagent/crello v5: 23,302 designs and 67 formats.
- We read **only** the geometry/typography columns (`format, canvas_*, type, left, top, width, height, font_size, text, angle`) by parquet column projection over HTTP. That takes minutes and no images.
- Script: `spikes/perception/r3_crello_priors_all.py` → `r3_out/crello_priors.json`. Round 2 extracted only the 3,204 wide designs; this run covers tall, square and wide.

**Per-design features** (roles are proxies, because Crello has none):

| feature | definition |
|---|---|
| headline | the largest text |
| headline scale | `font/H` and `font/short side` |
| lines | count of the headline's lines |
| centre | headline centre x/y |
| type ramp | 2nd ÷ largest font |
| smallest text | smallest font in px and ÷ short side |
| text area share | text box area ÷ canvas |
| biggest non-background image | h/H, w/W, area, centre |
| content fill | union of non-full-bleed boxes ÷ canvas |
| outer margin | ÷ short side |

**Per format:** median, p25, p75 and n.

**Catalogue mapping.** 17 of the 26 bench sizes have an exact Crello format; the rest borrow the nearest-aspect format with n ≥ 150, flagged `borrowed`. The mapping is in `crello_priors.json["catalogue_map"]`; the observed numbers are in §1a.

**Use in the energy.** For each feature f the energy adds `prior_nll_f = clip(((f − med) / IQR)², 0, 4)`, weighted by `w_prior_f` (fitted in §2). This term supplies the target's absolute operating point, while the source supplies the relative ones (ramp, palette, reading order).

**Caveats.**
- Crello designs are templates, not resizes, and their quality varies. Priors are *soft* (IQR-scaled and clipped).
- Crello's `font_size` for multi-line text boxes is the box font, not the rendered size; that is fine for these medians.

## 2. Pairwise VLM labels → Bradley–Terry

**Corpus (design-level split 70/15/15, seed 7):**
- the 3 official samples;
- JUDGE's 12 bench designs;
- fixtures U, F1, F2, S, B and DESIGNER photo/split;
- **200 Crello designs converted to our schema.** Geometry is copied; embedded layer crops are saved as assets; fonts are mapped to Solstice Sans/Serif by serif-ness; ids are made opaque.

That is about 225 designs, each with 8 targets sampled per design and stratified by band (strip, wide, squareish, tall), from the 26-size catalogue. Total: ~1,800 tasks.

**Candidates.**
- For each task, take the engine's top-K = 6 under **perturbed weights**: 6 draws, `w ~ w0 · LogNormal(0, 0.7)`. This gives diverse but well-formed layouts.
- Dedupe by render hash, and add the safe floor.
- Drop any candidate with a critic veto from the taste pool. Vetoes are not learned from preferences.
- Keep 10% veto-vs-clean pairs as **attention checks** for the VLM.

**Pair selection: 4,000 pairs, chosen actively.**
- 50%: pairs that differ in **one decision**: drop the product or not, subhead lines k vs k+1, topology A vs B, logo tier. These identify the exchange rates.
- 30%: the model's most uncertain pairs (|ΔE| smallest under the current w).
- 20%: uniform random, for unbiased evaluation.

**Why 4,000.** There are about 25 parameters. BT logistic regression wants ≳ 100 informative comparisons per parameter for a stable sign and scale. We pilot 500 pairs, plot held-out accuracy against n, and stop when +500 pairs adds < 1 point.

**Which VLM (offline).**
- **Primary labeller:** a frontier hosted model in the Claude family (current Opus/Sonnet tier), at temperature 0. The hidden evaluator is "almost certainly a VLM", and frontier models are the likeliest family.
- **Second labeller from a different family** (a GPT-4.x-class or Gemini model) on a 1,000-pair overlap, to measure inter-rater agreement and to stop the weights fitting one model's quirks.
- **Optional local pre-filter:** Qwen2.5-VL-7B via MLX on the dev Mac, to discard obviously-equal pairs cheaply.
- None of these runs at scoring time.

**Prompt and protocol.**
- The prompt contains the rubric text verbatim (collisions, readable, on-brand, intentional, holds up, faithfulness).
- Three images: the SOURCE render first, then candidates "Option 1" and "Option 2".
- Each image is a **native-resolution PNG**. Upscaled sheets flatter small text (Round-2 finding). Each image is labelled with its pixel size.
- Output is JSON: per-row preference ∈ {1, 2, tie} plus an overall preference, with a one-line reason.

**Position bias.**
- Every pair is asked **twice, with the order swapped**. Option labels are randomised: "Option 1/2" in one ask, "Left/Right" in the other.
- A pair is kept only if both answers agree. A disagreement becomes a tie (0.5/0.5 in BT) and counts toward a **bias audit**: report P(choose first shown). If it exceeds 0.55, switch to single-image absolute scoring (1–10 per row) for that model.

**Fit.**
- Model: `P(a ≻ b) = σ(β · (φ(b) − φ(a)))`, with ties as half-weights, φ the energy term vector (+ critic penalty terms for the near-tie head), and β = −w (lower energy is better).
- L2 prior toward w0.
- Solved with projected gradient under §3's constraints, as numpy-only Hildreth projection like OPTIMIZER's `r2_inverse.py`.

**Report:**
- held-out pairwise accuracy by design split and by band;
- top-1 agreement;
- cross-family agreement;
- the **learning curve**.

**Acceptance:** held-out pairwise ≥ 70%, against 36–64% for today's hand weights, and no regression in bench p10.

## 3. Source fixed-point cone (hard constraints)

**Constraints.**
- For every train design, enumerate alternatives at the **source canvas**: the engine's own space with the scale cap lifted, ±1–2 type steps, alternative topologies and omissions. This follows OPTIMIZER's 3,403 constraints from 5 designs.
- Require `w·(φ(L) − φ(S)) ≥ m` for each alternative L. Sample ≤ 300 alternatives per design, which gives about 50k constraints for 160 train designs.

**Margin and slack.** Hard for terms the cone identifies; soft hinge with large C otherwise, because some sources are not optimal under any w.

**Non-separable designs.** Designs that stay non-separable are **logged as missing-feature reports**, not silently dropped. This uses INVENTOR's non-separability detector: in Round 2 it found the missing `restack` feature.

**CI test (runs on every commit).** Resize every corpus design to its own canvas: centre drift < 3% and fonts unchanged.

**Runtime per-design calibration** (moderator §7). This happens *only* for structure weights, inside a trust region ‖w − w_pop‖ ≤ ρ, using that design's own cone. It is a tiny LP, run once per design.

## 4. Critic veto thresholds

**4a. Legibility floors by transcription (the most important constant).**
- Render each text element of 300 corpus outputs at a sweep of judge-px: 4–16 px, in both families and both weights, on its own backdrop.
- Present each crop at (a) native size and (b) downscaled to a 1024 px long side.
- Ask the VLM to **transcribe** the text and compute the character error rate.
- The floor per role is the smallest judge-px with median CER < 5%. Report it under both viewing assumptions; if they differ, keep the conservative one.
- This replaces JUDGE's assumed 9/10/14 and my `ILLEGIBLE_VETO = 0.75` margin with measurements.

**4b. Defect labels.**
- 400 outputs, drawn from engine candidates *including* vetoed ones, bench cases and mutations.
- The VLM answers, per output: "Is there a defect a reviewer would circle? Which: unreadable, overlapping, cut off, broken image, illegible on its background, label outside its button?"
- Thresholds are chosen to **maximise recall subject to precision ≥ 95%** per veto code, because vetoes override energy.
- Report the confusion matrix against these labels and against JUDGE's bench proxy (today: 98% case-level agreement, 386 held-out cases).

## 5. Avoiding self-preference (the Round-2 Goodhart finding)

In Round 2 my own outputs ranked #1 under the critic that had selected them. To keep that from recurring:

1. **The selector never chooses the labels.** Pair selection uses the engine energy and decision structure, not the critic score. Critic vetoes only *exclude* broken candidates.
2. **The judge is blind.** The VLM never sees energies, critic scores, engine names or which candidate was selected.
3. **Splits are by design, never by pair.** Every reported number is on held-out designs. Thresholds and weights are frozen before the test split is opened.
4. **Cross-family evaluation.** Weights fitted on family-A labels are evaluated on family-B labels. If accuracy drops by more than 5 points, we are fitting a model's quirks.
5. **Goodhart audit.** Two candidate pools are drawn from the same top-K:
   - `critic-selected`: the argmin of the fitted objective;
   - `random-valid`: a random veto-free pick.
   Compare their win-rates under the *independent* judge. If the selected pool wins much more often under our own objective than under the judge, we have overfitted. The ratio of the two win-rates is tracked over time.
6. **Humans spot-check** 100 random labelled pairs, one team member each. Report the VLM-human agreement; the VLM is the proxy for the hidden judge, but humans catch systematic VLM blind spots.

## 6. Reproducibility and cost

**Caching.** All VLM calls are cached in `calib/labels/*.jsonl`, keyed by `sha1(prompt_version, model, image hashes, order)`. Re-runs are free and deterministic. Seeds are fixed: corpus split 7, weight draws 11, pair sampling 13.

**Cost estimate.** 4,000 pairs × 2 orders × 2 families on the overlap gives roughly 10k calls. Each call carries 3 images (about 1–2.5k image tokens) plus about 700 text tokens, so roughly 30M input tokens. That is tens of dollars on current hosted pricing and 2–4 hours wall time at moderate concurrency. The local Qwen pre-filter cuts this further.

**Published artefacts:**
- labels (CC-BY);
- `weights.json`, `priors.json`, `critic_thresholds.json`;
- the scripts.

These are plain floats, so there is no model-size or approved-list issue.

**Timeline (person-days):**

| step | pd |
|---|---|
| D1 Crello priors (done; extend features) | 0.5 |
| D2 converter and corpus | 1.5 |
| D3 candidate generation and pair selection | 1 |
| D4 labelling pilot and bias audit | 0.5 |
| D5 full labelling | 0.5 wall |
| D6 BT + cone fit and ablations | 1.5 |
| D7 floors via transcription and veto thresholds | 1 |

## 1a. Crello priors, observed (`r3_out/crello_priors.json`)

(filled from the run log below)
