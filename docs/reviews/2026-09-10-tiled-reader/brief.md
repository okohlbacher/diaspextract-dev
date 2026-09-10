# Adversarial review: cell grid, step 3b -- the .d streaming source (tile by tile through the loader)

Scope: the HEAD commit ("Cell grid, step 3b: the .d streaming source reads the run in two passes";
`git show HEAD`; parent 7e71998). Files: patches/openms-brukertims-mz-calibration.patch (the new
hunks: `Config::dia_ms2_rt_lo/hi` in BrukerTimsFile.h; in the streaming MS2 loop the per-group
selection `frame_ids` = the group's frames with `lo <= time < hi`, placed AFTER the frame-table
export and BEFORE the unchanged batch loop), src/spextractor.cpp (function-scope `cfg`/`spicker`,
`tile_source`, `run_tables`; pass 1 with lo = +inf / hi = -inf; `frozen` and the RT axis from the
tables; `n_win`/`fkeys`; `wbands` over the frozen keys with the slab scan only where a resident slab
exists; the per-tile read in the tile loop -- a fresh `PickCompactConsumer` over
`loadDIAStreaming(in, tc, c2)` with `tablefn` = the frozen tables restricted to [lo, hi), the
per-window invariant, empty slabs for absent windows, `indexRt`; the slab reservation from the
window's table count; `spx:tile_source`).

The contract is STEP 3b of docs/reviews/2026-09-10-tiled-reader-plan/judge.md. The gate that runs
now (scratchpad chain_step3b.sh): G0 -- one tile on D (600 / 300 / -1 trace) and TNBC (600) must be
IDENTICAL to the flipped-default pins (D `8c1b047f`, TNBC `bff54a1f`, the files under
/scratch/kohlbach/pins_acq); G1 -- D at 300 as 2/3/6 tiles x 8/100 threads and TNBC 600 as 13
tiles IDENTICAL; the resident source (SPEXTRACTOR_TILE_RESIDENT=1) as the same-build control;
per-tile read wall and RSS; e2e 18/18.

Attack:
1. Exactness of the per-tile read: is the set of frames the loader emits for [lo, hi) exactly the
   frozen table's frames in that range (the table is exported before the selection; `frame.time`
   is the same double; half-open on both sides; the cell edges are MS1 frame times, so no MS2 frame
   sits on an edge -- true for every acquisition?); does the batch loop over the selected subset
   pick each frame identically to the whole-run loop (the picker is per-frame pure: measured 256 ==
   4096 batches; anything batch-COMPOSITION dependent left, e.g. `SPEXTRACTOR_LOAD_BATCH`, the
   thread-local ZSTD contexts, `cents` merging)? The lockstep padding against the tile's table
   slice: a frame the loader skips (num_peaks == 0 is excluded from the table; an empty IM slice is
   padded) -- consistent with pass 1's whole-run table on the pinned files (0 pads)?
2. Pass 1: with lo > hi the loader emits no MS2 frame but `g_dia_frame_table` is filled; the
   consumer's `tables_` initialise at `finish()`'s `flush_()` with zero MS2 frames; every window
   is "absent" -> `frame_table_src = loader`, `run_tables` copied. `frozen` from `run_tables`
   (rt, id) -- identical to what the resident path derives from the padded slabs? The RT axis
   from `frozen` (all windows' frame times) -- identical to ms1 U slabs when P = 0?
3. `n_win`/`fkeys` replace `window_list.size()` for n_bands/n_conc/the log, and key `wbands`,
   `carry_out`, `visited`, the coverage check. Any remaining use of `window_list` that is wrong
   under the streaming source (it is EMPTY then)? The K > 1 resident slicing still iterates
   `window_list` -- unreachable under the streaming source?
4. The per-tile consumer: `ms1_none` (an empty PeakMap) as `ms1_`; `cstat` shared across tiles;
   `spicker` reused (its Param is deep-copied per flush); `tc.tablefn` captures `tile` by
   reference; `expected_frames` = the window's table count for the reserve (was `ms1_.size()`).
   The per-window invariant and the absent-window empty slab; `indexRt` on an empty slab;
   `toTof` later in the body on an empty slab; `sliceFrames` never called. Memory: what is
   resident across tiles now (the previous tile's `tile_slabs` freed at the end of the loop
   iteration? `wl` dangling?), the consumer's scratch, the loader's handle (re-opened per tile:
   cost?).
5. `trace:band_edges=slab` refuses under the streaming source -- but is the refusal reachable
   before the load? (It sits in the `wbands` block after the MS1 phase.) `SPEXTRACTOR_TILE_RESIDENT`
   as an undocumented switch. The mzPeak source is unchanged (resident) -- is anything in the
   shared code now wrong for it (e.g. `frozen` built from slabs when `tile_source` is false but
   `run_tables` non-empty)?
6. The `[stream] ... falling back to loadExperiment` catch around pass 1: with the streaming
   source, a fallback to the resident load would silently produce a resident run with
   `tile_source` still true -> what happens in the tile loop (the loader called again on an mzML
   path?) Is that path reachable for a `.d`?
7. Performance: pass 1 opens the tdf and iterates the MS2 mapping only to export the table; each
   tile re-opens the tdf (sqlite Frames 72k rows, DiaFrameMsMsInfo 134k rows, T1, windows) --
   estimate; the loader's parallel batch loop runs OUTSIDE the window loop's parallel region
   (the tile loop calls readTile before `#pragma omp parallel`) -- any nested-parallelism hazard?
   LOAD(tile) phases sum vs the one-tile LOAD.
8. The judged plan's items not done here: chained `slabDigest_` per (window, tile); the
   `[det]` per-tile digests; the prefetch (step 5). Anything that must be in THIS commit for the
   gate to be meaningful?

Report: numbered findings with severity, file:line, a concrete failure scenario, the fix; then the
attack lines found sound.
