## Adversarial Review: SpeXtractor Stage 2 (dnoise MS1) and Fix Pass

### 1. TOF bin range check uses hardcoded limit instead of digitizer bounds
**Location**: `spextractor.cpp:DnoiseRun::frame()` (TOF recovery check)
**Failure**: The check `bin <= 4294967295.0` allows TOF bins up to 2³²−1, but the digitizer typically has only 2²⁰–2²⁴ bins (`ax.n_bins`). Out-of-bounds bins would be passed to `denoiseMs1Frame`, which uses TOF indices directly—risking buffer overruns in the ported Rust logic (e.g., `streak.rs` bin indexing).
**Fix**: Replace with `bin >= 0.0 && bin < ax.n_bins`.

---

### 2. Locale-dependent parsing of AccumulationTime
**Location**: `src/TdfLoad.h:loadTdfDnoise()` (`std::atof` on SQLite text)
**Failure**: `std::atof` respects the global C++ locale. In a locale using comma as decimal separator (e.g., `LC_NUMERIC=de_DE`), SQLite’s `"0.1"` becomes `0`, producing `corr = ∞` (silently refused later) or wrong `corr` leading to intensity recovery failures (hits ≠ 1).
**Fix**: Use `spx::dnoise::detail::parseF64` (already locale-independent via `std::locale::classic()`) or replicate its stream-based parser.

---

### 3. Compile-time FP checks miss critical dangerous flags
**Location**: `src/DnoiseMs1.h` (preprocessor guard)
**Failure**: The `#error` catches `-ffast-math`, `-ffinite-math-only`, `/fp:fast`, x87 excess precision, but **not** `-funsafe-math-optimizations`, `-freciprocal-math` (GCC), or clang’s `-ffp-model=fast`. These flags also fuse operations that flip D’s gate boxes (measured: 3 boxes change with contraction alone; further optimizations move more).
**Fix**: Document prominently in `CMakeLists.txt` and `README`, or add a runtime self-test in `buildMs1WindowGate` that verifies a known box’s bounds and aborts if they differ from pinned values.

---
---
### 4. TOF axis validity not checked during DnoiseRun::setup
**Location**: `spextractor.cpp:DnoiseRun::setup()`
**Failure**: `setup()` reads the tdf and builds the gate, but does **not** verify that the TOF axis is usable (`tofAxis().ok`) or matches `"tdf_table_modeltype1"` before proceeding. The check is deferred to `checkLoader()`, which runs later (after the tdf is fully parsed). If the axis is broken, milliseconds are wasted parsing the entire tdf before refusing.
**Fix**: After `tofAxis()` is loaded in `setup()`, call `checkLoader()` or duplicate its model check and refuse early.

---
---
### 5. Redundant and arbitrary intensity recovery search bounds
**Location**: `spextractor.cpp:DnoiseRun::frame()` (raw intensity recovery loop)
**Failure**: The loop bounds `(v ± 0.5)/corr ± 1.0` are arbitrary. The equation `round(r * corr) == v` only requires `r ∈ [(v−0.5)/corr, (v+0.5)/corr)`. The `±1.0` widens the search unnecessarily; for extreme `corr` (e.g., 0.1), the loop iterates 20× more than necessary. While safe, it wastes CPU in the hot path.
**Fix**: Tighten bounds to `std::floor((v−0.5)/corr)` to `std::ceil((v+0.5)/corr)`.

---
---
### 6. Non-finite m/z handling in Ms1Prune is incomplete
**Location**: `spextractor.cpp:Ms1Prune::frame()`
**Failure**: Spectra with non-finite m/z are kept whole (`if (!finite) return`), but the preceding `s.sortByPosition()` has undefined behavior when NaN m/z are present—`std::sort` with `operator<` treats NaNs as unordered, leading to implementation-defined sorting. The prune’s logic (stride-97 sampling, chain traversal) assumes sorted order.
**Fix**: Reject spectra containing NaN m/z entirely (fail-closed) or explicitly handle them in sorting (e.g., move NaNs to the end).

---
---
### 7. Exception containment gap in detectTraces_ parallel region
**Location**: `spextractor.cpp` (MS1 tracing parallel call)
**Failure**: `detectTraces_` has its own `#pragma omp parallel for` with exception capture, but its **outer** `try-catch` in the caller (`#pragma omp single` region) only catches exceptions thrown *outside* `detectTraces_`’s parallel loops. If `detectTraces_` throws from its serial preamble (e.g., band edge allocation), the exception escapes the `#pragma omp single` block and **terminates the process** (OpenMP default for uncaught exceptions in parallel regions), bypassing the rethrow and clean shutdown.
**Fix**: Extend the `try` block in the caller to cover the entire `detectTraces_` invocation, or ensure `detectTraces_`’s serial code cannot throw.

---
---
### 8. Stream fallback resets dnoise counters but not gate state
**Status**: **Clean**.
**Rationale**: `dnoise.total` is reset on fallback, but `dnoise.gate` and `dnoise.im_asc` are immutable after `setup()` and reused for the resident load. The gate depends only on tdf metadata, which is identical for both paths. No state divergence.

---
---
### 9. parseF64’s finite-decimal contract
**Status**: **Clean**.
**Rationale**: Deliberately refuses subnormals, inf, nan, and out-of-range values to match the port’s contract (dnoise’s gate builder would degenerate on these). Documented and validated against D’s pinned gate boxes.

---
---
### 10. dnoise:ms1 option defaults and stamps
**Status**: **Clean**.
**Rationale**: Default `"true"` is registered with valid strings `{"true", "false"}`, stamps correctly differentiate `"skipped (input is not a Bruker .d)"`, `"off"`, and port version. Header stamps (`spx:dnoise_ms1*`) match validation results.

---
---
### 11. Tests 19/19b/19c/20 sensitivity
**Status**: **Clean**.
**Rationale**:
- **19**: Fixture ensures witnesses are load-bearing (no-witness control adds exactly one MS1 trace).
- **19b**: Interior chain links are independently load-bearing at 48 bands (no-chain control flips 26 bands).
- **19c**: Descending m/z order produces identical output to ascending (pins entire pipeline).
- **20**: mzML skip is logged, stamped, and output-identical to `-dnoise:ms1 false`.

---
---
### Summary (Most Severe First)
| # | Severity | Issue | Location | Fix |
|---|----------|-------|----------|-----|
| 1 | **Critical** | TOF bin range check uses hardcoded max instead of `ax.n_bins` | `spextractor.cpp:DnoiseRun::frame()` | `bin < ax.n_bins` |
| 2 | **Critical** | Locale-dependent `AccumulationTime` parsing | `src/TdfLoad.h:loadTdfDnoise()` | Use `parseF64` |
| 3 | **High** | Compile-time FP checks miss `-funsafe-math-optimizations` etc. | `src/DnoiseMs1.h` | Expand `#error` or add runtime gate self-test |
| 4 | **High** | TOF axis validity not checked early in `setup()` | `spextractor.cpp:DnoiseRun::setup()` | Call `checkLoader()` after axis load |
| 5 | **Medium** | Arbitrary intensity recovery loop bounds | `spextractor.cpp:DnoiseRun::frame()` | Tighten to `[(v−0.5)/corr, (v+0.5)/corr]` |
| 6 | **Medium** | Non-finite m/z breaks `sortByPosition()` | `spextractor.cpp:Ms1Prune::frame()` | Reject NaN m/z spectra |
| 7 | **Medium** | Exception containment gap in `detectTraces_` caller | `spextractor.cpp` (MS1 tracing) | Extend `try` block to cover full call |
