# Stage-3 review: fix pass G (2026-09-10)

**What was reviewed:** the full fix-pass-G diff against the stage-2 snapshot.
- `src/DnoiseMs1.h`, with the new `recover::` section and `FrameCoverage`.
- `src/TdfLoad.h`, now fail-closed on SQLite errors, with per-row type and range checks and a classic-locale
  AccumulationTime parse.
- `src/spextractor.cpp`:
  - the `DnoiseRun` adaptor and per-row scan tables;
  - the completeness bitmap, the non-finite m/z refusal and the SDK refusal;
  - the resident-loop fixes.
- The transactional `scripts/sync_cluster.sh`.
- The new tests: `tests/test_tdf_load.cpp`, `tests/test_sync_cluster_txn.sh`, `testRecover` and e2e checks 19d
  and 21.

**Reviewers:** all three read the self-contained brief (`brief-selfcontained.md`, 444 KB). codex wrote 5.1 KB,
kimi 10.4 KB and vibe 13.3 KB; vibe reported no defects. The 10 deduplicated findings went to three read-only
verifier groups. Their verdicts, evidence, fixes and tests are in `verification.md`.

## Gates on the fix-pass binary

Binary sha `bcda6bfa`, published as arm `dnoise_s2c`. All runs used 100 threads and one cell per tile. The nodes
were shared, so walls are indicative.

| arm | node | settings | digest | peak | wall |
|---|---|---|---|---:|---:|
| G1 | ibminode05 | D, dnoise off, prune off | `8c1b047f` = pin | 31.58 GB | 5:21 |
| G2 | ibminode05 | D, dnoise off | `8c1b047f` = pin | 25.77 GB | 4:47 |
| G3 | ibminode05 | D, defaults | `e43672a0` = pin | 22.30 GB | 4:40 |
| G4 | ibminode05 | D, defaults, resident source (`SPEXTRACTOR_TILE_RESIDENT=1`) | `e43672a0` = pin | 34.44 GB | 4:17 |
| G5 | ibminode05 | D, `-perf:stream_load false` (resident load, completeness check on a real `.d`) | `e43672a0` | 88.77 GB | 10:10 |
| T1 | spock | TNBC 009, dnoise off | `bff54a1f` = pin | 31.17 GB | 9:32 |
| T2 | spock | TNBC 009, defaults | `3aafd0b5` = pin | 25.29 GB | 8:15 |

- **G5 against G3:** same MS1 trace digest (2,193,170 traces), same `[dnoise]` summary.
- **Stream-fallback arms:** all four (`r1_res`, `r2_fb`, `r1d_res`, `r2d_fb`) match the previous gate on spectrum
  digest, counts, `[det]` lines and `[dnoise]` lines.
- **e2e:** 24/24 on the new binary. The pre-fix arm `dnoise_s2b` fails exactly the two new checks, 19d and 21.

## Confirmed or partly confirmed

These are fixed in the v3 code round, together with the tiled memory default.

| id | finding | severity | fix |
|---|---|---|---|
| F2 | The deploy rollback never checks that each restore worked. It reports success, deletes the backups and can put back a provenance that no longer matches the tree (codex; reproduced with a read-only `src/topp`) | medium | Record each backup's hash, verify every restore, and keep the stage, the lock and a parked provenance when the restore is incomplete. |
| F1 | `COMMITTED=1` is set before the provenance rename that actually commits, so a failed rename reports a commit (codex, kimi; reproduced) | low | `finish()` decides from the filesystem: a leftover `provenance.tmp` means not committed. |
| F9 | A second signal can abort the rollback half-way, and a refusal does not say the lock's owner is dead (kimi) | low | Ignore HUP/INT/TERM inside `finish()`; name a dead owner pid in the refusal. The lock is still never broken automatically. |
| F3 | `loadTdfAxisBounds` still parses with `strtod`, which follows `LC_NUMERIC` (codex; predates this pass, demonstrated at function level) | low | The same classic-locale whole-text parse as AccumulationTime. |
| F4 | `test_tdf_load.cpp` fixtures use `ALTER TABLE DROP COLUMN`, which needs SQLite 3.35 (codex; exit 2 against SQLite 3.31.1) | low | Rebuild the table from the kept columns instead. |
| F7 | `PRAGMA table_info` skips generated columns, so a generated `Frames.MzCalibration` reads as absent (codex) | low | `PRAGMA table_xinfo`. |

## Refuted

- **F5, "the pins were not run on the fix-pass binary".** They were run afterwards, and all passed (table above).
- **F6, "the strict AccumulationTime parse is a new refusal class for MS2 rows".** A NULL was already refused on
  every row. What is new is only non-decimal text in a non-MS1 row, which real Bruker tdfs do not contain.
- **F8, "`SPEXTRACTOR_LOAD_ONLY` skips the completeness check".** The miss cannot happen: the probe is honoured
  only on the streaming path, and that path delivers every non-empty MS1 frame.
- **F10, "every deploy leaves its transaction log".** This is deliberate and documented, the same policy as the
  build logs.
