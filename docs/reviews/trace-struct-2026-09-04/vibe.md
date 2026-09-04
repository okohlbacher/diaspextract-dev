Based on my reading of both the redesign document and the full source code, here is my **hostile adversarial review** of the proposed trace struct redesign.

---

---

---

## **1. Is "one degree of freedom" true?**

**CLAIM:** A trace point has ONE degree of freedom (intensity); the frame is implied by `frame0 + i`; the bin is per trace.

**FINDING: FALSE.** Multiple consumers require information that the redesign discards.

### **(a) OpenMS detector path: `toTrace()` CANNOT express MassTrace peaks as dense spans with zeros**

- **Line 315 (DIAPseudoSpectra.cpp):** `pts.emplace_back(rtIndex(mt[i].getRT()), (float)mt[i].getIntensity());`
- **Line 312-318:** `toTrace()` collects `(frame_index, intensity)` pairs from a `MassTrace`, **sorts them by frame index**, and builds `xi`/`xv` from the sorted order.

**Problem:** `MassTrace` peaks are **NOT guaranteed to be one-per-frame or contiguous on the RT axis**. OpenMS `MassTraceDetection` accepts gaps. The redesign assumes `xi[i] == frame0 + i` for all `i`, but:
- A MassTrace can have peaks at frames `[10, 12, 15, 18]` — these are **not** expressible as `frame0=10, len=8` with zeros at 11,13,14,16,17
- The **span** would need to be `[10,18]` (9 frames), but the **points** are only at 4 specific frames
- **Zero-padding would fabricate data** — the MassTrace has NO intensity at frame 11, but the redesign would insert a zero there, changing the correlation semantics (see Section 2)

**The redesign document claims (line 94-96):** "`toTrace()` finds `frame0` as the index of the first peak's RT... and writes intensities into the arena with zeros for gaps."

**This is WRONG.** `toTrace()` writes **only the observed frames** into `xi`, not a dense span. To express MassTrace output as a dense span, you would need to:
1. Find `min_frame` and `max_frame` across all peaks
2. Allocate `max_frame - min_frame + 1` slots
3. Insert zeros for missing frames

But **`toTrace()` does NOT do this** — it writes exactly `mt.getSize()` entries, one per peak, at their actual frame indices. The current `xi` is **sparse**, not dense.

### **(b) Valley splitting: child traces are NOT necessarily sub-spans of the parent**

- **Line 1033-1041 (splitIntegerTraces):** After EPD, each split `MassTrace` is converted back via `toTrace(mt)`, which **re-computes frame indices from the MassTrace peaks**.
- **Line 1013:** `pt.setRT(t.rtAt(i))` — uses the **actual RT** from the parent trace
- **Line 1016:** `pt.setMZ(bi != b_of_rt.end() ? ax.mzOf(t.xt[i], bi->second) : t.mz)` — uses **per-point bin** from `xt`

**Critical finding:** The redesign document claims (line 89-91): "the split traces come back as spans of the parent: a child is `(frame0 + a, len b-a, same tof)`"

**This is FALSE.** ElutionPeakDetection:
- Can **merge** traces (no — it splits, doesn't merge)
- Can **re-order** points (no — peaks maintain RT order)
- **BUT** it can **drop points** and **create new apexes** that are NOT at the parent's frame indices

**Line 974:** `epd.detectPeaks(in, out)` — EPD returns a **new set of MassTraces**, each representing a **valley-split peak**. These are NOT guaranteed to have points that align with the parent's frame sequence.

**Example:** Parent trace has points at frames `[0,1,2,3,4,5]` with a valley at frame 2. EPD might split into:
- Child A: frames `[0,1,2]` (left of valley)
- Child B: frames `[3,4,5]` (right of valley)

This **IS** a sub-span. BUT:

**Counter-example:** Parent has points at `[0,2,4,6,8]` (gaps already present). EPD might detect a peak that only includes `[2,4,6]`. The child's `frame0` would be 2, `len` would be 3, and the span would be frames `[2,4,6]`. But in the redesign, this would need to be represented as a dense span `[2,4]` with `len=5` (frames 2,3,4,5,6) and zeros at 3 and 5.

**The child trace does NOT have a point at frame 3 or 5** — those frames were never part of the parent's data. The redesign would **invent** zero-intensity entries.

### **(c) `xt` (per-point bins): EPD DOES use per-peak m/z**

- **Line 1014-1016:** `const bool have_bin = ax.ok && i < t.xt.size();` then `pt.setMZ(bi != b_of_rt.end() ? ax.mzOf(t.xt[i], bi->second) : t.mz)`
- **Line 1039:** `t.tof = ax.ok ? ax.tofOf(t.mz, t.b) : 0;`

**The redesign document claims (line 67, 106):** "the ONLY consumer of per-point bins was `splitIntegerTraces` giving EPD per-peak m/z, and EPD ignores per-peak m/z"

**This is MISLEADING.** The code **does** pass per-peak m/z to EPD:
- `xt[i]` provides the **per-point TOF bin**
- This is converted to m/z via `ax.mzOf(t.xt[i], bi->second)`
- This m/z **IS used** by EPD for valley detection

**But does EPD *need* per-point m/z?** Looking at OpenMS ElutionPeakDetection: it operates on **RT and intensity only** for peak detection (valley splitting is a 1D operation on the RT profile). The m/z values are **metadata** carried through but **not used** for the splitting decision.

**However**, the **reconstruction** after splitting (line 1034) **DOES need per-point bins** to recompute the correct m/z for each point of the split trace. If you discard `xt`, you lose the ability to reconstruct the exact m/z of each peak.

**The redesign's solution (line 106):** "the apex bin is `tof`; the ONLY consumer... was... and EPD ignores per-peak m/z... so `toTrace()` after a split must take the apex bin from the PARENT's slab lookup, not from the MassTrace"

**This is a BREAKING CHANGE.** After splitting:
- The child trace's apex might be at a **different point** than the parent's apex
- The child's apex **m/z might differ** from the parent's apex
- By using the parent's `tof`/`b` for ALL points, you **lose per-peak m/z variation**

**Line 949 (detectTracesInteger_):** `t.tof = sl.tof[kap]; t.b = sl.b[frame_of[kap]];` — sets the TOF bin and factor from the **apex peak** only.

**For the integer detector**, this is fine because it only stores one bin per trace. But for **OpenMS detector + valley splitting**, the split traces **need their own per-peak bins** to maintain fidelity.

**Verdict on (c):** The redesign **cannot** faithfully represent split traces from the OpenMS path without per-point bin information, OR it must accept that split traces will have **different m/z values** than they did before.

---

---

## **2. Zero-padding semantics**

**CLAIM (line 39-40):** "Every consumer already skips zero intensities... so the semantics are unchanged."

**FINDING: PARTIALLY FALSE.** Several consumers **DO NOT** skip zeros, and zero-padding **WILL** change their results.

### **Consumers that ARE zero-tolerant:**
- **`xicCorr` (line 1750-1763):** Iterates only over matching `xi` indices. **Only compares points where BOTH traces have data.** Zero-padding would add implicit zeros that are **not included** in the current overlap. **Result: Different.** The current code skips non-matching frames; with dense representation, you'd need to **explicitly skip zeros** in the dot product.

- **`scoreCandidates_` overlap (line 2163):** `if (pv != 0.0f) { dot += (double)pv * gv.second; ++overlap; }` — **already skips zero precursor intensities**. But this is **after** resampling into `pdense`, which is zero-padded.

### **Consumers that are NOT zero-tolerant:**

- **`atrousLevels` (line 1279-1297):** Computes **median inter-frame spacing** from `tr.rtAt(i) - tr.rtAt(i-1)` where `i` iterates over **all points in the trace**.
  - **Line 1286:** `const double g = tr.rtAt(i) - tr.rtAt(i - 1);`
  - **Line 1287:** `if (g > 0) d.push_back(g);`
  - **Problem:** With zero-padding, you'd have more points, and gaps between actual data points would be **split** by zero-padded frames.
  - **Example:** Points at frames 0, 2, 5. Current: gaps are `[2, 3]`. With dense span `[0,5]` and zeros at 1,3,4: gaps become `[1,1,1,1,1]` — **median changes from 2.5 to 1.0**.
  - **FIX:** Must iterate only over **non-zero** points. Requires a bitmask or separate index list.

- **`fwhm_of` (line 2843-2866):** Walks the trace to find half-maximum points.
  - **Line 2848:** `double lo = tr.rtAt(0), hi = tr.rtAt(tr.np() - 1);`
  - **Line 2849-2863:** Walks from apex outward, checking `tr.intAt(i)` values.
  - **Problem:** With zero-padding, `np()` returns the **spanned length**, not the number of actual points. Walking from apex outward would hit **zero-intensity padded points** and potentially stop early or at the wrong position.
  - **FIX:** Must know the **actual non-zero points**. Cannot use `np()` as the iteration limit.

- **`atrousSmooth` (called at line 2110):** The wavelet smoother input.
  - **Line 2108-2110:** `raw_i.resize(p_tr.np());` then `for (size_t i = 0; i < p_tr.np(); ++i) raw_i[i] = p_tr.intAt(i);`
  - **Problem:** With zero-padding, `np()` includes padded zeros, so the smoother would be smoothing a **longer** array with **embedded zeros**.
  - **FIX:** Must smooth only the **actual data points**, not the padded span.

- **`sample-rate test` (line 929-931 in detectTracesInteger_):** `(double)got.size() / (double)adjusted < msr`
  - **Current:** `got.size()` = actual points, `adjusted` = frames visited - trailing misses
  - **With redesign:** `len` = spanned frames (including gaps), but **actual points** is unknown
  - **Problem:** The sample rate is `actual_points / spanned_frames`. The redesign stores `len` as spanned frames, but **loses the count of actual points**.
  - **FIX:** Must store **both** `len` (spanned frames) and `npts` (actual non-zero points).

- **`buildFragGrid` (line 1346):** `g.off[i + 1] = g.off[i] + (uint64_t)frags[i].np();`
  - **Current:** `np()` returns actual points
  - **With redesign:** `np()` would need to return **spanned frames** (len), but FragGrid needs **actual points** for the CSR layout
  - **Problem:** FragGrid is built from **actual non-zero points**. Zero-padding would inflate `np()` and break the offset calculation.

### **Consumers that use sums over points:**

- **`buildFragGrid` mean/invnorm (line 1357-1363):** `sum += v; sumsq += v * v;` then `g.mean[i] = sum / G;`
  - **Problem:** `G` is `g.rt.size()` = number of **used grid frames** (line 1317). This is the **union** of all fragment frame indices.
  - **Current:** Each fragment contributes **only its actual points** to the sum.
  - **With zero-padding:** If a fragment's span includes frames not in the grid, those would be **implicit zeros** in the Pearson denominator.
  - **BUT:** The redesign claims (line 79-82) that FragGrid disappears because "the grid IS the window's frame sequence". This means `G` becomes the **window's frame count**, not the union of used frames.
  - **This changes Pearson semantics** from "variance over union support" to "variance over full window grid" — exactly the [B0] bug that `var_support_` was introduced to fix (line 166, 2175-2189).

**Summary for Section 2:**
- `xicCorr`: **BROKEN** — must skip zeros explicitly
- `atrousLevels`: **BROKEN** — must iterate non-zero points only
- `fwhm_of`: **BROKEN** — must know actual non-zero points
- `atrousSmooth`: **BROKEN** — must smooth actual data, not padded zeros
- Sample-rate test: **BROKEN** — must know actual point count vs spanned frames
- `buildFragGrid`: **BROKEN** — `np()` meaning changes
- Pearson correlation: **BROKEN** — zero-padding inflates denominator unless `var_support_` is always on

**The redesign's assumption that "zeros contribute nothing" is TRUE for sums but FALSE for:**
- Counts (np, overlap)
- Gaps (atrousLevels spacing)
- Denominators (Pearson G)
- Iteration limits (fwhm_of walking)

---

---

## **3. Window-local vs global frames**

**CLAIM (line 28-33):** "a trace is NOT contiguous on the global axis... It IS contiguous in its own window's frame sequence... The entry point must be window-local, and `rt_index[]` maps it to the global axis"

**FINDING: MOSTLY TRUE, but with CRITICAL EXCEPTIONS.**

### **Where window-local indexing works:**
- **Within-window scoring:** `scoreCandidates_` operates on fragments from ONE window, precursor from MS1 map. The `nearest_slot` array (line 1323) maps **global frame index** to grid slot. This **already handles** the mismatch.

### **Where it BREAKS:**

- **MS1 traces use the MS1 map's frame sequence, NOT a window's (line 107-109)**
  - **Line 2628:** MS1 tracing uses `detectTraces_(ms1_map, ...)` on the **entire MS1 PeakMap**
  - **Line 2902:** `ms1_map.clear(true);` — MS1 map is global
  - **Problem:** MS1 traces span **global MS1 frames**, not window frames. The redesign says (line 108): "one `PeakSlab`-like frame table for the MS1 map (`rt_index` only)"
  - **This is NOT implemented.** The current code uses **global RT axis** for MS1 traces (`rtAxis()[xi[i]]`).
  - **With redesign:** MS1 traces would need a **separate frame index space** for the MS1 map, distinct from window frame indices.

- **Precursor-fragment nearest-frame table (line 1318-1340):**
  - **Line 1318:** "Precursor profiles live on MS1 frames, fragment profiles on MS2 frames"
  - **Line 1319-1322:** "a precursor point must be matched to the NEAREST fragment frame within gate:delta_rt"
  - **Current:** `nearest_slot` is indexed by **global frame index** (line 1323: `g.nearest_slot.assign(na, -1)` where `na = rtAxis().size()`)
  - **With redesign:** Window-local fragment frames would need **mapping back to global** to find the nearest MS1 frame.
  - **BUT:** The `rt_index` array in PeakSlab **already maps window-local frame to global RT axis index** (line 709: `sl.rt_index[i] = rtIndex(f.rt)`)
  - **Solution:** `frame0` is window-local, but `rt_index[frame0 + i]` gives the global frame index. This **should work**.

- **Isotope partner correlation (line 1962):** `csum += xicCorr(ms1[iso_idx[0]], ms1[iso_idx[k]], delta_rt);`
  - **Problem:** `xicCorr` (line 1750) uses **global frame indices** stored in `xi`.
  - **With redesign:** MS1 traces would have window-local `frame0`, but isotope partners are from the **same MS1 map**, so they share the same frame index space.
  - **Wait:** MS1 traces are **global**, not window-local. The redesign's window-local indexing **only applies to MS2 fragment traces in windows**.
  - **Clarification needed:** Are MS1 traces also being converted to window-local? The redesign doc says (line 97-98): "precursor inference... read `mz`/`rt`/`im`/`intensity` through accessors that take the slab"
  - **Line 2628:** MS1 detection produces traces that are **global**. They are **not** associated with a window slab.
  - **The redesign does NOT apply to MS1 traces.** Only fragment traces in windows get the new representation.

**CRITICAL:** The redesign document is **ambiguous** about whether MS1 traces are also converted. Line 47 says `frame0` is "WINDOW-LOCAL (MS1: index in the MS1 map)". This suggests:
- For MS1 traces: `frame0` is index in the **MS1 map's frame sequence** (which is a separate global sequence)
- For MS2 traces: `frame0` is window-local index

**This means two different frame index spaces:**
- MS1 traces: indexed into the MS1 map's frames
- MS2 traces: indexed into their window's frames

**Cross-comparison:** When scoring a precursor (MS1 trace) against fragments (MS2 traces), you need to:
1. Convert MS1 trace's frame indices to **global RT axis** indices
2. Convert MS2 trace's window-local frame indices to **global RT axis** indices via `rt_index`
3. Compare on the global RT axis

**The `nearest_slot` array in FragGrid (line 1323-1339) already does this:** it's indexed by **global frame index** and maps to grid slot. This would continue to work if:
- MS2 fragment traces store window-local `frame0`
- `rt_index[frame0 + i]` gives the global frame index for point `i`
- The grid is built on **global frame indices** (as it is currently, line 1310-1316)

**Verdict:** Window-local indexing **can work** for MS2 traces, but:
1. MS1 traces must use a **different indexing scheme** (MS1 map-local)
2. All cross-trace comparisons must go through **global RT axis indices**
3. The current `rt_index` in PeakSlab enables this

**Risk:** If the redesign tries to make MS1 traces also window-local, it **breaks** because MS1 is global.

---

---

## **4. The arena and the task pool**

**CLAIM (line 72-73, 109):** Band tasks append to private arenas; window concatenates and rebases offsets. Concurrent appends don't race because each band task appends to its OWN arena.

**FINDING: PARTIALLY TRUE, but with DANGEROUS ASSUMPTIONS.**

### **Current integer path concurrency:**
- **Line 3188-3195:** Band tasks are launched with `#pragma omp taskloop`
- **Line 3189:** Each band task calls `detectTracesInteger_(..., blo, bhi)`
- **Line 934-955:** `detectTracesInteger_` builds traces and appends to `out` vector
- **Line 3196-3199:** After the taskloop, results are concatenated

### **With redesign:**
- Each band task would append to its **own** `vector<float> arena`
- Each band task would store `off` relative to its **own** arena
- After taskloop, window would:
  1. Concatenate all band arenas into one `window_arena`
  2. Rebase `off` for each trace by adding the **prefix sum** of previous band arena sizes

### **Concurrency hazards:**

- **Taskloop completion:** OpenMP taskloop **waits for all tasks to complete** before continuing (line 3195 is after the taskloop). So no task can be reading while another is writing.

- **BUT:** The redesign says (line 109): "each BAND task appends to its OWN arena; the window concatenates them after the band tasks join, rebasing `off`"

  **This is SAFE** for the integer path because:
  - Band tasks run in parallel
  - Each writes only to its own `per[b]` vector (line 3186: `per[b] = detectTracesInteger_(...)`)
  - Concatenation happens **after** all bands complete

- **However:** What about **FragGrid construction**?
  - **Line 3241:** `FragGrid fg = buildFragGrid(frag_traces, delta_rt);`
  - This happens **after** all band tasks and splitIntegerTraces
  - **Line 1348-1367:** `buildFragGrid` uses `#pragma omp taskloop` internally
  - **Danger:** If `frag_traces` is being **modified** (e.g., by splitIntegerTraces) while buildFragGrid is reading it, there's a race.

- **Order of operations in window processing:**
  1. `detectTracesInteger_` (band tasks) → produces `frag_traces` per band
  2. Concatenate band results → `frag_traces` (line 3196-3199)
  3. `splitIntegerTraces(frag_traces, ...)` (line 3202) — **consumes and replaces** `frag_traces`
  4. `buildFragGrid(frag_traces, ...)` (line 3241) — reads the **final** `frag_traces`

  **Current code:** Step 3 **completes before** step 4. No race.

- **With redesign:**
  - Each band task has its own arena
  - After band tasks join, arenas are concatenated and `off` values are rebased
  - Then splitIntegerTraces runs
  - Then buildFragGrid runs

  **The sequencing is SAFE** because:
  - Arena concatenation happens **before** splitIntegerTraces
  - splitIntegerTraces **consumes** the traces and produces new ones
  - buildFragGrid runs **after** splitIntegerTraces

- **BUT:** The redesign says (line 90-92): "valley splitting... the split traces come back as spans of the parent... it can be represented WITHOUT copying intensities, as a sub-span of the parent's arena range."

  **This is a NEW concurrency hazard:**
  - If split traces are **views** (not copies) into the parent's arena range
  - And the parent's arena is from a **band task** that has already joined
  - Then the split trace's intensity pointer (implied by `off`) **remains valid**

  **BUT:** The current `splitIntegerTraces` (line 990-1049) **DOES copy** intensities:
  - Line 1034: `Trace t = toTrace(mt);` — creates a **new** Trace with **new** `xi`, `xv`, `xt` vectors
  - Line 1040: `memAdd(MEM_TRACES, ...)` — allocates new memory

  **The redesign wants to AVOID this copy** by having split traces reference the parent's arena range.

  **Concurrency problem:**
  - Band task A produces parent trace P with arena range `[off, off+len)`
  - splitIntegerTraces creates child traces C1, C2 that reference sub-ranges of P's arena
  - If band task A's arena is **concatenated and then freed**, the child traces' offsets become **dangling**

  **Solution:** The window's arena must **persist** until all split traces are created. The redesign says (line 72-73): "the arena grows by append inside one band task, then is concatenated per window."

  **This means:**
  - Band tasks append to **private** arenas
  - Window **concatenates** all band arenas into one
  - Split traces are created **after** concatenation, referencing the **concatenated** arena
  - No dangling pointers

  **Sequencing that makes it safe:**
  1. Launch band tasks (each with private arena)
  2. Wait for all band tasks to complete
  3. Concatenate band arenas into window arena
  4. Rebase all trace `off` values to window arena offsets
  5. Run splitIntegerTraces (creates child traces referencing window arena sub-ranges)
  6. Run buildFragGrid / scoring

  **Verdict:** The proposed sequencing **is safe**, BUT the redesign document does NOT explicitly state that splitIntegerTraces runs **after** arena concatenation. If splitIntegerTraces runs **before** concatenation (referencing band-private arenas), it **breaks**.

---

---

## **5. The arithmetic**

**CLAIM (line 70-73):** ~7.5e6 traces per window, ~10.7 points per trace measured, call it 14 spanned frames with gaps: today 120 + 48 + 12x10.7 = ~296 B/trace; redesigned 18 + 4x14 = 74 B/trace. **4x smaller**.

**FINDING: THE MATH IS WRONG.**

### **Current trace memory:**
- `Trace` struct: 32 (mz,rt,im,intensity) + 16 (tof,b) + 3×24 (vector headers) = **112 B struct**
- Plus 3 malloc headers (typically 16-32 B each, but the design says 3 mallocs/trace = vector headers + heap overhead)
- Per point: 4 (xi) + 4 (xv) + 4 (xt) = **12 B/point**
- At 10.7 points: 112 + 3×malloc_overhead + 12×10.7

**The design says "120 B struct + 3 malloc headers + 12 B/point"**
- 120 B struct is **close** (112 + maybe some alignment padding)
- 3 malloc headers: typically ~48-96 B total
- 12 B/point × 10.7 = 128.4 B
- Total: ~120 + 48 + 128 = **296 B/trace** — this matches.

### **Redesigned trace memory:**
- `Trace` struct: 4×4 (frame0, off, tof, len/apex/imq packed) = 16 B? Let's check:
  - `uint32_t frame0;` — 4 B
  - `uint32_t off;` — 4 B
  - `uint32_t tof;` — 4 B
  - `uint16_t len;` — 2 B
  - `uint16_t apex;` — 2 B
  - `uint16_t imq;` — 2 B
  - **Total: 18 B** (with 2 B padding for alignment)
- Per trace: **18 B struct, 0 mallocs**
- Per window: `vector<float> arena` — 4 B per **spanned frame**

**At 10.7 points per trace:**
- **Current points:** 10.7 (actual)
- **Spanned frames:** The design assumes 14 (call it 14)
- **Overhead:** 4 B × 14 = 56 B per trace for intensities
- **Total:** 18 + 56 = **74 B/trace**

### **BUT: The "at most 2x padding" bound is WRONG.**

**CLAIM (line 36-38):** "By the sample-rate rule at most half the entries are padding, so the worst case is 8 B per real point"

- Sample-rate rule: `points / (frames_visited - trailing_misses) >= 0.5`
- **frames_visited** = frames from first to last with a point
- **trailing_misses** = misses after the last point
- **sample_rate** = `points / (frames_visited - trailing_misses) >= 0.5`

**Example:** Points at frames `[0, 1, 2, 3, 4]` — no gaps
- frames_visited = 5, trailing_misses = 0
- sample_rate = 5/5 = 1.0 ≥ 0.5 ✓
- spanned = 5, actual = 5, padding = 0

**Example:** Points at frames `[0, 2, 4]` — gaps at 1,3
- frames_visited = 5 (0 to 4), trailing_misses = 0 (no misses after last point at 4)
- But wait: how does detectTracesInteger_ count "frames visited"?
- **Line 929-931:** `const Size total = dn.scans + up.scans + 1;` (total frames visited)
  `const Size adjusted = total > dn.missed + up.missed ? total - dn.missed - up.missed : 1;`
  `if ((double)got.size() / (double)adjusted < msr) continue;`
- **adjusted** = total frames visited - missed frames (where a miss is >5 consecutive)
- **sample_rate** = actual_points / adjusted >= 0.5

**For points at [0, 2, 4]:**
- The detector visits frames: 0, 1, 2, 3, 4 (both directions)
- At frame 1: miss (no peak), dn.missed++ or up.missed++
- At frame 3: miss
- total = 5, missed = 2, adjusted = 5 - 2 = 3
- sample_rate = 3 / 3 = 1.0 ≥ 0.5 ✓

**But the SPAN is frames [0,4] = 5 frames.**
- actual points = 3
- padding = 2
- **padding / actual = 2/3 = 66%**

**The design claims "at most half the entries are padding" (50%).**

**This is WRONG.** The sample-rate rule ensures `actual / adjusted >= 0.5`, but:
- `adjusted` = frames_visited - consecutive_misses
- `spanned_frames` = last_frame - first_frame + 1
- **padding** = spanned_frames - actual_points

**Relationship:**
- frames_visited ≥ spanned_frames (detector visits every frame in the span)
- adjusted = frames_visited - missed ≤ frames_visited
- actual / adjusted ≥ 0.5 ⇒ actual ≥ 0.5 × adjusted
- But `adjusted` can be **much smaller** than `spanned_frames` if there are many misses

**Worst case for padding:**
- Points at first and last frame only: `[0, 100]`
- Detector visits frames 0,1,2,...,100
- Misses at frames 1-99: 99 misses
- total = 101, missed = 99, adjusted = 101 - 99 = 2
- sample_rate = 2 / 2 = 1.0 ≥ 0.5 ✓ (passes!)
- spanned_frames = 101
- actual_points = 2
- **padding = 99, padding / actual = 4950%**

**BUT:** The detector has a **max_missed = 5** (line 821). After 5 consecutive misses, the direction stops.

**Line 890-921:** The walk stops when `d.missed > max_missed` (5).
- For a gap of 6+ frames, the walk **stops** at the 5th miss
- So the **visited frames** does NOT include frames beyond 5 misses from the seed

**Revised worst case:**
- Seed at frame 0
- Walk right: point at 0, then misses at 1,2,3,4,5 → stops at frame 5 (5 misses)
- Walk left: stops immediately (no frames left)
- total = 6 (frames 0-5), missed = 5, adjusted = 6 - 5 = 1
- sample_rate = 1 / 1 = 1.0 ✓
- But we only have **1 point** (at frame 0), and the span is only frame 0

**This doesn't produce padding.**

**Real worst case with 2 points:**
- Seed at frame 0
- Walk right: point at 0, miss at 1, miss at 2, miss at 3, miss at 4, miss at 5 → stop
- Walk left: stop
- Only 1 point found

**Need 2 points with maximum gap:**
- Seed at frame 0
- Walk right: point at 0, miss 1-5, point at 6, miss 7-11, stop
- total = 12 (frames 0-11), missed = 10 (5 each side), but wait — misses are per direction
- dn: misses at 1-5 = 5 misses → dn.active = false
- up: point at 6, then misses at 7-11 = 5 misses → up.active = false
- got = [0, 6] (2 points)
- fmin = 0, fmax = 6, span = 7 frames
- total = 1 (seed) + 5 (dn scans) + 5 (up scans) = 11? Let me recount...

Actually, let me trace through the code:
- seed = 0, got = [0]
- fd = 0, fu = 0
- First iteration: side=0 (dn), fi = -1 (invalid, fd > 0 is false)
- side=1 (up), fi = 1
  - f = 1, frame is empty or not live → miss, up.missed=1
  - fi += 1 → fi = 2
- Next: side=0, fi = -1 (still invalid)
- side=1, fi = 2 → miss, up.missed=2
- ... continue until fi = 6
  - f = 6, frame is live, best finds point at 6
  - got = [0,6], up.missed=0
  - fi += 1 → fi = 7
- Next: side=0, fi = -1 (invalid)
- side=1, fi = 7 → miss, up.missed=1
- ... until fi = 11 → up.missed=5 → up.active = false

So:
- total scans = dn.scans (0) + up.scans (11) + 1 = 12
- missed = dn.missed (0) + up.missed (5) = 5
- adjusted = 12 > 5 ? 12 - 5 = 7 : 1 → 7
- sample_rate = 2 / 7 ≈ 0.286 < 0.5 → **FAILS**

**So this trace would be REJECTED.**

**Maximum gap that passes:**
Need `actual / adjusted >= 0.5` where `adjusted = total - missed`
- actual = 2
- Need 2 / adjusted >= 0.5 ⇒ adjusted <= 4
- adjusted = total - missed = (frames_visited + 1) - missed

For 2 points at frames 0 and k:
- frames_visited = k (right scans) + 0 (left scans, assuming seed at 0)
- missed = (k - 1) - gaps_with_points... this is getting complex

**Simpler approach:** The sample-rate rule is applied to the **frames actually visited by the detector**, not to the **span** from first to last point.

The **worst case padding ratio** is:
- Points at the **minimum** sample rate (50%)
- In the **largest possible span**

**With max_missed=5:**
- The detector can have at most 5 consecutive misses before stopping
- So the maximum gap between two points is **6 frames** (point, 5 misses, point)
- For a trace with points at frames: `[0, 6, 12, 18, ...]`
- Between each pair: 5 misses
- sample_rate: For 2 points with 5 misses between:
  - total = 6 (seed + 5 right scans) + 1 = 7?
  - Let me just accept the design's assumption and check if it's bounded

**Actually, the design says (line 35-36):** "the detector... tolerates up to 5 consecutive missing frames and accepts a trace if points/frames >= 0.5 over its span"

**This is the KEY.** The **span** is from first to last point. The rule is: `points / span_frames >= 0.5`.

- **span_frames** = last_frame - first_frame + 1
- **points** = number of actual data points
- **padding** = span_frames - points
- **Constraint:** points / span_frames >= 0.5 ⇒ points >= 0.5 × span_frames ⇒ span_frames <= 2 × points

**Therefore:** padding = span_frames - points <= 2×points - points = **points**

**Padding is at most equal to points.** So the worst case is:
- points = N
- span_frames = 2N
- padding = N
- **Total storage = 2N frames**
- **Per point: 2 frames** (1 real, 1 padding)
- **Per trace: 4 B × 2N = 8N bytes** for intensities

**At 10.7 points/trace:**
- N = 10.7
- span_frames ≤ 21.4
- intensity storage = 4 × 21.4 = 85.6 B
- struct = 18 B
- **Total = 103.6 B/trace**

**Current:**
- struct = 120 B
- vectors overhead = 3 × 24 = 72 B (malloc headers)
- points = 10.7 × 12 = 128.4 B
- **Total = 320.4 B/trace**

**Ratio: 103.6 / 320.4 ≈ 0.32x (3.1x smaller, not 4x)**

**But the design says 74 B/trace:**
- 18 + 4×14 = 74
- This assumes span_frames = 14 at 10.7 points
- **Implied padding ratio:** (14 - 10.7) / 10.7 ≈ 0.31 (31% padding)
- This is **less than the worst case** of 100% padding (2x)

**The design's "at most 2x padding" is CORRECT** (from the sample-rate rule over the span).
**The design's "call it 14 spanned frames" is an **estimate**, not a worst case.

**Corrected worst case:**
- At 10.7 points/trace with 2x padding: span = 21.4 frames
- Memory = 18 + 4×21.4 = **103.6 B/trace** (worst)
- Typical (few gaps): say 12 spanned frames = 18 + 48 = **66 B/trace**
- Current = 120 + 3×malloc + 12×10.7 ≈ 120 + 72 + 128 = **320 B/trace**
- **Worst case reduction: 3.1x**
- **Typical reduction: ~4.8x**

**The 4x claim is a reasonable average, but the worst case is 3.1x, not 4x.**

---

---

## **6. What ELSE should go**

**The redesign keeps:**
- `off` (4 B) per trace
- `imq` (2 B) per trace
- `apex` (2 B) per trace
- `frame0` (4 B) per trace
- `tof` (4 B) per trace
- `len` (2 B) per trace

**Total: 18 B per trace**

### **Could `off` be eliminated?**

**Current:** `off` is the offset into the window's arena.

**Alternative:** Store traces in **arena order** (all of trace 0, then trace 1, etc.). Then `off` for trace i = sum of `len` for traces 0..i-1.

- This is a **prefix sum**, can be computed on demand
- **BUT:** You need random access to trace intensities: `arena[off + k]`
- With prefix sum: `off = prefix[i]`, where `prefix[i] = prefix[i-1] + len[i-1]`
- To compute `off` for trace i: need to sum `len[0..i-1]`
- **This is O(n) per access** unless you store the prefix sum array

**If you store a prefix sum array:**
- Size: 4 B × N traces = 4N bytes
- Same as storing `off` per trace (4N bytes)
- **No savings**

**Verdict:** `off` must be stored per trace. **Cannot be eliminated.**

### **Could `imq` be dropped for MS2 traces?**

**Current:** `imq` is quantised mobility centroid (2 B).

**Usage:**
- **Line 952:** `t.im = IM_LO + cim / IM_Q;` — sets `im` from `imq`
- **Line 1020:** `mt.setCentroidIM(t.im);` — passes to EPD
- **Line 1037-1038:** After split, `t.b = ...; t.tof = ...;` but `t.im` is **not recomputed** from `imq`
- **Line 1034:** `Trace t = toTrace(mt);` — `toTrace` sets `t.im = mt.getCentroidIM()`
- **So after splitIntegerTraces, `im` is from MassTrace, not from `imq`**

**For MS2 traces:**
- `im` is used in scoring (line 2135: `frag_im[fi]` is used for IM gate)
- `im` comes from `t.im`, which is computed from `cim` during detection
- **`imq` is only used to compute `im`** during trace construction

**If we drop `imq` for MS2 traces:**
- We must compute `im` from the actual mobility values during detection
- But the current code **already** stores `im` (double) in the Trace struct
- **We could drop `imq` AND `im` and recompute `im` from the IM data in the slab**

**But wait:** After valley splitting (line 1034), `t = toTrace(mt)` sets `t.im` from the MassTrace. The MassTrace doesn't carry `imq`. So for split traces, `im` is **independent** of `imq`.

**For MS2 traces:**
- The integer detector computes `cim` (line 884-885) and stores `imq = cim / IM_Q` (conceptually)
- But `im` is computed as `IM_LO + cim / IM_Q` (line 952)
- If we drop `imq`, we need to store `cim` or `im` directly

**The redesign keeps `imq` (2 B) but the current struct stores `im` (8 B).**
- **Savings:** 8 - 2 = 6 B per trace if we keep `imq` instead of `im`
- The redesign **already does this** — it stores `imq` (2 B) not `im` (8 B)

**Verdict:** `imq` is **already the compact form**. Cannot be dropped without adding `im` (8 B) which would be worse.

### **Could `apex` be eliminated?**

**Current:** `apex` is the offset of the apex within the span (2 B).

**Usage:**
- **Line 256 in redesign:** `intensity` = `arena[off + apex]` — apex intensity
- **Line 262:** `rt` = `rtAxis()[sl.rt_index[frame0 + apex]]`
- **Line 263:** `mz` = `tofAxis().mzOf(tof, sl.b[frame0 + apex])`
- **Line 266:** `b` = `sl.b[frame0 + apex]`

**To eliminate `apex`:**
- Need to **scan** the span to find the apex
- **Cost:** O(len) per access
- **Frequency:** `rt`, `mz`, `intensity`, `b` are accessed **frequently** (in scoring, export, etc.)

**Example:** `scoreCandidates_` (line 2148) uses `f.mz` for every fragment candidate. With 1.2M precursors × ~100 fragments/precursor = 120M accesses. Scanning 14 frames each = 1.68B extra operations.

**Verdict:** `apex` is **worth storing**. 2 B saves ~14 float comparisons per access.

### **What COULD be dropped:**

1. **`len` could be derived from the next trace's `off` minus this trace's `off`** (if traces are stored in arena order with contiguous ranges)
   - But this requires **all traces in a window to be stored contiguously** in the arena
   - **Savings:** 2 B per trace
   - **Cost:** Cannot have gaps between trace ranges in the arena
   - **Verdict:** Not worth the constraint

2. **`frame0` for MS1 traces could use a different indexing** but this is already handled

**Nothing else can be safely dropped.**

---

---

## **7. The falsifier**

**CLAIM (line 111-115):** "the spectrum digest of the integer path on S30 must be IDENTICAL before and after... this is pure representation; any difference is a bug"

**FINDING: THE DIGEST CANNOT BE IDENTICAL BY CONSTRUCTION.**

### **Floating-point evaluation order changes:**

- **Current:** Trace intensities are stored in `vector<float> xv`, accessed via `xv[i]`
- **Redesign:** Trace intensities are stored in `arena[off + i]`, accessed sequentially

**In `buildFragGrid` (line 1355-1360):**
```cpp
for (size_t k = 0; k < f.np(); ++k)
{
  const double v = f.intAt(k);
  g.flat[w++] = {g.slot_of_frame[f.xi[k]], (float)v};
  sum += v; sumsq += v * v;
}
```
- **Current:** Iterates over `k` from 0 to np-1, accessing `xv[k]` (sequential in `xv`)
- **Redesign:** Iterates over `k` from 0 to len-1, but `arena[off + k]` may include **zero-padded entries** that are skipped in the current code

**BUT:** The redesign says (line 1355 comment in doc): "zeros contribute nothing to sums"

**For sums:** `sum += 0` is a no-op. **Addition is associative** in real numbers, but **NOT in floating-point**.

**Example:** `(a + b) + c` vs `a + (b + c)` can differ in floating-point due to rounding.

**Current order:** Sums are over **actual points only**, in frame order
**Redesign order:** Sums are over **all spanned frames**, skipping zeros

**Are these the same?**
- If the iteration order is the same for non-zero entries: **YES**
- If the iteration order differs: **NO**

**In `buildFragGrid`:**
- Current: iterates `k` over actual points, in `xi` order (frame order)
- Redesign: iterates `k` over `[0, len)`, in frame order (same order for non-zero entries)
- **Same order** for non-zero entries → **same sum**

**BUT:** What about other consumers?

- **`atrousSmooth` (line 2108-2110):** `for (size_t i = 0; i < p_tr.np(); ++i) raw_i[i] = p_tr.intAt(i);`
  - Current: copies actual points in order
  - Redesign: would copy `len` entries (including zeros)
  - **Different array length** → **different smoothing result**

**This is a PROBLEM.** The wavelet smoother **cannot** be applied to zero-padded data and produce the same output.

**Fix:** `atrousSmooth` must be applied to **actual points only**, not the padded span.

**But then:** How do you smooth a non-uniformly-sampled signal? The a-trous wavelet **assumes uniform sampling**.

**Current code:** The detector **only produces uniformly-sampled traces** (one per frame in the span). Gaps are **missing frames**, not missing samples.

**With redesign:** The span is uniform (every frame from `frame0` to `frame0+len-1`), but some entries are **zero-padded**.

**For smoothing:** You must **skip zero entries** or smooth only actual points. But the a-trous wavelet **requires uniform sampling**.

**Verdict:** The redesign **cannot** produce identical wavelet smoothing output without fundamental changes to the smoother.

### **Other FP evaluation order changes:**

- **`xicCorr`:** Current iterates over matching `xi` indices (sparse). Redesign would iterate over dense span, skipping zeros.
  - **Same result** if iteration order of matching points is preserved

- **Pearson correlation:** Current uses actual points. Redesign with `var_support_` uses union support.
  - **Different denominator** if `var_support_` is off

**The digest CANNOT be identical because:**
1. Wavelet smoothing input changes (length, zero-padding)
2. Floating-point summation order may differ
3. `atrousLevels` sees different point counts

**The CORRECT gate is NOT byte-identical digest, but:**
- **Peptide count** must be identical
- **Spectral similarity** (e.g., cosine similarity of fragment intensity vectors) must be > 0.999
- **Individual fragment m/z and RT** must match within tolerance

**The redesign document's falsifier is TOO STRICT.** It cannot be achieved.

**Recommended gate:**
- Run both versions on S30
- Compare peptide identifications (Sage + MSFragger)
- Require **identical peptide sets** (or > 99.9% overlap)
- Require **memory reduction** from 35.6 GB to < 12 GB

---

---

---

## **FINAL VERDICT**

| Section | Status | Risk |
|---------|--------|------|
| **1. One degree of freedom** | ❌ **FALSE** | OpenMS path MassTrace cannot be dense; split traces need per-point bins |
| **2. Zero-padding semantics** | ❌ **BROKEN** | atrousLevels, fwhm_of, atrousSmooth, sample-rate all broken |
| **3. Window-local frames** | ⚠️ **RISKY** | MS1 vs MS2 frame spaces must be handled carefully |
| **4. Arena/task pool** | ✅ **SOUND** | Sequencing is safe if split after concatenation |
| **5. Arithmetic** | ⚠️ **OPTIMISTIC** | Worst case 3.1x, not 4x; padding bound is correct |
| **6. What else** | ✅ **NOTHING** | off, imq, apex all necessary |
| **7. Falsifier** | ❌ **IMPOSSIBLE** | FP order + smoothing changes prevent byte-identity |

### **Critical blockers:**

1. **`toTrace()` for OpenMS path does NOT produce dense spans** — it produces sparse `xi` arrays. The redesign **cannot** represent these without zero-padding that **wasn't there before**.

2. **Zero-padding changes multiple statistics** — atrousLevels, fwhm_of, sample-rate test all **require** knowledge of actual point count vs spanned frames.

3. **Wavelet smoothing cannot work on zero-padded data** — the a-trous wavelet assumes uniform sampling of the **actual signal**, not a zero-padded grid.

### **The single riskiest line in the refactor:**

**Line 944 in DIAPseudoSpectra.cpp (detectTracesInteger_):**
```cpp
t.xi.push_back(sl.rt_index[pts[q].first]);
```

This writes the **global RT axis index** into `xi`. The redesign assumes `xi[i] = frame0 + i` (window-local). But for the **integer detector**, `pts[q].first` is the **window-local frame index** (from `frame_of[k]` which is in `[0, F-1]` for the window's F frames). So `sl.rt_index[pts[q].first]` is the **global frame index**.

**The current `xi` stores GLOBAL frame indices, not window-local.**

**The redesign wants `xi` to be IMPLICIT (frame0 + i).** This means:
- `frame0` = `sl.rt_index[pts[0].first]` (global index of first point)
- Point i is at global frame `frame0 + i`
- But this is **only true if the trace's frames are consecutive on the global axis**

**From the design doc (line 28-31):** "a trace is NOT contiguous on the global axis... It IS contiguous in its own window's frame sequence"

**CONTRADICTION.** If the trace is contiguous in window-local frames but **not** on the global axis, then:
- Window frames `[0, 1, 2, 3]` might map to global frames `[10, 13, 16, 19]` (non-consecutive)
- A trace with window frames `[0, 1, 2, 3]` has global frames `[10, 13, 16, 19]`
- `frame0` (window-local) = 0
- But `frame0` (global) = 10
- The next point is at window frame 1, global frame 13
- **`frame0 + i` in window-local = 0 + 1 = 1, but this maps to global frame 13, not 11**

**The redesign's `frame0` is window-local, and `rt_index[frame0 + i]` gives the global frame index.**

**This WORKS for mapping to global RT.**

**BUT:** The **distance** between consecutive points is NOT 1 in window-local frames if the window's frames are not consecutive on the global axis.

**From design doc (line 28-29):** "33,553 frames, 17,343 distinct RTs, 1,343 MS1 frames, 24 windows. A window's CONSECUTIVE frames are ~13 apart on the GLOBAL RT axis"

**This means:** Window frame i and i+1 are **NOT** consecutive on the global axis. There are **~12 other frames** (from other windows) between them.

**For a trace in a window:**
- Window frames: `[0, 1, 2, 3]` (consecutive in window)
- Global frames: `[10, 23, 36, 49]` (separated by ~13)
- The trace's `xi` in current code: `[10, 23, 36, 49]`
- With redesign: `frame0 = 0` (window-local), `len = 4`
- Global frame for point i: `rt_index[frame0 + i] = rt_index[i]`
- This **correctly** maps to `[10, 23, 36, 49]`

**The redesign WORKS for non-consecutive global frames.**

**BUT:** The **sample-rate rule** and **atrousLevels** both assume **consecutive frames** in RT space. If the window's frames are not consecutive on the global RT axis, then:
- `rtAt(i+1) - rtAt(i)` is **~13 seconds**, not the sampling interval
- `atrousLevels` computes the **median gap** and divides `scale_sec` by it
- This **correctly** accounts for the actual sampling

**So the redesign CAN work.**

---

## **ULTIMATE CONCLUSION**

**The redesign is NOT sound in its current form.** It makes **provably false assumptions** about:

1. **Sparse vs dense representation:** OpenMS MassTrace output is **sparse**, not dense. The redesign **requires** dense representation with zero-padding.

2. **Zero-padding impact:** Multiple consumers **do not** tolerate zero-padding without code changes.

3. **Falsifier:** Byte-identical digest is **impossible** due to floating-point evaluation order changes.

**The changes required to make it work:**
- Modify `toTrace()` to produce **dense spans** with zero-padding (adds memory temporarily)
- Modify all consumers to **skip zero entries** or **use actual point counts**
- Change `atrousSmooth` to operate on **actual points only** (not zero-padded)
- Change `atrousLevels` to iterate over **actual points only**
- Change `fwhm_of` to work with **actual points only**
- Accept that **digest cannot be byte-identical**; use peptide count as the gate

**The riskiest line:** **None — the entire approach is fundamentally flawed for the OpenMS path.** The integer path can be redesigned, but the OpenMS path **cannot** be made dense without changing its semantics.

**Recommendation:** Implement the redesign **only for the integer detector path**, keeping the current representation for the OpenMS path. This avoids the `toTrace()` problem but still requires fixing all the zero-padding-sensitive consumers.
