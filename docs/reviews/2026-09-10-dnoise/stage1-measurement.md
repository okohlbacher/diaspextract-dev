# dnoise stage 1 on raw MS1 frames, measured (2026-09-10)

The verdict in this folder said: measure what the ion-mobility streak filter removes before writing any
of it. This is that measurement for stage 1 alone, plus a dry run of the real dnoise v0.1.0 on dataset D.

## Method

Sampled MS1 frames, read whole through the Bruker SDK: 60 of TNBC 009's 4,797 and 40 of dataset D's
1,343, evenly spaced. Every frame's point count equals `Frames.NumPeaks`: 38,804,584 points on TNBC and
27,269,046 on D. Paper point: at least 5 occupied scans, gaps of up to 2 bridged, a TOF window of ±2,
no intensity floor, one iteration.

Two independent implementations ran on the same frames, then a comparator checked both against a
deliberately slow brute-force reference on four TOF slices, about 20,000 points each.

- **A, the per-point window predicate**, matched the reference exactly: 0 mismatches on 80,012 points.
  It is the faithful implementation and every number below is from A.
- **B, the verdict's streak-clustering reformulation**, removes strictly MORE in every one of the 100
  frames: 4.8 points more pooled on TNBC and 2.9 on D, up to 5.6 per frame. It splits real ions whose TOF
  jitters over 3-4 bins once the streak's running mean drifts, and it credits some points with
  occupancy outside their own column.

**The verdict's claim that the reformulation "agrees on isolated points, differs only in crowded columns
that pass both, and removes strictly no more than dnoise" is falsified.** Any cheap in-loader version
would have to be the per-point window predicate.

## Removal at the paper point

| | TNBC 009 | dataset D |
|---|---:|---:|
| raw MS1 points removed | **70.4%** | **86.9%** |
| raw MS1 intensity removed | 41.6% | 70.6% |
| points in runs of one scan | 44.9% | 60.5% |

Removal by raw point intensity, points removed (intensity removed):

| raw counts | TNBC 009 | dataset D |
|---|---:|---:|
| 5-9 | 83.3% | empty |
| 10-99 | 74.9% (70.5%) | 90.8% (89.5%) |
| 100-999 | 23.2% (14.9%) | 53.9% (40.8%) |
| ≥ 1000 | 0.5% (0.2%) | 0.06% (0.03%) |

**Removal is a monotone staircase in intensity.** That fails the verdict's kill rule 4 at the raw-point
level; the centroid-level test, re-picking filtered and unfiltered frames, has not been run. Inside the
tracer's own working population, raw points above 100 counts, stage 1 removes 22% of TNBC's points (9% of
their intensity) and 53% of D's (31%). Along the run, removal is lowest in dense elution (TNBC 62%, D 83%)
and rises to 90-100% in the wash and before elution. The full grid, min feature length {3,4,5,6,8} × gap
{1,2,3} × window {1,2,4}, is on ibminode05 under `/scratch/kohlbach/dnoise_m1/impl_window/results`.

Two corrections to the verdict's arithmetic:

- **Its "every picker singleton is a run of length 1" lemma fails on TNBC.** Singletons are at least
  51.0% of raw points, but only 44.9% of sampled points sit in one-scan runs. So its bound on the
  surviving MS1 map is not a bound on the two-hour file. On D the lemma is consistent (56.4% ≤ 60.5%).
- **A unit slip.** 201.9 M centroids × 20 B is 3,851 MiB, not 4,038.

Raw-point removal does not map one-to-one to picked centroids, because the picker merges points. The
surviving TNBC MS1 map is estimated at 2.5-17.9 GiB against today's 44.5 GiB (45,617 MiB), uncertain by
about 5x until centroids are counted. *(This line first said "45.6", a unit slip.)*

## The MS1 map is mostly below the tracer's own threshold

`SPEXTRACTOR_MS1_HIST` on TNBC 009, 2,391,660,683 picked MS1 peaks:

| picked intensity | share |
|---|---:|
| < 100 | **85.0%** |
| 100-300 | 12.5% |
| 300-1000 | 1.9% |
| 1000-10000 | 0.5% |
| ≥ 10000 | 0.04% |

OpenMS `MassTraceDetection` builds its working map only from peaks above `noise_threshold_int`, which is
100 on our MS1 call (`MassTraceDetection.cpp:243`), and runs entirely on that map. **So 85% of the MS1 map,
and of the band copy and free list derived from it, is never traced.** Dropping those peaks is not
automatically output-identical: the MS1 band edges are drawn from the whole map, and a band spectrum is
kept if any peak, sub-threshold included, falls in the band, which sets the scan sequence the tracer
steps through. A version that preserves both would be class D.

## The real dnoise v0.1.0, dry runs on dataset D (and TNBC 009 for the MS2 split)

`dnoise-linux-x86_64.tar.gz` from github.com/pgarrett-scripps/dnoise, release v0.1.0, sha256
`0f476992…5857d92`, verified. Its shipped defaults are NOT what the verdict assumed: ±3 TOF indices, two
iterations, the halo filter ON, and both MS1 gates (isolation-window union and selection polygon) on.

| run | MS1 points kept | all points kept | wall |
|---|---:|---:|---:|
| defaults (MS1 only) | 12.73% of 927,158,066 | 67.3% of 2.47e9 | 38 s |
| `--denoise-msms` | 12.73% | 25.3% | 8 s |

The 38 s was the first read of the input, not the filter: full runs with the input in the page cache take
about 17 s on D in either mode (`real-dnoise-evaluation.md`).

On diaPASEF, `--denoise-msms` runs dnoise's MS/MS streak filter inside each isolation window, and that
filter does almost all of the removal. *(Corrected the same day: this paragraph first said the reverse, that
the filter was ddaPASEF-only and the window gate did the removing.)* Dry runs, all on `ms1_off.toml` so the
MS1 streak filter and both MS1 gates are off:

| MS2 points kept | dataset D | TNBC 009 |
|---|---:|---:|
| `--denoise-msms` | 33.22% | 45.96% |
| scan gate only (`--denoise-msms --msms-min-feature-length 1 --msms-max-internal-gap 0 --msms-iterations 1`) | **100.00%** | **99.91%** |
| MS/MS filter only (`--denoise-msms --no-dia-window`) | 33.22% | 45.96% |
| filter over the whole frame (`--denoise-msms --no-dia-per-window`) | 33.22% | not run |
| `--denoise-msms` with the halo filter on | 32.81% | 41.43% |
| halo filter on, no `--denoise-msms` | 100.00% | 100.00% |

dnoise's JSON report does not record the MS/MS filter's parameters, so the neutralised run's report looks
like the unneutralised one. The halo reaches MS2 only when the MS/MS filter runs, and then removes 0.4
points more of D's MS2 and 4.5 points more of TNBC's; that is exactly the MS2 difference between the
MS1 + MS2 and MS2-only configurations in the searched runs. On its own the halo removes 2.4% of D's MS1
points and 19.2% of TNBC's.

The full runs, DIAspeXtractor on the output, and both search engines with entrapment are chains `dnoise_d`,
`dnoise_tnbc`, `dnoise2_d` and `dnoise2_tnbc`, written up in `real-dnoise-evaluation.md`.
