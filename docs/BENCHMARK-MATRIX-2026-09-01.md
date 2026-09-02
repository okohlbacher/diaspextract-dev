# Full benchmark matrix: all tools x all datasets x all calibration methods x both engines

S30/S08/S23 (AGXT PH1 liver diaPASEF, same cohort/instrument). Both engines deterministic (sigma=0),
so counts are exact. speXtract config throughout: isotope-support gate + corr_power=2 (current
defaults); only the TOF->m/z calibration path varies. diaTracer references for S08/S23 created
2026-09-01 (previously S30-only).

## Sage, closed search, peptides @1% peptide_q
| file | chord (old default) | **TDF-table model (open)** | vendor SDK | diaTracer | table vs dt |
|---|---|---|---|---|---|
| S30 | 10,802 | **11,976** | 12,128 | 11,517 | **104.0%** |
| S08 |  9,735 | **10,333** | -- | 10,242 | **100.9%** |
| S23 |  9,032 | **9,891**  | -- |  8,948 | **110.5%** |
Calibration effect (chord -> table): **+10.9% / +6.1% / +9.5%**.

## MSFragger 4.4.1, peptidoform-level @1% target-decoy FDR
| file | chord | **TDF-table model** | vendor SDK | diaTracer | table vs dt |
|---|---|---|---|---|---|
| S30 | 11,560 | **11,463** | 11,460 | 13,932 | 82.3% |
| S08 | 11,350 | **11,465** | -- | 13,666 | 83.9% |
| S23 |  9,486 | **9,404**  | -- | 10,606 | 88.7% |
Calibration effect: **-0.8% / +1.0% / -0.9% = FLAT within noise on every file.**

## Mass accuracy (median ppm on identified precursors, |delta| < 0.9 Da)
| file | chord | table model | vendor SDK | diaTracer |
|---|---|---|---|---|
| S30 | -8.29 | +1.49 | +1.74 | -1.37 |
| S08 | --    | +3.19 | --    | +0.27 |
| S23 | --    | +2.29 | --    | -0.60 |

## What the matrix says
1. **The calibration fix is real and generalises** on Sage: +8.8% mean, 95% CI [+2.7, +15.0] (n=3
   paired), from the file's own MzCalibration table, no vendor library. IMPORTANT FRAMING (review):
   this is an IDENTIFICATION-YIELD effect, not better pseudo-spectra -- emission moved -0.23% and the
   spectra are informationally near-identical; Sage converts a corrected mass axis into yield because
   mass error is a discriminant FEATURE. And since diaTracer's spectra always carried vendor
   calibration, every earlier head-to-head was biased AGAINST us by this same mechanism: **the
   +6-11% is the removal of a self-inflicted handicap, not a lead over diaTracer.**
2. **The table model reproduces the vendor SDK** (S30 11,976 vs 12,128; the 1.3% delta is the
   vendor IM converter, not m/z) and is exact against the vendor oracle (2.5e-5 ppm, tests/).
3. **MSFragger is INSENSITIVE to input calibration** (flat across chord/table/SDK on all 3 files).
   CORRECTED REASON (adversarial review 2026-09-01): NOT "calibrate_mass absorbs it" -- that was
   inferred from a default we never set (bench/run_joint.sh writes msfragger.params without
   calibrate_mass) and never verified in the engine log. The real reason is our HARNESS: the
   MSFragger arm is scored by a raw-hyperscore target-decoy walk with NO rescoring
   (bench/joint_bench.py, bench/score_msf.py), and hyperscore is matched-fragment count and
   intensity -- it contains no mass-error term, so it is structurally near-blind to an m/z shift.
   Sage's discriminant, by contrast, uses delta_mass and average_ppm as FEATURES. The conclusion
   survives (MSFragger is useless as a calibration readout) but the mechanism is scoring-function
   blindness, not engine-side recalibration. Its flatness does, however, BOUND the spectral-content
   channel at |delta| <= 1%.
4. **The engine asymmetry is the headline honesty problem -- and n=3 statistics make it worse for us:
   Sage 105.1% mean, 95% CI [93.0, 117.3] = CONSISTENT WITH PARITY, NOT AN ADVANTAGE; MSFragger
   85.0%, 95% CI [76.7, 93.2] = a STATISTICALLY SUPPORTED DEFICIT.** "Matches or exceeds on all
   three files" is not a defensible claim (S08's +91 peptides is inside noise). Any public claim must show both engines. The MSFragger gap is
   search/detection-side (it survives perfect masses) -- consistent with the earlier finding that
   ~34% of missed peptides already have a near-threshold PSM.
5. **Our residual ppm (+1.5..+3.2) is consistently 2-4 ppm above diaTracer's (-1.4..+0.3)** on the
   same files with the same engine -> ours, not the instrument (centroiding/mono-reporting).
6. Emission ~1.32x diaTracer stands; per-1k-spectra efficiency still favours diaTracer.

## PRE-TAG FINDINGS (2026-09-01, after the 3-way adversarial review)

### 1. Determinism must be re-scoped: output IS thread-count dependent
`bench/semantic_digest.py` hashes the mzML from `<spectrumList` onwards, because two runs can never
be byte-identical for TWO reasons that each already cost this project a false "determinism FAIL":
OpenMS stamps a wall-clock `MS:1000747 completion time`, AND the header records the run's own
parameters -- so a threads-8 file and a threads-100 file differ in the header BY CONSTRUCTION.
That retroactively explains the July r1-vs-imw005 md5 mismatch recorded as unexplained.
**But with both artefacts removed, the SPECTRUM DATA still differs between threads 8 and 100.**
So: bit-determinism holds (as previously verified) at FIXED thread count; it does NOT hold across
thread counts. Every benchmark in this project used `-threads 100`, so no published number is
affected -- but the claim must be stated as "deterministic at fixed thread count", and the
fixed-thread check is now an explicit gate (running).

### 2. The pipeline is CHAOTICALLY SENSITIVE -- cross-binary comparisons carry ~2% uncertainty
Replacing the quadratic root `(-b+sqrt(disc))/(2c)` with the algebraically identical but
cancellation-free `2(t-C0)/(b+sqrt(disc))` -- a ~1e-11 relative change, i.e. ~1e-5 ppm -- moved
emission 921,938 -> 923,713 (+0.19%) and closed Sage 11,976 -> 12,200 (+1.9%). Greedy trace/gate
thresholds amplify last-ulp differences. **CONSEQUENCE: the 0.06% "noise floor" in the decision rule
is a SAME-BINARY figure. Comparisons across code versions carry ~2%.** The corr_power (+8-10%) and
calibration (+6-11%) results are far above that; every small lever ever decided across a rebuild is
not. 11,976 and 12,200 are the same number in this sense; the doc keeps 11,976 (the arm that was
actually benchmarked end-to-end).

### 3. dPeptides/dppm measured directly (the review's proposed control)
A UNIFORM affine m/z rescale changes no peak, no intensity, no count and no mass difference beyond
1e-6 relative -- the content channel is exactly zero by construction, unlike the nonlinear chord bow.
FRAGMENT-channel only (an early regex bug shifted arrays but not `selected ion m/z`, which usefully
isolated the channel): baseline 11,976; -1.5 ppm 11,934 (-42); +1.5 ppm 11,939 (-37); -3.0 ppm
11,811 (-165). Symmetric and quadratic-ish about zero -- the signature of mass accuracy feeding the
score, and an independent confirmation that the calibration gain is an identification-yield effect.
Precursor-channel and both-channel arms running.
**Governance consequence (review's "thing everybody missed"): peptides@1%FDR is partly a
mass-calibration measurement, so 11,976 is only comparable to future numbers taken at the same
residual ppm. Any future lever must report its ppm median beside its count.**

## MSFragger gap: hypothesis tests (2026-09-02)
Post-hoc on the archived TSVs, same global raw-hyperscore 1% walk that produced the matrix:
| | speXtract | diaTracer |
|---|---|---|
| PSM charges searched | 1+ 44,490 · 2+ 326,462 · 3+ 167,203 · 4+ 29,894 · 5+ 4,268 | 1+ 12,969 · 2+ 277,753 · 3+ 161,487 · 4+ 45,030 |
| accepted @1%, all charges | 11,463 (threshold hyperscore **15.205**, 358,493 distinct keys) | 13,932 (threshold **14.033**, 407,432 keys) |
| accepted @1%, z in {2,3} only | 11,327 (**-136**) | 13,722 (-210) |
- **H7 "MSFragger discards our z=1/4/5 spectra": DEAD.** It searched all charges (`precursor_charge` is
  a fallback for charge-less spectra only; confirmed by the charge column).
- **H1 "our extra low-yield spectra broaden the null and raise the threshold": DEAD.** Deleting every
  z!=2,3 PSM LOWERS our count (-136); a null-broadening tax would have raised it.
- **H-B/H-C/H-D/H-F (isolation window mode switch, TIC/title/base-peak metadata, 500-peak padding,
  encoding): DEAD** -- identical MSFragger parameters in both logs; the MSFTBX reader does not even
  parse the spectrum title; use_topN_peaks=150 caps both.
- **What survives:** our accepted-hyperscore threshold IS higher (15.2 vs 14.0) with FEWER distinct
  candidates (358k vs 407k) -> diaTracer's target scores sit higher relative to decoys in the TAIL;
  for the 9,405 shared peptides the scores are identical. I.e. coverage/quality of the faint tail
  (codex: 53-75% of the gap) plus kimi's reading of H-A as attribute CORRUPTION (a wrong charge label
  -> wrong precursor mass, invisible to a 25 ppm closed search in either engine; 16-35%). Decisive
  test for the latter running: MSFragger with override_charge=1, z=1..5, both tools.
- **"Is there additional information MSFragger can use?" -- No.** Nothing diaTracer writes that we
  do not is consumed by scoring. The deficit is in what we emit, not what we annotate.
