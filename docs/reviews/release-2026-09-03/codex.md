The current working tree is not ready for a public v0.3.0 release. The worst problems are silent mzPeak corruption/omission paths, known isotope-walk misassignment, misleading “open-search safe” behavior, and the absence of tests for any of this core logic.

## 1. Correctness and safety of the code

- **BLOCKER — mixed or wrong calibration is stamped as exact.** [`MzPeakStreamLoad.h:167`](</Users/kohlbach/Claude/speXtractor/src/MzPeakStreamLoad.h:167>), `MzPeakExactMz::exact()`: a missing/out-of-range `frame_id` silently substitutes `cal.T1_ref`; a non-finite recalculated value silently leaves the archive’s approximate m/z in place. The output is nevertheless stamped `tdf_table_modeltype1`. `sqrt(v)`/`llround()` is also unsafe for invalid input. Smallest fix: require a valid `Frames.Id` and explicit T1 entry for every frame; reject non-finite/non-positive input or calibrated m/z instead of retaining the old value.

- **BLOCKER — the mzPeak batch loader silently drops frames.** [`MzPeakStreamLoad.h:335`](</Users/kohlbach/Claude/speXtractor/src/MzPeakStreamLoad.h:335>), `get_spectra_batch()`: the loop stops at `min(want.size(), got.size())`; a short library result leaves empty slots that are quietly skipped at line 348. That produces incomplete mzML with a successful exit. Smallest fix: require `got.size() == want.size()` and verify returned IDs/order before conversion; otherwise throw.

- **BLOCKER — malformed or unsupported MS2 input can yield a valid-looking empty/partial result.** [`DIAPseudoSpectra.cpp:1787`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1787>), [`DIAPseudoSpectra.cpp:1838`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1838>), [`DIAPseudoSpectra.cpp:2850`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2850>): validation checks only that MS1 has some IM data. MS2 frames without IM or precursors are silently skipped, zero windows are allowed, and zero emitted spectra are written with `EXECUTION_OK`. Smallest fix: count and reject missing-IM/missing-window MS2 frames, require at least one usable isolation window, and fail if all windows or all output spectra disappear.

- **BLOCKER — the default contiguous isotope walk is a known wrong-mass generator.** [`DIAPseudoSpectra.cpp:1163`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1163>), `inferPrecursors_()`: the first missing isotope terminates each direction. Higher isotopes are then left unmarked and can seed new precursors with an M+1/M+2 monoisotope. The project’s own baseline confirms this mechanism at `dataset D-BASELINE.md:703-713`. Smallest fix: separate scoring from ownership—scan the bounded isotope lattice for the selected charge despite gaps, then mark every matched member of the selected envelope as consumed. Rebenchmark before adoption.

- **HIGH — isotope matching chooses the lowest-m/z candidate, not the best candidate.** [`DIAPseudoSpectra.cpp:1132`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1132>), `findPartner`: it returns the first trace in the tolerance interval. With multiple co-eluting candidates, that is neither nearest in ppm nor best in RT, IM, XIC correlation, or intensity. It deterministically returns the wrong trace. Smallest fix: evaluate the whole interval and minimize a documented tuple such as absolute ppm error, RT error, IM error, then stable trace ID.

- **HIGH — window identity is lossy.** [`DIAPseudoSpectra.cpp:1723`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1723>) and [`DIAPseudoSpectra.cpp:602`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:602>): windows are keyed only by m/z bounds rounded to 0.01 Da; mobility bands and `swath_nr` are discarded. Distinct windows can be merged, particularly methods reusing an m/z interval at different mobility bands. Smallest fix: use a structured acquisition-window identity containing unrounded/canonically quantized m/z and IM bounds, and abort on inconsistent collisions.

- **HIGH — precursors on a shared window boundary are emitted twice.** [`DIAPseudoSpectra.cpp:2394`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2394>): `lower_bound(win_lo)` plus `upper_bound(win_hi)` makes both edges inclusive. Adjacent windows `[a,b]` and `[b,c]` both claim a precursor exactly at `b`. Smallest fix: use half-open intervals `[lo,hi)`, with an explicit exception only for the final acquisition boundary.

- **HIGH — non-finite MS1 traces enter sort and binary-search code unchecked.** [`DIAPseudoSpectra.cpp:1998`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1998>) and `inferPrecursors_`: fragments are filtered for finite coordinates, but MS1 traces are not. NaNs invalidate the comparator and the sorted-range precondition required by `lower_bound`. The comment at line 2392 claiming NaN m/z “sorts to the end” is false. Smallest fix: reject traces with non-finite m/z, RT, IM, intensity, or XIC values before sorting and inference.

- **HIGH — cross-frame aggregation can reuse already-consumed peaks with negative intensity.** [`DIAPseudoSpectra.cpp:334`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:334>), `aggregateFrames_()`: consumed peaks are set to `-1`, but later clusters do not skip `buf[b].in < 0`. A peak within tolerance of two nearby IM anchors can be accumulated twice, the second time negatively. Smallest fix: add `buf[b].in > 0` to the membership condition or maintain a separate consumed bitmap.

- **HIGH — IM units are assumed, not enforced.** [`DIAPseudoSpectra.cpp:1796`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1796>): mzML is accepted after detecting “some IM,” but milliseconds, CCS, and FAIMS values can then be treated numerically as 1/K0. That silently corrupts every IM gate. Smallest fix: verify VSSC/1/K0 units on every relevant spectrum and reject unsupported units with a conversion-oriented error.

- **HIGH — default banding is asserted to be exact without an exact boundary argument.** [`DIAPseudoSpectra.cpp:915`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:915>): the claim that a trace cannot span more than one ppm tolerance ignores trace chaining across successive observations. A fixed 20× halo is plausible, not proof. Boundary traces can therefore be truncated or duplicated relative to `bands=1`. Smallest fix: add an equivalence test containing a deliberately drifting boundary trace; if equivalence fails, extend bands until no retained trace touches a halo boundary or assign seeds to cores while allowing unrestricted extension.

- **HIGH — parameter ranges permit silent nonsense.** [`DIAPseudoSpectra.cpp:1710`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1710>): negative fragment counts are cast to unsigned `Size`; negative tolerances quietly suppress output; negative `mem_fraction` is converted to `size_t`; `SPEXTRACTOR_PICK_BATCH=garbage` becomes zero and `-1` becomes a huge size. Smallest fix: define TOPP min/max constraints and explicitly validate all environment values with checked parsing.

- **MEDIUM — CSR indexing narrows real input sizes to 32 bits.** [`DIAPseudoSpectra.cpp:273`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:273>) and [`DIAPseudoSpectra.cpp:725`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:725>): `FragGrid::off` is `uint32_t`, and grid positions are `int`. A sufficiently large window wraps offsets and silently reads the wrong fragment support. Given this tool already operates near hundred-gigabyte scale, this is not academic. Smallest fix: use `size_t` for offsets and indices, or abort before exceeding the chosen representation.

- **MEDIUM — canonical MS1 ordering is not actually total.** [`DIAPseudoSpectra.cpp:1998`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1998>): two traces with equal m/z, RT, IM, and intensity but different XICs compare equivalent. Their inherited nondeterministic order then changes the index tie-break and greedy `used[]` ownership. Smallest fix: retain a stable physical origin ID or lexicographically compare the XIC as the final tie-break.

- **MEDIUM — even aggregation sizes do not mean what the parameter says.** [`DIAPseudoSpectra.cpp:300`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:300>): `n_frames=4` gives `half=2`, hence a five-frame window. Smallest fix: reject even values or implement asymmetric bounds totaling exactly `n_frames`.

- **MEDIUM — mzPeak array mismatches are normalized into partial input.** [`MzPeakStreamLoad.h:190`](</Users/kohlbach/Claude/speXtractor/src/MzPeakStreamLoad.h:190>): m/z and intensity are truncated with `min()`, while short IM arrays become “no IM.” Smallest fix: require equal array lengths and throw with frame ID and observed sizes.

I found no confirmed C++ data race in the reviewed OpenMP window loop or MS1 pick loop: picker instances are `firstprivate`, spectra/slots are disjoint, `pdense` is copied per inner worker, and shared appends/errors are protected. I also found no unchecked `--iterator` decrement; the only `prev(it)` at line 1442 is guarded. Empty `lower_bound`/`upper_bound` calls themselves are safe. The remaining risks are deterministic algorithmic wrongness and incomplete total ordering, not an obvious unprotected write.

## 2. Code versus documentation consistency

- **BLOCKER — “open-search safe” is not safe and its promised correction metadata does not exist.** [`DIAPseudoSpectra.cpp:774`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:774>) versus [`DIAPseudoSpectra.cpp:1647`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1647>): the flag only unsets guessed charges. Isotope-supported charges remain annotated despite the README admitting only 74.6% agreement. `spx_n_isotopes` is an evidence count, not an isotope-offset hypothesis capable of correcting ±1.00335 Da. Smallest fix: rename the option to `unset_guessed_charge`, remove the safety/correction claim, or implement an actual confidence/offset representation and unset every insufficiently supported charge.

- **HIGH — the documented “current defaults” are false.** [`dataset D-BASELINE.md:20`](</Users/kohlbach/Claude/speXtractor/docs/dataset D-BASELINE.md:20>) says `ms2_noise_threshold_int=10` and `ms2_split_valleys=7`; code defaults are 100 and 0 at [`DIAPseudoSpectra.cpp:780`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:780>) and line 788. Thus the README’s headline numbers are not reproducible from its one-line default invocation. Smallest fix: either change the defaults or label the benchmark overrides explicitly in README and provide the exact INI.

- **HIGH — several documented experimental options do not exist.** [`CHANGELOG.md:13`](</Users/kohlbach/Claude/speXtractor/CHANGELOG.md:13>) claims `SPEXTRACTOR_ISO_COLLAPSE` was added; [`CHANGELOG.md:55`](</Users/kohlbach/Claude/speXtractor/CHANGELOG.md:55>) and [`dataset D-BASELINE.md:594`](</Users/kohlbach/Claude/speXtractor/docs/dataset D-BASELINE.md:594>) document `SPEXTRACTOR_BACKFILL_RAW`, `BACKFILL_MAXFRAGS`, `BACKFILL_EMPTY`, and `BACKFILL_MAXQ`. None appears in either shipped source file. Smallest fix: restore the implementations or move them into an explicitly historical-results section saying “not present in v0.3.”

- **HIGH — `trace:split_valleys_fwhm` describes the wrong code path.** [`DIAPseudoSpectra.cpp:791`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:791>) says it overrides `trace:ms1_split_valleys`; lines 1969–1976 modify only `ms2_split`. Smallest fix: change the help to “overrides `trace:ms2_split_valleys`,” or implement the claimed MS1 two-pass behavior.

- **HIGH — `charge:ambiguity_margin` is inert under the shipping scoring mode.** [`DIAPseudoSpectra.cpp:851`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:851>) promises an alternative charge, but the `count` branch exits at line 1246 before the ambiguity block at line 1345. README presents four `count`-mode tests as a falsification; `dataset D-BASELINE.md:100` correctly admits it was unreachable. Smallest fix: mark it “envelope mode only” everywhere or calculate count-mode hypotheses without the early `continue`.

- **HIGH — benchmark numbers in `--help` are configuration-dependent but presented as properties of the option.** [`DIAPseudoSpectra.cpp:837`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:837>) embeds dataset D emission, peptide, engine, and runtime numbers produced under non-default MS2 settings. The current default invocation cannot reproduce them. Smallest fix: reduce help to behavior/default/risk and link to a versioned benchmark document containing the complete command and input identity.

- **MEDIUM — `charge:min_charge` has the correct position but not the claimed guessed-precursor semantics.** [`DIAPseudoSpectra.cpp:2032`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2032>) correctly applies default charge, then isotope-support gate, then minimum-charge filtering before extraction. True charge 0 survives. But a guessed precursor assigned `assembly:default_charge=1` is silently dropped by `min_charge=2`. Smallest fix: filter only `!pc.guessed && pc.charge > 0 && pc.charge < zmin`, or apply the charge gate before default-charge assignment.

- **MEDIUM — the README contains mutually incompatible reproducibility stories.** [`README.md:83`](</Users/kohlbach/Claude/speXtractor/README.md:83>) says spectrum data is byte-identical at any thread count; [`README.md:118`](</Users/kohlbach/Claude/speXtractor/README.md:118>) calls four differing counts “runs of an identical effective configuration.” The latter numbers are the ambiguity-margin experiment, not a current converter replicate guarantee. Smallest fix: separate converter determinism, search-engine determinism, and historical same-binary variability; do not reuse treatment-arm counts as replicate variance.

- **MEDIUM — README runtime is stale within the same document.** [`README.md:69`](</Users/kohlbach/Claude/speXtractor/README.md:69>) reports 12:49 for the current charge-gated arm, while line 91 calls 15:21 the current dataset D runtime without saying it is pre-charge-gate. Smallest fix: label 15:21 as the predecessor or delete it.

- **MEDIUM — “74.6% with current defaults” is denominator-ambiguous after `min_charge=2`.** [`README.md:101`](</Users/kohlbach/Claude/speXtractor/README.md:101>): 74.6% was measured before the new filter removes z=1 hypotheses. It is not clearly the agreement of the spectra now emitted by default. Smallest fix: rerun on the post-filter output and state the denominator, or label 74.6% as pre-filter inference accuracy.

The registered falsified options do exist with defensible off defaults: `competitive` false, `apportion=0`, `rp_max=0`, frame aggregation `=1`, `variance_support` false, `consolidate:delta_rt=0`, `merge:rt_window=0`, `mono_averagine_guard=0`, and `mono_averagine_select` false. The exception is `ambiguity_margin`: it exists and defaults to zero, but its advertised count-mode experiment never exercised the implementation.

## 3. Is the package complete and usable by someone else?

- **BLOCKER — the published benchmark is not externally reproducible.** README’s headline refers to dataset A/dataset B/dataset D, but no accession or downloadable raw/reference data is supplied. The harness uses private `/scratch` and `/ceph` paths and private the reference implementation products. Smallest fix: publish a public-data recipe or explicitly label the table “internally reproducible only”; include immutable input/config/binary hashes and a portable harness plan.

- **HIGH — the build instructions are internally wrong.** [`README.md:18`](</Users/kohlbach/Claude/speXtractor/README.md:18>) says to “rebuild the OpenMS DIAPseudoSpectra target,” although README and CMake insist this is standalone. No actual standalone `cmake -S/-B`, build, install, or runtime-library command is given. Smallest fix: provide a complete copy-paste build from fresh OpenMS checkout through `cmake --build` and one verified invocation.

- **HIGH — dependency identity is not reproducible.** [`README.md:30`](</Users/kohlbach/Claude/speXtractor/README.md:30>) names a bespoke `3.6.0-pre-exported-20260717`, while mzPeak is described as fork “trunk.” No OpenMS or mzPeak commit SHA, compiler/standard-library matrix, patch-base SHA, Arrow/Parquet/libzip versions, or container/lockfile is supplied. Smallest fix: pin commits and versions in a release manifest and CI-build exactly that manifest.

- **HIGH — CMake’s no-OpenMP promise is false.** [`CMakeLists.txt:23`](</Users/kohlbach/Claude/speXtractor/CMakeLists.txt:23>) claims a serial build works, but [`DIAPseudoSpectra.cpp:531`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:531>) calls `omp_set_schedule` and uses OpenMP enums outside `_OPENMP`. Smallest fix: guard that call and provide a serial schedule fallback, then CI-build with OpenMP disabled.

- **HIGH — no realistic resource requirements are given.** The README recommends tcmalloc but the benchmark itself reports 100–156 GB peak RAM. The admission code deliberately admits one oversized window, so a normal workstation can still OOM. Smallest fix: document tested RAM/disk/core requirements, a low-memory command, expected slowdown, and the meaning/limits of `perf:mem_fraction`.

- **HIGH — there is no worked example with an expected result.** [`README.md:44`](</Users/kohlbach/Claude/speXtractor/README.md:44>) gives only a command. There is no public miniature input, expected spectrum count, expected precursor/fragment values, provenance value, or validation command. Smallest fix: ship a small legally redistributable fixture plus expected semantic digest and five representative spectra.

- **MEDIUM — the input contract is incomplete.** README does not specify that mzML must contain usable MS1 and MS2, per-peak VSSC IM arrays, isolation-window offsets, and suitable profile/centroid metadata. It also does not describe behavior for unsupported IM units or multiple precursor records. Smallest fix: add an “Input contract” table and a preflight command.

- **MEDIUM — the output contract is incomplete.** “Searchable mzML” does not document charge-0 behavior, `spx_guessed`, `spx_n_isotopes`, calibration provenance, isolation offsets, or which search engines honor an unset precursor charge. Smallest fix: document emitted fields and provide Sage/MSFragger configs known to interpret them correctly.

- **MEDIUM — third-party attribution is incomplete for optional binary distribution.** [`NOTICE:4`](</Users/kohlbach/Claude/speXtractor/NOTICE:4>) covers OpenMS and algorithmic references, but the optional build statically links mzPeak, Arrow, and Parquet and also uses libzip, zlib, and SQLiteCpp. Smallest fix: list these dependencies, licenses, source locations, and any notices required when distributing binaries. The BSD-3 `LICENSE` and OpenMS attribution themselves are present.

- **MEDIUM — release metadata still says v0.2.0.** [`CMakeLists.txt:2`](</Users/kohlbach/Claude/speXtractor/CMakeLists.txt:2>) remains `VERSION 0.2.0`; `CITATION.cff` also remains 0.2.0. Smallest fix: update them atomically at release and add a version-output regression test.

The one-large-file convention is not itself a usability defect. The absence of a stable, testable and documented release envelope is.

## 4. Internal development commentary

My position: retain local engineering rationale, preserve falsified experiments in `docs/`, and remove lab-notebook prose from `--help` and executable hot paths.

Keep:

- [`DIAPseudoSpectra.cpp:1806`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1806>): why `PeakPickerIM` must be `firstprivate` and exceptions cannot escape OpenMP.
- [`DIAPseudoSpectra.cpp:367`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:367>): compact representation, quantization, and rejection policy.
- [`DIAPseudoSpectra.cpp:1988`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1988>): the fact that greedy ownership requires canonical trace ordering—after fixing the incomplete tie-break.
- [`DIAPseudoSpectra.cpp:1479`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1479>): why overlap support is checked before correlation.
- [`DIAPseudoSpectra.cpp:2833`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2833>): why calibration and weighting provenance must be written.

Move to `docs/experiments/`:

- Route/arm chronology, sample counts, dates, reviewer names, and measured peptide deltas at lines 768–856, 998–1005, 1145–1202, 2045–2072, 2192–2252, and 2398–2467.
- `[route-1]`, `[content 3]`, `[step-02]`, `[kimi]`, `[codex]`, dated launch details, and “first attempt/reverted” narratives. These are useful evidence, but they make local invariants indistinguishable from expired experimental context.
- The complete dataset D/dataset A/dataset B outcome histories already belong in `dataset D-BASELINE.md`; source comments should link to a stable experiment ID rather than reproduce the notebook.

Cut from user-facing help:

- Per-sample counts, dates, review arguments, “try this next,” and multi-paragraph causal narratives.
- Keep `FALSIFIED` because that is an intentional project convention, but compress it to: “Experimental; default off. Lost X under experiment E-ID; see docs/…”. Help must explain behavior, units, valid range, mode dependencies, and default—not litigate the experiment.

Factually stale commentary:

- [`DIAPseudoSpectra.cpp:758`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:758>) calls defaults placeholders pending a real-data sweep. The file then cites months of sweeps.
- [`DIAPseudoSpectra.cpp:244`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:244>) says default is the OpenMS centroid; line 249 defaults to apex.
- [`MzPeakStreamLoad.h:23`](</Users/kohlbach/Claude/speXtractor/src/MzPeakStreamLoad.h:23>) says exact m/z is enabled with `SPEXTRACTOR_MZPEAK_EXACT=1`; actual behavior is default-on and `=0` disables it.
- [`DIAPseudoSpectra.cpp:1317`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1317>) documents a non-envelope fallback that is dead code because the earlier count branch always `continue`s.
- [`DIAPseudoSpectra.cpp:1947`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1947>) refers to obsolete line `:1324`.
- [`DIAPseudoSpectra.cpp:2641`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2641>) says merge intensities are summed; the default implementation takes maximum.
- [`DIAPseudoSpectra.cpp:65`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:65>) sends users to top-level `PLAN.md` and `REVIEW.md`, neither of which exists.
- [`DIAPseudoSpectra.cpp:2239`](</Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:2239>), `bands_for`, is unused “kept for reference” code. Reference implementations belong in history or tests, not the release executable.
- The tag `ponytail` has no public meaning and should be replaced with an explanation or removed.

## 5. Test coverage

The smallest credible core suite is:

1. **`inferPrecursors_()` contiguous/gapped ownership test.** Supply a z=2 envelope at M, M+1, M+2 with M+1 absent in a second case. Assert one precursor, correct mono/charge, and that M+2 does not reseed. Add a lower-m/z decoy inside the ppm/RT/IM box to catch first-candidate selection.

2. **`inferPrecursors_()` permutation/determinism test.** Feed the same traces in every relevant order, including two equal scalar traces with different XICs. Assert identical precursor records and isotope ownership.

3. **Minimum-charge pipeline test.** Inputs: supported z1, supported z2, guessed/defaulted z1, and charge 0; test with and without `require_isotope_support` and `open_search_safe`. Assert only supported z1 is removed by `min_charge=2`.

4. **Window-partition test.** Two adjacent windows `[400,425)` and `[425,450]`, with precursors just below, exactly on, and just above 425. Assert each is assigned exactly once. Add two equal m/z windows with different IM bands to catch key collisions.

5. **`aggregateFrames_()` consumed-peak test.** Use IM values 1.000, 1.015, and 1.008 within one m/z cluster at tolerance 0.01, where the third peak is close to both anchors. Assert no negative reuse and conserved positive intensity. Also assert `n_frames=4` has defined behavior.

6. **Band-equivalence test for `detectTraces_()`.** Construct a trace drifting across a quantile boundary and compare `bands=1` versus `bands=12` trace sets bit-for-bit. Include a valley-split trace and duplicate boundary m/z.

7. **mzPeak loader contract tests.** A fake reader returning fewer spectra than requested must throw; missing/duplicate frame T1 must throw; invalid calibrated m/z must throw; unequal m/z/intensity/IM arrays must throw.

8. **Tiny end-to-end golden test.** Run one small mzML at threads 1, 2, and 8 and with MS1/MS2 band counts 1 and 12. Compare semantic spectrum records including precursor m/z, charge, RT, IM, fragment sequence/intensity, `spx_guessed`, `spx_n_isotopes`, and calibration provenance.

9. **Invalid-input/parameter tests.** Missing MS2 IM, no isolation windows, zero usable fragments, negative counts/tolerances/memory fraction, invalid environment integers, and an unreadable `SPEXTRACTOR_PRECURSOR_LIST` must all fail loudly rather than write an empty mzML.

These tests can remain compatible with the one-file convention by compiling the source under a test macro that exposes pure wrappers; no architectural rewrite is required.

Current verification is not sufficient for a public release. Peptide-set equality is downstream and lossy: it can miss dropped frames, duplicated spectra, wrong charges, isotope-shifted monoisotopes, tiny intensity corruption, and empty experimental branches whenever the search still returns the same peptides. Closed-search equality is especially incapable of protecting the blind/open-search failure modes that define this tool. The existing calibration tests cover the calibration formula, not the loader contract, precursor inference, window partitioning, OpenMP equivalence, or spectrum assembly.