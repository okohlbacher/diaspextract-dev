**One release blocker; no demonstrated spectrum or `spx:` regression on stable, readable inputs.** Findings ranked below. No files changed.

1. **Blocker — `CHANGELOG.md:1311` — exported in-house results remain.** The public CHANGELOG includes dataset A/B/D names, peptide counts, timings and memory figures. Other examples occur at lines 95, 353, 619 and 1380. These are inherited entries, but `.export-private` does not exclude them, so the release violates invariant 5. **Actual export leak**, independent of input data. No matches for the other prohibited names were found in exported files.

2. **Should-fix — `CMakeLists.txt:74` — retained mzPeak build configuration can stop working.** A fresh configure with `-DMZPEAK_ROOT=/checkout`, whose only library is `/checkout/build-release/libmzpeak.*`, succeeded before and now fails to find it. `buildfix/` loses the same support. This is documented in the changelog, but it is a substantive compatibility change beyond boilerplate cleanup. **Real build scenario**; existing caches containing `MZPEAK_LIB` can conceal it.

3. **Should-fix — `docs/options.md:223` — the documented mzPeak escape requires another option.** With `DIASPEXTRACT_MZPEAK_EXACT=0` and otherwise default options, `mzPeakRunMeta()` skips exact calibration entirely—even when available—then `src/diaspextract.cpp:4746` refuses because `m->exact` is null. It does not reach the advertised automatic OpenMS fallback. Document the need for `-trace:detector openms` and that `0` disables exact recovery unconditionally. **Real mzPeak scenario in a supporting build**; documentation regression, not newly introduced runtime behavior.

4. **Should-fix — `docs/options.md:173` — `core`/`sum` intensity descriptions omit a consequential fallback.** When an admitted fragment has no positive intensity inside the requested integration frames, `src/diaspextract.cpp:3943` substitutes its nearest real point outside that interval. Consequently, the output is not always the stated sum; it also receives the subsequent intensity weights. Restore the fallback qualification in the reference and help. **Real sparse-fragment scenario**, relevant to interpreting quantitative output.

5. **Should-fix — `docs/options.md:165–166` — twin-fold criteria are materially underspecified.** Cross-frame `bin`/`ext` matching tests **0.05 ppm**, not discrete flight-time-bin equality (`src/diaspextract.cpp:2410`); pairs across ownership-cell boundaries remain separate (`:2412`). The RT threshold is `(n + 0.5) × cycle`, not exactly `n` cycles. For example, otherwise matching twins on opposite sides of a cell boundary will not fold despite satisfying the documented criteria. **Real boundary scenario**.

6. **Note — `src/diaspextract.cpp:5460` — M-17 removes recovery from a transient calibration-read failure.** Consider mzML with parseable frame IDs and a valid, uncompressed TDF sidecar: its SQLite database is temporarily locked during preflight, then readable by the end of loading. Previously the second candidate loop could select integer detection; now the run falls back to OpenMS. **Theoretical/transient-I/O scenario, not reproduced here**. M-17 is equivalent for consistently readable or consistently unavailable candidates, but not under every changing availability condition.

7. **Note — `docs/options.md:69–70` — automatic minimum length has omitted floors and fallback.** `-trace:min_length_fwhm 0` still imposes half a cycle when estimation succeeds. Fewer than 100 measurable traces in the brightest sampled tenth—or no positive cycle—selects **3 seconds** (`src/diaspextract.cpp:5137–5153`). **Real small/sparse-run scenario**; the rewritten description implies a simpler formula.

8. **Note — `README.md:26` — the diagram’s 3-second gate is not universal at defaults.** Faint precursors use `gate:faint_delta_rt=6`; qualifying fragments more than 3 seconds away can pass. The prose below acknowledges the looser gate, but the chart does not. **Real default-path discrepancy**; stage ordering otherwise looks correct.

The targeted checks that look sound:

- **R3/R4/R9/R11:** retained arithmetic and ordering are preserved; R4’s removed predicates follow from the retained walk, and no intervening consumer reads the defaulted charge before R9’s drop.
- **R12:** acquisition bounds, frame tables, auto-band refusals and ordinary calibration fallback remain equivalent under kept settings.
- **C3:** span merging, co-rank reuse, M-11, M-15, initialized option mirrors and exception consolidation show no retained-path semantic defect. Both `absorbAll_` callers satisfy the new precondition.
- **CI/tests:** no executable reference to a deleted file or unintended assertion loss found. Removing the example-file scan is consistent with deleting both examples. Migration text correctly distinguishes removed CLI options, invalid values and INI rejection.

Validation passed: option-token check, Python calibration goldens, entrapment self-check, parsing all 29 tracked Python files, and AppleClang syntax checks for calibration, denoising and TDF-loader tests. Full runtime identity, mzPeak compilation and Windows compilation were not run.
