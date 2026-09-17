#include "TdfMzCalibration.h"
#include <cstdio>
#include <cmath>
using Cal = diaspextract::TdfMzCalibration;
int main() {
  struct R { const char* n; double tb, dl, c0, c1, c2, t1; } rows[] = {
    {"1418", 0.19999999999999998, 25779.8, 314.1341896383674, 154199.217568937, -0.0010422663259118895, 25.618823611312585},
    {"1431", 0.19999999999999998, 25779.8, 314.0580393347482, 154198.21084980678, -0.0012283576883732204, 25.612279482616906},
    {"1408", 0.19999999999999998, 25779.999999999996, 314.48704092054686, 154201.38074828373, -0.0007559259827031187, 25.610076586928137},
    {"1347", 0.19999999999999998, 25779.999999999996, 314.5551322024985, 154202.25071153036, -0.0005864322965816343, 25.609173082963196}};
  for (auto& r : rows) {
    Cal c; c.model_type = 1; c.dC1 = 20; c.digitizer_timebase = r.tb; c.digitizer_delay = r.dl; c.C0 = r.c0; c.C1 = r.c1; c.T1_ref = r.t1;
    double lo = 1e-9, hi = 10;
    for (int k = 0; k < 200; ++k) { const double mid = std::sqrt(lo * hi); c.C2 = -mid; (c.isSupported() ? lo : hi) = mid; }
    // NaN round-trip masking demo: fmax ignores NaN
    std::printf("%s edge |C2| %.7g = %.1f x |C2| %.6g\n", r.n, lo, lo / std::fabs(r.c2), std::fabs(r.c2));
  }
  std::printf("fmax(1e-9, NaN) = %g\n", std::fmax(1e-9, std::nan("")));
  // codex extreme rows
  Cal a; a.model_type = 1; a.C1 = 1e6; a.C2 = -0.25; a.C0 = std::ldexp(1.0, 72); a.digitizer_delay = std::ldexp(1.0, 72) + 1048576; a.digitizer_timebase = 1e-9;
  std::printf("codex row A supported %d; tofToMz(0) = %g\n", a.isSupported(), a.tofToMz(0, a.frameFactor(a.T1_ref)));
  Cal b; b.model_type = 1; b.C1 = 1e5; b.C2 = -1e-310; b.digitizer_timebase = 1e308;
  std::printf("codex row B supported %d; tofToMz(2) = %g\n", b.isSupported(), b.tofToMz(2, b.frameFactor(b.T1_ref)));
  // codex temperature witness: 1418 row, C4 = -500, T1 = T1_ref + 50000
  Cal t; t.model_type = 1; t.dC1 = 20; t.digitizer_timebase = 0.19999999999999998; t.digitizer_delay = 25779.8; t.C0 = 314.1341896383674; t.C1 = 154199.217568937; t.T1_ref = 25.618823611312585; t.C2 = -0.0010422663259118895; t.C4 = -500;
  const double bb = t.frameFactor(t.T1_ref + 50000);
  std::printf("codex T1 witness: supported %d frameReason '%s' b %g tofToMz(2000) %g\n", t.isSupported(), t.frameReason(t.T1_ref + 50000).c_str(), bb, t.tofToMz(2000, bb));
  t.C2 = 0.0010422663259118895;  // same witness with a POSITIVE C2: pre-existing?
  std::printf("  same with C2 > 0: supported %d frameReason '%s' tofToMz(2000) %g\n", t.isSupported(), t.frameReason(t.T1_ref + 50000).c_str(), t.tofToMz(2000, bb));
  // PXD017703-like C4 with positive C2 and cf == 0
  // uint32 max on each PXD vector at the +-1000 K corner: disc/b^2
  for (auto& r : rows) {
    const double cfh = 1 + 20.0 * 1000 / 1e6, b0 = 1e6 / std::sqrt(r.c1 * cfh);
    const double tt = 4294967295.0 * r.tb + r.dl;
    std::printf("%s uint32-max corner disc/b^2 %.4f\n", r.n, (b0 * b0 + 4 * r.c2 * (tt - r.c0)) / (b0 * b0));
  }
}
