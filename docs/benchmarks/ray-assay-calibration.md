# The delta-mass ray assay cannot quantify charge errors (calibration, S30)

## What was tested

`corrupt_charge.py` rewrote the reported charge of a known fraction of precursors, leaving m/z
untouched — exactly the error the tool makes in the field. The resulting neutral mass shifts by
`(z_new − z_old)(m/z − PROTON)` with no other change to the spectrum. The assay should then see
those PSMs as a straight ray of integer slope in (precursor m/z, Δmass).

Arm 1, `--from-z 4 --to-z 2` (true z=4 reported as z=2, k = −2), symmetric ±3000 Da window:

```
injected                     3,865
raw PSMs                 1,465,760
survive 1% entrapment FDR    1,754   (0.12%)
modified PSMs                  884
rays detected                   {}   <- ZERO
```

**Recovery is 0%.** Not low — zero, from 3,865 injected.

## Why

Only **0.12%** of PSMs survive 1% entrapment FDR in open search. A spectrum with a corrupted
precursor mass *can* still be identified — that is what open search is for — but the resulting
PSM must clear a threshold set against 1.47M candidates. Essentially none do.

So injected charge errors are real, and invisible by construction.

## What this retracts

**"The control fired at p ≈ 2.4×10⁻⁶"** was arithmetically correct about excess over base rate
(26 slope-+2 events vs 8.9 expected) but is **not evidence the instrument can measure anything**.
It detected 26 events out of an unknown true number, and the calibration puts the recovery rate
at zero. A ratio without a denominator is not a measurement.

This is the third metric on this project to fail once its control was actually run — after the
MS1 funnel (91.9% chance floor) and the ion-mobility charge prior (wrong null). The pattern is
consistent: the metric was reported first and calibrated later.

## Consequences

* The entrapment open-search benchmark **cannot quantify charge errors**. Presence/absence
  claims are also doubtful at 0/3,865.
* More broadly: **open search at 1% entrapment FDR retains 0.12% of PSMs on pseudo-DDA spectra**.
  Any open-search metric here describes a tiny, heavily-selected subset. That is a property of
  the regime, not a bug in the script.
* The **DIA-NN-anchored** charge measurement (74.6% agreement against a 69.6% majority-class
  constant) therefore remains the better instrument for this question, despite its own
  limitation — DIA-NN's tryptic / z2–4 / ≤2-mod space cannot contain non-canonical species.

## Still open

Arm 2 (`--from-z 2 --to-z 4`, k = +2, **99,984 injected** — 26× more) is running. If recovery is
genuinely zero rather than merely small, that arm bounds it far more tightly. A non-zero result
there would mean detectability depends on error *direction*, which would be a different and
more interesting finding than a flat null.
