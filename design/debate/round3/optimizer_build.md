# OPTIMIZER — Round 3 build log (proto engine)

Owner files: `proto/engine.py, decompile.py, search.py, textfit.py, contract.py, run.py, __init__.py, INTERFACES.md`.

## Log
- **[1] INTERFACES.md written.** It documents the `info` dict (moderator keys plus extensions), the hook semantics and the CLI. Hooks are optional and wrapped in try/except: a missing module or an exception means the hook is skipped.
- **[2] Repo state at start.** overlay.py (INVENTOR), finisher.py (DESIGNER) and critic.py (PERCEPTION) exist, and so do the fixtures `inventor_{U,F1,F2}`. INVENTOR's requests (REQUESTS.md) are accepted: live areas from `overlay.analyze`, a busy_ratio energy term, and `info.live_area` / `info.calm`.
- **[3] textfit.py written.** It does value-keyed caching only. JUDGE found that the id()-keyed width cache in my R1 solver caused all 5 of its bench crashes, so no cache in proto uses id(). Fonts are integers throughout, and the honest box height is max(ink height, n·f·lh).
- **[4] decompile.py written.**
  - Layers come first: background, texture, furniture and hidden.
  - Host/rider brackets are recursive sub-galleys.
  - Pseudo-pills: an ungrouped small shape with one centred text.
  - Chips: rows of non-CTA pills.
  - Roles are global, so a nested galley agrees with the top level on which text is the headline.
  - XY-cut runs on ink boxes. An overlapping cluster is read top-down instead of being frozen into a rigid island, which was GALLEY's failure mode.
