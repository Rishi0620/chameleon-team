# JUDGE: score like the scorer, break it like QA

## 1. Core idea and the one insight that matters

**Core idea.** Treat stage 1 as a scoring problem with a heavy failure tail, not as a layout-beauty contest. The engine generates a few candidate layouts, repairs each one against a strict output contract, renders the survivors in-process with the official renderer, and returns the best one according to an in-engine critic. A layout that is structurally guaranteed to be safe is always in the candidate pool, so the worst case is "plain but correct", never "broken".

**The insight.** The scorer looks at two artifacts that often disagree: the JSON boxes, which the structural checker reads, and the rendered pixels, which the VLM reads. The vendored renderer opens that gap wider than anyone expects. In my spikes:

- It **ignores `opacity` on text**: opacity-0 text renders fully visible.
- It ignores the text box height.
- It draws `letter_spacing` that its own wrap step never measured.
- It draws glyphs at `int(font_size)`.
- It **crashes** on a text box with width or height 0.

`main.py`'s `self_check` catches none of this. It passes the uniform-stretch baseline on L3 with **zero warnings**, even though the logo comes out 216×6.7 px and the text is unreadable. Most points will be lost in this JSON-vs-pixels gap, and the gap is mechanical, so it can be closed. Teams that measure with the renderer's own code, keep their boxes honest (box = ink), and verify by rendering will beat teams with smarter layout ideas that skip this.

## 2. Reverse-engineered scorer model

My best model is:

`score(task) = Gate × [α·Structural + (1−α)·VLM_rubric]`, averaged over a few hundred tasks and maybe weighted by level.

**Gate.** A crash, invalid JSON, or id mismatch probably zeroes the task. Note that `main.py` has **no try/except** around `resize()` or the render call. If they batch-run it, one exception loses every task after it.

**Structural.** Per-check pass rates. A role-unaware checker can do more than `self_check`.

**VLM.** Rubric rows (collisions, readable, on-brand, intentional, faithfulness), scored on the output render. The VLM almost certainly also sees the source render, because "faithfulness to intent" can't be judged without it. I'd guess it scores 1–10 per row, possibly pairwise against the baseline.

**"Holds up everywhere"** likely means variance or worst-case sensitivity. One spectacular failure costs more than ten small polish wins.

**Where the hidden data probably comes from.** The L3 note says *"a variable-count set of badges"*. That is the language of a **parametric template generator** built on the brand kit, with adversarial knobs: run-on copy, badge count, rotation, a missing asset. A generator knows the ground-truth roles of its elements, so I expect **role-aware checks** (logo visible and in proportion, headline still the largest text, CTA group intact) even though we never see the roles. Targets come from the platform catalogue.

**What gets penalized** (my confidence in brackets):

| Check | Source | Conf. |
|---|---|---|
| ids added, removed or duplicated; count changed | JSON | certain (gate) |
| Required fields missing; `type` changed | JSON | certain |
| Schema invalid: extra top-level or `canvas` keys (schema has `additionalProperties:false`), non-int canvas dims or `z_index`, NaN | JSON | likely |
| Unrotated box off-canvas beyond ±0.5 | JSON | certain |
| Rotated bounds off-canvas | JSON/pixels | 50% (the VLM sees clipping regardless) |
| Non-cover image box aspect more than 5% from source (full-bleed probably exempt) | JSON | certain |
| `content` or `font_family` changed | JSON | likely |
| Text overflow, measured with the same `wrap_text` (lines×lh×fs > box h; word wider than box) | JSON | likely ("nothing cut off") |
| `max_lines` exceeded | JSON | possible |
| Group split apart, or a label no longer inside its shape | JSON | likely |
| Relative z-order inverted | JSON | possible |
| Elements at opacity 0 counted as "missing" | JSON | **unknown: ask** |
| Text on an image or busy area; text-text overlap | VLM | certain |
| Text too small at the evaluator's resolution; low contrast | VLM | certain |
| Content clipped at the canvas edge (rotated ribbon, overflowing line) | VLM | certain |
| Visible grey "missing asset" placeholder | VLM | certain; it reads as "broken" |
| Logo or product distorted or tiny | VLM | certain |
| Dead space or a tiny centred island (letterbox look); unbalanced composition | VLM | likely |
| Hierarchy inverted (subhead ≥ headline); CTA not prominent | VLM + role-aware | likely |
| Clutter: more than ~4 visible units in a 728×90 or 320×50 | VLM | likely |

## 3. Adversarial case catalogue (prioritized)

Notes in brackets say what the renderer actually does, from the §8 spikes.

**P0: will appear, and costs the gate or an obvious visual hit**
1. **Opaque ids and shuffled element order.** Output must not change when ids are renamed or the order is permuted (except for z ties, see 12).
2. **Missing asset.** [Renders a grey box with a red border.] Hide it. But if *every* image is missing, our asset dir is probably wrong, so hide nothing.
3. **Run-on copy (140–200 chars) on small targets.** [Measured: at 728×90 the L3 headline fits a 420×80 slot only at 17px over 3 lines. The subhead fits only at 16px over 4 lines, so the two cannot coexist.]
4. **Rotated elements and groups near edges.** [The unrotated box passes `self_check` while the corners get clipped. The baseline clips rotation in 65 of 78 sweep cases.]
5. **Extreme or tiny targets**: 728×90, 970×90, 320×50, 160×600, 300×250.
6. **Intentional bleed in the source** (circle at −100,−100). It gets flagged in the output, so clamp it inside the canvas.
7. **Groups with a variable count**: 0–N badges, pill+label, pill+icon+label.
8. **Source text boxes that lie.** Source box heights are smaller than the wrapped text. Never trust the source h; re-measure.

**P1**

9. **Text-on-shape without a `group_id`.** Infer a pseudo-group when the shape is below the text in z, contains its centre, and is ≤ ~4× its area.
10. **Full-canvas translucent scrims.** Part of the background layer; stretch with it.
11. **Multiple images**, including non-background `cover` images. Centre-crop can cut the subject, so cap the aspect change.
12. **z ties or missing `z_index`.** [Stable sort: **list order breaks ties**; swapping list order flipped the top shape.] Never reorder the output list.
13. **Unbreakable tokens** (URLs). [Centred: overflow both sides. Right-aligned: 400 px bleed left.] The longest token caps the font size.
14. **`letter_spacing` > 0.** [Ink ran 189 px past the box.]
15. **Empty or whitespace-only content.** [Draws nothing.] Valid box, w and h ≥ 1, no reserved space.
16. **Line and stroke-only shapes.** [Lines are always horizontal and invisible at h=0. `stroke_*` is ignored on rect and ellipse.]
17. **Emoji and CJK/Arabic.** [Tofu boxes.] Unfixable, but still measure it.

**P2**

18. **HTML entities** (`&amp;`). [Wrapped raw, then unescaped: *mid-word* breaks ("Pep|per") and shifted style runs.] Prefer a single line.
19. **`style_runs`.** The renderer treats `end` as inclusive. Never touch them.
20. **Unknown `font_family`.** Falls back to Solstice Sans; measure with the same `FontManager`.
21. **Non-schema `capitalize: true`.** Rendered uppercase but measured lowercase, so it overflows.
22. **Named colours** (`"white"`). [Renderer **crash**.] Never write colours.
23. **numpy types or NaN in the output.** [`float32`/`int64` make `json.dumps` raise, which crashes `main.py`.]

## 4. Robustness architecture

**Invariants.** The validator enforces these on every candidate:

- **I1 Shape.** Output is `{"canvas":{"width":int,"height":int},"elements":[...]}` with nothing else. Ids match exactly and stay in source list order.
- **I2 Frozen fields.** Deep-copy every element. The only fields the engine may change are `x, y, width, height, font_size`, plus `opacity→0` and (for hidden text only) `z_index` for hiding. Unknown keys pass through.
- **I3 Numbers.** Plain Python types, finite, rounded to 2dp. `z_index` and `font_size` are ints, with `font_size` ≥ 1, so the size we measure is the size that renders.
- **I4 Bounds.** The unrotated box sits inside [0,W]×[0,H] with a 0.01 margin, **and** the rotated bounding box of every visible element sits inside the canvas.
- **I5 Aspect.** Non-cover, non-full-bleed images keep the *source box* aspect within 1%, leaving headroom under the 5% limit.
- **I6 Text honesty.** Use the converter's wrap at the float size, then widths at `int(fs)` plus `letter_spacing`. Every line must be ≤ box w, `n·fs·lh` ≤ box h, lines ≤ `max_lines`, and w and h ≥ 1.
- **I7 Legibility.** For every visible text, `int(fs)·min(1, 1024/max(W,H))` ≥ the floor for its tier: about 14 for primary, about 10 for the rest. Otherwise hide it (with its group).
- **I8 Groups.** Visibility is all-or-nothing. Each group moves as a rigid similarity transform (uniform scale + translation); rotation is unchanged.
- **I9 Z-order.** Relative z-order of visible elements is preserved.
- **I10 Hide encoding.** Set `opacity:0`. For text, *also* set `z_index = min_z−1`, under the opaque full-bleed background (the spike shows 0 px leak). Geometry is the safe-fit parking spot (see below): in-bounds, correct aspect, sensible if un-hidden. If there is no opaque background, text cannot be hidden, so it must be placed legibly.
- **I11 Determinism.** Identical output under id renaming and list permutation (outside z ties).
- **I12 Render-OK.** An in-process render must succeed. It takes about 0.1 s at full resolution, measured.

```python
def resize(source, target):
    try:
        src, tgt = normalize(source), normalize_canvas(target)   # no mutation; defaults; ints
        deadline = time.monotonic() + BUDGET_S
        pool = []
        for strategy in STRATEGIES:            # best-first: reflow/banner/stack/..., then safe_fit
            try:
                cand = repair(strategy(src, tgt), src, tgt)          # clamp, refit text, aspect, hide
            except Exception:
                continue                                          # log, never raise
            if hard_violations(cand, src, tgt):  continue
            if not render_ok(cand):              continue          # catches pydantic/skia crashes
            pool.append((critic(cand, src), PRIORITY[strategy], cand))
            if time.monotonic() > deadline and pool: break
        if not pool:
            pool.append((0, 99, repair(safe_fit(src, tgt), src, tgt)))
        return to_plain_json(max(pool, key=lambda t: (t[0], -t[1]))[2])
    except BaseException:
        return last_resort(source, target)     # uniform contain-scale, clamp, pure-python, no imports

def repair(c, src, tgt):                       # fixed order, at most 3 passes, then re-validate
    for _ in range(3):
        enforce_groups(c); fit_text(c); keep_aspect(c); clamp_rotated(c); apply_hiding(c)
        if not hard_violations(c, src, tgt): break
    return c
```

**Fallback ladder.**

1. Full engine, best-of-N.
2. Conservative "cluster-preserving reflow": proximity clusters treated as rigid units, scaled and packed. It is role-agnostic and copes with 15 text boxes.
3. **safe_fit**: uniform contain-scale of the whole design, centred; full-bleed layers stretched to the canvas; missing assets hidden; rotated bounds clamped. Its JSON is perfect by construction, but it looks like a small island in empty space.
4. `last_resort`: the same idea with zero dependencies.

The critic is the proxy scorer minus the VLM (§5), so the score optimized in development is the one that picks layouts at runtime.

## 5. Evaluation harness

**Generator** (`harness/gen.py`, seeded):
- **A. Parametric archetypes** from the brand kit: centred stack, split hero, product-left, text-only, banner, story. Knobs: 0–5 badges, copy from 2 words to 200 chars, rotation 0–20°, scrim, bleeds, legal line, 1–3 images, `group_id` kept or stripped.
- **B. Adversarial mutators**: one per §3 item, applicable to any design.
- **C. Crello converter** (the HF dataset; deps already in the venv). Converts normalized coords to px and π-angles to degrees, saves embedded crops as assets, and swaps fonts for Solstice. Gives real layout diversity and opaque uuid ids.
- **D.** The 3 samples, as permanent regression fixtures.

**Size catalogue** (exact px):

| Format | px | Format | px |
|---|---|---|---|
| Instagram Post | 1080×1080 | YouTube Channel Art | 2560×1440 |
| Instagram Portrait | 1080×1350 | Presentation 16:9 | 1920×1080 |
| Instagram Story/Reel, TikTok | 1080×1920 | IAB Leaderboard | 728×90 |
| Instagram Landscape | 1080×566 | IAB Large Leaderboard | 970×90 |
| Facebook Post (link) | 1200×630 | IAB Billboard | 970×250 |
| Facebook Cover | 820×312 | IAB Medium Rectangle | 300×250 |
| Facebook Event Cover | 1920×1005 | IAB Large Rectangle | 336×280 |
| X/Twitter Post | 1600×900 | IAB Half Page | 300×600 |
| X/Twitter Header | 1500×500 | IAB Wide Skyscraper | 160×600 |
| LinkedIn Post | 1200×627 | IAB Mobile Banner | 320×50 |
| LinkedIn Banner (≈L2's 1600×400) | 1584×396 | IAB Large Mobile Banner | 320×100 |
| Pinterest Pin | 1000×1500 | Email Header | 600×200 |
| YouTube Thumbnail | 1280×720 | US Letter Flyer @150dpi | 1275×1650 |

**Proxy scorer**, in three layers:
1. **Structural.** Deterministic, mirrors §2. The prototype is `spikes/judge/proxy_scorer.py`.
2. **Render-based heuristics.** Render each element alone (call `CrelloV5Renderer.render(..., canvas_color=None)` to get per-element ink masks), then measure:
   - true ink-in-canvas, and text ink ∩ other ink (minus group-mates and overlaps already present in the source);
   - backdrop busyness (edge density) under text, and WCAG contrast of text against backdrop pixels;
   - OCR character error rate (tesseract) at the evaluator's 1024 px resolution; this is the "readable" row made literal;
   - hierarchy: Spearman of source vs output font sizes, and share of area held by the primary element;
   - composition: margins, shared alignment lines, largest empty rectangle (penalizes the safe_fit island), and ink centre of mass;
   - faithfulness: importance-weighted kept set, Kendall τ of reading order, background colour histogram.
3. **VLM (dev only, never shipped).** A rubric prompt over the source and output renders. Run it pairwise A/B with positions swapped against the previous build, on a fixed 200-case golden set, using a hosted model or a local Qwen2.5-VL via MLX. It is used to calibrate the weights of layer 2; target Spearman ≥ 0.6 with the VLM.

**Runner.** Each case runs in a subprocess with a timeout, and the runner logs crashes and timings. It produces an HTML contact sheet (source | output | issues), and an A/B diff page sorted by score delta. **Merge gate:** no hard violations, no crashes, metamorphic tests passing, and no drop in mean or 5th-percentile score.

**Metamorphic tests:**
- id-scramble and permutation give identical output;
- target = source canvas gives roughly the source;
- a same-aspect target gives a uniform scale.

## 6. Strategy and open questions

1. **Ship the floor on day 1.** safe_fit plus the validator: 0 hard issues and 0 render crashes on 78/78 sweep cases. Every later change must beat it on the harness.
2. **Best-of-N beats one clever layout.** Rough arithmetic: a fancy layout scoring 8 that breaks 15% of the time (2.5) has an expected score of 7.2. If a critic swaps those failures for the floor (6), the expectation becomes about 7.7.
3. **Choose a regime by `r = |ln(aspect_t/aspect_s)|` and by absolute size.**
   - r < 0.15: uniform scale, then distribute the slack. Faithful, so no cleverness.
   - 0.15–0.9: re-layout keeping every element.
   - Above 0.9, or a short side under ~120 px: banner or tower mode with tiered hiding.
4. **Hide by a legibility budget, not by aspect.** Keep an element only if it fits at ≥ its floor without collisions. Hiding order:
   1. missing-asset images;
   2. watermarks and decorations;
   3. legal text;
   4. rotated stickers or ribbons;
   5. badges;
   6. subhead;
   7. product.

   Never hide the background, the logo, the primary text, or the CTA group. Hide groups whole. Hide only as much as the budget requires.
5. **Text quality wins are cheap.** Use integer font sizes. Get **balanced wrapping** by shrinking the box width to the smallest width that keeps the line count, which makes greedy wrap look typeset. Make boxes equal the ink. Map font sizes so their order is preserved (hierarchy). For text with `&...;` entities, use a single line.
6. **Use ids only to break ties,** and let the harness enforce that.
7. **Be conservative when unsure.** Low role confidence leads to cluster-preserving reflow, not template reassignment.
8. **No in-engine model for stage 1** unless it beats the heuristics on the harness by a clear margin. amd64-under-emulation CPU inference is slow and adds a failure mode.

**Ask the organizers:**
1. Is `opacity:0` an accepted "drop", or counted as missing? Do they know the renderer ignores text opacity?
2. Is off-canvas checked on the unrotated box or rotated bounds? Is intentional bleed allowed?
3. Is the 5% aspect measured against the source box or the asset? Are full-bleed non-cover images exempt?
4. Which fields are frozen besides `content` and `font_family` (`fit`, `z_index`, `rotation`, `color`)?
5. Can hidden designs use assets outside `brand_kit/assets`, or non-Solstice fonts?
6. Can `target_canvas` carry extra keys? Must the output canvas be exactly {width, height}?
7. Does the VLM see the source render, at what resolution, and is it pairwise?
8. Is `max_lines` enforced? Is scoring run per task or as a batch, and with what time budget?
9. What are the level weights, and how is "holds up everywhere" aggregated?

## 7. Build plan

- **Days 1–2: contract layer.** normalize → validate → repair → safe_fit → last_resort, plus `render_ok` and `to_plain_json`. Port `proxy_scorer.py` and `fallback_and_sweep.py` into `harness/`. Gate: 0 hard and 0 crashes on 3 × 26 sizes.
- **Days 2–4: harness.** Generator (A+B), the catalogue, mutators, runner, HTML report, metamorphic tests. Gate: 1,000 cases in under 5 minutes on a laptop. The prototype already runs 78 cases in about 5 s.
- **Days 4–9: engine strategies** (from the other proposals), each one a candidate in the pool, evaluated nightly. Add layer 2 of the scorer as the critic.
- **Days 9–11: VLM calibration** on the 200-case golden set; tune critic weights and the legibility floors.
- **Days 11–13: hardening.** Hypothesis fuzzing over the JSON (random field deletions, type swaps, extreme numbers), the Crello set, timing under `docker --platform linux/amd64`.
- **Day 14: freeze.** Only bug fixes with harness proof.

## 8. Spike evidence

Run from the repo root. Files are in `design/debate/spikes/judge/`. Raw results: `findings.json`, `sweep_results.json`, `out/*.png`.

**`spike_renderer_edges.py`** (26 probes):
- `opacity:0` text **renders fully visible** (ink (53,68)–(306,113)). Opacity-0 images and shapes, and alpha-0 text colour, are invisible.
- Text `width:0` or `height:0` **crashes the renderer** (pydantic `gt=0`); `self_check` reports nothing. Colour `"white"` also **crashes**.
- A -12° bar with its unrotated box inside the canvas gets its corner clipped; `self_check` is clean.
- `letter_spacing:12`: ink to x=689 for a box ending at 500 (485 without it).
- Over-long word: centred spans 165–554 for a 300–420 box; right-aligned bleeds to x=197 for a box starting at 600.
- `font_size` 59.9 and 59 render identically; 0.5 draws nothing.
- `&amp;` breaks lines mid-word. `style_runs` 0–4 colours 5 characters.
- Emoji/CJK/Arabic render as tofu (é, —, © are fine). An h=0 line and a stroke-only rectangle render nothing. An unknown font falls back to Solstice Sans.

**`proxy_scorer.py` on the baselines.** `self_check` flags only L2's deco circle. The proxy flags:

| Sample | Hard issues | Soft issues |
|---|---|---|
| L1 | 1 (logo aspect 2.56 vs 3.20) | 0 |
| L2 | 3 | 4 |
| L3 | 3 | 11 (8 texts perceived at 1–2 px, clipped ribbon, visible placeholder) |

**`fallback_and_sweep.py`** (3 samples × 26 catalogue sizes):

| | Cases with hard issues | Hard issues | Clipped rotations | Unreadable texts | Render crashes |
|---|---|---|---|---|---|
| Baseline | 75/78 | 173 | 65 | 229 | n/a |
| safe_fit | **0/78** | 0 | 0 | 217 | 0 |

The safe_fit unreadable texts are concentrated in leaderboards, mobile banners and the skyscraper. So the contract is easy to satisfy; the real battleground is legibility at extreme ratios. The safe_fit renders (`out/safefit_sheet.png`) look correct but sparse.

**Hiding text** (pixels that differ from a background-only render):

| Encoding | Differing px |
|---|---|
| Visible | 3577 |
| `opacity:0` | 3577 (no effect) |
| `font_size:1` | 14 (a speck) |
| `opacity:0` + z under opaque background | **0** |

**Hand mock of the brief's 728×90 reference** (`out/mock_l3_leaderboard_2x.png`): logo, a 16px three-line headline, the CTA, and 12 hidden elements. It is clean and legible. However, my eyeballed CTA box made "Shop the Summer Line" wrap, and "Line" spilled out of the pill. The proxy caught it ("2 lines overflow box height by 11px"). That is the whole thesis in one bug: **always measure with the renderer's code, then render and check.**

**Other:** a full-resolution L3 render takes 0.097 s, so best-of-8 with render checks is affordable. numpy `float32`/`int64` break `json.dumps`, and NaN serializes as invalid JSON.

**Limitations:** the floors (perceived 9/10/14 px at a 1024 long side) and the critic weights are assumptions until they are calibrated against a VLM. The occlusion check in the proxy is box-based and only treats unrotated opaque rectangles and RGB cover images as occluders.
