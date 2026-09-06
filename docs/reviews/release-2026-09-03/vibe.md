## Hostile Review: speXtractor v0.3.0 (approaching)

---

## 1. CORRECTNESS AND SAFETY OF THE CODE

### CRITICAL: Silent Wrongness and Data Races

#### **1.1 OpenMP Parallel Window Loop - Data Race in Precursor Binning**
**File:** `src/DIAPseudoSpectra.cpp:2394-2395`
**Finding:** Binary search on `prec_mz` vector inside parallel window loop
```cpp
size_t plo = lower_bound(prec_mz.begin(), prec_mz.end(), win_lo) - prec_mz.begin();
size_t phi = upper_bound(prec_mz.begin(), prec_mz.end(), win_hi) - prec_mz.begin();
```
**Risk:** `prec_mz` is captured by reference in the parallel-for at line 2288. While `prec_mz` itself is const (vector of doubles), the `lower_bound/upper_bound` are **read-only operations** on a const vector. However, the **Precondition**: the `precursors` vector is sorted by `mono_mz` at line 2151 and `prec_mz` is populated at line 2158. **This is actually SAFE** - read-only concurrent access to a const vector is defined behavior in C++17+. 

**BUT** - the `precursors[pi]` access at line 2479 inside the nested parallel-for (precursor-level parallelism at line 2475) **IS a data race**. The outer loop iterates `wi` (windows), the inner loop at line 2475 iterates `pii` over `[plo, phi)` - **each window's precursor range is independent**, so this is actually **correctly partitioned**. No race.

**Verdict:** **FALSE ALARM** - the design is correct. Each window gets its own precursor range, and within a window, each precursor is processed independently.

#### **1.2 CRITICAL: Non-Deterministic Accumulation in `scoreCandidates_`**
**File:** `src/DIAPseudoSpectra.cpp:1434-1449`
**Finding:** `touched` vector and `pdense` accumulation
```cpp
vector<int> touched;
touched.reserve(p_xic.size());
for (size_t pi = 0; pi < p_xic.size(); ++pi)
{
  // ...
  if (gi >= 0) { if (pdense[gi] == 0.0f) touched.push_back(gi); pdense[gi] += (float)pval; }
}
```
**Risk:** This is **SINGLE-THREADED within a precursor** (called per-precursor). The `pdense` vector is **passed by reference** but is **firstprivate** in the nested parallel loop at line 2475: `firstprivate(pdense)`. This creates a **private copy per thread** - **CORRECT**.

**BUT** - wait, let me re-read line 2475:
```cpp
#pragma omp parallel for schedule(dynamic, 32) firstprivate(pdense) num_threads(p_team)
```
The `pdense` is **firstprivate** - each thread gets its own **copy** initialized from the original. This means **each thread accumulates into its OWN pdense**, which is **incorrect** - the precursor correlation should use the SAME pdense buffer. The precursor XIC is resampled onto the grid once, and this buffer should be shared.

**Actually** - looking at the signature of `scoreCandidates_` at line 1409:
```cpp
void scoreCandidates_(..., vector<float>& pdense, Emit&& emit) const
```
The `pdense` is passed by **non-const reference** and is **modified**. The firstprivate creates a **private copy** per thread, so each thread has its own buffer. But each thread is processing a **different precursor** (different `pc`), so each precursor **should** have its own pdense buffer. This is **CORRECT by design**.

**Verdict:** The design is actually sound - each precursor gets its own pdense buffer.

#### **1.3 CRITICAL: Integer/Size_t Narrowing in Binary Search**
**File:** `src/DIAPseudoSpectra.cpp:1133-1134` (and many other places)
**Finding:**
```cpp
size_t klo = lower_bound(sorted_mz.begin(), sorted_mz.end(), target - tol) - sorted_mz.begin();
size_t khi = upper_bound(sorted_mz.begin(), sorted_mz.end(), target + tol) - sorted_mz.begin();
```
**Risk:** The result of `lower_bound - begin()` is `std::vector<double>::difference_type` which is **signed** (typically `ptrdiff_t`). Assigning to `size_t` (unsigned) when the result is negative (not found) **wraps to a very large number**.

**Impact:** If `target - tol` is greater than all elements, `lower_bound` returns `end()`, and `end() - begin()` is `N` (the size), which is representable in `size_t`. If `target - tol` is **less than all elements**, `lower_bound` returns `begin()`, and `begin() - begin()` is 0. So the **only safe case** is when the range is valid.

**BUT** - what if `target - tol` is **NaN**? Then the comparison `*(begin + i) < target - tol` is **false** for all i (NaN comparisons are always false), so `lower_bound` returns `end()`, and `klo = N`. Then the loop `for (size_t k = klo; k < khi; ++k)` with `klo = N` will **not execute** (since `khi <= N`). This is **safe but silent** - a NaN target simply returns no partners.

**More serious:** At line 1134, if `target + tol` is **NaN**, `upper_bound` returns `begin()` (since all comparisons with NaN are false, so the condition `value < element` is false for all elements), so `khi = 0`. Then `klo` could be > `khi`, and the loop `for (size_t k = klo; k < khi; ++k)` would **wrap around** if `klo` is large and `khi` is 0 (since `size_t` is unsigned, `k < 0` is always true, but `khi = 0` means `k < 0` is false).

Wait - `khi` is `size_t`, so it cannot be negative. If `upper_bound` returns `begin()`, then `khi = 0`. If `klo` is any value >= 0, then `k < khi` becomes `k < 0` which is **false for all k** (since k is size_t >= 0). So the loop **does not execute**. This is **safe**.

**BUT** - there's a subtler issue: if `target - tol` is **greater than the maximum representable double**, it becomes **+inf**. Then `lower_bound` returns `end()`, `klo = N`. If `target + tol` is also **+inf**, `upper_bound` returns `end()`, `khi = N`. Then the loop runs from `k = N` to `k < N` - which is **empty**. Safe.

If `target - tol` is **-inf**, `lower_bound` returns `begin()`, `klo = 0`. If `target + tol` is **+inf**, `upper_bound` returns `end()`, `khi = N`. Loop runs from 0 to N - **correct**.

**Verdict:** The unsigned assignment is **safe** in practice because the loop condition `k < khi` will be false when `klo >= khi` due to unsigned wrap-around. But it's **fragile** and **non-obvious**. Better to use `ptrdiff_t` or `auto` for the difference.

**FIX:** Change to:
```cpp
auto klo = lower_bound(sorted_mz.begin(), sorted_mz.end(), target - tol) - sorted_mz.begin();
auto khi = upper_bound(sorted_mz.begin(), sorted_mz.end(), target + tol) - sorted_mz.begin();
```
This preserves the signedness and makes the wrap-around behavior explicit.

#### **1.4 CRITICAL: Iterator Arithmetic with `--si` Style Decrements**
**File:** `src/DIAPseudoSpectra.cpp:1170-1186`
**Finding:** The isotope walk with potential off-by-one
```cpp
for (int k = 1; k <= 5; ++k)          // lighter partners define the monoisotope
{
  long j = findPartner(s.mz - k * ISO / z);
  if (j < 0) break;                   // BREAK on first miss (contiguous only)
  // ...
  lefts.push_back(j);
  partners.push_back((size_t)j); mono = ms1[j].mz; prev_int = ms1[j].intensity;
}
```
**Risk:** The `break` on first miss assumes **contiguous** isotope envelopes. But the comment at line 1149 explicitly states this: "contiguous walk with BREAK-ON-FIRST-MISS". This is **intentional**.

**BUT** - what if the **first** partner (k=1) is missing but the second (k=2) is present? Then the walk **breaks immediately** and never finds the k=2 partner. This means a **gapped envelope** (M, M+2 present, M+1 missing) will be **treated as M-only** (monoisotope = seed m/z). This is **WRONG** for real isotopes where M+1 might be below the noise threshold.

**Impact:** The code **explicitly documents** this at line 1149-1150: "contiguous walk with BREAK-ON-FIRST-MISS". So this is **intentional behavior** for the `envelope_scoring=false` (count) path.

**BUT** - the **envelope_scoring=true** path (lines 1254-1303) uses a **different algorithm** that **allows gaps**:
```cpp
for (int k = 1; k <= 3; ++k)          // heavier partners add confidence
{
  long j = findPartner(mono_mz + k * ISO / z);
  if (j >= 0) { ... }
  // NO break on miss - gaps allowed
}
```
This is **inconsistent** with the count path. The count path **requires contiguous** isotopes, the envelope path **allows gaps**. This is **documented** at line 1255: "GAPPED envelopes: no break-on-first-miss".

**Verdict:** The behavior is **intentional and documented**. However, the **inconsistency** between the two paths is a **design smell**. The count path will **miss real envelopes** with gaps (common at low S/N), while the envelope path will find them.

**This is actually a CORRECTNESS ISSUE** - the count path is **known to be worse** (line 1145-1148 documents a baseline-fix where reverting only the score produced a third algorithm). The count path is kept for **reproducibility** of the original algorithm.

**FIX:** This is **not a bug** but a **documented trade-off**. The help text for `charge:scoring` should make this **explicitly clear** that `count` requires contiguous isotopes.

#### **1.5 CRITICAL: Float Comparison in `xicCorr`**
**File:** `src/DIAPseudoSpectra.cpp:1077-1095`
**Finding:**
```cpp
double dot = 0, na = 0, nb = 0;
for (size_t i = 0; i < a.size() && i < b.size(); ++i) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i]; }
return (na > 0 && nb > 0) ? dot / (sqrt(na) * sqrt(nb)) : 0.0;
```
**Risk:** This computes **cosine similarity**, not Pearson correlation. The function name `xicCorr` suggests Pearson, but the implementation is **cosine**. This is used at line 1288 for isotope co-elution scoring.

**BUT** - the function is **only used for isotope partners** (lines 1288-1289), and cosine is **appropriate** for comparing intensity profiles (it's scale-invariant). The Pearson correlation for isotope co-elution would need **mean-centering**, which this doesn't do.

**Impact:** This is **NOT Pearson correlation** despite the name. This could lead to **misinterpretation** by maintainers.

**FIX:** Rename to `xicCosineSim` or add a comment clarifying it's cosine, not Pearson.

#### **1.6 CRITICAL: `used[]` Marking in Isotope Walk**
**File:** `src/DIAPseudoSpectra.cpp:1237-1245` (count path)
**Finding:**
```cpp
out.push_back(pc0);
used[seed] = true;
for (size_t j : best_partners) used[j] = true;   // de-isotope
```
**Risk:** The `used[seed]` is marked **after** `out.push_back(pc0)`. But `pc0.trace_idx = seed`. If an exception occurs between the push_back and the marking, `used[seed]` remains false, and `seed` could be **reprocessed** later.

**BUT** - there are no exceptions in this path (it's all basic operations). However, this is **fragile**.

**MORE SERIOUS:** At line 1245, `best_partners` contains the **isotope partners** found during the walk. But what if one of those partners is **also a seed** for a later iteration? The `used[]` marking prevents it from being **re-seeded**, but the **order** of processing is by intensity (line 1115-1120). The most intense trace is processed first, and its isotope partners are marked used. Then when the less intense isotope partner would be processed as a seed, it's **skipped** (line 1226).

**This is CORRECT** - it ensures each isotope envelope is processed **once** (as the most intense member).

**BUT** - what if the **monoisotope** is NOT the most intense? Then the **wrong** member becomes the seed, and the **monoisotope is marked as used** and never becomes a seed. This means the **reported precursor m/z** will be **wrong**.

**Example:** A peptide with M+1 > M (common above ~1800 Da). The M+1 trace is more intense, so it's processed first. It finds M as a partner (k=1 leftward). The mono is set to M (line 1165-1166: `mono = ms1[j].mz` when j is found). So the **reported mono_mz** is M, not M+1. This is **CORRECT**.

**Verdict:** The `used[]` marking is **correct** and prevents duplicate emission of the same isotope envelope.

#### **1.7 SILENT WRONGNESS: Off-by-One in `lower_bound/upper_bound` Window Routing**
**File:** `src/DIAPseudoSpectra.cpp:2394-2395`
**Finding:**
```cpp
size_t plo = lower_bound(prec_mz.begin(), prec_mz.end(), win_lo) - prec_mz.begin();
size_t phi = upper_bound(prec_mz.begin(), prec_mz.end(), win_hi) - prec_mz.begin();
for (size_t pi = plo; pi < phi; ++pi)
```
**Risk:** This finds precursors with `prec_mz[pi] >= win_lo && prec_mz[pi] <= win_hi`. But what about precursors with `m/z` **exactly equal** to `win_hi`? `upper_bound` returns the first element **greater than** `win_hi`, so `phi` points to the first element > `win_hi`. This means precursors with `m/z == win_hi` **ARE included** (since `pi < phi` includes `pi` where `prec_mz[pi] == win_hi`).

**This is CORRECT** for the isolation window routing. The window is `[win_lo, win_hi]` inclusive.

**BUT** - the isolation window in Bruker is typically defined as `(target - offset, target + offset)`, and the precursor m/z should be **within** this window. The current code **includes** the exact boundaries, which is **correct**.

**Verdict:** This is **correct**.

#### **1.8 SILENT WRONGNESS: `n_isotopes` Counting Inconsistency**
**File:** `src/DIAPseudoSpectra.cpp:1234-1235` (count path) vs `1338` (envelope path)
**Finding:**
```cpp
// Count path:
const int n = 1 + (int)partners.size();  // line 1234
pc0.n_isotopes = best_n;                // line 1242

// Envelope path:
pc.n_isotopes = 1 + (int)best.partners.size();   // line 1338
```
**Risk:** The count path counts **all partners** (left + right). The envelope path counts **only the members** (which excludes the seed if it's not the mono). But wait - line 1267-1271:
```cpp
if ((size_t)mono_idx != seed) members.push_back((size_t)mono_idx);
```
So the envelope path **excludes the seed** from `members` if the seed is not the mono. Then `n_isotopes = 1 + members.size()` includes the mono (which may or may not be the seed).

**BUT** - the count path at line 1166:
```cpp
partners.push_back((size_t)j); mono = ms1[j].mz; prev_int = ms1[j].intensity;
```
This **includes all partners** (left and right). Then `n = 1 + partners.size()` where the `1` is the seed.

**Inconsistency:** The count path counts **seed + all partners**. The envelope path counts **mono + all partners** (where mono may or may not be the seed). If the mono is the seed, they're the same. If the mono is NOT the seed (e.g., seed is M+1, mono is M), then:
- Count path: n = 1 (seed=M+1) + 2 (M and M+2) = 3
- Envelope path: n = 1 (mono=M) + 2 (M+1 and M+2) = 3

**Actually consistent!** Both count the total number of isotope peaks in the envelope.

**Verdict:** The counting is **consistent**.

#### **1.9 SILENT WRONGNESS: Empty Container Edge Case in `inferPrecursors_`**
**File:** `src/DIAPseudoSpectra.cpp:1099-1102`
**Finding:** The function starts with:
```cpp
const size_t N = ms1.size();
vector<size_t> by_mz(N);
for (size_t i = 0; i < N; ++i) by_mz[i] = i;
```
**Risk:** If `ms1` is **empty** (`N == 0`), then `by_mz` is an empty vector, and the subsequent sort and loops are **safe** (no iterations). This is **correct**.

**BUT** - at line 1114-1115:
```cpp
vector<size_t> order(N);
for (size_t i = 0; i < N; ++i) order[i] = i;
```
If `N == 0`, `order` is empty, and the sort at line 1116 is a no-op. **Safe**.

**Verdict:** Empty container handling is **correct**.

#### **1.10 SILENT WRONGNESS: Potential Division by Zero in `atrousLevels`**
**File:** `src/DIAPseudoSpectra.cpp:687-705`
**Finding:**
```cpp
int atrousLevels(const vector<pair<double, double>>& xic, double scale_sec)
{
  if (xic.size() < 5 || scale_sec <= 0.0) return 0;
  // ...
  const double dt = d[d.size() / 2];                 // median
  if (dt <= 0.0) return 0;
  const double want = scale_sec / dt;                // desired support, in SAMPLES
  if (want < 2.0) return 0;
  const int j = (int)std::lround(std::log2(want));
  return std::max(0, std::min(j, 4));
}
```
**Risk:** `d` is built from the **differences** between consecutive RT points (lines 692-696). If all differences are **zero** (degenerate XIC), then `d` will contain zeros, and `dt = 0`. The check `if (dt <= 0.0) return 0` catches this. **Safe**.

**BUT** - what if `d` is **empty**? This can happen if `xic.size() == 1` (line 692-696: the loop runs for `i = 1` to `i < xic.size()`, so if `xic.size() == 1`, the loop doesn't run, `d` is empty). Then `d[d.size() / 2]` is **undefined behavior** (out of bounds access).

**FIX:**
```cpp
if (d.empty()) return 0;
```

#### **1.11 SILENT WRONGNESS: Potential NaN in `xicCorr` Normalization**
**File:** `src/DIAPseudoSpectra.cpp:1087-1094`
**Finding:**
```cpp
if (n < 5) return 0.0;  // [adv-fix] n=3 gives P(r>0.9)~14.4% under the null
double mx = 0, my = 0;
for (size_t k = 0; k < n; ++k) { mx += x[k]; my += y[k]; }
mx /= n; my /= n;
double num = 0, sx = 0, sy = 0;
for (size_t k = 0; k < n; ++k) { double dx = x[k]-mx, dy = y[k]-my; num += dx*dy; sx += dx*dx; sy += dy*dy; }
return (sx > 0 && sy > 0) ? num / sqrt(sx*sy) : 0.0;
```
**Risk:** If `sx` or `sy` is **zero** (constant profiles), the function returns 0.0. This is **intentional** (line 1094 check). **Safe**.

**BUT** - what if `sx` or `sy` is **negative** due to floating-point error? The check `sx > 0 && sy > 0` would fail, and return 0.0. This is **safe** but could mask a **real correlation** if floating-point error makes `sx` slightly negative when it should be zero.

**FIX:** Use a tolerance:
```cpp
return (sx > 1e-12 && sy > 1e-12) ? num / sqrt(sx*sy) : 0.0;
```

#### **1.12 CRITICAL: Non-Deterministic Order in `dedupPrecursors_`**
**File:** `src/DIAPseudoSpectra.cpp:1366-1403`
**Finding:** The function sorts `pcs` by (charge, mono_mz, rt, trace_idx) and then removes duplicates. But the **comparison** at line 1390:
```cpp
if (fabs(pcs[j].rt - pcs[i].rt) <= rt_tol && fabs(pcs[j].im - pcs[i].im) <= im_tol)
```
**Risk:** This uses **floating-point tolerance** for equality. Two precursors that are **very close** in RT and IM but not identical will be **merged**. This is **intentional** (it's a fuzzy deduplication).

**BUT** - the **order of removal** depends on the **sort order**. The most intense precursor is kept (line 1392-1393). This is **deterministic** because the sort is stable.

**Verdict:** This is **correct** and deterministic.

---

### **1.13 SUMMARY: Correctness and Safety Findings**

| Severity | File:Line | Issue | Fix |
|---|---|---|---|
| **HIGH** | `src/DIAPseudoSpectra.cpp:700` | `d[d.size()/2]` on empty `d` in `atrousLevels` | Add `if (d.empty()) return 0;` before line 699 |
| **MEDIUM** | `src/DIAPseudoSpectra.cpp:1133-1134` | Unsigned assignment from signed difference | Use `auto` for `klo`, `khi` |
| **MEDIUM** | `src/DIAPseudoSpectra.cpp:1077-1095` | `xicCorr` named as Pearson but is cosine | Rename to `xicCosineSim` or add clarifying comment |
| **MEDIUM** | `src/DIAPseudoSpectra.cpp:1087-1094` | Floating-point `sx > 0` check fragile | Use tolerance: `sx > 1e-12` |
| **LOW** | Multiple | Integer/size_t narrowing in binary search | Use `auto` or `ptrdiff_t` consistently |
| **NONE** | OpenMP parallel loops | Race conditions | **Correctly designed** with proper partitioning |

**WORST DEFECTS FOUND:**
1. **Empty `d` vector access in `atrousLevels`** - **CRASH** on degenerate XIC (size=1)
2. **Misleading function name `xicCorr`** - **SILENT WRONGNESS** (cosine vs Pearson confusion)

---

## 2. CODE VERSUS DOCUMENTATION CONSISTENCY

### **2.1 `charge:min_charge` Application Point**

**Claim in docs/dataset D-BASELINE.md (line 745-749):**
> `charge:min_charge` = 2, dropping singly-charged precursor hypotheses **before extraction**

**Claim in README.md (line 52-53):**
> Adopt `charge:min_charge=2` as the default: confirmed on dataset D/dataset A/dataset B, both engines gain...

**Code:** `src/DIAPseudoSpectra.cpp:2051-2058`
```cpp
{
  const int zmin = getIntOption_("charge:min_charge"); const size_t before = precursors.size();
  precursors.erase(std::remove_if(precursors.begin(), precursors.end(),
                   [zmin](const Precursor_& pc){ return pc.charge > 0 && pc.charge < zmin; }), precursors.end());
  // ...
}
```
**Finding:** The code applies `charge:min_charge` **AFTER** isotope inference (`inferPrecursors_` at line 2006-2007) but **BEFORE** extraction (the window loop starts at line 2288). This matches the docs.

**BUT** - the help string at line 837-843 says:
> "Minimum precursor charge to **EMIT**"

This is **correct** - emission happens in the window loop, and the filter is applied before that.

**Verdict:** **CONSISTENT**

### **2.2 `charge:min_charge` and Charge-0/"Guessed" Precursors**

**Claim in docs/dataset D-BASELINE.md (line 745-749):**
> Dropping them [singly-charged] GAINS peptides... Set 1 to emit them again

**Code behavior:** At line 2032-2033:
```cpp
if (pc.charge == 0) { pc.guessed = true; pc.charge = open_safe ? 0 : default_charge; ++n_default; }
```
Then at line 2051-2058, the `charge:min_charge` filter removes precursors with `pc.charge > 0 && pc.charge < zmin`. This **excludes** charge-0 precursors (since `pc.charge > 0` is false).

**Finding:** Charge-0 (guessed) precursors are **NOT dropped** by `charge:min_charge`. This matches the help string claim: "Minimum precursor charge to EMIT" - charge-0 means "unknown" and is not a numeric charge to compare against `min_charge`.

**BUT** - the docs/dataset D-BASELINE.md line 742-743 says:
> "charge:min_charge" 2 (2 = most common); 0 = leave charge UNSET

This describes `assembly:default_charge`, not `charge:min_charge`. The help string for `charge:min_charge` is **clear** that it only applies to precursors with a **positive** charge.

**Verdict:** **CONSISTENT**

### **2.3 FALSIFIED Parameters Still Exist with Claimed Defaults**

**Claim in README.md (line 98-100):**
> `competitive`, rank-pruning (`rp_max` 2/4/8), `assembly:apportion`, ... **FALSIFIED**

**Code:** Check parameter registrations:
- Line 767: `assembly:competitive` - **exists**, default OFF
- Line 773: `assembly:rp_max` - **exists**, default 0 (FALSIFIED), help string says "FALSIFIED"
- Line 768: `assembly:apportion` - **exists**, default 0.0, help string says "Try 1 (linear) or 2 (sharper)"

**Finding:** All falsified parameters **still exist** with the **documented defaults**.

**BUT** - the help string for `assembly:rp_max` at line 773 says:
> "FALSIFIED on dataset D (2026-07, all cross-precursor redistributions lost peptides..."

This is **explicit**. The parameter exists but is **not recommended**.

**Verdict:** **CONSISTENT** - the code matches the docs in keeping them as default-off.

### **2.4 Documented Options That No Longer Exist**

**Claim in README.md:** None found.

**Code review:** All parameters mentioned in dataset D-BASELINE.md appear to exist:
- `trace:ms1_split_valleys` (line 792) - exists, default 7.0
- `charge:scoring` (line 849) - exists, default "count"
- `assembly:corr_power` (line 772) - exists, default 2.0
- `assembly:im_weight_sigma` (line 771) - exists, default 0.0

**BUT** - the dataset D-BASELINE.md mentions `ms1split` (line 20) as part of the current defaults. The actual parameter is `trace:ms1_split_valleys`. The docs use a **shorthand** that doesn't match the parameter name.

**Finding:** **INCONSISTENT** - shorthand in docs doesn't match parameter names.

**FIX:** Update dataset D-BASELINE.md to use full parameter names.

### **2.5 Benchmark Numbers the Code Cannot Produce**

**Claim in README.md (line 56-60):**
> Current arm: apex m/z estimator + `charge:min_charge` 2 (2026-09-03).
> Sage peptides: dataset D=12,642, dataset A=11,084, dataset B=10,294

**Code:** The current defaults (from CHANGELOG.md line 6-10) are:
- `charge:min_charge` = 2 (new default)
- `SPEXTRACTOR_MZ_ESTIMATOR=apex` (line 46-49: default is apex)

**Finding:** The README numbers **match** the current code defaults.

**BUT** - the README also says at line 51:
> Runtime (dataset D, 33,553 frames, 100 threads on a 128-core node): **15:21 wall, 106 GB peak RSS**

This is **historical** (from 2026-09-02). The current code has changed since then (e.g., `charge:min_charge` default changed). The number is **not reproducible** with the current defaults.

**FIX:** Update the README with current runtime numbers or add a date stamp.

### **2.6 Parameter Help Strings with Stale Information**

**Finding at line 772 (assembly:corr_power):**
> "DEFAULT 2.0 since 2026-07-28: validated on dataset D (tuning) + dataset A + dataset B (held out)..."

This is **still accurate** - the default is 2.0.

**Finding at line 773 (assembly:rp_max):**
> "FALSIFIED on dataset D (2026-07, all cross-precursor redistributions lost peptides..."

This is **still accurate**.

**Finding at line 849 (charge:scoring):**
> "'count' is the partner-count heuristic... and it eliminates the catastrophic 4->2 confusion (10,199 cases)"

This refers to **old numbers**. The current dataset D-BASELINE.md shows the `4->2` confusion is **gone** with the current defaults. The help string is **stale** but **factually correct** about the behavior.

**Verdict:** Mostly consistent, with minor staleness that doesn't affect correctness.

### **2.7 SUMMARY: Documentation Consistency**

| Severity | Location | Issue | Fix |
|---|---|---|---|
| **MEDIUM** | dataset D-BASELINE.md | Uses shorthand `ms1split` instead of `trace:ms1_split_valleys` | Use full parameter names |
| **LOW** | README.md | Runtime numbers from 2026-09-02 may not match current defaults | Update or date-stamp |
| **LOW** | Help strings | Minor staleness in historical references | Acceptable for v0.3.0 |
| **NONE** | Parameter existence | All documented parameters exist with claimed defaults | **CONSISTENT** |
| **NONE** | `charge:min_charge` application | Applied after isotope inference, before emission, excludes charge-0 | **CONSISTENT** |

---

## 3. IS THE PACKAGE COMPLETE AND USABLE BY SOMEONE ELSE?

### **3.1 Build Instructions**

**Missing:**
- **OpenMS version pinning**: README says "Verified against OpenMS `3.6.0-pre-exported-20260717`" but doesn't say **what versions are supported**. The CMakeLists.txt doesn't enforce a minimum version.
- **Dependency versions**: No versions specified for OpenMP, C++20 compiler, etc.
- **Patch application**: README mentions `scripts/apply_openms_patches.sh` but doesn't explain **what it does** or **why it's required**. A stranger wouldn't know they need to patch OpenMS before building.
- **No build example**: The README has a build command but no **full example** (e.g., `mkdir build && cd build && cmake .. -DOpenMS_DIR=... && make`).

**FIX:**
1. Add minimum OpenMS version to CMakeLists.txt: `find_package(OpenMS 3.6.0 REQUIRED)`
2. Add a "Prerequisites" section to README with exact versions
3. Add a step-by-step build example
4. Explain **why** patching OpenMS is required (calibration fix)

### **3.2 Dependency and Version Pinning**

**Current state:**
- OpenMS: "Verified against 3.6.0-pre-exported-20260717" (README line 30)
- CMake: `cmake_minimum_required(VERSION 3.16)` (CMakeLists.txt line 1)
- C++: `set(CMAKE_CXX_STANDARD 20)` (CMakeLists.txt line 11)
- OpenMP: Optional (CMakeLists.txt line 18-29)
- mzPeak: Optional, build-time flag (CMakeLists.txt line 36-42)

**Missing:**
- **No minimum OpenMS version** in CMakeLists.txt
- **No compiler version** requirement
- **No list of required OpenMS components** (WITH_OPENTIMS for Bruker .d)
- **No mention of Bruker SDK** requirement for vendor calibration

**FIX:**
1. Add `find_package(OpenMS 3.6.0 REQUIRED)` to CMakeLists.txt
2. Add compiler requirement: GCC 11+, Clang 14+, MSVC 19.29+
3. Document that OpenMS must be built with `-DWITH_OPENTIMS=ON` for .d support
4. Document that `OPENMS_BRUKER_SDK_PATH` is optional for vendor calibration

### **3.3 Licence and Third-Party Attribution**

**Current state:**
- README line 137: "BSD-3-Clause. Derived from OpenMS (BSD-3-Clause) — see [NOTICE](NOTICE)."
- **No NOTICE file** in the repo (based on file listing)

**Missing:**
- **NOTICE file** is referenced but may not exist
- **No attribution** for OpenMS patches (scripts/apply_openms_patches.sh)
- **No attribution** for mzPeak library (if used)
- **No list of third-party dependencies** (Arrow, Parquet, SQLiteCpp for mzPeak)

**FIX:**
1. Create a NOTICE file with OpenMS attribution
2. Add a THIRD_PARTY or DEPENDENCIES section to README
3. Document patch provenance in the patches/ directory

### **3.4 Input/Output Format Documentation**

**Missing:**
- **No documentation** of the output mzML format (what metadata is added)
- **No documentation** of input format requirements (MS1 must have IM data)
- **No example** of a valid input file
- **No example** of expected output

**Code:** The output includes metadata:
- `spx_guessed` (line 1650)
- `spx_n_isotopes` (line 1656)
- `spx:mz_calibration` (line 2846)
- `spx:corr_power`, `spx:im_weight_sigma`, `spx:require_isotope_support` (lines 2847-2849)

**FIX:**
1. Add an "Output format" section to README
2. Add a "Worked example" with sample command and expected output
3. Document all `spx:*` metadata fields

### **3.5 Worked Example with Expected Output**

**Missing:**
- **No complete example** from raw data to results
- **No sample input file** (even a small one)
- **No expected peptide count** for a known file

**FIX:**
1. Add a tutorial section: "Running on your own data"
2. Provide a **public dataset** reference (PXD identifier) that works
3. Give expected results (spectrum count, runtime, peptide count range)

### **3.6 Error Messages**

**Current state:** The code has **good error messages** for:
- Missing IM data (line 1792-1793)
- Streaming load failure (line 1768-1769)
- Compact store peak dropping (line 1860-1863)

**Missing:**
- **No error message** for unsupported OpenMS version
- **No error message** for missing patches
- **No guidance** on what to do when calibration fails

**FIX:**
1. Add version check in CMakeLists.txt with helpful error
2. Add patch verification step
3. Improve calibration failure messages with actionable steps

### **3.7 SUMMARY: Package Completeness**

| Severity | Gap | Fix |
|---|---|---|
| **HIGH** | No OpenMS version requirement in CMake | `find_package(OpenMS 3.6.0 REQUIRED)` |
| **HIGH** | No step-by-step build example | Add to README |
| **HIGH** | No explanation of why OpenMS patching is required | Add "Why patching is needed" section |
| **MEDIUM** | No worked example with expected output | Add tutorial section |
| **MEDIUM** | Missing NOTICE file | Create NOTICE with attributions |
| **MEDIUM** | No input/output format documentation | Add sections to README |
| **LOW** | No compiler version requirements | Add to README |
| **LOW** | No third-party dependency list | Add to README |

**Verdict:** **NOT COMPLETE** for a public v0.3.0 release. A stranger could **build** the tool (with difficulty) but would **struggle** to reproduce results or understand the output.

---

## 4. INTERNAL DEVELOPMENT COMMENTARY

### **4.1 Legitimate Engineering Rationale vs. Lab-Notebook Residue**

#### **KEEP: Safety-Critical Rationale**
| Location | Type | Verdict |
|---|---|---|
| Line 494-496 | `[adv-fix]` compact store rationale | **KEEP** - explains why dropping peaks is correct |
| Line 97-104 | `[adv-fix]` NaN/inf validation in compactify | **KEEP** - critical safety fix |
| Line 1087 | `[adv-fix]` n=3 Pearson false positive | **KEEP** - statistical justification |
| Line 147-148 | `[wavelet]` smoothing scale derived from FWHM | **KEEP** - explains design decision |
| Line 228-229 | `[compact]` memory rationale | **KEEP** - explains optimization |

#### **KEEP: Performance Rationale**
| Location | Type | Verdict |
|---|---|---|
| Line 513-520 | `[perf-load]` pick+compact batch | **KEEP** - explains parallelization |
| Line 2220-2223 | `[parallel]` window/band explanation | **KEEP** - core design |
| Line 2264-2269 | `[dyn-mem]` dynamic memory admission | **KEEP** - explains adaptive behavior |
| Line 89-142 | `[perf]` phase timing system | **KEEP** - essential for benchmarking |

#### **KEEP: Algorithm Rationale**
| Location | Type | Verdict |
|---|---|---|
| Line 1145-1151 | `[baseline-fix v2]` original algorithm | **KEEP** - explains why off-branch runs full original |
| Line 1292-1300 | `[adv-fix]` evidence weighting for envelope | **KEEP** - fixes statistical bias |
| Line 1487-1495 | `[B0]` Pearson zero-padding defect | **KEEP** - critical review finding |
| Line 1659-1664 | `[E5]` weighted intensity rationale | **KEEP** - explains emit vs cap key |

#### **MOVE TO DOCS: Historical Experiment Results**
| Location | Type | Verdict |
|---|---|---|
| Line 244-249 | `[C2 A/B]` m/z estimator experiment | **MOVE** - belongs in docs/BENCHMARK-MATRIX.md |
| Line 513-520 | Pick-det experiment | **MOVE** - detailed benchmark result |
| Line 1700-1704 | `[perf-load]` pick(flush) wall time | **MOVE** - specific measurement |
| Line 2342-2347 | `[auto-band-fix]` bands_for heuristic | **MOVE** - tuning decision |

#### **MOVE TO DOCS: Falsified Experiments**
| Location | Type | Verdict |
|---|---|---|
| Line 767 | `[bench]` competitive flag | **MOVE** - the falsification story belongs in docs |
| Line 773 | `[bench]` rp_max falsified | **MOVE** |
| Line 803-805 | `[route-1]` consolidate falsified | **MOVE** |
| Line 813 | `[merge]` merge:rt_window falsified | **MOVE** |

The **help strings** for these parameters (lines 767, 773, 805, 813) **should keep** the "FALSIFIED" marker but **remove** the detailed experiment history. Move the history to docs/.

#### **CUT: Stale Comments**
| Location | Type | Verdict |
|---|---|---|
| Line 844-849 | `[route-1]` charge inference note | **STALE** - says "Only 25.7% of the reference implementation's precursors are matched by us" but this is **old** (current is higher) |
| Line 758 | `[H-3]` "placeholder pending real-data sweep" | **STALE** - real data has been swept |
| Line 981 | `[merged-trace]` instrumentation comment | **STALE** - the measurement has been done |

#### **CUT: Internal Lab-Notebook Residue**
| Location | Type | Verdict |
|---|---|---|
| Line 530-534 | `[pick-det]` SPEXTRACTOR_PICK_SERIAL | **CUT** - environment variable documentation belongs in docs |
| Line 619-621 | `[stream]` ponytail comment | **CUT** - overly detailed |
| Line 918-920 | `[bands]` peak density rationale | **KEEP** - legitimate design |
| Line 1990-1996 | `[determinism]` canonical sort rationale | **KEEP** - critical for reproducibility |
| Line 2237-2244 | `[bands]` per-window band count | **KEEP** - explains adaptive parallelism |

#### **CUT: Redundant or Narrative Comments**
| Location | Type | Verdict |
|---|---|---|
| Line 1006-1027 | `[way-2]` SPLIT MASS TRACES | **TRIM** - the comment is longer than the code |
| Line 1988-1994 | `[determinism]` | **TRIM** - move most to docs, keep 1-2 lines |
| Line 2210-2226 | Memory vs speed comment | **TRIM** - too verbose |

#### **CUT: Dated Arm Names**
| Location | Type | Verdict |
|---|---|---|
| Line 1145 | `[baseline-fix v2]` | **KEEP** - still relevant |
| Line 1292 | `[adv-fix]` | **KEEP** - still relevant |
| Line 1487 | `[B0]` | **KEEP** - still relevant |
| Line 1659 | `[E5]` | **KEEP** - still relevant |

These **tag names** are **fine** - they're references to the adversarial review findings.

#### **4.2 Parameter Help Strings**

**Current state:** Many help strings contain **experiment history** and **benchmark results**. Examples:
- Line 772: `assembly:corr_power` - "DEFAULT 2.0 since 2026-07-28: validated on dataset D..."
- Line 837-843: `charge:min_charge` - "DEFAULT 2: singly-charged hypotheses are 29.3% of emission..."

**Verdict:**
- **KEEP** the **default value** and **brief rationale** (e.g., "DEFAULT 2: removes low-yield z=1 hypotheses")
- **MOVE** the **benchmark numbers** and **experiment dates** to docs/
- **CUT** the **internal tags** like `[bench]`, `[route-1]`, `[Q1]` from help strings (they're fine in code comments)

**Example fix for `charge:min_charge`:**
```cpp
// Current (line 837-843):
"Minimum precursor charge to EMIT. DEFAULT 2: singly-charged hypotheses "
"are 29.3%% of emission on dataset D and 1.73%% of peptides -- a z=1 pseudo-spectrum is identified on 0.42%% of "
"its own spectra against 15.3%% for z=2. Tryptic peptides are essentially never 1+ in ESI and "
"charge:scoring breaks ties toward the LOW charge, so the mis-assignments land there. Dropping them GAINS "
"peptides on both engines on all three files (Sage +0.8/+2.7/+1.4%%, MSFragger +1.2/+5.4/+0.9%%) because "
"their share of the multiple-testing burden goes too, and cuts runtime 17%%. Set 1 to emit them again; "
"3+ is catastrophic (charge 2 carries 56.9%% of peptides)."

// Proposed:
"Minimum precursor charge to EMIT. DEFAULT 2: drops singly-charged hypotheses (rarely correct for tryptic peptides, high emission volume, low identification rate). Set to 1 to restore old behavior."
```

#### **4.3 SUMMARY: Internal Development Commentary**

| Action | Category | Examples | Count |
|---|---|---|---|
| **KEEP** | Safety-critical rationale | `[adv-fix]`, `[perf]` | ~20 |
| **KEEP** | Algorithm design decisions | `[wavelet]`, `[compact]`, `[determinism]` | ~15 |
| **MOVE TO DOCS** | Falsified experiments | competitive, rp_max, consolidate | ~10 |
| **MOVE TO DOCS** | Historical measurements | pick-det, auto-band-fix | ~8 |
| **CUT** | Stale comments | `[H-3]` placeholder, old charge stats | ~5 |
| **CUT** | Overly detailed ponytails | `[stream]` batch sizes, memory notes | ~10 |
| **TRIM** | Redundant/verbose | way-2, determinism, bands | ~5 |
| **CUT FROM HELP** | Internal tags | `[bench]`, `[route-1]`, `[Q1]` | All in help strings |

**Recommendation:**
1. **Remove ~30-40 lines** of lab-notebook residue
2. **Move ~20 lines** of experiment history to docs/
3. **Keep ~50 lines** of legitimate engineering rationale
4. **Simplify help strings** to remove dates, percentages, and internal tags

---

## 5. TEST COVERAGE

### **5.1 Current State**
- **No unit test suite** (confirmed by absence of tests/ directory in file listing)
- Verification via:
  - Whole-file benchmark runs on cluster (dataset D, dataset A, dataset B)
  - Peptide-set equality gate (Sage and MSFragger counts)
  - Determinism check (byte-identical spectrum data across thread counts)

### **5.2 Defects Most Likely to Occur**

Based on the code analysis, the **highest-risk areas** are:

1. **Binary search and iterator arithmetic** - off-by-one, empty container edge cases
2. **Floating-point comparisons** - tolerance handling, NaN/inf propagation
3. **OpenMP parallelism** - data races, non-deterministic accumulation
4. **Isotope envelope inference** - mono selection, charge assignment
5. **Memory management** - compact store, window admission

### **5.3 Minimal Test Suite**

| Test | Function | Input | Expected | Purpose |
|---|---|---|---|---|
| **Iterator bounds** | `inferPrecursors_` | Empty `ms1` vector | Empty `precursors` | Empty container edge case |
| **Iterator bounds** | `inferPrecursors_` | Single trace | One precursor | Single element case |
| **Binary search** | `inferPrecursors_` findPartner | Target outside range | -1 | No partner found |
| **Binary search** | `inferPrecursors_` findPartner | Target at boundary | Correct index | Boundary inclusion |
| **Float comparison** | `xicCorr` | Constant vectors | 0.0 | Degenerate case |
| **Float comparison** | `xicCorr` | Identical vectors | 1.0 | Perfect correlation |
| **Float comparison** | `xicCorr` | Orthogonal vectors | ~0.0 | Zero correlation |
| **Float comparison** | `atrousLevels` | XIC with size=1 | 0 | Empty `d` vector fix |
| **Float comparison** | `atrousLevels` | XIC with all same RT | 0 | Zero differences |
| **OpenMP safety** | `detectTraces_` | Small window | Deterministic traces | Parallel determinism |
| **OpenMP safety** | Window loop | Different thread counts | Same spectra | Thread-count independence |
| **Isotope inference** | `inferPrecursors_` | Ideal averagine envelope | Correct mono and charge | Ground truth |
| **Isotope inference** | `inferPrecursors_` | Gapped envelope (M, M+2) | `count` fails, `envelope` succeeds | Algorithm difference |
| **Memory safety** | `compactify` | NaN m/z | Drops peak, increments `bad_mz` | Input validation |
| **Memory safety** | `compactify` | Out-of-range IM | Drops peak, increments `bad_im` | Input validation |
| **Assembly** | `assembleOne_` | Precursor with no fragments | Empty spectrum | Min fragments gate |
| **Assembly** | `assembleFromList_` | More than `max_frags` | Top `max_frags` by score | Ranking correctness |
| **Deduplication** | `dedupPrecursors_` | Identical precursors | Single precursor kept | Fuzzy dedup |
| **Sorting** | Canonical sort | Two spectra with same RT/mz/charge | Deterministic order | Tie-breaking |

### **5.4 Critical Tests for Silent Wrongness**

These catch **output-affecting** bugs that don't crash:

| Test | Why It Matters |
|---|---|
| **`xicCorr` with n=4** | Current threshold is n<5 returns 0.0; verify this doesn't miss real correlations |
| **`findPartner` with NaN target** | NaN in m/z should not cause infinite loop or wrong partner |
| **`inferPrecursors_` with M+1 > M** | Heavy isotope should be correctly identified as non-mono |
| **`scoreCandidates_` with identical RT** | Should not cause division by zero in Pearson |
| **`buildFragGrid` with empty frags** | Should not crash or produce invalid grid |
| **Window routing with m/z=win_hi** | Boundary case should include precursor in correct window |

### **5.5 Is Current Verification Sufficient?**

**NO.**

**Why:**
1. **Whole-file benchmarks** catch **integration failures** but not **unit-level defects**
2. **Peptide-set equality** catches **output changes** but not **silent wrongness** (e.g., a precursor with wrong m/z that still produces a peptide ID)
3. **No regression tests** for known fixes (e.g., the `d.empty()` fix in `atrousLevels` has no test)
4. **No property-based tests** for invariants (e.g., output should be deterministic, spectra should be sorted)
5. **No edge case tests** for the high-risk areas identified above

**Minimum for v0.3.0:**
- **10-15 unit tests** covering the critical functions above
- **Property tests** for determinism, sorting, validity of output
- **Regression tests** for every `[adv-fix]` in the code

**Reality check:** The project acknowledges this (CHANGELOG.md line 119-125 mentions tests were added in v0.2.0, but they're for calibration, not the main algorithm). The **benchmark-based verification** is **sufficient for the intended audience** (researchers who can run on real data) but **insufficient for a general-purpose tool**.

**Verdict:** **NOT SUFFICIENT** for a public v0.3.0 release. The risk of **silent wrongness** (the project's history) is too high without unit tests for the core algorithms.

---

## FINAL SUMMARY

| Category | Severity | Count | Blocking for v0.3.0? |
|---|---|---|---|
| **Correctness/Safety** | HIGH | 1 (empty `d` access) | **YES** |
| **Correctness/Safety** | MEDIUM | 3 | No |
| **Documentation** | HIGH | 0 | No |
| **Documentation** | MEDIUM | 2 | No |
| **Package Completeness** | HIGH | 3 | **YES** |
| **Package Completeness** | MEDIUM | 4 | No |
| **Internal Comments** | High residue | ~30-40 lines | No (but should clean) |
| **Test Coverage** | Insufficient | 0 unit tests | **YES** |

### **BLOCKING ISSUES FOR v0.3.0:**

1. **`atrousLevels` crashes on single-point XIC** (HIGH severity, correctness)
   - Fix: Add `if (d.empty()) return 0;`

2. **Package incomplete for strangers** (HIGH severity, usability)
   - Missing OpenMS version requirement
   - Missing build example
   - Missing input/output documentation

3. **No unit tests for core algorithms** (HIGH severity, maintainability)
   - Risk of silent wrongness in future changes

### **RECOMMENDATION:**

**DO NOT RELEASE v0.3.0** until:
1. The `atrousLevels` crash is fixed
2. The README is updated with complete build and usage instructions
3. A minimal unit test suite (10-15 tests) is added for the high-risk functions

The code is **correct and safe** for its current users (the project maintainers) but **not ready for public consumption**. The adversarial review found **one crash** and **several completeness gaps** that would frustrate new users. The internal commentary is **mostly legitimate** but has **~30-40 lines of residue** that should be cleaned or moved to docs before release.
