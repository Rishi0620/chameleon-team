# INVENTOR — GALLEY: a design is a paragraph

*Retarget a design by decompiling it into a typesetter's galley, then re-breaking that galley for each new canvas with Knuth–Plass-style search. Spike code: `design/debate/spikes/inventor/` (renders in `out/`).*

---

## 1. Brainstorm: 12 framings, scored

Scores are 1–5 for **O**riginality, **F**easibility (offline, CPU, small team, a few weeks), **R**obustness on unseen designs, and **V**LM-judge appeal.

| # | Framing | O | F | R | V | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Perceptual relation graph** (alignment, containment, proximity, order), re-solved for new coordinates | 3 | 3 | 3 | 3 | At an 8:1 ratio a vertical stack's "above" relations can't all hold, and choosing which ones to break is the whole problem. GALLEY keeps alignment, glue and order *by construction*. |
| 2 | **Design DNA**: decompile to a flexbox program, re-run it with reflow rules | 4 | 4 | 3 | 4 | Right IR, wrong executor: flex-wrap breaks lines greedily, never omits, and its reflow rules turn into templates. *Absorbed as the IR.* |
| 3 | **Seam carving** of whitespace | 4 | 4 | 2 | 2 | Works up to about 1.5× aspect change. It can't turn a stack into a row, which L2 and L3 both need. |
| 4 | **Force-directed / physics** | 2 | 4 | 2 | 1 | Organic and unaligned, so it reads as undesigned. |
| 5 | **Designer-operator search** (MCTS or beam) against a scorer | 3 | 3 | 3 | 4 | The space is unbounded and ill-structured, and the result is only as good as the scorer. Overlaps the critic agent. |
| 6 | **Analogical transfer** from Crello size families | 4 | 2 | 2 | 3 | Crello has no aligned multi-size families and no role labels. Heavy to bake in, and retrieval misses on novel content. |
| 7 | **Round-trip** A→B→A self-consistency | 4 | 3 | 3 | 2 | Needs an invertible engine. *Absorbed as the fixed-point invariant (§6).* |
| 8 | **Auction / rent** for space by priority | 4 | 4 | 3 | 3 | A good rule for what to keep, but silent on arrangement. *Absorbed as "rent".* |
| 9 | **Cartographic generalization** (Töpfer's radical law; selection, exaggeration, displacement) | 5 | 4 | 2 | 3 | The radical law is miscalibrated here. For L2→728×90 it keeps 6·√(65 520/1 166 400) ≈ **1.4** units; the brief's reference keeps **4**. *Absorbed: exaggeration (legibility floors) and displacement (furniture).* |
| 10 | **Inverse procedural modeling**: split grammars, as in façade retargeting (Wu et al., SIGGRAPH 2014) | 5 | 3 | 3 | 4 | Grammar induction is overkill for ≤20 elements, because a recursive XY-cut tree already *is* the grammar. *Absorbed as the decompiler.* |
| 11 | **Aspect homotopy**: drag the aspect ratio slowly and treat structural changes as bifurcations | 5 | 3 | 3 | 3 | Path-dependent. A great finale demo (live drag-resize). |
| 12 | **GALLEY**: Knuth–Plass re-breaking of a decompiled reading stream | **5** | **5** | **4** | **4–5** | **Winner.** Fuses 2, 7, 8, 9 and 10. |

**Why GALLEY wins.** The others work in continuous 2-D space (local minima, unaligned output, hand-tuned constraints) or need data we don't have. GALLEY makes retargeting a small discrete problem solved exactly with TeX's boxes, glue and penalties. The spike shows it on all three samples and on an untuned split layout.

## 2. Core idea and the "genius" insight

**Core idea.** Decompile the source into a galley:
- a canvas layer (the background);
- texture (ornaments);
- page furniture (corner stickers);
- a **stream** of content units in reading order, with TeX-style glue between them.

Then typeset that stream onto the target canvas. Search every order-preserving way to break it into rows (¶), columns (|) and stacks (/), and every priority-ordered set of omissions. For each candidate, find the largest uniform type scale that fits, and keep the best by one objective.

**The insight: changing the aspect ratio is a line-breaking problem.**
- A square post sets the paragraph one "word" per line: logo ¶ product ¶ headline ¶ subhead ¶ CTA.
- A leaderboard sets the same paragraph on one line: logo | headline / subhead | CTA.
- Because reading order doesn't change, the space of designer-plausible layouts collapses from continuous 2-D placement to a few hundred break patterns, and these can be searched exhaustively (or optimally with DP).
- Banner conventions are **not written anywhere in the code; they come out of the optimisation**. The spike's top layout for L2→728×90 has the structure the brief's reference leaderboard is described as having: logo left, headline plus one-line subhead in the middle, pill CTA right, product and badge gone. No template exists in the code.

## 3. Architecture

```
source ──► MEASURE   exact renderer metrics: skia glyph widths at int font sizes, real wrap_text(),
             │        asset alpha bounding boxes (ink), rotated AABBs
             ▼
          DECOMPILE  layers:   canvas | texture | furniture@corner | hidden (unresolvable asset)
             │        program:  recursive XY-cut → rows ¶ / columns | / stacks /  (= source labels)
             │        glue:     natural width = the source designer's gap
             │        rent:     feature-based priority (never ids); largest type = mandatory
             ▼
          TYPESET    for stream ∈ {source order, brand-mark-first}
             │          for omission prefix k (lowest rent first)
             │             for break pattern ∈ {/,|,¶}^(n-1) (canonical)
             │                s* = max type scale that fits (bisection);  J = objective
             ▼
          EMIT       TeX glue: shrink to fit → stretch back toward natural; leftover by source ratio ρ
             │        column alignment from text_align; images grow into slack; edge-image padding reserved
             │        furniture → same corner if collision-free; texture re-anchored (kept round, in-bounds)
             │        omitted → opacity 0 AND colour alpha 0 (see renderer finding, §8)
             ▼
          VALIDATE   ids, bounds, image aspect ±5 %, content/font unchanged, int font sizes → fallback chain
```

Deterministic; no model weights; no new dependencies (numpy, PIL, skia).

## 4. Key algorithms

**4.1 Decompiler**
```
xycut(atoms):                       # Nagy & Seth recursive XY-cut on INK boxes
  gy, gx = empty-gap groupings along y and x
  if no gap on either axis: return island(atoms)        # overlapping cluster → rigid unit
  pick the axis whose widest gap / canvas-dim is larger  (ties → y: read top-down)
  return node(axis, [xycut(g) for g in groups])

flatten(node, level):               # map the tree onto the 3-level galley
  Y at row level → '¶' between children;  X → '|' (columns);  Y inside a column → '/'
  X inside a stack, or side-by-side look-alikes (same kind, similar height) → rigid chip-row
```
Rent, from features only:

| Feature | Rent |
|---|---|
| Text with the largest (bold-weighted) size | ∞ (mandatory) |
| Shape+text group ("button") | 1.0 |
| Wide, small image ("mark") | 0.8 |
| Short, bold, saturated text (text-only CTA) | 0.6 |
| Secondary text | 0.2 |
| Picture | 0.12 + area share |
| Chip-row | 0.06 |
| Fine print (≤13 px or <30 % of top size) | 0.03 |

**4.2 Fitting a break pattern at type scale s**
```
s_u = max(s, floor/smallest_font(u))      # cartographic exaggeration: type never drops below the floor
                                          # (rigid units capped to the live area)
for row: reserve edge images' transparent padding (box must stay on-canvas)
         images/groups take fixed width; text columns share the rest:
         start at natural width (source measure × s), shrink to longest word, grow to one line
         column height = Σ real-wrapped heights + shrunk glue
feasible ⇔ every row ≤ live width and Σ rows + glue ≤ live height
s* = geometric bisection on [0.02, s_cap],   s_cap = max(1, √(target area / source area))
```

**4.3 Objective and search**
```
J = U(s*) + Σ rent(kept) − 0.05·#transpositions vs source program
          − 0.15·#text pairs split sideways − clutter(>5 columns) − 0.03·[stream permuted] + 0.06·fill
U(s) = log min(s, 0.85 s_cap) + 0.2·log⁺(s / 0.85 s_cap)   # concave: a roomy canvas keeps everything
```
- **Uniform s** preserves the size hierarchy by construction.
- **Rent** is how much type scale a unit may cost before it gets deferred. A picture with rent 0.18 stays unless keeping it shrinks all the type by more than about 16 %.
- **Search size and cost.** Enumeration is 3^(n−1) patterns × (n+1) omission prefixes. For L3 (7 units) that's 647 patterns, ≤0.83 s in pure Python.
- **Larger n.** Use the Knuth–Plass DP. For fixed s, rows are independent: `H[i] = min_j H[j] + glue + rowheight(j..i)`, with inner column splits enumerated (rows hold ≤5 units). Keep a Pareto (height, penalty) frontier per state, and wrap it in the s-bisection and the omission prefixes. That's O(n²·2⁵) per s.

**4.4 Emit (TeX glue)**
- Fit with shrunk glue, then stretch each gap back toward its natural (source) width.
- Split the leftover above and below the block in the source's own top/bottom ratio ρ.
- Wide rows use space-between.
- Images grow into slack: marks ≤1.3× and ≤45 % of row height; pictures ≤1.8×.

## 5. Walk-through: what the engine outputs (spike results, rendered and inspected)

**L1 (1080²→1080×1350).**
- Program `logo ¶ headline ¶ cta` is kept.
- s* = 1.118: headline 60→67, CTA 30→33.
- Glue is restored to the designer's gaps (287/128 px × s), and the block keeps the source's top-heavy placement (ρ).
- The text-only orange CTA is recognised as accent text (rent 0.6), so at 728×90 it stays: `logo | headline / cta`.

**L2 (1080²→1600×400). Chosen: `logo | product | headline / subhead / cta_bg`, s* = 1.000.**
- **No type shrinks at all:** headline stays 56 px, subhead 24 px, CTA 420×90.
- The product box is 389×389, so the bottle fills the height.
- The logo grows into its column.
- The "NEW FLAVOR" badge stays a top-left corner sticker.
- The two deco circles are re-anchored (304 px and 183 px), kept round and pulled in-bounds.
- Runner-up: the same layout with the CTA as a fourth column (ΔJ −0.04).

**L2 → 728×90 (the brief's own reference case).**
- Result: `logo | headline / subhead | cta_bg`. The product is omitted (rent < the type scale it would cost), and so is the badge (its corner collides with the logo).
- Headline 27 px, subhead 11 px, CTA pill 210×45 with a 10 px label.

**L3 (1080×1350→728×90). Chosen: `logo | headline | cta_bg`, s* = 0.40.**
- The 140-character headline sets at 15 px in **4 lines inside a 349 px column (72 px tall in a 74 px live area)**. That is the largest legible set of this copy at this size, measured with the renderer's own wrap.
- The CTA is a 191×41 pill with a 10 px label (raised to the legibility floor).
- Omitted, in rent order: legal (0.03), badge row (0.06), product (0.15), subhead (0.20).
- The rotated ribbon is omitted because it has no collision-free corner slot. The missing-asset watermark is hidden, never shown as a grey box.
- Runner-up: `logo | headline / subhead | cta_bg` at s = 0.275 (ΔJ −0.18). Keeping the subhead would shrink everything to ~11 px.

**Other targets (all in `out/`):**
- L3→1600×400 keeps all content except legal (ΔJ only −0.005 to keep it too): `logo / product | headline / subhead / badges / cta`. The ribbon has no free corner, and the watermark is hidden.
- L3→160×600 skyscraper: logo ¶ 9-line headline ¶ subhead ¶ CTA.
- L3→300×250: logo ¶ headline ¶ CTA.
- Stories stay as faithful stacks.

**Fixed point (resize to the source canvas):**

| Sample | Mean centre drift | Max drift | Font change |
|---|---|---|---|
| L1 | 0.8 % of diagonal | 1.2 % | 0 % |
| L2 | 2.5 % | 9.3 % | 0 % |
| L3 | 1.5 % | 2.7 % | 0 % |

The 9.3 % maximum is the intentionally bleeding circle, which the in-bounds rule forces inside.

## 6. Why nobody else will think of this, and why it still wins the rubric

**Why it's unusual.** Teams working on "AI layout" reason in 2-D boxes (constraints, templates, critics). GALLEY reasons in **1-D**, as a reading stream, and imports three fields hackathon teams don't touch:
- typesetting (Knuth–Plass 1981; TeX glue);
- cartographic generalization (selection, exaggeration, displacement);
- inverse procedural modeling (façade split grammars).

**Rubric mapping:**
- **Looks intentional.** Every output is a row/column/stack grid with consistent glue, so alignment and even spacing hold by construction, not by penalty.
- **Hierarchy.** One type scale plus floors means the most important element always stays largest.
- **Faithfulness.**
  - The source program is always a candidate and wins at near-aspect ratios (fixed-point drift 0.8–2.5 %).
  - Reading order never changes, except a single permitted "logo leads" move.
  - Natural glue is the designer's own spacing.
- **No collisions.** Cells are disjoint by construction; only declared layers (texture, furniture) overlap.
- **Readable.** Exact renderer metrics plus a legibility floor.
- **Graceful dropping.** One rule (rent vs type scale) reproduces the reference leaderboard and keeps everything when there's room (L2→1600×400 keeps all 11 elements).
- **Speed and reliability.** Deterministic, about 1 s, no weights.
- **Plays well with others.** A ranked top-k of valid candidates for a critic to re-rank.

## 7. Risks, mitigations, build plan

| Risk | Mitigation |
|---|---|
| **Omission encoding.** Opacity 0 may be flagged, and *text opacity is ignored by the renderer* (§8). | Set opacity 0 **and** colour alpha 0 (including `style_runs`). Make it a policy switch; ask organizers. Worst case: never omit text, only images and shapes. |
| **Weights are hand-set and sensitive.** In the spike, a fill term at weight 0.25 flipped two results. | Only about 10 scalars. Calibrate on a corpus (W3) using pairwise VLM/human preference, then lock with snapshot tests. |
| **Near-ties are decided by tiny terms.** E.g. the unseen story kept `product | logo` side by side. | Hand the top-k to the critic agent's re-ranker. Add hero-image scale to the utility. |
| **Order preservation forbids some designer moves.** | A small permitted-move set: mark-first is already built; furniture to stream ends. |
| **Decompiler errors on collages or text-on-photo.** | Island units (rigid) are already built. Add host/rider overlays (text attached to its image). Fallback chain: DP → rigid letterbox → uniform scale. |
| **Rigid groups can't reflow** (button label wrap, badges onto two rows). | Nested galleys: a chip-row is itself a paragraph (v2). |
| **Transparent asset padding wastes space** (the logo is 30 % empty at the sides). | Ink-based layout with edge-overhang reservation (built). |
| **Legibility floor is a guess** (judge viewing scale unknown). | Single knob, calibrated in W3. |

**Build plan (2–3 students):**
- **W1 (≈4 person-days):** measurement and decompiler productionised. Unit tests, including the fixed-point test (drift < 3 %).
- **W2 (≈5 person-days):** DP typesetter for n > 9, emitter, alignment variants, omission policy, validator, Docker.
- **W3 (≈5 person-days):** corpus and calibration.
  - 300 synthetic variants (text length, element counts, split and left-aligned layouts, text on photo) plus about 200 converted Crello designs.
  - Render the full size catalogue to contact sheets and tune the weights.
- **W4 (≈4 person-days):** hardening. Islands and overlays, nested galleys, and fuzzing 10k random designs until crashes and invalid outputs are zero.
- **Finale:** an Express add-on with a **live aspect slider**. Typesetting takes milliseconds, so the design visibly re-flows as you drag. Show the break-pattern overlay (¶ | /) and let the designer lock a break.

The spike (~1000 lines) already covers about 60 % of v1.

## 8. Spike evidence (`design/debate/spikes/inventor/`)

**Files and how to run:**
- `galley.py`: the full decompile → typeset → emit → render pipeline. Run `.venv/bin/python design/debate/spikes/inventor/galley.py`.
- `unseen.py`: a split-layout 1200×628 design with opaque ids that the engine was never tuned on.
- Contact sheets in `out/`: `sheet_leaderboards.png`, `sheet_wide.png`, `sheet_tall_small.png`, `sheet_fixed_point.png`, `sheet_unseen.png`.
- Logs: `out/run_log.txt`.

**Findings:**
1. **It works on the samples.**
   - 15/15 sample retargets have **0 structural violations**: ids, bounds, image aspect ±5 %, content and font unchanged, integer font sizes.
   - I looked at every PNG. The leaderboards and 1600×400 banners look designed.
   - Search takes 0.00–0.83 s per target in exhaustive pure Python.
2. **The decompiled IR is readable.** For L3 it prints:
   ```
   logo ¶ product ¶ headline ¶ subhead ¶ row(badge1,badge2,badge3) ¶ cta ¶ legal
   ```
   with furniture `ribbon@TR`, hidden `holiday_watermark`, and rents.
3. **Renderer finding (important for every agent).**
   - cr-renderer **ignores text `opacity`**: `Paint.setColor` overrides `Alphaf`. `out/opacity_test.png` shows an opacity-0 text fully visible. Only colour alpha hides glyphs; images and shapes do respect opacity.
   - skia truncates `font_size` to an int at draw time, so emit integer sizes (or measure with `int()`).
4. **Unseen design.**
   - The first decompiler (horizontal bands only) **failed**. It merged the whole split layout into one omittable "row", which could drop the headline.
   - I replaced it with a recursive XY-cut. Now `e1 | e2 / e3 / e4 / e5` (product | copy stack) is recovered.
   - 728×90 → `logo | headline | CTA` and 1600×400 → the split is preserved with left alignment. Both look right.
   - The 1080×1920 story is **weaker**: it keeps product|logo side by side in row 1. The top 10 candidates were within 0.03 J of each other, which is the critic re-ranking case above.
5. **Honest sensitivity.** A canvas-fill bonus at weight 0.25 broke the L2 fixed point (drift went to 6 %) and dropped L1's CTA at 728×90. At 0.06 it's harmless. Calibration is real work, not a formality.
6. **What's not yet good.**
   - The rotated ribbon is dropped in every banner (corner placement is primitive).
   - Logo lockup boxes hug the canvas edge (x = 0) because of transparent padding.
   - CTA labels sit at the 10 px floor in leaderboards.
