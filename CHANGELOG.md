# Changelog

## [Unreleased]

### Performance (2026-09-08/09) -- all of it byte-identical

Four changes, verified on both benchmark files against the pinned digests, so the peptide sets are
unchanged by construction and no search was needed. Interleaved A/B on a 2-hour diaPASEF
acquisition, arms alternating on one node: **13:42.9 -> 11:17.6 mean wall, -17.7%**, peak memory
unchanged.

- **The Savitzky-Golay coefficients are cached (OpenMS patch).** `ElutionPeakDetection::smoothData()`
  constructed a filter and called `setParameters()` on every mass trace, and `updateMembers_()`
  recomputes the coefficients with one Eigen SVD per half-window each time. They depend only on
  (frame_length, polynomial_order) -- a handful of values in a run -- while smoothData() runs once
  per trace, hundreds of millions of times. A thread_local cache leaves the coefficients, the
  filtering loop and every float conversion untouched. **MS1 tracing CPU -40%, window loop -22.5%.**
- **mzML spectra are encoded in parallel and written in order (fourth OpenMS patch).** Writing was
  the largest serial block left, 10.7% of the run at 1.0x, and it is CPU-bound rather than
  I/O-bound: it sustained ~400 MB/s against a filesystem measured at 4.0 GB/s. Serialising one
  spectrum is independent of every other; only the concatenation is ordered. **WRITE 90.0 s ->
  21.1 s, 1.0x -> 49x.** Each thread needs its own handler and validator -- OpenMS's writer memoises
  CV-term validation in mutable state, and sharing one handler corrupts the heap.
- **The canonical sort sorts keys, not spectra**, and the assembled PeakMap takes the vector whole.
  `std::sort` moves what it is handed, and an `MSSpectrum` is ~750 bytes against 32 for a key.
  **SORT -61%; the ASSEMBLE phase is gone.**

### Performance (2026-09-09, second batch) -- byte-identical unless stated

- **The drained compact store is returned when the last window has materialised.** The window
  loop's peak held ~40 GB of dead per-frame vectors in the allocator's free list for its whole
  life; one `malloc_trim` at the moment the last window's slab exists returns it. Interleaved A/B
  on a 2-hour acquisition, two reps each: **peak RSS 169.1 -> 138.1 GB (-18%)**, wall within the
  pair spread, output identical.
- **The mzML is written by a streaming writer (`TileWriter`)**: header once, spectra appended in
  the canonical order in parallel-encoded chunks with the index offsets rebased as they land, the
  declared count exact when the total is known and a same-width placeholder otherwise. Bytes from
  `<spectrumList>` on are the bulk writer's; **WRITE 19.6 -> 13.2 s on the 30-minute file** (the
  per-thread encoders no longer share a handler). Emitted spectra now carry `id="spectrum=<rank>"`.
- **The loader builds each window's peak slab directly.** The per-window `CompactFrame` store and
  its copy at window start are gone; frames are appended as they are picked, m/z quanta become
  flight-time bins in place when the window starts, and the batch's windows are appended in
  parallel from one reusable scratch. Output and every per-window slab digest identical. Costs
  +12 s of LOAD on the 30-minute file today (first-touch page faults on fewer threads; on the
  backlog) and lifts the load-phase peak by ~3 GB there, below the window loop's peak on a
  2-hour file.
- **MS1 traces are ordered by content only** (m/z, RT, mobility, intensity, point count, span,
  first frame time); the number of equal-key neighbours is logged (0 on the benchmark file).

### Added (2026-09-09)
- **`tile:rt_sec` -- detection in fixed retention-time cells (default 600 s).** The integer detector traces each window per RT cell cut at the run's
  MS1 frame times, so the output is bit-identical however the cells are grouped into tiles and
  however many threads run (at a fixed `perf:trace_bands`); the cut lines are stamped into the
  header (`spx:tile_rt_sec`, `spx:tile_boundaries`). This is what makes a streaming, tiled run
  reproduce the whole run exactly -- the halo designs could not (docs/BASELINE.md, "cause 2 vs
  cause 3"). Mass traces that elute across a cut line are cut there: on the 2-hour file at 600 s,
  Sage 28,845 -> 29,066 (+0.8%) with 9.4% of the peptides within 15 s of a line lost against 6.0%
  elsewhere (the usual set churn); on the 30-minute file Sage +0.8%, MSFragger +1.5%, entrapment
  FDR 1.16 -> 1.30% (inside its interval); 300 s gives Sage +3.4% at 1.38% entrapment and is not
  the default. `-1` is one cell = the previous output, byte-identical; e2e check 15 holds the
  thread invariance at a pitch that cuts the fixture in two.

### Changed (2026-09-09)
- **The valley splitter's smoothing window comes from the acquisition's cycle time
  (`trace:split_scan_time=frame`, new default; `trace` restores the old behaviour).** OpenMS
  ElutionPeakDetection derives its Savitzky-Golay window from each mass trace's own average cycle
  time, and the tool hands it a trace's real points only, so a trace with gaps was smoothed with a
  narrower window than its neighbours and split more. With one run-wide window the traces are
  fewer and longer -- 37% fewer MS1 traces and 28% fewer spectra on the 30-minute file, 16% fewer
  spectra on the 2-hour file -- and identify MORE peptides: Sage 12,625 -> 13,388 (+6.0%) and
  27,859 -> 28,845 (+3.5%), MSFragger 12,236 -> 12,732 (+4.1%) on the 30-minute file, with the
  entrapment FDR at nominal 1% moving from 1.35% to 1.16% there (12,496 vs 11,722 target peptides
  against the entrapment database). Found
  while measuring RT tiling: the per-trace window made a trace's split depend on where the run was
  cut. The EPD patch gains an advanced `scan_time` parameter (0 = the OpenMS default).
- **mzPeak input runs the integer detector.** mzPeak native IDs now carry `frame=<Id>` and the
  flight-time axis is built from the archive's embedded (or sidecar) `analysis.tdf`; before, every
  mzPeak spectrum was unmappable and the tool fell back to the OpenMS detector with a warning. On
  the 30-minute archive: 855,561 spectra, Sage 12,537 (the `.d` gives 12,625; the OpenMS detector
  on the same archive 12,756). Archives converted without the vendor tdf need
  `SPEXTRACTOR_MZPEAK_TDF=<analysis.tdf.gz>`.
- **e2e check 14**: the declared spectrum count, `id="spectrum=K"`, `index="K"` and every
  `<indexList>` offset agree.

### Fixed
- **The streaming loader dropped the last `n mod 256` MS2 window spectra of every run.** The pick
  consumer's tail flush was overridden but never invoked (OpenMS reaches it only through
  `retrieveSwathMaps`, which the streaming path does not use). The `.d` reader hands frames over
  window-group by window-group, so the loss fell on the last group: on a 31-minute file the last
  105 cycles of two windows (210 of 32,210 spectra); on mzPeak input the last ~9 cycles of every
  window. The v2.0.0 note "`SPEXTRACTOR_PICK_BATCH` is fast and rejected -- the picker carries
  per-thread state" was this bug: at 4096 the dropped tail was two whole windows plus 427 frames of
  two more, 11% of the MS2 spectra. With the tail kept, batch 256 and 4096 produce the identical
  digest: the picker is per-frame pure and the batch size is a resource knob. Dataset D: +758
  spectra, Sage 12,609 -> 12,625 peptides. Output changes; digests re-pinned.
- **The parallel mzML writer emitted an empty `<indexList>`** (`count="0"`, one dummy entry) since
  it shipped in v2.0.0: the per-thread handlers' spectrum offsets were discarded on concatenation.
  Search engines do not read the index, so no result was affected; the file was not a valid
  indexedmzML. Offsets are now rebased as each chunk is appended; an independent validator checks
  every offset on the benchmark output (854,817 spectra).

### Changed
- **Twenty-four falsified options removed** (from 71 to 47; 21 fewer in the plain `--help`). Each
  either carried a falsification verdict in its own help text or had no measurement on record, and
  each defaulted to its no-op value, so output is unchanged: the `merge:` and `consolidate:` groups,
  the cross-precursor redistribution family (`rp_max`, `competitive`, `apportion`), the wavelet
  smoother and its selftest, post-centroiding frame aggregation, `open_search_safe` (a documented
  no-op), `rank_by`, `ambiguity_margin`, `max_trace_length_sec`, `dedup_precursors` and
  `split_valleys_fwhm`. `gate:variance_support`, `gate:coelution`, the two averagine-monoisotope
  flags and `charge:scoring=envelope` are deliberately kept: the record says to keep them.
- Four finished experiment knobs, a never-called accessor, an orphaned doc comment, a duplicate
  option read and a struct member with no reader are gone with them.

### Fixed
- The one-shot-load peak picker no longer runs, and no longer logs "Loaded 0 frames.", on the
  streaming default; the compact-store digest no longer hashes an empty map on the integer path.
- The eight benchmark plans had aborted on their first pre-flight since the identifier scrub gave
  the sample ids a space here and an underscore in the registry.
- CI syntax-checks every tracked Python file rather than an arbitrary fifth of them, and
  `apply_openms_patches.sh` checks the OpenMS pin it documents.

## v2.0.0 — 2026-09-08

**Why 2.0.** The interface breaks: the executable is `spextractor`, so every script that called
`spextract` has to change, and ini files written by 1.x carry the old tool-name section and must be
regenerated (`-write_ini`). Two more things make a migration deliberate: a third OpenMS patch
(`MassTrace` move operations) is mandatory and a tree without it does not build the tool, and the
output is not digest-comparable with 1.x -- the defaults changed (charge floor, mobility veto, MS1
bands, allocator trim) and three corrections change spectra (the MS1 arena-compaction fix, the `C4`
calibration term, the window key). The public
release v1.0.0 (2026-09-04) was cut from the v0.3.0 tree described below, and v1.1.0 (the same day)
added the two defaults recorded under its own heading; from this release the private and the public
repository share one
version line, and the tool reports its own version (`--help`, the ini `version` parameter and the
output's software entry used to carry the OpenMS version).

**Where it stands.** On a 2-hour public diaPASEF acquisition (PXD047793, run 009; same node, both tools
at 100 threads) this release runs in **0.61x the reference implementation's wall time at 0.55x its peak
memory** (12:42 / 187.9 GB against 20:57 / 340.6 GB) and, under per-charge FDR control at 1%, identifies
**1.28x the peptides with Sage and 1.00x (0.996) with MSFragger** (27,831 / 28,181 against 21,743 / 28,294);
on run 001 the ratios are 1.25 / 0.98. Whole-run entrapment FDR on the 2-hour files is at the nominal
1% (0.93-1.03% under the engines' pooled cut, 0.98-0.99% under the per-charge walk; dataset D reads
1.33%). The
30-minute dataset D runs in 3:13 at 57 GB. The record is docs/BASELINE.md (sections dated 2026-09-06 to
2026-09-08) and docs/REFERENCE-COMPARISON-2026-09-08.md.

### Changed
- **`charge:min_charge` default 2 -> 1, with a new ion-mobility charge veto (`charge:im_charge_veto`,
  on; `charge:im_veto_band`, 2.5 MAD-sigma).** The old default was confirmed on the three 30-60 minute
  in-house files; on a 2-hour tryptic acquisition emitting z=1 gains 14-20% Sage peptides (12-17% of
  the larger count) and most of the MSFragger deficit against the reference implementation. Those identifications are physically singly charged: short (7-9 aa),
  lysine-terminated, single-basic-site tryptic peptides whose 1/K0 sits **+0.29 Vs/cm2 above the 2+
  trend line** at the same m/z in 99.4-99.9% of cases -- identically in the reference implementation's
  own 1+ identifications -- and which co-elute with their own 2+ ion where both are seen. Charge
  halving is nevertheless real: the count walk calls a 2+ envelope z=1 whenever its M+1 is missing or
  already claimed and its M+2 is present -- 11-26% of z=1 calls depending on the file, 60% of them
  below m/z 750 where a 1+
  cannot be scored at all. TIMS resolves it: the 2+ and 3+ mobility lines are fitted per run from the
  run's own confident calls; a z=1 whose mobility lies on the 2+ line is re-called 2+, and one on the
  3+ line is dropped. The 3+ arm was measured before it was settled: re-calling those to 3+ identified
  essentially nothing (z=3 peptides +9 on run 009, +47 on dataset D) while adding 178k / 93k re-called
  precursors (117k / 73k spectra) -- only ~1.8% of z=1 calls are genuinely on the 3+ band, and the two
  lines are ~1 sigma apart at low m/z -- so dropping them takes 2.9% / 7.9% off the v37 spectrum list
  at a cost below 0.3% of peptides on either engine under either walk.
  Two things to know. Under the engines' pooled 1% cut the z=1 stratum carries more entrapment FDR than
  the rest -- 2.9% on the 2-hour files, ~9% on dataset D where the stratum is ~150 peptides -- and
  a whole-run figure hides it. The mechanism is a lower true-match prior in that stratum under one
  pooled threshold, not peptide length (at matched score *and* length z=1 is still 3-5x dirtier than
  z=2; decoys reproduce it). A per-charge FDR walk puts the stratum at 0.87-0.91% on the 2-hour files
  while keeping the gain (Sage per-charge +20.2% / +13.7% on runs 001 / 009 against the old default), so report FDR by
  charge downstream.
- **`perf:ms1_trace_bands` default 12 -> 48: MS1 tracing is 2x faster.** The earlier sweep concluded
  more bands were worse (12/24/48 -> 75.0/93.7/147.9 s) but it was measuring a *serial* band
  distribution that grew with the band count. With that step parallel the order inverts:
  **41.7/27.1/20.4 s at 9.8x/18.4x/32.4x**. Gated on both datasets -- Sage 0.9999 / 0.9994,
  MSFragger 1.0002 / 1.0203, entrapment FDR 1.26->1.24% and 1.12->1.07%.
- **Mass-trace detection distributes its bands in parallel, and the seed list is segmented per
  band.** Two serial stages were setting the floor. (1) The MS1 band distribution copied every
  peak into its band's sub-map on ONE thread -- measured at 51% of the MS1 phase (39.0 s of
  75.9 s on a 30-minute file), and it is why raising `perf:ms1_trace_bands` made that phase
  strictly *worse* (12/24/48 bands -> 75.0/93.7/147.9 s at 3.9x/3.5x/2.5x): more bands is more of
  exactly this copy. Chunking over spectra takes it to 0.55 s (the phase to ~37 s on the 30-minute
  file, 106.2 s at 11.2x on the 2-hour one).
  (2) `prepareTracing` sorted up to 239 million seed indices on one thread and each of the 12
  bands then walked that whole list to find its own; segmenting by band first and sorting the
  segments independently is exact (`filter_b(sort(all)) == sort(filter_b(all))` for a total
  order) and takes per-window prep from 60.1 s to 27.1 s at the worst window, 904 s to 393 s
  summed. Both are byte-identical on both benchmark files.
- **`findPartner`'s gate fields are laid out in m/z order.** Precursor inference was
  single-threaded and 22-25% of a 2-hour run; it chased RT and IM through 48-byte records one
  cache miss at a time. Same values, same order, same first match -- **438.8 s -> 177.2 s**. The
  phase logs its three stages; the residue was the greedy claim loop (156.3 s), not the sorts
  (8.5 s), which the next two entries take on.
- **Two hot loops compute their index instead of searching for it.** `best()`, the innermost step
  of integer tracing, ran a `lower_bound` over its frame's ~25,000 sorted flight-time bins on every
  frame step of every trace extension; the bin is an integer the instrument produced, so a
  per-frame direct-address row (~32 peaks per bucket) makes the search start a subtract and a
  shift -- **window loop -19% at -9% CPU**. `findPartner`, in the greedy claim loop, searched 22
  million doubles up to 50 times per seed; the key there is the top bits of the IEEE-754 pattern,
  monotone for positive doubles, so the bucket is one load and one shift and its width is
  *relative*, matching a ppm tolerance. Both exact -- the sub-range handed to the search provably
  contains the same position. (The natural key for the second is the flight-time bin too, but
  `Trace::tof` is 0 on the OpenMS MS1 path; that needs MS1 through the integer detector.)
- **Precursor inference is parallel and exact** (ordered speculation, batch `SPEXTRACTOR_SPEC_BATCH`,
  default 8192): precursor inference's thread occupancy went from 1.0x to **23.4x** on a 2-hour file
  (the greedy walk itself 129 s -> 7.8 s), with 0.7% of seeds re-evaluated and a byte-identical
  spectrum list on three files.
- **The trace record is 48 bytes, was 72.** It carried an 8-byte pointer to the store every trace of
  a vector already shares, an 8-byte copy of a calibration factor the store holds per frame, and an
  8-byte copy of the apex intensity the arena holds. The span accessors take the store explicitly,
  the factor is a 4-byte frame index, and the apex intensity is read through the arena (72 -> 56 -> 48).
  On a 2-hour acquisition this is the largest structure in the tool -- ~2.1 billion records, ~144 GiB
  at 72 bytes if simultaneous. The 72 -> 56 step measured -10.7 GB there and -2.7 GB on dataset D,
  less than the 16-24 GiB predicted from the record count because not every window's records are
  resident at once; the 56 -> 48 step, with the splitter's reserve, a further -5.5 GiB. A
  `static_assert` pins the size.
- **Renamed to SpeXtractor** (the previous name was taken): executable, class, namespace, macros and
  environment variables, source and test file names, CMake project and target, CI workflows, the
  OpenMS patches and every document. The GitHub repositories moved with it; the old URLs redirect.

### Added
- **`perf:malloc_trim`, on by default: 30% less peak memory for 8.5% more wall time.** The
  window loop's allocations stacked on top of everything the loading and MS1 phases had freed but the
  allocator kept -- measured, that floor is 138 GB at the loop start of a 2-hour acquisition.
  Returning it first (`malloc_trim(0)` at the two phase boundaries, glibc only) takes the peak from
  **265 GB to 186 GB** (measured interleaved across the memory pass, v13 -> v19, at the previous charge
  default; the trim step alone measured -28% peak for +6% wall, and with z=1 emitted the release
  peaks at 187.9 GB), with a byte-identical spectrum list. It is not free: the loop faults those
  pages back in cold (minor page faults +26%, window-loop CPU +15% at unchanged concurrency), which
  costs **+8.5% of wall time** measured interleaved on one node. On by default because memory is what
  bounds this tool -- it decides how many windows fit at once and whether a run fits the machine at
  all -- and off is one flag when time is the binding constraint.
- **Third OpenMS patch: move operations for `MassTrace`.** The class declares a defaulted destructor
  and copy operations, which suppresses the implicit moves, so every `std::move` of a mass trace --
  in OpenMS's own vector growth and in the band and split gathering here -- deep-copied its points.
  Two defaulted moves transfer instead; a `static_assert` on `is_nothrow_move_constructible` means a
  tree without the patch does not build the tool.
- **Memory and stage instrumentation**: allocator statistics (`mallinfo2`) at every milestone, so
  free-but-retained memory is measured rather than inferred; the picked-MS1 peak count; per-window
  seeds, parents to children, record and arena size and capacity; per-window stage seconds on every
  exit of the window body; an ordered slab digest under `SPEXTRACTOR_DET`; `[tstage]` MS1-tracing
  sub-stage seconds; `[tsub]` per-window trace sub-stages (slab / detect / merge / sort); the
  `[infer]` line now reports the speculation batch and its committed / re-evaluated / already-claimed
  counts; `[im-veto]` reports the fitted 2+ line, its sigma and the re-call / drop / keep counts.
- **Diagnostic knobs** (environment, off by default): `SPEXTRACTOR_Z1_DIAG[=path]` dumps the +ISO/2
  and +ISO/3 evidence for every z=1 call; `SPEXTRACTOR_Z1_CHARGE_UNSET` emits z=1 calls with no
  charge, so a search engine chooses; `SPEXTRACTOR_SPEC_BATCH=1` runs precursor inference
  sequentially.
- **End-to-end checks 9-13**: the shipped detector is the one that runs (9, 10), one isolation m/z in
  two ion-mobility slices is two windows (11), the MS1 arena compaction self-test (12), and the
  admission gate's logged high-water mark (13, on a one-window fixture). Thirteen checks; the suite ran every check on the
  `openms` fallback before 9 and 10 existed.
- **Build reproducibility.** The OpenMS patches were malformed (not orphaned) and are regenerated as
  unified diffs against the commit pinned in `patches/openms.lock`; the tool compiles against that
  upstream commit once the three patches are applied, without the separate mzPeak integration (every
  mzPeak reference is guarded; `-out_type mzpeak` refuses without a mzPeak build);
  the sqlite3 tdf reader is its own header (`src/TdfLoad.h`) with an include guard; the weekly CI job
  builds OpenMS from source at that pin, applies the patches and runs the end-to-end suite.
- **Cluster tooling**: `bench/launch.sh` starts a long job detached so the ssh channel is released,
  reserves its tag atomically, refuses a missing work directory and reports started / exited /
  failed distinctly; the benchmark drivers refuse to overwrite a measured arm and the publish step
  refuses to publish a binary that failed its own suite. `the deploy script` ships the
  launcher, the tool's headers, the end-to-end suite and its golden calibration file with every
  deploy and records the
  MassTrace-patch marker and the OpenMS library hash in the provenance.
- **Repository hygiene**: acquisition and specimen identifiers are scrubbed from the tracked tree
  (cohort samples are datasets A-F; the dataset-D baseline file is now `docs/BASELINE.md`; the drivers
  that need real paths are untracked, with tracked `.example` templates; run-directory names quoted in
  the record keep their historical labels); `evidence/` left the tree; CONTRIBUTING.md,
  SECURITY.md, issue and pull-request templates.

### Fixed
- **The scoring stage of a large isolation window was silently single-threaded.** libgomp's
  `GOMP_taskloop` runs the whole loop inline in the creating thread once
  `task_count + num_tasks > 64 * nthreads`; with the previous `grainsize(32)` that is 204,800
  precursors at 100 threads. Measured on the same libgomp at 100 threads and 20 us per iteration:
  200,000 iterations -> 82.7x, 300,000 iterations -> **1.0x**, and `num_tasks(400)` at 300,000 ->
  88.0x. On a 2-hour acquisition exactly two of 28 windows sit above that line, and they were the
  two that decided the run: they scored 417.6 s and 581.0 s where every neighbouring window --
  within 16% on fragment count -- scored 12-28 s, and the window loop's 748.5 s wall was one
  window's own 741.9 s chain. Scoring now uses a fixed pool of worker tasks (one per thread) that
  pull 32-precursor chunks from a shared cursor, so the task count no longer depends on the window
  size at any thread count. Spectrum output is unchanged (results were already written to pre-sized
  per-precursor slots).
- **MS1 arena compaction overwrote ~1% of precursor XICs.** The compaction that frees the profiles
  of unreferenced MS1 traces walked the trace vector in container order with a monotone write
  cursor, but the vector had been sorted by m/z after its spans were appended in detection order:
  kept spans visited after the cursor had passed their offset were overwritten before they were
  copied. Deterministic, so the thread-count digests never saw it. `compactUnreferenced()` walks
  the kept spans in offset order and validates bounds and disjointness before moving a byte;
  `-diag:selftest_arena` (e2e check 12) presents a fixture that defeats the old walk. Output changes
  (the corrected profiles feed fragment scoring); the digest baselines are re-taken.
- **`perf:max_concurrent_windows` was computed and logged but never checked**; the per-window byte
  projection booked 160 B/peak against 44 B measured, and the budget added the process's own RSS
  back into itself. Admission now happens on the master before a window task is spawned, so both
  bounds hold; the default (every window admitted) is unchanged, and e2e check 13 asserts the logged
  high-water mark.
- **Lifetimes.** The peak slab and the seed order are released before the band-arena merge, not
  after it; the MS1 traces, spans and precursors are released when the window loop joins, not at the
  end of the run; the retention-time axis is reserved for MS1 + MS2 frames; each `MassTrace` is
  released as it is converted; the valley splitter reserves its child count.
- **The determinism digest was blind to the fragment sort's primary key**: it now hashes `im` and
  `tof` as well. `bench/semantic_digest.py` missed a closing tag straddling a 4 MiB read boundary and
  accepted a truncated spectrum list; the e2e digest returned the empty hash for a missing list. New
  `bench/mzml_header_diff.py` compares everything outside the spectrum list (completion time masked).
- **One isolation m/z acquired in two ion-mobility slices is two windows.** The PXD017703 "py3"
  scheme (9 of 27 acquisitions) acquires each m/z window in two window groups with shifted,
  overlapping scan ranges ~1.7 s apart. Keyed by m/z alone they collapsed into one window whose
  frames were all of group A then all of group B, and the run stopped at the retention-time
  order guard. The window key now carries the `WindowGroup` from the vendor native ID; every other
  scheme has one slice per m/z, so their partition and order are unchanged. New e2e check.
- **The `C4` calibration term is modelled.** Bruker ModelType 1 files from a 2019 timsTOF Pro
  (firmware 6.0.110; 18 of the 27 public PXD017703 acquisitions) store `C4 = -0.0905`, which the
  model refused as an unmodelled higher-order term. Fitted against the vendor library, the residual
  of the shipped quadratic is closed by exactly one candidate correction -- an additive offset on
  the mass, `m = u^2 - C4` -- and with the temperature term the closed form reproduces the vendor
  library to 0.0000 ppm on the first and the last frame. Dropping it is -53..-938 ppm, worst at low
  mass. Bit-identical on every file with `C4 == 0`; `C3` stays refused (never observed non-zero).
  Both golden tests pin ten vendor probes on two frames and guard the ablation.
- **Runs on the public diaPASEF HeLa benchmark (PXD017703).** Three defects the in-house cohort never
  exposed: the calibration loader demanded exactly one `MzCalibration` row (these files have two;
  it now uses the row the frames reference, and falls back to the single-row rule when `Frames` has
  no such column), rejected a stored `C2 == 0` as missing (a real linear calibration on 2020 timsTOF
  Pro firmware; NULL is now told apart from zero), and -- on a stock OpenMS install -- silently fell
  back to the `openms` detector because `loadTofAxis` sat behind a `__has_include` for an in-tree
  OpenMS header. Both tdf readers now use the sqlite3 C API and a missing SQLite is a compile error.
  First public-data extraction: 136,818 spectra in 57 s.
- **Calibration fails closed on unmappable frames.** `loadTofAxis` no longer backfills index 0; the
  integer detector refuses input whose native IDs carry no parseable frame number and falls back to
  `openms` with a loud warning instead of a silent one.

### Measured
- **`perf:stream_load` is a sensitivity/resource trade, not a free default.** Both readers searched
  with both engines on two datasets plus entrapment: equivalent on the smaller file, but on the
  larger one the one-shot reader finds +223 Sage peptides (+2.0%) at unchanged entrapment FDR
  (1.13% vs 1.15%) -- real signal the streaming path loses, for 1.75x the memory and ~1.7x the wall.
  The default stays `true`; `false` is now documented as the more sensitive setting.
- **Entrapment FDR on all six datasets at the v0.3.0 defaults (2026-09-05): 1.13-1.31% at a nominal
  1%**, every interval overlapping. At this release's defaults the whole-run figure is 1.33% on
  dataset D and 0.93% / 1.03% on the 2-hour runs 001 / 009, with the z=1 stratum at 2.9% under the
  pooled cut and 0.87-0.91% under a per-charge walk. The point estimates sit within a third of a point
  of the nominal 1% (dataset D's is the high one, 1.33%); intervals were not re-computed for the v38
  arms.
- **`SPEXTRACTOR_PICK_BATCH` is fast and rejected.** 256 -> 4096 is -39% on the load phase, but the
  digest changes with the batch size and 4096 loses 7.2% of Sage and 6.1% of MSFragger peptides: the
  picker carries per-thread state across frames. The batch stays at 256, and the sensitivity is on the
  backlog as a correctness question.
- **Head to head with the reference implementation at this release's defaults** (PXD047793 run 009,
  the same node, both tools at 100 threads):

  | | reference implementation | SpeXtractor v2.0.0 | ratio |
  |---|---|---|---|
  | wall | 21:12.24 / 20:41.46 (mean 20:56.9) | **12:42.21** | **0.61x** |
  | peak RSS | 357.7 / 323.4 GB (mean 340.6) | **187.9 GB** | **0.55x** |
  | Sage peptides, per-charge 1% -- 009 | 21,743 | **27,831** | **1.28** |
  | MSFragger peptides, per-charge 1% -- 009 | 28,294 | **28,181** | **1.00** |
  | Sage, per-charge -- 001 | 15,418 | **19,262** | **1.25** |
  | MSFragger, per-charge -- 001 | 19,652 | **19,230** | **0.98** |
  | Sage peptides, engines' pooled cut -- 009 / 001 | 18,920 / 14,764 | 27,855 / 19,035 | 1.47 / 1.29 |
  | MSFragger, pooled -- 009 / 001 | 27,427 / 18,745 | 26,559 / 18,212 | 0.97 / 0.97 |

  The reference is a JVM run with `-Xmx400G`, so its peak partly reflects what it was allowed; the
  honest memory statement is "roughly half, and not sensitive to a heap flag". The SpeXtractor wall
  is one run against the reference's two-rep mean; the previous default's two reps spread 8%. Before this cycle the
  same file ran 1.46x *slower* than the reference (31:27 against 21:28).

## v1.1.0 — 2026-09-04 (public release)

### Changed
- **`-threads` defaults to every core.** TOPPBase's default of 1 was the wrong one for a tool whose
  window loop is essentially the entire runtime. An explicit `-threads 1` is still honoured: the
  command line is inspected rather than the value compared. On 224 cores against the benchmark's
  `-threads 100`: 5:10 vs 5:22 for byte-identical output (a single pair).
- **The output format follows the `-out` extension, `.mzpeak` by default in a build with mzPeak; `-out_type` forces it.**
  mzPeak (Parquet inside a zip) is about a third the size of mzML (2.25 GB against 6.23 GB for the
  same 655,776 spectra). DDA search engines read mzML, not mzPeak, so write `.mzML` whenever a search
  comes next; the tool warns on every mzPeak write.
- CI runs on four platforms per push (Linux GCC 13 and 11, macOS arm64, Windows MSVC) and a weekly
  job builds the tool against an OpenMS source tree patched by `scripts/apply_openms_patches.sh`.

## v1.0.0 — 2026-09-04 (first public release)

The v0.3.0 tree below, with acquisition and specimen identifiers scrubbed, the six-dataset benchmark,
CONTRIBUTING.md, SECURITY.md and the issue templates.

## v0.3.0 — 2026-09-04

Published as v1.0.0 on 2026-09-04. The six-dataset table and the `perf:stream_load` note below were
added the same day, after the tag.

### Benchmark, all six datasets, shipped defaults only

`spextractor -in <file>.d -out pseudo.mzML -threads 100` and nothing else:

| file | spectra | wall | peak RSS | Sage @1% | MSFragger @1% |
|---|---|---|---|---|---|
| dataset A | 862,716 | 8:26 | 108.7 GB | 10,909 | 11,935 |
| dataset B | 585,503 | 5:37 | 84.6 GB | 10,272 | 9,691 |
| dataset C | 723,314 | 6:27 | 90.3 GB | 12,149 | 12,516 |
| dataset D | 655,776 | 5:21 | 79.0 GB | 12,482 | 12,337 |
| dataset E | 542,533 | 5:38 | 67.9 GB | 11,217 | 10,585 |
| dataset F | 597,267 | 5:59 | 73.8 GB | 11,362 | 11,049 |

dataset C and dataset F had never been benchmarked before. Peak RSS spans 67.9-108.7 GB across the cohort,
which is where the README of the time stated an 80-125 GB requirement.

### Changed
- **`assembly:require_isotope_support` and `perf:stream_load` now default to TRUE.** Both were
  `registerFlag_`, so they defaulted to OFF -- while every benchmark figure this project has ever
  published passed them explicitly. The shipped default configuration had therefore never been
  measured. It has now been, and it was **6.9x slower and worse on both engines**: with
  `require_isotope_support` off, dataset D emits 1,255,577 spectra in 36:25 at 6.0x window-loop occupancy
  for Sage 12,212 / MSFragger 12,148; on, it emits 655,776 in 5:15 at 65.7x for Sage 12,482 /
  MSFragger 12,337. (An earlier measurement in July had put the gate's cost at −0.78% peptides; the
  sign flipped somewhere behind the charge gate, the apex estimator and the integer detector.)
  Without `stream_load` the loader holds the entire run at a measured 90.3 GB floor, which by itself
  exceeds the tool's current total peak. Both are now `<true/false>` options, since a flag cannot
  default to true; pass `false` to restore the old behaviour. **`perf:stream_load` also CHANGES
  OUTPUT** -- checked rather than assumed, and the assumption was wrong: true gives 655,776 spectra
  in 5:11 at 78.4 GB, false gives 656,371 in 10:30 at 121.8 GB, and the spectrum lists are not
  identical. The two readers pick peaks on different frame groupings. (Which one is closer to the
  truth was settled on 2026-09-05 -- see "Measured" under v2.0.0: the one-shot reader is
  slightly better on a large file, at unchanged entrapment FDR, for 1.75x the memory.) Every figure
  this project has published used `true`. This is the same class of defect as
  the `ms2_noise_threshold_int` / `ms2_split_valleys` mismatch fixed on 2026-09-03 -- that sweep
  checked value-bearing options and missed the flags.

- **`charge:min_charge` now defaults to 2**, dropping singly-charged precursor hypotheses before
  extraction. They are ~30% of emission and ~1.7% of peptides, and removing them GAINS peptides on
  both search engines on all three benchmark files (Sage +0.8/+2.7/+1.4%, MSFragger +1.2/+5.4/+0.9%)
  while cutting emission ~30% and runtime 17%. Entrapment FDR stays inside the previous 95% interval
  on every file. Set `charge:min_charge=1` to restore the previous behaviour.

- **Shipped defaults now match the benchmarked configuration.** `trace:ms2_noise_threshold_int`
  100 -> 10 and `trace:ms2_split_valleys` 0 -> 7.0. Every published figure was produced with 10 and
  7.0 passed on the command line, so a default run could not reproduce any of them.
- **`trace:mz_estimator` is a real parameter** (default `apex`), replacing an undocumented
  environment variable that silently set every reported precursor and fragment m/z.

### Added
- Parameter bounds on the numeric options. A negative count used to wrap through `Size`
  (`min_fragments -1` became ~1.8e19 and nothing was emitted) and a negative tolerance gated
  everything out; both failed as an empty but valid-looking result.
- `bench/iso_dup.py`, `bench/iso_collapse.py`, `bench/iso_sim.py`, `bench/iso_loss.py`,
  `bench/iso_guard.py`: the isotope-duplication census, collapse-rule evaluation, content-similarity
  test and loss trace behind the emission findings.

### Changed
- **`trace:detector` now defaults to `integer`.** Mass-trace detection runs on the instrument's own
  integer axes -- flight-time bin for m/z, frame index for retention time -- following OpenMS
  MassTraceDetection step for step, and never materialises a PeakMap of doubles. On dataset D it is
  faster and uses ~40% less memory than the OpenMS path (dataset D 86 vs 150 GB, dataset A 126 vs 222 GB; wall
  6:21 vs 6:54 and 10:35 vs 11:14). The peptide effect is **mixed and not consistent in sign**: Sage
  -1.3% on dataset D but +0.2% on dataset A, MSFragger +2.1% on dataset D but -3.5% on dataset A, entrapment indistinguishable
  on both (dataset D 1.27% [1.03-1.52] vs 1.38% [1.14-1.63]). The detectors **agree on only ~85% of the
  union** of identified peptides -- 1,148 OpenMS-only and 981 integer-only on dataset D -- so the memory
  saving, not a peptide gain, is the case for the default. Without the vendor flight-time calibration
  the tool **falls back to `openms` and says so**; the emitted mzML records which detector ran as
  `spx:detector`.

### Performance (2026-09-04, round 2: three output-neutral changes)
Measured old-vs-new with both arms on the same host, three files concurrently on three machines,
one binary from a shared install. **Every arm is digest-identical to its base**, so peptides are
unchanged by construction and no search was run.

| | dataset D | dataset A | dataset B |
|---|---|---|---|
| RSS at end of the window loop | 65.0 -> **48.3 GB** | 85.6 -> **55.1 GB** | 70.0 -> **49.8 GB** |
| window-loop occupancy | 67.6 -> 69.9x | 56.2 -> 61.3x | 56.9 -> 63.3x |

**These are memory changes, not speed changes.** Replicated as interleaved base/clean pairs on
shared machines with the load recorded before each run -- three pairs on dataset D, two on dataset B, every
digest identical. dataset D: wall 321.3 -> 312.7 s (−2.7%), window-loop CPU 9,229 -> 9,690 (**+5.0%**),
RSS at end of the window loop 63,880 -> 46,922 MB (−26.5%), process peak 81.3 -> 77.9 GB (−4.1%),
all with non-overlapping ranges. dataset B: no wall-clock difference at all, same ~4% CPU cost, same
~30% memory drop. So the trade is **~27% of the window loop's memory for ~5% more CPU at roughly
unchanged wall time** -- worth taking because concurrency is bounded by the free-RAM admission
gate, but it is a memory change. A first pass of single pairs appeared to show 5-6% off wall on
three files; that was load drift on shared nodes and is withdrawn. Do not cite a speed-up.

- **Valley splitting is streamed.** It used to build every trace of a chunk as an OpenMS `MassTrace`
  and then split the whole chunk, so the input payload and the entire split output were alive at
  once -- the two largest structures after the peak slab, 7.5-10.6 GB. One trace is now in flight at
  a time and those lines fall to 0.08 MB. `ElutionPeakDetection` is constructed and parameterised
  once per chunk rather than once per trace.
- **The fragment RT gate rejects on 2 bytes instead of 8.** The gate discards 99.4% of what it
  visits -- 867 billion visits, 6.9 TB of traffic per dataset D run -- and was reading a `double` to do it.
  A parallel `uint16` bucket array does the reject; the exact test is unchanged and runs only on
  survivors, so the candidate set and its order are identical (the score-gate counters match to the
  digit between arms).
- **Trace arenas are reserved before merging.** `absorb()` appended without reserving into a
  just-emptied destination, so 12 band merges and 48 chunk merges regrew geometrically.
- Process peak RSS falls only 2-5 GB because the peak is set outside the window loop; the loop
  ENDING ~30% lighter is what governs how many windows fit in flight.
- Rejected on evidence: compacting the peak slab to above-noise peaks (the seeds line reads 100.0%
  -- there are no sub-noise peaks, so the slab is irreducible), and moving the seed sort into the
  band tasks (<1% of CPU, and it re-partitions seeds across bands, which cost 3.3% of peptides once).

### Performance (2026-09-04, trace representation)
- **A trace's profile is a span, not a point list.** A trace point has one degree of freedom -- its
  intensity -- so the three parallel 4-byte arrays (frame, intensity, flight-time bin) and their
  three allocations per trace are replaced by an entry frame and a range in a per-window arena, with
  zero meaning a missed frame. Verified **byte-identical on both detectors** on dataset D. The per-window
  correlation grid, which was a second copy of every profile, is gone. Window-loop memory falls from
  a 68.6 GB simultaneous peak to 27.9 GB (integer) / 32.4 GB (OpenMS); process peak RSS 105 -> 88 GB
  and 164 -> 147 GB.
- **The `SPEXTRACTOR_MEM_LEDGER` byte ledger has been REMOVED** (it was temporary scaffolding for the
  memory work above and is gone as of the round-2 changes; ~86 lines). While it existed it was
  corrected twice: the trace line had been cumulative rather than a peak, and a 6.0 GB
  `list<Peak2D>` line was a phantom (that list is per trace and dies each iteration). The structural
  wins it was built to find are permanent: the visited flags are a bitset (4.87 -> 0.61 GB), and the
  slab and per-window preparation arrays are released before valley splitting rather than held
  across it.

### Performance (2026-09-03, window loop)
- **The scoring gate reads its one field from a parallel array instead of striding the 96-byte
  trace record.** The gate rejects 99.4% of the fragments it visits; the scan was moving ~83 TB per
  dataset D run for 8 bytes of payload per visit. dataset D wall 12:53 -> **7:17**, scoring stage 47% -> 4.8% of
  window time, **peptide set identical** on Sage. Replicated three times.
- **The window loop is one OpenMP task pool over all threads** (master/worker) instead of a rigid
  threads/bands x bands grid; window-loop occupancy 65x -> 81x on 100 threads. The number of windows
  resident is bounded by the free-RAM admission gate, whose per-window estimate was re-calibrated
  (10x -> 16x compact bytes; it had been under-booking by 35-55%).
- **The retention-time axis is a global frame index.** A trace point is (frame index, intensity),
  8 B instead of 16, and aligning two profiles is integer equality instead of a binary search per
  point; the per-window correlation grid is built without collecting or sorting ~10^8 RT values.
- `trace:detector=integer`: mass-trace detection on integer arrays with the instrument's flight-time
  bin as the m/z axis, following OpenMS MassTraceDetection step for step, calibration re-applied only
  at export. Introduced here behind the flag at 6:53 wall / 105 GB against 7:17 / 164 GB for the
  OpenMS path; it became the default later the same day, on the numbers under "Changed" above.
  See docs/INTEGER-TRACING-DESIGN.md.
- Band-count sensitivity measured: 4/6/12/25 bands move the peptide set by −0.02% to +0.10% and
  differ in ~2% of spectra's content. Banding is an approximation, not exact as the help had
  claimed; the halo is now sized per edge.

### Fixed
- MS1 traces are filtered for non-finite coordinates before sorting. A NaN made the comparator
  non-transitive, which is undefined behaviour in `sort()` and silently corrupts every later binary
  search. The fragment path already did this; the MS1 path did not.
- `FragGrid` CSR offsets widened to 64-bit. At 8.5 M fragments and ~510 support points each, the
  32-bit offsets were within a factor of two of wrapping, and an overflow there silently corrupts
  every correlation rather than crashing.
- mzPeak input fails loudly instead of degrading: an unknown frame no longer falls back to the
  reference temperature while still being stamped as exactly calibrated; a short batch result from
  the reader no longer leaves empty tail frames; mismatched m/z, intensity and mobility array
  lengths are rejected instead of truncated to the shortest.

### Removed
- The raw apex-frame fragment backfill and the pre-extraction isotope collapse, with all their
  environment gates. Both were measured on all three files and falsified in every configuration;
  the results are in `docs/BASELINE.md` and `docs/ISOTOPE-DUPLICATION-2026-09-03.md`, and the
  implementations are in the git history. 160 lines.
- An unused per-window band-count heuristic that a comment described as kept for reference.

### Runtime
- **MS1 path parallelised** (loader `[SpeXtractor ms1-par]`: batched parallel MS1 decode with per-thread ZSTD contexts and
  `FrameCentroider`, ordered hand-off; consumer `flushMS1_`: parallel MS1 pick). dataset D/100 threads: LOAD 445 s -> 39 s,
  total 22:22 -> **15:21**; spectrum data byte-identical, Sage peptide set identical.
- Decode-once frame-major parallel MS2 loader (`[SpeXtractor par-load]`), batched parallel MS2 pick; per-phase `[perf]`
  table and `[perf-load]` decode/hand-off/pick timers; `SPEXTRACTOR_LOAD_ONLY=1` for load-only profiling.
- Falsified and recorded: `MALLOC_ARENA_MAX=4` (10x slower at 100 threads), loader batch depth (64/256/1024 flat).

### Input
- **Streaming `.mzpeak` input** (`src/MzPeakStreamLoad.h`, build-optional `-DMZPEAK_ROOT`) on the mzPeak C++ library
  (OpenMS/mzpeak fork trunk); reads ims-compact archives with per-window mobility bands (works around name-only band
  params and NULL `precursor_index`). Benchmarked: not faster (the floor was the MS1 pick), and -11.7% peptides from the
  archive's two-point TOF transform (fragment error +10 ppm) -- see the runtime plan and the converter
  handoff. Output stamps `spx:mz_calibration = mzpeak_two_point_transform ...` for this path.
- Library build recipe for GCC 13 / Arrow 23 (`scripts/build_mzpeak_lib.sh`, `patches/spx_ranges_to.h`,
  `patches/mzpeak-cpp-arrow23.py`).

### Determinism
- `bench/semantic_digest.py` now stops at `</spectrumList>`: the trailing `<indexList>` byte offsets shift with any header
  length change and had falsely flagged two spectrum-identical files. Loader batch size does NOT change content
  (922,902 spectra, 0 differ; Sage set identical), and **neither does the thread count**: threads 8 == threads 100 on two pairs with the fixed digest, retracting the 2026-09-01 "thread-count dependent" finding. Output is byte-identical spectrum data at any thread count and loader batch.

### Scoring / assembly
- **E5:** `apportion` and `rp_max` now go through the same emitted-intensity weights as the default path
  (`weighted_()`); they had silently bypassed `corr_power`/`im_weight`, so every earlier A/B of those flags was
  confounded. First clean apportion run: -3.9% peptides (falsified again; NNLS cut).
- **Reported m/z of every trace is now the APEX member's m/z** (`SPEXTRACTOR_MZ_ESTIMATOR=apex`, the new default;
  `mean` restores the OpenMS intensity-weighted centroid): dataset D +2.6% Sage (12,537 vs 12,217) and +4.1% MSFragger
  (11,927 vs 11,463) with the paired precursor mass error vs the reference implementation +1.12 -> +0.78 ppm. Both-engines gate passed;
  generalises: dataset A +4.4% (10,789), dataset B +2.7% (10,156); mean ratio vs the reference implementation on Sage 105.1% -> 109.2%;
  entrapment of the apex arm 1.28% [1.03-1.53] at nominal 1%.
- Under test (env switches, defaults unchanged): `SPEXTRACTOR_PICK_MZ_MODE=seed|top3` (pick-level m/z; the -2.4 ppm
  fragment offset vs the reference implementation is upstream of the trace estimator), `SPEXTRACTOR_DROP_PREC_ISO=1` (drop the precursor's
  M+1..M+3 from fragment lists; 28%/25% of spectra carried them -- FALSIFIED, -2.3%, keep off), `SPEXTRACTOR_MZPEAK_EXACT` (now the default; `=0` accepts the two-point m/z),
  `SPEXTRACTOR_MIN_ISOTOPES=k` (precursor gate by envelope depth; k=3 = -39% emission, -23% wall, MSFragger -0.9%, Sage -6.4%),
  `SPEXTRACTOR_PRECURSOR_LIST=<tsv>` (emit only precursors matching a reference list), `SPEXTRACTOR_BACKFILL_RAW=N` /
  `SPEXTRACTOR_BACKFILL_MAXFRAGS=K` (add the N most intense untraced raw peaks of the apex frame inside the IM band:
  N=50 lifts MSFragger to 90% of the reference implementation at -2.6% Sage; faint-tail-only variant under test).
- Output-identical: band partition by binary search (R3), early skip of fragments below `min_corr_pts` support.
- Help texts of falsified flags (`rp_max`, `consolidate`, `merge`) now say so; `charge:iso_im_tolerance` help
  no longer contradicts its default.

### Benchmark findings
- MSFragger gap is per-precursor CONTENT of the faint tail: same precursor population as the reference implementation -> 85.0%; emission -39% -> 84.8%;
  dt-only peptides are searched but short by ~2 of ~9 matched ions that never become a trace; raw apex-frame peak
  backfill recovers 1,151 of them (MSFragger 85.6% -> 90.0%). FragPipe rescoring (Percolator, MSBooster off for both) gives 13,211 vs the reference implementation
  15,947 peptides (82.8%; raw-hyperscore walk 85.6%) -- rescoring lifts both tools and leaves the ratio; ours has
  8.6 PSMs/peptide vs 2.0. Entrapment of the shipping arm: 1.28% / 0.95% / 1.32% at nominal 1% on dataset D/dataset A/dataset B.
- Falsified today (kept in docs so they are not re-proposed): apportion (clean, -3.9%), precursor-isotope stripping
  (-2.3%), median/seed/top3 m/z estimators, 48 MS1 trace bands (slower, not output-identical), MALLOC_ARENA_MAX=4.

### Docs
- an internal backlog register: every open issue with status, root cause, fix and gate. Confirmed: apportion/rp_max bypass corr_power (E5); 28% of spectra carry the precursor M+1 as a
  fragment (C9); false mzPeak calibration provenance (fixed).

## v0.2.0 — 2026-09-02

First release with a verified calibration, tests, and CI. Supersedes v0.1.0, which was tagged on the
day-one commit and never represented a working state.

### Headline: exact, license-free TOF -> m/z calibration
The Bruker `.d` reader converted TOF to m/z with a two-point linear-in-sqrt chord that is **-5 to -11
ppm biased** (m/z dependent). We derived the exact ModelType-1 model from the constants in each
file's own `MzCalibration` table and verified it to **2.5e-5 ppm** against Bruker's library:

    t_ns   = tof * DigitizerTimebase + DigitizerDelay
    C1_eff = C1 * (1 + dC1 * (T1_ref - T1_frame) / 1e6)
    t_ns   = C0 + (1e6 / sqrt(C1_eff)) * sqrt(m) + C2 * m

The widely-copied open implementation (timsrust-calibration, adapted then disabled by mzdata as "not
consistently better") **drops the `C2*m` term** -- worth -11..-40 ppm. That omission, not translation
subtlety, is why the port underperformed. Reported upstream.

Measured on three diaPASEF files, closed search: **+6-11% Sage peptide identifications**, no vendor
library. This is an identification-YIELD effect, not better spectra (emission moved -0.2%): mass
error is a feature of Sage's discriminant. Since the reference implementation always carried vendor-calibrated masses,
every earlier head-to-head was biased against the open path -- this removes a self-inflicted
handicap rather than establishing a lead.

### Benchmarks (3 files, both engines, identical settings; docs/BENCHMARK-MATRIX-2026-09-01.md)
| | dataset D | dataset A | dataset B | vs the reference implementation |
|---|---|---|---|---|
| Sage peptides @1% FDR | 11,976 | 10,333 | 9,891 | mean 105.1%, 95% CI [93.0, 117.3] -- consistent with PARITY |
| MSFragger peptidoforms @1% | 11,463 | 11,465 | 9,404 | mean 85.0%, 95% CI [76.7, 93.2] -- a supported DEFICIT |
| median precursor mass error | +1.5 | +3.2 | +2.3 ppm | the reference implementation -1.4 / +0.3 / -0.6 |
SpeXtractor also emits ~1.32x more spectra, so per-spectrum efficiency favours the reference implementation. The MSFragger
gap survives perfect masses and is therefore search/detection-side.

### Safety
- **Fails closed.** ModelType != 1, `C2 <= 0` (a NULL/text C2 reads as 0.0 and selects the known-bad
  pure-sqrt law), `dC2`/`C3`/`C4` != 0, implausible `C1`, NaN, multi-row tables, or an unreadable
  `Frames.T1` are all errors, not silent approximations. `SPEXTRACTOR_ALLOW_CHORD_FALLBACK=1` (exactly
  "1") opts back into the biased chord.
- **Provenance.** Every emitted mzML records `spx:mz_calibration` =
  `tdf_table_modeltype1` | `bruker_sdk` | `legacy_chord_APPROXIMATE`, via an exported accessor that
  works across the shared-library boundary.
- Out-of-model inputs return NaN, never a plausible-looking 0.0.

### Tests and CI (first in this repo)
- `tests/test_calibration_cpp.cpp` -- 60 vendor-derived golden cases against the **shipped** header,
  round-trip inverse, and every rejection path. Ablation guards prove the suite can catch the
  known-bad implementation (39.4 ppm) and the temperature term (0.67 ppm).
- `tests/test_calibration.py` -- an independent re-implementation as a cross-check.
- `tests/test_entrapment.py` -- estimator CI, determinism, NaN-on-empty.
- `.github/workflows/tests.yml` runs all three. None needs a vendor library, cluster, or raw data.

### Determinism (scoped honestly)
Bit-reproducible **at a fixed thread count** -- verified by `bench/semantic_digest.py`, which compares
spectrum data and ignores the wall-clock stamp and the recorded parameters (two runs can never be
byte-identical otherwise; this also explains a July md5 mismatch left unexplained at the time).
Output DOES differ across thread counts, and last-ulp code changes cascade to ~2% in peptide counts.
The 0.06% noise floor in the decision rule is a SAME-BINARY figure.

### Also
- Entrapment estimator corrected (peptide-hypothesis ratio 0.6805, foreign-only counting, bootstrap
  CIs): actual FDR at nominal 1% is ~1.0-1.45%, not the ~2.3% previously reported.
- `assembly:corr_power=2` default (validated +8-10%, three files, both engines).
- Spectrum collapse falsified (-20..-60% peptides at every operating point, intrinsic to both tools).
- `scripts/apply_openms_patches.sh`; `the deploy script` refuses to deploy into an unpatched
  tree; evidence chain archived to durable storage.

### Known limitations
- Verified on ONE cohort/instrument; the three golden files share ONE MzCalibration vector.
- Public-data replication not yet done; every claim is single-cohort.
- A +1.5..+3.2 ppm residual remains, 2-4 ppm above the reference implementation on the same files. It survives every
  calibration path, so it is downstream of the m/z axis (centroiding / monoisotope reporting).
- Peptide counts are partly a mass-calibration measurement: compare only at similar residual ppm.
