## 1. Line-by-line diff against OpenMS

Verdict: the extension loop is now close, but the implementation is still not step-for-step equivalent.

| Tool line | Difference from OpenMS | Effect |
|---|---|---|
| [L822](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:822) | Emptiness is tested on the original slab. OpenMS first deletes every peak `<= noise`, then tests `spec.empty()`. A frame containing only below-noise peaks is therefore empty to OpenMS but non-empty here; this code calls `best()`, fails, and increments `missed`. Six such frames can terminate a direction, and trailing ones are incorrectly removed from the sample-rate denominator. | **SET** |
| [L761](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:761)–763 | The missing OpenMS lines are `prev_counter *= counter_tmp; prev_denom *= denom_tmp`, not `+= w*v` and `+= w`. They are algebraically equivalent but not floating-point identical. The upstream implementation confirms the multiplications. [OpenMS source](https://github.com/OpenMS/OpenMS/blob/develop/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp#L52-L66) | Normally **COORD** at ulp scale; potentially **SET** at a candidate tie/window boundary |
| [L845](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:845) | OpenMS uses `fabs(last.rt-first.rt)`. This subtracts without `abs`. It is equivalent only if slab frames are RT-ordered. | **SET** on unordered input |
| [L652](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:652), [L3001](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3001) | `toSlab()` preserves arrival order. The OpenMS path calls `wmap.sortSpectra()` at L3014, but the integer slab is never sorted. Normal loaders probably provide RT order, but the integer path does not enforce the same precondition. | **SET** if input frames are unordered |
| [L869](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:869) | With valley splitting disabled, reported m/z is the running search centroid, in which the apex has weight twice. OpenMS constructs a `MassTrace` and calls `updateWeightedMeanMZ()`, recomputing the ordinary one-apex weighted mean; `toTrace()` may instead select apex or median. | **COORD**, with downstream set consequences |
| [L870](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:870) | With splitting disabled, RT is the raw-intensity apex RT. OpenMS first calls `updateWeightedMeanRT()`, and the common `toTrace()` reads `getCentroidRT()`. | **COORD** |
| [L726](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:726), [L869](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:869) | `mz_est` is ignored inside detection. Consequently `trace:mz_estimator` is ignored whenever `split_valleys <= 0`; all three modes return `cmz`. | **COORD** |
| [L731](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:731) | OpenMS rejects an input map with fewer than three MS1 spectra. This function only rejects zero frames/peaks and can emit singleton traces from one or two frames. | **SET/behavior** |
| [L745](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:745), [L748](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:748) | OpenMS promotes the float intensity to double and compares it with the double threshold. This code rounds `noise` and `snr*noise` to float first. Normally harmless for integer thresholds, but not identical at a threshold boundary. | **SET** at the boundary |
| [L847](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:847), [L1441](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1441) | For `max_len_sec == 0`, integer tracing enables a zero-length maximum. The OpenMS wrapper only sets `max_trace_length` when `max_len > 0`, leaving OpenMS at `-1`. | **SET** for that configuration |
| [L3016](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3016) | `frame_aggregation_n > 1` transforms only `wmap`; in integer mode `wmap` is empty because `wslab` was already built. Thus the integer detector silently ignores the aggregation option. | **SET** |
| [L1564](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:1564), [L902](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:902) | The actual OpenMS tool branch skips EPD when there is exactly one input trace (`mts.size() > 1`), while the integer branch runs it for any non-empty input. The stated ground truth says EPD should run, so the integer behavior is more faithful, but the two selectable tool branches differ. | **SET** if the sole trace is multimodal |

What is now correct:

- The guard at [L813](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:813) matches OpenMS exactly.
- [L815](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:815) performs down before up, so up observes centroid/SD changes made by down.
- IM filtering occurs inside candidate search at [L790](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:790). Thus “closest” means closest among IM-compatible, above-noise peaks.
- The strict `<` at L792 gives the same first-in-m/z-order tie behavior.
- The visited test occurs only after the closest candidate is selected at L794. A taken closest peak causes a miss; it does not try the runner-up.
- The apex is logically double-counted at [L805](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:805)–808.
- SD is updated after centroid updates at [L828](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:828)–831.
- The next down/up search recomputes `centroid ± 3*sd`. OpenMS likewise does not retroactively reject the just-accepted peak after SD shrinks.
- `total` is correctly `down.scan_counter + up.scan_counter + 1` at [L848](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:848). OpenMS then subtracts the two final consecutive-miss counts. [OpenMS source](https://github.com/OpenMS/OpenMS/blob/develop/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp#L598-L605)
- The defensive clamp at L849 is unreachable under normal counters because misses cannot exceed scans; it does not change behavior.
- Within one invocation, peaks are marked visited only after validity at [L851](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:851).
- The descending sort at L754–756 is equivalent to stable ascending sort followed by reverse iteration: equal-intensity apices seed in later-input-index-first order.

## 2. Bin/m/z round trip

The window-edge implementation itself does not have an obvious off-by-one error.

For a monotone calibration, `round(tofOf(lo_mz))` is never greater than the first integer bin at or above the lower m/z bound. It either begins at that bin or one bin earlier; [L789](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:789) removes the extra one. The upper edge is checked using the reconstructed m/z at L788, with equality admitted. Therefore exact integer-bin input receives the intended inclusive `±3sd` window.

The loss occurs earlier:

- [L603](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:603) quantizes a picked centroid to `1e-5 Da`.
- [L674](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:674) then rounds that centroid to an integer TOF bin.
- The reference OpenMS path instead traces the `1e-5 Da` value directly at [L958](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:958).

The comment that this “recovers the ORIGINAL bin exactly” is not generally true. `PeakPickerIM` can calculate an m/z apex by spline interpolation, so a picked centroid need not lie on a raw integer-bin center. [OpenMS PeakPickerIM source](https://github.com/OpenMS/OpenMS/blob/develop/src/openms/source/PROCESSING/CENTROIDING/PeakPickerIM.cpp#L505-L588)

Rounding can therefore:

- move a peak across an inclusive `±3sd` edge;
- swap which of two peaks is closest;
- collapse distinct picked centroids onto one bin;
- perturb the centroid and robust SD, which affects subsequent frames.

That is a genuine **SET** difference, although usually confined to peaks near decision boundaries.

Reattachment after EPD is estimator-dependent:

- `apex`: with a unique RT-to-frame mapping, [L929](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:929) selects the actual apex peak m/z, and [L934](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:934) should recover that apex bin.
- `mean`: there is no measured “right bin” for an intensity-weighted mean. L934 fabricates the nearest bin under the apex frame’s calibration, so exported m/z differs from `t.mz` by up to half a bin.
- `median`: likewise, unless the median is literally one member peak and its calibration matches the apex frame.

Also, `b_of_rt` at [L905](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:905) is a one-value map. Two frames sharing one global RT index overwrite each other, potentially attaching the wrong factor.

There is an additional mzPeak-specific danger: `frameIdOf()` treats `mzpeak=<archive index>` as a vendor Frames.Id at [L568](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:568). The mzPeak reader writes the archive index, while its exact calibration separately knows the actual metadata frame ID. If those are not identical, [L670](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:670) uses the wrong temperature factor. Missing/out-of-range IDs silently fall back to the reference factor at [L473](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:473), despite the “fail closed” comments. That can be both **COORD** and **SET**.

## 3. Valley splitting

The premise in the question describes an earlier snapshot. The current live file no longer gives every peak `t.mz`: it now stores per-point TOF in `Trace::xt` at [L247](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:247), populates it at [L864](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:864), and reconstructs each peak’s m/z at [L911](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:911)–917.

That change was necessary.

EPD’s segmentation does not materially use per-peak m/z. Smoothing, extrema discovery, valley depth, and width decisions use RT and intensity; m/z is recomputed only for the resulting subtrace coordinates. [OpenMS EPD source](https://github.com/OpenMS/OpenMS/blob/develop/src/openms/source/FEATUREFINDER/ElutionPeakDetection.cpp#L348-L506)

Therefore, in the old same-m/z implementation:

- valley locations and the number/profile of split traces were unchanged;
- `apex`, `mean`, and `median` all collapsed to the same inherited `t.mz`;
- `mean` was the full unsplit running centroid, not the subtrace mean;
- `apex` was not the apex peak m/z;
- `median` was not a median.

The current `xt` implementation fixes that estimator collapse relative to the integerized peaks. Residual differences from OpenMS remain because those per-point values have already undergone the m/z→TOF→m/z rounding described above, and mean/median are re-encoded into a synthetic apex-frame bin at L934.

With splitting disabled, none of this repair runs; the estimator remains ignored and L869’s double-seed running centroid is returned.

## 4. Banding

The band cores cover the full TOF range without gaps, but semantic ownership is not shared.

Each call creates its own `visited` array at [L759](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:759). A band restricts only seeds at [L750](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:750); extension can inspect every peak in the slab. The results are concatenated at [L3065](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3065).

Consequences:

- A trace whose accepted peaks cross a core boundary can be seeded independently on both sides and emitted twice.
- The two versions need not be identical duplicates. Their different seeds and interleaving histories can choose different competitors, centroids, SDs, termination points, and apexes.
- A cross-band peak that global OpenMS would already have marked visited remains available. Accepting it can divert another trace, cause an overlength/quality rejection, or prevent a trace that global greedy ownership would have produced. Thus the error is not only additive duplication; traces can also be altered or lost.
- Ownership is effectively by seed core, whereas the OpenMS halo implementation retains by final centroid core.
- Raw output order becomes band order rather than global apex-intensity order (**ORDER**), although the later canonical sort at [L3096](/Users/kohlbach/Claude/speXtractor/src/DIAPseudoSpectra.cpp:3096) removes that downstream.

The error is not formally bounded to a fixed number of bins around a boundary. Dynamic SD can widen and a running centroid can walk from frame to frame; there is no drift cap. A constructed trace can cross several cores and be duplicated by as many as the number of bands. The only hard bounds are the window and band count. For stable real ions, the practical affected region will usually be a few bins around each core edge, but that is an empirical observation, not an algorithmic guarantee.

Accordingly, the comment at L3043–3045 that the “one approximation” is duplicate taking is too strong.

## 5. Test that would have caught the first version

Use a direct differential test of `detectTracesInteger_`, not the full peptide-assembly executable.

Construct an unbanded `PeakSlab` with 20 RT-ordered frames at one-second intervals:

- Target peak: one fixed TOF bin, fixed IM, intensity `100`.
- Distractor in every frame: far outside the target m/z window, same or different IM, intensity `50`.
- `noise=10`, `snr=3`, `min_len=0`, `min_sample_rate=-1`, `max_len=-1`, `mass_ppm=15`, `im_tol=0.01`.
- Give the target a unique highest apex, e.g. intensity `200` in frame 15.

Two cases:

1. Remove the target only from frame 10. Assert exactly one trace contains all 19 target points.
2. Remove it from frames 7–13 inclusive. The above-noise distractor keeps those spectra non-empty, so they are real misses. Assert exactly two target traces exist, containing frames 0–6 and 14–19 respectively.

Also run the same constructed spectra through OpenMS and compare trace membership, not merely emitted peptide count.

The seven-gap assertion would have failed the first implementation because it lacked OpenMS’s `>5` consecutive-outlier termination and would bridge or reject the wrong span. The one-gap assertion catches premature termination.

The newly added test in [test_spextractor.py](/Users/kohlbach/Claude/speXtractor/test/test_spextractor.py:19) does not test the integer implementation: it explicitly exercises only the default OpenMS detector. The command at [L118](/Users/kohlbach/Claude/speXtractor/test/test_spextractor.py:118) never passes `-trace:detector integer`, and its trace-count assertion examines MS1 traces, while integer tracing is currently used only for MS2. A synthetic mzML cannot enable it because the implementation demands external TDF calibration. A test seam accepting a synthetic `PeakSlab`/calibration is therefore required.

Bottom line: the catastrophic first-version deviations are mostly fixed, but this rewrite is not faithful yet. For the running benchmark, a substantial deficit should first be triaged by:

1. one band versus many bands;
2. `.d` versus mzPeak input/frame-factor mapping;
3. per-peak m/z→TOF residuals and candidate flips;
4. counts of frames that are raw-nonempty but empty after the noise threshold;
5. splitting enabled versus disabled, especially estimator output.

I would not attribute any remaining peptide difference solely to harmless integer rounding until those are separated.