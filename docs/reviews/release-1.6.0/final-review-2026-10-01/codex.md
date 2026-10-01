The four-option reset looks sound by inspection. I would hold release sign-off for the empty-denominator behavior, exception-handling gaps, and export scrub. I found no new assembly race or task-count increase.

Reviewed **b2185db**, without creating, modifying, or deleting files. Counterexamples below are static constructions; I did not rerun the corpus or digest tests.

Findings, ordered by impact:

- **R1 — high — [src/diaspextract.cpp:3469](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:3469>) — An absent denominator is treated as evidence that the monoisotope is wrong.**  
  Concrete input: a true 3+ envelope at m/z `1500, 1500.3344516, 1500.6689032`, intensities `280, 750, 1000`, common apex RT, and IM `1.001, 1.040, 1.000`. The count walk accepts both lighter partners within 0.05. A v2 box of 0.01 excludes M+1 but includes the true mono and seed. `ratio(2)` returns zero because its denominator is absent; `ratio(1)` then returns zero because its numerator is absent. Iteration reports M+2, introducing **+2.0067 Da neutral error**. These intensities are consistent with λ≈2.67. **Real-data plausible**, given the mobility scatter this feature addresses. **Fix:** distinguish “comparison unavailable” from a measured zero ratio; preserve the candidate or compare against another supported position.

- **R2 — high — [CHANGELOG.md:44](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/CHANGELOG.md:44>), [src/DnoiseMs1.h:25](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/DnoiseMs1.h:25>) — Public-export invariant fails beyond the known matches.**  
  Current exports contain additional run identifiers and K562-derived results without the word “K562.” For example, CHANGELOG:44–45 repeats the 9.9%/5.5% results attributed explicitly later. **This ships immediately**, not theoretically. **Fix:** scrub complete result passages, including continuations, and the identifiers inventoried under Q24; replacing dataset names alone is insufficient.

- **R3 — medium — [src/diaspextract.cpp:3153](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:3153>), :3392, :5083 — The total-order invariant is not established.**  
  The new v2 m/z index sorts equal-m/z traces without a tie-break, leaving PS addition order unspecified across sort implementations. Separately, the inherited MS1 comparator omits profile samples: partners `[1,2,10,2,1]` and `[9,1,10,1,9]` can share every compared field, yet only the first passes v1 correlation against `[2,4,20,4,2]`. Their arrival order can therefore change v1’s mono and claims. **v1 failure is plausible but unmeasured; v2 threshold-rounding failure is theoretical.** Neither demonstrates a new default thread-count regression. **Fix:** complete the MS1 content order with profile samples and use `(mz, canonical index)` for the new index.

- **R4 — medium — [src/diaspextract.cpp:3517](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:3517>), :5954, :6009 — Mono-only window membership loses physically co-isolated envelopes.**  
  In window `[500,525]`, a 2+ precursor with mono `499.8` has M+1 at `500.3016774`. Extending an in-window call to the correct mono removes its assembly from this window despite transmitted isotope signal. The same precursor is absent from `ForeignIdx_`, so its in-window M+1/M+2 residuals cannot be removed. **Real boundary case.** Mono-only assignment predates rc-b; v2 exposes it through mass movement, while foreign removal inherits it. **Fix:** distinguish reported mono from isolation membership and consider supported isotope positions intersecting the window.

- **R5 — medium — [src/diaspextract.cpp:3757](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:3757>), :2265 — Default fusion can leave two copies of one ion after the twin fold.**  
  Twins at IM `1.0026/1.0074` see fragment pieces at m/z `500.000/500.010`, IM `.9976/1.0124`, equal raw intensities 1000 and equal correlations. Both pieces pass both gates. Default Gaussian weighting produces opposite weights `606.531/146.490`; fusion yields centroids `500.001945362/500.008054638`, **12.2185 ppm apart**. The 10 ppm fold retains both, each intensity ≈753.02. Add two distant ions to satisfy `min_fragments`. **Real-data plausible; frequency unmeasured.** **Fix:** reconcile fragment grouping across twins, ideally retaining group provenance. Re-capping alone cannot remove these duplicates.

- **R6 — medium — [src/diaspextract.cpp:3757](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:3757>) — Fusion sums separate elution events that same-bin merging deliberately excludes.**  
  Nearby fragments at `500.000/500.010` can have disjoint spans while both pass a broad precursor’s gate. Fusion adds their apex intensities unconditionally; identical-bin versions instead retain the strongest overlapping group at :4156. **Plausible with valley splits and neighbouring bins.** **Fix:** apply a consistent RT-overlap policy before summation, or explicitly justify this different amplitude definition. Emitted-intensity centroiding is likewise a heuristic, not an established unbiased mass estimator.

- **R7 — medium — [src/diaspextract.cpp:3660](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:3660>) — Two matched isotope positions do not establish foreign origin.**  
  A genuine singly charged fragment at `600.002`, with isotope `601.0053548`, matches a foreign 1+ envelope at `600/601.0033548` within 10 ppm. With matching RT/IM and an unrelated own precursor, both genuine fragment peaks are deleted even if the foreign precursor contributes no residual signal. **Physically plausible; incidence cannot be inferred from these measurements.** Fragment isotope pairs make the matches correlated, so an independent-two-coincidence argument is inappropriate. **Fix:** require additional evidence tying the fragment traces to the foreign precursor, or use attenuation instead of unconditional deletion.

- **R8 — medium — [src/diaspextract.cpp:2232](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:2232>), :2302, :2314 — New parallel paths violate exception propagation.**  
  With `post_fusion_cap=true`, allocation failure in keyed-fold vectors, recap’s `idx`, or `s.select()` escapes an OpenMP body. **Real under memory pressure, although this option is off by default.** The unkeyed fold already has the same inherited hole. **Fix:** catch inside each iteration using `taskErr_`, then rethrow after the parallel loop.

- **R9 — low — [src/diaspextract.cpp:3630](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:3630>), :3694, :4184 — Diagnostic atomics create avoidable shared contention.**  
  Dense windows at 100 threads perform several sequentially consistent counter updates per assembly, including zero additions. Full-window foreign indexes are also rebuilt for each tile. **Plausible cost, not a demonstrated regression; supplied timings are unchanged.** **Fix:** profile first, then aggregate counters in existing worker tasks and consider reusing window indexes. No additional task layer is needed.

- **R10 — low — [src/diaspextract.cpp:2469](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:2469>), README:293, CHANGELOG:38 — “Intensity only” guarantees are now false downstream.**  
  At 25 ppm, peaks `500.000/500.010/500.020` form one group when the middle is strongest, but two when the leftmost is strongest. Changing `corr_power` or `frag_intensity` can change the anchor, cap competitors, and `min_fragments` survival despite unchanged per-trace cap keys. **Real possible state.** **Fix:** document these grouping consequences; remove guarantees that cap survivors or spectra remain unchanged.

- **R11 — low — [README.md:281](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/README.md:281>), :319; CHANGELOG:44, :78, :92, :135 — Release prose is stale.**  
  Current default runs contradict “off by default,” “default output unchanged,” the old v2 values, and the **24-header-key** claim. Default output has **27 `spx:` keys**. `min_fragments` also follows foreign removal and fusion. **Every default run is affected by these documentation errors.** **Fix:** rewrite around final defaults and distinguish historical settings explicitly. Reconcile README’s unchanged-MSFragger claim with help’s +3–5%, and the im-box examples `0.019` versus `0.018/0.022`.

- **R12 — low — [src/diaspextract.cpp:2544](</Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/tune-wt/rc-b/src/diaspextract.cpp:2544>) — Capping rescue correlation does not prevent outranking an anchor.**  
  A rescue with `r=.8, I=10000, overlap=2` has evidence ≈22.1; an anchor with `.8, 10, 3` has ≈7.67. **Real possible state.** **Fix:** remove “so it never outweighs an anchor”; only the correlation component is bounded.

Answers to the numbered checks:

1. **Grouping is well-defined for finite, canonically ordered inputs.** Anchored groups can span 50 ppm, and their centroids need not be separated by 25 ppm. Arbitrary input permutations are not guaranteed bit-identical because equal-m/z summation ties use indices. Estimator limitations are R5–R6.

2. **MAX keys can rank a stronger aggregate below a singleton.** With equal correlation/support, `100+100` retains `ln(101)=4.615`, below a singleton 150’s `ln(151)=5.017`. This is the documented maximum-member policy, not a coding error. Call it maximum-member evidence; recomputing aggregate evidence requires a defined correlation/support model. No later code reads stale `frag_bin/frag_span`.

3. **Splitting/double representation is possible: R5.** The fold uses a running centroid, allowing chains exceeding 10 ppm overall. It can also max-collapse two nearby groups from the same member spectrum. Freed cap slots and changed centroids mean over-500 frequency can increase or decrease; no monotonic guarantee follows.

4. **Intentional and documented.** Removing a below-three spectrum can remove a twin contributor, preferred survivor, or connecting member, changing survivor metadata and ordering deterministically.

5. **Correct implementation of the documented linkage rule:** adjacent gap ≤ previous-m/z tolerance and total span ≤ twice first-m/z tolerance.

6. **Compaction is safe.** Every group member is at or after its head; preceding writes occur before the current head, and the strongest member’s fields are read before overwriting. Summation order is fixed for canonical input. Non-finite inputs would invalidate comparator assumptions.

7. **Units and ratio direction are correct.** Seed-based ppm becomes an absolute m/z half-width; RT uses apex seconds; IM uses 1/K0. For Poisson isotopes, lighter/heavier ×λ equals one at mono/M+1 and increases for later isotope pairs.

8. **Mapping is correct for supported `mul=1/2`.** The fallback condition identifies missing intermediate positions and uses λ²/2 correctly. `iterate=false` skips an empty intermediate landing. `v.nl<5` tests the original walk’s limit. At `mul=2`, extension examines a previously untested intermediate position—additional inference, not recovery of a miss at that exact position.

9. **Empty-denominator rejection is R1.** PS accumulates finite float values into **double**; MS1 non-finite apex values and coordinates are filtered. Ordinary data therefore does not present the suggested float-sum overflow. If NaN nevertheless entered a ratio, rejection would stop because `< threshold` is false; extension would fail.

10. **Correct:** emitted count walks remain in descending seed-intensity order. The sample is `ceil(nz/10)`, excluding z=0 records. The percentile uses `floor(.9*(n−1))`. Workers write distinct gap slots; serial `nth_element` introduces no scheduling dependence.

11. **Alignment holds.** Commit appends records alongside emissions; adaptive-auto/digest do not reorder; veto edits in place; erasures/sorting follow the pass. Envelope scoring bypasses testing and produces an explicit n/a stamp.

12. **Window consequences are R4.** Extension can also project existing hypotheses onto the same mono at different apex frames, which the exact-RT twin relation cannot fold. The other seed was processed before this post-pass; extension itself creates no additional precursor record.

13. **Dependencies are sufficient.** Selected partners enter `R.deps`; v1 profiles are immutable. Re-evaluation resets `R.v2`. Misses remain misses as claims only accumulate. v2 reads immutable traces after inference.

14. **Array handling and rescaling are correct.** `frag_ai` is consumed once before removal and never read afterward, so not compacting it is safe. Logarithmic/linear rescaling matches the relevant keys. Own protection uses `max(ppm,30 ppm)`. Symmetric ±3-grid skipping is conservative and can also spare distinct coincident ions.

15. **Boundary omission is R4.** The index otherwise is tile-invariant, built from the complete window list. `pc` references `precursors`, so address self-skip works. Guessed precursors become candidates when retained with a positive default charge; they are absent under default isotope-support filtering.

16. **R7 gives a concrete false positive.** Its frequency needs fragment-level truth or a suitable null experiment; aggregate peptide/FDR results do not determine it.

17. **The edge weight is correctly `exp(-2)≈0.1353`.** `frag_ai` correctly carries the IM-weighted apex. `log1p(I)` remains monotone below one and approaches a linear function there. Main interactions are precursor-dependent fusion centroids, maximum-member ranking, and R12’s inaccurate rescue guarantee.

18. **No new data race found.** Assembly scratch is task-local, fold clusters are disjoint, recap and v2 write separate elements, and new atomics feed diagnostics. Determinism qualifications are R3; the measured configurations do not prove every equal-key boundary case.

19. **No new task layer or nested OpenMP construct inside assembly.** V2 runs at top level; fold/recap run after the window team joins. The existing task-count bound remains unchanged.

20. **R8 is the exception failure.** V2’s parallel bodies allocate nothing; its `Precondition` and odd-core `InvalidParameter` execute serially and can propagate normally. Existing speculative inference also retains an older allocation-exception exposure.

21. **Cost is bounded but data-dependent:** fusion sorts `F` fragments; foreign removal adds another sort, an RT-range candidate scan, and four position searches per candidate. Dense co-elution increases cost. R9 is a profiling target, not evidence of an observed slowdown.

22. **Registered values agree with README default columns**, as follows. All new options are non-required; “advanced” controls ordinary-help visibility.

| Option/group | Registered defaults | Advanced |
|---|---|---|
| `assembly:max_fragments`, `im_weight_sigma` | 500, 0.005 | No |
| `diag:selftest_twins` flag | false/absent | Yes |
| `gate:anchor_rescue/min_count/min_corr/rescue_corr/max_rescued` | false, 3, 0.8, 0.7, 50 | Yes |
| `assembly:post_fusion_cap` | false | Yes |
| `assembly:frag_intensity/frag_core_frames` | apex, 3 | Yes |
| `assembly:foreign_precursor_weight/ppm/dim/min_iso` | 0, 10, 0.015, 2 | Yes |
| `assembly:fragment_fuse_ppm/mode` | 25, anchored | Yes |
| `charge:mono_profile_check/min_corr/max_dim` | v2, 0.6, 0.015 | Yes |
| `charge:mono_position_min_ratio/im_box/extend/iterate` | 0.2, 0, 0.6, true | Yes |

The three promoted mechanisms remain hidden from ordinary help; foreign/fusion still say “Experimental,” and mono checking says “under evaluation” in README. That needs an explicit release-interface decision. R10–R12 cover semantic/documentation disagreements. The default header has **24 unconditional keys plus `spx:monocheck`, `spx:foreign`, and `spx:fragment_fuse` = 27**. Also, v1’s “charge unchanged” only describes its immediate edit: its changed precursor population/masses can affect the subsequent IM veto.

23. **Static reset audit passes.** `gstop/best_nl` only record state; empty rescue arrays and `n_resc` change nothing; minimum-count behavior remains equivalent; ledger accounting uses the original 12 bytes; new stamps disappear; the twin fold takes its original unkeyed branch. This assumes the other new options retain their off/default values. No unguarded spectrum change was found.

24. **Known violations confirmed. Additional scrub inventory:**

| Content | Locations at b2185db |
|---|---|
| `TNBC 009` | `src/DnoiseMs1.h:25`; `src/diaspextract.cpp:2488, 2518, 2607, 2659, 2836, 6187` |
| `HeLa_22` | `src/diaspextract.cpp:3626`; `README.md:283`; `CHANGELOG.md:12, 15, 19, 53, 89, 105` |
| `HeLa_34` | `CHANGELOG.md:12, 15, 19` |
| `TNBC_009`, `CAD_3197`, HeLa runs `2450/2737/19/28` | `CHANGELOG.md:16`; run 28 again at :18 |
| K562 results without the dataset word | `CHANGELOG.md:44–45, 95, 103–104, 194–196, 204–205, 210`, plus continuation lines throughout the named result passages |
| Older public acquisition identifiers `1418/1420/1422/1431/1408/1347` | `CHANGELOG.md:300, 378, 401, 425, 446` |
| Older public run identifiers `001/009` | `CHANGELOG.md:367, 460, 543, 546, 603, 605–607, 610, 617, 622, 631, 634, 643, 652, 715, 726, 735, 973, 977, 997, 1006, 1177, 1185, 1192–1197` |

The last two rows are acquisition identifiers, not demonstrated private specimen identifiers; include them if the intended export rule excludes run identifiers as well.

The anonymous scorecard statistics at CHANGELOG:55 and :79 need provenance checked before retention; the exported text alone does not establish their dataset. The comparison tool’s literal name at :55 must become “the reference implementation.”

No additional banned cohort labels, AGXT/PH1/liver terms, `/Users/` paths, PXD041421, or references to `docs/reviews/`, `docs/benchmarks/`, or `harness/` were found. Generic mentions of “harness” are not references to those private paths.
