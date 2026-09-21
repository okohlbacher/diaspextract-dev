• The diff is in hand. Now I'll dig into the source for the tile-ownership logic, the canonical sort, and the comparison points.

• Now let me check the e2e test fixture (does it contain twins at all?) and whether OpenMS headers are available locally to verify `clear(false)`.

• The fixture for 12b is the default synthetic file — one isolation window, two cleanly separated precursors; I'll note that. Now let me verify `MSSpectrum::clear(bool)` semantics in OpenMS.

• `clear(false)` is confirmed correct. One last check — that the bulk (mzPeak) path also sees the folded `tile_out`.

• All verification is done. Let me do a final quick check on the test's `run()` helper (where logs land) and the `rtOf` snapping claim, then write up.

• Review complete. Everything below is from `git show 2cfc8e1`, the surrounding source at HEAD, `bench/twin_merge.py`, and the pinned OpenMS (`patches/openms.lock` → bd4b895, whose `MSSpectrum.h/.cpp` I fetched to verify `clear(false)`).

  ## Verdict

  The fold itself is sound: I could not construct an input that breaks determinism, crashes, mis-links, or mis-selects a survivor. Two findings worth acting on: the "off = output before 1.4.0" claim is byte-false (header stamp), and e2e 12b reconciles counts on a fixture that contains no twins.

  ## Findings

  **F1 [medium] "−1 = off (the output before 1.4.0)" is not byte-true — the header stamp is unconditional.**
  `src/diaspextract.cpp:4325` writes `spx:twin_merge` into `out_exp` even when `twin_im < 0` (value `"off"`). 1.3.x never wrote that key, and the header is part of the file. Everything else on the off path is correctly guarded: the `MERGE(twins)` phase, the per-tile log and `n_twins` (`src/diaspextract.cpp:4898-4904`), and the summary log (`src/diaspextract.cpp:4969`). Concrete failing input: any run with `-assembly:twin_im_tolerance -1` — its header carries `spx:twin_merge="off"`, so its digest differs from the stored 1.3.x output. This bites on real data if any gate proves off-equivalence by digest-comparing 1.4.0(-1) against 1.3.x. Note the internal contradiction: e2e 12b *requires* the off stamp (`test/test_diaspextract.py:452`), while CHANGELOG.md:34, the help text (`src/diaspextract.cpp:2231`) and the commit message claim the pre-1.4.0 output. Either guard the stamp behind `twin_im >= 0.0` or reword the claim to "same spectra as before 1.4.0". (The spectra themselves are identical; this is one header line.)

  **F2 [low-medium] e2e 12b passes vacuously on the fold itself.**
  `test/test_diaspextract.py:441-454`. The default fixture has one isolation window, and check 1 pins that each envelope yields exactly one precursor — so there are no twins, `folded` is 0, and `n(off) - n(on) == folded` holds as `0 == 0`. Worse, the assert only reconciles the logged count with the count delta: a fold that deleted the *wrong* spectra would also pass, as long as the log matches its own deletions. What 12b does test is real but narrow: the selftest exits green, the summary log line exists and parses, the stamp appears in both modes. What it cannot catch: the fold never firing on twin-containing data, or firing wrongly. The cluster benchmarks cover that today; nothing pre-commit does. Suggest asserting `folded == 0` on this fixture (pins the expectation) and/or a fixture that actually produces a twin (two seeds resolving to one mono, or overlapping windows via the existing `groups=` machinery).

  **F3 [low] selftest gaps — all expectations present are correct (I hand-verified each, including the fused m/z `(200·20+200.0005·5)/25` and the placement case), but uncovered:**
  - Boundary inclusivity: pair at exactly 20 ppm, `|d1/K0| == tol` exactly. The relation is inclusive on both; neither side of the boundary is tested. (`src/diaspextract.cpp:2027` probe window vs `test` at 3248.)
  - Probe orientation: every test has m/z increasing with `v` order, so only the forward scan (`ks[b].mz <= hi`) is exercised. The backward scan (earlier-in-`v` member has the *higher* m/z, linkage must use its tolerance) is never asserted.
  - Survivor field retention: only precursor m/z and position are checked; the survivor keeping its own RT, 1/K0, isolation offsets and userParams is asserted nowhere (it holds by construction via `clear(false)`, but that's the invariant the brief calls out).
  - Chained fusion: a group whose span exceeds 10 ppm via drift of the running weighted mean is untested.

  All theoretical; the logic for each is correct by inspection.

  ## Numbered questions

  1. **Thread/tile dependence: none found.** The argument is sound, in fact stronger than stated: the emitted RT is `pc.rt` bit-exactly (`src/diaspextract.cpp:3132`), and tile ownership is a pure function of that same double (`src/diaspextract.cpp:4716-4717`, same subtraction both sides), so bit-equal output RT ⇒ identical ownership predicates ⇒ same tile under every grouping — no reliance on the frame-time premise (the `[soa-rt]` snap at 4939-4946 is also a pure function of the trace RT over the frozen table, same in every tile). Inside `mergeTwins_`: `ks` sort has a unique tiebreak (`i`), union-find unions in a fixed order, survivor scan is in `v` order with strictly-greater replacement, the omp loop (`src/diaspextract.cpp:2057`) parallelises only across disjoint clusters with per-cluster sequential float summation, and the compaction is sequential. `canonicalSort_`'s total order feeds everything.
  2. **Crash / mis-fold: none found.** Cross-charge and cross-RT linking are impossible (group bound at `src/diaspextract.cpp:2023`); charge ≤ 0 and precursor-less spectra are excluded from `ks` and always kept; empty `v`, missing `spx_n_isotopes` (→ 0), and non-finite IM (never links; such precursors aren't emitted anyway) are all handled. A survivor is never deleted and a non-survivor never kept by the compaction (2076-2086). Isobaric same-frame same-charge precursors within 20 ppm *are* merged — that is the priced design, not a bug.
  3. **Fused list is always m/z-sorted** (contiguous groups of a sorted array; each emitted point is an all-positive-weight mean inside its group's span). An all-zero-intensity cluster would yield a 0-peak survivor, and `gw == 0` silently disables the split check — both unreachable on real data (`assembly:min_fragments` ≥ 1 enforced at `src/diaspextract.cpp:3113`, trace apex intensities > 0). No fused spectrum can lose all peaks on real data.
  4. **12b: see F2** — tests wiring and count reconciliation, not the fold; vacuous on this fixture.
  5. **Selftest: see F3** — expectations all correct; four coverage gaps, all theoretical.
  6. **Docs:** F1 is the only false claim. README/CHANGELOG numbers match the commit (23.8 % ≈ "24 %", 0.21/0.18 % ≈ "0.2 %"); "entrapment FDR unchanged" vs the commit's "+0.03 points" is defensible. The 10-ppm fusion and `max_fragments` overflow are documented accurately in help and CHANGELOG.

  ## Verified fine (one line each)

  - **`clear(false)`** — confirmed against OpenMS bd4b895: clears peaks, ranges and the float/string/int data arrays only; RT, precursors, MS level and userParams survive (`MSSpectrum.cpp`, `MSSpectrum::clear`). Emitted pseudo-MS2 spectra carry no data arrays, so clearing them is a no-op. Invariant 3 holds.
  - **Python equivalence** — line-by-line match with `bench/twin_merge.py`: 20 ppm probe tolerance on the earlier member, inclusive m/z and IM bounds on both sides, union-find components, survivor key (isotopes, peaks, lowest index) ≡ (isotopes, `size()`, earliest in `v`), fusion arithmetic identical including the `gw` guard and sort order. Only the acknowledged RT difference (≤ 1.5 s vs bit-equal). One nit: the Python default is `--im=0.01` vs the C++ default 0.005 — worth confirming the priced PXD029836 run passed `--im=0.005`.
  - **Scale** — no reachable quadratic path: pair scans are bounded by the 40-ppm window around each probe, fusion is one sorted cluster per thread iteration, and per-tile bookkeeping is ~50 B/spectrum; a single-tile 2-hour file (1.05 M spectra, 137 M peaks in clusters) is dominated by the `ps` sorts, well within budget.

