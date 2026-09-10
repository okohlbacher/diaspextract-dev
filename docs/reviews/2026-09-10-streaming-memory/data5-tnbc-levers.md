# TNBC 009: smaller tiles and the pass-1 levers (2026-09-10, chain `tnbc2`, binary d7cc14d)

Question: can smaller tiles, or the output-identical pass-1 levers, take the two-hour file's memory and
runtime down further? spock, 100 threads, 13 tiles at pitch 600 unless stated, `SPEXTRACTOR_MS1_HIST`
in every arm. `TNBC2_RESULT PASS`: every pitch-600 arm reproduces `bff54a1f`, the two pitch-300 arms
agree with each other (`725298dd`), and the MS1 histogram is identical in all six.

| arm | wall | peak | peak instant (ledger) | loop CPU |
|---|---:|---:|---|---:|
| control, first (load 5) | 10:16.16 | 68.94 GB | 67,450 MiB at 113 s, MS1 partition | 19,948 s |
| control, last (load 22) | 9:23.88 | 68.02 GB | 66,463 MiB at 79 s, MS1 partition | 20,061 s |
| `SPEXTRACTOR_MS1_TRIM=1` | 9:39.37 | 65.94 GB | 64,535 MiB at 40 s, **load** | 19,988 s |
| all three levers | 10:20.37 | **62.22 GB** | 61,082 MiB at 64 s, **load end** | 20,526 s |
| pitch 300, 26 tiles | 8:44.41 | 68.72 GB | 67,216 MiB at 77 s, MS1 partition | 17,873 s |
| pitch 300 with the levers | 9:52.18 | 62.78 GB | 61,221 MiB at 61 s, load end | 18,091 s |

The levers are: the MS1 trim between band distribution and detection, the MS1-only picker batch of 64,
and a trim every 16th flush. The controls bracket at 68.48 GB mean, 0.92 GB and 52 s apart. Their load
phase alone differed by 33 s (74.2 against 41.3), so wall differences under a minute are node noise.

**The pass-1 levers work and are output-identical: −6.3 GB (−9.1%) against the mean control**, with wall
inside the controls' spread. The MS1 trim alone returned 11.9-12.8 GB right after distribution and moved
the peak to the load (−2.5 GB). Adding the batch and flush trims lowers the load too, and the peak lands
at the end of the load, where the MS1 map is nearly full (44.2 GiB at the instant). The window loop, no
longer trimmed only at its end, finishes at 14.0 GB RSS instead of ~47.

**Smaller tiles do not lower the peak, with or without the levers.** Pitch 300 peaks at 68.72 GB alone
and 62.78 GB with the levers, matching pitch 600 in both cases, because the peak is in pass 1, which
tiling does not touch. What pitch 300 does buy is scan work: the scorer's fragment visits fall from
1.120e12 to 5.91e11 (−47%) and loop CPU by about 10%. But pitch 300 changes the output, so it is a
science knob: it would need both search engines and entrapment before it could be adopted.

**What binds next on TNBC is the MS1 map itself.** At the all-levers peak, 44.2 GiB of the 61.1 GiB is
the map. The exact prune of sub-threshold MS1 centroids (ms1-tracing-model.md, rank 1) targets exactly
that: 85.0% of the map's centroids are below the tracer's threshold.
