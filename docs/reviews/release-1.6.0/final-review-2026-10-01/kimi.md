• I'll review the diff against the invariants. Let me first pull the context the excerpts don't cover: the speculative loop's `order` construction and claims fill, the full `spx:` header stamp list, the OpenMP construct map, and `xicCorr`.

• Let me pin exact line numbers for the findings.

• Review complete. I read the diff, the surrounding context at b2185db (`inferPrecursors_` speculative loop, the tile/window OpenMP structure, the header stamps) and cross-checked every option registration against README/CHANGELOG. No critical findings; two highs. Findings first, then the numbered answers.

  # Findings (ranked)

  **F1 — high — src/diaspextract.cpp:3513-3518 (extension), 2189-2201 (fold relation)**
  Claim: v2's extension (B) can create a duplicate precursor at one monoisotope that the twin fold cannot fold.
  State: extension moves `pc.mono_mz` onto the most intense trace T at position -(nl+1) without claiming it. T is later seeded as its own precursor P2 (every unused trace seeds), with P2.mono = T.mz, P2.rt = T's apex frame, P2.im = T.im. The moved precursor P1 keeps its own seed's apex RT and IM. The fold requires bit-equal RT and |d1/K0| ≤ 0.005; T was selected within `delta_rt` seconds and `v2_box` ≤ 0.03 of the seed, so P1/P2 differ in RT frame and can differ up to 0.03 in 1/K0 — no fold. Same when T is already claimed by a brighter precursor whose apex frame differs. This re-introduces exactly the "one precursor claimed twice" duplication the fold exists to remove.
  Real data: yes, bounded — moved-left counts are the smallest `[monocheck]` category, but each occurrence is a genuine duplicate spectrum pair (also doubles the foreign-removal candidate at that mono).
  Fix: when extending, record T and either claim it, or extend the twin relation for this provenance (same mono trace, charge equal), or suppress the later seed at commit.

  **F2 — high — src/diaspextract.cpp:3466-3478 (`ratio`), 3433 (clamp)**
  Claim: an empty heavier position rejects the step (`return 0.0` at mul==1, and at mul>1 when -j+1 is a walk position), but the walk's own partner at that position can be invisible to PS because the walk found it with `charge:iso_im_tolerance` 0.05 while the box is clamped to [0.01, 0.03].
  State: py3-class run whose isotope 1/K0 scatter reaches 0.05; auto box wants > 0.03 but clamps; PS(-j+1) = 0 although the walk legitimately stepped there → `ratio = 0 < 0.2` → true step rejected → mono moved one isotope right off the true monoisotope. The clamp, not the percentile, decides on exactly the runs the auto box was built for.
  Real data: yes — the CHANGELOG itself measured 12 % true-step rejection on 2019 HeLa py3 at a fixed 0.01 box; the clamp caps the mitigation. Net is still a measured win, but the clamp/0.05 mismatch is a concrete wrong-output mechanism on a data class.
  Fix: raise the clamp to at least `charge:iso_im_tolerance` (or derive the cap from it), or treat "heavier position empty but walk partner exists outside the box" as no-evidence (skip) rather than reject.

  **F3 — medium — src/diaspextract.cpp:3762-3766 (key = max member key), README.md:287**
  Claim: a fused peak's cap key is the best member's key, computed from ONE member's intensity, while its emitted intensity is the sum. Since ln is concave, max_i ln(1+I_i) < ln(1+ΣI_i): fused peaks are systematically under-ranked against unfused peaks of equal total intensity at the 500-cap. That contradicts the documented intent "the cap ranks whole ions".
  State: a rich precursor at the cap; an ion split into 5 × I=100 pieces (key ∝ ln 101) competes against a single I=500 fragment (key ∝ ln 501) — the fused ion loses the slot it would win on summed evidence.
  Real data: bites only on capped spectra (the 50 %-of-spectra class the CHANGELOG cites for K562), so yes.
  Fix: carry the best member's (r, overlap) and recompute the key with the summed intensity at fusion time; `frag_ai` already shows the pattern.

  **F4 — medium — src/diaspextract.cpp:5954-5955, 6009, 3594-3611**
  Claim: foreign candidates are only precursors whose MONO lies in `[plo, phi)`. A co-isolated precursor whose mono sits up to 3·ISO/z outside the window edge but whose M+1..M+3 land inside is never a candidate; its residual isotopes are never filtered in this window.
  State: z=2 precursor with mono 1.4 Th below win_lo; its M+1/M+2 fall inside the window, co-elute, and pass the gate as fragments of this precursor. Not attenuated.
  Real data: yes, small — ~2 × 1.5 Th / 25 Th ≈ 12 % of precursors sit close enough to an edge at z=2, fewer need the full isotope-run match. One-sided under-removal, no false removal.
  Fix: build the index over `[plo', phi')` widened by 3·ISO (z=1 worst case, ~3.01 Th) and let the envelope match decide.

  **F5 — medium — src/diaspextract.cpp:2232-2249 (keyed fold), 2294-2320 (`capAfterFusion_`)**
  Claim: new `#pragma omp parallel for` bodies allocate (`ps`, `fused`, `kk`; `idx`) and call OpenMS containers with no try/catch. A `bad_alloc` (or any OpenMS exception) escaping the region is std::terminate with no message — invariant 5. The unkeyed fold had the same pattern, but the diff adds two new unguarded sites; `monoPositionPass_`'s loops are allocation-free and fine, and its `Precondition` throw (3384) is outside the parallel regions and fine.
  Real data: the tool deliberately runs near the memory ceiling (admission control), so bad_alloc is a plausible terminus.
  Fix: wrap the bodies in try/catch into a `taskErr_`-style handoff and rethrow after the loop, as the assembly taskloop does.

  **F6 — low — src/diaspextract.cpp:3760-3761, 3983-3985**
  Claim: fused m/z weights are the emitted intensities, which include corr^2 (and the IM weight). The fused m/z is biased toward the member with the best co-elution score, not the most abundant piece of the ion. For one ion's pieces the corr spread is small, so the pull is sub-ppm in practice. Also note the deliberate inconsistency: same-bin merge sums only RT-overlapping members, fusion sums all members, twin fold takes max — three different intensity conventions for "one ion", worth one README sentence.

  **F7 — low — src/diaspextract.cpp:3277**
  Phase-1 skip clears `R.emit/claims/deps` but not `R.v2`/`R.mc`. Harmless today (phase 2 skips used seeds before reading either, line 3284), but the slot then carries a previous batch's record — fragile if a future path reads `R.v2` before the used-check. Reset all five fields.

  **F8 — low — src/diaspextract.cpp:4491-4493**
  `assembly:frag_core_frames` must be odd is validated unconditionally, so `-assembly:frag_core_frames 4` now kills a run where `frag_intensity` is the default `apex` and the value is meaningless. Validate only when `frag_int_ == 1`.

  **F9 — low — src/diaspextract.cpp:3599 (build), 3654-3658 (`own`), 3643-3646**
  With `assembly:require_isotope_support false`, guessed precursors (charge defaulted to 2) become foreign candidates with a fictional envelope, and a guessed PC's own envelope is unprotected only when `charge <= 0` — after defaulting it IS protected at the wrong spacing (z=2). Off-default path; either exclude `pc.guessed` from candidates or use the walk charge.

  **F10 — low — src/diaspextract.cpp:3644-3646**
  The same-ion tests step the isotope grid at the caller's charge. The same ion called at two charges (z=2 vs z=3, monos 1/6-isotope apart) is not recognized (j·ISO/z never lands within 30 ppm), so it can become a foreign candidate of itself. Impact is only the generic Q16 removal, not own-isotope stripping. Acceptable, worth a comment.

  **F11 — low (perf) — src/diaspextract.cpp:330-343, 3669/3688-3694, 4182-4186**
  Per-assembly atomic RMWs on shared counter arrays (`foreignCount_` is 72 B and spans two lines; the arrays are adjacent statics, so fuse/foreign/anchor counters false-share), plus two full sorts per fused assembly (`om` and a copied `oi`) and ~4 vector allocations. At 100 threads this is measurable but small against assembly cost; consider per-thread counter accumulation and deriving `oi` from `om` ranks.

  **F12 — docs — README.md:319**
  "The header carries twenty-four `spx:` userParams": a DEFAULT 1.6.0 run writes 27 — the 24 unconditional keys plus `spx:monocheck` (5549), `spx:foreign` (5557) and `spx:fragment_fuse` (5564), all on by default. The sentence kept the 1.5.0 count.

  **F13 — docs — README.md:281**
  `min_fragments` row still says "after the gate and the same-bin merge". The check now runs after foreign removal (4128) and fusion (4179-4188); both can drop a spectrum below the floor.

  **F14 — docs — README.md:292 vs src/diaspextract.cpp:2468**
  README: "0.005 gave up to 7 % more Sage peptides and no change on MSFragger". Help: "MSFragger +3-5 %". Direct contradiction.

  **F15 — docs — src/diaspextract.cpp:2648 vs README.md:244**
  im_box examples disagree: help "(K562 9905: 0.01; 2019 HeLa py3 …: 0.019)", README "0.0101 …, 0.018 and 0.022". (Also scrub items.)

  **F16 — docs — src/diaspextract.cpp:2547, 2557-2559, 2636**
  `assembly:foreign_precursor_weight` (0), `assembly:fragment_fuse_ppm` (25) and `charge:mono_profile_check` (v2) are ON by default and change the default output, yet all three are registered advanced (hidden from plain `-help`) and two carry "Experimental." in help/README. A default user gets experimental, hidden-governed output. Either drop the advanced bit/"Experimental" or don't ship them as defaults.

  **F17 — docs — CHANGELOG.md "Unreleased"**
  Stale numbers inside the v2 entry's first paragraph: min_ratio "(0.15)", extend "(0.5)", "im_box 0.02 1/K0" — final defaults are 0.2 / 0.6 / auto. Noted for rewrite; also the "off by default" headers on entries whose options rc-b turns on are confusing.

  **F18 — scrub — beyond the known list**
  - CHANGELOG.md:55 "(diaTracer 44 %)" — names the comparison tool.
  - CHANGELOG.md:21 "harness-grade measurement" — harness reference.
  - CHANGELOG.md:16 "TNBC_009, K562 CAD_3197, HeLa 2450 / 2737 / 19 / 28" — specimen/run IDs; "K562 CAD_3197" is additionally a K562 result. Also :26 "HeLa 25pc", :27 "Evosep 60/200 SPD", "TNBC", :28 "K562 scorecard".
  - CHANGELOG.md:53, :71, :74, :77, :89, :94, :102, :105, :110, :136-218 — K562 (9905) and HeLa_22/HeLa_34 run IDs throughout, including precise internal counts (e.g. :193 "156,781 of 219,342 z=1 calls").
  - src/diaspextract.cpp:3626-3628 `attenuateForeign_` comment: "HeLa_22: 31 % …" — run ID in exported source.
  - src/diaspextract.cpp:2468 im_weight_sigma help also names "TNBC" (known: K562).
  - README.md:283 foreign_ppm row "on HeLa_22 (10 ng)" — run ID (known list covers the README's K562 rows only).
  - No S08/S23/S26/S30/S33/S36, AGXT/PH1/liver, /Users/ paths, or PXD041421 found in the diff. Pre-existing, not this diff: CHANGELOG.md:241-242 and :690 mention the harness in already-shipped sections — confirm policy.

  **F19 — info — src/diaspextract.cpp:4176-4178**
  `frag_bin`/`frag_span` are stale after fusion and `frag_ai` is not compacted by the merge/fusion — verified no readers afterwards (cap, emission and GateDump read only `frags`/`frag_scores`/`resc`). The comment at 4176 says it; fine.

  **F20 — info — src/diaspextract.cpp:2238 vs 2260**
  Keyed fold sorts (mz, intensity, key), unkeyed (mz, intensity): within one fused group the summation term order can differ → 1-ulp double differences in the weighted m/z before the float cast, and a group boundary could in principle flip. Negligible; "bit for bit" holds after the float cast except on a rounding boundary.

  # Numbered answers

  1. Grouping is well-defined and input-order independent: the anchor order is a total order (intensity desc, m/z asc, index) and exact m/z ties cannot survive the same-bin merge. Span ≤ 2·tol and fused peaks remaining within tol are documented behavior. Sum-vs-max inconsistency and the corr²-weighted m/z: see F3/F6.
  2. Yes, it mis-ranks — F3. `frag_bin`/`frag_span` stale but unread — F19.
  3. Twins fused at slightly different weighted m/z land within the fold's 10 ppm in the usual case and merge (max) — no double count; apart >10 ppm both survive (pre-existing failure mode, rarer after fusion since the member sets overlap). The fold's running centroid can still chain. Fusion shrinks folded spectra, so fewer exceed 500; without `post_fusion_cap` some still do — documented.
  4. Intended and documented ("a spectrum can fall below `min_fragments`"). Knock-on is limited to removal: a vanished spectrum can't be a twin member/survivor and canonical order shifts by deletion only; both deterministic.
  5. Linkage condition `m - mp <= mp*tol && m - ms <= 2*ms*tol` is correct as documented (ppm of the lighter member, span capped at 2·tol). Fine.
  6. Deterministic: total sort orders, sums in m/z order, head = min index; `w <= i` in-place compaction is safe because `g.top ≥ head ≥ w` and only heads write. Fine.
  7. Units and direction check out: λ = max(0.1, 0.000594·neutral) is averagine's M+1/M0, so ratio·λ ≈ 1 at expectation; reject < 0.2 and extend ≥ 0.6 are consistent. tol at the seed m/z and `delta_rt` on apex RTs are fine.
  8. `mul` mapping verified: `left_mz[i/mul - 1]` stays in bounds (i ≤ nl = v.nl·mul); the `(j-1) % mul != 0` two-position fallback with λ²/2 matches Poisson M+2/M0 and is correctly conditioned on -j+1 not being a walk position; the iterate=false walk-back (3499) can no longer leave the mono on a bare position, and at iterate=true an accepted acc always has PS(-acc) > 0 so `leftMz` finds a real trace. `v.nl < 5` (not `nl`) is the right miss test; extension at mul>1 deliberately tests a position the z=1 walk never stepped — correct at final-charge spacing.
  9. Empty-heavier ⇒ reject is wrong when the walk's partner sits outside the box — F2. No NaN/inf paths from finite inputs (den > 0 guarded, λ ≥ 0.1); a NaN trace intensity would make ratio NaN and every comparison false (step accepted) — benign.
  10. `order` is intensity-descending with a total tie-break (3023-3027) and `pcs` keeps commit order through the veto (in place) — the "brightest decile" premise holds. p90 index, clamp and `nth_element` are value-deterministic; the parallel fill is disjoint.
  11. Alignment holds: exactly one emit per committed seed in both scoring modes (3181, 3243/3257), `v2in` pushed alongside (3289), stale re-evaluation recomputes `R.v2`, the veto edits in place, and sort/erasures all come after `monoPositionPass_`. The Precondition is unreachable absent a bug. Envelope mode pushes z=0 records and the pass neither reads them nor checks size.
  12. Moving mono before window assignment is self-consistent (sort at 5270 and isolation offsets at 4236 both post-date the pass). The real problem is the extension duplicate — F1.
  13. Covered: `findPartner` records every found partner in `R.deps` (3066), v1 re-reads only the walk's own partners and immutable profiles and is fully recomputed on stale re-eval; v2 records only walk results. No uncovered state.
  14. Weight-0 compaction covers every array read later; the cap-key update is algebraically right for all three `cap_rank` modes (`log1p` ratio for the log keys, linear for corr_inten, `frag_ai` is exactly the key's intensity); own protection at max(ppm, 30 ppm) and both-direction `on_grid` are as documented. Same-ion-different-charge escapes the grid test — F10.
  15. Candidate set edge miss — F4. The index is tile-invariant (built from the global `[plo, phi)`, not the owned subset — 5954/6009). `&f == &pc` is valid (pc always references `precursors` via `pidx`, 6044). Guessed-precursor candidates — F9.
  16. Possible but rare: it needs ≥2 of 4 positions at 10 ppm plus RT and 0.015 1/K0 co-location; the corpus entrapment is unchanged. Acceptable.
  17. No ranking pathology: ln(1+I) is monotone and the weight is applied consistently to cap key, foreign rescale, anchor and fusion. The exp(-2) = 0.135 suppression at the gate edge is the intended default. (Emitted intensity carries corr², the key doesn't — pre-existing.)
  18. Nothing found: all new parallel loops write disjoint slots (`flag`/`rej`/`pcs[ii]`, per-cluster, per-spectrum, `gaps[ii]`), reductions are counters only, `v2_box` is fixed before the loops, foreign/fuse/v2/recap are tile-invariant by construction.
  19. No new task layer and no omp construct inside the assembly taskloop (`attenuateForeign_`/`fuseFragments_` are omp-free). `monoPositionPass_` runs at top level; `capAfterFusion_`/keyed `mergeTwins_` run in the tile block at 6140-6162, which is outside the `parallel/single` region (5680-6096) — top-level parallel fors, same as 1.5.0. The 64×nthreads bound is untouched.
  20. F5 covers the new unguarded allocation sites. The `Precondition` (3384) and the even-`frag_core_frames` `InvalidParameter` are outside parallel regions (but see F8).
  21. F11; otherwise fine (per-window `ForeignIdx_` build is one sort; candidate scan is a bounded range probe).
  22. F12 (count 24 → 27), F13 (min_fragments), F14 (MSFragger contradiction), F15 (im_box examples), F16 (advanced/"Experimental" on defaults), F17 (CHANGELOG stale 0.15/0.5/0.02). Registered defaults themselves match README tables (0.005 / 0 / 25+anchored / v2 with 0.2, auto, 0.6, true).
  23. Reset invariant holds in static review: with the four options reset, `mono_check_==0` skips both monocheck blocks and the pass; `fx` is null and `frag_ai` untouched; `fuse_ppm_==0` skips fusion; `post_fusion_cap_` false keeps the unkeyed fold and 12-B ledger; all stamps are conditional; the GateDump `rescued` branch requires non-empty `resc_fi`; `best_nl`/`best_gstop`/`n_before`/`n_merged`/`n_resc` are pure bookkeeping. Consistent with the measured digest equality.
  24. F18.

  **Bottom line:** shippable after the scrub (F18) and the README/help disagreements (F12-F17); I'd want a decision on F1 and F2 (both change output in unintended ways on identifiable data states) and on F3 (cap ranking contradicts the documented "cap ranks whole ions") before tagging 1.6.0.

