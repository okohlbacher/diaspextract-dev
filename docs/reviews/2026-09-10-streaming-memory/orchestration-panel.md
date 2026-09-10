*Note on the input: the payload carried three designs (`pipeline`, `independent`, `one-pool`); the fourth design and the attack on `one-pool` were truncated out of the message. I judged the three that arrived, against the repo record at `/Users/kohlbach/Claude/speXtractor` — every number below is re-derived from `docs/reviews/2026-09-10-streaming-memory/data.md`, `docs/BASELINE.md` and the source, not from the briefs.*

---

# Verdict

**Build `one-pool`: the window-major (window, tile) DAG in one OpenMP team, with a reader agent and a writer agent outside it.** It is the only design that attacks the item that dominates the table — the per-tile occupancy collapse, **+32.2 s** on the controlled K=1→K=3 pair — and both rejected designs' own attacks independently arrive at it.

**Wall:** dataset D at the shipped grid (pitch 600, `cells_per_tile 1`, K=3) goes **177.1 s → ~127 s (2:57 → 2:07)**, i.e. **−14% against the fastest arm on record** (`stream_1tile`, 146.67 s) and −28% against the equal-memory arm. TNBC 009 goes **695.9 s → ~9:15** (−20%), and about 50 s of that is one line: `WRITE(mzML)` is **52.4 s at 1.0x** in the current 2-hour reference.

**Memory:** on the 2-hour file the peak stays at the pass-1 floor (190.9 GB → the MS1 pass, inferred ~85-100 GB), because the second slab set costs 1/12 of the run's MS2 slab at K=12. On D at K=3 it costs **31.8 → ~39.7 GB** — back to roughly the one-tile arm's 41.1 GB, because with only three cells the second slab is a third of the run. **On D you buy wall at flat memory; on the long file you buy both.** No step in this plan is S-class.

---

# Why, against each alternative

### `pipeline` — two-slot tile carousel: absorbed as a component, rejected as a design

Its own attack corrects the win to **−2.7 to −5.5 s (−1.5 to −3.3%)** at the defaults it registers, and `data.md` caveat 2 caps it independently: at 3 tiles the reads are 1.60 / 7.17 / 6.25 s against exclusive loop intervals of 12.1 / 62.0 / 46.6 s, so **a perfect prefetch hides at most 13.4 s of 177.1 s = 7.6%**. The item it explicitly does not touch is 2.4x larger: exclusive-loop wall on the *controlled* pair (same pitch 600, same digest `8c1b047f3f70066c`) is 89.5 s at K=1 against 121.7 s at K=3 — **+32.2 s of pure occupancy loss while CPU actually falls 5,990 → 5,207 s (−13%)**. And its self-described "single largest item," starting the reader at `:3831`, is fatal on inspection: the tile reads share `cstat` with pass 1 — the source says so at `spextractor.cpp:5307` — the reader writes `cstat.unmapped_frame` non-atomically, and the master reads it at `:4360` to flip `integer_detector`, which then clears `cell_edges`/`cell_pitch`. That is the detector switch, i.e. a science change, from a thread race. `tofAxis()` isn't even loaded at `:3831`, so the design's own `[det]` gate would read an empty axis. Verdict: keep its reader/writer agents and its instrumentation fixes (they are inside `one-pool` already), delete the early start.

### `independent` — shadow-cell tiles: killed by a fact in the source

The dependency it spends 55.8% of D's picked peaks to remove **does not exist at tile granularity**. The carry is keyed by window: `carry_out.at(wl[wi].first)` (`:5254`) and `carry_in.find(wl[wi].first)` (`:5060`). So (w, k+1) depends only on (w, k) — 24 independent chains, not a barrier. A per-window ready flag removes the same edge for **zero** redundant detection. The shadow at K=3 recomputes cells 1+2 = 702.1e6 of 1,258.05e6 picked peaks for a corrected tax of **+37 to +45 s** and **+7.8 GiB** over the identical orchestration without shadows; corrected net on D is ~160 s, **worse than not tiling at all** (146.67 s). Multi-machine it recomputes 6.74 GB of slab to avoid relaying a carry blob whose measured size is **118.1 MB** (summed from the `carrying out … KB` lines; ledger `carry` peak 166 MB) through a coordinator that already barriers on per-tile counts. Independently of the economics it has five hard defects, three of which I confirmed in the source: the MS1 release at `:5315-5318` becomes a use-after-free the instant tiles overlap (its safety today is the parallel region's implicit barrier *inside* the tile loop); `writeBlock`'s `#pragma omp parallel for` at `:2052` collapses to one thread whenever `perf:trace_bands 1` leaves `omp_set_max_active_levels(2)` at `:4316` uncalled; and its manifest omits `rtAxis()` (`:335`), the global every trace's frame index is an index *into*. Reject the shadow, the manifest and the multi-machine tier; keep two small things (below).

---

# Build order

Canonical numbers first: **the task brief, `data.md` and the `[perf]` table disagree** (brief 2:42/2:32/3:03/2:56 vs data.md 2:33.63/2:26.67/2:57.14/2:48.05; MiB reported as MB throughout). Two of the three attacks were partly built on the wrong set. `data.md` is the digest-checked record and is canonical below.

| step | class | what | gate | depends on |
|---|---|---|---|---|
| **0** | none (measurement only) | Fix the instrument: `phase_stats_()` is a plain `std::map` written by `~Phase`; `cpu_seconds_()` is `RUSAGE_SELF`; nested `LOAD(tile)`/`SORT`/`WRITE` are summed into `WINDOW_LOOP` (why the table reports 105-109% of total); MiB printed as MB. Correct `ledSet_(LC_SLAB)` with a **signed** correction, not `ledAdd_` — `flush_` already adds at `:1793`. | none | — |
| **1** | **D** | Move carry emission from `:5252` to just after the content-total sort at `:5123`. Verified: nothing between those lines writes `frag_traces` or `wst.inten` (only `frag_im`, `FragRt::build`, `buildFragStats`, `assembleOne_` read them). ~10 lines, standalone commit. | D digest `8c1b047f3f70066c` at K=1 and K=3; TNBC `da1b86fb5c38409f` | — (independent of 0) |
| **2** | **D** | Move the MS1 release (`:5315-5318`) and the coverage check (`:5280-5301`) out of `if (tile.last)` and behind an all-units join. Land it *before* concurrency exists so it can be bisected. | same digests | — |
| **3** | **D** | **Writer agent.** One `std::thread` at `omp_get_level()==0` draining an ordered block queue: `canonicalSort_` + DP push + `writeBlock`. Do **not** convert `writeBlock`'s `parallel for` to a taskloop. Size its team from the measured 48-50x, not `threads/8`. | D + TNBC digests, e2e check 14 (count / native ids / index / indexList) | — (independent) |
| **4** | **D** | **The DAG.** One team walking a global (window, tile) list with a per-window ready flag; slab ring with consumer refcount; **global** `active`/`inflight` so the 24-window cap spans all tiles. Carry becomes one heap slot per window, single writer, no lock. Instrument the *actual* team task count at all four layers — the bare taskloops at `:1170` (per cell per window), `:1923`, `:1249`/`:1454` are not in the ~2,700 estimate — and assert against 32×nthreads. | D digest × K{1,3} × threads{8,100}; TNBC × K{1,12}; e2e 14; **`[det]` slab chain must become a per-(window,tile) digest set compared against a sorted reference** — the order-dependent fold at `:4663` stops meaning anything once tiles overlap | 0, 1, 2 |
| **5** | **D** | **Reader agent**, strictly one tile at a time — a correctness requirement (`cstat` accumulates non-atomically in `flush_`; `g_dia_frame_table` / `g_dia_windows` / `g_mz_calibration` / `g_perf_load` are file-scope in the patch). Start it at entry to `PRECURSOR_INFER`, never earlier: `ms1_map` is released only at `:3871` and the MS1 pass **is** the process peak (31,031 MiB at t=9.1 s). `initHelperICVs` sets `omp_set_num_threads` + `omp_set_schedule` only — **never** `omp_set_max_active_levels`, which is device-scoped and would undo `:4316`. `sched_set` (`:1722`) becomes `thread_local`. | same digests + slab-digest set | 4 |
| **6** | **D** | Peak-count-balanced grouping from `Frames.NumPeaks`. Take the **13%** `data.md` measured at 3 tiles (densest tile 50% → 43%), not 8.3% and not −31%. No `frame_np` field needed. | digests | — (independent) |

**Independent tracks:** {0}, {1}, {3}, {6} can proceed in parallel; {2} → {4} → {5} is the serial spine. **S-class steps: none.** The one S-class temptation is the cell pitch (300 vs 600: Sage 13,836 vs 13,490, entrapment 1.38% vs 1.30%) — decline it. Any pitch change needs both engines plus entrapment FDR per the search-engine policy; this plan needs neither.

---

# Parts worth stealing

**From `pipeline`:** the five instrumentation fixes (step 0, with the `ledSet_(LC_SLAB)` correction); `initHelperICVs` minus `omp_set_max_active_levels`; `thread_local sched_set`; the RAII join placed so it covers the two throws *inside* the loop (`:5091` double-ownership, `:5290` no-owner coverage), with `~TileWriter` and the `.part` rename running on the master **after** it; the `writeBlock(k, …)` expected-k assert.

**From `independent`:** balanced grouping at the measured 13%; the binary-sha256 + parameter-digest stamp (useful single-machine, in the ledger header); the observation that the existing refusal of `trace:band_edges=slab` for the streaming source is now **load-bearing** and must stay; and its runtime completeness detector, repurposed as the DAG's per-window carry assertion.

**Not stolen:** shadow cells, the POD manifest, the MS1 blob, the multi-machine tier, `frame_np`.

---

# What to measure first

**One 3-minute run, before a line of orchestration.** Dataset D, pitch 600, `tile:cells_per_tile 1` (K=3), current binary + step 0's instrument, plus one counter: for each of the 24 windows, wall from the tile's parallel region opening to that window's task completing.

**The number:** the per-tile straggler gap, `(tile wall) − (median window wall)`, summed over the three tiles. It must account for the 32.2 s.

**The decision it changes:**
- If the gap concentrates in one or two windows — the suspect is `327.52-468.80 Da`, 141 Da wide, carrying **163,952** fragments out of tile 2 against ~50k for every other window — the DAG recovers it directly (that window simply runs on into the next tile while nothing waits) and the −34.9 s loop estimate holds. **Build steps 1-6.**
- If the gap is spread evenly across all 24 windows, the loop is bandwidth-limited at ~43x whenever its working set is a tile rather than a run, no scheduling recovers it, and the family collapses to steps **1 + 3** only — worth ~3 s on D and ~50 s on TNBC, still worth shipping, but the DAG is not.

**Second, same chain:** exclusive-loop wall at `cells_per_tile 3` (= K=1) vs K=3 with step 6's grouping, to split "unequal tiles" from "tile barrier" inside the 32.2 s.

---

# The honest ceiling

**Dataset D.** Prefix 27.8 s (`LOAD(stream)` 10.2 @66.8x + `MS1_TRACE` 13.9 @**14.5x** + `PRECURSOR_INFER` 3.7 @**15.8x**) + loop at the demonstrated 66.9x (5,207.4 CPU s → 77.8 s) + last write ~3 s + 8.7 s of setup/teardown = **~117 s (1:56)**, against 146.67 s today. The resource floor (5,207/100 = 52.1 s) is not reachable: the real floor is the widest isolation window's own serial chain. **Binding constraint then:** `MS1_TRACE` + `PRECURSOR_INFER` at 14-16x (17.6 s = 15% of the new total) and that one 141 Da window.

**TNBC 009 (2-hour).** Prefix 178.6 s (`LOAD(stream)` 94.5 @60.2x + `MS1_TRACE` 59.3 @26.9x + `PRECURSOR_INFER` 24.8 @31.0x) + loop 32,968.6 CPU s at 80-100x (330-412 s) + write ~5 s (from 52.4 s at 1.0x) + teardown = **520-600 s (8:40-10:00)**, against 695.9 s (11:35.90). Note what this actually buys on the long file: the loop is *already* at 80.0x untiled, so the DAG mostly makes tiling **free** (peak 190.9 GB → the pass-1 floor) rather than fast; the raw speed comes from the serial write and from not paying the tile barrier. **Binding constraint then:** the 178.6 s prefix, now **31-34% of the run**, of which `LOAD(stream)` is 94.5 s at 60x.

After that the levers are step 7 (per-cell pass 1, which is what moves the MS1 floor and is the next real memory lever) and band count — and BASELINE already settles band count on the science side (`trace:bands 24` fails dataset A, −1.61% Sage). So: **~1:56 on D and ~8:40 on TNBC is where this direction ends, and pass 1 is what is standing there.**
---

## The decisive measurement, run against the existing logs (2026-09-10)

The panel asked for one 3-minute run to decide between "the DAG recovers the tiling penalty" and
"the loop is bandwidth-limited and only the writer agent is worth building". The per-window stage
lines the tool already logs answer it without a new run. Dataset D, pitch 600, `cells_per_tile 1`
(K = 3), streaming source, 100 threads:

| tile | windows | median window | slowest window | straggler gap | completion span |
|---:|---:|---:|---:|---:|---:|
| 1 | 24 | 2.4 s | 12.2 s | 9.7 s | 11 s |
| 2 | 24 | 22.5 s | 61.2 s | **38.7 s** | 47 s |
| 3 | 24 | 22.9 s | 46.2 s | 23.3 s | 37 s |

**Total straggler gap: 71.7 s**, against the 32.2 s the tiling costs in occupancy. And it is
CONCENTRATED, exactly as the panel's first branch requires:

| tile | the slowest window | width | its wall | of which tracing | spectra |
|---:|---|---:|---:|---:|---:|
| 1 | 327.52-468.80 Da | 141.3 Da | 12.2 s | 9.4 s | 18,958 |
| 2 | 327.52-468.80 Da | 141.3 Da | **61.2 s** | 51.0 s | 71,294 |
| 3 | 779.91-808.42 Da | 28.5 Da | 46.2 s | 41.6 s | 11,059 |

The acquisition uses variable-width isolation windows, and one of them is 141 Da wide against a
~26 Da typical. In tile 2 it runs 61.2 s while the median window runs 22.5 s, and the tile cannot
close until it finishes. That is the tiling penalty, and it is a scheduling artefact, not a
bandwidth wall: **the decision rule fires on the first branch, so the (window, tile) DAG recovers
it directly** -- the wide window simply runs on into the next tile while nothing waits for it.
Build the plan.
