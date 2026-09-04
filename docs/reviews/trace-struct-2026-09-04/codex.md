# Verdict

The redesign is not sound as written. Dense window-local storage is viable, and most of the memory win is real, but this is not yet a pure representation change. Four claims fail:

- `rt`, `mz`, and `im` are not all derivable with the proposed semantics.
- Missing-frame zeros are not semantically invisible.
- The MS1-to-MS2 nearest-frame lookup cannot use either side’s local index directly.
- `FragGrid.flat` can disappear, but the grid’s real-frame mask, `G`, nearest-frame mapping, and per-fragment normalization cannot simply disappear.

## 1. Is “one degree of freedom” true?

Only conditionally.

### OpenMS traces

OpenMS MassTraceDetection collects at most one peak per input spectrum: it selects one candidate from each spectrum and prepends/appends it to the trace. Therefore irregularly skipped spectra can be represented as a dense span with holes. [OpenMS MassTraceDetection](https://github.com/OpenMS/OpenMS/blob/develop/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp#L347-L401)

But conversion is safe only if:

1. `toTrace()` receives the exact MS1/window frame table, not merely the global RT axis.
2. Every MassTrace point maps to exactly one entry in that table.
3. Local frame indices are strictly increasing and unique.

Current `toTrace()` maps RT to a deduplicated global axis and sorts the resulting pairs ([lines 297–318](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:297)). A local dense representation cannot distinguish two source spectra with the same RT. Add a construction-time assertion for strict local-frame uniqueness, or retain a true source-spectrum identifier.

More seriously, the claimed scalar accessors are wrong:

- Current OpenMS `rt` is `mt.getCentroidRT()`, not apex RT ([line 307](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:307)). The proposed apex lookup at [design line 61](/Users/kohlbach/Claude/speXtract/docs/TRACE-STRUCT-REDESIGN.md:61) changes RT sorting, RT gates, precursor RT, and output spectrum RT.
- Current `mz` supports apex, median, and weighted-mean estimators ([lines 303–306](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:303)). OpenMS traces explicitly have no authoritative TOF bin ([lines 238–243](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:238)). One `tof` cannot reproduce those modes.
- Current `im` is a double centroid ([line 308](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:308)). Quantizing it again to `uint16_t imq` changes its bits and can move borderline IM gates.

Thus “all doubles are derivable” at [design lines 9–22](/Users/kohlbach/Claude/speXtract/docs/TRACE-STRUCT-REDESIGN.md:9) is false. Intensity and integer-path apex calibration are derivable; the other scalars need exact recomputation matching OpenMS or exact cached storage, possibly in SoA arrays.

### Valley splitting

The sub-span claim is true for EPD itself. EPD walks the input MassTrace in order and copies consecutive ranges between minima; it does not merge traces, reorder points within a child, or synthesize new points. It may drop a trace with no maxima, and parallel output order may vary, but every emitted child’s point sequence is contiguous within its parent. [OpenMS EPD splitting](https://github.com/OpenMS/OpenMS/blob/develop/src/openms/source/FEATUREFINDER/ElutionPeakDetection.cpp#L348-L506)

For a gapped dense parent, a child can therefore be represented as:

```text
frame0 = first child point’s local frame
off    = parent.off + (frame0 - parent.frame0)
len    = last child point’s local frame - frame0 + 1
```

But EPD must be given only real points. Giving it dense padding changes average cycle time, smoothing, extrema, and split positions.

### `xt` and EPD

The document’s statement is half-true in the dangerous way.

EPD’s split decision uses RT and intensity, not m/z. But when it emits a child it calls `updateWeightedMeanMZ()` and `updateWeightedMZsd()`. Afterwards this code’s `toTrace()` uses the child’s per-point m/z for apex or median estimation, or its recomputed centroid for mean estimation. [EPD lines 487–495](https://github.com/OpenMS/OpenMS/blob/develop/src/openms/source/FEATUREFINDER/ElutionPeakDetection.cpp#L487-L495), [local lines 303–306](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:303).

Current integer conversion deliberately supplies each point’s individual TOF-derived m/z ([lines 1011–1017](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1011)), then chooses the child’s apex and calibration ([lines 1034–1039](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1034)). A trace’s points are merely within tolerance; their TOF bins are not constant ([lines 940–949](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:940)).

Consequently:

- A child that excludes the parent apex generally needs a different TOF bin.
- `median` and `mean` require all child point m/z values.
- `same tof` in [design line 90](/Users/kohlbach/Claude/speXtract/docs/TRACE-STRUCT-REDESIGN.md:90) cannot reproduce current output.

A workable solution is a temporary dense arena of slab peak indices through EPD. Peak index yields exact intensity, TOF, IM, and frame. After splitting, materialize the final float arena and exact child scalars, then discard the temporary index arena.

## 2. Zero-padding semantics

The assertion that every consumer already ignores zeros ([design lines 34–40](/Users/kohlbach/Claude/speXtract/docs/TRACE-STRUCT-REDESIGN.md:34)) is false.

| Computation | Effect of padding | Required preservation |
|---|---|---|
| Fragment `dot` | A zero contributes numerically nothing, but should not be visited as support. | Skip missing fragment entries. Preserve chronological order of nonzero additions. |
| `overlap` | Changes: current code increments for every stored fragment point whose precursor slot is nonzero ([lines 2157–2164](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2157)). A padded fragment zero would falsely increment it. | Require both points present; skip fragment padding. |
| Precursor `touched` | Changes even without smoothing: a zero point can be appended to `touched` because the code tests the previous `pdense` value before adding `pval` ([lines 2114–2121](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2114)). | Skip missing precursor entries before lookup or addition. |
| `psum`/`psumsq` | Raw sums are unchanged by zero, but `touched.size()` changes union-support variance. Smoothed values change substantially. | Build `touched` from real points only. |
| `fsum`/`fsumsq` under `var_support_` | Sums unchanged, support cardinality changed because current `supEnd-supBegin` is the number of real points ([lines 2181–2186](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2181)). | Count nonmissing fragment entries, not `len`. |
| `fg.mean`/`fg.invnorm` | Sums remain equal only if padding is skipped, but the denominator `G` also has to remain identical ([lines 1352–1363](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1352)). | Skip padding and preserve old `G`. |
| `G` | Changes if “grid = full window sequence.” Current `G` is the union of frames touched by real fragment points ([lines 1306–1317](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1306)). | Retain a per-window real-fragment-frame bitset and use its population count. |
| Sample-rate test | Unchanged only because it currently executes before storage construction ([lines 923–932](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:923)). | Continue using real-point count divided by adjusted visited frames; never substitute `len`. |
| `atrousLevels` | Changes: padding replaces the median interval between observed points with the regular frame interval and changes the `<5` test ([lines 1279–1296](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1279)). | Iterate real points and compute RT gaps between successive real points. |
| FWHM | Changes drastically: the first missing frame becomes an artificial zero crossing, narrowing the peak. Both implementations assume adjacent stored entries are observed points ([lines 2647–2665](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2647), [lines 2843–2865](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2843)). | Run over a sparse/presence-filtered iterator, interpolating between successive observed points exactly as today. |
| Wavelet input | Changes: current smoother runs over the packed observed sequence ([lines 2104–2111](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2104)). Inserting zeros changes length, neighborhoods, mirrored edges, and every smoothed intensity. | Pack real intensities into the same order before `atrousSmooth`, then map results back only to their original real frames. |
| `xicCorr` | Changes: current Pearson counts only frames present in both traces ([lines 1750–1762](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1750)). Counting padded coincidences changes `m`, means, covariance, and the `m >= 3` guard. | Intersect spans, but accumulate only where both entries are present. |
| EPD smoothing/splitting | Changes if zeros become MassTrace peaks. EPD derives scan time and applies Savitzky–Golay smoothing to the supplied point sequence. | Construct MassTrace from real points only. |

A zero sentinel is adequate only while observed intensities are guaranteed strictly positive. For a robust general representation, carry a presence bitmask or use a peak-index sentinel. In either case `np()` must remain “number of observed points,” not `len`.

`FragGrid.flat` and its per-fragment offset vector can disappear. The used-frame mask, `G`, nearest-frame map, `mean`, and `invnorm` remain semantically necessary.

## 3. Window-local versus global frames

Current correctness comes from one global, deduplicated RT index shared by MS1 and MS2 ([lines 2578–2591](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2578)).

Three cases differ:

- Isotope `xicCorr` is MS1-to-MS1. Window-local indexing is safe because both traces use the same MS1 frame table.
- Fragment-to-fragment work occurs within one isolation window. Local indexing is safe.
- Precursor-to-fragment scoring is MS1-to-MS2 and is not safe under direct local indexing.

The current lookup is:

```cpp
fg.nearest_slot[p_tr.xi[pi]]
```

where `p_tr.xi[pi]` is a global frame/RT key ([line 2119](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2119)). An MS1-local index and an MS2-window-local index with the same integer value do not denote the same time.

The replacement must be one of:

```text
ms1 local
  -> ms1_rt_index[local] / actual RT
  -> nearest real fragment frame in this window
  -> fragment-window local index
```

or a precomputed per-window table:

```cpp
nearest_frag_local_by_ms1_local[ms1_frame]
```

Tie-breaking must remain “later fragment frame on equal distance,” matching [lines 1331–1338](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1331).

No XIC alignment crosses two MS2 windows, but the same MS1 precursor may be scored in a window task, so the mapping must be computed separately for each window.

Finally, a bare `Trace` no longer identifies which frame table interprets `frame0`. Either use distinct `MS1Trace`/`FragmentTrace` types or require all accessors to receive an explicit frame-table context.

## 4. Arena and task-pool sequencing

The safe sequence is exact:

1. Each detector band writes only its own `vector<Trace>` and private arena. Its `off` values are band-local.
2. The detection `taskloop` must complete.
3. Compute band arena prefix sizes.
4. Allocate the final window arena once.
5. Copy/move each band arena to its assigned range and add that band’s base to every trace offset.
6. Concatenate trace records in deterministic band order.
7. Run chunked EPD tasks against the now immutable final arena.
8. Each EPD task writes only its private `parts[ci]`; children store rebased absolute offsets into the immutable arena.
9. Wait for all EPD tasks.
10. Concatenate and canonically sort child records. Sorting records is safe because offsets are absolute.
11. Build the used-frame mask, normalization arrays, and scalar SoA arrays.
12. Start scorer tasks only after all arena growth and rebasing has ended.
13. Destroy the arena and frame/calibration tables only after the scoring taskgroup joins.

Existing taskloops have the required implicit taskgroup barrier because they do not use `nogroup`: band results are consumed after [lines 3188–3198](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:3188), and EPD parts after [lines 999–1047](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:999). Preserve that property explicitly.

Two additional hazards are missing from the proposal:

- The integer path currently frees `wslab.b` before sorting and scoring ([lines 3202–3206](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:3202)). The proposed `mz`/`b` accessors require it to remain alive.
- A 32-bit `off` needs `final_arena.size() < 2^32` asserted before conversion. Relaxed sample rates can make dense arenas far larger than the design assumes.

No reader may observe an offset before rebasing, and no scorer may run while any task can resize the arena.

## 5. Arithmetic

The current trace record is 120 bytes. At 10.7 real points:

```text
tracked current = 120 + 12 × 10.7 = 248.4 B/trace
allocator estimate = 3 × 16 = 48 B/trace
resident estimate = 296.4 B/trace
```

The 35.6 GB ledger did not include allocator headers: `memAdd` counts vector capacities plus `sizeof(Trace)` only ([line 954](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:954)). Therefore scaling 35.6 GB by `74/296` mixes incompatible denominators.

The proposed C++ struct is not normally 18 bytes. Its alignment is four, so `sizeof(Trace)` will ordinarily be 20 bytes. Eighteen requires packing or SoA storage.

There is no measured gap distribution in the proposal. Using a clearly labeled planning estimate of 75% occupancy:

```text
estimated span = 10.7 / 0.75 = 14.27 frames
new = 20 + 4 × 14.27 = 77.1 B/trace
```

At the document’s assumed span of 14, it is 76 bytes, not 74.

That gives:

```text
296.4 / 77.1 = 3.84× including assumed allocator metadata
248.4 / 77.1 = 3.22× against the measured ledger accounting
35.6 GB × 77.1 / 248.4 ≈ 11.0 GB
```

The claimed 9 GB is unsupported.

The default 2× span bound is valid for accepted integer traces, but only at sample rate `r = 0.5`. The adjusted visited count is at least the span between first and last accepted points, so:

```text
span <= adjusted <= floor(real_points / r)
```

Therefore the general bound is:

```text
padding factor <= 1/r
new bytes <= 20 + 4 × min(F, floor(N/r))
```

At default `r=.5`, 10.7 points imply a worst-case average bound near 21.4 spanned frames and approximately 105.6 B/trace. Scaling the measured ledger gives about 15.1 GB, not under 12 GB.

For configured `r=.3`, the bound is 3.33×; for `.1`, 10×; for `r=0`, there is no sample-rate bound and the worst case is the entire approximately 1,400-frame window. The unconditional “at most 2× padding” statement at [design lines 34–38](/Users/kohlbach/Claude/speXtract/docs/TRACE-STRUCT-REDESIGN.md:34) is therefore wrong.

## 6. What else should go?

- Keep `off` unless storage is reordered after the final canonical trace sort. MS1 traces are sorted by m/z/RT/IM before greedy inference ([lines 2740–2749](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2740)); fragments are sorted by IM/mz/RT before binary-search slicing ([lines 3227–3235](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:3227)). Keeping arena order would require a 4-byte permutation index, merely replacing `off`. Copying profiles into final sorted order could eliminate `off`, but forfeits the no-copy child-span advantage and creates a transient arena.
- Drop `imq` from final MS2 records after exact `frag_im` has been materialized. Fragment IM is then read from the persistent SoA for sorting/gating; it is not exported. This saves 2 B/fragment. It requires building the SoA before discarding the centroid and preserving the current double value, not re-quantizing it.
- Keep `apex` unless exact scalar SoA arrays for intensity, TOF, calibration, and any apex-based value are materialized first. Scanning 10–20 floats repeatedly during sorting, isotope inference, gating, and emission is a bad exchange for two bytes.
- Drop `tof` from MS1/OpenMS trace records: MS1 currently comes through `detectTraces_`, and OpenMS traces use `tof == 0` fallback semantics ([lines 2300–2306](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2300)). Separate MS1 and integer-fragment record types would avoid paying four useless bytes on every MS1 trace.
- Drop `len` only if an offsets/prefix array is retained; that saves nothing overall and damages random access.
- Delete `FragGrid.flat` and `FragGrid.off`, but retain compact metadata equivalent to used-frame mask, `G`, nearest-MS1 mapping, `mean`, and `invnorm`.

## 7. The falsifier

Byte-identical spectrum output is achievable for an arena-only representation change. Arena concatenation does not inherently change floating-point order: each trace’s nonmissing values can still be visited chronologically, and all sums can occur in the same sequence.

It is not achievable with the design as currently specified because it deliberately changes:

- centroid RT into apex RT;
- double IM into a re-quantized centroid;
- per-child TOF/m/z into the parent’s TOF;
- sparse smoothing into zero-padded smoothing;
- sparse `xicCorr` overlap into dense-span overlap;
- `G` from the real fragment-frame union into the full window frame count.

The existing internal trace digest is insufficient: it hashes only `mz`, `rt`, and `intensity`, and is order-insensitive ([lines 614–634](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:614)). Use staged falsifiers:

1. Exact trace count and exact ordered tuples of local frame plus intensity bits before EPD.
2. Exact EPD child boundaries and exact scalar bits after EPD.
3. Exact used-frame mask, `G`, means, and inverse norms.
4. Exact emitted precursor metadata and fragment membership.
5. The existing spectrum-list SHA-256 comparison, which hashes the serialized spectrum section ([test lines 170–177](/Users/kohlbach/Claude/speXtract/test/test_spextract.py:170)).

If the team intentionally accepts re-quantized centroids or altered normalization, it must stop calling the work pure representation. The replacement gate should then require exact spectrum count, precursor identity/charge, and fragment membership, with numeric comparisons bounded separately—ideally exact intensity bits and at most one ULP for recomputed doubles. Any gate threshold crossing is a set change and should fail.

The redesign is salvageable, but not approved in its current form. The riskiest assertion is “the grid IS the window’s frame sequence” at [design line 79](/Users/kohlbach/Claude/speXtract/docs/TRACE-STRUCT-REDESIGN.md:79); implemented literally, it silently changes every Pearson score through `G` while still producing plausible-looking output.