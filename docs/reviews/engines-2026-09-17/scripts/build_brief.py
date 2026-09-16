#!/usr/bin/env python3
"""Self-contained review brief for the `engines` harness commit (kimi + vibe have no shell headless)."""
import inspect, subprocess, sys
from pathlib import Path

DEV = Path("/Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract")
sha = sys.argv[1]
out = Path(sys.argv[2])
show = subprocess.run(["git", "-C", str(DEV), "show", "--stat", "--patch", sha, "--", "harness/corpus.py", "harness/README.md"],
                      capture_output=True, text=True, check=True).stdout
md = subprocess.run(["git", "-C", str(DEV), "show", sha, "--", "harness/CORPUS.md"], capture_output=True, text=True, check=True).stdout
sys.path.insert(0, str(DEV / "harness"))
import corpus  # noqa: E402

ctx = [corpus.cells, corpus.extended, corpus.q_tools, corpus.q_engines, corpus.plan_tool_keys, corpus.db_keys,
       corpus.run_group, corpus.search_done, corpus.pair_done, corpus.ready_arms, corpus.rescore, corpus.sweep_outputs,
       corpus._node_run, corpus.load_plan, corpus.check_extended, corpus.resolve_queue, corpus.cmd_status,
       corpus.table_guards, corpus.render_table, corpus.render_cells_table]
src = "\n\n".join(inspect.getsource(f) for f in ctx)
plan = """dwv_pxd029836:
  arm: v1.3.0
  spx_root: /ceph/ibmi/abi/oliver/spextract
  diatracer_dir: /ceph/ibmi/abi/oliver/spextract/diatracer
  diatracer_jar: diaTracer-2.2.1.jar
  jnatmp: /scratch/kohlbach/jnatmp
  scratch_root: /scratch/kohlbach/dwv_pxd029836
  results_ceph: /ceph/ibmi/abi/oliver/spextract/corpus_v3_dwv_pxd029836
  report: harness/dwv-pxd029836.md
  threads: 100
  load_wait_min: 20
  n_samples: 3
  search_db_sha256: {sage_fasta: 29e2a2f5..., msfragger_db: 4fa1ea7e...}
  tools: {sage, sage_config, msfragger_jar, msfragger_params, patch, fix: as corpus_v3; digest: semantic_digest.py}
  engines: [sage]
  cells:
    dwv_default: {kind: dwv, arm: diaweaver-7ed1169, args: [], wall_cap_h: 16}
  queues:
    ibminode05: {search_workers: 1, samples: [pxd_1418, pxd_1420, pxd_1422]}
"""
brief = f"""# Adversarial review: `engines` plan option in the benchmark harness (commit {sha[:12]})

**Review only. Do not modify any file. Do not run any shell command: everything you need is inline below.**
If something is fine, say so briefly rather than padding.

## Context

`harness/corpus.py` is the ONLY benchmarking entry point of a private proteomics project (pseudo-MS/MS extraction
from timsTOF diaPASEF data). It runs per-node queues: phase 1 runs the extractors back to back under GNU `time -v`
(diaTracer `dt`, DIAspeXtract `spx`, and for "extended" plans extra `cells` such as diaWeaver), phase 2 searches
every output with the engines (Sage, MSFragger) and counts peptides. Records (JSON) are the only source of truth for
`status` and `table`. Every guard is named (G-V01..G-V19), aborts rather than warns, and is exercised by `selftest`.

This commit adds an optional plan key `engines` (a subset of `("sage", "msfragger")`, e.g. `[sage]`) so that a plan can
run Sage only. The user asked for: diaTracer / DIAspeXtract / diaWeaver on three public PXD029836 HeLa files, Sage
only, with runtime and RSS. The plan it will run is:

```yaml
{plan}```

It also normalises one comparison in `table_guards` (a group record of a plan without cells stores `cells: {{}}`; the
plan dict has no `cells` key, so `p.get("cells") != plan.get("cells")` was `{{}} != None` and refused every table of
an extended plan without cells).

## Invariants the change must keep (attack these)

1. **Existing plans unchanged.** The measured functions (the `MEASURED` / `MEASURED_CELLS` tuples, hashed with
   `inspect.getsource`) must not change: pair/search/score hashes stay 3215b73e/064af71b/4fe0a1ce and the cells hash
   stays c586f871. A queue of plan `dwv_stage1` (two diaWeaver cells, entrapment, both engines) is RUNNING right now
   on another node with the previous harness; this harness will later run `status`, `collect` and `table` on its
   records, and a relaunch must adopt its verified records. Plain plans (no `cells`/`entrapment`/`engines`) must
   render the same tables and dry-runs byte for byte.
2. **A Sage-only plan never runs MSFragger**, never waits on it, never counts it, never prints a number for it, and
   still deletes each output once its (only) engine succeeded, and resumes without re-running anything.
3. **No silent wrong number**: a table must refuse mixed or stale records rather than render them.
4. The MSFragger jar/params and the `msfragger_db` pin stay required and checked for every plan (deliberate: same
   pins as the reference corpus), even when MSFragger does not run.

## Questions (answer each; give file:line or function name and a concrete failing input)

1. Is there any code path where a plan with `engines: [sage]` still runs, waits for, requires or counts MSFragger
   (phase 2 unit loop, `pending`, `ready_arms`, `pair_done`, `sweep_outputs`, `rescore`, `add_split`, `status`,
   `table`, `dry_run`)?
2. Can the change alter anything for a plan WITHOUT `engines` (plain `corpus_v3`, or `dwv_stage1`)? Look especially at
   `table_guards` (it is shared with the plain `render_table`), the `or {{}}` normalisation, and the new G-V13 engine
   check (`q_engines(plan)` vs the records' engines, including `entrap`).
3. `extended()` now returns True when `engines` is present. Does any caller of `extended()` misbehave for a plan
   that has `engines` but no `cells` and no `entrapment` (the group runner with an empty cell list, `noop_check`,
   `render_cells_table`, `guardtest`)?
4. Resume/staleness: plan run with both engines, then narrowed to `[sage]` (or widened back). What happens to the
   records, the mzML outputs (deleted once all *configured* engines succeeded), `status`, and `table`? Is any outcome
   a silently wrong or missing number rather than a refusal or a re-run?
5. Is the G-V01 validation complete (`[e for e in ENGINES if e in eng] != eng`)? Any value that passes and breaks
   later (YAML oddities: booleans, nested lists, `engines: [Sage]`)?
6. The summary rows of `render_cells_table`: `sm(...)` returns None for an engine the plan does not run; `num(None)`
   and `ratio2(None, None)` print `-`. Any case where a real total of 0 or a missing engine is confused?
7. Anything else that would bite on real data (3 x 120-min files, one 16-h-capped diaWeaver cell each), ranked by
   severity (HIGH / MEDIUM / LOW), and whether it would actually bite or is theoretical.

## The commit (corpus.py and README.md)

```diff
{show}```

## The commit (CORPUS.md)

```diff
{md}```

## Unchanged context: the functions the change interacts with (as committed)

```python
{src}
```

## Verification already done (so you can focus on what it does not cover)

- selftest 284/284 (258 before), including: G-V01 refusals (string, empty, unknown, repeat, order, `entrap`, null);
  a Sage-only extended queue (one cell, no entrapment, 2 samples) end to end with resume; its table, and refusals of an
  MSFragger or entrapment record in it; its dry-run; an engines-only plan without cells (queue + table).
- A mutation proof: each new check broken alone in a copy makes that copy's selftest fail.
- A differential proof: old and new harness render byte-identical tables (plain, extended with 2 cells + entrapment,
  1 cell with entrapment off, a partial table with pending rows) and dry-runs; `dry-run --local` of the real plans
  corpus_v3 (3 nodes), corpus_v3_selftest_v130 and dwv_stage1 is byte-identical; measurement hashes unchanged.

Output format: a numbered list of findings, each with severity, location, a concrete failing input, and "bites on
real data: yes/no/theoretical". Then one line per question above if it had no finding.
"""
out.write_text(brief)
print(out, len(brief), "bytes")
