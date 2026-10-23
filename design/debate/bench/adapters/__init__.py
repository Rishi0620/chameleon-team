"""Thin adapters: each module exposes NAME, resize(source, target_canvas) and optionally applies(W, H).
They import the round-1 spike engines WITHOUT editing them; asset-dir globals are re-pointed at
bench/assets (brand_kit copies + 2 generated test assets) so every engine sees the same files."""
