# DIAspeXtract on TNBC (PXD047793): runtime and memory by phase and data structure

Sixteen 130-min diaPASEF runs, the defaults of the build stated below, `-threads 100`, medians unless
noted. Sources: the
tool's own `[perf]` phase table and RSS milestones in every `extract.log`, `/usr/bin/time -v`, the
code (`src/spextractor.cpp`), and a three-agent reconciliation (two independent analyses, one refuter)
whose accounting closes each RSS milestone within ~10%. Basis is marked: **measured** (in a log),
**predicted** (from a struct + a logged count), **inferred** (from a fit to the milestones).

Build: the 30.3 min / 264 GB profile below (the runtime and memory sections) is the TNBC-table build
of 2026-09-06 (docs/TNBC-TABLE.md, committed 0f5440d at 07:13; before the memory work:
`charge:min_charge=2`, 72-byte trace record, no trim). The 'Measured, not inferred' section is v13
(the step-2 instrumentation); the CORRECTION section is the same v13 run read over all 28 windows; the
allocator experiment is v16 + `malloc_trim`. Superseded for the shipped build: v35 and v38 phase
tables are at BASELINE.md:1745-1752 and 1911-1917 (11:36 -> 12:42 wall, 188-191 GB peak).

Per run: 139,311 frames (4,804 MS1), 28 isolation windows, 4.27e9 picked MS2 peaks, 21.4 M MS1
traces, 8.7 M isotope seeds -> 3.0 M precursor hypotheses, 2.30 M pseudo-spectra, 19-20 GB mzML.

## Runtime: 30.3 min wall, 10.3 h CPU, 34 cores busy on average

| phase | wall s | % | CPU s | parallel | what the time is |
|---|---|---|---|---|---|
| LOAD(stream) | 75 | 4 | 5,581 | 77x | parallel peak picking (pick 42 of 61 s); serial reader hand-off |
| MS1_TRACE | 250 | 14 | 1,207 | 4.8x | 35-45% single-threaded: the band-partition copy of the whole picked MS1 map (40-70 s), toTrace/makeSpan over 21.4 M traces (30-45 s); 12-band MassTraceDetection at 6-9x (bands are peak-count quantiles, not apex-cost quantiles) |
| unattributed | 29 | 2 | 29 | 1.0x | serial FWHM pass + serial canonical sort of 21.4 M traces |
| PRECURSOR_INFER | 450 | 25 | 450 | **1.0x** | single-threaded greedy isotope walk: 8.7 M seeds x <=5 charges x <=10 partner searches, each two binary searches plus a linear scan of ~400 contiguous 72-B trace records; serial because `used[]` marking makes seed order a dependency; ~quadratic in trace count (31-63 s on the in-house files, 364-518 s here) |
| WINDOW_LOOP | 978 | 54 | 34,463 | 37x | CPU-bound tracing (78% of stage time) and scoring (19%); occupancy 35-43 of 100 threads because every window has single-threaded sections (the seed sort of 145-215 M elements through an indirect comparator, absorb, the 30-50 M-record fragment-trace sort) and the tof bands are uniform-width, not balanced. All 28 windows are admitted in the first ~90 s; the mean number active is 9.4, i.e. the last ~500-600 s run at ~10 threads |
| SORT + ASSEMBLE | 8 | 0 | 8 | 1.0x | sort of 2.3 M spectra, move into the PeakMap |
| WRITE(mzML) | 53 | 3 | 52 | 1.0x | single-threaded XML/base64 at ~400 MiB/s for 19-20 GB |

Kernel time is 1.8-2.9% of CPU-seconds (1,150 s of 62,900) and is NOT a wall lever: the on-record
tcmalloc A/B on the in-house file (d8_R3 vs d9_libtcmalloc_minimal) cut minor faults 137 M -> 48 M
and system time 616 -> 320 s for +1% wall. (An earlier note in the session compared system
CPU-seconds with wall-clock and called it 64%; that comparison is invalid for a 100-thread process.)
Host matters: ibminode05 (64 cores / 128 threads) runs the loop in 1,123-1,264 s, the 224-thread
nodes in 805-1,085 s.

## Memory: 264 GB peak (range 204-287), of which ~43 GB is live data at the loop start

| component | GB | basis | lifetime |
|---|---|---|---|
| Compact MS2 store `map<WinKey, vector<CompactFrame>>` (uint32 mzq + float inten + uint16 imq = 10 B/peak x 4.27e9) | 39.8 | measured | load -> window admission; consumed frame by frame by `toSlab`, chunks go back to per-thread arenas, not the OS |
| `ms1_map` picked MS1 PeakMap (Peak1D 16 B + IM float 4 B = 20 B/peak; N_ms1 ~1.4-2.1e9, **not logged**) | 28-41 | inferred | load -> start of MS1_TRACE (destroyed at the band partition) |
| LOAD-phase allocator retention (freed frame chunks below the mmap threshold, held in ~100 worker arenas) | ~15 | inferred | never trimmed |
| MS1 traces `vector<Trace>` (72 B x 21.4 M) | 1.4 | predicted | to the end |
| MS1 XIC arena (4 B x ~12 spanned frames x 21.4 M; compacted to the 25% a precursor references) | 1.1 | predicted | to the end |
| Serial band-partition COPY of the MS1 map (20 B x N_ms1), allocated in the main arena while the just-freed spectra sit in the worker arenas -> every byte new | 28-41 | inferred | MS1_TRACE only, then retained |
| MassTraceDetection work copies, apex lists, MassTrace parents + EPD children | ~16 | inferred | MS1_TRACE only, then retained |
| Precursor hypotheses (64 B x 8.7 M touched, 3.0 M kept) | 0.5 | predicted | to the end |
| Loop in flight: 28 PeakSlabs (10 B/peak, fresh mmaps replacing the compact chunks) | 39.8 | predicted | one window each |
| Loop in flight: 28 seed-order arrays (4 B x 0.95 x peaks) | 15 | predicted | one window each |
| Loop in flight: per-window band trace vectors/arenas, absorb targets, split parents + children, scoring set (~35-50 M fragment traces per window, **not logged**) | ~67 | inferred | one window each |
| Emitted spectra in `win_out` (2.30 M x ~7.5 KB: 752-B object + 208-B precursor + 8-KB peak array at the 500-peak cap without reserve) | 16 | inferred | loop -> write; lands in recycled arena holes, invisible in RSS |
| ASSEMBLE: out PeakMap, touched slots only | 1.7 | measured | write |

How the milestones add up: after load 90 = 39.8 + 28-41 + ~15 (+1 baseline); after MS1 142 = the
same pages plus the 52 GB partition copy and transients, of which only ~43 GB is live; loop peak
264 = 142 + 122 in flight (all 28 windows concurrent: 39.8 + 15 + ~67); loop end 139 (12 runs) or
~105 (4 runs where glibc happened to return whole heaps). The figure "2,598 B per MS1 trace" that
the milestone arithmetic suggests is a mis-normalisation: the term is 20 B per picked MS1 PEAK
(the map copy), not per trace.

## What this says

1. **Half the wall is the window loop at a third of the machine.** The loop is not memory- or
   kernel-bound; it is serial sections inside each window plus band imbalance, leaving a long tail
   at ~10 threads.
2. **A quarter is a single-threaded phase whose cost grows ~quadratically with trace count.**
   PRECURSOR_INFER is 31-63 s on 30-min in-house files and 364-518 s here; at 2.5x the traces it
   is 8x the time.
3. **The peak RSS is ~2.5x the live data.** Of 264 GB, ~43 GB is live at the loop start, ~100 GB
   is freed-but-retained (glibc never trims per-thread arenas; the map copy cannot reuse memory
   freed by other threads), and ~120 GB is 28 windows in flight. RAM, not CPU, sets concurrency;
   the admission gate over-books each window ~2x at its momentary peak.
4. **On the 2020 HeLa and in-house files none of this shows** (5 min, 80 GB): the serial phases
   are small there. It is the 2-h, 4e9-peak class where DIAspeXtract is 1.4-2.3x slower than the
   reference extractor, and the three items above are the whole explanation.

## Levers, ranked by expected wall gain on this file class (all inference until run)

1. **PRECURSOR_INFER on a structure-of-arrays gate** (float rt, float im in m/z order: 8 B per
   candidate instead of the 72-B record; same candidate order, same first match -> output
   identical): the scan is ~75% of the 450 s -> **-200..-300 s (-11..-17%)**. One run settles it.
2. **Window-loop critical path**: per-band seed order lists (12 parallel sorts of ~12 M instead of
   one serial sort of 145-215 M) and a parallel fragment-trace sort (output-identical); seed-count-
   balanced tof band edges (changes double-claims at band edges, ~0.1% of peptides, needs the set
   gate): **-150..-300 s (-8..-16%)** IF the tail is what the stage-elapsed arithmetic implies.
   First add per-window stage timestamps to the `window k/28` lines to measure that tail.
3. **MS1_TRACE**: partition the map into bands in parallel on the worker threads (so the copies
   land in the arenas that hold the freed spectra) and convert to spans per band: -60..-100 s
   (-3..-5%), output-identical, and removes 25-40 GB of the +52 GB step.
4. **WRITE**: mzPeak or a parallel mzML encoder: -40..-50 s (-2.5%), measured.
5. **Allocator / hugepages / NUMA / thread count** (tcmalloc preload, `glibc.malloc.hugetlb=1`,
   `-threads 64` on the 128-thread node): bounded by the 2-3% kernel share; adopt tcmalloc for the
   -7% RSS headroom, not for wall.
6. Not a wall lever: `perf:max_concurrent_windows` and the admission projection only cap RAM.

Two log lines would remove the two inferred quantities: the picked-MS1 peak count at "Split into",
and the fragment-trace count per window. Both are one `String(...)` each.

## Measured, not inferred (2026-09-06): the instrumentation the profile lacked

Two quantities this document could only bound, and one mechanism it could only assert, are now log
lines (`[mem]`, `mallinfo2` at every milestone, per-window stage times). First numbers, from the
30-min in-house file (dataset D; the TNBC file is 2-3x larger on every count):

| quantity | measured |
|---|---|
| picked MS1 peaks | 725,116,915 in 1,343 frames = 13.8 GB as a PeakMap (20 B/peak) |
| compact MS2 store | 11,975 MB for 1,255,770,798 peaks (10.0 B/peak) |
| band-arena merge, per window | 12 band arenas, ~330 MB held **twice** while absorbed, ~6 M traces |
| allocator after load | arena 31.4 GB, mmapped 8 MB, **free-but-retained 4.0 GB** |
| allocator after MS1 tracing | arena 47.3 GB, mmapped 345 MB, **free-but-retained 33.4 GB** of a 48.5 GB RSS |

The last row is the retention mechanism as a measurement: at the MS1 -> window-loop boundary about
two thirds of the resident set is memory the allocator holds free. It is the same pool the ownership
steps stop creating; it is also what a `malloc_trim(0)` at that boundary would return, which makes
the declined allocator-hygiene lever a measured 33 GB on this file rather than an assumption.

## CORRECTION (2026-09-06): the per-window numbers, from all 28 windows

An earlier reading of this file's first two `[mem]` lines concluded that the per-window structures
were about four times smaller than the plan assumed. **That was wrong.** The `[mem]` line prints in
trace-completion order while admission is heavy-first, so the first two lines are the two SMALLEST
windows: together 51,343,214 peaks, **1.19% of the run**, not 2/28 = 7.1%. The windows span
11.9x (min 21.1 M peaks, median 161.8 M, max 251.1 M) because the isolation tiles are 19-141 Da wide.

All 28 lines, scaled per peak (4,318,987,366 MS2 peaks):

| quantity | measured |
|---|---|
| parent fragment traces | 925,021,637 = 0.2142 per peak |
| child traces after the valley split | 1,217,100,843 = 0.2818 per peak |
| trace records at 72 B, if all were simultaneous | parents 62.0 GiB + children 81.6 GiB = **143.6 GiB** |
| span arena, one copy | 5,035,898,026 floats = 18.8 GiB |
| RSS observed at the window lines | 159-263 GiB (VmHWM 268) |

So the trace records are the **largest addressable structure in the tool**, larger than the compact
store (40.2 GiB) and the picked MS1 map (44.5 GiB). Shrinking the record from 72 to 56 bytes is
therefore worth roughly 16-24 GiB at the peak rather than the ~4 GiB the two-window reading implied,
and it is the cheapest change on the list.

The lesson is a measurement lesson: a per-window log line is not a sample of the run unless the
windows are equal, and these are not. Scale by peaks, never by window count.

## The allocator experiment (2026-09-06): one line returns 75 GB of the peak

`malloc_trim(0)` at the two phase boundaries, behind `SPEXTRACTOR_MALLOC_TRIM`, on TNBC run 009.
Output digest **identical**. The wall figure first quoted here (30:27 against 31:16, one unpaired run
on a shared node) was retracted the same day: the interleaved A/B measured the trim at **+8.5% wall
(+2:37)** for -30.7% peak, minor faults +26%, window-loop CPU +15% (BASELINE.md:1383-1409,
'CORRECTION (2026-09-06, 19:55): the trim is NOT free').

| boundary | RSS before | RSS after | returned | cost |
|---|---|---|---|---|
| MS1 tracing -> window loop | 138,360 MB | 45,931 MB | **92.4 GB** | 7.8 s |
| window loop -> write | 85,602 MB | 20,088 MB | **65.5 GB** | 4.9 s |

**Peak RSS 281.5 GB -> 206.7 GB, a 74.9 GB (26.6%) reduction, for two lines of code and 12.7 s of a
1,800 s run.** The mechanism is exactly what the milestones predicted: the loop's in-flight
allocations were stacking on top of a 138 GB floor of memory the allocator was holding free, and
returning that floor first means the same in-flight bytes peak 75 GB lower.

This is larger than every structural step on the plan combined, and it re-prices all of them: they
now act on a 207 GB peak, not a 281 GB one. It also confirms that the free-but-retained pool is
genuinely recoverable rather than stranded in fragmentation -- 92 of the 101 GB reported free at that
milestone came back.

What it does NOT do on its own is admit more windows: `availableBytes_()` adds the process's own RSS
back into its budget, so the admission gate sees roughly the same number either way. Pairing a trim
with a corrected admission budget is what would turn the freed memory into concurrency (fixed
2026-09-06, v19 -- BASELINE.md:1372-1376: `availableBytes_()` no longer adds RSS back,
`perf:max_concurrent_windows` is enforced, the per-peak projection is 44 B).
