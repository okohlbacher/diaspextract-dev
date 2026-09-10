Adversarial review of 1e7dcb1 (cell grid, step 2: the tile loop on a resident source), 2026-09-10.
Brief: brief.md (eight attack lines). Fixes: 5570d25 (Codex) and the follow-up (Kimi).

- codex.md -- Codex / GPT-6 (gpt-6-astra): "G1 has concrete counterexamples". Must-fix: (1) the
  ownership/carry boundaries were real-number arithmetic -- two reproduced double counterexamples
  at delta_rt = 3 (edge 7.2 / precursor 4.2 / fragment 1.2: the scorer accepts |4.2-1.2| = 3, the
  carry threshold 7.2-6 = 1.2000000000000002 drops it; edge 3.1 / precursor 0.1 / fragment 3.1:
  owned before the edge by 0.1 < 0.10000000000000009, its candidate detected after it); (2) the
  spectrum comparator ignored the isolation offsets, so two overlapping windows emitting one
  precursor with equal peaks could sort either way per tile; (3) the fragment comparator ignored
  the profile, so two band-duplicate traces sharing every compared scalar could sort either way;
  (6-8) e2e 16 exercised one non-empty block, no observable carry, no padded/empty window.
  Should-fix: MS1 state now lived through the per-tile sort/write; a failed tile left a
  structurally complete partial file; the digest tool's count normalisation missed a chunk
  boundary. Notes: `visited` proved at-most-once, not coverage; the step-3b reader still needs
  metadata-driven keys and an explicit expected frame count.
- kimi.md -- Kimi Code: no blocker/must-fix; the exactness argument "holds up line by line" (the
  induction, FragRt as a superset pre-filter, the frozen table in every tile, the DP pointer, the
  writer's cumulative offsets); should-fix: the contract's emitted-RT detector, a transitive-carry
  arm (pitch < 2 delta_rt), `indexListOffset` on the tiled file, e2e 18; notes: the partial file
  on exception, the Fix-A trim at K > 1, an unchecked uint32 narrowing on the carry-in, log
  semantics at K > 1, no `readTile` seam yet (step 3b's job).
- vibe.md -- 0 bytes: the documented bash-permission cause.

Fixes: ownership is decided with the scorer's own subtraction ((T - rt) > delta_rt; the first
tile for which it holds owns the precursor -- monotone in T, so exactly one does) and marked
before any early exit, with a coverage check after the last tile and a per-precursor ownership
detector in the scoring loop; the carry threshold carries a proven 1e-6 s slack (over-carry is
harmless, under-carry is the defect); both comparators are total on content; MS1 state is
released before the last tile's output; the Fix-A trim fires only with one tile; the mzML is
written as `<out>.part` and renamed on completion; the digest tool normalises the count on the
complete opening line; the carry-in checks the arena bound like absorb(); e2e 16 (two non-empty
blocks, exact one-tile count, all of check 14 on the tiled file), 17 (SPEXTRACTOR_TILE_NO_CARRY
must change the output; the pitch-5 transitive arm), 18 (a window with no frames in a middle
tile).

Gate: docs/BASELINE.md "Cell grid, step 2".
