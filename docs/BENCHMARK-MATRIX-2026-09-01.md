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
