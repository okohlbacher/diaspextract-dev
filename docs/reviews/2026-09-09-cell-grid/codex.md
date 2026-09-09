**The cell detector and current rebasing look sound. The unconditional output-exactness bound still has counterexamples downstream.** These are static-review conclusions; I did not run the data gates or modify files.

1. **Detection exactness: fine, with explicit preconditions.** [sliceFrames](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:917) preserves frame entries, peak order, calibration and RT indices. Subtracting the same `p0` from every peak index preserves the descending-index tie-break. `frame_live`, visited claims, centroid/SD initialization and extension decisions depend only on that cell and frozen parameters. `min_len_sec` uses actual RT differences; MSR uses frame counts.

   **TOF geometry is also fine.** [buildTofIndex](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1022) changes the search accelerator with `P/F`, not the result. Bucket bounds bracket the full-frame `lower_bound`; returning the restricted range’s end is valid because the subsequent scan continues to the **frame** end. This requires sorted TOFs and frozen bounds enclosing all peaks. I found no detector counterexample under those preconditions.

2. **Blocker to the universal bound — splitting still depends on the resident parent count.** [src/spextractor.cpp:1305](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1305)

   Cell A contains one double-lobed parent; its complete neighboring cells contain no parents; distant cell B contains another parent. Whole-window execution sees two parents and splits A. A probe/tile containing A and its neighbors sees one and returns it unsplit through `in.size() < 2`.

   This guard predates the commit, but makes “splitting is per parent” conditional. Real-data impact is unlikely in dense 300/600-second DIA cells, plausible for sparse windows or stringent thresholds. A normal dense-data gate can pass while this remains broken. Splitting eligibility must be identical across resident sets.

3. **Rebase: fine. Ordering has a separate exactness hole.** [src/spextractor.cpp:4203](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4203)

   `frame0` and `bframe` are the absolute store-local frame fields; both are rebased. `apex` and signed `rt_at` are relative and correctly remain unchanged. `absorb()` rebases arena offsets, keeps bins parallel to intensities, and preserves bin deltas relative to unchanged `t.tof`. Splitting subsequently uses the correct window tables.

   **Blocker to unconditional byte identity — the canonical fragment sort is not total.** [src/spextractor.cpp:4295](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4295)

   Two cross-band traces can share `(im, mz, rt, apex intensity)` but have different tails. Omitting unrelated cells can change their relative order under `std::sort`. If both export the same m/z, raw intensity is 10,000, and correlations are 0.5 and 0.8, default weighting emits intensities 2,500 and 6,400. The m/z-only `sortByPosition()` preserves their relative order; the final spectrum sort cannot repair the internal peak sequence.

   Exact ties should be rare, but quantization and cross-band claims make them plausible; no measured occurrence was established here. This is pre-existing, but **not necessarily tile-independent**, as the judge assumes. A persistent origin tie-break or content-based total order closes it.

   The [top-500 comparator](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3044) handles unequal scores/masses deterministically. Its index tie matters only when tied candidates have different emitted payloads; interchangeable identical peaks are harmless. The counterexample above does not require reaching the cap.

4. **Should-fix verification — the fragment digest cannot establish the requested identity.** [src/spextractor.cpp:810](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:810)

   It hashes only five scalars per trace, then sorts **all scalar words together**, losing tuple associations. Changing a non-apex intensity, support frame, bin or calibration can alter scoring/export while preserving this digest. Even swapping scalar associations between traces can pass. It is logged after splitting/trimming, not over parent/band-store contents.

   The [ordered slab digest](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:884) remains meaningful for input identity, but is computed before slicing and contains global RT indices that the probe rebuilds. Whole versus cropped digests are therefore not directly comparable.

   Real impact: precisely the slice/rebase defects this gate is intended to catch could escape. A cell comparison needs complete parent records and ordered profiles/bins, with frame identities normalized and arena offsets interpreted relative to their own stores.

5. **Note — `-1` preserves numerical operations, but not literally the old path or accounting.** [src/spextractor.cpp:4175](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4175)

   For ordinary multiple-band execution: same slab, same preparation, same detector calls, same band merge order, same reserves, and zero frame rebase. Both slab and preparation still disappear before destination arena reservation. I found no numerical difference.

   For `nb == 1`, the old code moved detector output directly into `frag_traces`. The new code retains it in `per[0][0]`, reserves another vector, and transfers every record: approximately **40 bytes × parent count** of additional transient allocation. This can matter on real large single-band runs; capacity accounting also changes, especially with splitting disabled.

   Preparation now dies before slab release; `w_merge` starts after release instead of before; the merge log gains `1 cell(s) x`; single-band timings change. Finally, [the two unconditional header fields](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4549) prevent literal historical file-byte identity. The identity contract must explicitly mean spectrum data with provenance differences exempted.

6. **Should-fix — odd frame pitches mishandle the half-cell remainder.** [src/spextractor.cpp:3399](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3399)

   With `n=5` and seven MS1 frames, the remainder is two frames: less than 2.5, so it should join the preceding cell. Integer `n / 2` is two, making `2 < 2` false. The implementation retains an extra short cell and changes detection.

   This affects real runs whenever `n` is odd and the remainder equals `floor(n/2)`; it is not merely malformed-input behavior.

   **Other edge handling is fine:** [lower_bound and the cut guard](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4143) assign all frames exactly at an edge to the right cell, including duplicate times. Skipping repeated cut offsets removes empty cells without joining populated cells across a boundary.

   **Note — probe upper endpoints differ.** [src/spextractor.cpp:1471](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1471) retains `rt == hi`, whereas cells/core selection are half-open. An MS2 frame exactly at the upper boundary introduces a partial next cell and potentially extra boundary fragments. Native diaPASEF avoids the equality described in the question; synthetic/converted inputs need an explicit half-open convention.

7. **Note — the probe can pass while a tiled reader still differs.** [src/spextractor.cpp:4110](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4110), [1690](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1690), [2849](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:2849)

   Currently `wst` remains slab-derived, `used` remains surviving-fragment-derived, and `nearest_local` remains resident-support-derived. Injecting `G` fixes only the denominator. A precursor whose retained MS1 profile extends outside resident support loses or remaps points, changing normalization even when its candidate fragments are identical.

   Complete neighboring cells can conceal this at ordinary pitches because they also cover the core precursors’ MS1 profiles. Their success would support the tested core calculation, not prove every parent/profile identical or validate future reader behavior.

   The later implementation must preserve:

   - **Detection inputs:** complete cells, exact peak bits/order, calibration, and the same empty frame entries. Five frames with signal only in frames 0 and 4 give MSR `2/5`; dropping the three empty frames gives `2/2`, changing acceptance.
   - **Frozen geometry/scalars:** boundary list, window membership, frame times/calibration, band count and edges, thresholds and scan time. Rebase onto the frozen window table; if that table inserts frames absent from the detection slice, spans need corresponding zero slots rather than just an offset.
   - **Scoring support:** identical `G`, `used` policy and `nearest_local`, full precursor profiles, and complete carried child profiles/calibration. `G_live == F` is insufficient: above-noise peaks can fail seeding or trace validity and contribute nothing to `used`.
   - **Ownership/output:** carry-over, precursor deferral, first/last-tile handling and final flushing, with each precursor emitted once and equal-key ordering resolved.
   - **Pass 1:** identical per-cell MS1 detection in both modes, followed by the same global inference. The whole-MS1 probe exercises none of that change.
   - **Picking:** identical picked cell arrays despite reader batching, plus raw neighbor frames when native aggregation is enabled. The probe deliberately filters only **after** picking.

8. **Should-fix — two qualifications are missing from “any pitch/threads.”**

   At [src/spextractor.cpp:3847](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3847), auto bands with 28 windows resolve to one band at eight threads and four at 100. Independent `visited` sets then change claims. This can bite real data in auto mode; explicit 12 bands avoids it. Freeze the **band count**, not only `tlo/thi`.

   At [judge.md:10](/Users/kohlbach/Claude/speXtractor/docs/reviews/2026-09-09-bounded-parents-design/judge.md:10), previous-cell-only carry does not cover arbitrary pitches: when cells are shorter than `2*delta_rt`, the required retention interval spans multiple predecessor cells. Carry must accumulate transitively and expire by RT, or the pitch/gate relationship must be constrained. This is relevant to supported small-pitch/large-gate settings, not 600-second cells with the default gate.

9. **Should-fix — the science bound is stronger than the code supports.** [judge.md:21](/Users/kohlbach/Claude/speXtractor/docs/reviews/2026-09-09-bounded-parents-design/judge.md:21)

   Even isolated signal wholly inside a cell can change validity: three signal frames followed by seven empty frames fail whole-window MSR (`3/10`) but pass a five-frame cell (`3/5`). Empty frames increment scans without incrementing misses. No accepted signal membership crosses the cut. This is plausible in sparse/high-threshold windows, less likely in the measured dense windows.

   Likewise, uniform peptide loss does not prove an unfrozen scalar: background re-segmentation can alter interior spectra and downstream thresholds. The [measured cause-3 result](/Users/kohlbach/Claude/speXtractor/docs/BASELINE.md:2618) supports that mechanism. Identical MS1 cut times also cannot guarantee unchanged isotope inference: a weak isotope segment can fall below minimum length while its mono survives. These qualify the science claims, not same-grid detector purity.

10. **Cost: mostly reasonable; no 13× preparation multiplier.** [src/spextractor.cpp:4162](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4162)

    Memory retains the whole slab, all completed cell stores/records, and one current slice/preparation/visited set. Merge still reserves the complete destination. Cells partition input points, so this is not 13× arena storage, but it remains whole-window memory; extra records and allocation slack depend on the changed parents. The slice adds roughly 10 bytes per current-cell peak, offset partly by smaller preparation/visited structures.

    Linear preparation scans sum to the original peak count; sorting becomes `Σ N_cell,band log N_cell,band`; index work is `Σ F_cell × buckets_cell`. Added costs are copying every slab peak once, allocations and task joins. **Note:** slice copying occurs before the preparation timer, so the detailed timers omit that cost from slab/prep/detect, though enclosing trace time includes it.

    Cells are sequential within each window because each taskloop joins. Twenty-eight ready windows supply up to 336 detector-band tasks, enough for 100 workers; fewer than nine ready windows can underfill detection, and the last window repeatedly exposes at most 12 band tasks. There is no new team explosion. The earlier probe’s [occupancy measurements](/Users/kohlbach/Claude/speXtractor/docs/BASELINE.md:2473) justify benchmarking the tail rather than inferring wall time from CPU savings.
