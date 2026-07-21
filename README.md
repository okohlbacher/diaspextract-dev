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
| S08, best config | 7,430 | 11,218 | 66.2% |
| S23, baseline | 5,131 | 9,038 | 56.8% |
| S23, MS1+MS2 valley splitting | **7,917** | 9,038 | **87.6%** |

Spectrum quality, from a model-free DIA-NN-anchored assay (decoy-controlled, equal depth,
independent of whether anything identifies the spectrum):

- **2.3x** more intensity on the correct precursor's fragments than diaTracer (5.79% vs 2.52% net)
- **30% less** co-isolation contamination (+7.50% vs +10.70% net)

## The main open defect

An MS1 funnel against 43,499 DIA-NN precursors localises where precursors are lost:

| stage | share |
|---|---|
| no MS1 trace at all | **2.2%** |
| trace, but no hypothesis | 10.5% |
| hypothesis, **wrong charge** | **15.9%** |
| correct hypothesis | 71.3% |

**Detection is not the bottleneck** — the MS1 ceiling is 97.8%. 26.5% is destroyed in isotope and
charge inference, corroborated by 47.8% charge agreement against diaTracer's 82.6%.

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
