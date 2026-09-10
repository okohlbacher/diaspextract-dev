**Two must-fix correctness issues remain.** I found no numerical change in the normal P=0 path. The cluster gates were not run; the local calibration test passed.

1. **must-fix — Structural table errors can continue with corrupted state.** [src/spextractor.cpp:1667](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1667), [3324](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3324), [3361](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3361).  
   An unexpected or repeated delivery exhausts the cursor, pads the remaining table, and throws. The catch treats this as recoverable, but leaves the partial `ms1_map`, slabs, and statistics intact. Full loading then appends the complete input onto them, duplicating frames and potentially producing nonmonotonic slab RTs. Separately, the post-load invariant throws **after `streamed=true`**: the catch logs “falling back” but skips fallback and continues with invalid data.  
   **Fix:** make table/alignment failures fatal; run validation outside the recoverable loader catch and assign `streamed=true` afterward. Any permitted fallback must discard all partial state.

2. **must-fix — RT-only matching silently puts signal into the wrong frame.** [src/spextractor.cpp:1563](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1563), [3334](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3334).  
   Consider metadata `(RT,id)=[(10,101),(10,102),(20,103)]`. Frame 101 has raw peaks but an empty slice for this window; frames 102 and 103 deliver. The cursor accepts `(10,102)` as row 101, then pads row 102. The resulting IDs are `[102,102,103]`, yet the RT invariant passes. mzPeak neither rejects duplicate RTs nor requires RT metadata—it defaults missing RTs to zero.

   This affects scoring: precursor samples at RT 10 and 20 map to `[1,0,1]`. Correct fragment placement `[0,1,1]` has Pearson −0.5; misplaced `[1,0,1]` has Pearson 1. I reproduced the cursor result and these correlations in an isolated model.  
   **Fix:** match delivered `(RT,frame_id)`, verify both vectors afterward, and reject or explicitly distinguish repeated identical identities.

3. **should-fix — Default mzML loading gets a false `loader` stamp.** [src/spextractor.cpp:3295](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3295), [4752](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4752).  
   With default `perf:stream_load=true`, mzML enters the non-mzPeak branch and sets `frame_table_src="loader"`. Bruker loading fails, resident loading succeeds, and the success-only reset at line 3325 never executes. The output therefore claims loader metadata despite using slab-derived tables.  
   **Fix:** assign provenance only after successful loading and validation; retain `"slab"` on resident fallback.

4. **should-fix — A delivered window missing from the table silently bypasses enforcement.** [src/spextractor.cpp:1644](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:1644), [3329](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3329).  
   For example, an inconsistent mzPeak archive declares zero peaks for every spectrum of window W but decoding produces nonempty spectra. W is omitted from the metadata table, receives `tab=nullptr`, and never enters the post-load invariant. Its frozen table comes from delivered data while the run can still claim metadata provenance.  
   **Fix:** distinguish “this reader has no table” from “this delivered key is missing”; require table membership for every delivered key when metadata tables are enabled.

5. **note — Duplicate-key rejection excludes geometry the .d schema permits.** [src/spextractor.cpp:3305](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3305).  
   Two rows with the same group/center/width but different scan ranges collide, as can different boundaries rounded to the same 0.01-Da key. The schema’s `(WindowGroup,ScanNumBegin)` primary key permits the former. Initialization throws even if both slices would deliver nothing, currently triggering finding 1. I did **not** establish an actual colliding acquisition among the inspected fixtures.  
   **Fix:** explicitly define and test rejection, or preserve full window/occurrence identity consistently through export, routing, and alignment.

6. **should-fix — A cache hit can expose another archive’s calibration through the “last” accessors.** [src/MzPeakStreamLoad.h:266](/Users/kohlbach/Claude/speXtractor/src/MzPeakStreamLoad.h:266).  
   Cache A successfully; attempt B, which resets or replaces calibration globals but fails before publishing its metadata; reload A. A’s peaks use cached A calibration, while `lastMzPeakExact()` can remain B/null and provenance can describe B. Ordinary same-path tile calls avoid this.  
   **Fix:** publish metadata and associated calibration/provenance transactionally, and restore the accessors from the returned metadata on cache hits.

7. **note — Step 2 must handle genuinely empty slabs before rebasing.** [src/spextractor.cpp:4372](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:4372).  
   A frozen window with no frames in a future tile still needs processing for carried fragments. Its cuts become `{0,0}`; detection returns safely, but rebasing dereferences `slab_rt[0]`. This is pre-existing step-1a code, not a regression introduced here.  
   **Fix:** handle zero-frame slabs explicitly and derive their frozen insertion position from the tile boundary. Preserve frozen keys independently of tile delivery.

8. **note — Mixed peak-count metadata produces a misleading diagnostic.** [src/MzPeakStreamLoad.h:301](/Users/kohlbach/Claude/speXtractor/src/MzPeakStreamLoad.h:301), [src/spextractor.cpp:3342](/Users/kohlbach/Claude/speXtractor/src/spextractor.cpp:3342).  
   One MS1 spectrum lacking `number_of_peaks` makes the log say every listed MS2 frame counts as present, although known-zero MS2 spectra remain excluded. Filtering itself is correct.  
   **Fix:** track MS2 availability separately and state that only spectra lacking the field are presumed present.

I checked all nine attack lines:

| Attack | Result |
|---|---|
| **1 — P=0 exactness** | **Sound on source inspection.** Same per-window append order, MS1 reservation count, peak arrays, offsets, frozen tables, RT axis and digest inputs. For picked-empty frames, the old `grow(...,0)` was already a no-op; the new branch preserves offsets. |
| **2 — Equality and delivery order** | **Reader transport is sound.** Both readers reuse the same RT doubles and preserve ordered handoff across batches. Synthetic groups use the loader’s own mapping. `native_ms2_neighbors` remains a streaming no-op. Identity ambiguity is finding 2. `!=` is numeric equality, not literally bitwise equality. |
| **3 — Parallel append** | **Ownership and synchronization are sound.** Maps are populated before the region; each window has one worker; pointers remain stable. The critical section and barrier safely publish the explicit mismatch error. `break` leaves structurally valid vectors, but the outer handling is unsafe—finding 1. |
| **4 — .d export** | **Sound**, apart from the unsupported-geometry question in finding 5. Export and spectra use identical doubles/key expressions; raw-zero filtering matches the reader. Clearing and early-return behavior are correct. |
| **5 — mzPeak** | **Ordinary loading is sound.** Shared ownership covers vectors and `exact.get()` through joined workers; key expressions, positive frame-ID normalization, group 0, archive order, and zero/absent-count filtering agree. Findings 2, 6 and 8 qualify this. |
| **6 — Frozen invariant / absence** | **Sound for unambiguous matched windows.** Entirely absent whole-run windows contribute no fragments. Missing delivered keys and unchecked IDs remain holes—findings 2 and 4. |
| **7 — Probe / empty cells** | **Sound for fully retained core cells with frozen TOF bounds.** Their arrays and detector state remain identical. All-empty cells generate no seeds/traces. Empty frames are not generally equivalent to absence: they count as scans and can change sample-rate acceptance in partially retained cells. |
| **8 — mzML union** | **No downstream correctness dependency found.** Per-window frozen sequences support resident slicing; the global RT axis already unions their times. Adding group-union padding would itself change sparse-mzML behavior. The provenance bug is finding 3. |
| **9 — Step-2 preparation** | **Publication timing is sound**, including `.d load_ms1=false`. Whole-run absent-window handling is harmless today; future tiles need independent frozen keys and the empty-slab guard in finding 7. |

The judged gate uses [semantic_digest.py](/Users/kohlbach/Claude/speXtractor/bench/semantic_digest.py:1), which compares spectrum-list bytes. Literal whole-file byte identity necessarily changes with `spx:frame_table` and shifted index offsets; that intended header change is not a numerical regression.
