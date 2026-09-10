# dnoise in SpeXtractor: decision and plan

> **Corrections, 2026-09-10 (stage1-measurement.md in this folder).** Measured on raw MS1 frames: the streak
> clustering reformulation in section 3 removes strictly MORE than the per-point definition, so it is not an
> equivalent cheaper design; the "every picker singleton is a run of length 1" lemma in section 4 fails on
> TNBC 009, so the surviving-map bound is not a bound on the long file; 201.9 M centroids is 3,851 MiB, not
> 4,038; removal is a monotone staircase in intensity (kill rule 4 fails at the raw-point level); and the
> real dnoise v0.1.0 defaults are ±3 TOF, two iterations, halo ON and both MS1 gates on.

## 1. The verdict in five lines

1. **Do not ship a dnoise filter now. Ship its predicate as instrumentation first** — one count-only pass that changes no byte of output and prices the whole proposal.
2. **If it is ever built, build it in the loader** (`frameToSpectrum`, on the integer (scan, TOF, intensity) triples before m/z conversion), MS1 only, stage 1 only. Halo off, MS2 off, `.d` rewrite never.
3. **Worth, memory:** the MS1 map falls 13,830 → **≤ 4,038 MiB** (arithmetic below, not the paper's rate) — but **0 GB at the shipped default**, whose peak is `loop1` at 40,299 MB with the MS1 map already released. It converts the 6-tile arm 31,031 → 23,463 MB (−24%) and only then makes tiling a real memory lever (40.3 → 23.5 GB, −42%).
4. **Worth, time:** −8 to −15 s of a 158.8 s run (−5 to −9%), and **negative** if emission rises: the window loop is 110.2 s / 6,935 CPU-s = 75% of the run, and the two closest prior experiments both raised emission 31% and 620%.
5. **Risk:** at the counting limit occupancy *is* intensity, and three cascades (MS1 `min_sample_rate` → trace deleted; break-on-first-miss isotope walk → `require_isotope_support` deletion; run-global `fitLine`) turn one deleted point into a lost precursor — in exactly the low-abundance stratum that is the entire identification deficit.

---

## 2. What is genuinely new versus what the tool already does

**Already covered (do not reimplement):**

| dnoise element | already in the tool |
|---|---|
| an m/z-channel definition | `pickIMCluster` whole-cluster span cap at `trace:mass_error_ppm` = 15 ppm (`spextractor.cpp:3486-3487`) |
| no absolute intensity floor in the decision | the picker has no floor at all (only `sum_intensity > eps`) |
| point-count reduction | picking removes 21.8% of MS1 and 18.6% of MS2 raw points — by **merging** |
| geometric gate, MS2 half | the loader already slices each MS2 frame to its window's 1/K0 band (`BrukerTimsFile.cpp:1494`, `:2310`); dnoise stage 3 is a no-op on MS2 here |
| occupancy on the **RT** axis | `trace:min_length_sec` 3.0, `ms1_min_sample_rate` 0.5, valley splitting |

**Genuinely additional — all of it:**

1. **Run length on the scan axis.** There is no contiguity concept anywhere in the tool. `pickIMCluster` has no minimum member count, no run, no gap rule; a single-scan hit is promoted to a first-class centroid, indistinguishable from a 40-scan streak's centroid. Occupancy is destroyed at emission (integer/string arrays cleared, `PeakPickerIM.cpp:1206-1207`), so the criterion **cannot** live downstream of the picker.
2. **Deletion instead of merging.** These are orthogonal operations on disjoint populations.
3. **The MS1 half of the geometric gate.** No MS1 point is ever dropped for lying outside the isolation-window table; `w.im_lower`/`w.im_upper` are never read by the tool at all.
4. **Off-column (halo) suppression.** Nothing resembling it exists.

One anti-overlap worth stating: the picker's `delta_im` = 0.01 span cap *partitions* a real streak into ~7-9-scan pieces, so it works against dnoise's premise. A filter running upstream on raw scan indices sees the streak whole and is unaffected.

There is also a dead seam already in the loader: the 3×3 (m/z × IM) neighbour denoiser (`ms1_min_support = 0`, `dia_ms2_min_support = 1`, active only under `dia_ms2_n_neighbors > 0`, which SpeXtractor leaves at 0). It is a 2-D *support* test, not a 1-D *run-length* test — not dnoise stage 1, but the proof that the loader is the right layer.

---

## 3. The design

**Placement: the loader, not the consumer.** In `BrukerTimsFile.cpp:1027` `frameToSpectrum`, between `TimsFrame::save_to_buffs` and the `Peak1D` build. Reasons, in order: the **exact scan index is already computed there and thrown away** (no dense-rank reconstruction, which collapses gaps and makes `max_internal_gap` vacuous); the triples are already CSR-ordered (scan asc, TOF asc within scan) so the filter is one linear sweep; TOF indices are integers so the neighbourhood is dnoise's own **bin** window, not a ppm window that would be 2.4× wider at m/z 1700 than at 300; and deleted points never pay for `tof2mz`, `scan2inv_ion_mobility`, `Peak1D` construction, `sortByPosition`, the ~88 B/point picker transient, the consumer's raw batch, or a `PeakMap` slot.

**The sweep (stage 1).** Maintain a TOF-ascending list of active streaks; per mobility scan, merge that scan's ascending TOF list against it within ±`tof_window` bins; retire a streak unseen for more than `max_internal_gap` scans; count **distinct occupied scans** per streak (dedupe — there are ~1.7 points per occupied TOF column); keep a point iff its streak's occupancy ≥ `min_feature_length`. Active list ≈ 690 points/scan × 3 ≈ 24 KB, L2-resident. Re-emit merged streaks with a bounded insertion sort, never `std::sort`.

Known divergence from the paper, to be documented as such: this is a **clustering** reformulation of a **per-point window** predicate. They agree exactly on isolated points (the entire prize) and can differ only in crowded columns, which pass both. Consequence: `iterations > 1` is vacuous here — strictly more conservative than dnoise.

**Stage 3 (geometric).** Requires hoisting `readDIAWindows(db, …)` (currently `BrukerTimsFile.cpp:1425`, after the MS1 loop) above the MS1 loop. Predicate = **union over all `DIAWindowRow`s** of (m/z band ± pad) × (1/K0 band ± pad), keyed by (group, window) — never a per-m/z lookup (`BASELINE.md:1114-1121`: one m/z window acquired in two groups with shifted scan ranges).

**Traps that must be in the first commit:**
- `frameToSpectrum` returns early on `num_peaks == 0` **before** attaching the IM array (`:1038`). A frame the filter empties must still emit an empty `FloatDataArray` with `setIMUnit(VSSC)` + `IM_PROFILE`, or the streaming reader keeps the frame and the resident reader drops it (`spextractor.cpp:3697`, `:3712`) and the MS1 frame grid diverges by reader. Array name stays "Ion Mobility".
- **mzPeak input:** the filter lives in `BrukerTimsFile.cpp`, so every `dnoise:*` option would be silently inert on `.mzpeak` (`MzPeakStreamLoad.h:226-247` builds the same MS1 spectra independently). **Hard-error** on `.mzpeak`/`.mzML` input when the filter is enabled. Do not approximate.
- Patch regeneration: `diff -u` against `.orig`, never `git diff` (cluster OpenMS is not a git tree). Do not publish during a chain.

**Options and defaults** (registered in `spextractor.cpp` next to `trace:native_ms1_neighbors`, mirrored into `BrukerTimsFile::Config`; every flag registered with an explicit default and included in the defaults audit):

| option | default | rationale |
|---|---|---|
| `dnoise:ms1` | `off` \| **`count`** \| `on` — ships as `off`, lands as `count` | `count` computes the mask, logs, and never compacts: digest must stay `8c1b047f` |
| `dnoise:ms1_min_feature_length` | 5 | paper |
| `dnoise:ms1_max_internal_gap` | 2 | paper |
| `dnoise:ms1_tof_window` | ±2 **bins** | ±12.8 ppm at m/z 600, ±7.6 at 1700 — below the picker's 15 ppm span cap, so the filter can never fuse populations the picker keeps apart; bins, not ppm, so the paper's numbers transfer |
| `dnoise:ms1_geometric` | `off` | separable, different risk profile, own arm |
| `dnoise:geometric_pad_mz` | **10.04 Da** | the seed can sit 5 isotope steps above the mono *and* `findPartner` walks 5 more from the seed (`:2782`, `:2809`); with `charge:min_charge = 1` the reach is 10×1.00335. Refuse to start below this. |
| `dnoise:geometric_pad_im` | **0.10 1/K0** | 2 × `charge:iso_im_tolerance` (0.05), same doubling argument |
| `dnoise:halo_peak_fraction` | **0.0 (off)** | see §5 |
| `dnoise:ms2` | **off, and not built** | pre-falsified, §5 |

Instrumentation is not optional: extend `g_perf_load` with `ms1_dnoise` seconds and `ms1_raw`/`ms1_kept`/`ms1_gated` counters on the `[perf-load]` line. Without the kept/raw ratio in the log a no-op filter is indistinguishable from a working one.

---

## 4. The expected win, with arithmetic

**The tight bound nobody has stated.** With `P` = 927 M raw MS1 points and `C` = 725,116,915 picked centroids, singleton clusters `n1 ≥ 2C − P = 523.2 M` (56.4% of raw points, ≥72.2% of centroids). A picker singleton is by definition a point with no other point within 15 ppm and 0.01 1/K0 — i.e. no neighbour within ~7-9 scans — so it is a run of length 1 under any (±2 bin, gap ≤ 2) criterion and stage 1 deletes it. Therefore:

> **surviving MS1 map ≤ P − C = 201.9 M centroids = 4,038 MiB.** MS1 map **13,830 → ≤4,038 MiB, −9.8 GiB**, from stage 1 alone, without borrowing the paper's 91-94% (which is all three stages).

Caveat: the picker closes an expansion side on the first failing *unused* candidate, so a small number of singletons may have had a blocked eligible neighbour; and the 927 M raw figure has one consistency check, not a measurement.

**Process peak — the part that kills the memory case at the default.** Measured (dataset D, spock, `SPEXTRACTOR_LEDGER`):

| arm | wall | peak RSS | where the peak is | `ms1_map` at the peak | win from a perfect MS1 filter |
|---|---:|---:|---|---:|---:|
| `stream_1tile` (**shipped default**) | 2:26.67 | 40,299 MB | `loop1`, t=88.6 s | **0 MB** | **0 MB** |
| `resident_1tile` | 2:33.63 | 46,272 MB | `start`, t=26.6 s | 13,830 | → 41,992 (tile1 floor), −4,280 |
| `stream_3tiles` | 2:57.14 | 30,920 MB | `start`, t=9.5 s | 10,508 | → loop floor ≈ 22-23 GB |
| `stream_6tiles` | 2:48.05 | 31,031 MB | `start`, t=9.1 s | 10,508 | → **23,463** (`loop5`), **−7,568 MB, −24.4%** |

So the honest headline is not "−12 GB": it is **the MS1 pass stops being the floor**, which is precisely what today prevents tiling from buying anything (3 and 6 tiles have the same 31.8 GB peak). The compound claim is the real one: **filter + 6 tiles = 23.5 GB against today's default 40.3 GB (−42%)**.

**CPU** (same arm, 158.8 s total): `LOAD(stream)` 10.2 s / 682.7 CPU-s; `MS1_TRACE` 13.9 s / 201.5 CPU-s; `PRECURSOR_INFER` 3.7 s / 57.9; `WINDOW_LOOP` 110.2 s / 6,935.4. Filter cost ≈ 20 ns/point × 927 M = 19 CPU-s (74 at 4× pessimism) = 3-11% of the phase it sits in. At ~20% survival, LOAD(stream) → ~4-5 s wall. `MS1_TRACE` is **unpredictable**: `MassTraceDetection` copies only peaks above `trace:noise_threshold_int` = 100 into `work_exp` and seeds above 300, and **the fraction of the 725 M picked MS1 peaks above 100 has never been measured**. Net: −8 to −15 s (−5 to −9%) if emission is unchanged; the window loop is 75% of the run and untouched by an MS1-only filter — unless emission rises, at which point a 10% rise costs +11 s and the change is net slower.

MS2, for reference only (not being built): slab 1,258,053,975 × 10 B = 11,997 MiB; same arithmetic gives surviving ≤ P − C = 286.9 M = 2,736 MiB. That is where the remaining memory is, and it is the half the evidence forbids.

---

## 5. Science risk and the gate that settles it

**The mechanism, stated concretely.** At high counts a peptide's mobility peak is 11-22 scans FWHM and `min_feature_length = 5` is nowhere near it. At the counting limit the ion does not shrink, it **fragments**: a shoulder frame carrying a few tens of counts over ~30 detector cells registers 4-6 scattered hits with gaps of 3+, and is deleted whole. Three cascades then amplify one deleted point into a lost precursor:

1. **`min_sample_rate`.** `MassTraceDetection` computes `trace.size() / (visited − trailing misses) ≥ 0.5`. Interior losses are pure poison. A median MS1 trace is 15.2 s at a 1.34-1.63 s cycle ≈ 9-11 frames; losing 5 interior members deletes the trace outright, and the repo already records that most MS1 traces have gaps.
2. **Break-on-first-miss isotope walk** (`:2783`, `:2810`). One lost partner truncates the envelope, not shortens it; `n_isotopes == 1` → `guessed` → deleted by `assembly:require_isotope_support` (default true) — a second occupancy gate whose own cost is unquantified.
3. **Run-global `fitLine`** (`:3993-4039`): a changed precursor population moves a, b and σ and flips z=1→z=2 calls at m/z nowhere near any deleted point. z=1 is the emission lever with its own ~2.8% entrapment stratum.

And "MS1-only is a memory change" is false: the Pearson's precursor profile **is** the MS1 seed trace (`:3113`), so one lost MS1 frame decrements `overlap` for **all** of that precursor's fragments at once, against hard cliffs at `gate:min_correlation_points = 3` and `assembly:min_fragments = 3`.

The peptide therefore moves from *emitted but not identified* to *not emitted* — a regression on the one axis measured **not** to be the problem (~87% of missed peptides are emitted, decoy floor 16.0%, positive control 0.9%). **And the release gate cannot see it:** deleting marginal true IDs *lowers* the entrapment FDR, so `entrapment ≤ base + 0.3` reads green on the failure mode; and `perf:ms1_trace_bands` 12→48 moved MSFragger by 1.0203 on data-derived quantiles alone, so a ±2% claimed effect sits inside a ±2% partition-noise floor that this filter re-triggers by deleting 56-90% of the map the quantiles are drawn from.

**Halo stays off, against the paper.** A 0.15 relative floor against a neighbouring column's max is a dynamic-range gate: it deletes any ion >7× weaker than a near-isobaric neighbour at the same mobility. Isotopes are safe (1.00335 Da ≈ 262 bins at z=1 vs a ±8-bin box); co-eluting weak peptides are not. Nobody here has looked for MCP saturation halos in these files.

**MS2 mode is pre-falsified and should not be built.** The ~2 missing fragment ions per faint spectrum are "peaks that never become a trace (single-frame or sub-SNR)", and backfilling the 50 most intense **untraced** raw MS2 peaks moved MSFragger 11,927 → 12,539 (+5.1%), converting 1,151 reference-only peptides to shared. It was rejected on a −2.6% Sage cost and a cross-file sign flip, **not** because the peaks were noise. `dnoise:ms2` deletes that population by construction. Add that an MS2 window spectrum is only a ~150-270-scan slice, so truncated streaks are punished for the truncation, and `trace:ms2_min_sample_rate` is measured binding in the losing direction.

### The sweep

Full-gate arms are expensive (2 datasets × 2 engines × entrapment). **Sweep in simulation, gate three configurations.**

**Phase A — simulation, free, no output change.** One count-mode run computes every run length once; re-threshold offline. Grid: `min_feature_length ∈ {3,4,5,6,8}` × `max_internal_gap ∈ {1,2,3}` × `tof_window ∈ {±1,±2,±4}`. Per cell report: raw removal %; picked-centroid disappearance % by intensity decile (pick each MS1 frame twice, filtered and unfiltered, match within 15 ppm / 0.01); **simulated trace survival** for the 13,491 Sage-identified precursors after re-applying `min_sample_rate` 0.5, `min_length_sec` 3.0 and the >5-consecutive-miss stop to post-filter membership; and the same at a +7.3 m/z decoy offset.

**Phase B — D-class.** `dnoise:ms1=count` digest-identical on **both** pins (`8c1b047f`, `bff54a1f`).

**Phase C — S-class, exactly four arms:**
1. **band-edge control** (filter off, `perf:ms1_trace_bands` 47/49 or subsample stride 89) — establishes the churn floor everything else is read against.
2. **geometric only** (pad 10.04 / 0.10), plus a pad×2 arm that must be output-identical (if it is not, the padding derivation is wrong and the gate is invalid).
3. **streak at the paper point** (5 / 2 / ±2), geometric on.
4. **streak at the most permissive setting from Phase A that still removes ≥50% of raw points.**

Each arm reports, on D **and** TNBC 009, on Sage **and** MSFragger: peptides; entrapment **stratified by charge**, not pooled; emitted-spectrum count; the **matched emitted-vs-missed split** (`bench/coverage.py` shape) — the only readout that can see "emitted → not emitted"; the `n_isotopes` histogram and guessed/kept counts; `fitLine` a/b/σ and the z=1 fraction.

**Abandon if any of:**
- Phase A: **>2%** of currently identified precursors lose their MS1 trace, or **>10%** in the bottom intensity decile.
- Phase A: identified and decoy run-length distributions **overlap** in the bottom intensity decile — occupancy then has no discriminating power at the abundance that matters, and no parameter choice can rescue it.
- Phase A: stage-1-alone removal **<50%** of raw MS1 points (the prize does not justify an S-class gate, given the win is 0 MB at the default).
- Phase A: centroid disappearance rises **monotonically** toward the low intensity decile rather than being flat.
- Phase C: any arm loses **>1%** on either engine on either dataset *beyond the band-edge control floor*; or entrapment exceeds base + 0.3 in **any** charge stratum; or the emitted-fraction-of-missed falls below ~85%; or spectra count rises **>5%** (the over-generation signature that cost +18% wall when the smoother was removed).
- Halo is enabled only if Phase A shows it removes >2% of stage-1 survivors **and** flat across deciles; then 0.15, then 0.05; otherwise never.

---

## 6. Order of work

**M1 — the one run that predicts the outcome (do this before writing any filter).** A single instrumented pass 1 + MS1_TRACE (`SPEXTRACTOR_LOAD_ONLY`-shaped, no output, ~25 s of a 158 s run) that prints:

1. **The intensity histogram of the 725,116,915 picked MS1 peaks against 100 and 300.** Never printed. It sets the CPU prize (`MS1_TRACE` = 201.5 CPU-s only moves if the map is mostly above 100), the intensity-shift risk, and whether the whole story is memory-only.
2. **Stage-1 removal fraction of raw MS1 points**, plus the run-length histogram, so the ≤4,038 MiB bound becomes a measurement.
3. **The raw-point fraction outside the padded window union** — the size of stage 3, currently proxied only by `never_in_window` = 6.64% of *precursor hypotheses*, which is not a point count.
4. **Double-pick centroid disappearance by intensity decile**, with the decoy offset — the falsifier.
5. **TNBC 009 raw and picked MS1 counts**, which have never been logged; the repo's two figures (2.392e9 vs 1.4-2.1e9) disagree and one is back-derived from an RSS milestone.

Then: **M2** count mode digest-clean on both pins (D-class) → **M3** geometric gate only, S-class with the control arm → **M4** streak filter, only if M1 passed the kill rules. Effort, honestly: M1 2-3 days; M2 3-5 days plus 1-2 for the patch/rebuild/publish cycle; M3 3-5 days elapsed on contended nodes; M4 a further 1-2 weeks. **2.5-4 weeks for an MS1-only default. "A week" is the filter body alone.** Do not start MS2.

**The competing lever that must be priced in the same breath:** the MS1 map is 20 B/peak and ≥72% singletons, while the MS2 slab is 10 B/peak; and MS1 tracing is the one pass that is still whole-run while detection is already cell-atomic. Compacting or cell-tiling pass 1 buys the same 13.8 GB with **no** science risk beyond cut lines already accepted. If M1 shows most of the map is below `noise_threshold_int`, that route dominates dnoise outright.

---

## 7. Attribution and licence

dnoise is MIT and open, but **nothing is copied**: this is an independent reimplementation from the published description, in a different language, at a different layer (in-memory, on decoded frames — not a `.d` rewrite), with a different formulation of stage 1. MIT's attribution clause therefore does not attach; attribution is owed as scientific credit, and should be given generously and precisely:

- **Option docstrings** (`dnoise:*`): "Reimplementation of the ion-mobility streak filter of Garrett, Diedrich & Yates III, *dnoise: Fast Native Data Reduction for Bruker timsTOF*, bioRxiv 2026.08.27.747603 (MIT, github.com/pgarrett-scripps/dnoise). No dnoise code is used." Keep the parameter **names and default values** identical to the paper's so results are comparable.
- **`docs/` and `CHANGELOG.md`**: an acknowledgement plus an explicit **divergence list** — (a) streak-clustering rather than per-point window, so `iterations > 1` is vacuous and this removes strictly no more than dnoise; (b) applied in-memory after decode, so `Frames.NumPeaks` and the frozen frame tables are untouched (a `.d` rewrite would silently move the RT grid every Pearson is computed over, invisibly to the `[frames]` invariant); (c) MS1 only, halo off, MS2 not implemented; (d) `.d` input only. Anyone comparing our removal fractions to the paper's must be able to see immediately that they are not the same configuration.
- **`ACKNOWLEDGEMENTS`/`NOTICE`**: name the authors, the paper, the repository and the MIT licence.
- **Any publication**: cite the paper. If a single line of dnoise source is ever ported, the full MIT licence text goes in `LICENSES/dnoise-MIT.txt` and the file carries the copyright header — but do not port; the reimplementation is cheaper than the audit.
- Do **not** describe the tool as "using dnoise" or "dnoise-compatible" anywhere. It reimplements one of three stages, with a documented behavioural difference.