// Copyright (c) 2026, speXtract authors. BSD-3-Clause.
//
// Exact TOF -> m/z conversion for Bruker TDF (timsTOF) data, ModelType 1.
//
// Header-only and dependency-free ON PURPOSE: this is the single source of truth for the
// calibration, shared by the OpenMS loader patch (patches/openms-brukertims-mz-calibration.patch,
// which supplies the constants from the file's MzCalibration table) and by the C++ unit test
// (tests/test_calibration_cpp.cpp), so the code that ships is the code that is tested.
//
// Model, derived numerically against Bruker's timsdata library used as a local oracle (no vendor
// code was read, no vendor binary is redistributed; every constant comes from the user's own file):
//
//     t_ns   = tof * DigitizerTimebase + DigitizerDelay
//     C1_eff = C1 * (1 + dC1 * (T1_ref - T1_frame) / 1e6)        // digitizer temperature drift
//     t_ns   = C0 + (1e6 / sqrt(C1_eff)) * sqrt(m) + C2 * m      // solved for sqrt(m)
//
// Verified to 2.5e-5 ppm max against the vendor library (tests/calibration_golden.json).
// SCOPE OF THAT CLAIM, stated precisely because it is narrower than the file count suggests: the
// three files share ONE identical MzCalibration vector (same C0/C1/C2/timebase/delay/T1_ref/dC1),
// so independent coverage of the parameter space is ONE vector -- 12 frames spanning only 0.034 K,
// probed at five TOF positions covering m/z 133.7-1573.7. ModelType 1, single-row table, dC2 == 0,
// one instrument cohort. Everything outside that is REJECTED rather than
// approximated -- see isSupported(): silently emitting wrong masses is the failure mode this whole
// file exists to prevent (the previous two-point chord was -5..-11 ppm and nobody noticed for months).
//
// Note for implementers: the widely-copied open implementation (timsrust-calibration, adapted then
// disabled by mzdata as "not consistently better") DROPS the C2*m term, which is worth -11..-40 ppm
// on this data. That omission -- not translation subtlety -- is why the port underperformed.

#pragma once
#include <cmath>
#include <string>

namespace spextract
{

/// Constants as stored in the TDF `MzCalibration` row plus the per-frame digitizer temperature.
struct TdfMzCalibration
{
  int model_type = 0;
  double digitizer_timebase = 0.0;
  double digitizer_delay = 0.0;
  double C0 = 0.0;
  double C1 = 0.0;      ///< must be > 0
  double C2 = 0.0;      ///< the quadratic term the open implementations drop
  double T1_ref = 0.0;  ///< reference digitizer temperature for the calibration
  double dC1 = 0.0;     ///< ppm/K drift of C1
  double dC2 = 0.0;     ///< drift of C2 -- NOT modelled; must be 0 (see isSupported)
  double C3 = 0.0, C4 = 0.0;   ///< higher-order terms -- NOT modelled; must be 0

  /// Why this calibration cannot be used, or empty if it can. Fail closed, never approximate.
  std::string unsupportedReason() const
  {
    if (model_type != 1) return "MzCalibration ModelType " + std::to_string(model_type) + " != 1";
    if (!(C1 > 0.0)) return "MzCalibration C1 <= 0";
    if (dC2 != 0.0) return "MzCalibration dC2 != 0 (temperature drift of C2 is not modelled)";
    if (C3 != 0.0 || C4 != 0.0) return "MzCalibration C3/C4 != 0 (higher-order terms are not modelled)";
    if (C2 < 0.0) return "MzCalibration C2 < 0 (outside the modelled/verified regime)";
    if (!(digitizer_timebase > 0.0)) return "DigitizerTimebase <= 0";
    return std::string();
  }
  bool isSupported() const { return unsupportedReason().empty(); }

  /// Temperature-corrected 1e6/sqrt(C1_eff) for one frame; hoist out of per-peak loops.
  double frameFactor(double t1_frame) const
  {
    const double cf = 1.0 + (dC1 * (T1_ref - t1_frame)) / 1e6;
    return 1e6 / std::sqrt(C1 * cf);
  }

  /// TOF index -> m/z. @p b is frameFactor() for this frame.
  double tofToMz(double tof, double b) const
  {
    const double t = tof * digitizer_timebase + digitizer_delay;
    if (C2 == 0.0)                                   // degenerate: pure sqrt law
    {
      const double u = (t - C0) / b;
      return u * u;
    }
    // Stable root of C2*u^2 + b*u + (C0 - t) = 0: the textbook form (-b + sqrt(disc))/(2*C2)
    // subtracts two nearly equal numbers (b ~ 2.5e3, C2 ~ 1e-3), throwing away ~4 digits.
    // u = 2*(t - C0) / (b + sqrt(disc)) is algebraically identical and cancellation-free.
    // t < C0 is unphysical (arrival before the calibration zero) and would yield a NEGATIVE u whose
    // square is a plausible-looking but WRONG mass -- the exact silent-wrongness this file exists to
    // prevent. Both it and a negative discriminant return 0.0, which callers see as an out-of-range
    // peak rather than a credible m/z.
    const double disc = b * b - 4.0 * C2 * (C0 - t);
    if (disc < 0.0 || t <= C0) return 0.0;
    const double denom = b + std::sqrt(disc);
    if (!(denom > 0.0)) return 0.0;
    const double u = 2.0 * (t - C0) / denom;
    return u * u;
  }

  /// m/z -> TOF index (exact inverse of tofToMz; the model is closed-form in this direction).
  double mzToTof(double mz, double b) const
  {
    const double t = C0 + b * std::sqrt(mz > 0.0 ? mz : 0.0) + C2 * mz;
    return (t - digitizer_delay) / digitizer_timebase;
  }
};

} // namespace spextract
