• I'll verify the branch state and a few load-bearing claims against the actual files, then write the review.

• One more check — the harness's `critical_guards.txt` pins source patterns; the old refusal string is gone from the header:

• Verification done: the worktree is at `2b9ade4c42`, the diff matches what was inlined, and I confirmed the load-bearing claims against the actual sources (`bad_mz` drop at `src/diaspextract.cpp:730`, `requireFiniteMs1Mz` throws at 1809/3522, dnoise setup loads the tool-side axis at 3273, C++20 at `CMakeLists.txt:11`, the C++ golden test parses no `C4` key at `tests/test_calibration_cpp.cpp:80-88`, deploy sha-pins the header at `tests/test_sync_cluster_txn.sh:122,128`). Review follows, by question.

  ## 1. Root choice — correct

  For C2 < 0, `disc = b² − 4|C2|(t − C0)`, so for C0 < t < C0 + b²/(4|C2|) we have 0 ≤ √disc ≤ b. The two textbook roots are `u = (b ∓ √disc)/(2|C2|)`: both ≥ 0 (the smaller is 0 exactly at t = C0). The rising-branch root is `(b − √disc)/(2|C2|) ≤ b/(2|C2|) = u_vertex`. Rationalizing it: `(b−√disc)(b+√disc)/(2|C2|(b+√disc)) = 4|C2|(t−C0)/(2|C2|(b+√disc)) = 2(t−C0)/(b+√disc)` — exactly what `tofToMz` computes (`src/TdfMzCalibration.h:123`). The falling branch is never reachable: numerator > 0 given the `t > C0` guard, denominator > 0 always (b > 0, √disc ≥ 0), so u > 0 always. At the vertex (disc = 0) it returns the correct double root u_v. Continuity at C2 = 0: the expression tends to `(t−C0)/b` from both sides, and for C2 = −0.0 the term `−4·(−0.0)·(C0−t)` is ±0, and `b² ± 0 = b²` bit-exactly in IEEE — so −0.0 is bit-identical to +0.0 (and `−0.0 < 0.0` is false, so it skips the domain check; the test pins both). No t or b yields the other root, a negative u, or a finite wrong value. Clean.

  ## 2. Domain check — sound; no accepting-while-violating row found

  `t_zero = C0 + b²/k`, `t_half = C0 + 0.75·b²/k`, `u_half = b/k` (k = 4|C2|) all check out by direct substitution into t(u) = C0 + b·u + C2·u²: slope dt/du = b − 2|C2|u is b/2 at u = b/k, and t(b/k) = C0 + b²/k − b²/(4k) = C0 + 0.75b²/k. ✓

  The deciding corner is right: disc = b² − k(t − C0) falls in t and rises in b², so the minimum over the domain is at max t and min b; b is minimized at the largest C1 factor, which is `1 + |dC1|·1000/1e6` for either sign of dC1 (`fabs`, `TdfMzCalibration.h:149`). Since `t_half` and `u_half²` are increasing in b², checking only at b_min is conservative for every warmer/colder frame in the span. The m/z condition `kDomainMaxMz + C4 ≤ u_half²` (:159) is the correct worst case over mz ≤ 1e5 for any sign of C4. Soundness proof: for any admitted frame, b(T1) ≥ b_min (up to 1 ulp — irrelevant against a 0.25 threshold with real margins ≥ 0.98), and any tof ≤ 1e8 has t ≤ t_max ≤ t_half(b_min) ≤ t_half(b(T1)), so disc ≥ b²/4. I could not construct a finite accepted row that violates this.

  Overflow/garbage paths in the check all fail closed: `u_half²` or `t_half` overflowing to +inf (tiny |C2|) accepts, which is genuinely safe (vertex astronomically far); `cf_lo ≤ 0` refuses first; C1·cf_hi can't overflow because cf_lo > 0 forces |dC1| < 1000, so C1·cf_hi < 2e12 and b ∈ (0.7, 1e6). The refusal message can print `inf` for the TOF index only if `digitizer_timebase` is denormal (division at :161-162) — cosmetic, the file is refused anyway. LOW, theoretical.

  One inherited (pre-existing) note: the NaN screen at :76 doesn't screen ±inf for timebase/delay/C0. For C2 < 0, `timebase = +inf` → t_max = inf → refused; `delay = −inf` → can be accepted but every conversion is NaN. Fail-safe, theoretical, unchanged for C2 ≥ 0.

  ## 3. Domain coverage — two real gaps, both fail-safe; one overstatement

  - **OpenMS loader TOF indices are unbounded.** The patch converts raw uint32 indices from the frame blob (patch F, lines 182-185); the 1e8 bound is only enforced by `loadTdfAxisBounds` (`src/TdfLoad.h:57`), which runs only in the integer-detector/mzPeak paths. For the actual PXD029836 vectors the margin holds even at 2³²−1 (disc/b² = 0.437, section 3b), so **no real file is affected**. For a hypothetical accepted near-edge calibration (|C2| = 0.0595), a blob index ≥ ~1.33e8 yields NaN — and NaN is dropped+counted (MS2: `diaspextract.cpp:730`) or thrown on (MS1: `requireFiniteMs1Mz`, :3522; dnoise: `recoverPoint` → Refusal::tof → throw). Fail-safe. LOW, theoretical (requires corrupt blob).
  - **`tofOf(mzOf(last) + 1e-5, b)` (`diaspextract.cpp:4116`) can invert far above kDomainMaxMz.** For a near-edge accepted calibration, mzOf(1e8) ≈ 1.1e8 m/z (u_half²), so this caller hands `mzToTof` ~1100× the verified m/z domain. The output is still correct — monotonicity holds to the vertex at 4·u_half², independent of the slope margin — but the header's "everything the tool can ask of the model" (:29-31) is slightly overstated on the m/z side. No wrong output possible. LOW, theoretical. The other `tofOf` callers are all inside the domain: `best`'s cmz ± 3 sd is bounded by the 42,950 store cap plus a realistic sd ≪ vertex mass ≥ 4e5 (`:1081-1082`), band edges use acq_hi ≤ 1e5 (`:4113`), `c.tof = tofOf(amz)` (:1263) inverts a peak m/z that came from the store.
  - **mzPeak `exact()`** fails closed (throws on non-finite result, `MzPeakStreamLoad.h:156-158`) and its T1 comes from `loadTdfCalibration` ✓. **`recoverPoint`** (`DnoiseMs1.h:453-455`) only ever sees loader-produced m/z, which is always a rising-branch image or NaN — the non-monotonic inverse can't false-pass kTofTol on real input.

  ## 4. Temperature — one genuine posture gap (the strongest finding)

  **The OpenMS loader patch never calls `frameReason`** (patch F, frames loop lines 153-168), and with `-dnoise:ms1 false` + OpenMS detector, `loadTdfCalibration` never runs (preflight at `diaspextract.cpp:3230` requires `band_edges_acq && integer_req`; dnoise setup at :3273 requires dnoise). So a negative-C2 file with a corrupt Frames.T1 is converted at an unchecked temperature on that path. Concrete failing input: PXD1418's row with `dC1 = 999 ppm/K` (passes `cf_lo > 0` at 0.001) and a frame at T1 = T1_ref − 2000 K → C1 factor ≈ 3.0 → m/z off by a factor ~3, finite and positive, so `requireFiniteMs1Mz` passes and the MS1 map is silently wrong (MS2 peaks above 42,000 m/z are dropped as `bad_mz`). Before 1.3.1 every negative-C2 file was refused outright, so this is a marginal fail-closed regression for exactly the newly-accepted class. The header discloses it (:34-37). **MEDIUM, theoretical** — no real file has T1 outside ±1000 K (real spreads ≤ 0.034 K), and with real dC1 = 20 ppm/K even an absurd T1 moves m/z by sub-ppm.

  Everything else here is consistent: the FP comparison is coherent — `cf_hi` at :149 is the same op order as `frameFactor` at exactly ΔT = ±1000, and `frameReason` admits the inclusive endpoint, so the boundary frame is exactly the checked corner. `setTofAxis`'s `f > 0 ? f : bref` (:664) and `factor()`'s T1_ref fallback (:643) both stay in-span (bref is the reference temperature). 1000 K never refuses a real file and is still meaningful because the `cf_lo > 0` guard caps |dC1| < 1000 ppm/K for negative C2.

  ## 5. Bit identity for C2 ≥ 0 — holds by construction; I checked every changed line

  - Reordered timebase check (:84 vs :88): for C2 ≥ 0 files nothing changes; a file with both defects gets a different refusal *message*, same refusal. Zero output-byte impact.
  - `frameReason` in the Frames loop (`TdfLoad.h:135`): `!(C2 < 0.0)` short-circuits before any FP on T1; returns empty for every C2 ≥ 0 file. ✓
  - `kDomainMaxTof`/`kDomainMaxMz` are literally 1e8/1e5, replacing identical literals. ✓
  - `#include <cstdio>`, the `private:` section, `static constexpr` members: no layout change (statics don't occupy the object), no aggregate-init sites exist anywhere in the tree (checked), C++20 is required (`CMakeLists.txt:11`) so inline statics are fine, no ODR exposure. The per-frame `std::string` is empty (SSO) for C2 ≥ 0. ✓
  - Mixed deploy: standalone CMake builds the tool against a shim copy of its own header (`CMakeLists.txt:50`), so the tool never sees a stale installed header at compile time; the cluster deploy transaction sha-pins header equality (`test_sync_cluster_txn.sh:122,128`). The remaining hand-built mismatch (old libOpenMS + new tool) fails safe: old libOpenMS still refuses C2 < 0, so the feature is silently absent but nothing converts wrong. ✓

  So the pins *should* reproduce — but see Q8: that gate hasn't run.

  ## 6. Golden cases — genuinely vendor, adequate; three small weaknesses

  - The 210 values come from `tims_index_to_mz` (`cases.append` from `vendor(...)` in section 5); the model re-implementation is used only for diagnostics. Independent ✓. Sufficiency: 7 probes incl. N-1, 4 vectors, 30 frames — reasonable; the dense 2017-probe sweep additionally validated the model without entering the JSON. T1 spread 0.004–0.011 K is thin but matches the instrument.
  - **Provenance gap:** the generator's `KNOWN` sha256 dict pins only 1418/1420/1422; 1431/1408/1347 have no hash check. LOW, trivially fixed.
  - **C4 trap confirmed:** the JSON has no `C4` key and neither parser reads one (`test_calibration_cpp.cpp:80-88` parses 8 keys, C4 stays default-0; Python `p.get("C4", 0.0)`). Correct for all 9 current files, but a future golden file with C4 ≠ 0 would be silently tested at C4 = 0. LOW.
  - **Per-file temperature guard missing:** per-file assertions cover only C2-drop and sign-flip; the temperature ablation is global, and run 1347's is 0.0776 ppm < the 0.1 threshold — the global guard passes only via dataset D's 0.669 ppm. A regenerated JSON with zero T1 spread on the six new files would still pass. LOW.
  - No vacuous assertions found: `g6` mirrors `num` but the C2 = −0.1 test recomputes `tof_zero` from first principles and the NaN/finite ablation at 1e8 vs 0.99·tof_zero is an independent behavioral check; `c2_edge = 3b²/(16(t_max−C0))` is a sound independent derivation of the boundary. The mutation matrix (3d) confirms none of the new checks is vacuous.

  ## 7. Other C2 ≥ 0 assumptions

  None found in the shown code. Grep across `docs/`, `harness/`, `bench/` found no stale "C2 < 0 refused" text outside the CHANGELOG's historical quote of the old message; `harness/critical_guards.txt` pins nothing in this header. The patch's "Fails CLOSED (ModelType != 1, dC2 != 0, multi-row table)" enumeration omits the C2 domain but the mechanism is `isSupported()`, so it's cosmetic. `tdf_table_modeltype1` provenance stays accurate. Trivial: `TdfLoad.h:57`'s refusal message still hardcodes "[2, 1e8]" while comparing against `kDomainMaxTof` — goes stale if the constant ever changes.

  ## 8. CHANGELOG accuracy — numbers check out; one claim is premature

  Verified against sections 3-4 and the code: C2 range −0.000586..−0.001228 over 23 runs/4 vectors ✓ (3c); 7.0e-6 ppm worst, 19–40 / 38–80 ppm ablations ✓ (3a; 18.990 rounds to 19); 2017 probes ✓ (2010 dense + 7); corner disc ≥ 0.984 b² — **caveat**: 3b measures only the 1418/1420/1422 vector directly (0.98687); the value for 1431's vector (~0.9845) is extrapolated, not measured. True, but the shown evidence covers one of four vectors at that corner. LOW. "6.4e9, 16,000×" ✓ (6.4e9/397657 ≈ 16,094; consistent with 1431's 6.6e9 at file frames, slightly less at ±1000 K). "|C2| = 0.0595, 57×" ✓ (0.0595301/0.00104227 = 57.1, vs the 1418 vector). "7.93471e+07", "−0.07 margin", "−2.5 at 1 ps", "edge 1e-6 in/out", "−inf", "dC1 = 1000", "−0.0 bit-identical", "T1 ±1000 K + NaN refused", "2e-10 bins", "round trip 5e-8 bins" (actual 3.0e-8) — all match 3e and the tests. The "every refusal test now has a valid row behind it" claim is real and an improvement.

  **The one problem**: "the spectra of every file the tool accepted before: the four pins reproduce" is stated in the past tense, but the digest gate has not run (invariant 2). The by-construction argument is strong (Q5), but as written the CHANGELOG asserts an unrun verification. **MEDIUM, process** — say "reproduce by construction; digest gate pending" or run the gate before tagging.

  ## 9. Before shipping 1.3.1, ranked

  1. **Run the digest gate** (dataset D e43672a0/8c1b047f, TNBC 009 3aafd0b5/bff54a1f). It's the release's central compatibility claim and the only one with zero executed evidence. Blocker for tagging, not for the branch.
  2. **Close the loader-path T1 gap (finding in Q4)**: add `frameReason` to the patch's Frames.T1 loop — three lines, same header, removes the only path where 1.3.1 converts a frame outside the checked domain. If deliberately deferred, say so in the README, not just the header comment.
  3. **Pin sha256 for runs 1431/1408/1347** in the generator's `KNOWN` (Q6).
  4. **Test hygiene**: per-file (or global-excluding-D) temperature ablation guard; add `C4` to the golden schema or assert the key's absence so a future C4 ≠ 0 file can't be silently tested at 0 (Q6).
  5. **Cosmetic**: `TdfLoad.h:57` message should print the constant, not "[2, 1e8]"; optionally note in the header that `mzOf(n_bins−1)` can exceed kDomainMaxMz for near-edge calibrations and why that's still sound (Q3).
  6. **Optional defense in depth**: saturate/refuse blob TOF indices ≥ kDomainMaxTof in the loader's `convert` (Q3). Not needed for any observed file — PXD margins hold to 2³² — skip unless cheap.

  Bottom line: the mathematics, the root choice, the domain corner, and the bit-identity argument are all correct as far as I can verify statically, and the mutation matrix shows the new guards are non-vacuous. Nothing here would bite on real data; the only finding with a plausible path to wrong output is the unchecked-T1 loader path (Q4), and it requires a corrupt file plus non-default options. Ship after the digest gate runs and, ideally, item 2.

