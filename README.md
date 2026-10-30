# CHAMELEON — our engine submission

**`engine/resize.py` is implemented.** It calls the `engine/chameleon/` package, which re-lays-out a design for a new
canvas without templates: it infers each element's role from geometry and type, searches row/column/stack layouts
with one shared type scale, typesets and verifies the best candidates with the official renderer, and falls back to
a safe layout if anything fails. Every source element stays present and visible (nothing is hidden or dropped),
source styling is preserved, and it runs fully offline with no model or weights. See **"Design reasoning and
trade-offs"** at the end of this file and `ENGINE.md` for the pipeline.

**How to run:** `pip install -r requirements.txt && python -m engine.main` (reads `input/*.json`, writes
`output/<task>_output.json` and `.png`), or the Docker commands under "Docker" below.

The rest of this file is the organisers' starter README, kept for reference.

---

# CHAMELEON — starter repo

This is the scaffolding for your engine. It handles input loading, output
writing, rendering, and Docker packaging — so the only file you need to
edit is **`engine/resize.py`**.

```
input:  a task JSON (source design + target canvas)
              |
              v
        engine/resize.py   <-- YOU IMPLEMENT THIS
              |
              v
output: <task>_output.json  (schema-valid resized design)
        <task>_output.png   (rendered preview)
```

Both the JSON and the PNG are what get evaluated — see `RULES.md`.

## Repo layout

```
engine/
  resize.py        <- implement your approach here
  main.py           <- orchestrator (input -> resize() -> output). Don't need to edit this.
renderer/           <- the real renderer (transformer-convertor + cr-renderer), already vendored
brand_kit/
  assets/           <- image files referenced by asset_id in the sample designs
  fonts/            <- font files matching the schema's font_family values
input/               <- drop task JSON files here for local testing (3 samples included)
output/              <- results land here
chameleon_design_schema_v0.9.json   <- full field-by-field spec for the design format
Dockerfile
RULES.md
```

## Quick start (no Docker needed for iterating on `resize()`)

```bash
pip install -r requirements.txt
python -m engine.main
```

This processes every `*.json` file in `input/` (the 3 sample designs are
already there — one per difficulty level) and writes an `_output.json` and
`_output.png` for each into `output/`.

The included baseline is a **uniform stretch** — deliberately the wrong
approach (see the main brief: "a naive program stretches the picture; a
good one moves the furniture"). It's there so the pipeline runs on day
one. Run it once, look at `output/*_output.png`, and you'll see exactly
why it's not good enough — that's the point. Replace the body of
`resize()` in `engine/resize.py`, not just its constants.

## What the self-check does (and doesn't do)

`main.py` runs a quick structural check after every task — same element
`id`s as the source, required fields present, nothing off-canvas. **This
is not the official scorer.** It exists to catch obvious mistakes before
you waste a submission on them. See `RULES.md` for what's actually
checked and graded.

A self-check warning does not fail the run — your JSON and PNG are still
written either way. Read the warning; decide whether it's a real problem
or, like the Level 2 sample's intentionally corner-bleeding decorative
circle, an expected one.

## The renderer

`main.py` calls `renderer/converter/convert.py`'s `render_design_to_png()`
(a vendored copy of `transformer-convertor`, wrapping `cr-renderer`) to
produce each task's PNG — already wired in, no setup needed. It reads
fonts/assets from `brand_kit/` and writes a real rendered preview, not a
placeholder. If you ever see plain labeled boxes instead of real text and
images in `output/*.png`, that means the import in `main.py` failed (e.g.
`cr-renderer` didn't install — check `requirements.txt` installed cleanly)
and it silently fell back to the box-and-label placeholder; don't judge
your layout quality by that fallback.

## Docker (how you'll actually be run)

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .
docker run --rm --network none \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  my-chameleon-engine
```

`--network none` matches how stage-one scoring runs: everything your
engine needs must be installed at **build** time (add it to
`requirements.txt`), not fetched at run time. If you're using a locally
hosted model, bake its weights into the image during the build step.

## See also

- `chameleon_design_schema_v0.9.json` — full input/output field spec
- `RULES.md` — what's checked, what's graded, and what disqualifies a submission
- FAQ — for anything not covered above

## Design reasoning and trade-offs

`engine/resize.py` calls the `engine/chameleon/` package (see `ENGINE.md` for the pipeline). The engine has no
templates: it reads the design, decides what each element is for, and lays it out again for the new canvas.

**How hierarchy is inferred.** Roles come from features only, never from ids. The text with the largest perceived
size is the headline; small, low or long text is legal; bold imperative or saturated short text is the CTA; a
picture that is small, wide or sparse and near an edge is the logo, the largest picture is the hero. Shapes that hold
text become pills, cards or panels. Reading order comes from a recursive cut on the visible ink, which also gives the
source's own structure (rows, columns, stacks).

**How candidates are generated and ranked.** A candidate is a grouping of the reading-order units into rows, columns
and stacks plus one shared type scale, found by bisection against the renderer's own text wrapping. Each role scales
with its own elasticity and has a legibility floor. Candidates are scored on size, legibility, line breaks,
hierarchy, image-to-type ratio and closeness to the source structure (which dominates near the source canvas). The
best few are typeset (balanced wraps, no widows, optical centring, consistent margins), rendered, and checked by a
pixel critic and a rule set. The pick is lexicographic: hard vetoes, then rule violations, then energy. Decorations
and stickers are placed after the content so they never decide the layout.

**How collisions are resolved.** Boxes are kept disjoint by construction. Rules and dividers slide to the nearest free
spot, a sticker goes to its source corner, the mirrored corner or the hero's shoulder, and a sticker inside a card
stays on that card. Text on a photo is judged against the exact centre-crop the renderer draws; calm regions are
preferred and busy placements are penalised. Intentional overlap (a sticker on a product, a label on its pill) is
kept.

**Dense small formats.** When a design cannot meet its legibility floors, the floors are relaxed step by step, fine
print first (badges, legal) and the headline last, so the message keeps its size. A type-order repair then keeps the
source's order of importance (a text that was smaller in the source is never drawn bigger; stickers grow, other
texts step down). If even the relaxed search finds no plan (320x50 with a long design), the minor units are carved
out of the flow into one fine-print band along the bottom edge, and the rest is laid out above it.

**Deliberate trade-offs.**
- *Never hide.* Nothing is dropped, faded or shrunk to a speck: every source element stays present, visible and
  on-canvas, and a missing asset stays a visible placeholder. The cost is very small type on dense strips.
- *Floors relaxed stepwise, not abandoned.* Each level lowers the floors a little and keeps the type hierarchy until
  the last levels, so a result is as legible as the content allows.
- *Source styling preserved.* Colour, weight, alignment, line height, z-order and fit are never changed;
  letter-spacing only scales down with the font; images keep their aspect and centre crop. Because text colour is
  fixed, text over a photo is moved to calm, high-contrast regions rather than recoloured or backed by an added
  scrim; where a crop is busy everywhere (a meadow strip) the engine keeps the least bad spot.
- *The source is a fixed point.* A target equal to the source canvas returns the source layout, uniformly scaled.
- *Runs offline, one process.* No network or model weights; slower cases take tens of seconds on one CPU.
