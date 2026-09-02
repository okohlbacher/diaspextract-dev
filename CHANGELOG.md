# Changelog

## [Unreleased]

### Runtime
- **MS1 path parallelised** (loader `[speXtract ms1-par]`: batched parallel MS1 decode with per-thread ZSTD contexts and
  `FrameCentroider`, ordered hand-off; consumer `flushMS1_`: parallel MS1 pick). S30/100 threads: LOAD 445 s -> 39 s,
  total 22:22 -> **15:21**; spectrum data byte-identical, Sage peptide set identical.
- Decode-once frame-major parallel MS2 loader (`[speXtract par-load]`), batched parallel MS2 pick; per-phase `[perf]`
  table and `[perf-load]` decode/hand-off/pick timers; `SPEXTRACT_LOAD_ONLY=1` for load-only profiling.
- Falsified and recorded: `MALLOC_ARENA_MAX=4` (10x slower at 100 threads), loader batch depth (64/256/1024 flat).

### Input
- **Streaming `.mzpeak` input** (`src/MzPeakStreamLoad.h`, build-optional `-DMZPEAK_ROOT`) on the mzPeak C++ library
  (OpenMS/mzpeak fork trunk); reads ims-compact archives with per-window mobility bands (works around name-only band
  params and NULL `precursor_index`). Benchmarked: not faster (the floor was the MS1 pick), and -11.7% peptides from the
  archive's two-point TOF transform (fragment error +10 ppm) -- see docs/RUNTIME-PLAN-2026-09-02.md and the converter
  handoff. Output stamps `spx:mz_calibration = mzpeak_two_point_transform ...` for this path.
- Library build recipe for GCC 13 / Arrow 23 (`scripts/build_mzpeak_lib.sh`, `patches/spx_ranges_to.h`,
  `patches/mzpeak-cpp-arrow23.py`).

### Determinism
- `bench/semantic_digest.py` now stops at `</spectrumList>`: the trailing `<indexList>` byte offsets shift with any header
  length change and had falsely flagged two spectrum-identical files. Loader batch size does NOT change content
  (922,902 spectra, 0 differ; Sage set identical), and **neither does the thread count**: threads 8 == threads 100 on two pairs with the fixed digest, retracting the 2026-09-01 "thread-count dependent" finding. Output is byte-identical spectrum data at any thread count and loader batch.

### Docs
- `docs/BACKLOG-ANALYSIS-2026-09-02.md`: every open issue with status, root cause, fix, gate; reviewed by kimi + codex
  (`docs/reviews/`). Confirmed today: apportion/rp_max bypass corr_power (E5); 28% of spectra carry the precursor M+1 as a
  fragment (C9); false mzPeak calibration provenance (fixed).

## v0.2.0 — 2026-09-02

First release with a verified calibration, tests, and CI. Supersedes v0.1.0, which was tagged on the
day-one commit and never represented a working state.

### Headline: exact, license-free TOF -> m/z calibration
The Bruker `.d` reader converted TOF to m/z with a two-point linear-in-sqrt chord that is **-5 to -11
ppm biased** (m/z dependent). We derived the exact ModelType-1 model from the constants in each
file's own `MzCalibration` table and verified it to **2.5e-5 ppm** against Bruker's library:

    t_ns   = tof * DigitizerTimebase + DigitizerDelay
    C1_eff = C1 * (1 + dC1 * (T1_ref - T1_frame) / 1e6)
    t_ns   = C0 + (1e6 / sqrt(C1_eff)) * sqrt(m) + C2 * m

The widely-copied open implementation (timsrust-calibration, adapted then disabled by mzdata as "not
consistently better") **drops the `C2*m` term** -- worth -11..-40 ppm. That omission, not translation
subtlety, is why the port underperformed. Reported upstream.

Measured on three diaPASEF files, closed search: **+6-11% Sage peptide identifications**, no vendor
library. This is an identification-YIELD effect, not better spectra (emission moved -0.2%): mass
error is a feature of Sage's discriminant. Since diaTracer always carried vendor-calibrated masses,
every earlier head-to-head was biased against the open path -- this removes a self-inflicted
handicap rather than establishing a lead.

### Benchmarks (3 files, both engines, identical settings; docs/BENCHMARK-MATRIX-2026-09-01.md)
| | S30 | S08 | S23 | vs diaTracer |
|---|---|---|---|---|
| Sage peptides @1% FDR | 11,976 | 10,333 | 9,891 | mean 105.1%, 95% CI [93.0, 117.3] -- consistent with PARITY |
| MSFragger peptidoforms @1% | 11,463 | 11,465 | 9,404 | mean 85.0%, 95% CI [76.7, 93.2] -- a supported DEFICIT |
| median precursor mass error | +1.5 | +3.2 | +2.3 ppm | diaTracer -1.4 / +0.3 / -0.6 |
speXtract also emits ~1.32x more spectra, so per-spectrum efficiency favours diaTracer. The MSFragger
gap survives perfect masses and is therefore search/detection-side.

### Safety
- **Fails closed.** ModelType != 1, `C2 <= 0` (a NULL/text C2 reads as 0.0 and selects the known-bad
  pure-sqrt law), `dC2`/`C3`/`C4` != 0, implausible `C1`, NaN, multi-row tables, or an unreadable
  `Frames.T1` are all errors, not silent approximations. `SPEXTRACT_ALLOW_CHORD_FALLBACK=1` (exactly
  "1") opts back into the biased chord.
- **Provenance.** Every emitted mzML records `spx:mz_calibration` =
  `tdf_table_modeltype1` | `bruker_sdk` | `legacy_chord_APPROXIMATE`, via an exported accessor that
  works across the shared-library boundary.
- Out-of-model inputs return NaN, never a plausible-looking 0.0.

### Tests and CI (first in this repo)
- `tests/test_calibration_cpp.cpp` -- 60 vendor-derived golden cases against the **shipped** header,
  round-trip inverse, and every rejection path. Ablation guards prove the suite can catch the
  known-bad implementation (39.4 ppm) and the temperature term (0.67 ppm).
- `tests/test_calibration.py` -- an independent re-implementation as a cross-check.
- `tests/test_entrapment.py` -- estimator CI, determinism, NaN-on-empty.
- `.github/workflows/tests.yml` runs all three. None needs a vendor library, cluster, or raw data.

### Determinism (scoped honestly)
Bit-reproducible **at a fixed thread count** -- verified by `bench/semantic_digest.py`, which compares
spectrum data and ignores the wall-clock stamp and the recorded parameters (two runs can never be
byte-identical otherwise; this also explains a July md5 mismatch left unexplained at the time).
Output DOES differ across thread counts, and last-ulp code changes cascade to ~2% in peptide counts.
The 0.06% noise floor in the decision rule is a SAME-BINARY figure.

### Also
- Entrapment estimator corrected (peptide-hypothesis ratio 0.6805, foreign-only counting, bootstrap
  CIs): actual FDR at nominal 1% is ~1.0-1.45%, not the ~2.3% previously reported.
- `assembly:corr_power=2` default (validated +8-10%, three files, both engines).
- Spectrum collapse falsified (-20..-60% peptides at every operating point, intrinsic to both tools).
- `scripts/apply_openms_patches.sh`; `scripts/sync_cluster.sh` refuses to deploy into an unpatched
  tree; evidence chain archived to durable storage.

### Known limitations
- Verified on ONE cohort/instrument; the three golden files share ONE MzCalibration vector.
- Public-data replication not yet done; every claim is single-cohort.
- A +1.5..+3.2 ppm residual remains, 2-4 ppm above diaTracer on the same files. It survives every
  calibration path, so it is downstream of the m/z axis (centroiding / monoisotope reporting).
- Peptide counts are partly a mass-calibration measurement: compare only at similar residual ppm.
