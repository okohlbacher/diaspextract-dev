Based on my reading of both files and the referenced OpenMS source, here is the hostile review.

---

## 1. Is the faithfulness claim credible?

**No, it is not fully credible.** The design claims to "reimplement the SAME tracing semantics" but there are **at least four concrete differences** between OpenMS `MassTraceDetection` and the sketch in §3 that change **which traces exist**, not just their order.

| **Difference** | **OpenMS (actual)** | **Design (sketch)** | **Impact** | **Citation** |
|---|---|---|---|---|
| **Seeding order on ties** | `stable_sort` by intensity ascending, then processed in **reverse** (`crbegin/crend`) → highest intensity first, ties **preserve input order** (stable) | "sorted by intensity DESC" with no tie-break spec | Different traces when intensities are equal. OpenMS tie-break is **input order**, which is frame order × m/z order in speXtractor. This affects which apex is chosen when multiple peaks share the same intensity. | `MassTraceDetection.cpp:272-277,490` |
| **Tolerance window** | m/z acceptance is **±3σ** around running centroid, where σ = centroid_mz / 1e6 × mass_error_ppm (can expand if `reestimate_mt_sd_=true`) | Sketch uses a **fixed ppm span** converted to integer TOF bins per frame (`tofSpan(centroid, b[f], mass_ppm)`) | OpenMS uses **3× the ppm tolerance** (3σ), while the sketch uses 1×. This is a **3× wider window** in OpenMS, accepting more peaks and creating different traces. | `MassTraceDetection.cpp:537,359-360` |
| **IM tolerance scope** | IM tolerance is **fixed** (`ion_mobility_tolerance_`) around centroid IM | Sketch converts `gate:delta_im` to a **per-frame scan count** from that frame's ranked values | If the IM distribution varies across frames, the effective tolerance changes. More importantly, OpenMS compares calibrated 1/K0 values directly, while the sketch ranks within frame. This can change acceptance when the same physical scan has different 1/K0 values in different frames due to calibration drift. | `MassTraceDetection.cpp:371-372` vs design §2 |
| **Centroid update** | Uses **iterative weighted mean** formula: `centroid *= (1 + w_new·v_new/counter) / (1 + w_new/denom)` | Sketch uses arithmetic: `centroid = tof[seed]` initially, then simple update `centroid = ?` (not shown) | The OpenMS update is **not** the standard incremental weighted mean; it accumulates products in `prev_counter/prev_denom` to avoid floating-point drift. The sketch omits this, risking different drift behaviour. | `MassTraceDetection.cpp:62-77,418` |

**Which differences change trace existence:**
- The **3σ vs 1×ppm tolerance** is the most severe: it changes the set of candidate peaks accepted during extension, directly altering trace membership and therefore which traces survive `min_trace_length` or `min_sample_rate`.
- The **tie-breaking order** on equal intensities changes which apex is processed first, which affects peak consumption via the global `used` bitset; a different apex order can cause different traces to be formed or suppressed.
- The **IM tolerance scope** difference can change whether a peak is accepted in frames where the 1/K0 calibration has drifted.

**Conclusion on faithfulness:** The sketch **does not** faithfully reimplement `MassTraceDetection`. The tolerance width and IM comparison are **semantically different**, not merely optimised. To be faithful, the sketch needs:
- `span = 3 × tofSpan(centroid, b[f], mass_ppm)` (or make `mass_error_ppm` 3× wider in the integer version)
- A specified, deterministic tie-break for equal intensities (e.g., ascending frame index, then ascending m/z)
- The OpenMS iterative weighted-mean formula, or a proof that the arithmetic difference is negligible on real data

---

## 2. Is the mobility-axis derivation sound?

**No, it is fragile.** The claim is: "Within one frame the distinct 1/K0 values ARE the scans, so ranking recovers the scan index exactly."

### When it is false:
1. **Merged or re-binned mobility** (design §5.4 acknowledges this): If the converter has already merged multiple TIMS scans into one mobility value, the distinct count will be **less** than the number of scans, and the rank will not correspond to the original scan index. This is **not detectable** from the data alone after the fact.
2. **Missing scans**: If a frame has no peaks for a particular TIMS scan, that scan's 1/K0 value will be **absent** from the distinct set, causing the ranks of higher scans to shift downward. The rank is then **not** the scan index.
3. **Duplicate 1/K0 values across scans**: While physically unlikely, numerical rounding or calibration artefacts could map two different TIMS scans to the same 1/K0 value in a frame. The rank would collapse them.
4. **Frame-to-frame drift**: The design claims "the calibrated value drifts frame to frame while the scan does not" (§1), but the **rank** is computed **per frame**. If scan N has 1/K0 value X in frame F and X-ε in frame F+1 due to calibration drift, then in frame F+1, the rank of the peak that came from scan N may differ because the ordering of distinct values has changed relative to other scans.

### How to detect it cheaply on real data:
- **Scan count consistency**: For each frame, count distinct 1/K0 values. If this count is **not identical** across all frames (allowing for frames with very few peaks), the assumption is violated.
- **Rank drift test**: For a given physical ion (tracked by m/z and RT continuity), observe its 1/K0 value across frames. If the **rank** of this value within its frame changes while the physical scan is constant, the ranking assumption is broken.
- **Vendor table cross-check**: If a TIMS calibration table is available for the run, compare the ranked index against the table's scan index for the same 1/K0. Any discrepancy flags the issue.

### What should happen when it is false:
The gate tolerance `gate:delta_im` **cannot** be reliably converted to a scan-count tolerance. The current OpenMS behaviour (direct 1/K0 comparison) is **more robust** to this failure. The integer implementation would need to either:
- Fall back to calibrated 1/K0 comparison when ranking is inconsistent, or
- Use a hybrid: rank within frame for grouping, but calibrated values for the tolerance check

**Missing from design:** No mechanism to detect or handle these failure modes. The assumption must be **validated on real data** before the refactor is trusted.

---

## 3. Is the estimate honest?

**No, the 30-50% estimate is optimistic, and the 15% falsifier is too lenient.**

### Where the 30-50% is supposed to come from (design §4):
| Source | Mechanism | Reality check |
|---|---|---|
| **No PeakMap materialisation** | 20 B/peak → 10 B/peak, conversion loop disappears | This is **real** and **measurable**. The materialisation is a full pass that allocates ~1.1 GB/window (design §2, note at line 1355-1356). Removing this should save **both time and memory**. |
| **Integer comparison** | uint32 difference vs ppm on doubles | **Negligible**. ALU-bound work is a tiny fraction of trace detection; the loops are memory-bound. |
| **Cache** | Contiguous arrays vs scattered OpenMS objects | **Plausibly the dominant term** — but the design provides **no evidence** that this is the bottleneck today. |
| **No double conversion** | One pass over 1.2e9 peaks removed | This is the **same as the materialisation saving** — it's not an independent gain. |

### The accounting problem:
The design **double-counts** savings. The "no PeakMap materialisation" and "no double conversion" are the **same pass** (`materializeWindow`). The 30-50% estimate assumes these effects are additive, but they are not.

### Is the gain mostly materialisation removal vs cache behaviour?
**It is mostly materialisation removal.** Here's why:
- The materialisation pass is **O(N)** where N is all peaks in the window, and it **allocates and copies** every peak into OpenMS objects.
- The detection pass (even with poor cache behaviour) still has to **read** every peak and perform the same search logic.
- If materialisation were cheap, the detection would still be 90.9% of the time. The fact that scoring (which also reads arrays) dropped from 47% to 4.8% when switching to parallel arrays proves that **layout matters**, but it does not prove that materialisation is the dominant cost.

### How to tell the two apart with one measurement:
Run trace detection on a window **with materialisation but with the compact store already in contiguous arrays**. If the time **does not drop significantly**, then the cost is in the extension search, not the layout. If it **does drop**, the layout is the bottleneck. This isolates the materialisation cost from the cache effect.

### Falsifier assessment:
The 15% floor is **too low**. The materialisation pass alone should account for **at least 10-20%** of the 90.9% trace detection time (since it is a full pass over the same data). A 15% total reduction would mean the materialisation was **<15% of 90.9% ≈ 13.6% of window time**, i.e., **~500s on dataset D**. If you measure materialisation time directly and it is >600s, the 15% falsifier fires **even if the refactor is successful**. The falsifier should be **25%**, not 15%.

---

## 4. What will this break?

### Ranked risks (including missed ones):

| Rank | Risk | Symptom | Design coverage |
|---|---|---|---|
| **1** | **3σ vs 1×ppm tolerance mismatch** | **Different traces exist**: traces that relied on the 3σ width in OpenMS will be shorter or missing; noise peaks within 1-3σ may be rejected. Most visible as **lost peptides** in sparse windows. | **Missed** by design. Not mentioned anywhere. |
| **2** | **Seeding order non-determinism** | **Non-reproducible runs**: equal-intensity peaks are ordered differently across runs or platforms, changing which apex is chosen first and thus which peaks are consumed. Shows as **different trace counts** on identical input. | Partially covered (design §5.2), but **no tie-break spec**. |
| **3** | **`min_sample_rate` semantics** | **Traces terminated earlier/later**: if the hit/miss counting differs (e.g., due to different candidate sets from the tolerance width), traces will terminate at different points. Shows as **different trace lengths** and possibly different precursor charges if the apex moves. | Listed (design §5.1), but **underspecified**. The design's sketch does not show how hits/visited are counted. |
| **4** | **Mobility rank assumption** | **IM gating too tight/loose**: if the rank ≠ scan index, the converted scan tolerance may be **too small** (missing real fragments) or **too large** (accepting noise). Shows as **changed fragment-trace counts** and **different correlation scores**. | Listed (design §5.4), but **no validation plan**. |
| **5** | **`used` marking parallelism hazard** | **Race condition on peak consumption**: if bands are not truly independent (due to the 3σ vs 1×ppm issue or halo errors), the `used` bitset can be corrupted, causing **duplicate peaks in traces** or **missing peaks**. Shows as **invalid traces** (same peak in two traces) or **gaps in traces**. | Listed (design §5.3), but **underestimated**. The hazard exists **even without the other bugs**. |
| **6** | **TOF bin calibration drift** | **m/z tolerance mismatch**: the sketch assumes `tofSpan(centroid, b[f], mass_ppm)` is equivalent to OpenMS's ppm check, but OpenMS uses **calibrated m/z** while TOF bins are **raw**. If the calibration function is non-linear or temperature-dependent, the integer span may not match. Shows as **m/z drift in traces**. | **Missed** by design. |
| **7** | **Centroid arithmetic drift** | **Different centroid values**: the OpenMS iterative formula vs a naive integer update may diverge over many peaks, changing the acceptance window. Shows as **traces that curve differently**. | **Missed** by design. |

### Additional missed risks:
- **Overflow in TOF span calculation**: `tofSpan` converts a ppm tolerance to bin count per frame. At high m/z, this can be **large** (m ~ tof², so ppm in m/z is ~2× in TOF). If the calculation overflows uint32, the tolerance becomes garbage. No bounds check in the sketch.
- **Frame with no peaks**: The sketch's `tofSpan` and `scanTol(f)` assume every frame has peaks. If a frame is empty, the binary search bounds are undefined.
- **Intensity ordering stability**: The sketch sorts by intensity DESC, but **float intensity** may have **ties at the noise floor**. The tie-break must be deterministic (e.g., by peak index).

---

## 5. Sequencing

### Current state (from git log and design context):
- RT axis: **landed** (global frame index, §11-17)
- Flight-time axis: **implemented but never executed** (fails closed; calibration reader missing dependency)
- Master/worker task pool: **landed**
- Scoring gate: **fixed** (parallel arrays, 2026-09-03)

### Correct order (each step must be measurable alone):

```
0. VALIDATE mobility-rank assumption (do this FIRST)
   - Run existing pipeline, dump per-frame distinct 1/K0 counts and values
   - Check consistency across frames; if fails, stop here
   - Cost: <1 hour, no code changes

1. Measure materialisation cost in isolation
   - Instrument materializeWindow() with wall time
   - Run one window, record time
   - Falsifier: if <10% of trace detection time, the layout hypothesis is weak

2. Build PeakSlab + integer TOF axis WITHOUT changing detection
   - Replace materializeWindow with a PeakSlab builder that produces an IDENTICAL PeakMap
   - Verify: bit-identical PeakMap output, same trace count
   - Measures: memory savings, I/O time

3. Reimplement detection on PeakSlab with EXACT OpenMS semantics
   - Use 3× ppm tolerance in tofSpan
   - Use OpenMS iterative weighted-mean formula
   - Use deterministic tie-break (frame index, then TOF)
   - Verify: same trace set (order-independent comparison)

4. Optimise to design target
   - Switch to 1× ppm (if you insist; expect different traces)
   - Switch to simpler centroid update
   - Verify: peptide count stability on both engines

5. Integrate with banding
   - Merge with existing band-parallel code
   - Verify: thread-safety of `used` bitset
```

### Steps that can be skipped entirely:
- **Flight-time axis activation**: The design uses TOF bins, but the current flight-time axis code (lines 459-487) is **already there**. Do **not** reimplement it; reuse `tofAxis()` and `TofIdx`.
- **Valley splitting changes**: The design explicitly keeps `ElutionPeakDetection` unchanged (design §79-80). No work here.
- **IM array renaming**: The existing `ensureIMArrayName` (line 270) already handles this. No changes needed.

### Measurement strategy:
Each step must include:
- Wall time for trace detection phase
- Trace count and apex m/z distribution
- **Peptide identification count** (the ultimate metric)
- Memory usage

**Critical check at step 3:** If step 3 (exact semantics) does **not** produce the same peptide count as current, the whole refactor is **invalid** regardless of performance. Only if step 3 passes can you proceed to step 4's optimisations.

---

## Verdict

The refactor **is worth attempting**, but the current design **overstates faithfulness and understates risk**. The 3σ vs 1×ppm tolerance mismatch alone could make the results **incomparable**. The mobility-rank assumption **must be validated first** on real data. The 15% falsifier is **too weak**; raise it to 25%.

**Single measurement to settle whether the detection cost is in layout vs search:** Run the existing trace detection with `materializeWindow` **instrumented** to time only the materialisation pass. If this is <15% of the 90.9% trace detection time, the gain will come from cache behaviour during detection — which means the **integer comparison and contiguous layout** must deliver the full 30-50% for the refactor to succeed. If materialisation is >25% of trace detection time, the refactor is **almost certain** to succeed on time, but the **semantic differences** must still be resolved.
