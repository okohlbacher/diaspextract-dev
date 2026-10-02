You are an adversarial code reviewer. REVIEW ONLY -- do not modify, create or delete any file, do not build, do not run git commands that change state.

## Scope (frozen)

Repository: the current directory (a git worktree). HEAD is e7c2487f9602308c28d660f75856bc5d8360bdaf; the tree is clean.
The change under review is `git diff b2185db..e7c2487 -- src/diaspextract.cpp` (one file, +1098/-179). The same diff is also saved at /tmp/advrev-e7c2487.diff.
Line numbers below are at e7c2487 (src/diaspextract.cpp). Read the surrounding code in that file wherever you need it.

## What the code is

DIAspeXtract: a C++17 / OpenMP (GCC 13, libgomp, libstdc++ 13) tool that turns diaPASEF DIA data into pseudo-MS/MS spectra (mzML).
The window loop runs per 600-s RT tile. Before this change (b2185db) each tile was: read the tile (LOAD) -> every isolation window as an
OpenMP task (a master in `omp single` admits windows heaviest-first under a memory budget and a window cap) -> barrier -> canonical
sort / twin merge / post-fusion cap / mzML write (TileWriter) / malloc_trim -> next tile. Per window: slab/toTof, prep (count/distribute
seeds per band + sort), detect = taskloop over 12 flight-time bands, merge band arenas, valley split, content sort, then
carry_out = the window's boundary fragments that the SAME window needs in its NEXT tile, then score precursors (tasks) and emit.

The diff merges three branches:
- **pipe** (pipelined tiles): ONE parallel region over all tiles; thread 0 is a "driver" that reads tile k+1 (and admits its windows)
  while tile k's windows run; a WRITER task finishes tiles strictly in tile order; per-window `CarryGate` (line ~6242) is the only
  dependency between a window's consecutive tiles; carry is now published right after the content sort, BEFORE scoring (line ~6842);
  the reader's and writer's parallel loops run through `teamFor_` / `teamAssist_` / `PullJob_` (lines 155-212): a shared cursor
  pulled by the caller, by up to team-size helper tasks, and by window code at "break points" (`teamAssist_` calls inside the band
  taskloop and the score loop). `DIASPEXTRACT_PIPE_TILES` (default 2; 1 = old barrier path). Driver/writer code: lines ~6364-7110.
- **serial**: the heavy window's serial stages as bounded task counts (`parTasks_`, `forTasks_`, `parallelSort_` with merge-path
  co-ranks, `absorbAll_`, toTof frame compaction ~1406-1480, prepareTracing count/distribute ~1550, cost-balanced split cuts ~1812,
  FragRt::build ~4250, parallel trimToSpan and frag_im).
- **outer**: phases outside the loop in parallel: MS1 trace conversion with precomputed arena offsets (`toTraceAt`, ~1080 and
  ~3509), `parallelSortTotal_`, `sortExact_` (permutation sort + tie check, falls back to std::sort), `stdSortPar_` (a replay of
  libstdc++ 13's introsort with tasks, ~364-410), `mzOrder_`, parallel bucket-start index, PRECURSOR_INFER speculation batch
  8192 -> 2048 with a smaller dynamic chunk, MS1 per-spectrum sorts in parallel, an opt-in async MS1 pick worker thread.

## Invariants the change must keep (attack these)

1. OUTPUT IS DIGEST-IDENTICAL to b2185db for ANY thread count (1..192), any tile grouping (tile:cells_per_tile), pipe on or off.
   Every lever claims "output-identical by construction". A thread-count-dependent order anywhere that reaches the output is a defect.
2. Tiles are WRITTEN IN TILE ORDER, each tile's block canonical-sorted as before.
3. carry_out(w,k) must be complete before (w,k+1) assembles/scores; and it must be the SAME carry the old end-of-body code produced.
4. No data race on shared buffers (arena `wst.inten`, per-window maps such as `visited`, `slab_chain`, `carry`, TileWriter encoders
   `enc_`, ledger, per-slot scratch indexed by `omp_get_thread_num()`).
5. Bounded residency: memory in flight must stay bounded (slabs of at most pipe_depth tiles; finished-but-unwritten tiles?).
6. libgomp task-count cliff: once a team has more than 64 x nthreads tasks queued, libgomp runs every newly created task INLINE in the
   creating thread (a whole taskloop then serialises). Never use grainsize on data-dependent taskloops; bound task counts. Also:
   libgomp's team queue is FIFO, a thread waiting at a taskgroup end / taskwait may run ANY queued child of its current task.
7. Exceptions thrown inside OpenMP tasks/regions must be caught and propagated (an exception escaping a task aborts the process).
8. No deadlock / livelock: spin-waits (CarryGate::wait, writeTile's wait, teamFor_'s busy wait, admission loop) are NOT task
   scheduling points; a thread spinning there runs nothing but `teamAssist_` chunks.

## Questions -- numbered; I am least sure of 1, 2, 4, 5

1. Deadlock freedom of the pipelined loop. The comment at ~7048 argues FIFO dequeue makes (w,k) start before (w,k+1). Break it:
   (a) the task cliff making the DRIVER run a window or a writer inline at `#pragma omp task` (driver = thread 0, which must never run a
   window); (b) the driver reaching any task scheduling point (a taskloop / forTasks_ / taskwait / taskgroup on the loadTile or admission
   path), where libgomp would hand it its own children = window tasks, newest first; (c) a window key present in tile k-1's `wl` but
   absent from tile k's (or vice versa), so `CarrySlot::ready` never reaches k and the next tile spins forever; (d) admission budget /
   window cap with tile k+1 windows holding the slots while spinning in CarryGate; (e) a failure (`pipe_abort`) mid-admission.
2. `teamFor_` / `teamAssist_` / `PullJob_`: lifetime of the caller's lambda `f` (on the caller's stack) vs late helpers and assisting
   threads; the seq_cst `busy` argument; slot uniqueness of `omp_get_thread_num()` for per-slot scratch (PeakPickerIM copies,
   `enc_[slot]`, `part[slot]`); what happens if a teamFor_ caller is itself inside a NESTED team (the vendor reader's decode loop opens
   one): could a slot index exceed the vector, or two pullers share a slot?
3. Carry before scoring: does anything after `gate.publish()` (~6842) still modify `frag_traces` or the arena (`wst`) for ANY option
   combination (foreign envelopes, recap keys, fragment fusion, monocheck, adaptive gate, short traces...)? Early returns before/after
   take(); exceptions (the CarryGate destructor calls take()/wait during unwinding).
4. State shared between (w,k) and (w,k+1), which are now concurrent (tile k scoring while tile k+1 detects/assembles/scores), and
   between the writer of tile k and windows of tile k+1: `visited`, `slab_chain`, per-window or global counters, logs, `win_done`,
   `all_out`, precursor objects, ledger, phase timers (`phase_depth_` atomic, `phaseAdd_` locked). Any race that changes output?
5. Residency: the driver never waits for the writer before reading more tiles. Are finished-but-unwritten tiles (their `win_out` spectra
   and `tile_slabs`) bounded? Writer tasks spin-sleep on a thread while waiting for their predecessor. Is peak RSS bounded by pipe_depth?
6. Exactness of the sorts: `parallelSort_` (co-rank formula, odd last run copied, pieces per merge, ping-pong buffer, final copy-back),
   `parallelSortTotal_`, `sortExact_`, `stdSortPar_` (is it really libstdc++ 13's `std::__sort`?). The window content sort (~6797) uses
   parallelSort_ with a comparator that is NOT total (exact duplicates compare equal) and a task count that depends on the thread count:
   can duplicates that differ in an uncompared field (e.g. `off`, or any Trace field not in the comparator) reach the output?
7. Exactness of the "serial" stage rewrites: toTof frame compaction + close-up copy (~1406-1485), prepareTracing count/distribute
   (frame chunks, `frame_live`, band cursors ~1590), cost-balanced split cuts (~1812), `absorbAll_` vs `TraceStore::absorb` (bins
   zero-fill, sizes, exceptions), FragRt::build lo/hi fold (NaN, -0.0), MS1 `toTraceAt` vs `toTrace`+`makeSpan` (same Trace, same arena
   bytes? does setRtFrame or makeSpan touch the store anywhere else?), the parallel `bstart` construction (~3655), parallel `trimToSpan`
   on a shared arena (~5776, ~6720).
8. Nested parallelism: the pipe driver calls `omp_set_max_active_levels(max(2, ...))` (global, persists). Is any unguarded
   `#pragma omp parallel` (in this file, or OpenMS library code it calls) reachable from inside a window task or the writer task that
   would now open a real nested team -- oversubscription, or a completion-order append that changes output? (Note line 6065 already
   sets 2 when n_bands > 1 in the old code too -- say whether the new code changes anything for n_bands <= 1.)
9. Exceptions: every new task/parallel body (teamFor_ helpers, writer task, introsortLoopPar_ tasks, parallelSortTotal_ /
   sortExact_ / mzOrder_ `parallel for` bodies, forTasks_, MS1 async worker thread) -- can anything escape?
10. PRECURSOR_INFER speculation (~3932): batch 2048, chunk `spec_chunk`: still exact (speculate, commit in seed order, re-evaluate on
   stale deps)?

## Output format

For EACH finding: severity (critical / high / medium / low), `file:line` at e7c2487, the defect in one sentence, a CONCRETE failing input
or interleaving (thread counts, option values, data shape), and "bites on real data" vs "theoretical". Rank most severe first.
Say explicitly which invariant (1-8) it breaks. If you checked a question and it is fine, say so in one line rather than padding --
those negative results are useful. Do not report style or naming issues.
