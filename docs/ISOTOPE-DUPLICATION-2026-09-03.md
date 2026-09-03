# Is our emission inflated by M+1/M+2 precursors, and can those spectra be merged?

**Hypothesis (user, 2026-09-03).** We emit 927,813 pseudo-spectra on S30 where diaTracer emits
700,434. Two claims to test: (a) the excess comes from selecting M+1/M+2 as precursors in their own
right instead of the monoisotope; (b) those spectra are basically identical and could be merged.

**Verdict: (a) confirmed and large. (b) refuted -- they are not near-duplicates, and no ordering rule
can collapse them without losing a quarter of the peptides.** The lever is upstream, at precursor
selection, and the mechanism is now named.

Scripts: `bench/iso_dup.py` (emission-level census + identification join), `bench/iso_collapse.py`
(collapse-rule evaluation), `bench/iso_sim.py` (content similarity). All run on the shipping arm
output `d7_apex/pseudo.mzML` (apex estimator, `require_isotope_support`), no re-extraction.

## 1. The duplication is real, and it is the whole of the excess

A spectrum counts as a duplicate if another EMITTED spectrum sits k isotope steps below it
(k = 1..3) at the same charge, within 3 s in RT and 0.02 in 1/K0. Both tolerances are at least as
tight as the extractor's own isotope-partner gate (`gate:delta_rt` 3.0 s,
`charge:iso_im_tolerance` 0.05), so every pair counted here was reachable by the extractor and was
not linked. The decoy offset is the same step plus 0.5/z -- same magnitude, off the isotope lattice --
because at 10^6 spectra in a narrow m/z range, lattice coincidences happen by chance.

| offset | spectra with a partner below | % of emission |
|---|---|---|
| isotope k*1.00335/z | 291,657 | 31.4% |
| decoy +0.5/z | 35,114 | 3.8% |
| **excess (real)** | **256,543** | **27.7%** |

Steps: k=1 177,689; k=2 62,795; k=3 51,173. Removing every heavier member leaves **671,270 spectra,
4% BELOW diaTracer's 700,434.** The inflation is isotope-offset duplication, essentially in full.

## 2. They are NOT near-duplicates in content

Binned sqrt-intensity cosine on 1,500 sampled pairs of each kind:

| pair type | median cosine | p25 | p75 | > 0.9 |
|---|---|---|---|---|
| isotope-linked | 0.505 | 0.316 | 0.721 | 6.5% |
| co-eluting neighbour, off-lattice | 0.446 | 0.250 | 0.686 | 6.3% |
| random spectra | 0.022 | 0.011 | 0.036 | 0.0% |

Being one isotope step apart adds almost nothing to content similarity over an arbitrary co-eluting
neighbour (0.505 vs 0.446); both sit far above random only because co-eluting spectra in one window
draw from the same fragment pool. **Only 6.5% are near-identical.** Each precursor hypothesis runs
its own fragment correlation and selects a different subset, so these are different extractions under
different mass labels, not one extraction emitted twice.

## 3. Collapsing loses peptides under every rule, and the naive rule is backwards

Identification join, Sage 1% spectrum-FDR, 291,657 isotope-linked pairs:

| | pairs | % |
|---|---|---|
| neither identified | 234,768 | 80.5% |
| both, same peptide (genuinely redundant) | 23,570 | 8.1% |
| **only the HEAVY one identified** | **20,966** | **7.2%** |
| only the light one identified | 11,389 | 3.9% |
| both, different peptides | 964 | 0.3% |

Dropping every heavy member loses **3,797 of 14,944 peptides (25%)**. Collapsing connected components
of the isotope graph (73,558 multi-member groups covering 445,917 spectra) to one member each:

| rule | spectra kept | peptides kept | lost |
|---|---|---|---|
| keep lightest (the naive rule) | 555,454 (59.9%) | 9,771 | 5,173 |
| keep most isotope partners | 555,454 | 9,933 | 5,011 |
| keep richest spectrum | 555,454 | 9,880 | 5,064 |
| **oracle (keep whichever was identified)** | 555,454 | 13,557 | **1,387** |

Even the oracle loses 1,387: single-linkage chains span genuinely different species. This reproduces
the earlier blanket falsification of `merge:rt_window` and `consolidate:delta_rt` and explains it.

**And "keep the lightest" is backwards.** Sage's own isotope correction on the identified member
(offset 0 = the mass we reported was right):

| | offset -1 | 0 | +1 | +2 |
|---|---|---|---|---|
| heavy-only identified | 4,904 | **14,624 (70%)** | 1,193 | 245 |
| light-only identified | 6,236 | 4,458 (39%) | 454 | 241 |

When only the heavy member is identified, 70% of the time the mass WE reported for it was correct --
the heavier member is the true monoisotope and its lighter partner is the spurious one. Even among
light-only identifications, 55% needed a -1 correction, i.e. that mass was also below the true mono.
Our monoisotope assignment errs systematically TOO LIGHT, consistent with the documented 22.9%
wrong-mono rate and with `findPartner` matching m/z, RT and IM but never intensity.

## 4. Mechanism: a consumed peak is invisible, so the leftover seeds its own precursor

`findPartner` skips any peak already marked `used[]` (src/DIAPseudoSpectra.cpp:1129). When an earlier
seed consumes a run, a remaining peak one step up can no longer walk left to it, finds nothing, and
becomes its own monoisotope. The signature is visible in the emitted metadata: heavy members carry
systematically FEWER isotope partners than their light partners (`spx_n_isotopes` mean 3.53 vs 4.59;
34.0% of heavy members are at the minimum of 2 against 13.9% of light members). Group sizes run to
9+ members, the chain such sequential consumption produces.

## 5. What follows

The excess is not redundancy to be merged away downstream; it is over-generation to be prevented
upstream, and every downstream collapse tested costs more peptides than it saves spectra. That
matches the standing finding that only a precursor quality gate can reach diaTracer's count, and it
sharpens it: the gate must be an OWNERSHIP rule, not an m/z ordering rule.

**Pre-registered next experiment (not yet run).** Replace the `used[]` boolean with owner tracking:
when a new seed's isotope-lattice neighbour at the same charge is already owned by an emitted
precursor, suppress the new precursor instead of letting it become a fresh monoisotope. A/B on S30,
both engines, plus entrapment. Prediction: emission falls toward ~670-700k with peptides within
replicate noise. Falsifier: peptides fall by more than the 0.17% replicate spread -- which the 7.2%
heavy-only-identified population makes a real risk, since suppression discards exactly the member
that is right 70% of the time. If it fires, the correct form is REPLACEMENT (transfer ownership to
the better-fitting member), not suppression.

## 6. Implemented: collapse the precursors before extraction

`SPEXTRACT_ISO_COLLAPSE=intense|light|heavy|niso` (with `SPEXTRACT_ISO_COLLAPSE_K`, default 3) runs
after the isotope-support gate and before the window loop, so the duplicate hypotheses never reach
extraction and their extraction cost is saved as well.

**Structure: a greedy dominating set, NOT single linkage.** Precursors are visited best-first by the
rule; each survivor removes the co-eluting, co-mobile, same-charge hypotheses sitting 1..K isotope
steps to either side of it, and an already-kept precursor is never removed. Transitive chaining is
what made the offline component collapse lose 1,387 peptides even with an oracle (chains span
genuinely different species), so each removal is one hop from a surviving member.

**Default rule is MS1 trace intensity, and the direction matters.** The measured failure is
symmetric: sometimes we seed on a spurious peak below the true mono, sometimes on a leftover above a
consumed run. Intensity is right in both cases, because a spurious peak below the mono is weaker and
the mono outweighs its own M+1 below about 1800 Da. Above that the rule inverts, which is why `light`
runs as a control rather than as an assumption.

**Pre-registered A/B (S30, queued behind the S08/S23 confirmation chain):** arms `intense` K=3,
`light` K=3, `intense` K=1. Both engines; entrapment on the default arm, since a large emission cut
changes the FDR denominator. Success = emission near 670-700k with Sage and MSFragger peptides within
the 0.17% replicate spread and entrapment no worse than the shipping arm's 1.37%. Falsifier = peptides
fall outside that spread, which would mean the duplicate hypotheses were carrying real content that
the survivor's own extraction does not recover -- and would close the emission question for good.
