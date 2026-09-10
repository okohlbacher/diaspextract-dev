• Now let me look at the surrounding code — the load path, the detector's band logic, and the tile loop:

• Let me look at the band bounds construction and the detector call site, plus the cell/assert code in the tile loop:

• Now checking a few remaining details — other `prepareTracing` callers, `setlocale`, the `wslab` provenance, and `TileProbe`:

• Let me check whether the tile loop containing the assert runs under OpenMP, and glance at `TileProbe::row` and the `loadTdfCalibration` error path:

• I have the full picture now. Let me pin exact line numbers in the current `TdfLoad.h`:

• # Adversarial review, round 2 — dde035e "Band edges, review fixes"

  ## Findings

  **1. MEDIUM — `mz_hi` magnitude is unvalidated; the strict parser admits values that make `tofOf` truncate or hit UB.**
  `src/TdfLoad.h:62` checks only `mz_hi > mz_lo` and finiteness. But `mz_hi` goes straight into `tofOf(acq_hi, b)` (`src/spextractor.cpp:4291`), and `mzToTof`/`tofOf` have no top clamp (`src/spextractor.cpp:650-654`, `src/TdfMzCalibration.h:118-123`):
  - `mz_hi ≈ 1e10–1e12` → `t` exceeds 2³² → `(TofIdx)llround(t)` truncates mod 2³² → `thi_mz` is garbage. If garbage < `n_bins-1`, the corrupt value is silently ignored; if garbage > `n_bins-1`, `thi` is up to ~4.3e9, every real peak lands in band 0, and the partition is degenerate with no warning. If garbage lands exactly on `UINT32_MAX`, `bnd[nb] = thi+1` wraps to 0 (`src/spextractor.cpp:4586`) and `bnd` is no longer sorted — `upper_bound` in `bandOf` is then UB-by-contract (still memory-safe thanks to the clamp, but the partition is meaningless and the superset assert passes because `chi ≤ thi`).
  - `mz_hi ≳ 1e20` (with C2 ≈ 1e-3) or ≈ 1e27 (C2 = 0) → `llround(t)` itself overflows `long` → hard UB.

  Scenario: corrupt or adversarial GlobalMetadata that still parses as finite and ordered — precisely the input class this commit set out to distrust. Probability low (the file is instrument-written), impact up to silent degenerate banding.
  Fix: bound the range in `loadTdfAxisBounds`, e.g. refuse `mz_hi > 1e5` (any real TIMS acquisition is ≤ ~3000); or clamp `t` in `tofOf` before `llround`.

  **2. LOW-MEDIUM — preflight and load disagree about candidate semantics; a usable sidecar is never consulted for bounds.**
  Preflight (`src/spextractor.cpp:3339-3343`) passes if **any** candidate provides bounds. The load (`src/spextractor.cpp:4152-4157`) breaks on the **first candidate whose calibration loads**, and `loadTofAxis` (`src/spextractor.cpp:695-697`) takes bounds only from that same file. Scenario: `.d/analysis.tdf` has a valid MzCalibration but no `DigitizerNumSamples` (older tdf schema), and `SPEXTRACTOR_MZPEAK_TDF` points at a complete tdf. Preflight passes via the sidecar; the load binds to the `.d` (calibration OK, bounds missing → `n_bins = 0`); the run then dies at the post-load throw (`src/spextractor.cpp:4268`) — after minutes of loading, which is exactly what the preflight was added to avoid, and despite a sidecar that could have supplied the bounds.
  Fix: when the calibration source's bounds parse fails, try the remaining candidates for bounds before giving up (or make the preflight validate only the candidate that will actually supply the calibration).

  **3. LOW — the `SPEXTRACTOR_WINDOW_FILE` conflict throw is post-load.**
  `src/spextractor.cpp:4271-4273` sits in the `wbands` block, after the load. It's a pure option×env check, detectable in milliseconds; a user combining the two pays a full load to be told. Fix: hoist it into the preflight block at `src/spextractor.cpp:3332` (which is also where the message's "(a slab-mode probe)" rationale belongs).

  **4. LOW — mzPeak refusal is still post-load.**
  Preflight is skipped for `FileTypes::MZPEAK` (`src/spextractor.cpp:3334-3336`), so an archive without usable embedded bounds loads fully before the `src/spextractor.cpp:4268` throw. The comment is honest about this, but the bounds could be read pre-load by peeking `vendor/analysis.tdf.gz` from the zip (`readMember_` + the existing gunzip, `src/MzPeakStreamLoad.h:121-143`) — no peak data needed.

  **5. NIT — duplicate GlobalMetadata keys: `seen` counts rows, last duplicate wins silently.**
  `src/TdfLoad.h:51-57`: `seen < 3` counts rows, not distinct keys. Two `MzAcqRangeUpper` rows with different values → the later silently wins (the tdf schema doesn't enforce key uniqueness). Every *missing*-key shape is still caught by the value checks (defaults are 0, refused by `src/TdfLoad.h:62`), so this is only the duplicate-with-conflict case. Fix if paranoid: refuse when a key repeats.

  **6. NIT — strictness holes in `num`: fractional `DigitizerNumSamples`, hex/scientific/whitespace.**
  `src/TdfLoad.h:45-56`: `"634073.9"` parses and truncates to 634073 via `(long)v`; `strtod` also accepts `"0x..."` hex floats, `"6.34e5"`, and leading whitespace. All harmless for instrument-written values, but "strict" is the stated contract; a fractional sample count should arguably refuse (`v != floor(v)`).

  **7. OBSERVATION — preflight converts the fail-open detector fallback into a hard refusal.**
  With `trace:detector=integer` + `band_edges=acquisition` + an input with no tdf at all (plain mzML, no sidecar), the preflight throws before the load, whereas the same run without `acquisition` would warn and fall back to the openms detector (`src/spextractor.cpp:4189-4202`, whose comment says "FALL BACK, do not refuse"). Defensible — the user explicitly requested edges the fallback can't provide — but it's a behavior change worth stating in the option help, and the error could mention `-trace:detector openms` as the escape.

  ## Checked and found sound

  - **`DigitizerNumSamples - 1` as an absolute bin bound.** A vendor peak IS a bin `< n_bins` by construction; the m/z quantum round trip (`llround(mz·1e5)` → `tofOf`'s `llround`) is exact because the 1e-5 Da quantum is ~500× finer than one bin at the top of the axis on D (error ≈ 1e-3 bins ≪ 0.5; the margin only collapses if the last bin's m/z is below ~`n_bins × 1e-5` ≈ 6 Da — nonphysical for TIMS). Centroids/aggregates are intensity-weighted means of per-bin m/z values, so they can never exceed the last bin's m/z. The identity requires the same calibration both directions, which the shared header (`src/TdfMzCalibration.h`, installed into the loader by the patch) guarantees; the 2.5e-5 ppm vendor discrepancy is ~0.016 bins. A raw peak at the last bin round-trips to exactly `n_bins - 1`.
  - **The `max(...)` exceeding the digitizer bound: harmless.** If `MzAcqRangeUpper` converts above the last bin, `thi` sits above all data — an empty top sliver; the assert still holds, `bandOf`'s clamp stays dead, and the partition is deterministic, logged, and stamped. That case aside, finding 1 covers the corrupt-magnitude case.
  - **`tofOf`'s clamp.** Bottom-only (`t > 0 ? llround : 0`) with NaN → 0 via the `t > 0.0` test — correct for `tlo = 0`; the top end is covered by the digitizer bound plus the assert.
  - **Strict parser mechanics.** NULL → refuse; `""`/whitespace-only → refuse (`end == txt`); trailing garbage → refuse (`*end != '\0'`); inf/nan → refuse; unordered/zero/negative/absurd `n_bins` → refuse; missing keys → refuse (value checks catch the zero defaults, so `seen < 3` is redundant but harmless); prepare failure → "no GlobalMetadata table"; `sqlite3_finalize(nullptr)` is a safe no-op; db closed on every path. `strtod` is C-locale-sensitive, but nothing in the process calls `setlocale`, so `"1700.000000"` parses as intended — fragile only if the code is ever linked into something that sets a comma-decimal locale, and it fails closed in that case.
  - **`bandOf` clamp vs the detector's range test.** `bnd[nb] = thi + 1` (`src/spextractor.cpp:4586`) keeps the partition total and the `upper_bound` segmentation consistent with the detector's `[band_lo, band_hi)` seed test (`src/spextractor.cpp:1244`). A clamped seed would be counted into band 0/nb−1's segment but silently skipped by the range test — but that is unreachable: the superset assert (`src/spextractor.cpp:4626-4634`) precedes the only `prepareTracing` call site, and an empty `cs` runs zero peaks.
  - **The one-cell assert in slab mode cannot fire.** `wbands` slab extremes are computed over `*window_list[i].second` (`src/spextractor.cpp:4280-4283`), and the tile loop's `wslab` is that same slab, moved (`src/spextractor.cpp:4492`); cells are slices of it, tile slices are subsets of it — `clo ≥ tlo`, `chi ≤ thi` by construction. It CAN fire where it should: TileProbe-frozen edges and acquisition mode with non-vendor-bounded inputs (mzML+sidecar, third-party mzPeak archives whose two-point transform recovers bins above `n_bins`). The throw is inside an omp task but is captured into `worker_err` and rethrown on the main thread (`src/spextractor.cpp:4977-4983`) — loud, clean, no cross-thread terminate.
  - **Preflight vs load candidate lists** are identical in content and order (`in + "/analysis.tdf"`, then `SPEXTRACTOR_MZPEAK_TDF`) — no false refusals; the only divergence is finding 2's any-vs-first semantics.
  - **mzPeak propagation.** `n_bins`/`bounds_why` flow from the embedded/sidecar tdf through `lastMzPeakExact()` into the axis (`src/MzPeakStreamLoad.h:141-142` → `src/spextractor.cpp:4163-4165`), and requiring all three keys (dropping the old two-key `loadTdfAcqRange` behavior for archives lacking `DigitizerNumSamples`) is correct since acquisition mode needs `n_bins` anyway; slab mode just loses the side-by-side log line, with the reason logged.
  - **The stamp.** `spx:band_edges` uses the *resolved* `integer_detector` (`src/spextractor.cpp:4336`), so an openms fallback stamps `"none"` and the integer detector stamps the applied mode; `SPEXTRACTOR_WINDOW_FILE_OUT` rows record the edges actually used (`w_tlo/w_thi`, `src/spextractor.cpp:4570`). `trace:detector=openms` + `band_edges=acquisition` is silently ignored but attributable via the stamp.
  - **WINDOW_FILE under acquisition** is doubly dead: refused at `src/spextractor.cpp:4271` and the `TileProbe::row` override is gated on `!band_edges_acq` (`src/spextractor.cpp:4569`).
  - **Thread safety unchanged.** All new state (`n_bins`, `bounds_why`, `acq_*`) is written single-threaded before the parallel `wbands` loop; the loop adds only per-iteration locals plus read-only `tofAxis()`/`frozen.at(k)` access; `wbands` is pre-keyed then only `.at()`-read; `winlog` stays under `#pragma omp critical`. The preflight is strictly before the load.
  - **`thi + 1` overflow** is unreachable from the digitizer side (`n_bins ≤ 1e8` guard); only finding 1's corrupt `mz_hi` can approach it.

  Net: the five claimed fixes all do what the commit message says, and the `DigitizerNumSamples - 1` bound is genuinely absolute for vendor-origin peaks. The one thing I'd fix before calling the parser "strict" is finding 1 (bound `mz_hi`'s magnitude — one comparison closes truncation, the unsorted-`bnd` wrap, and the `llround` UB in a single check); finding 2 is the only place the new preflight still lets a refusal slip past the load.

