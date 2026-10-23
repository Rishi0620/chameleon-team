# proto — interfaces (owner: OPTIMIZER; others: request changes in REQUESTS.md)

Package: `design/debate/proto/` (run everything from the **repo root**).

```
from design.debate.proto import resize            # resize(source, target_canvas, assets_dir=None) -> dict
.venv/bin/python -m design.debate.proto.run --help
```

## 1. Engine entry point (`engine.py`)

```python
resize(source: dict, target_canvas: dict, assets_dir: str | None = None) -> dict
resize_with_info(source, target_canvas, assets_dir=None) -> (output: dict, info: dict, report: dict)
```
* `source` = `{"canvas": {...}, "elements": [...]}` (a task wrapper `{"source":..}` is also accepted).
* `assets_dir` default: env `CHAMELEON_ASSETS`, else `brand_kit/assets`.
* Never raises: on any internal error it walks the fallback ladder (next candidate → best legible
  candidate → uniform contain `safe_fit` → `last_resort`).
* Module switches (set before calling, or via env):
  * `engine.HIDE_MODE ∈ {"alpha", "z_under_bg", "never_text"}` (env `CHAMELEON_HIDE_MODE`, default `alpha`):
    * `alpha`: hidden ⇒ `opacity: 0`, and for text also colour alpha 0 (incl. every `style_runs` colour).
    * `z_under_bg`: hidden ⇒ `opacity: 0`; text additionally gets `z_index = min_z - 1` (colour untouched).
    * `never_text`: text units are never omitted (rent = ∞); images/shapes still hide via `opacity: 0`.
  * `engine.DISJOINT_BOXES = True` (env `CHAMELEON_DISJOINT=0` to allow ink-sharing of transparent padding).
  * `engine.TOP_K = 6`, the number of candidates realised and sent through finisher, critic and rules.

## 2. Hooks the engine calls (all optional; missing module or exception ⇒ hook skipped)

| module | function | when | engine behaviour on failure |
|---|---|---|---|
| `overlay.py` | `calm_regions(source, target_canvas, info, assets_dir) -> [(x,y,w,h,score)]` | once, before search, if `info["bg_kind"] == "photo"` | full canvas used |
| `finisher.py` | `finish(source, output, info) -> output` | each top-K candidate | unfinished candidate kept; finished output that breaks the contract is reverted |
| `critic.py` | `critique(source, output, info, render_png_path=None) -> {"vetoes": [...], "penalty": float, "features": {...}}` | each finished candidate (PNG rendered by the engine and passed) | no vetoes, penalty 0 |
| `rules.py` | `check(source, output, info) -> list[Violation]` (`.rule .severity .ids .detail`; dicts accepted) | each finished candidate | no violations |

**Pick (lexicographic):**
1. contract-hard failures (must be 0);
2. number of critic vetoes plus number of `severity == "hard"` rule violations;
3. number of soft rule violations;
4. energy `E`. The critic penalty only breaks near-ties (`ΔE < 0.03`).

Hooks must be **pure**. They must not mutate `source`, and they must not mutate `info`, except that the finisher may update `info["ink"]` on its own copy.

## 3. `info` dict (produced by `decompile.py` + `engine.py`, consumed by everyone)

Keys from the moderator brief (never renamed):
```
roles       {id: role}   background|logo|hero|headline|subhead|body|cta_shape|cta_label|badge_shape|
                         badge_label|legal|decoration|panel|furniture|unknown
priority    {id: float}  rent / importance (headline = 1e9 i.e. mandatory)
hidden      [ids]        elements this candidate hides (incl. unresolvable assets)
containers  {host_id: [rider_ids]}
groups      {group_id: [ids]}
bg_id       id | None    the (lowest) full-bleed background element
ink         {id: [x,y,w,h]}   visible-pixel box in OUTPUT coords (visible elements only)
src_ink     {id: [x,y,w,h]}   visible-pixel box in SOURCE coords (all elements)
scale       float        chosen shared type scale z (font_i = round(f_src_i * z**gamma_role))
assets_dir  str
```
Extensions (OPTIMIZER; additive only):
```
bg_kind      "photo" | "flat" | "none"        photo = cover/fill image background
regime       "strip" | "wide" | "squareish" | "tall"   (bench/catalogue.band thresholds)
canvas       {"src": [W0,H0], "dst": [W,H]}
units        [{"name", "kind", "ids", "role", "rent", "kept"}]   kind: text|image|pill|chips|rigid|bracket
program      {"source": "logo ¶ headline / subhead ¶ cta", "chosen": "logo | headline / subhead | cta"}
gamma        {role: exponent}                  per-role type elasticity used (z**gamma)
floors_px    {id: int}                        legibility floor applied to each visible text (output px)
font_src     {id: font_size}                  source font sizes (for ramp checks)
live_area    [x,y,w,h]                        region the galley was typeset into (calm region or canvas)
energy       float, energy_terms {term: value}
candidate    int                              rank of this candidate in the search
hide_mode    str
```

## 4. CLI (`run.py`)

```
.venv/bin/python -m design.debate.proto.run TASK [TASK ...] [--sizes 728x90,320x50,...|official|std]
        [--out design/debate/proto/out] [--assets DIR] [--fixedpoint] [--sheet] [--quiet]
TASK  = a task/fixture JSON ({source,target_canvas[,assets_dir]} or a bare design),
        or one of the keywords: samples | fixtures | all
--sizes std = official + 728x90,320x50,160x600,300x250,1080x1920,1080x1080,1600x400
```
Writes `<out>/<design>_<W>x<H>.json|.png`, `<out>/sheet_<design>.png`, `<out>/run_log.txt` (timings,
contract result, hook status, critic vetoes, rule violations, chosen program), and with
`--fixedpoint` the drift table `<out>/fixedpoint.txt`.
