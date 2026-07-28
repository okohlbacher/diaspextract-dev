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

## Measurement methodology (2026-07-28) — variance model + estimator fix

* **BOTH engines are DETERMINISTIC: run-to-run sigma = 0.** Re-searching one mzML (S30 corr_power=2)
  3x: Sage 10,802/10,802/10,802 AND MSFragger 11,560/11,560/11,560. So ALL benchmark peptide counts
  are EXACT; n=1 is justified for both. CONSEQUENCE: the MSFragger k-curve non-monotonicity
  (11,402/11,560/11,482/11,751 across k=1..4) is NOT run-to-run noise -- it is a REAL (non-smooth)
  response to the different inputs (codex called this in review; now measured). The earlier "MSFragger
  is a noisy guardrail" framing was WRONG on the noise: MSFragger numbers are exact, just non-monotonic
  in k (its optimum k differs from Sage's). The ONLY stochastic uncertainty in the whole benchmark is
  the entrapment FDR estimate (small n), which the bootstrap CI below now quantifies.
* **Entrapment estimator was wrong TWO ways (fixed in `bench/entrapment.py`, codex #12):**
  (1) it counted peptides SHARED between human and Arabidopsis as entrapment -> inflated the fraction
  ~2.5x (S30 base entrap 222 -> correctly 86 foreign-ONLY). (2) it used the PROTEIN ratio (0.800); the
  correct PEPTIDE-hypothesis ratio (in-silico tryptic, Sage rules) is 0.6805, correction 1/r = 1.469.
* **Corrected absolute FDR at nominal 1% peptide_q is ~1.0-1.45%, NOT the ~2.3% previously reported** --
  the tool is WELL-CALIBRATED. With 95% bootstrap CIs (n_entrap ~ 60-90 -> noisy):
  S30 base 1.34% [1.06-1.65] / corr2 1.20% [0.95-1.46]; S08 base 1.01% / corr2 1.08%; S23 base 1.45%
  [1.15-1.77] / corr2 1.18% [0.91-1.47]. **The arm FDR CIs OVERLAP** -> the earlier "FDR improved
  2.33->2.13%" was an estimator+noise artifact. Correct statement: **corr_power adds +9-10% target
  peptides at an entrapment FDR statistically INDISTINGUISHABLE from base** (more peptides, same FDR).
* **Consequence for future levers:** the +1-3% regime (im_weight increments, cap sweeps, rescoring
  features) needs this CI machinery + MSFragger replicate sigma to be falsifiable; do not decide small
  levers on point estimates.

## Decision rule

* **Progress** = peptides ≥ 10,072 and PSMs/peptide not worse.
* **Regression** = peptides fall ≥ 1%.
* **Noise floor** = 0.06% same-node (from four runs of an effectively identical config:
  8,411 / 8,408 / 8,406 on one node). Differences below ~0.2% mean nothing.
* **Screen on Sage** (4.2× faster, signs reproduce); confirm winners on MSFragger before any
  default change. Sage is unreliable on effect SIZE — measured compression up to 3× on one arm.

## Confirmed WINS post-freeze (gate baseline: Sage 9,989 / MSFragger 11,033 / entrap 9,304 @ 2.33%)

* **`assembly:corr_power` (Q2) + `im_weight_sigma` STACK — WIN on BOTH engines, entrapment-confirmed (2026-07-27).**
  Emitted fragment intensity *= co-elution^k. corr_power is EMIT-ONLY (excluded from the 500-cap key),
  so the corr_power arms preserve peak MEMBERSHIP (identical 924,255 spectra + same peak m/z set; pure
  intensity re-ranking). im_weight IS in the cap key, so with 73% of spectra at the 500-cap the STACK
  also REORDERS which fragments survive (its intended interferent-removal channel) -- same spectrum +
  peak COUNT, but not the same membership. So the stack's +310 over corr_power=2 has TWO channels
  (intensity reweight + cap membership), not one [kimi 2026-07-27]. diaTracer on S30: Sage 11,517,
  MSFragger 13,932. MSFragger here is a NOISY guardrail (no replicate variance measured; screen on
  Sage+entrapment). The 2.33->2.13% entrap frac is WITHIN Poisson noise (n~85 entrapment) -- a guardrail
  (it passed: extra targets are not disproportionately entrapment), NOT an FDR win.
  | arm | Sage | MSFragger | entrap target @ actual-FDR |
  |---|---|---|---|
  | base (gate) | 9,989 | 11,033 | 9,304 @ 2.33% |
  | corr_power=1 | 10,622 | 11,402 | 9,894 @ 2.18% |
  | corr_power=2 | 10,802 | 11,560 | 10,235 @ 2.21% |
  | corr_power=3 | 10,901 | 11,482 | 10,288 @ 2.16% |
  | corr_power=4 | 10,875 | 11,751 | 10,262 @ 2.15% |
  | **corr_power=2 + im_weight 0.005** | **11,112 (96.5% of dt)** | **11,813 (84.8% of dt)** | **10,574 @ 2.13%** |
  corr_power alone PEAKS at k≈3 on Sage; the im_weight STACK is best on EVERY metric incl. the LOWEST
  entrap FDR (2.13%) -- the two are COMPLEMENTARY purity axes (RT co-elution vs IM), they ADD not erase.
  Sage 86.7% -> 96.5% of diaTracer; MSFragger 79.2% -> 84.8%. Mechanism: a true fragment co-elutes with
  its precursor by construction (high c), so c^k down-weights mediocre-c INTERFERENTS. This OVERTURNED a
  UNANIMOUS 3-CLI review that predicted -2..-5% MSFragger (premise "faint precursor -> low-c fragment"
  was wrong). MSFragger is NOISY here (non-monotonic) -- screen on Sage+entrapment.

  **GENERALISATION TEST PASSED for corr_power (frozen k=2/sigma=0.005 on untouched S08, S23; 2026-07-27):**
  Sage nominal 1%: S08 base 8,822 -> k2 9,735 (+10.4%) -> stack 10,428; S23 base 8,311 -> k2 9,032 (+8.7%)
  -> stack 9,159. So **corr_power=2 robustly generalises: +8-10% over base on ALL THREE files, both
  engines (MSFragger S08 +5.6%, S23 +7.6%), at nominal 1% AND <=2% empirical FDR.** The im_weight STACK
  increment is FILE-VARIABLE (+310 S30, +693 S08, +127 S23 over k2; flat on MSFragger) -- a Sage-leaning
  bonus, NOT a robust default increment (S23 +127 < the pre-registered +200 threshold). The <=1% empirical
  FDR numbers are erratic (k2 dips on S08, stack dips on S23) = estimator noise at ~50 entrapment n (the
  <=2% and nominal metrics are clean). **DECISION (pending 3-CLI review of the result): ship corr_power=2
  as the new default; im_weight_sigma=0.005 as a documented optional stack. Caveat: S08/S23 are the same
  study series as S30, so this de-risks the S30 family, not diaPASEF broadly -- a different-cohort file is
  the stronger (unavailable-today) test.**

## What is already falsified on this file or S23

Do not re-propose without new evidence: `competitive`, rank-pruning (`rp_max` 2/4/8),
`assembly:apportion`, `trace:frame_aggregation_n` (3, 5), `charge:ambiguity_margin` (0.5/1.0/2.0
— and it was *unreachable* in count mode, so it is untested rather than falsified),
`consolidate:delta_rt` (0.7 → −12.7%, 3.0 → −24.0%), **`merge:rt_window` 1.4 → −4.4%**,
mass recalibration, a monotonic ion-mobility charge prior, AlphaDIA-style log-sum co-elution
scoring (three implementations), **`gate:variance_support` (Q1, union-support Pearson — 2026-07-27:
DROP on unanimous 3-CLI analysis; it measures support co-LOCALISATION not co-elution SHAPE and reads
faint fragments' censored shoulders as anti-correlation, e.g. precursor-8/frag-5/overlap-3 scores
G-Pearson +0.47 but union −0.50. G-Pearson already ≈ robust cosine, so [B0] was cosmetic).**

## Spectrum COLLAPSE (same precursor across cycles) — FALSIFIED for quality (2026-07-28)
Tested on the OPEN-search entrapment results (simulation on existing PSMs, no re-search): group rank-1
PSMs by precursor coordinate ACROSS RT (charge + expmass 10 ppm + IM 0.01, single-link chained over a
10 s RT gap), keep one (or top-N) per group, RECOMPUTE the corrected entrapment FDR from scores.

| rule | spx kept | reduction | targets @1% FDR | dt targets |
|---|---|---|---|---|
| full            | 558,255 | 1.00x | **8,273** | 9,743 |
| apex (ID-agnostic) | 86,842 | 6.43x | 3,342 (-60%) | 4,491 (-54%) |
| best (ORACLE)   | 86,842 | 6.43x | 4,390 (-47%) | 5,089 |
| top3 / top5 / top10 (collapse + chimeric report_psms) | 132k/155k/190k | 4.2x/3.6x/2.9x | 5,448/5,767/6,603 | 6,068/6,672/7,422 |

**The multiple-testing-burden hypothesis is REFUTED.** Every arm's FDR CI sits at ~0.6-1.3%: collapse
removes true AND entrapment PSMs PROPORTIONALLY, so the FDR does not improve -- peptides are simply
lost. Emitting fewer spectra does NOT buy open-search sensitivity.
**It is INTRINSIC, not a speXtract defect:** diaTracer collapses the same way (-24% at top10, -54% at
apex) and BOTH tools reduce to the SAME ~87k precursor features (spx 86,842 / dt 87,112) -- speXtract
just emits 1.33x more spectra per feature (6.43 vs 4.84). The across-cycle multiplicity is INDEPENDENT
EVIDENCE (each cycle = a different noise realisation + co-isolation mixture, another shot at a different
co-eluting peptide), not redundancy. Consistent with the long-standing "across-cycle spread 2.66 is
CORRECT (MS1 FWHM = 2.61 cycles)" finding.
**Residual option, untested:** TRUE merging (union of peaks -> better S/N) could in principle ADD IDs
rather than select among existing ones; this simulation only bounds the SELECT-among-existing case. But
it must beat a -20%..-60% deficit and it blends interferents across RT, so it is not promising.
**Practical use:** collapse is a SPEED/recall knob, not a quality lever -- top10 gives 2.94x fewer
spectra (much cheaper search) for -20% peptides, if total pipeline time ever matters more than recall.

## Monoisotope -1.003 Da open-search artefact: STOPPING guard FALSIFIED, scoring fix under test (2026-07-28)
The open-search re-baseline found our largest delta-mass artefact is a **-1.003 Da population** (top bin
7,616 PSMs; 8.20% isotope-shifted vs diaTracer 3.46%): the `charge:scoring=count` walk defines the
monoisotope as the FURTHEST-LEFT peak it can reach, and `findPartner` matches m/z + RT + IM but **never
intensity**, so it latches onto noise or a co-eluting species one isotope below the true mono. Closed
search HIDES this (Sage enumerates `isotope_errors [-1,2]` and corrects it for free); open/blind search
turns it into a phantom -1 Da modification.

**Attempt 1 — `charge:mono_averagine_guard` (a STOPPING rule): FALSIFIED.** Require the leftward
candidate to reach the averagine minimum 1/lambda times the previous peak. At slack 0.5 on S30:
| metric | control | guard 0.5 |
|---|---|---|
| -1 Da bin | 7,616 | **2,734 (-64%, the target WORKED)** |
| +1 Da bin | 4,697 | **23,994 (+411%)** |
| total isotope-shift | 8.20% | **16.43% (WORSE)** |
| open targets @ FDR | 8,887 @1.29% | 8,939 @1.28% (flat, CIs overlap) |
| closed Sage | 10,802 | 11,697 (+8.3%) |
| emission | 924,255 | 1,005,353 (+8.8%) |
**A stopping rule can only trade over-reach for under-reach**, and worse: a walk that halts early leaves
the M+1 peak unconsumed by `used[]`, so it later seeds its OWN precursor one isotope too heavy -- that is
BOTH the +1 explosion and the +8.8% emission (one cause, two symptoms). Open search did not improve.
NOTE the closed-search 11,697 (> diaTracer 11,517) is NOT a quality win to bank: peptides/1k spectra is
11.7 -> 11.6, i.e. the gain tracks the extra emission -- exactly the over-emission-rewards-closed-search
corruption the reviewers warned about. Do not ship the guard for it.

**Attempt 2 — `charge:mono_averagine_select` (a SCORING decision): under test.** Walk the full run, then
choose WHICH peak is the mono by averagine cosine of the envelope starting there. Corrects BOTH
directions, and every found peak is still consumed, so de-isotoping and emission stay unchanged (only the
reported precursor mass moves) -- which also removes the emission confound from the experiment.
