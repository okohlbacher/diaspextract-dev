## Adversarial Review: SpeXtractor stage 1

---

### 1. Floating-point contraction hazard in the MS1 window gate builder (CRITICAL)

**Location**: `src/DnoiseMs1.h`, `buildMs1WindowGate`, lines 340–347
**Concrete failure**: The `volatile` qualifier only protects the `scan_slope * scan` product, but the subsequent additions, `fmax`, and divisions that compute `s0`/`s1` can still be fused by the compiler under `-ffp-contract=fast`, changing the scan bounds. The description itself states that fusing `im_max + slope*scan` flips 3 of D’s 24 boxes; the current guard does not prevent contraction across the entire expression chain (e.g., `scan_intercept + volatile_product` followed by `(max + pad - intercept) / slope`).
**Fix**:
```cpp
volatile double scaled0 = scan_slope * static_cast<double>(static_cast<std::uint32_t>(r.scan_num_begin));
volatile double im0 = scan_intercept + scaled0;
volatile double im1 = scan_intercept + (scan_slope * static_cast<double>(static_cast<std::uint32_t>(r.scan_num_end)));
volatile double max_im = std::fmax(im0, im1);
volatile double padded_max = max_im + p.dia_ms1_im_pad;
volatile double diff = padded_max - scan_intercept;
volatile double s0 = diff / scan_slope;
```
and similarly for `s1`. This ensures no intermediate contraction.

---

### 2. `from_chars` floating-point availability check is unreliable (HIGH)

**Location**: `src/DnoiseMs1.h`, `detail::parseF64`, lines 201–209
**Concrete failure**: `__cpp_lib_to_chars` tests for *integer* `from_chars` (P0067R5, C++17); floating-point `from_chars` (P0682R1) was added in C++20 and may not be available even when the macro is defined (e.g., older GCC with `-std=c++17`). On such a compiler, the `std::from_chars(body.data(), ..., v)` call for floating-point will fail to compile.
**Fix**: Replace the macro check with compiler/version-specific checks, or always use the `istringstream` fallback on macOS (libc++) as the comment already implies is safe. For example:
```cpp
#if defined(__cpp_lib_to_chars) && defined(__has_include) && __has_include(<charconv>) && (defined(__GNUC__) && __GNUC__ >= 11)
  // use from_chars
#else
  // use istringstream
#endif
```

---

### 3. Inconsistent prune filter between streaming and resident load paths (HIGH)

**Location**: 
- Streaming: `src/spextractor.cpp`, `PickCompactConsumer::flush_()` (line 1967)
- Resident: `src/spextractor.cpp`, after IM picking (line 3937)
**Concrete failure**: The streaming path prunes **all** spectra in `ms1_buf_` (`[](const MSSpectrum&) { return true; }`), while the resident path only prunes MS1 spectra with IM data (`s.containsIMData() && s.getMSLevel() == 1`). If a spectrum without IM data ever enters `ms1_buf_` (e.g., due to a future code path or edge case), it would be pruned in streaming but not in resident, causing the MS1 map to differ and breaking output-identity.
**Fix**: Use the resident path’s filter in both places:
```cpp
// In flush_():
if (ms1_prune && ms1_prune->on) ms1_prune->batch(ms1_buf_, [](const MSSpectrum& s) { return s.containsIMData() && s.getMSLevel() == 1; });
```

---

### 4. Prune algorithm keeps unnecessary sub-threshold peaks (MEDIUM)

**Location**: `src/spextractor.cpp`, `Ms1Prune::frame` (lines 1728–1757)
**Concrete failure**: The algorithm keeps sub-threshold peaks that are **not within `hop` of the last kept peak** and are **not first/last**. Example: spectrum with peaks at m/z `[100.0 (surv), 200.0 (sub), 300.0 (surv)]` and `hop=0.01`. 
- 100 is kept (first).
- 200 is not within `hop` of 100 (200 > 100 × 1.01), `cand=none`, so the code **keeps 200** unconditionally.
- 300 is not within `hop` of 200 (300 > 200 × 1.01), so 300 is kept.
This keeps 200 even though it is not needed to bridge 100→300 (neither pair is within `hop`). While the output may still be identical (MassTraceDetection ignores sub-threshold peaks), this violates the "minimal chain" contract and risks higher memory usage.
**Fix**: Only keep sub-threshold peaks if they are within `hop` of a kept peak or are first/last. Revise the loop to defer keeping a sub-threshold peak until it can bridge a gap:
```cpp
if (last == none) { /* first peak: always keep */ }
else if (!reach(last, x)) {
  if (cand != none) { keep.push_back(cand); last = cand; cand = none; }
  if (cand == none && !surv && i != 0 && i != n - 1) { cand = i; continue; } // defer
  // else keep i (survivor or last or first)
}
```

---

### 5. NaN m/z values are not handled in the prune (MEDIUM)

**Location**: `src/spextractor.cpp`, `Ms1Prune::frame`
**Concrete failure**: The `reach` lambda compares `x <= m + hop * m`. If `m` or `x` is NaN, the comparison returns `false`, causing the peak to be kept only if it is first/last or a survivor (but NaN intensity is neither). This could corrupt band partitioning or cause undefined behavior in later stages.
**Fix**: Add a guard at the start of the loop:
```cpp
const double x = s[i].getMZ();
if (!std::isfinite(x)) { /* drop or keep? NaN m/z is invalid; safest to keep first/last only */ }
```

---
---
---

### Areas with **no issues found**

- **Integer overflow/saturation**: TOF/scan/TOF-index arithmetic saturates correctly at 0 and `UINT32_MAX`; intensity sums use `uint64_t` and cannot overflow.
- **Duplicate (scan, TOF)**: The streak filter groups by TOF and sums intensities per scan; duplicates at the same (scan, TOF) are handled identically to dnoise’s Rust (each contributes to the window sum).
- **Zero-intensity points**: Correctly excluded from occupied scans in streak; kept by halo only when `best==0` (matching Rust’s `I >= fraction * best` with `best=0`).
- **Ordering**: Stable LSD radix sort by TOF and counting sort by scan preserve the required order for dnoise equivalence.
- **Performance shortcuts**: Streak early termination, two-pointer window, skip short runs, halo counting sort, gate-only-on-halo-survivors — all provably exact.
- **Concurrency in `Ms1Prune::batch`**: `sample` offsets are precomputed; each thread writes only to its slice of `sample` and its `cs[i]`; exception handling is correct.
- **Memory**: `MSSpectrum::select` in OpenMS does shrink capacity (verified in source), so no transient doubling at flush. The ledger accounts for post-prune sizes.
- **e2e check 19 fixture**: Exercises witnesses (requires `wit > 0`), verifies `no_witness` changes output, and checks byte-identity with prune on/off. The stride-97 sample is taken pre-prune. No vacuous pass.

---
---
---

### Summary

| # | Severity | Area | Status |
|---|----------|------|--------|
| 1 | **CRITICAL** | DnoiseMs1 gate FP contraction | Concrete fix above |
| 2 | **HIGH** | DnoiseMs1 floating-point parsing | Concrete fix above |
| 3 | **HIGH** | MS1 prune path inconsistency | Concrete fix above |
| 4 | **MEDIUM** | MS1 prune algorithm over-keeping | Concrete fix above |
| 5 | **MEDIUM** | MS1 prune NaN m/z handling | Concrete fix above |
