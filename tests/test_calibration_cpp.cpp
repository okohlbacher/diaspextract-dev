// Golden test for the SHIPPED C++ calibration (src/TdfMzCalibration.h) against values produced by
// Bruker's own timsdata library. Runs anywhere: no vendor library, no cluster, no raw data, no
// OpenMS -- only a C++17 compiler. Build: c++ -std=c++17 -I src tests/test_calibration_cpp.cpp
#include "TdfMzCalibration.h"
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

// Minimal extraction from the golden JSON: it is machine-generated with a fixed shape, so a tiny
// scanner beats adding a JSON dependency to a test that must build everywhere.
static bool nextNumber(const std::string& s, const std::string& key, size_t& pos, double& out)
{
  const size_t k = s.find("\"" + key + "\":", pos);
  if (k == std::string::npos) return false;
  size_t v = s.find(':', k) + 1;
  while (v < s.size() && (s[v] == ' ' || s[v] == '\n')) ++v;
  out = std::strtod(s.c_str() + v, nullptr);
  pos = v;
  return true;
}

int main(int argc, char** argv)
{
  const std::string path = argc > 1 ? argv[1] : "tests/calibration_golden.json";
  std::ifstream f(path);
  if (!f) { std::fprintf(stderr, "cannot open %s\n", path.c_str()); return 2; }
  std::stringstream ss; ss << f.rdbuf();
  const std::string j = ss.str();

  size_t pos = 0;
  int n_files = 0, n_cases = 0;
  double worst = 0.0, worst_noc2 = 0.0;
  while (true)
  {
    const size_t fstart = j.find("\"model_type\":", pos);
    if (fstart == std::string::npos) break;
    spextract::TdfMzCalibration cal;
    size_t p = fstart;
    double v = 0;
    nextNumber(j, "model_type", p, v);        cal.model_type = (int)v;
    nextNumber(j, "timebase", p, v);          cal.digitizer_timebase = v;
    nextNumber(j, "delay", p, v);             cal.digitizer_delay = v;
    nextNumber(j, "C0", p, v);                cal.C0 = v;
    nextNumber(j, "C1", p, v);                cal.C1 = v;
    nextNumber(j, "C2", p, v);                cal.C2 = v;
    nextNumber(j, "T1_ref", p, v);            cal.T1_ref = v;
    nextNumber(j, "dC1", p, v);               cal.dC1 = v;
    if (!cal.isSupported())
    { std::fprintf(stderr, "golden file %d unsupported: %s\n", n_files, cal.unsupportedReason().c_str()); return 1; }

    const size_t fend = j.find("\"model_type\":", fstart + 10);
    size_t cp = j.find("\"cases\":", fstart);
    while (true)
    {
      const size_t c = j.find("\"frame\":", cp);
      if (c == std::string::npos || (fend != std::string::npos && c > fend)) break;
      size_t q = c;
      double frame = 0, t1 = 0, tof = 0, mz = 0;
      nextNumber(j, "frame", q, frame);
      nextNumber(j, "t1", q, t1);
      nextNumber(j, "tof", q, tof);
      nextNumber(j, "mz", q, mz);
      const double b = cal.frameFactor(t1);
      const double got = cal.tofToMz(tof, b);
      const double ppm = std::fabs(got - mz) / mz * 1e6;
      if (ppm > 1e-3)
      {
        std::fprintf(stderr, "FAIL frame %.0f tof %.0f: got %.6f want %.6f (%.6f ppm)\n",
                     frame, tof, got, mz, ppm);
        return 1;
      }
      worst = std::fmax(worst, ppm);
      // round trip must return the same TOF
      const double back = cal.mzToTof(got, b);
      if (std::fabs(back - tof) > 1e-3)
      { std::fprintf(stderr, "FAIL round trip: tof %.4f -> mz -> %.4f\n", tof, back); return 1; }
      // ablation: dropping C2 must be clearly visible, else the golden set proves nothing
      spextract::TdfMzCalibration no_c2 = cal; no_c2.C2 = 0.0;
      worst_noc2 = std::fmax(worst_noc2, std::fabs(no_c2.tofToMz(tof, b) - mz) / mz * 1e6);
      ++n_cases;
      cp = q;
    }
    ++n_files;
    pos = fstart + 10;
  }
  if (n_cases < 30) { std::fprintf(stderr, "only %d golden cases parsed\n", n_cases); return 1; }
  if (worst_noc2 < 5.0)
  { std::fprintf(stderr, "C2 ablation only %.3f ppm -- golden set cannot catch the known-bad port\n", worst_noc2); return 1; }

  // negative paths must be REJECTED, not approximated
  spextract::TdfMzCalibration bad;
  bad.model_type = 2; bad.C1 = 1.0; bad.digitizer_timebase = 0.125;
  if (bad.isSupported()) { std::fprintf(stderr, "ModelType 2 must be rejected\n"); return 1; }
  bad.model_type = 1; bad.dC2 = 1e-9;
  if (bad.isSupported()) { std::fprintf(stderr, "dC2 != 0 must be rejected\n"); return 1; }
  bad.dC2 = 0.0; bad.C3 = 1e-9;
  if (bad.isSupported()) { std::fprintf(stderr, "C3 != 0 must be rejected\n"); return 1; }
  bad.C3 = 0.0; bad.C4 = 1e-9;
  if (bad.isSupported()) { std::fprintf(stderr, "C4 != 0 must be rejected\n"); return 1; }
  bad.C4 = 0.0; bad.C1 = 0.0;
  if (bad.isSupported()) { std::fprintf(stderr, "C1 <= 0 must be rejected\n"); return 1; }

  std::printf("OK  %d golden cases, %d files: max %.6f ppm; C2 ablation %.2f ppm; round trip + negative paths pass\n",
              n_cases, n_files, worst, worst_noc2);
  return 0;
}
