Static review only; no files changed or builds run. I found three new issues and one inherited hang that the new fallback does not fix. I did **not** establish a new deadlock in the normal multi-threaded pipeline.

1. **High — [src/diaspextract.cpp:7090](/private/tmp/advrev-base-e7c2487/src/diaspextract.cpp:7090) — Completed output residency is not bounded by `pipe_depth`.**  
   **Breaks invariant 5’s intended depth bound.** The driver advances after window completion, while only `writeTile()` releases the completed tile.

   **Concrete interleaving:** Four threads, depth 2, six tiles, one window per tile, and `perf:max_concurrent_windows=1`. Writer 0 stalls on output I/O. Two other workers eventually occupy writers 1 and 2, spinning at line 7063. Before that happens, windows through tile 3 finish. Writer 3 remains queued; the driver admits tile 4 and loads tile 5 before blocking. There are now **four completed output blocks plus two further tiles**, despite depth 2.

   **Bites on real data:** slow storage and substantial spectrum output. The heavy slabs remain depth-bounded; completed spectra do not. Ordinary FIFO scheduling eventually supplies backpressure proportional to **thread count plus depth**, so this is not unlimited accumulation.

2. **High — [src/diaspextract.cpp:7083](/private/tmp/advrev-base-e7c2487/src/diaspextract.cpp:7083) — The one-thread fallback can deadlock inside admission before reaching its `taskwait`.**  
   **Breaks invariant 8. Inherited limitation, not a demonstrated regression.**

   **Concrete input:** Requested threads 4, `OMP_THREAD_LIMIT=1`, depth 2, at least two tiles and two windows, `perf:max_concurrent_windows=1`. The actual team has one thread. Its first window task remains deferred; admission of the second spins at line 6485 because `active==n_conc`. The only thread cannot reach line 7095 to execute the deferred task. GCC installs a real team even for one thread, and its task-dispatch condition does not automatically make such tasks inline. [GCC team initialization](https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-13/libgomp/team.c), [GCC 13 task dispatch](https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-13.3.0/libgomp/task.c).

   **Bites on real data:** constrained OpenMP configurations. The baseline’s admission loop appears to have the same hang because libgomp’s `taskyield` supplies no progress; the newly added fallback does not resolve it.

3. **Medium — [src/diaspextract.cpp:1097](/private/tmp/advrev-base-e7c2487/src/diaspextract.cpp:1097) — Parallel MS1 conversion narrows unchecked arena offsets, allowing different tasks to overwrite the same span.**  
   **Breaks invariant 4; can also break invariant 1.**

   **Concrete input:** Two threads, parallel MS1 conversion enabled, `trace:ms1_split_valleys=0`, and 131,073 traces each spanning 32,768 frames. The prefix sum allocates 4,295,000,064 floats. Trace #131072 receives offset `2^32`, which narrows to zero. Its task can read/write the same cells as trace #0 at lines 1102–1103, making intensities and `npts` scheduling-dependent.

   **Theoretical:** requires an intensity arena exceeding 16 GiB. The baseline already mishandles this oversized arena through the same narrowing; **the new defect is concurrent aliasing**, rather than the original overflow.

4. **Low — [src/diaspextract.cpp:373](/private/tmp/advrev-base-e7c2487/src/diaspextract.cpp:373) — The introsort partition threshold bounds task size, not queued task count.**  
   **Breaks invariant 6.**

   **Concrete input/interleaving:** Two threads and `2^23` equal-m/z indices entering `stdSortPar_`. Deschedule the creator after its initial left descent; the other worker expands queued partitions FIFO. Equal keys produce midpoint partitions. The unthrottled expansion demands up to 148 queued tasks, crossing libgomp’s 128-task threshold and forcing subsequent recursive subtrees inline.

   **Theoretical/pathological input; performance only.** This does not establish an output mismatch or whole-sort serialization.

The remaining checks:

- **Q1(a,b):** The “driver never runs a window” premise is false: the admission task can execute inline at the task cliff, and diagnostic `toTof()` at line 6433 reaches `forTasks_`. Neither establishes a deadlock by itself; I found no concrete cycle through those paths.
- **Q1(c):** Checked: every frozen key gets a tile slab, including empty slices. `finish()` initializes tables even with no delivered spectra, so missing-window carry generations do not occur on successful loads.
- **Q1(d,e):** No independent admission/abort deadlock found. Earlier tiles are fully admitted; abort may allow one extra task, but the driver exits its `left` wait on abort.
- **Q2:** The sequentially consistent `busy`/cursor protocol protects lambda lifetime. Late helpers cannot claim work after exhaustion. Actual consumer callbacks occur after nested decoding, and inspected pull callbacks do not nest pulls, so slot uniqueness holds.
- **Q3:** Checked: post-publication scoring reads `frag_traces` and `wst`; foreign weighting, fusion and recap modify separate objects. Successful carry contents match the old end-of-body copy.
- **Q4:** No output-changing race found. `visited` updates precede carry publication; output slots are disjoint; final precursor cleanup follows all tile completions. Counters and phase accumulation have synchronization.
- **Q5:** Finding 1 applies. Writers remain ordered, but completed-output residency exceeds the configured depth.
- **Q6:** No ordinary-data exactness defect found in co-ranks, odd runs, copy-back, total sorting, tie fallback or the GCC 13 introsort replay. Omitted window-sort fields are storage-only or derived from compared content for current producers.
- **Q7:** Apart from finding 3, the inspected compaction, distribution, absorption, conversion, extrema folding, bucket indexing and trimming preserve their original results.
- **Q8:** For `n_bands<=1`, the change newly enables nested vendor decoding. Inspected writer loops and patched EPD avoid additional nested teams; no output-order defect found.
- **Q9:** No newly introduced escaping exception found in current task-body instantiations. Existing allocation-failure gaps in older parallel bodies and `firstprivate` copies remain.
- **Q10:** Checked: smaller speculation batches preserve frozen-state evaluation, dependency validation, stale-result reevaluation and seed-order commit.
