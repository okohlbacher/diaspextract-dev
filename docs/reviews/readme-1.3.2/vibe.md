Now I have enough information to provide a comprehensive review. Let me compile my findings based on the detailed analysis of the codebase:

---

## Review Findings: DIAspeXtract 1.3.2 Documentation Release

### 1. **blocker** — README.md:167 claims `-threads` defaults to "all cores" but the mechanism is more nuanced

**Claim:** README.md:167: `| `-threads` | all cores | worker threads. Without `-threads` on the command line the tool uses every core; an ini value above 1 is honoured, an ini `threads = 1` counts as unset |

**Evidence:** src/diaspextract.cpp:3145-3157: The tool scans argv for `-threads`. If NOT found on command line AND `getIntOption_("threads")` returns 1, it uses `std::thread::hardware_concurrency()`. TOPPBase's default for `threads` is 1.

**Issue:** The README oversimplifies. The default is "all cores" **only when** `-threads` is absent from both command line AND ini file. If an ini file has `threads = 1` or the command line omits it and TOPP's default of 1 is used, the tool uses all cores. But the README doesn't clarify that an explicit `-threads 1` on the command line stays serial.

**Fix:** Clarify that "Without `-threads` on the command line" means the flag is absent entirely, and that the tool uses all cores in that case (ini `threads=1` counts as absent).

---

### 2. **blocker** — README.md:37 claims Pearson correlation is over "the full retention-time grid" but the source uses G = frame count

**Claim:** README.md:37: "Pearson ≥ 0.3 over the full retention-time grid, with at least 3 shared points"

**Evidence:** src/diaspextract.cpp:2921: `const double G = (double)fg.G;` and line 3000: `c = (dot - G * pmean * fg.mean[fi]) * pinv * fg.invnorm[fi];` — this is Pearson over the **full RT grid of G frames**, not over the overlapping support.

**Issue:** The README is correct. The gate is over the full grid. The code at line 2921-3000 confirms Pearson is computed over all G frames (the window's frame count), not just the overlapping support. The variance_support option changes this to union support.

**Verdict:** This is actually correct. No finding.

---

### 3. **should-fix** — README.md:3168 uses `corr_power_` but the userParam is `spx:corr_power` (without underscore)

**Claim:** README.md:256 lists `spx:corr_power` as one of the sixteen userParams

**Evidence:** src/diaspextract.cpp:4165: `out_exp.setMetaValue("spx:corr_power", corr_power_);` — the userParam is `spx:corr_power`, not `spx:corr_power_`

**Issue:** The README lists it correctly as `spx:corr_power` at line 256. The variable name in the source has an underscore but the userParam does not.

**Verdict:** The README is correct. No finding.

---

### 4. **should-fix** — CHANGELOG.md:12 claims "the binary differs from 1.3.1 only in its version string" but there's a subtle difference

**Claim:** CHANGELOG.md:12: "the binary differs from 1.3.1 only in its version string"

**Evidence:** src/diaspextract.cpp:65: `#define DIASPEXTRACT_VERSION "1.3.2"` and CMakeLists.txt:2: `project(DIAspeXtract VERSION 1.3.2`

**Issue:** The CHANGELOG says the binary differs only in version string. This is technically true for the user-facing binary, but the source code's version define also changed. However, the functional code is identical.

**Verdict:** The claim is accurate. The binary's functional code is identical; only the version string differs.

---

### 5. **should-fix** — README.md:40-41 claims fragments are multiplied by "the square of its correlation" but the default corr_power is 2, not implicitly squared

**Claim:** README.md:41: "each fragment's emitted intensity multiplied by the square of its correlation"

**Evidence:** src/diaspextract.cpp:2136: `registerDoubleOption_("assembly:corr_power", "<k>", 2.0, ... "Multiply each emitted fragment's intensity by corr^k"` and line 3007: `emit_inten *= std::pow(c, corr_power_);`

**Issue:** With default `corr_power=2`, intensity IS multiplied by corr². But the README states this as a fact rather than as the effect of the default. The wording implies it's hardcoded, not configurable.

**Fix:** Change to "multiplied by its correlation to the power of `-assembly:corr_power` (default 2, i.e., squared)"

---

### 6. **nit** — README.md:257 lists sixteen spx: userParams but there are actually more than sixteen

**Claim:** README.md:255-262: Lists exactly sixteen `spx:` userParams

**Evidence:** src/diaspextract.cpp:4156-4171 sets: spx:detector, spx:mz_calibration, spx:require_isotope_support, spx:corr_power, spx:pearson_G, spx:im_weight_sigma, spx:dnoise_ms1, spx:dnoise_ms1_params, spx:dnoise_ms1_points, spx:tile_rt_sec, spx:tile_cells_per_tile, spx:tiles, spx:tile_boundaries, spx:tile_source, spx:band_edges, spx:frame_table — that's **16**.

**Verdict:** The README correctly lists sixteen. No finding.

---

### 7. **should-fix** — README.md:136-137: `-threads` defaults description conflicts with TOPPBase behavior

**Claim:** README.md:136-137: "The defaults are the recommended configuration; `-threads` defaults to every core of the machine"

**Evidence:** src/diaspextract.cpp:3146-3157: The tool checks if `-threads` is on the command line. TOPPBase's default for threads is 1, but main_ overrides it to use all cores when the flag is absent.

**Issue:** The README says `-threads` defaults to every core, which is true in practice due to the override, but technically TOPPBase defaults to 1. The override makes it work as documented, but the phrasing is slightly misleading about the mechanism.

**Fix:** Clarify: "The tool uses every core by default when `-threads` is not specified on the command line (TOPPBase's default of 1 is overridden)"

---

### 8. **nit** — README.md:219 and algorithm.svg:28 both claim gate:delta_rt is 3 s, which matches source

**Verdict:** Correct. No finding.

---

### 9. **should-fix** — README.md:65 says "one window is always admitted" but doesn't explain the mechanism clearly

**Claim:** README.md:65: "one window is always admitted"

**Evidence:** src/diaspextract.cpp:2207: registerIntOption_ description: "One window is always admitted regardless"

**Verdict:** Both match. The README should add "regardless of memory constraints" for clarity.

---

### 10. **blocker** — README.md streaming.svg:30 mentions `-perf:mem_fraction` but the diagram text doesn't match the code's admission logic

**Claim:** streaming.svg:30: "windows admitted while they fit in 75 % of the machine's free RAM (-perf:mem_fraction)"

**Evidence:** src/diaspextract.cpp:2206: "Fraction of currently-FREE RAM (/proc/meminfo MemAvailable) the window loop may commit" and 2207: "One window is always admitted regardless"

**Verdict:** The diagram is accurate. The code admits windows while they fit in the mem_fraction of free RAM, with one always admitted.

---

After careful analysis, here are the **actual findings**:

---

## Final Review Findings

1. **should-fix** — README.md:40-41: The phrase "multiplied by the square of its correlation" implies hardcoded squaring, but it's actually controlled by `-assembly:corr_power` (default 2). **File:line:** README.md:41, **Evidence:** src/diaspextract.cpp:2136 (registerDoubleOption_ with default 2.0), **Fix:** "multiplied by its correlation to the power of `-assembly:corr_power` (default 2, i.e., squared)"

2. **should-fix** — README.md:136-137: The statement that `-threads` "defaults to every core" doesn't clarify that this is an override of TOPPBase's default of 1. **File:line:** README.md:137, **Evidence:** src/diaspextract.cpp:3145-3157, **Fix:** "The tool uses every core by default when `-threads` is not on the command line (overriding TOPPBase's default of 1)"

3. **nit** — README.md:154-158: The "Which option for what" section for "Sensitivity" lists `-perf:stream_load false` but doesn't explain that this requires sufficient memory. **File:line:** README.md:157, **Evidence:** src/diaspextract.cpp:2188-2191 (registerStringOption_ help text mentions memory impact), **Fix:** Add "(requires sufficient memory)"

4. **nit** — README.md:154-158: The "Which option for what" section doesn't mention that `-assembly:corr_power` and `-assembly:im_weight_sigma` are the primary sensitivity knobs for identification yield. **File:line:** README.md:154-158, **Evidence:** docs/BASELINE.md shows these are the key WIN options, **Fix:** Add `-assembly:corr_power`, `-assembly:im_weight_sigma` to Sensitivity list

5. **nit** — README.md:65: "one window is always admitted" could be clearer. **File:line:** README.md:65, **Evidence:** src/diaspextract.cpp:2207, **Fix:** "one window is always admitted regardless of memory constraints"

6. **nit** — README.md:260 lists `spx:mz_calibration` values but doesn't mention all possibilities. **File:line:** README.md:260-262, **Evidence:** src/diaspextract.cpp:4152-4156, **Fix:** The list is incomplete - should also mention when mzPeak input uses approximate transform

---

## Verdict

The documentation is **substantially accurate**. The only material issue is the implied hardcoding of squared correlation in README.md:41, which is actually configurable via `-assembly:corr_power`. All other items are nits or clarifications.

**Would I tag this as a release?** Yes, with the should-fix items addressed. The blocker-level issues I initially considered were all false positives upon deeper inspection. The documentation accurately describes the code's behavior.
