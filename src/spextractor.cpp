// Copyright (c) 2002-present, OpenMS Inc. -- EKU Tuebingen, ETH Zurich, and FU Berlin
// SPDX-License-Identifier: BSD-3-Clause
//
// --------------------------------------------------------------------------
// $Maintainer: $
// $Authors: OpenMS-the reference implementation project $
// --------------------------------------------------------------------------

#include "MzPeakStreamLoad.h"   // [mzpeak] streaming .mzpeak input (SPEXTRACTOR_WITH_MZPEAK)
#include <OpenMS/APPLICATIONS/TOPPBase.h>

#include <OpenMS/FORMAT/FileHandler.h>
#include <sys/resource.h>
#include <OpenMS/FORMAT/BrukerTimsFile.h>
#include <OpenMS/FORMAT/DATAACCESS/SwathFileConsumer.h>
#include <OpenMS/KERNEL/MSExperiment.h>
#include <OpenMS/KERNEL/MassTrace.h>
#include <OpenMS/FEATUREFINDER/MassTraceDetection.h>
#include <unordered_map>
#include <cstring>
// spextractor::TdfMzCalibration comes from <OpenMS/FORMAT/TdfMzCalibration.h>, installed by the
// OpenMS patch and already included via the mzPeak loader; including the in-tree copy as well
// redefines the struct.
#include <OpenMS/FORMAT/TdfMzCalibration.h>
#include "TdfLoad.h"   // loadTdfCalibration: sqlite3, tool-only
#include <OpenMS/FEATUREFINDER/ElutionPeakDetection.h>
#include <OpenMS/PROCESSING/CENTROIDING/PeakPickerIM.h>
#include <OpenMS/IONMOBILITY/IMTypes.h>
#include <OpenMS/CONCEPT/Constants.h>
#include <OpenMS/CONCEPT/VersionInfo.h>   // verboseVersion_ carries the OpenMS build alongside ours

#include <algorithm>
#include <cmath>
#include <chrono>
#include <cassert>
#include <type_traits>
#include <array>
#include <functional>
#include <cstdio>
#include <fstream>
#include <atomic>
#include <thread>
#include <map>
#include <string>
#include <vector>
#include <cstdlib>     // getenv
#include <cstring>     // memcpy
#ifdef __GLIBC__
#include <malloc.h>    // mallinfo2: retained-vs-live at the milestones [mem]
#endif

// The four OpenMS patches in patches/ are build prerequisites. This is the compile-time check for the
// third: without defaulted moves an rvalue MassTrace binds to the copy constructor (not noexcept), and
// every "move" of a trace in the band/split gathering is a deep copy of its points.
static_assert(std::is_nothrow_move_constructible_v<OpenMS::MassTrace> && std::is_nothrow_move_assignable_v<OpenMS::MassTrace>,
              "OpenMS MassTrace has no noexcept move operations: apply patches/openms-masstrace-move.patch to the OpenMS tree");
#include <exception>   // exception_ptr
#ifdef _OPENMP
#include <omp.h>
#endif

// The release version. The standalone CMake build passes it from project(VERSION); the in-tree
// OpenMS build does not, so the fallback here is the same number.
#ifndef SPEXTRACTOR_VERSION
#define SPEXTRACTOR_VERSION "2.0.0"
#endif

using namespace OpenMS;
using namespace std;

//-------------------------------------------------------------
// Doxygen docu
//-------------------------------------------------------------

/**
  @page TOPP_SpeXtractor SpeXtractor

  @brief Extracts pseudo-MS/MS ("pseudo-DDA") spectra from diaPASEF (ion-mobility DIA) data.

  Reconstructs DDA-like MS2 spectra from ion-mobility DIA (timsTOF / diaPASEF) data by
  exploiting the fact that, in PASEF, fragments are recorded at the ion-mobility (1/K0)
  elution coordinate of their precursor. Precursor and fragment mass traces are detected
  IM-aware (@ref MassTraceDetection with an ion-mobility tolerance), then fragments are
  assigned to a precursor when they co-localize in ion mobility, retention time, and
  elution-profile (Pearson) correlation. The result is written as searchable mzML.

  This is an OpenMS-native, BSD-3 analogue of the published diaPASEF pseudo-MS/MS extractors. It is
  a discovery front-end (enables open / semi-tryptic / PTM searches); it does not perform the database
  search, FDR, library building or quantification.

  See docs/BASELINE.md for the measured decisions behind every default.

  <B>The command line parameters of this tool are:</B>
  @verbinclude TOPP_SpeXtractor.cli
  <B>INI file documentation of this tool:</B>
  @htmlinclude TOPP_SpeXtractor.html
*/

/// @cond TOPPCLASSES

namespace
{
  /// A detected mass trace reduced to the quantities we correlate/gate on.
  /// Current + peak resident set, read from /proc/self/status (Linux). Logged at phase boundaries so
  /// the memory peak is MEASURED rather than estimated: it tells us whether the peak sits in the
  /// raw-load phase or in the parallel per-window phase. Returns "" where unsupported. [mem]
  /// seconds since tool start, for per-phase bottleneck attribution [perf]
  static double phase_clock_()
  {
    static const auto t0 = std::chrono::steady_clock::now();
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  }
  static std::string clk_() { char b[32]; snprintf(b, sizeof b, " [t=%.0fs]", phase_clock_()); return b; }

  /// [perf-instr] Per-phase wall/CPU/RSS accounting. Sparse [t=..] markers left ~53% of wall time
  /// unattributed, which is how you optimise the wrong thing. Every phase is timed; the table is
  /// printed unconditionally at the end so a benchmark log always says where the time went.
  struct PhaseStat { double wall = 0; double cpu = 0; long rss_end_mb = 0; int n = 0; };
  inline double& flush_wall_() { static double v = 0; return v; }   // [perf-load] pick inside LOAD
  inline std::map<std::string, PhaseStat>& phase_stats_()
  { static std::map<std::string, PhaseStat> m; return m; }
  inline std::vector<std::string>& phase_order_()
  { static std::vector<std::string> v; return v; }
  static double cpu_seconds_()
  {
    struct rusage ru;                       // RUSAGE_SELF sums ALL threads -> parallel efficiency
    if (getrusage(RUSAGE_SELF, &ru) != 0) return 0.0;
    return ru.ru_utime.tv_sec + ru.ru_utime.tv_usec * 1e-6
         + ru.ru_stime.tv_sec + ru.ru_stime.tv_usec * 1e-6;
  }
  static long rss_mb_()
  {
    std::ifstream f("/proc/self/status"); std::string k;   // deliberate: Linux-only, returns 0 elsewhere
    while (f >> k) { if (k == "VmRSS:") { long v; f >> v; return v / 1024; } f.ignore(1 << 20, '\n'); }
    return 0;
  }
  struct Phase
  {
    std::string name; double w0, c0;
    explicit Phase(std::string n) : name(std::move(n)), w0(phase_clock_()), c0(cpu_seconds_()) {}
    ~Phase()
    {
      auto& st = phase_stats_()[name];
      if (st.n == 0) phase_order_().push_back(name);
      st.wall += phase_clock_() - w0; st.cpu += cpu_seconds_() - c0;
      st.rss_end_mb = rss_mb_(); ++st.n;
    }
  };
  static void report_phases_(double total_wall)
  {
    if (phase_order_().empty()) return;
    OPENMS_LOG_INFO << "\n[perf] phase breakdown (wall s | % of total | CPU s | par x | RSS MB at end)\n";
    double acc = 0;
    for (const auto& n : phase_order_())
    {
      const auto& p = phase_stats_()[n];
      acc += p.wall;
      char b[220];
      snprintf(b, sizeof b, "[perf] %-22s %8.1f  %5.1f%%  %9.1f  %5.1fx  %8ld%s\n", n.c_str(), p.wall,
               total_wall > 0 ? 100.0 * p.wall / total_wall : 0.0, p.cpu,
               p.wall > 0 ? p.cpu / p.wall : 0.0, p.rss_end_mb, p.n > 1 ? "  (summed)" : "");
      OPENMS_LOG_INFO << b;
    }
    char b[160];
    snprintf(b, sizeof b, "[perf] %-22s %8.1f  %5.1f%%  (unattributed %.1f s)\n", "TOTAL(measured)", acc,
             total_wall > 0 ? 100.0 * acc / total_wall : 0.0, total_wall - acc);
    OPENMS_LOG_INFO << b;
  }

  bool log_overlap_ = false;   ///< [B0] gate:coelution == "logoverlap"
  double im_weight_sigma_ = 0.0;     ///< [recall] Gaussian IM-proximity weight on emitted fragment intensity (0=off)
  double mono_guard_ = 0.0;          ///< [mono-guard] averagine slack on leftward isotope steps (0=off)
  bool mono_select_ = false;         ///< [mono-select] pick the mono by averagine fit over the isotope run
  std::atomic<long long> stat_slice_{0};    ///< fragments VISITED by the IM slice
  std::atomic<long long> stat_rtpass_{0};   ///< of those, how many pass the RT gate
  std::atomic<long long> stat_prec_{0};     ///< precursors scored
  bool var_support_ = false;         ///< [Q1] Pearson variance over union support, not full grid G (0-pad fix)
  double corr_power_ = 0.0;          ///< [Q2] emitted fragment intensity *= corr^corr_power (0=off; engine-agnostic)

  /// glibc arena accounting at a milestone: what the allocator holds in arenas vs mmapped blocks
  /// and how much of it is free-but-retained. RSS alone cannot tell live data from retained pages.
  static std::string mem_()
  {
#ifdef __GLIBC__
    const struct mallinfo2 mi = mallinfo2();
    return " [malloc arena=" + std::to_string(mi.arena >> 20) + " MB mmap=" + std::to_string(mi.hblkhd >> 20)
         + " MB free=" + std::to_string(mi.fordblks >> 20) + " MB]";
#else
    return "";
#endif
  }
  static std::string rss_()
  {
    std::ifstream st("/proc/self/status");
    if (!st) return "";
    std::string line, cur = "?", peak = "?";
    while (std::getline(st, line))
    {
      auto val = [&line]() {
        std::string v = line.substr(line.find(':') + 1);
        size_t a = v.find_first_not_of(" \t");
        return a == std::string::npos ? std::string("?") : v.substr(a);
      };
      if (line.rfind("VmRSS:", 0) == 0) cur = val();
      else if (line.rfind("VmHWM:", 0) == 0) peak = val();
    }
    return " [RSS " + cur + ", peak " + peak + "]";
  }

  /// [dyn-mem] Bytes we may still allocate. MemAvailable is the kernel's own estimate of what
  /// can be handed out without swapping (it accounts for reclaimable page cache), which is the
  /// right quantity on a SHARED node -- MemFree would ignore cache and MemTotal would ignore
  /// the other users. Returns 0 if unreadable, which the caller treats as "admit one at a time".
  ///
  /// It does NOT add our own RSS back any more. That was defensible when most of our resident set
  /// was allocator memory we would reuse; with perf:malloc_trim returning it at the phase boundary
  /// (measured 92 GB of 138 at the loop start), what remains resident during the loop is the
  /// windows actually in flight -- memory that is spoken for, not budget. Counting it as available
  /// double-booked exactly the bytes the gate exists to bound. [2026-09-06]
  static size_t availableBytes_()
  {
    std::ifstream mi("/proc/meminfo");
    if (!mi) return 0;
    std::string line;
    size_t avail_kb = 0;
    while (std::getline(mi, line))
      if (line.rfind("MemAvailable:", 0) == 0)
      { avail_kb = strtoull(line.c_str() + 13, nullptr, 10); break; }
    if (!avail_kb) return 0;

    return avail_kb * 1024ull;
  }

  /// THE RT AXIS IS GLOBAL AND DISCRETE. Every acquired frame has one retention time, and every
  /// point of every mass trace sits on one of those frames -- so an RT value never needs to be
  /// stored per point. It used to be: `vector<pair<double,double>>` cost 16 B per point and
  /// duplicated the same ~33,000 values across hundreds of millions of points, and aligning two
  /// profiles meant a binary search per point because the values had to be compared numerically.
  /// Here the axis is stored ONCE, a point is (frame index, intensity) at 8 B, and alignment is
  /// integer equality. Built once after loading, read-only thereafter.
  inline vector<double>& rtAxis() { static vector<double> v; return v; }

  /// Frame index of an RT. Used only while BUILDING traces: the value comes from a frame, so the
  /// match is exact, and the nearest-neighbour fallback only guards a last-ulp difference.
  inline uint32_t rtIndex(double rt)
  {
    const vector<double>& a = rtAxis();
    if (a.empty()) return 0;
    auto it = lower_bound(a.begin(), a.end(), rt);
    if (it == a.end()) return (uint32_t)(a.size() - 1);
    if (it != a.begin() && (*it - rt) > (rt - *(it - 1))) --it;
    return (uint32_t)(it - a.begin());
  }

  struct Trace
  {
    double mz = 0.0;
    double im = 0.0;   ///< centroid ion mobility (1/K0)
    /// The flight-time bin this trace was measured on, and the calibration factor of its apex
    /// frame. The pair is the AUTHORITATIVE m/z: `mz` below is a cached convenience for the gates
    /// that still compare in m/z space, and the value actually written out is recomputed from these
    /// two at export. 0 means the trace came from the OpenMS detector, which has no bin.
    uint32_t tof = 0;
    uint32_t bframe = 0;   ///< store-local frame whose factor calibrates `tof` (see bOf())
    /// THE PROFILE IS A SPAN, NOT A POINT LIST. A trace is contiguous in its window's frame
    /// sequence (with gaps the detector tolerates), so it needs an entry frame and its
    /// intensities -- not a frame per point and not a bin per point, which is what the three
    /// parallel vectors this replaces stored (12 B/point + 3 mallocs/trace, measured 35.6 GB).
    /// The intensities live in the owning TraceStore's arena at [off, off+len); ZERO MEANS
    /// MISSING, which is valid because every observed intensity is > noise_threshold >= 0.
    /// Every consumer walks REAL points in frame order (skipping zeros), so the floating-point
    /// sums are visited in the same order as before: the change is pure representation.
    /// `frame0` is LOCAL to the store's frame table (a window's, or the MS1 map's) -- a
    /// window's consecutive frames are ~13 apart on the global RT axis, so a global entry
    /// frame would not be contiguous.
    uint32_t frame0 = 0;   ///< first frame of the span, store-local
    uint32_t off = 0;      ///< offset of the span in the store's arena
    uint16_t len = 0;      ///< frames spanned (a gradient is ~1,400; asserted < 65536)
    uint16_t npts = 0;     ///< REAL points in the span
    uint16_t apex = 0;     ///< position of the apex within the span
    /// [soa-rt] THE RT IS AN INDEX, NOT A VALUE. Every producer of a Trace reports an RT that is
    /// one of the store's own frame times: the integer detector uses the apex frame's RT directly,
    /// and ElutionPeakDetection -- which runs on both MS1 and MS2 at the shipped defaults -- sets
    /// `centroid_rt_ = trace_peaks_[max_idx].getRT()` in updateSmoothedMaxRT(), i.e. one of the
    /// points it was given, whose RT this tool set from the frame table. So the 8-byte double was
    /// a cached copy of `frame_rt[frame0 + rt_at]`; storing the offset instead costs 2 bytes that
    /// were tail padding and takes the record from 48 to 40 -- 16 GiB on a 2-hour acquisition.
    /// Read it with rtOf(); never reconstruct it from `apex`, which is the RAW maximum and is a
    /// DIFFERENT frame from EPD's smoothed maximum.
    /// SIGNED: trimToSpan advances `frame0` by `lo` and this by -`lo`, so their SUM -- the
    /// absolute store frame -- is invariant under trimming. A trim can therefore move the span
    /// away from the frame EPD called the apex without changing the RT this trace reports.
    int16_t rt_at = 0;     ///< frame whose time is this trace's RT, relative to frame0 (see rtOf())
    size_t np() const { return npts; }
    size_t span() const { return len; }
    void freeProfile() { len = 0; npts = 0; }        ///< the arena is the store's; nothing to free
  };

  /// The frame table and the arenas that a set of traces point into: one per window, one for the
  /// MS1 map. `rt_index`/`b` are per FRAME (store-local index); `inten` holds every trace's span
  /// back to back (zero = missing); `bins` holds the per-frame flight-time bin for the integer
  /// path only and is freed once valley splitting has assigned each child its apex bin.
  struct TraceStore
  {
    vector<uint32_t> rt_index;   ///< frame -> global RT axis
    vector<double>   b;          ///< frame -> calibration factor (empty on the OpenMS path)
    vector<double>   frame_rt;   ///< frame -> RT value, for toTrace()'s frame lookup
    vector<float>    inten;      ///< arena of spans
    /// [bin-delta] A point's flight-time bin, stored as the SIGNED OFFSET from its trace's own
    /// bin (`Trace::tof`), not as the absolute bin. A mass trace is assembled within
    /// `trace:mass_error_ppm` of its seed, and one bin is 6.4 ppm at m/z 600 / 3.8 ppm at 1700, so
    /// the offsets a real trace produces are single digits; int16 leaves ~30,000 bins of headroom
    /// and the writer throws rather than truncate. Absolute bins needed 32 bits for a 19-bit
    /// quantity: 2 B x 5.2e9 arena slots on a 2-hour acquisition.
    /// Reconstruct with `t.tof + bins[t.off + k]` -- and note that reproduces the old sentinel
    /// exactly: a point whose absolute bin was 0 still reconstructs to 0, and a trace from a
    /// binless source has `tof == 0` so its zero-filled slots still reconstruct to 0.
    vector<int16_t> bins;        ///< arena of per-frame bin OFFSETS (integer path, until EPD)
    size_t frames() const { return rt_index.size(); }
    void setFrames(const vector<uint32_t>& ri, const vector<double>* bb)
    {
      rt_index = ri; if (bb) b = *bb; else b.clear();
      frame_rt.resize(ri.size());
      for (size_t f = 0; f < ri.size(); ++f) frame_rt[f] = rtAxis()[ri[f]];
    }
    /// Store-local frame of an RT value (exact by construction; nearest guards a last-ulp slip).
    uint32_t frameOf(double rt) const
    {
      auto it = lower_bound(frame_rt.begin(), frame_rt.end(), rt);
      if (it == frame_rt.end()) return (uint32_t)(frame_rt.size() - 1);
      if (it != frame_rt.begin() && (*it - rt) > (rt - *(it - 1))) --it;
      return (uint32_t)(it - frame_rt.begin());
    }
    /// Append `other`'s arenas and return the offset they now start at (for rebasing).
    uint32_t absorb(TraceStore& other)
    {
      const size_t base = inten.size();
      if (base + other.inten.size() >= (size_t)std::numeric_limits<uint32_t>::max())
        throw OpenMS::Exception::OutOfRange(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
      inten.insert(inten.end(), other.inten.begin(), other.inten.end());
      if (!other.bins.empty()) { bins.resize(base, 0); bins.insert(bins.end(), other.bins.begin(), other.bins.end()); }
      // Once ANY source has contributed bins, keep bins index-parallel to inten: a later binless
      // source would otherwise leave bins short, and a bins[t.off + k] read would run off the end.
      // No current caller mixes the two, which is exactly why this is worth pinning down here.
      else if (!bins.empty()) bins.resize(inten.size(), 0);
      vector<float>().swap(other.inten); vector<int16_t>().swap(other.bins);
      return (uint32_t)base;
    }
  };
  static_assert(sizeof(Trace) == 40, "Trace must stay 40 bytes: it is the largest structure in the tool "
                                    "(2.1e9 records on a 2-h file), and a silent 8-byte regrowth costs ~16 GiB");

  /// Span accessors take the owning store EXPLICITLY. Every trace of a vector shares one store, so
  /// a per-record 8-byte back-pointer bought nothing but 8 bytes x 2.1e9 records on a 2-h file.
  /// The store is an argument, not a member: passing the wrong one is the failure mode this
  /// replaces, so it is asserted in a debug build rather than left to a silent wrong-arena read.
  inline float xv(const TraceStore& s, const Trace& t, size_t k)
  { assert(t.off + k < s.inten.size()); return s.inten[t.off + k]; }
  inline bool real(const TraceStore& s, const Trace& t, size_t k) { return xv(s, t, k) > 0.0f; }
  inline uint32_t gframe(const TraceStore& s, const Trace& t, size_t k)
  { assert(t.frame0 + k < s.rt_index.size()); return s.rt_index[t.frame0 + k]; }
  inline double rtAtSpan(const TraceStore& s, const Trace& t, size_t k) { return rtAxis()[gframe(s, t, k)]; }
  /// [soa-rt] The trace's reported RT. `frame_rt` is one double per frame of the owning store
  /// (~38 KB for a window), so this is a single load from a table that stays hot, against the
  /// 8 bytes per record it replaces. Identical by construction: frame_rt[f] IS rtAxis()[ri[f]],
  /// the same array element the producers read.
  inline double rtOf(const TraceStore& s, const Trace& t)
  { const int64_t f = (int64_t)t.frame0 + t.rt_at;
    assert(f >= 0 && (size_t)f < s.frame_rt.size()); return s.frame_rt[(size_t)f]; }
  /// Traces whose RT is NOT one of the store's frame times: only reachable when
  /// ElutionPeakDetection is skipped (trace:ms{1,2}_split_valleys = 0, or a single trace), where
  /// MassTraceDetection reports an intensity-weighted mean instead. Counted, not silent.
  inline std::atomic<size_t>& rtOffGrid() { static std::atomic<size_t> n{0}; return n; }
  /// [soa-rt diag] cause (a): the producer's RT was not one of the store's frame times at all.
  inline std::atomic<size_t>& rtNotAFrame() { static std::atomic<size_t> n{0}; return n; }
  /// [soa-rt diag] cause (b): the RT frame was outside the window trimToSpan kept.
  inline std::atomic<size_t>& rtTrimmedOut() { static std::atomic<size_t> n{0}; return n; }
  /// [soa-rt diag] cause (a) again: is the stray RT strictly BETWEEN two frame times (a weighted
  /// mean, which no frame index can represent) or merely a hair off one (a representable value)?
  inline std::atomic<size_t>& rtStrictlyBetween() { static std::atomic<size_t> n{0}; return n; }
  /// Record `rt` as a frame offset. Snaps to the nearest frame if the value is off-grid (counted).
  inline void setRtFrame(const TraceStore& s, Trace& t, double rt)
  {
    if (s.frame_rt.empty()) { t.rt_at = 0; return; }
    const uint32_t f = s.frameOf(rt);
    if (s.frame_rt[f] != rt)
    {
      rtOffGrid().fetch_add(1, std::memory_order_relaxed);
      rtNotAFrame().fetch_add(1, std::memory_order_relaxed);
      // strictly interior to the frame grid => an interpolated value, unrepresentable as an index
      if (f > 0 && f + 1 < s.frame_rt.size() && rt > s.frame_rt[f - 1] && rt < s.frame_rt[f + 1])
        rtStrictlyBetween().fetch_add(1, std::memory_order_relaxed);
    }
    const int64_t d = (int64_t)f - (int64_t)t.frame0;
    if (d < -32768 || d > 32767) throw OpenMS::Exception::OutOfRange(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
    t.rt_at = (int16_t)d;
  }
  /// The calibration factor of the trace's own apex/measurement frame. Empty table (the OpenMS
  /// detector has no per-frame factors) yields 0.0, which is what the field held there before, and
  /// exportMz_ returns the cached m/z for those traces because their `tof` is 0.
  inline double bOf(const TraceStore& s, const Trace& t) { return s.b.empty() ? 0.0 : s.b[t.bframe]; }
  /// The trace's apex intensity. It was an 8-byte field holding a copy of a number the arena already
  /// stores: makeSpan sets `apex` to the position of the largest value in the span, and both
  /// producers set the field to exactly that value (sl.inten[kap] on the integer path,
  /// MassTrace::getMaxIntensity on the OpenMS one). Trimming moves `apex` with the data, so the
  /// identity survives it. A trace whose profile was released (len == 0) has no apex to read; it is
  /// also never scored, which is why its profile was released.
  inline double intensityOf(const TraceStore& s, const Trace& t)
  { return t.len ? (double)s.inten[t.off + t.apex] : 0.0; }

  /// The real points of a trace, packed in frame order, for the consumers that were written over
  /// point lists (smoother, FWHM): identical sequences, so identical arithmetic.
  inline void packReal(const TraceStore& s, const Trace& t, vector<double>& rt, vector<double>& v)
  {
    rt.clear(); v.clear();
    for (size_t k = 0; k < t.span(); ++k)
      if (real(s, t, k)) { rt.push_back(rtAtSpan(s, t, k)); v.push_back((double)xv(s, t, k)); }
  }

  /// TRIM a trace to at most `cap` seconds around its apex, AFTER detection and valley splitting
  /// have decided what the peak is. This is the safe form of a length limit:
  ///   * detection is untouched, so the greedy consume-and-mark ownership of peaks is unchanged --
  ///     unlike terminating extension, which changes which peaks belong to which trace;
  ///   * it works on MS1 as well as MS2, because it is a step on Trace objects rather than
  ///     something inside OpenMS's extension loop (MS1 is always traced by the OpenMS path, and
  ///     MS1 is where the long traces are: 15.2% of dataset D MS1 traces span >45 s, the longest 1,244 s
  ///     of a 1,860 s gradient, against a 375 s maximum for fragments);
  ///   * what it removes is the far tail of a blob that ElutionPeakDetection did not split, not
  ///     part of a chromatographic peak -- real peaks here are 5-30 s wide.
  /// On the span representation this is free: three integers move, no bytes are copied. The arena
  /// still holds the untrimmed bytes; reclaiming them needs a compaction pass (MS1 already has one).
  inline void trimToSpan(const TraceStore& s, Trace& t, double cap)
  {
    if (cap <= 0.0 || t.span() == 0) return;
    const size_t a = t.apex;
    size_t lo = a, hi = a;
    // grow symmetrically outward from the apex while the span fits, preferring the earlier frame on
    // a tie so the result does not depend on which side is tested first
    for (;;)
    {
      const bool can_lo = lo > 0, can_hi = hi + 1 < t.span();
      if (!can_lo && !can_hi) break;
      const double d_lo = can_lo ? rtAtSpan(s, t, hi) - rtAtSpan(s, t, lo - 1) : 1e30;
      const double d_hi = can_hi ? rtAtSpan(s, t, hi + 1) - rtAtSpan(s, t, lo) : 1e30;
      if (d_lo <= d_hi) { if (!can_lo || d_lo > cap) { if (!can_hi || d_hi > cap) break; ++hi; } else --lo; }
      else              { if (!can_hi || d_hi > cap) { if (!can_lo || d_lo > cap) break; --lo; } else ++hi; }
    }
    // Zero-trim the ends. makeSpan starts and ends a span on a real point by construction, but
    // growing outward from the apex can stop on a gap, and a leading or trailing zero is pure
    // padding: it costs 4 B, it is skipped by every consumer, and it makes `span()` overstate the
    // trace. Interior zeros are the gaps and MUST stay -- they are the presence encoding.
    while (lo < hi && xv(s, t, lo) == 0.0f) ++lo;
    while (hi > lo && xv(s, t, hi) == 0.0f) --hi;
    if (lo == 0 && hi + 1 == t.span()) return;                  // already within the cap, ends real
    uint16_t np = 0;
    for (size_t k = lo; k <= hi; ++k) if (xv(s, t, k) > 0.0f) ++np;
    // [soa-rt] rt_at names EPD's SMOOTHED apex, which is not `apex` (the raw maximum) and can in
    // principle sit outside the window this trim keeps. Clamping would change the trace's reported
    // RT, so it is counted rather than assumed away -- and the digest gate is what settles it.
    // frame0 and rt_at move in opposite directions by the same amount: the frame this trace
    // reports its RT from is untouched, whether or not the trim kept it inside the span.
    const long rr = (long)t.rt_at - (long)lo;
    if (rr < -32768L || rr > 32767L) throw OpenMS::Exception::OutOfRange(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
    t.frame0 += (uint32_t)lo; t.off += (uint32_t)lo;
    t.len = (uint16_t)(hi - lo + 1); t.apex = (uint16_t)(a - lo); t.npts = np;
    t.rt_at = (int16_t)rr;
  }

  /// Drop the spans of the traces nobody references and compact the arena IN PLACE, walking the kept
  /// spans in ORIGINAL OFFSET order -- not container order. ms1_traces is sorted by m/z after its
  /// spans were appended in detection order, so container order is not offset order, and the
  /// previous walk (monotone write cursor over the container) overwrote spans it had not copied yet:
  /// ~1% of precursor XICs, deterministically. Spans are pairwise disjoint on this path (every
  /// child gets its own makeSpan append; trimToSpan only shrinks), and that is VALIDATED before a
  /// byte moves: in ascending-offset order the write cursor can never pass the next source.
  /// A freed trace keeps its scalars and loses its span. Returns the number of profiles released.
  inline Size compactUnreferenced(vector<Trace>& tr, TraceStore& store, const vector<bool>& needed)
  {
    vector<uint32_t> ids;
    Size freed = 0;
    for (size_t i = 0; i < tr.size(); ++i)
    {
      if (!needed[i]) { if (tr[i].np() > 0) ++freed; tr[i].freeProfile(); continue; }
      if (tr[i].len > 0) ids.push_back((uint32_t)i);     // a zero-length span owns no bytes
    }
    sort(ids.begin(), ids.end(), [&](uint32_t a, uint32_t b) { return tr[a].off < tr[b].off; });
    uint64_t prev_end = 0;
    for (uint32_t i : ids)
    {
      const uint64_t beg = tr[i].off, end = beg + (uint64_t)tr[i].len;
      if (end > store.inten.size() || beg < prev_end)
        throw OpenMS::Exception::Precondition(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
                                              "MS1 spans overlap or exceed the arena");
      prev_end = end;
    }
    size_t w = 0;
    for (uint32_t i : ids)
    {
      Trace& t = tr[i];
      if (w != t.off) std::memmove(store.inten.data() + w, store.inten.data() + t.off, (size_t)t.len * sizeof(float));
      t.off = (uint32_t)w; w += t.len;
    }
    store.inten.resize(w); store.inten.shrink_to_fit();
    return freed;
  }

  /// Build a span from (store-local frame, intensity) points into `store`, returning the trace
  /// with `st` UNSET: the caller sets it once the store is immutable. Points may arrive unsorted.
  inline Trace makeSpan(vector<pair<uint32_t, float>>& pts, TraceStore& store)
  {
    Trace t;
    if (pts.empty()) return t;
    sort(pts.begin(), pts.end());
    const uint32_t f0 = pts.front().first, f1 = pts.back().first;
    const size_t L = (size_t)f1 - f0 + 1;
    if (L >= 65536) throw OpenMS::Exception::OutOfRange(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
    t.frame0 = f0; t.len = (uint16_t)L; t.off = (uint32_t)store.inten.size();
    store.inten.resize(store.inten.size() + L, 0.0f);
    float best = -1.0f; uint16_t np = 0;
    for (const auto& q : pts)
    {
      const size_t k = q.first - f0;
      if (store.inten[t.off + k] == 0.0f) ++np;      // one point per frame; a repeat overwrites
      store.inten[t.off + k] = q.second;
      if (q.second > best) { best = q.second; t.apex = (uint16_t)k; }
    }
    t.npts = np;
    return t;
  }

  /// A precursor hypothesis after isotope/charge inference.
  struct Precursor_
  {
    double mono_mz = 0.0;
    uint32_t mono_tof = 0;   ///< the monoisotope's flight-time bin, and its frame's factor: the
    double   mono_b = 0.0;   ///  reported m/z is recomputed from these when the spectrum is written
    int charge = 0;          ///< 0 == unknown
    double rt = 0.0;
    double im = 0.0;
    size_t trace_idx = 0;    ///< index into ms1 traces
    bool guessed = false;    ///< [way-4] charge was DEFAULTED, not isotope-supported
    int n_isotopes = 0;      ///< [Q4] isotope peaks behind the mono call (0/1 = weak, mono ±1.00335 uncertain)
  };

  /// MassTraceDetection locates the per-peak IM array by the exact name
  /// Constants::UserParam::ION_MOBILITY ("Ion Mobility"). Converters name it via CV term and
  /// PeakPickerIM names it "Ion Mobility Centroid"; rename whichever exists so tracing is IM-aware.
  void ensureIMArrayName(MSSpectrum& s)
  {
    auto& fdas = s.getFloatDataArrays();
    if (s.containsIMData())
    {
      fdas[s.getIMData().first].setName(Constants::UserParam::ION_MOBILITY);
      return;
    }
    for (auto& fda : fdas)
    {
      if (fda.getName() == Constants::UserParam::ION_MOBILITY_CENTROID)
      {
        fda.setName(Constants::UserParam::ION_MOBILITY);
        return;
      }
    }
  }

  /// Reported-m/z estimator, set once from `trace:mz_estimator` before any trace is converted.
  /// A file-scope value because toTrace() is a free helper with no access to the tool's parameters.
  inline std::string& mzEstimator() { static std::string v = "apex"; return v; }

  Trace toTrace(const MassTrace& mt, TraceStore& store)
  {
    Trace t;
    // Reported m/z of a mass trace. "apex" (the default) takes the m/z of the most intense peak;
    // "mean" is the OpenMS intensity-weighted centroid; "median" the median m/z. Set by
    // `trace:mz_estimator` -- see docs/BASELINE.md for the comparison that chose apex.
    const std::string& mz_est = mzEstimator();
    if (mz_est == "apex" && mt.getSize() > 0) t.mz = mt[mt.findMaxByIntPeak(false)].getMZ();
    else if (mz_est == "median" && mt.getSize() > 0) { MassTrace m2 = mt; m2.updateMedianMZ(); t.mz = m2.getCentroidMZ(); }
    else t.mz = mt.getCentroidMZ();
    const double crt = mt.getCentroidRT();   // [soa-rt] a frame time; stored as an offset below
    t.im = mt.getCentroidIM();
    // One peak per frame (MassTraceDetection takes at most one candidate per spectrum), so the
    // profile is a span over the store's frame table with zeros where frames were missed.
    const Size np = mt.getSize();
    vector<pair<uint32_t, float>> pts;
    pts.reserve(np);
    for (Size i = 0; i < np; ++i) pts.emplace_back(store.frameOf(mt[i].getRT()), (float)mt[i].getIntensity());
    Trace sp = makeSpan(pts, store);
    sp.mz = t.mz; sp.im = t.im;
    setRtFrame(store, sp, crt);
    return sp;
  }


  /// [compact] Quantised frame store for the per-window buffer.
  ///
  /// Holding all 24 isolation windows as full OpenMS PeakMaps costs ~89 GB resident before any window
  /// is consumed, which is what forces `max_concurrent_windows` down and caps our parallelism at ~7
  /// cores (the reference implementation uses ~43). A frame only needs (m/z, intensity, 1/K0) per peak plus one RT, so we
  /// store structure-of-arrays with quantised keys and materialise a PeakMap ONLY inside the worker
  /// that is about to trace it, freeing the compact copy immediately.
  ///
  /// Precision (deliberately far finer than every downstream tolerance, so tracing is unaffected):
  ///   m/z : uint32 at 1e-5 Da  -> 0.007 ppm at m/z 1400, vs a 20 ppm trace tolerance (2800x margin)
  ///   1/K0: uint16 over [0.4,1.8] -> 2.1e-5, vs a 0.01 IM tolerance (470x margin)
  ///   intensity: float32, unchanged (Peak1D already stores float)
  /// Cost: 10 B/peak (4+4+2) vs ~20 B/peak for Peak1D+FloatDataArray, plus no per-MSSpectrum overhead.
  constexpr double MZ_Q = 1e5;      ///< m/z quantum = 1e-5 Da

  /// THE M/Z AXIS IS THE INSTRUMENT'S FLIGHT-TIME INDEX. A timsTOF measures an integer TOF bin;
  /// m/z is a calibrated function of it, not a measured quantity. The compact store had been
  /// quantising the CALIBRATED m/z onto a uniform 1e-5 Da grid -- a second discretisation on top of
  /// the instrument's own, and a coarse approximation of the wrong axis. This tool only runs on
  /// ion-mobility TOF data, so the native axis is always available and there is no reason to
  /// approximate it.
  ///
  /// Why the native axis is better than a uniform m/z grid, not merely smaller:
  ///   * it is LOSSLESS -- the bin IS the measurement, so no quantum has to be justified;
  ///   * ~5e5 bins instead of ~1.7e8 grid points, so a bin index is a usable array subscript;
  ///   * the SAME ion gives the SAME bin in every frame, while its calibrated m/z wobbles with the
  ///     digitizer temperature -- so grouping in TOF space does not have to spend part of its ppm
  ///     tolerance absorbing calibration drift, which is exactly what the m/z-space tolerance does;
  ///   * a tolerance in m/z ppm becomes a handful of integer bins (m ~ tof^2, so a relative m/z
  ///     tolerance is about half of it in tof), which makes candidate lookup pure arithmetic.
  ///
  /// The per-frame factor `b` (from the digitizer temperature) is what turns a bin into an m/z, and
  /// it is applied at REPORT time, where it belongs -- the extraction never needs a calibrated m/z.
  using TofIdx = uint32_t;

  /// The flight-time axis for one run: the calibration model plus each frame's temperature factor.
  /// Fail-closed: without a calibration there is no TOF axis and the caller must not pretend there
  /// is one.
  struct TofAxis
  {
    spextractor::TdfMzCalibration cal;
    vector<double> b_by_frame;        ///< frame factor per FRAME ID (index 0 unused, as in the tdf)
    bool ok = false;

    double factor(size_t frame_id) const
    { return frame_id < b_by_frame.size() ? b_by_frame[frame_id] : cal.frameFactor(cal.T1_ref); }
    double mzOf(TofIdx tof, double b) const { return cal.tofToMz((double)tof, b); }
    TofIdx tofOf(double mz, double b) const
    {
      const double t = cal.mzToTof(mz, b);
      return t > 0.0 ? (TofIdx)llround(t) : 0u;
    }
    /// A relative m/z tolerance as a bin count, derived rather than assumed: convert both ends.
    TofIdx span(TofIdx tof, double b, double ppm) const
    {
      const double mz = mzOf(tof, b);
      if (!(mz > 0.0)) return 1u;
      const double t2 = cal.mzToTof(mz * (1.0 + ppm * 1e-6), b);
      const double d = fabs(t2 - (double)tof);
      return (TofIdx)std::max(1.0, d + 0.5);
    }
  };

  inline TofAxis& tofAxis() { static TofAxis a; return a; }

  /// Populate the flight-time axis from a Bruker analysis.tdf (the .d directory, or a sidecar).
  /// Returns false and leaves the axis unusable if anything is missing -- the detector that needs it
  /// refuses to run rather than substituting a reference temperature for every frame.
  inline bool loadTofAxis(const std::string& tdf_path, String& why)
  {
    TofAxis& ax = tofAxis();
    ax.ok = false;
    std::vector<double> t1;
    if (!spextractor::loadTdfCalibration(tdf_path, ax.cal, t1, why)) return false;
    ax.b_by_frame.assign(t1.size(), 0.0);
    for (size_t i = 1; i < t1.size(); ++i) ax.b_by_frame[i] = ax.cal.frameFactor(t1[i]);
    // Frames the tdf did not list keep the reference factor rather than a zero -- but index 0
    // is NOT such a frame. It is the "unknown frame" sentinel (the tdf's Frames.Id starts at 1),
    // and frameIdOf() returns 0 for any nativeID it cannot parse. Backfilling it to bref is what
    // let an mzML+sidecar input skip the fallback warning and calibrate every unmapped frame at
    // reference temperature -- the invented calibration this path is supposed to refuse.
    const double bref = ax.cal.frameFactor(ax.cal.T1_ref);
    for (size_t i = 1; i < ax.b_by_frame.size(); ++i) if (!(ax.b_by_frame[i] > 0.0)) ax.b_by_frame[i] = bref;
    ax.b_by_frame[0] = 0.0;
    ax.ok = true;
    return true;
  }
  constexpr double IM_LO = 0.4, IM_HI = 1.8;
  constexpr double IM_Q = 65535.0 / (IM_HI - IM_LO);

  struct CompactFrame
  {
    double rt = 0.0;
    uint32_t frame_id = 0;   ///< vendor frame Id: the key the per-frame calibration factor is on
    vector<uint32_t> mzq;
    vector<float> inten;
    vector<uint16_t> imq;
    size_t bytes() const { return mzq.size() * 4 + inten.size() * 4 + imq.size() * 2; }
  };

  /// Peaks that cannot be represented exactly are DROPPED and COUNTED, never silently altered.
  /// Clamping out-of-range 1/K0 to IM_LO/IM_HI would pin outliers from many frames onto two
  /// artificial, perfectly-aligned mobility values — manufacturing spurious traces out of nothing.
  /// NaN also passed straight through clamp into llround (UB on unsigned conversion). Dropping +
  /// counting is the only defensible behaviour.
  struct CompactStats
  {
    size_t no_im_array = 0, size_mismatch = 0, bad_mz = 0, bad_im = 0, kept = 0;
    size_t unmapped_frame = 0;   ///< nativeID carried no parseable "frame=": cannot be calibrated
    /// merge per-frame stats after a parallel batch [perf-load]
    CompactStats& operator+=(const CompactStats& o)
    {
      no_im_array += o.no_im_array; size_mismatch += o.size_mismatch;
      bad_mz += o.bad_mz; bad_im += o.bad_im; kept += o.kept;
      unmapped_frame += o.unmapped_frame;
      return *this;
    }
  };

  /// Convert one picked MSSpectrum into the compact form (drops everything tracing does not read).
  /// Vendor frame Id from a native identifier. Bruker writes "frame=<N> scan=<M>"; the mzPeak
  /// reader writes "mzpeak=<frame index> window=<w>". Anything else yields 0, which makes the
  /// calibration fall back to the reference temperature -- so the caller must treat 0 as unknown.
  inline uint32_t nidField(const String& nid, const char* key)
  {
    const size_t i = nid.find(key);
    if (i == std::string::npos) return 0;
    uint32_t v = 0; size_t k = i + strlen(key);
    for (; k < nid.size() && isdigit((unsigned char)nid[k]); ++k) v = v * 10 + (uint32_t)(nid[k] - '0');
    return v;
  }
  /// Only the vendor's own "frame=" key names a Frames.Id. The mzPeak reader's "mzpeak=" is an
  /// ARCHIVE index and must not be used as one; that input falls back to the reference factor.
  inline uint32_t frameIdOf(const String& nid) { return nidField(nid, "frame="); }
  /// "windowGroup=<WindowGroup>": which acquisition group this frame belongs to. A group holds each
  /// isolation m/z at most once, so (m/z, group) names one ion-mobility slice of the window; the
  /// scan range alone does not (two slices can share ScanNumBegin = 0 and differ in ScanNumEnd).
  /// 0 when absent (mzPeak input), which keeps that path keyed by m/z alone, as before.
  inline uint32_t windowGroupOf(const String& nid) { return nidField(nid, "windowGroup="); }

  CompactFrame compactify(const MSSpectrum& s, CompactStats& st)
  {
    CompactFrame f;
    f.rt = s.getRT();
    f.frame_id = frameIdOf(s.getNativeID());
    if (f.frame_id == 0) ++st.unmapped_frame;
    if (!s.containsIMData()) { st.no_im_array += s.size(); return f; }
    const auto& im = s.getFloatDataArrays()[s.getIMData().first];
    const Size n = s.size();
    if (im.size() != n) { st.size_mismatch += n; return f; }   // no out-of-bounds read
    f.mzq.reserve(n); f.inten.reserve(n); f.imq.reserve(n);
    for (Size i = 0; i < n; ++i)
    {
      const double mz = s[i].getMZ();
      const double imv = (double)im[i];
      // validate BEFORE the unsigned conversion (NaN/inf/negative -> UB otherwise)
      if (!std::isfinite(mz) || mz <= 0.0 || mz * MZ_Q > 4.2e9) { ++st.bad_mz; continue; }
      if (!std::isfinite(imv) || imv < IM_LO || imv > IM_HI)    { ++st.bad_im; continue; }
      f.mzq.push_back((uint32_t)llround(mz * MZ_Q));
      f.inten.push_back(s[i].getIntensity());
      f.imq.push_back((uint16_t)llround((imv - IM_LO) * IM_Q));
      ++st.kept;
    }
    return f;
  }


  /// [det] Order-insensitive 64-bit digest of a stage's numeric output, for localising
  /// run-to-run nondeterminism: sort the bit patterns, then FNV-1a. Logged under SPEXTRACTOR_DET=1.
  static uint64_t detDigest_(vector<uint64_t> bits)
  {
    std::sort(bits.begin(), bits.end());
    uint64_t h = 1469598103934665603ULL;
    for (uint64_t b : bits) { h ^= b; h *= 1099511628211ULL; }
    return h;
  }
  static bool detOn_() { static const bool on = std::getenv("SPEXTRACTOR_DET") != nullptr; return on; }
  static uint64_t traceDigest_(const TraceStore& st, const vector<Trace>& ts)
  {
    // im and tof are hashed too. im is the PRIMARY key of the fragment sort and the axis of the only
    // binary search in scoring, and tof decides the exported m/z -- a digest blind to them would
    // report "identical" across a change that moved every candidate slice. [2026-09-06]
    vector<uint64_t> b; b.reserve(ts.size() * 5);
    for (const auto& t : ts)
    {
      uint64_t u; double v;
      v = t.mz; std::memcpy(&u, &v, 8); b.push_back(u);
      v = rtOf(st, t); std::memcpy(&u, &v, 8); b.push_back(u);
      v = t.im; std::memcpy(&u, &v, 8); b.push_back(u);
      v = intensityOf(st, t); std::memcpy(&u, &v, 8); b.push_back(u);
      b.push_back((uint64_t)t.tof);
    }
    return detDigest_(std::move(b));
  }

  /// One window's peaks in INDEX SPACE, frame-major. This is what the compact store already holds;
  /// the point is that it is never converted back to Peak1D doubles. Replaces the materialised
  /// PeakMap for the integer detector. See docs/MZ-AXIS-DESIGN.md.
  struct PeakSlab
  {
    vector<uint32_t> frame_off;    ///< size F+1: frame f owns [frame_off[f], frame_off[f+1])
    vector<uint32_t> rt_index;     ///< size F: the frame's index on the GLOBAL RT axis
    vector<TofIdx>   tof;          ///< flight-time bin, ascending within a frame
    vector<double>   b;            ///< size F: the frame's calibration factor (bin -> m/z)
    vector<float>    inten;
    vector<uint16_t> imq;          ///< the store's quantised 1/K0, kept for export
    size_t frames() const { return rt_index.size(); }
    size_t peaks()  const { return tof.size(); }
  };

  /// Ordered, incremental digest of a window's slab: frame table (rt index, factor bits, count) then
  /// every (tof, intensity bits, imq) tuple in frame order. Unlike detDigest_ it is NOT sorted, so a
  /// reordered equal-intensity peak or a tuple swapped between frames changes it -- which is what a
  /// representation change of the store must not do. [det]
  static uint64_t slabDigest_(const PeakSlab& sl)
  {
    uint64_t h = 1469598103934665603ULL;
    auto mix = [&](uint64_t v) { h ^= v; h *= 1099511628211ULL; };
    for (size_t f = 0; f < sl.frames(); ++f)
    {
      uint64_t bb; std::memcpy(&bb, &sl.b[f], 8);
      mix(sl.rt_index[f]); mix(bb); mix(sl.frame_off[f + 1] - sl.frame_off[f]);
      for (uint32_t k = sl.frame_off[f]; k < sl.frame_off[f + 1]; ++k)
      { uint32_t ib; std::memcpy(&ib, &sl.inten[k], 4); mix(sl.tof[k]); mix(ib); mix(sl.imq[k]); }
    }
    return h;
  }

  /// Move a window's compact frames into a slab, consuming them as it goes (the compact store has
  /// to shrink in step, exactly as materializeWindow does, or the two representations coexist).
  PeakSlab toSlab(vector<CompactFrame>& frames)
  {
    PeakSlab sl;
    const size_t F = frames.size();
    sl.frame_off.resize(F + 1, 0);
    sl.rt_index.resize(F);
    size_t total = 0;
    for (const auto& f : frames) total += f.mzq.size();
    sl.tof.reserve(total); sl.inten.reserve(total); sl.imq.reserve(total);
    sl.b.resize(F);
    const TofAxis& ax = tofAxis();
    for (size_t i = 0; i < F; ++i)
    {
      CompactFrame& f = frames[i];
      sl.rt_index[i] = rtIndex(f.rt);
      // The compact store keeps m/z at a 1e-5 Da quantum, ~400x finer than one TOF bin at m/z 600,
      // so inverting the calibration recovers the ORIGINAL bin exactly -- no approximation is
      // introduced here, and the loader does not have to change.
      const double b = ax.factor(f.frame_id);
      sl.b[i] = b;
      sl.frame_off[i] = (uint32_t)sl.tof.size();
      for (size_t k = 0; k < f.mzq.size(); ++k)
        sl.tof.push_back(ax.tofOf((double)f.mzq[k] / MZ_Q, b));
      sl.inten.insert(sl.inten.end(), f.inten.begin(), f.inten.end());
      sl.imq.insert(sl.imq.end(), f.imq.begin(), f.imq.end());
      vector<uint32_t>().swap(f.mzq);
      vector<float>().swap(f.inten);
      vector<uint16_t>().swap(f.imq);
    }
    sl.frame_off[F] = (uint32_t)sl.tof.size();
    // The extension loop steps frames by index and takes the RT span as last minus first, so the
    // frames must be in RT order -- the OpenMS path sorts its spectra for the same reason. The
    // loader delivers them ordered; this checks rather than assumes.
    for (size_t i = 1; i < F; ++i)
      if (sl.rt_index[i] < sl.rt_index[i - 1])
        throw OpenMS::Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
              "window frames are not in retention-time order at frame", std::to_string(i));
    return sl;
  }


  /// Mass-trace detection on the integer m/z axis.
  ///
  /// The OpenMS detector accepts a peak when it lies within `mass_error_ppm` of a trace's RUNNING
  /// centroid, which needs a tolerance comparison against every live trace and makes the cost
  /// superlinear in peaks per band -- measured on dataset D: 4 bands 18:25 wall / 163 GB against 12 bands
  /// 12:53 / 103 GB, i.e. the same work costs more when the bands are bigger. On a uniform integer
  /// axis the candidates for a peak are found by ARITHMETIC: a live trace can only accept indices
  /// within `ppmSpan` of its centroid, so bucketing by `mz >> shift` with a bucket wider than the
  /// largest span puts every candidate in the peak's own bucket or its two neighbours.
  ///
  /// This is a DIFFERENT ALGORITHM, not a reimplementation: it will not reproduce the OpenMS
  /// detector peak for peak. It is the default (`trace:detector=integer`), and must be judged on
  /// identified peptides with both search engines, never on a spectrum digest. On dataset D and dataset A the
  /// two detectors agree on ~85% of the union of identified peptides, and which one identifies more
  /// flips with both the search engine and the file; the case for it is ~40% less memory.
  ///
  /// Mobility is part of the identity, as in the IM-aware OpenMS path: a candidate must also be
  /// within `im_tol` of the trace's mobility. Valley splitting is NOT done here -- the existing
  /// ElutionPeakDetection step runs afterwards on the traces this produces.
  /// Mass-trace detection on integer arrays, following OpenMS `MassTraceDetection::run_` step for
  /// step -- written from that source, not from a description of it. A version written from a
  /// description rather than from the source lost 92% of the peptides; the semantics that matter are:
  ///   * seeds in intensity order, ties later-index-first (stable ascending sort, reverse walk);
  ///   * the two directions extend INTERLEAVED, one frame down then one up, sharing one centroid;
  ///   * acceptance is the CLOSEST peak within +-3 sd of the running m/z centroid and within the
  ///     mobility tolerance of the running mobility centroid; if that closest peak is already
  ///     taken, the frame is a MISS -- the next-closest is not tried;
  ///   * sd starts at centroid*ppm and is RE-ESTIMATED from the accepted peaks (reestimate_mt_sd);
  ///   * a direction stops after more than 5 consecutive misses; an empty frame is not a miss;
  ///   * the trace is valid if its RT span is within [min,max] length and
  ///     size / (frames visited - trailing misses) >= min_sample_rate (0.5 by default);
  ///   * peaks are marked taken only when the trace is valid;
  ///   * the seed is counted twice in the centroid, as run_ does (init, then update again).
  /// Peaks stay integers (flight-time bin, quantised mobility); the running centroid and sd are
  /// doubles in m/z, exactly as in OpenMS, so the tolerance semantics are the same. The bin<->m/z
  /// conversion is one calibration call per frame step plus one per ACCEPTED peak -- never per
  /// visited peak. Valley splitting runs afterwards on the result, as it does for the OpenMS path.
  /// Per-window, read-only preparation shared by every band task: frame of each peak, the
  /// noise-membership mask, per-frame "has any member" (OpenMS deletes sub-noise peaks first and
  /// only then asks whether a frame is empty), and the intensity-ordered seed list. Built ONCE.
  /// The first corrected version rebuilt all of this inside each of the 12 band tasks -- twelve
  /// full-window sorts per window and twelve sets of P-sized arrays alive at once -- which is
  /// exactly where its extra time (9:28 vs 7:22) and extra memory (174 vs 166 GB) came from.
  struct TracePrep
  {
    vector<char>     frame_live;  ///< F: has at least one member
    size_t           n_live = 0;  ///< [tile-0d] frames with >= 1 above-noise peak (G_live)
    vector<uint32_t> order;       ///< seeds, intensity desc, later-index-first among equals
    vector<size_t>   seg;         ///< nb+1 offsets into `order`: band b owns [seg[b], seg[b+1])
    /// [tofidx] Per-frame direct-address index over the flight-time bins: bucket
    /// `(tof - tlo) >> tsh` of frame f starts at peak `fidx[f * (nbk+1) + bucket]`. Computed, not
    /// searched -- the bin IS an integer the instrument produced, so the bucket is a subtract and
    /// a shift. It replaces the per-frame-step binary search in `best()`, which ran once for every
    /// frame step of every trace extension over a frame's ~25,000 sorted bins.
    vector<uint32_t> fidx;
    TofIdx tlo = 0; unsigned tsh = 0; uint32_t nbk = 0;
    inline void range(size_t f, TofIdx lo_t, uint32_t a, uint32_t b, uint32_t& s0, uint32_t& s1) const
    {
      if (fidx.empty()) { s0 = a; s1 = b; return; }
      const uint64_t d = lo_t <= tlo ? 0 : ((uint64_t)(lo_t - tlo) >> tsh);
      const uint32_t k = d >= nbk ? nbk : (uint32_t)d;
      const uint32_t* row = &fidx[f * ((size_t)nbk + 1)];
      s0 = row[k]; s1 = (k + 1 <= nbk) ? row[k + 1] : b;
    }
  };
  /// [tofidx] Bucket every frame's flight-time bins so `best()` can address its scan start instead
  /// of binary-searching for it. ~32 peaks per bucket; the shift is global so bucket boundaries
  /// line up across frames. Exact: the bucket start is the first peak with `tof >= bucket_lo`, so
  /// the sub-range handed to lower_bound provably contains the same position it would have found.
  void buildTofIndex(const PeakSlab& sl, TracePrep& tp, TofIdx tlo, TofIdx thi)
  {
    const size_t F = sl.frames(), P = sl.tof.size();
    if (F == 0 || P == 0 || thi < tlo) return;
    const uint64_t span = (uint64_t)thi - tlo + 1;
    const size_t ppf = std::max<size_t>(1, P / F);
    uint32_t want = 64; while (want < 4096 && (size_t)want * 32 < ppf) want <<= 1;
    unsigned sh = 0; while ((span >> sh) > want) ++sh;
    const uint32_t nbk = (uint32_t)std::min<uint64_t>(want, (span >> sh) + 1);
    // one row of nbk+1 offsets per frame; the extra entry is the row's end
    if ((double)F * (nbk + 1) > 3e8) return;                 // pathological geometry: skip the index
    tp.tlo = tlo; tp.tsh = sh; tp.nbk = nbk;
    tp.fidx.assign(F * ((size_t)nbk + 1), 0);
    #pragma omp taskloop default(shared)
    for (long fi = 0; fi < (long)F; ++fi)
    {
      const size_t f = (size_t)fi;
      const uint32_t a = sl.frame_off[f], e = sl.frame_off[f + 1];
      uint32_t* row = &tp.fidx[f * ((size_t)nbk + 1)];
      uint32_t k = a;
      for (uint32_t bk = 0; bk <= nbk; ++bk)
      {
        const uint64_t blo = (uint64_t)bk << sh;
        while (k < e && (uint64_t)(sl.tof[k] - tlo) < blo) ++k;
        row[bk] = k;
      }
    }
  }

  /// `bnd` are the nb+1 flight-time band edges the detector will be given (bnd[0] = tlo,
  /// bnd[nb] = thi+1); pass {0, 0} for the unbanded path, which wants one globally sorted list.
  ///
  /// [seg 2026-09-07] The seed list is SEGMENTED BY BAND and each segment sorted on its own,
  /// instead of one global sort that all 12 bands then re-scan end to end. Exact, because the
  /// comparator is a total order:  filter_b(sort(all)) == sort(filter_b(all))  -- the sorted
  /// sequence is unique, so band b receives precisely the subsequence it used to select. What it
  /// buys: the sort is the whole of this stage (two linear passes plus an O(N log N) sort of up
  /// to 239e6 indices) and it was SERIAL, at 23-63 s per window on a 2-hour acquisition; as nb
  /// independent sorts it runs on nb threads of the same pool. Each band also stops walking the
  /// other bands' seeds.
  TracePrep prepareTracing(const PeakSlab& sl, double noise, double snr, const vector<TofIdx>& bnd,
                           TofIdx tlo, TofIdx thi)
  {
    TracePrep tp;
    const size_t F = sl.frames(), P = sl.tof.size();
    // No per-peak frame map and no membership byte: a peak's frame is the loop variable at every
    // hot site (and one binary search at the two that lack it), and membership IS
    // `inten > noise`. Measured: 100% of above-noise peaks are seeds at the shipped snr of 1.0, so
    // `order` was reserved at P/4 and grew by doubling to ~2P -- count first, reserve exactly.
    tp.frame_live.assign(F, 0);
    const double min_apex = snr * noise;
    size_t n_seed = 0;
    for (size_t f = 0; f < F; ++f)
      for (uint32_t k = sl.frame_off[f]; k < sl.frame_off[f + 1]; ++k)
        if ((double)sl.inten[k] > noise) { tp.frame_live[f] = 1; if ((double)sl.inten[k] > min_apex) ++n_seed; }
    for (char u : tp.frame_live) tp.n_live += u ? 1 : 0;
    // OpenMS: stable_sort ascending by intensity, then iterate in reverse -> among equal
    // intensities the LATER peak seeds first.
    auto cmp = [&](uint32_t a, uint32_t b) {
      if (sl.inten[a] != sl.inten[b]) return sl.inten[a] > sl.inten[b];
      return a > b;
    };
    const int nb = (int)bnd.size() - 1;
    tp.order.resize(n_seed);
    if (nb < 2)                                          // unbanded: one globally sorted list
    {
      size_t w = 0;
      for (uint32_t k = 0; k < P; ++k)
        if ((double)sl.inten[k] > noise && (double)sl.inten[k] > min_apex) tp.order[w++] = k;
      sort(tp.order.begin(), tp.order.end(), cmp);
      tp.seg = {0, n_seed};
      return tp;
    }
    // Band of a peak: the same half-open [bnd[b], bnd[b+1]) partition the detector applies, found
    // by upper_bound so that empty bands (bnd[b] == bnd[b+1], reachable when nb exceeds the tof
    // range) are skipped exactly as the detector's own range test skips them.
    auto bandOf = [&](TofIdx t) {
      return (size_t)(std::upper_bound(bnd.begin(), bnd.end(), t) - bnd.begin() - 1);
    };
    vector<size_t> cnt(nb, 0);
    for (uint32_t k = 0; k < P; ++k)
      if ((double)sl.inten[k] > noise && (double)sl.inten[k] > min_apex) ++cnt[bandOf(sl.tof[k])];
    tp.seg.assign(nb + 1, 0);
    for (int b = 0; b < nb; ++b) tp.seg[b + 1] = tp.seg[b] + cnt[b];
    vector<size_t> cur(tp.seg.begin(), tp.seg.end() - 1);
    for (uint32_t k = 0; k < P; ++k)
      if ((double)sl.inten[k] > noise && (double)sl.inten[k] > min_apex) tp.order[cur[bandOf(sl.tof[k])]++] = k;
    #pragma omp taskloop grainsize(1) default(shared)
    for (int b = 0; b < nb; ++b)
      sort(tp.order.begin() + tp.seg[b], tp.order.begin() + tp.seg[b + 1], cmp);
    buildTofIndex(sl, tp, tlo, thi);
    return tp;
  }

  vector<Trace> detectTracesInteger_(const PeakSlab& sl, const TracePrep& tp, TraceStore& store, double mass_ppm,
                                     double im_tol, double noise, double min_len_sec, double min_sample_rate,
                                     TofIdx band_lo = 0, TofIdx band_hi = 0,
                                     int band = -1)
  {
    vector<Trace> out;
    const size_t F = sl.frames(), P = sl.tof.size();
    if (F == 0 || P == 0) return out;
    const bool banded = band_hi > band_lo;
    const TofAxis& ax = tofAxis();
    const double msr = min_sample_rate >= 0.0 ? min_sample_rate : 0.5;   // -1 = OpenMS default
    const double imq_tol = im_tol * IM_Q;
    const Size max_missed = 5;                                            // trace_termination_outliers
    // a peak's frame, for the two sites that do not already have it in a loop variable
    auto frameOfPeak = [&](uint32_t k) {
      return (uint32_t)(std::upper_bound(sl.frame_off.begin(), sl.frame_off.end(), k) - sl.frame_off.begin() - 1);
    };
    const auto member = [&](uint32_t k) { return (double)sl.inten[k] > noise; };

    vector<uint64_t> visited((P + 63) / 64, 0);   // one BIT per peak: 8x less than the char array
    auto seen = [&](size_t k) { return (visited[k >> 6] >> (k & 63)) & 1u; };
    auto mark = [&](size_t k) { visited[k >> 6] |= (uint64_t)1 << (k & 63); };
    auto mzAt = [&](uint32_t k, size_t f) { return ax.mzOf(sl.tof[k], sl.b[f]); };
    auto iwm = [](double v, double w, double& c, double& cnt, double& den) {   // updateIterativeWeightedMean_
      const double ct = 1.0 + (w * v) / cnt, dt = 1.0 + w / den;
      c *= (ct / dt); cnt += w * v; den += w;
    };
    auto sdRobust = [](double mz, double w, double mean, double& sd, double& wsum) {   // updateWeightedSDEstimateRobust
      const double d1 = std::log(wsum) + 2.0 * std::log(sd);
      const double d2 = std::log(w) + 2.0 * std::log(std::abs(mz - mean));
      const double denom = std::sqrt(std::exp(d1) + std::exp(d2));
      const double ws = wsum + w;
      const double t = denom / std::sqrt(ws);
      if (t > std::numeric_limits<double>::epsilon()) sd = t;
      wsum = ws;
    };
    /// findBestPeak_ + isPeakAcceptable_: the closest peak in m/z within +-3 sd of the running
    /// centroid whose mobility is inside the gate; -1 for "no candidate", and `taken` set when the
    /// closest one is already used, which OpenMS counts as a miss rather than trying the next.
    /// The +-3 sd window is converted to a BIN range once per frame step, so the walk is bounded
    /// by two calibration calls and a binary search; only candidates inside that window are
    /// converted back to m/z for the comparison.
    auto best = [&](size_t f, double cmz, double sd, double cim, bool& taken) -> long {
      taken = false;
      const uint32_t a = sl.frame_off[f], b = sl.frame_off[f + 1];
      if (b <= a) return -1;
      const double bf = sl.b[f];
      const double lo_mz = cmz - 3.0 * sd, hi_mz = cmz + 3.0 * sd;
      const TofIdx lo_t = ax.tofOf(lo_mz > 0.0 ? lo_mz : 1e-9, bf);
      const TofIdx hi_t = ax.tofOf(hi_mz, bf);
      uint32_t r0 = a, r1 = b; tp.range(f, lo_t, a, b, r0, r1);   // [tofidx] computed, not searched
      const uint32_t s0 = (uint32_t)(lower_bound(sl.tof.begin() + r0, sl.tof.begin() + r1, lo_t) - sl.tof.begin());
      long bk = -1; double bd = std::numeric_limits<double>::infinity();
      for (uint32_t k = s0; k < b && sl.tof[k] <= hi_t; ++k)
      {
        if (!member(k)) continue;
        if (std::abs((double)sl.imq[k] - cim) > imq_tol) continue;
        // "Closest" is measured in m/z, as OpenMS does, NOT in bins: I had argued the calibration
        // is monotone so the two agree, and that is true only for candidates on the same side of
        // the centroid -- across it, the map's curvature can flip which is nearer. Measured: the
        // bin metric cost 1.4% of peptides (12,650 -> 12,466) and bought no time (the speed came
        // from parallel valley splitting). The walk is still bounded in bins; only candidates
        // inside the window pay the conversion.
        const double d = std::abs(ax.mzOf(sl.tof[k], bf) - cmz);
        if (d < bd) { bd = d; bk = (long)k; }          // strict <: first of equals wins
      }
      if (bk >= 0 && seen((size_t)bk)) { taken = true; return -1; }
      return bk;
    };

    struct Dir { Size hits = 0, missed = 0, scans = 0; bool active = true; };
    vector<pair<uint32_t, uint32_t>> got;   // (frame, peak); marked only if the trace is valid
    // [seg] Only this band's own segment of the seed list; the range test below stays as the
    // invariant it always was (and is what the unbanded/whole-list call still relies on).
    const bool segd = band >= 0 && (size_t)band + 1 < tp.seg.size();
    const size_t s0 = segd ? tp.seg[band] : 0, s1 = segd ? tp.seg[band + 1] : tp.order.size();
    for (size_t si = s0; si < s1; ++si)
    {
      const uint32_t seed = tp.order[si];
      if (banded && (sl.tof[seed] < band_lo || sl.tof[seed] >= band_hi)) continue;   // not this band's core
      if (seen(seed)) continue;
      const size_t f0 = frameOfPeak(seed);
      const double w0 = sl.inten[seed], m0 = mzAt(seed, f0);
      double cmz = m0, cnt = w0 * m0, den = w0;
      iwm(m0, w0, cmz, cnt, den);                             // seed counted twice, as run_ does
      double cim = sl.imq[seed], cnt_im = w0 * cim, den_im = w0;
      iwm((double)sl.imq[seed], w0, cim, cnt_im, den_im);
      double sd = (cmz / 1e6) * mass_ppm, wsum = w0;
      got.clear(); got.emplace_back((uint32_t)f0, seed);
      Dir dn, up;
      long fd = (long)f0, fu = (long)f0;
      while ((fd > 0 && dn.active) || (fu + 1 < (long)F && up.active))
      {
        for (int side = 0; side < 2; ++side)
        {
          Dir& d = side == 0 ? dn : up;
          long& fi = side == 0 ? fd : fu;
          if (!d.active) continue;
          if (side == 0 ? !(fi > 0) : !(fi + 1 < (long)F)) continue;
          const size_t f = (size_t)(side == 0 ? fi - 1 : fi + 1);
          // "empty" AFTER sub-noise deletion, as OpenMS tests it. Testing raw emptiness instead is
          // the A/B that attributes the 12,650 -> 12,466 move between the two corrected versions,
          // which is the only semantic change between them.
          if (tp.frame_live[f])
          {
            bool taken = false;
            const long k = best(f, cmz, sd, cim, taken);
            if (k >= 0)
            {
              const double mz = mzAt((uint32_t)k, f), w = sl.inten[k];
              iwm(mz, w, cmz, cnt, den);
              iwm((double)sl.imq[k], w, cim, cnt_im, den_im);
              sdRobust(mz, w, cmz, sd, wsum);   // reestimate_mt_sd: the tool never turns it off
              got.emplace_back((uint32_t)f, (uint32_t)k);
              ++d.hits; d.missed = 0;
            }
            else ++d.missed;
          }
          fi += (side == 0 ? -1 : 1);
          ++d.scans;
          if (d.missed > max_missed) d.active = false;
        }
      }
      // isTraceValid_
      uint32_t fmin = got[0].first, fmax = fmin;
      for (const auto& g : got) { fmin = std::min(fmin, g.first); fmax = std::max(fmax, g.first); }
      const double span_s = rtAxis()[sl.rt_index[fmax]] - rtAxis()[sl.rt_index[fmin]];
      if (span_s < min_len_sec) continue;
      const Size total = dn.scans + up.scans + 1;
      const Size adjusted = total > dn.missed + up.missed ? total - dn.missed - up.missed : 1;
      if ((double)got.size() / (double)adjusted < msr) continue;
      for (const auto& g : got) mark(g.second);               // valid: now they are taken

      // the span: (store-local frame, intensity) points, plus the per-frame bin arena the valley
      // splitter needs to give each child ITS measured apex bin
      vector<pair<uint32_t, float>> pts;
      pts.reserve(got.size());
      uint32_t kap = got[0].second, fap = got[0].first;
      for (const auto& g : got) { pts.emplace_back(g.first, sl.inten[g.second]);
                                  if (sl.inten[g.second] > sl.inten[kap]) { kap = g.second; fap = g.first; } }
      Trace t = makeSpan(pts, store);
      const uint32_t t_tof = sl.tof[kap];             // this trace's own bin: the offsets' origin
      store.bins.resize(store.inten.size(), 0);
      for (const auto& g : got)
      {
        const int64_t d = (int64_t)sl.tof[g.second] - (int64_t)t_tof;   // [bin-delta]
        if (d < -32768 || d > 32767) throw OpenMS::Exception::OutOfRange(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION);
        store.bins[t.off + (g.first - t.frame0)] = (int16_t)d;
      }
      t.tof = t_tof; t.bframe = fap;   // got-order first max: the frame the bin was measured on
      t.mz = cmz;                                              // the weighted centroid, as OpenMS reports
      t.rt_at = (int16_t)((int64_t)fap - (int64_t)t.frame0);   // [soa-rt] was rtAxis()[sl.rt_index[fap]]
      t.im = IM_LO + cim / IM_Q;
      out.push_back(std::move(t));
    }
    return out;
  }

  /// Integer traces -> MassTrace objects for EPD -> Trace again, with the flight-time bin
  /// re-attached from the apex frame's calibration. Only the TRACES become OpenMS objects -- the
  /// peak arrays never do, which is the point of the integer path.
  ///
  /// CHUNKED AND PARALLEL, like the OpenMS path's own valley-splitting step (do_split over
  /// bands*4 chunks as tasks). The previous version converted every trace of a window into a
  /// MassTrace (a list<Peak2D>, ~48 B/point) on ONE thread and then ran ElutionPeakDetection over
  /// all of them at once, also on one thread: a serial section of a stage that is 95% of the window
  /// loop, and the whole window's list-based copy alive at the same time. That is consistent with
  /// what was measured -- occupancy 44x against 81x for the OpenMS path, and MORE peak memory,
  /// after the per-band sorts and the per-visit calibration calls had already been removed and
  /// changed nothing.
  vector<Trace> splitIntegerTraces(vector<Trace>& in, double split_valleys, TraceStore& wst, int nchunk)
  {
    if (split_valleys <= 0.0 || in.size() < 2) return std::move(in);   // OpenMS branch: EPD needs > 1
    const TofAxis& ax = tofAxis();
    nchunk = std::max(1, std::min<int>(nchunk, (int)in.size()));
    vector<vector<Trace>> parts(nchunk);
    vector<TraceStore> stores(nchunk);                         // chunk-private arenas, merged after
    const size_t n_in = in.size();
    #pragma omp taskloop grainsize(1) default(shared)
    for (int ci = 0; ci < nchunk; ++ci)
    {
      const size_t lo = (size_t)ci * n_in / nchunk, hi = (size_t)(ci + 1) * n_in / nchunk;
      TraceStore& cst = stores[ci];
      cst.setFrames(wst.rt_index, &wst.b);
      // STREAMED: one MassTrace in flight, not the chunk's worth. The two-phase version built every
      // input trace of the chunk as a MassTrace and kept them all alive across the split, so the
      // input payload and the whole split output coexisted -- the two largest ledger lines after the
      // slab. Per-trace is exactly equivalent: with width_filtering=off and masstrace_snr_filtering
      // =false the cross-trace routines are unreachable, and the lock-free patch's nested path is
      // itself `for (i..) detectElutionPeaks_(mt_vec[i], out)` appending in the same order.
      //
      // epd is hoisted to chunk scope deliberately. splitValleys constructed one and did
      // getParameters/setValue x4/setParameters on EVERY call; moving that inside a per-trace loop
      // would be ~4e4 Param round-trips per chunk and would trade the memory win for a slowdown.
      ElutionPeakDetection epd;
      epd.setLogType(ProgressLogger::NONE);
      {
        Param ep = epd.getParameters();
        ep.setValue("chrom_fwhm", split_valleys);
        ep.setValue("width_filtering", "off");
        ep.setValue("masstrace_snr_filtering", "false");
        epd.setParameters(ep);
      }
      vector<Trace>& out = parts[ci];
      out.reserve((hi - lo) + (hi - lo) / 3);   // measured 1.316 children per parent over 28 windows:
      // reserving the PARENT count made every chunk cross exactly one doubling. [2026-09-06]
                              // Measured no regression (dataset D got faster and lighter); revisit only if it shows up.
      vector<Peak2D> pk;                                      // reused: a vector, not a per-point list
      vector<MassTrace> split;                                // reused: detectPeaks clears it itself
      for (size_t q = lo; q < hi; ++q)
      {
        const Trace& t = in[q];
        pk.clear();
        for (size_t k = 0; k < t.span(); ++k)                 // REAL points only: EPD smooths what it is given
        {
          if (!real(wst, t, k)) continue;
          Peak2D pt; pt.setRT(rtAtSpan(wst, t, k)); pt.setIntensity(xv(wst, t, k));
          // [bin-delta] reconstruct the absolute bin; identical to the value this used to store
          const uint32_t bin = wst.bins.empty() ? 0u : (uint32_t)((int64_t)t.tof + wst.bins[t.off + k]);
          pt.setMZ(ax.ok && bin ? ax.mzOf(bin, wst.b[t.frame0 + k]) : t.mz);
          pk.push_back(pt);
        }
        MassTrace mt(pk);
        mt.setCentroidIM(t.im);
        epd.detectPeaks(mt, split);
        // Each child carries its own measured m/z: the parent's per-frame bin was written into
        // every Peak2D above, so the child's APEX PEAK m/z is that bin's m/z and the bin comes back
        // by inverting the calibration -- which is what the pre-span code did.
        //
        // The first version of this walked the parent list to look the bin up by frame. That was
        // wrong: parents within a chunk are in IM/m-z order, not frame order, and their frame ranges
        // overlap freely, so the walk could attribute a child to the wrong parent and hand it another
        // trace's bin. It cost 3.3% of peptides on dataset D while the OpenMS arm stayed digest-identical,
        // which is what localised it here. [2026-09-04]
        for (const MassTrace& cm : split)
        {
          Trace c = toTrace(cm, cst);
          if (c.np() == 0) continue;
          const uint32_t cf = c.frame0 + c.apex;               // apex frame, window-local
          c.bframe = cf;
          const double cb = wst.b.empty() ? ax.factor(0) : wst.b[cf];
          const double amz = cm.getSize() ? cm[cm.findMaxByIntPeak(false)].getMZ() : c.mz;
          c.tof = ax.ok ? ax.tofOf(amz, cb) : 0u;
          out.push_back(std::move(c));
        }
      }
    }
    // the parents' spans are dead: rebuild the window arena from the chunk arenas
    vector<Trace>().swap(in);
    vector<float>().swap(wst.inten); vector<int16_t>().swap(wst.bins);
    size_t tot = 0, arena = 0; bool any_bins = false;
    for (int ci = 0; ci < nchunk; ++ci)
    { tot += parts[ci].size(); arena += stores[ci].inten.size(); any_bins |= !stores[ci].bins.empty(); }
    // absorb() appends without reserving and the window arena was just swapped empty, so without
    // this the 48 chunk appends regrow it geometrically. Note this trades regrowth for allocating
    // the whole destination while every source is still live: it removes the copies, but whether
    // it lowers the PEAK is a measurement, not a deduction.
    wst.inten.reserve(arena); if (any_bins) wst.bins.reserve(arena);
    vector<Trace> out; out.reserve(tot);
    for (int ci = 0; ci < nchunk; ++ci)
    {
      const uint32_t base = wst.absorb(stores[ci]);
      for (auto& t : parts[ci]) { t.off += base; out.push_back(std::move(t)); }
      vector<Trace>().swap(parts[ci]);
    }
    return out;
  }

  /// Rebuild a PeakMap for ONE window from its compact frames, for MassTraceDetection.
  /// Frames are consumed (cleared) as they are materialised so the compact store shrinks in step.
  PeakMap materializeWindow(vector<CompactFrame>& frames)
  {
    PeakMap m;
    m.reserve(frames.size());
    for (auto& f : frames)
    {
      MSSpectrum s;
      s.setRT(f.rt);
      s.setMSLevel(1); // MassTraceDetection traces MS1-level only
      s.reserve(f.mzq.size());
      OpenMS::DataArrays::FloatDataArray ima;
      ima.setName(Constants::UserParam::ION_MOBILITY);
      ima.reserve(f.mzq.size());
      for (size_t i = 0; i < f.mzq.size(); ++i)
      {
        Peak1D p;
        p.setMZ((double)f.mzq[i] / MZ_Q);
        p.setIntensity(f.inten[i]);
        s.push_back(p);
        ima.push_back((float)(IM_LO + (double)f.imq[i] / IM_Q));
      }
      s.getFloatDataArrays().push_back(std::move(ima));
      m.addSpectrum(std::move(s));
      // release this frame's compact storage immediately
      vector<uint32_t>().swap(f.mzq);
      vector<float>().swap(f.inten);
      vector<uint16_t>().swap(f.imq);
    }
    vector<CompactFrame>().swap(frames);
    return m;
  }

  /// [stream] Pick-and-compact consumer: removes the one-shot-read memory floor.
  ///
  /// MEASURED: `loadExperiment` reaches 90.3 GB RSS / 99.0 GB peak at t=0s, BEFORE any compaction
  /// exists — so the compact store (10 B/peak, 20.9 GB for 2.19e9 peaks) can never lower the peak.
  /// The floor is the whole run being resident at once. BrukerTimsFile::loadDIAStreaming hands us one
  /// frame at a time, so we peak-pick and compact each frame on arrival and never hold the raw run.
  ///
  /// Windows are keyed by the SAME (lo,hi) isolation-window key used downstream, taken from the
  /// spectrum's own precursor, so routing is identical to the old split - not by swath_nr, whose
  /// ordering is the reader's business and need not match ours.
  /// Isolation window identity: (lo*100, hi*100, WindowGroup). The group is part of it because
  /// one diaPASEF scheme (Meier 2020 "py3", PXD017703) acquires the SAME m/z window in two window
  /// groups with shifted, overlapping ion-mobility slices ~1.7 s apart in the cycle. Keyed by m/z
  /// alone the two halves land in one window as all of group A then all of group B (RT not
  /// monotone, and a precursor outside the overlap would see every other frame empty). Every
  /// other scheme has one slice per m/z, so for those this key orders and partitions exactly as
  /// the old (lo, hi) pair did.
  using WinKey = std::array<int, 3>;

  class PickCompactConsumer : public FullSwathFileConsumer
  {
  public:
    PickCompactConsumer(PeakPickerIM& picker, map<WinKey, vector<CompactFrame>>& windows,
                        PeakMap& ms1, CompactStats& stats,
                        std::function<WinKey(double, double, uint32_t)> keyfn)
      : picker_(picker), windows_(windows), ms1_(ms1), stats_(stats), keyfn_(std::move(keyfn)) {}

    size_t frames_seen = 0;

    /// [perf-load] Pick+compact a BATCH of buffered frames in parallel, then append in arrival
    /// order. OpenMS hands frames over a strictly serial `for (fid..) consumeSpectrum(spec)` loop,
    /// so before this the peak picking of 1.26e9 peaks ran on ONE thread and was 53% of total wall
    /// (measured: 1046 s wall, parallel factor 1.0). Buffering here parallelises it without
    /// touching the reader. Appending strictly by buffer index keeps the output order identical to
    /// the serial path; the emitted spectra matched it in m/z and differed in ~2% of intensities at
    /// the 1e-5..1e-4 relative level (Sage count unchanged).
    void flush_()
    {
      const int n = (int)buf_.size();
      if (n == 0) return;
      const double _tf0 = phase_clock_();
      std::vector<CompactFrame> compacted((size_t)n);
      std::vector<CompactStats> st((size_t)n);          // per-frame stats, merged serially below
      PeakPickerIM picker = picker_;                    // Param is a deep-copy value type
      // SPEXTRACTOR_PICK_SERIAL=1 runs this loop on one thread: the A/B that separates picker
      // scheduling-sensitivity from downstream chaos.
      static const bool par_pick = std::getenv("SPEXTRACTOR_PICK_SERIAL") == nullptr;
      static const bool sched_set = []{ const bool st = std::getenv("SPEXTRACTOR_PICK_STATIC") != nullptr; omp_set_schedule(st ? omp_sched_static : omp_sched_dynamic, st ? 0 : 1); return true; }(); (void)sched_set;
      std::exception_ptr pick_err;                      // an exception escaping an OMP region aborts
      // chunk 1: with chunk 8 a 64-frame batch made only 8 chunks = 8 workers
      #pragma omp parallel for firstprivate(picker) schedule(runtime) if(par_pick)   // SPEXTRACTOR_PICK_STATIC=1 -> static (history-vs-race probe)
      for (int i = 0; i < n; ++i)
      {
        try
        {
          auto& s = buf_[(size_t)i];
          ensureIMArrayName(s);
          if (s.getIMPeakType() != IMPeakType::IM_CENTROIDED) picker.pickIMCluster(s);
          ensureIMArrayName(s);
          compacted[(size_t)i] = compactify(s, st[(size_t)i]);
          s.clear(true);                                // raw frame dies here, inside the loop
        }
        catch (...)
        {
          #pragma omp critical(pick_err)
          if (!pick_err) pick_err = std::current_exception();
        }
      }
      if (pick_err) std::rethrow_exception(pick_err);
      for (int i = 0; i < n; ++i)
      {
        stats_ += st[(size_t)i];
        windows_[key_[(size_t)i]].push_back(std::move(compacted[(size_t)i]));
      }
      flush_wall_() += phase_clock_() - _tf0;
      buf_.clear(); key_.clear();
    }

  protected:
    void consumeMS1Spectrum_(MapType::SpectrumType& s) override
    {
      // MS1 stays a PeakMap (MassTraceDetection needs it whole), but its pick is NOT small: 1,343
      // frames x ~690k raw peaks = 37% of all peaks, and it used to run serially here (~400 s of
      // LOAD, measured 2026-09-02). Buffer and pick in parallel like MS2; order is kept by index.
      ms1_buf_.push_back(std::move(s));
      ++frames_seen;
      if (ms1_buf_.size() >= kBatch_()) flushMS1_();
    }

    void flushMS1_()
    {
      const int n = (int)ms1_buf_.size();
      if (n == 0) return;
      const double _tf0 = phase_clock_();
      PeakPickerIM picker = picker_;
      std::exception_ptr pick_err;
      #pragma omp parallel for firstprivate(picker) schedule(dynamic, 1)
      for (int i = 0; i < n; ++i)
      {
        try
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
      for (auto& s : ms1_buf_) ms1_.addSpectrum(std::move(s));
      ms1_buf_.clear();
      flush_wall_() += phase_clock_() - _tf0;
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

    void ensureMapsAreFilled_() override { finish(); }

  public:
    /// Flush the buffered tails. Neither reader calls this for us: FullSwathFileConsumer reaches
    /// ensureMapsAreFilled_ only through retrieveSwathMaps, which this consumer never uses, so
    /// until 2026-09-09 the last `n mod kBatch` MS2 window spectra of every run were dropped
    /// silently (dataset D: 210 of 32,210 = the last 105 frames of the last window group, which
    /// the .d reader emits group-major; at batch 4096 it was 3,538 and two whole windows -- the
    /// "7.2% of Sage peptides" on record for that batch size was this, not the picker).
    void finish() { flushMS1_(); flush_(); }

  private:
    /// deliberate: 256 frames is ~1 GB of raw buffer at ~37k peaks/frame -- 2.5 work items per
    /// thread at 100 threads (64 gave 8 chunks of 8 = 8 workers), small next to the 12 GB compact
    /// store.
    /// [tile-0b] Overridable for the picker-purity measurement (SPEXTRACTOR_PICK_BATCH). With the
    /// tail flushed (finish()) the batch size must not change the output; 256 stays the default
    /// for the raw-buffer footprint.
    static size_t kBatch_() { static const size_t v = []{ const char* e = std::getenv("SPEXTRACTOR_PICK_BATCH");
      const long x = e ? std::atol(e) : 0; return x > 0 ? (size_t)x : (size_t)256; }(); return v; }
    std::vector<MapType::SpectrumType> buf_;
    std::vector<WinKey> key_;
    PeakPickerIM& picker_;
    std::vector<MapType::SpectrumType> ms1_buf_;   // MS1 frames awaiting the parallel pick
    map<WinKey, vector<CompactFrame>>& windows_;
    PeakMap& ms1_;
    CompactStats& stats_;
    std::function<WinKey(double, double, uint32_t)> keyfn_;
  };

  /// Per-window scoring statistics from IM-sorted fragment traces (see FragStats).
  /// What the scorer needs per window, now that a fragment's profile is a span in the window's
  /// own frame sequence: the Pearson denominator G (distinct frames carrying a REAL fragment
  /// point -- not the window's frame count), per-fragment mean and 1/norm over real points, and
  /// the precursor-to-fragment nearest-frame table. No copy of any profile: the arena is the grid.
  struct FragStats
  {
    vector<double> mean, invnorm;   ///< per fragment, over the full grid of G frames
    vector<int>    nearest_local;   ///< MS1-store frame -> window frame with real fragment data, or -1
    size_t G = 0;
  };

  FragStats buildFragStats(const vector<Trace>& frags, const TraceStore& wst, const TraceStore& ms1st, double delta_rt)
  {
    FragStats g;
    const size_t F = wst.frames();
    vector<char> used(F, 0);            // window frame carries >= 1 real fragment point
    for (const auto& f : frags)
      for (size_t k = 0; k < f.span(); ++k) if (real(wst, f, k)) used[f.frame0 + k] = 1;
    for (char u : used) g.G += u ? 1 : 0;
    const double G = (double)g.G;
    // Precursor points live on MS1 frames; each maps to the NEAREST window frame that carries real
    // fragment data, within gate:delta_rt, ties to the LATER frame -- the rule the old grid used.
    vector<uint32_t> uf; uf.reserve(g.G);
    for (uint32_t f = 0; f < F; ++f) if (used[f]) uf.push_back(f);
    g.nearest_local.assign(ms1st.frames(), -1);
    size_t hi = 0;
    for (size_t m = 0; m < ms1st.frames(); ++m)
    {
      const double t = ms1st.frame_rt[m];
      while (hi < uf.size() && wst.frame_rt[uf[hi]] < t) ++hi;
      double bd = delta_rt; int gi = -1;
      if (hi > 0)          { const double d = fabs(wst.frame_rt[uf[hi - 1]] - t); if (d <= bd) { bd = d; gi = (int)uf[hi - 1]; } }
      if (hi < uf.size())  { const double d = fabs(wst.frame_rt[uf[hi]] - t);     if (d <= bd) { bd = d; gi = (int)uf[hi]; } }
      g.nearest_local[m] = gi;
    }
    g.mean.resize(frags.size()); g.invnorm.resize(frags.size());
    #pragma omp taskloop default(shared)
    for (long ii = 0; ii < (long)frags.size(); ++ii)
    {
      const Trace& f = frags[(size_t)ii];
      double sum = 0, sumsq = 0;
      for (size_t k = 0; k < f.span(); ++k) { const double v = xv(wst, f, k); if (v > 0.0) { sum += v; sumsq += v * v; } }
      g.mean[ii] = sum / G;
      const double var = sumsq - G * g.mean[ii] * g.mean[ii];
      g.invnorm[ii] = var > 0 ? 1.0 / sqrt(var) : 0.0;  // 0 => constant/degenerate -> never correlates
    }
    return g;
  }
}

class TOPPSpeXtractor : public TOPPBase
{
public:
  TOPPSpeXtractor() :
    // official=false: SpeXtractor is a STANDALONE tool that links against OpenMS, not a tool IN
    // OpenMS, so it is deliberately absent from ToolHandler's official list. TOPPBase rejects an
    // unregistered name when official is left true -- which is how the rename surfaced that the
    // old name had been passing itself off as an official TOPP tool.
    TOPPBase("SpeXtractor", "Extracts pseudo-MS/MS spectra from diaPASEF (ion-mobility DIA) data.", false)
  {
    // TOPPBase reports the OpenMS version as the tool's own (--help, the ini `version` parameter,
    // the output's software entry) unless the tool sets its own. --help prints verboseVersion_,
    // which the base constructor derives from the OpenMS version, so both are set.
    version_ = SPEXTRACTOR_VERSION;
    // Both numbers, deliberately: a bug report needs the tool's version AND the OpenMS it was
    // built against, because this tool only builds against a patched development OpenMS and the
    // two move independently. `version_` alone is what goes into the mzML software entry.
    verboseVersion_ = String(SPEXTRACTOR_VERSION) + " (OpenMS " + VersionInfo::getVersion() + ")";
  }

protected:
  void registerOptionsAndFlags_() override
  {
    registerInputFile_("in", "<file>", "", "Input diaPASEF data (ion-mobility DIA; 1/K0 / VSSC): mzML, mzPeak, or a Bruker .d directory.");
#ifdef SPEXTRACTOR_WITH_MZPEAK
    setValidFormats_("in", {"mzML", "mzpeak", "d"});
#else
    setValidFormats_("in", {"mzML", "d"});      // stock OpenMS does not know the mzpeak format
#endif
    registerOutputFile_("out", "<file>", "", "Output pseudo-MS2 spectra. The FORMAT FOLLOWS THE "
                        "EXTENSION: .mzpeak (default) or .mzML. mzPeak is columnar and much smaller; "
                        "mzML is what DDA search engines read today, so pass an .mzML name (or "
                        "-out_type mzML) if the next step is a search.");
#ifdef SPEXTRACTOR_WITH_MZPEAK
    setValidFormats_("out", {"mzpeak", "mzML"});
#else
    setValidFormats_("out", {"mzML"});
#endif
    registerStringOption_("out_type", "<type>", "", "Force the output format instead of taking it "
                          "from the extension of -out. Empty = follow the extension; mzPeak if the "
                          "extension says nothing.", false);
    setValidStrings_("out_type", {"", "mzpeak", "mzML"});

    registerTOPPSubsection_("gate", "Precursor-to-fragment co-localization gate");
    // Conservative, documented defaults; these are placeholders pending a real-data sweep.
    registerDoubleOption_("gate:delta_im", "<1/K0>", 0.01, "Max |precursor - fragment| ion mobility difference (1/K0). (the reference implementation deltaApexIM default 0.01)", false);
    registerDoubleOption_("gate:delta_rt", "<sec>", 3.0, "Max |precursor - fragment| apex RT difference (seconds).", false);
    registerDoubleOption_("gate:min_correlation", "<0..1>", 0.3, "Min Pearson correlation of elution profiles. (the reference implementation ms1MS2Corr default 0.3; raise for cleaner but sparser spectra)", false);
    registerIntOption_("gate:min_correlation_points", "<n>", 3, "Min overlapping XIC points required to accept a correlation.", false, true);

    registerTOPPSubsection_("assembly", "Pseudo-spectrum assembly");
    registerIntOption_("assembly:min_fragments", "<n>", 3, "Emit a pseudo-spectrum only if it has at least this many fragments.", false);
    registerIntOption_("assembly:max_fragments", "<n>", 500, "Keep at most this many (top-ranked) fragments per pseudo-spectrum.", false);
    registerDoubleOption_("assembly:im_weight_sigma", "<1/K0>", 0.0, "Down-weight each emitted fragment's intensity by a Gaussian of its ion-mobility distance from the precursor, exp(-(dIM)^2 / 2 sigma^2). TIMS precedes fragmentation so a TRUE fragment shares the precursor's 1/K0 exactly; a co-isolating interferent at the edge of the gate:delta_im band is suppressed. WITHIN-spectrum (no fragment removed or redistributed across precursors) so it escapes the fan-out depletion that falsified competitive/apex/deconvolution, and directly un-buries faint true fragments under the engine's intensity top-150. 0 = off. Try ~0.005 (half the 0.01 IM gate).", false);
    registerDoubleOption_("assembly:corr_power", "<k>", 2.0, "Multiply each emitted fragment's intensity by corr^k (k>=0), where corr is the fragment-precursor co-elution score. EMIT-ONLY (excluded from the max_fragments cap key), so it preserves peak membership and only re-ranks the intensities the search engine sees toward well-correlating (true co-eluting) fragments and away from bright interferents; WITHIN-spectrum so it escapes fan-out depletion. DEFAULT 2.0 since 2026-07-28: validated on dataset D (tuning) + dataset A + dataset B (held out) at frozen k=2 -- +8-10%% Sage / +5-8%% MSFragger over base on all three, both engines, at controlled empirical FDR; k=2 sits one step below the ~k=3 Sage peak (the safe side of the crossover where c^k starts crushing the faint tail). 0 = off (pre-2026-07-28 behaviour). Dimensionless + bounded (c in [0.3,1]) so it transfers across instruments, unlike assembly:im_weight_sigma.", false);
    registerIntOption_("assembly:default_charge", "<z>", 2, "Charge for precursors with no isotope support: >0 assigns that charge (the reference implementation-style; 2 = most common); 0 = leave charge UNSET so the search engine searches its charge range and picks the right one (recovers 3+/4+ that a forced 2 would lose).", false);

    registerTOPPSubsection_("trace", "Mass-trace detection (see MassTraceDetection)");
    registerDoubleOption_("trace:mass_error_ppm", "<ppm>", 15.0, "m/z tolerance for trace detection.", false);
    registerDoubleOption_("trace:noise_threshold_int", "<int>", 100.0, "MS1 (precursor) noise intensity threshold.", false);
    registerDoubleOption_("trace:ms2_noise_threshold_int", "<int>", 10.0, "MS2 (fragment) noise threshold. Lower it (e.g. 50, 20) to recover weak fragments toward the reference implementation-like density; the grid-Pearson optimization keeps that affordable.", false);
    registerDoubleOption_("trace:min_length_sec", "<sec>", 3.0, "Minimum MS1 mass-trace length (seconds).", false, true);
    // the reference implementation runs MS2 with deliberately RELAXED constraints vs MS1 (Nat Commun 16:95). The OpenMS
    // apex gate is chrom_peak_snr*noise_threshold_int, so the stock snr=3.0 silently TRIPLES the
    // fragment threshold (a "noise 30" run really gated apices at 90). Decouple both for MS2. [recall]
    registerDoubleOption_("trace:ms1_chrom_peak_snr", "<x>", 3.0, "Apex signal-to-noise multiplier for MS1 traces (effective apex threshold = this x noise_threshold_int). OpenMS default 3.0.", false, true);
    registerDoubleOption_("trace:ms2_chrom_peak_snr", "<x>", 1.0, "Apex signal-to-noise multiplier for MS2 (fragment) traces. 1.0 = the ms2_noise_threshold_int you set IS the apex threshold; 3.0 would reproduce the old hidden 3x. Lower = more weak fragments recovered.", false);
    registerDoubleOption_("trace:ms2_min_length_sec", "<sec>", 0.0, "Minimum MS2 (fragment) mass-trace length (seconds). 0 = no length filter (the reference implementation-style relaxed MS2); MS1 keeps trace:min_length_sec.", false);
    registerStringOption_("trace:detector", "<mode>", "integer", "Mass-trace detector. 'integer' "
                          "(default) works on the global integer m/z axis: it finds a peak's candidate traces by "
                          "arithmetic instead of a tolerance search, and never converts the compact store back "
                          "to double m/z. It needs the vendor flight-time calibration and falls back to 'openms' "
                          "without it. 'openms' is OpenMS MassTraceDetection on a materialised PeakMap. These are "
                          "DIFFERENT algorithms, not reimplementations: they agree on about 85% of the union of "
                          "identified peptides, and which one identifies more depends on the search engine AND the "
                          "file. Integer costs ~40% less memory. See docs/MZ-AXIS-DESIGN.md.", false);
    setValidStrings_("trace:detector", {"openms", "integer"});
    registerStringOption_("trace:mz_estimator", "<mode>", "apex", "Reported m/z of a mass trace. "
                          "'apex' (default) uses the most intense peak's m/z; 'mean' the OpenMS intensity-weighted "
                          "centroid; 'median' the median. apex was chosen on measured identifications with both "
                          "search engines -- see docs/BASELINE.md. Affects EVERY reported precursor and "
                          "fragment m/z.", false);
    setValidStrings_("trace:mz_estimator", {"apex", "mean", "median"});
    registerDoubleOption_("trace:ms2_split_valleys", "<chrom_fwhm>", 7.0, "Split MS2 mass traces at chromatographic local minima via ElutionPeakDetection (which MassTraceDetection never does - it only terminates on outliers, so two peptides 25 s apart within the m/z tolerance MERGE). Value is chrom_fwhm in seconds; it sets both the Savitzky-Golay window and the local-extrema half-window. 0 = OFF. Try 6-8 (peaks here are 5-30 s). width_filtering is forced off so this only SPLITS, never deletes.", false);
    registerFlag_("diag:selftest_arena", "Run assertions on the MS1 arena compaction (compactUnreferenced) and exit: kept spans must survive a container order that differs from their offset order", true);
    registerDoubleOption_("trace:ms1_split_valleys", "<chrom_fwhm>", 7.0, "Split MS1 mass traces at chromatographic valleys via ElutionPeakDetection. DEFAULT 7.0 s: MassTraceDetection never splits at a local minimum, so two peptides eluting ~25 s apart within the m/z tolerance merge into ONE multi-modal trace, producing a merged precursor with the wrong monoisotope and charge. Measured +36.7% peptides on dataset B and +37.4% on dataset A at peptide-level FDR. Costs ~1.7x wall time and ~25% peak RAM. 0 = off.", false);
    registerDoubleOption_("trace:max_span_sec", "<sec>", 120.0, "Trim a mass trace to at most this many "
                          "seconds around its apex, AFTER detection and valley splitting have decided what the peak "
                          "is. Applies to precursor and fragment traces alike. An unbounded trace has no locality: "
                          "15.2%% of dataset D precursor traces span >45 s and the longest spans 1,244 s of a 1,860 s "
                          "gradient, while real chromatographic peaks here are 5-30 s -- so what a 120 s cap removes "
                          "is the far tail of a blob ElutionPeakDetection did not split. Trimming AFTER the fact is "
                          "deliberate: it leaves detection's peak ownership untouched, unlike terminating "
                          "extension, and unlike a length limit that DISCARDS an over-length trace and deletes "
                          "all signal at that m/z (the falsified direction). 0 = no cap. "
                          "CHANGES OUTPUT.", false);
    setMinFloat_("trace:max_span_sec", 0.0);
    registerDoubleOption_("trace:ms2_min_sample_rate", "<r>", -1.0, "MS2 min fraction of visited scans that must contain a peak (MassTraceDetection min_sample_rate). OpenMS default 0.5 hard-deletes gappy fragment traces; MEASURED: 0.3 and 0.1 both LOSE peptides (8,865 -> 8,735 at 0.3), so -1 (= OpenMS 0.5) is the default. Lowering it produces longer, more-merged traces with wrong apexes.", false);
    registerDoubleOption_("trace:ms1_min_sample_rate", "<r>", -1.0, "MS1 min_sample_rate. -1 = OpenMS default 0.5 (strict, MS1 stays strict).", false, true);

    // NB: "threads" is reserved by TOPPBase (the standard -threads option), so this lives under "perf".

    registerStringOption_("perf:malloc_trim", "<true/false>", "true",
                          "Return the allocator's free pages to the OS at the two phase boundaries (glibc only). "
                          "The window loop's allocations otherwise stack on top of everything the loading and MS1 "
                          "phases freed but the allocator kept: measured on a 2-h acquisition that floor is 138 GB "
                          "at the loop start, and trimming it first takes the run's PEAK from 265 to 186 GB. "
                          "IT IS NOT FREE: the loop then faults those pages back in cold (minor faults +26%), which "
                          "costs about 8.5% of wall time -- so this trades ~30% of peak memory for ~8% of runtime, "
                          "measured interleaved on one node. On by default because memory is what bounds this tool "
                          "(it decides how many isolation windows fit at once, and whether the run fits the machine "
                          "at all). Turn it off when time is the binding constraint. Output is byte-identical "
                          "either way.", false);
    setValidStrings_("perf:malloc_trim", {"true", "false"});
    registerStringOption_("perf:stream_load", "<true/false>", "true",
                          "Read the .d frame-by-frame via BrukerTimsFile::loadDIAStreaming, "
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
                       "The z=1 stratum carries ~2.8%% entrapment FDR at a nominal 1%% global cut (a lower true-match prior in that stratum under one pooled threshold, not peptide length; decoys "
                       "reproduce it), so per-charge FDR control downstream is advised. Old text: "
                       "docs/ISOTOPE-DUPLICATION-2026-09-03.md.", false);
    // [route-1] Only 25.7%% of the reference implementation's precursors are matched by us with the RIGHT m/z AND charge;
    // 17.2%% have the wrong charge and 22.9%% (decoy-corrected) the wrong monoisotope. A wrong charge or
    // mono gives a wrong NEUTRAL MASS, so the peptide can never be identified no matter how good the
    // fragments are. Partner-COUNTING cannot tell a real envelope from a coincidence; averagine shape
    // x isotope co-elution can.
    registerStringOption_("charge:scoring", "<mode>", "count", "Charge/monoisotope inference. 'count' is the partner-count heuristic (ties favour LOW charge, break-on-first-miss) and is the DEFAULT: measured against a DIA-NN reference on dataset B it gives 71.8% charge agreement vs 49.7% for 'envelope', and it eliminates the catastrophic 4->2 confusion (10,199 cases) that fabricates a ~-1198 Da phantom modification at m/z 600 in open search. 'envelope' scores each (charge, mono) hypothesis by averagine cosine x isotope co-elution and allows gapped envelopes; it was the default until 2026-07-21 and is kept for comparison. NOTE both are close to trivial: always answering z=2 scores 69.6%.", false);
    setValidStrings_("charge:scoring", {"envelope", "count"});
    registerStringOption_("charge:im_charge_veto", "<true/false>", "true", "Use the ion-mobility charge-state trend "
                          "lines to correct charge halving. In TIMS, 1+ and 2+ ions of the same m/z sit on separate 1/K0 lines "
                          "(~+0.29 Vs/cm2 apart). The count walk calls a real 2+ envelope z=1 whenever its M+1 (+0.5017) is "
                          "missing or already claimed and its M+2 (+1.0034) is present -- measured at ~13%% of z=1 calls on a "
                          "2-hour file, 60%% of them below m/z 750 where a 1+ cannot be scored at all. The 2+ and 3+ lines are "
                          "fitted per run from the run's own confident calls (>= 3 isotopes; 25-Th bin medians, MAD residual "
                          "scale), and a z=1 call whose 1/K0 lies within charge:im_veto_band sigma of the 2+ (3+) line is "
                          "re-assigned 2+; one on the 3+ band is dropped (re-calling it 3+ identified nothing on two files). "
                          "Genuine 1+ ions are untouched: 0.0-0.6%% of identified z=1 peptides sit on the 2+ band.", false);
    setValidStrings_("charge:im_charge_veto", {"true", "false"});
    registerDoubleOption_("charge:im_veto_band", "<sigma>", 2.5, "Half-width of the 2+/3+ mobility band, in MAD-sigma of "
                          "the confident calls' residuals (measured residual sd ~0.037 1/K0 against a 1+/2+ separation of ~0.29).", false);
    registerStringOption_("assembly:require_isotope_support", "<true/false>", "true",
                          "Drop precursor hypotheses with NO isotope partner -- the 'guessed' "
                          "singletons. ON BY DEFAULT since 2026-09-04, when the shipped default (off) was "
                          "measured for the first time and found to be 6.9x SLOWER and worse on both engines: "
                          "dataset D off = 1,255,577 spectra, 36:25 wall, 6.0x occupancy, Sage 12,212 / MSFragger "
                          "12,148; on = 655,776 spectra, 5:15, 65.7x, Sage 12,482 / MSFragger 12,337. An "
                          "earlier measurement (2026-07-26, at 10,036 peptides, before the charge gate, the "
                          "apex estimator and the integer detector) had put the cost at -0.78% peptides; the "
                          "sign has since flipped. Set false to keep the guessed singletons.", false);
    setValidStrings_("assembly:require_isotope_support", {"true", "false"});
    registerDoubleOption_("charge:mono_averagine_guard", "<slack>", 0.0, "Reject a leftward isotope step (the walk that defines the MONOISOTOPE in charge:scoring=count) when the candidate peak is too weak to be a real lighter isotope under averagine. The partner search matches m/z, RT and IM but NEVER intensity, so it can latch onto a noise peak or a co-eluting species one isotope spacing below the true monoisotope -- making the reported precursor mass ~1.00335 Da TOO LIGHT. Closed search hides this (the engine enumerates isotope_errors and corrects it for free); OPEN/blind search turns it into a phantom -1.003 Da modification, and it is our single largest open-search delta-mass artefact on dataset D (8.20%% isotope-shifted PSMs vs the reference implementation's 3.46%%). The bound is averagine's LOOSEST: stepping from isotope m+1 to m the lighter peak is >= (m+1)/lambda times the heavier one, minimised at m=0 -> 1/lambda (lambda = 0.000594*neutral mass), so a value of 1.0 enforces exactly that minimum and never rejects a legitimate envelope; smaller values add slack for noise. 0 = off (old behaviour).", false);
    registerFlag_("charge:mono_averagine_select", "Choose the MONOISOTOPE by averagine envelope fit over the whole isotope run found by the charge:scoring=count walk, instead of taking the furthest-left peak reached. 'Furthest-left' is a STOPPING rule and can only trade over-reach (mono ~1.003 Da too LIGHT, a phantom -1 Da modification in open search) for under-reach (+1.003 Da) -- measured: an averagine STOPPING guard cut the -1 artefact 64%% but tripled +1, because a walk that halts early also leaves the M+1 peak unconsumed so it seeds its own too-heavy precursor. This is a SCORING decision instead: score every candidate mono position in the run by cosine against the averagine envelope and keep the best. Every found peak is still consumed, so de-isotoping and emission are unchanged -- only the reported precursor mass moves.");
    registerDoubleOption_("charge:iso_im_tolerance", "<1/K0>", 0.05, "IM tolerance for matching isotope partners. Default 0.05 (= 5x the fragment gate). 0.01 is arguable -- isotopes of one species share mobility, so 0.05 can admit cross-species partners -- but 0.01 has not been measured; change it only behind a peptide-set gate.", false);

    // Bounds, not documentation: without these a negative count wraps through `Size` (min_fragments
    // -1 becomes ~1.8e19 and nothing is ever emitted) and a negative tolerance silently gates
    // everything out. Both fail as an empty-but-valid result, the worst failure mode here.
    setMinInt_("assembly:min_fragments", 1);
    setMinInt_("assembly:max_fragments", 1);
    setMinInt_("assembly:default_charge", 0);
    setMinInt_("max_charge", 1);
    setMinInt_("perf:trace_bands", 0);      // 0 = auto (documented)
    setMinFloat_("gate:delta_im", 0.0);
    setMinFloat_("gate:delta_rt", 0.0);
    setMinFloat_("gate:min_correlation", -1.0);
    setMaxFloat_("gate:min_correlation", 1.0);
    setMinFloat_("charge:iso_im_tolerance", 0.0);
    setMinFloat_("trace:ms1_chrom_peak_snr", 0.0);
    setMinFloat_("trace:ms2_chrom_peak_snr", 0.0);
    setMinFloat_("trace:ms2_noise_threshold_int", 0.0);
    setMinFloat_("trace:noise_threshold_int", 0.0);
    setMinInt_("perf:ms1_trace_bands", 0);      // 0 = auto (documented)
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
                              double split_valleys, String* span_log = nullptr, int bands = 1)
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
    // after detectTraces_, and ms1_traces are canonically sorted before inferPrecursors_.
    auto do_split = [&](vector<MassTrace>& in) -> vector<MassTrace> {
      if (split_valleys <= 0.0 || in.empty()) return std::move(in);
      ElutionPeakDetection epd;
      epd.setLogType(ProgressLogger::NONE);
      Param ep = epd.getParameters();
      ep.setValue("chrom_fwhm", split_valleys);
      ep.setValue("width_filtering", "off");
      ep.setValue("masstrace_snr_filtering", "false");
      epd.setParameters(ep);
      vector<MassTrace> out; out.reserve(in.size());
      epd.detectPeaks(in, out);
      return out;
    };

    vector<MassTrace> mts;
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
      for (const auto& s : map)
        for (Size i = 0; i < s.size(); i += 97) sample.push_back(s[i].getMZ());
      sort(sample.begin(), sample.end());
      vector<double> edge(bands + 1);
      if (sample.empty()) { edge.assign(bands + 1, 0.0); }
      else
        for (int b = 0; b <= bands; ++b)
          edge[b] = sample[std::min(sample.size() - 1, (size_t)((double)b / bands * sample.size()))];
      edge.front() = 0.0; edge.back() = std::numeric_limits<double>::max();
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
          const double lo = edge[b] - edge[b] * ppm * 1e-6 * 20.0;
          const double hi = edge[b + 1] + edge[b + 1] * ppm * 1e-6 * 20.0;
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
      vector<vector<PeakMap>>().swap(csub);
      tt_dist = tt_s(_td0, tt_now());
      auto _tm0 = tt_now();
      vector<vector<MassTrace>> per(bands);
      #pragma omp taskloop grainsize(1) default(shared)
      for (int b = 0; b < bands; ++b)
      {
        MassTraceDetection m2; m2.setLogType(ProgressLogger::NONE); m2.setParameters(p);
        vector<MassTrace> t;
        sub[b].sortSpectra();
        if (sub[b].size() < 3) { sub[b].clear(true); continue; }   // MTD aborts below 3 spectra
        m2.run(sub[b], t);
        sub[b].clear(true);
        // keep only traces whose centroid lies in this band's CORE -> no duplicates from the halo
        for (auto& mt : t)
        {
          const double c = mt.getCentroidMZ();
          if (c >= edge[b] && c < edge[b + 1]) per[b].push_back(std::move(mt));
        }
      }
      tt_mtd = tt_s(_tm0, tt_now());
      auto _tg0 = tt_now();
      size_t tot = 0; for (const auto& v : per) tot += v.size();
      mts.reserve(tot);
      for (auto& v : per) { for (auto& t : v) mts.push_back(std::move(t)); vector<MassTrace>().swap(v); }
      tt_gather = tt_s(_tg0, tt_now());
    }
    else
    {
      if (map.size() >= 3) mtd.run(map, mts);   // MTD aborts below 3 spectra; a tiny input is not an error
      map.clear(true); // [compact] dead from here; ~1.1 GB/window freed before the EPD peak
    }

    // [way-2] SPLIT MASS TRACES AT CHROMATOGRAPHIC VALLEYS.
    // MassTraceDetection never splits at a local minimum: it terminates only on consecutive-miss
    // outliers or sample_rate, and max_trace_length only DISCARDS. So two peptides eluting 25 s apart
    // within the m/z tolerance merge into ONE multi-modal trace, whose XIC then correlates with
    // everything under it. ElutionPeakDetection is the OpenMS stage that actually smooths and splits
    // at local minima - we never ran it. width_filtering is forced to "off" because "fixed" is a
    // DELETION filter ([min_fwhm,max_fwhm]) and blanket deletion is on the falsified list.
    // [epd-parallel] Valley-splitting is the dominant serial phase (EPD-off dataset D 20:46 vs 28:40 for
    // MS2 alone). It is per-trace independent, so run it as a BALANCED parallel-for over the merged
    // traces -- more chunks than threads + dynamic schedule so no chunk's long traces stall the
    // rest. Lock-free (patched OpenMS), so the 8 concurrent windows above never contend. Trace SET
    // is identical to one serial split (per-trace, deterministic); only order differs, and both
    // consumers are order-independent (MS2 re-sorted after detectTraces_, MS1 sorted before
    // inferPrecursors_). Reverted once for a -0.8% "regression" that was actually the ms1_traces
    // determinism bug, now fixed.
    auto _ts0 = tt_now();
    if (split_valleys > 0.0 && mts.size() > 1)
    {
      const int nchunk = std::max(1, bands * 4);      // 4x chunks vs threads -> dynamic load balance
      const size_t n_in = mts.size();
      vector<vector<MassTrace>> parts(nchunk);
      #pragma omp taskloop grainsize(1) default(shared)
      for (int ci = 0; ci < nchunk; ++ci)
      {
        const size_t lo = (size_t)ci * n_in / nchunk, hi = (size_t)(ci + 1) * n_in / nchunk;
        if (lo >= hi) continue;
        vector<MassTrace> chunk(std::make_move_iterator(mts.begin() + lo),
                                std::make_move_iterator(mts.begin() + hi));
        parts[ci] = do_split(chunk);
      }
      size_t tot = 0; for (auto& pth : parts) tot += pth.size();
      vector<MassTrace> out; out.reserve(tot);
      for (auto& pth : parts) { for (auto& t : pth) out.push_back(std::move(t)); vector<MassTrace>().swap(pth); }
      if (span_log) *span_log += " | valley-split " + String(n_in) + " -> " + String(out.size())
                               + " traces (" + String((int)(1000.0 * out.size() / std::max<size_t>(n_in,1)) / 10.0) + "%)";
      mts.swap(out);
    }
    tt_split = tt_s(_ts0, tt_now());
    writeLogInfo_("[tstage] " + String(bands) + " bands -> " + String(mts.size()) + " traces: edges "
                  + String(tt_edge) + " s | distribute " + String(tt_dist) + " s (serial) | detect "
                  + String(tt_mtd) + " s | gather " + String(tt_gather) + " s (serial) | valley-split "
                  + String(tt_split) + " s");
    // [merged-trace] instrumentation: is trace merging actually happening? Log the RT-span
    // distribution. Peaks are 5-30 s here, so a large p90/max means multi-modal merged traces.
    if (!mts.empty())
    {
      vector<double> spans;
      spans.reserve(mts.size());
      for (const auto& mt : mts)
      {
        double lo = 1e30, hi = -1e30;
        for (Size i = 0; i < mt.getSize(); ++i) { double r = mt[i].getRT(); lo = min(lo, r); hi = max(hi, r); }
        spans.push_back(hi - lo);
      }
      sort(spans.begin(), spans.end());
      size_t n = spans.size();
      size_t over45 = spans.end() - lower_bound(spans.begin(), spans.end(), 45.0);
      // the tail fractions the trace:max_span_sec cap is priced against
      size_t over120 = spans.end() - lower_bound(spans.begin(), spans.end(), 120.0);
      size_t over240 = spans.end() - lower_bound(spans.begin(), spans.end(), 240.0);
      if (span_log) *span_log = "traces=" + String(n) + " span_s median=" + String(spans[n/2])
                      + " p90=" + String(spans[(size_t)(0.9*n)]) + " p99=" + String(spans[(size_t)(0.99*n)])
                      + " max=" + String(spans.back())
                      + " frac>45s=" + String((int)(1000.0*over45/n)/10.0) + "%"
                      + " frac>120s=" + String((int)(10000.0*over120/n)/100.0) + "%"
                      + " frac>240s=" + String((int)(10000.0*over240/n)/100.0) + "%";
    }
    vector<Trace> out;
    out.reserve(mts.size());
    // toTrace only reads, so each MassTrace is dead the moment it is converted. Releasing it here
    // keeps the peak at one MassTrace instead of the whole vector plus the whole Trace vector; the
    // same discipline is already applied to the band and chunk vectors above.
    //
    // This loop is SERIAL and a parallel version was measured and rejected (2026-09-09). Splitting
    // it into a parallel "compute coordinates and points" half and a serial "append the span" half
    // is output-identical -- verified -- but 17% SLOWER on the MS1 phase of a 2-hour acquisition
    // (50.5 s -> 59.3 s, parallelism 18.8x -> 15.5x) even though its CPU seconds fell. The per-trace
    // work is a handful of binary searches, too little to cover the cost of the point-list buffers:
    // 22 million small vector allocations move from one thread to all of them and contend in the
    // allocator, and the parallel halves write adjacent doubles in the coordinate arrays. A second
    // version using one chunked flat buffer, with no per-trace allocation at all, was measured too
    // and is also no better (168.2 s serial vs 171.6 s, dataset D, three reps interleaved). The
    // per-trace work is a few binary searches over a table that stays in cache; the coordination
    // costs more than the work, and the serial walk over `mts` prefetches where a parallel one
    // scatters. See docs/BASELINE.md.
    for (size_t i = 0; i < mts.size(); ++i) { out.push_back(toTrace(mts[i], store)); mts[i] = MassTrace(); }   // move-assign an empty one: the payload goes now, not at return
    return out;
  }

  /// [route-1] Averagine isotope envelope, Poisson approximation: for neutral mass M the expected
  /// number of 13C is lambda ~ 0.000594*M, giving relative intensities [1, l, l^2/2, l^3/6, ...].
  /// This is what lets us pick the MONOISOTOPE: the mono is NOT always the most intense peak
  /// (above ~1800 Da M+1 exceeds M), so intensity-ranking alone mis-assigns it.
  static void averagineRatios(double neutral_mass, int n, vector<double>& out)
  {
    const double lam = std::max(0.10, 0.000594 * neutral_mass);
    out.assign(n, 0.0);
    double term = 1.0;
    for (int k = 0; k < n; ++k) { out[k] = term; term *= lam / (double)(k + 1); }
    double mx = 0.0; for (double v : out) mx = std::max(mx, v);
    if (mx > 0) for (double& v : out) v /= mx;
  }

  static double cosineSim(const vector<double>& a, const vector<double>& b)
  {
    double dot = 0, na = 0, nb = 0;
    for (size_t i = 0; i < a.size() && i < b.size(); ++i) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i]; }
    return (na > 0 && nb > 0) ? dot / (sqrt(na) * sqrt(nb)) : 0.0;
  }

  /// [route-1] Pearson of two XICs over their OVERLAPPING RT points, properly mean-centred on the
  /// overlap (NOT zero-padded over a global grid). Isotopes of one peptide must co-elute; a
  /// coincidental peak at the right m/z spacing usually does not.
  /// Pearson correlation of two elution profiles over their shared frames. On a global axis the
  /// intersection is an integer merge -- no RT comparison, no tolerance, no binary search.
  static double xicCorr(const TraceStore& s, const Trace& a, const Trace& b, double /*rt_tol*/)
  {
    // both are MS1 traces on the same frame table: the shared frames are the overlap of the two
    // spans, and a frame counts only where BOTH have a real point -- the old index intersection
    double sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0; int m = 0;
    const uint32_t lo = std::max(a.frame0, b.frame0);
    const uint32_t hi = std::min(a.frame0 + a.len, b.frame0 + b.len);
    for (uint32_t f = lo; f < hi; ++f)
    {
      const double x = xv(s, a, f - a.frame0), y = xv(s, b, f - b.frame0);
      if (x > 0.0 && y > 0.0) { sx += x; sy += y; sxx += x * x; syy += y * y; sxy += x * y; ++m; }
    }
    if (m < 3) return -2.0;
    const double cov = sxy - sx * sy / m, vx = sxx - sx * sx / m, vy = syy - sy * sy / m;
    return (vx > 0 && vy > 0) ? cov / std::sqrt(vx * vy) : -2.0;
  }

  /// [route-1] Isotope/charge inference on MS1 traces. Scores each (charge, monoisotope) hypothesis
  /// by averagine-shape agreement x isotope-XIC co-elution, instead of counting partners.
  vector<Precursor_> inferPrecursors_(const vector<Trace>& ms1, const TraceStore& ms1st, int max_charge,
                                      double delta_rt, double iso_im_tol, double mass_ppm,
                                      bool envelope_scoring)
  {
    const double ISO = 1.0033548;
    const double PROTON_ = 1.00727646;
    const size_t N = ms1.size();

    // m/z-sorted index for O(log N) isotope-partner lookup (avoids O(N^2) over all MS1 traces).
    auto _pi_t0 = std::chrono::steady_clock::now();
    vector<size_t> by_mz(N);
    for (size_t i = 0; i < N; ++i) by_mz[i] = i;
    sort(by_mz.begin(), by_mz.end(), [&](size_t a, size_t b) { return ms1[a].mz < ms1[b].mz; });
    vector<double> sorted_mz(N);
    for (size_t i = 0; i < N; ++i) sorted_mz[i] = ms1[by_mz[i]].mz;
    // [soa] findPartner's candidate scan walks `by_mz` and dereferences each candidate's RT and
    // IM -- two 8-byte gate fields out of a 40-byte record, reached through an index, i.e. one
    // cache miss per candidate per field. This phase is single-threaded and 26% of TNBC wall, so lay the two gate
    // fields out in m/z order next to `sorted_mz` and scan them sequentially. Same values, same
    // order, same first match: output-identical by construction. 16 B/trace of transient state.
    vector<double> sorted_rt(N), sorted_im(N);
    for (size_t i = 0; i < N; ++i) { const Trace& t = ms1[by_mz[i]]; sorted_rt[i] = rtOf(ms1st, t); sorted_im[i] = t.im; }
    // [mzidx] A DIRECTLY COMPUTED integer index over `sorted_mz` -- no search to find the bucket
    // and no floating-point arithmetic to compute it. The greedy walk below is the single-threaded
    // residue of this phase (measured: 138.3 s of 155.7 on a 2-hour file) and it spent that in
    // `lower_bound`/`upper_bound` over 22e6 doubles: ~25 probes, each a cache miss, for up to 50
    // partner queries per seed.
    //
    // The key is the top bits of the IEEE-754 bit pattern, which for positive doubles is monotone
    // non-decreasing in the value -- one load and one shift, exact, with no rounding of its own.
    // Because the exponent leads, the bucket width is RELATIVE (2^-20 of the binade, ~0.5 mDa at
    // m/z 512-1024), which is the right shape for a ppm tolerance and keeps the occupancy even
    // across the m/z range in a way a uniform-in-m/z grid does not.
    //
    // NOTE: the natural key here is the flight-time bin itself -- an integer the instrument
    // already produced, with no calibration applied -- but `Trace::tof` is 0 on the OpenMS MS1
    // path (`toTrace` never sets it), and MS1 tracing still runs that path by default. Keying on
    // tof, and deferring the calibrated m/z to the end, becomes available once MS1 goes through
    // the integer detector.
    //
    // The POSITION found is unchanged: the key is monotone, so every element below the query's
    // bucket is strictly less than the query and every element above is strictly greater; the
    // standard-library search then runs on a sub-range that provably contains the answer.
    const double mz_lo = N ? sorted_mz.front() : 0.0, mz_hi = N ? sorted_mz.back() : 1.0;
    unsigned kshift = 32;
    auto rawKey = [](double x, unsigned sh) { uint64_t b; std::memcpy(&b, &x, sizeof b); return b >> sh; };
    while (kshift < 52 && (rawKey(mz_hi, kshift) - rawKey(mz_lo, kshift)) > (1u << 23)) ++kshift;
    const uint64_t klo = N ? rawKey(mz_lo, kshift) : 0;
    const size_t kspan = N ? (size_t)(rawKey(mz_hi, kshift) - klo) : 0;
    auto bucketOf = [&](double x) -> size_t {
      if (!(x > mz_lo)) return 0;
      const uint64_t k = rawKey(x, kshift);
      return k >= klo + kspan ? kspan : (size_t)(k - klo);
    };
    vector<uint32_t> bstart(kspan + 2, 0);
    {
      size_t i = 0;
      for (size_t b = 0; b <= kspan; ++b) { while (i < N && bucketOf(sorted_mz[i]) < b) ++i; bstart[b] = (uint32_t)i; }
      bstart[kspan + 1] = (uint32_t)N;
    }
    auto lbmz = [&](double x) -> size_t {
      if (N == 0 || x <= mz_lo) return 0;
      if (x > mz_hi) return N;
      const size_t b = bucketOf(x);
      return (size_t)(std::lower_bound(sorted_mz.begin() + bstart[b], sorted_mz.begin() + bstart[b + 1], x) - sorted_mz.begin());
    };
    auto ubmz = [&](double x) -> size_t {
      if (N == 0 || x < mz_lo) return 0;
      if (x >= mz_hi) return N;
      const size_t b = bucketOf(x);
      return (size_t)(std::upper_bound(sorted_mz.begin() + bstart[b], sorted_mz.begin() + bstart[b + 1], x) - sorted_mz.begin());
    };
    auto _pi_t1 = std::chrono::steady_clock::now();

    // The apex intensity now lives in the store's arena. This phase reads it O(N log N) times in the
    // sort below and again in every isotope walk, so pull it into one contiguous float array first:
    // 4 B per trace, sequentially laid out, against 8 B scattered through 56-byte records before.
    vector<float> inten(N);
    for (size_t i = 0; i < N; ++i) inten[i] = (float)intensityOf(ms1st, ms1[i]);
    vector<size_t> order(N);
    for (size_t i = 0; i < N; ++i) order[i] = i;
    sort(order.begin(), order.end(), [&](size_t a, size_t b) {
      if (inten[a] != inten[b]) return inten[a] > inten[b];
      if (ms1[a].mz != ms1[b].mz) return ms1[a].mz < ms1[b].mz;
      return a < b; // total order so greedy isotope assignment is deterministic
    });

    auto _pi_t2 = std::chrono::steady_clock::now();
    vector<bool> used(N, false);
    vector<Precursor_> out;
    // [spec 2026-09-07] ORDERED SPECULATION. The claim loop is greedy -- each seed marks its isotope
    // partners used, so what a later seed sees depends on every earlier one -- and it was the
    // single-threaded residue of this phase (measured 112-138 s of ~150). It is nevertheless
    // parallelisable EXACTLY, because the only mutable state a seed reads is `used`, and `used` is
    // monotone (false -> true, never back).
    //
    // Evaluate a batch of seeds concurrently against a frozen `used`, recording for each seed the
    // partner indices its searches actually returned. Then walk the batch in the ORIGINAL order and
    // commit: if the seed is now used, skip it exactly as the sequential loop would; otherwise, if
    // any recorded partner has since been claimed, re-evaluate that one seed against the current
    // `used`. Everything else is unchanged, so the emitted sequence and the final bitmap are
    // identical to the sequential algorithm.
    //
    // Why the dependency set is just the returned partners: findPartner reads `used[j]` only for
    // candidates that already passed the RT/IM gate, and it returns the FIRST such j that is unused.
    // A call that returned j depended on used[j] being false -- that can change, so it is recorded.
    // A call that returned -1 saw every candidate either fail the gate (no read) or already used;
    // both are stable under a monotone bitmap, so -1 stays -1 and needs no dependency.
    struct SeedRes { vector<Precursor_> emit; vector<size_t> claims; vector<size_t> deps; };
    auto evalSeed = [&](size_t seed, SeedRes& R)
    {
      R.emit.clear(); R.claims.clear(); R.deps.clear();
      // do/while(0): the body below is the sequential loop body VERBATIM, and its seed-level
      // `continue` statements exit this wrapper exactly as they used to exit one loop iteration,
      // while `continue` inside the body's own inner loops keeps binding to those loops.
      do
      {
      if (used[seed]) continue;
      const Trace& s = ms1[seed];
      const double s_rt = rtOf(ms1st, s);     // [soa-rt] hoisted: the candidate scan reads it per probe
      const double tol = s.mz * mass_ppm * 1e-6;

      // Find an unused isotope partner near `target` m/z, co-localized in RT and IM (binary-search
      // the m/z index, scan only the ppm-window candidates); -1 if none.
      auto findPartner = [&](double target) -> long {
        size_t klo = lbmz(target - tol), khi = ubmz(target + tol);   // [mzidx] same positions, local search
        for (size_t k = klo; k < khi; ++k)
        {
          if (fabs(sorted_rt[k] - s_rt) > delta_rt || fabs(sorted_im[k] - s.im) > iso_im_tol) continue;   // [soa]
          size_t j = by_mz[k];
          if (used[j] || j == seed) continue;
          { R.deps.push_back((size_t)j); return (long)j; }
        }
        return -1;
      };

      // [baseline-fix v2] When envelope scoring is OFF, run the ORIGINAL algorithm end-to-end, not
      // just the original scoring. The previous attempt reverted only the score while keeping the new
      // candidate generation (gapped walk + lead 0..3), producing a THIRD algorithm: 2.52M MS1 traces
      // -> 1.21M precursors, 967,956 spectra, 7,308 peptides (baseline: 1.76M -> 956k, 741k, 9,103).
      // The original is: contiguous walk with BREAK-ON-FIRST-MISS, seed is always the starting point
      // (no lead offsets), monoisotope = furthest-LEFT partner reached, pick z by partner COUNT with
      // ties favouring the LOWEST z.
      if (!envelope_scoring)
      {
        int best_z = 0, best_n = 1;
        double best_mono = s.mz;
        vector<size_t> best_partners;
        for (int z = 1; z <= max_charge; ++z)
        {
          vector<size_t> partners;
          double mono = s.mz;
          double prev_int = inten[seed];
          vector<long> lefts;
          for (int k = 1; k <= 5; ++k)          // lighter partners define the monoisotope
          {
            long j = findPartner(s.mz - k * ISO / z);
            if (j < 0) break;                   // BREAK on first miss (contiguous only)
            // [mono-guard] A LEFTWARD step asserts the new peak is a LIGHTER ISOTOPE of the same
            // peptide, but findPartner only checks m/z, RT and IM -- never intensity. So the walk
            // happily latches onto a noise peak or a co-eluting species' peak that happens to sit
            // one isotope spacing below, and the monoisotope ends up one isotope TOO LIGHT.
            // Closed search hides this (the engine enumerates isotope_errors [-1,2] and corrects it
            // for free); OPEN search cannot, so it becomes a phantom -1.003 Da "modification" --
            // measured as our single largest open-search delta-mass artefact on dataset D.
            // Averagine bounds how weak a genuine lighter isotope may be: stepping from isotope m+1
            // to m, theo[m]/theo[m+1] = (m+1)/lambda, minimised at m=0 -> 1/lambda. Requiring the
            // candidate to reach that (times a slack factor) rejects the latch without touching a
            // real envelope.
            if (mono_guard_ > 0.0)
            {
              const double neutral = (s.mz - k * ISO / z) * z - z * PROTON_;
              const double lam = std::max(0.10, 0.000594 * neutral);
              if (inten[j] < mono_guard_ * prev_int / lam) break;
            }
            lefts.push_back(j);
            partners.push_back((size_t)j); mono = ms1[j].mz; prev_int = inten[j];
          }
          vector<long> rights;
          for (int k = 1; k <= 5; ++k)          // heavier partners add confidence
          {
            long j = findPartner(s.mz + k * ISO / z);
            if (j < 0) break;
            rights.push_back(j);
            partners.push_back((size_t)j);
          }
          // [mono-select] Choosing the monoisotope by "furthest-left peak reached" is a STOPPING
          // rule, and a stopping rule can only trade over-reach (-1.003 Da) for under-reach (+1.003
          // Da) -- measured: the guard above cut the -1 artefact 64% but tripled +1, because a walk
          // that stops early also leaves the M+1 peak unconsumed, so it later seeds its OWN
          // precursor one isotope too heavy. Make it a SCORING decision instead: walk the full run,
          // then pick which peak IS the monoisotope by averagine fit of the envelope starting
          // there. Corrects both directions, and every found peak is still marked used below, so
          // de-isotoping and emission are untouched (only the reported mono m/z changes).
          if (mono_select_ && !lefts.empty())
          {
            const int nL = (int)lefts.size();
            vector<double> runI;                                  // ascending m/z: lefts, seed, rights
            for (int i = nL - 1; i >= 0; --i) runI.push_back(inten[lefts[i]]);
            runI.push_back(inten[seed]);
            for (long j : rights) runI.push_back(inten[j]);
            double best_cos = -1.0; int best_c = nL;              // default: seed is the mono
            vector<double> theo, obs;
            for (int c = 0; c <= nL; ++c)                         // mono cannot be right of the seed
            {
              const int len = std::min(4, (int)runI.size() - c);
              if (len < 2) break;                                 // need >=2 peaks to score a shape
              const double neutral = (s.mz - (double)(nL - c) * ISO / z) * z - z * PROTON_;
              averagineRatios(neutral, len, theo);
              obs.assign(runI.begin() + c, runI.begin() + c + len);
              double mx = 0.0; for (double v : obs) mx = std::max(mx, v);
              if (mx <= 0.0) continue;
              for (double& v : obs) v /= mx;
              // The SAME trap the envelope scorer documents below: the cosine of a short
              // vector is nearly always high, and `len` SHRINKS as the candidate mono moves right,
              // so raw cosine systematically prefers a too-HEAVY mono. Measured (first cut, raw
              // cosine): -1 bin 7,616 -> 2,314 as intended, but +1 exploded 4,697 -> 21,591 and the
              // unmodified fraction fell 31.2% -> 26.4%, at flat emission -- i.e. precursors that
              // were CORRECT were pushed one isotope right. Weight by evidence exactly as the
              // envelope scorer does: (n-1)/3 capped at 1 (4 isotopes 1.00, 3 -> 0.67, 2 -> 0.33).
              const double cs = cosineSim(obs, theo) * std::min(1.0, (double)(len - 1) / 3.0);
              if (cs > best_cos) { best_cos = cs; best_c = c; }
            }
            mono = (best_c < nL) ? ms1[lefts[nL - 1 - best_c]].mz : s.mz;
          }
          const int n = 1 + (int)partners.size();
          if (n > best_n) { best_n = n; best_z = z; best_mono = mono; best_partners = partners; }
        }
        Precursor_ pc0;
        pc0.trace_idx = seed;
        pc0.rt = s_rt; pc0.im = s.im;
        pc0.mono_mz = best_mono;
        // Carry the bin of whichever trace the monoisotope call landed on, so the exported mass is
        // calibrated from a measurement rather than from a number that passed through the gates.
        pc0.mono_tof = ms1[seed].tof; pc0.mono_b = bOf(ms1st, ms1[seed]);
        for (size_t j : best_partners)
          if (ms1[j].mz == best_mono) { pc0.mono_tof = ms1[j].tof; pc0.mono_b = bOf(ms1st, ms1[j]); break; }
        pc0.charge = best_z;                    // 0 => unknown, default_charge applied later
        pc0.n_isotopes = best_n;                // [Q4] envelope confidence for the mono call
        R.emit.push_back(pc0);
        for (size_t j : best_partners) R.claims.push_back(j);   // de-isotope
        continue;
      }

      struct Hyp { int z; double mono; double score; vector<size_t> partners; };
      vector<Hyp> hyps;
      vector<double> theo, obs(4), obsn(4);

      for (int z = 1; z <= max_charge; ++z)
      {
        // [route-1] GAPPED envelopes: no break-on-first-miss (a sub-threshold M+1 with a present
        // M+2 previously killed the whole walk). Try the seed AND up to 3 isotopes below it as the
        // monoisotope candidate; averagine decides which one really is the mono.
        for (int lead = 0; lead <= 3; ++lead)
        {
          const double mono_mz = s.mz - lead * ISO / z;
          long mono_idx = (lead == 0) ? (long)seed : findPartner(mono_mz);
          if (lead > 0 && mono_idx < 0) continue;
          const double neutral = mono_mz * z - z * PROTON_;
          if (neutral < 400.0 || neutral > 6000.0) continue;

          vector<size_t> members;
          vector<long> iso_idx(4, -1);
          obs.assign(4, 0.0);
          obs[0] = inten[mono_idx];
          iso_idx[0] = mono_idx;
          if ((size_t)mono_idx != seed) members.push_back((size_t)mono_idx);
          int found = 1;
          for (int k = 1; k <= 3; ++k)
          {
            long j = findPartner(mono_mz + k * ISO / z);
            if (j >= 0) { obs[k] = inten[j]; iso_idx[k] = j; ++found;
                          if ((size_t)j != seed) members.push_back((size_t)j); }
          }
          if (found < 2) continue;   // need >=2 isotopes before a shape can be scored

          averagineRatios(neutral, 4, theo);
          double mx = 0.0; for (double v : obs) mx = std::max(mx, v);
          if (mx <= 0) continue;
          for (int k = 0; k < 4; ++k) obsn[k] = obs[k] / mx;
          const double cos_sim = cosineSim(obsn, theo);

          double csum = 0.0; int cn = 0;
          for (int k = 1; k <= 3; ++k)
            if (iso_idx[k] >= 0) { csum += xicCorr(ms1st, ms1[iso_idx[0]], ms1[iso_idx[k]], delta_rt); ++cn; }
          const double mean_corr = cn ? std::max(0.0, csum / cn) : 0.0;

          // Composite: shape AND co-elution must BOTH hold, WEIGHTED BY EVIDENCE.
          // The naive product cos*corr + 0.01*n is statistically indefensible: a 2-isotope
          // hypothesis (cos 0.99 x corr 0.95 = 0.9605) BEATS 4 genuine isotopes (0.95 x 0.85 = 0.8475),
          // because the cosine of a 2-vector is nearly always high and the +0.01*n bonus (0.02 between
          // 2 and 4 isotopes) sits far below correlation noise. That biases us toward exactly the
          // sparse, weakly-supported envelopes we are trying to eliminate.
          // Fix: multiply by an evidence weight (n-1)/3 capped at 1 => 4 isotopes 1.00, 3 -> 0.67,
          // 2 -> 0.33. The counterexample now scores 0.808 vs 0.313 - correctly ordered.
          const double evidence = std::min(1.0, (found - 1) / 3.0);
          hyps.push_back({z, mono_mz, cos_sim * mean_corr * evidence, members});
        }
      }

      Precursor_ pc;
      pc.trace_idx = seed;
      pc.rt = s_rt; pc.im = s.im;

      if (hyps.empty())
      {
        pc.mono_mz = s.mz; pc.charge = 0;   // no envelope evidence at all -> unknown charge
      pc.mono_tof = s.tof; pc.mono_b = bOf(ms1st, s);
        R.emit.push_back(pc);
        continue;
      }

      // [baseline-fix] When envelope scoring is OFF we must still DE-ISOTOPE, otherwise every isotope
      // peak seeds its own precursor and the spectrum count explodes (measured: 741k -> 1,209,295
      // spectra, 9,103 -> 7,830 peptides). The off-branch therefore falls back to the ORIGINAL
      // partner-COUNT criterion with the original low-z tie-break, and still marks members used.
      if (!envelope_scoring)
      {
        for (auto& h : hyps) h.score = (double)h.partners.size();  // count, not shape
        sort(hyps.begin(), hyps.end(), [](const Hyp& a, const Hyp& b) {
          if (a.score != b.score) return a.score > b.score;
          if (a.z != b.z) return a.z < b.z;                        // original: ties favour LOW z
          return a.mono < b.mono;
        });
      }
      else
      sort(hyps.begin(), hyps.end(), [](const Hyp& a, const Hyp& b) {
        if (a.score != b.score) return a.score > b.score;
        if (a.z != b.z) return a.z > b.z;   // [route-1] ties now favour HIGHER z (old code favoured low z)
        return a.mono < b.mono;
      });
      const Hyp& best = hyps[0];
      pc.mono_mz = best.mono; pc.charge = best.z;
      pc.mono_tof = s.tof; pc.mono_b = bOf(ms1st, s);
      for (size_t j : best.partners)
        if (ms1[j].mz == best.mono) { pc.mono_tof = ms1[j].tof; pc.mono_b = bOf(ms1st, ms1[j]); break; }
      // partners + the seed = envelope size. `members` excludes the seed, so this is the whole
      // envelope only because the seed is always one of its peaks.
      pc.n_isotopes = 1 + (int)best.partners.size();   // [Q4] envelope confidence for the mono call
      R.emit.push_back(pc);
      for (size_t j : best.partners) R.claims.push_back(j);
      } while (0);
    };

    size_t spec_batch = 8192;
    if (const char* e = std::getenv("SPEXTRACTOR_SPEC_BATCH")) { long v = atol(e); if (v >= 1) spec_batch = (size_t)v; }
    vector<SeedRes> res(spec_batch);
    size_t n_committed = 0, n_conflict = 0, n_skipped = 0;
    for (size_t b0 = 0; b0 < order.size(); b0 += spec_batch)
    {
      const size_t b1 = std::min(b0 + spec_batch, order.size());
      // Phase 1: speculate. Nothing here writes `used`, so the concurrent reads are safe.
      #pragma omp parallel for schedule(dynamic, 16)
      for (long ii = (long)b0; ii < (long)b1; ++ii)
      {
        SeedRes& R = res[(size_t)ii - b0];
        const size_t seed = order[(size_t)ii];
        if (used[seed]) { R.emit.clear(); R.claims.clear(); R.deps.clear(); continue; }
        evalSeed(seed, R);
      }
      // Phase 2: commit in the original seed order.
      for (size_t ii = b0; ii < b1; ++ii)
      {
        const size_t seed = order[ii];
        if (used[seed]) { ++n_skipped; continue; }
        SeedRes& R = res[ii - b0];
        bool stale = false;
        for (size_t d : R.deps) if (used[d]) { stale = true; break; }
        if (stale) { evalSeed(seed, R); ++n_conflict; }
        for (const auto& pc : R.emit) out.push_back(pc);
        used[seed] = true;
        for (size_t j : R.claims) used[j] = true;
        ++n_committed;
      }
    }
    // [z1-diag 2026-09-08] Entrapment FDR stratified by charge put the z=1 stratum at ~2.8% against
    // ~0.4% for z=2 on two TNBC files. The obvious mechanism is charge halving: a 2+ ion whose M+1
    // (+0.5017) was missed but whose M+2 (+1.0034) was found reads as a 1+ envelope. This dumps,
    // for every z=1 call, whether a co-eluting MS1 trace sits at +ISO/2 (a 2+ M+1) or +ISO/3, and
    // whether that trace had already been claimed -- the direct test, on every precursor.
    if (const char* dz = std::getenv("SPEXTRACTOR_Z1_DIAG"))
    {
      size_t n1 = 0, has2 = 0, has3 = 0, has2_free = 0;
      FILE* fo = (*dz && std::strcmp(dz, "1") != 0) ? std::fopen(dz, "w") : nullptr;
      if (fo) std::fprintf(fo, "mono_mz\trt\tim\tn_iso\tp2\tp2_free\tp3\n");
      for (const auto& pc : out)
      {
        if (pc.charge != 1) continue;
        ++n1;
        const Trace& sd = ms1[pc.trace_idx];
        const double sd_rt = rtOf(ms1st, sd);   // [soa-rt]
        const double tol = sd.mz * mass_ppm * 1e-6;
        auto has = [&](double target, bool& free_) -> bool {
          const size_t klo = lbmz(target - tol), khi = ubmz(target + tol);
          for (size_t k = klo; k < khi; ++k)
          {
            if (fabs(sorted_rt[k] - sd_rt) > delta_rt || fabs(sorted_im[k] - sd.im) > iso_im_tol) continue;
            const size_t j = by_mz[k]; if (j == pc.trace_idx) continue;
            free_ = !used[j]; return true;
          }
          return false;
        };
        bool f2 = false, f3 = false;
        const bool p2 = has(pc.mono_mz + ISO / 2.0, f2), p3 = has(pc.mono_mz + ISO / 3.0, f3);
        has2 += p2; has3 += p3; has2_free += (p2 && f2);
        if (fo) std::fprintf(fo, "%.5f\t%.3f\t%.5f\t%d\t%d\t%d\t%d\n", pc.mono_mz, pc.rt, pc.im, pc.n_isotopes, (int)p2, (int)f2, (int)p3);
      }
      if (fo) std::fclose(fo);
      writeLogInfo_("[z1-diag] " + String(n1) + " z=1 precursors: " + String(has2) + " (" + String((int)(1000.0 * has2 / std::max<size_t>(n1, 1)) / 10.0)
                    + "%) have a co-eluting MS1 trace at +ISO/2, i.e. where a 2+ ion's M+1 would be (" + String(has2_free)
                    + " of those unclaimed); " + String(has3) + " at +ISO/3");
    }
    {
      auto _pi_t3 = std::chrono::steady_clock::now();
      auto secs_ = [](auto d) { return std::chrono::duration<double>(d).count(); };
      writeLogInfo_("[infer] " + String(N) + " MS1 traces -> " + String(out.size()) + " precursors: mz-index "
                    + String(secs_(_pi_t1 - _pi_t0)) + " s | intensity-sort " + String(secs_(_pi_t2 - _pi_t1))
                    + " s | greedy walk " + String(secs_(_pi_t3 - _pi_t2)) + " s (speculative, batch "
                    + String(spec_batch) + ": " + String(n_committed) + " committed, " + String(n_conflict)
                    + " re-evaluated (" + String((int)(1000.0 * n_conflict / std::max<size_t>(n_committed, 1)) / 10.0)
                    + "%), " + String(n_skipped) + " already claimed)");
    }
    return out;
  }

  /// The fragment RT gate field. 99.4% of scoring visits die on |rt - pc.rt| > delta_rt, and
  /// reading an 8-byte double to reject each one is the last large bandwidth term in the scorer:
  /// 867e9 visits x 8 B = 6.9 TB per dataset D run, against a measured ~150-226 GB/s. `q` is the same RT
  /// quantised into buckets NEVER NARROWER than delta_rt, so two RTs within delta_rt of each other
  /// can never be more than one bucket apart; the reject then reads 2 bytes instead of 8 and the
  /// exact double test runs only on what survives it. Identical candidates in identical order --
  /// the exact test is the original one, unmoved, and the quantised test only precedes it. [soa2]
  ///
  /// The reject admits +/-2 buckets where +/-1 is provably enough in exact arithmetic. The extra
  /// bucket is insurance against a floor() landing on the far side of a boundary through rounding,
  /// which would silently DROP a candidate; it costs a pass rate of ~0.9% instead of ~0.6%.
  struct FragRt
  {
    vector<double> rt;
    vector<uint16_t> q;
    double rt0 = 0.0, inv = 0.0;
    double operator[](size_t i) const { return rt[i]; }
    /// Signed at the low end and clamped at both: a precursor may sit outside the window's
    /// fragment RT range. The test is written `!(x > 0.0)` rather than `x <= 0.0` so that a NaN
    /// coordinate lands in bucket 0 instead of reaching (int)NaN, which is undefined behaviour.
    int bucketOf(double v) const
    { const double x = (v - rt0) * inv; return !(x > 0.0) ? 0 : (x >= 65535.0 ? 65535 : (int)x); }
    /// inv == 0 is the DISABLED state, not an error: every bucket is then 0, every dq is 0, and
    /// the exact test alone decides. That is the fallback for every degenerate parameter below,
    /// and it costs no branch in the scan.
    void build(const vector<Trace>& fr, const TraceStore& st, double delta_rt)
    {
      const size_t n = fr.size();
      rt.resize(n); q.assign(n, 0);
      rt0 = 0.0; inv = 0.0;
      double lo = 0.0, hi = 0.0;
      for (size_t i = 0; i < n; ++i) { rt[i] = rtOf(st, fr[i]); if (!i || rt[i] < lo) lo = rt[i]; if (!i || rt[i] > hi) hi = rt[i]; }
      // A denormal delta_rt makes 1/delta_rt infinite, and an RT range spanning +/-DBL_MAX makes
      // the span infinite; both then produce inf*0 = NaN inside bucketOf. Neither survives real
      // acquisition, but both are reachable and both were UB, so every one degrades to disabled.
      if (!(delta_rt > 0.0) || !std::isfinite(delta_rt)) return;
      if (!std::isfinite(lo) || !std::isfinite(hi)) return;
      const double span = hi - lo;
      if (!std::isfinite(span)) return;
      double iv = 1.0 / delta_rt;
      // Buckets are delta_rt wide, but widened if the window's RT span would overflow uint16.
      // Wider is always safe: it can only put more fragments in reach of the exact test.
      if (span > 0.0 && span * iv > 65000.0) iv = 65000.0 / span;
      if (!std::isfinite(iv) || !(iv > 0.0)) return;
      rt0 = lo; inv = iv;
      for (size_t i = 0; i < n; ++i) q[i] = (uint16_t)bucketOf(rt[i]);
    }
  };

  /// Resample the precursor XIC onto the window grid (once), then for every IM+RT+overlap-passing
  /// candidate fragment compute the Pearson correlation and, if >= min_corr, call emit(fi, corr).
  /// pdense is caller-owned scratch, so the caller decides the per-thread copy.
  template <class Emit>
  void scoreCandidates_(const Precursor_& pc, const vector<Trace>& frag_traces, const TraceStore& wst,
                        const vector<double>& frag_im, const FragRt& frag_rt,
                        const vector<Trace>& ms1_traces, const TraceStore& ms1st,
                        const FragStats& fg, double delta_im, double delta_rt, double min_corr,
                        int min_corr_pts, vector<float>& pdense, Emit&& emit) const
  {
    const double G = (double)fg.G;
    const Trace& p_tr = ms1_traces[pc.trace_idx];
    vector<int> touched;
    touched.reserve(p_tr.np());
    for (size_t k = 0; k < p_tr.span(); ++k)
    {
      if (!real(ms1st, p_tr, k)) continue;
      const double pval = (double)xv(ms1st, p_tr, k);
      const int gi = fg.nearest_local[p_tr.frame0 + k];   // MS1 frame -> window frame, precomputed
      if (gi >= 0) { if (pdense[gi] == 0.0f) touched.push_back(gi); pdense[gi] += (float)pval; }
    }
    double psum = 0, psumsq = 0, plogsum = 0;
    // plogsum normalises the precursor profile for gate:coelution=logoverlap. Constant across
    // every fragment of this precursor, so hoist it out of the inner loop.
    for (int gi : touched)
    {
      double v = pdense[gi];
      psum += v; psumsq += v * v;
      if (log_overlap_) plogsum += std::log1p(v);
    }
    double pmean = psum / G, pvar = psumsq - G * pmean * pmean;
    double pinv = pvar > 0 ? 1.0 / sqrt(pvar) : 0.0;
    if (pinv > 0.0)
    {
      size_t lo = lower_bound(frag_im.begin(), frag_im.end(), pc.im - delta_im) - frag_im.begin();
      size_t hi = upper_bound(frag_im.begin(), frag_im.end(), pc.im + delta_im) - frag_im.begin();
      long long n_rtpass = 0;
      stat_slice_ += (long long)(hi - lo); ++stat_prec_;
      const int pq = frag_rt.bucketOf(pc.rt);
      for (size_t fi = lo; fi < hi; ++fi)
      {
        const int dq = (int)frag_rt.q[fi] - pq;
        if (dq < -2 || dq > 2) continue;                                // 2 B reject, see FragRt
        // Read the gate field from a parallel array, and do NOT touch the 96-byte trace record
        // until the fragment has passed: 99.4% of visits end here, and at 8 B instead of 96 B the
        // scan moves ~12x fewer bytes. [soa]
        if (fabs(frag_rt[fi] - pc.rt) > delta_rt) continue;            // RT gate
        ++n_rtpass;
        if (fg.invnorm[fi] == 0.0) continue;                           // degenerate fragment
        const Trace& f = frag_traces[fi];
        if (fabs(f.mz - pc.mono_mz) < 0.01) continue;                  // exclude precursor peak [M-7]
        double dot = 0; int overlap = 0;
        // [R2-late, 2026-09-02] overlap <= support, so a fragment with fewer support points than
        // min_corr_pts can never pass the overlap guard below: skip it before the dot product.
        // Output-identical by construction (the guard's continue is the only thing it would reach).
        if (f.np() < (size_t)std::max(min_corr_pts, 0)) continue;
        // two sequential streams: the fragment's span in the arena and pdense over window frames
        for (size_t k = 0; k < f.span(); ++k)
        { const float fv = xv(wst, f, k); if (fv == 0.0f) continue;
          const float pv = pdense[f.frame0 + k]; if (pv != 0.0f) { dot += (double)pv * fv; ++overlap; } }
        if (overlap < min_corr_pts) continue;                          // overlap guard [H-4]
        // [B0] Pearson takes variance over the FULL grid G, so a fragment present in 5 of ~1300
        // grid points has its variance computed against ~1300 implicit zeros -- the zero-padding
        // defect. It rewards sparse fragments that happen to spike where the precursor spikes,
        // and its scale depends on G rather than on the evidence.
        // AlphaDIA instead collapses fragments with sum(log(intensity+1)): a likelihood under
        // independence, where one missing point does not zero the score (unlike a product) and
        // one huge point cannot dominate (unlike a sum). Adapted to a (precursor, fragment) pair:
        // profile overlap in log space, summed ONLY where the precursor has signal, normalised to
        // [0,1]. No zero padding, no dependence on G.
        double c;
        if (var_support_ && !log_overlap_)                             // [Q1] pearson-only, per the flag doc
        {
          // [Q1] Pearson over the UNION SUPPORT (points where precursor OR fragment is non-zero),
          // not the full grid G. Removes the [B0] zero-padding: no ~1300 implicit zeros inflating
          // sparse fragments, no dependence on grid size. n = |touched U f.support|. fsum/fsumsq
          // over f.support are accumulated here (support is tiny, so a second pass is negligible).
          double fsum = 0.0, fsumsq = 0.0;
          for (size_t k = 0; k < f.span(); ++k)
          { const double fv = xv(wst, f, k); if (fv > 0.0) { fsum += fv; fsumsq += fv * fv; } }
          double n = (double)(touched.size() + f.np() - (size_t)overlap);
          double pm = psum / n, fm = fsum / n;
          double pv2 = psumsq - n * pm * pm, fv2 = fsumsq - n * fm * fm;
          if (pv2 <= 0.0 || fv2 <= 0.0) continue;                      // degenerate on union support
          c = (dot - n * pm * fm) / std::sqrt(pv2 * fv2);
        }
        else if (log_overlap_)
        {
          // Normalise BOTH log-profiles to unit sum, then intersect. The first attempt divided
          // the intersection by the precursor's total log-intensity alone, which made the score
          // bounded by the fragment/precursor INTENSITY RATIO: a genuine fragment at 1% of
          // precursor intensity scored ~0.01 however perfectly it co-eluted, and was gated out.
          // Measured -18.9% peptides at gate 0.5 and -9.1% at 0.3 -- a magnitude statistic
          // standing in for a shape statistic. Unit-sum normalisation makes this a distributional
          // intersection: 1 iff the two normalised elution shapes agree, invariant to scale --
          // which is what Pearson gets right and the first version did not.
          double fsum = 0.0;
          for (size_t k = 0; k < f.span(); ++k)
          { const double fv = xv(wst, f, k); if (fv > 0.0) fsum += std::log1p(fv); }
          if (fsum <= 0.0 || plogsum <= 0.0) continue;
          double inter = 0.0;
          for (size_t k = 0; k < f.span(); ++k)
          {
            const double fv = xv(wst, f, k); if (fv <= 0.0) continue;
            inter += std::min(std::log1p(fv) / fsum,
                              std::log1p((double)pdense[f.frame0 + k]) / plogsum);
          }
          c = inter;
        }
        else c = (dot - G * pmean * fg.mean[fi]) * pinv * fg.invnorm[fi]; // Pearson
        if (c < min_corr) continue;                                    // correlation gate
        emit(fi, c);
      }
      stat_rtpass_ += n_rtpass;
    }
    for (int gi : touched) pdense[gi] = 0.0f;                          // reset scratch
  }

  /// [arena] Assertions on the SHIPPED compactUnreferenced(): the compaction must survive traces
  /// whose container order differs from their arena-offset order, which the previous walk did not.
  ExitCodes selftestArena_()
  {
    int fail = 0;
    auto chk = [&](bool ok, const char* what) {
      if (!ok) { writeLogError_(String("FAIL: ") + what); ++fail; }
      else writeLogInfo_(String("  ok  ") + what);
    };
    // four spans A(4) B(3) C(5) D(2) at offsets 0, 4, 7, 12, every value distinct; span k of trace T
    // holds T*100 + k + 1, with a gap (zero) inside D so interior zeros are exercised
    auto build = [](TraceStore& st, vector<Trace>& tr) {
      st = TraceStore(); tr.clear();
      const vector<pair<uint32_t, int>> spec = {{4, 1}, {3, 2}, {5, 3}, {3, 4}};
      for (const auto& [L, tag] : spec)
      {
        vector<pair<uint32_t, float>> pts;
        for (uint32_t k = 0; k < L; ++k) if (!(tag == 4 && k == 1)) pts.emplace_back(k, (float)(tag * 100 + k + 1));
        tr.push_back(makeSpan(pts, st));
      }
    };
    auto bytes = [](const TraceStore& st, const Trace& t) {
      return vector<float>(st.inten.begin() + t.off, st.inten.begin() + t.off + t.len);
    };
    TraceStore st0; vector<Trace> tr0; build(st0, tr0);
    vector<vector<float>> ref; for (const auto& t : tr0) ref.push_back(bytes(st0, t));
    chk(st0.inten.size() == 15 && tr0[3].len == 3 && tr0[3].npts == 2, "fixture: 15 floats, D spans 3 frames with a gap");

    // 1. container order D,B,A,C (offsets 12,4,0,7), keep D,B,A, drop C. The old container-order walk
    //    moved D to 0 and B to 2 before reading A from [0,4): A came back as D's and B's bytes.
    { vector<Trace> v = {tr0[3], tr0[1], tr0[0], tr0[2]}; TraceStore s = st0;
      const Size freed = compactUnreferenced(v, s, vector<bool>{true, true, true, false});
      chk(freed == 1, "1: one profile released");
      chk(s.inten.size() == 10, "1: arena holds exactly the kept spans (4+3+3)");
      chk(bytes(s, v[0]) == ref[3], "1: D survives (interior zero kept)");
      chk(bytes(s, v[1]) == ref[1], "1: B survives");
      chk(bytes(s, v[2]) == ref[0], "1: A survives -- the old walk overwrote it");
      chk(v[3].len == 0 && v[3].npts == 0, "1: C freed (span cleared)"); }
    // 2. offset order, everything needed: unchanged bytes, no move
    { vector<Trace> v = tr0; TraceStore s = st0;
      chk(compactUnreferenced(v, s, vector<bool>(4, true)) == 0, "2: nothing released");
      bool ok = s.inten.size() == 15; for (size_t i = 0; i < 4; ++i) ok = ok && bytes(s, v[i]) == ref[i];
      chk(ok, "2: offset-order input is a no-op"); }
    // 3. the freed trace first, then a trimmed span: the trim moved off/len/apex (as trimToSpan does)
    { vector<Trace> v = {tr0[2], tr0[0], tr0[1], tr0[3]}; TraceStore s = st0;
      v[1].off += 1; v[1].len -= 2; v[1].frame0 += 1; v[1].npts = 2;          // A trimmed to [1,3)
      const vector<float> a_trim(ref[0].begin() + 1, ref[0].begin() + 3);
      chk(compactUnreferenced(v, s, vector<bool>{false, true, true, true}) == 1, "3: C released first");
      chk(bytes(s, v[1]) == a_trim && bytes(s, v[2]) == ref[1] && bytes(s, v[3]) == ref[3], "3: trimmed A, B, D survive");
      chk(s.inten.size() == 2 + 3 + 3, "3: arena sized to the trimmed spans"); }
    // 4. nobody needed / a needed trace whose span was already released (len == 0) / duplicate references
    { vector<Trace> v = tr0; TraceStore s = st0;
      chk(compactUnreferenced(v, s, vector<bool>(4, false)) == 4 && s.inten.empty(), "4a: none needed -> empty arena");
      vector<Trace> w = tr0; TraceStore s2 = st0; w[0].freeProfile();
      chk(compactUnreferenced(w, s2, vector<bool>(4, true)) == 0 && s2.inten.size() == 11 && bytes(s2, w[1]) == ref[1], "4b: a needed len==0 trace owns no bytes"); }
    // 5. compaction is idempotent
    { vector<Trace> v = {tr0[3], tr0[1], tr0[0], tr0[2]}; TraceStore s = st0;
      compactUnreferenced(v, s, vector<bool>{true, true, true, false});
      const vector<float> once = s.inten;
      compactUnreferenced(v, s, vector<bool>{true, true, true, false});
      chk(s.inten == once && bytes(s, v[2]) == ref[0], "5: second compaction is a no-op"); }
    // 6. overlapping spans are refused before any byte moves
    { vector<Trace> v = tr0; TraceStore s = st0; v[1].off = 2;                    // B now overlaps A
      bool threw = false; try { compactUnreferenced(v, s, vector<bool>(4, true)); } catch (const OpenMS::Exception::Precondition&) { threw = true; }
      chk(threw, "6: overlapping spans throw Precondition"); }

    writeLogInfo_(fail ? "[arena] SELFTEST FAILED" : "[arena] selftest passed");
    return fail ? UNEXPECTED_RESULT : EXECUTION_OK;
  }

  /// Build a pseudo-MS2 from a fragment list (m/z,intensity) + ranking scores: keeps top
  /// max_frags by score, drops if < min_frags, annotates the synthetic precursor. Deterministic.
  /// EXPORT-TIME CALIBRATION. On a flight-time axis the measured quantity is a bin; m/z is a
  /// calibrated function of it and of the frame's digitizer temperature. Applying that function
  /// ONCE, here, when the value is written, is what keeps the reported mass free of anything the
  /// intermediate gates did in cached m/z space -- and the apex frame's own factor is the most
  /// accurate one to use. A zero bin means the trace came from the OpenMS detector, which has no
  /// bin, and the value it computed stands.
  static double exportMz_(uint32_t tof, double b, double cached)
  {
    if (tof == 0 || !(b > 0.0) || !tofAxis().ok) return cached;
    const double v = tofAxis().mzOf(tof, b);
    return std::isfinite(v) && v > 0.0 ? v : cached;
  }

  void assembleFromList_(const Precursor_& pc, double win_lo, double win_hi,
                         vector<pair<double, double>>& frags, vector<double>& frag_scores,
                         Size min_frags, Size max_frags, MSSpectrum& out) const
  {
    if (frags.size() < min_frags) return;
    if (frags.size() > max_frags)
    {
      vector<size_t> idx(frags.size());
      for (size_t i = 0; i < idx.size(); ++i) idx[i] = i;
      // Rank by correlation. Ties break on m/z, then index, so the output is deterministic.
      partial_sort(idx.begin(), idx.begin() + max_frags, idx.end(), [&](size_t a, size_t b) {
        const double ka = frag_scores[a];
        const double kb = frag_scores[b];
        if (ka != kb) return ka > kb;
        if (frags[a].first != frags[b].first) return frags[a].first < frags[b].first;
        return a < b;
      });
      vector<pair<double, double>> keep; keep.reserve(max_frags);
      for (size_t i = 0; i < max_frags; ++i) keep.push_back(frags[idx[i]]);
      frags.swap(keep);
    }
    out.setMSLevel(2);
    out.setType(SpectrumSettings::SpectrumType::CENTROID);
    out.setRT(pc.rt);
    // [mem] emplace_back with no reserve grows by doubling, so a spectrum at the 500-fragment cap
    // ends up with capacity 512 and every spectrum between 129 and 256 fragments carries a 256-slot
    // array. 3.9e6 spectra x 16 B/Peak1D of slack is real memory held from emit until the write.
    // Reserving the exact count cannot change the peaks or their order.
    out.reserve(frags.size());
    for (const auto& fr : frags) out.emplace_back(fr.first, fr.second);
    out.sortByPosition();
    OpenMS::Precursor prec;
    prec.setMZ(exportMz_(pc.mono_tof, pc.mono_b, pc.mono_mz));   // calibrate on write
    if (pc.charge > 0) prec.setCharge(pc.charge);
    prec.setIsolationWindowLowerOffset(max(0.0, pc.mono_mz - win_lo));   // [C-5]
    prec.setIsolationWindowUpperOffset(max(0.0, win_hi - pc.mono_mz));
    prec.setDriftTime(pc.im);
    prec.setDriftTimeUnit(DriftTimeUnit::VSSC);
    out.setPrecursors({prec});
    // [provenance] Stamp the inference class onto the emitted spectrum so identified peptides can be
    // joined back to guessed (no isotope support) vs isotope-supported precursors -- the number that
    // sets the peptide cost of an isotope-support gate. Written as a <userParam> in the mzML.
    out.setMetaValue("spx_guessed", (int)(pc.guessed ? 1 : 0));
    // [Q4] Isotope-offset hypothesis for open/blind search: the number of isotope peaks behind the
    // mono call. 0/1 => the mono is weakly determined and could be off by +-k*1.00335 Da, so a
    // downstream delta-mass corrector should treat a near-integer-Da delta as an isotope miscall to
    // reassign rather than a real modification. Harmless in closed search (ignored).
    out.setMetaValue("spx_n_isotopes", pc.n_isotopes);
  }

  /// [E5, 2026-09-02] The ONE place the emitted-intensity weights live. Returns {cap-key intensity,
  /// emitted intensity}: the IM-proximity weight feeds both (IM-on-c, orthogonal to correlation); the
  /// [Q2] correlation-power weight feeds ONLY the emitted (engine-visible) intensity -- putting it in the
  /// cap key made frag_scores = base*c^(k+1) and double-hit borderline-c faint fragments at the 500-cap.
  pair<double, double> weighted_(double base, double c, double dim) const
  {
    double inten = base;
    if (im_weight_sigma_ > 0.0) inten *= std::exp(-(dim * dim) / (2.0 * im_weight_sigma_ * im_weight_sigma_));
    double emit_inten = inten;
    if (corr_power_ > 0.0 && c > 0.0) emit_inten *= std::pow(c, corr_power_);
    return {inten, emit_inten};
  }

  /// Per-precursor assembly: this precursor claims every fragment passing its gate (a fragment may
  /// be shared across precursors -> chimeric). Leaves @p out empty on failure.
  void assembleOne_(const Precursor_& pc, double win_lo, double win_hi,
                    const vector<Trace>& frag_traces, const TraceStore& wst, const vector<double>& frag_im,
                    const FragRt& frag_rt,
                    const vector<Trace>& ms1_traces, const TraceStore& ms1st, const FragStats& fg,
                    double delta_im, double delta_rt, double min_corr, int min_corr_pts,
                    Size min_frags, Size max_frags, vector<float>& pdense, MSSpectrum& out) const
  {
    vector<pair<double, double>> frags;
    vector<double> frag_scores;
    scoreCandidates_(pc, frag_traces, wst, frag_im, frag_rt, ms1_traces, ms1st, fg, delta_im, delta_rt, min_corr,
                     min_corr_pts, pdense, [&](size_t fi, double c) {
      const auto [inten, emit_inten] = weighted_(intensityOf(wst, frag_traces[fi]), c, frag_im[fi] - pc.im);
      frags.emplace_back(exportMz_(frag_traces[fi].tof, bOf(wst, frag_traces[fi]), frag_traces[fi].mz), emit_inten);
      frag_scores.push_back(c * inten);
    });
    assembleFromList_(pc, win_lo, win_hi, frags, frag_scores, min_frags, max_frags, out);
  }

  ExitCodes main_(int argc, const char** argv) override
  {
    phase_clock_();   // [perf-instr] fix the epoch HERE: it is a first-call static, and the
                      // streaming path first touched it only AFTER loading, so load time was
                      // invisible and every [t=..] was relative to post-load.

    // -threads defaults to 1 in TOPPBase, a poor default for a tool whose window loop IS the
    // runtime. Default to every core. The command line is scanned rather than the value tested,
    // so that an EXPLICIT `-threads 1` still means one thread: testing `value == 1` alone would
    // silently override the one user who actually wants it serial.
    int n_threads_req = getIntOption_("threads");
    {
      bool given = false;
      for (int i = 1; i < argc && !given; ++i) given = (String(argv[i]) == "-threads");
      if (!given && n_threads_req == 1)
      {
        n_threads_req = std::max(1, (int)std::thread::hardware_concurrency());
        omp_set_num_threads(n_threads_req);
        writeLogInfo_("-threads not given: using all " + String(n_threads_req) + " cores. Pass "
                      "-threads <n> to limit it, which is what you want on a shared machine.");
      }
    }
    const String in = getStringOption_("in");
    const String out = getStringOption_("out");
    const double delta_im = getDoubleOption_("gate:delta_im");
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
    map<WinKey, vector<CompactFrame>> ms2_by_window;
    CompactStats cstat;
    auto winKey = [](double lo, double hi, uint32_t window_group) -> WinKey {
      return {(int)llround(lo * 100.0), (int)llround(hi * 100.0), (int)window_group};
    };
    const bool stream_load = (getStringOption_("perf:stream_load") == "true");
    const bool trim_on = (getStringOption_("perf:malloc_trim") == "true");
    bool streamed = false;

    if (stream_load)
    {
      // [stream] frame-by-frame: pick + compact on arrival, never hold the whole run.
      // Also the ONLY place the reader's NATIVE pre-centroid frame aggregation is reachable.
      BrukerTimsFile::Config cfg;
      cfg.dia_ms2_n_neighbors = getIntOption_("trace:native_ms2_neighbors");
      cfg.ms1_n_neighbors     = getIntOption_("trace:native_ms1_neighbors");
      PeakPickerIM spicker;
      Param sp = spicker.getParameters();
      sp.setValue("pickIMCluster:im_tolerance_cluster", getDoubleOption_("gate:delta_im"));
      sp.setValue("pickIMCluster:ppm_tolerance_cluster", getDoubleOption_("trace:mass_error_ppm"));
      if (const char* m = std::getenv("SPEXTRACTOR_PICK_MZ_MODE")) sp.setValue("pickIMCluster:mz_mode", std::string(m));   // [C2 pick-level A/B] weighted|seed|top3
      spicker.setParameters(sp);
      PickCompactConsumer consumer(spicker, ms2_by_window, ms1_map, cstat, winKey);
      try
      {
#ifdef SPEXTRACTOR_WITH_MZPEAK
        if (FileHandler::getTypeByFileName(in) == FileTypes::MZPEAK)
#else
        if (false)
#endif
        {
#ifdef SPEXTRACTOR_WITH_MZPEAK
          spx::loadMzPeakStreaming(in, consumer, n_threads_req);   // consumer counts frames itself
#else
          throw Exception::NotImplemented(__FILE__, __LINE__, "streaming .mzpeak input needs a build with -DMZPEAK_ROOT");
#endif
        }
        else BrukerTimsFile().loadDIAStreaming(in, consumer, cfg);
        consumer.finish();                                          // the last partial batch
        streamed = true;
        phase_stats_()["LOAD(stream)"].wall = phase_clock_();      // [perf-instr] start-to-here
        phase_stats_()["LOAD(stream)"].cpu  = cpu_seconds_();
        phase_stats_()["LOAD(stream)"].rss_end_mb = rss_mb_();
        if (phase_stats_()["LOAD(stream)"].n++ == 0) phase_order_().push_back("LOAD(stream)");
        writeLogInfo_("[perf-load] pick(flush) wall=" + String(flush_wall_(), 1) + " s inside LOAD(stream)");
        if (std::getenv("SPEXTRACTOR_LOAD_ONLY")) { report_phases_(phase_clock_()); return EXECUTION_OK; }   // [perf-load] decode/hand-off/pick split only
        writeLogInfo_("[stream] frame-by-frame load done: " + String(consumer.frames_seen)
                      + " frames, MS1 " + String(ms1_map.size()) + ", windows "
                      + String(ms2_by_window.size()) + " (native ms2_neighbors="
                      + String(cfg.dia_ms2_n_neighbors) + ")" + clk_() + rss_() + mem_());
      }
      catch (const Exception::BaseException& e)
      {
        writeLogWarn_(String("[stream] streaming load failed (") + e.getName()
                      + "); falling back to loadExperiment. " + e.getMessage());
      }
    }

    if (!streamed)
    {
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
      IMFormat imf = IMTypes::determineIMFormat(exp, 1);
      if (imf == IMFormat::NONE)
      {
        writeLogError_("Error: input has no ion-mobility data at MS1. SpeXtractor requires diaPASEF (IM DIA) input.");
        return ILLEGAL_PARAMETERS;
      }
    }
    // deliberate: assumes 1/K0 (VSSC). ms/CCS conversion and FAIMS rejection are Phase 2 [M-2].

    // Centroid IM frames that are still profile, keeping per-peak IM at a tolerance no coarser
    // than the trace IM tolerance [C-2]. Split MS1 vs MS2 into separate working maps.
    if (!streamed)
    {
    PeakPickerIM picker;
    Param pp = picker.getParameters();
    pp.setValue("pickIMCluster:im_tolerance_cluster", delta_im);
    pp.setValue("pickIMCluster:ppm_tolerance_cluster", mass_ppm);
    picker.setParameters(pp);

    // Peak-pick (centroid) all IM frames in PARALLEL. PeakPickerIM is firstprivate so each thread
    // has its own copy -> the mutable ccs_warning_shown_ flag is not shared (a shared const picker
    // would be a real data race). pickIMCluster mutates only its own spectrum; distinct indices are
    // independent. [par-Crit-1]
    writeLogInfo_("Loaded " + String(exp.size()) + " frames." + clk_() + rss_()); // raw residency peak? [mem]
    writeLogInfo_("Peak-picking " + String(exp.size()) + " frames (OpenMP)...");
    // Param is a deep-copy value type (mutable ParamNode root_, defaulted copy) so firstprivate
    // gives each thread a fully independent picker -> no refcount/COW race. pickIMCluster can throw
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
        ms2_by_window[winKey(lo, hi, windowGroupOf(s.getNativeID()))].push_back(compactify(s, cstat));
        s.clear(true);   // [mem] the picked frame is dead once compacted; waiting for exp.clear()
      }                  // below held the whole picked run (20 B/peak) beside the compact store
    }
    }
    exp.clear(true); // frames moved out; release the container
    {
      size_t cb = 0, cp = 0;
      for (const auto& kv : ms2_by_window) for (const auto& f : kv.second) { cb += f.bytes(); cp += f.mzq.size(); }
      const size_t lost = cstat.no_im_array + cstat.size_mismatch + cstat.bad_mz + cstat.bad_im;
      if (lost)
      {
        writeLogWarn_("[compact] DROPPED " + String(lost) + " peaks: no_im_array=" + String(cstat.no_im_array)
                      + " size_mismatch=" + String(cstat.size_mismatch) + " bad_mz=" + String(cstat.bad_mz)
                      + " bad_im=" + String(cstat.bad_im) + " (kept " + String(cstat.kept) + ") -- if this is"
                      + " nonzero the compact store is NOT lossless and results differ from the old path.");
      }
      size_t ms1_pk = 0; for (const auto& sp : ms1_map) ms1_pk += sp.size();
      writeLogInfo_("Split into MS1 + " + String(ms2_by_window.size()) + " windows (picked); compact store "
                    + String(cb / (1024ULL * 1024ULL)) + " MB for " + String(cp) + " peaks (~"
                    + String(cp ? (double)cb / cp : 0.0) + " B/peak); MS1 " + String(ms1_map.size()) + " frames / "
                    + String(ms1_pk) + " peaks (" + String(ms1_pk * 20 / (1024ULL * 1024ULL)) + " MB as PeakMap)." + clk_() + rss_() + mem_()); // [mem]
    }

    if (ms1_map.empty())
    {
      writeLogError_("Error: no MS1 ion-mobility frames found; cannot seed precursors.");
      return INCOMPATIBLE_INPUT_DATA;
    }

    // THE GLOBAL RT AXIS. Every frame contributes one retention time; every trace point sits on a
    // frame. Building it here, once, is what lets a trace point be 8 bytes (frame index +
    // intensity) instead of 16 (RT + intensity), and lets two profiles be aligned by integer
    // equality instead of a binary search per point. Frames are counted once even when an MS1 and
    // an MS2 frame share an RT, which is what makes the index a valid shared key.
    {
      vector<double>& ax = rtAxis();
      ax.clear();
      { size_t nf = ms1_map.size(); for (const auto& kv : ms2_by_window) nf += kv.second.size();
        ax.reserve(nf + 1024); }   // MS1 *and* every window's MS2 frames land here [mem]
      for (const auto& sp : ms1_map) ax.push_back(sp.getRT());
      for (const auto& kv : ms2_by_window) for (const auto& f : kv.second) ax.push_back(f.rt);
      sort(ax.begin(), ax.end());
      ax.erase(unique(ax.begin(), ax.end()), ax.end());
      writeLogInfo_("RT axis: " + String(ax.size()) + " distinct frame retention times"
                    + (ax.empty() ? "" : " spanning " + String(ax.front()) + "-" + String(ax.back()) + " s"));
      if (ax.empty())
      {
        writeLogError_("Error: no frame retention times; cannot build the RT axis.");
        return INCOMPATIBLE_INPUT_DATA;
      }
    }

    //-------------------------------------------------------------
    // MS1 traces + precursor/charge inference (shared, once) [H-8,H-10]
    //-------------------------------------------------------------
    ms1_map.sortSpectra();
    const double ms1_snr = getDoubleOption_("trace:ms1_chrom_peak_snr");
    const double ms2_snr = getDoubleOption_("trace:ms2_chrom_peak_snr");
    const double ms2_minlen = getDoubleOption_("trace:ms2_min_length_sec");
    const double ms2_msr = getDoubleOption_("trace:ms2_min_sample_rate");
    double ms2_split = getDoubleOption_("trace:ms2_split_valleys");
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
    #pragma omp parallel
    #pragma omp single
    ms1_traces = detectTraces_(ms1_map, ms1_store, delta_im, getDoubleOption_("trace:noise_threshold_int"),
                                             ms1_snr, getDoubleOption_("trace:min_length_sec"), getDoubleOption_("trace:ms1_min_sample_rate"), getDoubleOption_("trace:ms1_split_valleys"), &ms1_span, ms1_bands);
    { const double cap = max_span;
      if (cap > 0.0) for (auto& t : ms1_traces) trimToSpan(ms1_store, t, cap); }
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
      fw.reserve(ms1_traces.size() / 4 + 1);
      vector<double> prt, pv;
      for (const auto& t : ms1_traces)
      {
        if (t.np() < 5) continue;
        packReal(ms1_store, t, prt, pv);              // walk REAL points: a gap is not a zero crossing
        size_t ap = 0;
        for (size_t i = 1; i < pv.size(); ++i) if (pv[i] > pv[ap]) ap = i;
        const double half = pv[ap] * 0.5;
        if (half <= 0.0) continue;
        double lo = -1.0, hi = -1.0;
        for (size_t i = ap; i > 0; --i)
          if (pv[i - 1] <= half)
          { const double d = pv[i] - pv[i - 1];
            const double f = d > 0 ? (pv[i] - half) / d : 0.0;
            lo = prt[i] - f * (prt[i] - prt[i - 1]); break; }
        for (size_t i = ap; i + 1 < pv.size(); ++i)
          if (pv[i + 1] <= half)
          { const double d = pv[i] - pv[i + 1];
            const double f = d > 0 ? (pv[i] - half) / d : 0.0;
            hi = prt[i] + f * (prt[i + 1] - prt[i]); break; }
        if (lo >= 0.0 && hi > lo) fw.push_back(hi - lo);
      }
      if (!fw.empty())
      {
        std::nth_element(fw.begin(), fw.begin() + fw.size() / 2, fw.end());
        ms1_fwhm_med = fw[fw.size() / 2];
        writeLogInfo_("Measured MS1 FWHM: median " + String(ms1_fwhm_med) + " s over "
                      + String(fw.size()) + " traces (of " + String(ms1_traces.size())
                      + "; truncated peaks excluded)");
      }
      else writeLogInfo_("Measured MS1 FWHM: NO usable traces -- falling back to absolute seconds");
    }
    // ms2_split is declared at :1324 but the FWHM is only known HERE, after MS1 tracing --
    // that ordering is why only the MS2 side can use the measured width for free. Doing the
    // same for MS1 needs a two-pass trace (measure with splitting off, then re-trace), which is
    // a real cost and is deliberately not done blind.
    const double iso_im_tol = getDoubleOption_("charge:iso_im_tolerance");
    const double ms2_noise = getDoubleOption_("trace:ms2_noise_threshold_int");
    writeLogInfo_("MS2 trace gate: apex > " + String(ms2_snr * ms2_noise) + " (snr " + String(ms2_snr)
                  + " x noise " + String(ms2_noise) + "), membership > " + String(ms2_noise)
                  + ", min_length " + String(ms2_minlen) + " s");
    const bool env_scoring = (getStringOption_("charge:scoring") == "envelope");
    // [determinism] Canonically order the MS1 traces before precursor inference. inferPrecursors_
    // is a GREEDY seed-and-mark-used loop; its output depends on ms1_traces' CONTAINER ORDER, and
    // that order is non-deterministic -- MS1 detectTraces_ runs at top level so EPD's internal
    // parallel-for is active and appends split traces in thread-completion order. The greedy
    // seed sort already tie-breaks on index (a<b), but the index maps to a different physical
    // trace each run. Result: ~0.7% run-to-run peptide wobble, and the deterministic -0.8% when a
    // parallel change reshuffled the order. A total physical sort here mirrors the MS2-side sort
    // that already exists (fragment traces are canonicalised right after detectTraces_) and makes
    // the whole tool reproducible -- which also makes the emitted-count/peptide correctness gate
    // MEASURABLE.
    // A non-finite coordinate makes the comparator below non-transitive, which is UB in sort()
    // and silently corrupts every lower_bound on the result. The fragment path already filtered;
    // this one did not.
    {
      const size_t before = ms1_traces.size();
      ms1_traces.erase(remove_if(ms1_traces.begin(), ms1_traces.end(), [&ms1_store](const Trace& t) {
        return !std::isfinite(t.mz) || !std::isfinite(rtOf(ms1_store, t)) || !std::isfinite(t.im)
               || !std::isfinite(intensityOf(ms1_store, t));
      }), ms1_traces.end());
      if (before != ms1_traces.size())
        writeLogInfo_("dropped " + String(before - ms1_traces.size()) + " MS1 traces with non-finite coordinates");
    }
    sort(ms1_traces.begin(), ms1_traces.end(), [&ms1_store](const Trace& a, const Trace& b) {
      if (a.mz != b.mz) return a.mz < b.mz;
      { const double ra = rtOf(ms1_store, a), rb = rtOf(ms1_store, b); if (ra != rb) return ra < rb; }
      if (a.im != b.im) return a.im < b.im;
      return intensityOf(ms1_store, a) < intensityOf(ms1_store, b);
    });
    double _t_win = 0, _c_win = 0;                             // [perf-instr] window loop (function scope)
    double _t_inf = phase_clock_(), _c_inf = cpu_seconds_();   // [perf-instr]
    vector<Precursor_> precursors = inferPrecursors_(ms1_traces, ms1_store, max_charge, delta_rt, iso_im_tol,
                                                     mass_ppm, env_scoring);
    if (detOn_())
    {
      vector<uint64_t> b;
      for (const auto& pc : precursors) { uint64_t u; double v; v = pc.rt; std::memcpy(&u, &v, 8); b.push_back(u); v = pc.im; std::memcpy(&u, &v, 8); b.push_back(u); }
      writeLogInfo_("[det] precursors n=" + String(precursors.size()) + " digest=" + String(detDigest_(std::move(b))));
    }
    // Emulate the reference implementation, which assigns a charge to every precursor: give isotope-unsupported
    // precursors the default charge (0 = keep the strict isotope-only behavior and drop them).
    // [im-veto 2026-09-08] Charge halving, corrected by ion mobility. See charge:im_charge_veto.
    if (getStringOption_("charge:im_charge_veto") == "true")
    {
      auto fitLine = [&](int z, double& a, double& b, double& sig, size_t& n) -> bool {
        std::map<int, vector<double>> bins;                           // 25-Th bins of 1/K0, confident calls only
        for (const auto& pc : precursors)
          if (pc.charge == z && pc.n_isotopes >= 3 && std::isfinite(pc.im) && pc.mono_mz > 0.0)
            bins[(int)(pc.mono_mz / 25.0)].push_back(pc.im);
        vector<double> xs, ys; n = 0;
        for (auto& kv : bins)
        {
          auto& v = kv.second; if (v.size() < 30) continue;
          std::nth_element(v.begin(), v.begin() + v.size() / 2, v.end());
          xs.push_back((kv.first + 0.5) * 25.0); ys.push_back(v[v.size() / 2]); n += v.size();
        }
        if (xs.size() < 4) return false;
        double sx = 0, sy = 0, sxx = 0, sxy = 0; const double m = (double)xs.size();
        for (size_t i = 0; i < xs.size(); ++i) { sx += xs[i]; sy += ys[i]; sxx += xs[i] * xs[i]; sxy += xs[i] * ys[i]; }
        const double den = m * sxx - sx * sx; if (den <= 0.0) return false;
        b = (m * sxy - sx * sy) / den; a = (sy - b * sx) / m;
        vector<double> res;
        for (const auto& pc : precursors)
          if (pc.charge == z && pc.n_isotopes >= 3 && std::isfinite(pc.im) && pc.mono_mz > 0.0)
            res.push_back(fabs(pc.im - (a + b * pc.mono_mz)));
        if (res.empty()) return false;
        std::nth_element(res.begin(), res.begin() + res.size() / 2, res.end());
        sig = 1.4826 * res[res.size() / 2];
        return sig > 0.0;
      };
      double a2 = 0, b2 = 0, s2 = 0, a3 = 0, b3 = 0, s3 = 0; size_t n2 = 0, n3 = 0;
      const bool ok2 = fitLine(2, a2, b2, s2, n2), ok3 = fitLine(3, a3, b3, s3, n3);
      const double kband = getDoubleOption_("charge:im_veto_band");
      size_t n1 = 0, to2 = 0, to3 = 0;
      if (ok2)
      {
        for (auto& pc : precursors)
        {
          if (pc.charge != 1 || !std::isfinite(pc.im)) continue;
          ++n1;
          const double r2 = fabs(pc.im - (a2 + b2 * pc.mono_mz)) / s2;
          const double r3 = ok3 ? fabs(pc.im - (a3 + b3 * pc.mono_mz)) / s3 : 1e9;
          if (r2 <= kband && r2 <= r3) { pc.charge = 2; ++to2; }
          // [2026-09-08] A z=1 call on the 3+ band is not a 1+ ion, but re-calling it 3+ produced
          // NOTHING on either benchmark file (z=3 peptides 5,313 -> 5,322 on TNBC 009, 3,888 ->
          // 3,935 on dataset D) while adding 178k / 93k spectra -- and the emitted-population split
          // puts only ~1.8% of z=1 calls genuinely on the 3+ band against the 7% this branch was
          // catching, because the 2+ and 3+ lines are ~1 sigma apart at low m/z. Unset the charge
          // instead: the call becomes a guessed precursor and require_isotope_support removes it.
          else if (ok3 && r3 <= kband) { pc.charge = 0; ++to3; }
        }
        writeLogInfo_("[im-veto] 2+ line 1/K0 = " + String(a2) + " + " + String(b2) + " * m/z (n=" + String(n2) + ", sigma "
                      + String(s2) + ")" + (ok3 ? "; 3+ line " + String(a3) + " + " + String(b3) + " * m/z (n=" + String(n3) + ", sigma " + String(s3) + ")" : String("; no 3+ line"))
                      + ". Of " + String(n1) + " z=1 calls, " + String(to2) + " (" + String((int)(1000.0 * to2 / std::max<size_t>(n1, 1)) / 10.0)
                      + "%) sit on the 2+ band and are re-called 2+, " + String(to3) + " on the 3+ band are dropped, " + String(n1 - to2 - to3) + " kept as 1+");
      }
      else writeLogInfo_("[im-veto] too few confident 2+ calls to fit a mobility line; no z=1 re-calls");
    }
    const int default_charge = getIntOption_("assembly:default_charge");
    Size n_default = 0;
    // [way-4] A GUESSED charge and an isotope-SUPPORTED charge must not be emitted identically.
    // Closed search hides the difference (engine enumerates); open search does not.
    for (auto& pc : precursors)
      if (pc.charge == 0) { pc.guessed = true; pc.charge = default_charge; ++n_default; }
    // [emission] Isotope-support gate: drop the guessed singletons rather than emit them. They are
    // coordinate-distinct (merge/dedup cannot cut them) and identify 8.8x less often; dropping all
    // guessed cost 0.78% peptides for -39.5% emission on dataset D. OFF by default (open-search caveat).
    if (getStringOption_("assembly:require_isotope_support") == "true")
    {
      const size_t before = precursors.size();
      precursors.erase(std::remove_if(precursors.begin(), precursors.end(),
                       [](const Precursor_& pc){ return pc.guessed; }), precursors.end());
      writeLogInfo_("require_isotope_support: dropped " + String(before - precursors.size())
                    + " guessed precursors, " + String(precursors.size()) + " isotope-supported remain");
    }
    // [min-charge, 2026-09-03] 29.3% of dataset D emission is SINGLY-charged precursor hypotheses (271,559
    // spectra) and they carry 259 unique peptides, 1.73%. They are identified on 0.42% of their own
    // spectra against 15.3% for z=2 -- 36x less often. Tryptic peptides are essentially never 1+ in
    // ESI, and charge inference breaks ties toward the LOW charge, so this is where the mis-assignments
    // land. Dropping them is a far better emission lever than any isotope collapse tested: -29.3%
    // emission for -1.73% peptides, against -15.3% for -4.6% at the best collapse setting.
    {
      const int zmin = getIntOption_("charge:min_charge"); const size_t before = precursors.size();
      precursors.erase(std::remove_if(precursors.begin(), precursors.end(),
                       [zmin](const Precursor_& pc){ return pc.charge > 0 && pc.charge < zmin; }), precursors.end());
      if (before != precursors.size())
        writeLogInfo_("charge:min_charge=" + String(zmin) + ": dropped " + String(before - precursors.size())
                      + " precursors below that charge, " + String(precursors.size()) + " remain");
    }
    // [z1-unset 2026-09-08] Emit z=1 calls with the charge UNSET, so the engines search their
    // configured 2-4 range instead of honouring a 1+ that may be a halved 2+. Discriminates the
    // two hypotheses directly: a real 1+ peptide is lost, a mis-called 2+ comes back at 2+.
    if (std::getenv("SPEXTRACTOR_Z1_CHARGE_UNSET"))
    {
      size_t n = 0;
      for (auto& pc : precursors) if (pc.charge == 1) { pc.charge = 0; ++n; }
      writeLogInfo_("SPEXTRACTOR_Z1_CHARGE_UNSET: " + String(n) + " z=1 precursors emitted with the charge unset");
    }
    // [step-02 emission-controlled arm, 2026-09-02] SPEXTRACTOR_MIN_ISOTOPES=k keeps only precursors whose
    // envelope has >= k isotope peaks (n_isotopes counts the mono): a precursor QUALITY gate that cuts
    // emission without touching fragment sharing. Pre-registered falsifier in BASELINE.md.
    if (const char* mi = std::getenv("SPEXTRACTOR_MIN_ISOTOPES"))
    {
      const int k = std::atoi(mi); const size_t before = precursors.size();
      precursors.erase(std::remove_if(precursors.begin(), precursors.end(),
                       [k](const Precursor_& pc){ return pc.n_isotopes < k; }), precursors.end());
      writeLogInfo_("SPEXTRACTOR_MIN_ISOTOPES=" + String(k) + ": dropped " + String(before - precursors.size())
                    + " precursors with fewer isotope peaks, " + String(precursors.size()) + " remain");
    }
    // SPEXTRACTOR_PRECURSOR_LIST=<tsv: rt_sec mz z, header line> keeps only precursors that
    // MATCH a listed one (|dRT| <= 10 s, |dm/z| <= 10 ppm, same z or listed z == 0). Given a reference
    // tool's own precursor list, this holds the precursor population fixed while varying the spectra.
    if (const char* pl = std::getenv("SPEXTRACTOR_PRECURSOR_LIST"))
    {
      struct Ref { double mz, rt; int z; };
      std::vector<Ref> refs; std::ifstream f(pl); std::string line; std::getline(f, line);   // header
      while (std::getline(f, line)) { std::istringstream ls(line); Ref r{}; if (ls >> r.rt >> r.mz >> r.z) refs.push_back(r); }
      std::sort(refs.begin(), refs.end(), [](const Ref& a, const Ref& b){ return a.mz < b.mz; });
      const size_t before = precursors.size();
      precursors.erase(std::remove_if(precursors.begin(), precursors.end(), [&](const Precursor_& pc) {
        const double tol = pc.mono_mz * 10e-6;
        auto lo = std::lower_bound(refs.begin(), refs.end(), pc.mono_mz - tol, [](const Ref& r, double v){ return r.mz < v; });
        for (auto it = lo; it != refs.end() && it->mz <= pc.mono_mz + tol; ++it)
          if (std::fabs(it->rt - pc.rt) <= 10.0 && (it->z == 0 || pc.charge == 0 || it->z == pc.charge)) return false;
        return true; }), precursors.end());
      writeLogInfo_("SPEXTRACTOR_PRECURSOR_LIST: " + String(refs.size()) + " reference precursors; kept "
                    + String(precursors.size()) + " of " + String(before) + " (matched within 10 s / 10 ppm / z)");
    }
    // [ms1-funnel] Measured recall against a DIA-NN truth set is 74.3% vs the reference implementation's 84.4%, but a
    // single number cannot say WHERE a precursor is lost: no MS1 trace at all, a trace that never
    // became a hypothesis, or a hypothesis that never produced a spectrum. Dump both upstream
    // stages so the loss can be attributed to one of them instead of guessed at.
    const String ms1_dump = getStringOption_("diag:dump_ms1_tsv");
    if (!ms1_dump.empty())
    {
      // [fwhm] FWHM straight from each trace's own XIC rather than from
      // ElutionPeakDetection, so the measurement does not depend on whether split_valleys ran.
      // Apex, then walk outwards to half maximum with linear interpolation between samples;
      // -1 when the trace never falls to half max on both sides (truncated peak), which must be
      // reported rather than silently imputed -- a truncated peak is not a narrow one.
      auto fwhm_of = [&ms1_store](const Trace& tr) -> double {
        if (tr.np() < 3) return -1.0;
        vector<double> prt, pv; packReal(ms1_store, tr, prt, pv);
        size_t ap = 0;
        for (size_t i = 1; i < pv.size(); ++i) if (pv[i] > pv[ap]) ap = i;
        const double half = pv[ap] * 0.5;
        double lo = prt[0], hi = prt[pv.size() - 1];
        for (size_t i = ap; i > 0; --i)
          if (pv[i - 1] <= half)
          {
            const double d = pv[i] - pv[i - 1];
            const double f = d > 0 ? (pv[i] - half) / d : 0.0;
            lo = prt[i] - f * (prt[i] - prt[i - 1]);
            break;
          }
        for (size_t i = ap; i + 1 < pv.size(); ++i)
          if (pv[i + 1] <= half)
          {
            const double d = pv[i] - pv[i + 1];
            const double f = d > 0 ? (pv[i] - half) / d : 0.0;
            hi = prt[i] + f * (prt[i + 1] - prt[i]);
            break;
          }
        return hi - lo;
      };
      ofstream ft((ms1_dump + ".traces.tsv").c_str());
      // [model] 12 significant digits, not the ostream default 6: at m/z 765 six digits quantise
      // to ~1 mDa = 1.3 ppm inside a 15 ppm isotope window, which both flips borderline partner
      // matches and destroys the ppm-residual feature a charge model needs. Every dump written
      // before 2026-07-23 carries that quantisation.
      ft.precision(12);
      ft << "mz\trt\tim\tintensity\tfwhm_s\tn_xic\trt_first\trt_last\n";   // [tile-0d] span endpoints
      for (const auto& t : ms1_traces)
        ft << t.mz << '\t' << rtOf(ms1_store, t) << '\t' << t.im << '\t' << intensityOf(ms1_store, t) << '\t'
           << fwhm_of(t) << '\t' << t.np() << '\t'
           << (t.span() ? rtAtSpan(ms1_store, t, 0) : 0.0) << '\t' << (t.span() ? rtAtSpan(ms1_store, t, t.span() - 1) : 0.0) << '\n';
      ft.close();
      ofstream fp((ms1_dump + ".precursors.tsv").c_str());
      fp.precision(12);
      // [model] trace_idx makes the hypothesis -> seed-trace link explicit, so an offline replica
      // of inferPrecursors_ can be checked row-for-row rather than assumed to agree.
      fp << "mono_mz\tcharge\trt\tim\tguessed\ttrace_idx\n";
      for (const auto& pc : precursors)
        fp << pc.mono_mz << '\t' << pc.charge << '\t' << pc.rt << '\t' << pc.im << '\t'
           << (pc.guessed ? 1 : 0) << '\t' << pc.trace_idx << '\n';
      fp.close();
      writeLogInfo_("MS1 funnel dump: " + String(ms1_traces.size()) + " traces, "
                    + String(precursors.size()) + " precursors -> " + ms1_dump + ".{traces,precursors}.tsv");
    }
    // sort precursors by mono m/z so each window can binary-search its members instead of
    // rescanning all ~1M precursors per window (total order for determinism).
    sort(precursors.begin(), precursors.end(), [](const Precursor_& a, const Precursor_& b) {
      if (a.mono_mz != b.mono_mz) return a.mono_mz < b.mono_mz;
      if (a.rt != b.rt) return a.rt < b.rt;
      if (a.im != b.im) return a.im < b.im;
      return a.trace_idx < b.trace_idx;
    });
    vector<double> prec_mz(precursors.size());
    for (size_t i = 0; i < precursors.size(); ++i) prec_mz[i] = precursors[i].mono_mz;
    // NOTE: ms1_map is already empty here. detectTraces_ takes it by non-const reference and
    // releases every spectrum as it distributes it into the m/z bands, then clears the container
    // itself; a clear() at this point frees nothing. The bytes it used to be credited with are
    // released one phase earlier -- into the picking threads' allocator arenas, which is why the
    // resident set does not fall there either. [mem]
    // MEMORY: scoring reads the profile of ms1_traces[pc.trace_idx], so ms1_traces must STAY -- but only the
    // traces an actual precursor points at are ever dereferenced. Free the xic of the rest
    // (2.5M traces vs 1.2M precursors => roughly half are dead weight held through scoring). [mem]
    {
      vector<bool> needed(ms1_traces.size(), false);
      for (const auto& pc : precursors)
        if (pc.trace_idx < ms1_traces.size()) needed[pc.trace_idx] = true;
      // The spans share one arena, so releasing a trace means COMPACTING, in place (a second arena
      // would double the MS1 arena at exactly the moment it is largest) and in OFFSET order -- see
      // compactUnreferenced() for why container order corrupted ~1% of the kept spans.
      const Size freed = compactUnreferenced(ms1_traces, ms1_store, needed);
      writeLogInfo_("Released XICs of " + String(freed) + " unreferenced MS1 traces." + rss_() + mem_());
#ifdef __GLIBC__
    if (trim_on)
    { const double _tt = phase_clock_(); const long _r0 = rss_mb_();
      malloc_trim(0);
      writeLogInfo_("[trim] MS1 -> window loop: " + String(_r0) + " -> " + String(rss_mb_()) + " MB RSS in "
                    + String(phase_clock_() - _tt) + " s" + mem_());
    }
#endif
    }
    writeLogInfo_(clk_() + " Detected " + String(ms1_traces.size()) + " MS1 traces -> " + String(precursors.size())
                  + " precursor hypotheses (" + String(n_default) + " assigned default charge)." + rss_());
    std::exception_ptr worker_err;

    //-------------------------------------------------------------
    // PARALLEL over windows (independent; with ~24 windows this fully uses the cores, and each
    // window's trace detection AND gating run on its own core). Each window frees its raw frames
    // right after trace extraction. Per-window buckets are merged in fixed window order then
    // canonically sorted, so output is thread-count-independent. Exceptions (e.g. MassTraceDetection
    // on a degenerate window) are captured and rethrown serially. [C-3,H-5,C-5,par-Crit-2/3/4]
    //-------------------------------------------------------------
    vector<pair<WinKey, vector<CompactFrame>*>> window_list;
    window_list.reserve(ms2_by_window.size());
    for (auto& kv : ms2_by_window) window_list.emplace_back(kv.first, &kv.second);
    // [heavy-first] Process the biggest windows FIRST. With n_conc slots and unequal windows,
    // a small window admitted late runs nearly alone in the tail; starting the largest first
    // gives the scheduler the whole run to overlap it. The widest tile holds ~23.7% of all
    // precursors, so tail order dominates wall time. Cost proxy = compact bytes (peaks to trace),
    // which correlates with both trace and score work. Output order is unaffected: a canonical
    // total-order sort over all emitted spectra runs after the loop, so reordering here is safe.
    {
      auto wbytes = [](const vector<CompactFrame>& fr) { size_t b = 0; for (const auto& f : fr) b += f.bytes(); return b; };
      { auto& st = phase_stats_()["PRECURSOR_INFER"]; if (st.n++ == 0) phase_order_().push_back("PRECURSOR_INFER");
        st.wall += phase_clock_() - _t_inf; st.cpu += cpu_seconds_() - _c_inf; st.rss_end_mb = rss_mb_(); }
      _t_win = phase_clock_(); _c_win = cpu_seconds_();          // [perf-instr] window loop
      std::stable_sort(window_list.begin(), window_list.end(),
                       [&](const auto& a, const auto& b) { return wbytes(*a.second) > wbytes(*b.second); });
    }
    vector<vector<MSSpectrum>> win_out(window_list.size());
    Size win_done = 0;
    // MEMORY vs SPEED: every concurrently-processed window holds its own frames + traces + grid, so
    // peak RSS scales with the number of windows in flight, not with the window count. Capping
    // concurrency trades wall time for RAM. 0 = unlimited (previous behaviour). [mem]
    const int max_conc = getIntOption_("perf:max_concurrent_windows");
    int n_threads = 1;
#ifdef _OPENMP
    n_threads = omp_get_max_threads();
#endif
    // [bands] The window count is FIXED BY THE ACQUISITION METHOD (24 tiles here), so
    // min(windows, threads) pinned us to 24 cores no matter the machine -- measured: 24
    // concurrent windows on a 224-core node ran at load ~20. The ceiling is now the thread
    // count, with each window split into m/z bands to supply the extra work units.
    // [bands] PER-WINDOW band count, sized from the window itself rather than one global
    // constant. Measured motivation: tracing is 69.3% of window-loop CPU (materialize 0.10,
    // trace 69.34, fraggrid 1.75, score 28.81, emit 0.01), and MassTraceDetection has no OpenMP
    // of its own -- banding is the only way to parallelise it.
    //
    // A global count is wrong because the HALO IS A FIXED WIDTH PER BAND (20x mass_error_ppm on
    // each side, which is what makes the partition exact). Its overhead therefore depends on how
    // wide the band is:
    //     tile 328-469 Da (141 wide):  24 bands ->  5% halo overhead
    //     tile 564-583 Da (19 wide):   24 bands -> 57% halo overhead
    // So a wide tile tolerates many bands and a narrow one does not. Sizing per window also
    // hands the most parallelism to the widest tile -- which holds 23.7% of all precursors and
    // is the Amdahl tail of this loop.
    //
    // min_band_da = 8x the halo keeps overhead near 12% at the narrow end. Bands are capped by
    // the thread budget so windows x bands cannot oversubscribe.
    int n_bands = getIntOption_("perf:trace_bands");
    if (n_bands <= 0)  // auto: enough bands that windows x bands covers every thread
      n_bands = (int)std::ceil((double)n_threads / std::max<size_t>(window_list.size(), 1));
    n_bands = std::max(1, n_bands);
    // TOTAL live threads are outer x inner. Capping only the inner team (as a first cut did)
    // gave 24 windows x 9 bands = 216 threads on a 224-core box that another job was already
    // loading to ~173 -- measured: 11 of 24 windows in 98 min against a 40 min single-band
    // reference. Divide the thread budget between the two levels instead of multiplying it.
    // [master/worker] n_conc no longer partitions the thread pool -- tasks do that. It is now
    // only the number of windows allowed IN FLIGHT, i.e. how many materialised windows may hold
    // memory at once, and the free-RAM admission gate below is the real bound. Deriving it from
    // threads/bands (the old 100/12 = 8) was what pinned the tool to a 96-thread grid.
    // MEASURED 2026-09-03: letting every window be in flight raised window-loop occupancy from
    // 64.8x to 86.2x -- and made the run SLOWER (15:50 against 12:53) because peak RSS went 103 ->
    // 152 GB and system time rose 75%: more resident windows means a bigger working set, more page
    // faults and worse locality, not more useful work. Occupancy and working set are separate
    // knobs and the task pool only fixes the first. So keep a default cap on windows IN FLIGHT --
    // the old threads/bands value, which was accidentally a reasonable working-set bound -- while
    // the pool goes on filling every thread from whatever is admitted.
    // I capped this earlier because the task pool alone had been SLOWER (15:50 vs 12:53) and I
    // read that as an oversized working set. The measurement says otherwise: once the scoring gate
    // stopped striding 96-byte records, uncapped is slightly faster (7:04 vs 7:15) at the SAME peak
    // memory (157 GB both ways). The pool's regression was the gate's bandwidth problem amplified
    // by concurrency, not a working-set problem of its own -- so the cap is not needed, and taking
    // it out costs nothing. `perf:max_concurrent_windows` still bounds it for a small machine.
    int n_conc = (int)window_list.size();
    if (max_conc > 0) n_conc = std::min(n_conc, max_conc);
    if (n_conc < 1) n_conc = 1;
#ifdef _OPENMP
    // outer loop over windows + inner loop over bands = two live levels
    if (n_bands > 1) omp_set_max_active_levels(2);
#endif
    writeLogInfo_("Parallelism: " + String(window_list.size()) + " windows x " + String(n_bands)
                  + " m/z bands = " + String((int)window_list.size() * n_bands) + " trace units; "
                  + String(n_threads) + " worker threads over one task pool; up to "
                  + String(n_conc) + " windows in flight (memory-bounded)");
    // [dyn-mem] Thread count is the UPPER bound; free RAM is the real one. A static cap either
    // wastes cores on a big machine or OOMs on a shared one, and this node is shared. Admit each
    // window only when its projected footprint fits in currently-free RAM, re-read from
    // /proc/meminfo at each admission so the run yields to other jobs instead of fighting them.
    // Always admit when nothing is in flight, so the loop cannot deadlock on a single huge window.
    bool integer_detector = (getStringOption_("trace:detector") == "integer");
    String why = "not attempted";
    if (integer_detector && !tofAxis().ok)
    {
      // The flight-time axis comes from the input's own analysis.tdf: a .d directory has one, and an
      // mzPeak archive can be accompanied by one (SPEXTRACTOR_MZPEAK_TDF, as the exact-calibration
      // path already uses).
      why = "no candidate tdf";
      std::vector<std::string> cand;
      cand.push_back(in + "/analysis.tdf");
      if (const char* sc = std::getenv("SPEXTRACTOR_MZPEAK_TDF")) cand.push_back(sc);
      for (const std::string& c : cand)
        if (loadTofAxis(c, why)) { writeLogInfo_("flight-time axis from " + c + ": "
              + String(tofAxis().b_by_frame.size()) + " frame factors"); break; }
    }
    // FAIL CLOSED on frames the calibration cannot address. A .d names every frame "frame=<Id>";
    // an mzML (or an archive index) may not, and frameIdOf() returns 0 for anything it cannot
    // parse. With index 0 backfilled to the reference factor those frames used to calibrate
    // SILENTLY at reference temperature, skipping the warning below entirely -- an mzML plus a
    // sidecar tdf loaded "fine" and produced masses that were never calibrated per frame. The
    // temperature term is small (0.669 ppm, tests/test_calibration.py) but it is exactly the
    // invented calibration this path exists to refuse, so an unmapped frame now costs the integer
    // detector rather than being papered over.
    if (integer_detector && tofAxis().ok && cstat.unmapped_frame > 0)
    {
      writeLogWarn_("trace:detector=integer needs a per-frame calibration factor for EVERY frame, and "
                    + String(cstat.unmapped_frame) + " frame(s) carry a nativeID with no parseable "
                    "\"frame=<Id>\" key, so they cannot be addressed in the tdf's Frames table. Falling "
                    "back to trace:detector=openms rather than calibrating them at reference "
                    "temperature. A Bruker .d always names its frames; an mzML converted from one may "
                    "not. Pass -trace:detector openms to silence this.");
      integer_detector = false;
    }
    if (integer_detector && !tofAxis().ok)
    {
      // FALL BACK, do not refuse. Failing closed is right when the alternative is inventing a
      // calibration -- that would put wrong masses in the output. Here there is a second detector
      // that needs no calibration at all, so refusing would only make the tool unusable on inputs
      // it handled before this became the default. Which one ran is recorded in the output as
      // spx:detector, so a file is always attributable.
      writeLogWarn_("trace:detector=integer needs the vendor flight-time calibration (MzCalibration "
                    "+ Frames.T1 from analysis.tdf) and it was not available for this input ("
                    + why + "). Falling back to trace:detector=openms; the two detectors agree on about "
                    "85% of the union of identified peptides, so this file is NOT comparable peptide-for-peptide "
                    "with one traced on the integer axis. Pass -trace:detector openms to silence this.");
      integer_detector = false;
    }
    const double mem_frac = getDoubleOption_("perf:mem_fraction");
    std::atomic<size_t> inflight{0};
    std::atomic<int> adm_hwm{0};   // high-water mark of admitted windows, for the log and the e2e
    // [Fix A] The compact store is consumed window by window (toSlab/materializeWindow swap each
    // frame's vectors away), but it was all arena memory in ~126 kB chunks, so glibc kept every
    // freed byte on its free lists: measured, 43 GB whose last read is the last materialisation
    // stayed resident for 425 of the loop's 431 s. Return it ONCE, when the last window has
    // materialised, under the same gate as the two phase-boundary trims. Zero-code arm on record
    // (2026-09-09): forcing every >=64 kB block to mmap took the peak from 168.2 to 154.2 GB but
    // cost +28% wall through LOAD; a single trim here is the same reclaim at ~4 s.
    std::atomic<size_t> n_materialised{0};
    // Projected footprint per window, from its own compact size. RE-CALIBRATED 2026-09-03: the
    // 10x multiplier booked the average dataset A window at 8.9 GB against a measured 12-14 GB, i.e. it
    // under-booked by 35-55% in the UNSAFE direction -- it admitted more windows than fit. That was
    // survivable while the thread grid capped concurrency at 8 anyway; with the task pool, memory
    // is the only bound, so the estimate has to be honest.
    // RE-CALIBRATED AGAIN 2026-09-06, this time against the per-window [mem] lines rather than a
    // multiplier: over 28 windows of a 2-h acquisition the SUSTAINED footprint of a window is
    // ~44 B per compact peak (slab 10 + seed order 3.8 + band/visited ~6 + trace records 51 at
    // 0.21 parents + 0.28 children per peak x 56 B + span arena 4.4 + scoring copies 12.9, minus
    // the stages that do not coexist). The old 16x of the COMPACT BYTES booked 160 B/peak, i.e.
    // 3.6x the sustained figure, which is why the gate never throttled anything.
    auto project = [&](const vector<CompactFrame>& fr) {
      size_t peaks = 0; for (const auto& f : fr) peaks += f.mzq.size();
      return peaks * (size_t)44 + (size_t)256 * 1024 * 1024;
    };
    writeLogInfo_("Processing " + String(window_list.size()) + " isolation windows (OpenMP over windows, <="
                  + String(n_conc) + " concurrent, admission bounded by " + String((int)(mem_frac * 100))
                  + "% of free RAM)..." + rss_() + mem_());

    // [timers] phase_clock_ is never called between the start of this loop and its end, so
    // EVERYTHING said about where the loop's 85.9% goes has been inference. Two performance
    // fixes were already attempted and reverted against a model that was never verified. These
    // are atomic nanosecond accumulators -- one add per stage per window, so the measurement
    // cost is unmeasurable against stages that run for minutes.
    std::atomic<long long> t_mat{0}, t_trace{0}, t_grid{0}, t_score{0}, t_emit{0};
    std::atomic<bool> span_logged{false};
    // [master/worker, 2026-09-03] The loop used to be `parallel for num_threads(n_conc)` with
    // nested `parallel for num_threads(n_bands)` inside, i.e. a RIGID n_conc x n_bands grid
    // (8 x 12 = 96 of 100 threads). Two costs followed from the rigidity: the grid never fills the
    // last 4 threads, and when fewer windows remain than slots the survivors keep only their own
    // 12-thread team while the rest of the machine idles -- measured 67.9x of 100 on dataset A, 71% of
    // the grid's own ceiling. Here ONE thread (the master) walks the windows heaviest-first and
    // throttles on memory, and every unit of work inside a window is an OpenMP TASK. Idle threads
    // steal across window boundaries, so the tail of one window is filled by another's bands.
    // Output is unaffected: every result is written to an index-addressed slot (win_out[wi],
    // pslot[pi-plo], per[b]), never appended in completion order.
    // [admit] The master admits BEFORE spawning: the byte budget and the window cap are both
    // enforced by construction, and no worker thread sits in a spin loop holding a slot it cannot
    // use. `perf:max_concurrent_windows` was computed and logged but never actually checked --
    // the only bound was the byte gate, which over-booked by 3.6x, so nothing ever throttled.
    std::atomic<int> active{0};
    #pragma omp parallel num_threads(n_threads)
    #pragma omp single
    for (long wi = 0; wi < (long)window_list.size(); ++wi)
    {
      {
        const size_t need = project(*window_list[wi].second);
        for (;;)
        {
          const size_t budget = (size_t)(availableBytes_() * mem_frac);
          // "at least one": an empty pipeline always admits, however large the window
          if ((active.load() == 0) || (active.load() < n_conc && inflight.load() + need <= budget)) break;
          #pragma omp taskyield
          std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        inflight += need; ++active;
        if (active.load() > adm_hwm.load()) adm_hwm.store(active.load());
      }
      #pragma omp task default(shared) firstprivate(wi)
      {
      // A lambda, because `continue` is not a legal exit from a task's structured block and the
      // window body has one early exit (a window whose fragments all fail the finiteness filter).
      [&]() {
      try
      {
        const double win_lo = window_list[wi].first[0] / 100.0;
        const double win_hi = window_list[wi].first[1] / 100.0;
        // admitted by the master before this task existed; release both charges however we leave
        const size_t need = project(*window_list[wi].second);
        struct Release { std::atomic<size_t>& b; std::atomic<int>& a; size_t n;
                         ~Release() { b -= n; --a; } } rel{inflight, active, need};
        // Per-window stage seconds and the completion line, printed on EVERY exit of the body
        // (empty window, any assembly arm, exception): what the profile could only infer. [mem]
        double w_prep = 0, w_trace = 0, w_split = 0, w_score = 0, w_emit = 0;
        // [tsub] w_trace bundles more than the band taskloop -- the slab build, the serial arena
        // merge, and a full sort of every trace record in the window. Time them apart, so the next
        // decision about this stage is measured rather than attributed to the parallel part.
        double w_slab = 0, w_detect = 0, w_merge = 0, w_sort = 0;
        auto secs = [](auto d) { return std::chrono::duration<double>(d).count(); };
        struct WinDone { std::function<void()> f; ~WinDone() { f(); } } win_done_guard{[&]() {
          #pragma omp critical(winlog)
          writeLogInfo_("  window " + String(++win_done) + "/" + String(window_list.size()) + " " + String(win_lo) + "-" + String(win_hi)
                        + ": prep " + String(w_prep) + " s | trace " + String(w_trace) + " s | split " + String(w_split)
                        + " s | score " + String(w_score) + " s | emit " + String(w_emit) + " s | spectra " + String(win_out[wi].size()) + clk_()
                        + "\n    [tsub] " + String(win_lo) + "-" + String(win_hi) + " trace = slab " + String(w_slab)
                        + " + detect " + String(w_detect) + " + merge " + String(w_merge) + " + sort " + String(w_sort) + " s");
        }};
        // [compact] materialise ONLY this window, and free its compact frames as we go
        auto _t0 = std::chrono::steady_clock::now();
        // The integer detector reads the compact store directly; only the OpenMS path needs the
        // peaks converted back into Peak1D doubles, which is the largest per-window allocation.
        PeakMap wmap;
        PeakSlab wslab;
        if (integer_detector)
        {
          { auto _tsl = std::chrono::steady_clock::now();
            wslab = toSlab(*window_list[wi].second);
            w_slab = secs(std::chrono::steady_clock::now() - _tsl); }
          if (detOn_())
          {
            #pragma omp critical
            writeLogInfo_("[det] window " + String(win_lo) + "-" + String(win_hi) + " slab n=" + String(wslab.peaks()) + " digest=" + String(slabDigest_(wslab)));
          }
        }
        else
        {
          wmap = materializeWindow(*window_list[wi].second);
          if (detOn_())   // [det] compact store digest BEFORE tracing: splits "pick" from "trace+assemble"
          {
            // materializeWindow consumed the frames; digest the materialised map instead (same content)
            vector<uint64_t> b;
            for (const auto& sp : wmap) for (const auto& pk : sp) { uint64_t u; double v = pk.getMZ(); std::memcpy(&u, &v, 8); b.push_back(u); float f = pk.getIntensity(); uint32_t w; std::memcpy(&w, &f, 4); b.push_back(w); }
            #pragma omp critical
            writeLogInfo_("[det] window " + String(win_lo) + "-" + String(win_hi) + " compact n=" + String(b.size() / 2) + " digest=" + String(detDigest_(std::move(b))));
          }
        }
        if (++n_materialised == window_list.size() && trim_on)
        { const double _tt = phase_clock_(); const long _r0 = rss_mb_();
#ifdef __GLIBC__
          malloc_trim(0);
#endif
          writeLogInfo_("[trim] last window materialised -> compact store returned: " + String(_r0) + " -> "
                        + String(rss_mb_()) + " MB RSS in " + String(phase_clock_() - _tt) + " s" + mem_()); }
        auto _t1 = std::chrono::steady_clock::now();
        t_mat += std::chrono::duration_cast<std::chrono::nanoseconds>(_t1 - _t0).count();
        for (MSSpectrum& s : wmap) s.setMSLevel(1); // MassTraceDetection traces MS1-level only
        wmap.sortSpectra();
        String ms2_span;
        auto _t2 = std::chrono::steady_clock::now();
        // per-window band count: n_bands is the AUTO cap (threads/windows); a wide tile may exceed
        // it since bands are cheap relative to the trace work they unlock, a narrow one may not
        // reach it. Explicit -perf:trace_bands N pins every window to N.
        // MEASURED on dataset D: a flat 12 bands beats a per-window width-derived band count by 25% and beats
        // flat 24 as well (1,844 s vs 2,483 s vs 1,987 s). The heuristic under-provisioned
        // because it sized bands against HALO overhead, and the halo term turned out to be
        // dominated by a much larger effect: trace CPU falls 11,168 -> 5,378 -> 2,972 s across
        // 5/12/24 bands, i.e. banding REDUCES TOTAL WORK, not just wall time.
        // MassTraceDetection scans candidates per apex within the band's m/z range, so halving a
        // band halves the candidate list for every apex in it -- superlinear, and it swamps the
        // fixed per-band halo cost. 24 bands then loses to 12 on wall time despite half the CPU,
        // because 24 windows x 24 bands = 576 threads on 100 cores and scheduling overtakes the
        // algorithmic gain.
        // [auto-band-fix] Use the RESOLVED n_bands, not the raw option. In auto mode
        // (perf:trace_bands=0) n_bands was computed as ceil(threads/windows) at the top and
        // n_conc was sized from it, but the actual call here re-read the raw 0 and max(1,0)=1
        // traced every window SERIALLY while the log advertised multiple bands. Passing n_bands
        // keeps the advertised and actual band counts identical. Explicit values pass through
        // unchanged (n_bands == the option when the option is > 0).
        const int w_bands = n_bands;
        vector<Trace> frag_traces;
        TraceStore wst;                                   // this window's frame table + arenas; outlives scoring
        size_t w_live = 0;                                // [tile-0d] G_live, carried out of the tracing block
        if (integer_detector)
        {
          wst.setFrames(wslab.rt_index, &wslab.b);
          // Banded like the OpenMS path. A band SEEDS only in its own flight-time core but may
          // extend anywhere, so no halo is needed and no trace is cut; the one approximation is
          // that two bands can take the same peak (each has its own `visited`), which is the same
          // class of error the OpenMS halo carries -- measured at 0.1% of peptides. Bands are
          // TASKS, so they fill the pool alongside every other window's work.
          TofIdx tlo = 0xFFFFFFFFu, thi = 0;
          for (TofIdx t : wslab.tof) { tlo = std::min(tlo, t); thi = std::max(thi, t); }
          const int nb = (thi <= tlo) ? 1 : std::max(1, w_bands);
          // [tile-0d] the slab-derived band bounds a tiled design would have to inject globally
          writeLogInfo_("[tof] window " + String(win_lo) + "-" + String(win_hi) + " tlo=" + String(tlo)
                        + " thi=" + String(thi) + " frames=" + String(wslab.frames()) + " peaks=" + String(wslab.peaks()));
          size_t n_seeds = 0, n_parents = 0;
          const size_t n_peaks = wslab.peaks();
          {
          // The band edges are computed ONCE and shared by the seed segmentation and the detector,
          // so the two can never disagree about which band owns a seed.
          vector<TofIdx> bnd;
          if (nb > 1)
          {
            const double wdt = (double)(thi - tlo + 1) / nb;
            bnd.resize(nb + 1);
            for (int b = 0; b < nb; ++b) bnd[b] = tlo + (TofIdx)(b * wdt);
            bnd[nb] = thi + 1;
          }
          else bnd = {0, 0};
          auto _tp = std::chrono::steady_clock::now();
          TracePrep tprep = prepareTracing(wslab, ms2_noise, ms2_snr, bnd, tlo, thi);   // once per window
          w_prep = secs(std::chrono::steady_clock::now() - _tp);
          n_seeds = tprep.order.size(); w_live = tprep.n_live;
          // The slab and the seed order are dead the moment the detector returns: the merge below
          // reads only the band stores, and valley splitting reads only the window store. Releasing
          // them HERE rather than after the merge matters because the merge is the peak allocation
          // of the window -- it reserves the whole merged arena while every band arena is still
          // live -- so the slab used to be resident across exactly the worst moment. [2026-09-06]
          auto release_input = [&]() {
            vector<TofIdx>().swap(wslab.tof); vector<float>().swap(wslab.inten);
            vector<uint16_t>().swap(wslab.imq); vector<uint32_t>().swap(wslab.frame_off);
            vector<double>().swap(wslab.b); vector<uint32_t>().swap(wslab.rt_index);
            vector<uint32_t>().swap(tprep.order); vector<char>().swap(tprep.frame_live);
            vector<size_t>().swap(tprep.seg); vector<uint32_t>().swap(tprep.fidx);
          };
          // Each band appends spans to a PRIVATE store; after the taskloop joins, the window
          // store absorbs them in band order and every offset is rebased (R4 sequencing).
          vector<TraceStore> bst(std::max(1, nb));
          if (nb == 1)
          {
            frag_traces = detectTracesInteger_(wslab, tprep, bst[0], mass_ppm, delta_im, ms2_noise, ms2_minlen, ms2_msr);
            release_input();
          }
          else
          {
            vector<vector<Trace>> per(nb);
            auto _td0 = std::chrono::steady_clock::now();
            #pragma omp taskloop grainsize(1) default(shared)
            for (int b = 0; b < nb; ++b)
              per[b] = detectTracesInteger_(wslab, tprep, bst[b], mass_ppm, delta_im, ms2_noise, ms2_minlen, ms2_msr,
                                            bnd[b], bnd[b + 1], b);
            w_detect = secs(std::chrono::steady_clock::now() - _td0);
            auto _tm0 = std::chrono::steady_clock::now();
            release_input();                       // before the merge, not after it
            size_t tot = 0, arena = 0; bool any_bins = false;
            for (int b = 0; b < nb; ++b)
            { tot += per[b].size(); arena += bst[b].inten.size(); any_bins |= !bst[b].bins.empty(); }
            frag_traces.reserve(tot);
            wst.inten.reserve(arena); if (any_bins) wst.bins.reserve(arena);   // as in splitIntegerTraces
            writeLogInfo_("[mem] window " + String(win_lo) + "-" + String(win_hi) + " merge: " + String(nb) + " band arenas, "
                          + String(arena) + " floats (" + String(arena * (any_bins ? 6 : 4) / (1024ULL * 1024ULL)) + " MB) x2 while absorbed, " + String(tot) + " traces");
            for (int b = 0; b < nb; ++b)
            {
              const uint32_t base = wst.absorb(bst[b]);
              for (auto& t : per[b]) { t.off += base; frag_traces.push_back(std::move(t)); }
              vector<Trace>().swap(per[b]);
            }
            w_merge = secs(std::chrono::steady_clock::now() - _tm0);
          }
          if (nb == 1) { const uint32_t base = wst.absorb(bst[0]); for (auto& t : frag_traces) t.off += base; }
          }                                                  // tprep dies here
          // (the slab and the seed order were released above, before the band-arena merge)
          // The same valley-splitting step the OpenMS path runs; skipping it was one of the
          // defects behind the first version's 92% peptide loss. It rebuilds the arena, so the
          // store pointers are set again afterwards; the per-frame bins are dead after it.
          n_parents = frag_traces.size();
          auto _ts = std::chrono::steady_clock::now();
          frag_traces = splitIntegerTraces(frag_traces, ms2_split, wst, std::max(1, w_bands) * 4);
          w_split = secs(std::chrono::steady_clock::now() - _ts);
          // [tile-0d] RT extent of fragment traces on the INTEGER path, which `ms2_span` never
          // reports (it is only filled by the OpenMS detector). Two figures per trace: the total
          // span, and the ONE-SIDED extent from the reported RT (rtOf) -- the quantity a tile halo
          // has to cover, since trimToSpan bounds the span, not the distance from the apex.
          // Logged before and after the trim so the halo can be sized on detection extent.
          auto extents = [&](const char* tag) {
            const size_t NB = 256; const double BW = 5.0;                     // 5-s bins to 1,280 s
            vector<size_t> hs(NB + 1, 0), ho(NB + 1, 0); double mx_s = 0, mx_o = 0; size_t n = 0;
            for (const auto& t : frag_traces)
            { if (t.span() == 0) continue; ++n;
              const double r0 = rtAtSpan(wst, t, 0), r1 = rtAtSpan(wst, t, t.span() - 1), rr = rtOf(wst, t);
              const double sp = r1 - r0, os = std::max(rr - r0, r1 - rr);
              mx_s = std::max(mx_s, sp); mx_o = std::max(mx_o, os);
              ++hs[std::min<size_t>(NB, (size_t)(sp / BW))]; ++ho[std::min<size_t>(NB, (size_t)(os / BW))]; }
            auto q = [&](const vector<size_t>& h, double p) { size_t acc = 0; const size_t want = (size_t)(p * n);
              for (size_t i = 0; i <= NB; ++i) { acc += h[i]; if (acc >= want) return (i + 1) * BW; } return (NB + 1) * BW; };
            auto fr = [&](const vector<size_t>& h, double x) { size_t acc = 0; for (size_t i = (size_t)(x / BW); i <= NB; ++i) acc += h[i];
              return n ? 100.0 * acc / n : 0.0; };
            writeLogInfo_("[ms2ext] window " + String(win_lo) + "-" + String(win_hi) + " " + tag + " n=" + String(n)
                          + " span p50=" + String(q(hs, .5)) + " p90=" + String(q(hs, .9)) + " p99=" + String(q(hs, .99)) + " max=" + String(mx_s)
                          + " frac>120=" + String(fr(hs, 120)) + "% frac>246=" + String(fr(hs, 246)) + "%"
                          + " | onesided p50=" + String(q(ho, .5)) + " p90=" + String(q(ho, .9)) + " p99=" + String(q(ho, .99)) + " max=" + String(mx_o)
                          + " frac>63=" + String(fr(ho, 63)) + "% frac>123=" + String(fr(ho, 123)) + "% frac>300=" + String(fr(ho, 300)) + "%");
          };
          if (detOn_()) extents("pre-trim");
          if (max_span > 0.0) for (auto& t : frag_traces) trimToSpan(wst, t, max_span);
          if (detOn_()) extents("post-trim");
          vector<int16_t>().swap(wst.bins);
          writeLogInfo_("[mem] window " + String(win_lo) + "-" + String(win_hi) + ": seeds " + String(n_seeds) + " of " + String(n_peaks)
                        + " peaks (" + String((int)(1000.0 * n_seeds / std::max<size_t>(n_peaks, 1)) / 10.0) + "%); traces " + String(n_parents)
                        + " -> " + String(frag_traces.size()) + " (cap " + String(frag_traces.capacity()) + ", "
                        + String(frag_traces.capacity() * sizeof(Trace) / (1024ULL * 1024ULL)) + " MB); arena " + String(wst.inten.size()) + "/"
                        + String(wst.inten.capacity()) + " floats (" + String(wst.inten.capacity() * 4 / (1024ULL * 1024ULL)) + " MB)" + rss_());
        }
        else
        {
          { vector<uint32_t> ri; ri.reserve(wmap.size());          // wmap is RT-sorted above
            for (const auto& sp : wmap) ri.push_back(rtIndex(sp.getRT()));
            wst.setFrames(ri, nullptr); }
          frag_traces = detectTraces_(wmap, wst, delta_im, ms2_noise, ms2_snr, ms2_minlen, ms2_msr, ms2_split, &ms2_span, w_bands);
          if (max_span > 0.0) for (auto& t : frag_traces) trimToSpan(wst, t, max_span);
        }
        // the window's spans and records, released with the window (the old add-only line was
        // cumulative over the run, not a peak)
        if (detOn_())
        {
          #pragma omp critical
          writeLogInfo_("[det] window " + String(win_lo) + "-" + String(win_hi) + " frag traces n=" + String(frag_traces.size()) + " digest=" + String(traceDigest_(wst, frag_traces)));
        }
        // (compact frames already released inside materializeWindow) [par-Crit-3]
        if (!span_logged.exchange(true)) { // [merged-trace] one window's span statistics, once
          #pragma omp critical
          writeLogInfo_("MS2 " + ms2_span);
        }

        auto _tso = std::chrono::steady_clock::now();
        frag_traces.erase(remove_if(frag_traces.begin(), frag_traces.end(), [&wst](const Trace& t) {
          return !std::isfinite(t.im) || !std::isfinite(t.mz) || !std::isfinite(rtOf(wst, t));
        }), frag_traces.end());
        if (frag_traces.empty()) return;   // nothing traceable in this window

        sort(frag_traces.begin(), frag_traces.end(), [&wst](const Trace& a, const Trace& b) {
          if (a.im != b.im) return a.im < b.im;
          if (a.mz != b.mz) return a.mz < b.mz;
          { const double ra = rtOf(wst, a), rb = rtOf(wst, b); if (ra != rb) return ra < rb; }
          return intensityOf(wst, a) < intensityOf(wst, b);
        });
        vector<double> frag_im(frag_traces.size());
        for (size_t i = 0; i < frag_traces.size(); ++i) frag_im[i] = frag_traces[i].im;
        FragRt frag_rt; frag_rt.build(frag_traces, wst, delta_rt);
        w_sort = secs(std::chrono::steady_clock::now() - _tso);

        // Precompute the common correlation grid once per window; pdense is reused across the
        // window's precursors (this window runs on one thread). [perf]
        auto _t3 = std::chrono::steady_clock::now();
        t_trace += std::chrono::duration_cast<std::chrono::nanoseconds>(_t3 - _t2).count();
        w_trace = secs(_t3 - _t2) - w_prep - w_split;
        FragStats fg = buildFragStats(frag_traces, wst, ms1_store, delta_rt);
        // [tile-0d] the Pearson denominator G against the two tile-independent candidates: the
        // window's frame count F and the frames with any above-noise peak G_live. If G == F the
        // denominator can be injected from metadata under RT tiling; if not, the statistic must
        // move to a G-free form (gate:variance_support / logoverlap) behind the peptide gate.
        writeLogInfo_("[gstat] window " + String(win_lo) + "-" + String(win_hi) + " F=" + String(wst.frames())
                      + " G=" + String(fg.G) + " G_live=" + String(w_live) + " frags=" + String(frag_traces.size()));
        auto _t4 = std::chrono::steady_clock::now();
        t_grid += std::chrono::duration_cast<std::chrono::nanoseconds>(_t4 - _t3).count();
        vector<float> pdense(wst.frames(), 0.0f);   // indexed by window-local frame

        vector<MSSpectrum>& bucket = win_out[wi];
        // only this window's precursors (by mono m/z); NaN mono_mz sorts to the end, excluded.
        // (charge 0 is NOT dropped: emitted with charge UNSET so the engine searches its range.)
        size_t plo = lower_bound(prec_mz.begin(), prec_mz.end(), win_lo) - prec_mz.begin();
        size_t phi = upper_bound(prec_mz.begin(), prec_mz.end(), win_hi) - prec_mz.begin();
        {
          // Share-all (default, current best): each fragment goes to EVERY gated precursor.
          //
          // [perf-3] PRECURSOR-LEVEL PARALLELISM. The outer loop's unit of work is the isolation
          // window -- an ACQUISITION-METHOD CONSTANT (24 tiles) with one tile holding 23.7% of
          // all precursors, so Amdahl caps that loop at 4.2x regardless of thread count. /proc
          // sampling caught the tail running 1,993 s at 1.000 user cores with 21 of 22 threads
          // in futex_wait: one window left, scoring its precursors serially. Precursors within a
          // window are independent, so they are the correct unit.
          //
          // An earlier attempt at this was REVERTED for LOSING SPECTRA: it appended to the shared
          // `bucket`, and a race dropped emissions (caught by a 15 MB smaller mzML, not by the
          // peptide count). This writes into a PRE-SIZED slot per precursor -- no append, no
          // critical section, so a lost write is structurally impossible. `pdense` is the scratch
          // buffer assembleOne_ writes through, so it must be firstprivate: sharing it across
          // threads is precisely the corruption the reverted attempt suffered.
          //
          // Order-safety: a canonical total-order sort over all_out runs after the window loop
          // (RT, precursor m/z, charge, then fragment sequence), so emission order is already
          // thread-count-independent. Only slot CONTENTS matter here.
          // THREAD CAP -- this region is NESTED inside the window loop (num_threads(n_conc)).
          // Without a cap it requests the full team PER WINDOW, i.e. n_conc x omp_get_max_threads()
          // threads on a fixed core count. That is precisely the defect diagnosed in
          // ElutionPeakDetection.cpp:328 (a bare parallel-for with no num_threads, reached from
          // inside this same loop, measured at 43.5% kernel time) -- reproduced here by omission.
          // Divide the budget instead of multiplying it.
          auto _t5 = std::chrono::steady_clock::now();
          vector<MSSpectrum> pslot(phi > plo ? phi - plo : 0);
          // grainsize, not num_threads: the pool decides how many threads land here, so a window
          // that outlives its neighbours gets the whole machine instead of a fixed team of 12.
          //
          // [gomp-cliff 2026-09-07] ...but the task COUNT must stay bounded, and `grainsize(32)`
          // does not bound it. libgomp's GOMP_taskloop runs the WHOLE loop inline in the creating
          // thread when `team->task_count + num_tasks > 64 * team->nthreads` -- with 100 threads
          // that is 6,400 tasks, i.e. 204,800 precursors at grainsize 32. Above that line the
          // stage silently becomes SINGLE-THREADED. Measured with a standalone taskloop on the
          // same libgomp (100 threads, 20 us per iteration):
          //     200,000 iters grainsize(32) ->  6,250 tasks -> 82.7x
          //     300,000 iters grainsize(32) ->  9,375 tasks ->  1.0x   <-- the cliff
          //     300,000 iters num_tasks(400) ->   400 tasks -> 88.0x
          // On TNBC 009 exactly two windows sit above the line, and they are the two that ran the
          // window loop into the ground: 525-551 scored 417.6 s and 575-601 scored 581.0 s, while
          // every neighbouring window -- same fragment count to within 16% -- scored 12-28 s. The
          // loop's wall (748.5 s) was window 575-601's own chain (741.9 s), 78% of it this stage.
          // Bound the task count instead: 4 tasks per thread is enough for dynamic balance and
          // leaves headroom for the other windows' band and split tasks under the same threshold.
          // Output-identical: every result goes to its own pre-sized slot, so task granularity
          // cannot reorder or drop an emission.
          // A fixed, small number of worker tasks that PULL 32-precursor chunks from a shared
          // cursor: dynamic balance without letting the task count depend on the window size, so
          // the task count no longer grows with the window size. The team-wide bound is then
          // 28 windows x (1 + ~100) = ~2,800 against the 6,400 threshold, with headroom for the
          // band and split taskloops -- a budget to keep in mind before adding another task layer,
          // not a guarantee that holds whatever else is queued.
          const long n_prec_w = (long)phi - (long)plo;
          const long n_task_w = std::max(1L, std::min((n_prec_w + 31) / 32, (long)n_threads));
          std::atomic<long> pcur{(long)plo};
          #pragma omp taskloop num_tasks(n_task_w) firstprivate(pdense) default(shared)
          for (long w = 0; w < n_task_w; ++w)
          {
            for (;;)
            {
              const long cs = pcur.fetch_add(32);
              if (cs >= (long)phi) break;
              const long ce = std::min(cs + 32, (long)phi);
              for (long pii = cs; pii < ce; ++pii)
              {
                const size_t pi = (size_t)pii;
                const Precursor_& pc = precursors[pi];
                if (!std::isfinite(pc.rt) || !std::isfinite(pc.im)) continue;
                MSSpectrum ms2;
                assembleOne_(pc, win_lo, win_hi, frag_traces, wst, frag_im, frag_rt, ms1_traces, ms1_store, fg,
                             delta_im, delta_rt, min_corr, min_corr_pts, min_frags, max_frags, pdense, ms2);
                if (!ms2.empty()) pslot[pi - plo] = std::move(ms2);
              }
            }
          }
          auto _t6 = std::chrono::steady_clock::now();
          t_score += std::chrono::duration_cast<std::chrono::nanoseconds>(_t6 - _t5).count();
          w_score = secs(_t6 - _t5);
          for (auto& s : pslot) if (!s.empty()) bucket.push_back(std::move(s));
          const auto _t7 = std::chrono::steady_clock::now();
          t_emit += std::chrono::duration_cast<std::chrono::nanoseconds>(_t7 - _t6).count();
          w_emit = secs(_t7 - _t6);
        }
      }
      catch (...)
      {
        #pragma omp critical
        if (!worker_err) worker_err = std::current_exception();
      }
      }();   // window body
      }      // omp task
    }
    if (worker_err) std::rethrow_exception(worker_err);
    // MEMORY: every MS1 structure is dead once the window loop has joined -- scoring was its only
    // reader (assembleOne_ -> scoreCandidates_ dereferences ms1_traces[pc.trace_idx] and its span).
    // They used to ride to the end of main_, i.e. through the canonical sort, the PeakMap
    // assembly and the whole mzML write. [mem]
    vector<Trace>().swap(ms1_traces);
    ms1_store = TraceStore();
    vector<Precursor_>().swap(precursors);
    vector<double>().swap(prec_mz);
    writeLogInfo_("[mem] MS1 traces, spans, precursors released after the window loop." + rss_() + mem_());

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
      malloc_trim(0);
      writeLogInfo_("[trim] window loop -> write: " + String(_r0) + " -> " + String(rss_mb_()) + " MB RSS in "
                    + String(phase_clock_() - _tt) + " s" + mem_());
    }
#endif
    {
      // These are CPU-seconds summed across threads, not wall time -- a stage that runs on 20
      // threads contributes 20x its wall. That is the right denominator for "where does the work
      // go", but it must not be read as wall time, so both are printed.
      const double S = 1e-9;
      const double tot = S * (t_mat + t_trace + t_grid + t_score + t_emit);
      auto pct = [&](long long v) { return tot > 0 ? 100.0 * S * v / tot : 0.0; };
      writeLogInfo_("Window-loop stage breakdown (each stage's own ELAPSED time, summed over "
                    "windows -- NOT CPU-seconds: stages of different windows run concurrently, so "
                    "this sum exceeds the loop's wall time; " + String(tot) + " s total):");
      writeLogInfo_("  materialize " + String(S * t_mat)   + " s (" + String(pct(t_mat))   + "%)");
      writeLogInfo_("  trace       " + String(S * t_trace) + " s (" + String(pct(t_trace)) + "%)");
      writeLogInfo_("  fraggrid    " + String(S * t_grid)  + " s (" + String(pct(t_grid))  + "%)");
      writeLogInfo_("  score       " + String(S * t_score) + " s (" + String(pct(t_score)) + "%)");
      writeLogInfo_("  emit        " + String(S * t_emit)  + " s (" + String(pct(t_emit))  + "%)");
      // Is the score stage doing arithmetic, or walking fragments the RT gate then discards?
      // One atomic add per precursor, so this costs nothing against a 10^11-iteration loop.
      const long long np = stat_prec_.load(), sl = stat_slice_.load(), rp = stat_rtpass_.load();
      if (np > 0)
        writeLogInfo_("  score gate: " + String(np) + " precursors visited " + String(sl)
                      + " fragments (" + String(sl / np) + "/precursor), "
                      + String(rp) + " passed the RT gate ("
                      + String(rp > 0 ? (double)sl / (double)rp : 0.0) + "x scanned per survivor)");
    }

    vector<MSSpectrum> all_out;
    {
      size_t n_tot = 0;
      for (const auto& bucket : win_out) n_tot += bucket.size();
      all_out.reserve(n_tot); // avoid repeated reallocation of ~1M spectrum objects
    }
    for (auto& bucket : win_out) { for (auto& s : bucket) all_out.push_back(std::move(s)); bucket.clear(); bucket.shrink_to_fit(); }

    // Canonical total-order sort (RT, precursor m/z, charge): thread-count-independent and free of
    // RT-tie ambiguity (RT-only sortSpectra is NOT canonical). [par-Crit-2]
    { Phase _ph("SORT(canonical)");
    // Sort a compact key array and permute once, rather than sorting the spectra themselves:
    // std::sort moves whatever it is given, and an MSSpectrum object is ~750 bytes against 32 for a
    // key. The comparator returns exactly what the old one returned for every pair -- the cheap
    // fields live in the key, the rare full tie defers to the peaks -- and the keys start in the
    // order the spectra were in, so introsort makes the same decisions and yields the same
    // permutation, ties included.
    struct SortKey { double rt, mz; int charge; uint32_t n, idx; };
    vector<SortKey> keys(all_out.size());
#pragma omp parallel for schedule(static)
    for (long i = 0; i < (long)all_out.size(); ++i)
    {
      const MSSpectrum& a = all_out[i];
      keys[i].rt = a.getRT();
      keys[i].mz = a.getPrecursors().empty() ? 0.0 : a.getPrecursors()[0].getMZ();
      keys[i].charge = a.getPrecursors().empty() ? 0 : a.getPrecursors()[0].getCharge();
      keys[i].n = (uint32_t)a.size();
      keys[i].idx = (uint32_t)i;
    }
    sort(keys.begin(), keys.end(), [&all_out](const SortKey& ka, const SortKey& kb) {
      if (ka.rt != kb.rt) return ka.rt < kb.rt;
      if (ka.mz != kb.mz) return ka.mz < kb.mz;
      if (ka.charge != kb.charge) return ka.charge < kb.charge;
      // fragment-sequence tiebreaks so equal-precursor spectra have a canonical order
      if (ka.n != kb.n) return ka.n < kb.n;
      const MSSpectrum& a = all_out[ka.idx];
      const MSSpectrum& b = all_out[kb.idx];
      for (Size i = 0; i < a.size(); ++i)
      {
        if (a[i].getMZ() != b[i].getMZ()) return a[i].getMZ() < b[i].getMZ();
        if (a[i].getIntensity() != b[i].getIntensity()) return a[i].getIntensity() < b[i].getIntensity();
      }
      return false;
    });
    { vector<MSSpectrum> ord; ord.reserve(all_out.size());
      for (const SortKey& k : keys) ord.push_back(std::move(all_out[k.idx]));
      all_out.swap(ord); } }

    PeakMap out_exp;
    { Phase _ph("ASSEMBLE(PeakMap)");
      out_exp.setSpectra(std::move(all_out)); }   // vector ownership transfer, not per-spectrum moves
    const Size n_out = out_exp.size();
    addDataProcessing_(out_exp, getProcessingInfo_(DataProcessing::DATA_PROCESSING));
    // [provenance] Record the emitted-intensity reweighting so an identical historical command line is
    // still reproducible after assembly:corr_power's default changed 0->2 (2026-07-28). Without this,
    // the same command produces different intensities across tool versions with no trace of why.
    // [provenance] WHICH m/z calibration produced this file. Without it an archived mzML is not
    // attributable to a calibration path and a silent fallback would be invisible afterwards.
    // The value travels ON THE LOADED EXPERIMENT (set by BrukerTimsFile), not through a header
    // static: an inline static can be duplicated across a shared-library boundary, in which case
    // the tool would read its own copy and always report "unset".
#ifdef SPEXTRACTOR_WITH_MZPEAK
    if (FileHandler::getTypeByFileName(in) == FileTypes::MZPEAK)
      out_exp.setMetaValue("spx:mz_calibration", spx::lastMzPeakCalibration());   // not BrukerTimsFile's state
    else
#endif
    out_exp.setMetaValue("spx:mz_calibration", BrukerTimsFile::lastMzCalibration());
    out_exp.setMetaValue("spx:detector", String(integer_detector ? "integer" : "openms"));
    out_exp.setMetaValue("spx:corr_power", corr_power_);
    out_exp.setMetaValue("spx:im_weight_sigma", im_weight_sigma_);
    out_exp.setMetaValue("spx:require_isotope_support",
                         (int)(getStringOption_("assembly:require_isotope_support") == "true"));
    // Output format. The extension is authoritative, because that is what a user typing
    // `-out pseudo.mzML` means; -out_type overrides it; mzPeak is the default when neither says.
    FileTypes::Type out_type = FileTypes::MZML;
    const String out_type_opt = getStringOption_("out_type");
#ifdef SPEXTRACTOR_WITH_MZPEAK
    if (!out_type_opt.empty())
      { String t = out_type_opt; t.toLower(); out_type = (t == "mzml") ? FileTypes::MZML : FileTypes::MZPEAK; }
    else
    {
      const FileTypes::Type by_name = FileHandler::getTypeByFileName(out);
      out_type = (by_name == FileTypes::MZML || by_name == FileTypes::MZPEAK) ? by_name
                                                                             : FileTypes::MZPEAK;
    }
    if (out_type == FileTypes::MZPEAK)
      writeLogInfo_("Writing mzPeak. NOTE: DDA search engines read mzML, not mzPeak -- if this file "
                    "is going straight into a search, write .mzML instead (or -out_type mzML).");
#else
    // Built without mzPeak support: mzML is the only container this binary can write. Refuse an
    // explicit request for mzPeak rather than silently writing something else.
    String out_type_lc = out_type_opt; out_type_lc.toLower();          // toLower() mutates
    if (!out_type_lc.empty() && out_type_lc != "mzml")
      throw OpenMS::Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
            "-out_type mzpeak needs a build with mzPeak support (-DMZPEAK_ROOT=...); this binary "
            "can only write mzML.");
#endif
    { Phase _ph(out_type == FileTypes::MZML ? "WRITE(mzML)" : "WRITE(mzPeak)");
      FileHandler().storeExperiment(out, out_exp, {out_type}, log_type_); }
    writeLogInfo_("Wrote " + String(n_out) + " pseudo-MS2 spectra to " + out
                  + " (" + String(FileTypes::typeToName(out_type)) + ")");
    report_phases_(phase_clock_());
    return EXECUTION_OK;
  }
};

/// @endcond

int main(int argc, const char** argv)
{
  // OpenMS builds with ENABLE_UPDATE_CHECK=ON by default, and TOPPBase then calls
  // UpdateCheck::run(tool_name_, version_) on every invocation -- a network request to an OpenMS
  // REST endpoint asking whether a newer OPENMS exists. For a tool shipped outside the OpenMS
  // release that answer is not actionable, and three things make it actively unwanted here:
  // it sends this tool's name and version to a third party the user never opted into; it fires on
  // every run of a benchmark chain; and when it fails -- an offline compute node, a proxy, a
  // sandbox -- Qt prints "QIODevice::read (QNetworkReplyHttpImpl): device not open" to STDERR,
  // which is the stream this project's own harness parses for timing and RSS.
  //
  // Set it only if unset, so a user who exports the variable still decides, in either direction.
#ifdef _WIN32
  size_t sz = 0;
  if (getenv_s(&sz, nullptr, 0, "OPENMS_DISABLE_UPDATE_CHECK") != 0 || sz == 0)
    _putenv_s("OPENMS_DISABLE_UPDATE_CHECK", "ON");
#else
  ::setenv("OPENMS_DISABLE_UPDATE_CHECK", "ON", 0);
#endif
  TOPPSpeXtractor tool;
  return tool.main(argc, argv);
}
