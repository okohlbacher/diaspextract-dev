• The full source is read. Now the mandated docs.

• The docs are read. Now let me verify the actual commits behind the biggest claims — especially whether the "integer default" commit actually changed the registered default, and what the span-gate commit changed.

• Confirmed a major finding. Now the subagent's summary of the review docs:

• One more verification pass on tests and a couple of ledger details:

• The review files were still being written when the subagent read them — codex.md and vibe.md now have content. Reading them:

• One last check on the CHANGELOG contradiction codex flagged:

• Review complete. I read the full 3,880-line source, today's commits, the design/plan docs, and the (still-being-written) day-assessment reviews. Where another reviewer found something first I say so; where they're wrong I say that too.

  ---

  ## 1. Is making the integer detector the default defensible?

  **No — and the day's central fact is worse than a bent rule: the default was never actually changed.**

  Commit `e3c6eb4` ("Make trace:detector=integer the default") touches exactly three things in the source: `const bool` → `bool` at `src/DIAPseudoSpectra.cpp:3115`, the fallback at `:3130-3142`, and the `spx:detector` meta value at `:3862`. It does **not** touch `registerStringOption_("trace:detector", "<mode>", "openms", ...)` at `:1485`. I verified this with `git show e3c6eb4` and by grepping HEAD. So `integer_detector` is true only when a user explicitly passes `-trace:detector integer`; the "NEW DEFAULT" arm in the table was necessarily run with an explicit flag; the fallback path the commit adds is dead code under real defaults; and the CHANGELOG both claims "now defaults to integer" (`CHANGELOG.md:27`) and still says "EXPERIMENTAL, default `openms`" (`CHANGELOG.md:61`). README makes the same false claim. The codex reviewer found this independently; I confirmed it from the diff, not from his say-so.

  **The rule, on the merits.** The adoption criterion written into `docs/dataset D-BASELINE.md` the previous evening is explicit: *"peptides within the replicate spread on BOTH engines, entrapment inside the charge-gate arm's interval, and dataset A replication of the runtime."* Against the current binary:

  - Sage: 12,475 vs 12,642 = **−1.3%**. After the determinism fix the tool is reproducible, so this is a real deficit, not replicate noise — and −1.4% was the stated reason for *holding* the detector on 2026-09-03. **Fail.**
  - MSFragger: +2.1%. Pass. Entrapment 1.27% [1.03–1.52] inside [1.15–1.64]. Pass.
  - Second file: dataset A's +0.3% comes from `4a22ad7`, which predates the span representation (`3a1d91e`) **and** the split-child-bin fix (`6ea4e3f`, which moved peptides by 3.3%). It describes a detector that no longer exists. **Absent.**

  Two of four legs fail or are missing. The rule was bent, not met. Worse, the project already adjudicated this exact evidence pattern **the day before**: backfill q=0.5 was Sage-negative / MSFragger-positive / entrapment-flat, and the verdict was *"the two engines genuinely want different spectra — but that makes it a per-engine option at best, not a default"* (dataset D-BASELINE.md, backfill confirmation arm). The integer detector has the identical signature and was declared default ~15 hours later.

  **The "about 1%" language is wrong by ~8x.** only-openms is 1,148/12,642 = 9.1%; only-integer is 981/12,475 = 7.9%; the symmetric difference is 2,129/13,623 = **15.6% of the union** (codex's arithmetic; it checks out against the numbers in the prompt). The *net* differs by 1.3%; the *membership* differs by ~8%. This claim is repeated in the commit message, CHANGELOG, README, and the fallback warning at `:3137-3140` — every one of them misstates the evidence. Also: entrapment "lower" is not demonstrated; 1.27 vs 1.38 with those CIs is "no evidence of worsening," full stop.

  **The fallback is not enough, for two reasons.** (a) A log warning plus `spx:detector` metadata means a `.d` user and an mzML user running the same nominal command get algorithms that differ on 8% of peptide membership — at minimum the mode should be named `auto`, and the warning should state the real churn. (b) Fail-open by a second door, found by codex and verified by me: `frameIdOf` returns 0 for unparseable native IDs (`:641-655`), the comment says "the caller must treat 0 as unknown," and **no caller does** — `toSlab` calls `ax.factor(0)` (`:783`), which returns the reference-temperature factor (`:542-543`, with `b_by_frame[0]` backfilled at `:594-595`). So an mzML plus a sidecar tdf loads the axis fine, skips the fallback warning entirely, and calibrates every frame at reference temperature — precisely the invented-calibration outcome the commit message says must fail closed.

  **Honest statement of the evidence:** on dataset D the integer detector is 8% faster (6:21 vs 6:54), 43% lighter (86 vs 150 GB, span arms), −1.3% Sage / +2.1% MSFragger / entrapment-not-worse, with 15.6% union churn; on dataset A an earlier, differently-broken version was +0.3% Sage at 140 vs 230 GB. Generalisation across engines and files is unverified.

  ## 2. What is unverified or overstated

  **Verified by a run:**
  - The span gate (`bbb2121`, recorded `docs/TRACE-STRUCT-REDESIGN.md:230-235`): pre-span vs post-span spectrum-list digest identical on both detectors, one dataset D run each. This is the day's strongest evidence — but note three caveats: it passed only on the **second** attempt, after `6ea4e3f` repaired a refactor-introduced bug that cost 3.3% of peptides (the commit message omits the first failure); the R7 staged falsifiers (pre-EPD frame/intensity tuples, child boundaries, G/mean/invnorm) are not recorded as having been run — only the final digest; and "identical" is within-detector, not cross-detector (656,254 vs 656,256 spectra — the two detectors do not agree with each other).
  - The scoring-gate change (12:53 → 7:17): the record says "set identical, replicated three times" — that is **peptide-set** identity. Calling it "digest-identical" overstates the record; no spectrum digest for it is documented anywhere.

  **Asserted "by construction," never run:**
  - `7d6e56f` (prep compaction) says "Output-neutral by construction; digest-gated" — **the digest gate has never been executed**. HEAD of the branch is unrun code. The plan required E3/E4 as *isolated* runs with digest falsifiers; both were bundled into one commit and zero runs. Its partial defence: I checked the substitutions myself — `frameOfPeak` is `upper_bound(...)−1` (`:893-895`, the plan's explicit requirement), the seed fill keeps both conjuncts (`:869-870`), the count-then-reserve logic is consistent for snr<1. "By construction" looks right here, but the plan's own rule is that this class of claim is one cheap dataset A run away from proven, and that run hasn't happened.
  - The "ledger after" numbers in the table (prep 14.3/14.3, compaction to ~4.5 GB) predate `7d6e56f`; the 4.5 GB is projection, not measurement.

  **The ledger is still not the corrected instrument the plan made a prerequisite.** I checked every `MemGuard` use:
  - `g_tr` is created only **after** detection and splitting (`:3339`), so the "traces 6.9 GB peak" is a post-split resident measurement — it never saw the band-private stores, parent spans, or `bins`. The redesign's own falsifier ("traces must fall 35.6 → <12 GB") compares a cumulative-wrong "before" against a post-split "after".
  - The EPD guards are installed after the structures they measure exist: `g_in` at `:1095` after `mts` is fully built, `g_out` at `:1099` after `splitValleys` returns; and both book `np × sizeof(Peak2D)` while each `MassTrace` also carries `smoothed_intensities_` (8 B/pt, written by EPD `smoothData`) — the plan itself (§3c) prices the payload at 32 B/pt, so the 7.6+1.0 GB lines understate by ~25%+.
  - `g_wmap` (`:3211`) is never released even though `detectTraces_` clears the map at `:1700`/`:1725` — the OpenMS arm is overcharged in the one category it has.
  - `MEM_SPECTRA` is still added only in the share-all branch (`:3474-3476`); apportion (`:3383-3428`) and rp_max (`:3480-3541`) are unaccounted — the E1 item "hoist the add" was not done.
  - `memTotalPeak` sums independently-mutating atomics without a coherent snapshot (`:735-737`).
  - The MS1 compaction subtracts `vbytes(old) − keep.size()*4` (`:3009`) but `keep`'s capacity can exceed its size (reserved at half, `:3000`) — under-books retained capacity.
  - The label at `:718` still says "FragGrid," a structure that no longer exists.

  So: the 68.6 GB "before" mixes real bytes with known accounting artifacts (the plan calls its own prep line "impossible… must not be used as a basis"), and the 27.9 GB "after" is a lower bound assembled from non-coherent, post-hoc, partially-missing guards. **The defensible memory claim of the day is process RSS: 105 → 86/88 GB.** Everything below that line is attribution, and the attribution is not trustworthy yet.

  ## 3. Correctness of the span representation as implemented

  I walked the specific hazards the prompt names. **The core lifetime design is sound as written** — and I checked rather than trusting the gate:

  - *Dangling `st`*: stores are never moved after `st` is set — `ms1_store` is a stack local (`:2704`), `wst` is task-local (`:3264`), `bst`/`stores` are pre-sized vectors; offsets are indices, so arena reallocation is harmless, and `st` is re-set after each absorb/split (`:3311`, `:3326`, `:3335`, `:2712`). `xv()`/`gframe()` read `st->inten` fresh. Safe today; but the invariant is carried by four manual assignments and nothing else — one future `Trace` copy out of a chunk store without the re-set dangles.
  - *Rebase*: band absorb (`:3303-3310`) and chunk absorb (`:1127-1132`) rebase after the implicit taskgroup joins; `splitIntegerTraces` reads `wst.bins[t.off+k]` only inside the taskloop, before the arena swap at `:1123-1124`. Sequencing is correct. The `absorb` bins invariant (a non-empty `inten` implies non-empty `bins` on the detection path, empty on the EPD path) holds today and is undocumented at `:297-306`.
  - *OpenMS path with empty `store.b`*: `toTrace` leaves `tof=0, b=0`, `exportMz_` falls back to cached m/z (`:2378-2383`); the OpenMS arm being digest-identical through the gate exercises every shared consumer of this case. Handled correctly.

  **Real defects, in decreasing severity:**

  1. **Fail-open calibration on unknown frame IDs** (`:641-655`, `:783`, `:594-595`) — detailed in §1. This is a correctness bug in the intended-default path, independent of the span work.
  2. **`fwhm_of` in the diag dump contradicts its contract.** The comment (`:2924-2928`) promises "−1 when the trace never falls to half max on both sides (truncated peak)… must be reported rather than silently imputed." The code initializes `lo = prt[0]`, `hi = prt[pv.size()-1]` and unconditionally `return hi - lo` (`:2935-2953`): a truncated peak is silently imputed as **full span**. The main median-FWHM routine (`:2740-2752`) does exclude truncated peaks correctly, so this corrupts exactly the diagnostic column you'd use to audit the other one. Pre-existing, but it sits in the code today's review was supposed to cover. (Codex found the same; I verified both routines line by line.)
  3. **Unchecked `uint32` offset casts.** The design's R4.8 required `assert(arena.size() < 2^32)` before any `off` is written. `makeSpan` casts `store.inten.size()` to `uint32_t` at `:330` with no check (the `absorb` check at `:300` cannot repair a band-local offset that already wrapped), and the MS1 compaction repeats the unchecked cast at `:3005`. Implausible on dataset D, unguarded by design.
  4. **Zero-sentinel invariant remains unasserted.** `makeSpan` accepts anything; `real(k)` is `xv(k) > 0.0f`. It is valid today only because both detectors feed it intensities > noise — but `setMinFloat_` allows noise = 0 (`:1585-1586`), and a genuine 0.0-intensity peak would silently become "missing." One `q.second > 0` assert in `makeSpan` closes it; the reviewers asked for exactly this and it wasn't done. (vibe.md's related complaint that `== 0.0f` at `:336` is "dangerous floating-point equality" is itself wrong — that's a test against freshly zero-initialised memory, which is exact.)
  5. **Unsplit-path semantic divergence.** With `trace:ms2_split_valleys=0`, `splitIntegerTraces` returns parents untouched, whose scalars are `mz = cmz` (weighted centroid, `:1020`) and `rt` = **apex-frame** RT (`:1021`) — while the OpenMS path under the default `apex` estimator reports apex m/z and centroid RT. After splitting, children pass through `toTrace` and the semantics re-converge — so the two detectors agree *only because the default splits*. Non-default but reachable, and undocumented in `trace:detector`'s help text.
  6. **Apex-tie inconsistency.** `detectTracesInteger_` picks `kap/fap` by strict `>` over `got` in extension order (`:1013-1015`); `makeSpan` picks `apex` by strict `>` over `pts` in frame order (`:338`). On exact intensity ties the stored `apex` (used for `c.b` at `:1116`) can name a different frame than `fap` (used for `t.rt`/`t.tof` at `:1019-1021`) — wrong frame's calibration factor on a tie. Rare, real, one line to align.
  7. **The per-band `visited` double-claim defect ships in the intended default.** `docs/INTEGER-MEMORY-ANALYSIS.md` §4 called per-band visited "not merely wasteful, it is wrong"; the bitset (`:898`) kept per-band scope, so two bands can still claim the same out-of-core peak (measured 0.1% of peptides). The shared-bitset fix was rejected for changing output — fine, but then this is a known deterministic error being carried into a default, and it belongs in the warning text.
  8. **The `[det]` compact-store digest is dead on the integer path.** At `:3227-3234` it digests `wmap`, which is empty on the integer path — it logs "n=0" and a constant. The frag-trace digest at `:3340-3344` works, so `7d6e56f`'s promised digest gate is executable, but half the instrument is silently inert on the path that is supposed to become the default.
  9. Test coverage: `test/test_spextractor.py:19` states the suite exercises the OpenMS detector only. The dataset D digest is the *only* coverage of the integer span/split path.

  For the record, vibe.md's claim that `npts` can overflow because "a trace could have 70,000 spanned frames" is wrong — `makeSpan` throws at `L ≥ 65536` (`:329`), so `npts ≤ len` and `apex < len` are safe; the missing guard is the 32-bit offset (item 3), as codex says.

  ## 4. The occupancy question

  **Consistent. No large scheduling defect.** The arithmetic (whole-run wall decomposed against loop occupancy):

  - Work ratio: 14,249 / 19,440 = **0.733**. Occupancy ratio: 68.5 / 81.0 = **0.846**. For like scopes, occupancy ratio = work ratio ÷ loop-wall ratio, so the implied integer loop wall is 0.733/0.846 = **0.867** of OpenMS's.
  - Decompose total wall: 414 = T + W and 381 = T + 0.867W → W ≈ **248 s**, T ≈ **166 s**, integer loop ≈ **215 s**.
  - Back-check: 81.0 × 248 = 20,088 predicted OpenMS loop CPU vs 19,440 total (−648 ≈ CPU outside the loop); 68.5 × 215 = 14,728 vs 14,249 (−479). Both close within ~3%, in the same direction, consistent with ~500–650 CPU-s of load/MS1 outside the loop.

  So the 16-point occupancy gap is almost entirely the arithmetic consequence of doing 27% less work in a loop that is 13% shorter — codex's section 4 reaches the same result and it is correct; vibe.md's section 4 (which multiplies occupancy by *whole-run* wall, uses 373 s for 6:21, and declares a "77% discrepancy… 25% unexplained") is a scope error and should be disregarded.

  The honest residual: if the integer loop ran at the OpenMS arm's 81x it would take ~(14,249−479)/81 ≈ **170 s instead of ~215 s** — so the upper bound on any real scheduling loss is ~45 s, ≈12% of wall, not the ~600 s a naive reading of the occupancy gap implies. Direction also argues against bandwidth explanations: a cache-stalled thread is still on-CPU and inflates CPU-s; the integer path has *fewer*.

  Still worth measuring, all cheap: the plan's free 1 Hz thread-state sampler (R/S/D per thread) attached to the dataset A re-runs that are needed anyway; a split-stage timer (the EPD stage is currently pooled into `t_trace` between `_t2` `:3242` and `_t3` `:3369`, which is also the prerequisite for judging the SG-coefficient-cache item); and time spent in the admission wait at `:3189-3203`. Do not spend a dedicated run, and do not redesign the scheduler on the raw 68.5 vs 81.0 comparison.

  ## 5. What next, and what to STOP

  **Do, ranked:**

  1. **Resolve the default honestly — today.** Either flip `:1485` to `"integer"` and take the rule violation head-on with the evidence stated correctly (15.6% union churn, Sage −1.3% / MSFragger +2.1%, dataset A pending), or revert CHANGELOG/README and keep `openms`. Rename the calibration-dependent behaviour to `auto`, make unknown frame IDs fail closed (`frameIdOf` 0 → refuse or warn loudly), and fix the "about 1%" language everywhere including the fallback warning at `:3137`.
  2. **Re-run dataset A with the current binary** — both engines plus entrapment. This single run covers the missing second-file leg for the default decision *and* the never-executed digest gate for `7d6e56f` *and* gives the occupancy sampler a ride. It is the cheapest highest-value run available.
  3. **Fix the ledger before quoting another component-level number**: move `g_tr` above detection, guard the EPD structures at allocation time with the 32 B/pt payload, release `g_wmap` at map clear, hoist the `MEM_SPECTRA` add out of the share-all branch, capacity-consistent subtraction at `:3009`, rename the stale label. Until then, quote RSS (86 GB), not 27.9 GB.
  4. **The v0.3.0 blockers, before any further optimisation.** Public-dataset replication, dependency SHAs/compiler identity, a worked example with expected output, and resource requirements (a tool that needs 86–164 GB and says so nowhere). Every one of today's gains is a number no external party can reproduce; that is the project's largest credibility gap and it predates this week.
  5. **Small correctness fixes** (each a few lines): `fwhm_of` return −1 on no crossing; `off`/arena asserts per R4.8; `q.second > 0` assert in `makeSpan`; align the apex-tie rule; document the unsplit-path scalar divergence.
  6. **Integer-path tests**: a tiny injectable calibration fixture exercising span holes, split-child apex bins, unknown frame IDs, and detector selection — right now the only coverage of the intended default is one dataset D digest.

  **Stop:**

  - **Slab compaction / "slab lifetime" as open items.** The lifetime fix already shipped (`:3313-3321`). The remaining slab-compaction item (E5) is gated on seed fraction m < 0.8, and the seed counter measured **m = 1.0** (`docs/TRACE-STRUCT-REDESIGN.md:250-252`: 100% of above-noise peaks are seeds at shipped snr). Its own precondition failed; close it.
  - **Trace scalar removal** (1.6–3.2 GB): rests on a trace population the plan itself flags as unmeasured, touches ~8 read sites of the hottest loop, worth <2% of process RSS. Not now.
  - **Allocator experiments**: falsified for speed already, and confounded for RSS because `availableBytes_()` adds our own RSS back (plan §8). The glibc↔tcmalloc A/B is on record (101.8 → 94.3 GB).
  - **Per-trace valley splitting (8–11 GB) as currently justified**: its size estimate derives from the ledger this review just showed is untrustworthy, and its motivation is memory on a node that tolerated 164 GB. If anything in EPD is worth doing it is the SG coefficient cache (measured 87–95% of per-trace `detectPeaks` cost — a *wall-time* item), gated on the split-stage timer. Don't do the memory surgery first.
  - **Declaring defaults ahead of the evidence**: two consecutive days produced a held-then-adopted flip on the same −1.3% number. The project's own both-engines-plus-second-file rule exists precisely for this; either follow it or rewrite it deliberately, not accidentally.

  One meta-observation: the day's adversarial-review round is itself incomplete — `docs/reviews/day-assessment-2026-09-04/kimi.md` contains only stray status lines (no review), vibe.md's occupancy and uint16 sections are wrong as noted, and codex.md (the one solid review) landed after the commits it reviews. The two findings that matter most — the default that was never flipped and the fail-open frame-ID path — were catchable by reading the diff of `e3c6eb4` alone, which is four hunks long.

