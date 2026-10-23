# DESIGNER — "Re-typeset, don't transform"

*Lens: senior brand designer / typographer who codes. Spike code + renders: `design/debate/spikes/designer/` (start with `contact_sheet.png`).*

## 1. Core idea and the one insight

When a human designer adapts a 1:1 post to a 728×90 leaderboard, they don't scale boxes. They (a) read the design: what is the brand mark, the message, the action, the proof, the fine print, the atmosphere; (b) choose the **layout archetype** that works for the new shape (stack, split or strip); and (c) **re-typeset** the content into it, keeping the *ratios* that made the original feel designed (type ramp, button anatomy, rhythm, density) and dropping whole tiers of content when the space can't carry them. My engine encodes exactly those three steps, and the role labels it needs are inferred from the input without ids.

**The insight: one knob, many exponents, and "legible or absent".** All type and image sizes come from a *single* elasticity scalar `k`, and each role has its own exponent: `size' = size_src · k^γ(role)`. Display type is elastic (γ=1), text type is stubborn (γ≈0.6–0.75, less again for legal), and when shrinking (k<1) pictures give way before words. `k` is bisected against the **real renderer's glyph widths** until the composition fills its budget. That one solve gives three things at once: hierarchy preservation (the ratios can't invert), fill-to-canvas (type grows on a story, shrinks on a banner), and degradation. If no `k` is feasible, or the floors would flatten the hierarchy (headline < 1.2× any other text), or the headline is "starved", the lowest content tier is dropped and the solve runs again. A visible element is always legible and ranked. Anything that can't be both is not shown, rather than shrunk until it's unreadable. A VLM judge punishes unreadable text hard and almost never notices that a badge is missing.

## 2. Architecture / pipeline

```
source + target
  │
  ├─ 0. Measure      renderer-exact text metrics (wrap.py char_widths/wrap_text, skia ascent/cap),
  │                  image optical bounds (alpha bbox of the asset under contain-fit), asset existence
  ├─ 1. Read         role inference → modules: background · atmosphere(decos) · logo · hero ·
  │                  message(headline, subhead, body) · action(CTA chip or CTA text) ·
  │                  proof(badges, stickers) · fine print(legal) · broken
  ├─ 2. Distil "DNA" type ramp ratios, chip anatomy (h/fs, padx/fs, radius/min-side), source rhythm
  │                  (optical gaps), vertical density (content span / H), alignment axis, corner anchors
  ├─ 3. Choose       archetype by aspect band (+ "has hero?")  →  strip | split | stack
  ├─ 4. Compose      archetype composer: slots + one-knob k-solve + tier dropping + optical placement
  ├─ 5. Atmosphere   decorations: halo behind the image they overlapped / re-anchor to corner / drop
  ├─ 6. Hide         dropped ids: opacity 0 AND text colour alpha 0 (see §3.6), parked in-bounds
  └─ 7. Verify       ids, bounds (incl. rotated AABB), image aspect ±5%, re-wrap check, fallback
```

Everything is deterministic Python with no model. A compose takes 0.04–0.14 s per design in the spike.

## 3. Key algorithms

### 3.1 Role inference (no ids, verified with anonymised ids)

```
background  = lowest-z image/shape covering ≥90% of canvas
chips       = shape+text pairs: shared group_id first; else an OPAQUE (alpha≥.5) shape geometrically
              containing a text. (Translucent shapes never "hold" text: this fixes L2's big
              circle, which geometrically contains the NEW FLAVOR label.)
decoration  = remaining shapes; any image with alpha<.3
broken      = image whose asset file doesn't exist  → always hidden (else grey "missing asset" box)
hero/logo   = among live images: hero = largest area; logo = argmax logo_score
              (small area, mostly transparent pixels, near top/bottom edge, wide, high z)
CTA chip    = argmax over chips of: imperative verb lexicon (shop/buy/get/learn/…) +2,
              not ALL-CAPS +1, area share, lower on canvas, rotated −3
sticker     = rotated chip; badge = other chips
headline    = free text with max font_size·(1.25 if bold)
legal       = small (≤.55·headline, smallest, <16px) AND (low on canvas | faint | >60 chars)
cta_text    = free text starting with an imperative verb, <32 chars
subhead     = next free text; further ones → body
```

`roles.py` renames ids to `e0..eN` and group ids to `g0..` (and shuffles) before inference. **All 32 elements across the 3 samples get the right role.** Every rule is generic, and the verb lexicon is general English, not tailored to these samples.

### 3.2 Archetype selection (aspect bands over the platform catalogue)

| band | r = W/H | archetype | examples |
|---|---|---|---|
| strip | r ≥ 4.5, or r ≥ 3 and H ≤ 120 | `logo │ hero? │ message │ action` on one row | 728×90, 970×90, 468×60, 320×50, 320×100 |
| split | 1.3 ≤ r < 4.5 **and** a hero exists | hero column + message stack column | 16:9, 1.91:1, 3:1, 1600×400 |
| stack | r < 1.3, or no hero | centred reading-order stack, pinned top/bottom | 1:1, 4:5, 9:16, 300×250 |

A landscape canvas with **no hero** goes to `stack`. Splitting an empty column is a designer's mistake. Skyscrapers (160×600) are a narrow-measure stack. I'd add a `tower` variant only if the catalogue shows many of them.

### 3.3 Placement: optical, not box-based

- **Text** is placed by its *cap-top*, not its box: `y = optical_top − (ascent − cap)·fs`, with ascent and cap height read from skia. Solstice Sans: 1.05 / 0.70 em. Serif: 1.006 / 0.70 em.
- **Chip labels** are optically centred: `label.y = cy − (ascent − cap/2)·fs`. The source sits about 5 px high because it centres the *box*.
- **Images** are positioned by their visible alpha bbox. The logo lockup is 60% transparent padding horizontally (content x 268–631 of 900), and the bottle has 31% vertical padding. Without this, spacing looks random. The JSON box keeps the source aspect exactly and is then clamped in-canvas: if the transparent padding would push the box off-canvas, the visible size shrinks instead.
- **Balanced wrap**: the renderer wraps greedily, so I bisect the *box width* down to the narrowest width that keeps the same line count. That emulates CSS `text-wrap: balance`, with no orphans and even rag. The width is always re-verified with the real `wrap_text`, because a widest-line width can re-wrap differently owing to trailing-space accounting.
- **Font sizes are integers.** The renderer draws at `int(fontSize)` but the converter measures wraps at the float size, so fractional sizes mis-wrap.
- **Shared axis**: every stack item centres on one column axis, and margins are a function of the short side (strip 13% H, split 8%, stack 6.5%).

### 3.4 Elastic type and the stack solve

```
GAMMA_UP   = {headline:1.0, subhead:.75, body:.75, chip:.6, legal:.35}   # k ≥ 1
GAMMA_DOWN = {headline:.8,  subhead:.6,  body:.6,  chip:.5, legal:.3}    # k < 1 (images use γ=1)
floor_px(role) = ceil(FLOOR[role] / min(1, 1024/long_side))   # legibility in *judge pixels*
FLOOR = {headline:14, subhead:11, chip:11, body:11, legal:9}

solve_stack(kinds, col_w, avail, target):
  bisect k in [0.15, 4]:
     items = measure each kind at k (text wraps at measure=min(col_w, src_w·W/W_src);
             headline may not gain lines when growing, except on tall canvases)
     if any infeasible (overflowing word, too many lines, hero wider than column): hi=k
     elif not hierarchy_ok(items): lo=k               # floors flattened ranking → push k up
     else gaps = max(src_gap·k, descender + .8·max(fs_a, fs_b)); fits(target) ? lo=k : hi=k
```

The **fill target** comes from the source's vertical density: content span ÷ source height, plus extra fill on small canvases where floors and gaps eat space. Split uses 90% of available height. That's why the L1 headline grows 60→75 on 4:5 instead of exploding.

### 3.5 Degradation (tier dropping)

| tier | contents | rule |
|---|---|---|
| T0 never | background, headline, CTA, logo | logo shrinks to a floor (24 judge-px visible) |
| T1 | hero, subhead | strip: hero only if the message still reads at ≥0.2H in ≤2 lines; subhead only on 1 line and ≤ headline/1.25 |
| T2 | badges (N-of-M from the tail), stickers | sticker returns to its source corner only if free, ≤4% of canvas, ≤0.75× headline size |
| T3 | legal, body | legal pinned to the bottom if legible at floor in ≤2 lines |
| T4 | decorations | gone in strips; otherwise halo or corner (§3.7) |
| T∞ | broken assets | always hidden |

A tier is dropped when the solve is infeasible, when the hierarchy is flattened, or when the headline is "starved" (< max(1.5× body floor, 2.5% of short side)) and dropping the victim measurably grows the headline.

### 3.6 How "absent" is expressed — critical renderer finding

**The official renderer ignores `opacity` on text.** `cr_renderer` builds `TextElement` without opacity, and `render_text_fill` calls `paint.setColor()`, which overwrites the alpha. I verified it: `opacity_test.png` shows an opacity-0 text drawn fully white. Images and shapes do honour opacity. So a dropped element gets:

- `opacity: 0` on every type, which declares the intent;
- for text, `color` (and any style_run colours) set to `rgba(R,G,B,0)`. The RGB values stay the same, so the palette is unchanged.
- geometry parked in-bounds: source geometry scaled by `min(W/Ws, H/Hs)` and positioned proportionally.

Hiding behind the background through z-order also works but is less honest. Whether the structural scorer accepts opacity 0 is the #1 question to put to the organisers.

### 3.7 Decorations ("atmosphere")

A decoration travels with the content element it overlapped most in the source, which keeps the designer's intentional layering:

- If that element is an image, the decoration becomes a **concentric halo**: diameter ≈1.12× the image's visible height, clamped to the canvas. Offset relationships don't survive aspect changes, but halos always read as intentional.
- If it overlapped text, it keeps a compressed (×0.5) relative offset.
- If it overlapped nothing, it goes back to its source corner, sized on the short side and fully in-bounds. I never bleed off-canvas, because the bounds check is hard.

## 4. Walk-through (actual spike output, ids anonymised during the run)

**L1 1080×1350 (stack).** k=1.25.
- Logo box (339, 75, 402×126), visible mark at y≈75–165, centred.
- Headline 60→**75 px**, one line, box x=258 w=565 y=527.
- CTA text 30→**34 px** (γ=0.6), y=779.
- Everything is on axis x=540. Content span = 55% of the height, the same as the source, so it's faithful rather than inflated.

**L2 1600×400 (split, hero right because the source hero is centred → text-first reading order).** m=32.
- Product box (1211, 3, 389×389), so the visible bottle is about 165×268 centred at (1405, 200). deco_circle_1 becomes a **halo** of d=300 behind it at (1256, 50), opacity 0.15 kept.
- Message column x∈[32, 1240], axis x≈658:
  - logo box (526, 47, 266×91), visible mark ≈98×66;
  - headline **48 px**, one line with the gold `style_run` intact, box (477, 136, w 363);
  - subhead **21 px**, one line, (378, 228, w 560);
  - CTA pill (500, 283, 317×68, r=34, still a pill) with a 20 px label, caps optically centred.
- Badge "NEW FLAVOR" returns to its **top-left corner** (32, 26, 174×54, r=27) with an 18 px label, ≤0.75× the headline.
- deco_circle_2 (d=93) stays attached to the headline, behind "the" at (660, 121).
- Nothing is hidden. Result: a believable web-hero banner (see `out_level2_core_1600x400.png`).

**L3 728×90 (strip).** m=12, row centre y=45.
- Logo box (0, 12.5, 248×77.5): the visible mark is ≈100×56 at x≈76–176. The transparent padding sits under the headline box but never under its glyphs.
- CTA pill (511, 25, 205×39, r=19.6) with "Shop the Summer Line" at **14 px**, right-aligned to the margin.
- Message cell x∈[187, 499]: the 140-character headline fits at **14 px serif bold in 4 balanced lines**, box x=206 w=270, cap-top y≈15, last baseline ≈75.
- The hero test fails (a 4-line message can't spare ~40 px), so the product is dropped.
- Subhead (190 chars) can't fit on one line at ≥11 px, so it's dropped.
- 3 badge groups, the −12° ribbon group, legal and the missing-asset watermark are dropped (12 ids, opacity 0 + transparent colour).
- Result: logo │ headline │ pill, which matches the brief's reference leaderboard; the only difference is that the copy can't be shortened.

## 5. Against the rubric

- **No unwanted collisions.** Collision-freedom is by construction: slots and stacks don't overlap, and min gaps include descender room. Text never sits on the hero, and decorations stay *under* content as intentional layering. Corner chips check overlap against visible rects before claiming a corner.
- **Readable.** Judge-pixel floors cover downscaling for big canvases. Balanced wraps, integer sizes and renderer-exact measurement mean nothing overflows or gets cut. Anything that can't be legible is absent.
- **On brand.** No colour, font or content changes on visible elements, apart from transparent alpha on hidden text. Logo aspect is exact, pills stay pills (radius/min-side preserved), style_runs survive.
- **Looks intentional.** One axis, short-side margins, optical alignment, balanced rag, the type ramp preserved and amplified, halos, corner anchors faithful to the source. This is the core of the approach.
- **Faithfulness.** Reading order, alignment, density, corner anchoring and layering relationships all come from the source DNA. Drops follow the brief's own leaderboard.
- **Holds up / reliability.** Deterministic, ~0.1 s, never crashes on missing assets. Every output passes ids, bounds and aspect checks (11/11 in the spike).

## 6. Risks / failure modes and mitigations

1. **Role inference on unseen designs** (logos made of text, photo heroes that aren't cut-outs, two products, editorial layouts with no clear headline).
   - Give every role a confidence score. Below a threshold, fall back to a conservative "proportional re-anchor" mode: uniform fit-scale per module, anchors preserved, still with renderer-exact text fitting.
   - Build an anonymised test corpus early (synthetic variants + Crello-derived layouts) and test role accuracy as a unit metric.
2. **Grammar too narrow** (left-aligned editorial, product grids, multi-column copy).
   - The stack already keeps the source's anchoring. Add left/right anchoring per item, and a `grid` slot for ≥3 similar repeated items. The badge row is the first instance of this.
3. **Busy photo backgrounds.** The samples use a smooth gradient, so this is untested.
   - Emulate the cover crop on the asset, compute local luminance std and edge density under each candidate text rect, and move text to the calmest band.
   - Last resort: reuse an existing translucent shape as a scrim behind the text. That honestly moves an existing element and invents nothing.
4. **Opacity-0 acceptance.** Ask the organisers.
   - If it's rejected, keep "drop" for T2–T4 only and give T1 a minimal legible presence where possible.
5. **Logo box overlapping a text box** (transparent padding, L3 strip). This matters if the structural check tests box overlaps.
   - Add a constraint switch so the box never overlaps another content box. The cost is a ~25% smaller visible logo in strips.
6. **Spacing rhythm on extreme stretches.** In the L2 story the source gaps ×k produce uneven gaps: 300 px under the logo vs 35 px above the CTA.
   - Regularise gaps: snap them to {1,2,3,4}× a rhythm unit while keeping their rank order.
7. **Impossible inputs** (320×50 with a 140-character headline). The spike shows logo + CTA only.
   - Correct for "legible or absent", but faithfulness suffers. Consider "drop the logo before the headline" when the headline would fit without it.
8. **Rotated elements.** Done for stickers: the rotated AABB is pulled inside the canvas while the angle is kept. Needs generalising to any rotated module.

## 7. Build plan (2–3 people, ~2 weeks to a strong stage-1 engine)

| # | Work | Owner | Effort |
|---|---|---|---|
| 1 | Measurement layer (wrap/metrics/optics/balance/fit), invariants checker, render + contact-sheet regression harness | A | 2 d |
| 2 | Role inference + confidence + anonymised fixture suite (≥30 hand-made/synthetic designs) | B | 3 d |
| 3 | k-solver, tier dropper, strip/split/stack composers (port and clean the spike) | A | 4 d |
| 4 | Decorations, stickers/rotation, legal pinning, hide/park, missing assets | C | 2 d |
| 5 | Busy-background detection, gap regularisation, left/right anchoring, grid slot | B/C | 3 d |
| 6 | Constant tuning across the full catalogue × corpus, using a VLM as a *dev-time* proxy judge on contact sheets (not shipped); Docker/offline verification | all | 3 d |

Days 1–5 already produce a submission that beats the baseline on every sample. Everything after that improves robustness.

## 8. Spike evidence (honest)

Files are in `design/debate/spikes/designer/`:
- `roles.py`: inference on anonymised ids, 32/32 correct.
- `compose.py`: a ~800-line rough implementation of §3.
- `out_*.png/json`: 11 renders through the **official** `render_design_to_png`.
- `contact_sheet.png`, plus the source renders `src_*.png`.

All 11 outputs pass ids, bounds and aspect checks.

**What worked**
- L3 728×90 and L2 728×90 look like real leaderboards. L2's version even keeps the bottle, because the short headline leaves room.
- L2 1600×400 and 1280×720 read as polished web heroes with intentional halos.
- L3 1080×1080 (4:5 → 1:1) keeps all 16 live elements (ribbon at its corner, 3-badge row, legal) and hides the broken placeholder.
- L1 4:5 is faithful and clean.

**What failed or is weak**
- 300×250: the headline is only ~17 px, and the badge and subhead were dropped by the rules. Acceptable but plain.
- 1080×1920 story: uneven rhythm (see risk 6).
- 320×50 with L3: no headline at all.
- 1920×1080 from L1 is correct but conservative. A human would push the headline larger.
- Debugging found three renderer traps a naive engine will hit: text opacity is ignored, font size is truncated to int, and transparent asset padding defeats box-based spacing. The last one pushed the logo and bottle off-canvas in my first pass, before the box clamp was added.

**Earlier iterations taught real rules**
- Translucent shapes must not be treated as button containers.
- Offset decorations look random, while halos look designed.
- Fill-to-max produced absurd 190 px headlines, so the fill target now comes from source density.
- Floors silently flatten hierarchy unless there is a guard.
- A badge next to a CTA in one column reads as two buttons, so corner-sourced badges must return to their corners.
