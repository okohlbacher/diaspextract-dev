
# tool-1

## [REFUTED/none] F5 (kimi): The D/TNBC digest pins, the resident dnoise-on arm and the completeness check had not been run on the fix-pass binary (sha bcda6bfa). requireComplete() could then falsely refuse real .d files if a loader skipped a non-empty MS1 frame.

EVIDENCE: Accurate at review time (brief 4.4), but closed since. Nothing is left to fix.

(1) Pins now run on sha bcda6bfa. The published arm dnoise_s2c was provenance-checked in the driver. Logs: SP/fixg/gates/fixg_gate_D.log and fixg_gate_T.log, mirrored at ibminode05:/scratch/kohlbach/fixg_gate_D.log.
- D, dnoise off: G1 (prune off) and G2 give 8c1b047f, PASS.
- D, dnoise on: G3 (stream) and G4 (SPEXTRACTOR_TILE_RESIDENT=1) give e43672a0, PASS.
- D resident: G5 (-perf:stream_load false, dnoise on) exits 0 with digest e43672a0, and [perf] LOAD(full) ran.
- G5 printed '[dnoise] ... MS1: 1343 frames (2 emptied), 927158066 raw points ...'. That line comes after dnoise.requireComplete() at src/spextractor.cpp:4329, so the completeness check ran on a real .d on the resident path and passed.
- G5 vs G3: [det] MS1 traces digest and the [dnoise] summary and setup lines are EQUAL.
- c3 r1_res, r2_fb, r1d_res and r2d_fb: PASS, equal to the previous gate.
- TNBC: T1 bff54a1f PASS, T2 3aafd0b5 PASS.

(2) The false-refusal case cannot happen in the code. I read the cluster build's sources: BrukerTimsFile.cpp sha 52230ba7 (identical to SP/cl) and _deps/opentims-src.
- opentims read_sql (opentims.cpp:287) fills frame_descs from 'SELECT Id, ... from Frames', i.e. every row. has_frame is frame_descs.count (opentims.h:301), and min/max frame ids come from the same map.
- The loader collects MS1 ids as has_frame && msms_type==0 over [min,max]: streaming at :1546-1549, resident loadDIA_ at :2372-2376.
- It emits exactly one spectrum per id unconditionally: :1614 consumeSpectrum, and exp.addSpectrum in loadDIA_. An empty frame is delivered as an empty level-1 spectrum (:1194/:1241), not skipped.
- load_ms1 is false only in tile pass 2 (spextractor.cpp:5256), which runs after the check.
- MS1 aggregation and an SDK path are refused at dnoise setup (:3987, :3995).
- FullSwathFileConsumer::consumeSpectrum passes every level-1 spectrum to consumeMS1Spectrum_ (SwathFileConsumer.h:194-197). That buffers each one (:2163), and finish() flushes the tail (:2249).
- The resident loop filters every MS1 spectrum before the IM skip (:4270).
- loadTdfDnoise reads the same Frames table (TdfLoad.h:275).
- So the frames requireComplete demands are exactly the frames both loaders deliver.

FIX: None needed. The main session should cite fixg_gate_D.log and fixg_gate_T.log (sha bcda6bfa) as the identity evidence in place of brief 4.4's 'not yet run'.

TEST: Already run: SP/fixg/gates/driver_D.sh (G1-G5 plus the c3 arms) and driver_T.sh (T1, T2), all PASS.


## [REFUTED/none] F8 (codex): With SPEXTRACTOR_LOAD_ONLY set, the run returns EXECUTION_OK before requireComplete(), so a streaming loader that silently omits a non-empty MS1 frame would go undetected.

EVIDENCE: The control flow is as described: the return at src/spextractor.cpp:4141-4143 comes before :4329. The failure is not reachable, for four reasons.
- LOAD_ONLY is honoured only inside the streaming try block. If the stream fails, the resident fallback ignores LOAD_ONLY and reaches requireComplete, with marks cleared at :4205.
- On that streaming path no non-empty MS1 frame can go missing (same evidence as F5):
  - loadDIAStreaming collects every Frames row with MsMsType 0 from opentims' full 'SELECT ... from Frames' (:1546-1549);
  - load_ms1 is true in pass 1, and dnoise setup refuses aggregation and an SDK path (:3987, :3995);
  - it hands every one to consumeSpectrum (:1614), which routes it to consumeMS1Spectrum_ and buffers it (:2163);
  - finish() flushes the tail (:2249) before the LOAD_ONLY check;
  - TileProbe drops MS2 frames only (:2110), and pass 1 sets only the MS2 RT bounds (:4058-4059).
- Duplicates are still refused in flushMS1_ via add() (:2206).
- The mode writes no spectra; it is load-only profiling per CHANGELOG:729. It also skips the [dnoise] summary, so it makes no claim about dnoise coverage.

A before/after test would need a mock loader that drops an MS1 frame, a failure no real input can produce.

FIX: Optional hygiene, output-neutral (one bitmap scan): just before the LOAD_ONLY check at :4141 add
  if (dnoise.on && std::getenv("SPEXTRACTOR_LOAD_ONLY")) dnoise.requireComplete();   // [dnoise] the load-only return skips the check at the split
A DnoiseError thrown there is already rethrown past the fallback (:4154).

TEST: None reachable. Only a mocked consumer run (e.g. extending SP/fixg/b2mock) that never delivers one MS1 frame with NumPeaks > 0, under SPEXTRACTOR_LOAD_ONLY=1, would fail before and pass after.


# headers-1

## [PARTLY/low] F3 (codex): loadTdfAxisBounds parses the GlobalMetadata bounds with std::strtod, which follows LC_NUMERIC. Under a comma-decimal locale the default preflight would refuse valid bounds.

EVIDENCE: **Failure demonstrated at function level.**
- TdfLoad.h:57-59 still calls std::strtod.
- Probe SP/fixg/verify3/h1/probe.cpp, built against the current src headers, on a D-shaped fixture (h1/fx/d.tdf, SQLite 3.51.0):
  - C locale: ok, n_bins 634073, lo 0x1.8ff69d30270f4p+6.
  - After setlocale(LC_NUMERIC, "de_DE.UTF-8"): loadTdfAxisBounds refuses "MzAcqRangeLower is not a finite number: '99.990834'". loadTdfCalibration and loadTdfDnoise still load.
- If it were reachable, it would refuse a valid run on the default path:
  - trace:band_edges defaults to acquisition and trace:detector to integer (spextractor.cpp:2567, :2575).
  - A failed bounds read only sets bounds_why (:823).
  - The preflight at :3966-3968 then throws InvalidParameter.

**Not reachable in the shipped tool.**
- A process starts in the C locale, and `grep setlocale|QCoreApplication src/` is empty.
- Stage-2 evidence (kimi#10):
  - the OpenMS library's only setlocale is Types.cpp (save, set C, restore);
  - QCoreApplication is constructed only in openms_gui;
  - main sets OPENMS_DISABLE_UPDATE_CHECK;
  - opentims' locale guard leaves the C locale.
- So nothing sets a comma LC_NUMERIC. This is a latent hazard, the same class stage 2 rated PARTLY/low for AccumulationTime. It is not a false refusal today, so severity is low, not medium.

**The fix keeps output identical.**
- The patched copy (h1/fix/TdfLoad.h) loads under de_DE, with C-locale values bit-identical to strtod's (same hexfloats).
- The real bound texts are plain decimals parseF64 accepts: D '99.990834', '1700.000000', '634073'; TNBC '99.994278', '1700.000000', '399967' (read-only sqlite query on ibminode05).
- On an accepted text parseF64 converts through classic-locale num_get, i.e. strtod in the C locale, so the digest pins are unaffected.
- The only newly refused texts are leading whitespace, hex floats and underflow. The dnoise gate (DnoiseMs1.h:289) already refuses those for the same keys on the default dnoise-on path.

FIX: src/TdfLoad.h, in loadTdfAxisBounds, replace the body of the `num` lambda (lines 56-61):
```cpp
    if (!txt) { why = std::string(key) + " is NULL"; return false; }
    char* end = nullptr; const double x = std::strtod(reinterpret_cast<const char*>(txt), &end);
    // the parse must consume the WHOLE value (sqlite3_column_bytes: an embedded NUL is not an end)
    if (end == reinterpret_cast<const char*>(txt) || end != reinterpret_cast<const char*>(txt) + nbytes || !std::isfinite(x))
    { why = std::string(key) + " is not a finite number: '" + std::string(reinterpret_cast<const char*>(txt), (size_t)nbytes) + "'"; return false; }
    v = x; return true; };
```
with:
```cpp
    if (!txt) { why = std::string(key) + " is NULL"; return false; }
    // the WHOLE value (sqlite3_column_bytes: an embedded NUL is not an end) in the C locale, whatever LC_NUMERIC the process
    // has: the grammar and conversion DnoiseMs1.h reads the same keys with
    const std::string s(reinterpret_cast<const char*>(txt), (size_t)nbytes);
    if (!spx::dnoise::detail::parseF64(s, v)) { why = std::string(key) + " is not a finite number: '" + s + "'"; return false; }
    return true; };
```
parseF64 writes v only on success and refuses non-finite values, so the separate isfinite check is not needed. Applied copy: SP/fixg/verify3/h1/fix/TdfLoad.h.

TEST: In tests/test_tdf_load.cpp testAccumulationTime, inside the existing de_DE block, add right after the `refused("acc_de_comma", ...)` line:
```cpp
      spextractor::TdfAxisBounds bd;   // the preflight's GlobalMetadata bounds parse in the C locale too
      CHECK(spextractor::loadTdfAxisBounds(makeTdf("bounds_de.tdf", dShaped()), bd, why) && bd.mz_lo == 99.990834 && bd.mz_hi == 1700.0 && bd.n_bins == 634073,
            "loadTdfAxisBounds under de_DE: %s", why.c_str());
```
Verified on macOS arm64 with SQLite 3.51.0 (h1/fixtest/test_tdf_load.cpp):
- **Current header:** "FAIL ... loadTdfAxisBounds under de_DE: MzAcqRangeLower is not a finite number: '99.990834'".
- **With the fix:** every check OK, exit 0.

Where no de_DE locale exists (likely the ubuntu runners) the block's existing guard skips it.


## [PARTLY/low] F4 (codex): tests/test_tdf_load.cpp fixtures use ALTER TABLE DROP COLUMN (SQLite 3.35+), a minimum nothing declares. On an older SQLite the test exits 2 before exercising the readers.

EVIDENCE: **Mechanism confirmed.**
- DROP COLUMN is used at test_tdf_load.cpp:156, :207, :291 and :293.
- CMakeLists.txt:39 is `find_package(SQLite3 QUIET)` with no version, and the test declares no minimum.
- Built unchanged against the SQLite 3.31.1 amalgamation (opentims' bundled copy, h1/sqlite3311) on arm64 and on x86-64 under Rosetta, both exit 2: `fixture failed: nocol.tdf: near "DROP": syntax error`, before any reader check.

**No current host is affected, so low rather than medium.**
- CI: ubuntu-22.04 SQLite 3.37.2, ubuntu-latest 3.45, macOS system 3.51.0; the Windows leg does not build the test; build.yml uses ubuntu-latest libsqlite3-dev.
- Deploy node ibminode05 (Ubuntu 24.04): sync_cluster.sh links $BUILD/lib/libsqlite3.a, which strings shows is 3.49.2, with a 3.49.2 header (SQLiteCpp extern). The build agent's deploy ran test_tdf_load: passed.
- The failure is loud (exit 2 with the SQL error), test-only, and touches no production query. It is test hygiene, not a broken deploy today.

**The suggested fix works.** Rebuilding tables with CREATE TABLE AS SELECT plus a rename, current headers unchanged (h1/f4only):
- SQLite 3.31.1 x86-64: exit 0, all four OK lines.
- System 3.51.0 arm64: exit 0.

**Two residuals.**
- On 3.31.1 arm64 (long double == double), SQLite's pre-3.43 text-to-double conversion parses the fixture literal 25.727120813485598 one ulp high (0x1.9ba2496f2295dp+4 vs C++ ...5cp+4, probe h1/lit.cpp). The exact t1[3000] check in testFrames (frames3000) then fails. That affects only Apple arm64 with an old non-system SQLite. On x86-64 3.31.1 every literal parses exactly.
- Generated columns need 3.31: SQLite 3.30.0 (anaconda) refuses `CREATE TABLE t(a, b GENERATED ALWAYS AS (1))` with 'near "AS": syntax error'. So F7's new fixture must be version-guarded.

FIX: tests/test_tdf_load.cpp only (full diff: SP/fixg/verify3/h1/f4only/f4.diff).

1. Add before makeTdf:
```cpp
/// @p table rebuilt with only the columns @p keep: a column dropped without ALTER TABLE DROP COLUMN, which needs SQLite 3.35.
static std::string keepColumns(const std::string& table, const char* keep)
{
  return "CREATE TABLE " + table + "_kept AS SELECT " + keep + " FROM " + table + "; DROP TABLE " + table + "; ALTER TABLE " + table +
         "_kept RENAME TO " + table + ";";
}
```
2. Replace the four DROP COLUMN uses:
```cpp
  refused("nocol", dShaped() + keepColumns("DiaFrameMsMsWindows", "WindowGroup, ScanNumBegin, ScanNumEnd, IsolationMz, CollisionEnergy"), "IsolationWidth");
  refused("no_timscal_col", dShaped() + keepColumns("Frames", "Id, MsMsType, NumScans, NumPeaks, AccumulationTime, MzCalibration, T1"), "TimsCalibration");
  ... makeTdf("cal_nocol.tdf", dShaped() + keepColumns("Frames", "Id, MsMsType, NumScans, NumPeaks, AccumulationTime, TimsCalibration, T1")) ...
  ... makeTdf("cal_nocol2.tdf", dShaped() + keepColumns("Frames", "Id, MsMsType, NumScans, NumPeaks, AccumulationTime, TimsCalibration, T1") +
                                                 "INSERT INTO MzCalibration SELECT 2, ...") ...
```
Every refusal substring the checks look for is unchanged, and all checks pass on 3.31.1 x86-64 and 3.51.0.

Alternative, if exact-literal portability to old arm64 SQLite also matters: keep the fixtures and require SQLite 3.35 at run time instead (`if (sqlite3_libversion_number() < 3035000)`, return a ctest SKIP_RETURN_CODE).

TEST: Build test_tdf_load against SQLite 3.31.1, for example on x86-64:
```
clang++ -arch x86_64 -std=c++20 -I<opentims>/sqlite -Isrc -I<shim> tests/test_tdf_load.cpp <3.31.1 sqlite3.o>
```
- **Before:** exit 2, `fixture failed: nocol.tdf: near "DROP": syntax error`.
- **After:** exit 0.

Verified both with h1/t_cur_3311_x86 and h1/t_f4only_3311_x86.


## [REFUTED/none] F6 (kimi): The strict AccumulationTime parse, NULL refusal included, runs on every Frames row including MS2, although only MS1 corr is used. This is claimed as a new refusal of such tdfs.

EVIDENCE: **The NULL part is not new.**
- The pre-fix loader (SP/pre_g/src/TdfLoad.h) already did `if (!acc) return fail("frame N has no AccumulationTime")` on every row.
- Probe with the pre_g header on an MS2 NULL fixture (h1/fx/ms2_acc_null.tdf): refused "frame 7 has no AccumulationTime", the same as today.

**What is new is non-decimal or non-positive TEXT in a non-MS1 row.**
- The pre_g header accepts '99.958ms', ' 99.958' and 0 on frame 7 (MsMsType 9).
- The current header refuses each: "frame 7: Frames.AccumulationTime '<text>' is not a positive decimal number".
- setup wraps it as "dnoise:ms1 cannot be exact on this input: ... -dnoise:ms1 false runs without MS1 denoising." (spextractor.cpp:3985-3986, :4015-4016). So the refusal is loud, names frame, column and value, and gives the escape hatch.

**None of these cells is valid data.**
- opentims parses every frame's AccumulationTime as `100.0 / atof(sql_row[4])` (opentims.cpp:74, query :287), MS2 included.
- NULL is atof(nullptr).
- 0 or a negative gives an infinite or negative correction, which opentims.cpp:225 casts as `double(raw)*corr+0.5` into uint32: undefined for the MS2 intensities.
- Only padded or suffixed text survives atof, and no SQLite rendering of a stored REAL or INTEGER produces it.
- Real data stores REAL on every row (read-only query on ibminode05):
  - D: 1,343 MS1 and 16,105 MS2 frames, all typeof 'real' '99.958'.
  - TNBC: 4,797 and 67,156, all 'real' '99.953'.
  - Stage 2: all 49 .d files have 99.953 or 99.958.

**The behaviour is what scope decision 1 specifies.** It says parse with parseF64 and require > 0, with no MS1 restriction. Decision 5 applies the same fail-closed per-row validation (MsMsType, NumScans, NumPeaks, TimsCalibration) to MS2 rows. TdfLoad.h's header states every read is whole or refused.

No valid input is falsely refused, so there is no defect to fix.

FIX: None needed.


## [CONFIRMED/low] F7 (codex): loadTdfCalibration decides whether Frames.MzCalibration exists from PRAGMA table_info, which omits generated columns. A generated MzCalibration column plus two MzCalibration rows is now refused, where the pre-fix SELECT DISTINCT read row 1.

EVIDENCE: **Fixture** (h1/mk.py, python sqlite 3.53.4): D-shaped, plus a second MzCalibration row with 2*C1, plus Frames rebuilt with `MzCalibration GENERATED ALWAYS AS (1)`, in VIRTUAL and STORED variants.
- `PRAGMA table_info(Frames)` lists 7 columns and no MzCalibration.
- table_xinfo lists ('MzCalibration', hidden 2 for VIRTUAL, 3 for STORED).
- `SELECT DISTINCT MzCalibration` returns [(1,)].

**probe cal (h1/probe_{pre,cur,fix}, SQLite 3.51.0):**
- **pre_g header:** ok, C1=155279.13067653627 (row 1), both variants.
- **current header:** refuses both with "Frames has no MzCalibration column and MzCalibration has 2 rows (need exactly 1)".
- **table_xinfo patch:** ok, C1 from row 1, both variants.
- **Controls:** the plain two-row file and D-shaped load under all three headers.

So this is a regression introduced by the pass's schema-decided fallback (decision 4).

**Impact is low.** The refusal is loud, and it hits only a synthetic file. Real D and TNBC Frames.MzCalibration is an ordinary column (table_info lists it), and vendors are not known to write generated columns.

**Portability of the fix.**
- table_xinfo exists from SQLite 3.26. Below that the unknown pragma returns no rows, and the code would take the fallback, which refuses two-row files loudly rather than reading a wrong row.
- Every build host has >= 3.31: CI 3.37.2+, cluster 3.49.2, and the patched test passes on 3.31.1 x86-64.
- Generated columns themselves need 3.31: 3.30.0 rejects the CREATE. So the new test needs a version guard.

FIX: src/TdfLoad.h loadTdfCalibration.

Line 110:
```cpp
  if (sqlite3_prepare_v2(db, "PRAGMA table_xinfo(Frames)", -1, &st, nullptr) != SQLITE_OK) return sqlfail("cannot read the Frames schema");
```
(was `"PRAGMA table_info(Frames)"`)

Comment at line 105:
```cpp
  bool frames_have_cal = false;   // PRAGMA table_xinfo: one row per column, generated ones too (table_info skips them), the name in column 1, matched ASCII case-insensitively as sqlite resolves it
```
Applied copy: SP/fixg/verify3/h1/fix/TdfLoad.h.

TEST: In tests/test_tdf_load.cpp testCalibrationAndBounds, add after the cal_nocol2 CHECK:
```cpp
  // a generated Frames.MzCalibration column (SQLite 3.31+) is the frames' reference like a stored one: PRAGMA table_info skips it
  if (sqlite3_libversion_number() >= 3031000)
    CHECK(spextractor::loadTdfCalibration(makeTdf("cal_generated.tdf", dShaped() +
                                                   "INSERT INTO MzCalibration SELECT 2, ModelType, DigitizerTimebase, DigitizerDelay, T1, dC1, C0, 2 * C1, C2, dC2, C3, C4 FROM MzCalibration;"
                                                   "ALTER TABLE Frames RENAME TO F0;"
                                                   "CREATE TABLE Frames (Id INTEGER PRIMARY KEY, MsMsType, NumScans, NumPeaks, AccumulationTime, TimsCalibration, T1,"
                                                   "  MzCalibration GENERATED ALWAYS AS (1));"
                                                   "INSERT INTO Frames SELECT Id, MsMsType, NumScans, NumPeaks, AccumulationTime, TimsCalibration, T1 FROM F0; DROP TABLE F0;"),
                                           cal, t1, why) && cal.C1 == 155279.13067653627 && t1.size() == 11,
          "a generated MzCalibration column and two rows: %s", why.c_str());
```
The fixture uses no DROP COLUMN, so it does not reintroduce F4.

Verified with h1/fixtest/test_tdf_load.cpp:
- **Current header:** "FAIL ... a generated MzCalibration column and two rows: Frames has no MzCalibration column and MzCalibration has 2 rows (need exactly 1)".
- **table_xinfo fix:** all OK, exit 0 on SQLite 3.51.0 arm64 and on 3.31.1 x86-64.


# deploy-1

## [PARTLY/low] F1 (codex, kimi): COMMITTED=1 is set before the provenance rename that is the real commit point.

EVIDENCE: **Reproduced.** Probe scenario S13 puts a directory in $PROV's place during the build (the old provenance is already parked), so `mv -f $PROV.tmp $PROV` fails with EISDIR after a successful build. On the current script:
- rc is 1 and the log says "COMMITTED (binary + provenance), but a post-commit step failed (rc 1)".
- The tree is the new version, there is no spextractor.provenance, and provenance.tmp remains.
- The stage and the lock are gone.

**The signal half is real too.** SP/fixg/verify3/sigwin.sh shows a trapped TERM runs between `COMMITTED=1` and the next command (finish sees COMMITTED=1, rc 143) in bash 3.2 and 5.3. A `kill -TERM $$` injected between the two on one deploy leaves the same state.

**Why PARTLY and low.** The leftover state is consistent, and there is no provenance at all rather than a wrong one:
- The inputs are the promoted bytes, hash-rechecked after the build, and the binary was built from them. The correct provenance sits in provenance.tmp.
- What finish deletes is not needed for recovery. prov.prev names a binary the successful build replaced, and bak/ holds inputs a commit supersedes anyway.
- The real harm is the false "COMMITTED (binary + provenance)" line. c_notes' refusal table tells the operator that line means binary AND provenance are valid.
- On the node, verify_publish.sh runs under `set -u` only. Without a provenance its cp fails, yet it still publishes and prints VERIFY_DONE, so the arm would ship without one.

**Unlikely to happen.**
- The rename happens in the same directory the transaction just wrote into (one ext filesystem on the /scratch NVMe). It fails only if something outside the lock interferes, or on a filesystem fault.
- The signal window is one assignment wide. Nothing signals txn.sh on its own: there is no pty and it writes only to its log.

**The reviewers' fix alone is wrong.** With `mv; kill -TERM $$; COMMITTED=1`, finish rolls back to v1 and prints "there is NO provenance". The new provenance stays in place, naming v2's src_sha256 over the v1 tree.

FIX: Derive commitment from the filesystem in finish(); rename is atomic. Keep `COMMITTED=1; mv -f "$PROV.tmp" "$PROV"` as it is, with no signal juggling:
```
finish() {
  rc=$?; set +e
  # The rename is the commit point, not the flag: a failed mv, or a signal between the two, leaves $PROV.tmp behind.
  if [ -e "$PROV.tmp" ]; then COMMITTED=0; rm -f "$PROV.tmp"; fi
  if [ "$COMMITTED" != 1 ]; then
```
With this change:
- A failed rename rolls back like a failed build: inputs restored, the old provenance parked as .stale, the FAIL-CLOSED message printed.
- The injected signal-window probe also rolls back cleanly.
- A failure after the rename still reports a post-commit failure.

The combined patch for F1, F2 and F9 is SP/fixg/verify3/sync_cluster.F1F2F9.patch; shellcheck is clean.

TEST: S13 in SP/fixg/verify3/harness_additions.sh, appended after S12b in tests/test_sync_cluster_txn.sh.

Setup:
1. reset_node commits v18.
2. Deploy v19 with slow=3.
3. Once $O/building exists, run `mkdir -p $PROV/spextractor.provenance.tmp`.

Checks:
- "a failed provenance rename is never reported as a commit": rc != 0 and no "^COMMITTED (binary + provenance)" line.
- "it rolls back like a failed build": tree_is v18, ROLLED BACK printed, no $PROV.tmp, $PROV.stale identical to the v18 provenance, clean.

On the current script both S13 checks fail. On the fixed script both pass, and the shipped harness still passes 27/27.


## [CONFIRMED/medium] F2 (codex): The rollback in finish() never checks that each restore worked. It reports success, deletes the remaining backups, and can put back a provenance that no longer matches the tree.

EVIDENCE: **Reproduced both halves.** Probe scenario S14:
- reset_node commits v20.
- Deploy v21 with BREAK_BUILD and the calibration unchanged, so the failed build leaves libOpenMS.so and the binary as they were.
- During the build, `chmod a-w $O/src/topp`.

On the current script:
- Four restore renames fail with "Permission denied": spextractor.cpp, TdfLoad.h, MzPeakStreamLoad.h, DnoiseMs1.h.
- finish still prints "ROLLED BACK every promoted build input: ..." and then "bin/spextractor, libOpenMS.so and provenance unchanged".
- It deletes the stage (the four backups are lost for good) and releases the lock.
- The tree now holds v21's four topp files, including the BREAK_BUILD source, next to v20's calibration header.
- The restored provenance's src_sha256 names v20. The probe prints "prov src==tree cpp? no".
- The next make would build v21 sources under a v20 provenance.

**Likelihood is low.** It needs a second, independent fault during the build: a permission change outside the lock, a directory in a file's place, or the filesystem going read-only. Same-filesystem renames of the user's own files do not fail by themselves. The script already defends against writers outside the lock (S8), so a rollback that claims success without having happened is a broken rollback, and medium by the rubric.

FIX: At backup time (current line 134), record each backup's hash against its destination:
```
for f in $BUILD_INPUTS; do d=$(dest "$f"); if [ -e "$d" ]; then cp -p "$d" "$S/bak/$f"; printf '%s  %s\n' "$(sha "$S/bak/$f")" "$d"; fi; done > "$S/restore.sha256"
```
In finish, replace the restore loop and its message with:
```
    UNDONE=""
    for f in $PROMOTED; do
      d=$(dest "$f")
      if [ -e "$S/bak/$f" ]; then { mv -f "$S/bak/$f" "$d" && touch "$d"; } || UNDONE="$UNDONE $f"; else rm -f "$d" || UNDONE="$UNDONE $f"; fi
    done
    # every backed-up input must hold its backup's bytes again (a directory in a file's place swallows the mv)
    if [ -n "$PROMOTED" ] && [ -z "$UNDONE" ] && ! sha256sum -c --quiet "$S/restore.sha256"; then UNDONE=" (restore.sha256)"; fi
    if [ -n "$UNDONE" ]; then
      echo "FAIL-CLOSED: rollback incomplete for:$UNDONE; there is NO provenance. Kept the stage $S (bak/, prov.prev)" \
           "and the lock $LOCK: put the backups back by hand, then rm -rf $S and rmdir $LOCK."
      exit "$rc"
    fi
    [ -z "$PROMOTED" ] || echo "ROLLED BACK every promoted build input:$PROMOTED"
```
The prov.prev branch stays unchanged and is now reached only after a verified restore. Exiting inside finish keeps the stage and the lock.

TEST: S14 in SP/fixg/verify3/harness_additions.sh (setup as in the evidence above).

Checks:
- "not reported as a complete rollback": rc 2, no "ROLLED BACK every", and "rollback incomplete" printed.
- "the unrestored backups, the parked provenance and the lock are kept": the lock exists, and the stage's bak/spextractor.cpp and prov.prev equal v20's.
- "no provenance is put back over a tree that still holds the failed deploy's source": $PROV is absent, or its src_sha256 equals the tree's cpp.

On the current script all three S14 checks fail. On the fixed script they pass, and the shipped harness still passes 27/27.

Whole appended harness (SP/fixg/verify3/full_plus.sh):
- Current script: 30/37, exactly the 7 new checks failing.
- Fixed script (sync_cluster.fixed2.sh): 37/37.


## [PARTLY/low] F9 (kimi): A stale .deploy.lock has no recovery: after a killed transaction, every later deploy refuses until someone removes the lock by hand.

EVIDENCE: **True, but the refusal is correct.** A SIGKILL, OOM kill or reboot leaves the lock, and the pre-G script behaved the same. A killed transaction can leave a half-promoted tree whose only recovery material is the stage's bak/ and prov.prev. Refusing is therefore the right fail-closed behaviour, and the lock must not be broken automatically.

**Half of the suggested fix already exists.** Line 81 prints the owner file, "<stage> pid <pid> <date>"; S4b's refusal shows it.

**What is missing:**
- The refusal does not say whether that pid is alive.
- The repo has no recovery pointer. The manual procedure exists only in SP/fixg/c_notes.md in the scratchpad. A grep for deploy.lock outside docs/reviews finds only the script and the harness.

**A second route to a stale lock, not only SIGKILL.**
- A HUP/INT/TERM that arrives while finish runs aborts the rollback half-way: the trap's `exit` inside the EXIT trap ends the shell.
- SP/fixg/verify3/sigfin2.sh confirms this in bash 3.2 and 5.3, and the lock is left behind.
- Harness S9b (a touch shim stalls the rollback, then TERM is sent) on the current script: rc 143, no ROLLED BACK, tree not restored, lock held, stage kept.
- The first TERM waits for make, which takes minutes by design, so an operator re-sending TERM is plausible. The window, though, is the sub-second rollback.

The outcome still fails closed, so this is diagnostics: low.

FIX: First line of finish:
```
  rc=$?; set +e; trap '' HUP INT TERM   # a second signal must not abort the rollback half-way and strand the lock
```
Replace line 81:
```
if ! mkdir "$LOCK" 2>/dev/null; then
  OWNER=$(cat "$LOCK/owner" 2>/dev/null || echo 'owner unknown'); OPID=$(sed -n 's/^.* pid \([0-9][0-9]*\) .*$/\1/p' "$LOCK/owner" 2>/dev/null || true)
  # a SIGKILLed, OOM-killed or rebooted transaction leaves the lock, and its stage holds what a recovery needs (bak/, prov.prev)
  if [ -n "$OPID" ] && ! kill -0 "$OPID" 2>/dev/null; then OWNER="$OWNER; that pid is NOT running: a killed deploy left the lock and its stage"; fi
  echo "REFUSED: another deploy holds $LOCK ($OWNER) - nothing changed"; exit 1
fi
```
The `|| true` is required: under set -e, a failing sed in that assignment would exit before the refusal is printed.

Optionally, move c_notes' "Recover by hand" section into CONTRIBUTING.md or the script header.

TEST: Both scenarios are in SP/fixg/verify3/harness_additions.sh; each fails on the current script and passes on the fixed one under /bin/bash 3.2 and bash 5.3.

- **S4b:** reset to a clean v15, then create the lock with an owner line whose pid is a just-exited `sh -c 'exit 0'`. Expect rc 1, the node unchanged, and "is NOT running" in the output.
- **S9b:** install a touch shim that sleeps 1 s once $V/slow_touch exists. Deploy v17 with BREAK_BUILD and calibration c15. Raise the flag mid-build and send TERM when the rollback's touch hits it. Expect tree_is v15, prov_is v15, prov_truthful, ROLLED BACK printed, and clean. On the fixed script rc stays 2 because the TERM is ignored.


## [REFUTED/low] F10 (kimi): Every deploy leaves /scratch/kohlbach/.deploy.stage.XXXXXX.log behind, and finish() never removes it.

EVIDENCE: **Deliberate and documented.**
- c_notes says the transaction log "is kept after every deploy and accumulates like the build logs".
- The build agent's report says the stage log is kept on purpose.
- The script prints the log's path before the run starts (line 177).

**Same policy as build_sync_*.log, which predates G** (the pre_g script already wrote build_sync_$(date).log). Read-only check on ibminode05:
- 108 build_sync logs, 460K in total.
- 1 stage log, 1,693 bytes, after the first deploy with the new script.
- /scratch has 8.4T free.

**Needed for recovery.** The manual recovery reads the stage log first ("Read $S.log") to see how far a killed transaction got, so deleting it would destroy that record.

**finish cannot delete it anyway.** It is the file finish's own stdout goes to, and the caller cats it afterwards.

The harness excludes it from snap() because the log is expected to change, not to hide a leak. There is no defect.

FIX: None.

TEST: None.

