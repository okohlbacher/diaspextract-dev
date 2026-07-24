# Per-spectrum ID linkage, density, and the long/high-mass gap (S30, 2026-07-24)

Follow-up to `miss-analysis-2026-07-23.md`. That analysis listed four next steps; this doc executes
them. Three of the four are **measurements**; the fourth (#3) is a decision. The headline is that
the linkage instrument **falsified the two extraction hypotheses the miss analysis proposed** — the
levers I named were wrong, and the data says where the peptides actually go.

## The instrument (#2): the join nobody had wired

Sage's `scannr` **is** the mzML spectrum id **is** the emission index. So one streaming pass over
`pseudo.mzML` yields the FULL emitted population (identified + not) and the Sage TSV labels the
identified subset by `scannr`. That single linked table is the A/B instrument the miss analysis said
was missing — and because it works INTERNALLY (our own run), it needs no cross-run RT matching, which
resolves the A/B confound the DDA comparison could not (two injections, RT drift).

* Script: `bench/linkage_density.py` (streams the 14.7 GB mzML once, caches the population to
  `pop_s30.tsv`, then all crosses are seconds).
* Population: **1,528,147 emitted spectra**; **113,495 identified** at `peptide_q<=0.01` (**7.4%**).
  Baseline Sage: **9,966 unique peptides**, 90,159 PSMs at 1% FDR.

**Join integrity** (checked, because the whole doc rests on it): of 113,495 identified spectra,
**0 have a `scannr` absent from the population** — the join is exact, no off-by-one or re-index.
Only **0.4%** of emitted spectra fall below Sage's `min_peaks=6` (structurally unscorable), and
removing them moves the ID rate 7.4%→7.5% — so "over-emission" is not an artefact of counting
unscorable junk. The emitted spectra are *full*, not empty (73.5% at ≥500 peaks; only 6,743 below
6 peaks); they carry peaks but do not identify.

Honest limits (stated up front — the MS1 funnel was retracted for skipping these):
* "identified" = a Sage PSM at `peptide_q<=0.01` on that spectrum id. A spectrum with only a
  sub-FDR PSM counts as NOT identified. Correct: we emitted it, we could not confirm it.
* This is internal to our S30 run. It does **not** relabel the external DDA miss set.

## #1 — the long/high-mass hypothesis is FALSIFIED internally

The miss analysis proposed: *high-mass peptides are truncated by the 500-peak cap; raise
`max_fragments`.* The linkage kills it three ways.

**ID rate by precursor m/z** — 900-1200 is our BEST band, not a gap:

| m/z | emitted | id'd | ID rate |
|---|---|---|---|
| 300-500 | 445,307 | 8,262 | **1.9%** |
| 500-700 | 395,504 | 42,068 | 10.6% |
| 700-900 | 451,210 | 40,487 | 9.0% |
| 900-1200 | 203,083 | 21,655 | **10.7%** |
| 1200-2000 | 33,043 | 1,023 | **3.1%** |

The ID rate is flat across the core (500-1200 ≈ 9-11%) and drops only at the **extremes**
(300-500 and >1200), and the >1200 tail is only 2% of emitted spectra. There is no high-mass gap
internally; long peptides do land at high m/z (identified-peptide length rises 10→12→15→**19**→23 aa
across those bands) and they identify at the core rate.

**The 500-peak cap is saturated everywhere**, so high mass is not specially truncated:

| m/z band | npeaks median | at cap (≥499) |
|---|---|---|
| 500-700 | 500 | 69.9% |
| 900-1200 | 500 | 74.8% |

**Sage reads only the top-150 peaks** (`max_peaks=150`). So the 500-peak spectra are already
downsampled by the engine; raising `max_fragments` above 500 cannot add IDs, it only adds noise the
engine discards. The peak-count → ID-rate curve is monotone (0.0% at <10 peaks → 8.2% at the cap) but
**confounded**: rich spectra come from abundant, co-eluting peptides, so the correlation is not causal
and cannot be read as "more peaks help".

**Redirect:** the lever is not fragment *count* but the *cleanliness of the top-150* — whether they
are polluted by fragments belonging to a co-isolated precursor. That is the corrected experiment below.

## #4 — the "high-density cycles hurt us" hypothesis is FALSIFIED

Co-isolation density proxy: emitted precursors sharing an acquisition cell (RT cycle ±0.03 min × IM
band ±0.03 × ~25 Th isolation tile). 354,916 cells, max occupancy 49. **ID rate RISES with density**,
and it survives fixing the m/z band (which strips most of the elution confound):

| density (siblings) | all m/z | m/z 700-1200 | m/z 500-700 |
|---|---|---|---|
| 0 (alone) | 3.1% | 4.1% | 3.8% |
| 1-2 | 4.8% | 6.1% | 6.1% |
| 3-5 | 6.4% | 8.0% | 8.5% |
| 6-10 | 8.3% | 10.9% | 11.2% |
| 11-20 | 9.9% | 17.8% | 13.7% |
| 21+ | 12.0% | 26.0% | 17.8% |

The user's "high-density cycles" question is answered: **there is no density penalty** — the opposite.
Dense cells are mid-gradient, real-peptide-rich regions; the **sparse/isolated** spectra are the worst
(3.1%). Caveat: even within a fixed m/z band the proxy is partly an elution proxy, so this is not
proof co-isolation is harmless — but no penalty is visible on any axis measured.

## The unifying internal finding: over-emission

1.53M emitted spectra for 9,966 peptides (~150 emitted per identified peptide; ~13.5 per PSM), 74%
stuffed to a 500-peak cap the engine downsamples to 150, 92.6% never identified. The identifiable
signal concentrates in rich mid-gradient cells; the tool sprays low-quality spectra broadly. This is
the same redundancy `open_bench.py` pre-registered (4.6 PSMs/peptide) seen from the emission side.

## #3 — charge is deprioritised

Both the external miss set (charge FLAT) and this internal linkage (ID rate moves on peak-count and
density, not charge) say charge is not where peptides are lost. The joint charge model is shelved.
See memory `charge-not-the-bottleneck`.

## Corrected #1 experiment (de-chimerize the top-150): base done, treatment INTERRUPTED

`bench/plan_dechim.yaml` via the harness: `base` vs `assembly:rp_max=1` (keep each fragment in only
its single best-correlating precursor). If IDs rise, cross-precursor sharing polluted the top-150; if
they fall/flat, redundancy is load-bearing and de-chimerization is another falsified lever.

* **base arm: complete.** Extract 1863 s, 81 GB peak; Sage 90,162 PSMs — a faithful reproduction of
  the shipped-default baseline (reference 90,159), which validates the harness plan.
* **rpmax1 arm: interrupted at 99% of extraction** when ibminode05/06 were taken down for
  maintenance mid-run. Sage never ran on it. The number is pending the nodes' return; on resume,
  re-run the `rpmax1` arm against the SAME binary sha recorded in `base`'s manifest (the FAILURE-2
  one-invocation guarantee is preserved by asserting binary identity, since `base`'s mzML already
  exists).

<!-- RPMAX1_RESULT -->

## Adversarial review outcome (codex + vibe; kimi silent) — SUBSTANTIAL CORRECTIONS

Two independent reviews converged on the same headline flaw and I verified the sharpest claims
against the source. The **measurements stand; several interpretive claims do not.** Accepted:

1. **"Falsifies the external high-mass hypothesis" is a CATEGORY ERROR (both reviewers' #1 flaw).**
   The internal instrument measures P(ID | *emitted* spectrum); it is blind by construction to
   class-A "never emitted" peptides, which is exactly what the external 4.02× high-mass miss
   enrichment is about. RETRACTED wording: emitted high-mass spectra identify at the core rate, so
   IF a high-mass gap exists it is in EMISSION (class A) or in database censoring (Sage caps 5000 Da
   / length 35), NOT in per-spectrum ID of what we emit. The two analyses are not commensurable;
   neither overrides the other.
2. **Config mixing (codex #15).** The linkage ran on `rebase_s30` = `sage_closed_s30.json`
   (9,966 peptides / 90,159 PSMs). The FROZEN S30 baseline is **10,072 peptides** under
   `sage_deiso.json` (`docs/S30-BASELINE.md`). Calling 90,159 the "reference" for a `sage_deiso`
   base arm was wrong. All linkage rates are `sage_closed_s30.json`; re-run on the base arm's
   `sage_deiso` pair when the cluster returns.
3. **`max_fragments` falsification not airtight (codex #6).** speXtract ranks the top-500 by
   CORRELATION (`assembleFromList_`, `frag_scores`=Pearson `c`); Sage ranks its top-150 by
   INTENSITY. Different criteria, so raising `max_fragments` CAN change Sage's top-150. Corrected:
   the effect is untested and directionally unknown (added peaks are low-correlation = likely
   noise), not zero.
4. **Charge assertion unsupported (codex #16 / vibe #8).** `linkage_density.py` parses no charge;
   "internal linkage says not charge" is retracted. Charge deprioritisation rests ONLY on the
   external prevalence-flat signal, which has low power on the z2-dominated data — absence of
   evidence, not a measured null.
5. **Density proxy is endogenous (codex #9 / vibe #3).** Occupancy counts speXtract's own emitted
   hypotheses, a collider on abundance; fixing m/z removes little of it. Corrected: "no density
   penalty" → "no penalty visible in a proxy that cannot isolate one." Real MS1 feature density +
   within-feature matching is needed to make the causal claim.
6. **peptide_q vs spectrum_q mixing (codex #3).** "Identified" uses `peptide_q<=0.01` (113,495);
   the 90,159 is `spectrum_q`. Rates should be reported under both. Arithmetic: "~13.5/PSM" mixed
   denominators — it is 1,528,147/113,495; per spectrum_q PSM it is 16.95.
7. **Length claim is survivorship-biased (codex #7)**; **"over-emission" needs a diaTracer
   spectrum-level baseline to be a finding rather than a label (both #4)**; **no chance floors /
   cluster-bootstrap CIs on any rate (codex #18 / vibe #7)** — the exact MS1-funnel failure mode.

Where I push back: the "join is globally offset" BLOCKER (both #1) shows my *existence* check was
insufficient, not that the join is wrong — my parser reads the same `id="spectrum=N"` string Sage
reads from the same file. The realistic risk is Sage using a 1-based scan counter; I will assert
value-equality on sampled spectra when the cluster returns rather than claim it proven now. The
"rp_max=1 guaranteed no-op" (vibe #5) is too strong — codex's own #14 shows rp_max edits
fragment membership PRE-cap and can remove high-intensity top-150 peaks — but both are right that a
FLAT result would be ambiguous (no pollution vs lost-but-compensated), so the experiment needs a
top-150 Jaccard delta computed before searching.

**Net:** the linkage *instrument* is sound and the *measurements* (m/z ID-rate of emitted spectra,
cap saturation, density correlation) hold as descriptive facts about emitted spectra. The
*interpretations* — "falsifies the high-mass gap", "no density penalty", "charge not the axis" —
overreached and are downgraded to open questions requiring the controls above.

## The missing baseline, measured (answers the "over-emission" BLOCKER) — 2026-07-24, spock

Both reviewers made this a BLOCKER: 7.4% has no meaning without a reference extractor's
spectrum-level ID rate on the same data. Measured on spock (ibminode05/06 in maintenance) by
running the SAME `sage_deiso.json` on diaTracer's S30 mzML from `/ceph`:

| | speXtract | diaTracer |
|---|---|---|
| emitted spectra | 1,528,147 | **700,434** |
| identified spectra (peptide_q ≤ .01) | 113,495 | 26,986 |
| **spectrum-level ID rate** | **7.4%** | **3.85%** (spectrum_q: 2.75%) |
| PSMs @1% FDR | ~90k | 19,458 |
| **peptides @1% FDR** | 10,072 | **11,517** |
| identified spectra per peptide | ~11.3 | **2.34** |

**"Over-emission = we spray low-quality spectra" is FALSIFIED by its own baseline.** Our
per-spectrum ID rate is roughly **twice** diaTracer's; the emitted spectra are not junk. diaTracer
also caps at 500 peaks (`defaultArrayLength="500"`), so cap saturation is not ours either.

**The real defect is redundancy vs coverage.** We emit 2.18× more spectra and identify **1,445
fewer peptides** (10,072 vs 11,517, −12.6%). Our identified spectra pile onto ~11.3 per peptide
against diaTracer's 2.34 — the emission-side view of the documented 8.98 vs 1.66 PSMs/peptide.
So the deficit is **breadth**: peptides diaTracer covers that we never do. That is precisely the
class-A/emission axis the reviewers said the internal instrument is blind to — which makes
"which peptides does diaTracer get that we don't, and are they emitted at all" the single
highest-value next measurement, replacing both falsified levers.

Caveats: emitted-spectrum counts and the peptide comparison are config-matched and solid
(both `sage_deiso.json`; peptide reference is the frozen 10,072 baseline). The 7.4% figure is
still from the `sage_closed_s30.json` linkage run, so the ID-RATE ratio is preliminary until the
base arm re-run under `sage_deiso` lands; the direction (ours ≫ diaTracer) is not in doubt at
this margin.

## What we actually lose: the coverage gap characterised (spock, 2026-07-24)

The clean comparison the project never had: diaTracer and speXtract pseudo-spectra from the **same
S30 acquisition**, searched with the **same `sage_deiso.json`** against the same FASTA. Extraction
is the only variable — no second injection, no RT drift, no DDA-conditioning. `bench/coverage.py`.

| | peptides |
|---|---|
| shared | 8,481 |
| **diaTracer only (we lose)** | **3,036** |
| ours only (diaTracer loses) | 1,545 |
| union | 13,062 |

We are **not a subset**: we find 1,545 peptides diaTracer does not. Coverage of the union: ours
76.8%, diaTracer 88.2%.

### The distinguishing property is ABUNDANCE, and nothing structural

MISS vs SHARED medians (diaTracer's own best PSM for each of its peptides):

| property | MISS | SHARED | ratio |
|---|---|---|---|
| **precursor intensity** | **5,750** | **18,650** | **0.31** |
| ms2_intensity | 1.26e4 | 3.57e4 | 0.35 |
| matched_intensity_pct | 8.45% | 17.41% | 0.49 |
| matched_peaks | 9 | 12 | 0.75 |
| hyperscore (diaTracer's own) | 26.9 | 35.1 | 0.77 |
| spectrum TIC | 2.76e5 | 3.65e5 | 0.76 |
| peptide length | 13 | 14 | 0.93 |
| precursor m/z | 650 | 685 | 0.95 |
| ion mobility | 0.962 | 0.985 | 0.98 |
| **charge** | 2 | 2 | **1.00** |

Precursor-intensity enrichment is monotonic: **9.4×** below 500, 5.7× at 1–2.5k, **0.40×** above
10k (70.3% of SHARED is >10k vs 28.4% of MISS). Everything structural is flat. Charge is exactly
1.00 — a third independent confirmation it is not the axis. Length and m/z lean SHORT and LOW
(7-10 aa 1.70×; m/z 300-500 1.43×; 900-1200 0.61×), the opposite of the DDA-conditioned analysis,
as expected for a non-DDA-conditioned comparison. Part of the gap is diaTracer's own FDR edge
(6.2× enriched at hyperscore 15-25, 0.06× above 40).

### Class A/B: we DO emit them — the gap is identification, not emission

Well-posed here because both sides share one RT axis. Every number beside a decoy-coordinate
floor (same RT/IM, non-physical m/z offset), and a positive control that must be ~all-B:

| RT window | A never emitted | B emitted, not ID'd | A% | decoy floor for B |
|---|---|---|---|---|
| 0.2 min | 320 | 2,716 | **10.5%** | 16.0% |
| 0.5 min | 152 | 2,884 | 5.0% | 27.4% |
| 1.0 min | 74 | 2,962 | 2.4% | 37.3% |

**Positive control (SHARED, must be ~all B): 0.9% A / 99.1% B at 0.5 min — passes.** At the
tightest window **89.5% of missed peptides are class B** against a 16.0% coincidence floor.

So the "we never emit high-value peptides" hypothesis is ALSO falsified. We emit a spectrum at
~90% of the missed coordinates; we fail to *identify* it. Caveat: class B means an emission within
20 ppm / RT / IM of the coordinate, not proof that the spectrum is of that peptide — the decoy
floor bounds the coincidence, it does not identify the content.

**Synthesis.** We are not less accurate than diaTracer — our spectra identify at ~2× its
per-spectrum rate. We are less **sensitive**: at faint precursors we emit a spectrum that is too
thin (8.5% matched intensity, 9 matched peaks) to clear the identification threshold, while
spending emission budget re-deriving spectra for peptides already covered (11.3 identified spectra
per peptide vs 2.34). The lever is the low-abundance sensitivity floor — trace-detection
thresholds and how weak precursor hypotheses are admitted and assembled — NOT emission coverage,
NOT charge, NOT fragment count, NOT de-chimerization.

### #1 experiment, settled: de-chimerization is strongly harmful

`base` vs `assembly:rp_max=1`, one binary, one invocation (spock):

| | base | rp_max=1 | Δ |
|---|---|---|---|
| peptides | 10,124 | 4,819 | **−52.4%** |
| PSMs | 90,154 | 19,542 | −78.3% |
| emitted spectra | 1,528,083 | 1,427,890 | −6.6% |
| wall | 1,353 s | 3,270 s | 2.4× slower |

Spectra largely survive (−6.6%) but stop being identifiable (PSMs −78%). Cross-precursor fragment
sharing is **load-bearing**. Per the review's warning, the WRONG reading is "top-150 pollution is
absent"; the right one is that winner-take-all assignment strips real signal along with any
pollution. Lever closed.

Two bugs were caught by controls during this analysis and fixed before reporting: a native-id
parse that collapsed 700,434 diaTracer spectra into 1, and FAILURE 8 again — our mzML writes
`scan start time` in SECONDS (`unitName="second"`) while Sage reports minutes, so the first A/B
attempt compared seconds to minutes and the positive control read a physically impossible 100%
class A. `coverage.py` now reads the unit from the CV accessor and aborts if the RT ranges fail to
overlap.

## Harness fix landed in passing

`resolved_defaults()` parsed defaults from `--helphelp` "(default: '...')" text, which OpenMS 3.6
builds no longer emit — the parser silently returned `{}` and the FAILURE-5 no-op guard aborted every
run. Repointed at `-write_ini` (authoritative across versions; INI item paths minus the tool/instance
wrapper NODEs are exactly the CLI parameter names). Verified: 58 defaults parsed, correct values.
