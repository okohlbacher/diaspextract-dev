• # Adversarial review: stage 2 (dnoise:ms1 in-tool) + fix pass

  Findings most severe first. Clean areas are called out at the end.

  ---

  ## 1. The raw-intensity inversion assumes an opentims evaluation order that the inlined text contradicts — and a mismatch is *silent*, not fail-closed

  **Location:** `DnoiseRun::frame`, `spextractor.cpp` — `corr = fr.corr` (= `100.0 / std::atof(acc_text)`, TdfLoad.h), forward check `if ((uint32_t)(r * corr + 0.5) == (uint32_t)v)`.

  The context paragraph describes the loader's value as `(uint32)(raw*100/AccumulationTime + 0.5)`, i.e. `(raw*100)/at`. The recovery recomputes `r * (100/at)`. These are different double roundings (`raw*100` is exact, then one rounding on division; `100/at` rounds first, then multiplies — two roundings). They agree almost everywhere, but they disagree at exact `.5` ties, and the stage-1 header itself documents that a ±1 raw difference flips kept points (9 of 3.1 M on TNBC). If opentims' actual expression is `(raw*100)/at` (or it reads `AccumulationTime` via `sqlite3_column_double` rather than text+`atof` — the comment asserts text, the diff does not show the opentims source), then at a tie the true raw `r0` does **not** reproduce `v`, and a neighbour `r0±1` may reproduce it **uniquely** (`hits == 1`). That is a wrong raw count passing every check — the kept set silently diverges from dnoise's, and nothing throws. The same applies to `mzToTof`/scan only in principle (tolerances absorb ulps there); the intensity path is the one that demands bit-exactness.

  **Fix:** pin the exact opentims expression from its source in a comment and reproduce it operation-for-operation (`(r * 100.0) / at` if that is what it does, not `r * corr`); state whether opentims reads the column as REAL or text, with the same one-ulp argument. Add a golden test (finding 2) that includes tie-constructed (raw, AccumulationTime) pairs.

  ## 2. No automated test covers point recovery at all

  **Location:** `DnoiseRun::frame` / `scanOf` / `setup` all live in `spextractor.cpp`. `tests/test_dnoise_ms1.cpp` pins only the port's filter and gate boxes (DnoiseMs1.h). The e2e suite cannot build a .d (check 20 tests only the mzML skip). The sync_cluster unit test compiles only the header.

  So the entire inversion layer — TOF round-trip, scan-table nearest-match, intensity uniqueness, NumPeaks/msms_type cross-checks, the rational-model term order, 0- vs 1-based scan indexing — is pinned only by two manual cluster digests (e43672a0, 3aafd0b5). Any regression here (an OpenMS loader change, a refactor of `scanOf`, finding 1) compiles green and passes 22/22, and is discovered on the cluster hours into a run — as a refusal if lucky, as a digest mismatch otherwise.

  **Fix:** factor the recovery into a small header (like TdfMzCalibration.h) and add golden vectors extracted from D/TNBC frames: (m/z, float32 1/K0, float intensity, frame id) → (tof, scan, raw), including boundary cases: a corrected intensity at exactly k−0.5, a 1/K0 adjacent to a table step, intensity 0, and the monotonicity/corr refusal paths. A synthetic mini-.d (sqlite + blob) is constructible from python for a true e2e of the .d branch of check 20.

  ## 3. sync_cluster.sh overwrites four headers with no backup and does not restore them on failure

  **Location:** the `scp` lines for `TdfMzCalibration.h`, `TdfLoad.h`, `MzPeakStreamLoad.h`, `DnoiseMs1.h`; the failure paths restore only `'${REMOTE_SRC}.bak' → '$REMOTE_SRC'`.

  On a unit-test or build failure the script prints "source restored, binary and provenance unchanged" — but the new headers remain on the node. The next `make spextractor` compiles the *old* spextractor.cpp against the *new* TdfLoad.h/DnoiseMs1.h. That is precisely the src/header drift the script's own comments describe ("a rename left the cluster building against a stale TdfLoad.h") and the provenance block will not show it (it hashes the restored .cpp and states the new header SHAs — actually `tool_headers_sha256` records the *new* headers against the *old* source, so the record itself becomes misleading). This got worse with this change: TdfLoad.h now `#include`s DnoiseMs1.h, so a restored pre-stage-2 source plus new headers is a configuration that never existed locally.

  **Fix:** back up all four remote headers (and the topp-dir copies) before overwriting, restore them in both failure branches alongside the .cpp, and fix the failure message.

  ## 4. The contraction guard does not reach the recovery arithmetic on the in-tree build

  **Location:** DnoiseMs1.h guards its own gate math (pragma + volatile) and CMakeLists adds `-ffp-contract=off` to the `spextractor` target — but the cluster build is `make spextractor` inside the OpenMS tree, where this repo's CMakeLists does not run; the flag exists there only if OpenMS's own topp flags carry it. `DnoiseRun::frame` (the `r * corr + 0.5` forward check, the `mzToTof` round trip) is defined in spextractor.cpp, *after* the header's `#pragma GCC pop_options` region, so the header cannot protect it. The node unit test compiles `test_dnoise_ms1.cpp` with the topp flags — but the recovery code is not in that translation unit, so the test passes even if the tool TU contracts. Contraction shifts the intensity forward-check by 1 ulp at `.5` ties → finding 1's failure mode (usually refusal, occasionally a unique wrong hit).

  **Fix:** add `-ffp-contract=off` (or a function-level guard) to the OpenMS topp target for spextractor.cpp via the patch stack, and/or move the per-point recovery into `inline` functions inside the guarded region of DnoiseMs1.h so the protection travels with the code.

  ## 5. The scan-table validation is stricter than the contract and refuses legitimate files

  **Location:** `DnoiseRun::setup`: `const size_t n_scans = tdf.meta.max_num_scans;` then every TimsCalibration row's table is built and required strictly monotonic with gaps > 4e-6 over the **global** `MAX(Frames.NumScans)`.

  (a) A calibration row referenced only by frames with `NumScans < max` is checked through the extrapolated region of the rational model, where nothing requires monotonicity — one such row refuses the whole run although no point ever uses those table entries. (b) Rows referenced by no MS1 frame (or by MS2-only frames) must still pass. Both are false refusals on legitimate multi-calibration acquisitions (e.g., a calibration segment with a different scan count). dnoise itself never builds these tables; this is the tool's own check over-reaching.

  **Fix:** build/check each row's table only up to the max `NumScans` of frames that reference that row, and only for rows referenced by at least one MS1 frame.

  ## 6. Emptied-frame identity with the preprocessor pipeline is asserted, not demonstrated

  **Location:** the claim "an emptied frame stays with an empty Ion Mobility array" (`DnoiseRun` docstring) vs the validation line "equal to SpeXtractor run on dnoise's own filtered .d files". The `-perf:ms1_trace_bands 1 ... with emptied frames completes` run proves only no crash.

  An emptied-but-present MS1 spectrum is still a **scan** to MassTraceDetection (the Ms1Prune docstring makes exactly this point for min_sample_rate). If the .d loader *skips* zero-peak MS1 frames when reading dnoise's filtered files, the in-tool path and the preprocessor path diverge precisely when `total.emptied > 0`. If D and TNBC had `emptied == 0`, the digest equality never exercised this. The peptide numbers carried into the help text (−4.3%/−4.0%, +1.5%/−0.5%) rest on that equivalence.

  **Fix:** state whether D/TNBC emptied any frame; if not, construct a small .d (or pick a frame/params) where a frame empties and digest-compare in-tool vs preprocessor. Also pin what the loader does with zero-peak MS1 frames.

  ## 7. Help-text memory and wall figures were measured on a different configuration than the one they describe

  **Location:** `dnoise:ms1` help: "peak memory D 26.46 -> 22.41 GB (-15%), TNBC 009 34.67 -> 25.41 GB (-27%); wall time about -15%" — "measured with dnoise run as a preprocessor ... and carried over because this in-tool path gives digest-identical output". Fix-pass item 11 corrected help figures, but these remain preprocessor numbers.

  Digest identity does not imply memory identity: the in-tool path adds `DnoiseRun::Work` per thread — by the code's own comment ~45 B per raw point — inside the MS1 batch phase that already holds ~3.5 GB of raw buffer on D. At 100 threads and ~690k points/frame that is roughly +3 GB of transient scratch in exactly the phase that sets the peak. The shipped default's peak may be higher than the quoted 22.41/25.41 GB, possibly erasing part of the claimed −15%/−27%.

  **Fix:** measure the in-tool default at 100 threads on both files and put those numbers (or no numbers) in the help text.

  ## 8. The fallback reset still leaks diagnostics, and two accumulation paths need verification

  **Location:** the new reset block (`ms1_map = PeakMap(); ms2_by_window.clear(); cstat = ...; ms1_prune.reset(); dnoise.total = ...; ledSet_(LC_MS1MAP,0); ledSet_(LC_SLAB,0)`).

  The core fix is right (it eliminates the double-load; good). What it does not touch:
  - `ms1Hist_()` counters: batches flushed before the failure already added their picked-peak histograms; the resident path does not re-count, so the `[ms1-hist]` log line after a fallback counts a partial run. Diagnostic only, but it is exactly the kind of row the reset exists for.
  - `phase_stats_()["LOAD(stream)"]` / `flush_wall_()` accumulate the failed attempt; the phase report then mixes stream and resident time. Cosmetic.
  - Verify, from code not inlined here: any ledger row charged during streaming consume other than LC_MS1MAP/LC_SLAB (e.g., the compact-store byte charge per window slab growth) must be zeroed too, and `LedCharge _raw(LC_SCRATCH, raw_b)` in flushMS1_ must un-charge in its destructor when the parallel loop rethrows — if LedCharge is not strictly RAII, LC_SCRATCH leaks raw_b per failed batch.

  **Fix:** reset the hist counters and either reset or annotate the phase rows; audit the ledger for other rows charged in `consume`/flush and add them to the reset.

  ## 9. Non-finite-m/z spectra are sorted before the "kept whole" bail

  **Location:** `Ms1Prune::frame`: `s.sortByPosition()` runs unconditionally at the top; the `!finite` early-return happens after the counting pass. The comment says such a spectrum "stays whole", and fix 8 is listed as "frames with a non-finite m/z are not pruned" — but the sort has already reordered it (std::sort with a NaN in the comparator produces an unspecified, input-dependent permutation), and the stride-97 sample is taken from that new order. With prune off, the same spectrum reaches the band builder in picked order. So on NaN-carrying input the prune can change peak order *and* edge samples while claiming to leave the spectrum untouched — precisely the length/order-dependent lower_bound behaviour the comment worries about. No test exercises `bad_mz` (check 19 asserts it is 0).

  **Fix:** detect non-finite m/z during a pre-scan *before* `sortByPosition`, and return before sorting and before sampling (the sample offsets for detectTraces_ must then come from the unsorted spectrum, matching what the unpruned path samples). Add a fixture with a NaN m/z asserting prune on/off identity and `bad_mz > 0`.

  ## 10. `std::atof` for `corr` is locale-sensitive — the fix pass hardened parseF64 against exactly this and left atof

  **Location:** TdfLoad.h `f.corr = 100.0 / std::atof(...)` vs fix 5 ("parseF64 uses one classic-locale istringstream path ... a Qt application may have set a decimal-comma C locale"). Under a decimal-comma locale, `atof("16.6")` yields 16.0, corr is wrong, and the uniqueness check then refuses the run (fail-closed, but spuriously). The gate's own parsing was fixed for this scenario; the intensity correction — the other place the same sqlite text is parsed — was not.

  **Fix:** use `detail::parseF64` (or `strtod_l`/from_chars) for AccumulationTime too — with the caveat from finding 1 that you must first confirm opentims' own parse, since bit-identity, not correctness, is the contract.

  ## 11. Smaller items

  - **Corrected intensity ≥ 2²⁴ refuses the run** (`v < 16777216.0f` guard → `hits == 0`). Principled (float32 genuinely cannot represent those counts, inversion is ambiguous), but it means the in-tool default refuses data that dnoise-as-preprocessor filters fine. Neither the help text nor the error message states this bound; a bright-point file fails hours in with "not opentims' correction of exactly one raw count (0 found)", which does not say *why*. Add the bound to the error text and help.
  - **dnoise-off output identity is spectra-only**: the header gains `spx:dnoise_ms1/_params/_points` even when off, so pre-stage-2 files are not byte-identical — only the digest is. The validation language ("the old pins ... identical [det] lines") is accurate; just make sure no downstream gate byte-diffs whole mzMLs.
  - **`checkLoader` validates a last-value global** (`BrukerTimsFile::lastMzCalibration()`): a hypothetical mid-run model switch would slip past it, but the per-point 1e-6-bin TOF check then refuses, so this stays fail-closed. Fine as is; worth a one-line comment.
  - **Check 20 brittleness**: `assert "[dnoise]" not in log_off` fails if any future unrelated `[dnoise]`-prefixed line is added; scope it to the specific skip/summary lines.
  - **Streaming dnoise+prune interplay is untested in the suite** (per-batch `checkLoader`, cross-batch sample offsets, `dn_work` sizing under `schedule(dynamic,1)`, emptied frames in flushMS1_) — acknowledged in the suite header for the prune, but stage 2 adds the dnoise half and it is likewise cluster-gates-only.
  - **`num_scans`/`num_peaks` casts in TdfLoad.h** (`(std::uint32_t)sqlite3_column_int64(...)`) have no range check, unlike the Id checks around them; corrupt values wrap (they degrade to refusals downstream, so this is hygiene, not a hole).

  ---

  ## Areas that are clean

  - **Fail-closed architecture:** refusals move to setup() (tdf reads, gate build, corr invertibility, scan separation, `trace:native_ms1_neighbors > 0`, TOF-axis availability) — milliseconds, before the load. Per-point failures throw `DnoiseError`, are captured inside both OpenMP loops (`pick_err`/`ms1_prune_err` criticals), rethrown serially, and the dedicated `catch (const DnoiseError&) { throw; }` correctly sits ahead of the BaseException fallback so a refusal never triggers a wasteful resident re-read. The `parallel → single(try/catch) → rethrow outside the region` pattern around `detectTraces_` is correctly formed (the single construct ends the parallel region; the rethrow is serial, with the implicit single barrier ordering the write of `ms1_err`).
  - **Determinism:** per-frame `dn_cnt[i]` merged in index order, per-thread scratch is pure working memory, the prune sample offsets are fixed before the parallel loop, and `total.cpu` (thread CPU time) reaches only the log, never the stamps — so stamps and output are thread-count-independent. The two-pass chain in the refactored `Ms1Prune::frame` (count, then collect only if it shrinks) preserves the kept set exactly and the NO_CHAIN control correctly walks from dropped links.
  - **`scanOf` binary search:** the `n -= h` unconditionally idiom is correct (superset narrowing never moves `b` past the last entry ≤ v); with the setup-time > 4e-6 separation guarantee against a 1e-6 tolerance, nearest-match is unambiguous, and a hypothetical off-by-one scan convention cannot silently match (steps ≥ 8.8e-4 ≫ tol) — it refuses. Good fail-closed design.
  - **`parseF64` rewrite (fix 5):** grammar checked first, single classic-locale conversion path, range contract checked on the value (so library differences in failbit-on-underflow don't matter), `0e999` vs `1e-999` distinguished via the nonzero-mantissa track. Clean, and self-checking via the pinned gate boxes on CI.
  - **`denoiseMs1Frame` hardening (fix 7):** the n/num_scans bounds now fire before `keep.assign` and before any allocation or point access, as documented; given `num_peaks` is u32 the n-bound is in practice unreachable, which is fine.
  - **Options registration:** valid strings, min bounds on all numeric dnoise options, the previously missing `tile` subsection registered, `dnoise` subsection registered (no ElementNotFound path). String "true/false" matches the file's existing convention (perf:ms1_prune).
  - **CMake:** `test_dnoise_ms1` builds and registers in both the full and TESTS_ONLY builds with the no-contract flag, `enable_testing()` ordering is correct, and the MSVC absence of the flag is backstopped by the pinned-box test failing on Windows CI if contraction ever occurs.
  - **Tests 19/19b/19c:** genuinely sensitive, not vacuous — 19 pins the witness mechanism with an exact no-witness delta (+1 trace, +1 precursor, changed band spectra) and asserts the fixture actually exercises the prune (`picked > kept`, `wit > 0`, `at_noise == 3`); 19b pins interior links with an exact 26-band × 6-frame deficit and an edge-stability check; 19c pins the whole sort pipeline against the ascending reference at 2 and 48 bands, prune off and on. These are well-constructed.
  - **Fallback reset core:** discarding `ms1_map`/slabs/`cstat`/prune state/dnoise counters and zeroing the two ledger rows fixes a real double-load bug ("loaded twice ... 'not in retention-time order'"); `DnoiseError` bypassing the fallback is the right semantics.

  The two findings I would act on before anything else are **1** (the inversion's arithmetic contract with opentims — the only path I found that can *silently* diverge from dnoise's kept set) and **3** (header restore in the deploy script — a live operational drift mechanism, worsened by this change).

