# Backlog: closed and superseded items

Moved verbatim out of docs/BACKLOG.md on 2026-09-23 after a triage against the code, the CHANGELOG and
the project notes. Each keeps its full text; the first line under its heading says why it closed.

## 1. Unmix fragment XICs onto the co-eluting MS1 precursor basis (NNLS)

**Closed 2026-09-23:** superseded: its prerequisite (apportion) was falsified at -3.9% Sage (CHANGELOG v0.3.0); apportion/rp_max removed in 1.2.0

**Status: CUT 2026-09-02.** The prerequisite failed under the correct measurement: `assembly:apportion`,
re-run with the emit weights actually applied, lost 3.9% of Sage peptides (11,742 vs 12,217 share-all;
docs/BASELINE.md:457-463, C7), and NNLS was cut on that result (CHANGELOG.md v0.3.0, "First clean
apportion run: -3.9% peptides (falsified again; NNLS cut)"; docs/BACKLOG-ANALYSIS-2026-09-02.md). The
reasoning below is kept as written; do not re-propose without a new prerequisite.

**The idea.** Today the scorer in `assembleOne_` asks a *pairwise* question, one precursor at a time:
does fragment `f`'s elution profile correlate with precursor `p`'s? Every co-eluting precursor
asks independently, so under share-all a fragment is emitted into all of them at full intensity
(measured mean fan-out 6.45). Nothing ever asks the *joint* question.

The joint question is a regression. Let `P` be the matrix whose columns are the MS1 XICs of the
precursors co-eluting in this window, and `f` a fragment's XIC. Solve

    min || P w - f ||^2   subject to  w >= 0

The weights `w` are the fragment's intensity split across precursors, directly. Assign the
fragment to `argmax w`, or emit it into each precursor at `w_i` — an apportionment *derived from
the data* rather than a heuristic.

**Why this is better-posed than the decompositions already falsified.** Earlier analysis rejected
global SVD/NMF on this data because the rank is unknown and the matrix is not globally low-rank —
and rank selection *is* the answer you want, so assuming it is circular. That objection does not
apply here: **the number of components is not estimated, it is observed.** MS1 tells us which
precursors are present and gives their elution profiles. This turns an ill-posed blind
decomposition into a well-posed non-negative regression with a known design matrix. That is the
whole difference, and it is why this deserves a test where blind NMF did not.

**Relation to what exists.** `assembly:apportion` already splits intensity by `corr^p / sum(corr^p)`.
That is a crude, coordinate-wise stand-in for the same intent — it never solves a joint fit, so two
precursors with similar profiles both get high weight instead of competing. NNLS is the principled
version and subsumes it. `assembly:apportion` was measured first, on 2026-09-02, with the emit weights
actually applied (every earlier apportion A/B had bypassed them): it lost 3.9% of Sage peptides
(docs/BASELINE.md:457-463, C7). The heuristic captured no gain, so NNLS was cut on its prerequisite.

**Why it should help, in terms of measured defects.**
- Redundancy: we lose 14-16% of peptides at peptide-level FDR against the reference implementation's 5-7%, because we
  emit ~4.6 PSMs/peptide. Fragments landing in one precursor instead of six attacks that directly.
- Purity: only 5.79% (decoy-corrected, equal depth) of an emitted spectrum's intensity belongs to
  its own precursor; co-isolation contributes +7.50%.

**How to test.** The DIA-NN truth set already provides ground-truth fragment ownership: the
predicted library gives 405,336 true (precursor, fragment) pairs, and negatives are fragments of
other co-eluting precursors in the same window. So this is directly measurable *without* a search
engine — compute assignment precision/recall against that set for pairwise-Pearson vs `apportion`
vs NNLS, before running Sage at all.

**What would falsify it.**
- Assignment precision against the DIA-NN pairs does not beat the pairwise baseline. Then the
  limiting factor is the MS1 profiles themselves, not how they are combined.
- Precursor XICs in a window are too collinear to separate. **Measure this first** — it is cheap
  and decisive. Compute the condition number / pairwise correlation of `P` per window. Peptides
  co-eluting within a couple of seconds have near-identical profiles, and no solver recovers a
  split the data does not contain. If typical `P` is severely ill-conditioned, NNLS produces
  confident, arbitrary, wrong splits — worse than the current honest ambiguity.
- Peptides at `peptide_q` do not improve even if assignment precision does.

**Note on the ill-conditioning risk.** This is the real hazard, not compute cost. A regression that
silently picks one of many equally good answers is more dangerous than a heuristic that spreads the
intensity, because downstream it looks decisive. Regularisation (ridge, or an IM-similarity prior)
or an explicit ambiguity flag would be needed — and an ambiguity flag is arguably the more honest
output for a blind-search tool.

**Cost.** Windows hold ~50 co-eluting DIA-NN precursors and millions of fragment traces, so this is
a small dense NNLS (~50 unknowns, grid-length equations) per fragment. Warm-startable and trivially
parallel across fragments, but it sits in the inner loop, so runtime must be measured too.

**Prerequisite ordering.** Measure `assembly:apportion` -> measure conditioning of `P` -> only then
implement NNLS. The chain stopped at the first step (2026-09-02); the conditioning of `P` was never
measured and NNLS was never implemented.

---

## N. Decompose the whole cycle jointly, using our own redundancy as the data

**Closed 2026-09-23:** superseded: consolidate falsified at -12.7%/-24.0% and removed in 1.2.0; same-precursor duplicates are folded by the 1.4.0 twin fold

**Status: KILLED 2026-07-28.** The third kill condition fired: within-cycle duplicates carry
information. The `consolidate:delta_rt` sweep lost peptides at every setting (0.7 -> -12.7%,
3.0 -> -24.0%; docs/BASELINE.md:139-142, on the do-not-re-propose list), and the named prerequisite,
item 1, was cut on 2026-09-02 (docs/BASELINE.md:461). What the duplicates actually are is worked out
in docs/ISOTOPE-DUPLICATION-2026-09-03.md.

**Origin.** User proposal, 2026-07-22: *"use the large number of spectra to cluster the peaks in
the cycle (e.g. SVD/NNLS) to decompose everything"* — framed as **data cleanup**.

**The hook that makes this different from the blind decomposition already rejected.** Today's
cycle analysis ([benchmarks/cycle-redundancy.md](benchmarks/cycle-redundancy.md)) measured
within-cycle multiplicity of **2.85** — we emit ~3 pseudo-spectra per (peptide, cycle), where
the reference implementation emits 1.25. Those have been treated purely as a defect. But they are also **~3
independent noisy views of the same underlying cycle content**, and that is exactly the regime
where joint decomposition has something to work with. The redundancy stops being only a bug and
becomes the input.

Concretely: within one isolation window × one cycle, build `X` = (emitted spectra × fragment
m/z bins). We have many rows *because* of the over-emission. Factor `X ≈ W H` with `H` ≥ 0 the
component spectra and `W` ≥ 0 the per-emission weights. Components that recur across the
redundant emissions are real; components appearing in one emission only are extraction noise.
Output one consolidated spectrum per component — which is precisely the cleanup asked for, and
would attack the ~56% of within-cycle duplicates that `consolidate:delta_rt` addresses only by
nearest-neighbour merging.

**What the 2026-07-22 review established against blind decomposition, which still applies:**

* **Kruskal uniqueness needs component profiles to differ in at least one mode.** Co-eluting
  precursors inside one isolation window are exactly where profiles are collinear — PARAFAC is
  least identifiable precisely where we need it most.
* **Ion mobility is a partition, not a profile.** TIMS precedes fragmentation, so the mobility
  mode is a *label*, not a continuous third mode. The trilinearity argument for PARAFAC — the
  main reason it looked attractive — does not hold.
* **The quadrupole mask makes missingness structured**, not random: m/z visibility depends on IM
  and cycle position.
* Overall probability of success judged **<5%**.

**Why this variant partly escapes those.** It is not blind and not trilinear. It is a 2-D
non-negative factorisation over (emission × fragment) *within* one cycle-window cell, where the
row count is empirically large and the rank question is bounded by something observable — DIA-NN
reports ~50 co-isolated precursors per spectrum, and MS1 supplies candidate precursors for that
cell. It is closer to codex's recommendation of **anchored / coupled factorisation using
MS1-derived profiles as partial known factors** than to blind PARAFAC. It also overlaps
substantially with backlog item 1 (NNLS onto the MS1 basis) — **item 1 was to be tried first**,
since it needs no rank estimate at all; item 1 has since been cut (2026-09-02).

**Cheap falsification, before any implementation.** Take the ~31,621 duplicated (peptide, cycle)
groups already identified. For the ~56% whose members agree to ~15 ppm, ask offline: does a rank-1
non-negative fit reconstruct the members within noise? If yes, they are redundant views and joint
decomposition is justified. If the members need rank ≥ 2 to reconstruct, they carry distinct
information and merging them — by NMF *or* by `consolidate` — destroys signal. **That test is a
few hours on existing output and needs no new extraction run.**

**What would kill it — and did.** Rank-1 reconstruction fails on the tight-m/z duplicates; or item 1
(NNLS) already captures the gain, making the extra machinery unjustified; or the peptide count falls
in the `consolidate:delta_rt` sweep. The sweep finished with 0.7 -> -12.7% and 3.0 -> -24.0%
(docs/BASELINE.md:142), which showed that within-cycle duplicates carry information after all; the
item was killed on that result (2026-07-28). Item 1 was later cut as well.

---

## Operational notes moved

**Closed 2026-09-23:** stale pointer: the bench/README.md section it names was removed in 9a6c2d4; the procedure is bench/launch.sh

The "Cluster launch discipline (2026-09-07)" section — `bench/launch.sh`, `verify_publish.sh` and the
ssh-channel / `exit 255` findings — is finished procedure rather than an untested idea and now lives
in [bench/README.md](../bench/README.md) under the same heading.

### The peak picker is sensitive to how frames are grouped across threads -- CLOSED (2026-09-09): it was a dropped tail

**Closed 2026-09-23:** done: the dropped tail was fixed; per-window peak counts identical

**What it was.** `DIASPEXTRACT_PICK_BATCH` 256 -> 4096 changed the digest and cost 7.2% Sage / 6.1%
MSFragger peptides on dataset D, and the picker was suspected of per-thread state. Step 0b of the
tiling plan compared per-window slab digests and picked peak counts at both sizes: 20 of the 22
windows present at 4096 had IDENTICAL peak counts, and two windows were missing altogether. The
loss is exactly `n_MS2 mod kBatch` (210 at 256, 3,538 at 4096): `PickCompactConsumer`'s tail flush
was never invoked on the streaming path, and the `.d` reader emits window-group major, so the tail
is the last group's last cycles (docs/BASELINE.md, "tiling plan step 0", 0b). Fixed in 8219485
(`finish()` after both readers). The picker is frame-local; the batch size is a resource knob again.

**What remains.** `perf:stream_load=false` also differs from `true` -- part of that was the same
tail (the non-streaming path has no batches), the rest is the reader's frame aggregation; re-measure
after the fix before calling it a sensitivity.

### Tile invariance needs bounded parents (2026-09-09, decision pending)

**Closed 2026-09-23:** superseded by the cell-atomic grid (2026-09-09): digest-identical across tile groupings and thread counts

**The idea.** The step-1 probe showed 99.7% of spectra change under RT tiling, uniformly in RT:
EPD's smoothing window was per-parent (fixed, `trace:split_scan_time=frame`), and EPD's valley
DECISIONS are parent-global (a failed valley keeps the taller maximum and advances the other), so
any sub-range of a long parent can split differently from the whole. Detection itself is
unbounded (seeds by intensity, running centroid/sd, `visited` claims along a connected trace),
and MassTraceDetection's `min_sample_rate` is a whole-trace gate on the OpenMS-detector path.
Children are short (TNBC: p99 44 s, max 421 s) but parents are not. Options under design review
(bounded-parents workflow, 2026-09-09): cap the detector's extension around the seed; make the
split local (windowed EPD, a local valley rule, gap-filled parents); or price the dependence and
make the tiled geometry the reference. See docs/reviews/2026-09-09-split-scan-time/.

**Why.** Without it the tiled output differs everywhere by a small amount and the only gate is the
FDR-thresholded peptide set, which flips 0.2-20% under perturbations of any size.

**What would falsify it.** A tile-vs-whole per-spectrum diff (`bench/mzml_specdiff.py`) whose
differences are confined to within the smoother's edge of a boundary after the fix.

### Reimplement dnoise-style mobility-coherence denoising (2026-09-10, user request; IMPLEMENTED, default on)

**Closed 2026-09-23:** done: shipped, default on (1.2.0)

**Implemented 2026-09-10.** `src/DnoiseMs1.h` is a bit-identical port of dnoise v0.1.0's default MS1 path. It runs
inside the tool on the raw points before picking (`dnoise:ms1`, default true, `.d` input only). The gates:
- dnoise off reproduces both old pins (D `8c1b047f`, TNBC 009 `bff54a1f`);
- dnoise on reproduces DIAspeXtract on dnoise's own filtered file (D `e43672a0`, TNBC 009 `3aafd0b5`), at 100 and
  8 threads;
- the kept point counts equal dnoise's (118,053,254 and 649,615,267).

The user turned it on by default knowing dataset D's result (Sage −4.3%, MSFragger −4.0%). The output-identical MS1
prune (`perf:ms1_prune`) landed with it. See docs/reviews/2026-09-10-dnoise-port/ and
docs/reviews/2026-09-10-streaming-memory/data7-ms1-prune.md. The analysis below is kept as written.

**The paper.** Garrett, Diedrich and Yates III, *dnoise: Fast Native Data Reduction for Bruker
timsTOF*, bioRxiv 2026.08.27.747603; open source (Rust, MIT, github.com/pgarrett-scripps/dnoise).
It rewrites a native `.d` with points removed, in three stages:

1. **Ion-mobility streak filter.** A frame is (scan index, TOF index, intensity) triples. Intensity
   is summed over a neighbouring TOF window to give per-scan mobility profiles; occupied scans are
   grouped into runs with internal gaps up to `max_internal_gap` (2) bridged; a run survives only
   with at least `min_feature_length` (5) occupied scans; repeated for `iterations` passes.
   Intensity floors are ZERO -- the criterion is mobility occupancy, not intensity.
2. **Halo filter** against microchannel-plate saturation: drop a point below
   `halo_peak_fraction` (0.15) times the maximum intensity in a local box that EXCLUDES its own
   TOF column, so a real streak cannot suppress itself.
3. **Acquisition-aware geometric gates**: drop MS1 points outside anything the method could
   fragment -- for diaPASEF, the isolation-window table in m/z and 1/K0, with padding.

Reported on diaPASEF: **91-94% of MS1 points removed**, frame binaries 35-40% smaller, precursor
and protein-group counts within +/-0-2%; <= 69 s per run.

**Why it matters here, in this tool's own numbers.** The streaming tiled architecture moved the
process peak onto the MS1 pass: 31.0 GB, of which the picked MS1 `PeakMap` is **13.8 GB holding
725,116,915 picked peaks**. Raw MS1 frames carry ~690k points each, so the existing
`PeakPickerIM::pickIMCluster` is removing only about a fifth of them -- the rest are single-scan
hits that survive clustering as their own centroid, which is exactly the population dnoise
targets. If the reported diaPASEF reduction transfers even partly, the binding constraint of the
whole streaming design falls by an order of magnitude, and MS1 tracing (204 CPU-s) with it. The
MS2 side is the same shape: 12.6 GB of slab from 1.258e9 picked peaks.

**Why it is not free.** This tool's identification gap is at LOW ABUNDANCE -- it emits a spectrum
for ~87% of the peptides it misses, and abundance is the only discriminator. A filter keyed on
occupancy could remove the faint ions the tool is already failing to convert, or could remove the
noise burying them. It is an S-class change: Sage and MSFragger plus an entrapment FDR on both
acquisitions, against D Sage 13,491 / MSFragger 12,918 / entrapment 1.30% and TNBC 009
Sage 29,067 / MSFragger 27,949 / entrapment 1.09%.

**Measured (docs/reviews/2026-09-10-dnoise/stage1-measurement.md):** stage 1 removes 70.4% of TNBC's
and 86.9% of D's raw MS1 points, as a monotone staircase in intensity; the verdict's streak-clustering
design removes strictly more than the paper's definition, and its map bound fails on TNBC. 85.0% of TNBC's
picked MS1 map is below the tracer's own 100-count threshold and is never traced.

**The real dnoise v0.1.0 as a preprocessor, searched (docs/reviews/2026-09-10-dnoise/real-dnoise-evaluation.md):**
the no-op reproduces both pins, so its rewrite changes nothing DIAspeXtract reads. Its default, MS1 only, cuts
DIAspeXtract's tiled peak (`-tile:cells_per_tile 1`) by 33% on D and 63% on TNBC 009 against same-node
controls; the shipped single tile was not measured. Entrapment stays inside the gate: 1.36% against 1.30% on
D, 0.93% against 1.09% on TNBC, just below the control's interval. The peptide cost is D −4.3% on Sage and
−4.0% on MSFragger, TNBC +1.5% and −0.5%: on D that fails the S gate. Anything that filters MS2 costs 13-21% of MSFragger
peptides on both files. On diaPASEF, dnoise's MS2 mode is its MS/MS streak filter inside each window; the
scan gate removes almost nothing.

**Verdict (docs/reviews/2026-09-10-dnoise/verdict.md): ship the PREDICATE as instrumentation
first, not a filter.** One count-only pass that changes no byte of output and prices the whole
proposal, `dnoise:ms1=count`. If it is ever built as a filter it belongs in the LOADER
(`frameToSpectrum`, on the integer (scan, TOF, intensity) triples before m/z conversion), MS1 only,
stage 1 only, halo off, MS2 off, and the `.d` rewrite never. Four reasons the loader is the layer:
the exact scan index is computed there and thrown away, so nothing downstream can reconstruct
occupancy; the triples are already CSR-ordered, so the filter is one linear sweep; TOF indices are
integers, so the neighbourhood is the paper's own bin window rather than a ppm window 2.4x wider at
m/z 1700 than at 300; and a deleted point never pays for `tof2mz`, the `Peak1D` build, the sort,
the picker transient or a `PeakMap` slot.

What is genuinely new is run length on the SCAN axis. The tool has no contiguity concept anywhere:
`pickIMCluster` has no minimum member count, no run and no gap rule, and a single-scan hit becomes a
first-class centroid indistinguishable from a 40-scan streak's. Occupancy is destroyed at emission,
so the criterion CANNOT live downstream of the picker. The MS2 half of dnoise's geometric gate removes
almost nothing on diaPASEF: no MS2 points on D and 0.09% on TNBC 009, measured by dry run. dnoise's MS2
mode is its MS/MS streak filter, which removes 66.8% and 54.0% (stage1-measurement.md).

**Worth, and why it is not urgent.** The MS1 map would fall 13,830 -> <= 3,851 MiB by the verdict's bound
(4,038 was a unit slip; the real dnoise default left 43.5 M picked MS1 peaks, 831 MiB), but that is
**0 GB at the shipped default**, whose peak is in the window loop with the MS1 map already
released. It converts the 6-tile arm by -24% and only then makes tiling a real memory lever. Time:
-5 to -9% of the run, and NEGATIVE if emission rises -- the two closest prior experiments raised
emission 31% and 620%. **Risk:** at the counting limit occupancy IS intensity, and three cascades
(MS1 `min_sample_rate`, the break-on-first-miss isotope walk, the run-global veto fit) turn one
deleted point into a lost precursor, in exactly the low-abundance stratum that is the whole
identification deficit. S-class: both engines and entrapment on both acquisitions.

### Tiled reader, steps 3a/3b: what the step-2 reviews put on the list (2026-09-10)

**Closed 2026-09-23:** done: 14-arm digest gate; TNBC 009 124 -> 71 GB at 13 tiles

- **A `readTile()` seam.** Step 2 slices the resident slabs inline in the tile loop; step 3b's
  `.d` reader (`Config::dia_ms2_rt_lo/hi` + per-tile re-open) needs the two-method source the
  judged plan names (`readMS1()`, `readTile(tile)`), with the frozen tables, window keys and band
  edges initialised from METADATA independently of delivered slabs (Codex 11, Kimi 10).
- **`expected_frames` in pass 2.** The consumer reserves each slab from `ms1_.size()`; with
  `load_ms1 = false` that is 0 and the reservation degrades to geometric growth. Pass the tile's
  frozen frame count per window (judged plan item 12; Kimi 9b).
- **Band edges from the acquisition range (3a)** so that a reader that never sees the whole slab
  can compute `wbands`; a G-class re-pin (`tlo = 0`, `thi` from `MzAcqRangeUpper`).

### mzML input keeps the slab as its frame table (2026-09-10, deliberate)

**Closed 2026-09-23:** done: a correctness record, no open work

The judged tiled-reader plan (docs/reviews/2026-09-10-tiled-reader-plan/judge.md, step 1) defines
an mzML window's frozen frame table as the union of its window group's frames. Step 1 (b) leaves
mzML at "the frames the window delivered" (`spx:frame_table=slab`): the mzML path is resident and
untiled, converters other than OpenMS's own carry no `windowGroup=` in their native IDs (every
window would land in group 0 and the union would be the whole run's MS2 frames), and no gate
exists for mzML input beyond the e2e fixtures. Revisit only if an mzML tiled reader is ever built;
then the definition must be pinned on a converted real file first.

### Parallel mzML serialisation: the win is real, OpenMS's writer is not thread-safe

**Closed 2026-09-23:** done: openms-mzml-parallel-write.patch, WRITE 20.1 -> 5.9 s on D, byte-identical

**The idea.** WRITE is the largest serial block left: 92.9 s of an 822 s run on a 2-hour
acquisition (10.7%), 20 s of 197 s on a 30-minute one, all at 1.0x parallelism. It is CPU-bound,
not I/O-bound -- measured, the write sustains ~390 MB/s while the filesystem underneath it does
**4.0 GB/s**, a 10x headroom. Serialising a spectrum is independent of every other spectrum; only
the concatenation is ordered. Encoding in parallel into per-chunk buffers appended in index order
is byte-identical by construction, and should take the phase to roughly the I/O floor (~10-15 s).

**Attempted 2026-09-08, and why it was reverted.** The patch (parallel encode in waves, bounded
buffering, ordered append, `copyfmt` so the number formatting matches) is correct in shape: it
passed the end-to-end suite and produced the file. On a real acquisition it aborts with
`double free or corruption`. `MzMLHandler::writeSpectrum_` is const and takes its inputs by const
reference, but the path underneath it mutates shared state in at least two places:
`MzMLHandler::cached_terms_` (a `mutable std::map` memoising CV-term validation, written in
`validateCV_`), and the `SemanticValidator` the writer holds. Freezing `cached_terms_` -- warming
it serially on the first spectrum, then only reading it -- removed one race and the corruption
persisted, so the validator has its own.

**Where the corruption actually is (backtrace, 2026-09-08).** Under gdb the abort lands in
`MzMLHandler::writePrecursor_`, in `operator new` taking the malloc arena lock -- i.e. that frame is
where a corrupted heap was *detected*, not where it was corrupted. Ruling out by inspection since:
`writePrecursor_` only reads `options_`; `SemanticValidator::locateTerm` is `const` and reads
`rules_` and the CV; and freezing `cached_terms_` (warm serially, then read-only) did not stop it.
So a fourth writer is still unaccounted for. Note that `writePrecursor_`, `writeSoftware_`,
`writeSourceFile_` and `writeDataProcessing_` are all NON-const members, unlike `writeSpectrum_` and
`writeUserParam_` -- that asymmetry is the place to look next, together with the
`ControlledVocabulary` singleton's lookup paths (`checkAndGetTermByName`, `iterateAllChildren`),
which are the remaining shared objects on the path.

**What would actually work.** Give each encoding thread its own `MzMLHandler` and its own
validator, so nothing is shared: the per-thread construction cost is paid once per wave, not per
spectrum. That is a larger change inside OpenMS than it first appears, and it needs its own
correctness argument (the handlers must be configured identically, or the output differs).
Alternatively, precompute only the base64 blobs in parallel -- `Base64::encode` is a pure static
function -- and have the serial writer consume them; that captures the array encoding but not the
per-spectrum XML and cvParam work, and the split between those two is unmeasured.

**What would falsify it.** A measurement showing the per-spectrum XML and metadata work, rather
than base64 of the arrays, is most of the 23.7 us/spectrum -- then a per-thread handler is the only
route and the base64 shortcut is not worth building. Also: on the default output format (mzPeak,
which is Parquet) this phase is a different code path entirely and the whole item may not apply.

### Rename the tool, docs and repositories to DIAspeXtract (2026-09-12, user request) -- DONE (2026-09-15)

**Closed 2026-09-23:** done: 1.3.0

**Done 2026-09-15** on branch `rename/diaspextract-1.3.0`, released as v1.3.0 (CHANGELOG.md, "Migrating from 1.2.x"):
the rename tool (scratchpad `rename13/rename_dia.py`, the same shape as the 2026-09-11 one) plus the hand edits below;
the guard in `main()` refuses `DIASPEXTRACTOR_*` and `SPEXTRACTOR_*`; filename-dated docs, docs/benchmarks, docs/reviews
and the released CHANGELOG sections keep the names they were written under. The entry below is the plan as written.

**What.** Third rename, dropping the "-or": tool name `DIAspeXtract`, binary `diaspextract`, repositories
`okohlbacher/diaspextract` and `okohlbacher/diaspextract-dev`, and every mention in docs and code. History:
speXtract (original, collided) -> SpeXtractor (2026-09-06) -> DIAspeXtractor (2026-09-11, v1.2.0) -> DIAspeXtract.

**Check first.** `diaspextract` / `DIAspeXtract` for collisions on GitHub (repos, orgs, code), bioconda, conda-forge,
PyPI, bio.tools (was unreachable last time), the OpenMS TOPP list and the literature. The original collision was on the
bare `spextract`; the `DIA` prefix is what separates the new name, so check the prefixed form, not the stem.

**Scope, from the previous rename** (same procedure, one day of attended work): the rename tool
`rename_dia.py` with its ordered lookbehind rules and exclusion list (it is in the 2026-09-11 session scratchpad,
`plan/tools/`; re-create it from `git show 5e8a660` if gone), then the hand edits it cannot do: CMake project and
option (`DIASPEXTRACT_TESTS_ONLY`, the old option a FATAL_ERROR), the version define, `main()`'s fail-closed guard
extended to refuse `DIASPEXTRACTOR_*` as well as `SPEXTRACTOR_*`, namespace, the OpenMS patches (namespace, the three
getenv names read inside libOpenMS, comments; hunks must still apply to the pinned tree), `scripts/sync_cluster.sh`
and its transaction harness, `build.yml`'s version and name gates, `verify_publish_dia.sh` on the cluster (a new copy,
never `sed -i` on a script a chain uses), the in-tree OpenMS build on ibminode05 (`executables.cmake`, `src/topp/CMakeLists.txt`,
the patched sources, then `cmake .` and a rebuild), `harness/` (env prefix `DIASPEXTRACT_*`), CITATION.cff, README,
NOTICE, SECURITY, CONTRIBUTING, the public logo's title/aria-label, and the export script's `--name`.

**Decisions carried over unless revisited.** `spx:` header stamps and `spx_` precursor keys stay (they sit inside
the digest; renaming them moves all four pins). No compatibility alias for the old binary name. Frozen: verbatim
reviewer outputs under docs/reviews, released CHANGELOG sections, the ceph install root
`/ceph/ibmi/abi/oliver/spextract` and the published arms (new arms publish `bin/diaspextract`). Prose-only renames in
historical docs. The private harness plan schema id stays.

**Gate.** Digest identity on both files at the defaults (D `e43672a0`, TNBC 009 `3aafd0b5`; dnoise off `8c1b047f`,
`bff54a1f`), e2e including the guard check for BOTH old prefixes, the deploy-transaction harness, CI on all legs.

**Release.** A binary and repository rename is a breaking change for 1.2.x users: ship it as its own release with a
migration section (the 1.2.0 one is the template), rename the GitHub repositories at that point (redirects cover the
old URLs), update the two `origin` remotes, and archive nothing until the export is verified.

### Rename the project and repositories to DIAspeXtractor (2026-09-10, user request) -- DONE (2026-09-11)

**Closed 2026-09-23:** done, then superseded by the DIAspeXtract rename

**Done 2026-09-11** in the commit after b5f6395 (CHANGELOG [Unreleased], "Renamed"). Decided: binary `diaspextractor`;
`DIASPEXTRACTOR_*` variables, and any set `SPEXTRACTOR_*` variable refuses the run (no dual read); no `spextractor`
alias; CMake option `DIASPEXTRACTOR_TESTS_ONLY`, the old one an error; namespace `diaspextractor::`; `spx:` / `spx_`
kept; repository URLs `okohlbacher/diaspextractor` and `okohlbacher/diaspextractor-dev`. The GitHub renames, the
cluster tree edits and the digest gates come with the 3.0.0 release. Kept as they were: verbatim reviewer outputs and
briefs under docs/reviews, the `/ceph/ibmi/abi/oliver/spextract` root and published arms, quoted commands, variables and
paths; the historical docs are renamed in prose only. harness/ is renamed separately. The entry below is the plan as
written on 2026-09-10.

**Why.** Another existing tool is already named spextractor, and the names collide. This is the second
rename for the same reason: the tool became SpeXtractor on 2026-09-06 because its first name was taken.

**Check first.** Search the new name for collisions before committing to it: GitHub, bioconda and
conda-forge, PyPI, bio.tools, the OpenMS TOPP tool list, and the literature.

**Scope, measured 2026-09-10.** The current name appears 4,180 times in 176 of 263 tracked files.
- Name and metadata: `TOPPBase("SpeXtractor", ...)`, CMake `project(SpeXtractor ...)`, `CITATION.cff`
  (title, repository URL), README, CHANGELOG, NOTICE, CONTRIBUTING, SECURITY, the public repo's logo, and the
  release export script.
- Code identifiers: the binary and build target `spextractor`, `src/spextractor.cpp`,
  `test/test_spextractor.py`, the namespace, and 53 distinct `SPEXTRACTOR_*` macros and environment
  variables (`SPEXTRACTOR_VERSION`, `SPEXTRACTOR_TESTS_ONLY`, every probe).
- Repositories: `okohlbacher/spextractor` (public) and `okohlbacher/spextractor-dev` (private). GitHub
  redirects renamed repositories, but the `origin` remotes, the CITATION URL, badges and workflow paths
  (`build.yml` checks out into `spextractor/`) need updating.
- Cluster: the in-tree OpenMS build needs the same manual edits as the last rename (`src/topp/executables.cmake`,
  `src/topp/CMakeLists.txt`, the tool namespace inside the patched `BrukerTimsFile.cpp`, then `cmake .` in
  the build tree), with the patch regenerated by `diff -u` against the pristine tree.
  `scripts/sync_cluster.sh`, `verify_publish.sh` and the chain scripts name the binary.

**Decisions to make.**
- Binary name: `diaspextractor`. Should `spextractor` remain as a compatibility link for one release?
- Environment variables: rename to `DIASPEXTRACTOR_*`, or accept both names for a transition? Chains set
  many of them.
- The mzML header stamp prefix `spx:` (13 keys, parsed by the bench tools) is not the tool's name.
  Keeping it means older outputs still read.
- Version: a changed binary name breaks users' scripts, so it belongs in a clearly flagged release.

**What stays.** Historical records (BASELINE, docs/reviews) keep the old name where they describe past
runs. The shared install root `/ceph/ibmi/abi/oliver/spextract` and the published arms keep their paths,
as after the last rename. Do the cluster part only when no chain is running.

## The repaired ledger, and what it exposed (2026-09-10, commit 4258d16)

**Closed 2026-09-23:** done: both items measured (PICK_BATCH -3.0 GB / +2.3% wall, not adopted; periodic trim -15.3% peak / +8.1% wall, shipped as a probe)

The three streaming-memory reviewers all refused to price allocator reclamation off the old
instrumentation. They were right; the repairs are in `4258d16` (phase nesting, the MS1 band
partition, the emitted spectra, MiB). Two things became visible immediately, both on dataset D
at the resident source, `instr3/resident_1tile`:

- **The MS1 band partition is 13.6 GiB and was reported as 0.6.** It is a full copy of the MS1 map
  plus a 1-5% halo, live from the distribution until each band's detection consumes it. The
  handover is exact in the ledger: `ms1_map` 13,830 -> 0 and `band_arena` 0 -> 13,579 MiB in one
  250 ms tick, then draining band by band. **MassTraceDetection's own internal copy of each band is
  still unattributed** and can only be charged by patching OpenMS.
- **The load accumulates ~17 GiB of allocator free list that a single `malloc_trim` returns at the
  end of it.** RSS runs 45,279 MiB at t=27.5 s and 28,052 at t=30.1 with the charged total
  UNCHANGED at ~26,500. So the process peak of the resident arm is not live data at all: it is one
  load's worth of retention, released a second later.

Two items follow, both D-class:

| item | status | what it is |
|---|---|---|
| MS1 staging batch A/B (`DIASPEXTRACT_PICK_BATCH` 16/32/64/256/512 on D, streaming, 3 tiles) | RUNNING (chain `ms1batch`) | zero code. `ms1_buf_` is 256 frames of raw peaks (3.8-4.8 GiB on D) and the loader holds its own copy behind it; both scale with the batch, and step 0b proved batch composition is output-invariant. The only question is the wall cost. |
| periodic `malloc_trim` DURING the load, not only at its end | NOT STARTED | ~5 lines under the existing `perf:malloc_trim` gate, every N batches. The env-var route (`MALLOC_TRIM_THRESHOLD_`/`MALLOC_MMAP_THRESHOLD_`) is already priced and rejected: step 0a measured -15.5 GB but +26% wall, because it changes the threshold for every allocation in the process rather than reclaiming at a few chosen points. |

### Harness: the contention measure of an extended cell counts the cell's own process (2026-09-17, found in the diaWeaver run)

**Closed 2026-09-23:** done 2026-09-23: the cause was killpg orphaning the tool to init (not start_new_session); kill_session now kills the wrapper's children first (cells pin 196c420d07ce)

`during.foreign_cores_mean` of a `dwv` cell record read 29.9 with a "peak60" of 16,220 cores, on a 128-core node whose
only other load was ~2 cores: the own-process-tree exclusion that works for the dt/spx arms (their `during` read 2.2)
misses a cell started with `start_new_session=True` (`run_capped`), so the cell's own threads are summed as foreign
CPU and every cell row is flagged `contended`. Fix: exclude by session id (or walk the children of the wrapper) in
`ArmMonitor`, and add a selftest case that runs a fake cell with a known CPU burn and asserts foreign ~ 0. Until
then, read the `during` flags of cell rows as meaningless; the dt/spx flags are unaffected.

## Restore precursor de-duplication, in its merging form

**Closed 2026-09-23:** done: released as the 1.4.0 twin fold (assembly:twin_im_tolerance)

`assembly:dedup_precursors` / `dedupPrecursors_` (`git show 9a6c2d4^:src/spextractor.cpp:2632-2668`) collapsed
precursor hypotheses that are the same species -- same charge, mono m/z within ppm, co-eluting, co-located in
mobility -- immediately after inference. It was pre-registered as a probable loss, **never run**, and removed on
2026-09-08 among options with no measurement on record. It now has one:
docs/SAME-POSITION-DUPLICATION-2026-09-20.md prices the drop form at -1.8% of peptides for -30% of spectra and the
*merging* form -- one precursor kept, the duplicate seeds' fragments folded in -- at **-0.5%** on Sage and -0.4% on
MSFragger, with entrapment FDR +0.03 points. 45.9% of inferred precursors have a same-monoisotope competitor.
Restoring it needs `Precursor_` to carry the merged members' trace indices so `assembleOne_` can correlate against
the summed XIC, placement relative to the IM charge veto (the historical code ran before it), and the same
predicate taught to the post-tile coverage assertion (src/diaspextract.cpp:4695-4711).

## Give the window loop the ownership rule the tile loop already has

**Closed 2026-09-23:** superseded: the 1.4.0 twin fold folds the seam duplicates; the cost of assembling them twice is unmeasured

Adjacent diaPASEF windows on PXD029836 overlap by exactly 1.00 m/z; precursor selection at
src/diaspextract.cpp:4554 takes `[win_lo, win_hi]` closed at both ends with no cross-window guard, so a precursor
in the seam is assembled twice. The tile loop immediately below has an exact ownership predicate and throws when
two tiles claim one precursor (:4565-4568). 13.2% of same-position twin pairs on that file
(docs/SAME-POSITION-DUPLICATION-2026-09-20.md).
