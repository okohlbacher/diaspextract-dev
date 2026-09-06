## HOSTILE REVIEW: DAY'S WORK ON speXtractor (2026-09-04)

---

## 1. **Is making the integer detector the default defensible on this evidence?**

**VERDICT: NO. The rule was BENT, not met. The default was not even changed.**

**The honest evidence:**
- **Sage on dataset D:** integer **LOSES 1.3%** (12,642 → 12,475), **NOT "about 1% in either direction"** — it is a clear regression on the primary engine
- **MSFragger on dataset D:** +2.1% (12,073 → 12,322) — improvement, but **not sufficient to offset Sage loss under the both-engines rule**
- **8% symmetric churn** on ~12.5k peptides is **material**, not "about 1%"
- **dataset A has NOT been re-run since the span representation landed** — the only dataset A integer data is from commit `4a22ad7` (pre-span), which showed +0.3% Sage, 140 vs 230 GB. The span refactor changed semantics; that number is stale.

**Project rule violation:**
- Rule: both engines + entrapment + **a second file**
- Met: Sage and MSFragger on dataset D only
- **NOT met:** dataset A not re-run post-span; entrapment numbers not provided for integer arm

**The default was NOT changed:**
- `src/DIAPseudoSpectra.cpp:1485`: `registerStringOption_("trace:detector", "<mode>", "openms", ...)` — **default is still "openms"**
- `src/DIAPseudoSpectra.cpp:3115`: `bool integer_detector = (getStringOption_("trace:detector") == "integer");` — string comparison, defaults false
- **Commit `e3c6eb4` claimed to "Make trace:detector=integer the default" but the registration was never updated.** The commit only added the fallback logic and the `spx:detector` metadata.

**Fallback hazard:**
- Users with `.d` files → **integer detector**
- Users with `.mzML` files → **openms detector** (fallback)
- **Same command, different output based on input type.** The warning at `src/DIAPseudoSpectra.cpp:3137-3140` exists but does not prevent silent algorithmic divergence.

**Conclusion:** The default change is **overstated** (never implemented), the evidence is **incomplete** (dataset A missing), and the rule is **bent**.

---

---

## 2. **What in today's claims is unverified or overstated?**

### **UNVERIFIED**

| Claim | Status | Location |
|---|---|---|
| Prep compaction | **Committed but NOT verified** | Commit `7d6e56f` ("built and queued but NOT yet verified"); `INTEGER-MEMORY-PLAN.md:59-70` |
| Ledger correctness | **Multiple known defects** | `INTEGER-MEMORY-PLAN.md:62-63,92-94,127` |
| dataset A post-span results | **Not measured** | User's table only shows pre-span dataset A (integer 11,121 vs openms 11,084) |

**Ledger defects in detail:**
- `MEM_TRACES`: cumulative over run, not peak — `src/DIAPseudoSpectra.cpp:3339` adds, never subtracts (`INTEGER-MEMORY-PLAN.md:92-93`)
- `MEM_PREP`: guard at `src/DIAPseudoSpectra.cpp:3211` lives through split, grid, scoring — **wrong scope** (`INTEGER-MEMORY-PLAN.md:62-63`)
- `MEM_EPD_LIST`: phantom — list is per-trace, dies each iteration, but was charged chunk-wide (`INTEGER-MEMORY-PLAN.md:96-99`)
- `memAdd`/`memSub`: **no release mechanism** in `MemGuard` (`src/DIAPseudoSpectra.cpp:741-747`)

### **OVERSTATED**

| Claim | Reality | Location |
|---|---|---|
| "Span gate PASSED on both detectors: digest-identical" | Only **pre-span vs post-span** on same detector, **NOT integer vs OpenMS** | Commit `bbb2121`, `docs/TRACE-STRUCT-REDESIGN.md:230-235 |
| "68.6 → 27.9 GB" traces ledger drop | **Partially stale** — old ledger had cumulative traces line | `docs/TRACE-STRUCT-REDESIGN.md:234-235` |
| "pure representation change" | **Not pure** — changes centroid RT→apex RT, double IM→requantized, per-child TOF→parent TOF | `docs/reviews/trace-struct-2026-09-04/codex.md:217-224` |
| "9 GB" trace memory estimate | **Unsupported** — arithmetic error, ignored allocator headers | `docs/reviews/trace-struct-2026-09-04/codex.md:182-185` |

### **MemGuard misuse:**
- `src/DIAPseudoSpectra.cpp:3339`: `MemGuard g_tr(MEM_TRACES, ...)` — added inside critical section, **never released**
- `src/DIAPseudoSpectra.cpp:901`: `MemGuard g_vis(MEM_VISITED, vbytes(visited))` — correct, but visited **redundant with seed list** (`INTEGER-MEMORY-ANALYSIS.md:38`)

---

---

## 3. **Correctness review of the span representation**

### **✗ Dangling `st` pointers after store reallocation**

- `struct Trace` line 255: `const struct TraceStore* st = nullptr`
- `TraceStore::absorb()` lines 297-306: **reallocates** `inten` and `bins` via `vector::insert`
- Sequence:
  1. `detectTracesInteger_` appends to private band stores
  2. `wst.absorb(bst[b])` at `src/DIAPseudoSpectra.cpp:3305,3310 **reallocates** the arena
  3. `t.off += base` at `src/DIAPseudoSpectra.cpp:3306,3310` — offsets updated
  4. `t.st = &wst` at `src/DIAPseudoSpectra.cpp:3311` — **re-set after absorb** (safe)
  5. `splitIntegerTraces` at line 3325: rebuilds arena again
  6. `t.st = &wst` at `src/DIAPseudoSpectra.cpp:3326` — **re-set after split**
- **Currently safe** only because `st` is manually re-set after every arena modification
- **Fragile:** Any future code path that moves a `Trace` without updating `st` will dangle

### **✗ Zero-means-missing invariant can be violated**

- `Trace` line 249-250: "ZERO MEANS MISSING, which is valid because every observed intensity is > noise_threshold >= 0"
- **Problem:** `noise_threshold_int` can be **0** (user-settable)
- `src/DIAPseudoSpectra.cpp:853` (old `member`): `if ((double)sl.inten[k] > noise)`
- If `noise = 0`, then `inten[k] == 0` is **ambiguous** — real zero or missing?
- **Impact:** `Trace::real(k)` line 264: `return xv(k) > 0.0f;` — **floating point equality** is unsafe; should be `fabs(xv(k)) > epsilon` or check against `noise`

### **✗ uint16 overflow risk**

- `Trace::len` line 258: "asserted < 65536"
- `makeSpan` line 329: `if (L >= 65536) throw ...` — **good**
- **BUT** `Trace::npts` line 259 and `Trace::apex` line 260: **no overflow checks**
- A trace could have 70,000 spanned frames with 65,536+ real points → **undefined behavior**
- **Fix needed:** Add `assert(npts < 65536)` and `assert(apex < len)` in `makeSpan`

### **✗ OpenMS path: empty `store.b` and zero sentinels**

- `src/DIAPseudoSpectra.cpp:3333`: `wst.setFrames(ri, nullptr)` → `store.b` is **empty**
- `TraceStore::setFrames` line 284: `if (bb) b = *bb; else b.clear();`
- `Trace::xv` line 308: `return st->inten[off + k];` — OK, no `b` access
- **BUT** any code that accesses `t.b` on OpenMS traces gets **0.0** (line 243)
- **From `INTEGER-MEMORY-PLAN.md` line 41:** "`b` (8 B) ... `store.b` is **empty** on the OpenMS path ... and `b` stays 0.0 there, which `exportMz_` relies on"
- **Risk:** If `exportMz_` or any consumer uses `t.b` for OpenMS traces, it gets garbage

### **✗ `makeSpan` floating-point equality and sorting issues**

- Line 326: `sort(pts.begin(), pts.end())` — sorts `vector<pair<uint32_t, float>>` by frame then intensity
- **Non-deterministic:** If two points have same frame (should not happen), sort order depends on float comparison
- Line 336: `if (store.inten[t.off + k] == 0.0f) ++np;` — **floating point equality** — **DANGEROUS**
- **Should be:** `if (store.inten[t.off + k] != 0.0f)` since `makeSpan` just set it, or use an epsilon
- **Worse:** If a real point has exactly 0.0 intensity (possible if `noise=0`), it will be counted as missing

### **✗ `splitIntegerTraces`: child apex bin lookup**

- Lines 1082-1089: **Correctly preserves per-point bins** via `wst.bins[t.off + k]`
- Lines 1111-1120: After split, **recomputes child's apex bin from MassTrace**
- **Good:** The bug described in `docs/TRACE-STRUCT-REDESIGN.md:237-242` ("walk over parent traces to look the bin up") was **fixed**
- **Verified:** Commit `bbb2121` confirms OpenMS arm digest-identical, integer arm fixed

---
---
---

## 4. **The occupancy question**

**Measured today:**
| Arm | Wall | Occupancy | CPU-seconds (user) |
|---|---|---|---|
| integer | 6:21 = 373 s | 68.5x | 14,249 |
| OpenMS | 6:54 = 414 s | 81.0x | 19,440 |

**Arithmetic:**
- Occupancy = CPU-seconds ÷ wall-seconds (by definition, `INTEGER-MEMORY-PLAN.md:152`)
- **Integer implied CPU-seconds:** 68.5 × 373 = **25,485.5 s**
- **OpenMS implied CPU-seconds:** 81.0 × 414 = **33,534 s**
- **User's measured CPU-seconds:** integer 14,249, OpenMS 19,440

**Inconsistency:**
- **Integer:** 25,485.5 vs 14,249 = **77% discrepancy**
- **OpenMS:** 33,534 vs 19,440 = **74% discrepancy**

**Hypothesis from `INTEGER-MEMORY-PLAN.md:152-154`:**
- Occupancy should track CPU-seconds directly
- The numbers **do not agree** → either:
  1. **Measurement error** — occupancy computed differently than CPU-seconds
  2. **Real scheduling defect** — threads are parked or stalled

**From the plan, dataset A numbers DO agree:**
- integer: 31,033 CPU-s at 66× → wall = 31,033/66 ≈ 470 s
- OpenMS: 41,530 CPU-s at 84× → wall = 41,530/84 ≈ 494 s
- **Work ratio:** 31,033/41,530 = 0.747
- **Occupancy ratio:** 66/84 = 0.786
- **Agree to within 5%** — consistent

**Conclusion for dataset D:**
- The occupancy numbers are **INCONSISTENT** with measured CPU-seconds
- **Residual:** ~25% unexplained (not the 5% from dataset A)
- **Likely cause:** Measurement artifact or the occupancy metric includes something other than pure CPU time (e.g., time in `R` state including spin-wait)

**What to measure next:**
- **Thread-state sampling** as per `INTEGER-MEMORY-PLAN.md:158-166`:
  ```bash
  while :; do date +%s; awk '{print $3}' /proc/$PID/task/*/stat | sort | uniq -c; sleep 1; done
  ```
- Check for threads in `S` (sleeping) or `D` (I/O) states that inflate wall time without contributing to occupancy

---
---
---

## 5. **What should be done next, and what should be STOPPED?**

### **🛑 STOP IMMEDIATELY**

| Item | Reason | Priority |
|---|---|---|
| **Claiming integer is the default** | The registration default is still "openms" | **CRITICAL** |
| **Making integer the default** | Both-engines rule not met; dataset A not re-run post-span | **CRITICAL** |
| **Trace scalar removal** | Ledger broken; savings estimates unreliable | **HIGH** |
| **Allocator experiments** | Already falsified; no evidence of benefit | **HIGH** |
| **Fine-tuning min_sample_rate** | Output impact unmeasured; changes trace validity | **MEDIUM** |

### **✅ DO NEXT (ranked by value)**

| # | Task | Saving/Value | Risk | Falsifier |
|---|---|---|---|---|
| **0** | **Fix ledger accounting** | Prerequisite for ALL byte claims | **B** | `MEM_TRACES` must fall below 12 GB; `MEM_PREP` in [0, 10.8] GB |
| | | `MemGuard::release()`, fix scoping, add `memSub` | | | |
| **1** | **Actually change the default** | Consistency | **B** | `getStringOption_("trace:detector")` returns "integer" |
| | | Change registration default at line 1485 to "integer" | | | |
| **2** | **Run dataset A post-span** | Both-engines rule | **E** | Peptides within replicate spread on BOTH engines |
| | | Full both-engines + entrapment gate on dataset A | | | |
| **3** | **Verify prep compaction** | ~1.2-2.4 GB | **B** | Digest must be identical |
| | | Commit `7d6e56f` needs both-engines gate | | | |
| **4** | **Investigate occupancy** | Clarify metrics | **B** | Thread-state sampler shows <5% unexplained |
| | | Run with the sampler from the plan | | | |
| **5** | **Address v0.3.0 blockers** | Release readiness | **B** | External reproduction, dependency SHAs, worked example |
| | | From user: "no external party can reproduce a number..." | | | |

### **📋 WHAT IS BEING MISSED**

1. **The ledger is fundamentally broken** — without correct accounting, **no memory claim is trustworthy**
2. **The both-engines rule is the project's safety net** — bending it undermines reproducibility
3. **The default was never actually changed** — this is a documentation/commit message bug at minimum
4. **dataset A post-span validation is missing** — the span refactor changed semantics; old dataset A numbers are stale

### **💡 SPECIFIC QUANTITATIVE FINDINGS**

| Finding | Impact | File:line |
|---|---|---|
| Default not changed | User confusion, incorrect claims | `src/DIAPseudoSpectra.cpp:1485` |
| Ledger cumulative, not peak | Memory claims inflated | `src/DIAPseudoSpectra.cpp:3339` |
| `MEM_PREP` scope too wide | Overstates prep memory | `src/DIAPseudoSpectra.cpp:3211` |
| Zero sentinel invalid if noise=0 | Correctness risk | `src/DIAPseudoSpectra.cpp:249-250,853` |
| Floating-point equality in `makeSpan` | Non-determinism risk | `src/DIAPseudoSpectra.cpp:336` |
| Occupancy inconsistency | Metric reliability issue | User's table vs `INTEGER-MEMORY-PLAN.md:152` |

---
---
---

## **FINAL SUMMARY**

**Today's work claimed progress that is partially real but significantly overstated and unverified:**

1. **The integer detector is NOT the default** — the commit message is misleading; the registration was never updated.
2. **The both-engines rule is BENT** — dataset A has not been re-run since the span representation landed, and the Sage regression on dataset D is not offset by MSFragger gains under the stated rule.
3. **The ledger is BROKEN** — cumulative counts, phantom lines, and incorrect scoping make memory claims unreliable.
4. **The occupancy numbers are INCONSISTENT** — suggesting either a measurement error or a real issue that needs investigation.
5. **The span representation itself IS correct** — the gate passed (commit `bbb2121`), but this was only pre-span vs post-span on the same detector, not cross-detector.

**The honest statement of today's evidence:**
- The span representation reduces trace memory from ~35.6 GB to ~6.9 GB and IS pure representation (digest-identical on same detector)
- The integer detector is ~27% faster and ~36% lighter than OpenMS but **loses 1.3% Sage peptides on dataset D** with 8% symmetric churn
- **The integer detector should NOT be the default** until dataset A is re-run post-span and the both-engines rule is satisfied
- **The default was not changed** — this must be fixed or the claim retracted
- **The ledger must be fixed** before any memory claim is credible

**Immediate actions required:**
1. **Revert the misleading commit message** or **actually change the default** in the registration
2. **Fix the ledger** — add `memSub`, correct scoping
3. **Run dataset A with span representation** on both detectors, both engines, entrapment
4. **Do not release v0.3.0** until the packaging blockers are addressed

**The day's work contains real progress (span representation, ledger corrections) but the claims around default status and completeness are not defensible.**
