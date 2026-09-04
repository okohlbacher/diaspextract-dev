• I'll read the required files first, then deliver the adversarial review.

• Now the final section of the source, lines 2001–2864.

• Let me verify the actual benchmark configuration against the shipped defaults.

• I've read all 2,864 lines of `DIAPseudoSpectra.cpp`, all of `MzPeakStreamLoad.h`, the docs, and cross-checked the bench harness configs. Findings below, ranked within each section. Where I verified something is *not* a problem, I say so.

  ---

  ## 1. CORRECTNESS AND SAFETY

  First, the things I checked and am clearing: the window loop has no data race I can find — `win_out[wi]` per-window buckets, `pslot[pi-plo]` pre-sized per-precursor slots (`DIAPseudoSpectra.cpp:2474-2484`), `pdense` firstprivate (`:2475`), `fanout_hist` and `worker_err` under criticals, and a canonical total-order sort (`:2606`) make accumulation order deterministic. The MS1 pick path (`flushMS1_`, `:573-600`) is only ever entered from the serial consumer callback, picks in parallel into indexed slots, and appends in order — clean. All `--`-style decrements I found are guarded (`prev(it)` at `:1442` is begin-checked; the FWHM walks at `:1925`,`:1930` are index-bounded). So the specific defects the project history warns about are, this time, handled. The remaining problems are elsewhere.

  **S1 — `winKey` quantizes isolation-window edges to centi-Da, silently misassigning edge precursors.** `DIAPseudoSpectra.cpp:1723-1725` keys windows on `(int)llround(lo*100)`, and `:2293-2294` reconstructs `win_lo/win_hi` from the rounded key. Precursor membership (`:2394-2395`) is then tested against the *rounded* edges, not the true ones. A precursor within ±5 mDa of a window boundary is silently included in or excluded from the wrong window, and two windows whose edges agree to 0.01 Da merge into one bucket. This is exactly the "silently wrong, looks like results" class: it shifts a small number of precursors' fragment content with no log line. Smallest fix: quantize at 1e-6 (`llround(x*1e6)` into `long long`), which keeps the map key exact for any physically distinct window.

  **S1 — MS1 traces are never filtered for non-finite values; the fragment path is.** `:2362-2364` erase-remove_if's `frag_traces` on `isfinite(mz/rt/im)`, but no equivalent exists for `ms1_traces` before the sorts at `:1998` and `:1110`. One NaN m/z in a trace makes the `<` comparator violate strict weak ordering — `std::sort` on a non-strict-weak-order is UB: arbitrary permutation, out-of-bounds reads in some libstdc++ builds, or a silently scrambled seed order that still produces plausible-looking peptides. `MassTrace` centroids can be NaN on degenerate input. Fix: copy the three-line filter from the frag path to right after the MS1 `detectTraces_` call.

  **S2 — `FragGrid::off` is `uint32_t` with no overflow guard.** `:276`, `:725`, `:736`. The comment at `:272` cites 8.5 M fragments/window; at ~510 support points/fragment the CSR offsets wrap 2^32 and every fragment's support range becomes garbage — no crash, wrong correlations everywhere. Today it's ~25x away from the limit, but nothing checks it, and the failure mode is invisible. Fix: one `if (g.flat.size() > UINT32_MAX) throw` in `buildFragGrid`.

  **S2 — `n_isotopes` is off by one in the envelope path when the seed is not the monoisotope.** `:1338` sets `pc.n_isotopes = 1 + best.partners.size()`, but `members` excludes the seed (`:1271`,`:1277`). With `lead>0` (seed is M+1/M+2 of the envelope) the count omits the seed, so a genuine 4-isotope envelope reports 3. This metadata is stamped into every mzML as `spx_n_isotopes` (`:1656`) with an explicit invitation for open-search delta-mass correctors to trust it, and it drives the `SPEXTRACT_MIN_ISOTOPES` gate. Fix: count distinct `{mono} ∪ members ∪ {seed}`.

  **S2 — `charge:ambiguity_margin` is dead code in the default mode, and the README's falsification table measured that dead code.** The ambiguity block (`:1345-1357`) is only reachable in the envelope branch; the count branch `continue`s at `:1246`. `charge:scoring` defaults to `count`. `docs/dataset D-BASELINE.md:100` admits "it was *unreachable* in count mode, so it is untested rather than falsified" — yet `README.md:162-172` presents a four-row falsification table ("0.5 → 8,408, -0.04%…") measured against the `split_count` 8,411 arm, i.e. count mode, where the parameter *cannot fire*. The recorded near-zero deltas are the noise floor of a no-op, not evidence about charge hedging. This is the project's own "measurement that looked like a result" failure mode, in the released README. Fix: either implement the margin in count mode and re-run, or rewrite the README section to say "untested in the shipping configuration" — and the help string (`:851`) must state "envelope mode only".

  **S2 — The recorded `consolidate` falsification was measured with a dead IM gate.** The comment at `:2794-2797` admits `getDriftTime()` "returned -1 always, so the mobility gate NEVER FIRED — every consolidate result to date merged on (RT, m/z, charge) only." The help string at `:812` still cites "-12.7% peptides at 5 s" as the falsification evidence, and `merge:rt_window`'s help (`:805`) cites consolidate's number too. Under the project's own keep-falsified-options convention, the recorded negative must describe the shipped code; this one doesn't. Same class as the admitted E5/apportion confound. Fix: annotate the help and dataset D-BASELINE entry "falsified on a build with the IM gate inert; re-measurement owed" — or re-run, it's a default-off option and one dataset D run.

  **S3 — negative integer options wrap through `Size`.** `:1712-1713`: `(Size)getIntOption_("assembly:min_fragments")` — no `setMinInt_` anywhere. `-assembly:min_fragments -1` wraps to ~1.8e19, `frags.size() < min_frags` is always true, and the tool emits *zero* spectra successfully. Silent, valid-looking mzML of nothing. Fix: `setMinInt_("assembly:min_fragments", 0)` and same for `max_fragments`, `max_charge`, `charge:min_charge`.

  **S3 — `MzPeakExactMz::exact` calls `llround` without an input finiteness guard** (`MzPeakStreamLoad.h:172`). The output is checked (`isfinite(e)` at `:174`) but `llround(NaN)` is UB on the way in — the same bug class the `compactify` comment (`:424-426`) proudly fixed. One-line guard.

  **S3 — minor robustness in the mzPeak loader, all low-severity:** the `/tmp/spx_mzpeak_tdf_XXXXXX` file leaks on every throw path between `mkstemp` and `std::remove` (`MzPeakStreamLoad.h:130-159`); the parquet footer length `flen` is trusted without a `flen < st.size` check (`:104-109`), so a corrupt archive requests a huge allocation instead of a clean error; `MzPeakExactMz` reads `SPEXTRACT_MZPEAK_TDF` with no size cap.

  Nothing found: non-deterministic accumulation order (deterministic by construction), shared mutable state in the parallel pick, iterator invalidation in the merge/consolidate walks, float equality traps (the `invnorm == 0.0` compares are intentional sentinel checks).

  ---

  ## 2. CODE VERSUS DOCUMENTATION

  **The headline defect: shipped defaults do not produce the published numbers.** `docs/dataset D-BASELINE.md:20-22` states "**Current defaults:** … `ms2_noise_threshold_int 10` … `ms2_split_valleys 7.0`". The registered defaults are `trace:ms2_noise_threshold_int` = **100.0** (`:780`) and `trace:ms2_split_valleys` = **0.0** (`:788`). Every benchmark run overrides them: `bench/run_open.sh:42` and every `bench/plan_*.yaml` set 10 and 7.0 — `bench/plan_dechim.yaml:15` even comments "code-default is 100 but the baseline runs it at 10". A stranger running the README's exact command gets a fragment apex gate 10x stricter and no MS2 valley splitting, and cannot reproduce a single number in the README table. For a v0.3.0 release either the defaults move to the measured values or the README command must spell out the full parameter set. Right now the README's "Run" section is a reproducibility trap.

  **`charge:min_charge` placement: verified consistent.** The gate (`:2051-2058`) runs after the default-charge assignment (`:2032-2033`) and after `require_isotope_support` (`:2037`), before the window loop/extraction (`:2288`), and the predicate `pc.charge > 0 && pc.charge < zmin` keeps charge-0 precursors (which exist only under `open_search_safe` or `default_charge 0`). Docs say "after the isotope-support gate, before extraction, not dropping charge-0" — the code does exactly that. No finding here.

  **Documented features that do not exist in the code.** `CHANGELOG.md` [Unreleased] lists `SPEXTRACT_ISO_COLLAPSE` ("Kept for reproducibility of that finding") and `SPEXTRACT_BACKFILL_RAW` / `SPEXTRACT_BACKFILL_MAXFRAGS` as present env switches. Neither appears anywhere in `src/` (grepped). Given dataset D-BASELINE:715 ("backfill stays OFF") the code was evidently pulled after falsification — but then the CHANGELOG's "Added" section is false, and convention (a) ("kept as default-off options to stop them being retried") is violated in the one place it matters: the option is *not there* to stop a retry. Reconcile before tagging.

  **Falsified-parameter audit:** `rp_max` 0 ✓, `consolidate:delta_rt` 0 ✓, `merge:rt_window` 0 ✓, `apportion` 0 ✓, `mono_averagine_guard` 0 ✓ — all exist at the documented defaults. Two help strings contradict the record though: `assembly:apportion` (`:768`) still says "**Try 1 (linear) or 2 (sharper)**" despite dataset D-BASELINE:416 ("FALSIFIED CLEANLY") — and the CHANGELOG claims falsified flags' help "now say so", which is only true for three of the four. And `assembly:require_isotope_support`'s help (`:853`) quotes "603,858 of 1,528,113 spectra, 78 of 10,036 peptides (2026-07-26)" — measured four algorithm changes ago (pre-apex, pre-`corr_power`, pre-`min_charge`); the current binary cannot reproduce those numbers on any input.

  **Help-string benchmark numbers the code can't produce:** beyond the two above, `consolidate`'s -12.7% (dead IM gate, §1), and `charge:scoring`'s "71.8% vs 49.7%" — fine as literature citations of the DIA-NN reference, but they're stale relative to the README's own current 74.6% arm. Not wrong; dated.

  **Undocumented options:** twelve `SPEXTRACT_*` env vars are read in `src/` (grep-verified list), including result-changing ones — `SPEXTRACT_MZ_ESTIMATOR` changes every reported mass, `SPEXTRACT_DROP_PREC_ISO`, `SPEXTRACT_MIN_ISOTOPES`, `SPEXTRACT_PRECURSOR_LIST`, `SPEXTRACT_PICK_MZ_MODE`. None appear in `--help`, and unlike the INI parameters they are **not recorded** in the mzML's parameter section — and the output stamps (`:2847-2849`) record `corr_power`/`im_weight_sigma`/`require_isotope_support` but *not* the m/z estimator. `SPEXTRACT_MZ_ESTIMATOR=mean DIAPseudoSpectra …` produces a file indistinguishable in provenance from a default run with different masses. That undercuts the `spx:mz_calibration` provenance work. Fix: stamp every result-affecting env override into the output meta values, and list the env vars in one doc.

  **Stale doc references:** the doxygen block (`:65`) points to "PLAN.md / REVIEW.md in the project workspace" — neither ships in the repo.

  ---

  ## 3. CAN A STRANGER BUILD AND REPRODUCE?

  No, not today. Concrete gaps:

  1. **The build instructions are self-contradictory.** README says speXtract "lives outside the OpenMS source tree", then the Build section ends with "rebuild the OpenMS DIAPseudoSpectra target" — an in-tree instruction for an out-of-tree project. The actual standalone commands (`cmake -B build -DOpenMS_DIR=… && cmake --build build`) exist only in a *comment in `CMakeLists.txt:8-9`*. The README's `build/DIAPseudoSpectra` invocation assumes a build directory it never tells you to create.
  2. **Version is stale:** `CMakeLists.txt:2` says `VERSION 0.2.0` on the eve of v0.3.0, and no `setVersion_()` call exists in the tool ctor, so `--help`/`-version` won't report 0.3.0 either.
  3. **The headline command cannot reproduce the headline numbers** (§2, ms2_noise/ms2_split defaults). This is the worst packaging defect because it's silent.
  4. **No public input data.** Every number is on private cohort files dataset D/dataset A/dataset B; CHANGELOG admits "public-data replication not yet done". For a public release, ship or point at one small public diaPASEF file (PRIDE has several) with an expected spectrum count and the `bench/semantic_digest.py` hash of the expected output. Without it, "reproduce a number" is impossible for anyone but the authors.
  5. **The mzpeak+exact-mz link configuration is likely broken standalone.** `MzPeakStreamLoad.h:138-147` calls `SQLite::Database` when `SPX_HAVE_SQLITECPP`, but `CMakeLists.txt:42` links only `mzpeak`, `Parquet::parquet_static`, `Arrow::arrow_static`, `zip` — no `SQLiteCpp`, no `sqlite3`, no `z` (inflate is used at `:132-137`). If SQLiteCpp headers are absent the feature always throws; if present, the link likely fails. Either CI never builds this configuration, or it silently degrades to the throw path.
  6. **Third-party attribution is incomplete for the optional build.** `NOTICE` covers OpenMS; a static-linked Arrow (Apache-2.0), libzip, zlib, SQLiteCpp in a distributed binary carry notice obligations that aren't mentioned anywhere.
  7. **Output semantics are undocumented.** `spx_guessed` and `spx_n_isotopes` userParams — the metadata the open-search story depends on — are explained only in code comments (`:1647-1656`). A user who wants to do the delta-mass correction the tool promises has no spec.
  8. **The load-failure fallback is a footgun on small machines.** `:1766-1770`: if streaming load fails, the tool warns once and falls back to `loadExperiment`, whose 90 GB memory floor is the documented reason streaming exists. On a 64 GB workstation that's an OOM an hour later. At minimum the warning must say "peak memory will now reach ~90 GB; abort if unavailable".
  9. Good, for balance: the calibration fail-closed errors (`MzPeakStreamLoad.h:261-263`, the `SPEXTRACT_ALLOW_CHORD_FALLBACK` path) are models of actionable error messages — they name the cause, the cost, and the exact remedy. Do that everywhere.

  ---

  ## 4. INTERNAL COMMENTARY — WHAT TO KEEP, MOVE, CUT

  My position: the *convention* is sound (keeping falsified options with their negative results is genuinely useful and rare), but the *placement* is wrong. A maintainer's invariant belongs in the source; an experiment log belongs in `docs/`; and `--help` is neither.

  **Keep in source** — these encode invariants a future editor can violate silently:
  - The race-anatomy comments: pre-sized slots vs the reverted shared-`bucket` append (`:2453-2458`), `pdense` firstprivate rationale, exception-capture-before-omp-region notes (`:1812-1815`). This is exactly the knowledge that prevents re-introducing the bug.
  - The halo-exactness argument for banding (`:912-917`) and the quantisation-precision budget (`:375-379`) — these are correctness arguments, not history.
  - The fail-closed calibration rationale and the averagine bound derivation in the mono-guard (`:1167-1183`).
  - One-word `FALSIFIED` markers in help strings, with a pointer to the doc.

  **Move to `docs/`** — lab-notebook content currently in user-facing text:
  - Per-sample benchmark counts inside help strings: `charge:min_charge`'s "29.3% of emission on dataset D and 1.73%… 0.42% vs 15.3%… +0.8/+2.7/+1.4%" (`:837-843`), `require_isotope_support`'s 2026-07-26 counts (`:853`), `corr_power`'s full validation narrative (`:772`). dataset D-BASELINE.md already holds these; `--help` should say what the knob does, the default, and "see docs/dataset D-BASELINE.md". Help text is a UI, not a results section.
  - The arm names: `[route-1]`…`[route-4]`, `[way-2]`, `[way-4]`, `[step-02 sub-arm 2]`, `[content 3]`, `[bench]` — meaningless to anyone without the project history. The *substance* ("gapped envelopes because a sub-threshold M+1 killed the walk") is good and should stay, re-tagged.
  - Reviewer attribution and timestamps: `[adv-review kimi/codex 2026-07-26]` (`:1997`), `[vibe/claude review 2026-09-01]` (`:2840`), `[codex #13]` (`:2843`), "measured 13:55" (`MzPeakStreamLoad.h:329`), "DEFAULT ON (2026-09-02 18:58)" (`:251`). Credit belongs in CHANGELOG/git history; a date-stamped "default since" note rots the moment the default changes again.

  **Cut outright:**
  - The dead `bands_for` lambda (`:2239-2244`) — "kept for reference" unused code with a 15-line obituary (`:2329-2341`); the measurement belongs in docs, the code should go.
  - The stale line-cross-reference "ms2_split is declared at :1324" (`:1947`) — it's at `:1886`; line-number comments are always wrong eventually, and this one already is.
  - "ponytail:" tags (`MzPeakStreamLoad.h:12`, `:107`, `:179`) — internal milestone names with no meaning to a reader.

  **Factually stale comments relative to the code:**
  - `toTrace` (`:244-248`) still frames the m/z estimator as "under test" — the test concluded, apex won, it's the default. Rewrite as the decision, not the experiment.
  - The apportion help "Try 1 or 2" vs C7 falsification (§2).
  - `flush_`'s comment (`:516-519`) records that parallel picking "differed in ~2% of intensities at the 1e-5..1e-4 relative level" vs serial — worth keeping, but it sits awkwardly next to README's "byte-identical at any thread count"; clarify that the claim is thread-count-invariance of the *current* parallel path, not serial-vs-parallel equivalence.
  - The `inferPrecursors_` header comment (`:1097-1098`) says it "scores each hypothesis by averagine-shape × co-elution, instead of counting partners" — but the *default* mode is partner counting. The comment describes the non-default branch as if it were the algorithm.

  ---

  ## 5. TEST COVERAGE

  What exists: `tests/test_calibration_cpp.cpp` (golden calibration cases), `tests/test_calibration.py`, `tests/test_entrapment.py`, CI for those three. What that covers: the calibration header and a Python estimator. **The 2,864-line tool itself has zero executable tests** — no test links `DIAPseudoSpectra.cpp`, exercises `inferPrecursors_`, or builds the binary in CI. The verification that does exist (whole-file cluster benchmarks + peptide-set gate) only exercises the *default* code path on *one* instrument's data, can't run in CI, and can't be run by an external contributor. The project's own defect ledger proves non-default paths ship broken: E5 (apportion/rp_max bypassed `corr_power` for months), the consolidate IM gate (dead from birth), `[auto-band-fix]` (advertised banding, ran serial). Every one of those is a unit-testable defect that whole-file benchmarking did not catch.

  The smallest set that catches the most likely defect classes:

  1. **`inferPrecursors_`, synthetic traces.** (a) A clean z=3 envelope (mono + M+1 + M+2 at 1.00335/3, ≥5-point co-eluting XICs, same IM): expect charge 3, mono correct, and both partners `used[]` — no ghost precursors at M+1/M+2. (b) Equal partner counts at z=2 and z=3: expect z=2 (documented low-z tie-break). (c) Gap at M+1 with M+2 present: count mode must stop (break-on-first-miss), envelope mode must span — this pins the algorithm difference the help text sells. (d) A bright singleton: charge 0, `guessed` set.
  2. **The `min_charge` predicate.** It takes 10 lines to factor `:2053-2054` into a function; test `{z=0,1,2,3}` at `zmin=2` → `{0,2,3}` survive. This is the newest adopted default and the easiest to regress.
  3. **`compactify`.** Input spectrum with NaN m/z, negative m/z, IM outside [0.4,1.8], and m/z 42950 (`mz*1e5 > 4.2e9`): all dropped *and counted*, none clamped. This guards the UB-on-unsigned-conversion class they already burned once.
  4. **`xicCorr`.** n<5 → 0; constant XIC → 0; identical XICs → 1.0. Three lines each; pins the two guards that everything downstream trusts.
  5. **`buildFragGrid` + `scoreCandidates_`.** One precursor, one co-eluting fragment: emitted. Same fragment with support < `min_corr_pts`: skipped. Constant fragment (`invnorm == 0`): skipped. Plus the `off` overflow check from §1.
  6. **`assembleFromList_` cap determinism.** `frags > max_frags` with engineered score ties: assert the documented m/z-then-index tie-break, twice, same result. This is the function that silently re-orders what the engine sees.
  7. **End-to-end determinism in CI.** Generate a tiny synthetic IM-aware mzML (a few dozen frames; OpenMS can write this), run at threads 1 and 8, assert `bench/semantic_digest.py` equality. The determinism claim is the project's most-retracted claim; it deserves a gate that runs without the cluster.
  8. **Wire the existing self-test into CI.** `diag:selftest_wavelet` (`:1545-1605`) already ships and exits non-zero on failure — it is simply never run automatically. One CI line.

  Verdict: current verification is **not sufficient for a public release**. It is a regression gate for the authors' private workflow, not a test suite: it cannot catch defects off the default path (demonstrated, three times), cannot run without private data, and gives an external contributor no way to validate a change. Items 1–6 above are a day or two of work against the existing anonymous-namespace functions (they're testable as-is by compiling the file with a test main, the same trick `test_calibration_cpp.cpp` uses against the header), and they target precisely the functions where this project's history says silent wrongness lives.

