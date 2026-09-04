• Reading the remaining pieces — the rest of `toTrace`, the OpenMS-path EPD call site, the banded merge, and the git history of these changes.

• Now let me look at the git history for these changes and find the OpenMS source locally.

• The old code is now cl• Now I need the actual OpenMS source. Let me check what OpenMS version this repo builds against, then fetch the EPD and MassTrace sources.

• I have everything I need from the code. Let me cross-check against the earlier review artifacts from today so I don't miss anything they caught.

• The earlier reviews raise two guard-hole claims about CHANGE 3 (subnormal `delta_rt` → `inv = inf`; `span = inf` → `inv = 0`). Let me verify how `delta_rt` is validated, and check a couple of other details.

• Review complete. I read the full diff (`git diff` — all three changes are uncommitted), the whole `TraceStore`/`splitIntegerTraces`/`FragRt` code, the lock-free patch, and the actual OpenMS source in the local checkout at `/Users/kohlbach/OpenMS` (unpatched stock, which is what the patch hunks modify). Verdicts first, then findings ranked.

  ## Verdicts

  - **CHANGE 1 (arena reserves): OUTPUT-NEUTRAL.** Pure allocation; cannot touch values, offsets, or order. Sizing provably never too small.
  - **CHANGE 2 (streamed valley splitting): OUTPUT-NEUTRAL.** The equivalence argument survives contact with the real OpenMS source — in fact it's *stronger* than stated. Two non-output defects found (one real perf regression, one broken ledger).
  - **CHANGE 3 (quantised RT gate): OUTPUT-NEUTRAL on every reachable input, but formally NOT OUTPUT-NEUTRAL as written** — there are two constructible inputs that hit UB in `bucketOf`. The 3-file digest A/B will pass; the claim "provably neutral" is false without a one-line guard. Also: ±2 is not "insurance", it is the exact tight bound — ±1 would be a genuine bug.

  ## Ranked findings

  **1. CHANGE 3 — UB in `bucketOf` on two constructible inputs (silent-results class, in principle).**
  `bucketOf` is `x <= 0.0 ? 0 : (x >= 65535.0 ? 65535 : (int)x)` (`src/DIAPseudoSpectra.cpp:2247`). NaN fails both comparisons and reaches `(int)NaN` — undefined behavior.

  - *Breaking input A:* `gate:delta_rt = denorm_min()`. Validation is only `setMinFloat_(..., 0.0)` (line 1607), so a subnormal passes. `inv = 1/denorm_min = +inf`. With a **single fragment** (span = 0, no widening), `x = (rt0 - rt0) * inf = 0 * inf = NaN` → UB cast. The old code passes that fragment through the exact test (`fabs(0) > denorm_min` is false); the new code's behavior is whatever the UB happens to emit. On x86-64 it lucks into neutral (both sides cast to the same garbage), which is exactly why your A/B won't catch it.
  - *Breaking input B:* fragment RTs `{-DBL_MAX, +DBL_MAX}` — both **finite**, so they survive the isfinite filter at line 3480. `span = inf`, widening gives `inv = 65000/inf = 0.0`, then `x = inf * 0 = NaN` → UB cast. Old code: the exact test on finite doubles behaves normally.

  Fix is one line: write bucketOf as `if (!(x > 0.0)) return 0; if (x >= 65535.0) return 65535; return (int)x;` (NaN then maps to 0, never reaching the cast), plus `if (!std::isfinite(inv)) inv = 0.0;` in `build` to inert the gate. Note `!(x>0)` also changes NaN `pc.rt` from UB to pq=0 — but NaN `pc.rt` then still diverges from the old code (old admits the whole IM slice since `fabs(NaN) > delta` is false; new rejects fragments with `q > 2`). That needs inf/NaN intensities upstream to occur; flag, don't fix.

  **2. CHANGE 2 — `out.reserve(hi - lo)` under-reserves; strictly heavier than what it replaced (perf only).**
  The old code reserved `out.reserve(split.size())` — the *child* count, known after EPD. The new code reserves the *parent* count (`src/DIAPseudoSpectra.cpp:1131`). Valley splitting exists to produce *more* children than parents; on a split-heavy chunk `parts[ci]` regrows geometrically and memmoves the whole Trace array 1–2 times. Small in absolute terms (Trace is a few dozen bytes), but it is a real regression against the old line, and free to fix (grow by a factor, or count children).

  **3. CHANGE 2 — the new `MemGuard` accounting is invalid (accounting only).**
  `MemGuard g_mt(MEM_EPD_MT, mt_live)` is constructed at line 1172, *after* the per-trace loop; the value it reports omits the reused `pk` buffer (which coexists with the `MassTrace mt(pk)` **copy** — the constructor copies, `MassTrace.cpp:40-48`), each MassTrace's `smoothed_intensities_` (a same-length `vector<double>` attached to every child — roughly doubling the per-point footprint the ledger charges), and vector capacities. The ledger cannot substantiate the claimed peak reduction; it undercounts the streamed payload by ~2×.

  **4. CHANGE 1 — the reserve misses the `nb == 1` path (incomplete, not a regression).**
  The single-band/degenerate path at line 3436 does `wst.absorb(bst[0])` into a just-emptied arena with **no** reserve — the exact geometric-regrowth defect the change claims to eliminate, surviving on the `w_bands == 1` / `thi <= tlo` path.

  **5. Latent (unreachable today): `absorb()` mixed-bins invariant.**
  `absorb`'s `bins.resize(base, 0u)` pads only *backwards* for earlier binless sources; a binful source followed by a non-empty binless source leaves `bins` shorter than `inten`, and `wst.bins[t.off + k]` at line 1142 would read out of bounds. Unreachable because both producers are all-or-nothing (see below), but `any_bins` in the reserve code hints at a mixed case that `absorb` cannot actually handle.

  ## Answers to your specific questions

  **CHANGE 1.**
  - *Is `any_bins` right given `absorb` does `bins.resize(base, 0u)`?* Yes at both sites. In `splitIntegerTraces` it is provably always **false** (dead but harmless): chunk stores are filled only via `toTrace` → `makeSpan`, which never writes `bins`. At the banded merge (line 3426) it is **exact**: `detectTracesInteger_` resizes `bins` to `inten.size()` after every accepted span (lines 1072–1073), so every non-empty band store has `bins.size() == inten.size()`, and an empty band contributes nothing to either arena — the two arenas stay aligned through every absorb, in any order.
  - *Can reserving `bins` to the inten total be too small?* No. Per store, `bins.size() ∈ {0, inten.size()}`; `absorb` grows `bins` only to the current inten base plus the source's bins, so `bins ≤ inten ≤ arena` after every step.
  - *Can the reserve raise peak memory?* Virtual, yes — it allocates the full final arena up front while all 48 source arenas (with their own geometric capacities) are live. Resident, no on Linux: untouched reserved pages don't commit, whereas geometric growth touches every page it copies and can overshoot capacity to ~2× final with old+new live during the last realloc. Worst-case theoretical peaks are roughly a wash; in practice the reserve wins. But "lowers peak" is only provable by an HWM measurement, and note the reserve cannot fix the source-side over-capacity, which exists regardless.

  **CHANGE 2.** Verified against `/Users/kohlbach/OpenMS/src/openms/source/FEATUREFINDER/ElutionPeakDetection.cpp`:
  - *Does the single-trace overload do anything the vector overload does not?* No — it does **less**. It is exactly `single_mtraces.clear(); detectElutionPeaks_(mt, single_mtraces);` (lines 312–318). The vector overload is `clear` + progress + a per-trace loop over the same `detectElutionPeaks_`. The `clear()` makes your reused `split` buffer safe (children are converted before the next call). The patch doesn't touch the single overload, and its nested path (which is what the old `splitValleys` executed inside your taskloop) is indeed the serial ordered loop shown in `patches/openms-epd-lockfree.patch`.
  - *Cross-trace noise/SNR, neighbours?* None exist. `win_size` comes from the trace's own `getAverageMS1CycleTime()` (first/last point of *that* trace); `smoothData` is per-trace Savitzky-Golay; `findLocalExtrema`'s `num_neighboring_peaks` means points *within the same chromatogram*; `computeMassTraceNoise`/`computeApexSNR` are per-trace and only run under `mt_snr_filtering_`. The only collection-wide routine, `filterByPeakWidth`, is **never called by `detectPeaks`** — it's a separate public method ("call it yourself", line 32–33 comment). So the equivalence holds for *any* width/SNR settings, not just off/false; your off/false premise was unnecessarily weak. Order is identical: per parent, children emit in the same order, parents iterate in the same order.
  - *`MassTrace(vector)` vs `MassTrace(list)`?* Identical semantics (`MassTrace.cpp:28-48`): both copy the point sequence in order into the internal `vector<Peak2D> trace_peaks_`; neither sorts, neither computes centroids. Same sequence in → same object.
  - One pre-existing UB shared by both paths, not a regression: `win_size = ceil(chrom_fwhm_ / scan_time)` with `scan_time = 0` for a ≤1-point trace is a `double→Size` cast of `inf` (line 387–388). Old and new code hit it identically.

  **CHANGE 3.**
  - *Is ±2 sufficient?* Yes — provably tight, not just safe. Exact-arithmetic gives |dq| ≤ 1 for exact-passing pairs (bucket width ≥ `delta_rt` always; widening only widens). With FP rounding, each floor can cross at most one integer boundary, and the two adverse crossings can only co-occur when the true values straddle adjacent integers with true dq = 0 — yielding computed dq = ±2, never ±3 (an upward cross of the fragment needs it just *below* integer k; a downward cross of the precursor needs it just *above* integer j; |x diff| ≤ 1 forces k − j ≤ 1). So ±2 is the exact bound — **with ±1 the gate would have a real, constructible false-reject bug** (`x_pc = j+δ₁`, `x_fi = j+1−δ₂`, both δ within rounding error). The "insurance" bucket is load-bearing.
  - *Clamps safe on both ends?* Yes. Fragments can never reach the 65535 clamp: fragment x ≤ `span*inv` ≤ 65000 by the widening test, and the widened `fl(span * 65000/span)` overshoots by at most a few ulp (≤ 65001). A precursor clamped to 65535 is ≥ 535 bucket-widths above every fragment — the exact test would reject those too. The low clamp (pq=0 for `pc.rt < rt0`) only makes the gate *more* permissive; any exact-passing fragment is then within one bucket of 0. `delta_rt <= 0` → `inv = 0` → all buckets 0 → gate inert → exact test decides → neutral. Empty input returns at line 3483 before `build`; single-element is safe; negative RTs are safe (`rt0` is the min, so fragment x ≥ 0).
  - *Memory/build cost?* The claim holds. The 8-byte `rt` array replaces the pre-existing `frag_rt` vector (built before this change), so net new is 2 B/fragment per window — kilobytes-to-megabytes against 6.9 TB of avoided reads per S30 run. Build is O(n) as claimed, though it's an *additional* pass: the old code filled `frag_im` and `frag_rt` in one loop; the new code does the `frag_im` loop plus two passes in `build` — same complexity, larger constant, amortised instantly by any window with precursors.

  **Bottom line for the A/B:** nothing here silently changes spectra on realistic data — the digest should come back identical, and if it doesn't, look elsewhere. The one thing I'd fix before shipping the neutrality *claim* is the `bucketOf` NaN/UB guard (finding 1); the one real perf regression is the `out.reserve(hi - lo)` under-reserve (finding 2).

