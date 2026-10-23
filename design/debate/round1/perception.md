# PERCEPTION: render it, look at it, then choose

Agent: PERCEPTION (pixels, CV, ML). Spike code and outputs are in `design/debate/spikes/perception/`.

## 1. Core idea and the main insight

**Core idea.** The judge never reads our JSON layout. It looks at a PNG made by a renderer that is deterministic, in-process and already vendored. So the engine should look at the same thing. Every candidate layout gets rendered with the official code path and graded on its pixels by a fast *pixel critic*. The critic's thresholds are set relative to the source design, and its weights are learned offline from a frontier VLM. At runtime there is no neural model at all: perception is classical CV plus about 25 learned floats.

**Main insight.** The box geometry in the JSON is not what the judge sees, and the gap is large and measurable:
- **Ink is not box.** The bottle's visible ink is only 43% × 69% of its pixel box. The logo's ink is 40% × 72% of its box, and the ink centre sits 13% of the box height above the box centre. White wordmark letters make up 60% of the logo's ink. If you lay out and align by box, the logo floats about 60 px away from the left margin of a 728 px banner, and when "centred" it looks 8 px too high.
- **The renderer ignores text `opacity`** (spike S0). `opacity: 0` hides images and shapes, but text with `opacity: 0` still renders at full strength: 4,545 changed pixels, identical to `opacity: 1`. Only the alpha in the colour (`rgba(...,0)`) hides text. Any team that "drops" low-priority text with `opacity: 0` will ship visible clutter and never find out, because nobody checks the pixels.
- **Text box height is ignored, and overflow is not clipped.** A missing asset renders as a grey box with the words "missing asset". The PNG is never upscaled (`max_size` is 2048, so a 728×90 banner is judged at 728×90). Readability therefore has to be measured in output pixels, not in points.

So the engine should optimise what the judge sees: render, measure, choose.

## 2. Architecture / pipeline

```
source + target
  │
  ├─ P0  Asset perception (once per asset, cached by hash)
  │      alpha ink bbox, ink centroid, fill ratio, blob count, colourfulness, dominant colours,
  │      "unseen" flag if the file is absent; for cover images: exact renderer centre-crop at the
  │      candidate box aspect → luminance map, busyness map, saliency-retained score
  ├─ P1  Role inference (no ids): geometry + typography + z + groups + P0 pixel stats
  │      → soft roles + priority ladder (headline > logo > CTA > hero > subhead > badge > sticker > legal > deco)
  ├─ G   Candidate generator: aspect-bucket archetypes × variants (which optional roles are shown,
  │      scale steps, alignment, order) + a "source-faithful" candidate (uniform fit + reflow).
  │      Each candidate is solved in GEOMETRY: exact text fit (skia widths, renderer's wrap),
  │      ink-aware image placement, rigid groups, hide() for dropped roles.
  ├─ S1  Cheap pre-screen (no rendering): box/ink-rect overlaps, text fit, drop costs → keep top K≈12
  ├─ S2  Render + pixel critic (official renderer code, in process): full layer, under-text layer
  │      (render_text=False), cached per-element solo alpha masks → ~20 features → score
  ├─ S3  Local refinement of the top 3 (coordinate descent: font size, gaps, snaps), re-rendered
  └─ V   Verify: official render_design_to_png + structural self-check + hard vetoes;
         fall back to the safest candidate if anything trips
```

Offline only (dev machines, never in the container):
- **D1** Converter from Crello to the CHAMELEON schema. This gives us a corpus of hundreds of real designs (photos, light backgrounds, real logos) to test against, instead of our three Solstice samples.
- **D2** Judge distillation. A frontier VLM labels pairs of candidates against the exact rubric text. Fitting a Bradley-Terry / logistic model on feature differences gives the critic weights.
- **D3** Crello layout priors per format. We extracted these in about 4 minutes by reading only the geometry columns (spike S5), and the resulting file is 2.6 MB.

## 3. Key algorithms

### 3.1 Ink-aware placement (optical alignment)
```python
def ink_stats(asset):                       # cached; contain-fit is emulated exactly as assets._fit_image
    a = alpha(asset); x0,y0,x1,y1 = bbox(a > 8)
    return ink=(x0/w, y0/h, x1/w, y1/h), fill=mean(a[y0:y1,x0:x1] > 8), blobs=cc_count(a > 8)

def place_by_ink(el, box_h, anchor):        # box keeps the SOURCE aspect (proportion check)
    bw = box_h * el.w/el.h; s = min(bw/asset.w, box_h/asset.h)        # contain scale
    ox, oy = (bw - asset.w*s)/2, (box_h - asset.h*s)/2               # letterbox offsets
    ink_rect = (ox + s*asset.w*ink.x0, oy + s*asset.h*ink.y0, ...)   # visible extent inside the box
    box.xy = anchor - ink_rect.anchor_point                          # align/centre the INK, not the box
    box.xy = clamp_inside_canvas(box)                                # the box must stay on canvas
```
Spacing, alignment snaps and "centred" are all computed on ink rects. Boxes may overlap only where both boxes are fully transparent, and only when space is tight (strip formats). The critic checks this on solo alpha masks.

### 3.2 Exact text fit (what the renderer will really draw)
```python
def fit_font(el, W, H, fs_max, fs_min):
    # binary search; uses renderer.converter.wrap.char_widths/wrap_text (same skia font lookup)
    while hi - lo > 0.25:
        fs = (lo+hi)/2; lines = wrap_text(el.content, char_widths(..., fs), W).split("\n")
        ok = len(lines)*fs*el.line_height <= H and max(line_widths) <= W   # no word overflow
        lo, hi = (fs, hi) if ok else (lo, fs)
    return lo
```
Text box `height = n_lines*fs*lh` (honest JSON). Group labels are centred in their pills with skia cap-height and ascent metrics.

### 3.3 Hide (the only honest "drop" that renders)
```python
def hide(el):                       # ids kept, still in bounds, aspect kept
    el.opacity = 0
    if el.type == "text": el.color = rgba(r, g, b, 0)   # renderer ignores text opacity (S0)
    el.box = clamp_in_canvas(proportional_position(el), keep_aspect=True)
```
An `unseen_image` (asset missing from disk) is hidden only if small and near an edge. Otherwise it keeps box geometry, because the scorer may have the file.

### 3.4 Pixel critic (features measured on rendered layers)
```python
full  = render(c)                         # what the judge sees
under = render(c, render_text=False)      # pixels beneath glyphs
mask[e] = solo_render(e, transparent).alpha > 40     # cached by (canvas, element) key
for text t:    contrast_p10(t)  = p10 WCAG ratio of colour(t) vs under[mask[t]]
               xheight_px(t)    = skia fXHeight(font, fs)             (output pixels)
               busy_under(t)    = edge density + local std of under[dilate(mask[t])]
               cutoff(t), overflow(t) from the real wrapped line count
pairs:         ink_collision(i,j) = |mask_i ∧ mask_j| / min(|mask_i|,|mask_j|)  (skip same group, deco, bg)
global:        hierarchy  = no text out-salient the headline; rank corr. of text salience vs source
               ink_share  = L1(share of foreground ink per element, source vs candidate)
               palette    = colour-histogram distance(source render, candidate render)
               balance    = ink centroid offset vs source; alignment = ink-edge clustering
               reading_order = Kendall τ of (y, x) order vs source
               placeholder_visible, drop_cost[role], prior_nll(headline scale/zone | format)
score = Σ w_k · f_k   (weights from D2);  hard vetoes: off-canvas, aspect > 5%, unreadable text
        that is not hidden, visible placeholder, ink collision above a threshold
```
**Source-relative thresholds.** In the source design, the brand's own CTA (white on orange #E86A3A) measures **3.20:1**, which fails WCAG AA. A critic using the absolute 4.5 bar would punish the designer's own brand choice. So thresholds are `min(absolute, 0.95 × source value)`, with a floor of 3.0. The source render is our best reference for what the designer intended.

### 3.5 Search (anytime, budgeted)
```python
cands = generate(src, tgt, roles)                    # 30–80 geometric candidates
cands = sorted(cands, key=prescreen)[:K]             # K≈12, no rendering
scored = [(critic(c), c) for c in cands]             # rendered
best = refine(top3(scored), steps=20, critic)        # ±font, ±gap, snap; re-render each
return verify(best) or safest_fallback(src, tgt)
```

### 3.6 Judge distillation (offline)
```python
pairs = sample_pairs(candidates over D1 corpus × catalogue targets)    # ~3–5k pairs
y = frontier_vlm("Which better satisfies <rubric row>? A/B", render(a), render(b))
w = logistic_regression(features(a) - features(b), y)                  # Bradley–Terry
report held-out pairwise agreement; ship w (~25 floats) as JSON
```

## 4. Walk-through on the three samples

**Role inference (spike, no ids used): 32/32 roles correct** on the samples. This includes the L1 text-only CTA (short, bold, accent colour), the L3 rotated ribbon as a sticker, the L3 missing watermark as `unseen_image`, and logo vs. hero from alpha fill (logo 0.15, bottle 0.79). It is n=3 and needs the D1 corpus before anyone should trust it.

**L1 1080×1080 → 1080×1350.** This is a near ratio, so the source-faithful candidate wins. The background cover-fills 1080×1350 (scale 0.9, no crop). The logo stays at the top, aligned on its ink. The headline is scaled up (fit at about 66–72 px) and centred in the extra height. The perception detail is the CTA, which is orange text on the background. Its contrast depends on how far down the canvas it sits (S4c): p10 is **3.41** at y≈540 (the warm glow), **4.39** at y≈800 and **5.13** at y≈950. The source has 4.22. So the critic pushes the CTA down into the darker lower field, and the extra 270 px goes above it. The result is more faithful and more readable.

**L2 1080×1080 → 1600×400.** This is a strip archetype: [logo | bottle | headline + subhead | CTA pill], with the translucent circles kept as in-bounds corner accents. Out of 72 rendered candidates, spike rank 1 was: logo ink at the left, bottle box 392×392 (ink ≈168×270), "Chase the Light" at 59.6 px (x-height 29.8 px, inside the format prior), subhead at 29.5 px, CTA label at 30.8 px, and the NEW FLAVOR badge hidden. Self-check is clean and image aspects are kept at 0.0% deviation. Rank 72, which the critic rejected, had a giant "NEW FLAVOR" pill above the bottle and a 10 px headline, flagged as "hierarchy inverted ×2" (see `out/s4b_contact_sheet.png`). The full engine would add a wider text column (subhead in 1–2 lines, not 4), a smaller logo (ink-share already penalises it, 0.27), and the badge on the bottle's shoulder when its ink fits without collision.

**L3 1080×1350 → 728×90.** Spike rank 1 (out of 72): logo ink at x≈8 (the box borrows its own transparent margin), a small bottle (ink ≈38×61), the 140-character headline at 15.4 px in 4 lines, and the CTA pill on the right at a 15.4 px label. Hidden: subhead, 3 badge groups, the ribbon group, legal text, and the missing watermark. The text elements are hidden with alpha-0 colour; without that, the shown text would still render. Self-check is clean. This matches the brief's reference leaderboard, with one difference: our headline cannot be "Chase the Light", because the content is fixed.

The Crello prior tells us what to change. Across 317 real leaderboards, the largest text has a median font size of 0.30·H (27 px) and is 1–2 lines. Our headline cannot reach that. With the bottle shown, the column is about 380 px wide, which fits 16 px in 3 lines. Hiding the bottle gives about 470 px and 19.5 px; the ceiling is 20.5 px. A prior-calibrated critic therefore trades the bottle for a 22% bigger headline. That is a decision made with data, not taste. Legal text at 728×90 would be under 9 px (below the Crello p25 for the smallest leaderboard text), so we hide it rather than show an unreadable smudge.

## 5. How it scores against each rubric row

| Rubric row | Mechanism | Measured proxy |
|---|---|---|
| No unwanted collisions / text on busy image | Ink-mask collisions, skipping same-group and decoration pairs; busyness under glyphs; calm-region placement | `ink_collision`, `busy_under` on rendered pixels |
| Readable (size, contrast, nothing cut off) | Exact wrap fit; x-height in output pixels; contrast vs the under-text layer; cut-off from the real line count | `xheight_px`, `contrast_p10` (source-relative), `cutoff` |
| On brand (colours, fonts, logo intact) | Fonts and colours untouched (hidden text keeps RGB); logo never hidden or cropped; logo ink contrast-checked like text (60% of it is white) | `palette` distance, logo ink contrast |
| Looks intentional (alignment, spacing, hierarchy) | Ink-based alignment and centring; hierarchy and widow terms; format priors | `hierarchy`, `alignment`, `ink_share`, `prior_nll` |
| Holds up everywhere | Behaviour checked on a Crello corpus of hundreds of designs; vetoes plus a safe fallback; never crashes on unseen assets | Crash-free rate; critic score distribution per aspect bucket |
| Speed and reliability | Pre-screen to K≈12 renders, cached masks and assets, time-boxed search | 64–194 ms per rendered candidate (native, S4b) |
| Faithfulness | Source-relative thresholds; ink-share, reading order and palette vs the source render; a source-faithful candidate always in the pool | `ink_share`, Kendall τ, `palette` |

## 6. Risks and mitigations

1. **Emulated amd64 runtime.** Native arm64 numbers: 27–82 ms per official render (S2) and 64–194 ms per fully critiqued candidate with the mask cache (S4b). We have **not measured** under Docker emulation (the Docker daemon was not running here). Budget for a 2–5× slowdown, more if the platform falls back to QEMU. Mitigations: pre-screen to K≈12, an asset decode/resize cache, skipping the PNG encode in the loop (read the skia surface directly), and an anytime time cap per design. Expect about 2–6 s per design.
2. **Critic mis-calibration.** This is the main risk, and the spike demonstrated it. The first hand-weighted critic chose "Chase / the / Light" on three lines with the subhead hidden. Adding hierarchy, widow and ink-share terms fixed it. Mitigations: D2 distillation with a held-out agreement KPI, hard vetoes, a fixed regression contact sheet reviewed by humans, and a source-faithful fallback.
3. **Unknowns in the structural checker.** We don't know whether (a) `opacity: 0` counts as "kept" and (b) a text colour with alpha 0 counts as a colour change. Mitigation: ask the organisers in week 1. If either is disallowed, the fallback is "minimise": keep the element at the smallest still-legible size in a corner slot, and the critic's drop cost becomes a clutter cost. Transparent-margin box overlaps are behind a flag in case box-overlap is checked structurally.
4. **Asset pixels unavailable at runtime.** If a hidden design references assets not in our image, we treat the box as opaque. Missing pixels never crash us.
5. **Overfitting to Solstice.** All three samples share one dark background, so contrast is never stressed: white text is ≥6.9:1 everywhere (S3). The D1 corpus brings in light, photographic and busy backgrounds. For `cover` photos, the renderer always centre-crops, so the box aspect is our only lever. A "saliency retained" score (spectral-residual saliency mass inside the crop) picks box aspects that keep the subject.
6. **Model approval and size limits.** These don't apply to our runtime path: no neural model ships. That is deliberate.

**What I reject, and why:**
- **A small VLM as a runtime critic** (SmolVLM, Moondream, Florence-2, Qwen2.5-VL-3B). It would be CPU-only under emulation (seconds to minutes per call), the approved model list is still TBD, the image would grow by 1–4 GB, and small VLMs are poor at pairwise judgements between near-identical layouts. Everything they could catch (overlap, tiny text, low contrast) the pixel critic measures exactly and deterministically. Florence-2-base or Tesseract OCR as a legibility oracle is a possible later add-on, not core.
- **LayoutDM / LayoutFormer++.** They output boxes per element type, with no content knowledge for text fitting, groups or z-order. Too much integration risk for stage 1; maybe for the finale.
- **Crello as a generative layout model.** No role labels and no cross-size pairing. Its value is as **priors**, a **test corpus**, and **teacher-labelled training data for the critic**.

## 7. Build plan (2–3 people)

| Week | Person A (geometry) | Person B (perception and critic) | Person C (data and ML) |
|---|---|---|---|
| 1 | Text fitter, `hide()`, rigid groups, 6 aspect-bucket archetypes (4 pd) | Asset ink stats, background maps, role inference, critic v1: contrast, x-height, collision, cut-off, placeholder, hierarchy (4 pd) | Crello→CHAMELEON converter and corpus, run harness, contact sheets (4 pd) |
| 2 | Variants, pre-screen, refinement, safe fallback (5 pd) | Critic v2: alignment, spacing, palette, reading order, busy-under, source-relative thresholds; speed work (4 pd) | Priors extraction (done in S5) and per-format targets; Docker amd64 timing on M-series (3 pd) |
| 3 | Fix failure clusters from the corpus (5 pd) | Hard vetoes, parity test of in-process vs official render (2 pd) | D2 pair labelling with a frontier VLM, Bradley-Terry fit, held-out agreement report (5 pd) |
| 4 | Robustness fuzzing over the catalogue sizes × corpus; README; freeze | | |

Week 1 alone gives a working engine (archetypes plus hand-weighted critic v1 produced the spike results). Weeks 2–3 add calibration. With only two people, cut D2 and tune hand weights against the contact sheet.

## 8. Spike evidence

All runs used `.venv/bin/python` on the M-series laptop (native arm64). Files are in `design/debate/spikes/perception/`.

- **S0 `s0_opacity_probe.py`: text opacity is ignored.** Changed pixels: text `opacity 1` 4,545; text `opacity 0` **4,545**; colour alpha 0 **0**; colour alpha 0.3 4,415 (faded); image `opacity 0` 0. Hiding text needs colour alpha.
- **S1 `s1_ink_boxes.py`: ink boxes.**
  - Bottle 800×800: ink (230,130)–(571,681), 43%×69% of the box, centred, fill 0.79, 10 blobs.
  - Logo 900×300: ink (268,2)–(632,218), 40%×72%, ink centre offset −13.3% vertically, fill 0.15, 23 blobs, 60% of the ink is white.
  - Background: RGB, no alpha.
- **S2 `s2_render_timing.py`: render cost** (median of 7, full resolution, convert + rasterise):
  - L1 1080×1350: 82 ms
  - L2 1600×400: 69 ms
  - L3 728×90: 27 ms
  - Downscaled previews barely help (56–57 ms), because conversion dominates (asset decode and LANCZOS resize every call), which means caching helps a lot. Renderer import: 383 ms, once.
- **S3 `s3_bg_calm_map.py`: background perception per target crop.**
  - Busyness is high on only about 1–8% of the area (the dots).
  - White text contrast is ≥6.9:1 against the local mean everywhere, and 3.7:1 directly over a dot.
  - Orange text passes AA on only 52–80% of the area, failing near the glow.
- **S4a `s4a_critic_baselines.py`: the critic separates baseline from source.**
  - Uniform stretch: L3 penalty 151.7 (every text x-height ≤1.3 px, placeholder visible); L2 21.9 (subhead and CTA x-heights 4.5–4.9 px).
  - The brand's own CTA measures 3.20:1, hence source-relative thresholds.
  - Render plus full critic: 0.1–0.86 s uncached.
- **S4b `s4b_render_in_loop.py` + `critic.py` + `roles.py`: render-in-the-loop end to end.**
  - Setup: 72 candidates per banner, roles inferred without ids, every candidate rendered and critiqued.
  - Cost per candidate with the mask cache: **L3 64 ms, L2 194 ms** (4.6 s and 14 s total).
  - The winners pass `engine.main.self_check` cleanly with 0.0% aspect deviation.
  - The losers are rejected for the right reasons: badge/headline ink collisions, hierarchy inversion, unreadable labels.
  - Contact sheet: `out/s4b_contact_sheet.png`.
- **S4c (inline): position-dependent contrast for L1** at 1080×1350. The orange CTA's p10 contrast is 3.41 at y=540, 4.39 at y=800 and 5.13 at y=950. L3 headline fit: a 380 px column gives 16 px in 3 lines, 470 px gives 19.5 px, and the ceiling is 20.5 px.
- **S5 `s5_crello_priors.py`, `s5b_leaderboard_stats.py`: Crello priors without the 18 GB download.**
  - Parquet column projection over HTTP read 23,302 designs' format, size and geometry in about 2–4 minutes and kept 3,204 wide/odd-format designs (a 2.6 MB artefact).
  - Format counts: Leaderboard 317 (all 728×90), Email header 444, Facebook cover 1,458, Skyscraper 320.
  - Leaderboard priors: largest text median 0.30·H, 1 line (p75: 2); smallest text median 12.4 px (p25: 9 px); biggest non-background image height median 1.0·H; headline centre-x in the left third 45% of the time and middle 32%.
  - No explicit cross-size pairing field exists.

**Bottom line.** A render-measure-choose loop is affordable today (tens to hundreds of milliseconds per candidate), catches failures that box geometry cannot see (ink, opacity, overflow, placeholders, contrast), and needs no runtime model. The ML belongs offline: distil the judge into the critic's weights and mine Crello for priors and test designs.
