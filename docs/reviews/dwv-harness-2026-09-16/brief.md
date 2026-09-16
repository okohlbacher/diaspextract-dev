# Adversarial review: diaWeaver cells in the benchmark harness (corpus.py), before it produces numbers

Review only. Do not modify any file and do not run any shell command: everything you need is inline below.
If something is fine, say so briefly rather than padding.

## Scope

Repository: a private benchmark harness for pseudo-MS/MS extractors from Bruker timsTOF diaPASEF data.
HEAD is `a716b5c` (two commits on top of `0a1bb0d`: `ba91ac0` and `a716b5c`); only `harness/corpus.py`,
`harness/CORPUS.md` and `harness/README.md` changed. The full `harness/corpus.py` diff is inline at the end, followed
by the unchanged functions the new code calls.

`harness/corpus.py` is the only allowed benchmarking entry point. It runs, per sample, a timed "pair": diaTracer 2.2.1
(`dt`, closed Java jar) and DIAspeXtract 1.3.0 (`spx`, our C++ tool), on one staged copy of the raw `.d` directory,
then searches every output with Sage 0.14.7 and MSFragger 4.4.1 and renders a markdown table. Every failure mode it
has hit is a named guard G-V01..G-V15 that aborts (never warns); `selftest` fires every guard against fake tools.

The change adds an optional "extended plan": extra extractor "cells" (kind `dwv` = diaWeaver, an OpenMS fork tool)
run after the pair on the same staged copy, a re-encode of each cell's output with the fork's own
`FileFilter -sort`, a no-op flag between two cells, an entrapment search, and a per-charge split of the peptide
counts. New guards G-V16..G-V19. The first real run will be one patient-derived 31-min diaPASEF file ("dataset D"),
with two diaWeaver cells capped at 12 h each, on a shared 224-core node. It will take up to ~26 h, so a defect
found after the run costs a day.

## Facts about the tools (verified by reading the fork source at 7ed1169 and by building it)

- diaWeaver writes ONE `<out>/pseudo_spectra.mzML`. It streams spectra to that path, logs
  `Finished processing all windows. Wrote N pseudo spectra.`, then (if N > 0) reloads the file with a default
  `MzMLFile` (which sorts each peak list by m/z on load in this fork), `sortSpectra(false)` (RT only, std::sort,
  unstable), renumbers native ids `scan=1..n`, and stores it again at the same path with MS-Numpress: m/z linear
  (+zlib, MS:1002746), intensity slof (+zlib, MS:1002748), float data arrays slof (+zlib); an array whose numpress
  round-trip error exceeds 1e-4 falls back to plain zlib (MS:1000574). Then it logs
  `Done. Output (numpress compressed): <path>`. If N == 0 it logs a warning and returns 0 without the Done line.
  Each spectrum carries MS:1000827 (isolation target, with window offsets), MS:1000744, MS:1000041 (z = 2..4 only),
  MS:1002815 (1/K0; 0 on the default .d path), and per-peak float arrays `fragment_trace_id`,
  `fragment_window_id`. Precursors with z = 1 are never produced; every spectrum has >= 30 peaks.
- Sage 0.14.x treats MS:1002746 as unknown and drops the m/z array, so the output must be re-encoded before Sage.
- The fork's FileFilter: `-sort` = `sortSpectra(true)` (spectra by RT, each peak list by m/z with its data
  arrays); numpress defaults to none, zlib to false, m/z precision 64 bit; FileFilter always removes empty spectra.
- OpenMS writes each cvParam on its own line and each `<binary>...</binary>` on one line.
- diaTracer's mzML lacks MS:1000744, so Sage needs `patch_diatracer_precursor.py` first; MSFragger needs
  `fix_mzml_cvparams.py` on OpenMS-written mzML (valueless cvParams).
- Records and the table must never carry raw paths or specimen ids; the staged copy is patient data and must be
  in a 0700 directory, contain only what the tools need, and be deleted on success, failure and SIGTERM.

## The corpus-v3 counting rules (must be identical for every arm)

- Sage peptides: distinct `peptide` with `rank == 1` and `peptide_q <= 0.01`, target AND decoy rows counted
  (target-only reported beside it).
- MSFragger peptides: best hyperscore per (peptide, modification_info), sorted descending, deepest prefix with
  decoy/target <= 1%, count targets.
- The per-charge split must put each counted peptide in exactly one stratum (z1 or z2p) and sum to the count.
- Entrapment: `bench/entrapment.py score()` (inline below) on the Sage entrapment search; strata must partition.

## What I most want attacked (numbered; answer each)

1. **Plain plans unchanged.** A plan without `cells`/`entrapment` must behave byte-for-byte as before. The three
   measurement hashes (pair/search/score) are pinned and unchanged, but several unmeasured functions changed
   (`pair_done` -> `ready_arms`, `search_done`, `sweep_outputs`, `rescore`, `identity`, `build_identity`,
   `busy_patterns`, `load_plan`, `preflight`, `table_guards`, `cmd_status`). Find any input on which a plain plan now
   behaves differently.
2. **`mzml_scan`** is a line-based streaming parser. Find real OpenMS/diaWeaver output on which it silently
   miscounts, accepts an unsorted or numpress array, crashes, or produces a `prec_digest` that differs between two
   files with identical spectra (or matches between files that differ). Is taking the FIRST occurrence of each
   PREC_CV accession inside a spectrum right (MS:1002815 can appear at scan level and in selectedIon)?
3. **`reencode` / G-V17**: does every check fail closed? What passes that should not (a truncated array, a
   compressed array not labelled MS:1000574, a float array reordered independently of m/z, a spectrum with no m/z
   array)?
4. **`run_capped` / G-V16**: can the diaWeaver process outlive a wall-cap kill, a memory-floor kill, or the
   runner's SIGTERM? Is the "stopped" check ordered correctly relative to `parse_time_log`/`check_exit`?
5. **`run_group`**: an exception that is not `Abort` inside one cell (e.g. a `ValueError` from `mzml_scan` or a
   `zlib.error`): what happens to the reference arms' results and the other cell? Is that the intended
   "a failed cell does not stop the next one"?
6. **No-op flag (G-V18)**: the content digest hashes each spectrum block of the re-encoded file minus
   id/index/spectrumRef. Can two runs of the SAME arm differ in it (so a real no-op is never flagged)? Can two
   different arms collide?
7. **Identity/provenance (G-V03/G-V04/G-V11/G-V13)**: is `build_identity` complete for a cell arm? The arm has
   `bin/`, `lib/`, `share/OpenMS` (OPENMS_DATA_PATH, 258 data files the tool reads at run time), `env.sh`,
   `PROVENANCE` (which also carries `share_OpenMS_tree_sha256=`). What can change between two launches without
   any guard noticing?
8. **Counting rules**: are `sage_by_charge`, `msf_by_charge`, `entrap_strata` exactly consistent with
   `sage_peptides`, `msf_peptides`, `entrapment.score()`? Any tie-break or parsing difference that the equality
   checks would not catch?
9. **Resume logic**: `pair_done`/`ready_arms`/`search_done`/`add_split`/`rescore` with the new `cells` hash. Can a
   search record be adopted without its charge split, or a group be adopted with a failed or stale cell? Can a
   crash between `run_search` writing its record and `add_split` leave a record that the table then crashes on?
10. **Patient-data staging (`stage_tdf`)**: 0700 everywhere, only `analysis.tdf` + `analysis.tdf_bin`, deletion
    on every path, nothing written beside the raw. Anything missed?
11. **Table (`render_cells_table`)**: any KeyError/ZeroDivision on real partial records; any number shown that
    was not produced by a guarded path?
12. Anything else that would make the 26-h run produce a plausible wrong number rather than a refusal.

For every finding give `function`/line context from the diff, a concrete failing input, a severity (blocker /
should-fix / nit), and say whether it would actually bite on this run or is theoretical.

## The plan that will run (from the gitignored registry; no specimen paths)

```yaml
dwv_stage1:
  arm: v1.3.0
  spx_root: /ceph/ibmi/abi/oliver/spextract
  diatracer_dir: /ceph/ibmi/abi/oliver/spextract/diatracer
  diatracer_jar: diaTracer-2.2.1.jar
  jnatmp: /scratch/kohlbach/jnatmp
  scratch_root: /scratch/kohlbach/dwv_stage1
  results_ceph: /ceph/ibmi/abi/oliver/spextract/corpus_v3_dwv_stage1
  report: harness/dwv-stage1.md
  threads: 100
  load_wait_min: 20
  n_samples: 1
  search_db_sha256: {sage_fasta: 29e2..., msfragger_db: 4fa1..., entrap_fasta: 929d...}
  tools: {sage, sage_config, msfragger_jar, msfragger_params, patch, fix, digest, sage_entrap, entrapment}
  entrapment: true
  cells:
    dwv_default: {kind: dwv, arm: diaweaver-7ed1169, args: [], wall_cap_h: 12}
    dwv_pickim:  {kind: dwv, arm: diaweaver-7ed1169,
                  args: ["-bruker:ms1_centroid_mz_ppm", "0", "-bruker:ms1_centroid_im_pct", "0"],
                  wall_cap_h: 12, differs_from: dwv_default}
  queues:
    data: {search_workers: 1, samples: [S30]}
```

The published cell arm `diaweaver-7ed1169/env.sh`:

```sh
export DWV_ARM=/ceph/ibmi/abi/oliver/spextract/diaweaver-7ed1169
export DWV_BIN=$DWV_ARM/bin/diaWeaver
export PATH=$DWV_ARM/bin${PATH:+:$PATH}
export LD_LIBRARY_PATH=$DWV_ARM/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export OPENMS_DATA_PATH=$DWV_ARM/share/OpenMS
export OPENMS_DISABLE_UPDATE_CHECK=ON
unset OPENMS_BRUKER_SDK_PATH
```

`jnatmp` (`/scratch/kohlbach/jnatmp`, the TMPDIR every cell gets) is mode 0755. The scratch root is created 0700.

## git show --stat
```
ba91ac0 harness/corpus.py: extra extractor cells (diaWeaver), re-encode, entrapment by charge (G-V16..G-V19)

 harness/CORPUS.md |  141 ++++-
 harness/README.md |    4 +-
 harness/corpus.py | 1707 +++++++++++++++++++++++++++++++++++++++++++++++++----
 3 files changed, 1743 insertions(+), 109 deletions(-)
a716b5c harness/corpus.py: extended plans stage analysis.tdf + analysis.tdf_bin only

 harness/CORPUS.md |  9 ++++++---
 harness/corpus.py | 56 +++++++++++++++++++++++++++++++++++++++++++++++++------
 2 files changed, 56 insertions(+), 9 deletions(-)
```

## Full diff of harness/corpus.py, 0a1bb0d..a716b5c
```diff
diff --git a/harness/corpus.py b/harness/corpus.py
index 8c53371..5b8934a 100644
--- a/harness/corpus.py
+++ b/harness/corpus.py
@@ -53,6 +53,16 @@ renders as FAILED, never as a number). Each id is triggered by --selftest.
         not a corpus_v3* results dir, collected tree not private
   G-V15 node environment: root under /home, jnatmp not writable, MemAvailable or /proc unreadable,
         python < 3.9, TIME not GNU time -v, no java
+Extended plans (optional plan keys `cells`, `entrapment`; harness/CORPUS.md "Extra cells"):
+  G-V16 cell result: exit!=0, signal, wall cap passed or MemAvailable under the floor (the tool's session is
+        killed), unparseable time log, output missing/stale/unterminated, count <=0, the tool's count line
+        missing/different, its finalisation line missing
+  G-V17 re-encode: tool failed, a numpress term left, a spectrum not m/z-sorted or undecodable, spectrum count
+        changed, RT/selected ion/charge/1/K0/isolation target values changed, a spectrum without MS:1000744
+  G-V18 no-op cell (FLAG): a cell's content digest equals the one of the cell it must differ from, or the
+        check could not run
+  G-V19 charge strata: a result TSV without charge/score columns, a split that does not add up to the cell's
+        count, an entrapment FASTA without ENTRAP_ peptides, 0 target peptides in the entrapment search
 """
 from __future__ import annotations
 
@@ -94,6 +104,31 @@ TOOL_KEYS = ("sage", "sage_config", "msfragger_jar", "msfragger_params", "patch"
 # builds, e.g. a gate chain of another session.
 BUSY_FIXED = [r"diaTracer-2\.2\.[1]\.jar", r"MSFragger-4\.4\.[1]\.jar", r"/sag[e] ", r"spextracto[r] -in"]
 
+# ---- Extended plans: optional plan keys `cells` (extra extractors run after the reference pair, on the same staged
+# copy) and `entrapment` (a third search per output). A plan without either is the two-extractor pair above: the same
+# functions run and measure it, and its three measurement hashes do not move (selftest pins them).
+OPTIONAL_PLAN_KEYS = {"cells", "entrapment"}
+CELL_KEYS = {"kind", "arm", "args", "wall_cap_h"}                 # plus optional differs_from
+CELL_NAME = r"[a-z][a-z0-9_]{0,23}"
+# One kind so far: diaWeaver (alhigaylan/diaWeaver, branch diaWeaver-2). Its env.sh exports `bin`; the arm's `prov`
+# file lists `sha256_published:` for every published file; the tool writes ONE <out dir>/pseudo_spectra.mzML, logs
+# "Wrote N pseudo spectra." and, after its RT sort and numpress rewrite, "Done. Output".
+CELL_KINDS = {"dwv": {"bin": "DWV_BIN", "prov": "PROVENANCE", "out": "pseudo_spectra.mzML", "log": "dwv.log",
+                      "count": rb"Wrote (\d+) pseudo spectra", "done": b"Done. Output"}}
+# Re-encode of a cell output before any search (G-V17). The ONLY place these option strings live. The fork's FileFilter
+# (7ed1169, src/topp/FileFilter.cpp:417/430-447/1011-1013): `-sort` = sortSpectra(true), spectra by RT and every peak
+# list by m/z with its data arrays; numpress defaults to none, zlib to false, m/z to 64 bit. It sits beside the cell bin.
+REENCODE = ("FileFilter", ("-sort",))
+NUMPRESS_CV = (b"MS:1002312", b"MS:1002313", b"MS:1002314", b"MS:1002746", b"MS:1002747", b"MS:1002748")
+PREC_CV = (b"MS:1000016", b"MS:1000744", b"MS:1000041", b"MS:1002815", b"MS:1000827")   # RT, sel. m/z, z, 1/K0, target
+CELL_TOOL_KEYS = ("digest",)                        # bench/semantic_digest.py, for plans with cells
+ENTRAP_TOOL_KEYS = ("sage_entrap", "entrapment")    # Sage config naming the target+entrapment FASTA; bench/entrapment.py
+ENTRAP_DB, ENTRAP_TAG = "entrap_fasta", "ENTRAP_"
+STRATA = (("all", 0, 999), ("z1", 1, 1), ("z2p", 2, 999))   # charge strata (inclusive); z1 + z2p must partition all
+# What an extended plan stages (patient-data rule of the diaWeaver stage): the two files every extractor reads. A raw
+# .d also carries sample and acquisition metadata (SampleInfo.xml, HyStar files, method folders) that no arm needs.
+STAGE_FILES = ("analysis.tdf", "analysis.tdf_bin")
+
 
 class Abort(Exception):
     """A guard fired. `queue=True` stops the whole queue; otherwise only the cell fails."""
@@ -330,12 +365,13 @@ def arm_env(q: dict) -> tuple:
     return env, removed
 
 
-def ldd_deps(env: dict, arm_dir: str) -> dict:
-    """Shared objects SPX_BIN resolves under the arm environment (DT_NEEDED closure) outside the arm directory,
-    with sha256 (review F6): $SPX/lib and another project's conda env sit on LD_LIBRARY_PATH, and the binary's
-    RUNPATH points into a node-local OpenMS build tree that only LD_LIBRARY_PATH overrides."""
+def ldd_deps(env: dict, arm_dir: str, binary=None) -> dict:
+    """Shared objects SPX_BIN (or `binary`) resolves under the arm environment (DT_NEEDED closure) outside the arm
+    directory, with sha256 (review F6): $SPX/lib and another project's conda env sit on LD_LIBRARY_PATH, and the
+    binary's RUNPATH points into a node-local OpenMS build tree that only LD_LIBRARY_PATH overrides."""
+    binary = binary or env["SPX_BIN"]
     try:
-        r = subprocess.run(["ldd", env["SPX_BIN"]], env=env, capture_output=True, text=True, timeout=300)
+        r = subprocess.run(["ldd", binary], env=env, capture_output=True, text=True, timeout=300)
     except FileNotFoundError:
         if sys.platform.startswith("linux"):
             die_queue("G-V15", "ldd not found: the extractor's libraries cannot be pinned")
@@ -344,15 +380,15 @@ def ldd_deps(env: dict, arm_dir: str) -> dict:
     if "not a dynamic executable" in out:          # a script (guardtest/selftest wrapper arm) resolves nothing
         return {}
     if r.returncode != 0 or "not found" in out:
-        die_queue("G-V03", "ldd %s failed or left libraries unresolved: %s" % (env["SPX_BIN"], out.strip()[-400:]))
+        die_queue("G-V03", "ldd %s failed or left libraries unresolved: %s" % (binary, out.strip()[-400:]))
     found = re.findall(r"=>\s+(/\S+)\s+\(0x", out) + re.findall(r"^\s*(/\S+)\s+\(0x", out, re.M)
     deps = {}
     for p in sorted({os.path.realpath(x) for x in found}):
         if p.startswith(arm_dir + os.sep):
             continue                                    # hashed as the arm's lib/**
         if not p.startswith(LIB_ROOTS):
-            die_queue("G-V03", "SPX_BIN resolves %s outside the arm, /ceph and the system library directories "
-                               "(a node-local build tree?)" % p)
+            die_queue("G-V03", "%s resolves %s outside the arm, /ceph and the system library directories "
+                               "(a node-local build tree?)" % (os.path.basename(binary), p))
         deps[p] = sha256(p)
     return deps
 
@@ -380,23 +416,36 @@ def java_info(env: dict) -> dict:
             "major": int(v.split(".")[1] if v.startswith("1.") else re.split(r"[.+_-]", v)[0])}
 
 
+def tree_sha256(d: Path) -> dict:
+    return {str(p.relative_to(d)): sha256(p) for p in sorted(d.rglob("*")) if p.is_file()} if d.is_dir() else {}
+
+
 def identity(q: dict, env: dict) -> dict:
     arm = os.path.realpath(Path(q["spx_root"]) / q["arm"])
     dt = Path(q["diatracer_dir"])
-    tree = lambda d: {str(p.relative_to(d)): sha256(p) for p in sorted(d.rglob("*")) if p.is_file()} if d.is_dir() else {}
-    return {"binary": env["SPX_BIN"], "binary_sha256": sha256(env["SPX_BIN"]), "lib_sha256": tree(Path(arm) / "lib"),
-            "deps_sha256": ldd_deps(env, arm), "jar": q["diatracer_jar"],
-            "jar_sha256": sha256(dt / q["diatracer_jar"]), "bruker_sha256": tree(dt / "ext" / "bruker"),
-            "java": java_info(env)}
+    out = {"binary": env["SPX_BIN"], "binary_sha256": sha256(env["SPX_BIN"]), "lib_sha256": tree_sha256(Path(arm) / "lib"),
+           "deps_sha256": ldd_deps(env, arm), "jar": q["diatracer_jar"],
+           "jar_sha256": sha256(dt / q["diatracer_jar"]), "bruker_sha256": tree_sha256(dt / "ext" / "bruker"),
+           "java": java_info(env)}
+    if cells(q):
+        out["cells"] = cells_identity(q)
+    return out
 
 
 def build_identity(ident: dict) -> dict:
     """What must match across records (G-V11 resume, G-V13 table): the build and every ceph-resident library it
-    loads. Node-local system libraries and the JDK's files may differ between nodes: recorded, and compared
-    within a queue only (G-V04). The JDK feature version is compared on its own (java_major)."""
-    return {"binary_sha256": ident.get("binary_sha256"), "lib_sha256": ident.get("lib_sha256"),
-            "deps_sha256": {p: h for p, h in (ident.get("deps_sha256") or {}).items() if p.startswith("/ceph/")},
-            "jar_sha256": ident.get("jar_sha256"), "bruker_sha256": ident.get("bruker_sha256")}
+    loads, and for an extended plan each cell's build (binary, lib/**, re-encode tool, ceph libraries). Node-local
+    system libraries and the JDK's files may differ between nodes: recorded, and compared within a queue only
+    (G-V04). The JDK feature version is compared on its own (java_major)."""
+    ceph = lambda deps: {p: h for p, h in (deps or {}).items() if p.startswith("/ceph/")}
+    out = {"binary_sha256": ident.get("binary_sha256"), "lib_sha256": ident.get("lib_sha256"),
+           "deps_sha256": ceph(ident.get("deps_sha256")),
+           "jar_sha256": ident.get("jar_sha256"), "bruker_sha256": ident.get("bruker_sha256")}
+    if ident.get("cells"):
+        out["cells"] = {n: {"binary_sha256": c["binary_sha256"], "lib_sha256": c["lib_sha256"],
+                            "reencode_sha256": c["reencode_sha256"], "deps_sha256": ceph(c["deps_sha256"])}
+                        for n, c in ident["cells"].items()}
+    return out
 
 
 def java_major(ident: dict):
@@ -409,6 +458,16 @@ def check_identity(q: dict, env: dict, ident0: dict, when: str) -> None:
         die_queue("G-V04", "binary/lib/jar changed %s (republished under a running queue?)" % when)
 
 
+def tool_label(binary: str, env: dict) -> str:
+    r = subprocess.run([binary, "--help"], env=env, capture_output=True, text=True,
+                       stdin=subprocess.DEVNULL, timeout=300)
+    name = re.search(r"^(\S+) -- ", r.stdout + r.stderr, re.M)
+    ver = re.search(r"^Version: (\S+)", r.stdout + r.stderr, re.M)
+    if not (name and ver):
+        die_queue("G-V03", "tool label unresolvable from %s --help" % binary)
+    return "%s %s" % (name.group(1), ver.group(1))
+
+
 def arm_meta(env: dict, ident0: dict) -> dict:
     """Tool label from the binary itself; provenance from the publish step. Nothing hard-coded."""
     prov = Path(env["SPX_BIN"] + ".provenance")
@@ -418,18 +477,118 @@ def arm_meta(env: dict, ident0: dict) -> dict:
     ps = [x.split("=", 1)[1] for x in lines if x.startswith("binary_sha256=")]
     if not ps or ps[0] != ident0["binary_sha256"]:
         die_queue("G-V03", "provenance binary_sha256 %s != sha256(SPX_BIN) %s" % (ps[:1], ident0["binary_sha256"][:16]))
-    r = subprocess.run([env["SPX_BIN"], "--help"], env=env, capture_output=True, text=True,
-                       stdin=subprocess.DEVNULL, timeout=300)
-    name = re.search(r"^(\S+) -- ", r.stdout + r.stderr, re.M)
-    ver = re.search(r"^Version: (\S+)", r.stdout + r.stderr, re.M)
-    if not (name and ver):
-        die_queue("G-V03", "tool label unresolvable from %s --help" % env["SPX_BIN"])
-    return {"label": "%s %s" % (name.group(1), ver.group(1)), "provenance": lines}
+    return {"label": tool_label(env["SPX_BIN"], env), "provenance": lines}
+
+
+# ------------------------------------------------------------------------------- node: extra cells (extended plans)
+def cells(q: dict) -> dict:
+    return q.get("cells") or {}
+
+
+def extended(q: dict) -> bool:
+    return bool(cells(q) or q.get("entrapment"))
+
+
+def q_tools(q: dict) -> tuple:
+    return TOOLS + tuple(cells(q))
+
+
+def q_engines(q: dict) -> tuple:
+    return ENGINES + (("entrap",) if q.get("entrapment") else ())
+
+
+def cell_env(q: dict, name: str) -> dict:
+    """A cell's env.sh on the base arm_env uses (G-V03): the same variables stripped, the kind's binary variable
+    set, executable and inside the cell arm, with the re-encode tool beside it."""
+    c = q["cells"][name]
+    var = CELL_KINDS[c["kind"]]["bin"]
+    env_sh = Path(q["spx_root"]) / c["arm"] / "env.sh"
+    if not env_sh.is_file():
+        die_queue("G-V03", "cell %s: env.sh missing: %s" % (name, env_sh))
+    base = {k: v for k, v in os.environ.items() if not (strip_var(k) or k in INHERIT_DROP)}
+    r = subprocess.run(["bash", "-c", 'source "$1" >&2 && env -0', "_", str(env_sh)], env=base, capture_output=True)
+    if r.returncode != 0:
+        die_queue("G-V03", "cell %s: sourcing %s failed: %s" % (name, env_sh, r.stderr.decode(errors="replace")[-300:]))
+    env = dict(kv.split("=", 1) for kv in r.stdout.decode(errors="replace").split("\0") if "=" in kv)
+    bad = sorted(k for k in env if strip_var(k))
+    if bad:
+        die_queue("G-V03", "cell %s: %s itself exports %s: a configured arm, not the defaults" % (name, env_sh, bad))
+    arm_dir = os.path.realpath(env_sh.parent)
+    for what, b in ((var, env.get(var, "")), (REENCODE[0], str(Path(env.get(var) or "/nonexistent").parent / REENCODE[0]))):
+        if not b or not os.path.isfile(b) or not os.access(b, os.X_OK):
+            die_queue("G-V03", "cell %s: %s unset or not an executable file: %r" % (name, what, b))
+        if not os.path.realpath(b).startswith(arm_dir + os.sep):
+            die_queue("G-V03", "cell %s: %s %s is outside the cell arm %s" % (name, what, b, arm_dir))
+    env.update(LC_ALL="C", TMPDIR=q["jnatmp"])
+    return env
+
+
+def cells_identity(q: dict) -> dict:
+    """G-V04/G-V11/G-V13 for the cells: binary, re-encode tool, the arm's lib/** and the libraries both resolve."""
+    by_arm, out = {}, {}
+    for name, c in cells(q).items():
+        if c["arm"] not in by_arm:
+            env = cell_env(q, name)
+            b = env[CELL_KINDS[c["kind"]]["bin"]]
+            tool = str(Path(b).parent / REENCODE[0])
+            arm = os.path.realpath(Path(q["spx_root"]) / c["arm"])
+            by_arm[c["arm"]] = {"binary": b, "binary_sha256": sha256(b), "reencode_sha256": sha256(tool),
+                                "lib_sha256": tree_sha256(Path(arm) / "lib"),
+                                "deps_sha256": dict(ldd_deps(env, arm, b), **ldd_deps(env, arm, tool))}
+        out[name] = by_arm[c["arm"]]
+    return out
+
+
+def cell_provenance(q: dict, name: str, cenv: dict, cid: dict) -> list:
+    """G-V03: the cell arm's provenance file lists, under `sha256_published:`, the binary, the re-encode tool and every
+    lib/** file of the arm, each with the sha256 the file has now."""
+    c = q["cells"][name]
+    kind = CELL_KINDS[c["kind"]]
+    arm = os.path.realpath(Path(q["spx_root"]) / c["arm"])
+    prov = Path(arm) / kind["prov"]
+    if not prov.is_file():
+        die_queue("G-V03", "cell %s: provenance missing: %s" % (name, prov))
+    lines = prov.read_text().splitlines()
+    listed, block = {}, False
+    for line in lines:
+        if not line[:1].isspace():
+            block = line.strip() == "sha256_published:"
+        elif block:
+            m = re.fullmatch(r"\s+([0-9a-f]{64})\s+(\S+)\s*", line)
+            if m:
+                listed[m.group(2)] = m.group(1)
+    b = os.path.realpath(cenv[kind["bin"]])
+    want = dict({os.path.relpath(b, arm): cid["binary_sha256"],
+                 os.path.relpath(os.path.join(os.path.dirname(b), REENCODE[0]), arm): cid["reencode_sha256"]},
+                **{"lib/" + k: v for k, v in cid["lib_sha256"].items()})
+    bad = sorted(k for k, v in want.items() if listed.get(k) != v)
+    if bad:
+        die_queue("G-V03", "cell %s: %s sha256_published omits or differs from %s" % (name, prov, bad[:4]))
+    return lines
+
+
+def cells_meta(q: dict, cenvs: dict, ident0: dict) -> dict:
+    """G-V03 per cell: provenance listing the files in use, label from the binary's --help."""
+    out = {}
+    for name, c in cells(q).items():
+        env, var = cenvs[name], CELL_KINDS[c["kind"]]["bin"]
+        out[name] = {"label": tool_label(env[var], env), "bin_var": var,
+                     "provenance": cell_provenance(q, name, env, ident0["cells"][name]),
+                     "openms_data_path": env.get("OPENMS_DATA_PATH"), "ld_library_path": env.get("LD_LIBRARY_PATH")}
+    return out
 
 
 def tool_dest(q: dict) -> dict:
     t, d = q["tools"], Path(q["root"]) / "tools"
-    return {"sage": d / "sage" / "sage", **{k: d / Path(t[k]).name for k in TOOL_KEYS if k != "sage"}}
+    return {"sage": d / "sage" / "sage", **{k: d / Path(t[k]).name for k in plan_tool_keys(q) if k != "sage"}}
+
+
+def plan_tool_keys(plan: dict) -> tuple:
+    return TOOL_KEYS + (CELL_TOOL_KEYS if plan.get("cells") else ()) + (ENTRAP_TOOL_KEYS if plan.get("entrapment") else ())
+
+
+def db_keys(plan: dict) -> tuple:
+    return DB_KEYS + ((ENTRAP_DB,) if plan.get("entrapment") else ())
 
 
 def install_tools(q: dict) -> dict:
@@ -446,33 +605,37 @@ def install_tools(q: dict) -> dict:
             d.parent.mkdir(parents=True, exist_ok=True)
             shutil.copy2(src, d)
     paths = {k: str(v) for k, v in dest.items()}
-    paths.update(search_dbs(dest["sage_config"], dest["msfragger_params"]))
+    paths.update(search_dbs(dest["sage_config"], dest["msfragger_params"], dest.get("sage_entrap")))
     shas = {k: sha256(v) for k, v in paths.items()}
     check_db_pins(q, shas)
     return {"paths": paths, "sha256": shas}
 
 
 def check_fasta(tools: dict) -> None:
-    for k in DB_KEYS:
+    for k in [k for k in DB_KEYS + (ENTRAP_DB,) if k in tools["paths"]]:
         if sha256(tools["paths"][k]) != tools["sha256"][k]:
             die_queue("G-V12", "%s changed during the run: %s" % (k, tools["paths"][k]))
 
 
-def search_dbs(sage_config, msfragger_params) -> dict:
-    try:
-        fasta = json.loads(Path(sage_config).read_text())["database"]["fasta"]
-    except (OSError, ValueError, KeyError, TypeError) as x:
-        die_queue("G-V12", "sage config %s has no database.fasta: %s" % (sage_config, x))
+def search_dbs(sage_config, msfragger_params, sage_entrap=None) -> dict:
+    def fasta(cfg):
+        try:
+            return json.loads(Path(cfg).read_text())["database"]["fasta"]
+        except (OSError, ValueError, KeyError, TypeError) as x:
+            die_queue("G-V12", "sage config %s has no database.fasta: %s" % (cfg, x))
     m = re.search(r"^database_name\s*=\s*(\S+)", Path(msfragger_params).read_text(), re.M)
     if not m:
         die_queue("G-V12", "msfragger.params has no database_name")
-    return {"sage_fasta": fasta, "msfragger_db": m.group(1)}
+    out = {"sage_fasta": fasta(sage_config), "msfragger_db": m.group(1)}
+    if sage_entrap:
+        out[ENTRAP_DB] = fasta(sage_entrap)
+    return out
 
 
 def check_db_pins(q: dict, shas: dict) -> None:
     """The databases are node-local files: one byte of difference on one node would otherwise surface only when
     the table refuses mixed search inputs after the whole run (review F5)."""
-    for k in DB_KEYS:
+    for k in db_keys(q):
         if shas.get(k) != q["search_db_sha256"].get(k):
             die_queue("G-V12", "%s sha256 %s differs from the plan pin %s" % (k, str(shas.get(k))[:16],
                                                                              str(q["search_db_sha256"].get(k))[:16]))
@@ -495,7 +658,7 @@ def preflight(q: dict, env: dict, version_info=None) -> dict:
             die_queue("G-V15", "%s -v true: rc %s exit %s" % (TIME, rc, t["exit_status"]))
     if sys.platform.startswith("linux") and proc_snapshot() is None:
         die_queue("G-V15", "/proc unreadable: contention during an arm cannot be measured")
-    dbs = search_dbs(q["tools"]["sage_config"], q["tools"]["msfragger_params"])
+    dbs = search_dbs(q["tools"]["sage_config"], q["tools"]["msfragger_params"], q["tools"].get("sage_entrap"))
     for k, p in dbs.items():
         if not os.path.isfile(p):
             die_queue("G-V12", "%s missing on this node: %s" % (k, p))
@@ -503,13 +666,19 @@ def preflight(q: dict, env: dict, version_info=None) -> dict:
     check_db_pins(q, shas)
     j = java_info(env)
     return {"python": ".".join(map(str, v)), "time": TIME, "java": {k: j[k] for k in ("path", "version", "major")},
-            "search_db": {k: {"path": dbs[k], "sha256": shas[k]} for k in DB_KEYS}}
+            "search_db": {k: {"path": dbs[k], "sha256": shas[k]} for k in db_keys(q)}}
 
 
 # ------------------------------------------------------------------------------- node: gate, staging
-def busy_patterns(env: dict) -> list:
-    base = os.path.basename(env["SPX_BIN"])
-    return BUSY_FIXED + [base[:-1].replace(".", r"\.") + "[" + base[-1] + "] -in"]
+def bracketed(binary: str) -> str:
+    base = os.path.basename(binary)
+    return base[:-1].replace(".", r"\.") + "[" + base[-1] + "] -in"
+
+
+def busy_patterns(env: dict, cenvs=None) -> list:
+    """`cenvs` (extended plans): the cells' binaries are ours too."""
+    extra = sorted({bracketed(e[v]) for e in (cenvs or {}).values() for v in e if v in {k["bin"] for k in CELL_KINDS.values()}})
+    return BUSY_FIXED + [bracketed(env["SPX_BIN"])] + extra
 
 
 def busy(patterns: list) -> list:
@@ -739,6 +908,14 @@ def cmd_msf(tp, tl):
     return [TIME, "-v", "-o", str(tl), "java", "-Xmx200G", "-jar", tp["msfragger_jar"], tp["msfragger_params"], "./in.mzML"]
 
 
+def cmd_dwv(q, dwv_bin, staged, adir, tl, args):
+    return [TIME, "-v", "-o", str(tl), dwv_bin, "-in", str(staged), "-out", str(adir), "-threads", str(q["threads"])] + list(args)
+
+
+def cmd_reencode(tool, src, dst, tl):
+    return [TIME, "-v", "-o", str(tl), tool, "-in", str(src), "-out", str(dst)] + list(REENCODE[1])
+
+
 def run_logged(argv, cwd, env, log: Path) -> int:
     with open(log, "wb") as f:
         return subprocess.run(argv, cwd=str(cwd), env=env, stdout=f, stderr=subprocess.STDOUT,
@@ -841,38 +1018,371 @@ def run_pair(q, idx, s, env, ident0, meta, removed, patterns) -> bool:
     return rec["status"] == "ok"
 
 
+def stage_tdf(q: dict, s: dict, pair_run: str) -> tuple:
+    """stage() for an extended plan: the same fresh 0700 directory, neutral name and pin checks (G-V02, G-V07), but
+    only STAGE_FILES are copied."""
+    sroot = Path(q["root"]) / "stage"
+    sroot.mkdir(mode=0o700, parents=True, exist_ok=True)
+    os.chmod(sroot, 0o700)
+    d = sroot / ("%s-%s" % (s["id"], pair_run))
+    d.mkdir(mode=0o700)
+    raw = Path(s["raw"])
+    fp_raw = fingerprint(raw, with_acq=True, what="raw of %s" % s["id"])
+    check_pin(fp_raw, s["pin"], "raw of %s" % s["id"])
+    if round(fp_raw["acq_min"], 1) != round(float(s["acq_min"]), 1):
+        die("G-V02", "raw of %s: acquisition %.1f min, registry acq_min %s" % (s["id"], fp_raw["acq_min"], s["acq_min"]))
+    dst = d / (s["id"] + ".d")
+    t0 = time.monotonic()
+    try:
+        dst.mkdir(mode=0o700)
+        for f in STAGE_FILES:
+            shutil.copyfile(raw / f, dst / f)
+    except OSError as x:
+        die("G-V07", "staging copy of %s failed: %s" % (s["id"], x.strerror or type(x).__name__))
+    secs = time.monotonic() - t0
+    fp = fingerprint(dst, what="staged copy of %s" % s["id"])
+    check_pin(fp, s["pin"], "staged copy of %s" % s["id"])
+    return dst, {"dir": str(d), "name": dst.name, "copy_s": round(secs, 1), "fingerprint": fp,
+                 "acq_min_read": fp_raw["acq_min"], "files": sorted(x.name for x in dst.iterdir())}
+
+
+def kill_session(pid: int) -> None:
+    try:
+        os.killpg(pid, signal.SIGKILL)
+    except ProcessLookupError:
+        pass
+
+
+def run_capped(argv, cwd, env, log: Path, cap_s: float) -> tuple:
+    """run_logged with a wall cap and a node memory floor (G-V16). The tool runs in its own session, and the whole
+    session is killed when the cap passes, when MemAvailable falls below MEM_FLOOR of MemTotal (a runaway arm must not
+    take a shared node down), or when the runner itself is stopped. Returns (returncode, reason stopped or None)."""
+    t0, why = time.monotonic(), None
+    with open(log, "wb") as f:
+        p = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=f, stderr=subprocess.STDOUT,
+                             stdin=subprocess.DEVNULL, start_new_session=True)
+        try:
+            while p.poll() is None:
+                m = proc_snapshot()
+                if time.monotonic() - t0 > cap_s:
+                    why = "wall cap %.0f s exceeded" % cap_s
+                elif m and m["memavail_kb"] < MEM_FLOOR * m["memtotal_kb"]:
+                    why = "MemAvailable %.1f%% of total" % (100.0 * m["memavail_kb"] / m["memtotal_kb"])
+                if why:
+                    kill_session(p.pid)
+                    break
+                try:
+                    p.wait(timeout=MON_S)
+                except subprocess.TimeoutExpired:
+                    pass
+        except BaseException:
+            kill_session(p.pid)
+            p.wait()
+            raise
+        p.wait()
+    return p.returncode, why
+
+
+def time_cpu(path: Path) -> dict:
+    """CPU seconds and occupancy from a GNU time -v log (user + system over wall)."""
+    txt = path.read_text(errors="replace") if path.exists() else ""
+    u = re.search(r"User time \(seconds\): ([\d.]+)", txt)
+    k = re.search(r"System time \(seconds\): ([\d.]+)", txt)
+    c = re.search(r"Percent of CPU this job got: (\d+)%", txt)
+    return {"cpu_s": round(float(u.group(1)) + float(k.group(1)), 2) if u and k else None,
+            "cpu_pct": int(c.group(1)) if c else None}
+
+
+def mzml_scan(path: Path, decode=False) -> dict:
+    """One pass over an mzML (G-V17, G-V18): spectra, numpress terms anywhere, per-spectrum RT and precursor values
+    (a digest of the sorted tuples: order may change, values may not), charge and 1/K0 tallies, peaks. With `decode`,
+    each m/z array (plain or zlib, 32/64 bit) is read and its order checked, and an order-independent content digest
+    is built: every spectrum block hashed without its id/index/spectrumRef, the sorted block digests hashed again.
+    diaWeaver's final RT sort is unstable and renumbers scan=N, so two runs of one arm differ in order and ids but
+    not in this digest."""
+    import array, zlib
+    acc_re, val_re = re.compile(rb'\saccession="(MS:\d+)"'), re.compile(rb'\svalue="([^"]*)"')
+    ids_re = re.compile(rb'\s(?:id|index|spectrumRef)="[^"]*"')
+    out = {"spectra": 0, "numpress_terms": 0, "unsorted": 0, "undecoded": 0, "length_mismatch": 0,
+           "missing_selected_ion": 0, "im_zero": 0, "im_missing": 0, "charges": {}}
+    keys, blocks, peaks = [], [], array.array("l")
+    inside, h, prec, arr, n_decl = False, None, {}, {}, 0
+    with open(path, "rb") as f:
+        for line in f:
+            if b"<cvParam" in line:
+                a = acc_re.search(line)
+                acc = a.group(1) if a else b""
+                if acc in NUMPRESS_CV:
+                    out["numpress_terms"] += 1
+                if inside:
+                    if acc in PREC_CV and acc not in prec:
+                        v = val_re.search(line)
+                        prec[acc] = v.group(1).decode() if v else ""
+                    arr[acc] = True
+            if not inside:
+                if b"<spectrum " in line or line.lstrip().startswith(b"<spectrum>"):
+                    inside, prec, arr = True, {}, {}
+                    m = re.search(rb'defaultArrayLength="(\d+)"', line)
+                    n_decl = int(m.group(1)) if m else -1
+                    h = hashlib.sha256(ids_re.sub(b"", line)) if decode else None
+                continue
+            if h is not None:
+                h.update(ids_re.sub(b"", line) if b"spectrumRef" in line else line)
+            if b"<binaryDataArray " in line or b"<binaryDataArray>" in line:
+                arr = {}
+            elif b"<binary>" in line and b"MS:1000514" in arr:
+                if not decode:
+                    continue
+                if any(t in arr for t in NUMPRESS_CV) or not (b"MS:1000523" in arr or b"MS:1000521" in arr):
+                    out["undecoded"] += 1
+                    continue
+                raw = base64.b64decode(line.split(b"<binary>", 1)[1].split(b"</binary>", 1)[0])
+                if b"MS:1000574" in arr:
+                    raw = zlib.decompress(raw)
+                mz = array.array("d" if b"MS:1000523" in arr else "f")
+                mz.frombytes(raw)
+                if sys.byteorder != "little":
+                    mz.byteswap()
+                values = mz.tolist()
+                out["unsorted"] += values != sorted(values)
+                out["length_mismatch"] += len(values) != n_decl
+            elif b"</spectrum>" in line:
+                inside = False
+                out["spectra"] += 1
+                peaks.append(n_decl)
+                fl = lambda k: repr(float(prec[k])) if prec.get(k) not in (None, "") else ""
+                keys.append("|".join(fl(k) for k in PREC_CV))
+                out["missing_selected_ion"] += not fl(b"MS:1000744")
+                z = prec.get(b"MS:1000041") or "none"
+                out["charges"][z] = out["charges"].get(z, 0) + 1
+                im = fl(b"MS:1002815")
+                out["im_missing"] += not im
+                out["im_zero"] += bool(im) and float(im) == 0.0
+                if h is not None:
+                    blocks.append(h.digest())
+    keys.sort()
+    out["prec_digest"] = hashlib.sha256("\n".join(keys).encode()).hexdigest()
+    out["peaks_total"] = sum(peaks)
+    out["peaks_median"] = statistics.median(peaks) if peaks else 0
+    if decode:
+        blocks.sort()
+        out["content_digest"] = hashlib.sha256(b"".join(blocks)).hexdigest()
+    return out
+
+
+def reencode(q, name, cenv, src: Path, adir: Path, rec: dict, digest) -> None:
+    """G-V17: the cell output rewritten by REENCODE before any search (Sage 0.14 drops a numpress m/z array; diaWeaver
+    writes peaks unsorted). The rewrite must carry no numpress term, m/z-sorted peaks, the same spectra and the same
+    RT/precursor values, and a selected ion m/z in every spectrum (no selected-ion patch for cells). The original is
+    deleted once the rewrite passed; `rec["output"]` is the rewrite, the file every search reads."""
+    tool = str(Path(cenv[CELL_KINDS[q["cells"][name]["kind"]]["bin"]]).parent / REENCODE[0])
+    dst, tl = adir / "reencoded.mzML", adir / "reencode.time"
+    argv = cmd_reencode(tool, src, dst, tl)
+    t0 = time.time()
+    rc = run_logged(argv, adir, cenv, adir / "reencode.log")
+    t = parse_time_log(tl, "G-V17")
+    rec["reencode"] = dict(t, cmd=argv, time_rc=rc, cpu=time_cpu(tl))
+    check_exit(t, rc, "G-V17", "re-encode of %s" % name)
+    try:
+        o = verify_mzml(dst, t0)
+    except Abort as a:
+        die("G-V17", a.message)
+    before, after = mzml_scan(src), mzml_scan(dst, decode=True)
+    rec.update(spectra_stats=before, reencoded_stats=after)
+    if after["numpress_terms"]:
+        die("G-V17", "%d numpress term(s) remain after the re-encode of %s" % (after["numpress_terms"], name))
+    if after["unsorted"] or after["undecoded"] or after["length_mismatch"]:
+        die("G-V17", "re-encoded %s: %d spectra not m/z-sorted, %d m/z arrays undecodable, %d with a length mismatch"
+            % (name, after["unsorted"], after["undecoded"], after["length_mismatch"]))
+    counts = {before["spectra"], after["spectra"], o["count"], rec["raw_output"]["count"]}
+    if len(counts) != 1:
+        die("G-V17", "re-encode of %s changed the spectrum count: %d -> %d (spectrumList %d -> %d)"
+            % (name, before["spectra"], after["spectra"], rec["raw_output"]["count"], o["count"]))
+    if after["prec_digest"] != before["prec_digest"]:
+        die("G-V17", "re-encode of %s changed RT, selected ion m/z, charge, 1/K0 or isolation target values" % name)
+    if after["missing_selected_ion"]:
+        die("G-V17", "%d spectra of %s carry no selected ion m/z (MS:1000744)" % (after["missing_selected_ion"], name))
+    try:
+        sem = digest(str(dst))
+    except SystemExit as x:              # semantic_digest.py exits on a file without a complete spectrum list
+        die("G-V17", "spectrum-list digest of re-encoded %s: %s" % (name, x))
+    rec.update(output=o, digests={"semantic": sem, "content": after["content_digest"]})
+    src.unlink()
+
+
+def run_cell(q, name, staged: Path, adir: Path, cenv, env, ident0, rec: dict, digest) -> None:
+    """One extra cell, timed like run_arm (G-V16 in place of G-V08), then re-encoded outside its timed window."""
+    c = q["cells"][name]
+    kind = CELL_KINDS[c["kind"]]
+    adir.mkdir(parents=True)
+    tl, log, out = adir / "time.log", adir / kind["log"], adir / kind["out"]
+    argv = cmd_dwv(q, cenv[kind["bin"]], staged, adir, tl, c["args"])
+    if not str(staged).startswith(str(Path(q["root"]) / "stage") + os.sep):
+        die("G-V07", "cell input outside the stage root: %s" % staged)
+    check_identity(q, env, ident0, "before the %s cell" % name)
+    rec.update(tool=name, kind=c["kind"], arm=c["arm"], cmd=argv, cwd=str(adir), host=hostname(), cores=os.cpu_count(),
+               wall_cap_s=c["wall_cap_h"] * 3600, sync_s=flush_io(q["root"]), prewarm_s=prewarm(staged))
+    rec.update(ps_top=ps_top(), load_before=load1(), memavail_before_kb=mem_available_kb(), start=now_iso())
+    with ArmMonitor(load_max(q)) as mon:
+        t0 = time.time()
+        rc, stopped = run_capped(argv, adir, cenv, log, c["wall_cap_h"] * 3600)
+    rec.update(end=now_iso(), start_epoch=t0, time_rc=rc, stopped=stopped, during=mon.summary(), load_after=load1(),
+               memavail_after_kb=mem_available_kb())
+    check_identity(q, env, ident0, "during the %s cell" % name)
+    if stopped:
+        die("G-V16", "%s killed: %s" % (name, stopped))
+    rec.update(parse_time_log(tl, "G-V16"), cpu=time_cpu(tl))
+    check_exit(rec, rc, "G-V16", name)
+    if not out.is_file():
+        die("G-V16", "%s wrote no %s" % (name, kind["out"]))
+    try:
+        o = verify_mzml(out, t0)
+    except Abort as a:
+        die("G-V16", a.message)
+    n = log_count(log, kind["count"])
+    rec.update(raw_output=o, log_count=n)
+    if n != o["count"]:
+        die("G-V16", "%s: log count %s != spectrumList count %s" % (name, n, o["count"]))
+    if kind["done"] not in log.read_bytes():
+        die("G-V16", "%s log lacks %r: the final rewrite did not finish" % (name, kind["done"].decode()))
+    reencode(q, name, cenv, out, adir, rec, digest)
+
+
+def noop_check(rec: dict) -> None:
+    """G-V18 (flags): a cell with `differs_from` must differ from that cell in content (order-independent digest; the
+    spectrum-list digest and count are recorded beside it). Not computable (either cell failed) counts as flagged."""
+    for name, c in (rec.get("cells") or {}).items():
+        ref = c.get("differs_from")
+        a, b = rec["arms"].get(name) or {}, rec["arms"].get(ref) or {}
+        if not ref or a.get("status") != "ok":
+            continue
+        if b.get("status") != "ok":
+            a["noop"] = {"vs": ref, "computed": False, "flag": True, "why": "%s did not finish" % ref}
+            continue
+        same = a["digests"]["content"] == b["digests"]["content"]
+        a["noop"] = {"vs": ref, "computed": True, "flag": same, "content_equal": same,
+                     "semantic_equal": a["digests"]["semantic"] == b["digests"]["semantic"],
+                     "count_equal": a["output"]["count"] == b["output"]["count"]}
+
+
+def run_group(q, idx, s, env, ident0, meta, removed, patterns, cenvs, digest) -> bool:
+    """run_pair for an extended plan (G-V09 extended). The reference pair runs first, alternating as in run_pair, then
+    every cell in plan order rotated by queue index, all on one staged copy, each synced and pre-warmed. A failed
+    reference arm ends the attempt before any cell. A failed cell is recorded in its arm and the other cells still run
+    (a wall-cap stop of one arm must not hide the next), but the group counts as done only when every arm is ok, so
+    the next launch re-runs it whole (pair_done). run_pair itself stays untouched: it measures the plain plans."""
+    root = Path(q["root"])
+    pair_run = time.strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex()
+    ref = list(TOOLS) if idx % 2 == 0 else list(reversed(TOOLS))
+    names = list(cells(q))
+    k = idx % len(names) if names else 0
+    order = ref + names[k:] + names[:k]
+    rec = {"kind": "pair", "id": s["id"], "sample": sample_record(s), "pair_run": pair_run, "order": order,
+           "node": hostname(), "plan": q["plan"], "harness_sha256": q["harness_sha256"],
+           "measure_sha256": meta.get("measure"), "runtime": meta.get("runtime"), "identity": ident0, "label": meta["label"],
+           "provenance": meta["provenance"], "env_removed": removed, "env_keys": sorted(env),
+           "ld_library_path": env.get("LD_LIBRARY_PATH"), "threads": q["threads"], "cells": cells(q),
+           "cells_meta": meta.get("cells", {}), "entrapment": bool(q.get("entrapment")), "cells_failed": [],
+           "started": now_iso(), "arms": {}, "status": "running"}
+    for old in (root / "runs" / s["id"]).glob("*/*/*.mzML"):
+        old.unlink()
+    sd = root / "stage" / ("%s-%s" % (s["id"], pair_run))
+    err = None
+    write_json(root / "records" / ("%s.pair.json" % s["id"]), rec)
+    say("group %s %s order %s" % (s["id"], pair_run, " -> ".join(order)))
+    try:
+        staged, rec["stage"] = stage_tdf(q, s, pair_run)
+        rec["gate"] = load_gate(q, patterns)
+        nb = rec["neighbour_before"] = neighbour(s["raw"])
+        for tool in ref:
+            rec["arms"][tool] = {}
+            adir = root / "runs" / s["id"] / pair_run / tool
+            run_arm(q, tool, staged, adir, env, ident0, rec["arms"][tool], s, nb)
+            rec["arms"][tool]["cpu"] = time_cpu(adir / "time.log")
+        for name in order[len(ref):]:
+            a = rec["arms"][name] = {}
+            try:
+                run_cell(q, name, staged, root / "runs" / s["id"] / pair_run / name, cenvs[name], env, ident0, a, digest)
+                a["status"] = "ok"
+            except Abort as x:
+                if x.queue:
+                    raise
+                a.update(status="failed", guard=x.guard, message=x.message)
+                rec["cells_failed"].append(name)
+                say("cell %s %s failed [%s] %s" % (s["id"], name, x.guard, x.message))
+        noop_check(rec)
+        rec["status"] = "ok"
+    except Abort as a:
+        rec.update(status="failed", guard=a.guard, message=a.message)
+        err = a
+    except Exception as x:
+        rec.update(status="failed", guard="CRASH", message="%s: %s" % (type(x).__name__, x))
+        err = x
+    except BaseException as x:
+        rec.update(status="failed", guard="KILLED", message="%s during the group" % type(x).__name__)
+        err = x
+    finally:
+        remove_tree(sd)
+        if sd.exists():
+            rec.update(status="failed", cleanup="G-V14 staged copy not deleted: %s" % sd)
+            rec.setdefault("guard", "G-V14")
+            rec.setdefault("message", "staged copy not deleted: %s" % sd)
+        rec["ended"] = now_iso()
+        write_json(root / "records" / ("%s.pair.json" % s["id"]), rec)
+        say("group %s %s%s %s" % (s["id"], rec["status"], " cells failed %s" % rec["cells_failed"] if rec["cells_failed"] else "",
+                                  "" if rec["status"] == "ok" else "[%s] %s" % (rec.get("guard"), rec.get("message"))))
+    if sd.exists():
+        die_queue("G-V14", "staged copy not deleted: %s" % sd)
+    if err is not None and (not isinstance(err, Abort) or err.queue):
+        raise err
+    return rec["status"] == "ok" and not rec["cells_failed"]
+
+
 def rec_path(root, sid: str, *k) -> Path:
     return Path(root) / "records" / (".".join((sid,) + k) + ".json")
 
 
 def search_done(rec, pair, ctx: dict) -> bool:
+    """`cells` is the extended plans' fourth measurement hash; a plain plan has none on either side."""
     m = (rec or {}).get("measure_sha256") or {}
     return bool(rec and pair) and rec.get("status") == "ok" and rec.get("pair_run") == pair.get("pair_run") \
         and rec.get("tools_sha256") == ctx["tools_sha"] and m.get("search") == ctx["measure"]["search"] \
-        and m.get("score") == ctx["measure"]["score"] and rec.get("peptides", 0) > 0
+        and m.get("score") == ctx["measure"]["score"] and m.get("cells") == ctx["measure"].get("cells") \
+        and rec.get("peptides", 0) > 0
 
 
 def pair_done(rec, s, ctx: dict, root: Path) -> bool:
     """G-V11: a record is trusted only if it describes THIS build, JDK feature version, measurement code, thread
-    count and input, and every output it still has to feed a search is the very file it verified. An old mzML is
-    never adopted. `ctx`: ident, tools_sha, measure, threads of the running queue."""
+    count, cells and input, every arm finished ok, and every output it still has to feed a search is the very file it
+    verified. An old mzML is never adopted. `ctx`: ident, tools_sha, measure, threads of the running queue (plus
+    tools, engines and cells for an extended plan)."""
+    ready = ready_arms(rec, s, ctx, root)
+    return ready is not None and ready == list(ctx.get("tools", TOOLS))      # a failed cell is never ready
+
+
+def ready_arms(rec, s, ctx: dict, root: Path):
+    """None if the record is not of this build/code/threads/cells/input; else the arms (in plan order) that finished
+    ok and whose output either fed every search already or is still the verified file."""
     ident = (rec or {}).get("identity") or {}
+    m = (rec or {}).get("measure_sha256") or {}
     if not rec or rec.get("status") != "ok" or build_identity(ident) != build_identity(ctx["ident"]) \
             or java_major(ident) != java_major(ctx["ident"]) or rec.get("threads") != ctx["threads"] \
-            or (rec.get("measure_sha256") or {}).get("pair") != ctx["measure"]["pair"] \
+            or m.get("pair") != ctx["measure"]["pair"] or m.get("cells") != ctx["measure"].get("cells") \
+            or rec.get("cells") != ctx.get("cells") \
             or rec["sample"].get("pin") != s["pin"] or rec["sample"].get("raw_sha256") != sample_record(s)["raw_sha256"]:
-        return False
-    for tool in TOOLS:
+        return None
+    ready = []
+    for tool in ctx.get("tools", TOOLS):
         a = rec["arms"].get(tool) or {}
         o = a.get("output")
-        if not o or o["count"] <= 0 or o["mtime"] <= a["start_epoch"]:
-            return False
-        if all(search_done(read_json(rec_path(root, s["id"], tool, e)), rec, ctx) for e in ENGINES):
+        if a.get("status", "ok") != "ok" or not o or o["count"] <= 0 or o["mtime"] <= a["start_epoch"]:
             continue
-        p = Path(o["path"])
-        if not p.is_file() or p.stat().st_size != o["size"] or p.stat().st_mtime != o["mtime"]:
-            return False
-    return True
+        if not all(search_done(read_json(rec_path(root, s["id"], tool, e)), rec, ctx) for e in ctx.get("engines", ENGINES)):
+            p = Path(o["path"])
+            if not p.is_file() or p.stat().st_size != o["size"] or p.stat().st_mtime != o["mtime"]:
+                continue
+        ready.append(tool)
+    return ready
 
 
 # ------------------------------------------------------------------------------- node: searches
@@ -968,19 +1478,216 @@ def run_search(q, s, tool, engine, pair, tools, env, ctx=None) -> bool:
     return rec["status"] == "ok"
 
 
+def load_module(path, name: str):
+    """A run-local bench tool (bench/entrapment.py, bench/semantic_digest.py) imported as a module: the same code
+    the historical drivers ran, pinned by G-V12 like every other run-local tool."""
+    import importlib.util
+    spec = importlib.util.spec_from_file_location(name, str(path))
+    mod = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(mod)
+    return mod
+
+
+def tsv_iter(tsv: Path, need: set, guard: str):
+    """Header first, then the rows, streamed (a TNBC result TSV holds millions of PSMs)."""
+    import csv
+    with open(tsv, newline="") as f:
+        r = csv.reader(f, delimiter="\t")
+        h = next(r, None)
+        if not h or not need <= set(h):
+            die(guard, "%s lacks columns %s" % (tsv.name, sorted(need - set(h or []))))
+        yield h
+        yield from r
+
+
+def entrap_strata(tsv: Path, est, fasta: str) -> dict:
+    """G-V19: bench/entrapment.py's own estimator (peptide-hypothesis ratio, score() with its bootstrap CI) per charge
+    stratum. score() takes each non-decoy peptide's best PSM by sage_discriminant_score; the same choice puts the
+    peptide in the stratum of that PSM's charge, and each stratum is scored by score() on a TSV of those rows, so
+    z1 + z2p partition the whole-run numbers exactly (checked)."""
+    ratio = est.peptide_ratio(fasta, ENTRAP_TAG)
+    if not ratio > 0:
+        die("G-V19", "the entrapment FASTA has no %s peptides (ratio %s): no entrapment to measure" % (ENTRAP_TAG, ratio))
+    rows = tsv_iter(tsv, {"peptide", "proteins", "charge", "peptide_q", "sage_discriminant_score"}, "G-V19")
+    h = next(rows)
+    ip, ipr, iz, iq, isc = (h.index(k) for k in ("peptide", "proteins", "charge", "peptide_q", "sage_discriminant_score"))
+    best = {}                        # peptide -> (score, charge, line): one joined line per peptide, not a parsed row
+    for row in rows:
+        try:
+            sc, _ = float(row[isc]), float(row[iq])
+        except ValueError:
+            continue
+        prots = [x for x in row[ipr].split(";") if x]
+        if not prots or all(x.startswith("rev_") for x in prots):
+            continue
+        if row[ip] not in best or sc > best[row[ip]][0]:
+            best[row[ip]] = (sc, int(row[iz]), "\t".join(row))
+    out = {"ratio": ratio, "fasta": fasta}
+    with tempfile.TemporaryDirectory() as td:
+        for name, lo, hi in STRATA:
+            part = Path(td) / (name + ".tsv")
+            with open(part, "w") as f:
+                f.write("\t".join(h) + "\n" + "".join(line + "\n" for _, z, line in best.values() if lo <= z <= hi))
+            acc, nt, ne, raw, fdr, lo_ci, hi_ci = est.score(str(part), ENTRAP_TAG, ratio)
+            fin = lambda v: round(v, 4) if v == v else None          # an empty stratum's CI is NaN
+            out[name] = {"accepted": acc, "target": nt, "entrap": ne, "raw_pct": fin(raw), "fdr_pct": fin(fdr),
+                         "ci_pct": [fin(lo_ci), fin(hi_ci)]}
+    for k in ("accepted", "target", "entrap"):
+        if out["z1"][k] + out["z2p"][k] != out["all"][k]:
+            die("G-V19", "charge strata do not partition the run: %s z1 %d + z2p %d != %d"
+                % (k, out["z1"][k], out["z2p"][k], out["all"][k]))
+    if out["all"]["target"] <= 0:
+        die("G-V19", "0 target peptides accepted in the entrapment search: a failed search, never a result")
+    return out
+
+
+def run_entrap(q, s, tool, pair, tools, env, ctx) -> bool:
+    """The entrapment search of one output (engine `entrap`): Sage with the plan's entrapment config on the same input
+    the Sage cell reads (diaTracer patched, cells re-encoded), the same read checks as run_search (G-V10), then
+    entrap_strata (G-V19)."""
+    root, tp = Path(q["root"]), tools["paths"]
+    o = pair["arms"][tool]["output"]
+    mz = Path(o["path"])
+    sdir = root / "runs" / s["id"] / pair["pair_run"] / "search" / ("%s_entrap" % tool)
+    rec = {"kind": "search", "id": s["id"], "tool": tool, "engine": "entrap", "pair_run": pair["pair_run"],
+           "node": hostname(), "tools_sha256": tools["sha256"], "workers": q["search_workers"],
+           "measure_sha256": {k: ctx["measure"].get(k) for k in ("search", "score", "cells")},
+           "java": (ctx["ident"].get("java") or {}).get("version"), "started": now_iso(), "steps": {}, "status": "running"}
+    err = None
+    write_json(rec_path(root, s["id"], tool, "entrap"), rec)
+
+    def step(name, argv, log):
+        tl = Path(argv[3])
+        t = rec["steps"][name] = {"cmd": argv, "start": now_iso(), "start_epoch": time.time()}
+        rc = run_logged(argv, sdir, env, sdir / log)
+        t.update(parse_time_log(tl, "G-V10"), end=now_iso(), end_epoch=time.time(), time_rc=rc)
+        check_exit(t, rc, "G-V10", name)
+        return (sdir / log).read_bytes()
+
+    try:
+        st = mz.stat() if mz.is_file() else None
+        if st is None or st.st_size != o["size"] or st.st_mtime != o["mtime"]:
+            die("G-V11", "extractor output missing or changed since its pair: %s" % mz)
+        check_fasta(tools)
+        shutil.rmtree(sdir, ignore_errors=True)
+        sdir.mkdir(parents=True)
+        n_out = rec["mzml_count"] = o["count"]
+        inp = mz
+        if tool == "dt":
+            inp = sdir / "patched.mzML"
+            step("patch", cmd_patch(tp, mz, inp, sdir / "patch.time"), "patch.log")
+            rec["patched"] = log_count(sdir / "patch.log", rb"patched (\d+) precursor")
+            if rec["patched"] != n_out:
+                die("G-V10", "patch_diatracer_precursor.py patched %s of %d spectra" % (rec["patched"], n_out))
+        log = step("engine", cmd_sage(dict(tp, sage_config=tp["sage_entrap"]), inp, sdir, sdir / "engine.time"), "sage.log")
+        if b"finished in" not in log:
+            die("G-V10", "Sage (entrapment) log lacks 'finished in'")
+        rec["engine_spectra"] = engine_spectra(log, "sage")
+        if rec["engine_spectra"] is None or not SAGE_MIN_READ * n_out <= rec["engine_spectra"] <= n_out:
+            die("G-V10", "Sage (entrapment) searched >= %s spectra of %d written" % (rec["engine_spectra"], n_out))
+        tsv = sdir / "results.sage.tsv"
+        if not tsv.is_file():
+            die("G-V10", "result TSV missing: %s" % tsv)
+        est = load_module(tp["entrapment"], "entrapment_runlocal")
+        rec.update(entrapment=entrap_strata(tsv, est, tp[ENTRAP_DB]), result_tsv=str(tsv))
+        rec["peptides"] = rec["entrapment"]["all"]["target"]
+        rec["status"] = "ok"
+    except Abort as a:
+        rec.update(status="failed", guard=a.guard, message=a.message)
+        err = a
+    except Exception as x:
+        rec.update(status="failed", guard="CRASH", message="%s: %s" % (type(x).__name__, x))
+        err = x
+    except BaseException as x:
+        rec.update(status="failed", guard="KILLED", message="%s during the search" % type(x).__name__)
+        err = x
+    finally:
+        if sdir.is_dir():
+            for junk in list(sdir.glob("*.mzML")) + list(sdir.glob("*.mzBIN*")):
+                junk.unlink()
+        rec["ended"] = now_iso()
+        write_json(rec_path(root, s["id"], tool, "entrap"), rec)
+        say("search %s %s entrap %s" % (s["id"], tool, "ok %d target peptides" % rec["peptides"] if rec["status"] == "ok"
+                                        else "%s [%s] %s" % (rec["status"], rec.get("guard"), rec.get("message"))))
+    if err is not None and (not isinstance(err, Abort) or err.queue):
+        raise err
+    return rec["status"] == "ok"
+
+
+def sage_by_charge(tsv: Path) -> dict:
+    """The corpus-v3 Sage count (sage_peptides: rank 1, peptide_q <= 0.01, target+decoy), each counted peptide put in
+    the stratum of its best counted PSM (highest sage_discriminant_score)."""
+    rows = tsv_iter(tsv, {"peptide", "rank", "peptide_q", "label", "charge", "sage_discriminant_score"}, "G-V19")
+    h = next(rows)
+    ip, ir, iq, il, iz, isc = (h.index(k) for k in ("peptide", "rank", "peptide_q", "label", "charge", "sage_discriminant_score"))
+    best = {}
+    for row in rows:
+        if row[ir] == "1" and float(row[iq]) <= 0.01:
+            sc = float(row[isc])
+            if row[ip] not in best or sc > best[row[ip]][0]:
+                best[row[ip]] = (sc, int(row[iz]), row[il] != "-1")
+    return {name: {"peptides": sum(1 for _, z, _ in best.values() if lo <= z <= hi),
+                   "target_peptides": sum(1 for _, z, t in best.values() if t and lo <= z <= hi)}
+            for name, lo, hi in STRATA}
+
+
+def msf_by_charge(tsv: Path) -> dict:
+    """The corpus-v3 MSFragger count (msf_peptides: best hyperscore per key, deepest prefix with decoy/target <= 1%),
+    each accepted key put in the stratum of its best PSM. Keys are ordered exactly as msf_peptides orders them."""
+    rows = tsv_iter(tsv, {"peptide", "hyperscore", "charge"}, "G-V19")
+    col = {k: i for i, k in enumerate(next(rows))}
+    get = lambda row, k: row[col[k]] if col.get(k, len(row)) < len(row) else ""
+    best = {}
+    for row in rows:
+        key = (get(row, "peptide"), get(row, "modification_info") or get(row, "assigned_modifications"))
+        prots = [x for x in re.split(r"[,;@]", (get(row, "proteins") or get(row, "protein"))) if x]
+        dec = all(x.startswith("rev_") for x in prots)
+        hs = float(get(row, "hyperscore"))
+        if key not in best or hs > best[key][0]:
+            best[key] = (hs, dec, int(get(row, "charge")))
+    t = d = cut = 0
+    ranked = sorted(best.values(), key=lambda v: (v[0], v[1]), reverse=True)
+    for i, (hs, dec, z) in enumerate(ranked):
+        d, t = d + dec, t + (not dec)
+        if t and d / t <= 0.01:
+            cut = i + 1
+    return {name: {"peptides": sum(1 for _, dec, z in ranked[:cut] if not dec and lo <= z <= hi)} for name, lo, hi in STRATA}
+
+
+def add_split(root, sid: str, tool: str, engine: str, ctx: dict) -> bool:
+    """Per-charge split of a finished Sage or MSFragger cell (extended plans), written into its record with the cells
+    hash. The split must add up to the cell's own count (G-V19)."""
+    p = rec_path(root, sid, tool, engine)
+    r = read_json(p)
+    try:
+        by = (sage_by_charge if engine == "sage" else msf_by_charge)(Path(r["result_tsv"]))
+        for k in [k for k in ("peptides", "target_peptides") if k in by["all"]]:
+            if by["z1"][k] + by["z2p"][k] != by["all"][k] or by["all"][k] != r[k]:
+                die("G-V19", "%s %s: charge split %s z1 %d + z2p %d, all %d, counted %d"
+                    % (tool, engine, k, by["z1"][k], by["z2p"][k], by["all"][k], r[k]))
+        r["by_charge"] = by
+        r["measure_sha256"] = dict(r["measure_sha256"], cells=ctx["measure"]["cells"])
+    except Abort as a:
+        r.update(status="failed", guard=a.guard, message=a.message)
+        say("search %s %s %s split failed [%s] %s" % (sid, tool, engine, a.guard, a.message))
+    write_json(p, r)
+    return r["status"] == "ok"
+
+
 def rescore(root, samples: list, ctx: dict) -> int:
     """G-V11 (review F3): a search whose engine run is current but whose peptide rule changed is re-counted from
     its kept result TSV. The engine is not re-run (its mzML may be gone); the record keeps the old counts."""
     n = 0
     for s in samples:
         pair = read_json(rec_path(root, s["id"], "pair"))
-        for tool in TOOLS:
+        for tool in ctx.get("tools", TOOLS):
             for e in ENGINES:
                 p = rec_path(root, s["id"], tool, e)
                 r = read_json(p)
                 m = (r or {}).get("measure_sha256") or {}
                 if not (r and pair and r.get("status") == "ok" and r.get("pair_run") == pair.get("pair_run")
                         and r.get("tools_sha256") == ctx["tools_sha"] and m.get("search") == ctx["measure"]["search"]
+                        and m.get("cells") == ctx["measure"].get("cells")
                         and m.get("score") != ctx["measure"]["score"] and Path(r.get("result_tsv") or "/nonexistent").is_file()):
                     continue
                 keep = {k: r[k] for k in ("peptides", "target_peptides", "diag_decoy_peptides_in_set", "diag_distinct_keys") if k in r}
@@ -993,6 +1700,8 @@ def rescore(root, samples: list, ctx: dict) -> int:
                 except Abort as a:
                     r.update(status="failed", guard=a.guard, message=a.message)
                 write_json(p, r)
+                if "cells" in ctx["measure"] and r["status"] == "ok":      # the split follows the new count
+                    add_split(root, s["id"], tool, e, ctx)
                 say("search %s %s %s re-counted: %s -> %s peptides" % (s["id"], tool, e, keep.get("peptides"), r.get("peptides")))
                 n += 1
     return n
@@ -1011,9 +1720,10 @@ def sweep_outputs(root, samples: list, ctx: dict) -> list:
         pair = read_json(rec_path(root, s["id"], "pair"))
         if not pair or pair.get("status") != "ok":
             continue
-        for tool in TOOLS:
+        for tool in ctx.get("tools", TOOLS):
             o = (pair["arms"].get(tool) or {}).get("output")
-            if o and all(search_done(read_json(rec_path(root, s["id"], tool, e)), pair, ctx) for e in ENGINES):
+            if o and all(search_done(read_json(rec_path(root, s["id"], tool, e)), pair, ctx)
+                         for e in ctx.get("engines", ENGINES)):
                 Path(o["path"]).unlink(missing_ok=True)
     return leftovers(root)
 
@@ -1086,17 +1796,26 @@ def _node_run(q: dict, root: Path) -> int:
         die_queue("G-V14", "leftover staged copies could not be deleted: %s" % (root / "stage"))
     env, removed = arm_env(q)
     runtime = preflight(q, env)
+    ext = extended(q)
+    cenvs = {n: cell_env(q, n) for n in cells(q)}
     ident0 = identity(q, env)
     meta = arm_meta(env, ident0)
+    if cells(q):
+        meta["cells"] = cells_meta(q, cenvs, ident0)
     tools = install_tools(q)
-    ctx = {"ident": ident0, "tools_sha": tools["sha256"], "measure": measure_sha256(), "threads": q["threads"]}
+    ctx = {"ident": ident0, "tools_sha": tools["sha256"], "measure": measure_sha256(ext), "threads": q["threads"]}
+    if ext:
+        ctx.update(tools=list(q_tools(q)), engines=list(q_engines(q)), cells=cells(q))
+    digest = load_module(tools["paths"]["digest"], "semantic_digest_runlocal").digest if cells(q) else None
     meta.update(measure=ctx["measure"], runtime=runtime)
-    patterns = busy_patterns(env)
+    patterns = busy_patterns(env, cenvs)
     say("QUEUE_START plan %s node %s cores %s load %.1f label %s binary %s jar %s java %s harness %s measure %s "
         "samples %d removed %s" % (q["plan"], hostname(), os.cpu_count(), load1(), meta["label"],
                                    ident0["binary_sha256"][:16], ident0["jar_sha256"][:16], runtime["java"]["version"],
                                    q["harness_sha256"][:16], "/".join(v[:8] for v in ctx["measure"].values()),
-                                   len(q["samples"]), removed))
+                                   len(q["samples"]), removed)
+        + ("".join(" cell %s %s %s" % (n, meta["cells"][n]["label"], ident0["cells"][n]["binary_sha256"][:16])
+                   for n in cells(q)) + (" entrapment" if q.get("entrapment") else "") if ext else ""))
     n = rescore(root, q["samples"], ctx)
     if n:
         say("RESCORED %d search cell(s) from their kept result TSVs (peptide rule changed)" % n)
@@ -1106,23 +1825,37 @@ def _node_run(q: dict, root: Path) -> int:
         if pair_done(read_json(rec_path(root, s["id"], "pair")), s, ctx, root):
             say("pair %s already done (record verified): skipped" % s["id"])
             continue
-        failed += not run_pair(q, i, s, env, ident0, meta, removed, patterns)
+        if ext:
+            failed += not run_group(q, i, s, env, ident0, meta, removed, patterns, cenvs, digest)
+        else:
+            failed += not run_pair(q, i, s, env, ident0, meta, removed, patterns)
     say("PHASE1_DONE failed %d" % failed)
     pairs = {s["id"]: read_json(rec_path(root, s["id"], "pair")) for s in q["samples"]}
+    engines = ctx.get("engines", ENGINES)
 
     def pending(s, tool, e):
         return not search_done(read_json(rec_path(root, s["id"], tool, e)), pairs[s["id"]], ctx)
 
+    def one_search(s, tool, e):
+        if e == "entrap":
+            return run_entrap(q, s, tool, pairs[s["id"]], tools, env, ctx)
+        ok = run_search(q, s, tool, e, pairs[s["id"]], tools, env, ctx)
+        return add_split(root, s["id"], tool, e, ctx) if ok and ext else ok
+
     def unit(u):                                      # -> number of failed search cells
         s, tool = u
-        oks = [run_search(q, s, tool, e, pairs[s["id"]], tools, env, ctx) if pending(s, tool, e) else True
-               for e in ENGINES]
-        if all(oks):                                  # both engines succeeded: the mzML goes
+        # a cell's own libraries run its re-encode, never an engine: every search runs in the reference arm's env
+        oks = [one_search(s, tool, e) if pending(s, tool, e) else True for e in engines]
+        if all(oks):                                  # every engine succeeded: the mzML goes
             Path(pairs[s["id"]]["arms"][tool]["output"]["path"]).unlink(missing_ok=True)
         return oks.count(False)
 
-    units = [(s, t) for s in q["samples"] if pair_done(pairs[s["id"]], s, ctx, root)
-             for t in TOOLS if any(pending(s, t, e) for e in ENGINES)]
+    if ext:        # every ok arm of a current group is searched, also when another cell of the group failed
+        units = [(s, t) for s in q["samples"] for t in (ready_arms(pairs[s["id"]], s, ctx, root) or [])
+                 if any(pending(s, t, e) for e in engines)]
+    else:
+        units = [(s, t) for s in q["samples"] if pair_done(pairs[s["id"]], s, ctx, root)
+                 for t in TOOLS if any(pending(s, t, e) for e in ENGINES)]
     rest, msf_ok = [], False
     for u in units:      # alone until one MSFragger search succeeded: a failed first one built no .pepindex (F8)
         if not msf_ok and pending(u[0], u[1], "msfragger"):
@@ -1157,6 +1890,12 @@ def dry_run(q: dict) -> None:
                   % (pre["python"], pre["time"], pre["java"]["version"], pre["java"]["path"]))
         except Abort as a:
             print("# NOTE: a launch would ABORT now: %s" % a)
+    cenvs = {}
+    for n in cells(q):
+        try:
+            cenvs[n] = cell_env(q, n)
+        except Abort as a:
+            print("# NOTE: a launch would ABORT now: %s" % a)
     root, tp = Path(q["root"]), {k: str(v) for k, v in tool_dest(q).items()}
     j = lambda argv: shlex.join(str(x) for x in argv)
     print("# plan %s node %s root %s search_workers %s load gate: 1-min load <= 24 (>=200 cores) else 12, wait %s min "
@@ -1164,13 +1903,25 @@ def dry_run(q: dict) -> None:
           % (q["plan"], q["node"], root, q["search_workers"], q["load_wait_min"], round(MEM_FLOOR * 100)))
     print("# env: unset %s %s and the inherited LD_LIBRARY_PATH; source %s/%s/env.sh; LC_ALL=C TMPDIR=%s"
           % (" ".join(p + "*" for p in STRIP_PREFIX), " ".join(sorted(STRIP_EXACT)), q["spx_root"], q["arm"], q["jnatmp"]))
+    if extended(q):
+        print("# extended plan: cells %s (each: the same env rules on <spx_root>/<cell arm>/env.sh), entrapment %s; "
+              "measurement hashes pair/search/score/cells" % (", ".join("%s=%s" % (n, c["arm"]) for n, c in cells(q).items())
+                                                               or "none", "on" if q.get("entrapment") else "off"))
+    names = list(cells(q))
     for i, s in enumerate(q["samples"]):
         order = list(TOOLS) if i % 2 == 0 else list(reversed(TOOLS))
+        k = i % len(names) if names else 0
+        extra = names[k:] + names[:k]
         d = root / "stage" / ("%s-<pair_run>" % s["id"])
         staged, pdir = d / (s["id"] + ".d"), root / "runs" / s["id"] / "<pair_run>"
-        print("\n## %s  %s  order %s" % (s["id"], s["scheme"], " -> ".join(order)))
-        print("# copy data only, folders 0700 (no modes/ACLs/xattrs), neutral name; pin + acq_min check on the raw, "
-              "pin check on the copy\ncopy %s %s" % (shlex.quote(s["raw"]), shlex.quote(str(staged))))
+        print("\n## %s  %s  order %s" % (s["id"], s["scheme"], " -> ".join(order + extra)))
+        if extended(q):
+            print("# copy %s only into a fresh 0700 directory, neutral name; pin + acq_min check on the raw, pin check on "
+                  "the copy\ncopy %s/{%s} %s" % (" + ".join(STAGE_FILES), shlex.quote(s["raw"]), ",".join(STAGE_FILES),
+                                                shlex.quote(str(staged))))
+        else:
+            print("# copy data only, folders 0700 (no modes/ACLs/xattrs), neutral name; pin + acq_min check on the raw, "
+                  "pin check on the copy\ncopy %s %s" % (shlex.quote(s["raw"]), shlex.quote(str(staged))))
         print("# load gate")
         for tool in order:
             a = pdir / tool
@@ -1181,14 +1932,29 @@ def dry_run(q: dict) -> None:
                       % (q["diatracer_dir"], j(cmd_dt(q, staged, a, a / "time.log")), a / "dt.log"))
             else:
                 print("(cd %s && %s >e.log 2>&1)" % (a, j(cmd_spx(q, spx, staged, a / "pseudo.mzML", a / "time.log"))))
+        for name in extra:
+            c, a = q["cells"][name], pdir / name
+            kind = CELL_KINDS[c["kind"]]
+            b = cenvs[name][kind["bin"]] if name in cenvs else "$" + kind["bin"]
+            print("sync -f %s; %s >/dev/null   # before each arm, outside its timed window"
+                  % (root, j(["cat", staged / "analysis.tdf", staged / "analysis.tdf_bin"])))
+            print("(cd %s && %s >%s 2>&1)   # own session, killed after %s h or when MemAvailable < %d%% (G-V16)"
+                  % (a, j(cmd_dwv(q, b, staged, a, a / "time.log", c["args"])), kind["log"], c["wall_cap_h"],
+                     round(MEM_FLOOR * 100)))
+            print("(cd %s && %s >reencode.log 2>&1 && rm %s)   # G-V17: no numpress term, m/z-sorted, same spectra "
+                  "and RT/precursor values, MS:1000744 everywhere" % (a, j(cmd_reencode(
+                      os.path.join(os.path.dirname(b), REENCODE[0]), a / kind["out"], a / "reencoded.mzML",
+                      a / "reencode.time")), kind["out"]))
+            if c.get("differs_from"):
+                print("# G-V18: flag %s if its content digest equals %s's" % (name, c["differs_from"]))
         print("rm -rf %s" % d)
     print("\n# phase 2 (after every pair of this queue; MSFragger units alone until one MSFragger search succeeded)\n"
           "# checks: patched == spectra; Sage 'finished in' and '- search:' covering %d-100%% of the spectra; "
           "MSFragger 'TOTAL TIME' and Scans == spectra; peptides > 0" % round(SAGE_MIN_READ * 100))
     for s in q["samples"]:
         pdir = root / "runs" / s["id"] / "<pair_run>"
-        for tool in TOOLS:
-            mz = pdir / tool / ("pseudo.mzML" if tool == "spx" else s["id"] + "_diatracer.mzML")
+        for tool in q_tools(q):
+            mz = pdir / tool / {"spx": "pseudo.mzML", "dt": s["id"] + "_diatracer.mzML"}.get(tool, "reencoded.mzML")
             sd = pdir / "search" / ("%s_sage" % tool)
             inp = mz
             if tool == "dt":
@@ -1198,7 +1964,20 @@ def dry_run(q: dict) -> None:
             sd = pdir / "search" / ("%s_msfragger" % tool)
             print("(cd %s && %s && ln -s fixed.mzML in.mzML && %s)"
                   % (sd, j(cmd_fix(tp, mz, sd / "fixed.mzML", sd / "fix.time")), j(cmd_msf(tp, sd / "engine.time"))))
-            print("rm -f %s   # only after both engines succeeded" % mz)
+            if not extended(q):
+                print("rm -f %s   # only after both engines succeeded" % mz)
+                continue
+            print("# G-V19: each Sage/MSFragger count split by the charge of its best PSM (z1, z2p)")
+            if q.get("entrapment"):
+                sd = pdir / "search" / ("%s_entrap" % tool)
+                inp = mz
+                if tool == "dt":
+                    inp = sd / "patched.mzML"
+                    print("(cd %s && %s)" % (sd, j(cmd_patch(tp, mz, inp, sd / "patch.time"))))
+                print("(cd %s && %s)   # then entrapment.py peptide_ratio + score() per stratum %s (G-V19)"
+                      % (sd, j(cmd_sage(dict(tp, sage_config=tp["sage_entrap"]), inp, sd, sd / "engine.time")),
+                         "/".join(n for n, _, _ in STRATA)))
+            print("rm -f %s   # only after every engine succeeded" % mz)
 
 
 def node_status(o: dict) -> dict:
@@ -1230,8 +2009,15 @@ def node_busy(q: dict) -> dict:
     b, pre, err, eg = [], None, None, None
     try:
         env = arm_env(q)[0]
-        b = busy(busy_patterns(env))
+        cenvs = {n: cell_env(q, n) for n in cells(q)}
+        b = busy(busy_patterns(env, cenvs))
         pre = preflight(q, env)
+        if cells(q):              # G-V03 for every cell before a launch: provenance, label, libraries
+            ident = {"cells": cells_identity(q)}
+            pre["cells"] = {n: {"label": m["label"], "arm": q["cells"][n]["arm"],
+                                "binary_sha256": ident["cells"][n]["binary_sha256"],
+                                "reencode_sha256": ident["cells"][n]["reencode_sha256"]}
+                            for n, m in cells_meta(q, cenvs, ident).items()}
     except Abort as a:
         err, eg = a.message, a.guard
     return {"host": hostname(), "load1": load1(), "cores": os.cpu_count(), "busy": b, "preflight": pre,
@@ -1397,6 +2183,8 @@ def node_guardtest(q: dict) -> int:
 def _guardtest(q: dict, root: Path) -> int:
     if "selftest" not in q["plan"]:
         die_queue("G-V01", "guardtest runs for a selftest plan only, never beside a real queue (plan %s)" % q["plan"])
+    if extended(q):
+        die_queue("G-V01", "guardtest covers the two-extractor pair only; plan %s has cells or entrapment" % q["plan"])
     (root / ("runner-%s.pid" % q["nonce"])).write_text("%d\n" % os.getpid())
     gt, s = root / "guardtest" / q["nonce"], q["samples"][0]
     fx = gt / "fixtures"
@@ -1601,9 +2389,11 @@ def load_plan(name: str, reg_path=REG) -> tuple:
     plan = reg.get(name)
     if not isinstance(plan, dict):
         die("G-V01", "no plan section %r in %s" % (name, reg_path))
-    if set(plan) != PLAN_KEYS or not isinstance(plan["tools"], dict) or set(plan["tools"]) != set(TOOL_KEYS):
+    check_extended(name, plan)
+    tk = plan_tool_keys(plan)
+    if set(plan) - OPTIONAL_PLAN_KEYS != PLAN_KEYS or not isinstance(plan["tools"], dict) or set(plan["tools"]) != set(tk):
         die("G-V01", "plan %s: unknown keys %s, missing keys %s (tools need exactly %s)"
-            % (name, sorted(set(plan) - PLAN_KEYS), sorted(PLAN_KEYS - set(plan)), TOOL_KEYS))
+            % (name, sorted(set(plan) - PLAN_KEYS - OPTIONAL_PLAN_KEYS), sorted(PLAN_KEYS - set(plan)), tk))
     seen = {}
     for node, qd in plan["queues"].items():
         if not isinstance(qd, dict) or set(qd) - {"search_workers", "samples"} or not qd.get("samples"):
@@ -1620,8 +2410,8 @@ def load_plan(name: str, reg_path=REG) -> tuple:
             if miss or not str(e["raw"]).endswith(".d"):
                 die("G-V01", "sample %s: missing %s, or raw is not a .d" % (sid, miss))
     db = plan["search_db_sha256"]
-    if not isinstance(db, dict) or set(db) != set(DB_KEYS) or not all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in db.values()):
-        die("G-V01", "plan %s: search_db_sha256 needs exactly %s as sha256 hex" % (name, DB_KEYS))
+    if not isinstance(db, dict) or set(db) != set(db_keys(plan)) or not all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in db.values()):
+        die("G-V01", "plan %s: search_db_sha256 needs exactly %s as sha256 hex" % (name, db_keys(plan)))
     raws, pins = {}, {}
     for sid in seen:              # review F12: a row pasted twice under two ids counts twice in every total
         e = reg["samples"][sid]
@@ -1636,6 +2426,38 @@ def load_plan(name: str, reg_path=REG) -> tuple:
     return plan, reg
 
 
+def check_extended(name: str, plan: dict) -> None:
+    """G-V01 for the optional keys: `entrapment` a boolean; `cells` a mapping of names to exactly CELL_KEYS (plus
+    differs_from naming another cell of the same kind). A cell name is a path component and a record key."""
+    if "entrapment" in plan and not isinstance(plan["entrapment"], bool):
+        die("G-V01", "plan %s: entrapment must be true or false, not %r" % (name, plan["entrapment"]))
+    if "cells" not in plan:
+        return
+    cs = plan["cells"]
+    if not isinstance(cs, dict) or not cs:
+        die("G-V01", "plan %s: cells must be a non-empty mapping of cell name to its settings" % name)
+    for n, c in cs.items():
+        if not isinstance(n, str) or not re.fullmatch(CELL_NAME, n) or n in TOOLS + ENGINES + ("entrap", "pair", "search"):
+            die("G-V01", "plan %s: cell name %r must match %s and not be a reserved name" % (name, n, CELL_NAME))
+        if not isinstance(c, dict) or not CELL_KEYS <= set(c) <= CELL_KEYS | {"differs_from"}:
+            die("G-V01", "cell %s: needs exactly %s (and optionally differs_from), got %s"
+                % (n, sorted(CELL_KEYS), sorted(c) if isinstance(c, dict) else c))
+        if c["kind"] not in CELL_KINDS:
+            die("G-V01", "cell %s: unknown kind %r (known: %s)" % (n, c["kind"], sorted(CELL_KINDS)))
+        if not isinstance(c["arm"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", c["arm"]):
+            die("G-V01", "cell %s: arm %r is not a directory name under spx_root" % (n, c["arm"]))
+        if not isinstance(c["args"], list) or not all(isinstance(a, str) for a in c["args"]) \
+                or set(c["args"]) & {"-in", "-out", "-threads", "-ini"}:
+            die("G-V01", "cell %s: args must be a list of strings without -in/-out/-threads/-ini (the harness sets "
+                         "those): %r" % (n, c["args"]))
+        if type(c["wall_cap_h"]) not in (int, float) or not 0 < c["wall_cap_h"] <= 72:
+            die("G-V01", "cell %s: wall_cap_h must be a number in (0, 72], got %r" % (n, c["wall_cap_h"]))
+        ref = c.get("differs_from", n)
+        if "differs_from" in c and (ref == n or ref not in cs or not isinstance(cs[ref], dict)
+                                    or cs[ref].get("kind") != c["kind"]):
+            die("G-V01", "cell %s: differs_from %r must name another cell of kind %s" % (n, ref, c["kind"]))
+
+
 def lock_path(plan: dict) -> str:
     return str(Path(plan["scratch_root"]).parent / ".corpus-queue.lock")   # node-wide: one queue per node
 
@@ -1649,6 +2471,7 @@ def resolve_queue(name: str, plan: dict, reg: dict, node: str) -> dict:
         die("G-V01", "plan %s has no queue for node %s" % (name, node))
     qd = plan["queues"][node]
     q = {k: plan[k] for k in PLAN_KEYS if k != "queues"}
+    q.update({k: plan[k] for k in OPTIONAL_PLAN_KEYS if k in plan})
     q.update(plan=name, node=node, nonce=time.strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex(),
              root=node_root(plan, node), lock=lock_path(plan), harness_sha256=sha256(SELF),
              search_workers=int(qd.get("search_workers", 1)),
@@ -1779,27 +2602,31 @@ def cmd_guardtest(args) -> int:
 
 def cmd_status(args) -> int:
     plan, _ = load_plan(args.plan)
-    cols = ["pair"] + ["%s.%s" % (t, e) for t in TOOLS for e in ENGINES]
+    cols = ["pair"] + ["%s.%s" % (t, e) for t in q_tools(plan) for e in q_engines(plan)]
+    wd = max([15] + [len(c) + 1 for c in cols])
     for node in [args.node] if args.node else list(plan["queues"]):
         s = remote(node, "node-status", {"root": node_root(plan, node), "lock": lock_path(plan)})
         print("\n== %s (host %s) load %.1f  lock %s  stage leftovers %s"
               % (node, s["host"], s["load1"], "HELD " + s["lock_info"] if s["lock_held"] else "free", s["stage_left"] or "none"))
         recs = {(r["id"], "pair" if r["kind"] == "pair" else "%s.%s" % (r["tool"], r["engine"])): r for r in s["records"]}
-        print("%-10s " % "sample" + " ".join("%-15s" % c for c in cols))
+        print("%-10s " % "sample" + " ".join("%-*s" % (wd, c) for c in cols))
         for sid in plan["queues"][node]["samples"]:
-            pair, cells = recs.get((sid, "pair")), []
+            pair, row = recs.get((sid, "pair")), []
             for c in cols:
                 r = recs.get((sid, c))
                 if r is None:
-                    cells.append("-")
+                    row.append("-")
                 elif r["status"] != "ok":
-                    cells.append("%s %s" % (r["status"], r.get("guard", "")))
+                    row.append("%s %s" % (r["status"], r.get("guard", "")))
                 elif c == "pair":
-                    cells.append("ok")
+                    row.append("ok" if not r.get("cells_failed") else "ok, %d failed" % len(r["cells_failed"]))
                 else:
-                    cells.append("ok %s" % r["peptides"] if pair and r["pair_run"] == pair["pair_run"] else "stale")
-            fl = pair_flags(pair) if pair else "-"
-            print("%-10s " % sid + " ".join("%-15s" % c for c in cells) + ("" if fl == "-" else "  " + fl))
+                    row.append("ok %s" % r["peptides"] if pair and r["pair_run"] == pair["pair_run"] else "stale")
+            fl = group_flags(pair) if pair else "-"
+            print("%-10s " % sid + " ".join("%-*s" % (wd, c) for c in row) + ("" if fl == "-" else "  " + fl))
+            for n in (pair or {}).get("cells_failed") or []:
+                a = pair["arms"][n]
+                print("  cell %s FAILED [%s] %s" % (n, a.get("guard"), a.get("message")))
         if s.get("mzml_left"):
             print("  mzML/mzBIN under runs/: %d (%s)" % (len(s["mzml_left"]), ", ".join(s["mzml_left"][:4])))
         for line in s["log_tail"][-6:]:
@@ -1839,6 +2666,11 @@ def cmd_preflight(args) -> int:
         print("   python %s, %s is GNU time, java %s (%s), sage_fasta %s, msfragger_db %s" % (
             pre["python"], pre["time"], pre["java"]["version"], pre["java"]["path"],
             pre["search_db"]["sage_fasta"]["sha256"][:16], pre["search_db"]["msfragger_db"]["sha256"][:16]))
+        for n, c in (pre.get("cells") or {}).items():
+            print("   cell %s: %s, arm %s, binary %s, %s %s" % (n, c["label"], c["arm"], c["binary_sha256"][:16],
+                                                           REENCODE[0], c["reencode_sha256"][:16]))
+        if ENTRAP_DB in pre["search_db"]:
+            print("   entrap_fasta %s" % pre["search_db"][ENTRAP_DB]["sha256"][:16])
         majors[node] = pre["java"]["major"]
         bad += bool(b["busy"] or b["lock_held"])
     if len(set(majors.values())) > 1:
@@ -1854,7 +2686,7 @@ def cmd_table(args) -> int:
         key = "scratch_root" if args.source == "scratch" else "results_ceph"
         got = remote(node, "node-status", {"root": node_root(plan, node, key), "records_only": True})["records"]
         recs += [r for r in got if r["id"] in qd["samples"]]
-    md, incomplete, total = render_table(args.plan, plan, reg, recs, args.source)
+    md, incomplete, total = (render_cells_table if extended(plan) else render_table)(args.plan, plan, reg, recs, args.source)
     out = Path(args.out) if args.out else REPO / plan["report"]
     out.parent.mkdir(parents=True, exist_ok=True)
     out.write_text(md)
@@ -1875,7 +2707,21 @@ def pair_flags(p: dict, names=None) -> str:
             continue
         du = a.get("during") or {"contended": True, "why": ["contention not measured"]}
         if du.get("contended"):
-            out.append("during %s: %s" % (names[t], "; ".join(du.get("why") or ["?"])))
+            out.append("during %s: %s" % (names.get(t, t), "; ".join(du.get("why") or ["?"])))
+    return "; ".join(out) or "-"
+
+
+def noop_flag(a: dict) -> str:
+    nz = a.get("noop") or {}
+    if not nz.get("flag"):
+        return ""
+    return "no-op: content equal to %s" % nz["vs"] if nz.get("computed") else "no-op check impossible: %s" % nz.get("why")
+
+
+def group_flags(p: dict, names=None) -> str:
+    """pair_flags plus the G-V18 no-op flags of an extended group."""
+    out = [f for f in [pair_flags(p, names)] if f != "-"]
+    out += ["%s %s" % (n, noop_flag(a)) for n, a in (p.get("arms") or {}).items() if noop_flag(a)]
     return "; ".join(out) or "-"
 
 
@@ -1887,14 +2733,13 @@ def search_overlaps(recs: list) -> set:
     return {k1 for n1, k1, a1, b1 in steps for n2, k2, a2, b2 in steps if k1 != k2 and n1 == n2 and a1 < b2 and a2 < b1}
 
 
-def render_table(name, plan, reg, recs, source="scratch") -> tuple:
-    pairs = {r["id"]: r for r in recs if r["kind"] == "pair"}
-    srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r["kind"] == "search"}
-    okp = [p for p in pairs.values() if p["status"] == "ok"]
-    oks = [r for r in srch.values() if r["status"] == "ok"]
+def table_guards(okp: list, oks: list, reg: dict, plan: dict) -> None:
+    """G-V13 over the ok pair/group and search records of one table."""
     one = lambda xs: len({json.dumps(x, sort_keys=True) for x in xs}) <= 1
     if not one(build_identity(p["identity"]) for p in okp) or not one(p["label"] for p in okp):
         die("G-V13", "records come from more than one binary/lib/jar: one table, one build")
+    if not one({n: m.get("label") for n, m in (p.get("cells_meta") or {}).items()} for p in okp):
+        die("G-V13", "cell records carry more than one tool label: one table, one build")
     if not one(java_major(p["identity"]) for p in okp):
         die("G-V13", "pair records ran on different Java feature versions: %s" % sorted({str(java_major(p["identity"])) for p in okp}))
     if any(not (p.get("measure_sha256") or {}).get("pair") for p in okp) or not one(p["measure_sha256"] for p in okp) \
@@ -1905,17 +2750,28 @@ def render_table(name, plan, reg, recs, source="scratch") -> tuple:
     if any(not (r.get("measure_sha256") or {}).get("search") for r in oks) or not one(r["measure_sha256"] for r in oks):
         die("G-V13", "search records run or counted by different harness code (or without measurement hashes)")
     for p in okp:
-        if {a["host"] for a in p["arms"].values()} != {p["node"]}:
+        arms = [a for a in p["arms"].values() if a.get("status", "ok") == "ok"]
+        if {a["host"] for a in p["arms"].values() if "host" in a} != {p["node"]}:
             die("G-V13", "pair %s: arms on %s, record node %s" % (p["id"], sorted(a["host"] for a in p["arms"].values()), p["node"]))
         e = reg["samples"].get(p["id"]) or {}
         if e.get("pin") != p["sample"]["pin"] or p["sample"].get("raw_sha256") != hashlib.sha256(str(e.get("raw")).encode()).hexdigest():
             die("G-V13", "pair %s: record pin or raw path differs from samples.yaml" % p["id"])
-        if any(a["output"]["count"] <= 0 or a["peak_rss_kb"] <= 0 for a in p["arms"].values()):
+        if any(a["output"]["count"] <= 0 or a["peak_rss_kb"] <= 0 for a in arms):
             die("G-V13", "pair %s: ok record with a spectrum count or RSS <= 0" % p["id"])
+        if p.get("cells") != plan.get("cells") or bool(p.get("entrapment")) != bool(plan.get("entrapment")):
+            die("G-V13", "pair %s: record cells or entrapment differ from the plan" % p["id"])
     for r in oks:
         if r.get("peptides", 0) <= 0:
             die("G-V13", "search %s %s %s: ok record with %s peptides" % (r["id"], r["tool"], r["engine"], r.get("peptides")))
 
+
+def render_table(name, plan, reg, recs, source="scratch") -> tuple:
+    pairs = {r["id"]: r for r in recs if r["kind"] == "pair"}
+    srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r["kind"] == "search"}
+    okp = [p for p in pairs.values() if p["status"] == "ok"]
+    oks = [r for r in srch.values() if r["status"] == "ok"]
+    table_guards(okp, oks, reg, plan)
+
     def verdict(r):
         return "running" if r["status"] == "running" else "FAILED %s" % r.get("guard")
 
@@ -2058,6 +2914,198 @@ during an arm).
     return head + "\n".join(lines) + "\n" + tail + "\n".join(summary) + "\n", len(ids) - len(full), len(ids)
 
 
+def render_cells_table(name, plan, reg, recs, source="scratch") -> tuple:
+    """`table` for an extended plan: one row per (sample, arm) with ratios against diaTracer, the per-charge split,
+    entrapment by stratum, cell output statistics, and totals per arm over complete groups (every arm and search ok)."""
+    pairs = {r["id"]: r for r in recs if r["kind"] == "pair"}
+    srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r["kind"] == "search"}
+    okp = [p for p in pairs.values() if p["status"] == "ok"]
+    oks = [r for r in srch.values() if r["status"] == "ok"]
+    table_guards(okp, oks, reg, plan)
+    tools, engines = list(q_tools(plan)), list(q_engines(plan))
+    label = okp[0]["label"] if okp else "extractor"
+    dtl = Path(plan["diatracer_jar"]).stem
+    names = dict({"dt": dtl, "spx": label}, **{n: n for n in cells(plan)})
+    ids = [sid for sid in reg["samples"] if any(sid in qd["samples"] for qd in plan["queues"].values())]
+    verdict = lambda r: "running" if r["status"] == "running" else "FAILED %s" % r.get("guard")
+    fmt = lambda x, f: f(x[0]) if x[0] else x[1]
+    num = lambda v: "{:,}".format(v) if v is not None else "-"
+    pct = lambda v: "%.2f" % v if v is not None else "-"
+
+    def arm(sid, t):
+        p = pairs.get(sid)
+        if not p:
+            return None, "pending"
+        if p["status"] != "ok":
+            return None, verdict(p)
+        a = p["arms"].get(t) or {}
+        return (a, None) if a.get("status", "ok") == "ok" and a.get("output") else (None, "FAILED %s" % a.get("guard"))
+
+    def search(sid, t, e):
+        p, r = pairs.get(sid), srch.get((sid, t, e))
+        if not arm(sid, t)[0]:
+            return None, "-"
+        if not r or r["pair_run"] != p["pair_run"]:
+            return None, "pending"
+        return (r, None) if r["status"] == "ok" else (None, verdict(r))
+
+    def flags(p, t):
+        out, g, a = [], p.get("gate") or {}, p["arms"].get(t) or {}
+        if g.get("contended"):
+            out.append("gate: load %.1f > %.0f%s" % (g["load"], g["load_max"], ", busy" if g.get("busy") else ""))
+        if a and (a.get("status", "ok") == "ok" or "during" in a):
+            du = a.get("during") or {"contended": True, "why": ["contention not measured"]}
+            if du.get("contended"):
+                out.append("during: " + "; ".join(du.get("why") or ["?"]))
+        return "; ".join(out + [f for f in [noop_flag(a)] if f]) or "-"
+
+    main, charge, entrap, cellrows, full = [], [], [], [], {}
+    for sid in ids:
+        e, p = reg["samples"][sid], pairs.get(sid)
+        S = {(t, g): search(sid, t, g) for t in tools for g in engines}
+        A = {t: arm(sid, t) for t in tools}
+        complete = all(A[t][0] for t in tools) and all(v[0] for v in S.values())
+        for t in tools:
+            a = A[t]
+            ratio = lambda g: "%.2f" % (S[t, g][0]["peptides"] / S["dt", g][0]["peptides"]) \
+                if t != "dt" and S[t, g][0] and S["dt", g][0] else "-"
+            swall = lambda g: fmt(S[t, g], lambda r: hms(r["steps"]["engine"]["wall_s"]))
+            cores = lambda x: "%.1f" % (x["cpu"]["cpu_s"] / x["wall_s"]) if (x.get("cpu") or {}).get("cpu_s") is not None and x["wall_s"] > 0 else "-"
+            main.append("| " + " | ".join([
+                str(e.get("label", sid)), "%.1f" % e["acq_min"], p["node"] if p else "-", names[t], flags(p, t) if p else "-",
+                fmt(a, lambda x: hms(x["wall_s"])), fmt(a, lambda x: "%.1f" % (x["peak_rss_kb"] / 1e6)), fmt(a, cores),
+                fmt(a, lambda x: num(x["output"]["count"])),
+                fmt(S[t, "sage"], lambda r: num(r["peptides"])), fmt(S[t, "sage"], lambda r: num(r.get("target_peptides"))),
+                ratio("sage"), fmt(S[t, "msfragger"], lambda r: num(r["peptides"])), ratio("msfragger"),
+                swall("sage"), swall("msfragger")]) + " |")
+            bc = lambda g, z, k="peptides": fmt(S[t, g], lambda r: num(((r.get("by_charge") or {}).get(z) or {}).get(k)))
+            charge.append("| " + " | ".join([str(e.get("label", sid)), names[t], bc("sage", "z1"), bc("sage", "z2p"),
+                                             bc("sage", "z1", "target_peptides"), bc("sage", "z2p", "target_peptides"),
+                                             bc("msfragger", "z1"), bc("msfragger", "z2p")]) + " |")
+            if plan.get("entrapment"):
+                r, v = S[t, "entrap"]
+                for st, _, _ in STRATA:
+                    x = (r or {}).get("entrapment", {}).get(st) or {}
+                    ci = x.get("ci_pct") or [None, None]
+                    entrap.append("| " + " | ".join([str(e.get("label", sid)), names[t], st] + (
+                        [num(x.get("accepted")), num(x.get("target")), num(x.get("entrap")), pct(x.get("raw_pct")),
+                         pct(x.get("fdr_pct")), "%s-%s" % (pct(ci[0]), pct(ci[1]))] if r else [v] * 6)) + " |")
+            if t in cells(plan):
+                c, x = plan["cells"][t], p["arms"].get(t) if p else None
+                st = (x or {}).get("spectra_stats") or {}
+                n = st.get("spectra") or 0
+                cellrows.append("| " + " | ".join([
+                    str(e.get("label", sid)), t, c["arm"], "`%s`" % (" ".join(c["args"]) or "defaults"),
+                    fmt(a, lambda y: num(y["output"]["count"])),
+                    ", ".join("z%s %s" % (z, num(k)) for z, k in sorted(st.get("charges", {}).items())) or "-",
+                    "%.1f%%" % (100.0 * st["im_zero"] / n) if n else "-", num(st.get("im_missing")) if n else "-",
+                    str(st.get("peaks_median", "-")) if n else "-",
+                    fmt(a, lambda y: hms(y["reencode"]["wall_s"])),
+                    fmt(a, lambda y: "%d / %d" % (y["spectra_stats"]["numpress_terms"], y["reencoded_stats"]["numpress_terms"])),
+                    fmt(a, lambda y: "`%s` / `%s`" % (y["digests"]["semantic"][:12], y["digests"]["content"][:12])),
+                    (noop_flag(x or {}) or ("differs from %s" % c["differs_from"] if (x or {}).get("noop") else "-"))
+                    if c.get("differs_from") else "-"]) + " |")
+        if complete:
+            full[sid] = {"flagged": any(flags(p, t) != "-" for t in tools), "arms": {t: A[t][0] for t in tools},
+                         "search": {k: v[0] for k, v in S.items()}}
+    summary = []
+    tot = lambda f: sum(f(g) for g in full.values())
+    for t in tools:
+        if not full:
+            break
+        sage, msf = tot(lambda g: g["search"][t, "sage"]["peptides"]), tot(lambda g: g["search"][t, "msfragger"]["peptides"])
+        s_z2 = tot(lambda g: g["search"][t, "sage"]["by_charge"]["z2p"]["target_peptides"])
+        m_z2 = tot(lambda g: g["search"][t, "msfragger"]["by_charge"]["z2p"]["peptides"])
+        d_s = tot(lambda g: g["search"]["dt", "sage"]["peptides"])
+        d_m = tot(lambda g: g["search"]["dt", "msfragger"]["peptides"])
+        d_sz2 = tot(lambda g: g["search"]["dt", "sage"]["by_charge"]["z2p"]["target_peptides"])
+        d_mz2 = tot(lambda g: g["search"]["dt", "msfragger"]["by_charge"]["z2p"]["peptides"])
+        rows = [g["arms"][t] for g in full.values()]
+        summary.append("| %s | %d | %d/%d | %s | %.1f | %s | %.2f | %s | %.2f | %s | %.2f | %s | %.2f |" % (
+            names[t], len(full), sum(g["flagged"] for g in full.values()), len(full), hms(sum(a["wall_s"] for a in rows)),
+            statistics.median(a["peak_rss_kb"] for a in rows) / 1e6, num(sum(a["output"]["count"] for a in rows)),
+            sage / d_s, num(s_z2), s_z2 / d_sz2 if d_sz2 else float("nan"), num(msf), msf / d_m, num(m_z2),
+            m_z2 / d_mz2 if d_mz2 else float("nan")))
+    ident = okp[0]["identity"] if okp else {}
+    cm = okp[0].get("cells_meta", {}) if okp else {}
+    tsha = oks[0]["tools_sha256"] if oks else {}
+    pm = okp[0]["measure_sha256"] if okp else {}
+    sh = lambda v: (v or "?")[:16]
+    cell_lines = "".join(
+        "\n- **%s** (%s, arm `%s`): %s; binary sha256 `%s`, %s sha256 `%s`, %d lib files, %d ceph-resident libraries; "
+        "%s; `-in <staged .d> -out <cell dir> -threads %s%s`, wall cap %s h, killed when MemAvailable < %d%%."
+        % (n, c["kind"], c["arm"], (cm.get(n) or {}).get("label", "?"), sh(((ident.get("cells") or {}).get(n) or {}).get("binary_sha256")),
+           REENCODE[0], sh(((ident.get("cells") or {}).get(n) or {}).get("reencode_sha256")),
+           len(((ident.get("cells") or {}).get(n) or {}).get("lib_sha256") or {}),
+           len(build_identity(ident).get("cells", {}).get(n, {}).get("deps_sha256", {})) if ident.get("cells") else 0,
+           ", ".join(l for l in (cm.get(n) or {}).get("provenance", []) if l.startswith(("git_sha=", "published=", "compiler=")))
+           or "no git_sha/published line",
+           plan["threads"], "".join(" " + x for x in c["args"]), c["wall_cap_h"], round(MEM_FLOOR * 100))
+        for n, c in cells(plan).items())
+    head = """# Extractor comparison: %(dtl)s, %(label)s and %(cells)s
+
+Generated %(now)s by `harness/corpus.py table` (plan `%(name)s`, records from %(source)s). **n = 1 per cell.** %(full)d of
+%(ids)d samples complete (every arm and every search ok).
+
+- **%(label)s**: SPX_BIN sha256 `%(bin)s`; `-in <staged .d> -out pseudo.mzML -threads %(threads)s`, defaults only.
+- **%(dtl)s**: jar sha256 `%(jar)s`; the corpus-v3 invocation (`-Xmx400G`, every option passed: `%(dtparams)s`).%(cell_lines)s
+- **Order and timing**: per sample, one staged copy, the reference pair first (order alternating by queue index), then
+  the cells in plan order (rotated by queue index); every arm synced and pre-warmed outside its timed window; wall,
+  peak RSS and CPU from GNU `time -v` (CPU cores = (user + system) / wall). RSS GB = kbytes / 1e6. Compare walls
+  within one sample only. A failed cell does not stop the next one; a group with a failed cell re-runs whole.
+- **Re-encode** (cells, before any search, outside the timed window): `%(reencode)s -in pseudo_spectra.mzML -out
+  reencoded.mzML %(reargs)s` from the cell's own build. Checked: no numpress term (MS:1002312/13/14, MS:1002746/47/48),
+  every m/z array sorted, the same spectra, the same RT, selected ion m/z, charge, 1/K0 and isolation target values,
+  a selected ion m/z in every spectrum. Searches read the re-encoded file; no selected-ion patch for cells.
+- **No-op check** (G-V18): a cell with `differs_from` is flagged when its order-independent content digest (each
+  spectrum block without id/index, sorted) equals that cell's. The spectrum-list digest (bench/semantic_digest.py) is
+  shown beside it; diaWeaver's final RT sort is unstable, so that digest can differ between two runs of one arm.
+- **Searches**: Sage `%(sage)s` (config `%(sage_config)s`, FASTA `%(sage_fasta)s`), MSFragger `%(msf)s` (params
+  `%(msf_params)s`, database `%(msf_db)s`); diaTracer patched before Sage; `fix_mzml_cvparams.py` before MSFragger for
+  every arm; the corpus-v3 read checks (patched = spectra, MSFragger Scans = spectra, Sage >= %(minread)d%% of them).
+- **Peptides at 1%%**: the corpus-v3 rules. Sage = distinct peptides with rank 1 and peptide_q <= 0.01,
+  **target+decoy** (target-only beside it); MSFragger = best hyperscore per (peptide, modification_info), deepest
+  prefix with decoy/target <= 1%%, targets. Ratios are arm / %(dtl)s.
+- **Per charge**: each counted peptide in the stratum of its best counted PSM (Sage: highest
+  sage_discriminant_score; MSFragger: the best-hyperscore PSM of its key); z1 + z2p equals the count (checked).
+%(entrap_line)s- **Measurement code**: pair `%(mpair)s`, search `%(msearch)s`, peptide rule `%(mscore)s`, cells `%(mcells)s`.
+- `FAILED G-Vxx` = a guard refused the cell (never a zero); `pending` = no current record; `-` = no arm or search.
+
+| sample | acq min | node | arm | flags | wall | RSS GB | CPU cores | spectra | Sage | Sage target | Sage vs dT | MSFragger | MSFragger vs dT | Sage wall | MSFragger wall |
+|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
+""" % {"dtl": dtl, "label": label, "cells": ", ".join(cells(plan)) or "no cells", "now": now_iso(), "name": name,
+       "source": source, "full": len(full), "ids": len(ids), "bin": sh(ident.get("binary_sha256")), "threads": plan["threads"],
+       "jar": sh(ident.get("jar_sha256")), "dtparams": " ".join(DT_PARAMS), "cell_lines": cell_lines,
+       "reencode": REENCODE[0], "reargs": " ".join(REENCODE[1]), "minread": round(SAGE_MIN_READ * 100),
+       "sage": sh(tsha.get("sage")), "sage_config": sh(tsha.get("sage_config")), "sage_fasta": sh(tsha.get("sage_fasta")),
+       "msf": sh(tsha.get("msfragger_jar")), "msf_params": sh(tsha.get("msfragger_params")), "msf_db": sh(tsha.get("msfragger_db")),
+       "entrap_line": ("- **Entrapment**: Sage with `%s` (sha256 `%s`, FASTA `%s`), estimator `bench/entrapment.py` (sha256 `%s`): "
+                       "peptide-hypothesis ratio, est. FDR = (entrapment / ratio) / target, 95%% bootstrap CI. Strata as for "
+                       "the peptides (each peptide in the stratum of its best non-decoy PSM), scored by the estimator itself; "
+                       "z1 + z2p equals all (checked). Never quote the `all` row without the strata.\n"
+                       % (Path(plan["tools"]["sage_entrap"]).name, sh(tsha.get("sage_entrap")), sh(tsha.get(ENTRAP_DB)),
+                          sh(tsha.get("entrapment")))) if plan.get("entrapment") else "",
+       "mpair": str(pm.get("pair"))[:12], "msearch": str(pm.get("search"))[:12], "mscore": str(pm.get("score"))[:12],
+       "mcells": str(pm.get("cells"))[:12]}
+    parts = [head + "\n".join(main) + "\n",
+             "\n## Peptides by precursor charge\n\n| sample | arm | Sage z=1 | Sage z>=2 | Sage target z=1 | Sage target z>=2 "
+             "| MSFragger z=1 | MSFragger z>=2 |\n|---|---|---:|---:|---:|---:|---:|---:|\n" + "\n".join(charge) + "\n"]
+    if plan.get("entrapment"):
+        parts.append("\n## Entrapment by charge stratum (Sage, nominal peptide_q <= 0.01)\n\n| sample | arm | stratum | accepted "
+                     "| target | entrapment | raw % | est. FDR % | 95% CI |\n|---|---|---|---:|---:|---:|---:|---:|---:|\n"
+                     + "\n".join(entrap) + "\n")
+    if cells(plan):
+        parts.append("\n## Cell outputs (before the re-encode unless noted)\n\n| sample | cell | cell arm | args | spectra "
+                     "| charges | 1/K0 = 0 | 1/K0 missing | peaks per spectrum (median) | re-encode wall | numpress terms "
+                     "(raw / re-encoded) | spectrum-list / content digest (re-encoded) | no-op check |\n"
+                     "|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---|---|\n" + "\n".join(cellrows) + "\n")
+    parts.append("\n## Per arm, complete samples only\n\n| arm | n | flagged | wall total | median RSS GB | spectra | Sage vs dT "
+                 "| Sage target z>=2 | Sage target z>=2 vs dT | MSFragger | MSFragger vs dT | MSFragger z>=2 "
+                 "| MSFragger z>=2 vs dT |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
+                 + "\n".join(summary) + "\n")
+    return "".join(parts), len(ids) - len(full), len(ids)
+
+
 # ------------------------------------------------------------------------------- measurement code identity
 # G-V11/G-V13 (review F3): a record counts only for the code that measured it. Function sources (comments included)
 # and the constants they use, captured at import: a selftest monkeypatch of a global cannot change them. A change to
@@ -2073,9 +3121,21 @@ MEASURED = {
 }
 
 
-def measure_sha256() -> dict:
+# Extended plans only (plan keys `cells`, `entrapment`): the group runner, the cells, the re-encode, the entrapment search
+# and the per-charge split. A change here re-runs the groups and searches of extended plans and nothing else.
+MEASURED_CELLS = (sorted(CELL_KINDS.items()), REENCODE, NUMPRESS_CV, PREC_CV, ENTRAP_TAG, STRATA, STAGE_FILES, stage_tdf,
+                  cell_env, cmd_dwv,
+                  cmd_reencode, kill_session, run_capped, time_cpu, mzml_scan, reencode, run_cell, noop_check, run_group,
+                  load_module, tsv_iter, entrap_strata, run_entrap, sage_by_charge, msf_by_charge, add_split)
+# The two-extractor pair as of DIAspeXtract 1.3.0 (CORPUS.md). selftest asserts these: an edit to a measured function
+# must change them here on purpose, knowing that every record of a plain plan then re-runs.
+PAIR_MEASURE_1_3_0 = {"pair": "3215b73e62ae", "search": "064af71b2bfe", "score": "4fe0a1cecefb"}
+
+
+def measure_sha256(extended=False) -> dict:
+    parts = dict(MEASURED, cells=MEASURED_CELLS) if extended else MEASURED
     out = {}
-    for part, items in MEASURED.items():
+    for part, items in parts.items():
         h = hashlib.sha256()
         for x in items:
             h.update((inspect.getsource(x) if callable(x) else repr(x)).encode())
@@ -2106,6 +3166,7 @@ out=$3; shift 3
 { echo "Command being timed: \"$*\""
   echo "Elapsed (wall clock) time (h:mm:ss or m:ss): 1:02.50"
   echo "Maximum resident set size (kbytes): 2500000"
+  echo "User time (seconds): 100.00"; echo "System time (seconds): 25.00"; echo "Percent of CPU this job got: 200%"
   if [ $rc -gt 128 ]; then echo "Command terminated by signal $((rc - 128))"; st=0; fi   # as GNU time reports it
   if [ -n "${FAKE_SIGNAL_FOR:-}" ] && [[ "$*" == *"$FAKE_SIGNAL_FOR"* ]]; then echo "Command terminated by signal 7"; fi
   echo "Exit status: $st"; } > "$out"
@@ -2139,9 +3200,10 @@ else:
     t0 = time.time()
     time.sleep(float(os.environ.get("FAKE_MSF_SLEEP", "0")))
     with open("in.tsv", "w") as f:
-        f.write("scannum\tpeptide\tproteins\tmodification_info\thyperscore\n")
-        f.write("".join("%d\tPEP%d\tsp|P%d|X_HUMAN desc, with comma\t\t%d\n" % (i, i, i, 200 - i) for i in range(150)))
-        f.write("0\tREVPEP\trev_sp|Q1|Y_HUMAN decoy\t\t1\n")
+        f.write("scannum\tpeptide\tproteins\tmodification_info\thyperscore\tcharge\n")
+        f.write("".join("%d\tPEP%d\tsp|P%d|X_HUMAN desc, with comma\t\t%d\t%d\n" % (i, i, i, 200 - i, 1 if i % 10 == 0 else 2)
+                        for i in range(150)))
+        f.write("0\tREVPEP\trev_sp|Q1|Y_HUMAN decoy\t\t1\t2\n")
     open("in_uncalibrated.mzBIN", "w").write("x")
     with open(os.environ["FAKE_MSF_TIMES"], "a") as f:
         f.write("%f %f\n" % (t0, time.time()))
@@ -2154,15 +3216,118 @@ FAKE_SAGE = FAKE_HEAD + r'''
 odir, mz = arg("-o"), sys.argv[-1]
 assert os.path.exists(mz), mz
 zero = hit("FAKE_SAGE_ZERO", mz)
-rows = "".join("%d\tPEPTIDE%d\tsp|P%d|X\t1\tf.mzML\t%d\t1\t1\t%s\n" % (i, i, i, i, "0.5" if zero else "0.001") for i in range(30))
+rows = "".join("%d\tPEPTIDE%d\tsp|P%d|X\t1\tf.mzML\t%d\t1\t1\t%s\t%d\t%.2f\n"
+               % (i, i, i, i, "0.5" if zero else "0.001", 1 if i % 5 == 0 else 2, 1 - i / 100) for i in range(30))
 if not zero:
-    rows += "99\tDECOYPEP\trev_sp|P1|X\t1\tf.mzML\t99\t1\t-1\t0.001\n"
+    rows += "99\tDECOYPEP\trev_sp|P1|X\t1\tf.mzML\t99\t1\t-1\t0.001\t2\t0.1\n"
+if "entrap" in sys.argv[1]:           # the entrapment config: foreign-proteome hits (one at z=1), and a weaker duplicate
+    rows += "".join("%d\tENTRAPPEP%d\tENTRAP_sp|A%d|ARATH\t1\tf.mzML\t%d\t1\t1\t0.001\t%d\t0.5\n"
+                    % (200 + i, i, i, 200 + i, 1 if i == 0 else 2) for i in range(3))
+    rows += "300\tPEPTIDE1\tsp|P1|X\t1\tf.mzML\t300\t1\t1\t0.001\t1\t0.01\n"
+hdr = "psm_id\tpeptide\tproteins\tnum_proteins\tfilename\tscannr\trank\tlabel\tpeptide_q\tcharge\tsage_discriminant_score\n"
+if hit("FAKE_SAGE_NOCHARGE", mz):
+    hdr = hdr.replace("\tcharge\t", "\tz\t")
 with open(os.path.join(odir, "results.sage.tsv"), "w") as f:
-    f.write("psm_id\tpeptide\tproteins\tnum_proteins\tfilename\tscannr\trank\tlabel\tpeptide_q\n" + rows)
+    f.write(hdr + rows)
 n = count(mz)
 print("[INFO sage] - search:       999 ms (%d spectra/s)" % (n // 3 if hit("FAKE_SAGE_SHORT", mz) else n))
 print("[INFO sage] finished in 1s")
 '''
+# Extended plans: a diaWeaver and a FileFilter that write and read real base64 arrays. The diaWeaver fake labels its
+# plain little-endian arrays as numpress (the FileFilter fake reads them as plain), writes peaks unsorted, and shuffles
+# its spectra (equal RTs in pairs) like the real tool's unstable RT sort; ms1_centroid args shift every m/z.
+FAKE_MZML_LIB = r'''
+import base64, random, struct
+def write_mzml(path, specs, numpress=False):
+    with open(path, "w") as f:
+        f.write('<?xml version="1.0"?>\n<indexedmzML><mzML><run>\n<spectrumList count="%d">\n' % len(specs))
+        for i, s in enumerate(specs):
+            enc = lambda fmt, v: base64.b64encode(struct.pack("<%d%s" % (len(v), fmt), *v)).decode()
+            f.write('<spectrum id="scan=%d" index="%d" defaultArrayLength="%d">\n' % (s["id"], i, len(s["mz"])))
+            f.write(' <scanList count="1"><scan>\n  <cvParam cvRef="MS" accession="MS:1000016" name="scan start time" '
+                    'value="%r" unitAccession="UO:0000010"/>\n </scan></scanList>\n' % s["rt"])
+            f.write(' <precursorList count="1"><precursor>\n  <isolationWindow>\n   <cvParam cvRef="MS" accession="MS:1000827" '
+                    'name="isolation window target m/z" value="%r"/>\n  </isolationWindow>\n  <selectedIonList count="1">'
+                    '<selectedIon>\n' % s["sel"])
+            if s["sel_ok"]:
+                f.write('   <cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="%r"/>\n' % s["sel"])
+            f.write('   <cvParam cvRef="MS" accession="MS:1000041" name="charge state" value="%d"/>\n' % s["z"])
+            f.write('   <cvParam cvRef="MS" accession="MS:1002815" name="inverse reduced ion mobility" value="%r" '
+                    'unitAccession="MS:1002814"/>\n  </selectedIon></selectedIonList>\n </precursor></precursorList>\n' % s["im"])
+            f.write(' <binaryDataArrayList count="2">\n  <binaryDataArray encodedLength="0">\n   <cvParam cvRef="MS" '
+                    'accession="MS:1000523" name="64-bit float"/>\n   <cvParam cvRef="MS" accession="%s" name="c"/>\n'
+                    '   <cvParam cvRef="MS" accession="MS:1000514" name="m/z array"/>\n   <binary>%s</binary>\n'
+                    '  </binaryDataArray>\n' % ("MS:1002746" if numpress else "MS:1000576", enc("d", s["mz"])))
+            f.write('  <binaryDataArray encodedLength="0">\n   <cvParam cvRef="MS" accession="MS:1000521" name="32-bit float"/>\n'
+                    '   <cvParam cvRef="MS" accession="%s" name="c"/>\n   <cvParam cvRef="MS" accession="MS:1000515" '
+                    'name="intensity array"/>\n   <binary>%s</binary>\n  </binaryDataArray>\n </binaryDataArrayList>\n'
+                    '</spectrum>\n' % ("MS:1002748" if numpress else "MS:1000576", enc("f", s["inten"])))
+        f.write('</spectrumList></run></mzML>\n<indexListOffset>1</indexListOffset></indexedmzML>\n')
+def read_mzml(path):
+    specs, cur, kind = [], None, None
+    for line in open(path):
+        if "<spectrum " in line:
+            cur = {"mz": [], "inten": [], "sel_ok": False, "id": int(re.search(r'id="scan=(\d+)"', line).group(1))}
+        m = re.search(r'accession="(MS:\d+)"(?:[^>]*?value="([^"]*)")?', line)
+        if cur is not None and m:
+            a, v = m.groups()
+            if a == "MS:1000016": cur["rt"] = float(v)
+            elif a == "MS:1000827": cur["sel"] = float(v)
+            elif a == "MS:1000744": cur["sel_ok"] = True
+            elif a == "MS:1000041": cur["z"] = int(v)
+            elif a == "MS:1002815": cur["im"] = float(v)
+            elif a in ("MS:1000514", "MS:1000515"): kind = a
+        if "<binary>" in line:
+            raw = base64.b64decode(line.split("<binary>")[1].split("</binary>")[0])
+            mz = kind == "MS:1000514"
+            cur["mz" if mz else "inten"] = list(struct.unpack("<%d%s" % (len(raw) // (8 if mz else 4), "d" if mz else "f"), raw))
+        if "</spectrum>" in line:
+            specs.append(cur)
+            cur = None
+    return specs
+'''
+FAKE_DWV = FAKE_HEAD + FAKE_MZML_LIB + r'''
+if "--help" in sys.argv:
+    print("diaWeaver -- Extract pseudo spectra from DIA data\nVersion: 3.5.0-pre-fake")
+    sys.exit(0)
+line = " ".join(sys.argv)
+out = os.path.join(arg("-out"), "pseudo_spectra.mzML")
+with open(os.path.join(arg("-out"), "staged_files.txt"), "w") as f:
+    f.write("\n".join(sorted(os.listdir(arg("-in")))) + "\n")
+if hit("FAKE_DWV_FAIL", line):
+    sys.exit(3)
+if hit("FAKE_DWV_SLOW", line):
+    time.sleep(30)
+shift = 0.25 if "-bruker:ms1_centroid_mz_ppm" in sys.argv else 0.0
+n = 0 if hit("FAKE_DWV_ZERO", line) else 12
+specs = [{"rt": 60.0 + i // 2, "sel": 400.0 + 10 * i, "sel_ok": not hit("FAKE_DWV_NO744", line), "z": 2 + i % 3,
+          "im": 0.0 if i % 4 else 0.9, "mz": [300.0 + 7.5 * ((i * 7 + k * 13) % 40) + shift for k in range(8)],
+          "inten": [float(1000 + 10 * k) for k in range(8)]} for i in range(n)]
+random.shuffle(specs)
+for i, sp in enumerate(specs):
+    sp["id"] = i + 1
+if not hit("FAKE_DWV_NOOUT", line):
+    write_mzml(out, specs, numpress=True)
+print("Finished processing all windows. Wrote %d pseudo spectra." % (n + 1 if hit("FAKE_DWV_MISCOUNT", line) else n))
+if not hit("FAKE_DWV_NODONE", line):
+    print("Done. Output (numpress compressed): %s" % out)
+'''
+FAKE_FILEFILTER = FAKE_HEAD + FAKE_MZML_LIB + r'''
+src, dst = arg("-in"), arg("-out")
+assert sys.argv[5:] == ["-sort"], sys.argv
+if hit("FAKE_FF_FAIL", src):
+    sys.exit(1)
+specs = sorted(read_mzml(src), key=lambda sp: sp["rt"])
+for sp in specs:
+    if not hit("FAKE_FF_NOSORT", src):
+        o = sorted(range(len(sp["mz"])), key=lambda k: sp["mz"][k])
+        sp["mz"], sp["inten"] = [sp["mz"][k] for k in o], [sp["inten"][k] for k in o]
+if hit("FAKE_FF_DROP", src):
+    specs = specs[1:]
+if hit("FAKE_FF_CHARGE", src):
+    specs[0]["z"] += 1
+write_mzml(dst, specs, numpress=hit("FAKE_FF_NUMPRESS", src))
+'''
 FAKE_PATCH = FAKE_HEAD + r'''
 shutil.copy(sys.argv[1], sys.argv[2])
 n = count(sys.argv[1])
@@ -2317,6 +3482,380 @@ def _reg(q: dict) -> tuple:
     return plan, {"samples": {s["id"]: s for s in q["samples"]}}
 
 
+def _bench_tool(name: str):
+    """The real bench tool the extended selftest imports: the repository copy, else the cluster deployment point."""
+    for d in (REPO / "bench", Path("/ceph/ibmi/abi/oliver/spextract/tools")):
+        if (d / name).is_file():
+            return d / name
+    return None
+
+
+def _dwv_world(w: Path) -> dict:
+    spx, t = w / "ceph" / "spx", w / "ceph" / "spx" / "tools"
+    for arm in ("dwv", "dwv_noff", "dwv_badprov", "dwv_omp"):
+        a = spx / arm
+        _exe(a / "bin" / "diaWeaver", FAKE_DWV)
+        if arm != "dwv_noff":
+            _exe(a / "bin" / "FileFilter", FAKE_FILEFILTER)
+        (a / "lib").mkdir()
+        (a / "lib" / "libOpenMS.so").write_bytes(b"fork " + arm.encode())
+        (a / "env.sh").write_text("export DWV_BIN=%s\nexport OPENMS_DATA_PATH=%s\n%s" % (
+            a / "bin" / "diaWeaver", a / "share", "export OMP_NUM_THREADS=4\n" if arm == "dwv_omp" else ""))
+        files = [f for f in ("bin/diaWeaver", "bin/FileFilter", "lib/libOpenMS.so") if (a / f).is_file()]
+        (a / "PROVENANCE").write_text("arm=%s\ngit_sha=7ed11696fa71b3ac0b8c1a9f62fa2a2cbb39c0a8\nsha256_published:\n%s"
+                                      "published=2026-09-16T22:09:20+02:00\n" % (arm, "".join(
+                                          "  %s  %s\n" % ("0" * 64 if arm == "dwv_badprov" and f == "lib/libOpenMS.so"
+                                                           else sha256(a / f), f) for f in files)))
+    (spx / "dwv_outside").mkdir()
+    (spx / "dwv_outside" / "env.sh").write_text("export DWV_BIN=%s\n" % (spx / "dwv" / "bin" / "diaWeaver"))
+    tools = {}
+    for key, name in (("digest", "semantic_digest.py"), ("entrapment", "entrapment.py")):
+        src = _bench_tool(name)
+        if src:
+            shutil.copyfile(src, t / name)
+            tools[key] = str(t / name)
+    (w / "bench" / "human_entrap.fasta").write_text(">sp|P1|X\nPEPTIDEKAAAGGGLLLKMMMSTTTR\n>ENTRAP_sp|A1|ARATH\nWWWYYYHHHKFFFLLLIIIR\n")
+    (w / "bench" / "no_entrap.fasta").write_text(">sp|P1|X\nPEPTIDEKAAAGGGLLLKMMMSTTTR\n")
+    (t / "sage_entrap.json").write_text(json.dumps({"database": {"fasta": str(w / "bench" / "human_entrap.fasta")}}))
+    tools["sage_entrap"] = str(t / "sage_entrap.json")
+    return tools
+
+
+DWV_CELLS = {"dwv_default": {"kind": "dwv", "arm": "dwv", "args": [], "wall_cap_h": 1},
+             "dwv_pickim": {"kind": "dwv", "arm": "dwv", "args": ["-bruker:ms1_centroid_mz_ppm", "0", "-bruker:ms1_centroid_im_pct", "0"],
+                            "wall_cap_h": 1, "differs_from": "dwv_default"}}
+
+
+def _xqueue(w: Path, ids: str, root: str, xtools: dict, cells_=None, **kw) -> dict:
+    q = _queue(w, ids, root=root, **kw)
+    q.update(tools=dict(q["tools"], **xtools), entrapment=True, cells=json.loads(json.dumps(cells_ or DWV_CELLS)),
+             search_db_sha256=dict(q["search_db_sha256"], entrap_fasta=sha256(w / "bench" / "human_entrap.fasta")))
+    return q
+
+
+def _xreg(q: dict) -> tuple:
+    plan, reg = _reg(q)
+    plan.update(cells=q["cells"], entrapment=q["entrapment"], tools=q["tools"])
+    return plan, reg
+
+
+def _selftest_extended(C, w: Path, q1: dict, q3: dict) -> None:
+    """Extended plans (cells, re-encode, no-op flag, entrapment, charge split) and the pair-compatibility claim."""
+    import contextlib, io, yaml
+    spx = w / "ceph" / "spx"
+    xt = _dwv_world(w)
+    if set(xt) != {"digest", "entrapment", "sage_entrap"}:
+        C.check("G-V19", "selftest finds bench/entrapment.py and bench/semantic_digest.py", False,
+                "run it from the repository (or where /ceph/.../tools holds them)")
+        return
+    os.environ["FAKE_MSF_SLEEP"] = "0"
+
+    # ---- the two-extractor pair is unchanged
+    m0, mx = measure_sha256(), measure_sha256(True)
+    C.check("COMPAT", "pair/search/score measurement code is the 1.3.0 code (PAIR_MEASURE_1_3_0; update on purpose only)",
+            {k: v[:12] for k, v in m0.items()} == PAIR_MEASURE_1_3_0, {k: v[:12] for k, v in m0.items()})
+    C.check("COMPAT", "an extended plan adds a fourth hash (cells) and keeps the other three",
+            set(mx) == {"pair", "search", "score", "cells"} and {k: mx[k] for k in m0} == m0)
+    plan_p = {k: q1[k] for k in PLAN_KEYS if k != "queues"}
+    plan_p["queues"] = {"n1": {"samples": ["A"]}}
+    qp = resolve_queue("pp", plan_p, {"samples": {s["id"]: s for s in q1["samples"]}}, "n1")
+    C.check("COMPAT", "a plain plan resolves without cells/entrapment: TOOLS, ENGINES, run_pair",
+            not extended(qp) and not set(qp) & OPTIONAL_PLAN_KEYS and q_tools(qp) == TOOLS and q_engines(qp) == ENGINES
+            and plan_tool_keys(qp) == TOOL_KEYS and db_keys(qp) == DB_KEYS)
+    rp = _records(q1)
+    C.check("COMPAT", "plain records carry no cells, cells hash or charge split",
+            all("cells" not in r and "cells" not in (r.get("measure_sha256") or {}) and "by_charge" not in r for r in rp.values()))
+    buf = io.StringIO()
+    with contextlib.redirect_stdout(buf):
+        dry_run(q3)
+    C.check("COMPAT", "plain dry-run prints nothing of the extended plans",
+            not any(x in buf.getvalue() for x in ("extended plan", "G-V17", "reencoded", "entrap", "dwv", "tdf_bin only")))
+    C.check("COMPAT", "plain pairs stage the whole .d as before", "files" not in rp["A", "pair"]["stage"])
+    mdp = render_table("selftest", *_reg(q1), list(rp.values()))[0]
+    C.check("COMPAT", "plain table renders without the extended sections",
+            "Peptides by precursor charge" not in mdp and "Entrapment by charge" not in mdp and "Cell outputs" not in mdp)
+    C.check("COMPAT", "plain identity carries no cells", "cells" not in build_identity(identity(q1, arm_env(q1)[0])))
+
+    # ---- G-V01 extended plan validation
+    xq = _xqueue(w, "AB", "x1", xt)
+    xplan = {k: xq[k] for k in (PLAN_KEYS | OPTIONAL_PLAN_KEYS) - {"queues"}}
+    xplan["queues"] = {"n1": {"samples": ["A", "B"]}}
+    samples = {s["id"]: {k: s[k] for k in SAMPLE_KEYS} for s in xq["samples"]}
+
+    def pf(pl):
+        f = w / ("xreg%s.yaml" % os.urandom(3).hex())
+        f.write_text(yaml.safe_dump({"samples": samples, "xp": pl}))
+        return f
+    C.ok("G-V01", "extended plan (two cells, entrapment) loads", lambda: load_plan("xp", pf(xplan)))
+    for what, mut, frag in (
+            ("a cell named like a reference arm", lambda pl: pl["cells"].update(dt=pl["cells"]["dwv_default"]), "reserved"),
+            ("a cell name with a path separator", lambda pl: pl["cells"].update({"../x": pl["cells"]["dwv_default"]}), "reserved"),
+            ("an unknown cell kind", lambda pl: pl["cells"]["dwv_default"].update(kind="weaver"), "unknown kind"),
+            ("a cell without wall_cap_h", lambda pl: pl["cells"]["dwv_default"].pop("wall_cap_h"), "needs exactly"),
+            ("a cell with an unknown key", lambda pl: pl["cells"]["dwv_default"].update(ram_gb=10), "needs exactly"),
+            ("wall_cap_h 0", lambda pl: pl["cells"]["dwv_default"].update(wall_cap_h=0), "wall_cap_h"),
+            ("wall_cap_h given as a boolean", lambda pl: pl["cells"]["dwv_default"].update(wall_cap_h=True), "wall_cap_h"),
+            ("cell args setting -threads", lambda pl: pl["cells"]["dwv_default"].update(args=["-threads", "8"]), "harness sets"),
+            ("cell args not a list of strings", lambda pl: pl["cells"]["dwv_default"].update(args="-x 1"), "list of strings"),
+            ("differs_from an unknown cell", lambda pl: pl["cells"]["dwv_pickim"].update(differs_from="dwv_x"), "differs_from"),
+            ("differs_from itself", lambda pl: pl["cells"]["dwv_pickim"].update(differs_from="dwv_pickim"), "differs_from"),
+            ("a cell arm with a path separator", lambda pl: pl["cells"]["dwv_default"].update(arm="../v1.3.0"), "directory name"),
+            ("entrapment: yes (a string)", lambda pl: pl.update(entrapment="yes"), "true or false"),
+            ("entrapment without its tools", lambda pl: pl["tools"].pop("sage_entrap"), "tools need exactly"),
+            ("cells without the digest tool", lambda pl: pl["tools"].pop("digest"), "tools need exactly"),
+            ("entrapment without an entrap_fasta pin", lambda pl: pl["search_db_sha256"].pop("entrap_fasta"), "search_db_sha256"),
+            ("empty cells", lambda pl: pl.update(cells={}), "non-empty")):
+        pl = json.loads(json.dumps(xplan))
+        mut(pl)
+        C.abort("G-V01", "extended plan refused: %s" % what, lambda pl=pl: load_plan("xp", pf(pl)), frag)
+    C.abort("G-V01", "guardtest refused for an extended plan", lambda: _guardtest(dict(xq, plan="x_selftest"), Path(xq["root"])),
+            "two-extractor pair only")
+
+    # ---- G-V03 / G-V04 / G-V11 cell arms and identity
+    one = lambda arm: dict(xq, cells={"c1": dict(DWV_CELLS["dwv_default"], arm=arm)})
+    C.abort("G-V03", "cell env.sh missing", lambda: cell_env(one("nope"), "c1"), "env.sh missing")
+    C.abort("G-V03", "cell env.sh exports an OpenMP knob", lambda: cell_env(one("dwv_omp"), "c1"), "itself exports")
+    C.abort("G-V03", "DWV_BIN outside the cell arm", lambda: cell_env(one("dwv_outside"), "c1"), "outside the cell arm")
+    C.abort("G-V03", "no FileFilter beside DWV_BIN", lambda: cell_env(one("dwv_noff"), "c1"), "FileFilter")
+    qb = one("dwv_badprov")
+    C.abort("G-V03", "cell provenance lists another sha256 for a lib file",
+            lambda: cells_meta(qb, {"c1": cell_env(qb, "c1")}, {"cells": cells_identity(qb)}), "lib/libOpenMS.so")
+    (spx / "dwv_unlisted" / "lib").mkdir(parents=True)
+    for f in ("bin", "env.sh", "PROVENANCE"):
+        (shutil.copytree if f == "bin" else shutil.copyfile)(spx / "dwv" / f, spx / "dwv_unlisted" / f)
+    (spx / "dwv_unlisted" / "lib" / "libOpenMS.so").write_bytes(b"fork dwv")
+    (spx / "dwv_unlisted" / "lib" / "libextra.so").write_bytes(b"not published")
+    (spx / "dwv_unlisted" / "env.sh").write_text("export DWV_BIN=%s\n" % (spx / "dwv_unlisted" / "bin" / "diaWeaver"))
+    qu = one("dwv_unlisted")
+    C.abort("G-V03", "a lib file the provenance does not list",
+            lambda: cells_meta(qu, {"c1": cell_env(qu, "c1")}, {"cells": cells_identity(qu)}), "lib/libextra.so")
+    qn = one("dwv_noprov")
+    shutil.copytree(spx / "dwv", spx / "dwv_noprov")
+    (spx / "dwv_noprov" / "PROVENANCE").unlink()
+    (spx / "dwv_noprov" / "env.sh").write_text("export DWV_BIN=%s\n" % (spx / "dwv_noprov" / "bin" / "diaWeaver"))
+    C.abort("G-V03", "cell arm without PROVENANCE",
+            lambda: cells_meta(qn, {"c1": cell_env(qn, "c1")}, {"cells": cells_identity(qn)}), "provenance missing")
+    cenvs = {n: cell_env(xq, n) for n in xq["cells"]}
+    cm = C.ok("G-V03", "cell provenance and label resolve", lambda: cells_meta(xq, cenvs, {"cells": cells_identity(xq)}))
+    ce = cenvs["dwv_default"]
+    C.check("G-V03", "cell label from --help; cell env stripped like the arm's",
+            bool(cm) and cm["dwv_default"]["label"] == "diaWeaver 3.5.0-pre-fake" and not any(strip_var(k) for k in ce)
+            and "LD_LIBRARY_PATH" not in ce and ce["LC_ALL"] == "C", cm and cm["dwv_default"]["label"])
+    envx = arm_env(xq)[0]
+    C.check("G-V05", "busy patterns include the cell binary", r"diaWeave[r] -in" in busy_patterns(envx, cenvs))
+    ix = identity(xq, envx)
+    C.check("G-V11", "extended build identity carries each cell's build",
+            set(build_identity(ix).get("cells", {})) == {"dwv_default", "dwv_pickim"})
+    for what, f in (("diaWeaver binary", spx / "dwv" / "bin" / "diaWeaver"), ("FileFilter", spx / "dwv" / "bin" / "FileFilter"),
+                    ("cell arm lib", spx / "dwv" / "lib" / "libOpenMS.so")):
+        orig = f.read_bytes()
+        f.write_bytes(orig + b"\n# changed\n")
+        C.abort("G-V04", "%s changed across an arm" % what, lambda: check_identity(xq, envx, ix, "during dwv_default"), "changed")
+        C.check("G-V11", "%s changed: build identity differs" % what, build_identity(identity(xq, envx)) != build_identity(ix))
+        f.write_bytes(orig)
+
+    # ---- extended happy queue: 2 samples, 2 cells, entrapment
+    rc = C.ok("G-V16", "extended queue runs", lambda: node_run(xq))
+    R = _records(xq)
+    tx, ex = list(q_tools(xq)), list(q_engines(xq))
+    C.check("G-V16", "both groups ok, every arm ok, rc 0",
+            rc == 0 and all(R[s, "pair"]["status"] == "ok" and not R[s, "pair"]["cells_failed"]
+                            and all(R[s, "pair"]["arms"][t].get("status", "ok") == "ok" for t in tx) for s in "AB"), rc)
+    C.check("G-V09", "reference pair first (alternating), then the cells rotated by queue index",
+            R["A", "pair"]["order"] == ["dt", "spx", "dwv_default", "dwv_pickim"]
+            and R["B", "pair"]["order"] == ["spx", "dt", "dwv_pickim", "dwv_default"], [R[s, "pair"]["order"] for s in "AB"])
+    a = R["A", "pair"]["arms"]["dwv_default"]
+    C.check("G-V17", "cell output re-encoded: numpress 24 -> 0, peaks sorted, 12 spectra kept, raw file deleted",
+            a["spectra_stats"]["numpress_terms"] == 24 and a["reencoded_stats"]["numpress_terms"] == 0
+            and a["reencoded_stats"]["unsorted"] == 0 and a["output"]["count"] == a["raw_output"]["count"] == 12
+            and a["output"]["path"].endswith("/reencoded.mzML") and not Path(a["raw_output"]["path"]).exists(), a.get("reencoded_stats"))
+    C.check("G-V07", "an extended plan stages analysis.tdf + analysis.tdf_bin only (the raw also has a method folder)",
+            R["A", "pair"]["stage"]["files"] == list(STAGE_FILES) and (w / "ceph" / "raw" / "run_A.d" / "run.m").is_dir()
+            and (Path(a["cwd"]) / "staged_files.txt").read_text().split() == list(STAGE_FILES)
+            and R["A", "pair"]["stage"]["fingerprint"] == xq["samples"][0]["pin"], R["A", "pair"]["stage"].get("files"))
+    C.check("G-V16", "every arm timed with CPU; the cell's cap recorded and not hit",
+            all(R["A", "pair"]["arms"][t]["cpu"]["cpu_s"] == 125.0 for t in tx) and a["wall_cap_s"] == 3600
+            and a["stopped"] is None and a["log_count"] == 12)
+    C.check("G-V17", "cell statistics: charges 2/3/4, 1/K0 = 0 in 9 of 12, 8 peaks",
+            a["spectra_stats"]["charges"] == {"2": 4, "3": 4, "4": 4} and a["spectra_stats"]["im_zero"] == 9
+            and a["spectra_stats"]["peaks_median"] == 8, a["spectra_stats"])
+    nz = R["A", "pair"]["arms"]["dwv_pickim"].get("noop") or {}
+    C.check("G-V18", "a cell that differs from its reference is not flagged",
+            nz.get("computed") and not nz.get("flag") and not nz.get("content_equal"), nz)
+    C.check("G-V10", "every arm searched by Sage, MSFragger and the entrapment search (24 cells ok)",
+            all(R[s, "%s.%s" % (t, e)]["status"] == "ok" for s in "AB" for t in tx for e in ex))
+    ss, ms, es = R["A", "dwv_default.sage"], R["A", "dwv_default.msfragger"], R["A", "dt.entrap"]
+    C.check("G-V19", "charge split adds up: Sage z1 6 + z2p 25 (targets 6 + 24), MSFragger 15 + 135",
+            ss["by_charge"]["z1"] == {"peptides": 6, "target_peptides": 6}
+            and ss["by_charge"]["z2p"] == {"peptides": 25, "target_peptides": 24}
+            and ms["by_charge"]["z1"]["peptides"] == 15 and ms["by_charge"]["z2p"]["peptides"] == 135
+            and ss["measure_sha256"]["cells"] == mx["cells"], (ss.get("by_charge"), ms.get("by_charge")))
+    en = es.get("entrapment") or {}
+    C.check("G-V19", "entrapment by stratum on the patched diaTracer file: all 30 + 3, z1 6 + 1, z2p 24 + 2",
+            es["patched"] == 17 and en["all"]["target"] == 30 and en["all"]["entrap"] == 3 and en["z1"]["target"] == 6
+            and en["z1"]["entrap"] == 1 and en["z2p"]["target"] == 24 and en["z2p"]["entrap"] == 2 and es["peptides"] == 30, en)
+    est = load_module(xt["entrapment"], "entrapment_selftest")
+    whole = est.score(es["result_tsv"], ENTRAP_TAG, en["ratio"])
+    C.check("G-V19", "the `all` stratum equals bench/entrapment.py score() on the whole TSV",
+            (whole[0], whole[1], whole[2]) == (en["all"]["accepted"], en["all"]["target"], en["all"]["entrap"]), whole[:3])
+    C.check("G-V11", "records carry the four measurement hashes", R["A", "pair"]["measure_sha256"] == mx
+            and all(R["A", "%s.entrap" % t]["measure_sha256"]["cells"] == mx["cells"] for t in tx))
+    C.check("G-V14", "no mzML and no staged copy left after the extended queue",
+            not list(Path(xq["root"]).rglob("*.mzML")) and not any((Path(xq["root"]) / "stage").iterdir()))
+    md, inc, tot = C.ok("G-V13", "extended table renders", lambda: render_cells_table("x", *_xreg(xq), list(R.values())))
+    mainrows = [l for l in md.split("\n## ")[0].splitlines() if l.startswith("| A ") or l.startswith("| B ")]
+    C.check("G-V13", "extended table: 2 of 2 complete, 8 arm rows, all sections, no zero in the main rows",
+            inc == 0 and tot == 2 and len(mainrows) == 8 and not any("| 0 |" in l for l in mainrows)
+            and all(x in md for x in ("## Peptides by precursor charge", "## Entrapment by charge stratum", "## Cell outputs",
+                                      "## Per arm, complete samples only", "FileFilter -in pseudo_spectra.mzML",
+                                      "diaWeaver 3.5.0-pre-fake", "| A | dwv_default | z1 |")), (inc, tot, len(mainrows)))
+    ctxx = {"ident": ix, "tools_sha": install_tools(xq)["sha256"], "measure": mx, "threads": 100,
+            "tools": tx, "engines": ex, "cells": xq["cells"]}
+    bad = json.loads(json.dumps(R["A", "pair"]))
+    bad["arms"]["dwv_pickim"]["status"] = "failed"
+    C.check("G-V11", "a record whose cell failed is never adopted, even if it lists an output",
+            pair_done(R["A", "pair"], xq["samples"][0], ctxx, Path(xq["root"]))
+            and not pair_done(bad, xq["samples"][0], ctxx, Path(xq["root"]))
+            and "dwv_pickim" not in (ready_arms(bad, xq["samples"][0], ctxx, Path(xq["root"])) or []))
+    n_msf = len((w / "msf_times.log").read_text().splitlines())
+    node_run(dict(xq, nonce="xresume"))
+    R2 = _records(xq)
+    C.check("G-V11", "extended resume skips verified groups and searches",
+            all(R2[s, "pair"]["pair_run"] == R[s, "pair"]["pair_run"] for s in "AB")
+            and len((w / "msf_times.log").read_text().splitlines()) == n_msf)
+    recs = list(R.values())
+
+    def mutated(fn, plan=None):
+        rr = json.loads(json.dumps(recs))
+        fn({(r["id"], r.get("tool", "pair"), r.get("engine", "pair")): r for r in rr})
+        return lambda: render_cells_table("x", plan or _xreg(xq)[0], _xreg(xq)[1], rr)
+    C.abort("G-V13", "extended table refuses two diaWeaver builds", mutated(
+        lambda m: m["B", "pair", "pair"]["identity"]["cells"]["dwv_default"].update(binary_sha256="x")), "more than one")
+    C.abort("G-V13", "extended table refuses two cell labels", mutated(
+        lambda m: m["B", "pair", "pair"]["cells_meta"]["dwv_default"].update(label="diaWeaver 9")), "tool label")
+    C.abort("G-V13", "extended table refuses records of other cell settings", mutated(
+        lambda m: None, dict(_xreg(xq)[0], cells=dict(xq["cells"], dwv_default=dict(DWV_CELLS["dwv_default"], wall_cap_h=2)))),
+        "differ from the plan")
+    C.abort("G-V13", "extended table refuses an ok cell with 0 spectra", mutated(
+        lambda m: m["A", "pair", "pair"]["arms"]["dwv_pickim"]["output"].update(count=0)), "count")
+    rq = read_json(rec_path(xq["root"], "A", "spx", "sage"))
+    write_json(rec_path(xq["root"], "A", "spx", "sage"), dict(rq, peptides=rq["peptides"] + 1))
+    C.check("G-V19", "a charge split that does not add up to the count fails the cell",
+            not add_split(xq["root"], "A", "spx", "sage", {"measure": mx})
+            and read_json(rec_path(xq["root"], "A", "spx", "sage"))["guard"] == "G-V19")
+    buf = io.StringIO()
+    with contextlib.redirect_stdout(buf):
+        dry_run(xq)
+    out = buf.getvalue()
+    want = ("order dt -> spx -> dwv_default -> dwv_pickim", "analysis.tdf + analysis.tdf_bin only", "bin/diaWeaver -in", "-threads 100 -bruker:ms1_centroid_mz_ppm 0",
+            "FileFilter -in", "reencoded.mzML' -sort >reencode.log", "G-V16", "G-V18: flag dwv_pickim", "sage_entrap.json",
+            "dwv_pickim_msfragger", "G-V19")
+    C.check("DRY", "extended dry-run prints the cells, re-encode, no-op and entrapment steps",
+            all(x in out for x in want), [x for x in want if x not in out])
+
+    # ---- G-V18: a cell equal in content is flagged although its order and ids differ
+    xn = _xqueue(w, "C", "x2", xt, cells_={"dwv_a": dict(DWV_CELLS["dwv_default"]),
+                                           "dwv_b": dict(DWV_CELLS["dwv_default"], differs_from="dwv_a")})
+    node_run(xn)
+    RN = _records(xn)
+    nb = RN["C", "pair"]["arms"]["dwv_b"].get("noop") or {}
+    C.check("G-V18", "no-op cell flagged: content digest equal, spectrum-list digest not (order and ids differ)",
+            nb.get("flag") is True and nb.get("content_equal") and not nb.get("semantic_equal"), nb)
+    mdn = render_cells_table("x", *_xreg(xn), list(RN.values()))[0]
+    C.check("G-V18", "the no-op flag reaches the status flags and the table",
+            "no-op: content equal to dwv_a" in group_flags(RN["C", "pair"]) and "no-op: content equal to dwv_a" in mdn)
+
+    # ---- G-V16: cell failures, the other cell still runs, the group re-runs whole
+    mine = re.escape(str(spx / "dwv" / "bin" / "diaWeave")) + "[r] -in"      # this world's tool only (parallel selftests)
+    capped = {n: dict(c, wall_cap_h=0.0005) for n, c in DWV_CELLS.items()}
+    fails = {"FAKE_DWV_FAIL": "/C.d&/dwv_default", "FAKE_DWV_MISCOUNT": "/D.d", "FAKE_DWV_NODONE": "/E.d",
+             "FAKE_DWV_NOOUT": "/F.d", "FAKE_DWV_ZERO": "/G.d", "FAKE_DWV_SLOW": "/H.d"}
+    os.environ.update(fails)
+    xf = _xqueue(w, "CDEFGH", "x3", xt, cells_=capped)
+    rcf = node_run(xf)
+    for k in fails:
+        del os.environ[k]
+    RF = _records(xf)
+    cell = lambda sid, n: RF[sid, "pair"]["arms"].get(n) or {}
+    msg = lambda sid, n: "[%s] %s" % (cell(sid, n).get("guard"), cell(sid, n).get("message", ""))
+    C.check("G-V16", "a failing cell (exit 3) fails alone: the next cell ran, the group is ok with cells_failed",
+            cell("C", "dwv_default").get("guard") == "G-V16" and "rc=3" in msg("C", "dwv_default")
+            and cell("C", "dwv_pickim").get("status") == "ok" and RF["C", "pair"]["status"] == "ok"
+            and RF["C", "pair"]["cells_failed"] == ["dwv_default"], msg("C", "dwv_default"))
+    C.check("G-V18", "no-op check impossible when the reference cell failed: flagged",
+            (cell("C", "dwv_pickim").get("noop") or {}).get("flag") is True
+            and "impossible" in group_flags(RF["C", "pair"]), cell("C", "dwv_pickim").get("noop"))
+    C.check("G-V10", "the ok arms of a group with a failed cell are searched, the failed cell is not",
+            (RF.get(("C", "dwv_pickim.entrap")) or {}).get("status") == "ok"
+            and (RF.get(("C", "dt.msfragger")) or {}).get("status") == "ok" and ("C", "dwv_default.sage") not in RF)
+    for sid, frag, what in (("D", "log count", "tool count line differs"), ("E", "final rewrite", "no finalisation line"),
+                            ("F", "wrote no pseudo_spectra.mzML", "no output file"), ("G", "count missing or <= 0", "0 spectra"),
+                            ("H", "wall cap", "wall cap passed: session killed")):
+        C.check("G-V16", "cell %s (both cells of %s)" % (what, sid),
+                all(cell(sid, n).get("guard") == "G-V16" and frag in cell(sid, n).get("message", "") for n in capped)
+                and RF[sid, "pair"]["cells_failed"] == list(RF[sid, "pair"]["order"][2:]), msg(sid, "dwv_default"))
+    C.check("G-V16", "the killed cell tool is gone", not busy([mine]))
+    C.check("G-V14", "raw cell output kept after a failed cell (re-runnable), listed for purge",
+            any(x.endswith("dwv_default/pseudo_spectra.mzML") for x in leftovers(xf["root"])) and rcf == 1)
+    mdf = render_cells_table("x", *_xreg(xf), list(RF.values()))[0]
+    C.check("G-V13", "failed cells render FAILED G-V16, never a number", mdf.count("FAILED G-V16") >= 5)
+    runs_f = {sid: RF[sid, "pair"]["pair_run"] for sid in "CDEFGH"}
+    node_run(dict(xf, nonce="xrerun"))
+    RF2 = _records(xf)
+    C.check("G-V11", "a group with a failed cell re-runs whole on the next launch (same plan), now ok",
+            all(RF2[sid, "pair"]["pair_run"] != runs_f[sid] and not RF2[sid, "pair"]["cells_failed"] for sid in "CDEFGH"))
+    runs_f = {sid: RF2[sid, "pair"]["pair_run"] for sid in "CDEFGH"}
+    node_run(dict(xf, nonce="xsame"))
+    C.check("G-V11", "a complete group of the same plan is skipped", all(
+        _records(xf)[sid, "pair"]["pair_run"] == runs_f[sid] for sid in "CD"))
+    xf["cells"] = {n: dict(c, wall_cap_h=1) for n, c in capped.items()}
+    node_run(dict(xf, nonce="xsettings"))
+    RF3 = _records(xf)
+    C.check("G-V11", "a complete group of other cell settings is not adopted: it re-runs",
+            all(RF3[sid, "pair"]["pair_run"] != runs_f[sid] and RF3[sid, "pair"]["status"] == "ok" for sid in "CD"))
+    os.environ.update(FAKE_MEMAVAIL="10", FAKE_DWV_SLOW="/A.d")
+    xm = _xqueue(w, "A", "x4", xt)
+    node_run(xm)
+    del os.environ["FAKE_MEMAVAIL"], os.environ["FAKE_DWV_SLOW"]
+    RM = _records(xm)
+    C.check("G-V16", "MemAvailable under the floor: the cell session is killed; the reference arms are flagged",
+            all("MemAvailable 1.0%" in RM["A", "pair"]["arms"][n].get("message", "") for n in DWV_CELLS)
+            and "during" in group_flags(RM["A", "pair"]) and not busy([mine]),
+            RM["A", "pair"]["arms"]["dwv_default"].get("message"))
+
+    # ---- G-V17: the re-encode checks
+    ff = {"FAKE_FF_NUMPRESS": "/runs/A/", "FAKE_FF_NOSORT": "/runs/B/", "FAKE_FF_DROP": "/runs/C/",
+          "FAKE_FF_CHARGE": "/runs/D/", "FAKE_DWV_NO744": "/E.d", "FAKE_FF_FAIL": "/runs/F/", "FAKE_SAGE_NOCHARGE": "/runs/F/"}
+    os.environ.update(ff)
+    xr = _xqueue(w, "ABCDEF", "x5", xt, cells_={"dwv_default": DWV_CELLS["dwv_default"]})
+    node_run(xr)
+    for k in ff:
+        del os.environ[k]
+    RR = _records(xr)
+    for sid, frag, what in (("A", "numpress term", "numpress left"), ("B", "not m/z-sorted", "peaks unsorted"),
+                            ("C", "changed the spectrum count", "a spectrum dropped"),
+                            ("D", "changed RT, selected ion m/z, charge", "a charge changed"),
+                            ("E", "carry no selected ion m/z", "no selected ion m/z"), ("F", "failed: time rc=1", "the tool failed")):
+        c = RR[sid, "pair"]["arms"]["dwv_default"]
+        C.check("G-V17", "re-encode refused: %s" % what, c.get("guard") == "G-V17" and frag in c.get("message", ""), c.get("message"))
+    C.check("G-V17", "the raw output is kept when the re-encode fails",
+            Path(RR["A", "pair"]["arms"]["dwv_default"]["raw_output"]["path"]).is_file())
+    C.check("G-V19", "a Sage TSV without a charge column fails the split and the entrapment search",
+            RR["F", "spx.sage"]["guard"] == "G-V19" and RR["F", "spx.entrap"]["guard"] == "G-V19"
+            and "charge" in RR["F", "spx.entrap"]["message"], (RR["F", "spx.sage"].get("message"), RR["F", "spx.entrap"].get("message")))
+    purge = node_purge({"root": xr["root"], "lock": xr["lock"]})
+    C.check("G-V14", "purge removes the kept cell outputs", bool(purge["removed"]) and not purge["left"], purge)
+
+    # ---- G-V19 units
+    tsv = Path(es["result_tsv"])
+    C.abort("G-V19", "entrapment FASTA without ENTRAP_ peptides", lambda: entrap_strata(
+        tsv, est, str(w / "bench" / "no_entrap.fasta")), "no ENTRAP_")
+    C.abort("G-V19", "MSFragger TSV without a charge column", lambda: msf_by_charge(w / "hdr.tsv"), "lacks columns")
+    C.check("G-V19", "MSFragger split keeps msf_peptides' count", msf_by_charge(Path(ms["result_tsv"]))["all"]["peptides"]
+            == msf_peptides(Path(ms["result_tsv"]))["peptides"] == 150)
+    os.environ["FAKE_MSF_SLEEP"] = "0.3"
+
+
 def selftest(args=None) -> int:
     import contextlib, io
     C = Cases()
@@ -2332,7 +3871,7 @@ def selftest(args=None) -> int:
         def fake_snapshot():          # our tree at 4 cores; FAKE_FOREIGN_CORES more on the node
             t, f = time.monotonic(), float(os.environ.get("FAKE_FOREIGN_CORES", "0"))
             return {"t": t, "busy": int((4 + f) * CLK_TCK * t), "ours": int(4 * CLK_TCK * t),
-                    "memavail_kb": 900, "memtotal_kb": 1000}
+                    "memavail_kb": int(os.environ.get("FAKE_MEMAVAIL", "900")), "memtotal_kb": 1000}
         globals().update(TIME=str(w / "bin" / "time"), POLL_S=0.01, LOCK_RETRY_S=0.3, MON_S=0.02, load1=lambda: 0.5,
                          mem_available_kb=lambda *a: 1000, proc_snapshot=fake_snapshot)
         os.environ.update(PATH=str(w / "bin") + os.pathsep + os.environ["PATH"], FAKE_ENVDUMP=str(w / "envdump.txt"),
@@ -2776,11 +4315,19 @@ def selftest(args=None) -> int:
                 "patch_diatracer_precursor.py", "fix_mzml_cvparams.py", "copy data only", "rm -rf", "cat "]
         C.check("DRY", "dry-run prints every command", all(x in out for x in want) and out.count("## ") == 4,
                 [x for x in want if x not in out])
+
+        # ---- extended plans (cells, re-encode, no-op flag, entrapment, charge split) and pair compatibility
+        try:
+            _selftest_extended(C, w, q1, q3)
+        except Exception as x:               # a crash is a FAIL line, never a silently shorter selftest
+            import traceback
+            C.check("EXT", "extended selftest completed", False, "crashed: %s: %s %s" % (
+                type(x).__name__, x, traceback.format_exc().strip().splitlines()[-3][-60:]))
     finally:
         globals().update(saved)
         os.environ.clear()
         os.environ.update(env_saved)
-    missing = sorted({"G-V%02d" % i for i in range(1, 16)} - C.fired)
+    missing = sorted({"G-V%02d" % i for i in range(1, 20)} - C.fired)
     if missing:
         C.results.append(("FAIL", "ALL", "every guard fired at least once", "never fired: %s" % missing))
     width = max(len(r[2]) for r in C.results)
```

## Unchanged functions the new code calls (harness/corpus.py at a716b5c)
```python
class Abort(Exception):
    """A guard fired. `queue=True` stops the whole queue; otherwise only the cell fails."""

    def __init__(self, guard, message, queue=False):
        super().__init__("[%s] %s" % (guard, message))
        self.guard, self.message, self.queue = guard, message, queue


def die(guard, message):
    raise Abort(guard, message)


def die_queue(guard, message):
    raise Abort(guard, message, queue=True)


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()

# ...
def parse_time_log(path: Path, guard: str) -> dict:
    """GNU time -v. "Command terminated by signal 7" comes with "Exit status: 0" (the SIGBUS of
    memory never-publish-during-a-chain), so both lines are read."""
    txt = path.read_text(errors="replace") if path.exists() else ""
    w = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (\S+)", txt)
    r = re.search(r"Maximum resident set size \(kbytes\): (\d+)", txt)
    e = re.search(r"Exit status: (\d+)", txt)
    if not (w and r and e):
        die(guard, "time log unparseable: %s" % path)
    parts = [float(x) for x in w.group(1).split(":")]
    wall = sum(v * 60 ** i for i, v in enumerate(reversed(parts)))
    s = re.search(r"Command terminated by signal (\d+)", txt)
    return {"wall_s": round(wall, 2), "peak_rss_kb": int(r.group(1)), "exit_status": int(e.group(1)),
            "signal": int(s.group(1)) if s else None}


def check_exit(t: dict, rc: int, guard: str, what: str) -> None:
    if rc != 0 or t["exit_status"] != 0 or t["signal"] is not None:
        die(guard, "%s failed: time rc=%s exit=%s signal=%s" % (what, rc, t["exit_status"], t["signal"]))


def verify_mzml(path: Path, start_epoch: float) -> dict:
    """Fresh (mtime > start), terminated, and spectrumList count > 0 parsed as an INTEGER: tiled
    output writes a zero-padded count, which a string comparison gets wrong (critique F9)."""
    if not path.is_file():
        die("G-V08", "output missing: %s" % path)
    st = path.stat()
    if st.st_mtime <= start_epoch:
        die("G-V08", "output is stale (mtime %.0f <= arm start %.0f): %s" % (st.st_mtime, start_epoch, path))
    with open(path, "rb") as f:
        f.seek(max(0, st.st_size - 4096))
        tail = f.read().rstrip()
        if not (tail.endswith(b"</indexedmzML>") or tail.endswith(b"</mzML>")):
            die("G-V08", "output not terminated (truncated?): %s" % path)
        f.seek(0)
        buf, m = b"", None
        while m is None and len(buf) < (64 << 20):
            blk = f.read(1 << 20)
            if not blk:
                break
            buf += blk
            m = re.search(rb"<spectrumList\b[^>]*\bcount=\"(\d+)\"", buf)
    if m is None or int(m.group(1)) <= 0:
        die("G-V08", "spectrumList count missing or <= 0: %s" % path)
    return {"path": str(path), "size": st.st_size, "mtime": st.st_mtime, "count": int(m.group(1))}


def log_count(path: Path, pattern: bytes) -> int | None:
    """Bytes regex over the whole log: e.log can hold binary bytes, which hide lines from plain
    grep (memory spextractor-elog-needs-grep-a)."""
    m = re.findall(pattern, path.read_bytes()) if path.exists() else []
    return int(m[-1]) if m else None


def engine_spectra(log: bytes, engine: str) -> int | None:
    """Spectra the engine itself read (review F1). MSFragger: `in.mzML: Scans = N`, every scan. Sage 0.14.7
    logs only a rate, `- search: D ms (R spectra/s)` with R = floor(n * 1000 / (D + 1)) over the spectra with
    >= min_peaks peaks (sage-cli main.rs:138-141), so floor(R * (D + 1) / 1000) is a lower bound on that n."""
    if engine == "msfragger":
        m = re.findall(rb"in\.mzML: Scans = (\d+)", log)
        return int(m[-1]) if m else None
    m = re.findall(rb"- search:\s+(\d+) ms \((\d+) spectra/s\)", log)
    return sum(int(r) * (int(d) + 1) // 1000 for d, r in m) if m else None


# ------------------------------------------------------------------------------- peptide rules
# Ported verbatim (logic) from /ceph/ibmi/abi/oliver/spextract/tools/bench_table.py sage_peps()
# and msf_peps(), the script behind docs/TNBC-TABLE.md (hela_table.py, behind docs/HELA-TABLE.md,
# carries identical functions). See CORPUS.md "Peptide counts".
def sage_peptides(tsv: Path) -> dict:
    """`peptides` is the decided rule (target+decoy). Diagnostics beside it (review F14): `target_peptides`
    (label == 1, the historical drivers' awk) and the decoy peptides inside the counted set."""
    import csv
    s, decoy, target = set(), set(), set()
    with open(tsv, newline="") as f:
        r = csv.reader(f, delimiter="\t")
        h = next(r, None)
        if not h or not {"peptide", "rank", "peptide_q", "label"} <= set(h):
            die("G-V10", "Sage TSV lacks peptide/rank/peptide_q/label columns: %s" % tsv)
        ip, ir, iq, il = h.index("peptide"), h.index("rank"), h.index("peptide_q"), h.index("label")
        for row in r:
            if row[ir] == "1" and float(row[iq]) <= 0.01:
                s.add(row[ip])
                (decoy if row[il] == "-1" else target).add(row[ip])
    return {"peptides": len(s), "target_peptides": len(target), "diag_decoy_peptides_in_set": len(decoy)}


def msf_peptides(tsv: Path) -> dict:
    import csv
    best = {}
    with open(tsv, newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        if not r.fieldnames or not {"peptide", "hyperscore"} <= set(r.fieldnames):
            die("G-V10", "MSFragger TSV lacks peptide/hyperscore columns: %s" % tsv)
        for row in r:
            key = (row["peptide"], row.get("modification_info", "") or row.get("assigned_modifications", ""))
            prots = [p for p in re.split(r"[,;@]", (row.get("proteins") or row.get("protein") or "")) if p]
            dec = all(p.startswith("rev_") for p in prots)
            hs = float(row["hyperscore"])
            if key not in best or hs > best[key][0]:
                best[key] = (hs, dec)
    t = d = acc = 0
    for hs, dec in sorted(best.values(), reverse=True):
        if dec:
            d += 1
        else:
            t += 1
        if t and d / t <= 0.01:
            acc = t
    return {"peptides": acc, "diag_distinct_keys": len(best)}

# ------------------------------------------------------------------------------- node: identity
def fingerprint(d: Path, with_acq=False, what=None) -> dict:
    """`what` names the input in messages: records and logs go to ceph and must not carry specimen ids."""
    tdf, tdfbin = Path(d) / "analysis.tdf", Path(d) / "analysis.tdf_bin"
    if not (tdf.is_file() and tdfbin.is_file()):
        die("G-V02", "no analysis.tdf + analysis.tdf_bin in %s" % (what or d))
    con = sqlite3.connect("file:%s?mode=ro&immutable=1" % urllib.parse.quote(str(tdf)), uri=True)
    try:
        meta = dict(con.execute("select Key, Value from GlobalMetadata where Key in "
                                "('AcquisitionDateTime', 'InstrumentSerialNumber')"))
        fp = {"tdf_bytes": tdf.stat().st_size, "tdf_bin_bytes": tdfbin.stat().st_size,
              "acq_datetime": meta.get("AcquisitionDateTime"), "instrument_serial": meta.get("InstrumentSerialNumber")}
        if with_acq:
            lo, hi = con.execute("select min(Time), max(Time) from Frames").fetchone()
            fp["acq_min"] = round((hi - lo) / 60.0, 1)
    finally:
        con.close()
    return fp


def check_pin(fp: dict, pin: dict, where: str) -> None:
    diff = {k: (pin.get(k), fp.get(k)) for k in PIN_KEYS if pin.get(k) != fp.get(k) or fp.get(k) is None}
    if diff:
        die("G-V02", "%s does not match its registry pin (pin, seen): %s" % (where, diff))


def strip_var(k: str) -> bool:
    return k.startswith(STRIP_PREFIX) or k in STRIP_EXACT
# ...
def flush_io(path) -> float:
    """syncfs the node-local filesystem before an arm's timer starts: the staging copy and the previous arm's
    multi-GB mzML are written back here, not inside the next arm (review F11)."""
    t0 = time.monotonic()
    try:
        import ctypes
        fd = os.open(str(path), os.O_RDONLY)
        try:
            if ctypes.CDLL(None, use_errno=True).syncfs(fd) != 0:
                raise OSError(ctypes.get_errno(), "syncfs")
        finally:
            os.close(fd)
    except (OSError, AttributeError):
        os.sync()
    return round(time.monotonic() - t0, 1)


def prewarm(staged: Path) -> float:
    """Before EACH arm (memory cold-first-read-inflates-wall): the first arm's writes may evict the cache."""
    t0 = time.monotonic()
    subprocess.run(["cat", str(staged / "analysis.tdf"), str(staged / "analysis.tdf_bin")],
                   stdout=subprocess.DEVNULL, check=True)
    return round(time.monotonic() - t0, 1)


def load_max(q: dict) -> float:
    """Plans cannot set the threshold (PLAN_KEYS); only a guardtest queue carries `load_max`."""
    return float(q["load_max"]) if q.get("load_max") is not None else (24.0 if (os.cpu_count() or 0) >= 200 else 12.0)


def load_gate(q: dict, patterns: list) -> dict:
    lmax = load_max(q)
    t0 = time.monotonic()
    while True:
        load, b = load1(), busy(patterns)
        waited = time.monotonic() - t0
        if (load <= lmax and not b) or waited >= q["load_wait_min"] * 60:
            return {"guard": "G-V06", "load_max": lmax, "load": load, "busy": b, "waited_s": round(waited),
                    "contended": load > lmax or bool(b)}
        time.sleep(POLL_S)


def remove_tree(p: Path) -> None:
    """rmtree that also clears read-only folders (a raw .d carries r-x `*.m` method folders)."""
    if p.is_dir() and not p.is_symlink():
        for d, _, _ in os.walk(p):
            os.chmod(d, 0o700)
    shutil.rmtree(p, ignore_errors=True)


def stage(q: dict, s: dict, pair_run: str) -> tuple:
    """Fresh 0700 node-local copy. diaTracer writes <input>_diatracer.mzML beside its input, so
    running it on the ceph path would overwrite (or let a driver reuse) the stale reference output
    that already sits there, and would write patient-derived output into the data directory.
    Data only, folders 0700: `cp -a` carried ceph ACLs and r-x method folders along, failed, and left
    a copy rmtree could not delete (first cluster proof, 2026-09-10)."""
    sroot = Path(q["root"]) / "stage"
    sroot.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(sroot, 0o700)
    d = sroot / ("%s-%s" % (s["id"], pair_run))
    d.mkdir(mode=0o700)
    raw = Path(s["raw"])
    fp_raw = fingerprint(raw, with_acq=True, what="raw of %s" % s["id"])
    check_pin(fp_raw, s["pin"], "raw of %s" % s["id"])
    if round(fp_raw["acq_min"], 1) != round(float(s["acq_min"]), 1):        # review F13: the table prints it
        die("G-V02", "raw of %s: acquisition %.1f min, registry acq_min %s" % (s["id"], fp_raw["acq_min"], s["acq_min"]))
    dst = d / (s["id"] + ".d")        # neutral name: command lines and tool logs carry no specimen id (review F10)
    t0 = time.monotonic()
    try:
        for sub, _, files in os.walk(raw):
            to = dst / Path(sub).relative_to(raw)
            to.mkdir(mode=0o700, parents=True, exist_ok=True)
            for f in files:
                shutil.copyfile(Path(sub) / f, to / f)
    except OSError as x:
        die("G-V07", "staging copy of %s failed: %s" % (s["id"], x.strerror or type(x).__name__))
    secs = time.monotonic() - t0
    fp = fingerprint(dst, what="staged copy of %s" % s["id"])
    check_pin(fp, s["pin"], "staged copy of %s" % s["id"])
    return dst, {"dir": str(d), "name": dst.name, "copy_s": round(secs, 1), "fingerprint": fp,
                 "acq_min_read": fp_raw["acq_min"]}


def neighbour(raw: str) -> list:
    """[size, mtime_ns] of the stale diaTracer reference beside the ceph raw; no path (records go to ceph)."""
    try:
        st = Path(raw[:-2] + "_diatracer.mzML").stat()
        return [st.st_size, st.st_mtime_ns]
    except FileNotFoundError:
        return [None, None]


def sample_record(s: dict) -> dict:
    """The sample as a record carries it: no raw path (in-house basenames are specimen ids), its sha256 instead."""
    return dict({k: v for k, v in s.items() if k != "raw"}, raw_sha256=hashlib.sha256(s["raw"].encode()).hexdigest())


# ------------------------------------------------------------------------------- node: commands
def cmd_dt(q, staged, wdir, tl):
    j = q["jnatmp"]
    return [TIME, "-v", "-o", str(tl), "java", "-Xmx400G", "-Djna.tmpdir=" + j, "-Djava.io.tmpdir=" + j,
            "-Djna.library.path=./ext/bruker", "-jar", q["diatracer_jar"], "-d", str(staged),
            "-t", str(q["threads"]), "-w", str(wdir)] + DT_PARAMS


def cmd_spx(q, spx_bin, staged, out, tl):
    return [TIME, "-v", "-o", str(tl), spx_bin, "-in", str(staged), "-out", str(out), "-threads", str(q["threads"])]


def cmd_patch(tp, mzml, out, tl):
    return [TIME, "-v", "-o", str(tl), "python3", tp["patch"], str(mzml), str(out)]


def cmd_sage(tp, mzml, odir, tl):
    return [TIME, "-v", "-o", str(tl), tp["sage"], tp["sage_config"], "-o", str(odir), SAGE_TELEMETRY, str(mzml)]


def cmd_fix(tp, mzml, out, tl):
    return [TIME, "-v", "-o", str(tl), "python3", tp["fix"], str(mzml), str(out)]


def cmd_msf(tp, tl):
    return [TIME, "-v", "-o", str(tl), "java", "-Xmx200G", "-jar", tp["msfragger_jar"], tp["msfragger_params"], "./in.mzML"]


def cmd_dwv(q, dwv_bin, staged, adir, tl, args):
    return [TIME, "-v", "-o", str(tl), dwv_bin, "-in", str(staged), "-out", str(adir), "-threads", str(q["threads"])] + list(args)


def cmd_reencode(tool, src, dst, tl):
    return [TIME, "-v", "-o", str(tl), tool, "-in", str(src), "-out", str(dst)] + list(REENCODE[1])


def run_logged(argv, cwd, env, log: Path) -> int:
    with open(log, "wb") as f:
        return subprocess.run(argv, cwd=str(cwd), env=env, stdout=f, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL).returncode


def say(msg: str) -> None:
    print("%s %s" % (now_iso(), msg), flush=True)


# ------------------------------------------------------------------------------- node: arms and pairs
def run_arm(q, tool, staged: Path, adir: Path, env, ident0, rec: dict, s: dict, nb: list) -> None:
    """`rec` is filled in place so a failed arm still leaves its partial record in the pair record."""
    adir.mkdir(parents=True)
    tl = adir / "time.log"
    if tool == "dt":
        cwd, e, log = q["diatracer_dir"], dict(env, LD_LIBRARY_PATH="./ext/bruker"), adir / "dt.log"
        out = staged.with_name(staged.name[:-2] + "_diatracer.mzML")
        argv = cmd_dt(q, staged, adir, tl)
    else:
        cwd, e, log, out = adir, env, adir / "e.log", adir / "pseudo.mzML"
        argv = cmd_spx(q, env["SPX_BIN"], staged, out, tl)
    if not str(staged).startswith(str(Path(q["root"]) / "stage") + os.sep):
        die("G-V07", "arm input outside the stage root: %s" % staged)
    check_identity(q, env, ident0, "before the %s arm" % tool)
    rec.update(tool=tool, cmd=argv, cwd=str(cwd), host=hostname(), cores=os.cpu_count(),
               sync_s=flush_io(q["root"]), prewarm_s=prewarm(staged))
    rec.update(ps_top=ps_top(), load_before=load1(), memavail_before_kb=mem_available_kb(), start=now_iso())
    with ArmMonitor(load_max(q)) as mon:
        t0 = time.time()
        rc = run_logged(argv, cwd, e, log)
    rec.update(end=now_iso(), start_epoch=t0, time_rc=rc, during=mon.summary(), load_after=load1(),
               memavail_after_kb=mem_available_kb())
    check_identity(q, env, ident0, "during the %s arm" % tool)
    if tool == "dt" and neighbour(s["raw"]) != nb:
        die_queue("G-V07", "the ceph neighbour _diatracer.mzML beside the raw of %s changed during the diaTracer arm" % s["id"])
    rec.update(parse_time_log(tl, "G-V08"))
    check_exit(rec, rc, "G-V08", tool)
    o = verify_mzml(out, t0)
    if tool == "dt":
        moved = adir / out.name
        os.replace(out, moved)                       # same filesystem: mtime kept
        o["path"] = str(moved)
        n = log_count(log, rb"Writing mzML file\.\.\.(\d+) scans")
    else:
        n = log_count(log, rb"Wrote (\d+) pseudo")
    rec.update(output=o, log_count=n)
    if n != o["count"]:
        die("G-V08", "%s: log count %s != spectrumList count %s" % (tool, n, o["count"]))


def run_pair(q, idx, s, env, ident0, meta, removed, patterns) -> bool:
    root = Path(q["root"])
    pair_run = time.strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex()
    order = list(TOOLS) if idx % 2 == 0 else list(reversed(TOOLS))
    rec = {"kind": "pair", "id": s["id"], "sample": sample_record(s), "pair_run": pair_run, "order": order,
           "node": hostname(), "plan": q["plan"], "harness_sha256": q["harness_sha256"],
           "measure_sha256": meta.get("measure"), "runtime": meta.get("runtime"), "identity": ident0, "label": meta["label"],
           "provenance": meta["provenance"], "env_removed": removed, "env_keys": sorted(env),
           "ld_library_path": env.get("LD_LIBRARY_PATH"), "threads": q["threads"],
           "started": now_iso(), "arms": {}, "status": "running"}
    for old in (root / "runs" / s["id"]).glob("*/*/*.mzML"):
        old.unlink()                                  # outputs of a superseded attempt
    sd = root / "stage" / ("%s-%s" % (s["id"], pair_run))
    err = None
    write_json(root / "records" / ("%s.pair.json" % s["id"]), rec)   # status shows the attempt, not the last one
    say("pair %s %s order %s" % (s["id"], pair_run, " -> ".join(order)))
    try:
        staged, rec["stage"] = stage(q, s, pair_run)
        rec["gate"] = load_gate(q, patterns)
        nb = rec["neighbour_before"] = neighbour(s["raw"])
        for tool in order:            # G-V09: an Abort in the first arm leaves the second unrun
            rec["arms"][tool] = {}
            run_arm(q, tool, staged, root / "runs" / s["id"] / pair_run / tool, env, ident0,
                    rec["arms"][tool], s, nb)
        rec["status"] = "ok"
    except Abort as a:
        rec.update(status="failed", guard=a.guard, message=a.message)
        err = a
    except Exception as x:
        rec.update(status="failed", guard="CRASH", message="%s: %s" % (type(x).__name__, x))
        err = x
    except BaseException as x:                        # SIGTERM (sys.exit) or ^C: never leave "running" behind
        rec.update(status="failed", guard="KILLED", message="%s during the pair" % type(x).__name__)
        err = x
    finally:
        remove_tree(sd)                               # patient-derived raw must not linger
        if sd.exists():                               # keep the first failure's reason in the record
            rec.update(status="failed", cleanup="G-V14 staged copy not deleted: %s" % sd)
            rec.setdefault("guard", "G-V14")
            rec.setdefault("message", "staged copy not deleted: %s" % sd)
        rec["ended"] = now_iso()
        write_json(root / "records" / ("%s.pair.json" % s["id"]), rec)
        say("pair %s %s %s" % (s["id"], rec["status"], "" if rec["status"] == "ok"
                               else "[%s] %s" % (rec.get("guard"), rec.get("message"))))
    if sd.exists():
        die_queue("G-V14", "staged copy not deleted: %s" % sd)
    if err is not None and (not isinstance(err, Abort) or err.queue):
        raise err
    return rec["status"] == "ok"

# ...
def run_search(q, s, tool, engine, pair, tools, env, ctx=None) -> bool:
    root, tp = Path(q["root"]), tools["paths"]
    o = pair["arms"][tool]["output"]
    mz = Path(o["path"])
    sdir = root / "runs" / s["id"] / pair["pair_run"] / "search" / ("%s_%s" % (tool, engine))
    rec = {"kind": "search", "id": s["id"], "tool": tool, "engine": engine, "pair_run": pair["pair_run"],
           "node": hostname(), "tools_sha256": tools["sha256"], "workers": q["search_workers"],
           "measure_sha256": {k: (ctx or {}).get("measure", {}).get(k) for k in ("search", "score")},
           "java": ((ctx or {}).get("ident", {}).get("java") or {}).get("version"),
           "started": now_iso(), "steps": {}, "status": "running"}
    err = None
    write_json(rec_path(root, s["id"], tool, engine), rec)

    def step(name, build, log):
        tl = sdir / (name + ".time")
        argv = build(tl)
        t = rec["steps"][name] = {"cmd": argv, "start": now_iso(), "start_epoch": time.time()}
        rc = run_logged(argv, sdir, env, sdir / log)
        t.update(parse_time_log(tl, "G-V10"), end=now_iso(), end_epoch=time.time(), time_rc=rc)
        check_exit(t, rc, "G-V10", name)
        return (sdir / log).read_bytes()

    try:
        st = mz.stat() if mz.is_file() else None
        if st is None or st.st_size != o["size"] or st.st_mtime != o["mtime"]:
            die("G-V11", "extractor output missing or changed since its pair: %s" % mz)
        check_fasta(tools)
        shutil.rmtree(sdir, ignore_errors=True)
        sdir.mkdir(parents=True)
        n_out = o["count"]
        rec["mzml_count"] = n_out
        if engine == "sage":
            inp = mz
            if tool == "dt":      # diaTracer omits selected ion m/z: Sage panics, a driver reads 0
                inp = sdir / "patched.mzML"
                step("patch", lambda tl: cmd_patch(tp, mz, inp, tl), "patch.log")
                rec["patched"] = log_count(sdir / "patch.log", rb"patched (\d+) precursor")
                if rec["patched"] != n_out:          # review F1: every spectrum, not just "some"
                    die("G-V10", "patch_diatracer_precursor.py patched %s of %d spectra: no selected ion m/z for the rest"
                        % (rec["patched"], n_out))
            log = step("engine", lambda tl: cmd_sage(tp, inp, sdir, tl), "sage.log")
            if b"finished in" not in log:
                die("G-V10", "Sage log lacks 'finished in'")
            rec["engine_spectra"] = engine_spectra(log, "sage")
            if rec["engine_spectra"] is None:
                die("G-V10", "Sage log lacks '- search: ... spectra/s'")
            if not SAGE_MIN_READ * n_out <= rec["engine_spectra"] <= n_out:
                die("G-V10", "Sage searched >= %d spectra of %d written: a partial read or another file"
                    % (rec["engine_spectra"], n_out))
            tsv, count = sdir / "results.sage.tsv", sage_peptides
        else:                     # both tools' mzML, as the historical drivers did
            if b"done:" not in step("fix", lambda tl: cmd_fix(tp, mz, sdir / "fixed.mzML", tl), "fix.log"):
                die("G-V10", "fix_mzml_cvparams.py did not report done")
            os.symlink("fixed.mzML", sdir / "in.mzML")
            log = step("engine", lambda tl: cmd_msf(tp, tl), "engine.log")
            if b"TOTAL TIME" not in log:
                die("G-V10", "MSFragger log lacks 'TOTAL TIME'")
            rec["engine_spectra"] = engine_spectra(log, "msfragger")
            if rec["engine_spectra"] != n_out:     # review F1: a zero-padded count or a per-spectrum NPE
                die("G-V10", "MSFragger read Scans = %s of %d spectra: a partial read" % (rec["engine_spectra"], n_out))
            tsv, count = sdir / "in.tsv", msf_peptides
        if not tsv.is_file():
            die("G-V10", "result TSV missing: %s" % tsv)
        with open(tsv, "rb") as f:
            if not (f.readline() and f.readline()):
                die("G-V10", "result TSV is header-only: %s" % tsv)
        rec.update(count(tsv), result_tsv=str(tsv))
        if rec["peptides"] <= 0:
            die("G-V10", "0 peptides at 1%%: a failed search, never a result (%s)" % tsv)
        rec["status"] = "ok"
    except Abort as a:
        rec.update(status="failed", guard=a.guard, message=a.message)
        err = a
    except Exception as x:
        rec.update(status="failed", guard="CRASH", message="%s: %s" % (type(x).__name__, x))
        err = x
    except BaseException as x:
        rec.update(status="failed", guard="KILLED", message="%s during the search" % type(x).__name__)
        err = x
    finally:
        if sdir.is_dir():
            for junk in list(sdir.glob("*.mzML")) + list(sdir.glob("*.mzBIN*")):
                junk.unlink()
        rec["ended"] = now_iso()
        write_json(root / "records" / ("%s.%s.%s.json" % (s["id"], tool, engine)), rec)
        say("search %s %s %s %s" % (s["id"], tool, engine, "ok %d peptides" % rec["peptides"] if rec["status"] == "ok"
                                     else "%s [%s] %s" % (rec["status"], rec.get("guard"), rec.get("message"))))
    if err is not None and (not isinstance(err, Abort) or err.queue):
        raise err
    return rec["status"] == "ok"
# ...
MEASURED = {
    "pair": (DT_PARAMS, STRIP_PREFIX, sorted(STRIP_EXACT), sorted(INHERIT_DROP), LIB_ROOTS, MON_S, MON_WINDOW_S, MEM_FLOOR,
             arm_env, strip_var, stage, fingerprint, check_pin, neighbour, load_max, load_gate, proc_snapshot, contention,
             ArmMonitor, flush_io, prewarm, cmd_dt, cmd_spx, run_logged, run_arm, run_pair, parse_time_log, check_exit,
             verify_mzml, log_count),
    "search": (SAGE_TELEMETRY, SAGE_MIN_READ, cmd_patch, cmd_sage, cmd_fix, cmd_msf, run_logged, run_search,
               engine_spectra, parse_time_log, check_exit, log_count),
    "score": (sage_peptides, msf_peptides),
}
```

## bench/entrapment.py (score and peptide_ratio, unchanged)
```python
    cuts = [0] + [i+1 for i in range(len(seq)-1) if seq[i] in 'KR' and seq[i+1] != 'P'] + [len(seq)]
    peps, n = set(), len(cuts)-1
    for i in range(n):
        for j in range(i+1, min(i+2+mc, n+1)):
            p = seq[cuts[i]:cuts[j]]
            if lo <= len(p) <= hi:
                m = 18.010565
                ok = True
                for a in p:
                    if a not in _AA: ok = False; break
                    m += _AA[a]
                if ok and mlo <= m <= mhi: peps.add(p)
    return peps

def peptide_ratio(fasta, tag="ENTRAP_"):
    """entrapment/target PEPTIDE-hypothesis ratio: |peptides UNIQUE to foreign| / |target peptides|."""
    tgt, ent, seq, is_ent = set(), set(), [], False
    def flush():
        if seq: (ent if is_ent else tgt).update(_digest("".join(seq)))
    with open(fasta) as f:
        for line in f:
            if line.startswith(">"):
                flush(); seq = []; is_ent = line[1:].startswith(tag)
            else: seq.append(line.strip())
        flush()
    return len(ent - tgt) / max(len(tgt), 1)

def _bootstrap_fdr(flags, ratio, B=1000, seed=1):
    """95% CI on the corrected target-FDR by resampling the accepted peptides (flags: 1=entrap)."""
    rng = random.Random(seed); n = len(flags)
    if n == 0: return (float("nan"), float("nan"))
    fdrs = []
    for _ in range(B):
        ne = 0; sample = (flags[rng.randrange(n)] for _ in range(n))
        ne = sum(sample)
        nt = n - ne
        fdrs.append(100.0 * (ne / ratio) / max(nt, 1) if ratio > 0 else float("nan"))
    fdrs.sort()
    return (fdrs[int(0.025*B)], fdrs[int(0.975*B)])


def build_entrapment(target_fa, foreign_fa, out_fa, tag="ENTRAP_"):
    """Concatenate a foreign proteome, prefixing every foreign accession."""
    n_t = n_e = 0
    with open(out_fa, "w") as out:
        with open(target_fa) as f:
            for line in f:
                if line.startswith(">"):
                    n_t += 1
                out.write(line)
        with open(foreign_fa) as f:
            for line in f:
                if line.startswith(">"):
                    n_e += 1
                    out.write(">" + tag + line[1:])
                else:
                    out.write(line)
    return n_t, n_e


def score(tsv, tag, ratio, q_field="peptide_q", q_cut=0.01):
    """Observed entrapment rate among peptides accepted at NOMINAL q_cut."""
    best = {}
    with open(tsv) as f:
        for x in csv.DictReader(f, delimiter="\t"):
            try:
                s = float(x["sage_discriminant_score"])
                q = float(x[q_field])
                prots = [p for p in x["proteins"].split(";") if p]
            except (ValueError, KeyError):
                continue
            if not prots or all(p.startswith("rev_") for p in prots):
                continue                      # decoys are Sage's model, not our measurement
            pep = x["peptide"]
            if pep not in best or s > best[pep][0]:
                # entrapment iff EVERY protein is foreign; a peptide shared with a human protein
                # is not evidence of error (shared tryptic peptides exist between proteomes)
                ent = all(p.startswith(tag) or p.startswith("rev_" + tag) for p in prots)
                best[pep] = (s, q, ent)
```

## bench/semantic_digest.py (unchanged)
```python
import hashlib, re, sys
MARK = b"<spectrumList"
END = b"</spectrumList>"
def digest(path):
    h = hashlib.sha256()
    started = False
    ended = False
    tail = b""
    pending = b""
    with open(path, "rb") as f:
        while True:
            c = f.read(1 << 22)
            if not c:
                break
            if not started:
                buf = tail + c
                i = buf.find(MARK)
                if i < 0:
                    tail = buf[-len(MARK):]
                    continue
                started = True
                c = buf[i:]
                # a run written tile by tile declares its count through a same-width zero-padded
                # placeholder (`count="0000611034"`); the number is the same, so normalise it --
                # on the COMPLETE opening line (a chunk boundary can fall inside the tag)
                while c.find(b"\n") < 0:
                    more = f.read(1 << 22)
                    if not more: break
                    c += more
                nl = c.find(b"\n")
                head = c if nl < 0 else c[:nl]
                c = re.sub(rb'count="0+(\d)', rb'count="\1', head, count=1) + (b"" if nl < 0 else c[nl:])
            # stop at </spectrumList>: the trailing <indexList> holds byte OFFSETS, which shift with any
            # header-length change (a 4-byte longer <software> version stamp moved every offset and
            # falsely flagged two spectrum-identical files as different, 2026-09-02).
            # The tag can straddle a chunk boundary: search the carry + chunk, hash everything but a
            # tag-length carry, and keep that carry for the next chunk (review finding, 2026-09-06).
            pending += c
            j = pending.find(END)
            if j >= 0:
                h.update(pending[:j + len(END)])
                ended = True
                break
            keep = len(END) - 1
            h.update(pending[:-keep])
            pending = pending[-keep:]
    if not started:
        raise SystemExit(f"{path}: no {MARK!r} found")
    if not ended:
        raise SystemExit(f"{path}: {MARK!r} without {END!r}: truncated or not an mzML spectrum list")
    return h.hexdigest()
if __name__ == "__main__":
    ds = [(p, digest(p)) for p in sys.argv[1:]]
    for p, d in ds:
        print(f"{d}  {p}")
    if len(ds) > 1:
        same = len({d for _, d in ds}) == 1
        print("SPECTRUM DATA " + ("IDENTICAL -> deterministic" if same else "DIFFERS -> NOT deterministic"))
        sys.exit(0 if same else 1)
```
