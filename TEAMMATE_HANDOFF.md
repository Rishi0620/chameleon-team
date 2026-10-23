# CHAMELEON — teammate handoff

Read this first. It covers what the project is, what is already built, what is broken, who owns what, and how to run everything.

## 1. The task (hackathon rules in short)

`engine/resize.py` exposes `resize(source, target_canvas) -> dict`. It re-lays-out a design JSON (text, image and shape elements) into a new canvas size.

- Keep the same element ids.
- Keep the content and fonts fixed.
- Output must render through the official renderer (`renderer/`) without crashing.
- Scoring: structural JSON checks, plus a VLM judge on the rendered PNG, over hidden designs and platform-catalogue sizes.
- Stage-one scoring runs with `--network none`. Nothing can be installed or downloaded at run time.

The full rules are in `RULES.md`, `FAQ.md` and `chameleon_design_schema_v0.9.json`. Read them before changing the engine.

## 2. Where the work lives

| path | what it is |
|---|---|
| `engine/` | Starter engine. Our winning engine goes here at the end. |
| `renderer/`, `brand_kit/`, `input/`, `Dockerfile` | Organiser code. **Do not edit.** |
| `design/debate/00_CONTEXT.md` | Shared ground truth for the design debate. Start here for context. |
| `design/debate/round1/`, `round2/` | Five independent proposals, then critiques. |
| `design/debate/round3/SPEC_v1.md` | The unified architecture spec (~7k words). The main design doc. |
| `design/debate/round3/*_build.md` | What each owner built, and what they still think is missing. |
| `design/debate/round4/redteam_designer.md` | Red-team notes. **Incomplete**: only the first pass was written. |
| `design/debate/proto/` | The merged prototype. One owner per file (see §4). Interfaces in `proto/INTERFACES.md`, cross-owner requests in `proto/REQUESTS.md`. |
| `design/debate/bench/` | The benchmark: 15 designs × 26 sizes = 390 cases per engine. Scoreboard in `bench/SCOREBOARD.md`. |
| `design/debate/spikes/<name>/` | Each agent's experiment code. Reference only. |
| `design/debate/proto/fixtures/`, `bench/designs/` | Test designs, including synthetic adversarial ones (opaque ids). |

Generated outputs (renders, sheets, results, `r2_out`, `proto/out`) are gitignored. Re-create them by running the commands in §6.

## 3. Architecture (the "bracketed galley")

The engine is a pipeline. Each stage has one job.

1. **Decompile** (`decompile.py`). XY-cut on ink boxes gives a reading-order stream. Layers are background, texture, furniture and hidden. Containers are host/rider panels, which hold text on a coloured shape. Bonds keep consecutive text units together, so a picture can't split them. The output is the `info` dict (§5).
2. **Search** (`search.py`). The stream grammar is `¶` (row), `|` (column) and `/` (stack), with nested brackets for containers. For up to 10 units, enumerate. For more, use Knuth–Plass DP with skip transitions, where omission costs the unit's "rent".
3. **Inner solver** (`engine.py`, `textfit.py`). One shared type scale `z`, with per-role exponents γ. Bisection runs against the renderer's exact wrap (`renderer/converter/wrap.py`). Also: exact text frontier, image size tiers, PAVA positions, copy budget and a hard hierarchy. The logo's ink must be at most 0.8 × the headline's ink. Size utility is concave and capped. Do not make it monotone in size: inverse optimisation showed that breaks the source-as-optimum property.
4. **Finish** (`finisher.py`, owner DESIGNER). Balanced wrap, no widows, cap-height optical centring, balanced margins, rhythm snapping on tall canvases, CTA label ≥ 12 judge-px, strips cap the headline at 3 lines. Brand-reminder mode only when copy is genuinely impossible.
5. **Overlay** (`overlay.py`, owner INVENTOR). For photo backgrounds, find calm regions of the exact centre-crop the renderer produces.
6. **Verify** (`critic.py`, `rules.py`). Render the top K candidates. The pixel critic and the rule set produce vetoes. Use them lexicographically: hard vetoes, then rule violations, then energy `E`. The critic penalty only breaks near-ties (ΔE < 0.03).
7. **Contract, repair, fallback** (`contract.py`). 12–16 invariants. Integer font sizes, no zero-size text, rotated boxes in bounds, rgba colours only. The fallback ladder ends at the best legible candidate. It does not end at a "safe" layout that may be unreadable.

**Taste calibration.** Three rules, from the debate:
- The source canvas is a fixed point. Run the engine with target = source canvas and check drift < 3%. This is a CI test.
- Source-relative tolerances. Use the source's own metric values as the threshold, not absolute numbers.
- Far-regime exchange rates come from Crello format priors and dev-time VLM pairwise labels. Never use the source as the only objective.

**Hide policy.** `engine.HIDE_MODE` is one of:
- `alpha` (default). Hidden means `opacity: 0`. Text also gets colour alpha 0, on every `style_runs` colour. Text `opacity` is ignored by the renderer, so this is required.
- `z_under_bg`. Hidden text gets `z_index = min_z - 1`. Only works with an opaque full-bleed background.
- `never_text`. Text is never omitted.

Open question for the organisers: is opacity 0 accepted as "dropped"? May a hidden element's colour alpha change?

## 4. File ownership (suggested split)

Each file should have one owner at a time. Coordinate through `proto/REQUESTS.md` (append-only, tagged with your name).

| file | suggested owner | notes |
|---|---|---|
| `engine.py`, `decompile.py`, `search.py`, `textfit.py`, `contract.py`, `run.py`, `__init__.py` | **you** (lead) | Engine core and merge. |
| `finisher.py`, `rules.py` | **teammate** | Typography rules and the finisher. Pure functions, no side effects. |
| `critic.py` | **teammate** | Pixel critic. Its weights are the calibration target. |
| `overlay.py` | **teammate** or **you** | Calm regions for photo backgrounds. |
| `bench/` | **teammate** | Benchmark runner, scoring and weight tuning. Changes here must not change the scoring formula without a note in the scoreboard. |

Hooks are optional. If a module is missing or throws, the engine skips that hook. Hooks must be pure: they must not mutate `source`, and must not mutate `info` (except the finisher updating `info["ink"]` on its own copy).

## 5. The `info` dict

Produced by `decompile.py` and `engine.py`. Consumed by the critic, finisher, rules and overlay.

```
roles       {id: role}      background|logo|hero|headline|subhead|body|cta_shape|cta_label|
                            badge_shape|badge_label|legal|decoration|panel|furniture|unknown
priority    {id: float}
hidden      [id]            every hidden id (the critic relies on this list)
containers  {host_id: [rider_ids]}
groups      {group_id: [ids]}
bg_id       id | None
ink         {id: [x,y,w,h]} visible-pixel box, OUTPUT coords
src_ink     {id: [x,y,w,h]} visible-pixel box, SOURCE coords
scale       float           shared type scale z
assets_dir  "brand_kit/assets"
mode        "brand_reminder" only when the headline is deliberately dropped
```

Keys are added, never renamed. Full details: `design/debate/proto/INTERFACES.md`.

## 6. How to run things

Run everything from the repo root, using the venv.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` pulls the renderer from GitHub (`cr-renderer`, an external project). Install it once. The Docker image does this at build time too.

Run the prototype on the samples and fixtures:

```bash
.venv/bin/python -m design.debate.proto.run samples fixtures --sizes std --fixedpoint
.venv/bin/python -m design.debate.proto.run input/chameleon_sample_level3_advanced.json --sizes 728x90
```

Run the benchmark (one fresh process per engine and design; resumable):

```bash
.venv/bin/python design/debate/bench/run.py
.venv/bin/python design/debate/bench/run.py --engines optimizer --designs S03_multi_product_grid --force
.venv/bin/python design/debate/bench/run.py --module my_pkg.my_engine   # any module exposing resize()
```

Then regenerate the scoreboard with `bench/report.py`.

Tests: `pytest` is not in the venv. The test files in `proto/tests/` (`test_critic.py`, `test_finisher.py`) were written for pytest. Install it into the venv (`.venv/bin/pip install pytest`) and run `.venv/bin/python -m pytest design/debate/proto/tests`.

Ship the engine: the Docker image only copies `engine/`, so after changing anything under `design/debate/proto/` run `./scripts/sync_engine.sh`. It copies the modules into `engine/chameleon/`, which `engine/resize.py` calls (falling back to the stretch baseline if it ever fails). Never edit `engine/chameleon/` by hand.

Tests and fuzz (pytest is installed in the venv):

```bash
.venv/bin/python -m pytest design/debate/proto/tests -q
.venv/bin/python design/debate/proto/tests/fuzz_engine.py 60 1   # N cases, seed; must print failures=0
```

Docker check, as the organisers run it (verified working, network none, all three samples OK):

```bash
docker build --platform linux/amd64 -t chameleon .
```

Then follow `README.md` for the run command.

## 7. Benchmark status and gates

Current scoreboard (390 cases each, `bench/SCOREBOARD.md`):

| engine | mean | p10 | crashes |
|---|---|---|---|
| **proto (merged engine, current)** | **92.9** | 80.9 | 0 |
| optimizer_fixed (proto's ancestor) | 90.4 | 79.9 | 0 |
| galley | 88.1 | 73.2 | 3 |
| designer | 86.5 | 69.7 | 0 |
| perception | 52.3 | 0.0 | 50 |
| safe_floor | 71.9 | 43.5 | 0 |

**Merge gates for the final engine:** mean ≥ 90.4, p10 ≥ 80, zero crashes, zero hard structural failures. The scoreboard's `unreadable_text` count for the safe floor (936) shows why the fallback must be the best *legible* candidate.

Caveat: the composite score is a proxy. Read the caveats at the bottom of `SCOREBOARD.md` before quoting a number. Differences of a few points between designed engines are within the noise (rank stability: optimizer_fixed #1 in 90% of re-weightings, all sizes).

## 8. Known open bugs

**Fixed (bench: proto mean 92.9, p10 80.9, zero crashes, every shape band p10 >= 80):**
- Glyph-width cache keyed by `id()`: `textfit.py` keys by value now.
- L3 at 320x50 fell back to the safe layout: the relaxed headline floor rounded up to 11 px. Now 10 px; output is logo + headline.
- Furniture (ribbon) text below the legibility floor is hidden instead of shown at 4 px (`engine._place_furniture`).
- Source structure is always a search candidate, even above the row limit (`search.patterns`); omission and structure-change penalties and the margin are source-relative near the source canvas. L3 same-size drift is now 2.9% mean.
- Brackets (cards/panels) may omit low-rent riders instead of failing (`search.bracket_dims`): S11 at 320x50 no longer falls back.
- The engine escalates the relaxation ladder when the winner is still vetoed (`engine._run`).
- Finisher leaves decorations alone when the target canvas equals the source canvas.
- Hide-mode A/B on the bench: alpha 92.9, z_under_bg 92.8, never_text 90.6 (p10 77.8, fails the gate).

**Still open:**
- L2 at its own canvas: drift 4.2% mean / 12% max (headline and subhead vertical placement). Target is under 3%.
- L3 at 1080x1080: legal text can land as a small side column mid-canvas.
- S04 at 160x600 still has TEXT_OVERFLOW / ILLEGIBLE / LOST_BACKDROP vetoes (3 candidates cannot be made clean).
- Logo is small in tall and story formats; logo/product tiers are untuned.
- Overlay live-area result at 728x90 (no calm pixels) is untested.

**Design gaps the team has not closed:**
- Perception critic is weak on designed-vs-designed pairs (36–64% agreement). It is reliable for broken-vs-designed (~92%). Use it for vetoes, not ranking.
- Ink-vs-box packing: boxes may overlap. Confirm with organisers whether JSON box overlap is penalised.
- Extreme formats (160×600, 320×50): floors need the Crello priors. Currently 8–9 px text is possible.

## 9. Ideas that are decided — don't re-debate

- Source as the sole objective: rejected.
- Monotone size reward: rejected (breaks source-as-optimum).
- Z-under-background as default hide: rejected (needs an opaque background). Alpha 0 is the default.
- Per-design calibration: only structure and faithfulness weights, in a trust region.
- Brand-reminder mode only when the copy is genuinely impossible, and always logged.

## 10. Model and effort guidance (to keep usage down)

- Building engine code: Sonnet, medium effort.
- Running bench, checks, reruns: Haiku, low effort.
- Final merge decisions and red-teaming: Opus, high effort, sparingly. Ultra effort on Opus used up the usage quickly.
- Use subagents on Sonnet for independent, file-scoped tasks.

## 11. Organiser questions to ask

1. Is opacity 0 accepted as "dropped"?
2. May a hidden element's colour alpha change?
3. May JSON boxes overlap?

Ask these before finalising the hide policy.

## 12. Git

- `origin` for this repo is the team's private repo. The hackathon's upstream is kept as `upstream` (`jhaaj08/chameleon`). Do not push to upstream.
- Commit the source, docs and fixtures. Generated outputs are gitignored.
