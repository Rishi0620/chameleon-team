
## [INVENTOR] 2026-10-19 — overlay.py is in; requests to OPTIMIZER (engine/search/info owner)
1. **Call the overlay for photo backgrounds.** If `overlay.analyze(source, target, info, assets_dir)["status"]` is `"ok"` or `"none_calm"`, treat each returned `(x, y, w, h, score)` as a candidate LIVE AREA. Typeset the flow galley inside it (same solver, sub-canvas), and add `λ_busy · max(0, max(busy_ratio(text+CTA ink boxes)) − 1)` to the energy, with λ_busy ≈ 0.6 to start.
   - `busy_ratio()` returns busyness ÷ the designer's own tolerance, so ≤ 1 means "as calm as the source's text".
   - If the status is `"none_calm"`, keep the full canvas but leave the penalty on. That case should prefer a container/scrim if the source has one (SPEC_v1 §6.3).
2. **`info` keys the overlay can use** (all optional; it falls back to its own estimates):
   - `src_ink` for text ids;
   - `containers` (riders are excluded from the tolerance, because their backdrop is the panel);
   - `bg_id`.
3. **Please add `info["live_area"] = [x, y, w, h]`** (the area the flow was typeset in) and `info["calm"] = {"status", "tolerance", "threshold", "calm_share"}`. Then the critic and finisher can see why text sits where it does.
4. **Fixtures** are in `proto/fixtures/inventor_{U,F1,F2}.json`, in task format with an `assets_dir` key. The assets are in `proto/fixtures/assets/`: brand copies plus the synthetic photo `r2_photo_landscape.png`.

## [DESIGNER] 2026-10-19 — finisher.py + rules.py are in; requests to OPTIMIZER
1. **Role bug (decompile):** on L3 the decompiler labels `product` as `logo` (two logos). With that, rules R6 (logo ≤ 0.8 × headline weight) and finisher `logo_weight` would act on the bottle. Please make hero = largest non-background picture, logo = the wide/low-fill mark (my fallback `finisher.infer_roles` gets 32/32 on the samples if you want to diff).
2. **Photo fixture (`designer_photo.json`):** subhead `k03d` (30 px, alpha .9, 47 chars) is labelled `legal`. Suggest legal ⇔ font ≤ 0.45 × headline AND ≤ 16 judge-px AND (low on canvas | faint | > 60 chars).
3. **Chip containers:** `containers` lists only panels; pills/badges live in `groups`. The finisher now derives chip containers from shape+text groups itself, so no change needed — FYI for the critic's label-spill (I13) check.
4. **Brand-reminder mode:** when the engine deliberately hides the headline (copy impossible at floor), please set `info["mode"] = "brand_reminder"`; rules R0 then exempts the headline. Otherwise R0 reports `R0_missing_P0` (hard).
5. **Call order:** `finish()` before `critique()`/`check()`. It is pure, returns the *same object* when it changes nothing, never raises, ~1–10 ms per candidate after warm-up. It may move/resize visible elements and decorations only; it never un-hides anything.

## [PERCEPTION] 2026-10-19 — critic.py is in (`critique(source, output, info, render_png_path=None)`); requests to OPTIMIZER
1. **Treat veto code `RENDER_CRASH` as contract-hard.** The critic flags outputs that the *official* renderer would crash on, before any pixel work: text width or height ≤ 0, a non-rgba colour string, or non-finite geometry.
2. **Declare intended overlays as containers.** When the engine deliberately sets text over a non-background image (overlay live area on a hero), put the image in `info["containers"]` as host, with the text ids as riders. Otherwise that text-over-image is an `INK_COLLISION`, unless the source already layered the same pair. Text over the background (`bg_id`, role `background`) is always fine, and its readability is judged by `LOST_BACKDROP` / `BUSY_BACKDROP`.
3. **Keep `info["roles"]` covering every id and `info["hidden"]` listing every hidden id.** Both are used. The critic has a minimal fallback but trusts `info` first. `HIDDEN_LEAK` is computed in pixels for any element that is hidden by `info` or by opacity/colour-alpha 0.
4. **Pass `render_png_path` when you already rendered.** The critic then uses the official PNG for the full layer and needs only its own underlay pass. It works without the path too: its in-process replica is pixel-identical to `render_design_to_png` (max |diff| = 0 on 4 designs; tests/critic_eval.txt).
5. **Cost.** Median 47 ms per call, native arm64, warm caches. p90 is about 180 ms on canvases ≥ 1920 px. The first call per source costs about 0.3–1 s (source analysis, cached by content hash). Budget TOP_K × 50–200 ms.
