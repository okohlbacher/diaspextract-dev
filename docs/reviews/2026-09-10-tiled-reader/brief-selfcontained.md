# Adversarial review: cell grid, step 3b -- the .d streaming source (tile by tile through the loader)

Scope: the HEAD commit ("Cell grid, step 3b: the .d streaming source reads the run in two passes";
`git show HEAD`; parent 7e71998). Files: patches/openms-brukertims-mz-calibration.patch (the new
hunks: `Config::dia_ms2_rt_lo/hi` in BrukerTimsFile.h; in the streaming MS2 loop the per-group
selection `frame_ids` = the group's frames with `lo <= time < hi`, placed AFTER the frame-table
export and BEFORE the unchanged batch loop), src/spextractor.cpp (function-scope `cfg`/`spicker`,
`tile_source`, `run_tables`; pass 1 with lo = +inf / hi = -inf; `frozen` and the RT axis from the
tables; `n_win`/`fkeys`; `wbands` over the frozen keys with the slab scan only where a resident slab
exists; the per-tile read in the tile loop -- a fresh `PickCompactConsumer` over
`loadDIAStreaming(in, tc, c2)` with `tablefn` = the frozen tables restricted to [lo, hi), the
per-window invariant, empty slabs for absent windows, `indexRt`; the slab reservation from the
window's table count; `spx:tile_source`).

The contract is STEP 3b of docs/reviews/2026-09-10-tiled-reader-plan/judge.md. The gate that runs
now (scratchpad chain_step3b.sh): G0 -- one tile on D (600 / 300 / -1 trace) and TNBC (600) must be
IDENTICAL to the flipped-default pins (D `8c1b047f`, TNBC `bff54a1f`, the files under
/scratch/kohlbach/pins_acq); G1 -- D at 300 as 2/3/6 tiles x 8/100 threads and TNBC 600 as 13
tiles IDENTICAL; the resident source (SPEXTRACTOR_TILE_RESIDENT=1) as the same-build control;
per-tile read wall and RSS; e2e 18/18.

Attack:
1. Exactness of the per-tile read: is the set of frames the loader emits for [lo, hi) exactly the
   frozen table's frames in that range (the table is exported before the selection; `frame.time`
   is the same double; half-open on both sides; the cell edges are MS1 frame times, so no MS2 frame
   sits on an edge -- true for every acquisition?); does the batch loop over the selected subset
   pick each frame identically to the whole-run loop (the picker is per-frame pure: measured 256 ==
   4096 batches; anything batch-COMPOSITION dependent left, e.g. `SPEXTRACTOR_LOAD_BATCH`, the
   thread-local ZSTD contexts, `cents` merging)? The lockstep padding against the tile's table
   slice: a frame the loader skips (num_peaks == 0 is excluded from the table; an empty IM slice is
   padded) -- consistent with pass 1's whole-run table on the pinned files (0 pads)?
2. Pass 1: with lo > hi the loader emits no MS2 frame but `g_dia_frame_table` is filled; the
   consumer's `tables_` initialise at `finish()`'s `flush_()` with zero MS2 frames; every window
   is "absent" -> `frame_table_src = loader`, `run_tables` copied. `frozen` from `run_tables`
   (rt, id) -- identical to what the resident path derives from the padded slabs? The RT axis
   from `frozen` (all windows' frame times) -- identical to ms1 U slabs when P = 0?
3. `n_win`/`fkeys` replace `window_list.size()` for n_bands/n_conc/the log, and key `wbands`,
   `carry_out`, `visited`, the coverage check. Any remaining use of `window_list` that is wrong
   under the streaming source (it is EMPTY then)? The K > 1 resident slicing still iterates
   `window_list` -- unreachable under the streaming source?
4. The per-tile consumer: `ms1_none` (an empty PeakMap) as `ms1_`; `cstat` shared across tiles;
   `spicker` reused (its Param is deep-copied per flush); `tc.tablefn` captures `tile` by
   reference; `expected_frames` = the window's table count for the reserve (was `ms1_.size()`).
   The per-window invariant and the absent-window empty slab; `indexRt` on an empty slab;
   `toTof` later in the body on an empty slab; `sliceFrames` never called. Memory: what is
   resident across tiles now (the previous tile's `tile_slabs` freed at the end of the loop
   iteration? `wl` dangling?), the consumer's scratch, the loader's handle (re-opened per tile:
   cost?).
5. `trace:band_edges=slab` refuses under the streaming source -- but is the refusal reachable
   before the load? (It sits in the `wbands` block after the MS1 phase.) `SPEXTRACTOR_TILE_RESIDENT`
   as an undocumented switch. The mzPeak source is unchanged (resident) -- is anything in the
   shared code now wrong for it (e.g. `frozen` built from slabs when `tile_source` is false but
   `run_tables` non-empty)?
6. The `[stream] ... falling back to loadExperiment` catch around pass 1: with the streaming
   source, a fallback to the resident load would silently produce a resident run with
   `tile_source` still true -> what happens in the tile loop (the loader called again on an mzML
   path?) Is that path reachable for a `.d`?
7. Performance: pass 1 opens the tdf and iterates the MS2 mapping only to export the table; each
   tile re-opens the tdf (sqlite Frames 72k rows, DiaFrameMsMsInfo 134k rows, T1, windows) --
   estimate; the loader's parallel batch loop runs OUTSIDE the window loop's parallel region
   (the tile loop calls readTile before `#pragma omp parallel`) -- any nested-parallelism hazard?
   LOAD(tile) phases sum vs the one-tile LOAD.
8. The judged plan's items not done here: chained `slabDigest_` per (window, tile); the
   `[det]` per-tile digests; the prefetch (step 5). Anything that must be in THIS commit for the
   gate to be meaningful?

Report: numbered findings with severity, file:line, a concrete failure scenario, the fix; then the
attack lines found sound.

---

# EVERYTHING YOU NEED IS INLINE BELOW. DO NOT RUN ANY SHELL COMMAND.

You have no shell and no file access in this run. Every command you would want to run has been run
for you and its output is pasted below. Answer from this text alone. If a fact you need is genuinely
absent, say so explicitly and reason without it rather than asking for a tool.

## `git show --stat 933bba5` (the commit under review)
commit 933bba55782edab8e5cc4671596049f8b5f97a01
Author: Oliver <oliver.kohlbacher@uni-tuebingen.de>
Date:   Thu Sep 10 07:15:22 2026 +0200

    Cell grid, step 3b: the .d streaming source reads the run in two passes -- pass 1 MS1 only (the loader still exports the whole DIA frame table; the frozen tables and the RT axis come from it), pass 2 one loader call per tile over the calibration patch's new Config::dia_ms2_rt_lo/hi (half-open; frames outside are neither decoded nor emitted) into a fresh consumer lockstep-padded against the tile's slice of the frozen tables; the slab reservation uses the window's table count; run-level structures (band edges, carry, visited, coverage) are keyed by the frozen tables; trace:band_edges=slab refuses under the streaming source; SPEXTRACTOR_TILE_RESIDENT=1 keeps the resident source for the same-build control; header stamp spx:tile_source

 patches/openms-brukertims-mz-calibration.patch |  76 ++++++++-----
 src/spextractor.cpp                            | 142 +++++++++++++++++++------
 2 files changed, 158 insertions(+), 60 deletions(-)

## The full diff of 933bba5 against its parent
```diff
commit 933bba55782edab8e5cc4671596049f8b5f97a01
Author: Oliver <oliver.kohlbacher@uni-tuebingen.de>
Date:   Thu Sep 10 07:15:22 2026 +0200

    Cell grid, step 3b: the .d streaming source reads the run in two passes -- pass 1 MS1 only (the loader still exports the whole DIA frame table; the frozen tables and the RT axis come from it), pass 2 one loader call per tile over the calibration patch's new Config::dia_ms2_rt_lo/hi (half-open; frames outside are neither decoded nor emitted) into a fresh consumer lockstep-padded against the tile's slice of the frozen tables; the slab reservation uses the window's table count; run-level structures (band edges, carry, visited, coverage) are keyed by the frozen tables; trace:band_edges=slab refuses under the streaming source; SPEXTRACTOR_TILE_RESIDENT=1 keeps the resident source for the same-build control; header stamp spx:tile_source

diff --git a/patches/openms-brukertims-mz-calibration.patch b/patches/openms-brukertims-mz-calibration.patch
index c1fd512..374fd62 100644
--- a/patches/openms-brukertims-mz-calibration.patch
+++ b/patches/openms-brukertims-mz-calibration.patch
@@ -6,23 +6,38 @@
 # exports BrukerTimsFile::lastMzCalibration() so the emitted file can record which path ran.
 #
 # Base: OpenMS/OpenMS develop bd4b89555629d68b431b189a4c841efbcc4dfeea (2026-04-24).
-# Regenerated 2026-09-10 (DIA frame-table export) as a UNIFIED diff against that public commit. The previous version was
+# Regenerated 2026-09-10 (DIA frame-table export, MS2 RT-range entry point) as a UNIFIED diff against that public commit. The previous version was
 # generated against a partially-patched tree -- its BrukerTimsFile.h hunk carried, as context, a
 # comment the patch itself introduces -- so it could never apply to a pristine checkout.
 # Apply with: patch -p1 -d <OpenMS tree> < this file
 --- a/src/openms/include/OpenMS/FORMAT/BrukerTimsFile.h
 +++ b/src/openms/include/OpenMS/FORMAT/BrukerTimsFile.h
-@@ -12,7 +12,9 @@
+@@ -12,7 +12,10 @@
  #include <OpenMS/INTERFACES/IMSDataConsumer.h>
  #include <OpenMS/OPENSWATHALGO/DATAACCESS/SwathMap.h>
  #include <cstdint>
++#include <limits>
 +#include <map>
  #include <string>
 +#include <vector>
  
  class TimsDataHandle;
  
-@@ -120,6 +122,24 @@
+@@ -61,6 +64,13 @@
+       int   ms1_centroid_max_peaks = 100000; ///< Upper bound on centroided peaks per MS1 spectrum. Caps retention at the top-intensity peaks; low-intensity tail is dropped when the limit is hit (a warning is emitted at that point). Sized for aggregated MS1 where frame-stacked grids commonly exceed 200k peaks; per-frame MS1 rarely hits even 10k.
+ 
+       int dia_ms2_n_neighbors = 0;  ///< DIA MS2 frame aggregation: number of adjacent frames on each side (0 = disabled, 1 = 3-frame sum, 2 = 5-frame sum)
++      /// [speXtractor] Stream only the DIA MS2 frames whose time lies in [dia_ms2_rt_lo, dia_ms2_rt_hi)
++      /// (half-open, seconds; the defaults select every frame; lo > hi selects none -- an MS1-only
++      /// pass that still exports the frame table). Frames outside the range are neither decoded nor
++      /// emitted; everything about a selected frame is unchanged, so a caller that reads the run as
++      /// several ranges sees, per frame, exactly what one whole-run call emits.
++      double dia_ms2_rt_lo = -std::numeric_limits<double>::infinity();
++      double dia_ms2_rt_hi = std::numeric_limits<double>::infinity();
+       int dia_ms2_min_support = 1;  ///< DIA MS2 denoising: minimum occupied neighbors in 3x3 (mz x IM) grid to retain a point (center excluded)
+       bool dia_ms2_centroid = false; ///< DIA MS2 2D peak picking: apply Gaussian smoothing + local maxima detection to produce IM_CENTROIDED spectra
+ 
+@@ -120,6 +130,24 @@
                            const Config& config);
  
      /// Load entire .d directory into MSExperiment
@@ -64,10 +79,13 @@
  #include <opentims++/scan2inv_ion_mobility_converter.h>
  #include <OpenMS/FORMAT/RationalScan2ImConverter.h>
  #include <SQLiteCpp/SQLiteCpp.h>
-@@ -921,6 +929,114 @@
-     }
-   }
- 
+@@ -918,9 +926,117 @@
+         return PerFramePressureCompensationWithMissingReference;
+       default:
+         return NoPressureCompensation;
++    }
++  }
++
 +// [speXtractor table-mz] License-free EXACT TOF->m/z from the TDF MzCalibration table.
 +// The MODEL lives in speXtractor's own repo (src/TdfMzCalibration.h, BSD-3, copied here by
 +// scripts/sync_cluster.sh) so the shipped code is the code the C++ unit test exercises.
@@ -131,7 +149,7 @@
 +      cal_.C2 = sqlite3_column_double(st, 5); cal_.T1_ref = sqlite3_column_double(st, 6);
 +      cal_.dC1 = sqlite3_column_double(st, 7); cal_.dC2 = sqlite3_column_double(st, 8);
 +      cal_.C3 = sqlite3_column_double(st, 9);  cal_.C4 = sqlite3_column_double(st, 10);
-+    }
+     }
 +    sqlite3_finalize(st); st = nullptr;
 +    if (!cal_.isSupported())
 +    { const std::string why = cal_.unsupportedReason(); sqlite3_close(db); throw std::runtime_error("TdfMzCalibration: " + why); }
@@ -158,7 +176,7 @@
 +    }
 +    sqlite3_finalize(st);
 +    sqlite3_close(db);
-+  }
+   }
 +  // frame_id 0 is not a real Bruker frame (Frames.Id is 1-based); one pristine OpenMS DDA path
 +  // converts with a hardcoded 0. Slot 0 therefore holds T1_ref by construction = no temperature
 +  // correction (<=0.7 ppm on the files measured). Documented rather than incidental.
@@ -174,7 +192,7 @@
 +  std::string description() override final { return "TdfMzCalibration (ModelType 1 + temperature, exact)"; }
 +};
 +} // namespace
-+
+ 
 +
    // =====================================================================
    // Helper: open TimsDataHandle with tiered calibration strategy
@@ -405,10 +423,11 @@
      std::map<int, std::vector<const DIAWindow*>> group_to_windows;
      for (const auto& w : windows)
        group_to_windows[w.window_group].push_back(&w);
-@@ -1448,71 +1662,124 @@
+@@ -1448,71 +1662,131 @@
      startProgress(0, total_work, "Streaming DIA-PASEF MS2 frames");
      Size progress_count = 0;
  
+-    for (const auto& [group, frame_ids] : group_to_frames)
 +    // [speXtractor par-load] FRAME-MAJOR, PARALLEL, DECODE-ONCE.
 +    //
 +    // The original loop was window-major: for each window of a group, for each frame, decode the
@@ -426,12 +445,19 @@
 +    size_t batch = 256;
 +    if (const char* e = std::getenv("SPEXTRACTOR_LOAD_BATCH")) { const long v = std::atol(e); if (v > 0) batch = (size_t)v; }
 +
-     for (const auto& [group, frame_ids] : group_to_frames)
++    for (const auto& [group, frame_ids_all] : group_to_frames)
      {
        auto wit = group_to_windows.find(group);
        if (wit == group_to_windows.end()) continue;
 -      const auto& dia_windows = wit->second;
 +      const auto& dia_windows = wit->second;   // windows of this group, in table order
++      // [speXtractor tile] the frames of this group whose time lies in the configured range (the
++      // frame table above was exported for ALL of them); the batch loop below is unchanged, so a
++      // selected frame is decoded, sliced and emitted exactly as in a whole-run call
++      std::vector<uint32_t> frame_ids;
++      frame_ids.reserve(frame_ids_all.size());
++      for (uint32_t fid : frame_ids_all)
++      { const double t = handle->get_frame(fid).time; if (t >= config.dia_ms2_rt_lo && t < config.dia_ms2_rt_hi) frame_ids.push_back(fid); }
  
 -      for (const DIAWindow* win : dia_windows)
 +      for (size_t b0 = 0; b0 < frame_ids.size(); b0 += batch)
@@ -473,21 +499,15 @@
 -
            frame.save_to_buffs(nullptr, scan_ids.data(), nullptr, intensities.data(),
 -                              mzs.data(), inv_ion_mobilities.data(), nullptr);
--
++                              mzs.data(), inv_ion_mobilities.data(), nullptr, tl_ctx.get());
++          frame.close();                                    // releases the frame's view of OUR buffer
+ 
 -          MSSpectrum spec;
 -          spec.setRT(frame.time);
 -          spec.setMSLevel(2);
 -          spec.setDriftTimeUnit(DriftTimeUnit::VSSC);
 -          spec.setType(SpectrumSettings::SpectrumType::CENTROID);
 -          spec.setNativeID("frame=" + String(frame.id) + " windowGroup=" + String(win->window_group) + " scan=" + String(win->scan_begin));
-+                              mzs.data(), inv_ion_mobilities.data(), nullptr, tl_ctx.get());
-+          frame.close();                                    // releases the frame's view of OUR buffer
- 
--          Precursor prec;
--          prec.setMZ(win->mz_center);
--          prec.setIsolationWindowLowerOffset(win->mz_width / 2.0);
--          prec.setIsolationWindowUpperOffset(win->mz_width / 2.0);
--          spec.setPrecursors({prec});
 +          auto& slot = out[(size_t)k];
 +          slot.reserve(dia_windows.size());
 +          for (const DIAWindow* win : dia_windows)
@@ -499,8 +519,11 @@
 +            spec.setType(SpectrumSettings::SpectrumType::CENTROID);
 +            spec.setNativeID("frame=" + String(frame.id) + " windowGroup=" + String(win->window_group) + " scan=" + String(win->scan_begin));
  
--          spec.setMetaValue("ion mobility lower limit", win->im_lower);
--          spec.setMetaValue("ion mobility upper limit", win->im_upper);
+-          Precursor prec;
+-          prec.setMZ(win->mz_center);
+-          prec.setIsolationWindowLowerOffset(win->mz_width / 2.0);
+-          prec.setIsolationWindowUpperOffset(win->mz_width / 2.0);
+-          spec.setPrecursors({prec});
 +            Precursor prec;
 +            prec.setMZ(win->mz_center);
 +            prec.setIsolationWindowLowerOffset(win->mz_width / 2.0);
@@ -509,6 +532,9 @@
 +            spec.setMetaValue("ion mobility lower limit", win->im_lower);
 +            spec.setMetaValue("ion mobility upper limit", win->im_upper);
  
+-          spec.setMetaValue("ion mobility lower limit", win->im_lower);
+-          spec.setMetaValue("ion mobility upper limit", win->im_upper);
+-
 -          DataArrays::FloatDataArray im_array;
 -          IMDataConverter::setIMUnit(im_array, DriftTimeUnit::VSSC);
 -
@@ -572,7 +598,7 @@
        }
      }
      endProgress();
-@@ -1526,9 +1793,14 @@
+@@ -1526,9 +1800,14 @@
      load(path, exp, Config());
    }
  
@@ -587,7 +613,7 @@
      auto handle = openTimsDataHandle(path, config);
  
      String tdf_path = path + "/analysis.tdf";
-@@ -1551,6 +1823,7 @@
+@@ -1551,6 +1830,7 @@
      loadExperimentalSettings_(path, exp);
  
      // Sort by RT, interleaved across MS levels
diff --git a/src/spextractor.cpp b/src/spextractor.cpp
index 82a4d8b..5247905 100644
--- a/src/spextractor.cpp
+++ b/src/spextractor.cpp
@@ -1675,7 +1675,8 @@ namespace
         Batch& bw = per_win[(size_t)w];
         for (int i : bw.idx)
         {
-          if (bw.tab && !bw.tab->step(*bw.slab, frt[(size_t)i], fid[(size_t)i], n_ms1))   // [frames] lockstep with the frozen table
+          const size_t exp_f = bw.tab ? bw.tab->rt.size() : n_ms1;   // the window's frame count: exact when a table exists
+          if (bw.tab && !bw.tab->step(*bw.slab, frt[(size_t)i], fid[(size_t)i], exp_f))   // [frames] lockstep with the frozen table
           {
             #pragma omp critical(pad_err)
             if (!pad_err) pad_err = std::make_exception_ptr(FrameTableError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
@@ -1684,7 +1685,7 @@ namespace
             break;
           }
           const size_t o = scratch_off_[(size_t)i];
-          bw.slab->append(frt[(size_t)i], fid[(size_t)i], &scratch_mzq_[o], &scratch_inten_[o], &scratch_imq_[o], kept[(size_t)i], n_ms1);
+          bw.slab->append(frt[(size_t)i], fid[(size_t)i], &scratch_mzq_[o], &scratch_inten_[o], &scratch_imq_[o], kept[(size_t)i], exp_f);
         }
       }
       if (pad_err) std::rethrow_exception(pad_err);
@@ -1761,7 +1762,7 @@ namespace
       // [frames] the tail of every delivered window's table; a table window that delivered nothing
       // gets no slab (it is counted as absent by the caller)
       for (auto& kv : tables_)
-      { auto w = windows_.find(kv.first); if (w != windows_.end()) kv.second.tail(w->second, ms1_.size()); }
+      { auto w = windows_.find(kv.first); if (w != windows_.end()) kv.second.tail(w->second, kv.second.rt.size()); }
     }
 
   private:
@@ -3361,26 +3362,41 @@ protected:
               "trace:band_edges=acquisition: no candidate tdf provides a calibration:" + reasons + " (the integer detector cannot run on this input; -trace:detector openms is the escape)");
     }
     String frame_table_src = "slab";   // [frames] where the frozen frame tables came from: loader | mzpeak | slab
-
-    if (stream_load)
+    // [3b] the .d streaming SOURCE: pass 1 reads MS1 only (the loader exports the whole frame
+    // table regardless), pass 2 reads each tile's MS2 frames through the loader's RT range. The
+    // resident source (mzPeak, mzML, perf:stream_load=false, or SPEXTRACTOR_TILE_RESIDENT=1 for an
+    // A/B) holds the whole run and slices it, as before.
+    bool tile_source = false;
+    PickCompactConsumer::FrameTables run_tables;   // the reader's frozen tables, kept for pass 2
+    BrukerTimsFile::Config cfg;
+    cfg.dia_ms2_n_neighbors = getIntOption_("trace:native_ms2_neighbors");
+    cfg.ms1_n_neighbors     = getIntOption_("trace:native_ms1_neighbors");
+    PeakPickerIM spicker;
     {
-      // [stream] frame-by-frame: pick + compact on arrival, never hold the whole run.
-      // Also the ONLY place the reader's NATIVE pre-centroid frame aggregation is reachable.
-      BrukerTimsFile::Config cfg;
-      cfg.dia_ms2_n_neighbors = getIntOption_("trace:native_ms2_neighbors");
-      cfg.ms1_n_neighbors     = getIntOption_("trace:native_ms1_neighbors");
-      PeakPickerIM spicker;
       Param sp = spicker.getParameters();
       sp.setValue("pickIMCluster:im_tolerance_cluster", getDoubleOption_("gate:delta_im"));
       sp.setValue("pickIMCluster:ppm_tolerance_cluster", getDoubleOption_("trace:mass_error_ppm"));
       if (const char* m = std::getenv("SPEXTRACTOR_PICK_MZ_MODE")) sp.setValue("pickIMCluster:mz_mode", std::string(m));   // [C2 pick-level A/B] weighted|seed|top3
       spicker.setParameters(sp);
+    }
+
+    if (stream_load)
+    {
+      // [stream] frame-by-frame: pick + compact on arrival, never hold the whole run.
+      // Also the ONLY place the reader's NATIVE pre-centroid frame aggregation is reachable.
       PickCompactConsumer consumer(spicker, ms2_by_window, ms1_map, cstat, winKey);
 #ifdef SPEXTRACTOR_WITH_MZPEAK
       const bool in_mzpeak = (FileHandler::getTypeByFileName(in) == FileTypes::MZPEAK);
 #else
       const bool in_mzpeak = false;
 #endif
+      tile_source = !in_mzpeak && std::getenv("SPEXTRACTOR_TILE_RESIDENT") == nullptr;
+      if (tile_source)
+      {
+        // pass 1: MS1 only; lo > hi selects no MS2 frame, the loader exports the table anyway
+        cfg.dia_ms2_rt_lo = std::numeric_limits<double>::infinity();
+        cfg.dia_ms2_rt_hi = -std::numeric_limits<double>::infinity();
+      }
       // [frames] The frozen frame tables come from the READER's metadata, keyed with the reader's
       // own precursor expressions so the keys equal the consumer's: the .d loader exports its
       // frame table and windows (patch: lastDIAFrameTable/lastDIAWindows; frames with no raw peaks
@@ -3473,6 +3489,8 @@ protected:
       }
       // [frames] the invariant the frozen tables rest on, checked OUTSIDE the recoverable catch: a
       // delivered window's slab is its table (rt and id, frame for frame) after padding
+      if (streamed && tile_source && consumer.tables().empty())
+        throw FrameTableError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[3b] the .d loader exported no frame table; the tiled source cannot read this input", in);
       if (streamed && !consumer.tables().empty())
       {
         size_t n_pad = 0, n_del = 0, n_absent = 0;
@@ -3480,14 +3498,16 @@ protected:
         {
           const String wl = String(kv.first[0] / 100.0) + "-" + String(kv.first[1] / 100.0);
           const auto w = ms2_by_window.find(kv.first);
-          if (w == ms2_by_window.end()) { ++n_absent; writeLogInfo_("[frames] window " + wl + ": absent (no frame delivered), " + String(kv.second.rt.size()) + " in the table"); continue; }
+          if (w == ms2_by_window.end()) { ++n_absent; if (!tile_source) writeLogInfo_("[frames] window " + wl + ": absent (no frame delivered), " + String(kv.second.rt.size()) + " in the table"); continue; }
           if (w->second.rt != kv.second.rt || w->second.frame_id != kv.second.id)
             throw FrameTableError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[frames] a window's slab is not its frozen frame table after padding", wl);
           n_pad += kv.second.padded; n_del += kv.second.delivered;
           writeLogInfo_("[frames] window " + wl + ": delivered " + String(kv.second.delivered) + ", padded " + String(kv.second.padded) + " of " + String(kv.second.rt.size()));
         }
         frame_table_src = table_src_if_ok;
-        writeLogInfo_("[frames] source=" + frame_table_src + " windows=" + String(consumer.tables().size()) + " delivered=" + String(n_del) + " padded=" + String(n_pad) + " absent=" + String(n_absent));
+        run_tables = consumer.tables();
+        writeLogInfo_("[frames] source=" + frame_table_src + " windows=" + String(consumer.tables().size()) + " delivered=" + String(n_del) + " padded=" + String(n_pad) + " absent=" + String(n_absent)
+                      + (tile_source ? " (pass 1: MS1 only; the windows' frames are read per tile)" : ""));
 #ifdef SPEXTRACTOR_WITH_MZPEAK
         if (in_mzpeak && spx::lastMzPeakMeta())
           writeLogInfo_("[frames] mzPeak number_of_peaks: " + String(spx::lastMzPeakMeta()->n_peaks_missing_ms2) + " MS2 spectra lack it and count as present"
@@ -3613,8 +3633,12 @@ protected:
     // [cell] the frozen frame tables (see FrozenWin); today from the resident slabs, before
     // indexRt() frees their frame times and toTof() their frame ids
     map<WinKey, FrozenWin> frozen;
-    for (const auto& kv : ms2_by_window)
-    { FrozenWin& fw = frozen[kv.first]; fw.frame_rt = kv.second.rt; fw.frame_id = kv.second.frame_id; }
+    if (tile_source)
+      for (const auto& kv : run_tables)   // [3b] every window of the reader's table, no slab needed
+      { FrozenWin& fw = frozen[kv.first]; fw.frame_rt = kv.second.rt; fw.frame_id = kv.second.id; }
+    else
+      for (const auto& kv : ms2_by_window)
+      { FrozenWin& fw = frozen[kv.first]; fw.frame_rt = kv.second.rt; fw.frame_id = kv.second.frame_id; }
     // THE GLOBAL RT AXIS. Every frame contributes one retention time; every trace point sits on a
     // frame. Building it here, once, is what lets a trace point be 8 bytes (frame index +
     // intensity) instead of 16 (RT + intensity), and lets two profiles be aligned by integer
@@ -3626,7 +3650,7 @@ protected:
       { size_t nf = ms1_map.size(); for (const auto& kv : ms2_by_window) nf += kv.second.frames();
         ax.reserve(nf + 1024); }   // MS1 *and* every window's MS2 frames land here [mem]
       for (const auto& sp : ms1_map) ax.push_back(sp.getRT());
-      for (const auto& kv : ms2_by_window) ax.insert(ax.end(), kv.second.rt.begin(), kv.second.rt.end());
+      for (const auto& kv : frozen) ax.insert(ax.end(), kv.second.frame_rt.begin(), kv.second.frame_rt.end());   // the tables' frame times (== the slabs' after padding)
       sort(ax.begin(), ax.end());
       ax.erase(unique(ax.begin(), ax.end()), ax.end());
       writeLogInfo_("RT axis: " + String(ax.size()) + " distinct frame retention times"
@@ -4082,6 +4106,8 @@ protected:
     vector<pair<WinKey, PeakSlab*>> window_list;
     window_list.reserve(ms2_by_window.size());
     for (auto& kv : ms2_by_window) window_list.emplace_back(kv.first, &kv.second);
+    const size_t n_win = frozen.size();   // the run's windows (the resident list is empty under the tiled source)
+    vector<WinKey> fkeys; fkeys.reserve(n_win); for (const auto& kv : frozen) fkeys.push_back(kv.first);
     // [heavy-first] Process the biggest windows FIRST. With n_conc slots and unequal windows,
     // a small window admitted late runs nearly alone in the tail; starting the largest first
     // gives the scheduler the whole run to overlap it. The widest tile holds ~23.7% of all
@@ -4126,7 +4152,7 @@ protected:
     // the thread budget so windows x bands cannot oversubscribe.
     int n_bands = getIntOption_("perf:trace_bands");
     if (n_bands <= 0)  // auto: enough bands that windows x bands covers every thread
-      n_bands = (int)std::ceil((double)n_threads / std::max<size_t>(window_list.size(), 1));
+      n_bands = (int)std::ceil((double)n_threads / std::max<size_t>(n_win, 1));
     n_bands = std::max(1, n_bands);
     // TOTAL live threads are outer x inner. Capping only the inner team (as a first cut did)
     // gave 24 windows x 9 bands = 216 threads on a 224-core box that another job was already
@@ -4149,14 +4175,14 @@ protected:
     // memory (157 GB both ways). The pool's regression was the gate's bandwidth problem amplified
     // by concurrency, not a working-set problem of its own -- so the cap is not needed, and taking
     // it out costs nothing. `perf:max_concurrent_windows` still bounds it for a small machine.
-    int n_conc = (int)window_list.size();
+    int n_conc = (int)n_win;
     if (max_conc > 0) n_conc = std::min(n_conc, max_conc);
     if (n_conc < 1) n_conc = 1;
 #ifdef _OPENMP
     // outer loop over windows + inner loop over bands = two live levels
     if (n_bands > 1) omp_set_max_active_levels(2);
 #endif
-    writeLogInfo_("Parallelism: " + String(window_list.size()) + " windows x " + String(n_bands)
+    writeLogInfo_("Parallelism: " + String(n_win) + " windows x " + String(n_bands)
                   + " m/z bands = " + String((int)window_list.size() * n_bands) + " trace units; "
                   + String(n_threads) + " worker threads over one task pool; up to "
                   + String(n_conc) + " windows in flight (memory-bounded)");
@@ -4296,15 +4322,22 @@ protected:
         throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
               "SPEXTRACTOR_WINDOW_FILE overrides the band edges per window (a slab-mode probe); it cannot be combined with trace:band_edges=acquisition.");
       if (!(tofAxis().n_bins > 1)) writeLogInfo_("[tof] no run-level axis bounds from the tdf (" + tofAxis().bounds_why + "); the acquisition edge set is not on record for this run");
-      for (const auto& w : window_list) wbands[w.first] = {0xFFFFFFFFu, 0};
+      if (tile_source && !band_edges_acq)
+        throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
+              "trace:band_edges=slab needs the whole window resident; the .d streaming source reads it per tile. Use trace:band_edges=acquisition, or SPEXTRACTOR_TILE_RESIDENT=1 for the resident source.");
+      for (const WinKey& k : fkeys) wbands[k] = {0xFFFFFFFFu, 0};
       #pragma omp parallel for schedule(dynamic, 1)
-      for (long i = 0; i < (long)window_list.size(); ++i)
+      for (long i = 0; i < (long)fkeys.size(); ++i)
       {
-        const WinKey& k = window_list[(size_t)i].first;
-        PeakSlab& sl = *window_list[(size_t)i].second;
-        toTof(sl);
+        const WinKey& k = fkeys[(size_t)i];
         TofIdx tlo = 0xFFFFFFFFu, thi = 0;
-        for (TofIdx t : sl.tof) { tlo = std::min(tlo, t); thi = std::max(thi, t); }
+        const auto rs = ms2_by_window.find(k);   // a resident slab: converted here, once, in place
+        if (rs != ms2_by_window.end())
+        {
+          PeakSlab& sl = rs->second;
+          toTof(sl);
+          for (TofIdx t : sl.tof) { tlo = std::min(tlo, t); thi = std::max(thi, t); }
+        }
         // [3a] the run-level alternative: tlo 0, thi the larger of the digitizer's last bin
         // (DigitizerNumSamples - 1: no bin index can exceed it) and the acquisition's upper m/z
         // through the calibration at every frame of the frozen table; logged in both modes so
@@ -4337,13 +4370,13 @@ protected:
     struct Carry { vector<Trace> rec; vector<float> inten; };
     map<WinKey, Carry> carry_in, carry_out;
     map<WinKey, vector<uint8_t>> visited;
-    for (const auto& w : window_list)
+    for (const WinKey& k : fkeys)
     {
-      carry_out[w.first];
-      const double lo = w.first[0] / 100.0, hi = w.first[1] / 100.0;
+      carry_out[k];
+      const double lo = k[0] / 100.0, hi = k[1] / 100.0;
       const size_t plo = lower_bound(prec_mz.begin(), prec_mz.end(), lo) - prec_mz.begin();
       const size_t phi = upper_bound(prec_mz.begin(), prec_mz.end(), hi) - prec_mz.begin();
-      visited[w.first].assign(phi > plo ? phi - plo : 0, 0);
+      visited[k].assign(phi > plo ? phi - plo : 0, 0);
     }
     // [tile] The output: settings and stamps are fixed before the first tile, the mzML writer is
     // opened once and fed a sorted block per tile (with one tile the count is exact and the bytes
@@ -4411,7 +4444,8 @@ protected:
     if (out_type == FileTypes::MZML) { writer.reset(new TileWriter(out_part)); writer->setExperimentalSettings(out_exp); }
     vector<MSSpectrum> all_out;   // the bulk (mzPeak) path only
     Size n_out = 0;
-    writeLogInfo_("Processing " + String(window_list.size()) + " isolation windows in " + String(tiles.size()) + " tile(s) (OpenMP over windows, <="
+    out_exp.setMetaValue("spx:tile_source", tile_source ? "stream" : "resident");
+    writeLogInfo_("Processing " + String(n_win) + " isolation windows in " + String(tiles.size()) + " tile(s) from the " + (tile_source ? "streaming" : "resident") + " source (OpenMP over windows, <="
                   + String(n_conc) + " concurrent, admission bounded by " + String((int)(mem_frac * 100))
                   + "% of free RAM)..." + rss_() + mem_());
 
@@ -4445,7 +4479,45 @@ protected:
     // whole run: this arm is the exactness gate, not the memory configuration)
     map<WinKey, PeakSlab> tile_slabs;
     vector<pair<WinKey, PeakSlab*>> wl;
-    if (tiles.size() == 1) wl = window_list;
+    if (tile_source)
+    {
+      // [3b] read the tile: a fresh consumer over the loader's RT range, lockstep-padded against
+      // the frozen tables restricted to the tile, so a window's slab is exactly the table's frames
+      // in [lo, hi); a window with none gets an empty slab (the body's empty-slab branch)
+      Phase _ph("LOAD(tile)");
+      const double _tr0 = phase_clock_();
+      PeakMap ms1_none;
+      PickCompactConsumer tc(spicker, tile_slabs, ms1_none, cstat, winKey);
+      tc.tablefn = [&]() {
+        PickCompactConsumer::FrameTables t;
+        for (const auto& kv : frozen)
+        {
+          PickCompactConsumer::FrameTab& tab = t[kv.first];
+          for (size_t f = 0; f < kv.second.frames(); ++f)
+            if (kv.second.frame_rt[f] >= tile.lo && kv.second.frame_rt[f] < tile.hi) { tab.rt.push_back(kv.second.frame_rt[f]); tab.id.push_back(kv.second.frame_id[f]); }
+        }
+        return t; };
+      BrukerTimsFile::Config c2 = cfg;
+      c2.load_ms1 = false; c2.dia_ms2_rt_lo = tile.lo; c2.dia_ms2_rt_hi = tile.hi;
+      BrukerTimsFile().loadDIAStreaming(in, tc, c2);   // a failure here is fatal: no fallback onto a half-read tile
+      tc.finish();
+      size_t n_del = 0, n_pad = 0, n_absent = 0, n_peaks = 0;
+      for (const auto& kv : tc.tables())
+      {
+        auto w = tile_slabs.find(kv.first);
+        if (w == tile_slabs.end()) { ++n_absent; tile_slabs[kv.first]; continue; }   // no frame in this tile: an empty slab
+        if (w->second.rt != kv.second.rt || w->second.frame_id != kv.second.id)
+          throw FrameTableError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[3b] a tile's slab is not the frozen table's frames for the tile", String(kv.first[0] / 100.0) + "-" + String(kv.first[1] / 100.0));
+        n_del += kv.second.delivered; n_pad += kv.second.padded; n_peaks += w->second.peaks();
+      }
+      for (auto& kv : tile_slabs) indexRt(kv.second);
+      for (auto& kv : tile_slabs) wl.emplace_back(kv.first, &kv.second);
+      std::stable_sort(wl.begin(), wl.end(), [](const auto& a, const auto& b) { return a.second->bytes() > b.second->bytes(); });
+      writeLogInfo_("[tile] " + String(tk + 1) + "/" + String(tiles.size()) + " [" + String(tile.lo) + "," + String(tile.hi) + ") read: "
+                    + String(wl.size()) + " windows, frames delivered " + String(n_del) + " padded " + String(n_pad) + " absent-windows " + String(n_absent)
+                    + ", " + String(n_peaks) + " peaks, " + String(phase_clock_() - _tr0, 1) + " s" + rss_() + mem_());
+    }
+    else if (tiles.size() == 1) wl = window_list;
     else
     {
       size_t tile_peaks = 0;
@@ -5022,12 +5094,12 @@ protected:
       // [tile] coverage: every finite precursor of every window was owned by exactly one tile
       // (the per-tile check catches a second owner; this catches none)
       size_t n_cov = 0;
-      for (const auto& w : window_list)
+      for (const WinKey& k : fkeys)
       {
-        const double lo = w.first[0] / 100.0, hi = w.first[1] / 100.0;
+        const double lo = k[0] / 100.0, hi = k[1] / 100.0;
         const size_t plo = lower_bound(prec_mz.begin(), prec_mz.end(), lo) - prec_mz.begin();
         const size_t phi = upper_bound(prec_mz.begin(), prec_mz.end(), hi) - prec_mz.begin();
-        const vector<uint8_t>& vis = visited.at(w.first);
+        const vector<uint8_t>& vis = visited.at(k);
         for (size_t pi = plo; pi < phi; ++pi)
         {
           if (!std::isfinite(precursors[pi].rt) || !std::isfinite(precursors[pi].im)) continue;
@@ -5071,7 +5143,7 @@ protected:
     }
     carry_in = std::move(carry_out);
     carry_out.clear();
-    for (const auto& w : window_list) carry_out[w.first];
+    for (const WinKey& k : fkeys) carry_out[k];
     }   // tiles
 
     { auto& st = phase_stats_()["WINDOW_LOOP"]; if (st.n++ == 0) phase_order_().push_back("WINDOW_LOOP");
```

## The review fixes applied afterwards, dbcfa9c
```diff
commit dbcfa9c52778863512f1db369b8ef9d54854772f
Author: Oliver <oliver.kohlbacher@uni-tuebingen.de>
Date:   Thu Sep 10 07:26:41 2026 +0200

    Tiled reader, review fixes (Codex): the streaming source is a .d only and is committed only by a successful pass 1 (an mzML fallback no longer calls the Bruker loader again); a window whose every slice is empty in a tile is padded from its table slice, not left frameless; auto banding is refused under the streaming source (the two sources count windows differently); spx:tile_source is stamped before the writer copies the settings; the whole-run compaction losses are reported after the last tile; slabDigest_ takes a seed so the per-(window, tile) digests chain, logged under SPEXTRACTOR_DET; band_edges=slab under the streaming source is refused before the load; LOAD_ONLY says it measures pass 1; the parallelism line counts the run's windows

diff --git a/src/spextractor.cpp b/src/spextractor.cpp
index 5247905..bf88878 100644
--- a/src/spextractor.cpp
+++ b/src/spextractor.cpp
@@ -926,9 +926,9 @@ namespace
   /// every (tof, intensity bits, imq) tuple in frame order. Unlike detDigest_ it is NOT sorted, so a
   /// reordered equal-intensity peak or a tuple swapped between frames changes it -- which is what a
   /// representation change of the store must not do. [det]
-  static uint64_t slabDigest_(const PeakSlab& sl)
+  static uint64_t slabDigest_(const PeakSlab& sl, uint64_t seed = 1469598103934665603ULL)
   {
-    uint64_t h = 1469598103934665603ULL;
+    uint64_t h = seed;
     auto mix = [&](uint64_t v) { h ^= v; h *= 1099511628211ULL; };
     for (size_t f = 0; f < sl.frames(); ++f)
     {
@@ -3332,6 +3332,10 @@ protected:
     // load when no candidate tdf provides them (an mzPeak archive is checked after its embedded
     // tdf is recovered, below). Milliseconds against minutes of loading.
     const bool band_edges_acq = (getStringOption_("trace:band_edges") == "acquisition");
+    if (!band_edges_acq && getStringOption_("trace:detector") == "integer" && getStringOption_("perf:stream_load") == "true"
+        && FileHandler::getTypeByFileName(in) == FileTypes::BRUKER_TDF && !std::getenv("SPEXTRACTOR_TILE_RESIDENT"))
+      throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
+            "trace:band_edges=slab needs the whole window resident; the .d streaming source reads it per tile. Use trace:band_edges=acquisition, or SPEXTRACTOR_TILE_RESIDENT=1 for the resident source.");
     if (band_edges_acq && std::getenv("SPEXTRACTOR_WINDOW_FILE"))   // an option x env conflict: refuse in milliseconds
       throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
             "SPEXTRACTOR_WINDOW_FILE overrides the band edges per window (a slab-mode probe); it cannot be combined with trace:band_edges=acquisition.");
@@ -3390,7 +3394,12 @@ protected:
 #else
       const bool in_mzpeak = false;
 #endif
-      tile_source = !in_mzpeak && std::getenv("SPEXTRACTOR_TILE_RESIDENT") == nullptr;
+      // [3b] the streaming source needs the Bruker loader: a .d only, never an mzML or an mzPeak
+      // archive (the resident path reads those whole). SPEXTRACTOR_TILE_RESIDENT=1 forces the
+      // resident source for a same-build A/B; any other value leaves the default.
+      { const char* r = std::getenv("SPEXTRACTOR_TILE_RESIDENT");
+        const bool force_resident = r && String(r) != "0" && String(r) != "";
+        tile_source = !in_mzpeak && !force_resident && FileHandler::getTypeByFileName(in) == FileTypes::BRUKER_TDF; }
       if (tile_source)
       {
         // pass 1: MS1 only; lo > hi selects no MS2 frame, the loader exports the table anyway
@@ -3471,7 +3480,9 @@ protected:
         phase_stats_()["LOAD(stream)"].rss_end_mb = rss_mb_();
         if (phase_stats_()["LOAD(stream)"].n++ == 0) phase_order_().push_back("LOAD(stream)");
         writeLogInfo_("[perf-load] pick(flush) wall=" + String(flush_wall_(), 1) + " s inside LOAD(stream)");
-        if (std::getenv("SPEXTRACTOR_LOAD_ONLY")) { report_phases_(phase_clock_()); return EXECUTION_OK; }   // [perf-load] decode/hand-off/pick split only
+        if (std::getenv("SPEXTRACTOR_LOAD_ONLY"))
+        { if (tile_source) writeLogInfo_("[perf-load] SPEXTRACTOR_LOAD_ONLY under the .d streaming source measures PASS 1 (MS1) only; the MS2 frames are read per tile in pass 2.");
+          report_phases_(phase_clock_()); return EXECUTION_OK; }   // [perf-load] decode/hand-off/pick split only
         if (TileProbe::get().on)
           writeLogInfo_("[probe] MS2 RT range " + String(TileProbe::get().lo) + "-" + String(TileProbe::get().hi)
                         + " halo " + String(TileProbe::get().halo) + " s: dropped " + String(consumer.frames_probe_dropped)
@@ -3487,6 +3498,10 @@ protected:
         writeLogWarn_(String("[stream] streaming load failed (") + e.getName()
                       + "); falling back to loadExperiment. " + e.getMessage());
       }
+      // [3b] the source is COMMITTED only by a successful pass 1: a fallback to the resident load
+      // reads the whole run, so the tile loop must slice it rather than call the loader again
+      if (!streamed && tile_source)
+      { tile_source = false; writeLogWarn_("[3b] the streaming source did not read pass 1; the resident source takes over (the whole run is loaded)."); }
       // [frames] the invariant the frozen tables rest on, checked OUTSIDE the recoverable catch: a
       // delivered window's slab is its table (rt and id, frame for frame) after padding
       if (streamed && tile_source && consumer.tables().empty())
@@ -4183,7 +4198,7 @@ protected:
     if (n_bands > 1) omp_set_max_active_levels(2);
 #endif
     writeLogInfo_("Parallelism: " + String(n_win) + " windows x " + String(n_bands)
-                  + " m/z bands = " + String((int)window_list.size() * n_bands) + " trace units; "
+                  + " m/z bands = " + String((int)n_win * n_bands) + " trace units; "
                   + String(n_threads) + " worker threads over one task pool; up to "
                   + String(n_conc) + " windows in flight (memory-bounded)");
     // [dyn-mem] Thread count is the UPPER bound; free RAM is the real one. A static cap either
@@ -4288,6 +4303,9 @@ protected:
     if (cell_pitch > 0.0 && getIntOption_("perf:trace_bands") <= 0)
       throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
             "tile:rt_sec needs a fixed perf:trace_bands: the auto setting (0) ties the band count to the thread count, and each band has its own `visited`, so the output would depend on the threads.");
+    if (tile_source && integer_detector && getIntOption_("perf:trace_bands") <= 0)
+      throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
+            "the .d streaming source needs a fixed perf:trace_bands: the auto setting derives the band count from the WINDOW COUNT, and the streaming source counts every window of the acquisition while the resident source counts only the windows that delivered a frame -- the two would band differently (review 3b).");
     // [tile] The cells grouped into TILES. A tile owns the precursors whose MS1 frame time lies in
     // [lo - delta_rt, hi - delta_rt) -- the half-open ranges partition RT (lo = -inf for the first,
     // hi = +inf for the last) -- and traces its windows on the tile's frames only; a precursor's
@@ -4322,9 +4340,9 @@ protected:
         throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
               "SPEXTRACTOR_WINDOW_FILE overrides the band edges per window (a slab-mode probe); it cannot be combined with trace:band_edges=acquisition.");
       if (!(tofAxis().n_bins > 1)) writeLogInfo_("[tof] no run-level axis bounds from the tdf (" + tofAxis().bounds_why + "); the acquisition edge set is not on record for this run");
-      if (tile_source && !band_edges_acq)
+      if (tile_source && !band_edges_acq)   // unreachable: refused before the load
         throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
-              "trace:band_edges=slab needs the whole window resident; the .d streaming source reads it per tile. Use trace:band_edges=acquisition, or SPEXTRACTOR_TILE_RESIDENT=1 for the resident source.");
+              "trace:band_edges=slab needs the whole window resident; the .d streaming source reads it per tile.");
       for (const WinKey& k : fkeys) wbands[k] = {0xFFFFFFFFu, 0};
       #pragma omp parallel for schedule(dynamic, 1)
       for (long i = 0; i < (long)fkeys.size(); ++i)
@@ -4369,6 +4387,7 @@ protected:
     // the once-only ownership check per precursor (a window's m/z range is tile-independent)
     struct Carry { vector<Trace> rec; vector<float> inten; };
     map<WinKey, Carry> carry_in, carry_out;
+    map<WinKey, uint64_t> slab_chain;   // [det] the per-window slab digest, chained across tiles
     map<WinKey, vector<uint8_t>> visited;
     for (const WinKey& k : fkeys)
     {
@@ -4401,6 +4420,7 @@ protected:
     out_exp.setMetaValue("spx:tile_rt_sec", cell_pitch);
     out_exp.setMetaValue("spx:tile_cells_per_tile", getIntOption_("tile:cells_per_tile"));
     out_exp.setMetaValue("spx:band_edges", integer_detector ? getStringOption_("trace:band_edges") : String("none"));   // what was applied
+    out_exp.setMetaValue("spx:tile_source", tile_source ? "stream" : "resident");
     out_exp.setMetaValue("spx:tiles", (int)tiles.size());
     out_exp.setMetaValue("spx:frame_table", frame_table_src);   // the frozen tables' source (loader | mzpeak | slab)
     out_exp.setMetaValue("spx:pearson_G", "frames");
@@ -4444,7 +4464,6 @@ protected:
     if (out_type == FileTypes::MZML) { writer.reset(new TileWriter(out_part)); writer->setExperimentalSettings(out_exp); }
     vector<MSSpectrum> all_out;   // the bulk (mzPeak) path only
     Size n_out = 0;
-    out_exp.setMetaValue("spx:tile_source", tile_source ? "stream" : "resident");
     writeLogInfo_("Processing " + String(n_win) + " isolation windows in " + String(tiles.size()) + " tile(s) from the " + (tile_source ? "streaming" : "resident") + " source (OpenMP over windows, <="
                   + String(n_conc) + " concurrent, admission bounded by " + String((int)(mem_frac * 100))
                   + "% of free RAM)..." + rss_() + mem_());
@@ -4504,13 +4523,26 @@ protected:
       size_t n_del = 0, n_pad = 0, n_absent = 0, n_peaks = 0;
       for (const auto& kv : tc.tables())
       {
-        auto w = tile_slabs.find(kv.first);
-        if (w == tile_slabs.end()) { ++n_absent; tile_slabs[kv.first]; continue; }   // no frame in this tile: an empty slab
-        if (w->second.rt != kv.second.rt || w->second.frame_id != kv.second.id)
+        PeakSlab& sl = tile_slabs[kv.first];   // a window that delivered nothing still owns its table's frames
+        if (sl.frames() == 0 && !kv.second.rt.empty())
+        {
+          // every frame of the slice was skipped (an empty ion-mobility slice in each): pad them
+          // all, exactly as the resident path does, so the frame sequence is the table's
+          ++n_absent;
+          for (size_t f = 0; f < kv.second.rt.size(); ++f) sl.append(kv.second.rt[f], kv.second.id[f], nullptr, nullptr, nullptr, 0, kv.second.rt.size());
+          n_pad += kv.second.rt.size();
+        }
+        else { n_del += kv.second.delivered; n_pad += kv.second.padded; }
+        if (sl.rt != kv.second.rt || sl.frame_id != kv.second.id)
           throw FrameTableError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[3b] a tile's slab is not the frozen table's frames for the tile", String(kv.first[0] / 100.0) + "-" + String(kv.first[1] / 100.0));
-        n_del += kv.second.delivered; n_pad += kv.second.padded; n_peaks += w->second.peaks();
+        n_peaks += sl.peaks();
       }
       for (auto& kv : tile_slabs) indexRt(kv.second);
+      if (detOn_())   // [det] the reader's exactness: per (window, tile), chained over tiles
+        for (auto& kv : tile_slabs)
+        { uint64_t& h = slab_chain[kv.first]; h = slabDigest_(kv.second, h);
+          writeLogInfo_("[det] window " + String(kv.first[0] / 100.0) + "-" + String(kv.first[1] / 100.0) + " tile " + String(tk + 1)
+                        + " slab n=" + String(kv.second.peaks()) + " digest=" + String(slabDigest_(kv.second)) + " chain=" + String(h)); }
       for (auto& kv : tile_slabs) wl.emplace_back(kv.first, &kv.second);
       std::stable_sort(wl.begin(), wl.end(), [](const auto& a, const auto& b) { return a.second->bytes() > b.second->bytes(); });
       writeLogInfo_("[tile] " + String(tk + 1) + "/" + String(tiles.size()) + " [" + String(tile.lo) + "," + String(tile.hi) + ") read: "
@@ -5110,6 +5142,17 @@ protected:
         }
       }
       writeLogInfo_("[tile] coverage: " + String(n_cov) + " precursor-window pairs owned exactly once over " + String(tiles.size()) + " tile(s)");
+      if (tile_source)
+      {
+        // the tile reads share `cstat` with pass 1; the pre-pass-2 report could not see them
+        const size_t lost2 = cstat.no_im_array + cstat.size_mismatch + cstat.bad_mz + cstat.bad_im;
+        if (lost2) writeLogWarn_("[compact] DROPPED " + String(lost2) + " peaks over the whole run (pass 1 + every tile): no_im_array="
+                                 + String(cstat.no_im_array) + " size_mismatch=" + String(cstat.size_mismatch) + " bad_mz=" + String(cstat.bad_mz)
+                                 + " bad_im=" + String(cstat.bad_im) + " (kept " + String(cstat.kept) + ")");
+        else writeLogInfo_("[compact] no peak dropped over the whole run (kept " + String(cstat.kept) + ")");
+        if (detOn_()) for (const auto& kv : slab_chain)
+          writeLogInfo_("[det] window " + String(kv.first[0] / 100.0) + "-" + String(kv.first[1] / 100.0) + " slab chain=" + String(kv.second));
+      }
       // MEMORY: every MS1 structure is dead once the last tile's window loop has joined -- scoring
       // was its only reader (assembleOne_ -> scoreCandidates_ dereferences ms1_traces[pc.trace_idx]
       // and its span). Released BEFORE this tile's output is assembled and written. [mem]
```

## The gate result (from docs/BASELINE.md)
```
### Cell grid, step 3b: the .d streaming source, gated (2026-09-10)

Commits 933bba5 (the two-pass source) and dbcfa9c (the review fixes; docs/reviews/2026-09-10-tiled-reader/).
Pass 1 reads MS1 only and the loader exports the whole DIA frame table anyway; pass 2 calls the
patched loader once per tile over `Config::dia_ms2_rt_lo/hi`, into a fresh consumer lockstep-padded
against the tile's slice of the frozen tables. `SPEXTRACTOR_TILE_RESIDENT=1` keeps the resident
source for a same-build control.

**Gate (ibminode05, 54a7721, chain `step3b`, 07:40-09:23): 14 arms, every one SPECTRUM DATA
IDENTICAL to its pin, none differing.** G0 one tile on D at 600 / 300 / -1 `trace` and on TNBC at
600; G1 D at 300 as 2, 3 and 6 tiles at 8 and 100 threads; the resident control on the same build;
TNBC at 600 as 13 tiles. Every arm reported its frames: 32,210 window frames delivered on D and
134,312 on TNBC, 0 padded, 0 absent, and `[tile] coverage` accounted every precursor-window pair
exactly once (710,356 on D at one tile; 4,206,205 on TNBC over 13 tiles).

**What it costs and what it saves:**

| | resident | streaming, 1 tile | streaming, tiled |
|---|---:|---:|---:|
| D at 600, wall / peak | 2:34 / 47.2 GB | 2:27 / 41.1 GB | 2:57 / 31.8 GB (3 tiles) |
| **TNBC 009 at 600, wall / peak** | 13:12 / **124.1 GB** | 13:49 / **109.9 GB** | 11:33 / **70.9 GB** (13 tiles) |

On the two-hour file the streaming source alone takes 14 GB off the peak (the MS1 map and the MS2
slabs no longer coexist) and tiling takes another 39 GB: **124.1 -> 70.9 GB, -43%, at -12% wall**.
The remaining 70.9 GB is the MS1 pass, which pass 2 never touches.

**Every failure the chain reported was in its own instrumentation, not the tool:** eleven arms
failed a stamp assertion whose grep did not allow for OpenMS's `type="xsd:string"` attribute
between `name` and `value`; the chained slab digest was seeded from a zero-initialised map entry
instead of the FNV offset basis it must share with the whole-window digest; and the e2e suite
could not run at all (the synthetic tdf fixture predated the band-edge default's metadata
requirement, and an early refusal fired on mzML inputs that have no tdf and are supposed to fall
back quietly). All three are fixed (2b1f6e3, 8e2f1c0, 906e758) and re-checked by the `verify`
chain on the rebuilt binary. **A gate whose failures are all in the gate is not a passing gate:
it is a gate that has to be re-run, which is what the verify chain is for.**

**Re-run and CLOSED (chain `verify`, ibminode05, f07da66, 09:24-09:36): `VERIFY_RESULT PASS`.**
All three settle:

- the stamps read `spx:tile_source = stream`, `band_edges = acquisition`, `frame_table = loader`,
  `tiles = 3`, `tile_rt_sec = 600.0` -- the grep, not the tool, had been wrong (it did not allow
  for OpenMS's `type="xsd:string"` between `name` and `value`, the second time that has cost a
  gate a false failure);
- the chained per-tile slab digests equal the resident whole-window digests over all 24 windows:
  **the six tiled reads deliver exactly the peaks one whole-window read delivers, frame for
  frame**, and the two files are SPECTRUM DATA IDENTICAL;
- e2e **18/18**.

The 3-tile streaming arm on the rebuilt binary reproduces the pin at 3:43 and **32.1 GB**, with
frames delivered 10,416 / 10,416 / 11,378, 0 padded and 0 absent in every tile.
```
