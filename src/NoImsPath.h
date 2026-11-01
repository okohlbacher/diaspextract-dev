// The extraction path for DIA input without ion mobility (Orbitrap, SWATH mzML). Separate from the IMS path by rule:
// it shares loading and writing with it, nothing else, and never changes what the IMS path emits.
//
// Per isolation window, in parallel: (1) precursors = MS1 mass traces of the window's m/z slice grouped into isotope
// envelopes (charge 1-4; the mono is the lightest trace of the group); (2) fragments = mass traces of the window's MS2
// scans; (3) a fragment joins a precursor when its profile correlates with the precursor's over the precursor's
// elution span (Pearson r >= noims:min_corr on the window's scan grid), or, with fewer than 3 grid points in that
// span, when its apex lies within one cycle of the precursor apex. One spectrum per precursor with >= 3 fragments.
#pragma once

#include <OpenMS/KERNEL/MSExperiment.h>
#include <OpenMS/KERNEL/MassTrace.h>
#include <OpenMS/FEATUREFINDER/MassTraceDetection.h>
#include <OpenMS/FEATUREFINDER/ElutionPeakDetection.h>
#include <omp.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <exception>
#include <functional>
#include <map>
#include <vector>

namespace spx_noims
{
  using namespace OpenMS;

  struct Params
  {
    double ppm = 10.0;          ///< mass-trace and isotope m/z tolerance
    double min_corr = 0.6;      ///< fragment-precursor Pearson r on the window grid
    int max_peaks = 150;        ///< most intense fragments kept per spectrum
    double ms1_noise = 0.0;     ///< MS1 peaks below this intensity are ignored (0 = MassTraceDetection's default)
    int ms1_min_scans = 2;      ///< MS1 traces need at least this many MS1 scans
    bool ms1_split = true;      ///< split MS1 traces at valleys (ElutionPeakDetection)
    double few_apex_cycles = 1.0; ///< precursors with < 3 window scans: fragment apex within this many cycles of the precursor apex
    int ms2_min_scans = 2;
    bool singles = true;        ///< MS1 traces in no isotope envelope become precursors at z = 2 and z = 3 (DIA-Umpire Q2-like)
    bool ms2_prec = true;       ///< isotope envelopes (z >= 2) of unfragmented precursors in the window's MS2 traces (DIA-Umpire Q3-like)      ///< fragment traces need at least this many of the window's scans (1 = single points too)
  };

  struct Stats { size_t windows = 0, ms1_traces = 0, ms2_traces = 0, precursors = 0, spectra = 0, peaks = 0; double busy_s = 0, wall_s = 0; int threads = 1; };

  namespace detail
  {
    constexpr double C13 = 1.0033548, PROTON = 1.007276;

    struct Prec { double mz, rt, rt_lo, rt_hi, inten; int z; std::vector<double> rt_pts, int_pts; int tier = 1; };
    struct Frag { double mz, apex_rt, inten; std::vector<std::pair<double, double>> pts; };

    inline double apexRT(const MassTrace& t)
    {
      double best = -1, rt = t.getCentroidRT();
      for (const auto& p : t) if (p.getIntensity() > best) { best = p.getIntensity(); rt = p.getRT(); }
      return rt;
    }

    inline std::vector<MassTrace> traces(const PeakMap& m, double ppm, double min_len, double noise, bool split)
    {
      MassTraceDetection mtd;
      Param p = mtd.getDefaults();
      p.setValue("mass_error_ppm", ppm);
      p.setValue("min_trace_length", min_len);
      if (noise > 0) p.setValue("noise_threshold_int", noise);
      mtd.setParameters(p);
      std::vector<MassTrace> mt;
      mtd.run(m, mt);
      if (!split || mt.empty()) return mt;
      ElutionPeakDetection epd;
      Param q = epd.getDefaults();
      q.setValue("width_filtering", "off");
      epd.setParameters(q);
      std::vector<MassTrace> out;
      epd.detectPeaks(mt, out);
      return out;
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
      const size_t j = std::upper_bound(x.begin(), x.end(), t) - x.begin();
      if (j == 0) return y.front();
      if (j >= x.size()) return y.back();
      const double f = (t - x[j - 1]) / (x[j] - x[j - 1]);
      return y[j - 1] + f * (y[j] - y[j - 1]);
    }

    /// isotope envelopes from MS1 traces; a trace is a mono if it has a +1 isotope and no -1 isotope at the same charge
    // ponytail: greedy, highest charge first, no averagine check; add an intensity-pattern test if charge errors show up
    inline std::vector<Prec> envelopes(const std::vector<MassTrace>& mt, double ppm, double lo, double hi, double coelute,
                                       int zmin = 1, bool singles = false)
    {
      std::vector<size_t> o(mt.size());
      for (size_t i = 0; i < o.size(); ++i) o[i] = i;
      std::sort(o.begin(), o.end(), [&](size_t a, size_t b) { return mt[a].getCentroidMZ() < mt[b].getCentroidMZ(); });
      std::vector<double> mz(o.size()), art(o.size());
      for (size_t k = 0; k < o.size(); ++k) { mz[k] = mt[o[k]].getCentroidMZ(); art[k] = apexRT(mt[o[k]]); }
      auto partner = [&](size_t k, double target) -> long {   // co-eluting trace at target m/z
        const double tol = target * ppm * 1e-6;
        const MassTrace& a = mt[o[k]];
        const double half = std::max(a.getFWHM() * 0.5, coelute);   // isotopes share MS1 scans: one scan of apex jitter
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
      std::vector<char> used(o.size(), 0);   // part of an envelope (mono or isotope)
      auto make = [&](size_t k, int z, int tier) {
        const MassTrace& t = mt[o[k]];
        Prec p{mz[k], art[k], t.begin()->getRT(), t.rbegin()->getRT(), t.getMaxIntensity(false), z, {}, {}, tier};
        for (const auto& pk : t) { p.rt_pts.push_back(pk.getRT()); p.int_pts.push_back(pk.getIntensity()); }
        out.push_back(std::move(p));
      };
      for (size_t k = 0; k < o.size(); ++k)
      {
        for (int z = 4; z >= zmin; --z)
        {
          const long nx = partner(k, mz[k] + C13 / z);
          if (nx < 0) continue;
          if (partner(k, mz[k] - C13 / z) >= 0) { used[k] = 1; break; }   // not the lightest isotope at this charge: not a mono
          used[k] = 1;
          for (long j = nx, i = 1; j >= 0 && i <= 3; j = partner((size_t)j, mz[j] + C13 / z), ++i) used[(size_t)j] = 1;
          if (mz[k] >= lo && mz[k] < hi) make(k, z, 1);
          break;
        }
      }
      if (singles)
        for (size_t k = 0; k < o.size(); ++k)
          if (!used[k] && mz[k] >= lo && mz[k] < hi) { make(k, 2, 2); make(k, 3, 2); }
      return out;
    }
  }

  /// @p exp: the resident run without ion mobility (MS1 and MS2 centroided). Fills @p out with one MS2 spectrum per precursor.
  inline Stats run(const PeakMap& exp, const Params& P, PeakMap& out, const std::function<void(const String&)>& log)
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
    for (const auto& kv : win) keys.push_back(kv.first);
    st.windows = keys.size();
    if (keys.empty() || ms1.empty()) { log("[noims] no MS1 scans or no MS2 isolation windows"); return st; }
    // a precursor belongs to the window containing it whose center is nearest (windows may overlap)
    auto owner = [&](double mz) {
      long best = -1; double bd = 1e9;
      for (size_t w = 0; w < keys.size(); ++w)
        if (mz >= keys[w].first && mz < keys[w].second)
        { const double d = std::fabs(mz - 0.5 * (keys[w].first + keys[w].second)); if (d < bd) { bd = d; best = (long)w; } }
      return best;
    };
    // cycle time: median spacing of the first window's scans
    double cycle = 1.0;
    {
      const auto& v = win.begin()->second;
      std::vector<double> d;
      for (size_t k = 1; k < v.size(); ++k) d.push_back(exp[v[k]].getRT() - exp[v[k - 1]].getRT());
      if (!d.empty()) { std::nth_element(d.begin(), d.begin() + d.size() / 2, d.end()); cycle = d[d.size() / 2]; }
    }
    double ms1_dt = cycle;
    {
      std::vector<double> d;
      for (size_t k = 1; k < ms1.size(); ++k) d.push_back(exp[ms1[k]].getRT() - exp[ms1[k - 1]].getRT());
      if (!d.empty()) { std::nth_element(d.begin(), d.begin() + d.size() / 2, d.end()); ms1_dt = d[d.size() / 2]; }
    }
    log("[noims] " + String(keys.size()) + " isolation windows, " + String(ms1.size()) + " MS1 scans every " + String(ms1_dt)
        + " s, MS2 cycle " + String(cycle) + " s");

    std::vector<std::vector<MSSpectrum>> res(keys.size());
    std::vector<size_t> nprec(keys.size(), 0), ntr1(keys.size(), 0), ntr2(keys.size(), 0);
    std::vector<double> busy(keys.size(), 0.0);
    std::exception_ptr err;
    #pragma omp parallel for schedule(dynamic, 1)
    for (long w = 0; w < (long)keys.size(); ++w)
    try
    {
      const auto tw = clk::now();
      if (win.at(keys[w]).size() < 3) continue;   // MassTraceDetection needs 3 scans
      const double lo = keys[w].first, hi = keys[w].second;
      // MS1 slice: the window's m/z range plus room for a mono's isotopes
      PeakMap m1;
      for (size_t i : ms1)
      {
        const MSSpectrum& s = exp[i];
        MSSpectrum c;
        c.setRT(s.getRT()); c.setMSLevel(1);
        for (auto it = s.MZBegin(lo - 1.5); it != s.end() && it->getMZ() < hi + 1.5; ++it) c.push_back(*it);
        m1.addSpectrum(std::move(c));
      }
      std::vector<MassTrace> mt1 = traces(m1, P.ppm, (P.ms1_min_scans - 1) * ms1_dt * 0.99, P.ms1_noise, P.ms1_split);
      ntr1[w] = mt1.size();
      std::vector<Prec> prec = envelopes(mt1, P.ppm, lo, hi, 1.01 * ms1_dt, 1, P.singles);
      prec.erase(std::remove_if(prec.begin(), prec.end(), [&](const Prec& p) { return owner(p.mz) != w; }), prec.end());
      nprec[w] = prec.size();
      m1.clear(true);

      // MS2 traces and the window's scan grid
      PeakMap m2;
      std::vector<double> grid;
      for (size_t i : win.at(keys[w]))
      { m2.addSpectrum(exp[i]); m2.getSpectra().back().setMSLevel(1); grid.push_back(exp[i].getRT()); }   // MassTraceDetection reads MS1 only
      std::vector<MassTrace> ft = traces(m2, P.ppm, (P.ms2_min_scans - 1) * cycle * 0.99, 0.0, false);
      ntr2[w] = ft.size();
      m2.clear(true);
      if (P.ms2_prec)   // unfragmented precursors seen in MS2, unless MS1 already has them (same z, 1 cycle, ppm)
      {
        std::vector<Prec> q = envelopes(ft, P.ppm, lo, hi, 1.01 * cycle, 2);
        const size_t n1 = prec.size();
        for (auto& c : q)
        {
          if (owner(c.mz) != w) continue;
          bool dup = false;
          for (size_t i = 0; i < n1 && !dup; ++i)
            dup = prec[i].z == c.z && std::fabs(prec[i].mz - c.mz) <= c.mz * P.ppm * 1e-6 && std::fabs(prec[i].rt - c.rt) <= cycle;
          if (!dup) { c.tier = 3; prec.push_back(std::move(c)); }
        }
        nprec[w] = prec.size();
      }
      std::vector<Frag> fr;
      fr.reserve(ft.size());
      for (const auto& t : ft)
      {
        Frag f{t.getCentroidMZ(), apexRT(t), t.getMaxIntensity(false), {}};
        for (const auto& pk : t) f.pts.emplace_back(pk.getRT(), pk.getIntensity());
        fr.push_back(std::move(f));
      }
      std::sort(fr.begin(), fr.end(), [](const Frag& a, const Frag& b) { return a.apex_rt < b.apex_rt; });
      std::vector<double> fapex(fr.size());
      for (size_t k = 0; k < fr.size(); ++k) fapex[k] = fr[k].apex_rt;

      for (const Prec& p : prec)
      {
        const size_t g0 = std::lower_bound(grid.begin(), grid.end(), p.rt_lo) - grid.begin();
        const size_t g1 = std::upper_bound(grid.begin(), grid.end(), p.rt_hi) - grid.begin();
        std::vector<double> pp;
        for (size_t g = g0; g < g1; ++g) pp.push_back(interp(p.rt_pts, p.int_pts, grid[g]));
        const bool few = pp.size() < 3;
        const double neutral = p.z * (p.mz - PROTON);
        std::vector<std::pair<double, double>> pk;   // (intensity, m/z)
        const double a0 = few ? p.rt - P.few_apex_cycles * cycle : p.rt_lo, a1 = few ? p.rt + P.few_apex_cycles * cycle : p.rt_hi;
        for (size_t k = std::lower_bound(fapex.begin(), fapex.end(), a0) - fapex.begin(); k < fr.size() && fapex[k] <= a1; ++k)
        {
          const Frag& f = fr[k];
          if (f.mz - PROTON > neutral - 56.0) continue;   // heavier than the precursor allows at z = 1
          if (!few)
          {
            std::vector<double> fp(pp.size(), 0.0);
            for (const auto& q : f.pts)
            {
              const size_t g = std::lower_bound(grid.begin(), grid.end(), q.first - 1e-6) - grid.begin();
              if (g >= g0 && g < g1) fp[g - g0] = q.second;
            }
            if (pearson(pp, fp) < P.min_corr) continue;
          }
          pk.emplace_back(f.inten, f.mz);
        }
        if (pk.size() < 3) continue;
        if ((int)pk.size() > P.max_peaks)
        { std::nth_element(pk.begin(), pk.begin() + P.max_peaks, pk.end(), std::greater<>()); pk.resize(P.max_peaks); }
        MSSpectrum s;
        s.setMSLevel(2);
        s.setType(SpectrumSettings::SpectrumType::CENTROID);
        s.setRT(p.rt);
        Precursor pr;
        pr.setMZ(p.mz); pr.setCharge(p.z); pr.setIntensity(p.inten);
        pr.setIsolationWindowLowerOffset(p.mz - lo); pr.setIsolationWindowUpperOffset(hi - p.mz);
        s.setPrecursors({pr});
        for (const auto& q : pk) { Peak1D x; x.setMZ(q.second); x.setIntensity(q.first); s.push_back(x); }
        s.sortByPosition();
        res[w].push_back(std::move(s));
      }
      busy[w] = std::chrono::duration<double>(clk::now() - tw).count();
    }
    catch (...)
    {
      #pragma omp critical(noims_err)
      if (!err) err = std::current_exception();
    }
    if (err) std::rethrow_exception(err);

    for (size_t w = 0; w < keys.size(); ++w)
    {
      st.precursors += nprec[w]; st.busy_s += busy[w]; st.ms1_traces += ntr1[w]; st.ms2_traces += ntr2[w];
      for (auto& s : res[w]) { st.peaks += s.size(); out.addSpectrum(std::move(s)); }
    }
    out.sortSpectra(false);
    for (size_t i = 0; i < out.size(); ++i) out[i].setNativeID("index=" + String(i));
    st.spectra = out.size();
    st.wall_s = std::chrono::duration<double>(clk::now() - t0).count();
    log("[noims] " + String(st.ms1_traces) + " MS1 traces (window slices), " + String(st.ms2_traces) + " MS2 traces, " + String(st.precursors) + " precursors, " + String(st.spectra) + " spectra, " + String(st.peaks) + " peaks; "
        + String(st.wall_s) + " s, window busy " + String(st.busy_s) + " s on " + String(st.threads) + " threads");
    return st;
  }
}
