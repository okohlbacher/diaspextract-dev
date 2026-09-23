• I'll verify each of the five areas. Starting with the patch mechanics and surrounding code.

• The TOPPBase.h context at bd4b895 matches the patch exactly, and TOPPBase already has virtual functions. Now checking the override's access context and the OpenMP task regions in diaspextract.cpp.

• Now reading the six taskloop sites and their enclosing handlers.

• The containment picture is complete. Now checking how real cells invoke `run_capped` (whether the leader really is GNU time) and the selftest context.

• One more critical path to verify: whether `active`/`inflight` are decremented on the exception path of the window body — otherwise a caught exception turns the old crash into an admission deadlock.

• One last check — thread-safe static init assumption for `taskFault_`:

• Review complete. I verified the patch context against the actual OpenMS bd4b895 sources, traced every OpenMP region boundary in `src/diaspextract.cpp`, and walked the `kill_session` process accounting chain in `harness/corpus.py`. No blocking findings; the commit is sound. Details per area:

  ## 1. patches/openms-topp-docurl.patch — correct

  - **Override**: `src/diaspextract.cpp:2218` sits in the `public:` section of `TOPPDIAspeXtract` (class at 2203, `public:` at 2205), base member is public, and the signature matches exactly (`String getDocumentationURL() const override` vs `virtual String getDocumentationURL() const`). The definition in TOPPBase.cpp correctly needs no change. Both call sites — `printUsage_` (TOPPBase.cpp:572) and the CTD writer (:2421) — dispatch virtually to the override.
  - **Applies at bd4b895 with -p1**: I fetched `src/openms/include/OpenMS/APPLICATIONS/TOPPBase.h` at bd4b895 and the context (`getToolPrefix()`, the doxygen doc comment, `cite_openms`) matches verbatim and uniquely; hunk counts (-191,7 / +191,9) are consistent. The headerless `---/+++` format is accepted by both `patch` (used in apply_openms_patches.sh:31) and `git apply --reverse --check` (used in build.yml:166). Both scripts glob `patches/*.patch`, so the fifth patch is applied and CI-asserted with no list to update.
  - **ABI**: TOPPBase was already polymorphic, so no vptr is added. However, the new virtual is declared at header line 191, *before* `getSubsectionDefaults_`/`registerOptionsAndFlags_`/`main_`, so under the Itanium ABI it is inserted mid-vtable and shifts those slots. Within the pinned source build this is harmless — libOpenMS, all TOPP tools and diaspextract compile from the same patched tree. It would only break a binary compiled against *unpatched* headers and run against the patched libOpenMS (virtual dispatch into the wrong slot), e.g. a system FileConverter under `LD_LIBRARY_PATH=<patched>/lib`. The other four patches already make that mix unsupported, and README/build.yml already forbid released packages. **Informational; does not bite in the shipped configuration.**

  ## 2. PerfLoad guard — consistent, correct test

  Hunk `@@ -17,6 +17,15 @@` (patches/openms-brukertims-mz-calibration.patch:67): 6 context lines + 9 added lines = 15 on the + side, 6 on the − side. Consistent.

  "All five counters zero" is the right nothing-loaded test: any completed load has `batches >= 1` and `decode`/`handoff` are chrono-measured wall times, strictly > 0 for any real decode; a load that fails before the first batch (missing file, instant SDK error) leaves everything zero and stays silent, which is the desired behavior since the tool reports its own error. Minor observation: a load that throws *after* the first batch still prints a partial `[perf-load]` line at exit — but that is a failing run and the line is a diagnostic. Cosmetic at worst. (Counter increments from parallel decode threads are a pre-existing benign race feeding only this diagnostic; unchanged by this commit.)

  ## 3. Exception containment — all six loops verified

  - Sites: 1237 (integer splitter), 2469 (distribute), 2544 (ms1 band), 2589 (valley split), 4662 (window band), 4845 (assembly). Each `try` covers the whole task body. The only top-level `continue`s — 2553 (`sub[b].size() < 3`) and 2593 (`lo >= hi`) — are inside the `try`; a `continue` exits a try block normally, so behavior is unchanged, and the ledger decrement at 2553 happens *before* the continue. The `break`/`continue` in 4845 belong to the inner `for(;;)`.
  - Every `std::rethrow_exception` is immediately after its taskloop construct; taskloop carries an implicit taskgroup, so all tasks (including nested ones created inside detectTraces_ when called from the window task at 4733) have joined.
  - **Landing**: MS1 path — the rethrows inside detectTraces_ reach the `try` at 3912; the catch at 3918 stores `ms1_err`. Crucially, `#pragma omp parallel`/`single` at 3910-3911 have the try-catch as their entire structured block, so the rethrow at 3919 runs serially, after the join — it cannot escape an OpenMP region. Window path — rethrows at 4668/4865 (and 1284 via the call at 4718) are inside the window body's `try` (4516), caught at 4900 into `worker_err`; the parallel/single regions end at 4907 (their block is the task-spawning `for`), and the end-of-parallel implicit barrier joins all window tasks before the serial rethrow at 4908. Both then propagate into `main_`, where TOPPBase::main catches, prints, and returns a non-zero ExitCode — matching 12e's expectations.
  - **No introduced deadlock**: the RAII `Release` at 4522 decrements `inflight`/`active` on every exit path, so a caught exception cannot stall the admission loop at 4505 (this is the one place where turning a terminate into a catch could have created a hang).
  - The three unwrapped taskloops (966, 1034, 1940) contain only writes into preallocated arrays, an in-place `std::sort` with a pure comparator, and arithmetic — no allocation, no throwing call. Leaving them bare is sound.
  - `taskFault_`: function-local static init is thread-safe (C++20 build, no `-fno-threadsafe-statics` anywhere); unset → `want == nullptr` → one comparison, zero effect. Safe to ship.
  - Two notes, both informational: (a) `DIASPEXTRACT_TASK_THROW` exists for only 2 of the 6 sites, so four wrappings are e2e-blind — the pattern is mechanically identical in all six, so risk is low; (b) once `worker_err` is set, the admission loop keeps spawning the remaining windows (each fails at the same site) rather than aborting early — pre-existing behavior of the worker_err design, an efficiency footnote for genuine persistent errors, not a regression.

  ## 4. harness/corpus.py kill_session — correct, races benign

  - **Parsing**: after `rindex(")") + 2`, `split()[3]` is field 6 = session id — matches proc_snapshot's own parsing (corpus.py:747). Leader excluded from the first wave; `/proc` unreadable → `kids` empty → straight to killpg (old behavior, the macOS path). Session already gone → leader read fails → break → `ProcessLookupError` caught.
  - **Leader is not reaped here — confirmed.** No `waitpid` anywhere in the function; the reap happens via `p.wait()` in run_capped (corpus.py:1182/1184), same thread, after kill_session returns, so there is no concurrent reaper and the CPython ECHILD→returncode-0 trap cannot spring. A killed cell keeps its non-zero status.
  - **The leader really is GNU time** for real cells: `cmd_dwv`/`cmd_reencode` (947-952) prepend `[TIME, "-v", "-o", ...]`, so the tool is time's direct child; `FAKE_TIME` (3412) also waits on its child, so the selftest fixture exercises the same shape. The accounting chain closes: tool CPU → time's cutime on reap → runner's cutime via `p.wait()`, and proc_snapshot sums utime+stime+cutime+cstime over the live tree (749) — "ours" no longer drops when the tool dies, which removes the 12-16k-foreign-cores artifact at the mechanism, not just in the sample.
  - Races, one by one:
   - *Member forking during the kill*: missed by `kids`, orphaned, but still in the process group → killpg gets it; only its last-instant CPU is misbooked. These tools don't fork; theoretical.
   - *Leader not being time / no wrapper*: `kids` is then the tool's own children (none) → no wait → killpg → `p.wait()` reaps the tool directly and its CPU lands in the runner's cutime — still correctly accounted.
   - *Leader that never exits after its children die*: full 30 s block, then killpg; correct but slow, and only for a misconfigured wrapper.
   - *Leader PID reuse*: impossible — the runner is the leader's parent and does not reap it until after kill_session returns, so the pid stays pinned (alive or zombie) for the whole function.
   - *Member PID reuse between scan and kill*: microsecond window in a 4M pid space; theoretical.
   - *Member in uninterruptible (D) sleep*: SIGKILL pends past the 30 s wait, killpg kills the leader, the member dies later and is reaped by init — its CPU leaves the tree (the old bug, partially). Rare; the realistic failure mode is gone.
  - **Selftest** (4249-4256): deterministic. MON_S is 0.02 in the selftest fixture, cap 4.0 s, single-threaded burn ⇒ ~4 s CPU against a ≥1.0 s threshold (4x margin; a node would have to starve the process of >75 % of a core for 4 s to flake). With the old one-signal killpg, time and the burn die together, init reaps the burn, and own-tree CPU grows only by time's own ~0.0-0.1 s < 1.0 — so the case really does fail on the old code; it is a genuine falsifier. Two nits, both practically unreachable: `proc_snapshot()` can return `None` and `proc_snapshot()["ours"]` would then raise `TypeError` instead of a check failure (corpus.py:4252/4254), and the case hardcodes `/usr/bin/time` rather than the `TIME` global — deliberate (TIME is a stand-in in the selftest) and guarded by `os.path.exists`.

  ## 5. e2e 12d/12e and wording

  - **12d**: TOPPBase.cpp:572-579 emits `bright("Full documentation: ") << underline(docurl)` to stderr; after the test's ANSI strip the regex `Full documentation:\s*<url>` matches. The CTD writer takes `docurl` from `getDocumentationURL()` (:2421), so `docurl="<repo>"` and the absence of `openms.de/doxygen` are both pinned. The unchecked `-write_ctd` return code is backstopped by `assert ctds`.
  - **12e**: `run(..., expect_fail=True)` (test_diaspextract.py:235) asserts non-zero; the additional `r.returncode > 0` correctly discriminates a signal death (negative returncode) from a clean error exit, and the injected `InvalidValue`'s message contains `injected failure in task <site>`, which TOPPBase::main prints for caught exceptions. `threads=4` makes the taskloops genuinely parallel. Sound.
  - **Wording**: README's "build stops without the first, third and fifth" is accurate — without patch 5 the `override` at diaspextract.cpp:2218 fails to compile, without 1 the calibration symbols are missing, 3 carries the `static_assert`, and 2/4 are perf-only. build.yml's marker step (163) and the apply script both glob `patches/*.patch`, so "five" is enforced structurally, not just in prose. openms.lock comment updated consistently.

  **Bottom line**: the commit does what it says; no finding that bites in practice. The only things I'd write down for the record are the mid-vtable insertion caveat (matters only if someone mixes prebuilt binaries with the patched libOpenMS, which the project already forbids) and the D-state edge case in kill_session (the one path where a sliver of the old misaccounting can still occur).

