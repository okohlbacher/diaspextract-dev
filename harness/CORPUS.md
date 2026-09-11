# Corpus mode: `harness/corpus.py`

diaTracer-2.2.1 against our extractor on every registered raw file, each output searched with Sage
and MSFragger. The mode reports peptides, peak RSS and runtime per file, with per-scheme and corpus
totals. It is part of the harness: the standing rule (benchmark numbers come from the harness only)
applies. One module, stdlib only on the nodes (PyYAML only on the laptop side), no driver scripts.

```
python3 harness/corpus.py selftest                                  # offline; every guard must fire
python3 harness/corpus.py pin      --node data                      # print registry pins (read-only)
python3 harness/corpus.py dry-run  --node spock [--plan corpus_v3]  # every command per cell, nothing run
python3 harness/corpus.py launch   --node spock [--plan corpus_v3]  # start that node's queue
python3 harness/corpus.py status   [--node spock]                   # read records; re-invoke to wait
python3 harness/corpus.py collect  --node spock                     # logs, TSVs, records -> ceph
python3 harness/corpus.py table    [--source scratch|ceph] [--out F] # docs/benchmarks/corpus-v3.md
python3 harness/corpus.py guardtest --node data [--show]            # faults on the REAL node (selftest plans)
python3 harness/corpus.py preflight [--node spock]                  # every queue node: python, GNU time, java, DB pins
python3 harness/corpus.py purge    --node spock                     # after the run: mzML/mzBIN kept for failed searches
```

Exit codes: `0` ok, `1` queue finished with failed cells, `2` guard abort, `3` table incomplete, `7`
launch not confirmed. `launch` prints `LAUNCH_OK` for a running queue, and `LAUNCH_FINISHED <verdict>`
when the runner already ended within the confirmation window (a resume with nothing left to do).
`QUEUE_DONE failed N mzml_left M` counts failed cells (failed pairs plus failed search cells, one per engine)
and the mzML/mzBIN files still under `runs/`. A queue that crashes still ends with `QUEUE_ABORTED [CRASH]`
(or `[KILLED]` on SIGTERM). `preflight` exits 2 when a node would abort or is busy; `purge` exits 1 when
files remain.

---

## Registry and plan (`harness/samples.yaml`, private, untracked)

Every sample carries `raw` (ceph `.d`), `scheme`, `acq_min`, `database`, an optional `label` (in-house
rows print the dataset letter) and a `pin`: `analysis.tdf` and `analysis.tdf_bin` byte sizes plus
GlobalMetadata `AcquisitionDateTime` and `InstrumentSerialNumber`. `corpus.py pin --node data` reads
all of them (sqlite `immutable=1`, read-only) and prints the lines to paste; `acq_min` is
`(max - min) Frames.Time / 60`. The bench.py v1 fields (`fingerprint`, `references`, `search`) stay.
The registry is read with a loader that refuses duplicate keys (PyYAML's `safe_load` keeps the last one
without a word), and no two samples of a plan may share a raw path or a pin (G-V01).

A plan is a top-level section (`corpus_v3`, and the proof plans `corpus_v3_selftest`,
`corpus_v3_selftest_r2`, `corpus_v3_selftest_v120`)
with exactly these keys:

| key | meaning |
|---|---|
| `arm` | directory under `spx_root`; its `env.sh` must export `SPX_BIN` (the binary name comes from there) |
| `spx_root`, `diatracer_dir`, `diatracer_jar`, `jnatmp` | install locations |
| `scratch_root` | node-local root; each node works in `<scratch_root>/<node>`; the node lock is `<parent>/.corpus-queue.lock` |
| `results_ceph` | where `collect` copies to (basename must start with `corpus_v3`) |
| `report` | table path relative to the repository |
| `threads` | `-t` for diaTracer, `-threads` for ours (100) |
| `load_wait_min` | how long the load gate waits before running a pair anyway and flagging it (20; T0 decision 2026-09-11) |
| `n_samples` | the number of samples across all queues (49); anything else refuses the plan (G-V01) |
| `search_db_sha256` | sha256 of the two node-local databases the configs name (`sage_fasta`, `msfragger_db`), checked on each node before staging (G-V12) |
| `tools` | `sage`, `sage_config`, `msfragger_jar`, `msfragger_params`, `patch`, `fix` sources (copied run-local) |
| `queues` | `{node: {samples: [...], search_workers: N}}`; a sample may be in one queue only |

---

## What one queue does

`launch` checks the node over ssh (queue lock free, none of our tools running, arm resolvable), copies
`corpus.py` to `<root>/harness/corpus-<sha12>.py` (content-named, never overwritten) and the resolved
queue to `<root>/queue-<nonce>.json`, and starts
`setsid nohup python3 <copy> node-run --queue <json> </dev/null >><root>/runner.log 2>&1 &`. That is one
redirected simple command, so the ssh channel is released. The launch is confirmed by the runner's own
pid stamp and lock line, not by `pgrep`.

**Start.** The runner makes `<root>` mode `0700` (with umask 0022 it was `0755`, so in-house mzMLs, logs
and records were readable by every user of a shared node; `launch` also creates it private). It takes
the node lock, retrying for 5 s because a `status` probe flocks it for microseconds, and removes any staged
copy a killed runner left behind. Then it:
- resolves the arm: `source env.sh` after removing `SPEXTRACTOR_*`, `DIASPEXTRACTOR_*`, `MALLOC_*`, `OMP_*`,
  `GOMP_*`, `KMP_*`, `TCMALLOC_*`, `LD_PRELOAD`, `GLIBC_TUNABLES`, `_JAVA_OPTIONS`, `JAVA_TOOL_OPTIONS`,
  `JDK_JAVA_OPTIONS` and the inherited `LD_LIBRARY_PATH` (`_JAVA_OPTIONS` overrides an explicit `-Xmx`,
  verified on data); `LC_ALL=C`, `TMPDIR=<jnatmp>`. An env.sh that exports any of them aborts (G-V03);
- runs the preflight (G-V15, G-V12): python >= 3.9, `TIME` is a working GNU `time -v`, `/proc` readable,
  `java` resolvable (version recorded), both databases equal to the plan's `search_db_sha256`;
- hashes the identity (G-V04): `SPX_BIN`, every file under `<arm>/lib/`, every library `ldd` resolves under
  the arm environment, the diaTracer jar and `ext/bruker/`, and the JDK (`java`, `libjvm.so`, version). A
  library resolved outside the arm, `/ceph` and the system library directories aborts: the binary's RUNPATH
  points into a node-local OpenMS build tree, which only the arm's `LD_LIBRARY_PATH` overrides. It checks the
  provenance `binary_sha256` and reads the tool label from `SPX_BIN --help` (`Name -- ...`, `Version: x`);
- copies the search tools into `<root>/tools/`;
- computes the measurement-code hashes `pair`, `search` and `score`: sha256 of the sources of the functions
  that stage, gate, time and verify an arm; that run and check a search; and that count peptides, plus the
  constants they use;
- re-counts search records whose `score` hash changed from their kept TSVs, and deletes every extractor mzML
  whose two searches are done (a runner killed between the second record and the delete left it behind).

**Phase 1: timed pairs, one at a time, no searches on the node.** For each sample, in queue order:
1. Check the ceph raw against its pin, and its acquisition length (`Frames.Time`) against `acq_min`.
2. Copy it, data only, into a fresh `0700` directory as `<root>/stage/<id>-<pair_run>/<id>.d` (folders `0700`,
   no modes, ACLs or xattrs: `cp -a` failed on the ceph ACLs and left read-only `*.m` folders that could not
   be deleted), and check the copy against the pin as well. The neutral name keeps the specimen id of the
   in-house basenames out of command lines, tool logs and records (our tool echoes its input path).
3. Run the load gate: 1-min load <= 24 on nodes with >= 200 cores, <= 12 otherwise, and none of our tools
   running. The gate polls every 60 s, for up to `load_wait_min`, then runs anyway with
   `gate.contended = true`.
4. Before each arm, outside its timed window: `syncfs` of the node-local filesystem (the staging copy and the
   previous arm's mzML are written back here, not inside the next arm) and the pre-warm
   `cat analysis.tdf analysis.tdf_bin > /dev/null`. Both durations are recorded per arm.
5. Run both arms back to back. Queue index 0, 2, 4... runs diaTracer first; 1, 3, 5... runs ours first.
   Each arm is hashed before and after; load, MemAvailable, `ps` top-5 and timestamps are recorded. While an
   arm runs, a sampler reads `/proc` every 10 s: foreign CPU is the busy CPU ticks minus the ticks of the
   runner's own process tree (a reaped child stays counted in its parent), and MemAvailable. The arm is
   flagged (`during.contended`) when its highest 60-s foreign-CPU mean exceeds the gate threshold, when
   MemAvailable falls below 5% of MemTotal, or when it was not measured.
   ```
   cd <diatracer_dir> && LC_ALL=C LD_LIBRARY_PATH=./ext/bruker /usr/bin/time -v -o dt/time.log \
     java -Xmx400G -Djna.tmpdir=<jnatmp> -Djava.io.tmpdir=<jnatmp> -Djna.library.path=./ext/bruker \
     -jar diaTracer-2.2.1.jar -d <staged .d> -t 100 -w dt/ -mC 0.3 -dI 0.01 -dR 3 -rM 500 -mF 1 -mO 0.1 -r 0
   cd spx/ && /usr/bin/time -v -o spx/time.log $SPX_BIN -in <staged .d> -out spx/pseudo.mzML -threads 100
   ```
6. Verify each output. It must be fresh (mtime > arm start) and terminated, with an integer
   `spectrumList count` > 0 (zero padding is tolerated). The tool's own count must also be present and
   equal: diaTracer's `Writing mzML file...N scans`, our `Wrote N pseudo` (bytes regex, so binary bytes
   in the log cannot hide the line). diaTracer writes beside its input, so its mzML is moved from the
   stage into `runs/<id>/<pair_run>/dt/`.
7. Delete the staged copy in `finally`, on success, failure and SIGTERM alike. Write the pair record.

**Phase 2: searches**, started only after every pair in the queue has finished. Each output is one unit:
- Sage (`sage sage_deiso.json -o <dir> --disable-telemetry-i-dont-want-to-improve-sage <mzML>`). On
  diaTracer output it runs on a copy patched by `patch_diatracer_precursor.py`.
- MSFragger (`java -Xmx200G -jar MSFragger-4.4.1.jar msfragger.params ./in.mzML`), with
  `in.mzML -> fixed.mzML` from `fix_mzml_cvparams.py`. Both tools' output goes through the fix, as in
  `tnbc_ref.sh` / `hela_ref*.sh`.

Every step runs under `time -v`. Each search must show that it read the whole output:
- the patch writes a selected ion m/z into every diaTracer spectrum (`patched N` equal to the spectrumList
  count);
- MSFragger's `in.mzML: Scans = N` equals the count (a zero-padded count or a per-spectrum NPE would
  otherwise drop spectra silently);
- Sage 0.14.7 logs only a rate, `- search: D ms (R spectra/s)`, over the spectra with >= `min_peaks` peaks
  (sage-cli `main.rs:138-141`), so `floor(R * (D + 1) / 1000)` is a lower bound on what it searched; it must
  lie between 50% and 100% of the count (HeLa_2740: 99.96% diaTracer, 99.75% ours).

Units with a pending MSFragger search run alone until one MSFragger search has succeeded (it may build the
`.pepindex` beside the database, and a failed first one built none); the rest run with `search_workers` in
parallel. Engine steps record start and end epochs, so the table marks overlapping searches. Patched and
fixed copies and `*.mzBIN*` are removed after each engine. The extractor mzML is removed once both engines of
that output succeeded, and again by the sweep at the start and end of every launch; otherwise it is kept so
the failed search can be re-run, `status` lists it, and `purge` removes it after the run.

**Layout.** Everything lives under `<root>`:
- `records/<id>.pair.json` and `records/<id>.<dt|spx>.<sage|msfragger>.json`: the only source for
  `status` and `table`, written atomically;
- `runs/<id>/<pair_run>/{dt,spx}/`: logs and time logs;
- `runs/<id>/<pair_run>/search/<tool>_<engine>/`: engine logs, time logs, `results.sage.tsv` / `in.tsv`;
- `runner.log`, `QUEUE_DONE-<nonce>`.

**Resume.** Re-launching a queue re-runs only cells that are not proven done (G-V11):
- A pair counts as done only if its record is `ok` and all of the following hold:
  - the same build identity: binary, `lib/**`, ceph-resident libraries, jar and Bruker library sha256, and
    the same JDK feature version. Node-local system libraries and the JDK's exact files are recorded and
    guarded within a queue (G-V04), but may differ between nodes and launches;
  - the same `pair` measurement-code hash, thread count, pin and raw path (compared as sha256);
  - both outputs were verified fresh;
  - each output either has both searches done, or still exists with the recorded size and mtime.
- A search counts as done only for the current `pair_run`, with the same tool sha256s, the same `search` and
  `score` hashes, and peptides > 0. A search whose only change is the `score` hash is re-counted from its kept
  TSV at the start of the launch (the engine is not re-run; the record keeps the old counts under
  `rescored`). A changed `search` hash re-runs the searches, and the pair as well when its mzML is gone.
- A failed or superseded pair is re-run whole, in a new `pair_run` directory. An existing mzML is
  never adopted, and a failed arm never re-runs the other arm in the same attempt.
- Any edit to a measured function, even a comment, changes its hash: finish harness edits before T0.

**Waiting.** Re-invoke `status`; never hold one ssh session open. A local loop is fine, keyed on the
node lock (runner.log is appended across launches, so an old `QUEUE_DONE` can still be in the tail):
`until python3 harness/corpus.py status --node spock | grep -q "lock free"; do sleep 600; done`, then
read the log tail for `QUEUE_DONE failed N` or `QUEUE_ABORTED`.
Stop a queue with `kill -TERM <pid>`: the runner cleans its stage and writes the record. The running
tool child is not killed; `kill -- -<pid>` stops the whole session.

**Retention.**
- Logs, time logs, TSVs and records stay under `<root>` until collected.
- `collect` (refused while the node lock is held) copies `<root>` to `<results_ceph>/<node>`, leaving out
  `stage/`, `tools/`, `queue-*.json` (they carry the raw paths), `*.mzML` and `*.mzBIN*`. It then removes
  group and other permissions from every copied path (with POSIX ACLs this lowers the mask) and refuses
  (G-V14) if a path is still accessible. Records carry the raw path only as a sha256.
- Staged raw copies never outlive their pair; `purge` removes mzMLs kept for failed searches.

---

## Guards

Queue-level aborts stop the queue (exit 2, `QUEUE_ABORTED` in the log). Cell-level aborts write a
`failed` record with the guard id, and the table prints `FAILED G-Vxx`, never a number. Every id is
triggered by `--selftest`, which fails if any id never fires.

| id | level | refuses | failure it prevents |
|---|---|---|---|
| G-V01 | launch | unknown plan key, missing sample field or pin, sample in two queues, unknown sample/node, duplicate YAML key, two samples sharing a raw path or pin, sample count != `n_samples`, malformed `search_db_sha256` | a typo that parses and silently drops or duplicates a file |
| G-V02 | cell | raw or staged copy differs from the pin (tdf sizes, acquisition time, serial); the raw's acquisition length differs from `acq_min` | a row labelled with the wrong acquisition (FAILURE 1 of bench.py); a mistyped `acq min` in the table |
| G-V03 | queue | env.sh missing/failing; SPX_BIN unset, not executable, or outside the arm directory; env.sh itself exporting a stripped variable (probe, allocator, OpenMP, JVM options); provenance missing or its `binary_sha256` differing; no label from `--help`; a library unresolved, or resolved outside the arm, `/ceph` and the system library directories | a dev build, a probe knob, a tcmalloc preload or a node-local OpenMS build tree measured as "the release" (critique C7, F7) |
| G-V04 | queue | SPX_BIN, `lib/**`, a resolved library, the jar, `ext/bruker/` or the JDK changing across an arm | republish under a running chain (SIGBUS, silent empty run); a conda or JDK update between two arms |
| G-V05 | launch/queue | node lock held by another corpus queue; our tools already running (bracketed, case-correct `pgrep -f`: `diaTracer-2\.2\.[1]\.jar`, `MSFragger-4\.4\.[1]\.jar`, `/sag[e] `, `spextracto[r] -in`, plus the SPX_BIN basename) | two timed runs on one node; self-matching busy checks |
| G-V06 | flag | before the pair: 1-min load > 24 / 12 or our tools running after `load_wait_min`; during an arm: highest 60-s foreign-CPU mean above the same threshold, MemAvailable < 5%, or not measured | contended walls reported as clean, including contention that starts after the gate (the row is flagged) |
| G-V07 | cell/queue | scratch root on ceph (queue); staging copy failed; an arm input outside the 0700 stage root; the ceph `<raw>_diatracer.mzML` changing during the diaTracer arm (queue) | overwriting or reusing the stale reference output beside the raw data; patient data outside a private node-local directory |
| G-V08 | cell | exit != 0, `Command terminated by signal`, unparseable time log, output missing/stale/unterminated, count <= 0, tool count line missing or different | a SIGBUS with exit 0, a truncated file, an old file accepted |
| G-V09 | cell | (structural) a failed first arm ends the attempt | `a && b \|\| c` re-running both arms and overwriting the first timing (critique C8) |
| G-V10 | cell | patch count != spectra; fix without `done:`; Sage without `finished in`, or searching < 50% (or > 100%) of the spectra; MSFragger without `TOTAL TIME`, or `Scans` != spectra; exit != 0; TSV missing, header-only or lacking columns; 0 peptides | the silent `Sage: 0` of unpatched diaTracer output; `Scans = 0` MSFragger runs; a partial read that lowers one tool's count |
| G-V11 | cell | (resume) records of another build identity, JDK feature version, measurement code, thread count, pin, raw or pair_run; extractor output changed since its pair | skipping a run because an old mzML exists; a table mixing two verification or counting rules after a mid-run harness fix |
| G-V12 | queue | run-local tool copy differs from its source (tools changed between launches); a database differs from the plan pin (preflight, queue start) or changed during the run | cells of one table searched with different configs or databases, found only when the table refuses after the run |
| G-V13 | table | more than one build, JDK feature version, thread count, measurement code or search setup across records (or ok records without measurement hashes); pair arms on two hosts; ok record with count, RSS or peptides <= 0; record pin or raw differs from the registry | a table mixing builds, rules, nodes or corrupted records |
| G-V14 | queue/collect/purge | staged copy not deleted; collect or purge while the lock is held; destination not a `corpus_v3*` results directory; a collected path still group/other-accessible | patient-derived data lingering, or readable on ceph; writing into a published arm |
| G-V15 | queue/launch | root under `/home`; `jnatmp` not writable; MemAvailable or `/proc` unreadable; python < 3.9; `TIME` not GNU `time -v`; no `java`; JDK feature versions differing across nodes (`preflight`) | the quota-killed "12 h JNA trap"; unrecorded memory state; a queue that crashes after 20 h without a marker |

---

## Peptide counts (the rule and its source)

The rule is the one that produced the most recent head-to-head tables. `docs/TNBC-TABLE.md` came from
`/ceph/ibmi/abi/oliver/spextract/tools/bench_table.py` (sha256 `6809927b07606fa3...`). `docs/HELA-TABLE.md`
came from `hela_table.py` (sha256 `26df867abd67235b...`), which defines identical `sage_peps()` and
`msf_peps()`. `corpus.py` ports both functions line for line as `sage_peptides()` / `msf_peptides()`:

- **Sage:** the number of distinct `peptide` strings over rows with `rank == "1"` and
  `peptide_q <= 0.01`. Columns are resolved by header name, and decoy rows are *not* removed, as in the
  source. With `report_psms 1` every row is rank 1, so the rank filter removes nothing, and the count is
  **target+decoy**: on HeLa_2740, 7,391 counted vs 7,323 target-only for diaTracer (0.9%), 6,652 vs 6,590
  for ours. The historical drivers' awk (`$8==1`, label) counted target-only. The record carries
  `target_peptides` and `diag_decoy_peptides_in_set`; the table header prints the target-only totals.
- **MSFragger:** best `hyperscore` per (`peptide`, `modification_info`), sorted descending
  (`sorted(values, reverse=True)`, so ties put decoys first). Walk down the list and keep the deepest
  prefix with decoy/target <= 1%. A PSM is a decoy when every entry of `proteins`, split on `,;@`,
  starts with `rev_`. With `human_decoy.fasta` (decoy headers `rev_<acc> decoy`, no separators) this
  equals the "starts with `rev_`" rule of `score_msf_td.py`. The only exception is a row with an empty
  `proteins` field, which `bench_table.py` counts as a decoy.
- Ratios in the table are ours / diaTracer. A count of 0 is a failed search (G-V10) and never reaches
  the table.

Not in this run, and not computed: entrapment FDR (option for later: Sage with `sage_entrap.json` and
`bench/entrapment.py`, with mandatory charge strata), per-charge walks, protein groups, and replicates
(n = 1 per cell).

---

## Reading the table

- One row per file, showing the scheme, acquisition minutes, and the node taken from the record's
  hostname.
- Load flags; diaTracer and our wall and peak RSS; both spectrum counts; Sage and MSFragger peptides
  for both tools, with ratios; engine-step walls.
- Summary rows per scheme and for the corpus: totals, flagged rows (`k/n`), the median per-file wall
  ratio of all rows and of unflagged rows, median RSS, and peptide totals with ratio of totals and median
  per-file ratio. They include complete rows only.
- Load flags: `gate: load X > T` (the pair ran after `load_wait_min`) and `during <tool>: foreign CPU X
  cores > T` or `MemAvailable X% of total` (measured while that arm ran).
- **RSS GB = `time -v` kbytes / 1e6.** GNU time's kbytes are KiB, so one unit is 1.024e9 bytes; multiply by
  0.9537 to compare with the GiB of the older HELA/TNBC tables.
- Walls are comparable within a row only: back to back, one node, staged, synced and pre-warmed.
- Search walls ran with up to `search_workers` concurrent searches and are indicative; `†` marks an engine
  step that overlapped another search on the same node.
- The header prints the measurement-code hashes (one value across the table), the JDK per node, and any
  node-local system library that differs between nodes.
- diaTracer's RSS partly reflects `-Xmx400G`.
- The tool label in the headers comes from `SPX_BIN --help`, and the build from the provenance lines.

---

## Selftest and cluster proof

`corpus.py selftest` builds a fake world in a temp directory and runs the real code paths, in process,
against it:
- a sqlite `analysis.tdf`, a fake GNU `time`, `java` (diaTracer and MSFragger), extractor, Sage, patch
  and fix;
- arms that export probes, point outside, carry a bad provenance, or print no label.

It runs whole queues: happy, resume, first-arm failure, wrong pin, search failures, signal, miscount,
changed output, new binary, and writes beside the ceph raw. It also checks table and collect guards,
the lock, a real bracketed `pgrep`, and the dry-run output. Since 2026-09-11 it also runs the whole
`guardtest` against the fake world (37 cases, the same code that runs on a node), a SIGTERM in the
middle of an arm (record `failed KILLED`, stage deleted, re-run on the next launch), the private
`0700` root, the refusal of `guardtest` for a non-selftest plan, and the node-lock probe: 85 cases.
`status`, `collect` and `launch` probe the node lock with a SHARED non-blocking flock. Until 2026-09-11
the probe was exclusive, so two concurrent probes (say `status` and `collect` from two terminals) could
see each other as a running queue and refuse spuriously. A queue's exclusive lock still conflicts with a
probe, and a runner starting during a probe retries for 5 s. The fake GNU `time`
now reports a signalled child the way GNU time does (`Command terminated by signal N`, `Exit status:
0`), and the fake diaTracer needs a `.so` in its cwd-relative `ext/bruker`, like the real jar.

Records are written at the start of each pair and search with `status: running`, so `status` shows the
attempt in flight rather than the previous attempt's verdict. `kill -TERM` (or ^C) marks the record
`failed` with guard `KILLED`; before 2026-09-11 it raised a KeyError in the pair's `finally` and left
`running` behind. Only SIGKILL leaves a `running` record behind a free lock; the next launch replaces it.
Pair records also carry `env_keys` (the names of every variable the tools saw) and `ld_library_path`.

### Cluster proof run (2026-09-10, node `data`, plan `corpus_v3_selftest`)

Settings: one public file (HeLa_2740, 5.6 min), run against the existing published arm `v2.0.0`, which
was executed and not modified. data had 224 cores and a 1-min load of 44-129 from other users. These
are harness checks, not benchmark numbers: an old arm, a contended node, n = 1.

- **First launch: G-V14 fired.** `cp -a` of the ceph `.d` failed on its ACLs. It left a copy holding
  only the read-only `2740.m` folder, which `rmtree` could not delete, and the queue stopped. The fix
  is a data-only copy with 0700 folders plus a removal that clears read-only folders first. The
  selftest raws now contain a read-only method folder. The record fix keeps the first failure's reason
  when cleanup also fails.
- **Second launch ran end to end:**
  - The gate flagged the pair `contended` after 62 s at load 64. Order was diaTracer first.
  - diaTracer: 1:02 wall, 33.5 GB, 117,388 spectra. The count matches its `Writing mzML file...N scans`.
  - Ours: 0:21 wall, 7.7 GB, 97,505 spectra. The count matches `Wrote N pseudo`.
  - The ceph `_diatracer.mzML` beside the raw is unchanged (size and Sep 5 mtime). The staged copy
    was deleted.
  - Sage: 7,391 peptides for diaTracer (patched copy) and 6,791 for ours. MSFragger: 9,032 and 6,235.
    Every log carried `finished in` / `TOTAL TIME`. The existing `.pepindex` was reused.
  - Both mzMLs and all `*.mzBIN*` files were deleted. The runner logged `QUEUE_DONE failed 0`.
- **Relaunch (resume):** the pair record verified, and the pair and all four searches were skipped.
  `launch` printed `LAUNCH_FINISHED ... failed 0`.
- **Collect and table:** `collect` copied 41 files to
  `/ceph/ibmi/abi/oliver/spextract/corpus_v3_selftest/data`. `table --source ceph` rendered 1 of 1 rows
  complete, with no zero cell. The tool label and build hashes came from the records.
- **Afterwards:** `pgrep -cf` for diaTracer, MSFragger, Sage, the extractor and the runner returned 0
  on data.

### Cluster proof run 2 (2026-09-11, node `data`, plan `corpus_v3_selftest`, arm `dnoise_s2c`)

Settings: the smallest Evosep 200SPD file (HeLa_2740, 5.6 min, 693 MB), the published arm `dnoise_s2c`
(binary still named `spextractor`, taken from its `env.sh`; sha256 `bcda6bfa...` equal to its provenance;
`--help` label `SpeXtractor 2.0.0`, git `cc39a66+dirty`). data: 224 cores, 1-min load 70-112 from other
users. Harness checks, not benchmark numbers.

- **Switching the arm (G-V11 on the node):** the v2.0.0 records of proof run 1 were not adopted. The
  pair and all four searches re-ran in a fresh `pair_run`; `status` showed the old searches as `stale`.
- **Launch → `QUEUE_DONE failed 0`** (00:02-00:07):
  - gate `contended` (load 73.8 > 24, waited 62 s); staging 5.2 s; order diaTracer first;
  - diaTracer 68.1 s, 41.8 GB, 117,388 spectra = its `Writing mzML file...117388 scans`;
  - ours 14.6 s, 5.5 GB, 75,026 spectra = `Wrote 75026 pseudo`;
  - Sage 7,391 / 6,652 and MSFragger 9,032 / 6,066 peptides (diaTracer / ours), each record on the
    current `pair_run`; every step exit 0 under `time -v`;
  - afterwards: no `*.mzML`, `*.mzBIN*` or staged copy under the root; root `0700`; the ceph
    `_diatracer.mzML` beside the raw unchanged (925,925,883 B, 2026-09-05 14:48); bracketed `pgrep` of
    diaTracer, MSFragger, Sage, the extractor and the runner all 0. `env_removed` was empty on data.
- **Second launch:** `LAUNCH_FINISHED ... failed 0`, the log says `already done (record verified):
  skipped`, and the five record files kept their mtimes (nothing re-ran, nothing rewritten).
- **Collect and table:** 73 files to `/ceph/.../corpus_v3_selftest/data`; `table --source ceph` rendered
  the row with all 19 columns filled, no pending/FAILED/zero cell.

## Guard test on a real node (`corpus.py guardtest --node data`)

`selftest` proves the guard logic against fakes. `guardtest` proves the guards on the node itself: the
plan's real raw file (staged exactly as in a queue), its real arm, diaTracer jar, Sage, MSFragger and
FASTAs, and the production queue code (`_node_run`). Each fault enters through a fixture built under
`<root>/guardtest/<nonce>/fixtures/`, never through a branch in production code and never by touching a
published arm or tool. It refuses non-selftest plans, holds the node lock for its whole run, starts
detached like `launch`, and is read back with `guardtest --node data --show` (exit 0 only when every
case passed and the lock is free). Results: `<root>/guardtest/<nonce>/RESULTS.txt`, marker
`GUARDTEST_DONE-<nonce>`, scenario records and logs under `<root>/guardtest/<nonce>/<scenario>/`.

| case | fixture | must happen |
|---|---|---|
| GT0 | the main run's real records on the node | the record of the current binary/lib/jar is trusted; the same record with a changed binary, lib or jar sha256 is not (G-V11); the real row renders complete; mixed with another binary's records the table refuses (G-V13) |
| GT1 | diaTracer directory with the real jar but an empty `ext/bruker` (the JNA trap) | diaTracer runs first and fails (G-V08); the extractor arm never runs (G-V09); gate not flagged with `load_max` 1e9 (G-V06); stage deleted |
| GT2 | queue `[wrong-pin copy, sample]`; arm wrapper that kills the real extractor after 5 s and then dies by SIGBUS | the wrong pin is refused on the ceph raw (G-V02); `time` reports the signal with exit status 0 and the arm fails (G-V08); the extractor ran once and diaTracer never (G-V09); gate flagged with `load_max` 0 (G-V06) |
| GT3 | arm wrapper: real extractor, then output mtime set 1 h back | stale output fails the arm (G-V08); diaTracer never runs (G-V09) |
| GT4 | arm wrapper: real extractor, then it appends to its own file | SPX_BIN sha256 changed during the arm: queue abort (G-V04), stage deleted |
| GT5 | arm whose provenance carries the real binary's sha256, not the wrapper's | refused before any pair (G-V03) |
| GT6 | real pair; Sage wrapper setting every `peptide_q` to 1.0; `java` wrapper on PATH dropping MSFragger's `TOTAL TIME` line | both arms ok with counts equal to the tools' lines; gate flagged at `load_max` 0; each Sage cell fails with rows but "0 peptides" and each MSFragger cell fails on the missing `TOTAL TIME` (G-V10); both mzMLs kept; `QUEUE_DONE failed 4` |
| GT7 | second queue while the guardtest holds the lock | G-V05 |
| GT8 | `collect` while the lock is held | G-V14 |

Afterwards it deletes the run-local tool copies, the jar copy, and every mzML/mzBIN under the
guardtest root, and checks nothing staged is left. `load_max` exists only in guardtest queues; plans
cannot set a threshold.

### Guard test proof (2026-09-11, node `data`, nonce `20260911-000857-e09e6d`, arm `dnoise_s2c`)

Run right after cluster proof run 2, on its records, at 1-min load 84-111:
- **GT0:** the real pair record was trusted with the current identity and refused with a changed binary,
  lib or jar sha256; the real row rendered complete; real records mixed with another binary's were refused
  (`records come from more than one binary/lib/jar`).
- **GT1:** diaTracer with an empty `ext/bruker` exited 1 within 3 s (`dt failed: time rc=1 exit=1`);
  the record holds only the `dt` arm and no `spx` directory exists; gate not flagged at `load_max` 1e9.
- **GT2:** the wrong-pin copy was refused on the ceph raw before staging (G-V02). The SIGBUS wrapper
  reproduced the historical republish failure exactly: `spx failed: time rc=135 exit=0 signal=7`. The
  extractor ran once, diaTracer never; the gate was flagged at `load_max` 0 (load 83.7).
- **GT3:** `output is stale (mtime 1789074577 <= arm start 1789078161)`; diaTracer never ran.
- **GT4:** `binary/lib/jar changed during the spx arm`: queue abort, pair record G-V04, stage deleted,
  no `QUEUE_DONE`.
- **GT5:** `provenance binary_sha256 ['bcda6bfa...'] != sha256(SPX_BIN)`: refused before any pair.
- **GT6:** a real pair through the `java` wrapper (diaTracer 64.0 s, 117,388 spectra; ours 14.7 s,
  75,026; both equal to the tools' lines), gate flagged at `load_max` 0 (load 100.6). Real Sage finished
  (`finished in` present) with 102,805 rows on diaTracer's patched output and 58,040 on ours, and each
  cell failed with `0 peptides at 1%: a failed search, never a result`. Both MSFragger cells failed with
  `MSFragger log lacks 'TOTAL TIME'`. Both mzMLs were kept; `QUEUE_DONE failed 4`.
- **GT7:** `another corpus queue holds /scratch/kohlbach/.corpus-queue.lock` (after the 5 s retry).
- **GT8:** `a queue still holds the node lock (pid ... guardtest ...): collect after QUEUE_DONE`.
- **37/37 cases pass** (00:08:57-00:14:21). Afterwards, under the guardtest root: no staged raw, no
  `*.mzML`, no `*.mzBIN*`, no run-local `tools/`; bracketed `pgrep` for diaTracer, MSFragger, Sage, the
  extractor and both runner kinds all 0; lock free.
- **Final harness re-check** (after the shared-lock probe fix, `corpus.py` sha256 `7ab160cd...`, 00:16):
  offline `selftest` 85/85; on data a relaunch skipped the verified pair (record mtimes unchanged),
  `collect` copied 152 files (0 mzML/mzBIN/stage/tools on ceph), `guardtest --show` exit 0 (37/37),
  `table --source ceph` 1 of 1 rows complete, bracketed `pgrep` all 0.

## Review fixes (2026-09-11, `harness/review/verdicts.md`)

The kimi, vibe and internal findings F1-F16 were verified against the code and node `data`; 15 are fixed, F7 is a
user decision. What changed is described in the sections above. Proof:
- **Offline selftest:** 135/135 on the laptop.
- **Mutation proof:** 22/22. Each fix, re-broken alone in a copy (`scratchpad/mutate_corpus.py`), makes the copy's
  selftest fail.
- **End-to-end on data**, plan `corpus_v3_selftest_r2`, fresh directories, same arm `dnoise_s2c` and file as proof run
  2, nonce `20260911-015345-7f75e7`:
  - `QUEUE_DONE failed 0 mzml_left 0`.
  - diaTracer: 66.5 s, 36.2 GB, 117,388 spectra. Ours: 15.9 s, 5.6 GB, 75,026 spectra.
  - Sage 7,391 / 6,652 and MSFragger 9,032 / 6,066: identical to proof run 2.
  - Engine read checks: MSFragger Scans 117,388 and 75,026; patch 117,388; Sage lower bounds 117,341 and 74,838.
  - Target-only Sage 7,323 / 6,590.
  - Row flags: `gate: load 55.9 > 24; during dt: foreign CPU 54.3 cores > 24; during spx: foreign CPU 49.1 cores > 24`.
  - 18 resolved libraries pinned (12 on ceph); JDK 21.0.12; staged as `HeLa_2740.d`, `acq_min_read` 5.6.
  - No raw basename in records or runs.
  - Relaunch: every record verified and skipped, record mtimes unchanged.
- **Guard test on data** (nonce `20260911-020442-acb43a`, harness `10a088d9`): 39/39. It adds two GT0 cases: a
  changed ceph-resident library and a changed measurement-code hash are not adopted.
- **Offline selftest on data** with the same harness: 136/136 (the extra case reads the real `/proc`).

## Release preflight and smoke (2026-09-11, arm `v1.2.0`)

The last two items the review left open (`harness/review/verdicts.md`, "Still open" 2 and 3): the real
release binary had never run under the harness, and no multi-tile, zero-padded output had gone through
either engine. Both are closed here. `corpus_v3` now points at the published arm and waits 20 min.

**Preflight on all three queue nodes** (`corpus.py preflight`, `PREFLIGHT_OK`), the first check of
ibminode05:

| | spock | data | ibminode05 |
|---|---|---|---|
| cores / 1-min load | 224 / 4.5 | 224 / 80 | 128 / 57 |
| python, GNU `time -v`, `/proc` | ok | ok | ok |
| JDK | 21.0.12 | 21.0.12 | 21.0.12 |
| `sage_fasta` / `msfragger_db` sha256 | pins match | pins match | pins match |
| queue lock, our tools running | free, none | free, none | free, none |
| `/scratch` free | 18.9 TB | 9.0 TB | 8.4 TB |

Beyond what `preflight` itself covers, the same node-side code (`arm_env`, `identity`, `arm_meta`) was run
read-only on each node: the arm resolves to `/ceph/ibmi/abi/oliver/spextract/v1.2.0`, `SPX_BIN` is inside
it, `env.sh` exports nothing that would be stripped (`env_removed` empty), `--help` gives the label
**DIAspeXtractor 1.2.0**, the provenance's `binary_sha256` equals the binary's, and `ldd` under the arm
environment resolves **18 libraries, all inside the arm, `/ceph` and the system library directories**
(12 on ceph). Equal on all three nodes: binary, `lib/**`, the 12 ceph-resident libraries, the diaTracer
jar and `ext/bruker/**` (including `libtimsdata-2-21-0-4.so`), Sage, the MSFragger jar, both engine
configs, the patch and fix scripts, and both databases. The six libraries that differ are the node-local
glibc set (`libc`, `libm`, `libpthread`, `librt`, `libdl`, `ld-linux`), which `build_identity` excludes by
design and the table header lists.

**Smoke, plan `corpus_v3_selftest_v120`, node ibminode05, HeLa_22** (120 min, the file the release smoke
showed at 12 tiles), 08:45:20-08:51:45, `QUEUE_DONE failed 0 mzml_left 0`:

- gate flagged (`load 47.0 > 12`, waited 61 s); staging 15.3 s; `acq_min_read` 120.0; order diaTracer first.
- diaTracer 2:02, 91.6 GB, 62,784 spectra = its `Writing mzML file...62784 scans`, and equal to the count in
  the reference mzML that has sat beside the raw since 2026-09-05 (unchanged, 421,492,539 B).
- Ours 0:51, 4.8 GB, **`spectrumList count="0000061342"`** over **12 tiles**
  (`coverage: 144644 precursor-window pairs owned exactly once over 12 tile(s)`), equal to
  `Wrote 61342 pseudo`.
- Both arms flagged `during` (foreign CPU 40.8 and 40.1 cores > 12) from other users' work.
- Four searches, all ok, every read check on a real value: patch 62,784 = the count; MSFragger
  `Scans` **62,784** and **61,342** -- the zero-padded count read back exactly; Sage lower bounds 62,296
  (99.2%) and 52,059 (84.9%, the sparse 10 ng spectra below `min_peaks`, as review F1 predicted).
- Peptides: Sage 9,186 / 4,423, MSFragger 8,116 / 2,850 (diaTracer / ours). **The two diaTracer cells equal
  docs/HELA-TABLE.md's published reference numbers for run 22 exactly** (9,186 and 8,116), which is an
  independent check of the whole scoring path. The low ratios are this scheme, not a regression: the
  2026-09-05 table has 4,764 / 2,676 for the old build on the same file.
- `collect` copied 33 files to `/ceph/.../corpus_v3_selftest_v120/ibminode05` (0700, no group/other),
  `table --source ceph` rendered the row complete, `purge` found nothing left.
- Afterwards on ibminode05: no `*.mzML`, `*.mzBIN*` or staged copy under the root, root `0700`, the raw
  basename only in `queue-*.json` (which `collect` skips) and nowhere in `records/`, `runs/` or on ceph,
  bracketed `pgrep` for diaTracer, MSFragger, Sage, the extractor and the runner all 0, lock free.

**Guard test on ibminode05** against the same arm (`guardtest --plan corpus_v3_selftest_v120 --node
ibminode05`, nonce `20260911-090102-9df84f`, 09:01-09:08, node load 44-94): **39/39**, `guardtest --show`
exit 0, lock free afterwards. This is the first guard test on ibminode05 and the first on the release
binary. GT5 refused a wrapper arm carrying the release provenance
(`binary_sha256 ['ec6ae270...'] != sha256(SPX_BIN) ffe94686...`); GT2 reproduced the republish SIGBUS
(`rc=135 exit=0 signal=7`) and refused the wrong-pin raw; GT4 aborted on a binary changing mid-arm; GT6 ran
a real HeLa_22 pair (2:50) whose four searches all failed as intended (Sage with 49,138 rows and 0 peptides,
MSFragger without `TOTAL TIME`), kept both mzMLs and reported `failed 4`; GT7 and GT8 refused a second queue
and a `collect` while the lock was held. Afterwards: no staged raw, mzML or mzBIN under the guardtest root,
bracketed `pgrep` all 0, the ceph reference mzML and the published arm byte-identical.

Offline `selftest` on the laptop with the same `corpus.py`: **135/135**, and the measurement hashes are
still `050e2e2a` / `064af71b` / `4fe0a1ce` -- the harness has not drifted since the review. One caveat: the
39/39 guard test of 2026-09-11 02:04 ran on `corpus.py` `10a088d9`, and the file that will run the corpus is
`3601ef3a` (the rename pass landed afterwards in 3814eee). The three measurement hashes and the 135/135
selftest are identical across the two, so no measured function changed -- and the guard test above re-proves
all 39 cases on `3601ef3a` itself.

### Estimated queue hours

From the diaTracer reference mzML beside every raw (exact spectra and bytes for all 49), the `ref wall`
columns of docs/HELA-TABLE.md and docs/TNBC-TABLE.md, the v1.2.0 walls of the release gates and this
smoke, and a least-squares fit of the eight engine steps measured by the two harness runs (Sage
0.387 ms/spectrum, MSFragger 12.4 s + 0.444 ms/spectrum, both at `search_workers: 1`):

| node | n | phase 1 | phase 2 | gate wait at today's load | total |
|---|---:|---:|---:|---:|---:|
| spock | 24 | 6:07 | 6:21 | 0:00 (load 4.5, under 24) | **~12.5 h** |
| data | 11 | 4:56 | 5:26 | 3:40 (load 66-80, every pair waits) | **~14.0 h** |
| ibminode05 | 14 | 1:54 | 3:03 | 4:40 (load 54, every pair waits) | **~9.6 h** |

The corpus finishes with the longest queue, so ~14 h at today's loads, one night. Phase 2 carries the
uncertainty: it extrapolates the patch/fix step from 0.2-0.9 GB mzMLs to a ~28 GB TNBC one, and assumes
our spectrum count equals diaTracer's on the HeLa schemes where v1.2.0 has never been measured (it is
0.709x on the in-house file, 1.080x on TNBC, 0.977x on HeLa_22). Treat the totals as +-30%.

Because both data and ibminode05 sit permanently above their load thresholds (24 for >= 200 cores, 12
below), **every row from those two nodes will be flagged and none from them will enter the unflagged wall
ratios**; spock at load 4.5 is the only node whose rows can be clean, which is an argument for leaving the
largest queue there. Moving `TNBC_013` from data to ibminode05 would even the queues out (12.5 / 12.6 /
11.6 h, longest 12.6 h), a ~1.4 h saving that is inside the estimate's own error bar; not taken.

## Before the real run

- Publish the arm first and never republish it during the run. `<arm>/env.sh` must export `SPX_BIN`,
  and `SPX_BIN.provenance` must carry `binary_sha256=`. **Done 2026-09-11: `corpus_v3.arm: v1.2.0`**, the
  published release arm (`bin/diaspextractor`, sha256 `ec6ae270...`, git `91a1b28`).
- Point a selftest plan at the release arm and run one file end to end, then `guardtest --node <n>` with
  `guardtest --show` exit 0. Both prove the label, the `Wrote N pseudo` line and the arm on the renamed
  binary before a timed pair uses them. A one-file smoke on a multi-tile output (e.g. HeLa_22) additionally
  proves MSFragger on a zero-padded `spectrumList count`. **Done 2026-09-11**, plan
  `corpus_v3_selftest_v120` -- see "Release preflight and smoke" below.
- Run `preflight` (all queue nodes: python, GNU time, JDK feature version equal across nodes, database pins,
  nothing of ours running, lock free; `PREFLIGHT_OK`), then `dry-run --node <n>` for each node. Launch one
  node at a time and check `LAUNCH_OK`. **Done 2026-09-11: `PREFLIGHT_OK` on spock, data and ibminode05**
  (the first check of ibminode05), plus a `dry-run` on ibminode05.
- Decide the node split and load wait at T0 from measured loads (review F7). **Decided 2026-09-11:
  `load_wait_min: 20`** -- a pair on a node that stays loaded waits 20 min, then runs anyway with
  `gate.contended = true` and the load in the record. The point is not to lose a day waiting for a quiet
  moment that a shared node never gives; contended rows are flagged and excluded from the unflagged wall
  ratios, and the peptide numbers do not depend on the load. The **split is unchanged** (spock 24, data 11,
  ibminode05 14). Moving samples between queues is an edit of `samples.yaml` (keep `n_samples` at 49).
- Search walls are indicative with `search_workers: 2`; set 1 if they are to be reported.
- Keep other chains off the three nodes. G-V05 refuses a launch beside our own tools, and the load gate
  flags everything else.
- Add `harness/corpus.py` and `harness/CORPUS.md` to `.export-private` (they name the comparison tool
  and cluster paths); `samples.yaml` is already ignored. **Done**: `.export-private` excludes `harness/`
  whole, so `harness/review/` is covered too.
- Disk: phase 2 starts only after every pair of the queue has finished, so both mzMLs of every sample of
  that queue are on the node at once. Estimated peak from the diaTracer reference mzML sizes plus the
  largest staged `.d` and the phase-2 patched/fixed copies: spock ~573 GB, data ~507 GB, ibminode05
  ~127 GB, against 18.9 / 9.0 / 8.4 TB free on 2026-09-11.
- The Sage binary is the one every earlier table used (sha256 `d3820543a31bfa2a...`, the
  `sage-v0.14.7-x86_64-unknown-linux-gnu` tarball). `sage --version` on it prints **`sage 0.14.6`**: the
  tarball's CLI version string was not bumped. The rate-line rule of G-V10 was read from the 0.14.7 source
  and verified against this binary's own logs on data and ibminode05.
