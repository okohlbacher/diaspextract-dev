# speXtract

Extraction of pseudo-DDA ("pseudo-MS/MS") spectra from Bruker timsTOF **diaPASEF** data.

An open, BSD-3, standalone alternative to the closed-source [diaTracer](https://github.com/Nesvilab/diaTracer).
The goal is **blind / open search** — finding variants and unexpected modifications that a
library-based DIA tool cannot report, because its search space is enumerated before the search
begins.

speXtract is a standalone application. **OpenMS is a prerequisite, not a host** — the tool links
against an OpenMS installation but lives outside the OpenMS source tree.

## Build

```bash
cmake -B build -DOpenMS_DIR=/path/to/OpenMS/build
cmake --build build -j
```

Requires OpenMS built with `WITH_OPENTIMS` for Bruker `.d` input.

## Run

```bash
build/DIAPseudoSpectra -in sample.d -out pseudo.mzML -threads 64
```

Recommended: preload tcmalloc. It is worth more than the structural memory work in this
repository (measured: -18.4% peak RSS combined, of which compaction alone is -6.1%).

## Where it stands

Measured against diaTracer on the same samples, and against a DIA-NN reference annotation used
as a truth set. **All peptide counts are at `peptide_q <= 0.01`** — spectrum-level FDR overstates
our counts by 14-16% versus diaTracer's 5-7%, because we emit more spectra per peptide and each
gets more chances at a per-spectrum threshold.

All three samples now run **matched baselines** — identical config, one node, one binary, both
arms in a single invocation — because the first attempt compared each sample against whatever
baseline it happened to have (MS2-split, plain, and a tuned ±25 ppm config), which produced a
spurious "+4.1%, does not generalise" for S30.

| sample | matched base | **with defaults** | delta | diaTracer | ratio |
|---|---|---|---|---|---|
| S23 | 5,817 | **8,411** | **+44.6%** | 9,038 | **93.1%** |
| S08 | 6,114 | **8,996** | **+47.1%** | 11,218 | **80.2%** |
| S30 | 6,866 | **10,072** | **+46.7%** | *no reference* | — |

**+44.6% / +47.1% / +46.7%** — consistent within 2.5 points across three samples. There is no
diaTracer run for S30, so that row has no ratio. An earlier version of this table reported
"S08, best config 7,430 → 66.2%", which was wrong twice over: 7,430 is an **S30** result, and it
was divided by the **S08** diaTracer reference.

The two defaults responsible are `trace:ms1_split_valleys 7.0` and `charge:scoring count`. They
are **coupled** — see below — and cost ~1.7x wall time and ~25% peak RAM.

Spectrum quality, from a model-free DIA-NN-anchored assay (decoy-controlled, equal depth,
independent of whether anything identifies the spectrum):

- **2.3x** more intensity on the correct precursor's fragments than diaTracer (5.79% vs 2.52% net)
- **30% less** co-isolation contamination (+7.50% vs +10.70% net)

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

See [docs/](docs/) for the measurements, including levers that were **falsified** — ion mobility
cannot predict charge, and every redundancy-reducing knob loses peptides at peptide-level FDR.

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

**MS1 splitting REQUIRES `count`.** On its own it drops charge agreement below baseline and
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
