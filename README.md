# speXtract

Extraction of pseudo-DDA ("pseudo-MS/MS") spectra from Bruker timsTOF **diaPASEF** data.

An open, BSD-3, standalone alternative to the closed-source [diaTracer](https://github.com/Nesvilab/diaTracer).
The goal is **blind / open search** — finding variants and unexpected modifications that a
library-based DIA tool cannot report, because its search space is enumerated before the search
begins.

speXtract is a standalone application. **OpenMS is a prerequisite, not a host** — the tool links
against an OpenMS installation but lives outside the OpenMS source tree.

## Build

Needs OpenMS with `WITH_OPENTIMS` (to read Bruker `.d`). **Apply this repo's OpenMS patches first:**

```bash
scripts/apply_openms_patches.sh /path/to/OpenMS      # installs src/TdfMzCalibration.h + patches
# then rebuild the OpenMS DIAPseudoSpectra target
```

**Why this is not optional.** Without the calibration patch the Bruker reader converts TOF to m/z with
a two-point linear-in-sqrt chord that is **-5 to -11 ppm biased** (m/z dependent) on every file we
measured, costing roughly **6-11% of closed-search peptide identifications**. The build says nothing
about it; the run log names the calibration used, and every emitted mzML records it in the
`spx:mz_calibration` userParam (`tdf_table_modeltype1` | `bruker_sdk` | `legacy_chord_APPROXIMATE`).
An unsupported calibration table now **fails closed** rather than silently producing biased masses;
`SPEXTRACT_ALLOW_CHORD_FALLBACK=1` opts back into the old behaviour.

Verified against OpenMS `3.6.0-pre-exported-20260717`. Other versions may need the patch rebased.
Optionally, `OPENMS_BRUKER_SDK_PATH=/path/to/libtimsdata.so` uses Bruker's own library instead (an
oracle for cross-checking; not required, not redistributed).

### Optional: `.mzpeak` input (mzPeak C++ library)

Build the library once against the same Arrow/Parquet/libzip OpenMS uses (`scripts/build_mzpeak_lib.sh`;
GCC 13 / Arrow 23 need `patches/spx_ranges_to.h` and `patches/mzpeak-cpp-arrow23.py`, both applied by the
script), then configure speXtract with `-DMZPEAK_ROOT=<checkout>`. Inside an OpenMS source tree use
`patches/openms-topp-mzpeak-cmake.py` instead. ims-compact archives store raw TOF behind a two-point
transform; the loader recovers the exact TDF calibration from the embedded `vendor/analysis.tdf.gz` (or
`SPEXTRACT_MZPEAK_TDF=<analysis.tdf.gz>` for `--no-vendor` archives) and refuses to run without it unless
`SPEXTRACT_MZPEAK_EXACT=0`.

## Run

```bash
build/DIAPseudoSpectra -in sample.d -out pseudo.mzML -threads 64
```

Recommended: preload tcmalloc. It is worth more than the structural memory work in this
repository (measured: -18.4% peak RSS combined, of which compaction alone is -6.1%).

## Where it stands

Measured 2026-09-01 on three diaPASEF acquisitions (one cohort, one instrument), both engines,
identical search settings for both tools. Full matrix: `docs/BENCHMARK-MATRIX-2026-09-01.md`.

| | S30 | S08 | S23 | vs diaTracer |
|---|---|---|---|---|
| **Sage** peptides @1% FDR | 11,976 | 10,333 | 9,891 | 104.0 / 100.9 / 110.5% -- mean 105.1%, 95% CI [93.0, 117.3] |
| **MSFragger** peptidoforms @1% | 11,463 | 11,465 | 9,404 | 82.3 / 83.9 / 88.7% -- mean 85.0%, 95% CI [76.7, 93.2] |
| median precursor mass error | +1.5 ppm | +3.2 | +2.3 | diaTracer -1.4 / +0.3 / -0.6 |
| pseudo-spectra emitted | ~0.92 M | | | ~1.32x diaTracer |

Read honestly: **on Sage the result is consistent with parity, not an advantage; on MSFragger there
is a statistically supported deficit.** speXtract also emits ~1.32x more spectra, so per-spectrum
efficiency still favours diaTracer. The MSFragger gap survives perfect masses, so it is
search/detection-side, not calibration.

The 2026-09-01 calibration fix is worth +6-11% closed-search peptides on Sage. It is an
identification-*yield* effect, not better spectra (emission moved -0.2%): mass error is a feature of
Sage's discriminant. Since diaTracer's spectra always carried vendor-calibrated masses, every earlier
comparison was biased against the open path -- **this is the removal of a self-inflicted handicap,
not a lead.**

Determinism: the spectrum data is **byte-identical at any thread count and any loader batch size**
(verified 2026-09-02 on three independent pairs: threads 8 vs 100 twice, loader batch 64 vs 256;
`bench/semantic_digest.py` hashes `<spectrumList>`..`</spectrumList>`, excluding the wall-clock
stamp, the recorded parameters and the trailing byte-offset index, none of which can match across
invocations -- the last of these had produced two false "differs" verdicts before it was excluded).
Last-ulp *code* changes still cascade to ~2% in peptide counts, so compare builds by the accepted
peptide SET and the ppm median, not by raw counts.

Runtime (S30, 33,553 frames, 100 threads on a 128-core node): **15:21 wall, 106 GB peak RSS**
(2026-09-02; was 33:05 on 09-01 -- the serial floor was the MS1 path, now parallel). The loader is
4% of the run; the window loop is 83%. Reading from `.mzpeak` instead of `.d` is supported
(build-optional, mzPeak C++ library) but slower (17:04); the archive's two-point TOF transform costs
12% of identifications, so the loader recovers the exact TDF calibration from the embedded
`vendor/analysis.tdf.gz` (or a `SPEXTRACT_MZPEAK_TDF=` sidecar) by default and fails closed without
it (-1% vs `.d` then). `.d` remains the primary input.

## The main open defect

**Charge annotation.** Now **74.6%** with the current defaults (was 47.8%), against diaTracer's
**82.6%**. The catastrophic `4->2` confusion is gone. But **always answering z=2 would score
69.6%** — so charge inference beats a constant by 5.0 points. It has stopped failing
catastrophically rather than started working, and it remains the largest headroom in the tool.

An MS1 funnel attempting to localise *where* precursors are lost was **retracted the same day it
was produced** — see [docs/ms1-funnel.md](docs/ms1-funnel.md). A decoy floor added afterwards
showed that a precursor which does not exist still matched an MS1 trace 91.9% of the time, so the
assay measured trace density rather than correctness. **"97.8% detection ceiling" and "26.5% lost
in inference" are withdrawn.** A tolerance sweep is running to find a usable operating point.

The charge-agreement number does not depend on that assay and stands.

This matters disproportionately for the intended use: dM = (z'-z)(m/z - 1.00728), so a z4->z2
error at m/z 600 fabricates a -1198 Da phantom modification. A closed search hides this because
the engine enumerates charge; an open search does not.

**Run-to-run reproducibility is 0.17%** (4 runs of an identical effective configuration:
8,411 / 8,408 / 8,406 / 8,397). Differences below ~0.2% are noise; the +46% delta is far above it.

See [docs/](docs/) for the measurements, including levers that were **falsified** — every
redundancy-reducing knob loses peptides at peptide-level FDR. One falsification has been
**withdrawn**: ion mobility was retired against the wrong null (`max p_z` = 69.6% instead of
`sum p_z^2` = 55.8%), so its true margin is **+19.2 points, not +5.4**. See
[docs/charge-inference.md](docs/charge-inference.md).

## Layout

```
src/        the tool
scripts/    truth-set, funnel, FDR-recount and charge analyses
docs/       benchmark results and architecture reviews
```

## License

BSD-3-Clause. Derived from OpenMS (BSD-3-Clause) — see [NOTICE](NOTICE).

## Charge inference: the two defaults are coupled, not independent

Measured against a DIA-NN S23 reference (`charge agreement` = our charge vs truth on matched
spectra; always answering z=2 would score **69.6%**):

| arm | charge agreement | `4->2` errors |
|---|---|---|
| ms1split + ambiguity_margin | **41.7%** | 34,554 |
| ms1split alone | 45.8% | 19,995 |
| baseline (`envelope`) | 49.7% | 10,199 |
| `count` | 71.8% | -- |
| **`ms1split` + `count`** (default) | **74.6%** | -- |

**MS1 splitting must not ship without `count`** — an *empirical* coupling, not an architectural
one. The two touch separate code paths (`trace:ms1_split_valleys` in `detectTraces_`,
`charge:scoring` in `inferPrecursors_`); nothing in the code enforces the pairing, so the
combination is a benchmark finding that a future edit could silently break. On its own MS1
splitting drops charge agreement below baseline and
more than triples the `4->2` confusion, which fabricates a ~-1198 Da phantom modification at
m/z 600 -- invisible to closed search (the engine enumerates charge) and fatal to open search.
Shipping `trace:ms1_split_valleys` without `charge:scoring count` would have been actively
harmful for this tool's actual purpose.

### `charge:ambiguity_margin` -- falsified, four tests

| margin | peptide_q | vs `split_count` 8,411 |
|---|---|---|
| 0.5 | 8,408 | -0.04% |
| 1.0 | 8,406 | -0.06% |
| 2.0 | 8,397 | -0.2% |

2.0 is the first value that can genuinely fire against an integer partner count (it admits any
hypothesis within 2 partners of the best) and it still changes nothing. Hedging charge does not
help; deciding it well does. Left at 0.
