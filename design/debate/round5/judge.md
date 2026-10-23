# Round 5 judge red-team (shipped engine, engine/resize.py)

Method: all 15 designs (3 samples + S01-S12) x 26 catalogue sizes (390 cases) plus 10 odd sizes, rendered with the official renderer, plus 25 malformed-input mutations and fuzz_engine.py (seeds 101: 80 cases, 202 and 303: 40 each). Scratch: `/private/tmp/claude-501/-Applications/70e2a436-c099-4488-9786-832ede80d468/scratchpad/judge5/` (h.py, mal.py, ov.py; outputs in out/, renders in png/).

Zero crashes, zero render crashes, zero hidden elements, zero id/content/font_family changes, zero off-canvas boxes, zero image-aspect failures across the 390 catalogue cases.

## Confirmed defects

### D1. letter_spacing is not scaled with font size (HIGH)
Rule broken: nothing off-canvas, text not wider than box, legibility. Fuzz seed 101 case 61 also trips contract I6 from this.
Repro: `design/debate/bench/designs/S07_lines_zties_spacing.json`, element `ea4fd1f2` (font 24, letter_spacing 10).
- 160x600: font 2px, box 90 wide, drawn line 278px, ink x 12..290, so about 130px off the 160px canvas.
- 100x100 and 50x2000: ink reaches x=272 and x=268, off-canvas.
- 300x250, 728x90, 320x50, 320x100, 336x280: font collapses to 1px, line 264px in a 107-260px box.
Same for S04 `e4b29beb` (ls 6): 320x50 font 1, line 137 in a 47px box; 100x100 ink to x=154.
Cause: the engine shrinks the font but keeps absolute letter_spacing, so the tracking dominates the width and the solver drives the font to the floor. Mutation check: `letter_spacing=8` on the level2 sample at 728x90 overflows `subhead` (line 458 vs box 222).
Fix: `engine/chameleon/textfit.py` (the `ls` terms around lines 72/231) and the contract/finalise step. Set the output `letter_spacing = src_ls * out_font / src_font` (or `* z`) before measuring. Cap ls so the line still fits the box. Clamp ls to 0 when font < 8.

### D2. Rule / divider shapes and secondary text collide with text (HIGH)
Rule broken: unwanted collisions penalised.
Repro: `S07_lines_zties_spacing.json`.
- 600x200 and 970x90: the horizontal rule is placed through the headline "Live music" (a visible strike-through). The eyebrow (`ea4fd1f2`) sits directly on the headline. The legal line "...terms-and-conditions" crosses the vertical divider.
- 3000x500: headline `e9e0764f` overlaps the date line `e623d2bc` ("Fri 21 June" printed over "golden hour"). Eyebrow overlaps headline too.
D1 is partly the cause (the eyebrow box and its measured ink disagree), but the rule and divider are positioned with no collision check against text ink.
Fix: `finisher.py` and `rules.py`. Rules and dividers are not in the critic's veto set. Place them after text and reject candidates whose rule ink intersects text ink.

### D3. Rotated sticker covers headline text (MEDIUM)
Repro: `S10_story_source.json` at 1280x720, 1600x900, 2560x1440. The red rotated "NEW" sticker (`e805084d`) sits on the "s" of "sips" in the headline `e9955c5f`. My text-ink overlap check gives 405-658 px^2 overlap with no overlap in the source.
Fix: `search.py` candidate generation. Test the rotated AABB of rider/sticker elements against text ink.

### D4. Dark text on busy photo (MEDIUM)
Rule broken: text on busy images penalised.
Repro: `S02_text_over_photo.json`, source colour rgba(25,30,70) on sky. At 300x250, 728x90, 1584x396 and 160x600, the cover-crop leaves little sky and the subhead `eec2f75b` (and part of the headline at 728x90/1584x396) lands on dark-green dotted grass. It is near-invisible. At 300x250 the subhead is at y=113 on grass while sky is only about the top 55px.
Fix: `overlay.py`. Compute calm regions from the exact crop and require luminance contrast against the (unchanged) text colour. Veto when contrast is low and rank candidates that stack all text in the calm band higher. If no calm band fits, the shrink-first ladder should be used before placing on busy pixels.

### D5. Text box wider than its card panel (LOW)
Repro: `S11_card_overlay.json` at 160x600. Headline `ec803fd0` box x 8..152, panel `e84dc3dc` x 10.4..149.6. "Members get" touches the card edges (visible in the render).
Fix: `finisher.py` panel padding. Clamp text box width to panel width minus padding.

### D6. Absurd sizes (LOW, outside catalogue)
At 1x1, 2x300, 10x10: non-background image aspect is off by more than 5% (for example 1.00 vs 2.99) because dimensions round to 1px, and images shrink to 1x1. Font floors at 1. Not a crash. Round-to-int at tiny sizes should keep aspect, or accept it. 4000x4000 takes 35-128s (S10), catalogue max 39s.

## Held up
- All 390 catalogue cases: ids, bounds including rotated corners (no rotated_clip warns), aspect, no opacity/alpha 0, integer font_size >= 1, content/font_family frozen, group label inside its shape, group partial hiding. Zero violations.
- Missing asset ids (holiday_watermark, S08 unknown asset) stay visible as placeholders at sane sizes.
- Mutations that did not break anything: style_runs, hex3 colours, zero-size text/shape/image in the source, duplicate and absent z_index, source opacity 0, all-rotated 33 degrees, off-canvas source elements, blank text, missing line_height/text_align/font_weight, single and empty element lists, unicode/emoji/newlines, capitalize+italic, float font sizes, one big group, 100x100, 3000x500, 500x3000, 50x2000, 728x728.
- Not engine faults: the named colour "red" crashes the official renderer on the source itself (schema requires rgba()), and a font_size of 2000 in the source overflows. Duplicate ids in the source break id uniqueness in any output.
- Fuzz: seeds 202 and 303, 0 failures. Seed 101: 1 failure (D1).
- Tiny type on strips (S03, S12, level3 at 320x50) is the declared honest cost of never-hide, not a rule break.
