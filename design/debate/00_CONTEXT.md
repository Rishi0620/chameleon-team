# CHAMELEON design debate — shared context (read this first)

You are one of several agents debating the best possible architecture for the
CHAMELEON engine. This file is the shared ground truth. The repo is at
`/Users/rishabhbhargav/Desktop/chameleon` (venv python: `.venv/bin/python`).

## The challenge in one paragraph
Adobe University Hackathon NA 2026. Build an offline engine:
`resize(source: dict, target_canvas: dict) -> dict` in `engine/resize.py`.
Input: a design (canvas + list of `text` / `image` / `shape` elements with
x, y, width, height, rotation, opacity, z_index, group_id, and type-specific
fields) and a target canvas size. Output: the SAME elements (same ids, same
count) with new geometry (and optionally new `font_size`) so the design fits
the new canvas and still looks designed. "Move the furniture, don't stretch the
photo." Stage 1 = automated scoring on hundreds of hidden designs and unseen
target sizes across 3 difficulty levels; top 6–7 teams go to an in-person
finale (turn the engine into an Adobe Express add-on, judged by a jury).

## How stage 1 is scored (both are checked)
1. **Output JSON, structurally**: same ids (nothing added/removed), required
   fields present, nothing off-canvas, images kept in proportion (non-cover
   images: aspect ratio within ~5% of source), etc.
2. **Rendered PNG**: output JSON rendered by the official renderer (the one
   vendored in `renderer/`), then scored by an **AI evaluator (almost
   certainly a vision-language model) against a rubric**:
   - No unwanted collisions (intentional layering is fine; text must never
     sit on a busy image)
   - Everything readable (size + contrast; nothing cut off)
   - On brand (colours, fonts, logo intact and in proportion)
   - Looks intentional (alignment, even spacing, hierarchy — most important
     element still stands out, pictures keep proportions)
   - Holds up everywhere (robust across many designs/shapes)
   - Speed & reliability is a rubric row (but no hard time limit; quality first)
   - Faithfulness to the original design's intent is weighted

## Hard rules
- Every source id appears exactly once in the output. No adding/removing.
- **Never regenerate/redraw/replace image pixels (incl. generative AI) — DISQUALIFYING.**
- `font_size` may change. `content` and `font_family` must NOT change in stage 1.
- Nothing outside target canvas bounds (main.py self-check: x,y >= -0.5 and
  x+w, y+h <= canvas + 0.5, computed on the UNROTATED box).
- No hand-tailoring to specific designs/sizes (hidden test set).
- Runs offline in Docker: `docker build --platform linux/amd64`, `docker run --network none`.
  Everything (deps, model weights, datasets) must be baked in at BUILD time.
- Local models allowed, but under a (TBD) size limit and an approved open-model
  list (TBD). Fine-tuned weights/LoRA must be public (e.g. HF).
- Reference scoring machine: Apple M5 Pro (RAM etc TBD). NOTE: Docker on macOS
  has NO GPU/Metal access and `linux/amd64` on Apple Silicon runs under
  emulation — any model inference in-container is CPU-only and slow-ish.
- Target sizes come from a fixed catalogue of real platform formats
  ("Instagram Post", "YouTube Thumbnail", leaderboard 728×90, story 1080×1920,
  etc.) — you may rely on that catalogue as a "fixed material". Brand colours,
  fonts, logo are also fixed materials.

## Inputs have NO semantic labels
You get `id`, `type`, geometry, style. In the samples the ids are human-readable
("headline", "cta_bg", "logo") but **do not rely on ids** — hidden data may use
opaque ids. Roles (background, logo, hero image, headline, subhead, CTA, badge,
legal text, decoration) must be inferred from geometry, typography, z-order,
grouping, asset image pixels, etc. Inputs may also carry extra keys like
`_note` — pass unknown keys through untouched.

## Schema (chameleon_design_schema_v0.9.json, summarized)
canvas {width:int, height:int}; element required: id, type, x, y, width, height.
Optional common: rotation (deg, clockwise about centre), opacity [0,1],
z_index (int), group_id (elements sharing it are a designer unit — e.g. button
shape + label — "meant to travel together").
text: content, font_family, font_size(>=1), font_weight(regular|bold),
font_style(normal|italic), color rgba(), text_align(left|center|right),
line_height(1.2), letter_spacing, max_lines, style_runs[{start,end,color,font_weight,font_style}].
image: asset_id, fit(contain|cover|fill; default contain).
shape: shape_type(rectangle|ellipse|line), fill_color, stroke_color, stroke_width, corner_radius.

## The three samples (input/*.json)
- L1 warmup: 1080×1080 → 1080×1350. bg cover image, logo, headline text, cta text (4 els).
- L2 core: 1080×1080 → **1600×400**. bg, 2 translucent decorative circles (one
  bleeds off canvas at -100,-100 — intentional), logo, product (bottle) image,
  headline with 2-colour style_run, subhead, badge group (pill shape + label),
  cta group (pill shape + label). 11 els.
- L3 advanced: 1080×1350 → **728×90** (leaderboard). 17 els: bg, logo, product,
  a run-on 140-char headline, a 190-char subhead, 3 badge groups, cta group,
  a ribbon group rotated -12°, an image whose asset is MISSING
  (renders as a grey "missing asset" placeholder box!), 120-char legal text.
Brand assets (brand_kit/assets): solstice_bg_gradient.png 1200×1500 RGB (dark
gradient + dots), solstice_bottle.png 800×800 RGBA, solstice_logo_lockup.png
900×300 RGBA. Fonts: Solstice Serif / Solstice Sans (regular/bold/italic).

## The official reference picture (from the brief)
The brief shows a "reference output — one design, four canvases": 1080×1080
post (logo top, product, headline, subhead, CTA stacked & centred), 1080×1920
story (same stack, taller), a poster with a split colour-block layout, and a
**728×90 leaderboard: logo on the left, "Chase the Light" + one-line subhead in
the middle, a pill "Shop" button on the right — the product image and badges
are simply GONE**. So graceful dropping of low-priority elements is clearly
the intended behaviour at extreme ratios. Since ids can't be removed, "drop"
must be expressed some other way (e.g. opacity 0 — unconfirmed whether the
scorer accepts that; tiny/hidden-behind tricks are probably seen as dishonest).
The brief's illustrative 1080×1920 example: product kept in proportion,
headline font scaled UP (size 150, wraps to 2 lines).

## Renderer facts you MUST know (renderer/converter/*.py, cr-renderer/skia)
- Elements drawn in z_index order. Rotation about centre.
- **Text box height is ignored by the renderer** — text is greedy-word-wrapped
  to the box WIDTH using real skia glyph widths (`renderer/converter/wrap.py`:
  `char_widths()` + `wrap_text()`), then drawn from the top; extra lines
  overflow downward and are NOT clipped. A single word wider than the box
  overflows horizontally. => The engine must do its own text fitting, and can
  import these exact functions to measure precisely what will render.
- Image `fit` is emulated in `renderer/converter/assets.py`: contain =
  letterbox centred in box; cover = scale-to-fill + CENTRE crop (no focal
  point control); fill = stretch.
- Shapes are rasterized with PIL (rounded rects, ellipses, lines); opacity
  applied as paint alpha; fill alpha multiplies opacity.
- Missing asset => grey placeholder with red border and "missing asset" text.
- Baseline (uniform stretch) renders are in `output/*.png` — look at them.
- The installed venv includes `datasets`/`huggingface_hub` (cr-renderer deps);
  the Crello dataset (CyberAgent, ~20k designs in many sizes) is public on HF
  and could be baked into the image at build time if useful.

## Debate rules
- Work in `design/debate/`. Write ONLY inside your own files/folders there
  (e.g. `design/debate/round1/<your_name>.md`, spikes in
  `design/debate/spikes/<your_name>/`). Do NOT edit `engine/`, `renderer/`,
  `input/`, `brand_kit/`, and do NOT run any git commands.
- You may run quick experiments (spikes) with `.venv/bin/python` to validate
  claims — e.g. measure text with the real renderer, render a hand-built JSON
  via `renderer.converter.convert.render_design_to_png(design, "brand_kit/assets", out_png)`
  (run from the repo root). Evidence beats assertion.
- Goal: an approach that is genuinely clever and unique AND realistically
  buildable by a small student team, robust on hidden data, and scores high
  with a VLM judge. Brilliance that can't ship loses to boring that works.
