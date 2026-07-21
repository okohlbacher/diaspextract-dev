# Charge inference: what the 15.9% is, and what will not fix it

The [[ms1-funnel]] localises **15.9%** of precursor loss to wrong charge assignment and
**10.5%** to failed monoisotope identification — against only 2.2% undetected. Truth-set
charge agreement is **47.8% vs diaTracer's 82.6%**, dominant confusion `4→2` (15,734 cases).

## Why 4→2 happens

Isotope spacing is 1/z. At z=4 that is 0.25 Da; at z=2, 0.50 Da. A spurious peak halfway
between two real isotopes is indistinguishable from a genuine z=4 partner **on spacing
alone** — and the higher-charge hypothesis always has more chances to find one, so the
error is systematically biased toward overcalling charge.

Cost in open search: ΔM = (z′−z)(m/z − 1.00728). Measured at m/z 600:

| ours | true | phantom ΔM |
|---|---|---|
| z=4 | z=2 | **−1198.0 Da** |
| z=3 | z=2 | −599.0 Da |
| z=1 | z=2 | +599.0 Da |

## FALSIFIED: ion mobility cannot break the tie

Hypothesis was that diaPASEF's mobility dimension constrains charge — the acquisition
tiles themselves track the charge-2 line, so charge ought to be separable in (m/z, 1/K0).
Tested against DIA-NN S08 ground truth (43,499 precursors with m/z, IM **and** true charge):

| m/z 600–700 | z=2 | z=3 | z=4 |
|---|---|---|---|
| 1/K0 | 0.993 ± 0.031 | 0.937 ± 0.044 | **0.966 ± 0.035** |

**z=4 lies between z=2 and z=3 — mobility is not monotonic in charge.** At fixed m/z a
higher-charge peptide is proportionally heavier (mass = z × m/z), so its larger CCS
cancels the extra charge, non-monotonically.

Nearest-neighbour test (m/z ±2 Da, closest IM): **75.0% share charge vs a 69.6% chance
baseline — +5.4 points.** The plane carries almost no charge information beyond the base
rate. Do not build an IM-based charge prior.

This also retires the broader "use `ScanNumBegin`/`ScanNumEnd` to gate charge" idea. The
tile IM range is still worth using as a *transmission* filter (a precursor outside the
tile's mobility band could not have produced its fragments), but not as charge evidence.

## What is left

Isotope-envelope **intensity** matching: for a genuine z=4 precursor of mass ~2400 Da the
averagine model predicts specific M/M+1/M+2 abundance ratios. A spurious +0.25 Da peak
will not match them. Spacing is degenerate between z and 2z; **abundance is not**.

`charge:scoring=envelope` already implements this path and is default-OFF. It was
evaluated only under `spectrum_q` — see the correction in [[S08-results]] — so its prior
assessment is not trustworthy and it must be re-judged at `peptide_q`.
