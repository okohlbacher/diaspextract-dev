You are an adversarial reviewer of a software RELEASE. The project is SpeXtractor (C++20 OpenMS TOPP tool extracting pseudo-DDA spectra from Bruker diaPASEF data). Today (2026-09-08) it is being released as v2.0.0. Your job: find every statement in the release documents below that is WRONG, STALE, INTERNALLY CONTRADICTORY, or UNSUPPORTED by the evidence, and every release-engineering defect (version fields, semver reasoning, build/CI consequences). Do not praise. Do not summarise. Output a numbered list of findings, each: (file, quoted text, what is wrong, what the evidence says, severity HIGH/MEDIUM/LOW). If you can read files, verify against docs/BASELINE.md (the measurement record), docs/REFERENCE-COMPARISON-2026-09-08.md, src/spextractor.cpp (option registrations near lines 1650-1875, threads handling near line 3110, the version_ assignment near line 1659) and test/test_spextractor.py. If you cannot read files, judge from the evidence excerpts included below.

Specific questions to answer at the end:
Q1. Is v2.0.0 the right semver bump given: the executable was renamed spextract -> spextractor, a third OpenMS patch became mandatory (static_assert), defaults changed (charge:min_charge 2->1, new mobility veto, perf:ms1_trace_bands 12->48, perf:malloc_trim on), and outputs are not digest-comparable with 1.x? The previous public releases were v1.0.0 and v1.1.0 (both 2026-09-04).
Q2. The tool now sets TOPPBase::version_ = SPEXTRACTOR_VERSION ("2.0.0") in its constructor (the base class otherwise reports the OpenMS version). Any correctness or compatibility risk (e.g. OpenMS version checks on unofficial tools, ini-file round trips, the mzML software entry)?
Q3. Any number in the CHANGELOG v2.0.0 section or the README that is inconsistent with another number in the same documents or with the BASELINE excerpt?

=================== CHANGELOG.md, section v2.0.0 (and v1.1.0 / v1.0.0) ===================
# Changelog

## v2.0.0 — 2026-09-08

**Why 2.0.** Three things break compatibility with 1.x: the executable is `spextractor` (every script
that called `spextract` has to change); a third OpenMS patch (`MassTrace` move operations) is mandatory,
and a tree without it does not build the tool; and the output is not digest-comparable with 1.x (the
MS1 arena-compaction fix, the `C4` calibration term and the window key all change spectra). The public
releases v1.0.0 and v1.1.0 (2026-09-04) were cut from the v0.3.0 tree described below plus the two
defaults recorded under v1.1.0; from this release the private and the public repository share one
version line, and the tool reports its own version (`--help`, the ini `version` parameter and the
output's software entry used to carry the OpenMS version).

**Where it stands.** On a 2-hour public diaPASEF acquisition (PXD047793, run 009; same node, both tools
at 100 threads) this release runs in **0.61x the reference implementation's wall time at 0.55x its peak
memory** (12:42 / 188 GB against 20:57 / 341 GB) and, under per-charge FDR control at 1%, identifies
**1.28x the peptides with Sage and 1.00x with MSFragger** (27,831 / 28,181 against 21,743 / 28,294);
on run 001 the ratios are 1.25 / 0.98. Whole-run entrapment FDR is at the nominal 1% (0.93-1.03%). The
30-minute dataset D runs in 3:13 at 57 GB. The record is docs/BASELINE.md (sections dated 2026-09-06 to
2026-09-08) and docs/REFERENCE-COMPARISON-2026-09-08.md.

### Changed
- **`charge:min_charge` default 2 -> 1, with a new ion-mobility charge veto (`charge:im_charge_veto`,
  on; `charge:im_veto_band`, 2.5 MAD-sigma).** The old default rested on dataset D; on a 2-hour tryptic
  acquisition it discarded 14-20% of Sage peptides and most of the MSFragger deficit against the
  reference implementation. Those identifications are physically singly charged: short (7-9 aa),
  lysine-terminated, single-basic-site tryptic peptides whose 1/K0 sits **+0.29 Vs/cm2 above the 2+
  trend line** at the same m/z in 99.4-99.9% of cases -- identically in the reference implementation's
  own 1+ identifications -- and which co-elute with their own 2+ ion where both are seen. Charge
  halving is nevertheless real: the count walk calls a 2+ envelope z=1 whenever its M+1 is missing or
  already claimed and its M+2 is present, ~13% of z=1 calls, 60% of them below m/z 750 where a 1+
  cannot be scored at all. TIMS resolves it: the 2+ and 3+ mobility lines are fitted per run from the
  run's own confident calls; a z=1 whose mobility lies on the 2+ line is re-called 2+, and one on the
  3+ line is dropped. The 3+ arm was measured before it was settled: re-calling those to 3+ identified
  nothing on either file (z=3 peptides 5,313 -> 5,322 on run 009, 3,888 -> 3,935 on dataset D) while
  adding 178k / 93k spectra -- only ~1.8% of z=1 calls are genuinely on the 3+ band, and the two lines
  are ~1 sigma apart at low m/z -- so dropping them takes 3.0% / 8.5% off the spectrum list for free.
  Two things to know. Under the engines' pooled 1% cut the z=1 stratum carries more entrapment FDR than
  the rest -- 2.8-2.9% on the 2-hour files, ~9% on dataset D where the stratum is ~150 peptides -- and
  a whole-run figure hides it. The mechanism is a lower true-match prior in that stratum under one
  pooled threshold, not peptide length (at matched score *and* length z=1 is still 3-5x dirtier than
  z=2; decoys reproduce it). A per-charge FDR walk puts the stratum at 0.87-0.91% while keeping the
  gain (Sage per-charge +20.2% / +13.7% on runs 001 / 009 against the old default), so report FDR by
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
  exactly this copy. Chunking over spectra takes it to 0.55 s and the phase to **36.3 s at 8.0x**.
  (2) `prepareTracing` sorted up to 239 million seed indices on one thread and each of the 12
  bands then walked that whole list to find its own; segmenting by band first and sorting the
  segments independently is exact (`filter_b(sort(all)) == sort(filter_b(all))` for a total
  order) and takes per-window prep from 60.1 s to 27.1 s at the worst window, 904 s to 393 s
  summed. Both are byte-identical on both benchmark files.
- **`findPartner`'s gate fields are laid out in m/z order.** Precursor inference was
  single-threaded and 22-25% of a 2-hour run; it chased RT and IM through 48-byte records one
  cache miss at a time. Same values, same order, same first match -- **438.8 s -> 177.2 s**. The
  phase logs its three stages; the residue was the greedy claim loop (156.3 s), not the sorts
  (8.5 s), which the next entry removes.
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
  default 8192): the greedy claim loop went from 1.0x to **23.4x** on a 2-hour file, 112-138 s ->
  7.8 s, with 0.7% of seeds re-evaluated and a byte-identical spectrum list on three files.
- **The trace record is 48 bytes, was 72.** It carried an 8-byte pointer to the store every trace of
  a vector already shares, an 8-byte copy of a calibration factor the store holds per frame, and an
  8-byte copy of the apex intensity the arena holds. The span accessors take the store explicitly,
  the factor is a 4-byte frame index, and the apex intensity is read through the arena (72 -> 56 -> 48).
  On a 2-hour acquisition this is the largest structure in the tool -- 2.1 billion records, 143.6 GiB
  at 72 bytes if simultaneous -- and the change measured -10.7 GB there and -2.7 GB on dataset D:
  less than the 16-24 GiB predicted from the record count, because not every window's records are
  resident at once. A `static_assert` pins the size.
- **Renamed to SpeXtractor** (the previous name was taken): executable, class, namespace, macros and
  environment variables, source and test file names, CMake project and target, CI workflows, the
  OpenMS patches and every document. The GitHub repositories moved with it; the old URLs redirect.

### Added
- **`perf:malloc_trim`, on by default: 30% less peak memory for about 8% more wall time.** The
  window loop's allocations stacked on top of everything the loading and MS1 phases had freed but the
  allocator kept -- measured, that floor is 138 GB at the loop start of a 2-hour acquisition.
  Returning it first (`malloc_trim(0)` at the two phase boundaries, glibc only) takes the peak from
  **265 GB to 186 GB**, with a byte-identical spectrum list. It is not free: the loop faults those
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
  admission gate's logged high-water mark (13). Thirteen checks; the suite ran every check on the
  `openms` fallback before 9 and 10 existed.
- **Build reproducibility.** The OpenMS patches were malformed (not orphaned) and are regenerated as
  unified diffs against the commit pinned in `patches/openms.lock`; the tool compiles on a stock
  OpenMS tree (every mzPeak reference is guarded; `-out_type mzpeak` refuses without a mzPeak build);
  the sqlite3 tdf reader is its own header (`src/TdfLoad.h`) with an include guard; the weekly CI job
  builds OpenMS from source at that pin, applies the patches and runs the end-to-end suite.
- **Cluster tooling**: `bench/launch.sh` starts a long job detached so the ssh channel is released,
  reserves its tag atomically, refuses a missing work directory and reports started / exited /
  failed distinctly; the benchmark drivers refuse to overwrite a measured arm and the publish step
  refuses to publish a binary that failed its own suite. `scripts/sync_cluster.sh` ships the
  launcher, the tool's headers and the end-to-end suite with every deploy and records the
  MassTrace-patch marker and the OpenMS library hash in the provenance.
- **Repository hygiene**: acquisition and specimen identifiers are scrubbed from the tracked tree
  (cohort samples are datasets A-F; `docs/S30-BASELINE.md` is `docs/BASELINE.md`; the drivers that
  need real paths are untracked `.example` templates); `evidence/` left the tree; CONTRIBUTING.md,
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
  the root, `m = u^2 - C4` -- and with the temperature term the closed form reproduces the vendor
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
  pooled cut and 0.87-0.91% under a per-charge walk. The peptide counts on record are honest to
  about a quarter point of FDR.
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
  honest memory statement is "roughly half, and not sensitive to a heap flag". Before this cycle the
  same file ran 1.46x *slower* than the reference (31:27 against 21:28).

## v1.1.0 — 2026-09-04 (public release)

### Changed
- **`-threads` defaults to every core.** TOPPBase's default of 1 was the wrong one for a tool whose
  window loop is essentially the entire runtime. An explicit `-threads 1` is still honoured: the
  command line is inspected rather than the value compared. On 224 cores against the benchmark's
  `-threads 100`: 5:10 vs 5:22 for byte-identical output.
- **The output format follows the `-out` extension, `.mzpeak` by default; `-out_type` forces it.**
  mzPeak (Parquet inside a zip) is about a third the size of mzML (2.25 GB against 6.23 GB for the
  same 655,776 spectra). DDA search engines read mzML, not mzPeak, so write `.mzML` whenever a search
  comes next; the tool warns on every mzPeak write.
- CI runs on four platforms per push (Linux GCC 13 and 11, macOS arm64, Windows MSVC) and a weekly
  job builds the tool against an OpenMS source tree patched by `scripts/apply_openms_patches.sh`.

## v1.0.0 — 2026-09-04 (first public release)

The v0.3.0 tree below, with acquisition and specimen identifiers scrubbed, the six-dataset benchmark,
CONTRIBUTING.md, SECURITY.md and the issue templates.


=================== README.md (complete) ===================
# SpeXtractor

Extract pseudo-DDA ("pseudo-MS/MS") spectra from Bruker timsTOF **diaPASEF** data.

SpeXtractor turns a data-independent acquisition into a set of pseudo-tandem spectra that any
ordinary DDA search engine can read. Each emitted spectrum pairs one precursor hypothesis with the
fragment traces that co-elute with it in both retention time and ion mobility. The output is mzML
(or mzPeak, following the `-out` extension), so it feeds Sage, MSFragger, Comet or anything else that
reads mzML — no library, no spectral prediction, no enumeration of the search space in advance.

That last point is the reason the tool exists: because the search space is not enumerated before
the search runs, an **open or blind search** over the output can report variants and unexpected
modifications that a library-based DIA workflow cannot represent.

SpeXtractor is BSD-3-Clause and is a standalone application. **OpenMS is a prerequisite, not a
host** — the tool links against an OpenMS installation but lives outside the OpenMS source tree.

## Requirements

| | |
|---|---|
| OpenMS | the development commit pinned in `patches/openms.lock` (bd4b895, 2026-04-24; it identifies itself as a 3.6.0 pre-release), patched by `scripts/apply_openms_patches.sh` and built `WITH_OPENTIMS` to read Bruker `.d`. No released OpenMS package works |
| Compiler | C++20 — GCC 13+ or Clang 16+ |
| OpenMP | strongly recommended; without it the tool runs single-threaded |
| CMake | 3.16+ |
| **Memory** | **~57 GB peak** on a 30-minute gradient and **~170–190 GB** on a 2-hour acquisition at the shipped defaults (the 30–60 min cohort spanned 68–109 GB before the memory work); it scales with the acquisition |
| Disk | mzML output is roughly 9 GB for a 30-minute run and 19–20 GB for a 2-hour run at the previous emission; the current default emits 30–70% more spectra. mzPeak is about a third of that |

The memory figure is not a suggestion. A full diaPASEF acquisition holds millions of mass traces in
flight; on a 32 GB machine the tool will not complete. Peak usage is reported at the end of every
run, so you can size a node from your own data.

## Install

```bash
git clone https://github.com/okohlbacher/spextractor.git
cd spextractor
scripts/apply_openms_patches.sh /path/to/OpenMS    # see "OpenMS patches" below
cmake -B build -DOpenMS_DIR=/path/to/OpenMS/build
cmake --build build -j
```

The binary is `build/spextractor`. `cmake --install build` puts it in `<install prefix>/bin` (set `-DCMAKE_INSTALL_PREFIX`).

### OpenMS patches

`scripts/apply_openms_patches.sh` installs `src/TdfMzCalibration.h` into the OpenMS tree and applies
three patches. **All three matter. The build stops without the first and the third; it does not
notice a missing second:**

- **Vendor m/z calibration.** Without it the Bruker reader converts flight time to m/z with a
  two-point linear-in-sqrt chord that is **−5 to −11 ppm biased** (m/z dependent) on every file
  measured, costing roughly **6–11% of closed-search peptide identifications**. Every emitted mzML
  records which calibration was used in the `spx:mz_calibration` userParam
  (`tdf_table_modeltype1` | `bruker_sdk` | `legacy_chord_APPROXIMATE`). An unsupported calibration
  table **fails closed** rather than silently producing biased masses.
- **Lock-free elution-peak detection.** OpenMS guards a shared vector with a program-global critical
  section. Called from inside SpeXtractor's parallel window loop, that one lock serialises the tool.
- **`MassTrace` move operations.** OpenMS declares a defaulted destructor and copy operations on
  `MassTrace`, which suppresses the implicit moves, so every `std::move` deep-copied its points. A
  `static_assert` stops the build without this one.

Optionally, `OPENMS_BRUKER_SDK_PATH=/path/to/libtimsdata.so` uses Bruker's own library for the
conversion instead. It is an independent cross-check, not a requirement, and is not redistributed.

### Optional: `.mzpeak` input

Build the mzPeak C++ library once against the same Arrow/Parquet/libzip that OpenMS uses
(`scripts/build_mzpeak_lib.sh`), then configure with `-DMZPEAK_ROOT=<checkout>`. `.d` remains the
primary input and is faster.

## Run

```bash
spextractor -in sample.d -out pseudo.mzML -threads 64
```

That is the complete command. Every default is the configuration the project benchmarks; a run that
needed extra flags to reproduce a published figure would be a bug, and there is a test for exactly
that.

Then search the output like any DDA file:

```bash
sage sage.json -o results pseudo.mzML
```

### Options worth knowing

| option | default | what it does |
|---|---|---|
| `-threads` | all cores | worker threads; an explicit `-threads 1` is honoured. Parallelism is isolation windows × flight-time bands, and the window loop reaches ~72× (30-min) to ~90× (2-hour) thread occupancy at 100 threads; window concurrency is bounded by a free-RAM admission gate, not by core count |
| `-out_type` | follows the extension | `mzML` or `mzpeak`; `.mzpeak` when the extension says nothing. Search engines read mzML, so write `.mzML` whenever a search comes next |
| `-trace:detector` | `integer` | `integer` works on the instrument's flight-time bin; `openms` uses OpenMS `MassTraceDetection`. Different algorithms — see below |
| `-charge:min_charge` | 1 | lowest precursor charge to emit. Singly charged precursors are genuine on tryptic data (their mobility sits on the 1+ trend line) and are 14–20% of Sage peptides on a 2-hour acquisition, though only ~1.7% on a 30-minute one. Their stratum carries ~3% entrapment FDR under a pooled 1% cut, so control FDR per charge downstream. `2` restores the old behaviour |
| `-charge:im_charge_veto` | `true` | the 2+ and 3+ ion-mobility trend lines are fitted per run from the run's own confident precursors; a z=1 call on the 2+ line (~13% of z=1 calls, a halved 2+ envelope) is re-called 2+, one on the 3+ line is dropped. Genuine 1+ ions are untouched |
| `-charge:im_veto_band` | 2.5 | half-width of the veto's mobility band, in MAD-sigma of the fitted residuals |
| `-assembly:require_isotope_support` | `true` | drop precursor hypotheses with no isotope partner. `false` roughly doubles emission, is ~7× slower, and identifies fewer peptides |
| `-perf:malloc_trim` | `true` | return the allocator's free pages at the two phase boundaries (glibc). Trades **-30% peak memory for +8.5% wall** on a 2-hour acquisition (the loop re-faults the returned pages cold); byte-identical output either way. Off when time, not memory, is the constraint |
| `-perf:stream_load` | `true` | read the `.d` frame by frame. `false` holds the whole run in memory (90 GB floor) **and changes the output**: measured, it is slightly *more* sensitive on a large file (+2.0% Sage peptides at unchanged entrapment FDR) for 1.75× the memory and ~1.7× the wall |
| `-perf:ms1_trace_bands` | 48 | band-parallel MS1 mass-trace detection (exact partition with a halo). Raised from 12 on 2026-09-07: MS1 tracing 2× faster, peptide sets within 0.06–2% on both engines and both gate datasets; 1 = off |
| `-trace:max_span_sec` | 120 | trim a mass trace to this many seconds around its apex |

`spextractor --help` lists every option with the measurement behind each default.

### Reading the output

Emitted spectra are MS2 with a synthetic precursor. Provenance is recorded as userParams on the
run — `spx:detector`, `spx:require_isotope_support`, `spx:mz_calibration` — so a file can always be
attributed to the configuration that produced it.

## Two detectors

`-trace:detector` selects between genuinely different algorithms, not two implementations of one.

- **`integer`** (default) finds a peak's candidate traces by arithmetic on the instrument's own
  flight-time index, and never converts its compact store back to double m/z. It needs the vendor
  calibration and falls back to `openms` — loudly — without it.
- **`openms`** runs OpenMS `MassTraceDetection` on a materialised peak map.

They agree on about 85% of the union of identified peptides. Which one identifies more depends on
the search engine and on the file, so **the reason `integer` is the default is memory** — roughly
40% less — not a peptide gain. If you are chasing identifications on a particular dataset, it is
worth trying both.

## Performance

Measured at the shipped defaults of this release (v2.0.0), 100 threads:

| | 30-minute gradient (33,553 frames) | 2-hour acquisition (PXD047793 run 009) |
|---|---|---|
| wall time | 3:13 | 12:42 |
| peak RSS | 57 GB | 188 GB |
| window-loop occupancy | ~78× | ~89× |
| pseudo-spectra emitted | 0.85 M | 3.9 M |

On the 2-hour file, on the same node, that is **0.61× the wall time and 0.55× the peak memory** of the
reference implementation, and 1.28× its Sage peptides at parity with MSFragger under per-charge FDR
control (docs/REFERENCE-COMPARISON-2026-09-08.md).

The allocator's retained free pages were the largest single memory item on a 2-hour acquisition;
`perf:malloc_trim` returns them at the phase boundaries (−30% peak for +8.5% wall) and is on by
default. Preloading `tcmalloc_minimal` is a further, independent lever (−7% peak RSS, wall-neutral,
byte-identical), measured before the trim shipped and not re-measured with it.

Runtime is dominated by the window loop, which is parallel across isolation windows and, within a
window, across flight-time bands. The loader is a few percent. Memory, not CPU, sets how many
windows can be in flight: an admission gate sizes concurrency from free RAM at startup.

## Determinism

The spectrum data is **byte-identical at any thread count** for a fixed binary at the default loader
batch (8 vs 100 threads on two real-data pairs, and 1 vs 4 threads in the end-to-end suite on every
build). The loader batch size is *not* free: 1024 and 4096 change the digest, and 4096 loses 7% of
peptides, so it is not a knob.
`bench/semantic_digest.py` hashes `<spectrumList>`..`</spectrumList>`, excluding the wall-clock
stamp, the recorded parameters and the trailing byte-offset index — none of which can match across
invocations.

This does **not** survive a code change: a last-ulp difference in one arithmetic path cascades to
~2% in peptide counts. Compare two builds by the accepted peptide **set** and the ppm median, never
by raw counts. The two statements are about different things and both have been measured.

## Tests

```bash
python3 test/test_spextractor.py build/spextractor
```

Thirteen end-to-end checks against a synthetic acquisition: isotope ownership, the charge floor,
parameter validation, thread-count determinism, mass-trace extension across missing cycles, and
that the shipped detector is the one that actually runs. No fixtures, no framework, no network.

`tests/` additionally holds the calibration unit tests and the entrapment-FDR scoring used for the
benchmark record.

## Layout

```
src/        the tool (one translation unit) plus three headers: the calibration model, the tdf reader
            and the mzPeak streaming loader
patches/    the three OpenMS patches and the pinned OpenMS commit (openms.lock)
scripts/    build helpers, OpenMS patch application, cluster deployment
test/       the end-to-end suite
tests/      calibration and entrapment tests, golden calibration values
bench/      benchmark drivers, the semantic digest and the cluster launcher
harness/    the benchmark harness and the sample-registry template
docs/       measurements, design notes and review records
```

## Documentation

- [docs/BASELINE.md](docs/BASELINE.md) — the decision record: every default, what was
  measured to justify it, and what was falsified
- [docs/MZ-AXIS-DESIGN.md](docs/MZ-AXIS-DESIGN.md) — the flight-time index and the integer detector
- [docs/charge-inference.md](docs/charge-inference.md) — charge assignment, its coupling to MS1
  splitting, and the levers that did not work
- [CHANGELOG.md](CHANGELOG.md)

## Citing

See [CITATION.cff](CITATION.cff).

## License

BSD-3-Clause. Derived from OpenMS (BSD-3-Clause) — see [NOTICE](NOTICE).

=================== CONTRIBUTING.md (complete) ===================
# Contributing to SpeXtractor

Thanks for your interest. A few things are specific to this project and will save you time.

## Before you start

**SpeXtractor cannot be built against a released OpenMS package.** It includes a header that
`scripts/apply_openms_patches.sh` installs *into* the OpenMS tree, calls an OpenMS method the same
patch *adds*, uses APIs that postdate the newest OpenMS release, and refuses to compile against a
`MassTrace` without move operations (the third patch). You need an OpenMS source tree at the commit
pinned in `patches/openms.lock` (develop, 2026-04-24), patched by that script — the patches are cut
against exactly that commit. `.github/workflows/build.yml` does exactly this and is the reference
recipe.

**It needs a large machine.** Peak memory is ~57 GB on a 30-minute acquisition and ~170–190 GB on a 2-hour one at the shipped defaults (docs/BASELINE.md). The test suite runs on
a synthetic input and needs none of that.

## The one rule that matters

**A change to extraction is judged on identified peptides, never on spectrum counts, and never on
one search engine alone.** This project has repeatedly found changes that improve one engine and
harm the other, and changes whose sign flips between acquisitions. The standing bar for altering a
default is:

- both search engines,
- entrapment FDR inside the previous interval,
- and confirmation on a second acquisition.

If a change is *supposed* to be output-neutral, prove it with a spectrum-list digest
(`bench/semantic_digest.py`) rather than with peptide counts — counts move by ~2% from a last-ulp
arithmetic difference, so equal counts are not equality.

## Running the tests

```bash
python3 test/test_spextractor.py /path/to/spextractor     # 13 end-to-end checks, synthetic input
cmake -B build -DSPEXTRACTOR_TESTS_ONLY=ON && cmake --build build && ctest --test-dir build
```

The second form needs no OpenMS and is what CI runs on four platforms.

## Pull requests

- Say what you measured, on what, and what would have falsified it. "Should be faster" is not a
  measurement; a wall-clock delta from two runs on a shared machine usually isn't either.
- Keep defaults reproducible: a run with `-in`, `-out` and `-threads` must reproduce the benchmarked
  configuration. There is a test for this, because it has been broken before.
- Don't commit acquisition or specimen identifiers. `harness/samples.yaml` is untracked for this
  reason; copy `harness/samples.yaml.example`.

## Reporting a bug

Include the SpeXtractor version, the OpenMS version, the full command line, and the `spx:*` userParams
from the output mzML — they record which detector and which calibration actually ran, which is
usually the answer.

=================== EVIDENCE: docs/BASELINE.md, lines 1792-1938 (the 2026-09-08 measurements) ===================
## Head to head with the reference implementation, measured tonight (2026-09-08)

Both tools on TNBC 009, on `data`, within the same hour, both given 100 threads. The recorded
reference timing for this file was from a previous campaign, and `head2head.sh` carries a warning
that comparing across time is the error that produced one withdrawn claim -- so it was re-measured.

| | rep 1 | rep 2 | mean |
|---|---|---|---|
| reference implementation | 21:12.24 / 357.7 GB | 20:41.46 / 323.4 GB | 20:56.9 / 340.6 GB |
| **SpeXtractor v35** | 11:24.97 / 179.1 GB | 10:36.92 / 178.5 GB | **11:00.9 / 178.8 GB** |

**1.90x faster at 0.53x the peak memory.** For context this file was 1.46x SLOWER than the reference
before this week's work (31:26.98 against 21:28.00).

One caveat on the memory ratio: the reference is a JVM run with `-Xmx400G`, so its peak RSS partly
reflects what it was allowed rather than what it needs -- the same flags gave 268.2 GB in the earlier
campaign. SpeXtractor's 179 GB is a genuine requirement. The honest statement is "roughly half, and
not sensitive to a heap flag".


### v37: `charge:min_charge` 1 + the ion-mobility charge veto -- dataset D (2026-09-08)

See docs/REFERENCE-COMPARISON-2026-09-08.md for why. Arms: v35 default (`gateMs1Bands/b48_S30`, min_charge 2)
against v37 (min_charge 1, veto on), same file, same engines.

| | v35 default | v37 | |
|---|---:|---:|---|
| spectra | 656,257 | 927,712 | +41% |
| wall / peak RSS | 3:27.48 / 57.6 GB | **3:25.95 / 57.9 GB** | flat |
| veto | -- | of 407,478 z=1 calls: 107,040 -> 2+, 93,008 -> 3+, 207,430 kept | |
| Sage peptides (engine's global cut) | 12,593 | 12,536 (z=1: 202) | -0.45% |
| MSFragger peptides (global) | 11,642 | 11,581 (z=1: 163) | -0.52% |
| Sage, **per-charge** walk | 12,493 | **12,597** (z=1: 46) | **+0.8%** |
| MSFragger, **per-charge** walk | 12,360 | **12,700** (z=1: 28) | **+2.8%** |
| entrapment FDR, whole run | 1.24% | 1.38% | |
| entrapment by stratum (v37) | | z=1 **9.2%** (n=144, CI 3.9-16), z=2 1.05%, z=3 1.64% | |

Dataset D is the case the old default was tuned on, and it is where z=1 is rarest: 202 peptides against
5,000+ on a 2-hour TNBC file. Under the engines' own pooled cut the arm is -0.5% on both engines --
inside the gate's 1% rule -- and the loss is the pooled-threshold eviction the refuters demonstrated:
under a per-charge walk the same files give +0.8% and +2.8%. The z=1 stratum's 9% is real but small
(144 peptides) and is what per-charge control is for.

The veto's **3+ arm is the weak spot**: 93,008 re-calls to 3+ moved the z=3 count from 3,888 to
3,935 (global) and 3,817 to 3,832 (per-charge) -- essentially nothing -- so on this file they are
emission without identifications. The fitted 2+ and 3+ mobility lines are only ~1 sigma apart at low
m/z (at m/z 500: 0.867 vs 0.822 1/K0 against a 3+ sigma of 0.051), so a multiply charged z=1 in that
overlap is assigned 2 or 3 by whichever residual is smaller. The principled tie-breaker is the
intermediate-isotope test (a co-eluting trace at +ISO/2 says 2+, at +ISO/3 says 3+), which the
`SPEXTRACTOR_Z1_DIAG` machinery already computes; not yet wired in.


### New TNBC baseline T3 (v37, 2026-09-08)

`charge:min_charge` 1 + the mobility veto change the spectrum list, so T2 is retired.
**T3 = `88f89abad8eca9ca...`** (TNBC 009, v37, `/scratch/kohlbach/v37_009`). Extraction facts:

| | T2 (v35) | T3 (v37) |
|---|---:|---:|
| spectra | 2,343,822 | **4,035,234** (+72%) |
| veto | -- | 2,548,391 z=1 calls: 287,900 -> 2+, 178,226 -> 3+, 2,082,265 kept as 1+ |
| peak RSS | 190.9 GB | **190.3 GB** (flat: emission is not what bounds memory) |
| window loop | 412.0 s (80.0x) | 511.3 s (**90.6x**) |
| wall | 11:35.90 (spock) | 13:43.10 on `data`, **contended** by a concurrent MSFragger -- not a head-to-head number; a clean rerun follows |

The 72% more spectra cost no memory and ~+11% wall when uncontended (the earlier z>=1 arm ran
in ~13:20 against 11:59 on the same node); the window loop's occupancy rose to 90.6x because
more precursors means more scoring work to fill the tail with.


### v38: the veto's 3+ arm dropped -- dataset D (2026-09-08)

Same arms as the v37 table above; v38 differs from v37 only in dropping z=1 calls that sit on the 3+
mobility band instead of re-labelling them 3+.

| | v35 default | v37 | **v38** |
|---|---:|---:|---:|
| spectra | 656,257 | 927,712 | **854,817** |
| wall / peak RSS | 3:27.48 / 57.6 GB | 3:25.95 / 57.9 GB | **3:12.61 / 57.3 GB** |
| Sage peptides, engine's pooled cut | 12,593 | 12,536 (-0.45%) | **12,609 (+0.13%)** |
| MSFragger peptides, pooled cut | 11,642 | 11,581 (-0.52%) | 11,564 (-0.67%) |
| Sage, per-charge walk | 12,493 | 12,597 (+0.8%) | **12,639 (+1.2%)** |
| MSFragger, per-charge walk | 12,360 | 12,700 (+2.8%) | **12,666 (+2.5%)** |
| entrapment, whole run | 1.24% | 1.38% | 1.33% |
| entrapment z=1 stratum | -- | 9.2% (n=144) | 8.8% (n=151) |

The 93,008 dropped calls were pure emission: peptide counts are unchanged or better on both walks,
73k fewer spectra than v37, and the fastest dataset D wall measured. On dataset D the new default is
inside the gate's 1% rule under the engines' own pooled cut and positive on both engines under
per-charge control; the z=1 stratum here is tiny (~150 peptides) and dirty, which is what per-charge
FDR is for.


### v38 on TNBC 001 (2026-09-08)

v35 default arm = `qual_001` (min_charge 2); v38 = min_charge 1 + mobility veto with the 3+ arm dropped.
Extraction on ibminode05 (shared, loaded -- not a timing number): 16:02, 170.1 GB, 3,409,189 spectra
(v35: 2,135,267). Veto: of 2,137,636 z=1 calls, 241,062 (11.2%) re-called 2+, 157,532 dropped, 1,739,042 kept.

| | v35 default | **v38** | vs reference (v38) |
|---|---:|---:|---|
| Sage peptides, engine's pooled cut | 15,694 | **19,035 (+21.3%)** | 14,764 -> **1.289** |
| Sage proteins | 4,074 | 4,142 | 3,802 -> 1.089 |
| MSFragger peptides, pooled cut | 15,976 | **18,212 (+14.0%)** | 18,745 -> 0.972 |
| Sage, per-charge walk | 16,029 | **19,262 (+20.2%)** | |
| MSFragger, per-charge walk | 16,727 | **19,230 (+15.0%)** | |
| entrapment, whole run | 0.98% | 0.93% | |
| entrapment by stratum (v38) | | z=1 2.91% (n=3,481), z=2 0.41%, z=3 0.57% | |
| per-charge walk entrapment (v38) | | z=1 **0.87%**, z=2 1.14%, z=3 0.68%, whole 0.99% | |

Second file, same shape as 009: the z=1 stratum sits at ~2.9% under the pooled cut and at 0.87%
under per-charge control, with the gain intact on both engines under both walks.


### v38 on TNBC 009, and the new reference T4 (2026-09-08)

**T4 = `057aad4beec52483...`** (`/scratch/kohlbach/v38_009`, the shipped default: min_charge 1, mobility veto,
3+-band calls dropped). T3 is retired. Extraction on `data`, alone on the node:

| | v35 (T2) | v37 (T3) | **v38 (T4)** |
|---|---:|---:|---:|
| spectra | 2,343,822 | 4,035,234 | **3,918,321** |
| wall, uncontended, same node | 11:24.97 / 10:36.92 | 13:07.40 / 12:36.77 | **12:42.21** |
| peak RSS | 179.1 / 178.5 GB | 177.4 / 180.0 GB | 187.9 GB |
| window loop | 412.0 s (80.0x) | 442.4 s (91.1x) | 443.4 s (89.2x) |
| Sage peptides, pooled | 24,213 | 27,808 | **27,855** |
| MSFragger peptides, pooled | 24,199 | 26,588 | **26,559** |
| Sage, per-charge walk | 24,484 | 27,908 | **27,831 (+13.7%)** |
| MSFragger, per-charge walk | 25,029 | 28,185 | **28,181 (+12.6%)** |
| entrapment, whole run | 1.01% | 1.00% | 1.03% |
| entrapment z=1 stratum (pooled / per-charge) | -- | 2.91% / 0.91% | 2.94% / 0.91% |

Emitting the singly charged population costs ~+15% wall on a 2-hour file (12:42 against 11:01 mean
for v35) and no memory beyond the usual +-10 GB run-to-run spread; the window loop's occupancy rose
to ~90x because there is more scoring work to fill its tail with.

### Head to head at the new default (2026-09-08, `data`, both tools 100 threads)

| | reference implementation | SpeXtractor v38 | ratio |
|---|---|---|---|
| wall | 21:12.24 / 20:41.46 (mean 20:56.9) | **12:42.21** | **0.61x** |
| peak RSS | 357.7 / 323.4 GB (mean 340.6) | **187.9 GB** | **0.55x** |
| Sage peptides, per-charge 1% -- 009 | 21,743 | **27,831** | **1.28** |
| MSFragger peptides, per-charge 1% -- 009 | 28,294 | **28,181** | **1.00** |
| Sage, per-charge -- 001 | 15,418 | **19,262** | **1.25** |
| MSFragger, per-charge -- 001 | 19,652 | **19,230** | **0.98** |
| entrapment FDR, whole run (SpeX) | -- | 1.03% / 0.93% | at nominal 1% |

=================== EVIDENCE: source, option registrations (excerpt) ===================
62:#ifndef SPEXTRACTOR_VERSION
63:#define SPEXTRACTOR_VERSION "2.0.0"
334:  static_assert(sizeof(Trace) == 48, "Trace must stay 48 bytes: it is the largest structure in the tool "
1659:    version_ = SPEXTRACTOR_VERSION;
1680:    registerStringOption_("out_type", "<type>", "", "Force the output format instead of taking it "
1772:    registerStringOption_("perf:malloc_trim", "<true/false>", "true",
1784:    registerStringOption_("perf:stream_load", "<true/false>", "true",
1805:    registerIntOption_("perf:ms1_trace_bands", "<n>", 48, "[parallel] Band-parallel MS1 mass-trace detection, same exact-partition scheme as perf:trace_bands. DEFAULT RAISED 12 -> 48 on 2026-09-07: the earlier sweep
1818:    registerIntOption_("charge:min_charge", "<n>", 1, "Minimum precursor charge to emit; hypotheses below it "
1838:    registerStringOption_("charge:im_charge_veto", "<true/false>", "true", "[im-veto] Use the ion-mobility charge-state trend "
1848:    registerDoubleOption_("charge:im_veto_band", "<sigma>", 2.5, "[im-veto] Half-width of the 2+/3+ mobility band, in MAD-sigma of "
3124:        n_threads_req = std::max(1, (int)std::thread::hardware_concurrency());
  ExitCodes main_(int argc, const char** argv) override
  {
    phase_clock_();   // [perf-instr] fix the epoch HERE: it is a first-call static, and the
                      // streaming path first touched it only AFTER loading, so load time was
                      // invisible and every [t=..] was relative to post-load. [codex review]

    // -threads defaults to 1 in TOPPBase, a poor default for a tool whose window loop IS the
    // runtime. Default to every core. The command line is scanned rather than the value tested,
    // so that an EXPLICIT `-threads 1` still means one thread: testing `value == 1` alone would
    // silently override the one user who actually wants it serial.
    int n_threads_req = getIntOption_("threads");
    {
      bool given = false;
      for (int i = 1; i < argc && !given; ++i) given = (String(argv[i]) == "-threads");
      if (!given && n_threads_req == 1)
      {
        n_threads_req = std::max(1, (int)std::thread::hardware_concurrency());
        omp_set_num_threads(n_threads_req);
