# Backlog

Ideas not yet tested, with the reasoning that makes them worth testing and the result that
would kill them. Falsified ideas move to the relevant docs/ file rather than being deleted —
knowing what does not work is most of what this project has established.

---

## 1. Unmix fragment XICs onto the co-eluting MS1 precursor basis (NNLS)

**Status: CUT 2026-09-02.** The prerequisite failed under the correct measurement: `assembly:apportion`,
re-run with the emit weights actually applied, lost 3.9% of Sage peptides (11,742 vs 12,217 share-all;
docs/BASELINE.md:457-463, C7), and NNLS was cut on that result (CHANGELOG.md v0.3.0, "First clean
apportion run: -3.9% peptides (falsified again; NNLS cut)"; docs/BACKLOG-ANALYSIS-2026-09-02.md). The
reasoning below is kept as written; do not re-propose without a new prerequisite.

**The idea.** Today `scoreCandidates_` asks a *pairwise* question, one precursor at a time:
does fragment `f`'s elution profile correlate with precursor `p`'s? Every co-eluting precursor
asks independently, so under share-all a fragment is emitted into all of them at full intensity
(measured mean fan-out 6.45). Nothing ever asks the *joint* question.

The joint question is a regression. Let `P` be the matrix whose columns are the MS1 XICs of the
precursors co-eluting in this window, and `f` a fragment's XIC. Solve

    min || P w - f ||^2   subject to  w >= 0

The weights `w` are the fragment's intensity split across precursors, directly. Assign the
fragment to `argmax w`, or emit it into each precursor at `w_i` — an apportionment *derived from
the data* rather than a heuristic.

**Why this is better-posed than the decompositions already falsified.** Earlier analysis rejected
global SVD/NMF on this data because the rank is unknown and the matrix is not globally low-rank —
and rank selection *is* the answer you want, so assuming it is circular. That objection does not
apply here: **the number of components is not estimated, it is observed.** MS1 tells us which
precursors are present and gives their elution profiles. This turns an ill-posed blind
decomposition into a well-posed non-negative regression with a known design matrix. That is the
whole difference, and it is why this deserves a test where blind NMF did not.

**Relation to what exists.** `assembly:apportion` already splits intensity by `corr^p / sum(corr^p)`.
That is a crude, coordinate-wise stand-in for the same intent — it never solves a joint fit, so two
precursors with similar profiles both get high weight instead of competing. NNLS is the principled
version and subsumes it. `assembly:apportion` was measured first, on 2026-09-02, with the emit weights
actually applied (every earlier apportion A/B had bypassed them): it lost 3.9% of Sage peptides
(docs/BASELINE.md:457-463, C7). The heuristic captured no gain, so NNLS was cut on its prerequisite.

**Why it should help, in terms of measured defects.**
- Redundancy: we lose 14-16% of peptides at peptide-level FDR against the reference implementation's 5-7%, because we
  emit ~4.6 PSMs/peptide. Fragments landing in one precursor instead of six attacks that directly.
- Purity: only 5.79% (decoy-corrected, equal depth) of an emitted spectrum's intensity belongs to
  its own precursor; co-isolation contributes +7.50%.

**How to test.** The DIA-NN truth set already provides ground-truth fragment ownership: the
predicted library gives 405,336 true (precursor, fragment) pairs, and negatives are fragments of
other co-eluting precursors in the same window. So this is directly measurable *without* a search
engine — compute assignment precision/recall against that set for pairwise-Pearson vs `apportion`
vs NNLS, before running Sage at all.

**What would falsify it.**
- Assignment precision against the DIA-NN pairs does not beat the pairwise baseline. Then the
  limiting factor is the MS1 profiles themselves, not how they are combined.
- Precursor XICs in a window are too collinear to separate. **Measure this first** — it is cheap
  and decisive. Compute the condition number / pairwise correlation of `P` per window. Peptides
  co-eluting within a couple of seconds have near-identical profiles, and no solver recovers a
  split the data does not contain. If typical `P` is severely ill-conditioned, NNLS produces
  confident, arbitrary, wrong splits — worse than the current honest ambiguity.
- Peptides at `peptide_q` do not improve even if assignment precision does.

**Note on the ill-conditioning risk.** This is the real hazard, not compute cost. A regression that
silently picks one of many equally good answers is more dangerous than a heuristic that spreads the
intensity, because downstream it looks decisive. Regularisation (ridge, or an IM-similarity prior)
or an explicit ambiguity flag would be needed — and an ambiguity flag is arguably the more honest
output for a blind-search tool.

**Cost.** Windows hold ~50 co-eluting DIA-NN precursors and millions of fragment traces, so this is
a small dense NNLS (~50 unknowns, grid-length equations) per fragment. Warm-startable and trivially
parallel across fragments, but it sits in the inner loop, so runtime must be measured too.

**Prerequisite ordering.** Measure `assembly:apportion` -> measure conditioning of `P` -> only then
implement NNLS. The chain stopped at the first step (2026-09-02); the conditioning of `P` was never
measured and NNLS was never implemented.

---

## N. Decompose the whole cycle jointly, using our own redundancy as the data

**Status: KILLED 2026-07-28.** The third kill condition fired: within-cycle duplicates carry
information. The `consolidate:delta_rt` sweep lost peptides at every setting (0.7 -> -12.7%,
3.0 -> -24.0%; docs/BASELINE.md:139-142, on the do-not-re-propose list), and the named prerequisite,
item 1, was cut on 2026-09-02 (docs/BASELINE.md:461). What the duplicates actually are is worked out
in docs/ISOTOPE-DUPLICATION-2026-09-03.md.

**Origin.** User proposal, 2026-07-22: *"use the large number of spectra to cluster the peaks in
the cycle (e.g. SVD/NNLS) to decompose everything"* — framed as **data cleanup**.

**The hook that makes this different from the blind decomposition already rejected.** Today's
cycle analysis ([benchmarks/cycle-redundancy.md](benchmarks/cycle-redundancy.md)) measured
within-cycle multiplicity of **2.85** — we emit ~3 pseudo-spectra per (peptide, cycle), where
the reference implementation emits 1.25. Those have been treated purely as a defect. But they are also **~3
independent noisy views of the same underlying cycle content**, and that is exactly the regime
where joint decomposition has something to work with. The redundancy stops being only a bug and
becomes the input.

Concretely: within one isolation window × one cycle, build `X` = (emitted spectra × fragment
m/z bins). We have many rows *because* of the over-emission. Factor `X ≈ W H` with `H` ≥ 0 the
component spectra and `W` ≥ 0 the per-emission weights. Components that recur across the
redundant emissions are real; components appearing in one emission only are extraction noise.
Output one consolidated spectrum per component — which is precisely the cleanup asked for, and
would attack the ~56% of within-cycle duplicates that `consolidate:delta_rt` addresses only by
nearest-neighbour merging.

**What the 2026-07-22 review established against blind decomposition, which still applies:**

* **Kruskal uniqueness needs component profiles to differ in at least one mode.** Co-eluting
  precursors inside one isolation window are exactly where profiles are collinear — PARAFAC is
  least identifiable precisely where we need it most.
* **Ion mobility is a partition, not a profile.** TIMS precedes fragmentation, so the mobility
  mode is a *label*, not a continuous third mode. The trilinearity argument for PARAFAC — the
  main reason it looked attractive — does not hold.
* **The quadrupole mask makes missingness structured**, not random: m/z visibility depends on IM
  and cycle position.
* Overall probability of success judged **<5%**.

**Why this variant partly escapes those.** It is not blind and not trilinear. It is a 2-D
non-negative factorisation over (emission × fragment) *within* one cycle-window cell, where the
row count is empirically large and the rank question is bounded by something observable — DIA-NN
reports ~50 co-isolated precursors per spectrum, and MS1 supplies candidate precursors for that
cell. It is closer to codex's recommendation of **anchored / coupled factorisation using
MS1-derived profiles as partial known factors** than to blind PARAFAC. It also overlaps
substantially with backlog item 1 (NNLS onto the MS1 basis) — **item 1 was to be tried first**,
since it needs no rank estimate at all; item 1 has since been cut (2026-09-02).

**Cheap falsification, before any implementation.** Take the ~31,621 duplicated (peptide, cycle)
groups already identified. For the ~56% whose members agree to ~15 ppm, ask offline: does a rank-1
non-negative fit reconstruct the members within noise? If yes, they are redundant views and joint
decomposition is justified. If the members need rank ≥ 2 to reconstruct, they carry distinct
information and merging them — by NMF *or* by `consolidate` — destroys signal. **That test is a
few hours on existing output and needs no new extraction run.**

**What would kill it — and did.** Rank-1 reconstruction fails on the tight-m/z duplicates; or item 1
(NNLS) already captures the gain, making the extra machinery unjustified; or the peptide count falls
in the `consolidate:delta_rt` sweep. The sweep finished with 0.7 -> -12.7% and 3.0 -> -24.0%
(docs/BASELINE.md:142), which showed that within-cycle duplicates carry information after all; the
item was killed on that result (2026-07-28). Item 1 was later cut as well.

---

## N+1. Learned monoisotope/charge predictor from MS1 + fragment features

**Status 2026-09-08: premise rewritten; one head still open.** Every charge number in this item
belonged to the retired `envelope` algorithm, and the (m/z, IM) prior it proposed to learn now ships
as physics (`charge:im_charge_veto`). The open head is the learned monoisotope offset for open
search; the charge head cannot be sized until its baselines are re-measured on the shipped
`count` + veto arm.

**Origin.** User proposal, 2026-07-22: *"correlate with MS1 precursor masses, perhaps in an ML
based predictor including these features."*

**Why this looked well-posed on 2026-07-22, and what has changed since.** Three things changed that
day; two of them have since been overtaken:

1. **The target was quantified — for the wrong arm.** Charge agreement of **74.6%** against a
   majority-class baseline of **69.6%** was measured on the retired `envelope` algorithm, whose
   tie-break is the opposite of the shipped one; the shipped arm's confusion cells have never been
   measured (docs/charge-inference.md:12-16). The headroom on the shipped `count` + veto arm is
   unknown until it is re-measured.
2. **Ion mobility is back in play — and now ships as physics, not as a learned prior.** The IM
   lever was retired on a statistics error: a *share-a-label* rate was compared against `max p_z`
   (69.6%) instead of `sum p_z^2` (55.8%). Corrected, (m/z, IM) carries **+19.2 points** of charge
   information over chance, not +5.4. See [charge-inference.md](charge-inference.md). A *monotonic*
   IM prior still fails — z=4 lies between z=2 and z=3 — but a 2-D prior does not. Since the
   `charge:min_charge` 2 -> 1 change, `charge:im_charge_veto` fits per-run 2+/3+ mobility lines from
   the run's own confident calls and re-calls a z=1 lying on the 2+ line, or drops one on the 3+
   band (CHANGELOG.md v2.0.0, "`charge:min_charge` default 2 -> 1"; src/spextractor.cpp:1830,
   3548-3568). What a learned 2-D prior would add on top of the veto is unmeasured.
3. **The failure mode is localised.** ~44% of within-cycle duplicates are separated by ~1000 ppm
   ≈ one isotope spacing: the same peptide assigned to different monoisotopes. That is the thing
   to predict.

**Labels exist.** DIA-NN references give true charge and monoisotope for ~43,499 precursors on
dataset A, plus dataset B and dataset D — ~130k labelled precursors. Small for a transformer (DIA-BERT needed
276M) but ample for the model class the review actually recommends.

**Model class, per the 2026-07-22 review.** AlphaDIA — state of the art in this exact data type —
scores with **46 hand-crafted features into a 10,810-parameter MLP**, *not* a transformer. Verdict
there: transformer ~8% probability of beating the hand-crafted path; the small model is the
recommendation. Start with gradient-boosted trees or an MLP of that size.

**Feature set (all already computed or cheaply derivable):**

| group | features |
|---|---|
| MS1 isotope | intensity ratios M/M+1/M+2, observed-vs-averagine cosine, spacing residual in ppm, number of partners found |
| MS1–MS2 coupling | correlation of fragment XICs to the precursor XIC, fraction of fragments correlating, apex RT offset |
| mobility | 1/K0, deviation from the (m/z, IM) charge-2 line, and the tile's `ScanNumBegin/End` band — a hard transmission constraint the code currently discards |
| position | m/z, RT, precursor intensity, local co-isolation density |
| redundancy | within-cycle multiplicity for this precursor (measured 2.85 mean) |

**Target.** Correct charge, and correct monoisotope offset (−1 / 0 / +1 / +2), as two heads or
one joint class.

**Falsification, pre-registered.** The model must beat **both** baselines:
* the majority-class constant, and
* the shipped `count` + `im_charge_veto` heuristic,
by more than the 0.17% replicate spread, on a **held-out sample** — train on dataset A+dataset D, test on
dataset B. Training and testing on one sample would measure memorisation, and this project's
characteristic failure is exactly a metric that cannot tell the two apart. The 69.6% / 74.6%
figures written here on 2026-07-22 are `envelope`-arm numbers and cannot serve as these baselines;
both must be re-measured on the shipped arm first (docs/charge-inference.md:12-16).

**What would kill it.** Held-out charge accuracy does not beat the re-measured shipped-arm figure;
or it does, but the peptide count does not move — which would mean charge was never the binding
constraint and the real limit is elsewhere.

**Do first — answered 2026-07-28/29.** The `isotope_errors [0,0]` experiment measured how much the
*search engine* was already repairing our monoisotope errors: closed search hides the error
entirely (Sage enumerates `isotope_errors [-1,2]` and corrects it for free, docs/BASELINE.md:181),
and in open search the -1 Da artefact is a PTM-interpretation problem, not a recall lever — a
-1-shifted precursor is still identified, mislabelled with a phantom modification
(docs/BASELINE.md:222-229). So a predictor buys nothing for closed search; its value is confined to
the monoisotope head in open search, where a phantom -1.003 Da modification is a correctness defect
for blind-PTM work. That is the stated purpose, but it changes the cost/benefit.

## N+2. Adjudicate charge head-to-head on co-identified spectra: who is actually right?

**Status: resolved in part, 2026-09-08.** docs/REFERENCE-COMPARISON-2026-09-08.md, "What the
charge-1 spectra are (resolved)", did most of what this item asked without the enumerated search:
our z=1 calls were compared against the reference's own 1+ identifications (identical +0.28-0.30
1/K0 offset above the 2+ line); the charge-unset discriminating experiment was run (only 319 of
5,947 come back, all at 2+); the trap below was confirmed (both engines honour the declared charge);
and the question the item was written to decide — whether the MSFragger deficit is recoverable by
fixing the call — is answered: emitting z=1 with the mobility veto took it from 0.882 to 0.97 pooled
/ 1.00 per-charge on 009 and from 0.852 to 0.97 / 0.98 on 001 (same doc, "Decision";
docs/BASELINE.md:1895, 1935-1937). **What remains** is the enumerated-charge adjudication as
designed — `override_charge = 1, z = 1..5` on both tools' outputs at q <= 0.001, and the joint
(ours, theirs) table on PXD017703 — of which no run is recorded after
docs/BENCHMARK-MATRIX-2026-09-01.md:120-121.

**The question.** For every spectrum the reference tool has confidently identified, find our
spectrum for the same precursor and compare the two charge calls. Where they disagree, decide from
the spectra themselves which call is correct — rather than assuming either tool is the oracle.

**Why this beats what we have.** Every charge number on record is scored against a DIA-NN report,
and that reference has three problems established on 2026-09-05: it is stale (it predates
`require_isotope_support=true`, the apex estimator, the integer detector, `perf:stream_load` and both
moves of `charge:min_charge` — to 2, and back to 1 with the mobility veto (CHANGELOG.md v2.0.0;
src/spextractor.cpp:1810) — so the measured population is disjoint from the shipped one); it is
structurally blind (tryptic, <=2 mods, z2-4 — exactly the space this tool exists to look outside);
and the confusion table it produced belongs to a retired algorithm whose tie-break is the opposite
of the shipped one. This experiment replaces a library-shaped oracle with **identification as
truth**, on the population that actually matters — spectra good enough to be identified.

**THE TRAP THAT WOULD SILENTLY INVALIDATE IT.** Both engines *trust the charge we declare*:
`msfragger.params` has `override_charge = 0`, and Sage's `precursor_charge: [2,4]` is the
enumeration range for spectra with NO declared charge — a declared one is used as given (verify
this against the Sage version in use before relying on it). So a confident PSM does **not**
independently confirm a charge: it confirms that the declared charge produced a match. Scoring
agreement this way would just echo our own annotation back at us.

The experiment is therefore only meaningful if the adjudicating search **re-derives** charge:
run both tools' outputs with `override_charge = 1, z = 1..5` (MSFragger) and the equivalent
Sage configuration, so the winning charge is chosen by spectral evidence. That arm already exists
for MSFragger — `docs/BENCHMARK-MATRIX-2026-09-01.md:120-121`, where it moved SpeXtractor +4.5%.

**Design.**
1. Extract the same acquisition with both tools. Use the public HeLa benchmark (PXD017703) so the
   result is reproducible outside the group.
2. Search both outputs with charge **enumerated**, not trusted, at a strict threshold (q <= 0.001,
   not the usual 0.01 — this is an adjudication, not a yield measurement).
3. Pair spectra by precursor **coordinates**, never by neutral mass: if the charge calls differ the
   masses differ by construction, so mass-matching would drop exactly the disagreements the
   experiment is about. Match on (mono m/z within ~10 ppm, RT within ~10 s, 1/K0 within ~0.02).
4. Allow, and separately count, a **+-1.00335/z isotope offset** in the m/z match. Our monoisotope
   call is a known artefact class; if it is not admitted the pairing silently loses those cases,
   and if it is not counted separately the two defect classes get conflated.
5. Tabulate the joint distribution (ours, theirs) — not just an agreement rate.

**Adjudication, where the two disagree.** Rank the evidence, and report each line separately:
* the re-derived charge from the engine, on each tool's own spectrum, at q <= 0.001;
* whether the identified peptide is tryptic and its mass consistent with the precursor at each
  candidate charge (a wrong z gives a mass off by (z'-z)(m/z - 1.00728), which for real peptides is
  usually not a peptide mass at all);
* fragment-side consistency — a z=2 precursor cannot carry a fragment heavier than itself;
* the MS1 isotope envelope spacing at the precursor coordinate, read from the raw data rather than
  from either tool's summary, which is the only fully independent arbiter.

**What would make it inconclusive**, and must be reported if it happens: if the great majority of
pairs agree, the disagreement set may be too small to characterise; if the disagreements
concentrate in spectra that neither tool identifies at q <= 0.001, then charge is not the thing
limiting identification and the result argues for **deprioritising** this line entirely. Both are
useful answers.

**Cost.** Two extractions plus four searches on one acquisition, roughly half a day, plus the
pairing script. No new tooling beyond the pairing; the enumerated-charge search arm already exists.

**What it decides.** Whether our charge calls are worse, equal or merely *different*, and the true
direction of the error on the shipped algorithm (still unmeasured — see the note at the head of
`docs/charge-inference.md`). The third question it was written for — whether the ~10% of the
MSFragger deficit attributed to charge labels is recoverable by fixing the call, or only by not
declaring one — was answered on 2026-09-08 without it: the deficit was the z=1 class itself, and
emitting it with the veto closed the gap to 0.97 pooled / 0.98-1.00 per-charge (see the status line
above).

## From the public HeLa table (2026-09-05, docs/HELA-TABLE.md)

- **Low-load A/B on public data.** *Status 2026-09-08: half moot, nothing re-measured.* At 10 ng
  SpeXtractor loses on both engines and both 2019 schemes (py3: Sage 4.8k vs 9.2k). The
  isotope-support gate and the z>=2 floor were adopted at 200 ng in-house; the floor is since gone
  (`charge:min_charge` default is 1 with the mobility veto, CHANGELOG.md v2.0.0;
  src/spextractor.cpp:1810), and nothing at 10 ng has been re-measured (no 10 ng / HeLa / PXD017703
  entry in docs/BASELINE.md after line 1196). Do: (1) re-measure `assembly:require_isotope_support`
  on the six 10 ng files at the v38 default (1.5-5 min per extraction, both engines already wired);
  (2) measure the v38 default (z=1 + veto) on the 10 ng files and on one 100 ng HeLa file as the
  control — the whole of docs/HELA-TABLE.md was measured at `min_charge` 2, and the z=1 gain
  (+14-20% Sage on TNBC) has never been checked on a HeLa file. Both-engines + entrapment gate
  applies before any default moves.
- **MSFragger content gap on py3.** *Status 2026-09-08: measured at `min_charge` 2; re-measure
  first.* MSFragger got 1.9x more peptides from the reference's py3 spectra than from ours while
  Sage was at 0.85 (docs/HELA-TABLE.md, py3 MSFragger ratio 0.54). On TNBC the MSFragger deficit
  closed from 0.85-0.88 to 0.97 pooled / 0.98-1.00 per-charge once z=1 was emitted
  (docs/REFERENCE-COMPARISON-2026-09-08.md, "Decision"; docs/BASELINE.md:1895, 1935-1937), and
  21.1% of the only-reference MSFragger peptides were z=1 (same doc, "Where the MSFragger deficit
  comes from"). Re-measure the py3 gap at v38 before any content work; the HeLa table predates the
  z=1 change and no HeLa re-run is recorded. If a gap remains: same content-candidate machinery as
  before (matched fragment ions per co-identified precursor), now on public data where the gap is
  widest.

## Operational notes moved

The "Cluster launch discipline (2026-09-07)" section — `bench/launch.sh`, `verify_publish.sh` and the
ssh-channel / `exit 255` findings — is finished procedure rather than an untested idea and now lives
in [bench/README.md](../bench/README.md) under the same heading.

## Routes (2026-09-08)

docs/BASELINE.md refers to "the routes list"; this is it.

### Per-charge FDR as the shipped readout

**The idea.** Report every peptide count under a per-charge 1% walk and make the harness default
per-charge, keeping the pooled cut as a secondary column.

**Why.** With `charge:min_charge=1` the z=1 stratum runs 2.9% entrapment under the engines' pooled 1%
cut (009 2.94%, 001 2.91%) while the whole-run figure reads 0.93-1.03%; under a per-charge walk z=1
sits at 0.87-0.91% and the gain survives (009 Sage 27,831 vs 24,484 for the v35 arm; 001 19,262 vs
16,029) — docs/BASELINE.md:1896-1900 (v38 on TNBC 001), 1919-1922 (v38 on TNBC 009);
docs/REFERENCE-COMPARISON-2026-09-08.md, "The z=1 stratum runs ~2.8% entrapment FDR at a nominal 1%
cut". The reference tool's own 1+ stratum shows the same (decoy FDR 1.4% on 009, 7.6% on 001, same
section), so it is an engine-calibration property, and a pooled cut penalises whichever tool emits
more 1+.

**What would falsify it.** A per-charge walk that pushes a z>=2 stratum above 1% entrapment on either
file (001 z=2 already reads 1.14% per-charge, docs/BASELINE.md:1900), or a per-length stratification
that controls z=1 better than per-charge — then the readout should be per-length.

### The MSFragger residual: 0.97 pooled, 0.98-1.00 per-charge

**The idea.** The content-gap line was scoped when the ratio was 0.85-0.88; emitting z=1 took it to
0.968/0.972 pooled and 1.00/0.98 per-charge on 009/001 (docs/REFERENCE-COMPARISON-2026-09-08.md,
"Decision"; docs/BASELINE.md:1895, 1935-1937). Re-characterise the only-reference MSFragger set at
v38 (T4) before any content work: is what remains still the faint-tail content class (median
hyperscore ~18; docs/BASELINE.md:597-615, content candidate 2) or churn at the acceptance boundary?

**Why.** The 6,749-peptide characterisation (docs/REFERENCE-COMPARISON-2026-09-08.md, "Where the
MSFragger deficit comes from") is v35 and its 21.1% z=1 component is gone; the raw-apex backfill that
lifted MSFragger to 90% was falsified on its 2.6% Sage cost (docs/BASELINE.md:660-676, 756-780), and
that trade may now differ.

**What would falsify it.** A v38 only-reference set under ~2% of the common set with its median
hyperscore at the boundary — then there is no content gap left and the item closes.

### `require_isotope_support` and genuine 1+ singletons

**The idea — a hypothesis to measure, not a recorded observation.** A 1+ hypothesis whose M+1 was not
traced becomes a `guessed` precursor, and `assembly:require_isotope_support=true` erases it
(docs/charge-inference.md:37-40; CHANGELOG.md v0.3.0, "`assembly:require_isotope_support` and
`perf:stream_load` now default to TRUE"; src/spextractor.cpp:3562). Whether the gate drops genuine 1+
singletons is not established anywhere in the repository — the only in-repo link between the two is
src/spextractor.cpp:3562, which uses the gate to *drop* 3+-band z=1 calls. Count, on 009 and 001, how
many of the reference tool's 1+ identifications we emit only as `guessed`.

**Why.** The gate was adopted at `min_charge` 2 on dataset D (6.9x slower and worse with it off,
same CHANGELOG entry) and has never been re-measured with z=1 emission on; on the 10 ng public file
it dropped 2.09 M guessed precursors and kept 466 k (docs/BASELINE.md:1171-1174), and z=1 IDs are
7-9-mers around 920 Da (docs/REFERENCE-COMPARISON-2026-09-08.md, "The identifications are genuine
singly charged peptides") whose M+1 is the faint-tail case.

**What would falsify it.** Fewer than ~1% of the reference tool's 1+ identifications in our guessed
z=1 population, or a z=1-only relaxation of the gate that adds no peptides while moving the z=1
stratum above 1% per-charge entrapment.

### MS1 through the integer detector (plan step 13), then tof-keyed precursor inference

**The idea.** `trace:ms1_detector = openms | integer`: MS1 compact frames in tof mode -> PeakSlab ->
`detectTracesInteger_` + `splitIntegerTraces` with the MS1 parameters, gated (gate C) against the
OpenMS MS1 path; then key `findPartner` on the flight-time bin instead of the IEEE-754 m/z stand-in.

**Why.** MS1 tracing is the last OpenMS-detector path; `Trace::tof` is 0 there, so the natural integer
key is unavailable (CHANGELOG.md v2.0.0, "`Trace::tof` is 0 on the OpenMS MS1 path";
docs/BASELINE.md:1593-1597), and the MS1 PeakMap (13.8 GB on dataset D at 20 B/peak, 44.5 GiB on TNBC) plus
its 48 band sub-maps is the largest structure outside the window loop (docs/TNBC-PROFILE.md:102,
131-132; docs/BASELINE.md:1512-1513). No `ms1_detector` option exists yet (grep src/spextractor.cpp).

**What would falsify it.** Gate C showing >= 1% peptide loss in either engine, or the engines
contradicting each other — the MS2 integer detector agrees with OpenMS on only ~85% of the union
(CHANGELOG.md v0.3.0, "`trace:detector` now defaults to `integer`"), so equal churn on MS1 would make
it a memory-only trade.

### Band-independent tracing: make `perf:trace_bands` a free speed knob

**The idea.** Each MS2 band carries its own `visited` bitset over the whole window
(src/spextractor.cpp:1074; comment at 4046), so a trace grown by one band consumes peaks in another
band's core, and ownership at band edges depends on the band count. Make ownership band-independent
(a shared claim set with deterministic order, or the halo + core-ownership scheme the MS1 path uses,
docs/BASELINE.md:1673-1675) so that every band count yields the same spectrum list.

**Why.** 24 and 48 bands are -30% window-loop wall at 7% lower CPU, but they move 4-10% of the
peptide set with the engines disagreeing in sign on dataset A (Sage -1.6/-1.7%, MSFragger +2.2%; overlap
95.5%/89.7%) and were rejected twice (docs/BASELINE.md:1520-1536, 1639-1658); the loop is 60-64% of
the run, and 94% of its critical window is the band taskloop (docs/BASELINE.md:1633-1636, 1712-1714).

**What would falsify it.** A band-independent partition whose 12-band output is not byte-identical
(then it is a gated G change), or one that is exact but whose 48-band wall is no better than 12
because the churn was where the speed came from.

### Ordered speculation inside the band trace detector: recorded, not open now

**The idea.** The ordered-speculation scheme that made precursor inference 23x exact-parallel
(docs/BASELINE.md:1599-1620), applied to the greedy claim loop of `detectTracesInteger_`. Implemented
(commits 913bd91..0337663), measured, removed (438ef84): a fixed width of 8 cost +31% window-loop CPU
and +11% wall; adaptive width on live occupancy removed the penalty but barely engaged, because the
window whose detect is the critical path is the last one and sees idle threads only in its final
~20% (docs/BASELINE.md:1716-1738).

**Why keep it.** It becomes worthwhile the moment the loop stops being tail-bound — after
band-independent tracing, or a cap that leaves threads idle.

**What would falsify it.** An interleaved dataset D A/B, with the loop no longer tail-bound, where the
control spread (133.0 vs 121.7 s) still exceeds the effect.

### The peak picker is sensitive to how frames are grouped across threads

**The idea.** `SPEXTRACTOR_PICK_BATCH` 256 -> 4096 is -39% LOAD wall but changes the digest and costs
7.2% Sage / 6.1% MSFragger peptides on dataset D (overlap 91.7% / 81.3%), and `perf:stream_load=false` —
another frame grouping — also changes the output (docs/BASELINE.md:1762-1790; CHANGELOG.md v2.0.0
Measured, "`SPEXTRACTOR_PICK_BATCH` is fast and rejected" and "`perf:stream_load` is a
sensitivity/resource trade"). A picker whose output depends on which thread saw which frames carries
per-thread state it should not; find it in the pick consumer (`PickCompactConsumer`/`FrameCentroider`,
src/spextractor.cpp:3169; CHANGELOG.md v0.3.0 Runtime, "MS1 path parallelised") and make the pick
frame-local.

**Why.** A correctness smell in the first stage, and it blocks a free 1.6x on LOAD (13.7% of a 2-h run).

**What would falsify it.** A frame-local picker that is byte-identical across batch sizes but loses
peptides against today's 256 — then the state is a real cross-frame feature, and the item becomes a
documented parameter, not a bug.

### The 2+/3+ tie-breaker for the mobility veto

**The idea.** The fitted 2+ and 3+ lines are ~1 sigma apart at low m/z (at m/z 500: 0.867 vs 0.822
1/K0 against a 3+ sigma of 0.051), so v38 drops a z=1 on the 3+ band instead of re-labelling it
(src/spextractor.cpp:3556-3563). The principled arbiter is the intermediate-isotope test — a
co-eluting trace at +ISO/2 says 2+, at +ISO/3 says 3+ — which the `SPEXTRACTOR_Z1_DIAG` machinery
already computes (docs/BASELINE.md:1839-1841); it is not yet wired in.

**Why.** ~1.8% of z=1 calls are genuinely 3+ and are now discarded; recovering them is the only
upside left in the veto.

**What would falsify it.** z=3 peptides not moving on 009 or dataset D with the tie-breaker on — re-calling
178k/93k spectra to 3+ already identified nothing (5,313 -> 5,322 on 009, 3,888 -> 3,935 on dataset D;
src/spextractor.cpp:3557-3559, docs/BASELINE.md:1835-1836) — meaning dropping is final.

### The 009 Sage protein count under z=1

**The idea.** Emitting z=1 on the v35 binary moved 009 protein groups 5,802 -> 5,641 (-2.8%) while 001
rose 4,074 -> 4,118 (docs/REFERENCE-COMPARISON-2026-09-08.md, "Where the MSFragger deficit comes
from", which named it as one of two things to resolve before changing the default). The default
changed; at v38 the 001 figure is 4,142 (docs/BASELINE.md:1894) and no 009 protein count is recorded
(docs/BASELINE.md:1906-1938, "v38 on TNBC 009", has none). Measure it under both walks and, if the
drop persists, list the protein groups that lose their last peptide.

**Why.** The candidate mechanism is the z=1 stratum's lower prior under the pooled cut (63% of z=1
spectra produce no rank-1 row; docs/REFERENCE-COMPARISON-2026-09-08.md, "The z=1 stratum runs ~2.8%
entrapment FDR at a nominal 1% cut"), which a per-charge walk should undo.

**What would falsify it.** A v38 009 protein count at or above 5,802 under either walk.

### Overlap the loader's decode with its peak picking

**The idea.** LOAD is now the second-largest phase (93.5 s of a 677 s run, 14%, after tonight's
work) and it runs at 56x on 100 threads: 5,266 CPU seconds against a 53 s floor, so **~40 s is lost
to something other than work**. The structure is two parallel stages that ALTERNATE rather than
overlap: the reader decodes a batch of frames (`BrukerTimsFile.cpp`, frame-major
`#pragma omp parallel for schedule(dynamic, 1)`), hands the spectra to the consumer one at a time,
and when the 256-frame buffer fills, `PickCompactConsumer::flush_()` picks and compacts it in a
second parallel region. Measured: picking is 45.7 s of the 93.5 s. Both stages are already
internally parallel, so the loss is not a serial stage -- it is the barrier and ramp at every batch
boundary, plus the serial hand-off between them, repeated across thousands of frames.

Note what this rules out: simply "parallelising the decode" is not the answer, because it already
is. The candidates are (a) software-pipelining the two stages so batch N's pick overlaps batch N+1's
decode, filling each other's ramps, and (b) reducing the number of boundaries -- which the batch
size controls, and that is frozen (below).

**Why it should be output-identical.** The frame grouping is what the picker is sensitive to, and
double-buffering does not change it: batch i is still frames [256i, 256i+256), picked by the same
code with the same per-thread scheduling. Only *when* the pick runs changes. That distinction
matters here because the batch size itself is frozen -- `SPEXTRACTOR_PICK_BATCH` 256 -> 4096 is
-39% on the load phase but changes the digest and loses 7.2% of Sage peptides, so the picker carries
per-thread state across frames and the grouping is load-bearing.

**What would falsify it.** Both stages already saturate the cores while they run, so overlapping
them only fills ramps -- if instrumenting decode wall and CPU separately shows each stage near 100x
inside its own region, the recoverable 40 s is mostly barrier cost and pipelining buys a fraction of
it, not the lot. Or the reader cannot release a buffer without stalling (it owns the frames it hands
over), making the hand-off a copy that costs what the overlap saves. Measure the two stages
separately before building anything.

### `perf:ms1_trace_bands` 96: faster, and output-changing

Measured 2026-09-08 on dataset D: 48 -> 96 bands takes MS1 band detection from 7.04 s to 3.96 s
(-44%) and the whole MS1 phase from 15.1 s to 11.4 s (-25%), because detection is capped at
band-count parallelism and 48 bands cannot fill 100 threads. **It changes the spectrum list**
(4,905,492 -> 4,905,486 traces; digest differs), so it is not a free knob: band edges move trace
ownership, exactly as `perf:trace_bands` does. On the 2-hour file the phase is 52.9 s, so the prize
is ~13 s (~2% of the run) against a full two-engine, two-dataset, entrapment-controlled gate -- and
the record already shows the 12 -> 48 move shifted MSFragger by 2% on one dataset. Not worth it at
that price, but worth knowing the knob is there if MS1 tracing ever becomes the critical path.

### Parallel mzML serialisation: the win is real, OpenMS's writer is not thread-safe

**The idea.** WRITE is the largest serial block left: 92.9 s of an 822 s run on a 2-hour
acquisition (10.7%), 20 s of 197 s on a 30-minute one, all at 1.0x parallelism. It is CPU-bound,
not I/O-bound -- measured, the write sustains ~390 MB/s while the filesystem underneath it does
**4.0 GB/s**, a 10x headroom. Serialising a spectrum is independent of every other spectrum; only
the concatenation is ordered. Encoding in parallel into per-chunk buffers appended in index order
is byte-identical by construction, and should take the phase to roughly the I/O floor (~10-15 s).

**Attempted 2026-09-08, and why it was reverted.** The patch (parallel encode in waves, bounded
buffering, ordered append, `copyfmt` so the number formatting matches) is correct in shape: it
passed the end-to-end suite and produced the file. On a real acquisition it aborts with
`double free or corruption`. `MzMLHandler::writeSpectrum_` is const and takes its inputs by const
reference, but the path underneath it mutates shared state in at least two places:
`MzMLHandler::cached_terms_` (a `mutable std::map` memoising CV-term validation, written in
`validateCV_`), and the `SemanticValidator` the writer holds. Freezing `cached_terms_` -- warming
it serially on the first spectrum, then only reading it -- removed one race and the corruption
persisted, so the validator has its own.

**Where the corruption actually is (backtrace, 2026-09-08).** Under gdb the abort lands in
`MzMLHandler::writePrecursor_`, in `operator new` taking the malloc arena lock -- i.e. that frame is
where a corrupted heap was *detected*, not where it was corrupted. Ruling out by inspection since:
`writePrecursor_` only reads `options_`; `SemanticValidator::locateTerm` is `const` and reads
`rules_` and the CV; and freezing `cached_terms_` (warm serially, then read-only) did not stop it.
So a fourth writer is still unaccounted for. Note that `writePrecursor_`, `writeSoftware_`,
`writeSourceFile_` and `writeDataProcessing_` are all NON-const members, unlike `writeSpectrum_` and
`writeUserParam_` -- that asymmetry is the place to look next, together with the
`ControlledVocabulary` singleton's lookup paths (`checkAndGetTermByName`, `iterateAllChildren`),
which are the remaining shared objects on the path.

**What would actually work.** Give each encoding thread its own `MzMLHandler` and its own
validator, so nothing is shared: the per-thread construction cost is paid once per wave, not per
spectrum. That is a larger change inside OpenMS than it first appears, and it needs its own
correctness argument (the handlers must be configured identically, or the output differs).
Alternatively, precompute only the base64 blobs in parallel -- `Base64::encode` is a pure static
function -- and have the serial writer consume them; that captures the array encoding but not the
per-spectrum XML and cvParam work, and the split between those two is unmeasured.

**What would falsify it.** A measurement showing the per-spectrum XML and metadata work, rather
than base64 of the arrays, is most of the 23.7 us/spectrum -- then a per-thread handler is the only
route and the base64 shortcut is not worth building. Also: on the default output format (mzPeak,
which is Parquet) this phase is a different code path entirely and the whole item may not apply.

### Can DWT/CWT smoothing improve QUALITY without costing too much runtime?
*(was: "Is Savitzky-Golay the right smoother for elution-peak detection?" -- the runtime half
of that question is now closed by measurement; see below. Only quality is open.)*

**The idea.** `ElutionPeakDetection::smoothData()` smooths every mass trace with a Savitzky-Golay
filter (polynomial order 2, frame length = max(3, win_size)) before the local-minimum search that
splits a trace at chromatographic valleys. SG is one choice among several. A discrete wavelet
smoother -- a stationary (a-trous) B3-spline transform, or a Haar/Daubechies DWT with level-wise
thresholding -- is the obvious alternative, and the question is open on all three axes: runtime,
memory and peptide quality.

**Why it is worth asking now.** Caching the SG coefficients (2026-09-08) removed the coefficient
construction, which was the dominant cost -- MS1 tracing CPU fell 44% and the window loop 10%. What
remains is the filter *application*: O(n x frame_length) multiply-adds per trace, plus an MSSpectrum
copy of the trace points on every call. A stationary wavelet transform is O(n x levels) with levels
~ log2(frame_length), so for LONG frames it would be asymptotically cheaper; a Haar DWT is O(n).
Whether that matters depends on the frame-length distribution -- **now measured, and it kills the
runtime argument in the opposite direction: the frames are short, so a DWT is MORE work, not less.**

Quality is the more interesting half. SG preserves peak height and width by construction (that is
its whole point, and OpenMS's own comment says it fits better than the lowess alternative it
replaced), but it is a fixed-width linear filter: one frame length is applied to traces whose widths
vary across the gradient. A wavelet smoother is multi-scale by construction, so it can denoise a
narrow early-eluting peak and a broad late one with the same parameters. The valley search that
consumes the smoothed intensities is what decides how traces split, and splitting decides precursor
and fragment boundaries -- so this is upstream of everything.

**Note on the previous wavelet result, which does NOT settle this.** `trace:wavelet_smooth` (an
a-trous B3-spline, removed 2026-09-08 as falsified) smoothed the *precursor XIC before correlating
fragments against it* -- a different signal at a different stage, and it benchmarked flat (-0.03%).
Its own mechanism note explains why: at 2.6 samples per FWHM the requested scale was below the first
meaningful a-trous level, so the filter was frequently a no-op. That is a statement about the
correlation input, not about trace smoothing for valley detection, and the implementation is in the
git history if a resurrection is wanted.

**Measured 2026-09-08: the smoother is load-bearing for the OUTPUT, and its cost cannot be priced
by removing it.** An ablation that returns the raw intensities instead of smoothed ones was not
faster but **slower** -- dataset D, same node, back to back: wall 5:35.95 -> 6:34.52 (+18%),
window-loop CPU 14,253 -> 18,279 (+28%) -- and emitted **1,122,695 spectra against 854,817 (+31%)**.
The reason is the consumer: the smoothed intensities feed a local-minimum search, and unsmoothed
noise manufactures spurious minima, so traces over-split and every downstream stage does more work.
Two consequences. The runtime question cannot be answered by ablation, because removing the
smoother changes the workload rather than isolating its cost -- it needs a timer inside
`smoothData()`. And the quality question is now the load-bearing one: a replacement smoother is not
a drop-in, it moves the split count directly, so it must be gated on peptides and on the split-count
distribution, not on speed.

**MEASURED 2026-09-09: step (1) is done and the runtime half is CLOSED. `smoothData` is 0.385%
of run CPU; the filter itself is 0.236%.** `rdtsc` around three regions of `smoothData`, dataset D,
100 threads, TSC pinned at 2.4500 GHz, run CPU 16,549 s (user 16,261 + sys 288):

| region | cycles/point | CPU s | % of run CPU |
|---|---|---|---|
| build the input `MSSpectrum` copy | 37.3 | 14.44 | 0.087% |
| `sg.filter()` -- Savitzky-Golay proper | 101.1 | 39.11 | **0.236%** |
| copy out via unreserved `push_back` | 26.4 | 10.22 | 0.062% |
| whole `smoothData` | 164.8 | **63.76** | **0.385%** |

41,190,765 calls over 947,955,937 points (23.0 points/trace); **`frame_len` ranges over [3, 6]**,
i.e. `win_size = ceil(chrom_fwhm / scan_time) = ceil(7.0 / 1.627) = 5`. Against the two phases that
contain it (window loop 12,033 + MS1 trace 337 = 12,369 CPU s) `smoothData` is 0.52% and the filter
0.32%. The four `rdtsc` reads per call add ~1.9 CPU s of the total, so the true figures are a few
percent lower. (The measurement build is not shipped: the instrumented
`ElutionPeakDetection.cpp` was restored and the rebuilt binary hashes to `dc5c331c...`, byte-identical
to the published `soa1`.)

Three conclusions follow, and together they close the runtime half for good:

1. **The coefficient cache already took it.** Pre-cache, `smoothData` was ~1,260 CPU s (from the
   -44% MS1 / -10% window-loop measurement that justified the cache); post-cache it is 63.8. There
   is no remaining runtime in this function to win.
2. **A DWT would be SLOWER, not faster.** At `frame_len` 5 the SG is a 5-tap convolution, ~6
   multiply-adds per point. A DWT denoise is analysis + threshold + synthesis over an L-level
   pyramid at ~8*k*n operations for filter length k: Haar (k=2) ~16n, db4 (k=8) ~64n -- **3x to 11x
   the arithmetic of the filter it would replace.** The entry's original "asymptotically cheaper"
   reasoning assumed long frames; the frames are 3-6.
3. **The traces are too short for a multi-level transform anyway.** 23.0 points per trace on
   average, and traces under 3 points skip smoothing entirely. A DWT wants n = 2^L; at n = 23 you
   get four levels at best, with levels 3-4 holding two or three coefficients where boundary
   extension dominates the transform. Wavelet shrinkage is a large-n method and this is not large n.

**So the ceiling on the runtime side is 0.24%: a smoother that took ZERO time would return 39 CPU s
of 16,549.** A DWT/CWT can only be adopted here if it wins on PEPTIDES, and it must do so while
paying 3-11x the arithmetic of what it replaces -- which, on a 0.24% base, is affordable: even a 10x
slower smoother costs ~2.4% of CPU, and at 80x parallelism roughly 4-5 s of a 660 s wall. **That is
the trade to state up front: runtime is no longer an objection to trying it, and no longer an
argument for it either.** The only remaining question is whether multi-scale denoising splits traces
better than a fixed 5-tap filter.

One incidental finding, not worth doing on its own: 39% of `smoothData` is the wrapper, not the
filter -- a `Peak1D` copy in and an unreserved `push_back` loop out, 24.7 CPU s (0.15%). Reserving
and writing the smoothed vector directly is output-identical and would make any future smoother
comparison cleaner, but 0.15% is a tidiness fix.

**How to test the remaining (quality) half.** The smoother is behind one OpenMS function, so this
is a contained experiment: (1) DONE -- see above; (2) implement the alternative behind a
`trace:smoother = savgol | wavelet` option,
defaulting to savgol; (3) compare on the two gate datasets and both engines, with entrapment FDR,
plus the split-count and trace-length distributions, which is where a smoother difference shows up
before the peptides do.

**What would falsify it.** Wavelet smoothing loses peptides on either engine or either dataset (it
is OUTPUT-CHANGING, so it needs the full gate); or the split-count distribution is indistinguishable,
meaning the valley search is insensitive to the smoother and the whole question is moot. The second
falsifier in the original entry -- "`smoothData()` is a negligible share of CPU after the cache" --
HAS NOW FIRED at 0.385%, which is why this item is a pure quality question and must be justified by
peptides or dropped. Note the direction of the prior: the tool currently emits 31% FEWER spectra
than with no smoothing at all, so the SG is already doing substantial work in suppressing spurious
valleys; a smoother that suppresses MORE is not automatically better, and the split-count
distribution is the first thing to look at, before any search runs.

### External-tool defects that need an OpenMS change or a DOI (2026-09-09)

Found by walking the openms-external-tools checklist. Two were fixed in the tool (the live update
check, and `verboseVersion_` dropping the OpenMS build -- both now gated in CI). These three
cannot be fixed inside SpeXtractor and are recorded rather than left to be rediscovered.

**1. `--help` advertises a documentation URL that 404s.** `TOPPBase::getDocumentationURL()`
(TOPPBase.cpp:2375-2388) returns `http://www.openms.de/doxygen/nightly/html/TOPP_<tool>.html`
unconditionally -- it does not consult the `official` flag we pass as false. For a tool that is
not in the OpenMS release there is no such page, so every user who follows the first line of
`--help` lands on a 404 instead of this repository. The method is NOT virtual (TOPPBase.h:194),
so it cannot be overridden in a subclass; fixing it means a fifth OpenMS patch making it virtual,
or upstreaming a change that respects `official`. Worth doing when the patch set is next touched,
not worth a patch of its own.

**2. The tool cites OpenMS but not itself.** `TOPPBase` takes a `std::vector<Citation>` as its
fourth constructor argument and prints "To cite <tool>:" when it is non-empty; we pass none, so
`--help` credits only OpenMS. `Citation::toString()` is `authors + title + when_where + "doi:" +
doi` with no conditional, so passing an entry without a DOI renders a bare "doi:." -- which is why
this is blocked rather than merely undone. It needs a real DOI first (a Zenodo deposit on the
GitHub release is the cheap route); CITATION.cff already exists and has everything else.

**3. `stty: 'standard input': Inappropriate ioctl for device` on every non-tty run.** OpenMS
probes the terminal width by shelling out to `stty`, which fails whenever stdout is not a
terminal -- i.e. every cluster run, every CI run, every pipe. It is harmless but it lands on the
same stderr this project's benchmark harness parses, and it looks like our error. Upstream fix
only.

Two smaller notes from the same pass, both ours: the `[perf-load] ms2 decode_wall=...` diagnostic
prints even on `--help`, where it is meaningless; and there is still no macOS or Windows
packaging at all (blocked on the missing Developer ID private key -- see the release review).


## Memory-work plan status (2026-09-08)

The memory-work plan (`.claude/plans`, see docs/BASELINE.md:1228) asked this file to record what it
skipped. Status of each step at the v2.0.0 release, from CHANGELOG.md, docs/BASELINE.md and the
source (`src` = src/spextractor.cpp; CHANGELOG entries are cited by title because the file is being
re-cut for the release):

| step | status | evidence |
|---|---|---|
| 0 tooling (digest fix, header diff) | DONE | CHANGELOG v2.0.0 Fixed, "The determinism digest was blind to the fragment sort's primary key"; bench/semantic_digest.py and bench/mzml_header_diff.py exist (the plan said tools/) |
| 1 MS1 arena compaction fix (G) | DONE, gate A passed | CHANGELOG v2.0.0 Fixed, "MS1 arena compaction overwrote ~1% of precursor XICs"; BASELINE.md:1230-1240, 1261-1309; src:413 `compactUnreferenced`, src:1725 `diag:selftest_arena`; B1/T1 taken |
| 2 instrumentation | DONE | CHANGELOG v2.0.0 Added, "Memory and stage instrumentation"; BASELINE.md:1242-1255; src:48, 185 `mallinfo2`; 13 e2e checks (BASELINE.md:1583) |
| 3 MassTrace move patch | DONE | patches/openms-masstrace-move.patch; CHANGELOG v2.0.0 Added, "Third OpenMS patch: move operations for `MassTrace`"; BASELINE.md:1247, 1316, 1353 |
| 4 lifetime releases | DONE | CHANGELOG v2.0.0 Fixed, "Lifetimes"; BASELINE.md:1317, 1323-1329 (v15) |
| 5 SpecRec + streaming mzML write | NOT STARTED | src:4737 `FileHandler().storeExperiment` (whole experiment); no SpecRec / MSDataWritingConsumer in src; WRITE still 52.4 s at 1.0x (BASELINE.md:1751, 1589) |
| 6 enforce `max_concurrent_windows` + admission budget | DONE | BASELINE.md:1364-1376 (v19); src:3779-3830, 3946; CHANGELOG v2.0.0 Fixed, "`perf:max_concurrent_windows` was computed and logged but never checked" (the audit found no entry; one is now present) |
| 7 chunked tof slab replaces the CompactFrame store | NOT STARTED | src:712 `CompactFrame` still mzq; src:820 `PeakSlab` is flat vectors; src:852 `toSlab` still converts per window, called at src:3991 |
| 8 Trace 72 -> 56 B | DONE and exceeded: 48 B | src:329 `static_assert(sizeof(Trace) == 48)`; BASELINE.md:1411-1425 (v20); CHANGELOG v2.0.0 Changed, "The trace record is 48 bytes, was 72" (the audit found it reading 56; corrected) |
| 9 segmented arenas, no absorb | NOT STARTED; measured as not worth it | src:314 `absorb()`, called at 1324, 4113, 4119; BASELINE.md:1634-1636, 1652-1653 (merge 5.3 s, "too small to matter"); only the reserve fix landed (CHANGELOG v0.3.0, "Trace arenas are reserved before merging") |
| 10a delete `frag_im` | NOT STARTED | src:4170-4171 still copies `frag_traces[i].im` into `vector<double> frag_im` |
| 10b delete `FragRt::rt` | NOT STARTED | src:2672-2677 `FragRt` still holds `vector<double> rt` |
| 11a per-band MS1 (PickedFrame, `ms1_map` gone) | PARTIAL, by a different mechanism | `ms1_map` still a PeakMap (src:3146); the serial band distribution was parallelised by chunking instead (CHANGELOG v2.0.0 Changed, "Mass-trace detection distributes its bands in parallel"; BASELINE.md:1499, 1509, v25: MS1_TRACE 252.5 -> 106.2 s; +3.4% peak RSS from chunked sub-maps, 1512-1513); `ms1_trace_bands` 12 -> 48 adopted (CHANGELOG v2.0.0 Changed, "`perf:ms1_trace_bands` default 12 -> 48"; BASELINE.md:1685-1694) |
| 11b MS1 as compact frames (G), gate B, B2/T2 | NOT STARTED | no MS1 compact path; T2 exists but was re-taken for `ms1_trace_bands=48`, not for 11b (BASELINE.md:1740-1743) |
| 12 band-local `visited` bitsets | NOT STARTED | src:1074 `visited` sized by `P = sl.tof.size()` (whole window) per band call; src:4046 |
| 13 MS1 through the integer detector, gate C | NOT STARTED | no `trace:ms1_detector` in src; CHANGELOG v2.0.0 Changed, "`Trace::tof` is 0 on the OpenMS MS1 path"; BASELINE.md:1594-1597 ("plan step 13") |

Still open from the plan: step 12 (band-local visited sets — see "Band-independent tracing" above),
comparator strengthening, the streaming mzPeak write, and steps 5, 7, 9, 10a/10b, 11b and 13 (see
"MS1 through the integer detector" above). Allocator hygiene and the admission budget are no longer
skipped: they shipped as `perf:malloc_trim` (CHANGELOG v2.0.0 Added) and v19 respectively. Release
notes may claim steps 0-4, 6, 8 (at 48 B) and the parallel band distribution; they may not claim a
streaming writer, a chunked slab, segmented arenas, a single scoring set, per-band MS1
materialisation, band-local visited sets, or an integer MS1 detector.

## Open items from the release review (2026-09-08, codex/kimi/vibe on v2.0.0)

Not fixed in the release; each is a measured gap, not a guess.

- **e2e coverage.** The gap-extension checks and the thread-count check run without a calibration
  sidecar and therefore exercise the `openms` fallback, not the shipped integer detector; check 13
  (admission high-water mark) uses a one-window fixture, so a cap of one cannot distinguish enforced
  from unrestricted admission; the mobility veto's branches (re-call, 3+ drop, insufficient fitting
  data) have no coverage because the fixture is too small to fit a line. No real-data thread-count
  digest pair has been taken since the compaction fix.
- **`threads = 1` in an ini file is overridden** to all cores: only argv is inspected, and the
  effective thread count is not written back into the tool's parameters, so provenance can record 1.
- **`scripts/sync_cluster.sh`** stages the source and copies headers before taking the remote lock,
  and restores only the `.cpp` on a failed build; two concurrent deploys can interleave their inputs.
- **Units.** Memory figures are `/usr/bin/time` RSS in kB / 10^6 and are labelled GB throughout;
  docs/BASELINE.md calls its figures GiB. Reconcile before any of them becomes a hardware requirement.
- **`perf:malloc_trim` in isolation at the shipped default**: the -30% / +8.5% pair is the whole
  memory pass (v13 -> v19) measured interleaved; the trim step alone was -28% / +6%. One trim-on/off
  A/B on v2.0.0 would settle the attribution.
