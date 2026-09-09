Review only -- do not modify any file. Repository: /Users/kohlbach/Claude/speXtractor, HEAD is d85c2b4
(clean tree). Scope: the changes of commit d85c2b4 -- `git show d85c2b4 -- src/spextractor.cpp
patches/openms-epd-lockfree.patch`. The pristine OpenMS source the patch applies to is checked out at
/Users/kohlbach/Claude/OpenMS-mzpeak-build (commit bd4b895; read
src/openms/source/FEATUREFINDER/ElutionPeakDetection.cpp and src/openms/source/KERNEL/MassTrace.cpp
there if you need the full call path; do not modify that tree either).

Domain: SpeXtractor turns diaPASEF (timsTOF DIA) raw data into pseudo-MS/MS spectra. Mass traces are
detected per isolation window over all retention-time frames (one frame per 1.626 s cycle, ~4,800
frames in a 2-h run), then split at chromatographic valleys by OpenMS ElutionPeakDetection (EPD),
then trimmed to <= 120 s around the apex. The tool hands EPD a MassTrace built from the trace's REAL
points only (frames where the detector found a peak), as `Peak2D(rt, intensity)` lists.

What was measured: processing the run in RT tiles (600-s cores + 123-s halo, everything else frozen:
band edges, Pearson support, MS1 side whole-run) changed 99.7% of the emitted spectra, uniformly in
RT -- spectra 600-900 s from the only tile boundary differed as often as spectra 30 s from it, on a
dataset whose longest post-split MS2 trace spans 345 s. Per spectrum, ~90% of fragments are identical
(same m/z, identical intensities), the rest are different fragment TRACES. So a window-global
quantity changes the SPLIT of traces everywhere.

Diagnosis: EPD computes `scan_time = mt.getAverageMS1CycleTime(); win_size = ceil(chrom_fwhm /
scan_time)` and uses win_size for the Savitzky-Golay smoother and `findLocalExtrema(mt, win_size/2)`.
MassTrace::getAverageMS1CycleTime is (last RT - first RT) / (n - 1) over the points it was given --
real points only here -- so a long trace with gaps (a background ion seen intermittently across the
run) has an inflated cycle time, a narrower window, and a sub-range of it (what a tile sees) gets a
different window than the whole, hence different valleys everywhere along it.

The change (d85c2b4): EPD gains an advanced param `scan_time` (0.0 = old behaviour, per trace); the
tool gains `trace:split_scan_time` = frame (default) | trace. 'frame' passes the median gap between
consecutive frame times of the MS level: for the MS1 path (and the MS2 OpenMS-detector path) from the
PeakMap's spectrum RTs, sorted, inside detectTraces_; for the MS2 integer path from the window store's
frame_rt (splitIntegerTraces gains a scan_time argument). New helper `frameSpacing()`.

Attack these, in order of what I am least sure of:
1. Is the diagnosis complete? Is there anything ELSE on the detect -> merge -> split -> trim -> score
   path that makes a trace's children depend on the trace's extent beyond its local neighbourhood
   (e.g. in EPD: findLocalExtrema's neighbourhood, the SG edge handling, chrom_peak_snr, the FWHM
   estimate; in the tool: trimToSpan, toTrace, apex selection)? Give file:line.
2. frameSpacing(): median of consecutive gaps. On the integer MS2 path frame_rt is the window's frame
   times (one per cycle where the window's spectrum was non-empty). On mzPeak input empty frames are
   skipped by the reader; on the synthetic e2e input (test/test_spextractor.py, synth() with
   gap_cycles) cycles are missing on purpose. Does the median give the acquisition spacing in each
   case, and can it be 0 or inflated? What happens with 1 frame (returns 0 -> EPD falls back to per
   trace)? Is sorting the MS1 map RTs correct if the map is not in RT order?
3. The patch: is the hunk correct against the pristine base (defaults_ registration, updateMembers_,
   header member default-initialised, the EPD ctor calls defaultsToParam_ after registration)? Does
   `trace:split_scan_time trace` reproduce the pre-change bytes exactly (scan_time 0.0 -> the old
   expression), including for traces where getAverageMS1CycleTime would be 0 or NaN?
4. Science: is a fixed window the right call? A gappy trace's per-trace window was NARROWER; the fixed
   window is wider and smooths more -- could it merge two real peaks that the old window separated
   (peaks ~7 s apart at chrom_fwhm 7 s)? The development gate is Sage peptides on dataset D (30 min);
   the release gate is both engines and a second acquisition. What concrete measurement would
   falsify the change?
5. Anything else concretely wrong in the diff (types, signatures, the default-argument ordering of
   detectTraces_, the option registration flags, the comments).

For each finding: severity (blocker / should-fix / note), file:line, a concrete failing input or
scenario, and whether it would bite on real data or is theoretical. If something is fine, say so in
one line. Do not restate the design.
