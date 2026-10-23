# Engine notes

`engine/resize.py` calls `engine/chameleon/` (the "bracketed galley" engine) and falls back to a uniform stretch
only if that package fails to import or raises.

Pipeline (`engine/chameleon/`):
1. `decompile.py`: reading-order stream (XY-cut on visible ink), layers, containers (panels holding text), groups.
2. `search.py` + `textfit.py`: grammar of rows / columns / stacks, one shared type scale found by bisection against the
   renderer's own text wrapping, image size tiers, hierarchy and legibility terms, source-relative faithfulness.
3. `engine.py`: realises the best candidates, relaxes legibility floors step by step when a dense design must fit a
   small canvas, then runs `finisher.py` (typography), `critic.py` and `rules.py` (verification) and picks the cleanest.
4. `contract.py`: output invariants and repair (same ids, in-bounds incl. rotated corners, integer font sizes,
   labels inside their shapes) and the fallback floor.

Stage-one rules followed: every element is kept and visible (nothing hidden via opacity or colour alpha), source
styling is preserved (colour, weight, alignment, line height, z-order, fit), images keep their aspect, no assets are
modified. Runs offline; no network, no model weights.
