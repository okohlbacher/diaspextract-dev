# Deep review: SpeXtractor's memory and time in a STREAMING setting

You are reviewing a working, measured C++ tool, not a design. Your job is to find the improvements
that are still on the table, in three specific directions, and to say what each is worth and what
it would cost. Read the code AND the measurements; a proposal that the measurements already refute
is worse than no proposal.

## What the tool is

SpeXtractor (`src/spextractor.cpp`, one translation unit, ~5,300 lines, plus `src/TdfLoad.h`,
`src/MzPeakStreamLoad.h`, `src/TdfMzCalibration.h` and four OpenMS patches under `patches/`) turns
a diaPASEF acquisition into pseudo-MS/MS spectra a database search engine can read. It is a TOPP
tool: it links OpenMS, and the OpenMS pieces it needed changed live as patches against a pinned
commit.

The physical shape of the problem, measured on the two benchmark acquisitions:

* Dataset **D**: 30 minutes, 24 isolation windows, 32,210 MS2 window frames (1,342 per window),
  **1.258e9 picked MS2 peaks** (measured by the tile reader, 2026-09-10), ~612k emitted spectra.
* Dataset **TNBC 009** (PXD047793 run 009): 2 hours, 28 windows, 134,312 MS2 window frames
  (4,797 per window), 4.319e9 raw MS2 peaks (picked ~0.8x), ~3.29 M emitted spectra.
* One isolation window is an m/z slice sampled once per 1.626 s cycle for the whole gradient. A
  chromatographic feature is ~4 s wide; `trace:max_span_sec` trims traces at 120 s.

## The architecture as it stands today (all of it measured, all of it gated)

1. **Load.** The Bruker `.d` is read frame by frame through a patched OpenMS streaming loader.
   Each frame is decoded once, sliced into its window group's isolation windows, peak-picked in
   parallel batches of 256 frames, and compacted into a per-window `PeakSlab`: flight-time bin
   (`uint32`), intensity (`float`), quantised 1/K0 (`uint16`) per peak, plus a per-frame table.
2. **The cell grid.** Mass-trace detection runs per fixed 600 s retention-time CELL, cut at the
   run's MS1 frame times, in every mode. This is what makes the output invariant under any
   grouping of cells into tiles and any thread count -- proven by digest on real data.
3. **Frozen frame tables.** Every window's frame table (times, vendor ids, RT-axis indices,
   per-frame calibration factors, and the MS1-frame -> window-frame map the correlation uses) is a
   run-level constant taken from the reader's metadata, not from whatever frames are resident.
   Frames the reader skips are padded as empty frames so the resident sequence IS the table.
4. **The tile loop.** `tile:cells_per_tile` groups cells into tiles. Each tile: read its frames,
   trace/split/score its windows, emit the spectra of the precursors it owns (an MS1 frame time in
   [T_k - delta_rt, T_{k+1} - delta_rt)), carry the boundary fragments within 2*delta_rt to the
   next tile, sort the tile's spectra, write them as one block through a streaming mzML writer.
5. **The streaming source (new).** Pass 1 reads MS1 only; pass 2 calls the loader once per tile
   over a retention-time range. The band partition comes from the acquisition's metadata so a
   reader that holds only a tile's frames can compute it.

Everything above is output-identical for any tiling: dataset D at pitch 300 as 1/2/3/6 tiles at 8
and 100 threads, TNBC at 600 as 1 and 13 tiles, all reproduce the same spectra byte for byte.

## What you are asked to find

**1. More compact data structures.** The tool has already been through one compaction pass (a
40-byte `Trace` with the retention time as a frame index and the profile as a span into a shared
arena; int16 bin deltas; a 10 B/peak slab). Where is the next factor? Name the structure, the
representation, the exact bytes saved on the two acquisitions, and what it costs in CPU or in
correctness. A representation change that alters the output is not automatically disqualified --
say so and it will be gated -- but say it.

**2. Caching behaviour.** The window loop is 65-85% of the wall and is memory-bound, not
compute-bound: an earlier structure-of-arrays change to the scoring gate alone took a 2-hour run
from 12:53 to 7:04 with identical output, and a candidate-scan reorder that touched fewer bytes
was 10% SLOWER because it broke three sequential prefetch streams. Where are the remaining
misses? Consider the detector's per-frame scan, the flight-time index, the arena walks in
scoring, the sort keys, and the write path. Concrete, please: which access pattern, which array,
what layout instead, and what you expect it to be worth.

**3. Data lifetime in a streaming setting.** This is the one the measurements were made for. For
every structure: is it live longer than it is needed, does it have to be resident at all, could it
be recomputed instead of held, could it be per tile instead of per run, and does the memory it
frees actually leave the process? The ledger data below gives live bytes per structure at 250 ms
resolution alongside RSS, so "freed but retained" is visible as the unattributed column.

Also fair game, if the data supports it: the pass-1 MS1 phase (still whole-run and now the process
peak), the cost of re-opening the `.d` per tile, the prefetch that is not implemented yet, the
allocator (glibc, `malloc_trim` at phase boundaries; tcmalloc measured -7% peak once), and the
thread/task structure (an OpenMP task pool over windows x bands with a documented libgomp
grainsize cliff at 64 x nthreads tasks).

## What has already been tried, so you do not propose it again

Measured and REJECTED for performance (docs/PERF-ATTEMPT-1-REVERTED.md, docs/BASELINE.md and the
CHANGELOG carry the numbers):

* Reordering the detector's candidate scan to test the narrow array first: **10% slower** -- it
  broke three sequential prefetch streams. Fewer bytes touched is not fewer cache lines.
* Parallelising the MS1 trace conversion, twice: 17% slower (22 M small allocations), then
  no better with a flat pre-sized buffer and no allocation at all.
* Longest-first band dispatch: no effect (~300 tasks over 100 threads is a deep enough pool).
* `sdRobust` in log/exp form: +0.9%, i.e. nothing.
* Forcing every >= 64 kB block to mmap (`MALLOC_MMAP_THRESHOLD_`): -15.5 GB peak but **+26% wall**
  (the loop re-faults the returned pages cold).
* Removing the splitter's smoothing entirely: **slower** (+18% wall) and 31% MORE spectra --
  unsmoothed noise manufactures spurious valleys, so traces over-split.
* A per-window `max_concurrent_windows` cap as the memory lever: it is the measured knob at
  2.60 s of wall per GB of peak, which is exactly what the tiling has to beat.

Landed and worth knowing (all byte-identical unless stated):

* The scoring gate went structure-of-arrays: a 2-hour run 12:53 -> 7:04, output identical.
* The Savitzky-Golay coefficients are cached in the OpenMS patch: MS1 tracing CPU -40%.
* mzML spectra are encoded in parallel by a streaming writer: WRITE 90 s -> 21 s -> 13.2 s.
* The canonical sort sorts 32-byte keys, not 750-byte spectra: SORT -61%.
* One `malloc_trim` when the last window materialises: peak 169 -> 138 GB on the 2-hour file.
* The `Trace` record is 40 bytes and static_asserted; the profile is a span into a shared arena;
  per-point flight-time bins are int16 deltas from the trace's own bin.

## Ground rules

* **Say what is measured and what is inferred.** Every claim in this brief is measured; hold
  yourself to the same line.
* The output is pinned by digest on both acquisitions. Any change is classed D (output-identical,
  gated by digest) or S (output-changing, gated by Sage + MSFragger peptides and an entrapment
  FDR on both acquisitions). Say which class your proposal is.
* Quantify against the measurements below, not against a model. If a number you need is not
  there, say which measurement would settle it.
* Rank what you find. A ranked list of five real improvements beats twenty speculative ones.

## The measurements

See `data.md` next to this brief: the per-structure ledger (live bytes at 250 ms with the phase
markers), the phase breakdown, the per-tile read/loop/write picture, and the historical
before/after table. `docs/BASELINE.md` has the full measurement history; the last four sections
cover the cell grid, the frozen tables, the tile loop and the band partition.
