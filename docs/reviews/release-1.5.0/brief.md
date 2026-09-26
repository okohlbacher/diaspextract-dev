# Pre-release code review brief: DIAspeXtract 1.5.0 (the low-intensity fragment gate)

Review only -- do not modify, create or delete any file. Everything you need is inline below; do not run any shell
command. HEAD is 433931e on main; the last release is tag v1.4.1. The code under review is `git diff v1.4.1..main --
src tests` (section A, 546 lines) plus the defaults 1.5.0 will ship (section B: two commits from the release-candidate
branches, applied on top of main). DIAspeXtract is a TOPP tool (OpenMS, C++17, OpenMP) that turns diaPASEF DIA runs into
pseudo-MS/MS spectra: per precursor MS1 trace it gates candidate fragment traces by co-elution (1/K0 window, apex RT
window, overlap >= gate:min_correlation_points, zero-padded Pearson >= gate:min_correlation), ranks the survivors and
keeps assembly:max_fragments (500). Output determinism is a shipped guarantee: the semantic digest of the output must
not depend on the thread count or the tile grid, and every option at its default must leave the digest unchanged
from 1.4.1 (verified: with all new modes off the digest is identical, aea1ae05).

What the new code does, in the author's words (attack these claims too):
- gate:short_traces concentric: fragment traces too short to correlate pass a span test (centre of the fragment span
  inside the precursor span within gate:short_center_tol of the precursor half-width), scored c = min_corr * (1 - 0.5*d/(tol+1)).
- gate:colocation ranges: a fragment's apex must lie inside the precursor's detected RT span and the spans overlap by
  >= gate:colocation_overlap of the shorter span.
- gate:shrinkage fisher: the gate compares the posterior mean of the Fisher-z transformed correlation (prior mean
  gate:shrink_prior_r, sd gate:shrink_prior_sd in z units, n-3 effective precision) with gate:min_correlation instead
  of the raw r; correlations from gate:shrink_min_points overlapping frames. gate:shrinkage + logoverlap is refused.
- gate:fragment_delta_im: a gate-only 1/K0 window (-1 = gate:delta_im).
- gate:adaptive faint: the modes above, gate:faint_delta_rt (6 s) and gate:faint_corr_power (1) apply only to
  precursors with <= gate:faint_max_frames (4) window frames of signal; other precursors get the 1.4.1 gate. The
  fragment RT index is built with the larger window. gate:adaptive auto (off by default) switches the faint gate on
  per run when the fraction of precursors with <= faint_max_frames MS1 trace points is >= gate:auto_faint_fraction.
- assembly:cap_rank evidence: the max_fragments cap ranks by raw r (captured before shrinkage) x ln(1+I) x (1+overlap)
  instead of gate score x intensity; umpire = max(r,0)^2 x ln(1+I).
- [pspan] log line: histogram of precursor MS1 spans (window frames) and the faint count, from atomics.
- DIASPEXTRACT_GATE_DUMP / DIASPEXTRACT_GATE_TARGETS: a diagnostic per-fragment dump near target precursors.
Measured (harness, entrapment FDR): 1.5.0 defaults vs 1.4.1 on HeLa 10 ng +85 %/+130 % peptides (Sage/MSFragger),
K562 250 ng +1.4 %, six in-house liver runs +2.1 %/+0.7 %, FDR 0.9-1.25 % throughout.

Attack, with file:line (diff line numbers are fine) for every finding:
1. Correctness of the math: Fisher z with r = +-1 (2 identical points, or 1 point when shrink_min_points is 1), n-3 <= 0,
   the posterior formula, the concentric score range, overlap fractions with zero-length spans, ln(1+I) with I = 0,
   the evidence key's tie behaviour, integer/float conversions, NaN propagation into comparisons and sorts.
2. Determinism: any order dependence in the new code (parallel loops, atomics used for anything but counters, sort
   keys with ties that depend on thread scheduling, the auto rule's fraction computed from a parallel reduction),
   anything that makes the digest depend on the thread count or the tile grid under the 1.5.0 defaults.
3. Precedence and interaction bugs: adaptive faint with a mode explicitly set by the user, shrinkage with
   min_correlation_points, fragment_delta_im -1 sentinel, the max-window RT index used for non-faint precursors,
   corr_power switching per precursor, cap_rank with fewer than max_fragments survivors, the refusal paths.
4. Performance in the hot loop (the window loop is 83 % of runtime): per-fragment allocations, recomputed
   transcendentals, the second pass for the faint classification, the dump path when the env var is unset.
5. Help strings and defaults: each register*Option_ default equals the value the text claims; the 1.5.0 defaults in
   section B are consistent with the help texts (e.g. shrink_prior_r 0.6 while the text says "0 = shrink toward no co-elution").
6. Tests: what the new tests cover and what they miss (no test exercises the gate modes on synthetic traces?).

Rank by severity (would it change output, crash, or is it cosmetic). If something is fine, say so in one line.

## Section B: the 1.5.0 defaults (applied on top of main for the release)

```diff
commit 2bcdeaa99be3eb29dfa65e0e6c0ca5ae654b5881
Author: Oliver <oliver.kohlbacher@uni-tuebingen.de>
Date:   Fri Sep 25 16:03:09 2026 +0200

    RC2 (branch lowint-gate-rc2): the adaptive gate (N=4) as defaults
    
    gate:adaptive faint, faint_max_frames 4: precursors with signal in <= 4 window frames get shrinkage (r0 0.6, sd 0.3,
    from 1 frame), co-location 0.3, the concentric path, a 6 s window and corr_power 1; every other precursor keeps the
    plain gate (3 s, 3 frames, power 2). Cap ranking unchanged. K562 run 1330: +0.8 % Sage / +2.9 % MSFragger, FDR 1.01 %;
    HeLa 10 ng +85 % / +129 %, FDR 0.84 %. Version 1.5.0. For the in-house benchmark.
    
    Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>

diff --git a/CMakeLists.txt b/CMakeLists.txt
index a332197..0f4adb4 100644
--- a/CMakeLists.txt
+++ b/CMakeLists.txt
@@ -1,5 +1,5 @@
 cmake_minimum_required(VERSION 3.16)
-project(DIAspeXtract VERSION 1.4.1 LANGUAGES CXX)
+project(DIAspeXtract VERSION 1.5.0 LANGUAGES CXX)
 
 # DIAspeXtract is a STANDALONE application that links against an existing OpenMS
 # installation. It is deliberately not part of the OpenMS source tree: OpenMS is a
diff --git a/src/diaspextract.cpp b/src/diaspextract.cpp
index 5e2ec0b..1536b3c 100644
--- a/src/diaspextract.cpp
+++ b/src/diaspextract.cpp
@@ -62,7 +62,7 @@ static_assert(std::is_nothrow_move_constructible_v<OpenMS::MassTrace> && std::is
 // The release version. The standalone CMake build passes it from project(VERSION); the in-tree
 // OpenMS build does not, so the fallback here is the same number.
 #ifndef DIASPEXTRACT_VERSION
-#define DIASPEXTRACT_VERSION "1.4.1"
+#define DIASPEXTRACT_VERSION "1.5.0"
 #endif
 
 using namespace OpenMS;
@@ -2354,7 +2354,7 @@ protected:
     registerTOPPSubsection_("perf", "Concurrency / memory tradeoff");
     registerStringOption_("gate:coelution", "<mode>", "pearson", "Fragment-precursor co-elution statistic: 'pearson' over the full RT grid, or 'logoverlap' (AlphaDIA-style profile overlap in log space where the precursor has signal; falsified: docs/BASELINE.md 'What is already falsified'). The scales differ: retune gate:min_correlation when switching.", false);
     setValidStrings_("gate:coelution", {"pearson", "logoverlap"});
-    registerStringOption_("gate:short_traces", "<mode>", "off", "Fragment traces with fewer than gate:min_correlation_points points, or fewer overlapping frames: 'off' drops them; 'concentric' keeps one whose detected RT span lies inside the precursor's (one cycle of slack) and whose span centre is within max(1 cycle, gate:short_center_tol x the precursor half-span) of the precursor's. Faint ions are the tips of their elution peaks: their spans shrink with intensity but stay centred on the apex. Experimental.", false, true);
+    registerStringOption_("gate:short_traces", "<mode>", "concentric", "Fragment traces with fewer than gate:min_correlation_points points, or fewer overlapping frames: 'off' drops them; 'concentric' keeps one whose detected RT span lies inside the precursor's (one cycle of slack) and whose span centre is within max(1 cycle, gate:short_center_tol x the precursor half-span) of the precursor's. Faint ions are the tips of their elution peaks: their spans shrink with intensity but stay centred on the apex. Experimental.", false, true);
     setValidStrings_("gate:short_traces", {"off", "concentric"});
     registerDoubleOption_("gate:short_center_tol", "<frac>", 0.5, "gate:short_traces concentric: centre tolerance as a fraction of the precursor half-span (at least one cycle).", false, true);
     setMinFloat_("gate:short_center_tol", 0.0);
@@ -2363,7 +2363,7 @@ protected:
     registerDoubleOption_("gate:fragment_delta_im", "<1/K0>", -1.0, "Max |precursor - fragment| 1/K0 difference in the co-elution gate alone; negative = gate:delta_im, which also sets the tracing tolerance (widening that merges ions of different mobility). Experimental.", false, true);
     registerStringOption_("assembly:cap_rank", "<mode>", "corr_inten", "Which fragments survive assembly:max_fragments: 'corr_inten' ranks by gate score x intensity (the score is the shrunk or concentric one when those modes are on); 'umpire' by r^2 x ln(1+I) with r the raw co-elution correlation (DIA-Umpire's key); 'evidence' by max(r,0) x ln(1+I) x (1 + overlapping frames), so long, correlated support outranks an intense one-frame coincidence. Experimental.", false, true);
     setValidStrings_("assembly:cap_rank", {"corr_inten", "umpire", "evidence"});
-    registerStringOption_("gate:adaptive", "<mode>", "off", "'faint': apply gate:shrinkage, gate:colocation, gate:short_traces, gate:faint_delta_rt and gate:faint_corr_power only to faint precursors, those with signal in at most gate:faint_max_frames window frames (a faint ion is the short tip of its elution peak); every other precursor keeps the plain gate (gate:delta_rt, gate:min_correlation_points, assembly:corr_power). 'off': the modes apply to every precursor. Experimental.", false, true);
+    registerStringOption_("gate:adaptive", "<mode>", "faint", "'faint': apply gate:shrinkage, gate:colocation, gate:short_traces, gate:faint_delta_rt and gate:faint_corr_power only to faint precursors, those with signal in at most gate:faint_max_frames window frames (a faint ion is the short tip of its elution peak); every other precursor keeps the plain gate (gate:delta_rt, gate:min_correlation_points, assembly:corr_power). 'off': the modes apply to every precursor. Experimental.", false, true);
     setValidStrings_("gate:adaptive", {"off", "faint"});
     registerIntOption_("gate:faint_max_frames", "<n>", 4, "gate:adaptive faint: most window frames with precursor signal for a faint precursor.", false, true);
     setMinInt_("gate:faint_max_frames", 1);
@@ -2371,16 +2371,16 @@ protected:
     setMinFloat_("gate:faint_delta_rt", 0.0);
     registerDoubleOption_("gate:faint_corr_power", "<k>", 1.0, "gate:adaptive faint: assembly:corr_power for faint precursors.", false, true);
     setMinFloat_("gate:faint_corr_power", 0.0);
-    registerStringOption_("gate:colocation", "<mode>", "off", "'ranges': keep a fragment only if its apex lies inside the precursor's detected RT span and the precursor apex inside the fragment's (one cycle of slack), and the spans overlap by at least gate:colocation_overlap of the shorter one (DIA-Umpire's apex-in-range and RT-overlap tests). Experimental.", false, true);
+    registerStringOption_("gate:colocation", "<mode>", "ranges", "'ranges': keep a fragment only if its apex lies inside the precursor's detected RT span and the precursor apex inside the fragment's (one cycle of slack), and the spans overlap by at least gate:colocation_overlap of the shorter one (DIA-Umpire's apex-in-range and RT-overlap tests). Experimental.", false, true);
     setValidStrings_("gate:colocation", {"off", "ranges"});
     registerDoubleOption_("gate:colocation_overlap", "<frac>", 0.3, "gate:colocation ranges: least span overlap as a fraction of the shorter span.", false, true);
     setMinFloat_("gate:colocation_overlap", 0.0);
-    registerStringOption_("gate:shrinkage", "<mode>", "off", "'fisher': gate on the posterior mean of the co-elution score instead of a hard gate:min_correlation_points cut: z = atanh(r), r the gate:coelution pearson statistic (full grid by default), with the overlapping frames n as a heuristic effective sample size (variance 1/max(n-3,1)) and prior N(atanh(gate:shrink_prior_r), gate:shrink_prior_sd^2). Scores on few frames are pulled toward the prior, so a prior below gate:min_correlation demands more from short traces; a prior equal to it reduces the mode to a plain cut at gate:shrink_min_points. Not with gate:coelution logoverlap. Experimental.", false, true);
+    registerStringOption_("gate:shrinkage", "<mode>", "fisher", "'fisher': gate on the posterior mean of the co-elution score instead of a hard gate:min_correlation_points cut: z = atanh(r), r the gate:coelution pearson statistic (full grid by default), with the overlapping frames n as a heuristic effective sample size (variance 1/max(n-3,1)) and prior N(atanh(gate:shrink_prior_r), gate:shrink_prior_sd^2). Scores on few frames are pulled toward the prior, so a prior below gate:min_correlation demands more from short traces; a prior equal to it reduces the mode to a plain cut at gate:shrink_min_points. Not with gate:coelution logoverlap. Experimental.", false, true);
     setValidStrings_("gate:shrinkage", {"off", "fisher"});
-    registerDoubleOption_("gate:shrink_prior_r", "<r>", 0.0, "gate:shrinkage fisher: prior mean correlation (0 = shrink toward no co-elution).", false, true);
-    registerDoubleOption_("gate:shrink_prior_sd", "<sd>", 0.5, "gate:shrinkage fisher: prior standard deviation in Fisher-z units (smaller = stronger shrinkage).", false, true);
+    registerDoubleOption_("gate:shrink_prior_r", "<r>", 0.6, "gate:shrinkage fisher: prior mean correlation (0 = shrink toward no co-elution).", false, true);
+    registerDoubleOption_("gate:shrink_prior_sd", "<sd>", 0.3, "gate:shrinkage fisher: prior standard deviation in Fisher-z units (smaller = stronger shrinkage).", false, true);
     setMinFloat_("gate:shrink_prior_sd", 0.01);
-    registerIntOption_("gate:shrink_min_points", "<n>", 2, "gate:shrinkage fisher: fewest overlapping frames to compute a correlation.", false, true);
+    registerIntOption_("gate:shrink_min_points", "<n>", 1, "gate:shrinkage fisher: fewest overlapping frames to compute a correlation.", false, true);
     setMinInt_("gate:shrink_min_points", 1);
     registerFlag_("gate:variance_support", "Compute the Pearson co-elution score over the union support of the two profiles instead of the full RT grid (gate:coelution pearson only; the scale changes, retune gate:min_correlation). Falsified 2026-07-27, kept for reproducibility: docs/BASELINE.md 'What is already falsified'.");
     registerIntOption_("perf:ms1_trace_bands", "<n>", 48, "Split MS1 mass-trace detection into N m/z bands traced concurrently (the halo partition of perf:trace_bands). Not exact: the band count changes the spectrum list slightly. Default 48 since 2026-09-07, gated on datasets D and A: docs/BASELINE.md 'ms1_trace_bands=48 adopted'. 1 = off; 0 is read as 1.", false);

commit a4f4cdaa793b46052531c9d2b4f72adda256a859
Author: Oliver <oliver.kohlbacher@uni-tuebingen.de>
Date:   Fri Sep 25 18:42:46 2026 +0200

    RC3 rc3b (branch lowint-gate-rc3b): adaptive N=4 gate + assembly:cap_rank evidence as default
    
    The max_fragments cap ranks by raw correlation x ln(1+I) x (1+overlap). K562 1330: always-on gate +0.9 %/+5.8 % (evidence) vs -10.3 %/-1.1 % (old key); adaptive N=4 +3.4 %/+3.0 % vs +0.8 %/+2.9 %.
    
    Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>

diff --git a/src/diaspextract.cpp b/src/diaspextract.cpp
index 1536b3c..506e611 100644
--- a/src/diaspextract.cpp
+++ b/src/diaspextract.cpp
@@ -2361,7 +2361,7 @@ protected:
     registerIntOption_("gate:short_min_points", "<n>", 1, "gate:short_traces concentric: fewest points a short fragment trace needs.", false, true);
     setMinInt_("gate:short_min_points", 1);
     registerDoubleOption_("gate:fragment_delta_im", "<1/K0>", -1.0, "Max |precursor - fragment| 1/K0 difference in the co-elution gate alone; negative = gate:delta_im, which also sets the tracing tolerance (widening that merges ions of different mobility). Experimental.", false, true);
-    registerStringOption_("assembly:cap_rank", "<mode>", "corr_inten", "Which fragments survive assembly:max_fragments: 'corr_inten' ranks by gate score x intensity (the score is the shrunk or concentric one when those modes are on); 'umpire' by r^2 x ln(1+I) with r the raw co-elution correlation (DIA-Umpire's key); 'evidence' by max(r,0) x ln(1+I) x (1 + overlapping frames), so long, correlated support outranks an intense one-frame coincidence. Experimental.", false, true);
+    registerStringOption_("assembly:cap_rank", "<mode>", "evidence", "Which fragments survive assembly:max_fragments: 'corr_inten' ranks by gate score x intensity (the score is the shrunk or concentric one when those modes are on); 'umpire' by r^2 x ln(1+I) with r the raw co-elution correlation (DIA-Umpire's key); 'evidence' by max(r,0) x ln(1+I) x (1 + overlapping frames), so long, correlated support outranks an intense one-frame coincidence. Experimental.", false, true);
     setValidStrings_("assembly:cap_rank", {"corr_inten", "umpire", "evidence"});
     registerStringOption_("gate:adaptive", "<mode>", "faint", "'faint': apply gate:shrinkage, gate:colocation, gate:short_traces, gate:faint_delta_rt and gate:faint_corr_power only to faint precursors, those with signal in at most gate:faint_max_frames window frames (a faint ion is the short tip of its elution peak); every other precursor keeps the plain gate (gate:delta_rt, gate:min_correlation_points, assembly:corr_power). 'off': the modes apply to every precursor. Experimental.", false, true);
     setValidStrings_("gate:adaptive", {"off", "faint"});
```

## Section A: git diff v1.4.1..main -- src tests CMakeLists.txt

```diff
diff --git a/src/DnoiseMs1.h b/src/DnoiseMs1.h
index 0011f29..c36eb0f 100644
--- a/src/DnoiseMs1.h
+++ b/src/DnoiseMs1.h
@@ -356,18 +356,14 @@ inline bool opentimsCorrection(const std::string& text, double& corr)
 
 /// Why the raw counts of MS1 frame @p fid cannot be recovered through its correction @p corr, or empty when they can. At
 /// corr >= 1 (AccumulationTime <= 100 ms) raw counts below 2^24 do not collide (checked exhaustively at 19 values, 1 + 1 ulp
-/// among them); below 1 they do, from raw 3 at 125 ms and from raw 1191 at 100.042 ms. 1e6 is a plausibility bound.
+/// among them), so recovery is exact; below 1 they do (from raw 3 at 125 ms, from raw 1191 at 100.042 ms) and recoverPoint
+/// takes the candidate nearest v / corr -- an approximation, accepted (user decision 2026-09-24). 1e6 is a plausibility bound.
 inline std::string correctionRefusal(std::size_t fid, double corr)
 {
-  if (corr >= 1.0 && corr < 1e6) return std::string();
+  if (corr < 1e6) return std::string();
   std::ostringstream m;   // the classic locale, as for every number this header reads
   m.imbue(std::locale::classic());
-  m << "MS1 frame " << fid << ": ";
-  if (corr < 1.0)
-    m << "AccumulationTime " << 100.0 / corr << " ms exceeds 100 ms, so opentims' intensity correction 100/" << 100.0 / corr << " = "
-      << corr << " < 1 maps several raw counts to one intensity and the raw counts dnoise filters cannot be recovered";
-  else
-    m << "opentims' intensity correction 100 / AccumulationTime = " << corr << " is not invertible";
+  m << "MS1 frame " << fid << ": opentims' intensity correction 100 / AccumulationTime = " << corr << " is not invertible";
   return m.str();
 }
 
@@ -436,8 +432,8 @@ inline Refusal frameCheck(const std::vector<FrameRow>& frames, std::uint32_t fid
 }
 
 /// One point of a frame with factor @p b (Cal::mzToTof inverts the m/z model the loader calibrated with:
-/// TdfMzCalibration in the tool), correction @p corr (correctionRefusal empty, so the search visits at most five raw
-/// counts), scan table @p asc / @p falls (buildScanTable) and @p num_scans scans: the TOF bin, scan and raw count the
+/// TdfMzCalibration in the tool), correction @p corr (correctionRefusal empty; the search visits 1 / corr + 3 raw counts at
+/// most), scan table @p asc / @p falls (buildScanTable) and @p num_scans scans: the TOF bin, scan and raw count the
 /// loader turned into @p mz, @p im and @p v. Checked in that order; on Refusal::none @p tof, @p scan and @p raw hold the
 /// point. For a message: @p t is the fractional TOF, @p hits the raw counts whose correction is @p v (0 until the
 /// intensity is checked).
@@ -458,11 +454,16 @@ inline Refusal recoverPoint(const Cal& cal, double b, double mz, float im, float
   if (v >= 16777216.0f) return Refusal::intensity_range;   // a float32 holds every count below 2^24 exactly, and no more
   std::uint32_t found = 0;
   int n = 0;
+  double best = HUGE_VAL;
   if (v >= 0.0f && v == std::floor(v))
     for (double r = std::max(0.0, std::floor((v - 0.5) / corr) - 1.0), r_end = std::ceil((v + 0.5) / corr) + 1.0; r <= r_end; r += 1.0)
-      if ((std::uint32_t)(r * corr + 0.5) == (std::uint32_t)v) { found = (std::uint32_t)r; ++n; }   // opentims.cpp:225: double(raw) * correction + 0.5, into a uint32
+      if ((std::uint32_t)(r * corr + 0.5) == (std::uint32_t)v)   // opentims.cpp:225: double(raw) * correction + 0.5, into a uint32
+      {
+        ++n;
+        if (std::fabs(r - v / corr) < best) { best = std::fabs(r - v / corr); found = (std::uint32_t)r; }   // n > 1 only at corr < 1
+      }
   hits = n;
-  if (n != 1) return Refusal::intensity;
+  if (n == 0) return Refusal::intensity;
   tof = (std::uint32_t)bin; scan = (std::uint32_t)s; raw = found;
   return Refusal::none;
 }
diff --git a/src/diaspextract.cpp b/src/diaspextract.cpp
index 7c208f3..78f693a 100644
--- a/src/diaspextract.cpp
+++ b/src/diaspextract.cpp
@@ -129,6 +129,33 @@ namespace
     if (want && String(want) == site)
       throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, String("[task-err] injected failure in task ") + site, site);
   }
+  /// [gate-dump] Diagnostics, read-only: with DIASPEXTRACT_GATE_DUMP=<out.tsv> and DIASPEXTRACT_GATE_TARGETS=<tsv: id mz
+  /// rt_sec im z>, every precursor within 20 ppm (mono or +-1 isotope at the target's charge), 20 s and 0.05 1/K0 of a
+  /// target writes one PRECURSOR row (fragments passing the gate) and one row per fragment trace within 0.05 1/K0 and
+  /// 15 s, with the first gate it fails (pearson mode, default gate rules only: gate:short_traces, gate:colocation and
+  /// gate:shrinkage are not reflected in the fate). The spectra are unchanged; off unless both variables are set.
+  struct GateDump_
+  {
+    struct T { std::string id; double mz, rt, im; int z; };
+    std::vector<T> t;   ///< sorted by mz
+    std::ofstream out;
+    std::mutex mu;
+    bool on = false;
+    GateDump_()
+    {
+      const char* f = std::getenv("DIASPEXTRACT_GATE_DUMP");
+      const char* g = std::getenv("DIASPEXTRACT_GATE_TARGETS");
+      if (!f || !g) return;
+      std::ifstream in(g);
+      T x;
+      while (in >> x.id >> x.mz >> x.rt >> x.im >> x.z) t.push_back(x);
+      std::sort(t.begin(), t.end(), [](const T& a, const T& b) { return a.mz < b.mz; });
+      out.open(f);
+      out << "target\tiso_k\tpc_mz\tpc_z\tpc_rt\tpc_im\tpc_iso\tpc_guessed\tfrag_mz\tdim\tdrt\tnp\toverlap\tcorr\tinten\tfate\n";
+      on = !t.empty() && out.good();
+    }
+    static GateDump_& get() { static GateDump_ d; return d; }
+  };
   inline std::map<std::string, PhaseStat>& phase_stats_()
   { static std::map<std::string, PhaseStat> m; return m; }
   inline std::vector<std::string>& phase_order_()
@@ -188,7 +215,21 @@ namespace
   double mono_guard_ = 0.0;          ///< [mono-guard] averagine slack on leftward isotope steps (0=off)
   bool mono_select_ = false;         ///< [mono-select] pick the mono by averagine fit over the isotope run
   bool var_support_ = false;         ///< [Q1] Pearson variance over union support, not full grid G (0-pad fix)
+  bool short_conc_ = false;          ///< [short] gate:short_traces == "concentric": span test for traces too short for Pearson
+  double short_center_tol_ = 0.5;    ///< [short] gate:short_center_tol, fraction of the precursor half-span
+  int short_min_pts_ = 1;            ///< [short] gate:short_min_points
+  bool coloc_ = false;               ///< [coloc] gate:colocation == "ranges": each apex inside the other span, span overlap
+  double coloc_overlap_ = 0.3;       ///< [coloc] gate:colocation_overlap, fraction of the shorter span
+  bool shrink_ = false;              ///< [shrink] gate:shrinkage == "fisher": Fisher-z posterior mean instead of a hard point cut
+  double shrink_r0_ = 0.0, shrink_sd_ = 0.5;   ///< [shrink] prior N(atanh r0, sd^2) on the Fisher z of the true correlation
+  int shrink_min_pts_ = 2;           ///< [shrink] gate:shrink_min_points, overlapping frames needed to compute r at all
+  bool adaptive_ = false;            ///< [adaptive] gate:adaptive == "faint": the relaxed modes only for faint precursors
+  bool adaptive_auto_ = false;       ///< [adaptive] gate:adaptive == "auto": faint mode only when the run's faint fraction >= auto_faint_frac_
+  double auto_faint_frac_ = 0.45;    ///< [adaptive] gate:auto_faint_fraction
+  int faint_frames_ = 4;             ///< [adaptive] gate:faint_max_frames
+  double faint_drt_ = 6.0, faint_cp_ = 1.0;   ///< [adaptive] gate:faint_delta_rt, gate:faint_corr_power
   double corr_power_ = 0.0;          ///< [Q2] emitted fragment intensity *= corr^corr_power (0=off; engine-agnostic)
+  int cap_rank_ = 0;                 ///< [cap] assembly:cap_rank: 0 corr_inten (score x intensity), 1 umpire (r^2 ln I), 2 evidence (r ln I (1+overlap))
 
   /// glibc arena accounting at a milestone: what the allocator holds in arenas vs mmapped blocks
   /// and how much of it is free-but-retained. RSS alone cannot tell live data from retained pages.
@@ -253,6 +294,8 @@ namespace
   /// 1000-10000, >=10000; 100 and 300 are MS1 tracing's default noise and seed thresholds). Counting only.
   inline bool ms1HistOn_() { static const bool on = []{ const char* e = std::getenv("DIASPEXTRACT_MS1_HIST"); return e && *e && *e != '0'; }(); return on; }
   inline std::array<std::atomic<long long>, 5>& ms1Hist_() { static std::array<std::atomic<long long>, 5> h{}; return h; }
+  /// [pspan] precursors reaching assembly by MS1 span in window frames: 1, 2, 3, 4, 5-6, 7-10, 11-20, >20; [8] = faint (adaptive)
+  inline std::array<std::atomic<long long>, 9>& pspanHist_() { static std::array<std::atomic<long long>, 9> h{}; return h; }
   /// RAII in main_: one sampler for the run, joined before any return path leaves the function.
   struct LedRun
   {
@@ -1506,7 +1549,7 @@ namespace
       spx::dnoise::GateBuild g = spx::dnoise::buildMs1WindowGate(tdf.meta, tdf.windows, p);
       if (!g.error.empty()) return "the dnoise MS1 port cannot build its window gate from this file: " + g.error;
       gate = std::move(g.gate);
-      for (size_t id = 1; id < tdf.frames.size(); ++id)   // below 1 (AccumulationTime > 100 ms) raw counts share a corrected value
+      for (size_t id = 1; id < tdf.frames.size(); ++id)   // above 100 ms raw counts are approximate (recoverPoint), not refused
         if (tdf.frames[id].msms_type == 0)
           if (std::string r = spx::dnoise::recover::correctionRefusal(id, tdf.frames[id].corr); !r.empty()) return r;
       // one table per TimsCalibration row, over the most scans an MS1 frame using it has (tdf.ms1_max_scans): a row no MS1
@@ -1582,7 +1625,7 @@ namespace
           case Refusal::intensity_range:
             throw refuse("intensity " + String(v) + " in frame " + String(fid) + " is >= 2^24 = 16777216: the loader's float32 intensity no longer identifies one raw count");
           default:   // Refusal::intensity
-            throw refuse("intensity " + String(v) + " in frame " + String(fid) + " is not opentims' correction of exactly one raw count (" + String(hits) + " found)");
+            throw refuse("intensity " + String(v) + " in frame " + String(fid) + " is not opentims' correction of any raw count");
         }
       }
       const spx::dnoise::FrameCounts fc = spx::dnoise::denoiseMs1Frame(k.scan.data(), k.tof.data(), k.raw.data(), n, fr.num_scans, p, gate ? &*gate : nullptr, k.w, k.keep);
@@ -2315,6 +2358,37 @@ protected:
     registerTOPPSubsection_("perf", "Concurrency / memory tradeoff");
     registerStringOption_("gate:coelution", "<mode>", "pearson", "Fragment-precursor co-elution statistic: 'pearson' over the full RT grid, or 'logoverlap' (AlphaDIA-style profile overlap in log space where the precursor has signal; falsified: docs/BASELINE.md 'What is already falsified'). The scales differ: retune gate:min_correlation when switching.", false);
     setValidStrings_("gate:coelution", {"pearson", "logoverlap"});
+    registerStringOption_("gate:short_traces", "<mode>", "off", "Fragment traces with fewer than gate:min_correlation_points points, or fewer overlapping frames: 'off' drops them; 'concentric' keeps one whose detected RT span lies inside the precursor's (one cycle of slack) and whose span centre is within max(1 cycle, gate:short_center_tol x the precursor half-span) of the precursor's. Faint ions are the tips of their elution peaks: their spans shrink with intensity but stay centred on the apex. Experimental.", false, true);
+    setValidStrings_("gate:short_traces", {"off", "concentric"});
+    registerDoubleOption_("gate:short_center_tol", "<frac>", 0.5, "gate:short_traces concentric: centre tolerance as a fraction of the precursor half-span (at least one cycle).", false, true);
+    setMinFloat_("gate:short_center_tol", 0.0);
+    registerIntOption_("gate:short_min_points", "<n>", 1, "gate:short_traces concentric: fewest points a short fragment trace needs.", false, true);
+    setMinInt_("gate:short_min_points", 1);
+    registerDoubleOption_("gate:fragment_delta_im", "<1/K0>", -1.0, "Max |precursor - fragment| 1/K0 difference in the co-elution gate alone; negative = gate:delta_im, which also sets the tracing tolerance (widening that merges ions of different mobility). Experimental.", false, true);
+    registerStringOption_("assembly:cap_rank", "<mode>", "corr_inten", "Which fragments survive assembly:max_fragments: 'corr_inten' ranks by gate score x intensity (the score is the shrunk or concentric one when those modes are on); 'umpire' by r^2 x ln(1+I) with r the raw co-elution correlation (DIA-Umpire's key); 'evidence' by max(r,0) x ln(1+I) x (1 + overlapping frames), so long, correlated support outranks an intense one-frame coincidence. Experimental.", false, true);
+    setValidStrings_("assembly:cap_rank", {"corr_inten", "umpire", "evidence"});
+    registerStringOption_("gate:adaptive", "<mode>", "off", "'faint': apply gate:shrinkage, gate:colocation, gate:short_traces, gate:faint_delta_rt and gate:faint_corr_power only to faint precursors, those with signal in at most gate:faint_max_frames window frames (a faint ion is the short tip of its elution peak); every other precursor keeps the plain gate (gate:delta_rt, gate:min_correlation_points, assembly:corr_power). 'off': the modes apply to every precursor. Experimental.", false, true);
+    setValidStrings_("gate:adaptive", {"off", "faint", "auto"});
+    registerDoubleOption_("gate:auto_faint_fraction", "<frac>", 0.45, "gate:adaptive auto: the run gets the faint gate when at least this fraction of its precursors span at most gate:faint_max_frames MS1 points (a sparse run: HeLa 10-100 ng 0.57-0.69, K562 250 ng 0.30, dense tissue 0.21); otherwise the plain gate. Logged and stamped spx:gate_adaptive.", false, true);
+    setMinFloat_("gate:auto_faint_fraction", 0.0);
+    setMaxFloat_("gate:auto_faint_fraction", 1.0);
+    registerIntOption_("gate:faint_max_frames", "<n>", 4, "gate:adaptive faint: most window frames with precursor signal for a faint precursor.", false, true);
+    setMinInt_("gate:faint_max_frames", 1);
+    registerDoubleOption_("gate:faint_delta_rt", "<sec>", 6.0, "gate:adaptive faint: the apex RT window for faint precursors.", false, true);
+    setMinFloat_("gate:faint_delta_rt", 0.0);
+    registerDoubleOption_("gate:faint_corr_power", "<k>", 1.0, "gate:adaptive faint: assembly:corr_power for faint precursors.", false, true);
+    setMinFloat_("gate:faint_corr_power", 0.0);
+    registerStringOption_("gate:colocation", "<mode>", "off", "'ranges': keep a fragment only if its apex lies inside the precursor's detected RT span and the precursor apex inside the fragment's (one cycle of slack), and the spans overlap by at least gate:colocation_overlap of the shorter one (DIA-Umpire's apex-in-range and RT-overlap tests). Experimental.", false, true);
+    setValidStrings_("gate:colocation", {"off", "ranges"});
+    registerDoubleOption_("gate:colocation_overlap", "<frac>", 0.3, "gate:colocation ranges: least span overlap as a fraction of the shorter span.", false, true);
+    setMinFloat_("gate:colocation_overlap", 0.0);
+    registerStringOption_("gate:shrinkage", "<mode>", "off", "'fisher': gate on the posterior mean of the co-elution score instead of a hard gate:min_correlation_points cut: z = atanh(r), r the gate:coelution pearson statistic (full grid by default), with the overlapping frames n as a heuristic effective sample size (variance 1/max(n-3,1)) and prior N(atanh(gate:shrink_prior_r), gate:shrink_prior_sd^2). Scores on few frames are pulled toward the prior, so a prior below gate:min_correlation demands more from short traces; a prior equal to it reduces the mode to a plain cut at gate:shrink_min_points. Not with gate:coelution logoverlap. Experimental.", false, true);
+    setValidStrings_("gate:shrinkage", {"off", "fisher"});
+    registerDoubleOption_("gate:shrink_prior_r", "<r>", 0.0, "gate:shrinkage fisher: prior mean correlation (0 = shrink toward no co-elution).", false, true);
+    registerDoubleOption_("gate:shrink_prior_sd", "<sd>", 0.5, "gate:shrinkage fisher: prior standard deviation in Fisher-z units (smaller = stronger shrinkage).", false, true);
+    setMinFloat_("gate:shrink_prior_sd", 0.01);
+    registerIntOption_("gate:shrink_min_points", "<n>", 2, "gate:shrinkage fisher: fewest overlapping frames to compute a correlation.", false, true);
+    setMinInt_("gate:shrink_min_points", 1);
     registerFlag_("gate:variance_support", "Compute the Pearson co-elution score over the union support of the two profiles instead of the full RT grid (gate:coelution pearson only; the scale changes, retune gate:min_correlation). Falsified 2026-07-27, kept for reproducibility: docs/BASELINE.md 'What is already falsified'.");
     registerIntOption_("perf:ms1_trace_bands", "<n>", 48, "Split MS1 mass-trace detection into N m/z bands traced concurrently (the halo partition of perf:trace_bands). Not exact: the band count changes the spectrum list slightly. Default 48 since 2026-09-07, gated on datasets D and A: docs/BASELINE.md 'ms1_trace_bands=48 adopted'. 1 = off; 0 is read as 1.", false);
     registerStringOption_("perf:ms1_prune", "<true/false>", "true",
@@ -2353,9 +2427,9 @@ protected:
 
     registerTOPPSubsection_("dnoise", "MS1 denoising of the raw frames before peak picking (dnoise v0.1.0's MS1 path; Bruker .d only)");
     registerStringOption_("dnoise:ms1", "<true/false>", "true",
-                          "Denoise every MS1 frame on its raw points before picking: a bit-identical port of dnoise v0.1.0's default MS1 path "
+                          "Denoise every MS1 frame on its raw points before picking: a port of dnoise v0.1.0's default MS1 path, bit-identical up to AccumulationTime 100 ms "
                           "(Garrett, Diedrich & Yates III, bioRxiv 2026.08.27.747603; MIT, LICENSES/dnoise-MIT.txt). Bruker .d only: other inputs "
-                          "pass through, logged and stamped spx:dnoise_ms1. A run whose raw points do not recover exactly is refused, as is "
+                          "pass through, logged and stamped spx:dnoise_ms1. Above 100 ms several raw counts share one intensity and the nearest is taken. A run whose raw points do not recover is refused, as is "
                           "trace:native_ms1_neighbors > 0. CHANGES OUTPUT (dataset D -4.3% Sage peptides, TNBC 009 +1.5%) and lowers peak memory "
                           "13-21% at one cell per tile: CHANGELOG, 2026-09-10 'MS1 denoising is on by default'. false = the output before 2026-09-10.", false);
     setValidStrings_("dnoise:ms1", {"true", "false"});
@@ -3066,6 +3140,19 @@ protected:
       psum += v; psumsq += v * v;
       if (log_overlap_) plogsum += std::log1p(v);
     }
+    int p_lo = std::numeric_limits<int>::max(), p_hi = -1;              // [short] the precursor's span in window frames
+    int p_apex = -1;                                                    // [coloc] the precursor apex frame
+    for (int gi : touched)
+    {
+      p_lo = std::min(p_lo, gi); p_hi = std::max(p_hi, gi);
+      if (p_apex < 0 || pdense[gi] > pdense[p_apex]) p_apex = gi;
+    }
+    // [adaptive] with gate:adaptive faint, the relaxed modes apply only to faint precursors (short precursor traces)
+    const bool faint = adaptive_ && (int)touched.size() <= faint_frames_, all_p = !adaptive_ || faint;
+    { const size_t n = touched.size(); pspanHist_()[n <= 4 ? (n ? n - 1 : 0) : n <= 6 ? 4 : n <= 10 ? 5 : n <= 20 ? 6 : 7]++; if (faint) pspanHist_()[8]++; }
+    const bool g_shrink = shrink_ && all_p, g_coloc = coloc_ && all_p, g_conc = short_conc_ && all_p;
+    const double g_drt = faint ? faint_drt_ : delta_rt, g_cp = faint ? faint_cp_ : corr_power_;
+    const double p_ctr = 0.5 * (p_lo + p_hi), p_half = 0.5 * (p_hi - p_lo);
     double pmean = psum / G, pvar = psumsq - G * pmean * pmean;
     double pinv = pvar > 0 ? 1.0 / sqrt(pvar) : 0.0;
     if (pinv > 0.0)
@@ -3078,7 +3165,7 @@ protected:
         const int dq = (int)frag_rt.q[fi] - pq;
         if (dq < -2 || dq > 2) continue;                                // 2 B reject, see FragRt
         // [soa] the gate reads a parallel array; the trace record is touched only after it passes.
-        if (fabs(frag_rt[fi] - pc.rt) > delta_rt) continue;            // RT gate
+        if (fabs(frag_rt[fi] - pc.rt) > g_drt) continue;               // RT gate ([adaptive] faint window)
         if (fg.invnorm[fi] == 0.0) continue;                           // degenerate fragment
         const Trace& f = frag_traces[fi];
         if (fabs(f.mz - pc.mono_mz) < 0.01) continue;                  // exclude precursor peak [M-7]
@@ -3086,56 +3173,131 @@ protected:
         // [R2-late, 2026-09-02] overlap <= support, so a fragment with fewer support points than
         // min_corr_pts can never pass the overlap guard below: skip it before the dot product.
         // Output-identical by construction (the guard's continue is the only thing it would reach).
-        if (f.np() < (size_t)std::max(min_corr_pts, 0)) continue;
+        const bool short_np = f.np() < (size_t)std::max(min_corr_pts, 0);
+        if (short_np && !g_conc && !(g_shrink && (int)f.np() >= shrink_min_pts_)) continue;
+        int f_lo = -1, f_hi = -1, f_apex = -1;                         // [short]/[coloc] the fragment's detected span and apex
+        float f_max = 0.0f;
         // two sequential streams: the fragment's span in the arena and pdense over window frames
         for (size_t k = 0; k < f.span(); ++k)
         { const float fv = xv(wst, f, k); if (fv == 0.0f) continue;
+          if (f_lo < 0) f_lo = (int)(f.frame0 + k);
+          f_hi = (int)(f.frame0 + k);
+          if (fv > f_max) { f_max = fv; f_apex = (int)(f.frame0 + k); }
           const float pv = pdense[f.frame0 + k]; if (pv != 0.0f) { dot += (double)pv * fv; ++overlap; } }
-        if (overlap < min_corr_pts) continue;                          // overlap guard [H-4]
-        // [B0] Plain Pearson takes variance over the full grid G, so a sparse fragment is scored against ~G
-        // implicit zeros. gate:variance_support uses the union support instead; gate:coelution=logoverlap is
-        // the AlphaDIA-style log-space profile overlap, summed where the precursor has signal, in [0,1].
-        double c;
-        if (var_support_ && !log_overlap_)                             // [Q1] pearson-only, per the flag doc
+        if (g_coloc)                                                    // [coloc] DIA-Umpire-style co-location
         {
-          // [Q1] n = |precursor support U fragment support|; fsum/fsumsq over the fragment's real points.
-          double fsum = 0.0, fsumsq = 0.0;
-          for (size_t k = 0; k < f.span(); ++k)
-          { const double fv = xv(wst, f, k); if (fv > 0.0) { fsum += fv; fsumsq += fv * fv; } }
-          double n = (double)(touched.size() + f.np() - (size_t)overlap);
-          double pm = psum / n, fm = fsum / n;
-          double pv2 = psumsq - n * pm * pm, fv2 = fsumsq - n * fm * fm;
-          if (pv2 <= 0.0 || fv2 <= 0.0) continue;                      // degenerate on union support
-          c = (dot - n * pm * fm) / std::sqrt(pv2 * fv2);
+          if (f_lo < 0 || p_hi < 0) continue;
+          if (f_apex < p_lo - 1 || f_apex > p_hi + 1 || p_apex < f_lo - 1 || p_apex > f_hi + 1) continue;
+          const int inter = std::min(f_hi, p_hi) - std::max(f_lo, p_lo) + 1, shorter = std::min(f_hi - f_lo, p_hi - p_lo) + 1;
+          if (inter < coloc_overlap_ * shorter) continue;
         }
-        else if (log_overlap_)
+        double c, c_raw = 0.0;                                          // c_raw: the unshrunk score, for assembly:cap_rank
+        const bool no_corr = g_shrink ? overlap < shrink_min_pts_ : (short_np || overlap < min_corr_pts);   // [short]/[shrink] precedence
+        if (g_conc && no_corr)
         {
-          // Both log-profiles normalised to unit sum, then intersected: a shape statistic. Normalising by the
-          // precursor's log-sum alone bounded the score by the intensity ratio (-18.9% peptides at gate 0.5).
-          double fsum = 0.0;
-          for (size_t k = 0; k < f.span(); ++k)
-          { const double fv = xv(wst, f, k); if (fv > 0.0) fsum += std::log1p(fv); }
-          if (fsum <= 0.0 || plogsum <= 0.0) continue;
-          double inter = 0.0;
-          for (size_t k = 0; k < f.span(); ++k)
+          // [short] too few points for a correlation: faint ions are the tips of their elution peaks, so their
+          // detected spans shrink with intensity but stay centred on the apex. Keep a fragment whose span lies inside
+          // the precursor's (one cycle of slack) with its centre near the precursor's; the score ranks by centring.
+          if ((int)f.np() < short_min_pts_ || f_lo < 0 || p_hi < 0) continue;
+          if (f_lo < p_lo - 1 || f_hi > p_hi + 1) continue;
+          const double d = std::fabs(0.5 * (f_lo + f_hi) - p_ctr), tol = std::max(1.0, short_center_tol_ * p_half);
+          if (d > tol) continue;
+          c = min_corr * (1.0 - 0.5 * d / (tol + 1.0));                // at the gate: ranks and weighs as a borderline fragment
+          c_raw = c;
+        }
+        else
+        {
+          if (overlap < (g_shrink ? shrink_min_pts_ : min_corr_pts)) continue;   // overlap guard [H-4]; [shrink] its own floor
+          // [B0] Plain Pearson takes variance over the full grid G, so a sparse fragment is scored against ~G
+          // implicit zeros. gate:variance_support uses the union support instead; gate:coelution=logoverlap is
+          // the AlphaDIA-style log-space profile overlap, summed where the precursor has signal, in [0,1].
+          if (var_support_ && !log_overlap_)                             // [Q1] pearson-only, per the flag doc
           {
-            const double fv = xv(wst, f, k); if (fv <= 0.0) continue;
-            inter += std::min(std::log1p(fv) / fsum,
-                              std::log1p((double)pdense[f.frame0 + k]) / plogsum);
+            // [Q1] n = |precursor support U fragment support|; fsum/fsumsq over the fragment's real points.
+            double fsum = 0.0, fsumsq = 0.0;
+            for (size_t k = 0; k < f.span(); ++k)
+            { const double fv = xv(wst, f, k); if (fv > 0.0) { fsum += fv; fsumsq += fv * fv; } }
+            double n = (double)(touched.size() + f.np() - (size_t)overlap);
+            double pm = psum / n, fm = fsum / n;
+            double pv2 = psumsq - n * pm * pm, fv2 = fsumsq - n * fm * fm;
+            if (pv2 <= 0.0 || fv2 <= 0.0) continue;                      // degenerate on union support
+            c = (dot - n * pm * fm) / std::sqrt(pv2 * fv2);
           }
-          c = inter;
+          else if (log_overlap_)
+          {
+            // Both log-profiles normalised to unit sum, then intersected: a shape statistic. Normalising by the
+            // precursor's log-sum alone bounded the score by the intensity ratio (-18.9% peptides at gate 0.5).
+            double fsum = 0.0;
+            for (size_t k = 0; k < f.span(); ++k)
+            { const double fv = xv(wst, f, k); if (fv > 0.0) fsum += std::log1p(fv); }
+            if (fsum <= 0.0 || plogsum <= 0.0) continue;
+            double inter = 0.0;
+            for (size_t k = 0; k < f.span(); ++k)
+            {
+              const double fv = xv(wst, f, k); if (fv <= 0.0) continue;
+              inter += std::min(std::log1p(fv) / fsum,
+                                std::log1p((double)pdense[f.frame0 + k]) / plogsum);
+            }
+            c = inter;
+          }
+          else c = (dot - G * pmean * fg.mean[fi]) * pinv * fg.invnorm[fi]; // Pearson
+          c_raw = c;
+          if (g_shrink)                                                  // [shrink] Fisher-z posterior mean
+          {
+            const double z = std::atanh(std::max(-0.999, std::min(0.999, c))), s2 = 1.0 / std::max(overlap - 3, 1);
+            const double t2 = shrink_sd_ * shrink_sd_, mu = std::atanh(std::max(-0.999, std::min(0.999, shrink_r0_)));
+            c = std::tanh((z / s2 + mu / t2) / (1.0 / s2 + 1.0 / t2));
+          }
+          if (c < min_corr) continue;                                    // correlation gate
         }
-        else c = (dot - G * pmean * fg.mean[fi]) * pinv * fg.invnorm[fi]; // Pearson
-        if (c < min_corr) continue;                                    // correlation gate
         // [E5] The IM weight feeds both the cap key and the emitted intensity; corr^corr_power feeds only the emitted one.
         double inten = intensityOf(wst, f);
         const double dim = frag_im[fi] - pc.im;
         if (im_weight_sigma_ > 0.0) inten *= std::exp(-(dim * dim) / (2.0 * im_weight_sigma_ * im_weight_sigma_));
         double emit_inten = inten;
-        if (corr_power_ > 0.0 && c > 0.0) emit_inten *= std::pow(c, corr_power_);
+        if (g_cp > 0.0 && c > 0.0) emit_inten *= std::pow(c, g_cp);
         frags.emplace_back(exportMz_(f.tof, bOf(wst, f), f.mz), emit_inten);
-        frag_scores.push_back(c * inten);
+        frag_scores.push_back(cap_rank_ == 1 ? std::max(c_raw, 0.0) * std::max(c_raw, 0.0) * std::log1p(inten)
+                            : cap_rank_ == 2 ? std::max(c_raw, 0.0) * std::log1p(inten) * (1.0 + overlap)
+                            : c * inten);                              // [cap] the max_fragments ranking key
+      }
+    }
+    if (GateDump_& gd = GateDump_::get(); gd.on)                       // [gate-dump] read-only; before the reset
+    {
+      std::ostringstream rows;
+      rows.imbue(std::locale::classic());
+      auto it = std::lower_bound(gd.t.begin(), gd.t.end(), pc.mono_mz - 1.2, [](const GateDump_::T& a, double v) { return a.mz < v; });
+      for (; it != gd.t.end() && it->mz <= pc.mono_mz + 1.2; ++it)
+      {
+        if (std::fabs(it->rt - pc.rt) > 20.0 || std::fabs(it->im - pc.im) > 0.05 || it->z <= 0) continue;
+        int kk = 9;
+        for (int k = -1; k <= 1; ++k)
+          if (std::fabs(pc.mono_mz - (it->mz + k * 1.003355 / it->z)) <= it->mz * 20e-6) { kk = k; break; }
+        if (kk == 9) continue;
+        auto head = [&]() { rows << it->id << '\t' << kk << '\t' << pc.mono_mz << '\t' << pc.charge << '\t' << pc.rt << '\t' << pc.im
+                                 << '\t' << pc.n_isotopes << '\t' << (int)pc.guessed << '\t'; };
+        head(); rows << "-\t-\t-\t-\t-\t-\t" << frags.size() << (pinv > 0.0 ? "\tPRECURSOR\n" : "\tPRECURSOR_FLAT\n");
+        if (!(pinv > 0.0)) continue;
+        const size_t lo = lower_bound(frag_im.begin(), frag_im.end(), pc.im - 0.05) - frag_im.begin();
+        const size_t hi = upper_bound(frag_im.begin(), frag_im.end(), pc.im + 0.05) - frag_im.begin();
+        for (size_t fi = lo; fi < hi; ++fi)
+        {
+          const double drt = frag_rt[fi] - pc.rt, dim = frag_im[fi] - pc.im;
+          if (std::fabs(drt) > 15.0) continue;
+          const Trace& f = frag_traces[fi];
+          double dot = 0; int overlap = 0;
+          for (size_t k = 0; k < f.span(); ++k)
+          { const float fv = xv(wst, f, k); if (fv == 0.0f) continue;
+            const float pv = pdense[f.frame0 + k]; if (pv != 0.0f) { dot += (double)pv * fv; ++overlap; } }
+          const double c = fg.invnorm[fi] == 0.0 ? 0.0 : (dot - G * pmean * fg.mean[fi]) * pinv * fg.invnorm[fi];
+          const char* fate = std::fabs(dim) > delta_im ? "im" : std::fabs(drt) > delta_rt ? "rt" : fg.invnorm[fi] == 0.0 ? "degenerate"
+                           : std::fabs(f.mz - pc.mono_mz) < 0.01 ? "precursor_peak" : f.np() < (size_t)std::max(min_corr_pts, 0) ? "np"
+                           : overlap < min_corr_pts ? "overlap" : c < min_corr ? "corr" : "kept";
+          head(); rows << exportMz_(f.tof, bOf(wst, f), f.mz) << '\t' << dim << '\t' << drt << '\t' << f.np() << '\t' << overlap << '\t'
+                       << c << '\t' << intensityOf(wst, f) << '\t' << fate << '\n';
+        }
       }
+      if (rows.tellp() > 0) { std::lock_guard<std::mutex> lk(gd.mu); gd.out << rows.str(); gd.out.flush(); }
     }
     for (int gi : touched) pdense[gi] = 0.0f;                          // reset scratch
     if (frags.size() < min_frags) return;
@@ -3365,6 +3527,8 @@ protected:
     const String in = getStringOption_("in");
     const String out = getStringOption_("out");
     const double delta_im = getDoubleOption_("gate:delta_im");
+    // [frag-im] the gate's fragment-precursor 1/K0 window, apart from the tracing tolerance delta_im (negative = delta_im)
+    const double gate_dim = getDoubleOption_("gate:fragment_delta_im") >= 0.0 ? getDoubleOption_("gate:fragment_delta_im") : delta_im;
     const double delta_rt = getDoubleOption_("gate:delta_rt");
     if (getFlag_("diag:selftest_arena")) return selftestArena_();
     if (getFlag_("diag:selftest_twins")) return selftestTwins_();
@@ -3373,6 +3537,24 @@ protected:
     mono_guard_ = getDoubleOption_("charge:mono_averagine_guard");
     mono_select_ = getFlag_("charge:mono_averagine_select");
     var_support_ = getFlag_("gate:variance_support");
+    short_conc_ = (getStringOption_("gate:short_traces") == "concentric");
+    short_center_tol_ = getDoubleOption_("gate:short_center_tol");
+    short_min_pts_ = getIntOption_("gate:short_min_points");
+    coloc_ = (getStringOption_("gate:colocation") == "ranges");
+    coloc_overlap_ = getDoubleOption_("gate:colocation_overlap");
+    shrink_ = (getStringOption_("gate:shrinkage") == "fisher");
+    shrink_r0_ = getDoubleOption_("gate:shrink_prior_r");
+    shrink_sd_ = getDoubleOption_("gate:shrink_prior_sd");
+    shrink_min_pts_ = getIntOption_("gate:shrink_min_points");
+    adaptive_ = (getStringOption_("gate:adaptive") == "faint");
+    adaptive_auto_ = (getStringOption_("gate:adaptive") == "auto");
+    auto_faint_frac_ = getDoubleOption_("gate:auto_faint_fraction");
+    cap_rank_ = getStringOption_("assembly:cap_rank") == "umpire" ? 1 : getStringOption_("assembly:cap_rank") == "evidence" ? 2 : 0;
+    faint_frames_ = getIntOption_("gate:faint_max_frames");
+    faint_drt_ = getDoubleOption_("gate:faint_delta_rt");
+    faint_cp_ = getDoubleOption_("gate:faint_corr_power");
+    if (shrink_ && log_overlap_)
+      throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "gate:shrinkage fisher needs a correlation: it does not apply to gate:coelution logoverlap");
     corr_power_ = getDoubleOption_("assembly:corr_power");
     const double min_corr = getDoubleOption_("gate:min_correlation");
     const int min_corr_pts = getIntOption_("gate:min_correlation_points");
@@ -3965,6 +4147,15 @@ protected:
     double _t_inf = phase_clock_(), _c_inf = cpu_seconds_();   // [perf-instr]
     vector<Precursor_> precursors = inferPrecursors_(ms1_traces, ms1_store, max_charge, delta_rt, iso_im_tol,
                                                      mass_ppm, env_scoring);
+    if (adaptive_auto_)   // [adaptive] auto: decide the run's gate from its precursor span distribution (MS1 points)
+    {
+      size_t nf = 0;
+      for (const Precursor_& pc : precursors) if ((int)ms1_traces[pc.trace_idx].np() <= faint_frames_) ++nf;
+      const double frac = precursors.empty() ? 0.0 : (double)nf / (double)precursors.size();
+      adaptive_ = frac >= auto_faint_frac_;
+      writeLogInfo_("[adaptive] auto: " + String(nf) + " of " + String(precursors.size()) + " precursors span <= " + String(faint_frames_)
+                    + " MS1 points (" + String(frac) + ", threshold " + String(auto_faint_frac_) + "): faint gate " + (adaptive_ ? "ON" : "OFF"));
+    }
     if (detOn_())
     {
       vector<uint64_t> b;
@@ -4372,6 +4563,7 @@ protected:
     out_exp.setMetaValue("spx:pearson_G", "frames");
     out_exp.setMetaValue("spx:tile_boundaries", cell_boundaries.empty() ? String("none") : cell_boundaries);
     out_exp.setMetaValue("spx:corr_power", corr_power_);
+    out_exp.setMetaValue("spx:gate_adaptive", adaptive_auto_ ? String(adaptive_ ? "auto:on" : "auto:off") : String(adaptive_ ? "faint" : "off"));
     out_exp.setMetaValue("spx:im_weight_sigma", im_weight_sigma_);
     // [dnoise] what was applied: the port, "off", or skipped because the input is no .d
     out_exp.setMetaValue("spx:dnoise_ms1", dnoise.on ? String(String(spx::dnoise::kPortedFrom) + " MS1") : String(dnoise_req ? "skipped (input is not a Bruker .d)" : "off"));
@@ -4807,7 +4999,7 @@ protected:
         });
         vector<double> frag_im(frag_traces.size());
         for (size_t i = 0; i < frag_traces.size(); ++i) frag_im[i] = frag_traces[i].im;
-        FragRt frag_rt; frag_rt.build(frag_traces, wst, delta_rt);
+        FragRt frag_rt; frag_rt.build(frag_traces, wst, adaptive_ ? std::max(delta_rt, faint_drt_) : delta_rt);   // [adaptive] buckets cover the wider window
         w_sort = secs(std::chrono::steady_clock::now() - _tso);
 
         // Precompute the common correlation grid once per window; pdense is reused across the
@@ -4856,7 +5048,7 @@ protected:
                 const Precursor_& pc = precursors[pidx[(size_t)j]];
                 MSSpectrum ms2;
                 assembleOne_(pc, win_lo, win_hi, frag_traces, wst, frag_im, frag_rt, ms1_traces, ms1_store, fg,
-                             delta_im, delta_rt, min_corr, min_corr_pts, min_frags, max_frags, pdense, ms2);
+                             gate_dim, delta_rt, min_corr, min_corr_pts, min_frags, max_frags, pdense, ms2);
                 if (!ms2.empty())
                 { ledAdd_(LC_SPECTRA, (long long)(sizeof(MSSpectrum) + ms2.size() * 12)); pslot[(size_t)j] = std::move(ms2); }
               }
@@ -5030,6 +5222,12 @@ protected:
     writeLogInfo_("Wrote " + String(n_out) + " pseudo-MS2 spectra to " + out
                   + " (" + String(FileTypes::typeToName(out_type)) + ")");
     if (twin_im >= 0.0) writeLogInfo_("[twins] " + String(n_twins) + " spectra folded into a twin (assembly:twin_im_tolerance " + String(twin_im) + ")");
+    {   // [pspan] the precursor MS1-span histogram, for choosing gate:faint_max_frames per data set
+      auto& h = pspanHist_(); long long tot = 0; for (int i = 0; i < 8; ++i) tot += h[i].load();
+      writeLogInfo_("[pspan] precursors by MS1 span (window frames): 1:" + String(h[0].load()) + " 2:" + String(h[1].load()) + " 3:" + String(h[2].load())
+                    + " 4:" + String(h[3].load()) + " 5-6:" + String(h[4].load()) + " 7-10:" + String(h[5].load()) + " 11-20:" + String(h[6].load())
+                    + " >20:" + String(h[7].load()) + " total " + String(tot) + (adaptive_ ? " faint(<=" + String(faint_frames_) + "): " + String(h[8].load()) : String("")));
+    }
     report_phases_(phase_clock_());
     return EXECUTION_OK;
   }
diff --git a/tests/test_dnoise_ms1.cpp b/tests/test_dnoise_ms1.cpp
index 7d25f5f..ef49542 100644
--- a/tests/test_dnoise_ms1.cpp
+++ b/tests/test_dnoise_ms1.cpp
@@ -750,13 +750,14 @@ static void testRecover()
   }
   CHECK(rc::correctionRefusal(7, 0x1.001b896437031p+0).empty() && rc::correctionRefusal(7, 1.0).empty() &&
           rc::correctionRefusal(7, std::nextafter(1.0, 2.0)).empty(), "corr >= 1 is invertible");
-  const std::string r125 = rc::correctionRefusal(7, 100.0 / 125.0);
-  CHECK(r125.find("MS1 frame 7: AccumulationTime 125 ms exceeds 100 ms") == 0 && r125.find("= 0.8 < 1") != std::string::npos,
-        "AccumulationTime 125 ms: '%s'", r125.c_str());
-  CHECK(rc::opentimsCorrection("100.042", corr) && corr < 1.0 && !rc::correctionRefusal(1, corr).empty(), "AccumulationTime 100.042 ms is refused");
-  CHECK(!rc::correctionRefusal(7, 0.5).empty() && !rc::correctionRefusal(7, std::nextafter(1.0, 0.0)).empty() &&
-          !rc::correctionRefusal(7, 1e6).empty() && !rc::correctionRefusal(7, std::numeric_limits<double>::infinity()).empty(),
-        "corr 0.5, 1 - 1 ulp, 1e6 and inf are refused");
+  // above 100 ms raw counts are approximated (recoverPoint), not refused: only the plausibility bound refuses
+  CHECK(rc::correctionRefusal(7, 100.0 / 125.0).empty() && rc::correctionRefusal(7, 100.0 / 166.0).empty() &&
+          rc::correctionRefusal(7, 0.5).empty() && rc::correctionRefusal(7, std::nextafter(1.0, 0.0)).empty(),
+        "corr 0.8, 100/166, 0.5 and 1 - 1 ulp are accepted");
+  CHECK(rc::opentimsCorrection("100.042", corr) && corr < 1.0 && rc::correctionRefusal(1, corr).empty(), "AccumulationTime 100.042 ms is accepted");
+  const std::string r1e6 = rc::correctionRefusal(7, 1e6);
+  CHECK(r1e6.find("MS1 frame 7: opentims' intensity correction") == 0 && !rc::correctionRefusal(7, std::numeric_limits<double>::infinity()).empty(),
+        "corr 1e6 and inf are refused: '%s'", r1e6.c_str());
 
   for (const RecoverFile& f : {recoverD(), recoverTnbc()})
   {
@@ -870,8 +871,19 @@ static void testRecover()
   rc::opentimsCorrection("99.968", corr);
   CHECK(opentimsCorrect(1562, corr) == 1562 && point(1562.0f, corr) == R::none && raw == 1562 && hits == 1 && point(1563.0f, corr) == R::intensity && hits == 0,
         "the '99.968' tie: 1562 recovers, 1563 has no raw count");
+  // corr < 1 (above 100 ms): several raw counts share a value; the one nearest v / corr is taken, the smaller on a tie
   rc::opentimsCorrection("125", corr);
-  CHECK(point(2.0f, corr) == R::intensity && hits == 2, "corr 0.8: raw counts 2 and 3 both give 2 (%d found)", hits);
+  CHECK(point(2.0f, corr) == R::none && hits == 2 && raw == 2, "corr 0.8: raw counts 2 and 3 both give 2, the tie takes 2 (%d found, raw %u)", hits, raw);
+  rc::opentimsCorrection("166", corr);
+  CHECK(point(1.0f, corr) == R::none && hits == 2 && raw == 2, "corr 100/166: raw 1 and 2 give 1, 2 is nearer 1.66 (%d found, raw %u)", hits, raw);
+  long approx_bad = 0;
+  for (const double c : {0.8, 100.0 / 166.0, 0.5})
+    for (u32 r = 0; r < (1u << 20); ++r)
+    {
+      const u32 v = opentimsCorrect(r, c);
+      approx_bad += point(static_cast<float>(v), c) != R::none || opentimsCorrect(raw, c) != v || std::fabs(static_cast<double>(raw) - v / c) > 0.5 / c + 1e-9;
+    }
+  CHECK(approx_bad == 0, "corr < 1: %ld values below 2^20 do not recover a raw count that corrects back to them", approx_bad);
   rc::opentimsCorrection("50", corr);
   CHECK(opentimsCorrect(1u << 23, corr) == 16777216u && point(16777216.0f, corr) == R::intensity_range, "corr 2: raw 2^23 gives 2^24, refused");
   // the corr >= 1 threshold: no two raw counts collide at corr 1, 1 + 1 ulp or 100/96 (tie-prone), below 2^20
diff --git a/tests/test_tdf_load.cpp b/tests/test_tdf_load.cpp
index 6c30b7e..788212b 100644
--- a/tests/test_tdf_load.cpp
+++ b/tests/test_tdf_load.cpp
@@ -252,12 +252,12 @@ static void testAccumulationTime()
   refused("acc_null", dShaped() + "UPDATE Frames SET AccumulationTime = NULL WHERE Id = 6;", "AccumulationTime");
   CHECK(loads(makeTdf("acc_text.tdf", dShaped() + "UPDATE Frames SET AccumulationTime = '99.953' WHERE Id = 6;"), in, why) &&
           in.frames[6].corr == 100.0 / 99.953 && in.frames[1].corr == 100.0 / 99.958, "AccumulationTime as TEXT and as REAL: %s", why.c_str());
-  // above 100 ms the correction loads, and the setup refusal names it
-  CHECK(loads(makeTdf("acc_125.tdf", dShaped() + "UPDATE Frames SET AccumulationTime = '125' WHERE Id = 6;"), in, why) && in.frames[6].corr == 0.8 &&
-          has(dn::recover::correctionRefusal(6, in.frames[6].corr), "AccumulationTime 125 ms exceeds 100 ms") &&
-          dn::recover::correctionRefusal(1, in.frames[1].corr).empty(), "AccumulationTime 125: %s", why.c_str());
+  // above 100 ms the correction loads and is accepted (raw counts approximated, see recoverPoint)
+  CHECK(loads(makeTdf("acc_166.tdf", dShaped() + "UPDATE Frames SET AccumulationTime = '166' WHERE Id = 6;"), in, why) && in.frames[6].corr == 100.0 / 166.0 &&
+          dn::recover::correctionRefusal(6, in.frames[6].corr).empty() && dn::recover::correctionRefusal(1, in.frames[1].corr).empty(),
+        "AccumulationTime 166: %s", why.c_str());
   CHECK(loads(makeTdf("acc_100042.tdf", dShaped() + "UPDATE Frames SET AccumulationTime = 100.042 WHERE Id = 6;"), in, why) && in.frames[6].corr < 1.0 &&
-          !dn::recover::correctionRefusal(6, in.frames[6].corr).empty(), "AccumulationTime 100.042 (REAL): %s", why.c_str());
+          dn::recover::correctionRefusal(6, in.frames[6].corr).empty(), "AccumulationTime 100.042 (REAL): %s", why.c_str());
   // opentims parses under a C-locale guard; so must the port, whatever LC_NUMERIC the process has
   bool comma = false;
   if (const char* prev = std::setlocale(LC_NUMERIC, nullptr))
```
