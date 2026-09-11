# Corpus harness review: verdicts and fixes (2026-09-11)

Review input: `harness/review/{kimi.md,vibe.md}` plus the internal pass (findings R0, F1-F16 of the synthesis). Harness
under review: `harness/corpus.py` sha256 `7ab160cd...`. Every finding was checked against the code and, where it made
an empirical claim, against node `data` (proof-run records and logs, the arm, java, the FASTAs). A finding counts as
refuted only when the code or the data contradicts it.

Result: **R0 confirmed, not fixable in the harness (user decision). F1-F16: 16 confirmed; 15 fixed in
`harness/corpus.py`, F7 documented (user decision).** Two suggested fixes were rejected as unsafe and replaced (kimi's F2
`load_after` rule, the internal F1 "Sage within 1%" rule); F3's "recompute at table time" was replaced by re-counting in
the queue.

## Proof

- **Offline selftest:** 135/135 on the laptop (85 before). On data (Linux paths: real `/proc`, `ldd` on a script,
  `syncfs`): 136/136 with the final `corpus.py` sha256 `10a088d9...` (the extra case reads the real `/proc`).
- **Every new case fails without its fix (mutation proof):**
  - `scratchpad/mutate_corpus.py` re-breaks one fix at a time in a copy and runs that copy's selftest.
  - **22/22 mutations caught.** Twenty end in FAIL lines. F10 and F14 end in a selftest crash on the missing field,
    which counts as caught.
  - The first pass caught 18/22. Four gaps were closed:
    - F3-score-hash had no case of its own; a case was added.
    - F2-flag-render was checked against header text that is always present; the check now reads the row itself.
    - Table renders sat outside the case wrapper, so a guard firing inside them crashed the selftest; they are now
      wrapped.
    - A load-gate check depended on other selftest copies running in parallel; it now checks the load only.
- **End-to-end on data**, plan `corpus_v3_selftest_r2`, fresh directories `/scratch/kohlbach/corpus_v3_selftest_r2`
  and `/ceph/.../corpus_v3_selftest_r2`, nonce `20260911-015345-7f75e7`, 01:54-01:59:
  - Same arm `dnoise_s2c` (binary `bcda6bfa...`), same file HeLa_2740, harness `34129497...`.
  - Measurement hashes `050e2e2a/064af71b/4fe0a1ce`. `QUEUE_DONE failed 0 mzml_left 0`.
  - diaTracer: 66.5 s, 36.2 GB, 117,388 spectra. Ours: 15.9 s, 5.6 GB, 75,026 spectra.
  - Peptides: Sage 7,391 / 6,652, MSFragger 9,032 / 6,066. **Identical** to the 00:02 proof run on the same outputs
    (7,391 / 6,652 / 9,032 / 6,066; spectra 117,388 / 75,026).
  - Flags on the row: `gate: load 55.9 > 24; during dt: foreign CPU 54.3 cores > 24; during spx: foreign CPU 49.1
    cores > 24`.
  - Relaunch: `LAUNCH_FINISHED ... failed 0`, "already done (record verified): skipped", all 5 record mtimes unchanged.
- **Guard test on data** (nonce `20260911-020442-acb43a`, 02:04-02:10, harness `10a088d9`): **39/39 pass**
  (`guardtest --show` exit 0, lock free, bracketed pgrep of MSFragger, diaTracer, Sage, the extractor and the runner
  all empty afterwards). New GT0 cases: the r2 record is trusted with the current build, JDK, code and threads, and
  refused with a changed binary, lib, jar, ceph-resident library or measurement-code hash. GT1-GT8 unchanged and passing
  on the real raw, arm, jar and engines: the SIGBUS arm reports `rc=135 exit=0 signal=7`; GT6 is a real pair
  (117,388 / 75,026 spectra) whose four searches fail as intended (Sage 102,805 / 58,040 rows with 0 peptides;
  MSFragger without `TOTAL TIME`), and it ran all four searches through the new engine read checks.
- **Collect and table:**
  - `collect` copied 110 files to `/ceph/ibmi/abi/oliver/spextract/corpus_v3_selftest_r2/data`: directory 0700,
    ACL group/other `---`, 0 group/other-accessible paths, 0 `*.mzML`/`*.mzBIN*`/`queue-*.json`/`stage`/`tools`,
    0 raw-basename hits.
  - `table --source ceph` (`scratchpad/corpus-v3-selftest-r2.md`): 1 of 1 rows complete.
  - The row equals the 00:02 proof table cell for cell on spectra and peptides: 117,388 / 75,026; Sage 7,391 /
    6,652 (0.90); MSFragger 9,032 / 6,066 (0.67). Walls 1:07 / 0:16, RSS 36.2 / 5.6 GB.
  - Flags on the row: `gate: load 55.9 > 24; during diaTracer-2.2.1: foreign CPU 54.3 cores > 24; during
    SpeXtractor 2.0.0: foreign CPU 49.1 cores > 24`. Summary `1/1` flagged, so there is no unflagged wall ratio.
  - The ceph directory keeps a default ACL (`default:group::rwx`): entries created there later inherit group
    access until the next `collect` re-applies the chmod.

## Verdicts

| id | verdict | evidence (code, data) | fix | selftest / mutation |
|---|---|---|---|---|
| R0 | **confirmed, open** (process) | codex quota exhausted until 2026-09-17 17:41 in both runs; kimi 9 findings, vibe 2; the standing rule makes a missing reviewer blocking | none in the harness: re-run codex on `corpus-brief.md` after the quota resets, or accept the two-model + internal synthesis | - |
| F1 | **confirmed** | `run_search` refused only a zero patch count and required only `finished in` / `TOTAL TIME`. On data, `engine.log:43` `in.mzML: Scans = 117388` / `75026` and `patched 117388 precursor(s)` were never parsed | G-V10: patch count == spectrumList count; MSFragger `Scans` == count; Sage lower bound `floor(R*(D+1)/1000)` from `- search: D ms (R spectra/s)` in [50%, 100%] of the count; all three stored in the search record. **Suggested "Sage within ~1%" rejected:** sage-cli 0.14.7 `main.rs:124-141` computes the rate over spectra with >= `min_peaks` peaks only, so a sparse-spectrum fraction is legitimately missing (proof: 99.96% / 99.75%) and an output-dependent 1% rule could fail good cells. Real node r2: Scans 117,388/117,388 and 75,026/75,026, patch 117,388, Sage 117,341 and 74,838 | 3 cases; 3/3 mutations |
| F2 | **confirmed** | the row flag came only from `gate`; `load_before/after`, `ps_top` were recorded, never read. **kimi's fix (flag on `load_after > load_max`) refuted:** `load_after` includes our own 100-thread arm | `ArmMonitor` samples `/proc` every 10 s during each arm: foreign CPU = busy ticks minus the runner's process tree (utime+stime+cutime+cstime, so reaped children stay counted), time-weighted highest 60-s mean > the gate threshold, or MemAvailable < 5% of MemTotal, or unmeasured -> `during.contended` (G-V06 flag). Rendered per arm, counted in the summary (`k/n`, median wall ratio of unflagged rows), shown by `status`. MemAvailable uses 5% of MemTotal, not "1.2 x heap": `-Xmx400G` is not diaTracer's RSS and our own arm's use cannot be separated. Real node r2: 54.3 and 49.1 foreign cores during the two arms at 1-min load 56-120 | 6 unit + 1 queue case; 2/2 mutations |
| F3 | **confirmed** | `harness_sha256` written, never compared; r1 record of harness `f24d0a69` skipped by `7ab160cd` (runner.log 00:16:57); `threads` not compared | `MEASURED` hashes the sources (and constants) of the functions that stage/gate/time/verify an arm (`pair`), run and check a search (`search`), count peptides (`score`). `pair_done` compares `pair` + threads; `search_done` compares `search` + `score`; G-V13 refuses mixed hashes, thread counts, or ok records without hashes. A `score`-only change is **re-counted from the kept TSV in the queue** (no engine re-run, old counts kept under `rescored`), instead of recounting at table time, which would parse every TSV of the corpus through one long ssh session (memory ssh-waiters-die-together). Comment-only edits of measured functions invalidate too (documented: finish edits before T0) | 5 cases; 2/2 mutations; relaunch on data verified the hashes |
| F4 | **confirmed** | `STRIP_PREFIX` covered 4 names only. On data, `_JAVA_OPTIONS=-Xmx64m java -Xmx400m` gives `MaxHeapSize = 67108864` ("Picked up _JAVA_OPTIONS"); root `env.sh` appends `${LD_LIBRARY_PATH:-}` | strip and record `GLIBC_TUNABLES`, `OMP_*`, `GOMP_*`, `KMP_*`, `TCMALLOC_*`, `_JAVA_OPTIONS`, `JAVA_TOOL_OPTIONS`, `JDK_JAVA_OPTIONS` (`MALLOC_CONF` is covered by `MALLOC_*`); drop the inherited `LD_LIBRARY_PATH` before `env.sh`; an `env.sh` exporting any of them aborts (G-V03). Not adopted: a PATH/HOME/USER/LANG allowlist (would also drop the variables the selftest's fake tools read) and identical `env_keys` across nodes (session variables differ by node). Library resolution is pinned by F6 instead of the `LD_LIBRARY_PATH` string | 3 cases; 2/2 mutations |
| F5 | **confirmed** | `TIME` never checked; `ex.shutdown(cancel_futures=True)` needs 3.9; bare `java` unrecorded; FASTA mismatch surfaced only in G-V13; `node_main` caught only `Abort` | `preflight()` (G-V15/G-V12): python >= 3.9, `TIME -v true` parses, `/proc` readable, `java -version` recorded (path, version, feature version), both databases == new plan key `search_db_sha256`. Run by `launch` (node-busy), `dry-run`, the queue start, and the new `corpus.py preflight` over all queue nodes (refuses differing JDK feature versions). `node_main` writes `QUEUE_ABORTED [CRASH]` / `[KILLED]`. Verified on data (python 3.12.3, GNU time, java 21.0.12, pins match); ibminode05 not touched (run `preflight` before T0) | 6 cases; 2/2 mutations |
| F6 | **confirmed, worse than claimed** | identity hashed `SPX_BIN`, top-level `<arm>/lib/*`, jar. On data `ldd` under the arm env resolves 18 libraries outside the arm, 12 of them on ceph (OpenDIAlyzer conda `libstdc++`, `libgomp`, `libcrypto`, boost, ...); **without** the arm's `LD_LIBRARY_PATH` the binary's RUNPATH resolves `libOpenMS.so` from `/scratch/kohlbach/OpenMS/build` (a node-local dev tree) | identity = `SPX_BIN` + `<arm>/lib/**` + every `ldd`-resolved library (under the arm env) + jar + `ext/bruker/**` + JDK (`java`, `libjvm.so`, version). A library resolved outside the arm, `/ceph` and the system library dirs, or unresolved, aborts (G-V03). G-V04 compares the full identity within a queue; G-V11/G-V13 compare the build identity (ceph-resident parts) plus the JDK feature version, so node-local system libraries may differ across nodes (listed in the table header when they do). `dlopen`ed libraries are not covered (no `dlopen`/`QLibrary` in `src/`) | 5 cases; 1/1 mutation; r2 record: 18 deps pinned |
| F7 | **confirmed** (operational) | data 1-min load 74.6 at 01:05 and 55.9-119.8 during r2; spock 4.4 at 01:05; `load_wait_min: 60` per pair | no code change (the per-pair 60-min wait is a user decision); documented in `CORPUS.md` "Before the real run"; the new during-arm flag makes contended rows visible either way. **Needs sign-off:** node split / wait at T0 | - |
| F8 | **confirmed** | `_node_run` ran only `first` alone, then pooled whatever its result | MSFragger-pending units run alone until one MSFragger search ends ok | 1 case; 1/1 mutation |
| F9 | **confirmed** | the mzML was unlinked only inside `unit()`; units without pending searches never reach it; failed-search mzMLs unreported (vibe's interrupted-delete scenario is muddled, the gap is real) | `sweep_outputs` at queue start and end; `QUEUE_DONE ... mzml_left N`; `status` lists leftovers; `corpus.py purge` (lock-guarded) | 3 cases; 1/1 mutation |
| F10 | **confirmed** | pair records carried `cmd` with the staged raw basename and `sample.raw`; proof-run 2 `spx/e.log` echoed `.../20200505_..._MLHeLa_..._2740.d/analysis.tdf`; `collect` copied `queue-*.json` (raw paths) with 0755 subdirectories | staged as `<id>.d`; records keep `raw_sha256` instead of `raw`; neighbour path dropped; guard messages name the sample id; `collect` skips `queue-*.json`, removes group/other bits (lowers the ACL mask) and refuses (G-V14) if any path stays accessible. r2 on data: 0 raw-basename hits in records and runs; e.log echoes `.../HeLa_2740.d/analysis.tdf`. Residual: the in-house registry ids still name directories and records; the table prints labels A-F | 3 cases; 1/1 mutation |
| F11 | **confirmed** (code fact; magnitude unmeasured) | one pre-warm before the first arm; nothing written back before the second arm's timer | `syncfs` of the node-local filesystem and a pre-warm before each arm, outside the timed window, durations recorded (r2: 0.0 s / 0.1 s each) | 1 case; 1/1 mutation |
| F12 | **confirmed** | `yaml.safe_load` keeps the last duplicate key (verified locally); no uniqueness or count check | duplicate-key loader (G-V01), unique raw path and pin per plan, plan key `n_samples` (49) | 3 cases; 2/2 mutations |
| F13 | **confirmed** | `stage()` fingerprinted without `with_acq`; the table printed the registry value | acquisition length read from the raw's `Frames` at staging and compared with `acq_min` (G-V02), stored as `stage.acq_min_read` (r2: 5.6) | 2 cases; 1/1 mutation |
| F14 | **confirmed** | on data every Sage row is rank 1 (102,805 and 58,040 rows); counted 7,391 vs target-only 7,323 (diaTracer), 6,652 vs 6,590 (ours) | decided rule kept; `target_peptides` stored; header names it **target+decoy** and prints the target-only totals | 2 cases; 1/1 mutation |
| F15 | **confirmed** | summaries mixed flagged rows; `workers` was the configured value; no overlap info | per-scheme `flagged k/n` and median wall ratio of unflagged rows; engine steps record start/end epochs; `†` marks overlapping searches | 2 cases; 1/1 mutation |
| F16 | **confirmed** | GNU time's "kbytes" is `ru_maxrss` in KiB on Linux; header said "time -v reports kB" | arithmetic kept (decision); columns `RSS GB (kB/1e6)`; header: KiB, one unit = 1.024e9 bytes, x0.9537 for the GiB of the older tables | 1 case; 1/1 mutation |

## Still open

1. **R0:** a three-CLI review of this harness needs codex after 2026-09-17 17:41 (or the user's acceptance).
2. **F7: closed 2026-09-11.** `load_wait_min: 20` (user decision: do not lose a day waiting; contended rows are
   flagged and the load recorded), node split unchanged (spock 24, data 11, ibminode05 14). Measured loads that
   day: spock 4.5, data 66-80, ibminode05 54 -- so data and ibminode05 sit permanently above their thresholds and
   every row of theirs will be flagged. See CORPUS.md "Release preflight and smoke".
3. **Closed 2026-09-11 on the published `v1.2.0` arm.** `preflight` is `PREFLIGHT_OK` on spock, data and
   ibminode05 (the first check of ibminode05); the arm resolves with label `DIAspeXtractor 1.2.0`, provenance
   `binary_sha256` `ec6ae270...`, and 18 `ldd`-resolved libraries all inside the arm, `/ceph` and the system
   library directories, identical across the three nodes but for the node-local glibc set. The smoke
   (`corpus_v3_selftest_v120`, HeLa_22 on ibminode05) produced a 12-tile output with
   `spectrumList count="0000061342"`, and **MSFragger read back `Scans = 61342`**; Sage lower bounds 62,296 and
   52,059 of 62,784 / 61,342. Its two diaTracer peptide cells (Sage 9,186, MSFragger 8,116) equal
   docs/HELA-TABLE.md's published reference numbers for run 22 exactly. `guardtest --node ibminode05` against
   the same arm: **39/39**, `--show` exit 0 -- the first guard test on ibminode05, on the release binary, and
   on `corpus.py` `3601ef3a` (the committed file; the 02:04 guard test ran `10a088d9`, which differs only in
   text outside the measured functions: same three measurement hashes, same 135/135 selftest).
4. **Export privacy:** `harness/corpus.py`, `harness/CORPUS.md` and `harness/review/` belong in `.export-private`
   (repo root, not edited here).
5. **Leftovers of this proof** (public HeLa data only), to delete when no longer needed:
   - on data: `/scratch/kohlbach/corpus_v3_selftest_r2/data` (records, logs, TSVs, run-local tool copies, guardtest
     tree) and `/scratch/kohlbach/corpus_v3_selftest_r2_unit` (selftest copy and output);
   - on ceph: `/ceph/ibmi/abi/oliver/spextract/corpus_v3_selftest_r2/data` (110 files);
   - mutation copies under the scratchpad `mut/`.
6. **Records of the earlier proofs** (`corpus_v3_selftest`) predate measurement hashes. The fixed harness refuses to
   adopt or tabulate them (G-V11/G-V13), by design.
