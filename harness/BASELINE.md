# Baseline mode: `harness/baseline.py`

Extractors and DIA-NN on registered runs across a thread-count axis, one exclusive BinAC2 node per Slurm job: wall,
CPU, peak RSS, speedup and parallel efficiency per (sample, tool, threads), and identifications for each tool. The
harness rule applies here too: benchmark numbers come only from the harness. `corpus.py` is imported, not copied. The
following come from it unchanged: staging (`stage_tdf`, pins), `time -v` parsing, `syncfs` and pre-warm, the `/proc`
contention sampler, wall cap and memory floor (`run_capped`), the environment rule (`arm_env`/`strip_var`), the
command builders, `run_search` with its read checks, and the peptide rules. Nodes run stdlib Python. The exception
is pyarrow, which reads DIA-NN's `report.parquet`.

```
python3 harness/baseline.py selftest                                   # offline, fake tools; every guard fires
python3 harness/baseline.py dry-run   [--plan baseline_v1] [--sample S] [--cell C]   # sbatch scripts + commands
python3 harness/baseline.py preflight [--plan baseline_v1]             # read-only, on the cluster login node
python3 harness/baseline.py submit    [--plan baseline_v1] [--sample S] [--cell C]   # ssh <host> sbatch ...
python3 harness/baseline.py status    [--plan baseline_v1]             # squeue + record counts
python3 harness/baseline.py fetch     [--plan baseline_v1] --dest DIR  # scp <results>/records -> DIR/records
python3 harness/baseline.py table     [--plan baseline_v1] [--source remote|DIR] [--out PREFIX]   # PREFIX.json/.md
python3 harness/baseline.py submit-corpus --corpus-plan P [--plan baseline_v1] [--sample S] [--dry]
python3 harness/baseline.py corpus-table  --corpus-plan P [--plan baseline_v1] [--source remote|DIR] [--out F]
```

The laptop side needs PyYAML, the same requirement as for `corpus.py`; `/usr/bin/python3` has it. `selftest` needs
no YAML. Exit codes: `0` ok, `1` failed units in a job, `2` guard abort, `3` table incomplete.

## Plan (`harness/samples.yaml`, private, untracked)

| key | meaning |
|---|---|
| `cluster.host` | ssh alias of the login node (`binac2j`) |
| `cluster.partition`, `cluster.walltime` | `compute`, `[D-]H:MM:SS` (BinAC2's default walltime is 10 min, so this key is required) |
| `cluster.python` | python3 on the nodes; with a DIA-NN cell, one that has pyarrow (`/pfs/10/project/bw26g016/conda/envs/massivora/bin/python3`: 3.12, pyarrow 25) |
| `cluster.job_unit` | `sample`: one job per sample, every unit back to back on one node. `cell`: one job per (sample, cell, threads) |
| `cluster.cpus` (opt) | `--cpus-per-task` (128 = 64 physical cores with SMT) |
| `cluster.path` (opt) | directories put first on PATH in the job, e.g. a JDK >= 11 (BinAC2's system java is 1.8) |
| `cluster.sbatch_args` (opt) | extra `#SBATCH` lines, e.g. `--constraint=eth`. The flags the harness sets itself are refused |
| `results` | absolute cluster path (a workspace): `harness/<sha>/`, `jobs/` (spec, script, Slurm output), `records/`, `runs/` (logs) |
| `raw_map` (opt) | registry path prefix -> cluster prefix (`/ceph/...` -> `/pfs/10/work/...`); the longest matching prefix wins. The registry pins are checked on the cluster copy |
| `threads` | default thread axis, ascending, e.g. `[8, 16, 32, 64, 128]` |
| `repeats` | r >= 1 |
| `samples`, `n_samples` | sample ids (registry); the count must match |
| `search_db_sha256`, `tools` | as in corpus plans (Sage, MSFragger, patch, fix; database pins) |
| `engines` (opt) | `[sage]` or `[msfragger]` (default: both) |
| `cells` | `{name: {kind, search_at, threads?, wall_cap_h?, engines?, sage_config?, msfragger_params?, ...}}`, see below. `engines` is an ordered subset of the plan's engines; `sage_config`/`msfragger_params` replace the plan's config for that cell's searches (copied run-local; the databases they name must match the plan pins, G-V12) |

Cell kinds:
- `diaspextract`: `env` names an arm `env.sh` that exports `SPX_BIN`. Optional `args`; the harness sets `-in`, `-out` and `-threads`. Checks: `corpus.arm_env` (G-V03), provenance and label (`arm_meta`), `ldd_deps`.
- `diatracer`: `dir` and `jar`. The invocation is `corpus.cmd_dt` (`-t p`). The output is moved off the stage.
- `diann`: `bin` (DIA-NN 2.0), optional `env` (an env.sh sourced under the stripping rule; on BinAC2 it sets the `LD_LIBRARY_PATH` that DIA-NN needs for GLIBCXX_3.4.30). Each run makes one library-free call: `--f <staged .d> --fasta <sage_fasta> --fasta-search --predictor --gen-spec-lib`, plus the digest and settings of `/ceph/ibmi/abi/oliver/results/diann-bench-2.0` (K*,R*, 1 missed cleavage, length 7-30, charge 2-4, precursor m/z 350-1200, fragment m/z 200-1800, C carbamidomethyl, M excision, 0 variable modifications, mass accuracy 15/15 ppm, `--qvalue 0.01`, `--pg-level 1`, no MBR) and `--threads p`. The FASTA is the corpus's pinned target FASTA, the one Sage uses. The predicted library and temp files are deleted after each run; the report is kept.
- `cmd`: a generic tool (DIA-Umpire, DIA-MS2pep, Dear-DIA, ...). `exe` (absolute; hashed and watched), `cmd` (the timed command), optional `pre` and `post` (lists of commands run before and after the timed window, untimed: input adapters and the conversion of the tool's output into one mzML; each step's command, rc, wall and the sha256 of every absolute file it names are recorded; a failing step fails the unit, G-B04), `out` (a plain `*.mzML` name in the run dir), `input` (`d` or `mzml`, default `mzml`), optional `count` (a regex with one group for the tool's spectrum count) and `env`. Placeholders in all three: `{in} {out} {threads} {dir} {exe}` and `{cpulist}` (the first p CPUs of the job that are first hyperthread siblings: only for tools without a thread option, i.e. Dear-DIA under `taskset`; every other tool is unpinned). Together they must use `{in}`, `{out}` and `{threads}` (or `{cpulist}`). The searches read mzML, so `post` must leave one; Orbitrap-only tools need `.mzML` samples, whose registry pin is `{bytes, sha256}`.

## What a job does

`submit` copies `baseline.py` and `corpus.py` to `<results>/harness/<sha16>/` (named by content, so they are never
overwritten). It then writes one spec (`jobs/<name>.json`) and one script (`jobs/<name>.sbatch`) per job and runs
`sbatch` for each over ssh:

```
#SBATCH --partition=compute --nodes=1 --exclusive --mem=0 --time=<walltime> --cpus-per-task=128
exec <python> <results>/harness/<sha16>/baseline.py job --spec <results>/jobs/<name>.json
```

On the node (`job_main`):
1. `$TMPDIR` must exist and be node-local (BinAC2: `/scratch/<jobid>`, 453 GB, 2.5 GB/s), not under `/pfs`, `/home` or `/ceph` (G-B07). The root, lock and jnatmp are placed there. `cluster.path` is put first on PATH. `root/records` is a symlink to `<results>/records`, so every record is written atomically to Lustre as it happens and all jobs of a plan share one record set (resume across jobs).
2. Inside `node_run`: the corpus.py copy is checked against the hash it was resolved with. Every thread count must be within the CPUs the job may use (affinity). Then: `corpus.preflight` (python, GNU time, `/proc`, java, database pins), java >= 11 when diaTracer or MSFragger runs, `install_tools` (run-local copies, G-V12), and a resolve of each cell's tool.
3. Per sample, phase 1: stage once (`stage_tdf`: 0700, `analysis.tdf` + `analysis.tdf_bin`, pins checked on the raw and on the copy). Then every (cell, p, repeat) unit runs back to back. Before each unit: the load gate (with `load_wait_min = 0` it only records, because the node is exclusive), tool drift check, `syncfs`, pre-warm. During the unit: the `/proc` sampler (foreign CPU, MemAvailable) and `run_capped` (wall cap, memory floor). After it: drift check, `time -v` parse, exit check, output verification. The staged copy is deleted in `finally`.
4. Phase 2: searches run only after every timed unit of the job. For each mzML cell whose rep-0 `search_at` unit belongs to this job, `corpus.run_search` runs Sage (on a patched copy for diaTracer, recorded as tool `dt`) and MSFragger (after the fix). The mzML is deleted once both searches are ok.
5. At the end, even after SIGTERM from walltime or scancel: the root is copied to `<results>/runs` without stage, tools, tmp, `*.mzML`, `*.mzBIN*` or `*.speclib`.

**Order.** Repeat 0 runs the thread counts ascending, repeat 1 descending, and so on. At each thread step the cell
order flips, so that no tool always runs first. **Pinning:** none, meaning no taskset, numactl or `OMP_PLACES`; the
scheduler places threads. Records carry the logical CPUs, the job's affinity, the physical cores (distinct
`(physical id, core id)`), NUMA nodes, CPU model and Slurm job id. **Resume:** a unit is skipped when its record is ok
for the same tool sha256, `baseline.py` and `corpus.py`. The kept output of a `search_at` unit lives on the job's
`$TMPDIR` and is gone after the job, so if its searches are not done that unit runs again.

**Corpus pairing (`submit-corpus`).** A corpus.py plan becomes one exclusive job per sample. Its arm, diaTracer and
tools must use cluster paths; the baseline plan supplies `cluster`, `raw_map` and the results root
(`<results>/corpus-<plan>/`). The job runs `corpus.node_run` itself with root, lock and jnatmp in `$TMPDIR` and
`load_wait_min = 0`. Everything else is corpus semantics: alternating arm order, both arms back to back, phase-2
searches, measurement hashes, G-V01..G-V19. `corpus-table` renders corpus.py's own table (`render_table` /
`render_cells_table`, G-V13) from those records.

**`corpus-table` and `raw_map` (fixed 2026-11-01).** The corpus jobs get each sample's raw after the baseline plan's
`raw_map` (the BinAC2 `/pfs/...` copy), so a pair record stores sha256 of the mapped path, while corpus.py's G-V13
check in `table_guards` hashes the raw as written in samples.yaml (`/ceph/...`). Before the fix every plan with a
`raw_map` aborted (`pair HeLa_19: record pin or raw path differs from samples.yaml`). `corpus-table` now passes
corpus.py a copy of the registry with every sample raw mapped through the same `raw_map` (`mapped_registry`);
corpus.py itself (pinned by sha256) is unchanged. The guard keeps its meaning: a different raw file, or a raw under no
`raw_map` prefix, still hashes differently and aborts (selftest cases `corpus-table: ...`, G-V13).

## Metrics (per sample, cell, threads p; `table` -> JSON + Markdown)

| metric | definition |
|---|---|
| wall T(p) | median over repeats of GNU `time -v` elapsed; min/max and `spread = (max-min)/median` when r > 1 |
| CPU | user + sys from `time -v`; `cpu_util = (user+sys) / (wall * p)` (JVM tools can exceed 1: GC and JIT threads) |
| peak RSS | `time -v` maximum resident set size (median and max over repeats). GNU time reports the largest single process, not the sum over a process tree: for DIA-MS2pep (Perl forks under `bash -c`) it understates the footprint |
| speedup | `S(p) = T(p0) / T(p)`, where p0 is the smallest thread count on the cell's axis. If T(p0) is missing, S and E are left empty and never rebased |
| efficiency | `E(p) = T(p0)*p0 / (T(p)*p)`, per thread |
| physical efficiency | `E_phys(p) = T(p0)*min(p0,P) / (T(p)*min(p,P))`, with P physical cores. `smt = p > P` (on BinAC2 p=128 is SMT, P=64) |
| load | 1-min load before and after each unit, foreign-CPU mean and 60-s peak during it, MemAvailable minimum. `contended` (G-V06, a flag, not a failure). On a fresh exclusive node the 1-min load average still carries the previous job's load for a minute or two, so a gate flag on the first unit of a job is usually that; `during.foreign_cores_peak60` is the real check |
| spectra | `spectrumList count` of the `search_at` output (rep 0) |
| Sage / MSFragger peptides | corpus rules (CORPUS.md "Peptide counts"): Sage distinct `peptide` at `peptide_q <= 0.01` (target+decoy; `sage_target_peptides` beside it); MSFragger target-decoy walk at 1% |
| DIA-NN | precursors = distinct `Precursor.Id` with `Q.Value <= 0.01` and `Lib.Q.Value <= 0.01` (rows with `Decoy != 0` dropped). Peptides = distinct `Stripped.Sequence` of those. Protein groups = distinct `Protein.Group` of those with `PG.Q.Value <= 0.01`. DIA-NN's own `report.stats.tsv` counts are recorded as diagnostics. Counted at every p; the table reports the `search_at` run and the precursor range over all runs |
| per tool | over samples that have every p: the sum of T(p), with S, E and E_phys of those sums, plus identification sums |

DIA-NN's wall covers the whole pipeline (library prediction plus search). An extractor's wall covers extraction
only, without its searches. Do not compare the two walls directly.

## Guards

baseline.py raises its own guards, G-B01 to G-B07, and reuses corpus ids with their meaning in CORPUS.md: G-V02 pin,
G-V03 arm, G-V06 contention flag, G-V07 staging, G-V08 run result, G-V10 search, G-V12 tools/databases, G-V14
retention, G-V15 node environment. `selftest` fails unless all of G-B01..07 and G-V02/03/06/08/10/12/14 fire.

| id | level | refuses |
|---|---|---|
| G-B01 | plan/job | unknown or missing key; a bad cluster section (job_unit, walltime, harness-owned sbatch flags); a bad cell (kind, keys, relative path, reserved name, args that set harness flags, a cmd template without `{in}/{out}/{threads}`, an out that is not a plain mzML name, a count regex without one group); a thread axis that is not ascending, distinct and positive; `search_at` off the axis; repeats < 1; more than one diatracer cell; a sample unknown, listed twice, sharing a raw path, without a reading cell, or outside `raw_map`; n_samples mismatch. At job start: p above the job's CPUs, or the corpus.py copy differs |
| G-B02 | job | a tool binary, jar or Bruker library missing or not executable; a cmd env.sh that fails or exports a stripped variable; java < 11 when diaTracer or MSFragger runs; preflight: no pyarrow for a DIA-NN cell |
| G-B03 | job | a file of the cell's tool changed across a unit (size or mtime of the binary, `lib/**`, resolved libraries, jar, `ext/bruker`, the DIA-NN directory, java) |
| G-B04 | unit | DIA-NN report missing, stale, lacking columns, or 0 precursors; a cmd count line missing or different from the spectrumList count |
| G-B05 | unit | wall cap passed, or available memory under 5% for 3 samples: the tool's session is killed |
| G-B06 | table | one cell with two tool builds; mixed baseline/corpus code; one sample on two CPU models or core counts (`job_unit: cell` spreads a sample over nodes of one type, which is allowed); an ok record with wall, RSS or spectra <= 0 |
| G-B07 | job | `$TMPDIR` unset, missing or not node-local; results not absolute |

A unit-level failure writes a `failed` record with the guard and the job continues with the next unit; the table
prints the unit as missing and exits 3. A job-level abort stops the job (`QUEUE_ABORTED` in its Slurm output).

## Records

`<results>/records/`:
- `<id>.<cell>.p<p>.r<rep>.json` (`kind: baseline_run`): sample (raw as sha256), cell, tool (sha256, label, provenance, deps, java), threads, rep, seq, node facts, gate, during, cmd, wall/RSS/CPU, output or DIA-NN counts, status/guard.
- `<id>.stage.json`: staging.
- `<id>.<cell|dt>.<engine>.json`: corpus.py search records.

Writes are atomic. `table` reads them on the login node (`--source remote`), or from a `fetch`ed copy
(`--source DIR`). The JSON is meant to feed a dashboard: `cells`, `rows[]` (one per sample and cell, with `ids` and
`scaling[]` per p) and `per_tool`.

## BinAC2 plans (2026-11-01)

Kit: `/pfs/10/project/bw26g016/diaspx-bench` (its README). `results/baseline-kit/` holds `mgf_to_mzml.py` (stdlib; MGF
blocks -> MS2 mzML spectra: PEPMASS -> selected ion and isolation target, CHARGE when present, RTINSECONDS (negative ->
0), zero-intensity peaks dropped, 64-bit zlib), `sage_orbi.json` / `msfragger_orbi.params` (the kit configs with 20 ppm
precursor and fragment tolerance), `msfragger_ms2pep.params` (precursor +-100 Da, isotope error 0, charge 2-4: DIA-MS2pep
writes the isolation-window centre as PEPMASS and no charge, so it is searched MSFragger-only with a wide window) and
`diann-2.0.env.sh`. Every plan requests `--constraint=ib` (the IB nodes are uniform: 128 CPUs, 511 GB; the eth set mixes
96-CPU and 2 TB nodes).

| plan | what | jobs |
|---|---|---|
| `corpus171` | DIA-NN library-free, 64 threads, the 43 public samples; also supplies cluster/raw_map/results for `submit-corpus --corpus-plan corpus171_rc160` (DIAspeXtract rev171-18d15e3 vs diaTracer at 64 threads, Sage + MSFragger + entrapment; IBMI corpus runs used 100 threads) | 43 + 43 |
| `scaling171` | HeLa_22, HeLa_34 x {DIAspeXtract rev171-18d15e3, diaTracer, DIA-NN} x p in {8, 16, 32, 64, 128}, r = 2, `job_unit: cell`, searches at 64 (MP_K562_N_9905 is not on BinAC2) | 30 |
| `orbi171` | DIA-Umpire, DIA-MS2pep, Dear-DIA on the 3 Orbitrap runs at 32 threads | 3 |
| `orbi171_scale` | the same tools on PXD032263, p in {8, 16, 32, 64}, `job_unit: cell` | 12 |

Results: `<kit>/results/<plan>/` (corpus pairs: `results/corpus171/corpus-corpus171_rc160/`). Records carry the harness
sha256; the table refuses records of two harness versions in one plan, so baseline.py must not change while a plan runs.
