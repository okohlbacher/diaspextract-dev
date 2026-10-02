# Adversarial review: DIAspeXtract 1.6.0 rc2, everything since the first release review

**Review only. Do not modify, create or delete any file. Do not run git commands that change state (no checkout,
stash, commit, reset, worktree). Do not build or run anything.** Everything you need is inline below: the commit list,
the full source diff, the hand-resolved merge conflicts, the docs diff and the test diff. If you are in a checkout, it
is at commit b592804, whose `src/` is byte-identical to e53b357; you may READ files there for more context (the whole
`src/diaspextract.cpp` is ~7,640 lines), but every finding must be answerable from the code, not from running it.

## What the tool is

DIAspeXtract is a C++ OpenMS TOPP tool (one file, `src/diaspextract.cpp`, OpenMP) that turns Bruker timsTOF diaPASEF
DIA runs into pseudo-MS/MS spectra (mzML/mzPeak) for DDA search engines: it traces MS1 and MS2 signals in
(RT, m/z, 1/K0), infers precursors (isotope walk -> charge + monoisotope), gates fragments by co-elution with the
precursor, and writes one spectrum per precursor. The run is cut into fixed 600-s retention-time cells; a tile (one cell
by default, `-tile:cells_per_tile`) is read, traced, scored, sorted and written; fragments straddling a cut are carried.
The output identity check is a **semantic digest** over the spectrum list (precursor m/z, charge, RT, 1/K0, peaks) and
the `spx:` header stamps.

## Scope (frozen)

- Base: **8e447bc** (1.6.0 rc1, reviewed by the first release review; its known limitations are listed below).
- Head: **e53b357** (rc2 source and docs) plus **b592804** (one test-only commit on top; same binary).
- Range `8e447bc..e53b357` touches: `src/diaspextract.cpp` (+1,831 / -305 incl. context), `CHANGELOG.md`,
  `README.md`, `docs/BACKLOG.md` (internal, not exported, NOT in scope), `docs/reviews/...rc-gate...md` (internal
  record, NOT in scope). `b592804` touches `test/test_diaspextract.py` only.
- **Files in scope:** `src/diaspextract.cpp`, `CHANGELOG.md`, `README.md`, `test/test_diaspextract.py` (the b592804
  hunk only).

What the range adds on top of 1.6.0 rc1 (each merged from its own branch; merge commits are listed below):

1. **F3 fused cap key** (93cd776, merged d9c3d89): a fused peak (fragment fusion, `-assembly:fragment_fuse_ppm` 25
   anchored, a 1.6.0 default) is ranked under the 500-peak cap by a key computed from the SUM of its members'
   1/K0-weighted apex intensities, with the score (and for `evidence`, the shared points) of the member with the best
   key. Before: the best member's key.
2. **minlen** (ba78a57, merged 3a2d75f): `-trace:min_length_sec` default 3 -> -1 = auto. Traces a fixed sample of the
   MS1 map (every peak in 1-Th m/z slices, one slice every 25 Th) with no minimum length; minimum = `min_length_fwhm`
   (0.4) x the median FWHM of the brightest tenth of the sample's traces, at least half an MS1 cycle; fewer than 100
   measurable traces -> 3 s fallback. Stamp `spx:ms1_min_length`, log `[minlen]`.
3. **isotol** (b5e5bef, 2409b0b, merged 55d72d6): `-charge:iso_im_tolerance` default 0.05 -> 0 = auto. A stride sample
   of the content-sorted MS1 traces (at most 200,000 probes) is probed at each charge's +1 isotope position (the walk's
   m/z and RT window) and at two control positions +-50 ppm; the nearest trace's 1/K0 gap is kept per position; the
   tolerance maximises admitted isotope-position traces minus 2x control traces on a 0.001 grid clamped to
   [0.01, 0.05]. Also `-charge:iso_partner first|closest` (default first = 1.5.0). Stamp `spx:iso_im_tolerance`.
4. **f1fold** (06377d1, a546e92, b25d42f, 71bd6f5, merged b42d3e7): `-assembly:twin_rt_frames` (default 0 = auto) and
   `-assembly:twin_rt_match ext|bin|ppm` (default ext). The twin fold (folds spectra that claim one precursor twice:
   same charge, precursor m/z within 20 ppm, 1/K0 within `twin_im_tolerance` 0.005; the survivor takes the union of the
   cluster's fragments) used to require the SAME MS1 frame. It now also joins a pair from nearby frames when: precursor
   m/z within one flight-time bin (0.05 ppm); with `ext`, at least one member's monoisotope was placed by the v2
   monocheck's extension (`mono_ext`); |dRT| <= (n + 0.5) x MS1 cycle with n = auto = the run's median MS1 peak FWHM
   in cycles (FWHM of the precursors' seed traces with >= 3 points, rounded, at least 1); and both in ONE
   retention-time cell (so output does not depend on tiling/threads). `-1` = same frame only (the pre-1.6.0 fold).
5. **scaling** (tune/rc-b-scal 7e6acdc, merged 9ad11f2 with hand-resolved conflicts): (a) **pipe** = pipelined RT tiles:
   one window-team region over all tiles, up to two tiles with windows in flight, the next tile read (read-ahead) and
   the finished one sorted/folded/written (write-behind) while windows run; the carry-over is the only dependency;
   `DIASPEXTRACT_PIPE_TILES=1` = one tile at a time. `teamFor_`/`teamAssist_`/`PullJob_` run the reader/writer loops
   on the window team without a nested team. (b) **serial** = a heavy window's serial stages as bounded task counts
   (`parTasks_`, `forTasks_`, `parallelSort_`). (c) **outer** = MS1 conversion and sorts, `mzOrder_`, PRECURSOR_INFER
   batches in parallel (`parallelSortTotal_`, `sortExact_`, `stdSortPar_`, which replays libstdc++ 13's std::sort).
   Plus review fixes 7dcf44d (writer backpressure, team-of-one admission, MS1 offset guard) and 7e6acdc (no taskloop on
   the pipe driver).
6. Scrub 35ac0af (dataset name out of source comments), docs e53b357 (CHANGELOG/README/help strings).

Commit list `8e447bc..b592804` and the merge-conflict resolutions are inline below.

## Evidence already in hand (do not re-derive; attack it if you think it is wrong)

- **Defaults identity:** the published rc2 binary (from b592804) reproduces the pinned semantic digests of the combined
  arm at the defaults (100 threads) on two runs, and with the six-option reset
  (`-assembly:im_weight_sigma 0 -assembly:foreign_precursor_weight 1 -assembly:fragment_fuse_ppm 0
  -charge:mono_profile_check false -charge:iso_im_tolerance 0.05 -trace:min_length_sec 3`) the 1.5.0 digests exactly.
- **Scaling identity:** features + scaling == features without scaling (digest) on five public runs at 100 threads;
  the scaling branch alone was digest-identical to its base on 12/12 runs at 16 and 100 threads, 1 and 2 cells/tile.
- e2e suite 30/30 on the rc2 binary. The suite at e53b357 failed 1 check (12b: the default `spx:twin_merge` stamp
  text changed with the cross-frame fold); b592804 fixes the test only (inline below).
- NOT measured at rc2: thread counts other than 100 for the three per-run estimators and the cross-frame fold;
  `-tile:cells_per_tile 0/2` with the cross-frame fold on; `DIASPEXTRACT_PIPE_TILES=1` vs pipelined at the 1.6.0
  defaults; tiny runs; runs with one MS1 frame or no MS1 traces.

## Invariants the code must hold (attack these)

1. **Output-identical across threads, tiles and pipelining**: same semantic digest at any `-threads`, any
   `-tile:cells_per_tile` (0 = one tile, 1, 2), pipelined or `DIASPEXTRACT_PIPE_TILES=1`, and stream-load on/off. Every
   parallel sort must return exactly the serial sort's sequence (std::sort is unstable: ties are the danger); every
   reduction must be order-independent or index-addressed; every per-run estimator must see the same sample in the same
   order.
2. **Options reset -> 1.5.0**: with the six options above every new code path must be inert or reproduce 1.5.0
   bit-for-bit (twin_rt_frames stays at its default 0 = auto in that reset: the claim is that nothing folds across
   frames without v2, because `mono_ext` is only set by v2's extension and `ext` requires it). Header stamps included.
3. **Each per-run estimator deterministic and robust**: the minlen FWHM estimate, the isotol tolerance, the twin_rt_frames
   n. Check: sampling (stride, slice positions), ties (median of an even count, nth_element, argmax ties on the grid),
   NaN/inf (non-finite m/z, RT, 1/K0, zero cycle), tiny runs (fewer than 100 traces, fewer than 3 points, 1 MS1
   frame), a run with **no MS1 traces at all**, a run where the MS1 cycle is irregular or zero, integer overflow in
   `llround`/casts, and division by zero.
4. **Clamps sane**: isotol [0.01, 0.05]; minlen >= half a cycle (and is there an upper bound? should there be?);
   twin_rt_frames n >= 1 with NO upper bound (what happens with a slow MS1 cycle or very wide peaks?).
5. **The cross-frame fold's survivor rule**: which spectrum survives a cluster, is it independent of input order
   (tile order, sort order, thread scheduling), how are transitive clusters formed (same-frame pair + cross-frame pair
   = one cluster?), can the `ext` condition plus transitivity fold two spectra that are NOT a same-mono pair, and is
   the "one retention-time cell" condition evaluated on the SAME cell the spectrum's tile assignment uses (if a
   spectrum's fold cell can differ from the tile it is written in, the fold sees different sets at
   cells_per_tile 1 vs 0/2 and the output depends on tiling).
6. **The merged exception handling in the pipelined writer**: the 9ad11f2 resolution kept `try/catch -> exception_ptr
   -> rethrow` only on the `omp parallel for` branch of `mergeTwins_`'s fuse loop and `capAfterFusion_`, and relies on
   `teamFor_`'s own rethrow on the pipelined branch. Check that every exception path inside the pipelined tile loop
   (reader, window tasks, writer task, `finishTile`, `teamFor_` helpers, `teamAssist_` from window code) is caught
   inside an OpenMP task/region and reaches the user as an error message and non-zero exit, never `std::terminate`,
   never a hang (a waiter on a flag/counter that the failed path never releases), never a partially written file
   reported as success.
7. **Residency bounded**: "up to two tiles have windows in flight". Check that read-ahead, carry-over and write-behind
   cannot hold a third tile's slabs, that the admission charge (75 % of free RAM, one window always admitted) accounts
   for both tiles, that writer backpressure works, and that `DIASPEXTRACT_PIPE_TILES=1` really restores one tile at a
   time.
8. **Scrub rules for exported text** (`src/` incl. comments and help strings, `CHANGELOG.md`, `README.md`, `test/`):
   no K562 or PXD041421 results, the comparison tool never named (say "the reference implementation"), no cohort
   labels (S08/S23/S26/S30/S33/S36), no `/Users` paths, no `docs/reviews` mentions, no internal sample/arm/workflow
   labels that mean nothing to a public reader.
9. **Docs == code**: every number, default, clamp, condition and stamp count in the CHANGELOG/README/help must match
   the code (e.g. "29 stamps at the defaults", "(n + 0.5) x the cycle", "at least 1", "0.001 grid", "200,000 probes",
   "fewer than 100 measurable traces fall back to 3 s", "within 0.05 ppm", the six-option reset sentence).

## Numbered questions (answer each; say "fine" briefly when it is)

1. `stdSortPar_` (replays libstdc++ 13 introsort with tasks) and `parallelSortTotal_`/`sortExact_`/`mzOrder_`: is each
   call site's result provably std::sort's sequence, including ties? Where `less` is not a total order, what decides
   the tie order, and does it depend on the thread count? What happens on libstdc++ != 13, libc++ (macOS) and MSVC
   (Windows CI legs compile this file)?
2. `parallelSort_` in the window's serial stages: its own comment says the result equals std::sort's only for a TOTAL
   order. Is every caller's comparator total (unique last key)? If not, the output can depend on `parTasks_`, which
   depends on `omp_get_num_threads()` and on `onPipeDriver_()`.
3. minlen: the sample trace detection runs `detectTraces_` on a sample map built by `nchunk = min(#spectra,
   4 x max_threads)` parallel chunks. Is the sample (and thus the estimate) independent of the thread count? Of
   stream-load vs not? Of dnoise? Does it run on the same MS1 map (after the same sorts/denoise) at every setting?
4. isotol: is the stride sample independent of tiling and threads? Ties at the grid argmax? What if N = 0, N < probes,
   or no control traces at all (net = admitted - 2 x 0)? Is the measured value stamped and logged exactly as used?
5. twin_rt_frames auto: `llround(med / cycle)` with `cycle` 0, NaN or tiny; `(int)` of a huge value; precursors empty;
   seed traces all < 3 points. And what `cycle` is used: the run's median MS1 cycle, a mean, or a per-tile value?
6. Cross-frame fold: walk through `mergeTwins_` with the new pair test. Concrete failing input wanted for any order
   dependence, any transitive over-fold, any pair counted in the `[twins]` log but not folded (or vice versa), and any
   difference between `-assembly:twin_rt_frames -1` and the pre-1.6.0 fold.
7. F3 fused cap key: is the summed-apex key computed from the same IM weighting as an unfused fragment's key? Can a
   fused peak's key ever be LOWER than its best piece's (the docs say never)? NaN/zero intensities? Float vs double
   rounding that could make the key differ between the fusion paths (keyed vs unkeyed, pipelined vs not)?
8. Pipelined tile loop (`pipe`): ordering of writes (tile k always written before tile k+1, spectra in the same order
   as the serial loop), the carry-over hand-off between tiles (who owns it when, can tile k+1's windows start before
   tile k's carry is final?), `malloc_trim` between tiles, `teamHelpersQueued_` (a global counter: can it leak and
   stop helpers forever after an exception?), `onPipeDriver_` (thread_local: reset on every exit path?).
9. Exception paths: see invariant 6. Also `taskFault_` sites: does the e2e falsifier cover the pipelined writer?
10. Docs/help/scrub: any number or claim that does not match the code; any scrub violation (quote it).
11. b592804: does the updated e2e check 12b actually test what its message claims, and could it pass on a binary whose
    cross-frame fold is broken?

## Known limitations already accepted (do NOT re-report unless the new diff makes them worse)

- v2 box narrower than the walk's isotope tolerance (an out-of-box partner counts as an empty position).
- Duplicate monoisotope after the extension beyond the fold's 1/K0 tolerance or across a cell edge stays two spectra.
- Fusion sums pieces whose elution does not overlap; fusion is not reconciled across twins.
- Foreign-envelope removal considers only precursors whose monoisotope lies in the window.
- Everything in the 8e447bc tree that the range does not touch was reviewed in the first release review.

## Output format

For each finding: **severity** (blocker / high / medium / low), **file:line** (in the b592804 tree, or the diff hunk),
**what is wrong**, **a concrete failing input or execution order**, **would this bite on real data or is it
theoretical**, and **does a fix change the output at the defaults** (yes/no/unknown). Rank by severity. If something is
fine, say so in one line rather than padding. Do not report style. Do not propose large refactors.

## Commit list `git log --oneline 8e447bc..b592804`

```
b592804 e2e: the twin fold check expects the 1.6.0 header (cross-frame fold on by default)
e53b357 1.6.0 docs: combined screen, digest gate and timings; twin_im_tolerance help points at the near-frame fold
35ac0af Scrub: the scaling levers' source comments name no dataset (K562 -> a 60-min run)
9ad11f2 Merge tune/rc-b-scal (scaling levers: pipelined tiles, serial-stage tasks, parallel outer phases) into release-1.6.0
b42d3e7 Merge f160-f1fold (twin fold across nearby frames, ext) into release-1.6.0
55d72d6 Merge f160-isotol (per-run isotope-partner 1/K0 tolerance) into release-1.6.0
3a2d75f Merge f160-minlen (adaptive MS1 minimum trace length) into release-1.6.0
71bd6f5 Twin fold across frames: README row, CHANGELOG 1.6.0 bullet, BACKLOG screen record
2409b0b isotol: document the screen (measured tolerances; iso_partner closest not recommended)
b25d42f Twin fold across frames: fold only the extension's pairs by default (twin_rt_match ext)
a546e92 Twin fold across frames: match one flight-time bin (0.05 ppm) by default
b5e5bef charge:iso_im_tolerance auto: per-run isotope-partner 1/K0 tolerance; charge:iso_partner closest variant
06377d1 Twin fold: join same-monoisotope pairs at nearby MS1 frames (F1 redesign)
ba78a57 trace:min_length_sec auto: the MS1 minimum trace length from the run's peak width
7e6acdc rc-b-scal review fix: no taskloop on the pipe driver
7dcf44d rc-b-scal review fixes: writer backpressure, team-of-one admission, MS1 offset guard
02ecc52 Merge fix160-monocheck (BACKLOG evidence only) into release-1.6.0
d9c3d89 Merge fix160-fusecap (F3: fused-peak cap key from the summed apex) into release-1.6.0
e7c2487 Merge tune/scal-outer at b406c10 (outside-loop phases in parallel; arm scal-outer-4) into tune/rc-b-scal
c654e81 Merge tune/scal-serial at 7a0442a (heavy window's serial stages as bounded tasks; arm scal-serial-2) into tune/rc-b-scal
36e6760 Merge tune/scal-pipe at 56b445b (pipelined RT tiles; arm scal-pipe-4) into tune/rc-b-scal
e991476 Release 1.6.0: rc gate record (v1.6.0rc1, 8e447bc)
fd394ef monocheck v2 review findings R1/F1: no fix passes the panel screen; code and public docs back to 8e447bc
9fb23fc monocheck v2: drop the extension claim check (F1), keep the empty-heavier-position fix (R1)
888dbc5 BACKLOG: F3 fused cap key -- identity, determinism and panel screen of fix160-fusecap-1
994fa91 monocheck v2: keep an extension onto another precursor's mono when the twin fold joins the two
56b445b Revert "pipe: the band detector's seed loop helps a live tile reader/writer loop every 8192 seeds"
4c2b88a monocheck v2: an empty heavier position decides nothing; the extension never lands on another precursor's mono
93cd776 Fusion: recompute the fused peak's cap key from the summed apex (1.6.0 review F3)
b406c10 scal-outer: greedy walk back to frozen batches, batch 2048, chunk sized to the batch
a26f7f4 pipe: the band detector's seed loop helps a live tile reader/writer loop every 8192 seeds
a6a330d scal-outer: by_mz in std::sort's order in parallel; MS1 async pick opt-in; walk switches
7c69b15 pipe: window code helps the live tile reader/writer loop (teamAssist_), so the I/O is not starved
a7e64ac pipe: back to task helpers; the tile write is a writer task, so the next read never waits behind it
8dbb1a1 pipe: reader/writer loops back on nested teams, driver = thread 0, tile written before the next read
7a0442a scal-serial: split chunks cost-balanced and up to one per team thread for large windows
49fbfc9 scal-outer: MS1 trace conversion in parallel with the serial arena layout
e6f6270 scal-outer: MS1 pick beside the stream reader; greedy-walk commit beside the next speculation
ef0ac8b pipe: pipelined tiles -- one window-team region over all tiles, read-ahead, carry as the only dependency
0289d93 scal-outer: parallelise the phases outside the window loop, output-identically
3f59164 scal-serial: run the heavy window's serial stages as bounded tasks, output-identical
```

## `git diff --stat 8e447bc e53b357` (+ b592804)

```
 CHANGELOG.md                                     |  109 +-
 README.md                                        |   36 +-
 docs/BACKLOG.md                                  |  142 +-
 docs/reviews/release-1.6.0/rc-gate-2026-10-01.md |   86 +
 src/diaspextract.cpp                             | 1831 +++++++++++++++++++---
 5 files changed, 1899 insertions(+), 305 deletions(-)
 test/test_diaspextract.py | 11 +++++++++--
 1 file changed, 9 insertions(+), 2 deletions(-)
```

## Hand-resolved merge conflicts in src (git show --remerge-diff: lines starting "-<<<<<<<" etc. are the conflict as git produced it; the +/- lines are the hand resolution)

### 9ad11f2 (merge of the scaling branch) -- src part

```diff
diff --git a/src/diaspextract.cpp b/src/diaspextract.cpp
remerge CONFLICT (content): Merge conflict in src/diaspextract.cpp
index 164ee51..a3dfbf6 100644
--- a/src/diaspextract.cpp
+++ b/src/diaspextract.cpp
@@ -2857,15 +2857,8 @@ namespace
         if (r1 - r0 > rt_tol) ++(*st)[4];
       }
     // fuse: each thread reads and writes one cluster's spectra only
-<<<<<<< b42d3e7 (Merge f160-f1fold (twin fold across nearby frames, ext) into release-1.6.0)
-    std::exception_ptr fold_err;   // [task-err] an exception escaping the region (bad_alloc) would abort without a message
-#pragma omp parallel for schedule(dynamic, 64)
-    for (long c = 0; c < (long)surv.size(); ++c)
-    { try {
-=======
     auto fuse = [&](const long c)
     {
->>>>>>> 7e6acdc (rc-b-scal review fix: no taskloop on the pipe driver)
       if (keyed)
       {
         // [recap] the same fusion over (m/z, intensity, key) triples. Peaks equal in m/z and intensity add equal terms
@@ -2911,18 +2904,15 @@ namespace
       s.clear(false);   // peaks only: RT, precursor and userParams are the survivor's
       s.reserve(fused.size());
       for (const auto& f : fused) s.emplace_back(f.first, (float)f.second);
-<<<<<<< b42d3e7 (Merge f160-f1fold (twin fold across nearby frames, ext) into release-1.6.0)
-    } catch (...) { taskErr_(fold_err); } }
-    if (fold_err) std::rethrow_exception(fold_err);
-=======
     };
     if (!omp_in_parallel())
     {
+      std::exception_ptr fold_err;   // [task-err] an exception escaping the region (bad_alloc) would abort without a message
 #pragma omp parallel for schedule(dynamic, 64)
-      for (long c = 0; c < (long)surv.size(); ++c) fuse(c);
+      for (long c = 0; c < (long)surv.size(); ++c) { try { fuse(c); } catch (...) { taskErr_(fold_err); } }
+      if (fold_err) std::rethrow_exception(fold_err);
     }
-    else teamFor_((long)surv.size(), 64, [&](long c, int) { fuse(c); });   // [pipe] the pipelined tile writer
->>>>>>> 7e6acdc (rc-b-scal review fix: no taskloop on the pipe driver)
+    else teamFor_((long)surv.size(), 64, [&](long c, int) { fuse(c); });   // [pipe] the pipelined tile writer; teamFor_ rethrows the first exception
     size_t w = 0;
     for (uint32_t i = 0; i < (uint32_t)v.size(); ++i)
     {
@@ -2944,16 +2934,9 @@ namespace
   static std::array<size_t, 3> capAfterFusion_(vector<MSSpectrum>& v, Size max_frags)
   {
     size_t n_sp = 0, n_pk = 0, n_max = 0;
-<<<<<<< b42d3e7 (Merge f160-f1fold (twin fold across nearby frames, ext) into release-1.6.0)
-    std::exception_ptr cap_err;   // [task-err] an exception escaping the region (bad_alloc) would abort without a message
-#pragma omp parallel for schedule(dynamic, 256) reduction(+ : n_sp, n_pk) reduction(max : n_max)
-    for (long i = 0; i < (long)v.size(); ++i)
-    { try {
-=======
     // the counters are parameters, not captures: inside the reduction loop they must be the thread's copies
     auto capOne = [&v, max_frags](const long i, size_t& n_sp, size_t& n_pk, size_t& n_max)
     {
->>>>>>> 7e6acdc (rc-b-scal review fix: no taskloop on the pipe driver)
       MSSpectrum& s = v[(size_t)i];
       n_max = std::max(n_max, (size_t)s.size());
       if (s.size() > max_frags && !s.getFloatDataArrays().empty())
@@ -2974,15 +2957,13 @@ namespace
         s.select(idx);
       }
       s.getFloatDataArrays().clear();
-<<<<<<< b42d3e7 (Merge f160-f1fold (twin fold across nearby frames, ext) into release-1.6.0)
-    } catch (...) { taskErr_(cap_err); } }
-    if (cap_err) std::rethrow_exception(cap_err);
-=======
     };
     if (!omp_in_parallel())
     {
+      std::exception_ptr cap_err;   // [task-err] an exception escaping the region (bad_alloc) would abort without a message
 #pragma omp parallel for schedule(dynamic, 256) reduction(+ : n_sp, n_pk) reduction(max : n_max)
-      for (long i = 0; i < (long)v.size(); ++i) capOne(i, n_sp, n_pk, n_max);
+      for (long i = 0; i < (long)v.size(); ++i) { try { capOne(i, n_sp, n_pk, n_max); } catch (...) { taskErr_(cap_err); } }
+      if (cap_err) std::rethrow_exception(cap_err);
     }
     else
     {
@@ -2991,7 +2972,6 @@ namespace
       teamFor_((long)v.size(), 256, [&](long i, int slot) { auto& p = part[(size_t)slot]; capOne(i, p[0], p[1], p[2]); });
       for (const auto& p : part) { n_sp += p[0]; n_pk += p[1]; n_max = std::max(n_max, p[2]); }
     }
->>>>>>> 7e6acdc (rc-b-scal review fix: no taskloop on the pipe driver)
     return {n_sp, n_pk, n_max};
   }
 
@@ -3731,7 +3711,6 @@ protected:
     return (vx > 0 && vy > 0) ? cov / std::sqrt(vx * vy) : -2.0;
   }
 
-<<<<<<< b42d3e7 (Merge f160-f1fold (twin fold across nearby frames, ext) into release-1.6.0)
   /// [isotol] charge:iso_im_tolerance 0 (auto): the run's isotope-partner 1/K0 tolerance, measured on its own MS1 traces
   /// before the greedy walk. `ms1` is the content-sorted list (m/z ascending), so the sample and every search are the same
   /// at any thread count and tiling. Every ceil(N / 200000)-th trace is a probe. At each charge z <= max_charge it is
@@ -3806,7 +3785,8 @@ protected:
                   tol, tstar, ns, stride, N, Z, rate(0, xc), 0.5 * (rate(1, xc) + rate(2, xc)), rate(0, NG - 1), 0.5 * (rate(1, NG - 1) + rate(2, NG - 1)));
     writeLogInfo_(String(b));
     return tol;
-=======
+  }
+
   /// [outer] The m/z order inferPrecursors_ and monoPositionPass_ share: the indices of @p ms1 by std::sort on m/z alone.
   /// The MS1 traces arrive content-sorted (m/z is the first key), so unless two of them share an m/z the m/z values
   /// strictly increase in container order, the identity is then the only sorted order, and it is taken without sorting.
@@ -3824,7 +3804,6 @@ protected:
     for (long i = 1; i < (long)N; ++i) if (!(ms1[(size_t)i - 1].mz < ms1[(size_t)i].mz)) ++nonincr;
     if (nonincr) stdSortPar_(by_mz, [&ms1](size_t a, size_t b) { return ms1[a].mz < ms1[b].mz; });
     return nonincr;
->>>>>>> 7e6acdc (rc-b-scal review fix: no taskloop on the pipe driver)
   }
 
   /// [route-1] Isotope/charge inference on MS1 traces. Scores each (charge, monoisotope) hypothesis
```

### b42d3e7 (merge of f1fold) -- src part

```diff
diff --git a/src/diaspextract.cpp b/src/diaspextract.cpp
remerge CONFLICT (content): Merge conflict in src/diaspextract.cpp
index 140e0d2..b6bb711 100644
--- a/src/diaspextract.cpp
+++ b/src/diaspextract.cpp
@@ -562,15 +562,9 @@ namespace
       if (real(s, t, k)) { rt.push_back(rtAtSpan(s, t, k)); v.push_back((double)xv(s, t, k)); }
   }
 
-<<<<<<< 55d72d6 (Merge f160-isotol (per-run isotope-partner 1/K0 tolerance) into release-1.6.0)
   /// [fwhm] FWHM (seconds) from the trace's own XIC: apex, then outwards to half maximum with linear interpolation;
   /// a side that never reaches half maximum ends at the first/last point. -1 below 3 points.
   inline double xicFwhm(const TraceStore& s, const Trace& tr)
-=======
-  /// [fwhm] FWHM (s) from the trace's own XIC: apex, then outwards to half maximum with linear interpolation;
-  /// a side that never reaches half maximum ends at the first/last point. -1 below 3 points.
-  inline double traceFwhm(const TraceStore& s, const Trace& tr)
->>>>>>> 71bd6f5 (Twin fold across frames: README row, CHANGELOG 1.6.0 bullet, BACKLOG screen record)
   {
     if (tr.np() < 3) return -1.0;
     vector<double> prt, pv; packReal(s, tr, prt, pv);
@@ -5576,11 +5570,7 @@ protected:
     const String ms1_dump = getStringOption_("diag:dump_ms1_tsv");
     if (!ms1_dump.empty())
     {
-<<<<<<< 55d72d6 (Merge f160-isotol (per-run isotope-partner 1/K0 tolerance) into release-1.6.0)
       auto fwhm_of = [&ms1_store](const Trace& tr) -> double { return xicFwhm(ms1_store, tr); };   // [fwhm]
-=======
-      auto fwhm_of = [&ms1_store](const Trace& tr) -> double { return traceFwhm(ms1_store, tr); };   // [fwhm]
->>>>>>> 71bd6f5 (Twin fold across frames: README row, CHANGELOG 1.6.0 bullet, BACKLOG screen record)
       ofstream ft((ms1_dump + ".traces.tsv").c_str());
       // [model] 12 significant digits: the default 6 quantises m/z 765 to ~1.3 ppm.
       ft.precision(12);
@@ -5615,7 +5605,7 @@ protected:
       {
         vector<double> fw;
         fw.reserve(precursors.size());
-        for (const Precursor_& pc : precursors) { const double f = traceFwhm(ms1_store, ms1_traces[pc.trace_idx]); if (f > 0.0) fw.push_back(f); }
+        for (const Precursor_& pc : precursors) { const double f = xicFwhm(ms1_store, ms1_traces[pc.trace_idx]); if (f > 0.0) fw.push_back(f); }
         double med = -1.0;
         if (!fw.empty()) { const size_t m = fw.size() / 2; std::nth_element(fw.begin(), fw.begin() + (long)m, fw.end()); med = fw[m]; }
         n = med > 0.0 ? std::max(1, (int)llround(med / cycle)) : 1;
```

## Full source diff `git diff 8e447bc e53b357 -- src/diaspextract.cpp` (new-file line numbers are in the @@ headers; b592804 has the same src)

```diff
diff --git a/src/diaspextract.cpp b/src/diaspextract.cpp
index ccdbfcb..9930ac7 100644
--- a/src/diaspextract.cpp
+++ b/src/diaspextract.cpp
@@ -37,6 +37,7 @@
 #include <fstream>
 #include <atomic>
 #include <mutex>
+#include <condition_variable>   // [outer] the MS1 pick worker
 #include <thread>
 #include <map>
 #include <string>
@@ -44,6 +45,7 @@
 #include <cstdlib>     // getenv
 #include <cstring>     // memcpy
 #include <optional>
+#include <memory>      // [outer] unique_ptr
 #include <time.h>      // clock_gettime(CLOCK_THREAD_CPUTIME_ID): [dnoise] filter CPU
 #ifdef __GLIBC__
 #include <malloc.h>    // mallinfo2: retained-vs-live at the milestones [mem]
@@ -111,8 +113,9 @@ namespace
   /// [perf-instr] Per-phase wall/CPU/RSS accounting, printed unconditionally at the end.
   struct PhaseStat { double wall = 0; double cpu = 0; long rss_end_mb = 0; int n = 0; bool nested = false; };
   /// [perf-instr] A phase opened inside another (the tile loop's read/sort/write inside WINDOW_LOOP)
-  /// is marked enclosed and left out of the TOTAL. Phases are opened only on the master thread.
-  inline int& phase_depth_() { static int d = 0; return d; }
+  /// is marked enclosed and left out of the TOTAL. Phases are opened on the master thread, and with pipelined
+  /// tiles also by the writer task while the master reads (atomic depth, locked phaseAdd_).
+  inline std::atomic<int>& phase_depth_() { static std::atomic<int> d{0}; return d; }
   inline double& flush_wall_() { static double v = 0; return v; }   // [perf-load] pick inside LOAD
   /// [task-err] An exception escaping an OpenMP task terminates the process with no message. Task bodies catch
   /// everything and hand the first exception here; the code after the loop rethrows it once the tasks have joined.
@@ -129,6 +132,289 @@ namespace
     if (want && String(want) == site)
       throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, String("[task-err] injected failure in task ") + site, site);
   }
+  /// [pipe] Helper tasks of teamFor_ created and not yet started, over every call: capped at the team size, so
+  /// stale helpers (started after their loop ran out) cannot pile up towards the libgomp cliff (64 x nthreads).
+  inline std::atomic<int>& teamHelpersQueued_() { static std::atomic<int> q{0}; return q; }
+  /// [pipe] A loop that the pipelined tile loop runs on the window team's driver (the tile reader and writer).
+  /// Outside a parallel region the call sites keep their `omp parallel for`. Inside the team a `parallel for`
+  /// would open a NESTED team -- fresh threads on the cores the windows use -- so the loop runs here instead:
+  /// the caller pulls `chunk` indices at a time from a shared cursor, and up to one helper task per team
+  /// thread pulls with it once a thread is free. The caller never reaches a task scheduling point, so it is
+  /// never handed a window task (libgomp lets a thread waiting at a taskgroup end run ANY child of its task),
+  /// and it never waits for a helper to START: a helper that starts after the cursor ran out touches nothing
+  /// but its own reference to the cursor, so only helpers that claimed a chunk are waited for (seq_cst: a
+  /// helper raises `busy` before it claims). f(i, slot): `slot` = the puller's omp_get_thread_num(), unique
+  /// among the concurrent pullers (a thread pulls one chunk at a time and never nests a pull), for per-slot
+  /// scratch where a thread number was used. Every caller writes index-addressed results only, so the output
+  /// is the parallel for's. The first exception is rethrown here, after every claimed chunk has finished.
+  /// Helper tasks queue behind the band and score tasks, and while windows hold the threads they barely run
+  /// (scal-pipe-1 on kim: a heavy tile of a 60-min run read in 31-43 s at 64 threads, 5-7 s with the barrier). So the
+  /// loop is also published for teamAssist_: window code pulls a chunk at its natural break points, which
+  /// gives the I/O a share of the window threads without a nested team (libgomp starts fresh threads for every
+  /// nested region: scal-pipe-2).
+  struct PullJob_
+  {
+    std::atomic<long> cur{0}; std::atomic<int> busy{0}; std::exception_ptr err;
+    long n = 0, chunk = 1;
+    void (*call)(void*, long, int) = nullptr; void* fp = nullptr;
+    /// up to max_chunks chunks (all with max_chunks < 0), returns how many it claimed; `busy` is raised BEFORE
+    /// the first claim (see above)
+    long pull(const long max_chunks)
+    {
+      const int slot = omp_get_thread_num();
+      busy.fetch_add(1);
+      long a = 0, k = 0;
+      for (; (max_chunks < 0 || k < max_chunks) && (a = cur.fetch_add(chunk)) < n; ++k)
+      { try { for (long i = a, e = std::min(a + chunk, n); i < e; ++i) call(fp, i, slot); }
+        catch (...) { taskErr_(err); cur.store(n); } }
+      busy.fetch_sub(1);
+      return k;
+    }
+  };
+  inline std::mutex& pullMu_() { static std::mutex m; return m; }
+  inline std::vector<std::shared_ptr<PullJob_>>& pullJobs_() { static std::vector<std::shared_ptr<PullJob_>> v; return v; }
+  inline std::atomic<int>& pullLive_() { static std::atomic<int> n{0}; return n; }
+  /// [pipe] Help a live teamFor_ loop (the pipelined tile reader or writer) with up to max_chunks chunks; true if
+  /// it did any. One relaxed load when none is live. Called inside the window team only (slot = thread number).
+  inline bool teamAssist_(const long max_chunks)
+  {
+    if (pullLive_().load(std::memory_order_relaxed) == 0) return false;
+    std::shared_ptr<PullJob_> j;   // the copy keeps the job alive; its loop body is the caller's until it returns
+    { std::lock_guard<std::mutex> g(pullMu_());
+      for (const auto& p : pullJobs_()) if (p->cur.load(std::memory_order_relaxed) < p->n) { j = p; break; } }
+    return j && j->pull(max_chunks) > 0;
+  }
+  template <class F> static void teamFor_(long n, long chunk, F&& f)
+  {
+    if (n <= 0) return;
+    using FT = std::remove_reference_t<F>;
+    auto st = std::make_shared<PullJob_>();
+    st->n = n; st->chunk = chunk; st->fp = (void*)&f;
+    st->call = [](void* p, long i, int slot) { (*static_cast<FT*>(p))(i, slot); };
+    { std::lock_guard<std::mutex> g(pullMu_()); pullJobs_().push_back(st); }
+    ++pullLive_();
+    const int team = std::max(1, omp_get_num_threads());
+    const int nt = (int)std::min<long>((n + chunk - 1) / chunk, (long)team);
+    for (int t = 1; t < nt && teamHelpersQueued_().load() < team; ++t)
+    {
+      ++teamHelpersQueued_();
+      #pragma omp task default(none) firstprivate(st)
+      { --teamHelpersQueued_(); st->pull(-1); }
+    }
+    st->pull(-1);
+    { std::lock_guard<std::mutex> g(pullMu_());
+      auto& v = pullJobs_(); v.erase(std::remove(v.begin(), v.end(), st), v.end()); }
+    --pullLive_();
+    while (st->busy.load() != 0) std::this_thread::yield();
+    if (st->err) std::rethrow_exception(st->err);
+  }
+  /// [review] True on the pipelined tile loop's driver while it drives. Every window task is a child of the driver's
+  /// implicit task, so a taskloop's taskgroup end on the driver (libgomp then runs ANY queued child of the waiting task)
+  /// could hand it a whole window, stalling the reads and admissions: the [det] toTof() in the tile read reached one.
+  /// parTasks_ keeps every pass the driver reaches inline instead (nt = 1 is forTasks_'s serial branch: the same result).
+  inline bool& onPipeDriver_() { static thread_local bool v = false; return v; }
+  /// [serial] Task count for one of a window's data-parallel passes over n items: at most 16 and none smaller than
+  /// min_per; 1 (run inline) outside a parallel region and on the pipe driver. A bounded COUNT, never a grainsize over
+  /// data: libgomp runs a whole taskloop inline once the team's task count passes 64 x nthreads ([gomp-cliff]).
+  inline long parTasks_(size_t n, size_t min_per)
+  {
+    const long cap = omp_in_parallel() && !onPipeDriver_() ? std::min(16, omp_get_num_threads()) : 1;
+    return std::max(1L, std::min(cap, (long)(n / std::max<size_t>(min_per, 1))));
+  }
+  /// [serial] body(c) for c in [0, nt): nt tasks of the current team (the creating thread waits in the taskloop's
+  /// taskgroup and runs its own children, so a busy pool degrades to the serial loop), or inline for nt <= 1.
+  /// The first exception is rethrown once every task has joined.
+  template <class F> void forTasks_(long nt, F&& body)
+  {
+    if (nt <= 1) { body(0L); return; }
+    std::exception_ptr err;
+    #pragma omp taskloop num_tasks(nt) default(shared)
+    for (long c = 0; c < nt; ++c)
+    { try { body(c); } catch (...) { taskErr_(err); } }
+    if (err) std::rethrow_exception(err);
+  }
+  /// [serial] Merge-path co-rank: how many of the first r elements of the STABLE merge of a[0, m) and b[0, k) come
+  /// from a (a first on ties, as std::merge takes them).
+  template <class T, class Less> size_t coRank_(size_t r, const T* a, size_t m, const T* b, size_t k, const Less& less)
+  {
+    size_t lo = r > k ? r - k : 0, hi = std::min(r, m);
+    while (lo < hi)
+    {
+      const size_t i = lo + (hi - lo) / 2, j = r - i;   // i < m and 1 <= j <= k here
+      if (!less(b[j - 1], a[i])) lo = i + 1; else hi = i;
+    }
+    return lo;
+  }
+  /// [serial] Sort a[0, n) as nt tasks: nt chunks std::sort-ed, then pairwise std::merge levels, each pair's output
+  /// cut at merge-path co-ranks into pieces of about n / nt, ping-ponging with one scratch buffer of n elements.
+  /// The result equals std::sort's whenever `less` is a TOTAL order (no two elements equivalent: the sorted sequence
+  /// is then unique). Under a weaker order equivalent elements may come out in another order.
+  template <class T, class Less> void parallelSort_(T* a, size_t n, const Less& less, long nt)
+  {
+    static_assert(std::is_trivially_copyable<T>::value, "parallelSort_ moves elements through raw scratch memory");
+    if (nt <= 1 || n < 2 * (size_t)nt) { std::sort(a, a + n, less); return; }
+    vector<size_t> run(nt + 1);
+    for (long c = 0; c <= nt; ++c) run[c] = (size_t)c * n / (size_t)nt;
+    forTasks_(nt, [&](long c) { std::sort(a + run[c], a + run[c + 1], less); });
+    // uninitialised scratch, first touched by the merge tasks (an implicit-lifetime type: malloc creates the objects)
+    std::unique_ptr<T, void (*)(T*)> buf(static_cast<T*>(std::malloc(n * sizeof(T))), [](T* p) { std::free(p); });
+    if (!buf) throw std::bad_alloc();
+    T* src = a; T* dst = buf.get();
+    struct Piece { size_t s, mid, e, r0, r1; };   // merge src[s, mid) with src[mid, e); output ranks [r0, r1)
+    while (run.size() > 2)
+    {
+      const size_t nr = run.size() - 1;
+      vector<size_t> nxt{0};
+      vector<Piece> pcs;
+      for (size_t p = 0; p < nr; p += 2)
+      {
+        const size_t s = run[p], mid = run[p + 1], e = p + 1 < nr ? run[p + 2] : mid;   // an odd last run is copied
+        const size_t len = e - s, np = std::max<size_t>(1, (len * (size_t)nt + n - 1) / n);
+        for (size_t q = 0; q < np; ++q) pcs.push_back({s, mid, e, q * len / np, (q + 1) * len / np});
+        nxt.push_back(e);
+      }
+      forTasks_((long)pcs.size(), [&](long c) {
+        const Piece& p = pcs[(size_t)c];
+        const T* A = src + p.s; const T* B = src + p.mid;
+        const size_t m = p.mid - p.s, k = p.e - p.mid;
+        const size_t i0 = coRank_(p.r0, A, m, B, k, less), i1 = coRank_(p.r1, A, m, B, k, less);
+        std::merge(A + i0, A + i1, B + (p.r0 - i0), B + (p.r1 - i1), dst + p.s + p.r0, less);
+      });
+      std::swap(src, dst); run.swap(nxt);
+    }
+    if (src != a)
+      forTasks_(nt, [&](long c) { const size_t lo = (size_t)c * n / (size_t)nt, hi = (size_t)(c + 1) * n / (size_t)nt;
+                                  std::copy(src + lo, src + hi, a + lo); });
+  }
+
+  /// [outer] std::sort's result, computed in parallel, for a comparator that is a strict TOTAL order on the elements
+  /// present (no two equivalent): the sorted sequence is then unique, so any correct sort returns exactly what std::sort
+  /// returns. Chunks are sorted concurrently and merged pairwise; each merge is cut into equal output pieces by merge path
+  /// (exactly std::merge's sequence). Serial std::sort when small, on one thread, or inside a parallel region. Callers
+  /// guarantee the total order by construction (a unique last key) or check the result (sortExact_).
+  template <typename T, typename Less>
+  void parallelSortTotal_(std::vector<T>& v, Less less)
+  {
+    const size_t n = v.size();
+    const int nt = omp_get_max_threads();
+    if (n < ((size_t)1 << 15) || nt < 2 || omp_in_parallel()) { std::sort(v.begin(), v.end(), less); return; }
+    size_t nc = 1;                                              // a power of two, about one chunk per thread
+    while (nc < (size_t)nt && n / (2 * nc) >= 4096) nc *= 2;
+    auto bound = [n, nc](size_t c) { return c * n / nc; };     // chunk c is [bound(c), bound(c + 1))
+    std::vector<T> buf(n);
+    T* src = v.data(); T* dst = buf.data();
+    #pragma omp parallel for schedule(dynamic, 1)
+    for (long c = 0; c < (long)nc; ++c) std::sort(src + bound((size_t)c), src + bound((size_t)c + 1), less);
+    for (size_t w = 1; w < nc; w *= 2)                          // runs of w chunks, merged pairwise
+    {
+      const size_t nm = nc / (2 * w), np = std::max<size_t>(1, (2 * (size_t)nt + nm - 1) / nm);   // merges, pieces per merge
+      #pragma omp parallel for schedule(dynamic, 1)
+      for (long q = 0; q < (long)(nm * np); ++q)
+      {
+        const size_t m = (size_t)q / np, p = (size_t)q % np;
+        const size_t a0 = bound(2 * m * w), b0 = bound((2 * m + 1) * w), b1 = bound((2 * m + 2) * w);
+        const T* a = src + a0; const T* b = src + b0;
+        const size_t na = b0 - a0, nb = b1 - b0, k0 = p * (na + nb) / np, k1 = (p + 1) * (na + nb) / np;
+        // merge path: how many of std::merge(a, b)'s first k outputs come from a (a[i] precedes b[j] iff !less(b[j], a[i]))
+        auto corank = [&](size_t k) {
+          size_t lo = k > nb ? k - nb : 0, hi = std::min(k, na);
+          while (lo < hi) { const size_t i = lo + (hi - lo) / 2; if (!less(b[k - i - 1], a[i])) lo = i + 1; else hi = i; }
+          return lo;
+        };
+        const size_t i0 = corank(k0), i1 = corank(k1);
+        std::merge(a + i0, a + i1, b + (k0 - i0), b + (k1 - i1), dst + a0 + k0, less);
+      }
+      std::swap(src, dst);
+    }
+    if (src != v.data()) v.swap(buf);
+  }
+
+  /// [outer] Sorts @p v exactly as std::sort(v.begin(), v.end(), less) does, in parallel whenever that is provably the
+  /// same result: a permutation is sorted in parallel (index as the last key, so a total order) and, when no two
+  /// neighbours are equivalent under @p less (every element then has one place, and std::sort's sequence is that one),
+  /// gathered. With an equivalent pair, @p v -- still untouched -- goes through std::sort, so the order of equal keys is
+  /// std::sort's own. Returns the number of equal-key neighbours of the result (the same count either way).
+  template <typename T, typename Less>
+  size_t sortExact_(std::vector<T>& v, Less less)
+  {
+    const size_t n = v.size();
+    auto serial = [&]() { std::sort(v.begin(), v.end(), less); size_t t = 0;
+                          for (size_t i = 1; i < n; ++i) if (!less(v[i - 1], v[i])) ++t;
+                          return t; };
+    if (n < ((size_t)1 << 15) || n > (size_t)std::numeric_limits<uint32_t>::max() || omp_get_max_threads() < 2 || omp_in_parallel())
+      return serial();
+    std::vector<uint32_t> perm(n);
+    #pragma omp parallel for schedule(static)
+    for (long i = 0; i < (long)n; ++i) perm[(size_t)i] = (uint32_t)i;
+    parallelSortTotal_(perm, [&v, &less](uint32_t a, uint32_t b) {
+      if (less(v[a], v[b])) return true;
+      if (less(v[b], v[a])) return false;
+      return a < b; });
+    size_t ties = 0;
+    #pragma omp parallel for schedule(static) reduction(+ : ties)
+    for (long i = 1; i < (long)n; ++i) if (!less(v[perm[(size_t)i - 1]], v[perm[(size_t)i]])) ++ties;
+    if (ties) return serial();
+    std::vector<T> out(n);
+    #pragma omp parallel for schedule(static)
+    for (long i = 0; i < (long)n; ++i) out[(size_t)i] = v[perm[(size_t)i]];
+    v.swap(out);
+    return 0;
+  }
+
+#if defined(__GLIBCXX__) && defined(_GLIBCXX_RELEASE) && _GLIBCXX_RELEASE == 13
+  /// [outer] libstdc++ 13's std::__introsort_loop with the right part of each cut handed to a task: the two parts are
+  /// disjoint and each is processed by the same calls in the same order as in the serial loop, so the array ends
+  /// exactly as std::sort leaves it, equal keys included. Small parts run inline (bounded task count).
+  template <typename It, typename Size, typename Cmp>
+  void introsortLoopPar_(It first, It last, Size depth, Cmp cmp)
+  {
+    while (last - first > 16)   // libstdc++'s _S_threshold
+    {
+      if (depth == 0) { std::__partial_sort(first, last, last, cmp); return; }
+      --depth;
+      It cut = std::__unguarded_partition_pivot(first, last, cmp);
+      if (last - cut >= 16384)
+      {
+        #pragma omp task default(shared) firstprivate(cut, last, depth, cmp)
+        introsortLoopPar_(cut, last, depth, cmp);
+      }
+      else introsortLoopPar_(cut, last, depth, cmp);
+      last = cut;
+    }
+  }
+#endif
+
+  /// [outer] std::sort(v.begin(), v.end(), less), equal keys in std::sort's own order, in parallel where the standard
+  /// library is libstdc++ 13 (the release compiler): its std::__sort is introsort loop + final insertion sort, replayed
+  /// here with tasks (introsortLoopPar_) and the same final pass. Any other library, small inputs or a caller already
+  /// inside a parallel region: std::sort itself.
+  template <typename T, typename Less>
+  void stdSortPar_(std::vector<T>& v, Less less)
+  {
+#if defined(__GLIBCXX__) && defined(_GLIBCXX_RELEASE) && _GLIBCXX_RELEASE == 13
+    if (v.size() >= ((size_t)1 << 15) && omp_get_max_threads() > 1 && !omp_in_parallel())
+    {
+      // DIASPEXTRACT_OUTER_VERIFY: also sort a copy with std::sort and report whether the two sequences are identical
+      static const bool verify = std::getenv("DIASPEXTRACT_OUTER_VERIFY") != nullptr;
+      std::vector<T> ref;
+      if (verify) { ref = v; std::sort(ref.begin(), ref.end(), less); }
+      auto cmp = __gnu_cxx::__ops::__iter_comp_iter(less);
+      const auto first = v.begin(), last = v.end();
+      const auto depth = std::__lg(last - first) * 2;   // as std::__sort
+      #pragma omp parallel
+      #pragma omp single
+      {
+        #pragma omp taskgroup
+        introsortLoopPar_(first, last, depth, cmp);
+      }
+      std::__final_insertion_sort(first, last, cmp);
+      if (verify) std::fprintf(stderr, "[outer] stdSortPar_ verify: %zu elements, %s\n", v.size(),
+                               ref == v ? "identical to std::sort" : "DIFFERENT from std::sort");
+      return;
+    }
+#endif
+    std::sort(v.begin(), v.end(), less);
+  }
   /// [gate-dump] Diagnostics, read-only: with DIASPEXTRACT_GATE_DUMP=<out.tsv> and DIASPEXTRACT_GATE_TARGETS=<tsv: id mz
   /// rt_sec im z>, every precursor within 20 ppm (mono or +-1 isotope at the target's charge), 20 s and 0.05 1/K0 of a
   /// target writes one PRECURSOR row (fragments passing the gate) and one row per fragment trace within 0.05 1/K0 and
@@ -175,6 +461,8 @@ namespace
   }
   static void phaseAdd_(const std::string& name, double w0, double c0, bool nested)
   {
+    // [pipe] the pipelined tile loop times the tile read (driver) and the tile write (writer task) concurrently
+    static std::mutex m; std::lock_guard<std::mutex> g(m);
     auto& st = phase_stats_()[name];
     if (st.n++ == 0) phase_order_().push_back(name);
     st.wall += phase_clock_() - w0; st.cpu += cpu_seconds_() - c0;
@@ -219,6 +507,7 @@ namespace
   double mono_pos_min_ratio_ = 0.2, mono_pos_im_box_ = 0.0, mono_pos_extend_ = 0.6;   ///< [monocheck-v2] charge:mono_position_* (im_box 0 = auto)
   bool mono_pos_iterate_ = true;     ///< [monocheck-v2] charge:mono_position_iterate
   String mono_check_stamp_;          ///< [monocheck] the spx:monocheck run stamp, filled by inferPrecursors_
+  bool iso_closest_ = false;         ///< [isotol] charge:iso_partner == "closest": the nearest candidate in RT and 1/K0, not the first in m/z
   bool var_support_ = false;         ///< [Q1] Pearson variance over union support, not full grid G (0-pad fix)
   bool short_conc_ = false;          ///< [short] gate:short_traces == "concentric": span test for traces too short for Pearson
   double short_center_tol_ = 0.5;    ///< [short] gate:short_center_tol, fraction of the precursor half-span
@@ -245,6 +534,7 @@ namespace
   double anchor_rescue_corr_ = 0.7;  ///< [anchor] gate:anchor_rescue_corr
   int anchor_max_rescued_ = 50;      ///< [anchor] gate:anchor_max_rescued
   bool post_fusion_cap_ = false;     ///< [recap] assembly:post_fusion_cap: carry the cap key per peak, re-cap after the twin fold
+  bool twin_ext_mark_ = false;       ///< [twin-rt] assembly:twin_rt_match ext: mark spectra whose mono v2's extension placed (spx_mono_ext, never written)
   double foreign_w_ = 1.0;           ///< [foreign] assembly:foreign_precursor_weight (1 = off, 0 removes)
   double foreign_ppm_ = 10.0;        ///< [foreign] assembly:foreign_precursor_ppm
   double foreign_dim_ = 0.015;       ///< [foreign] assembly:foreign_precursor_dim
@@ -505,6 +795,64 @@ namespace
   static_assert(sizeof(Trace) == 40, "Trace must stay 40 bytes: it is the largest structure in the tool "
                                     "(2.1e9 records on a 2-h file), and a silent 8-byte regrowth costs ~16 GiB");
 
+  /// [serial] `dst.absorb()` of every source in order, each source's records rebased (off += its base; frame0 and
+  /// bframe += its frame shift) and appended to `out`: the serial loop's result byte for byte (sizes and capacities
+  /// included), with the copies run as bounded tasks at prefix-summed offsets. The parallel form needs an empty
+  /// `dst` and `out` and every source's bins index-parallel to its inten (or absent) -- what every caller has; any
+  /// other input runs the serial loop. The sources are emptied either way.
+  inline void absorbAll_(TraceStore& dst, vector<Trace>& out, const vector<std::pair<TraceStore*, vector<Trace>*>>& src,
+                         const vector<uint32_t>& fshift)
+  {
+    const size_t ns = src.size();
+    vector<size_t> ib(ns + 1, 0), tb(ns + 1, 0);   // arena / record prefix sums
+    bool par = dst.inten.empty() && dst.bins.empty() && out.empty(), any_bins = false;
+    for (size_t s = 0; s < ns; ++s)
+    {
+      const TraceStore& o = *src[s].first;
+      if (!o.bins.empty()) { any_bins = true; par &= (o.bins.size() == o.inten.size()); }
+      ib[s + 1] = ib[s] + o.inten.size(); tb[s + 1] = tb[s] + src[s].second->size();
+    }
+    if (!par)
+    {
+      out.reserve(out.size() + tb[ns]);
+      for (size_t s = 0; s < ns; ++s)
+      {
+        const uint32_t base = dst.absorb(*src[s].first), fs = fshift[s];
+        for (auto& t : *src[s].second) { t.off += base; t.frame0 += fs; t.bframe += fs; out.push_back(std::move(t)); }
+        vector<Trace>().swap(*src[s].second);
+      }
+      return;
+    }
+    // absorb() throws at the first source that would reach 2^32 - 1 floats; the prefix sums are monotone
+    if (ib[ns] >= (size_t)std::numeric_limits<uint32_t>::max())
+      throw OpenMS::Exception::OutOfRange(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
+    // absorb()'s bins: once any source carries bins they are index-parallel to inten, zero where a source has none
+    dst.inten.resize(ib[ns]); if (any_bins) dst.bins.resize(ib[ns], 0);
+    out.resize(tb[ns]);
+    // call f(s, a, e) for the part [a, e) of source s that falls in slice c of nt of the concatenation `pre`
+    auto slices = [ns](const vector<size_t>& pre, long c, long nt, auto&& f) {
+      const size_t N = pre[ns], lo = (size_t)c * N / (size_t)nt, hi = (size_t)(c + 1) * N / (size_t)nt;
+      size_t s = (size_t)(std::upper_bound(pre.begin(), pre.end(), lo) - pre.begin()) - 1;
+      for (; s < ns && pre[s] < hi; ++s)
+      { const size_t a = std::max(lo, pre[s]) - pre[s], e = std::min(hi, pre[s + 1]) - pre[s]; if (a < e) f(s, a, e); }
+    };
+    const long nt = parTasks_(ib[ns] + 8 * tb[ns], 1 << 20);   // a record is ~8 floats of copying
+    forTasks_(nt, [&](long c) {
+      slices(ib, c, nt, [&](size_t s, size_t a, size_t e) {
+        const TraceStore& o = *src[s].first;
+        std::copy(o.inten.begin() + a, o.inten.begin() + e, dst.inten.begin() + ib[s] + a);
+        if (!o.bins.empty()) std::copy(o.bins.begin() + a, o.bins.begin() + e, dst.bins.begin() + ib[s] + a);
+      });
+      slices(tb, c, nt, [&](size_t s, size_t a, size_t e) {
+        const uint32_t base = (uint32_t)ib[s], fs = fshift[s];
+        const vector<Trace>& r = *src[s].second;
+        for (size_t q = a; q < e; ++q) { Trace t = r[q]; t.off += base; t.frame0 += fs; t.bframe += fs; out[tb[s] + q] = t; }
+      });
+    });
+    for (size_t s = 0; s < ns; ++s)
+    { vector<float>().swap(src[s].first->inten); vector<int16_t>().swap(src[s].first->bins); vector<Trace>().swap(*src[s].second); }
+  }
+
   /// Span accessors take the owning store explicitly (no per-record back-pointer); bounds asserted in debug builds.
   inline float xv(const TraceStore& s, const Trace& t, size_t k)
   { assert(t.off + k < s.inten.size()); return s.inten[t.off + k]; }
@@ -560,6 +908,35 @@ namespace
       if (real(s, t, k)) { rt.push_back(rtAtSpan(s, t, k)); v.push_back((double)xv(s, t, k)); }
   }
 
+  /// [fwhm] FWHM (seconds) from the trace's own XIC: apex, then outwards to half maximum with linear interpolation;
+  /// a side that never reaches half maximum ends at the first/last point. -1 below 3 points.
+  inline double xicFwhm(const TraceStore& s, const Trace& tr)
+  {
+    if (tr.np() < 3) return -1.0;
+    vector<double> prt, pv; packReal(s, tr, prt, pv);
+    size_t ap = 0;
+    for (size_t i = 1; i < pv.size(); ++i) if (pv[i] > pv[ap]) ap = i;
+    const double half = pv[ap] * 0.5;
+    double lo = prt[0], hi = prt[pv.size() - 1];
+    for (size_t i = ap; i > 0; --i)
+      if (pv[i - 1] <= half)
+      {
+        const double d = pv[i] - pv[i - 1];
+        const double f = d > 0 ? (pv[i] - half) / d : 0.0;
+        lo = prt[i] - f * (prt[i] - prt[i - 1]);
+        break;
+      }
+    for (size_t i = ap; i + 1 < pv.size(); ++i)
+      if (pv[i + 1] <= half)
+      {
+        const double d = pv[i] - pv[i + 1];
+        const double f = d > 0 ? (pv[i] - half) / d : 0.0;
+        hi = prt[i] + f * (prt[i + 1] - prt[i]);
+        break;
+      }
+    return hi - lo;
+  }
+
   /// Trim a trace to at most `cap` seconds around its apex, AFTER detection and valley splitting, so
   /// peak ownership is unchanged (rationale: trace:max_span_sec). Only the span fields change and no
   /// bytes are copied; the arena keeps the trimmed bytes until a compaction pass.
@@ -610,7 +987,9 @@ namespace
       if (!needed[i]) { if (tr[i].np() > 0) ++freed; tr[i].freeProfile(); continue; }
       if (tr[i].len > 0) ids.push_back((uint32_t)i);     // a zero-length span owns no bytes
     }
-    sort(ids.begin(), ids.end(), [&](uint32_t a, uint32_t b) { return tr[a].off < tr[b].off; });
+    // [outer] valid spans have distinct offsets (equal ones overlap and throw below either way), so with the index as a
+    // last key the order is total and the parallel sort returns std::sort's
+    parallelSortTotal_(ids, [&](uint32_t a, uint32_t b) { return tr[a].off != tr[b].off ? tr[a].off < tr[b].off : a < b; });
     uint64_t prev_end = 0;
     for (uint32_t i : ids)
     {
@@ -664,6 +1043,7 @@ namespace
     double im = 0.0;
     size_t trace_idx = 0;    ///< index into ms1 traces
     bool guessed = false;    ///< [way-4] charge was DEFAULTED, not isotope-supported
+    bool mono_ext = false;   ///< [twin-rt] the monoisotope was placed by monocheck v2's extension (B)
     int n_isotopes = 0;      ///< [Q4] isotope peaks behind the mono call (0/1 = weak, mono ±1.00335 uncertain)
   };
 
@@ -719,6 +1099,54 @@ namespace
     return t;
   }
 
+  /// [outer] The span length makeSpan gives @p mt: its points' frame range, 0 without points. Throws as makeSpan does.
+  inline size_t spanLength(const MassTrace& mt, const TraceStore& store)
+  {
+    const Size np = mt.getSize();
+    if (np == 0) return 0;
+    uint32_t f0 = std::numeric_limits<uint32_t>::max(), f1 = 0;
+    for (Size i = 0; i < np; ++i) { const uint32_t f = store.frameOf(mt[i].getRT()); f0 = std::min(f0, f); f1 = std::max(f1, f); }
+    const size_t L = (size_t)f1 - f0 + 1;
+    if (L >= 65536) throw OpenMS::Exception::OutOfRange(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
+    return L;
+  }
+
+  /// [outer] toTrace with the span placed at arena offset @p off (already sized and zero) instead of appended: the same
+  /// statements as toTrace + makeSpan, so the same Trace and the same arena bytes when @p off is where the append would
+  /// have put it. @p pts is the caller's scratch.
+  inline Trace toTraceAt(const MassTrace& mt, TraceStore& store, size_t off, vector<pair<uint32_t, float>>& pts)
+  {
+    const std::string& mz_est = mzEstimator();
+    double mz;
+    if (mz_est == "apex" && mt.getSize() > 0) mz = mt[mt.findMaxByIntPeak(false)].getMZ();
+    else if (mz_est == "median" && mt.getSize() > 0) { MassTrace m2 = mt; m2.updateMedianMZ(); mz = m2.getCentroidMZ(); }
+    else mz = mt.getCentroidMZ();
+    const Size np = mt.getSize();
+    pts.clear();
+    for (Size i = 0; i < np; ++i) pts.emplace_back(store.frameOf(mt[i].getRT()), (float)mt[i].getIntensity());
+    Trace t;
+    if (!pts.empty())
+    {
+      sort(pts.begin(), pts.end());
+      const uint32_t f0 = pts.front().first, f1 = pts.back().first;
+      const size_t L = (size_t)f1 - f0 + 1;
+      if (L >= 65536) throw OpenMS::Exception::OutOfRange(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
+      t.frame0 = f0; t.len = (uint16_t)L; t.off = (uint32_t)off;
+      float best = -1.0f; uint16_t npt = 0;
+      for (const auto& q : pts)
+      {
+        const size_t k = q.first - f0;
+        if (store.inten[t.off + k] == 0.0f) ++npt;      // one point per frame; a repeat overwrites
+        store.inten[t.off + k] = q.second;
+        if (q.second > best) { best = q.second; t.apex = (uint16_t)k; }
+      }
+      t.npts = npt;
+    }
+    t.mz = mz; t.im = mt.getCentroidIM();
+    setRtFrame(store, t, mt.getCentroidRT());   // [soa-rt] a frame time, stored as an offset
+    return t;
+  }
+
 
   /// [compact] Quantised per-peak store, 10 B/peak, far finer than every downstream tolerance:
   ///   m/z : uint32 at 1e-5 Da     (0.007 ppm at m/z 1400)
@@ -1013,18 +1441,24 @@ namespace
     // single linkage along 1/K0 with a link of im_slice_merge_, the whole group within 2x that (one ion's 2-3 slices;
     // measured slice spacing median 0.008, q90 0.014, max 0.019 at the 0.01 picker box)
     const long tol_q = im_slice_merge_ >= 0.0 ? (long)llround(im_slice_merge_ * IM_Q) : -1, span_q = 2 * tol_q;
+    // [serial] Frames convert and merge independently, so they run as tasks over frame chunks, each frame compacted
+    // within its own range (its cursor starts at its first peak and never passes the read position, as the global
+    // cursor never did); the frames are then closed up in order -- the one-cursor loop's layout, byte for byte.
+    const long nt = parTasks_(sl.tof.size(), 1 << 17);
+    vector<uint32_t> nkept(F);                               // the frame's peaks after the merge
+    vector<long long> mc(nt, 0), fmc(nt, 0);                 // per task: peaks merged away, frames with a merge
+    forTasks_(nt, [&](long ch) {
     vector<pair<uint16_t, uint32_t>> run;                    // (imq, slab index) of one same-bin run
     vector<std::tuple<uint32_t, float, uint16_t>> cl;        // (first slab index, intensity, imq) of the run's groups
-    uint32_t w = 0;
     long long merged = 0, frames_merged = 0;
-    for (size_t i = 0; i < F; ++i)
+    for (size_t i = (size_t)ch * F / (size_t)nt; i < (size_t)(ch + 1) * F / (size_t)nt; ++i)
     {
       const double b = ax.factor(sl.frame_id[i]);
       sl.b[i] = b;
       const uint32_t lo = sl.frame_off[i], hi = sl.frame_off[i + 1];
       for (uint32_t k = lo; k < hi; ++k)
         sl.tof[k] = ax.tofOf((double)sl.tof[k] / MZ_Q, b);
-      sl.frame_off[i] = w;
+      uint32_t w = lo;
       bool any = false;
       for (uint32_t k = lo; k < hi;)
       {
@@ -1064,8 +1498,25 @@ namespace
         for (const auto& c : cl) { sl.tof[w] = t; sl.inten[w] = std::get<1>(c); sl.imq[w] = std::get<2>(c); ++w; }
         k = e;
       }
+      nkept[i] = w - lo;
       frames_merged += any;
     }
+    mc[ch] = merged; fmc[ch] = frames_merged;
+    });
+    long long merged = 0, frames_merged = 0;
+    for (long c = 0; c < nt; ++c) { merged += mc[c]; frames_merged += fmc[c]; }
+    uint32_t w = 0;
+    for (size_t i = 0; i < F; ++i)                           // close up: every destination lies at or before its source
+    {
+      const uint32_t lo = sl.frame_off[i], n = nkept[i];
+      if (w != lo)
+      {
+        std::copy(sl.tof.begin() + lo, sl.tof.begin() + lo + n, sl.tof.begin() + w);
+        std::copy(sl.inten.begin() + lo, sl.inten.begin() + lo + n, sl.inten.begin() + w);
+        std::copy(sl.imq.begin() + lo, sl.imq.begin() + lo + n, sl.imq.begin() + w);
+      }
+      sl.frame_off[i] = w; w += n;
+    }
     if (F) sl.frame_off[F] = w;
     sl.tof.resize(w); sl.inten.resize(w); sl.imq.resize(w);
     ledAdd_(LC_SLAB, (long long)sl.bytes() - led_b0);         // [ledger] give back what the merge freed
@@ -1141,10 +1592,6 @@ namespace
     // Membership IS inten > noise (no per-peak map); seeds are counted first so `order` is sized exactly.
     tp.frame_live.assign(F, 0);
     const double min_apex = snr * noise;
-    size_t n_seed = 0;
-    for (size_t f = 0; f < F; ++f)
-      for (uint32_t k = sl.frame_off[f]; k < sl.frame_off[f + 1]; ++k)
-        if ((double)sl.inten[k] > noise) { tp.frame_live[f] = 1; if ((double)sl.inten[k] > min_apex) ++n_seed; }
     // OpenMS: stable_sort ascending by intensity, then iterate in reverse -> among equal
     // intensities the LATER peak seeds first.
     auto cmp = [&](uint32_t a, uint32_t b) {
@@ -1152,16 +1599,8 @@ namespace
       return a > b;
     };
     const int nb = (int)bnd.size() - 1;
-    tp.order.resize(n_seed);
-    if (nb < 2)                                          // unbanded: one globally sorted list
-    {
-      size_t w = 0;
-      for (uint32_t k = 0; k < P; ++k)
-        if ((double)sl.inten[k] > noise && (double)sl.inten[k] > min_apex) tp.order[w++] = k;
-      sort(tp.order.begin(), tp.order.end(), cmp);
-      tp.seg = {0, n_seed};
-      return tp;
-    }
+    const bool banded = nb >= 2;                         // unbanded: one globally sorted list
+    const size_t nseg = banded ? (size_t)nb : 1;
     // Band of a peak: the same half-open [bnd[b], bnd[b+1]) partition the detector applies, found
     // by upper_bound so that empty bands (bnd[b] == bnd[b+1], reachable when nb exceeds the tof
     // range) are skipped exactly as the detector's own range test skips them.
@@ -1169,21 +1608,54 @@ namespace
     // bounds. The window's edges are asserted to enclose every cell's bins before this runs (a
     // loud throw); the clamp is the memory-safety floor under that assert.
     auto bandOf = [&](TofIdx t) {
+      if (!banded) return (size_t)0;
       const auto it = std::upper_bound(bnd.begin(), bnd.end(), t);
       if (it == bnd.begin()) return (size_t)0;
       return std::min((size_t)(it - bnd.begin() - 1), (size_t)(nb - 1));
     };
-    vector<size_t> cnt(nb, 0);
-    for (uint32_t k = 0; k < P; ++k)
-      if ((double)sl.inten[k] > noise && (double)sl.inten[k] > min_apex) ++cnt[bandOf(sl.tof[k])];
-    tp.seg.assign(nb + 1, 0);
-    for (int b = 0; b < nb; ++b) tp.seg[b + 1] = tp.seg[b] + cnt[b];
-    vector<size_t> cur(tp.seg.begin(), tp.seg.end() - 1);
-    for (uint32_t k = 0; k < P; ++k)
-      if ((double)sl.inten[k] > noise && (double)sl.inten[k] > min_apex) tp.order[cur[bandOf(sl.tof[k])]++] = k;
+    // [serial] Count, then distribute, as tasks over peak-balanced FRAME chunks (frame_live stays chunk-private):
+    // chunk c counts its seeds per band, the prefix over (band, chunk) is its write cursor, so every band receives
+    // its seeds in ascending peak index -- what the one-pass loops wrote. Chunk c owns peaks [kb(c), kb(c + 1)).
+    const long nt = parTasks_(P, 1 << 17);
+    vector<size_t> fc(nt + 1, F);
+    fc[0] = 0;
+    for (long c = 1; c < nt; ++c)
+      fc[c] = (size_t)(std::lower_bound(sl.frame_off.begin(), sl.frame_off.begin() + F, (uint32_t)((size_t)c * P / (size_t)nt)) - sl.frame_off.begin());
+    auto kb = [&](long c) { return fc[c] >= F ? (uint32_t)P : sl.frame_off[fc[c]]; };
+    vector<size_t> cnt((size_t)nt * nseg, 0);
+    forTasks_(nt, [&](long c) {
+      size_t* cc = &cnt[(size_t)c * nseg];
+      for (size_t f = fc[c]; f < fc[c + 1]; ++f)
+        for (uint32_t k = sl.frame_off[f]; k < sl.frame_off[f + 1]; ++k)
+          if ((double)sl.inten[k] > noise) { tp.frame_live[f] = 1; if ((double)sl.inten[k] > min_apex) ++cc[bandOf(sl.tof[k])]; }
+    });
+    tp.seg.assign(nseg + 1, 0);
+    vector<size_t> cur((size_t)nt * nseg);
+    size_t n_seed = 0;
+    for (size_t b = 0; b < nseg; ++b)
+    {
+      tp.seg[b] = n_seed;
+      for (long c = 0; c < nt; ++c) { cur[(size_t)c * nseg + b] = n_seed; n_seed += cnt[(size_t)c * nseg + b]; }
+    }
+    tp.seg[nseg] = n_seed;
+    tp.order.resize(n_seed);
+    forTasks_(nt, [&](long c) {
+      size_t* cc = &cur[(size_t)c * nseg];
+      for (uint32_t k = kb(c), ke = kb(c + 1); k < ke; ++k)
+        if ((double)sl.inten[k] > noise && (double)sl.inten[k] > min_apex) tp.order[cc[bandOf(sl.tof[k])]++] = k;
+    });
+    // [serial] A segment holding many seeds (the dense band) is itself sorted as tasks. The comparator is a TOTAL
+    // order (the index breaks every tie), so the sorted segment is unique: parallelSort_ returns std::sort's result.
+    auto sortSeg = [&](size_t b) {
+      const size_t n = tp.seg[b + 1] - tp.seg[b];
+      parallelSort_(tp.order.data() + tp.seg[b], n, cmp, parTasks_(n, 1 << 18));
+    };
+    if (!banded) { sortSeg(0); return tp; }
+    std::exception_ptr sort_err;   // [task-err]
     #pragma omp taskloop grainsize(1) default(shared)
     for (int b = 0; b < nb; ++b)
-      sort(tp.order.begin() + tp.seg[b], tp.order.begin() + tp.seg[b + 1], cmp);
+    { try { sortSeg((size_t)b); } catch (...) { taskErr_(sort_err); } }
+    if (sort_err) std::rethrow_exception(sort_err);
     buildTofIndex(sl, tp, tlo, thi);
     return tp;
   }
@@ -1379,15 +1851,28 @@ namespace
     // No `in.size() < 2` guard: a lone parent must split as it would among others (tile invariance).
     if (split_valleys <= 0.0 || in.empty()) return std::move(in);
     const TofAxis& ax = tofAxis();
-    nchunk = std::max(1, std::min<int>(nchunk, (int)in.size()));
+    // [serial] Every parent splits on its own (below), so neither the chunk count nor the cut points can change the
+    // output. A large window (>= 8192 parents per chunk) gets up to one chunk per team thread instead of `nchunk`,
+    // and the cuts sit at equal cumulative cost (real points + 8 per trace) rather than equal counts: a window's
+    // parents come band by band, most intense (longest) first, so equal counts put the longest traces together.
+    const size_t n_in = in.size();
+    const int team = omp_in_parallel() ? omp_get_num_threads() : 1;
+    nchunk = std::max(nchunk, std::min<int>(team, (int)std::min<size_t>(n_in / 8192, 1 << 20)));
+    nchunk = std::max(1, std::min<int>(nchunk, (int)n_in));
+    vector<size_t> cut(nchunk + 1, n_in);
+    cut[0] = 0;
+    { uint64_t tot = 0, acc = 0; int c = 1;
+      for (const Trace& t : in) tot += (uint64_t)t.npts + 8;
+      for (size_t q = 0; q < n_in && c < nchunk; ++q)
+      { acc += (uint64_t)in[q].npts + 8;
+        while (c < nchunk && acc * (uint64_t)nchunk >= tot * (uint64_t)c) cut[c++] = q + 1; } }
     vector<vector<Trace>> parts(nchunk);
     vector<TraceStore> stores(nchunk);                         // chunk-private arenas, merged after
-    const size_t n_in = in.size();
     std::exception_ptr task_err;   // [task-err]
     #pragma omp taskloop grainsize(1) default(shared)
     for (int ci = 0; ci < nchunk; ++ci)
     { try {
-      const size_t lo = (size_t)ci * n_in / nchunk, hi = (size_t)(ci + 1) * n_in / nchunk;
+      const size_t lo = cut[ci], hi = cut[ci + 1];
       TraceStore& cst = stores[ci];
       cst.setFrames(wst.rt_index, &wst.b);
       // One MassTrace in flight at a time. Per-trace detectPeaks equals the batch call: with
@@ -1441,12 +1926,9 @@ namespace
     // Reserve the merged arena once (absorb() does not); the chunk arenas stay live until absorbed.
     wst.inten.reserve(arena); if (any_bins) wst.bins.reserve(arena);
     vector<Trace> out; out.reserve(tot);
-    for (int ci = 0; ci < nchunk; ++ci)
-    {
-      const uint32_t base = wst.absorb(stores[ci]);
-      for (auto& t : parts[ci]) { t.off += base; out.push_back(std::move(t)); }
-      vector<Trace>().swap(parts[ci]);
-    }
+    vector<std::pair<TraceStore*, vector<Trace>*>> src(nchunk);   // [serial] absorbed in chunk order, copies as tasks
+    for (int ci = 0; ci < nchunk; ++ci) src[ci] = {&stores[ci], &parts[ci]};
+    absorbAll_(wst, out, src, vector<uint32_t>(nchunk, 0));
     return out;
   }
 
@@ -1801,8 +2283,11 @@ namespace
     PickCompactConsumer(PeakPickerIM& picker, map<WinKey, PeakSlab>& windows,
                         PeakMap& ms1, CompactStats& stats)
       : picker_(picker), windows_(windows), ms1_(ms1), stats_(stats) {}
+    /// [outer] the MS1 worker ends with the consumer, also when an exception leaves the load early
+    ~PickCompactConsumer() { stopMs1Worker_(); }
 
     size_t frames_seen = 0;
+    String ms1_pick_mode_;   ///< [outer] how the MS1 batches were picked, for the log (set by finish())
 
     /// [frames] A window's FROZEN frame table (rt, vendor id) with the lockstep cursor: every table
     /// frame the reader skipped (no raw peaks, an empty mobility slice) is appended EMPTY with the
@@ -1861,15 +2346,13 @@ namespace
       std::vector<CompactStats> st((size_t)n);          // per-frame stats, merged serially below
       PeakPickerIM picker = picker_;                    // Param is a deep-copy value type
       std::exception_ptr pick_err;                      // an exception escaping an OMP region aborts
-      // chunk 1: with chunk 8 a 64-frame batch made only 8 chunks = 8 workers
-      #pragma omp parallel for firstprivate(picker) schedule(dynamic, 1)
-      for (int i = 0; i < n; ++i)
+      auto pickOne = [&](const int i, PeakPickerIM& pk)
       {
         try
         {
           auto& s = buf_[(size_t)i];
           ensureIMArrayName(s);
-          if (s.getIMPeakType() != IMPeakType::IM_CENTROIDED) picker.pickIMCluster(s);
+          if (s.getIMPeakType() != IMPeakType::IM_CENTROIDED) pk.pickIMCluster(s);
           ensureIMArrayName(s);
           frt[(size_t)i] = s.getRT();
           fid[(size_t)i] = frameIdOf(s.getNativeID());
@@ -1883,6 +2366,22 @@ namespace
           #pragma omp critical(pick_err)
           if (!pick_err) pick_err = std::current_exception();
         }
+      };
+      if (!omp_in_parallel())
+      {
+        // chunk 1: with chunk 8 a 64-frame batch made only 8 chunks = 8 workers
+        #pragma omp parallel for firstprivate(picker) schedule(dynamic, 1)
+        for (int i = 0; i < n; ++i) pickOne(i, picker);
+      }
+      else
+      {
+        // [pipe] the pipelined tile reader, on the window team's driver: one picker copy per puller slot, made
+        // by the slot's first frame (a slot has one puller at a time)
+        std::vector<std::unique_ptr<PeakPickerIM>> pk((size_t)std::max(1, omp_get_num_threads()));
+        teamFor_(n, 1, [&](long i, int slot) {
+          std::unique_ptr<PeakPickerIM>& p = pk[(size_t)slot];
+          if (!p) p.reset(new PeakPickerIM(picker));
+          pickOne((int)i, *p); });
       }
       if (pick_err) std::rethrow_exception(pick_err);
       // Append in arrival order per window, the windows of this batch in parallel: a window's
@@ -1908,8 +2407,7 @@ namespace
       const size_t n_ms1 = ms1_.size();
       std::atomic<long long> slab_b{0};   // [ledger] what this batch actually touched
       std::exception_ptr pad_err;
-      #pragma omp parallel for schedule(dynamic, 1)
-      for (long w = 0; w < (long)per_win.size(); ++w)
+      auto appendWin = [&](const long w)
       {
         Batch& bw = per_win[(size_t)w];
         for (int i : bw.idx)
@@ -1927,7 +2425,13 @@ namespace
           bw.slab->append(frt[(size_t)i], fid[(size_t)i], &scratch_mzq_[o], &scratch_inten_[o], &scratch_imq_[o], kept[(size_t)i], exp_f);
           slab_b += (long long)kept[(size_t)i] * 10 + 24;   // [ledger] touched bytes: 10 B/peak + the frame's table row
         }
+      };
+      if (!omp_in_parallel())
+      {
+        #pragma omp parallel for schedule(dynamic, 1)
+        for (long w = 0; w < (long)per_win.size(); ++w) appendWin(w);
       }
+      else teamFor_((long)per_win.size(), 1, [&](long w, int) { appendWin(w); });   // [pipe] as the pick above
       ledAdd_(LC_SLAB, slab_b);
       if (pad_err) std::rethrow_exception(pad_err);
       flush_wall_() += phase_clock_() - _tf0;
@@ -1944,17 +2448,76 @@ namespace
       if (dnoise && dnoise->on && !dn_loader_checked_) { dnoise->checkLoader(); dn_loader_checked_ = true; }
       ms1_buf_.push_back(std::move(s));
       ++frames_seen;
-      if (ms1_buf_.size() >= kBatchMS1_()) flushMS1_();
+      if (ms1_buf_.size() >= ms1BatchNow_()) flushMS1Async_();
     }
 
+    /// Picks the buffered MS1 frames now, after the worker's batch (if any): the order of the MS1 map is the arrival order.
     void flushMS1_()
     {
-      const int n = (int)ms1_buf_.size();
+      waitMs1Worker_();
+      pickMS1Batch_(ms1_buf_);
+    }
+
+    /// [outer] Hands the buffered MS1 frames to the worker thread and returns to the reader, which decodes the next batch
+    /// meanwhile. The previous batch is picked and appended first, so batches still reach the MS1 map in arrival order,
+    /// and every frame is processed exactly as by flushMS1_: batch composition does not change the output (kBatch_).
+    void flushMS1Async_()
+    {
+      if (!ms1Async_()) { flushMS1_(); return; }
+      waitMs1Worker_();
+      ms1_inflight_.swap(ms1_buf_);   // ms1_buf_ takes the picked (empty) buffer back
+      ms1_buf_.clear();
+      if (!w_th_.joinable())
+      {
+        const int nthr = std::max(1, omp_get_max_threads());   // a new thread starts from the global default team size
+        w_th_ = std::thread([this, nthr] {
+          omp_set_num_threads(nthr);
+          std::unique_lock<std::mutex> lk(w_mu_);
+          for (;;)
+          {
+            w_cv_.wait(lk, [this] { return w_job_ || w_quit_; });
+            if (!w_job_) return;   // quit, nothing pending
+            lk.unlock();
+            std::exception_ptr err;
+            try { pickMS1Batch_(ms1_inflight_); } catch (...) { err = std::current_exception(); }
+            lk.lock();
+            w_err_ = err; w_job_ = false;
+            w_cv_.notify_all();
+          }
+        });
+      }
+      { std::lock_guard<std::mutex> g(w_mu_); w_job_ = true; }
+      w_cv_.notify_all();
+    }
+
+    /// [outer] Waits for the worker's batch and rethrows its error, if any.
+    void waitMs1Worker_()
+    {
+      if (!w_th_.joinable()) return;
+      std::unique_lock<std::mutex> lk(w_mu_);
+      w_cv_.wait(lk, [this] { return !w_job_; });
+      if (w_err_) { std::exception_ptr e = w_err_; w_err_ = nullptr; lk.unlock(); std::rethrow_exception(e); }
+    }
+
+    /// [outer] Lets the worker finish its batch and ends it (finish() and the destructor; an unreported error is dropped
+    /// here only when an exception is already unwinding the load).
+    void stopMs1Worker_()
+    {
+      if (!w_th_.joinable()) return;
+      { std::lock_guard<std::mutex> g(w_mu_); w_quit_ = true; }
+      w_cv_.notify_all();
+      w_th_.join();
+      w_quit_ = false;
+    }
+
+    void pickMS1Batch_(std::vector<MapType::SpectrumType>& buf)   // one MS1 batch, picked and appended to the MS1 map, then emptied
+    {
+      const int n = (int)buf.size();
       if (n == 0) return;
       const double _tf0 = phase_clock_();
       // [ledger] the buffered RAW MS1 frames, 20 B per raw peak, held until picked: pass 1's largest transient.
       long long raw_b = 0;
-      for (const auto& sp : ms1_buf_) raw_b += (long long)sp.size() * 20;
+      for (const auto& sp : buf) raw_b += (long long)sp.size() * 20;
       LedCharge _raw(LC_SCRATCH, raw_b);
       PeakPickerIM picker = picker_;
       std::exception_ptr pick_err;
@@ -1968,7 +2531,7 @@ namespace
       {
         try
         {
-          auto& s = ms1_buf_[(size_t)i];
+          auto& s = buf[(size_t)i];
           ensureIMArrayName(s);
           if (dn) dnoise->frame(s, dn_work.at((size_t)omp_get_thread_num()), dn_cnt[(size_t)i]);   // [dnoise] the raw points, before the pick
           if (s.getIMPeakType() != IMPeakType::IM_CENTROIDED) picker.pickIMCluster(s);
@@ -1984,7 +2547,7 @@ namespace
       if (pick_err) std::rethrow_exception(pick_err);
       if (dn) dnoise->add(dn_cnt);
       if (ms1HistOn_())
-        for (const auto& sp : ms1_buf_)
+        for (const auto& sp : buf)
         {
           long long c[5] = {0, 0, 0, 0, 0};
           for (const auto& pk : sp) { const float v = pk.getIntensity(); ++c[v < 100 ? 0 : v < 300 ? 1 : v < 1000 ? 2 : v < 10000 ? 3 : 4]; }
@@ -1992,10 +2555,10 @@ namespace
         }
       // [ms1-prune] after [ms1-hist] (which counts what was PICKED), before the charge below (which is then
       // the kept bytes)
-      if (ms1_prune && ms1_prune->on) ms1_prune->batch(ms1_buf_, [](const MSSpectrum&) { return true; });
-      { long long mb = 0; for (const auto& s : ms1_buf_) mb += (long long)s.size() * 20; ledAdd_(LC_MS1MAP, mb); }
-      for (auto& s : ms1_buf_) ms1_.addSpectrum(std::move(s));
-      ms1_buf_.clear();
+      if (ms1_prune && ms1_prune->on) ms1_prune->batch(buf, [](const MSSpectrum&) { return true; });
+      { long long mb = 0; for (const auto& s : buf) mb += (long long)s.size() * 20; ledAdd_(LC_MS1MAP, mb); }
+      for (auto& s : buf) ms1_.addSpectrum(std::move(s));
+      buf.clear();
       flush_wall_() += phase_clock_() - _tf0;
       loadTrim_();
     }
@@ -2023,6 +2586,9 @@ namespace
     void finish()
     {
       flushMS1_(); flush_();
+      stopMs1Worker_();
+      ms1_pick_mode_ = ms1Async_() ? "beside the reader on a worker thread, batches of " + String(ms1BatchNow_())
+                                   : "inside the reader's hand-over, batches of " + String(kBatchMS1_());
       // [frames] the tail of every delivered window's table; a table window that delivered nothing
       // gets no slab (it is counted as absent by the caller)
       for (auto& kv : tables_)
@@ -2064,6 +2630,24 @@ namespace
     PeakPickerIM& picker_;
     std::vector<MapType::SpectrumType> ms1_buf_;   // MS1 frames awaiting the parallel pick
     bool dn_loader_checked_ = false;               ///< [dnoise] checkLoader ran on the first MS1 frame
+    /// [outer] The MS1 worker: picks ms1_inflight_ while the reader fills ms1_buf_. w_job_ is set by the reader's thread
+    /// and cleared by the worker, both under w_mu_; the worker touches only its batch, the MS1 map, the prune, the dnoise
+    /// counts and the ledger (atomic), none of which the reader's thread uses before waitMs1Worker_ has returned.
+    std::vector<MapType::SpectrumType> ms1_inflight_;
+    std::thread w_th_;
+    std::mutex w_mu_;
+    std::condition_variable w_cv_;
+    bool w_job_ = false, w_quit_ = false;
+    std::exception_ptr w_err_;
+    /// [outer] DIASPEXTRACT_MS1_ASYNC=1: the MS1 batches are picked on the worker, beside the reader's decode of the next
+    /// batch. OFF by default: the worker's team is a second OpenMP team on the same places as the reader's (libgomp binds
+    /// a foreign thread's team from place 0), so at 64 threads a 60-min run's LOAD(stream) got 0.3 s slower, and its extra thread
+    /// arenas raised HeLa_19's peak RSS by 6 % for 0.5-0.9 s (scalfix/outer timing, 2026-10-01). Default: the MS1 batches
+    /// are picked inside the reader's hand-over, one full batch at a time (the behaviour before 2026-10-01).
+    static bool ms1Async_() { static const bool v = []{ const char* e = std::getenv("DIASPEXTRACT_MS1_ASYNC"); return e && *e && *e != '0'; }(); return v; }
+    /// [outer] Beside the reader two batches are in memory (one being picked, one filling), so each is half the
+    /// synchronous batch and the raw-frame residency stays what it was.
+    static size_t ms1BatchNow_() { return ms1Async_() ? std::max<size_t>(1, kBatchMS1_() / 2) : kBatchMS1_(); }
     map<WinKey, PeakSlab>& windows_;
     PeakMap& ms1_;
     CompactStats& stats_;
@@ -2111,8 +2695,7 @@ namespace
   {
     struct SortKey { double rt, mz; int charge; uint32_t n, idx; };
     vector<SortKey> keys(v.size());
-#pragma omp parallel for schedule(static)
-    for (long i = 0; i < (long)v.size(); ++i)
+    auto key = [&](const long i)
     {
       const MSSpectrum& a = v[i];
       keys[i].rt = a.getRT();
@@ -2120,7 +2703,13 @@ namespace
       keys[i].charge = a.getPrecursors().empty() ? 0 : a.getPrecursors()[0].getCharge();
       keys[i].n = (uint32_t)a.size();
       keys[i].idx = (uint32_t)i;
+    };
+    if (!omp_in_parallel())
+    {
+#pragma omp parallel for schedule(static)
+      for (long i = 0; i < (long)v.size(); ++i) key(i);
     }
+    else teamFor_((long)v.size(), 4096, [&](long i, int) { key(i); });   // [pipe] the pipelined tile writer
     sort(keys.begin(), keys.end(), [&v](const SortKey& ka, const SortKey& kb) {
       if (ka.rt != kb.rt) return ka.rt < kb.rt;
       if (ka.mz != kb.mz) return ka.mz < kb.mz;
@@ -2167,39 +2756,78 @@ namespace
   /// thread-invariant. This is bench/twin_merge.py, which priced it: docs/SAME-POSITION-DUPLICATION-2026-09-20.md.
   /// `v` in canonical order; survivors keep their places. Returns the number of spectra removed.
   /// [recap] `keyed`: every spectrum carries its peaks' cap keys as float data array 0; a fused peak keeps the max key.
-  static size_t mergeTwins_(vector<MSSpectrum>& v, double im_tol, bool keyed = false)
+  /// [twin-rt] `rt_tol` > 0 widens "same MS1 frame" to |dRT| <= rt_tol (assembly:twin_rt_frames): two calls of one
+  /// monoisotope at nearby frames (seeds of one ion whose apexes differ, or v2's extension onto another precursor's
+  /// monoisotope) fold like same-frame twins. Such a pair must also lie in one RT cell: the cell that owns a precursor
+  /// (`cells`: the cell edges, `cell_drt`: tile_drt; the tile loop's own test, (T - rt) > cell_drt), so a pair never
+  /// straddles a tile under any grouping and the output stays grouping- and thread-invariant. rt_tol 0 is the
+  /// same-frame relation (|dRT| <= 0 and one frame is one cell), bit for bit. `st` (optional) adds {pairs linked at one
+  /// frame, pairs linked across frames, near pairs refused at a cell edge, spectra the same-frame relation alone would
+  /// have removed, clusters spanning more than rt_tol}. `near_mode`, how a pair from two frames must match: 0 precursor
+  /// m/z within TWIN_PPM, as at one frame; 1 within BIN_PPM (one flight-time bin: one MS1 trace, or one bin at two
+  /// frames, is the monoisotope of both); 2 as 1, and one of the two carries the userParam spx_mono_ext (its mono was
+  /// placed by monocheck v2's extension), which mode 2 removes from every spectrum.
+  static size_t mergeTwins_(vector<MSSpectrum>& v, double im_tol, bool keyed = false, double rt_tol = 0.0,
+                            const vector<double>* cells = nullptr, double cell_drt = 0.0, std::array<size_t, 5>* st = nullptr,
+                            int near_mode = 0)
   {
     const double TWIN_PPM = 20.0, FUSE_PPM = 10.0;   // ponytail: the measured values, no option until another is measured
-    struct K { double rt, mz, im; int z; uint32_t i; };
+    // [twin-rt] one flight-time bin across frames: the per-frame calibration moves one bin's m/z by < 0.01 ppm, distinct
+    // monoisotope traces of one charge and 1/K0 at nearby frames sit >= 0.3 ppm apart (HeLa 10 ng: no pair in between)
+    const double BIN_PPM = 0.05;
+    struct K { double rt, mz, im; int z; uint32_t i, cell; bool ext; };
+    auto cellOf = [&](double rt) -> uint32_t {   // the first edge T with (T - rt) > cell_drt; edges ascend, so the test is monotone
+      if (!cells || cells->empty()) return 0;
+      return (uint32_t)(std::partition_point(cells->begin(), cells->end(), [&](double T) { return !(T - rt > cell_drt); }) - cells->begin());
+    };
     vector<K> ks; ks.reserve(v.size());
     for (size_t i = 0; i < v.size(); ++i)
     {
       const auto& p = v[i].getPrecursors();
-      if (!p.empty() && p[0].getCharge() > 0) ks.push_back({v[i].getRT(), p[0].getMZ(), p[0].getDriftTime(), p[0].getCharge(), (uint32_t)i});
+      if (!p.empty() && p[0].getCharge() > 0) ks.push_back({v[i].getRT(), p[0].getMZ(), p[0].getDriftTime(), p[0].getCharge(), (uint32_t)i, cellOf(v[i].getRT()),
+                                                               near_mode == 2 && v[i].metaValueExists("spx_mono_ext")});
     }
+    // one charge, then m/z: a pair is found from its lower-m/z member's 20-ppm window whatever its frames
     sort(ks.begin(), ks.end(), [](const K& a, const K& b) {
-      if (a.rt != b.rt) return a.rt < b.rt;
       if (a.z != b.z) return a.z < b.z;
       if (a.mz != b.mz) return a.mz < b.mz;
+      if (a.rt != b.rt) return a.rt < b.rt;
       return a.i < b.i;
     });
-    vector<uint32_t> up(v.size());
+    vector<uint32_t> up(v.size()), up1;   // up1: the same-frame relation alone, for the counter only
     for (size_t i = 0; i < up.size(); ++i) up[i] = (uint32_t)i;
-    auto root = [&up](uint32_t a) { while (up[a] != a) { up[a] = up[up[a]]; a = up[a]; } return a; };
+    if (st) up1 = up;
+    auto rootIn = [](vector<uint32_t>& u, uint32_t a) { while (u[a] != a) { u[a] = u[u[a]]; a = u[a]; } return a; };
+    auto root = [&](uint32_t a) { return rootIn(up, a); };
+    size_t n_same = 0, n_near = 0, n_edge = 0;
     for (size_t g0 = 0, g1; g0 < ks.size(); g0 = g1)
     {
-      for (g1 = g0 + 1; g1 < ks.size() && ks[g1].rt == ks[g0].rt && ks[g1].z == ks[g0].z; ++g1) {}   // one frame, one charge
+      for (g1 = g0 + 1; g1 < ks.size() && ks[g1].z == ks[g0].z; ++g1) {}   // one charge
       for (size_t a = g0; a < g1; ++a)
       {
         // the probe is the EARLIER member of a pair, with its own tolerance, as in bench/twin_merge.py
         const double tol = ks[a].mz * TWIN_PPM * 1e-6, lo = ks[a].mz - tol, hi = ks[a].mz + tol;
         auto link = [&](size_t b) {
-          if (ks[b].i > ks[a].i && fabs(ks[b].im - ks[a].im) <= im_tol) { const uint32_t ra = root(ks[a].i), rb = root(ks[b].i); if (ra != rb) up[ra] = rb; }
+          if (ks[b].i <= ks[a].i || !(fabs(ks[b].im - ks[a].im) <= im_tol) || !(fabs(ks[b].rt - ks[a].rt) <= rt_tol)) return;
+          const bool same = ks[b].rt == ks[a].rt;
+          if (!same && near_mode >= 1 && fabs(ks[b].mz - ks[a].mz) > ks[a].mz * BIN_PPM * 1e-6) return;
+          if (!same && near_mode == 2 && !ks[a].ext && !ks[b].ext) return;
+          if (ks[b].cell != ks[a].cell) { ++n_edge; return; }
+          ++(same ? n_same : n_near);
+          { const uint32_t ra = root(ks[a].i), rb = root(ks[b].i); if (ra != rb) up[ra] = rb; }
+          if (st && same) { const uint32_t ra = rootIn(up1, ks[a].i), rb = rootIn(up1, ks[b].i); if (ra != rb) up1[ra] = rb; }
         };
         for (size_t b = a + 1; b < g1 && ks[b].mz <= hi; ++b) link(b);
         for (size_t b = a; b-- > g0 && ks[b].mz >= lo; ) link(b);
       }
     }
+    if (st)
+    {
+      vector<uint8_t> seen(v.size(), 0);
+      size_t n_roots = 0;
+      for (uint32_t i = 0; i < (uint32_t)v.size(); ++i) { const uint32_t r = rootIn(up1, i); if (!seen[r]) { seen[r] = 1; ++n_roots; } }
+      (*st)[0] += n_same; (*st)[1] += n_near; (*st)[2] += n_edge; (*st)[3] += v.size() - n_roots;
+    }
     // survivor per cluster: (isotopes, peaks) strictly greater replaces, so a tie keeps the earliest
     const uint32_t NONE = UINT32_MAX;
     vector<uint32_t> n_in(v.size(), 0), best(v.size(), NONE);
@@ -2221,11 +2849,16 @@ namespace
     }
     vector<vector<uint32_t>> members(surv.size());
     for (uint32_t i = 0; i < (uint32_t)v.size(); ++i) { const uint32_t r = root(i); if (n_in[r] >= 2) members[(size_t)slot[best[r]]].push_back(i); }
+    if (st && rt_tol > 0.0)   // [twin-rt] clusters whose members span more than rt_tol: chained through intermediate frames
+      for (const auto& m : members)
+      {
+        double r0 = v[m[0]].getRT(), r1 = r0;
+        for (uint32_t i : m) { r0 = std::min(r0, v[i].getRT()); r1 = std::max(r1, v[i].getRT()); }
+        if (r1 - r0 > rt_tol) ++(*st)[4];
+      }
     // fuse: each thread reads and writes one cluster's spectra only
-    std::exception_ptr fold_err;   // [task-err] an exception escaping the region (bad_alloc) would abort without a message
-#pragma omp parallel for schedule(dynamic, 64)
-    for (long c = 0; c < (long)surv.size(); ++c)
-    { try {
+    auto fuse = [&](const long c)
+    {
       if (keyed)
       {
         // [recap] the same fusion over (m/z, intensity, key) triples. Peaks equal in m/z and intensity add equal terms
@@ -2254,7 +2887,7 @@ namespace
         for (const auto& f : fused) s.emplace_back(f.first, (float)f.second);
         s.getFloatDataArrays().clear();
         s.getFloatDataArrays().push_back(std::move(kk));   // moved, not copied (assign(1, x) copies)
-        continue;
+        return;
       }
       vector<pair<double, double>> ps;
       for (uint32_t i : members[(size_t)c]) for (const auto& pk : v[i]) ps.emplace_back(pk.getMZ(), (double)pk.getIntensity());
@@ -2271,8 +2904,15 @@ namespace
       s.clear(false);   // peaks only: RT, precursor and userParams are the survivor's
       s.reserve(fused.size());
       for (const auto& f : fused) s.emplace_back(f.first, (float)f.second);
-    } catch (...) { taskErr_(fold_err); } }
-    if (fold_err) std::rethrow_exception(fold_err);
+    };
+    if (!omp_in_parallel())
+    {
+      std::exception_ptr fold_err;   // [task-err] an exception escaping the region (bad_alloc) would abort without a message
+#pragma omp parallel for schedule(dynamic, 64)
+      for (long c = 0; c < (long)surv.size(); ++c) { try { fuse(c); } catch (...) { taskErr_(fold_err); } }
+      if (fold_err) std::rethrow_exception(fold_err);
+    }
+    else teamFor_((long)surv.size(), 64, [&](long c, int) { fuse(c); });   // [pipe] the pipelined tile writer; teamFor_ rethrows the first exception
     size_t w = 0;
     for (uint32_t i = 0; i < (uint32_t)v.size(); ++i)
     {
@@ -2283,6 +2923,7 @@ namespace
     }
     const size_t removed = v.size() - w;
     v.erase(v.begin() + (long)w, v.end());
+    if (near_mode == 2) for (auto& sp : v) if (sp.metaValueExists("spx_mono_ext")) sp.removeMetaValue("spx_mono_ext");   // [twin-rt] never written
     return removed;
   }
 
@@ -2293,10 +2934,9 @@ namespace
   static std::array<size_t, 3> capAfterFusion_(vector<MSSpectrum>& v, Size max_frags)
   {
     size_t n_sp = 0, n_pk = 0, n_max = 0;
-    std::exception_ptr cap_err;   // [task-err] an exception escaping the region (bad_alloc) would abort without a message
-#pragma omp parallel for schedule(dynamic, 256) reduction(+ : n_sp, n_pk) reduction(max : n_max)
-    for (long i = 0; i < (long)v.size(); ++i)
-    { try {
+    // the counters are parameters, not captures: inside the reduction loop they must be the thread's copies
+    auto capOne = [&v, max_frags](const long i, size_t& n_sp, size_t& n_pk, size_t& n_max)
+    {
       MSSpectrum& s = v[(size_t)i];
       n_max = std::max(n_max, (size_t)s.size());
       if (s.size() > max_frags && !s.getFloatDataArrays().empty())
@@ -2317,8 +2957,21 @@ namespace
         s.select(idx);
       }
       s.getFloatDataArrays().clear();
-    } catch (...) { taskErr_(cap_err); } }
-    if (cap_err) std::rethrow_exception(cap_err);
+    };
+    if (!omp_in_parallel())
+    {
+      std::exception_ptr cap_err;   // [task-err] an exception escaping the region (bad_alloc) would abort without a message
+#pragma omp parallel for schedule(dynamic, 256) reduction(+ : n_sp, n_pk) reduction(max : n_max)
+      for (long i = 0; i < (long)v.size(); ++i) { try { capOne(i, n_sp, n_pk, n_max); } catch (...) { taskErr_(cap_err); } }
+      if (cap_err) std::rethrow_exception(cap_err);
+    }
+    else
+    {
+      // [pipe] the pipelined tile writer: per-slot partial counters, summed here
+      vector<std::array<size_t, 3>> part((size_t)std::max(1, omp_get_num_threads()), std::array<size_t, 3>{0, 0, 0});
+      teamFor_((long)v.size(), 256, [&](long i, int slot) { auto& p = part[(size_t)slot]; capOne(i, p[0], p[1], p[2]); });
+      for (const auto& p : part) { n_sp += p[0]; n_pk += p[1]; n_max = std::max(n_max, p[2]); }
+    }
     return {n_sp, n_pk, n_max};
   }
 
@@ -2370,8 +3023,11 @@ namespace
       // A handler is not reentrant (writeSpectrum_ memoises CV-term validation in cached_terms_),
       // so each thread encodes with its own; dps_ is shared read-only -- every spectrum carries the
       // one data-processing entry the header registered, so writeSpectrum_ never appends to it.
+      // [pipe] On the pipelined tile writer (inside the window team) the encoders are per puller slot of
+      // teamFor_, at most the team size; the chunks and their order are the same either way.
+      const bool in_team = omp_in_parallel();
       const Size CHUNK = 256;
-      const Size n_thr = (Size)std::max(1, omp_get_max_threads());
+      const Size n_thr = (Size)std::max(1, in_team ? omp_get_num_threads() : omp_get_max_threads());
       while (enc_.size() < n_thr) { enc_.emplace_back(new TileWriter("/dev/null")); enc_.back()->options_ = options_; }
       const Size wave = CHUNK * n_thr;
       for (Size w0 = 0; w0 < block.size(); w0 += wave)
@@ -2381,12 +3037,10 @@ namespace
         vector<std::string> text(n_chunk);
         vector<vector<pair<std::string, Int64>>> offs(n_chunk);
         std::exception_ptr err;
-        #pragma omp parallel for schedule(dynamic, 1)
-        for (long c = 0; c < (long)n_chunk; ++c)
+        auto encode = [&](const long c, TileWriter& h)
         {
           try
           {
-            TileWriter& h = *enc_[(Size)omp_get_thread_num()];
             std::ostringstream buf; buf.copyfmt(ofs_);          // identical formatting state, or the numbers differ
             const Size lo = w0 + (Size)c * CHUNK, hi = std::min(lo + CHUNK, w1);
             const Size o0 = h.spectra_offsets_.size();
@@ -2400,7 +3054,13 @@ namespace
             #pragma omp critical(tile_writer_err)
             if (!err) err = std::current_exception();
           }
+        };
+        if (!in_team)
+        {
+          #pragma omp parallel for schedule(dynamic, 1)
+          for (long c = 0; c < (long)n_chunk; ++c) encode(c, *enc_[(Size)omp_get_thread_num()]);
         }
+        else teamFor_((long)n_chunk, 1, [&](long c, int slot) { encode(c, *enc_[(Size)slot]); });
         if (err) std::rethrow_exception(err);
         for (Size c = 0; c < n_chunk; ++c)
         {
@@ -2471,14 +3131,20 @@ protected:
     registerIntOption_("assembly:max_fragments", "<n>", 500, "Keep at most this many (top-ranked) fragments per pseudo-spectrum (applied before the twin fold, see assembly:twin_im_tolerance; assembly:post_fusion_cap re-applies it after the fold).", false);
     registerDoubleOption_("assembly:im_weight_sigma", "<1/K0>", 0.005, "Multiply each fragment's intensity by exp(-dIM^2 / 2 sigma^2), dIM its 1/K0 distance from the precursor; this also changes which fragments survive assembly:max_fragments. 0 = off, as in 1.5.0. Default 0.005 since 1.6.0: together with assembly:foreign_precursor_weight 0, +5.8 % Sage and +4.2 % MSFragger peptides over 1.5.0 on 43 public runs at unchanged entrapment (CHANGELOG, v1.6.0); earlier measurements in docs/BASELINE.md 'Confirmed WINS post-freeze'.", false);
     registerDoubleOption_("assembly:corr_power", "<k>", 2.0, "Multiply each emitted fragment's intensity by corr^k (k >= 0), corr its co-elution score with the precursor. It changes the emitted intensity, not the cap key; but assembly:fragment_fuse_ppm (on by default, mode anchored) groups the fragments strongest first by emitted intensity, so it can change which pieces fuse and with them which peaks survive assembly:max_fragments. 0 = off (the behaviour before 2026-07-28). Default 2: +8-10% Sage on three files (docs/BASELINE.md 'Confirmed WINS post-freeze') and +4% MSFragger on the one file measured with it ('CONTENT CANDIDATE 1 FALSIFIED').", false);
-    registerDoubleOption_("assembly:twin_im_tolerance", "<1/K0>", 0.005, "Fold spectra that claim one precursor twice into one: same MS1 frame, same charge, precursor m/z within 20 ppm, 1/K0 within this tolerance. The member with the most isotopes, then the most peaks, keeps its precursor and takes the union of the cluster's fragments (peaks within 10 ppm fused), so a folded spectrum can exceed assembly:max_fragments. Twins come from two seeds that resolve to one monoisotope, or from one precursor in the overlap of two isolation windows. -1 = off (the spectra before 1.4.0); 0 still folds twins of identical 1/K0. CHANGES OUTPUT. Default 0.005: -23.8% spectra for -0.21% Sage / -0.18% MSFragger peptides on PXD029836, entrapment FDR 0.98% with the fold against 0.98% without (docs/SAME-POSITION-DUPLICATION-2026-09-20.md).", false);
+    registerDoubleOption_("assembly:twin_im_tolerance", "<1/K0>", 0.005, "Fold spectra that claim one precursor twice into one: same MS1 frame (or nearby frames, see assembly:twin_rt_frames), same charge, precursor m/z within 20 ppm, 1/K0 within this tolerance. The member with the most isotopes, then the most peaks, keeps its precursor and takes the union of the cluster's fragments (peaks within 10 ppm fused), so a folded spectrum can exceed assembly:max_fragments. Twins come from two seeds that resolve to one monoisotope, or from one precursor in the overlap of two isolation windows. -1 = off (the spectra before 1.4.0); 0 still folds twins of identical 1/K0. CHANGES OUTPUT. Default 0.005: -23.8% spectra for -0.21% Sage / -0.18% MSFragger peptides on PXD029836, entrapment FDR 0.98% with the fold against 0.98% without (docs/SAME-POSITION-DUPLICATION-2026-09-20.md).", false);
+    registerIntOption_("assembly:twin_rt_frames", "<n>", 0, "Let the twin fold (assembly:twin_im_tolerance) also join two spectra of one monoisotope from nearby MS1 frames: charge:mono_profile_check v2's extension can move a monoisotope onto another precursor's monoisotope trace at another frame, which the same-frame fold cannot join. A pair folds across frames with the same charge, precursor m/z in one flight-time bin (within 0.05 ppm) and, by default, one of the two monoisotopes placed by the extension (assembly:twin_rt_match), 1/K0 within assembly:twin_im_tolerance, apexes at most n MS1 cycles apart (|dRT| <= (n + 0.5) x the cycle) and in one retention-time cell (tile:rt_sec; a pair across a cell edge stays two spectra). The survivor rule and the fusion are the fold's. 0 = auto: the run's median MS1 peak width (FWHM of the precursors' seed traces with at least 3 points) in MS1 cycles, rounded, at least 1. -1 = off: the same MS1 frame only (the fold before 1.6.0). Logged as [twins], stamped in spx:twin_merge. CHANGES OUTPUT.", false);
+    registerStringOption_("assembly:twin_rt_match", "<mode>", "ext", "assembly:twin_rt_frames: which pairs from two different MS1 frames fold. 'ext': precursor m/z in one flight-time bin (within 0.05 ppm) and the monoisotope of at least one of the two placed by charge:mono_profile_check v2's extension, i.e. the extension moved it onto another precursor's monoisotope (nothing folds across frames without v2). 'bin': any pair in one flight-time bin (one MS1 trace, or one bin at two frames, is the monoisotope of both; distinct monoisotope traces of one charge and 1/K0 at nearby frames lie 0.3 ppm or more apart). 'ppm': within 20 ppm, as at one frame; it also folds the spectra of one ion seeded from different flight-time bins. 'bin' and 'ppm' cost peptides in the screen.", false, true);
     registerIntOption_("assembly:default_charge", "<z>", 2, "Charge given to a precursor left without a charge call (no isotope partner, or a z=1 call on the 3+ mobility band): > 0 assigns that charge, 0 leaves it unset for the search engine. These are the guessed precursors, so it has no effect unless -assembly:require_isotope_support false keeps them.", false);
 
     registerTOPPSubsection_("trace", "Mass-trace detection (see MassTraceDetection)");
     registerDoubleOption_("trace:mass_error_ppm", "<ppm>", 15.0, "m/z tolerance for trace detection.", false);
     registerDoubleOption_("trace:noise_threshold_int", "<int>", 100.0, "MS1 (precursor) noise intensity threshold.", false);
     registerDoubleOption_("trace:ms2_noise_threshold_int", "<int>", 10.0, "MS2 (fragment) noise intensity threshold.", false);
-    registerDoubleOption_("trace:min_length_sec", "<sec>", 3.0, "Minimum MS1 mass-trace length (seconds).", false, true);
+    registerDoubleOption_("trace:min_length_sec", "<sec>", -1.0, "Minimum MS1 mass-trace length in seconds (last minus first point). "
+                          "Negative = auto (the default since 1.6.0): trace:min_length_fwhm x the run's median MS1 peak FWHM, at least half an MS1 cycle, so a trace needs 2 MS1 points. "
+                          "The FWHM is that of the brightest tenth of a fixed sample of MS1 traces (1-Th m/z slices every 25 Th, traced like the run but with no minimum length). "
+                          "Logged as [minlen], stamped spx:ms1_min_length. 0 = no length filter; 3 = the value before 1.6.0. CHANGES OUTPUT.", false);
+    registerDoubleOption_("trace:min_length_fwhm", "<x>", 0.4, "trace:min_length_sec auto: the minimum MS1 trace length as this fraction of the run's median MS1 peak FWHM.", false, true);
     registerDoubleOption_("trace:ms1_chrom_peak_snr", "<x>", 3.0, "Apex signal-to-noise multiplier for MS1 traces (effective apex threshold = this x noise_threshold_int). OpenMS default 3.0.", false, true);
     registerDoubleOption_("trace:ms2_chrom_peak_snr", "<x>", 1.0, "Apex signal-to-noise multiplier for MS2 (fragment) traces: the apex threshold is this x trace:ms2_noise_threshold_int (OpenMS default 3.0). Lower recovers weaker fragments.", false);
     registerDoubleOption_("trace:ms2_min_length_sec", "<sec>", 0.0, "Minimum MS2 (fragment) mass-trace length (seconds). 0 = no length filter (the reference implementation-style relaxed MS2); MS1 keeps trace:min_length_sec.", false);
@@ -2501,7 +3167,7 @@ protected:
     registerStringOption_("trace:mz_estimator", "<mode>", "apex", "Reported m/z of a mass trace: 'apex' the most intense peak's, 'mean' the intensity-weighted centroid (OpenMS), 'median' the median. CHANGES OUTPUT. Fragment traces of the integer detector always report the calibrated m/z of their apex bin, whatever this says; with trace:detector openms the estimator applies to them too. apex measured best on both engines: docs/BASELINE.md 'APEX estimator: 3-FILE RESULT'.", false);
     setValidStrings_("trace:mz_estimator", {"apex", "mean", "median"});
     registerDoubleOption_("trace:ms2_split_valleys", "<chrom_fwhm>", 7.0, "Split MS2 mass traces at chromatographic valleys (ElutionPeakDetection, width filtering off). Value = chrom_fwhm (seconds); 0 = off.", false);
-    registerFlag_("diag:selftest_twins", "Run assertions on the twin fold (mergeTwins_) and exit: the relation, the cluster closure, the survivor order, the 10-ppm fusion and the keyed fold with the post-fusion cap (assembly:post_fusion_cap)", true);
+    registerFlag_("diag:selftest_twins", "Run assertions on the twin fold (mergeTwins_) and exit: the relation (also across nearby frames), the cluster closure, the survivor order, the 10-ppm fusion and the keyed fold with the post-fusion cap (assembly:post_fusion_cap)", true);
     registerFlag_("diag:selftest_arena", "Run assertions on the MS1 arena compaction (compactUnreferenced) and exit: kept spans must survive a container order that differs from their offset order", true);
     registerDoubleOption_("trace:ms1_split_valleys", "<chrom_fwhm>", 7.0, "Split MS1 mass traces at chromatographic valleys (ElutionPeakDetection), so two peptides eluting apart within the m/z tolerance do not merge into one precursor with the wrong monoisotope and charge. Value = chrom_fwhm (seconds); 0 = off.", false);
     registerDoubleOption_("trace:max_span_sec", "<sec>", 120.0, "Trim each mass trace (precursor and fragment) to at most this many seconds "
@@ -2576,7 +3242,7 @@ protected:
     registerIntOption_("assembly:foreign_precursor_min_iso", "<n>", 2, "assembly:foreign_precursor_weight: how many of a foreign envelope's four positions (mono to M+3) must carry a fragment before its fragments are attenuated.", false, true);
     setMinInt_("assembly:foreign_precursor_min_iso", 1);
     setMaxInt_("assembly:foreign_precursor_min_iso", 4);
-    registerDoubleOption_("assembly:fragment_fuse_ppm", "<ppm>", 25.0, "Fuse a spectrum's fragments that lie within this many ppm into one peak, after the same-bin merge and before assembly:min_fragments and assembly:max_fragments (0 = off, as in 1.5.0; default 25 with assembly:fragment_fuse_mode anchored since 1.6.0): the IM picker keeps 1-2 flight-time bins of an ion that spans 4-7, so one fragment ion becomes several traces and several peaks a few ppm apart. A fused peak's intensity is the sum of its members' emitted intensities (whatever their retention-time overlap, unlike the same-bin merge), its m/z their intensity-weighted mean and its cap key (assembly:cap_rank) their best member's, not one recomputed from the sum; a fused ion takes one cap slot and the slots it frees refill. A spectrum that fuses below assembly:min_fragments is not written. Grouping by assembly:fragment_fuse_mode. Logged as [fuse], stamped spx:fragment_fuse. CHANGES OUTPUT.", false, false);
+    registerDoubleOption_("assembly:fragment_fuse_ppm", "<ppm>", 25.0, "Fuse a spectrum's fragments that lie within this many ppm into one peak, after the same-bin merge and before assembly:min_fragments and assembly:max_fragments (0 = off, as in 1.5.0; default 25 with assembly:fragment_fuse_mode anchored since 1.6.0): the IM picker keeps 1-2 flight-time bins of an ion that spans 4-7, so one fragment ion becomes several traces and several peaks a few ppm apart. A fused peak's intensity is the sum of its members' emitted intensities (whatever their retention-time overlap, unlike the same-bin merge), its m/z their intensity-weighted mean and its cap key (assembly:cap_rank) the key of one fragment applied to the whole ion: the best-keyed member's score (and, under evidence, its shared frames) with the sum of the members' IM-weighted apex intensities, never below that member's own key; a fused ion takes one cap slot and the slots it frees refill. A spectrum that fuses below assembly:min_fragments is not written. Grouping by assembly:fragment_fuse_mode. Logged as [fuse], stamped spx:fragment_fuse. CHANGES OUTPUT.", false, false);
     setMinFloat_("assembly:fragment_fuse_ppm", 0.0);
     setMaxFloat_("assembly:fragment_fuse_ppm", 50.0);
     registerStringOption_("assembly:fragment_fuse_mode", "<mode>", "anchored", "assembly:fragment_fuse_ppm: 'anchored' takes the fragments by emitted intensity, strongest first (ties: lower m/z); each one not yet fused becomes an anchor and takes every unfused fragment within the tolerance of its own m/z. 'linkage' walks the fragments in m/z order and joins a fragment to the group of the previous one when it lies within the tolerance of it and within twice the tolerance of the group's first member (single linkage, span capped).", false, true);
@@ -2649,11 +3315,18 @@ protected:
     registerDoubleOption_("charge:mono_profile_min_corr", "<r>", 0.6, "charge:mono_profile_check true: minimum Pearson correlation of a leftward partner's MS1 profile with the seed's.", false, true);
     registerDoubleOption_("charge:mono_profile_max_dim", "<1/K0>", 0.015, "charge:mono_profile_check true: maximum 1/K0 difference of a leftward partner from the seed.", false, true);
     registerDoubleOption_("charge:mono_position_min_ratio", "<q>", 0.2, "charge:mono_profile_check v2: the walk's leftmost step is rejected when its averagine-scaled position ratio PS(-j) / PS(-j+1) x lambda is below this.", false, true);
-    registerDoubleOption_("charge:mono_position_im_box", "<1/K0>", 0.0, "charge:mono_profile_check v2: 1/K0 half-width around the seed of the isotope-position intensity sums. 0 = auto: 3.5 x the 90th percentile of the 1/K0 gap between the brightest tenth of the count-walk seeds and their nearest MS1 trace one isotope heavier, clamped to [0.01, 0.03] (0.018 and 0.022 on the 2019 HeLa py3 10 and 100 ng runs of PXD017703, whose isotope traces scatter widely in 1/K0). A value > 0 fixes the box. The count walk accepts partners up to charge:iso_im_tolerance (0.05) away, so a walk's own partner can lie outside the box and then counts as an empty position.", false, true);
+    registerDoubleOption_("charge:mono_position_im_box", "<1/K0>", 0.0, "charge:mono_profile_check v2: 1/K0 half-width around the seed of the isotope-position intensity sums. 0 = auto: 3.5 x the 90th percentile of the 1/K0 gap between the brightest tenth of the count-walk seeds and their nearest MS1 trace one isotope heavier, clamped to [0.01, 0.03] (0.018 and 0.022 on the 2019 HeLa py3 10 and 100 ng runs of PXD017703, whose isotope traces scatter widely in 1/K0). A value > 0 fixes the box. The count walk accepts partners up to charge:iso_im_tolerance away (auto: 0.01-0.05 per run), so a walk's own partner can lie outside the box and then counts as an empty position.", false, true);
     registerDoubleOption_("charge:mono_position_extend", "<q>", 0.6, "charge:mono_profile_check v2: when no step was rejected and the walk ended on a miss, move the monoisotope one isotope lighter (the most intense trace there, not claimed) if that position's ratio is >= this. 0 = off.", false, true);
     registerStringOption_("charge:mono_position_iterate", "<true/false>", "true", "charge:mono_profile_check v2: after a rejected leftmost step, test the new leftmost step too, and repeat while steps fail. false tests the leftmost step only.", false, true);
     setValidStrings_("charge:mono_position_iterate", {"true", "false"});
-    registerDoubleOption_("charge:iso_im_tolerance", "<1/K0>", 0.05, "1/K0 tolerance for matching isotope partners. Only 0.05 has been measured; change it behind a peptide-set gate.", false);
+    registerDoubleOption_("charge:iso_im_tolerance", "<1/K0>", 0.0, "1/K0 tolerance for matching isotope partners (default 0 = auto since 1.6.0; 0.05 = the fixed value of 1.5.0). "
+                          "auto measures it per run before the isotope walk: a stride sample of the MS1 traces is probed at each charge's +1 isotope position (the partner m/z tolerance, gate:delta_rt) "
+                          "and at two control positions 50 ppm either side, where no isotope of the probe can sit; the nearest trace's 1/K0 gap is recorded at each. "
+                          "The tolerance is the one that admits the most isotope-position traces net of twice the control traces (true partners admitted minus chance partners admitted), "
+                          "on a 0.001 grid, clamped to [0.01, 0.05]: about 0.01 on dense short-gradient runs, up to 0.05 on sparse low-load runs. A value > 0 fixes it. Logged as [isotol], stamped spx:iso_im_tolerance. CHANGES OUTPUT.", false);
+    registerStringOption_("charge:iso_partner", "<first/closest>", "first", "Which candidate inside the isotope-partner box (m/z tolerance, gate:delta_rt, charge:iso_im_tolerance) the walk takes: "
+                          "'first' in m/z order (as in 1.5.0), or 'closest' to the seed in apex RT and 1/K0, each scaled by its tolerance (ties to the first in m/z). Screened 2026-10-01: closest lost 1.6-5.0% MSFragger peptides on two 10 ng HeLa runs and wrote 14-15% more spectra on Evosep for about the same peptides; not recommended. CHANGES OUTPUT.", false, true);
+    setValidStrings_("charge:iso_partner", {"first", "closest"});
 
     registerTOPPSubsection_("dnoise", "MS1 denoising of the raw frames before peak picking (dnoise v0.1.0's MS1 path; Bruker .d only)");
     registerStringOption_("dnoise:ms1", "<true/false>", "true",
@@ -2686,6 +3359,8 @@ protected:
     setMinInt_("assembly:max_fragments", 1);
     setMinInt_("assembly:default_charge", 0);
     setMinFloat_("assembly:twin_im_tolerance", -1.0);   // any negative value = off
+    setMinInt_("assembly:twin_rt_frames", -1);          // -1 = off (same frame), 0 = auto
+    setValidStrings_("assembly:twin_rt_match", {"ext", "bin", "ppm"});
     setMinInt_("max_charge", 1);
     setMinInt_("perf:trace_bands", 0);      // 0 = auto (documented)
     setMinFloat_("gate:delta_im", 0.0);
@@ -2698,6 +3373,7 @@ protected:
     setMinFloat_("charge:mono_profile_max_dim", 0.0);
     setMinFloat_("charge:mono_position_min_ratio", 0.0);
     setMinFloat_("charge:mono_position_im_box", 0.0);
+    setMinFloat_("trace:min_length_fwhm", 0.0);   // [minlen] 0 = the 2-point floor
     setMinFloat_("charge:mono_position_extend", 0.0);
     setMinFloat_("trace:ms1_chrom_peak_snr", 0.0);
     setMinFloat_("trace:ms2_chrom_peak_snr", 0.0);
@@ -2734,6 +3410,10 @@ protected:
     mtd.setParameters(p);
 
     vector<MassTrace> mts;
+    // [outer] The traces as consecutive segments (the bands, then the valley-split chunks): their concatenation is the
+    // sequence the serial gather and the serial re-concatenation used to build, and every later step walks it in that
+    // order, so neither copy is needed.
+    vector<vector<MassTrace>> seg;
     // [tstage] Sub-stage seconds of this phase, logged as one line.
     double tt_edge = 0, tt_dist = 0, tt_mtd = 0, tt_gather = 0, tt_split = 0;
     auto tt_now = []() { return std::chrono::steady_clock::now(); };
@@ -2873,9 +3553,7 @@ protected:
       if (band_err) std::rethrow_exception(band_err);
       tt_mtd = tt_s(_tm0, tt_now());
       auto _tg0 = tt_now();
-      size_t tot = 0; for (const auto& v : per) tot += v.size();
-      mts.reserve(tot);
-      for (auto& v : per) { for (auto& t : v) mts.push_back(std::move(t)); vector<MassTrace>().swap(v); }
+      seg = std::move(per);   // [outer] the bands, in band order, are the segments: no serial gather
       tt_gather = tt_s(_tg0, tt_now());
     }
     else
@@ -2883,17 +3561,21 @@ protected:
       if (map.size() >= 3) mtd.run(map, mts);   // MTD aborts below 3 spectra; a tiny input is not an error
       map.clear(true); // [compact] dead from here; ~1.1 GB/window freed before the EPD peak
       if (in_cat >= 0) ledSet_(in_cat, 0);
+      seg.resize(1); seg[0].swap(mts);
     }
+    size_t n_tr = 0; for (const auto& s : seg) n_tr += s.size();
 
     // [way-2] Split mass traces at chromatographic valleys: MassTraceDetection never splits at a local
     // minimum, so co-eluting neighbours within the m/z tolerance merge. width_filtering is forced off
     // (a deletion filter). Per-trace and deterministic, so it runs as a balanced parallel loop (4 chunks
     // per band); both consumers re-sort (MS2 after detectTraces_, MS1 before inferPrecursors_).
     auto _ts0 = tt_now();
-    if (split_valleys > 0.0 && mts.size() > 1)
+    if (split_valleys > 0.0 && n_tr > 1)
     {
       const int nchunk = std::max(1, bands * 4);      // 4 chunks per band -> dynamic load balance
-      const size_t n_in = mts.size();
+      const size_t n_in = n_tr;
+      vector<size_t> at(seg.size() + 1, 0);           // [outer] segment s holds positions [at[s], at[s+1]) of the sequence
+      for (size_t s = 0; s < seg.size(); ++s) at[s + 1] = at[s] + seg[s].size();
       vector<vector<MassTrace>> parts(nchunk);
       std::exception_ptr split_err;   // [task-err]
       #pragma omp taskloop grainsize(1) default(shared)
@@ -2901,28 +3583,93 @@ protected:
       { try {
         const size_t lo = (size_t)ci * n_in / nchunk, hi = (size_t)(ci + 1) * n_in / nchunk;
         if (lo >= hi) continue;
-        vector<MassTrace> chunk(std::make_move_iterator(mts.begin() + lo),
-                                std::make_move_iterator(mts.begin() + hi));
+        // [outer] positions [lo, hi) of the segment sequence, moved out segment by segment: the chunk the gathered
+        // vector gave (distinct chunks move distinct elements)
+        vector<MassTrace> chunk; chunk.reserve(hi - lo);
+        size_t s = (size_t)(std::upper_bound(at.begin(), at.end(), lo) - at.begin()) - 1;
+        for (size_t g = lo; g < hi; ++g) { while (g >= at[s + 1]) ++s; chunk.push_back(std::move(seg[s][g - at[s]])); }
         ElutionPeakDetection epd; setSplitter(epd, split_valleys, split_scan_time);
         parts[ci].reserve(chunk.size());
         epd.detectPeaks(chunk, parts[ci]);
       } catch (...) { taskErr_(split_err); } }
       if (split_err) std::rethrow_exception(split_err);
-      size_t tot = 0; for (auto& pth : parts) tot += pth.size();
-      vector<MassTrace> out; out.reserve(tot);
-      for (auto& pth : parts) { for (auto& t : pth) out.push_back(std::move(t)); vector<MassTrace>().swap(pth); }
-      mts.swap(out);
+      seg.swap(parts);   // [outer] the chunks' outputs, in chunk order, are the segments now: no serial re-concatenation
+      n_tr = 0; for (const auto& s : seg) n_tr += s.size();
     }
     tt_split = tt_s(_ts0, tt_now());
-    writeLogInfo_("[tstage] " + String(bands) + " bands -> " + String(mts.size()) + " traces: edges "
+    writeLogInfo_("[tstage] " + String(bands) + " bands -> " + String(n_tr) + " traces: edges "
                   + String(tt_edge) + " s | distribute " + String(tt_dist) + " s | detect "
                   + String(tt_mtd) + " s | gather " + String(tt_gather) + " s (serial) | valley-split "
                   + String(tt_split) + " s");
+    auto _tc0 = tt_now();
     vector<Trace> out;
-    out.reserve(mts.size());
-    // Each MassTrace is released as soon as it is converted. Serial on purpose: a parallel split was
-    // output-identical but 17% slower (docs/BASELINE.md, "Parallelising the MS1 trace conversion").
-    for (size_t i = 0; i < mts.size(); ++i) { out.push_back(toTrace(mts[i], store)); mts[i] = MassTrace(); }   // move-assign an empty one: the payload goes now, not at return
+    // [outer] The MS1 call converts in parallel: pass 1 sizes every span (makeSpan's frame range), the offsets are the
+    // running sum from the arena's end -- exactly where the serial appends put them -- and pass 2 fills each span at
+    // its offset with toTrace's own statements. Every trace writes only its own span and its own slot, so the arena and
+    // the trace list are byte-identical to the serial loop's. Contiguous ranges per task keep the walk sequential. The
+    // two earlier parallel versions kept the arena append serial (docs/BASELINE.md, "Parallelising the MS1 trace
+    // conversion"); DIASPEXTRACT_MS1_CONVERT_SERIAL=1 runs the serial loop below.
+    static const bool conv_serial = []{ const char* e = std::getenv("DIASPEXTRACT_MS1_CONVERT_SERIAL"); return e && *e && *e != '0'; }();
+    bool conv_par = ms1_prune && !conv_serial && n_tr >= 4096 && omp_in_parallel() && omp_get_num_threads() > 1;
+    const char* conv_why = "";
+    vector<size_t> at, off;   // segment s holds positions [at[s], at[s+1]) of the sequence; off: span length, then offset
+    auto segOf = [&at](size_t g) { return (size_t)(std::upper_bound(at.begin(), at.end(), g) - at.begin()) - 1; };
+    const int ntask = conv_par ? std::max(1, std::min(4 * omp_get_num_threads(), (int)(n_tr / 1024))) : 1;   // bounded: no task-count cliff
+    std::exception_ptr conv_err;   // [task-err]
+    if (conv_par)
+    {
+      at.assign(seg.size() + 1, 0);
+      for (size_t s = 0; s < seg.size(); ++s) at[s + 1] = at[s] + seg[s].size();
+      off.assign(n_tr + 1, 0);
+      #pragma omp taskloop num_tasks(ntask) default(shared)
+      for (int c = 0; c < ntask; ++c)
+      { try {
+        const size_t lo = (size_t)c * n_tr / ntask, hi = (size_t)(c + 1) * n_tr / ntask;
+        if (lo >= hi) continue;
+        size_t s = segOf(lo);
+        for (size_t g = lo; g < hi; ++g) { while (g >= at[s + 1]) ++s; off[g + 1] = spanLength(seg[s][g - at[s]], store); }
+      } catch (...) { taskErr_(conv_err); } }
+      if (conv_err) std::rethrow_exception(conv_err);
+      off[0] = store.inten.size();
+      for (size_t g = 0; g < n_tr; ++g) off[g + 1] += off[g];   // off[g] = the arena size before trace g's append
+      // [review] Trace::off is 32-bit and makeSpan narrows the arena size without a check. Past 2^32 - 1 floats two
+      // traces' narrowed offsets would alias and their tasks would race on the same span; the serial loop below keeps
+      // the old (deterministic) result there instead.
+      if (off[n_tr] > (size_t)std::numeric_limits<uint32_t>::max()) { conv_par = false; conv_why = ", the arena passes 2^32 floats"; }
+    }
+    if (conv_par)
+    {
+      store.inten.resize(off[n_tr], 0.0f);
+      out.resize(n_tr);
+      #pragma omp taskloop num_tasks(ntask) default(shared)
+      for (int c = 0; c < ntask; ++c)
+      { try {
+        const size_t lo = (size_t)c * n_tr / ntask, hi = (size_t)(c + 1) * n_tr / ntask;
+        if (lo >= hi) continue;
+        vector<pair<uint32_t, float>> pts;
+        size_t s = segOf(lo);
+        for (size_t g = lo; g < hi; ++g)
+        {
+          while (g >= at[s + 1]) ++s;
+          MassTrace& mt = seg[s][g - at[s]];
+          out[g] = toTraceAt(mt, store, off[g], pts);
+          mt = MassTrace();   // the payload goes now, as in the serial loop
+        }
+      } catch (...) { taskErr_(conv_err); } }
+      if (conv_err) std::rethrow_exception(conv_err);
+      vector<vector<MassTrace>>().swap(seg);
+    }
+    else
+    {
+      out.reserve(n_tr);
+      // Each MassTrace is released as soon as it is converted.
+      for (auto& sv : seg)   // [outer] the segments in order: the sequence the gathered vector held
+      {
+        for (size_t i = 0; i < sv.size(); ++i) { out.push_back(toTrace(sv[i], store)); sv[i] = MassTrace(); }   // move-assign an empty one: the payload goes now, not at return
+        vector<MassTrace>().swap(sv);
+      }
+    }
+    if (ms1_prune) writeLogInfo_("[outer] MS1 trace conversion " + String(tt_s(_tc0, tt_now())) + " s (" + (conv_par ? "parallel" : "serial") + conv_why + ")");
     return out;
   }
 
@@ -2964,6 +3711,101 @@ protected:
     return (vx > 0 && vy > 0) ? cov / std::sqrt(vx * vy) : -2.0;
   }
 
+  /// [isotol] charge:iso_im_tolerance 0 (auto): the run's isotope-partner 1/K0 tolerance, measured on its own MS1 traces
+  /// before the greedy walk. `ms1` is the content-sorted list (m/z ascending), so the sample and every search are the same
+  /// at any thread count and tiling. Every ceil(N / 200000)-th trace is a probe. At each charge z <= max_charge it is
+  /// probed at its +1 isotope position (m/z + 1.0033548 / z) and at two controls 50 ppm either side, where no isotope of the
+  /// probe can sit, in the walk's partner window (probe m/z x mass_ppm, gate:delta_rt), and the nearest other trace's
+  /// |d 1/K0| is kept. A tolerance t then admits P_iso(t) traces per isotope probe, of which about P_ctl(t) (the mean of
+  /// the two controls) are chance traces: t* maximises P_iso(t) - 2 P_ctl(t), the true partners admitted minus the chance
+  /// partners admitted, on a 0.001 grid over [0.002, 0.050] (ties to the wider), then clamped to [0.01, 0.05] (0.01: the
+  /// tightest value screened without loss on dense runs; 0.05: the fixed value of 1.5.0). `info` gets the stamp text.
+  double autoIsoImTol_(const vector<Trace>& ms1, const TraceStore& ms1st, int max_charge, double delta_rt, double mass_ppm, String& info)
+  {
+    const double ISO = 1.0033548, CTL = 50e-6, LO = 0.01, HI = 0.05;
+    const int NG = 49;                                    // grid t_x = 0.002 + 0.001 x, x = 0..48
+    auto tg = [](int x) { return 0.002 + 0.001 * x; };
+    const size_t N = ms1.size();
+    if (N < 2 || max_charge < 1)
+    {
+      info = "auto 0.05 (too few MS1 traces to measure)";
+      writeLogInfo_("[isotol] auto: " + String(N) + " MS1 traces, too few to measure; 1/K0 tolerance 0.05");
+      return HI;
+    }
+    vector<double> mz(N), rt(N), im(N);
+    for (size_t i = 0; i < N; ++i) { mz[i] = ms1[i].mz; rt[i] = rtOf(ms1st, ms1[i]); im[i] = ms1[i].im; }
+    if (!std::is_sorted(mz.begin(), mz.end()))
+      throw Exception::Precondition(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[isotol] the MS1 traces are not sorted by m/z");
+    const size_t stride = std::max<size_t>(1, (N + 199999) / 200000), ns = (N + stride - 1) / stride;
+    const int Z = max_charge;
+    vector<int8_t> gx(ns * (size_t)Z * 3, -1);            // per (probe, z, kind): first grid index x with gap <= t_x, -1 none
+    #pragma omp parallel for schedule(dynamic, 256)
+    for (long q = 0; q < (long)ns; ++q)
+    {
+      const size_t s = (size_t)q * stride;
+      const double tol = mz[s] * mass_ppm * 1e-6;
+      for (int z = 1; z <= Z; ++z)
+        for (int c = 0; c < 3; ++c)
+        {
+          const double base = mz[s] + ISO / z;
+          const double target = c == 0 ? base : c == 1 ? base * (1.0 + CTL) : base * (1.0 - CTL);
+          const size_t klo = (size_t)(std::lower_bound(mz.begin(), mz.end(), target - tol) - mz.begin());
+          const size_t khi = (size_t)(std::upper_bound(mz.begin(), mz.end(), target + tol) - mz.begin());
+          double g = 1.0;
+          for (size_t k = klo; k < khi; ++k)
+          {
+            if (k == s || fabs(rt[k] - rt[s]) > delta_rt) continue;
+            const double d = fabs(im[k] - im[s]);
+            if (d < g) g = d;
+          }
+          int8_t b = -1;
+          for (int x = 0; x < NG; ++x) if (g <= tg(x)) { b = (int8_t)x; break; }
+          gx[((size_t)q * (size_t)Z + (size_t)(z - 1)) * 3 + (size_t)c] = b;
+        }
+    }
+    vector<long long> cum(3 * NG, 0);                     // kind c, grid x: probes whose nearest gap is <= t_x
+    for (size_t i = 0; i < gx.size(); ++i) if (gx[i] >= 0) ++cum[(i % 3) * NG + (size_t)gx[i]];
+    for (int c = 0; c < 3; ++c) for (int x = 1; x < NG; ++x) cum[c * NG + x] += cum[c * NG + x - 1];
+    int best = 0; long long bj = 0;
+    for (int x = 0; x < NG; ++x)
+    {
+      const long long J = cum[x] - cum[NG + x] - cum[2 * NG + x];
+      if (x == 0 || J >= bj) { best = x; bj = J; }
+    }
+    const double tstar = tg(best), tol = std::min(HI, std::max(LO, tstar));
+    const int xc = (int)std::lround((tol - 0.002) / 0.001);
+    const double np = (double)ns * Z;
+    auto rate = [&](int c, int x) { return (double)cum[c * NG + x] / np; };
+    char b[400];
+    std::snprintf(b, sizeof b, "auto %.3f (t* %.3f of isotope minus 2 x control traces, clamped to [0.01, 0.05]; per probe within %.3f: isotope %.3f, control %.3f; %zu probes x %d charges)",
+                  tol, tstar, tol, rate(0, xc), 0.5 * (rate(1, xc) + rate(2, xc)), ns, Z);
+    info = String(b);
+    std::snprintf(b, sizeof b, "[isotol] auto: 1/K0 tolerance %.3f for isotope partners (t* %.3f, clamped to [0.01, 0.05]). %zu probes (stride %zu over %zu MS1 traces) x %d charges: "
+                  "the nearest trace lies within the tolerance at the +1 isotope position for %.3f of the probes, at the +-50 ppm controls for %.3f (within 0.05: %.3f, %.3f)",
+                  tol, tstar, ns, stride, N, Z, rate(0, xc), 0.5 * (rate(1, xc) + rate(2, xc)), rate(0, NG - 1), 0.5 * (rate(1, NG - 1) + rate(2, NG - 1)));
+    writeLogInfo_(String(b));
+    return tol;
+  }
+
+  /// [outer] The m/z order inferPrecursors_ and monoPositionPass_ share: the indices of @p ms1 by std::sort on m/z alone.
+  /// The MS1 traces arrive content-sorted (m/z is the first key), so unless two of them share an m/z the m/z values
+  /// strictly increase in container order, the identity is then the only sorted order, and it is taken without sorting.
+  /// With any equal (or unordered) neighbour -- a 60-min run has 677,976, a 2-h HeLa run 19,200: quantised m/z -- the order of equal
+  /// m/z is std::sort's own, so it is std::sort's sequence, computed by stdSortPar_. Returns the neighbours that are not
+  /// strictly increasing (0 = the identity was taken).
+  static size_t mzOrder_(const vector<Trace>& ms1, vector<size_t>& by_mz)
+  {
+    const size_t N = ms1.size();
+    by_mz.resize(N);
+    #pragma omp parallel for schedule(static)
+    for (long i = 0; i < (long)N; ++i) by_mz[(size_t)i] = (size_t)i;
+    size_t nonincr = 0;
+    #pragma omp parallel for schedule(static) reduction(+ : nonincr)
+    for (long i = 1; i < (long)N; ++i) if (!(ms1[(size_t)i - 1].mz < ms1[(size_t)i].mz)) ++nonincr;
+    if (nonincr) stdSortPar_(by_mz, [&ms1](size_t a, size_t b) { return ms1[a].mz < ms1[b].mz; });
+    return nonincr;
+  }
+
   /// [route-1] Isotope/charge inference on MS1 traces. Scores each (charge, monoisotope) hypothesis
   /// by averagine-shape agreement x isotope-XIC co-elution, instead of counting partners.
   vector<Precursor_> inferPrecursors_(const vector<Trace>& ms1, const TraceStore& ms1st, int max_charge,
@@ -2976,14 +3818,14 @@ protected:
 
     // m/z-sorted index for O(log N) isotope-partner lookup (avoids O(N^2) over all MS1 traces).
     auto _pi_t0 = std::chrono::steady_clock::now();
-    vector<size_t> by_mz(N);
-    for (size_t i = 0; i < N; ++i) by_mz[i] = i;
-    sort(by_mz.begin(), by_mz.end(), [&](size_t a, size_t b) { return ms1[a].mz < ms1[b].mz; });
+    vector<size_t> by_mz;
+    const size_t mz_nonincr = mzOrder_(ms1, by_mz);   // [outer]
     vector<double> sorted_mz(N);
-    for (size_t i = 0; i < N; ++i) sorted_mz[i] = ms1[by_mz[i]].mz;
     // [soa] The candidate scan's RT and IM, laid out in m/z order beside sorted_mz (sequential reads).
     vector<double> sorted_rt(N), sorted_im(N);
-    for (size_t i = 0; i < N; ++i) { const Trace& t = ms1[by_mz[i]]; sorted_rt[i] = rtOf(ms1st, t); sorted_im[i] = t.im; }
+    #pragma omp parallel for schedule(static)
+    for (long ii = 0; ii < (long)N; ++ii)
+    { const size_t i = (size_t)ii; const Trace& t = ms1[by_mz[i]]; sorted_mz[i] = t.mz; sorted_rt[i] = rtOf(ms1st, t); sorted_im[i] = t.im; }
     // [mzidx] Bucket index over sorted_mz keyed on the top bits of the IEEE-754 pattern: monotone for
     // positive doubles, so the bucket width is relative (ppm-shaped) and the std search on the bucket's
     // sub-range returns the same position as on the whole array. docs/BASELINE.md, "Computed indices
@@ -3001,8 +3843,15 @@ protected:
     };
     vector<uint32_t> bstart(kspan + 2, 0);
     {
-      size_t i = 0;
-      for (size_t b = 0; b <= kspan; ++b) { while (i < N && bucketOf(sorted_mz[i]) < b) ++i; bstart[b] = (uint32_t)i; }
+      // bstart[b] = the first i with bucketOf(sorted_mz[i]) >= b, else N. [outer] bucketOf is monotone over sorted_mz, so
+      // the buckets (bucketOf(sorted_mz[i-1]), bucketOf(sorted_mz[i])] start at i: every b is written by exactly one i.
+      #pragma omp parallel for schedule(static)
+      for (long ii = 0; ii < (long)N; ++ii)
+      {
+        const size_t i = (size_t)ii, b_hi = std::min(bucketOf(sorted_mz[i]), kspan);
+        for (size_t b = (i == 0 ? 0 : bucketOf(sorted_mz[i - 1]) + 1); b <= b_hi; ++b) bstart[b] = (uint32_t)i;
+      }
+      for (size_t b = (N ? std::min(bucketOf(sorted_mz[N - 1]), kspan) + 1 : 0); b <= kspan; ++b) bstart[b] = (uint32_t)N;
       bstart[kspan + 1] = (uint32_t)N;
     }
     auto lbmz = [&](double x) -> size_t {
@@ -3021,10 +3870,12 @@ protected:
 
     // Apex intensities in one contiguous array: the sort and every isotope walk read them.
     vector<float> inten(N);
-    for (size_t i = 0; i < N; ++i) inten[i] = (float)intensityOf(ms1st, ms1[i]);
     vector<size_t> order(N);
-    for (size_t i = 0; i < N; ++i) order[i] = i;
-    sort(order.begin(), order.end(), [&](size_t a, size_t b) {
+    #pragma omp parallel for schedule(static)
+    for (long ii = 0; ii < (long)N; ++ii) { const size_t i = (size_t)ii; inten[i] = (float)intensityOf(ms1st, ms1[i]); order[i] = i; }
+    // [outer] a total order (the index breaks every tie; the coordinates are finite, non-finite traces were dropped before
+    // the content sort), so the sorted sequence is unique and the parallel sort returns std::sort's
+    parallelSortTotal_(order, [&](size_t a, size_t b) {
       if (inten[a] != inten[b]) return inten[a] > inten[b];
       if (ms1[a].mz != ms1[b].mz) return ms1[a].mz < ms1[b].mz;
       return a < b; // total order so greedy isotope assignment is deterministic
@@ -3060,16 +3911,25 @@ protected:
 
       // Find an unused isotope partner near `target` m/z, co-localized in RT and IM (binary-search
       // the m/z index, scan only the ppm-window candidates); -1 if none.
+      // [isotol] charge:iso_partner closest: the unused candidate nearest the seed in (dRT / delta_rt)^2 + (d1/K0 / iso_im_tol)^2,
+      // ties to the first in m/z. Recording only the chosen partner as the dependency stays exact: `used` is monotone, so a
+      // candidate claimed later that was not chosen cannot change the minimum while the chosen one stays unused.
       auto findPartner = [&](double target) -> long {
         size_t klo = lbmz(target - tol), khi = ubmz(target + tol);   // [mzidx] same positions, local search
+        long best = -1; double bd = 0.0;
         for (size_t k = klo; k < khi; ++k)
         {
           if (fabs(sorted_rt[k] - s_rt) > delta_rt || fabs(sorted_im[k] - s.im) > iso_im_tol) continue;   // [soa]
           size_t j = by_mz[k];
           if (used[j] || j == seed) continue;
-          { R.deps.push_back((size_t)j); return (long)j; }
+          if (!iso_closest_) { R.deps.push_back((size_t)j); return (long)j; }
+          const double dr = delta_rt > 0.0 ? (sorted_rt[k] - s_rt) / delta_rt : 0.0;
+          const double di = iso_im_tol > 0.0 ? (sorted_im[k] - s.im) / iso_im_tol : 0.0;
+          const double d = dr * dr + di * di;
+          if (best < 0 || d < bd) { best = (long)j; bd = d; }
         }
-        return -1;
+        if (best >= 0) R.deps.push_back((size_t)best);
+        return best;
       };
 
       // charge:scoring=count end to end, sharing nothing with the envelope path below (no gapped walk, no
@@ -3263,17 +4123,26 @@ protected:
       } while (0);
     };
 
-    size_t spec_batch = 8192;
+    // [outer] 2048 (was 8192): the commit is serial and mostly fixed cost per seed, but each re-evaluation in it costs a
+    // whole seed (~10 us); a quarter of the batch re-evaluates a third of the seeds (a 60-min run: 17,853 vs 51,891) for 4x the
+    // fork/joins. Its greedy walk 1.45 -> 1.19 s at 64 threads, 1.55 -> 1.48 s at 192 (kim/dax, 2026-10-01). Committing
+    // beside the next batch's speculation was exact but slower (more re-evaluations, a contended commit): not kept.
+    size_t spec_batch = 2048;
     if (const char* e = std::getenv("DIASPEXTRACT_SPEC_BATCH")) { long v = atol(e); if (v >= 1) spec_batch = (size_t)v; }
+    // [outer] about four speculation chunks per thread (at most 16 seeds, as before), so a small batch feeds every thread
+    const int spec_chunk = (int)std::max<size_t>(1, std::min<size_t>(16, spec_batch / (4 * (size_t)std::max(1, omp_get_max_threads()))));
     vector<SeedRes> res(spec_batch);
     size_t n_committed = 0, n_conflict = 0, n_skipped = 0;
     std::array<size_t, 8> mc_tot{};   // [monocheck] SeedRes::mc over the committed seeds
     vector<MonoV2In_> v2in;           // [monocheck-v2] parallel to `out` when mono_check_ == 2
+    double t_spec = 0.0, t_commit = 0.0, t_reeval = 0.0;   // [outer] the walk's sub-steps, log only
+    auto now_s = []() { return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count(); };
     for (size_t b0 = 0; b0 < order.size(); b0 += spec_batch)
     {
       const size_t b1 = std::min(b0 + spec_batch, order.size());
+      const double ts0 = now_s();
       // Phase 1: speculate. Nothing here writes `used`, so the concurrent reads are safe.
-      #pragma omp parallel for schedule(dynamic, 16)
+      #pragma omp parallel for schedule(dynamic, spec_chunk)
       for (long ii = (long)b0; ii < (long)b1; ++ii)
       {
         SeedRes& R = res[(size_t)ii - b0];
@@ -3281,6 +4150,8 @@ protected:
         if (used[seed]) { R.emit.clear(); R.claims.clear(); R.deps.clear(); R.mc.fill(0); R.v2 = MonoV2In_(); continue; }
         evalSeed(seed, R);
       }
+      const double tc0 = now_s();
+      t_spec += tc0 - ts0;
       // Phase 2: commit in the original seed order.
       for (size_t ii = b0; ii < b1; ++ii)
       {
@@ -3289,13 +4160,14 @@ protected:
         SeedRes& R = res[ii - b0];
         bool stale = false;
         for (size_t d : R.deps) if (used[d]) { stale = true; break; }
-        if (stale) { evalSeed(seed, R); ++n_conflict; }
+        if (stale) { const double tr0 = now_s(); evalSeed(seed, R); ++n_conflict; t_reeval += now_s() - tr0; }
         for (const auto& pc : R.emit) { out.push_back(pc); if (mono_check_ == 2) v2in.push_back(R.v2); }
         if (mono_check_) for (size_t q = 0; q < mc_tot.size(); ++q) mc_tot[q] += R.mc[q];
         used[seed] = true;
         for (size_t j : R.claims) used[j] = true;
         ++n_committed;
       }
+      t_commit += now_s() - tc0;
     }
     // [z1-diag] DIASPEXTRACT_Z1_DIAG[=file]: for every z=1 call, is there a co-eluting MS1 trace at +ISO/2
     // (a halved 2+ ion's M+1) or +ISO/3, and was it already claimed.
@@ -3340,6 +4212,10 @@ protected:
                     + String(spec_batch) + ": " + String(n_committed) + " committed, " + String(n_conflict)
                     + " re-evaluated (" + String((int)(1000.0 * n_conflict / std::max<size_t>(n_committed, 1)) / 10.0)
                     + "%), " + String(n_skipped) + " already claimed)");
+      writeLogInfo_("[outer] infer m/z order: " + (mz_nonincr ? String(mz_nonincr) + " neighbours not strictly increasing, std::sort's order (stdSortPar_)"
+                                                              : String("strictly increasing, identity"))
+                    + "; greedy walk: " + String((order.size() + spec_batch - 1) / spec_batch) + " batches, chunk " + String(spec_chunk)
+                    + " | speculate " + String(t_spec) + " s | commit " + String(t_commit) + " s (re-evaluation " + String(t_reeval) + " s)");
     }
     if (mono_check_ == 1)
     {
@@ -3391,13 +4267,14 @@ protected:
       // The m/z-sorted index of inferPrecursors_ (same comparator on the same container, so the same order; the plain
       // std searches return the positions its bucket index returns).
       const size_t N = ms1.size();
-      vector<size_t> by_mz(N);
-      for (size_t i = 0; i < N; ++i) by_mz[i] = i;
-      sort(by_mz.begin(), by_mz.end(), [&](size_t a, size_t b) { return ms1[a].mz < ms1[b].mz; });
+      vector<size_t> by_mz;
+      mzOrder_(ms1, by_mz);   // [outer] the same helper, so the same order
       vector<double> sorted_mz(N), sorted_rt(N), sorted_im(N);
-      for (size_t i = 0; i < N; ++i) { const Trace& t = ms1[by_mz[i]]; sorted_mz[i] = t.mz; sorted_rt[i] = rtOf(ms1st, t); sorted_im[i] = t.im; }
       vector<float> inten(N);
-      for (size_t i = 0; i < N; ++i) inten[i] = (float)intensityOf(ms1st, ms1[i]);
+      #pragma omp parallel for schedule(static)
+      for (long ii = 0; ii < (long)N; ++ii)
+      { const size_t i = (size_t)ii; const Trace& t = ms1[by_mz[i]]; sorted_mz[i] = t.mz; sorted_rt[i] = rtOf(ms1st, t); sorted_im[i] = t.im;
+        inten[i] = (float)intensityOf(ms1st, ms1[i]); }
       auto lbmz = [&](double x) -> size_t { return (size_t)(std::lower_bound(sorted_mz.begin(), sorted_mz.end(), x) - sorted_mz.begin()); };
       auto ubmz = [&](double x) -> size_t { return (size_t)(std::upper_bound(sorted_mz.begin(), sorted_mz.end(), x) - sorted_mz.begin()); };
       if (v2_box <= 0.0)
@@ -3518,7 +4395,7 @@ protected:
           f |= 8;
           long bt = -1;
           const double q = ratio(nl + 1, &bt);
-          if (q >= mono_pos_extend_ && q > 0.0 && bt >= 0) { mono = ms1[(size_t)bt].mz; f |= 16; }
+          if (q >= mono_pos_extend_ && q > 0.0 && bt >= 0) { mono = ms1[(size_t)bt].mz; f |= 16; pc.mono_ext = true; }
         }
         pc.mono_mz = mono;
         flag[(size_t)ii] = f; rej[(size_t)ii] = r;
@@ -3568,13 +4445,29 @@ protected:
     /// inv == 0 is the DISABLED state, not an error: every bucket is then 0, every dq is 0, and
     /// the exact test alone decides. That is the fallback for every degenerate parameter below,
     /// and it costs no branch in the scan.
-    void build(const vector<Trace>& fr, const TraceStore& st, double delta_rt)
+    void build(const vector<Trace>& fr, const TraceStore& st, double delta_rt, long nt = 1)
     {
       const size_t n = fr.size();
       rt.resize(n); q.assign(n, 0);
       rt0 = 0.0; inv = 0.0;
-      double lo = 0.0, hi = 0.0;
-      for (size_t i = 0; i < n; ++i) { rt[i] = rtOf(st, fr[i]); if (!i || rt[i] < lo) lo = rt[i]; if (!i || rt[i] > hi) hi = rt[i]; }
+      // [serial] As nt tasks. The serial fold takes the first value, then any value strictly below (above) it, so
+      // chunk 0 folds serially and every later chunk contributes its smallest (largest) non-NaN value, earliest on
+      // ties, folded in chunk order: the same lo and hi for any values (a NaN first value sticks, a later NaN never
+      // replaces).
+      vector<double> clo(nt, 0.0), chi(nt, 0.0);
+      vector<char> has(nt, 0);
+      forTasks_(nt, [&](long c) {
+        double l = 0.0, h = 0.0; bool any = false;
+        for (size_t i = (size_t)c * n / (size_t)nt; i < (size_t)(c + 1) * n / (size_t)nt; ++i)
+        {
+          rt[i] = rtOf(st, fr[i]);
+          if (c == 0) { if (!i || rt[i] < l) l = rt[i]; if (!i || rt[i] > h) h = rt[i]; }
+          else if (rt[i] == rt[i]) { if (!any || rt[i] < l) l = rt[i]; if (!any || rt[i] > h) h = rt[i]; any = true; }
+        }
+        clo[c] = l; chi[c] = h; has[c] = any;
+      });
+      double lo = clo[0], hi = chi[0];
+      for (long c = 1; c < nt; ++c) if (has[c]) { if (clo[c] < lo) lo = clo[c]; if (chi[c] > hi) hi = chi[c]; }
       // A denormal delta_rt makes 1/delta_rt infinite, and an RT range spanning +/-DBL_MAX makes
       // the span infinite; both then produce inf*0 = NaN inside bucketOf. Neither survives real
       // acquisition, but both are reachable and both were UB, so every one degrades to disabled.
@@ -3588,7 +4481,8 @@ protected:
       if (span > 0.0 && span * iv > 65000.0) iv = 65000.0 / span;
       if (!std::isfinite(iv) || !(iv > 0.0)) return;
       rt0 = lo; inv = iv;
-      for (size_t i = 0; i < n; ++i) q[i] = (uint16_t)bucketOf(rt[i]);
+      forTasks_(nt, [&](long c) {
+        for (size_t i = (size_t)c * n / (size_t)nt; i < (size_t)(c + 1) * n / (size_t)nt; ++i) q[i] = (uint16_t)bucketOf(rt[i]); });
     }
   };
 
@@ -3621,14 +4515,15 @@ protected:
   /// grid, up to 3 steps, within max(foreign_ppm_, 30 ppm)). A candidate's positions are mono + k ISO/z, k = 0..3; a
   /// position is present when an admitted fragment lies within foreign_ppm_ of it. With at least foreign_min_iso_
   /// positions present, those fragments are multiplied by foreign_w_ (0 removes them) and their cap key is recomputed
-  /// from the attenuated IM-weighted apex (@p frag_ai). A fragment within max(foreign_ppm_, 30 ppm) of this
+  /// from the attenuated IM-weighted apex (@p frag_ai, attenuated with it). A fragment within max(foreign_ppm_, 30 ppm) of this
   /// precursor's own envelope (mono to M+3) neither counts nor is touched: stripping the own isotopes lost 2.3 % of
   /// peptides in tuning. Two matched positions are weak evidence for a 1+ (or same-charge) fragment and its own
   /// isotope, which line up with a co-isolated envelope of that charge as soon as one does (open). Returns the fragments
-  /// attenuated. @p resc: gate:anchor_rescue's rescued flags, parallel to @p frags when not empty, compacted with it.
+  /// attenuated. @p resc: gate:anchor_rescue's rescued flags, @p frag_kq: the [fuse] key factors; each parallel to @p frags
+  /// when not empty, compacted with it.
   size_t attenuateForeign_(const Precursor_& pc, double drt, const ForeignIdx_& fx, vector<pair<double, double>>& frags,
                            vector<double>& frag_scores, vector<uint32_t>& frag_bin, vector<pair<int, int>>& frag_span,
-                           const vector<double>& frag_ai, vector<char>& resc) const
+                           vector<double>& frag_ai, vector<double>& frag_kq, vector<char>& resc) const
   {
     // The two own-ion tests take a wider tolerance than the envelope match: an ion's residual peaks scatter tens of
     // ppm around the MS1 mono grid (a 10 ng HeLa run: 31 % of the own-grid peaks within 60 ppm lie 20-60 ppm off), and with
@@ -3690,13 +4585,21 @@ protected:
       frags[i].second *= foreign_w_;
       const double L = std::log1p(frag_ai[i]);                       // corr_inten keys are linear in it, the others in its log
       frag_scores[i] = cap_rank_ == 0 ? frag_scores[i] * foreign_w_ : L > 0.0 ? frag_scores[i] * std::log1p(frag_ai[i] * foreign_w_) / L : frag_scores[i];
+      frag_ai[i] *= foreign_w_;                                      // [fuse] a fused key sums the attenuated apex
     }
     if (n && foreign_w_ <= 0.0)                                      // remove: compact every parallel array
     {
       size_t w = 0;
       for (size_t i = 0; i < hit.size(); ++i)
-        if (!hit[i]) { frags[w] = frags[i]; frag_scores[w] = frag_scores[i]; frag_bin[w] = frag_bin[i]; frag_span[w] = frag_span[i]; if (!resc.empty()) resc[w] = resc[i]; ++w; }
-      frags.resize(w); frag_scores.resize(w); frag_bin.resize(w); frag_span.resize(w);
+        if (!hit[i])
+        {
+          frags[w] = frags[i]; frag_scores[w] = frag_scores[i]; frag_bin[w] = frag_bin[i]; frag_span[w] = frag_span[i]; frag_ai[w] = frag_ai[i];
+          if (!frag_kq.empty()) frag_kq[w] = frag_kq[i];
+          if (!resc.empty()) resc[w] = resc[i];
+          ++w;
+        }
+      frags.resize(w); frag_scores.resize(w); frag_bin.resize(w); frag_span.resize(w); frag_ai.resize(w);
+      if (!frag_kq.empty()) frag_kq.resize(w);
       if (!resc.empty()) resc.resize(w);
     }
     cnt[1] += n_env; cnt[3] += (long long)n; cnt[6] += err; cnt[7] += n_match;
@@ -3709,11 +4612,15 @@ protected:
   /// exact bins. Groups the fragments within @p ppm (anchored: strongest first, each unfused fragment an anchor taking
   /// every unfused one within ppm of its own m/z; @p linkage: m/z order, joined to the previous member within ppm and to
   /// the group's first within 2 x ppm). A fused peak: m/z = intensity-weighted mean of the members' (emitted) intensities,
-  /// intensity = their sum, key = their best key, rescued flag = the strongest member's. It sits at its members' lowest
-  /// index, so the relative order of the peaks is kept; a lone fragment is kept bit for bit. @p keys and @p resc (when not
-  /// empty) are parallel to @p frags and compacted with it. Deterministic: every order has a total tie-break and the sums
-  /// run in m/z order. Returns the groups of >= 2 fused and adds their members to @p n_members.
+  /// intensity = their sum, rescued flag = the strongest member's, key = the best-keyed member's factor @p kq (its score,
+  /// and shared frames under evidence) times the summed IM-weighted apex @p ai (ln(1 + sum) when @p log_key), the formula
+  /// of an unfused fragment's key applied to the whole ion; it is never below the best member's key. It sits at its
+  /// members' lowest index, so the relative order of the peaks is kept; a lone fragment is kept bit for bit. @p keys and
+  /// @p resc (when not empty) are parallel to @p frags and compacted with it; @p ai and @p kq are parallel to it on entry
+  /// and stale on return. Deterministic: every order has a total tie-break and the sums run in m/z order. Returns the
+  /// groups of >= 2 fused and adds their members to @p n_members.
   static long long fuseFragments_(vector<pair<double, double>>& frags, vector<double>& keys, vector<char>& resc,
+                                  const vector<double>& ai, const vector<double>& kq, bool log_key,
                                   double ppm, bool linkage, long long& n_members)
   {
     const size_t n = frags.size();
@@ -3757,13 +4664,14 @@ protected:
       }
     }
     if (ng == n) return 0;                                           // nothing within ppm: unchanged
-    struct Acc { double w = 0.0, wmz = 0.0, key = -std::numeric_limits<double>::infinity(); uint32_t head = NONE, top = NONE, n = 0; };
+    struct Acc { double w = 0.0, wmz = 0.0, ai = 0.0; uint32_t head = NONE, top = NONE, best = NONE, n = 0; };
     vector<Acc> acc(ng);
     for (uint32_t i : om)                                            // m/z order: a fixed summation order
     {
       Acc& g = acc[grp[i]];
       g.w += frags[i].second; g.wmz += frags[i].second * frags[i].first;
-      g.key = std::max(g.key, keys[i]);
+      g.ai += ai[i];
+      if (g.best == NONE || keys[i] > keys[g.best]) g.best = i;      // the best key; ties: lower m/z
       g.head = std::min(g.head, i);
       if (g.top == NONE || frags[i].second > frags[g.top].second) g.top = i;   // the strongest; ties: lower m/z
       ++g.n;
@@ -3779,7 +4687,7 @@ protected:
       {
         const double mz = g.w > 0.0 ? g.wmz / g.w : frags[g.top].first;
         const char r = resc.empty() ? 0 : resc[g.top];
-        frags[w] = {mz, g.w}; keys[w] = g.key;
+        frags[w] = {mz, g.w}; keys[w] = kq[g.best] * (log_key ? std::log1p(g.ai) : g.ai);
         if (!resc.empty()) resc[w] = r;
         ++groups; n_members += g.n;
       }
@@ -3804,7 +4712,9 @@ protected:
   {
     vector<pair<double, double>> frags;
     vector<double> frag_scores;
-    vector<double> frag_ai;      // [foreign] each fragment's IM-weighted apex, its cap key's intensity (only with fx)
+    vector<double> frag_ai;      // [foreign]/[fuse] each fragment's IM-weighted apex, its cap key's intensity (only with fx or fusion)
+    vector<double> frag_kq;      // [fuse] each fragment's cap key factor besides that intensity term (only with fusion)
+    const bool fuse_on = fuse_ppm_ > 0.0;
     vector<uint32_t> frag_bin;   // [merge] the TOF bin of each fragment (0: OpenMS detector, no bin; a real bin 0, m/z just
                                  // below the usual 100 m/z floor, is compared by exact m/z like the OpenMS path)
     vector<pair<int, int>> frag_span;   // [merge] its detected window-frame span
@@ -3986,10 +4896,12 @@ protected:
         frags.emplace_back(exportMz_(f.tof, bOf(wst, f), f.mz), emit_inten);
         frag_bin.push_back(f.tof);
         frag_span.emplace_back(f_lo, f_hi);
-        if (fx) frag_ai.push_back(inten);
+        if (fx || fuse_on) frag_ai.push_back(inten);
         frag_scores.push_back(cap_rank_ == 1 ? std::max(c_raw, 0.0) * std::max(c_raw, 0.0) * std::log1p(inten)
                             : cap_rank_ == 2 ? std::max(c_raw, 0.0) * std::log1p(inten) * (1.0 + overlap)
                             : c * inten);                              // [cap] the max_fragments ranking key
+        if (fuse_on)                                                   // [fuse] the same key without its intensity term
+          frag_kq.push_back(cap_rank_ == 1 ? std::max(c_raw, 0.0) * std::max(c_raw, 0.0) : cap_rank_ == 2 ? std::max(c_raw, 0.0) * (1.0 + overlap) : c);
         if (g_anchor && c >= anchor_min_corr_) anchors.push_back((uint32_t)fi);   // [anchor] a well-correlated accepted fragment
       }
       // [anchor] gate:anchor_rescue. A weak fragment of a strong precursor is a 2-3 point tip that fails the plain gate's
@@ -4079,8 +4991,9 @@ protected:
             frags.emplace_back(q.mz, emit_inten);
             frag_bin.push_back(f.tof);
             frag_span.emplace_back(q.t_lo, q.t_hi);
-            if (fx) frag_ai.push_back(inten);                            // [foreign] parallel to frags, as above
+            if (fx || fuse_on) frag_ai.push_back(inten);                 // [foreign]/[fuse] parallel to frags, as above
             frag_scores.push_back(cap_rank_ == 1 ? c * c * std::log1p(inten) : cap_rank_ == 2 ? c * std::log1p(inten) * (1.0 + q.ov) : c * inten);
+            if (fuse_on) frag_kq.push_back(cap_rank_ == 1 ? c * c : cap_rank_ == 2 ? c * (1.0 + q.ov) : c);
             resc.push_back(1);
             resc_fi.push_back(q.fi);
             ++n_why[q.why];
@@ -4133,7 +5046,7 @@ protected:
     for (int gi : touched) pdense[gi] = 0.0f;                          // reset scratch
     // [foreign] other precursors' residual envelopes, before the merge and the cap: a removed fragment frees its slot
     const size_t n_before = frags.size();                              // [foreign] for the fell-below count
-    const size_t n_foreign = fx && !frags.empty() ? attenuateForeign_(pc, g_drt, *fx, frags, frag_scores, frag_bin, frag_span, frag_ai, resc) : 0;
+    const size_t n_foreign = fx && !frags.empty() ? attenuateForeign_(pc, g_drt, *fx, frags, frag_scores, frag_bin, frag_span, frag_ai, frag_kq, resc) : 0;
     // [merge] guard: one TOF bin is one m/z. What toTof's same-frame merge cannot reach (slices beyond its span, valley-
     // split children, band edges, tile carries) is merged here, before the cap, into the strongest member: members whose
     // RT span overlaps its span are summed (parallel slices of one ion), RT-disjoint pieces are dropped (the stronger
@@ -4157,15 +5070,22 @@ protected:
           const size_t head = ord[g];                                    // lowest index: the output order is unchanged
           size_t top = head;
           for (size_t k = g; k < e; ++k) if (frags[ord[k]].second > frags[top].second) top = ord[k];
-          double sum = 0.0, cap = -std::numeric_limits<double>::infinity();
+          double sum = 0.0, cap = -std::numeric_limits<double>::infinity(), asum = 0.0;
+          size_t kb = top;                                               // [fuse] the member whose key the peak takes
           for (size_t k = g; k < e; ++k)
           {
             const size_t i = ord[k];
             if (!(frag_span[i].second < frag_span[top].first || frag_span[top].second < frag_span[i].first))
-            { sum += frags[i].second; cap = std::max(cap, frag_scores[i]); }
+            {
+              sum += frags[i].second;
+              if (frag_scores[i] > cap) kb = i;
+              cap = std::max(cap, frag_scores[i]);
+              if (fuse_on) asum += frag_ai[i];
+            }
             if (k > g) gone[i] = 1;
           }
           frags[head] = {frags[top].first, sum}; frag_scores[head] = cap;
+          if (fuse_on) { frag_ai[head] = asum; frag_kq[head] = frag_kq[kb]; }   // [fuse] the summed apex, the key's member's factor
           if (!resc.empty()) resc[head] = resc[top];                    // [anchor] rescued if its m/z is a rescued one's
           nm += (long long)(e - g - 1);
         }
@@ -4175,19 +5095,27 @@ protected:
       {
         size_t w = 0;
         for (size_t i = 0; i < frags.size(); ++i)
-          if (!gone[i]) { frags[w] = frags[i]; frag_scores[w] = frag_scores[i]; if (!resc.empty()) resc[w] = resc[i]; ++w; }
+          if (!gone[i])
+          {
+            frags[w] = frags[i]; frag_scores[w] = frag_scores[i];
+            if (fuse_on) { frag_ai[w] = frag_ai[i]; frag_kq[w] = frag_kq[i]; }
+            if (!resc.empty()) resc[w] = resc[i];
+            ++w;
+          }
         frags.resize(w); frag_scores.resize(w);
+        if (fuse_on) { frag_ai.resize(w); frag_kq.resize(w); }
         if (!resc.empty()) resc.resize(w);
         mergeCount_()[2] += nm;
       }
     }
-    // [fuse] one peak per fragment ion, after the merge (frag_bin and frag_span are stale from here on) and before
-    // min_fragments and the cap: the cap ranks fused peaks, so the slots of an ion's pieces refill
+    // [fuse] one peak per fragment ion, after the merge (frag_bin, frag_span, frag_ai and frag_kq are stale from here on)
+    // and before min_fragments and the cap: the cap ranks fused peaks by a key recomputed from the summed apex, so the
+    // slots of an ion's pieces refill
     const size_t n_merged = frags.size();                              // [foreign]/[fuse] the fell-below counts
-    if (fuse_ppm_ > 0.0 && n_merged > 0)
+    if (fuse_on && n_merged > 0)
     {
       long long n_mem = 0;
-      const long long n_grp = fuseFragments_(frags, frag_scores, resc, fuse_ppm_, fuse_linkage_, n_mem);
+      const long long n_grp = fuseFragments_(frags, frag_scores, resc, frag_ai, frag_kq, cap_rank_ != 0, fuse_ppm_, fuse_linkage_, n_mem);
       auto& fc = fuseCount_();
       ++fc[0]; fc[1] += (long long)n_merged; fc[2] += (long long)frags.size();
       if (n_grp) { fc[3] += n_grp; fc[4] += n_mem; }
@@ -4250,6 +5178,7 @@ protected:
     // mono call (0/1: the mono may be off by +-k*1.00335 Da, a hint for open-search correction).
     out.setMetaValue("spx_guessed", (int)(pc.guessed ? 1 : 0));
     out.setMetaValue("spx_n_isotopes", pc.n_isotopes);
+    if (twin_ext_mark_ && pc.mono_ext) out.setMetaValue("spx_mono_ext", 1);   // [twin-rt] read and removed by mergeTwins_
   }
 
   /// [arena] Assertions on the SHIPPED compactUnreferenced(): the compaction must survive traces
@@ -4351,6 +5280,38 @@ protected:
     chk(!pair_folds(sp(10.0, 500.001, 2, 1.006, 2, P)), "1/K0 beyond the tolerance: untouched");
     chk(pair_folds(sp(10.0, 500.001, 2, 1.004, 2, P)), "1/K0 inside the tolerance: folded");
     chk(!pair_folds(sp(11.1, 500.0, 2, 1.0, 2, P)), "the next MS1 frame: untouched");
+    // [twin-rt] the near-frame relation (assembly:twin_rt_frames): |dRT| <= rt_tol, inside one RT cell
+    { auto nearFold = [&](double rt_b, double tol, const vector<double>* cells, std::array<size_t, 5>* st = nullptr) {
+        vector<MSSpectrum> v{sp(10.0, 500.0, 2, 1.0, 2, P), sp(rt_b, 500.001, 2, 1.0, 3, P)};
+        return mergeTwins_(v, 0.005, false, tol, cells, 3.0, st) == 1 && v.size() == 1; };
+      const vector<double> edges{20.0};   // cell 0 owns rt < 17, cell 1 rt >= 17 (the first edge T with (T - rt) > 3)
+      std::array<size_t, 5> st{};
+      chk(nearFold(11.1, 1.5, nullptr, &st) && st[0] == 0 && st[1] == 1 && st[3] == 0, "the next MS1 frame inside rt_tol: folded, counted as a near-frame link");
+      chk(nearFold(11.5, 1.5, nullptr), "|dRT| exactly rt_tol: folded (the bound is inclusive)");
+      chk(!nearFold(11.75, 1.5, nullptr), "|dRT| beyond rt_tol: untouched");
+      chk(!nearFold(11.1, 0.0, nullptr), "rt_tol 0: the same-frame relation, the next frame untouched");
+      chk(nearFold(16.9, 7.0, &edges), "both inside one cell: dRT 6.9 within a 7-s tolerance folds");
+      { std::array<size_t, 5> se{};
+        vector<MSSpectrum> v{sp(16.5, 500.0, 2, 1.0, 2, P), sp(17.5, 500.001, 2, 1.0, 3, P)};
+        chk(mergeTwins_(v, 0.005, false, 1.65, &edges, 3.0, &se) == 0 && v.size() == 2 && se[2] == 1, "a pair across a cell edge stays two spectra (counted)"); }
+      { vector<MSSpectrum> v{sp(10.0, 500.0, 2, 1.0, 2, P), sp(10.0, 500.002, 2, 1.0, 2, P), sp(11.1, 500.001, 2, 1.004, 2, P), sp(12.2, 500.0, 2, 1.0, 2, P)};
+        std::array<size_t, 5> sc{};
+        chk(mergeTwins_(v, 0.005, false, 1.2, nullptr, 3.0, &sc) == 3 && v.size() == 1 && sc[0] == 1 && sc[3] == 1 && sc[4] == 1,
+            "frames 10, 11.1, 12.2 chain into one cluster (span 2.2 > rt_tol: counted as chained); the same frame alone folds one"); }
+      { vector<MSSpectrum> v{sp(10.0, 500.0, 2, 1.0, 2, P), sp(11.1, 500.0, 2, 1.006, 2, P), sp(11.1, 500.0, 3, 1.0, 2, P), sp(11.1, 500.0125, 2, 1.0, 2, P)};
+        chk(mergeTwins_(v, 0.005, false, 1.65) == 0 && v.size() == 4, "near frames: 1/K0, charge and 20 ppm still apply"); }
+      { vector<MSSpectrum> v{sp(10.0, 500.0, 2, 1.0, 2, P), sp(11.1, 500.0002, 2, 1.0, 2, P), sp(11.6, 500.00002, 2, 1.0, 2, P), sp(10.0, 500.0005, 2, 1.0, 2, P)};
+        chk(mergeTwins_(v, 0.005, false, 1.65, nullptr, 3.0, nullptr, 1) == 2 && v.size() == 2,
+            "near_bin: across frames only m/z within 0.05 ppm links (10/500.0 with 11.6/500.00002 at 0.04 ppm, not 11.1/500.0002 at 0.4 ppm); one frame keeps the 20-ppm relation"); }
+      { auto ext = [&](MSSpectrum s) { s.setMetaValue("spx_mono_ext", 1); return s; };
+        vector<MSSpectrum> v{sp(10.0, 500.0, 2, 1.0, 2, P), sp(11.1, 500.00002, 2, 1.0, 2, P), sp(20.0, 600.0, 2, 1.0, 2, P), ext(sp(21.1, 600.00002, 2, 1.0, 2, P))};
+        chk(mergeTwins_(v, 0.005, false, 1.65, nullptr, 3.0, nullptr, 2) == 1 && v.size() == 3 && v[0].getRT() == 10.0 && v[1].getRT() == 11.1,
+            "near_mode 2: a one-bin pair across frames folds only when one member's mono came from the v2 extension");
+        bool clean = true; for (const auto& q : v) clean = clean && !q.metaValueExists("spx_mono_ext");
+        chk(clean, "near_mode 2: the spx_mono_ext marks are removed (never written)"); }
+      { vector<MSSpectrum> v{sp(12.0, 500.001, 2, 1.0, 2, P), sp(10.0, 500.0, 2, 1.0, 3, P)};
+        mergeTwins_(v, 0.005, false, 2.5);
+        chk(v.size() == 1 && v[0].getRT() == 10.0 && v[0].getPrecursors()[0].getMZ() == 500.0, "near frames: the survivor rule is the fold's (more isotopes), with its own RT"); } }
     chk(!pair_folds(sp(10.0, 500.0, 3, 1.0, 2, P)), "another charge: untouched");
     chk(!pair_folds(sp(10.0, 500.0125, 2, 1.0, 2, P)), "25 ppm apart: untouched");
     { vector<MSSpectrum> v{sp(10.0, 500.0, 0, 1.0, 2, P), sp(10.0, 500.0, 0, 1.0, 2, P)};
@@ -4480,6 +5441,7 @@ protected:
     mono_pos_im_box_ = getDoubleOption_("charge:mono_position_im_box");
     mono_pos_extend_ = getDoubleOption_("charge:mono_position_extend");
     mono_pos_iterate_ = getStringOption_("charge:mono_position_iterate") == "true";
+    iso_closest_ = getStringOption_("charge:iso_partner") == "closest";
     var_support_ = getFlag_("gate:variance_support");
     short_conc_ = (getStringOption_("gate:short_traces") == "concentric");
     short_center_tol_ = getDoubleOption_("gate:short_center_tol");
@@ -4523,6 +5485,9 @@ protected:
     const Size min_frags = (Size)getIntOption_("assembly:min_fragments");
     const Size max_frags = (Size)getIntOption_("assembly:max_fragments");
     const double twin_im = getDoubleOption_("assembly:twin_im_tolerance");
+    const int twin_rt_frames = getIntOption_("assembly:twin_rt_frames");   // [twin-rt] -1 off, 0 auto, n frames
+    const String twin_rt_match = getStringOption_("assembly:twin_rt_match");
+    const int twin_rt_mode = twin_rt_match == "ppm" ? 0 : twin_rt_match == "bin" ? 1 : 2;
     const int max_charge = getIntOption_("max_charge");
     mzEstimator() = getStringOption_("trace:mz_estimator");   // before any toTrace() call
     const double mass_ppm = getDoubleOption_("trace:mass_error_ppm");
@@ -4738,6 +5703,7 @@ protected:
           }
           return t; };
       }
+      writeLogInfo_("[outer] start-up before the stream reader: " + String(phase_clock_()) + " s");
       try
       {
         if (in_mzpeak)
@@ -4759,6 +5725,7 @@ protected:
                         + String(h[3].load()) + " (" + pc(h[3].load()) + "%), >=10000 " + String(h[4].load()) + " (" + pc(h[4].load()) + "%)"); }
         phaseAdd_("LOAD(stream)", 0.0, 0.0, false);                // [perf-instr] start-to-here
         writeLogInfo_("[perf-load] pick(flush) wall=" + String(flush_wall_(), 1) + " s inside LOAD(stream)");
+        writeLogInfo_("[outer] MS1 pick " + consumer.ms1_pick_mode_);
         if (std::getenv("DIASPEXTRACT_LOAD_ONLY"))
         { if (tile_source) writeLogInfo_("[perf-load] DIASPEXTRACT_LOAD_ONLY under the .d streaming source measures PASS 1 (MS1) only; the MS2 frames are read per tile in pass 2.");
           report_phases_(phase_clock_()); return EXECUTION_OK; }   // [perf-load] decode/hand-off/pick split only
@@ -4993,7 +5960,18 @@ protected:
     //-------------------------------------------------------------
     // MS1 traces + precursor/charge inference (shared, once) [H-8,H-10]
     //-------------------------------------------------------------
-    ms1_map.sortSpectra();
+    // [outer] sortSpectra() = the RT sort, then each spectrum's own m/z sort (a no-op check on a picked spectrum). The
+    // per-spectrum sorts are independent, so they run in parallel after the same RT sort.
+    {
+      const double _tss = phase_clock_();
+      ms1_map.sortSpectra(false);
+      std::exception_ptr ss_err;
+      #pragma omp parallel for schedule(dynamic, 16)
+      for (long i = 0; i < (long)ms1_map.size(); ++i)
+      { try { ms1_map[(Size)i].sortByPosition(); } catch (...) { taskErr_(ss_err); } }
+      if (ss_err) std::rethrow_exception(ss_err);
+      writeLogInfo_("[outer] MS1 spectra sorted in " + String(phase_clock_() - _tss) + " s");
+    }
     const double ms1_snr = getDoubleOption_("trace:ms1_chrom_peak_snr");
     const double ms2_snr = getDoubleOption_("trace:ms2_chrom_peak_snr");
     const double ms2_minlen = getDoubleOption_("trace:ms2_min_length_sec");
@@ -5042,6 +6020,96 @@ protected:
     { vector<uint32_t> ri; ri.reserve(ms1_map.size());
       for (const auto& sp : ms1_map) ri.push_back(rtIndex(sp.getRT()));
       ms1_store.setFrames(ri, nullptr); }
+    // [minlen] trace:min_length_sec < 0 (auto): the run's minimum MS1 trace length from its own peak widths. A fixed
+    // sample of the MS1 map -- every peak in the 1-Th m/z slices [25k, 25k + 1), plus the band halo -- is traced like
+    // the run (tolerances, snr, valley splitter, bands) but with no minimum length, so the estimate does not depend on
+    // the threshold it sets; a whole Th per slice samples every mass-defect phase. The median FWHM W of the brightest
+    // tenth of the traces centred in a slice (ranked by apex intensity, then FWHM: deterministic) sets the minimum to
+    // trace:min_length_fwhm x W, at least half a cycle (2 MS1 points). Fewer than 100 measurable traces, or no cycle,
+    // fall back to 3 s, the value before 1.6.0. A fixed value skips all of it and leaves the header unchanged.
+    double ms1_min_len = getDoubleOption_("trace:min_length_sec");
+    String minlen_stamp;   // spx:ms1_min_length, auto only
+    if (ms1_min_len < 0.0)
+    {
+      const double _tm = phase_clock_();
+      const double frac = getDoubleOption_("trace:min_length_fwhm"), ppm = getDoubleOption_("trace:mass_error_ppm");
+      const double kPitch = 25.0, kWidth = 1.0;
+      auto slicePos = [&](double x) { return x - kPitch * std::floor(x / kPitch); };   // position within its 25-Th period
+      PeakMap smp;
+      TraceStore smp_store;
+      smp_store.setFrames(ms1_store.rt_index, nullptr);
+      vector<Trace> st;
+      size_t smp_pk = 0;
+      const size_t og0 = rtOffGrid().load(), sb0 = rtStrictlyBetween().load();   // [soa-rt] counts the run's traces, not the sample's
+      std::exception_ptr smp_err;
+      #pragma omp parallel
+      #pragma omp single
+      try
+      {
+        // the cut: chunks of spectra in parallel, each spectrum kept in place (empty ones too: the frame sequence)
+        vector<MSSpectrum> part(ms1_map.size());
+        const int nchunk = std::max(1, std::min((int)ms1_map.size(), 4 * omp_get_max_threads()));
+        std::exception_ptr cut_err;   // [task-err]
+        #pragma omp taskloop grainsize(1) default(shared)
+        for (int ci = 0; ci < nchunk; ++ci)
+        { try {
+          const size_t a = (size_t)ci * ms1_map.size() / nchunk, b = (size_t)(ci + 1) * ms1_map.size() / nchunk;
+          for (size_t i = a; i < b; ++i)
+          {
+            const MSSpectrum& s = ms1_map[i];
+            const auto* ima = s.getFloatDataArrays().empty() ? nullptr : &s.getFloatDataArrays()[0];
+            MSSpectrum& t = part[i]; t.setRT(s.getRT()); t.setMSLevel(1);
+            OpenMS::DataArrays::FloatDataArray ia;
+            ia.setName(Constants::UserParam::ION_MOBILITY);
+            for (Size k = 0; k < s.size(); ++k)
+            {
+              const double x = s[k].getMZ(), h = x * ppm * 1e-6 * kBandHaloPpmMul, r = slicePos(x);
+              if (r < kWidth + h || r >= kPitch - h) { t.push_back(s[k]); if (ima && k < ima->size()) ia.push_back((*ima)[k]); }
+            }
+            t.getFloatDataArrays().push_back(std::move(ia));
+          }
+        } catch (...) { taskErr_(cut_err); } }
+        if (cut_err) std::rethrow_exception(cut_err);
+        smp.reserveSpaceSpectra(part.size());
+        for (auto& sp : part) { smp_pk += sp.size(); smp.addSpectrum(std::move(sp)); }
+        vector<MSSpectrum>().swap(part);
+        st = detectTraces_(smp, smp_store, delta_im, getDoubleOption_("trace:noise_threshold_int"), ms1_snr, 0.0,
+                           getDoubleOption_("trace:ms1_split_valleys"), ms1_bands, split_scan_time, -1, LC_MS1BAND);
+      }
+      catch (...) { smp_err = std::current_exception(); }
+      if (smp_err) std::rethrow_exception(smp_err);
+      rtOffGrid().store(og0); rtStrictlyBetween().store(sb0);
+      vector<pair<double, double>> iw;   // (apex intensity, FWHM s) of the traces centred in a slice
+      for (const Trace& t : st)
+        if (std::isfinite(t.mz) && slicePos(t.mz) < kWidth) iw.emplace_back(intensityOf(smp_store, t), xicFwhm(smp_store, t));
+      std::sort(iw.begin(), iw.end(), [](const pair<double, double>& a, const pair<double, double>& b)
+                { return a.first != b.first ? a.first > b.first : a.second < b.second; });
+      const size_t top = iw.size() / 10;
+      vector<double> w;
+      for (size_t i = 0; i < top; ++i) if (iw[i].second > 0.0) w.push_back(iw[i].second);
+      std::sort(w.begin(), w.end());
+      auto q = [&w](double p) { return w[(size_t)(p * (double)(w.size() - 1) + 0.5)]; };
+      const String head = "sample " + String(smp_pk) + " MS1 peaks in 1-Th slices every 25 Th -> " + String(st.size()) + " traces at min length 0, "
+                          + String(iw.size()) + " centred in a slice; brightest tenth " + String(top) + ", " + String(w.size()) + " with a FWHM (>= 3 points)";
+      if (w.size() >= 100 && cycle > 0.0)
+      {
+        const double w50 = q(0.5);
+        ms1_min_len = std::max(frac * w50, 0.5 * cycle);
+        const int pts = 1 + (int)std::ceil(ms1_min_len / cycle - 1e-9);
+        writeLogInfo_("[minlen] auto: " + head + "; FWHM median " + String(w50) + " s = " + String(w50 / cycle) + " cycles (p10 " + String(q(0.1))
+                      + " s = " + String(q(0.1) / cycle) + ", p90 " + String(q(0.9)) + " s = " + String(q(0.9) / cycle) + "), cycle " + String(cycle)
+                      + " s -> trace:min_length_sec " + String(ms1_min_len) + " = max(" + String(frac) + " x median, half a cycle): >= "
+                      + String(pts) + " MS1 points [" + String(phase_clock_() - _tm) + " s]");
+        minlen_stamp = "auto " + String(ms1_min_len) + " s = max(" + String(frac) + " x FWHM median " + String(w50) + " s, half the cycle " + String(cycle)
+                       + " s), >= " + String(pts) + " MS1 points; FWHM of " + String(w.size()) + " bright sampled traces";
+      }
+      else
+      {
+        ms1_min_len = 3.0;
+        writeLogWarn_("[minlen] auto: " + head + ", cycle " + String(cycle) + " s: too few to estimate (100 needed, and a positive cycle); trace:min_length_sec 3, the value before 1.6.0");
+        minlen_stamp = "auto fallback 3 s (" + String(w.size()) + " bright sampled traces with a FWHM, cycle " + String(cycle) + " s)";
+      }
+    }
     // [ms1-prune] every MS1 spectrum must have left its m/z sample before losing a peak, or the band edges
     // would come from a pruned map. Checked here, outside the parallel region an exception cannot leave.
     if (ms1_prune.on && (ms1_prune.frames != ms1_map.size() || ms1_prune.sample.size() != ms1_prune.sample_n))
@@ -5056,19 +6124,28 @@ protected:
     try
     {
       ms1_traces = detectTraces_(ms1_map, ms1_store, delta_im, getDoubleOption_("trace:noise_threshold_int"),
-                                               ms1_snr, getDoubleOption_("trace:min_length_sec"), getDoubleOption_("trace:ms1_split_valleys"), ms1_bands,
+                                               ms1_snr, ms1_min_len, getDoubleOption_("trace:ms1_split_valleys"), ms1_bands,
                                                split_scan_time, LC_MS1MAP, LC_MS1BAND, &ms1_prune);   // [ledger] the partition takes the charge over
     }
     catch (...) { ms1_err = std::current_exception(); }
     if (ms1_err) std::rethrow_exception(ms1_err);
     { const double cap = max_span;
-      if (cap > 0.0) for (auto& t : ms1_traces) trimToSpan(ms1_store, t, cap); }
+      // [outer] per trace, reading the store and writing only its own span fields: in parallel
+      std::exception_ptr trim_err;
+      if (cap > 0.0)
+      {
+        #pragma omp parallel for schedule(static)
+        for (long i = 0; i < (long)ms1_traces.size(); ++i)
+        { try { trimToSpan(ms1_store, ms1_traces[(size_t)i], cap); } catch (...) { taskErr_(trim_err); } }
+      }
+      if (trim_err) std::rethrow_exception(trim_err); }
     vector<double>().swap(ms1_prune.sample);   // [ms1-prune] consumed by the band edges, or unused at one band
     ledSet_(LC_MS1TRACE, (long long)(ms1_traces.capacity() * sizeof(Trace)) + ms1_store.bytes());
     if (detOn_()) writeLogInfo_("[det] MS1 traces n=" + String(ms1_traces.size()) + " digest=" + String(traceDigest_(ms1_store, ms1_traces)));
     phaseAdd_("MS1_TRACE", _t_ms1, _c_ms1, false);
 
-    const double iso_im_tol = getDoubleOption_("charge:iso_im_tolerance");
+    double iso_im_tol = getDoubleOption_("charge:iso_im_tolerance");   // [isotol] 0 = auto, resolved after the content sort
+    String iso_tol_stamp = String(iso_im_tol);
     const double ms2_noise = getDoubleOption_("trace:ms2_noise_threshold_int");
     writeLogInfo_("MS2 trace gate: apex > " + String(ms2_snr * ms2_noise) + " (snr " + String(ms2_snr)
                   + " x noise " + String(ms2_noise) + "), membership > " + String(ms2_noise)
@@ -5097,19 +6174,23 @@ protected:
       if (a.len != b.len) return a.len < b.len;
       return ms1_store.frame_rt[a.frame0] < ms1_store.frame_rt[b.frame0];
     };
-    sort(ms1_traces.begin(), ms1_traces.end(), traceLess);
     {
-      size_t ties = 0;
-      for (size_t i = 1; i < ms1_traces.size(); ++i)
-        if (!traceLess(ms1_traces[i - 1], ms1_traces[i])) ++ties;
+      // [outer] in parallel when that is provably std::sort's order (no equal-key neighbours), else std::sort itself
+      const double _tcs = phase_clock_();
+      const size_t ties = sortExact_(ms1_traces, traceLess);
       writeLogInfo_("[det] MS1 traces sorted by content: " + String(ms1_traces.size()) + " traces, "
                     + String(ties) + " equal-key neighbours");
+      writeLogInfo_("[outer] MS1 content sort " + String(phase_clock_() - _tcs) + " s (" + (ties ? "equal keys: std::sort" : "unique order") + ")");
     }
+    if (iso_im_tol <= 0.0) iso_im_tol = autoIsoImTol_(ms1_traces, ms1_store, max_charge, delta_rt, mass_ppm, iso_tol_stamp);   // [isotol]
+    else writeLogInfo_("[isotol] 1/K0 tolerance for isotope partners " + String(iso_im_tol) + " (fixed)");
+    writeLogInfo_(String("[isotol] partner rule: ") + (iso_closest_ ? "closest to the seed in apex RT and 1/K0 (charge:iso_partner closest)" : "first in m/z order"));
     std::optional<Phase> win_phase;                            // [perf-instr] the window loop (function scope)
     double _t_inf = phase_clock_(), _c_inf = cpu_seconds_();   // [perf-instr]
     vector<MonoV2In_> mono_v2in;   // [monocheck-v2] the count walks, parallel to `precursors` until monoPositionPass_
     vector<Precursor_> precursors = inferPrecursors_(ms1_traces, ms1_store, max_charge, delta_rt, iso_im_tol,
                                                      mass_ppm, env_scoring, mono_check_ == 2 ? &mono_v2in : nullptr);
+    const double _t_inf_fn = phase_clock_();   // [outer] sub-step clock of PRECURSOR_INFER, log only
     if (adaptive_auto_)   // [adaptive] auto: decide the run's gate from its precursor span distribution (MS1 points)
     {
       size_t nf = 0;
@@ -5181,11 +6262,13 @@ protected:
     }
     // [monocheck-v2] At the final charge: after the veto (which reads the walks' own monoisotopes, as without v2),
     // before the charge-less precursors are defaulted or dropped (the veto edits in place, so the order still matches).
+    const double _t_inf_v2a = phase_clock_();   // [outer]
     if (mono_check_ == 2)
     {
       monoPositionPass_(ms1_traces, ms1_store, precursors, mono_v2in, delta_rt, iso_im_tol, mass_ppm, env_scoring);
       vector<MonoV2In_>().swap(mono_v2in);
     }
+    const double _t_inf_v2b = phase_clock_();   // [outer]
     const int default_charge = getIntOption_("assembly:default_charge");
     Size n_default = 0;
     // [way-4] A GUESSED charge and an isotope-SUPPORTED charge must not be emitted identically.
@@ -5225,33 +6308,7 @@ protected:
     const String ms1_dump = getStringOption_("diag:dump_ms1_tsv");
     if (!ms1_dump.empty())
     {
-      // [fwhm] FWHM from the trace's own XIC: apex, then outwards to half maximum with linear interpolation;
-      // a side that never reaches half maximum ends at the first/last point. -1 below 3 points.
-      auto fwhm_of = [&ms1_store](const Trace& tr) -> double {
-        if (tr.np() < 3) return -1.0;
-        vector<double> prt, pv; packReal(ms1_store, tr, prt, pv);
-        size_t ap = 0;
-        for (size_t i = 1; i < pv.size(); ++i) if (pv[i] > pv[ap]) ap = i;
-        const double half = pv[ap] * 0.5;
-        double lo = prt[0], hi = prt[pv.size() - 1];
-        for (size_t i = ap; i > 0; --i)
-          if (pv[i - 1] <= half)
-          {
-            const double d = pv[i] - pv[i - 1];
-            const double f = d > 0 ? (pv[i] - half) / d : 0.0;
-            lo = prt[i] - f * (prt[i] - prt[i - 1]);
-            break;
-          }
-        for (size_t i = ap; i + 1 < pv.size(); ++i)
-          if (pv[i + 1] <= half)
-          {
-            const double d = pv[i] - pv[i + 1];
-            const double f = d > 0 ? (pv[i] - half) / d : 0.0;
-            hi = prt[i] + f * (prt[i + 1] - prt[i]);
-            break;
-          }
-        return hi - lo;
-      };
+      auto fwhm_of = [&ms1_store](const Trace& tr) -> double { return xicFwhm(ms1_store, tr); };   // [fwhm]
       ofstream ft((ms1_dump + ".traces.tsv").c_str());
       // [model] 12 significant digits: the default 6 quantises m/z 765 to ~1.3 ppm.
       ft.precision(12);
@@ -5273,17 +6330,52 @@ protected:
       writeLogInfo_("MS1 funnel dump: " + String(ms1_traces.size()) + " traces, "
                     + String(precursors.size()) + " precursors -> " + ms1_dump + ".{traces,precursors}.tsv");
     }
+    // [twin-rt] assembly:twin_rt_frames: the twin fold's frame tolerance, |dRT| <= (n + 0.5) cycles (0 s = one frame).
+    // Auto (0): n = the median FWHM of the final precursors' seed traces (>= 3 points), in cycles, rounded, >= 1. The
+    // median of a multiset does not depend on the container order, so neither does n.
+    double twin_rt_tol = 0.0;
+    String twin_rt_desc;
+    if (twin_im >= 0.0 && twin_rt_frames >= 0 && cycle > 0.0)
+    {
+      int n = twin_rt_frames;
+      String how = String(n) + " (set)";
+      if (n == 0)
+      {
+        vector<double> fw;
+        fw.reserve(precursors.size());
+        for (const Precursor_& pc : precursors) { const double f = xicFwhm(ms1_store, ms1_traces[pc.trace_idx]); if (f > 0.0) fw.push_back(f); }
+        double med = -1.0;
+        if (!fw.empty()) { const size_t m = fw.size() / 2; std::nth_element(fw.begin(), fw.begin() + (long)m, fw.end()); med = fw[m]; }
+        n = med > 0.0 ? std::max(1, (int)llround(med / cycle)) : 1;
+        char b[200];
+        std::snprintf(b, sizeof b, "%d (auto: median MS1 FWHM %.3f s over %zu seed traces = %.2f cycles)", n, med, fw.size(), med / cycle);
+        how = String(b);
+      }
+      twin_rt_tol = (n + 0.5) * cycle;
+      char b[96];
+      std::snprintf(b, sizeof b, "|dRT| <= %.4f s", twin_rt_tol);
+      twin_rt_desc = "MS1 frames up to " + how + " cycles apart (" + String(b) + ", cycle " + String(cycle) + " s"
+                     + (twin_rt_mode == 0 ? ", precursor m/z within 20 ppm across frames" : twin_rt_mode == 1 ? ", precursor m/z within 0.05 ppm across frames"
+                        : ", across frames precursor m/z within 0.05 ppm and one monoisotope placed by the v2 extension") + "), one RT cell";
+      twin_ext_mark_ = twin_rt_mode == 2;
+      writeLogInfo_("[twins] assembly:twin_rt_frames: the fold joins " + twin_rt_desc);
+    }
     // sort precursors by mono m/z so each window can binary-search its members instead of
     // rescanning all ~1M precursors per window (total order for determinism).
-    sort(precursors.begin(), precursors.end(), [](const Precursor_& a, const Precursor_& b) {
+    // [outer] trace_idx is unique (one precursor per committed seed), so the order is total and sortExact_ sorts in
+    // parallel; an equal-key pair (a non-finite key) would send it to std::sort itself.
+    const double _t_inf_srt = phase_clock_();
+    const size_t prec_ties = sortExact_(precursors, [](const Precursor_& a, const Precursor_& b) {
       if (a.mono_mz != b.mono_mz) return a.mono_mz < b.mono_mz;
       if (a.rt != b.rt) return a.rt < b.rt;
       if (a.im != b.im) return a.im < b.im;
       return a.trace_idx < b.trace_idx;
     });
+    const double _t_inf_cmp = phase_clock_();
     ledSet_(LC_PRECURSOR, (long long)(precursors.capacity() * sizeof(Precursor_) + precursors.size() * 8));
     vector<double> prec_mz(precursors.size());
     for (size_t i = 0; i < precursors.size(); ++i) prec_mz[i] = precursors[i].mono_mz;
+    double _t_inf_trim = 0.0;
     // [mem] Scoring reads only the profiles of traces a precursor points at: release the rest.
     // (ms1_map is already empty: detectTraces_ consumed it.)
     {
@@ -5294,10 +6386,15 @@ protected:
       const Size freed = compactUnreferenced(ms1_traces, ms1_store, needed);
       ledSet_(LC_MS1TRACE, (long long)(ms1_traces.capacity() * sizeof(Trace)) + ms1_store.bytes());
       writeLogInfo_("Released XICs of " + String(freed) + " unreferenced MS1 traces." + rss_() + mem_());
+      _t_inf_trim = phase_clock_();
 #ifdef __GLIBC__
     if (trim_on) trimLogged_("MS1 -> window loop");
 #endif
     }
+    writeLogInfo_("[outer] PRECURSOR_INFER steps: inferPrecursors_ " + String(_t_inf_fn - _t_inf) + " s | veto " + String(_t_inf_v2a - _t_inf_fn)
+                  + " s | monocheck v2 " + String(_t_inf_v2b - _t_inf_v2a) + " s | filters " + String(_t_inf_srt - _t_inf_v2b) + " s | precursor sort "
+                  + String(_t_inf_cmp - _t_inf_srt) + " s (" + (prec_ties ? "equal keys: std::sort" : "unique order") + ") | compaction "
+                  + String(_t_inf_trim - _t_inf_cmp) + " s | trim " + String(phase_clock_() - _t_inf_trim) + " s");
     writeLogInfo_(clk_() + " Detected " + String(ms1_traces.size()) + " MS1 traces -> " + String(precursors.size())
                   + " precursor hypotheses (" + String(n_default) + " assigned default charge)." + rss_());
     std::exception_ptr worker_err;
@@ -5502,13 +6599,39 @@ protected:
     }
     // [tile] carried boundary fragments (records + spans), in for tile k = out of tile k - 1; and
     // the once-only ownership check per precursor (a window's m/z range is tile-independent)
-    struct Carry { vector<Trace> rec; vector<float> inten; };
-    map<WinKey, Carry> carry_in, carry_out;
+    struct Carry { vector<Trace> rec; vector<float> inten;
+                   long long bytes() const { return (long long)(rec.capacity() * sizeof(Trace) + inten.capacity() * 4); } };
+    // [pipe] One slot per window: `c` is carry_out(w, k - 1), and `ready` counts the window's tiles that have
+    // published theirs, so tile k may take `c` once ready == k. Under the per-tile barrier that always holds;
+    // with pipelined tiles it is the one dependency between a window's tiles -- tile k + 1 may slab, prepare,
+    // detect, merge and split while tile k still runs; it waits only where it takes the carry (assembly).
+    struct CarrySlot { Carry c; std::atomic<size_t> ready{0}; };
+    // [pipe] A window's handle on its slot for one tile. take() waits until the window's previous tile has
+    // published, then moves that carry out; publish() hands this tile's carry (put() before it, or none) to
+    // the next tile. The destructor publishes on every exit of the window body, waiting first if the body left
+    // before take(), so a slot is never published out of order and the next tile never waits forever.
+    struct CarryGate
+    {
+      CarrySlot& s; const size_t tk; bool took = false, done = false;
+      void wait() const   // [pipe] idle until the carry arrives: help the tile reader or writer meanwhile
+      { while (s.ready.load(std::memory_order_acquire) < tk) if (!teamAssist_(4)) std::this_thread::sleep_for(std::chrono::microseconds(200)); }
+      Carry take() { wait(); took = true; Carry c = std::move(s.c); s.c = Carry(); ledAdd_(LC_CARRY, -c.bytes()); return c; }
+      void put(Carry&& c) { ledAdd_(LC_CARRY, c.bytes()); s.c = std::move(c); }
+      void publish()
+      {
+        if (done) return;
+        if (!took) { (void)take(); }   // the body left early: drop the previous tile's carry, in order
+        done = true;
+        s.ready.store(tk + 1, std::memory_order_release);
+      }
+      ~CarryGate() { publish(); }
+    };
+    map<WinKey, CarrySlot> carry;
     map<WinKey, uint64_t> slab_chain;   // [det] the per-window slab digest, chained across tiles
     map<WinKey, vector<uint8_t>> visited;
     for (const WinKey& k : fkeys)
     {
-      carry_out[k];
+      carry[k];
       const double lo = k[0] / 100.0, hi = k[1] / 100.0;
       const size_t plo = lower_bound(prec_mz.begin(), prec_mz.end(), lo) - prec_mz.begin();
       const size_t phi = upper_bound(prec_mz.begin(), prec_mz.end(), hi) - prec_mz.begin();
@@ -5554,11 +6677,15 @@ protected:
     out_exp.setMetaValue("spx:dnoise_ms1_params", dnoise.on ? dnoise.params() : String("none"));
     out_exp.setMetaValue("spx:dnoise_ms1_points", dnoise.on ? String("raw " + String(dnoise.total.raw) + " kept " + String(dnoise.total.kept)) : String("none"));
     out_exp.setMetaValue("spx:require_isotope_support", (int)require_iso);
+    if (!minlen_stamp.empty()) out_exp.setMetaValue("spx:ms1_min_length", minlen_stamp);   // [minlen] auto only: a fixed value leaves the header unchanged
     if (mono_check_) out_exp.setMetaValue("spx:monocheck", mono_check_stamp_);   // [monocheck] only when on
+    if (getDoubleOption_("charge:iso_im_tolerance") <= 0.0 || iso_closest_)       // [isotol] only when not the 1.5.0 behaviour
+      out_exp.setMetaValue("spx:iso_im_tolerance", iso_tol_stamp + (iso_closest_ ? ", closest partner in RT and 1/K0" : ", first partner in m/z"));
     if (post_fusion_cap_)   // [recap] only when on: the default header is unchanged
       out_exp.setMetaValue("spx:post_fusion_cap", String("max_fragments ") + String(max_frags) + " after the twin fold, ranked by the "
                            + (cap_rank_ == 2 ? "evidence" : cap_rank_ == 1 ? "umpire" : "corr_inten") + " cap key");
-    out_exp.setMetaValue("spx:twin_merge", twin_im >= 0.0 ? String("same frame, same charge, 20 ppm, 1/K0 <= " + String(twin_im) + ", fused 10 ppm") : String("off"));
+    out_exp.setMetaValue("spx:twin_merge", twin_im < 0.0 ? String("off") : twin_rt_desc.empty() ? String("same frame, same charge, 20 ppm, 1/K0 <= " + String(twin_im) + ", fused 10 ppm")
+                         : String(twin_rt_desc + ", same charge, 20 ppm, 1/K0 <= " + String(twin_im) + ", fused 10 ppm"));   // [twin-rt] the 1.5.0 text when off
     if (frag_int_ != 0)   // [fragint] stamped only when on: the default header is unchanged
       out_exp.setMetaValue("spx:fragint", frag_int_ == 1 ? String("core ") + String(2 * frag_core_half_ + 1) + " frames" : String("sum"));
     if (foreign_w_ < 1.0)   // [foreign] stamped only when on (on by default since 1.6.0; 1 leaves the 1.5.0 header)
@@ -5569,7 +6696,7 @@ protected:
     {
       String s = String(fuse_linkage_ ? "linkage " : "anchored ") + String(fuse_ppm_) + " ppm";
       if (fuse_linkage_) s += String(" (group span <= ") + String(2.0 * fuse_ppm_) + " ppm)";
-      s += ", summed intensity, intensity-weighted m/z, best cap key; after the same-bin merge, before min_fragments and max_fragments";
+      s += ", summed intensity, intensity-weighted m/z, cap key from the summed apex; after the same-bin merge, before min_fragments and max_fragments";
       out_exp.setMetaValue("spx:fragment_fuse", s);
     }
     std::unique_ptr<TileWriter> writer;
@@ -5580,6 +6707,7 @@ protected:
     vector<MSSpectrum> all_out;   // the bulk (mzPeak) path only
     Size n_out = 0;
     Size n_twins = 0;   // [twins] spectra folded into a twin, over every tile
+    std::array<size_t, 5> twin_st{};   // [twin-rt] mergeTwins_'s counters, over every tile
     std::array<size_t, 4> recap{};   // [recap] spectra re-capped, peaks removed, largest spectrum before, spectra seen
     writeLogInfo_("Processing " + String(n_win) + " isolation windows in " + String(tiles.size()) + " tile(s) from the " + (tile_source ? "streaming" : "resident") + " source (OpenMP over windows, <="
                   + String(n_conc) + " concurrent, admission bounded by " + String((int)(mem_frac * 100))
@@ -5590,15 +6718,45 @@ protected:
     // window is an OpenMP task, so idle threads steal across windows. Results go to index-addressed slots
     // (win_out[wi], pslot[j], per[ci][b]), never appended in completion order.
     std::atomic<int> active{0};
-    for (size_t tk = 0; tk < tiles.size(); ++tk)
+    // [pipe] Pipelined tiles. With the per-tile barrier, every tile waits for its slowest window chain and the
+    // read, sort, merge, write and trim between two tiles overlap nothing. Pipelined, ONE parallel region
+    // spans the whole loop and its single thread drives it: it reads tile k + 1 and admits its windows while
+    // tile k's still run, and finishes (sorts, merges, writes, trims) the tiles strictly in tile order as each
+    // completes. A window's tiles depend on each other only through the carry (CarryGate); tiles own disjoint
+    // precursors and are sorted and written per tile as before, so the output is the barrier's, bit for bit.
+    // DIASPEXTRACT_PIPE_TILES=<n> (default 2, 1 = the per-tile barrier) bounds the tiles whose windows may run
+    // at once: tile j is read only after every window of tile j - n has finished, which bounds the slabs
+    // resident and the chain of carry waits; the window cap and the memory admission below still apply to
+    // every window in flight, over all tiles. The reader's and writer's loops run as tasks of the window team
+    // (teamFor_); only the vendor reader's own decode loop (libOpenMS) opens a nested team.
+    const int pipe_depth = []() { const char* e = std::getenv("DIASPEXTRACT_PIPE_TILES");
+                                  const long v = e && *e ? std::atol(e) : 2L; return (int)std::max(1L, std::min(v, 16L)); }();
+    const bool pipe = pipe_depth > 1 && tiles.size() > 1 && n_threads > 1;
+    std::atomic<bool> pipe_abort{false};   // a window or the driver failed: admit nothing more, skip unstarted windows
+    writeLogInfo_("[pipe] " + (pipe ? "tiles pipelined, up to " + String(pipe_depth) + " with windows in flight"
+                                    : String("off (") + (pipe_depth <= 1 ? "DIASPEXTRACT_PIPE_TILES=1" : tiles.size() <= 1 ? "one tile" : "one thread")
+                                      + "): a barrier after every tile"));
+    // [pipe] One tile in flight: its slabs, its windows heaviest-first, their output slots, and how many of its
+    // windows have not finished yet (the driver finishes the tile once that is 0).
+    struct TileRun
+    {
+      size_t tk = 0;
+      map<WinKey, PeakSlab> tile_slabs;
+      vector<pair<WinKey, PeakSlab*>> wl;
+      vector<vector<MSSpectrum>> win_out;
+      Size win_done = 0;
+      std::atomic<size_t> left{0};
+    };
+    auto loadTile = [&](TileRun& R)
     {
+    const size_t tk = R.tk;
     const Tile& tile = tiles[tk];
     ledPhaseTile_("tile", tk + 1);
     // [tile] the tile's slabs: one tile = the resident slabs themselves (moved out by the body, as
     // today); several = a slice of each window's frames in [lo, hi) (the resident source keeps the
     // whole run: this arm is the exactness gate, not the memory configuration)
-    map<WinKey, PeakSlab> tile_slabs;
-    vector<pair<WinKey, PeakSlab*>> wl;
+    map<WinKey, PeakSlab>& tile_slabs = R.tile_slabs;
+    vector<pair<WinKey, PeakSlab*>>& wl = R.wl;
     if (tile_source)
     {
       // [3b] read the tile: a fresh consumer over the loader's RT range, lockstep-padded against
@@ -5639,7 +6797,8 @@ protected:
         n_peaks += sl.peaks();
       }
       for (auto& kv : tile_slabs) indexRt(kv.second);
-      { long long sb = 0; for (const auto& kv : tile_slabs) sb += (long long)kv.second.bytes(); ledSet_(LC_SLAB, sb); }
+      { long long sb = 0; for (const auto& kv : tile_slabs) sb += (long long)kv.second.bytes();
+        if (pipe) ledAdd_(LC_SLAB, sb); else ledSet_(LC_SLAB, sb); }   // [pipe] other tiles' slabs may still be live
       if (detOn_() && integer_detector)   // the OpenMS path needs the slabs in m/z quanta (materializeWindow)
         // [det] the reader's exactness: the per-(window, tile) slab digest, chained over the tiles.
         // The tiles partition a window's frames in RT order and the digest is a sequential fold, so
@@ -5684,26 +6843,51 @@ protected:
       std::stable_sort(wl.begin(), wl.end(), heavyFirst);
     }
     else wl = window_list;
-    vector<vector<MSSpectrum>> win_out(wl.size());
-    Size win_done = 0;
-    #pragma omp parallel num_threads(n_threads)
-    #pragma omp single
-    for (long wi = 0; wi < (long)wl.size(); ++wi)
+    R.win_out.resize(wl.size());
+    R.left.store(wl.size());
+    };   // loadTile
+    // [pipe] the window body, defined below the admission that spawns it
+    std::function<void(TileRun*, long, size_t)> runWindow;
+    auto admitTile = [&](TileRun* R)
+    {
+    auto* rw = &runWindow;
+    for (long wi = 0; wi < (long)R->wl.size() && !pipe_abort.load(); ++wi)
     {
-      const size_t need = project(*wl[wi].second);
+      const size_t need = project(*R->wl[wi].second);
       for (;;)
       {
         const size_t budget = (size_t)(availableBytes_() * mem_frac);
         // [dyn-mem] admit while fewer than n_conc windows are in flight and the projection fits mem_fraction
         // of MemAvailable (re-read at every admission); an empty pipeline always admits, however large the window
         if ((active.load() == 0) || (active.load() < n_conc && inflight.load() + need <= budget)) break;
-        #pragma omp taskyield
+        // [review] A team of ONE (-threads 1, OMP_THREAD_LIMIT=1, OMP_DYNAMIC) has nobody else to run the windows admitted
+        // so far, and libgomp's taskyield is a no-op: once the window cap or the memory budget held, this loop spun forever
+        // (the barrier path since before the pipeline, and the pipeline's solo fallback). In a team of one every queued
+        // window is a child of this thread, so taskwait runs them, which releases their admission charges.
+        if (omp_get_num_threads() < 2)
+        {
+          #pragma omp taskwait
+          continue;
+        }
+        if (!pipe)   // [pipe] the driver must not be handed a window here (a no-op in libgomp, not in every runtime)
+        {
+          #pragma omp taskyield
+        }
         std::this_thread::sleep_for(std::chrono::milliseconds(20));
       }
       inflight += need; ++active;
       if (active.load() > adm_hwm.load()) adm_hwm.store(active.load());
-      #pragma omp task default(shared) firstprivate(wi, need)
-      {
+      #pragma omp task default(none) firstprivate(rw, R, wi, need)
+      (*rw)(R, wi, need);
+    }
+    };   // admitTile
+    runWindow = [&](TileRun* R, const long wi, const size_t need)
+    {
+      const size_t tk = R->tk;
+      const Tile& tile = tiles[tk];
+      vector<pair<WinKey, PeakSlab*>>& wl = R->wl;
+      vector<vector<MSSpectrum>>& win_out = R->win_out;
+      Size& win_done = R->win_done;
       // A lambda, because `continue` is not a legal exit from a task's structured block and the
       // window body has one early exit (a window whose fragments all fail the finiteness filter).
       [&]() {
@@ -5714,6 +6898,9 @@ protected:
         // admitted by the master before this task existed; release both charges however we leave
         struct Release { std::atomic<size_t>& b; std::atomic<int>& a; size_t n;
                          ~Release() { b -= n; --a; } } rel{inflight, active, need};
+        // [pipe] this window's carry slot: its destructor publishes this tile's carry on every exit
+        CarryGate gate{carry.at(wl[wi].first), tk};
+        if (pipe_abort.load()) return;   // [pipe] a window or the driver failed: the run is ending
         // Per-window stage seconds and the completion line, printed on EVERY exit of the body
         // (empty window, any assembly arm, exception): what the profile could only infer. [mem]
         double w_prep = 0, w_trace = 0, w_split = 0, w_score = 0, w_emit = 0;
@@ -5836,7 +7023,14 @@ protected:
               // the window's band edges must enclose the cell's bins: bandOf() and the tof index
               // wrap for a bin below tlo (review M2). A run-level freeze must be a superset. In
               // every mode, one cell included (review 3a: the acquisition edges are metadata).
-              TofIdx clo = 0xFFFFFFFFu, chi = 0; for (TofIdx t : cs.tof) { clo = std::min(clo, t); chi = std::max(chi, t); }
+              // [serial] the extremes as tasks: min and max are exact in any order
+              const size_t np = cs.tof.size();
+              const long nr = parTasks_(np, 1 << 18);
+              vector<TofIdx> clos(nr, 0xFFFFFFFFu), chis(nr, 0);
+              forTasks_(nr, [&](long c) {
+                for (size_t k = (size_t)c * np / (size_t)nr; k < (size_t)(c + 1) * np / (size_t)nr; ++k)
+                { clos[c] = std::min(clos[c], cs.tof[k]); chis[c] = std::max(chis[c], cs.tof[k]); } });
+              const TofIdx clo = *std::min_element(clos.begin(), clos.end()), chi = *std::max_element(chis.begin(), chis.end());
               if (clo < tlo || chi > thi) throw OpenMS::Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
                     "cell bins outside the window's band edges", String(clo) + "-" + String(chi) + " vs " + String(tlo) + "-" + String(thi));
             }
@@ -5856,6 +7050,7 @@ protected:
               #pragma omp taskloop grainsize(1) default(shared)
               for (int b = 0; b < nb; ++b)
               { try {
+                teamAssist_(1);   // [pipe] a chunk of the pipelined tile reader or writer, if one is live
                 pc[b] = detectTracesInteger_(cs, tprep, bc[b], mass_ppm, delta_im, ms2_noise, ms2_minlen,
                                              bnd[b], bnd[b + 1], b);
               } catch (...) { taskErr_(band_err); } }
@@ -5893,16 +7088,11 @@ protected:
           if (nb > 1)
             writeLogInfo_("[mem] window " + String(win_lo) + "-" + String(win_hi) + " merge: " + String(n_cells) + " cell(s) x " + String(nb) + " band arenas, "
                           + String(arena) + " floats (" + String(arena * (any_bins ? 6 : 4) / (1024ULL * 1024ULL)) + " MB) x2 while absorbed, " + String(tot) + " traces");
-          for (size_t ci = 0; ci < n_cells; ++ci)
-          {
-            const uint32_t f0 = (uint32_t)f0z[ci];             // the cell's first frame in the frozen table
-            for (int b = 0; b < nb; ++b)
-            {
-              const uint32_t base = wst.absorb(bst[ci][b]);
-              for (auto& t : per[ci][b]) { t.off += base; t.frame0 += f0; t.bframe += f0; frag_traces.push_back(std::move(t)); }
-              vector<Trace>().swap(per[ci][b]);
-            }
-          }
+          { // [serial] absorbed in (cell, band) order, rebased by the cell's first frame in the frozen table; copies as tasks
+            vector<std::pair<TraceStore*, vector<Trace>*>> src; vector<uint32_t> fsh;
+            for (size_t ci = 0; ci < n_cells; ++ci)
+              for (int b = 0; b < nb; ++b) { src.push_back({&bst[ci][b], &per[ci][b]}); fsh.push_back((uint32_t)f0z[ci]); }
+            absorbAll_(wst, frag_traces, src, fsh); }
           w_merge = secs(std::chrono::steady_clock::now() - _tm0);
           ledAdd_(LC_BAND, -band_bytes); ledAdd_(LC_PARENT, -parent_bytes); ledStore();
           }                                                  // the band stores die here
@@ -5911,7 +7101,10 @@ protected:
           auto _ts = std::chrono::steady_clock::now();
           frag_traces = splitIntegerTraces(frag_traces, ms2_split, wst, n_bands * 4, split_scan_time);
           w_split = secs(std::chrono::steady_clock::now() - _ts); ledStore();
-          if (max_span > 0.0) for (auto& t : frag_traces) trimToSpan(wst, t, max_span);
+          if (max_span > 0.0)   // [serial] per trace, independent: as tasks over trace chunks
+          { const size_t n = frag_traces.size(); const long nr = parTasks_(n, 1 << 16);
+            forTasks_(nr, [&](long c) { for (size_t i = (size_t)c * n / (size_t)nr; i < (size_t)(c + 1) * n / (size_t)nr; ++i)
+                                          trimToSpan(wst, frag_traces[i], max_span); }); }
           vector<int16_t>().swap(wst.bins); ledStore();
           writeLogInfo_("[mem] window " + String(win_lo) + "-" + String(win_hi) + ": seeds " + String(n_seeds) + " of " + String(n_peaks)
                         + " peaks (" + String((int)(1000.0 * n_seeds / std::max<size_t>(n_peaks, 1)) / 10.0) + "%); traces " + String(n_parents)
@@ -5937,11 +7130,12 @@ protected:
         // [tile] the previous tile's boundary fragments join this window's list, spans copied
         // onto its arena; their frame indices are the frozen table's already (the same table in
         // every tile), and they enter BEFORE the content sort, so they take their canonical places.
+        // [pipe] take() waits for this window's previous tile to publish them: the one point where a
+        // window's tiles meet (everything above ran on this tile's slab alone).
         size_t n_carried_in = 0;
-        { const auto cit = carry_in.find(wl[wi].first);
-          if (cit != carry_in.end() && !cit->second.rec.empty())
+        { const Carry ci = gate.take();
+          if (!ci.rec.empty())
           {
-            const Carry& ci = cit->second;
             frag_traces.reserve(frag_traces.size() + ci.rec.size());
             for (const Trace& r : ci.rec)
             {
@@ -5984,7 +7178,9 @@ protected:
 
         // Content-only and TOTAL: traces equal in (im, mz, rt, apex intensity) fall through to the remaining
         // fields, so their order never depends on what else is resident; exact duplicates are interchangeable.
-        sort(frag_traces.begin(), frag_traces.end(), [&wst](const Trace& a, const Trace& b) {
+        // [serial] Sorted as tasks (parallelSort_): it may order exact duplicates differently from std::sort, which
+        // the comparator already allows -- the order of what else is resident moves them too.
+        parallelSort_(frag_traces.data(), frag_traces.size(), [&wst](const Trace& a, const Trace& b) {
           if (a.im != b.im) return a.im < b.im;
           if (a.mz != b.mz) return a.mz < b.mz;
           { const double ra = rtOf(wst, a), rb = rtOf(wst, b); if (ra != rb) return ra < rb; }
@@ -5998,10 +7194,42 @@ protected:
           if (a.bframe != b.bframe) return a.bframe < b.bframe;
           if (a.rt_at != b.rt_at) return a.rt_at < b.rt_at;
           return false;
-        });
+        }, parTasks_(frag_traces.size(), 1 << 15));
+        // [tile] carry the boundary fragments to the next tile: every record (own or carried in)
+        // whose RT is within 2 tile_drt of this tile's upper edge -- the candidates of a precursor
+        // the next tile owns. Over ALL of frag_traces, so the carry is transitive by induction.
+        // A precursor a later tile owns has (T - rt) <= tile_drt, its candidates x have
+        // (rt - x) <= tile_drt: x >= T - 2 tile_drt up to two roundings of ~1e-12 s. The slack
+        // over-carries by a hair (a carried fragment no precursor accepts changes nothing), never
+        // under-carries (review, step 2: the exact form dropped a fragment at 1.2000000000000002).
+        // [pipe] Taken and published HERE, after the content sort: scoring below only reads frag_traces
+        // and the arena, so this is the carry the end of the body would produce, and the window's next
+        // tile may assemble while this one scores.
+        static const bool no_carry = std::getenv("DIASPEXTRACT_TILE_NO_CARRY") != nullptr;   // e2e falsifier only
+        if (!tile.last && !no_carry)
+        {
+          Carry co;
+          const double keep_from = tile.hi - 2.0 * tile_drt - 1e-6;
+          for (const Trace& t : frag_traces)
+            if (rtOf(wst, t) >= keep_from)
+            {
+              Trace c = t; c.off = (uint32_t)co.inten.size();
+              co.inten.insert(co.inten.end(), wst.inten.begin() + t.off, wst.inten.begin() + t.off + t.len);
+              co.rec.push_back(c);
+            }
+          if (n_carried_in || !co.rec.empty())
+          {
+            #pragma omp critical(winlog)
+            writeLogInfo_("[tile] window " + String(win_lo) + "-" + String(win_hi) + " tile " + String(tk + 1) + ": carried in "
+                          + String(n_carried_in) + ", carrying out " + String(co.rec.size()) + " fragments (" + String((co.rec.size() * sizeof(Trace) + co.inten.size() * 4) / 1024) + " KB)");
+          }
+          gate.put(std::move(co));
+        }
+        gate.publish();
         vector<double> frag_im(frag_traces.size());
-        for (size_t i = 0; i < frag_traces.size(); ++i) frag_im[i] = frag_traces[i].im;
-        FragRt frag_rt; frag_rt.build(frag_traces, wst, tile_drt);   // [adaptive] buckets cover the wider window
+        { const size_t n = frag_traces.size(); const long nr = parTasks_(n, 1 << 17);   // [serial] as tasks
+          forTasks_(nr, [&](long c) { for (size_t i = (size_t)c * n / (size_t)nr; i < (size_t)(c + 1) * n / (size_t)nr; ++i) frag_im[i] = frag_traces[i].im; }); }
+        FragRt frag_rt; frag_rt.build(frag_traces, wst, tile_drt, parTasks_(frag_traces.size(), 1 << 17));   // [adaptive] buckets cover the wider window
         w_sort = secs(std::chrono::steady_clock::now() - _tso);
 
         // Precompute the common correlation grid once per window; pdense is reused across the
@@ -6045,6 +7273,7 @@ protected:
             taskFault_("assemble");
             for (;;)
             {
+              teamAssist_(1);   // [pipe] a chunk of the pipelined tile reader or writer, if one is live
               const long cs = pcur.fetch_add(32);
               if (cs >= n_prec_w) break;
               const long ce = std::min(cs + 32, n_prec_w);
@@ -6068,42 +7297,23 @@ protected:
           const auto _t7 = std::chrono::steady_clock::now();
           w_emit = secs(_t7 - _t6);
         }
-        // [tile] carry the boundary fragments to the next tile: every record (own or carried in)
-        // whose RT is within 2 tile_drt of this tile's upper edge -- the candidates of a precursor
-        // the next tile owns. Over ALL of frag_traces, so the carry is transitive by induction.
-        // A precursor a later tile owns has (T - rt) <= tile_drt, its candidates x have
-        // (rt - x) <= tile_drt: x >= T - 2 tile_drt up to two roundings of ~1e-12 s. The slack
-        // over-carries by a hair (a carried fragment no precursor accepts changes nothing), never
-        // under-carries (review, step 2: the exact form dropped a fragment at 1.2000000000000002).
-        static const bool no_carry = std::getenv("DIASPEXTRACT_TILE_NO_CARRY") != nullptr;   // e2e falsifier only
-        if (!tile.last && !no_carry)
-        {
-          Carry& co = carry_out.at(wl[wi].first);
-          const double keep_from = tile.hi - 2.0 * tile_drt - 1e-6;
-          for (const Trace& t : frag_traces)
-            if (rtOf(wst, t) >= keep_from)
-            {
-              Trace c = t; c.off = (uint32_t)co.inten.size();
-              co.inten.insert(co.inten.end(), wst.inten.begin() + t.off, wst.inten.begin() + t.off + t.len);
-              co.rec.push_back(c);
-            }
-          if (n_carried_in || !co.rec.empty())
-          {
-            #pragma omp critical(winlog)
-            writeLogInfo_("[tile] window " + String(win_lo) + "-" + String(win_hi) + " tile " + String(tk + 1) + ": carried in "
-                          + String(n_carried_in) + ", carrying out " + String(co.rec.size()) + " fragments (" + String((co.rec.size() * sizeof(Trace) + co.inten.size() * 4) / 1024) + " KB)");
-          }
-        }
       }
       catch (...)
       {
         #pragma omp critical
         if (!worker_err) worker_err = std::current_exception();
+        pipe_abort.store(true);
       }
       }();   // window body
-      }      // omp task
-    }
-    if (worker_err) std::rethrow_exception(worker_err);
+      R->left.fetch_sub(1, std::memory_order_acq_rel);   // [pipe] last: the driver may finish the tile after this
+    };   // runWindow
+    // [pipe] After every window of the tile has finished: the coverage check (last tile), the canonical sort,
+    // the twin fold, the post-fusion cap and the write of the tile's block, then the between-tile trim.
+    auto finishTile = [&](TileRun& R)
+    {
+    const size_t tk = R.tk;
+    const Tile& tile = tiles[tk];
+    vector<vector<MSSpectrum>>& win_out = R.win_out;
     if (tile.last)
     {
       // [tile] coverage: every finite precursor of every window was owned by exactly one tile
@@ -6159,7 +7369,7 @@ protected:
       if (twin_im >= 0.0)
       {
         Phase _ph("MERGE(twins)");
-        const size_t before = tile_out.size(), gone = mergeTwins_(tile_out, twin_im, post_fusion_cap_);
+        const size_t before = tile_out.size(), gone = mergeTwins_(tile_out, twin_im, post_fusion_cap_, twin_rt_tol, &cell_edges, tile_drt, &twin_st, twin_rt_mode);
         n_twins += gone;
         writeLogInfo_("[twins] tile " + String(tk + 1) + "/" + String(tiles.size()) + ": " + String(gone) + " of " + String(before) + " spectra folded into a twin");
       }
@@ -6185,22 +7395,120 @@ protected:
         for (auto& sp : tile_out) all_out.push_back(std::move(sp));   // [ledger] the same bytes, still charged
       }
     }
-    carry_in = std::move(carry_out);
-    { long long cb = 0; for (const auto& kv : carry_in) cb += (long long)(kv.second.rec.capacity() * sizeof(Trace) + kv.second.inten.capacity() * 4);
-      ledSet_(LC_CARRY, cb); }
-    carry_out.clear();
-    for (const WinKey& k : fkeys) carry_out[k];
 #ifdef __GLIBC__
     // [trim] Between tiles, under perf:malloc_trim: nothing else returns the allocator's free pages here -- the in-loop
     // trim above runs only when there is one tile -- so a tiled loop's RSS would ratchet toward the arena pass 1 sized.
     // After tile k is written, before tile k+1 is read; about 4 GB off TNBC 009 and 0.5 GB off dataset D. Output-identical.
+    // [pipe] Pipelined, the later tiles in flight keep their pages: the trim returns what tile k left behind.
     if (trim_on && tk + 1 < tiles.size())
     { const double _tt = phase_clock_(); const long _r0 = rss_mb_();
       malloc_trim(0);
       writeLogInfo_("[trim] tile " + String(tk + 1) + "/" + String(tiles.size()) + ": " + String(_r0) + " -> " + String(rss_mb_()) + " MB RSS in "
                     + String(phase_clock_() - _tt) + " s" + mem_()); }
 #endif
-    }   // tiles
+    };   // finishTile
+
+    if (!pipe)
+      for (size_t tk = 0; tk < tiles.size(); ++tk)
+      {
+        TileRun R;
+        R.tk = tk;
+        loadTile(R);
+        #pragma omp parallel num_threads(n_threads)
+        #pragma omp single
+        admitTile(&R);
+        if (worker_err) std::rethrow_exception(worker_err);
+        finishTile(R);
+      }
+    else
+    {
+      // [pipe] The driver is thread 0 of ONE parallel region over all tiles: it reads tile fin + pipe_depth - 1
+      // while tile fin's windows run, admits its windows as the cap and memory allow, and once tile fin's windows
+      // are done hands the tile to the WRITER, a task that finishes the tiles strictly in tile order. So the read
+      // of the next tile never waits behind a write (scal-pipe-1 ran both on the driver: on a 60-min run at 100 threads
+      // read + write per heavy tile outlasted the tile's windows, which then sat idle at three boundaries).
+      // The driver does not run windows: it reaches no taskgroup end or taskwait (teamFor_, and parTasks_ keeps its
+      // passes inline), so its n_threads - 1 team mates run the windows, the writer, and the reader's and writer's helper
+      // tasks when they are free. One exception remains: past libgomp's task cliff (team task count > 64 x nthreads) a
+      // spawned window or writer runs undeferred in the driver -- a stall, not a deadlock (review 2026-10-01).
+      // Thread 0 rather than `single`'s first arrival: the vendor reader's decode loop opens a nested team next
+      // to the driver's place, so under OMP_PROC_BIND=close it shares the window team's cores, never others.
+      // Deadlock-free: a window waits only on its own previous tile (CarryGate), which was admitted earlier and
+      // is dequeued earlier (the team queue is FIFO), and a tile is read only after tile j - pipe_depth finished,
+      // so that previous tile never waits itself; the writer of tile f waits only for the writer of tile f - 1,
+      // spawned (and dequeued) before it.
+      omp_set_max_active_levels(std::max(2, omp_get_max_active_levels()));
+      vector<std::unique_ptr<TileRun>> runs(tiles.size());
+      std::exception_ptr drv_err;
+      auto drvFail = [&]() {
+        #pragma omp critical(pipe_err)
+        if (!drv_err) drv_err = std::current_exception();
+        pipe_abort.store(true);
+      };
+      std::atomic<size_t> written{0};   // tiles the writer has finished, in tile order
+      auto writeTile = [&](const size_t f)   // the writer: outside the region, so a queued task never outlives it
+      {
+        while (written.load(std::memory_order_acquire) < f) std::this_thread::sleep_for(std::chrono::milliseconds(1));
+        try { if (!pipe_abort.load()) finishTile(*runs[f]); } catch (...) { drvFail(); }
+        runs[f].reset();
+        written.store(f + 1, std::memory_order_release);   // on every exit: the next writer never waits forever
+      };
+      #pragma omp parallel num_threads(n_threads)
+      if (omp_get_thread_num() == 0)
+      {
+        // A team of one (OMP_DYNAMIC, a thread limit) has nobody to run the windows while the driver polls: then
+        // one tile at a time, run by the driver's own taskwait and written by the driver -- the barrier's schedule.
+        const bool solo = omp_get_num_threads() < 2;
+        const size_t depth = solo ? 1 : (size_t)pipe_depth;
+        size_t next = 0;   // the next tile to read
+        auto issue = [&](const size_t upto)
+        {
+          for (; next < tiles.size() && next < upto && !pipe_abort.load(); ++next)
+          {
+            runs[next].reset(new TileRun);
+            runs[next]->tk = next;
+            loadTile(*runs[next]);
+            admitTile(runs[next].get());
+          }
+        };
+        onPipeDriver_() = !solo;   // [review] no taskloop on the driver (parTasks_); solo runs its windows itself anyway
+        try
+        {
+          for (size_t fin = 0; fin < tiles.size() && !pipe_abort.load(); ++fin)
+          {
+            // [review] Backpressure on the writer: at most `depth` tiles whose windows are done wait for their write. Without
+            // it the driver kept reading and admitting while the writer lagged (slow output storage), so finished spectra and
+            // writer tasks spinning on their predecessor piled up without a bound. Never binds while the writer keeps pace:
+            // by the read/write order in their logs it would not have bound in any of the 38 pipelined scalfix/integrate
+            // runs. Deadlock-free: writers 0..fin-1 are spawned, and they wait only on each other, in spawn order.
+            while (written.load(std::memory_order_acquire) + depth < fin && !pipe_abort.load())
+              if (!teamAssist_(8)) std::this_thread::sleep_for(std::chrono::milliseconds(1));   // help the writer meanwhile
+            if (pipe_abort.load()) break;
+            issue(fin + depth);
+            if (!runs[fin]) break;   // the reader stopped (a failure)
+            TileRun& R = *runs[fin];
+            if (solo)
+            {
+              #pragma omp taskwait
+            }
+            while (R.left.load(std::memory_order_acquire) != 0 && !pipe_abort.load())
+              if (!teamAssist_(8)) std::this_thread::sleep_for(std::chrono::milliseconds(1));   // help the writer meanwhile
+            if (pipe_abort.load()) break;
+            if (solo) writeTile(fin);
+            else
+            {
+              auto* wt = &writeTile;
+              #pragma omp task default(none) firstprivate(wt, fin)
+              (*wt)(fin);
+            }
+          }
+        }
+        catch (...) { drvFail(); }
+        onPipeDriver_() = false;
+      }   // the region's barrier: every admitted window and every writer has finished
+      if (drv_err) std::rethrow_exception(drv_err);
+      if (worker_err) std::rethrow_exception(worker_err);
+    }
 
     win_phase.reset();   // [perf-instr] WINDOW_LOOP ends here: the tile loop's own phases were enclosed in it, the final write is not
     writeLogInfo_("[soa-rt] off-grid " + String(rtOffGrid().load())
@@ -6234,6 +7542,11 @@ protected:
     writeLogInfo_("Wrote " + String(n_out) + " pseudo-MS2 spectra to " + out
                   + " (" + String(FileTypes::typeToName(out_type)) + ")");
     if (twin_im >= 0.0) writeLogInfo_("[twins] " + String(n_twins) + " spectra folded into a twin (assembly:twin_im_tolerance " + String(twin_im) + ")");
+    if (twin_im >= 0.0 && twin_rt_tol > 0.0)   // [twin-rt] the before/after of the near-frame relation
+      writeLogInfo_("[twins] assembly:twin_rt_frames: " + String(twin_st[0]) + " twin pairs at one MS1 frame, " + String(twin_st[1])
+                    + " same-monoisotope pairs at nearby frames joined, " + String(twin_st[2]) + " left apart at an RT cell edge; "
+                    + String(n_twins - std::min<size_t>(n_twins, twin_st[3])) + " of the " + String(n_twins) + " folded spectra need a near-frame link (the same frame alone folds "
+                    + String(twin_st[3]) + "); " + String(twin_st[4]) + " clusters span more than the tolerance (chained)");
     if (post_fusion_cap_)
       writeLogInfo_("[recap] assembly:post_fusion_cap: " + String(recap[0]) + " of " + String(recap[3]) + " spectra re-capped to " + String(max_frags)
                     + " peaks after the twin fold, " + String(recap[1]) + " peaks removed (largest spectrum before: " + String(recap[2]) + " peaks)");
```

## Docs diff `git diff 8e447bc e53b357 -- CHANGELOG.md README.md`

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index d2f6e0b..f3ae151 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -2,9 +2,11 @@
 
 ## v1.6.0 — 2026-10-01
 
-Four new defaults. On 43 public runs, peptides at 1 % FDR rise by 12.3 % with Sage and by 7.7 % with MSFragger over
-1.5.0. No run loses peptides on either engine, entrapment FDR and memory are unchanged, and wall time is within 3 %.
-Each default can be set back.
+Seven new defaults. With the first four, on 43 public runs, peptides at 1 % FDR rise by 12.3 % with Sage and by
+7.7 % with MSFragger over 1.5.0. No run loses peptides on either engine, entrapment FDR and memory are unchanged, and
+wall time is within 3 %. The last three measure a setting per run (the isotope-partner 1/K0 tolerance, the MS1 minimum
+trace length and the twin fold's frame tolerance); they were screened, not measured on the corpus. Each default can be
+set back.
 
 - **New defaults.**
 
@@ -14,12 +16,17 @@ Each default can be set back.
   | `-assembly:foreign_precursor_weight` | (new) | 0 | removes the residual isotope envelopes of co-isolated precursors from the spectrum |
   | `-assembly:fragment_fuse_ppm` | (new) | 25, `anchored` | fuses the pieces of one fragment ion into one peak before the cap |
   | `-charge:mono_profile_check` | false | v2 | checks the monoisotope against the summed MS1 intensity at the isotope positions |
+  | `-charge:iso_im_tolerance` | 0.05 | 0 (auto) | measures the isotope-partner 1/K0 tolerance per run |
+  | `-trace:min_length_sec` | 3 | −1 (auto) | sets the MS1 minimum trace length from the run's peak width |
+  | `-assembly:twin_rt_frames` | (new) | 0 (auto) | lets the twin fold join two spectra of one monoisotope from nearby MS1 frames |
 
   `-assembly:im_weight_sigma 0 -assembly:foreign_precursor_weight 1 -assembly:fragment_fuse_ppm 0
-  -charge:mono_profile_check false` gives the 1.5.0 spectra exactly (same semantic digest, checked on two runs). The
-  three options new to the defaults are now listed by `--help`, not only `--helphelp`.
-- **Measured effect.** The corpus is 43 public runs: PXD017703 (HeLa: 10/50/100 ng in the py3 and 25pc window
-  schemes, and Evosep 60/100/200 samples per day) and PXD047793 (TNBC tissue). Each run is extracted once
+  -charge:mono_profile_check false -charge:iso_im_tolerance 0.05 -trace:min_length_sec 3` gives the 1.5.0 spectra
+  exactly (same semantic digest, checked on two runs); the cross-frame twin fold needs v2, so these options switch it
+  off too. The options new to the defaults are now listed by `--help`, not only `--helphelp`.
+- **Measured effect** (the first four defaults; the three per-run settings below were screened, not measured on the
+  corpus). The corpus is 43 public runs: PXD017703 (HeLa: 10/50/100 ng in the py3 and 25pc window schemes, and Evosep
+  60/100/200 samples per day) and PXD047793 (TNBC tissue). Each run is extracted once
   with each release at 100 threads and searched with both engines at 1 % FDR, with a Sage entrapment search for the
   FDR check.
 
@@ -39,6 +46,10 @@ Each default can be set back.
     sat one isotope apart now resolve to one monoisotope and fold into twins.
   - Median peak RSS is 8.7 GB (1.5.0: 8.6 GB). Walls are compared through the reference implementation, which ran on
     the same node: the extraction takes 0.36 of its wall time (1.5.0: 0.35).
+  - The three per-run settings were screened together, with one extraction per run against the first four defaults
+    alone. The nine Evosep runs gain 12.7–27.6 % Sage and 13.6–29.6 % MSFragger peptides (60 SPD about 13 %, 100 and
+    200 SPD 22–30 %) with 37–54 % more spectra. HeLa 25pc at 10 ng gains 5.5 % and 1.6 %, TNBC 2.8 % and 1.8 %, and
+    HeLa py3 moves by 0.4 % or less. The Sage entrapment FDR changes by −0.27 to +0.13 pt.
 - **Foreign precursor envelopes** (`-assembly:foreign_precursor_weight`, `-assembly:foreign_precursor_ppm` 10,
   `-assembly:foreign_precursor_dim` 0.015, `-assembly:foreign_precursor_min_iso` 2). A diaPASEF window passes every
   precursor inside it, and the unfragmented envelope of a co-isolated precursor lands in the spectrum as intense
@@ -57,7 +68,9 @@ Each default can be set back.
   50 ppm) are fused after the same-bin merge and before `min_fragments` and the cap. A fused peak has:
   - the sum of its members' emitted intensities;
   - their intensity-weighted m/z;
-  - the best member's cap key.
+  - a cap key computed as for one fragment from the sum of the members' 1/K0-weighted apex intensities, with the
+    score (and, for `evidence`, the shared points) of the member with the best key. A fused ion ranks under the cap
+    as one ion of its total intensity, never below its best piece.
 
   A spectrum that fuses below `min_fragments` is not written. `anchored` takes the fragments strongest first, and each
   one not yet fused takes every unfused fragment within the tolerance of its own m/z. `linkage` joins m/z neighbours,
@@ -81,6 +94,67 @@ Each default can be set back.
   Logged as `[monocheck]`, stamped `spx:monocheck` (with the box and the percentile). `true` selects v1, which
   correlates each leftward step's elution profile with the seed's (`-charge:mono_profile_min_corr` 0.6,
   `-charge:mono_profile_max_dim` 0.015). v1 rejects many true steps; it is kept for comparison.
+- **Isotope-partner 1/K0 tolerance per run** (`-charge:iso_im_tolerance` 0 = auto, `-charge:iso_partner first|closest`).
+  The isotope walk took any MS1 trace within 0.05 1/K0 as an isotope partner. On dense short-gradient runs that is
+  many times the spread of real isotopes, so chance traces became partners and took other precursors' monoisotopes.
+  auto measures the tolerance before the walk:
+  - a stride sample of the MS1 traces (at most 200,000) is probed at each charge's +1 isotope position, in the walk's
+    m/z and retention-time window, and at two control positions 50 ppm either side, where no isotope can sit;
+  - at each position the nearest trace's 1/K0 gap is kept;
+  - the tolerance is the one that admits the most isotope-position traces net of twice the control traces (true
+    partners admitted minus chance partners admitted), on a 0.001 grid clamped to [0.01, 0.05].
+
+  It measures 0.010 on the four Evosep HeLa runs screened, 0.012 on TNBC, 0.019 on HeLa py3 at 100 ng, 0.027 on HeLa
+  25pc at 10 ng and 0.05 on HeLa py3 at 10 ng (that run's output is unchanged). In a screen (one extraction per run,
+  not the corpus), the Evosep runs gain 5.0–6.7 % Sage and 4.0–6.4 % MSFragger peptides with 6–8 % more spectra;
+  the other runs move between −0.4 % and +1.9 % on either engine, at the same wall time and memory. A value above 0
+  fixes the tolerance; 0.05 is the 1.5.0 behaviour. Logged as `[isotol]`, stamped `spx:iso_im_tolerance` (the
+  measured value and the partner rule). `-charge:iso_partner closest` takes the candidate closest to the seed in apex
+  RT and 1/K0 (each scaled by its tolerance) instead of the first in m/z order. It is off by default: in the same
+  screen it lost 1.6 and 5.0 % MSFragger peptides on the two 10 ng HeLa runs and wrote 14–15 % more spectra on Evosep
+  for about the same peptides.
+- **MS1 minimum trace length per run** (`-trace:min_length_sec` −1 = auto, `-trace:min_length_fwhm` 0.4). The fixed
+  3 s minimum needed 5 MS1 points at a 0.95-s cycle but 2 at a 3.5-s cycle, so short gradients lost their short,
+  faint precursors. auto first measures the run's peak width. It traces a fixed sample of the MS1 map like the run but
+  with no minimum length: every peak in 1-Th m/z slices, one every 25 Th. The minimum is 0.4 × the median FWHM of the
+  brightest tenth of those traces, and at least half an MS1 cycle, so a trace always needs 2 MS1 points. Fewer than
+  100 measurable traces fall back to 3 s. The run's peak width is about 2 MS1 cycles on every scheme screened, so auto
+  asks for 2 points everywhere (0.64–0.84 s on Evosep, 1.5–1.6 s on HeLa 25pc and TNBC, 2.6–2.8 s on HeLa py3,
+  whose output is unchanged). In a screen (one extraction per run, not the corpus), the four Evosep runs gain
+  7.0–15.8 % Sage and 7.1–17.9 % MSFragger peptides with 30–45 % more spectra; HeLa 25pc at 10 ng gains 5.1 % and
+  2.9 %, TNBC 1.4 % and 0.6 %. Logged as `[minlen]` (cycle, FWHM median, p10 and p90 in seconds and cycles, the
+  minimum and the points it implies), stamped `spx:ms1_min_length`. Any value ≥ 0 fixes the minimum as before
+  (`3` = 1.5.0, `0` = no filter).
+- **Twin fold across nearby frames** (`-assembly:twin_rt_frames` 0 = auto, `-assembly:twin_rt_match ext`). v2's
+  extension can put a monoisotope on a trace that is another precursor's monoisotope at another MS1 frame, so one ion
+  was written as two spectra that the same-frame fold could not join. The fold now also joins such a pair. Besides the
+  fold's charge and 1/K0 tests, the two must meet four conditions:
+  - their precursor m/z lie in one flight-time bin (within 0.05 ppm);
+  - the monoisotope of at least one of them was placed by the extension;
+  - their apexes are at most n MS1 cycles apart, with n the run's median MS1 peak width in cycles (2 on the public runs);
+  - they lie in one retention-time cell, so the output does not depend on the tiling or the thread count.
+
+  The survivor rule and the fusion are the fold's. Across frames, pairs of one charge and 1/K0 lie either within
+  0.01 ppm (one bin) or 0.3 ppm and more apart (distinct traces). Screened on top of the other two per-run settings
+  (one extraction per run), the fold removes 0.7–2.4 % of the spectra and moves peptides by −0.5 to +0.4 % on either
+  engine. Screened without them, one Evosep 200 SPD run lost 1.7 % with MSFragger; with them, that run lost 0.1 %.
+  The corpus numbers above predate it. `bin` (any one-bin pair across frames) and `ppm` (the
+  fold's 20 ppm) are options; both lost peptides in the screen. Without v2 nothing folds across frames, so the 1.5.0
+  options above still give the 1.5.0 spectra. `-1` restores the same-frame fold. Logged as `[twins]` (pairs joined at
+  one frame and across frames, pairs left apart at a cell edge), stamped in `spx:twin_merge`.
+- **Speed and memory.** The parallel structure changed, the output did not: the same semantic digest as without these
+  changes, at 16 and 100 threads and with one or two cells per tile.
+  - The retention-time tiles are pipelined. Up to two tiles have windows in flight; the next tile is read, and the
+    finished one sorted, folded and written, while the windows run. `DIASPEXTRACT_PIPE_TILES=1` restores one tile at
+    a time.
+  - The serial stages of a heavy window run as bounded tasks.
+  - The MS1 conversion and sorts and the precursor-inference batches run in parallel.
+
+  Measured before the per-run defaults, with two or three runs per build on one node: HeLa 25pc at 10 ng takes 44–48 %
+  less wall time at 32 to 192 threads, TNBC 36 % less at 100 threads. On the 1.6.0 defaults (one run per build, back
+  to back on one node, 100 threads): HeLa 25pc 132 → 73 s, TNBC 583 → 416 s, HeLa py3 at 10 ng 24 → 18 s, Evosep
+  200 SPD 14 → 12 s. Peak memory rises with the second tile in flight: TNBC from 22 to 29 GB, HeLa 25pc from 6.3 to
+  7.2 GB, and with `-tile:cells_per_tile 2` TNBC needs 44 GB.
 - **New options, off by default:**
   - `-assembly:frag_intensity apex|core|sum` (with `-assembly:frag_core_frames` 3) sets the amplitude written for a
     fragment. The default is the trace's apex. `core` sums the frames centred on the precursor's apex, and `sum` sums
@@ -92,20 +166,21 @@ Each default can be set back.
   - `-assembly:post_fusion_cap` re-applies `max_fragments` after the twin fold. The fold unions the members' capped
     fragment lists. Every peak carries its cap key through the merge, the fusion and the fold. Stamped
     `spx:post_fusion_cap`.
-- **Header.** A default run now carries 27 `spx:` stamps: `spx:monocheck`, `spx:foreign` and `spx:fragment_fuse` are
-  added to the 24 that are always written.
+- **Header.** A default run now carries 29 `spx:` stamps: `spx:monocheck`, `spx:foreign`, `spx:fragment_fuse`,
+  `spx:ms1_min_length` and `spx:iso_im_tolerance` are added to the 24 that are always written.
 - `-assembly:frag_core_frames` must be odd only with `-assembly:frag_intensity core`, the only mode that uses it.
 - An exception inside the parallel twin fold or the post-fusion cap now ends the run with an error message, not an
   abort. An allocation failure is one example.
 - **Known limitations.**
   - **Box narrower than the walk.** The v2 box is at most 0.03 1/K0, but the count walk accepts isotope partners up to
-    `-charge:iso_im_tolerance` (0.05) away. A walk whose own partner lies outside the box sees an empty position, which
-    counts against the step. The monoisotope can then move one or more isotopes right of the true one (two for one
-    empty position inside the walk, with `iterate`), mainly on runs with wide isotope 1/K0 scatter.
-  - **Duplicate monoisotope after the extension.** v2's extension can put a monoisotope on a trace that is another
-    precursor's monoisotope. The twin fold joins the two spectra only when they come from the same MS1 frame.
-  - **Fusion and the cap.** A fused peak is ranked under the cap by its best piece's key, not by its summed
-    intensity. Fusion also sums pieces whose elution does not overlap, unlike the same-bin merge.
+    `-charge:iso_im_tolerance` away (auto: 0.01–0.05 per run). A walk whose own partner lies outside the box sees an
+    empty position, which counts against the step. The monoisotope can then move one or more isotopes right of the
+    true one (two for one empty position inside the walk, with `iterate`), mainly on runs with wide isotope 1/K0
+    scatter.
+  - **Duplicate monoisotope after the extension, the rest.** The fold joins the extension's pair only within its
+    1/K0 tolerance (0.005) and the run's frame tolerance. A pair farther apart, or one that straddles a retention-time
+    cell edge, is still written as two spectra.
+  - **Fusion and elution.** Fusion sums pieces whose elution does not overlap, unlike the same-bin merge.
   - **Fusion and twins.** Fusion is not reconciled across twins, so after the fold's 10-ppm merge one ion can still
     appear as two peaks a little over 10 ppm apart.
   - **Window edges.** Foreign-envelope removal considers only precursors whose monoisotope lies in the window. A
diff --git a/README.md b/README.md
index 0bd6d38..293c1e9 100644
--- a/README.md
+++ b/README.md
@@ -62,7 +62,8 @@ patched OpenMS source tree but lives outside it. Earlier releases were named spe
    default, `anchored`; 0 = off) fuses the pieces of one fragment ion that the mobility picker split over neighbouring
    flight-time bins, peaks within that many ppm, into one peak with their summed intensity, so the ion takes one slot
    under the cap. A spectrum with at least 3 fragments left is written: its fragments ranked by evidence —
-   max(r, 0) × ln(1 + intensity) × (1 + shared points), a fused peak by its best piece's key — and the top 500 kept,
+   max(r, 0) × ln(1 + intensity) × (1 + shared points), a fused peak by the same key over its summed apex intensities
+   (r and shared points of its best piece) — and the top 500 kept,
    with a synthetic precursor (apex m/z, charge, retention time, 1/K0). Spectra are sorted per tile, a precursor
    claimed twice is folded into one spectrum that carries the union of the members' fragment lists
    (`-assembly:twin_im_tolerance`; with `-assembly:post_fusion_cap` a folded spectrum is cut back to `max_fragments` by
@@ -89,8 +90,10 @@ so search it as written.
 
 Memory, not CPU, decides whether a run fits a machine. The window loop therefore runs **tile by tile**: the run is cut
 into fixed 600-s retention-time cells at MS1 frame times, each tile (one cell by default) is read, traced, scored,
-sorted and written before the next one starts, and the fragments that straddle a cut are carried over. Tiling
-bounds the fragment working set; the MS1 traces and precursors of the whole run stay resident throughout. Within a
+sorted and written, and the fragments that straddle a cut are carried over. Since 1.6.0 the tiles are pipelined: up
+to two tiles have windows in flight, the next tile is read and the finished one sorted, folded and written while the
+windows run, with the same output as one tile at a time (`DIASPEXTRACT_PIPE_TILES=1` restores that, at less memory).
+Tiling bounds the fragment working set; the MS1 traces and precursors of the whole run stay resident throughout. Within a
 tile, isolation windows are admitted while they fit in 75 % of the machine's free RAM, so the run adapts to
 neighbours on a shared machine; one window is always admitted whatever the memory says, so a single oversized window cannot deadlock the run. Between tiles the allocator's free pages are returned to the OS.
 
@@ -181,12 +184,13 @@ procedure cannot stratify by charge, filter the search results per precursor cha
 charge, gate, assembly and denoising options shape the spectra by definition; in the memory and concurrency table,
 only the options marked **changes output** move the spectrum list, the others cost or save time and memory.
 
-**Which option for what.** Memory: `-tile:cells_per_tile` (1 is the smallest footprint), `-perf:max_concurrent_windows`
-and `-perf:mem_fraction`; avoid `.mzpeak` output and `-trace:detector openms` on a small machine, both process the
+**Which option for what.** Memory: `-tile:cells_per_tile` (1 is the smallest footprint), `-perf:max_concurrent_windows`,
+`-perf:mem_fraction` and `DIASPEXTRACT_PIPE_TILES=1` (one tile at a time); avoid `.mzpeak` output and `-trace:detector openms` on a small machine, both process the
 whole run at once. Time: `-threads`, and `-perf:malloc_trim false` when memory is not the constraint. Sensitivity:
 `-perf:stream_load false` on a machine with the memory for it, and trying `-trace:detector openms` on your own data.
 Charge and FDR: `-charge:min_charge`. The spectra of 1.5.0: `-assembly:im_weight_sigma 0
--assembly:foreign_precursor_weight 1 -assembly:fragment_fuse_ppm 0 -charge:mono_profile_check false`.
+-assembly:foreign_precursor_weight 1 -assembly:fragment_fuse_ppm 0 -charge:mono_profile_check false
+-charge:iso_im_tolerance 0.05 -trace:min_length_sec 3`.
 
 **Input and output**
 
@@ -221,7 +225,8 @@ Charge and FDR: `-charge:min_charge`. The spectra of 1.5.0: `-assembly:im_weight
 | `-trace:mass_error_ppm` | 15 | m/z tolerance for trace extension |
 | `-trace:noise_threshold_int` | 100 | MS1 noise intensity threshold |
 | `-trace:ms2_noise_threshold_int` | 10 | MS2 noise intensity threshold |
-| `-trace:min_length_sec` | 3 | minimum MS1 trace length |
+| `-trace:min_length_sec` | −1 = auto | minimum MS1 trace length in seconds (last minus first point). Auto: `-trace:min_length_fwhm` × the run's median MS1 peak FWHM, measured on a fixed sample of its MS1 traces (1-Th m/z slices every 25 Th, traced with no minimum), at least half an MS1 cycle, so a trace needs 2 MS1 points; logged as `[minlen]`, stamped `spx:ms1_min_length`. 0 = no length filter; 3 = the 1.5.0 value. **Changes output** |
+| `-trace:min_length_fwhm` | 0.4 | auto minimum MS1 trace length as a fraction of the run's median MS1 peak FWHM |
 | `-trace:ms2_min_length_sec` | 0 | minimum MS2 trace length; 0 = no length filter |
 | `-trace:ms1_chrom_peak_snr`, `-trace:ms2_chrom_peak_snr` | 3, 1 | apex threshold as a multiple of the noise threshold, MS1 and MS2 |
 | `-trace:ms1_split_valleys`, `-trace:ms2_split_valleys` | 7, 7 | split traces at chromatographic valleys, value = expected peak FWHM in seconds; 0 = off |
@@ -241,10 +246,10 @@ Charge and FDR: `-charge:min_charge`. The spectra of 1.5.0: `-assembly:im_weight
 | `-charge:scoring` | count | monoisotope and charge from the isotope partner count (`count`, ties to the lower charge) or from averagine cosine × co-elution (`envelope`) |
 | `-charge:im_charge_veto` | true | fit the run's 2+ and 3+ mobility trend lines from its confident envelopes; a z = 1 call on the 2+ line is re-called 2+, one on the 3+ line loses its charge |
 | `-charge:im_veto_band` | 2.5 | half-width of that band in MAD-sigma of the fit residuals |
-| `-charge:iso_im_tolerance` | 0.05 | 1/K0 tolerance for isotope partners |
+| `-charge:iso_im_tolerance`, `-charge:iso_partner` | 0 (auto), first | 1/K0 tolerance for isotope partners. 0 (auto, since 1.6.0) measures it per run before the isotope walk: a stride sample of the MS1 traces is probed at each charge's +1 isotope position and at two control positions 50 ppm either side, where no isotope can sit, and the tolerance is the one that admits the most isotope-position traces net of twice the control traces (true partners minus chance partners), on a 0.001 grid clamped to [0.01, 0.05]. Dense short-gradient runs get about 0.01, sparse low-load runs up to 0.05; a value > 0 fixes it (0.05 = 1.5.0). Logged as `[isotol]`, stamped `spx:iso_im_tolerance`. `iso_partner` picks the candidate inside the partner box: the first in m/z order (`first`, as in 1.5.0) or the one closest to the seed in apex RT and 1/K0, each scaled by its tolerance (`closest`; screened, lost MSFragger peptides on 10 ng runs, not recommended); **changes output** |
 | `-charge:mono_averagine_guard`, `-charge:mono_averagine_select` | 0, off | averagine-based corrections of the monoisotope; off by default, neither improves identifications |
 | `-charge:mono_profile_check`, `-charge:mono_profile_min_corr`, `-charge:mono_profile_max_dim` | v2 (false = off), 0.6, 0.015 | `true` checks each leftward step of the count walk for the winning charge: the lighter trace becomes the monoisotope only if its MS1 profile correlates with the seed's (Pearson ≥ min_corr; fewer than 3 shared frames pass unchecked) and its 1/K0 is within max_dim of the seed's; the walk stops at the first failure and the rejected trace stays unclaimed. Charge and envelope size are unchanged. `v2` (the default since 1.6.0) is described in the next row. **Changes output** |
-| `-charge:mono_profile_check v2`, `-charge:mono_position_min_ratio`, `-charge:mono_position_im_box`, `-charge:mono_position_extend`, `-charge:mono_position_iterate` | –, 0.2, 0 (auto), 0.6, true | `v2` tests isotope positions, not the claimed partner: PS(k) sums the apex intensity of every MS1 trace, claimed or not, at the seed's isotope position k (partner m/z tolerance, `gate:delta_rt`, im_box 1/K0 of the seed). im_box 0 (auto) sizes the box from the run's own isotope scatter: 3.5 × the 90th percentile of the 1/K0 gap between the brightest tenth of the seeds and their nearest trace one isotope heavier, clamped to [0.01, 0.03] (0.018 and 0.022 on the 2019 HeLa py3 10 and 100 ng runs of PXD017703); a value > 0 fixes it. The walk itself accepts partners up to `iso_im_tolerance` (0.05) away, so a partner outside the box counts as an empty position. The walk's leftmost step j is rejected when PS(−j)/PS(−j+1) × λ < min_ratio (λ = max(0.1, 0.000594 × neutral mass); 0 = no test), and the monoisotope moves one isotope right; `iterate` (`true`) repeats the test on the new leftmost step while it fails, `false` tests one step only. If nothing was rejected and the walk ended on a miss, the next lighter position becomes the monoisotope (its most intense trace, not claimed) when its ratio is ≥ extend (0 = off). Each walk is judged at its precursor's final charge, after `charge:im_charge_veto` (a z=1 walk re-called 2+ is read at 2+ spacing). Claims, charge and envelope size are unchanged. The default since 1.6.0; **changes output** |
+| `-charge:mono_profile_check v2`, `-charge:mono_position_min_ratio`, `-charge:mono_position_im_box`, `-charge:mono_position_extend`, `-charge:mono_position_iterate` | –, 0.2, 0 (auto), 0.6, true | `v2` tests isotope positions, not the claimed partner: PS(k) sums the apex intensity of every MS1 trace, claimed or not, at the seed's isotope position k (partner m/z tolerance, `gate:delta_rt`, im_box 1/K0 of the seed). im_box 0 (auto) sizes the box from the run's own isotope scatter: 3.5 × the 90th percentile of the 1/K0 gap between the brightest tenth of the seeds and their nearest trace one isotope heavier, clamped to [0.01, 0.03] (0.018 and 0.022 on the 2019 HeLa py3 10 and 100 ng runs of PXD017703); a value > 0 fixes it. The walk itself accepts partners up to `iso_im_tolerance` away (auto, 0.01–0.05 per run), so a partner outside the box counts as an empty position. The walk's leftmost step j is rejected when PS(−j)/PS(−j+1) × λ < min_ratio (λ = max(0.1, 0.000594 × neutral mass); 0 = no test), and the monoisotope moves one isotope right; `iterate` (`true`) repeats the test on the new leftmost step while it fails, `false` tests one step only. If nothing was rejected and the walk ended on a miss, the next lighter position becomes the monoisotope (its most intense trace, not claimed) when its ratio is ≥ extend (0 = off). Each walk is judged at its precursor's final charge, after `charge:im_charge_veto` (a z=1 walk re-called 2+ is read at 2+ spacing). Claims, charge and envelope size are unchanged. The default since 1.6.0; **changes output** |
 
 **Co-elution gate (`gate:`)**
 
@@ -287,7 +292,7 @@ Charge and FDR: `-charge:min_charge`. The spectra of 1.5.0: `-assembly:im_weight
 | `-assembly:foreign_precursor_dim` | 0.015 | the largest 1/K0 distance between this precursor and a foreign one |
 | `-assembly:foreign_precursor_min_iso` | 2 | how many of a foreign envelope's four positions (mono…M+3) must carry a fragment before its fragments are attenuated (1–4) |
 | `-assembly:merge_same_bin` | true | merge a spectrum's fragments of one flight-time bin (one exact m/z with the OpenMS detector) into one peak before `max_fragments`: members overlapping the strongest in retention time are summed, retention-time-disjoint pieces dropped. Two peaks at one m/z stall the fragment matching of OpenMS-based search engines. **Changes output** |
-| `-assembly:fragment_fuse_ppm` | 25 (0 = off) | fuse a spectrum's fragments within this many ppm (at most 50) into one peak, after the same-bin merge and before `min_fragments` and `max_fragments`. The mobility picker keeps 1–2 flight-time bins of a fragment ion that spans 4–7, so one ion becomes several peaks 5–20 ppm apart, each with its own apex intensity. A fused peak takes the sum of its members' emitted intensities (whatever their retention-time overlap, unlike the same-bin merge), their intensity-weighted m/z and their best `cap_rank` key (the best piece's, not one computed from the sum), so the ion takes one cap slot and the freed slots refill; a spectrum that fuses below `min_fragments` is not written. A `[fuse]` log line counts the fragments in, the peaks out, the groups fused and their mean size; stamped `spx:fragment_fuse`. 25 ppm `anchored` is the default since 1.6.0; **changes output** |
+| `-assembly:fragment_fuse_ppm` | 25 (0 = off) | fuse a spectrum's fragments within this many ppm (at most 50) into one peak, after the same-bin merge and before `min_fragments` and `max_fragments`. The mobility picker keeps 1–2 flight-time bins of a fragment ion that spans 4–7, so one ion becomes several peaks 5–20 ppm apart, each with its own apex intensity. A fused peak takes the sum of its members' emitted intensities (whatever their retention-time overlap, unlike the same-bin merge), their intensity-weighted m/z and a `cap_rank` key computed like an unfused fragment's from the sum of their 1/K0-weighted apex intensities, with the score (and, under `evidence`, the shared points) of the best-keyed piece, so a fused ion ranks as one ion of its total intensity, never below its best piece; it takes one cap slot and the freed slots refill; a spectrum that fuses below `min_fragments` is not written. A `[fuse]` log line counts the fragments in, the peaks out, the groups fused and their mean size; stamped `spx:fragment_fuse`. 25 ppm `anchored` is the default since 1.6.0; **changes output** |
 | `-assembly:fragment_fuse_mode` | anchored | how `fragment_fuse_ppm` groups: `anchored` takes the fragments strongest first (ties: lower m/z), and each one not yet fused takes every unfused fragment within the tolerance of its own m/z; `linkage` walks them in m/z order and joins a fragment to the previous one's group when it lies within the tolerance of it and within twice the tolerance of the group's first member (single linkage with a capped span) |
 | `-assembly:max_fragments` | 500 | keep at most this many, top-ranked; keep it at or above `min_fragments`. Applied before the twin fold below, so a folded spectrum can hold more (unless `post_fusion_cap`) |
 | `-assembly:cap_rank` | evidence | which fragments survive `max_fragments`: `evidence` ranks by max(r, 0) × ln(1 + I) × (1 + shared points), so long correlated support outranks an intense one-frame coincidence; `corr_inten` by gate score × intensity (the 1.4 key); `umpire` by max(r, 0)² × ln(1 + I). r is the raw co-elution score before shrinkage (Pearson, or the `logoverlap` score) |
@@ -297,7 +302,8 @@ Charge and FDR: `-charge:min_charge`. The spectra of 1.5.0: `-assembly:im_weight
 | `-assembly:frag_core_frames` | 3 | `frag_intensity core`: the number of window frames (odd, 1–15) |
 | `-assembly:require_isotope_support` | true | drop precursor hypotheses without an isotope partner; `false` doubles the spectra, runs about 7× slower and identifies fewer peptides |
 | `-assembly:default_charge` | 2 | charge given to a precursor left without a charge call (only matters when guessed precursors are kept) |
-| `-assembly:twin_im_tolerance` | 0.005 | fold spectra that claim one precursor twice — same MS1 frame, same charge, precursor m/z within 20 ppm, 1/K0 within this tolerance — into one, which takes the union of the cluster's fragments, peaks within 10 ppm fused (so it can exceed `max_fragments`); −1 = off, the spectra of 1.3 (0 still folds twins of identical 1/K0). On a 2-hour HeLa run (PXD029836): 24 % fewer spectra for 0.2 % of the peptides on both engines, entrapment FDR 0.98 % with the fold against 0.98 % without |
+| `-assembly:twin_im_tolerance` | 0.005 | fold spectra that claim one precursor twice — same MS1 frame (or nearby frames, next row), same charge, precursor m/z within 20 ppm, 1/K0 within this tolerance — into one, which takes the union of the cluster's fragments, peaks within 10 ppm fused (so it can exceed `max_fragments`); −1 = off, the spectra of 1.3 (0 still folds twins of identical 1/K0). On a 2-hour HeLa run (PXD029836): 24 % fewer spectra for 0.2 % of the peptides on both engines, entrapment FDR 0.98 % with the fold against 0.98 % without |
+| `-assembly:twin_rt_frames`, `-assembly:twin_rt_match` | 0 (auto), ext | let the twin fold also join two spectra of one monoisotope from nearby MS1 frames. The v2 check's extension can move a monoisotope onto another precursor's monoisotope trace at another frame, and the same-frame fold leaves both spectra. A pair folds across frames with the same charge, 1/K0 within `twin_im_tolerance`, apexes at most n MS1 cycles apart (\|ΔRT\| ≤ (n + 0.5) × the cycle), in one retention-time cell (a pair across a cell edge stays two spectra), precursor m/z in one flight-time bin (within 0.05 ppm) and, with `ext`, the monoisotope of at least one of the two placed by the extension (nothing folds across frames without v2). `bin` folds any one-bin pair across frames, `ppm` any pair within the fold's 20 ppm; both cost peptides in a screen. Across frames, pairs of one charge and 1/K0 lie either within 0.01 ppm (one bin) or 0.3 ppm and more apart (distinct traces). The survivor rule and the fusion are the fold's. 0 = auto: the run's median MS1 peak width (FWHM of the precursors' seed traces with at least 3 points) in MS1 cycles, rounded, at least 1; −1 = the same frame only (the fold before 1.6.0). A `[twins]` log line counts the pairs joined at one frame and across frames, the pairs left apart at a cell edge and the spectra folded only through a cross-frame link; the relation is stamped in `spx:twin_merge`. **Changes output** |
 | `-assembly:post_fusion_cap` | false | re-apply `max_fragments` after the twin fold: every peak carries its `cap_rank` key (a 32-bit float) through the same-bin merge and the fold, where a fused peak keeps its members' best key, and a spectrum over the cap keeps its top-ranked peaks (ties: higher intensity, then lower m/z). A `[recap]` log line counts the spectra cut and the peaks removed; stamped `spx:post_fusion_cap`. Experimental. **Changes output** |
 
 **MS1 denoising (`dnoise:`)** — a port of dnoise v0.1.0's MS1 path (Garrett, Diedrich & Yates III,
@@ -319,7 +325,7 @@ lost precursor can be attributed to a stage.
 
 Every emitted spectrum is MS2 with a synthetic precursor: `selected ion m/z` (the apex m/z of the monoisotopic
 trace), `charge state`, the precursor's retention time and 1/K0, and the isolation window it was taken from. The run
-header carries `spx:` userParams that make any file attributable to the configuration that produced it, twenty-seven
+header carries `spx:` userParams that make any file attributable to the configuration that produced it, twenty-nine
 at the defaults. Twenty-four are always written: the detector and calibration (`spx:detector`, `spx:mz_calibration`,
 `spx:require_isotope_support`, `spx:corr_power`, `spx:pearson_G` (the correlation support, always `frames`),
 `spx:im_weight_sigma`), the twin fold (`spx:twin_merge`: its relation and tolerance, or `off`), the co-elution gate
@@ -327,10 +333,12 @@ at the defaults. Twenty-four are always written: the detector and calibration (`
 cap ranking (`spx:cap_rank`), the same-bin merges (`spx:same_bin_merge`), MS1 denoising (`spx:dnoise_ms1`,
 `spx:dnoise_ms1_params`, `spx:dnoise_ms1_points`), the cell grid and tiling (`spx:tile_rt_sec`,
 `spx:tile_cells_per_tile`, `spx:tiles`, `spx:tile_boundaries`, `spx:tile_source`), the band edges (`spx:band_edges`)
-and the frozen frame table (`spx:frame_table`). The others are written when their option is on, three of them at the
+and the frozen frame table (`spx:frame_table`). The others are written when their option is on, five of them at the
 defaults: `spx:monocheck` with `-charge:mono_profile_check true` or `v2` (its settings and how many monoisotopes
 moved), `spx:foreign` when `-assembly:foreign_precursor_weight` is below 1, `spx:fragment_fuse` when
-`-assembly:fragment_fuse_ppm` is above 0; and, off by default, `spx:anchor` (`-gate:anchor_rescue true`),
+`-assembly:fragment_fuse_ppm` is above 0, `spx:ms1_min_length` when `-trace:min_length_sec` is auto (the minimum it
+chose and the peak width it came from), `spx:iso_im_tolerance` when `-charge:iso_im_tolerance` is 0 (auto: the
+measured value) or `-charge:iso_partner` is `closest`; and, off by default, `spx:anchor` (`-gate:anchor_rescue true`),
 `spx:fragint` (`-assembly:frag_intensity` not `apex`) and `spx:post_fusion_cap` (`-assembly:post_fusion_cap true`).
 `spx:mz_calibration` starts with `tdf_table_modeltype1` (mzPeak input appends how the table was recovered), or is
 `bruker_sdk`, `legacy_chord_APPROXIMATE`, `mzpeak_two_point_transform` (an mzPeak archive read through its approximate
```

## Test diff `git diff e53b357 b592804` (test-only commit)

```diff
diff --git a/test/test_diaspextract.py b/test/test_diaspextract.py
index 4d6a7e8..abf9f8c 100644
--- a/test/test_diaspextract.py
+++ b/test/test_diaspextract.py
@@ -441,6 +441,8 @@ def main():
     #      twin: the fold must not touch it. With groups=(1, 9) the same m/z window is acquired in two window groups,
     #      so each precursor is assembled twice -- twins on RT, m/z, charge and 1/K0 -- and the fold must fire; the
     #      logged count must be exactly the spectra removed, and the header must name the setting either way.
+    #      Since 1.6.0 the default fold also joins nearby MS1 frames (assembly:twin_rt_frames 0 = auto) and the header
+    #      says so; assembly:twin_rt_frames -1 restores the same-frame fold and its 1.5.0 header text.
     def c12b():
         r = run(binary, inp, os.path.join(work, "selftest_twins.mzML"), extra=("-diag:selftest_twins",))
         assert "[twins] selftest passed" in (r.stdout + r.stderr), \
@@ -449,10 +451,15 @@ def main():
         folded = lambda r: int(re.search(r"\[twins\] (\d+) spectra folded into a twin", r.stdout).group(1))
         stamp = lambda f: re.search(rb'name="spx:twin_merge"[^>]*value="([^"]*)"', open(f, "rb").read(40000))
         on, off = os.path.join(work, "twins_on.mzML"), os.path.join(work, "twins_off.mzML")
+        same = os.path.join(work, "twins_same_frame.mzML")
         r_on = run(binary, inp, on)
         run(binary, inp, off, extra=("-assembly:twin_im_tolerance", "-1"))
-        assert folded(r_on) == 0 and digest(on) == digest(off), "the fold changed a fixture that has no twin"
-        assert stamp(on) and stamp(on).group(1).startswith(b"same frame") and stamp(off) and stamp(off).group(1) == b"off", \
+        r_same = run(binary, inp, same, extra=("-assembly:twin_rt_frames", "-1"))
+        assert folded(r_on) == 0 and folded(r_same) == 0 and digest(on) == digest(off) == digest(same), \
+            "the fold changed a fixture that has no twin"
+        assert stamp(on) and stamp(on).group(1).startswith(b"MS1 frames up to ") and b"(auto: " in stamp(on).group(1) \
+            and stamp(same) and stamp(same).group(1).startswith(b"same frame") \
+            and stamp(off) and stamp(off).group(1) == b"off", \
             "the header does not record the twin setting"
         inp_g = os.path.join(work, "twins_groups.mzML")
         synth(inp_g, groups=(1, 9))
```

(end of brief -- everything above is inline; answer in the output format given before the commit list)
