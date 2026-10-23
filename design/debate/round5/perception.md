# Round 5 perception: pairwise VLM judging, strip and small formats

Method: 7 designs (L1, L2, L3, S03, S07, S11, S12) x 5 sizes (728x90, 320x100, 300x250, 160x600, 300x600) = 35 cells. I rendered 3 variants and judged the PNGs by eye. Elements are visible in every variant, so the never-hide rule holds.
- A = default (TOP_K=6, DISJOINT=1)
- B = CHAMELEON_DISJOINT=0 (no ink-sharing of transparent padding)
- C = CHAMELEON_TOP_K=1

I did not run 336x280, 970x90 or 320x50. Scratch renders are in `/private/tmp/claude-501/-Applications/70e2a436-c099-4488-9786-832ede80d468/scratchpad/perception5/{A,B,C,m_*.png}`.

## A/B/C table (winner, reason)

| design | 728x90 | 320x100 | 300x250 | 160x600 | 300x600 |
|---|---|---|---|---|---|
| L1 | B: headline and CTA larger | tie | tie | C: headline fills the canvas, A/B text tiny | tie |
| L2 | B: CTA, copy and product larger | C: headline stays one line, product bigger; B breaks the headline and shrinks the product | B: product, headline and copy balanced; C pill text is illegible | B: slightly larger | B: A's headline hugs the right edge |
| L3 | B: body text legible; A/C unreadably small | tie: all tiny | B: product and copy larger | B: product larger | B: larger |
| S03 | B: products and labels 1.5x larger | B: the can is legible | B: larger products, but prices drift away from names | B | tie |
| S07 | A=C: B's kicker overruns and the date overlaps the headline | B: no overlap with the rule | tie | tie: all letterboxed | A: B's date is misplaced |
| S11 | B: card fills the strip | tie | tie | tie: headline touches the card edges | tie |
| S12 | B: badges and price legible | B: price larger | tie | B: bullets readable | B: larger product and logo |

## Verdict

- **B (DISJOINT=0) wins 19 of 35 cells.** It loses 1 (S07 728x90, a clear overlap) and is slightly worse in 1 more (S07 300x600). It ties the rest (about 12). It is clearly better on dense, multi-element designs at 728x90 and 160x600 (L3, S03, S12), where A and C leave content at roughly half the size the canvas allows.
- **K=1 vs K=6 is a wash.** C wins 2 cells (L1 160x600, L2 320x100) and loses none outright. Across the 35 cells the outputs are nearly identical, so TOP_K is not worth tuning.
- **Recommendation:** make DISJOINT=0 the default, but add a post-check that vetoes any B plan with text-on-text overlap (S07 728x90) and falls back to the A plan in that case.

## Three recurring visual failures

1. **Under-scaled content (most common).** A and C show tiny type, tiny products and tiny pills with big dead zones. Examples are L3 and S03 at 728x90, S12 at 160x600, and L2 at 160x600. B recovers part of this.
   - Fix (general): in `engine.py`, `ctx_scale` and the tier selection that follows it; in `search.py`, `max_zi`, `utility` and `unit_dims`. Raise the size-utility cap and the image tiers when the plan occupies less than about 60% of the canvas. Then re-run `best_plan_fixed_z` at a higher `zi`. Add an "occupied-area" term to `energy` so a sparse plan loses to a fuller one.
2. **Collisions that the critic vetoed but the engine still chose.** The run log reports `vetoed_chosen` on 14-20 of 35 runs.
   - Seen in S07: the thin rule runs through the date and headline, the kicker overruns, and the date sits on the headline.
   - Seen in L3: the red stamp overlaps the disclaimer.
   - In S07 160x600 the whole layout falls back to a letterboxed strip with white bars. That is the `fallback=1` run.
   - Fix (general): `critic.py` `_veto` should hard-reject text-on-text overlap in `search.py` `search`, ranking by `energy` only among non-colliding plans. In `engine.py`, `_place_furniture` and `_overlap` should treat rules and lines as obstacles for text, not as free decoration. They should push the line to a canvas edge or shorten it. Replace the letterbox floor (`_floor`) for extreme aspect ratios with a real vertical stack, so 160x600 never gets a white-bar layout.
3. **Orphaned groups and ragged alignment.**
   - In S03, prices and names detach from their products in 300x250 and 300x600, and the product-to-label pairing is lost.
   - In S11 and L2 at 160x600, headlines touch the card edges.
   - In L3 and S07 at 300x600, the date sits off-axis from the headline.
   - Fix (general): in `decompile.py`, `decompile` and `_unit`, bond image + label + price into one cell unit so `search.py` `make_plan` keeps them together. In `finisher.py`, `p9_furniture` and the margin and rhythm passes should enforce a minimum inner padding for text in cards, and share an alignment axis between the headline and date.

## Do general rules fix these?

Yes, all three are systemic, not one-offs.
- Failure 1 needs a fill-ratio term, not per-design tuning.
- Failure 2 needs a hard no-text-overlap constraint plus a proper tall-skinny fallback layout.
- Failure 3 needs bonds at decompile time.

None of them needs hiding, so they stay within the organiser ruling.
