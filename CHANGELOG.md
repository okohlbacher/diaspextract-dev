# Changelog

## [Unreleased]

### Changed
- **`charge:min_charge` now defaults to 2**, dropping singly-charged precursor hypotheses before
  extraction. They are ~30% of emission and ~1.7% of peptides, and removing them GAINS peptides on
  both search engines on all three benchmark files (Sage +0.8/+2.7/+1.4%, MSFragger +1.2/+5.4/+0.9%)
  while cutting emission ~30% and runtime 17%. Entrapment FDR stays inside the previous 95% interval
  on every file. Set `charge:min_charge=1` to restore the previous behaviour.

### Added
- `SPEXTRACT_ISO_COLLAPSE` (experimental, default off): collapses precursor hypotheses on the isotope
  lattice before extraction. Measured on S30 and NOT adopted -- it loses peptides at every setting,
  and loses more on top of the charge gate. Kept for reproducibility of that finding.
- `bench/iso_dup.py`, `bench/iso_collapse.py`, `bench/iso_sim.py`, `bench/iso_loss.py`,
  `bench/iso_guard.py`: the isotope-duplication census, collapse-rule evaluation, content-similarity
  test and loss trace behind those results.

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

### Scoring / assembly
- **E5:** `apportion` and `rp_max` now go through the same emitted-intensity weights as the default path
  (`weighted_()`); they had silently bypassed `corr_power`/`im_weight`, so every earlier A/B of those flags was
  confounded. First clean apportion run: -3.9% peptides (falsified again; NNLS cut).
- **Reported m/z of every trace is now the APEX member's m/z** (`SPEXTRACT_MZ_ESTIMATOR=apex`, the new default;
  `mean` restores the OpenMS intensity-weighted centroid): S30 +2.6% Sage (12,537 vs 12,217) and +4.1% MSFragger
  (11,927 vs 11,463) with the paired precursor mass error vs diaTracer +1.12 -> +0.78 ppm. Both-engines gate passed;
  generalises: S08 +4.4% (10,789), S23 +2.7% (10,156); mean ratio vs diaTracer on Sage 105.1% -> 109.2%;
  entrapment of the apex arm 1.28% [1.03-1.53] at nominal 1%.
- Under test (env switches, defaults unchanged): `SPEXTRACT_PICK_MZ_MODE=seed|top3` (pick-level m/z; the -2.4 ppm
  fragment offset vs diaTracer is upstream of the trace estimator), `SPEXTRACT_DROP_PREC_ISO=1` (drop the precursor's
  M+1..M+3 from fragment lists; 28%/25% of spectra carried them -- FALSIFIED, -2.3%, keep off), `SPEXTRACT_MZPEAK_EXACT` (now the default; `=0` accepts the two-point m/z),
  `SPEXTRACT_MIN_ISOTOPES=k` (precursor gate by envelope depth; k=3 = -39% emission, -23% wall, MSFragger -0.9%, Sage -6.4%),
  `SPEXTRACT_PRECURSOR_LIST=<tsv>` (emit only precursors matching a reference list), `SPEXTRACT_BACKFILL_RAW=N` /
  `SPEXTRACT_BACKFILL_MAXFRAGS=K` (add the N most intense untraced raw peaks of the apex frame inside the IM band:
  N=50 lifts MSFragger to 90% of diaTracer at -2.6% Sage; faint-tail-only variant under test).
- Output-identical: band partition by binary search (R3), early skip of fragments below `min_corr_pts` support.
- Help texts of falsified flags (`rp_max`, `consolidate`, `merge`) now say so; `charge:iso_im_tolerance` help
  no longer contradicts its default.

### Benchmark findings
- MSFragger gap is per-precursor CONTENT of the faint tail: same precursor population as diaTracer -> 85.0%; emission -39% -> 84.8%;
  dt-only peptides are searched but short by ~2 of ~9 matched ions that never become a trace; raw apex-frame peak
  backfill recovers 1,151 of them (MSFragger 85.6% -> 90.0%). FragPipe rescoring (Percolator, MSBooster off for both) gives 13,211 vs diaTracer
  15,947 peptides (82.8%; raw-hyperscore walk 85.6%) -- rescoring lifts both tools and leaves the ratio; ours has
  8.6 PSMs/peptide vs 2.0. Entrapment of the shipping arm: 1.28% / 0.95% / 1.32% at nominal 1% on S30/S08/S23.
- Falsified today (kept in docs so they are not re-proposed): apportion (clean, -3.9%), precursor-isotope stripping
  (-2.3%), median/seed/top3 m/z estimators, 48 MS1 trace bands (slower, not output-identical), MALLOC_ARENA_MAX=4.

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
