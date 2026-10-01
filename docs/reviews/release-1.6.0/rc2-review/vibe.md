# Adversarial Review Findings: DIAspeXtract 1.6.0 rc2

---

## BLOCKER

**1. src/diaspextract.cpp:6124-6125 | minlen estimator depends on thread count**
- **What is wrong**: The sample chunk count for minlen estimation uses `nchunk = std::max(1, std::min((int)ms1_map.size(), 4 * omp_get_max_threads()))`, making the sample set different at different thread counts.
- **Failing input**: Any run executed at `-threads 1` vs `-threads 2` (or any other counts) will sample different MS1 peaks, leading to different FWHM estimates and thus different `min_length_sec`.
- **Real-world impact**: Yes — the adaptive minlen will differ across thread counts, violating invariant 3 (per-run estimator must be deterministic).
- **Changes output at defaults**: Yes.

---

**2. src/diaspextract.cpp:6145-6147 | twin_rt_frames auto: division by zero / NaN / overflow**
- **What is wrong**: `n = med > 0.0 ? std::max(1, (int)llround(med / cycle)) : 1;` performs `med / cycle` where `cycle` (from `ms1_store.cycle_`) can be 0 (no MS1 frames / irregular timing), NaN, or produce a value that overflows `int` when cast.
- **Failing input**: A run with no MS1 frames (cycle=0), or where the median FWHM is so large relative to cycle that `med/cycle` exceeds `INT_MAX`. Also runs where cycle is NaN (e.g., from invalid frame timestamps).
- **Real-world impact**: Yes — division by zero is undefined behavior (typically crash), NaN propagation yields unpredictable results, and overflow is undefined.
- **Changes output at defaults**: Unknown (may crash before output).

---
**3. src/diaspextract.cpp:7194-7205 | frag_traces sort: non-total order comparator with parallelSort_**
- **What is wrong**: The comparator for `parallelSort_` over `frag_traces` lacks a final tie-breaker. For traces equal in all compared fields (im, m/z, RT, apex, len, npts, frame0, bframe, rt_at), it returns `false` for both `a<b` and `b<a`, making them equivalent. `parallelSort_` chunks the data (chunk count via `parTasks_`, which depends on thread count) and merges; equivalent elements can be ordered differently at different thread counts as chunk boundaries change.
- **Failing input**: Any run producing two fragment `Trace` objects with *exactly* identical fields in the comparator. This is possible with duplicate MS2 peaks in the input (e.g., synthetic data or detector noise producing identical points).
- **Real-world impact**: Theoretical but code-allowed — violates invariant 1 (output-identical across threads).
- **Changes output at defaults**: Yes.

---
---
## HIGH

*(None identified.)*

---
---
## MEDIUM

**4. CHANGELOG.md:71, README.md:237 | minlen fallback condition incomplete**
- **What is wrong**: Documentation states fallback to 3 s occurs only when there are "fewer than 100 measurable traces". The code falls back *also* when `cycle <= 0.0` (line 6137: `if (w.size() >= 100 && cycle > 0.0)`).
- **Failing input**: Documentation text.
- **Real-world impact**: No (documentation only).
- **Changes output at defaults**: No.

---
---
## LOW

**5. src/diaspextract.cpp:135-145 | teamHelpersQueued_ potential leak**
- **What is wrong**: `teamHelpersQueued_` is a global atomic counter incremented when spawning helper tasks in `teamFor_`. If a helper task is queued but never executed (e.g., due to OpenMP runtime resource constraints), the decrement in the task body never runs, leaking the counter. While `nt` is capped at team size, a pathological case (e.g., very small team, large `n`) could theoretically cause the counter to saturate, preventing future helpers from being spawned.
- **Failing input**: A run with `OMP_THREAD_LIMIT=1` and a very large `n` in a `teamFor_` call.
- **Real-world impact**: Theoretical — would manifest as performance degradation, not incorrectness.
- **Changes output at defaults**: No.

---
---
## Answers to Numbered Questions

1. **FINE** — `stdSortPar_` (libstdc++13 introsort replay, else std::sort), `parallelSortTotal_` (total-order callers), `sortExact_` (falls back to std::sort on ties), `mzOrder_` (stdSortPar_) each provably return std::sort’s sequence on the target platform. libstdc++13: stdSortPar_ replays std::__introsort_loop + insertion sort exactly; other libs fall back to std::sort. MSVC/macOS: stdSortPar_ uses std::sort. Ties are preserved identically for total orders; for non-total orders, std::sort’s behavior is unspecified but consistent on a given platform.

2. **NOT FINE** — `parallelSort_` in the window’s serial stages equals std::sort *only for total orders*. The frag_traces sort comparator is *not* a total order (no final tie-breaker), so equivalent fragment traces can be reordered at different thread counts via `parTasks_` chunking. This violates invariant 1.

3. **NOT FINE** — minlen sample is *not* thread-independent: `nchunk = std::max(1, std::min((int)ms1_map.size(), 4 * omp_get_max_threads()))` makes chunking and thus the sampled traces depend on thread count. It runs on the same MS1 map (pre-conversion), same tolerances, independent of stream-load/dnoise, but thread count breaks determinism.

4. **FINE** — isotol stride sample is thread/tiling-independent (stride = ceil(N/200000), schedule dynamic 256). Ties at grid argmax go to wider tolerance (deterministic). N<2 or no probes: fallback to 0.05. No control traces: J=0 for all x → best=0 → t=0.002 clamped to 0.01. Measured value is stamped and logged exactly as used.

5. **NOT FINE** — twin_rt_frames auto: `llround(med / cycle)` has division by zero if `cycle == 0`, undefined if `cycle` is NaN, and integer overflow if `med/cycle` is huge. `cycle` is the run’s median MS1 cycle from `ms1_store.cycle_`; can be 0/NaN with no frames or irregular timing. Precursor empty: `fw.empty()` → n=1. Seed traces all <3 points: `xicFwhm` returns -1 → `fw` empty → n=1.

6. **FINE** — No concrete order dependence, transitive over-fold, or counting/folding mismatch identified in `mergeTwins_`. The cell check (partition_point on global tile boundaries) correctly prevents cross-cell folds. `-assembly:twin_rt_frames -1` restores pre-1.6.0 same-frame-only behavior.

7. **FINE** — Fused peak key = kq_best * (log_key ? log(1+Σai) : Σai) where Σai ≥ ai_best and log(1+Σai) ≥ log(1+ai_best), so fused key ≥ best member’s key. Same IM weighting (ai = IM-weighted apex). NaN/zero filtered pre-fusion. Float vs double: computation in double, stored as float; sum order is deterministic (m/z order), so rounding is consistent across paths.

8. **FINE** — Pipelined writes: tile k written before k+1 (driver waits for tile k’s windows, then spawns writer in tile order). Carry: per-window CarryGate with atomic ready counter ensures in-order hand-off. malloc_trim: called after write, OS-dependent. teamHelpersQueued_: capped at team size, decremented in task body before work. onPipeDriver_: thread_local, reset on exit.

9. **FINE** — All pipelined exception paths are caught: window body has try/catch setting `worker_err`, writer tasks set `drv_err`, driver loop has outer try/catch. teamAssist_ calls PullJob_::pull which has try/catch. The e2e falsifier (12b) exercises the twin fold path in the pipelined writer via the normal window task flow.

10. **MEDIUM** — Docs match code except: CHANGELOG/README say minlen fallback only on "< 100 traces", but code also falls back when `cycle <= 0.0`. No scrub violations found.

11. **FINE** — b592804’s 12b check verifies no folding on twin-free fixture and correct header (`spx:twin_merge` starts with "MS1 frames up to..." for auto, "same frame" for -1, "off" for -1 and twin_im_tolerance -1). Would fail if cross-frame fold incorrectly triggered on the fixture.

---
---
## Summary

- **3 BLOCKER** issues violate core invariants (output-identical, deterministic estimators).
- **1 MEDIUM** documentation discrepancy.
- **1 LOW** theoretical resource leak.
- All numbered questions answered; cross-frame fold, parallel sorts, and estimators are otherwise sound.
