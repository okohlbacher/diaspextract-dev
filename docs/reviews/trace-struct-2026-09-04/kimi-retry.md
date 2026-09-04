• # Hostile review: TRACE-STRUCT-REDESIGN.md

  Verdict up front: the compaction arithmetic is sound, but the claim "this is pure representation" is false as written. I count at least five independent semantic changes hiding inside the accessor table, each sufficient to break the stated falsifier. Details per question.

  ## 1. "One degree of freedom per point" — refuted

  The claim survives for `buildFragGrid` and the scorer's fragment dot product, but fails for these consumers:

  - **`splitIntegerTraces` / export (per-point bin).** The design asserts "the apex's measured bin IS `tof`" (§3 table) and dismisses `xt` because "EPD ignores per-peak m/z" (§5). That answers the wrong question. The struct comment at lines 249–253 states `xt` exists so that a *split child's reported spectrum m/z* under the default `apex` estimator is the measured apex m/z, not the parent centroid — a fix landed 2026-09-03, one day before this design. EPD ignoring per-peak m/z for its *splitting decision* is irrelevant; the export path writes the child's apex m/z. The proposed fix — "take the apex bin from the PARENT's slab lookup" — only works if the bin is provably constant along every trace. If it is constant, yesterday's `xt` fix was dead code and should be reverted with that evidence; if it is not, deleting `xt` reintroduces the exact systematic bias it fixed. The design cannot have it both ways and presents no measurement either way.
  - **`atrousLevels` (per-point validity).** Lines 1285–1289 build the gap multiset from *consecutive present points*; a 5-frame hole contributes one large gap entry, and the comment at line 1292 says the median is used precisely because "gaps are heavy-tailed." In the dense representation holes become unit steps, the heavy tail vanishes, `dt` shrinks, `want = scale_sec / dt` grows, and the level count changes. The needed per-point datum — "is this frame real or padding" — is not `frame0+i`.
  - **Wavelet smoothing (per-point sampling).** Lines 2105–2110 smooth the present-point intensity sequence. À trous is a convolution: smoothing a zero-filled span is *not* the same operator as smoothing the gapped sequence (zero-fill is arguably more correct, since à trous assumes uniform sampling — which means the redesign silently "fixes" an undocumented behavior and breaks identity). The smoothed values then feed `pdense` at line 2116, so every downstream score moves whenever `wl_scale_ > 0`.
  - **`xicCorr` (pairwise presence).** Lines 1754–1758 intersect the *present-point sets* of both traces. The needed datum is per-point presence on two traces simultaneously, not two intervals. See Q2.
  - **FWHM**: a zero inside the span is a false valley below half-max; width computed over the dense span shrinks or splits. Needs the real-point sequence.
  - **Scorer scatter (cross-axis frame).** Line 2114 indexes `fg.nearest_slot[p_tr.xi[pi]]` with a *global axis* frame. The per-point frame is still `frame0+i`, but only in the MS1 map's local domain — the mapping to the MS2 slot is a table lookup, not arithmetic. See Q3.

  ## 2. Zero-padding: consumer by consumer

  | consumer | does a zero entry change the value? | fix |
  |---|---|---|
  | `dot` (2161–2162) | No — `pv * 0 == 0` — *if* the loop keeps the `pv != 0` guard | none, but the "no branch, two streams" claim in §4 dies: you still need `av != 0` for overlap, so the branch stays |
  | `overlap` (2162–2163) | **Yes.** Current code increments only on visited (present) fragment points with `pv != 0`. A padding frame with `pv != 0` and `av == 0` increments `overlap` unless explicitly skipped. §4's "skipping arena == 0 preserves overlap exactly" is correct but is a branch the "contiguous walk" framing omits | `if (pv != 0.0f && av != 0.0f)` |
  | `touched` (2116–2118) | **Yes, and it's a duplicate-counting bug.** A zero-pval gap frame with `pdense[gi]==0` pushes `gi` without changing `pdense`; a later real frame mapping to the same `gi` pushes it *again*, and the loop at 2121–2125 then counts that slot's intensity twice in `psum`/`psumsq`/`plogsum` | `if (pval == 0) continue` in the scatter — which also requires wavelet output at gap frames to be excluded, see below |
  | `fg.mean` / `fg.invnorm` (1355–1357) | Sums: unchanged. **Values: changed**, because `G` is redefined (next row). `var = sumsq − G·mean²` with a different `G` is a different number | keep `G` as the count of *signal-bearing* frames (cheap: a 1,400-entry bitmask over the window, not the deleted 33,553-entry global pass) |
  | `G` (1318) | **Yes.** Old `G` = size of the union of used frames (line 1318); new `G` = window frame count `F`. Pearson at 2124 (`pmean = psum/G`, `pvar = …`) and `fg.mean[i] = sum/G` (1355) both change → scores change → threshold decisions flip. §2's "sums are unaffected by zeros" is true and beside the point: the *divisor* moves | retain the union-count semantics, or admit the digest gate fails on every Pearson-path run |
  | `atrousLevels` (1281–1293) | **Yes**, per Q1: the gap multiset, the median `dt`, and the `np() < 5` guard (line 1281: `np` becomes `len`, so a 2-point trace spanning 10 frames now passes) | compute gaps and the guard over nonzero entries only |
  | `xicCorr` (1754–1761) | **Yes.** At a frame where `a` is padded and `b` has signal, the aligned dot adds `y` to `sy`/`syy` and increments `m`; the merge at 1754–1758 excludes that frame entirely. Mean-centring is over a different set, so the correlation value differs, and the `m < 3` guard (1761) can flip | accumulate only where `av != 0 && bv != 0`; count `m` on the same condition |
  | FWHM / wavelet | **Yes** (false valleys; convolution over zeros) | iterate real points for FWHM; for the wavelet there is no cheap fix — smoothing *must* run on the present-point sequence to reproduce current output, which means keeping a present-point index list for MS1 traces, i.e. reintroducing `xi` by the back door whenever `wl_scale_ > 0` |

  Additionally: "zero = missing" conflates a gap with a genuine zero-intensity measurement. Probably safe for detector output, but it is an unasserted invariant, and §5's own table is where such invariants belong.

  ## 3. MS1↔MS2 alignment

  The break is at line 2114. Today `nearest_slot` is indexed by **global axis position** (`na = rtAxis().size()`, line 1309; assignment loop 1331–1344), and the query key is the precursor's global frame. In the redesign, precursor frames are MS1-map-local and fragment slots are window-local, so:

  - The required table is `nearest_slot[ms1_local_frame] → window_local_slot`, built by RT-matching each of the ~1,343 MS1 frames against the window's frame RTs within `delta_rt`, preserving the documented tie-break ("ties go to the LATER slot", line 1327) and the `<=` comparisons at 1339/1343 exactly.
  - §4 says the table is "indexed by window-local frame — ~1,400 entries." That is the **wrong index domain**: the lookup key is an MS1 frame, not a window frame. As specified, the table cannot serve the scatter at all. (A table indexed by MS1-local frame, sized ~1,343, is what's needed — per window.)
  - Accessors must also pick the right slab context: `sl.b[frame0+apex]` and `rt_index` for a precursor mean the **MS1** slab's `b`/`rt_index`; for a fragment, the **window** slab's. §3's table shows one undifferentiated `sl`, and the `Precursor_` path (lines 262–263) recomputes reported m/z from `(mono_tof, mono_b)` — `mono_b` must come from the MS1 slab, or precursor m/z silently picks up a window's calibration factor.

  ## 4. The padding bound, corrected

  The detector accepts a trace when `points/span >= r` over its span. Dense storage is `4·span` bytes, so:

  **bytes per real point ≤ 4/r; padding fraction ≤ 1 − r.**

  "At most half the entries are padding" and "8 B per real point" are the special case `r = 0.5`, and only because the span is the detector's own span. Consequences the design doesn't state:

  - Against the **integer** path's 12 B/point, dense wins only when `r > 1/3`.
  - Against the **OpenMS** path's 8 B/point (no `xt` there — lines 250–251 say `xt` is set *only* by the integer detector), dense at `r = 0.5` merely **ties** on point bytes. The entire OpenMS-path win is the struct and the three mallocs, not the profile. §3's "4× smaller" averages over this; the per-path honesty is missing.
  - If `min_sample_rate` is user-configurable below 0.5, the bound degrades accordingly and should be stated as `4/r`, not as a constant 8.

  ## 5. Byte-identical digest: no, not by construction

  Independent identity-breakers, in decreasing severity:

  1. **`rt` and `im` are not "caches."** `toTrace` sets `t.rt = mt.getCentroidRT()` and `t.im = mt.getCentroidIM()` (lines 300–301) — intensity-weighted centroids. The accessor table replaces them with the **apex frame's** RT ("two loads") and a **quantized** IM (`IM_LO + imq/IM_Q`). Both feed gates: `fabs(frag_rt[fi] - pc.rt) > delta_rt` (line 2130) and the `frag_im` window at 2128–2129. Centroid ≠ apex, and quantization shifts values by up to ±IM_Q/2; gate decisions at the boundary flip. `im` is worse: the per-point IM needed to *recompute* the centroid is stored nowhere, so `imq` is genuinely lossy — this is a deletion, not a compaction.
  2. **`mz` is not recomputable for the OpenMS path.** For estimators `mean`/`median` (lines 290–292) `t.mz` is a real-valued centroid, not `mzOf(uint32 bin, b)`. "Both detectors then produce the SAME structure" (§4) forces OpenMS-path fragment m/z through bin quantization, which moves the `[M-7]` and isotope-exclusion comparisons at 2135–2143 (0.01 tolerance) and the exported values. Digest breaks unless estimator=apex *and* the apex peak's measured m/z equals the calibration call exactly — true by construction only in the integer path.
  3. **`G` redefinition** (Q2) breaks every Pearson-path score.
  4. **Wavelet over zero-fill** (Q1) breaks all runs with `wl_scale_ > 0`.
  5. **`xt` removal** (Q1) breaks split-trace apex m/z unless per-trace bin constancy is proven — the design asserts "within tolerance" against a code comment, dated the previous day, asserting the opposite.
  6. Fixable-but-required: scatter zero-skip (Q2 `touched`), `xicCorr` pairwise-nonzero, `atrousLevels`/FWHM over real points, `nearest_slot` re-indexing with exact tie-breaks.

  **Tightest achievable gate.** Digest-identical on: integer path only, `wl_scale_ = 0`, `G` kept as signal-frame count (retain a per-window bitmask pass), scatter/xicCorr/atrousLevels/FWHM zero-discipline applied, `nearest_slot` rebuilt with bit-exact tie-breaking, and either (a) per-trace bin constancy *measured* on S30 and asserted, or (b) a per-split-child apex bin retained (children are few — this is cheap and keeps yesterday's fix). Even then, `rt`/`im` for the integer detector must be verified: if the integer detector also stores centroids, the apex-RT accessor changes the RT gate and the gate fails anyway; the honest fix is keeping centroid `rt`/`im` as two doubles (16 B back — 74 B becomes 90 B, still ≈3× better). For the OpenMS path and `wl_scale_ > 0`, byte-identity is unreachable; the honest gate there is statistical: identical spectrum *count* plus bounded score drift (quantile report), acknowledging that threshold discontinuity makes ε-drift flip borderline spectra. The current §5 falsifier ("digest IDENTICAL … any difference is a bug") will fail on first run and teach nothing, because §4 as written guarantees differences.

  ## 6. What else to delete, and what it breaks

  - **`b` (the per-trace double)** — already deleted by the design; correct, it's `sl.b[frame0+apex]` in the right slab. Breaks nothing if Q3's slab discipline is enforced.
  - **`mz`** — deletable *only* for the integer path with estimator=apex. Breaks OpenMS-path `mean`/`median` estimators and every m/z gate otherwise (Q5.2).
  - **`rt`, `im`** — deletable only if you accept apex-RT and quantized-IM semantics, i.e. you accept the digest gate failing. Keeping them as centroids is the price of the design's own falsifier. The design currently tries to have both; it can't.
  - **`intensity`** — genuinely derivable as `arena[off+apex]` **iff** `apex` is defined as the argmax and tie-breaking matches `findMaxByIntPeak(false)` (line 290). Assert the tie rule; otherwise export intensity can pick a different equal-maximum point than the m/z did.
  - **`apex` itself** — deletable by scanning the span for the max at conversion time; saves 2 B, breaks nothing if the tie rule above is fixed. Marginal.
  - **`tof` for unsplit traces** — must stay; export needs it (lines 262–263).
  - **`len` as uint16** — fine on a 1,400-frame gradient; the §5 assert is right, but make it a hard abort at *detector* time, not at arena-write time, or a pathological trace corrupts `off` rebasing for the whole window before anyone notices.

  ### Bottom line

  The memory story (296 B → 74–90 B, 3 mallocs → 0, FragGrid's 1.7 GB and one pass) is real and worth doing. But the document's load-bearing claim — "pure representation, digest-identical" — is refuted by its own accessor table: `rt` and `im` change semantics, `mz` is unrepresentable for two of three estimators, `G` is silently redefined, the wavelet sees a different signal, and `xt`'s deletion contradicts a one-day-old fix on the say-so of "within tolerance." Rewrite §4 with the zero-discipline fixes above, rescope the falsifier to the integer path with `wl_scale_=0`, add the bin-constancy measurement as a *precondition*, and present the OpenMS-path result as statistical equivalence — or keep centroid `rt`/`im` and per-child bins and pay the ~20 B.

