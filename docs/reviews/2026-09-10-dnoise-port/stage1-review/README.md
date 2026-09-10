# Stage-1 review: the exact dnoise MS1 port and the output-identical MS1 prune (2026-09-10)

Reviewed on a frozen snapshot of the stage-1 code (`src/DnoiseMs1.h`, the prune and tile-trim probe in
`src/spextractor.cpp`, e2e check 19). All three reviewers ran on the self-contained brief
(`brief-selfcontained.md`, 112 KB): codex 8.9 KB, kimi 13.7 KB, vibe 6.9 KB, none silent. Eight read-only
verifiers then checked every finding against the snapshot, the OpenMS sources actually built and probes on the
cluster. Full verdicts, evidence and fixes are in `verification.md`.

## Confirmed or partly confirmed: to fix

| # | finding | severity | fix |
|---:|---|---|---|
| 1 | `MSSpectrum::select` right-sizes the peaks but leaves the float data arrays at their old capacity (`MSSpectrum.cpp:49`), so a pruned spectrum still holds its Ion Mobility array's capacity for every picked peak (codex 7, kimi 6) | medium | `shrink_to_fit` the data arrays after `select`; correct the "right-sized buffers" comment |
| 2 | the prune builds an index vector even for frames it removes nothing from; `select` holds a transient copy (codex 7) | low | count kept peaks first and skip frames with nothing to prune |
| 3 | a stream attempt that adds MS1 spectra and then fails leaves them in the map, so the resident fallback now stops at the prune's precondition (codex 3; reproduced with a window row whose IsolationMz is 0) | low | before the resident load, reset the map, the window stores, the compact stats, the prune state and the ledger rows |
| 4 | check 19 does not isolate the interior witness chain, and its negative assertion accepts "traces OR bands differ" (codex 6) | low | a `SPEXTRACTOR_MS1_PRUNE_NO_CHAIN` control that drops only interior chain links; assert the exact trace and precursor change |
| 5 | the streaming-side prune has no in-repo e2e coverage (kimi 5) | low | not possible without a redistributable `.d`; say so in the test, keep the real-data digest gates |
| 6 | `parseF64` refuses inf/nan/overflow/underflow that Rust accepts (codex 1, kimi 7); the `__cpp_lib_to_chars` branch is unnecessary risk | low | one classic-locale stream path everywhere, a library-independent range check, and a documented finite-metadata contract |
| 7 | the contraction guards do not cover -ffast-math, finite-math or x87 excess precision (codex 2) | low | `#error` under `__FAST_MATH__`, `__FINITE_MATH_ONLY__`, `_M_FP_FAST` or `FLT_EVAL_METHOD != 0` |
| 8 | `denoiseMs1Frame` can wrap `num_scans + 1` or a scan index near 2^32, and checks the point count after allocating (codex 4) | low | reject `n` and `num_scans` above 2^32-1 before any allocation |
| 9 | a non-finite m/z would be dropped by the witness chain (vibe 5) | low | leave a frame with any non-finite m/z unpruned and count it |
| 10 | the dnoise unit test is built only in the OpenMS-free CI build (kimi 9) | low | compile and run it in the cluster build before `make spextractor` |
| 11 | an exception from the new `[det]` code under the MS1 tracing call can escape an OpenMP region (codex 8) | low | catch inside the `single` block, rethrow after the region |

## Refuted

- **kimi 2**, "the prune samples band edges in a different order than before". `ms1_map.sortSpectra()` sorts every
  spectrum by m/z before MS1 tracing on every path, and the loaders sort too. A probe that stored every MS1
  spectrum in descending m/z order gave identical digests, edges and `[det]` lines with the prune off and on.
- **vibe 3**, "apply the resident predicate to the streaming prune". This would make every streamed `.d` with an
  empty MS1 frame fail the prune's precondition. The two predicates each match their own path's dispatch.
- **kimi 4**, "an out-of-range gate box is folded onto the last scan". dnoise's `dia_ms1.rs` does the same, and
  the port is faithful.
- **vibe 4**, "the prune over-keeps a gap anchor". A band range can contain only that peak; dropping it breaks
  band membership.
- **vibe 1**, "contraction beyond the guarded product". Only multiply-add shapes can be fused, and the only one in
  the gate builder is guarded.
- **kimi 3**, "the volatile alone is unmeasured". It was measured: volatile only, 0 differences with g++-13 -O3
  -ffp-contract=fast -march=native, and protected under Apple clang and g++-16.
- **kimi 8**, "the prune hop can contract". It is benign: the proof has a factor-2 margin, and prune on and off
  are built with the same flags.
