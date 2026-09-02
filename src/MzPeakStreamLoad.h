// speXtract: streaming diaPASEF load from an .mzpeak archive through the mzPeak C++ library
// (github.com/OpenMS/mzpeak, fork okohlbacher/mzpeak-openms). Mirrors BrukerTimsFile::
// loadDIAStreaming's contract so PickCompactConsumer sees the same stream: every MS1 spectrum
// first (frame order), then one MSSpectrum per (MS2 frame, isolation window) holding only the
// peaks inside that window's 1/K0 band, handed over serially in frame order.
//
// mzPeak stores a diaPASEF frame as ONE spectrum carrying N precursors (one per window, each
// with an ion-mobility band) and a per-peak ion-mobility array; ims-compact archives carry raw
// TOF and the library reconstructs m/z with the archive's own two-point transform. Peaks arrive
// mobility-major, so each per-window spectrum is m/z-sorted here.
//
// ponytail: decode is parallel over contiguous frame ranges with one Index per thread (decodes
// serialise on a reader's mutex); the hand-off is serial. No caching beyond the library's own.
#pragma once
#ifdef SPEXTRACT_WITH_MZPEAK

#include <mzpeak/open.h>
#include <mzpeak/index.h>
#include <mzpeak/spectra.h>
#include <mzpeak/spectrum.h>
#include <mzpeak/spectrum_metadata.h>

#include <OpenMS/KERNEL/MSSpectrum.h>
#include <OpenMS/METADATA/Precursor.h>
#include <OpenMS/CONCEPT/Exception.h>
#include <OpenMS/IONMOBILITY/IMDataConverter.h>
#include <OpenMS/FORMAT/DATAACCESS/SwathFileConsumer.h>

#include <algorithm>
#include <cmath>
#include <exception>
#include <limits>
#include <memory>
#include <string>
#include <vector>
#ifdef _OPENMP
#include <omp.h>
#endif

namespace spx
{
  struct MzPeakWin { double lo, hi, im_lo, im_hi; };

  /// Calibration provenance of the last mzPeak load (the archive's two-point tof transform, applied by the
  /// library; NOT the TDF table model). Stamped into the output instead of BrukerTimsFile's state.
  inline std::string& lastMzPeakCalibration() { static std::string s = "unset"; return s; }

  /// One decoded frame split per window (index-aligned with `wins` of that frame).
  inline void frameToSpectra_(const MzPeak::Spectrum& sp, double rt, std::size_t frame_idx,
                              const std::vector<MzPeakWin>& wins, std::vector<OpenMS::MSSpectrum>& out)
  {
    using namespace OpenMS;
    const std::vector<double>& mz = sp.mz();
    const std::vector<float>& in = sp.intensity();
    const std::vector<double>& im = sp.ion_mobility_array();
    const std::size_t n = std::min(mz.size(), in.size());
    const bool have_im = im.size() >= n;
    out.assign(wins.size(), MSSpectrum());
    for (std::size_t w = 0; w < wins.size(); ++w)
    {
      const MzPeakWin& win = wins[w];
      MSSpectrum& spec = out[w];
      spec.setRT(rt);
      spec.setMSLevel(wins.size() == 1 && !(win.lo < win.hi) ? 1 : 2);
      spec.setDriftTimeUnit(DriftTimeUnit::VSSC);
      spec.setNativeID("mzpeak=" + std::to_string(frame_idx) + " window=" + std::to_string(w));
      if (spec.getMSLevel() == 2)
      {
        Precursor prec;
        prec.setMZ(0.5 * (win.lo + win.hi));
        prec.setIsolationWindowLowerOffset(0.5 * (win.hi - win.lo));
        prec.setIsolationWindowUpperOffset(0.5 * (win.hi - win.lo));
        spec.setPrecursors({prec});
        spec.setMetaValue("ion mobility lower limit", win.im_lo);
        spec.setMetaValue("ion mobility upper limit", win.im_hi);
      }
      DataArrays::FloatDataArray im_array;
      IMDataConverter::setIMUnit(im_array, DriftTimeUnit::VSSC);
      spec.reserve(n / wins.size() + 64); im_array.reserve(n / wins.size() + 64);
      for (std::size_t k = 0; k < n; ++k)
      {
        const double k0 = have_im ? im[k] : 0.0;
        if (have_im && (k0 < win.im_lo || k0 > win.im_hi)) continue;
        if (!(in[k] > 0)) continue;
        spec.emplace_back(mz[k], in[k]);
        im_array.push_back(static_cast<float>(k0));
      }
      if (spec.empty()) continue;
      // mobility-major on disk -> sort by m/z, carrying the IM array along
      std::vector<std::size_t> ord(spec.size());
      for (std::size_t k = 0; k < ord.size(); ++k) ord[k] = k;
      std::stable_sort(ord.begin(), ord.end(), [&](std::size_t a, std::size_t b) { return spec[a].getMZ() < spec[b].getMZ(); });
      std::vector<Peak1D> sorted; sorted.reserve(spec.size());
      DataArrays::FloatDataArray im_sorted; IMDataConverter::setIMUnit(im_sorted, DriftTimeUnit::VSSC); im_sorted.reserve(spec.size());
      for (std::size_t k : ord) { sorted.push_back(spec[k]); im_sorted.push_back(im_array[k]); }
      spec.clear(false);                                          // peaks only; RT/precursor/meta stay
      for (const Peak1D& pk : sorted) spec.push_back(pk);
      spec.getFloatDataArrays().push_back(std::move(im_sorted));
      spec.setIMPeakType(IMPeakType::IM_PROFILE);
    }
  }

  /// Stream an .mzpeak run into `consumer` (MS1 first, then MS2 per (frame, window), frame order).
  /// Returns the number of frames seen.
  inline std::size_t loadMzPeakStreaming(const std::string& path, OpenMS::FullSwathFileConsumer& consumer, int threads)
  {
    // 1) metadata sweep (no peak decode): RT, level, windows with IM bands, per frame
    MzPeak::Index index = MzPeak::open(path);
    MzPeak::Spectra spectra = index.spectra();
    const std::size_t n = spectra.size();
    lastMzPeakCalibration() = "mzpeak_two_point_transform (library-applied MS:1003825 from the archive; not the TDF MzCalibration model) archive=" + path.substr(path.find_last_of('/') + 1);
    std::vector<double> rt(n);
    std::vector<std::vector<MzPeakWin>> wins(n);
    std::vector<std::size_t> ms1, ms2;
    for (std::size_t i = 0; i < n; ++i)
    {
      MzPeak::Spectrum sp = spectra[i];
      const auto& md = sp.metadata();
      rt[i] = md.retention_time.value_or(0.0);
      if (md.ms_level.value_or(1) == 1) { wins[i] = {MzPeakWin{0, 0, -1e9, 1e9}}; ms1.push_back(i); continue; }
      // Selected ions carry the per-window 1/K0 band. mzpeak-convert 0.9.x writes precursor_index
      // as NULL and the band as NAME-ONLY CV params; the reader then attaches every ion of the
      // frame to the FIRST precursor. So: flatten all ions of the spectrum and match each window
      // to the ion whose selected_ion_mz is its isolation target.
      struct Ion { double mz, lo, hi; };
      std::vector<Ion> ions;
      for (const auto& p : md.precursors)
        for (const auto& si : p.selected_ions)
        {
          Ion ion{si.selected_ion_mz.value_or(-1.0), -1e9, 1e9};
          if (si.ion_mobility_lower_limit && si.ion_mobility_upper_limit) { ion.lo = *si.ion_mobility_lower_limit; ion.hi = *si.ion_mobility_upper_limit; }
          for (const auto& cv : si.parameters)
          {
            if (!cv.name || !cv.value) continue;
            if (cv.name->find("ion mobility lower limit") != std::string::npos) ion.lo = std::stod(*cv.value);
            else if (cv.name->find("ion mobility upper limit") != std::string::npos) ion.hi = std::stod(*cv.value);
          }
          ions.push_back(ion);
        }
      for (const auto& p : md.precursors)
      {
        if (!p.isolation_window.target_mz) continue;
        const double c = *p.isolation_window.target_mz;
        const double lo = c - p.isolation_window.lower_offset.value_or(0.f), hi = c + p.isolation_window.upper_offset.value_or(0.f);
        const Ion* best = nullptr;
        for (const Ion& ion : ions) if (!best || std::fabs(ion.mz - c) < std::fabs(best->mz - c)) best = &ion;
        if (!best || std::fabs(best->mz - c) > 0.05 || best->lo < -1e8 || best->hi > 1e8)
          throw OpenMS::Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
                                                "mzPeak MS2 window without a matching ion-mobility band (spectrum " + std::to_string(i) + ")", std::to_string(c));
        wins[i].push_back(MzPeakWin{lo, hi, best->lo, best->hi});
      }
      if (!wins[i].empty()) ms2.push_back(i);
    }

    // 2) decode in parallel over contiguous ranges (row-group locality), hand off serially in order
    int nthr = std::max(1, threads);
#ifdef _OPENMP
    nthr = std::min(nthr, std::max(1, omp_get_max_threads()));
#endif
    auto run = [&](const std::vector<std::size_t>& ids)
    {
      const std::size_t per = 12;                                  // frames per thread per batch (~1 row group)
      const std::size_t batch = std::max<std::size_t>(per, per * (std::size_t)nthr);
      for (std::size_t b0 = 0; b0 < ids.size(); b0 += batch)
      {
        const std::size_t b1 = std::min(ids.size(), b0 + batch);
        const int nchunk = (int)((b1 - b0 + per - 1) / per);
        std::vector<std::vector<std::vector<OpenMS::MSSpectrum>>> out((std::size_t)nchunk);
        std::exception_ptr err;
        #pragma omp parallel for schedule(dynamic, 1) num_threads(nthr)
        for (int c = 0; c < nchunk; ++c)
        {
          try
          {
            const std::size_t c0 = b0 + (std::size_t)c * per, c1 = std::min(b1, c0 + per);
            // one reader per THREAD (not per work item): MzPeak::open re-reads the zip directory and
            // every parquet footer; ~1,450 opens cost ~1 h of system time on S30 (measured 13:55).
            static thread_local std::unique_ptr<MzPeak::Index> tidx;   // Index is neither movable nor copyable:
            static thread_local std::string tidx_path;                  // construct it from the prvalue (elided)
            if (!tidx || tidx_path != path) { tidx.reset(new MzPeak::Index(MzPeak::open(path))); tidx_path = path; }
            MzPeak::Spectra tsp = tidx->spectra();
            std::vector<std::size_t> want(ids.begin() + (std::ptrdiff_t)c0, ids.begin() + (std::ptrdiff_t)c1);
            std::vector<MzPeak::Spectrum> got = tsp.get_spectra_batch(want);
            auto& slot = out[(std::size_t)c]; slot.resize(want.size());
            for (std::size_t k = 0; k < want.size() && k < got.size(); ++k)
              frameToSpectra_(got[k], rt[want[k]], want[k], wins[want[k]], slot[k]);
          }
          catch (...)
          {
            #pragma omp critical(mzpeak_err)
            if (!err) err = std::current_exception();
          }
        }
        if (err) std::rethrow_exception(err);
        for (auto& chunk : out) for (auto& frame : chunk) for (auto& spec : frame)
          if (!spec.empty()) consumer.consumeSpectrum(spec);
      }
    };
    run(ms1);
    run(ms2);
    return ms1.size() + ms2.size();
  }
} // namespace spx
#endif // SPEXTRACT_WITH_MZPEAK
