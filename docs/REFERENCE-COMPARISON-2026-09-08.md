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
