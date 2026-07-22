# S30 is the decision file

**All progress/regression decisions are made on S30 alone.** Other samples are for confirmation
once something has already won here — cross-sample comparison has produced three wrong
conclusions in this project, and single-sample iteration removes that class of error entirely.

## Reference numbers (frozen 2026-07-22)

| measure | value | how |
|---|---|---|
| **peptides @ peptide_q ≤ 0.01** | **10,072** | `sage_deiso.json`, current defaults |
| peptides, common-FDR procedure | 9,977 | `joint_bench.py`, Sage |
| diaTracer, same procedure | 11,552 | ratio **86.4%** |
| MSFragger, same file | 10,470 | diaTracer 13,014, ratio 80.5% |
| PSMs/peptide | 8.98 | diaTracer 1.66 |
| within-cycle multiplicity | 2.85 | the defect |
| across-cycle spread | 2.66 | **correct** — MS1 FWHM is 2.61 cycles |
| MS1 FWHM | 3.61 s | flat with RT (1.04× across gradient) |

**Current defaults:** `trace:ms1_split_valleys 7.0`, `charge:scoring count`, plus
`ms2_chrom_peak_snr 1.0`, `ms2_noise_threshold_int 10`, `ms2_min_length_sec 0`,
`ms2_split_valleys 7.0`.

## Decision rule

* **Progress** = peptides ≥ 10,072 and PSMs/peptide not worse.
* **Regression** = peptides fall ≥ 1%.
* **Noise floor** = 0.06% same-node (from four runs of an effectively identical config:
  8,411 / 8,408 / 8,406 on one node). Differences below ~0.2% mean nothing.
* **Screen on Sage** (4.2× faster, signs reproduce); confirm winners on MSFragger before any
  default change. Sage is unreliable on effect SIZE — measured compression up to 3× on one arm.

## What is already falsified on this file or S23

Do not re-propose without new evidence: `competitive`, rank-pruning (`rp_max` 2/4/8),
`assembly:apportion`, `trace:frame_aggregation_n` (3, 5), `charge:ambiguity_margin` (0.5/1.0/2.0
— and it was *unreachable* in count mode, so it is untested rather than falsified),
`consolidate:delta_rt` (0.7 → −12.7%, 3.0 → −24.0%), **`merge:rt_window` 1.4 → −4.4%**,
mass recalibration, a monotonic ion-mobility charge prior, AlphaDIA-style log-sum co-elution
scoring (three implementations).
