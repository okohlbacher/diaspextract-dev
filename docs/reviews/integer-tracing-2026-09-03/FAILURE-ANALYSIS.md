# Why the first integer trace detector failed, and what the corrected one does

Measured on S30, same binary family, OpenMS detector as reference (656,254 spectra, 12,642 Sage
peptides):

| version | spectra | peptides | wall | peak RSS |
|---|---|---|---|---|
| first integer detector | 312,539 | **994** | 5:47 | 86 GB |
| + sample-rate sentinel fixed only | 625,495 | 8,907 | 4:25 | 92 GB |
| corrected (this commit) | pending | pending | pending | pending |

The first version was written from a DESCRIPTION of `MassTraceDetection`; the design document
called it faithful. Three reviewers (codex, kimi, vibe) read the OpenMS source instead and agreed it
was not. Their findings, ranked by how much each one changes WHICH traces exist:

| # | deviation | OpenMS actually | first version | found by |
|---|---|---|---|---|
| 1 | min_sample_rate sentinel | tool passes -1 = "keep the OpenMS default", which is 0.5 | read -1 as no termination: every trace ran the whole gradient, took one peak per frame, then was discarded for exceeding max length | measured (this is the 994) |
| 2 | termination rule | `outlier`: a direction stops after >5 consecutive misses; empty frames are not misses | a running per-direction hit rate, and empty frames counted as misses | codex, kimi, vibe |
| 3 | final validity | `size / (frames visited - trailing misses) >= 0.5`, applied once at the end | none | codex, kimi |
| 4 | tolerance | closest peak within +-3 sd, sd = centroid*ppm initially and RE-ESTIMATED from accepted peaks | fixed +-1 ppm span in bins: 3x narrower, never widening | codex, kimi, vibe |
| 5 | closest-then-reject | the closest candidate is chosen first; if it is already taken the frame is a miss | took the closest UNTAKEN peak | codex, kimi |
| 6 | when peaks are taken | marked only after the trace passes validity | marked at take time, never rolled back | codex, kimi |
| 7 | direction order | one frame down, one frame up, interleaved, sharing one centroid | +1 to exhaustion, then -1 | codex, kimi, vibe |
| 8 | mobility gate | against a RUNNING intensity-weighted mobility centroid | against the seed's mobility forever | codex, kimi |
| 9 | valley splitting | ElutionPeakDetection runs on the traces | skipped entirely in the integer branch | kimi |
| 10 | mobility axis | -- | ranked a frame's distinct mobilities as TIMS scans; false on PICKED frames, where mobility is a centroid, not a scan | kimi |
| 11 | profile pairing | -- | sorted the frame array alone, so intensities attached to the wrong frames | codex |
| 12 | membership | peaks <= noise are deleted before tracing | only seeds were filtered | codex, kimi |
| 13 | seed weight | the seed is counted twice in the centroid (init, then update) | once | codex |
| 14 | drift cap | none | a cap of +-span from the seed, invented to make banding exact | codex |

Item 1 alone accounts for 994 -> 8,907. Items 2-9 are what the corrected version implements, each
written from the OpenMS function that defines it (`run_`, `findBestPeak_`, `isPeakAcceptable_`,
`processPeak_`, `updateIterativeWeightedMean_`, `updateWeightedSDEstimateRobust`, `isTraceValid_`).
Items 10 and 14 are retired: the mobility gate is integer `imq` against a running centroid, which is
OpenMS's semantics in integer form, and banding no longer claims exactness -- a band seeds only in
its own core and may extend anywhere, so nothing is cut, and the only residual is that two bands can
take the same peak, the same class of error the OpenMS halo carries (measured 0.1% of peptides).

**What the six-check suite did not catch.** Every version passed it. The suite covers parameter
handling, the charge gate and thread-count identity; it has nothing that exercises trace extension
on data with gaps, so a wrong termination rule is invisible to it. A check that would have caught
items 1-2: a synthetic profile with one missing frame in the middle must come out as ONE trace, and
one with seven missing frames must come out as two.

**What the speed numbers mean now.** Nothing yet. The first version was fast partly because it did
a twelfth of the work. The corrected detector is judged on peptides first; only if those match is its
wall time a result.
