// Read the calibration a Bruker .d actually uses, straight from analysis.tdf via the sqlite3 C API.
// Kept OUT of TdfMzCalibration.h on purpose: that header is the pure arithmetic model, is installed
// into the OpenMS tree by the patch script, and is compiled by the dependency-free golden test on
// every CI platform -- including Windows, which has no sqlite3.h. Only the tool needs this file.
#pragma once
#include <OpenMS/FORMAT/TdfMzCalibration.h>   // the copy the OpenMS patch installs; same header as src/TdfMzCalibration.h
#include <sqlite3.h>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <string>
#include <vector>

namespace spextractor
{
// ---------------------------------------------------------------------------------------------
// Read the calibration a .d actually uses, straight from analysis.tdf with the sqlite3 C API.
//
// This deliberately does NOT use SQLiteCpp. That wrapper is an OpenMS in-tree extern whose headers
// are not on the include path of an OpenMS *installation*, so the two callers used to sit behind
// `#if __has_include(<SQLiteCpp/SQLiteCpp.h>)` -- false for the documented public build -- and fell
// back to "built without SQLiteCpp", which made the integer detector silently revert to `openms`.
// The stock-OpenMS CI caught it: 9/10 checks passed and the tenth said the shipped detector never
// ran. sqlite3.h is what OpenMS itself links, so a missing SQLite is now a compile error, never a
// behaviour switch.
//
// The row is the one the FRAMES reference (Frames.MzCalibration), not "the only row": PXD017703
// acquisitions carry two rows with every frame on Id 1. Refuses when frames reference more than
// one row (per-frame recalibration, unsupported). t1_by_frame[id] = Frames.T1, T1_ref when NULL;
// index 0 is never a frame (Ids start at 1) and is left for the caller to treat as a sentinel.
// ---------------------------------------------------------------------------------------------
/// The run-level bounds of the flight-time axis from GlobalMetadata: the digitizer's sample count
/// (every bin index is below it -- the absolute bound) and the acquisition's m/z range. Values are
/// TEXT in the tdf; a NULL, trailing garbage, a non-finite or unordered value refuses with a reason
/// rather than becoming a bound.
struct TdfAxisBounds { long n_bins = 0; double mz_lo = 0.0, mz_hi = 0.0; };
inline bool loadTdfAxisBounds(const std::string& tdf, TdfAxisBounds& out, std::string& why)
{
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(tdf.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK)
  { why = std::string("cannot open ") + tdf; sqlite3_close(db); return false; }
  sqlite3_stmt* st = nullptr; out = TdfAxisBounds{}; int seen = 0; why.clear();
  auto num = [&](const unsigned char* txt, int nbytes, const char* key, double& v) {
    if (!txt) { why = std::string(key) + " is NULL"; return false; }
    char* end = nullptr; const double x = std::strtod(reinterpret_cast<const char*>(txt), &end);
    // the parse must consume the WHOLE value (sqlite3_column_bytes: an embedded NUL is not an end)
    if (end == reinterpret_cast<const char*>(txt) || end != reinterpret_cast<const char*>(txt) + nbytes || !std::isfinite(x))
    { why = std::string(key) + " is not a finite number: '" + std::string(reinterpret_cast<const char*>(txt), (size_t)nbytes) + "'"; return false; }
    v = x; return true; };
  if (sqlite3_prepare_v2(db, "SELECT Key, Value FROM GlobalMetadata WHERE Key IN ('MzAcqRangeLower','MzAcqRangeUpper','DigitizerNumSamples')", -1, &st, nullptr) != SQLITE_OK)
  { why = "no GlobalMetadata table"; sqlite3_finalize(st); sqlite3_close(db); return false; }
  bool ok = true; bool have_lo = false, have_hi = false, have_n = false;
  while (ok && sqlite3_step(st) == SQLITE_ROW)
  {
    const unsigned char* kt = sqlite3_column_text(st, 0); if (!kt) continue;
    const std::string k = reinterpret_cast<const char*>(kt); double v = 0.0;
    { bool& have = (k == "MzAcqRangeLower") ? have_lo : (k == "MzAcqRangeUpper") ? have_hi : have_n;
      if (have) { why = k + " appears twice in GlobalMetadata"; ok = false; break; }   // a repeated key would let the later row win silently
      have = true; }
    if (!num(sqlite3_column_text(st, 1), sqlite3_column_bytes(st, 1), k.c_str(), v)) { ok = false; break; }
    if (k == "MzAcqRangeLower") out.mz_lo = v;
    else if (k == "MzAcqRangeUpper") out.mz_hi = v;
    else
    {
      // an integral count in [2, 1e8], checked BEFORE the narrowing cast (1e100 -> long is UB)
      if (!(v >= 2.0 && v <= 100000000.0 && std::trunc(v) == v)) { why = "DigitizerNumSamples is not an integer in [2, 1e8]: " + std::to_string(v); ok = false; break; }
      out.n_bins = (long)v;
    }
    ++seen;
  }
  sqlite3_finalize(st); sqlite3_close(db);
  if (!ok) return false;
  if (seen < 3) { why = "GlobalMetadata lacks MzAcqRangeLower/MzAcqRangeUpper/DigitizerNumSamples (" + std::to_string(seen) + " of 3)"; return false; }
  // plausibility: a TIMS acquisition ends far below 1e5 m/z; a corrupt but finite value beyond
  // that would drive the flight-time conversion past the axis (review 3a, round 2)
  if (!(out.mz_lo > 0.0) || !(out.mz_hi > out.mz_lo) || !(out.mz_hi <= 1.0e5) || out.n_bins < 2 || out.n_bins > 100000000L)
  { why = "GlobalMetadata bounds are not usable: MzAcqRange " + std::to_string(out.mz_lo) + "-" + std::to_string(out.mz_hi) + ", DigitizerNumSamples " + std::to_string(out.n_bins); return false; }
  return true;
}

inline bool loadTdfCalibration(const std::string& tdf, TdfMzCalibration& cal,
                               std::vector<double>& t1_by_frame, std::string& why)
{
  sqlite3* db = nullptr;
  if (sqlite3_open_v2(tdf.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK)
  { why = std::string("cannot open ") + tdf + ": " + (db ? sqlite3_errmsg(db) : "out of memory"); sqlite3_close(db); return false; }
  sqlite3_stmt* st = nullptr;
  long long cal_id = -1; int ncal = 0;
  if (sqlite3_prepare_v2(db, "SELECT DISTINCT MzCalibration FROM Frames", -1, &st, nullptr) == SQLITE_OK)
  {
    while (sqlite3_step(st) == SQLITE_ROW) { cal_id = sqlite3_column_int64(st, 0); ++ncal; }
    sqlite3_finalize(st); st = nullptr;
    if (ncal != 1) { why = "frames reference " + std::to_string(ncal) + " distinct MzCalibration rows"; sqlite3_close(db); return false; }
  }
  else
  {
    // Frames has no MzCalibration column (a minimal or very old tdf): fall back to the single-row
    // rule rather than refusing -- the reference is then unambiguous only if there IS one row.
    sqlite3_finalize(st); st = nullptr;
    if (sqlite3_prepare_v2(db, "SELECT Id FROM MzCalibration", -1, &st, nullptr) == SQLITE_OK)
      while (sqlite3_step(st) == SQLITE_ROW) { cal_id = sqlite3_column_int64(st, 0); ++ncal; }
    sqlite3_finalize(st); st = nullptr;
    if (ncal != 1) { why = "Frames has no MzCalibration column and MzCalibration has " + std::to_string(ncal) + " rows (need exactly 1)"; sqlite3_close(db); return false; }
  }
  if (sqlite3_prepare_v2(db, "SELECT ModelType, DigitizerTimebase, DigitizerDelay, C0, C1, C2, T1, dC1, dC2, C3, C4 "
                             "FROM MzCalibration WHERE Id = ?", -1, &st, nullptr) != SQLITE_OK
      || sqlite3_bind_int64(st, 1, cal_id) != SQLITE_OK || sqlite3_step(st) != SQLITE_ROW)
  { why = "no MzCalibration row with Id " + std::to_string(cal_id); sqlite3_finalize(st); sqlite3_close(db); return false; }
  cal.model_type = sqlite3_column_int(st, 0);
  cal.digitizer_timebase = sqlite3_column_double(st, 1); cal.digitizer_delay = sqlite3_column_double(st, 2);
  cal.C0 = sqlite3_column_double(st, 3); cal.C1 = sqlite3_column_double(st, 4);
  cal.C2 = (sqlite3_column_type(st, 5) == SQLITE_NULL) ? std::numeric_limits<double>::quiet_NaN()
                                                       : sqlite3_column_double(st, 5);
  cal.T1_ref = sqlite3_column_double(st, 6); cal.dC1 = sqlite3_column_double(st, 7); cal.dC2 = sqlite3_column_double(st, 8);
  cal.C3 = sqlite3_column_double(st, 9); cal.C4 = sqlite3_column_double(st, 10);
  sqlite3_finalize(st); st = nullptr;
  if (std::isnan(cal.C2)) { why = "MzCalibration C2 is NULL (missing, not zero)"; sqlite3_close(db); return false; }
  if (!cal.isSupported()) { why = cal.unsupportedReason(); sqlite3_close(db); return false; }
  t1_by_frame.clear();
  if (sqlite3_prepare_v2(db, "SELECT Id, T1 FROM Frames", -1, &st, nullptr) == SQLITE_OK)
    while (sqlite3_step(st) == SQLITE_ROW)
    {
      const long long id = sqlite3_column_int64(st, 0);
      if (id < 0 || id > 10000000) { why = "implausible Frames.Id"; sqlite3_finalize(st); sqlite3_close(db); return false; }
      if ((size_t)id >= t1_by_frame.size()) t1_by_frame.resize((size_t)id + 1, cal.T1_ref);
      t1_by_frame[(size_t)id] = (sqlite3_column_type(st, 1) == SQLITE_NULL) ? cal.T1_ref : sqlite3_column_double(st, 1);
    }
  sqlite3_finalize(st); sqlite3_close(db);
  if (t1_by_frame.size() < 2) { why = "no Frames rows"; return false; }
  return true;
}
} // namespace spextractor
