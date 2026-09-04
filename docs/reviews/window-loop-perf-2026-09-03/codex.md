# Executive verdict

speXtract is not 2.3× slower primarily because it “only” achieves 67.9× parallel speedup. It is slower because it performs roughly 3.1× as much CPU work:

- CPU ratio: \(22.9/7.3 = 3.14×\)
- Core-use ratio: \(60/45 = 1.33×\)
- Therefore expected wall ratio: \(3.14/1.33 = 2.35×\), essentially the measured \(1359/586 = 2.32×\).

The window loop alone consumes 77,333 CPU-s = 21.48 CPU-h—2.94× the reference implementation’s entire 7.3 CPU-h. Even deleting every other speXtract phase would not produce CPU parity. Scheduler improvements can plausibly remove 15–25% wall time. Closing the remaining gap requires reducing the number of fragment traces and/or precursor–fragment correlation work.

There is also a revision mismatch. The measured run is clearly from the parent of commit `d0b3cb4`. The current file has already replaced the rigid 8×12 nested grid with one 100-thread task pool, parallelized `FragGrid`, changed the admission multiplier from 10× to 16×, and shortened the wait from 200 to 20 ms. See [DIAPseudoSpectra.cpp:2322](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2322), [DIAPseudoSpectra.cpp:2344](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2344), and [DIAPseudoSpectra.cpp:2363](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2363). The supplied measurements therefore do not characterize the current source.

## 1. Where the wall time goes

### The measured 29% efficiency loss

The per-window stage timers are elapsed stage durations summed across windows—not CPU-seconds, despite the incorrect log message at [DIAPseudoSpectra.cpp:2671](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2671). The timers surround stages with `steady_clock`, for example [DIAPseudoSpectra.cpp:2415](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2415) and [DIAPseudoSpectra.cpp:2472](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2472).

That permits a concrete decomposition:

- Average active outer slots:
  \(8139.5/1139.0 = 7.146\) of 8 = 89.3%.
- Average cores used per active window:
  \(77332.9/8139.5 = 9.50\) of 12 = 79.2%.
- Product:
  \(7.146 × 9.50 = 67.9\) cores, exactly the measured loop speedup.

Of the 96-thread ceiling, the missing 28.1 core-equivalents are approximately:

| Loss | Core-equivalents | Explanation |
|---|---:|---|
| Vacant outer slots | 10.25 | \(96 × (1-7.146/8)\): tail, admission stalls, or gaps between stages |
| Known serial stages | at least 4.06 | Materialize + old serial `fraggrid` + emit = 420.9 of 8139.5 window-s, using one rather than 12 cores |
| Residual inner loss | at most 13.79 | Band/chunk imbalance, serial work hidden inside `trace`, fork/join overhead, allocator and memory-bandwidth stalls |

The serial-stage estimate is only a lower bound: the `trace` timer also includes serial band construction, sorting, canonicalization and result merging surrounding the parallel detector.

### Which constraint is binding?

- **Eight-window cap:** not the primary limit. Eight windows × twelve threads already exposes 96 threads. The four permanently unused threads cost at most 4.2%. The rigid topology is bad chiefly because idle teams cannot help surviving windows, which the current task-pool rewrite explicitly addresses at [DIAPseudoSpectra.cpp:2363](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2363).

- **Across-window imbalance/admission:** measurable but bounded. Perfectly filling eight slots reduces the loop from 1139 to \(8139.5/8 = 1017.4\) s: at most 121.6 s, or 9.0% of total wall time. Because admission waiting is outside the stage timers, the supplied data cannot separate window-size tail from memory admission.

- **Old serial `fraggrid`:** not binding. Even ideal 12-way acceleration saves at most
  \((395.8-395.8/12)/8 ≈ 45\) wall-s, about 3.3% of total runtime. The current implementation now uses a task loop at [DIAPseudoSpectra.cpp:741](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:741).

- **Inside-band/precursor imbalance:** real. After accounting for outer vacancy and the explicitly serial stages, roughly 13.8 of the missing 28.1 cores remain. Quantile bands balance sampled peak count, not `MassTraceDetection` work; its candidate work is locally superlinear in peak density. The partition and detector are at [DIAPseudoSpectra.cpp:968](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:968) and [DIAPseudoSpectra.cpp:1015](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1015). Scoring also uses chunks of 32 precursors whose costs vary with IM density, support length and emitted-fragment count; current equivalent is [DIAPseudoSpectra.cpp:2560](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2560).

- **Raw trace/correlation volume:** the actual binding problem. Trace and score occupy 94.83% of summed active window time. The scoring path takes an IM slice, performs the RT gate, then walks every surviving fragment’s CSR support for the dot product at [DIAPseudoSpectra.cpp:1515](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1515) and [DIAPseudoSpectra.cpp:1534](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1534). With up to 8.5 M fragment traces per window, this is an enormous intermediate workload unrelated to the final count of 863 k spectra.

### What would falsify this accounting?

It fails if any of the following is false:

- The 8,139.5 s timers and 77,332.9 CPU-s came from the same run and revision.
- Exactly eight window workers and real 12-thread nested teams were used.
- `WINDOW_LOOP` CPU includes no unrelated process work.
- Admission did not regularly restrict execution below eight windows.
- The timers measure elapsed per-window stage duration—as the source shows—rather than CPU time as the log incorrectly claims.

The settling measurement is cheap: record, per window and band, admission-wait time, stage start/end, thread CPU time and active-team size. One OMPT trace or even four atomic histograms would separate admission, window tail, band imbalance and memory stalls.

## 2. Where the memory goes

The 20.85 GB compact store is only the floor. `CompactFrame` stores 10 bytes per peak—4-byte m/z, 4-byte intensity and 2-byte IM—at [DIAPseudoSpectra.cpp:393](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:393). Materialization expands this into `Peak1D` plus an IM array, approximately 20 bytes per peak, at [DIAPseudoSpectra.cpp:468](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:468).

During one old-revision window, memory includes:

- Materialized `PeakMap`.
- Twelve band `PeakMap`s. During partition, the source map and band copies coexist; only afterward is the source cleared at [DIAPseudoSpectra.cpp:982](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:982).
- Halo peaks copied into adjacent bands.
- Millions of OpenMS `MassTrace` objects, their point storage, valley-split results, converted `Trace` objects and XICs.
- At 8.5 M fragments, approximately 476 MB just for 56-byte `Trace` headers, before any XIC points.
- `frag_im`, means, norms and CSR offsets: roughly another 200–300 MB.
- For \(Q\) XIC support points, the old grid builder simultaneously retained approximately:
  - `Trace::xic`: \(16Q\) bytes;
  - CSR `flat`: \(8Q\) bytes;
  - the all-point RT temporary/capacity: \(8Q\) bytes.

That is approximately \(32Q\) bytes plus trace headers. A few hundred million support points therefore explain a 10–14 GB transient without invoking a mysterious full-window copy.

The likeliest peak driver is the old `buildFragGrid`: it collected every support RT, sorted roughly \(10^8\) entries to obtain only ~1,400 distinct RTs, then built CSR while all original XICs remained alive. The current source explicitly describes that temporary at [DIAPseudoSpectra.cpp:716](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:716) and now consumes XICs during CSR filling at [DIAPseudoSpectra.cpp:741](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:741).

But “97 GB / 8 = 12 GB per window” is not a valid exact measurement. While the loop runs:

- The remaining compact store shrinks.
- Completed pseudo-spectra accumulate in `win_out`.
- Allocator high-water pages may remain resident after vectors are released.
- Up to 863,319 spectra are retained until the post-loop merge at [DIAPseudoSpectra.cpp:2654](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2654).

If 70% of spectra contain 500 peaks, their raw `Peak1D` arrays alone require at least
\(0.70 × 863319 × 500 × 16 ≈ 4.83\) GB, excluding vector capacity and metadata. The 87.9 GB end-of-loop RSS proves that a substantial amount is persistent output or retained allocator memory, not eight live windows.

### Is 10× + 256 MB defensible?

No.

Average compact bytes per window are \(20.849/24 = 0.869\) GB. The old estimate therefore booked approximately:

\[
10 × 0.869 + 0.256 = 8.95\text{ GB}
\]

against the claimed ~12.1 GB observed increment—about 35% under-booking. The current source acknowledges precisely this defect and uses 16× at [DIAPseudoSpectra.cpp:2344](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2344).

The admission policy is also not the lock convoy described in the prompt: both old and current code sleep outside `critical(admit)`. The current code does, however, read `/proc/meminfo` and `/proc/self/status` while holding the critical section, then sleeps for 20 ms at [DIAPseudoSpectra.cpp:2390](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2390).

Sixteen times compact bytes is a safer empirical guard, not a defensible model. The estimator should separately model peak count, expected traces \(F\), support points \(Q\), band halo copies and retained output. Stage-tagged RSS or allocator counters before/after partition, MTD, valley splitting, conversion and grid building would identify the peak conclusively.

## 3. MS1_TRACE and PRECURSOR_INFER

A 5.0× speedup on twelve nominal workers corresponds, under a simple Amdahl model, to an effective serial fraction of:

\[
s=\frac{1/5-1/12}{1-1/12}=12.7\%
\]

That is credible because only the actual band detector and valley-split chunks are parallel. The following remain serial or effectively serial inside `detectTraces_`:

- Sampling and sorting quantiles: [DIAPseudoSpectra.cpp:970](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:970).
- Building twelve complete band maps: [DIAPseudoSpectra.cpp:984](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:984).
- Concatenating band results: [DIAPseudoSpectra.cpp:1031](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1031).
- Span collection/sort and conversion from `MassTrace` to `Trace`: [DIAPseudoSpectra.cpp:1078](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1078).
- Unequal band work despite equal approximate peak counts.

`PRECURSOR_INFER` is serial because it is an intensity-ordered greedy seed-and-mark-used algorithm. It sorts indices, checks `used`, selects isotope partners and marks them consumed at [DIAPseudoSpectra.cpp:1157](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1157) and [DIAPseudoSpectra.cpp:1172](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1172). Parallelizing seeds naively changes which cluster wins and therefore changes output.

These phases are secondary:

- Making MS1 trace scale from 5× to 9× saves about \(83-410.9/9 = 37\) s, or 2.7% total.
- Deleting precursor inference entirely saves only 50.6 s, 3.7%.
- Deleting both phases saves 133.6 s, 9.8%, and speXtract would still take roughly 20:25.

Fix the MS1 serial preparation eventually, especially for sensitivity settings that explode the trace count. Do not mistake it for the competitive gap.

## 4. Why the reference implementation can be 3.1× cheaper in CPU

Equal output counts do not imply equal work. Runtime is governed by raw points, detected features and candidate pairs, not the final number of spectra.

Several algorithmic differences can plausibly produce a threefold intermediate-work gap:

1. **Early denoising and feature compression.** the reference implementation aggregates neighboring RT frames, removes points lacking proximate neighbors, smooths an m/z–IM sparse matrix, and fits 2D features before tracing. speXtract’s corresponding aggregation defaults are off at [DIAPseudoSpectra.cpp:821](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:821). the reference implementation’s published method therefore has an opportunity to discard noise before it becomes millions of fragment traces. [the reference implementation Methods](https://www.nature.com/articles/s41467-024-55448-8)

2. **A specialized feature detector versus generic greedy MTD.** speXtract invokes OpenMS `MassTraceDetection` separately over haloed bands at [DIAPseudoSpectra.cpp:919](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:919). The source itself records that increasing bands from 5 to 12 to 24 reduced trace CPU from 11,168 to 5,378 to 2,972 s because MTD candidate scanning is superlinear in band population at [DIAPseudoSpectra.cpp:2426](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2426). That is an algorithmic red flag, not a mere compiler issue.

3. **Fewer precursor hypotheses.** the reference implementation isotope-groups MS1 signals and discards peaks not belonging to a cluster. speXtract assigns unsupported singleton traces a default charge unless an optional gate is enabled at [DIAPseudoSpectra.cpp:2096](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2096). More precursor hypotheses mean proportionally more fragment scans and correlations.

4. **Different feature multiplicity.** speXtract documents 4.6 identified spectra per peptide versus the reference implementation’s 1.46 and acknowledges that one feature can become several RT/IM/charge hypotheses at [DIAPseudoSpectra.cpp:1414](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1414). Similar final spectrum counts can hide radically different precursor and fragment candidate sets.

5. **Brute-force candidate association.** speXtract indexes only by IM, then linearly scans that slice and tests RT before correlation at [DIAPseudoSpectra.cpp:1515](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:1515). A joint RT–IM feature index or feature-range intersection can avoid most candidate visits. The public the reference implementation paper does not disclose enough implementation detail to prove that it does so, but its retained m/z/IM signal ranges make it possible.

6. **Correlation support representation.** speXtract constructs a global ~1,300-point RT axis for every window, stores every fragment support, and repeatedly streams that support for every eligible precursor. the reference implementation correlates bounded precursor and fragment XIC features after feature segmentation. The paper does not publish sufficient low-level detail to quantify this difference, but it is a plausible major work reducer.

The honest conclusion is that scheduler tuning alone cannot close the gap. At an impossible perfect 96-core loop speedup, the measured loop still takes \(77333/96 = 806\) s. Adding the other phases gives roughly 16:58—still 1.74× the reference implementation.

## 5. Mitigations ranked by expected gain/risk

| Rank | Specific change | Expected effect | Risk / output | Cheap falsifier |
|---:|---|---|---|---|
| 1 | Rebenchmark the current unified task pool: window tasks, band tasks and precursor tasks share one 100-thread team ([loop](//Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2373)). | Expected 15–20% total wall reduction; hard ceiling 24.5% from 67.9→96 loop speedup. | Medium runtime/scheduling risk; intended output-neutral because writes use indexed slots. | Run dataset A with per-window digests and peptide-set equality; capture active-thread timeline. If mean loop use remains below ~80 cores, it failed. |
| 2 | Retain the current `buildFragGrid` rewrite: avoid the all-support RT temporary, parallel-fill CSR and consume XICs in place ([implementation](//Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:716)). | Approximately 3–4% total wall; potentially 2–4 GB less transient memory per heavy window. | Low–medium; output-neutral only if RT set and per-fragment arithmetic remain identical. | Compare per-window trace/grid digests and correlations near the 0.3 cutoff; log RSS before and after grid construction. |
| 3 | Test 24 trace bands under the task pool instead of the old rigid grid. | Source’s own dataset D data show 44.7% less trace CPU versus 12 bands; weighted ceiling is about 18% total wall, realistic 10–18%. | Medium; intended neutral, but finite halos and greedy MTD can make boundary behavior differ. Narrow-window halo memory may grow sharply. | Run the two heaviest and two narrowest windows at 12/24 bands; require identical trace digest and emitted spectra before a full run. |
| 4 | Replace the IM-only candidate scan with an exact joint RT–IM bin/posting index; preserve fragment order for correlation arithmetic. | Likely 4–10% total; absolute ceiling is the 38.8% of total wall represented by score. | Medium; output-neutral if boundary comparisons and summation order are preserved. | Use existing `stat_slice_ / stat_rtpass_` logging at [DIAPseudoSpectra.cpp:2684](/Users/kohlbach/Claude/speXtract/src/DIAPseudoSpectra.cpp:2684). If scanned/passed is below ~2×, abandon it. |
| 5 | Tile scoring fragment-major or by RT–IM cell so fragment CSR remains cache-hot across nearby precursors. | Roughly 10–25% of score time, or 4–10% total wall. | Medium–high; reordering floating-point sums can move borderline correlations and therefore change output. | Prototype on one heavy window; compare pair counts, hardware cache misses and all correlations within ±1e-5 of threshold. |
| 6 | Eliminate full band `PeakMap` copies using immutable spectrum/range views or one compact per-band index. | Perhaps 2–5% wall and 1–2 GB less transient memory per average window. | High implementation risk around OpenMS ownership; output-neutral in principle. | Instrument bytes copied during partition. If partition/copy CPU is below 2% and RSS is not peaking there, reject it. |
| 7 | Parallelize MS1’s quantile sampling, band materialization and result conversion—not the greedy isotope assignment. | About 2–3% total wall; ceiling 6.1%. | Low–medium; output-neutral if physical ordering is canonically restored. | Time the serial substeps individually. Stop if they total under 25 s. |
| 8 | Parallelize only independent setup in `inferPrecursors_`—index creation and perhaps sorting—while retaining serial greedy consumption. | About 0.5–1.5%; absolute ceiling 3.7%. | Low if ordering is preserved; parallel greedy clustering is output-changing and unjustified. | Profile the two sorts versus the seed loop. |
| 9 | Adopt the reference implementation-like early neighbor filtering/feature compression before MTD, or require isotope-supported precursors. | Potentially 25–50% loop-work reduction; isotope-support alone could cut score work by roughly 15% total. | **Output-changing.** The source already records that isotope support loses 0.78% of peptides and post-centroid frame aggregation lost 26%; these fail strict peptide-set equality. | Run only behind an experimental flag and require exact held-out peptide-set equality. Expect failure. |

Finally, the 16× admission estimator is a safety correction, not an optimization. It may reduce concurrency and worsen wall time. Its value should be calibrated from stage-specific peak allocations, not treated as a performance win.