# Round 3 — build the merged prototype (read before writing anything)

## Where Round 2 landed (read all of design/debate/round2/*.md)

Consensus architecture, the "bracketed galley":
1. **Decompile** (INVENTOR): XY-cut on INK boxes → ordered reading stream + layers
   (background / texture / furniture / hidden) + **containers** (host/rider =
   DESIGNER's "ground binding" = OPTIMIZER's "brackets"), + bonds (consecutive text
   units can't be split by a picture).
2. **Search**: stream grammar ¶ | / plus nested brackets; Knuth–Plass DP with skip
   transitions (omission at rent cost) for n>10, enumeration otherwise; one shared
   type scale with per-role exponents γ (DESIGNER k^γ), bisection; OPTIMIZER's
   exact text frontier (renderer's wrap), image tiers, PAVA, copy budget, hard
   ordinal hierarchy incl. cross-type (logo ink ≤ 0.8 × headline ink), capped
   concave size utility (no monotone size reward — inverse optimization proved it).
3. **Realize/finish** (DESIGNER): balanced wrap, no widows/one-word lines, cap-height
   optical placement, balanced optical margins, rhythm snapping on tall canvases,
   CTA label ≥ 12 judge-px, strip headline ≤ 3 lines, message-first extreme policy,
   brand-reminder mode only when copy is impossible, furniture & decoration policy.
4. **Overlay live areas** (INVENTOR): text on a full-bleed photo goes into calm
   regions of the renderer's exact target centre-crop, threshold relative to the
   busyness under the designer's own text in the source.
5. **Verify** (PERCEPTION): render top-K, source-relative pixel critic used as
   VETOES for defects (it is good at broken-vs-designed, ~92%; bad at
   designed-vs-designed, 36–64%), then energy decides; lexicographic tie-break:
   hard vetoes → rule-violation count → energy.
6. **Contract/repair/fallback** (JUDGE): 12 invariants, int font sizes, no w/h 0
   text, rotated AABB in-bounds, rgba colours only, fallback ladder whose floor
   is the best LEGIBLE candidate. Disjoint JSON boxes by default (costs ~5% type),
   ink-sharing behind a flag.
7. **Taste/calibration**: source fixed point as CI test (target = source canvas ⇒
   drift < 3%); inverse-optimization cone as constraints; per-design trust-region
   calibration of structure weights only; far-regime exchange rates from Crello
   format priors + dev-time VLM pairwise labels (Bradley–Terry). Never the source
   as the sole objective.
8. **Hide**: policy switch `HIDE_MODE ∈ {alpha, z_under_bg, never_text}`; default
   `alpha` (opacity 0 + colour alpha 0 incl. style_runs, in-bounds parking) until
   JUDGE's recommendation lands.

## Round 3: build it, as one codebase with clear ownership

Location: `design/debate/proto/` (a package; run from repo root with
`.venv/bin/python -m design.debate.proto.run <task.json> <W> <H> <out_prefix>` or
similar — OPTIMIZER defines the CLI). Each file has ONE owner; never edit a file
you don't own — if you need a change, write the request in
`design/debate/proto/REQUESTS.md` (append-only, tagged with your name).

| file | owner | interface |
|---|---|---|
| `engine.py`, `decompile.py`, `search.py`, `textfit.py`, `contract.py`, `run.py`, `__init__.py` | OPTIMIZER | `resize(source, target_canvas) -> dict` (the engine) |
| `finisher.py` | DESIGNER | `finish(source, output, info) -> output` (pure; must not break the contract; may only adjust geometry/font_size of visible elements and placement of furniture/decoration) |
| `rules.py` | DESIGNER | `check(source, output, info) -> list[Violation]` (source-relative; Violation has `rule`, `severity: "hard"|"soft"`, `ids`, `detail`) |
| `critic.py` | PERCEPTION | `critique(source, output, info, render_png_path=None) -> {"vetoes": [...], "penalty": float, "features": {...}}` (source-relative, relation-aware: text on its own host panel is NOT a collision; has a busyness term) |
| `overlay.py` | INVENTOR | `calm_regions(source, target_canvas, info, assets_dir) -> list[(x, y, w, h, score)]` |
| `SPEC_v1.md` (in round3/) | INVENTOR | the unified architecture spec |

`info` dict (produced by OPTIMIZER's decompiler, consumed by everyone):
```
{
  "roles":      {id: role},   # background|logo|hero|headline|subhead|body|cta_shape|cta_label|
                              # badge_shape|badge_label|legal|decoration|panel|furniture|unknown
  "priority":   {id: float},  # rent / importance
  "hidden":     [ids],        # elements the engine chose to hide (or unresolvable assets)
  "containers": {host_id: [rider_ids]},
  "groups":     {group_id: [ids]},
  "bg_id":      id | None,
  "ink":        {id: [x, y, w, h]},   # visible-pixel box in OUTPUT coordinates
  "src_ink":    {id: [x, y, w, h]},   # visible-pixel box in SOURCE coordinates
  "scale":      float,        # chosen shared type scale z
  "assets_dir": "brand_kit/assets"
}
```
OPTIMIZER may extend `info` (add keys, never rename) and must document it in
`design/debate/proto/INTERFACES.md` early.

Test designs: the 3 samples + OPTIMIZER's S and B, INVENTOR's U, F1, F2, DESIGNER's
photo/split fixtures. Copy any fixture JSON into `design/debate/proto/fixtures/`
(owner: whoever adds it; name files `<owner>_<name>.json`). JUDGE's benchmark is in
`design/debate/bench/` (runner `run.py`, adapters in `bench/adapters/`) — use it
once it is ready; JUDGE will run the merged prototype through it in Round 4.

Rules as before: write only in your own files under `design/debate/`; never edit
engine/, renderer/, input/, brand_kit/; no git.
