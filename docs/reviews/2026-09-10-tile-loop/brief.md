# Adversarial review: cell grid, step 2 -- the tile loop on a resident source

Scope: the HEAD commit of this repository, titled "Cell grid, step 2: the window loop runs TILE by
tile on the resident source ..." (run `git log -1` and `git show HEAD` for the diff; the parent is
a91cfcf). Files: src/spextractor.cpp (the tile loop wrapped around the window loop's parallel
region; `canonicalSort_`; the option `tile:cells_per_tile`; the per-window run-level band edges
`wbands`; `Carry`/`carry_in`/`carry_out`; `visited`; the precursor selection `pidx`; the per-tile
output block; the writer opened before the first tile), bench/semantic_digest.py and
test/test_spextractor.py (count normalisation; e2e check 16).

The contract is STEP 2 of docs/reviews/2026-09-10-tiled-reader-plan/judge.md (the paragraph
starting "STEP 2 -- tile loop on a RESIDENT source"). Read it first, then the diff, then the
surrounding code (the window body is a lambda inside `#pragma omp task`; the detection runs per
RT cell inside it -- `cell_edges`, `cut`, `f0z`; the fragments' RT is `rtOf(wst, t)`, a frame time
of the window's FROZEN table; a precursor's RT `pc.rt` is an MS1 frame time; scoring gates
candidates by |rtOf - pc.rt| <= gate:delta_rt in `assembleOne_`/`scoreCandidates_`/`FragRt`).

What must hold (the cluster gate): (G0) with one tile (the default, `tile:cells_per_tile 0`) the
output is BYTE-IDENTICAL to the parent commit on every pin (D at 600 / -1 / 300, TNBC 009 at 600,
the exact `count`); (G1) D at pitch 300 (6 cells) run as 2, 3 and 6 tiles at 8 and 100 threads
gives the SAME spectra as the one-tile run (digest from `<spectrumList` on, with the zero-padded
count normalised), TNBC 009 at 600 as 13 tiles likewise; the tiled files pass the count/index
invariants; a Sage search of a tiled file reproduces the one-tile file's peptides exactly.

Attack these, and anything else:
1. G0 identity: `toTof` now runs for every window BEFORE the loop (in parallel) instead of inside
   the body; the band edges come from `wbands` (the whole slab's extremes computed the same way);
   `pidx` replaces the [plo, phi) walk with a filter that is a no-op at lo = -inf / hi = +inf;
   `pslot` is indexed by position in `pidx`; the DataProcessing entry is one shared_ptr pushed by
   the tool instead of `addDataProcessing_`; the writer is opened before the loop with the stamped
   (empty) PeakMap as settings; `setExpectedSize` is called before the single block. Any byte that
   can move (header aside)? Any change in the ORDER of spectra inside the block?
2. G1 exactness: (a) ownership -- `tile.lo - delta_rt <= pc.rt < tile.hi - delta_rt`: do the ranges
   partition every finite precursor exactly once (first lo = -inf, last hi = +inf; `visited`
   throws on a second visit but nothing checks "never visited")? (b) candidates -- is EVERY
   fragment a tile-k precursor can use either detected in tile k's cells or carried in? The carry
   keeps records with `rtOf >= tile.hi - 2*delta_rt` over ALL of frag_traces (own + carried-in) --
   is the induction sound, including the case pitch < 2*delta_rt (a fragment must cross several
   tiles)? Is `rtOf` guaranteed to lie inside the trace's cell (it is the smoothed apex frame
   `frame0 + rt_at`; can `rt_at` point outside the span after `trimToSpan`)? (c) is any window-level
   quantity a function of the SET of fragments rather than of each fragment: `FragRt` (rt0/inv
   buckets -- a pre-filter only?), `buildFragStats` (mean/invnorm per trace, `nearest_local` from
   the frozen table), the 500-candidate cap tie-break (position in the sorted list), `pdense`,
   the `[gstat]` numbers, the content sort's total order? (d) carried spans are copied onto
   `wst.inten` with `off` rebased and `frame0/bframe/rt_at` untouched -- is the frozen table
   really identical in every tile (same `fwin`), and is `wst.bins` guaranteed empty by then?
   (e) the empty-slab branch (a window with no frame in the tile) sets only the frame table; is
   anything else the scoring needs left uninitialised (`w_tlo/w_thi`, the `[tof]` bounds,
   `frag_traces` empty then carried-in appended)?
3. The resident source: `sliceFrames(sl, f0, f1)` after `toTof` (b filled; frame_id already
   dropped); the binary searches on `rtAxis()[rt_index[f]]` against `tile.lo/hi` (cell edges are
   MS1 frame times; window frames never coincide with them?) -- half-open consistent with the
   body's own per-cell `cut` (lower_bound on the same values)? Peaks of a window frame exactly at
   an edge?
4. Thread safety: `carry_out`/`visited`/`wbands` are std::maps pre-populated before the parallel
   region and only `.at()`-accessed inside; `tile_slabs` is built serially; the per-tile
   `win_out`/`win_done` are declared inside the tile loop. Anything mutated structurally inside
   the region? The `#pragma omp critical(winlog)` reuse?
5. The writer: `TileWriter` is fed K blocks; the header is written at the first block from
   `settings_` + the first spectrum's DP; `count_off_` placeholder patched in the destructor
   (`writer.reset()` inside a Phase); `spectra_offsets_` grow across blocks; the `<indexList>`
   offsets and `indexListOffset` for a multi-block file. mzPeak output refuses K > 1. Is the
   destructor order safe when an exception escapes the tile loop (writer destroyed while the
   file is half-written)?
6. Memory/perf of the identity arm: is anything now resident that was not (all slabs converted up
   front; `wl` copies; `carry_out` entries for every key)? Does the Fix-A trim still fire at the
   right moment with one tile?
7. e2e check 16: does it actually exercise >= 2 tiles with the fixture (pitch 10 s, 14 cycles of
   1.4 s), a straddling precursor, the carry, and the multi-block writer? What is missing
   (the judged plan's 17/18)?
8. Anything that blocks the next steps (3a run-level band edges from the acquisition range; 3b the
   .d reader delivering only a tile's frames with `load_ms1=false`, where `n_ms1 = ms1_.size()`
   is 0 for the slab reservation).

Report format: numbered findings with severity (blocker / must-fix / should-fix / note), file:line,
a concrete failure scenario, the fix; then which attack lines you checked and found sound. Do not
summarise the diff back to me.
