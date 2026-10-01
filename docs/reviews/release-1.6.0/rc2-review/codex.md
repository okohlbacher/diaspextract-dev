Static review only; no files changed and no builds or tests run. I found two high-severity issues. The stated header-inclusive reset digest is contradicted by the code.

1. **High — `src/diaspextract.cpp:7451`, `:7494`, `:6617` — pipeline progress depends on FIFO task scheduling.**

   Writer tasks block while waiting for earlier writers; carry consumers similarly block waiting for earlier windows. These waits cannot execute ordinary queued tasks. OpenMP does not guarantee the FIFO ordering assumed by the comment.

   **Failing execution:** with two threads and three tiles, finish tiles 0 and 1’s windows, then queue writer 0, tile 2’s windows, and writer 1. If the worker starts writer 1 first, it waits for writer 0. The driver waits for tile 2’s windows. Both prerequisites remain queued; `teamAssist_` cannot run them.

   **Exposure:** ordinary data; runtime/scheduling dependent. This establishes a portability failure, not a demonstrated hang on the tested libgomp configuration.  
   **Fix changes default output:** **no**, for executions that currently finish.

2. **High — `src/diaspextract.cpp:6338`, `:6687` — the six-option reset does not restore the 1.5.0 header.**

   The auto twin description is generated without checking whether v2 is enabled. Disabling v2 prevents `mono_ext` marks and cross-frame links, but still writes `"MS1 frames up to ..."` rather than `"same frame..."`.

   **Failing input:** any ordinary positive-cycle run with the six reset options. Its `spx:twin_merge` differs from 1.5.0 even when every spectrum matches.

   **Exposure:** systematic for that reset. The reported digest equality can hold only if the comparison excludes/normalizes this stamp, or the tested configuration differs from the stated one.  
   **Fix changes default output:** **no**, if confined to making the inaccessible `ext` mode inert when v2 is disabled.

3. **Medium — `src/diaspextract.cpp:3750`, `:3772` — isotope controls can count genuine isotopes as background.**

   The ±50 ppm controls are not isotope-free across the tested charges. At m/z 1000, the genuine z=4 M+1 is `1000.2508387`; the z=5 positive control is `1000.25068099348`. Their separation is only `0.00015770652 Da`, inside the default `0.015 Da` search window. That genuine isotope contributes both +1 signal and −1 control.

   **Failing input:** four co-RT traces, arranged as two isolated pairs:

   | Seed m/z | Partner m/z | IM gap | Effect |
   |---|---|---:|---|
   | 600 | `(600 + ISO/2) × 1.00005` | 0.0304 | One background-control hit from grid point 0.031 |
   | 1000 | `1000 + ISO/4` | 0.0404 | One genuine isotope hit **and** one control hit from 0.041 |

   The objective is zero through 0.030, then −1 through 0.050. The estimator chooses **0.030**, excluding the genuine partner. Without its contamination of the control count, the objective returns to zero at 0.041 and the wider-tie rule chooses **0.050**.

   **Exposure:** plausible high-m/z, higher-charge envelopes; frequency and corpus impact are unmeasured.  
   **Fix changes default output:** **yes** on this constructed input; unknown on the measured runs.

4. **Medium — `src/diaspextract.cpp:6097`, `:6349` — estimator arithmetic is narrowed without range checks.**

   Minlen converts `ceil(ms1_min_len / cycle)` directly to `int`; out-of-range floating-to-integer conversion is undefined behavior. Twin auto rounds to `long long` and then narrows to `int`, potentially producing an unrelated frame count.

   **Failing inputs:**
   - Normal cycle 1 s, at least 100 bright measured FWHMs of 10 s, and the permitted `-trace:min_length_fwhm 1e308`: multiplication becomes infinity before the integer conversion.
   - Otherwise ordinary frame times containing one near-duplicate positive gap of `1e-9` s: `frameSpacing` chooses that gap. A 10 s FWHM gives a twin ratio of `1e10`, outside `int`. The existing cell-grid calculation `600 / cycle` still fits `long long`, so it does not guard this case.

   **Exposure:** extreme options or anomalous timestamps, rather than normal acquisition cadence.  
   **Fix changes default output:** **unknown** for anomalous inputs; no change expected in the ordinary finite range.

5. **Medium — `src/diaspextract.cpp:2407`, `:2560` — the optional MS1 worker introduces data races.**

   With `DIASPEXTRACT_MS1_ASYNC=1`, the worker appends to `ms1_` while the reader’s MS2 flush unconditionally reads `ms1_.size()`. Both threads also update the non-atomic `flush_wall_()` at lines 2437 and 2562.

   **Failing execution:** stream interleaved MS1/MS2 mzPeak data, or use the resident-source `.d` path; launch an MS1 batch, then flush MS2 while the worker appends spectra.

   **Exposure:** reachable in the new opt-in mode. The default `.d` MS1-only first pass avoids this overlap.  
   **Fix changes default output:** **no**; async is off by default.

6. **Low — `src/diaspextract.cpp:4690` — “never below its best piece” is not guaranteed.**

   **Failing input:** with permitted `cap_rank=corr_inten` and `gate:min_correlation=-1`, two admitted nearby fragments with score −1 and weighted apex 100 each have keys −100. Their fused key is −200.

   Positive evidence keys also change floating-point association: the original is `(r × log1p(I)) × q`, while fusion computes `(r × q) × log1p(sum)`. If an additional weighted apex is zero or rounds away, this can reduce the result by an ULP.

   **Exposure:** the clear negative-key example requires nondefault settings; the positive rounding issue is a numerical boundary case.  
   **Fix changes default output:** **unknown** if enforcing the guarantee for rounding cases; fixing only negative keys would not affect defaults.

7. **Low — `src/diaspextract.cpp:6801` — streaming pipelining double-charges the slab ledger.**

   The consumer already adds the loaded slab charge at line 2435. `loadTile` then adds its complete slab size again. Subsequent release subtracts the actual slab once, leaving an accumulating residual.

   **Failing input:** any nonempty streamed, pipelined multi-tile run with ledger diagnostics enabled.

   **Exposure:** real diagnostic error; it can resemble retained slabs. Admission uses available memory, so this does not itself change admission.  
   **Fix changes default output:** **no**.

8. **Low — `src/diaspextract.cpp:151`, `:2645`, `:7482` — new exported comments retain internal labels.**

   Examples introduced in this range include `"scal-pipe-1 on kim"`, `"HeLa_19"`, `"scalfix/outer timing"`, and `"38 pipelined scalfix/integrate runs"`.

   **Failing input:** exporting the source as written; no execution required.  
   **Exposure:** direct violation of the supplied scrub rule.  
   **Fix changes default output:** **no**.

9. **Low — `CHANGELOG.md:134` — the cross-frame time condition omits the half-cycle allowance.**

   It says apexes are “at most n MS1 cycles apart”; the implementation accepts `(n + 0.5) × cycle`. README and help include the actual formula.

   **Failing input:** cycle 1 s, n=2, and an otherwise qualifying pair 2.4 s apart: code accepts it, the CHANGELOG description excludes it.

   **Exposure:** relevant for irregular cadence; documentation only.  
   **Fix changes default output:** **no**.

Answers to the numbered questions:

1. **Fine relative to each platform’s native `std::sort`, for valid inputs.** GNU-13 introsort partitions are disjoint, all descendant tasks finish before final insertion, and ties follow the serial algorithm. Other libraries use native `std::sort`; they are not promised GNU-13’s cross-platform tie order. `parallelSortTotal_` callers have unique index tie-breakers. `sortExact_` sends the untouched original sequence through serial sorting when it detects equivalent keys. `mzOrder_` takes identity only when that order is unique.

2. **Fine semantically, but not literally identical as a sequence of records.** Seed ordering is total. Fragment ordering permits duplicates with different arena offsets, so task counts can permute those records. It compares their profiles and relevant bin/frame content; I found no valid-input semantic difference from those remaining ties. The comment should not be read as proving byte-identical `Trace` ordering.

3. **Fine for thread-dependent chunking.** Chunks write `part[i]`, then gather in spectrum order; changing `nchunk` does not change the sample. The sample sees the already picked/pruned/denoised map after sorting. Dnoise can therefore intentionally change the estimate. Equivalent stream/resident MS1 maps produce the same sample. One qualification: the sample builds its own band quantiles from the pruned map rather than using the full run’s preserved pre-prune sample, so “traced like the run” does not mean identical band boundaries.

4. **Determinism and small-N handling are fine; control validity is F3.** Sampling precedes tiling, results are index-addressed, and reductions count integers. N<2 returns 0.05; below 200,000 traces every trace is probed. Argmax ties choose wider. With no control hits, the objective is monotone and 0.05 wins. The chosen tolerance is used and stamped/logged at its nominal grid precision. Precisely, optimization covers **0.002–0.050 and then clamps**, rather than optimizing only over 0.010–0.050.

5. **The cycle is the run-wide minimum positive consecutive MS1 RT gap**, not the median, mean, or a tile value (`frameSpacing`, line 1826). Zero fails the positive-cycle guard; a hypothetical NaN would too. Positive infinity is not explicitly rejected. Empty precursors or no positive measurable FWHMs give n=1 when the cycle is positive. Both estimators use the upper middle value for even counts. There is no explicit upper clamp; F4 covers unsafe conversions.

6. **Cell ownership and the production survivor rule are fine; transitive over-fold is possible by design.**
   
   `cellOf` uses the same subtraction and strict inequality as tile ownership, on the same `pc.rt` emitted into the spectrum. I found no cell-versus-tile mismatch.

   Survivor ranking is most isotopes, then most peaks, then earliest canonical input position. Calling `mergeTwins_` directly on arbitrary permutations is not permutation-invariant; production supplies the canonical order.

   A concrete mixed cluster, all z=2 and IM=1:

   | Spectrum | RT | m/z | Extension |
   |---|---:|---:|---|
   | A | 10 | 500.005 | no |
   | B | 10 | 500 | no |
   | C | 11 | 500 | yes |

   A–B links at the same frame; B–C links across frames; A–C fails the cross-frame bin test. All three nevertheless fold. Thus `ext` does not ensure every cluster member shares one monoisotope bin. Similarly, three successive-frame spectra at IM 0.996, 1.000, and 1.004, with only the middle one extended, can bridge endpoints beyond the 0.005 IM tolerance. These are plausible false-merge risks, but chaining is explicitly implemented and self-tested, so I have not classified it as an accidental violation of the implemented connected-component rule.

   Counters count qualifying **edges**, including redundant edges, rather than removed spectra. I found no accepted edge whose endpoints remain in separate output clusters. `twin_rt_frames=-1` preserves the old finite-input same-frame relation and survivor/fusion behavior.

7. **Weighting and shared implementation are fine; monotonicity is F6.** Fusion receives the same IM-weighted apex used by unfused ranking, including foreign attenuation. Its sums have fixed m/z order. Pipelining introduces no separate F3 arithmetic. Keyed twin fusion subsequently carries float keys and takes their maximum; that optional precision boundary is separate. Zero additions do not provide a strict increase; NaN inputs have no general monotonicity guarantee.

8. **Ordering, carry ownership, and bounds are fine conditional on progress; progress itself is F1.** Writers serialize through `written`; encoding gathers chunks in index order. Carry publication uses release/acquire, and publishing before scoring is safe because scoring reads private state. No third tile’s processing slabs are admitted at default depth 2 before the oldest tile’s windows finish.

   Finished spectrum buffers can outlive those slabs. Backpressure is bounded, but its “at most depth waiting” comment is off by one: with depth 2 and `written=0`, `fin=2` may still queue writer 2. Read-ahead allocation itself is not preflighted by window admission. `PIPE_TILES=1` restores sequential load/window/write operation. No ordinary exception leak in `teamHelpersQueued_` was found, and `onPipeDriver_` resets after caught driver exits. `malloc_trim` does not invalidate live later-tile allocations.

9. **The merged fold/cap exception handling is fine for ordinary body exceptions; the no-hang guarantee is not.** `teamFor_` catches callback failures, waits for claimed work, and rethrows into the writer catch. Writer failure advances `written`; window exits release admission charges and decrement `left`. The `.part` rename occurs only after successful completion.

   The falsifier does **not** cover the pipelined writer: injection sites are only `ms1_band` and `assemble`. Its synthetic resident/OpenMS fixture does not exercise the pipeline’s writer, fold, cap, or encoding failures.

10. **The normal default stamp count is 29.** Scrub and threshold discrepancies are F8–F9; the reset claim is F2 and isotope-free-control claim is F3. Two wording qualifications also matter: “100 measurable traces” means **100 within the selected brightest tenth**, and the explicit 3 s fallback can be below half a cycle when the cycle exceeds 6 s.

11. **Yes, 12b tests its narrow message; yes, it can pass with broken production cross-frame folding.** It checks an inert fixture, header prefixes, same-frame duplicate folding, and direct helper self-tests. If production stopped setting `spx_mono_ext`, or passed zero RT tolerance while retaining the new header, these fixtures could still pass. Moreover, this test’s `digest()` hashes only `<spectrumList>`; it excludes the header and cannot establish the stated header-inclusive identity.
