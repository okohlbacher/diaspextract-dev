• I'll start by pulling the diff and the relevant pristine OpenMS sources.

• The diff is in hand. Let me verify the patch applies cleanly against the pristine OpenMS tree, then fan out the deep reading.

• Two things I want to confirm with my own eyes in the pristine EPD: the gating of `estimateFWHM` and the SNR filter (the tool sets `width_filtering=off` and `masstrace_snr_filtering=false`), and the minima-acceptance criteria.

• All verification is done — patch applies cleanly, both sub-reads are complete, and I've confirmed the key gating conditions in the pristine EPD myself. Here is the review.

  ---

  ## Verdict summary

  The patch is mechanically correct, the diagnosis is right, and `trace` mode is byte-exact. The residual risks are: (a) one remaining extent-dependence the fix does not address (SG no-smoothing cliff, minor), (b) the MS2 spacing is per-window, not per-MS-level as documented, and can inflate on sparse windows, (c) the merger concern in Q4 is real but only in gappy regions, and the current e2e test cannot detect it. No blockers.

  ## 1. Completeness of the diagnosis

  **Mostly complete.** In the tool's actual EPD configuration (`width_filtering=off`, `masstrace_snr_filtering=false`), the only whole-trace quantities left on the split path are small:

  - **SG no-smoothing cliff — note, real but marginal.** `SavitzkyGolayFilter.h:94`: if `frame_size_ > n`, the filter returns the data **unsmoothed**. Whether any smoothing happens at all therefore depends on the handed trace's total point count. With the fixed window (7 s / 1.626 s → `win_size` 5, `ElutionPeakDetection.cpp:584` `frame_length = max(3, win_size)`), a trace contributing ≤4 real points inside a tile is split on raw data while the whole-run trace (more points) is split smoothed. The scan_time fix does not address this. Failing input: a background ion with 4 frames inside a tile, 40 across the run. Bites on real data only for near-noise traces that downstream length/sample-rate filters likely discard anyway.

  - **SG edge transients — note, bounded by the halo.** `SavitzkyGolayFilter.h:104-118,141-156`: the first/last `mid` points are smoothed with a one-sided window anchored at the *handed* trace's edge, so a sub-range's edge region is smoothed differently from the whole run's. Inherent to tiling; the 123-s halo ≫ the ~8-s window covers it. Fine as long as the halo stays ≫ `win_size` × spacing.

  - **`findLocalExtrema` — fine.** Rejection reach is exactly `±win_size/2` points (`ElutionPeakDetection.cpp:154-195`), minima acceptance is local (`:278-281`). Iteration is by global intensity rank but reach is unchanged. No whole-trace dependence beyond `win_size` itself.

  - **`estimateFWHM` / `computeApexSNR` — inert in the tool's config, but landmines.** I confirmed in the pristine source: `estimateFWHM(true)` runs only under `pw_filtering_ == "fixed"` (`ElutionPeakDetection.cpp:431-437, 511-517`), and `computeApexSNR` only under `mt_snr_filtering_` (`:443-448, 525` — note `:525` tests the SNR of the **whole parent**, not the child). Both are whole-trace (global-max apex, whole-trace RMSE noise, `:54-63,88-93`). If anyone ever enables width filtering or SNR filtering, the tile-dependence returns through a different door. One line in the patch header saying "the tool relies on off/false here" would future-proof it.

  - **Tool side — fine, with two notes.** No post-detection trace merging exists (band halo duplicates are *dropped*, `spextractor.cpp:2189-2194`). `trimToSpan` (`:436-471`) is local around the apex, and the apex is an argmax within one already-split child (`makeSpan`, `:529`), strictly after splitting on all three paths (split `:2225`/`:4145`/`:4187`, trim `:3394`/`:4173`/`:4188`) — a tile boundary cannot move an apex except through EPD itself. Two pre-existing extent-dependences outside the split: the default Pearson normalises by the **window-global** frame count G (`:1666-1672`, the documented [B0] defect; tiling needs G==F per the `:4228-4233` comment), and MassTraceDetection's `min_sample_rate` validity gate is whole-trace (`MassTraceDetection.cpp:451-468`) — a gappy trace failing the rate over the whole run can pass on a dense sub-range, so it can *exist* in a tile and not in the whole run, independent of the split. Worth checking the shipped defaults of `trace:ms{1,2}_min_sample_rate`; if >0, that is a second, untouched tile-instability channel on the detect step.

  ## 2. `frameSpacing()`

  - **Median is correct when <50% of consecutive gaps are inflated — holds on the real paths.** Streaming mzPeak drops empty frames before the consumer (`MzPeakStreamLoad.h:363-364`), so `wst.frame_rt` has 2×-cycle gaps where a window was empty; the median tolerates these. The non-streaming path keeps every cycle (`spextractor.cpp:3289-3294`), so the median is exact there. The native `.d` path has the identical empty-drop gate (`patches/openms-brukertims-mz-calibration.patch:516-518`).
  - **Should-fix: MS2 spacing is per-window, not "of the MS level".** Both MS2 paths derive it per isolation window (`:4146` integer via `wst.frame_rt`; `:4187`→`:2037-2040` OpenMS via `wmap`). A window whose spectrum is empty in ≥ half the cycles (sparse high-m/z windows on real diaPASEF data are plausible) gets a median ≥ 2× the true spacing → `win_size` halves → under-smoothing for that window only, and neighbouring windows disagree. It also contradicts the option's own doc (`:1869`, "of the MS level"). Computing it once per run from the MS1 frame list and passing it down removes both problems at trivial cost. Real data: rare but reachable.
  - **Note: silent fallback on zero spacing.** mzPeak archives missing RT metadata get `retention_time.value_or(0.0)` (`MzPeakStreamLoad.h:280`) → all gaps 0 → `frameSpacing` returns 0.0 (`spextractor.cpp:1266`) → EPD silently reverts to per-trace, i.e. exactly the behaviour `frame` mode claims to fix, with no log line. Theoretical for real archives; a warning when the median is 0 under `frame` mode would do.
  - **1 frame → 0.0 → per-trace fallback: fine.** A 1-frame store yields 1-point traces; split is a no-op anyway. Sorting the MS1 RTs is correct even if the map were unordered (it is `sortSpectra()`'d at `:3361` regardless), and `wst.frame_rt` ordering is throw-enforced by `indexRt` (`:902-912`, checked at `:3349`) — so the unsorted input to `frameSpacing` at `:4146` is safe.
  - **Note: the e2e test exercises nothing here.** `synth()`'s `gap_cycles` blanks peaks but never omits a spectrum (`test/test_spextractor.py:96-107`), so all 20 frames always survive and the median is always exactly 1.4 s. `split_scan_time` appears nowhere in `test/`, `tests/`, `bench/`, or `harness/`. The inflated-median and zero-median failure modes are unreachable from the current generator.

  ## 3. The patch against the pristine base

  **Correct.** Verified `patch --dry-run` applies both files against bd4b895 (EPD files are untouched in that tree). Registration sits after `masstrace_snr_filtering` and before `defaultsToParam_()` (pristine `ElutionPeakDetection.cpp:39-42`); the `updateMembers_` hunk matches pristine `:625-629`; `getAverageMS1CycleTime` has exactly one other occurrence in all of OpenMS — its definition (`MassTrace.h:234`) — so no second per-trace scan-time use survives; the ctor's `defaultsToParam_()` sets `scan_time_=0.0` even if the caller never calls `setParameters`.

  - **`trace` mode reproduces the pre-change bytes exactly — confirmed.** `scan_time=0.0` → `scan_time_ > 0.0` false → the old expression verbatim. `getAverageMS1CycleTime` is guarded (`MassTrace.h:236`: ≤1 point → 0.0), so it can be 0 (also duplicate RTs) but never NaN. The 0 case feeds `ceil(chrom_fwhm/0.0)=+inf` into a `double→Size` conversion (`ElutionPeakDetection.cpp:388`) — technically UB — but identically before and after, so byte-reproduction holds including the UB. Pre-existing, not introduced.
  - **Note (style only):** `double scan_time_ = 0.0;` is the only in-class initializer among EPD's members (all others are set in `updateMembers_`). Harmless.

  ## 4. Science — can the wider fixed window merge two real peaks?

  **Yes, but only in gappy regions, and the mechanism is worth stating precisely.** `win_size` is in *points*, and EPD never resamples — `smoothData` builds the SG input from the raw points (`ElutionPeakDetection.cpp:575-579`) and the filter operates on indices only; its own doc says "works only for uniform profile data" (`SavitzkyGolayFilter.h:65`). So:

  - Dense region: 5 points ≈ 8 s. Two 7-s-FWHM peaks 7 s apart are ~4.3 frames apart, outside `findLocalExtrema`'s ±2-point (≈3.3 s) rejection window, and order-2/frame-5 SG is mild — they almost certainly survive. And for dense traces the old per-trace scan time ≈ the frame spacing anyway, so behaviour is unchanged there.
  - Gappy region: 5 points can span 15–20 s. Both peaks then fall inside one SG window and can fuse into one bump. The old code on the same trace had `win_size` 2–3 (→ frame `max(3,·)=3`), i.e. less smoothing — so the new code can genuinely merge pairs the old code split, exactly the scenario you worried about, but localised to sparse stretches of gappy traces.

  Concrete falsifiers, in order of cheapness:

  1. **Split-count audit on dataset D, whole-run, old vs new**: distribution of EPD children per parent, stratified by parent sample rate (real frames / span frames). A systematic children-drop concentrated in low-sample-rate parents is the merger signature; flat there means the concern is empirically empty.
  2. **Synthetic doublet**: two Gaussians, FWHM 7 s, centres 7 s apart, on a flat background trace with 50–70% of frames randomly dropped; count children old vs new. This needs a synth variant that actually omits spectra — the current `gap_cycles` generator cannot produce it (see Q2).
  3. **Gate**: Sage peptides on D within noise of baseline; if it drops, check whether the drop correlates with low-sample-rate parents before reverting.

  If (1) or (2) fires, the principled fix is gap-filling traces with zero-intensity points at missing frame RTs before EPD — that makes points uniform, so the fixed `win_size` becomes uniform in seconds and the whole question disappears.

  ## 5. Anything else concretely wrong

  - **Fine:** default-argument ordering (`span_log = nullptr, bands = 1, split_by_frame = true`) is legal; `detectTraces_` has a single definition, no other declaration; both call sites pass `split_by_frame` explicitly (`:3392`, `:4187`). The `= true` default is dead code — dropping it would prevent a future caller silently getting frame mode. Note.
  - **Fine:** option registration `(required=false, advanced=true)` matches the dominant neighbour pattern; `setValidStrings_` consistent.
  - **Note, theoretical:** the EPD `scan_time` param has no lower-bound constraint; a negative value gives `win_size ≤ 0` → SG frame 3 and `win_size/2 = 0` → every positive point becomes its own maximum (degenerate, no crash). The tool never passes negative.
  - **Note:** option doc says the spacing is "of the MS level" — per-window in reality (the should-fix in Q2).

  Nothing here blocks gating on Sage/D. The two things I'd do before the release gate: the should-fix in Q2 (per-run spacing, one warning line), and falsifier #1 from Q4 since it needs only data you already have.

