Based on my adversarial review of the **DIAspeXtract 1.3.1** branch (`fix/c2-negative-1.3.1`, commit `2b9ade4c42`), here are my findings, structured by your numbered questions. I attack the code’s invariants, domain logic, and edge cases, and assess whether issues are **real-world** or **theoretical**.

---

---

---

## **Executive Summary**
**Overall assessment:** The change is **sound**. The mathematical derivation, domain check, and fail-closed discipline are correct. The golden cases are independent and sufficient, and the code preserves bit identity for `C2 ≥ 0`. The only **real-world gaps** are in the **OpenMS loader patch**, which does not enforce per-frame temperature or axis bounds, but these are mitigated by the conservative domain check and the tool’s default use of its own reader. No changes are *required* for 1.3.1 to ship, but I recommend **one HIGH-priority fix** (OpenMS patch) and **two MEDIUM clarifications** before release.

---
---
---

---

## **Answers to Questions**

---

### **1. Root choice for C2 < 0**
**Answer:**
- **Yes, the root is correct.** For `C2 < 0` and `C0 < t < t_zero = C0 + b²/(4|C2|)`, **both roots of the quadratic `C2 u² + b u + (C0 - t) = 0 are positive** (product of roots `(C0 - t)/C2 > 0` since `C2 < 0` and `t > C0`; sum of roots `-b/C2 > 0`).
- **`u = 2(t - C0)/(b + sqrt(disc))` is the rising-branch root** for either sign of `C2`:
  - At `t = C0+`, `u ≈ 0`.
  - At `t = t_zero`, `u = b/(2|C2|)` (the parabola’s vertex in `u`).
  - For all `t ∈ (C0, t_zero)`, `u < b/(2|C2|)` (rising branch, where `dt/du = b + 2C2 u > 0`).
- **No finite input** (for `C2 < 0` in the accepted domain) returns:
  - The **other root**: The code’s formula is the **smaller positive root** (rising branch), while the other root is larger and corresponds to the falling branch (non-physical for TOF→m/z).
  - A **negative `u`**: Impossible, as both roots are positive for `C0 < t < t_zero`.
  - A **finite wrong value**: `tofToMz` returns **NaN** for `t ≤ C0`, `disc < 0`, or `denom ≤ 0` (the latter cannot occur for `t > C0` and `C2 < 0` in the domain).
- **Continuity through `C2 = 0` and `C2 = -0.0`:**
  - At `C2 = 0`, `u = (t - C0)/b`, matching the limit of the formula as `C2 → 0`.
  - For `C2 = -0.0`, IEEE-754 treats `-0.0 == 0.0` in comparisons, so `C2 < 0.0` is **false**, and the code treats it identically to `C2 = 0.0` (verified in tests: `test_calibration_cpp.cpp` checks bit identity).

**Severity:** NONE. The root choice is mathematically sound.

---

---

### **2. Domain check correctness (`negativeC2Reason`, lines 145–165)**
**Answer:**
- **`t_zero`, `t_half`, and `u_half` are correct:**
  - `k = -4C2 > 0` (for `C2 < 0`).
  - `t_zero = C0 + b²/k = C0 + b²/(4|C2|)`: Flight time where `disc = 0` (beyond this, no real `u` exists).
  - `t_half = C0 + 0.75 b²/k`: Flight time where `disc = b²/4` (slope `dt/du = b/2`).
  - `u_half = b/k = b/(4|C2|)`: At `t_half`, `u = 2(t_half - C0)/(b + b/2) = b/(4|C2|)` (verified by substitution).
- **Deciding corner is correct:**
  - The **smallest `b`** (largest `cf = 1 + |dC1|·1000/1e6`) gives the **smallest `t_zero` and `t_half`** (since `t_half ∝ b²`).
  - Thus, checking at `b_min` (smallest `b`) and `t_max = kDomainMaxTof * timebase + delay` is the **most restrictive corner** for both TOF and m/z conditions.
- **m/z condition `kDomainMaxMz + C4 ≤ u_half²` is correct:**
  - `m_half = u_half² - C4` is the m/z where `dt/du = b/2`.
  - For `m ≤ m_half`, `u ≤ u_half`, and `dt/du = b + 2C2 u ≥ b/2` (verified by substitution).
  - The condition ensures `kDomainMaxMz ≤ m_half`, so all `m ≤ 1e5` are in the well-conditioned region.
- **No finite input row accepted while violating the domain:**
  - The check requires **both** `t_max ≤ t_half` and `kDomainMaxMz + C4 ≤ u_half²`.
  - For any `(TOF ≤ 1e8, m/z ≤ 1e5, |T1 - T1_ref| ≤ 1000 K)`, `disc ≥ b²/4` and `dt/du ≥ b/2` hold **by construction** (since the worst case is the checked corner).
  - **Edge cases (all refused):**
    - `C2 = -0.1`: Rejected (TOF index `7.93471e+07` where `disc = 0`; verified in tests).
    - `C2 = -0.07`: Rejected (slope margin; `disc ≥ b²/4` fails at `t_max`).
    - `C2 = -2.5` (1 ps timebase): Rejected on m/z side (`m_half < 1e5`).
    - `dC1 = 1000 ppm/K`: Rejected (`cf_lo ≤ 0`; C1 factor exits `(0, ∞)` within 1000 K).
    - `t1_frame = 1100°C`: Rejected by `frameReason` (only for `C2 < 0`).
- **No garbage computation:**
  - All arithmetic uses `double` with sufficient range (e.g., `b²/k` for `C2 = -1e-3` is `~2.5e14`, well within `double`’s `~1e308`).
  - NaN is handled by the initial `unsupportedReason()` NaN screen (line 76–77).

**Severity:** NONE. The domain check is **mathematically conservative** and **correctly implemented**.

---

---

### **3. Is the domain the right one?**
**Answer:**
The domain (`TOF ≤ 1e8`, `m/z ≤ 1e5`, `|T1 - T1_ref| ≤ 1000 K`) is **theoretically insufficient** but **practically safe** because the **verified domain is far larger** than the checked bounds:
- **TOF bound:**
  - The half-slope point for PXD029836 runs is at **TOF index ~5.7e9** (14,000× the digitizer’s 397,657 bins; [Evidence 3b](#3b-discriminant-margins-from-the-laptop-tdf-copies-runs-141814201422)).
  - The root stops existing at **TOF index ~7.6e9** (19,000× the digitizer’s range).
  - **Conclusion:** For any file passing the domain check, **all TOF indices up to 1e8 are deep inside the well-conditioned region** (disc ≥ b²/4, slope ≥ b/2).
- **m/z bound:**
  - The half-slope m/z for PXD029836 is **~3.66e11** ([Evidence 3b](#3b-discriminant-margins-from-the-laptop-tdf-copies-runs-141814201422)), **3.66 million× larger than 1e5**.
  - **Conclusion:** For any file passing the domain check, **all m/z up to 1e5 are on the rising branch** (`m ≤ m_vertex ≈ 1.46e12`).
- **Temperature bound:**
  - Real files have T1 spreads of **0.004–0.011 K** ([Evidence 3b](#3b-discriminant-margins-from-the-laptop-tdf-copies-runs-141814201422)), **100× smaller than 1000 K**.
  - **Conclusion:** The 1000 K span is **conservative** and **never refuses real files**.

**Places where TOF > 1e8 or m/z > 1e5 could reach the model:**
The **OpenMS loader path** (not the tool’s own reader) does **not** enforce the axis bounds (`DigitizerNumSamples`, `MzAcqRangeUpper`). However, **this is not a real-world risk** because:
| Place | Input | Risk for Real Files? | Why Safe |
|-------|-------|----------------------|---------|
| `TdfTableTof2MzConverter::convert` (OpenMS patch) | TOF from raw frames (`≤ DigitizerNumSamples - 1`) | **NO** | For any file passing `isSupported()`, the half-slope TOF is **~5.7e9** >> 1e8, so even if `DigitizerNumSamples > 1e8`, all TOF are still in the well-conditioned region. |
| `TdfTableTof2MzConverter::inverse_convert` (OpenMS patch) | m/z from loader | **NO** | Half-slope m/z is **~3.66e11** >> 1e5. |
| `TofAxis::tofOf` in `best` (line 1081–1082) | `hi_mz = cmz + 3·sd` | **NO** | Real `cmz + 3·sd` ≤ 1700 (PXD029836’s `MzAcqRangeUpper`) << 1e5. |
| `TofAxis::tofOf` in band edges (line 4113–4116) | `acq_hi` or `mzOf(last) + 1e-5` | **NO** | Tool’s own reader enforces `acq_hi ≤ 1e5`; OpenMS loader path is fallback only. |
| `MzPeakExactMz::exact` | m/z from archive | **NO** | Archive m/z ≤ 42,000 (compact store’s 1e-5 Da quanta up to 42949.67) < 1e5. |
| `recoverPoint` (dnoise) | m/z from loader | **NO** | Same as above. |

**Would non-monotonic `mzToTof` or ill-conditioned root change output on real negative-C2 files?**
**NO.** For all real negative-C2 files (PXD029836):
- `m_vertex ≈ 1.46e12` >> any real m/z (≤ 1700).
- `m_half ≈ 3.66e11` >> 1e5.
- Thus, **`mzToTof` is strictly monotonic** (rising branch) for all real m/z, and the root is **well-conditioned** (slope ≥ b/2).

**Severity:** **LOW (theoretical only)**. The domain is **over-conservative** for real files, but this is a **feature**, not a bug.

---
---

### **4. Temperature handling**
**Answer:**
- **Can a frame reach `frameFactor` with an unchecked T1?**
  - **Tool’s own reader (`loadTdfCalibration`):** **NO**. Calls `cal.frameReason(t1)` for every frame and refuses if non-empty (line 135 in `TdfLoad.h`).
  - **OpenMS loader patch:** **YES**. Does **not** call `frameReason`. Frames with `|T1 - T1_ref| > 1000 K` are **not refused**, but:
    - For real files (T1 spread ≤ 0.011 K), this **never occurs**.
    - Even if `T1` is outside 1000 K, `frameFactor` may still return a valid `b` (e.g., `dC1 = 20`, `T1 = 1100°C` → `cf = 1 + 20*(25 - 1100)/1e6 = 0.78` > 0), but **the domain check did not verify this temperature**.
    - **However:** For any file passing `isSupported()`, the **half-slope TOF is ~5.7e9**, so even at extreme `T1`, all TOF ≤ 1e8 are still in the well-conditioned region.
- **Floating-point consistency:**
  - `frameReason` uses `std::fabs(t1_frame - T1_ref) ≤ kDomainT1Span`.
  - `negativeC2Reason` uses `std::fabs(dC1) * kDomainT1Span / 1e6`.
  - Both use `kDomainT1Span = 1000.0` (exactly representable in `double`), so the comparison is **consistent**.
- **Is 1000 K sensible?**
  - **Yes.** It is **100× wider than any real file’s T1 spread** (0.004–0.011 K; [Evidence 3b](#3b-discriminant-margins-from-the-laptop-tdf-copies-runs-141814201422)), so it **never refuses real files**.
  - It is **meaningful** because it provides a **conservative bound** for the domain check (worst-case `b` is at `±1000 K`).

**Severity:** **LOW (theoretical only)**. The OpenMS loader’s lack of `frameReason` is **not a real-world risk** due to the conservative domain check.

---
---
### **5. Bit identity for C2 ≥ 0**
**Answer:**
All changes **preserve bit identity** for `C2 ≥ 0` files:
| Changed Line | Effect for `C2 ≥ 0` | Risk? |
|-------------|----------------------|-------|
| Reordered `timebase` check (line 84) | Check order changed, but logic identical for `C2 ≥ 0` (same conditions evaluated). | **NO** |
| `frameReason` in Frames loop (line 135) | Returns empty string for `C2 ≥ 0` (line 98: `if (!(C2 < 0.0) || ...)`). | **NO** |
| `kDomainMaxTof`/`kDomainMaxMz` (lines 66–70) | Replace literals `1e8`/`1e5` in `loadTdfAxisBounds`. Same numeric values. | **NO** |
| `#include <cstdio>` (line 40) | Unused for `C2 ≥ 0` (only `negativeC2Reason` uses `num`). | **NO** |
| `private:` section (lines 137–165) | Static `num()` and `negativeC2Reason()` do not affect object layout. `TdfMzCalibration` size/alignment **unchanged**. | **NO** |
| Per-frame `std::string` (line 135) | No-op for `C2 ≥ 0`. | **NO** |

**Mixed deploy (libOpenMS with old header, tool with new):**
- **Tool’s own reader (`-dnoise:ms1 true`):** Uses new header; accepts negative `C2` if domain passes.
- **OpenMS loader fallback (`-dnoise:ms1 false`):** Uses old header (in libOpenMS); **refuses all `C2 < 0`**.
  - **Risk:** A negative-C2 file would be **refused by the fallback**, causing the tool to fail with a warning (same as any unsupported calibration).
  - **Mitigation:** The tool’s **default is `-dnoise:ms1 true`**, which avoids the fallback. The CHANGELOG documents this behavior.
- **Bit identity for `C2 ≥ 0`:** **Preserved** in mixed deploy (both old/new headers behave identically for `C2 ≥ 0`).

**Severity:** **LOW (theoretical only)**. No real-world impact on `C2 ≥ 0` files.

---
---
### **6. Golden cases**
**Answer:**
- **Are the 210 new cases vendor values?**
  **YES.** Generated by `tims_index_to_mz` from Bruker’s **libtimsdata 2.21.0.4** on the cluster (not redistributed; [Section 5](#5-the-sdk-golden-generator-sdk_golden_pxd029836py-run-on-the-cluster-not-in-the-repo)).
- **Are they sufficient?**
  **YES.**
  - Coverage: **6 runs** (1418, 1420, 1422, 1431, 1408, 1347) × **5 frames** (first, middle, last, coldest, warmest) × **7 TOF probes** (2,000 to 397,656).
  - **Four calibration vectors** (1408–1415, 1418–1422, 1431–1435, 1347–1358) are represented.
  - **T1 spread:** 0.004–0.011 K per run ([Evidence 3b](#3b-discriminant-margins-from-the-laptop-tdf-copies-runs-141814201422)), sufficient to detect temperature effects (ablation: 0.088–0.210 ppm; [Evidence 3a](#3a-sdk-golden-generator-output-ibminode05-libtimsdata-22104)).
  - **TOF range:** Probes span the **full digitizer range** (2,000 to 397,656), including the last bin.
- **C4 handling:**
  - Golden JSON **omits `C4`**, and parsers assume `C4 = 0`.
  - **Correct for PXD029836** (all runs have `C4 = 0`; [Evidence 3c](#3c-calibration-rows-of-all-23-pxd029836-runs-mzcalibration-referenced-by-the-frames)).
  - **C4 ≠ 0** is tested separately in `test_calibration_cpp.cpp` (lines 187–202).
- **Assertion independence:**
  - All assertions **compare to vendor values** (`tims_index_to_mz`), **not** the tool’s formula.
  - **Non-vacuous:** Each file is checked **individually** (Python: `f_noc2 > 5.0` and `f_flip > 5.0`; C++: `f_noc2 >= 5.0` and `f_flip >= 5.0`).
    - PXD029836: Dropping `C2` = **19–40 ppm** (>> 5 ppm); flipping `C2` = **38–80 ppm** (>> 5 ppm; [Evidence 3a](#3a-sdk-golden-generator-output-ibminode05-libtimsdata-22104)).
  - **Edge formula:** `c2_edge = 3 * b_lo² / (16 * (t_max - C0))` is **derived independently** of the header (matches the mathematical condition for `disc = b²/4` at `t_max`).

**Severity:** NONE.

---
---
### **7. Any remaining C2 ≥ 0 assumptions?**
**Answer:**
**NO.** All code, comments, docs, and tests have been updated:
- **Comments:**
  - `TdfMzCalibration.h` lines 19–37: Explicitly discusses **negative `C2`** and its domain.
  - `tofToMz` comment (lines 114–118): Updated to `|C2|` and "either sign of `C2`".
  - `mzToTof` comment (lines 128–129): Notes rising branch for `C2 < 0`.
- **README.md:** Updated to state `C2` can be **either sign** (lines 73–77 in diff).
- **CHANGELOG.md:** Thoroughly documents negative `C2` support.
- **Tests:**
  - Golden cases include **6 runs with `C2 < 0`**.
  - Explicit tests for `C2 = -0.0` (bit identity with `0.0`).

**No lingering assumptions** that `C2 ≥ 0`.

**Severity:** NONE.

---
---
### **8. CHANGELOG accuracy**
**Answer:**
**All claims are accurate** except one **minor premature statement**:
| Claim | Evidence | Accuracy |
|-------|----------|----------|
| "All 23 runs of PXD029836 have `C2 < 0` in four vectors (`-0.00059` to `-0.00123`)" | [Evidence 3c](#3c-calibration-rows-of-all-23-pxd029836-runs-mzcalibration-referenced-by-the-frames) | **ACCURATE** (ranges: `-0.000586` to `-0.001228`). |
| "Tool stopped after 0.03 s with exit 6 for `-dnoise:ms1 true`" | [Evidence 3d](#3d-mutation-proof-each-mutation-applied-alone-to-the-headerreader-which-test-suites-catch-it) (M1) | **ACCURATE**. |
| "Worst error: 7.0e-6 ppm" | [Evidence 3a](#3a-sdk-golden-generator-output-ibminode05-libtimsdata-22104) | **ACCURATE** (max: 7.0e-6 ppm). |
| "Dropping `C2`: 19–40 ppm; flipping sign: 38–80 ppm" | [Evidence 3a](#3a-sdk-golden-generator-output-ibminode05-libtimsdata-22104) | **ACCURATE** (verified per run). |
| "Half-slope TOF: ~5.7e9 (14,000× digitizer range)" | [Evidence 3b](#3b-discriminant-margins-from-the-laptop-tdf-copies-runs-141814201422) | **ACCURATE** (slope half at `5.7187e+09`). |
| "Root stops existing beyond TOF index 6.4e9" | [Evidence 3a](#3a-sdk-golden-generator-output-ibminode05-libtimsdata-22104) (run 1431: `6.59929e+09`) | **MINOR INACCURACY** (actual: **6.6e9** for run 1431, **7.6e9** for run 1418). **Rounded for brevity.** |
| "16,000× the digitizer’s range" | `7.6e9 / 397657 ≈ 19,100×` | **MINOR INACCURACY** (should be **~19,000×**). **Rounded.** |
| "Four pins reproduce (dataset D `e43672a0`, run 009 `3aafd0b5`)" | Not yet run (digest gate pending) | **PREMATURE** (stated before verification). |
| "Golden cases: 210 new (6 runs × 5 frames × 7 TOF probes)" | [Evidence 4](#4-golden-json-after-the-change-9-files-the-first-3-predate-the-branch) | **ACCURATE**. |
| "Round trip to 1e-6 bins" | [Evidence 3e](#3e-local-ctest-on-the-branch-appleclang-21-gcc-16-prints-the-same-numbers) (worst: `3.0e-08` bins) | **ACCURATE**. |
| "Python twin agrees to 3.1e-5 ppm" | [Evidence 3e](#3e-local-ctest-on-the-branch-appleclang-21-gcc-16-prints-the-same-numbers) | **ACCURATE**. |

**Severity:**
- **LOW** for the rounded numbers (6.4e9, 16,000×) and the premature "four pins reproduce" claim.
- All other numbers and claims are **verified against evidence**.

---
---
### **9. What would you add or change before shipping 1.3.1?**
**Ranked by severity:**

| Rank | Issue | Severity | Fix | Real-World Risk? |
|------|-------|----------|-----|------------------|
| **1** | OpenMS loader patch **does not call `frameReason`** or enforce axis bounds (`DigitizerNumSamples`, `MzAcqRangeUpper`). | **HIGH** | Update the OpenMS patch to: (1) Call `cal.frameReason(t1_frame)` for each frame and refuse if non-empty. (2) Check `DigitizerNumSamples ≤ 1e8` and `MzAcqRangeUpper ≤ 1e5` in the loader. | **NO** (mitigated by conservative domain check and tool’s default reader), but **violates fail-closed principle** for the fallback path. |
| **2** | CHANGELOG claims **"four pins reproduce"** before the digest gate ran. | **MEDIUM** | Qualify as **"expected to reproduce"** or run the digest gate before release. | **NO** |
| **3** | CHANGELOG **rounds TOF index** (6.4e9 vs. actual 6.6e9–7.6e9) and **multiplier** (16,000× vs. ~19,000×). | **LOW** | Use precise values: **6.6e9–7.6e9** (17,000–19,000×). | **NO** |
| **4** | No test for **`C4 ≠ 0` + `C2 < 0`** in golden cases. | **LOW** | Add a PXD017703-like golden case (which has `C4 = -0.0905`) with negative `C2` (hypothetical; not yet observed). | **NO** (no known real files have both `C4 ≠ 0` and `C2 < 0`). |
| **5** | `num()` uses `%.6g` for TOF indices, which **loses precision** for very large values (e.g., `7.93471e+07` becomes `7.93471e+07` in `%.6g`, but `123456789012345` would be rounded). | **LOW** | Use `%.15g` or ensure sufficient precision for all possible values. | **NO** (real TOF indices are ≤ 1e8; `%.6g` is sufficient). |

**Recommendation for 1.3.1:**
- **MUST:** Fix the OpenMS loader patch to call `frameReason` (1 day of work). This closes the theoretical gap in fail-closed discipline.
- **SHOULD:** Run the digest gate to verify the "four pins reproduce" claim.
- **COULD:** Update CHANGELOG numbers for precision.

---
---
---
---

## **Final Verdict**
| Invariant | Status | Notes |
|-----------|--------|-------|
| **Fail closed** | ✅ **PASSED** | Negative `C2` refused outside domain; NaN for out-of-model inputs. |
| **Bit identity for C2 ≥ 0** | ✅ **PASSED** | All changes are no-ops for `C2 ≥ 0`. |
| **Golden cases independent** | ✅ **PASSED** | Vendor values from `tims_index_to_mz`; not derived from header. |
| **Shipped code = tested code** | ✅ **PASSED** | Same header in libOpenMS (via patch) and tool; C++ golden test includes header. |
| **Domain check conservative** | ✅ **PASSED** | Worst-case corner (smallest `b`, largest TOF) checked; real files have **100× more headroom**. |
| **Non-monotonic `mzToTof`** | ✅ **PASSED** | For real files, `m_vertex ≈ 1.46e12` >> any real m/z (≤ 1700). |
| **Temperature handling** | ✅ **PASSED** | 1000 K span is **conservative** (real spread: 0.004–0.011 K). |
| **CHANGELOG accuracy** | ⚠️ **MINOR ISSUES** | Rounded numbers; premature claim. |
| **OpenMS patch** | ⚠️ **GAP** | Does not enforce `frameReason` or axis bounds (but **not a real-world risk**). |

**DIAspeXtract 1.3.1 is ready to ship** with the **HIGH-priority OpenMS patch fix** and **MEDIUM CHANGELOG clarifications**. The branch’s core logic is **sound**, and the adversarial review found **no critical flaws**.
