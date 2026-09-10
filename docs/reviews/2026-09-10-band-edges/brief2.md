# Adversarial review, round 2: the step-3a fix-up (HEAD, "Band edges, review fixes")

Scope: `git show HEAD` (parent 1641a00, reviewed in brief.md / codex.md / kimi.md). Files:
src/TdfLoad.h (`TdfAxisBounds`, `loadTdfAxisBounds`), src/spextractor.cpp (`TofAxis::n_bins`,
`bounds_why`; the preflight before the load; the `wbands` block; `bandOf`; the per-cell superset
assert; the stamp; the TileProbe conflict), src/MzPeakStreamLoad.h.

What the first round found and this commit claims to fix: (1) the acquisition `thi` was the
MzAcqRangeUpper conversion, not a guaranteed bound on peak bins; with one cell the superset assert
was skipped and `bandOf` could index out of bounds -> now `thi = max(DigitizerNumSamples - 1,
the conversion)`, `bandOf` clamps at both ends, the assert runs in every mode; (2) TEXT parsing of
GlobalMetadata (NULL, junk, inf) -> strict strtod, finite, ordered, a reason string; (3) the
refusal came after the load -> a preflight before the load for .d/sidecar inputs; (4) the
SPEXTRACTOR_WINDOW_FILE override under acquisition -> refused; (5) the stamp records what was
applied. Measured on D (chain step3a, 1641a00): every window's acquisition thi = 634,072 =
DigitizerNumSamples - 1 (634,073 - 1), so the fix-up's edges on D are the first version's; D
acquisition re-pins `8c1b047f`, Sage 13,491 vs 13,490, entrapment 1.30% both.

Attack: is `DigitizerNumSamples - 1` truly an upper bound on every bin `toTof()` can produce
(the m/z quantum round trip `llround(mz * 1e5)` then `tofOf` `llround`; a raw peak at the last
bin; `tofOf`'s clamp)? Is the `max(...)` with the MzAcqRangeUpper conversion ever LARGER than the
digitizer bound in a way that matters (an empty sliver above the last bin -- harmless?)? The
strict parser: `strtod` on "1700.000000" with locale; a Value of "634073" for n_bins through
strtod -> (long); `seen < 3` when a key appears twice; `n_bins > 1e8` guard. The preflight:
runs for `trace:detector=integer` only -- what if the detector later falls back to openms (the
option then stamps... what?); the mzPeak path's refusal timing. `bandOf`'s clamp vs the
detector's own band range test for a clamped seed (never seeded -- silently?). The assert now
also runs with one cell in slab mode: can it ever fire there (tlo/thi are the slab's own
extremes)? Thread safety unchanged? The stamp for `trace:detector=openms`.

Report: numbered findings with severity, file:line, scenario, fix; then what was checked and
found sound.
