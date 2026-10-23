# PERCEPTION — Round 3 build notes (`proto/critic.py`)

## What I built

| file | what |
|---|---|
| `proto/critic.py` | `critique(source, output, info, render_png_path=None) -> {"vetoes", "penalty", "features"}` |
| `proto/tests/build_critic_pairs.py` | builds the labelled set `proto/tests/critic_pairs.json` (+ `tests/data/*.json`) |
| `proto/tests/test_critic.py` | parity, veto precision/recall, pairwise agreement, timing, never-raise → `tests/critic_eval.txt` |
| `proto/tests/critic_vs_bench.py` | **held-out** check vs JUDGE's independent bench proxy (386 cases) → `tests/critic_vs_bench.txt` |
| `proto/tests/_disagree_sheet.py` | renders disagreement cases with their vetoes, for eyeballing |
| `round3/perception_calibration.md` | the dev-time calibration plan (Crello priors, VLM pairwise labels, Bradley–Terry with the source cone) |
| `spikes/perception/r3_crello_priors_all.py` | Crello format priors for **all** formats (tall, square and wide), mapped onto the 26-size catalogue |

## Design of the critic (what it does, and why)

**Its main job is vetoes.** Round 2 showed a pixel critic is good at broken-vs-designed and bad at designed-vs-designed. The penalty is secondary: per OPTIMIZER's pick order it only breaks ties with ΔE < 0.03. Every check is source-relative, meaning "worse than the designer's own render", and relation-aware.

| veto code | fires when | relation / source rule |
|---|---|---|
| `RENDER_CRASH` | text w/h ≤ 0, a non-rgba colour string, or NaN geometry. The official renderer would crash. | checked before any pixel work |
| `HIDDEN_LEAK` | an intended-hidden element (in `info.hidden`, opacity 0, or text colour α 0) still renders ≥ 20 px after occlusion | opacity-only text hiding leaks; the renderer ignores text opacity |
| `PLACEHOLDER` | a visible image whose asset file is missing | — |
| `CLIPPED` | text lines run below the canvas, text ink runs past a side, or > 2% of a rotated element's ink is outside the canvas | — |
| `TEXT_OVERFLOW` | a line is wider than its box (letter-spacing included, since the renderer draws it but its wrap never measures it) | — |
| `SPILL` | > 1% of a rider's or group label's ink lies outside its host or group shape | only counts if worse than the source |
| `INK_COLLISION` | drawn ink of two flow elements overlaps by ≥ max(24 px, 1% of the smaller ink) | skipped for the same group, host↔rider (`info.containers`), background/decoration/texture, and pairs whose ink already overlapped in the source |
| `ILLEGIBLE` | judge-px < 0.75 × floor | floors in judge px (px × min(1, 1024/long side)): headline 12, cta 11, subhead/body 10, badge 9, legal 8. The floor is lowered to 0.9 × the source's own judge-px. |
| `LOST_BACKDROP` | contrast p10 (rendered glyph vs underlay) < 0.55 × min(WCAG need for its size, source's own) and < 3.0 (small text) / 2.0 (≥ 18 judge-px); or < 1.5 outright | the brand's own 3.2:1 CTA stays legal |
| `BUSY_BACKDROP` | edge density in a ring around the glyphs > 0.25 and > 2 × source + 0.10 | — |

**Penalty terms (soft):** contrast and busy deficits below the veto line, small-text band (0.75–1.25 × floor), one-word headline line, hierarchy (cap-height of a non-headline > 1.1 × headline), under-fill relative to the source's content block, near-collisions, text box overflow, and newly edge-touching ink.

**Cheap.**
- There is no PNG round-trip and no per-element "without" render.
- Images and shapes come from a decoded-skia-image cache built with the *same* PIL fit/rasterise code and the *same* skia draw calls as the official renderer.
- Text masks come from small cropped renders, cached by element.
- Each candidate costs one underlay pass, one full pass (skipped if `render_png_path` is given) and small text passes.
- The source analysis is cached by content hash.

**Never raises.** Internal errors return `{"vetoes": [], "penalty": 0, "features": {"error", "trace"}}`. This is tested with `output=None`, empty elements, a 0-width text (which becomes a `RENDER_CRASH` veto rather than an exception) and `info=None`.

## Results (all numbers from `tests/critic_eval.txt`, `tests/critic_vs_bench.txt`)

**Render parity.** The critic's in-process replica matches `render_design_to_png` exactly: max |diff| = **0** on 4 designs, including F1's busy photo and a rotated ribbon.

**Speed** (native arm64, warm):

| measurement | ms per call |
|---|---|
| labelled set (82 calls), median | 47 |
| labelled set, p90 | 165 |
| bench (386 calls), median | 49 |
| bench, p90 (canvases ≥ 1920 px, e.g. 2560×1440) | ~185 |
| bench, max | 470 |

The first call per source costs 0.3–1 s. Expect 2–5× slower under amd64 emulation.

**Labelled set** (`critic_pairs.json`): 82 outputs (25 defect / 57 clean), 125 pairs (52 defect, 73 taste), built from four sources:
- my Round-2 eye rankings and per-output defect labels;
- INVENTOR's 4 eye-known pairs;
- my BLIND near-tie picks (GALLEY candidates, regenerated);
- 9 synthetic mutations, one per veto type.

| | thresholds as in the brief (v0) | final (two margins added, **in-sample**) |
|---|---|---|
| veto precision | 25/35 = **71%** (10 FP, all `ILLEGIBLE` at ~0.9 × floor, one `LOST_BACKDROP`) | **100%** (25/25) |
| veto recall | 25/25 = **100%** | **100%** |
| per kind | all 8 kinds 100% recall | same |
| defect pairs | 50/52 | **52/52** |
| taste pairs | 48/73 | **48/73 = 66%** (R2 cross-engine 17/37 = 46%; blind near-ties 29/33; INVENTOR 2/3) |
| INVENTOR's 4 pairs | — | **3/4** (round-1 critic: 0/4); the remaining miss is a taste pair |

**Read the "final" column with care.**
- The two margins were tuned on this same set: `ILLEGIBLE_VETO = 0.75 × floor`, and `LOST_BACKDROP` being size-aware with a 2.0/3.0 guard. So 100/100 is in-sample.
- The honest out-of-sample number is the held-out bench check below.
- The taste numbers confirm Round 2: **do not let the critic penalty decide designed-vs-designed.**

**Held-out: 386 bench cases.**
- The cases are DESIGNER outputs on the 12 adversarial bench designs + 3 samples × 26 sizes. The critic was never tuned on them.
- The comparison is JUDGE's independent proxy, so this is agreement between two automated raters, not accuracy.

| | both flag | critic only | bench only | neither | agreement |
|---|---|---|---|---|---|
| before the bug fix (identical thresholds to v0) | 113 | 0 | 8 | 265 | **98%** |
| after | 116 | 4 | 5 | 261 | **98%** |

I eyeballed every disagreement (`tests/data/disagree_sheet.png`):
- **1 real critic bug.** At S10 → 320×100 the CTA pill sits on the logo. Occlusion had removed the logo's covered ink from its mask, so no overlap was seen. Fixed: collisions now use *drawn* ink. That fix surfaced **4 real collisions the bench misses**: a pill over the wordmark's last letter at 320×100 on S01, S07 and S12, and a divider line through the product on S07 600×200.
- **5 bench-only `low_contrast`.** These are mild drops (p10 2.7–3.7 vs source 4.2–4.6), for example L1's orange CTA on the skyscraper, which is readable by eye. The critic deliberately penalises rather than vetoes them; vetoes must be precise because they override the energy.
- Fixed along the way: S02 → 1584×396 has a dark subhead over a busy photo at 2.31:1 for 11.6 judge-px. The bench was right, and the size-aware contrast rule now vetoes it.

## Known limitations

1. **Judge viewing resolution is unknown.** The floors assume a 1024 px long side (JUDGE's assumption). This is the single most consequential constant. `perception_calibration.md` §4 calibrates it by VLM transcription error vs judge-px.
2. **Busyness is edge density.** There is no texture model. It caught F1's striped trees (0.72 vs source 0.00), but a smooth-but-patterned photo could slip through. The calm-region placement (INVENTOR's `overlay.py`) is the primary defence; this veto is the backstop.
3. **Text over a non-background image counts as a collision** unless the engine declares it (requested in REQUESTS.md #2) or the source had it.
4. **Roles.** The critic trusts `info["roles"]`. Its built-in fallback is minimal, so the floors (headline vs legal) depend on the engine's role inference.
5. **The labelled set is small and my own.** 25 defects; one eye for most labels; INVENTOR's 4 pairs are the only second labeller. The calibration plan replaces this with VLM labels across model families.

## Requests filed (proto/REQUESTS.md, PERCEPTION)

1. `RENDER_CRASH` should be contract-hard.
2. Overlay riders on a hero should be declared in `info["containers"]`.
3. Keep `info["roles"]` and `info["hidden"]` complete.
4. Pass `render_png_path` when the PNG already exists.
5. Budget `TOP_K × 50–200 ms` for the critic.
