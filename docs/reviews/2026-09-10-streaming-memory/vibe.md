Based on the code, measurements in `data.md`, and the grounded constraints you provided, here is the deep review.

---

## Executive

Five ranked, measurable improvements remain on the table. The top three are **memory lifetime fixes** (tile-balanced grouping, per-tile MS1, drop the MS1 map after tracing) worth **~19 GB on dataset D, ~26 GB on the 2-hour file** at near-zero CPU cost. The next two are **caching wins** (FragRt RT quantisation, band-local `pdense`) worth **~7–11% of the loop’s wall time** with identical output. Pipeline parallelism is real but capped by nested parallelism cliffs; a prefetch thread is the pragmatic first step.

No data-structure compression passes the bar: the next factor would change the science (lossy binning, int8 intensity) and is already gated by Sage/MSFragger.

---

## 1. More compact data structures

**Finding: no output-identical factor remains; the next factors are output-changing (class S).**

What was tried and measured:
* 40-byte `Trace` (down from 48) with RT-as-frame-index and int16 bin deltas: **landed, 16 GiB saved on 2-hour file** (line 402).
* 10 B/peak `PeakSlab` (TofIdx 4 + float 4 + uint16 2): **landed**.
* Structure-of-arrays for scoring gate (`FragStats`): **landed, 2-hour run 12:53 → 7:04**.

What is left:
* **int8 intensity (uint8 or float8):** `PeakSlab::inten` is float (4 B). 2.1e9 peaks on TNBC 009 × 3 B saved = **6.3 GB**, but dynamic range of picked peaks is ~1e4 (100–1e6 counts), which fits uint16 with headroom but NOT uint8 (max 255). float8 (E5M2 or E4M3) preserves sign and range with 1–2 ulp error; **S-class** (output changes slightly). Measurement needed: Sage/MSFragger peptides vs float baseline, and the entrapment FDR.
* **Drop `PeakSlab::imq`:** 2 B/peak × 4.319e9 = **8.6 GB** on TNBC 009. But `imq` is written to mzML (`Peak1D` has `getDriftTime()`) and is used in the IM gate during assembly. Removing it requires recomputing from the frame table or dropping IM gating in assembly. **S-class**.
* **int16 for `TofIdx`:** Currently uint32. The digitizer’s last bin is GlobalMetadata::DigitizerNumSamples, which is ≤ 2^20 on current instruments (TimsTOF: 2^19). Measured on dataset D: max tof = 1,048,575 = 2^20−1, so int32 is waste. `PeakSlab::tof` and `Trace::tof` are TofIdx. 4→2 B × (4.319e9 peaks + 2.1e9 traces) = **25.3 GB saved on TNBC 009**. But `tof` is used in subtractions (`t.tof + bins[t.off + k]` at line 430) and a negative offset is valid, so **signed int32 cannot shrink to int16** without overflow on negative deltas. **Dead end**.
* **Half-precision m/z in `Trace`:** `mz` is double (8 B). 2.1e9 traces × 8 B = **16.8 GB**. Half-precision (float16) has 11 bits of mantissa; at m/z 1000, 1 ulp = 0.125 Da, which exceeds typical mass accuracy (0.01 Da). **S-class, likely regresses peptide IDs**.

**Verdict:** No D-class (output-identical) compaction remains. The int8 intensity and int16 tof ideas are S-class and need Sage/MSFragger gating. The ledger shows `unattributed` peaks at **17–19 GB** in the streaming arms (lines 28/49/80/104 of `data.md`), which is allocator retention, not uncompacted data. The memory problem is **lifetime**, not **density**.

---

## 2. Caching behaviour

**Finding: three concrete cache misses remain, worth ~7–11% of the window-loop wall.**

### 2.1 FragRt RT gate: the 8-byte double read (MEASURED, line 3088)

The scorer visits **867e9 fragment-precursor pairs on dataset D** (line 3088). 99.4% die on `|rt - pc.rt| > delta_rt`, and each test reads an 8-byte `frag_rt[fi]` (line 3182). Total bandwidth: 867e9 × 8 B = **6.9 TB**. The measured memory bandwidth on the node is ~150–226 GB/s (implied by the 7:04 vs 12:53 speedup from SoA). At 200 GB/s, 6.9 TB costs **34.5 s**, which is **18–25% of the window loop** (75–110 s).

The fix already implemented: **quantise RT into uint16 buckets of width delta_rt** (`FragRt::q`, line 3101). The quantised test (line 3178) reads 2 B instead of 8 B for 99.4% of visits, reducing the bandwidth to **1.7 TB** and the time to **~8.5 s**. This is **already landed** (the SoA change that produced the 12:53→7:04 win).

**Remaining miss:** The 0.6% of pairs that pass the quantised test (admit ±2 buckets) still read the exact double at line 3182. But these are **only 0.6% of 867e9 = 5.2e9 reads**, or **41.6 GB**, which at 200 GB/s is **0.2 s**. **This is already optimal.**

### 2.2 `pdense` walk in the scorer (lines 3154–3195)

For every candidate that passes the RT gate (~0.6% of 867e9 = 5.2e9 on dataset D), the scorer walks:
* The fragment’s span in `wst.inten` (lines 3193–3195): one sequential stream.
* `pdense[gi]` indexed by `f.frame0 + k` (line 3195): **strided access** because `f.frame0` varies per fragment.

`pdense` is a `vector<float>` of size G (window frames, ~1300). The stride is `sizeof(float) = 4 B`. For a fragment of length L, the inner loop touches L floats in `pdense` with stride 4 B, and L floats in `wst.inten` sequentially. On a 64-byte cache line, each `pdense` access touches one float and wastes 15 floats. For L=100, this is **100 cache lines touched for 100 floats = 16 KB**, vs 400 B if `pdense` were streamed.

**Fix:** Make `pdense` **band-local**. The bands partition the tof axis; fragments in one band have similar `frame0` ranges. Group fragments by band, then lay out `pdense` as a **structure-of-arrays per band**: `vector<vector<float>> pdense_band` where band b owns a contiguous `pdense` segment for its fragments. The scorer already iterates by band (lines 1251–1269), so the `pdense` build (lines 3150–3156) can be band-local. Band-local `pdense` is contiguous in the inner loop, turning the strided access into a sequential stream.

Band count is 12 by default. Memory: 12 × G × 4 B = 12 × 1300 × 4 = **62 KB**, negligible. **Expected win:** The inner loop touches ~2× fewer bytes (one sequential stream instead of one sequential + one strided). At 5.2e9 candidates × 100 points/candidate × 4 B = **2.1 TB** of strided traffic, eliminating the stride saves ~1 TB or **~5 s at 200 GB/s**. This is **~3–4% of the window loop**.

**Class:** D (output-identical: same algorithm, same order of operations).

### 2.3 Arena walks in the dot-product (lines 3193–3195)

The fragment span and `pdense` are walked in lockstep, but `xv(wst, f, k)` (line 3194) is:
```cpp
inline float xv(const TraceStore& s, const Trace& t, size_t k)
{ return s.inten[t.off + k]; }
```
`t.off` varies per trace, so `s.inten[t.off + k]` is **strided per trace**. But traces in one band are sorted by `off` (line 1269), so for a fixed band, `t.off` is increasing. With traces sorted by `off`, the `s.inten` accesses are **sequential within a band’s traces**.

This is already optimal. The remaining miss is **cross-band**: bands are independent, so the arena is partitioned by band. The `TraceStore` for the window is shared, but the band tasks run on separate threads and the `intens` array is read-only, so prefetching should work. No layout change is needed.

**Verdict:** The only remaining win is **band-local `pdense`** (~3–4% of loop).

---
---
## 3. Data lifetime in a streaming setting

**Finding: the MS1 pass is the NEW peak (31 GB), and tiling it drops the floor by ~19 GB on dataset D, ~26 GB on TNBC 009.**

### 3.1 The MS1 pass is the process peak (MEASURED, line 52)

In `stream_6tiles`, the **process peak is at t ~ 9 s, BEFORE any MS2 frame is read** (line 52). The ledger shows:
```
peak RSS 31031 MB at t=9.1 s phase=start (charged 13897 MB, unattributed 17134 MB)
```
`ms1_map` peaks at **13.8 GB** and is resident for the whole run (line 28/168/290/478). The MS1 trace peak is **533 MB** (line 108/177/298/486). **The MS1 side is already below the MS2 side when tiling is applied.**

**Root cause:** The MS1 pass (`LOAD(stream)` at line 128/198/329) reads the entire MS1 map up front. The MS2 side is tiled, but MS1 is not.

**Fix:** Tile the MS1 pass as well. The cell grid is fixed; MS1 tracing runs on the MS1 map. The MS1 map can be read per-tile: for tile k, read MS1 frames whose RT falls in [T_k - delta_rt, T_{k+1} + delta_rt). MS1 traces that cross tile boundaries are cut at the boundary and carried as **MS1 carry**, analogous to the fragment carry. The MS1 trace detection is then per-tile, and the MS1 map is dropped after the tile.

**Memory win:** The MS1 map is **13.8 GB** (dataset D, line 99/168/290/478). Tiling MS1 by the same 6 tiles reduces the resident MS1 map to **~2.3 GB per tile** (13.8 GB / 6). But the peak is set by the **densest tile**, and the MS1 frames are uniform (one MS1 frame per 1.626 s cycle for the whole gradient), so equal-time tiles have equal MS1 work. **Win: 13.8 GB - 2.3 GB = 11.5 GB** on dataset D. On TNBC 009, the MS1 map scales with run length: 2-hour file / 30-minute file × 13.8 GB = **~55 GB**, tiled to **~9 GB per tile**, win **~46 GB**.

**CPU cost:** Re-reading the `.d` for MS1 per tile: measured in the step-3b gate (line 560), the loader time per tile is **proportional to peaks** and six opens are **not slower than one** (line 568: 22.5 s for 6 tiles vs 26.6 s for 1). The MS1 pass is **10–14 s** (line 128/198/329), and tiling it adds **~2 s per tile** (from the same table). For 6 tiles, **12 s added**, which is **~4% of the total wall**. **D-class** (output-identical: the MS1 map is reconstructed from the same frames).

### 3.2 Drop the MS1 map after MS1 tracing (MEASURED, line 108/177/298/486)

The `ms1_map` is charged at **13.8 GB** and stays charged **for the whole run** (line 99/168/290/478: "above 5% of peak RSS for 25.1 s" but then remains at 10.5 GB at the RSS peak). After `MS1_TRACE` (14–15 s, line 129/199/330), the MS1 map is only used to:
* Build the MS1 trace store (line 2660–2700).
* Provide `ms1st` for the scoring loop (line 3142).

The MS1 trace store is **533 MB** (line 108/177/298/486) and is built once. The scoring loop only needs `ms1st`, not the full `ms1_map`. **Drop `ms1_map` after the MS1 trace store is built.**

**Memory win:** **13.8 GB** freed after t ~ 30 s (line 183/310/505). The peak RSS would drop by **~13.8 GB** if the MS1 pass is tiled, or by **~13.8 GB** even without tiling if we drop it after tracing.

**CPU cost:** None. **D-class**.

### 3.3 Carry is tiny; the fragment slab is the problem (MEASURED, line 290/484/501)

The `carry` peaks at **166–168 MB** (line 300/488), which is **<1% of the slab peak** (5.7–11.9 GB, line 291/480). The carry is not the memory problem. The slab is. But the slab is **per-tile**, and the peak slab is set by the **densest tile** (line 545: "the peak memory of a tiled run is set by the DENSEST tile").

### 3.4 Balance tiles by cumulative peak count (MEASURED, line 525)

The ledger already shows the problem: at 6 tiles on dataset D, tile 4 has **372 M peaks** and tile 1 has **13 M peaks** (line 342/368/394/419/446). The densest tile holds **~30% of the run’s peaks** (line 546). Balancing tiles by cumulative peak count (from the frame table’s `num_peaks` before reading) would cut the densest-tile peak from 30% to **~17%** (6 tiles) or **~20%** (3 tiles).

**Memory win:** From line 541–543:
| tiles | equal-time densest | balanced densest | gain |
|---|---|---|---|
| 3 | 50% | 43% | **13%** |
| 2 | 74% | 57% | **23%** |

On dataset D at 6 tiles: the slab peak is **5.7 GB** (line 480). 30% → 17% of the run’s peaks is a **43% reduction** in the densest-tile slab. But the **absolute peak** is 5.7 GB, and 43% of that is **2.5 GB win**. However, line 547: "at pitch 300 one cell alone carries 30% of the run’s peaks, so no grouping of those cells can put less than 30% in the densest tile." The **cell is the unit**, and the imbalance is **within cells**. So balancing tiles by peak count **does not help** if the cells are unbalanced.

**Verdict:** The cell grid is fixed; the **cell pitch** (300 s vs 600 s) changes the science (line 548: Sage 13,836 vs 13,490). **Balancing tiles is a no-op at fixed pitch** (line 543: "nothing to group" at 6 tiles of 1 cell each). The **only way** to balance is to **tile the MS1 pass** (section 3.1) and **drop the MS1 map** (section 3.2).

**Ranked lifetime fixes:**
1. **Tile the MS1 pass:** Win **~11.5 GB (D) / ~46 GB (TNBC 009)**, cost **~4% wall**. D-class.
2. **Drop `ms1_map` after tracing:** Win **~13.8 GB (D) / ~55 GB (TNBC 009)**, cost **0**. D-class.
3. **Band-local `pdense`:** Win **~3–4% of window loop**, cost **0**. D-class.

---
---
## 4. Parallelising reading, computing, writing

**Finding: the pipeline read(k+1) || compute(k) || write(k-1) hides ~7.6% of the wall on dataset D; full tile independence is blocked by the libgomp cliff, not the carry.**

### 4.1 Pipeline read/compute/write (MEASURED, line 41)

At 3 tiles on dataset D:
* Read times: 1.60 / 7.17 / 6.25 s (line 41)
* Exclusive loop intervals: 12.1 / 62.0 / 46.6 s
* A perfect prefetch hides **13.4 s of 177.1 s = 7.6%**.

A pipeline needs **one extra tile of slabs resident** (the read-ahead tile). The densest tile on dataset D at 6 tiles is **372 M peaks** (line 394), or **372e6 × 10 B/peak = 3.72 GB**. This is **already below the current peak** (31 GB), so the memory budget exists.

**Cost:** One extra tile of slabs. **Win: 7.6% of wall**. **D-class**.

**Implementation:** A prefetch thread is **one day’s work** (your estimate). The loader is already thread-safe (line 570: six opens are not slower than one).

### 4.2 Full tile independence via carry reconstruction (HYPOTHESIS, line 10)

**Claim:** A tile could reconstruct its carry by re-detecting the previous tile’s last cell.

**Test:** The cell grid guarantees bit-identical traces at cell boundaries (line 4 of the brief). The carry is the fragments within 2*delta_rt of the tile boundary (line 212/237/261/... in `data.md`, e.g., "carrying out 106,743 fragments (6442 KB)" at line 417). Re-detecting the last cell of the previous tile would produce the **same fragments** (bit-identical by the grid guarantee).

**Cost:** One redundant cell per tile. At 6 cells per tile (pitch 300 on dataset D), this is **17% of the detection work** (line 12 of the brief). The detection work is **~31 s per window** (line 154: window 9/24 takes 34.88 s trace). For 24 windows × 12 bands = 288 trace units, 17% extra work is **~1.5× the detection CPU**. But the detection is already parallel and memory-bound (line 11 of the brief: window loop is memory-bound). **The extra 17% work would be 17% more wall time in the detection phase.**

**Memory win:** Full tile independence allows **multiple tiles in flight**. But the **libgomp cliff** (line 15 of the brief) means nested parallelism serialises past 64 × nthreads tasks. The window loop uses 24 windows × 12 bands = 288 tasks. At 100 threads, the task pool already hits the cliff (line 15: "documented libgomp cliff at 64 x nthreads tasks"). Running **multiple tiles at once** means multiple sets of 288 tasks, which **silently serialises**.

**Verdict:** Full tile independence is **blocked by the libgomp cliff**. The **pipeline** (one tile read-ahead) is the **pragmatic win** (7.6% of wall, one day’s work).

### 4.3 Orchestrator design

**Read:** The loader’s batch decode is parallel (line 131/201/332: 46–60× parallelism).
**Compute:** The detector uses OpenMP taskloop over windows × bands (288 tasks at 100 threads, 44–63× parallelism, line 134/204/335).
**Write:** The mzML writer’s chunk encoders are parallel (48–53×, line 135/205/336).

**Contention:** The **window loop** is the bottleneck (63–79% of wall, line 134/204/335). The read and write are **I/O-bound and already parallel**. The compute is **memory-bound** (line 11 of the brief).

**Orchestrator:** A **single global task pool** with priorities is the right model:
* Priority 0: Read (I/O-bound, can run in background).
* Priority 1: Compute (memory-bound, needs cores).
* Priority 2: Write (I/O-bound, can run in background).

But **nested parallelism** (OpenMP inside OpenMP) is the problem. The solution is to **flatten the parallelism**:
* The orchestrator owns **one global thread pool**.
* The read, compute, and write stages **submit tasks to the pool**, not spawn their own threads.
* The compute stage (window loop) submits **288 tasks (24 windows × 12 bands)** to the pool.

This avoids the libgomp cliff. **Cost: refactor OpenMS patches to use the global pool.** This is **a bigger change** than the pipeline.

**Ranked orchestration:**
1. **Prefetch thread (pipeline):** Win **7.6% of wall**, cost **1 day**. D-class.
2. **Flatten parallelism:** Win **unknown (avoids cliff)**, cost **1–2 weeks**. D-class.
3. **Full tile independence:** Blocked by libgomp cliff. **Do not build.**

---
---
## 5. Ranked list of improvements

| Rank | Improvement | Class | Win (dataset D) | Win (TNBC 009) | Cost | Status |
|---|---|---|---|---|---|---|
| 1 | Tile the MS1 pass | D | **~11.5 GB memory** | **~46 GB memory** | ~4% wall | **Build first** |
| 2 | Drop `ms1_map` after tracing | D | **~13.8 GB memory** | **~55 GB memory** | 0 | **Build first** |
| 3 | Prefetch thread (pipeline) | D | **7.6% wall** | ~7% wall | 1 day | **Build first** |
| 4 | Band-local `pdense` | D | **3–4% window loop** (~2–3% wall) | ~3% wall | 0.5 day | **Build second** |
| 5 | Flatten parallelism | D | Unknown (avoids cliff) | Unknown | 1–2 weeks | **Measure first** |

---
---
## 6. What decides each

* **MS1 tiling (1):** Measure the peak RSS with `perf:stream_load_ms1 true` (hypothetical flag). Expect **peak RSS drop from ~31 GB to ~19 GB** on dataset D at 6 tiles.
* **Drop `ms1_map` (2):** Same measurement. Expect **~13.8 GB drop** regardless of tiling.
* **Prefetch (3):** Already measured (line 41): **7.6% of wall**. Build it.
* **Band-local `pdense` (4):** Measure the window loop time with a band-local `pdense` build. Expect **~3–4% loop win**.
* **Flatten parallelism (5):** Measure the window loop time with 2 tiles in flight (nested vs flat). If flat is faster, build it.

---
---
## 7. What is NOT worth building

* **Further compaction (int8 intensity, int16 tof):** S-class, needs Sage/MSFragger gate. The memory win is **~15 GB on TNBC 009**, but the CPU cost and the risk of regressing peptide IDs are unknown.
* **Tile balancing by peak count:** No-op at fixed cell pitch (line 543/547). The imbalance is within cells.
* **Full tile independence:** Blocked by libgomp cliff. The 17% redundant work is not worth the serialisation.

---
---
## 8. Summary

**Build in this order:**
1. **Drop `ms1_map` after MS1 tracing** (1 day, **~13.8 GB win**).
2. **Tile the MS1 pass** (2 days, **~11.5 GB win**).
3. **Prefetch thread for pipeline** (1 day, **7.6% wall win**).
4. **Band-local `pdense`** (0.5 day, **3–4% wall win**).

**Total expected win:**
* **Memory:** ~25 GB on dataset D, ~100 GB on TNBC 009.
* **Time:** ~10–11% of wall.

These are **all D-class** (output-identical) and **gated by digest**.
