1. **CHANGELOG.md / supplied source excerpt — “the tool reports its own version (`--help`…)” — HIGH in the supplied implementation; resolved during review.** Setting only `version_` leaves OpenMS’s cached `verboseVersion_` unchanged; `printUsage_()` prints that cached value. The workspace constructor was updated during this review to set both fields, so this defect no longer exists in the current constructor.

2. **[README.md](/Users/kohlbach/Claude/speXtractor/README.md:24), CMakeLists.txt — “without [OpenMP] the tool runs single-threaded” — HIGH.** The source unconditionally calls `omp_set_schedule`, references `omp_sched_static`/`omp_sched_dynamic`, and calls `omp_set_num_threads`. A genuinely non-OpenMP build lacks the required declarations/linkage. Additionally, the fallback `SPEXTRACTOR_VERSION` definition is incorrectly inside `#ifdef _OPENMP`, breaking an in-tree non-OpenMP build independently.

3. **[README.md](/Users/kohlbach/Claude/speXtractor/README.md:68) — “then configure with `-DMZPEAK_ROOT=<checkout>`” — HIGH.** This is insufficient against the documented OpenMS pin. That commit has no `FileTypes::MZPEAK`; none of the three supplied patches adds it. Enabling `SPEXTRACTOR_WITH_MZPEAK` exposes references to that missing enum and assumes OpenMS mzPeak writer support. The additional OpenMS integration required by this configuration is not supplied by the installation recipe.

4. **README.md — “`.mzpeak` when the extension says nothing” — MEDIUM.** That behavior exists only in the mzPeak-enabled branch. The documented ordinary build registers only mzML output and initializes its output type to mzML. The advertised default is therefore build-dependent, without that qualification in the options table.

5. **CHANGELOG.md — “the tool compiles on a stock OpenMS tree” — MEDIUM.** An unpatched stock tree cannot compile it: the calibration header/API and `MassTrace` move operations are mandatory. The defensible claim is that a tree at the stock upstream pin works **after applying the three patches**, without the separate mzPeak integration.

6. **[README.md](/Users/kohlbach/Claude/speXtractor/README.md:38) — patch application immediately followed by configuring SpeXtractor — HIGH.** The recipe never rebuilds OpenMS after changing its headers and implementation. Against an existing unpatched build, this can leave declarations and `libOpenMS` inconsistent, including an unresolved `BrukerTimsFile::lastMzCalibration`. The full-build workflow correctly builds OpenMS between those steps.

7. **scripts/apply_openms_patches.sh — “WITHOUT these patches the tool builds and runs”; “Rebuild the spextractor target” — MEDIUM.** The first statement contradicts the mandatory header/API and move assertions. The second assumes an in-tree SpeXtractor target, although the documented installation is standalone. The required sequence is to rebuild patched OpenMS, then build the standalone tool.

8. **README.md installation/run instructions — “The binary is `build/spextractor`” — MEDIUM.** The source-build recipe omits the OpenMS resource-path requirement. Its own CI explicitly sets `OPENMS_DATA_PATH` and records that the source-built binary otherwise dies even on `--help`. The user-facing instructions need the corresponding resource setup or an installed OpenMS configuration.

9. **README.md — “CMake | 3.16+” — MEDIUM.** SpeXtractor’s own minimum is 3.16, but the mandatory OpenMS source pin requires CMake **3.21**. The stated requirement does not cover the documented end-to-end installation.

10. **[README.md](/Users/kohlbach/Claude/speXtractor/README.md:79), CONTRIBUTING.md — “there is a test for exactly that”; “a run with `-in`, `-out` and `-threads` must reproduce the benchmarked configuration” — HIGH.** Every e2e invocation goes through `run()`, which adds five extraction options, including `assembly:min_fragments=2` and both valley splitters disabled. It explicitly supplies `require_isotope_support=true`, masking a regression of that default. No test shown verifies the complete shipped configuration using only the promised three options.

11. **README.md — “byte-identical at any thread count” — HIGH.** The evidence establishes particular tested pairs, not every thread count. More importantly, e2e check 6 compares synthetic mzML runs without a calibration sidecar, so both use the **OpenMS fallback**. It does not establish thread-count determinism of the shipped integer detector or the streaming `.d` picker, whose frame-assignment sensitivity is explicitly unresolved.

12. **test/test_spextractor.py — “the check every broken integer detector would have failed” — MEDIUM.** The gap-extension checks also run without the sidecar and therefore exercise the fallback detector. Check 9 subsequently checks the `spx:detector` label, but does not repeat the gap assertions on integer output. The claimed regression protection is absent.

13. **[test/test_spextractor.py](/Users/kohlbach/Claude/speXtractor/test/test_spextractor.py:18) — “These exercise the default (OpenMS) detector only”; “not here” — LOW.** This module documentation is stale: integer is the default, and check 9 does exercise the integer path using a generated TDF. The later comment saying the default drops z=1 is also stale; check 2 expects z=1 emission.

14. **CHANGELOG.md / test/test_spextractor.py — “the admission gate’s logged high-water mark (13)” — MEDIUM.** Check 13 uses an acquisition containing **one window**. A cap of one cannot distinguish enforced admission from unrestricted admission. Comparing that result with the uncapped run is similarly vacuous. A multi-window fixture is necessary to test the defect described.

15. **CHANGELOG.md — “new ion-mobility charge veto … on” — MEDIUM.** The new default’s actual branches have no e2e coverage. The test explicitly says its fixture is too small to fit a mobility line, so the veto is inert. Recalling 1→2, dropping the 3+ band, resolving overlapping bands, and handling insufficient fitting data are unverified by the advertised suite.

16. **README.md — “in the end-to-end suite on every build” — MEDIUM.** Per-push CI builds only the OpenMS-independent calibration target and runs Python checks. The executable/e2e workflow runs weekly or manually, with no push, PR, tag, or release trigger. Consequently, ordinary green CI does not establish that the release executable builds or passes e2e checks.

17. **.github/workflows/build.yml — “The binary runs and reports itself” — MEDIUM.** The smoke test checks only that help contains a line beginning `SpeXtractor`. It never checks the release number, generated INI version, or mzML software version. The original help-version defect would pass this gate, and no version round-trip test is present.

18. **[src/spextractor.cpp](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3120), README.md — “`-threads` … all cores”; “an explicit `-threads 1` is honoured” — HIGH.** Explicit CLI `-threads 1` works, but an explicit **INI `threads=1`** is overridden to hardware concurrency because only argv is examined. The effective thread count is not written back into TOPP’s parameters, so output provenance can record `threads=1` while many threads ran. Generated INI/CTD defaults also continue to advertise 1.

19. **CHANGELOG.md — “every script that called `spextract` has to change” — HIGH.** Migration also affects INI section names. TOPPBase looks for the new tool-name prefix; an old section is not translated. With input/output supplied on the command line, OpenMS can warn and continue using defaults instead of the old tool-specific settings. Renaming only the executable in a workflow is therefore insufficient.

20. **README.md — “`2` restores the old behaviour” — HIGH.** The mobility veto runs **before** the minimum-charge filter. Setting `charge:min_charge=2` still preserves newly recalled 2+ precursors and applies the new veto behavior. It does not reproduce the old charge-processing configuration, much less 1.x output. At minimum, reproducing the former charge policy also requires disabling the veto.

21. **[README.md](/Users/kohlbach/Claude/speXtractor/README.md:104) — “`spextractor --help` lists every option with the measurement behind each default” — MEDIUM.** TOPPBase hides advanced options unless `--helphelp` is used. Furthermore, numerous option descriptions contain no measured justification. The statement overclaims both completeness and evidential coverage.

22. **src/spextractor.cpp option descriptions — “Which is closer to the truth is UNMEASURED”; “MemAvailable + our own RSS”; “short peptides” — MEDIUM.** These help strings contradict the release record. Reader sensitivity was measured on September 5; RSS was removed from the memory budget; and the charge-FDR investigation explicitly rejects peptide length as the explanation. The registered help remains stale despite the README directing users to it as the authoritative explanation.

23. **[README.md](/Users/kohlbach/Claude/speXtractor/README.md:101) — “peptide sets within 0.06–2%” — HIGH.** Those figures describe approximately **count changes**, not set agreement. BASELINE records set overlaps of 99.44%/99.37% on D and 99.24%/**89.33%** on A. The last result is **10.67% set disagreement**. Even the count-change range starts around 0.008%, rather than 0.06%.

24. **CHANGELOG.md — “dropping them takes 3.0% / 8.5% off the spectrum list” — MEDIUM.** Using the pre-drop spectrum lists, the reductions are **2.90%** on 009 and **7.86%** on D. The quoted numbers approximately use the smaller, post-drop lists as denominators. Also, 178,226/93,008 are precursor-call counts; emitted spectra fall by only **116,913/72,895**.

25. **CHANGELOG.md — “identified nothing”; “for free” — MEDIUM.** The quoted z=3 counts themselves rise by **9** and **47**, rather than zero. Dropping the arm also reduces accepted totals in several comparisons: on D, MSFragger goes 11,581→11,564 pooled and 12,700→12,666 per-charge; on 009, Sage per-charge goes 27,908→27,831. Small net changes do not establish that no identifiable spectra or peptides were lost.

26. **CHANGELOG.md / README.md — “discarded 14–20% of Sage peptides”; “are 14–20% of Sage peptides” — MEDIUM.** The reference document derives 14.2%/20.1% as **gains relative to the smaller old counts** in the no-veto experiment. Expressed as losses relative to the larger counts, these are **12.4%/16.8%**. Neither calculation establishes the fraction of accepted peptides belonging to z=1; threshold refitting also changes other charge strata.

27. **CHANGELOG.md — “The old default rested on dataset D” — MEDIUM.** The September 3 adoption record says it was confirmed on **D, A, and B**, with both engines and entrapment checks. Describing its evidential basis as D alone omits the recorded confirmations and misrepresents why the old default was adopted.

28. **README.md — “a z=1 call on the 2+ line (~13% of z=1 calls…)” — MEDIUM.** The approximate 13% describes an earlier diagnostic population, not a universal shipped-veto rate. BASELINE records **26.3%** recalled to 2+ on D and **11.3%** on 009’s v37 arm; 001’s shipped arm is about 11.3%. The options table conflates the diagnostic estimate with the actual recall fraction.

29. **README.md / CHANGELOG.md — “Their stratum carries ~3% entrapment FDR”; “0.87–0.91% under a per-charge walk” — MEDIUM.** These figures need explicit dataset scope. D’s shipped pooled z=1 estimate is **8.8%**, not approximately 3%. The cited 0.87–0.91% per-charge estimates are for the two TNBC runs; the supplied D record does not establish that same range.

30. **CHANGELOG.md headline / REFERENCE-COMPARISON conclusion — “under per-charge FDR control”; “whole-run entrapment … 0.93–1.03%” — MEDIUM.** The presentation mixes filtering procedures. On 001, **0.93% is pooled-cut entrapment**, while the measured per-charge walk gives **0.99%** whole-run entrapment. The headline should identify which filtering procedure generated each FDR figure.

31. **CHANGELOG.md — “honest to about a quarter point of FDR” — MEDIUM.** This is not an established error bound. The shipped D whole-run estimate is 1.33%, already 0.33 percentage points above nominal; its z=1 estimate is 8.8%. Historical confidence intervals are also wider than ±0.25 points. Neither overlapping intervals nor nearby point estimates certify the stated accuracy.

32. **CHANGELOG.md / README.md — “30% less peak memory for … +8.5% wall” attributed to `malloc_trim` — MEDIUM.** The cited interleaved comparison is **v13 versus v19**, encompassing moves, lifetime changes, record reduction, admission changes, and trimming. It does not isolate trimming. The closer v17→v18 series gives approximately **+5.9% wall and −27.8% peak**, but is not the interleaved experiment. No isolated trim-on/off v38 measurement is supplied.

33. **README.md — “tcmalloc_minimal is a further, independent lever” — MEDIUM.** The document simultaneously acknowledges it was measured before trimming and never retested with trimming. Those measurements establish an alternative allocator result on an older configuration, not an independent or additive saving at the shipped defaults.

34. **README.md — “`require_isotope_support=false` … is ~7× slower” — MEDIUM.** That ratio comes from September 4, before the task-scheduling cliff was fixed. Its recorded occupancy collapse to 6.0× is precisely the kind of behavior the release subsequently repairs. The old ratio cannot be presented as current v2 behavior without another measurement.

35. **README.md — “The loader is a few percent” — MEDIUM.** BASELINE’s phase tables put loading at **10.7%** on D and **13.7%** on TNBC 009 at v35. No shipped-default phase record supplied supports “a few percent.”

36. **README.md — “window-loop occupancy … ~72×” versus “~78×” — LOW.** Two different 30-minute figures are presented without identifying different runs or configurations. BASELINE supports 72.0× at v35; the supplied v38 D record contains no occupancy measurement supporting 78×.

37. **README.md — “on a 32 GB machine the tool will not complete” — MEDIUM.** This universal claim is contradicted by measured full acquisitions in BASELINE: public files extracted at approximately **10–16 GB**, and a two-hour py3 file at **26 GB**. D’s measured requirement cannot establish a minimum for every full acquisition.

38. **README.md — “roughly 9 GB for a 30-minute run … at the previous emission” — MEDIUM.** The changelog records **6.23 GB** for the previous-default D output of 655,776 spectra. Approximately 9 GB belongs to an older, larger-emission configuration. “Previous emission” does not distinguish these baselines, so the disk-sizing guidance mixes generations of output.

39. **README.md / CHANGELOG.md / CONTRIBUTING.md — memory figures labeled “GB” — MEDIUM.** BASELINE explicitly states “Every figure in this file is GiB,” while its tables and the release documents repeatedly label copied values GB. Its unit-trap explanation also contains inconsistent conversion language. The raw measurements and conversions must be reconciled before these become hardware-sizing requirements.

40. **CHANGELOG.md — “The trace record is 48 bytes, was 72 … the change measured −10.7 GB … −2.7 GB” — MEDIUM.** Those savings were recorded for the **72→56-byte** stage. BASELINE separately records the subsequent 48-byte record plus splitter-reserve change, including another approximately 5.5 GiB peak reduction. The release attaches intermediate-stage measurements to the final combined change.

41. **CHANGELOG.md — “the greedy claim loop went … to 23.4x … 112–138 s → 7.8 s” — LOW.** The 23.4× figure is recorded **phase CPU/wall occupancy**, not elapsed-time speedup. The explicit 128.8→7.8-second comparison is **16.5× faster**. Naming the metric is necessary to avoid presenting incompatible multipliers as the same result.

42. **CHANGELOG.md — “an additive offset on the root, `m = u^2 - C4`” — LOW.** The equation applies the offset to the **squared root result, i.e. mass**, not to the root `u`. The implementation computes `u*u - C4`; the prose describes a different operation.

43. **README.md — “costing roughly 6–11% of closed-search peptide identifications” — MEDIUM.** The underlying three-file measurement is a **6.1–10.9% gain in Sage**, relative to the old counts. It is not an engine-independent loss estimate; the earlier MSFragger comparison was approximately flat. Converting those Sage gains into losses relative to corrected counts gives approximately **5.8–9.8%**.

44. **CHANGELOG.md — “the `C4` calibration term and the window key all change spectra” as semver justification — MEDIUM.** The C4 change is explicitly identical when C4=0 and enables files previously refused; the window-key change preserves other acquisition schemes. More fundamentally, digest changes from corrected numerical behavior do not alone establish an incompatible public interface. The executable rename supplies that justification; the rationale should distinguish interface breakage, changed defaults, and corrected results.

45. **CHANGELOG.md — “drivers … are untracked `.example` templates” — LOW.** The `.example` templates are tracked: `bench/run_joint.sh.example`, `bench/run_open.sh.example`, and `harness/samples.yaml.example` appear in `git ls-files`. The configured local copies are what should be untracked.

46. **CHANGELOG.md / CONTRIBUTING.md — “acquisition and specimen identifiers are scrubbed from the tracked tree”; “Don’t commit acquisition or specimen identifiers” — MEDIUM.** Tracked BASELINE entries still contain legacy identifiers in paths such as `final_S30`, `digest_port`, and `gateMs1Bands/b48_S30`; public acquisition identifiers also appear throughout. If public identifiers and historical artifact names are intentional exceptions, the stated policy and completed-scrub claim need those exceptions.

47. **CHANGELOG.md / scripts/sync_cluster.sh — “ships … the end-to-end suite with every deploy” — MEDIUM.** Check 9 reads `../tests/calibration_golden.json` relative to the deployed test script, but deployment copies only the Python script, not that dependency. A clean deployment can fail; an existing deployment can silently use stale calibration fixtures.

48. **scripts/sync_cluster.sh — “remote lock so deploys cannot interleave”; “source restored” — HIGH.** Source staging and header/test copies occur **before** acquiring the remote lock. Concurrent deployments can overwrite those inputs while another build runs. On failure, only the `.cpp` backup is restored, leaving updated headers behind. The stated exclusion and rollback guarantees are not implemented.

49. **docs/REFERENCE-COMPARISON-2026-09-08.md — “within 2% of parity on MSFragger” — LOW.** On 001, 19,230 versus 19,652 is a **2.147% deficit**. The displayed ratio rounds to 0.98, but the unrounded counts do not satisfy “within 2%.”

**Q1.** Yes: **v2.0.0 is appropriate relative to public v1.1.0**. Removing the old executable name breaks the command-line interface. Changed build prerequisites and default behavior reinforce the migration requirement. Digest changes alone are not sufficient semver reasoning; corrected outputs can accompany compatible bug fixes. The private 0.x history and four-day interval do not alter the public-version baseline. [Semantic Versioning specification](https://semver.org/spec/v2.0.0.html)

**Q2.** Setting `version_` is valid. At the pinned OpenMS implementation, `official=false` bypasses official-name registration checks; there is no requirement that this tool’s version equal OpenMS’s version. INI version mismatches produce a warning, and new 2.0.0 INIs can round-trip. mzML processing software correctly receives SpeXtractor’s version; the mzML format version is separate. The supplied constructor had the help-banner defect, now fixed in the workspace. Remaining risks include old INI section migration, `threads=1` handling, and lack of automated version round-trip coverage.

**Q3.** Yes: the set-agreement claim, spectrum-reduction percentages, charge-gain denominators, FDR scopes, occupancy figures, disk baseline, memory units, and record-saving attribution are inconsistent or unsupported as detailed above. The headline **0.61× wall, 0.55× RSS, 1.28/1.00 and 1.25/0.98 peptide ratios** follow from the supplied counts with ordinary rounding.