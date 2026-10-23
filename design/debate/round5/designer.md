# Round 5 - Designer review (judge's eye)

Renders: `/private/tmp/claude-501/-Applications/70e2a436-c099-4488-9786-832ede80d468/scratchpad/designer5/` (sheets `sheet_S01_split_photo.png`, `sheet_S02_text_over_photo.png`, `sheet_S05_rotated_sticker_bleed.png`, `sheet_S12_many_badges.png`, plus per-size PNGs `<design>_<WxH>.png`). Sizes: std set.

## Top 8 defect classes (ranked by likely judge penalty x generality)

**1. Headline text sitting on the busy part of a full-bleed photo (text-on-busy-image).**
S02_text_over_photo_728x90, _320x50, _1600x400: the navy headline "Picnic season is here" lies over the dotted meadow. In 1600x400 the "season" glyphs are crossed by black and red blobs. Navy on dark green is also near-zero contrast. The 160x600 and 300x250 outputs are fine because the sky band is tall enough. A judge calls this "illegible, text over busy photo", the worst single penalty.
Fix: in `search.py:energy` raise the `busy` weight so a text item cannot score well on the meadow. Make busy a hard cap on text boxes when `overlay.busy_ratio` > ~1.3, so the plan falls back to the calm sky strip (`overlay.calm_regions`). Where no calm rect fits, have `finisher.halo_followers` add a scrim, but the "hidden" ruling means it must be a visible, semi-opaque solid (alpha ~0.6, not 0). `critic.py` already measures `busy` and `contrast`, but the soft penalty is too weak in strips (728x90, 1600x400, 320x50).

**2. Dark-on-dark / low-contrast text after relocation.**
S02 728x90 and 320x50: the subhead "Pack the new Solstice botanicals" is dark navy over dark green, unreadable. The SOLSTICE wordmark (white) is lost on light sky in S02_300x250 and _1080x1350. Text colour was tuned for the sky and is not re-checked after the move.
Fix: in `critic.py` (`_text_pixels` contrast term, around line 545), make contrast failure a veto, not only a penalty, when the contrast is under 3:1 and the text is not decorative. Allow the finisher a colour swap to the brand light/dark pair, which keeps brand fidelity.

**3. Micro-text and tiny CTAs on tall formats (hierarchy collapse at 1080x1920 and 160x600).**
S01_split_photo_1080x1920: the subhead is about 10 px and the CTA pill is tiny, with a large empty dark band under the content. The headline is also small for a 1080 wide canvas. S05_..._1080x1920: the "Every flavour" line and the 50% badge are minuscule. S12_many_badges_160x600: all six badge labels are unreadable specks. The shared type scale `z` is capped by the narrowest column or the image tiers, not by the free canvas.
Fix: in `search.py` (`max_zi`, `W["size"]`, `W["leg"]`), let `z` grow until column fill is about 85 percent on portrait canvases. Add a floor for the CTA label of about 2.2% of the short side, and a floor of about 0.9% for legal text and the smallest text role. If six badges cannot reach the floor, `search.py:make_plan` should drop the badge row (by copy-budget "rent") instead of shrinking it. A readable page with fewer badges beats a full page of specks.

**4. Awkward vertical empty space / content floating (poor vertical distribution).**
S01_..._1080x1080 and _1080x1920: the content block is compact, centred, with large equal voids top and bottom. S12_..._1080x1920: dead space between the pack and the badge row. S12_160x600: the bottom 25% is empty. The judge reads this as "unused space, weak composition".
Fix: after the solve, `finisher.py` (the margin/rhythm snapping pass) should distribute the slack as larger inter-group gaps (capped at about 2.5x the base gap) and scale the hero image up (`engine.py` image size tiers) before leaving margins empty.

**5. Hero image undersized or oddly framed.**
S01_1200x628: the photo became a floating inset with margins, where the source is a full-height half-bleed panel. The split concept is lost, and that is the brand-fidelity cue. S01_728x90 and _320x50: the photo is a thumbnail. S05_1600x400 and _728x90: the product is tiny next to the headline.
Fix: in `engine.py:_place_furniture` and the image-tier logic, prefer a bleed-to-edge image panel for images that bled in the source (src_cov in `engine.py:_src_cov`). Add an image-area term to the `search.py:energy` utility that rewards keeping the source image share of area (about 0.6 to 1.0x the source ratio).

**6. Collisions and badge/sticker problems (S05, S12).**
S05_1080x1080: the 50% sticker moved to sit tight against the "Summer Sale" headline's right end and the CTA row, with a faint grey disc (decor) overlapping the headline. S05_300x250: a grey disc ring is behind the can, which reads as a rendering artefact. The sticker edge at 160x600 hugs the canvas edge. S12_300x250: the product can sits tight against the bullet list and the first badge row, with the CTA crowding the badges. Overlaps that were intentional in the source (sticker over the product) should be preserved, and unintended ones removed.
Fix: `rules.py` collision check should include decor discs and furniture and not only text and images. In `finisher.py:overlap_pairs`, move decor rather than content. Enforce a minimum inter-item gap of about 1.5% of the short side between text and badge or CTA in `search.py:_pair_gap`.

**7. Rag and wrap defects in headlines.**
S01_300x250: "Golden / hour, bottled." splits the unit awkwardly. S01_160x600: "Golden / hour, / bottled." leaves an orphan accent word on its own line. S02_320x50 and _1600x400: "Picnic season / is here" has an unbalanced break. S02_1080x1350: a two-line subhead leaves a short last line.
Fix: `finisher.balanced_int_width` and `rag_penalty` need a heavier penalty on a last line under 40% of the width and on a break inside a phrase ("Golden hour," should stay together). `search.py` `W["breaks"]`, `W["oneword"]` are low (0.15 and 0.2), so raise them.

**8. Banner strips (728x90, 320x50): crowding and the logo/legal fragments.**
S12_many_badges_728x90: logo, price, bullets, can, six badges, CTA and the legal text are all squeezed in, and the legal text is a grey smudge. S12_320x50 is pure noise: eight tiny things. S01_320x50 and S05_320x50 are tidy but the logo is a speck (about 4 px). A judge penalises noise more than omission.
Fix: in `search.py` give strips a stronger per-element legibility cost. Let the copy budget drop legal text, secondary bullets and badges in strips under about 100 px high, if it keeps the hierarchy intact (`W["drop"]`, `drop_mult`). Allow dropping low-value decor instead. The ruling forbids hidden elements, so "drop" in the output must still mean visible but compacted (smaller, in a stack), and the engine's `_hide` path must keep it on canvas and visible. Check this carefully.

## Observed positives
CTA pills keep brand colour and shape. Logos stay clean and uncropped. No strike-through lines from rules were seen in these 4 designs at std sizes. S05 1080x1080 and 1600x400 are well composed.

## The 3 changes to make first
1. **Busy-text hard cap plus visible scrim (class 1 and 2).** `search.py:energy` busy term (raise the weight and add a hard rejection above a busy_ratio threshold), `critic.py` contrast veto below 3:1, with a fallback of `finisher.halo_followers` adding a visible semi-opaque backing. This fixes the S02 strip failures, the most visible defects.
2. **Legibility floors with drop-before-shrink (class 3 and 8).** Add a minimum judge-pixel size for CTA, subhead, legal and badge labels in `search.py` (`max_zi`, `W["leg"]`, `W["drop"]`), so micro-text is replaced by fewer, readable elements (compacted, never hidden).
3. **Fill the canvas better on portrait and square (class 4 and 5).** Scale the hero image and type up to use the free space in `engine.py` image tiers and `finisher.py` rhythm/margin passes, preferring bleed panels where the source bled, so tall outputs stop looking like a tiny block in a dark void.
