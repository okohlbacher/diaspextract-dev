1. **P1 — Resident loading can bypass MS1 validation.**  
   **Location:** `spextractor.cpp`, resident picking loop: `if (!s.containsIMData()) continue;` precedes `dnoise.frame(...)`.

   A nonempty MS1 spectrum without IM data never reaches the refusal in `DnoiseRun::frame`; the dispatch also skips it. Unless the omitted normalization rejects every such spectrum, the run can succeed with missing MS1 frames and a stamp claiming denoising was applied. The per-frame checks also do not establish that every expected nonempty MS1 frame arrived exactly once.

   **Fix:** Validate MS1 through `dnoise.frame` before the generic IM skip. Track delivered frame IDs and verify completeness and uniqueness against the expected MS1 frames.

2. **P1 — SQLite failures can silently change or disable the window gate.**  
   **Location:** `TdfLoad.h::loadTdfDnoise`, especially the `DiaFrameMsMsWindows` query.

   A prepare failure becomes “no rows”; each row loop treats every result other than `SQLITE_ROW` as successful completion. An I/O error partway through the window query therefore builds a gate from a partial union. A failure before the first row disables the gate entirely because `buildMs1WindowGate` returns without a gate when `usable.empty()`.

   **Fix:** Distinguish an intentionally absent optional table from query failures. Require `SQLITE_DONE` after every row loop, and report `sqlite3_errmsg` with the failed query. Apply this to metadata, calibration and frame reads too.

3. **P1 — Deployment is neither protected by its lock nor fully restored on failure.**  
   **Location:** `sync_cluster.sh`, uploads before `mkdir .../.deploy.lock`, and rollback restoring only `${REMOTE_SRC}.bak`.

   Deploy B can overwrite `.new`, headers or the unit-test source while deploy A holds the lock and builds. A can then record its own hashes against B’s code. Independently, a failed test/build restores the `.cpp` but leaves the new `TdfLoad.h`, `DnoiseMs1.h`, calibration header and other uploads installed. A later build can silently combine versions.

   **Fix:** Upload to a unique staging directory, then acquire the lock before promoting anything. Test/build a consistent staged revision and restore every promoted build input on failure. The SSH quote escaping shown here is correct; the failure is transaction ordering and incomplete rollback.

4. **P2 — Legitimate intensities are refused, including some uniquely recoverable ones.**  
   **Location:** `DnoiseRun::setup` and `frame`, `corr > 0.5` and `v < 16777216.0f`.

   Two concrete cases:

   - `AccumulationTime = 125`, hence `corr = 0.8`: raw counts 2 and 3 both correct to 2. Setup passes, but encountering that intensity refuses the run.
   - `AccumulationTime = 50`, hence `corr = 2`: raw count 8,388,608 produces float intensity 16,777,216. This value is uniquely recoverable under that correction, yet the strict cutoff refuses it.

   The first refusal protects correctness; the second is conservative rejection. Both are compatibility limitations of default-on operation. On the resident path, either can be discovered only after loading the entire run.

   **Fix:** Preserve raw `uint32_t` intensities in the loader interface. If inversion remains, document these restrictions and support larger floats only by checking uniqueness through the complete forward conversion, including the float cast.

5. **P2 — Scan-table validation rejects valid calibration segments outside their actual domain.**  
   **Location:** `DnoiseRun::setup`: every calibration is evaluated over `tdf.meta.max_num_scans`.

   Suppose calibration A is used only by 100-scan frames and calibration B by 1,000-scan frames. A can be monotonic and well separated over its actual scans but develop a pole or reversal around extrapolated scan 500. Setup rejects A even though the loader never evaluates it there. Unreferenced calibration rows are likewise subjected to this test.

   **Fix:** Build recovery tables over the maximum scan count actually needed by MS1 frames referencing each calibration. Retain the global maximum separately for dnoise’s gate construction.

6. **P2 — Frame metadata is narrowed before its range is checked.**  
   **Location:** `TdfLoad.h`, assignments to `f.num_scans` and `f.num_peaks`.

   `MAX(NumScans) <= 1000000` does not exclude negative individual values. A row containing `NumScans = -1` becomes `UINT32_MAX`; the filter’s new upper-bound check explicitly permits that value. `NumPeaks = 2^32 + N` becomes `N`, weakening the purported whole-frame count check.

   **Fix:** Validate each original SQLite integer before casting: scan counts against the supported scan limit, peak counts against the representable range, and NULL/type handling explicitly. Refuse malformed metadata during setup.

7. **P2 — Resident denoising scratch survives into downstream processing.**  
   **Location:** `spextractor.cpp`, resident `dn_work` declaration outside a limited picking scope.

   Unlike the batch-local streaming buffers, these vectors remain alive until the enclosing function exits. Their capacities retain each worker’s largest frame after picking. Using the supplied estimate, 100 workers × 690,000 points × 45 bytes is approximately **3.1 GB** retained during subsequent tracing and assembly. The shown ledger charges also do not include this scratch.

   **Fix:** Scope the resident work buffers around picking and destroy them immediately afterward. Account for their capacity in the scratch ledger. Perform any intended allocator trimming after their destruction.

8. **P2 — The non-finite-m/z fix checks too late to make sorting safe.**  
   **Location:** `Ms1Prune::frame`: `s.sortByPosition()` precedes the finite-value check.

   With ordinary floating-point ordering, a spectrum such as `[2, 1, NaN, 0]` does not satisfy the comparator requirements for sorting. Keeping the spectrum whole afterward cannot repair that operation. The function also samples the spectrum before deciding it contains non-finite m/z values.

   **Fix:** Detect non-finite m/z before sorting. Define consistent handling for both prune modes—preferably an explicit refusal, or a deliberately defined ordering used throughout sampling and tracing. This is an incomplete fix, rather than evidence of a regression on finite benchmark data.

9. **P2 — Fallback still leaves stale MS1 histogram state.**  
   **Location:** `flushMS1_` histogram accumulation and the `if (!streamed)` reset block.

   Successfully flushed batches increment `ms1Hist_()`. A later streaming failure resets spectra, pruning and dnoise counters, but not those histogram counters. The shown resident path does not rebuild the histogram between picking and pruning. Consequently, `[ms1-hist]` can describe only the abandoned streaming prefix.

   **Fix:** Reset the histogram on fallback and populate it on the resident path at the same post-pick, pre-prune stage. Keep elapsed-time statistics for attempted work; those need not be discarded.

10. **P2 — Tool-wide floating-point changes broaden the off-path identity claim beyond the validation.**  
    **Location:** `CMakeLists.txt`: `target_compile_options(spextractor PRIVATE ${SPX_NO_FP_CONTRACT})`.

    This changes contraction behavior throughout the tool even with `dnoise:ms1 false`. Your own comment identifies Apple arm64 as previously contracting by default. A contraction-sensitive calculation near a membership or scoring boundary can therefore change independently of denoising. The cluster pins do not settle this because the supplied text says its OpenMS build already used contraction-off flags.

    **Fix:** Either constrain strict arithmetic to the code that requires it, or validate and explicitly define the new whole-tool floating-point baseline. This is an unresolved portability risk, not a demonstrated mismatch on D or TNBC.

11. **P2 — The supplied tests do not establish the integration’s exact recovered points or keep masks.**  
    **Location:** checks 19–20 and the validation description.

    Checks 19/19b exercise pruning; 19c exercises stored-order normalization; 20 exercises skipping mzML. None directly exercises `DnoiseRun` recovery. Equal kept counts and equal downstream spectra are strong evidence, but different masks can have equal counts and differences that disappear during picking or tracing.

    **Fix:** Add recovery tests against known raw tuples, including multiple calibrations, intensity ambiguity/cutoff cases, missing IM, malformed counts and duplicate/missing frames. Compare recovered tuples and per-frame masks directly with raw data/reference masks. Add failure injection after a completed streaming batch to verify reset behavior.

12. **P3 — `iterations=0` help promises more than the implementation does.**  
    **Location:** registration of `dnoise:iterations`: “0 keeps every point.”

    Zero iterations bypasses streak passes; halo and the window gate still run. A user attempting to disable filtering this way can still lose points.

    **Fix:** Say “0 skips the streak filter; halo and window filtering remain controlled by their own options.”

13. **Clean areas and limits of this review.**  
    Within the accepted intensity domain, the expanded candidate search has no demonstrated missing-preimage or overflow problem. The scan-spacing requirement makes tolerance matches unambiguous. The shown stage order is correct: denoise, pick, histogram, prune. Selection preserves point order and associated arrays, and the count-first prune avoids needless selection.

    The visible per-frame denoising refusals are caught inside both OpenMP loops, and `DnoiseError` explicitly bypasses streaming fallback. The outer MS1 tracing handler does **not** cover task-body exceptions, as its comment acknowledges; those bodies and the top-level exception handler are not supplied, so their containment and exact exit codes cannot be certified.

    Checks 19 and 19b are meaningfully sensitive, with explicit negative controls. Check 19c correctly tests pipeline behavior rather than isolating the prune’s sort. String defaults, subsection registration, the shown stamps, and CMake test registration are coherent. The unit-test source is not inlined, so its assertions and sensitivity under deployment flags cannot be assessed.