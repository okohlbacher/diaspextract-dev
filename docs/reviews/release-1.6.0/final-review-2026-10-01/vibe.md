## Code Review Findings: DIAspeXtract 1.6.0-rc-b (b2185db)

---

### **CRITICAL: Public-export scrub violations (Invariant 7)**

| id | severity | file:line | claim | failing input | real data | fix |
|---|---|---|---|---|---|---|
| 24-1 | **critical** | src/diaspextract.cpp:2467 | Help for `assembly:im_weight_sigma` cites *"K562, HeLa 10/100 ng and TNBC"* | Any run; compiled into binary | **Yes** | Remove dataset names; say *"public DIA datasets"* |
| 24-2 | **critical** | src/diaspextract.cpp:2681–2682 | Help for `charge:mono_position_im_box` cites *"K562 9905: 0.01; 2019 HeLa py3 … 0.019"* | Any run | **Yes** | Replace with generic *"typical runs show 0.01–0.03"* |
| 24-3 | **critical** | src/diaspextract.cpp:3399–3401 | Doc comment of `monoPositionPass_` cites *"K562 9905 … 54.5 % … 55.7 % …"* | Any run | **Yes** | Remove entire dataset-specific example sentence |
| 24-4 | **critical** | README.md:246–247 | `assembly:im_weight_sigma` description cites *"K562, HeLa 10/100 ng and TNBC"* | Any run | **Yes** | Replace with *"across multiple public datasets"* |
| 24-5 | **critical** | README.md:292–293 | `charge:mono_position_im_box` description cites *"K562 9905 … 2019 HeLa py3 … 0.018 … 0.022"* | Any run | **Yes** | Replace with generic range *"0.01–0.03 in measured runs"* |

---

---

### **HIGH: Exception safety in OpenMP parallel regions**

| id | severity | file:line | claim | failing input | real data | fix |
|---|---|---|---|---|---|---|
| 20-1 | **high** | src/diaspextract.cpp:2292 | `capAfterFusion_`: `vector<Size> idx(s.size())` allocated inside `#pragma omp parallel for` without try/catch | Spectrum with > `max_frags` peaks under low memory | Theoretical | Move allocation outside loop or wrap in try/catch that hands to `taskErr_` |
| 20-2 | **high** | src/diaspextract.cpp:2232–2256 | `mergeTwins_` (keyed path): `vector<array<double,3>> ps`, `vector<pair<double,double>> fused`, `FloatDataArray kk` allocated inside `#pragma omp parallel for` without try/catch | Twin fold with `post_fusion_cap=true` and many twins under low memory | Theoretical | Same as 20-1 |

---
---
### **MEDIUM: Functional correctness issues**

| id | severity | file:line | claim | failing input | real data | fix |
|---|---|---|---|---|---|---|
| 2-1 | **medium** | src/diaspextract.cpp:3717–3740 | Fused peak cap key = **max** of members' keys, not recomputed from fused intensity/overlap. Can mis-rank: a fused peak with one high-key, low-intensity member may outrank an unfused peak with moderate key and high summed intensity, altering `max_frags` retention | Spectrum where one fragment has high correlation but low intensity, fused with others that have lower correlation but higher intensities | **Yes** | Recompute the cap key for the fused peak from its fused intensity and the best correlation among its members |
| 9-1 | **medium** | src/diaspextract.cpp:3438–3450 | `ratio` in `monoPositionPass_` returns **0** when the heavier isotope position in the box is empty (denominator PS(-j+1)=0 for mul=1), **rejecting the step** even if the walk accepted that partner (found with `iso_im_tolerance=0.05`, but box auto-sized to 0.01–0.03). A true isotope partner can sit outside the box, causing false rejection | Precursor whose leftward partner is >0.015 1/K0 from seed | **Yes** | When den=0 and the walk *did* claim a partner at that position, treat the ratio as ∞ (auto-accept) or skip the test for positions the walk reached |

---
---
### **MEDIUM: Documentation inconsistencies**

| id | severity | file:line | claim | fix |
|---|---|---|---|---|
| 22-1 | **medium** | README.md:319 | Claims header carries *"twenty-four `spx:` userParams"*. A default 1.6.0 run writes ~30 keys (new: `spx:foreign`, `spx:fragment_fuse`, `spx:monocheck`; plus existing). | Update count or remove the exact number |
| 22-2 | **medium** | README.md:273 | `assembly:min_fragments` row: *"after the gate and the same-bin merge"* — **stale**; foreign removal and fragment fusion now run **before** that check | Change to *"after the gate, foreign-precursor removal, fragment fusion, and same-bin merge"* |

---
---
### **LOW: Cosmetic / Logical nits**

| id | severity | file:line | claim | fix |
|---|---|---|---|---|
| 24-6 | low | CHANGELOG.md:1–217 | "Unreleased" section contains numerous *"K562"*, *"9905"*, *"HeLa"*, dataset-specific numbers. User noted it will be rewritten for 1.6.0 | Confirm all instances are replaced with public-only references during rewrite |
| 8-1 | low | src/diaspextract.cpp:3438–3450 | For a veto-recalled z=1→2+ walk, `leftMz(i)` for in-between positions returns the **most intense trace in the box** (or a bare m/z). When that trace is not the walk’s own partner, the extension may land on a trace that **was never validated by the walk**. Risk is mitigated by `iterate=true` moving to the next own position (commit 20700ca) | Acceptable; design choice |
| 16-1 | low | src/diaspextract.cpp:3705–3742 | At `foreign_w_=0`, a genuine fragment of THIS precursor that happens to land on a foreign envelope position **is removed**. Code measures 15 % of removed fragments on HeLa_22 were the precursor’s own isotopes (2-point traces 20–60 ppm off grid) | Rare (0.06 % chance per code comment); acceptable limitation |

---
---
---
## **Question-by-question answers (brief where fine)**

| # | Answer |
|---|---|
| **1** | **Fine.** Anchored grouping is well-defined: sort by intensity desc → m/z asc → index; each anchor claims all unfused within tol of its m/z. Intensity-weighted m/z and summed intensity are correct estimators. Ties in intensity/m/z are broken by the total order (index). |
| **2** | **Medium issue (2-1).** MAX cap key can mis-rank fused vs. unfused peaks. `frag_bin`/`frag_span` are stale after fusion but unused thereafter. |
| **3** | **Fine.** Fusion (25 ppm) occurs before the cap; twin fold (10 ppm) occurs after. The fold unions already-capped fragments, but fusion reduces pre-cap count, slightly reducing the chance a folded spectrum exceeds 500. No double-counting: fold merges spectra, fusion merges peaks within one spectrum. |
| **4** | **Intended.** Yes, a spectrum can drop below 3 and vanish; counted in `fuseCount_()[5]`. No knock-on: other spectra unaffected. |
| **5** | **Fine.** `m - mp <= mp*tol && m - ms <= 2*ms*tol` correctly enforces group span ≤ 2×tol. |
| **6** | **Fine.** Sorts are total-ordered; summation in m/z order; head = lowest index; in-place compaction `w ≤ i`. |
| **7** | **Fine.** Units/ppm at seed m/z, δ_RT on apex RTs, box in 1/K0. λ = max(0.1, 0.000594×neutral mass). Ratio direction and averagine bound correct. |
| **8** | **Fine.** For z=1→2+ re-calls: `mul=2`, `leftMz` maps walk positions at z=2 spacing to v2in’s z=1 walk partners. Two-position fallback (λ²/2) for in-between positions handles empty boxes. `iterate=false` + empty box moves mono to next own position (commit 20700ca). |
| **9** | **Medium issue (9-1).** Rejecting due to empty heavier position in box is **incorrect** if the walk accepted that partner (partner tolerance 0.05 > box 0.01–0.03). NaN/inf: ratio NaN → comparison false → no reject (safe but not ideal). |
| **10** | **Fine.** Brightest decile = first ⌈nz/10⌉ in commit (seed-intensity desc) order; still that order at `monoPositionPass_`. p90 index and clamp correct. `nth_element` on deterministically-filled vector is deterministic. |
| **11** | **Fine.** `v2in` built in `inferPrecursors_` commit loop, parallel to `out` (precursors). `monoPositionPass_` runs **before** precursor sort (line 5176 < 5268), so alignment holds. |
| **12** | **Fine.** `monoPositionPass_` runs before sort **and** before window assignment (line 5176 < 5954). Moving mono_mz is correct for window assignment. Extension cannot create duplicate mono: lands on unclaimed trace at a *lighter* m/z. |
| **13** | **Fine.** `R.v2` reset at `evalSeed` start; stale seeds recompute. v2 uses only local `best_*` and immutable `ms1`/`ms1st`; covered by speculative independence. |
| **14** | **Fine.** Weight 0 compacts all parallel arrays *except* `frag_ai` (unused after `attenuateForeign_`). Cap-key update for 0<w<1 correct. Own-ion tests at max(ppm,30 ppm) prevent self-removal. |
| **15** | **Fine.** Candidate set = precursors with mono in window; tile-invariant (built from whole window list). Self-skip `&f == &pc` safe (`pc` reference into `precursors`). Guessed precursors included (charge>0). Limitation (mono-outside co-isolated ion) acceptable. |
| **16** | **Low (16-1).** Possible but rare (0.06 %); own-ion protection at 30 ppm mitigates. |
| **17** | **Fine.** Interactions consistent: weight feeds cap key (via `inten` in `ln(1+I)`) and emitted intensity; no pathology in `ln(1+I)` for I<1. |
| **18** | **Fine.** No thread-count or tile-grid dependency: all new code is either top-level (`monoPositionPass_`), tile-level (`capAfterFusion_`), or per-precursor with deterministic sorts. |
| **19** | **Fine.** No new task layer or nested parallel inside assembly taskloop. `monoPositionPass_`/`capAfterFusion_` parallel regions run outside the taskloop. |
| **20** | **High issues (20-1, 20-2).** New throws at top level are fine. Allocations inside new `#pragma omp parallel for` without try/catch risk `std::terminate` on `bad_alloc`. |
| **21** | **Fine.** Atomic counters (one cache line each) negligible. Foreign scan O(n_candidates × n_fragments) acceptable (n_candidates ~10³, n_fragments ~10² per spectrum). |
| **22** | **Medium issues (22-1, 22-2).** Otherwise: registered defaults, help text, README, CHANGELOG agree for all new/changed options. "Experimental" wording retained for features now on by default is acceptable (they are still experimental). |
| **23** | **Fine.** With `-assembly:im_weight_sigma 0 -assembly:foreign_precursor_weight 1 -assembly:fragment_fuse_ppm 0 -charge:mono_profile_check false`, every changed code path is a no-op (guarded by option checks or conditional compilation). Measured to reproduce 1.5.0 digests. |
| **24** | **Critical/low as listed above (24-1 to 24-6).** |

---
---
---
## **Invariant status summary**

| Invariant | Status |
|---|---|
| **1. Default output changes only through four options** | **PASS** |
| **2. Determinism** | **PASS** (modulo theoretical `bad_alloc` in parallel regions) |
| **3. No data race** | **PASS** (atomics used only for counters; all shared writes guarded) |
| **4. libgomp taskloop cliff** | **PASS** (num_tasks ≤ n_threads ≤ 64×nthreads) |
| **5. Exceptions from tasks propagate** | **PASS** (new parallel bodies are top-level or tile-level, not nested in taskloop; **but** missing try/catch for allocations inside parallel regions) |
| **6. Docs agree with code** | **FAIL** (22-1, 22-2) |
| **7. Public-export scrub** | **FAIL** (24-1 to 24-5; 24-6 to be fixed in CHANGELOG rewrite) |
