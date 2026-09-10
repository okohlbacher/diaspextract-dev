# Adversarial review: cell grid, step 1 (b) -- frozen frame tables from the readers' metadata

Scope: commit 38907fb in this repository (HEAD). Run `git show 38907fb` for the full diff. Files:
- src/spextractor.cpp: `PickCompactConsumer` (struct `FrameTab`, `tablefn`, the lockstep append in
  `flush_()`, the tail pad in `finish()`), the loader call site in `main_` (the two `tablefn`
  lambdas, the post-load `[frames]` invariant and log), `PeakSlab::append` (n == 0 branch), the
  header stamp `spx:frame_table`.
- src/MzPeakStreamLoad.h: `MzPeakRunMeta`, `lastMzPeakMeta()`, `mzPeakRunMeta()`, and the
  rewritten head of `loadMzPeakStreaming`.
- patches/openms-brukertims-mz-calibration.patch: the new hunks only -- `DIAFrameRow`,
  `DIAWindowRow`, `lastDIAFrameTable()`, `lastDIAWindows()` in BrukerTimsFile.h; the file-local
  globals, the clear at the top of `loadDIAStreaming`, the export fill after
  `readFrameToWindowGroupMapping`, and the two accessors in BrukerTimsFile.cpp. The rest of the
  patch is unchanged code that was regenerated (hunk offsets moved).

The contract this implements is STEP 1 of docs/reviews/2026-09-10-tiled-reader-plan/judge.md
(the paragraph starting "STEP 1 -- frozen frame tables"). Read it first. The previous commit
(0862aa8, step 1a) already made the window store and the Pearson support come from a frozen
per-window table (`FrozenWin`, built from the resident slab); this commit makes the SLAB equal
the reader's metadata table by padding, so that table can later be the frozen one when only a
tile of frames is resident.

What must hold (the gate that will run on the cluster): with 0 padded frames on both pinned
datasets, the output must be BYTE-IDENTICAL to the step-1a build (dataset D at tile:rt_sec 600 /
-1 / 300, in both `trace:split_scan_time` modes; TNBC 009 at 600; the mzPeak S30 archive); the
cell-exactness probe (SPEXTRACTOR_MS2_RT_RANGE drops frames after picking -> those frames are now
PADDED as empty frames instead of absent) must still give core cells identical to the whole run.

Attack these specifically, and anything else you see:
1. Exactness at P = 0: is there ANY path where the padded/lockstep code changes the slab, the
   frame order, the frozen tables, `n_ms1`-based reservation, `slabDigest_`, or the RT axis when
   no frame is padded? (`append(n=0)` is new; an empty frame has frame_off[f] == frame_off[f+1].)
2. The lockstep itself: the cursor walks `while (rt[cur] != t) pad` with a BITWISE double compare;
   the .d export's `time` is the double stamped on the spectra (`spec.setRT(frame.time)`), the
   mzPeak meta's `rt[i]` is what `frameToSpectra_` stamps. Is bitwise equality guaranteed on both
   readers (any conversion, any float/double truncation, any `String` round trip)? Delivery order
   per window vs table order (the .d loop is group-major, batches of 256, serial hand-off in
   (frame, window) order; mzPeak `run(ms2)` over archive index order): can a window ever receive a
   frame out of table order, or twice? What happens with `SPEXTRACTOR_LOAD_BATCH`, with
   `trace:native_ms2_neighbors`, with an old-format tdf (synthetic window groups)?
3. Thread safety of the parallel per-window append: `FrameTab` objects live in `tables_` (a
   std::map) and are pointed to from `Batch::tab`; one thread per window per batch; `tables_` is
   not mutated inside the parallel region. Is that right? Is the error path (exception_ptr under a
   named critical, `break`, rethrow after the region) sound? Does a `break` leave the slab in a
   consistent state (the run aborts anyway)?
4. The .d export: `handle->get_frame(fid)` uses `frame_descs.at()`; `num_peaks` is uint32; the
   fill runs before the MS2 loop and after the `windows.empty()` early return (tables cleared at
   the top of the function). Groups in `group_to_frames` are ORDER BY Frame. The tool's lambda
   filters `num_peaks > 0` (the loop `continue`s on `frame.num_peaks == 0` for every window of the
   frame) and keys windows with `c = mz_center, off = mz_width / 2.0` -- exactly the reader's
   `prec.setMZ(win->mz_center)` / `setIsolationWindowLowerOffset(win->mz_width / 2.0)`; the
   consumer computes `lo = getMZ() - lower offset`. Are the keys bitwise-equal in every case? Two
   windows with the same (lo, hi, group) throw -- can that happen on a real diaPASEF method?
5. mzPeak: `mzPeakRunMeta` caches by path in a function-local static shared_ptr; the run lambda
   now reads `meta->rt` etc. through const refs; `exact` is a `shared_ptr<MzPeakExactMz>` inside a
   `shared_ptr<const MzPeakRunMeta>` and is passed as `exact.get()`. Lifetimes, the `lastMzPeakExact()`
   contract (reset then set inside the sweep), the number_of_peaks rule (== 0 skipped; absent =>
   present, logged), and the key expressions `c = 0.5*(lo+hi), off = 0.5*(hi-lo)` vs
   `frameToSpectra_`'s `prec.setMZ(0.5 * (win.lo + win.hi))`, offsets `0.5 * (win.hi - win.lo)`.
   The archive's `id` string parse for `frame=`. Group is 0 for every mzPeak window
   (`windowGroupOf` finds no `windowGroup=`).
6. The post-load invariant `slab.rt == table.rt` and the "absent window" rule (a table window
   that delivered nothing gets no slab). Is `frozen` (built from the padded slab, unchanged code)
   now exactly the metadata table for delivered windows? What about a window absent from the
   table but delivered (mzML has no table -> no check; a .d window not in `lastDIAWindows`)?
7. The probe interplay: `TileProbe::keepFrame` drops frames BEFORE the append; they are padded by
   the cursor walk. The step-1a build left them ABSENT. Does the per-cell cut
   (`lower_bound` on slab frame times, `sliceFrames`) treat an all-empty cell the same as a
   missing cell? Does an empty frame inside a cell change detection (`visited`, `frame_live`,
   the tof index, seeds)? Note: picked-empty frames already exist today (a frame whose peaks all
   fail the pick), so the detector already sees empty frames.
8. mzML input: no table (stamp `slab`). The judged plan said "mzml: a group's frames = the union
   over its windows"; this commit deliberately leaves mzML as the slab (resident, untiled).
   Is anything downstream (step 2's tile loop) going to need the union definition on mzML?
9. Anything that makes the step-2 tile loop harder: e.g. `tables_init_` lazily on the first MS2
   flush (both readers publish before their first MS2 frame -- is that true for the .d loader
   when `config.load_ms1 == false`, i.e. pass 2 of the tiled design?), `finish()` padding tails
   only for delivered windows.

Report format: numbered findings, each with severity (blocker / must-fix / should-fix / note),
the exact file:line, a concrete failure scenario (inputs -> wrong output), and the fix. Say
explicitly which of the nine attack lines you checked and found sound. Do not summarise the
diff back to me.
