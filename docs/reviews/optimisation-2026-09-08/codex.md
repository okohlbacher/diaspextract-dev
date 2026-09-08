**The strongest new runtime candidate is caching the Savitzky–Golay coefficients rebuilt for every trace.** The cheapest substantial memory candidate is deleting the duplicate scoring coordinates. Several proposed designs overstate the copies they remove.

I reviewed the current 3,989-line translation unit, both headers, and the relevant local OpenMS implementations. Estimates below are **not new benchmark results**. GB means decimal GB; aggregate allocations across all windows are distinguished from simultaneous RSS.

1. **Cache Savitzky–Golay coefficient construction.**

   **What:** The calls in [`splitIntegerTraces()`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1178) and MS1 `do_split()` at line 1712 reach [`ElutionPeakDetection::smoothData()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/ElutionPeakDetection.cpp:556). It constructs and configures a filter for every parent. [`SavitzkyGolayFilter::updateMembers_()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/PROCESSING/SMOOTHING/SavitzkyGolayFilter.cpp:30) reconstructs coefficients using repeated SVDs. Cache configured filters per thread, keyed by effective odd frame length and polynomial order; bound retained cache memory.

   **Why:** The source’s population estimate gives `0.21 × 4.27e9 = 896.7 million` parents. The repository’s [older Release microbenchmark](/Users/kohlbach/Claude/speXtractor/docs/INTEGER-MEMORY-PLAN.md:156) reports **16.8 µs** coefficient construction. If applicable here, that is `896.7e6 × 16.8µs = 15,065 CPU-s`, approximately **164 wall seconds at 91.9×**. Saving only **4.5 µs per parent** would already exceed 5% of the 877-second run.

   **OUTPUT-IDENTICAL:** Reuse coefficients produced by the existing computation; leave filtering loops, accumulation order, and float conversions untouched.

   **Risk/falsifier:** That historical microbenchmark may overestimate today’s cost. Low cache reuse or materially less coefficient CPU would falsify the projected gain. Do not replace SVD with a mathematically equivalent coefficient formula.

   **Effort:** **30–80 lines**, localized OpenMS patch. Highest priority.

2. **Delete the duplicate fragment IM and RT arrays.**

   **What:** Remove `frag_im` at [`3734–3735`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3734) and `FragRt::rt` at [`2402`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:2402). Binary-search `Trace::im`; retain the existing uint16 RT rejection array and read `Trace::rt` only after it passes.

   **Why:** Exactly **16 bytes per simultaneously scoring trace**. The scoring representation falls from `48 + 16 + 2 + 16 = 82` to **66 B/trace**, excluding profiles: **19.5% smaller**. Using the source’s `0.28 children/peak`, the all-window ceiling is `16 × 0.28 × 4.27e9 = 19.1 GB`. It exceeds 10 GB at **625 million simultaneously scoring traces**. Applying 16 bytes to all 2.1 billion parent-plus-child records would overstate this saving.

   **OUTPUT-IDENTICAL:** Same stored doubles, bounds, candidate order, and arithmetic.

   **Risk/falsifier:** Surviving RT candidates now fetch a larger record. A scoring slowdown exceeding the admission benefit would falsify the runtime case; the allocation saving remains exact.

   **Effort:** **25–45 lines**, local. The designed “authoritative scoring set” is sound.

3. **Remove OpenMS’s hidden MS1 working-map copy by transferring ownership.**

   **What:** At [`m2.run(sub[b], t)`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1823), the caller immediately discards `sub[b]`. Yet [`MassTraceDetection::run()`](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/MassTraceDetection.cpp:219) builds another `work_exp`: it copies each spectrum at line 256, selects noise-passing peaks, then copies that result again at line 258. Add a consuming entry point that filters the owned map and invokes unchanged `run_()`.

   **Why:** With membership-retained fraction `r`, the additional working payload is approximately **45r GB** on the two-hour file and **14r GB** on the shorter file. The two-hour figure exceeds 10 GB when `r > 22.2%`, subject to overlapping band lifetimes. It also removes substantial copying.

   **OUTPUT-IDENTICAL:** Preserve empty frames, selected-peak order, apex insertion order, stable seed sorting, and the detector’s arithmetic.

   **Risk/falsifier:** Low retained fraction or little simultaneous working-map residency reduces the benefit. Ownership changes must not remove empty frames.

   **Effort:** **60–100 lines**, OpenMS overload/patch plus caller changes. Better value than changing the MS1 detector.

4. **Make integer EPD children reference parent intensity spans.**

   **What:** Replace the profile allocation in [`toTrace(cm, cst)`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1190) with child offsets into the existing parent arena. Remove child stores at lines 1131/1137 and their intensity gathering at 1203–1216. Continue obtaining child metadata through the existing computations.

   **Why:** OpenMS [constructs children from unchanged contiguous parent points](/Users/kohlbach/Claude/OpenMS/src/openms/source/FEATUREFINDER/ElutionPeakDetection.cpp:474). The current code nevertheless allocates all child profiles while parent profiles remain live. Eliminating that costs saves **`4 × total simultaneously live child-span entries` bytes**, plus capacity slack. At `0.28 × 4.27e9 = 1.196 billion` children, mean spans of 3 or 5 frames correspond to **14.3 or 23.9 GB across all windows**. Actual peak saving depends on simultaneous splitting windows.

   **OUTPUT-IDENTICAL:** Same raw intensities, zero gaps, metadata, and traversal. Preserve the distinction between **smoothed-max RT** and **raw-intensity apex**.

   **Risk/falsifier:** Retaining unused parent tails/capacity after splitting can consume the saving. Reclaim discarded ranges after trimming; avoid introducing a full-sized replacement arena during reclamation.

   **Effort:** **70–130 lines**, contained splitter/helper refactor. More compelling than segmented arenas alone.

5. **Use RT-bucket postings to avoid scanning almost entirely rejected IM slices.**

   **What:** Extend [`FragRt`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:2400) with lists of existing fragment indices, grouped by the **existing** RT bucket. At [`2477`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:2477), search the IM index interval within the five `pq±2` lists and merge candidates in increasing original `fi`. Run the exact current scoring body.

   **Why:** The historical source measurement—not today’s two-hour measurement—has approximately **867 billion visits** and a **0.9% bucket pass rate**. That becomes roughly **7.8 billion posting entries**: about **111× fewer rejection iterations**. Read payload changes from `867e9 × 2 = 1.73 TB` to `7.8e9 × 4 = 31 GB`, before search/merge overhead. Postings replace `2N` bucket bytes with `4N` index bytes: **+2N memory**, or a net **−14N** combined with item 2.

   **OUTPUT-IDENTICAL:** Preserve the original bucket predicate, exact RT gate, and ascending `fi` order. Visiting buckets consecutively without merging is insufficient: emission order participates in ties.

   **Risk/falsifier:** Short slices or weak RT selectivity can make five searches and merging slower. Retain the scan fallback. The supplied phase table does not establish the current gain: **>5% total requires >43.85 seconds**, or **7.93% of WINDOW_LOOP**.

   **Effort:** **100–170 lines**, contained indexing refactor. High upside, less certain than items 1–4.

6. **Remove fragments that cannot pass the existing support-count gate—but preserve their grid contribution.**

   **What:** After the unchanged canonical fragment sort at [`3728`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3728), construct `G` and `nearest_local` from **all** original fragments, then discard records satisfying the existing rejection at [`2493`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:2493). Preserve the original RT-bucket calibration too. Build scoring arrays only for retained records.

   **Why:** One- and two-point traces survive the current detector/EPD path but cannot pass the default three-point overlap requirement. After item 2, reclaiming a rejected trace with mean span 1.5 removes approximately `66 + 4×1.5 = 72 B`. **139 million reclaimed records would save 10 GB**, and their repeated scoring visits disappear. The actual rejected population is currently unmeasured.

   **OUTPUT-IDENTICAL:** Only if the original support grid, nearest-frame mapping, bucket calibration, and retained ordering survive. Dropping these traces before computing the grid changes Pearson scores.

   **Risk/falsifier:** **`erase()` does not release capacity.** Shrinking the Trace vector can temporarily duplicate `48 × N_kept` bytes; arena shrinking can duplicate retained profiles too. Without capacity reclamation, after item 2 the immediate array saving is only **18 B/rejected trace**. Too few short traces or a worse compaction peak falsifies the memory case.

   **Effort:** **60–110 lines** for filtering/grid separation; controlled physical reclamation may require more. Count the population before committing to the memory refactor.

7. **Hoist the MS1 sortedness check out of the 48-band loop.**

   **What:** [`s.isSorted()` at 1787](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1787) runs inside the band loop beginning at 1774. Compute it once per source spectrum. OpenMS implements this as a full `std::is_sorted` traversal.

   **Why:** Approximately `45 GB / 20 B = 2.25 billion` peaks. This removes **47 × 2.25 billion = 105.75 billion comparisons**, traversing approximately **1.69 TB** of Peak1D storage. The 30-minute equivalent is **526 GB**. These are avoided cache/memory traversals, not guaranteed DRAM traffic.

   **OUTPUT-IDENTICAL:** The source spectrum does not change between band checks.

   **Risk/falsifier:** Small measured `tt_dist` improvement would limit the wall benefit. No meaningful numerical risk.

   **Effort:** **2–4 lines**, local. Do this immediately despite lacking a defensible seconds estimate.

8. **Transfer the entire output vector into PeakMap.**

   **What:** Replace the loop at [`3927`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3927) with `out_exp.setSpectra(std::move(all_out))`. The [local rvalue overload](/Users/kohlbach/Claude/OpenMS/src/openms/source/KERNEL/MSExperiment.cpp:1092) transfers vector ownership.

   **Why:** Removes nearly the **5-second ASSEMBLE phase** and the moved-from source object array, destination growth, and spare capacity. The observed **40→45 GB** increase indicates the relevant scale, although not every byte is necessarily attributable to these arrays.

   **OUTPUT-IDENTICAL:** Identical elements and order; unchanged writer path.

   **Risk/falsifier:** Verify that the deployed OpenMS has this overload. The important correction: the current loop already **moves spectrum payloads**; it does not deep-copy all peaks.

   **Effort:** **1–5 lines**, local. Much better return than beginning with a streaming writer.

9. **Convert MS1 split children to Trace inside the splitting tasks.**

   **What:** [`1865–1880`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1865) gathers the entire split `MassTrace` population, then [`1917`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1917) converts it serially. Split and convert per parent inside existing chunks, using private stores and deterministic gathering.

   **Why:** Parallelizes conversion, frame lookup, allocation, and destruction; avoids retaining all split-child OpenMS objects. Their point payload includes roughly **24 B Peak2D + 8 B smoothed intensity**, compared with 4-byte span entries plus Trace records. Exact saving needs the MS1 child-point count. The supplied **106 seconds at 11.2×** makes this worth investigating, but does not prove conversion dominates.

   **OUTPUT-IDENTICAL:** Keep per-trace EPD computations, point order, and the existing effective gather order.

   **Risk/falsifier:** Low current conversion time or equally expensive arena gathering defeats the case.

   **Effort:** **100–180 lines**, moderate refactor. Complements item 3.

10. **Segmented arenas: useful, but the full-arena doubling claim is wrong.**

    **What:** Replace [`TraceStore::absorb()`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:313) and merges at 3671–3679/1207–1217 with segment references. Put a **uint16 segment ID in the existing two bytes of Trace padding**.

    **Why:** It removes all arena-copy traffic. However, `reserve()` does not initialize every destination page, and `absorb()` frees **each source immediately after copying it**. Ignoring allocator retention, duplicate touched payload is approximately the **largest source**, not the full destination. Balanced 12-band merges duplicate roughly **1/12** of the parent arena; balanced 48-chunk merges roughly **1/48** of the child arena.

    **OUTPUT-IDENTICAL:** Storage addressing changes; values and iteration order do not.

    **Risk/falsifier:** A uint32 segment field can grow Trace **48→56 B**, costing **16.8 GB** at 2.1 billion records. Extra indirection may outweigh copy savings. RSS remaining unchanged would falsify the claimed peak benefit. Item 4 already removes the child intensity merge; do not count it twice.

    **Effort:** **120–200 lines**, storage/accessor refactor. Downgrade its current priority.

11. **Chunked TOF store: eliminate copying, not a guaranteed second 40 GB.**

    **What:** Make [`CompactFrame`/`PeakSlab`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:619) share owned frame/chunk arrays, eliminating concatenation in [`toSlab()`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:759).

    **Why:** Current lines 784–786 release each compact frame as the slab grows. Live peak payload is approximately **10P plus one frame’s overlap**, rather than 20P. A shared backing store removes approximately **42.7 GB of destination writes** across the run, corresponding source reads, and allocation churn. Computing TOF during loading **relocates** the inversions; it does not eliminate their CPU cost.

    **OUTPUT-IDENTICAL:** Preserve exactly `tofOf(mzq/MZ_Q, b)`, peak/frame order, and fallback behavior. Substituting raw vendor TOF or unquantized picked m/z is not the same transformation.

    **Risk/falsifier:** Slower hot-path indexing or little measured slab time defeats the runtime case. Allocator retention determines how much RSS actually disappears.

    **Effort:** **200–400 lines**, loader/store/detector refactor. Sound only with corrected expectations.

12. **Band-local visited: use exact overflow storage, never clip reach.**

    **What:** Replace the full-range bitmap at [`980`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:980) with sparse pages or a local bitmap plus exact overflow. Bands restrict seeds at 1040; extension can reach outside the core.

    **Why:** Ideal all-window saving is `(12−1) × 4.27e9 / 8 = 5.87 GB`, before sparse-page overhead and concurrency effects. **This cannot deliver a 10 GB payload win.**

    **OUTPUT-IDENTICAL** with full-address overflow semantics. **OUTPUT-CHANGING** if visits outside a fixed core/halo are forgotten or prohibited.

    **Risk/falsifier:** Broad page occupancy or slower `seen()/mark()` lookups can erase the benefit.

    **Effort:** **50–100 lines**, localized detector change. Low priority.

13. **Streaming output: reject the claimed 66-second removal; reconsider compact records separately.**

    **What:** The affected path is [`assembleFromList_()`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:2641), `pslot`, `win_out`, and lines 3896–3975.

    **Why:** A writing consumer does not eliminate the **9-second global sort** or **52-second serialization**. Windows span the entire RT range, so completion-order output cannot preserve canonical order. Existing spectrum transfers move payloads; the writer does not hold a third complete peak representation.

    Compact records can still save memory: separate double m/z and float intensity arrays save **4 B/emitted fragment**, up to `3.9e6 × 500 × 4 = 7.8 GB`, plus reduced spectrum/precursor object overhead. That latter saving needs actual object/capacity counts.

    **OUTPUT-CHANGING** for direct completion-order streaming. A corrected ordered-record design can be **OUTPUT-IDENTICAL**, preserving float casts, IDs, metadata, and ordering. Beware: the current comparator omits some serialized metadata, so parallel sort or k-way merge is not automatically tie-identical.

    **Risk/falsifier:** Scratch I/O, serialization still dominating, or little output resident at the admission peak. Parallel encoding would be a separate optimization.

    **Effort:** **200–400 lines** for compact records plus final ordered writing; **350–600+** for spill/merge. Defer until the cheaper changes land.

14. **Per-band MS1 materialization: reject as currently described.**

    **What:** Moving slicing from [`1772–1803`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1772) into each detector task.

    **Why it loses:** Current distribution destroys source spectra progressively. Lazy band tasks instead require retaining the original map while constructing their slices. With 48 concurrent tasks, this can add approximately **45 GB** on the two-hour file, before OpenMS working copies.

    **OUTPUT-IDENTICAL** if slicing and ordering remain unchanged, but that does not make it a memory optimization.

    **Risk/falsifier:** Only a compact backing store, non-owning detector views, or genuinely bounded ownership handoff reverses this argument.

    **Effort:** Roughly **50–100 lines** for the harmful relocation; substantially more for a useful ownership redesign. Prefer item 3.

15. **MS1 through the integer detector: real memory potential, expensive acceptance risk.**

    **What:** Replace the MS1 route at [`2989`](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:2989), including loading/storage and band preparation.

    **Why:** Source peak storage alone could fall from 20 to 10 B/peak: **22.5 GB** on the two-hour file, **7 GB** on the shorter one, plus removal of OpenMS working copies.

    **OUTPUT-CHANGING:** MS1 currently uses m/z quantile bands, halo seeding, and centroid ownership. Integer detection uses core seeding and unrestricted extension. Quantized IM accumulation also changes arithmetic. The already-shipped IEEE m/z index weakens the additional precursor-index justification.

    **Risk/falsifier:** Either digest will change; the full scientific acceptance gate is unavoidable. Memory savings alone cannot justify promotion.

    **Effort:** **200–400 lines**, routing/calibration/storage refactor, plus expensive acceptance. Last among substantial-memory candidates.

Neither header supplies a major win for the measured `.d` workload. `TdfLoad.h` handles small frame metadata; `MzPeakStreamLoad.h` is not on that path.

Finally, **more admitted windows alone cannot justify minutes of claimed speedup at 91.9×**. Holding CPU work fixed, the optimistic window-loop floor is `50,776/100 = 507.76 seconds`: only **45.24 seconds** below 553. Larger improvements need reduced work or reduced memory stalls—precisely why coefficient caching and avoiding rejected candidate scans deserve priority.