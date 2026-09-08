You are reviewing SpeXtractor, a C++20 OpenMS TOPP tool that extracts pseudo-DDA spectra from Bruker timsTOF diaPASEF data. It was released as v2.0.0 today. Your ONE job: find where MEMORY and RUNTIME can still be saved. Nothing else — not style, not naming, not tests.

Read `src/spextractor.cpp` (one translation unit, ~4,300 lines after today's cleanup) and `src/TdfLoad.h`, `src/MzPeakStreamLoad.h`.

## Where the tool actually spends, measured on a 2-hour acquisition (100 threads, 224-core node)

| phase | wall | % | CPU s | parallelism | RSS at end |
|---|---|---|---|---|---|
| LOAD (streaming .d) | 118 s | 13.7% | 8,613 | 73x | 47 GB |
| MS1_TRACE | 106 s | 12.3% | 1,190 | 11.2x | 60 GB |
| PRECURSOR_INFER | 27 s | 3.1% | 630 | 23x | 33 GB |
| WINDOW_LOOP | 553 s | 63.8% | 50,776 | 91.9x | 86 GB |
| SORT (canonical) | 9 s | 1.0% | 9 | **1.0x** | 40 GB |
| ASSEMBLE (PeakMap) | 5 s | 0.6% | 5 | **1.0x** | 45 GB |
| WRITE (mzML) | 52 s | 6.0% | 52 | **1.0x** | 45 GB |

Peak RSS 188 GB; 3.9 M spectra emitted; total wall 14:37 under load (12:42 uncontended).
A 30-minute acquisition: 3:17, 58 GB, 855 k spectra, window loop 78x.

## The structures that dominate memory (measured)

- The MS2 compact peak store: 10 B/peak, 4.27e9 picked MS2 peaks -> ~40 GB. Per window it is converted into a `PeakSlab` (a second copy of the window's share) and freed after the window.
- `Trace`: 48 B/record, ~2.1e9 records if simultaneous (~96 GB at 48 B). This is the largest single structure.
- Per-window band trace vectors, merged into one window arena (`absorb()` copies into a fresh arena, so the source and destination are both live at the merge).
- The picked MS1 PeakMap (~14 GB on a 30-min file, ~45 GB on a 2-hour one) plus its 48 band sub-maps.
- Emitted spectra: held as `MSSpectrum` in `all_out`, then copied into a `PeakMap` for the writer (`ASSEMBLE` above), then serialised. Three representations of the same 3.9 M spectra.

## Constraints you must respect

1. **Output is pinned.** Two digests are the acceptance gate (a 30-min and a 2-hour file). An optimisation is CHEAP to accept if it is provably byte-identical, and EXPENSIVE if it changes the spectrum list (that needs a full search-engine + entrapment-FDR gate on two datasets and two engines). Classify every proposal as OUTPUT-IDENTICAL or OUTPUT-CHANGING and say why.
2. Floating-point evaluation order is output. Reassociating a sum, changing an accumulation order, or vectorising a reduction changes the digest.
3. The window loop is bounded by a free-RAM admission gate: less memory per window means more windows in flight, so memory savings convert into speed.
4. glibc-only code must stay behind `#ifdef __GLIBC__`.

## What has already been tried — do NOT propose these again

- `perf:malloc_trim` at the phase boundaries: SHIPPED, -30% peak for +8.5% wall.
- Trace record 72 -> 56 -> 48 B (dropped a store pointer, a calibration factor, an apex-intensity copy): SHIPPED.
- Fragment RT gate reading a uint16 bucket array instead of a double: SHIPPED, 12:53 -> 7:17.
- Direct-address TOF-bin index in `best()`, and an IEEE-754 bit-pattern m/z index in `findPartner`: SHIPPED, window loop -19%.
- Ordered speculation to parallelise the greedy precursor claim loop: SHIPPED, 23x.
- Bounding the scoring taskloop's task count (libgomp inlines a taskloop past 64x nthreads tasks): SHIPPED.
- Band-parallel MS1 detection at 48 bands: SHIPPED.
- Ordered speculation inside the band trace detector: implemented, measured +31% CPU, REMOVED.
- Raising `perf:trace_bands` above 12: changes trace ownership at band edges, moves 4-10% of the peptide set, REJECTED.
- Larger loader pick batches (`kBatch` 256 -> 4096): -39% load wall but changes the digest and loses 7% of peptides, REJECTED.
- tcmalloc preload: -7% peak RSS, wall-neutral, not adopted in-tree.

## Designed but NOT implemented (a plan exists; judge each on merit, and say if the design is wrong)

- **Streaming mzML write**: build spectra as plain records and stream them through a writing consumer instead of materialising `all_out` -> `PeakMap` -> file. Would remove the SORT/ASSEMBLE/WRITE serial tail (66 s at 1.0x) and one or two full copies of 3.9 M spectra.
- **Chunked TOF slab as the store**: make the compact per-window store BE the slab, removing the per-window slab generation and its second copy.
- **Segmented arenas**: `{arena, off, len}` spans so band arenas are never concatenated, deleting `absorb()` and its duplicate-liveness peak.
- **One authoritative scoring set**: delete the copied `frag_im` array and the copied `FragRt::rt` field, slicing on the sorted arrays instead.
- **Per-band MS1 materialisation**: slice each frame into its band inside the band task rather than building 48 sub-maps up front.
- **Band-local `visited` bitsets** instead of one full-range bitset per band.
- **MS1 through the integer detector** (MS1 currently runs OpenMS `MassTraceDetection` on a materialised PeakMap of doubles; `Trace::tof` is 0 on that path, which also blocks the integer m/z key in precursor inference).

## What I want from you

A ranked list. For each proposal:
1. **What** to change, naming the exact functions/structures/lines.
2. **Why it wins**, quantified from the numbers above (GB saved, or seconds, or which serial phase it parallelises). Show the arithmetic.
3. **OUTPUT-IDENTICAL or OUTPUT-CHANGING**, with the reason.
4. **The risk** and what would falsify the idea.
5. **Effort**: lines touched, and whether it is a local change or a refactor.

Rank by (expected saving) / (risk x effort). Put anything you believe is a >5% wall or >10 GB win at the top. Be concrete and quantitative; a proposal I cannot cost is useless. If one of the designed-but-unimplemented items above is a bad idea, say so and why — that is as valuable as a new one.

Do not be deferential. If the biggest win is something the list above has not thought of, lead with that.
