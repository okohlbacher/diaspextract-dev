**I would prioritize MS1 staging, work-balanced tiles, and bounded stage overlap.** The code supports further compaction, but the supplied measurements do not support another large, general-purpose reduction from shrinking `Trace` alone.

This is a source-and-measurement review; I did not run new benchmarks. Below, **D** means intended output-identical, requiring the digest gate; **S** requires the Sage, MSFragger, and entrapment gates on both acquisitions. Exact byte figures describe payload, not measured RSS reductions.

Three measurement corrections affect the recommendations:

- The current three-tile D run reads tiles in **1.60, 7.17, and 6.25 seconds**, with exclusive loop intervals of **12.1, 62.0, and 46.6 seconds**. Hiding the later reads therefore saves at most **13.41 seconds, or 7.57% of 177.14 seconds**, before contention. The attached data does not support the brief’s ~20% estimate.
- `WINDOW_LOOP` encloses tile reads, sorting, and writing. Adding those phase totals double-counts work, explaining totals above 100%. Use the ledger intervals for scheduling estimates. [Timing code](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:5350)
- The three-tile and six-tile arms use **different cell pitches, 600 and 300 seconds**, with different digests. They demonstrate the MS1 floor, but are not a controlled comparison of grouping alone. Ledger “MB” values are actually **MiB**. [Measurements](/Users/kohlbach/Claude/speXtractor/docs/reviews/2026-09-10-streaming-memory/data.md:175)

My ranking is:

| Rank | Change | What it is worth on the supplied measurements | Estimated implementation cost |
|---|---|---|---|
| 1 | Bound MS1 staging; subsequently compact its picked storage | Attacks the actual tiled-process peak. Lossless MS1 packing saves **2.90 billion payload bytes on D** | 1–3 days for batch control; several days for storage integration |
| 2 | Group fixed cells by predicted peak count | **2.260 billion bytes less in D’s largest two-tile slab**; four groups can reach the six-group slab floor | 1–2 days plus measurement |
| 3 | One bounded prefetch reader | Up to **13.41 s / 7.57%** on D three tiles; adds approximately one tile’s slabs and reader transients | About 1–3 days including accounting and thread-budget fixes |
| 4 | Overlap detection and scoring through per-window dependencies | Removes unnecessary whole-tile barriers without redundant detection; potentially addresses more time than read prefetch | Several days to a week |
| 5 | Reduce scoring candidate visits, then improve arena/index locality | Concrete remaining cache opportunities; current per-tile measurements are insufficient to price a speedup | 2–5 days of isolated prototypes |

All five can be developed as **D** changes.

**1. The MS1 floor has a representation problem and a batching problem.**

The decoder stages **64 MS1 frames**, while `PickCompactConsumer` accumulates **256** before picking. Those raw frames coexist with the growing picked `PeakMap` and picker temporaries. In the six-tile run, the sampled process peak contains 10,508 MiB charged to the map and 3,388 MiB to scratch; scratch reaches 3,842 MiB elsewhere. [Decoder](/Users/kohlbach/Claude/speXtractor/patches/openms-brukertims-mz-calibration.patch:338), [consumer](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1801)

First, separate the MS1 batch setting from the MS2 setting and test **128 and 64 frames, with a byte limit**. Halving the backlog nominally removes roughly 1.7–1.9 GiB of the recorded batch payload. That is an inference, not an RSS prediction: picker concurrency, capacities, and allocation timing matter. A subsequent bounded handoff or fused decode-and-pick task can eliminate the accumulation of four decoder batches. Preserve frame order and give each worker its own picker.

The current picked MS1 representation costs 20 B/peak: padded `Peak1D` plus its IM float. Lossless arrays of **m/z double, intensity float, IM float** cost 16 B/peak. Using the recorded D count of 725,116,915 picked MS1 peaks gives exactly:

**725,116,915 × 4 = 2,900,467,660 bytes saved.**

This only helps if tracing consumes the compact representation through an adapter or bounded band materialization. Reconstructing the entire expanded map would move the peak. The exact current TNBC picked-MS1 count is absent; its historical 44.5 GiB map suggests approximately 8.9 GiB of payload opportunity, not an exact current saving. [Recorded count](/Users/kohlbach/Claude/speXtractor/docs/BASELINE.md:1250)

For a larger D-preserving reduction, spool exact picked frames, retain the existing every-97th-peak sample, calculate the same quantile band edges, and materialize whole-gradient MS1 bands under bounded admission. That costs storage traffic and a larger refactor.

**RT-tiling MS1 is S.** MS1 still uses whole-run quantile bands and greedy OpenMS detection. The MS2 cell proof does not cover it, and the 120-second trim happens after detection. [MS1 partitioning](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:2382)

Even eliminating the MS1 peak entirely would leave the existing six-tile loop peak of **23,463 MiB**. Against its sampled process peak of 31,031 MiB, that establishes the next bottleneck after approximately **7,568 MiB** of improvement.

**2. Peak-balanced grouping is worthwhile, with a discrete limit.**

The six measured 300-second cells contain:

`12,986,293; 83,059,978; 233,943,119; 372,109,365; 363,831,426; 192,123,794`

The last count follows from the measured total minus the first five. Enumerating adjacent partitions gives:

| Grouping | Peaks in largest tile | Largest 10 B/peak slab |
|---|---:|---:|
| Current equal-time two tiles: 3 + 3 cells | 928,064,585 | 9,280,645,850 B |
| Best two tiles: 4 + 2 | 702,098,755 | 7,020,987,550 B |
| Best three tiles: 3 + 1 + 2 | 555,955,220 | 5,559,552,200 B |
| Four tiles: 3 + 1 + 1 + 1 | 372,109,365 | 3,721,093,650 B |
| Six one-cell tiles | 372,109,365 | 3,721,093,650 B |

Thus the two-tile improvement saves exactly **2,259,658,300 bytes, or 24.35% of the largest slab**. Four groups attain the indivisible-cell floor with two fewer reads and barriers than six groups. Neither result establishes a wall-time improvement, and neither lowers the current MS1 process peak by itself.

There is an important implementation qualification: `num_peaks` is a **raw physical-frame count**, before window slicing and picking. It is not the exact picked count used in this calculation, and `FrameTab` currently drops it. Capture counts by physical group/frame, avoid counting one physical frame repeatedly as independent work, and validate the proxy against picked counts per cell. [Metadata export](/Users/kohlbach/Claude/speXtractor/patches/openms-brukertims-mz-calibration.patch:412)

Use a contiguous partitioner constrained by both predicted bytes and cell count. For a pipeline, also evaluate **adjacent tile sums**, since current and prefetched tiles coexist.

At the default 600-second pitch, D has only three cells. Three one-cell tiles already exhaust the grouping freedom. Changing the pitch to gain more freedom is S.

**3. Build prefetch first, then overlap computation without reconstructing carry.**

For the initial implementation, use one reader and a queue containing at most one prefetched tile. The orchestrator should reserve memory before reading it. Keep output commitment ordered.

The three-tile memory cost is material:

| Overlap | Existing compute RSS peak | Additional next-tile slab |
|---|---:|---:|
| Compute tile 1 + prefetch tile 2 | 11,934 MiB | approximately 5,780 MiB |
| Compute tile 2 + prefetch tile 3 | 28,086 MiB | approximately 5,302 MiB |

The second combination is approximately **33,388 MiB before reader transients or previous output**. Keeping tile 1’s output adds another 268 MiB; read-3’s recorded scratch allowance is 681 MiB, although its accounting needs correction below. An additive planning envelope is therefore around **34.3 thousand MiB**, above the three-tile MS1 peak of 30,920 MiB.

This is not a predicted RSS measurement: allocator reuse and transient overlap decide the result. It does establish that the extra tile cannot be called small. Do not add whole read-phase RSS to compute-phase RSS; both include shared and retained memory.

The six-cell arm has more apparent headroom: compute-4 RSS plus tile-5 slab is approximately **25,542 MiB**, before additional transients. That must be tested within a fixed-pitch comparison.

The stronger same-machine schedule requires **no redundant cell**:

- Detection, splitting, and trimming of `(tile k+1, window w)` need only its input and immutable run metadata.
- Carry is first consumed after that work.
- Scoring reads fragments without changing them.
- Therefore publish carry after fragment preparation, then let successor scoring wait for that carry, rather than waiting for predecessor scoring or the whole tile.

Currently carry extraction occurs after scoring, imposing an unnecessary dependency. [Detection and carry consumption](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4865), [late carry extraction](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:5239)

This is the architecture I would build after the prefetch experiment. The three-tile exclusive compute intervals total **120.7 seconds**, versus **88.6 seconds** for one tile at the same pitch. That 32.1-second difference motivates investigation; it is not proof that all 32.1 seconds are recoverable barrier time.

The orchestrator should own:

- A **global byte budget**, covering loaded slabs, active work, carry, and completed output.
- One compute task pool, with a **global task limit**.
- Explicit reader and encoder thread budgets, within the overall CPU allowance.
- Ordered output commitment and bounded queues.

For the first prefetch implementation, separate reader and compute teams are practical, provided their budgets are explicit. Avoid giving every concurrent stage the full machine. For the subsequent compute dependency graph, retain one shared compute pool.

The current scorer bounds tasks per window, not across arbitrary numbers of overlapping tiles. Two sets of 28 windows can approach **5,600 scorer workers at 100 threads**, before band, splitting, and other tasks consume the documented 6,400-task threshold. Use a bounded number of workers pulling jobs globally.

There are also shared-state changes needed before simply launching `std::async`: phase statistics mutate global containers, `LC_SLAB` uses a replacement assignment that would overwrite another tile’s charge, and the picker schedule initialization only configures the first calling thread. Concurrent stages need per-stage events and additive ownership-based charges.

**Carry reconstruction is valid under explicit conditions.**

For the default `delta_rt = 3`, the predecessor’s final full cell covers the required interval:

`[tile.lo − 6 seconds − ε, tile.lo)`.

Re-run that **entire cell** through detection, splitting, trimming, and filtering; rebase to the frozen frame table; retain the selected fragments’ complete profiles. Reading only six seconds of raw peaks does not reproduce the cell’s greedy detection.

For cells shorter than `2 × delta_rt`, one preceding cell is insufficient. Carry is deliberately transitive, and the existing five-second-cell test exercises this case. Reconstruct all preceding cells that can contribute. The 120-second profile trim is not the bound that selects these cells.

The “17% at six cells” estimate also needs peak weighting. On D’s three one-cell tiles, reconstructing predecessor cells rereads **702,098,755 picked peaks**, or **55.81% extra** over the run. That is substantial duplication to replace carry whose recorded peak is only 166 MiB.

I would reserve independent-tile reconstruction primarily for **multiple machines**, where it buys independent memory bandwidth and scheduling. On one machine, the dependency graph offers overlap without duplicated work. Multiple simultaneous loader calls additionally require removing mutable loader-global metadata and calibration state, or using separate processes.

**Output must remain physically ordered.**

`TileWriter` assigns indices and native IDs from the running spectrum count and records offsets at append time. Writing tiles physically out of order and fixing the index afterward would not restore canonical spectrum order. [Writer](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:2032)

Keep a bounded map of completed blocks and commit the next tile only. If a slow earlier tile causes pressure, stop admitting later work or spill compact spectrum blocks. For distributed execution, merge part artifacts in order and encode with one consistent header, numbering, and index. Complete mzML files cannot simply be concatenated.

Writing itself totals approximately **2.9 seconds** in the three-tile phase accounting. Its overlap is useful, but does not justify a large reordering infrastructure on D alone.

**The remaining compaction opportunities are specific, rather than a universal next factor.**

| Structure and representation | Exact payload saving where counts support it | Cost and classification |
|---|---|---|
| Picked MS1: 20 → 16 B/peak | **D: 2,900,467,660 B**. TNBC: `4 × current picked-MS1 count`, which is missing | Adapter or bounded materialization; D |
| Slab TOF: uint32 → packed uint24, retaining float intensity and uint16 IM | **D whole run: 1,258,053,975 B**; largest measured 300-second cell: **372,109,365 B**. TNBC: one byte per picked peak; ~3.46 GB using the brief’s approximate ratio | Packed loads and binary searches cost CPU. Convert m/z quanta before packing; the intermediate quanta do not fit uint24. D with checked fallback |
| MS2 `Trace`: 40 → 32 B through checked integer-field packing, retaining both doubles | `8 × simultaneously resident records`. D’s recorded category maxima imply about **1,080 MiB** one-tile or **167 MiB** six-tile opportunity | Intrusive accessors, range checks, and fallback for MS1/long runs; D. Current TNBC streaming record count is missing |
| `FragRt::rt`: double → uint16 absolute frozen-frame index, with wider fallback | **6 B/fragment** on these frame counts; approximately **178 MiB** of six-tile saving is *not* supported—the category includes other arrays. Its RT component is only about **47 MiB** from the rounded 264 MiB aggregate | Preserves exact RT lookup, adds indirection; D, benchmark with scoring index |
| Writer offsets: `{string, int64}` → `uint64`, regenerate `spectrum=N` | **D: 19,579,200 B**; **105,146,464 B** using TNBC’s recorded 3,285,827 spectra | Footer/OpenMS change and index validation; D, low priority |

The TNBC spectrum count is explicitly recorded in the cell/frozen-table gates; confirm it against the latest acquisition-edge output before treating that writer figure as current. [TNBC count](/Users/kohlbach/Claude/speXtractor/docs/BASELINE.md:2748)

For `Trace`, merely narrowing `frame0` and `bframe` to uint16 leaves an aligned 40-byte object. Actual packing is required. **Do not derive `bframe` from `frame0 + apex`**: equal-intensity tie handling can make those different measurement frames. Likewise, recomputing cached `mz` from the export calibration is not automatically D.

I would not prioritize lossy intensity or mobility compression. Those are S changes affecting greedy detection and correlation, with no supplied evidence pricing their science cost. Compressing 32-byte sort keys further is also low priority: canonical sorting is only about 0.4–0.5 seconds on D.

**The remaining cache misses have identifiable sources.**

The best scoring experiment is an RT-bucket index over the existing canonical fragment order. Today each precursor scans its entire IM slice, mostly rejecting entries through `FragRt::q`. Build postings of canonical fragment indices per RT bucket; binary-search the five eligible buckets to the IM interval, merge their indices in ascending order, and retain the exact double RT test. This preserves visitation and tie order while avoiding rejected candidates. It differs fundamentally from the rejected detector predicate reorder. [Scoring scan](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3137)

The price is approximately 4 B/fragment of postings, potentially replacing the 2-byte `q` array. Historical whole-run rejection ratios cannot establish current tiled benefit. Record candidate visits, survivors, and scoring time **per tile**.

Other concrete experiments, in descending interest:

| Access pattern | Candidate layout | Expected value and deciding measurement |
|---|---|---|
| Trace extension visits neighboring frames at nearly the same TOF bucket; `fidx` is frame-major | Bucket-major or blocked bucket × frame index | Small, unmeasured gain; benchmark detector time and LLC/DTLB misses. Preserve the three sequential peak streams |
| IM-sorted records point into arenas built in cell/band order | Repack surviving profiles into canonical order once, preferably during an already-required copy | Improves profile-walk locality but adds bandwidth and temporary storage. Measure repeated arena reads versus repack cost |
| Seed comparison sort repeatedly gathers `inten[a]` and `inten[b]` | Temporary packed intensity/index keys per band | May reduce random loads, but adds 4 B/seed and possibly sorting scratch. Current prep timing must justify it |
| Output retains large `MSSpectrum` objects and individually allocated peaks | Compact descriptors plus m/z/intensity arrays; materialize only an encoder wave | More promising for output memory than key shrinking. Exact saving needs actual object sizes and emitted-peak counts |

Do not assume all these gains stack. For example, an RT-postings scorer changes which arena regions it revisits and may reduce the value of repacking.

**The lifetime audit favors owning memory at cell and stage boundaries.**

| Structure | Current lifetime and remaining action |
|---|---|
| Decoder buffers, picker raw batches | Batch data should die after handoff; decoder thread-local buffers persist. Bound and charge them separately |
| MS1 map, band maps, OpenMS traces | Map is already consumed during distribution. Avoid its initial full expansion; do not credit another late `clear()` |
| MS1 traces and precursors | Necessary for scoring, but unreferenced profiles are already compacted. Remaining D state is about **184 + 133 MiB**; pack referenced records or retire profiles after their last owning tile only if worth the bookkeeping |
| Frozen tables, calibration, RT axis | Correctly run-level. Share immutable table views instead of repeated `setFrames()` copies; keep global `G` and mapping unchanged |
| Slabs | Already released before the final arena merge. However, multi-cell processing calls `sliceFrames()`, copying all three peak arrays |
| Seed order, TOF index, band `visited` | Cell-local already. Free after detection. Sharing `visited` between bands changes peak ownership and is S |
| Band arenas and parent records | All cells’ outputs accumulate before window merging/splitting. Split and trim each completed cell, retaining children; canonical sorting resolves final order |
| Window arena | Trimming moves offsets but leaves discarded tails allocated. Reclaim during a necessary merge/repack, after measuring discarded slots |
| Scoring arrays and `pdense` | Window/scoring-task lifetime is appropriate. Reuse worker scratch; do not replace the frozen correlation denominator with tile size |
| Spectrum slots and blocks | Live through tile completion and writing. Compact descriptors or bounded ordered output reduce this residence |
| Carry | Needed until its successor consumes it. Release each consumed slot; publish earlier to remove the scoring dependency |
| Writer index | Run-level through footer generation; numeric offsets suffice |

For slabs, I would first replace `sliceFrames()` with a read-only cell view. Eventually let the loader own separate cell slabs, allowing each cell’s input to be released immediately after detection. The view eliminates **10 bytes copied per cell peak** in grouped tiles; it saves nothing on the existing one-cell fast path. [Cell copies and accumulation](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4897)

Per-cell splitting is especially attractive for larger groups: the splitter already operates independently per parent with fixed parameters. It avoids retaining every cell’s unsplit parents until the whole window finishes. A segmented arena can eliminate further merging copies, but introduces addressing complexity; measure the simpler per-cell lifetime change first.

**Finally, repair attribution before pricing allocator reclamation.**

The ledger is useful, but several omissions are large enough to affect this review:

- Band arenas and records are charged after detection joins; growing allocations and band `visited` arrays are invisible during execution.
- Splitter child stores coexist with parents without corresponding live charges.
- `pslot` output is charged only after scoring.
- The copied cell slab is uncharged.
- `scratch_charged` is static and survives destruction of the consumer, leaving stale scratch charges.
- The MS1 map remains charged after its source spectra have been consumed; raw spectrum charges also use 16 rather than the padded 20 B/peak representation. [Ledger update sites](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1711), [split storage](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1452)

Consequently, **unattributed RSS is not wholly reclaimable memory**. Nor is `fordblks` an exact resident-free-page count: the end-state RSS is approximately 2.9 GB while allocator free space remains around 20,000 MiB.

Add ownership-based charges and overlapping stage events before the pipeline A/B. Then compare bounded reuse against trims at genuinely dead phase boundaries, recording **minor faults**, RSS, and wall time. The mmap experiment already disproves the idea that aggressively returning pages is free.

The decisive first measurements are: MS1 batch-size A/B, fixed-pitch balanced grouping, and one-prefetched-tile runs with explicit CPU and memory budgets. Proceed to the compute dependency graph if those traces show idle tails; proceed to cache-layout work where hardware counters show stalled memory access. Full tile reconstruction belongs behind that evidence on one machine, and is a stronger proposition across machines.
