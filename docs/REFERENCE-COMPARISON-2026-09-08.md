# SpeXtractor vs the reference implementation, measured 2026-09-07/08

Everything here was measured on the current default build (**v35**, `perf:ms1_trace_bands=48`) against
the reference implementation's own output, using one scoring definition applied to BOTH sides:
Sage = unique peptides at rank 1 with `peptide_q <= 0.01`; MSFragger = the peptide-level target-decoy
walk. Entrapment FDR uses the human-target + Arabidopsis-entrapment search with the peptide-hypothesis
ratio 0.6805.

## Runtime and memory (TNBC 009, `data`, 100 threads both tools, same hour)

| | rep 1 | rep 2 | mean |
|---|---|---|---|
| reference implementation | 21:12.24 / 357.7 GB | 20:41.46 / 323.4 GB | 20:56.9 / 340.6 GB |
| **SpeXtractor v35** | 11:24.97 / 179.1 GB | 10:36.92 / 178.5 GB | **11:00.9 / 178.8 GB** |
| ratio | | | **0.53x wall, 0.53x RSS** |

Re-measured rather than taken from the earlier campaign, because `head2head.sh` records that a
cross-time comparison is what produced one withdrawn claim. Before this week's work the same file ran
**31:26.98** against the reference's 21:28.00, i.e. 1.46x SLOWER; it is now 1.90x faster.

Caveat on the memory ratio: the reference is a JVM run with `-Xmx400G`, so its peak RSS partly
reflects what it was allowed rather than what it needs (the same flags gave 268.2 GB in the earlier
campaign). SpeXtractor's 179 GB is a genuine requirement and is not sensitive to a heap flag.

## Quality, two files

| | TNBC 009 | | | TNBC 001 | | |
|---|---:|---:|---|---:|---:|---|
| | SpeX | ref | ratio | SpeX | ref | ratio |
| Sage peptides | 24,213 | 18,920 | **1.280** | 15,694 | 14,764 | **1.063** |
| Sage proteins | 5,813 | 4,944 | **1.176** | 4,074 | 3,802 | **1.072** |
| MSFragger peptides | 24,199 | 27,427 | **0.882** | 15,976 | 18,745 | **0.852** |
| entrapment FDR (SpeX) | 1.01% (0.86-1.20) | | | 0.98% (0.80-1.19) | | |

The direction is consistent across both files and the magnitude is not: SpeXtractor finds more with
Sage and fewer with MSFragger, and the Sage advantage is 1.28 on one file and 1.06 on the other.
Entrapment FDR is controlled at the nominal 1% in both, so the Sage advantage is not FDR inflation.

## Where the MSFragger deficit comes from

Characterising the 6,749 MSFragger peptides the reference finds on 009 and we do not:

| set | n | median hyperscore | z=1 | z=2 | z>=3 |
|---|---:|---:|---:|---:|---:|
| only reference | 6,749 | 18.19 | **21.1%** | 55.4% | 23.5% |
| common | 21,641 | 26.30 | ~0% | 70.0% | 29.9% |
| only SpeXtractor | 3,428 | 18.56 | ~0% | 70.1% | 27.8% |

Two things. First, both exclusive sets are **marginal** -- median hyperscore ~18 against ~26 for the
peptides both tools find -- so a large part of the "gap" is churn at the acceptance boundary rather
than signal we never emitted. Second, **21.1% of what we miss is charge 1**, against essentially none
of what we share: a class `charge:min_charge=2` never emits.

Confirmed by measurement, on 009:

| | z>=2 (shipped default) | z>=1 |
|---|---:|---:|
| Sage peptides | 24,245 | **27,685 (+14.2%)** |
| MSFragger peptides | 24,121 | **26,332 (+9.2%)** |
| Sage proteins | 5,802 | 5,641 (-2.8%) |
| entrapment FDR | 1.03% | **1.01%** |
| spectra | 2,343,822 | 4,035,058 (+72%) |
| wall | 11:59 | ~13:20 (+11%) |

Repeated on a second file, and it is stronger there:

| | TNBC 009 z>=2 -> z>=1 | TNBC 001 z>=2 -> z>=1 |
|---|---|---|
| Sage peptides | 24,245 -> 27,685 (**+14.2%**) | 15,694 -> 18,854 (**+20.1%**) |
| Sage ratio vs ref | 1.280 -> **1.463** | 1.063 -> **1.277** |
| MSFragger peptides | 24,121 -> 26,332 (**+9.2%**) | 15,976 -> 17,068 (**+6.8%**) |
| MSFragger ratio vs ref | 0.882 -> **0.960** | 0.852 -> **0.911** |
| Sage proteins | 5,802 -> 5,641 (-2.8%) | 4,074 -> 4,118 (+1.1%) |
| entrapment FDR | 1.03% -> **1.01%** | 0.98% -> **0.90%** |
| spectra | +72% | +64% |
| wall | +11% | +20% |

So on this dataset class the z>=2 default costs 14-20% of Sage peptides and most of the MSFragger
deficit, with entrapment FDR unchanged or better on both files. That directly contradicts the S30
measurement that established the default (where dropping z=1 GAINED peptides on both engines), so
`charge:min_charge` is dataset-dependent, not settled. Two things to resolve before changing it: the
protein count fell 2.8% on 009 while rising 1.1% on 001, and the cost is a 64-72% larger spectrum
file for 11-20% more wall.


## What the charge-1 spectra are (resolved 2026-09-08)

The +14-20% Sage gain from emitting z=1 was challenged: had we not already fixed a charge-assignment
defect, and was this the same class of error? An adversarial pass (GPT-6 Astra, a 10-agent Claude
workflow, and direct analysis of the extracted spectra) settled it. There are **two separate things**
inside the z=1 stratum, and the whole-run entrapment figure hid one of them.

### 1. The identifications are genuine singly charged peptides

| evidence | result |
|---|---|
| ion mobility vs the 2+ trend line (1/K0 = 0.5026 + 0.000729 m/z, fit on 15,001 z=2 IDs) | z=1 IDs sit **+0.29 Vs/cm2 above it** in every 100-Th bin; 99.4% above, 0.6% on the 2+ band. A halved 2+ ion would carry the 2+ mobility. |
| the reference implementation's own 1+ IDs | identical offset (+0.283 to +0.296), 99.9% above the 2+ line -- the same population |
| sequence chemistry | 92% are 7-9 residues, ~920 Da, 86% end in K, only ~12% carry any internal K/R/H (69% for z=2): single-basic-site tryptic peptides, the class that flies as 1+ |
| same sequence seen at both charges | 570 (009) / 422 (001) peptides: co-elute at dRT = 0, with the 1+ ion 0.65 1/K0 above its own 2+ in 100% of pairs |
| match quality | MSFragger matches 75% of theoretical b/y for z=1 (55% for z=2, 33% for decoys); extracted DTAs show mono m/z within ~5 ppm and b/y ladders at 1+ |
| the discriminating experiment | same spectra emitted with the charge UNSET so the engines search 2-4: **only 319 of 5,947 (5.4%) come back**, all at 2+ -- the dual-charge minority -- and the arm falls below the default (23,938 vs 24,245) |
| why the engines report 1+ at all | `precursor_charge 2-4` / `override_charge 0` is the fallback when the file carries no charge; both tools write charge 1 on these spectra and both engines honour it |

Neither tool has 1+ identifications below m/z 700, because a 1+ there is under the engines' mass
floor (500 Da, 7 residues).

### 2. Charge halving is real -- in the calls, not the identifications

The count walk calls a 2+ envelope z=1 whenever its M+1 (+0.5017) is missing or already claimed and
its M+2 (+1.0034) is present: z=1 then wins outright (M0, M2, M4 = 3 partners against z=2's 1).
Measured on 009: **~13% of the 2.55 M z=1 calls sit on the 2+ mobility band** (p2 = 51% there against
a 2.3% chance rate on the 1+ band), 60% of them below m/z 750 where a 1+ cannot be scored at all --
dead emission, and a lost 2+. Dropping z=1 (the old default) did not undo it: the walk had already
consumed the 2+ envelope's peaks, so the old default lost those 2+ ions too. **Fix:**
`charge:im_charge_veto` fits the 2+/3+ mobility lines per run from the run's own confident calls
(>= 3 isotopes, 25-Th bin medians, MAD residual scale) and re-calls any z=1 whose mobility lies within
2.5 sigma of them. Genuine 1+ ions are 7-8 sigma away and untouched.

### 3. The z=1 stratum runs ~2.8% entrapment FDR at a nominal 1% cut -- and the whole-run figure hid it

| stratum | 009, z>=1 arm | 001, z>=1 arm |
|---|---|---|
| z=1 | 5,145 peptides, **2.80%** (CI 2.25-3.30) | 3,465, **2.84%** (2.24-3.49) |
| z=2 | 0.43% | 0.39% |
| z=3 | 0.91% | 0.52% |
| whole run | 1.01% | 0.90% |

This is not an extraction artefact: decoys reproduce it (3.3-4.0% of z=1 targets clear the global
threshold against 0.3% of z=2), and zero z=1 peptides sit on the 2+ band. It is the ordinary
random-match rate of short peptides under one pooled score threshold subsidised by the strong z>=2
strata; adding the z=1 search space *lowered* the z>=2 strata (0.85 -> 0.43%), which is exactly why
the pooled 1.01% looked clean. Remedy is downstream (per-charge or per-length FDR). **A whole-run
entrapment figure must never again be quoted without its charge strata.**

### Decision

`charge:min_charge` default 2 -> 1, `charge:im_charge_veto` on. The z=1 peptides are real and the
reference implementation reports them too; the halved 2+ calls are corrected by physics the
instrument already measured; the residual stratum FDR is a search-engine calibration matter and is
now documented rather than hidden.
