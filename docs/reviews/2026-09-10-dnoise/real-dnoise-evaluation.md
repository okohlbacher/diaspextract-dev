# The real dnoise v0.1.0 on both files, searched (2026-09-10)

What dnoise does to SpeXtractor's output when it runs as a preprocessor on the raw `.d`, for every
combination of its MS1 and MS2 filters, judged on peptides from both engines and on entrapment.

## Method

dnoise v0.1.0, the release binary (sha256 `0f476992…5857d92`, verified), run on the original `.d`. Five
configurations per file:

| configuration | dnoise invocation |
|---|---|
| control | none: the original `.d`, rerun on the same node, must reproduce the pin |
| no-op | `--config ms1_off.toml`: every stage off (streak length 1, gap 0, one iteration, halo and both MS1 gates off). Must reproduce the pin |
| MS1 only | no flags: dnoise's own default. Streak filter length 5, gap 2, ±3 TOF, 2 iterations, halo on, both MS1 gates on (the isolation-window union; the selection polygon is a no-op on diaPASEF) |
| MS2 only | `--config ms1_off.toml --denoise-msms` |
| MS1 + MS2 | `--denoise-msms` on the defaults |

The last two configurations are not a clean factorial. With `--denoise-msms`, the halo filter also runs on
MS2, and MS2 only has the halo off. Dry runs attribute the difference to the halo exactly: 0.4 points more
of D's MS2 removed and 4.5 points more of TNBC's (`stage1-measurement.md`).

SpeXtractor build `d7cc14d`, 100 threads, pitch 600, **`-tile:cells_per_tile 1`**, so one 600-s cell per
tile. The output does not depend on the tile count, by construction. Memory does: every peak below is the
tiled peak. The shipped default is one tile (`cells_per_tile 0`), where the window loop sets the peak, and
that was not measured with dnoise.

The gates are the usual three:

- Sage (`sage_deiso.json`) unique peptides at rank 1, q ≤ 0.01.
- Sage entrapment FDR with its 95% interval.
- MSFragger 4.4.1 target peptides at 1% FDR.

On top of those: Sage peptide-set overlap with the control, and `bench/dnoise_strat.py`, which stratifies
lost and gained Sage peptides by the control's intensity and hyperscore quintiles. The control and the no-op
were not searched again. Their search results are the recorded searches of the pinned output (D:
`step3a/d_acq`; TNBC: `dnoise_eval/control_tnbc`), which any digest-identical output reproduces.

Nodes: dataset D ran entirely on ibminode05. On TNBC 009, MS1 only and MS1 + MS2 ran on `data`; the
control, the no-op and MS2 only ran on `spock`. A second TNBC control was rerun on `data` afterwards, so
each node has its own reference. Every node is shared: compare wall within a node only.

## What dnoise's MS2 mode is on diaPASEF

On diaPASEF, `--denoise-msms` runs the MS/MS streak filter inside each isolation window, and the filter
does almost all of the removal. The isolation-window scan gate removes no MS2 points on D and 0.09% on
TNBC. The filter removes 66.8% and 54.0%. The dry runs are in `stage1-measurement.md`, which this
evaluation corrected.

## Results

Built by `bench/dnoise_table.py` from the chain logs and the recorded control searches. Wall and peak in
these two tables are SpeXtractor's alone; dnoise's own run is in the next section. "Picked MS1 peaks" is
the count from `SPEXTRACTOR_MS1_HIST`. One cell needed a manual read: TNBC MS2-only's `e.log` contains
binary bytes, so the chain's `grep` hid its `Wrote` line. The count was read with `grep -a`, and equals
MSFragger's scan count for that input.

### Dataset D (ibminode05)

| configuration | MS1 points kept | all points kept | .d size | SpeXtractor wall | SpeXtractor peak | pseudo-spectra | picked MS1 peaks | Sage peptides | MSFragger peptides | entrapment FDR (95% CI) | Sage set vs control: common / lost / gained |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| control, original file | 100% | 100% | 9.2G | 3:48.08 | 31.84 GB | 611,850 | 725,116,915 | 13,491 | 12,918 | 1.30% (1.07-1.55%) | reference |
| dnoise, every stage off | 100.0% | 100.0% | 9.1G | 3:47.44 | 32.17 GB | 611,850 | 725,116,915 | 13,491 (+0.0%) | 12,918 (+0.0%) | 1.30% (1.07-1.55%) | identical output |
| dnoise MS1 only (its default) | 12.7% | 67.3% | 7.5G | 3:06.84 | 21.41 GB | 496,722 | 43,546,607 | 12,917 (−4.3%) | 12,404 (−4.0%) | 1.36% (1.13-1.61%) | 11,590 / 1,901 / 1,327 |
| dnoise MS2 only | 100.0% | 58.3% | 6.6G | 1:57.72 | 32.13 GB | 603,275 | 725,116,915 | 12,758 (−5.4%) | 11,234 (−13.0%) | 1.46% (1.19-1.72%) | 11,396 / 2,095 / 1,362 |
| dnoise MS1 + MS2 | 12.7% | 25.3% | 5.0G | 1:16.09 | 8.13 GB | 492,682 | 43,546,607 | 12,522 (−7.2%) | 10,945 (−15.3%) | 1.26% (1.03-1.52%) | 10,911 / 2,580 / 1,611 |

### TNBC 009

| configuration | node | MS1 points kept | all points kept | .d size | SpeXtractor wall | SpeXtractor peak | pseudo-spectra | picked MS1 peaks | Sage peptides | MSFragger peptides | entrapment FDR (95% CI) | Sage set vs control: common / lost / gained |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| control, original file | spock | 100% | 100% | 20G | 9:18.79 | 68.82 GB | 3,285,827 | 2,391,660,683 | 29,067 | 27,949 | 1.09% (0.94-1.23%) | reference |
| control, original file | data | 100% | 100% | 20G | 9:16.95 | 68.41 GB | 3,285,827 | 2,391,660,683 | same output | same output | same output | identical output |
| dnoise, every stage off | spock | 100.0% | 100.0% | 20G | 9:23.24 | 69.73 GB | 3,285,827 | 2,391,660,683 | 29,067 (+0.0%) | 27,949 (+0.0%) | 1.09% (0.94-1.23%) | identical output |
| dnoise MS1 only (its default) | data | 20.5% | 70.7% | 15G | 8:00.85 | 25.08 GB | 3,010,923 | 309,395,291 | 29,510 (+1.5%) | 27,808 (−0.5%) | 0.93% (0.80-1.08%) | 26,351 / 2,716 / 3,159 |
| dnoise MS2 only | spock | 100.0% | 65.9% | 13G | 5:44.18 | 67.80 GB | 3,259,327 | 2,391,660,683 | 26,167 (−10.0%) | 22,112 (−20.9%) | 0.93% (0.78-1.08%) | 23,721 / 5,346 / 2,446 |
| dnoise MS1 + MS2 | data | 20.5% | 33.7% | 7.3G | 3:42.71 | 19.87 GB | 2,989,162 | 309,395,291 | 26,792 (−7.8%) | 23,678 (−15.3%) | 0.92% (0.78-1.07%) | 23,661 / 5,406 / 3,131 |

Chain `tnbc2`, earlier the same day, ran two more TNBC controls on spock: 10:16 and 9:24, 68.94 and
68.02 GB.

### The preprocessing step itself

dnoise's own wall and peak, and the pipeline's. Pipeline wall is dnoise plus SpeXtractor; pipeline peak is
the larger of the two.

| configuration | D: dnoise | D: pipeline | TNBC: dnoise | TNBC: pipeline |
|---|---|---|---|---|
| control | — | 3:48, 31.84 GB | — | 9:19, 68.82 GB (spock); 9:17, 68.41 GB (data) |
| no-op | 0:17, 12.91 GB | 4:05, 32.17 GB | 0:31, 27.53 GB | 9:54, 69.73 GB (spock) |
| MS1 only | 1:24 (cold read), 12.90 GB | 4:31 (cold read), 21.41 GB | 1:28 (cold read), 25.24 GB | 9:29 (cold read), 25.24 GB (data) |
| MS2 only | 0:17, 10.51 GB | 2:15, 32.13 GB | 0:28, 26.97 GB | 6:12, 67.80 GB (spock) |
| MS1 + MS2 | 0:18, 10.29 GB | 1:34, 10.29 GB | 0:34, 26.32 GB | 4:16, 26.32 GB (data) |

The two MS1-only dnoise times, 1:24 and 1:28, were each chain's first read of the input `.d`, not the
filter. I reran them on ibminode05 with the input already in the page cache. The default took 17.7 s and
16.8 s on D, and `--denoise-msms` took 18.0 s. On TNBC, at load 72-116, they took 54.7 s and 58.0 s.
dnoise's own cost is therefore about 17 s on D, whatever it filters. With that, D's MS1-only pipeline is
about 3:24 against the control's 3:48. TNBC MS1 only was not rerun warm on data.

## Where the peptides go (Sage)

Sage's lost peptides, stratified by the control's MS2 intensity quintile and hyperscore quintile (Q1 =
faintest or weakest). "Gained" counts peptides new in the arm. The last column is the share of gained
peptides that fall below the control's faintest-quintile edge, judged by the arm's own intensities.
MSFragger was not stratified.

| arm | lost | gained | net | lost, intensity Q1 | Q5 | lost, hyperscore Q1 | Q5 | gained below Q1 edge |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| D, MS1 only | 1,901 (14.1%) | 1,327 | −574 | 35.7% | 2.0% | 43.1% | 0.3% | 43% |
| D, MS2 only | 2,095 (15.5%) | 1,362 | −733 | 46.1% | 1.5% | 45.3% | 0.4% | 38% |
| D, MS1 + MS2 | 2,580 (19.1%) | 1,611 | −969 | 52.0% | 2.5% | 51.0% | 0.9% | 35% |
| TNBC 009, MS1 only | 2,716 (9.3%) | 3,159 | +443 | 22.6% | 1.8% | 30.4% | 0.2% | 50% |
| TNBC 009, MS2 only | 5,346 (18.4%) | 2,446 | −2,900 | 55.9% | 1.9% | 52.1% | 0.8% | 38% |
| TNBC 009, MS1 + MS2 | 5,406 (18.6%) | 3,131 | −2,275 | 54.8% | 2.3% | 52.4% | 1.0% | 37% |

Full tables, including by charge and by RT tenth, come from
`bench/dnoise_strat.py CONTROL/results.sage.tsv ARM/results.sage.tsv` on the chain directories
(`/scratch/kohlbach/dnoise_eval/{D,TNBC009}/<arm>/sage/`).

## Findings

1. **The rewrite is lossless for SpeXtractor.** The no-op reproduces both pins (D `8c1b047f`, TNBC
   `bff54a1f`), so on an unfiltered file dnoise's writer changes nothing SpeXtractor reads. The differences
   below are the filters, plus however the writer handles frames the filters empty, which the no-op cannot
   exercise.
2. **MS1 filtering unlocks the memory; MS2 filtering alone changes nothing.** dnoise's default keeps 12.7%
   of D's MS1 points and 20.5% of TNBC's. The picked MS1 map shrinks 16.7× and 7.7×, and SpeXtractor's
   tiled peak falls 33% on D and 63% on TNBC against the same-node control. MS2 only leaves the
   peak within 1.5% of the control, because pass 1 sets it. Once MS1 is filtered, MS2 filtering does lower
   memory: on D, SpeXtractor goes from 21.41 to 8.13 GB and the pipeline to 10.29 GB, where dnoise itself
   binds. On TNBC, SpeXtractor goes from 25.08 to 19.87 GB, but the pipeline stays at dnoise's 25-26 GB
   (25.24 and 26.32 GB).
3. **In peptide counts, MS1 only is nearly free on TNBC and not on D.** TNBC: Sage +1.5%, MSFragger
   −0.5%, though 9.3% of the control's Sage peptides are replaced. D: Sage −4.3% and MSFragger −4.0%, the
   two engines agreeing, which fails the S gate. One plausible reading, not tested: on D the filter removes
   more of what the tracer works on. Picked MS1 centroids at or above 100 counts fall 75.8% on D against
   50.6% on TNBC. That count is approximate, because filtering also lowers the intensity of surviving
   centroids. Stage 1's raw-point figures, 53% against 22%, point the same way, but they were measured at
   the paper point, not at dnoise's default.
4. **Filtering MS2 costs MSFragger most, on both files.** MS2 only: MSFragger −13.0% on D and −20.9% on
   TNBC, Sage −5.4% and −10.0%. MS1 + MS2: MSFragger −15.3% on both, Sage −7.2% and −7.8%. On TNBC, MS1 + MS2
   keeps more peptides than MS2 only (Sage +2.4%, MSFragger +7.1%), even though it removes 4.5 points more
   MS2. On D it keeps fewer (−1.8%, −2.6%). The two differ in both the MS1 filter and the halo on MS2, with
   one run each, so the difference cannot be credited to the MS1 filter.
5. **Entrapment never rises above the control's interval.** D's three arms stay inside it; the largest rise
   is +0.16 points (MS2 only), well within the S gate's +0.3. All three TNBC arms fall just below it, to
   0.92-0.93% against 1.09% (0.94-1.23%), which is −0.16 to −0.17 points.
6. **The Sage loss sits in the faint, low-scoring tail.** Across all six arms the control's faintest
   intensity quintile loses 23-56% of its peptides and the brightest 1.5-2.5%; by hyperscore, 30-52% against
   0.2-1.0%. MS1 filtering alone churns the faint stratum (net −392 on D, +283 on TNBC). Every arm that
   filters MS2 depletes it, losing 2.4-3.5 faint peptides for each faint one gained (net −721 and −840 on D,
   −2,310 and −2,022 on TNBC). Two caveats. Losses near the score threshold follow from any output change,
   and no null arm was run, so this locates the loss rather than showing that dnoise removes faint signal
   selectively. And that stratum is already the tool's identification gap.
7. **MS2 filtering is the time lever.** Pipelines on D: 3:48 for the control against 2:15 for MS2 only and
   1:34 for both. On spock, TNBC MS2 only runs 6:12 against the control's 9:19. On data, TNBC MS1 + MS2 runs
   4:16 against the control's 9:17.

## What this means for SpeXtractor

- **Not as a default.** dnoise's own default fails the S gate on D. Every MS2 setting costs 13-21% of
  MSFragger peptides and 5-10% of Sage's.
- **Part of the memory has a route that can preserve output, but it is not dnoise's peak.** 85% of TNBC's
  picked MS1 map lies below the tracer's 100-count threshold and is never traced. The MS1 tracing model
  (`../2026-09-10-streaming-memory/ms1-tracing-model.md`) ranks pruning those centroids at the picker flush
  first. It is class D only with two conditions coded: band edges drawn from the unpruned spectra, and a
  per-frame band non-emptiness mask. The model's verifier rated it "partly". It predicts the map at 45,617
  → ~6,840 MiB (44.5 → 6.7 GiB), but the 13-tile run peak only at ~52 GB, because the window loop then
  binds; a per-tile trim is predicted to take the loop to ~20-25 GiB. None of this is measured. dnoise MS1
  only reached 25.08 GB, at a cost in peptides.
- **MS2 filtering stays out.** Its time saving costs 13-21% of MSFragger peptides on both files.
