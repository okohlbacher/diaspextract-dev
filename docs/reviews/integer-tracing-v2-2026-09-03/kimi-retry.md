• Reviewing the paste as given. Line numbers below refer to the pasted block, counted from `struct TracePrep` (L7) — `detectTracesInteger_` spans ~L38–175, `splitIntegerTraces` ~L182–220.

  First, the two things you asked me to verify from my own knowledge of OpenMS 3.x:

  - **`updateIterativeWeightedMean_`**: yes, the two cut-off lines are `prev_counter += added_intensity * added_value; prev_denominator += added_intensity;`. The tool's `iwm` lambda (L54–57) is exactly right, including the order (centroid scaled by the *old* counters, counters incremented after).
  - **`total_scans_visited`**: OpenMS passes `scan_counter_down + scan_counter_up + 1`, where each counter is incremented once per visited spectrum step on that side — including empty spectra and rejected candidates — and the `+1` is the apex's own spectrum. The tool's `total = dn.scans + up.scans + 1` (L148) matches. The `adjusted` clamp at L149 is dead code in both (`missed ≤ scans` per side, so `missed_down + missed_up < total` always); OpenMS just subtracts with no guard. No behavioral difference.

  ## 1. Line-by-line diff

  Things that are now **faithful** (so you can stop suspecting them): the interleave guards (L113, L119–120) are exactly OpenMS's `while` condition and per-side guards; index decrement and scan counter increment happen outside the empty-spectrum test on both sides (L137–138), and empty is tested *after* sub-noise deletion via `frame_live` (L122) ≡ `!work_exp[i].empty()`; `member` is applied *inside* the search (L88), exactly like OpenMS searching the filtered map; the IM filter is inside the search (L89), so "closest" is closest among IM-compatible peaks, as in `findBestPeak_`; the visited check happens *after* the closest is chosen (L93) — closest-then-reject, correct; the seed is double-counted in both the m/z and IM weighted means (L106, L108) exactly as `run_` does, while `wsum` is seeded once (L109) exactly as `intensity_so_far = I`; `sdRobust` is called with the already-updated centroid (L131), matching `processPeak_`; termination is `missed > 5` checked after the increments (L139); visited is marked only for valid traces (L151). The `taken` flag (L93, L124) is dead but harmless — a rejected closest peak increments `missed`, same as OpenMS.

  Remaining differences:

  **1a. L23, L28 — thresholds evaluated on integer intensities. SET.**
  OpenMS deletes peaks with float `intensity <= noise` and gates seeds with float `intensity > snr*noise`. You compare `(double)sl.inten[k]`. If `sl.inten` is a *truncation* of the original intensity, every peak whose true intensity lies in `(noise, ceil(noise))` is deleted where OpenMS keeps it, and likewise at the apex SNR gate. That is a systematic, one-sided loss concentrated exactly at the noise floor — the population low-abundance peptide traces are made of. If it's round-to-nearest, the effect is symmetric and mostly washes out. **This is my primary suspect if the running benchmark shows a deficit.** Verify how `inten` was quantized.

  **1b. L32 — seed tie-break on quantized intensities. ORDER → SET.**
  `sl.inten[a] != sl.inten[b]` ties peaks that were merely close in float. OpenMS's `stable_sort` on doubles would order them by their true intensities; you order them by index. Since claim order decides contested peaks, individual traces near ties can come out differently.

  **1c. L81–84, L86 — window edges in bins. SET (rare).**
  `lo_t/hi_t = tofOf(...)` plus `lower_bound(..., lo_t)` and `tof[k] <= hi_t`. If `tofOf` floors, the left edge admits a bin whose m/z is just below `cmz - 3σ` (window slightly wide on the left); if it rounds, both edges can be off by half a bin either way. OpenMS's `MZBegin/MZEnd` are exact in m/z. Only peaks sitting within ~1 bin of the ±3σ edge flip.

  **1d. L90–91 — "closest in bins" is not "closest in m/z" in general. SET (rare).**
  The comment at L71–73 claims monotonicity makes them equivalent. That is only true when all candidates are on the *same side* of the centroid. When two candidates straddle the centroid, comparing `|tof − ct|` vs `|mz − cmz|` can flip the argmin because the calibration's local slope differs on the two sides (sqrt-type calibration). Practically tiny — it needs two IM-compatible candidates nearly equidistant from the centroid on opposite sides — but the justification as written is wrong.

  **1e. L89, L107–108, L130 — IM gate and IM centroid in quantized `imq` units. SET at gate edges.**
  `cim` is a weighted mean of integers and the gate compares `|imq[k] − cim| > im_tol*IM_Q`. Both the per-peak values and the centroid carry up to ~0.5/IM_Q of quantization error, so borderline peaks flip in/out versus OpenMS's float gate. Symmetric, small, but it's a membership decision, so it's SET class.

  **1f. L104, L128 — accepted peak's m/z comes from bin inversion. COORD (occasionally SET).**
  `mzAt` recovers m/z from the stored bin with the peak's frame factor; error ≤ half a bin in m/z. That jitters `cmz` and the robust SD, and therefore the *next* step's ±3σ window — a borderline next-frame candidate can flip. Mostly a coordinate effect.

  **1g. L147 — `max_len_sec > 0.0` vs OpenMS `max_len >= 0`. SET boundary, inert here.**
  OpenMS treats `0.0` as *enabled* (rejects any trace with span > 0); you treat it as "off". Only differs if the caller literally forwards 0.0 meaning "enabled at zero". With your convention (0 = off) and OpenMS's (−1 = off) both handled, no current effect — but it's a trap if the parameter plumbing changes.

  **1h. L168 — `t.mz = cmz` is the apex-double-weighted mean. COORD.**
  Because of the (correct) seed double-count, the running centroid converges to `(2I₀m₀ + ΣIᵢmᵢ)/(2I₀ + ΣIᵢ)`, whereas the `MassTrace` OpenMS emits reports the plain intensity-weighted mean of its peaks. The reported trace m/z is biased slightly toward the apex. This is washed out on the split path (§3, `toTrace` recomputes from per-peak m/z), but any consumer of pre-split `t.mz` — including the no-split early return at L184 — sees the double-weighted value where OpenMS would show the plain one.

  **1i. L48, L131, L139 — hardcoded config. No current diff.**
  `max_missed = 5`, outlier-only termination (no `sample_rate` criterion branch), and `reestimate_mt_sd` always on. All match your stated defaults; none are wired to parameters. Fragility, not a bug today.

  **1j. Output order across bands.** Each band emits in correct intensity order, but the concatenation isn't the global OpenMS order. ORDER only.

  ## 2. The bin/m/z round trip

  - **Window edges**: covered in 1c — you lose up to ±1 bin of edge fidelity versus OpenMS's continuous ±3σ window, direction depending on whether `tofOf` floors or rounds.
  - **Argmin**: covered in 1d — monotone ≠ distance-preserving across the centroid.
  - **Accepted-peak inversion**: 1f — bounded by half a bin, feeds back into centroid/SD.
  - **Re-attached bin after splitting (L214–216)**: the comment "the store is ~400× finer than a bin, so the inversion recovers the measured bin exactly" holds only if `t.mz` *is* a measured per-peak m/z *and* you invert it with *that peak's frame's* factor. Neither is guaranteed:
    - Under a mean/weighted-mean `trace:mz_estimator`, `t.mz` is an average of per-peak m/z values — not a measured value — so `tofOf(t.mz, …)` lands between measured bins by up to the estimator spread.
    - Even under a median estimator (where `t.mz` is some peak's recovered m/z), you invert with the **apex frame's** `t.b`, while that m/z was produced with its own frame's factor. Any inter-frame calibration drift translates directly into a bin offset.
    - The `ax.factor(0)` fallback (L215) is a silent wrong-frame guess if the apex RT lookup fails.
    Effect is COORD (the trace set is already fixed at that point), but it shifts whatever downstream extraction window is keyed on `t.tof`. Bounded by (estimator spread + inter-frame drift) expressed in bins.

  ## 3. Valley splitting

  Your premise is slightly out of date relative to the code: L196–198 **does** recover per-peak m/z (`mzOf(t.xt[i], b_of_rt[t.xi[i]])`, per-frame factor), falling back to flat `t.mz` only when the bin or RT mapping is missing. Two consequences:

  - **Does EPD care about per-peak m/z?** No. `ElutionPeakDetection` splits on the chromatogram (RT, intensity); per-peak m/z feeds only centroid reporting and the mass-trace SNR filter, which is off. So per-peak m/z — recovered or flattened — never changes *which* sub-traces exist. Splitting is SET-identical to OpenMS either way.
  - **Does it change what `toTrace()` reports?** Yes, COORD only. Under a mean/weighted-mean estimator the reported m/z is an average of the per-peak values (recovered path: near-correct; flat fallback: collapses to the double-weighted `t.mz` from 1h). Under median it's a per-peak value. Also note `b_of_rt` is keyed by `rt_index` (L187–188): if two frames in the slab share an `rt_index`, one factor silently overwrites the other.
  - One asymmetry with OpenMS: L184 skips EPD entirely when `split_valleys <= 0` or fewer than two traces. OpenMS runs EPD unconditionally (it would just pass such traces through, recomputing centroids). Inert at your config, but on that path traces keep the 1h-biased `t.mz`.

  ## 4. Banding

  Mechanics: seeds gated to the band's bin core (L101); extension is *not* m/z-restricted — it follows the trace's own ±3σ window across the whole frame range; each band has a private `visited` (L52).

  What can go wrong at boundaries:

  1. **Duplicate traces of one feature.** A feature whose ±3σ m/z span straddles a boundary has peaks in both cores. Band A seeds below the boundary and its extension window reaches across it; band B independently seeds one of the above-boundary peaks and traces the same feature. OpenMS's single `visited` makes the second seed impossible; here both traces are emitted and both are valid. Each goes through EPD and downstream as a separate MassTrace.
  2. **The kill mechanism doesn't fire across bands.** OpenMS terminates a direction when the closest compatible peak is already taken (missed++ → outlier kill). A trace that OpenMS would strangle because a rival claimed its peaks instead runs to completion in the other band — extra and longer traces than OpenMS produces.
  3. **Boundary definition drift.** The core is defined in raw bins, but per-frame calibration factors make the boundary wobble in m/z frame-to-frame. Only the seed's bin is tested, so this mostly just fuzzes which band owns borderline seeds.
  4. **Determinism.** Per band the result is deterministic; if bands run concurrently and merge, output *order* is not.

  **Bounded?** Yes, and one-sided: duplication is limited to features whose ±3σ span crosses a boundary (a fraction ~ `n_bands × 6σ / window_width` of features), each producing at most as many copies as bands it touches. Crucially, banding is purely **additive** — it cannot remove a trace OpenMS would find. If the benchmark shows a peptide *deficit*, banding is not your cause; if anything it inflates (and can perturb FDR/feature linking via duplicates).

  ## 5. Speed

  The old 9:28 causes (per-band prep rebuild, a sqrt per *visited* peak) are genuinely gone. What remains above OpenMS's per-step cost:

  - **L81–83**: three calibration evaluations per frame-step (`tofOf` ×2 + `mzToTof` ×1) versus OpenMS's two binary searches over doubles. If the calibration is sqrt-based that's ~3 transcendentals per visited spectrum per direction. Unavoidable in the bin-walk design, but check that `tofOf`/`mzToTof` are closed-form and not hiding a lookup or iteration.
  - **L53/104/128**: one `mzOf` per accepted peak and per seed — OpenMS does zero conversions (it reads doubles). Small.
  - **Band-seam duplicate tracing** (§4): every straddling feature is traced, validated, and EPD'd twice or more. Additive, bounded, but on boundary-dense data this is real work OpenMS never does.
  - Per-band full scan of `tp.order` (12 × |order| cheap integer compares) and the per-band `visited(P)` alloc — negligible.

  Nothing asymptotic remains; at equal output this should be at parity with OpenMS's detector. If it still measures slow, profile the calibration call — that's the only per-step cost OpenMS doesn't have.

  ## Verdict

  The tracing loop itself — interleaving, guards, counters, double-counted seed, closest-then-reject, IM-inside-search, member filtering, SD re-estimation ordering, outlier termination, validity accounting — is now faithful to the OpenMS excerpts. What remains is (a) quantization-domain differences at every threshold and comparison (intensity, m/z-bin, IM), of which **integer-truncated intensities at the noise/SNR gates (1a) is the only one with a systematic deficit direction**, and (b) additive banding duplicates. If the detector were run unbanded with float-faithful intensity thresholds, I'd expect residual peptide-count differences of order a percent or two, dominated by edge-bin/tie-break coin flips and with a slight *positive* bias from seam duplicates. A deficit larger than that points at intensity quantization or the calibration/`tofOf` edge behavior, not at the tracing logic.

