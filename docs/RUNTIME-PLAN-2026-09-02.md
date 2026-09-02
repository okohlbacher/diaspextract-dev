# Runtime + memory plan (2026-09-02) — measured, not guessed

## The profile that replaces every hypothesis
Per-phase timers added 2026-09-02 (`[perf]` table; CPU from getrusage so the parallel factor is
real). S30, release binary, 100 threads, 128-core/995 GB node, warm page cache:

| phase | wall s | share | parallel | note |
|---|---|---|---|---|
| LOAD (streaming .d) | ~1,046 | 53% | **1.0x** | serial: zstd + TOF->m/z + scan->IM + MSSpectrum build, on one thread |
| WINDOW_LOOP | 769 | 39% | **63x** | already well parallelised |
| MS1_TRACE | 83 | 4% | 5.0x | |
| PRECURSOR_INFER | 63 | 3% | 1.0x | serial, small |
| SORT + ASSEMBLE + WRITE | 24 | 1.2% | 1.0x | **not** a lever |

Every prior guess about "the unattributed 53%" (canonical sort, consolidation, the 9.3 GB mzML write)
totals 1.2%. The whole runtime problem is one serial phase, and the 27x whole-run parallel factor
is that phase dragging a 63x loop down. NOTE: the clock epoch was set on first call, which on the
streaming path is the "load done" line -- so the load was invisible to all earlier `[t=..]`
markers. Fixed (epoch anchored at main_).

## Root causes in the loader (verified in source, file:line in the archaeology reports)
1. **Every MS2 frame is decoded once per isolation window of its group** (window-outside-frame loop,
   BrukerTimsFile.cpp:1589-1610; `save_to_buffs` does not cache, it `close()`s). S30: 2 windows per
   group -> **2.0x re-decode of the entire 6.2 GB run**, from SQL: 16,105 physical frames, 32,210 decodes.
2. **The loop is strictly serial** (`for (fid..) consumer.consumeSpectrum(spec)`), and our consumer
   peak-picks + compacts 1.26e9 peaks inline on that thread.
3. I/O is NOT the cost: tdf_bin is 6.18 GB, contiguous append-only (0 out-of-order TimsId pairs of
   17,448), mmap'ed -- ~3 s sequential on NVMe. It is CPU work: zstd, per-peak conversions, allocation.
4. opentims documents the thread-safe decode recipe (per-thread ZSTD_DCtx + buffer: decompress(buf,ctx)
   -> save_to_buffs(..,ctx) -> close()) and uses it itself (opentims.cpp:599-634). No lock, no upstream change.

## Measures, ranked by (win) / (risk x effort). Status as of writing.
| # | measure | expected | byte-identical? | status |
|---|---|---|---|---|
| 1 | **Parallel batched pick+compact in our consumer** (64-frame batches, ordered append) | load 1,046 -> 637 s; total 33:05 -> **25:28 (-23%)** | intensities differ at 1e-5..1e-4 rel. (chaotic amplification of last-ulp), m/z identical, **Sage 12,200 = identical peptide count**; self-determinism run pending | **DONE, measured** |
| 2 | **Decode-once, frame-major, parallel decode in the loader** (per-thread ZSTD_DCtx; batch via SPEXTRACT_LOAD_BATCH) | removes the 2x re-decode AND parallelises the remaining ~637 s serial path; predicted load -> **~50-100 s** | expected identical to #1's output (per-window frame order preserved) | **built; sweep 64/256/1024 running** |
| 3 | Cull traces with < min_correlation_points support before EPD/grid (codex #2; "R2") | 8-18% wall, 15-35 GB RSS | yes | next |
| 4 | Link tcmalloc/jemalloc in CMake (kimi: July LD_PRELOAD A/B measured -18.4% RSS, -10.7% wall); free A/B `MALLOC_ARENA_MAX=4` first | -20..-60 GB RSS | yes | queued (needs quiet node) |
| 5 | Band construction: two lower_bounds instead of O(bands x peaks) scan ("R3") | 3-8% wall | yes | next |
| 6 | Fixed-bands concurrency cap sweep (n_conc 8/4/2 with trace_bands=12 held) | 25-40 GB RSS, 0-15% wall cost | yes | queued; the old "more windows is slower" sweep was CONFOUNDED (it also changed bands 12->4) |
| 7 | MS1 loop (1,343 frames) same treatment as #2 | ~small (4% of frames) | yes | after #2 |
| 8 | Cross-window task graph ("R5") | 15-30% of what remains | no | only after 1-6; its 2x claim ignored load |
| - | Parallel/compressed mzML write | write is 22 s | - | **dropped** (kimi's #1, refuted by measurement) |
| - | Naive dynamic thread apportionment, spectrum merging/collapse | - | - | falsified earlier; do not re-propose |

Ring buffer / producer thread (the question asked): with #2 the design is batch-synchronous
(decode a batch in parallel, hand off in order, pick in parallel). Decode-agent sizing formula:
N ~ k*(2B + D*t_p/t_d), k in [1.5,2]; with decode parallel, decode is the bottleneck, so a depth
of 2-3 batches suffices and extra depth is wasted RAM -- spend threads on decoders, not on depth.
Memory per buffered frame ~1.5 MB (37k peaks), so 256 frames ~ 400 MB, negligible vs the 12 GB
compact store. The batch sweep measures this instead of trusting the formula. A separate reader
PROCESS is unnecessary: mmap + per-thread contexts give the same overlap in-process.

## Memory (120 GB peak, measured inside the window loop)
Peak RSS is a temporal high-water mark inside WINDOW_LOOP (RSS 27 GB after load, 87 GB at loop
end, 124 GB peak). July measured ~87% of a similar peak as glibc arena retention (tcmalloc -18.4%).
Live data: 12 GB compact store + per-window working sets + ~10 GB of buffered output spectra.
Order of attack: #4 (free), #3 (cuts working sets), #6 (caps concurrency), then streaming the
output instead of buffering 924k spectra.

## Pre-registered predictions for the decode-once loader sweep (recorded before the numbers)
Kimi's first-principles decomposition (plan review, 2026-09-02): post-#1 load 637 s = ~619 s serial
decode+build + ~18 s pick wall; decode-once removes ~75-135 core-s; what remains (~485-545 core-s
decode/slice/build + ~430 core-s pick) is fully parallel -> at 35-70% efficiency on 100 threads
**LOAD wall 15-30 s (central ~20-25 s), whole run ~16 min.** My own number in the table above was
50-100 s, which -- as kimi points out -- silently assumes ~10-15% parallel efficiency. Reading key:
<12 s suspect the timers; 15-30 s kimi confirmed; 50-100 s = contention (allocator / NUMA first-touch),
not "confirmed"; >150 s or parallel factor ~1.0 = the pragma did not take. Batch 64/256/1024 should be
within +-20% of each other; a large win for 1024 means per-batch overhead nobody has seen in the code.
Sweep is gated to start only after the concurrent MSFragger run has exited (it was not, initially).

## Plan review verdicts (kimi + codex, 2026-09-02) and what changed
**Bugs found and fixed (before the sweep binary is built):**
- **Chunking capped the parallelism** (codex #6/#7). `schedule(dynamic, 8)` over a 64-frame batch =
  8 chunks = 8 workers; the "parallel" pick ran 8-way, so 1046 -> 637 s is the 8-way number, not the
  100-way one (implied serial pick ~467 s, residual ~58 s). The loader's `(dynamic, 4)` over 256
  frames capped the decoder at 64 workers (16 at batch 64). Both are now chunk 1, pick batch 256
  (`SPEXTRACT_PICK_BATCH`), and the running sweep will build this binary first.
- **Exceptions in both OMP regions** (codex #11) would have aborted the process; both loops now
  capture and rethrow serially like the full-load path.
- **Vendor-SDK converter thread-safety is unvouched** (codex #9, kimi): the loader runs serially
  when the SDK converter is active unless `SPEXTRACT_SDK_PARALLEL` is set. The TDF-table converter
  is read-only after construction. Cluster runs use the table (provenance `tdf_table_modeltype1`).
- **Sweep timing gated** on the concurrent MSFragger job exiting (it was not).

**Acceptance criterion, replacing "Sage count identical":** (a) two fixed-config runs digest-identical
(`bench/semantic_digest.py`, pickdet running); (b) baseline vs optimized: same spectrum count, keys,
RT, precursors, quantized m/z/IM, and a pre-registered intensity envelope with the cause explained;
(c) both engines: accepted-peptide SET overlap, not count. **Measured for (c) now:** the v0.2.0
serial-pick S30 run (`final_t100`, 12,200) and the batched-pick run (12,200) accept **exactly the same
12,200 peptides (symmetric difference 0)**. For calibration, the same-code run at another thread count
(`tbl_s30`, 11,976) differs from it by 2,730 peptides (20% of the union) -- the cross-config chaos is
a 20% membership churn at a 2% count level, so count equality alone is indeed a weak test and set
equality is a strong one. The 1e-5..1e-4 intensity differences are tens-to-hundreds of float ULPs
(codex #2), cause not yet shown; `SPEXTRACT_PICK_SERIAL=1` on the new build is the direct A/B.

**Pre-registered load predictions for the sweep:** kimi 15-30 s (fully parallel, 35-70% efficiency);
codex 105 / 75 / 70 s for batch 64 / 256 / 1024 -- with the OLD chunking; with chunk 1 codex's
worker cap no longer applies, so codex's numbers become an upper bound. Mine (50-100 s) is withdrawn.

**Re-ranked measures (after the sweep lands; wall and RSS ranked separately, codex #15/kimi):**
1. determinism gate (#1, #2) -> 2. allocator env A/B `MALLOC_ARENA_MAX=4` (free, byte-identical to
verify) -> 3. exact `lower_bound` band endpoints (#5; codex #13: same half-open interval, provable)
-> 4. WINDOW_LOOP parallel efficiency 63x -> ?, PRECURSOR_INFER (63 s serial) and MS1_TRACE (83 s
at 5x) -- three rows the plan lacked (kimi) -> 5. short-trace skip ONLY at the dot-product-only
location (#3 demoted: pre-EPD/grid cull is behaviour-changing, codex #12) -> 6. tcmalloc/jemalloc
as separate A/Bs -> 7. concurrency cap for RSS (#6; no memory target stated yet: 124 GB on a 995 GB
node) -> 8. output streaming, cross-window task graph (#8) re-estimated against the post-sweep
profile (codex #20: reprofile decode/convert/slice/sort/pick/compact before assigning percentages).
**Loose ends kept:** 33:05 - 409 s = 26:16, not 25:28 -- 48 s moved elsewhere, per-phase tables to be
compared (both reviewers); the memory section's 400 MB/batch undercounts (codex #18): the sweep's
RSS column is the measurement; the "ring buffer" prose over-sold a pipeline that is batch-synchronous
(codex #19) -- with decode and pick both parallel there is no producer/consumer overlap to size, only
the per-batch barrier, which chunk 1 minimises.
