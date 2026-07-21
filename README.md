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

| | ours | diaTracer | ratio |
|---|---|---|---|
| S08, baseline | 6,133 | 11,218 | 54.7% |
| S23, baseline | 5,131 | 9,038 | 56.8% |
| S23, MS2 valley splitting | 5,813 | 9,038 | 64.3% |
| S23, **MS1+MS2 valley splitting** | **7,949** | 9,038 | **88.0%** |
| S30, best config | 7,430 | *no reference* | — |

**MS1+MS2 valley splitting is confirmed on S23 only.** Confirmation on S08 and S30 is in
progress; this project has produced three wrong conclusions from cross-sample comparison, so
a single-sample result is not treated as established.

There is **no diaTracer run for S30**, so the S30 column has no ratio. An earlier version of
this table reported "S08, best config 7,430 -> 66.2%", which was wrong twice over: 7,430 is an
**S30** result, and it was being divided by the **S08** diaTracer reference.

Spectrum quality, from a model-free DIA-NN-anchored assay (decoy-controlled, equal depth,
independent of whether anything identifies the spectrum):

- **2.3x** more intensity on the correct precursor's fragments than diaTracer (5.79% vs 2.52% net)
- **30% less** co-isolation contamination (+7.50% vs +10.70% net)

## The main open defect

**Charge annotation.** Agreement with a DIA-NN reference is **47.8%** against diaTracer's
**82.6%**, dominant confusion `4->2` (15,734 cases on S08).

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
