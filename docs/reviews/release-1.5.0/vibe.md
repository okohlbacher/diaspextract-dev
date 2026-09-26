## Code review findings for DIAspeXtract 1.5.0

Ranked by severity. File:line refers to the diff in Section A unless noted as Section B.

---

### **SEVERE** (would change output or crash)

1. **src/diaspextract.cpp:2363**
   gate:adaptive help string does not describe the `"auto"` mode. `setValidStrings_` accepts `{"off", "faint", "auto"}` (line 2364) but the help only documents `"faint"` and `"off"`. Users cannot learn that `"auto"` exists from `--help`. This is a documentation-correctness bug that will mislead users.

2. **tests/test_*.cpp: missing**
   No new tests exercise the gate modes on synthetic traces. The existing test changes only cover the opentims correction path (`test_dnoise_ms1.cpp`, `test_tdf_load.cpp`). No test validates concentric, colocation, shrinkage, adaptive faint, or cap_rank evidence on controlled inputs.

3. **src/diaspextract.cpp:2361**
   assembly:cap_rank `"umpire"` help claims the key is `r^2 x ln(1+I)`, but the implementation (diff line 3199) computes `std::max(c_raw,0.0) * std::max(c_raw,0.0) * std::log1p(inten)`, i.e. `(max(r,0))^2`. For negative correlations the help implies a positive contribution, while the code gives zero. This discrepancy affects user expectations and tuning.

---

### **HIGH**

4. **src/diaspextract.cpp:3195-3196**
   gate:shrinkage fisher uses `s2 = 1.0 / std::max(overlap - 3, 1)`. With the 1.5.0 default `shrink_min_points_ = 1`, `overlap` can be 1, so `overlap-3 = -2` and `s2 = 1.0`. A Pearson correlation computed from a single overlapping point over a zero-padded grid is not statistically meaningful, yet it is fed into the Fisher-z posterior. The clamping to ±0.999 before `atanh` avoids infinities, but the model is degenerate here. This does not crash but may produce questionable shrinkage for very short overlaps.

5. **src/diaspextract.cpp:existing (not in diff)**
   The fragment vector for capping is sorted by the ranking key and truncated to `max_frags`. The code uses a sort that is not stable (likely `std::partial_sort` in the pre-existing assembly path). When multiple fragments have the identical ranking key (e.g., same `max(r,0)*ln(1+I)*(1+overlap)` in evidence mode), the order among them is not deterministic, so which fragments survive the cap can vary by thread count or tile grid. This **violates the shipped determinism guarantee** for the 1.5.0 defaults.

---
---

### **MEDIUM**

6. **src/diaspextract.cpp:2374**
   gate:shrink_prior_r help text: "0 = shrink toward no co-elution" is accurate but potentially confusing. With `shrink_prior_r = 0.6` (1.5.0 default), the prior mean in Fisher-z is `atanh(0.6) ≈ 0.693`, not zero. A user might expect `shrink_prior_r=0` to disable shrinkage toward co-elution, but the text implies it shrinks toward *no* co-elution, which is correct. This is cosmetic but could mislead.

7. **src/diaspextract.cpp:3173-3180 (concentric path)**
   The concentric score is `c = min_corr * (1 - 0.5*d/(tol+1))` with `tol = max(1, short_center_tol_ * p_half)`. Since concentric fragments are accepted solely by the span test (they bypass the `c < min_corr` gate), the score can be below `min_corr`; this is fine for ranking. However, the maximum score is `min_corr` (when `d=0`), so concentric fragments will never rank above non-concentric fragments that achieve the full correlation. This is by design and correct, but note that if `min_corr` is tuned, the concentric score scale moves with it.

---
---

### **LOW / FINE**

8. **src/DnoiseMs1.h:356-360**
   `correctionRefusal` now accepts `corr < 1` (above 100 ms AccumulationTime) and relies on `recoverPoint` to pick the nearest raw count. The updated comment and refusal string accurately reflect this change. The new `recoverPoint` logic (selecting the `r` that minimizes `|r - v/corr|`) is correct for the approximation. **Fine.**

9. **src/diaspextract.cpp:2363,2372,2378,2383**
   The 1.5.0 defaults in Section B are consistent with the help texts: `shrink_prior_r=0.6` ("0 = shrink toward no co-elution" still holds), `shrink_prior_sd=0.3` ("smaller = stronger shrinkage" holds), `shrink_min_points=1` ("fewest overlapping frames" holds). **Fine.**

10. **src/diaspextract.cpp:4147-4156 (adaptive auto)**
    The auto rule computes the faint fraction from a sequential loop over `precursors`. This is deterministic and correctly sets `adaptive_` before parallel assembly. The fraction is logged and stamped. **Fine.**

11. **src/diaspextract.cpp:3076-3077 (pspan histogram)**
    `pspanHist_()` uses atomics and is incremented inside the parallel precursor loop. The histogram counts are deterministic and only used for logging. **Fine.**

12. **src/diaspextract.cpp:132-158 (GateDump)**
    Diagnostics are read-only, mutex-protected, and only active when both environment variables are set. They do not affect spectra or the digest. **Fine.**

13. **src/diaspextract.cpp:3128-3129 (colocation overlap with zero-length spans)**
    `shorter = min(f_hi - f_lo, p_hi - p_lo) + 1` ensures `shorter >= 1`. `inter` is computed safely. Edge cases (single-point spans, no overlap) are handled correctly. **Fine.**

14. **src/diaspextract.cpp:3183-3184 (ln(1+I) with I=0)**
    `std::log1p(0) = 0`. For zero-intensity fragments the evidence/umpire keys are zero, which is acceptable. **Fine.**

---
---

## Summary

| # | Severity | Issue | Location |
|---|----------|-------|----------|
|1|SEVERE|gate:adaptive help omits "auto"|src/diaspextract.cpp:2363|
|2|SEVERE|No tests for new gate modes|tests/ (missing)|
|3|SEVERE|umpire help says r^2 but impl uses (max(r,0))^2|src/diaspextract.cpp:2361|
|4|HIGH|Fisher-z variance with overlap≤3 is degenerate|src/diaspextract.cpp:3195-3196|
|5|HIGH|Non-stable sort for cap ranking breaks determinism|src/diaspextract.cpp:existing|

All other reviewed aspects (math for concentric/colocation, NaN propagation, IM/RT gate interactions, adaptive precedence, performance in hot loop, defaults consistency) are correct or cosmetic.
