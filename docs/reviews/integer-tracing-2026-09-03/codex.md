## 1. Is the faithfulness claim credible?

No. Section 3 is not a faithful description of OpenMS `MassTraceDetection`, and the partial implementation already embodies several different scientific decisions. The contradiction is visible in the source itself: [detectTracesInteger_()](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:715) calls the algorithm both “a DIFFERENT ALGORITHM” and, eight lines later, a “FAITHFUL reimplementation.”

Legend below:

- **SET** — changes peak membership or whether a trace is emitted.
- **COORD** — may preserve membership but changes trace coordinates/profiles and therefore downstream gates.
- **ORDER** — only harmless ordering, provided traces do not compete for peaks.

| Difference | What OpenMS actually does | Effect |
|---|---|---|
| Termination mode | Default is `trace_termination_criterion="outlier"` with `trace_termination_outliers=5`; speXtractor never overrides it. Because the test is `consecutive_missed > 5`, termination occurs after six consecutive misses. [`MassTraceDetection` ctor](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:26), [`run_()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:540) | **SET.** The sketch instead stops on sample rate. |
| Role of `min_sample_rate` | Under the active default, it does not terminate extension. It is a final validity test in `isTraceValid_()`. [`isTraceValid_()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:445) | **SET.** The design’s central account of the algorithm is wrong. |
| Sample-rate semantics when explicitly enabled | OpenMS waits until a direction has visited more than five scans, then computes one combined rate from both directions plus the apex. It is not a fresh per-direction `hits/visited`. | **SET.** Especially different near gaps and asymmetric peaks. |
| Final sample-rate denominator | OpenMS uses `trace.size() / (total_scans_visited - terminal_misses_down - terminal_misses_up)`. Internal misses remain; trailing misses are removed. | **SET.** The sketch has no equivalent final check. |
| Direction scheduling | OpenMS alternates one downward frame and one upward frame, downward first, with both directions sharing the evolving centroid and variance. The sketch finishes `+1` completely before starting `-1`. | **SET.** The first side processed pulls the centroid and decides what is available on the other side. |
| Initial mass tolerance | `ftl_sd = centroid_mz * ppm / 1e6`, but acceptance is within `centroid ± 3*ftl_sd`: initially approximately ±3× the configured ppm. [`findBestPeak_()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:288) | **SET.** `tofSpan(..., mass_ppm)` implements about ±1× ppm. |
| Dynamic mass tolerance | `reestimate_mt_sd=true` by default. Every accepted peak updates `ftl_sd` from observed weighted dispersion. [`processPeak_()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:384) | **SET.** A fixed integer span is not equivalent. |
| Seed weighting | OpenMS initializes the centroid counters with the seed and then calls `updateIterativeWeightedMean_()` on the seed again. The extension centroid therefore behaves as though the seed has double weight. | **SET** near candidate boundaries. The sketch counts it once. |
| Centroid coordinate | OpenMS averages calibrated m/z doubles. The proposed detector averages TOF bins and rounds the centroid after each hit. Nonlinear, frame-dependent `mz(tof,b)` means these are not equivalent operations. | **SET.** |
| IM centroid | OpenMS maintains an intensity-weighted running 1/K0 centroid and gates around it. The sketch gates against `scan(seed)`, never a running mobility centroid. | **SET.** |
| Candidate versus `used` | OpenMS first chooses the closest-m/z candidate satisfying IM, then checks whether that one is visited. If it is visited, the frame is a miss; it does not take the second-closest unused candidate. [`findBestPeak_()` and `isPeakAcceptable_()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:288) | **SET.** The sketch explicitly chooses the closest unused peak. |
| Membership threshold | OpenMS removes all peaks with intensity `<= noise` before extension. [`run()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:216) | **SET.** The current integer `pick()` searches every slab peak, including below-noise peaks. [`pick` lambda](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:780) |
| Apex threshold | A peak is an apex only when `intensity > snr*noise`. Equality does not pass. | **SET**, minor but deterministic. The current integer code accepts equality because it breaks only on `< min_apex`. |
| When peaks become used | OpenMS collects provisional indices and marks them visited only after the entire trace passes length and sample-rate validity. [`run_()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:650) | **SET, severe.** The sketch/current code marks immediately and never rolls back an invalid trace, permanently deleting its peaks from later valid traces. |
| Singleton handling | With `min_trace_length=0`, an OpenMS singleton can pass if its final quality passes. The current integer detector unconditionally drops `xi.size()<2`. | **SET.** Relevant because MS2 min length defaults to zero. |
| Empty spectra | Empty spectra advance `scan_counter` but do not increment `consecutive_missed`; this matters differently to outlier termination and final quality. | **SET.** Treating every frame with no candidate as an ordinary miss is different. |
| Equal-intensity seed ordering | OpenMS uses ascending `stable_sort`, then reverse iteration. Equal intensities therefore seed in reverse original frame/peak order. The integer comparator uses `(intensity desc, tof asc, flat index asc)`. | **SET**, not merely order: seeding is greedy, so ties can change ownership. |
| Closest-peak ties | OpenMS keeps the first candidate in ascending m/z order because replacement uses strict `<`. Integer TOF rounding can collapse distinct m/z values onto one bin and introduces a different tie population. | **SET** in dense regions. |
| Drift cap | The proposed seed-relative centroid cap has no OpenMS equivalent. | **SET.** It may make banding easier, but it is a new detector definition. |
| Output coordinates | `toTrace()` reports apex/mean/median m/z as selected, intensity-weighted centroid RT, OpenMS centroid IM, and max intensity. [`toTrace()`](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:293) | **COORD.** Current integer code reports apex RT and treats `median` as mean. These values control downstream RT, IM and isotope gates. |
| Valley splitting | The OpenMS path invokes `ElutionPeakDetection` inside `detectTraces_()`. [`detectTraces_()`](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1373) | **SET.** The integer branch currently bypasses it entirely at [the window dispatch](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2969). |

There is also a direct profile-corruption bug in the partial implementation: it sorts `xi` before pairing it with `xv`, so intensities are attached to the wrong frames. [`detectTracesInteger_()`](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:841). That will change correlations even if trace membership happens to be right.

Bottom line: none of the disputed differences can safely be dismissed as “only order,” except the eventual order of traces that are demonstrably peak-disjoint. Equal seed or candidate ties are not order-only in a greedy consumed-peak algorithm.

## 2. Is the mobility-axis derivation sound?

No. Ranking distinct 1/K0 values is not a generally valid recovery of native TIMS scan IDs in this pipeline.

It works only if all of the following hold simultaneously:

1. Every native scan in the relevant absolute scan interval is represented by at least one surviving peak.
2. Every surviving mobility value is exactly a native scan coordinate.
3. No two native scans collapse after float or `uint16` quantization.
4. The ranking covers the same absolute scan range in every compared frame.
5. The input has not been centroided, clustered, aggregated or re-binned.
6. Comparing equal scan numbers across frames is scientifically intended despite frame-dependent TIMS calibration.

The actual path violates several of these:

- `PeakPickerIM::pickIMCluster()` outputs an intensity-weighted mean mobility for each cluster, not a native scan coordinate. See the weighted `sum_im_intensity / sum_intensity` in [`pickIMCluster()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/PROCESSING/CENTROIDING/PeakPickerIM.cpp:1173). After this operation, distinct mobility values are cluster centroids, not scans.
- Empty scans and scans whose peaks were filtered are absent. Ranking compresses those gaps.
- Each MS2 window contains only its acquisition scan slice. Rank zero therefore means `ScanNumBegin`, not native scan zero. MS1 uses a different/full range. Local MS1 and MS2 ranks are not comparable without absolute offsets.
- Post-picking `aggregateFrames_()` forms weighted mobility centroids across frames, making rank recovery still less meaningful.
- `uint16` quantization can merge close values.
- A physical analyte is defined by calibrated mobility. If calibration drifts, the same physical 1/K0 can move to a different raw scan. “The scan does not drift” is not automatically an advantage; it may mean calibration correction was discarded.

Even with true scan IDs, one target-frame `scan_tol` does not correct calibration offset between the seed frame and target frame. You would have to map the trace’s calibrated mobility into the target frame’s scan coordinate. Subtracting two scan numbers and applying a width only corrects scale, not offset.

The current `indexScans()` has two additional defects:

- It stores one worst-case tolerance per frame even though the scan-to-1/K0 spacing can vary with scan position.
- `hi - i` includes the current value, but the later comparison treats that count as an allowed rank difference. It is at least one rank too permissive. [`indexScans()`](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:685)

### Cheap real-data check

For a sampled frame from every window:

1. Before peak picking, retain the distinct raw 1/K0 grid and native scan IDs.
2. Require `native_scan_id = constant ± rank` for every observed value, with no internal missing scan IDs across the declared `ScanNumBegin..ScanNumEnd`.
3. After picking, require every emitted mobility to equal one value on that raw grid.
4. Repeat for MS1 and MS2 and verify absolute offsets, not merely equal distinct counts.

The Bruker reader already has `scan_ids` before it emits calibrated mobility and discards the IDs. [`BrukerTimsFile::loadDIAStreaming()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FORMAT/BrukerTimsFile.cpp:1465). This diagnostic is therefore cheap.

Without native IDs, checks such as distinct-count stability, repeated-value multiplicity and `IM_PROFILE` versus `IM_CENTROIDED` are useful rejection tests, but they cannot prove that a rank is an absolute scan number. Missing native scans are unrecoverable from ranking alone.

When validation fails, keep the existing `uint16 imq` and compare quantized 1/K0 directly. It is already an integer representation and preserves the current physical axis to much better accuracy than the 0.01 tolerance. Do not silently substitute ranks. An explicitly requested native-scan mode should fail closed unless actual scan IDs and their calibration mapping are available.

## 3. Is the estimate honest?

No. It is plausible that arrays help substantially, but 30–50% is not supported by the accounting presented.

First, materialisation is not inside the reported 3,869-second trace number. The window loop times `materializeWindow()` into `t_mat` and starts `t_trace` afterwards. [`window timers`](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2924), [`stage report`](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3230). Given 90.9% trace and 4.8% score, materialisation plus grid and emission together occupy at most the remaining 4.3% of that reported subtotal.

Therefore:

- Removal of `materializeWindow()` cannot produce 30–50% off `t_trace`.
- “No materialisation” and “no double-conversion pass” are the same saving, not two independent terms.
- Any 30–50% trace improvement must come from inside detection: eliminating OpenMS’s second filtered `work_exp` copy, reducing the working set, or doing less extension work.

There is some legitimate opportunity inside OpenMS. `MassTraceDetection::run()` builds another `PeakMap`, filters each spectrum with `select()`, builds the apex list and sorts it before extension. [`MassTraceDetection::run()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:216). A direct-array implementation can remove that copy.

But the candidate lookup itself is already two m/z binary searches followed by a short tolerance-window scan. [`findBestPeak_()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:288). The proposed lookup is not an algorithmic breakthrough over that.

The current partial implementation also adds costs omitted from the estimate:

- `PeakSlab` is 12 B/peak because it retains both `imq` and `scan`, not 10 B.
- Every band allocates a full-size `frame_of` and byte-per-peak `used` array and scans the entire slab. Twelve concurrent bands multiply that overhead.
- `vector<char> used` is eight times larger than OpenMS’s bitset.
- `indexScans()` sorts mobility values in every frame.
- Each band has an independent `used`, permitting the same halo peak to participate in traces owned by different bands.
- EPD is omitted, so any apparent current speedup is contaminated by deleted work.

The wall-time projection is also unexplained. If the summed stage times scaled proportionally, 30% off a 90.9% component would reduce the window subtotal by 27%; 50% would reduce it by 45%. From 7:04 that suggests roughly 5:08 down toward 3:51 before fixed phases, not “5:00–6:00.” Because these are per-window elapsed times summed across concurrent tasks, the conversion to wall time needs a critical-path or per-window model.

The 15% threshold is acceptable as a business go/no-go, but it is not a falsifier of the layout hypothesis:

- A faithful 12% speedup could still prove layout mattered while missing the chosen ROI.
- A 30% speedup could be entirely bogus because the implementation terminated earlier, consumed invalid traces, skipped EPD, or admitted below-noise members.
- Memory reduction may be valuable even below 15%, depending on how it changes window concurrency.

One measurement already separates materialisation from detector layout: `t_mat` versus `t_trace`. For the remaining decision, split the existing `t_trace` timer once into:

1. band partition plus `MassTraceDetection::run`;
2. EPD;
3. `MassTrace`→`Trace` conversion/instrumentation.

Run that on dataset D with the current baseline. If MTD proper is not at least about two-thirds of the 3,869 seconds, a 30–50% reduction of the whole trace stage is not credible without also optimizing EPD. If MTD proper dominates, an exact-semantics array prototype is justified.

## 4. What will this break?

Ranked by likelihood × severity of silently changing output:

| Rank | Risk | Expected output symptom |
|---:|---|---|
| 1 | Wrong termination/tolerance semantics: outlier versus sample-rate, ±3σ and re-estimation versus fixed ppm, alternating directions versus sequential | Large changes in trace count and length distribution; gappy traces disappear or over-extend; merged chromatographic modes; different apexes and peptide sets. |
| 2 | Immediate `used` marking with no rollback, plus “closest unused” instead of OpenMS’s visited-candidate miss | Missing traces around dense m/z regions; strong seed-order sensitivity; later real traces vanish because an invalid provisional trace consumed their peaks. |
| 3 | Mobility ranks are not native scans and are not comparable across MS1/MS2 slices | Frame- and window-dependent IM offsets; genuine fragment traces fragment; unrelated peaks merge; precursor–fragment IM gates fail asymmetrically across windows. |
| 4 | Picked m/z is not necessarily a native TOF bin | `PeakPickerIM` also creates intensity-weighted m/z centroids. Rounding those to `tof` loses sub-bin centroid information. Expect ppm-residual broadening, changed isotope linkage and boundary-dependent trace membership. |
| 5 | EPD, aggregation and estimator options are bypassed | Long multimodal traces remain unsplit; `trace:frame_aggregation_n` silently does nothing; `trace:mz_estimator=median` behaves as mean. Output spectra become less coherent even if raw trace counts rise. |
| 6 | Wrong trace coordinates and profile association | Current `xi`/`xv` mismatch produces shifted or scrambled XICs, lower correlations, wrong apex RTs and apparently plausible but chemically incoherent spectra. |
| 7 | Band ownership is not equivalent to a shared `used` set | With per-band `used`, the same physical peak can appear in multiple traces. With shared `used`, it becomes a race. Symptom: trace and peptide sets change with `perf:trace_bands` or thread scheduling. |
| 8 | Frames are not explicitly RT-sorted on the integer path | The OpenMS path calls `wmap.sortSpectra()`; the slab path trusts arrival order. Non-streaming or alternate-converter input can produce backward/jumping profiles and incorrect gap termination. |
| 9 | Calibration/frame-ID association | `frameIdOf()` may return zero or an archive index; `TofAxis::factor()` silently substitutes the reference factor rather than rejecting it. Symptom: RT-dependent mass drift, trace splits and wrong exported m/z despite “exact” calibration. |
| 10 | Seed and nearest-peak tie ordering | Equal-intensity or equal-TOF populations are assigned differently. Symptom: deterministic but band/input-order-dependent swaps between neighboring traces. |
| 11 | Mobility tolerance conversion | One worst-case `scan_tol` per frame and the off-by-one make the gate systematically too wide in much of the ramp. Symptom: broader IM traces and more chimeric precursor–fragment assignments. |
| 12 | Integer narrowing and missing invariants | `frame_off` and flat peak indices are `uint32_t`; no overflow or per-frame sortedness assertions exist. Symptom: only large windows silently point into the wrong frame ranges or make binary search miss candidates. |
| 13 | Peptide-only validation | Search engines can hide dropped traces, duplicate spectra, wrong XICs and isotope-shifted precursor masses. Symptom: “same peptide set” despite materially different emitted spectra and reduced robustness on another engine/sample. |

Of the four risks listed in the design, mobility ranking and `min_sample_rate` are correctly recognized but substantially understated. Seed order is medium rather than top-tier. A shared-`used` race is avoidable and currently not the principal problem; independent band-local ownership and invalid-trace consumption are more immediate.

## 5. Sequencing

Do not combine layout, native TOF, reconstructed scan IDs, new termination and new banding into one experiment. The right order is:

1. **Freeze and rebuild the current baseline.** The working tree already contains a partial integer implementation. Confirm the default OpenMS path still builds and reproduces the 7:04 result, exact invocation, stage totals, trace counts and both-engine peptide sets.

2. **Measure the ceiling before more implementation.** Split `t_trace` into MTD, EPD and conversion as described above. This requires no calibration work. Stop the project if MTD proper is too small to repay the refactor.

3. **Test the two native-axis premises independently.**
   - For mobility, compare raw scan IDs against ranks before and after picking. Expect post-picking rank recovery to fail.
   - For m/z, measure the residual `abs(mzToTof(picked_mz)-round(...))` before rounding and the resulting ppm error after round-trip.
   - Validate every `frame_id` against the TDF rather than using the reference factor.

4. **Build a semantic oracle from OpenMS.** Synthetic cases must cover: six consecutive misses, internal versus trailing gaps, invalid-trace rollback, used nearest candidate with an unused second choice, equal intensities, equidistant peaks, empty spectra, asymmetric peaks, dynamic SD, running IM centroid, singleton MS2 traces and max-length rejection.

5. **Implement the layout experiment on the existing axes first.** Use the current `mzq` and `imq` arrays, with double running centroids where necessary, single band, and exact active OpenMS semantics. This isolates SoA/cache/work-copy effects without introducing TOF or scan-rank science changes.

6. **Preserve the entire postprocessing contract.** Run EPD, preserve aggregation behavior, all m/z estimators, length options and output centroid definitions. Unsupported options must fail loudly; they must not silently no-op.

7. **Compare one representative window before parallelization.** Record peak-membership mapping, trace count, length, gap rate, apex/centroid coordinates, EPD split count and elapsed time. Peptide identity is a later gate, not the only correctness oracle.

8. **Then add bands/tasks.** Partition once using density/quantile edges; do not rescan and allocate full-slab state per band. Test `bands=1, 2, 12, 24` for trace-set stability. Keep the existing OpenMS path available as the A/B reference.

9. **Run dataset D and dataset A with both engines and entrapment/FDR.** Report MTD, EPD, materialisation, RSS, critical-path wall time, emitted spectrum count and trace-level deltas separately.

10. **Only after layout pays, try native TOF as a separate scientific A/B.** First make `loadTofAxis()` actually executable in the production build and reject unknown frame mappings. Do not describe this step as data-structure-only.

11. **Try native mobility scans only if actual IDs are retained and calibrated.** Ranking post-picked values should be skipped.

Steps that can be skipped entirely:

- Mobility-rank reconstruction; keep `imq`.
- Integer MS1 detection until MS2 is proven—MS1 is not the measured bottleneck and changes precursor discovery.
- A 2-D scoring index; scoring is now 4.8%.
- The seed-relative drift cap and “exact by construction” banding; both change the detector.
- Native TOF conversion if the `mzq`/`imq` layout-only prototype fails the ROI threshold.
- The whole refactor if the MTD/EPD split shows extension proper is not the dominant part of `t_trace`.

Verdict: a faithful array-layout prototype is worth one bounded experiment because the bottleneck and prior gate result justify it. The current all-three-native-axes plan is not faithful, its mobility premise is false for the actual picked data, and its present implementation cannot produce a trustworthy performance result.