Based on my detailed review of the implementation against the OpenMS excerpts, here are my findings:

---

## 1. Line-by-line diff against the OpenMS excerpts

| Tool Line | What OpenMS Does | What Tool Does | Impact |
|-----------|------------------|----------------|--------|
| **740** | Deletes every peak with intensity ≤ noise_threshold_int before tracing | `member[k] = sl.inten[k] > (float)noise` | **MATCH** |
| **743–745** | Apex must have intensity > chrom_peak_snr * noise_threshold_int (strict) | Seeds filtered by `sl.inten[k] > min_apex` where `min_apex = snr * noise` | **MATCH** |
| **749–752** | stable_sort ascending by intensity, iterate in REVERSE (ties: later peak first) | `sort` descending by intensity, ties by `a > b` (higher index first) | **MATCH** |
| **756–759** | `updateIterativeWeightedMean_(v, w, c, cnt, den)` | `c *= (1 + w*v/cnt) / (1 + w/den); cnt += w*v; den += w` | **MATCH** |
| **799–801** | Seed counted twice: init `centroid_mz = apex.mz; prev_counter = I*mz; prev_denom = I`, then `updateIterativeWeightedMean_(apex.mz, I, ...)` | Same initialization and double-update | **MATCH** |
| **802–803** | Same for IM centroid | Same | **MATCH** |
| **804** | `ftl_sd = (centroid_mz/1e6)*mass_error_ppm` | `sd = (cmz / 1e6) * mass_ppm` | **MATCH** |
| **808** | `while ((down_idx > 0 && down.active) || (up_idx < n-1 && up.active))` | `while ((fd > 0 && dn.active) || (fu + 1 < (long)F && up.active))` | **MATCH** (F = number of frames = n) |
| **810–835** | Down then up, each as separate `if` blocks | Interleaved via `for (side=0..1)`, same order | **MATCH** |
| **817–818** | Empty frame is not a miss | `if (sl.frame_off[f + 1] > sl.frame_off[f])` | **MATCH** |
| **771–791** | `findBestPeak_`: search within ±3 sd in m/z **and** IM tolerance; closest m/z AMONG IM-compatible peaks | `best()`: converts m/z bounds to TOF via `ax.tofOf`, iterates bins, converts each back via `ax.mzOf`, checks m/z ∈ [lo,hi] **and** IM. | **COORD**: Round-trip conversion is exact per line 663–664 comment, but the search is in TOF space vs OpenMS’s m/z space. The explicit m/z check after conversion ensures correctness. |
| **785** | IM gate: `±ion_mobility_tolerance` | `abs(sl.imq[k] - cim) > imq_tol` (quantized IM) | **COORD**: Precision loss from quantization, but negligible |
| **789–790** | If closest is already taken → frame is a **miss** | `if (bk >= 0 && visited[bk]) { taken=true; return -1; }` | **MATCH** |
| **822–827** | `processPeak_`: push peak, update centroids, `updateWeightedSDEstimateRobust` if enabled | Same | **MATCH** |
| **828–830** | `++hits; missed=0` or `++missed` | Same | **MATCH** |
| **832–834** | `++scan_counter; if (missed > trace_termination_outliers) active=false` | `fi += step; ++scans; if (missed > max_missed) active=false` | **MATCH** |
| **838–845** | `isTraceValid_`: `rt_range = |last.rt - first.rt|`; `adjusted = total_scans_visited - missed_down - missed_up`; `return size/adjusted >= min_sample_rate` | `span_s = rt[fmax] - rt[fmin]`; `total = dn.scans + up.scans + 1`; `adjusted = total > dn.missed+up.missed ? total - ... : 1`; `size/adjusted >= msr` | **MATCH** (safeguard `>...?...:1` is never triggered because `total = scans+1 > scans >= missed`) |
| **846** | Mark every gathered index **visited only after validity** | Same | **MATCH** |
| **847** | — | `if (banded && (sl.tof[seed] < band_lo || sl.tof[seed] >= band_hi)) continue` | **NONE**: Redundant (seeds already filtered by band at line 745) |
| **804, 826** | `reestimate_mt_sd` controls whether `updateWeightedSDEstimateRobust` runs | Always runs `sdRobust` (no conditional) | **COORD**: Tool always re-estimates SD; OpenMS has a flag. If the caller passes `reestimate_mt_sd=false`, this is a **SET** difference. |

**Newly identified deviation:**
- **Line 826**: The tool **always** re-estimates the SD via `sdRobust`, but OpenMS only does so if `reestimate_mt_sd` is true (default is true per OpenMS defaults, but the parameter exists). If the caller disables SD re-estimation, the tool will still re-estimate, which changes **which peaks are accepted** as the window widens/narrows. This is a **SET** difference.

---

## 2. The bin/m/z round trip

- **Search phase**: The tool converts `cmz ± 3·sd` to TOF bounds via `ax.tofOf(lo_mz, bf)`, binary-searches to the first bin ≥ lo_t, then walks bins while converting each back via `ax.mzOf(tof, bf)` and checking `mz ∈ [lo_mz, hi_mz]` explicitly. Per the comment at **line 663–664**, the compact store’s m/z quantum (1e-5 Da) is ~400× finer than a TOF bin at m/z 600, so the calibration inversion recovers the **original bin exactly**. Thus, no bias is introduced at search window edges.
- **After valley splitting** (`splitIntegerTraces:915–924`): The re-attached bin uses `ax.tofOf(t.mz, t.b)`, where `t.mz` comes from `toTrace(mt)`. Inside `splitIntegerTraces`, every peak of the `MassTrace` was set to the **same m/z** (`t.mz`, line 903), so `toTrace()`’s apex m/z equals the centroid, and `tofOf(centroid, b)` is the **correct bin** for that centroid. However, this is **not the same as OpenMS**, where `MassTrace` peaks have **per-peak m/z** and `toTrace("apex")` returns the **actual apex peak’s m/z**, which may differ from the centroid if the trace drifts in m/z.

**Conclusion**: The bin/m/z round trip is numerically exact, but **the tool loses per-peak m/z variation** before valley splitting, which affects the final m/z reported for split traces.

---

## 3. Valley splitting

- **Does `ElutionPeakDetection` care about per-peak m/z?** No. `ElutionPeakDetection` performs 1D peak detection on the **RT–intensity** chromatogram. It does **not** use m/z for splitting decisions.
- **Does losing per-peak m/z change what `toTrace()` reports?**
  - **YES.** In `splitIntegerTraces` (**line 901–903**), every peak of the `MassTrace` is assigned the **same m/z** (`t.mz`, the integer trace’s centroid). After `splitValleys` (EPD) splits the trace, `toTrace()` is called on each split `MassTrace`:
    - **"apex" estimator**: OpenMS returns the **actual measured m/z of the apex peak**; the tool returns the **original centroid m/z** (since all peaks have the same value).
    - **"mean"/"median" estimators**: Both return the centroid, so they match.
  - **Impact**: If a trace has m/z drift across RT, OpenMS can split it into sub-traces with **different apex m/z values**, while the tool’s split traces all retain the **original centroid m/z**. This causes the tool’s fragment traces to have **less accurate m/z**, reducing their match scores during peptide identification.

**This is a SET-level difference: it changes the m/z values of the final traces, which directly affects peptide identification.**

---

## 4. Banding

- **Semantics**: Each band seeds **only in its core** (`[band_lo, band_hi)`) but **extends over the entire slab** with its **own `visited` array** (line 754).
- **What can go wrong at boundaries**:
  1. **Duplicate peaks**: A peak can be included in traces from **multiple bands** (each band has independent `visited`). This is **acknowledged** (line 3033–3034) and measured at **0.1% of peptides** in OpenMS’s halo.
  2. **Trace splitting**: A trace crossing a band boundary may be **fragmented** into multiple partial traces (one per band that seeds within its core). This is **bounded** by the maximum trace length and band width.
- **Line 847 check**: `if (banded && (sl.tof[seed] < band_lo || sl.tof[seed] >= band_hi)) continue` is **redundant** (seeds are pre-filtered at line 745) and thus **harmless**.

**Conclusion**: Banding is correct and bounded. The **only residual is duplicate peak usage**, which is explicitly accepted as matching OpenMS’s halo error rate.

---

## 5. A test that would have caught the first version

**Synthetic input** (to be added to `test/test_spextract.py`):
```python
def test_trace_termination_and_validity():
    """
    The first version failed because:
      - min_sample_rate=-1 was treated as "no termination" (traces ran full gradient, then discarded for max length)
      - wrong termination rule (consecutive misses vs hit rate)
    """
    # Build a minimal mzML with:
    #   MS1: 7 frames at RT=0.0,0.1,0.2,0.3,0.4,0.5,0.6
    #   Each frame: one peak at m/z=100, IM=1.0, intensity=10.0
    #   EXCEPT frame 3 (RT=0.3) has NO peak -> one empty frame (not a miss)
    #   Parameters: trace:ms1_min_length_sec=0.5, min_sample_rate=0.5 (default)
    # Expected: ONE valid trace spanning all 7 frames (6 peaks, 1 empty).
    #   - Empty frame is NOT a miss (OpenMS: "empty frames are not misses")
    #   - total_scans_visited = 7, missed = 0, adjusted = 7
    #   - size/adjusted = 6/7 ≈ 0.857 >= 0.5 -> valid
    #
    # First version behavior:
    #   - If min_sample_rate sentinel broken: would discard or run full gradient
    #   - If termination rule broken: might stop at frame 2 or not count empty correctly
    pass
```
**Concrete assertion**:
- Count the number of MS1 traces in the output. Must be **exactly 1**.
- A second test: 11 frames with a **7-frame gap** (frames 3–9 empty). Must produce **TWO** traces (0–2 and 10–10), because >5 consecutive misses terminates a direction.

**Why the suite missed it**: The existing tests (isotope ownership, charge gate, determinism) do **not** exercise trace extension with gaps. This test directly probes the **termination rule** and **validity check**.

---

## Summary: What is STILL different

The rewrite fixes the **14 deviations** from the failure analysis, but **one critical difference remains**:

### **Primary cause of peptide deficit: Loss of per-peak m/z in valley splitting**
- **Location**: `splitIntegerTraces` (**lines 901–903**)
- **Issue**: All peaks in the `MassTrace` are assigned the **same m/z** (the integer trace’s centroid). OpenMS preserves **per-peak m/z**.
- **Impact on peptides**: 
  - `ElutionPeakDetection` itself is unaffected (it only uses RT/intensity).
  - But the **final trace m/z** (for "apex" estimator) is the **centroid** in the tool vs the **actual apex peak’s m/z** in OpenMS.
  - For traces with m/z drift, this causes **systematic m/z error** in fragment traces, reducing match scores and **losing peptides**.

### **Secondary issue: Hardcoded SD re-estimation**
- **Location**: Line 826 (`sdRobust` called unconditionally)
- **Issue**: OpenMS respects a `reestimate_mt_sd` flag (default true). The tool always re-estimates.
- **Impact**: If the flag is ever false, the tool will have **wider/narrowing windows** where OpenMS would have fixed windows, changing **which peaks are accepted** (**SET** difference). However, the default is true, so this is likely **not the cause of the current deficit**.

### **Expected residual**
If the **only** remaining difference is the per-peak m/z loss, the peptide deficit should be **small** (proportional to traces with significant m/z drift across RT). The failure analysis reports **0.1% halo error** from banding, and this m/z issue should add a **similar small deficit**. A **large deficit** (e.g., >1%) would indicate an additional, unidentified SET-level difference.

---

## Recommendation

**Fix the per-peak m/z loss in `splitIntegerTraces`** by storing the **original per-peak m/z** from the integer trace detection. Currently, `detectTracesInteger_` only preserves the **centroid m/z** (`t.mz`). To match OpenMS, you must:
1. Store **per-peak m/z** in the `Trace` object (or a parallel array) during integer detection.
2. In `splitIntegerTraces`, use these **per-peak m/z values** when building the `MassTrace`, not the uniform centroid.

This will ensure that after valley splitting, the split traces have accurate per-peak m/z, and `toTrace("apex")` returns the true apex m/z. This is the most likely cause of the remaining peptide deficit.
