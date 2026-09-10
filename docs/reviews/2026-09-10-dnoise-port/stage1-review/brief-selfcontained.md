# Adversarial review: SpeXtractor stage 1 -- an exact dnoise MS1 port and an output-identical MS1 prune

EVERYTHING YOU NEED IS INLINE BELOW. Do not run shell commands and do not try to open files; answer from this text.

## Context
SpeXtractor is an OpenMS TOPP tool (C++20, OpenMP) that builds pseudo-MS/MS spectra from Bruker timsTOF diaPASEF
data. Two changes are under review.

### A. src/DnoiseMs1.h (new, header-only) + tests/test_dnoise_ms1.cpp (new; not inlined, summarised)
A C++ port of dnoise v0.1.0's default MS1 denoising (MIT; Garrett, Diedrich & Yates III). Contract: for one MS1
frame of raw (scan index, TOF index, raw u32 intensity) points, the keep mask must be BIT-IDENTICAL to the set of
points the dnoise binary writes back. Semantics, verified against the binary:
- Streak filter, `iterations` (2) passes, each over the previous pass's survivors only: for each distinct TOF index c,
  sum intensities per scan over alive points with TOF in [c-3, c+3] (inclusive, saturating at 0); a scan is occupied
  iff its sum > 0 (and >= min_window_intensity, default 0); occupied scans form runs, a new run starts when the scan
  step exceeds max_internal_gap+1 (3); a run with >= 5 OCCUPIED scans (not span) whose span sum >= min_feature_intensity
  (0) accepts [first, last]; points with TOF == c whose scan lies in an accepted span survive.
- Halo, once, reference set = streak survivors: best = max intensity over survivors with scan in [s-2, s+2]
  (clamped) and TOF in [t-80, t+80] (saturating), EXCLUDING every point whose TOF == t; keep iff
  (double)I >= 0.15*(double)best; best == 0 keeps.
- diaPASEF MS1 window gate, ANDed last. Built once per run with timsrust 0.4.2's two-point calibration: m/z bounds
  MzAcqRangeLower/Upper widened by 5 Da each side iff AcquisitionSoftware == "Bruker otofControl"; tof_of(mz) =
  (sqrt(mz) - sqrt(mz_min)) / ((sqrt(mz_max) - sqrt(mz_min)) / DigitizerNumSamples); im_of(scan) = im_max +
  ((im_min - im_max)/Nscan)*scan with Nscan = max(Frames.NumScans) over all frames; per DiaFrameMsMsWindows row:
  m/z [Iso - W/2 - 5, Iso + W/2 + 5] -> TOF floor/ceil; scans from im_of(ScanNumBegin) and im_of(ScanNumEnd) (the
  exclusive end used as if inclusive) padded by 0.05 1/K0 -> scan floor/ceil, clamped to Nscan-1; saturating u32
  casts; the gate is the union of all boxes.
- Floating-point contraction is a proven hazard: on dataset D the scan bounds are floor/ceil of values within one ulp
  of an integer (e.g. 542.9999999999999); fusing im_max + slope*scan into an FMA flips 3 of 24 boxes. The header
  guards with GCC push_options/optimize("fp-contract=off"), clang `fp contract(off)`, AND a volatile on the product;
  CMake adds -ffp-contract=off for GNU/Clang.
- Performance shortcuts the author claims are result-preserving: stable LSD radix sort by TOF; two pointers instead
  of binary search per window; skipping windows with fewer occupied scans than min_feature_length; stopping passes
  early once a pass removes nothing; counting sort by scan for the halo; evaluating the gate only on halo survivors.
- Metadata strings parsed with std::from_chars where __cpp_lib_to_chars exists, else a classic-locale istringstream
  (libc++/macOS); both paths pre-check Rust's float grammar.
Validation done: 0 differing points against dnoise's output on 24 + 4 D frames and on 24 TNBC 009 frames (raw
intensities); 16-thread reverse-order runs byte-identical; 3,000 random frames against a line-by-line transliteration
of the Rust (zero intensities, duplicate (scan, TOF), TOF extremes, non-default params, random gates); unit test pins
D's 24 and TNBC's 28 gate boxes and fails with the guards removed.

### B. src/spextractor.cpp + e2e check 19 (test/test_spextractor.py): prune picked MS1 centroids at load, claimed OUTPUT-IDENTICAL
- The MS1 tracer is OpenMS MassTraceDetection; it keeps peaks with (double)intensity > noise_threshold_int (100) and
  counts EVERY spectrum it receives as a scan (sample-rate validity and outlier termination depend on that count).
- The tool splits the MS1 PeakMap into 48 m/z bands: edges are quantiles of a stride-97 m/z sample (indices 0, 97,
  194, ... of each spectrum) over all spectra; band b covers [MZBegin(lo), MZBegin(hi)) with lo = edge[b]*(1 - h),
  hi = edge[b+1]*(1 + h), h = 20 * mass_error_ppm * 1e-6 (3e-4 at 15 ppm); a band spectrum is inserted iff at least
  one peak of any intensity falls in that range; bands with < 3 spectra are skipped.
- The prune keeps every survivor (> noise), each spectrum's first and last peak, and the minimal chain of sub-threshold
  "witnesses" so consecutive kept peaks are at most c = h apart relative in m/z; the stride-97 edge sample is taken
  from the unpruned sorted spectra at flush and handed to detectTraces_ instead of re-sampling the pruned map.
  Claim: any band range that held an unpruned peak still holds a kept one, because hi - lo >= 2h*lo/(1-h) >= c*lo, so
  band membership, spectrum counts and the tracer's work content are unchanged (brute force: 0 mismatches in 360,968
  band checks, 37,119 without witnesses).
- Also an env probe SPEXTRACTOR_TILE_TRIM=1: malloc_trim(0) between tiles.
Validation done: e2e 19/19, including a fixture where dropping witnesses changes MS1 traces (6 -> 7) and precursors;
dataset D real data prune off vs on: identical output digest (the pin 8c1b047f) and all 245 [det]/[ms1-edges] lines
identical; peak 31.82 -> 26.49 GB; 3.40 M witnesses on 136.7 M survivors; 3.54 M centroids at exactly 100.0; on
dnoise-filtered D input also identical (e43672a0).

## What to attack -- be concrete, cite the inlined text (hunk context or line text)
1. Any input or parameter for which the port's keep mask differs from the semantics above (integer types,
   saturation, overflow, ordering, each claimed-equivalent shortcut, zero-intensity points, duplicate (scan, TOF)).
2. FP contraction and parsing: any compiler/flag combination or code path that can still contract the gate
   arithmetic or change evaluation order; parser correctness and locale independence.
3. The prune's identity: counterexamples involving edge sampling order and sortByPosition, NaN, exactly-at-noise
   peaks, float->double compares, the band builder's halo arithmetic versus the hop, first/last anchors, empty
   spectra, the Ion Mobility float array, the resident/mzML path, the stream-fallback reset, -perf:ms1_trace_bands 1,
   thread/tile/batch invariance; ANY path where the map is pruned but the edges are sampled from the pruned map.
4. Memory: does select() release capacity; any path that transiently doubles memory at the flush.
5. Concurrency: OpenMP regions, exceptions escaping parallel regions, shared counters.
6. The e2e fixture: does it really exercise the witness chain; could it pass vacuously.
7. Anything else that makes these changes wrong, unsafe, or not output-identical.
Report a numbered list, most severe first, each with location, a concrete failure scenario, and a fix. Say explicitly
when you found nothing in an area. Do not pad with style remarks.

## Inlined code
### 1. Diff of tracked files against git HEAD cc39a66 (src/spextractor.cpp and test/test_spextractor.py with 20 lines of context; CMakeLists.txt, NOTICE, tests.yml)
```diff
--- a/src/spextractor.cpp
+++ b/src/spextractor.cpp
@@ -1658,40 +1658,135 @@
     {
       static const std::map<std::string, Row> rows = []{
         std::map<std::string, Row> m;
         if (const char* e = std::getenv("SPEXTRACTOR_WINDOW_FILE"))
         {
           std::ifstream f(e); std::string ln;
           while (std::getline(f, ln))
           {
             char k[128]; unsigned long g; unsigned a, b;
             if (std::sscanf(ln.c_str(), "%127s %lu %u %u", k, &g, &a, &b) == 4) m[k] = Row{(size_t)g, a, b};
           }
           if (m.empty()) throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "SPEXTRACTOR_WINDOW_FILE has no rows", e);
         }
         return m; }();
       const auto it = rows.find(key);
       if (it == rows.end()) { if (!rows.empty()) throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "SPEXTRACTOR_WINDOW_FILE has no row for window", key); return false; }
       out = it->second; return true;
     }
   };
 
+  /// The MS1 band partition's halo in units of trace:mass_error_ppm: detectTraces_ widens every band by
+  /// this many tolerances on each side, and the load-time MS1 prune is exact only because its hop is
+  /// derived from the same number. There is deliberately only this one. [ms1-prune]
+  constexpr double kBandHaloPpmMul = 20.0;
+
+  /// [ms1-prune 2026-09-10] Picked MS1 centroids at or below trace:noise_threshold_int, dropped at load.
+  /// MassTraceDetection never traces them (its work map keeps (double)intensity > noise only), yet they
+  /// are ~81% of dataset D's picked MS1 map. Two things still read them, and both are kept exact:
+  ///  (i)  the band EDGES are quantiles of a stride-97 m/z sample of the whole map, so the sample is taken
+  ///       here, from the sorted spectrum BEFORE a peak is removed, and detectTraces_ uses it;
+  ///  (ii) a band spectrum EXISTS iff any peak lies in the band's range, and one whose peaks are all
+  ///       sub-threshold is still a SCAN to MassTraceDetection (it counts against min_sample_rate; an
+  ///       absent one does not). So a spectrum keeps its first and last peak plus the fewest sub-threshold
+  ///       witnesses that leave no two consecutive kept peaks more than hop (relative m/z) apart. A band
+  ///       range with its halo is at least 2 hop / (1 - hop) of its lower bound wide, so a range that
+  ///       holds any peak holds a kept one -- with a factor-2 margin over floating-point rounding.
+  /// Brute-forced against a model of the band builder and MassTraceDetection's filter: 0 of 360,968 band
+  /// checks differ, 37,119 without the witnesses. Never removes a spectrum or strips the IM array.
+  struct Ms1Prune
+  {
+    struct Counts { long long picked = 0, survivors = 0, kept = 0, at_noise = 0, nan = 0; };
+    bool on = false;              ///< perf:ms1_prune
+    bool no_witness = false;      ///< SPEXTRACTOR_MS1_PRUNE_NO_WITNESS=1: survivors only -- a negative control, NOT exact
+    double noise = 0.0;           ///< trace:noise_threshold_int, the very double MassTraceDetection is given
+    double hop = 0.0;             ///< trace:mass_error_ppm x 1e-6 x kBandHaloPpmMul
+    std::vector<double> sample;   ///< the stride-97 m/z sample of every spectrum pruned so far, taken unpruned
+    size_t frames = 0, sample_n = 0;   ///< spectra pruned; the sample size their picked counts imply
+    Counts total;
+
+    void reset() { std::vector<double>().swap(sample); frames = sample_n = 0; total = Counts(); }
+
+    /// One spectrum: sort by m/z (a no-op on a picked one), write the m/z values detectTraces_ would
+    /// sample to @p samp, then keep the survivors and the witnesses.
+    void frame(MSSpectrum& s, double* samp, Counts& c) const
+    {
+      s.sortByPosition();
+      const Size n = s.size();
+      for (Size i = 0; i < n; i += 97) *samp++ = s[i].getMZ();
+      std::vector<Size> keep;
+      const Size none = (Size)-1;
+      Size last = none, cand = none;   // the last kept peak; the farthest sub-threshold peak within its reach
+      auto reach = [&](Size k, double x) { const double m = s[k].getMZ(); return x <= m + hop * m; };
+      for (Size i = 0; i < n; ++i)
+      {
+        const double v = s[i].getIntensity();   // float -> double, as MassTraceDetection reads it
+        const bool surv = v > noise;            // its own test; the complement also drops NaN and == noise
+        c.survivors += surv; c.at_noise += (v == noise); c.nan += (v != v);
+        if (no_witness) { if (surv) keep.push_back(i); continue; }
+        const double x = s[i].getMZ();
+        if (last != none && reach(last, x)) { if (surv) { keep.push_back(i); last = i; cand = none; } else cand = i; continue; }
+        if (cand != none)                       // out of reach: the candidate becomes a witness first
+        {
+          keep.push_back(cand); last = cand; cand = none;
+          if (reach(last, x)) { if (surv) { keep.push_back(i); last = i; } else cand = i; continue; }
+        }
+        keep.push_back(i); last = i;            // the first peak, or the far side of a gap nothing bridges
+      }
+      if (cand != none) keep.push_back(cand);   // the last peak
+      c.picked += (long long)n; c.kept += (long long)keep.size();
+      if (keep.size() != n) s.select(keep);     // peaks and IM array in lockstep, into right-sized buffers
+    }
+
+    /// Prune every spectrum of @p v that @p take selects, in parallel. A spectrum's sample size does not
+    /// depend on the prune, so the offsets are fixed first; the order is irrelevant (detectTraces_ sorts).
+    void batch(std::vector<MSSpectrum>& v, bool (*take)(const MSSpectrum&))
+    {
+      std::vector<char> sel(v.size());
+      std::vector<size_t> off(v.size());
+      size_t at = sample.size();
+      for (size_t i = 0; i < v.size(); ++i) { sel[i] = take(v[i]); off[i] = at; if (sel[i]) at += (v[i].size() + 96) / 97; }
+      sample.resize(at);
+      std::vector<Counts> cs(v.size());
+      std::exception_ptr err;
+      #pragma omp parallel for schedule(dynamic, 1)
+      for (long i = 0; i < (long)v.size(); ++i)
+      {
+        if (!sel[(size_t)i]) continue;
+        try { frame(v[(size_t)i], sample.data() + off[(size_t)i], cs[(size_t)i]); }
+        catch (...)
+        {
+          #pragma omp critical(ms1_prune_err)
+          if (!err) err = std::current_exception();
+        }
+      }
+      if (err) std::rethrow_exception(err);
+      for (size_t i = 0; i < v.size(); ++i)
+      {
+        if (!sel[i]) continue;
+        const Counts& c = cs[i];
+        ++frames; sample_n += (size_t)(c.picked + 96) / 97;
+        total.picked += c.picked; total.survivors += c.survivors; total.kept += c.kept; total.at_noise += c.at_noise; total.nan += c.nan;
+      }
+    }
+  };
+
   class PickCompactConsumer : public FullSwathFileConsumer
   {
   public:
     PickCompactConsumer(PeakPickerIM& picker, map<WinKey, PeakSlab>& windows,
                         PeakMap& ms1, CompactStats& stats,
                         std::function<WinKey(double, double, uint32_t)> keyfn)
       : picker_(picker), windows_(windows), ms1_(ms1), stats_(stats), keyfn_(std::move(keyfn)) {}
 
     size_t frames_seen = 0;
     size_t frames_probe_dropped = 0;   ///< [tile-1] MS2 frames outside the probe's range + halo
 
     /// [frames] A window's FROZEN frame table (rt, vendor id) in the reader's delivery order, with
     /// the lockstep cursor: every table frame the reader skipped before the delivered one -- a raw
     /// frame with no peaks, an empty ion-mobility slice, a probe-dropped frame -- is appended EMPTY
     /// with the table's own rt and id, so the slab's frame sequence IS the table's in every mode
     /// (an empty frame is a scan, not a miss; a missing frame would be neither). Measured 0 pads
     /// on both pinned datasets, so today's output is unchanged; under the tiled readers the pads
     /// stand in for the frames that are not resident.
     struct FrameTab
     {
@@ -1699,40 +1794,42 @@
       size_t cur = 0, delivered = 0, padded = 0;
       /// pad up to the delivered frame (its rt AND vendor id equal the table row's -- an rt alone is
       /// ambiguous when two rows share one, e.g. an mzPeak archive without retention times); false
       /// = not in the table
       bool step(PeakSlab& sl, double t, uint32_t fid, size_t expected_frames)
       {
         while (cur < rt.size() && (rt[cur] != t || id[cur] != fid)) { sl.append(rt[cur], id[cur], nullptr, nullptr, nullptr, 0, expected_frames); ++cur; ++padded; }
         if (cur == rt.size()) return false;
         ++cur; ++delivered; return true;
       }
       void tail(PeakSlab& sl, size_t expected_frames)
       { for (; cur < rt.size(); ++cur, ++padded) sl.append(rt[cur], id[cur], nullptr, nullptr, nullptr, 0, expected_frames); }
     };
     using FrameTables = std::map<WinKey, FrameTab>;
     /// The reader's frozen tables, fetched at the first MS2 flush: both streaming readers publish
     /// their metadata before their first MS2 frame (the .d loader exports its frame table and
     /// windows before its MS2 loop, the mzPeak reader sweeps the archive before decoding). Unset
     /// (an mzML) = no tables, no padding: the slab is its own table.
     std::function<FrameTables()> tablefn;
     const FrameTables& tables() const { return tables_; }
+    /// [ms1-prune] pass 1's run-level MS1 prune and its edge sample; null = every picked peak is kept
+    Ms1Prune* ms1_prune = nullptr;
 
     /// [perf-load] Pick+compact a BATCH of buffered frames in parallel, then append in arrival
     /// order. OpenMS hands frames over a strictly serial `for (fid..) consumeSpectrum(spec)` loop,
     /// so before this the peak picking of 1.26e9 peaks ran on ONE thread and was 53% of total wall
     /// (measured: 1046 s wall, parallel factor 1.0). Buffering here parallelises it without
     /// touching the reader. Appending strictly by buffer index keeps the output order identical to
     /// the serial path; the emitted spectra matched it in m/z and differed in ~2% of intensities at
     /// the 1e-5..1e-4 relative level (Sage count unchanged).
     void flush_()
     {
       if (!tables_init_) { tables_init_ = true; if (tablefn) tables_ = tablefn(); }
       const int n = (int)buf_.size();
       if (n == 0) return;
       const double _tf0 = phase_clock_();
       // [ledger] the batch's RAW frames at 20 B per raw peak: a Peak1D is 16 B (a double position
       // plus a float intensity, padded) and the ion-mobility float array adds 4. Freed one by one
       // inside the pick loop below; this is the load's largest transient, and the reason its peak
       // is not the sum of what survives it. (Both reviews of 2026-09-10 corrected 16 -> 20.)
       long long raw_b = 0;
       for (const auto& sp : buf_) raw_b += (long long)sp.size() * 20;
@@ -1862,40 +1959,43 @@
         {
           auto& s = ms1_buf_[(size_t)i];
           ensureIMArrayName(s);
           if (s.getIMPeakType() != IMPeakType::IM_CENTROIDED) picker.pickIMCluster(s);
           ensureIMArrayName(s);
         }
         catch (...)
         {
           #pragma omp critical(pick_err_ms1)
           if (!pick_err) pick_err = std::current_exception();
         }
       }
       if (pick_err) std::rethrow_exception(pick_err);
       if (ms1HistOn_())
         for (const auto& sp : ms1_buf_)
         {
           long long c[5] = {0, 0, 0, 0, 0};
           for (const auto& pk : sp) { const float v = pk.getIntensity(); ++c[v < 100 ? 0 : v < 300 ? 1 : v < 1000 ? 2 : v < 10000 ? 3 : 4]; }
           for (int k = 0; k < 5; ++k) ms1Hist_()[(size_t)k].fetch_add(c[k], std::memory_order_relaxed);
         }
+      // [ms1-prune] after [ms1-hist] (which counts what was PICKED), before the charge below (which is then
+      // the kept bytes)
+      if (ms1_prune && ms1_prune->on) ms1_prune->batch(ms1_buf_, [](const MSSpectrum&) { return true; });
       { long long mb = 0; for (const auto& s : ms1_buf_) mb += (long long)s.size() * 20; ledAdd_(LC_MS1MAP, mb); }
       for (auto& s : ms1_buf_) ms1_.addSpectrum(std::move(s));
       ms1_buf_.clear();
       flush_wall_() += phase_clock_() - _tf0;
       loadTrim_();
     }
 
     void consumeSwathSpectrum_(MapType::SpectrumType& s, size_t /*swath_nr*/) override
     {
       const auto& prec = s.getPrecursors();
       if (prec.empty()) return;                      // no isolation window -> not routable
       const double c = prec[0].getMZ();
       const double lo = c - prec[0].getIsolationWindowLowerOffset();
       const double hi = c + prec[0].getIsolationWindowUpperOffset();
       flushMS1_();                                   // MS1 arrives first; pick it before any MS2 work
       key_.push_back(keyfn_(lo, hi, windowGroupOf(s.getNativeID())));
       buf_.push_back(std::move(s));                  // pick+compact deferred to flush_()
       ++frames_seen;
       if (buf_.size() >= kBatch_()) flush_();
     }
@@ -2286,40 +2386,50 @@
                           "peak-picking and compacting each frame on arrival, instead of loadExperiment() "
                           "which holds the entire run (MEASURED 90.3 GB RSS at t=0s -- that one-shot read IS "
                           "the memory floor and no downstream compaction can lower it, so with this off the "
                           "floor alone exceeds the whole tool's current peak). ON BY DEFAULT since 2026-09-04; "
                           "every benchmark figure on record was taken with it on. Bruker .d only -- ignored "
                           "for other inputs, which fall back to the one-shot reader. "
                           "CHANGES OUTPUT: this is not a pure performance switch. Measured on dataset D 2026-09-04, "
                           "true = 655,776 spectra in 5:11 at 78.4 GB, false = 656,371 in 10:30 at 121.8 GB, "
                           "spectrum lists NOT identical (0.09% more spectra with the one-shot reader). The two "
                           "readers pick peaks on different frame groupings; which is closer to the truth is "
                           "measured 2026-09-05: false is slightly MORE sensitive on a large file (+2.0%% Sage peptides at unchanged entrapment FDR) for 1.75x the memory and ~1.7x the wall. Every benchmark figure used true.", false);
     setValidStrings_("perf:stream_load", {"true", "false"});
     registerIntOption_("trace:native_ms2_neighbors", "<n>", 0, "NATIVE cross-frame aggregation in the READER (BrukerTimsFile Config dia_ms2_n_neighbors): adjacent frames each side, 0=off, 1=3-frame sum, 2=5-frame sum. This sums RAW frames BEFORE centroiding, which is what the reference implementation does; summing AFTER centroiding instead lost 26% of peptides. Requires perf:stream_load.", false);
     registerIntOption_("trace:native_ms1_neighbors", "<n>", 0, "Same, for MS1 frames (BrukerTimsFile Config ms1_n_neighbors). Requires perf:stream_load.", false);
 
     registerTOPPSubsection_("perf", "Concurrency / memory tradeoff");
     registerStringOption_("gate:coelution", "<mode>", "pearson", "Fragment-precursor co-elution statistic. 'pearson' takes variance over the FULL RT grid, so a fragment present in a handful of points is scored against ~1300 implicit zeros -- it rewards sparse fragments that spike where the precursor spikes, and its scale depends on grid size rather than evidence. 'logoverlap' is the AlphaDIA-style alternative: profile overlap in log space, summed only where the precursor has signal, normalised to [0,1]. The two are on DIFFERENT SCALES, so gate:min_correlation must be retuned when switching.", false);
     setValidStrings_("gate:coelution", {"pearson", "logoverlap"});
     registerFlag_("gate:variance_support", "Compute the Pearson co-elution variance over the UNION SUPPORT of the precursor and fragment profiles (points where either is non-zero) rather than the full RT grid G (~1300). Fixes the zero-padding: a fragment present in a handful of grid points is no longer scored against ~1300 implicit zeros, and the score no longer depends on grid size. Only affects gate:coelution=pearson. Retune gate:min_correlation when enabling -- the score scale changes.");
     registerIntOption_("perf:ms1_trace_bands", "<n>", 48, "Band-parallel MS1 mass-trace detection, same exact-partition scheme as perf:trace_bands. DEFAULT RAISED 12 -> 48 on 2026-09-07: the earlier sweep found more bands to be WORSE (12/24/48 -> 75.0/93.7/147.9 s) but it was measuring a SERIAL band distribution that grew with band count; with that step parallel the order inverts (41.7/27.1/20.4 s at 9.8x/18.4x/32.4x) and 48 was gated on both datasets -- Sage 0.9999 and 0.9994, MSFragger 1.0002 and 1.0203, entrapment FDR 1.26->1.24%% and 1.12->1.07%%. MS1 tracing was running SINGLE-THREADED (the call simply never passed a band count) while MS2 was banded, so the MS1 phase pinned one core. That is invisible at default thresholds because MS1 is only ~4% of frames, but it makes the MS1 SENSITIVITY sweep impossible: lowering trace:noise_threshold_int / ms1_chrom_peak_snr explodes MassTraceDetection's intensity-sorted apex list, and MassTraceDetection is a SERIAL greedy loop, so runtime blows up superlinearly on one core (measured: 40 min with no progress at 1.5 of 128 cores, vs 24 min for a whole default run). 1 = off (old behaviour).", false);
+    registerStringOption_("perf:ms1_prune", "<true/false>", "true",
+                          "Drop picked MS1 centroids at or below trace:noise_threshold_int as they are loaded, before "
+                          "they enter the MS1 map. MassTraceDetection never traces such a peak, but the MS1 band partition "
+                          "reads the whole map, so the prune keeps exactly what it reads: the band edges come from the m/z "
+                          "sample taken before the prune, and each frame keeps its first and last peak plus the fewest "
+                          "sub-threshold witnesses that leave no two kept peaks further apart than the band halo (20 x "
+                          "trace:mass_error_ppm), so every band spectrum that exists without the prune still exists. "
+                          "OUTPUT-IDENTICAL (class D): byte-identical spectra either way; only the MS1 map shrinks. Bound "
+                          "to trace:noise_threshold_int -- it has no threshold of its own. false = keep every picked centroid.", false);
+    setValidStrings_("perf:ms1_prune", {"true", "false"});
     registerIntOption_("perf:trace_bands", "<n>", 12, "Split each window's fragment m/z range into N bands traced CONCURRENTLY. The diaPASEF method fixes the window count (24 here), which caps window-level parallelism far below the core count; banding lifts the ceiling to threads. Traces cannot span more than trace:mass_error_ppm in m/z, so banding with a halo is exact. 0 = auto (windows x bands >= threads), 1 = off.", false);
     registerDoubleOption_("perf:mem_fraction", "<f>", 0.75, "Fraction of currently-FREE RAM (/proc/meminfo MemAvailable) the window loop may commit. Concurrency is re-decided at every window admission, so the run adapts to other jobs on a shared node. One window is always admitted regardless, so a single oversized window cannot deadlock.", false);
     registerIntOption_("perf:max_concurrent_windows", "<n>", 0, "UPPER bound on isolation windows processed concurrently (memory admission may run fewer). Peak RAM scales with windows IN FLIGHT (each holds its frames + traces + grid), not with the total window count, so lowering this trades wall time for RAM. 0 = unlimited (use all threads).", false);
 
     registerTOPPSubsection_("diag", "Diagnostics ('debug' is reserved by TOPP)");
     registerStringOption_("diag:dump_ms1_tsv", "<prefix>", "", "Write MS1 traces and inferred precursors to <prefix>.traces.tsv / <prefix>.precursors.tsv so precursor loss can be attributed to a stage (no trace / no hypothesis / no spectrum) rather than inferred from the final count. Empty = off.", false, true);
 
     registerIntOption_("max_charge", "<n>", 5, "Maximum precursor charge considered during isotope inference.", false);
 
     // NOTE: the subsection MUST be registered or printUsage_() throws ElementNotFound — which turns
     // any user parameter typo into a FATAL crash instead of a usage message. [bugfix]
     registerTOPPSubsection_("charge", "Isotope / charge-state inference");
     registerIntOption_("charge:min_charge", "<n>", 1, "Minimum precursor charge to emit; hypotheses below it "
                        "are dropped before extraction. DEFAULT CHANGED 2 -> 1 on 2026-09-08. The old default rested on "
                        "dataset D, where z=1 was ~30%% of emission and ~1.7%% of peptides; on a 2-hour tryptic acquisition "
                        "(TNBC) it discards 14-20%% of Sage peptides and most of the MSFragger deficit against the reference "
                        "implementation. Those identifications are physically singly charged: short (7-9 aa), lysine-terminated, "
                        "single-basic-site tryptic peptides whose ion mobility sits +0.29 Vs/cm2 above the 2+ trend line at "
                        "the same m/z in 99.4-99.9%% of cases -- a halved 2+ ion would carry the 2+ mobility. The halved 2+ "
                        "ions that DO occur (~13%% of z=1 calls, sitting on the 2+ band) are re-called by charge:im_charge_veto. "
@@ -2380,41 +2490,42 @@
     setMinFloat_("perf:mem_fraction", 0.05);
     setMaxFloat_("perf:mem_fraction", 0.95);
     // deliberate: mass-defect filter default OFF (would silently drop PTM/nonspecific — the discovery cases). [H-7]
   }
 
   /// Configure an IM-aware MassTraceDetection and run it on @p map.
   /// MassTraceDetection wrapper. NOTE the apex gate inside MassTraceDetection is
   ///   peak_int > chrom_peak_snr * noise_threshold_int
   /// so the EFFECTIVE apex threshold is snr*noise, while trace MEMBERSHIP only needs > noise.
   /// Leaving snr at the OpenMS default 3.0 silently triples the fragment apex threshold.
   /// the reference implementation deliberately runs MS2 with "more relaxed constraints" than MS1 (Nat Commun 16:95
   /// Methods) — so MS1 and MS2 get INDEPENDENT snr / min-length here. [recall]
   /// `map` is taken by NON-const ref and CLEARED as soon as MassTraceDetection has consumed it:
   /// it is dead from that point on, but at ~20 B/peak (Peak1D 16 + IM float 4) it is ~1.1 GB per
   /// window that would otherwise stay resident through the valley-splitting peak. [compact]
   vector<Trace> detectTraces_(PeakMap& map, TraceStore& store, double delta_im, double noise,
                               double snr, double min_len, double min_sample_rate,
                               double split_valleys, String* span_log, int bands,
                               double split_scan_time,   // the run's cycle time for the splitter, 0 = per trace
                               int in_cat = -1,          // [ledger] the caller's category for `map`, -1 = uncharged
-                              int part_cat = LC_BAND)   // [ledger] where this call's band partition belongs
+                              int part_cat = LC_BAND,   // [ledger] where this call's band partition belongs
+                              Ms1Prune* ms1_prune = nullptr)   // [ms1-prune] the MS1 call only: the pre-prune edge sample
   {
     MassTraceDetection mtd;
     mtd.setLogType(ProgressLogger::NONE); // quiet + thread-safe (called from the parallel window loop)
     Param p = mtd.getParameters();
     p.setValue("mass_error_ppm", getDoubleOption_("trace:mass_error_ppm"));
     p.setValue("noise_threshold_int", noise);
     p.setValue("chrom_peak_snr", snr);
     p.setValue("ion_mobility_tolerance", delta_im);        // IM-aware tracing [C-1]
     p.setValue("min_trace_length", min_len);
     // min_sample_rate (OpenMS default 0.5) requires a peak in >=50% of visited scans AND terminates
     // trace extension when occupancy drops below it — an intensity-INDEPENDENT deletion of gappy but
     // real fragment traces in sparse diaPASEF data. Relaxing it for MS2 is the sole surviving MS2
     // trace-validity lever. [recall]
     if (min_sample_rate >= 0.0) p.setValue("min_sample_rate", min_sample_rate);
     mtd.setParameters(p);
 
     // [epd-parallel] Reusable valley-split step. Called from a balanced parallel-for below, so 12
     // chunks split concurrently instead of once serially. Lock-free now that OpenMS EPD is patched
     // (patches/openms-epd-lockfree.patch); 96 concurrent callers (8 windows x 12 chunks) do not
     // contend. Output is order-independent downstream: MS2 traces are canonically re-sorted right
@@ -2438,118 +2549,126 @@
     // [tstage] Sub-stage seconds for this phase. MS1_TRACE runs at 4.8x on 100 threads and is the
     // second-largest phase on a 2-hour acquisition, and the milestone timer alone cannot say
     // whether that is the SERIAL band distribution, imbalance across the band detectors, or the
     // valley split. One line, so the next decision here is measured rather than assumed.
     double tt_edge = 0, tt_dist = 0, tt_mtd = 0, tt_gather = 0, tt_split = 0;
     auto tt_now = []() { return std::chrono::steady_clock::now(); };
     auto tt_s = [](auto a, auto b) { return std::chrono::duration<double>(b - a).count(); };
     if (bands > 1)
     {
       // [bands] The diaPASEF method fixes the window count at 24, so parallelising over
       // windows caps us at 24 threads however many cores exist. Fragment traces at
       // different m/z are INDEPENDENT, so a window's peaks can be partitioned by m/z and
       // traced concurrently. A trace can never span more than mass_error_ppm in m/z, so a
       // halo of 20x that tolerance makes the partition exact; each trace is kept only by the
       // band whose CORE contains its centroid, so halo duplicates are dropped rather than merged.
       const double ppm = getDoubleOption_("trace:mass_error_ppm");
       // Band edges from m/z QUANTILES, not uniform m/z: peak density varies by orders of
       // magnitude across a window, and uniform edges would leave one band holding most of the work.
       auto _te0 = tt_now();
       vector<double> sample;
-      for (const auto& s : map)
-        for (Size i = 0; i < s.size(); i += 97) sample.push_back(s[i].getMZ());
+      if (ms1_prune && ms1_prune->on) sample.swap(ms1_prune->sample);   // [ms1-prune] taken before the prune; the pruned map's own would move the edges
+      else
+        for (const auto& s : map)
+          for (Size i = 0; i < s.size(); i += 97) sample.push_back(s[i].getMZ());
       sort(sample.begin(), sample.end());
       vector<double> edge(bands + 1);
       if (sample.empty()) { edge.assign(bands + 1, 0.0); }
       else
         for (int b = 0; b <= bands; ++b)
           edge[b] = sample[std::min(sample.size() - 1, (size_t)((double)b / bands * sample.size()))];
       edge.front() = 0.0; edge.back() = std::numeric_limits<double>::max();
+      if (ms1_prune && detOn_())   // [det] condition (i) of the MS1 prune, gated on its own
+      { vector<uint64_t> eb; for (double e : edge) { uint64_t u; std::memcpy(&u, &e, 8); eb.push_back(u); }
+        writeLogInfo_("[ms1-edges] n=" + String(sample.size()) + " bands=" + String(bands) + " fnv=" + String(detDigest_(std::move(eb)))); }
       vector<double> ().swap(sample);
 
       // Partition ONCE (peaks are copied into exactly one core band plus any halo it falls in),
       // then release the source map so the halo duplicates are the only overhead.
       tt_edge = tt_s(_te0, tt_now());
       auto _td0 = tt_now();
       // [dist-par 2026-09-07] The distribution was SERIAL and, measured, 51% of this phase
       // (dataset D: 39.0 s of 75.9 s; and raising the band count made the phase strictly worse --
       // 12/24/48 bands -> 75.0/93.7/147.9 s -- because more bands means more of exactly this
       // copy). Split the SPECTRA into chunks instead: each chunk builds its own per-band maps
       // and releases its source spectra as it goes, then the chunks are concatenated in chunk
       // order. Same spectra, same peaks, same order in every band, so byte-identical -- and the
       // source still shrinks as the copies grow, which is what keeps the transient at ~1x rather
       // than 2x the map.
       int n_thr = 1;
 #ifdef _OPENMP
       n_thr = omp_get_max_threads();
 #endif
       const int nchunk = std::max(1, std::min((int)map.size(), 4 * n_thr));
       vector<vector<PeakMap>> csub((size_t)nchunk, vector<PeakMap>(bands));
       #pragma omp taskloop grainsize(1) default(shared)
       for (int ci = 0; ci < nchunk; ++ci)
       {
       const size_t sp0 = (size_t)ci * map.size() / nchunk, sp1 = (size_t)(ci + 1) * map.size() / nchunk;
       for (size_t spi = sp0; spi < sp1; ++spi)
       {
         auto& s = map[spi];        // non-const: each spectrum is released once distributed
         const auto* ima = s.getFloatDataArrays().empty() ? nullptr : &s.getFloatDataArrays()[0];
         // isSorted() is a full traversal of the spectrum, and the spectrum does not change between
         // bands -- evaluating it inside the band loop walked every peak once per band.
         const bool src_sorted = s.isSorted();
         for (int b = 0; b < bands; ++b)
         {
           // Size each halo from ITS OWN edge: one h derived from edge[b] under-sizes the upper
           // side by the ppm growth across the band.
-          const double lo = edge[b] - edge[b] * ppm * 1e-6 * 20.0;
-          const double hi = edge[b + 1] + edge[b + 1] * ppm * 1e-6 * 20.0;
+          const double lo = edge[b] - edge[b] * ppm * 1e-6 * kBandHaloPpmMul;
+          const double hi = edge[b + 1] + edge[b + 1] * ppm * 1e-6 * kBandHaloPpmMul;
           MSSpectrum t; t.setRT(s.getRT()); t.setMSLevel(1);
           OpenMS::DataArrays::FloatDataArray ia;
           ia.setName(Constants::UserParam::ION_MOBILITY);
           // [R3, 2026-09-02] spectra arrive m/z-sorted (loader sortByPosition), so the band's peak range is
           // two lower_bounds instead of a scan of every peak for every band (O(bands x peaks) -> O(bands log
           // peaks)). Same peaks in the same order -> byte-identical; the scan stays as the unsorted fallback.
           Size i0 = 0, i1 = s.size();
           if (src_sorted)
           {
             i0 = (Size)(s.MZBegin(lo) - s.begin());
             i1 = (Size)(s.MZBegin(hi) - s.begin());
             t.reserve(i1 - i0); ia.reserve(i1 - i0);
             for (Size i = i0; i < i1; ++i) { t.push_back(s[i]); if (ima && i < ima->size()) ia.push_back((*ima)[i]); }
           }
           else
             for (Size i = 0; i < s.size(); ++i)
               if (s[i].getMZ() >= lo && s[i].getMZ() < hi)
               { t.push_back(s[i]); if (ima && i < ima->size()) ia.push_back((*ima)[i]); }
           if (!t.empty()) { t.getFloatDataArrays().push_back(std::move(ia)); csub[ci][b].addSpectrum(std::move(t)); }
         }
         s.clear(true);   // distributed: release it now, so the source and the copies do not both
       }                  // stand at full size (the transient was ~2x the map)
       }
       map.clear(true);
       vector<PeakMap> sub(bands);
       for (int b = 0; b < bands; ++b)
       {
         size_t nsp = 0; for (int ci = 0; ci < nchunk; ++ci) nsp += csub[ci][b].size();
         sub[b].reserveSpaceSpectra(nsp);
         for (int ci = 0; ci < nchunk; ++ci)
         { for (auto& sp : csub[ci][b]) sub[b].addSpectrum(std::move(sp)); csub[ci][b].clear(true); }
       }
+      if (ms1_prune && detOn_())   // [det] which (frame, band) spectra exist: condition (ii) of the MS1 prune
+      { String cnt; for (int b = 0; b < bands; ++b) cnt += (b ? "," : "") + String(sub[b].size());
+        writeLogInfo_("[det] MS1 band spectra " + cnt); }
       // [ledger] the partition is a COPY of the whole map (plus a 1-5% halo) and lives from here
       // until each band is detected -- charged as ms1_map until now, which named the wrong
       // structure for the largest allocation of the MS1 phase. Hand the charge over at the swap.
       vector<long long> band_b((size_t)bands, 0);
       { long long tb = 0;
         for (int b = 0; b < bands; ++b) { band_b[(size_t)b] = ledMapBytes_(sub[b]); tb += band_b[(size_t)b]; }
         ledAdd_(part_cat, tb); if (in_cat >= 0) ledSet_(in_cat, 0); }
       vector<vector<PeakMap>>().swap(csub);
       tt_dist = tt_s(_td0, tt_now());
       // [ms1-trim probe 2026-09-10] On TNBC 009 at 13 tiles the process peak IS this phase: 68,666 MiB,
       // of which 28,605 MiB is glibc free list -- the MS1 map, released spectrum by spectrum by the
       // distribution above and not reused by the band copies. One full-arena walk here, before the
       // bands are detected, returns it. SPEXTRACTOR_MS1_TRIM=1 enables it (MS1 call only: in_cat >= 0);
       // unset is exactly today's behaviour. Output-identical by construction.
       static const bool ms1_trim = []{ const char* e = std::getenv("SPEXTRACTOR_MS1_TRIM"); return e && *e && *e != '0'; }();
       if (ms1_trim && in_cat >= 0)
       {
 #ifdef __GLIBC__
         const double _tt = phase_clock_(); const long _r0 = rss_mb_();
         malloc_trim(0);
@@ -3514,40 +3633,46 @@
     const double delta_rt = getDoubleOption_("gate:delta_rt");
     if (getFlag_("diag:selftest_arena")) return selftestArena_();
     log_overlap_ = (getStringOption_("gate:coelution") == "logoverlap");
     im_weight_sigma_ = getDoubleOption_("assembly:im_weight_sigma");
     mono_guard_ = getDoubleOption_("charge:mono_averagine_guard");
     mono_select_ = getFlag_("charge:mono_averagine_select");
     var_support_ = getFlag_("gate:variance_support");
     corr_power_ = getDoubleOption_("assembly:corr_power");
     const double min_corr = getDoubleOption_("gate:min_correlation");
     const int min_corr_pts = getIntOption_("gate:min_correlation_points");
     const Size min_frags = (Size)getIntOption_("assembly:min_fragments");
     const Size max_frags = (Size)getIntOption_("assembly:max_fragments");
     const int max_charge = getIntOption_("max_charge");
     mzEstimator() = getStringOption_("trace:mz_estimator");   // before any toTrace() call
     const double mass_ppm = getDoubleOption_("trace:mass_error_ppm");
 
     PeakMap exp;
     // Accept mzML, mzPeak, or a Bruker .d directory; FileHandler auto-detects the format
     // (mzPeak -> MzPeakFile; .d -> BrukerTimsFile, requires WITH_OPENTIMS).
     PeakMap ms1_map;
+    // [ms1-prune] one run-level prune (see Ms1Prune), used by the streaming consumer and the resident dispatch alike
+    Ms1Prune ms1_prune;
+    ms1_prune.on = (getStringOption_("perf:ms1_prune") == "true");
+    ms1_prune.noise = getDoubleOption_("trace:noise_threshold_int");
+    ms1_prune.hop = getDoubleOption_("trace:mass_error_ppm") * 1e-6 * kBandHaloPpmMul;
+    { const char* e = std::getenv("SPEXTRACTOR_MS1_PRUNE_NO_WITNESS"); ms1_prune.no_witness = e && *e && *e != '0'; }
     map<WinKey, PeakSlab> ms2_by_window;
     CompactStats cstat;
     auto winKey = [](double lo, double hi, uint32_t window_group) -> WinKey {
       return {(int)llround(lo * 100.0), (int)llround(hi * 100.0), (int)window_group};
     };
     const bool stream_load = (getStringOption_("perf:stream_load") == "true");
     const bool trim_on = (getStringOption_("perf:malloc_trim") == "true");
     bool streamed = false;
     // [3a] trace:band_edges=acquisition needs the tdf's GlobalMetadata bounds: refuse BEFORE the
     // load when no candidate tdf provides them (an mzPeak archive is checked after its embedded
     // tdf is recovered, below). Milliseconds against minutes of loading.
     const bool band_edges_acq = (getStringOption_("trace:band_edges") == "acquisition");
     if (!band_edges_acq && getStringOption_("trace:detector") == "integer" && getStringOption_("perf:stream_load") == "true"
         && FileHandler::getTypeByFileName(in) == FileTypes::BRUKER_TDF && !std::getenv("SPEXTRACTOR_TILE_RESIDENT"))
       throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
             "trace:band_edges=slab needs the whole window resident; the .d streaming source reads it per tile. Use trace:band_edges=acquisition, or SPEXTRACTOR_TILE_RESIDENT=1 for the resident source.");
     if (band_edges_acq && std::getenv("SPEXTRACTOR_WINDOW_FILE"))   // an option x env conflict: refuse in milliseconds
       throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
             "SPEXTRACTOR_WINDOW_FILE overrides the band edges per window (a slab-mode probe); it cannot be combined with trace:band_edges=acquisition.");
     if (band_edges_acq && getStringOption_("trace:detector") == "integer")
@@ -3577,40 +3702,41 @@
     // A/B) holds the whole run and slices it, as before.
     bool tile_source = false;
     PickCompactConsumer::FrameTables run_tables;   // the reader's frozen tables, kept for pass 2
     BrukerTimsFile::Config cfg;
     cfg.dia_ms2_n_neighbors = getIntOption_("trace:native_ms2_neighbors");
     cfg.ms1_n_neighbors     = getIntOption_("trace:native_ms1_neighbors");
     PeakPickerIM spicker;
     {
       Param sp = spicker.getParameters();
       sp.setValue("pickIMCluster:im_tolerance_cluster", getDoubleOption_("gate:delta_im"));
       sp.setValue("pickIMCluster:ppm_tolerance_cluster", getDoubleOption_("trace:mass_error_ppm"));
       if (const char* m = std::getenv("SPEXTRACTOR_PICK_MZ_MODE")) sp.setValue("pickIMCluster:mz_mode", std::string(m));   // [C2 pick-level A/B] weighted|seed|top3
       spicker.setParameters(sp);
     }
 
     if (stream_load)
     {
       // [stream] frame-by-frame: pick + compact on arrival, never hold the whole run.
       // Also the ONLY place the reader's NATIVE pre-centroid frame aggregation is reachable.
       PickCompactConsumer consumer(spicker, ms2_by_window, ms1_map, cstat, winKey);
+      consumer.ms1_prune = &ms1_prune;
 #ifdef SPEXTRACTOR_WITH_MZPEAK
       const bool in_mzpeak = (FileHandler::getTypeByFileName(in) == FileTypes::MZPEAK);
 #else
       const bool in_mzpeak = false;
 #endif
       // [3b] the streaming source needs the Bruker loader: a .d only, never an mzML or an mzPeak
       // archive (the resident path reads those whole). SPEXTRACTOR_TILE_RESIDENT=1 forces the
       // resident source for a same-build A/B; any other value leaves the default.
       { const char* r = std::getenv("SPEXTRACTOR_TILE_RESIDENT");
         const bool force_resident = r && String(r) != "0" && String(r) != "";
         tile_source = !in_mzpeak && !force_resident && FileHandler::getTypeByFileName(in) == FileTypes::BRUKER_TDF; }
       if (tile_source)
       {
         // pass 1: MS1 only; lo > hi selects no MS2 frame, the loader exports the table anyway
         cfg.dia_ms2_rt_lo = std::numeric_limits<double>::infinity();
         cfg.dia_ms2_rt_hi = -std::numeric_limits<double>::infinity();
       }
       // [frames] The frozen frame tables come from the READER's metadata, keyed with the reader's
       // own precursor expressions so the keys equal the consumer's: the .d loader exports its
       // frame table and windows (patch: lastDIAFrameTable/lastDIAWindows; frames with no raw peaks
@@ -3727,40 +3853,44 @@
           if (w == ms2_by_window.end()) { ++n_absent; if (!tile_source) writeLogInfo_("[frames] window " + wl + ": absent (no frame delivered), " + String(kv.second.rt.size()) + " in the table"); continue; }
           if (w->second.rt != kv.second.rt || w->second.frame_id != kv.second.id)
             throw FrameTableError(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[frames] a window's slab is not its frozen frame table after padding", wl);
           n_pad += kv.second.padded; n_del += kv.second.delivered;
           writeLogInfo_("[frames] window " + wl + ": delivered " + String(kv.second.delivered) + ", padded " + String(kv.second.padded) + " of " + String(kv.second.rt.size()));
         }
         frame_table_src = table_src_if_ok;
         run_tables = consumer.tables();
         writeLogInfo_("[frames] source=" + frame_table_src + " windows=" + String(consumer.tables().size()) + " delivered=" + String(n_del) + " padded=" + String(n_pad) + " absent=" + String(n_absent)
                       + (tile_source ? " (pass 1: MS1 only; the windows' frames are read per tile)" : ""));
 #ifdef SPEXTRACTOR_WITH_MZPEAK
         if (in_mzpeak && spx::lastMzPeakMeta())
           writeLogInfo_("[frames] mzPeak number_of_peaks: " + String(spx::lastMzPeakMeta()->n_peaks_missing_ms2) + " MS2 spectra lack it and count as present"
                         + (spx::lastMzPeakMeta()->n_peaks_missing_ms2 ? " (a frame with no peaks among them would be padded)" : "; a recorded zero is skipped like the .d loop's"));
 #endif
       }
     }
 
     if (!streamed)
     {
+      // [ms1-prune] a failed stream attempt may have sampled and pruned part of pass 1: start clean. Spectra
+      // it already added to ms1_map stay there (they always did), and the count check before MS1 tracing
+      // then refuses the run rather than tracing on edges it cannot account for.
+      ms1_prune.reset();
       Phase _ph("LOAD(full)");
       FileHandler().loadExperiment(in, exp,
 #ifdef SPEXTRACTOR_WITH_MZPEAK
                                    {FileTypes::MZML, FileTypes::MZPEAK, FileTypes::BRUKER_TDF},
 #else
                                    {FileTypes::MZML, FileTypes::BRUKER_TDF},
 #endif
                                    log_type_);
     }
 
     //-------------------------------------------------------------
     // Input normalization / validation [C-4]
     //-------------------------------------------------------------
     // [stream] The streaming path fills ms1_map/ms2_by_window directly via an IM-aware consumer
     // (PickCompactConsumer calls ensureIMArrayName), leaving `exp` EMPTY -- so the exp-based IM check
     // only applies to the non-streaming load. Running it on the streamed (empty) `exp` wrongly aborted
     // with "no ion-mobility data at MS1", which is why native pre-centroiding aggregation could never
     // be benchmarked. Streamed data is guarded by the ms1_map.empty() check below instead.
     if (!streamed)
     {
@@ -3794,79 +3924,88 @@
     // (e.g. unexpected IM format); an exception escaping an OMP region terminates the process, so
     // capture it and rethrow serially. [par-Crit-1, code-review]
     std::exception_ptr pick_err;
     #pragma omp parallel for firstprivate(picker) schedule(dynamic, 16)
     for (long i = 0; i < (long)exp.size(); ++i)
     {
       try
       {
         MSSpectrum& s = exp[i];
         if (!s.containsIMData()) continue;
         if (s.getIMPeakType() != IMPeakType::IM_CENTROIDED) picker.pickIMCluster(s);
         ensureIMArrayName(s); // so MassTraceDetection reads per-peak IM (IM-aware tracing) [C-1]
       }
       catch (...)
       {
         #pragma omp critical
         if (!pick_err) pick_err = std::current_exception();
       }
     }
     if (pick_err) std::rethrow_exception(pick_err);
+    // [ms1-prune] exactly the MS1 spectra the dispatch below keeps, pruned as flushMS1_ prunes a batch
+    if (ms1_prune.on) ms1_prune.batch(exp.getSpectra(), [](const MSSpectrum& s) { return s.containsIMData() && s.getMSLevel() == 1; });
 
     // Serial dispatch: MOVE (not copy) frames into the MS1 map / per-window MS2 maps to avoid
     // transient memory doubling; container inserts aren't thread-safe so this stays serial.
     for (MSSpectrum& s : exp)
     {
       if (!s.containsIMData()) continue;
       if (s.getMSLevel() == 1)
       {
         ms1_map.addSpectrum(std::move(s));
       }
       else if (s.getMSLevel() == 2 && !s.getPrecursors().empty())
       {
         const OpenMS::Precursor& pr = s.getPrecursors()[0];
         double lo = pr.getMZ() - pr.getIsolationWindowLowerOffset();
         double hi = pr.getMZ() + pr.getIsolationWindowUpperOffset();
         ms2_by_window[winKey(lo, hi, windowGroupOf(s.getNativeID()))].append(compactify(s, cstat), ms1_map.size());
         s.clear(true);   // [mem] the picked frame is dead once compacted; waiting for exp.clear()
       }                  // below held the whole picked run (20 B/peak) beside the compact store
     }
     }
     exp.clear(true); // frames moved out; release the container
     {
       size_t cb = 0, cp = 0;
       for (const auto& kv : ms2_by_window) { cb += kv.second.bytes(); cp += kv.second.peaks(); }
       const size_t lost = cstat.no_im_array + cstat.size_mismatch + cstat.bad_mz + cstat.bad_im;
       if (lost)
       {
         writeLogWarn_("[compact] DROPPED " + String(lost) + " peaks: no_im_array=" + String(cstat.no_im_array)
                       + " size_mismatch=" + String(cstat.size_mismatch) + " bad_mz=" + String(cstat.bad_mz)
                       + " bad_im=" + String(cstat.bad_im) + " (kept " + String(cstat.kept) + ") -- if this is"
                       + " nonzero the compact store is NOT lossless and results differ from the old path.");
       }
       size_t ms1_pk = 0; for (const auto& sp : ms1_map) ms1_pk += sp.size();
       { long long sb = 0; for (const auto& kv : ms2_by_window) sb += (long long)kv.second.bytes();
         ledSet_(LC_SLAB, sb); ledSet_(LC_MS1MAP, (long long)ms1_pk * 20); }   // touched bytes; the 2.5x reserve is untouched pages
       writeLogInfo_("Split into MS1 + " + String(ms2_by_window.size()) + " windows (picked); compact store "
                     + String(cb / (1024ULL * 1024ULL)) + " MB for " + String(cp) + " peaks (~"
                     + String(cp ? (double)cb / cp : 0.0) + " B/peak); MS1 " + String(ms1_map.size()) + " frames / "
                     + String(ms1_pk) + " peaks (" + String(ms1_pk * 20 / (1024ULL * 1024ULL)) + " MB as PeakMap)." + clk_() + rss_() + mem_()); // [mem]
+      if (ms1_prune.on)
+      { const Ms1Prune::Counts& t = ms1_prune.total;
+        writeLogInfo_("[ms1-prune] picked " + String(t.picked) + " survivors " + String(t.survivors) + " witnesses " + String(t.kept - t.survivors)
+                      + " at_noise " + String(t.at_noise) + " nan " + String(t.nan) + ": kept " + String(t.kept) + " peaks = "
+                      + String(t.kept * 20 / (1024LL * 1024LL)) + " MB as PeakMap of " + String(t.picked * 20 / (1024LL * 1024LL)) + " MB picked; sample "
+                      + String(ms1_prune.sample.size()) + " m/z from " + String(ms1_prune.frames) + " spectra"
+                      + (ms1_prune.no_witness ? String(" -- SPEXTRACTOR_MS1_PRUNE_NO_WITNESS: survivors only, a negative control, output NOT identical") : String())); }
     }
 
     if (ms1_map.empty())
     {
       writeLogError_("Error: no MS1 ion-mobility frames found; cannot seed precursors.");
       return INCOMPATIBLE_INPUT_DATA;
     }
 
     // [cell] the frozen frame tables (see FrozenWin); today from the resident slabs, before
     // indexRt() frees their frame times and toTof() their frame ids
     map<WinKey, FrozenWin> frozen;
     if (tile_source)
       for (const auto& kv : run_tables)   // [3b] every window of the reader's table, no slab needed
       { FrozenWin& fw = frozen[kv.first]; fw.frame_rt = kv.second.rt; fw.frame_id = kv.second.id; }
     else
       for (const auto& kv : ms2_by_window)
       { FrozenWin& fw = frozen[kv.first]; fw.frame_rt = kv.second.rt; fw.frame_id = kv.second.frame_id; }
     // THE GLOBAL RT AXIS. Every frame contributes one retention time; every trace point sits on a
     // frame. Building it here, once, is what lets a trace point be 8 bytes (frame index +
     // intensity) instead of 16 (RT + intensity), and lets two profiles be aligned by integer
@@ -3950,48 +4089,55 @@
     const double max_span = getDoubleOption_("trace:max_span_sec");
     String ms1_span;
     // [parallel] MS1 tracing was UNBANDED: the call never passed a band count, so it defaulted to
     // 1 and MassTraceDetection -- a serial greedy loop over an intensity-sorted apex list -- ran on
     // ONE core while MS2 was banded across the machine. Invisible at default thresholds (MS1 is ~4%
     // of frames), fatal for the MS1 sensitivity sweep, which is the one lever the literature names
     // as the root cause of low-abundance loss in this tool class.
     int ms1_bands = getIntOption_("perf:ms1_trace_bands");
     if (ms1_bands < 1) ms1_bands = 1;
     double _t_ms1 = phase_clock_(), _c_ms1 = cpu_seconds_();   // [perf-instr]
     // detectTraces_ distributes its bands as TASKS, which requires an enclosing parallel region;
     // the window loop provides one, this phase must open its own. It also lets MS1 tracing use the
     // whole machine instead of the band count (it was measured at only 5.0x on 12 bands).
     vector<Trace> ms1_traces;
     // The MS1 traces' frame table is the MS1 map's own spectrum sequence (RT-sorted above); their
     // spans live in this store, which must outlive scoring.
     TraceStore ms1_store;
     { vector<uint32_t> ri; ri.reserve(ms1_map.size());
       for (const auto& sp : ms1_map) ri.push_back(rtIndex(sp.getRT()));
       ms1_store.setFrames(ri, nullptr); }
+    // [ms1-prune] every MS1 spectrum must have left its m/z sample before losing a peak, or the band edges
+    // would come from a pruned map. Checked here, outside the parallel region an exception cannot leave.
+    if (ms1_prune.on && (ms1_prune.frames != ms1_map.size() || ms1_prune.sample.size() != ms1_prune.sample_n))
+      throw Exception::Precondition(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[ms1-prune] the pre-prune m/z sample covers " + String(ms1_prune.frames)
+            + " spectra (" + String(ms1_prune.sample.size()) + " of " + String(ms1_prune.sample_n) + " m/z) but the MS1 map holds " + String(ms1_map.size())
+            + "; -perf:ms1_prune false keeps every peak");
     #pragma omp parallel
     #pragma omp single
     ms1_traces = detectTraces_(ms1_map, ms1_store, delta_im, getDoubleOption_("trace:noise_threshold_int"),
                                              ms1_snr, getDoubleOption_("trace:min_length_sec"), getDoubleOption_("trace:ms1_min_sample_rate"), getDoubleOption_("trace:ms1_split_valleys"), &ms1_span, ms1_bands,
-                                             split_scan_time, LC_MS1MAP, LC_MS1BAND);   // [ledger] the partition takes the charge over
+                                             split_scan_time, LC_MS1MAP, LC_MS1BAND, &ms1_prune);   // [ledger] the partition takes the charge over
     { const double cap = max_span;
       if (cap > 0.0) for (auto& t : ms1_traces) trimToSpan(ms1_store, t, cap); }
     ledSet_(LC_MS1MAP, 0);   // belt and braces: detectTraces_ has already zeroed it
+    vector<double>().swap(ms1_prune.sample);   // [ms1-prune] consumed by the band edges, or unused at one band
     { const long long tb = (long long)(ms1_traces.capacity() * sizeof(Trace) + ms1_store.inten.capacity() * 4
                                        + ms1_store.bins.capacity() * 2 + ms1_store.rt_index.capacity() * 4
                                        + ms1_store.frame_rt.capacity() * 8);
       ledSet_(LC_MS1TRACE, tb); }
     if (detOn_()) writeLogInfo_("[det] MS1 traces n=" + String(ms1_traces.size()) + " digest=" + String(traceDigest_(ms1_store, ms1_traces)));
     { auto& st = phase_stats_()["MS1_TRACE"]; if (st.n++ == 0) phase_order_().push_back("MS1_TRACE");
       st.wall += phase_clock_() - _t_ms1; st.cpu += cpu_seconds_() - _c_ms1; st.rss_end_mb = rss_mb_(); }
     writeLogInfo_("MS1 " + ms1_span);   // [merged-trace] measure, do not assume
 
     // [fwhm] Measure the actual chromatographic peak width from the MS1 traces just built, and
     // use it to set the MS2 valley-splitting window. chrom_fwhm is an ABSOLUTE TIME, so a fixed
     // default cannot be right across methods: 14.0 s gave +0.0% peptides on a 31 min gradient
     // and -1.06% on a 5.6 min one, where the same 14 s is proportionally 5.5x wider.
     // Median, not mean: FWHM distributions are heavy-tailed and a mean is dominated by a handful
     // of merged or truncated traces. Traces that never fall to half maximum on both sides are
     // EXCLUDED rather than imputed -- a truncated peak is not a narrow one, and imputing it
     // would bias the estimate downward exactly where peaks are broadest.
     double ms1_fwhm_med = -1.0;
     {
       vector<double> fw;
@@ -5445,40 +5591,52 @@
       {
         for (auto& sp : tile_out) sp.getDataProcessing().push_back(out_dp);   // ONE entry, by pointer, for every spectrum
         if (tiles.size() == 1) writer->setExpectedSize(tile_out.size(), 0);   // exact count: the bulk writer's bytes
         ledPhaseTile_("write", tk + 1);
         { Phase _ph("WRITE(mzML)"); writer->writeBlock(tile_out); }
         n_out += tile_out.size();
         ledAdd_(LC_SPECTRA, -tile_spec_bytes); ledSet_(LC_WRITER, (long long)n_out * 40);
         writeLogInfo_("[tile] " + String(tk + 1) + "/" + String(tiles.size()) + ": " + String(tile_out.size()) + " spectra written" + clk_() + rss_() + mem_());
       }
       else
       {
         all_out.reserve(all_out.size() + tile_out.size());
         for (auto& sp : tile_out) all_out.push_back(std::move(sp));   // [ledger] the same bytes, still charged
       }
     }
     carry_in = std::move(carry_out);
     { long long cb = 0; for (const auto& kv : carry_in) cb += (long long)(kv.second.rec.capacity() * sizeof(Trace) + kv.second.inten.capacity() * 4);
       ledSet_(LC_CARRY, cb); }
     carry_out.clear();
     for (const WinKey& k : fkeys) carry_out[k];
+#ifdef __GLIBC__
+    // [tile-trim probe 2026-09-10] Nothing returns the allocator's free pages between tiles -- the in-loop
+    // trim above runs only when there is one tile -- so a tiled loop's RSS ratchets toward the arena pass 1
+    // sized. SPEXTRACTOR_TILE_TRIM=1 walks every arena after tile k is written and before tile k+1 is read;
+    // unset is exactly today's behaviour. Output-identical by construction.
+    static const bool tile_trim = []{ const char* e = std::getenv("SPEXTRACTOR_TILE_TRIM"); return e && *e && *e != '0'; }();
+    if (tile_trim && trim_on && tk + 1 < tiles.size())
+    { const double _tt = phase_clock_(); const long _r0 = rss_mb_();
+      malloc_trim(0);
+      writeLogInfo_("[trim] tile " + String(tk + 1) + "/" + String(tiles.size()) + ": " + String(_r0) + " -> " + String(rss_mb_()) + " MB RSS in "
+                    + String(phase_clock_() - _tt) + " s" + mem_()); }
+#endif
     }   // tiles
     }   // the enclosed-phase scope
 
     { auto& st = phase_stats_()["WINDOW_LOOP"]; if (st.n++ == 0) phase_order_().push_back("WINDOW_LOOP");
       st.wall += phase_clock_() - _t_win; st.cpu += cpu_seconds_() - _c_win; st.rss_end_mb = rss_mb_(); }
     writeLogInfo_("[soa-rt] off-grid " + String(rtOffGrid().load())
                   + " = not-a-frame " + String(rtNotAFrame().load())
                   + " (of which strictly between two frames " + String(rtStrictlyBetween().load()) + ")"
                   + " + trimmed-out " + String(rtTrimmedOut().load()));
     if (rtOffGrid().load() != 0)
       writeLogWarn_("[soa-rt] " + String(rtOffGrid().load()) + " traces had an RT that is not one of "
                     "the store's frame times (ElutionPeakDetection skipped, or a span trimmed away from "
                     "its smoothed apex); their RT was snapped to the nearest frame. Zero is the "
                     "output-identical case -- a nonzero count here means the digest will differ.");
     else writeLogInfo_("[soa-rt] every trace RT was exactly a frame time (0 snapped).");
     writeLogInfo_("All windows done (admission high-water " + String(adm_hwm.load()) + " of "
                   + String(n_conc) + " allowed concurrent windows)." + clk_() + rss_() + mem_()); // [mem]
 #ifdef __GLIBC__
     if (trim_on)
     { const double _tt = phase_clock_(); const long _r0 = rss_mb_();
diff --git a/test/test_spextractor.py b/test/test_spextractor.py
index 4d9ff16..32d568a 100644
--- a/test/test_spextractor.py
+++ b/test/test_spextractor.py
@@ -1,38 +1,39 @@
 #!/usr/bin/env python3
 """End-to-end checks on a synthetic input. No framework, no fixtures: one file, plain asserts.
 
 Verification on this project has been whole-file cluster benchmarks, which catch regressions in
 aggregate but cannot say WHY a number moved, and cannot run before a commit. These are the smallest
 checks that fail if the things most likely to break do break:
 
   1. isotope ownership   one z=2 envelope (M, M+1, M+2) must yield ONE precursor at the mono, not
                          three, and the M+1/M+2 peaks must not reseed precursors of their own
   2. min_charge          a supported z=1 envelope is emitted at the default (1) and dropped at 2, while a
                          z=2 envelope is unaffected either way
   3. parameter bounds    a negative count must be REJECTED, not wrapped through Size into an
                          empty-but-successful run
   4. determinism         the same input at 1 and 4 threads must give byte-identical spectrum data
   5. trace extension     one missing cycle must leave ONE trace and its gapped fragment in the
                          spectrum; seven missing cycles must give TWO traces. Every version of the
                          integer detector that lost 92% of the peptides passed checks 1-4.
   ... 14. writer           count, id="spectrum=K", index="K" and the <indexList> offsets agree
+  ... 19. MS1 prune        perf:ms1_prune leaves the spectra byte-identical; dropping its witnesses does not
 
 These exercise the default (OpenMS) detector only. `trace:detector=integer` refuses to run
 without the vendor flight-time calibration, which a synthetic mzML cannot carry, so it is judged on
 real data in the benchmark harness and not here.
 
 Usage: test_spextractor.py /path/to/spextractor [workdir]
 Exit status is 0 only if every check passes.
 """
 import base64, hashlib, os, re, struct, subprocess, sys, tempfile
 
 ISO = 1.0033548
 PROTON = 1.007276
 
 
 def b64f(vals, double=True):
     fmt = "<%d%s" % (len(vals), "d" if double else "f")
     return base64.b64encode(struct.pack(fmt, *vals)).decode()
 
 
 def spectrum(idx, ms_level, rt, peaks, im, prec=None, group=0):
@@ -47,78 +48,82 @@ def spectrum(idx, ms_level, rt, peaks, im, prec=None, group=0):
 <cvParam cvRef="MS" accession="MS:1000827" name="isolation window target m/z" value="{target}" unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS"/>
 <cvParam cvRef="MS" accession="MS:1000828" name="isolation window lower offset" value="{target-lo}" unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS"/>
 <cvParam cvRef="MS" accession="MS:1000829" name="isolation window upper offset" value="{hi-target}" unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS"/>
 </isolationWindow><activation><cvParam cvRef="MS" accession="MS:1000044" name="dissociation method"/></activation></precursor></precursorList>"""
     # "frame=<N>" is the vendor key frameIdOf() parses; without it every frame is unmappable and
     # the integer detector falls back, which is how all 8 checks silently ran on the OTHER detector.
     return f"""<spectrum id="frame={idx + 1} windowGroup={group} scan=0" index="{idx}" defaultArrayLength="{len(peaks)}">
 <cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum"/>
 <cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="{ms_level}"/>
 <cvParam cvRef="MS" accession="MS:1000294" name="mass spectrum"/>
 <scanList count="1"><cvParam cvRef="MS" accession="MS:1000795" name="no combination"/>
 <scan><cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="{rt}" unitAccession="UO:0000010" unitName="second" unitCvRef="UO"/></scan></scanList>
 {pre}
 <binaryDataArrayList count="3">
 <binaryDataArray encodedLength="{len(mz)}"><cvParam cvRef="MS" accession="MS:1000514" name="m/z array" unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS"/><cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/><cvParam cvRef="MS" accession="MS:1000576" name="no compression"/><binary>{mz}</binary></binaryDataArray>
 <binaryDataArray encodedLength="{len(inten)}"><cvParam cvRef="MS" accession="MS:1000515" name="intensity array" unitAccession="MS:1000131" unitName="number of counts" unitCvRef="MS"/><cvParam cvRef="MS" accession="MS:1000521" name="32-bit float"/><cvParam cvRef="MS" accession="MS:1000576" name="no compression"/><binary>{inten}</binary></binaryDataArray>
 <binaryDataArray arrayLength="{len(im)}" encodedLength="{len(imarr)}"><cvParam cvRef="MS" accession="MS:1002816" name="mean inverse reduced ion mobility array" unitAccession="MS:1002814" unitName="volt-second per square centimeter" unitCvRef="MS"/><cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/><cvParam cvRef="MS" accession="MS:1000576" name="no compression"/><binary>{imarr}</binary></binaryDataArray>
 </binaryDataArrayList></spectrum>"""
 
 
-def synth(path, n_cycles=14, cycle_s=1.4, gap_cycles=(), groups=None, z1_shift=0, drop_ms2=None):
+def synth(path, n_cycles=14, cycle_s=1.4, gap_cycles=(), groups=None, z1_shift=0, drop_ms2=None, ms1_extra=None):
     """Two precursors that co-elute in one isolation window: a z=2 envelope and a z=1 envelope.
 
     Both are given a 3-peak isotope envelope so `require_isotope_support` keeps them, matching
     fragments that co-elute with the precursor, and a distinct ion mobility.
 
     `gap_cycles`: cycles in which the z=2 precursor AND its first fragment are ABSENT. This is
     the input that separates a correct trace-extension rule from a wrong one: OpenMS tolerates up
     to five consecutive missing frames before it ends a trace, so one gap must still give ONE
     trace, and seven consecutive gaps must give TWO. Every version of the integer detector that
     lost 92% of peptides passed the other checks in this file; none would have passed this.
 
     `groups`: two WindowGroup ids; the MS2 frames then alternate between them by cycle,
     which is how one diaPASEF scheme (PXD017703 "py3") acquires the SAME m/z window twice per
     cycle with shifted ion-mobility slices. They must become two windows, not one.
 
     `z1_shift`: cycles by which the z=1 precursor's elution apex is moved (negative = earlier),
     so the two precursors can be owned by different tiles. `drop_ms2`: (lo, hi) in seconds; MS2
     frames with lo <= rt < hi are omitted (a window with no frames in one tile).
+
+    `ms1_extra`: a function of the cycle returning extra MS1 peaks [(mz, intensity, 1/K0)].
     """
     win = (600.0, 590.0, 620.0)                    # target, lo, hi
     z2_mono, z2_im = 601.3, 0.90                   # a doubly-charged precursor
     z1_mono, z1_im = 610.6, 1.20                   # a singly-charged one
     z2_frags = [(233.11, 0.7), (348.19, 1.0), (461.27, 0.55)]
     z1_frags = [(288.14, 0.8), (401.22, 0.9)]
     specs, idx = [], 0
     for c in range(n_cycles):
         rt = 1.0 + c * cycle_s
         shape = 1.0 - abs(c - n_cycles / 2.0) / (n_cycles / 2.0 + 1.0)   # a triangular elution
         amp = max(shape, 0.05)
         shape1 = 1.0 - abs(c - (n_cycles / 2.0 + z1_shift)) / (n_cycles / 2.0 + 1.0)
         amp1 = max(shape1, 0.05)
         ms1, ms1_im = [], []
         gap = c in gap_cycles
         for k, rel in enumerate((1.0, 0.55, 0.20)):                      # averagine-ish envelope
             if not gap:
                 ms1.append((z2_mono + k * ISO / 2.0, 6.0e5 * amp * rel)); ms1_im.append(z2_im)
             ms1.append((z1_mono + k * ISO / 1.0, 4.0e5 * amp1 * rel)); ms1_im.append(z1_im)
+        for mz, it, im in (ms1_extra(c) if ms1_extra else ()):
+            ms1.append((mz, it)); ms1_im.append(im)
         order = sorted(range(len(ms1)), key=lambda i: ms1[i][0])
         specs.append(spectrum(idx, 1, rt, [ms1[i] for i in order], [ms1_im[i] for i in order])); idx += 1
         if drop_ms2 and drop_ms2[0] <= rt < drop_ms2[1]: continue
         ms2, ms2_im = [], []
         for fi, (mz, rel) in enumerate(z2_frags):
             if gap and fi == 0: continue                                   # first fragment gapped too
             ms2.append((mz, 2.0e5 * amp * rel)); ms2_im.append(z2_im)
         for mz, rel in z1_frags: ms2.append((mz, 1.5e5 * amp1 * rel)); ms2_im.append(z1_im)
         order = sorted(range(len(ms2)), key=lambda i: ms2[i][0])
         specs.append(spectrum(idx, 2, rt, [ms2[i] for i in order], [ms2_im[i] for i in order],
                               prec=win, group=groups[c % 2] if groups else 0)); idx += 1
     body = "\n".join(specs)
     open(path, "w").write(f"""<?xml version="1.0" encoding="ISO-8859-1"?>
 <indexedmzML xmlns="http://psi.hupo.org/ms/mzml"><mzML version="1.1.0" id="spextractor_test">
 <cvList count="1"><cv id="MS" fullName="Proteomics Standards Initiative Mass Spectrometry Ontology" URI="https://raw.githubusercontent.com/HUPO-PSI/psi-ms-CV/master/psi-ms.obo"/></cvList>
 <fileDescription><fileContent><cvParam cvRef="MS" accession="MS:1000580" name="MSn spectrum"/></fileContent></fileDescription>
 <softwareList count="1"><software id="so_test" version="0"><cvParam cvRef="MS" accession="MS:1000799" name="custom unreleased software tool" value="spextractor-test"/></software></softwareList>
 <instrumentConfigurationList count="1"><instrumentConfiguration id="ic_test"><cvParam cvRef="MS" accession="MS:1000031" name="instrument model"/></instrumentConfiguration></instrumentConfigurationList>
 <dataProcessingList count="1"><dataProcessing id="dp_test"><processingMethod order="0" softwareRef="so_test"><cvParam cvRef="MS" accession="MS:1000544" name="Conversion to mzML"/></processingMethod></dataProcessing></dataProcessingList>
 <run id="run_test" defaultInstrumentConfigurationRef="ic_test">
@@ -516,40 +521,94 @@ def main():
     check("the boundary carry is load-bearing", c17)
 
     # 18: a window with NO frames in a middle tile (its MS2 frames in [20.6, 30.4) dropped -- the
     #     range is given with a margin, 1.0 + 14 * 1.4 is 20.599999999999998): the
     #     empty-slab branch runs, the tile scores with carried fragments only, and the tiled run
     #     still equals the one-tile run of the same file
     def c18():
         import re
         tdf = synth_tdf(os.path.join(work, "analysis.tdf"), n_frames=64)
         env = dict(os.environ, SPEXTRACTOR_MZPEAK_TDF=tdf)
         inp_e = tiled_fixture("tiles_empty.mzML", drop_ms2=(20.0, 30.0))   # the frames at 20.6 (= 20.599999999999998) .. 29.0
         one = os.path.join(work, "tiles_empty_one.mzML")
         run(binary, inp_e, one, extra=("-tile:rt_sec", "10"), threads=2, env=env)
         t = os.path.join(work, "tiles_empty_t.mzML")
         r = run(binary, inp_e, t, extra=("-tile:rt_sec", "10", "-tile:cells_per_tile", "1"), threads=2, env=env)
         assert "no frames in the tile" in (r.stdout + r.stderr), "the empty-slab branch did not run:\n" + (r.stdout + r.stderr)[-800:]
         assert digest(t) == digest(one), "the tiled run of a window with an empty tile differs from the one-tile run"
         invariants(t, "empty-tile file")
     check("a window with no frames in a tile", c18)
 
-    total = 6 + 2 + 2 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 1
+    # 19: the MS1 prune (perf:ms1_prune, default true) drops picked MS1 peaks at or below
+    #     trace:noise_threshold_int at load and must leave the output byte-identical. The fixture makes it
+    #     load-bearing: an MS1 trace at m/z 400.25 with hits in cycles 6, 10 (apex) and 14 only, while
+    #     cycles 7-9 and 11-13 carry nothing but sub-threshold peaks inside its band's m/z range (400.2 at
+    #     50 and at exactly 100.0; 400.24-400.38 at 50, of which the chain drops 400.24). A band spectrum
+    #     whose peaks are all at or below the threshold is still a SCAN to MassTraceDetection: 3 hits in 9
+    #     scans fail min_sample_rate 0.5. Without those spectra it is 3 of 3 and a trace -- so the
+    #     no-witness control (SPEXTRACTOR_MS1_PRUNE_NO_WITNESS=1, survivors only) must change the MS1
+    #     traces or the band spectra, and the witness chain must change nothing. Each cycle's lowest peak
+    #     is its stride-97 m/z sample and places the band edges: 450 in cycles 0-5 / 15-20 (an edge above
+    #     the trace, and misses that end its extension), 300 in 6/10/14, 200 in 8. The hit in cycle 14 is
+    #     float32 nextafter(100): a survivor. 1 band is exact trivially; 2 and 48 are the real test.
+    def c19():
+        import re
+        nx100 = struct.unpack("<f", struct.pack("<I", struct.unpack("<I", struct.pack("<f", 100.0))[0] + 1))[0]
+        def extra(c):
+            if c <= 5 or c >= 15: return [(450.0, 150.0, 0.80)]
+            if c in (6, 10, 14): return [(300.0, 150.0, 0.80), (400.25, {6: 150.0, 10: 500.0, 14: nx100}[c], 0.95)]
+            if c == 8: return [(200.0, 150.0, 0.80), (400.2, 50.0, 0.95)]
+            if c in (7, 9): return [(400.2, 50.0, 0.95)]
+            return [(400.2, 100.0, 0.95), (400.24, 50.0, 0.95), (400.28, 50.0, 0.95), (400.38, 50.0, 0.95)]
+        inp_p = os.path.join(work, "prune.mzML")
+        synth(inp_p, n_cycles=21, ms1_extra=extra)
+        keys = {"traces": r"\[det\] MS1 traces n=\S+ digest=\S+", "sorted": r"\[det\] MS1 traces sorted by content: [^\n]*",
+                "prec": r"\[det\] precursors n=\S+ digest=\S+", "bands": r"\[det\] MS1 band spectra \S*", "edges": r"\[ms1-edges\] [^\n]*"}
+        def arm(bands, prune, nowit=False):
+            out = os.path.join(work, f"prune_b{bands}_{prune}{'_nowit' if nowit else ''}.mzML")
+            env = dict(os.environ, SPEXTRACTOR_DET="1")
+            if nowit: env["SPEXTRACTOR_MS1_PRUNE_NO_WITNESS"] = "1"
+            r = run(binary, inp_p, out, extra=("-perf:ms1_trace_bands", str(bands), "-perf:ms1_prune", prune), env=env)
+            log = r.stdout + r.stderr
+            got = {k: (m.group(0) if m else None) for k, m in ((k, re.search(p, log)) for k, p in keys.items())}
+            assert got["traces"] and got["prec"], f"bands {bands} prune {prune}: no [det] MS1/precursor line under SPEXTRACTOR_DET:\n" + log[-800:]
+            assert (got["bands"] is not None) == (bands > 1) and (got["edges"] is not None) == (bands > 1), \
+                f"bands {bands} prune {prune}: [det] MS1 band spectra / [ms1-edges] expected iff bands > 1: {got}"
+            return out, got, log
+        for bands in (1, 2, 48):
+            off, g_off, log_off = arm(bands, "false")
+            on, g_on, log_on = arm(bands, "true")
+            assert "[ms1-prune]" not in log_off, "perf:ms1_prune false still pruned"
+            m = re.search(r"\[ms1-prune\] picked (\d+) survivors (\d+) witnesses (\d+) at_noise (\d+) nan (\d+): kept (\d+)", log_on)
+            assert m, "the prune did not log its counters:\n" + log_on[-800:]
+            picked, surv, wit, at_noise, _, kept = (int(x) for x in m.groups())
+            assert kept == surv + wit and picked > kept and wit > 0 and at_noise == 3, \
+                f"the fixture does not exercise the prune (picked {picked}, survivors {surv}, witnesses {wit}, at_noise {at_noise}, kept {kept})"
+            assert digest(on) == digest(off), f"bands {bands}: perf:ms1_prune true changed the spectra"
+            for k in keys:
+                assert g_on[k] == g_off[k], f"bands {bands}: {k} differs with the prune on:\n  off {g_off[k]}\n  on  {g_on[k]}"
+            if bands > 1:
+                _, g_nw, _ = arm(bands, "true", nowit=True)
+                assert g_nw["traces"] != g_off["traces"] or g_nw["bands"] != g_off["bands"], \
+                    f"bands {bands}: dropping the witnesses changed neither the MS1 traces nor the band spectra -- the fixture does not exercise them"
+    check("the MS1 prune is output-identical, and its witnesses are load-bearing", c19)
+
+    total = 6 + 2 + 2 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 1
     print(f"\n{total - len(fails)}/{total} checks passed" + (f"; FAILED: {', '.join(fails)}" if fails else ""))
     return 1 if fails else 0
 
 
 if __name__ == "__main__":
     # A suite that CANNOT RUN must not look like a suite that ran: a failure outside a check() --
     # a fixture that no longer matches the tool's requirements, a binary that refuses an option --
     # used to escape as a traceback, and a gate chain grepping for "checks passed" or "FAIL" saw
     # nothing at all (2026-09-10: the band-edge default started requiring tdf metadata the
     # synthetic fixture did not write, and three chains reported an empty e2e section).
     try:
         sys.exit(main())
     except SystemExit:
         raise
     except BaseException as e:
         import traceback
         traceback.print_exc()
         print(f"\n0/0 checks passed; FAIL the suite could not run: {type(e).__name__}: {e}")
         sys.exit(2)
diff --git a/.github/workflows/tests.yml b/.github/workflows/tests.yml
index f2e8964..50b7587 100644
--- a/.github/workflows/tests.yml
+++ b/.github/workflows/tests.yml
@@ -30,7 +30,7 @@ jobs:
       - name: Build
         run: cmake --build build --config Release
 
-      - name: Calibration golden test (the C++ that ships)
+      - name: C++ golden tests -- calibration model and dnoise MS1 port (the C++ that ships)
         run: ctest --test-dir build -C Release --output-on-failure
 
       - name: Calibration golden test (Python reference implementation)
diff --git a/CMakeLists.txt b/CMakeLists.txt
index 6d069b4..2348893 100644
--- a/CMakeLists.txt
+++ b/CMakeLists.txt
@@ -14,18 +14,30 @@ if(NOT CMAKE_BUILD_TYPE)
   set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
 endif()
 
+# src/DnoiseMs1.h reproduces dnoise's MS1 window gate bit for bit only without floating-point
+# contraction: an FMA flips 3 of dataset D's 24 boxes, and Apple clang on arm64 contracts by default.
+# The header guards its own arithmetic; the flag keeps the translation units around it honest too, and
+# matches the cluster's in-tree build, where OpenMS compiles with it but does not export it.
+set(SPX_NO_FP_CONTRACT $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-ffp-contract=off>)
+
 # The tool itself cannot be built without a PATCHED OpenMS: it includes
 # <OpenMS/FORMAT/TdfMzCalibration.h>, which scripts/apply_openms_patches.sh installs into the
 # OpenMS tree, and calls BrukerTimsFile::lastMzCalibration, which the same patch adds. No released
 # OpenMS package contains either. The calibration model, however, is a self-contained header, so
-# it can be compiled and tested anywhere -- which is what CI does on every platform.
+# it can be compiled and tested anywhere -- which is what CI does on every platform. So is the
+# dnoise MS1 port (src/DnoiseMs1.h).
 option(SPEXTRACTOR_TESTS_ONLY "Build only the OpenMS-independent tests (portability CI)" OFF)
 if(SPEXTRACTOR_TESTS_ONLY)
   add_executable(test_calibration_cpp tests/test_calibration_cpp.cpp)
   target_include_directories(test_calibration_cpp PRIVATE src)
+  target_compile_options(test_calibration_cpp PRIVATE ${SPX_NO_FP_CONTRACT})
+  add_executable(test_dnoise_ms1 tests/test_dnoise_ms1.cpp)
+  target_include_directories(test_dnoise_ms1 PRIVATE src)
+  target_compile_options(test_dnoise_ms1 PRIVATE ${SPX_NO_FP_CONTRACT})
   enable_testing()
   add_test(NAME calibration_golden
            COMMAND test_calibration_cpp ${CMAKE_CURRENT_SOURCE_DIR}/tests/calibration_golden.json)
+  add_test(NAME dnoise_ms1 COMMAND test_dnoise_ms1)
   return()
 endif()
 
@@ -35,6 +47,7 @@ find_package(SQLite3 REQUIRED)   # analysis.tdf is read directly; a missing SQLi
 
 add_executable(spextractor src/spextractor.cpp)
 target_link_libraries(spextractor PRIVATE OpenMS SQLite::SQLite3)
+target_compile_options(spextractor PRIVATE ${SPX_NO_FP_CONTRACT})
 target_compile_definitions(spextractor PRIVATE SPEXTRACTOR_VERSION="${PROJECT_VERSION}")
 # The source carries the same number as a fallback for builds that do not go through this file
 # (the in-tree OpenMS build); refuse to configure if the two have drifted.
diff --git a/NOTICE b/NOTICE
index a1ce879..f0c4a48 100644
--- a/NOTICE
+++ b/NOTICE
@@ -13,6 +13,15 @@ was extracted into this standalone repository. It uses OpenMS classes including
 MassTraceDetection, ElutionPeakDetection, PeakPickerIM, BrukerTimsFile and
 FullSwathFileConsumer, and retains OpenMS's BSD-3-Clause terms.
 
+Ported code, used under its own licence (full text in LICENSES/):
+
+  dnoise v0.1.0 -- Garrett, Diedrich & Yates III, bioRxiv 2026.08.27.747603
+  https://github.com/pgarrett-scripts/dnoise (tag v0.1.0, commit fa750c9)
+  MIT License, Copyright (c) 2026 Patrick Garrett -- LICENSES/dnoise-MIT.txt
+  src/DnoiseMs1.h is a C++ port of its default MS1 denoising: the streak filter,
+  the halo filter and the diaPASEF MS1 window gate, including the timsrust 0.4.2
+  (Apache-2.0) two-point calibration formulas dnoise builds that gate with.
+
 Algorithmic ideas were reviewed against, but no code was taken from:
 
   the reference implementation (Nesvizhskii Lab)     -- pseudo-MS/MS extraction from diaPASEF
```

### 2. src/DnoiseMs1.h (new)
```cpp
#ifndef SPEXTRACTOR_DNOISE_MS1_H
#define SPEXTRACTOR_DNOISE_MS1_H
// Copyright (c) 2026, SpeXtractor authors. BSD-3-Clause.
//
// PORTED CODE: this file is a C++ port of the default MS1 path of dnoise v0.1.0
//   Garrett, Diedrich & Yates III, bioRxiv 2026.08.27.747603; github.com/pgarrett-scripts/dnoise,
//   tag v0.1.0 (commit fa750c9). MIT License, Copyright (c) 2026 Patrick Garrett.
// The MIT notice is reproduced in LICENSES/dnoise-MIT.txt and covers the ported logic: src/filter.rs,
// src/halo.rs, src/dia_ms1.rs, the gate construction in src/writer.rs and src/tdf/mod.rs, and the
// timsrust 0.4.2 metadata converters dnoise builds that gate with.
//
// Header-only and dependency-free for the same reason as TdfMzCalibration.h: the tool and the
// OpenMS-free unit test (tests/test_dnoise_ms1.cpp) compile the same code.
//
// The contract is BIT-IDENTITY with dnoise, not a better filter: for one MS1 frame, the keep mask is
// exactly the set of points dnoise v0.1.0 (default flags, diaPASEF) writes back. Every rule below was
// checked against the binary's output; each "obvious fix" changes that output measurably (points that
// differ on D frame 8724, 144,814 kept):
//   1. Stage order: the streak filter on the raw points, `iterations` passes, each summing only the
//      previous pass's survivors (1 pass: 24,906); then the halo ONCE, with the streak survivors as
//      its reference set (raw points as reference: 122); then the window gate ANDed (gate first: 199).
//   2. Raw u32 intensities from the frame blob, not the floor(I * 100 / AccumulationTime + 0.5) that
//      opentims and the Bruker SDK return. At default settings they only enter the halo ratio, yet on
//      24 TNBC 009 frames the corrected values flip 9 of 3.1 million kept points.
//   3. Streak: min_feature_length counts OCCUPIED scans of a gap-bridged run, not its span; points are
//      kept by span, which only matters for zero-intensity points.
//   4. Halo: the reference skips EVERY point in the point's own TOF column (that is what spares a
//      streak), ties are kept (strict >: 15), and an empty box keeps the point.
//   5. Gate: timsrust's two-point chord calibration (sqrt-linear over MzAcqRange/DigitizerNumSamples,
//      linear 1/K0 over max NumScans), NOT TdfMzCalibration.h; +-5 Da on the m/z range when the file
//      says "Bruker otofControl" (TOF edges move 317-1,953 bins without it); ScanNumEnd -- exclusive in
//      the schema -- converted as if inclusive (42); the union of every window row of every group.
//   6. Floating-point contraction. On D the 0.05 1/K0 pad is 59 scans to within an ulp, so gate scan
//      bounds are floor/ceil of values like 542.9999999999999; fusing `intercept + slope * scan` into
//      one FMA flips 3 of D's 24 boxes (13 points on 8724). The builder keeps that product apart
//      through a volatile and is compiled with contraction off, whatever the including translation
//      unit's flags; CMakeLists.txt passes -ffp-contract=off as well. tests/test_dnoise_ms1.cpp pins
//      D's boxes, those three included.
// Not ported, because dnoise's defaults never reach it on diaPASEF MS1: the mz_ppm width override,
// frame_half_width neighbourhoods, the selection-polygon gate (skipped whenever DiaFrameMsMsInfo and
// DiaFrameMsMsWindows map frames to windows), crop, smooth/watershed/box-centroid, and the MS2 paths.

#pragma once
#include <version>
#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#if !defined(__cpp_lib_to_chars)
#include <locale>
#include <sstream>
#endif

namespace spx::dnoise
{

inline constexpr const char* kPortedFrom = "dnoise v0.1.0 (fa750c9)";

/// dnoise v0.1.0's MS1 knobs at its built-in defaults (params.rs:23-34, 52-60, 189-196; main.rs:367-437, 598-607).
/// Integer widths follow the Rust fields; unsigned arithmetic saturates or wraps where Rust's does.
struct Params
{
  // streak ("vertical IM feature") filter, filter.rs
  std::uint32_t mz_half_width = 3;          ///< window [c - w, c + w] around each TOF index c, saturating
  std::size_t min_feature_length = 5;       ///< occupied scans a run needs; bridged empty scans do not count
  std::size_t max_internal_gap = 2;         ///< empty scans a run may bridge (a larger step breaks it)
  std::uint64_t min_window_intensity = 0;   ///< window sum a scan needs to count as occupied (and > 0)
  std::uint64_t min_feature_intensity = 0;  ///< window sum over the run's whole span
  std::size_t iterations = 2;               ///< passes, each over the previous survivors; 0 keeps every point
  // halo filter, halo.rs
  bool halo = true;
  double halo_peak_fraction = 0.15;         ///< keep iff I >= fraction * (max off-column I in the box)
  std::uint32_t halo_mz_idx_half_width = 80;
  std::size_t halo_scan_half_width = 2;
  // diaPASEF MS1 window gate, dia_ms1.rs + writer.rs:978-1021
  bool dia_ms1_window = true;
  double dia_ms1_mz_pad = 5.0;              ///< Da added on both sides of every isolation window
  double dia_ms1_im_pad = 0.05;             ///< 1/K0 added on both sides
};

/// What timsrust 0.4.2's MetadataReader reads for the gate: GlobalMetadata values exactly as stored (TEXT,
/// unparsed -- the builder parses them the way Rust does; std::nullopt for an absent key), and
/// SELECT MAX(NumScans) FROM Frames over ALL frames, MS1 and MS2 alike.
struct RunMeta
{
  std::optional<std::string> acquisition_software;         ///< AcquisitionSoftware
  std::optional<std::string> mz_acq_range_lower;           ///< MzAcqRangeLower
  std::optional<std::string> mz_acq_range_upper;           ///< MzAcqRangeUpper
  std::optional<std::string> digitizer_num_samples;        ///< DigitizerNumSamples
  std::optional<std::string> one_over_k0_acq_range_lower;  ///< OneOverK0AcqRangeLower
  std::optional<std::string> one_over_k0_acq_range_upper;  ///< OneOverK0AcqRangeUpper
  std::uint32_t max_num_scans = 0;
};

/// One row of tdf/mod.rs:246-249, i.e. of
///   SELECT DISTINCT ScanNumBegin, ScanNumEnd, IsolationMz, IsolationWidth FROM DiaFrameMsMsWindows
///   WHERE IsolationMz IS NOT NULL AND IsolationWidth IS NOT NULL
/// No such table means no rows. DISTINCT does not change the union, so duplicates are harmless.
struct WindowRow
{
  std::int64_t scan_num_begin = 0;
  std::int64_t scan_num_end = 0;   ///< exclusive in the schema; dnoise converts it as if inclusive
  double isolation_mz = 0.0;
  double isolation_width = 0.0;
};

/// A padded isolation window as an inclusive integer (scan, TOF index) box (dia_ms1.rs TofScanBox).
struct GateBox
{
  std::uint32_t scan_lo = 0, scan_hi = 0, tof_lo = 0, tof_hi = 0;
};

/// The union of all padded windows as per-scan merged TOF intervals (dia_ms1.rs DiaMs1Gate). Immutable once
/// built, so one gate serves every thread.
class Ms1WindowGate
{
public:
  /// dia_ms1.rs:43-73. No gate without boxes or scans. A box with tof_hi < tof_lo is skipped; scan bounds are
  /// clamped onto the last scan; touching intervals (lo <= hi + 1) merge, which leaves membership unchanged.
  static std::optional<Ms1WindowGate> fromBoxes(const std::vector<GateBox>& boxes, std::uint32_t num_scans)
  {
    if (boxes.empty() || num_scans == 0) return std::nullopt;
    std::vector<std::vector<std::pair<std::uint32_t, std::uint32_t>>> per_scan(num_scans);
    for (const GateBox& b : boxes)
    {
      if (b.tof_hi < b.tof_lo) continue;
      const std::uint32_t lo = std::min(b.scan_lo, num_scans - 1), hi = std::min(b.scan_hi, num_scans - 1);
      for (std::uint32_t s = lo; s <= hi; ++s) per_scan[s].emplace_back(b.tof_lo, b.tof_hi);
    }
    Ms1WindowGate g;
    g.boxes_ = boxes;
    g.row_.assign(1, 0);
    for (auto& row : per_scan)
    {
      std::sort(row.begin(), row.end());
      for (const auto& iv : row)
      {
        const bool merge = g.iv_.size() > g.row_.back() &&
                           iv.first <= (g.iv_.back().second == std::numeric_limits<std::uint32_t>::max() ? g.iv_.back().second : g.iv_.back().second + 1);
        if (merge) g.iv_.back().second = std::max(g.iv_.back().second, iv.second);
        else g.iv_.push_back(iv);
      }
      g.row_.push_back(g.iv_.size());
    }
    return g;
  }

  /// dia_ms1.rs:76-84: inside some window; a scan past the run's last scan is outside.
  bool contains(std::uint32_t scan, std::uint32_t tof) const
  {
    if (scan >= numScans()) return false;
    const auto b = iv_.begin() + static_cast<std::ptrdiff_t>(row_[scan]);
    const auto e = iv_.begin() + static_cast<std::ptrdiff_t>(row_[scan + 1]);
    const auto it = std::partition_point(b, e, [tof](const std::pair<std::uint32_t, std::uint32_t>& iv) { return iv.second < tof; });
    return it != e && tof >= it->first;
  }

  std::uint32_t numScans() const { return static_cast<std::uint32_t>(row_.size() - 1); }
  /// The padded boxes in window-row order, before the per-scan clamp and merge (for logging and tests).
  const std::vector<GateBox>& boxes() const { return boxes_; }

private:
  Ms1WindowGate() = default;
  std::vector<GateBox> boxes_;
  std::vector<std::size_t> row_;                                ///< intervals of scan s: [row_[s], row_[s + 1])
  std::vector<std::pair<std::uint32_t, std::uint32_t>> iv_;     ///< inclusive [tof_lo, tof_hi], sorted per scan
};

namespace detail
{
/// Rust's `f as u32`: saturating, NaN -> 0.
inline std::uint32_t asU32(double v)
{
  if (!(v > 0.0)) return 0;
  if (v >= 4294967296.0) return std::numeric_limits<std::uint32_t>::max();
  return static_cast<std::uint32_t>(v);
}

/// `str::parse::<u32>()`: one optional '+', then decimal digits, no overflow, nothing else.
inline bool parseU32(const std::string& s, std::uint32_t& out)
{
  const char* b = s.data();
  const char* const e = b + s.size();
  if (b != e && *b == '+') ++b;
  if (b == e || *b < '0' || *b > '9') return false;
  const auto r = std::from_chars(b, e, out);
  return r.ec == std::errc() && r.ptr == e;
}

/// `str::parse::<f64>()` for finite values: Rust's grammar [+-]? (d+ | d+.d* | d*.d+) ([eE][+-]?d+)?, no
/// whitespace, correctly rounded, locale-independent (a Qt application may have set a decimal-comma C locale).
/// inf, nan and out-of-range literals, which Rust accepts, are refused: a gate calibrated from them is noise.
inline bool parseF64(const std::string& s, double& out)
{
  std::size_t i = 0;
  if (i < s.size() && (s[i] == '+' || s[i] == '-')) ++i;
  const std::size_t start = i;
  auto digits = [&s, &i]() { std::size_t k = 0; for (; i < s.size() && s[i] >= '0' && s[i] <= '9'; ++i) ++k; return k; };
  std::size_t mantissa = digits();
  if (i < s.size() && s[i] == '.') { ++i; mantissa += digits(); }
  if (mantissa == 0) return false;
  if (i < s.size() && (s[i] == 'e' || s[i] == 'E'))
  {
    ++i;
    if (i < s.size() && (s[i] == '+' || s[i] == '-')) ++i;
    if (digits() == 0) return false;
  }
  if (i != s.size()) return false;
  const std::string body = (s[0] == '-' ? "-" : "") + s.substr(start);   // from_chars takes no '+'
  double v = 0.0;
#if defined(__cpp_lib_to_chars)
  const auto r = std::from_chars(body.data(), body.data() + body.size(), v);
  if (r.ec != std::errc() || r.ptr != body.data() + body.size()) return false;
#else
  // libc++ does not define __cpp_lib_to_chars: its floating-point from_chars is recent and availability-gated
  // (macOS 26). Its num_get converts through strtod_l in the C locale, which is correctly rounded; the grammar
  // is already checked, so the stream only converts, and an out-of-range value sets failbit.
  std::istringstream in(body);
  in.imbue(std::locale::classic());
  in >> v;
  if (in.fail()) return false;
#endif
  if (!std::isfinite(v)) return false;
  out = v;
  return true;
}
} // namespace detail

/// buildMs1WindowGate's result.
struct GateBuild
{
  std::optional<Ms1WindowGate> gate;  ///< no value: this run has no gate (not requested, no usable window rows, no scans)
  std::string error;                  ///< non-empty: dnoise refuses the run here (timsrust MetadataReader error)
};

// Contraction off for everything the gate builder computes (point 6 at the top). Clang attaches its pragma to each
// operation, so it survives inlining, but an explicit -ffp-contract=fast overrides it -- hence also the volatile in
// the builder. GCC applies the optimize pragma to every function defined before pop_options.
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC push_options
#pragma GCC optimize("fp-contract=off")
#endif

/// The run's diaPASEF MS1 window gate, exactly as dnoise v0.1.0 builds it once per run (writer.rs:978-1021 with
/// timsrust 0.4.2 metadata_reader.rs:59-102, tof_to_mz.rs, scan_to_im.rs), in the Rust evaluation order.
inline GateBuild buildMs1WindowGate(const RunMeta& meta, const std::vector<WindowRow>& rows, const Params& p)
{
#if defined(__clang__)
  #pragma clang fp contract(off)
#endif
  GateBuild out;
  if (!p.dia_ms1_window) return out;
  // tdf/mod.rs:251-252 cast with `i64 as u32` (wrapping); :265 drops ScanNumEnd <= ScanNumBegin.
  std::vector<WindowRow> usable;
  for (const WindowRow& r : rows)
    if (static_cast<std::uint32_t>(r.scan_num_end) > static_cast<std::uint32_t>(r.scan_num_begin)) usable.push_back(r);
  if (usable.empty()) return out;   // writer.rs:984-986: no gate, and the metadata is never read

  auto number = [&out](const std::optional<std::string>& v, const char* key, double& x) {
    if (!v) out.error = std::string("GlobalMetadata has no ") + key;
    else if (!detail::parseF64(*v, x)) out.error = std::string("GlobalMetadata ") + key + " '" + *v + "' is not a finite number";
    return out.error.empty();
  };
  double mz_min = 0.0, mz_max = 0.0, im_min = 0.0, im_max = 0.0;
  std::uint32_t tof_max_index = 0;
  if (!meta.acquisition_software) { out.error = "GlobalMetadata has no AcquisitionSoftware"; return out; }
  if (!number(meta.mz_acq_range_lower, "MzAcqRangeLower", mz_min) || !number(meta.mz_acq_range_upper, "MzAcqRangeUpper", mz_max) ||
      !number(meta.one_over_k0_acq_range_lower, "OneOverK0AcqRangeLower", im_min) ||
      !number(meta.one_over_k0_acq_range_upper, "OneOverK0AcqRangeUpper", im_max))
    return out;
  if (!meta.digitizer_num_samples || !detail::parseU32(*meta.digitizer_num_samples, tof_max_index))
  {
    out.error = "GlobalMetadata DigitizerNumSamples '" + meta.digitizer_num_samples.value_or("") + "' is missing or not a u32";
    return out;
  }
  if (*meta.acquisition_software == "Bruker otofControl") { mz_min -= 5.0; mz_max += 5.0; }   // metadata_reader.rs:67-70
  if (meta.max_num_scans == 0) return out;                                                     // writer.rs:988-991
  const std::uint32_t num_scans = meta.max_num_scans;

  const double tof_intercept = std::sqrt(mz_min);                                              // Tof2MzConverter::from_boundaries
  const double tof_slope = (std::sqrt(mz_max) - tof_intercept) / static_cast<double>(tof_max_index);
  const double scan_intercept = im_max;                                                        // Scan2ImConverter::from_boundaries
  const double scan_slope = (im_min - scan_intercept) / static_cast<double>(num_scans);
  std::vector<GateBox> boxes;
  for (const WindowRow& r : usable)
  {
    const double mz_lo = r.isolation_mz - r.isolation_width / 2.0;                            // tdf/mod.rs:258-259
    const double mz_hi = r.isolation_mz + r.isolation_width / 2.0;
    const double t0 = (std::sqrt(mz_lo - p.dia_ms1_mz_pad) - tof_intercept) / tof_slope;       // Tof2MzConverter::invert
    const double t1 = (std::sqrt(mz_hi + p.dia_ms1_mz_pad) - tof_intercept) / tof_slope;
    GateBox b;
    b.tof_lo = detail::asU32(std::fmax(std::floor(std::fmin(t0, t1)), 0.0));                  // f64::min/max ignore NaN, as fmin/fmax
    b.tof_hi = detail::asU32(std::fmax(std::ceil(std::fmax(t1, t0)), 0.0));
    // Scan2ImConverter::convert as two separate IEEE operations; the binary matches only the unfused result. The
    // product passes through a volatile, a barrier no optimiser can fuse across: clang does not honour its pragma
    // under an explicit -ffp-contract=fast.
    volatile double scaled0 = scan_slope * static_cast<double>(static_cast<std::uint32_t>(r.scan_num_begin));
    volatile double scaled1 = scan_slope * static_cast<double>(static_cast<std::uint32_t>(r.scan_num_end));
    const double im0 = scan_intercept + scaled0;
    const double im1 = scan_intercept + scaled1;
    const double s0 = (std::fmax(im0, im1) + p.dia_ms1_im_pad - scan_intercept) / scan_slope;  // Scan2ImConverter::invert
    const double s1 = (std::fmin(im0, im1) - p.dia_ms1_im_pad - scan_intercept) / scan_slope;
    b.scan_lo = detail::asU32(std::fmax(std::floor(std::fmin(s0, s1)), 0.0));
    b.scan_hi = std::min(detail::asU32(std::fmax(std::ceil(std::fmax(s0, s1)), 0.0)), num_scans - 1);
    boxes.push_back(b);
  }
  out.gate = Ms1WindowGate::fromBoxes(boxes, num_scans);
  return out;
}

#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC pop_options
#endif

/// Points left after each stage of one frame, for logging.
struct FrameCounts
{
  std::uint64_t raw = 0;
  std::uint64_t after_streak = 0;
  std::uint64_t after_halo = 0;   ///< == after_streak with the halo off
  std::uint64_t kept = 0;         ///< after the window gate; == after_halo without one
};

/// Working memory of denoiseMs1Frame, one per thread, reused so a thread's frames do not reallocate.
/// Its contents between calls mean nothing.
struct Scratch
{
  std::vector<std::uint32_t> idx, idx2;             ///< radix sort by TOF
  std::vector<std::uint32_t> tof, scan, inten, id;  ///< live points in TOF order; id = input position
  std::vector<std::uint8_t> mark;
  std::vector<std::uint64_t> sum;                   ///< per-scan window sums, valid where stamp == the window
  std::vector<std::uint32_t> stamp;
  std::vector<std::uint32_t> touched;
  std::vector<std::pair<std::uint32_t, std::uint32_t>> spans;
  std::vector<std::size_t> row, cursor;             ///< halo: survivors of scan s at [row[s], row[s + 1])
  std::vector<std::uint32_t> htof, hinten, hpos;
};

namespace detail
{
/// Drop the live points (TOF-ordered arrays of @p w) whose mark is 0; returns how many remain.
inline std::size_t compact(Scratch& w, std::size_t m)
{
  std::size_t k = 0;
  for (std::size_t j = 0; j < m; ++j)
    if (w.mark[j])
    {
      w.tof[k] = w.tof[j]; w.scan[k] = w.scan[j]; w.inten[k] = w.inten[j]; w.id[k] = w.id[j];
      ++k;
    }
  return k;
}

/// One streak pass (filter.rs:14-129) over the first @p m live points; returns the survivors left in place.
inline std::size_t streakPass(Scratch& w, std::size_t m, std::size_t num_scans, const Params& p)
{
  const std::uint32_t* const t = w.tof.data();
  const std::uint32_t* const s = w.scan.data();
  const std::uint32_t* const v = w.inten.data();
  const std::uint32_t hw = p.mz_half_width, u32max = std::numeric_limits<std::uint32_t>::max();
  w.mark.assign(m, 0);
  w.stamp.assign(num_scans, 0);
  w.sum.resize(num_scans);
  std::uint32_t window = 0;   // at most one window per live point, and m < 2^32
  std::size_t lo = 0, hi = 0;
  for (std::size_t k = 0; k < m;)
  {
    const std::uint32_t c = t[k];
    std::size_t kb = k + 1;
    while (kb < m && t[kb] == c) ++kb;   // the block of points at TOF c; only these are decided here
    // [c - w, c + w], saturating (filter.rs:48-51). Both ends only grow with c, so two pointers replace the
    // binary searches.
    const std::uint32_t lo_val = c >= hw ? c - hw : 0, hi_val = c <= u32max - hw ? c + hw : u32max;
    while (t[lo] < lo_val) ++lo;
    while (hi < m && t[hi] <= hi_val) ++hi;
    ++window;
    w.touched.clear();
    for (std::size_t j = lo; j < hi; ++j)
    {
      const std::uint32_t sc = s[j];
      if (w.stamp[sc] != window) { w.stamp[sc] = window; w.sum[sc] = 0; w.touched.push_back(sc); }
      w.sum[sc] += v[j];
    }
    auto occupied = [&w, &p](std::uint32_t sc) { return w.sum[sc] > 0 && w.sum[sc] >= p.min_window_intensity; };
    std::size_t n_occupied = 0;
    for (const std::uint32_t sc : w.touched) n_occupied += occupied(sc);
    // A run holds at most every occupied scan of the window, so fewer than min_feature_length accept nothing.
    if (n_occupied != 0 && n_occupied >= p.min_feature_length)
    {
      std::sort(w.touched.begin(), w.touched.end());
      w.spans.clear();
      std::size_t first = 0, last = 0, count = 0;   // positions in touched of the open run's first/last occupied scan
      auto close = [&]() {
        if (count < p.min_feature_length) return;   // occupied scans, not the span (filter.rs:86-92)
        if (p.min_feature_intensity > 0)            // the span's sum, sub-floor scans included (filter.rs:93-96)
        {
          std::uint64_t total = 0;
          for (std::size_t q = first; q <= last; ++q) total += w.sum[w.touched[q]];
          if (total < p.min_feature_intensity) return;
        }
        w.spans.emplace_back(w.touched[first], w.touched[last]);
      };
      bool open = false;
      for (std::size_t q = 0; q < w.touched.size(); ++q)
      {
        if (!occupied(w.touched[q])) continue;
        if (open && static_cast<std::size_t>(w.touched[q] - w.touched[last]) > p.max_internal_gap + 1) { close(); open = false; }
        if (!open) { open = true; first = q; count = 0; }
        last = q;
        ++count;
      }
      if (open) close();
      if (!w.spans.empty())
        for (std::size_t j = k; j < kb; ++j)   // kept iff the scan lies in an accepted run's span (filter.rs:108-118)
        {
          const std::uint32_t sc = s[j];
          const auto sp = std::partition_point(w.spans.begin(), w.spans.end(),
                                               [sc](const std::pair<std::uint32_t, std::uint32_t>& r) { return r.second < sc; });
          if (sp != w.spans.end() && sc >= sp->first) w.mark[j] = 1;
        }
    }
    k = kb;
  }
  return compact(w, m);
}
} // namespace detail

/// dnoise v0.1.0's default MS1 denoising of ONE frame (writer.rs:838-853). Inputs are the frame's points in any
/// order: 0-based scan index (< @p num_scans, the frame's NumScans), TOF index, and RAW blob intensity. @p gate is
/// the run's buildMs1WindowGate() result, or nullptr for none. On return keep[i] == 1 iff dnoise keeps point i.
/// A pure function of its inputs: @p w is working memory only, so any thread may process any frame.
/// Throws std::invalid_argument for a scan index >= num_scans (dnoise panics there) or more than 2^32-1 points.
inline FrameCounts denoiseMs1Frame(const std::uint32_t* scan, const std::uint32_t* tof, const std::uint32_t* intensity,
                                   std::size_t n, std::size_t num_scans, const Params& p, const Ms1WindowGate* gate,
                                   Scratch& w, std::vector<std::uint8_t>& keep)
{
  FrameCounts c;
  c.raw = n;
  keep.assign(n, 0);
  if (n == 0) return c;
  if (n > std::numeric_limits<std::uint32_t>::max()) throw std::invalid_argument("dnoise: more than 2^32-1 points in one frame");
  std::uint32_t max_tof = 0;
  for (std::size_t i = 0; i < n; ++i)
  {
    if (scan[i] >= num_scans)
      throw std::invalid_argument("dnoise: scan index " + std::to_string(scan[i]) + " outside a frame of " + std::to_string(num_scans) + " scans");
    max_tof = std::max(max_tof, tof[i]);
  }

  // Points in TOF order (stable LSD radix sort, 11-bit digits); set semantics make the tie order irrelevant.
  w.idx.resize(n);
  w.idx2.resize(n);
  for (std::size_t i = 0; i < n; ++i) w.idx[i] = static_cast<std::uint32_t>(i);
  for (unsigned shift = 0; shift < 32 && (shift == 0 || (max_tof >> shift) != 0); shift += 11)
  {
    std::array<std::size_t, 2049> start{};
    for (std::size_t k = 0; k < n; ++k) ++start[((tof[w.idx[k]] >> shift) & 2047u) + 1];
    for (std::size_t d = 0; d < 2048; ++d) start[d + 1] += start[d];
    for (std::size_t k = 0; k < n; ++k) w.idx2[start[(tof[w.idx[k]] >> shift) & 2047u]++] = w.idx[k];
    w.idx.swap(w.idx2);
  }
  w.id.swap(w.idx);
  w.tof.resize(n);
  w.scan.resize(n);
  w.inten.resize(n);
  for (std::size_t k = 0; k < n; ++k)
  {
    const std::uint32_t i = w.id[k];
    w.tof[k] = tof[i]; w.scan[k] = scan[i]; w.inten[k] = intensity[i];
  }

  // 1. Streak filter (filter.rs:133-165). A pass that removes nothing is a fixed point: every further pass
  //    would see the same input, so stopping there is exact.
  std::size_t m = n;
  for (std::size_t pass = 0; pass < p.iterations && m > 0; ++pass)
  {
    const std::size_t before = m;
    m = detail::streakPass(w, m, num_scans, p);
    if (m == before) break;
  }
  c.after_streak = m;

  // 2. Halo (halo.rs:24-101), once, with the streak survivors as both the points judged and the reference;
  //    simultaneous, so a point it drops still counts as a neighbour's reference.
  if (p.halo && m > 0)
  {
    w.row.assign(num_scans + 1, 0);
    for (std::size_t j = 0; j < m; ++j) ++w.row[w.scan[j] + 1];
    for (std::size_t r = 0; r < num_scans; ++r) w.row[r + 1] += w.row[r];
    w.cursor.assign(w.row.begin(), w.row.end() - 1);
    w.htof.resize(m);
    w.hinten.resize(m);
    w.hpos.resize(m);
    for (std::size_t j = 0; j < m; ++j)   // stable by scan over TOF order: (scan, TOF) order
    {
      const std::size_t d = w.cursor[w.scan[j]]++;
      w.htof[d] = w.tof[j]; w.hinten[d] = w.inten[j]; w.hpos[d] = static_cast<std::uint32_t>(j);
    }
    w.mark.assign(m, 0);
    const std::size_t sw = p.halo_scan_half_width;
    const std::uint32_t mw = p.halo_mz_idx_half_width, u32max = std::numeric_limits<std::uint32_t>::max();
    const std::uint32_t* const ht = w.htof.data();
    for (std::size_t r = 0; r < num_scans; ++r)
      for (std::size_t i = w.row[r]; i < w.row[r + 1]; ++i)
      {
        const std::uint32_t ti = ht[i];
        const std::size_t v_lo = r >= sw ? r - sw : 0, v_hi = sw >= num_scans - 1 - r ? num_scans - 1 : r + sw;
        const std::uint32_t t_lo = ti >= mw ? ti - mw : 0, t_hi = ti <= u32max - mw ? ti + mw : u32max;
        std::uint32_t best = 0;
        for (std::size_t vs = v_lo; vs <= v_hi; ++vs)
        {
          const std::uint32_t* const e = ht + w.row[vs + 1];
          for (const std::uint32_t* q = std::lower_bound(ht + w.row[vs], e, t_lo); q != e && *q <= t_hi; ++q)
            if (*q != ti && w.hinten[static_cast<std::size_t>(q - ht)] > best) best = w.hinten[static_cast<std::size_t>(q - ht)];
        }
        // The Rust double compare, verbatim: no addition, so nothing to contract; best == 0 keeps.
        if (static_cast<double>(w.hinten[i]) >= p.halo_peak_fraction * static_cast<double>(best)) w.mark[w.hpos[i]] = 1;
      }
    m = detail::compact(w, m);
  }
  c.after_halo = m;

  // 3. The window gate, ANDed per point (writer.rs:846-853).
  for (std::size_t j = 0; j < m; ++j)
    if (gate == nullptr || gate->contains(w.scan[j], w.tof[j]))
    {
      keep[w.id[j]] = 1;
      ++c.kept;
    }
  return c;
}

} // namespace spx::dnoise

#endif // SPEXTRACTOR_DNOISE_MS1_H
```
