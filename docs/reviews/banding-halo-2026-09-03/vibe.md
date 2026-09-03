Based on my reading of `src/DIAPseudoSpectra.cpp`, here is my hostile review of the m/z banding mechanism.

---

## 1. Is the hypothesis right?

**The hypothesis is correct and the help text is wrong.**
The claim *"Traces cannot span more than trace:mass_error_ppm in m/z, so banding with a halo is exact"* (`src/DIAPseudoSpectra.cpp:909`, `src/DIAPseudoSpectra.cpp:1020-1021`) is **demonstrably false** for all three reasons you state. The code and comments themselves contain the evidence.

### Reason 1: Halo sizing — the magic 20× is unbounded

- **Code:** `src/DIAPseudoSpectra.cpp:1048-1049`
  ```cpp
  const double lo = edge[b] - edge[b] * ppm * 1e-6 * 20.0;
  const double hi = edge[b + 1] + edge[b + 1] * ppm * 1e-6 * 20.0;
  ```
- **Issue:** 20× is **arbitrary** and **underruns** the * claimed bound. Even with this fix (each edge now sizes its own halo), the factor is a guess.
- **Your fix:** Symmetric halo was broken; now each side is sized from its own edge. This addresses asymmetry, **not** the magic number.

### Reason 2: Traces **do** drift — the running centroid is the fatal flaw

- **OpenMS MassTraceDetection behaviour:** Per your description and consistent with standard centroid-updating trace growth: each new peak within `mass_error_ppm` of the **current** centroid is accepted, and the centroid is **recomputed** to include it.
- **Code evidence within speXtract:** `src/DIAPseudoSpectra.cpp:2911-2913` in the merging logic shows the *same* pattern:
  ```cpp
  while (b < pk.size() && fabs(pk[b].first - mz_sum / in_sum) <= mg_mz)
  { mz_sum += pk[b].first * pk[b].second; in_sum += pk[b].second; ...
  ```
  Here peaks are accepted within `mg_mz` of the **running** centroid `mz_sum / in_sum`.
- **Implication:** A trace can walk arbitrarily far. Consider:

  **Concrete Example 2 (trace drift):**
  1. Apex at m/z 1000.000, ppm=15
  2. Next peak at 1000.015 (within 15 ppm of 1000.000) → accepted, new centroid ≈ 1000.0075
  3. Next peak at 1000.030 (within 15 ppm of 1000.0075) → accepted, new centroid ≈ 1000.015
  4. Next peak at 1000.045 (within 15 ppm of 1000.015) → accepted...
  5. After N steps, span ≈ N × 1000 × 15e-6 = N × 0.015 Da

  **No finite multiple of ppm bounds the span.** The trace grows by **O(N × ppm × m/z)** over N peaks. Banding with *any* fixed halo cannot guarantee that a trace is entirely contained in one halo.

### Reason 3: Detection is not local — the set matters

- **Code:** Each band gets a **different subset** of peaks (`sub[b]` in `src/DIAPseudoSpectra.cpp:1040-1069`).
- **MassTraceDetection dependence:** Per your description, it is **greedy and order-dependent**, using an intensity-sorted apex list (`src/DIAPseudoSpectra.cpp:909`).
- **Concrete Example 3 (set dependency):**
  - Two bands: Band A has peaks at {100.0, 100.1, 100.3}, Band B has peaks at {100.2, 100.4}
  - With a 20 ppm tolerance at m/z 100, the halo overlap might include 100.1, 100.2, 100.3 in *both* bands' partitions
  - But a peak at **100.25** might be in Band A's halo but **excluded from Band B's** partition due to edge placement
  - In the full unbanded run, 100.25 joins the trace and shifts its centroid
  - In Band A, 100.25 is present → trace forms with centroid ~100.18
  - In Band B, 100.25 is absent → a different trace forms with a different centroid and profile
  - The **final centroid** determines which band keeps it (`src/DIAPseudoSpectra.cpp:1086-1087`):
    ```cpp
    if (c >= edge[b] && c < edge[b + 1]) per[b].push_back(std::move(mt));
    ```
  - **Result:** Different traces are found, kept, or discarded depending on banding.

**Verdict:** All three mechanisms are real, **no halo width can fix Reason 2 and 3**, and the help text is falsifiable.

---

---

## 2. Can banding be made exact?

| Approach | Exact? | Cost | Verification |
|----------|--------|------|--------------|
| **(a) Real bound on trace span** | **No** | N/A | Trace span is **data-dependent and unbounded** due to running centroid (Reason 2). No finite halo suffices. |
| **(b) Partition on gaps > max trace span** | **No** | N/A | Max trace span is unbounded (Reason 2), so no finite gap can guarantee no trace is cut. |
| **(c) Detect on whole window, parallelise differently** | **Yes** | **High** | Run MassTraceDetection on the full PeakMap without partitioning. Parallelise at a coarser grain: per-window (already done) or per-apex (would require rewriting MassTraceDetection's greedy loop into a task-parallel form). **Cost:** Likely a rewrite of OpenMS, which you forbade. |
| **(d) Accept approximation, remove machine & band-count dependence** | **No (but honest)** | **Medium** | **Pin band count to a fixed default (12), remove "auto" mode.** Verify by: (1) Ensure `perf:trace_bands` default is fixed; (2) Remove auto-derivation (`src/DIAPseudoSpectra.cpp:2392-2393`); (3) Document that results depend on this parameter. **Verification:** Run S30 at default bands and at bands=1, compare digests (already done: they differ). |

**Conclusion:** Only (c) is truly exact; it requires rewriting OpenMS. All other approaches either cannot be exact (a, b) or are approximations (d).

---

---

## 3. What should the default and "auto" mode be?

**Eliminate "auto" mode entirely.**

- **Evidence:** `src/DIAPseudoSpectra.cpp:2392-2393`:
  ```cpp
  if (n_bands <= 0)  // auto: enough bands that windows x bands covers every thread
    n_bands = (int)std::ceil((double)n_threads / std::max<size_t>(window_list.size(), 1));
  ```
  This ties scientific output to `n_threads`, which varies by machine. Your measurement shows **different accepted-peptide sets** at different band counts.

- **Default:** Keep **12** (current default). It is fast and the change is small but non-zero.

- **Recommendation:** 
  - Change `perf:trace_bands` default to 12
  - **Remove the `0 = auto` option** from the help text and parser
  - Add a warning: *"Banding is an approximation; higher counts may change results slightly"*
  - Do the same for `perf:ms1_trace_bands`

**Auto mode should not exist at all.** The current code makes results **machine-dependent**, which violates reproducibility.

---

---
## 4. How would you measure the approximation error?

**Comparison:** Banded run vs **bands=1** (unpartitioned) on the same window.

**Statistic:** 
- **Primary:** Jaccard similarity of *accepted peptide sets* (your gate)
- **Secondary:** 
  - Spectrum-level: fraction of spectra with different m/z/intensity profiles
  - Trace-level: count of traces that appear/disappear between banded and unbanded
  - Mass error: distribution of centroid shifts for traces found in both

**Method (given 18 min / 160 GB for unbanded):**
1. Run **one** representative window unbanded (bands=1) → reference trace set T₁
2. Run the **same window** with bands=N → trace set T_N
3. Compute **symmetric difference** |T₁ Δ T_N| / |T₁ ∪ T_N|
4. Aggregate across a **stratified sample** of windows (e.g., 5 wide, 5 narrow, 5 medium)
5. Report **mean ± stddev** of the symmetric difference

**Cost:** One full window at bands=1 is ~18 min / 160 GB. For a 24-window diaPASEF run, this is 18 min × 24/24 = **18 min** for one window plus negligible for banded versions.

**Honest reporting:** Add a log line: *"Banding approximation: X% trace set difference vs unbanded (window sample)"*

---

---
## 5. Can parallelism be kept without partitioning?

**Yes, and you already have the infrastructure.**

- **Current state:** `src/DIAPseudoSpectra.cpp:2033` shows the code now uses a **master/worker task pool**:
  ```cpp
  // detectTraces_ distributes its bands as TASKS, which requires an enclosing parallel region;
  ```
- **Performance:** `src/DIAPseudoSpectra.cpp:2506-2510` shows banding **reduces total CPU** (11,168 → 2,972 s across 5/12/24 bands) because MassTraceDetection's cost is **superlinear** in peak count.

- **Solution:** **Keep the bands for performance, but fix the count.**
  - Banding is **not needed to fill cores** (task pool handles that)
  - Banding **is needed to reduce per-thread peak count** (superlinear scaling)
  - **Optimal:** Use a **fixed band count** (12) **regardless of threads**
  - **Cost:** No loss of parallelism; bands are tasks in the pool
  - **Benefit:** Results become **machine-independent**

**Answer:** Yes. The master/worker task pool (`src/DIAPseudoSpectra.cpp:1074-1075`, `src/DIAPseudoSpectra.cpp:2030-2040`) already decouples parallelism from banding. Bands are now **performance optimization**, not **parallelism mechanism**.

---

---
## Summary

| Question | Answer |
|----------|--------|
| **Hypothesis?** | **Right.** The claim is false for all three reasons; no halo fixes drift or set-dependence. |
| **Exact banding?** | **Only by rewriting OpenMS** (parallelise differently). All halo-based approaches are approximate. |
| **Default / auto?** | **Kill auto.** Default to 12, document approximation. |
| **Measure error?** | **Jaccard vs unbanded** on stratified window sample; report symmetric difference. |
| **Parallelism without partition?** | **Yes** — task pool already supports it; bands are for performance, not parallelism. |

**The help text in `src/DIAPseudoSpectra.cpp:909` and `src/DIAPseudoSpectra.cpp:1020-1021` must be corrected:** it falsely claims exactness. Replace with: *"Banding partitions m/z into concurrent tasks with a 20×ppm halo to reduce per-thread work; results may vary slightly with band count."*
