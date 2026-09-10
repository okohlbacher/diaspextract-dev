# Stage-2 review: dnoise MS1 inside the tool, default on, and the stage-1 fix pass (2026-09-10)

**What was reviewed:** a frozen snapshot of `src/spextractor.cpp` (the in-tool dnoise hook `DnoiseRun`, the MS1 prune
after the stage-1 fixes, the stream-fallback reset) and `src/DnoiseMs1.h`, plus `src/TdfLoad.h`,
`scripts/sync_cluster.sh`, `CMakeLists.txt` and e2e checks 19-20.

**Reviewers:** all three read the self-contained brief (`brief-selfcontained.md`, 142 KB), and none was silent:
codex 10.3 KB, kimi 18.0 KB, vibe 6.9 KB.

**Verification:** seven read-only verifiers checked every finding against the snapshot and the OpenMS and opentims
sources actually built. They used exhaustive brute-force probes, locale and SQLite-corruption probes, and a
fake-node deploy harness. Full verdicts, evidence, fixes and proposed tests are in `verification.md`.

The fixes are fix pass G (arm `dnoise_s2c`); see "Fix pass G" below.

## Confirmed or partly confirmed

| # | finding | severity | fix pass G |
|---:|---|---|---|
| 1 | A failed SQLite prepare reads as "no rows", and any non-ROW step code ends a row loop as if complete. A corrupt `analysis.tdf` can therefore build a partial window gate (1,554 of 3,000 windows in a probe) or none at all (codex 2) | medium | Check every prepare and require `SQLITE_DONE`. Decide whether the optional table exists from `sqlite_master`. Name `sqlite3_errmsg` in the refusal. |
| 2 | No automated test covers `DnoiseRun`'s point recovery: TOF from m/z, scan from the float32 1/K0 table, raw count from the corrected intensity (kimi 2, codex 11) | medium | Move the recovery into `spx::dnoise::recover` in the header and pin it with metadata-only goldens from D and TNBC 009. |
| 3 | `sync_cluster.sh` uploads before taking the remote lock, and a failed test or build restores only the `.cpp`, so a later build can mix versions (codex 3, kimi 3) | medium | Transactional deploy: stage, lock, test, promote, build, re-check hashes, then commit the provenance. A failure rolls back every promoted input. A fake-node harness passes 18/18 and four mutants fail it. |
| 4 | An AccumulationTime above 100 ms (correction < 1) maps several raw counts to one intensity and refuses mid-run. An intensity of 2^24 is refused with an unclear message (codex 4) | low | Refuse a correction below 1 at setup, and name 2^24 in the frame refusal. |
| 5 | AccumulationTime was parsed with `atof` in the ambient locale, whereas opentims parses it under a "C" locale guard. A comma-decimal `LC_NUMERIC` turns 100.042 into a silent correction of exactly 1 (kimi 10, vibe 2). No code path sets such a locale today. | low | Classic-locale `parseF64` over the whole text; fail closed. |
| 6 | The `#error` guard misses `-freciprocal-math`, `-funsafe-math-optimizations`, `-fassociative-math` and `-fno-signed-zeros` (vibe 3) | low | Extend the guard and add negative-compile CI steps. No runtime canary. |
| 7 | `-ffp-contract=off` applies to the whole tool, not only the port (codex 10) | low | Keep it tool-wide, say so in the CHANGELOG, and run the dnoise ctest in the full-tool CI build. |
| 8 | `NumScans` and `NumPeaks` are narrowed to u32 without a range check: -1 becomes 4294967295 (codex 6, kimi 11) | low | Check each row's SQLite type and range before the cast. |
| 9 | The scan-table check runs every TimsCalibration row over the global `MAX(NumScans)`, including rows no MS1 frame uses (codex 5, kimi 5) | low | Check each table over the largest scan count its own MS1 frames need. |
| 10 | The TOF axis model is checked only at the first batch, and on the resident path only after the whole load (vibe 4) | low | Check at the first MS1 spectrum. Refuse at setup when the Bruker SDK would calibrate m/z. |
| 11 | The resident loop skips a spectrum without IM data before dnoise sees it, and nothing checks that every MS1 frame was filtered exactly once (codex 1) | low | Run dnoise before the skip. A seen bitmap refuses duplicates and missing non-empty frames. |
| 12 | The resident dnoise scratch (about 3 GB at 100 threads) lives on into tracing (codex 7) | low | Free it right after the pick. |
| 13 | After a stream fallback, `[ms1-hist]` keeps the failed attempt's counts (codex 9, kimi 8) | low | Zero them in the reset. |
| 14 | The prune sorts and samples a spectrum before it notices a non-finite m/z (codex 8, kimi 9, vibe 6) | low | Refuse a non-finite MS1 m/z right after the pick, prune on or off (e2e check 19d). |
| 15 | The `dnoise:iterations` help says 0 keeps every point, but the halo filter and the window gate still run (codex 12) | low | Correct the help text; add a gate-side unit check. |
| 16 | The recovery search bounds are ±1 wider than needed (vibe 5) | none | No change: exhaustive tests show every preimage is inside them either way. |

## Refuted

- **kimi 1, "the recovery can silently diverge from opentims at .5 ties".**
  - opentims computes `100.0 / atof(text)` and `double(raw) * correction + 0.5` in the same order the recovery
    inverts.
  - A brute force over every raw count below 2^24 found 0 wrong unique recoveries. It covered 17 AccumulationTime
    values, contracted and uncontracted arithmetic, and a correction 1-4 ulps off.
  - What is real is only that two comments misstated the operation order. They are fixed in pass G.
- **kimi 4, "`-ffp-contract=off` does not reach the recovery in the cluster build".** The in-tree flags carry it
  (OpenMS `compiler_flags.cmake`). An `-mssse3` target cannot emit FMA, and the cluster binaries contain 0 FMA
  instructions.
- **vibe 1, "a TOF bin up to 2^32-1 can index out of bounds".** No storage in the port is indexed by TOF: radix
  digits are masked, windows saturate, and gate intervals only compare. An ASan/UBSan probe at the edges was clean.
- **kimi 8 (sub-question), "the scratch ledger charge leaks when the parallel loop rethrows".** `LedCharge` is RAII,
  and every exception is caught inside the region and rethrown serially.
- **vibe 7, "an exception from `detectTraces_`'s serial preamble escapes the `omp single`".** The `try` covers the
  whole call, and the exception is rethrown after the region.
- **kimi 6, "identity for emptied frames was asserted, not demonstrated".** D empties 2 MS1 frames. dnoise's
  filtered file keeps them as zero-peak rows, the reference run loads all 1,343, and the digests match in six arms.
- **kimi 7, "the help-text figures are preprocessor numbers".** They are the in-tool gate runs, byte for byte.
- **kimi, smaller item, "check 20's absence assertion is brittle".** No `[dnoise]` line can be emitted with
  `-dnoise:ms1 false`.

## Fix pass G

Adopted exactly as in the table above.

Skipped on purpose:
- **A runtime canary for the window gate:** add it when arbitrary third-party CXXFLAGS matter.
- **Ledger accounting for the dnoise scratch:** diagnostics only.
- **Relaxing the 2^24 intensity bound:** the largest MS1 intensity in 49 local `.d` files is 145,043.
- **Tightening the recovery loop bounds.**

The rebuild, the digest gates on both files (dnoise on and off), the publication of arm `dnoise_s2c` and a
stage-3 review of the fix diff are recorded in `../stage3-review/`.
