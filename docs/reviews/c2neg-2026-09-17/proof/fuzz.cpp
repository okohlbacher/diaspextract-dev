// Independent check of the negative-C2 domain rule: random rows; for every ACCEPTED row, sample the domain
// (TOF <= 1e8, m/z <= 1e5, |T1 - T1_ref| <= 1000) and verify disc >= b^2/4 (1e-12 rel slack), tofToMz finite,
// rising, round trip; mzToTof monotone up to 1e5 and beyond (report the first m where it turns).
#include "TdfMzCalibration.h"
#include <random>
#include <cstdio>
#include <cmath>
using Cal = diaspextract::TdfMzCalibration;
int main() {
  std::mt19937_64 rng(12345);
  auto U = [&](double a, double b) { return std::uniform_real_distribution<double>(a, b)(rng); };
  long acc = 0, rej = 0, viol = 0, nonmono_1e5 = 0, rt_bad = 0;
  double min_vertex_accepted = 1e300, max_rt = 0;
  for (int it = 0; it < 200000; ++it) {
    Cal c; c.model_type = 1;
    c.digitizer_timebase = std::pow(10.0, U(-3, 0.5));
    c.digitizer_delay = U(-1e5, 1e5);
    c.C0 = U(-1e3, 1e3);
    c.C1 = std::pow(10.0, U(0.01, 11.9));
    c.C2 = -std::pow(10.0, U(-8, 1));
    c.T1_ref = U(-50, 80);
    c.dC1 = U(-1500, 1500);
    c.C4 = (it % 3 == 0) ? 0.0 : U(-2e5, 2e5) * (it % 7 == 0 ? 1.0 : 1e-6);
    if (!c.isSupported()) { ++rej; continue; }
    ++acc;
    for (int j = 0; j < 64; ++j) {
      const double t1 = c.T1_ref + (j < 2 ? (j ? 1000.0 : -1000.0) : U(-1000, 1000));
      const double b = c.frameFactor(t1);
      const double tof = j < 4 ? 1e8 : U(0, 1e8);
      const double t = tof * c.digitizer_timebase + c.digitizer_delay;
      const double disc = b * b - 4.0 * c.C2 * (c.C0 - t);
      if (t > c.C0 && disc < 0.25 * b * b * (1 - 1e-12)) {
        if (++viol <= 5) std::printf("VIOL tof: C0 %g C1 %g C2 %g tb %g dl %g dC1 %g t1-T1ref %g tof %g disc/b2 %g\n",
                                     c.C0, c.C1, c.C2, c.digitizer_timebase, c.digitizer_delay, c.dC1, t1 - c.T1_ref, tof, disc / (b * b));
      }
      const double mz = j < 4 ? 1e5 : U(1e-3, 1e5);
      const double m = mz + c.C4;
      if (m > 0) {
        const double u = std::sqrt(m);
        const double slope = b + 2.0 * c.C2 * u;   // dt/du
        if (slope < 0.5 * b * (1 - 1e-12)) {
          if (++viol <= 10) std::printf("VIOL mz: C2 %g C4 %g b %g mz %g slope/b %g\n", c.C2, c.C4, b, mz, slope / b);
        }
        // round trip through the inverse
        const double tt = c.mzToTof(mz, b);
        const double back = c.tofToMz(tt, b);
        if (std::isfinite(back)) { const double r = std::fabs(back - mz) / mz; if (r > max_rt) max_rt = r; if (r > 1e-6 && mz > 1) ++rt_bad; }
      }
      const double vertex = b * b / (4 * c.C2 * c.C2) - c.C4;   // m/z where mzToTof turns
      if (vertex < min_vertex_accepted) min_vertex_accepted = vertex;
      if (vertex < 1e5) ++nonmono_1e5;
    }
  }
  std::printf("accepted %ld refused %ld violations %ld nonmono_below_1e5 %ld min_vertex_mz %.6g max_rt_rel %.3g rt_bad %ld\n",
              acc, rej, viol, nonmono_1e5, min_vertex_accepted, max_rt, rt_bad);
  // largest accepted |C2| for 1418 and D constants by bisection
  for (int which = 0; which < 2; ++which) {
    Cal c; c.model_type = 1; c.dC1 = 20;
    if (which == 0) { c.digitizer_timebase = 0.19999999999999998; c.digitizer_delay = 25779.8; c.C0 = 314.1341896383674; c.C1 = 154199.217568937; c.T1_ref = 25.618823611312585; }
    else { c.digitizer_timebase = 0.125; c.digitizer_delay = 25655.375; c.C0 = 279.3262846272992; c.C1 = 155279.13067653627; c.T1_ref = 25.693668980735552; }
    double lo = 1e-9, hi = 10;
    for (int k = 0; k < 200; ++k) { const double mid = std::sqrt(lo * hi); c.C2 = -mid; (c.isSupported() ? lo : hi) = mid; }
    c.C2 = -lo;
    const double b = c.frameFactor(c.T1_ref);
    std::printf("%s: max accepted |C2| %.7g; m/z vertex at T1_ref %.6g; m/z where slope halves %.6g\n", which ? "D" : "1418", lo,
                b * b / (4 * lo * lo), b * b / (16 * lo * lo));
    // real 1418 row: m/z where mzToTof turns
    if (which == 0) { c.C2 = -0.0010422663259118895; std::printf("1418 real: vertex m/z %.6g, TOF at vertex %.6g\n", b*b/(4*c.C2*c.C2), c.mzToTof(b*b/(4*c.C2*c.C2), b)); }
  }
  // tofOf behaviour for huge m/z (DBL_MAX, 1e300) on the real 1418 row vs D
  {
    Cal c; c.model_type = 1; c.dC1 = 20; c.digitizer_timebase = 0.19999999999999998; c.digitizer_delay = 25779.8; c.C0 = 314.1341896383674; c.C1 = 154199.217568937; c.T1_ref = 25.618823611312585; c.C2 = -0.0010422663259118895;
    const double b = c.frameFactor(c.T1_ref);
    for (double mz : {1e5, 4e5, 1e12, 1.46e12, 1e13, 1e20, 1.7976931348623157e308})
      std::printf("1418 mzToTof(%g) = %.6g\n", mz, c.mzToTof(mz, b));
  }
}
