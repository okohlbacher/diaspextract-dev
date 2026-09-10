## Adversarial Review Report: Cell grid, step 3b — the .d streaming source

---

### I. Numbered Findings

| # | Severity | file:line (933bba5) | Concrete failure scenario | Fix (as in dbcfa9c) |
|---|---|---|---|---|
| **1** | **HIGH** | `src/spextractor.cpp:4186` | Streaming source logs `"Parallelism: 0 windows x N bands = 0 trace units"` because it prints `window_list.size()` (0) instead of `n_win` (the true count from frozen tables). Downstream scheduling and user monitoring rely on the wrong count. | Use `n_win` in the log line and in the trace-units computation. |
| **2** | **HIGH** | `src/spextractor.cpp:3487-3498` | Pass 1 fails (e.g., missing calibration) → fallback to `loadExperiment` → `streamed=false` but `tile_source` stays `true` → tile loop calls `BrukerTimsFile().loadDIAStreaming(in, tc, c2)` on an already-resident-loaded run, passing an mzML-like `in` path to the Bruker loader (undefined behaviour, likely crash). | After the fallback catch, set `tile_source = false` and log the switch to resident. |
| **3** | **MEDIUM** | `src/spextractor.cpp:4332` | `-trace:band_edges slab -perf:stream_load true` on a .d: pass 1 completes (wasting minutes) only to throw at the `wbands` block. | Check and refuse `band_edges=slab` **before** pass 1 starts. |
| **4** | **HIGH** | `src/spextractor.cpp:4504-4513` | A tile where a window’s every frame has empty IM slices → slab has 0 frames but the frozen table expects N → later lockstep code sees a length mismatch or wrong padding count → **FrameTableError** or silent corruption. | For a window with `sl.frames()==0` but non-empty table slice, pad all frames from the table (`append` with 0 peaks) and account it as padded. |
| **5** | **LOW** | `src/spextractor.cpp:3482` | User runs `SPEXTRACTOR_LOAD_ONLY=1` on a .d streaming source expecting full-load timings; the output only covers pass 1 (MS1) with no clarification. | Log that under streaming source, LOAD_ONLY measures pass 1 only. |
| **6** | **HIGH** | *(logic in tile setup)* | Auto banding (`perf:trace_bands=0`) derives bands from *window count*: streaming source counts every acquisition window, resident counts only windows that delivered ≥1 frame → different `n_bands` → different `visited` arrays → **different trace output** for the same run. | Refuse auto banding (`perf:trace_bands ≤ 0`) under streaming source. |
| **7** | **MEDIUM** | *(det instrumentation)* | `-trace:detector integer -det`: the per-(window, tile) slab digests cannot be chained → no way to verify the streaming source emits *exactly* the same peaks as the resident source across tiles. The gate’s “spectrum data identical” check cannot be backed by a cryptographic digest. | Add `seed` to `slabDigest_`; chain digests per window across tiles; log chain value and per-tile digest. |
| **8** | **LOW** | `src/spextractor.cpp:4447` | `out_exp.setMetaValue("spx:tile_source", ...)` is set **after** `TileWriter` copies the settings → the stamp is missing from the mzML → downstream tools cannot tell streaming from resident runs. | Move the stamp before the writer is constructed. |

---

---

### II. Attack-line Verdict

| Attack line | Verdict | Rationale |
|---|---|---|
| **1. Exactness of the per-tile read** | **NOT SOUND** | The per-frame selection in the loader and the table restriction in `tc.tablefn` use the same half-open `[lo, hi)` test on `frame.time`, and the frozen tables are exported *before* selection, so the set is exact. **But** empty windows were not padded from their table slice (F4). Lockstep is now consistent. |
| **2. Pass 1 with lo > hi** | **SOUND** | Pass 1 sets `lo=+∞, hi=-∞`, loader emits zero MS2 frames, still exports the full frame table; `run_tables` are copied from `consumer.tables()`; `frozen` is built from `run_tables` (rt, id) identically to the resident path when P=0; RT axis uses the tables’ frame times. No flaw. |
| **3. n_win / fkeys replace window_list.size()** | **NOT SOUND** | `window_list` is **empty** under streaming source (no MS2 delivered in pass 1), so every use of its size is wrong. The parallelism log used it (F1); `n_win` fixes this. Resident slicing is unreachable under streaming source (guarded by `if (tile_source)`). |
| **4. Per-tile consumer** | **NOT SOUND** | Empty slabs for absent windows were not created from the table slice (F4); `indexRt`/`toTof` on empty slabs is safe (branches exist), but the missing padding breaks lockstep. `tile_slabs` is local to the tile iteration → freed after each tile; loader re-open per tile is the intended cost; `cstat` sharing is correct. |
| **5. trace:band_edges=slab and SPEXTRACTOR_TILE_RESIDENT** | **NOT SOUND** | `band_edges=slab` refusal was reachable *after* MS1 phase (F3). Refusal now before load. `SPEXTRACTOR_TILE_RESIDENT` is undocumented but harmless. Shared code for mzPeak is unaffected (`tile_source` is false for mzPeak). |
| **6. Fallback to loadExperiment** | **NOT SOUND** | The fallback leaves `tile_source=true` (F2), so the tile loop would call the Bruker loader on a resident-loaded run. Fixed by committing the source only after a successful pass 1. |
| **7. Performance** | **SOUND** | Pass 1 cost is one tdf open + MS1 + table export. Each tile re-opens the tdf (sqlite Frames 72k, DiaFrameMsMsInfo 134k rows) — acceptable for 13 tiles on TNBC (11:33 wall, 70.9 GB peak). No nested parallelism: tile loop is sequential; the loader’s parallel batch loop runs *inside* `readTile`, not inside a parallel region. LOAD phases sum as expected. |
| **8. Judged plan items not done here** | **NOT SOUND** | Chained `slabDigest_` per (window, tile) and `[det]` per-tile digests are **required** for the gate to be meaningful (F7); they verify the streaming source emits the same peaks as the resident source. Prefetch is step 5 (future). Without the chained digest, the gate’s identity check lacks a cryptographic basis. |

---
---
### III. Overall Assessment

**The original commit 933bba5 contains 6 HIGH/MEDIUM flaws** that would have caused:
- Silent wrongness (incorrect parallelism counts, missing metadata)
- Crashes or undefined behaviour (fallback path, empty-window lockstep)
- Inability to verify correctness (missing chained digests)
- Incompatible configuration (auto banding)

**All 8 findings are addressed in the review commit dbcfa9c**, and the re-run gate confirms: 14 arms, all spectrum-data identical to pins, 18/18 e2e, and the TNBC memory win (124.1 → 70.9 GB) stands.

**Attack lines found sound: 2, 7.**
The other six attack lines uncover real flaws (all fixed).
