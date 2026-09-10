The calibration extremum is correct. The main defect is that the nominal acquisition ceiling is not a guaranteed peak-bin bound—and the one-cell path can turn an exceeded bound into an out-of-bounds write.

1. **High — Above-bound peaks can abort or corrupt memory.** [spextractor.cpp:4257](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4257), [spextractor.cpp:4589](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4589). A supported calibration counterexample exists in the local [SDK fixture](/Users/kohlbach/Claude/mzPeak/mzPeakConverter/tests/fixtures/tdf_2485_sdk_golden.json:177): final digitizer bin `636030` maps to `1700.00316175`, while the documented nominal upper `1700` maps to `636029.219…`, rounding to `636029`. A frozen window containing that frame therefore need not enclose a valid final-bin peak. This establishes a possible input, not an observed D/TNBC failure.

   The picker does not extrapolate beyond its input cluster under positive weights, but neither picking nor compaction enforces `MzAcqRangeUpper`. With multiple cells, the superset check throws. With one cell—including `tile:cells_per_tile=1`—the check is skipped; an above-threshold seed at `thi+1` makes `bandOf()` return `nb`, indexing beyond `cnt` at [spextractor.cpp:1143](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1143).

   **Fix:** implement the judged plan’s total outer-band coverage, cell-local TOF-index bounds, and logged range violations. Preserve the acquisition-derived interior edges. Widening them from resident peaks would reintroduce tile dependence. An unconditional assertion is an immediate memory-safety fix, but still rejects otherwise valid peaks.

2. **Medium — Unchecked TEXT parsing introduces failures even under `slab`.** [TdfLoad.h:43](/Users/kohlbach/Claude/speXtractor/src/TdfLoad.h:43). SQL `NULL` reaches `atof(nullptr)`; `"inf"` and `"1e309"` pass the ordering check; `"1700junk"` is accepted as `1700`. Nonfinite or unrepresentable bounds then reach `tofOf`/`llround`. Both modes invoke this reader, so malformed optional metadata can break the formerly working default.

   **Fix:** reject NULL, require complete numeric conversion and finite ordered values, and check TOF representability before rounding. Preserve the actual diagnostic.

3. **Medium — Missing metadata is refused after substantial work.** [spextractor.cpp:4240](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4240). A `.d` with valid calibration but absent range rows completes loading/picking, MS1 tracing, and precursor inference before acquisition mode throws. The refusal is reachable, but not early.

   **Fix:** preflight required metadata before peak decoding; for mzPeak, validate immediately after loading its calibration metadata. Also report that a missing **lower** value can invalidate the range—the current message mentions only upper.

4. **Medium — TileProbe can silently override the selected option and invalidate its stamp.** [spextractor.cpp:4532](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4532), [spextractor.cpp:4299](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4299). With `SPEXTRACTOR_WINDOW_FILE` set, the body replaces acquisition edges after the paired log announces them “in use”; the header still says `spx:band_edges=acquisition`. Old slab rows can therefore make an acquisition-labelled experiment use slab bands.

   **Fix:** reject conflicting overrides or resolve and stamp the effective source centrally. The supplied gate script’s explicit `unset` protects that particular chain.

5. **Medium — TNBC lacks a control check on this build.** [chain_step3a.sh:33](</private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/step1b/chain_step3a.sh:33>). Comparing against historical counts cannot isolate this small change unless the current slab output is demonstrably the historical input. Earlier `f0502f33` matches support continuity, but do not verify `1641a00`.

   **Fix:** rerun TNBC **slab extraction** on this build and compare the full semantic digest. Historical search results can be reused if spectra and search binaries, configurations, databases, preprocessing, and scorers match. Otherwise rerun the searches too. A different extractor binary alone does not invalidate an identical spectral control.

6. **Medium — “Within run-to-run spread” needs a numerical definition.** [BASELINE.md:67](/Users/kohlbach/Claude/speXtractor/docs/BASELINE.md:67), [chain_step3a.sh:30](</private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/step1b/chain_step3a.sh:30>). The recorded repeated searches found zero variation for both engines. Changed counts cannot automatically be dismissed as search noise.

   **Fix:** apply independently to each acquisition: corrected, unrounded `E_acq ≤ E_slab + 0.3 percentage points`, and each engine within a prespecified numerical margin. The recorded TNBC baseline implies approximately **1.38% maximum entrapment**. Literal zero measured spread permits zero count difference; any nonzero tolerance needs an explicit scientific justification. Gains elsewhere and overlapping confidence intervals do not override a failed criterion.

7. **Medium — The collection script can finish despite failed extraction or searches.** [chain_step3a.sh:6](</private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/step1b/chain_step3a.sh:6>). Only `set -u` is enabled. Extraction failures are printed and ignored; pipelines mask failures; missing Sage results can produce an empty peptide file; `STEP3A_DONE` is unconditional.

   **Fix:** require successful commands, complete outputs, and valid metrics before reporting acceptance. Distinguish collection completion from gate passage.

8. **Medium — The chain discards the evidence needed to check the claimed small perturbation.** [chain_step3a.sh:30](</private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/a01a4fa9-478a-46f9-841b-a62735f601ab/scratchpad/step1b/chain_step3a.sh:30>), [judge.md:15](/Users/kohlbach/Claude/speXtractor/docs/reviews/2026-09-10-tiled-reader-plan/judge.md:15). Each mzML is deleted before a paired spectrum comparison. D Sage overlap alone cannot distinguish a tiny perturbation from substantial spectrum turnover with similar identification totals.

   **Fix:** retain outputs through `mzml_specdiff.py`, record lost/gained/common peptide sets, and finish the planned acquisition-edge pins before using P1 for step 3b. The expected approximately `1e−5` changed spectra is a diagnostic expectation, not an established acceptance threshold.

The following attack lines hold up:

- **Calibration direction:** from [TdfMzCalibration.h:118](/Users/kohlbach/Claude/speXtractor/src/TdfMzCalibration.h:118), `∂tof/∂b = sqrt(mz+C4)/DigitizerTimebase > 0` on the physical branch. Larger `b` gives larger TOF. Maximizing converted bounds over the frozen table is correct; those factors match the slab conversion.
- **Lower bound:** `tlo=0` encloses normally converted unsigned bins, including the nonpositive-TOF clamp.
- **Metadata lifetime:** embedded and gzipped `SPEXTRACTOR_MZPEAK_TDF` sources share the temporary-file path. The new range read occurs at [MzPeakStreamLoad.h:140](/Users/kohlbach/Claude/speXtractor/src/MzPeakStreamLoad.h:140), before removal. Missing tables/rows safely leave the range unavailable and preserve ordinary slab operation.
- **Slab identity:** the selected min/max pair is unchanged. `frozen.at(k).b` is read-only during the parallel loop; distinct `wbands` entries are precreated. Roughly 115,000 conversions are negligible beside peak processing, although I did not benchmark that overhead. The old `[tof]` line remains; the paired line is additional. Full-file bytes change through the new header stamp—spectral semantic identity is the appropriate comparison.
- **Step 3b:** the block **cannot yet run without slabs**: it still dereferences, converts, and scans each resident slab at [spextractor.cpp:4248](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4248). Build acquisition `wbands` directly from frozen tables and the axis, and make resident comparisons optional. Beyond this block and TileProbe, the body consumes `wbands`; its remaining extrema scan is cell-local validation. The planned cell-local search-index change remains outstanding.

Validation: reviewed `1641a00`; Python calibration golden tests passed. Existing synthetic fixtures still lack acquisition-range rows, so they do not exercise successful acquisition mode.
