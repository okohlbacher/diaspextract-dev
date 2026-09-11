# Why the first integer trace detector failed, and what the corrected one does

Measured on dataset D, same binary family, OpenMS detector as reference (656,254 spectra, 12,642 Sage
peptides):

| version | spectra | peptides | wall | peak RSS |
|---|---|---|---|---|
| first integer detector | 312,539 | **994** | 5:47 | 86 GB |
| + sample-rate sentinel fixed only | 625,495 | 8,907 | 4:25 | 92 GB |
| corrected, centroid m/z into valley splitting | 656,241 | 11,940 | 9:38 | 168 GB |
| corrected, measured per-peak m/z | 656,241 | **12,650** | 9:28 | 174 GB |
| corrected, prep hoisted + bin search | 656,256 | 12,466 | 9:31 | 185 GB |
| **corrected, valley splitting chunked + parallel** | 656,256 | 12,466 | **6:53** | **105 GB** |
| same, raw-emptiness A/B (SPEXTRACTOR_INT_EMPTY_RAW=1) | 656,256 | 12,466 (set identical to the row above) | 6:56 | 105 GB |

**The emptiness rule was NOT the 1.4%.** Same count, same set. The only other semantic change between
the 12,650 and 12,466 versions is the candidate metric: "closest to the centroid" measured in bins
instead of m/z. I had asserted they agree because the calibration is monotone; that holds for
candidates on one side of the centroid and fails across it, where the map's curvature can flip
which is nearer. The bin metric also bought no time -- the speed came from parallel valley
splitting -- so it is reverted (tr9) and the A/B is the 12,650 it should recover.
| OpenMS detector, same binary | 656,254 | 12,642 | 7:17-7:22 | 164-166 GB |

**The serial section was valley splitting.** Chunking it into bands*4 parallel tasks, as the OpenMS
path does, took the integer detector from 9:31 to 6:53 wall (now faster than the OpenMS path's
7:17), window-loop CPU from 17,414 to 15,842 s, occupancy from 44x to 67.6x, and peak memory from
185 to 105 GB -- 36% below the OpenMS path. Peptides unchanged at 12,466; the 1.4% against the
12,650 of the earlier version is the frame-emptiness rule and is being measured in isolation.

**Science: parity.** 12,650 against 12,642, with a symmetric set difference (1,036 only-reference,
1,044 only-integer): the residual of a faithful reimplementation that is not bit-identical, and a
net of +8. The centroid-m/z row shows what the second-pass review caught was worth: −5.6%.

**Performance: the design's falsifier fired.** Slower (9:28 vs 7:22), less occupancy (46.9x vs
78.9x) and MORE memory (174 vs 166 GB). Layout was not the cost. Two causes, both in the first
corrected version's own bookkeeping, not in the algorithm:
1. every band task rebuilt the per-window arrays (frame index, membership, the intensity-sorted
   seed list) -- twelve full-window sorts per window, twelve P-sized array sets alive at once;
2. the candidate walk converted every visited peak from bin to m/z (a sqrt per visit) to compare
   in m/z, although the calibration is monotone and closest-in-bins is the same peak.
The version after that prepared each window once and searched in bins -- and changed NOTHING
(9:31, occupancy 44x, memory up to 185 GB, peptides 12,466). So neither the per-band sorts nor
the per-visit calibration calls were the cost. What that version still did on one thread per
window, and the OpenMS path does in bands*4 parallel chunks, is valley splitting: every trace
converted to a list-based MassTrace and ElutionPeakDetection run over the whole window's traces at
once -- a serial section inside the stage that is 95% of the loop, with the whole window's list
copy alive simultaneously. That is consistent with both the occupancy and the memory. The next
version chunks and parallelises it exactly as the OpenMS path does.

**Second-pass review (docs/reviews/integer-tracing-v2-2026-09-03/):** vibe found the extension
loop faithful line by line and the per-peak m/z gap above. codex found it "close but not
step-for-step" and listed boundary items now addressed: frame emptiness tested before rather than
after sub-noise deletion, `max_trace_length` 0 meaning "on" instead of "off", valley splitting run
for a single trace, `frame_aggregation_n` silently ignored, and the mzPeak archive index misread as
a vendor frame Id. **kimi was SILENT** (385 bytes: it left to consult upstream OpenMS and never
returned) -- no review, not a clean bill.

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


## dataset A: the second file (2026-09-03, 23:09)

| dataset A, 100 threads | wall | peak RSS | Sage @1% |
|---|---|---|---|
| integer detector | **11:51** | **140 GB** | **11,121** |
| OpenMS detector, same binary | 11:42 | 230 GB | 11,084 |
| the reference implementation, same node | 9:46 | 163 GB | 10,242 |

**The dataset D peptide deficit does not reproduce.** On dataset A the integer detector finds slightly MORE
peptides than the OpenMS path (11,121 vs 11,084, +0.3%) where on dataset D it found 1.4% fewer -- which is
what a faithful-but-not-identical reimplementation looks like: a small per-file wobble of either
sign, not a systematic loss.

**Memory is the bigger and more consistent result: 140 GB against 230 GB, a 39% cut**, matching the
36% seen on dataset D (105 vs 164 GB). It also puts DIAspeXtractor BELOW the reference implementation's 163 GB on this file for
the first time. Wall time is a wash here (11:51 vs 11:42) although it won on dataset D (6:53 vs 7:17);
window-loop CPU is 31,033 s against 41,530 s, i.e. the integer path does 25% less work but fills
fewer threads (64x vs 87x), so on the larger file the two effects cancel.

Remaining before it could be a default: MSFragger and entrapment (queued), and an explanation for
the occupancy gap -- 64x vs 87x is the last unexplained number in this line of work.


## Both engines and entrapment (2026-09-03, 23:41)

| dataset D | Sage @1% | MSFragger @1% | entrapment FDR |
|---|---|---|---|
| OpenMS detector (shipping default) | 12,642 | 12,073 | 1.38% [1.15-1.64] |
| integer detector | 12,466-12,475 (−1.3%) | **12,328 (+2.1%)** | 1.24% [1.01-1.50] |

**The two engines disagree in sign.** Sage loses 1.3%, MSFragger gains 2.1%, on the same spectra --
and on dataset A Sage itself gained 0.3%. So there is no evidence of a systematic loss; there is evidence
of a per-engine, per-file wobble of about a percent either way, which is what a faithful-but-not-
identical reimplementation produces. Entrapment is slightly LOWER (1.24% vs 1.38%), so nothing here
is bought with false positives.

**The candidate-metric revert did essentially nothing:** 12,466 -> 12,475 on Sage (+9), 12,328 ->
12,322 on MSFragger (−6). So the earlier attribution of the 12,650 -> 12,466 move to the bin metric
was WRONG too -- neither that nor the frame-emptiness rule explains it, and both A/Bs came back
null. The remaining difference between those two builds is the per-window preparation hoist and the
chunked valley splitting, i.e. the parallel structure, which means the ~1% is scheduling-order
sensitivity in a greedy consume-and-mark algorithm, not a semantic difference. That is expected and
is the reason this project gates on peptide SETS rather than counts.

**Status: the adoption conditions are met on everything except a reason to prefer it.** Both engines
within ~2% either way, entrapment no worse, dataset A replicated on memory (−39%) and peptides (+0.3%).
The case for it is memory (−36 to −39%, and below the reference implementation for the first time) and CPU (−25%); the
case against is a 64x vs 87x occupancy gap that is still unexplained, and that gap is what makes the
wall-time win vanish on the larger file.
