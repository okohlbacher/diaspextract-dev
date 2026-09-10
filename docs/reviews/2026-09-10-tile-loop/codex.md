Reviewed `1e7dcb1` against `a91cfcf`. **G1 has concrete counterexamples.** The later README-only HEAD change leaves the reviewed files unchanged. Validation was source analysis and in-memory numerical/digest probes; the cluster matrix and search gates remain unverified.

1. **must-fix — Rounded ownership/carry boundaries can omit eligible fragments.** [src/spextractor.cpp:4789](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4789), [src/spextractor.cpp:4859](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4859).

   Two reproduced double-arithmetic counterexamples use the default `delta_rt=3`:
   
   - Edge `T=7.2`, precursor `4.2`, fragment `1.2`: ownership includes the precursor after the edge; `abs(4.2-1.2)==3` accepts the fragment. Carry drops it because `7.2-6 == 1.2000000000000002`.
   - Edge `T=3.1`, precursor `0.1`, fragment exactly `3.1`: `0.1 < 3.1-3 == 0.10000000000000009` assigns the precursor before the edge, yet `abs(3.1-0.1)==3` accepts the fragment, which is detected only afterward.

   **Fix:** derive ownership and retention using the scorer’s actual boundary predicate, or proven conservative rounding. Add both boundary regressions. The real-number proof alone is insufficient.

2. **must-fix — Per-tile sorting can reverse spectra with distinct serialized metadata.** [src/spextractor.cpp:1831](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1831), [src/spextractor.cpp:4354](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4354).

   Windows A=`[490,510]` and B=`[495,515]` can emit identical RT, precursor m/z `500`, charge and peaks, but different isolation offsets: `10/10` versus `5/15`. `canonicalSort_` considers them equal. Arrange nontraceable peaks so whole-run sizes order A before B, while the emitting tile orders B before A. With two emitted spectra, the sorts retain those opposite input orders, changing spectrum bytes and IDs.

   **Fix:** complete the comparator with every varying serialized field, including isolation offsets, precursor IM and inference metadata. Add this overlapping-window case and rerun G0. The incomplete comparator predates HEAD; tile-specific window ordering exposes it.

3. **must-fix — The fragment “content-total” comparator still omits the profile.** [src/spextractor.cpp:4715](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4715).

   Profiles `[1,10,1]` and `[2,10,2]` can share all compared fields: IM, apex m/z, reported RT, apex intensity, point count, length and starting frame. Adjacent bands’ independent `visited` sets can produce such traces by sharing an apex and following different flank peaks.

   They score differently: with frozen `G=10` and precursor `[1,10,1]`, correlations are `1` and approximately `0.9909193`. Changing the surrounding fragment set can reorder these equivalent records under `std::sort`. The stable final m/z sort preserves their differing intensity order, changing bytes even below the 500-fragment cap.

   **Fix:** add lexicographic profile samples and export-relevant fields to the tie-break, then verify G0.

4. **should-fix — K=1 now retains the entire MS1 scoring state through sorting and writing.** [src/spextractor.cpp:4888](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4888), [src/spextractor.cpp:4914](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4914).

   The parent released MS1 traces, spans and precursors before output concatenation/sorting/writing. HEAD performs all those output allocations first. A large one-tile run therefore holds the full scoring state alongside spectrum permutations and writer buffers, weakening the required memory reference.

   **Fix:** release the MS1 structures immediately after the last tile’s parallel region joins, before constructing its output block. Also guard Fix-A with `tiles.size()==1`: its current counter fires on the first tile of a multi-tile run too.

5. **should-fix — A failed tile can replace a complete destination with an apparently complete partial run.** [src/spextractor.cpp:4301](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4301), [src/spextractor.cpp:4883](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4883).

   Opening the writer truncates the destination before any tile succeeds. If a later window throws, destruction patches the completed-prefix count and writes its index/footer. The resulting file can pass structural invariants while containing only earlier tiles. The parent opened the writer after all window computation succeeded.

   **Fix:** write to a sibling temporary file, explicitly finalize/check it after successful completion, then rename. Destructor object lifetimes are safe; publication of partial results is the problem.

6. **must-fix — Check 16 exercises only one nonempty writer block.** [test/test_spextractor.py:436](/Users/kohlbach/Claude/speXtractor/test/test_spextractor.py:436).

   Both fixture precursors belong after the shifted boundary `10.8-3=7.8`. Tile 1 emits nothing; tile 2 emits everything. `writeBlock` skips the first block. Broken cross-block IDs, offsets or DP handling can therefore pass this test.

   **Fix:** add an earlier precursor and assert at least two positive per-tile spectrum counts. Reuse all check-14 invariants: check 16 currently omits `indexListOffset`. Keep a separate assertion for the exact, unpadded K=1 count so normalization cannot conceal a G0 regression.

7. **must-fix — The purported straddling test does not make carry observable.** [test/test_spextractor.py:424](/Users/kohlbach/Claude/speXtractor/test/test_spextractor.py:424).

   From the fixture’s triangular profiles and identical MS1/MS2 frame times, the first-cell fragment’s Pearson correlation is approximately **0.1980**, below the default **0.3** gate; the second-cell fragment reaches **0.5489**. Thus carried fragments can all be rejected, allowing carry removal to leave the output unchanged. Both splitters are also disabled by `run()`.

   **Fix:** implement check 17 with an explicitly expected carried peak and exactly one emission of its precursor. Include splitting and at least three tiles with pitch below `2*delta_rt`, so transitive carry is observable.

8. **must-fix — The judged padded-window check 18 is absent.** [test/test_spextractor.py:456](/Users/kohlbach/Claude/speXtractor/test/test_spextractor.py:456).

   The fixture has one MS2 window with every frame present. It cannot detect broken padding or exercise a carry-bearing window with no frames in an intermediate tile. Merely deleting an mzML spectrum is insufficient because this path derives its frozen table from the slab.

   **Fix:** add a fixture supplying an independent frozen reader table, assert the expected padding count and tile equality, and explicitly exercise the empty-slab/carry branch.

9. **should-fix — Count normalization fails across the benchmark reader’s chunk boundary.** [bench/semantic_digest.py:37](/Users/kohlbach/Claude/speXtractor/bench/semantic_digest.py:37).

   Normalization runs only on the first chunk containing `<spectrumList`. With a **4,194,291-byte header**, the chunk ends immediately after that marker; the count arrives later and is never normalized. An in-memory reproduction makes `count="12"` and `count="0000000012"` falsely compare different.

   **Fix:** buffer the complete opening tag before normalizing, including tests splitting before and inside the count.

10. **note — `visited` proves only some at-most-once visits, not complete ownership.** [src/spextractor.cpp:4709](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4709), [src/spextractor.cpp:4792](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4792).

    An empty-fragment window returns before marking its owned precursors, and there is no final coverage check or planned emitted-RT assertion. Consequently, “zero detector hits” cannot establish that every eligible precursor was handled.

    **Fix:** account for ownership before the empty-fragment return, check final coverage, and assert emitted RT ownership. This is a missing detector, not evidence of another current omission.

11. **note — The reader transition still requires metadata-driven initialization.** [src/spextractor.cpp:3544](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3544), [src/spextractor.cpp:4010](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4010), [src/spextractor.cpp:1657](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1657).

    Replacing only the slice operation with an MS1-only pass followed by tile reads would leave frozen/window keys dependent on absent resident MS2 slabs. A pass-2 consumer also sees `ms1_.size()==0`, losing its run-sized reservation estimate.

    **Fix for 3a/3b:** initialize full tables, window keys and acquisition band edges from metadata independently of delivered slabs; supply each tile’s expected frame count explicitly. The zero estimate causes additional geometric reallocations, not inherently quadratic growth.

The attack lines checked and found sound, subject to the findings above:

- **G0 mechanics:** `toTof` is in-place and idempotent; the upfront extremes match the former whole-slab calculation. K=1 preserves window order and surviving precursor order through `pidx`/`pslot`. The factored spectrum comparator is unchanged from the parent.
- **DP/settings:** one shared DP pointer reproduces `addDataProcessing_`. Passing the stamped empty `PeakMap` loses no spectrum-dependent settings; the first nonempty spectrum supplies DP to the header.
- **Ownership/carry structure:** adjacent computed ownership intervals partition finite RTs. Filtering all fragments makes carry transitive across arbitrarily many tiles. The defect is rounded candidate coverage, not the induction’s structure.
- **RT containment:** trimming preserves `frame0+rt_at`. The reported RT may leave the trimmed span but remains in the original detection cell.
- **Scoring:** frozen `G`, `nearest_local`, per-trace means/norms and private/reset `pdense` are independent of the resident fragment set. `FragRt` remains a conservative prefilter for ordinary finite inputs. The cap preserves relative candidate ordering when that ordering is well-defined.
- **Resident slicing:** both tile and cell cuts use lower bounds on the same RT values. A frame exactly at an edge belongs to the following interval. Slices correctly copy factors after frame IDs have been discarded.
- **Carry reconstruction/empty slabs:** unchanged frozen indices plus rebased intensity offsets suffice; bins are empty before append. Empty-slab frame initialization supplies scoring’s needs. Its zero band bounds affect diagnostics only.
- **Thread safety:** the maps are structurally fixed during tasks; distinct mapped entries, per-window slots and private task scratch avoid new shared-container races. Reusing `winlog` introduces no nested critical section.
- **Successful writer completion:** running IDs, cumulative offsets, fixed-width count patching and footer offsets are consistent across blocks. Empty leading/intermediate blocks are safely skipped; mzPeak refuses K>1. All-empty zero-byte output and serialization-failure count inconsistencies are inherited writer limitations.

The recorded D-300 **13,836** search result belongs to the earlier one-tile pin; it does not establish the required search acceptance of this tiled output.
