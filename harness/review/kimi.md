• Review of `harness/corpus.py` (sha `7ab160cd...`), `CORPUS.md`, `samples.yaml`, the ported historical tools, and both cluster proofs. No tools were run; everything below is from the inline material.

  ---

  ### 1. Mid-pair load contention never reaches the table — a contended wall renders with flag `-`
  - severity: high
  - location: corpus.py:377-388 `load_gate`, corpus.py:494 (`load_after`/`memavail_after_kb` recorded but unused), corpus.py:1429-1431 (`flag` renders only the gate)
  - failure scenario: the gate passes on spock at load 5; ten minutes into the diaTracer arm another user's `diamond` job (observed 2026-09-10/11 at ~5,400% CPU, loads swinging 57-112 within hours) starts and runs through both arms. The pair's walls are inflated, `gate.contended` is `False`, and the row renders `load flags: -`. The record's own `load_after`/`ps_top` prove the contention, but nothing surfaces them: the table — the reported artifact — presents the number as uncontended. With n=1 and per-row walls as the headline comparison, that row's wall and wall-ratio are wrong-looking with no visible signal.
  - evidence: `"contended": load > lmax or bool(b)` is computed once, before the pre-warm; `rec.update(end=..., load_after=load1(), ...)` is stored per arm and never read by `render_table`, whose flag is built solely from `(p or {}).get("gate")`.
  - fix: in `render_table`, flag a row contended when any arm's `load_before`/`load_after` exceeds `gate.load_max` (or `ps_top` shows a foreign process above some CPU floor), and print e.g. `contended during arms (load 84.1)`; better, also re-check `busy()`/load between the two arms and store it in the record.
  - confidence: high

  ### 2. Resume and table identity ignore `harness_sha256` — a mid-run harness fix silently mixes two scoring/verification rules in one table
  - severity: high
  - location: corpus.py:567-569 `search_done`, corpus.py:572-589 `pair_done`, corpus.py:1385-1388 (G-V13 uniformity checks), corpus.py:518 (`harness_sha256` written into every record but never compared)
  - failure scenario: the peptide scorers (`sage_peptides`, `msf_peptides`), the output verifier and the count-equality check all live in `corpus.py` itself. A bug is found in one of them mid-run (this project changed the harness twice within 24 h during the proofs), the file is edited, and the queue is relaunched. `pair_done`/`search_done` compare binary/lib/jar sha, pin, pair_run and `tools_sha256` — none of which change — so cells produced under the old rule are adopted as fresh, and the table mixes two rules with no guard. G-V13 checks build and tools uniformity, not harness uniformity. This already happened in the proof: the record at 5.4 carries `"harness_sha256": "f24d0a69..."` and the 00:16 relaunch logged `harness 7ab160cdaf15bce6` then `pair HeLa_2740 already done (record verified): skipped`.
  - evidence: `rec.get("identity") != ident0` and `rec.get("tools_sha256") == tools_sha` are the only identity comparisons; `harness_sha256` appears only in records and the `QUEUE_START` line.
  - fix: add a G-V13 check `len({r["harness_sha256"] for r in records_used}) > 1 -> abort`, and document that any harness edit requires invalidating records (or include `harness_sha256` in `pair_done`/`search_done`, accepting full re-runs on harness edits).
  - confidence: high

  ### 3. If the "first MSFragger alone" unit fails, the thread pool can still race the `.pepindex` build
  - severity: medium
  - location: corpus.py:765-770 (`first = next(...); failed += unit(first); ex.map(unit, [u for u in units if u is not first])`)
  - failure scenario: the first unit with a pending MSFragger search runs alone so the `.pepindex` beside `/scratch/kohlbach/bench/human_decoy.fasta` is built once (P7). If that unit's fix step or engine fails before/during index build (bad mzML, OOM at `-Xmx200G` under another user's load), `unit(first)` returns with the MSFragger cell failed, and the pool immediately starts the remaining units — two of which can be first-ever MSFragger runs building the same index concurrently. Best case: loud `G-V10` failures; worst case: a torn index that searches successfully and returns silently wrong peptide counts for every later cell on that node (records would look `ok`, `tools_sha256` uniform, G-V13 blind).
  - evidence: there is no check that a MSFragger search has ever succeeded (or that the index exists) before `ex.map` starts; `first` is chosen by `pending(...)` only.
  - fix: after `unit(first)`, if its msfragger cell did not end `ok`, take the *next* unit with a pending msfragger and run it alone, repeating until one succeeds or none remain; or treat a failed first MSFragger as a queue abort. Additionally assert the `.pepindex` files exist and are non-empty before entering the pool.
  - confidence: medium

  ### 4. Environment hygiene stops at four prefixes — malloc tunables, OpenMP and JVM option variables are neither stripped nor guarded
  - severity: medium
  - location: corpus.py:60 `STRIP_PREFIX`, corpus.py:269-270 `strip_var`, corpus.py:293 (`env.update(LC_ALL="C", TMPDIR=...)` only), corpus.py:519 (`env_keys` records names only)
  - failure scenario: `strip_var` removes `SPEXTRACTOR_*`, `DIASPEXTRACTOR_*`, `MALLOC_*` and `LD_PRELOAD`, but not `GLIBC_TUNABLES` (e.g. `glibc.malloc.arena_max` — the same class of knob as `MALLOC_ARENA_MAX`), `OMP_NUM_THREADS`/`GOMP_CPU_AFFINITY`/`KMP_*` (the extractor's window loop is OpenMP; per R8 counts are not digest-reproducible across thread counts, so an OMP cap on one node silently changes peptide counts, not just walls), and `_JAVA_OPTIONS`/`JAVA_TOOL_OPTIONS`/`JDK_JAVA_OPTIONS` (apply to both diaTracer and MSFragger). The caller's `LD_LIBRARY_PATH` is also inherited (only prepended-to by env.sh). 5.6 verified a clean non-interactive env on spock only; ibminode05 — which "runs other gates" — was not checked. Any of these set on one node makes that node's rows silently different; `env_keys` would show the name in the record but nothing aborts and the table never displays it.
  - evidence: `removed = sorted(k for k in os.environ if strip_var(k))` — the selftest's `QUEUE_START ... removed ['DIASPEXTRACTOR_PROBE', 'LD_PRELOAD', 'MALLOC_ARENA_MAX', 'SPEXTRACTOR_PROBE']` shows exactly what is covered.
  - fix: extend the strip (or, safer, abort-and-list) set to `GLIBC_TUNABLES`, `OMP_*`, `GOMP_*`, `KMP_*`, `_JAVA_OPTIONS`, `JAVA_TOOL_OPTIONS`, `JDK_JAVA_OPTIONS`, and drop the inherited `LD_LIBRARY_PATH` before sourcing env.sh; print the surviving list in `QUEUE_START`.
  - confidence: medium (the hole is certain; whether anything sets these on ibminode05 is unverified)

  ### 5. No node preflight: ibminode05's GNU time, python version, default JVM and FASTA equality are unverified, and the guards that do exist fire only after the 20 h run
  - severity: medium
  - location: corpus.py:57 (`TIME = "/usr/bin/time"` — G-V15 never checks it), corpus.py:772 (`ex.shutdown(wait=True, cancel_futures=True)` — `cancel_futures` needs Python ≥ 3.9), corpus.py:440/462 (bare `java` from PATH; version never recorded), corpus.py:347-358 + 1387-1388 (node-local FASTAs hashed per node; cross-node mismatch aborts only in `render_table`)
  - failure scenario (several, one node): 5.6 verified GNU time, Python 3.12.3, OpenJDK 21 and FASTA sha256 only on data and spock. On ibminode05: (a) a missing/non-GNU `/usr/bin/time` fails all 14 pairs with G-V08 after each has staged GBs — visible, but wasteful; (b) Python 3.8 would crash at `ex.shutdown` *after* all pairs and searches, leaving no `QUEUE_DONE` and no `QUEUE_ABORTED` (only an Abort prints that) — a "finished" queue with no marker; (c) the notes say "ibminode05 also has java-11" and the harness invokes bare `java` — if the default is 11, diaTracer and MSFragger run on a different JVM than the other nodes and the records contain nothing (`cmd`, `env_keys` don't capture it) to explain the difference; (d) if ibminode05's `human_decoy.fasta` differs by one byte, every search record from it has a different `tools_sha256`, and G-V13 aborts the *entire table* after the run — fixing it forces redoing searches under a unified database.
  - evidence: "ibminode05 was not queried (it runs other gates)" / "Not checked on ibminode05" (5.6); `node_main` catches only `Abort` (corpus.py:892-897).
  - fix: a preflight in `launch` (or a `preflight` subcommand run per node before T0): assert GNU time, `sys.version_info >= (3,9)`, capture `java -version` into the pair/search records, and compare `sage_fasta`/`msfragger_db` sha256 across the three nodes (or against a pin in the plan).
  - confidence: medium

  ### 6. G-V04 identity hashes only the binary, `arm/lib/*` top level and the jar — libraries resolved via `$SPX/lib` and the OpenDIAlyzer conda env on `LD_LIBRARY_PATH` are unhashed
  - severity: medium
  - location: corpus.py:297-301 `identity()`, corpus.py:304-307 `check_identity`; the arm's env chain (section 6: root `env.sh` exports `LD_LIBRARY_PATH=$SPX/lib:/ceph/ibmi/abi/oliver/AI/OpenDIAlyzer/opt/env/lib:...`; the proof record's `ld_library_path` shows all three)
  - failure scenario: the v3 binary resolves some dependency outside `arm/lib` (anything not shipped in the arm falls through to `spextract/lib` or the conda env). R13 says `sync_cluster.sh` and other gate work run on these trees tonight. A between-arms overwrite of such a library changes the measured build with no guard firing: `identity()` never hashes it, G-V04 compares only arm-local files, and G-V13 sees one `identity` throughout. (A *during*-arm overwrite SIGBUSes and is caught by G-V08's signal check; the between-arms swap is the silent case.) `identity()` also globs only top-level files, so libs in `arm/lib` subdirectories escape as well.
  - evidence: `"lib_sha256": {p.name: sha256(p) for p in sorted(lib.glob("*")) if p.is_file()}` with `lib = <spx_root>/<arm>/lib`.
  - fix: build the identity from the resolved dependency set — run `ldd $SPX_BIN` under the arm env (plus any dlopened Bruker SDK, if its location is known) and hash every resolved path, recursively for `arm/lib`.
  - confidence: medium

  ### 7. Arm-order writeback asymmetry biases within-row wall ratios
  - severity: low
  - location: corpus.py:492-500 (`run_arm` timing), corpus.py:516 (order alternation); 5.6 (`vm.dirty_ratio 20`, `vm.dirty_expire_centisecs 3000` on a 2,267 GB node)
  - failure scenario: with `dirty_ratio` 20, the kernel can hold hundreds of GB dirty; after the diaTracer arm, up to ~25 GB (TNBC) of freshly written mzML is flushing to disk while the *next* arm is being timed. On dt-first rows the spx wall absorbs that writeback; on spx-first rows the dt wall absorbs writeback of a much smaller file. Within-row wall ratio — the headline per-row number, n=1 — is systematically biased upward on dt-first rows and less so on spx-first rows. Alternation cancels it only in the median across rows, not per row.
  - evidence: dt mzML 18-25 GB for TNBC (P6), spx mzML ~0.65 GB in the proof; no `sync`/fadvise between arms.
  - fix: run `sync -f <run dir>` (or `posix_fadvise(DONTNEED)` on the first arm's output) after each arm, before starting the next; seconds at most.
  - confidence: medium

  ### 8. `acq_min` is never verified at run time — a bad registry value lands in the table silently
  - severity: low
  - location: corpus.py:255-257 (`with_acq` computed only when asked), corpus.py:857-864 (used only by the `pin` subcommand), corpus.py:411/423 (`stage()` fingerprints without acq), corpus.py:1433 (table prints `e["acq_min"]` from samples.yaml)
  - failure scenario: the pin covers tdf sizes, acquisition datetime and serial, but not acquisition length; a paste/transcription error when moving `corpus.py pin` output into samples.yaml (49 rows, done by hand) puts a wrong `acq min` in the reported table with no guard anywhere.
  - evidence: `fp["acq_min"]` is computed only under `with_acq=True`, which only `node_pin` passes.
  - fix: in `stage()`, compute the fingerprint with `with_acq=True` once and G-V02-compare `acq_min` against the registry value (sqlite is already open for the pin).
  - confidence: high (that it is unguarded)

  ### 9. Specimen-identifying paths are copied into the ceph results tree
  - severity: low
  - location: corpus.py:490 (`rec.update(..., cmd=argv, ...)` — the staged path embeds the raw basename), corpus.py:517 (`"sample": s` includes `raw`), corpus.py:874-876 `node_collect` (copies records, logs and `queue-*.json`; ignores only `stage/tools/*.mzML/*.mzBIN/*.tmp*`; no permission handling on the destination)
  - failure scenario: for INH_A-F, every pair record's `cmd` arrays contain `/scratch/.../stage/<id>-<pair_run>/<inhouse-specimen-X>.d`, `sample.raw` contains the cohort path, and dt/e/sage/engine logs echo the same paths. `collect` copies all of it to `/ceph/ibmi/abi/oliver/spextract/corpus_v3/<node>/`, whose readability by other cluster users is not established in the brief (the node-local side is 0700 under a `drwx------` home; the ceph side inherits copytree/umask defaults). The *table* is clean (labels A-F per R12), but the exported-evidence tree carries patient-specimen identifiers.
  - evidence: the proof pair record at 5.4 shows `cmd` and `sample.raw` verbatim (public file there; same shape for in-house).
  - fix: `chmod -R go-rwx` (or copy with a 077 umask) the ceph destination in `node_collect`; drop `sample.raw` from the record (the pin is the identity) or store only its basename hash; optionally stage the copy under a neutral `<id>.d` name so paths in logs/cmds carry no specimen id.
  - confidence: medium

  ---

  Notes on two things I checked and am *not* reporting as findings:

  - **Sage counting vs the historical awk.** The ported `sage_peptides` matches `bench_table.py` (the producer of TNBC-TABLE) exactly: `rank == "1"`, `peptide_q <= 0.01`, unique peptides, decoys included. The drivers' awk (`$8==1 && $38<=0.01`) is actually `label == 1` with *no* rank filter (rank is column 7) — a third, different rule; the decision explicitly chose the table producer's scorer, and the decoy inclusion is documented with `diag_decoy_peptides_in_set` recorded. Consistent with the stated source.
  - **MSFragger counting.** `msf_peptides` is line-for-line `msf_peps`: same key (`peptide`, `modification_info` or `assigned_modifications`), same decoy rule (every `[,;@]`-split protein starts with `rev_`; empty → decoy), same tie order (`sorted(values, reverse=True)` puts decoys first), same deepest-prefix walk. Correct port.

  ### Checklist of categories examined and found clean

  1. **Wrong pairing** — sample identity pinned at G-V02 and re-checked at G-V11/G-V13 (record pin and raw vs registry); searches bound to pairs by `pair_run`; node taken from the record's hostname with G-V13 verifying all arms ran on it; label from `--help`, jar label from the plan; ratio direction ours/diaTracer consistent in rows and summaries. Clean apart from findings 2 and 8.
  2. **Skipped/duplicated arms** — G-V09 is structural (sequential `for tool in order`, Abort in arm 1 skips arm 2; no `&&`/`||`); order alternation is by `enumerate` over the full queue, so it is stable across resumes; failed cells re-run on relaunch; no cell is silently dropped (abort → `pending`/FAILED, exit 3). Clean apart from finding 3.
  3. **Stale outputs/records** — output freshness via size+mtime equality and mtime > arm start; searches require current `pair_run` + `tools_sha256`; GT0 proved adoption/refusal on a real node. Clean apart from finding 2 (harness version).
  4. **Peptide counting** — both scorers verified line-for-line against `bench_table.py` (see notes above); 0-count → failed cell, never a table zero; header-name column resolution; TSV column guards present.
  5. **Units** — `h:mm:ss`/`m:ss` parsing handles both shapes; RSS `kB/1e6` is the decided convention and is labelled in the table; `hms` formatting unbounded in hours; totals/medians/ratios arithmetically consistent.
  6. **RSS/wall attribution** — `time -v` wraps the tool directly; staging, pre-warm, identity hashing and patch/fix steps are outside the timed windows (search wall = engine step, documented as indicative). Clean apart from findings 1 and 7.
  7. **Load contamination** — gate waits and flags, flag reaches the row, proof shows it firing; searches are ungated by design (walls indicative). Clean apart from finding 1 (mid-pair spikes).
  8. **Deletion/retention** — stage deleted in `finally` including SIGTERM/KILLED paths; mzML unlinked only after both engines succeed; the superseded-attempt glob `runs/<id>/*/*/*.mzML` is depth-correct and cannot touch search dirs; collect excludes stage/tools/mzML/mzBIN/tmp and refuses to run under a held lock; guardtest cleanup verified on the node.
  9. **Patient data** — 0700 roots, `drwx------` scratch, staged raw never outlives its pair, table uses A-F labels. Clean apart from finding 9 (identifiers in collected records/logs).
  10. **Guards/environment** — abort-vs-flag semantics verified by 85 offline + 37 on-node cases; the fake world's GNU-time signal behavior and cwd-relative Bruker lib are faithful; guards fire through fixtures, not branches. Clean apart from findings 4, 5, 6.
  11. **Launch/wait/collect/table** — content-named harness copy, detached single-command launch, shared-lock probes, wait-by-reinvocation, table aborts on mixed builds/tools, exit 3 on incomplete, FAILED never renders as a number, `QUEUE_DONE failed N` counts engine cells. Clean apart from finding 2.

