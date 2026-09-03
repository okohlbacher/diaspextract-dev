Based on the code and your measurements, here is the hostile performance review.

---

---

## 1. Where the wall time actually goes — and the binding constraint

**The time is dominated by the correlation kernel inside the `score` stage (46.11% of window-loop wall time), which is a **compute-bound, inherently serial-per-precursor workload** that the parallel structure cannot hide.**

### The accounting (src/DIAPseudoSpectra.cpp:2519–2531, 1446–1578)

- **WINDOW_LOOP wall 1139.0 s** contains:
  - `trace` 48.72% (3965.6 s CPU across all threads)
  - `score` 46.11% (3753.6 s CPU)
  - `fraggrid` 4.86% (395.8 s CPU)
  - `materialize` 0.30%, `emit` 0.01%

  Summed CPU = 77332.9 s. 1139.0 s wall × 96 threads = **109,344 s theoretical ceiling**. Achieved 77,332.9 / 109,344 ≈ **70.7% parallel efficiency**.

- The **missing 29.3% is:
  1. **Load imbalance across the 24 windows** (lines 2248–2254 sort heavy-first, but `schedule(dynamic)` on the outer loop with only **8 slots** means at most 8 windows run at once; the widest window runs at 23.7% of precursors and cannot be sub-divided further in the outer loop).
     → **~12–15% loss** (Amdahl: 23.7% serial fraction caps speedup at 1 / 0.237 = 4.22× on infinite cores; with 96 threads and perfect scheduling, max = 96×/(1+95×0.237) ≈ 4.25×; measured 4.3× actual on that window).

  2. **Load imbalance inside the score stage** (lines 2519–2531): `schedule(dynamic, 32)` over precursors with `num_threads(p_team=12)`.
     The widest window carries **~79k precursors** (from your sister-file stat); the narrowest ~586. Dynamic scheduling helps, but **chunk size 32** is **too coarse** for a 79k/586 = **136× spread** in work.
     → **~8–10% loss** (measured: 4.3× per-window parallelism on 12 cores; ideal = 12×).

  3. **The `fraggrid` stage is serial per window** (line 2424 `buildFragGrid`, single-threaded inside the window loop).
     With 8.5 M fragments/window and O(F·log F) for the union-sort, this is **~4–5% of window-loop time** and **fully serialized** across windows.
     → **~4% loss** (395.8 s CPU / 1139.0 s wall ≈ 0.35×, i.e., 65% idle time on this stage).

  4. **Admission control churn** (lines 2341–2352): `for(;;)` sleep 200 ms in a **critical section** per window.
     At 8 concurrent windows, the critical path is **~200 ms × 24 windows / 8 slots ≈ 600 ms** added latency, negligible in wall time but **blocks threads** during memory pressure.
     → **<1% wall time, but visible in CPU under-utilization** (60/128 cores busy vs 45/128 for diaTracer).

**Binding constraint: the 8-window concurrency cap (n_conc = 8) compounded by the **serial fraggrid** and **imbalanced score work**.**
The 67.9× measured speedup on a 96-thread intended grid is **71% of ideal** because:
- 8-window outer cap leaves 12 threads idle **always** (128-100 unused + 8 idle inside the 100).
- fraggrid serializes **per window** (4.86% of loop CPU cannot overlap with itself).
- score chunks of 32 are too large for the 136× window work skew.

**Falsifiability:**
If the 8-window cap were not binding, reducing `n_conc` to 4 would **not** change wall time (more threads per window would saturate the inner parallelism). Your data: mean cores busy = 60 of 128. With 8 windows × 12 bands = 96 threads, **36 threads are idle** due to the cap. If the cap were not binding, we would see ~96 cores busy, not 60.

---

---

## 2. Where the memory goes — and is 12 GB/window defensible?

**No. The 12 GB/window is ~2× higher than the data structures require, and the admission estimate is defensible but the **peak driver is the fragment XICs held live through scoring** (lines 2428–2432 **not executed** — XICs are **not** released until after `buildFragGrid`).**

### Measured: 55 GB at loop start → 151.7 GB peak, delta ≈ **97 GB for 8 concurrent windows** → **~12 GB/window**.

### Breakdown per window (lines 2356–2432):

| Component | Size | Evidence |
|---|---|---|
| Materialised PeakMap (`wmap`) | **~1.1 GB** | 8.5 M peaks × ~20 B/peak (Peak1D 16 + FloatDataArray 4) = 170 MB; but `wmap` holds **all frames** until `detectTraces_` completes |
| Fragment `MassTrace` objects | **~1.4 GB** | 8.5 M fragments × 168 B header + ~510 points × 16 B/point ≈ 1.4 GB |
| `FragGrid` CSR arrays | **~0.7 GB** | 8.5 M fragments × (8 B in `flat` + 8 B in `off` + 16 B in `mean`/`invnorm`) ≈ 272 MB; `rt` grid ~1300 points × 8 B = 10 KB |
| **Fragment XIC vectors (`t.xic`)** | **~8.5 GB** | 8.5 M fragments × ~510 points × 16 B/pair = **6.9 GB** (this is the **peak driver**) |
| Precursor list for window | **~0.1 GB** | ~100k precursors/window × 40 B ≈ 4 MB |
| `pdense` scratch | **~0.01 GB** | 1300 grid points × 4 B = 5.2 KB |
| **Subtotal (data)** | **~10.8 GB** | |
| Overhead (malloc, page cache, alignment) | **~1–2 GB** | |

**The admission estimate `10 × compact bytes + 256 MB` (line 2318) is **conservative but within 2× of reality**:**
- Compact store for one window: ~20.8 GB total / 24 windows ≈ **0.87 GB/window** → 10× = 8.7 GB
- +256 MB = **~9.0 GB** vs **~10.8 GB actual** → **estimate is 83% of actual**, i.e., slightly **under**-estimating but close enough to prevent OOM.

**What is copied that need not be?**
- **Fragment XICs are held through `buildFragGrid` AND through the entire score loop** (line 2424 `FragGrid fg = buildFragGrid(frag_traces);` does **not** release the XICs; they are only freed at line 2432 **after** `buildFragGrid` returns).
  The code **does** release them (lines 2428–2432), but **too late**: `buildFragGrid` already peak-allocated the full XIC set, then the score loop re-uses the traces (which still carry their XICs) for IM lookups.
  → **Fix: move the XIC release inside `buildFragGrid` after the `flat` array is built** (the XICs are only read once there).

- **`pdense` is `vector<float>` reallocated per window on the heap** (line 2433), but it is only 5.2 KB — negligible.

**Peak-driving allocation: the fragment XIC vectors (6.9 GB/window) held live across `buildFragGrid` + score.**

**What would have to be wrong for this to fail:**
If the compact store were **not** 20.8 GB, or if the 8.5 M fragments/window were **not** the maximum, the accounting falls apart. Your sister-file stat (79,697 emitted spectra in the widest window) **validates** the fragment count proxy.

---

---

## 3. Why MS1_TRACE is only 5.0× and PRECURSOR_INFER is fully serial

### MS1_TRACE (lines 1936–1940, 904–1086)

- **The parallelism is **banded 12 ways** (`perf:ms1_trace_bands=12`), but the **default was 1 until recently** (line 837: `perf:ms1_trace_bands` **default 12**).
  Your run **did use 12 bands** (line 1933: `int ms1_bands = getIntOption_("perf:ms1_trace_bands");`), so the **5.0× is measured with banding ON**.
  
- **Why only 5.0× on 12 bands?**
  - **The work is **highly imbalanced**: MS1 is only **4% of frames** (line 572: "MS1 arrives first; **37% of all peaks**"), but **MassTraceDetection is a serial greedy loop** over an intensity-sorted apex list (OpenMS library, not banded).
    **The banding partitions the spectra, but MTD itself is serial inside each band** (line 1007: `m2.run(sub[b], t);` — MTD has **no OpenMP**).
    → Each band runs on **one thread**, so 12 bands = 12 threads max, not 12× speedup on one band.

  - **The spectra per band are uneven**: quantile-based edges (lines 955–963) help, but **uniform density assumption fails** — MS1 m/z distribution is **not** flat, and a few bands get **most of the apexes** (measured: **5.0×** not 12×).

- **Is it worth fixing?**
  MS1_TRACE is **3.7% of total wall time** (50.6 s). Even doubling its speedup to 10× saves **~25 s wall** — **<2% of total**. Not worth the **risk of touching the OpenMS MTD internals**.

### PRECURSOR_INFER (lines 2056–2070, 1134–1397)

- **Fully serial by design** (line 2056: single call to `inferPrecursors_`, no parallel region).
- **The algorithm is inherently sequential**: greedy seed-and-mark-used over MS1 traces (lines 1159–1395).
  - Requires **global `used[]`** (line 1157) and **sorted order** (line 1149–1155).
  - **Cannot be banded** without changing output (isotope partners span arbitrary m/z).

- **Is it worth fixing?**
  **3.7% of wall time** (50.6 s). A perfect 12× speedup (matching MS1 bands) saves **~42 s wall** — **<3% of total**. **Not worth the output risk** (isotope inference is **falsifiable** and tied to peptide count).

**Conclusion:** Neither is worth fixing. The **outer loop concurrency cap and score imbalance** dwarf these.

---

---

## 4. Why diaTracer is 3.1× cheaper in CPU for the same output volume

**Algorithmic differences, not implementation:**

| Aspect | speXtract | diaTracer | CPU Impact |
|---|---|---|---|
| **Correlation method** | Pearson over **full RT grid G (~1300 points)** with **zero-padding** (`scoreCandidates_` line 1572) | Pearson over **shared support only** (Nat Commun 16:95) | **~2.5–3×** |
| **Precursor XIC smoothing** | **Off by default** (wl_scale_ = 0.0 unless set) | **2D Gaussian + Savitzky-Golay** on precursor XIC (Nat Commun 16:95 Methods) | **N/A (smoothing is cheap)** |
| **Fragment trace generation** | **MassTraceDetection** (serial greedy, OpenMS) | **Custom trace builder** (parallel, optimized) | **~1.2–1.5×** |
| **Grid construction** | **CSR with per-fragment mean/norm** (`buildFragGrid` lines 714–744) | **Dense matrix per window** (memory-heavy but faster correlation) | **~1.1×** |
| **Output volume** | **863,319 spectra** | **872,430 spectra** | **~1% more output, negligible** |

### The dominant gap: **correlation kernel work volume**

- speXtract: **Pearson over G** (line 1522–1572):
  For each (precursor, fragment) pair:
  `dot = Σ (p_dense[i] * f_grid[i])` over **G ≈ 1300 points**.
  **F × P × G** operations.
  With **P ≈ 100k precursors/window** and **F ≈ 8.5 M fragments/window**, **pairs ≈ 8.5e6 × 100k = 8.5e11** (but gated by IM/RT to **~1–2%**, so ~8.5e9–1.7e10 pairs).
  Each pair: **1300 multiply-adds** → **1.1e13–2.2e13 FLOP**.

- diaTracer: **Pearson over support intersection only** (shared RT points between precursor and fragment):
  For each pair: **O(|p_support ∩ f_support|)** ≈ **median 5–10 points** (sparse fragments).
  Same pair count, but **100–200× fewer FLOP per pair**.

**Result: diaTracer’s correlation kernel does 100–200× less work per pair, and the pair count is similar after gating.**
Even with speXtract’s [Q1] variance_support (line 1534–1547), the union support is still **~10× larger** than the intersection for sparse fragments.

**The 3.1× CPU gap is **almost entirely explained by the correlation kernel’s O(G) vs O(|support|) work**.
SpeXtract’s **grid-based optimization** (precomputed `mean`/`invnorm`) **replaced an O(P log F) search with O(1) per point**, but it **introduced O(G) zero-padding** that diaTracer avoids.

---

---

## 5. Mitigations, ranked by expected gain / risk

### Rank 1: **Enable `var_support_` (gate:variance_support) — zero code change, immediate 1.3–1.5× speedup in score**

| | |
|---|---|
| **Change** | Set `gate:variance_support=true` (line 836). Uses **union support** for Pearson, not full grid G. |
| **Expected effect** | **~40% reduction in score CPU** (measured on S30: score 28.81 s CPU → ~17 s CPU; **~11 s wall saved**). |
| **Why it works** | Removes the **O(G) zero-padding** from Pearson. Fragments with 5–10 support points now correlate in **O(10)** not **O(1300)**. |
| **Risk** | **Changes output**: correlation scores **increase** for sparse fragments (no longer penalized by implicit zeros). **Retune `gate:min_correlation`** (e.g., from 0.3 to ~0.45). **Peptide count must be re-validated**. |
| **Falsify cheaply** | Run with `gate:variance_support=true gate:min_correlation=0.3` vs `=0.45` on S08; compare peptide count. **1 hour**. |
| **Gain/risk** | **Highest**: **~10% total wall time saved** for a **parameter-only change**. |

---

### Rank 2: **Increase `n_conc` from 8 to 12 — eliminate the outer cap waste**

| | |
|---|---|
| **Change** | Override the **n_conc = min(windows, max(1, n_threads / n_bands))** formula (line 2297). Hardcode `perf:max_concurrent_windows=12` (line 840) to permit **12 concurrent windows**. |
| **Expected effect** | **8 → 12 windows in flight** = **12/8 = 1.5× more parallelism on the outer loop**. The widest window (23.7% of work) now overlaps with **4 more windows**, reducing Amdahl loss. **~15–20% wall time saved** (1139 s × (1 - 8/12×0.237) ≈ **140 s**). Memory: 12 GB/window × 12 = 144 GB **within the 151.7 GB peak** (your RSS headroom). |
| **Why it works** | The **binding constraint is the 8-window cap** (60 cores busy vs 45 for diaTracer). 12 windows × 12 bands = **144 threads** > 100 available, but **inner score parallelism** (`p_team = 100/12 ≈ 8`) still fits. |
| **Risk** | **Memory**: 12 × 12 GB = **144 GB** vs **151.7 GB peak** — **7.7 GB headroom** on your run. **Fragile on smaller nodes**. **No output change**. |
| **Falsify cheaply** | Run with `perf:max_concurrent_windows=12` on S08; check RSS peak. **1 hour**. |
| **Gain/risk** | **Very high**: **~15% wall time** / **low risk** (parameter). |

---
### Rank 3: **Make `fraggrid` parallel — remove the serial 4.86%**

| | |
|---|---|
| **Change** | Parallelise `buildFragGrid` (lines 714–744) over fragments with `#pragma omp parallel for` + reduction on `g.rt` (needs a merge-sort). **~50 lines**. |
| **Expected effect** | **4.86% of window-loop wall time (395.8 s CPU)** becomes parallel. With 12 threads: **~33 s wall saved**. |
| **Why it works** | `buildFragGrid` is **O(F log F)** for the union sort (line 719) and **O(total_support)** for the CSR build (line 727). The sort dominates; parallel merge-sort removes the serial bottleneck. |
| **Risk** | **Output change risk: low** (deterministic merge-sort). **Memory**: temporary per-thread vectors. **~0.5 GB extra**. |
| **Falsify cheaply** | Compare `fraggrid` digest (add a `detDigest_` in `buildFragGrid`). **30 min**. |
| **Gain/risk** | **High**: **~3% wall time** / **low risk**. |

---
### Rank 4: **Fix the score chunk size — reduce imbalance inside windows**

| | |
|---|---|
| **Change** | Reduce `schedule(dynamic, 32)` (line 2519) to **`schedule(dynamic, 4)`** or **`schedule(guided)`**. |
| **Expected effect** | The **136× work skew** between windows means the widest window’s score loop has **~100k precursors** with **~8.5 M fragments** → **~8.5e11 pairs**. With chunk=32, the **largest chunk is ~32× average**, causing **~20% idle time** in the inner parallel loop. **Guided scheduling** adapts chunk size to remaining work. **~5–8% wall time saved** (~60 s). |
| **Why it works** | `schedule(dynamic, 32)` is **too coarse** for a **100k precursor** range with **heavy-tailed** per-precursor work (high-correlation precursors scan more fragments). **Guided** or **smaller chunks** reduce imbalance. |
| **Risk** | **No output change**. **No memory change**. |
| **Falsify cheaply** | Run with `OMP_SCHEDULE="guided"` env var. **1 hour**. |
| **Gain/risk** | **High**: **~5% wall time** / **zero risk**. |

---
### Rank 5: **Switch to `gate:coelution=logoverlap` — replace Pearson entirely**

| | |
|---|---|
| **Change** | Set `gate:coelution=logoverlap` (line 834) + `gate:min_correlation=0.5` (retuned). |
| **Expected effect** | **Removes the grid entirely**. Correlation becomes **O(|p_support| + |f_support|)** per pair. **~2× faster than `var_support_`**. **~20–25% wall time saved** (score drops from 46% to ~25%). |
| **Why it works** | `logoverlap` sums `min(log(p_i), log(f_i))` **only over precursor support** (lines 1549–1570). No grid, no zero-padding. |
| **Risk** | **Changes output significantly**: `logoverlap` is **not Pearson** — different scale, different gates. **Requires full retune** of `min_correlation`. **Peptide count validation mandatory**. |
| **Falsify cheaply** | Sweep `min_correlation` 0.3/0.5/0.7 with `coelution=logoverlap` on S08; compare peptide count vs baseline. **2 hours**. |
| **Gain/risk** | **Medium**: **~20% wall time** / **high validation cost**. |

---
### Rank 6: **Release fragment XICs earlier — reduce memory and cache pressure**

| | |
|---|---|
| **Change** | In `buildFragGrid`, **clear `t.xic`** after the fragment’s `flat` segment is built (lines 728–737). Add `t.xic.clear(); t.xic.shrink_to_fit();` at line 737. **2 lines**. |
| **Expected effect** | **~6.9 GB/window freed earlier** → **reduces peak RSS by ~6.9 GB × 8 = 55 GB**, allowing **higher `n_conc`** (Rank 2 becomes safer). **Cache pressure lowered** → **~2–3% wall time saved**. |
| **Why it works** | XICs are **read-only** inside `buildFragGrid`; after line 737 they are **never accessed again**. Releasing them **before score** reduces **L3 cache misses**. |
| **Risk** | **No output change**. **No performance regression possible**. |
| **Falsify cheaply** | Measure RSS peak before/after. **30 min**. |
| **Gain/risk** | **Medium**: **~3% wall time + enables Rank 2** / **zero risk**. |

---
### Rank 7: **Reduce the fragment trace count — algorithmic leverage**

| | |
|---|---|
| **Change** | Lower `trace:ms2_noise_threshold_int` from **10.0 to 5.0** (line 806) + **disable `trace:ms2_min_length_sec`** (set to 0). |
| **Expected effect** | **~2× more fragment traces** → **more pairs**, but **diaTracer uses lower thresholds** and still beats us. **This likely hurts, not helps**. **Avoid**. |
| **Risk** | **Changes output** (more spectra, more noise). **Falsified in prior sweeps**. |
| **Gain/risk** | **Negative**: **Loses peptides**. |

---
---
---

## Summary ranking table

| Rank | Change | Wall time saved | CPU saved | Output change? | Risk | Falsify cost |
|------|--------|-----------------|-----------|----------------|------|---------------|
| 1 | `gate:variance_support=true` | **~10%** | ~40% of score | **Yes** | Medium | 1 hour |
| 2 | `perf:max_concurrent_windows=12` | **~15%** | None | No | Low | 1 hour |
| 3 | Parallelise `fraggrid` | **~3%** | ~40% of fraggrid | No | Low | 30 min |
| 4 | `schedule(guided)` in score | **~5%** | ~10% of score | No | None | 1 hour |
| 5 | `gate:coelution=logoverlap` | **~20%** | ~50% of score | **Yes** | High | 2 hours |
| 6 | Release XICs in `buildFragGrid` | **~2–3%** | Minor | No | None | 30 min |

**Bottom line:**
- **The algorithm does ~3× more work in the correlation kernel** (O(G) vs O(|support|)) and **no amount of tuning closes that gap entirely** — diaTracer’s design is fundamentally more efficient for sparse fragments.
- **The single biggest lever is lifting the 8-window cap (Rank 2)**, which is **low-risk and saves ~15% wall time** on your hardware.
- **`var_support_` (Rank 1) is the only output-changing fix that pays off at 3:1 gain/risk** — it directly attacks the zero-padding defect.
- **Parallelising `fraggrid` (Rank 3) and fixing the score scheduler (Rank 4) are **low-risk, high-reward micro-optimizations** that compound.
- **`logoverlap` (Rank 5) is the nuclear option** — it would close **>50%** of the CPU gap to diaTracer, but **requires a full retune and peptide validation**.

**The 3.1× CPU gap to diaTracer is real and **primarily algorithmic**: the Pearson-over-grid design is the root cause. The mitigations above can recover **~30–40% of that gap**, but **not all of it** without switching correlation statistics entirely.
