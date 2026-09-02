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
