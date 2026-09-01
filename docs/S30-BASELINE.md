# S30 is the decision file

**All progress/regression decisions are made on S30 alone.** Other samples are for confirmation
once something has already won here — cross-sample comparison has produced three wrong
conclusions in this project, and single-sample iteration removes that class of error entirely.

## Reference numbers (frozen 2026-07-22)

| measure | value | how |
|---|---|---|
| **peptides @ peptide_q ≤ 0.01** | **10,072** | `sage_deiso.json`, current defaults |
| peptides, common-FDR procedure | 9,977 | DEPRECATED 2026-09-01 (procedure's primary outputs no longer exist) |
| diaTracer, same procedure | 11,552 | DEPRECATED (doc-only; canonical ref = 11,517) — legacy ratio 86.4% not citable |
| MSFragger, same file | 10,470 | DEPRECATED (diaTracer 13,014 doc-only; canonical = 13,932 form-level / 12,752 seq-level) |
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

* **Progress** = Sage peptides ≥ 10,802 (standard bench config = tool defaults + `-assembly:require_isotope_support`; re-based 2026-09-01, was 10,072 pre-gate/pre-corr_power) and PSMs/peptide not worse (guardrail retained).
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

### Attempt 2 result + the finding that STOPS this line of work (2026-07-29)
`charge:mono_averagine_select` raw cosine repeated the envelope scorer's documented short-vector trap
(`len` shrinks as the candidate mono moves right -> short vectors score high -> too-HEAVY mono). Adding
the same evidence weight the envelope scorer uses, (len-1)/3 capped at 1, largely fixed that:
| metric | control | guard 0.5 | msel raw | **msel + evidence weight** |
|---|---|---|---|---|
| emission | 924,255 | 1,005,353 | 924,716 | **924,552** |
| -1 bin | 7,616 | 2,734 | 2,314 | **4,015 (-47%)** |
| +1 bin | 4,697 | 23,994 | 21,591 | **12,188** |
| unmod | 31.2% | 24.3% | 26.4% | **32.0% (best)** |
| isotope-shift | **8.20%** | 16.43% | 15.24% | **9.48%** |
| open targets @FDR | 8,887 @1.29% | 8,939 @1.28% | 8,916 @1.33% | 8,932 @1.33% |
| closed Sage | 10,802 | 11,697 | 11,458 | 11,279 |
Pre-registered criterion was total isotope-shift BELOW 8.20% with both +-1 bins down: **NOT MET (9.48%)**.
Stopped rather than running a 4th variant. Both flags stay default-OFF, documented, for reproducibility.

**THE FINDING THAT MATTERS — the -1 artefact is NOT the open-search recall lever (my hypothesis was WRONG).**
Open-search targets are FLAT across all four arms (8,887 / 8,939 / 8,916 / 8,932; every CI overlaps)
even though the -1 population was cut 47-70%. Reason, obvious in hindsight: **a -1-shifted precursor is
still IDENTIFIED** -- it appears in the delta-mass histogram AS an identified PSM at -1.003 Da. Open
search does not lose the peptide, it mislabels it with a phantom modification. So the monoisotope
artefact is a **PTM-INTERPRETATION problem (real, and it matters for blind-PTM correctness, our actual
differentiator), NOT a recall problem.** It cannot explain the 8,887 vs 9,989 open-search gap; do not
spend more effort here expecting recall. The open-search recall gap needs a different explanation --
candidates not yet tested: our 924k vs diaTracer's 700k emission competing in the huge open search
space, fragment quality on the faint tail, or precursor mass ACCURACY (ppm) rather than isotope offset.

## STEP 01 (2026-09-01): the metric re-denominated + denominators reconciled

### A. Delta-mass-BIN-level open-search scoring (bench/open_ptm_score.py v2, corrected estimator)
Unit = (peptide, delta-bin); classes scored separately: unmod (|d|<=8 mDa), nearzero (8-900 mDa =
mass-error tail, NOT a mod), artifact (iso lattice +-k*1.00335, k=1..9), known (curated Unimod list),
other (off-lattice, per-BIN FDR walks for top bins -- pooled class FDR let junk bins ride; the spx
-485..-499 Da window-edge wall at ~36% raw entrap collapses to ~30-80 @1% under per-bin walks).
| class @1% corrected FDR | speXtract | diaTracer | ratio |
|---|---|---|---|
| unmodified | 4,885 | 7,015 | 70% |
| known-PTM (the raison-d'etre number) | 2,692 | 3,092 | **87%** |
| isotope-artifact (k<=9) | 4,073 | 3,611 | 1.13x (v1's "2.4x artifact" was a k<=3-grid artifact of its own: dt's big envelope ladder is ON-lattice at k>=4; ours skews to iso-1) |
| **nearzero mass-error (8-900 mDa)** | **7,099** | **2,814** | **2.5x -- NEW finding** |
| other (off-lattice) | 44,143 | 78,244 | 56% (interpret with care: correlated bins; contains e.g. -0.984 amidation-type masses off the iso lattice) |
**Findings:** (1) In the honest currency diaTracer leads every legitimate class; the old
"89% targets@FDR" UNDERSTATED the unmod gap (70%) and roughly matched known-PTM (87%).
(2) NEW: spx's near-zero mass-error tail is 2.5x dt's, and spx unmod+nearzero = 11,984 vs dt 9,829 --
much of our "missing unmodified" population is IDENTIFIED but MASS-DEGRADED (precursor 8-900 mDa off),
i.e. an interpretation-quality defect (like the -1 Da class), pointing at PRECURSOR MASS ACCURACY.
NOTE: "mass recalibration" sits in the falsified list, but it was falsified ON THE CORRUPT CLOSED
METRIC -- exactly the class of falsification the 2026-09-01 review said may need re-audit. Flagged for
re-evaluation in THIS currency; not re-litigated yet. (3) The phantom-mod gap (artifact class) is
+13%, not 2.4x -- the earlier headline overstated it by using a too-short isotope grid.

### B. Denominators reconciled (the "no ratio is citable" blocker)
- **CANONICAL diaTracer references from 2026-09-01 on: Sage 11,517** (dt_s30/results.sage.tsv,
  nominal peptide_q<=0.01 -- re-verified today; TSV archived to ceph) and **MSFragger 13,932**
  (msf_dt/fixed.tsv via score_msf_td target-decoy; archived).
- **11,552 / 13,014 are DEPRECATED**: products of the 2026-07-22 joint common-FDR procedure whose
  primary outputs (joint_results.json et al.) exist in NO file on the cluster -- doc-only numbers.
  Not to be used in ratios. The frozen table's 86.4%/80.5% ratios are legacy.
- **Decision-rule re-base:** the frozen threshold 10,072 predates the isotope-support gate AND
  corr_power (superseded twice). New reference for progress/regression: **Sage 10,802** = current
  tool defaults (corr_power=2) + the standard bench config (which passes -assembly:require_isotope_support
  explicitly; that flag remains OFF in the tool). Noise floor and +-1% rules unchanged.

### STEP 01 CLOSURE (v3 scorer, post kimi+codex review, 2026-09-01) — SUPERSEDES the v2 table above
The v2 class table is NOT citable (review: Da-constant tolerance made every ratio a mass-accuracy
measurement biased against spx; per-bin @1% on zero-entrapment slivers vacuous; ontology gaps).
v3 (bench/open_ptm_score.py @ e9f5b64b): nearest-candidate assignment over {0, iso-lattice k<=15,
28 KNOWN masses}, ppm-scaled tol max(8 mDa, 12 ppm), conservative (e+1)/r tie-grouped walks with
bootstrap CIs, min-evidence rule (per-name @1% only when accepted e>=10), provenance headers.

**Citable v3 table (S30 open search, @1% corrected class-FDR, CIs in ptm_score_v3.out):**
| class | spx | dt | reading |
|---|---|---|---|
| unmod | 6,907 | 7,890 | 87.5% at hypothesis level; PEPTIDE level ~parity (96-106% by definition: accepted-union 7,744 vs 8,079; best-hypothesis 6,547 vs 6,164) |
| knownPTM | 4,878 | 4,651 | "105%" is CONTAMINATED: spx's top-3 knownPTM bins are all iso-AMBIGUOUS (Didehydro/Amidation/Deamid = 34% of spx knownPTM units vs dt 14%) = our lattice spill relabeled. Ambiguity-excluded units: spx ~78%. Honest: BROADLY COMPARABLE SCALE, per-mod 57-131% (Ox 93%, Acetyl 131%, Phospho 57%), NO single mod FDR-certifiable (all per-name e<10) |
| isotope lattice (k<=15) | 7,737 | 8,826 | dt carries MORE lattice hypotheses (its +k up-ladder); spx signature = iso-1 (1,790 @1%, e=11, certified). NEITHER tool is clean |
| nearzero (mass-error) | 5,415 | 1,432 | 3.8x — THE spx-specific defect, mechanism nailed (below) |
| other | 40,160 | 72,747 | DESCRIPTIVE ONLY: dominated in BOTH tools by off-lattice integer-Da bins (dt's ladder to +21); not PTM discovery |

**The nearzero mechanism is PROVEN (three independent legs, all on existing data):**
(1) 70.1% of spx nearzero peptides ARE dt's unmod peptides; (2) 89.4% same-scan concordance with our
OWN closed search (same scan -> same peptide; 0.7% different -> chimeric explanation dead);
(3) deltas 93.8% negative, median -16.2 mDa, slope -18.3 ppm vs calcmass (dt control ~symmetric).
=> speXtract's reported precursor masses carry a SYSTEMATIC ~-18 ppm CALIBRATION BIAS introduced by
our pipeline (same raw data as dt). Fixable (per-run linear recalibration of reported mono m/z);
distinct from the old falsified "mass recalibration" lever (different target, corrupt metric).
Scheduled as its own arm AFTER step 02 (both reviewers: do not confound the pre-registered arm).

**MSFragger denominator reconciled (codex #14):** 13,932/11,560 are PEPTIDOFORM-level (pair them);
sequence-level recount from archived TSVs: dt 12,752 vs spx 11,055 = 86.7%; legacy 13,014 was
sequence-level and is within 2% of 12,752 — unit mismatch closed, ratios now like-for-like.

**Step-01 bottom line:** the old "89% on open search" dissolves. At peptide level we are at ~parity
on unmodified; known-PTM scale is comparable (ambiguity-limited both ways); BOTH tools' open-search
delta dimension is dominated by non-PTM structure (lattice + integer-Da junk = 5-9x the legitimate
classes) — a tool-CLASS finding worth publishing; and speXtract's one distinctive open-search defect
is the -18 ppm mass bias (fixable), vs diaTracer's up-ladder envelope artifacts. Step 02 (emission
arm) runs AS REGISTERED with a nearzero-stratified secondary readout, scored under this v3 metric.

## THE -8 ppm MASS BIAS: mechanism found + fixed (2026-09-01, follows the step-01 nearzero finding)
**Every speXtract-reported m/z to date carries a systematic, m/z-dependent -5..-11 ppm error**
(median -8.3 ppm on identified precursors; dt control -1.1 ppm on the same raw data).
**Mechanism (proven by direct comparison against Bruker's timsdata library via ctypes):** the loader
(BrukerTimsFile -> opentims++) converts TOF->m/z with `OpenSourceTof2MzConverter (linear-in-sqrt)` --
a TWO-POINT chord fit to just (MzAcqRangeLower=100, MzAcqRangeUpper=1700, DigitizerNumSamples): error
~0 at the anchors, bowing to -10.8 ppm mid-range, frame-independent -- reproducing every observed
feature (flat in RT and mass-in-ppm; the "IM trend" is the m/z-dependence in disguise; temperature was
a red herring, dC2=0 and dT1 tiny). The loader's SDK branch (OPENMS_BRUKER_SDK_PATH) upgraded ONLY the
ion-mobility converter -- the m/z converter was never swapped (and the env var was never set anyway).
**Fix: patches/openms-brukertims-sdk-mz.patch** -- 3 lines: the SDK branch now also installs
`BrukerTof2MzConverterFactory` (vendor per-frame calibration via tims_index_to_mz). Requires
OPENMS_BRUKER_SDK_PATH pointing at a local Bruker timsdata .so (present on the cluster from fp-tools;
used locally, never redistributed; without it the tool falls back to the open model as before).
The open-model inaccuracy is itself reportable upstream (opentims; also explains why mzdata disabled
its own m/z model port).
**Why mzPeak was NOT the answer (user directive "pull latest mzPeak", researched 2026-09-01):** spec
is draft 0.9 / prototype v0.1.0 / breaking layout change 2026-07-14 / no releases; the current
TDF->mzpeak converter stores RAW TOF indices and its own m/z path uses the same two-point model
(mzdata implemented the true vendor model 0.66.3 but disabled it 0.66.5 as "not consistently better");
the OpenMS in-tree MzPeakFile is unmerged/dormant and keyed to a superseded spelling. mzPeak re-poses
the calibration problem; it does not solve it.
**Impact on prior results:** [CORRECTED by review: the original "closed counts unaffected" claim
here was falsified by sdkcal itself, +12.3% -- candidate-window inclusion was never the only channel];
step-01 v3 open-search numbers stand AS MEASURED but the nearzero class (5,415 vs 1,432) was this bug.
Decisive arm `sdkcal` running: vendor-calibrated re-extraction -> expect ppm median -> ~-1, nearzero
to collapse toward dt's level, and possibly small closed gains (tighter effective tolerance).

### sdkcal CONFIRMED (2026-09-01): vendor m/z calibration is the new benchmark configuration
| metric | pre-fix (corr2) | **sdkcal (corr2 + vendor m/z)** | diaTracer |
|---|---|---|---|
| ppm median (open IDs) | -8.29 [-12.5,-4.0] | **+1.74 [-2.4,+6.1]** | -1.10 [-3.8,+1.2] |
| closed Sage | 10,802 | **12,128 (+12.3%)** | 11,517 (scoped claim only -- see review verdict below) |
| closed Sage entrapment | 10,381 @1.20% | **11,435 @1.26% [1.00-1.51]** | -- (FDR unchanged -> gain is real) |
| closed MSFragger | 11,560 | 11,460 (-0.9%, FLAT) | 13,932 (82.3%) -> Sage-specific gain |
| emission | 924,255 | 922,132 (~unchanged) | 700,434 |
| open unmod @1% | 6,907 (87.5%) | **7,566 (95.9%)** | 7,890 |
| open nearzero @1% | 5,415 (3.8x dt) | **2,769 (1.9x)** | 1,432 |
| open knownPTM @1% | 4,878 | 6,058 (total; ambiguity-excluded units ~85% of dt) | 4,651 |
**Decision: OPENMS_BRUKER_SDK_PATH + patches/openms-brukertims-sdk-mz.patch = REQUIRED benchmark
config from now on; closed-Sage reference re-based 10,802 -> 12,128.** Caveats carried into review:
(1) the +12% is Sage-specific (MSFragger flat -- its gap is search/detection-side, consistent with
prior reviews); (2) EVERY pre-2026-09-01 number was measured at -8 ppm, INCLUDING the corr_power
validation and all falsifications -- corr_power=0 ablation under vendor-cal launched (sdkcal_cp0);
S08/S23 holdout re-validation owed; falsified-lever re-audit only where a lever plausibly interacted
with mass accuracy; (3) knownPTM ambiguous fraction unchanged (34.7% vs dt 14%) but the bins are now
physically separable at +-4 ppm -- the 1,610-unit Amidation bin (1.4% raw entrap) deserves real
chemical scrutiny rather than automatic dismissal as spill.

### Calibration-step adversarial review verdict (kimi + codex, 2026-09-01) — 12,128 is PROVISIONAL
Convergent verdict: the chord mechanism is the proven DOMINANT cause of the old raw-axis bias, but the
step over-claimed in four ways, now corrected:
1. **Attribution not isolated:** setting the env var flipped BOTH converters (m/z AND ion mobility) --
   the SDK IM swap engaged for the first time ever alongside the m/z patch. Part of the +12.3% could be
   IM-side; ALL prior IM-dependent results (incl. im_weight's validation) silently ran on the open IM
   model. IM-isolation arm required (m/z vendor + IM open).
2. **12,128 = provisional S30/vendor-SDK regression oracle, NOT a validated reference** until: cp0
   ablation (running), the IM-isolation arm, and S08/S23 re-validation under vendor-cal.
3. **"Leads diaTracer" is not citable.** Maximum defensible wording (codex): "On S30, using Sage and
   the vendor-SDK calibration configuration, speXtract yielded 5.3% more closed-search peptides; under
   MSFragger it yielded 17.7% fewer." Per-1k-spectra efficiency: spx 13.2 vs dt 16.4 (dt +25%) -- the
   emission column stays in any public row. MSFragger flatness is UNINFORMATIVE (its default
   calibrate_mass auto-corrects input bias), not evidence against the fix.
4. **Residual defect remains:** sdkcal centers +1.74 ppm vs dt -1.10 (2.8 ppm apart, quartiles
   symmetric -- earlier "right-skewed" claim wrong) and nearzero is halved, not closed (1.9x dt).
   Candidates: our centroiding/mono reporting point. Paired same-feature spx-vs-dt reported-m/z
   comparison is the discriminator. The -18 ppm (step-01 regression slope on the truncated nearzero
   subset) vs -8.3 ppm (median, all IDs) are different statistics of the same defect -- reconciled here.
Hardening obligations recorded: benchmark must FAIL CLOSED on a missing/wrong SDK path (silent
fallback = known-wrong masses); opentims' BrukerTof2MzConverter DISCARDS tims_index_to_mz's return
code (silent incomplete-buffer risk -- fix when the patch is vendored properly); SDK identity pinned
in evidence/SHA256SUMS (sha a9708613..., PRERELEASE TDF-SDK 2.21.0 -- Bruker notes a tims_index_to_mz
implementation change in this line); patch base = OpenMS 3.6.0-pre-exported-20260717 tarball; runtime
headlines must be RE-MEASURED under the SDK path before publication. Determinism check (threads-8 vs
threads-100 semantic/byte hash) running. Two-tier calibration product conflict stands: license-blocked
users (the stated market) get -8 ppm masses from the open fallback -- an open true-polynomial port or
loud two-tier disclosure is a v0.2.0 gate.

### cp0 ablation result (2026-09-01): corr_power SURVIVES the calibration fix — provisionality condition 1/3 cleared
corr_power=0 + vendor-cal = 11,017 vs corr_power=2 + vendor-cal = 12,128. The 2x2 (closed Sage):
old-cal cp0 9,989 / cp2 10,802 (+8.1%); vendor-cal cp0 11,017 / cp2 12,128 (+10.1%). The levers are
independent and additive (mild positive synergy); corr_power's +8-10% validation was NOT a
calibration artifact. Note the cp0 arm also ran vendor IM, so the m/z-vs-IM attribution of the
calibration gain itself still awaits the IM-isolation arm (condition 2/3); S08/S23 = condition 3/3.

### Table-model calibration: 3-FILE RESULT (open path, no vendor .so; 2026-09-01)
| file | old chord | **TDF-table model** | gain | vendor-SDK | ppm (table) |
|---|---|---|---|---|---|
| S30 | 10,802 | **11,976** | +10.9% | 12,128 | +1.49 [-2.4,+5.4] |
| S08 |  9,735 | **10,333** | +6.1%  | -- | +3.19 [-0.8,+7.1] |
| S23 |  9,032 | **9,891**  | +9.5%  | -- | +2.29 [-1.7,+6.3] |
**The calibration gain GENERALISES: +6-11% closed Sage on all three files with NO vendor library.**
Provisionality conditions on the re-based reference: (1) cp0 ablation CLEARED; (2) IM-isolation
ANSWERED FOR FREE -- the table arm is vendor-exact m/z + OPEN (rational) IM, the sdkcal arm was
vendor both: S30 11,976 vs 12,128 => ~93% of the +12.3% is m/z-side, ~1.3% (152 peptides) is the
vendor-IM contribution; (3) S08/S23 re-validated above. **New open-path reference: S30 = 11,976**
(the 12,128 SDK number stays as the vendor-oracle upper bound, not the shipping config).
Residual +1.5..+3.2 ppm persists across all files and BOTH calibration paths -> consistent with the
centroiding/mono-reporting hypothesis (Option I), not the m/z axis. diaTracer per-file ppm + S08/S23
head-to-head running to test whether part of it is instrument/per-file rather than ours.
