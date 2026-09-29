• I'll review the release candidate. Let me start by gathering the diff and the scoped files.

• Now let me look at the actual source in context — PeakSlab, the ledger, and the merge code as it stands at HEAD.

• Now let me examine the tile loop, the toTof call sites, and the [det] block change.

• Let me check how `Trace.tof` is set on both detector paths, `exportMz_`, and the twin fold interplay.

• Now the CHANGELOG and README:

• Let me verify the remaining details: FragRt, the e71b085 diff itself, DnoiseMs1.h changes, and a few registered defaults.

• One more check — what the harness's "semantic digest" actually covers (relevant to the CHANGELOG's "reproduces 1.4.1 exactly" claim):

• Two last consistency checks — the `trace_bands` default quoted in the README pipeline text, and the 1.4.1 default of `dnoise:ms1`:

• Review complete. I read the full `v1.4.1..HEAD` diff of `src/diaspextract.cpp`, the surrounding code at HEAD (PeakSlab, TofAxis, FragRt, mergeTwins_, the tile loop, the ledger), both review dossiers (`docs/reviews/release-1.5.0/FINDINGS.md`, `docs/reviews/same-bin-traces-2026-09-27/verdict.md`), the harness digest definition (`bench/semantic_digest.py`), and verified the OpenMS PR state. No files were modified.

  **Verdict up front: no blockers. One fix-before-tag documentation error (GATE_DUMP format in the CHANGELOG). The two merges are deterministic and honor the off-path invariants.**

  ## Q1 — toTof() merge (src/diaspextract.cpp:964–1033)

  Clean. Specifically checked:

  - **Cross-frame/cross-bin safety.** Runs are bounded by `[lo, hi)` of the current frame and by exact bin equality (`sl.tof[e] == sl.tof[k]`, line 990). Bins are consecutive-equal because the slab is m/z-ascending within a frame (PeakSlab doc, line 833) and `tofOf` is monotone. `frame_off[i] = w` is written only after `lo/hi` were captured, and frame `i+1`'s `lo` is read before its own rewrite — no aliasing. Writes for a run land in `[w, w + outputs)` with `w ≤ k`, and all reads of the run (`sl.inten`, `sl.imq`, `sl.tof[k]`) complete before any write (the `cl` staging, line 999–1021). No peak can migrate across a frame or bin boundary.
  - **Order dependence.** The regroup sort key is `(imq, slab index)` — a total order (line 998). Summation order is therefore fixed by content, not by thread or schedule; IEEE addition of the two-element tie case is commutative, and 3+-element ties are ordered by slab index, which is itself deterministic (loader appends frames sequentially). toTof runs concurrently over windows (line 4611–4621) and in window tasks (line 4868), but each call touches one slab; shared state is atomics only. Thread- and tile-invariant ✓ (a frame lives in exactly one tile; on the resident path toTof runs once on the whole slab before slicing, line 4620).
  - **Span cap boundary.** Inclusive: `(long)run[q].first - (long)run[r].first <= span_q` with `span_q = 2 * tol_q` (lines 973, 1003–1004) — a group spanning exactly 2× the link still merges. Matches the docs' "at most twice". The cap is measured from the group's first member, so chaining is deterministic and cannot snowball.
  - **Off path (invariant 2).** `tol_q < 0` takes the verbatim branch for every run: self-copies with `w == j`, `frame_off` rewritten to identical values, `resize(w)` a no-op, ledger delta 0, counters 0. Byte-identical slab ✓.

  Minor (theoretical, not real data):
  - Line 1012: members with non-finite or ≤0 intensity are silently excluded from the sum but still consumed; an all-such group yields a 0-intensity peak. The picker doesn't emit those.
  - Line 973: `trace:im_slice_merge` has no `setMaxFloat_`; an absurd value (e.g. 1e15) overflows `llround` → UB. User error only.

  ## Q2 — assembly guard (src/diaspextract.cpp:3380–3417)

  Deterministic, and invariant 2 holds:

  - **Tie-breaking.** The sort key `(binless?, bin, exact-m/z, index)` is a total order (line 3384). `top` uses strict `>` (line 3397), so intensity ties keep the first in sorted order = lowest original index. `cap` is a plain max over the summed members — value-deterministic. The merged peak is written at `head = ord[g]`, the lowest index in the group, so spectrum order is unchanged (lines 3395, 3406); compaction is a stable forward scan (line 3414).
  - **No-op when no duplicates (invariant 2).** All groups size 1 → `nm == 0` → no writes, no resize. Verified: with `merge_same_bin false` the block is skipped entirely; with it on and no shared bins the spectrum is untouched.
  - **Cap-key inflation (invariant 3).** The merge runs before `max_fragments` (line 3420), the merged peak counts once, and the key is the max member key, not a sum ✓. Note the key is computed from the *member's* intensity, not the merged sum — this is documented in the option help ("best cap key of the summed members (not recomputed)").
  - RT-overlap is deliberately non-transitive (members must overlap `top`, not each other) — deterministic and documented.

  One theoretical edge: on the integer detector a trace at TOF bin 0 would be treated as "OpenMS detector, no bin" and compared by exact m/z. `tofOf` returns 0 only off-axis (line 711), unreachable for real picked peaks.

  ## Q3 — can two same-bin fragments survive both merges?

  Effectively no, and the residual paths are documented:

  - **Valley splits, band edges, tile carries** all surface as multiple fragments in one spectrum → caught by the assembly guard, which groups on the integer bin exactly (line 3386). Carried traces keep their `tof` and their spans are on the same frozen window-frame axis, so the RT-overlap test is tile-consistent ✓.
  - **Twin fold** (`mergeTwins_`, post-assembly) unions two spectra and could in principle reintroduce a same-bin pair exported at slightly different m/z (per-frame calibration factor). Its 10-ppm fusion absorbs this: the measured per-frame calibration step is Δ ≤ 1.1e-5 Th (verdict.md), inside 10 ppm for any m/z ≥ ~1.1. Residual risk only if calibration drift ever exceeds 10 ppm between two apex frames — theoretical.
  - **OpenMS detector**: only exact-equal m/z doubles merge. Stated in the option help and stamped `on (exact m/z)` (line 4694) — acceptable as documented, and the upstream stall is separately fixed (OpenMS #10291, merged into develop 2026-09-28 — I verified the PR state; the CHANGELOG's "fixed upstream" is accurate).
  - **MS1**: the merge is MS2-only (all three toTof call sites are MS2 window slabs); MS1 traces never appear as spectrum peaks, so invariant 3 is unaffected even though the verdict doc suspects MS1 slicing exists.

  ## Q4 — ledger (src/diaspextract.cpp:967, 1029)

  Correct. `ledAdd_` is an atomic relaxed `fetch_add` on `long long` (line 267); negative deltas are fine and safe under the concurrent toTof calls. `bytes()` is size-based (line 842), and every LC_SLAB charge/release in the file is size-based (lines 1889, 4768, 4803, 5009), so the merge delta balances exactly against the later `-wslab.bytes()` release. Caveat: `resize()` doesn't free capacity, so after a merge the ledger under-counts *held* pages — but that's the file's own "touched bytes" convention (line 4085 comment), the ledger is diagnostics-only (gated by `ledFile_()`), and it stays self-consistent. Minor at most.

  ## Q5 — CHANGELOG / README accuracy

  - **The 1.4.1-repro recipe is complete.** I traced every output-changing default added since v1.4.1 through `assembleOne_`: `-gate:adaptive off -gate:shrinkage off -gate:colocation off -gate:short_traces off -assembly:cap_rank corr_inten -trace:im_slice_merge -1 -assembly:merge_same_bin false` covers all of them; `fragment_delta_im` defaults to −1 (= `delta_im`, inert), the `faint_*`/`auto_*` options are inert under `adaptive off`, and the dnoise change only affects >100 ms files that 1.4.1 *refused* (`correctionRefusal` in src/DnoiseMs1.h — the ≤100 ms path is untouched, claim verified). "Same semantic digest" is the right hedge: `bench/semantic_digest.py` hashes from `<spectrumList>` onwards, so the new `spx:*` header stamps don't disturb it.
  - **FIX-BEFORE-TAG — wrong GATE_DUMP format in CHANGELOG** (CHANGELOG.md, v1.5.0 diagnostics bullet). It says `DIASPEXTRACT_GATE_TARGETS=<m/z,rt;...>`; the code reads a **TSV file path** with five columns `id mz rt_sec im z` (src/diaspextract.cpp:132,151). A user following the CHANGELOG gets a silently empty dump. Real-data impact: doc-only, diagnostic feature, trivial fix.
  - The one code-path difference vs 1.4.1 that survives the all-off recipe: NaN correlation scores are now rejected (`!(c >= min_corr)`, line 3321) where 1.4.1's `c < min_corr` let NaN through. NaN is unreachable with finite traces (pinv/invnorm are guarded), and FINDINGS.md already classified this digest-neutral. Theoretical.
  - Numbers and names checked against code and review docs: 0.015/2× span ✓, "15 % of HeLa spectra / half without the fold" ✓ (5cbc478, verdict.md's 50.6 %), `spx:same_bin_merge` + `[merge]` line ✓, `[pspan]` ✓, cap_rank formulas ✓ (evidence = max(r,0)·ln(1+I)·(1+overlap), umpire = max(r,0)²·ln(1+I), corr_inten = the 1.4 key).
  - **README defaults all match the registrations**: top 500 ✓ (line 2360), 0.015 ✓, merge_same_bin true ✓, cap_rank evidence ✓, adaptive faint / 4 frames / 6 s / power 1 / 0.45 ✓, shrinkage fisher 0.6/0.3/1 ✓, colocation ranges 0.3 ✓, short_traces concentric 0.5/1 ✓, fragment_delta_im −1 ✓, pipeline text's 3 s / 0.01 1/K0 / 12 bands / corr_power 2 ✓.
  - Minor omission (acceptable): the tile_drt fix (e71b085) and the NaN gate are not in the CHANGELOG. Both are digest-neutral or fix a bug that never existed in a released version; one line on the tile fix would still help anyone who ran an rc.

  ## Q6 — anything else

  Nothing blocking. For completeness: the new `InvalidParameter` on `shrinkage fisher` + `coelution logoverlap` (line ~3700 region of main_) is a new refusal for a previously accepted-but-nonsensical combination — documented in the option help, fine. The untracked `harness/*.md` files were out of scope and not reviewed. The FINDINGS.md note that the codex review never ran ("review is incomplete until codex has run") is a process gap you may want to close before tagging, but nothing I found suggests a latent issue hiding behind it.

  **Bottom line: the release can ship after fixing the GATE_DUMP line in the CHANGELOG.**

