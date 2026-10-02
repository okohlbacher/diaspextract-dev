# Pre-release code review brief: DIAspeXtract 1.6.0 (release candidate rc-b)

**Review only -- do not modify, create or delete any file.** Everything you need is inline below. If you are Kimi or
Vibe: do not run any shell command; your working directory is a throwaway checkout of commit b2185db, and you may open
`src/diaspextract.cpp` there with a file-reading tool for context beyond the excerpts. If you are Codex: your working
directory is a read-only checkout of b2185db inside the git repository; read-only git commands (`git diff
b65c8dd..b2185db`, `git show`, `git log`) and grep are fine.

## Scope (frozen)

- Commit under review: **b2185db** (branch `tune/rc-b`). Last release: **b65c8dd** = DIAspeXtract 1.5.0.
- Diff under review: `git diff b65c8dd..b2185db`, 3 files, 40 commits:

```
 CHANGELOG.md         | 217 ++++++++++++
 README.md            |  51 ++-
 src/diaspextract.cpp | 960 +++++++++++++++++++++++++++++++++++++++++++++++++--
 3 files changed, 1196 insertions(+), 32 deletions(-)
```

- No test files changed. The only new test is the `-diag:selftest_twins` extension inside src (keyed fold + post-fusion cap).
- Line numbers: cite `src/diaspextract.cpp` line numbers **at b2185db** where you can (the file in your working
  directory); otherwise cite the diff hunk header in Section B.

## What the tool is

DIAspeXtract is a TOPP tool (OpenMS, C++17, OpenMP) that turns Bruker diaPASEF DIA runs into pseudo-MS/MS spectra for
DDA search engines. MS1 mass traces are walked into isotope envelopes (`inferPrecursors_`: the count walk assigns the
monoisotope by walking up to 5 isotope steps to lighter m/z, break on first miss; z by partner count; a greedy
seed-intensity-ordered claim loop, evaluated speculatively in parallel batches and committed serially). An
ion-mobility veto then re-calls z=1 calls that sit on the run's 2+ mobility line as 2+ (or unsets those on the 3+
line). Precursors are sorted by mono m/z and assigned to isolation windows by mono m/z. Per isolation window and
600-s RT cell (tiles), fragment traces are gated by co-elution with each precursor (`assembleOne_`); survivors are
ranked by a cap key (`assembly:cap_rank evidence` = max(r,0) x ln(1+I) x (1+overlap)) and the top
`assembly:max_fragments` (500) are kept. Spectra are canonically sorted per tile, then twins (same MS1 frame, same
charge, precursor m/z within 20 ppm, 1/K0 within 0.005) are folded into one spectrum carrying the union of their
peaks (fused within 10 ppm, intensity = max), after the cap -- so a folded spectrum can exceed 500 peaks.

## What 1.6.0 changes

rc-b merges five tuning branches (all new options off by default on those branches) and then sets four defaults:

| option | 1.5.0 | rc-b default | what it does (author's claim -- attack it) |
|---|---|---|---|
| `assembly:im_weight_sigma` | 0 | 0.005 | multiply each fragment's intensity by exp(-dIM^2/2 sigma^2); feeds the cap key AND the emitted intensity (pre-existing code, new default) |
| `assembly:foreign_precursor_weight` | (new) | 0 | remove fragments lying on the residual isotope envelope of ANOTHER precursor co-isolated in the same window (apex within the gate RT window, 1/K0 within 0.015, >= 2 of its mono..M+3 positions matched at 10 ppm); own envelope (30 ppm) never touched; before the same-bin merge and the cap |
| `assembly:fragment_fuse_ppm` (+ `_mode anchored`) | (new) | 25, anchored | after the same-bin merge, before min_fragments and the cap: fuse a spectrum's fragments within 25 ppm into one peak (sum of emitted intensities, intensity-weighted m/z, max cap key). anchored = strongest first, each unfused fragment becomes an anchor taking every unfused fragment within tol of its own m/z |
| `charge:mono_profile_check` | (new) | v2 | after the IM veto, at the final charge: isotope-position sums PS(k) over every MS1 trace in a box (ppm, delta_rt, 1/K0 im_box, auto-sized from the run); reject the walk's leftmost step when PS(-j)/PS(-j+1) x lambda < 0.2 (iterate), or extend one isotope lighter when the walk ended on a miss and the ratio >= 0.6; only mono_mz changes |

Off by default and also in the diff (review them, lower priority): `assembly:frag_intensity core|sum`,
`gate:anchor_rescue`, `assembly:post_fusion_cap` (keyed twin fold + re-cap), `charge:mono_profile_check true` (v1).

Evidence summary (not under review, context only): on a 43-run public corpus (two search engines, entrapment FDR),
rc-b finds more peptides than 1.5.0 in every run (Sage +12.3 %, MSFragger +7.7 % overall), entrapment unchanged, wall
and RSS unchanged, 3.7 % fewer spectra (by design, from the monoisotope check).

## Invariants the code must keep (attack each)

1. **Default output changes only through the four default options.** With
   `-assembly:im_weight_sigma 0 -assembly:foreign_precursor_weight 1 -assembly:fragment_fuse_ppm 0 -charge:mono_profile_check false`
   the output must be byte-identical (spectrum digest) to 1.5.0. Every new code path must be a no-op then. (Measured:
   the reset reproduces the 1.5.0 digests on two runs.)
2. **Determinism:** the semantic digest must not depend on the thread count (16 vs 100), the tile grid (1 vs 2 cells
   per tile) or the node. Every sort needs a total order; floating-point sums must run in a fixed order; atomics may
   only feed log counters. (Measured: one digest across 16/100 threads, 1/2 cells per tile, two nodes.)
3. **No data race:** `assembleOne_` runs inside `#pragma omp taskloop` over precursors with shared read-only inputs and
   per-task `pdense`; `monoPositionPass_` and `capAfterFusion_` use `#pragma omp parallel for`.
4. **libgomp taskloop task-count cliff:** GOMP_taskloop silently runs a whole taskloop inline in the creating thread
   once team task_count + num_tasks > 64 x nthreads (grainsize does not bound it). No new task layer may push the
   count past that, and no new omp construct may be nested inside the assembly taskloop.
5. **Exceptions from tasks propagate:** an exception escaping an OpenMP task/parallel body terminates the process with
   no message; task bodies catch everything into `taskErr_` and the code after the loop rethrows. New parallel bodies
   must not let an exception escape (allocation included), or must be shown to be unable to throw.
6. **Docs agree with code:** every `register*Option_` default (including flags and the advanced/hidden bit), its help
   text, the README option tables/pipeline prose and the CHANGELOG must agree with the registered defaults.
7. **Public-export scrub:** src/, README.md and CHANGELOG.md are exported to a public repository. They must contain no
   private cohort labels (S08/S23/S26/S30/S33/S36), never name the comparison tool (write "the reference
   implementation"), no specimen IDs, no /Users/... paths, no AGXT/PH1/liver, and **no K562 results at all** (neither
   the Roest K562 set nor PXD041421), no references to docs/reviews/, harness/ or docs/benchmarks/ private content.
   Already found by grep (confirm, then look for what a word grep misses): "K562" in the compiled help strings of
   `assembly:im_weight_sigma` and `charge:mono_position_im_box` (also a run number "9905" there), "K562 9905" in the
   `monoPositionPass_` doc comment, K562 in the README rows for `fragment_fuse_ppm` and `mono_profile_check v2`, K562
   numbers and the comparison tool's name throughout the CHANGELOG "Unreleased (tuning 2026-09-29)" section (that
   section will be rewritten for 1.6.0 with public numbers; still list anything else in it that must not ship).

## Questions (numbered; answer each, briefly if it is fine)

**Fragment fusion (`fuseFragments_`, default 25 ppm anchored)**
1. Anchored grouping: members within tol of the anchor give a group span up to 2 x tol; fused peaks can still sit
   within tol of each other; ties in intensity/m/z. Is the grouping well defined and order-independent? Is the
   intensity-weighted m/z (weights = emitted intensities, which already include corr^2 and the IM weight) the right
   estimator, and is `sum` the right intensity when the same-bin merge sums only RT-overlapping members and the twin
   fold takes the max?
2. Interaction with the 500-peak cap: the fused peak's cap key is the MAX of its members' keys (the evidence key is
   r x ln(1+I) x (1+overlap) of ONE member), not recomputed from the summed intensity. Can that mis-rank fused peaks
   against unfused ones? `frag_bin`/`frag_span` are stale after fusion -- is anything reading them later?
3. Interaction with the twin fold (after the cap; 10 ppm; intensity = max): two twins carry the same ion fused at
   slightly different weighted m/z -- does the fold double count, split, or chain? Does fusion before the fold change
   how often a folded spectrum exceeds 500 peaks (the cap is not re-applied by default)?
4. Fusion runs before `min_fragments`: a spectrum can now drop below 3 and vanish. Intended? Any knock-on effect on
   other spectra (twin fold survivor choice, canonical order)?
5. Linkage mode (not default): check the condition `m - mp <= mp*tol && m - ms <= 2*ms*tol`.
6. Determinism and numerics of the fusion: sort keys, summation order, the `head` (lowest index) placement, `w <= i`
   in-place compaction of three parallel arrays.

**Monoisotope check v2 (`monoPositionPass_`, default)**
7. Units and formula: the PS box (ppm tolerance computed at the seed m/z, `delta_rt` on apex RTs, `v2_box` in 1/K0),
   lambda = max(0.1, 0.000594 x neutral mass), the direction of the ratio PS(-j)/PS(-j+1) x lambda against averagine.
8. Charge 1 and the veto re-read (`mul = pc.charge / v.z`, `nl = v.nl * mul`): the `leftMz` index mapping
   `v.left_mz[i/mul - 1]`, the two-position fallback condition `(j - 1) % mul != 0` and its lambda^2/2, the
   iterate=false walk-back loop (commit 20700ca), the extension `ratio(nl + 1)` at mul > 1 (a position the z=1 walk
   never tested), and `v.nl < 5` vs `nl`.
9. Empty positions and NaN: `ratio` returns 0 when the heavier position is empty in the box (mul == 1), which REJECTS
   the step. The walk's partners were found with `charge:iso_im_tolerance` 0.05, the box is 0.01-0.03, so a walk's
   own partner can fall outside the box. Is rejecting then correct? Can any value be NaN/inf (float sums, zero
   intensities, lambda), and what do the comparisons do with it?
10. Auto box: "brightest decile" = the first nz/10 walks in `pcs` order -- is `inferPrecursors_`'s output order really
    seed-intensity order (descending), and is it still that order at this point? p90 index, clamp, determinism of
    `nth_element` on a vector filled by a parallel loop.
11. Alignment of `v2in` with `precursors`: the record is pushed once per emitted precursor in the commit loop, then the
    adaptive-auto rule, the [det] digest and the veto run before `monoPositionPass_`; the sort by mono m/z and the
    erasures run after. Any path that breaks the alignment (or makes the Precondition throw)? Envelope scoring path?
12. v2 moves mono_mz BEFORE precursors are sorted by mono m/z and assigned to isolation windows (binary search on
    `prec_mz` per window) and before the isolation offsets `max(0, mono - win_lo)` are written. A mono moved right
    (rejection) or left (extension, onto an unclaimed trace) can change the window(s) the precursor is assembled in.
    Is that a correctness problem? Can the extension create a second precursor at the same mono (the unclaimed trace
    later seeds its own precursor) that the twin fold cannot fold (different seed RT)?
13. Speculative claim loop: `R.v2` is reset at the start of `evalSeed`; a stale (re-evaluated) seed recomputes it.
    Anything in v1 or v2 that reads state not covered by `R.deps` (v1 reads `xicCorr` of partners)?

**Foreign-precursor removal (default weight 0)**
14. Semantics of weight 0: removal with compaction of `frags, frag_scores, frag_bin, frag_span, resc` (not `frag_ai`);
    the cap-key update for 0 < w < 1 (`log1p` ratio for log keys, linear for corr_inten); own-ion protection at
    max(ppm, 30 ppm); the sibling/twin tests (`on_grid` both directions, |j| <= 3, mono within 0.01).
15. Candidate set: only precursors whose MONO lies in this window (`[plo, phi)`), so a co-isolated precursor whose mono
    lies just outside but whose M+1..M+3 lie inside is never a candidate. Is the index tile-invariant (built from the
    whole window list, not the tile's owned subset)? Self-skip `&f == &pc` -- is `pc` always a reference into
    `precursors`? Guessed precursors (charge defaulted) as candidates?
16. At weight 0 a fragment that is a genuine fragment of THIS precursor and happens to sit on a foreign envelope
    position is deleted. How likely is that on real data (two positions at 10 ppm within a 0.015 1/K0 / RT window)?

**IM weight default (`im_weight_sigma` 0.005)**
17. The weight feeds the cap key (`inten` inside ln(1+I)) and the emitted intensity: with sigma 0.005 and `gate:delta_im` 0.01, a
    fragment at the gate edge (dIM 0.01) gets weight exp(-2) = 0.135. Interactions with the foreign cap-key update (`frag_ai`), the anchor rescue and the
    fusion key. Any ranking pathology (ln(1+I) for I < 1, ties)?

**Threads, tasks, exceptions, performance**
18. Anything in the diff that can make the output depend on the thread count or the tile grid (parallel loops writing
    shared state, order-dependent reductions, atomics used for more than counters, unordered containers).
19. Taskloop cliff and nesting: does the diff add a task layer, a nested parallel region, or an omp construct inside
    the assembly taskloop? (`monoPositionPass_` runs at top level; `capAfterFusion_` and `mergeTwins_` in the tile loop.)
20. Exceptions: new throws (`Exception::Precondition` in `monoPositionPass_`, `InvalidParameter` for an even
    `frag_core_frames`) and allocations inside the new `#pragma omp parallel for` bodies (`capAfterFusion_`'s `idx`,
    the keyed fold's vectors) without try/catch -- std::terminate on bad_alloc?
21. Hot-path cost at 100 threads: per-assembly atomic adds on shared counter arrays (`fuseCount_`, `foreignCount_`,
    one cache line each), per-assembly sorts (`om` in fuse and foreign), the foreign candidate scan per precursor.

**Defaults, docs, reset**
22. For every new or changed option: registered default vs help text vs README table vs CHANGELOG, the advanced
    (hidden) bit on options that are now ON by default (`fragment_fuse_ppm`, `foreign_precursor_weight`,
    `mono_profile_check`), "Experimental" wording on defaults, numeric claims that disagree between help and README
    (e.g. the im_box examples), the README `min_fragments` row ("after the gate and the same-bin merge") now that
    fusion and foreign removal run before that check, and the README sentence "the header carries twenty-four `spx:`
    userParams" -- count the `spx:` keys a DEFAULT 1.6.0 run writes (the new stamps are conditional on the options).
23. Reset invariant (invariant 1): with the four options reset, is every changed line a no-op for the output? Look for
    changes outside guarded branches (`gstop`/`best_nl` bookkeeping, the `min_fragments` block, `n_resc`, the ledger
    byte counts, header stamps, the keyed/unkeyed twin fold).
24. Scrub (invariant 7): list every remaining violation in exported files beyond the known list above.

## How to answer

- One entry per finding: **id, severity (critical / high / medium / low / info), file:line, the claim, a concrete
  failing input or state, "would this bite on real data or is it theoretical", and a suggested fix.**
- Rank by severity: changes output or breaks an invariant > crash/terminate > performance > docs > cosmetic.
- If something is fine, say so in one line. Do not pad. Disagreeing with the author's claims is the point.

## Section B: `git diff b65c8dd..b2185db -- src` (complete)

```diff
diff --git a/src/diaspextract.cpp b/src/diaspextract.cpp
index 62958c4..1677f7c 100644
--- a/src/diaspextract.cpp
+++ b/src/diaspextract.cpp
@@ -214,6 +214,11 @@ namespace
   double im_weight_sigma_ = 0.0;     ///< [recall] Gaussian IM-proximity weight on emitted fragment intensity (0=off)
   double mono_guard_ = 0.0;          ///< [mono-guard] averagine slack on leftward isotope steps (0=off)
   bool mono_select_ = false;         ///< [mono-select] pick the mono by averagine fit over the isotope run
+  int mono_check_ = 0;               ///< [monocheck] charge:mono_profile_check: 0 false, 1 true (v1 profile + 1/K0 steps), 2 v2
+  double mono_check_min_corr_ = 0.6, mono_check_max_dim_ = 0.015;   ///< [monocheck] charge:mono_profile_min_corr, _max_dim
+  double mono_pos_min_ratio_ = 0.2, mono_pos_im_box_ = 0.0, mono_pos_extend_ = 0.6;   ///< [monocheck-v2] charge:mono_position_* (im_box 0 = auto)
+  bool mono_pos_iterate_ = true;     ///< [monocheck-v2] charge:mono_position_iterate
+  String mono_check_stamp_;          ///< [monocheck] the spx:monocheck run stamp, filled by inferPrecursors_
   bool var_support_ = false;         ///< [Q1] Pearson variance over union support, not full grid G (0-pad fix)
   bool short_conc_ = false;          ///< [short] gate:short_traces == "concentric": span test for traces too short for Pearson
   double short_center_tol_ = 0.5;    ///< [short] gate:short_center_tol, fraction of the precursor half-span
@@ -232,6 +237,20 @@ namespace
   int cap_rank_ = 0;                 ///< [cap] assembly:cap_rank: 0 corr_inten (score x intensity), 1 umpire (r^2 ln I), 2 evidence (r ln I (1+overlap))
   double im_slice_merge_ = 0.015;   ///< [merge] trace:im_slice_merge, 1/K0 link (group span <= 2x); negative = off
   bool merge_same_bin_ = true;       ///< [merge] assembly:merge_same_bin
+  int frag_int_ = 0;                 ///< [fragint] assembly:frag_intensity: 0 apex (legacy), 1 core, 2 sum
+  int frag_core_half_ = 1;           ///< [fragint] (assembly:frag_core_frames - 1) / 2
+  bool anchor_rescue_ = false;       ///< [anchor] gate:anchor_rescue: weak fragments of non-faint precursors judged against an anchor consensus
+  int anchor_min_count_ = 3;         ///< [anchor] gate:anchor_min_count
+  double anchor_min_corr_ = 0.8;     ///< [anchor] gate:anchor_min_corr
+  double anchor_rescue_corr_ = 0.7;  ///< [anchor] gate:anchor_rescue_corr
+  int anchor_max_rescued_ = 50;      ///< [anchor] gate:anchor_max_rescued
+  bool post_fusion_cap_ = false;     ///< [recap] assembly:post_fusion_cap: carry the cap key per peak, re-cap after the twin fold
+  double foreign_w_ = 1.0;           ///< [foreign] assembly:foreign_precursor_weight (1 = off, 0 removes)
+  double foreign_ppm_ = 10.0;        ///< [foreign] assembly:foreign_precursor_ppm
+  double foreign_dim_ = 0.015;       ///< [foreign] assembly:foreign_precursor_dim
+  int foreign_min_iso_ = 2;          ///< [foreign] assembly:foreign_precursor_min_iso
+  double fuse_ppm_ = 0.0;            ///< [fuse] assembly:fragment_fuse_ppm (0 = off)
+  bool fuse_linkage_ = false;        ///< [fuse] assembly:fragment_fuse_mode: false anchored, true linkage
 
   /// glibc arena accounting at a milestone: what the allocator holds in arenas vs mmapped blocks
   /// and how much of it is free-but-retained. RSS alone cannot tell live data from retained pages.
@@ -301,6 +320,24 @@ namespace
   /// [merge] [0] picked MS2 peaks merged away in toTof (one frame, one bin, 1/K0 within trace:im_slice_merge);
   /// [1] frames that had such a merge; [2] fragments merged away at assembly (one bin in one spectrum)
   inline std::array<std::atomic<long long>, 3>& mergeCount_() { static std::array<std::atomic<long long>, 3> c{}; return c; }
+  /// [fragint] [0] gate-passing (and gate:anchor_rescue rescued) fragments given the core/sum amplitude; [1] those of
+  /// them with no point there (fallback)
+  inline std::array<std::atomic<long long>, 2>& fragIntCount_() { static std::array<std::atomic<long long>, 2> c{}; return c; }
+  /// [anchor] gate:anchor_rescue: [0] non-faint precursors scored, [1] of them anchored, [2] candidates of the anchored,
+  /// [3] rescued, [4] passed beyond gate:anchor_max_rescued, [5] precursors with a rescue, [6] rescued peaks in written
+  /// spectra (after the same-bin merge and the cap, before the twin fold), [7] written spectra holding one, [8..10] rescued
+  /// fragments the gate had rejected at the point floor, the overlap guard, the correlation cut
+  inline std::array<std::atomic<long long>, 11>& anchorCount_() { static std::array<std::atomic<long long>, 11> c{}; return c; }
+  /// [foreign] per assembly (one precursor in one window): [8] assemblies checked (with fragments), [0] of them with a
+  /// foreign candidate, [1] foreign envelopes matched, [2] assemblies with a fragment attenuated, [3] fragments
+  /// attenuated, [4] candidates skipped as this precursor's own ion, [5] assemblies of [2] with at least
+  /// assembly:min_fragments before the removal (weight 0) and fewer after it and the same-bin merge, [6] matched
+  /// fragments' signed m/z error summed in 0.001 ppm, [7] matches behind [6]
+  inline std::array<std::atomic<long long>, 9>& foreignCount_() { static std::array<std::atomic<long long>, 9> c{}; return c; }
+  /// [fuse] assembly:fragment_fuse_ppm, per assembly (one precursor in one window) with at least one fragment: [0]
+  /// assemblies, [1] fragments in, [2] peaks out, [3] groups of >= 2 fused, [4] fragments in those groups, [5] assemblies
+  /// with at least assembly:min_fragments before the fusion and fewer after it
+  inline std::array<std::atomic<long long>, 6>& fuseCount_() { static std::array<std::atomic<long long>, 6> c{}; return c; }
   /// RAII in main_: one sampler for the run, joined before any return path leaves the function.
   struct LedRun
   {
@@ -630,6 +667,11 @@ namespace
     int n_isotopes = 0;      ///< [Q4] isotope peaks behind the mono call (0/1 = weak, mono ±1.00335 uncertain)
   };
 
+  /// [monocheck-v2] What charge:mono_profile_check v2 needs of a count walk, one per precursor of inferPrecursors_
+  /// (z = 0: nothing to test): the winning charge, its leftward partners' m/z (nearest first), the monoisotope before
+  /// v2, and whether the leftward walk stopped at charge:mono_averagine_guard instead of on a miss.
+  struct MonoV2In_ { int z = 0, nl = 0; bool guard_stop = false; double mono = 0.0; std::array<double, 5> left_mz{}; };
+
   /// MassTraceDetection locates the per-peak IM array by the exact name
   /// Constants::UserParam::ION_MOBILITY ("Ion Mobility"). Converters name it via CV term and
   /// PeakPickerIM names it "Ion Mobility Centroid"; rename whichever exists so tracing is IM-aware.
@@ -2124,7 +2166,8 @@ namespace
   /// own. Same frame => same RT cell => same tile under every grouping, so the output stays grouping- and
   /// thread-invariant. This is bench/twin_merge.py, which priced it: docs/SAME-POSITION-DUPLICATION-2026-09-20.md.
   /// `v` in canonical order; survivors keep their places. Returns the number of spectra removed.
-  static size_t mergeTwins_(vector<MSSpectrum>& v, double im_tol)
+  /// [recap] `keyed`: every spectrum carries its peaks' cap keys as float data array 0; a fused peak keeps the max key.
+  static size_t mergeTwins_(vector<MSSpectrum>& v, double im_tol, bool keyed = false)
   {
     const double TWIN_PPM = 20.0, FUSE_PPM = 10.0;   // ponytail: the measured values, no option until another is measured
     struct K { double rt, mz, im; int z; uint32_t i; };
@@ -2182,6 +2225,36 @@ namespace
 #pragma omp parallel for schedule(dynamic, 64)
     for (long c = 0; c < (long)surv.size(); ++c)
     {
+      if (keyed)
+      {
+        // [recap] the same fusion over (m/z, intensity, key) triples. Peaks equal in m/z and intensity add equal terms
+        // and always land in one fused peak, so the peaks are the unkeyed fold's; each fused peak keeps its members' max key.
+        vector<std::array<double, 3>> ps;
+        for (uint32_t i : members[(size_t)c])
+        {
+          const auto& fd = v[i].getFloatDataArrays();
+          for (Size j = 0; j < v[i].size(); ++j) ps.push_back({v[i][j].getMZ(), (double)v[i][j].getIntensity(), fd.empty() ? 0.0 : (double)fd[0][j]});
+        }
+        sort(ps.begin(), ps.end());
+        vector<pair<double, double>> fused;
+        OpenMS::DataArrays::FloatDataArray kk;
+        kk.setName("spx_cap_key");
+        const double NO_KEY = -std::numeric_limits<double>::infinity();
+        double gm = 0.0, gw = 0.0, gi = 0.0, gk = NO_KEY;
+        for (const auto& pk : ps)
+        {
+          if (gw != 0.0 && pk[0] - gm / gw > (gm / gw) * (FUSE_PPM * 1e-6)) { fused.emplace_back(gm / gw, gi); kk.push_back((float)gk); gm = gw = gi = 0.0; gk = NO_KEY; }
+          gm += pk[0] * pk[1]; gw += pk[1]; gi = std::max(gi, pk[1]); gk = std::max(gk, pk[2]);
+        }
+        if (gw != 0.0) { fused.emplace_back(gm / gw, gi); kk.push_back((float)gk); }
+        MSSpectrum& s = v[surv[(size_t)c]];
+        s.clear(false);
+        s.reserve(fused.size());
+        for (const auto& f : fused) s.emplace_back(f.first, (float)f.second);
+        s.getFloatDataArrays().clear();
+        s.getFloatDataArrays().push_back(std::move(kk));   // moved, not copied (assign(1, x) copies)
+        continue;
+      }
       vector<pair<double, double>> ps;
       for (uint32_t i : members[(size_t)c]) for (const auto& pk : v[i]) ps.emplace_back(pk.getMZ(), (double)pk.getIntensity());
       sort(ps.begin(), ps.end());
@@ -2211,6 +2284,40 @@ namespace
     return removed;
   }
 
+  /// [recap] assembly:post_fusion_cap: the twin fold unions capped spectra, so a folded one can exceed max_frags. Keeps
+  /// the max_frags peaks with the highest carried cap key (ties: higher intensity, then lower m/z), in m/z order, and
+  /// drops the key array of every spectrum (it is never written). Per spectrum, so thread-invariant.
+  /// Returns {spectra re-capped, peaks removed, largest spectrum before}.
+  static std::array<size_t, 3> capAfterFusion_(vector<MSSpectrum>& v, Size max_frags)
+  {
+    size_t n_sp = 0, n_pk = 0, n_max = 0;
+#pragma omp parallel for schedule(dynamic, 256) reduction(+ : n_sp, n_pk) reduction(max : n_max)
+    for (long i = 0; i < (long)v.size(); ++i)
+    {
+      MSSpectrum& s = v[(size_t)i];
+      n_max = std::max(n_max, (size_t)s.size());
+      if (s.size() > max_frags && !s.getFloatDataArrays().empty())
+      {
+        const auto& k = s.getFloatDataArrays()[0];
+        vector<Size> idx(s.size());
+        for (Size j = 0; j < idx.size(); ++j) idx[j] = j;
+        partial_sort(idx.begin(), idx.begin() + (long)max_frags, idx.end(), [&](Size a, Size b) {
+          if (k[a] != k[b]) return k[a] > k[b];
+          if (s[a].getIntensity() != s[b].getIntensity()) return s[a].getIntensity() > s[b].getIntensity();
+          if (s[a].getMZ() != s[b].getMZ()) return s[a].getMZ() < s[b].getMZ();
+          return a < b;
+        });
+        idx.resize(max_frags);
+        sort(idx.begin(), idx.end());   // the peaks are m/z-sorted: ascending positions keep that order
+        n_pk += s.size() - max_frags; ++n_sp;
+        s.getFloatDataArrays().clear();
+        s.select(idx);
+      }
+      s.getFloatDataArrays().clear();
+    }
+    return {n_sp, n_pk, n_max};
+  }
+
   /// [tile-2e] Streams spectra to an mzML in BLOCKS: the header once, then every block encoded in
   /// parallel chunks (the tool-side twin of patches/openms-mzml-parallel-write.patch) and appended in
   /// order, the index offsets rebased as each chunk lands. Blocks arrive in the canonical order (a
@@ -2357,8 +2464,8 @@ protected:
 
     registerTOPPSubsection_("assembly", "Pseudo-spectrum assembly");
     registerIntOption_("assembly:min_fragments", "<n>", 3, "Emit a pseudo-spectrum only if it has at least this many fragments.", false);
-    registerIntOption_("assembly:max_fragments", "<n>", 500, "Keep at most this many (top-ranked) fragments per pseudo-spectrum (applied before the twin fold, see assembly:twin_im_tolerance).", false);
-    registerDoubleOption_("assembly:im_weight_sigma", "<1/K0>", 0.0, "Multiply each fragment's intensity by exp(-dIM^2 / 2 sigma^2), dIM its 1/K0 distance from the precursor; this also changes which fragments survive assembly:max_fragments. 0 = off. 0.005 is the measured optional setting (Sage +1-7% over corr_power 2 on three files, flat on MSFragger): docs/BASELINE.md 'Confirmed WINS post-freeze'.", false);
+    registerIntOption_("assembly:max_fragments", "<n>", 500, "Keep at most this many (top-ranked) fragments per pseudo-spectrum (applied before the twin fold, see assembly:twin_im_tolerance; assembly:post_fusion_cap re-applies it after the fold).", false);
+    registerDoubleOption_("assembly:im_weight_sigma", "<1/K0>", 0.005, "Multiply each fragment's intensity by exp(-dIM^2 / 2 sigma^2), dIM its 1/K0 distance from the precursor; this also changes which fragments survive assembly:max_fragments. 0 = off. Default 0.005 since the 2026-09-29 tuning campaign (screen: Sage +3-7 %, MSFragger +3-5 % on K562, HeLa 10/100 ng and TNBC at flat entrapment); earlier measurements in docs/BASELINE.md 'Confirmed WINS post-freeze'.", false);
     registerDoubleOption_("assembly:corr_power", "<k>", 2.0, "Multiply each emitted fragment's intensity by corr^k (k >= 0), corr its co-elution score with the precursor. Emitted intensity only: which fragments survive assembly:max_fragments is unchanged. 0 = off (the behaviour before 2026-07-28). Default 2: +8-10% Sage on three files (docs/BASELINE.md 'Confirmed WINS post-freeze') and +4% MSFragger on the one file measured with it ('CONTENT CANDIDATE 1 FALSIFIED').", false);
     registerDoubleOption_("assembly:twin_im_tolerance", "<1/K0>", 0.005, "Fold spectra that claim one precursor twice into one: same MS1 frame, same charge, precursor m/z within 20 ppm, 1/K0 within this tolerance. The member with the most isotopes, then the most peaks, keeps its precursor and takes the union of the cluster's fragments (peaks within 10 ppm fused), so a folded spectrum can exceed assembly:max_fragments. Twins come from two seeds that resolve to one monoisotope, or from one precursor in the overlap of two isolation windows. -1 = off (the spectra before 1.4.0); 0 still folds twins of identical 1/K0. CHANGES OUTPUT. Default 0.005: -23.8% spectra for -0.21% Sage / -0.18% MSFragger peptides on PXD029836, entrapment FDR 0.98% with the fold against 0.98% without (docs/SAME-POSITION-DUPLICATION-2026-09-20.md).", false);
     registerIntOption_("assembly:default_charge", "<z>", 2, "Charge given to a precursor left without a charge call (no isotope partner, or a z=1 call on the 3+ mobility band): > 0 assigns that charge, 0 leaves it unset for the search engine. These are the guessed precursors, so it has no effect unless -assembly:require_isotope_support false keeps them.", false);
@@ -2390,7 +2497,7 @@ protected:
     registerStringOption_("trace:mz_estimator", "<mode>", "apex", "Reported m/z of a mass trace: 'apex' the most intense peak's, 'mean' the intensity-weighted centroid (OpenMS), 'median' the median. CHANGES OUTPUT. Fragment traces of the integer detector always report the calibrated m/z of their apex bin, whatever this says; with trace:detector openms the estimator applies to them too. apex measured best on both engines: docs/BASELINE.md 'APEX estimator: 3-FILE RESULT'.", false);
     setValidStrings_("trace:mz_estimator", {"apex", "mean", "median"});
     registerDoubleOption_("trace:ms2_split_valleys", "<chrom_fwhm>", 7.0, "Split MS2 mass traces at chromatographic valleys (ElutionPeakDetection, width filtering off). Value = chrom_fwhm (seconds); 0 = off.", false);
-    registerFlag_("diag:selftest_twins", "Run assertions on the twin fold (mergeTwins_) and exit: the relation, the cluster closure, the survivor order and the 10-ppm fusion", true);
+    registerFlag_("diag:selftest_twins", "Run assertions on the twin fold (mergeTwins_) and exit: the relation, the cluster closure, the survivor order, the 10-ppm fusion and the keyed fold with the post-fusion cap (assembly:post_fusion_cap)", true);
     registerFlag_("diag:selftest_arena", "Run assertions on the MS1 arena compaction (compactUnreferenced) and exit: kept spans must survive a container order that differs from their offset order", true);
     registerDoubleOption_("trace:ms1_split_valleys", "<chrom_fwhm>", 7.0, "Split MS1 mass traces at chromatographic valleys (ElutionPeakDetection), so two peptides eluting apart within the m/z tolerance do not merge into one precursor with the wrong monoisotope and charge. Value = chrom_fwhm (seconds); 0 = off.", false);
     registerDoubleOption_("trace:max_span_sec", "<sec>", 120.0, "Trim each mass trace (precursor and fragment) to at most this many seconds "
@@ -2430,12 +2537,46 @@ protected:
     registerIntOption_("gate:short_min_points", "<n>", 1, "gate:short_traces concentric: fewest points a short fragment trace needs.", false, true);
     setMinInt_("gate:short_min_points", 1);
     registerDoubleOption_("gate:fragment_delta_im", "<1/K0>", -1.0, "Max |precursor - fragment| 1/K0 difference in the co-elution gate alone; negative = gate:delta_im, which also sets the tracing tolerance (widening that merges ions of different mobility). Experimental.", false, true);
+    registerStringOption_("gate:anchor_rescue", "<true/false>", "false", "Rescue weak fragments of well-sampled precursors (signal in more than gate:faint_max_frames window frames, the faint test of gate:adaptive in every mode). When at least gate:anchor_min_count fragments pass the gate with a correlation of gate:anchor_min_corr or more, their profiles, each scaled to unit maximum, are summed into a consensus over the window frames. A fragment trace inside the RT and 1/K0 windows that the gate rejected only for too few shared points or by gate:min_correlation, with at least 2 points, then joins when its apex is within one cycle of the consensus apex and its points correlate with the consensus at those frames (Pearson over its own points, not the full grid) by gate:anchor_rescue_corr or more; a 2-point trace instead needs both points in the consensus core (at least half its maximum) rising or falling with it, and scores gate:anchor_rescue_corr. The emitted intensity and the cap key use that score, capped at gate:anchor_min_corr; at most gate:anchor_max_rescued per spectrum, best score first. Logged as [anchor], stamped spx:anchor. Experimental.", false, true);
+    setValidStrings_("gate:anchor_rescue", {"true", "false"});
+    registerIntOption_("gate:anchor_min_count", "<n>", 3, "gate:anchor_rescue: fewest anchors (accepted fragments at gate:anchor_min_corr or more) a precursor needs for the rescue.", false, true);
+    setMinInt_("gate:anchor_min_count", 1);
+    registerDoubleOption_("gate:anchor_min_corr", "<r>", 0.8, "gate:anchor_rescue: least gate correlation of an anchor; also caps the score of a rescued fragment, so it never outweighs an anchor.", false, true);
+    setMinFloat_("gate:anchor_min_corr", 0.0);
+    setMaxFloat_("gate:anchor_min_corr", 1.0);
+    registerDoubleOption_("gate:anchor_rescue_corr", "<r>", 0.7, "gate:anchor_rescue: least Pearson correlation of a rejected fragment's points with the anchor consensus.", false, true);
+    setMinFloat_("gate:anchor_rescue_corr", 0.0);
+    setMaxFloat_("gate:anchor_rescue_corr", 1.0);
+    registerIntOption_("gate:anchor_max_rescued", "<n>", 50, "gate:anchor_rescue: most rescued fragments per spectrum (best score first, ties by m/z).", false, true);
+    setMinInt_("gate:anchor_max_rescued", 0);
     registerDoubleOption_("trace:im_slice_merge", "<1/K0>", 0.015, "Integer detector: before tracing, merge a frame's picked MS2 peaks that fall in one flight-time bin into one peak (intensity summed, 1/K0 intensity-weighted). Peaks join when their 1/K0 is within this distance of the previous one and the group spans at most twice this distance: the IM picker (box gate:delta_im) cuts an ion with a wider mobility peak into several same-bin centroids, which would otherwise become separate traces and duplicate m/z in a spectrum. Negative = off.", false, true);
     setMaxFloat_("trace:im_slice_merge", 1.0);   // 1/K0 units: anything wider than the mobility axis is a typo
     registerStringOption_("assembly:merge_same_bin", "<true/false>", "true", "Merge fragments of one flight-time bin (one m/z; exact m/z on the OpenMS detector) in a spectrum into one peak before assembly:max_fragments: members overlapping the strongest one in retention time are summed, RT-disjoint pieces dropped; the peak keeps the strongest member's m/z and the best cap key of the summed members. Catches what trace:im_slice_merge cannot (valley splits, band edges, tile carries, slices beyond its span). Two peaks at one m/z break the fragment matching of OpenMS-based search engines.", false, true);
     setValidStrings_("assembly:merge_same_bin", {"true", "false"});
+    registerStringOption_("assembly:post_fusion_cap", "<true/false>", "false", "Re-apply assembly:max_fragments after the twin fold (assembly:twin_im_tolerance), whose union of the members' capped fragments can exceed it. Every peak carries its assembly:cap_rank key (as a 32-bit float) through the same-bin merge and the fold (a fused peak keeps its members' best key); a spectrum over the cap keeps its top-ranked peaks (ties: higher intensity, then lower m/z). Logged as [recap], stamped spx:post_fusion_cap. CHANGES OUTPUT. Experimental.", false, true);
+    setValidStrings_("assembly:post_fusion_cap", {"true", "false"});
     registerStringOption_("assembly:cap_rank", "<mode>", "evidence", "Which fragments survive assembly:max_fragments: 'corr_inten' ranks by gate score x intensity (the score is the shrunk or concentric one when those modes are on); 'umpire' by max(r,0)^2 x ln(1+I) with r the raw co-elution score before shrinkage (Pearson, or the logoverlap score under gate:coelution logoverlap; DIA-Umpire's key); 'evidence' by max(r,0) x ln(1+I) x (1 + overlapping frames), so long, correlated support outranks an intense one-frame coincidence. Experimental.", false, true);
     setValidStrings_("assembly:cap_rank", {"corr_inten", "umpire", "evidence"});
+    registerStringOption_("assembly:frag_intensity", "<mode>", "apex", "The base amplitude of each emitted fragment, before the 1/K0 weight (assembly:im_weight_sigma) and corr^assembly:corr_power: 'apex' the fragment trace's maximum in one frame; 'core' its intensity summed over the assembly:frag_core_frames window frames centred on the precursor's apex frame (the same frames for every fragment of the precursor; a missing point counts 0); 'sum' its intensity summed over the precursor's span, the window frames from its first to its last point (gaps included). A fragment with no point in those frames takes its point nearest the precursor's apex frame, so none is dropped or written at 0. The gate and the assembly:cap_rank key (still the apex) are unchanged; the later steps that weigh by intensity follow the new values (the same-bin merge's strongest member, the twin fold's intensity-weighted m/z), so a few peaks move or change. Experimental.", false, true);
+    setValidStrings_("assembly:frag_intensity", {"apex", "core", "sum"});
+    registerIntOption_("assembly:frag_core_frames", "<n>", 3, "assembly:frag_intensity core: the number of window frames (odd) centred on the precursor's apex frame.", false, true);
+    setMinInt_("assembly:frag_core_frames", 1);
+    setMaxInt_("assembly:frag_core_frames", 15);
+    registerDoubleOption_("assembly:foreign_precursor_weight", "<w>", 0.0, "Multiply the fragments that lie on the residual isotope envelope of ANOTHER precursor isolated with this one by w, before assembly:max_fragments (0 removes them, 1 = off); the cap key follows the attenuated intensity. A foreign precursor is one of the run's precursors in the same isolation window with its apex within the gate's RT window of this precursor's, 1/K0 within assembly:foreign_precursor_dim, and neither a twin (mono within 0.01) nor this ion called again (either mono on the other's isotope grid, up to 3 steps, within 30 ppm). Its envelope counts when at least assembly:foreign_precursor_min_iso of its positions mono + k x 1.00335/z, k = 0..3, carry a fragment within assembly:foreign_precursor_ppm. Fragments within 30 ppm of this precursor's own envelope (mono to M+3) are never touched. Logged as [foreign], stamped spx:foreign. Experimental.", false, true);
+    setMinFloat_("assembly:foreign_precursor_weight", 0.0);
+    setMaxFloat_("assembly:foreign_precursor_weight", 1.0);
+    registerDoubleOption_("assembly:foreign_precursor_ppm", "<ppm>", 10.0, "assembly:foreign_precursor_weight: m/z tolerance between a foreign envelope position and a fragment (ppm).", false, true);
+    setMinFloat_("assembly:foreign_precursor_ppm", 0.0);
+    registerDoubleOption_("assembly:foreign_precursor_dim", "<1/K0>", 0.015, "assembly:foreign_precursor_weight: largest 1/K0 distance between this precursor and a foreign one.", false, true);
+    setMinFloat_("assembly:foreign_precursor_dim", 0.0);
+    registerIntOption_("assembly:foreign_precursor_min_iso", "<n>", 2, "assembly:foreign_precursor_weight: how many of a foreign envelope's four positions (mono to M+3) must carry a fragment before its fragments are attenuated.", false, true);
+    setMinInt_("assembly:foreign_precursor_min_iso", 1);
+    setMaxInt_("assembly:foreign_precursor_min_iso", 4);
+    registerDoubleOption_("assembly:fragment_fuse_ppm", "<ppm>", 25.0, "Fuse a spectrum's fragments that lie within this many ppm into one peak, after the same-bin merge and before assembly:min_fragments and assembly:max_fragments (0 = off; default 25 with assembly:fragment_fuse_mode anchored since the 2026-09-29 tuning campaign, rc-b): the IM picker keeps 1-2 flight-time bins of an ion that spans 4-7, so one fragment ion becomes several traces and several peaks a few ppm apart. A fused peak's intensity is the sum of its members' emitted intensities, its m/z their intensity-weighted mean and its cap key (assembly:cap_rank) their best, so the cap ranks fused peaks and the slots they free refill. Grouping by assembly:fragment_fuse_mode. Logged as [fuse], stamped spx:fragment_fuse. CHANGES OUTPUT. Experimental.", false, true);
+    setMinFloat_("assembly:fragment_fuse_ppm", 0.0);
+    setMaxFloat_("assembly:fragment_fuse_ppm", 50.0);
+    registerStringOption_("assembly:fragment_fuse_mode", "<mode>", "anchored", "assembly:fragment_fuse_ppm: 'anchored' takes the fragments by emitted intensity, strongest first (ties: lower m/z); each one not yet fused becomes an anchor and takes every unfused fragment within the tolerance of its own m/z. 'linkage' walks the fragments in m/z order and joins a fragment to the group of the previous one when it lies within the tolerance of it and within twice the tolerance of the group's first member (single linkage, span capped).", false, true);
+    setValidStrings_("assembly:fragment_fuse_mode", {"anchored", "linkage"});
     registerStringOption_("gate:adaptive", "<mode>", "faint", "'faint': apply gate:shrinkage, gate:colocation, gate:short_traces, gate:faint_delta_rt and gate:faint_corr_power only to faint precursors, those with signal in at most gate:faint_max_frames window frames (a faint ion is the short tip of its elution peak); every other precursor keeps the plain gate (gate:delta_rt, gate:min_correlation_points, assembly:corr_power). 'auto': 'faint' when at least gate:auto_faint_fraction of the run's precursors have at most gate:faint_max_frames MS1 trace points, else the plain gate for every precursor (gate:shrinkage, gate:colocation and gate:short_traces off; the choice is stamped as spx:gate_adaptive auto:on|auto:off). 'off': gate:shrinkage, gate:colocation and gate:short_traces apply to every precursor at gate:delta_rt and assembly:corr_power (gate:faint_delta_rt and gate:faint_corr_power unused). Experimental.", false, true);
     setValidStrings_("gate:adaptive", {"off", "faint", "auto"});
     registerDoubleOption_("gate:auto_faint_fraction", "<frac>", 0.45, "gate:adaptive auto: the run gets the faint gate when at least this fraction of its precursors span at most gate:faint_max_frames MS1 points (a sparse run: HeLa 10-100 ng 0.57-0.69, dense tissue 0.21); otherwise the plain gate. Logged and stamped spx:gate_adaptive.", false, true);
@@ -2492,6 +2633,22 @@ protected:
     setValidStrings_("assembly:require_isotope_support", {"true", "false"});
     registerDoubleOption_("charge:mono_averagine_guard", "<slack>", 0.0, "Reject a leftward isotope step of the charge:scoring=count walk when the lighter peak is below slack x heavier peak / lambda, averagine's loosest ratio (lambda = 0.000594 x neutral mass; 1.0 = exactly that bound, smaller values add slack). 0 = off. Falsified: it trades the -1.003 Da open-search artefact for a +1.003 Da one, docs/BASELINE.md 'Monoisotope -1.003 Da open-search artefact'.", false);
     registerFlag_("charge:mono_averagine_select", "Choose the monoisotope by averagine cosine over the whole isotope run of the charge:scoring=count walk instead of its furthest-left peak; only the reported precursor mass moves. Missed its pre-registered criterion: docs/BASELINE.md 'Monoisotope -1.003 Da open-search artefact'.");
+    registerStringOption_("charge:mono_profile_check", "<false/true/v2>", "v2", "Check the monoisotope of the charge:scoring=count walk, for the winning charge only (default v2 since the 2026-09-29 tuning campaign, rc-b; false = off). "
+                          "'true' (v1): a lighter trace becomes the monoisotope only if its MS1 elution profile correlates with the seed trace's (Pearson >= charge:mono_profile_min_corr over the frames both have; below 3 shared frames the correlation test passes unchecked) and its 1/K0 is within charge:mono_profile_max_dim of the seed's. "
+                          "The walk stops at the first failed step: the monoisotope is the last accepted peak, and the rejected trace and the ones beyond it stay unclaimed for other precursors. "
+                          "'v2': isotope-position intensity sums (charge:mono_position_*). PS(k) = summed apex intensity of every MS1 trace, claimed or not, at the seed's isotope position k (the partner tolerance in m/z, gate:delta_rt, charge:mono_position_im_box 1/K0 of the seed, by default from the run's own isotope scatter). "
+                          "The walk's leftmost step j is rejected when PS(-j) / PS(-j+1) x lambda < charge:mono_position_min_ratio (lambda = max(0.1, 0.000594 x neutral mass), averagine's M-1/M0 bound; an empty heavier position counts as 0); "
+                          "the monoisotope moves one isotope right, the rejected trace stays claimed, and (charge:mono_position_iterate true) the new leftmost step is tested in turn. If nothing was rejected and the walk ended on a miss (not a charge:mono_averagine_guard stop), the next lighter position is accepted without claiming when its ratio is >= charge:mono_position_extend (0 = off). "
+                          "v2 judges each walk at its precursor's final charge, after charge:im_charge_veto: a z=1 walk re-called 2+ stepped 1.003 m/z, two isotopes at 2+, and is read at 2+ spacing. "
+                          "Both 'true' and 'v2' keep the charge, the seed and the envelope size (spx_n_isotopes). Logged as [monocheck], stamped spx:monocheck. CHANGES OUTPUT.", false, true);
+    setValidStrings_("charge:mono_profile_check", {"false", "true", "v2"});
+    registerDoubleOption_("charge:mono_profile_min_corr", "<r>", 0.6, "charge:mono_profile_check true: minimum Pearson correlation of a leftward partner's MS1 profile with the seed's.", false, true);
+    registerDoubleOption_("charge:mono_profile_max_dim", "<1/K0>", 0.015, "charge:mono_profile_check true: maximum 1/K0 difference of a leftward partner from the seed.", false, true);
+    registerDoubleOption_("charge:mono_position_min_ratio", "<q>", 0.2, "charge:mono_profile_check v2: the walk's leftmost step is rejected when its averagine-scaled position ratio PS(-j) / PS(-j+1) x lambda is below this.", false, true);
+    registerDoubleOption_("charge:mono_position_im_box", "<1/K0>", 0.0, "charge:mono_profile_check v2: 1/K0 half-width around the seed of the isotope-position intensity sums. 0 = auto: 3.5 x the 90th percentile of the 1/K0 gap between the brightest tenth of the count-walk seeds and their nearest MS1 trace one isotope heavier, clamped to [0.01, 0.03] (K562 9905: 0.01; 2019 HeLa py3, whose isotope traces scatter wider in 1/K0: 0.019). A value > 0 fixes the box.", false, true);
+    registerDoubleOption_("charge:mono_position_extend", "<q>", 0.6, "charge:mono_profile_check v2: when no step was rejected and the walk ended on a miss, move the monoisotope one isotope lighter (the most intense trace there, not claimed) if that position's ratio is >= this. 0 = off.", false, true);
+    registerStringOption_("charge:mono_position_iterate", "<true/false>", "true", "charge:mono_profile_check v2: after a rejected leftmost step, test the new leftmost step too, and repeat while steps fail. false tests the leftmost step only.", false, true);
+    setValidStrings_("charge:mono_position_iterate", {"true", "false"});
     registerDoubleOption_("charge:iso_im_tolerance", "<1/K0>", 0.05, "1/K0 tolerance for matching isotope partners. Only 0.05 has been measured; change it behind a peptide-set gate.", false);
 
     registerTOPPSubsection_("dnoise", "MS1 denoising of the raw frames before peak picking (dnoise v0.1.0's MS1 path; Bruker .d only)");
@@ -2532,6 +2689,12 @@ protected:
     setMinFloat_("gate:min_correlation", -1.0);
     setMaxFloat_("gate:min_correlation", 1.0);
     setMinFloat_("charge:iso_im_tolerance", 0.0);
+    setMinFloat_("charge:mono_profile_min_corr", -1.0);
+    setMaxFloat_("charge:mono_profile_min_corr", 1.0);
+    setMinFloat_("charge:mono_profile_max_dim", 0.0);
+    setMinFloat_("charge:mono_position_min_ratio", 0.0);
+    setMinFloat_("charge:mono_position_im_box", 0.0);
+    setMinFloat_("charge:mono_position_extend", 0.0);
     setMinFloat_("trace:ms1_chrom_peak_snr", 0.0);
     setMinFloat_("trace:ms2_chrom_peak_snr", 0.0);
     setMinFloat_("trace:ms2_noise_threshold_int", 0.0);
@@ -2801,7 +2964,7 @@ protected:
   /// by averagine-shape agreement x isotope-XIC co-elution, instead of counting partners.
   vector<Precursor_> inferPrecursors_(const vector<Trace>& ms1, const TraceStore& ms1st, int max_charge,
                                       double delta_rt, double iso_im_tol, double mass_ppm,
-                                      bool envelope_scoring)
+                                      bool envelope_scoring, vector<MonoV2In_>* v2_out = nullptr)
   {
     const double ISO = 1.0033548;
     const double PROTON_ = 1.00727646;
@@ -2872,10 +3035,15 @@ protected:
     // and re-evaluates one whose recorded partner has since been claimed. A search that returned -1 saw
     // only gate failures or used candidates, both stable under a monotone bitmap, so it needs no
     // dependency. docs/BASELINE.md, "Ordered speculation on the greedy claim loop".
-    struct SeedRes { vector<Precursor_> emit; vector<size_t> claims; vector<size_t> deps; };
+    // mc: [monocheck] v1 (true): walks checked, monos moved, rejected by profile, by 1/K0, steps passed with < 3
+    // shared frames (or a flat profile), partners released, moved monos left with no claimed partner, steps
+    // accepted by a profile that could be judged. v2: walks tested, monos moved right, steps rejected, extensions
+    // tested, monos moved left, -, monos moved back onto the seed, -. Summed at commit, not in speculation.
+    // [monocheck-v2] v2: the count walk's result for monoPositionPass_ (MonoV2In_), which runs after the IM charge veto.
+    struct SeedRes { vector<Precursor_> emit; vector<size_t> claims; vector<size_t> deps; std::array<size_t, 8> mc{}; MonoV2In_ v2; };
     auto evalSeed = [&](size_t seed, SeedRes& R)
     {
-      R.emit.clear(); R.claims.clear(); R.deps.clear();
+      R.emit.clear(); R.claims.clear(); R.deps.clear(); R.mc.fill(0); R.v2 = MonoV2In_();
       // do/while(0): the body below is the sequential loop body VERBATIM, and its seed-level
       // `continue` statements exit this wrapper exactly as they used to exit one loop iteration,
       // while `continue` inside the body's own inner loops keeps binding to those loops.
@@ -2905,7 +3073,8 @@ protected:
       // break-on-first-miss, monoisotope = furthest-left partner reached, z by partner count, ties to lowest z.
       if (!envelope_scoring)
       {
-        int best_z = 0, best_n = 1;
+        int best_z = 0, best_n = 1, best_nl = 0;
+        bool best_gstop = false;                // [monocheck-v2] the winning walk stopped at the guard, not on a miss
         double best_mono = s.mz;
         vector<size_t> best_partners;
         for (int z = 1; z <= max_charge; ++z)
@@ -2914,6 +3083,7 @@ protected:
           double mono = s.mz;
           double prev_int = inten[seed];
           vector<long> lefts;
+          bool gstop = false;
           for (int k = 1; k <= 5; ++k)          // lighter partners define the monoisotope
           {
             long j = findPartner(s.mz - k * ISO / z);
@@ -2925,7 +3095,7 @@ protected:
             {
               const double neutral = (s.mz - k * ISO / z) * z - z * PROTON_;
               const double lam = std::max(0.10, 0.000594 * neutral);
-              if (inten[j] < mono_guard_ * prev_int / lam) break;
+              if (inten[j] < mono_guard_ * prev_int / lam) { gstop = true; break; }
             }
             lefts.push_back(j);
             partners.push_back((size_t)j); mono = ms1[j].mz; prev_int = inten[j];
@@ -2967,7 +3137,40 @@ protected:
             mono = (best_c < nL) ? ms1[lefts[nL - 1 - best_c]].mz : s.mz;
           }
           const int n = 1 + (int)partners.size();
-          if (n > best_n) { best_n = n; best_z = z; best_mono = mono; best_partners = partners; }
+          if (n > best_n) { best_n = n; best_z = z; best_mono = mono; best_partners = partners; best_nl = (int)lefts.size(); best_gstop = gstop; }
+        }
+        // [monocheck] Re-walk the winning charge's leftward partners (best_partners[0, best_nl), nearest first):
+        // each must share the seed's elution profile and mobility, else the walk stops there and the
+        // rejected trace and those beyond it are released unclaimed. Charge and n_isotopes stay as counted.
+        if (mono_check_ == 1 && best_nl > 0)
+        {
+          ++R.mc[0];
+          int acc = 0; double acc_mz = s.mz;
+          for (; acc < best_nl; ++acc)
+          {
+            const Trace& t = ms1[best_partners[acc]];
+            if (fabs(t.im - s.im) > mono_check_max_dim_) { ++R.mc[3]; break; }
+            const double r = xicCorr(ms1st, t, s);   // -2: < 3 shared frames (or flat), too little to judge
+            if (r <= -2.0) ++R.mc[4];
+            else if (r < mono_check_min_corr_) { ++R.mc[2]; break; }
+            else ++R.mc[7];
+            acc_mz = t.mz;
+          }
+          if (acc < best_nl)
+          {
+            R.mc[5] += (size_t)(best_nl - acc);
+            if (acc_mz > best_mono) { best_mono = acc_mz; ++R.mc[1]; }   // mono_averagine_select may already sit further right
+            best_partners.erase(best_partners.begin() + acc, best_partners.begin() + best_nl);
+            if (best_partners.empty()) ++R.mc[6];
+          }
+        }
+        // [monocheck-v2] Record what monoPositionPass_ needs (v2 reads only the immutable arrays and changes only
+        // mono_mz, so deciding it after the loop gives the same result as deciding it here, lets an automatic im_box
+        // use the run's own isotope scatter, and lets the decision follow the IM charge veto).
+        if (mono_check_ == 2 && best_z > 0)
+        {
+          R.v2.z = best_z; R.v2.nl = best_nl; R.v2.mono = best_mono; R.v2.guard_stop = best_gstop;
+          for (int i = 0; i < best_nl; ++i) R.v2.left_mz[(size_t)i] = ms1[best_partners[(size_t)i]].mz;
         }
         Precursor_ pc0;
         pc0.trace_idx = seed;
@@ -3060,6 +3263,8 @@ protected:
     if (const char* e = std::getenv("DIASPEXTRACT_SPEC_BATCH")) { long v = atol(e); if (v >= 1) spec_batch = (size_t)v; }
     vector<SeedRes> res(spec_batch);
     size_t n_committed = 0, n_conflict = 0, n_skipped = 0;
+    std::array<size_t, 8> mc_tot{};   // [monocheck] SeedRes::mc over the committed seeds
+    vector<MonoV2In_> v2in;           // [monocheck-v2] parallel to `out` when mono_check_ == 2
     for (size_t b0 = 0; b0 < order.size(); b0 += spec_batch)
     {
       const size_t b1 = std::min(b0 + spec_batch, order.size());
@@ -3081,7 +3286,8 @@ protected:
         bool stale = false;
         for (size_t d : R.deps) if (used[d]) { stale = true; break; }
         if (stale) { evalSeed(seed, R); ++n_conflict; }
-        for (const auto& pc : R.emit) out.push_back(pc);
+        for (const auto& pc : R.emit) { out.push_back(pc); if (mono_check_ == 2) v2in.push_back(R.v2); }
+        if (mono_check_) for (size_t q = 0; q < mc_tot.size(); ++q) mc_tot[q] += R.mc[q];
         used[seed] = true;
         for (size_t j : R.claims) used[j] = true;
         ++n_committed;
@@ -3131,9 +3337,215 @@ protected:
                     + " re-evaluated (" + String((int)(1000.0 * n_conflict / std::max<size_t>(n_committed, 1)) / 10.0)
                     + "%), " + String(n_skipped) + " already claimed)");
     }
+    if (mono_check_ == 1)
+    {
+      mono_check_stamp_ = String(envelope_scoring ? "n/a (charge:scoring envelope)" : "on") + ", min_corr " + String(mono_check_min_corr_)
+                          + ", max_dim " + String(mono_check_max_dim_) + ": " + String(mc_tot[1]) + " of " + String(mc_tot[0]) + " monos moved right";
+      writeLogInfo_("[monocheck] " + String(mc_tot[0]) + " count walks checked (winning charge with a leftward partner): "
+                    + String(mc_tot[1]) + " monoisotopes moved right; steps rejected by profile (r < " + String(mono_check_min_corr_) + ") "
+                    + String(mc_tot[2]) + ", by 1/K0 (> " + String(mono_check_max_dim_) + ") " + String(mc_tot[3]) + "; steps accepted "
+                    + String(mc_tot[7]) + " by profile, " + String(mc_tot[4]) + " unchecked (< 3 shared frames or flat); " + String(mc_tot[5])
+                    + " leftward partners released unclaimed; " + String(mc_tot[6]) + " precursors kept no claimed partner"
+                    + (envelope_scoring ? " (charge:scoring envelope: not applied)" : ""));
+    }
+    if (v2_out) v2_out->swap(v2in);   // [monocheck-v2] parallel to `out`, for monoPositionPass_
     return out;
   }
 
+  /// [monocheck-v2] charge:mono_profile_check v2, after the IM charge veto: each count walk is judged at its
+  /// precursor's FINAL charge. A z=1 walk the veto re-calls 2+ stepped 1.003 m/z, two isotopes at 2+; judged at z=1
+  /// spacing its steps and extension land two isotopes off (K562 9905, identified release keys from such walks:
+  /// 54.5 % not monoisotopic in the release, 55.7 % after a z=1-spaced v2), so its walk is read at the final charge:
+  /// its leftmost partner is position -2 nl there, and the positions between are filled by whatever traces sit on
+  /// them. PS(k) sums the apex intensity of EVERY MS1 trace (claimed or not, the seed included) at the seed's isotope
+  /// position k within im_box 1/K0, in m/z order (deterministic): findPartner takes the first box candidate in m/z
+  /// order and IM slicing splits one isotope over several traces, so single-trace ratios are noisy. A: an identified
+  /// walk carries at most one spurious step and it is the leftmost (engines search -1..2), so step j = the leftmost is
+  /// rejected when PS(-j) / PS(-j+1) x lambda < min_ratio and the mono moves one isotope right (iterate: repeat).
+  /// B: when A rejected nothing and the walk ended on a miss (< 5 steps, not a charge:mono_averagine_guard stop), the
+  /// true mono may be claimed by a brighter precursor, so the next lighter position becomes the mono, unclaimed, on a
+  /// ratio >= extend. Only mono_mz changes: claims, charge and n_isotopes are the greedy loop's and the veto's.
+  /// im_box 0 (auto): 3.5 x the 90th percentile of |d 1/K0| between the brightest decile of the walks (commit order is
+  /// seed-intensity order) and their nearest trace one isotope heavier at the walk's charge (partner m/z tolerance,
+  /// delta_rt, iso_im_tol), clamped to [0.01, 0.03]. `pcs` must be inferPrecursors_'s output in its order (the veto
+  /// edits charges in place); `v2in` is the walk record inferPrecursors_ returned beside it.
+  void monoPositionPass_(const vector<Trace>& ms1, const TraceStore& ms1st, vector<Precursor_>& pcs,
+                         const vector<MonoV2In_>& v2in, double delta_rt, double iso_im_tol, double mass_ppm,
+                         bool envelope_scoring)
+  {
+    const double ISO = 1.0033548;
+    const double PROTON_ = 1.00727646;
+    // walks tested, moved right, steps rejected, extensions tested, moved left, walks read at a veto-changed charge,
+    // moved back onto the seed
+    std::array<size_t, 8> mc_tot{};
+    double v2_box = mono_pos_im_box_, v2_p90 = -1.0;
+    size_t v2_nb = 0, v2_nhit = 0;
+    if (!envelope_scoring)
+    {
+      if (v2in.size() != pcs.size())
+        throw Exception::Precondition(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[monocheck-v2] the walk record does not match the precursor list");
+      // The m/z-sorted index of inferPrecursors_ (same comparator on the same container, so the same order; the plain
+      // std searches return the positions its bucket index returns).
+      const size_t N = ms1.size();
+      vector<size_t> by_mz(N);
+      for (size_t i = 0; i < N; ++i) by_mz[i] = i;
+      sort(by_mz.begin(), by_mz.end(), [&](size_t a, size_t b) { return ms1[a].mz < ms1[b].mz; });
+      vector<double> sorted_mz(N), sorted_rt(N), sorted_im(N);
+      for (size_t i = 0; i < N; ++i) { const Trace& t = ms1[by_mz[i]]; sorted_mz[i] = t.mz; sorted_rt[i] = rtOf(ms1st, t); sorted_im[i] = t.im; }
+      vector<float> inten(N);
+      for (size_t i = 0; i < N; ++i) inten[i] = (float)intensityOf(ms1st, ms1[i]);
+      auto lbmz = [&](double x) -> size_t { return (size_t)(std::lower_bound(sorted_mz.begin(), sorted_mz.end(), x) - sorted_mz.begin()); };
+      auto ubmz = [&](double x) -> size_t { return (size_t)(std::upper_bound(sorted_mz.begin(), sorted_mz.end(), x) - sorted_mz.begin()); };
+      if (v2_box <= 0.0)
+      {
+        size_t nz = 0;
+        for (const MonoV2In_& v : v2in) if (v.z > 0) ++nz;
+        v2_nb = (nz + 9) / 10;
+        vector<size_t> idx;
+        idx.reserve(v2_nb);
+        for (size_t i = 0; i < pcs.size() && idx.size() < v2_nb; ++i) if (v2in[i].z > 0) idx.push_back(i);
+        vector<double> gaps(idx.size(), -1.0);
+        #pragma omp parallel for schedule(dynamic, 256)
+        for (long ii = 0; ii < (long)idx.size(); ++ii)
+        {
+          const size_t seed = pcs[idx[(size_t)ii]].trace_idx;
+          const Trace& s = ms1[seed];
+          const double s_rt = rtOf(ms1st, s), tol = s.mz * mass_ppm * 1e-6;
+          const double target = s.mz + ISO / v2in[idx[(size_t)ii]].z;
+          const size_t klo = lbmz(target - tol), khi = ubmz(target + tol);
+          double g = -1.0;
+          for (size_t q = klo; q < khi; ++q)
+          {
+            if (fabs(sorted_rt[q] - s_rt) > delta_rt || by_mz[q] == seed) continue;
+            const double d = fabs(sorted_im[q] - s.im);
+            if (d <= iso_im_tol && (g < 0.0 || d < g)) g = d;
+          }
+          gaps[(size_t)ii] = g;
+        }
+        gaps.erase(std::remove_if(gaps.begin(), gaps.end(), [](double g) { return g < 0.0; }), gaps.end());
+        v2_nhit = gaps.size();
+        if (!gaps.empty())
+        {
+          const size_t k = (size_t)(0.9 * (double)(gaps.size() - 1));
+          std::nth_element(gaps.begin(), gaps.begin() + (long)k, gaps.end());
+          v2_p90 = gaps[k];
+        }
+        v2_box = v2_p90 < 0.0 ? 0.01 : std::min(0.03, std::max(0.01, 3.5 * v2_p90));
+      }
+      // Per precursor: bit 0 walk tested, 1 moved right, 2 moved back onto the seed, 3 extension tested, 4 moved left,
+      // 5 read at a veto-changed charge; rej = steps rejected. Summed below in index order.
+      vector<uint8_t> flag(pcs.size(), 0), rej(pcs.size(), 0);
+      #pragma omp parallel for schedule(dynamic, 1024)
+      for (long ii = 0; ii < (long)pcs.size(); ++ii)
+      {
+        const MonoV2In_& v = v2in[(size_t)ii];
+        Precursor_& pc = pcs[(size_t)ii];
+        // The final charge: the veto re-calls a z=1 walk 2+ (a multiple of the walk's charge) or unsets it (0: the
+        // precursor becomes guessed and is dropped or defaulted later, untested).
+        if (v.z <= 0 || pc.charge <= 0 || pc.charge % v.z != 0) continue;
+        const int z = pc.charge, mul = pc.charge / v.z, nl = v.nl * mul;
+        const size_t seed = pc.trace_idx;
+        const Trace& s = ms1[seed];
+        const double s_rt = rtOf(ms1st, s), tol = s.mz * mass_ppm * 1e-6;
+        auto PS = [&](int k, long* best) -> double {
+          const double target = s.mz + k * ISO / z;
+          const size_t klo = lbmz(target - tol), khi = ubmz(target + tol);
+          double sum = 0.0; float bi = -1.0f;
+          for (size_t q = klo; q < khi; ++q)
+          {
+            if (fabs(sorted_rt[q] - s_rt) > delta_rt || fabs(sorted_im[q] - s.im) > v2_box) continue;
+            const size_t j = by_mz[q];
+            sum += inten[j];
+            if (best && inten[j] > bi) { bi = inten[j]; *best = (long)j; }
+          }
+          return sum;
+        };
+        // q of the step onto position -j: PS(-j) / PS(-j+1) x lambda(neutral mass of the mono after that step). A walk
+        // re-read at a veto charge never stood on its in-between positions: an empty one there is no evidence against
+        // the step, so the step is compared over two positions, PS(-j) / PS(-j+2) x lambda^2 / 2 (Poisson M+2/M0).
+        auto ratio = [&](int j, long* best) -> double {
+          const double neutral = (s.mz - j * ISO / z) * z - z * PROTON_;
+          const double lam = std::max(0.10, 0.000594 * neutral);
+          const double den = PS(-j + 1, nullptr);
+          if (den > 0.0) return PS(-j, best) / den * lam;
+          if (mul > 1 && (j - 1) % mul != 0)
+          {
+            const double den2 = PS(-j + 2, nullptr);
+            return den2 > 0.0 ? PS(-j, best) / den2 * lam * lam / 2.0 : 0.0;
+          }
+          return 0.0;
+        };
+        // the m/z standing at position -i: the walk's own partner where the walk stepped, else the most intense trace
+        // there in the box, else the position itself
+        auto leftMz = [&](int i) -> double {
+          if (i % mul == 0) return v.left_mz[(size_t)(i / mul - 1)];
+          long bt = -1;
+          PS(-i, &bt);
+          return bt >= 0 ? ms1[(size_t)bt].mz : s.mz - i * ISO / z;
+        };
+        double mono = v.mono;
+        uint8_t f = mul > 1 ? 32 : 0, r = 0;
+        int acc = nl;
+        if (nl > 0)
+        {
+          f |= 1;
+          while (acc > 0 && ratio(acc, nullptr) < mono_pos_min_ratio_)
+          {
+            --acc; ++r;
+            if (!mono_pos_iterate_)
+            {
+              // Leftmost step only, at a veto charge: an EMPTY in-between position cannot be the monoisotope (leftMz
+              // would report a bare position), so the mono moves on to the walk's next own position. mul == 1: no-op.
+              while (acc > 0 && acc % mul != 0 && PS(-acc, nullptr) <= 0.0) --acc;
+              break;
+            }
+          }
+          if (acc < nl)
+          {
+            const double acc_mz = acc > 0 ? leftMz(acc) : s.mz;
+            if (acc_mz > mono) { mono = acc_mz; f |= 2; if (acc == 0) f |= 4; }   // mono_averagine_select may already sit further right
+          }
+        }
+        // B: only when A rejected nothing, the walk ended on a miss (< 5 steps, not a guard stop) and the mono is the
+        // walk's leftmost peak (mono_averagine_select may have moved it right).
+        const double leftmost_mz = v.nl > 0 ? v.left_mz[(size_t)(v.nl - 1)] : s.mz;
+        if (mono_pos_extend_ > 0.0 && acc == nl && v.nl < 5 && !v.guard_stop && mono == leftmost_mz)
+        {
+          f |= 8;
+          long bt = -1;
+          const double q = ratio(nl + 1, &bt);
+          if (q >= mono_pos_extend_ && q > 0.0 && bt >= 0) { mono = ms1[(size_t)bt].mz; f |= 16; }
+        }
+        pc.mono_mz = mono;
+        flag[(size_t)ii] = f; rej[(size_t)ii] = r;
+      }
+      for (size_t i = 0; i < pcs.size(); ++i)
+      {
+        const uint8_t f = flag[i];
+        mc_tot[0] += f & 1; mc_tot[1] += (f >> 1) & 1; mc_tot[6] += (f >> 2) & 1; mc_tot[3] += (f >> 3) & 1; mc_tot[4] += (f >> 4) & 1;
+        mc_tot[5] += (f >> 5) & 1; mc_tot[2] += rej[i];
+      }
+    }
+    String box = String(mono_pos_im_box_);
+    if (mono_pos_im_box_ <= 0.0)
+    {
+      char b[160];
+      if (envelope_scoring) std::snprintf(b, sizeof b, "auto");
+      else std::snprintf(b, sizeof b, "auto %.4f (3.5 x p90 %.4f of the +1-isotope 1/K0 gap, %zu of %zu brightest seeds)", v2_box,
+                         v2_p90, v2_nhit, v2_nb);
+      box = String(b);
+    }
+    const String cfg = "v2, min_ratio " + String(mono_pos_min_ratio_) + ", im_box " + box + ", extend "
+                       + String(mono_pos_extend_) + (mono_pos_iterate_ ? ", iterate" : ", leftmost step only") + ", at the final charge";
+    mono_check_stamp_ = (envelope_scoring ? String("n/a (charge:scoring envelope), ") : String("")) + cfg + ": " + String(mc_tot[1]) + " of "
+                        + String(mc_tot[0]) + " monos moved right, " + String(mc_tot[4]) + " of " + String(mc_tot[3]) + " moved left";
+    writeLogInfo_("[monocheck] " + cfg + ": " + String(mc_tot[0]) + " count walks with a leftward partner tested, " + String(mc_tot[2])
+                  + " steps rejected, " + String(mc_tot[1]) + " monoisotopes moved right (" + String(mc_tot[6]) + " back onto the seed); "
+                  + String(mc_tot[3]) + " walks tested for extension, " + String(mc_tot[4]) + " monoisotopes moved left (unclaimed); "
+                  + String(mc_tot[5]) + " walks read at the charge the IM veto gave them; claims unchanged"
+                  + (envelope_scoring ? " (charge:scoring envelope: not applied)" : ""));
+  }
+
   /// [soa2] The fragment RT gate field. 99.4% of scoring visits fail the RT gate, so `q` quantises RT into
   /// buckets never narrower than delta_rt and a 2-byte test precedes the unchanged exact one. The reject
   /// admits +/-2 buckets where +/-1 suffices in exact arithmetic: insurance against a floor() rounding
@@ -3176,6 +3588,200 @@ protected:
     }
   };
 
+  /// [foreign] One window's precursors, the candidate foreign envelopes of its spectra: every precursor whose mono
+  /// m/z lies in the window, with a finite apex RT and 1/K0 and a charge, sorted by apex RT (ties by index). Built
+  /// from the run's precursor list, not from the tile's owned subset, so it is the same in any tiling.
+  struct ForeignIdx_
+  {
+    const vector<Precursor_>* p = nullptr;
+    vector<double> rt;       ///< apex RT, ascending
+    vector<uint32_t> idx;    ///< into *p, in rt order
+    void build(const vector<Precursor_>& v, size_t lo, size_t hi)
+    {
+      p = &v;
+      vector<pair<double, uint32_t>> o;
+      o.reserve(hi > lo ? hi - lo : 0);
+      for (size_t i = lo; i < hi; ++i)
+        if (std::isfinite(v[i].rt) && std::isfinite(v[i].im) && v[i].charge > 0) o.emplace_back(v[i].rt, (uint32_t)i);
+      std::sort(o.begin(), o.end());
+      rt.resize(o.size()); idx.resize(o.size());
+      for (size_t i = 0; i < o.size(); ++i) { rt[i] = o[i].first; idx[i] = o[i].second; }
+    }
+  };
+
+  /// [foreign] assembly:foreign_precursor_weight: attenuate, among one precursor's admitted fragments, the residual
+  /// (unfragmented) envelopes of the OTHER precursors isolated with it -- apex within drt of this one's, 1/K0 within
+  /// foreign_dim_, neither a twin (mono within 0.01) nor this ion called again (either mono on the other's isotope
+  /// grid, up to 3 steps, within 30 ppm). A candidate's positions are mono + k ISO/z, k = 0..3; a position is present
+  /// when an admitted fragment lies within foreign_ppm_ of it. With at least foreign_min_iso_ positions present, those
+  /// fragments are multiplied by foreign_w_ (0 removes them) and their cap key is recomputed from the attenuated
+  /// IM-weighted apex (@p frag_ai). A fragment within 30 ppm of this precursor's own envelope (mono to M+3) neither
+  /// counts nor is touched: stripping the own isotopes lost 2.3 % of peptides (CHANGELOG). Returns the fragments
+  /// attenuated. @p resc: gate:anchor_rescue's rescued flags, parallel to @p frags when not empty, compacted with it.
+  size_t attenuateForeign_(const Precursor_& pc, double drt, const ForeignIdx_& fx, vector<pair<double, double>>& frags,
+                           vector<double>& frag_scores, vector<uint32_t>& frag_bin, vector<pair<int, int>>& frag_span,
+                           const vector<double>& frag_ai, vector<char>& resc) const
+  {
+    // The two own-ion tests take a wider tolerance than the envelope match: an ion's residual peaks scatter tens of
+    // ppm around the MS1 mono grid (HeLa_22: 31 % of the own-grid peaks within 60 ppm lie 20-60 ppm off), and with
+    // both tests at foreign_ppm_ (10) 15 % of the removed fragments sat 10-60 ppm off the precursor's own M..M+3
+    // (chance 0.06 %): the same ion called again with a mono just outside the sibling test took them.
+    const double ISO = 1.0033548, ppm = foreign_ppm_ * 1e-6, same = std::max(ppm, 30e-6);
+    auto& cnt = foreignCount_();
+    ++cnt[8];
+    auto on_grid = [&](double a, double b, int z) {                 // a within `same` of b + j ISO/z, |j| <= 3
+      for (int j = -3; j <= 3; ++j) if (std::fabs(a - (b + j * ISO / z)) <= a * same) return true;
+      return false; };
+    vector<const Precursor_*> cand;
+    long long n_skip = 0;                                            // added to the shared counter once per call
+    const size_t lo = std::lower_bound(fx.rt.begin(), fx.rt.end(), pc.rt - drt) - fx.rt.begin();
+    for (size_t j = lo; j < fx.rt.size() && fx.rt[j] <= pc.rt + drt; ++j)
+    {
+      const Precursor_& f = (*fx.p)[fx.idx[j]];
+      if (&f == &pc || std::fabs(f.rt - pc.rt) > drt || std::fabs(f.im - pc.im) > foreign_dim_) continue;
+      if (std::fabs(f.mono_mz - pc.mono_mz) < 0.01 || (pc.charge > 0 && on_grid(f.mono_mz, pc.mono_mz, pc.charge))
+          || on_grid(pc.mono_mz, f.mono_mz, f.charge)) { ++n_skip; continue; }
+      cand.push_back(&f);
+    }
+    if (n_skip) cnt[4] += n_skip;
+    if (cand.empty()) return 0;
+    ++cnt[0];
+    vector<uint32_t> om(frags.size());                               // the fragments by m/z, ties by index
+    for (size_t i = 0; i < om.size(); ++i) om[i] = (uint32_t)i;
+    std::sort(om.begin(), om.end(), [&](uint32_t a, uint32_t b) { return frags[a].first != frags[b].first ? frags[a].first < frags[b].first : a < b; });
+    auto own = [&](double mz) {
+      if (pc.charge <= 0) return false;
+      for (int k = 0; k <= 3; ++k) { const double m = pc.mono_mz + k * ISO / pc.charge; if (std::fabs(mz - m) <= m * same) return true; }
+      return false; };
+    vector<char> hit(frags.size(), 0);
+    vector<uint32_t> at;
+    long long n_env = 0, n_match = 0, err = 0;
+    for (const Precursor_* f : cand)
+    {
+      at.clear();
+      int present = 0; long long e = 0;
+      for (int k = 0; k <= 3; ++k)
+      {
+        const double m = f->mono_mz + k * ISO / f->charge, tol = m * ppm;
+        bool any = false;
+        auto it = std::lower_bound(om.begin(), om.end(), m - tol, [&](uint32_t i, double v) { return frags[i].first < v; });
+        for (; it != om.end() && frags[*it].first <= m + tol; ++it)
+          if (!own(frags[*it].first)) { at.push_back(*it); e += std::llround((frags[*it].first - m) / m * 1e9); any = true; }
+        present += any;
+      }
+      if (present < foreign_min_iso_) continue;
+      ++n_env; n_match += (long long)at.size(); err += e;
+      for (uint32_t i : at) hit[i] = 1;
+    }
+    size_t n = 0;
+    for (size_t i = 0; i < hit.size(); ++i)
+    {
+      if (!hit[i]) continue;
+      ++n;
+      if (foreign_w_ <= 0.0) continue;
+      frags[i].second *= foreign_w_;
+      const double L = std::log1p(frag_ai[i]);                       // corr_inten keys are linear in it, the others in its log
+      frag_scores[i] = cap_rank_ == 0 ? frag_scores[i] * foreign_w_ : L > 0.0 ? frag_scores[i] * std::log1p(frag_ai[i] * foreign_w_) / L : frag_scores[i];
+    }
+    if (n && foreign_w_ <= 0.0)                                      // remove: compact every parallel array
+    {
+      size_t w = 0;
+      for (size_t i = 0; i < hit.size(); ++i)
+        if (!hit[i]) { frags[w] = frags[i]; frag_scores[w] = frag_scores[i]; frag_bin[w] = frag_bin[i]; frag_span[w] = frag_span[i]; if (!resc.empty()) resc[w] = resc[i]; ++w; }
+      frags.resize(w); frag_scores.resize(w); frag_bin.resize(w); frag_span.resize(w);
+      if (!resc.empty()) resc.resize(w);
+    }
+    cnt[1] += n_env; cnt[3] += (long long)n; cnt[6] += err; cnt[7] += n_match;
+    if (n) ++cnt[2];
+    return n;
+  }
+
+  /// [fuse] assembly:fragment_fuse_ppm: one peak per fragment ion. The IM picker keeps 1-2 flight-time bins of an ion
+  /// that spans 4-7, so one ion becomes several traces and several peaks 5-20 ppm apart; the same-bin merge reaches only
+  /// exact bins. Groups the fragments within @p ppm (anchored: strongest first, each unfused fragment an anchor taking
+  /// every unfused one within ppm of its own m/z; @p linkage: m/z order, joined to the previous member within ppm and to
+  /// the group's first within 2 ppm). A fused peak: m/z = intensity-weighted mean of the members' (emitted) intensities,
+  /// intensity = their sum, key = their best key, rescued flag = the strongest member's. It sits at its members' lowest
+  /// index, so the relative order of the peaks is kept; a lone fragment is kept bit for bit. @p keys and @p resc (when not
+  /// empty) are parallel to @p frags and compacted with it. Deterministic: every order has a total tie-break and the sums
+  /// run in m/z order. Returns the groups of >= 2 fused and adds their members to @p n_members.
+  static long long fuseFragments_(vector<pair<double, double>>& frags, vector<double>& keys, vector<char>& resc,
+                                  double ppm, bool linkage, long long& n_members)
+  {
+    const size_t n = frags.size();
+    if (n < 2 || !(ppm > 0.0)) return 0;
+    const double tol = ppm * 1e-6;
+    constexpr uint32_t NONE = std::numeric_limits<uint32_t>::max();
+    vector<uint32_t> om(n);                                          // by m/z, ties by index
+    for (size_t i = 0; i < n; ++i) om[i] = (uint32_t)i;
+    std::sort(om.begin(), om.end(), [&](uint32_t a, uint32_t b) { return frags[a].first != frags[b].first ? frags[a].first < frags[b].first : a < b; });
+    vector<uint32_t> grp(n, NONE);
+    uint32_t ng = 0;
+    if (linkage)
+    {
+      size_t s = 0;                                                  // the current group's first member in om
+      for (size_t k = 0; k < n; ++k)
+      {
+        if (k > 0)
+        {
+          const double m = frags[om[k]].first, mp = frags[om[k - 1]].first, ms = frags[om[s]].first;
+          if (!(m - mp <= mp * tol && m - ms <= 2.0 * ms * tol)) { ++ng; s = k; }
+        }
+        grp[om[k]] = ng;
+      }
+      ++ng;
+    }
+    else
+    {
+      vector<uint32_t> oi(om);                                       // by intensity desc, then m/z asc, then index
+      std::sort(oi.begin(), oi.end(), [&](uint32_t a, uint32_t b) {
+        if (frags[a].second != frags[b].second) return frags[a].second > frags[b].second;
+        if (frags[a].first != frags[b].first) return frags[a].first < frags[b].first;
+        return a < b;
+      });
+      for (uint32_t a : oi)
+      {
+        if (grp[a] != NONE) continue;
+        const double m = frags[a].first, d = m * tol;
+        auto it = std::lower_bound(om.begin(), om.end(), m - d, [&](uint32_t i, double v) { return frags[i].first < v; });
+        for (; it != om.end() && frags[*it].first <= m + d; ++it) if (grp[*it] == NONE) grp[*it] = ng;
+        ++ng;
+      }
+    }
+    if (ng == n) return 0;                                           // nothing within ppm: unchanged
+    struct Acc { double w = 0.0, wmz = 0.0, key = -std::numeric_limits<double>::infinity(); uint32_t head = NONE, top = NONE, n = 0; };
+    vector<Acc> acc(ng);
+    for (uint32_t i : om)                                            // m/z order: a fixed summation order
+    {
+      Acc& g = acc[grp[i]];
+      g.w += frags[i].second; g.wmz += frags[i].second * frags[i].first;
+      g.key = std::max(g.key, keys[i]);
+      g.head = std::min(g.head, i);
+      if (g.top == NONE || frags[i].second > frags[g.top].second) g.top = i;   // the strongest; ties: lower m/z
+      ++g.n;
+    }
+    long long groups = 0;
+    size_t w = 0;
+    for (size_t i = 0; i < n; ++i)                                   // write position w <= i <= every unread member
+    {
+      const Acc& g = acc[grp[i]];
+      if (g.head != i) continue;
+      if (g.n == 1) { frags[w] = frags[i]; keys[w] = keys[i]; if (!resc.empty()) resc[w] = resc[i]; }
+      else
+      {
+        const double mz = g.w > 0.0 ? g.wmz / g.w : frags[g.top].first;
+        const char r = resc.empty() ? 0 : resc[g.top];
+        frags[w] = {mz, g.w}; keys[w] = g.key;
+        if (!resc.empty()) resc[w] = r;
+        ++groups; n_members += g.n;
+      }
+      ++w;
+    }
+    frags.resize(w); keys.resize(w);
+    if (!resc.empty()) resc.resize(w);
+    return groups;
+  }
+
   /// Per-precursor assembly: this precursor claims every fragment passing its gate (a fragment may
   /// be shared across precursors -> chimeric). Leaves @p out empty on failure.
   /// pdense is caller-owned scratch, so the caller decides the per-thread copy. Keeps the top max_frags
@@ -3185,10 +3791,12 @@ protected:
                     const FragRt& frag_rt,
                     const vector<Trace>& ms1_traces, const TraceStore& ms1st, const FragStats& fg,
                     double delta_im, double delta_rt, double min_corr, int min_corr_pts,
-                    Size min_frags, Size max_frags, vector<float>& pdense, MSSpectrum& out) const
+                    Size min_frags, Size max_frags, vector<float>& pdense, MSSpectrum& out,
+                    const ForeignIdx_* fx = nullptr) const
   {
     vector<pair<double, double>> frags;
     vector<double> frag_scores;
+    vector<double> frag_ai;      // [foreign] each fragment's IM-weighted apex, its cap key's intensity (only with fx)
     vector<uint32_t> frag_bin;   // [merge] the TOF bin of each fragment (0: OpenMS detector, no bin; a real bin 0, m/z just
                                  // below the usual 100 m/z floor, is compared by exact m/z like the OpenMS path)
     vector<pair<int, int>> frag_span;   // [merge] its detected window-frame span
@@ -3219,6 +3827,34 @@ protected:
       p_lo = std::min(p_lo, gi); p_hi = std::max(p_hi, gi);
       if (p_apex < 0 || pdense[gi] > pdense[p_apex]) p_apex = gi;
     }
+    // [fragint] the frames a fragment's amplitude is summed over: core, the K frames centred on the precursor apex
+    // (ties to the earlier frame); sum, the precursor's span with its gaps: a faint MS1 trace has missing points and the
+    // concentric gate keeps fragments with no point where pdense != 0 (summed only there, 29% of HeLa 10 ng's had none)
+    int fint_apex = -1, fint_lo = 0, fint_hi = -1;
+    long long n_fint = 0, n_fint_fb = 0;
+    if (frag_int_ != 0)
+    {
+      for (int gi : touched) if (fint_apex < 0 || pdense[gi] > pdense[fint_apex] || (pdense[gi] == pdense[fint_apex] && gi < fint_apex)) fint_apex = gi;
+      fint_lo = frag_int_ == 1 ? fint_apex - frag_core_half_ : p_lo;
+      fint_hi = frag_int_ == 1 ? fint_apex + frag_core_half_ : p_hi;
+    }
+    auto fintAmp = [&](const Trace& f, double dim)                     // [fragint] a gate-passing or rescued fragment's amplitude
+    {
+      const int f0 = (int)f.frame0, f1 = f0 + (int)f.span() - 1;
+      double b = 0.0;                                                  // the same frames for every fragment of this precursor
+      for (int g = std::max(fint_lo, f0); g <= std::min(fint_hi, f1); ++g) b += xv(wst, f, (size_t)(g - f0));
+      if (!(b > 0.0))                                                  // no point there: the point nearest the precursor apex (ties earlier),
+      {                                                                // so the peak set stays the apex mode's and no peak is written at 0
+        int kb = -1;
+        for (int k = 0; k < (int)f.span(); ++k)
+          if (real(wst, f, (size_t)k) && (kb < 0 || std::abs(f0 + k - fint_apex) < std::abs(f0 + kb - fint_apex))) kb = k;
+        if (kb >= 0) b = xv(wst, f, (size_t)kb);
+        ++n_fint_fb;
+      }
+      if (im_weight_sigma_ > 0.0) b *= std::exp(-(dim * dim) / (2.0 * im_weight_sigma_ * im_weight_sigma_));
+      ++n_fint;
+      return b;
+    };
     // [adaptive] with gate:adaptive faint, the relaxed modes apply only to faint precursors (short precursor traces)
     const bool faint = adaptive_ && (int)touched.size() <= faint_frames_, all_p = !adaptive_ || faint;
     { const size_t n = touched.size(); pspanHist_()[n <= 4 ? (n ? n - 1 : 0) : n <= 6 ? 4 : n <= 10 ? 5 : n <= 20 ? 6 : 7]++; if (faint) pspanHist_()[8]++; }
@@ -3227,6 +3863,13 @@ protected:
     const double p_ctr = 0.5 * (p_lo + p_hi), p_half = 0.5 * (p_hi - p_lo);
     double pmean = psum / G, pvar = psumsq - G * pmean * pmean;
     double pinv = pvar > 0 ? 1.0 / sqrt(pvar) : 0.0;
+    // [anchor] gate:anchor_rescue, well-sampled precursors (signal in more than gate:faint_max_frames window frames, the
+    // faint test of gate:adaptive, whatever that mode is set to): the accepted fragments that can anchor a consensus, and
+    // the ones the gate rejected only for support (point or overlap floor) or by the correlation cut, with at least 2 points
+    const bool g_anchor = anchor_rescue_ && (int)touched.size() > faint_frames_;
+    vector<uint32_t> anchors, resc_fi;                                  // resc_fi: the rescued indices, sorted, for the gate dump
+    vector<size_t> cands;                                               // cands: index << 2 | rejection (0 points, 1 overlap, 2 corr)
+    vector<char> resc;                                                  // [anchor] 1 = rescued, parallel to frags (empty: none)
     if (pinv > 0.0)
     {
       size_t lo = lower_bound(frag_im.begin(), frag_im.end(), pc.im - delta_im) - frag_im.begin();
@@ -3246,7 +3889,8 @@ protected:
         // min_corr_pts can never pass the overlap guard below: skip it before the dot product.
         // Output-identical by construction (the guard's continue is the only thing it would reach).
         const bool short_np = f.np() < (size_t)std::max(min_corr_pts, 0);
-        if (short_np && !g_conc && !(g_shrink && (int)f.np() >= shrink_min_pts_)) continue;
+        if (short_np && !g_conc && !(g_shrink && (int)f.np() >= shrink_min_pts_))
+        { if (g_anchor && f.np() >= 2) cands.push_back(fi << 2); continue; }
         int f_lo = -1, f_hi = -1, f_apex = -1;                         // [short]/[coloc] the fragment's detected span and apex
         float f_max = 0.0f;
         // two sequential streams: the fragment's span in the arena and pdense over window frames
@@ -3279,7 +3923,8 @@ protected:
         }
         else
         {
-          if (overlap < (g_shrink ? shrink_min_pts_ : min_corr_pts)) continue;   // overlap guard [H-4]; [shrink] its own floor
+          if (overlap < (g_shrink ? shrink_min_pts_ : min_corr_pts))    // overlap guard [H-4]; [shrink] its own floor
+          { if (g_anchor && f.np() >= 2) cands.push_back(fi << 2 | 1u); continue; }
           // [B0] Plain Pearson takes variance over the full grid G, so a sparse fragment is scored against ~G
           // implicit zeros. gate:variance_support uses the union support instead; gate:coelution=logoverlap is
           // the AlphaDIA-style log-space profile overlap, summed where the precursor has signal, in [0,1].
@@ -3320,22 +3965,124 @@ protected:
             const double t2 = shrink_sd_ * shrink_sd_, mu = std::atanh(std::max(-0.999, std::min(0.999, shrink_r0_)));
             c = std::tanh((z / s2 + mu / t2) / (1.0 / s2 + 1.0 / t2));
           }
-          if (!(c >= min_corr)) continue;                                // correlation gate (a NaN score is rejected too)
+          if (!(c >= min_corr))                                          // correlation gate (a NaN score is rejected too)
+          { if (g_anchor && f.np() >= 2) cands.push_back(fi << 2 | 2u); continue; }
         }
         // [E5] The IM weight feeds both the cap key and the emitted intensity; corr^corr_power feeds only the emitted one.
         double inten = intensityOf(wst, f);
         const double dim = frag_im[fi] - pc.im;
         if (im_weight_sigma_ > 0.0) inten *= std::exp(-(dim * dim) / (2.0 * im_weight_sigma_ * im_weight_sigma_));
         double emit_inten = inten;
+        if (frag_int_ != 0) emit_inten = fintAmp(f, dim);               // [fragint] base amplitude summed over frames; the cap key keeps the apex
         if (g_cp > 0.0 && c > 0.0) emit_inten *= std::pow(c, g_cp);
         frags.emplace_back(exportMz_(f.tof, bOf(wst, f), f.mz), emit_inten);
         frag_bin.push_back(f.tof);
         frag_span.emplace_back(f_lo, f_hi);
+        if (fx) frag_ai.push_back(inten);
         frag_scores.push_back(cap_rank_ == 1 ? std::max(c_raw, 0.0) * std::max(c_raw, 0.0) * std::log1p(inten)
                             : cap_rank_ == 2 ? std::max(c_raw, 0.0) * std::log1p(inten) * (1.0 + overlap)
                             : c * inten);                              // [cap] the max_fragments ranking key
+        if (g_anchor && c >= anchor_min_corr_) anchors.push_back((uint32_t)fi);   // [anchor] a well-correlated accepted fragment
+      }
+      // [anchor] gate:anchor_rescue. A weak fragment of a strong precursor is a 2-3 point tip that fails the plain gate's
+      // point floor or its full-grid Pearson, while the precursor's well-correlated fragments (the anchors) outline the
+      // elution peak. Their profiles, each at unit maximum, are summed into a consensus over the window frames; a candidate
+      // joins when its apex is within one cycle of the consensus apex and its own points follow the consensus (local
+      // Pearson; with two points: both in the core, >= half the consensus maximum, and in its direction, scored at the
+      // threshold like a borderline fragment). The score, capped at anchor_min_corr, weighs it like any other fragment, and
+      // its cap key counts the frames it shares with the precursor, as every other fragment's does.
+      // Deterministic: anchors and candidates come in index order, the budget sorts by (score, m/z, index).
+      if (g_anchor)
+      {
+        auto& ac = anchorCount_();
+        ++ac[0];
+        if ((int)anchors.size() >= anchor_min_count_)
+        {
+          ++ac[1]; ac[2] += (long long)cands.size();
+          int c_lo = std::numeric_limits<int>::max(), c_hi = -1;
+          for (uint32_t ai : anchors)
+          { const Trace& a = frag_traces[ai]; c_lo = std::min(c_lo, (int)a.frame0); c_hi = std::max(c_hi, (int)(a.frame0 + a.span()) - 1); }
+          vector<double> cons((size_t)(c_hi - c_lo + 1), 0.0);
+          for (uint32_t ai : anchors)
+          {
+            const Trace& a = frag_traces[ai];
+            float amax = 0.0f;
+            for (size_t k = 0; k < a.span(); ++k) amax = std::max(amax, xv(wst, a, k));
+            if (!(amax > 0.0f)) continue;
+            for (size_t k = 0; k < a.span(); ++k) cons[a.frame0 + k - (size_t)c_lo] += (double)xv(wst, a, k) / amax;
+          }
+          size_t ca = 0;
+          for (size_t j = 1; j < cons.size(); ++j) if (cons[j] > cons[ca]) ca = j;   // the consensus apex (first maximum)
+          const int c_apex = c_lo + (int)ca;
+          const double core = 0.5 * cons[ca];
+          struct Resc { double r, mz; uint32_t fi; int why, ov, t_lo, t_hi; };
+          vector<Resc> rs;
+          for (size_t cw : cands)
+          {
+            const uint32_t fi = (uint32_t)(cw >> 2);
+            const Trace& f = frag_traces[fi];
+            if (std::abs((int)(f.frame0 + f.apex) - c_apex) > 1) continue;   // the raw apex, within one cycle
+            // sums shifted by the first point, so a constant profile has exactly zero variance
+            double sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0, x0 = 0, y0 = 0, dx1 = 0, dy1 = 0;
+            int n = 0, ov = 0, t_lo = -1, t_hi = -1;
+            bool in_core = true;
+            for (size_t k = 0; k < f.span(); ++k)
+            {
+              const double x = xv(wst, f, k); if (x <= 0.0) continue;
+              const int g = (int)(f.frame0 + k);
+              const double y = g < c_lo || g > c_hi ? 0.0 : cons[(size_t)(g - c_lo)];
+              if (t_lo < 0) { t_lo = g; x0 = x; y0 = y; }
+              t_hi = g;
+              if (pdense[g] != 0.0f) ++ov;                               // shared with the precursor (pdense is still live)
+              if (y < core) in_core = false;
+              const double dx = x - x0, dy = y - y0;
+              if (n == 1) { dx1 = dx; dy1 = dy; }
+              sx += dx; sy += dy; sxx += dx * dx; syy += dy * dy; sxy += dx * dy; ++n;
+            }
+            double r = -1.0;
+            if (n == 2) { if (in_core && dx1 * dy1 > 0.0) r = anchor_rescue_corr_; }
+            else if (n > 2)
+            {
+              const double vx = sxx - sx * sx / n, vy = syy - sy * sy / n;
+              if (vx > 0.0 && vy > 0.0) r = (sxy - sx * sy / n) / std::sqrt(vx * vy);
+            }
+            if (!(r >= anchor_rescue_corr_)) continue;
+            rs.push_back({r, exportMz_(f.tof, bOf(wst, f), f.mz), fi, (int)(cw & 3), ov, t_lo, t_hi});
+          }
+          std::sort(rs.begin(), rs.end(), [](const Resc& a, const Resc& b) {
+            if (a.r != b.r) return a.r > b.r;
+            if (a.mz != b.mz) return a.mz < b.mz;
+            return a.fi < b.fi;
+          });
+          const size_t nk = std::min(rs.size(), (size_t)anchor_max_rescued_);
+          ac[4] += (long long)(rs.size() - nk);
+          if (nk) { ac[3] += (long long)nk; ++ac[5]; resc.assign(frags.size(), 0); }
+          long long n_why[3] = {0, 0, 0};
+          for (size_t j = 0; j < nk; ++j)
+          {
+            const Resc& q = rs[j];
+            const Trace& f = frag_traces[q.fi];
+            const double c = std::min(q.r, anchor_min_corr_);
+            double inten = intensityOf(wst, f);                          // as above: IM weight, then c^corr_power
+            const double dim = frag_im[q.fi] - pc.im;
+            if (im_weight_sigma_ > 0.0) inten *= std::exp(-(dim * dim) / (2.0 * im_weight_sigma_ * im_weight_sigma_));
+            double emit_inten = frag_int_ != 0 ? fintAmp(f, dim) : inten;  // [fragint] the same amplitude as a gate-passing fragment
+            if (g_cp > 0.0 && c > 0.0) emit_inten *= std::pow(c, g_cp);
+            frags.emplace_back(q.mz, emit_inten);
+            frag_bin.push_back(f.tof);
+            frag_span.emplace_back(q.t_lo, q.t_hi);
+            if (fx) frag_ai.push_back(inten);                            // [foreign] parallel to frags, as above
+            frag_scores.push_back(cap_rank_ == 1 ? c * c * std::log1p(inten) : cap_rank_ == 2 ? c * std::log1p(inten) * (1.0 + q.ov) : c * inten);
+            resc.push_back(1);
+            resc_fi.push_back(q.fi);
+            ++n_why[q.why];
+          }
+          for (int w = 0; w < 3; ++w) if (n_why[w]) ac[8 + w] += n_why[w];
+          std::sort(resc_fi.begin(), resc_fi.end());
+        }
       }
     }
+    if (n_fint) { fragIntCount_()[0] += n_fint; fragIntCount_()[1] += n_fint_fb; }   // [fragint] once per precursor x window
     if (GateDump_& gd = GateDump_::get(); gd.on)                       // [gate-dump] read-only; before the reset
     {
       std::ostringstream rows;
@@ -3365,7 +4112,9 @@ protected:
             const float pv = pdense[f.frame0 + k]; if (pv != 0.0f) { dot += (double)pv * fv; ++overlap; } }
           const double c = fg.invnorm[fi] == 0.0 ? 0.0 : (dot - G * pmean * fg.mean[fi]) * pinv * fg.invnorm[fi];
           const char* fate = std::fabs(dim) > delta_im ? "im" : std::fabs(drt) > g_drt ? "rt" : fg.invnorm[fi] == 0.0 ? "degenerate"
-                           : std::fabs(f.mz - pc.mono_mz) < 0.01 ? "precursor_peak" : f.np() < (size_t)std::max(min_corr_pts, 0) ? "np"
+                           : std::fabs(f.mz - pc.mono_mz) < 0.01 ? "precursor_peak"
+                           : !resc_fi.empty() && std::binary_search(resc_fi.begin(), resc_fi.end(), (uint32_t)fi) ? "rescued"   // [anchor]
+                           : f.np() < (size_t)std::max(min_corr_pts, 0) ? "np"
                            : overlap < min_corr_pts ? "overlap" : c < min_corr ? "corr" : "kept";
           head(); rows << exportMz_(f.tof, bOf(wst, f), f.mz) << '\t' << dim << '\t' << drt << '\t' << f.np() << '\t' << overlap << '\t'
                        << c << '\t' << intensityOf(wst, f) << '\t' << fate << '\n';
@@ -3374,6 +4123,9 @@ protected:
       if (rows.tellp() > 0) { std::lock_guard<std::mutex> lk(gd.mu); gd.out << rows.str(); gd.out.flush(); }
     }
     for (int gi : touched) pdense[gi] = 0.0f;                          // reset scratch
+    // [foreign] other precursors' residual envelopes, before the merge and the cap: a removed fragment frees its slot
+    const size_t n_before = frags.size();                              // [foreign] for the fell-below count
+    const size_t n_foreign = fx && !frags.empty() ? attenuateForeign_(pc, g_drt, *fx, frags, frag_scores, frag_bin, frag_span, frag_ai, resc) : 0;
     // [merge] guard: one TOF bin is one m/z. What toTof's same-frame merge cannot reach (slices beyond its span, valley-
     // split children, band edges, tile carries) is merged here, before the cap, into the strongest member: members whose
     // RT span overlaps its span are summed (parallel slices of one ion), RT-disjoint pieces are dropped (the stronger
@@ -3406,6 +4158,7 @@ protected:
             if (k > g) gone[i] = 1;
           }
           frags[head] = {frags[top].first, sum}; frag_scores[head] = cap;
+          if (!resc.empty()) resc[head] = resc[top];                    // [anchor] rescued if its m/z is a rescued one's
           nm += (long long)(e - g - 1);
         }
         g = e;
@@ -3413,12 +4166,32 @@ protected:
       if (nm)
       {
         size_t w = 0;
-        for (size_t i = 0; i < frags.size(); ++i) if (!gone[i]) { frags[w] = frags[i]; frag_scores[w] = frag_scores[i]; ++w; }
+        for (size_t i = 0; i < frags.size(); ++i)
+          if (!gone[i]) { frags[w] = frags[i]; frag_scores[w] = frag_scores[i]; if (!resc.empty()) resc[w] = resc[i]; ++w; }
         frags.resize(w); frag_scores.resize(w);
+        if (!resc.empty()) resc.resize(w);
         mergeCount_()[2] += nm;
       }
     }
-    if (frags.size() < min_frags) return;
+    // [fuse] one peak per fragment ion, after the merge (frag_bin and frag_span are stale from here on) and before
+    // min_fragments and the cap: the cap ranks fused peaks, so the slots of an ion's pieces refill
+    const size_t n_merged = frags.size();                              // [foreign]/[fuse] the fell-below counts
+    if (fuse_ppm_ > 0.0 && n_merged > 0)
+    {
+      long long n_mem = 0;
+      const long long n_grp = fuseFragments_(frags, frag_scores, resc, fuse_ppm_, fuse_linkage_, n_mem);
+      auto& fc = fuseCount_();
+      ++fc[0]; fc[1] += (long long)n_merged; fc[2] += (long long)frags.size();
+      if (n_grp) { fc[3] += n_grp; fc[4] += n_mem; }
+      if (n_merged >= min_frags && frags.size() < min_frags) ++fc[5];
+    }
+    if (frags.size() < min_frags)
+    {   // [foreign] counted only when the removal (weight 0) took a spectrum that had enough fragments below the floor
+      if (n_foreign && foreign_w_ <= 0.0 && n_before >= min_frags && n_merged < min_frags) ++foreignCount_()[5];
+      return;
+    }
+    long long n_resc = 0;                                               // [anchor] rescued peaks in this spectrum
+    for (char r : resc) n_resc += r;
     if (frags.size() > max_frags)
     {
       vector<size_t> idx(frags.size());
@@ -3433,14 +4206,29 @@ protected:
       });
       vector<pair<double, double>> keep; keep.reserve(max_frags);
       for (size_t i = 0; i < max_frags; ++i) keep.push_back(frags[idx[i]]);
+      if (!resc.empty()) { n_resc = 0; for (size_t i = 0; i < max_frags; ++i) n_resc += resc[idx[i]]; }
       frags.swap(keep);
+      if (post_fusion_cap_)                                            // [recap] the kept peaks' keys, in the same order
+      {
+        vector<double> keep_k(max_frags);
+        for (size_t i = 0; i < max_frags; ++i) keep_k[i] = frag_scores[idx[i]];
+        frag_scores.swap(keep_k);
+      }
     }
+    if (n_resc) { anchorCount_()[6] += n_resc; ++anchorCount_()[7]; }
     out.setMSLevel(2);
     out.setType(SpectrumSettings::SpectrumType::CENTROID);
     out.setRT(pc.rt);
     // [mem] exact reserve: no doubling slack held from emit until the write.
     out.reserve(frags.size());
     for (const auto& fr : frags) out.emplace_back(fr.first, fr.second);
+    if (post_fusion_cap_)   // [recap] each peak's cap key rides along as a float data array (sorted with the peaks), dropped before the write
+    {
+      OpenMS::DataArrays::FloatDataArray k;
+      k.setName("spx_cap_key");
+      k.assign(frag_scores.begin(), frag_scores.end());
+      out.getFloatDataArrays().push_back(std::move(k));
+    }
     out.sortByPosition();
     OpenMS::Precursor prec;
     prec.setMZ(pc.mono_mz);   // MS1 traces come from the OpenMS detector: no bin to calibrate
@@ -3601,6 +4389,26 @@ protected:
       chk(v.size() == 1 && v[0].getRT() == 40.0 && q.getMZ() == 700.0 && q.getCharge() == 3 && q.getDriftTime() == 1.1
           && q.getIsolationWindowLowerOffset() == 7.0 && q.getIsolationWindowUpperOffset() == 18.0 && (int)v[0].getMetaValue("spx_guessed") == 0,
           "the survivor keeps its own RT, precursor, 1/K0, isolation offsets and userParams"); }
+    // [recap] the keyed fold (assembly:post_fusion_cap) and the cap after it
+    auto keyed = [](MSSpectrum s, const vector<float>& k) {
+      OpenMS::DataArrays::FloatDataArray a; a.setName("spx_cap_key"); a.assign(k.begin(), k.end()); s.getFloatDataArrays().push_back(std::move(a)); return s; };
+    { const vector<pair<double, float>> A{{100.0, 10.0f}, {200.0, 20.0f}}, B{{200.0005, 5.0f}, {300.0, 30.0f}};
+      vector<MSSpectrum> u{sp(10.0, 500.0, 2, 1.0, 2, A), sp(10.0, 500.001, 2, 1.0, 3, B)};
+      vector<MSSpectrum> v{keyed(sp(10.0, 500.0, 2, 1.0, 2, A), {1.0f, 2.0f}), keyed(sp(10.0, 500.001, 2, 1.0, 3, B), {7.0f, 0.5f})};
+      mergeTwins_(u, 0.005); mergeTwins_(v, 0.005, true);
+      bool same = u.size() == 1 && v.size() == 1 && u[0].size() == v[0].size();
+      for (Size i = 0; same && i < u[0].size(); ++i) same = u[0][i].getMZ() == v[0][i].getMZ() && u[0][i].getIntensity() == v[0][i].getIntensity();
+      chk(same, "keyed fold: the peaks of the unkeyed fold, bit for bit");
+      const auto& k = v[0].getFloatDataArrays();
+      chk(k.size() == 1 && k[0].size() == 3 && k[0][0] == 1.0f && k[0][1] == 7.0f && k[0][2] == 0.5f, "keyed fold: a fused peak keeps its members' max key");
+      const std::array<size_t, 3> r = capAfterFusion_(v, 2);
+      chk(r[0] == 1 && r[1] == 1 && r[2] == 3 && v[0].size() == 2 && v[0][0].getMZ() == 100.0 && v[0][1].getMZ() == u[0][1].getMZ()
+          && v[0].getFloatDataArrays().empty(), "post-fusion cap: the top keys survive in m/z order, the key array is dropped"); }
+    { vector<MSSpectrum> v{keyed(sp(10.0, 500.0, 2, 1.0, 2, {{100.0, 5.0f}, {200.0, 9.0f}, {300.0, 9.0f}}), {1.0f, 1.0f, 1.0f}),
+                           keyed(sp(12.0, 500.0, 2, 1.0, 2, {{100.0, 5.0f}}), {3.0f})};
+      const std::array<size_t, 3> r = capAfterFusion_(v, 1);
+      chk(r[0] == 1 && r[1] == 2 && v[0].size() == 1 && v[0][0].getMZ() == 200.0, "post-fusion cap ties: the higher intensity, then the lower m/z");
+      chk(v[1].size() == 1 && v[1][0].getMZ() == 100.0 && v[1].getFloatDataArrays().empty(), "post-fusion cap: a spectrum within the cap keeps its peaks, without the key array"); }
     writeLogInfo_(fail ? "[twins] SELFTEST FAILED" : "[twins] selftest passed");
     return fail ? UNEXPECTED_RESULT : EXECUTION_OK;
   }
@@ -3654,6 +4462,16 @@ protected:
     im_weight_sigma_ = getDoubleOption_("assembly:im_weight_sigma");
     mono_guard_ = getDoubleOption_("charge:mono_averagine_guard");
     mono_select_ = getFlag_("charge:mono_averagine_select");
+    {
+      const String mc = getStringOption_("charge:mono_profile_check");
+      mono_check_ = (mc == "true") ? 1 : (mc == "v2") ? 2 : 0;
+    }
+    mono_check_min_corr_ = getDoubleOption_("charge:mono_profile_min_corr");
+    mono_check_max_dim_ = getDoubleOption_("charge:mono_profile_max_dim");
+    mono_pos_min_ratio_ = getDoubleOption_("charge:mono_position_min_ratio");
+    mono_pos_im_box_ = getDoubleOption_("charge:mono_position_im_box");
+    mono_pos_extend_ = getDoubleOption_("charge:mono_position_extend");
+    mono_pos_iterate_ = getStringOption_("charge:mono_position_iterate") == "true";
     var_support_ = getFlag_("gate:variance_support");
     short_conc_ = (getStringOption_("gate:short_traces") == "concentric");
     short_center_tol_ = getDoubleOption_("gate:short_center_tol");
@@ -3670,9 +4488,25 @@ protected:
     cap_rank_ = getStringOption_("assembly:cap_rank") == "umpire" ? 1 : getStringOption_("assembly:cap_rank") == "evidence" ? 2 : 0;
     im_slice_merge_ = getDoubleOption_("trace:im_slice_merge");
     merge_same_bin_ = getStringOption_("assembly:merge_same_bin") == "true";
+    frag_int_ = getStringOption_("assembly:frag_intensity") == "core" ? 1 : getStringOption_("assembly:frag_intensity") == "sum" ? 2 : 0;
+    if (getIntOption_("assembly:frag_core_frames") % 2 == 0)
+      throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "assembly:frag_core_frames must be odd: the core is centred on the precursor's apex frame");
+    frag_core_half_ = getIntOption_("assembly:frag_core_frames") / 2;
+    post_fusion_cap_ = getStringOption_("assembly:post_fusion_cap") == "true";
+    foreign_w_ = getDoubleOption_("assembly:foreign_precursor_weight");
+    foreign_ppm_ = getDoubleOption_("assembly:foreign_precursor_ppm");
+    foreign_dim_ = getDoubleOption_("assembly:foreign_precursor_dim");
+    foreign_min_iso_ = getIntOption_("assembly:foreign_precursor_min_iso");
+    fuse_ppm_ = getDoubleOption_("assembly:fragment_fuse_ppm");
+    fuse_linkage_ = getStringOption_("assembly:fragment_fuse_mode") == "linkage";
     faint_frames_ = getIntOption_("gate:faint_max_frames");
     faint_drt_ = getDoubleOption_("gate:faint_delta_rt");
     faint_cp_ = getDoubleOption_("gate:faint_corr_power");
+    anchor_rescue_ = getStringOption_("gate:anchor_rescue") == "true";
+    anchor_min_count_ = getIntOption_("gate:anchor_min_count");
+    anchor_min_corr_ = getDoubleOption_("gate:anchor_min_corr");
+    anchor_rescue_corr_ = getDoubleOption_("gate:anchor_rescue_corr");
+    anchor_max_rescued_ = getIntOption_("gate:anchor_max_rescued");
     if (shrink_ && log_overlap_)
       throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "gate:shrinkage fisher needs a correlation: it does not apply to gate:coelution logoverlap");
     corr_power_ = getDoubleOption_("assembly:corr_power");
@@ -4265,8 +5099,9 @@ protected:
     }
     std::optional<Phase> win_phase;                            // [perf-instr] the window loop (function scope)
     double _t_inf = phase_clock_(), _c_inf = cpu_seconds_();   // [perf-instr]
+    vector<MonoV2In_> mono_v2in;   // [monocheck-v2] the count walks, parallel to `precursors` until monoPositionPass_
     vector<Precursor_> precursors = inferPrecursors_(ms1_traces, ms1_store, max_charge, delta_rt, iso_im_tol,
-                                                     mass_ppm, env_scoring);
+                                                     mass_ppm, env_scoring, mono_check_ == 2 ? &mono_v2in : nullptr);
     if (adaptive_auto_)   // [adaptive] auto: decide the run's gate from its precursor span distribution (MS1 points)
     {
       size_t nf = 0;
@@ -4336,6 +5171,13 @@ protected:
       }
       else writeLogInfo_("[im-veto] too few confident 2+ calls to fit a mobility line; no z=1 re-calls");
     }
+    // [monocheck-v2] At the final charge: after the veto (which reads the walks' own monoisotopes, as without v2),
+    // before the charge-less precursors are defaulted or dropped (the veto edits in place, so the order still matches).
+    if (mono_check_ == 2)
+    {
+      monoPositionPass_(ms1_traces, ms1_store, precursors, mono_v2in, delta_rt, iso_im_tol, mass_ppm, env_scoring);
+      vector<MonoV2In_>().swap(mono_v2in);
+    }
     const int default_charge = getIntOption_("assembly:default_charge");
     Size n_default = 0;
     // [way-4] A GUESSED charge and an isotope-SUPPORTED charge must not be emitted identically.
@@ -4695,13 +5537,32 @@ protected:
     out_exp.setMetaValue("spx:cap_rank", String(cap_rank_ == 2 ? "evidence" : cap_rank_ == 1 ? "umpire" : "corr_inten"));
     out_exp.setMetaValue("spx:same_bin_merge", String("im_slices ") + (!integer_detector ? String("n/a (openms detector)") : im_slice_merge_ >= 0.0 ? String(im_slice_merge_) + " (span " + String(2.0 * im_slice_merge_) + ")" : String("off"))
                          + ", assembly " + (merge_same_bin_ ? (integer_detector ? "on" : "on (exact m/z)") : "off"));
+    if (anchor_rescue_)   // [anchor] stamped only when on: the default header is unchanged
+      out_exp.setMetaValue("spx:anchor", String("anchors ") + String(anchor_min_count_) + " at r " + String(anchor_min_corr_) + ", rescue r "
+                                          + String(anchor_rescue_corr_) + ", max " + String(anchor_max_rescued_) + " per spectrum");
     out_exp.setMetaValue("spx:im_weight_sigma", im_weight_sigma_);
     // [dnoise] what was applied: the port, "off", or skipped because the input is no .d
     out_exp.setMetaValue("spx:dnoise_ms1", dnoise.on ? String(String(spx::dnoise::kPortedFrom) + " MS1") : String(dnoise_req ? "skipped (input is not a Bruker .d)" : "off"));
     out_exp.setMetaValue("spx:dnoise_ms1_params", dnoise.on ? dnoise.params() : String("none"));
     out_exp.setMetaValue("spx:dnoise_ms1_points", dnoise.on ? String("raw " + String(dnoise.total.raw) + " kept " + String(dnoise.total.kept)) : String("none"));
     out_exp.setMetaValue("spx:require_isotope_support", (int)require_iso);
+    if (mono_check_) out_exp.setMetaValue("spx:monocheck", mono_check_stamp_);   // [monocheck] only when on
+    if (post_fusion_cap_)   // [recap] only when on: the default header is unchanged
+      out_exp.setMetaValue("spx:post_fusion_cap", String("max_fragments ") + String(max_frags) + " after the twin fold, ranked by the "
+                           + (cap_rank_ == 2 ? "evidence" : cap_rank_ == 1 ? "umpire" : "corr_inten") + " cap key");
     out_exp.setMetaValue("spx:twin_merge", twin_im >= 0.0 ? String("same frame, same charge, 20 ppm, 1/K0 <= " + String(twin_im) + ", fused 10 ppm") : String("off"));
+    if (frag_int_ != 0)   // [fragint] stamped only when on: the default header is unchanged
+      out_exp.setMetaValue("spx:fragint", frag_int_ == 1 ? String("core ") + String(2 * frag_core_half_ + 1) + " frames" : String("sum"));
+    if (foreign_w_ < 1.0)   // [foreign] stamped only when on: the default header is unchanged
+      out_exp.setMetaValue("spx:foreign", String("weight " + String(foreign_w_) + ", " + String(foreign_ppm_) + " ppm, 1/K0 " + String(foreign_dim_)
+                                                 + ", min_iso " + String(foreign_min_iso_) + ", positions mono..M+3, own ion kept (30 ppm)"));
+    if (fuse_ppm_ > 0.0)   // [fuse] stamped only when on (on by default since rc-b; 0 leaves the 1.5.0 header)
+    {
+      String s = String(fuse_linkage_ ? "linkage " : "anchored ") + String(fuse_ppm_) + " ppm";
+      if (fuse_linkage_) s += String(" (group span <= ") + String(2.0 * fuse_ppm_) + " ppm)";
+      s += ", summed intensity, intensity-weighted m/z, best cap key; after the same-bin merge, before min_fragments and max_fragments";
+      out_exp.setMetaValue("spx:fragment_fuse", s);
+    }
     std::unique_ptr<TileWriter> writer;
     // written as `<out>.part` and renamed on completion: a tile that throws must not leave a
     // structurally valid file holding the earlier tiles only (review, step 2)
@@ -4710,6 +5571,7 @@ protected:
     vector<MSSpectrum> all_out;   // the bulk (mzPeak) path only
     Size n_out = 0;
     Size n_twins = 0;   // [twins] spectra folded into a twin, over every tile
+    std::array<size_t, 4> recap{};   // [recap] spectra re-capped, peaks removed, largest spectrum before, spectra seen
     writeLogInfo_("Processing " + String(n_win) + " isolation windows in " + String(tiles.size()) + " tile(s) from the " + (tile_source ? "streaming" : "resident") + " source (OpenMP over windows, <="
                   + String(n_conc) + " concurrent, admission bounded by " + String((int)(mem_frac * 100))
                   + "% of free RAM)..." + rss_() + mem_());
@@ -5142,6 +6004,9 @@ protected:
         LedCharge _frag(LC_FRAG, (long long)(frag_im.capacity() * 8 + frag_rt.rt.capacity() * 8 + frag_rt.q.capacity() * 2
                                              + fg.mean.capacity() * 8 + fg.invnorm.capacity() * 8));
         vector<float> pdense(wst.frames(), 0.0f);   // indexed by window-local frame
+        // [foreign] the window's precursors by apex RT, owned by this tile or not: the same candidates in any tiling
+        ForeignIdx_ fx;
+        if (foreign_w_ < 1.0) fx.build(precursors, plo, phi);
 
         vector<MSSpectrum>& bucket = win_out[wi];
         {
@@ -5179,9 +6044,10 @@ protected:
                 const Precursor_& pc = precursors[pidx[(size_t)j]];
                 MSSpectrum ms2;
                 assembleOne_(pc, win_lo, win_hi, frag_traces, wst, frag_im, frag_rt, ms1_traces, ms1_store, fg,
-                             gate_dim, delta_rt, min_corr, min_corr_pts, min_frags, max_frags, pdense, ms2);
+                             gate_dim, delta_rt, min_corr, min_corr_pts, min_frags, max_frags, pdense, ms2,
+                             foreign_w_ < 1.0 ? &fx : nullptr);
                 if (!ms2.empty())
-                { ledAdd_(LC_SPECTRA, (long long)(sizeof(MSSpectrum) + ms2.size() * 12)); pslot[(size_t)j] = std::move(ms2); }
+                { ledAdd_(LC_SPECTRA, (long long)(sizeof(MSSpectrum) + ms2.size() * (post_fusion_cap_ ? 16 : 12))); pslot[(size_t)j] = std::move(ms2); }   // [recap] +4 B/peak key
               }
             }
           } catch (...) { taskErr_(asm_err); } }
@@ -5279,15 +6145,21 @@ protected:
       { size_t n_tot = 0; for (const auto& bucket : win_out) n_tot += bucket.size(); tile_out.reserve(n_tot); }
       for (auto& bucket : win_out) { for (auto& s : bucket) tile_out.push_back(std::move(s)); bucket.clear(); bucket.shrink_to_fit(); }
       long long tile_spec_bytes = 0;
-      for (const auto& sp : tile_out) tile_spec_bytes += (long long)(sizeof(MSSpectrum) + sp.size() * 12);
+      for (const auto& sp : tile_out) tile_spec_bytes += (long long)(sizeof(MSSpectrum) + sp.size() * (post_fusion_cap_ ? 16 : 12));   // as charged at emission
       { Phase _ph("SORT(canonical)"); canonicalSort_(tile_out); }
       if (twin_im >= 0.0)
       {
         Phase _ph("MERGE(twins)");
-        const size_t before = tile_out.size(), gone = mergeTwins_(tile_out, twin_im);
+        const size_t before = tile_out.size(), gone = mergeTwins_(tile_out, twin_im, post_fusion_cap_);
         n_twins += gone;
         writeLogInfo_("[twins] tile " + String(tk + 1) + "/" + String(tiles.size()) + ": " + String(gone) + " of " + String(before) + " spectra folded into a twin");
       }
+      if (post_fusion_cap_)
+      {
+        Phase _ph("RECAP(post-fusion)");
+        const std::array<size_t, 3> r = capAfterFusion_(tile_out, max_frags);
+        recap[0] += r[0]; recap[1] += r[1]; recap[2] = std::max(recap[2], r[2]); recap[3] += tile_out.size();
+      }
       if (writer)
       {
         for (auto& sp : tile_out) sp.getDataProcessing().push_back(out_dp);   // ONE entry, by pointer, for every spectrum
@@ -5353,18 +6225,60 @@ protected:
     writeLogInfo_("Wrote " + String(n_out) + " pseudo-MS2 spectra to " + out
                   + " (" + String(FileTypes::typeToName(out_type)) + ")");
     if (twin_im >= 0.0) writeLogInfo_("[twins] " + String(n_twins) + " spectra folded into a twin (assembly:twin_im_tolerance " + String(twin_im) + ")");
+    if (post_fusion_cap_)
+      writeLogInfo_("[recap] assembly:post_fusion_cap: " + String(recap[0]) + " of " + String(recap[3]) + " spectra re-capped to " + String(max_frags)
+                    + " peaks after the twin fold, " + String(recap[1]) + " peaks removed (largest spectrum before: " + String(recap[2]) + " peaks)");
     {   // [merge] how much splitting the two merges removed
       auto& m = mergeCount_();
       writeLogInfo_("[merge] im-slice merge (trace:im_slice_merge " + (!integer_detector ? String("n/a, openms detector") : im_slice_merge_ >= 0.0 ? String(im_slice_merge_) : String("off")) + "): " + String(m[0].load())
                     + " picked MS2 peaks merged away in " + String(m[1].load()) + " frames; assembly same-bin merge (" + (merge_same_bin_ ? "on" : "off") + "): "
                     + String(m[2].load()) + " fragments merged away");
     }
+    if (frag_int_ != 0)   // [fragint] what the fragment-intensity mode did (gate-passing and rescued fragments, before the merge and the cap)
+      writeLogInfo_("[fragint] assembly:frag_intensity " + (frag_int_ == 1 ? "core (" + String(2 * frag_core_half_ + 1) + " frames around the precursor apex)" : String("sum (the precursor's span)"))
+                    + ": " + String(fragIntCount_()[0].load()) + " fragments took the summed amplitude, " + String(fragIntCount_()[1].load())
+                    + " of them had no point there and took their point nearest the precursor apex");
+    if (foreign_w_ < 1.0)
+    {   // [foreign] what assembly:foreign_precursor_weight did
+      auto& c = foreignCount_();
+      const long long nm = c[7].load();
+      writeLogInfo_("[foreign] assembly:foreign_precursor_weight " + String(foreign_w_) + " (" + String(foreign_ppm_) + " ppm, 1/K0 " + String(foreign_dim_)
+                    + ", min_iso " + String(foreign_min_iso_) + "): of " + String(c[8].load()) + " precursor-window assemblies with fragments, "
+                    + String(c[0].load()) + " had a foreign candidate (" + String(c[4].load()) + " candidates skipped as the precursor's own ion); "
+                    + String(c[1].load()) + " foreign envelopes matched; "
+                    + String(c[3].load()) + " fragments " + (foreign_w_ > 0.0 ? "attenuated" : "removed") + " in " + String(c[2].load()) + " assemblies, "
+                    + String(c[5].load()) + " of which then fell below assembly:min_fragments; mean m/z error of the " + String(nm)
+                    + " matches " + String(nm ? (double)c[6].load() / 1000.0 / (double)nm : 0.0, false) + " ppm");
+    }
+    if (fuse_ppm_ > 0.0)
+    {   // [fuse] what assembly:fragment_fuse_ppm did (per precursor-window assembly, before min_fragments and the cap)
+      auto& c = fuseCount_();
+      const long long g = c[3].load();
+      writeLogInfo_("[fuse] assembly:fragment_fuse_ppm " + String(fuse_ppm_) + " (" + (fuse_linkage_ ? "linkage" : "anchored") + "): "
+                    + String(c[1].load()) + " fragments in, " + String(c[2].load()) + " peaks out, in " + String(c[0].load())
+                    + " precursor-window assemblies; " + String(g) + " groups of >= 2 fused, mean size "
+                    + String(g ? (double)c[4].load() / (double)g : 0.0, false) + "; " + String(c[5].load())
+                    + " assemblies fell below assembly:min_fragments");
+    }
     {   // [pspan] the precursor MS1-span histogram, for choosing gate:faint_max_frames per data set
       auto& h = pspanHist_(); long long tot = 0; for (int i = 0; i < 8; ++i) tot += h[i].load();
       writeLogInfo_("[pspan] precursors by MS1 span (window frames): 1:" + String(h[0].load()) + " 2:" + String(h[1].load()) + " 3:" + String(h[2].load())
                     + " 4:" + String(h[3].load()) + " 5-6:" + String(h[4].load()) + " 7-10:" + String(h[5].load()) + " 11-20:" + String(h[6].load())
                     + " >20:" + String(h[7].load()) + " total " + String(tot) + (adaptive_ ? " faint(<=" + String(faint_frames_) + "): " + String(h[8].load()) : String("")));
     }
+    if (anchor_rescue_)
+    {   // [anchor] what the rescue did (counted at assembly: before the twin fold)
+      auto& a = anchorCount_();
+      char b[640];
+      snprintf(b, sizeof b, "[anchor] %lld of %lld non-faint precursors anchored (>= %d fragments at r >= %g), %lld candidates; %lld fragments "
+                            "rescued (r >= %g; rejected at the point floor %lld, overlap guard %lld, correlation cut %lld) in %lld precursors, "
+                            "%.2f per anchored precursor, %lld more beyond %d per spectrum; %lld rescued peaks in %lld written spectra after the "
+                            "same-bin merge and the cap (%.2f per such spectrum)",
+               a[1].load(), a[0].load(), anchor_min_count_, anchor_min_corr_, a[2].load(), a[3].load(), anchor_rescue_corr_, a[8].load(),
+               a[9].load(), a[10].load(), a[5].load(), a[1].load() ? (double)a[3].load() / a[1].load() : 0.0, a[4].load(),
+               anchor_max_rescued_, a[6].load(), a[7].load(), a[7].load() ? (double)a[6].load() / a[7].load() : 0.0);
+      writeLogInfo_(b);
+    }
     report_phases_(phase_clock_());
     return EXECUTION_OK;
   }
```

## Section C: unchanged context the diff depends on (b2185db, with line numbers)

### taskErr_ (exception hand-off from tasks) (src/diaspextract.cpp lines 115-122 at b2185db)

```cpp
  115    inline int& phase_depth_() { static int d = 0; return d; }
  116    inline double& flush_wall_() { static double v = 0; return v; }   // [perf-load] pick inside LOAD
  117    /// [task-err] An exception escaping an OpenMP task terminates the process with no message. Task bodies catch
  118    /// everything and hand the first exception here; the code after the loop rethrows it once the tasks have joined.
  119    inline void taskErr_(std::exception_ptr& first)
  120    {
  121      #pragma omp critical(task_err)
  122      if (!first) first = std::current_exception();
```

### canonicalSort_ and mergeTwins_ (the twin fold, complete) (src/diaspextract.cpp lines 2108-2286 at b2185db)

```cpp
 2108    /// Tiles are RT-disjoint and RT is the first key, so per-tile sorted blocks concatenate to the
 2109    /// order one sort of everything gives.
 2110    static void canonicalSort_(vector<MSSpectrum>& v)
 2111    {
 2112      struct SortKey { double rt, mz; int charge; uint32_t n, idx; };
 2113      vector<SortKey> keys(v.size());
 2114  #pragma omp parallel for schedule(static)
 2115      for (long i = 0; i < (long)v.size(); ++i)
 2116      {
 2117        const MSSpectrum& a = v[i];
 2118        keys[i].rt = a.getRT();
 2119        keys[i].mz = a.getPrecursors().empty() ? 0.0 : a.getPrecursors()[0].getMZ();
 2120        keys[i].charge = a.getPrecursors().empty() ? 0 : a.getPrecursors()[0].getCharge();
 2121        keys[i].n = (uint32_t)a.size();
 2122        keys[i].idx = (uint32_t)i;
 2123      }
 2124      sort(keys.begin(), keys.end(), [&v](const SortKey& ka, const SortKey& kb) {
 2125        if (ka.rt != kb.rt) return ka.rt < kb.rt;
 2126        if (ka.mz != kb.mz) return ka.mz < kb.mz;
 2127        if (ka.charge != kb.charge) return ka.charge < kb.charge;
 2128        // fragment-sequence tiebreaks so equal-precursor spectra have a canonical order
 2129        if (ka.n != kb.n) return ka.n < kb.n;
 2130        const MSSpectrum& a = v[ka.idx];
 2131        const MSSpectrum& b = v[kb.idx];
 2132        for (Size i = 0; i < a.size(); ++i)
 2133        {
 2134          if (a[i].getMZ() != b[i].getMZ()) return a[i].getMZ() < b[i].getMZ();
 2135          if (a[i].getIntensity() != b[i].getIntensity()) return a[i].getIntensity() < b[i].getIntensity();
 2136        }
 2137        // equal peaks: the fields that still serialise differently -- two overlapping isolation
 2138        // windows can emit one precursor with the same peaks and different offsets (review, step 2)
 2139        const auto& pa = a.getPrecursors(); const auto& pb = b.getPrecursors();
 2140        if (pa.empty() != pb.empty()) return pa.empty();
 2141        if (!pa.empty())
 2142        {
 2143          if (pa[0].getIsolationWindowLowerOffset() != pb[0].getIsolationWindowLowerOffset()) return pa[0].getIsolationWindowLowerOffset() < pb[0].getIsolationWindowLowerOffset();
 2144          if (pa[0].getIsolationWindowUpperOffset() != pb[0].getIsolationWindowUpperOffset()) return pa[0].getIsolationWindowUpperOffset() < pb[0].getIsolationWindowUpperOffset();
 2145          if (pa[0].getDriftTime() != pb[0].getDriftTime()) return pa[0].getDriftTime() < pb[0].getDriftTime();
 2146        }
 2147        for (const char* key : {"spx_guessed", "spx_n_isotopes"})
 2148        {
 2149          const int ia = a.metaValueExists(key) ? (int)a.getMetaValue(key) : -1, ib = b.metaValueExists(key) ? (int)b.getMetaValue(key) : -1;
 2150          if (ia != ib) return ia < ib;
 2151        }
 2152        return false;
 2153      });
 2154      vector<MSSpectrum> ord; ord.reserve(v.size());
 2155      for (const SortKey& k : keys) ord.push_back(std::move(v[k.idx]));
 2156      v.swap(ord);
 2157    }
 2158  
 2159    /// [twins] One precursor claimed twice is emitted as two spectra with complementary fragments: two seeds that
 2160    /// resolved to the same monoisotope (the claim loop's `used[]` owns traces, not mono positions), or one
 2161    /// precursor in the 1-m/z overlap of two isolation windows. Folds each such cluster into one spectrum.
 2162    /// Relation: same MS1 frame (RT bit-equal; every precursor RT is a frame time), same charge > 0, precursor
 2163    /// m/z within 20 ppm of the member earlier in `v`, |d1/K0| <= im_tol; clusters are its connected
 2164    /// components. Survivor: most isotopes, then most peaks, then the earliest. Its peaks become the union of
 2165    /// the cluster's, fused within 10 ppm (m/z intensity-weighted, intensity = max); every other field is its
 2166    /// own. Same frame => same RT cell => same tile under every grouping, so the output stays grouping- and
 2167    /// thread-invariant. This is bench/twin_merge.py, which priced it: docs/SAME-POSITION-DUPLICATION-2026-09-20.md.
 2168    /// `v` in canonical order; survivors keep their places. Returns the number of spectra removed.
 2169    /// [recap] `keyed`: every spectrum carries its peaks' cap keys as float data array 0; a fused peak keeps the max key.
 2170    static size_t mergeTwins_(vector<MSSpectrum>& v, double im_tol, bool keyed = false)
 2171    {
 2172      const double TWIN_PPM = 20.0, FUSE_PPM = 10.0;   // ponytail: the measured values, no option until another is measured
 2173      struct K { double rt, mz, im; int z; uint32_t i; };
 2174      vector<K> ks; ks.reserve(v.size());
 2175      for (size_t i = 0; i < v.size(); ++i)
 2176      {
 2177        const auto& p = v[i].getPrecursors();
 2178        if (!p.empty() && p[0].getCharge() > 0) ks.push_back({v[i].getRT(), p[0].getMZ(), p[0].getDriftTime(), p[0].getCharge(), (uint32_t)i});
 2179      }
 2180      sort(ks.begin(), ks.end(), [](const K& a, const K& b) {
 2181        if (a.rt != b.rt) return a.rt < b.rt;
 2182        if (a.z != b.z) return a.z < b.z;
 2183        if (a.mz != b.mz) return a.mz < b.mz;
 2184        return a.i < b.i;
 2185      });
 2186      vector<uint32_t> up(v.size());
 2187      for (size_t i = 0; i < up.size(); ++i) up[i] = (uint32_t)i;
 2188      auto root = [&up](uint32_t a) { while (up[a] != a) { up[a] = up[up[a]]; a = up[a]; } return a; };
 2189      for (size_t g0 = 0, g1; g0 < ks.size(); g0 = g1)
 2190      {
 2191        for (g1 = g0 + 1; g1 < ks.size() && ks[g1].rt == ks[g0].rt && ks[g1].z == ks[g0].z; ++g1) {}   // one frame, one charge
 2192        for (size_t a = g0; a < g1; ++a)
 2193        {
 2194          // the probe is the EARLIER member of a pair, with its own tolerance, as in bench/twin_merge.py
 2195          const double tol = ks[a].mz * TWIN_PPM * 1e-6, lo = ks[a].mz - tol, hi = ks[a].mz + tol;
 2196          auto link = [&](size_t b) {
 2197            if (ks[b].i > ks[a].i && fabs(ks[b].im - ks[a].im) <= im_tol) { const uint32_t ra = root(ks[a].i), rb = root(ks[b].i); if (ra != rb) up[ra] = rb; }
 2198          };
 2199          for (size_t b = a + 1; b < g1 && ks[b].mz <= hi; ++b) link(b);
 2200          for (size_t b = a; b-- > g0 && ks[b].mz >= lo; ) link(b);
 2201        }
 2202      }
 2203      // survivor per cluster: (isotopes, peaks) strictly greater replaces, so a tie keeps the earliest
 2204      const uint32_t NONE = UINT32_MAX;
 2205      vector<uint32_t> n_in(v.size(), 0), best(v.size(), NONE);
 2206      for (uint32_t i = 0; i < (uint32_t)v.size(); ++i) ++n_in[root(i)];
 2207      auto isotopes = [&v](uint32_t i) { return v[i].metaValueExists("spx_n_isotopes") ? (int)v[i].getMetaValue("spx_n_isotopes") : 0; };
 2208      for (uint32_t i = 0; i < (uint32_t)v.size(); ++i)
 2209      {
 2210        const uint32_t r = root(i);
 2211        if (n_in[r] < 2) continue;
 2212        const uint32_t b = best[r];
 2213        if (b == NONE || std::make_pair(isotopes(i), v[i].size()) > std::make_pair(isotopes(b), v[b].size())) best[r] = i;
 2214      }
 2215      vector<uint32_t> surv;
 2216      vector<int> slot(v.size(), -1);
 2217      for (uint32_t i = 0; i < (uint32_t)v.size(); ++i)
 2218      {
 2219        const uint32_t r = root(i);
 2220        if (n_in[r] >= 2 && best[r] == i) { slot[i] = (int)surv.size(); surv.push_back(i); }
 2221      }
 2222      vector<vector<uint32_t>> members(surv.size());
 2223      for (uint32_t i = 0; i < (uint32_t)v.size(); ++i) { const uint32_t r = root(i); if (n_in[r] >= 2) members[(size_t)slot[best[r]]].push_back(i); }
 2224      // fuse: each thread reads and writes one cluster's spectra only
 2225  #pragma omp parallel for schedule(dynamic, 64)
 2226      for (long c = 0; c < (long)surv.size(); ++c)
 2227      {
 2228        if (keyed)
 2229        {
 2230          // [recap] the same fusion over (m/z, intensity, key) triples. Peaks equal in m/z and intensity add equal terms
 2231          // and always land in one fused peak, so the peaks are the unkeyed fold's; each fused peak keeps its members' max key.
 2232          vector<std::array<double, 3>> ps;
 2233          for (uint32_t i : members[(size_t)c])
 2234          {
 2235            const auto& fd = v[i].getFloatDataArrays();
 2236            for (Size j = 0; j < v[i].size(); ++j) ps.push_back({v[i][j].getMZ(), (double)v[i][j].getIntensity(), fd.empty() ? 0.0 : (double)fd[0][j]});
 2237          }
 2238          sort(ps.begin(), ps.end());
 2239          vector<pair<double, double>> fused;
 2240          OpenMS::DataArrays::FloatDataArray kk;
 2241          kk.setName("spx_cap_key");
 2242          const double NO_KEY = -std::numeric_limits<double>::infinity();
 2243          double gm = 0.0, gw = 0.0, gi = 0.0, gk = NO_KEY;
 2244          for (const auto& pk : ps)
 2245          {
 2246            if (gw != 0.0 && pk[0] - gm / gw > (gm / gw) * (FUSE_PPM * 1e-6)) { fused.emplace_back(gm / gw, gi); kk.push_back((float)gk); gm = gw = gi = 0.0; gk = NO_KEY; }
 2247            gm += pk[0] * pk[1]; gw += pk[1]; gi = std::max(gi, pk[1]); gk = std::max(gk, pk[2]);
 2248          }
 2249          if (gw != 0.0) { fused.emplace_back(gm / gw, gi); kk.push_back((float)gk); }
 2250          MSSpectrum& s = v[surv[(size_t)c]];
 2251          s.clear(false);
 2252          s.reserve(fused.size());
 2253          for (const auto& f : fused) s.emplace_back(f.first, (float)f.second);
 2254          s.getFloatDataArrays().clear();
 2255          s.getFloatDataArrays().push_back(std::move(kk));   // moved, not copied (assign(1, x) copies)
 2256          continue;
 2257        }
 2258        vector<pair<double, double>> ps;
 2259        for (uint32_t i : members[(size_t)c]) for (const auto& pk : v[i]) ps.emplace_back(pk.getMZ(), (double)pk.getIntensity());
 2260        sort(ps.begin(), ps.end());
 2261        vector<pair<double, double>> fused;
 2262        double gm = 0.0, gw = 0.0, gi = 0.0;
 2263        for (const auto& pk : ps)
 2264        {
 2265          if (gw != 0.0 && pk.first - gm / gw > (gm / gw) * (FUSE_PPM * 1e-6)) { fused.emplace_back(gm / gw, gi); gm = gw = gi = 0.0; }
 2266          gm += pk.first * pk.second; gw += pk.second; gi = std::max(gi, pk.second);
 2267        }
 2268        if (gw != 0.0) fused.emplace_back(gm / gw, gi);
 2269        MSSpectrum& s = v[surv[(size_t)c]];
 2270        s.clear(false);   // peaks only: RT, precursor and userParams are the survivor's
 2271        s.reserve(fused.size());
 2272        for (const auto& f : fused) s.emplace_back(f.first, (float)f.second);
 2273      }
 2274      size_t w = 0;
 2275      for (uint32_t i = 0; i < (uint32_t)v.size(); ++i)
 2276      {
 2277        const uint32_t r = root(i);
 2278        if (n_in[r] >= 2 && best[r] != i) continue;
 2279        if (w != i) v[w] = std::move(v[i]);
 2280        ++w;
 2281      }
 2282      const size_t removed = v.size() - w;
 2283      v.erase(v.begin() + (long)w, v.end());
 2284      return removed;
 2285    }
 2286  
```

### assembleOne_ tail: foreign removal, same-bin merge, fusion, min_fragments, the cap, the output (src/diaspextract.cpp lines 4120-4240 at b2185db)

```cpp
 4120                         << c << '\t' << intensityOf(wst, f) << '\t' << fate << '\n';
 4121          }
 4122        }
 4123        if (rows.tellp() > 0) { std::lock_guard<std::mutex> lk(gd.mu); gd.out << rows.str(); gd.out.flush(); }
 4124      }
 4125      for (int gi : touched) pdense[gi] = 0.0f;                          // reset scratch
 4126      // [foreign] other precursors' residual envelopes, before the merge and the cap: a removed fragment frees its slot
 4127      const size_t n_before = frags.size();                              // [foreign] for the fell-below count
 4128      const size_t n_foreign = fx && !frags.empty() ? attenuateForeign_(pc, g_drt, *fx, frags, frag_scores, frag_bin, frag_span, frag_ai, resc) : 0;
 4129      // [merge] guard: one TOF bin is one m/z. What toTof's same-frame merge cannot reach (slices beyond its span, valley-
 4130      // split children, band edges, tile carries) is merged here, before the cap, into the strongest member: members whose
 4131      // RT span overlaps its span are summed (parallel slices of one ion), RT-disjoint pieces are dropped (the stronger
 4132      // piece stands, as the twin fold's max); the merged peak takes the strongest member's m/z and the best cap key of
 4133      // the summed members (not recomputed). Two peaks at one m/z stall OpenMS' MatchedIterator.
 4134      if (merge_same_bin_ && frags.size() > 1)
 4135      {
 4136        vector<size_t> ord(frags.size());
 4137        for (size_t i = 0; i < ord.size(); ++i) ord[i] = i;
 4138        auto key = [&](size_t i) { return std::make_tuple(frag_bin[i] == 0, frag_bin[i], frag_bin[i] ? 0.0 : frags[i].first, i); };
 4139        std::sort(ord.begin(), ord.end(), [&](size_t a, size_t b) { return key(a) < key(b); });
 4140        auto same = [&](size_t a, size_t b) { return frag_bin[a] ? frag_bin[a] == frag_bin[b] : (!frag_bin[b] && frags[a].first == frags[b].first); };
 4141        vector<char> gone(frags.size(), 0);
 4142        long long nm = 0;
 4143        for (size_t g = 0; g < ord.size();)
 4144        {
 4145          size_t e = g + 1;
 4146          while (e < ord.size() && same(ord[g], ord[e])) ++e;
 4147          if (e - g > 1)
 4148          {
 4149            const size_t head = ord[g];                                    // lowest index: the output order is unchanged
 4150            size_t top = head;
 4151            for (size_t k = g; k < e; ++k) if (frags[ord[k]].second > frags[top].second) top = ord[k];
 4152            double sum = 0.0, cap = -std::numeric_limits<double>::infinity();
 4153            for (size_t k = g; k < e; ++k)
 4154            {
 4155              const size_t i = ord[k];
 4156              if (!(frag_span[i].second < frag_span[top].first || frag_span[top].second < frag_span[i].first))
 4157              { sum += frags[i].second; cap = std::max(cap, frag_scores[i]); }
 4158              if (k > g) gone[i] = 1;
 4159            }
 4160            frags[head] = {frags[top].first, sum}; frag_scores[head] = cap;
 4161            if (!resc.empty()) resc[head] = resc[top];                    // [anchor] rescued if its m/z is a rescued one's
 4162            nm += (long long)(e - g - 1);
 4163          }
 4164          g = e;
 4165        }
 4166        if (nm)
 4167        {
 4168          size_t w = 0;
 4169          for (size_t i = 0; i < frags.size(); ++i)
 4170            if (!gone[i]) { frags[w] = frags[i]; frag_scores[w] = frag_scores[i]; if (!resc.empty()) resc[w] = resc[i]; ++w; }
 4171          frags.resize(w); frag_scores.resize(w);
 4172          if (!resc.empty()) resc.resize(w);
 4173          mergeCount_()[2] += nm;
 4174        }
 4175      }
 4176      // [fuse] one peak per fragment ion, after the merge (frag_bin and frag_span are stale from here on) and before
 4177      // min_fragments and the cap: the cap ranks fused peaks, so the slots of an ion's pieces refill
 4178      const size_t n_merged = frags.size();                              // [foreign]/[fuse] the fell-below counts
 4179      if (fuse_ppm_ > 0.0 && n_merged > 0)
 4180      {
 4181        long long n_mem = 0;
 4182        const long long n_grp = fuseFragments_(frags, frag_scores, resc, fuse_ppm_, fuse_linkage_, n_mem);
 4183        auto& fc = fuseCount_();
 4184        ++fc[0]; fc[1] += (long long)n_merged; fc[2] += (long long)frags.size();
 4185        if (n_grp) { fc[3] += n_grp; fc[4] += n_mem; }
 4186        if (n_merged >= min_frags && frags.size() < min_frags) ++fc[5];
 4187      }
 4188      if (frags.size() < min_frags)
 4189      {   // [foreign] counted only when the removal (weight 0) took a spectrum that had enough fragments below the floor
 4190        if (n_foreign && foreign_w_ <= 0.0 && n_before >= min_frags && n_merged < min_frags) ++foreignCount_()[5];
 4191        return;
 4192      }
 4193      long long n_resc = 0;                                               // [anchor] rescued peaks in this spectrum
 4194      for (char r : resc) n_resc += r;
 4195      if (frags.size() > max_frags)
 4196      {
 4197        vector<size_t> idx(frags.size());
 4198        for (size_t i = 0; i < idx.size(); ++i) idx[i] = i;
 4199        // Rank by correlation. Ties break on m/z, then index, so the output is deterministic.
 4200        partial_sort(idx.begin(), idx.begin() + max_frags, idx.end(), [&](size_t a, size_t b) {
 4201          const double ka = frag_scores[a];
 4202          const double kb = frag_scores[b];
 4203          if (ka != kb) return ka > kb;
 4204          if (frags[a].first != frags[b].first) return frags[a].first < frags[b].first;
 4205          return a < b;
 4206        });
 4207        vector<pair<double, double>> keep; keep.reserve(max_frags);
 4208        for (size_t i = 0; i < max_frags; ++i) keep.push_back(frags[idx[i]]);
 4209        if (!resc.empty()) { n_resc = 0; for (size_t i = 0; i < max_frags; ++i) n_resc += resc[idx[i]]; }
 4210        frags.swap(keep);
 4211        if (post_fusion_cap_)                                            // [recap] the kept peaks' keys, in the same order
 4212        {
 4213          vector<double> keep_k(max_frags);
 4214          for (size_t i = 0; i < max_frags; ++i) keep_k[i] = frag_scores[idx[i]];
 4215          frag_scores.swap(keep_k);
 4216        }
 4217      }
 4218      if (n_resc) { anchorCount_()[6] += n_resc; ++anchorCount_()[7]; }
 4219      out.setMSLevel(2);
 4220      out.setType(SpectrumSettings::SpectrumType::CENTROID);
 4221      out.setRT(pc.rt);
 4222      // [mem] exact reserve: no doubling slack held from emit until the write.
 4223      out.reserve(frags.size());
 4224      for (const auto& fr : frags) out.emplace_back(fr.first, fr.second);
 4225      if (post_fusion_cap_)   // [recap] each peak's cap key rides along as a float data array (sorted with the peaks), dropped before the write
 4226      {
 4227        OpenMS::DataArrays::FloatDataArray k;
 4228        k.setName("spx_cap_key");
 4229        k.assign(frag_scores.begin(), frag_scores.end());
 4230        out.getFloatDataArrays().push_back(std::move(k));
 4231      }
 4232      out.sortByPosition();
 4233      OpenMS::Precursor prec;
 4234      prec.setMZ(pc.mono_mz);   // MS1 traces come from the OpenMS detector: no bin to calibrate
 4235      if (pc.charge > 0) prec.setCharge(pc.charge);
 4236      prec.setIsolationWindowLowerOffset(max(0.0, pc.mono_mz - win_lo));   // [C-5]
 4237      prec.setIsolationWindowUpperOffset(max(0.0, win_hi - pc.mono_mz));
 4238      prec.setDriftTime(pc.im);
 4239      prec.setDriftTimeUnit(DriftTimeUnit::VSSC);
 4240      out.setPrecursors({prec});
```

### main_: precursor inference, adaptive auto, IM veto, monocheck v2, default charge, drops (src/diaspextract.cpp lines 5099-5215 at b2185db)

```cpp
 5099      }
 5100      std::optional<Phase> win_phase;                            // [perf-instr] the window loop (function scope)
 5101      double _t_inf = phase_clock_(), _c_inf = cpu_seconds_();   // [perf-instr]
 5102      vector<MonoV2In_> mono_v2in;   // [monocheck-v2] the count walks, parallel to `precursors` until monoPositionPass_
 5103      vector<Precursor_> precursors = inferPrecursors_(ms1_traces, ms1_store, max_charge, delta_rt, iso_im_tol,
 5104                                                       mass_ppm, env_scoring, mono_check_ == 2 ? &mono_v2in : nullptr);
 5105      if (adaptive_auto_)   // [adaptive] auto: decide the run's gate from its precursor span distribution (MS1 points)
 5106      {
 5107        size_t nf = 0;
 5108        for (const Precursor_& pc : precursors) if ((int)ms1_traces[pc.trace_idx].np() <= faint_frames_) ++nf;
 5109        const double frac = precursors.empty() ? 0.0 : (double)nf / (double)precursors.size();
 5110        adaptive_ = frac >= auto_faint_frac_;
 5111        if (!adaptive_) shrink_ = coloc_ = short_conc_ = false;   // auto:off = the plain gate for every precursor, not 'off'
 5112        writeLogInfo_("[adaptive] auto: " + String(nf) + " of " + String(precursors.size()) + " precursors span <= " + String(faint_frames_)
 5113                      + " MS1 points (" + String(frac) + ", threshold " + String(auto_faint_frac_) + "): faint gate " + (adaptive_ ? "ON" : "OFF"));
 5114      }
 5115      if (detOn_())
 5116      {
 5117        vector<uint64_t> b;
 5118        for (const auto& pc : precursors) { pushBits_(b, pc.rt); pushBits_(b, pc.im); }
 5119        writeLogInfo_("[det] precursors n=" + String(precursors.size()) + " digest=" + String(detDigest_(std::move(b))));
 5120      }
 5121      // [im-veto 2026-09-08] Charge halving, corrected by ion mobility. See charge:im_charge_veto.
 5122      if (getStringOption_("charge:im_charge_veto") == "true")
 5123      {
 5124        auto fitLine = [&](int z, double& a, double& b, double& sig, size_t& n) -> bool {
 5125          std::map<int, vector<double>> bins;                           // 25-Th bins of 1/K0, confident calls only
 5126          for (const auto& pc : precursors)
 5127            if (pc.charge == z && pc.n_isotopes >= 3 && std::isfinite(pc.im) && pc.mono_mz > 0.0)
 5128              bins[(int)(pc.mono_mz / 25.0)].push_back(pc.im);
 5129          vector<double> xs, ys; n = 0;
 5130          for (auto& kv : bins)
 5131          {
 5132            auto& v = kv.second; if (v.size() < 30) continue;
 5133            std::nth_element(v.begin(), v.begin() + v.size() / 2, v.end());
 5134            xs.push_back((kv.first + 0.5) * 25.0); ys.push_back(v[v.size() / 2]); n += v.size();
 5135          }
 5136          if (xs.size() < 4) return false;
 5137          double sx = 0, sy = 0, sxx = 0, sxy = 0; const double m = (double)xs.size();
 5138          for (size_t i = 0; i < xs.size(); ++i) { sx += xs[i]; sy += ys[i]; sxx += xs[i] * xs[i]; sxy += xs[i] * ys[i]; }
 5139          const double den = m * sxx - sx * sx; if (den <= 0.0) return false;
 5140          b = (m * sxy - sx * sy) / den; a = (sy - b * sx) / m;
 5141          vector<double> res;
 5142          for (const auto& pc : precursors)
 5143            if (pc.charge == z && pc.n_isotopes >= 3 && std::isfinite(pc.im) && pc.mono_mz > 0.0)
 5144              res.push_back(fabs(pc.im - (a + b * pc.mono_mz)));
 5145          if (res.empty()) return false;
 5146          std::nth_element(res.begin(), res.begin() + res.size() / 2, res.end());
 5147          sig = 1.4826 * res[res.size() / 2];
 5148          return sig > 0.0;
 5149        };
 5150        double a2 = 0, b2 = 0, s2 = 0, a3 = 0, b3 = 0, s3 = 0; size_t n2 = 0, n3 = 0;
 5151        const bool ok2 = fitLine(2, a2, b2, s2, n2), ok3 = fitLine(3, a3, b3, s3, n3);
 5152        const double kband = getDoubleOption_("charge:im_veto_band");
 5153        size_t n1 = 0, to2 = 0, to3 = 0;
 5154        if (ok2)
 5155        {
 5156          for (auto& pc : precursors)
 5157          {
 5158            if (pc.charge != 1 || !std::isfinite(pc.im)) continue;
 5159            ++n1;
 5160            const double r2 = fabs(pc.im - (a2 + b2 * pc.mono_mz)) / s2;
 5161            const double r3 = ok3 ? fabs(pc.im - (a3 + b3 * pc.mono_mz)) / s3 : 1e9;
 5162            if (r2 <= kband && r2 <= r3) { pc.charge = 2; ++to2; }
 5163            // On the 3+ band: unset the charge (re-calling it 3+ identified nothing; docs/BASELINE.md, "The
 5164            // veto's 3+ arm dropped"). It becomes a guessed precursor, which require_isotope_support drops.
 5165            else if (ok3 && r3 <= kband) { pc.charge = 0; ++to3; }
 5166          }
 5167          writeLogInfo_("[im-veto] 2+ line 1/K0 = " + String(a2) + " + " + String(b2) + " * m/z (n=" + String(n2) + ", sigma "
 5168                        + String(s2) + ")" + (ok3 ? "; 3+ line " + String(a3) + " + " + String(b3) + " * m/z (n=" + String(n3) + ", sigma " + String(s3) + ")" : String("; no 3+ line"))
 5169                        + ". Of " + String(n1) + " z=1 calls, " + String(to2) + " (" + String((int)(1000.0 * to2 / std::max<size_t>(n1, 1)) / 10.0)
 5170                        + "%) sit on the 2+ band and are re-called 2+, " + String(to3) + " on the 3+ band are dropped, " + String(n1 - to2 - to3) + " kept as 1+");
 5171        }
 5172        else writeLogInfo_("[im-veto] too few confident 2+ calls to fit a mobility line; no z=1 re-calls");
 5173      }
 5174      // [monocheck-v2] At the final charge: after the veto (which reads the walks' own monoisotopes, as without v2),
 5175      // before the charge-less precursors are defaulted or dropped (the veto edits in place, so the order still matches).
 5176      if (mono_check_ == 2)
 5177      {
 5178        monoPositionPass_(ms1_traces, ms1_store, precursors, mono_v2in, delta_rt, iso_im_tol, mass_ppm, env_scoring);
 5179        vector<MonoV2In_>().swap(mono_v2in);
 5180      }
 5181      const int default_charge = getIntOption_("assembly:default_charge");
 5182      Size n_default = 0;
 5183      // [way-4] A GUESSED charge and an isotope-SUPPORTED charge must not be emitted identically.
 5184      // Closed search hides the difference (engine enumerates); open search does not.
 5185      for (auto& pc : precursors)
 5186        if (pc.charge == 0) { pc.guessed = true; pc.charge = default_charge; ++n_default; }
 5187      // [emission] assembly:require_isotope_support: drop the guessed singletons.
 5188      const bool require_iso = (getStringOption_("assembly:require_isotope_support") == "true");
 5189      if (require_iso)
 5190      {
 5191        const size_t before = precursors.size();
 5192        precursors.erase(std::remove_if(precursors.begin(), precursors.end(),
 5193                         [](const Precursor_& pc){ return pc.guessed; }), precursors.end());
 5194        writeLogInfo_("require_isotope_support: dropped " + String(before - precursors.size())
 5195                      + " guessed precursors, " + String(precursors.size()) + " isotope-supported remain");
 5196      }
 5197      {
 5198        const int zmin = getIntOption_("charge:min_charge"); const size_t before = precursors.size();
 5199        precursors.erase(std::remove_if(precursors.begin(), precursors.end(),
 5200                         [zmin](const Precursor_& pc){ return pc.charge > 0 && pc.charge < zmin; }), precursors.end());
 5201        if (before != precursors.size())
 5202          writeLogInfo_("charge:min_charge=" + String(zmin) + ": dropped " + String(before - precursors.size())
 5203                        + " precursors below that charge, " + String(precursors.size()) + " remain");
 5204      }
 5205      // [step-02 emission-controlled arm, 2026-09-02] DIASPEXTRACT_MIN_ISOTOPES=k keeps only precursors whose
 5206      // envelope has >= k isotope peaks (n_isotopes counts the mono): a precursor QUALITY gate that cuts
 5207      // emission without touching fragment sharing. Pre-registered falsifier in BASELINE.md.
 5208      if (const char* mi = std::getenv("DIASPEXTRACT_MIN_ISOTOPES"))
 5209      {
 5210        const int k = std::atoi(mi); const size_t before = precursors.size();
 5211        precursors.erase(std::remove_if(precursors.begin(), precursors.end(),
 5212                         [k](const Precursor_& pc){ return pc.n_isotopes < k; }), precursors.end());
 5213        writeLogInfo_("DIASPEXTRACT_MIN_ISOTOPES=" + String(k) + ": dropped " + String(before - precursors.size())
 5214                      + " precursors with fewer isotope peaks, " + String(precursors.size()) + " remain");
 5215      }
```

### main_: sort of precursors by mono m/z (window assignment) (src/diaspextract.cpp lines 5266-5279 at b2185db)

```cpp
 5266                      + String(precursors.size()) + " precursors -> " + ms1_dump + ".{traces,precursors}.tsv");
 5267      }
 5268      // sort precursors by mono m/z so each window can binary-search its members instead of
 5269      // rescanning all ~1M precursors per window (total order for determinism).
 5270      sort(precursors.begin(), precursors.end(), [](const Precursor_& a, const Precursor_& b) {
 5271        if (a.mono_mz != b.mono_mz) return a.mono_mz < b.mono_mz;
 5272        if (a.rt != b.rt) return a.rt < b.rt;
 5273        if (a.im != b.im) return a.im < b.im;
 5274        return a.trace_idx < b.trace_idx;
 5275      });
 5276      ledSet_(LC_PRECURSOR, (long long)(precursors.capacity() * sizeof(Precursor_) + precursors.size() * 8));
 5277      vector<double> prec_mz(precursors.size());
 5278      for (size_t i = 0; i < precursors.size(); ++i) prec_mz[i] = precursors[i].mono_mz;
 5279      // [mem] Scoring reads only the profiles of traces a precursor points at: release the rest.
```

### main_: window ownership per tile, ForeignIdx_ build, the assembly taskloop (task-count bound) (src/diaspextract.cpp lines 5948-6062 at b2185db)

```cpp
 5948          // fragment at frame time x is a candidate of rt iff fabs(x - rt) <= tile_drt (doubles), so
 5949          // rt has no candidate at or beyond an edge T iff (T - rt) > tile_drt -- the same
 5950          // subtraction, monotone in T. The first tile k with (T_{k+1} - rt) > tile_drt owns rt:
 5951          // exactly one does (-inf never, +inf always). Marked here, before any early exit, so the
 5952          // coverage check after the last tile sees every precursor exactly once. Only this
 5953          // window's precursors (by mono m/z); NaN sorts to the end, excluded; charge 0 kept.
 5954          const size_t plo = lower_bound(prec_mz.begin(), prec_mz.end(), win_lo) - prec_mz.begin();
 5955          const size_t phi = upper_bound(prec_mz.begin(), prec_mz.end(), win_hi) - prec_mz.begin();
 5956          vector<uint32_t> pidx; pidx.reserve(phi > plo ? phi - plo : 0);
 5957          for (size_t pi = plo; pi < phi; ++pi)
 5958          {
 5959            const Precursor_& pc = precursors[pi];
 5960            if (!std::isfinite(pc.rt) || !std::isfinite(pc.im)) continue;
 5961            if (!(tk == 0 || !(tile.lo - pc.rt > tile_drt))) continue;   // an earlier tile owns it
 5962            if (!(tile.last || (tile.hi - pc.rt > tile_drt))) continue;  // a later tile owns it
 5963            pidx.push_back((uint32_t)pi);
 5964          }
 5965          { vector<uint8_t>& vis = visited.at(wl[wi].first);
 5966            for (uint32_t pi : pidx)
 5967              if (vis[pi - plo]++ != 0)
 5968                throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[tile] a precursor is owned by two tiles",
 5969                                              String(precursors[pi].rt, 6) + " s in window " + String(win_lo) + "-" + String(win_hi)); }
 5970          auto _tso = std::chrono::steady_clock::now();
 5971          frag_traces.erase(remove_if(frag_traces.begin(), frag_traces.end(), [&wst](const Trace& t) {
 5972            return !std::isfinite(t.im) || !std::isfinite(t.mz) || !std::isfinite(rtOf(wst, t));
 5973          }), frag_traces.end());
 5974          if (frag_traces.empty()) return;   // nothing traceable in this window
 5975  
 5976          // Content-only and TOTAL: traces equal in (im, mz, rt, apex intensity) fall through to the remaining
 5977          // fields, so their order never depends on what else is resident; exact duplicates are interchangeable.
 5978          sort(frag_traces.begin(), frag_traces.end(), [&wst](const Trace& a, const Trace& b) {
 5979            if (a.im != b.im) return a.im < b.im;
 5980            if (a.mz != b.mz) return a.mz < b.mz;
 5981            { const double ra = rtOf(wst, a), rb = rtOf(wst, b); if (ra != rb) return ra < rb; }
 5982            { const double ia = intensityOf(wst, a), ib = intensityOf(wst, b); if (ia != ib) return ia < ib; }
 5983            if (a.npts != b.npts) return a.npts < b.npts;
 5984            if (a.len != b.len) return a.len < b.len;
 5985            { const double fa = wst.frame_rt[a.frame0], fb = wst.frame_rt[b.frame0]; if (fa != fb) return fa < fb; }
 5986            // ...then the profile and the bin fields (two bands can share an apex with different flanks)
 5987            for (size_t k = 0; k < a.len; ++k) { const float xa = xv(wst, a, k), xb = xv(wst, b, k); if (xa != xb) return xa < xb; }
 5988            if (a.tof != b.tof) return a.tof < b.tof;
 5989            if (a.bframe != b.bframe) return a.bframe < b.bframe;
 5990            if (a.rt_at != b.rt_at) return a.rt_at < b.rt_at;
 5991            return false;
 5992          });
 5993          vector<double> frag_im(frag_traces.size());
 5994          for (size_t i = 0; i < frag_traces.size(); ++i) frag_im[i] = frag_traces[i].im;
 5995          FragRt frag_rt; frag_rt.build(frag_traces, wst, tile_drt);   // [adaptive] buckets cover the wider window
 5996          w_sort = secs(std::chrono::steady_clock::now() - _tso);
 5997  
 5998          // Precompute the common correlation grid once per window; pdense is reused across the
 5999          // window's precursors (this window runs on one thread). [perf]
 6000          auto _t3 = std::chrono::steady_clock::now();
 6001          w_trace = secs(_t3 - _t2) - w_prep - w_split;
 6002          FragStats fg = buildFragStats(frag_traces, wst, fwin);
 6003          ledStore();   // the finiteness filter and the content sort have run
 6004          LedCharge _frag(LC_FRAG, (long long)(frag_im.capacity() * 8 + frag_rt.rt.capacity() * 8 + frag_rt.q.capacity() * 2
 6005                                               + fg.mean.capacity() * 8 + fg.invnorm.capacity() * 8));
 6006          vector<float> pdense(wst.frames(), 0.0f);   // indexed by window-local frame
 6007          // [foreign] the window's precursors by apex RT, owned by this tile or not: the same candidates in any tiling
 6008          ForeignIdx_ fx;
 6009          if (foreign_w_ < 1.0) fx.build(precursors, plo, phi);
 6010  
 6011          vector<MSSpectrum>& bucket = win_out[wi];
 6012          {
 6013            // Share-all (default, current best): each fragment goes to EVERY gated precursor.
 6014            //
 6015            // [perf-3] Precursors are the unit of parallelism (one window can hold ~24% of them). Each result goes to
 6016            // its own pre-sized slot (an earlier append to the shared bucket lost spectra), so task granularity cannot
 6017            // drop or reorder an emission; pdense is per-task scratch and must stay firstprivate.
 6018            auto _t5 = std::chrono::steady_clock::now();
 6019            vector<MSSpectrum> pslot(pidx.size());   // [tile] the owned precursors, in index order as before
 6020            // [ledger] ~700 B of empty header per OWNED precursor, most of which never emit, plus the
 6021            // payloads as they are produced -- charged HERE and not at the end of the stage, so the
 6022            // scoring stage's real footprint is visible instead of appearing all at once after it.
 6023            LedCharge _pslot(LC_SPECTRA, (long long)pidx.size() * (long long)sizeof(MSSpectrum));
 6024            // [gomp-cliff] Bound the TASK COUNT: libgomp's GOMP_taskloop runs the whole loop inline in the
 6025            // creating thread once team task_count + num_tasks > 64 x nthreads, silently serialising it
 6026            // (grainsize does not bound the count). So <= n_threads worker tasks pull 32-precursor chunks from
 6027            // a shared cursor; keep the team-wide total well under the threshold when adding task layers.
 6028            // docs/BASELINE.md, "Scheduling: the window loop was bounded by one window's serial chain".
 6029            const long n_prec_w = (long)pidx.size();
 6030            const long n_task_w = std::max(1L, std::min((n_prec_w + 31) / 32, (long)n_threads));
 6031            std::atomic<long> pcur{0};
 6032            std::exception_ptr asm_err;   // [task-err] rethrown into the window body's catch
 6033            #pragma omp taskloop num_tasks(n_task_w) firstprivate(pdense) default(shared)
 6034            for (long w = 0; w < n_task_w; ++w)
 6035            { try {
 6036              taskFault_("assemble");
 6037              for (;;)
 6038              {
 6039                const long cs = pcur.fetch_add(32);
 6040                if (cs >= n_prec_w) break;
 6041                const long ce = std::min(cs + 32, n_prec_w);
 6042                for (long j = cs; j < ce; ++j)
 6043                {
 6044                  const Precursor_& pc = precursors[pidx[(size_t)j]];
 6045                  MSSpectrum ms2;
 6046                  assembleOne_(pc, win_lo, win_hi, frag_traces, wst, frag_im, frag_rt, ms1_traces, ms1_store, fg,
 6047                               gate_dim, delta_rt, min_corr, min_corr_pts, min_frags, max_frags, pdense, ms2,
 6048                               foreign_w_ < 1.0 ? &fx : nullptr);
 6049                  if (!ms2.empty())
 6050                  { ledAdd_(LC_SPECTRA, (long long)(sizeof(MSSpectrum) + ms2.size() * (post_fusion_cap_ ? 16 : 12))); pslot[(size_t)j] = std::move(ms2); }   // [recap] +4 B/peak key
 6051                }
 6052              }
 6053            } catch (...) { taskErr_(asm_err); } }
 6054            if (asm_err) std::rethrow_exception(asm_err);
 6055            auto _t6 = std::chrono::steady_clock::now();
 6056            w_score = secs(_t6 - _t5);
 6057            for (auto& s : pslot) if (!s.empty()) bucket.push_back(std::move(s));
 6058            // (the payloads were charged at emission; moving them into the bucket changes no bytes)
 6059            const auto _t7 = std::chrono::steady_clock::now();
 6060            w_emit = secs(_t7 - _t6);
 6061          }
 6062          // [tile] carry the boundary fragments to the next tile: every record (own or carried in)
```

## Section D: `git diff b65c8dd..b2185db -- CHANGELOG.md README.md` (complete)

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 483d575..9ffe1ef 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,5 +1,222 @@
 # Changelog
 
+## Unreleased (tuning 2026-09-29)
+
+- **Unreleased: rc-b (branch tune/rc-b = rc-a + tune/fuse + tune/monocheck): new defaults**
+  `-assembly:fragment_fuse_ppm 25` with `-assembly:fragment_fuse_mode anchored` (was 0 = off) and
+  `-charge:mono_profile_check v2` (was `false`), with v2's reviewed sub-defaults (`mono_position_min_ratio` 0.2,
+  `mono_position_im_box` 0 = auto, `mono_position_extend` 0.6, `mono_position_iterate` true); rc-a's
+  `-assembly:im_weight_sigma 0.005` and `-assembly:foreign_precursor_weight 0` stay. `-assembly:fragment_fuse_ppm 0
+  -charge:mono_profile_check false -assembly:im_weight_sigma 0 -assembly:foreign_precursor_weight 1` restores the
+  1.5.0 output. Screening grade (n = 1 per sample; Sage / MSFragger peptides at 1 % FDR, Sage entrapment FDP;
+  release 1.5.0 = K562 9905 36,742 / 36,057 / 1.183 %, HeLa_22 8,837 / 7,211 / 0.969 %, HeLa_34 30,957 / 26,721 /
+  1.174 %). The two halves were screened apart, not together:
+  fusion with the rc-a defaults (fuse 25 ppm anchored + im_weight_sigma 0.005 + foreign 0): K562 42,236 (+15.0 %) /
+  38,602 (+7.1 %) / 1.227 %; HeLa_22 9,227 (+4.4 %) / 7,630 (+5.8 %) / 0.979 %; HeLa_34 34,144 (+10.3 %) / 30,253
+  (+13.2 %) / 1.050 %; on six further public runs (TNBC_009, K562 CAD_3197, HeLa 2450 / 2737 / 19 / 28) more peptides
+  with both engines on all six (Sage +8.2..+13.9 %, MSFragger +2.6..+14.5 %), entrapment +0.04..+0.17 pt on five and
+  −0.03 pt on HeLa 28. Monocheck v2 with im_weight_sigma 0.005 (review arm, no foreign weight, no fusion): K562 39,915
+  (+8.6 %) / 37,822 (+4.9 %) / 1.198 %; HeLa_22 9,111 (+3.1 %) / 7,477 (+3.7 %) / 1.016 %; HeLa_34 32,689 (+5.6 %) /
+  27,870 (+4.3 %) / 1.189 %; identified K562 isotope error 5.2 % (1.5.0: 18.5 %). The fused runs' entrapment rise and
+  the combination itself still need a harness-grade measurement. The default output changes: the release digest pins
+  do not apply to this branch.
+
+- **Release candidate A (branch tune/rc-a): new defaults** `-assembly:im_weight_sigma 0.005` (was 0 = off) and
+  `-assembly:foreign_precursor_weight 0` (was 1 = off). Screen, both engines at 1 % FDR with Sage entrapment, versus 1.5.0: K562
+  (two instruments) +8.2 % Sage / +4.2-5.1 % MSFragger, HeLa py3 10/50/100 ng +2.7-5.1 % / +3.6-4.6 %, HeLa 25pc 10 ng +6.4 / +3.9 %,
+  Evosep 60/200 SPD +5.5-7.5 % / +2.3-3.4 %, TNBC +5.2 / +4.5 %; entrapment within -0.14..+0.09 points. The spectra are more
+  DDA-like on the K562 scorecard (b/y ions in the top 150 +0.76, unexplained top-20 peaks -1.4, weak-ion recovery 25.6 -> 29.4 %).
+  The default output changes: the release digest pins do not apply to this branch.
+
+- **Fragment intensity definition (`-assembly:frag_intensity`, off by default).** The written fragment intensity is
+  the trace's apex in one frame, while a DDA spectrum sums the precursor's selection. `core` sums the fragment trace
+  over the `-assembly:frag_core_frames` (default 3, odd) window frames centred on the precursor's apex frame, the same
+  frames for every fragment of the precursor; `sum` over the precursor's span, from its first to its last frame with
+  signal, gaps included (summed only where the precursor has a point, 29 % of HeLa 10 ng's fragments had none: a faint
+  MS1 trace has missing points and the concentric gate keeps fragments that sit in them). The 1/K0 weight and
+  corr^`corr_power` apply on top as before. A fragment with no point in those frames takes its point nearest the
+  precursor's apex rather than being dropped or written at 0. The gate and the `max_fragments` cap key (still the
+  apex) are unchanged, so the spectra and the fragments passing the gate are the same; the steps after it that weigh
+  by intensity follow the new values (the same-bin merge keeps its strongest member's m/z and sums the members that
+  overlap it, the twin fold fuses peaks at their intensity-weighted m/z), so on HeLa 10 ng 99.9 % of the peaks lie
+  within 10 ppm of the `apex` run's. Stamped `spx:fragint`; a `[fragint]` log line counts the fragments and the
+  fallbacks. `apex` is the 1.5.0 output (same semantic digest).
+- **`-charge:mono_profile_check` (off by default): profile-supported monoisotope.** 9.9 % of the identified precursors
+  were reported one isotope below the monoisotope (5.5 % in DDA on the same keys): the count walk latches leftward onto
+  the first unused MS1 trace at mono − 1.00335/z within 15 ppm, 3 s and 0.05 1/K0 without asking whether it belongs to
+  the envelope. With the option on, each leftward step of the winning charge must correlate with the seed trace's MS1
+  profile (Pearson ≥ `-charge:mono_profile_min_corr`, default 0.6, over the frames both have; fewer than 3 shared frames
+  pass unchecked) and lie within `-charge:mono_profile_max_dim` (default 0.015) 1/K0 of the seed. The walk stops at the
+  first failed step, the monoisotope is the last accepted peak, and the rejected trace (and any beyond it) stays
+  unclaimed. The charge, the seed and `spx_n_isotopes` are unchanged. A `[monocheck]` log line counts the walks checked,
+  the monoisotopes moved and the rejections; the header is stamped `spx:monocheck`. Default output unchanged. At the
+  defaults the unclaimed traces seed precursors of their own: spectra +8.5 % on HeLa_22 (10 ng), +28 % on K562 9905.
+- **Anchor-conditioned rescue of weak fragments (`-gate:anchor_rescue`, off by default).** Of the DDA fragment ions
+  below 5 % relative intensity the pseudo-spectra recover 33 % (diaTracer 44 %): the faint-precursor gate helps only
+  when the precursor is faint, and a weak fragment of a strong precursor still needs 3 shared points and a full-grid
+  Pearson of 0.3. With the option on, a well-sampled precursor (signal in more than `-gate:faint_max_frames` window
+  frames, in every `-gate:adaptive` mode) with at least `-gate:anchor_min_count` (3) fragments at
+  r >= `-gate:anchor_min_corr` (0.8) builds a consensus profile from them (each at unit maximum, summed); fragment
+  traces in the RT and 1/K0 windows that the gate rejected only for support or by the correlation cut, with at least
+  2 points, join when their apex is within one cycle of the consensus apex and their own points correlate with the
+  consensus by `-gate:anchor_rescue_corr` (0.7) or more (2 points: both in the consensus core, in its direction,
+  scored at the threshold). Rescued fragments are weighted and cap-ranked like the others with that score, capped at
+  `anchor_min_corr`, and their cap key counts the frames shared with the precursor like every other fragment's; at
+  most `-gate:anchor_max_rescued` (50) per spectrum. An `[anchor]` log line counts anchored precursors, candidates,
+  rescues (by the gate step that had rejected them) and rescued peaks in the written spectra; the header stamps
+  `spx:anchor`, and `DIASPEXTRACT_GATE_DUMP` labels a rescued fragment's fate `rescued`. The default output is
+  unchanged (same semantic digest).
+- **`-assembly:post_fusion_cap` (off by default): `max_fragments` holds after the twin fold.** The cap was applied per
+  precursor before the fold, whose union of the members' fragment lists lets a spectrum exceed 500 peaks: at the 1.5.0
+  defaults 50.5 % of the K562 9905 spectra (up to 5,551 peaks) and 35.4 % of HeLa 10 ng (up to 1,611). With the option
+  on, each peak carries its `cap_rank` key (as a 32-bit float) through the same-bin merge and the fold (a fused peak
+  keeps its members' best key), and every spectrum over the cap after the fold keeps its top-ranked peaks (ties: higher
+  intensity, then lower m/z), in m/z order: on K562 9905 it removes 44 % of those spectra's peaks (203 M), the spectrum
+  count is unchanged, the cap takes 0.6 s and the keyed fold 0.9 s more, peak RSS +0.6 GB (+2.9 %). A `[recap]` log
+  line gives the spectra re-capped and the peaks removed; the header stamps `spx:post_fusion_cap`. Off, the output is
+  unchanged (same semantic digest on HeLa 10 ng and K562 9905). `-diag:selftest_twins` covers the keyed fold and the cap.
+- **Foreign precursor envelopes (`-assembly:foreign_precursor_weight`, off by default).** A diaPASEF window passes
+  every precursor inside it, and the unfragmented envelope of a co-isolated precursor lands in the spectrum as intense
+  fragments (about half of the 20 most intense peaks are not the peptide's, against 30 % in DDA). Below 1, fragments on
+  the envelope of another of the run's precursors in the same window (apex within the gate's retention-time window,
+  1/K0 within `-assembly:foreign_precursor_dim` 0.015, neither a twin nor this ion called again, i.e. a mono on the
+  other's isotope grid within 30 ppm) are multiplied by the weight before the same-bin merge and `max_fragments` (0
+  removes them, freeing their cap slots; the cap key follows the attenuated intensity), when at least
+  `-assembly:foreign_precursor_min_iso` (2) of its mono…M+3 positions carry a fragment within
+  `-assembly:foreign_precursor_ppm` (10). Fragments within 30 ppm of the precursor's own mono…M+3 are never touched
+  (stripping them lost 2.3 % of peptides, below). The two own-ion tests take 30 ppm, not the match tolerance: an ion's
+  residual peaks scatter tens of ppm around its MS1 mono grid, and with both tests at 10 ppm 15 % of the fragments
+  removed on HeLa_22 were the precursor's own isotopes, taken by the same ion called again with a mono just outside
+  the test. A `[foreign]` log line counts what it did; the header stamps `spx:foreign`. The default output is
+  unchanged (same semantic digest).
+- **Fragment fusion (`-assembly:fragment_fuse_ppm`, `-assembly:fragment_fuse_mode`, off by default): one peak per
+  fragment ion.** The mobility picker keeps 1.4–2.3 flight-time bins of a fragment ion that spans 3.8–6.9, so one ion
+  becomes several traces and several output peaks 5–20 ppm apart, each written with its own apex intensity: on K562
+  9905 49.8 % of the b/y ions have at least 2 peaks within 20 ppm (chance 12.9 %, DDA 0.6 %), and the 1.5.0 same-bin
+  merge, which reaches only an exact bin, does not change that. Above 0, a spectrum's fragments within that many ppm
+  (at most 50) are fused after the same-bin merge and before `min_fragments` and `max_fragments`: the fused peak takes
+  the sum of its members' emitted intensities, their intensity-weighted m/z and their best cap key, so the cap ranks
+  whole ions and the slots of an ion's pieces refill. `anchored` (the default mode) takes the fragments strongest first
+  (ties: lower m/z), each unfused one taking every unfused fragment within the tolerance of its own m/z; `linkage` joins
+  m/z neighbours within the tolerance of the previous member, the group's span capped at twice the tolerance (a
+  post-hoc single-linkage fusion chained past 20 ppm). Post hoc on the 1.5.0 K562 9905 output, 20 ppm gave MSFragger
+  +1.6 % (anchored) / +2.1 % (single linkage) and Sage +3.7 % / +5.6 %, Sage entrapment FDP 1.18 % to 1.21 % / 1.25 %;
+  a 25-ppm bound keeps 98 % of an ion, 15 ppm 72 %. A spectrum whose fragments fuse below `min_fragments` is not
+  written. Smoke on HeLa_22 (10 ng, 64 threads), anchored 20 ppm: 7.8 % of the fragments reaching the cap fuse away
+  (1.71 M groups, mean size 2.4; linkage 8.5 %, 25 ppm 9.3 % / 9.9 %), 7 fewer spectra of 53,715 (12 fell below
+  `min_fragments`), the written peaks with another peak within 20 ppm drop from 10.3 % to 3.9 % (among each spectrum's
+  150 most intense from 19.9 % to 6.5 %; with the twin fold off from 12.3 % to 0.42 %, linkage 0.04 %: the rest are
+  the fold's union of its members' peaks, which it fuses only within 10 ppm), peaks per spectrum 404 to 402 (the
+  freed slots refill), wall time unchanged. K562 9905: 18.6 % fused away, the spectrum count unchanged, wall +3 %
+  (3:37 to 3:43, the second run on a busier node), peak RSS -3.7 %. With the other tuning options: the fused
+  intensities are the `frag_intensity` amplitudes after the `foreign_precursor_weight` attenuation; a fused peak is
+  `anchor_rescue`-rescued when its strongest member was; with `post_fusion_cap` it carries its fused key into the
+  twin fold. Fused together with `foreign_precursor_weight 0`, `anchor_rescue` and `post_fusion_cap` (anchored and
+  linkage, 20 ppm), and with all five tuning options (anchored 20 ppm; linkage 25 ppm with `frag_intensity sum` and
+  foreign weight 0.1), the output is the same at 16 and 100 threads (anchored 20 ppm also at 64 threads with 4 cells
+  per tile). A `[fuse]` log line counts the fragments in, the peaks out, the groups fused, their mean size and the
+  spectra that fell below `min_fragments`; the header stamps `spx:fragment_fuse`. The default output is unchanged
+  (same semantic digest).
+- **The five tuning options together (integration branch `tune/r1`).** Each option alone behaves as on its own
+  branch; all five off is the 1.5.0 output. Where two act on the same fragments: `-gate:anchor_rescue` fragments take
+  the `-assembly:frag_intensity` amplitude like gate-passing ones (their cap key stays the IM-weighted apex, as for every
+  fragment), and the `[fragint]` counts include them. `-assembly:foreign_precursor_weight` sees the rescued fragments
+  like any other (their apex is carried for its cap-key rescale, and removal at weight 0 keeps the rescued flags in
+  step, so the `[anchor]` written-peak counts stay exact); both happen before the same-bin merge and the cap.
+  `-assembly:post_fusion_cap` carries the cap key as it stands after the foreign rescale and the rescue, and its
+  ties fall to the written intensity, which is the `frag_intensity` amplitude when that is on; the `[anchor]`
+  written-peak counts are taken before the fold and the post-fusion cap. `-charge:mono_profile_check` changes the
+  precursor list that `-assembly:foreign_precursor_weight` draws its candidates from: the own-envelope protection
+  follows the moved monoisotope (mono…M+3 of the new one), so the released lighter trace at its M−1 is outside it, but
+  a precursor that trace seeds lies on this precursor's isotope grid and is skipped as the same ion, so it never turns
+  that position into a foreign envelope; the extra precursors seeded by released traces add candidates and spectra,
+  so the `[foreign]` counts are not comparable across `mono_profile_check` settings.
+
+- **`-charge:mono_profile_check v2` (off by default): isotope-position monoisotope check.** `true` (v1) cut the M-1
+  calls on K562 9905 from 9.9 % to 3.7 % but raised the total isotope error from 18.5 % to 39.7 % (true monoisotopes
+  rejected) and the spectra by 28 %: `findPartner` takes the first candidate in m/z order, which for a third of true
+  steps sits more than 0.01 1/K0 from the seed, and ion-mobility slicing splits one isotope over several traces, so a
+  single trace's profile and intensity are noisy. `v2` sums the apex intensity of every MS1 trace, claimed or not, at
+  each isotope position of the seed (the partner m/z tolerance, `gate:delta_rt`, `-charge:mono_position_im_box` 0.02
+  1/K0). Only the walk's leftmost step is tested (an identified walk has at most one spurious step, and it is the
+  leftmost): it is rejected when PS(−j)/PS(−j+1) × λ, with averagine's λ = max(0.1, 0.000594 × neutral mass), is below
+  `-charge:mono_position_min_ratio` (0.15), and the monoisotope moves one isotope right;
+  `-charge:mono_position_iterate` (`true`; `false` = one step only) repeats the test on the new leftmost step while it
+  fails. If nothing was rejected and the walk ended on a miss, the next lighter position becomes the monoisotope,
+  without claiming its trace, when its ratio is ≥ `-charge:mono_position_extend` (0.5; 0 = off). Claims, charge and
+  `spx_n_isotopes` never change, so the same precursors are inferred (the spectrum count can still shift where a moved
+  mass crosses a window edge or the twin fold). The test reads only the fixed trace arrays (no speculation
+  dependencies) and sums in m/z order (deterministic). Logged as `[monocheck]`, stamped `spx:monocheck`. `false`
+  output unchanged; `true` unchanged. Screened 2026-09-29 (iteration 1: im_box 0.01, min_ratio 0.2, extend 0.6; n = 1,
+  K562 9905, HeLa 10 ng and 100 ng): with iterate the isotope error of identified K562 precursors falls from 18.5 % to
+  8.1 % (M-1 9.9 % to 1.4 %), peptides rise with both engines on all three runs (Sage / MSFragger +1.0 / +0.7 %, +0.4
+  / +0.2 %, +1.5 / +4.8 %), entrapment is lower on all three, and spectra fall by 1.6-5.6 % (seeds of one ion that sat
+  one isotope apart now fold into twins). Without iterate: 10.3 %. On the 2019 HeLa py3 runs the isotope traces of one
+  ion scatter about 3x wider in 1/K0 than on K562, and the leftmost-step test rejects 12 % of true steps (K562 3 %):
+  the identified 10 ng isotope error rises from 8.6 % to 9.8 %.
+  **Defaults re-tuned (iteration 2):** iterate is on (`-charge:mono_position_iterate` is now a `true`/`false` option,
+  default `true`), `im_box` 0.01 → 0.02, `min_ratio` 0.2 → 0.15, `extend` 0.6 → 0.5. Search-free sweep on the fixed
+  identified release keys (K562 MSFragger/DDA truth; HeLa Sage isotope_error), total isotope error K562 / HeLa 10 ng /
+  HeLa 100 ng: release 18.5 / 9.0 / 18.2 %; iteration-1 settings 7.7 / 10.3 / 14.8 %; new defaults 8.1 / 8.5 / 12.7 %
+  (extend 0.6: im_box 0.015 7.7 / 9.5 / 13.5; 0.02 8.0 / 9.3 / 13.1; 0.03 8.6 / 9.1 / 13.1; 0.02 with min_ratio 0.10
+  8.9 / 8.3 / 13.1). Of the ten settings tried the new defaults have the lowest error summed over the three runs; at the
+  iteration-1 settings (im_box 0.01) the HeLa 10 ng error stays above the release.
+  Screened (iteration 2, n = 1; Sage / MSFragger peptides vs release): K562 +0.6 / +0.3 %, HeLa 10 ng +0.4 / −0.8 %,
+  HeLa 100 ng +1.3 / +4.6 %; entrapment −0.09, +0.02, −0.06 pt; spectra −5.0, −1.9, −4.5 %. Identified K562 isotope
+  error 8.4 % (M-1 2.4 %; iteration 1 with iterate 8.1 %, M-1 1.4 %). Sage isotope error on the peptides both runs
+  identify: HeLa 10 ng 8.5 → 8.2 %, 100 ng 17.6 → 12.3 % (same measure, iteration 1: 8.5 → 9.7 %, 17.5 → 14.3 %).
+  Peptide counts are 0.2-0.5 % below iteration 1's, except at 10 ng (Sage equal, MSFragger −1.0 %); that MSFragger
+  loss sits at the 1 % cut (71 vs 72 decoys; target peptides above hyperscore 20, 22 and 25 equal iteration 1's within
+  4). With `-assembly:im_weight_sigma 0.005`: K562 +8.4 / +4.3 %, 10 ng +3.1 / +3.4 %, 100 ng +6.0 / +5.6 % (above
+  `im_weight_sigma 0.005` alone at 100 ng, which iteration 1 was not), entrapment −0.01, +0.05, +0.05 pt, K562 isotope
+  error 8.0 %.
+  **Iteration 3: the 1/K0 box follows the run.** `-charge:mono_position_im_box` 0 (the new default) = auto: 3.5 × the
+  90th percentile of the 1/K0 gap between the brightest tenth of the count-walk seeds (commit order) and their nearest
+  MS1 trace one isotope heavier (partner m/z tolerance, `gate:delta_rt`, `charge:iso_im_tolerance`), clamped to
+  [0.01, 0.03]; a value > 0 fixes the box as before. The runs' own p90 is 0.0029 on K562 9905 (box 0.0101, i.e.
+  iteration 1's 0.01), 0.0053 on HeLa 10 ng (0.018) and 0.0063 on HeLa 100 ng (0.022). `min_ratio` and `extend` return
+  to iteration 1's 0.2 and 0.6, whose peptide counts were the higher ones (iterate stays on). To use the run-level box,
+  the v2 decision moved from the greedy loop to a pass after it; it reads the same immutable arrays and changes only
+  `mono_mz`. With a fixed box the output is unchanged: HeLa 10 ng digests equal iteration 2's defaults and iteration 1's
+  settings; 16 and 100 threads give the same digest. The log and `spx:monocheck` report the box and the percentile.
+  Search-free, fixed identified release keys, total isotope error K562 / HeLa 10 ng / HeLa 100 ng: 7.7 / 9.3 / 13.1 %
+  (release 18.5 / 9.0 / 18.2; iteration 1 7.7 / 10.3 / 14.8; iteration 2 8.1 / 8.5 / 12.7).
+  Screened (iteration 3, n = 1; Sage / MSFragger peptides vs release): K562 +1.0 / +0.6 %, HeLa 10 ng +0.5 / −0.6 %,
+  HeLa 100 ng +1.1 / +4.8 %; entrapment −0.09, −0.00, −0.07 pt; spectra −5.6, −1.8, −4.5 %. Identified K562 isotope
+  error 8.2 % (M-1 1.4 %). Sage isotope error on the peptides both runs identify: HeLa 10 ng 8.5 → 8.9 %, 100 ng 17.5 →
+  12.6 %. The 10 ng MSFragger loss (7,165 vs 7,211) is where the 1 % cut falls (71 decoys vs 72): above hyperscore 20,
+  22 and 25 the run keeps 3,171 / 2,353 / 1,436 target peptides, the release 3,143 / 2,318 / 1,418. With
+  `-assembly:im_weight_sigma 0.005`: K562 +8.8 / +5.0 %, 10 ng +3.1 / +3.4 %, 100 ng +5.8 / +5.6 %, entrapment +0.04,
+  +0.05, +0.05 pt, K562 isotope error 7.6 % (M-1 1.4 %); peptides above `im_weight_sigma 0.005` alone on K562 (+1.5 /
+  +1.1 %) and 100 ng (+1.1 / +0.7 %), level at 10 ng (+0.3 / −0.4 %).
+  **Review fix: v2 decides at the final charge.** `charge:im_charge_veto` (on by default) runs after the count walk and
+  re-calls 2+ the z=1 calls that sit on the run's 2+ mobility line (K562 9905: 156,781 of 219,342 z=1 calls), keeping
+  their monoisotope. v2 used to judge those walks at z=1 spacing, where a step of 1.003 m/z is two isotopes of the 2+
+  ion: on the 2,375 identified release keys from such walks the release monoisotope is wrong for 54.5 %, v2 left it
+  wrong for 55.7 % and moved 267 of them two or four isotopes (none onto the right one). v2 now runs after the veto
+  (`monoPositionPass_`), which therefore reads the walks' own monoisotopes as without v2, and judges each walk at its
+  precursor's final charge: a re-called walk's leftmost partner is position −2·nl at 2+, and the positions between are
+  read like any other (the tested sums do not need a claimed partner); where such an in-between position is empty
+  in the box, which is no evidence against a step the walk never took there, the step is compared over two positions
+  against the Poisson M+2/M0 = λ²/2. The extension (B) also no longer fires after a
+  `charge:mono_averagine_guard` stop, which is not a miss, and the "back onto the seed" count no longer counts
+  monoisotopes that `charge:mono_averagine_select` had already put there. Offline replica on the fixed K562 keys
+  (agrees with the tool on 99.75 % of same-charge walks): re-called walks 55.7 % → 22.0 % not monoisotopic, all keys
+  10.6 % → 8.7 %. With `-charge:mono_position_iterate false`, a rejected step of a re-called walk could leave the
+  monoisotope on an empty in-between position (a bare computed m/z, no trace); it now moves on to the walk's next own
+  position (HeLa 10 ng: 580 of 72,537 monoisotopes sat on no MS1 trace, now 0). The default (`true`) and every
+  same-charge walk are unaffected (HeLa 10 ng digests unchanged).
+  Search-free, fixed identified release keys, total isotope error K562 (DDA-matched) / HeLa 10 ng / HeLa 100 ng:
+  5.3 / 9.0 / 11.5 % (release 18.5 / 9.0 / 18.2; iteration 3 7.7 / 9.3 / 13.1); at 10 ng M-1 falls 2.4 → 1.2 % and
+  M+1 rises 6.2 → 7.0 %. Screened (review arm, n = 1; Sage / MSFragger peptides vs release): K562 +0.9 / +0.4 %,
+  HeLa 10 ng +0.5 / +0.1 %, HeLa 100 ng +0.9 / +4.4 %; entrapment −0.11, +0.16, −0.08 pt; spectra −6.5, −2.3, −5.6 %;
+  identified K562 isotope error 5.5 % (M-1 1.4 %; DDA 5.5 % on the same keys). The 10 ng entrapment rise (63 vs 55
+  entrapment peptides, CI 0.88-1.42 %) is the 1 % cut moving: the entrapment search is exactly reproducible on the same
+  mzML, and against the previous review build (0.95 %, 66 spectra different) 15 of the 16 extra entrapment peptides
+  come from spectra present unchanged in both, where they sat at q 0.010-0.021. With
+  `-assembly:im_weight_sigma 0.005`: K562 +8.6 / +4.9 %, 10 ng +3.1 / +3.7 %, 100 ng +5.6 / +4.3 %, entrapment +0.02,
+  +0.05, +0.02 pt, K562 isotope error 5.2 % (M-1 1.4 %).
+
 ## v1.5.0 — 2026-09-29
 
 - **Low-intensity runs: an adaptive co-elution gate.** At 10 ng the 1.4 gate stripped most true fragments: a faint ion
diff --git a/README.md b/README.md
index ce1c81f..8d9fd7b 100644
--- a/README.md
+++ b/README.md
@@ -31,6 +31,11 @@ patched OpenMS source tree but lives outside it. Earlier releases were named spe
    trimmed to 120 s around their apex. Traces that sit one isotope apart at the same mobility are walked into
    envelopes: the walk assigns the monoisotopic peak and a charge from 1 to 5, an ion-mobility veto re-calls a z = 1
    envelope that lies on the run's own 2+ trend line, and hypotheses without an isotope partner are dropped.
+   By default (`-charge:mono_profile_check v2`) the monoisotope is then checked against the summed MS1 intensity at
+   the isotope positions near the seed's mobility: a leftmost step that is too weak for averagine is rejected, and a
+   walk that stopped one isotope short is extended; claims do not change. `true` instead accepts a lighter peak only
+   if its elution profile and mobility match the seed's (otherwise the walk stops before that peak and leaves it
+   free); `false` turns the check off.
 3. **Fragments and the gate.** For every isolation window and 600-s cell, the tile's MS2 frames are read and fragment
    mass traces are detected in 12 flight-time bands on the integer TOF axis, then split and trimmed like the precursors.
    Before tracing, the peaks of one frame that share a flight-time bin at nearly the same 1/K0 are merged into one
@@ -41,14 +46,25 @@ patched OpenMS source tree but lives outside it. Earlier releases were named spe
    grid, with at least 3 shared points). A faint precursor — signal in at most 4 window frames, the short tip of an
    elution peak — gets a relaxed gate instead (`-gate:adaptive`): a 6 s window, the correlation shrunk toward a prior
    of 0.6 from as little as one shared point, an apex inside the precursor's span, and traces too short to correlate
-   judged by their centre.
+   judged by their centre. With `-gate:anchor_rescue true` (off by default) a well-sampled precursor whose own fragments
+   correlate strongly (the anchors) also takes back weak fragments the gate rejected for too few points or a low
+   correlation, when their apex and their points follow the anchors' consensus elution profile.
 4. **Assembly and output.** The accepted fragments are ranked by evidence — max(r, 0) × ln(1 + intensity) × (1 + shared
    points) — and the top 500 kept;
    fragments that still share a flight-time bin are merged into one peak first (`-assembly:merge_same_bin`), so no
-   spectrum carries two peaks at one m/z; a spectrum with at least 3 of them is written with a synthetic precursor (apex m/z, charge, retention time, 1/K0),
-   each fragment's emitted intensity multiplied by its correlation raised to `-assembly:corr_power` (2 by default, so squared; 1 for faint precursors, `-gate:faint_corr_power`). Spectra are sorted per tile,
+   spectrum carries two peaks at one m/z. Before that merge, `-assembly:foreign_precursor_weight` (0 by default,
+   which removes them; 1 = off) attenuates the residual isotope envelope of another precursor isolated with this one:
+   one of the run's own precursors in the same window, co-eluting within the gate's window and 0.015 1/K0, with at
+   least 2 of its mono…M+3 positions among the fragments; the precursor's own envelope is never touched. After the
+   merge, `-assembly:fragment_fuse_ppm` (25 by default, `anchored`; 0 = off) fuses the pieces of one fragment ion that
+   the mobility picker split over neighbouring flight-time bins, peaks within that many ppm, into one peak with their
+   summed intensity, so the cap ranks whole ions and the freed slots refill. A spectrum with at least 3 fragments is written with a synthetic precursor (apex m/z, charge, retention time, 1/K0),
+   each fragment's emitted intensity multiplied by its correlation raised to `-assembly:corr_power` (2 by default, so squared; 1 for faint precursors, `-gate:faint_corr_power`).
+   That intensity is the fragment trace's apex by default; `-assembly:frag_intensity core` sums the trace over the
+   frames around the precursor's apex instead, and `sum` over the precursor's whole span. Spectra are sorted per tile,
    a precursor claimed twice is folded into one spectrum that carries the union of the members' fragment lists
-   (`-assembly:twin_im_tolerance`), and the tile is serialised in parallel. The header records every setting that shaped the output.
+   (`-assembly:twin_im_tolerance`; with `-assembly:post_fusion_cap` a folded spectrum is cut back to `max_fragments` by
+   the same `cap_rank` key, which each peak carries through the merge and the fold), and the tile is serialised in parallel. The header records every setting that shaped the output.
 
 <p align="center"><img src="assets/algorithm.svg" alt="The co-elution gate and the assembly of one pseudo-spectrum" width="1000"></p>
 
@@ -224,6 +240,8 @@ and trying `-trace:detector openms` on your own data. Charge and FDR: `-charge:m
 | `-charge:im_veto_band` | 2.5 | half-width of that band in MAD-sigma of the fit residuals |
 | `-charge:iso_im_tolerance` | 0.05 | 1/K0 tolerance for isotope partners |
 | `-charge:mono_averagine_guard`, `-charge:mono_averagine_select` | 0, off | averagine-based corrections of the monoisotope; off by default, neither improves identifications |
+| `-charge:mono_profile_check`, `-charge:mono_profile_min_corr`, `-charge:mono_profile_max_dim` | v2 (false = off), 0.6, 0.015 | `true` checks each leftward step of the count walk for the winning charge: the lighter trace becomes the monoisotope only if its MS1 profile correlates with the seed's (Pearson ≥ min_corr; fewer than 3 shared frames pass unchecked) and its 1/K0 is within max_dim of the seed's; the walk stops at the first failure and the rejected trace stays unclaimed. Charge and envelope size are unchanged. **Changes output**; under evaluation |
+| `-charge:mono_profile_check v2`, `-charge:mono_position_min_ratio`, `-charge:mono_position_im_box`, `-charge:mono_position_extend`, `-charge:mono_position_iterate` | –, 0.2, 0 (auto), 0.6, true | `v2` tests isotope positions, not the claimed partner: PS(k) sums the apex intensity of every MS1 trace, claimed or not, at the seed's isotope position k (partner m/z tolerance, `gate:delta_rt`, im_box 1/K0 of the seed). im_box 0 (auto) sizes the box from the run's own isotope scatter: 3.5 × the 90th percentile of the 1/K0 gap between the brightest tenth of the seeds and their nearest trace one isotope heavier, clamped to [0.01, 0.03] (0.0101 on K562 9905, 0.018 and 0.022 on the 2019 HeLa py3 10 and 100 ng runs); a value > 0 fixes it. The walk's leftmost step j is rejected when PS(−j)/PS(−j+1) × λ < min_ratio (λ = max(0.1, 0.000594 × neutral mass); 0 = no test), and the monoisotope moves one isotope right; `iterate` (`true`) repeats the test on the new leftmost step while it fails, `false` tests one step only. If nothing was rejected and the walk ended on a miss, the next lighter position becomes the monoisotope (its most intense trace, not claimed) when its ratio is ≥ extend (0 = off). Each walk is judged at its precursor's final charge, after `charge:im_charge_veto` (a z=1 walk re-called 2+ is read at 2+ spacing). Claims, charge and envelope size are unchanged. The default since the 2026-09-29 tuning (rc-b); **changes output** |
 
 **Co-elution gate (`gate:`)**
 
@@ -250,20 +268,34 @@ and trying `-trace:detector openms` on your own data. Charge and FDR: `-charge:m
 | `-gate:short_center_tol` | 0.5 | centre tolerance as a fraction of the precursor half-width |
 | `-gate:short_min_points` | 1 | fewest points of a short fragment trace |
 | `-gate:fragment_delta_im` | −1 | 1/K0 window of the gate alone (tracing keeps `delta_im`); −1 = `delta_im` |
+| `-gate:anchor_rescue` | false | `true`: rescue weak fragments of a well-sampled precursor (signal in more than `faint_max_frames` window frames, whatever `adaptive` is set to). When at least `anchor_min_count` fragments pass the gate at a correlation of `anchor_min_corr` or more, their profiles, each scaled to unit maximum, are summed into a consensus; a fragment trace inside the retention-time and 1/K0 windows that the gate rejected only for too few shared points or by `min_correlation`, with at least 2 points, joins when its apex is within one cycle of the consensus apex and its points correlate with the consensus by `anchor_rescue_corr` or more (Pearson over its own points; a 2-point trace needs both points at half the consensus maximum or more, rising or falling with it, and scores `anchor_rescue_corr`). Its emitted intensity and cap key use that score, capped at `anchor_min_corr` (the cap key's shared points are, as for every fragment, the frames it shares with the precursor). Logged as `[anchor]`, stamped `spx:anchor`; `DIASPEXTRACT_GATE_DUMP` rows carry the fate `rescued`. **Changes output** |
+| `-gate:anchor_min_count` | 3 | fewest anchors a precursor needs for `anchor_rescue` |
+| `-gate:anchor_min_corr` | 0.8 | least gate correlation of an anchor; also the cap on a rescued fragment's score |
+| `-gate:anchor_rescue_corr` | 0.7 | least correlation of a rejected fragment's points with the anchor consensus |
+| `-gate:anchor_max_rescued` | 50 | most rescued fragments per spectrum, best score first (ties by m/z) |
 
 **Assembly (`assembly:`)**
 
 | option | default | meaning |
 |---|---|---|
 | `-assembly:min_fragments` | 3 | emit a spectrum only if at least this many fragments remain after the gate and the same-bin merge (checked before the cap below) |
+| `-assembly:foreign_precursor_weight` | 0 (remove; 1 = off) | multiply the fragments on the residual isotope envelope of ANOTHER precursor isolated with this one by this weight (0 removes them) before the same-bin merge and `max_fragments`; the cap key follows the attenuated intensity. A foreign precursor is one of the run's precursors in the same window, apex within the gate's retention-time window of this one's, 1/K0 within `-assembly:foreign_precursor_dim` (0.015), neither a twin (mono within 0.01) nor this ion called again (either mono on the other's isotope grid within 30 ppm); its envelope counts when at least `-assembly:foreign_precursor_min_iso` (2) of mono + k × 1.00335/z, k = 0…3, carry a fragment within `-assembly:foreign_precursor_ppm` (10). Fragments within 30 ppm of the precursor's own mono…M+3 are never touched. Logged as `[foreign]`, stamped `spx:foreign`. Experimental |
+| `-assembly:foreign_precursor_ppm` | 10 | the m/z tolerance between a foreign envelope position and a fragment; the own-ion tests take the larger of this and 30 ppm. Residual precursor peaks scatter widely around the MS1 mono grid: on HeLa_22 (10 ng) about half of them lie beyond 10 ppm and three quarters within 20 ppm |
+| `-assembly:foreign_precursor_dim` | 0.015 | the largest 1/K0 distance between this precursor and a foreign one |
+| `-assembly:foreign_precursor_min_iso` | 2 | how many of a foreign envelope's four positions (mono…M+3) must carry a fragment before its fragments are attenuated (1–4) |
 | `-assembly:merge_same_bin` | true | merge a spectrum's fragments of one flight-time bin (one exact m/z with the OpenMS detector) into one peak before `max_fragments`: members overlapping the strongest in retention time are summed, retention-time-disjoint pieces dropped. Two peaks at one m/z stall the fragment matching of OpenMS-based search engines. **Changes output** |
-| `-assembly:max_fragments` | 500 | keep at most this many, top-ranked; keep it at or above `min_fragments`. Applied before the twin fold below, so a folded spectrum can hold more |
+| `-assembly:fragment_fuse_ppm` | 25 (0 = off) | fuse a spectrum's fragments within this many ppm (at most 50) into one peak, after the same-bin merge and before `min_fragments` and `max_fragments`. The mobility picker keeps 1–2 flight-time bins of a fragment ion that spans 4–7, so one ion becomes several peaks 5–20 ppm apart (half of the b/y ions on K562, against 0.6 % in DDA), each with its own apex intensity. A fused peak takes the sum of its members' emitted intensities, their intensity-weighted m/z and their best `cap_rank` key, so the cap ranks whole ions and the freed slots refill; a spectrum can fall below `min_fragments`. A `[fuse]` log line counts the fragments in, the peaks out, the groups fused and their mean size; stamped `spx:fragment_fuse`. 25 ppm `anchored` is the default since the 2026-09-29 tuning (rc-b); **changes output** |
+| `-assembly:fragment_fuse_mode` | anchored | how `fragment_fuse_ppm` groups: `anchored` takes the fragments strongest first (ties: lower m/z), and each one not yet fused takes every unfused fragment within the tolerance of its own m/z; `linkage` walks them in m/z order and joins a fragment to the previous one's group when it lies within the tolerance of it and within twice the tolerance of the group's first member (single linkage with a capped span) |
+| `-assembly:max_fragments` | 500 | keep at most this many, top-ranked; keep it at or above `min_fragments`. Applied before the twin fold below, so a folded spectrum can hold more (unless `post_fusion_cap`) |
 | `-assembly:cap_rank` | evidence | which fragments survive `max_fragments`: `evidence` ranks by max(r, 0) × ln(1 + I) × (1 + shared points), so long correlated support outranks an intense one-frame coincidence; `corr_inten` by gate score × intensity (the 1.4 key); `umpire` by max(r, 0)² × ln(1 + I). r is the raw co-elution score before shrinkage (Pearson, or the `logoverlap` score) |
 | `-assembly:corr_power` | 2 | multiply each emitted fragment's intensity by its correlation to this power; 0 = off. 2 gives +8–10 % Sage peptides over 0 on three files, and +4 % MSFragger peptides on the one file measured with it |
-| `-assembly:im_weight_sigma` | 0 = off | additionally weight fragments by their 1/K0 distance to the precursor (Gaussian, this sigma); this also changes which fragments survive the cut. 0.005 gave up to 7 % more Sage peptides and no change on MSFragger |
+| `-assembly:im_weight_sigma` | 0.005 (0 = off) | additionally weight fragments by their 1/K0 distance to the precursor (Gaussian, this sigma); this also changes which fragments survive the cut. 0.005 gave up to 7 % more Sage peptides and no change on MSFragger |
+| `-assembly:frag_intensity` | apex | the base amplitude of an emitted fragment, before the 1/K0 weight and `corr_power`: `apex` the trace's maximum in one frame; `core` the trace summed over the `frag_core_frames` window frames centred on the precursor's apex frame (the same frames for every fragment of the precursor); `sum` the trace summed over the precursor's span, from its first to its last frame with signal (gaps included). A fragment with no point there takes its point nearest the precursor's apex. Fragments rescued by `gate:anchor_rescue` take the same amplitude. The gate and the `cap_rank` key (still the apex) are unchanged; only the steps that weigh by intensity move a few peaks (the same-bin merge keeps the strongest member's m/z, the twin fold fuses at the intensity-weighted m/z): on HeLa 10 ng 99.9 % of the peaks lie within 10 ppm of the `apex` run's. Experimental; **changes output** when not `apex` |
+| `-assembly:frag_core_frames` | 3 | `frag_intensity core`: the number of window frames (odd, 1–15) |
 | `-assembly:require_isotope_support` | true | drop precursor hypotheses without an isotope partner; `false` doubles the spectra, runs about 7× slower and identifies fewer peptides |
 | `-assembly:default_charge` | 2 | charge given to a precursor left without a charge call (only matters when guessed precursors are kept) |
 | `-assembly:twin_im_tolerance` | 0.005 | fold spectra that claim one precursor twice — same MS1 frame, same charge, precursor m/z within 20 ppm, 1/K0 within this tolerance — into one, which takes the union of the cluster's fragments, peaks within 10 ppm fused (so it can exceed `max_fragments`); −1 = off, the spectra of 1.3 (0 still folds twins of identical 1/K0). On a 2-hour HeLa run (PXD029836): 24 % fewer spectra for 0.2 % of the peptides on both engines, entrapment FDR 0.98 % with the fold against 0.98 % without |
+| `-assembly:post_fusion_cap` | false | re-apply `max_fragments` after the twin fold: every peak carries its `cap_rank` key (a 32-bit float) through the same-bin merge and the fold, where a fused peak keeps its members' best key, and a spectrum over the cap keeps its top-ranked peaks (ties: higher intensity, then lower m/z). A `[recap]` log line counts the spectra cut and the peaks removed; stamped `spx:post_fusion_cap`. Experimental. **Changes output** |
 
 **MS1 denoising (`dnoise:`)** — a port of dnoise v0.1.0's MS1 path (Garrett, Diedrich & Yates III,
 bioRxiv 2026.08.27.747603; MIT, `LICENSES/dnoise-MIT.txt`), applied to the raw points of every MS1 frame of a Bruker
@@ -287,14 +319,15 @@ trace), `charge state`, the precursor's retention time and 1/K0, and the isolati
 header carries twenty-four `spx:` userParams that make any file attributable to the configuration that produced it: the
 detector and calibration (`spx:detector`, `spx:mz_calibration`, `spx:require_isotope_support`, `spx:corr_power`,
 `spx:pearson_G` (the correlation support, always `frames`), `spx:im_weight_sigma`), the twin fold (`spx:twin_merge`: its relation and
-tolerance, or `off`), the co-elution gate (`spx:gate_adaptive`, `spx:gate_faint`, `spx:gate_shrinkage`,
+tolerance, or `off`; `spx:post_fusion_cap` is added when `-assembly:post_fusion_cap` is on), the co-elution gate (`spx:gate_adaptive`, `spx:gate_faint`, `spx:gate_shrinkage`,
 `spx:gate_colocation`, `spx:gate_short_traces`), the cap ranking (`spx:cap_rank`), the same-bin merges
 (`spx:same_bin_merge`), MS1 denoising (`spx:dnoise_ms1`, `spx:dnoise_ms1_params`,
 `spx:dnoise_ms1_points`), the cell grid and tiling (`spx:tile_rt_sec`, `spx:tile_cells_per_tile`, `spx:tiles`,
 `spx:tile_boundaries`, `spx:tile_source`), the band edges (`spx:band_edges`) and the frozen frame table
-(`spx:frame_table`). `spx:mz_calibration` starts with `tdf_table_modeltype1` (mzPeak input appends how the table was recovered), or is
+(`spx:frame_table`); `-gate:anchor_rescue true` adds `spx:anchor`. `spx:foreign` is added when `-assembly:foreign_precursor_weight` is below 1, `spx:fragint` when `-assembly:frag_intensity` is not `apex`, `spx:fragment_fuse` when `-assembly:fragment_fuse_ppm` is above 0. `spx:mz_calibration` starts with `tdf_table_modeltype1` (mzPeak input appends how the table was recovered), or is
 `bruker_sdk`, `legacy_chord_APPROXIMATE`, `mzpeak_two_point_transform` (an mzPeak archive read through its approximate
-transform, on request) or `unset` (an mzML input, which carries its m/z as is).
+transform, on request) or `unset` (an mzML input, which carries its m/z as is). With
+`-charge:mono_profile_check true` or `v2` the header also carries `spx:monocheck` (its settings and how many monoisotopes moved).
 
 ## Layout
 
```

(end of brief)
