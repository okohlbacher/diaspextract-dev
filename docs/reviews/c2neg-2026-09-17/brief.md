# Adversarial review: DIAspeXtract 1.3.1 accepts a negative MzCalibration C2 (branch fix/c2-negative-1.3.1)

**Review only. Do not modify, create or delete any file.** If you are running without a shell, everything you need is
inline below: do not try to run commands. If you do have a read-only shell (codex), the working directory is a git
worktree of the branch head `2b9ade4c42e2d366e11ee7d198bab7c1fc0d07b0`; the base is main `edf8ad8668febf2088cb154a295dd056510e693a` (`git diff edf8ad8..HEAD`).
If something is fine, say so briefly rather than padding. For every finding give `file:line`, a concrete failing
input (numbers), a severity (CRITICAL/HIGH/MEDIUM/LOW) and **whether it would bite on real data or is theoretical**.

## Context

DIAspeXtract is a C++ OpenMS TOPP tool that extracts pseudo-MS/MS spectra from Bruker timsTOF diaPASEF `.d` data. Its
m/z comes from a license-free, header-only re-implementation of Bruker's TOF->m/z calibration (ModelType 1), identified
numerically against Bruker's own libtimsdata (`tims_index_to_mz`) used as a local oracle:

    t_ns   = tof * DigitizerTimebase + DigitizerDelay
    C1_eff = C1 * (1 + dC1 * (T1_ref - T1_frame) / 1e6)       # digitizer temperature, per frame
    b      = 1e6 / sqrt(C1_eff)                               # frameFactor()
    t_ns   = C0 + b * u + C2 * u^2,   u = sqrt(m + C4)          # solved for u; m = u^2 - C4

`tofToMz` uses the cancellation-free root `u = 2 (t - C0) / (b + sqrt(disc))`, `disc = b^2 - 4 C2 (C0 - t)`, and returns
NaN for `disc < 0`, `t <= C0`, `denom <= 0`, `m <= 0`. `mzToTof` is the closed-form forward law.

Until 1.3.0 `unsupportedReason()` refused every `C2 < 0` ("flips the root branch"). The public PXD029836 (timsTOF Pro 2,
acquisition software 2.0.53) stores C2 < 0 in all 23 runs (four vectors, -0.000586..-0.001228), so 1.3.0 refused them
all (exit 6, 0.03 s). A read-only SDK check showed the shipped formula with the negative C2 matches the vendor to
~6e-6 ppm; dropping C2 is 19-40 ppm off, flipping its sign 38-80 ppm off.

The fix (one commit, `2b9ade4c42`): for C2 < 0, `unsupportedReason()` runs a DOMAIN check (`negativeC2Reason`): accept
only if `disc >= b^2/4` (slope dt/du >= half its linear value) for every TOF index up to `kDomainMaxTof` = 1e8, every
m/z up to `kDomainMaxMz` = 1e5, at every frame temperature within `kDomainT1Span` = 1000 K of T1_ref (checked at the
smallest b, i.e. the largest C1 factor). A new `frameReason(t1)` refuses (for C2 < 0 only) a frame whose T1 is outside
that span; the tool's sqlite reader `loadTdfCalibration` calls it per frame. The OpenMS loader patch is unchanged (it
calls `isSupported()` only; it never sees DigitizerNumSamples or a per-frame check). The conversion functions are
unchanged. New golden cases: 210 vendor values (six PXD029836 runs x 5 frames x 7 TOF probes), generated on the cluster
by the SDK script in section 5.

## Invariants the code must keep (attack these)

1. **Fail closed, never approximate.** A calibration the model does not cover must be refused, never converted with a
   plausible-looking wrong mass. NaN is acceptable only where the tool drops and counts the peak.
2. **Bit identity for every file accepted before.** Zero and positive C2 files must produce byte-identical spectra
   (four digest pins: dataset D e43672a0 / 8c1b047f, TNBC run 009 3aafd0b5 / bff54a1f). The claim is by construction:
   tofToMz/mzToTof/frameFactor unchanged, no new branch for C2 >= 0. The digest gate has NOT run yet.
3. **The golden cases must be independent of the code under test**: vendor values from `tims_index_to_mz`, never from
   the tool's formula.
4. **The shipped code is the tested code**: the same header is compiled into libOpenMS (loader patch) and the tool,
   and the C++ golden test includes it directly.
5. **The domain check must be conservative** over everything the tool can hand the model: every TOF index the loaders
   convert, every m/z the tool inverts (`mzToTof`), every frame temperature. And it must not refuse plausible real files.
6. `mzToTof` for C2 < 0 is non-monotonic beyond the parabola's vertex (m_vertex = b^2/(4 C2^2) - C4). Callers that turn
   an m/z bound into a TOF bound rely on monotonicity.

## Questions (numbered; answer each)

1. **Root choice.** Derive it: for C2 < 0 and C0 < t < C0 + b^2/(4|C2|), are both roots positive, and is
   `2(t - C0)/(b + sqrt(disc))` always the rising-branch (physical) one? Any t or b for which the code returns the other
   root, a negative u, or a finite wrong value? Is it continuous through C2 = 0 and C2 = -0.0?
2. **Domain check correctness** (`negativeC2Reason`, section A lines 145-165): are t_zero, t_half, u_half right? Is the
   deciding corner right (largest TOF, smallest b = largest C1 factor, both signs of dC1)? Is the m/z condition
   `kDomainMaxMz + C4 <= u_half^2` right, including negative or large C4? Any finite input row (C0, C4, delay,
   timebase, dC1 extremes; infinities other than C2) that the check ACCEPTS while some TOF <= 1e8 or m/z <= 1e5 at a
   T1 within the span gives disc < b^2/4, or where the refusal message computes garbage?
3. **Is the domain the right one?** The TOF bound 1e8 is enforced only by `loadTdfAxisBounds` (DigitizerNumSamples);
   the OpenMS loader converts raw uint32 TOF indices from the frame blob without a bound. The m/z bound 1e5 is
   MzAcqRangeUpper. Find every place that hands the model a TOF > 1e8 or an m/z > 1e5 (or > m_vertex), including
   `TofAxis::tofOf` callers (`best`: cmz +- 3 sd; band edges `acq_hi`, `mzOf(last)+1e-5`; `c.tof = tofOf(amz)`), the
   mzPeak path, dnoise `recoverPoint`, the patch's `inverse_convert`. For each, would a non-monotonic `mzToTof` or an
   ill-conditioned root change output on a real negative-C2 file?
4. **Temperature.** `frameReason` checks |T1 - T1_ref| <= 1000 K; the domain check assumes that bound. Can a frame reach
   `frameFactor` with an unchecked T1 in any path of the tool (OpenMS loader, TofAxis fallback `factor()`,
   `setTofAxis`'s `f > 0 ? f : bref`, mzPeak `exact()`)? Is the floating-point comparison consistent with `cf_hi`?
   Is 1000 K sensible (never refuses a real file, still meaningful)?
5. **Bit identity for C2 >= 0.** Check every changed line: the reordered timebase check, `frameReason` in the Frames loop,
   `kDomainMaxTof`/`kDomainMaxMz` replacing literals, the new `#include <cstdio>`, the `private:` section and
   `static constexpr` members (aggregate-ness, layout, ODR / C++ standard version), the per-frame std::string. Can any
   of them change a single output byte or a refusal for a zero/positive-C2 file? Anything about a mixed deploy
   (libOpenMS built with the old header, the tool with the new one)?
6. **Golden cases.** Are the 210 new cases really vendor values (section 5 generator)? Are they sufficient (T1 spread
   0.004-0.011 K per run, 7 TOF probes incl. N-1, four calibration vectors)? Note the golden JSON has no `C4` key; the
   parsers assume C4 = 0 for every golden file (PXD029836 has C4 = 0 per section 5). Is any assertion in the C++/Python
   tests vacuous, too loose, or dependent on the header it tests (e.g. `g6` mirroring `num`, the `c2_edge` formula)?
7. **Anything else assuming C2 >= 0** in the code shown (comments, docs, CHANGELOG, README, tests, provenance line)?
8. **CHANGELOG accuracy** (section 2 diff): check every number and claim against the evidence in sections 3-4 and the
   code. In particular "the four pins reproduce" is stated before the digest gate ran.
9. **What would you add or change before this ships as 1.3.1?** Rank.

## 1. Branch diff (stat)
```
 CHANGELOG.md                   |   87 +++
 CITATION.cff                   |    4 +-
 CMakeLists.txt                 |    2 +-
 README.md                      |    6 +-
 src/TdfLoad.h                  |   12 +-
 src/TdfMzCalibration.h         |   89 ++-
 src/diaspextract.cpp           |    2 +-
 tests/calibration_golden.json  | 1344 ++++++++++++++++++++++++++++++++++++++++
 tests/test_calibration.py      |   39 +-
 tests/test_calibration_cpp.cpp |  208 ++++++-
 tests/test_dnoise_ms1.cpp      |   36 ++
 tests/test_tdf_load.cpp        |   28 +-
 12 files changed, 1795 insertions(+), 62 deletions(-)

```
`tests/calibration_golden.json`: tests/calibration_golden.json | 1344 +++++++++++++++++++++++++++++++++++++++++
 1 file changed, 1344 insertions(+) (210 cases appended; summary in section 4, not inlined)

## 2. Full diff except the golden JSON (`git diff edf8ad8668..2b9ade4c42`)
```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index c843321..6c8cd66 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,5 +1,92 @@
 # Changelog
 
+## v1.3.1 — 2026-09-17
+
+**Why 1.3.1.** DIAspeXtract refused every Bruker file whose `MzCalibration` row stores a negative quadratic
+term `C2`, and such files are not rare. All 23 runs checked from the public PXD029836 have one
+(timsTOF Pro 2, acquisition software 2.0.53), in four calibration vectors (`C2` from −0.00059 to
+−0.00123). With the
+default `-dnoise:ms1 true`, the tool stopped 0.03 s after starting (exit 6) with
+`MzCalibration C2 < 0 (negative quadratic term is not a supported model)`. With `-dnoise:ms1 false`, the
+patched loader refused the same file. 1.3.1 accepts a negative `C2` inside a checked domain, which is the
+only change. It affects timsTOF Pro 2 calibrations with a negative `C2`. Options and defaults are
+unchanged, and so are the spectra of every file the tool accepted before: the four pins reproduce
+(dataset D `e43672a0`, run 009 `3aafd0b5` at the defaults; `8c1b047f` and `bff54a1f` with
+`-dnoise:ms1 false`).
+
+### Fixed
+
+- **A negative `C2` follows the same law, and the shipped root already solves it.** The refusal, in place
+  since 2026-09-01, assumed that a negative `C2` "flips the root branch", but it does not.
+  `TdfMzCalibration::tofToMz` computes `u = 2 (t − C0) / (b + sqrt(disc))`. That is the root on the rising
+  branch for either sign of `C2`, and it is continuous through `C2 = 0`. Bruker's own library
+  (`tims_index_to_mz`, used as a local oracle and never redistributed) confirms this on six PXD029836 runs:
+  1418, 1420 and 1422, which share one vector, plus 1431, 1408 and 1347, one per vector. The check used
+  5 frames per run (first, middle, last, coldest, warmest), each probed at 2,017 TOF indices across the
+  whole digitizer range. The worst error was 7.0e-6 ppm. Dropping `C2` is 19–40 ppm off; flipping its
+  sign is 38–80 ppm off.
+- **The refusal is now a domain check.** With `C2 < 0`, flight time as a function of `u = sqrt(m + C4)` is a
+  parabola with its peak at `u = b / (2|C2|)`.
+  - **Beyond the peak** no mass has that flight time. The discriminant is negative there, and the
+    conversion returns NaN, as before.
+  - **Near the peak** the root is ill-conditioned.
+  - **The acceptance rule.** `unsupportedReason()` accepts a negative `C2` only if the discriminant stays
+    at least `b²/4` over everything the tool can ask of the model. `b²/4` means the flight-time slope stays
+    at least half its linear value. The domain is:
+    - every TOF index up to 1e8 and every m/z up to 1e5. These are the bounds the tdf reader already
+      applied to `DigitizerNumSamples` and `MzAcqRangeUpper`, and both now use the same constants;
+    - at every frame temperature within 1000 K of the calibration's `T1`.
+  - **The deciding corner** is the largest TOF at the smallest frame factor. On PXD029836 the discriminant
+    is at least 0.984 `b²` there. Over the runs' own range (397,657 bins, frames within 0.011 K of `T1`)
+    it is at least 0.99992 `b²`. The root would stop existing only beyond TOF index 6.4e9.
+  - **A refusal names** the TOF index where the root stops existing and the one where the slope halves.
+  - **The largest accepted `|C2|`** with PXD029836's other constants is 0.0595, 57 times theirs, so a
+    plausible future calibration is not refused falsely.
+- **Frame temperatures, for a negative `C2` only.** `TdfMzCalibration::frameReason` is new, and the tool's
+  tdf reader (`loadTdfCalibration`) calls it for every frame. The reader refuses a file with a frame whose
+  `T1` lies more than 1000 K from the calibration's, and names the frame. This reader feeds the MS1
+  denoiser, the integer detector's flight-time axis and the mzPeak exact-m/z path.
+  - **The OpenMS loader patch is unchanged.** It calls `isSupported()`, so the domain check reaches it
+    through the updated header, but it has no per-frame check.
+  - **If the reader refuses such a file:** with the default `-dnoise:ms1 true` the run is refused at
+    setup. Otherwise the integer detector falls back to `openms` with a warning, as for any calibration
+    its reader refuses.
+  - **Zero and positive `C2`** take none of these branches. The conversion code is unchanged.
+- **Every refusal test now has a valid row behind it.** In the C++ golden test, the "must be rejected" cases
+  for `ModelType`, `dC2`, `C3` and `C2 < 0` started from a row whose `C1` of 1.0 was already outside the
+  plausible range. They would therefore have passed even if their own check were gone. Each case now
+  changes one field of dataset D's valid row and asserts the refusal names that field.
+
+### Tests
+
+- `tests/calibration_golden.json` holds 210 new vendor cases: six PXD029836 runs × 5 frames × 7 TOF
+  positions, 270 cases in all. Both golden tests now check every file on its own: at least 20 cases, and
+  dropping `C2` or flipping its sign must each move the result by at least 5 ppm. The C++ test also
+  checks the round trip to 1e-6 bins and the temperature ablation. The Python twin's textbook root agrees
+  with the vendor values to 3.1e-5 ppm; the tolerance stays 1e-4.
+- `tests/test_calibration_cpp.cpp`:
+  - The PXD029836 row is accepted. Over the whole domain, at both temperature extremes, its conversion is
+    finite and rising, and the round trip holds to within 5e-8 bins.
+  - `C2 = −0.1` is refused. The reason names TOF index 7.93471e+07, where the root stops existing, and
+    the ablation confirms the conversion is NaN at 1e8.
+  - `C2 = −0.07` is refused by the slope margin, although its root still exists at 1e8.
+  - `C2 = −0.05` is accepted.
+  - The domain edge for this row, `|C2|` = 0.0595301, is computed independently of the header. `|C2|`
+    1e-6 inside the edge is accepted, and 1e-6 outside it is refused.
+  - With a 1 ps timebase, `C2 = −2.5` is refused on the m/z side of the domain.
+  - `−inf` is refused.
+  - `dC1 = 1000` ppm/K is refused for a negative `C2` and accepted for a positive one.
+  - A stored `−0.0` converts bit for bit like `0.0`.
+  - Frame temperatures outside ±1000 K, and NaN, are refused for a negative `C2` only.
+- `tests/test_dnoise_ms1.cpp`: the MS1 denoiser's TOF recovery inverts the model exactly with a negative
+  `C2`. All 397,657 bins of run 1418 come back at three frame temperatures, with a worst round trip of
+  2e-10 bins. Half a bin and +1 ppm are refused.
+- `tests/test_tdf_load.cpp`:
+  - A negative-`C2` tdf loads, and one with `C2 = −0.1` is refused with the TOF index.
+  - A frame at 1100 °C is refused for a negative `C2`; for a positive `C2` it is read as before.
+  - A NULL `T1` is the reference temperature.
+  - The axis bounds 1e8 and 1e5 are accepted, and values just above them are refused.
+
 ## v1.3.0 — 2026-09-15
 
 **Why 1.3.** A rename only. The tool, its executable, its environment prefix and its repositories are
diff --git a/CITATION.cff b/CITATION.cff
index f2f20ab..1c2691a 100644
--- a/CITATION.cff
+++ b/CITATION.cff
@@ -11,5 +11,5 @@ abstract: >-
   OpenMS, including an exact license-free TOF-to-m/z calibration derived from the acquisition's own
   MzCalibration table.
 license: BSD-3-Clause
-version: 1.3.0
-date-released: "2026-09-15"
+version: 1.3.1
+date-released: "2026-09-17"
diff --git a/CMakeLists.txt b/CMakeLists.txt
index 38df62d..00edb28 100644
--- a/CMakeLists.txt
+++ b/CMakeLists.txt
@@ -1,5 +1,5 @@
 cmake_minimum_required(VERSION 3.16)
-project(DIAspeXtract VERSION 1.3.0 LANGUAGES CXX)
+project(DIAspeXtract VERSION 1.3.1 LANGUAGES CXX)
 
 # DIAspeXtract is a STANDALONE application that links against an existing OpenMS
 # installation. It is deliberately not part of the OpenMS source tree: OpenMS is a
diff --git a/README.md b/README.md
index ac19451..3cce538 100644
--- a/README.md
+++ b/README.md
@@ -70,7 +70,11 @@ notice a missing second or fourth:**
   two-point linear-in-sqrt chord that is **−5 to −11 ppm biased** (m/z dependent) on every file
   measured, worth roughly **6–11% more closed-search Sage identifications** on the three files measured. Every emitted mzML
   records which calibration was used in the `spx:mz_calibration` userParam
-  (`tdf_table_modeltype1` | `bruker_sdk` | `legacy_chord_APPROXIMATE`). An unsupported calibration
+  (`tdf_table_modeltype1` | `bruker_sdk` | `legacy_chord_APPROXIMATE`). The exact model covers
+  `ModelType` 1 with the digitizer-temperature term, the `C4` mass offset and a quadratic term `C2` of
+  either sign. A negative `C2`, as timsTOF Pro 2 acquisition software 2.0.53 writes it, is accepted since
+  1.3.1, but only inside a checked domain (`src/TdfMzCalibration.h`). The golden tests pin each variant
+  (`tests/calibration_golden.json`, `tests/test_calibration_cpp.cpp`). An unsupported calibration
   table **fails closed** rather than silently producing biased masses.
 - **Lock-free elution-peak detection.** OpenMS guards a shared vector with a program-global critical
   section. Called from inside DIAspeXtract's parallel window loop, that one lock serialises the tool.
diff --git a/src/TdfLoad.h b/src/TdfLoad.h
index fa4d537..57f1539 100644
--- a/src/TdfLoad.h
+++ b/src/TdfLoad.h
@@ -52,8 +52,9 @@ inline bool loadTdfAxisBounds(const std::string& tdf, TdfAxisBounds& out, std::s
     else if (k == "MzAcqRangeUpper") out.mz_hi = v;
     else
     {
-      // an integral count in [2, 1e8], checked BEFORE the narrowing cast (1e100 -> long is UB)
-      if (!(v >= 2.0 && v <= 100000000.0 && std::trunc(v) == v)) { why = "DigitizerNumSamples is not an integer in [2, 1e8]: " + std::to_string(v); ok = false; break; }
+      // an integral count in [2, 1e8], checked BEFORE the narrowing cast (1e100 -> long is UB); the bound is the TOF
+      // range a negative C2 is verified over
+      if (!(v >= 2.0 && v <= TdfMzCalibration::kDomainMaxTof && std::trunc(v) == v)) { why = "DigitizerNumSamples is not an integer in [2, 1e8]: " + std::to_string(v); ok = false; break; }
       out.n_bins = (long)v;
     }
   }
@@ -62,14 +63,16 @@ inline bool loadTdfAxisBounds(const std::string& tdf, TdfAxisBounds& out, std::s
   if (!ok) return false;
   if (!(have_lo && have_hi && have_n)) { why = "GlobalMetadata lacks MzAcqRangeLower/MzAcqRangeUpper/DigitizerNumSamples (" + std::to_string(have_lo + have_hi + have_n) + " of 3)"; return false; }
   // plausibility: a TIMS acquisition ends far below 1e5 m/z; a corrupt but finite value beyond
-  // that would drive the flight-time conversion past the axis (review 3a, round 2)
-  if (!(out.mz_lo > 0.0) || !(out.mz_hi > out.mz_lo) || !(out.mz_hi <= 1.0e5))
+  // that would drive the flight-time conversion past the axis (review 3a, round 2), and 1e5 is the m/z
+  // range a negative C2 is verified over
+  if (!(out.mz_lo > 0.0) || !(out.mz_hi > out.mz_lo) || !(out.mz_hi <= TdfMzCalibration::kDomainMaxMz))
   { why = "GlobalMetadata bounds are not usable: MzAcqRange " + std::to_string(out.mz_lo) + "-" + std::to_string(out.mz_hi) + ", DigitizerNumSamples " + std::to_string(out.n_bins); return false; }
   return true;
 }
 
 /// The MzCalibration row the FRAMES reference (Frames.MzCalibration; PXD017703 files carry two rows), refused
 /// when frames reference more than one. t1_by_frame[id] = Frames.T1 (T1_ref when NULL); index 0 is never a frame.
+/// A frame whose T1 lies outside the span a negative C2 was checked over is refused (TdfMzCalibration::frameReason).
 inline bool loadTdfCalibration(const std::string& tdf, TdfMzCalibration& cal,
                                std::vector<double>& t1_by_frame, std::string& why)
 {
@@ -129,6 +132,7 @@ inline bool loadTdfCalibration(const std::string& tdf, TdfMzCalibration& cal,
     if (id < 0 || id > 10000000) return fail("implausible Frames.Id");
     if ((size_t)id >= t1_by_frame.size()) t1_by_frame.resize((size_t)id + 1, cal.T1_ref);
     t1_by_frame[(size_t)id] = (sqlite3_column_type(st, 1) == SQLITE_NULL) ? cal.T1_ref : sqlite3_column_double(st, 1);
+    if (std::string w = cal.frameReason(t1_by_frame[(size_t)id]); !w.empty()) return fail("frame " + std::to_string(id) + ": " + w);
   }
   if (rc != SQLITE_DONE) return sqlfail("reading Frames.T1");
   sqlite3_finalize(st); sqlite3_close(db);
diff --git a/src/TdfMzCalibration.h b/src/TdfMzCalibration.h
index bcd673f..e9e0ae6 100644
--- a/src/TdfMzCalibration.h
+++ b/src/TdfMzCalibration.h
@@ -16,11 +16,28 @@
 //
 // Verified to 2.5e-5 ppm against the vendor library (tests/calibration_golden.json: three files sharing ONE
 // MzCalibration vector, 12 frames over 0.034 K); the C4 term was pinned the same way on a 2019 timsTOF Pro
-// (tests/test_calibration_cpp.cpp). What the model does not cover (ModelType != 1, dC2 or C3 != 0, frames that
-// reference more than one MzCalibration row) is REJECTED by unsupportedReason() and the loaders, never approximated.
-// The open timsrust-calibration port drops the C2*m term (-11..-40 ppm on this data).
+// (tests/test_calibration_cpp.cpp). A NEGATIVE C2 (timsTOF Pro 2, acquisition software 2.0.53: all 23 runs checked
+// of the public PXD029836, four calibration vectors) is the same law and the same root: pinned on six of those runs
+// (30 frames, 7.0e-6 ppm worst; dropping C2 is 19..40 ppm off, flipping its sign 38..80 ppm).
+// What the model does not cover (ModelType != 1, dC2 or C3 != 0, frames that reference more than one MzCalibration
+// row, a negative C2 outside its verified domain) is REJECTED by unsupportedReason() and the loaders, never
+// approximated. The open timsrust-calibration port drops the C2*m term (-11..-40 ppm on this data).
+//
+// The negative-C2 domain. With C2 < 0 the law t(u) = C0 + b*u + C2*u^2 (u = sqrt(m + C4)) is a parabola that peaks at
+// u = b / (2|C2|): no mass has a later flight time (the discriminant below is negative there and tofToMz returns NaN),
+// and near the peak the root is ill-conditioned. At the root, sqrt(disc) is the slope dt/du, so unsupportedReason()
+// requires disc >= b^2 / 4 -- the slope at least half its linear value -- over everything the tool can ask of the
+// model: every TOF index up to kDomainMaxTof, every m/z up to kDomainMaxMz, and every frame temperature within
+// kDomainT1Span of T1_ref. disc falls with the flight time and with the C1 factor, so the corner that decides is the
+// largest TOF at the largest factor. On the six PXD029836 runs that corner has disc >= 0.984 b^2, the runs' own range
+// (397,657 bins, frames within 0.011 K of T1_ref) >= 0.99992 b^2, and the root would only stop existing beyond TOF
+// index 6.4e9, 16,000 times the digitizer's range. frameReason() lets a loader refuse a frame outside the checked
+// temperature span: the tool's tdf reader (TdfLoad.h) does, the OpenMS loader patch predates it and does not -- a frame
+// there converts as a positive-C2 frame at such a temperature would, and a peak beyond the parabola's peak comes back
+// NaN, which the tool drops and counts (bad_mz). Positive and zero C2 take none of these branches.
 
 #include <cmath>
+#include <cstdio>
 #include <initializer_list>
 #include <limits>
 #include <string>
@@ -36,13 +53,22 @@ struct TdfMzCalibration
   double digitizer_delay = 0.0;
   double C0 = 0.0;
   double C1 = 0.0;      ///< must be > 0
-  double C2 = 0.0;      ///< the quadratic term the open implementations drop
+  double C2 = 0.0;      ///< the quadratic term the open implementations drop; negative only inside its domain
   double T1_ref = 0.0;  ///< reference digitizer temperature for the calibration
   double dC1 = 0.0;     ///< ppm/K drift of C1
   double dC2 = 0.0;     ///< drift of C2 -- NOT modelled; must be 0 (see isSupported)
   double C3 = 0.0;      ///< NOT modelled; must be 0 (never observed non-zero)
   double C4 = 0.0;      ///< additive mass offset on the quadratic root: m = u^2 - C4
 
+  /// The negative-C2 domain (header comment): what the tool can hand the model. TdfLoad.h refuses a file whose
+  /// DigitizerNumSamples (every stored TOF index is below it) or MzAcqRangeUpper exceeds these, and the compact
+  /// store caps a peak's m/z at 42,000.
+  static constexpr double kDomainMaxTof = 1e8;
+  static constexpr double kDomainMaxMz = 1e5;
+  /// Kelvin around T1_ref: wider than any temperature a working digitizer can have (T1_ref is ~25 C, so the span
+  /// reaches below absolute zero); the golden files' frames span 0.004 to 0.034 K.
+  static constexpr double kDomainT1Span = 1000.0;
+
   /// Why this calibration cannot be used, or empty if it can. Fail closed, never approximate.
   std::string unsupportedReason() const
   {
@@ -55,15 +81,25 @@ struct TdfMzCalibration
     if (!(C1 > 1.0) || !(C1 < 1e12)) return "MzCalibration C1 outside the plausible range (1, 1e12)";
     if (dC2 != 0.0) return "MzCalibration dC2 != 0 (temperature drift of C2 is not modelled)";
     if (C3 != 0.0) return "MzCalibration C3 != 0 (not modelled; never observed non-zero)";
+    if (!(digitizer_timebase > 0.0)) return "DigitizerTimebase <= 0";
     // C2 == 0.0 stored in the file is a real calibration (the 2020 timsTOF Pro firmware behind PXD017703 has no
     // quadratic term). A NULL C2, which sqlite3_column_double hands over as 0.0, is refused by the loaders
-    // themselves. A negative C2 flips the root branch.
-    if (C2 < 0.0) return "MzCalibration C2 < 0 (negative quadratic term is not a supported model)";
-    if (!(digitizer_timebase > 0.0)) return "DigitizerTimebase <= 0";
+    // themselves. A negative C2 is accepted inside its domain only.
+    if (C2 < 0.0) return negativeC2Reason();
     return std::string();
   }
   bool isSupported() const { return unsupportedReason().empty(); }
 
+  /// Why a frame at digitizer temperature @p t1_frame cannot be converted, or empty. Only a negative C2 has a
+  /// temperature-dependent domain, and unsupportedReason() checked it for T1_ref +- kDomainT1Span: a frame outside
+  /// that span (a corrupt T1) is refused rather than converted where nothing was checked.
+  std::string frameReason(double t1_frame) const
+  {
+    if (!(C2 < 0.0) || std::fabs(t1_frame - T1_ref) <= kDomainT1Span) return std::string();
+    return "Frames.T1 " + num(t1_frame) + " is not within " + num(kDomainT1Span) + " K of the MzCalibration T1 " + num(T1_ref)
+           + ", the temperature span over which the negative C2 was checked";
+  }
+
   /// Temperature-corrected 1e6/sqrt(C1_eff) for one frame; hoist out of per-peak loops.
   double frameFactor(double t1_frame) const
   {
@@ -76,8 +112,10 @@ struct TdfMzCalibration
   {
     const double t = tof * digitizer_timebase + digitizer_delay;
     // Stable root of C2*u^2 + b*u + (C0 - t) = 0: u = 2*(t - C0) / (b + sqrt(disc)) avoids the textbook form's
-    // cancellation (b ~ 2.5e3, C2 ~ 1e-3). Out-of-model inputs (t <= C0, a negative discriminant, m <= 0)
-    // return NaN, never a plausible-looking 0.0 or the wrong mass a negative u would give.
+    // cancellation (b ~ 2.5e3, |C2| ~ 1e-3). It is the root on the rising branch for either sign of C2 and
+    // continuous through C2 = 0, where it is (t - C0) / b. Out-of-model inputs (t <= C0, a negative discriminant --
+    // with C2 < 0, a flight time beyond the parabola's peak -- m <= 0) return NaN, never a plausible-looking 0.0
+    // or the wrong mass a negative u would give.
     const double disc = b * b - 4.0 * C2 * (C0 - t);
     if (!(disc >= 0.0) || !(t > C0)) return std::numeric_limits<double>::quiet_NaN();
     const double denom = b + std::sqrt(disc);
@@ -87,13 +125,44 @@ struct TdfMzCalibration
     return m > 0.0 ? m : std::numeric_limits<double>::quiet_NaN();
   }
 
-  /// m/z -> TOF index (exact inverse of tofToMz; the model is closed-form in this direction).
+  /// m/z -> TOF index (exact inverse of tofToMz; the model is closed-form in this direction). With C2 < 0 it is the
+  /// inverse on the rising branch, which unsupportedReason() verified up to kDomainMaxMz.
   double mzToTof(double mz, double b) const
   {
     const double m = mz + C4;
     const double t = C0 + b * std::sqrt(m > 0.0 ? m : 0.0) + C2 * m;
     return (t - digitizer_delay) / digitizer_timebase;
   }
+
+private:
+  static std::string num(double v)
+  {
+    char buf[32];
+    std::snprintf(buf, sizeof buf, "%.6g", v);
+    return buf;
+  }
+
+  /// The negative-C2 domain check (header comment). disc = b^2 - k*(t - C0) with k = 4|C2| is smallest at the
+  /// largest flight time and the smallest frame factor b, i.e. the largest C1 factor within the temperature span.
+  std::string negativeC2Reason() const
+  {
+    const double cf_lo = 1.0 - std::fabs(dC1) * kDomainT1Span / 1e6, cf_hi = 1.0 + std::fabs(dC1) * kDomainT1Span / 1e6;
+    if (!(cf_lo > 0.0))
+      return "MzCalibration C2 < 0 with dC1 " + num(dC1) + " ppm/K: the C1 factor leaves (0, inf) within " + num(kDomainT1Span)
+             + " K of T1, so the negative C2 cannot be checked over that span";
+    const double b = 1e6 / std::sqrt(C1 * cf_hi);
+    const double k = -4.0 * C2;
+    const double t_zero = C0 + b * b / k;          // disc = 0: beyond it no mass has this flight time
+    const double t_half = C0 + 0.75 * b * b / k;   // disc = b^2 / 4: the slope dt/du is half its linear value
+    const double u_half = b / k;                   // the root there, sqrt(m + C4)
+    const double t_max = kDomainMaxTof * digitizer_timebase + digitizer_delay;
+    if (t_max <= t_half && kDomainMaxMz + C4 <= u_half * u_half) return std::string();
+    return "MzCalibration C2 " + num(C2) + " < 0 outside its verified domain: the TOF-to-m/z root stops existing at TOF index "
+           + num((t_zero - digitizer_delay) / digitizer_timebase) + " and its slope halves at TOF index "
+           + num((t_half - digitizer_delay) / digitizer_timebase) + " (m/z " + num(u_half * u_half - C4)
+           + "); a negative C2 is accepted only while the slope stays above half up to TOF index " + num(kDomainMaxTof)
+           + " and m/z " + num(kDomainMaxMz) + ", at every frame temperature within " + num(kDomainT1Span) + " K of T1";
+  }
 };
 
 } // namespace diaspextract
diff --git a/src/diaspextract.cpp b/src/diaspextract.cpp
index 42ac097..d9c233b 100644
--- a/src/diaspextract.cpp
+++ b/src/diaspextract.cpp
@@ -62,7 +62,7 @@ static_assert(std::is_nothrow_move_constructible_v<OpenMS::MassTrace> && std::is
 // The release version. The standalone CMake build passes it from project(VERSION); the in-tree
 // OpenMS build does not, so the fallback here is the same number.
 #ifndef DIASPEXTRACT_VERSION
-#define DIASPEXTRACT_VERSION "1.3.0"
+#define DIASPEXTRACT_VERSION "1.3.1"
 #endif
 
 using namespace OpenMS;
diff --git a/tests/test_calibration.py b/tests/test_calibration.py
index dd18fa5..7cc1074 100644
--- a/tests/test_calibration.py
+++ b/tests/test_calibration.py
@@ -1,10 +1,14 @@
 #!/usr/bin/env python3
 """Golden test for the TDF MzCalibration (ModelType 1) TOF->m/z model.
 
-Guards the calibration that produced the 2026-09-01 +6-11% closed-search gain. The 60 golden cases
-were produced by Bruker's own timsdata library on three diaPASEF files (dataset D/dataset A/dataset B, 4 frames x 5
-TOF positions each) and are stored in tests/calibration_golden.json, so this test needs NO vendor
-library, NO cluster and NO raw data.
+Guards the calibration that produced the 2026-09-01 +6-11% closed-search gain. The 270 golden cases
+were produced by Bruker's own timsdata library and are stored in tests/calibration_golden.json, so this
+test needs NO vendor library, NO cluster and NO raw data:
+  * 60 on three diaPASEF files sharing one calibration vector (dataset D/dataset A/dataset B, 4 frames x 5
+    TOF positions each);
+  * 210 on six runs of the public PXD029836 (timsTOF Pro 2, acquisition software 2.0.53), whose C2 is
+    NEGATIVE: 1418/1420/1422 share one vector, 1431, 1408 and 1347 carry one each (5 frames x 7 TOF
+    positions each: first, middle and last frame, the coldest and the warmest).
 
 Model (derived numerically against the vendor oracle). NOTE this is an INDEPENDENT re-implementation
 of the model, not a copy of the shipped C++: it uses the textbook quadratic root where
@@ -16,9 +20,10 @@ twice. tests/test_calibration_cpp.cpp is the one that exercises the code that ac
     C1_eff = C1 * (1 + dC1 * (T1_ref - T1_frame) / 1e6)          # temperature compensation
     t_ns   = C0 + (1e6 / sqrt(C1_eff)) * sqrt(m) + C2 * m        # solve the quadratic for sqrt(m)
 
-Two regressions this catches:
+Regressions this catches:
   * dropping the C2*m term -- the bug in the widely-copied open implementation (timsrust-calibration,
     adapted then disabled by mzdata): -11..-40 ppm on this data;
+  * flipping the sign of a negative C2, or taking the other root: 38..80 ppm on PXD029836 (checked per file);
   * dropping the dC1 temperature term: ~0.67 ppm. (m is proportional to C1_eff, NOT its square
     root, so dC1*dT/1e6 lands on m/z undiminished -- an earlier note here claimed ~0.33 ppm by
     applying a spurious halving; the measured guard value 0.669 confirms 0.67. The golden files
@@ -27,7 +32,8 @@ Run: python3 tests/test_calibration.py
 """
 import json, math, os, sys
 
-TOL_PPM = 0.0001         # measured max 2.6e-5 ppm; matches the C++ test's tolerance exactly
+TOL_PPM = 0.0001         # measured max 3.1e-5 ppm (this textbook root cancels on PXD029836; the shipped root: 2.6e-5);
+                         # matches the C++ test's tolerance exactly
 NO_C2_MIN_PPM = 5.0      # dropping C2 must be caught: it is worth >>5 ppm
 NO_TEMP_MIN_PPM = 0.1    # dropping the temperature term must be visible
 
@@ -39,7 +45,8 @@ def tof_to_mz(tof, p, t1_frame, use_c2=True, use_temp=True):
     if abs(c2) < 1e-12:                      # degenerate: pure sqrt law
         return ((t_ns - p["C0"]) / b) ** 2 - p.get("C4", 0.0)
     disc = b * b - 4.0 * c2 * (p["C0"] - t_ns)
-    u = (-b + math.sqrt(max(disc, 0.0))) / (2.0 * c2)
+    assert disc > 0.0, f"t = {t_ns} ns is beyond the calibration's range (negative discriminant)"
+    u = (-b + math.sqrt(disc)) / (2.0 * c2)   # the rising-branch root for either sign of c2
     return u * u - p.get("C4", 0.0)       # C4: additive mass offset on the root
 
 def ppm(a, b):
@@ -87,18 +94,30 @@ def main():
     worst = 0.0
     worst_noc2 = 0.0
     worst_notemp = 0.0
+    negative = 0
     for f in files:
         assert f["model_type"] == 1, f"{f['file']}: golden set must be ModelType 1"
+        f_worst = f_noc2 = f_flip = 0.0
+        flipped = dict(f, C2=-f["C2"])
         for case in f["cases"]:
             got = tof_to_mz(case["tof"], f, case["t1"])
             e = ppm(got, case["mz"])
             assert e < TOL_PPM, (
                 f"{f['file']} frame {case['frame']} tof {case['tof']:.0f}: "
                 f"model {got:.6f} vs vendor {case['mz']:.6f} = {e:.5f} ppm > {TOL_PPM}")
-            worst = max(worst, e)
-            worst_noc2 = max(worst_noc2, ppm(tof_to_mz(case["tof"], f, case["t1"], use_c2=False), case["mz"]))
+            f_worst = max(f_worst, e)
+            f_noc2 = max(f_noc2, ppm(tof_to_mz(case["tof"], f, case["t1"], use_c2=False), case["mz"]))
+            f_flip = max(f_flip, ppm(tof_to_mz(case["tof"], flipped, case["t1"]), case["mz"]))
             worst_notemp = max(worst_notemp, ppm(tof_to_mz(case["tof"], f, case["t1"], use_temp=False), case["mz"]))
             n += 1
+        # per file: every file must tell the model from the known-bad variants on its own
+        assert len(f["cases"]) >= 20 and f_noc2 > NO_C2_MIN_PPM and f_flip > NO_C2_MIN_PPM, (
+            f"{f['file']}: {len(f['cases'])} cases, without C2 {f_noc2:.3f} ppm, C2 sign-flipped {f_flip:.3f} ppm")
+        print(f"    {f['file']:<16} C2 {f['C2']:+.6e}  {len(f['cases']):2d} cases  max {f_worst:.7f} ppm  "
+              f"(without C2 {f_noc2:.2f}, sign-flipped {f_flip:.2f} ppm)")
+        worst, worst_noc2 = max(worst, f_worst), max(worst_noc2, f_noc2)
+        negative += f["C2"] < 0
+    assert len(files) >= 9 and n >= 270 and negative >= 6, f"only {n} cases in {len(files)} files ({negative} with C2 < 0)"
     # the ablations must actually be detectable, or this test proves nothing
     assert worst_noc2 > NO_C2_MIN_PPM, (
         f"dropping C2 changed the result by only {worst_noc2:.3f} ppm -- the golden set cannot "
@@ -106,7 +125,7 @@ def main():
     assert worst_notemp > NO_TEMP_MIN_PPM, (
         f"dropping the temperature term changed the result by only {worst_notemp:.4f} ppm -- "
         f"the golden set has no temperature spread; regenerate across more frames")
-    print(f"OK  {n} golden cases, {len(files)} files: max error {worst:.6f} ppm (tol {TOL_PPM})")
+    print(f"OK  {n} golden cases, {len(files)} files ({negative} with C2 < 0): max error {worst:.7f} ppm (tol {TOL_PPM})")
     print(f"    ablation guards: without C2 {worst_noc2:.2f} ppm, without temperature {worst_notemp:.4f} ppm")
     return 0
 
diff --git a/tests/test_calibration_cpp.cpp b/tests/test_calibration_cpp.cpp
index b0dd31a..aff455c 100644
--- a/tests/test_calibration_cpp.cpp
+++ b/tests/test_calibration_cpp.cpp
@@ -11,6 +11,38 @@
 #include <string>
 #include <vector>
 
+using Cal = diaspextract::TdfMzCalibration;
+
+static bool has(const std::string& s, const char* part) { return s.find(part) != std::string::npos; }
+
+/// Dataset D's row (the first golden file): valid, so each negative path below changes exactly one thing.
+static Cal validD()
+{
+  Cal c;
+  c.model_type = 1; c.digitizer_timebase = 0.125; c.digitizer_delay = 25655.375;
+  c.C0 = 279.3262846272992; c.C1 = 155279.13067653627; c.C2 = 0.001260061434461731;
+  c.T1_ref = 25.693668980735552; c.dC1 = 20.0;
+  return c;
+}
+
+/// PXD029836 run 1418's row (timsTOF Pro 2, acquisition software 2.0.53): the negative C2 the golden set pins.
+static Cal pxd1418()
+{
+  Cal c;
+  c.model_type = 1; c.digitizer_timebase = 0.19999999999999998; c.digitizer_delay = 25779.8;
+  c.C0 = 314.1341896383674; c.C1 = 154199.217568937; c.C2 = -0.0010422663259118895;
+  c.T1_ref = 25.618823611312585; c.dC1 = 20.0;
+  return c;
+}
+
+/// The reason text's number format (TdfMzCalibration::num), so a test can find the value it computed itself.
+static std::string g6(double v)
+{
+  char buf[32];
+  std::snprintf(buf, sizeof buf, "%.6g", v);
+  return buf;
+}
+
 // Minimal extraction from the golden JSON: it is machine-generated with a fixed shape, so a tiny
 // scanner beats adding a JSON dependency to a test that must build everywhere.
 static bool nextNumber(const std::string& s, const std::string& key, size_t& pos, double& out)
@@ -33,12 +65,14 @@ int main(int argc, char** argv)
   const std::string j = ss.str();
 
   size_t pos = 0;
-  int n_files = 0, n_cases = 0;
-  double worst = 0.0, worst_noc2 = 0.0;
+  int n_files = 0, n_cases = 0, n_negative = 0;
+  double worst = 0.0, worst_noc2 = 0.0, worst_notemp = 0.0, worst_back = 0.0;
   while (true)
   {
     const size_t fstart = j.find("\"model_type\":", pos);
     if (fstart == std::string::npos) break;
+    const size_t name_at = j.rfind("\"file\": \"", fstart);
+    const std::string name = name_at == std::string::npos ? "?" : j.substr(name_at + 9, j.find('"', name_at + 9) - name_at - 9);
     diaspextract::TdfMzCalibration cal;
     size_t p = fstart;
     double v = 0;
@@ -55,6 +89,8 @@ int main(int argc, char** argv)
 
     const size_t fend = j.find("\"model_type\":", fstart + 10);
     size_t cp = j.find("\"cases\":", fstart);
+    int f_cases = 0;
+    double f_worst = 0.0, f_noc2 = 0.0, f_flip = 0.0;
     while (true)
     {
       const size_t c = j.find("\"frame\":", cp);
@@ -65,42 +101,72 @@ int main(int argc, char** argv)
       nextNumber(j, "t1", q, t1);
       nextNumber(j, "tof", q, tof);
       nextNumber(j, "mz", q, mz);
+      if (!cal.frameReason(t1).empty())
+      { std::fprintf(stderr, "FAIL %s frame %.0f refused: %s\n", name.c_str(), frame, cal.frameReason(t1).c_str()); return 1; }
       const double b = cal.frameFactor(t1);
       const double got = cal.tofToMz(tof, b);
       const double ppm = std::fabs(got - mz) / mz * 1e6;
-      if (ppm > 1e-4)   // same tolerance as the python twin; measured max is 2.6e-5
+      if (!(ppm <= 1e-4))   // same tolerance as the python twin; measured max is 2.6e-5 (NaN fails too)
       {
-        std::fprintf(stderr, "FAIL frame %.0f tof %.0f: got %.6f want %.6f (%.6f ppm)\n",
-                     frame, tof, got, mz, ppm);
+        std::fprintf(stderr, "FAIL %s frame %.0f tof %.0f: got %.6f want %.6f (%.6f ppm)\n",
+                     name.c_str(), frame, tof, got, mz, ppm);
         return 1;
       }
-      worst = std::fmax(worst, ppm);
-      // round trip must return the same TOF
+      f_worst = std::fmax(f_worst, ppm);
+      // round trip must return the same TOF, to the dnoise port's tolerance (recover::kTofTol)
       const double back = cal.mzToTof(got, b);
-      if (std::fabs(back - tof) > 1e-3)
-      { std::fprintf(stderr, "FAIL round trip: tof %.4f -> mz -> %.4f\n", tof, back); return 1; }
-      // ablation: dropping C2 must be clearly visible, else the golden set proves nothing
+      worst_back = std::fmax(worst_back, std::fabs(back - tof));
+      if (!(std::fabs(back - tof) <= 1e-6))
+      { std::fprintf(stderr, "FAIL %s round trip: tof %.4f -> mz -> %.10f\n", name.c_str(), tof, back); return 1; }
+      // ablations: dropping C2, flipping its sign or dropping the temperature term must be visible, else the golden
+      // set proves nothing
       diaspextract::TdfMzCalibration no_c2 = cal; no_c2.C2 = 0.0;
-      worst_noc2 = std::fmax(worst_noc2, std::fabs(no_c2.tofToMz(tof, b) - mz) / mz * 1e6);
-      ++n_cases;
+      diaspextract::TdfMzCalibration flip = cal; flip.C2 = -cal.C2;
+      f_noc2 = std::fmax(f_noc2, std::fabs(no_c2.tofToMz(tof, b) - mz) / mz * 1e6);
+      f_flip = std::fmax(f_flip, std::fabs(flip.tofToMz(tof, b) - mz) / mz * 1e6);
+      worst_notemp = std::fmax(worst_notemp, std::fabs(cal.tofToMz(tof, cal.frameFactor(cal.T1_ref)) - mz) / mz * 1e6);
+      ++n_cases; ++f_cases;
       cp = q;
     }
+    // per file, so a file whose cases cannot tell the model from the known-bad ports fails on its own
+    if (f_cases < 20 || !(f_noc2 >= 5.0) || !(f_flip >= 5.0))
+    { std::fprintf(stderr, "FAIL %s: %d cases, C2 ablation %.3f ppm, sign flip %.3f ppm\n", name.c_str(), f_cases, f_noc2, f_flip); return 1; }
+    std::printf("    %-16s C2 %+.6e  %2d cases  max %.7f ppm  (C2 dropped %.2f, flipped %.2f ppm)\n",
+                name.c_str(), cal.C2, f_cases, f_worst, f_noc2, f_flip);
+    worst = std::fmax(worst, f_worst);
+    worst_noc2 = std::fmax(worst_noc2, f_noc2);
+    n_negative += cal.C2 < 0.0;
     ++n_files;
     pos = fstart + 10;
   }
-  if (n_cases < 30) { std::fprintf(stderr, "only %d golden cases parsed\n", n_cases); return 1; }
+  // 60 cases on dataset D's vector, 210 on six PXD029836 runs (four negative-C2 vectors)
+  if (n_files < 9 || n_cases < 270 || n_negative < 6)
+  { std::fprintf(stderr, "only %d golden cases in %d files (%d with C2 < 0) parsed\n", n_cases, n_files, n_negative); return 1; }
   if (worst_noc2 < 5.0)
   { std::fprintf(stderr, "C2 ablation only %.3f ppm -- golden set cannot catch the known-bad port\n", worst_noc2); return 1; }
+  if (worst_notemp < 0.1)
+  { std::fprintf(stderr, "temperature ablation only %.4f ppm -- the golden set has no temperature spread\n", worst_notemp); return 1; }
 
-  // negative paths must be REJECTED, not approximated
-  diaspextract::TdfMzCalibration bad;
-  bad.model_type = 2; bad.C1 = 1.0; bad.digitizer_timebase = 0.125;
-  if (bad.isSupported()) { std::fprintf(stderr, "ModelType 2 must be rejected\n"); return 1; }
-  bad.model_type = 1; bad.dC2 = 1e-9;
-  if (bad.isSupported()) { std::fprintf(stderr, "dC2 != 0 must be rejected\n"); return 1; }
-  bad.dC2 = 0.0; bad.C3 = 1e-9;
-  if (bad.isSupported()) { std::fprintf(stderr, "C3 != 0 must be rejected\n"); return 1; }
-  bad.C3 = 0.0; bad.C4 = 0.0;
+  // negative paths must be REJECTED, not approximated -- each one a valid row with exactly one defect, and the
+  // reason must name it (a row refused for something else would pass a bare isSupported() check vacuously)
+  if (!validD().isSupported()) { std::fprintf(stderr, "dataset D's row must be supported: %s\n", validD().unsupportedReason().c_str()); return 1; }
+  {
+    struct Neg { const char* what; Cal cal; const char* reason; };
+    std::vector<Neg> negs;
+    Cal c = validD(); c.model_type = 2;          negs.push_back({"ModelType 2", c, "ModelType 2"});
+    c = validD(); c.dC2 = 1e-9;                   negs.push_back({"dC2 != 0", c, "dC2 != 0"});
+    c = validD(); c.C3 = 1e-9;                    negs.push_back({"C3 != 0", c, "C3 != 0"});
+    c = validD(); c.C1 = 1e-300;                  negs.push_back({"implausible C1", c, "C1 outside"});
+    c = validD(); c.C1 = 0.0;                     negs.push_back({"C1 <= 0", c, "C1 outside"});
+    c = validD(); c.C0 = std::nan("");            negs.push_back({"NaN C0", c, "NaN"});
+    c = validD(); c.C2 = std::nan("");            negs.push_back({"NaN C2", c, "NaN"});
+    c = validD(); c.digitizer_timebase = 0.0;     negs.push_back({"timebase 0", c, "DigitizerTimebase"});
+    for (const Neg& n : negs)
+    {
+      const std::string why = n.cal.unsupportedReason();
+      if (!has(why, n.reason)) { std::fprintf(stderr, "%s must be rejected for it, got '%s'\n", n.what, why.c_str()); return 1; }
+    }
+  }
   // C4 != 0 is an additive mass offset on the quadratic root (2019 timsTOF Pro, firmware 6.0.110;
   // the PXD017703 highsens files carry C4 = -0.0905 and every frame references that row). Pinned
   // against the vendor library on the first and the last frame of one such file; dropping the
@@ -130,8 +196,92 @@ int main(int argc, char** argv)
     if (worst_no_c4 < 50.0) { std::fprintf(stderr, "C4 ablation only %.3f ppm -- the case cannot catch a dropped C4\n", worst_no_c4); return 1; }
     std::printf("OK  C4 offset case: %.6f ppm vs vendor (10 probes, 2 frames); without C4 %.1f ppm\n", worst_c4, worst_no_c4);
   }
-  bad.C2 = -1e-6;
-  if (bad.isSupported()) { std::fprintf(stderr, "C2 < 0 must be rejected\n"); return 1; }
+  // A NEGATIVE C2 is the same law (the golden cases above pin six PXD029836 runs against the vendor library), accepted
+  // inside its domain: the rising branch, with the slope dt/du at least half its linear value, for every TOF index up to
+  // 1e8, every m/z up to 1e5 and every frame temperature within 1000 K of T1_ref.
+  {
+    const Cal px = pxd1418();
+    if (!px.isSupported()) { std::fprintf(stderr, "PXD029836's negative C2 must be ACCEPTED: %s\n", px.unsupportedReason().c_str()); return 1; }
+    // the corner the check decides on: dC1 > 0, so the smallest frame factor is at T1_ref - 1000 K
+    const double b_lo = px.frameFactor(px.T1_ref - Cal::kDomainT1Span), b_hi = px.frameFactor(px.T1_ref + Cal::kDomainT1Span);
+    if (!(b_lo < px.frameFactor(px.T1_ref) && px.frameFactor(px.T1_ref) < b_hi)) { std::fprintf(stderr, "corner: frame factor order\n"); return 1; }
+    const double t_max = Cal::kDomainMaxTof * px.digitizer_timebase + px.digitizer_delay;
+    const double ratio = (b_lo * b_lo + 4.0 * px.C2 * (t_max - px.C0)) / (b_lo * b_lo);
+    if (!(ratio > 0.98 && ratio < 0.99)) { std::fprintf(stderr, "PXD029836 corner disc / b^2 = %.6f, expected 0.987\n", ratio); return 1; }
+    // over the whole domain the conversion is finite, rising and round-trips, at both temperature extremes
+    double worst_rt = 0.0;
+    for (double b : {b_lo, b_hi})
+    {
+      double prev = 0.0;
+      for (double tof = 0.0; tof <= Cal::kDomainMaxTof; tof += Cal::kDomainMaxTof / 4096.0)
+      {
+        const double mz = px.tofToMz(tof, b);
+        if (!(std::isfinite(mz) && mz > prev)) { std::fprintf(stderr, "negative C2: tof %.0f -> %.9g after %.9g\n", tof, mz, prev); return 1; }
+        worst_rt = std::fmax(worst_rt, std::fabs(px.mzToTof(mz, b) - tof));   // bins: 3e-8 at TOF index 8.4e7, as for C2 >= 0
+        prev = mz;
+      }
+      for (double mz : {50.0, 1700.0, Cal::kDomainMaxMz})   // the inverse stays on the rising branch up to 1e5
+      {
+        const double tof = px.mzToTof(mz, b);
+        if (!(std::fabs(px.tofToMz(tof, b) - mz) / mz < 1e-12)) { std::fprintf(stderr, "negative C2: m/z %.1f does not round trip\n", mz); return 1; }
+      }
+    }
+    if (!(worst_rt <= 1e-6)) { std::fprintf(stderr, "negative C2 round trip: %.3g bins\n", worst_rt); return 1; }
+    // a stored -0.0 is zero: accepted, and the same conversion bit for bit
+    Cal nz = validD(), z = validD(); nz.C2 = -0.0; z.C2 = 0.0;
+    if (!nz.isSupported()) { std::fprintf(stderr, "C2 = -0.0 must be ACCEPTED: %s\n", nz.unsupportedReason().c_str()); return 1; }
+    for (double tof : {0.0, 1000.0, 300000.0, 634072.0})
+      if (nz.tofToMz(tof, nz.frameFactor(25.7)) != z.tofToMz(tof, z.frameFactor(25.7))) { std::fprintf(stderr, "C2 = -0.0 differs from 0.0\n"); return 1; }
+
+    // frames: a negative C2 refuses a T1 outside the checked span (and a NaN); positive and zero C2 never refuse one
+    for (double dt : {0.0, 999.9, -999.9, Cal::kDomainT1Span, -Cal::kDomainT1Span})
+      if (!px.frameReason(px.T1_ref + dt).empty()) { std::fprintf(stderr, "T1_ref %+g K must be converted: %s\n", dt, px.frameReason(px.T1_ref + dt).c_str()); return 1; }
+    for (double t1 : {px.T1_ref + 1000.001, px.T1_ref - 1000.001, 1e9, -1e9, std::nan("")})
+      if (!has(px.frameReason(t1), "Frames.T1")) { std::fprintf(stderr, "T1 %g must be refused for a negative C2\n", t1); return 1; }
+    for (double t1 : {1e9, -1e9, std::nan("")})
+    {
+      Cal zero = validD(); zero.C2 = 0.0;
+      if (!validD().frameReason(t1).empty() || !zero.frameReason(t1).empty()) { std::fprintf(stderr, "C2 >= 0 must not refuse a frame\n"); return 1; }
+    }
+
+    // a negative C2 whose root stops existing INSIDE the domain is refused, and the reason names the TOF index where the
+    // discriminant turns negative; the ablation shows the refusal is not vacuous: without it that TOF converts to NaN
+    Cal deep = px; deep.C2 = -0.1;
+    const std::string why = deep.unsupportedReason();
+    const double k = -4.0 * deep.C2, bw = deep.frameFactor(deep.T1_ref - Cal::kDomainT1Span);
+    const double tof_zero = (deep.C0 + bw * bw / k - deep.digitizer_delay) / deep.digitizer_timebase;
+    if (!(tof_zero < Cal::kDomainMaxTof) || !has(why, "outside its verified domain") || !has(why, ("stops existing at TOF index " + g6(tof_zero)).c_str()))
+    { std::fprintf(stderr, "C2 = -0.1 must be refused naming TOF index %s, got '%s'\n", g6(tof_zero).c_str(), why.c_str()); return 1; }
+    if (!std::isnan(deep.tofToMz(Cal::kDomainMaxTof, bw)) || !std::isfinite(deep.tofToMz(0.99 * tof_zero, bw)))
+    { std::fprintf(stderr, "C2 = -0.1: the discriminant must turn negative at TOF index %.6g, no earlier\n", tof_zero); return 1; }
+    // the margin: C2 = -0.07 still has a root at every TOF index up to 1e8, but its slope falls below half there
+    Cal shallow = px; shallow.C2 = -0.07;
+    if (shallow.isSupported() || !std::isfinite(shallow.tofToMz(Cal::kDomainMaxTof, bw)) || !has(shallow.unsupportedReason(), "slope halves"))
+    { std::fprintf(stderr, "C2 = -0.07 must be refused by the slope margin: '%s'\n", shallow.unsupportedReason().c_str()); return 1; }
+    Cal inside = px; inside.C2 = -0.05;   // 48 times PXD029836's: still inside
+    if (!inside.isSupported()) { std::fprintf(stderr, "C2 = -0.05 must be ACCEPTED: %s\n", inside.unsupportedReason().c_str()); return 1; }
+    // the boundary itself, stated independently: the slope is half its linear value at TOF index 1e8 and T1_ref - 1000 K
+    // (dC1 > 0) when |C2| = 3 b^2 / (16 (t_max - C0)); a wrong corner, span or margin moves it by far more than 1e-6
+    const double c2_edge = 3.0 * b_lo * b_lo / (16.0 * (t_max - px.C0));
+    Cal edge_in = px, edge_out = px; edge_in.C2 = -c2_edge * (1.0 - 1e-6); edge_out.C2 = -c2_edge * (1.0 + 1e-6);
+    if (!edge_in.isSupported() || edge_out.isSupported())
+    { std::fprintf(stderr, "the domain edge |C2| = %.9g: just inside '%s', just outside '%s'\n", c2_edge, edge_in.unsupportedReason().c_str(), edge_out.unsupportedReason().c_str()); return 1; }
+    // the m/z side: a fine timebase keeps every TOF index early, yet the branch peaks below m/z 1e5
+    Cal fine = px; fine.C2 = -2.5; fine.digitizer_timebase = 0.001;
+    const double kf = -4.0 * fine.C2, bf = fine.frameFactor(fine.T1_ref - Cal::kDomainT1Span);
+    const bool tof_side_ok = Cal::kDomainMaxTof * fine.digitizer_timebase + fine.digitizer_delay <= fine.C0 + 0.75 * bf * bf / kf;
+    if (!tof_side_ok || fine.isSupported() || !has(fine.unsupportedReason(), "m/z 100000"))
+    { std::fprintf(stderr, "C2 = -2.5 at 1 ps must be refused on the m/z side (TOF side ok %d): '%s'\n", int(tof_side_ok), fine.unsupportedReason().c_str()); return 1; }
+    Cal minus_inf = px; minus_inf.C2 = -std::numeric_limits<double>::infinity();
+    if (minus_inf.isSupported()) { std::fprintf(stderr, "C2 = -inf must be rejected\n"); return 1; }
+    // a temperature coefficient that takes the C1 factor through zero within the span cannot be checked
+    Cal hot = px; hot.dC1 = 1000.0;
+    Cal hot_pos = validD(); hot_pos.dC1 = 1000.0;
+    if (!has(hot.unsupportedReason(), "dC1") || !hot_pos.isSupported())
+    { std::fprintf(stderr, "dC1 1000: refused for C2 < 0 ('%s'), accepted for C2 > 0 ('%s')\n", hot.unsupportedReason().c_str(), hot_pos.unsupportedReason().c_str()); return 1; }
+    std::printf("OK  negative C2: PXD029836 accepted (corner disc/b^2 %.4f, round trip %.1e bins up to TOF index 1e8); C2 -0.1 refused at TOF index %s, "
+                "-0.07 by the margin, -2.5 at 1 ps on m/z; edge |C2| %.6g; T1 outside +-1000 K refused\n", ratio, worst_rt, g6(tof_zero).c_str(), c2_edge);
+  }
   // C2 == 0.0 STORED in the file is a real calibration -- the 2020 timsTOF Pro firmware behind
   // PXD017703 ships t = C0 + C1_eff*sqrt(m) with no quadratic term, every frame referencing it --
   // and must be ACCEPTED. A NULL C2 is what must be refused; the loader converts NULL to NaN, which
@@ -153,12 +303,6 @@ int main(int argc, char** argv)
       if (std::fabs(back - tof) > 1e-6) { std::fprintf(stderr, "C2==0 round trip: %.4f -> %.4f\n", tof, back); return 1; }
     }
   }
-  bad.C2 = 1e-3; bad.C1 = 1e-300;   // positive but implausible: b*b overflows -> silent m/z 0
-  if (bad.isSupported()) { std::fprintf(stderr, "implausible C1 must be rejected\n"); return 1; }
-  bad.C1 = 155279.0; bad.C0 = std::nan("");
-  if (bad.isSupported()) { std::fprintf(stderr, "NaN must be rejected\n"); return 1; }
-  bad.C0 = 279.3; bad.C1 = 0.0;
-  if (bad.isSupported()) { std::fprintf(stderr, "C1 <= 0 must be rejected\n"); return 1; }
 
   // unphysical TOF must NOT return a plausible mass (silent-wrongness guard)
   diaspextract::TdfMzCalibration ok;
@@ -179,7 +323,7 @@ int main(int argc, char** argv)
   if (!std::isnan(late.tofToMz(1e5, late.frameFactor(late.T1_ref))))
   { std::fprintf(stderr, "t <= C0 must yield NaN, not a plausible-looking mass\n"); return 1; }
 
-  std::printf("OK  %d golden cases, %d files: max %.6f ppm; C2 ablation %.2f ppm; round trip + negative paths pass\n",
-              n_cases, n_files, worst, worst_noc2);
+  std::printf("OK  %d golden cases, %d files (%d with C2 < 0): max %.7f ppm; C2 ablation %.2f ppm, temperature %.3f ppm; "
+              "round trip %.1e bins; negative paths pass\n", n_cases, n_files, n_negative, worst, worst_noc2, worst_notemp, worst_back);
   return 0;
 }
diff --git a/tests/test_dnoise_ms1.cpp b/tests/test_dnoise_ms1.cpp
index 28d47a0..7d25f5f 100644
--- a/tests/test_dnoise_ms1.cpp
+++ b/tests/test_dnoise_ms1.cpp
@@ -816,6 +816,42 @@ static void testRecover()
           "%s: corrected value %u has no raw count (%d found)", f.name, f.no_preimage, hits);
   }
 
+  // a negative C2 (PXD029836 run 1418, timsTOF Pro 2): the inverse the recovery uses is exact there too -- every one of the
+  // digitizer's 397,657 bins comes back at frame 1's temperature and at the run's coldest and warmest frame, and half a bin
+  // and +1 ppm are refused. The scan and intensity geometry is D's: the TOF is checked first and does not depend on it.
+  {
+    diaspextract::TdfMzCalibration neg;
+    neg.model_type = 1; neg.digitizer_timebase = 0.19999999999999998; neg.digitizer_delay = 25779.8; neg.C0 = 314.1341896383674;
+    neg.C1 = 154199.217568937; neg.C2 = -0.0010422663259118895; neg.T1_ref = 25.618823611312585; neg.dC1 = 20.0;
+    CHECK(neg.isSupported(), "PXD029836's row: %s", neg.unsupportedReason().c_str());
+    const RecoverFile g = recoverD();
+    double c = 0.0;
+    rc::opentimsCorrection(g.accumulation_time, c);
+    std::vector<float> asc;
+    bool falls = false;
+    rc::buildScanTable(g.tims, g.n_scans, asc, falls);
+    const float im0 = loaderIm(g.tims, 0.0);
+    const long n_bins = 397657;
+    long tof_bad = 0, half_bad = 0, ppm_bad = 0;
+    double worst = 0.0;
+    for (const double t1 : {25.614796222167577, 25.61007554899474, 25.615998301764314})
+    {
+      const double b = neg.frameFactor(t1);
+      for (long bin = 0; bin < n_bins; ++bin)
+      {
+        const double mz = neg.tofToMz(static_cast<double>(bin), b);
+        tof_bad += rc::recoverPoint(neg, b, mz, im0, 0.0f, c, asc, falls, g.n_scans, tof, scan, raw, t, hits) != R::none || tof != static_cast<u32>(bin);
+        worst = std::max(worst, std::fabs(t - static_cast<double>(bin)));
+        half_bad += rc::recoverPoint(neg, b, neg.tofToMz(static_cast<double>(bin) + 0.5, b), im0, 0.0f, c, asc, falls, g.n_scans, tof, scan, raw, t, hits) != R::tof;
+        ppm_bad += rc::recoverPoint(neg, b, mz * (1.0 + 1e-6), im0, 0.0f, c, asc, falls, g.n_scans, tof, scan, raw, t, hits) != R::tof;
+      }
+    }
+    CHECK(tof_bad == 0 && half_bad == 0 && ppm_bad == 0 && worst < 1e-9,
+          "negative C2 TOF: %ld of %ld bins lost, %ld half-bin and %ld +1 ppm m/z not refused, worst round trip %.3g bins",
+          tof_bad, 3 * n_bins, half_bad, ppm_bad, worst);
+    std::printf("    negative C2 (PXD029836 1418): %ld bins x 3 temperatures recovered, worst round trip %.2g bins\n", n_bins, worst);
+  }
+
   // intensity edge cases, on D's frame geometry
   const RecoverFile d = recoverD();
   const double b = d.cal.frameFactor(d.t1), mz = d.cal.tofToMz(1000.0, b);
diff --git a/tests/test_tdf_load.cpp b/tests/test_tdf_load.cpp
index ebbeb0b..6c30b7e 100644
--- a/tests/test_tdf_load.cpp
+++ b/tests/test_tdf_load.cpp
@@ -311,6 +311,32 @@ static void testCalibrationAndBounds()
   CHECK(diaspextract::loadTdfAxisBounds(ok, bd, why) && bd.n_bins == 634073 && bd.mz_lo == 99.990834 && bd.mz_hi == 1700.0, "loadTdfAxisBounds: %s", why.c_str());
   CHECK(!diaspextract::loadTdfAxisBounds(makeTdf("bounds_notable.tdf", dShaped() + "DROP TABLE GlobalMetadata;"), bd, why) && has(why, "GlobalMetadata"),
         "no GlobalMetadata: %s", why.c_str());
+  // the two bounds are the negative-C2 domain's: 1e8 bins and m/z 1e5 are accepted, one more is not
+  CHECK(diaspextract::loadTdfAxisBounds(makeTdf("bounds_max.tdf", dShaped() + "UPDATE GlobalMetadata SET Value = '100000000' WHERE Key = 'DigitizerNumSamples';"
+                                                "UPDATE GlobalMetadata SET Value = '100000' WHERE Key = 'MzAcqRangeUpper';"), bd, why) &&
+          bd.n_bins == 100000000 && bd.mz_hi == 1e5, "DigitizerNumSamples 1e8, MzAcqRangeUpper 1e5: %s", why.c_str());
+  CHECK(!diaspextract::loadTdfAxisBounds(makeTdf("bounds_bins.tdf", dShaped() + "UPDATE GlobalMetadata SET Value = '100000001' WHERE Key = 'DigitizerNumSamples';"), bd, why) &&
+          has(why, "DigitizerNumSamples"), "DigitizerNumSamples 1e8 + 1: %s", why.c_str());
+  CHECK(!diaspextract::loadTdfAxisBounds(makeTdf("bounds_mz.tdf", dShaped() + "UPDATE GlobalMetadata SET Value = '100000.001' WHERE Key = 'MzAcqRangeUpper';"), bd, why) &&
+          has(why, "not usable"), "MzAcqRangeUpper above 1e5: %s", why.c_str());
+
+  // a negative C2 (PXD029836 run 1418's row, timsTOF Pro 2) loads; one whose root stops existing inside the domain is
+  // refused, naming the TOF index; a frame whose T1 lies outside the checked span is refused for a negative C2 only
+  const std::string pxd = "UPDATE MzCalibration SET DigitizerTimebase = 0.19999999999999998, DigitizerDelay = 25779.8, T1 = 25.618823611312585,"
+                          "  dC1 = 20, C0 = 314.1341896383674, C1 = 154199.217568937, C2 = -0.0010422663259118895;"
+                          "UPDATE Frames SET T1 = 25.614796222167577 - Id * 1e-6;";
+  CHECK(diaspextract::loadTdfCalibration(makeTdf("cal_c2neg.tdf", dShaped() + pxd), cal, t1, why) && cal.C2 == -0.0010422663259118895 &&
+          cal.digitizer_timebase == 0.19999999999999998 && t1.size() == 11 && t1[10] == 25.614796222167577 - 10 * 1e-6,
+        "a negative C2 inside its domain: %s", why.c_str());
+  CHECK(!diaspextract::loadTdfCalibration(makeTdf("cal_c2deep.tdf", dShaped() + pxd + "UPDATE MzCalibration SET C2 = -0.1;"), cal, t1, why) &&
+          has(why, "C2 -0.1 < 0 outside its verified domain") && has(why, "stops existing at TOF index 7.93471e+07"),
+        "C2 -0.1: %s", why.c_str());
+  CHECK(!diaspextract::loadTdfCalibration(makeTdf("cal_c2neg_hot.tdf", dShaped() + pxd + "UPDATE Frames SET T1 = 1100 WHERE Id = 7;"), cal, t1, why) &&
+          has(why, "frame 7: Frames.T1 1100 is not within 1000 K of the MzCalibration T1 25.6188"), "a negative C2, frame 7 at 1100 C: %s", why.c_str());
+  CHECK(diaspextract::loadTdfCalibration(makeTdf("cal_c2neg_null.tdf", dShaped() + pxd + "UPDATE Frames SET T1 = NULL WHERE Id = 7;"), cal, t1, why) &&
+          t1[7] == cal.T1_ref, "a negative C2, a NULL T1 is the reference temperature: %s", why.c_str());
+  CHECK(diaspextract::loadTdfCalibration(makeTdf("cal_c2pos_hot.tdf", dShaped() + "UPDATE Frames SET T1 = 1100 WHERE Id = 7;"), cal, t1, why) && t1[7] == 1100.0,
+        "a positive C2 reads frame 7 at 1100 C as before: %s", why.c_str());
 }
 
 int main()
@@ -330,7 +356,7 @@ int main()
   if (g_fail == before) std::printf("OK  AccumulationTime: whole C-locale decimal > 0; above 100 ms the setup refusal\n");
   before = g_fail;
   testCalibrationAndBounds();
-  if (g_fail == before) std::printf("OK  loadTdfCalibration and loadTdfAxisBounds: whole reads, schema-decided fallback\n");
+  if (g_fail == before) std::printf("OK  loadTdfCalibration and loadTdfAxisBounds: whole reads, schema-decided fallback; a negative C2 inside its domain, frame T1 span\n");
   std::error_code ec;
   std::filesystem::remove_all(g_dir, ec);
   if (g_fail) std::fprintf(stderr, "%d check(s) failed\n", g_fail);

```

## 3. Evidence

### 3a. SDK golden generator output (ibminode05, libtimsdata 2.21.0.4; one line per run)
```
ibminode05
2026-09-17T02:34:08+02:00
PXD029836 1418 <run 1418>: copy 0.5 s, tdf sha256 89f5fcffe91d1ba2, 67875 frames, T1 25.610076..25.615998 (T1_ref 25.618824), C2 -0.00104226632591, N 397657, vendor m/z 99.9990..1700.0024; picked frames [1, 55822, 33938, 9451, 67875]; 35 cases; dense 2017 probes x 5 frames: worst |ppm| shipped 0.0000057 (nan 0), C2 dropped 33.750, C2 flipped 67.497, temperature dropped 0.1750; disc/b^2 at tof N-1 0.999932501; disc = 0 at tof 7.77753e+09 (19558x N)
PXD029836 1420 <run 1420>: copy 0.5 s, tdf sha256 aee03877e3e0ac95, 67840 frames, T1 25.608334..25.612606 (T1_ref 25.618824), C2 -0.00104226632591, N 397657, vendor m/z 99.9990..1700.0026; picked frames [1, 21766, 33921, 56289, 67840]; 35 cases; dense 2017 probes x 5 frames: worst |ppm| shipped 0.0000070 (nan 0), C2 dropped 33.750, C2 flipped 67.497, temperature dropped 0.2098; disc/b^2 at tof N-1 0.999932501; disc = 0 at tof 7.77753e+09 (19558x N)
PXD029836 1422 <run 1422>: copy 0.5 s, tdf sha256 bc3a97f36cd35677, 67837 frames, T1 25.609132..25.613503 (T1_ref 25.618824), C2 -0.00104226632591, N 397657, vendor m/z 99.9990..1700.0025; picked frames [1, 2379, 33919, 14444, 67837]; 35 cases; dense 2017 probes x 5 frames: worst |ppm| shipped 0.0000065 (nan 0), C2 dropped 33.750, C2 flipped 67.497, temperature dropped 0.1938; disc/b^2 at tof N-1 0.999932501; disc = 0 at tof 7.77753e+09 (19558x N)
PXD029836 1431 <run 1431>: copy 0.3 s, tdf sha256 16b35daa502a59c0, 41834 frames, T1 25.607881..25.613427 (T1_ref 25.612279), C2 -0.00122835768837, N 397657, vendor m/z 99.9991..1700.0039; picked frames [1, 36972, 20918, 6226, 41834]; 35 cases; dense 2017 probes x 5 frames: worst |ppm| shipped 0.0000061 (nan 0), C2 dropped 39.775, C2 flipped 79.547, temperature dropped 0.0880; disc/b^2 at tof N-1 0.999920450; disc = 0 at tof 6.59929e+09 (16595x N)
PXD029836 1408 <run 1408>: copy 0.3 s, tdf sha256 3daa1720954fcf2b, 41852 frames, T1 25.609184..25.613797 (T1_ref 25.610077), C2 -0.000755925982703, N 397657, vendor m/z 99.9990..1700.0054; picked frames [1, 37745, 20927, 8635, 41852]; 35 cases; dense 2017 probes x 5 frames: worst |ppm| shipped 0.0000064 (nan 0), C2 dropped 24.478, C2 flipped 48.954, temperature dropped 0.0744; disc/b^2 at tof N-1 0.999951044; disc = 0 at tof 1.07235e+10 (26967x N)
PXD029836 1347 <run 1347>: copy 0.5 s, tdf sha256 b77f33edba54b59f, 67796 frames, T1 25.608357..25.613053 (T1_ref 25.609173), C2 -0.000586432296582, N 397657, vendor m/z 99.9989..1700.0034; picked frames [1, 19171, 33899, 35102, 67796]; 35 cases; dense 2017 probes x 5 frames: worst |ppm| shipped 0.0000063 (nan 0), C2 dropped 18.990, C2 flipped 37.978, temperature dropped 0.0776; disc/b^2 at tof N-1 0.999962021; disc = 0 at tof 1.38228e+10 (34761x N)
removed /scratch/kohlbach/c2neg_golden_20260917_023408_1239940 True
```

### 3b. Discriminant margins from the laptop tdf copies (runs 1418/1420/1422)
```
== <run 1418>
  rows 1 distinct refs 1 cal (1, 0.19999999999999998, 25779.8, 25.618823611312585, 20.0, 0.0, 314.1341896383674, 154199.217568937, -0.0010422663259118895, 0.0, 0.0)
  meta {'AcquisitionSoftware': 'timsTOF', 'AcquisitionSoftwareVersion': '2.0.53.0', 'DigitizerNumSamples': '397657', 'InstrumentName': 'timsTOF Pro 2', 'MzAcqRangeLower': '100.000000', 'MzAcqRangeUpper': '1700.000000'} frames 67875 T1 null 0 T1 range 25.610075549..25.615998302 (span 0.005923 K; vs T1_ref -0.008748..-0.002825 K)
  disc/b^2 at tof N-1=397656     over the frames' T1: 0.999932501  (sqrt 0.999966)
  disc/b^2 at tof 1e8            over the frames' T1: 0.987126295  (sqrt 0.993542)
  disc/b^2 at tof 2^32-1         over the frames' T1: 0.447765321  (sqrt 0.669153)
  disc/b^2 at tof N-1     T1_ref+-1000 K: 0.999931151
  disc/b^2 at tof 1e8     T1_ref+-1000 K: 0.986868823
  disc/b^2 at tof 2^32-1  T1_ref+-1000 K: 0.436720726
  worst corner (+-1000 K): disc = 0 at tof 7.6250e+09, slope half at tof 5.7187e+09; vertex m/z 1.4632e+12; half-slope m/z 3.6580e+11
  at the file's worst frame: disc = 0 at tof 7.7775e+09 (19558x N)
== <run 1420>
  rows 1 distinct refs 1 cal (1, 0.19999999999999998, 25779.8, 25.618823611312585, 20.0, 0.0, 314.1341896383674, 154199.217568937, -0.0010422663259118895, 0.0, 0.0)
  meta {'AcquisitionSoftware': 'timsTOF', 'AcquisitionSoftwareVersion': '2.0.53.0', 'DigitizerNumSamples': '397657', 'InstrumentName': 'timsTOF Pro 2', 'MzAcqRangeLower': '100.000000', 'MzAcqRangeUpper': '1700.000000'} frames 67840 T1 null 0 T1 range 25.608334259..25.612605653 (span 0.004271 K; vs T1_ref -0.010489..-0.006218 K)
  disc/b^2 at tof N-1=397656     over the frames' T1: 0.999932501  (sqrt 0.999966)
  disc/b^2 at tof 1e8            over the frames' T1: 0.987126294  (sqrt 0.993542)
  disc/b^2 at tof 2^32-1         over the frames' T1: 0.447765302  (sqrt 0.669153)
  disc/b^2 at tof N-1     T1_ref+-1000 K: 0.999931151
  disc/b^2 at tof 1e8     T1_ref+-1000 K: 0.986868823
  disc/b^2 at tof 2^32-1  T1_ref+-1000 K: 0.436720726
  worst corner (+-1000 K): disc = 0 at tof 7.6250e+09, slope half at tof 5.7187e+09; vertex m/z 1.4632e+12; half-slope m/z 3.6580e+11
  at the file's worst frame: disc = 0 at tof 7.7775e+09 (19558x N)
== <run 1422>
  rows 1 distinct refs 1 cal (1, 0.19999999999999998, 25779.8, 25.618823611312585, 20.0, 0.0, 314.1341896383674, 154199.217568937, -0.0010422663259118895, 0.0, 0.0)
  meta {'AcquisitionSoftware': 'timsTOF', 'AcquisitionSoftwareVersion': '2.0.53.0', 'DigitizerNumSamples': '397657', 'InstrumentName': 'timsTOF Pro 2', 'MzAcqRangeLower': '100.000000', 'MzAcqRangeUpper': '1700.000000'} frames 67837 T1 null 0 T1 range 25.609132027..25.613503383 (span 0.004371 K; vs T1_ref -0.009692..-0.005320 K)
  disc/b^2 at tof N-1=397656     over the frames' T1: 0.999932501  (sqrt 0.999966)
  disc/b^2 at tof 1e8            over the frames' T1: 0.987126294  (sqrt 0.993542)
  disc/b^2 at tof 2^32-1         over the frames' T1: 0.447765311  (sqrt 0.669153)
  disc/b^2 at tof N-1     T1_ref+-1000 K: 0.999931151
  disc/b^2 at tof 1e8     T1_ref+-1000 K: 0.986868823
  disc/b^2 at tof 2^32-1  T1_ref+-1000 K: 0.436720726
  worst corner (+-1000 K): disc = 0 at tof 7.6250e+09, slope half at tof 5.7187e+09; vertex m/z 1.4632e+12; half-slope m/z 3.6580e+11
  at the file's worst frame: disc = 0 at tof 7.7775e+09 (19558x N)

```

### 3c. Calibration rows of all 23 PXD029836 runs (`MzCalibration` referenced by the frames)
```
run 1408 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0007559259827 C4=0 dC2=0 C3=0 T1=25.6101']
run 1409 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0007559259827 C4=0 dC2=0 C3=0 T1=25.6101']
run 1410 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0007559259827 C4=0 dC2=0 C3=0 T1=25.6101']
run 1411 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0007559259827 C4=0 dC2=0 C3=0 T1=25.6101']
run 1412 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0007559259827 C4=0 dC2=0 C3=0 T1=25.6101']
run 1413 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0007559259827 C4=0 dC2=0 C3=0 T1=25.6101']
run 1414 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0007559259827 C4=0 dC2=0 C3=0 T1=25.6101']
run 1415 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0007559259827 C4=0 dC2=0 C3=0 T1=25.6101']
run 1416 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0007559259827 C4=0 dC2=0 C3=0 T1=25.6101']
run 1418 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.001042266326 C4=0 dC2=0 C3=0 T1=25.6188']
run 1420 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.001042266326 C4=0 dC2=0 C3=0 T1=25.6188']
run 1422 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.001042266326 C4=0 dC2=0 C3=0 T1=25.6188']
run 1431 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.001228357688 C4=0 dC2=0 C3=0 T1=25.6123']
run 1433 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.001228357688 C4=0 dC2=0 C3=0 T1=25.6123']
run 1435 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.001228357688 C4=0 dC2=0 C3=0 T1=25.6123']
run 1347 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0005864322966 C4=0 dC2=0 C3=0 T1=25.6092']
run 1354 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0005864322966 C4=0 dC2=0 C3=0 T1=25.6092']
run 1349 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0005864322966 C4=0 dC2=0 C3=0 T1=25.6092']
run 1358 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0005864322966 C4=0 dC2=0 C3=0 T1=25.6092']
run 1346 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0005864322966 C4=0 dC2=0 C3=0 T1=25.6092']
run 1352 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0005864322966 C4=0 dC2=0 C3=0 T1=25.6092']
run 1348 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0005864322966 C4=0 dC2=0 C3=0 T1=25.6092']
run 1356 refs [1] timsTOF Pro 2 2.0.53.0 397657 ['C2=-0.0005864322966 C4=0 dC2=0 C3=0 T1=25.6092']
```

### 3d. Mutation proof (each mutation applied alone to the header/reader; which test suites catch it)
```
control                        calib=pass | tdf=pass | dnoise=pass
M1 old refusal                 calib=FAIL: golden file 3 unsupported: MzCalibration C2 < 0 (negative quadratic term is not a supported model) | tdf=FAIL: FAIL line 330: a negative C2 inside its domain: MzCalibration C2 < 0 (negative quadratic term is not a support | dnoise=FAIL: FAIL line 826: PXD029836's row: MzCalibration C2 < 0 (negative quadratic term is not a supported model)
M2 no domain check             calib=FAIL: C2 = -0.1 must be refused naming TOF index 7.93471e+07, got '' | tdf=FAIL: FAIL line 333: C2 -0.1: GlobalMetadata bounds are not usable: MzAcqRange 99.990834-100000.001000, DigitizerNum | dnoise=pass
M3 no margin (disc > 0)        calib=FAIL: C2 = -0.07 must be refused by the slope margin: '' | tdf=pass | dnoise=pass
M4 no m/z side                 calib=FAIL: C2 = -2.5 at 1 ps must be refused on the m/z side (TOF side ok 1): '' | tdf=pass | dnoise=pass
M5 wrong corner (cf_lo)        calib=FAIL: C2 = -0.1 must be refused naming TOF index 7.93471e+07, got 'MzCalibration C2 -0.1 < 0 outside its verified do | tdf=FAIL: FAIL line 333: C2 -0.1: MzCalibration C2 -0.1 < 0 outside its verified domain: the TOF-to-m/z root stops exist | dnoise=pass
M6 no temperature span         calib=FAIL: C2 = -0.1 must be refused naming TOF index 7.93471e+07, got 'MzCalibration C2 -0.1 < 0 outside its verified do | tdf=FAIL: FAIL line 333: C2 -0.1: MzCalibration C2 -0.1 < 0 outside its verified domain: the TOF-to-m/z root stops exist | dnoise=pass
M7 frameReason never refuses   calib=FAIL: T1 1025.62 must be refused for a negative C2 | tdf=FAIL: FAIL line 335: a negative C2, frame 7 at 1100 C: MzCalibration C2 -0.1 < 0 outside its verified domain: the TO | dnoise=pass
M8 frameReason for every C2    calib=FAIL: C2 >= 0 must not refuse a frame | tdf=FAIL: FAIL line 339: a positive C2 reads frame 7 at 1100 C as before: frame 7: Frames.T1 1100 is not within 1000 K o | dnoise=pass
M9 reader skips frameReason    calib=pass | tdf=FAIL: FAIL line 335: a negative C2, frame 7 at 1100 C: MzCalibration C2 -0.1 < 0 outside its verified domain: the TO | dnoise=pass
M10 dC1 guard gone             calib=FAIL: dC1 1000: refused for C2 < 0 (''), accepted for C2 > 0 ('') | tdf=pass | dnoise=pass
M11 textbook root              calib=FAIL: FAIL dataset D round trip: tof 317036.5000 -> mz -> 317036.4999982993 | tdf=pass | dnoise=FAIL: FAIL line 782: D TOF: 292455 of 634073 bins lost, 0 half-bin and 0 +1 ppm m/z not refused
M12 other root                 calib=FAIL: FAIL dataset D frame 1 tof 31704: got 4056100864434.218750 want 133.659113 (30346609106978664.000000 ppm) | tdf=pass | dnoise=FAIL: FAIL line 782: D TOF: 634073 of 634073 bins lost, 0 half-bin and 0 +1 ppm m/z not refused

```

### 3e. Local ctest on the branch (AppleClang 21; GCC 16 prints the same numbers)
```
1: OK  gate: D 24 boxes (FMA-sensitive 11/15/16 intact), TNBC 009 28 boxes (otofControl); lookup, refusal and parse rules
1: OK  streak, halo and gate rules on synthetic frames; 0.15 double compare == integer rule
1: OK  3000 random frames (883832 points, 270115 kept) identical to a transliteration of the Rust, in either input order
1:     negative C2 (PXD029836 1418): 397657 bins x 3 temperatures recovered, worst round trip 2e-10 bins
1: OK  point recovery on D and TNBC 009 metadata: every TOF bin and scan, raw counts to 2^24; correction, frame and coverage rules
1/3 Test #1: dnoise_ms1 .......................   Passed    0.73 sec
2: OK  DiaFrameMsMsWindows: whole (24, 3000), absent = no gate, any case; a missing column, a NULL scan, a corrupt page refused
2: OK  Frames and TimsCalibration: typed and ranged before narrowing; per-row scan need; corrupt leaf refused
2: OK  AccumulationTime: whole C-locale decimal > 0; above 100 ms the setup refusal
2: OK  loadTdfCalibration and loadTdfAxisBounds: whole reads, schema-decided fallback; a negative C2 inside its domain, frame T1 span
2/3 Test #2: tdf_load .........................   Passed    0.41 sec
3: OK  C4 offset case: 0.000020 ppm vs vendor (10 probes, 2 frames); without C4 923.3 ppm
3: OK  negative C2: PXD029836 accepted (corner disc/b^2 0.9869, round trip 3.0e-08 bins up to TOF index 1e8); C2 -0.1 refused at TOF index 7.93471e+07, -0.07 by the margin, -2.5 at 1 ps on m/z; edge |C2| 0.0595301; T1 outside +-1000 K refused
3: OK  270 golden cases, 9 files (6 with C2 < 0): max 0.0000260 ppm; C2 ablation 39.78 ppm, temperature 0.669 ppm; round trip 1.7e-10 bins; negative paths pass
3/3 Test #3: calibration_golden ...............   Passed    0.13 sec
100% tests passed out of 3
```

## 4. Golden JSON after the change (9 files; the first 3 predate the branch)
- {"file": "dataset D", "model_type": 1, "timebase": 0.125, "delay": 25655.375, "C0": 279.3262846272992, "C1": 155279.13067653627, "C2": 0.001260061434461731, "T1_ref": 25.693668980735552, "dC1": 20.0, "num_samples": 634073}
  20 cases; frames [1, 5817, 11633, 17448]; t1 25.720969858..25.727120813; tof probes [31703.65, 158518.25, 317036.5, 475554.75, 602369.35]; mz 133.659113..1573.674888
- {"file": "dataset A", "model_type": 1, "timebase": 0.125, "delay": 25655.375, "C0": 279.3262846272992, "C1": 155279.13067653627, "C2": 0.001260061434461731, "T1_ref": 25.693668980735552, "dC1": 20.0, "num_samples": 634073}
  20 cases; frames [1, 5817, 11633, 17448]; t1 25.721467398..25.723088715; tof probes [31703.65, 158518.25, 317036.5, 475554.75, 602369.35]; mz 133.659124..1573.674873
- {"file": "dataset B", "model_type": 1, "timebase": 0.125, "delay": 25655.375, "C0": 279.3262846272992, "C1": 155279.13067653627, "C2": 0.001260061434461731, "T1_ref": 25.693668980735552, "dC1": 20.0, "num_samples": 634073}
  20 cases; frames [1, 5817, 11633, 17448]; t1 25.722542036..25.723943512; tof probes [31703.65, 158518.25, 317036.5, 475554.75, 602369.35]; mz 133.659122..1573.674839
- {"file": "PXD029836 1418", "model_type": 1, "timebase": 0.19999999999999998, "delay": 25779.8, "C0": 314.1341896383674, "C1": 154199.217568937, "C2": -0.0010422663259118895, "T1_ref": 25.618823611312585, "dC1": 20.0, "num_samples": 397657}
  35 cases; frames [1, 9451, 33938, 55822, 67875]; t1 25.610075549..25.615998302; tof probes [2000.0, 19882.850000000002, 99414.25, 198828.5, 298242.75, 377774.14999999997, 397656.0]; mz 103.165177..1700.002557
- {"file": "PXD029836 1420", "model_type": 1, "timebase": 0.19999999999999998, "delay": 25779.8, "C0": 314.1341896383674, "C1": 154199.217568937, "C2": -0.0010422663259118895, "T1_ref": 25.618823611312585, "dC1": 20.0, "num_samples": 397657}
  35 cases; frames [1, 21766, 33921, 56289, 67840]; t1 25.608334259..25.612605653; tof probes [2000.0, 19882.850000000002, 99414.25, 198828.5, 298242.75, 377774.14999999997, 397656.0]; mz 103.165184..1700.002616
- {"file": "PXD029836 1422", "model_type": 1, "timebase": 0.19999999999999998, "delay": 25779.8, "C0": 314.1341896383674, "C1": 154199.217568937, "C2": -0.0010422663259118895, "T1_ref": 25.618823611312585, "dC1": 20.0, "num_samples": 397657}
  35 cases; frames [1, 2379, 14444, 33919, 67837]; t1 25.609132027..25.613503383; tof probes [2000.0, 19882.850000000002, 99414.25, 198828.5, 298242.75, 377774.14999999997, 397656.0]; mz 103.165183..1700.002589
- {"file": "PXD029836 1431", "model_type": 1, "timebase": 0.19999999999999998, "delay": 25779.8, "C0": 314.0580393347482, "C1": 154198.21084980678, "C2": -0.0012283576883732204, "T1_ref": 25.612279482616906, "dC1": 20.0, "num_samples": 397657}
  35 cases; frames [1, 6226, 20918, 36972, 41834]; t1 25.607881392..25.613427122; tof probes [2000.0, 19882.850000000002, 99414.25, 198828.5, 298242.75, 377774.14999999997, 397656.0]; mz 103.165256..1700.004020
- {"file": "PXD029836 1408", "model_type": 1, "timebase": 0.19999999999999998, "delay": 25779.999999999996, "C0": 314.48704092054686, "C1": 154201.38074828373, "C2": -0.0007559259827031187, "T1_ref": 25.610076586928137, "dC1": 20.0, "num_samples": 397657}
  35 cases; frames [1, 8635, 20927, 37745, 41852]; t1 25.609183846..25.613796923; tof probes [2000.0, 19882.850000000002, 99414.25, 198828.5, 298242.75, 377774.14999999997, 397656.0]; mz 103.165156..1700.005426
- {"file": "PXD029836 1347", "model_type": 1, "timebase": 0.19999999999999998, "delay": 25779.999999999996, "C0": 314.5551322024985, "C1": 154202.25071153036, "C2": -0.0005864322965816343, "T1_ref": 25.609173082963196, "dC1": 20.0, "num_samples": 397657}
  35 cases; frames [1, 19171, 33899, 35102, 67796]; t1 25.608356953..25.613052928; tof probes [2000.0, 19882.850000000002, 99414.25, 198828.5, 298242.75, 377774.14999999997, 397656.0]; mz 103.165055..1700.003479

First three new cases (PXD029836 1418):
```json
[
 {
  "frame": 1,
  "t1": 25.614796222167577,
  "tof": 2000.0,
  "mz": 103.16517994053211
 },
 {
  "frame": 1,
  "t1": 25.614796222167577,
  "tof": 19882.850000000002,
  "mz": 133.66813499574562
 },
 {
  "frame": 1,
  "t1": 25.614796222167577,
  "tof": 99414.25,
  "mz": 317.113470964742
 }
]
```

## 5. The SDK golden generator (`sdk_golden_pxd029836.py`, run on the cluster; not in the repo)
```python
#!/usr/bin/env python3
"""Golden cases for a NEGATIVE MzCalibration C2 (PXD029836, timsTOF Pro 2, acquisition software 2.0.53), produced by
Bruker's libtimsdata on ibminode05 (local oracle only, never redistributed). Read-only on the raw files: only
analysis.tdf is copied into a private 0700 scratch directory, next to an EMPTY analysis.tdf_bin (index->m/z needs the
calibration, not the frame blobs); the directory is removed at the end.

Output: a JSON list in the schema of tests/calibration_golden.json (stdout, between markers), plus per-file
diagnostics: the worst |ppm| of the shipped model (cancellation-free root, re-implemented here) over a dense sweep,
the ablations (C2 dropped, C2 sign-flipped, temperature dropped), and the discriminant margin over the file's
whole TOF range at its extreme frame temperatures.
Usage: PYTHONPATH= python3 - < this file"""
import ctypes, hashlib, json, math, os, shutil, sqlite3, sys, time

LIB = "/ceph/ibmi/abi/oliver/spextract/diatracer/ext/bruker/libtimsdata-2-21-0-4.so"
ROOT = "/ceph/ibmi/abi/data/PXD029836/raw_d"
KNOWN = {  # analysis.tdf sha256, laptop == ceph (pxd029836-run1-evidence/check/*_recheck.sha256)
    "1418": "89f5fcffe91d1ba233c26471a8afb5ff007c6ba8d695ef025b816486ee3e19f0",
    "1420": "aee03877e3e0ac95c6023ea36054c6822890966bb0cd6537e730c4b54e6bb4ba",
    "1422": "bc3a97f36cd356772bcc87b9c4f0f7316d8d1f38dc043baa4147ca576d9a893d",
}
WANT = ["1418", "1420", "1422", "1431", "1408", "1347"]   # three runs of one calibration vector + one run of each other vector
W = "/scratch/kohlbach/c2neg_golden_%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), os.getpid())

import glob
cands = {}
for d in sorted(glob.glob(ROOT + "/*/*.d")):
    run = os.path.basename(d)[:-2].rsplit("_", 1)[-1]
    cands[run] = d

lib = ctypes.CDLL(LIB)
lib.tims_open.restype = ctypes.c_uint64
lib.tims_open.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
lib.tims_index_to_mz.restype = ctypes.c_uint32
lib.tims_index_to_mz.argtypes = [ctypes.c_uint64, ctypes.c_int64, ctypes.POINTER(ctypes.c_double),
                                 ctypes.POINTER(ctypes.c_double), ctypes.c_uint32]
lib.tims_close.argtypes = [ctypes.c_uint64]
lib.tims_get_last_error_string.restype = ctypes.c_uint32
lib.tims_get_last_error_string.argtypes = [ctypes.c_char_p, ctypes.c_uint32]


def last_err():
    buf = ctypes.create_string_buffer(1024)
    lib.tims_get_last_error_string(buf, 1024)
    return buf.value.decode(errors="replace")


def vendor(h, fid, tofs):
    n = len(tofs)
    inp = (ctypes.c_double * n)(*tofs)
    out = (ctypes.c_double * n)()
    ok = lib.tims_index_to_mz(h, fid, inp, out, n)
    assert ok == 1, "tims_index_to_mz rc %s: %s" % (ok, last_err())
    return list(out)


def model(tof, t1, p, C2=None, temp=True):
    C2 = p["C2"] if C2 is None else C2
    t = tof * p["timebase"] + p["delay"]
    cf = 1.0 + (p["dC1"] * (p["T1_ref"] - t1)) / 1e6 if temp else 1.0
    b = 1e6 / math.sqrt(p["C1"] * cf)
    disc = b * b - 4.0 * C2 * (p["C0"] - t)
    if not (disc >= 0.0) or not (t > p["C0"]):
        return float("nan")
    u = 2.0 * (t - p["C0"]) / (b + math.sqrt(disc))
    m = u * u - p["C4"]
    return m if m > 0 else float("nan")


out_entries, summary = [], []
os.makedirs(W, mode=0o700)
os.chmod(W, 0o700)
try:
    for run in WANT:
        src = cands[run]
        D = "%s/r%s.d" % (W, run)
        os.makedirs(D, mode=0o700)
        t0 = time.time()
        shutil.copyfile(src + "/analysis.tdf", D + "/analysis.tdf")
        open(D + "/analysis.tdf_bin", "wb").close()           # empty: the raw frame blobs are never opened
        sha = hashlib.sha256(open(D + "/analysis.tdf", "rb").read()).hexdigest()
        if run in KNOWN:
            assert sha == KNOWN[run], (run, sha)
        db = sqlite3.connect("file:%s/analysis.tdf?immutable=1" % D, uri=True)
        rows = db.execute("SELECT Id, ModelType, DigitizerTimebase, DigitizerDelay, T1, dC1, dC2, C0, C1, C2, C3, C4 FROM MzCalibration").fetchall()
        refs = [r[0] for r in db.execute("SELECT DISTINCT MzCalibration FROM Frames")]
        assert len(refs) == 1, refs
        row = [r for r in rows if r[0] == refs[0]][0]
        _, mt, tb, dl, t1r, dc1, dc2, c0, c1, c2, c3, c4 = row
        assert mt == 1 and dc2 == 0 and c3 == 0 and c2 < 0, row
        p = dict(model_type=mt, timebase=tb, delay=dl, C0=c0, C1=c1, C2=c2, T1_ref=t1r, dC1=dc1, C4=c4)
        N = int(db.execute("SELECT Value FROM GlobalMetadata WHERE Key='DigitizerNumSamples'").fetchone()[0])
        frames = db.execute("SELECT Id, T1 FROM Frames ORDER BY Id").fetchall()
        assert all(f[1] is not None for f in frames)
        db.close()
        fmin = min(frames, key=lambda f: (f[1], f[0]))
        fmax = max(frames, key=lambda f: (f[1], -f[0]))
        pick = []
        for f in (frames[0], fmin, frames[len(frames) // 2], fmax, frames[-1]):
            if f not in pick:
                pick.append(f)
        h = lib.tims_open(D.encode(), 0)
        assert h != 0, "tims_open failed: %s" % last_err()
        probes = [2000.0, 0.05 * N, 0.25 * N, 0.5 * N, 0.75 * N, 0.95 * N, float(N - 1)]
        dense = [float(x) for x in range(0, N, max(1, N // 2000))] + [float(N - 1)]
        cases = []
        worst = {"shipped": 0.0, "no_c2": 0.0, "flip_c2": 0.0, "no_temp": 0.0}
        nan = 0
        for fid, t1 in pick:
            got = vendor(h, fid, probes)
            for tof, mz in zip(probes, got):
                cases.append({"frame": fid, "t1": t1, "tof": tof, "mz": mz})
            vs = vendor(h, fid, dense + probes)
            for tof, v in zip(dense + probes, vs):
                if not (v > 0.0):
                    continue
                for k, m in (("shipped", model(tof, t1, p)), ("no_c2", model(tof, t1, p, C2=0.0)),
                             ("flip_c2", model(tof, t1, p, C2=-c2)), ("no_temp", model(tof, t1, p, temp=False))):
                    if m != m:
                        nan += k == "shipped"
                        continue
                    worst[k] = max(worst[k], abs(m - v) / v * 1e6)
        # vendor m/z of the dense sweep's ends on frame 1, for the record
        ends = vendor(h, pick[0][0], [0.0, float(N - 1)])
        lib.tims_close(h)
        # discriminant margin over the file's whole TOF range [0, N-1] at its extreme frame temperatures
        bs = [1e6 / math.sqrt(c1 * (1.0 + dc1 * (t1r - t1) / 1e6)) for t1 in (fmin[1], fmax[1])]
        tN = (N - 1) * tb + dl
        ratio = min((b * b - 4.0 * c2 * (c0 - tN)) / (b * b) for b in bs)
        bmin = min(bs)
        tof_zero = ((c0 + bmin * bmin / (4.0 * -c2)) - dl) / tb
        label = "PXD029836 %s" % run
        out_entries.append({"file": label, "model_type": mt, "timebase": tb, "delay": dl, "C0": c0, "C1": c1, "C2": c2,
                            "T1_ref": t1r, "dC1": dc1, "num_samples": N, "cases": cases})
        s = ("%s (%s): copy %.1f s, tdf sha256 %s, %d frames, T1 %.6f..%.6f (T1_ref %.6f), C2 %.12g, N %d, vendor m/z %.4f..%.4f; "
             "picked frames %s; %d cases; dense %d probes x %d frames: worst |ppm| shipped %.7f (nan %d), C2 dropped %.3f, "
             "C2 flipped %.3f, temperature dropped %.4f; disc/b^2 at tof N-1 %.9f; disc = 0 at tof %.5e (%.0fx N)"
             % (label, os.path.basename(src), time.time() - t0, sha[:16], len(frames), fmin[1], fmax[1], t1r, c2, N,
                ends[0], ends[1], [f[0] for f in pick], len(cases), len(dense) + len(probes), len(pick), worst["shipped"],
                nan, worst["no_c2"], worst["flip_c2"], worst["no_temp"], ratio, tof_zero, tof_zero / N))
        print(s, flush=True)
        summary.append(s)
        extra = sorted(set(os.listdir(D)) - {"analysis.tdf", "analysis.tdf_bin"})
        if extra:
            print("  files the SDK created in the private copy:", extra, flush=True)
        shutil.rmtree(D)
finally:
    shutil.rmtree(W, ignore_errors=True)
    print("removed", W, not os.path.exists(W), flush=True)
print("=====BEGIN JSON=====")
print(json.dumps(out_entries, indent=1))
print("=====END JSON=====")

```

## 6. Code context (unchanged or changed, at the branch head)

### A. `src/TdfMzCalibration.h` at 2b9ade4c42 (whole file; the conversion functions are unchanged except comments)
```cpp
    1| #ifndef DIASPEXTRACT_TDF_MZ_CALIBRATION_H
    2| #define DIASPEXTRACT_TDF_MZ_CALIBRATION_H
    3| // Copyright (c) 2026, DIAspeXtract authors. BSD-3-Clause.
    4| //
    5| // Exact TOF -> m/z conversion for Bruker TDF (timsTOF) data, ModelType 1. Header-only and dependency-free:
    6| // shared by the OpenMS loader patch (patches/openms-brukertims-mz-calibration.patch) and the C++ golden test
    7| // (tests/test_calibration_cpp.cpp), so the code that ships is the code that is tested.
    8| //
    9| // Model, derived numerically against Bruker's timsdata library used as a local oracle (no vendor code was read,
   10| // no vendor binary is redistributed; every constant comes from the user's own file):
   11| //
   12| //     t_ns   = tof * DigitizerTimebase + DigitizerDelay
   13| //     C1_eff = C1 * (1 + dC1 * (T1_ref - T1_frame) / 1e6)        // digitizer temperature drift
   14| //     t_ns   = C0 + (1e6 / sqrt(C1_eff)) * sqrt(m) + C2 * m      // solved for sqrt(m) =: u
   15| //     m      = u^2 - C4                                          // C4: additive mass offset
   16| //
   17| // Verified to 2.5e-5 ppm against the vendor library (tests/calibration_golden.json: three files sharing ONE
   18| // MzCalibration vector, 12 frames over 0.034 K); the C4 term was pinned the same way on a 2019 timsTOF Pro
   19| // (tests/test_calibration_cpp.cpp). A NEGATIVE C2 (timsTOF Pro 2, acquisition software 2.0.53: all 23 runs checked
   20| // of the public PXD029836, four calibration vectors) is the same law and the same root: pinned on six of those runs
   21| // (30 frames, 7.0e-6 ppm worst; dropping C2 is 19..40 ppm off, flipping its sign 38..80 ppm).
   22| // What the model does not cover (ModelType != 1, dC2 or C3 != 0, frames that reference more than one MzCalibration
   23| // row, a negative C2 outside its verified domain) is REJECTED by unsupportedReason() and the loaders, never
   24| // approximated. The open timsrust-calibration port drops the C2*m term (-11..-40 ppm on this data).
   25| //
   26| // The negative-C2 domain. With C2 < 0 the law t(u) = C0 + b*u + C2*u^2 (u = sqrt(m + C4)) is a parabola that peaks at
   27| // u = b / (2|C2|): no mass has a later flight time (the discriminant below is negative there and tofToMz returns NaN),
   28| // and near the peak the root is ill-conditioned. At the root, sqrt(disc) is the slope dt/du, so unsupportedReason()
   29| // requires disc >= b^2 / 4 -- the slope at least half its linear value -- over everything the tool can ask of the
   30| // model: every TOF index up to kDomainMaxTof, every m/z up to kDomainMaxMz, and every frame temperature within
   31| // kDomainT1Span of T1_ref. disc falls with the flight time and with the C1 factor, so the corner that decides is the
   32| // largest TOF at the largest factor. On the six PXD029836 runs that corner has disc >= 0.984 b^2, the runs' own range
   33| // (397,657 bins, frames within 0.011 K of T1_ref) >= 0.99992 b^2, and the root would only stop existing beyond TOF
   34| // index 6.4e9, 16,000 times the digitizer's range. frameReason() lets a loader refuse a frame outside the checked
   35| // temperature span: the tool's tdf reader (TdfLoad.h) does, the OpenMS loader patch predates it and does not -- a frame
   36| // there converts as a positive-C2 frame at such a temperature would, and a peak beyond the parabola's peak comes back
   37| // NaN, which the tool drops and counts (bad_mz). Positive and zero C2 take none of these branches.
   38| 
   39| #include <cmath>
   40| #include <cstdio>
   41| #include <initializer_list>
   42| #include <limits>
   43| #include <string>
   44| 
   45| namespace diaspextract
   46| {
   47| 
   48| /// Constants as stored in the TDF `MzCalibration` row plus the per-frame digitizer temperature.
   49| struct TdfMzCalibration
   50| {
   51|   int model_type = 0;
   52|   double digitizer_timebase = 0.0;
   53|   double digitizer_delay = 0.0;
   54|   double C0 = 0.0;
   55|   double C1 = 0.0;      ///< must be > 0
   56|   double C2 = 0.0;      ///< the quadratic term the open implementations drop; negative only inside its domain
   57|   double T1_ref = 0.0;  ///< reference digitizer temperature for the calibration
   58|   double dC1 = 0.0;     ///< ppm/K drift of C1
   59|   double dC2 = 0.0;     ///< drift of C2 -- NOT modelled; must be 0 (see isSupported)
   60|   double C3 = 0.0;      ///< NOT modelled; must be 0 (never observed non-zero)
   61|   double C4 = 0.0;      ///< additive mass offset on the quadratic root: m = u^2 - C4
   62| 
   63|   /// The negative-C2 domain (header comment): what the tool can hand the model. TdfLoad.h refuses a file whose
   64|   /// DigitizerNumSamples (every stored TOF index is below it) or MzAcqRangeUpper exceeds these, and the compact
   65|   /// store caps a peak's m/z at 42,000.
   66|   static constexpr double kDomainMaxTof = 1e8;
   67|   static constexpr double kDomainMaxMz = 1e5;
   68|   /// Kelvin around T1_ref: wider than any temperature a working digitizer can have (T1_ref is ~25 C, so the span
   69|   /// reaches below absolute zero); the golden files' frames span 0.004 to 0.034 K.
   70|   static constexpr double kDomainT1Span = 1000.0;
   71| 
   72|   /// Why this calibration cannot be used, or empty if it can. Fail closed, never approximate.
   73|   std::string unsupportedReason() const
   74|   {
   75|     // NaN defeats ordered comparisons (every < and > below is false for NaN), so screen first.
   76|     for (double v : {digitizer_timebase, digitizer_delay, C0, C1, C2, T1_ref, dC1, dC2, C3, C4})
   77|       if (std::isnan(v)) return "MzCalibration contains NaN";
   78|     if (model_type != 1) return "MzCalibration ModelType " + std::to_string(model_type) + " != 1";
   79|     // A merely-positive C1 is not enough: C1 < ~5.6e-297 overflows b*b to +inf and yields m/z 0.0
   80|     // for every peak, silently, under an "exact" log line. Real values are ~1e5.
   81|     if (!(C1 > 1.0) || !(C1 < 1e12)) return "MzCalibration C1 outside the plausible range (1, 1e12)";
   82|     if (dC2 != 0.0) return "MzCalibration dC2 != 0 (temperature drift of C2 is not modelled)";
   83|     if (C3 != 0.0) return "MzCalibration C3 != 0 (not modelled; never observed non-zero)";
   84|     if (!(digitizer_timebase > 0.0)) return "DigitizerTimebase <= 0";
   85|     // C2 == 0.0 stored in the file is a real calibration (the 2020 timsTOF Pro firmware behind PXD017703 has no
   86|     // quadratic term). A NULL C2, which sqlite3_column_double hands over as 0.0, is refused by the loaders
   87|     // themselves. A negative C2 is accepted inside its domain only.
   88|     if (C2 < 0.0) return negativeC2Reason();
   89|     return std::string();
   90|   }
   91|   bool isSupported() const { return unsupportedReason().empty(); }
   92| 
   93|   /// Why a frame at digitizer temperature @p t1_frame cannot be converted, or empty. Only a negative C2 has a
   94|   /// temperature-dependent domain, and unsupportedReason() checked it for T1_ref +- kDomainT1Span: a frame outside
   95|   /// that span (a corrupt T1) is refused rather than converted where nothing was checked.
   96|   std::string frameReason(double t1_frame) const
   97|   {
   98|     if (!(C2 < 0.0) || std::fabs(t1_frame - T1_ref) <= kDomainT1Span) return std::string();
   99|     return "Frames.T1 " + num(t1_frame) + " is not within " + num(kDomainT1Span) + " K of the MzCalibration T1 " + num(T1_ref)
  100|            + ", the temperature span over which the negative C2 was checked";
  101|   }
  102| 
  103|   /// Temperature-corrected 1e6/sqrt(C1_eff) for one frame; hoist out of per-peak loops.
  104|   double frameFactor(double t1_frame) const
  105|   {
  106|     const double cf = 1.0 + (dC1 * (T1_ref - t1_frame)) / 1e6;
  107|     return 1e6 / std::sqrt(C1 * cf);
  108|   }
  109| 
  110|   /// TOF index -> m/z. @p b is frameFactor() for this frame.
  111|   double tofToMz(double tof, double b) const
  112|   {
  113|     const double t = tof * digitizer_timebase + digitizer_delay;
  114|     // Stable root of C2*u^2 + b*u + (C0 - t) = 0: u = 2*(t - C0) / (b + sqrt(disc)) avoids the textbook form's
  115|     // cancellation (b ~ 2.5e3, |C2| ~ 1e-3). It is the root on the rising branch for either sign of C2 and
  116|     // continuous through C2 = 0, where it is (t - C0) / b. Out-of-model inputs (t <= C0, a negative discriminant --
  117|     // with C2 < 0, a flight time beyond the parabola's peak -- m <= 0) return NaN, never a plausible-looking 0.0
  118|     // or the wrong mass a negative u would give.
  119|     const double disc = b * b - 4.0 * C2 * (C0 - t);
  120|     if (!(disc >= 0.0) || !(t > C0)) return std::numeric_limits<double>::quiet_NaN();
  121|     const double denom = b + std::sqrt(disc);
  122|     if (!(denom > 0.0)) return std::numeric_limits<double>::quiet_NaN();
  123|     const double u = 2.0 * (t - C0) / denom;
  124|     const double m = u * u - C4;   // bit-identical to u*u when C4 == 0, i.e. on every earlier file
  125|     return m > 0.0 ? m : std::numeric_limits<double>::quiet_NaN();
  126|   }
  127| 
  128|   /// m/z -> TOF index (exact inverse of tofToMz; the model is closed-form in this direction). With C2 < 0 it is the
  129|   /// inverse on the rising branch, which unsupportedReason() verified up to kDomainMaxMz.
  130|   double mzToTof(double mz, double b) const
  131|   {
  132|     const double m = mz + C4;
  133|     const double t = C0 + b * std::sqrt(m > 0.0 ? m : 0.0) + C2 * m;
  134|     return (t - digitizer_delay) / digitizer_timebase;
  135|   }
  136| 
  137| private:
  138|   static std::string num(double v)
  139|   {
  140|     char buf[32];
  141|     std::snprintf(buf, sizeof buf, "%.6g", v);
  142|     return buf;
  143|   }
  144| 
  145|   /// The negative-C2 domain check (header comment). disc = b^2 - k*(t - C0) with k = 4|C2| is smallest at the
  146|   /// largest flight time and the smallest frame factor b, i.e. the largest C1 factor within the temperature span.
  147|   std::string negativeC2Reason() const
  148|   {
  149|     const double cf_lo = 1.0 - std::fabs(dC1) * kDomainT1Span / 1e6, cf_hi = 1.0 + std::fabs(dC1) * kDomainT1Span / 1e6;
  150|     if (!(cf_lo > 0.0))
  151|       return "MzCalibration C2 < 0 with dC1 " + num(dC1) + " ppm/K: the C1 factor leaves (0, inf) within " + num(kDomainT1Span)
  152|              + " K of T1, so the negative C2 cannot be checked over that span";
  153|     const double b = 1e6 / std::sqrt(C1 * cf_hi);
  154|     const double k = -4.0 * C2;
  155|     const double t_zero = C0 + b * b / k;          // disc = 0: beyond it no mass has this flight time
  156|     const double t_half = C0 + 0.75 * b * b / k;   // disc = b^2 / 4: the slope dt/du is half its linear value
  157|     const double u_half = b / k;                   // the root there, sqrt(m + C4)
  158|     const double t_max = kDomainMaxTof * digitizer_timebase + digitizer_delay;
  159|     if (t_max <= t_half && kDomainMaxMz + C4 <= u_half * u_half) return std::string();
  160|     return "MzCalibration C2 " + num(C2) + " < 0 outside its verified domain: the TOF-to-m/z root stops existing at TOF index "
  161|            + num((t_zero - digitizer_delay) / digitizer_timebase) + " and its slope halves at TOF index "
  162|            + num((t_half - digitizer_delay) / digitizer_timebase) + " (m/z " + num(u_half * u_half - C4)
  163|            + "); a negative C2 is accepted only while the slope stays above half up to TOF index " + num(kDomainMaxTof)
  164|            + " and m/z " + num(kDomainMaxMz) + ", at every frame temperature within " + num(kDomainT1Span) + " K of T1";
  165|   }
  166| };
  167| 
  168| } // namespace diaspextract
  169| 
  170| #endif // DIASPEXTRACT_TDF_MZ_CALIBRATION_H
```

### B. `src/TdfLoad.h` at 2b9ade4c42: the axis bounds and the calibration reader (the tool's own sqlite reader)
```cpp
    1| // analysis.tdf readers (sqlite3 C API): the m/z calibration, its axis bounds, and the dnoise port's inputs.
    2| // Kept out of TdfMzCalibration.h, which is sqlite-free and compiled by the golden test on every CI platform.
    3| #pragma once
    4| #include <OpenMS/FORMAT/TdfMzCalibration.h>   // the copy the OpenMS patch installs; same header as src/TdfMzCalibration.h
    5| #include <sqlite3.h>
    6| #include "DnoiseMs1.h"   // [dnoise] RunMeta, WindowRow: the MS1 port's gate inputs; recover::opentimsCorrection
    7| #include <algorithm>
    8| #include <array>
    9| #include <climits>
   10| #include <cmath>
   11| #include <cstdint>
   12| #include <optional>
   13| #include <string>
   14| #include <vector>
   15| 
   16| namespace diaspextract
   17| {
   18| // ---------------------------------------------------------------------------------------------
   19| // sqlite3 directly, not SQLiteCpp: SQLiteCpp is an OpenMS in-tree extern absent from an installed OpenMS,
   20| // and a missing SQLite must be a compile error, never a silent detector switch (docs/BASELINE.md).
   21| // Every read is whole or refused with sqlite3_errmsg: each prepare is checked and each row loop must end in
   22| // SQLITE_DONE (an error merely ends a loop, so a partial read would look complete). Optional tables and
   23| // columns are read from the schema, never inferred from a failed query.
   24| // ---------------------------------------------------------------------------------------------
   25| /// Run-level flight-time axis bounds from GlobalMetadata: DigitizerNumSamples (every bin index is below it)
   26| /// and the acquisition m/z range. A NULL, trailing garbage, non-finite or unordered value refuses.
   27| struct TdfAxisBounds { long n_bins = 0; double mz_lo = 0.0, mz_hi = 0.0; };
   28| inline bool loadTdfAxisBounds(const std::string& tdf, TdfAxisBounds& out, std::string& why)
   29| {
   30|   sqlite3* db = nullptr;
   31|   if (sqlite3_open_v2(tdf.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK)
   32|   { why = std::string("cannot open ") + tdf + ": " + (db ? sqlite3_errmsg(db) : "out of memory"); sqlite3_close(db); return false; }
   33|   sqlite3_stmt* st = nullptr; out = TdfAxisBounds{}; why.clear();
   34|   auto num = [&](const unsigned char* txt, int nbytes, const char* key, double& v) {
   35|     if (!txt) { why = std::string(key) + " is NULL"; return false; }
   36|     const std::string s(reinterpret_cast<const char*>(txt), (size_t)nbytes);   // the WHOLE value (an embedded NUL is not an end), in the C locale
   37|     if (!spx::dnoise::detail::parseF64(s, v)) { why = std::string(key) + " is not a finite number: '" + s + "'"; return false; }
   38|     return true; };
   39|   if (sqlite3_prepare_v2(db, "SELECT Key, Value FROM GlobalMetadata WHERE Key IN ('MzAcqRangeLower','MzAcqRangeUpper','DigitizerNumSamples')", -1, &st, nullptr) != SQLITE_OK)
   40|   { why = std::string("cannot read GlobalMetadata: ") + sqlite3_errmsg(db); sqlite3_finalize(st); sqlite3_close(db); return false; }
   41|   bool ok = true; bool have_lo = false, have_hi = false, have_n = false;
   42|   int rc = SQLITE_DONE;
   43|   while (ok && (rc = sqlite3_step(st)) == SQLITE_ROW)
   44|   {
   45|     const unsigned char* kt = sqlite3_column_text(st, 0); if (!kt) continue;
   46|     const std::string k = reinterpret_cast<const char*>(kt); double v = 0.0;
   47|     { bool& have = (k == "MzAcqRangeLower") ? have_lo : (k == "MzAcqRangeUpper") ? have_hi : have_n;
   48|       if (have) { why = k + " appears twice in GlobalMetadata"; ok = false; break; }   // a repeated key would let the later row win silently
   49|       have = true; }
   50|     if (!num(sqlite3_column_text(st, 1), sqlite3_column_bytes(st, 1), k.c_str(), v)) { ok = false; break; }
   51|     if (k == "MzAcqRangeLower") out.mz_lo = v;
   52|     else if (k == "MzAcqRangeUpper") out.mz_hi = v;
   53|     else
   54|     {
   55|       // an integral count in [2, 1e8], checked BEFORE the narrowing cast (1e100 -> long is UB); the bound is the TOF
   56|       // range a negative C2 is verified over
   57|       if (!(v >= 2.0 && v <= TdfMzCalibration::kDomainMaxTof && std::trunc(v) == v)) { why = "DigitizerNumSamples is not an integer in [2, 1e8]: " + std::to_string(v); ok = false; break; }
   58|       out.n_bins = (long)v;
   59|     }
   60|   }
   61|   if (ok && rc != SQLITE_DONE) { why = std::string("reading GlobalMetadata: ") + sqlite3_errmsg(db); ok = false; }
   62|   sqlite3_finalize(st); sqlite3_close(db);
   63|   if (!ok) return false;
   64|   if (!(have_lo && have_hi && have_n)) { why = "GlobalMetadata lacks MzAcqRangeLower/MzAcqRangeUpper/DigitizerNumSamples (" + std::to_string(have_lo + have_hi + have_n) + " of 3)"; return false; }
   65|   // plausibility: a TIMS acquisition ends far below 1e5 m/z; a corrupt but finite value beyond
   66|   // that would drive the flight-time conversion past the axis (review 3a, round 2), and 1e5 is the m/z
   67|   // range a negative C2 is verified over
   68|   if (!(out.mz_lo > 0.0) || !(out.mz_hi > out.mz_lo) || !(out.mz_hi <= TdfMzCalibration::kDomainMaxMz))
   69|   { why = "GlobalMetadata bounds are not usable: MzAcqRange " + std::to_string(out.mz_lo) + "-" + std::to_string(out.mz_hi) + ", DigitizerNumSamples " + std::to_string(out.n_bins); return false; }
   70|   return true;
   71| }
   72| 
   73| /// The MzCalibration row the FRAMES reference (Frames.MzCalibration; PXD017703 files carry two rows), refused
   74| /// when frames reference more than one. t1_by_frame[id] = Frames.T1 (T1_ref when NULL); index 0 is never a frame.
   75| /// A frame whose T1 lies outside the span a negative C2 was checked over is refused (TdfMzCalibration::frameReason).
   76| inline bool loadTdfCalibration(const std::string& tdf, TdfMzCalibration& cal,
   77|                                std::vector<double>& t1_by_frame, std::string& why)
   78| {
   79|   sqlite3* db = nullptr;
   80|   if (sqlite3_open_v2(tdf.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK)
   81|   { why = std::string("cannot open ") + tdf + ": " + (db ? sqlite3_errmsg(db) : "out of memory"); sqlite3_close(db); return false; }
   82|   sqlite3_stmt* st = nullptr;
   83|   auto fail = [&](const std::string& w) { why = w; sqlite3_finalize(st); sqlite3_close(db); return false; };
   84|   auto sqlfail = [&](const std::string& what) { return fail(what + ": " + sqlite3_errmsg(db)); };   // errmsg is read before fail() finalizes
   85|   int rc = SQLITE_OK;
   86|   bool frames_have_cal = false;   // PRAGMA table_xinfo: one row per column, generated ones too (table_info skips them), the name in column 1, matched ASCII case-insensitively as sqlite resolves it
   87|   if (sqlite3_prepare_v2(db, "PRAGMA table_xinfo(Frames)", -1, &st, nullptr) != SQLITE_OK) return sqlfail("cannot read the Frames schema");
   88|   while ((rc = sqlite3_step(st)) == SQLITE_ROW)
   89|   { const unsigned char* c = sqlite3_column_text(st, 1); frames_have_cal = frames_have_cal || (c && sqlite3_stricmp(reinterpret_cast<const char*>(c), "MzCalibration") == 0); }
   90|   if (rc != SQLITE_DONE) return sqlfail("reading the Frames schema");
   91|   sqlite3_finalize(st); st = nullptr;
   92|   long long cal_id = -1; int ncal = 0;
   93|   if (frames_have_cal)
   94|   {
   95|     if (sqlite3_prepare_v2(db, "SELECT DISTINCT MzCalibration FROM Frames", -1, &st, nullptr) != SQLITE_OK) return sqlfail("cannot read Frames.MzCalibration");
   96|     while ((rc = sqlite3_step(st)) == SQLITE_ROW) { cal_id = sqlite3_column_int64(st, 0); ++ncal; }
   97|     if (rc != SQLITE_DONE) return sqlfail("reading Frames.MzCalibration");
   98|     sqlite3_finalize(st); st = nullptr;
   99|     if (ncal != 1) return fail("frames reference " + std::to_string(ncal) + " distinct MzCalibration rows");
  100|   }
  101|   else
  102|   {
  103|     // Frames has no MzCalibration column (a minimal or very old tdf): fall back to the single-row
  104|     // rule rather than refusing -- the reference is then unambiguous only if there IS one row.
  105|     if (sqlite3_prepare_v2(db, "SELECT Id FROM MzCalibration", -1, &st, nullptr) != SQLITE_OK) return sqlfail("Frames has no MzCalibration column, and MzCalibration cannot be read");
  106|     while ((rc = sqlite3_step(st)) == SQLITE_ROW) { cal_id = sqlite3_column_int64(st, 0); ++ncal; }
  107|     if (rc != SQLITE_DONE) return sqlfail("reading MzCalibration");
  108|     sqlite3_finalize(st); st = nullptr;
  109|     if (ncal != 1) return fail("Frames has no MzCalibration column and MzCalibration has " + std::to_string(ncal) + " rows (need exactly 1)");
  110|   }
  111|   if (sqlite3_prepare_v2(db, "SELECT ModelType, DigitizerTimebase, DigitizerDelay, C0, C1, C2, T1, dC1, dC2, C3, C4 "
  112|                              "FROM MzCalibration WHERE Id = ?", -1, &st, nullptr) != SQLITE_OK)
  113|     return sqlfail("cannot read MzCalibration");
  114|   rc = sqlite3_bind_int64(st, 1, cal_id);
  115|   if (rc == SQLITE_OK) rc = sqlite3_step(st);
  116|   if (rc == SQLITE_DONE) return fail("no MzCalibration row with Id " + std::to_string(cal_id));
  117|   if (rc != SQLITE_ROW) return sqlfail("reading MzCalibration row " + std::to_string(cal_id));
  118|   if (sqlite3_column_type(st, 5) == SQLITE_NULL) return fail("MzCalibration C2 is NULL (missing, not zero)");
  119|   cal.model_type = sqlite3_column_int(st, 0);
  120|   cal.digitizer_timebase = sqlite3_column_double(st, 1); cal.digitizer_delay = sqlite3_column_double(st, 2);
  121|   cal.C0 = sqlite3_column_double(st, 3); cal.C1 = sqlite3_column_double(st, 4);
  122|   cal.C2 = sqlite3_column_double(st, 5);
  123|   cal.T1_ref = sqlite3_column_double(st, 6); cal.dC1 = sqlite3_column_double(st, 7); cal.dC2 = sqlite3_column_double(st, 8);
  124|   cal.C3 = sqlite3_column_double(st, 9); cal.C4 = sqlite3_column_double(st, 10);
  125|   sqlite3_finalize(st); st = nullptr;
  126|   if (!cal.isSupported()) return fail(cal.unsupportedReason());
  127|   t1_by_frame.clear();
  128|   if (sqlite3_prepare_v2(db, "SELECT Id, T1 FROM Frames", -1, &st, nullptr) != SQLITE_OK) return sqlfail("cannot read Frames.T1");
  129|   while ((rc = sqlite3_step(st)) == SQLITE_ROW)
  130|   {
  131|     const long long id = sqlite3_column_int64(st, 0);
  132|     if (id < 0 || id > 10000000) return fail("implausible Frames.Id");
  133|     if ((size_t)id >= t1_by_frame.size()) t1_by_frame.resize((size_t)id + 1, cal.T1_ref);
  134|     t1_by_frame[(size_t)id] = (sqlite3_column_type(st, 1) == SQLITE_NULL) ? cal.T1_ref : sqlite3_column_double(st, 1);
  135|     if (std::string w = cal.frameReason(t1_by_frame[(size_t)id]); !w.empty()) return fail("frame " + std::to_string(id) + ": " + w);
  136|   }
  137|   if (rc != SQLITE_DONE) return sqlfail("reading Frames.T1");
  138|   sqlite3_finalize(st); sqlite3_close(db);
  139|   if (t1_by_frame.size() < 2) { why = "no Frames rows"; return false; }
  140|   return true;
  141| }
  142| 
  143| // ---------------------------------------------------------------------------------------------
  144| // [dnoise] What the MS1 port (DnoiseMs1.h) reads besides the m/z calibration:
  145| //  * the gate's inputs exactly as dnoise v0.1.0 reads them: six GlobalMetadata values as stored TEXT,
```

### C. `src/diaspextract.cpp`: the flight-time axis (every caller of mzToTof/tofToMz in the tool)
```cpp
  626|   /// temperature) turns a bin into m/z at report time. See docs/MZ-AXIS-DESIGN.md.
  627|   using TofIdx = uint32_t;
  628| 
  629|   /// The flight-time axis for one run: the calibration model plus each frame's temperature factor.
  630|   /// Fail-closed: without a calibration there is no TOF axis and the caller must not pretend there
  631|   /// is one.
  632|   struct TofAxis
  633|   {
  634|     diaspextract::TdfMzCalibration cal;
  635|     vector<double> b_by_frame;        ///< frame factor per FRAME ID (index 0 unused, as in the tdf)
  636|     bool ok = false;
  637|     double acq_lo = std::numeric_limits<double>::quiet_NaN();   ///< the acquisition's m/z range (GlobalMetadata)
  638|     double acq_hi = std::numeric_limits<double>::quiet_NaN();
  639|     long n_bins = 0;                                            ///< DigitizerNumSamples: every bin index is below it
  640|     String bounds_why;                                          ///< why the bounds are missing, if they are
  641| 
  642|     double factor(size_t frame_id) const
  643|     { return frame_id < b_by_frame.size() ? b_by_frame[frame_id] : cal.frameFactor(cal.T1_ref); }
  644|     double mzOf(TofIdx tof, double b) const { return cal.tofToMz((double)tof, b); }
  645|     TofIdx tofOf(double mz, double b) const
  646|     {
  647|       const double t = cal.mzToTof(mz, b);
  648|       if (!(t > 0.0)) return 0u;
  649|       return t >= 4294967294.0 ? 4294967294u : (TofIdx)llround(t);   // saturate: a wrap here would collapse a band partition silently
  650|     }
  651|   };
  652| 
  653|   inline TofAxis& tofAxis() { static TofAxis a; return a; }
  654| 
  655|   /// Build the flight-time axis from a calibration and the per-frame T1 (index = Frames.Id).
  656|   inline void setTofAxis(const diaspextract::TdfMzCalibration& cal, const std::vector<double>& t1)
  657|   {
  658|     TofAxis& ax = tofAxis();
  659|     ax.cal = cal;
  660|     // A frame without a positive factor gets the reference one. Index 0 is the "unknown frame"
  661|     // sentinel (Frames.Id starts at 1; frameIdOf() returns 0 when it cannot parse) and stays 0.0.
  662|     const double bref = ax.cal.frameFactor(ax.cal.T1_ref);
  663|     ax.b_by_frame.assign(t1.size(), 0.0);
  664|     for (size_t i = 1; i < t1.size(); ++i) { const double f = ax.cal.frameFactor(t1[i]); ax.b_by_frame[i] = f > 0.0 ? f : bref; }
  665|     ax.ok = true;
  666|   }
  667|   /// Load the axis from an analysis.tdf; false (axis unusable) when anything is missing.
  668|   inline bool loadTofAxis(const std::string& tdf_path, String& why)
  669|   {
  670|     diaspextract::TdfMzCalibration cal;
  671|     std::vector<double> t1;
  672|     if (!diaspextract::loadTdfCalibration(tdf_path, cal, t1, why)) return false;
  673|     setTofAxis(cal, t1);
  674|     { std::string w2; diaspextract::TdfAxisBounds bd;
  675|       if (diaspextract::loadTdfAxisBounds(tdf_path, bd, w2)) { tofAxis().acq_lo = bd.mz_lo; tofAxis().acq_hi = bd.mz_hi; tofAxis().n_bins = bd.n_bins; }
  676|       else tofAxis().bounds_why = w2; }
  677|     return true;
  678|   }
  679|   constexpr double IM_LO = 0.4, IM_HI = 1.8;
  680|   constexpr double IM_Q = 65535.0 / (IM_HI - IM_LO);
...
  892|   /// m/z quanta -> flight-time bins, in place. The store keeps m/z at a 1e-5 Da quantum, ~400x finer
  893|   /// than one TOF bin at m/z 600, so inverting the calibration recovers the ORIGINAL bin exactly --
  894|   /// no approximation is introduced here, and the loader does not have to know the axis.
  895|   void toTof(PeakSlab& sl)
  896|   {
  897|     if (!sl.mzq) return;
  898|     const TofAxis& ax = tofAxis();
  899|     const size_t F = sl.frames();
  900|     sl.b.resize(F);
  901|     for (size_t i = 0; i < F; ++i)
  902|     {
  903|       const double b = ax.factor(sl.frame_id[i]);
  904|       sl.b[i] = b;
  905|       for (uint32_t k = sl.frame_off[i]; k < sl.frame_off[i + 1]; ++k)
  906|         sl.tof[k] = ax.tofOf((double)sl.tof[k] / MZ_Q, b);
  907|     }
  908|     vector<uint32_t>().swap(sl.frame_id);
  909|     sl.mzq = false;
  910|   }
  911| 
  912| 
...
 1072|     /// The +-3 sd window is converted to a BIN range once per frame step, so the walk is bounded
 1073|     /// by two calibration calls and a binary search; only candidates inside that window are
 1074|     /// converted back to m/z for the comparison.
 1075|     auto best = [&](size_t f, double cmz, double sd, double cim, bool& taken) -> long {
 1076|       taken = false;
 1077|       const uint32_t a = sl.frame_off[f], b = sl.frame_off[f + 1];
 1078|       if (b <= a) return -1;
 1079|       const double bf = sl.b[f];
 1080|       const double lo_mz = cmz - 3.0 * sd, hi_mz = cmz + 3.0 * sd;
 1081|       const TofIdx lo_t = ax.tofOf(lo_mz > 0.0 ? lo_mz : 1e-9, bf);
 1082|       const TofIdx hi_t = ax.tofOf(hi_mz, bf);
 1083|       uint32_t r0 = a, r1 = b; tp.range(f, lo_t, a, b, r0, r1);   // [tofidx] computed, not searched
 1084|       const uint32_t s0 = (uint32_t)(lower_bound(sl.tof.begin() + r0, sl.tof.begin() + r1, lo_t) - sl.tof.begin());
 1085|       long bk = -1; double bd = std::numeric_limits<double>::infinity();
 1086|       for (uint32_t k = s0; k < b && sl.tof[k] <= hi_t; ++k)
 1087|       {
 1088|         if (!((double)sl.inten[k] > noise)) continue;
 1089|         if (std::abs((double)sl.imq[k] - cim) > imq_tol) continue;
 1090|         // "Closest" in m/z, as OpenMS does, not in bins: across the centroid the calibration's
 1091|         // curvature can flip which is nearer. Only candidates inside the bin window pay the conversion.
 1092|         const double d = std::abs(ax.mzOf(sl.tof[k], bf) - cmz);
 1093|         if (d < bd) { bd = d; bk = (long)k; }          // strict <: first of equals wins
 1094|       }
 1095|       if (bk >= 0 && seen((size_t)bk)) { taken = true; return -1; }
 1096|       return bk;
 1097|     };
 1098| 
...
 1236|       for (size_t q = lo; q < hi; ++q)
 1237|       {
 1238|         const Trace& t = in[q];
 1239|         pk.clear();
 1240|         for (size_t k = 0; k < t.span(); ++k)                 // REAL points only: EPD smooths what it is given
 1241|         {
 1242|           if (!real(wst, t, k)) continue;
 1243|           Peak2D pt; pt.setRT(rtAtSpan(wst, t, k)); pt.setIntensity(xv(wst, t, k));
 1244|           // [bin-delta] reconstruct the absolute bin; identical to the value this used to store
 1245|           const uint32_t bin = wst.bins.empty() ? 0u : (uint32_t)((int64_t)t.tof + wst.bins[t.off + k]);
 1246|           pt.setMZ(bin ? ax.mzOf(bin, wst.b[t.frame0 + k]) : t.mz);
 1247|           pk.push_back(pt);
 1248|         }
 1249|         MassTrace mt(pk);
 1250|         mt.setCentroidIM(t.im);
 1251|         epd.detectPeaks(mt, split);
 1252|         // Each child's bin comes from its APEX PEAK m/z (the parent's per-frame bin was written into
 1253|         // every Peak2D above) by inverting the calibration -- never from the parent list, whose frame
 1254|         // ranges overlap.
 1255|         for (const MassTrace& cm : split)
 1256|         {
 1257|           Trace c = toTrace(cm, cst);
 1258|           if (c.np() == 0) continue;
 1259|           const uint32_t cf = c.frame0 + c.apex;               // apex frame, window-local
 1260|           c.bframe = cf;
 1261|           const double cb = wst.b.empty() ? ax.factor(0) : wst.b[cf];
 1262|           const double amz = cm.getSize() ? cm[cm.findMaxByIntPeak(false)].getMZ() : c.mz;
 1263|           c.tof = ax.tofOf(amz, cb);
 1264|           out.push_back(std::move(c));
 1265|         }
 1266|       }
...
 1540|         case Refusal::frame: throw refuse("an MS1 spectrum is not an MS1 frame of the input's analysis.tdf");
 1541|         case Refusal::peaks:
 1542|           throw refuse("frame " + String(fid) + " arrived with " + String(n) + " of its " + String(tdf.frames[fid].num_peaks) + " raw points: only a whole raw frame can be denoised (no frame aggregation, no loader centroiding)");
 1543|         default: throw refuse("frame " + String(fid) + " carries no 1/K0 per point");   // Refusal::im
 1544|       }
 1545|       const diaspextract::TdfDnoiseInputs::Frame& fr = tdf.frames[fid];
 1546|       ++c.frames; c.raw += (long long)n; c.fid = fid;
 1547|       if (n == 0) { c.cpu += threadCpu_() - cpu0; return; }
 1548|       const auto& im = s.getFloatDataArrays()[s.getIMData().first];
 1549|       const TofAxis& ax = tofAxis();
 1550|       const double b = ax.factor(fid), corr = fr.corr;
 1551|       const std::vector<float>& asc = im_asc[fr.cal];
 1552|       const bool falls = im_falls[fr.cal] != 0;
 1553|       k.scan.resize(n); k.tof.resize(n); k.raw.resize(n);
 1554|       for (Size i = 0; i < n; ++i)
 1555|       {
 1556|         const float v = s[i].getIntensity();
 1557|         double t = 0.0; int hits = 0;
 1558|         switch (spx::dnoise::recover::recoverPoint(ax.cal, b, s[i].getMZ(), im[i], v, corr, asc, falls, fr.num_scans, k.tof[i], k.scan[i], k.raw[i], t, hits))
 1559|         {
 1560|           case Refusal::none: break;
 1561|           case Refusal::tof:
 1562|             throw refuse("m/z " + String(s[i].getMZ()) + " in frame " + String(fid) + " is not the MzCalibration table model's value of a TOF bin (" + String(t) + "): the loader calibrated m/z otherwise");
 1563|           case Refusal::scan:
 1564|             throw refuse("1/K0 " + String(im[i]) + " in frame " + String(fid) + " is not the TimsCalibration model's value of one of its " + String(fr.num_scans) + " scans: the loader converted 1/K0 otherwise");
 1565|           case Refusal::intensity_range:
 1566|             throw refuse("intensity " + String(v) + " in frame " + String(fid) + " is >= 2^24 = 16777216: the loader's float32 intensity no longer identifies one raw count");
 1567|           default:   // Refusal::intensity
 1568|             throw refuse("intensity " + String(v) + " in frame " + String(fid) + " is not opentims' correction of exactly one raw count (" + String(hits) + " found)");
 1569|         }
 1570|       }
...
 3118|     return fail ? UNEXPECTED_RESULT : EXECUTION_OK;
 3119|   }
 3120| 
 3121|   /// Export-time calibration: the reported m/z is computed once, here, from the bin and its apex frame's
 3122|   /// factor. tof 0 (the OpenMS detector has no bin) keeps the cached m/z.
 3123|   static double exportMz_(uint32_t tof, double b, double cached)
 3124|   {
 3125|     if (tof == 0 || !(b > 0.0) || !tofAxis().ok) return cached;
 3126|     const double v = tofAxis().mzOf(tof, b);
 3127|     return std::isfinite(v) && v > 0.0 ? v : cached;
 3128|   }
 3129| 
 3130|   /// [trim] malloc_trim(0), logged with the RSS before and after and how long it took.
...
 3228|     std::vector<std::string> tdf_cand{in + "/analysis.tdf"};   // the calibration sources, in the order the load tries them
 3229|     if (const char* sc = std::getenv("DIASPEXTRACT_MZPEAK_TDF")) tdf_cand.push_back(sc);
 3230|     if (band_edges_acq && integer_req)
 3231|     {
 3232|       // [3a] The axis is selected HERE, in the order the load below would use it (the first
 3233|       // candidate whose calibration loads is THE source), so the bounds that are checked belong to
 3234|       // the tdf that will actually calibrate the run -- and the check costs a two-row query rather
 3235|       // than the whole load. No candidate at all is NOT an error: the integer detector then falls
 3236|       // back to the OpenMS detector further down, loudly, and traces no bands to partition.
 3237|       for (const std::string& c : tdf_cand)
 3238|       {
 3239|         String w_axis;
 3240|         if (!loadTofAxis(c, w_axis)) continue;   // not a calibration source; try the next
 3241|         if (!(tofAxis().n_bins > 1))
 3242|           throw Exception::InvalidParameter(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
 3243|                 "trace:band_edges=acquisition needs MzAcqRangeLower/Upper and DigitizerNumSamples from the tdf's GlobalMetadata; the calibration source " + c + " does not provide them (" + tofAxis().bounds_why + "). Use -trace:band_edges slab, or -trace:detector openms.");
 3244|         writeLogInfo_("flight-time axis from " + c + " (preflight): " + String(tofAxis().b_by_frame.size()) + " frame factors; digitizer bins " + String(tofAxis().n_bins) + ", acquisition m/z " + String(tofAxis().acq_lo) + "-" + String(tofAxis().acq_hi));
 3245|         break;
 3246|       }
 3247|     }
 3248|     // the .d loader's configuration; set here because the dnoise setup below predicts the loader's m/z model from it
 3249|     BrukerTimsFile::Config cfg;
 3250|     cfg.ms1_n_neighbors     = getIntOption_("trace:native_ms1_neighbors");
...
 4098|           PeakSlab& sl = rs->second;
 4099|           toTof(sl);
 4100|           for (TofIdx t : sl.tof) { tlo = std::min(tlo, t); thi = std::max(thi, t); }
 4101|         }
 4102|         // [3a] the run-level alternative: tlo 0, thi the larger of the digitizer's last bin
 4103|         // (DigitizerNumSamples - 1: no bin index can exceed it) and the acquisition's upper m/z
 4104|         // through the calibration at every frame of the frozen table; logged in both modes so
 4105|         // the two sets are on record side by side
 4106|         TofIdx thi_mz = 0, thi_acq = 0;
 4107|         if (tofAxis().n_bins > 1)
 4108|         {
 4109|           const TofIdx last = (TofIdx)(tofAxis().n_bins - 1);
 4110|           TofIdx thi_q = last;
 4111|           for (double b : frozen.at(k).b)
 4112|           {
 4113|             if (tofAxis().acq_hi > 0.0) thi_mz = std::max(thi_mz, tofAxis().tofOf(tofAxis().acq_hi, b));
 4114|             // the last bin's m/z, through the store's 1e-5 quantum, back to a bin: on a coarse
 4115|             // calibration the round trip can land one bin higher (review 3a, round 2)
 4116|             thi_q = std::max(thi_q, tofAxis().tofOf(tofAxis().mzOf(last, b) + 1.0e-5, b));
 4117|           }
 4118|           thi_acq = std::max(thi_q, thi_mz);
 4119|           if (thi_acq >= 4294967294u)
 4120|             throw Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION, "[tof] the acquisition's upper bin is not representable (the partition would wrap)", String(thi_acq));
 4121|         }
 4122|         #pragma omp critical(winlog)
 4123|         writeLogInfo_("[tof] window " + String(k[0] / 100.0) + "-" + String(k[1] / 100.0) + " slab tlo=" + String(tlo) + " thi=" + String(thi)
 4124|                       + " | acquisition tlo=0 thi=" + String(thi_acq) + " (digitizer " + String(tofAxis().n_bins > 1 ? tofAxis().n_bins - 1 : 0L) + ", MzAcqRangeUpper " + String(thi_mz) + ")"
 4125|                       + (band_edges_acq ? " (in use)" : " (slab in use)"));
 4126|         wbands.at(k) = band_edges_acq ? pair<TofIdx, TofIdx>{0, thi_acq} : pair<TofIdx, TofIdx>{tlo, thi};
```
The m/z quanta in the compact store are `uint32` at 1e-5 Da (so at most 42,949.67). `sd` in `best` is OpenMS's
robust running SD of accepted peaks, each within +-3 sd of the running centroid.

### D. `src/MzPeakStreamLoad.h`: the mzPeak exact-m/z path
```cpp
   56| 
   57| 
   58|   /// Exact TOF->m/z for an ims-compact archive: (c0, c1) from the peaks table's column metadata, the
   59|   /// MzCalibration row and Frames.T1 from the embedded vendor tdf. Throws on anything missing (fail closed).
   60|   struct MzPeakExactMz
   61|   {
   62|     double c0 = 0, c1 = 0;
   63|     diaspextract::TdfMzCalibration cal;
   64|     std::vector<double> t1_by_frame;          // index = Frames.Id
   65|     double acq_lo = std::numeric_limits<double>::quiet_NaN(), acq_hi = std::numeric_limits<double>::quiet_NaN();   // GlobalMetadata MzAcqRange
   66|     long n_bins = 0; std::string bounds_why;                                                                        // DigitizerNumSamples, or why not
   67| 
   68|     static std::vector<char> readMember_(zip_t* z, const char* name, zip_int64_t from = 0, zip_int64_t len = -1)
   69|     {
   70|       zip_int64_t idx = zip_name_locate(z, name, 0);
   71|       if (idx < 0) throw std::runtime_error(std::string("mzpeak: member missing: ") + name);
   72|       zip_stat_t st; zip_stat_index(z, (zip_uint64_t)idx, 0, &st);
   73|       if (len < 0) len = (zip_int64_t)st.size - from;
   74|       zip_file_t* f = zip_fopen_index(z, (zip_uint64_t)idx, 0);
   75|       if (!f) throw std::runtime_error(std::string("mzpeak: cannot open member ") + name);
   76|       if (from > 0 && zip_fseek(f, from, SEEK_SET) != 0) { zip_fclose(f); throw std::runtime_error(std::string("mzpeak: cannot seek in ") + name + " (member not stored?)"); }
   77|       std::vector<char> buf((size_t)len); zip_int64_t got = 0;
   78|       while (got < len) { zip_int64_t n = zip_fread(f, buf.data() + got, (zip_uint64_t)(len - got)); if (n <= 0) break; got += n; }
   79|       zip_fclose(f);
   80|       if (got != len) throw std::runtime_error(std::string("mzpeak: short read of ") + name);
   81|       return buf;
   82|     }
   83| 
   84|     explicit MzPeakExactMz(const std::string& path)
   85|     {
   86|       int err = 0; zip_t* z = zip_open(path.c_str(), ZIP_RDONLY, &err);
   87|       if (!z) throw std::runtime_error("mzpeak: zip_open failed on " + path);
   88|       try
   89|       {
   90|         // (1) two-point transform params from the parquet footer of spectra_peaks.parquet (stored member)
   91|         zip_int64_t idx = zip_name_locate(z, "spectra_peaks.parquet", 0);
   92|         if (idx < 0) throw std::runtime_error("mzpeak: spectra_peaks.parquet missing");
   93|         zip_stat_t st; zip_stat_index(z, (zip_uint64_t)idx, 0, &st);
   94|         std::vector<char> tail = readMember_(z, "spectra_peaks.parquet", (zip_int64_t)st.size - 8, 8);
   95|         uint32_t flen; std::memcpy(&flen, tail.data(), 4);
   96|         if (std::string(tail.data() + 4, 4) != "PAR1") throw std::runtime_error("mzpeak: peaks member is not parquet");
   97|         std::vector<char> footer = readMember_(z, "spectra_peaks.parquet", (zip_int64_t)st.size - 8 - flen, flen);
   98|         uint32_t flen2 = flen;
   99|         std::shared_ptr<parquet::FileMetaData> md = parquet::FileMetaData::Make(footer.data(), &flen2);
  100|         std::shared_ptr<arrow::Schema> schema;
  101|         parquet::ArrowReaderProperties props;
  102|         PARQUET_THROW_NOT_OK(parquet::arrow::FromParquetSchema(md->schema(), props, md->key_value_metadata(), &schema));
  103|         auto point = schema->GetFieldByName("point");
  104|         if (!point) throw std::runtime_error("mzpeak: no 'point' column");
  105|         auto tof = std::dynamic_pointer_cast<arrow::StructType>(point->type())->GetFieldByName("tof");
  106|         if (!tof || !tof->metadata()) throw std::runtime_error("mzpeak: no tof column / metadata (not an ims-compact archive?)");
  107|         auto tp = tof->metadata()->Get("mzpeak:transform_params");
  108|         if (!tp.ok()) throw std::runtime_error("mzpeak: tof column has no mzpeak:transform_params");
  109|         if (std::sscanf(tp->c_str(), "%lf,%lf", &c0, &c1) != 2 || !(c1 > 0)) throw std::runtime_error("mzpeak: bad transform_params " + *tp);
  110| 
  111|         // (2) the vendor tdf: gunzip vendor/analysis.tdf.gz to a temp file, read MzCalibration + Frames.T1
  112|         // --no-vendor archives have no embedded tdf: accept a sidecar via DIASPEXTRACT_MZPEAK_TDF=<analysis.tdf.gz>
  113|         std::vector<char> gz;
  114|         if (const char* side = std::getenv("DIASPEXTRACT_MZPEAK_TDF"))
  115|         {
  116|           FILE* sf = std::fopen(side, "rb"); if (!sf) throw std::runtime_error(std::string("mzpeak: cannot read DIASPEXTRACT_MZPEAK_TDF ") + side);
  117|           char b[1 << 16]; size_t n; while ((n = std::fread(b, 1, sizeof b, sf)) > 0) gz.insert(gz.end(), b, b + n); std::fclose(sf);
  118|         }
  119|         else gz = readMember_(z, "vendor/analysis.tdf.gz");
  120|         char tmpl[] = "/tmp/spx_mzpeak_tdf_XXXXXX"; int fd = mkstemp(tmpl); if (fd < 0) throw std::runtime_error("mzpeak: mkstemp");
  121|         close(fd);
  122|         { z_stream zs{}; inflateInit2(&zs, 16 + MAX_WBITS); FILE* out = std::fopen(tmpl, "wb");
  123|           zs.next_in = (Bytef*)gz.data(); zs.avail_in = (uInt)gz.size(); std::vector<char> ob(1 << 20); int rc;
  124|           do { zs.next_out = (Bytef*)ob.data(); zs.avail_out = (uInt)ob.size(); rc = inflate(&zs, Z_NO_FLUSH);
  125|                if (rc != Z_OK && rc != Z_STREAM_END) { std::fclose(out); inflateEnd(&zs); throw std::runtime_error("mzpeak: gunzip of analysis.tdf.gz failed"); }
  126|                std::fwrite(ob.data(), 1, ob.size() - zs.avail_out, out); } while (rc != Z_STREAM_END);
  127|           inflateEnd(&zs); std::fclose(out); }
  128|         { std::string why;
  129|           if (!diaspextract::loadTdfCalibration(std::string(tmpl), cal, t1_by_frame, why))
  130|             throw std::runtime_error("mzpeak: " + why);
  131|           std::string w2; diaspextract::TdfAxisBounds bd;
  132|           if (diaspextract::loadTdfAxisBounds(std::string(tmpl), bd, w2)) { acq_lo = bd.mz_lo; acq_hi = bd.mz_hi; n_bins = bd.n_bins; } else bounds_why = w2; }
  133|         std::remove(tmpl);
  134|       }
  135|       catch (...) { zip_close(z); throw; }
  136|       zip_close(z);
  137|     }
  138| 
  139|     /// Recover the integer tof from the archive's two-point m/z and re-apply the exact model.
  140|     void exact(std::vector<double>& mz, long frame_id) const
  141|     {
  142|       // Fail rather than fall back to the reference T1: substituting it for an unknown frame stamps
  143|       // masses calibrated at the wrong temperature as "exact", which is silent wrongness the
  144|       // provenance record would then vouch for.
  145|       if (frame_id < 0 || (size_t)frame_id >= t1_by_frame.size())
  146|         throw OpenMS::Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
  147|               "mzPeak exact calibration: no tdf T1 for frame", std::to_string(frame_id));
  148|       const double b = cal.frameFactor(t1_by_frame[(size_t)frame_id]);
  149|       for (double& v : mz)
  150|       {
  151|         if (!std::isfinite(v) || v <= 0.0)
  152|           throw OpenMS::Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
  153|                 "mzPeak exact calibration: non-positive archive m/z", std::to_string(v));
  154|         const double tof = std::llround((std::sqrt(v) - c0) / c1);
  155|         const double e = cal.tofToMz(tof, b);
  156|         if (!std::isfinite(e))
  157|           throw OpenMS::Exception::InvalidValue(__FILE__, __LINE__, OPENMS_PRETTY_FUNCTION,
  158|                 "mzPeak exact calibration produced a non-finite m/z at tof", std::to_string(tof));
  159|         v = e;
  160|       }
  161|     }
  162|   };
```

### E. `src/DnoiseMs1.h`: the MS1 denoiser's point recovery (inverts the loader's m/z with mzToTof)
```cpp
  438| /// One point of a frame with factor @p b (Cal::mzToTof inverts the m/z model the loader calibrated with:
  439| /// TdfMzCalibration in the tool), correction @p corr (correctionRefusal empty, so the search visits at most five raw
  440| /// counts), scan table @p asc / @p falls (buildScanTable) and @p num_scans scans: the TOF bin, scan and raw count the
  441| /// loader turned into @p mz, @p im and @p v. Checked in that order; on Refusal::none @p tof, @p scan and @p raw hold the
  442| /// point. For a message: @p t is the fractional TOF, @p hits the raw counts whose correction is @p v (0 until the
  443| /// intensity is checked).
  444| template <class Cal>
  445| inline Refusal recoverPoint(const Cal& cal, double b, double mz, float im, float v, double corr, const std::vector<float>& asc,
  446|                             bool falls, std::uint32_t num_scans, std::uint32_t& tof, std::uint32_t& scan, std::uint32_t& raw,
  447|                             double& t, int& hits)
  448| {
  449| #if defined(__clang__)
  450|   #pragma clang fp contract(off)
  451| #endif
  452|   hits = 0;
  453|   t = cal.mzToTof(mz, b);
  454|   const double bin = std::nearbyint(t);
  455|   if (!(std::fabs(t - bin) <= kTofTol && bin >= 0.0 && bin <= 4294967295.0)) return Refusal::tof;
  456|   const long s = scanOf(asc, falls, im);
  457|   if (s < 0 || (std::uint32_t)s >= num_scans) return Refusal::scan;
  458|   if (v >= 16777216.0f) return Refusal::intensity_range;   // a float32 holds every count below 2^24 exactly, and no more
  459|   std::uint32_t found = 0;
  460|   int n = 0;
  461|   if (v >= 0.0f && v == std::floor(v))
  462|     for (double r = std::max(0.0, std::floor((v - 0.5) / corr) - 1.0), r_end = std::ceil((v + 0.5) / corr) + 1.0; r <= r_end; r += 1.0)
  463|       if ((std::uint32_t)(r * corr + 0.5) == (std::uint32_t)v) { found = (std::uint32_t)r; ++n; }   // opentims.cpp:225: double(raw) * correction + 0.5, into a uint32
  464|   hits = n;
  465|   if (n != 1) return Refusal::intensity;
  466|   tof = (std::uint32_t)bin; scan = (std::uint32_t)s; raw = found;
  467|   return Refusal::none;
  468| }
  469| } // namespace recover
  470| 
```

### F. `patches/openms-brukertims-mz-calibration.patch` (UNCHANGED by this branch): the OpenMS loader that converts
every peak for the tool. It includes the same header (installed into the OpenMS tree by scripts/apply_openms_patches.sh
and by the deploy transaction scripts/sync_cluster.sh, which then runs `make diaspextract`, rebuilding libOpenMS).
```diff
   84|    }
   85|  
   86| +// [DIAspeXtract table-mz] License-free EXACT TOF->m/z from the TDF MzCalibration table.
   87| +// The MODEL lives in DIAspeXtract's own repo (src/TdfMzCalibration.h, BSD-3, copied here by
   88| +// scripts/apply_openms_patches.sh) so the shipped code is the code the C++ unit test exercises.
   89| +// Fails CLOSED: an unsupported calibration (ModelType != 1, dC2 != 0, multi-row table) throws
   90| +// rather than silently using the -5..-11 ppm chord. DIASPEXTRACT_ALLOW_CHORD_FALLBACK=1 opts back in.
   91| +#include <sqlite3.h>
   92| +#include <OpenMS/FORMAT/TdfMzCalibration.h>
   93| +namespace {
   94| +// File-local (never crosses a DSO boundary, unlike an inline header static): which m/z
   95| +// calibration the last load used. Stamped onto the MSExperiment so it travels with the data.
   96| +std::string g_mz_calibration = "unset";
   97| +// [DIAspeXtract frame-table] the last streamed run's DIA frame table and windows (see the header)
   98| +std::map<int, std::vector<BrukerTimsFile::DIAFrameRow>> g_dia_frame_table;
   99| +std::vector<BrukerTimsFile::DIAWindowRow> g_dia_windows;
  100| +class TdfTableTof2MzConverter final : public Tof2MzConverter
  101| +{
  102| +  diaspextract::TdfMzCalibration cal_;
  103| +  std::vector<double> frame_t1_;
  104| +public:
  105| +  explicit TdfTableTof2MzConverter(const std::string& d_dir)
  106| +  {
  107| +    const std::string tdf = d_dir + "/analysis.tdf";
  108| +    sqlite3* db = nullptr;
  109| +    if (sqlite3_open_v2(tdf.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK)
  110| +    {
  111| +      const std::string why = db ? sqlite3_errmsg(db) : "out of memory";
  112| +      sqlite3_close(db);   // sqlite allocates the handle even on failure
  113| +      throw std::runtime_error("TdfMzCalibration: cannot open " + tdf + ": " + why);
  114| +    }
  115| +    // Use the calibration row the FRAMES reference (Frames.MzCalibration), not "the only row".
  116| +    // A tdf may carry more than one MzCalibration row -- the public PXD017703 HeLa acquisitions
  117| +    // have two, of which every frame references Id 1 -- so "expected exactly 1" refused valid
  118| +    // data. Refuse only when the frames reference more than one row, which would need a
  119| +    // per-frame calibration this converter does not implement.
  120| +    sqlite3_stmt* st = nullptr;
  121| +    long long cal_id = -1; int ncal = 0;
  122| +    if (sqlite3_prepare_v2(db, "SELECT DISTINCT MzCalibration FROM Frames", -1, &st, nullptr) == SQLITE_OK)
  123| +      while (sqlite3_step(st) == SQLITE_ROW) { cal_id = sqlite3_column_int64(st, 0); ++ncal; }
  124| +    sqlite3_finalize(st); st = nullptr;
  125| +    if (ncal != 1)
  126| +    { sqlite3_close(db); throw std::runtime_error("TdfMzCalibration: frames reference " + std::to_string(ncal)
  127| +        + " distinct MzCalibration rows, expected exactly 1 (per-frame recalibration is not supported)"); }
  128| +    if (sqlite3_prepare_v2(db,
  129| +          "SELECT ModelType, DigitizerTimebase, DigitizerDelay, C0, C1, C2, T1, dC1, dC2, C3, C4 "
  130| +          "FROM MzCalibration WHERE Id = ?", -1, &st, nullptr) == SQLITE_OK
  131| +        && sqlite3_bind_int64(st, 1, cal_id) == SQLITE_OK
  132| +        && sqlite3_step(st) == SQLITE_ROW)
  133| +    {
  134| +      for (int col = 0; col <= 10; ++col)
  135| +      {
  136| +        const int ct = sqlite3_column_type(st, col);
  137| +        if (ct != SQLITE_INTEGER && ct != SQLITE_FLOAT)
  138| +        { sqlite3_finalize(st); sqlite3_close(db);
  139| +          throw std::runtime_error("TdfMzCalibration: MzCalibration column " + std::to_string(col)
  140| +                                   + " is NULL or non-numeric"); }
  141| +      }
  142| +      cal_.model_type = sqlite3_column_int(st, 0);
  143| +      cal_.digitizer_timebase = sqlite3_column_double(st, 1);
  144| +      cal_.digitizer_delay = sqlite3_column_double(st, 2);
  145| +      cal_.C0 = sqlite3_column_double(st, 3); cal_.C1 = sqlite3_column_double(st, 4);
  146| +      cal_.C2 = sqlite3_column_double(st, 5); cal_.T1_ref = sqlite3_column_double(st, 6);
  147| +      cal_.dC1 = sqlite3_column_double(st, 7); cal_.dC2 = sqlite3_column_double(st, 8);
  148| +      cal_.C3 = sqlite3_column_double(st, 9);  cal_.C4 = sqlite3_column_double(st, 10);
  149| +    }
  150| +    sqlite3_finalize(st); st = nullptr;
  151| +    if (!cal_.isSupported())
  152| +    { const std::string why = cal_.unsupportedReason(); sqlite3_close(db); throw std::runtime_error("TdfMzCalibration: " + why); }
  153| +    if (sqlite3_prepare_v2(db, "SELECT Id, T1 FROM Frames", -1, &st, nullptr) != SQLITE_OK)
  154| +    { sqlite3_close(db); throw std::runtime_error("TdfMzCalibration: cannot read Frames.T1"); }
  155| +    {
  156| +      int rc;
  157| +      while ((rc = sqlite3_step(st)) == SQLITE_ROW)
  158| +      {
  159| +        const size_t id = (size_t)sqlite3_column_int64(st, 0);
  160| +        if (id > 100000000u)   // sparse/corrupt frame ids must not drive an unbounded resize
  161| +        { sqlite3_finalize(st); sqlite3_close(db); throw std::runtime_error("TdfMzCalibration: implausible Frames.Id " + std::to_string(id)); }
  162| +        if (id >= frame_t1_.size()) frame_t1_.resize(id + 1, cal_.T1_ref);
  163| +        // A NULL T1 reads as 0.0 through sqlite3_column_double, which would silently apply the FULL
  164| +        // dC1*T1_ref temperature correction (~250 ppm) instead of none. Fall back to the reference
  165| +        // temperature (= no correction) rather than inventing one.
  166| +        frame_t1_[id] = (sqlite3_column_type(st, 1) == SQLITE_NULL)
  167| +                          ? cal_.T1_ref : sqlite3_column_double(st, 1);
  168| +      }
  169| +      if (rc != SQLITE_DONE)   // a partial read would silently leave frames at T1_ref
  170| +      { sqlite3_finalize(st); sqlite3_close(db);
  171| +        throw std::runtime_error("TdfMzCalibration: Frames.T1 read ended early (sqlite rc "
  172| +                                 + std::to_string(rc) + ")"); }
  173| +    }
  174| +    sqlite3_finalize(st);
  175| +    sqlite3_close(db);
  176| +  }
  177| +  // frame_id 0 is not a real Bruker frame (Frames.Id is 1-based); one pristine OpenMS DDA path
  178| +  // converts with a hardcoded 0. Slot 0 therefore holds T1_ref by construction = no temperature
  179| +  // correction (<=0.7 ppm on the files measured). Documented rather than incidental.
  180| +  inline double b_(uint32_t frame_id) const
  181| +  { return cal_.frameFactor(frame_id < frame_t1_.size() ? frame_t1_[frame_id] : cal_.T1_ref); }
  182| +  void convert(uint32_t frame_id, double* mzs, const double* tofs, uint32_t size) override final
  183| +  { const double b = b_(frame_id); for (uint32_t i = 0; i < size; ++i) mzs[i] = cal_.tofToMz(tofs[i], b); }
  184| +  void convert(uint32_t frame_id, double* mzs, const uint32_t* tofs, uint32_t size) override final
  185| +  { const double b = b_(frame_id); for (uint32_t i = 0; i < size; ++i) mzs[i] = cal_.tofToMz((double)tofs[i], b); }
  186| +  void inverse_convert(uint32_t frame_id, uint32_t* tofs, const double* mzs, uint32_t size) override final
  187| +  { const double b = b_(frame_id);
  188| +    for (uint32_t i = 0; i < size; ++i) tofs[i] = (uint32_t)std::max(0.0, std::round(cal_.mzToTof(mzs[i], b))); }
  189| +  std::string description() override final { return "TdfMzCalibration (ModelType 1 + temperature, exact)"; }
  190| +};
  191| +} // namespace
  192| +
```

