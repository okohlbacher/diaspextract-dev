1. **Medium — Fix-pass defect: rollback failures destroy the recovery material.**  
   **Location:** `scripts/sync_cluster.sh:57–77`.  
   If a build fails and a rollback `mv` fails—for example, because a destination’s permissions changed—`finish()` continues under `set +e`, reports every input restored, and deletes the stage containing the remaining backups. It can also restore the old provenance based solely on binary/library hashes while a source file remains from the failed deployment.  
   **Fix:** Check every restoration, verify restored input hashes, and retain the backups and lock if rollback is incomplete. Restore provenance only after successful restoration. Add a harness case that forces one rollback rename to fail.

2. **Medium — Fix-pass defect: the transaction marks itself committed before publishing provenance.**  
   **Location:** `scripts/sync_cluster.sh:160`, with cleanup at `:58` and `:77`.  
   If `mv "$PROV.tmp" "$PROV"` fails, `COMMITTED` is already 1. Cleanup consequently skips rollback and deletes both the backups and parked provenance. A signal between the assignment and rename produces the same state. The diagnostic incorrectly describes this as a post-commit failure.  
   **Fix:** Make successful provenance publication determine commitment. Defer signal handling across the rename/state update, and preserve rollback behavior when publication fails. Test a failed provenance rename.

3. **Medium — Pre-existing defect, still defeats the locale fix on the default path.**  
   **Location:** `src/TdfLoad.h:57–60`; `src/spextractor.cpp:3953–3968`.  
   With process `LC_NUMERIC` set to a decimal-comma locale, an ordinary bound such as `"99.990834"` still fails the axis reader’s whole-text `strtod` check. The default integer/acquisition-bounds preflight therefore refuses valid metadata before the newly locale-independent AccumulationTime recovery can help. The new locale tests exercise correction parsing, but not this prerequisite.  
   **Fix:** Make the axis-bound conversion explicitly use the C locale while preserving whole-text and finite checks. Exercise all three metadata loaders under the comma locale.

4. **Medium — Fix-pass defect: the new tests impose an undeclared SQLite version requirement.**  
   **Location:** `tests/test_tdf_load.cpp:156`, `:207`, `:291–294`; `CMakeLists.txt:39`.  
   CMake accepts SQLite without a minimum version, but these fixtures use `ALTER TABLE … DROP COLUMN`, which requires SQLite 3.35 or later. With an older library, fixture creation exits 2 before testing the reader. The deployment script likewise refuses deployment when it finds an older bundled SQLite, even though the production queries do not require this syntax.  
   **Fix:** Construct fixtures with the columns absent initially, or rebuild their tables using older supported SQL. Avoid raising the production dependency floor solely for fixture construction.

5. **Low — Fix-pass defect: schema discovery mistakes generated columns for absent columns.**  
   **Location:** `src/TdfLoad.h:110–132`.  
   `PRAGMA table_info(Frames)` omits generated columns. Consider a Frames table with `MzCalibration GENERATED ALWAYS AS (1)` and two MzCalibration rows: the previous `SELECT DISTINCT MzCalibration` correctly selected row 1; the new discovery path declares the column absent and refuses because two calibration rows exist. This is a concrete SQLite-schema regression, although the supplied evidence does not establish that vendor-produced files use generated columns.  
   **Fix:** Use schema discovery that includes generated columns, such as `table_xinfo` with appropriate compatibility handling. Add that two-row fixture.

6. **Low — Fix-pass defect: load-only success bypasses completeness verification.**  
   **Location:** `src/spextractor.cpp:4141–4143`; completeness check at `:4328–4329`.  
   With `SPEXTRACTOR_LOAD_ONLY` set, a streaming loader that silently omits a non-empty MS1 frame can finish and return `EXECUTION_OK` without calling `requireComplete()`. Duplicate detection still runs, but missing-frame detection does not.  
   **Fix:** Check completeness immediately after `consumer.finish()`, before the load-only return and success reporting.

Checked and found clean within the supplied code:

- Recovery expressions, types, operation order, and contraction guards preserve the scoped arithmetic.
- Per-calibration scan-table sizing preserves scan indices and leaves the gate’s global maximum unchanged.
- Normal streaming/resident coverage bookkeeping is serial, and fallback resets its marks.
- The new finite-m/z checks sit inside exception capture on both picking paths; their exceptions bypass stream fallback.
- Resident scratch release, histogram reset, and the iterations-zero gate assertion match their intended scope.

I ran no commands or tests. I could not independently verify digest identity, actual loader delivery/native-ID behavior, or compiler/linker behavior from the excerpts. The acknowledged missing real-data gates remain unverified; they are not additional findings above.