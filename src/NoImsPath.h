// The extraction path for DIA input without ion mobility (Orbitrap, SWATH mzML). Separate from the IMS path by rule:
// it shares loading and writing with it, nothing else, and never changes what the IMS path emits.
//
// Precursors: Biosaur2 features of the whole run's MS1, plus isotope envelopes (z >= 2) of unfragmented precursors in
// each window's MS2 traces that MS1 does not already have.
// Per isolation window: (1) the window's precursors; (2) fragments = mass traces of the window's MS2 scans; (3) a
// fragment joins a precursor when its profile correlates with the precursor's over the precursor's elution span
// (Pearson r >= min_corr on the window's scan grid), or, with fewer than 3 grid points in that span, when its apex lies
// within one cycle of the precursor apex. A fragment's intensity is weighted by r^24 (Sage and MSFragger peptides and
// entrapment on three Orbitrap sets: stronger powers overfit Sage's scoring); the 200 heaviest are kept, one spectrum
// per precursor with >= min_frags (3) fragments.
// Parallelism: windows run in parallel, heaviest first; each window's precursors are OpenMP tasks, so threads that have
// no window left help with the precursors of the last ones. Results are index-addressed: the output does not depend on
// the thread count.
#pragma once

#include <OpenMS/KERNEL/MSExperiment.h>
#include <OpenMS/KERNEL/MassTrace.h>
#include <OpenMS/FEATUREFINDER/MassTraceDetection.h>
#include <OpenMS/FEATUREFINDER/Biosaur2Algorithm.h>
#include <OpenMS/KERNEL/FeatureMap.h>
#include "PortableMath.h"
#include "OmsString.h"
#include <omp.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <exception>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <functional>
#include <map>
#include <numeric>
#include <tuple>
#include <vector>

namespace spx_noims
{
using diaspextract::String;
  using namespace OpenMS;

  struct Params
  {
    double ppm = 10.0;          ///< mass-trace and isotope m/z tolerance
    double min_corr = 0.3;      ///< fragment-precursor Pearson r on the window grid
    // MS1 precursor detection (Biosaur2): the Orbitrap defaults; TOF input changes them (see noImsSpectra_)
    bool tof = false;           ///< Biosaur2's TOF noise filter (per-50-m/z-bin intensity floor)
    double min_intensity = 1.0; ///< Biosaur2 mini: least peak intensity
    int min_hill_scans = 2;     ///< Biosaur2 minlh: fewest MS1 scans per hill
    int min_charge = 1;         ///< Biosaur2 cmin
    int min_frags = 3;          ///< fewest fragments a spectrum needs
    double min_frag_intensity = 0; ///< least apex intensity of a fragment trace
    int min_frag_points = 1;    ///< fewest scans of a fragment trace
    int max_frags = 200;        ///< most intense fragments kept per spectrum (by weighted intensity)
    double weight_pow = 24.0;   ///< fragment intensity x r^weight_pow
    double ms2_ppm = 0;         ///< MS2 mass-trace tolerance; 0 = ppm
    double split = 0;           ///< split MS2 traces at elution valleys below split x the lower flanking maximum; 0 = off
    bool env_all_charges = false; ///< MS2 envelopes: a -1 isotope at one charge moves on to the next lower charge (else: no precursor)
    bool drop_precursor = false;  ///< drop the precursor's own isotope peaks (mono-1 .. mono+3) from its spectrum
    double comp_boost = 0;      ///< weight x this for fragments with a complementary partner (m1 + m2 = M + 2 H+, both z = 1); 0 = off
    int frag_rank = 0;          ///< a fragment goes only to its this many best-correlated precursors of the window; 0 = all
    bool ms2_env = true;        ///< precursors from MS2 isotope envelopes
    int mono_corr = 0;          ///< MS2-envelope precursors move to the MS1 feature whose isotope peak they sit on: 0 off, 1 the precursor features, 2 features of a second Biosaur2 pass with 1-scan hills
    bool env_pattern = false;   ///< MS2 envelopes: +1/mono intensity must fit averagine within x3; the best-fitting charge wins
    int hill_seeds = 0;         ///< fragment-driven tier: MS1 hills outside every feature become z 2 and 3 precursors, kept with at least this many complementary fragment pairs; 0 = off
    bool tag_src = false;       ///< write userParam precursor_source (0 MS1 feature, 1 MS2 envelope, 2 corrected envelope, 3 MS1 hill with fragment pairs)
    int pair_top = 50;          ///< hill seeds: complementary pairs are counted among this many most intense peaks
    bool seed_mono = false;     ///< hill seeds: also hills that are a feature's monoisotopic peak
    double ms2_shift = 0;       ///< fragment m/z shift in ppm
    bool ms2_shift_auto = false; ///< estimate the shift from the y1 ions of tryptic peptides
    int span_pad = 0;           ///< widen the precursor's RT span by this many window scans on each side (correlation and apex gate); 0 = off
  };

  struct Stats { size_t windows = 0, ms2_traces = 0, precursors = 0, spectra = 0, peaks = 0; double busy_s = 0, wall_s = 0; int threads = 1; };

  namespace detail
  {
    constexpr double C13 = 1.0033548, PROTON = 1.007276;
    inline double ms2_scale = 1.0;   // fragment m/z recalibration factor, set once per run (DIASPX_MS2_SHIFT)
    constexpr double FEW_APEX_CYCLES = 1.0; ///< precursors with < 3 window scans: fragment apex within this many cycles of the precursor apex

    struct Prec { double mz, rt, rt_lo, rt_hi, inten; int z; std::vector<double> rt_pts, int_pts; int src = 0; };
    /// a fragment trace; `pts` are (RT, intensity), `gpts` the same points as (grid index, intensity)
    struct Frag { double mz, apex_rt, inten; std::vector<std::pair<double, double>> pts; std::vector<std::pair<size_t, double>> gpts; };

    inline double apexRT(const MassTrace& t)
    {
      double best = -1, rt = t.getCentroidRT();
      for (const auto& p : t) if (p.getIntensity() > best) { best = p.getIntensity(); rt = p.getRT(); }
      return rt;
    }

    inline std::vector<MassTrace> traces(const PeakMap& m, double ppm)
    {
      MassTraceDetection mtd;
      mtd.setLogType(ProgressLogger::NONE);   // windows run in parallel: progress lines would interleave
      Param p = mtd.getDefaults();
      p.setValue("mass_error_ppm", ppm);
      p.setValue("min_trace_length", 0.0);   // single points too: a fragment seen in one scan of a window
      mtd.setParameters(p);
      std::vector<MassTrace> mt;
      mtd.run(m, mt);
      return mt;
    }

    /// cut points (grid indices) of a trace's grid profile @p y (index g0 + k), at valleys of the 1-2-1 smoothed profile
    /// that fall below @p valley x both flanking maxima: one elution peak per segment
    inline std::vector<size_t> valleys(const std::vector<double>& y, size_t g0, double valley)
    {
      std::vector<size_t> cut;
      double M = 0, m = -1; size_t mi = 0;   // m < 0: still rising to the current maximum M
      for (size_t k = 0; k < y.size(); ++k)
      {
        const double v = 0.25 * ((k ? y[k - 1] : 0.0) + 2 * y[k] + (k + 1 < y.size() ? y[k + 1] : 0.0));
        if (m < 0) { if (v >= M) M = v; else { m = v; mi = k; } }
        else if (v < m) { m = v; mi = k; }
        else if (m < valley * M && m < valley * v) { cut.push_back(g0 + mi); M = v; m = -1; }
        else if (v > M) { M = v; m = -1; }
      }
      return cut;
    }

    /// Pearson r of two profiles sampled on the same grid
    inline double pearson(const std::vector<double>& a, const std::vector<double>& b)
    {
      const size_t n = a.size();
      double ma = 0, mb = 0;
      for (size_t i = 0; i < n; ++i) { ma += a[i]; mb += b[i]; }
      ma /= n; mb /= n;
      double sab = 0, saa = 0, sbb = 0;
      for (size_t i = 0; i < n; ++i) { sab += (a[i] - ma) * (b[i] - mb); saa += (a[i] - ma) * (a[i] - ma); sbb += (b[i] - mb) * (b[i] - mb); }
      return (saa > 0 && sbb > 0) ? sab / std::sqrt(saa * sbb) : 0.0;
    }

    /// linear interpolation of (x, y) at t, 0 outside
    inline double interp(const std::vector<double>& x, const std::vector<double>& y, double t)
    {
      if (x.empty() || t < x.front() || t > x.back()) return 0.0;
      const size_t j = std::upper_bound(x.begin(), x.end(), t) - x.begin();   // >= 1, since t >= x.front()
      if (j >= x.size()) return y.back();
      const double f = (t - x[j - 1]) / (x[j] - x[j - 1]);
      return y[j - 1] + f * (y[j] - y[j - 1]);
    }

    /// isotope envelopes (z = 2..4) from MS2 traces; a trace is a mono if it has a +1 isotope and no -1 isotope at the same charge
    // ponytail: greedy, highest charge first, no averagine check; add an intensity-pattern test if charge errors show up
    inline std::vector<Prec> envelopes(const std::vector<MassTrace>& mt, double ppm, double lo, double hi, double coelute, bool all_charges = false, bool pattern = false)
    {
      std::vector<size_t> o(mt.size());
      std::iota(o.begin(), o.end(), 0);
      std::sort(o.begin(), o.end(), [&](size_t a, size_t b) { return mt[a].getCentroidMZ() < mt[b].getCentroidMZ() || (mt[a].getCentroidMZ() == mt[b].getCentroidMZ() && a < b); });
      std::vector<double> mz(o.size()), art(o.size());
      for (size_t k = 0; k < o.size(); ++k) { mz[k] = mt[o[k]].getCentroidMZ(); art[k] = apexRT(mt[o[k]]); }
      auto partner = [&](size_t k, double target) -> long {   // co-eluting trace at target m/z
        const double tol = target * ppm * 1e-6;
        const MassTrace& a = mt[o[k]];
        const double half = std::max(a.getFWHM() * 0.5, coelute);   // isotopes share scans: one scan of apex jitter
        long best = -1; double bi = -1;
        for (auto it = std::lower_bound(mz.begin(), mz.end(), target - tol); it != mz.end() && *it <= target + tol; ++it)
        {
          const size_t j = it - mz.begin();
          if (std::fabs(art[j] - art[k]) > half) continue;
          const double in = mt[o[j]].getMaxIntensity(false);
          if (in > bi) { bi = in; best = (long)j; }
        }
        return best;
      };
      std::vector<Prec> out;
      auto emit = [&](size_t k, int z) {
        const MassTrace& t = mt[o[k]];
        Prec p{mz[k], art[k], t.begin()->getRT(), t.rbegin()->getRT(), t.getMaxIntensity(false), z, {}, {}, 1};
        for (const auto& pk : t) { p.rt_pts.push_back(pk.getRT()); p.int_pts.push_back(pk.getIntensity()); }
        out.push_back(std::move(p));
      };
      auto in = [&](long j) { return (double)mt[o[j]].getMaxIntensity(false); };
      for (size_t k = 0; pattern && k < o.size(); ++k)
      {
        if (!(mz[k] >= lo && mz[k] < hi)) continue;
        // ponytail: averagine as one number, I(+1)/I(mono) = 5.3e-4 x mass, within x3; fit the +2 peak too if charges stay wrong
        const double LN3 = 1.0986;
        int bz = 0; double bs = LN3;
        for (int z = 4; z >= 2; --z)
        {
          const long p1 = partner(k, mz[k] + C13 / z);
          if (p1 < 0) continue;
          const double ex = 5.3e-4 * z * (mz[k] - PROTON);
          const long m1 = partner(k, mz[k] - C13 / z);
          if (m1 >= 0 && std::fabs(std::log(in(k) / in(m1) / ex)) < LN3) continue;   // this trace is the +1 isotope at z
          const double sc = std::fabs(std::log(in(p1) / in(k) / ex));
          if (sc < bs) { bs = sc; bz = z; }
        }
        if (bz) emit(k, bz);
      }
      for (size_t k = 0; !pattern && k < o.size(); ++k)
      {
        for (int z = 4; z >= 2; --z)
        {
          if (partner(k, mz[k] + C13 / z) < 0) continue;
          if (partner(k, mz[k] - C13 / z) >= 0) { if (all_charges) continue; break; }   // not the lightest isotope at this charge
          if (mz[k] >= lo && mz[k] < hi) emit(k, z);
          break;
        }
      }
      return out;
    }

    /// precursors from OpenMS's Biosaur2 port, run once on the whole run's MS1 (averagine-checked isotope patterns)
    inline std::vector<Prec> biosaur(PeakMap&& ms1, const Params& P, double mzlo, double mzhi, std::vector<Prec>* seeds = nullptr)
    {
      std::vector<Biosaur2Algorithm::Hill> hills;
      std::vector<Biosaur2Algorithm::PeptideFeature> feats;
      {
        Biosaur2Algorithm b;
        Param p = b.getDefaults();
        p.setValue("htol", P.ppm); p.setValue("itol", P.ppm);
        p.setValue("minmz", mzlo); p.setValue("maxmz", mzhi);
        p.setValue("cmin", P.min_charge); p.setValue("cmax", 4);
        p.setValue("mini", P.min_intensity); p.setValue("minlh", P.min_hill_scans);
        p.setValue("tof", P.tof ? "true" : "false");
        // no per-peak ion mobility on this path: a FAIMS run's per-spectrum CV made Biosaur2 switch on its PASEF
        // centroiding and IM gating, both no-ops without an IM array but logged as if they ran
        p.setValue("paseftol", 0.0);
        b.setParameters(p);
        b.setMSData(std::move(ms1));
        FeatureMap fm;   // unused; freed with the algorithm's copy of the MS1 data
        b.run(fm, hills, feats);
      }
      if (const char* hp = std::getenv("DIASPX_HILLS"))   // DEBUG (experimental): every hill (H) and feature (F)
      {
        std::ofstream of(hp); of.precision(8);
        for (const auto& h : hills) of << "H\t" << h.mz_weighted_mean << '\t' << h.rt_start << '\t' << h.rt_end << '\t' << h.rt_apex << '\t' << h.length << '\t' << h.intensity_apex << '\n';
        for (const auto& f : feats) of << "F\t" << f.mz << '\t' << f.charge << '\t' << f.rt_start << '\t' << f.rt_end << '\t' << f.rt_apex << '\t' << f.n_isotopes << '\t' << f.n_scans << '\t' << f.intensity_apex << '\n';
      }
      if (seeds)   // every hill, charge open; run() drops those a feature explains
      {
        for (const auto& h : hills) seeds->push_back(Prec{h.mz_weighted_mean, h.rt_apex, h.rt_start, h.rt_end, h.intensity_apex, 0, h.rt_values, h.intensities, 3});
        std::sort(seeds->begin(), seeds->end(), [](const Prec& a, const Prec& b) {
          return std::tie(a.mz, a.rt, a.inten, a.rt_lo, a.rt_hi, a.rt_pts, a.int_pts) < std::tie(b.mz, b.rt, b.inten, b.rt_lo, b.rt_hi, b.rt_pts, b.int_pts); });
      }
      Size top = 0;
      for (const auto& h : hills) top = std::max(top, h.hill_idx);
      std::vector<size_t> at(hills.empty() ? 0 : top + 1, SIZE_MAX);   // hill_idx -> position in hills (last one wins, as a map would)
      for (size_t i = 0; i < hills.size(); ++i) at[hills[i].hill_idx] = i;
      std::vector<Prec> out;
      out.reserve(feats.size());
      for (const auto& f : feats)
      {
        if (f.mono_hill_idx >= at.size() || at[f.mono_hill_idx] == SIZE_MAX) continue;
        const auto& h = hills[at[f.mono_hill_idx]];
        out.push_back(Prec{f.mz, f.rt_apex, h.rt_start, h.rt_end, f.intensity_apex, f.charge, h.rt_values, h.intensities});
      }
      std::sort(out.begin(), out.end(), [](const Prec& a, const Prec& b) {   // a total order: Biosaur2's feature order is fixed, its ties are not
        return std::tie(a.mz, a.rt, a.z, a.inten, a.rt_lo, a.rt_hi, a.rt_pts, a.int_pts) < std::tie(b.mz, b.rt, b.z, b.inten, b.rt_lo, b.rt_hi, b.rt_pts, b.int_pts); });
      return out;
    }

    /// singly charged fragment pairs among the @p top most intense peaks of @p s that sum to the precursor (b + y = M + 2 H+)
    inline int complementPairs(const MSSpectrum& s, double neutral, double ppm, size_t top = 50)
    {
      std::vector<std::pair<double, double>> v;   // (intensity, m/z)
      for (const auto& x : s) v.emplace_back(x.getIntensity(), x.getMZ());
      // ponytail: a plain count among the top peaks; score by intensity if the count alone is too coarse
      if (v.size() > top) { std::nth_element(v.begin(), v.begin() + top, v.end(), std::greater<>()); v.resize(top); }
      std::vector<double> m;
      for (const auto& x : v) m.push_back(x.second);
      std::sort(m.begin(), m.end());
      const double sum = neutral + 2 * PROTON, tol = sum * ppm * 1e-6;
      int n = 0;
      for (long i = 0, j = (long)m.size() - 1; i < j;)
      {
        const double d = m[i] + m[j] - sum;
        if (d < -tol) ++i; else if (d > tol) --j; else { ++n; ++i; --j; }
      }
      return n;
    }

    /// the spectrum of precursor @p p from the window's fragments (sorted by apex RT), or an empty one (no MS level)
    inline MSSpectrum assemble(const Prec& p, const std::vector<Frag>& fr, const std::vector<double>& grid, double cycle,
                               const Params& P, double lo, double hi,
                               std::vector<std::pair<uint32_t, float>>* cand = nullptr, const std::vector<float>* rmin = nullptr,
                               std::vector<std::pair<double, double>>* raw = nullptr)
    {
      // frag_rank: with @p cand the call only records (fragment, r) of the correlated fragments; with @p rmin it
      // skips fragments whose r is below their rank threshold. ponytail: r is computed twice, cache it if this stays
      MSSpectrum s;
      size_t g0 = std::lower_bound(grid.begin(), grid.end(), p.rt_lo) - grid.begin();
      size_t g1 = std::upper_bound(grid.begin(), grid.end(), p.rt_hi) - grid.begin();
      g0 -= std::min(g0, (size_t)P.span_pad); g1 = std::min(grid.size(), g1 + P.span_pad);   // the precursor is 0 outside its hill
      std::vector<double> pp;
      for (size_t g = g0; g < g1; ++g) pp.push_back(interp(p.rt_pts, p.int_pts, grid[g]));
      const bool few = pp.size() < 3;
      const double neutral = p.z * (p.mz - PROTON);
      std::vector<std::pair<double, double>> pk;   // (intensity, m/z)
      std::vector<double> fp(pp.size());
      // split traces (TOF) are short against the precursor span: their r comes from their own points (one-pass sums).
      // ponytail: unsplit traces keep the two-pass dense form, so Orbitrap output stays bit-identical
      const bool sparse = P.split > 0;
      double sa = 0, saa = 0;
      for (double a : pp) { sa += a; saa += a * a; }
      const double nn = (double)pp.size(), va = nn * saa - sa * sa;
      const bool pad = P.span_pad > 0 && !few;
      const double a0 = few ? p.rt - FEW_APEX_CYCLES * cycle : pad ? grid[g0] : p.rt_lo, a1 = few ? p.rt + FEW_APEX_CYCLES * cycle : pad ? grid[g1 - 1] : p.rt_hi;
      // raw: the weighted fragments depend on the charge only through the mass limit (drop_precursor off), so a
      // second charge of the same precursor filters the list of the higher charge instead of correlating again
      if (raw && !raw->empty()) { for (const auto& q : *raw) if (q.second - PROTON <= neutral - 56.0) pk.push_back(q); }
      else {
      const auto first = std::lower_bound(fr.begin(), fr.end(), a0, [](const Frag& f, double t) { return f.apex_rt < t; });
      for (size_t k = first - fr.begin(); k < fr.size() && fr[k].apex_rt <= a1; ++k)
      {
        const Frag& f = fr[k];
        if (f.mz - PROTON > neutral - 56.0) continue;   // heavier than the precursor allows at z = 1
        if (P.drop_precursor)
        {
          const double iso = std::round((f.mz - p.mz) * p.z / C13);
          if (iso >= -1 && iso <= 3 && std::fabs(f.mz - p.mz - iso * C13 / p.z) <= f.mz * P.ppm * 1e-6) continue;   // unfragmented precursor
        }
        if (!few)
        {
          double r;
          if (sparse)
          {
            double sb = 0, sbb = 0, sab = 0;
            for (auto it = std::lower_bound(f.gpts.begin(), f.gpts.end(), std::make_pair(g0, -1.0)); it != f.gpts.end() && it->first < g1; ++it)
            { sb += it->second; sbb += it->second * it->second; sab += pp[it->first - g0] * it->second; }
            const double vb = nn * sbb - sb * sb;
            r = (va > 0 && vb > 0) ? (nn * sab - sa * sb) / std::sqrt(va * vb) : 0.0;
          }
          else
          {
            std::fill(fp.begin(), fp.end(), 0.0);
            for (const auto& q : f.gpts) if (q.first >= g0 && q.first < g1) fp[q.first - g0] = q.second;
            r = pearson(pp, fp);
          }
          if (r < P.min_corr) continue;
          if (cand) { cand->emplace_back((uint32_t)k, (float)r); continue; }
          if (rmin && (float)r < (*rmin)[k]) continue;
          pk.emplace_back(f.inten * pmath::pow(r, P.weight_pow), f.mz);
          continue;
        }
        const double d = (f.apex_rt - p.rt) / cycle;
        pk.emplace_back(f.inten * pmath::exp(-d * d * P.weight_pow / 4.0), f.mz);
      }
      if (raw) *raw = pk;
      }
      if (cand || (int)pk.size() < P.min_frags) return s;
      if (P.comp_boost > 0)
      {
        std::sort(pk.begin(), pk.end(), [](const auto& a, const auto& b) { return a.second < b.second; });
        const double target = neutral + 2 * PROTON, tol = target * 2 * P.ppm * 1e-6;
        std::vector<char> hit(pk.size(), 0);
        for (size_t i = 0, j = pk.size(); i < pk.size(); ++i)   // j: first peak too heavy to pair with i
        {
          while (j > 0 && pk[i].second + pk[j - 1].second > target + tol) --j;
          for (size_t q = j; q-- > 0 && pk[i].second + pk[q].second >= target - tol;) if (q != i) hit[i] = hit[q] = 1;   // a peak is not its own complement
        }
        for (size_t i = 0; i < pk.size(); ++i) if (hit[i]) pk[i].first *= P.comp_boost;
      }
      if ((int)pk.size() > P.max_frags)
      { std::nth_element(pk.begin(), pk.begin() + P.max_frags, pk.end(), std::greater<>()); pk.resize(P.max_frags); }
      // by m/z, equal m/z by intensity: nth_element leaves the kept peaks in an unspecified order
      std::sort(pk.begin(), pk.end(), [](const auto& a, const auto& b) { return std::tie(a.second, a.first) < std::tie(b.second, b.first); });
      s.setMSLevel(2);
      s.setType(SpectrumSettings::SpectrumType::CENTROID);
      s.setRT(p.rt);
      Precursor pr;
      pr.setMZ(p.mz); pr.setCharge(p.z); pr.setIntensity(p.inten);
      pr.setIsolationWindowLowerOffset(p.mz - lo); pr.setIsolationWindowUpperOffset(hi - p.mz);
      s.setPrecursors({pr});
      if (P.tag_src) s.setMetaValue("precursor_source", p.src);
      s.reserve(pk.size());
      for (const auto& q : pk) { Peak1D x; x.setMZ(q.second * ms2_scale); x.setIntensity(q.first); s.push_back(x); }
      return s;
    }
  }

  /// @p exp: the resident run without ion mobility (MS1 and MS2 centroided, one isolation window per MS2 scan, in RT
  /// order). Its spectra are moved out: @p exp is left empty. Fills @p out with one MS2 spectrum per precursor.
  inline Stats run(PeakMap& exp, const Params& P, PeakMap& out, const std::function<void(const String&)>& log)
  {
    using namespace detail;
    using clk = std::chrono::steady_clock;
    const auto t0 = clk::now();
    Stats st;
    st.threads = omp_get_max_threads();

    // windows from the MS2 isolation windows; MS1 scans indexed once
    std::map<std::pair<double, double>, std::vector<size_t>> win;   // (lo, hi) -> MS2 scan indices
    std::vector<size_t> ms1;
    for (size_t i = 0; i < exp.size(); ++i)
    {
      const MSSpectrum& s = exp[i];
      if (s.getMSLevel() == 1) ms1.push_back(i);
      else if (s.getMSLevel() == 2 && !s.getPrecursors().empty())
      {
        const Precursor& pr = s.getPrecursors()[0];
        const double lo = std::round((pr.getMZ() - pr.getIsolationWindowLowerOffset()) * 100) / 100;
        const double hi = std::round((pr.getMZ() + pr.getIsolationWindowUpperOffset()) * 100) / 100;
        win[{lo, hi}].push_back(i);
      }
    }
    std::vector<std::pair<double, double>> keys;
    std::vector<std::vector<size_t>> scans;
    for (auto& kv : win) { keys.push_back(kv.first); scans.push_back(std::move(kv.second)); }
    win.clear();
    const size_t W = keys.size();
    st.windows = W;
    if (W == 0 || ms1.empty()) { log("[noims] no MS1 scans or no MS2 isolation windows"); exp.clear(true); return st; }
    // a precursor belongs to the window containing it whose center is nearest (windows may overlap); a window with
    // fewer than 3 MS2 scans gives no spectra and so owns nothing
    auto owner = [&](double mz) {
      long best = -1; double bd = 1e9;
      for (size_t w = 0; w < W; ++w)
        if (mz >= keys[w].first && mz < keys[w].second && scans[w].size() >= 3)
        { const double d = std::fabs(mz - 0.5 * (keys[w].first + keys[w].second)); if (d < bd) { bd = d; best = (long)w; } }
      return best;
    };
    // median spacing of these scans (fallback when fewer than two)
    auto spacing = [&](const std::vector<size_t>& v, double fallback) {
      std::vector<double> d;
      for (size_t k = 1; k < v.size(); ++k) d.push_back(exp[v[k]].getRT() - exp[v[k - 1]].getRT());
      if (d.empty()) return fallback;
      std::nth_element(d.begin(), d.begin() + d.size() / 2, d.end());
      return d[d.size() / 2];
    };
    // MS2 cycle: the scans of the first window with >= 3 of them (a short window would give a wrong cycle to all others)
    const auto cyc_win = std::find_if(scans.begin(), scans.end(), [](const auto& v) { return v.size() >= 3; });
    const double cycle = spacing(cyc_win != scans.end() ? *cyc_win : scans.front(), 1.0);
    log("[noims] " + String(W) + " isolation windows, " + String(ms1.size()) + " MS1 scans every " + String(spacing(ms1, cycle))
        + " s, MS2 cycle " + String(cycle) + " s");

    // the run's spectra move into Biosaur2's MS1 map and the windows' MS2 maps (MassTraceDetection reads MS1 only)
    std::vector<PeakMap> m2(W);
    std::vector<std::vector<double>> grid(W);
    std::vector<size_t> wpeaks(W, 0);
    for (size_t w = 0; w < W; ++w)
      for (size_t i : scans[w])
      {
        grid[w].push_back(exp[i].getRT());
        wpeaks[w] += exp[i].size();
        exp[i].setMSLevel(1);
        m2[w].addSpectrum(std::move(exp[i]));
      }
    PeakMap m1;
    for (size_t i : ms1) m1.addSpectrum(std::move(exp[i]));
    exp.clear(true);

    // fragment m/z shift (P.ms2_shift ppm); auto estimates the run's offset from the y1 ions of tryptic peptides
    // (K 147.11280, R 175.11895) in the raw MS2 scans.
    // ponytail: the 1.7 ppm margin was tuned on one TripleTOF run; fit it per instrument if other TOFs disagree
    ms2_scale = 1.0;
    if (P.ms2_shift_auto || P.ms2_shift != 0)
    {
      double shift = P.ms2_shift;
      if (P.ms2_shift_auto)
      {
        std::vector<double> d, core;
        for (const auto& m : m2) for (const auto& sp : m) for (double a : {147.11280, 175.11895})
          for (auto it = sp.MZBegin(a * (1 - 15e-6)); it != sp.end() && it->getMZ() <= a * (1 + 15e-6); ++it) d.push_back((it->getMZ() - a) / a * 1e6);
        const auto median = [](std::vector<double>& v) { std::nth_element(v.begin(), v.begin() + v.size() / 2, v.end()); return v[v.size() / 2]; };
        const double m0 = d.size() < 1000 ? 0 : median(d);
        for (double x : d) if (std::fabs(x - m0) < 6) core.push_back(x);   // second pass: without the flat random background
        const double off = d.size() < 1000 ? 0 : median(core);
        shift = d.size() < 1000 ? 0 : -(off + 1.7);
        log("[noims] fragment m/z offset from y1 ions: " + String(off) + " ppm (n=" + String(d.size()) + "), shift " + String(shift) + " ppm");
      }
      ms2_scale = 1.0 + shift * 1e-6;
    }

    // DEBUG (experimental, not for release): DIASPX_DUMP=<dir> reads <dir>/queries.tsv ("mz z rt frag_mz...") and writes
    // <dir>/dump.tsv: every precursor (P), raw MS2 signal of the query fragments (R), their fate per matching precursor (F)
    struct Q { size_t id; double mz, rt; int z; std::vector<double> fr; std::vector<std::pair<int, double>> raw; };
    std::vector<std::vector<Q>> qs(W);
    std::vector<std::ostringstream> dbg(W);
    const char* dump = std::getenv("DIASPX_DUMP");
    if (dump)
    {
      std::ifstream in(std::string(dump) + "/queries.tsv");
      std::string line; size_t id = 0;
      while (std::getline(in, line))
      {
        std::istringstream ls(line); Q q; q.id = id++; ls >> q.mz >> q.z >> q.rt;
        for (double f; ls >> f;) q.fr.push_back(f);
        std::sort(q.fr.begin(), q.fr.end());
        const long w = owner(q.mz);
        if (w >= 0) qs[w].push_back(std::move(q));
      }
    }

    double top = 0;
    for (const auto& k : keys) top = std::max(top, k.second);
    const auto tb = clk::now();
    std::vector<Prec> bio2;   // mono_corr 2: features with 1-scan hills, for correction only
    if (P.mono_corr == 2) { Params R = P; R.min_hill_scans = 1; PeakMap c = m1; bio2 = biosaur(std::move(c), R, keys.front().first - 1.0, top + 1.0); }
    std::vector<Prec> seeds;
    const std::vector<Prec> bio = biosaur(std::move(m1), P, keys.front().first - 1.0, top + 1.0, P.hill_seeds > 0 ? &seeds : nullptr);
    const std::vector<Prec>& ref = P.mono_corr == 2 ? bio2 : bio;
    log("[noims] Biosaur2: " + String(bio.size()) + " isotope-pattern features as precursors in "
        + String(std::chrono::duration<double>(clk::now() - tb).count()) + " s");

    std::vector<size_t> order(W);   // heaviest window first, so the largest ones do not start last
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) { return wpeaks[a] > wpeaks[b]; });
    std::vector<std::vector<MSSpectrum>> res(W);
    std::vector<size_t> nprec(W, 0), ntr2(W, 0);
    std::vector<double> busy(W, 0.0), t_mtd(W, 0.0), t_frag(W, 0.0);
    std::vector<size_t> nfrag(W, 0);
    std::exception_ptr err;
    #pragma omp parallel for schedule(dynamic, 1)
    for (long o = 0; o < (long)W; ++o)
    try
    {
      const size_t w = order[o];
      if (scans[w].size() < 3) continue;   // MassTraceDetection needs 3 scans
      const auto tw = clk::now();
      const double lo = keys[w].first, hi = keys[w].second;
      std::vector<Prec> prec;
      for (auto it = std::lower_bound(bio.begin(), bio.end(), lo, [](const Prec& p, double m) { return p.mz < m; });
           it != bio.end() && it->mz < hi; ++it)
        if (owner(it->mz) == (long)w) prec.push_back(*it);

      // MS2 traces on the window's scan grid
      const std::vector<MassTrace> ft = traces(m2[w], P.ms2_ppm > 0 ? P.ms2_ppm : P.ppm);
      ntr2[w] = ft.size();
      t_mtd[w] = std::chrono::duration<double>(clk::now() - tw).count();
      for (Q& q : qs[w])
        for (double f : q.fr)
        {
          int n = 0; double mx = 0;
          for (const auto& sp : m2[w])
          {
            if (std::fabs(sp.getRT() - q.rt) > 30.0) continue;
            const Int j = sp.findNearest(f, f * 20e-6);
            if (j >= 0) { ++n; mx = std::max(mx, (double)sp[j].getIntensity()); }
          }
          q.raw.emplace_back(n, mx);
        }
      m2[w].clear(true);
      // unfragmented precursors seen in MS2, unless MS1 already has them (same z, 1 cycle, ppm)
      std::vector<Prec> q = P.ms2_env ? envelopes(ft, P.ppm, lo, hi, 1.01 * cycle, P.env_all_charges, P.env_pattern) : std::vector<Prec>();
      const size_t n1 = prec.size();
      for (auto& c : q)
      {
        if (P.mono_corr)
        {
          // the MS1 feature that has this trace as isotope peak k = 0..3 while it elutes; the same m/z and charge confirms, else the most intense
          const Prec* best = nullptr; bool same = false;
          for (int fz = 2; fz <= 4 && !same; ++fz)
            for (int k = 0; k <= 3 && !same; ++k)
            {
              const double t = c.mz - k * C13 / fz, tol = t * P.ppm * 1e-6;
              for (auto it = std::lower_bound(ref.begin(), ref.end(), t - tol, [](const Prec& p, double m) { return p.mz < m; });
                   it != ref.end() && it->mz <= t + tol; ++it)
              {
                if (it->z != fz || c.rt < it->rt_lo - cycle || c.rt > it->rt_hi + cycle) continue;
                if (k == 0 && fz == c.z) { same = true; break; }
                if (!best || it->inten > best->inten) best = &*it;
              }
            }
          if (!same && best) { c.mz = best->mz; c.z = best->z; c.src = 2; }
        }
        if (owner(c.mz) != (long)w) continue;
        bool dup = false;
        for (size_t i = 0, n = c.src == 2 ? prec.size() : n1; i < n && !dup; ++i)
          dup = prec[i].z == c.z && std::fabs(prec[i].mz - c.mz) <= c.mz * P.ppm * 1e-6 && std::fabs(prec[i].rt - c.rt) <= cycle;
        if (!dup) prec.push_back(std::move(c));
      }
      nprec[w] = prec.size();
      const std::vector<double>& gr = grid[w];
      std::vector<Frag> fr;
      fr.reserve(ft.size());
      std::vector<double> prof;
      for (const auto& t : ft)
      {
        if (t.getMaxIntensity(false) < P.min_frag_intensity || (int)t.getSize() < P.min_frag_points) continue;
        Frag f{t.getCentroidMZ(), apexRT(t), t.getMaxIntensity(false), {}, {}};
        for (const auto& pk : t)
        {
          f.pts.emplace_back(pk.getRT(), pk.getIntensity());
          f.gpts.emplace_back(std::lower_bound(gr.begin(), gr.end(), pk.getRT() - 1e-6) - gr.begin(), pk.getIntensity());
        }
        std::vector<size_t> cut;
        if (P.split > 0 && f.gpts.size() >= 3)
        {
          const size_t g0 = f.gpts.front().first;
          prof.assign(f.gpts.back().first - g0 + 1, 0.0);
          for (const auto& q : f.gpts) prof[q.first - g0] = q.second;
          cut = valleys(prof, g0, P.split);
        }
        if (cut.empty()) { fr.push_back(std::move(f)); continue; }
        // one fragment per elution peak: its own apex, intensity and intensity-weighted m/z
        cut.push_back(SIZE_MAX);
        size_t k = 0;
        for (size_t c : cut)
        {
          Frag g{0, 0, -1, {}, {}};
          double sw = 0;
          for (auto it = t.begin() + k; k < f.gpts.size() && f.gpts[k].first < c; ++k, ++it)
          {
            g.pts.push_back(f.pts[k]); g.gpts.push_back(f.gpts[k]);
            g.mz += it->getMZ() * it->getIntensity(); sw += it->getIntensity();
            if (it->getIntensity() > g.inten) { g.inten = it->getIntensity(); g.apex_rt = it->getRT(); }
          }
          if (g.gpts.empty()) continue;
          g.mz = sw > 0 ? g.mz / sw : t.getCentroidMZ();
          if (g.inten >= P.min_frag_intensity && (int)g.gpts.size() >= P.min_frag_points) fr.push_back(std::move(g));
        }
      }
      std::sort(fr.begin(), fr.end(), [](const Frag& a, const Frag& b) { return std::tie(a.apex_rt, a.mz, a.inten, a.pts) < std::tie(b.apex_rt, b.mz, b.inten, b.pts); });
      for (auto& f : fr) std::vector<std::pair<double, double>>().swap(f.pts);   // pts only break sort ties; gpts serve the rest
      nfrag[w] = fr.size();
      t_frag[w] = std::chrono::duration<double>(clk::now() - tw).count() - t_mtd[w];

      // one slot per precursor, filled by tasks that idle threads can take
      std::vector<MSSpectrum> slot(prec.size());
      std::exception_ptr terr;
      const long np = (long)prec.size();
      std::vector<float> rmin;
      if (P.frag_rank > 0)
      {
        std::vector<std::vector<std::pair<uint32_t, float>>> cand(prec.size());
        #pragma omp taskloop grainsize(256) default(shared)
        for (long i = 0; i < np; ++i)
        {
          try { assemble(prec[i], fr, gr, cycle, P, lo, hi, &cand[i]); }
          catch (...)
          {
            #pragma omp critical(noims_err)
            if (!terr) terr = std::current_exception();
          }
        }
        if (terr) std::rethrow_exception(terr);
        std::vector<std::vector<float>> rs(fr.size());
        for (const auto& c : cand) for (const auto& q : c) rs[q.first].push_back(q.second);
        rmin.assign(fr.size(), 0.0f);
        for (size_t k = 0; k < fr.size(); ++k) if ((int)rs[k].size() > P.frag_rank)
        { std::nth_element(rs[k].begin(), rs[k].begin() + P.frag_rank - 1, rs[k].end(), std::greater<>()); rmin[k] = rs[k][P.frag_rank - 1]; }
      }
      const std::vector<float>* rm = P.frag_rank > 0 ? &rmin : nullptr;
      #pragma omp taskloop grainsize(256) default(shared)
      for (long i = 0; i < np; ++i)
      {
        try { slot[i] = assemble(prec[i], fr, gr, cycle, P, lo, hi, nullptr, rm); }
        catch (...)
        {
          #pragma omp critical(noims_err)
          if (!terr) terr = std::current_exception();
        }
      }
      if (terr) std::rethrow_exception(terr);
      if (dump)
      {
        std::ostringstream& o = dbg[w];
        o.precision(10);
        auto corr = [&](const Prec& p, const Frag& f, int& npts) {   // the sparse r of assemble()
          const size_t g0 = std::lower_bound(gr.begin(), gr.end(), p.rt_lo) - gr.begin();
          const size_t g1 = std::upper_bound(gr.begin(), gr.end(), p.rt_hi) - gr.begin();
          double sa = 0, saa = 0, sb = 0, sbb = 0, sab = 0; const double nn = g1 > g0 ? double(g1 - g0) : 0.0;
          for (size_t g = g0; g < g1; ++g) { const double a = interp(p.rt_pts, p.int_pts, gr[g]); sa += a; saa += a * a; }
          npts = 0;
          for (const auto& x : f.gpts) if (x.first >= g0 && x.first < g1)
          { const double a = interp(p.rt_pts, p.int_pts, gr[x.first]); sb += x.second; sbb += x.second * x.second; sab += a * x.second; ++npts; }
          const double va = nn * saa - sa * sa, vb = nn * sbb - sb * sb;
          return (va > 0 && vb > 0) ? (nn * sab - sa * sb) / std::sqrt(va * vb) : 0.0;
        };
        for (size_t i = 0; i < prec.size(); ++i)
        {
          const Prec& p = prec[i];
          double mn = 0;
          for (const auto& x : slot[i]) mn = (mn == 0 || x.getIntensity() < mn) ? x.getIntensity() : mn;
          const size_t g0 = std::lower_bound(gr.begin(), gr.end(), p.rt_lo) - gr.begin(), g1 = std::upper_bound(gr.begin(), gr.end(), p.rt_hi) - gr.begin();
          o << "P\t" << w << '\t' << i << '\t' << p.mz << '\t' << p.z << '\t' << p.rt << '\t' << p.rt_lo << '\t' << p.rt_hi << '\t' << p.inten
            << '\t' << (i < n1 ? 1 : 2) << '\t' << p.rt_pts.size() << '\t' << (g1 > g0 ? g1 - g0 : 0) << '\t' << slot[i].size() << '\t' << mn << '\n';
        }
        for (const Q& q : qs[w])
        {
          for (size_t j = 0; j < q.fr.size(); ++j) o << "R\t" << q.id << '\t' << q.fr[j] << '\t' << q.raw[j].first << '\t' << q.raw[j].second << '\n';
          for (size_t i = 0; i < prec.size(); ++i)
          {
            const Prec& p = prec[i];
            if (p.z != q.z || std::fabs(p.rt - q.rt) > 30.0) continue;
            const double k = std::round((p.mz - q.mz) * q.z / C13);
            if (std::fabs(k) > 3 || std::fabs(p.mz - q.mz - k * C13 / q.z) > q.mz * 20e-6) continue;
            o << "M\t" << q.id << '\t' << w << '\t' << i << '\t' << k << '\n';
            const bool few = (std::upper_bound(gr.begin(), gr.end(), p.rt_hi) - std::lower_bound(gr.begin(), gr.end(), p.rt_lo)) < 3;
            const double a0 = few ? p.rt - cycle : p.rt_lo, a1 = few ? p.rt + cycle : p.rt_hi;
            for (auto it = std::lower_bound(fr.begin(), fr.end(), p.rt - 60.0, [](const Frag& f, double t) { return f.apex_rt < t; });
                 it != fr.end() && it->apex_rt <= p.rt + 60.0; ++it)
            {
              auto m = std::lower_bound(q.fr.begin(), q.fr.end(), it->mz * (1 - 20e-6));
              if (m == q.fr.end() || *m > it->mz * (1 + 20e-6)) continue;
              int npts = 0;
              const double r = corr(p, *it, npts);
              const bool kept = slot[i].getMSLevel() == 2 && slot[i].findNearest(it->mz, 1e-9) >= 0;
              o << "F\t" << q.id << '\t' << w << '\t' << i << '\t' << *m << '\t' << it->mz << '\t' << it->apex_rt - p.rt << '\t'
                << (it->apex_rt >= a0 && it->apex_rt <= a1) << '\t' << it->gpts.size() << '\t' << npts << '\t' << r << '\t' << it->inten << '\t' << kept << '\n';
            }
          }
        }
      }
      for (auto& s : slot) if (s.getMSLevel() == 2) res[w].push_back(std::move(s));
      if (P.hill_seeds > 0)
      {
        // fragment-driven tier, after and apart from the spectra above: hills that are no isotope peak (k = 0..5) of a
        // feature, tried as z 2 and 3; the charge with more complementary pairs is kept if it has enough of them
        std::vector<Prec> sd;   // per seed: z 2, then z 3
        const bool seed_mono = P.seed_mono, share = !P.drop_precursor;
        for (auto it = std::lower_bound(seeds.begin(), seeds.end(), lo, [](const Prec& p, double m) { return p.mz < m; });
             it != seeds.end() && it->mz < hi; ++it)
        {
          if (owner(it->mz) != (long)w) continue;
          bool used = false;
          for (int fz = 1; fz <= 4 && !used; ++fz)
            for (int k = 0; k <= 5 && !used; ++k)
            {
              const double t = it->mz - k * C13 / fz, tol = t * P.ppm * 1e-6;
              for (auto b = std::lower_bound(bio.begin(), bio.end(), t - tol, [](const Prec& p, double m) { return p.mz < m; });
                   b != bio.end() && b->mz <= t + tol && !used; ++b)
                used = b->z == fz && it->rt_lo <= b->rt_hi && b->rt_lo <= it->rt_hi;
            }
          if (used) continue;
          for (int z = 2; z <= 3; ++z)
          {
            sd.push_back(*it); sd.back().z = z;
            if (!seed_mono) continue;
            // experiment (DIASPX_SEED_MONO): a hill one isotope step below means this one is not the lightest at z
            const double t = it->mz - C13 / z, tol = t * P.ppm * 1e-6;
            for (auto b = std::lower_bound(seeds.begin(), seeds.end(), t - tol, [](const Prec& p, double m) { return p.mz < m; });
                 b != seeds.end() && b->mz <= t + tol && sd.back().z; ++b)
              if (it->rt_lo <= b->rt_hi && b->rt_lo <= it->rt_hi) sd.back().z = 0;   // 0 = skipped
          }
        }
        std::vector<MSSpectrum> s2(sd.size());
        std::vector<int> np2(sd.size(), 0);
        const long ns = (long)sd.size();
        #pragma omp taskloop grainsize(128) default(shared)
        for (long i = 0; i < ns; i += 2)
        {
          try
          {
            std::vector<std::pair<double, double>> raw;
            const auto one = [&](long j, std::vector<std::pair<double, double>>* r)
            {
              s2[j] = assemble(sd[j], fr, gr, cycle, P, lo, hi, nullptr, rm, r);
              if (s2[j].getMSLevel() == 2) np2[j] = complementPairs(s2[j], sd[j].z * (sd[j].mz - PROTON), P.ms2_ppm > 0 ? P.ms2_ppm : P.ppm, (size_t)P.pair_top);
            };
            const bool z3 = sd[i + 1].z > 0, sh = z3 && share;
            if (z3) one(i + 1, share ? &raw : nullptr);
            if (sd[i].z > 0 && !(sh && raw.empty())) one(i, sh ? &raw : nullptr);   // nothing at z 3: nothing at z 2
          }
          catch (...)
          {
            #pragma omp critical(noims_err)
            if (!terr) terr = std::current_exception();
          }
        }
        if (terr) std::rethrow_exception(terr);
        for (long i = 0; i < ns; i += 2)
        {
          const long j = np2[i + 1] > np2[i] ? i + 1 : i;   // one charge per seed; z 2 on a tie
          if (np2[j] >= P.hill_seeds) { res[w].push_back(std::move(s2[j])); ++nprec[w]; }
        }
      }
      busy[w] = std::chrono::duration<double>(clk::now() - tw).count();
    }
    catch (...)
    {
      #pragma omp critical(noims_err)
      if (!err) err = std::current_exception();
    }
    if (err) std::rethrow_exception(err);

    if (dump) { std::ofstream of(std::string(dump) + "/dump.tsv"); for (auto& o : dbg) of << o.str(); }
    for (size_t w = 0; w < W; ++w)
    {
      st.precursors += nprec[w]; st.busy_s += busy[w]; st.ms2_traces += ntr2[w];
      for (auto& s : res[w]) { st.peaks += s.size(); out.addSpectrum(std::move(s)); }
    }
    // by RT; spectra of one RT keep the assembly order (window key, then precursor order), which is platform-independent
    std::stable_sort(out.getSpectra().begin(), out.getSpectra().end(), [](const MSSpectrum& a, const MSSpectrum& b) { return a.getRT() < b.getRT(); });
    for (size_t i = 0; i < out.size(); ++i) out[i].setNativeID("index=" + String(i));
    st.spectra = out.size();
    if (const auto n = std::count_if(scans.begin(), scans.end(), [](const auto& v) { return v.size() < 3; }))
      log("[noims] " + String(n) + " of " + String(W) + " isolation windows have fewer than 3 MS2 scans: no spectra from them");
    double sm = 0, sf = 0; size_t nf = 0;
    for (size_t w = 0; w < W; ++w) { sm += t_mtd[w]; sf += t_frag[w]; nf += nfrag[w]; }
    log("[noims] " + String(nf) + " fragments; window busy: MS2 traces " + String(sm) + " s, envelopes and fragments " + String(sf)
        + " s, spectra " + String(st.busy_s - sm - sf) + " s");
    st.wall_s = std::chrono::duration<double>(clk::now() - t0).count();
    log("[noims] " + String(st.ms2_traces) + " MS2 traces, " + String(st.precursors) + " precursors, " + String(st.spectra) + " spectra, " + String(st.peaks) + " peaks; "
        + String(st.wall_s) + " s, window busy " + String(st.busy_s) + " s on " + String(st.threads) + " threads");
    return st;
  }
}
