Step 3b needs changes. The loader’s frame selection looks sound; the main problems are source fallback, missing padding, and gaps in the gate. P1 = high, P2 = medium, P3 = low.

1. **P1 — A resident fallback leaves the streaming source enabled.** [src/spextractor.cpp:3393](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3393), `:3485`, `:3636`, `:4502`.  
   `tile_source` becomes true for every non-mzPeak input and survives a failed streaming attempt. For a supported mzML invocation with `-trace:detector openms`, `loadExperiment` succeeds, but `frozen` is built from empty `run_tables`; the tile loop then calls the Bruker loader on the mzML again and fails. **Fix:** select the streaming source only for Bruker input, commit that selection after successful pass 1, and reset source state and partial data before resident fallback. A recoverable `.d` failure has the same state problem; I found no ordinary pinned-file trigger.

2. **P2 — Zero delivered spectra incorrectly means zero table frames.** [src/spextractor.cpp:4508](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4508), `:1764`.  
   Suppose a window delivers elsewhere, but every IM slice in this tile is empty. Its frozen slice contains frames, yet `finish()` never creates its slab. The absent branch creates a zero-frame slab, skips the invariant, and reports zero pads. The resident slice contains those zero-peak padded frames. **Fix:** tail-pad absent slabs with nonempty table slices, then validate and count them normally. Reserve zero-frame slabs for empty slices. This breaks the frame/digest contract; I found no resulting integer-path spectrum difference in this case.

3. **P2 — Wholly absent windows can change automatic banding between sources.** [src/spextractor.cpp:3636](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3636), `:4155`.  
   Streaming counts every metadata window; resident mode counts only windows with delivered spectra. With `tile:rt_sec=-1`, `perf:trace_bands=0`, two threads, one live window and one wholly absent window, resident mode chooses two bands and streaming chooses one. Independent band `visited` sets make this output-sensitive. Fixed-band G0/G1 misses it. **Fix:** give both sources the same run-level window population, or reject this automatic-band configuration until aligned.

4. **P2 — The advertised source stamp is missing from mzML.** [src/spextractor.cpp:4447](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4447).  
   `spx:tile_source` is set after `setExperimentalSettings(out_exp)` copies settings at `:4444`. `TileWriter` writes its header from that copy. Both streaming and resident-control mzML files therefore omit the stamp, while spectrum-data comparisons still pass. **Fix:** set it with the other stamps before configuring the writer; assert its value in the gate.

5. **P2 — MS2 compaction losses now escape the warning.** [src/spextractor.cpp:4490](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4490), `:3612`.  
   The sole dropped-peak report runs before pass 2. Invalid m/z or IM encountered during tile reads increments shared `cstat` and drops peaks, but nothing subsequently reports those losses. **Fix:** report per-tile statistic deltas or accumulated statistics after the final read. Sharing and accumulating `cstat` itself is safe.

6. **P2 — The required reader-exactness digests are absent.** [src/spextractor.cpp:929](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:929), `:4604`, `:4731`.  
   Each slab digest restarts from the initial seed and covers the entire tile; its log identifies only m/z bounds. There is no chain or per-cell comparison. A changed peak discarded downstream can leave every output spectrum identical. **Fix:** add a seed argument, chain by full `WinKey`, and log tile/global-cell identifiers and final chains. Enable and compare them in the gate, which currently explicitly unsets `SPEXTRACTOR_DET`. These checks belong in **3b**.

7. **P2 — The named gate signals completion after failures.** [chain_step3b.sh:19](/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/step1b/chain_step3b.sh:19), `:24`, `:38`.  
   Extraction status is merely printed; comparison and e2e failures are swallowed by pipelines. The script unconditionally emits `STEP3B_DONE`, which the driver waits for. A failed extraction or differing spectrum digest can therefore complete the chain successfully. **Fix:** preserve and aggregate command statuses, assert required results, and emit a success marker only after every gate passes.

8. **P2 — The memory measurements cannot establish the pass-2 bound.** [chain_step3b.sh:19](/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/step1b/chain_step3b.sh:19).  
   Process maximum RSS plus post-read/post-write snapshots misses a detection spike: a tile could reach 40 GB while both endpoints stay below 30 GB and MS1 remains the process maximum at 80 GB. **Fix:** collect the planned 250 ms VmRSS sidecar with tile/phase markers and enforce the 30/82 GB limits and LOAD ratio ≤1.15 using interleaved same-node arms. Also fix line 22’s phase grep: emitted lines begin `[perf]`, so its current pattern misses LOAD summaries.

9. **P3 — Slab-mode refusal comes after expensive work.** [src/spextractor.cpp:4325](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4325).  
   `-trace:band_edges slab` under the default streaming source loads and processes the whole MS1 phase before rejecting a conflict already knowable from the options. **Fix:** validate the combination when selecting the source, before pass 1.

10. **P3 — Load-only profiling now measures different work.** [src/spextractor.cpp:3474](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3474).  
    `SPEXTRACTOR_LOAD_ONLY=1` returns after MS1-only pass 1; the resident control still measures the complete load. An A/B therefore compares different workloads. **Fix:** preserve complete-load profiling across both passes, or explicitly rename/document this as pass-1-only profiling.

11. **P3 — One `window_list` replacement was missed in logging.** [src/spextractor.cpp:4186](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4186).  
    Streaming logs zero trace units because the multiplication still uses the empty resident list. **Fix:** multiply `n_win * n_bands`.

The attack lines found sound:

- **Frame selection and boundaries:** table export precedes filtering; loader selection and table slicing use the same `frame.time` double and `[lo, hi)` predicate. MS2 timestamps need **not** differ from MS1 edges: equality consistently belongs to the right tile.
- **Batch composition:** selected order and per-frame decode, IM slicing, sorting and serial handoff remain unchanged. No composition dependency was found in the picker, thread-local ZSTD usage, or `SPEXTRACTOR_LOAD_BATCH`. `cents` merges MS1 diagnostic counters.
- **Pass 1:** `+inf/-inf` selects no MS2 frames; `flush_()` initializes tables before returning for an empty buffer. On windows represented by resident padded slabs, frozen RT/id vectors match; their sorted-unique union with MS1 gives the same RT axis. Wholly absent windows are the qualification in finding 3.
- **State and lifetimes:** `tc`, `ms1_none`, and the reference-captured tile remain alive through synchronous load/finish. Consumer scratch dies before window computation. OpenMP completion precedes destruction of `wl` and `tile_slabs`; no dangling-pointer use was found. Tables, MS1 scoring support, carry and writer state persist; allocator-retained RSS still requires measurement.
- **Empty slabs and resident branches:** `indexRt` and `toTof` safely accept zero frames. Empty-window computation reinstalls frozen support before carry/scoring. Resident per-tile slicing is unreachable under streaming; nonempty multi-cell tiles can still call `sliceFrames` internally.
- **mzPeak and reservations:** mzPeak remains resident and derives `frozen` from slabs despite nonempty `run_tables`. Using the window’s table count changes capacity, not contents.
- **Parallelism and cost:** tile loading occurs outside the window parallel region; tile-read failures are fatal. Reopens and full metadata/filter scans recur per tile. The plan’s 0.3–1 s/open estimate implies roughly 3.6–12 s for twelve additional opens at 13 tiles, before batch-tail overhead; this remains unmeasured here.
- **Deferred work:** prefetch correctly belongs to step 5. The explicit `fid==0` guard is missing, but normal `.d` IDs are nonzero and mismatched IDs fail table matching. The MS2-neighbor option remains a no-op. The resident override currently tests environment-variable **presence**, so `=0` also enables it.

This was a read-only review of `933bba5`. All 22 calibration-patch hunks match the local OpenMS preimage. I did not execute the cluster pins or verify an 18/18 result.
