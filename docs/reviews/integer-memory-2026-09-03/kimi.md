• # Hostile memory review: integer-detector path

  Working numbers throughout: P = 5e7 peaks/window, F = 1,400 frames/window, T = 5e6–1e7 traces/window, 10 pts/trace, 24 windows, 12 band tasks/window, 48 EPD chunks/window. `TofIdx` assumed 4 B (it's compared against `uint32_t` and stored in `vector<uint32_t>`).

  ## 1. Per-structure inventory

  | # | Structure | B/elem | Simultaneous count | Peak bytes |
  |---|---|---|---|---|
  | 1 | `Trace` store (`out` per band: xi+xv+xt + struct) | 12 B/pt → 120 B + ~120 B struct + ~48 B malloc headers ≈ **290 B/trace** | all traces of 24 windows (detect runs before/while EPD consumes) | **34–67 GB** |
  | 2 | `FragGrid.flat` | 8 B/(int,float) | 8.5e6 frags × 510 pts = 4.3e9 entries, per window | **34.7 GB per grid** — see below |
  | 3 | EPD `MassTrace` phase | 24 B/pt (vector<Peak2D>) + ~300–500 B `MassTrace` (hulls, cached stats) ≈ 550–750 B/trace, **doubled** while `mts` and `split` coexist | up to a window's traces at once | **6–15 GB/window transient**, 50–150 GB if many windows mid-EPD at once |
  | 4 | `visited` per band task | 1 B × **P** (window-wide) | 12 × 24 = 288 arrays | **13.7 GiB** |
  | 5 | `PeakSlab` payload (tof 4 + inten 4 + imq 2) | 10 B/peak | 24 windows | **11.4 GiB** |
  | 6 | `TracePrep.frame_of` | 4 B/peak | 24 windows (shared per window) | **4.6 GiB** |
  | 7 | `TracePrep.member` | 1 B/peak | 24 | **1.1 GiB** |
  | 8 | `TracePrep.order` | 4 B/seed, reserved P/4 | 24 | **≤1.1 GiB** |
  | 9 | `FragGrid` mean/invnorm/off | 8.5e6 × 24 B | per grid | 204 MB/grid |
  | 10 | `frame_off`/`rt_index`/`b`/`frame_live`/`b_of_rt`/`got`/`pts` | — | — | < 100 MB total, noise |

  **Top three owners of the 105 GB: (1) the `Trace` store, (2) `FragGrid.flat` if it lives in this path's lifetime, (3) the EPD `MassTrace` double-copy.** Slab+visited+frame_of together are only ~30 GB — they are *not* the story.

  On (2): one grid per in-flight window is physically impossible (24 × 35 GB = 830 GB ≫ 105 GB), so grids must be serialized behind detection. If even 2–3 coexist while slabs and trace stores are still live, that's 70–105 GB by itself and *it is the peak*. Critically, `FragGrid` has **no `memAdd` accounting anywhere in the shown code** — your instrumentation is blind to the possibly-largest structure. Confirm by logging `flat.size()*8` at build time.

  On the residual: sum your `MEM_*` counters at peak and diff against 105 GB RSS. Whatever doesn't add up is (a) `FragGrid`, (b) emitted spectra accumulating across windows (not in this code — check where spectra are buffered before write), and (c) **glibc arena fragmentation**: ~3e7 small vector allocations per window (3 per trace) across 100 threads → up to 8×128 arenas, each hoarding freed chunks. Confirm with `MALLOC_ARENA_MAX=4` A/B or `mallinfo2`. I'd bet the residual is double-digit GB.

  ## 2. Duplication

  Genuinely simultaneous:

  - **`slab.tof` vs `Trace.xt`** (4 B/pt): `xt` copies bins out of the slab while the slab is alive for the whole window (EPD takes `sl` by const ref, `imq` is kept "for export"). ~1e8 traced pts/window → **~400 MB/window, ~9.6 GB total** held twice.
  - **`slab.inten` vs `Trace.xv`**: same ~400 MB/window, ~9.6 GB total. (Same for `xi` vs `rt_index`, trivial magnitude.) Unavoidable if the slab must persist for export — but see §5 on shrinking `xt`.
  - **EPD `mts` vs `split`**: `splitValleys(mts, ...)` returns a *new* vector while `mts` is still alive → the whole chunk's traces exist as two `MassTrace` copies (~500 B/trace × 2) for the duration of the split. This is the single largest *pure duplication* in the path.
  - **`t.mz` vs `(t.tof, t.b)`**: the struct's own comment admits `mz` is a cached convenience of the authoritative pair. 8 B/trace — trivial, but it's a lie-in-waiting.
  - **`FragGrid.flat` intensities vs `Trace.xv`**: the grid re-stores every trace point's intensity (as float inside an 8 B pair). If traces aren't freed before grid build, that's 12 B/pt + 8 B/pt simultaneously.

  Not actually simultaneous (fine, but worth stating):

  - Compact store vs slab: `toSlab` swaps each `CompactFrame`'s vectors away as it goes — sequential, good. Peak during `toSlab` is still slab_partial + compact_remaining ≈ one full window mass (~500 MB), fine.
  - EPD `list<Peak2D>` vs source `Trace` profile: `pk` is loop-scoped and `freeProfile()` runs per trace — the list is transient **one trace at a time** (~480 B). Note this means `MemGuard g_list(list_bytes)` *overstates* reality by ~5 orders of magnitude; the instrumentation lies about the list phase.
  - Source `Trace`s vs `parts[ci]`: freed chunk-wise via `freeProfile()` + `vector<Trace>().swap(in)` after the taskloop. Only staggered overlap.

  ## 3. Repeated passes

  Each **peak** (all P): (1) `toSlab` conversion; (2) `prepareTracing` pass 1 (frame_of + member); (3) `prepareTracing` pass 2 (order fill) — **passes 2 and 3 are fusible into one loop, no reason for two sweeps over 5e7 peaks**; (4) sort comparator touches seeds O(log) times; (5) the walk re-reads candidates inside the ±3sd window, and points of *rejected* traces can be re-scanned by later seeds (unbounded re-reads, mitigated only by `visited` on valid traces).

  Each **trace point**: (1) `best()`/accept reads; (2) fmin/fmax validation pass — **fusible into the walk** (track min/max frame as `got` grows); (3) `pts` build + sort — **eliminable**: `got` is produced by a bidirectional walk, so the profile is the down-run reversed concatenated with the up-run; a merge replaces both the sort and the 8 B/pt `pts` array; (4) profile build + apex scan; (5) EPD list build (with a `b_of_rt` hash lookup and a calibration call per point); (6) `splitValleys` internals (≥2–3 reads: smoothing, valley detection, split copy); (7) `toTrace` read-back; (8) apex **re-scan** in the split output loop — the apex was computable during split, this is a redundant pass; (9) export recomputes m/z from `(tof, b)`.

  That's ~9 reads per trace point, of which 3 (fmin/fmax, pts-sort, apex rescan) are pure waste and 1 (pass 2/3 split) is a wasted full-P sweep.

  ## 4. The `visited` array

  47.7 MiB per band task × 288 concurrent band tasks = **13.7 GiB**, for an array in which a band only ever *sets* bits for its accepted points: ~1e8 traced pts/window ÷ 12 bands ≈ 8.3e6 marks per 5e7-byte array — **~17% of the bytes ever touched, 99%+ of bits never set**.

  What it should be: the walk extends along *frames*; its tof reach is bounded by `cmz ± 3·sd` around the seed, i.e. a narrow bin corridor (at 10 ppm, m/z 600: ~±2 bins; robust sd grows it but not window-wide). But since nothing *provably* bounds the drift, don't size it to the band core — instead:

  - **Bitset** (`vector<uint64_t>(P/64)`): 6 MiB/band → **1.7 GiB total, −12 GiB**, zero semantic change, one `&`+shift per lookup. This is the right answer.
  - Or **one shared atomic `visited` per window** (48 MB → 1.2 GiB total, −12.5 GiB): *more* correct than today — currently two bands can both claim the same out-of-core peak and emit duplicate points, silently. But it changes which band wins the race → changes output. A/B on peptide counts before adopting.

  ## 5. More memory-efficient design (ranked by bytes saved per unit of risk)

  **1. Kill or shrink the EPD `MassTrace` round trip — save ~50–150 GB of peak transient. HIGH risk, biggest prize.**
  `Trace → list<Peak2D> → MassTrace(vector copy) → split copies → Trace` costs ~500–750 B/trace twice over. If `splitValleys` can be reimplemented on `vector<Peak2D>` or, better, in place on `Trace` (you already have xi/xv/xt and `sl`), the entire 24 B/pt Peak2D materialization, the per-instance hulls, and the mts/split doubling vanish. **Changes output if the split logic isn't replicated bit-exact** — results are gated on identified peptides, so verify against the 12,650-peptide reference and `tests/calibration_golden.json`. Cheap intermediate step that keeps OpenMS semantics: make the split move-construct rather than copy `mts`, halving the doubling.

  **2. Bitset `visited` — save 12 GiB. Free.** No output change, no time cost (cheaper cache footprint if anything). Verify: identical peptide counts, `MEM_VISITED` counter drops 8×.

  **3. Attack allocator fragmentation — plausibly 10–30 GB. Free to try.**
  One arena allocation per `Trace` (single block carved into xi/xv/xt) removes ~48 B of headers per trace (~480 MB/window, ~11 GB) *and* collapses 3e7 small allocs/window into 1e7; plus `MALLOC_ARENA_MAX=4` or mimalloc. No output change. Verify: RSS at fixed peptide count; diff `MEM_*` sum vs RSS before/after.

  **4. Shrink `Trace.xt` to int16 delta from the trace's bin — save ~4.8 GB. Low-medium risk.**
  The corridor is ±3 sd ≈ single-digit bins; int16 is vast headroom. Output identical iff the delta round-trip is exact — assert `xt[i] == tof + delta` in a debug run, then check peptide counts. Also fuse the free wins: single-pass `prepareTracing`, fmin/fmax in the walk, merge-instead-of-sort profile build (also deletes the transient `pts` array), drop the redundant apex rescan after split.

  **5. `frame_of` as `uint16_t` — save 2.3 GiB. Free.** F = 1,400 < 65,536; add a static guard. Zero output change. Alternatively delete it entirely and binary-search `frame_off` — trades ~17 comparisons per accepted point for 4.6 GiB; only if you're desperate.

  **6. Re-examine `FragGrid.flat` — up to ~35 GB/window. Unknown risk, possibly structural.**
  If it is per-window, building it *after* the slab and trace store for that window are freed, and capping concurrent grid builds to 1–2, moves it out of the peak. If its intensities can reference the trace store instead of copying (or if it can be built per-band and merged), the 8 B/pt copy shrinks. First **instrument it** (`memAdd` on `flat.capacity()*8`) — right now you cannot even see it.

  **7. Memory-for-time lever: cap in-flight windows 24 → 16.** −33% of slab + prep + visited + trace-store mass, roughly −20–35 GB at the high end, at some wall-time cost on a 128-core node that's already oversubscribed 100 threads × 24 windows. Not free, but it's the dial you turn if 1–6 aren't enough.

  Also fix the accounting lies while you're in there: `g_list` books bytes for lists that are destroyed per iteration, and `FragGrid` books nothing at all. A reviewer can't rank what the counters misreport.

