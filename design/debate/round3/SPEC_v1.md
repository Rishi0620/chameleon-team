# CHAMELEON — SPEC v1: the bracketed galley engine

*Owner: INVENTOR. Status: v1 for the Round 4 red team. This spec unifies the Round 1–2 work of all five agents. Every number cited comes from a run in `design/debate/` (bench, spikes, proto).*

**Conventions used throughout**

| Mark | Meaning |
|---|---|
| ★ | A genuinely original idea that the score depends on (§0.2) |
| **OPEN** | Still contested; the evidence on each side is in §12 |
| `code` | A module or function in `design/debate/proto/`, with its owner in brackets |

---

## 0. One page

### 0.1 What we are building

**Goal.** Implement `resize(source, target_canvas) -> design`. The output keeps the same ids and is judged two ways:
- structurally: ids, bounds, aspect, frozen fields;
- by a VLM looking at the official render, against the rubric rows: collisions, readability, brand, intentional look, robustness, speed, faithfulness.

**Scorer model** (JUDGE): `Gate × [α·Structural + (1−α)·VLM]`. One crash or one broken render costs more than ten polish wins.

**The engine in one sentence.** Decompile the source into a *program*: a reading-order stream of content units joined by ¶ (row), | (column) and / (stack), with containers as nested sub-programs and the background, texture and furniture as separate layers. Then re-break that program for the target canvas with an exact, renderer-measured solver, and choose the best candidate under hard contracts, defect vetoes and a calibrated energy.

### 0.2 The five ideas that matter, and why they move the score

**★1 Retargeting is re-breaking a decompiled reading stream (the galley)** — INVENTOR, with OPTIMIZER's DP.
- Reading order is preserved, so the space of designer-plausible layouts collapses to a few hundred break patterns. Knuth–Plass DP with skip transitions searches them exactly, deterministically and in milliseconds.
- Banner conventions emerge rather than being templated. For example, L2→728×90 gives `logo | headline / subhead | cta`, the brief's reference leaderboard, from no rule about leaderboards.
- *Score:* rows **intentional look** (grid and glue by construction), **faithfulness** (order kept) and **holds up everywhere** (no template cliff).

**★2 The source is a constraint, not an oracle** — INVENTOR and OPTIMIZER, independently.
- At its own canvas, the designer's layout must beat everything the engine could have produced there. That gives three uses:
  - **CI:** fixed-point drift < 3%.
  - **Dev:** the weight fit is constrained to the inverse-optimisation cone of every corpus source.
  - **Runtime:** a trust-region calibration of the *structure* weights only, plus non-separability as a missing-feature detector.
- **Proven limits:** the source never identifies extreme-format exchange rates. Full per-design calibration made 728×90 headlines 10 px, and monotone size rewards are inconsistent with every source (w_size → 0).
- *Score:* **faithfulness**, plus robustness of hand weights (a single fill weight flipped results until the cone caught it).

**★3 Everything is source-relative** — PERCEPTION, DESIGNER, INVENTOR.
- Every threshold is measured on the designer's own render:
  - contrast;
  - busyness tolerated under type (×1.5);
  - collisions only if *new* (pairs that already overlapped in the source are intent);
  - coverage, empty bands and decoration-over-text.
- Halos, text on its own panel, a badge on a product, and the brand's 3.2:1 CTA are never "fixed".
- *Score:* **collisions** and **faithfulness**. It cut false defect flags by 22–31% and turned the critic's 4/4 disagreement into 3/4 agreement.

**★4 Containers and overlays are relations, not templates** — INVENTOR, OPTIMIZER, DESIGNER.
- **Container:** an opaque non-background shape holding content is a *host*; its riders are a **nested galley** solved by the same solver inside the host's cell, and the host bleeds to the edges it touched.
- **Overlay:** a full-bleed photo host makes **calm rectangles** of the *renderer-exact* target crop the candidate live areas.
- *Score:* **text never on a busy image**, **no lost backdrop**. Lost-backdrop / on-busy failures went from 12/6 to 0/0 (OPTIMIZER `r2_merged`); F2 beat v1 on 5/5 sizes; F1 1600×400 moved its copy into the only calm band.

**★5 Pixels veto defects; energy decides structure** — PERCEPTION and JUDGE.
- The render-in-the-loop critic is ~98% right on broken-vs-designed but only 36–64% on designed-vs-designed.
- So it is used for **vetoes and counts**, never as the objective:
  > contract → vetoes + hard rules → soft-rule count → energy → critic score only inside ΔE < 0.03
- "Defects first, then J" picked eye-better candidates in 91% of pairs, against 79% for either signal alone.
- *Score:* the **p10 / worst case**, which "holds up everywhere" and a VLM average both punish hardest.

Everything else is table stakes and must be exact: the renderer-gap contract, integer fonts, value-keyed caches and the fallback ladder.

### 0.3 Where we stand (bench: 15 designs × 26 sizes = 390 cases, `bench/SCOREBOARD.md`)

| engine (R1 spikes) | mean | p10 | strip | wide | squareish | tall | crashes / timeouts / hard |
|---|---|---|---|---|---|---|---|
| OPTIMIZER | 88.9 | 79.3 | 84.1 | 88.7 | 91.1 | **91.6** | 5 / 0 / 0 (stale `id()` cache) |
| OPTIMIZER + 1-line cache fix | **90.4** | **79.9** | — | — | — | — | 0 / 0 / 0 |
| GALLEY | 88.1 | 73.2 | 80.8 | **91.7** | 87.3 | 83.7 | 3 / 1 / 6 (empty result, font 0, rotated line, 180 s blow-up) |
| DESIGNER | 86.5 | 69.7 | **86.6** | 86.8 | 89.2 | 82.3 | 0 / 0 / 4 |
| safe floor | 71.9 | 43.5 | 46.9 | 73.6 | 85.2 | 74.4 | 0 / 0 / 0 |

Each R1 engine wins a different band, and each has a mechanical failure class. The merged engine's target is to **take the best band behaviour of each, with zero mechanical failures** (§10 gates).

---

## 1. Pipeline

```
 source, target ─► S0 NORMALIZE & MEASURE ─► S1 DECOMPILE ─► S2 REGIME & LIVE AREAS ─► S3 SEARCH
                     (contract-in)            (IR + info)      (overlay.calm_regions)     (DP / enum,
                                                                                            inner solver)
      ┌──────────────────────────────────────────────────────────────────────────────────┘
      ▼
 S4 REALIZE ─► S5 FINISH ─► S6 CONTRACT+REPAIR ─► S7 VERIFY (render top-K, critic vetoes, rules) ─► S8 PICK
                (finisher)    (every candidate,       (critic.py, rules.py)                         (lexicographic)
                               BEFORE render)                                                         │
                                                         S9 FALLBACK LADDER ◄── nothing survives ─────┘
                                                                  │
                                                                  ▼
                                                           S10 EMIT plain JSON
```

| stage | module (owner) | input → output | budget (native) |
|---|---|---|---|
| S0 | `contract.py`, `textfit.py` (OPT) | raw source → normalized source + measurement caches | < 20 ms |
| S1 | `decompile.py` (OPT, INVENTOR's IR) | source → `Galley` + `info` | < 50 ms |
| S2 | `overlay.py` (INV) | source, target, info → live areas | warm < 10 ms, cold < 150 ms |
| S3 | `search.py` (OPT) | Galley, target, live areas → ranked `Candidate`s | p95 < 1.5 s |
| S4 | `engine.py` (OPT) | Candidate → output design + `info` | < 10 ms each |
| S5 | `finisher.py` (DES) | output, info → output | < 30 ms each |
| S6 | `contract.py` (OPT, JUDGE's invariants) | output → output or reject | < 5 ms each |
| S7 | `critic.py` (PER), `rules.py` (DES) | output (+PNG) → vetoes, violations, penalty | ~80–200 ms each (render) |
| S8–S10 | `engine.py` | candidates → one plain-JSON output | — |

**Per-design wall-time target:** p50 ≤ 1 s, p95 ≤ 4 s native. That allows a 2–5× amd64 emulation factor inside a ~10 s soft cap (**OPEN O5**).

The search is **anytime**. A deadline check runs between candidates, and if time runs out the engine falls back to the best candidate found so far. That candidate has already passed the contract, because S6 runs before S7.

---

## 2. Data structures

### 2.1 Unit (the "word" of the galley)

```python
Unit:
  name: str                 # debug only, never used for decisions
  kind: "text" | "image" | "pill" | "chips" | "rigid" | "bracket"
  ids: list[str]            # element ids this unit owns (group members travel together)
  role: str                 # headline|subhead|body|logo|hero|cta|badge|sticker|legal|... (features, never ids)
  rent: float               # cost of omitting it; inf = mandatory (P0 = headline, cta, logo; see §7.1)
  src_ink: (x0,y0,x1,y1)    # visible-pixel box in source coordinates
  src_box: (x0,y0,x1,y1)    # union of element boxes (rigid/pill geometry)
  fs_src: {id: font_size}   # for text-bearing units
  ink_rel: {id: (fx0,fy0,fx1,fy1)}   # ink as a fraction of the element box (images: alpha bbox under contain)
  inner: Galley | None      # kind == "bracket": the host's riders as a nested galley (★4)
  host_id: str | None       # bracket: the container shape id
  touches: set[str]         # bracket: canvas edges the host touched in the source {L,T,R,B}
```

### 2.2 Galley (the IR, ★1)

```python
Galley:
  canvas: (W0, H0)
  background: [element]             # lowest full-bleed layer(s); bg_kind ∈ {photo, flat, none}
  texture: [element]                # ungrouped translucent / bleeding shapes (atmosphere)
  furniture: [Unit + corner]        # small corner stickers / rotated ribbons, anchored TL|TR|BL|BR
  hidden_always: [element]          # unresolvable assets (only if the asset dir resolves other assets)
  stream: [Unit]                    # reading order (recursive XY-cut on ink boxes)
  labels: ["/"|"|"|"¶"] * (n-1)     # the SOURCE PROGRAM, e.g. "logo ¶ product ¶ headline / subhead ¶ cta"
  glue: [float] * (n-1)             # natural gap = designer's gap, with its axis (x for "|", y otherwise)
  bonds: [float] * (n-1)            # bond strength; text–text bonds may not be split by a picture
  rho: float                        # source top/bottom slack split (vertical anchoring intent)
  align: {col_key: left|center|right}  # source alignment per stack
```

The same structure nests: `Unit(kind="bracket").inner` is a `Galley` whose canvas is the host's box.

### 2.3 info (shared dict; authoritative definition in `proto/INTERFACES.md`, OPTIMIZER)

These are the keys the moderator required plus OPTIMIZER's extensions:

| group | keys |
|---|---|
| moderator | `roles`, `priority`, `hidden`, `containers`, `groups`, `bg_id`, `ink`, `src_ink`, `scale`, `assets_dir` |
| OPTIMIZER | `bg_kind`, `regime`, `canvas`, `units`, `program{source, chosen}`, `gamma`, `floors_px`, `font_src`, `live_area`, `energy`, `energy_terms`, `candidate`, `hide_mode` |

**Requested by this spec** (in `REQUESTS.md`):
- `calm{status, tolerance, threshold, calm_share}`;
- `decisions[]`: human-readable reasons, e.g. "subhead hidden: costs 31% type scale". The finale needs these (§11).

### 2.4 Candidate

```python
Candidate:
  stream_order: list[Unit]          # identity, or a permitted move (mark-first; furniture to ends)
  kept: list[Unit]; dropped: list[Unit]
  labels: list[str]                 # break pattern for kept units (canonical: no lone stacks)
  live_area: (x, y, w, h)           # canvas or a calm region (S2)
  z: float                          # shared type scale; font_i = clamp(round(fs_src_i · z^γ(role)))
  img_tier: {unit: ρ}               # discrete image scale tiers
  bracket_solutions: {unit: (orient, share, inner Candidate)}
  E: float; terms: dict             # energy and its breakdown (also feeds info["decisions"])
```

---

## 3. S0 normalize & measure, and S1 decompile

### 3.1 S0: normalize and measure (contract-in)

**Normalize** (never mutate the input; deep copy everything):
- Default the missing fields: `opacity` 1, `z_index` = list order, `fit` contain, `line_height` 1.2, `rotation` 0.
- Coerce numbers to finite floats.
- Keep unknown keys and pass them through untouched.

**Measure exactly what the renderer draws:**
- **Text.** Use `renderer.converter.wrap.char_widths` / `wrap_text` through the renderer's own `FontManager`.
  - Measure at **`int(font_size)`**, the size the renderer actually draws.
  - Add `letter_spacing·(n−1)` per line, because the renderer draws it but its wrap step does not measure it. This is what caused 41 overflows in DESIGNER's R1.
  - Rendered height = `n_lines · fs · lh`.
  - Read cap-height and ascent from skia metrics.
- **Images.** The alpha bbox of the asset under the element's `fit`, stored as `ink_rel`. Image *and* box geometry are always both available.
- **Missing assets.** If the asset dir resolves at least one other asset of this design, an image whose asset is missing is `hidden_always`. If *no* asset resolves, we are pointed at the wrong dir: hide nothing.

**Caches** are keyed by **value** (family, weight, style, int size, content, width) and never by `id()`. That rule is JUDGE invariant I13. OPTIMIZER's `id()`-keyed cache served another string's glyph widths 109 times in 594,883 wrap calls, and caused all 5 of its bench crashes.

### 3.2 S1: decompile into the galley

```
decompile(src):
  1. layers
     background  = lowest image/shape covering ≥ 85% of canvas (opacity > .5) → bg_kind:
                   photo if image with fit cover/fill and non-flat pixels; flat if shape or flat image
     texture     = ungrouped shapes with eff_alpha < .4, or bleeding off-canvas, not holding content
     containers  = opaque (eff_alpha ≥ .5) ungrouped non-bg shapes, ≥ 4–6% of canvas, holding ≥ 1
                   content element (ink centre inside, higher z)  → host + riders        (★4)
     atoms       = group_id clusters (rigid; pill = 1 shape + 1 text), singletons, brackets
     furniture   = small (< 8% canvas) atoms hugging a canvas corner AND (off the main axis OR rotated)
     hidden_always = unresolvable assets (see S0)
  2. roles & rent (features only; DESIGNER's 32/32 role inference + PERCEPTION's alpha stats)
     headline = max(fs · 1.15^bold) free text → rent ∞;   cta = pill whose label has an imperative verb
     (+2) / not all-caps / lower on canvas, or short bold saturated text → rent 1.0 (P0);
     logo = small, mostly-transparent, wide image near an edge → rent ∞ (P0, floor-shrinkable);
     hero/picture rent .12 + area share; subhead .2; badges/chips .06; legal .03; sticker .1
     (initial values; fitted in §8)
  3. reading order + source program: recursive XY-cut on INK boxes
     xycut(atoms): split on the axis whose widest empty gap / canvas-dim is larger (ties → y);
                   no gap on either axis → "island" (rigid unit)
     flatten(tree): Y at row level → "¶"; X → "|"; Y inside a column → "/"; X inside a stack, or
                    side-by-side look-alikes (same kind, height within 1.4×) → chips unit
  4. glue_i = source gap between stream neighbours (axis-aware); base glue = median vertical gap,
     clamped to [1.5%, 6%] of min(W0, H0)
  5. bonds: consecutive text units stacked within 1.5 line-heights → bond; a picture may not be
     placed between bonded text units (OPTIMIZER's 1600×400 failure)
  6. brackets: decompile(riders, canvas = host box) recursively → Unit(kind="bracket", inner=…)
  7. info: roles, priority, containers, groups, bg_id, src_ink, units, program.source
```

**Decompiler invariants** (these are CI tests, §10):
- Every source id appears in exactly one of: background, texture, furniture, hidden_always, or one unit.
- Ids, list order and z ties never change any decision. Test this with JUDGE's `r2_id_invariance`.
- Re-typesetting at the source canvas reproduces the source: fixed-point drift < 3% (★2).

---

## 4. S2: regime and live areas

**Regime.** Use JUDGE's catalogue bands on r = W/H:

| band | r |
|---|---|
| strip | r ≥ 4 |
| wide | 1.6 ≤ r < 4 |
| squareish | 0.7 ≤ r < 1.6 |
| tall | r < 0.7 |

Also flag a short side < 120 px as **tiny**. The regime selects policies (§7), never layouts.

**Live areas (★4, `overlay.py`, implemented and tested).** The full rule is:

```
if bg_kind != "photo":  live_areas = [canvas]
else:
  tol  = p90 busyness under the designer's FREE text in the source (riders/pill labels excluded)
  thr  = max(1.5 · tol, 0.006)                                   # source-relative (★3)
  crop = exact renderer pixels at the target (cover = scale-to-fill + centre crop; verified: max |diff| = 0)
  busy = box-blurred luminance-gradient energy, canvas-px units, window = min(W, H)/40
  grid = 40 cells on the long side; calm cell ⇔ max busy ≤ thr
  live_areas = [canvas if calm_share ≥ .85] + maximal calm rectangles (overall + each half),
               each ≥ 6% of canvas;  score = sqrt(area share) · (1 − mean/thr)
  status "none_calm" → [] (engine keeps the canvas, keeps the busy penalty, prefers a scrim/container)
```

**The API** (never raises):
- `calm_regions(source, target, info, assets_dir) -> [(x, y, w, h, score)]`;
- `busy_ratio(source, target, boxes, …) -> [busy / tolerance]` for the energy and the critic;
- `analyze(…)` returns the status.

**Cost:** a cold call is 4–130 ms (one-off font and PNG decode up to ~0.7 s for a 2.2 MB photo); a warm call is < 5 ms.

**Measured behaviour:**

| design | target | calm region found |
|---|---|---|
| F1 (photo) | 1600×400 | one 480×120 sky band |
| F1 | 1080×1920 | top 1080×720 |
| F1 | 728×90 | **none** (0% calm cells) |
| JUDGE's S02 | 728×90 | **none** |
| JUDGE's S02 | 2560×1440 | top band |
| U, F2, S11 (flat or gradient backgrounds) | all | whole canvas |

---

## 5. S3: search, inner solver and energy

### 5.1 Outer search

Enumerate when there are few kept units; otherwise use DP with skip transitions.

```
search(G, target, live_areas):
  cands = []
  for A in live_areas[:3]:                                   # S2
    for order in permitted_orders(G):                       # identity; logo-first (+.03); furniture→ends
      if len(order) ≤ 9:  pats = canonical {/,|,¶}^(n-1) × omission subsets (rent-ordered prefixes
                                 + 1-swap)      # ≤ ~5k evaluations, measured 0.03–0.8 s
      else:               pats = DP (below)                 # GALLEY's 3^(n-1) took 82–180 s on S12
      for p in pats: c = inner_solve(p, A); if c.feasible: cands.append(c)
  return top_k(cands by E, K = 6, require structural diversity)   # distinct programs, not near-duplicates
```

**Knuth–Plass DP with skips.**
- For a fixed z, rows are independent given the live width. Omission is a skip transition that costs the unit's rent.

```
for z in bisection_grid:
  F[0] = {(height 0, cost 0)}                                        # Pareto frontier (height, cost)
  for i in 1..n:
    F[i] = pareto( ⋃_{j<i}  { (h + glue + rowheight(j..i, z, A.w, skips), c + rowcost + Σ rent(skipped)) :
                               (h, c) ∈ F[j], row feasible } )      # rows hold ≤ 5 kept units;
                                                                   # column/stack splits enumerated inside
  feasible(z) ⇔ ∃(h, c) ∈ F[n] with h ≤ A.h
z* = max feasible z (bisection, ~14 probes); candidates = the cheapest K frontier points at z*
                                                     and at z ∈ {.9, .8}·z*   (scale variants, ★2 cone)
```

Complexity is O(n² · 2⁵ · |frontier|) per z probe. Frontiers are pruned to ≤ 8 points per state.

**Brackets (★4).** A bracket unit is solved recursively. The menu is orientation {beside, above} × share ∈ {.34, .42, .5, .58, .66, .75} × order {source, swapped (+.03)}:
- The inner galley is solved in the host's cell, and the host shape is resized to the cell. It bleeds to the canvas edges it touched in the source; shapes may stretch.
- Results are memoized by cell size.
- A **z-consistency term** keeps the inner and outer type scales within one ramp step.
- Images in sibling cells are scaled so that the **transparent-padded box fits with its ink centred in its own cell**. Clamping a box shifts its ink onto the neighbour, which was my F2 bug.

### 5.2 Inner solver (fixed program, fixed live area)

These are OPTIMIZER's exact solver and DESIGNER's elasticity:

```
font_i(z)   = max(floor_i, round(fs_src_i · z^γ(role_i, z≥1?)))   γ_up   = {headline 1, subhead/body .75, chip .6, legal .35}
                                                                   γ_down = {headline .8, subhead/body .6, chip .5, legal .3}
floor_i     = judge-px floors / min(1, 1024/long_side): headline 14, others 9–11, CTA label 12  (OPEN O6)
text box    = exact frontier: W_k(f) = min width with ≤ k lines (binary search on the renderer's wrap);
              H_k(f) = k·f·lh; candidate widths = breakpoints {W_k} ∪ {widest rigid}; never a word wider than box
images      = discrete tiers ρ ∈ z_ref·{.5,.7,1,1.4,2} ∪ {fit_max, .8 fit_max}; box keeps source aspect exactly;
              layout on INK, but boxes disjoint (§7.4) — padded assets placed on their tight axis
rigid/pills = scale with their label's font (label ≥ CTA floor); pills elastic between min-content and source
              proportion; rotated members: rotated AABB used for packing and bounds
columns     = min width = smallest frontier breakpoint at which the stacked heights fit
feasible(z) = Σ row heights + glue ≤ live h  ∧  every row ≤ live w (incl. edge-image padding overhang)
              ∧ hard hierarchy: every other text ≤ headline/1.2 (CTA label included); logo ink ≤ .8 × headline ink
z*          = bisection (monotone in z: all footprints grow with z); ±2 integer-step probe for rounding
widen       = spend leftover width on fewer lines, toward source line counts
place       = TeX glue: fit with shrunk glue, stretch toward the designer's natural gaps, leftover split by rho
              (tall canvases: PAVA toward source relative heights; rhythm snap in S5)
```

### 5.3 Energy (lower is better)

Every term is computed on the candidate. **Bold** marks the terms that every source "reveals" (§8).

```
E =  Σ_dropped rent_u                                            omission (rent)
   − U(z)            U = log min(z, z_cap) + .2·log⁺(z/z_cap)     capped concave size utility
                     z_cap from the Crello format prior (headline ≈ 0.30·H for strips, …), NOT from √area
   + w_leg  · Σ hinge(f_comf − f)²                                legibility (comfort above the hard floor)
   + w_copy · max(0, chars·f_comf²·.55/area − .5)                 copy budget: can the canvas be read?
   + w_lines· Σ max(0, k − k_src)  + widow/one-word-line count     line-break faithfulness, rag
   + w_img  · Σ |log(ρ/z)| + [source-larger image became smaller] image/type proportion, image hierarchy
   + **w_tr · #transpositions + w_rs · #restacks vs source program** structural faithfulness
   + **w_bond · #bonds broken**  + w_perm · [stream permuted]
   + w_dens · |log(coverage / coverage_target)|                  coverage_target = Crello prior × source deviation (§8)
   + w_busy · max(0, max busy_ratio(text inks) − 1)               overlay (S2)
   + w_clut · Σ max(0, cols − 5)                                  clutter
```

**Initial weights** come from OPTIMIZER R1 and GALLEY R1. **Final weights** are fitted as in §8. All terms are features of the candidate, so the fit is logistic regression on term differences.

---

## 6. S4–S10: realize, finish, contract, verify, pick, fallback

### 6.1 S4 realize (`engine.py`)

Realize turns a solved candidate into an output design:
- **Flow units** are placed in their cells:
  - text boxes take the frontier width and an honest height `n·fs·lh`;
  - images are positioned by their ink, with the box derived from `ink_rel`;
  - rigid groups get a similarity transform.
- **Furniture** and **decoration** follow §7.3.
- **Hidden elements** follow §7.2.
- The **background** fills the full canvas.

### 6.2 S5 finish (`finisher.py`, DESIGNER)

The finisher is pure. It may only adjust the geometry or `font_size` of visible elements, and the placement of furniture and decoration. It runs on each top-K candidate:
- balanced wrap: bisect the box width down to the narrowest width that keeps the line count;
- no widows (< 35% of the measure) and no one-word lines in a headline of ≥ 3 words;
- cap-height optical placement and optically centred pill labels;
- balanced optical side margins (ratio ≤ 2, or Δ ≤ 12 px);
- tall canvases: snap rhythm to {1, 2, 3}× a rhythm unit in rank order (fixes 23–355 px stacks);
- strips: ≥ 12% H text padding, headline ≤ 3 lines;
- CTA label ≥ 12 judge-px.

**A finished output that breaks the contract is reverted** to its unfinished version.

### 6.3 Overlay fallbacks when there is no calm region

These are evaluated in S3 as extra candidates, in order:
1. move the copy into a **source container** that is opaque or a scrim, if one exists (the host relation does this for free);
2. the calmest band, with `w_busy` penalty applied;
3. the gated palette swap to an in-design colour (**OPEN O7**, off by default).

Nothing else is allowed. In particular, no new pixels.

### 6.4 S6 contract + repair (`contract.py`; JUDGE I1–I15 + PERCEPTION's I13 label-in-pill)

This runs on **every candidate before it is rendered**: a candidate that crashes the renderer must never reach S7. PERCEPTION's R1 generator crashed it on 50 of 135 cases.

| # | invariant |
|---|---|
| I1 | output = `{"canvas":{int W, int H}, "elements":[…]}`; ids identical, source list order kept |
| I2 | frozen: `content`, `font_family`, `type`, `asset_id`, `fit`, `group_id`, `rotation`; unknown keys passed through; `color` changes only in its **alpha** channel, and only when hiding |
| I3 | plain finite Python numbers (no numpy, no NaN); `font_size` int ≥ 1; text w, h ≥ 1; z_index int |
| I4 | unrotated box within [−0.5, W+0.5]×[−0.5, H+0.5]; **and** the rotated AABB of every visible element in-canvas; line shapes whose unrotated box can't fit are length-scaled (JUDGE I14) |
| I5 | non-cover images: box aspect = source aspect (±1%) |
| I6 | text honesty: every measured line (with letter spacing) ≤ box w; `n·fs·lh` ≤ box h; lines ≤ `max_lines` |
| I7 | visible text ≥ floor in judge-px, else hidden (with its group) |
| I8 | groups: all visible or all hidden, rigid similarity transform; **a pill label's ink lies inside its pill's ink** |
| I9 | relative z-order of visible elements preserved |
| I10 | hide encoding per `HIDE_MODE` (§7.2) |
| I11 | determinism: invariant under id renaming and list permutation (outside z ties) |
| I12 | the render succeeds (checked in S7 for the top-K; the S10 output is always one of them) |
| I13 | value-keyed caches only; no state across `resize()` calls |
| I15 | P0 visible (headline, CTA, logo), unless brand-reminder mode is logged (§7.1) |
| I16 | default: visible content boxes are pairwise disjoint, except same group, pairs that already overlapped in the source, and background/decoration/host-rider (§7.4) |

**Repair** runs at most 3 passes in a fixed order: enforce groups → refit text → aspect → clamp the rotated AABB → apply hiding. It is followed by re-validation. Anything still failing is discarded.

### 6.5 S7 verify, S8 pick

For each of the top-K (K = 6) structurally diverse candidates:
1. **Render once**, in-process, with the official renderer. This takes 27–82 ms native, and the asset decode is cached.
2. Run **`critic.critique`** (PERCEPTION). It is source-relative and relation-aware. Its **vetoes** are:
   - a label spilling out of its pill;
   - a *new* ink collision;
   - x-height below the floor in native px;
   - glyphs over a busy backdrop beyond the source tolerance;
   - under-fill relative to the source;
   - clipping;
   - a visible placeholder;
   - a hidden element leaking pixels.
3. Run **`rules.check`** (DESIGNER), R0–R14 source-relative, which returns hard and soft violations.

**Pick lexicographically:**
1. contract-hard failures, which must be 0;
2. vetoes + hard rule violations;
3. soft rule violations;
4. E;
5. if ΔE < 0.03: critic penalty, then Crello format-prior likelihood, then structural distance to the source program, then stable id-free order.

Measured: "defects first, then J" was right on 30/33 eye-labelled pairs, against 26/33 for either signal alone.

### 6.6 S9 fallback ladder (never fail)

1. the next candidate in pick order;
2. **legible-or-absent single stack**: a role-free contain-fit of the flow in reading order, every text below its floor hidden except the headline, which takes priority space;
3. `safe_fit`, the uniform letterbox. It is used **only** on a hard failure of 1 and 2, never because of a score: it ranked #1 under a critic at 1080×1920 while looking like an island;
4. `last_resort`: pure-Python identity-clamped contain, with no imports beyond the stdlib.

The entire `resize()` body is wrapped in `try/except BaseException → last_resort`. Note that `main.py` has no try/except around `resize()`.

---

## 7. Policies

### 7.1 Extreme formats: message-first collapse (DESIGNER B3, made precise)

- **P0 = {headline, CTA, logo}.**
  - Drop order: hidden_always → legal → badges/chips → stickers → subhead/body → hero → decoration.
  - Inside the search this is not a rule. It falls out of rent, legibility and the copy budget. The rule only *bounds* the search: P0 rent is ∞, and I15 holds.
- **Logo.** Shrinks to its recognisability floor: visible mark ≈ 0.45–0.5 H in strips, ≥ 24 judge-px elsewhere. Logo ink is ≤ 0.8 × headline ink (cross-type hierarchy).
- **CTA label.** ≥ 12 judge-px and ≤ headline/1.2. In skyscrapers the label wraps to 2 optically centred lines before going below 12 px.
- **Strips (H ≤ 120, or r ≥ 4).**
  - The headline takes every remaining pixel, in ≤ 3 balanced lines, with ≥ 12% H padding.
  - Copy budget active: at most ~4 visible units.
  - Rotated stickers dropped.
- **Brand-reminder mode.** This is the *only* case where the headline is absent, and it is logged in `info.decisions`.
  - Trigger: the headline can't reach its floor in ≤ 3 lines even with everything else at its floor (e.g. L3's 140-character headline at 320×50).
  - Output: `logo | hero | CTA`. If the hero can't fit either: `logo | CTA`.
- **Skyscraper (160×600).** The headline averages ≥ 2 words per line; if it can't at its floor, the hero goes first.
- **Tall and story.**
  - The headline may gain one line when growing.
  - The message group sits at an optical centre ≈ 0.45 H; the logo is pinned to the top band.
  - Image tiers let the hero absorb slack. This is where OPTIMIZER wins (tall band 91.6 vs ≤ 83.7).
  - Rhythm snapping in S5.
  - Soft prior: keep text and CTA out of the bottom 15% (platform UI).
- **Near aspect** (|ln(r_t / r_s)| < 0.15). The source program wins by construction (★2). The result is a uniform scale plus glue redistribution, with no cleverness.

### 7.2 Hide policy (switch `HIDE_MODE`; default `alpha`)

| mode | encoding | when |
|---|---|---|
| `alpha` (default) | `opacity: 0`, and for text **colour alpha 0** in `color` and every `style_runs` colour (RGB kept); geometry parked in-bounds at its source position under uniform contain-fit; box ≥ 1×1; int `font_size` ≥ 1 | always valid; 0 leaks over 142 + 120 checked hides |
| `z_under_bg` | `opacity: 0` + text `z_index = min_z − 1` | only if the organisers freeze `color` **and** an opaque, unrotated, full-canvas bottom layer exists; otherwise falls through to `alpha` |
| `never_text` | text rent ∞; images and shapes still hide with opacity 0 | only if the organisers forbid hiding text; strips will then show smudges (936 on the safe floor) |

**Never** use `opacity` alone, which leaks in 109 of 120 cases. **Never** combine encodings, and never use the 1 px trick. This is **OPEN O1**.

### 7.3 Furniture and decoration

**Furniture** (corner stickers, rotated ribbons, watermarks) keeps its rotation, because the rotation is its identity. Placement order:
1. the source corner;
2. the mirrored top corner;
3. the hero's shoulder: ≤ 20% overlap with hero ink, 0% with text;
4. drop.

The rotated AABB must stay in-canvas, because the renderer clips rotated corners. In tiny strips (H < 120), furniture is dropped.

**Decoration** (translucent shapes):
- image-attached → a concentric **halo** ≈ 1.12× the image's visible height;
- off-canvas bleeders → tangent to their source corner, in-bounds;
- text-attached → kept only if the overlap with text or CTA ink is ≤ the source overlap + 5 points;
- never a disc around a logo, and never under a CTA pill;
- in strips, kept only if it overlaps no text.

Circles stay circles: the aspect is preserved.

**Background.** Always full canvas. `cover` is centre-crop only, so we choose where the type goes inside the crop (§4) rather than the crop itself.

### 7.4 Ink vs box (default: disjoint boxes; **OPEN O2**)

- Layout and gaps are computed **ink-to-ink**, then realised box-to-box: `g_box = max(0, g_ink − pad_a − pad_b)`.
- Visible content boxes are pairwise disjoint (I16).
- Padded assets are oriented on their tight axis. The logo is 30% padding on each side but 0.7% at the top: logo *above* the headline costs nothing, logo *beside* it costs ~44 px at 728×90.
- Text boxes shrink-wrap to their balanced ink width.
- The forced visible margin is mirrored onto the opposite edge.
- Cost: about 5% of type size in strips. The flag `DISJOINT_BOXES=False` enables ink sharing of transparent padding.

### 7.5 Robustness odds and ends

- Unknown `font_family` → measure with the same fallback the renderer uses.
- Empty or whitespace text → valid 1×1 box, no reserved space.
- `&amp;`-style entities → prefer a single line; the renderer breaks mid-word after unescaping.
- Emoji, CJK and Arabic → measured as drawn (tofu); no special casing.
- Named colours are never written. The engine only rewrites the alpha of existing `rgba()` strings, and only when hiding.
- `max_lines` respected.
- Groups with missing members, or lone pills → treated as rigid atoms.

---

## 8. Taste and calibration: who decides what (★2, ★3)

| decision | decided by | evidence |
|---|---|---|
| Structure near the source aspect; whether to transpose; stack vs rows; split axis of a bracket | **the source**, via fixed-point inequalities: at its own canvas the source beats every alternative the engine can produce (≈60–1,800 per design) | GALLEY E3: fixed points repaired, L2 6.0 → 2.5% drift, U 12.2 → 3.7%; near-regime decision margins 0.006–0.009 → 0.016–0.050 |
| Every *tolerance*: contrast, busyness under type, collisions (new only), coverage and empty bands, decoration-over-text | **the source's own render** (★3) | −22–31% false flags (DESIGNER); critic 4/4 → 3/4 agreement (PERCEPTION) |
| Invariants: type ramp, headline contrast, reading order, alignment | **the source**, held by construction (shared z, source-relative contrast) | PERCEPTION E: ramp log-ratio −0.04, contrast −0.02 across eye-best resizes |
| Absolute operating point per format: headline height, density, line counts, coverage | **Crello format priors**, baked at build time (2.6 MB: 3,204 wide/odd designs; leaderboard headline 0.30·H, 1–2 lines; smallest text p25 9 px) | the source can't supply it: pure source-density gave 10 px banner headlines (GALLEY E2) |
| Exchange rates at extreme formats: drop vs size, legibility vs content, keep the product at 728×90 | **dev-time VLM pairwise labels**, Bradley–Terry, native-resolution PNGs | OPTIMIZER cone: drop, legibility and copy-budget weights unidentified by any source; decisions flip inside the identified set |
| Defects: spill, smudge, clip, new collision, placeholder | **pixels** (critic vetoes) | 98% broken-vs-designed |

**Weight fitting (dev time, before submission):**

```
corpus  = 3 samples + 12 bench designs + fixtures (U, F1, F2, S, B) + ~200 Crello-converted designs
pairs   = for each (design, catalogue size): top-6 candidates → ~4 informative pairs (different programs,
          defect-free) → ~3–5k pairs, rendered at NATIVE resolution
label   = frontier VLM (dev only), rubric text, A/B swapped, ties allowed; 10% human-audited
fit     = min_w  BT-logloss(w; pairs)  +  λ‖w − w0‖²
          s.t.  w · (φ(alt) − φ(src)) ≥ Δ(src, alt)   ∀ corpus source, ∀ alt at its own canvas   (★2 cone)
                w ≥ 0 on penalty terms;  hard rules stay hard (never traded)
report  = held-out pairwise agreement (target ≥ 75%), per-band; ship ~25 floats as JSON
```

**Runtime per-design calibration (OPEN O4).** Before the search, run a trust-region projection of the **structure weights only** (`w_tr`, `w_rs`, `w_bond`, `w_perm`, bracket split axis) onto this source's cone. That costs ≤ 0.5 s. Scale and rent weights stay frozen.

**Dev tool.** If a corpus source is **not separable**, so that no weights let it win at its own canvas, that is a bug report: a feature is missing. This is how `restack` was found.

**Never:**
- a monotone size reward (inconsistent with every source: w_size → 0);
- the source as the sole objective;
- the critic's continuous score as the objective (Goodhart: a selector cannot also be the evaluator).

---

## 9. Test strategy

| layer | test | gate |
|---|---|---|
| T0 renderer-exactness | measured wrap = drawn wrap (int size, letter spacing); `overlay` crop equals `load_asset_image` (**verified: max \|diff\| = 0**); ink boxes vs solo-render alpha | exact |
| T1 contract | I1–I16 on every output of every test, and on every *candidate* in debug runs | 0 violations |
| T2 **fixed point** (★2) | `resize(src, src.canvas)`: centre drift < 3% of the diagonal, font change < 2%, same program | all designs |
| T3 metamorphic | id rename + list permutation (outside z ties) → identical output; same aspect → uniform scale (drift < 2%); larger canvas of the same aspect → headline never smaller; `resize(resize(s, T), T) ≈ resize(s, T)`; round trip `resize(resize(s, T), s.canvas)` scored, not gated | 100% |
| T4 cache hygiene | 1 process, 500 sequential tasks, shuffled; outputs identical to a fresh process per task | identical |
| T5 bench (JUDGE) | 15 designs × 26 sizes = 390 cases + fixtures; proxy composite, renderer gaps, P0-dropped count | 0 crash, 0 hard, 0 timeout; mean ≥ 90.4 (best current engine), p10 ≥ 80; per band ≥ best R1 engine − 1 |
| T6 eye | contact sheets: 15 designs × 8 sizes, reviewed per milestone; 20 VLM spot checks at native resolution | no new defect class |
| T7 fuzz | hypothesis-style JSON mutation (deleted fields, type swaps, extreme numbers, 0/neg sizes, 50+ elements) | never raises; valid JSON |
| T8 timing | `docker build --platform linux/amd64` + `--network none`; full bench | p95 ≤ 10 s/design, max ≤ 30 s |

---

## 10. Build plan (3 people, ~4 weeks; owners as in proto)

| milestone | content | owner(s) | gate |
|---|---|---|---|
| **M0** (day 3) | contract + repair + fallback ladder + last_resort; value-keyed caches; bench wired to proto | OPT + JUDGE | T1, T4, T7 green; 0 crash on 390 |
| **M1** (week 1) | S0 measurement, S1 decompiler (layers, XY-cut stream, roles/rent, bonds, brackets), enumeration search + inner solver (frontier, bisection, γ, tiers), S4 realize | OPT (+INV IR review) | T2 fixed point on 3 samples + U, F2; bench mean ≥ 88, 0 crash |
| **M2** (week 2) | KP DP + skips (n > 9); brackets recursive; `overlay` in S2/S3 (done); finisher; furniture/decoration policy; hide modes | OPT, DES, INV | S12 ≤ 2 s/size; S01/S11/F2 no lost backdrop; F1/S02 no busy-under-text where a calm area exists; bench mean ≥ 89.5, p10 ≥ 78 |
| **M3** (week 3) | critic vetoes + rules + lexicographic pick (top-K = 6); Crello priors baked; VLM pair labelling + cone-constrained BT fit; runtime trust-region (behind flag) | PER, DES, INV | held-out agreement ≥ 75%; bench mean ≥ 90.4, p10 ≥ 80; T3 green |
| **M4** (week 4) | Docker amd64 timing, hardening, regression gallery, README, freeze | all | T8; no regressions for 3 consecutive bench runs |

**Day-1 shortcut.** M0 alone (safe floor + contract) is a valid submission scoring ~72. The OPTIMIZER spike plus the cache fix already reaches 90.4 / 79.9. Every milestone must beat the previous bench run.

---

## 11. Finale vision: the Express add-on ("Chameleon")

The engine is deterministic, explainable and fast (sub-second, DP-cached), and that is what makes these features possible:
1. **Pick formats from the catalogue → every size at once.** A campaign grid of renders with per-size decision chips taken from `info.decisions`, e.g. "subhead hidden — keeping it costs 31% type size", "product dropped below legibility", "copy moved into the calm sky".
2. **Live aspect slider.** Drag the artboard and watch the galley re-break: column → row → stack. Structural changes happen at visible "bifurcation" points. This is INVENTOR's R1 homotopy idea, finally useful.
3. **Lock and nudge** in the program, not in pixels:
   - pin a break (`headline | cta`);
   - lock an element as must-keep (rent ∞);
   - drag a bracket's split share.

   The engine re-solves around the constraint.
4. **"More like the original ↔ more filled" slider.** It moves along the trust region between the source-cone weights and the Crello-prior weights (★2 made tangible).
5. **Busy-photo assistant.** Show the calm map of the crop, and suggest a scrim only by reusing a shape that exists in the design.
6. **Finale-only creativity.** Adaptive copy (shorter headline variants) enters as extra candidates in the same galley and is labelled as a suggestion, never applied silently. Font family swaps stay off.

---

## 12. OPEN items (evidence on each side)

**O1 Hide encoding.**
- For `alpha`: 0 leaks over 262 hides; needs nothing from the design.
- For `z_under_bg`: also 0 leaks, but it edits z-order and needs an opaque full-canvas bottom layer.
- Risk: a checker that string-compares `color` (alpha) or checks relative z-order (z).
- *Ask the organisers:* is `opacity: 0` accepted as dropped, and may a hidden element's colour alpha change?

**O2 Disjoint boxes vs ink sharing.**
- Ink sharing: +5% type in strips; all pixels clean today.
- Disjoint: 16/24 R1 outputs would fail a box-overlap check, which is the first check anyone writes.
- Default disjoint until the organisers answer.

**O3 L3 product at 728×90.**
- OPTIMIZER keeps it (weights); DESIGNER, GALLEY and the brief's reference drop it.
- The cone shows it is unidentified by the source.
- The VLM pairs decide.

**O4 Runtime per-design calibration.**
- For: repairs fixed points (E3) and widens near-regime margins.
- Against: +≤0.5 s and a new failure surface; the static cone-constrained fit may already suffice.
- Ship behind a flag and decide on the M3 bench.

**O5 Render-in-the-loop under emulation.**
- 27–82 ms per render native; Docker amd64 on Apple silicon is unmeasured (2–5×?).
- K = 6 with an anytime deadline. Measure at M0.

**O6 Legibility floors.**
- 9 judge-px text, 12 judge-px CTA (DESIGNER) vs native x-height ≥ 6 px (PERCEPTION).
- The judge's view scale (1024 long side?) is unknown.
- A 728×90 PNG is judged at native size (max_size 2048), so x-height in native px is the safer floor.

**O7 No-calm-region photos** (F1 / S02 at 728×90: 0% calm cells).
- Options: copy into an existing scrim or container (allowed); palette swap to an in-design colour (changes `color`, gated); accept a busy backdrop with contrast check.
- Hide copy? No: P0.

**O8 Tall canvases.**
- OPTIMIZER's image tiers fill stories best (91.6 band mean).
- DESIGNER's "message group at 0.45 H + logo pinned top" is untested at scale.
- Decide on the M2 bench by band.

**O9 Crello priors as baked data.** Licence and attribution need a check before building them into the image. Fallback: hand-set per-band operating points derived from the extracted statistics.

---

## Appendix A — evidence index

| claim | file |
|---|---|
| bench 390 cases, per-band numbers | `bench/SCOREBOARD.md`, `bench/scoreboard_cases.csv` |
| GALLEY crashes / timeouts | `bench/scoreboard_cases.csv` (galley rows) |
| fixed point and inverse calibration (E1–E3) | `spikes/inventor/out_r2/taste_log.txt`, `r2_taste.py` |
| cone identifiability | `spikes/optimizer/r2_inverse.py`, `round2/optimizer.md` §C |
| containers as nested designs | `spikes/optimizer/r2_merged.py`, `spikes/inventor/r2_topology.py` |
| calm regions, renderer-exact crop | `proto/overlay.py` (`python design/debate/proto/overlay.py`) |
| critic as veto: 36→64% vs 92→98% | `spikes/perception/r2_agreement.py`, `round2/perception.md` §B–C |
| hide encodings E1–E4 | `spikes/judge/r2_hide_encodings.py`, `round2/judge.md` |
| stale `id()` cache | `spikes/judge/r2_stale_cache_probe.py` |
| source-relative rules R0–R14 | `spikes/designer/r2_rules.py`, `round2/designer.md` |
