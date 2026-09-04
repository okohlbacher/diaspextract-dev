# SpeXtract

Extraction of pseudo-DDA ("pseudo-MS/MS") spectra from Bruker timsTOF **diaPASEF** data.

An open, BSD-3, standalone alternative to the closed-source [diaTracer](https://github.com/Nesvilab/diaTracer).
The goal is **blind / open search** — finding variants and unexpected modifications that a
library-based DIA tool cannot report, because its search space is enumerated before the search
begins.

SpeXtract is a standalone application. **OpenMS is a prerequisite, not a host** — the tool links
against an OpenMS installation but lives outside the OpenMS source tree.

## Build

Needs OpenMS with `WITH_OPENTIMS` (to read Bruker `.d`). **Apply this repo's OpenMS patches first:**

```bash
scripts/apply_openms_patches.sh /path/to/OpenMS      # installs src/TdfMzCalibration.h + patches
# then rebuild the OpenMS spextract target
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
script), then configure SpeXtract with `-DMZPEAK_ROOT=<checkout>`. Inside an OpenMS source tree use
`patches/openms-topp-mzpeak-cmake.py` instead. ims-compact archives store raw TOF behind a two-point
transform; the loader recovers the exact TDF calibration from the embedded `vendor/analysis.tdf.gz` (or
`SPEXTRACT_MZPEAK_TDF=<analysis.tdf.gz>` for `--no-vendor` archives) and refuses to run without it unless
`SPEXTRACT_MZPEAK_EXACT=0`.

## Run

```bash
build/spextract -in sample.d -out pseudo.mzML -threads 64
```

Recommended: preload tcmalloc. It is worth more than the structural memory work in this
repository (measured: -18.4% peak RSS combined, of which compaction alone is -6.1%).

## Where it stands

Measured on three diaPASEF acquisitions (one cohort, one instrument), both engines, identical search
settings for both tools. Current arm: apex m/z estimator + `charge:min_charge` 2 (2026-09-03).
Full matrix: `docs/BENCHMARK-MATRIX-2026-09-01.md`; decisions: `docs/S30-BASELINE.md`.

| | S30 | S08 | S23 | vs diaTracer |
|---|---|---|---|---|
| **Sage** peptides @1% FDR | **12,642** | **11,084** | **10,294** | 109.8 / 108.2 / 115.0% |
| Sage, before the charge gate (2026-09-02) | 12,537 | 10,789 | 10,156 | 108.9 / 105.3 / 113.5% |
| **MSFragger** peptidoforms @1% | **12,073** | **12,061** | **9,822** | 86.7 / 88.3 / 92.6% |
| MSFragger, before the charge gate | 11,927 | 11,444 | 9,738 | 85.6 / 83.7 / 91.8% |
| diaTracer reference (Sage / MSFragger) | 11,517 / 13,932 | 10,242 / 13,666 | 8,948 / 10,606 | -- |
| entrapment FDR at nominal 1% | 1.38% [1.15-1.64] | 0.99% [0.77-1.23] | 1.28% [1.01-1.54] | diaTracer 1.24 / 1.22% on S08/S23 |
| precursor mass error, paired vs diaTracer on shared peptides | +0.78 ppm | +1.47 | +1.17 | fragment: -2.4 / -2.0 / -2.1 (diaTracer-side reporting) |
| pseudo-spectra emitted | 0.66 M | 0.86 M | 0.59 M | **0.94 / 0.99 / 0.82x diaTracer** |
| wall time, 128-core node (S30) | 12:49 | -- | -- | -- |

Read honestly: **on Sage the result is above parity on all three files; on MSFragger the deficit
stands (7-13%) and is statistically supported.** The emission excess is gone -- since 2026-09-03 we
emit FEWER spectra than diaTracer on all three files, so per-spectrum efficiency no longer favours
diaTracer and the MSFragger gap cannot be attributed to over-emission. It also survives perfect
masses, so it is search/detection-side, not calibration.

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
This byte-identity holds for a FIXED binary across thread counts and batch sizes. It does not
survive a code change: a last-ulp difference in one arithmetic path cascades to ~2% in peptide
counts, so compare two BUILDS by the accepted peptide SET and the ppm median, never by raw counts.
The two statements are about different things and both have been measured.

Runtime (S30, 33,553 frames, 100 threads on a 128-core node): **7:17 wall, ~164 GB peak RSS**
with the current defaults (2026-09-03 evening; peptide set identical to the 12:49 build). The
scoring gate had been striding 96-byte records to read one field; it now reads a parallel array.
It was 12:49 that morning after `charge:min_charge` removed ~30% of the emission, 15:21 before
that, and 33:05 on 09-01 before the MS1 path was parallelised. Mass-trace detection runs on the
instrument's own integer axes by default (`trace:detector=integer`), which is faster and uses ~40%
less memory than the OpenMS detector (86 vs 150 GB on S30, 126 vs 222 GB on S08). The two are
different algorithms and agree on only ~85% of the union of identified peptides; which one identifies
more flips with the search engine and with the file (Sage -1.3% on S30, +0.2% on S08; MSFragger
+2.1% on S30, -3.5% on S08), so the memory is the reason for the default, not a peptide gain. Use
`-trace:detector openms` for the other one. Without the vendor flight-time calibration the tool falls
back to the OpenMS detector and records which one ran in the output. The loader is
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
