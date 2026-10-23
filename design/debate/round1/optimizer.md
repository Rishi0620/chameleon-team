# OPTIMIZER — Retargeting as an exact, structured optimization

## 1. Core idea and the one insight

Treat `resize()` as a mixed discrete/continuous optimization, but **put the aesthetics into the search space, not into penalty terms**. The engine enumerates a few hundred layouts that a designer would draw anyway: slot topologies, which atoms are visible, and image scale tiers. Each one is solved exactly and scored with a rubric-shaped energy. A pixel critic built on the official renderer re-ranks the best few.

**The one insight: hierarchy-as-shared-variables makes the continuous problem monotone.** All text shares one type scale `z`, so `font_i = max(floor_i, round(z · f_src_i))`. Groups scale with their labels, and images take discrete tiers. With this setup, every element's footprint grows monotonically with `z`. So for a fixed discrete topology, "fits on the canvas" is a monotone predicate in `z`, and bisection finds the exact largest feasible layout in about 14 probes. The continuous part costs microseconds, so the discrete part can be searched exhaustively instead of stochastically. Hierarchy is preserved by construction, because ratios are shared rather than penalized. Alignment and even spacing come by construction too: slots share axes and gaps are a single variable. The energy only *ranks* layouts that are already well formed. It never has to *create* good form, which is where simulated annealing, CMA-ES and free-coordinate MILP produce "valid but ugly" jitter.

A second, smaller insight: **text is a discrete set of exact rectangles**. For each font size `f` and line count `k`, `W_k(f)` is the minimal box width at which the renderer's own greedy wrap (`wrap.py`, real skia advances) gives at most `k` lines. Greedy line count is monotone in width, so `W_k` comes from a binary search. A text block is then just a menu of `(W_k(f), H_k(f))` boxes, with the same arithmetic the renderer will use.

## 2. Architecture / pipeline

```
source + target
  │
  ├─ 1. Measure    fonts via the renderer's FontManager; asset alpha-bboxes; missing assets
  ├─ 2. Atomize    bg (≥85% area) │ decor (ungrouped shapes) │ flow atoms │ corner overlays
  │                groups → pill (shape+label) / sticker (rotated) / rigid; same-row pills → cluster
  ├─ 3. Annotate   importance, reading order, k_pref (source line counts), ordinal relations,
  │                legibility floors (from target size), copy budget  — features only, never ids
  ├─ 4. Search     for visible ⊆ atoms, image tiers, template, slot partition:
  │                    z* = bisection(feasible); widen(); score energy
  ├─ 5. Realize    slot packing, PAVA vertical faithfulness, optical pill centring,
  │                overlays (anchored corners, collision-tested), decor remap, honest hide
  ├─ 6. Critic     render top-K with the official renderer → pixel terms → re-rank
  └─ 7. Guard      structural validator; relaxation ladder; never-fail uniform contain fallback
```

Decision variables per atom: visibility `v_a ∈ {0,1}`, slot `s_a`, and order within the slot (inherited from source reading order). Text gets a line count `k_a` and `font = g(z)`. Images get a tier `ρ_a ∈ R_a` (≤ 7 values). Pills get elastic width between min-content and the source proportion. Globally there are `z`, the template `T`, and margin and gap, both functions of `z`.

Hard constraints, all checked exactly:
- Same ids.
- Every unrotated box in bounds, and the rotated AABB too for stickers.
- Non-cover image boxes keep their source aspect exactly.
- Groups stay rigid or elastic as one unit.
- Text fits: no word wider than its box, and `H_k(f)` fits the slot.
- Integer font sizes: the renderer casts `int(fontSize)` while `wrap.py` measures at float size, so integers make measurement equal rendering.
- Legibility floors.
- Ordinal hierarchy: if A reads ≥1.1× larger than B in the source, A must still read ≥ min(1.25, 1 + (r−1)/2)× larger.
- No visible overlap between flow atoms.

## 3. Key algorithms

**Text frontier (exact).**
```
W_k(el, f, k):                       # cached per (el, f, k)
    lo = widest_word(el, f); hi = single_line_width(el, f)
    if k == 1: return hi
    if lines(el, f, lo) <= k: return lo
    binary-search width in [lo, hi] until lines(el,f,w) <= k   (0.25 px)
H_k(f) = (k-1)·f·line_height + ascent(f) + descent(f)          # skia metrics, as rendered
```

**Slot feasibility and minimal width.** A slot is a vertical stack. Its minimal width is the smallest breakpoint `c ∈ {W_k(f_i)} ∪ {widest rigid}` at which the stacked heights fit. This is exact because height is a step function of `c` that only changes at breakpoints.
```
min_slot_width(slot, z):
    for c in sorted(candidate breakpoints ≥ lower bound):
        if Σ heights(c) + gaps + transparent-pad overhang ≤ H_avail: return c
    return INFEASIBLE
row_feasible(slots, z): Σ min_slot_width + gaps + max(m, left/right image overhang) ≤ W
```

**Monotone bisection + Occam search.**
```
for visible in subsets(optional atoms) (≤64; else importance-prefix + 1-swap):
  for ρ in product(image tiers):                       # tiers ⊂ z_ref·{.5,.7,1,1.4,2} ∪ {fit_max, .8·fit_max}
    for k in 1..max_slots(aspect):                     # 1 (tall) … 4 (≥3:1)
      for slots in contiguous partitions of reading order into k:
          z* = bisect(lambda z: row_feasible(slots, z, ρ), 0.03, z_cap)
          if hierarchy_ok(z*):
              widths = widen(slots, z*)                # spend leftover width on fewer lines, toward source k
              cand.append((energy(...), layout))
re-rank top-K by pixel critic; return best
```
Contiguous partitions keep source reading order. Vertical order turns into left-to-right order when the canvas becomes a banner. That is the faithful "unrolling" a designer does.

**Vertical faithfulness via exact isotonic regression.** For near-aspect retargets (L1), the stack should keep each atom near its source relative height. The problem is `min Σ w_i (c_i − t_i)²` subject to `c_{i+1} − c_i ≥ (h_i + h_{i+1})/2 + gap`. Substituting `s_i = c_i − offset_i` turns it into plain isotonic regression, which pool-adjacent-violators solves exactly in O(n). The canvas bounds are then a clip. It needs no QP library and has no tuning.

**Energy** (lower is better). Weights are hand-set in the spike and fitted to judge preferences in production (§7):
```
E = 1.6·Σ_hidden imp                          drop cost (importance from features)
  − 1.0·Σ_vis imp·log(scale/z_ref)            bigger is better, relative to area-scale
  + 4.0·Σ_text imp·hinge((f_comf − f)/f_comf)²  legibility (f_comf = max(14, 1.8% of long side))
  + 3.0·max(0, chars·f_comf²·0.55/area − 0.5) copy budget: can the canvas be *read*?
  + 0.15·Σ imp·max(0, k − k_src)              line-break faithfulness
  + 0.12·Σ imp·max(0, k − 2) + 0.08·widows    typographic texture
  + 0.25·Σ imp·|log(ρ/z)|                     image-vs-type proportion drift
  + 0.5·[source-larger image became smaller]  visual hierarchy among images
  + 0.06·(slots − 1) + 0.1·order inversions + 0.8·underfill
  + pixel critic (top-K only): contrast below the SOURCE's own contrast, glyph-over-edges density
```
Every pixel term is measured relative to the source. The brand's white-on-orange CTA is 3.2:1 in the source, and an absolute WCAG penalty would push the solver to "fix" the brand.

**Combinatorial choices.** Hiding is a variable with a cost, never a rule. Atoms drop for three reasons. First, they cannot meet a recognisability or legibility floor, or the ordinal hierarchy, at the best `z`. Second, they blow the copy budget. Third, their drop cost is lower than the size and legibility they steal from others. Row versus column is the template variable `k`, bounded by aspect. Overlays such as corner badges and rotated ribbons are anchored to their source corner and kept only if their rotated AABB clears flow content.

**Honest hide** (spike finding, §8): `opacity: 0` plus a fully transparent `color` and `style_runs` colors, with the box shrunk and kept in bounds. *The renderer ignores `opacity` on text.*

## 4. Walk-through: what the engine outputs (from the spike, not imagined)

**L1 1080×1080 → 1080×1350.** The best layout is a single slot at `z = 1.677`, which is the cap of `max(1.5·z_ref, 1)`. The logo is ×2.51 (box 138,53, 804×251). "Chase the Light" is set at 101px on one line (box 162,560, 756×129). The CTA text is 50px on one line (162,777). PAVA keeps the logo near the top and the headline and CTA where the source had them, at 46% and 60% height. The runner-up layouts were the same but with a 2-line headline and a larger logo, ΔE = 0.10, and a 2-column split, ΔE = 0.42. The line-break term is what rejected "Chase / the / Light", the defect v1 shipped (§8).

**L2 1080×1080 → 1600×400.** This is a 3-slot row at `z = 1.111`.
- **Slot 0:** the logo at ×1.48. Its box is (64,140, 474×163), and transparent padding hangs into the margin.
- **Slot 1:** the bottle at ×0.70, box (414,22, 352×352), which is height-limited.
- **Slot 2:** a 716px column with the headline at 62px on one line, keeping its 2-color style run (784,46). Below it, the subhead at 27px on one line (784,172), then the CTA pill 458×98 with a 24px label at (913,256). The label is optically centred on cap-height from skia metrics.

The "NEW FLAVOR" badge is classified as a top-left corner overlay and lands at (36,22), 186×62. It layers over the 15%-opacity decor circle, which is intentional layering. Decor circles are remapped and clamped in bounds. The close alternatives were a separate CTA slot (ΔE = 0.17) and a larger logo (ΔE = 0.16).

**L3 1080×1350 → 728×90.** This is a 4-slot row at `z = 0.407`:
- Logo ×0.42: box (0,29.5, 136×42), visible about 55×31.
- Bottle ×0.19: box (91,6, 76×76), visible about 32×52.
- Headline at 16px bold serif on **3 lines**, centred in a 378px box at (166,16).
- CTA pill 151×41 at (564,25) with a 10px label.

Hidden atoms are the subhead, all 3 badges, the ribbon, the legal line and the missing-asset watermark, each with opacity 0 and transparent text. Why the subhead drops: 140 + 190 characters blow the copy budget for a 728×90 canvas (load ≈ 1.05 against 0.5). Without the subhead, the headline climbs from the 10px floor to 16px. The ribbon cannot clear the flow, and the badges and legal text cannot hold their floors and hierarchy. The product is kept with these weights: E = 0.45, against 0.92 for the best layout without it (logo | headline 15px | CTA). The brief's reference drops the product, so this is the most weight-sensitive decision in the whole set and a priority target for calibration. Run on L2 → 728×90, the engine gives exactly the brief's reference: logo | "Chase the Light" 29px | 3-line subhead | pill, with the product and badge dropped.

## 5. Against the rubric

| Rubric row | Mechanism |
|---|---|
| No unwanted collisions | Flow atoms are disjoint by construction, with no overlap constraints to tune. Overlays need a clear rotated AABB. Decor overlap is allowed as intentional layering. The pixel critic flags glyphs over edges: the baseline L3 badge labels score 0.51 edge density, ours ≤ 0.021. |
| Readable | Exact wrap and metrics make "nothing cut off" exact. Legibility floors and a hinge are scaled by target size. The copy budget stops long copy being squeezed in at unreadable sizes. Contrast is relative to the source. |
| On brand | Content, family and colors are untouched. Logo aspect is exact, and a recognisability floor applies to visible pixels. Style runs are preserved. |
| Looks intentional | Shared axes and a single gap variable give alignment and rhythm by construction. The ordinal hierarchy is hard. Image/type proportion and image hierarchy are energy terms. Pills are optically centred. |
| Holds up everywhere | 21 runs (3 designs × 7 catalogue sizes) were all feasible and all passed the structural checks. A relaxation ladder and a never-fail contain fallback back them up. |
| Speed & reliability | 0.01–0.2 s on the official targets and ≤ 4.8 s worst case, in un-optimized pure Python. It is deterministic, with no model weights. |
| Faithfulness | Source reading order is kept through contiguous partitions. Source line counts, source relative heights (PAVA) and source proportions are kept, and source contrast is the baseline. |

## 6. Risks and mitigations

1. **Role inference is wrong**, for example a decorative image taken as the hero. Importance only enters as soft costs, and only the top roles are must-keep. Features are geometric plus alpha content, never ids. Add a confidence score and widen the "must" set when uncertain.
2. **Weights overfit to three samples.** This is the real risk. Retarget Crello designs to catalogue sizes, generate energy-ranked candidate pairs, and collect pairwise preferences from a VLM judge at *development time*. Then fit the weights with Bradley-Terry: the energy is linear in its terms, so this is logistic regression on term differences. Only about 15 floats ship. CMA-ES belongs in this outer loop, not in layout.
3. **Topologies the grammar can't express**: split color blocks, text over full-bleed photos, Z-patterns. Add templates incrementally (SPLIT, OVERLAY-with-calm-region from the critic, GRID-2×2). Each one is a feasibility function plus a placement, and the search and energy are reused.
4. **Combinatorial blow-up** with more than 12 free atoms. Pre-cluster rows, groups and text stacks. Prune with branch-and-bound, since the drop cost plus the size reward at `z_cap` bounds E. If needed, move the same model onto OR-tools CP-SAT: slot booleans, presence literals, and NoOverlap2D with optional intervals.
5. **Opacity-0 drops judged dishonest.** This is a policy switch, not a rewrite: set the drop cost to ∞ and the solver keeps everything at its smallest legible tier. Packing by visible bbox also makes transparent-padding boxes overlap in the JSON, as with the L2 logo and product. If a structural overlap check exists, pack by box instead.
6. **Logo dominance**, seen in the spike at L1 → 1280×720, logo ×3.8. Add a cross-type ordinal constraint so visual weight keeps its source order.
7. **Optical margins.** Transparent padding pins the logo box at x=0 in L3, so the visible left margin is about 50px against 13px on the right. Equalize visible margins as a final 1-D LP.
8. **Non-monotonicity** from integer rounding and `z`-scaled margins. Bisection can be off by one font step, so finish with a ±2-step probe.

## 7. Build plan (2–3 people)

| Days | P1: measurement + search | P2: semantics + energy | P3: quality harness |
|---|---|---|---|
| 1–3 | Text frontier, metrics cache, atoms (pills, clusters, stickers) | Role and importance features, ordinal relations, floors | Batch runner, contact sheets, structural validator, Docker |
| 4–7 | Templates, partitions, bisection, widen, PAVA | Energy v1, copy budget, hide policy | Crello → retarget task generator (200 designs × catalogue) |
| 8–10 | Overlays, decor remap, relaxation and fallback | Pixel critic (underlay render, edge/contrast) | VLM pairwise-preference collection (dev time) |
| 11–14 | Branch-and-bound, perf | Weight fitting (Bradley-Terry) and ablations | Robustness sweep, regression gallery |

The core is about 900 lines of Python. The only dependencies are numpy, skia and PIL, which the renderer already uses. For the finale, the energy terms *explain* every decision ("subhead hidden: copy budget 1.05 > 0.5"). That makes for a strong jury demo, and add-on sliders map straight onto the weights.

## 8. Spike evidence (`design/debate/spikes/optimizer/`)

Run from the repo root: `.venv/bin/python design/debate/spikes/optimizer/solver.py [--all]`.

1. **Text frontier is cheap and exact.** One `char_widths` call takes about 0.5 ms. The whole frontier is computed lazily and cached. Measurement shares the renderer's `FontManager`, and font sizes are integers to match `int(fontSize)` at render time.
2. **Hiding (`hide_test.py`).** Text with `opacity: 0` renders **exactly as visible**: 2,961 dark pixels both ways, because `render_text_fill` calls `paint.setColor()` after setting the alpha. A transparent `color` hides it (0 pixels). Shapes, images and missing-asset placeholders do honor `opacity: 0`. **Any team that "drops" text via opacity alone will show stray text in the PNG.**
3. **The "valid but ugly" failure is real (`solver_v1.py`, `out_v1/`).** A pure max-zoom objective produced "Chase / the / Light" on 3 lines at 101px. In L3 it kept the 190-character subhead at the same 10px floor as the headline, and 0-opacity badge labels re-appeared at 22px. Every structural check still passed. v2 fixed it with line-break faithfulness, the copy budget, hard ordinal hierarchy and honest hide, without touching the search.
4. **v2 results (`out/`, `log.txt`, `log_all.txt`, `sheet_L*.png`).** All 3 official targets and 21 runs across catalogue sizes (728×90, 1600×400, 1080×1920, 1080×1080, 300×250, 1280×720, 160×600) are feasible and pass id, bounds and aspect checks. Two skyscraper cases needed relaxation level 1. Solve times are 0.01–4.8 s, and rendering takes 27–150 ms.
5. **The pixel critic is affordable (`pixel_critic.py`).** An underlay render takes 27–74 ms, so verifying the top 8 costs under 1 s. It separates bad from good: baseline L3 badge labels sit on 0.51 edge density, against at most 0.021 for ours.
6. **Known defects:** logo dominance at L1 → 1280×720; the skyscraper CTA wraps to 3 lines; the L3 optical margins are unequal; and keeping the L3 product depends on the weights. Each is a missing term, not a missing mechanism.
