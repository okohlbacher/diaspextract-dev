# Backlog analysis — 2026-09-02 (revised after kimi + codex adversarial review)

Every open item across `docs/` plus today's findings, reduced to: **what the issue is, whether it is confirmed, the root
cause, the fix, the cost, and the gate.** Status vocabulary: **MEASURED** (a number on a named file and build),
**CONFIRMED** (seen in code/data), **HYPOTHESIS** (argued, not measured), **FALSIFIED** / **CLOSED** (kept in the register
at the end so nobody re-proposes or re-does them).

Review corrections applied (kimi 9 findings, codex 13): attribution-by-subtraction is now labelled as such (A1, C1);
mechanisms without a measurement are HYPOTHESIS (B3, C2, D1); mis-stated statuses fixed (C7 was measured, apportion was
falsified — under the E5 confound, D5 is worked around); R2 re-scoped to the byte-identical location; missing rows added
(R4, BC-2, BC-3, OI-2..7, PTM ambiguity, hardening obligations, Q4); duplicates and closed items moved to the register;
codex #13 (false calibration provenance on mzPeak output) **fixed in code today**; every plan step now carries a gate.

## A. Runtime (S30, 100 threads; HEAD build with timers; total 22:22)

| # | issue | status | evidence | root cause | fix | gate / cost |
|---|---|---|---|---|---|---|
| A1 | **~429 s of LOAD (444.7 s) is outside the MS2 batched loop** — attributed by control flow to the MS1 path | MEASURED residual (444.7 − 4.4 − 11.4 = 428.9 s); the component split (decode / sort / pick) is **not** timed | S30 P256det; S08 LOAD-only: 418 s with MS2 decode 10 s + hand-off 25 s → same shape on a second file | `loadDIAStreaming` decodes + sorts 1,343 MS1 frames (7.7% of frames, 37% of peaks) serially; `consumeMS1Spectrum_` picked each serially; ranked "small" by frame count | loader: batched parallel MS1 decode (`[speXtract ms1-par]`, per-thread ZSTD ctx + `FrameCentroider`, applied 14:45); consumer: parallel MS1 pick `flushMS1_` (in tree) | **DONE 15:01, gate PASSED:** LOAD **38.8 s** (80.5×; MS1 decode 6.9 s, hand-off 15.4 s, pick 27 s), total **15:21 (−31%)**, spectrum data byte-identical to P1 (`ca1ddbbd…`), Sage 12,217 = 12,217 |
| A2 | mzPeak input does not help runtime | MEASURED | LOAD 396 vs 445 s; total 21:24 vs 22:22; CPU 7,296 vs 1,785 s, system 1 h 05 vs 10 min | the floor is A1 (format-independent); reader opened per work item | reader thread-local (**untested** until the MZPms1 run) | closes with A1 |
| A3 | WINDOW_LOOP 774 ± 30 s at 59.5×; PRECURSOR_INFER 31 s serial; MS1_TRACE 61 s at 5.1× | MEASURED (±30 s run-to-run on serial phases) | `[perf]` tables, 3 runs | uneven windows; serial precursor inference; MS1 tracing at low width | (i) **R2 re-scoped**: short-trace skip only at the dot-product-only location (byte-identical there; the pre-grid cull changes `g.rt` → every Pearson, WINDOW-LOOP-AUDIT §5); (ii) R3 two-`lower_bound` band construction; (iii) parallelise precursor inference over m/z bands; (iv) split `perf:trace_bands` into MS1/MS2 options first (BC-3: MTD throws on a < 3-spectra band) | byte-identity digest for (i)–(iii); (iv) needs the quality gate |
| A4 | Peak RSS 107–124 GB | MEASURED | RSS 29 GB after load, 81–89 GB loop end | temporal high-water mark: per-window working sets + ~10 GB buffered output; July: ~87% glibc arena retention | (i) allocator A/B by `LD_PRELOAD` tcmalloc/jemalloc (July −18% RSS, −11% wall); (ii) stream the output; (iii) R2 (dot-product location) | (i) 1 h, byte-identical; (ii) 1–2 days |
| A5 | R4: 2.99% double-scored precursors (window overlap) | MEASURED (07-27) | RUNTIME-QUALITY R4 | overlapping windows both score the same precursor | dedup at admission (hours) | not byte-identical — quality gate (emission Δ≈0, set overlap) |
| A6 | OI-2..OI-7 (MassTrace move ctor, unconditional span diagnostics, RT SoA, `g.rt` capacity, `std::move(tmp_spec)`, reserves) | CONFIRMED still open in code (codex: span calc unconditional :1000–1017, `g.rt` capacity :699–706) | WINDOW-LOOP-AUDIT §3 | — | each hours; OI-2/OI-6 need a libOpenMS rebuild | byte-identical digest |
| A7 | R5 cross-window task graph | HYPOTHESIS | "15–30% of what remains" | window barrier | only after A1/A3, behind the determinism gate | 1–2 weeks; deferred |

## B. Determinism / reproducibility

| # | issue | status | evidence | root cause | fix / claim | gate |
|---|---|---|---|---|---|---|
| B1 | Byte-identical at fixed config | MEASURED 11:36 | S1=S2=P1=P2 | — | README: "deterministic at fixed thread count and fixed loader batch" | closed |
| B2 | Loader batch 64 vs 256 | **CLOSED 14:46 — content identical.** specdiff: 922,902 spectra, 0 differ; Sage set 12,217 = 12,217, symdiff 0; fixed digest identical (`ca1ddbbd…`) | the earlier "DIFFERS" was `bench/semantic_digest.py` hashing the trailing `<indexList>` byte offsets, which shift when the header changes by 4 bytes (build-date version stamp) | digest now stops at `</spectrumList>` (fixed today); both reviewers' "B2 before A1" concern is answered by data, and their protocol (1-thread 64 vs 256, MS1-stage digests first) stays the standing procedure for any future batch/threads claim | closed |
| B3 | Output differs across thread counts (8 vs 100) | MEASURED 09-01 (with the OLD digest — **re-measure with the fixed digest first**) | semantic digest differed | HYPOTHESIS: schedule-dependent trace insertion order / comparator ties (BC-5) — code reasoning, not diagnosed | (1) re-run the 8-vs-100 digest with the fixed script; (2) if it still differs: `[det]` stage digests at 8 vs 100 → first differing stage; (3) index tie-break / order-insensitive reductions at that stage | fixed digest; then stage digests |
| B4 | Cross-binary sensitivity (~2% from a 1e-11 change) | MEASURED once (one perturbation) | +1.9% peptides | greedy thresholds amplify last-ulp differences; **not a noise distribution** — one observation | decision rule stays: set overlap + ppm median beside every count; do not quote ±2% as a bound | policy |

## C. Identification quality (the science)

| # | issue | status | evidence | root cause | next test (with falsifier) | cost |
|---|---|---|---|---|---|---|
| C1 | **MSFragger 85% of diaTracer (CI [76.7, 93.2])**; Sage at parity (105%, CI [93, 117]) | MEASURED | 3 files × 2 engines | **10% of the gap = wrong charge labels (measured, override_charge)**; H7 (charge discard) falsified; H1 (null broadening) **not** falsified by the z∉{2,3} deletion (codex: lost true targets can exceed the threshold benefit); the remainder is UNRESOLVED — not "tail quality" by subtraction | discriminating arms, in this order: (a) matched-precursor score distributions on shared peptides (free, existing TSVs); (b) rescoring A/B (MSBooster/Percolator) on BOTH tools — read the spx/dt RATIO after rescoring, not "half closed"; (c) emission-controlled arm (quality-gate 924k→~700k + precursor-matched sub-arm, step 02); (d) oracle-fragment arm (kimi F7) to separate metadata / content / search | (a) hours; (b) days; (c) 1 week; (d) days |
| C2 | Residual +1.5..+3.2 ppm on identified precursors, 2–4 ppm above diaTracer on every file | MEASURED (pipeline-relative offset) | 3 files, both calibration paths | HYPOTHESIS: our centroid / mono-peak reporting; selection bias and mono convention not excluded (different identified populations) | paired shared-feature reported-m/z bias vs diaTracer (the discriminator) BEFORE any fix; the "+1–2% peptides" estimate is withdrawn (fragment-channel curve misapplied to a precursor residual; the precursor/both-channel arms were never recorded — record them) | 1 day; gain unknown |
| C3 | Entrapment FDR of the shipping table-model arm never measured | CONFIRMED (owed) | only sdkcal has 1.26% | oversight | `bench/entrapment.py` on the table arm, S30 + S08/S23 — **first**, cheapest science item | hours |
| C4 | Emission 1.32× diaTracer; 4.6 PSMs/peptide; purity 5.8% | MEASURED | S30 | share-all fan-out by design; all cross-precursor redistributions FALSIFIED ×7 | only a precursor QUALITY gate (C1 c) or within-spectrum weighting; never merging/collapse | inside C1 c |
| C5 | Charge agreement 74.6% vs 82.6%; ~44% of within-cycle duplicates ±1 isotope | MEASURED (S08) | — | partner-count charge; mono selection | learned charge/mono predictor (BACKLOG N+1) **only if** the oracle arm (C1 d) isolates a metadata-bound residual; held-out S23; must beat 74.6% by > 0.17% | 1–2 weeks, conditional |
| C6 | Native pre-centroiding aggregation | **MEASURED 07-27 (pre-calibration, Sage only)**: `native_ms1_neighbors=1` Sage +7.8%, entrapment 2.31%, at 2.7× emission | RUNTIME-QUALITY Q3 | gain is real but bought with emission | re-test under corrected calibration, both engines, WITH a post-aggregation gate that holds emission ≤ 1.4×; falsifier: peptides@matched-entrapment ≤ baseline | 1 day of runs; only with the gate |
| C7 | `assembly:apportion` / NNLS (BACKLOG 1) | apportion **FALSIFIED (S30-BASELINE §96–106) — under the E5 confound** (it silently ran with corr_power off) | — | — | fix E5 first; re-run apportion once; NNLS only if apportion shows any signal AND the P-matrix conditioning is measured | hours + 1 run |
| C8 | Open-search: step 01 done on S30; step 02 emission-controlled arm not run; PTM ambiguity 34.7% vs 14% known-PTM bins and the 1,610-unit Amidation bin uninvestigated | CONFIRMED | S30-BASELINE §303–311 | — | step 02 as pre-registered (v3 scorer, full FDR curves); one script on existing output for the Amidation bin | 1 week; hours |
| C9 | Precursor isotopes leak into fragment lists | **MEASURED today (E9): of 200,000 S30 pseudo-spectra, 28.4% contain M+1 and 24.8% contain M+2 within 10 ppm; M itself 0.2%** | `iso_frag_check.py` on d2_P1 | only the mono peak is excluded from the fragment list | exclude M..M+3/z within tolerance at assembly | one S30 run; gate: set overlap, both engines |
| C10 | Public-PXD replication | not done | patient data unreproducible in principle | — | diaTracer paper's public diaPASEF data, both tools, both engines | 1–2 weeks; gate for any public number |

## D. mzPeak / converter / reader

| # | issue | status | evidence | root cause | fix | owner |
|---|---|---|---|---|---|---|
| D1 | mzPeak input: −11.7% peptides, fragment error +10.05 vs +3.39 ppm | MEASURED; **attribution = leading hypothesis** (two-point transform, ~7 ppm bow) — confounded by the IM axis (converter ModelType-2 vs our rational; vendor-IM alone was worth ~1.3% on 09-01), the band reconstruction, +0.3% spectra | Sage on d3_MZP vs d2_P1 | archive carries only `mzpeak:transform_params` | **A/B that isolates it**: exact m/z on the same archive (read `MzCalibration` from the embedded `vendor/analysis.tdf.gz`) with IM, bands, RT, reader and binary held fixed; falsifier: ≈12,217 peptides with high set overlap → m/z; else the IM axis | speXtract 1 day; converter (handoff §5) |
| D2 | `--ims-chunked` aborts on TDF | CONFIRMED | S30 + S08 | facet-layout mismatch in the writer | converter (handoff §1) | converter |
| D3 | archive 4.5–5.6% larger than `tdf_bin` | MEASURED | — | per-peak f64 1/K0 (0.57) + tof (0.52) | converter question (handoff §2) | converter |
| D4 | band as name-only CV params; `precursor_index` NULL → reader attaches both ions to precursor 0 | CONFIRMED | `spx_band2` | converter metadata + reader attach key | worked around (flatten + match by m/z, 0.05 Da); converter/reader fix (handoff §3–4) | converter + library |
| D5 | library targets GCC 14 / Arrow 24 | **WORKED AROUND** (builds on GCC 13 / Arrow 23 with `patches/spx_ranges_to.h` + `patches/mzpeak-cpp-arrow23.py`) | build log | `std::ranges::to`, `ReadTable()` Result form | upstream as `#if` guards | library |
| D6 | mzPeak output stamped `BrukerTimsFile::lastMzCalibration()` (codex #13: false provenance) | **FIXED today**: mzPeak path stamps `spx::lastMzPeakCalibration()` = "mzpeak_two_point_transform … archive=…" | src :2753 | one global for two loaders | verified in the MZPms1 output (pending) | done |

## E. Engineering / product hygiene

| # | issue | status | fix | cost |
|---|---|---|---|---|
| E1 | determinism smoke test in CI | open (tests + CI exist since v0.2.0) | fixed-config digest on a public-derived fixture with the fixed digest script | 1 day |
| E2 | README 13 commits stale; branch 59 ahead of `main`; binary still `DIAPseudoSpectra` | CONFIRMED | README rewrite (S30-BASELINE + runtime + mzPeak); fast-forward main; rename executable (compat symlink) | 1 day |
| E3 | falsified flags' help still recommends them (`rp_max` :764, `merge` :796 "summed" vs MAX, `consolidate` :803) | CONFIRMED | mark FALSIFIED in help or remove | hours |
| E4 | `charge:iso_im_tolerance` default 0.05 contradicts its own help (:840) | CONFIRMED | decide 0.01 behind an S30 gate, or fix the help | hours + 1 run |
| E5 | `apportion` / `rp_max` bypass `corr_power` / `im_weight` — `assembleOne_` applies them (:1632–1643); apportion emits raw shares (:2345), rp_max raw intensities (:2454) | **CONFIRMED today**; invalidates every apportion/rp_max A/B ever run (they compared corr_power 2 vs 0) | one emit lambda for all three branches | hours; then C7 |
| E6 | macOS serialises the window loop | NOT VERIFIABLE here (no Mac build of the tool exists; no `__APPLE__` guard) | CMake FAIL without OpenMP unless `-DALLOW_SERIAL=ON`; one Mac build | 1 h |
| E7 | evidence chain / provenance | partly done (evidence/ + SHA256SUMS 09-01; src-sha check in sync) | tarball the 09-02 runs to ceph; stamp src sha in the mzML | hours |
| E8 | OpenMS patch drift (3 incidents) | process | regenerate from `.orig` + grep-verify (commit template); CI check that the patch applies to the pinned tarball | hours |
| E9 | hardening obligations from S30-BASELINE §332–334: benchmark must fail closed on a missing/wrong SDK path; opentims discards `tims_index_to_mz`'s return code | open | fail-closed check in `bench/`; return-code check in the vendored converter | hours |
| E10 | Q4 mono-offset stamp: help at :796 claims `open_search_safe` records it | verify (may be done) | close or list | 30 min |

## Recurring root causes

1. **Ranking by the wrong denominator** (A1 frame-vs-peak share, "write is the cost", "MS1 loop is small"): every mis-ranking was an inferred share; every correction was a timer. No runtime measure is ranked without a `[perf]` line, and residuals are labelled residuals.
2. **Instruments that lie**: the semantic digest hashed byte offsets (B2), the `[t=..]` markers hid the load (09-01), the raw-hyperscore harness is mass-error-blind (C1). Validate the instrument before trusting a "FAIL".
3. **Confounded A/Bs**: apportion/rp_max ran with corr_power silently off (E5); native aggregation was compared at 2.7× emission (C6); mzPeak changes m/z and IM at once (D1). Every arm needs one variable and a pre-registered falsifier.
4. **Calibration is the yield lever** (C2, D1): +6–11% from the exact model, −12% from the two-point one; the residual +2–3 ppm is still ours and unexplained.

## Plan (reviewed; ordered by value/effort; each step with its gate)

**Week 1 — land the runtime win, restore the instruments, cheap science first**
1. ~~A1~~ **DONE** (LOAD 39 s, total 15:21, byte-identical, set identical); patch regenerated from `.orig`, reverse dry-run verified, committed.
2. B3 re-measure (8 vs 100 threads) with the fixed digest; if still different, stage digests → first differing stage → fix there. Ship the claim exactly as measured.
3. C3 entrapment on the shipping arm (S30, S08, S23) — hours, owed, cheapest science item.
4. C2 paired shared-feature m/z bias vs diaTracer (measurement only; no fix before the number).
5. E5 one-emit-lambda fix + E3/E4/E10 hygiene in one commit; then C7 apportion re-run (one S30 run, set gate).
6. A3(i) dot-product short-trace skip, A3(ii) R3, A4(i) allocator A/B — all byte-identity-gated, quiet node.
7. E7 tarball of the 09-02 evidence to ceph.

**Week 2 — resolve the MSFragger attribution instead of naming it**
8. C1(a) matched-precursor score distributions (free) → C1(b) rescoring A/B on both tools (ratio, not "half") → C1(d) oracle-fragment arm. Only then decide between C1(c) emission-controlled arm and C5 learned predictor.
9. D1 isolation A/B (exact m/z from the embedded tdf on the same archive; IM/bands/RT fixed) — settles the converter ask with one number.
10. C9 isotope exclusion at assembly (one run, both engines, set gate).

**Weeks 3–4 — the arms that change the product**
11. C1(c)/C8 step 02 emission-controlled open-search arm (pre-registered, v3 scorer, full FDR curves).
12. C6 native aggregation re-test with the emission gate (1 day of runs).
13. C10 public-PXD replication + v0.3.0 (E2 README rewrite, rename, main fast-forward, E1 determinism CI).

**Cut / not doing:** merging/collapse; arena capping; ring buffers/reader processes; the 2D Gaussian detector before a demonstrated content gap; NNLS before apportion re-measurement + P conditioning; the learned predictor before the oracle arm; closed-search parity as a goal; ±2% as a generic uncertainty bound.

## Register: closed / falsified today (do not re-open)
- **B2** loader batch size does not change content (specdiff 0/922,902; Sage set identical; fixed digest identical). The digest tool was wrong, not the loader.
- **A5** `MALLOC_ARENA_MAX=4` at 100 threads: ~10× slower window loop; aborted.
- **A6** loader batch 64/256/1024: LOAD 436/432/434 s; keep 256; no ring buffer or reader process.
- **B1** byte-identical at fixed config (4 runs); parallel pick == serial pick.
- **D6** false mzPeak calibration provenance — fixed in code.
- **E1 (tests/CI)** exist since v0.2.0; only the determinism smoke test remains.
- OpenMS in-tree `MzPeakFile` (0 spectra on ims-compact) — closed for speXtract (bypassed); open only as a separate OpenMS product.
