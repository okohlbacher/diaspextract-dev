# Adversarial review: `engines` plan option in the benchmark harness (commit 2d2f93d7e9c7)

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
dwv_pxd029836:
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
```

It also normalises one comparison in `table_guards` (a group record of a plan without cells stores `cells: {}`; the
plan dict has no `cells` key, so `p.get("cells") != plan.get("cells")` was `{} != None` and refused every table of
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
   `table_guards` (it is shared with the plain `render_table`), the `or {}` normalisation, and the new G-V13 engine
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
commit 2d2f93d7e9c7d240267ad26a3d297bdc677640e8
Author: Oliver <oliver.kohlbacher@uni-tuebingen.de>
Date:   Thu Sep 17 01:21:55 2026 +0200

    harness/corpus.py: optional plan key `engines` (Sage-only plans), G-V01/G-V13
    
    For the PXD029836 three-arm benchmark (diaTracer / DIAspeXtract / diaWeaver, Sage only; plan dwv_pxd029836 in the
    untracked samples.yaml). A plan may now name `engines: [sage]` (or `[msfragger]`); without the key both run, as before.
    
    - G-V01: `engines` must be a non-empty list of sage/msfragger in that order without repeats (the entrapment search
      keeps its own key). The key makes a plan extended: the plain queue always runs both engines.
    - q_engines follows the plan: status columns, pending searches, resume, and when an output is deleted.
    - phase 2: the MSFragger-first serial phase runs only when the plan runs MSFragger.
    - dry-run: only the engines' commands; the restriction is named.
    - table: the legend names the restriction; every column of an engine the plan does not run prints `-` (main,
      per-charge and per-arm rows). G-V13 refuses ok search records of an engine (or the entrapment search) the plan
      does not run (engines/entrapment changed after the run).
    - G-V13 fix found while reading the change back: a group record of a plan without cells stores `cells: {}`, the plan
      has no key (None), and the unnormalised comparison refused every table of such a plan (also an entrapment-only
      plan before this change). Both now mean no cells.
    - No measured function changed: pair/search/score 3215b73e/064af71b/4fe0a1ce and cells c586f871 (the hash
      dwv_stage1 was launched with; selftest now pins it as CELLS_MEASURE_DWV).
    - MSFragger jar/params and the msfragger_db pin stay required and checked for every plan, never run in a Sage-only one.
    
    Proof: selftest 284/284 (258 before); mutation proof 13/13 (each new check broken alone
    fails the selftest on that check; the unmutated control passes); old and new harness render byte-identical tables
    (plain; extended with two cells and entrapment; one cell with entrapment off; partial with pending rows) and
    dry-runs from the same records; dry-run --local of corpus_v3 (spock, data, ibminode05), corpus_v3_selftest_v130 and
    dwv_stage1 byte-identical; preflight --plan dwv_pxd029836 --node ibminode05 PREFLIGHT_OK (scratch copy).
    
    Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
---
 harness/README.md |   3 +-
 harness/corpus.py | 184 +++++++++++++++++++++++++++++++++++++++++++++---------
 2 files changed, 155 insertions(+), 32 deletions(-)

diff --git a/harness/README.md b/harness/README.md
index 6bfd14d..49391ce 100644
--- a/harness/README.md
+++ b/harness/README.md
@@ -6,7 +6,8 @@ write into the published benchmark tables.
 Head-to-head against diaTracer on the whole corpus (both extractors, Sage and MSFragger, wall and RSS,
 per-node queues) is `corpus.py`; see [CORPUS.md](CORPUS.md). A corpus plan may add extra extractor cells
 (diaWeaver: timed and capped, re-encoded before any search, no-op flagged) and an entrapment search reported
-per charge stratum ("Extended plans" in CORPUS.md, guards G-V16 to G-V19).
+per charge stratum, or run one search engine only (`engines: [sage]`) ("Extended plans" in CORPUS.md, guards
+G-V16 to G-V19).
 
 ```
 bench2.py   plan-check --plan P              # validate a plan; no side effects, no dirs created
diff --git a/harness/corpus.py b/harness/corpus.py
index cd534b6..7dd23cd 100644
--- a/harness/corpus.py
+++ b/harness/corpus.py
@@ -68,6 +68,9 @@ Extended plans (optional plan keys `cells`, `entrapment`; harness/CORPUS.md "Ext
         does not add up to the cell's count, an entrapment FASTA without ENTRAP_ peptides, 0 target peptides
         in the entrapment search
   (G-V03 for cells also: OPENMS_DATA_PATH not the arm's data tree, the provenance's data tree hash differs)
+  Optional plan key `engines` (a subset of sage/msfragger, e.g. a Sage-only plan; it makes a plan extended):
+  G-V01 refuses a value that is not a non-empty list of those names in that order without repeats; G-V13 refuses
+  a table whose ok search records name an engine (or the entrapment search) the plan does not run.
 """
 from __future__ import annotations
 
@@ -111,8 +114,9 @@ BUSY_FIXED = [r"diaTracer-2\.2\.[1]\.jar", r"MSFragger-4\.4\.[1]\.jar", r"/sag[e
 
 # ---- Extended plans: optional plan keys `cells` (extra extractors run after the reference pair, on the same staged
 # copy) and `entrapment` (a third search per output). A plan without either is the two-extractor pair above: the same
-# functions run and measure it, and its three measurement hashes do not move (selftest pins them).
-OPTIONAL_PLAN_KEYS = {"cells", "entrapment"}
+# functions run and measure it, and its three measurement hashes do not move (selftest pins them). `engines` (a subset
+# of ENGINES) restricts which searches run; it changes no measured function, only which search cells exist.
+OPTIONAL_PLAN_KEYS = {"cells", "entrapment", "engines"}
 CELL_KEYS = {"kind", "arm", "args", "wall_cap_h"}                 # plus optional differs_from
 CELL_NAME = r"[a-z][a-z0-9_]{0,23}"
 # One kind so far: diaWeaver (alhigaylan/diaWeaver, branch diaWeaver-2). Its env.sh exports `bin` and points
@@ -496,7 +500,8 @@ def cells(q: dict) -> dict:
 
 
 def extended(q: dict) -> bool:
-    return bool(cells(q) or q.get("entrapment"))
+    """`engines` makes a plan extended too: the plain queue (run_pair, phase 2) always runs both engines."""
+    return bool(cells(q) or q.get("entrapment") or "engines" in q)
 
 
 def q_tools(q: dict) -> tuple:
@@ -504,7 +509,7 @@ def q_tools(q: dict) -> tuple:
 
 
 def q_engines(q: dict) -> tuple:
-    return ENGINES + (("entrap",) if q.get("entrapment") else ())
+    return tuple(q.get("engines") or ENGINES) + (("entrap",) if q.get("entrapment") else ())
 
 
 def cell_env(q: dict, name: str) -> dict:
@@ -1997,7 +2002,7 @@ def _node_run(q: dict, root: Path) -> int:
                  for t in TOOLS if any(pending(s, t, e) for e in ENGINES)]
     rest, msf_ok = [], False
     for u in units:      # alone until one MSFragger search succeeded: a failed first one built no .pepindex (F8)
-        if not msf_ok and pending(u[0], u[1], "msfragger"):
+        if not msf_ok and "msfragger" in engines and pending(u[0], u[1], "msfragger"):
             failed += unit(u)
             msf_ok = not pending(u[0], u[1], "msfragger")
         else:
@@ -2044,8 +2049,10 @@ def dry_run(q: dict) -> None:
           % (" ".join(p + "*" for p in STRIP_PREFIX), " ".join(sorted(STRIP_EXACT)), q["spx_root"], q["arm"], q["jnatmp"]))
     if extended(q):
         print("# extended plan: cells %s (each: the same env rules on <spx_root>/<cell arm>/env.sh), entrapment %s; "
-              "measurement hashes pair/search/score/cells" % (", ".join("%s=%s" % (n, c["arm"]) for n, c in cells(q).items())
-                                                               or "none", "on" if q.get("entrapment") else "off"))
+              "measurement hashes pair/search/score/cells%s" % (", ".join("%s=%s" % (n, c["arm"]) for n, c in cells(q).items())
+                                                                 or "none", "on" if q.get("entrapment") else "off",
+                                                                 "; engines %s only (plan `engines`)" % ", ".join(q["engines"])
+                                                                 if "engines" in q else ""))
     names = list(cells(q))
     for i, s in enumerate(q["samples"]):
         order = list(TOOLS) if i % 2 == 0 else list(reversed(TOOLS))
@@ -2098,13 +2105,15 @@ def dry_run(q: dict) -> None:
             mz = pdir / tool / {"spx": "pseudo.mzML", "dt": s["id"] + "_diatracer.mzML"}.get(tool, "reencoded.mzML")
             sd = pdir / "search" / ("%s_sage" % tool)
             inp = mz
-            if tool == "dt":
-                inp = sd / "patched.mzML"
-                print("(cd %s && %s)" % (sd, j(cmd_patch(tp, mz, inp, sd / "patch.time"))))
-            print("(cd %s && %s)" % (sd, j(cmd_sage(tp, inp, sd, sd / "engine.time"))))
+            if "sage" in q_engines(q):
+                if tool == "dt":
+                    inp = sd / "patched.mzML"
+                    print("(cd %s && %s)" % (sd, j(cmd_patch(tp, mz, inp, sd / "patch.time"))))
+                print("(cd %s && %s)" % (sd, j(cmd_sage(tp, inp, sd, sd / "engine.time"))))
             sd = pdir / "search" / ("%s_msfragger" % tool)
-            print("(cd %s && %s && ln -s fixed.mzML in.mzML && %s)"
-                  % (sd, j(cmd_fix(tp, mz, sd / "fixed.mzML", sd / "fix.time")), j(cmd_msf(tp, sd / "engine.time"))))
+            if "msfragger" in q_engines(q):
+                print("(cd %s && %s && ln -s fixed.mzML in.mzML && %s)"
+                      % (sd, j(cmd_fix(tp, mz, sd / "fixed.mzML", sd / "fix.time")), j(cmd_msf(tp, sd / "engine.time"))))
             if not extended(q):
                 print("rm -f %s   # only after both engines succeeded" % mz)
                 continue
@@ -2569,9 +2578,14 @@ def load_plan(name: str, reg_path=REG) -> tuple:
 
 def check_extended(name: str, plan: dict) -> None:
     """G-V01 for the optional keys: `entrapment` a boolean; `cells` a mapping of names to exactly CELL_KEYS (plus
-    differs_from naming another cell of the same kind). A cell name is a path component and a record key."""
+    differs_from naming another cell of the same kind). A cell name is a path component and a record key. `engines`
+    a non-empty list of ENGINES names in ENGINES order, without repeats (the entrapment search has its own key)."""
     if "entrapment" in plan and not isinstance(plan["entrapment"], bool):
         die("G-V01", "plan %s: entrapment must be true or false, not %r" % (name, plan["entrapment"]))
+    eng = plan.get("engines")
+    if "engines" in plan and (not isinstance(eng, list) or not eng or [e for e in ENGINES if e in eng] != eng):
+        die("G-V01", "plan %s: engines must be a non-empty list of %s in that order without repeats, not %r"
+            % (name, list(ENGINES), eng))
     if "cells" not in plan:
         return
     cs = plan["cells"]
@@ -2890,6 +2904,10 @@ def table_guards(okp: list, oks: list, reg: dict, plan: dict) -> None:
         die("G-V13", "search records used different engines, configs or FASTAs")
     if any(not (r.get("measure_sha256") or {}).get("search") for r in oks) or not one(r["measure_sha256"] for r in oks):
         die("G-V13", "search records run or counted by different harness code (or without measurement hashes)")
+    other = sorted({r["engine"] for r in oks} - set(q_engines(plan)))
+    if other:
+        die("G-V13", "search records of %s, which the plan does not run: its `engines`/`entrapment` changed after the run"
+            % other)
     for p in okp:
         arms = [a for a in p["arms"].values() if a.get("status", "ok") == "ok"]
         if {a["host"] for a in p["arms"].values() if "host" in a} != {p["node"]}:
@@ -2899,7 +2917,8 @@ def table_guards(okp: list, oks: list, reg: dict, plan: dict) -> None:
             die("G-V13", "pair %s: record pin or raw path differs from samples.yaml" % p["id"])
         if any(a["output"]["count"] <= 0 or a["peak_rss_kb"] <= 0 for a in arms):
             die("G-V13", "pair %s: ok record with a spectrum count or RSS <= 0" % p["id"])
-        if p.get("cells") != plan.get("cells") or bool(p.get("entrapment")) != bool(plan.get("entrapment")):
+        # a group of a plan without cells records `cells: {}`; the plan has no key (None): both mean no cells
+        if (p.get("cells") or {}) != (plan.get("cells") or {}) or bool(p.get("entrapment")) != bool(plan.get("entrapment")):
             die("G-V13", "pair %s: record cells or entrapment differ from the plan" % p["id"])
     for r in oks:
         if r.get("peptides", 0) <= 0:
@@ -3106,22 +3125,23 @@ def render_cells_table(name, plan, reg, recs, source="scratch") -> tuple:
     for sid in ids:
         e, p = reg["samples"][sid], pairs.get(sid)
         S = {(t, g): search(sid, t, g) for t in tools for g in engines}
+        SG = lambda t_, g: S.get((t_, g), (None, "-"))          # an engine the plan does not run (`engines`): "-"
         A = {t: arm(sid, t) for t in tools}
         complete = all(A[t][0] for t in tools) and all(v[0] for v in S.values())
         for t in tools:
             a = A[t]
-            ratio = lambda g: "%.2f" % (S[t, g][0]["peptides"] / S["dt", g][0]["peptides"]) \
-                if t != "dt" and S[t, g][0] and S["dt", g][0] else "-"
-            swall = lambda g: fmt(S[t, g], lambda r: hms(r["steps"]["engine"]["wall_s"]))
+            ratio = lambda g: "%.2f" % (SG(t, g)[0]["peptides"] / SG("dt", g)[0]["peptides"]) \
+                if t != "dt" and SG(t, g)[0] and SG("dt", g)[0] else "-"
+            swall = lambda g: fmt(SG(t, g), lambda r: hms(r["steps"]["engine"]["wall_s"]))
             cores = lambda x: "%.1f" % (x["cpu"]["cpu_s"] / x["wall_s"]) if (x.get("cpu") or {}).get("cpu_s") is not None and x["wall_s"] > 0 else "-"
             main.append("| " + " | ".join([
                 str(e.get("label", sid)), "%.1f" % e["acq_min"], p["node"] if p else "-", names[t], flags(p, t) if p else "-",
                 fmt(a, lambda x: hms(x["wall_s"])), fmt(a, lambda x: "%.1f" % (x["peak_rss_kb"] / 1e6)), fmt(a, cores),
                 fmt(a, lambda x: num(x["output"]["count"])),
-                fmt(S[t, "sage"], lambda r: num(r["peptides"])), fmt(S[t, "sage"], lambda r: num(r.get("target_peptides"))),
-                ratio("sage"), fmt(S[t, "msfragger"], lambda r: num(r["peptides"])), ratio("msfragger"),
+                fmt(SG(t, "sage"), lambda r: num(r["peptides"])), fmt(SG(t, "sage"), lambda r: num(r.get("target_peptides"))),
+                ratio("sage"), fmt(SG(t, "msfragger"), lambda r: num(r["peptides"])), ratio("msfragger"),
                 swall("sage"), swall("msfragger")]) + " |")
-            bc = lambda g, z, k="peptides": fmt(S[t, g], lambda r: num(((r.get("by_charge") or {}).get(z) or {}).get(k)))
+            bc = lambda g, z, k="peptides": fmt(SG(t, g), lambda r: num(((r.get("by_charge") or {}).get(z) or {}).get(k)))
             charge.append("| " + " | ".join([str(e.get("label", sid)), names[t], bc("sage", "z1"), bc("sage", "z2p"),
                                              bc("sage", "z1", "target_peptides"), bc("sage", "z2p", "target_peptides"),
                                              bc("msfragger", "z1"), bc("msfragger", "z2p")]) + " |")
@@ -3155,16 +3175,18 @@ def render_cells_table(name, plan, reg, recs, source="scratch") -> tuple:
     summary = []
     tot = lambda f: sum(f(g) for g in full.values())
     ratio2 = lambda a, b: "%.2f" % (a / b) if b else "-"
+    # a total over an engine the plan does not run is None: num() and ratio2() print "-"
+    sm = lambda t_, g, f: tot(lambda x: f(x["search"][t_, g])) if g in engines else None
+    pep = lambda r: r["peptides"]
+    s_z2p = lambda r: r["by_charge"]["z2p"]["target_peptides"]
+    m_z2p = lambda r: r["by_charge"]["z2p"]["peptides"]
     for t in tools:
         if not full:
             break
-        sage, msf = tot(lambda g: g["search"][t, "sage"]["peptides"]), tot(lambda g: g["search"][t, "msfragger"]["peptides"])
-        s_z2 = tot(lambda g: g["search"][t, "sage"]["by_charge"]["z2p"]["target_peptides"])
-        m_z2 = tot(lambda g: g["search"][t, "msfragger"]["by_charge"]["z2p"]["peptides"])
-        d_s = tot(lambda g: g["search"]["dt", "sage"]["peptides"])
-        d_m = tot(lambda g: g["search"]["dt", "msfragger"]["peptides"])
-        d_sz2 = tot(lambda g: g["search"]["dt", "sage"]["by_charge"]["z2p"]["target_peptides"])
-        d_mz2 = tot(lambda g: g["search"]["dt", "msfragger"]["by_charge"]["z2p"]["peptides"])
+        sage, msf = sm(t, "sage", pep), sm(t, "msfragger", pep)
+        s_z2, m_z2 = sm(t, "sage", s_z2p), sm(t, "msfragger", m_z2p)
+        d_s, d_m = sm("dt", "sage", pep), sm("dt", "msfragger", pep)
+        d_sz2, d_mz2 = sm("dt", "sage", s_z2p), sm("dt", "msfragger", m_z2p)
         rows = [g["arms"][t] for g in full.values()]
         summary.append("| %s | %d | %d/%d | %s | %.1f | %s | %s | %s | %s | %s | %s | %s | %s |" % (
             names[t], len(full), sum(g["flagged"] for g in full.values()), len(full), hms(sum(a["wall_s"] for a in rows)),
@@ -3218,7 +3240,7 @@ Generated %(now)s by `harness/corpus.py table` (plan `%(name)s`, records from %(
   prefix with decoy/target <= 1%%, targets. Ratios are arm / %(dtl)s.
 - **Per charge**: each counted peptide in the stratum of its best counted PSM (Sage: highest
   sage_discriminant_score; MSFragger: the best-hyperscore PSM of its key); z1 + z2p equals the count (checked).
-%(entrap_line)s- **Measurement code**: pair `%(mpair)s`, search `%(msearch)s`, peptide rule `%(mscore)s`, cells `%(mcells)s`.
+%(engines_line)s%(entrap_line)s- **Measurement code**: pair `%(mpair)s`, search `%(msearch)s`, peptide rule `%(mscore)s`, cells `%(mcells)s`.
 - `FAILED G-Vxx` = a guard refused the cell (never a zero); `pending` = no current record; `-` = no arm or search.
 
 | sample | acq min | node | arm | flags | wall | RSS GB | CPU cores | spectra | Sage | Sage target | Sage vs dT | MSFragger | MSFragger vs dT | Sage wall | MSFragger wall |
@@ -3235,6 +3257,9 @@ Generated %(now)s by `harness/corpus.py table` (plan `%(name)s`, records from %(
                        "z1 + z2p equals all (checked). Never quote the `all` row without the strata.\n"
                        % (Path(plan["tools"]["sage_entrap"]).name, sh(tsha.get("sage_entrap")), sh(tsha.get(ENTRAP_DB)),
                           sh(tsha.get("entrapment")))) if plan.get("entrapment") else "",
+       "engines_line": ("- **Engines**: this plan runs %s only (plan `engines`); the columns of an engine it does not run "
+                        "print `-` (its tools stay installed and pinned, never run).\n" % " and ".join(plan["engines"]))
+                       if "engines" in plan else "",
        "mpair": str(pm.get("pair"))[:12], "msearch": str(pm.get("search"))[:12], "mscore": str(pm.get("score"))[:12],
        "mcells": str(pm.get("cells"))[:12]}
     parts = [head + "\n".join(main) + "\n",
@@ -3280,6 +3305,9 @@ MEASURED_CELLS = (sorted(CELL_KINDS.items()), REENCODE, NUMPRESS_CV, NUMPRESS_LI
 # The two-extractor pair as of DIAspeXtract 1.3.0 (CORPUS.md). selftest asserts these: an edit to a measured function
 # must change them here on purpose, knowing that every record of a plain plan then re-runs.
 PAIR_MEASURE_1_3_0 = {"pair": "3215b73e62ae", "search": "064af71b2bfe", "score": "4fe0a1cecefb"}
+# The extended-plan code the reviewed harness (0d8532d) measured dwv_stage1 with; dwv_pxd029836 reuses it. Same rule:
+# an edit that moves it re-runs every group and search of an extended plan, so change it here on purpose only.
+CELLS_MEASURE_DWV = "c586f8716617"
 
 
 def measure_sha256(extended=False) -> dict:
@@ -3365,6 +3393,7 @@ else:
 FAKE_SAGE = FAKE_HEAD + r'''
 odir, mz = arg("-o"), sys.argv[-1]
 assert os.path.exists(mz), mz
+time.sleep(float(os.environ.get("FAKE_SAGE_SLEEP", "0")))     # lets concurrent searches overlap (search_overlaps)
 zero = hit("FAKE_SAGE_ZERO", mz)
 badz = hit("FAKE_SAGE_BADZ", mz)
 rows = "".join("%d\tPEPTIDE%d\tsp|P%d|X\t1\tf.mzML\t%d\t1\t1\t%s\t%s\t%.2f\n"
@@ -3779,6 +3808,8 @@ def _selftest_extended(C, w: Path, q1: dict, q3: dict) -> None:
             {k: v[:12] for k, v in m0.items()} == PAIR_MEASURE_1_3_0, {k: v[:12] for k, v in m0.items()})
     C.check("COMPAT", "an extended plan adds a fourth hash (cells) and keeps the other three",
             set(mx) == {"pair", "search", "score", "cells"} and {k: mx[k] for k in m0} == m0)
+    C.check("COMPAT", "the cells measurement code is the dwv_stage1 code (CELLS_MEASURE_DWV; update on purpose only)",
+            mx["cells"][:12] == CELLS_MEASURE_DWV, mx["cells"][:12])
     plan_p = {k: q1[k] for k in PLAN_KEYS if k != "queues"}
     plan_p["queues"] = {"n1": {"samples": ["A"]}}
     qp = resolve_queue("pp", plan_p, {"samples": {s["id"]: s for s in q1["samples"]}}, "n1")
@@ -3806,7 +3837,7 @@ def _selftest_extended(C, w: Path, q1: dict, q3: dict) -> None:
 
     # ---- G-V01 extended plan validation
     xq = _xqueue(w, "AB", "x1", xt)
-    xplan = {k: xq[k] for k in (PLAN_KEYS | OPTIONAL_PLAN_KEYS) - {"queues"}}
+    xplan = {k: xq[k] for k in (PLAN_KEYS | OPTIONAL_PLAN_KEYS) - {"queues"} if k in xq}
     xplan["queues"] = {"n1": {"samples": ["A", "B"]}}
     samples = {s["id"]: {k: s[k] for k in SAMPLE_KEYS} for s in xq["samples"]}
 
@@ -3832,10 +3863,26 @@ def _selftest_extended(C, w: Path, q1: dict, q3: dict) -> None:
             ("entrapment without its tools", lambda pl: pl["tools"].pop("sage_entrap"), "tools need exactly"),
             ("cells without the digest tool", lambda pl: pl["tools"].pop("digest"), "tools need exactly"),
             ("entrapment without an entrap_fasta pin", lambda pl: pl["search_db_sha256"].pop("entrap_fasta"), "search_db_sha256"),
-            ("empty cells", lambda pl: pl.update(cells={}), "non-empty")):
+            ("empty cells", lambda pl: pl.update(cells={}), "non-empty"),
+            ("engines: sage (a string, not a list)", lambda pl: pl.update(engines="sage"), "engines must be"),
+            ("engines: [] (no engine)", lambda pl: pl.update(engines=[]), "engines must be"),
+            ("engines naming an unknown engine", lambda pl: pl.update(engines=["sage", "comet"]), "engines must be"),
+            ("engines with a repeat", lambda pl: pl.update(engines=["sage", "sage"]), "engines must be"),
+            ("engines out of ENGINES order", lambda pl: pl.update(engines=["msfragger", "sage"]), "engines must be"),
+            ("engines naming the entrapment search", lambda pl: pl.update(engines=["sage", "entrap"]), "engines must be"),
+            ("engines: null", lambda pl: pl.update(engines=None), "engines must be")):
         pl = json.loads(json.dumps(xplan))
         mut(pl)
         C.abort("G-V01", "extended plan refused: %s" % what, lambda pl=pl: load_plan("xp", pf(pl)), frag)
+    for eng in (["sage"], ["msfragger"], ["sage", "msfragger"]):
+        C.ok("G-V01", "extended plan with engines %s loads" % eng, lambda eng=eng: load_plan("xp", pf(dict(xplan, engines=eng))))
+    qe = resolve_queue("xp", *load_plan("xp", pf(dict(xplan, engines=["sage"]))), "n1")
+    C.check("G-V01", "engines reach the queue: Sage and the entrapment search only", q_engines(qe) == ("sage", "entrap")
+            and extended(qe) and q_engines(dict(qe, engines=None)) == ENGINES + ("entrap",), q_engines(qe))
+    qpe = resolve_queue("pe", dict(plan_p, engines=["sage"]), {"samples": {s["id"]: s for s in q1["samples"]}}, "n1")
+    C.check("G-V01", "engines alone make a plan extended (the plain queue always runs both engines), nothing else added",
+            extended(qpe) and q_tools(qpe) == TOOLS and q_engines(qpe) == ("sage",) and plan_tool_keys(qpe) == TOOL_KEYS
+            and db_keys(qpe) == DB_KEYS and not cells(qpe))
     C.abort("G-V01", "guardtest refused for an extended plan", lambda: _guardtest(dict(xq, plan="x_selftest"), Path(xq["root"])),
             "two-extractor pair only")
 
@@ -4190,6 +4237,81 @@ def _selftest_extended(C, w: Path, q1: dict, q3: dict) -> None:
     for what, junk in (("9 bytes", b"\0" * 9), ("a cut residual", vec[:-3])):
         C.abort("G-V17", "a corrupt numpress array is not decoded (%s)" % what, lambda junk=junk: _np_refuses(junk),
                 "undecodable")
+
+    # ---- plan key `engines`: a Sage-only plan with one cell and no entrapment (the dwv_pxd029836 shape)
+    so = _xqueue(w, "AB", "x7", xt, cells_={"dwv_default": DWV_CELLS["dwv_default"]})
+    so.pop("entrapment")
+    so.update(engines=["sage"], tools={k: v for k, v in so["tools"].items() if k not in ENTRAP_TOOL_KEYS},
+              search_db_sha256={k: v for k, v in so["search_db_sha256"].items() if k != ENTRAP_DB})
+    n_msf = len((w / "msf_times.log").read_text().splitlines())
+    os.environ["FAKE_SAGE_SLEEP"] = "0.4"
+    try:
+        rcs = node_run(so)
+    finally:
+        del os.environ["FAKE_SAGE_SLEEP"]
+    RS = _records(so)
+    ts = list(q_tools(so))
+    C.check("G-V10", "Sage-only plan: every arm searched by Sage and split by charge; no MSFragger run, record or fix step",
+            rcs == 0 and ts == ["dt", "spx", "dwv_default"]
+            and all(RS[s, "%s.sage" % t]["status"] == "ok" and "by_charge" in RS[s, "%s.sage" % t] for s in "AB" for t in ts)
+            and sorted(k[1] for k in RS if k[0] == "A") == ["dt.sage", "dwv_default.sage", "pair", "spx.sage"]
+            and len((w / "msf_times.log").read_text().splitlines()) == n_msf
+            and not list(Path(so["root"]).rglob("*_msfragger")) and not list(Path(so["root"]).rglob("*_entrap")),
+            (rcs, sorted(k[1] for k in RS)))
+    C.check("G-V10", "Sage-only plan: the searches run concurrently (search_workers 2): no MSFragger-first serial phase",
+            len(search_overlaps(list(RS.values()))) >= 2, sorted(search_overlaps(list(RS.values()))))
+    C.check("G-V14", "Sage-only plan: each output deleted once its only engine succeeded; no staged copy left",
+            not list(Path(so["root"]).rglob("*.mzML")) and not any((Path(so["root"]) / "stage").iterdir()))
+    starts = {k: r["started"] for k, r in RS.items()}
+    node_run(dict(so, nonce="sresume"))
+    C.check("G-V11", "Sage-only resume: groups and Sage searches verified and skipped (the outputs are gone)",
+            {k: r["started"] for k, r in _records(so).items()} == starts)
+    splan, sreg = _reg(so)
+    splan.update(cells=so["cells"], tools=so["tools"], engines=["sage"])
+    md, inc, tot = C.ok("G-V13", "Sage-only table renders", lambda: render_cells_table("s", splan, sreg, list(RS.values()))) \
+        or ("", -1, -1)
+    cols = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
+    sec = {x.split("\n", 1)[0]: x for x in md.split("\n## ")}
+    mrows = [cols(l) for l in md.split("\n## ")[0].splitlines() if l.startswith(("| A ", "| B "))]
+    crows = [cols(l) for l in sec.get("Peptides by precursor charge", "").splitlines() if l.startswith(("| A ", "| B "))]
+    srows = [cols(l) for l in sec.get("Per arm, complete samples only", "").splitlines()[4:] if l.startswith("| ")]
+    C.check("G-V13", "Sage-only table: 2/2 complete; 6 arm rows with Sage numbers and ratios, MSFragger `-`; per-charge "
+                     "and per-arm rows likewise; the engines line; no entrapment section",
+            inc == 0 and tot == 2 and len(mrows) == 6 and len(crows) == 6 and len(srows) == 3
+            and all(r[9] not in ("-", "0") and (r[11] == "-") == (r[3] == "diaTracer-2.2.1")
+                    and r[12] == r[13] == r[15] == "-" and r[14] != "-" for r in mrows)
+            and all(r[2] != "-" and r[6] == r[7] == "-" for r in crows)
+            and all(r[9] == r[10] == r[11] == r[12] == "-" and r[7] != "-" for r in srows)
+            and "this plan runs sage only" in md and "## Entrapment" not in md,
+            (inc, tot, mrows[:1], crows[:1], srows[:1]))
+    for what, eng in (("an MSFragger record (engines narrowed after the run)", "msfragger"),
+                      ("an entrapment record of a plan without entrapment", "entrap")):
+        more = json.loads(json.dumps(list(RS.values()))) + [dict(json.loads(json.dumps(RS["A", "spx.sage"])), engine=eng)]
+        C.abort("G-V13", "Sage-only table refuses %s" % what, lambda more=more: render_cells_table("s", splan, sreg, more),
+                "does not run")
+    buf = io.StringIO()
+    with contextlib.redirect_stdout(buf):
+        dry_run(so)
+    out = buf.getvalue()
+    C.check("DRY", "Sage-only dry-run: engines named, a Sage command for every arm, no MSFragger or fix command",
+            "engines sage only" in out and all("%s_sage" % t in out for t in ts) and "patched.mzML" in out
+            and "_msfragger" not in out and "fix_mzml_cvparams" not in out and "MSFragger-4.4.1.jar" not in out, out[-300:])
+    se = _queue(w, "C", root="x8", engines=["sage"])
+    rce = node_run(se)
+    RE = _records(se)
+    C.check("G-V10", "engines alone (no cells, no entrapment): the group runner runs the pair, then Sage only",
+            rce == 0 and RE["C", "pair"]["status"] == "ok" and "cells_failed" in RE["C", "pair"]
+            and sorted(RE["C", "pair"]["arms"]) == ["dt", "spx"] and sorted(k[1] for k in RE) == ["dt.sage", "pair", "spx.sage"],
+            sorted(k[1] for k in RE))
+    eplan, ereg = _reg(se)
+    eplan.update(tools=se["tools"], engines=["sage"])
+    mde = C.ok("G-V13", "Sage-only table without cells renders (the group's `cells: {}` equals the plan's absent key)",
+               lambda: render_cells_table("e", eplan, ereg, list(RE.values())))
+    C.check("G-V13", "  complete, two arm rows with Sage numbers, no cell section",
+            bool(mde) and mde[1] == 0 and "no cells" in mde[0] and "## Cell outputs" not in mde[0]
+            and len([l for l in mde[0].split("\n## ")[0].splitlines() if l.startswith("| C ")]) == 2, mde and mde[1])
+    C.abort("G-V13", "  but not against a plan that names a cell", lambda: render_cells_table(
+        "e", dict(eplan, cells={"dwv_default": DWV_CELLS["dwv_default"]}), ereg, list(RE.values())), "differ from the plan")
     os.environ["FAKE_MSF_SLEEP"] = "0.3"
 
 
```

## The commit (CORPUS.md)

```diff
commit 2d2f93d7e9c7d240267ad26a3d297bdc677640e8
Author: Oliver <oliver.kohlbacher@uni-tuebingen.de>
Date:   Thu Sep 17 01:21:55 2026 +0200

    harness/corpus.py: optional plan key `engines` (Sage-only plans), G-V01/G-V13
    
    For the PXD029836 three-arm benchmark (diaTracer / DIAspeXtract / diaWeaver, Sage only; plan dwv_pxd029836 in the
    untracked samples.yaml). A plan may now name `engines: [sage]` (or `[msfragger]`); without the key both run, as before.
    
    - G-V01: `engines` must be a non-empty list of sage/msfragger in that order without repeats (the entrapment search
      keeps its own key). The key makes a plan extended: the plain queue always runs both engines.
    - q_engines follows the plan: status columns, pending searches, resume, and when an output is deleted.
    - phase 2: the MSFragger-first serial phase runs only when the plan runs MSFragger.
    - dry-run: only the engines' commands; the restriction is named.
    - table: the legend names the restriction; every column of an engine the plan does not run prints `-` (main,
      per-charge and per-arm rows). G-V13 refuses ok search records of an engine (or the entrapment search) the plan
      does not run (engines/entrapment changed after the run).
    - G-V13 fix found while reading the change back: a group record of a plan without cells stores `cells: {}`, the plan
      has no key (None), and the unnormalised comparison refused every table of such a plan (also an entrapment-only
      plan before this change). Both now mean no cells.
    - No measured function changed: pair/search/score 3215b73e/064af71b/4fe0a1ce and cells c586f871 (the hash
      dwv_stage1 was launched with; selftest now pins it as CELLS_MEASURE_DWV).
    - MSFragger jar/params and the msfragger_db pin stay required and checked for every plan, never run in a Sage-only one.
    
    Proof: selftest 284/284 (258 before); mutation proof 13/13 (each new check broken alone
    fails the selftest on that check; the unmutated control passes); old and new harness render byte-identical tables
    (plain; extended with two cells and entrapment; one cell with entrapment off; partial with pending rows) and
    dry-runs from the same records; dry-run --local of corpus_v3 (spock, data, ibminode05), corpus_v3_selftest_v130 and
    dwv_stage1 byte-identical; preflight --plan dwv_pxd029836 --node ibminode05 PREFLIGHT_OK (scratch copy).
    
    Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

diff --git a/harness/CORPUS.md b/harness/CORPUS.md
index 1d42b55..bb838e3 100644
--- a/harness/CORPUS.md
+++ b/harness/CORPUS.md
@@ -43,8 +43,8 @@ The registry is read with a loader that refuses duplicate keys (PyYAML's `safe_l
 without a word), and no two samples of a plan may share a raw path or a pin (G-V01).
 
 A plan is a top-level section (`corpus_v3`, and the proof plans `corpus_v3_selftest`,
-`corpus_v3_selftest_r2`, `corpus_v3_selftest_v120`, `corpus_v3_selftest_v130`; the extended plan `dwv_stage1`)
-with exactly these keys, plus the optional `cells` and `entrapment` of an extended plan:
+`corpus_v3_selftest_r2`, `corpus_v3_selftest_v120`, `corpus_v3_selftest_v130`; the extended plans `dwv_stage1` and
+`dwv_pxd029836`) with exactly these keys, plus the optional `cells`, `entrapment` and `engines` of an extended plan:
 
 | key | meaning |
 |---|---|
@@ -61,6 +61,7 @@ with exactly these keys, plus the optional `cells` and `entrapment` of an extend
 | `queues` | `{node: {samples: [...], search_workers: N}}`; a sample may be in one queue only |
 | `cells` (optional) | `{name: {kind: dwv, arm, args: [...], wall_cap_h, differs_from?}}`: extra extractors, see below |
 | `entrapment` (optional) | `true`: a third search per output; `search_db_sha256` then also pins `entrap_fasta` |
+| `engines` (optional) | a non-empty list of `sage`/`msfragger` in that order, e.g. `[sage]`: only these searches run (default both); makes the plan extended |
 
 ---
 
@@ -198,7 +199,7 @@ triggered by `--selftest`, which fails if any id never fires.
 
 | id | level | refuses | failure it prevents |
 |---|---|---|---|
-| G-V01 | launch | unknown plan key, missing sample field or pin, sample in two queues, unknown sample/node, duplicate YAML key, two samples sharing a raw path or pin, sample count != `n_samples`, malformed `search_db_sha256` | a typo that parses and silently drops or duplicates a file |
+| G-V01 | launch | unknown plan key, missing sample field or pin, sample in two queues, unknown sample/node, duplicate YAML key, two samples sharing a raw path or pin, sample count != `n_samples`, malformed `search_db_sha256`; `engines` not a non-empty list of `sage`/`msfragger` in that order without repeats | a typo that parses and silently drops or duplicates a file; an engine name that silently runs nothing |
 | G-V02 | cell | raw or staged copy differs from the pin (tdf sizes, acquisition time, serial); the raw's acquisition length differs from `acq_min` | a row labelled with the wrong acquisition (FAILURE 1 of bench.py); a mistyped `acq min` in the table |
 | G-V03 | queue | env.sh missing/failing; SPX_BIN unset, not executable, or outside the arm directory; env.sh itself exporting a stripped variable (probe, allocator, OpenMP, JVM options); provenance missing or its `binary_sha256` differing; no label from `--help`; a library unresolved, or resolved outside the arm, `/ceph` and the system library directories | a dev build, a probe knob, a tcmalloc preload or a node-local OpenMS build tree measured as "the release" (critique C7, F7) |
 | G-V04 | queue | SPX_BIN, `lib/**`, a resolved library, the jar, `ext/bruker/` or the JDK changing across an arm | republish under a running chain (SIGBUS, silent empty run); a conda or JDK update between two arms |
@@ -210,7 +211,7 @@ triggered by `--selftest`, which fails if any id never fires.
 | G-V10 | cell | patch count != spectra; fix without `done:`; Sage without `finished in`, or searching < 50% (or > 100%) of the spectra; MSFragger without `TOTAL TIME`, or `Scans` != spectra; exit != 0; TSV missing, header-only or lacking columns; 0 peptides | the silent `Sage: 0` of unpatched diaTracer output; `Scans = 0` MSFragger runs; a partial read that lowers one tool's count |
 | G-V11 | cell | (resume) records of another build identity, JDK feature version, measurement code, thread count, pin, raw or pair_run; extractor output changed since its pair | skipping a run because an old mzML exists; a table mixing two verification or counting rules after a mid-run harness fix |
 | G-V12 | queue | run-local tool copy differs from its source (tools changed between launches); a database differs from the plan pin (preflight, queue start) or changed during the run | cells of one table searched with different configs or databases, found only when the table refuses after the run |
-| G-V13 | table | more than one build, JDK feature version, thread count, measurement code or search setup across records (or ok records without measurement hashes); pair arms on two hosts; ok record with count, RSS or peptides <= 0; record pin or raw differs from the registry | a table mixing builds, rules, nodes or corrupted records |
+| G-V13 | table | more than one build, JDK feature version, thread count, measurement code or search setup across records (or ok records without measurement hashes); pair arms on two hosts; ok record with count, RSS or peptides <= 0; record pin or raw differs from the registry; an ok search record of an engine (or the entrapment search) the plan does not run | a table mixing builds, rules, nodes or corrupted records; a plan whose `engines`/`entrapment` changed after the run |
 | G-V14 | queue/collect/purge | staged copy not deleted; collect or purge while the lock is held; destination not a `corpus_v3*` results directory; a collected path still group/other-accessible | patient-derived data lingering, or readable on ceph; writing into a published arm |
 | G-V15 | queue/launch | root under `/home`; `jnatmp` not writable; MemAvailable or `/proc` unreadable; python < 3.9; `TIME` not GNU `time -v`; no `java`; JDK feature versions differing across nodes (`preflight`) | the quota-killed "12 h JNA trap"; unrecorded memory state; a queue that crashes after 20 h without a marker |
 | G-V16 | cell | an extra cell's exit != 0 or signal; its wall cap passed or MemAvailable under 5% of MemTotal in 3 consecutive samples (the tool's session is killed); time log unparseable; `pseudo_spectra.mzML` missing, stale or unterminated; count <= 0; `Wrote N pseudo spectra` missing or different; the `Done. Output` finalisation line missing. A crash inside a cell fails that cell (`CRASH`), never the group | a diaWeaver run of unknown length holding a shared node for a day or pushing it into OOM; an output from before the final RT sort and rewrite accepted; one neighbour's memory dip or one parse error costing the other cell |
@@ -338,6 +339,20 @@ terms before/after, both digests, no-op result); totals per arm over complete sa
 differ from the plan, or more than one cell label or cell build. An ok search record without its charge split (a
 runner stopped between the two) renders as `pending`, never as a number.
 
+**Engines** (optional plan key `engines`, 2026-09-17). `engines: [sage]` runs Sage only (`[msfragger]` MSFragger
+only; the list must name `sage`/`msfragger` in that order without repeats, G-V01; the entrapment search keeps its own
+key). The key makes a plan extended (the plain queue always runs both engines), so a Sage-only plan without cells runs
+the group runner with the pair alone. It changes no measured function: the pair, search and score hashes stay
+`3215b73e`/`064af71b`/`4fe0a1ce` and the cells hash stays `c586f871` (selftest pins both, `CELLS_MEASURE_DWV`), so
+`dwv_stage1` records stay valid under this harness. What it changes: which search cells exist (`q_engines`: status
+columns, pending searches, when an output is deleted, resume); the MSFragger-first serial phase of phase 2 runs only
+when the plan runs MSFragger (a Sage-only plan searches with `search_workers` from the start); `dry-run` prints only
+the engines' commands and names the restriction; the table names it in its legend, prints `-` in every column of an
+engine the plan does not run (main rows, per-charge rows, per-arm totals), and refuses ok search records of such an
+engine (G-V13); a group of a plan without cells (`cells: {}`) matches the plan's absent key. The MSFragger jar, params
+and `msfragger_db` pin stay required and are copied and checked as for every
+plan, and never run.
+
 **Not covered.** `guardtest` refuses extended plans (it proves the pair). The plan's optional runs (MSFragger on
 the unfixed file, determinism repeats, dwv-author) are not implemented. Spectrum statistics exist for the cells
 only. Whether diaTracer and DIAspeXtract read a `.d` holding only the two tdf files exactly as a full `.d` is taken
@@ -375,6 +390,32 @@ python3 harness/corpus.py purge   --plan dwv_stage1 --node data
 If `preflight` shows `data` busy or loaded above 24 at launch time, rename the queue key to `ibminode05` in
 samples.yaml and use `--node ibminode05` throughout. The group can take up to ~26 h (two 12-h caps plus the pair).
 
+### PXD029836 three-arm benchmark: plan `dwv_pxd029836` (local, in the untracked samples.yaml)
+
+User request 2026-09-16: diaTracer, DIAspeXtract and diaWeaver on the three PXD029836 files, searched with Sage, with
+runtime and RSS. Samples `pxd_1418`, `pxd_1420`, `pxd_1422`: the public 200-ng P1 (SDC) HeLa triplicate of Demichev et
+al. 2022 (timsTOF Pro 2, 120.0-min acquisition, 16 window groups of 2 x 26 Th, m/z 100-1700, 1/K0 0.6-1.6; tdf_bin
+6.39-6.44 GB; about 0.82e9 MS1 and 1.49e9 MS2 peaks per file), from `/ceph/ibmi/abi/data/PXD029836/raw_d/` (SHA-1
+checked against PRIDE; the two tdf files' sha256 equal the laptop copy), scheme `PXD029836 HeLa 200ng SDC`, pins read
+with `node-pin` on ibminode05. Node `ibminode05` (128 cores, 995 GB; stage 1 holds `data`), `threads: 100`,
+`load_wait_min: 20`, `search_workers: 1`, `engines: [sage]`, no entrapment, results
+`/ceph/ibmi/abi/oliver/spextract/corpus_v3_dwv_pxd029836`, report `harness/dwv-pxd029836.md`. Arms: `dt` (diaTracer
+2.2.1, the corpus-v3 invocation), `spx` (arm `v1.3.0`) and one cell `dwv_default` (arm `diaweaver-7ed1169`, no args,
+`wall_cap_h: 16`). Tools and database pins as `corpus_v3`, plus `digest`. Worst case about 49 h: three 16-h caps plus
+three pairs (diaTracer about 5 min and up to 400 GB heap on a 120-min HeLa file, DIAspeXtract about 5 min) and nine
+Sage searches. diaWeaver's wall is set by its densest window (stage-1 smoke: 5 of 24 windows after 45 min on an
+11.5-min file), so a cell may reach its cap; a group with a failed cell re-runs whole on the next launch.
+
+```
+python3 harness/corpus.py preflight --plan dwv_pxd029836 --node ibminode05   # PREFLIGHT_OK; cell label and shas
+python3 harness/corpus.py dry-run   --plan dwv_pxd029836 --node ibminode05
+python3 harness/corpus.py launch    --plan dwv_pxd029836 --node ibminode05   # LAUNCH_OK
+until python3 harness/corpus.py status --plan dwv_pxd029836 --node ibminode05 | grep -q "lock free"; do sleep 900; done
+python3 harness/corpus.py collect --plan dwv_pxd029836 --node ibminode05
+python3 harness/corpus.py table   --plan dwv_pxd029836 --source ceph
+python3 harness/corpus.py purge   --plan dwv_pxd029836 --node ibminode05
+```
+
 ## Reading the table
 
 - One row per file, showing the scheme, acquisition minutes, and the node taken from the record's
@@ -516,6 +557,28 @@ The smoke also showed that diaWeaver processes all DIA windows at once and that
 time: 5 of 24 windows were done after 45 min at 32 threads on an 11.5-min file. Dataset D may reach the 12-h cap;
 read `cells_failed` before relaunching, because a group re-runs whole.
 
+### Engines option (2026-09-17)
+
+The plan key `engines` (above) with G-V01 and G-V13 checks. Selftest **284/284** (258 before): seven G-V01 refusals
+(a string, an empty list, an unknown engine, a repeat, the wrong order, `entrap`, null) and three accepted lists; the
+queue sees Sage (and the entrapment search) only; engines alone make a plan extended and add nothing else; a
+Sage-only queue with one cell and no entrapment (two samples) runs Sage for every arm with its charge split, never
+MSFragger (no run, record, fix step or directory), runs its searches concurrently, deletes every output and resumes
+without re-running anything; its table is complete with Sage numbers and ratios and `-` for MSFragger in the main,
+per-charge and per-arm rows, names the restriction and has no entrapment section; the table refuses an MSFragger or an
+entrapment record for that plan; its dry-run prints no MSFragger or fix command; a Sage-only plan without cells runs
+the pair and Sage only and its table renders; the cells hash equals the one `dwv_stage1` was launched with
+(`c586f871`). Found while reading the change back: G-V13 compared a group record's `cells: {}` with the plan's absent
+`cells` (None) unnormalised, so it would have refused every table of an extended plan without cells (also an
+entrapment-only plan, before this change); both now mean no cells, and a plan that names a cell still refuses such
+records. Mutation proof (scratchpad `mutate_engines.py`): 13 of 13 mutations killed, each new check broken alone in a
+copy of the final corpus.py (sha256 `d944dff1`) fails that copy's selftest on exactly that check; the unmutated
+control passes 284/284. Differential
+proof: the 0d8532d harness and this one render byte-identical tables (plain; extended with two cells and entrapment;
+one cell with entrapment off; a partial extended table with pending rows) and dry-runs from the same records, and
+`dry-run --local` of `corpus_v3` (spock, data, ibminode05), `corpus_v3_selftest_v130` and `dwv_stage1` is
+byte-identical.
+
 ## Guard test on a real node (`corpus.py guardtest --node data`)
 
 `selftest` proves the guard logic against fakes. `guardtest` proves the guards on the node itself: the
```

## Unchanged context: the functions the change interacts with (as committed)

```python
def cells(q: dict) -> dict:
    return q.get("cells") or {}


def extended(q: dict) -> bool:
    """`engines` makes a plan extended too: the plain queue (run_pair, phase 2) always runs both engines."""
    return bool(cells(q) or q.get("entrapment") or "engines" in q)


def q_tools(q: dict) -> tuple:
    return TOOLS + tuple(cells(q))


def q_engines(q: dict) -> tuple:
    return tuple(q.get("engines") or ENGINES) + (("entrap",) if q.get("entrapment") else ())


def plan_tool_keys(plan: dict) -> tuple:
    return TOOL_KEYS + (CELL_TOOL_KEYS if plan.get("cells") else ()) + (ENTRAP_TOOL_KEYS if plan.get("entrapment") else ())


def db_keys(plan: dict) -> tuple:
    return DB_KEYS + ((ENTRAP_DB,) if plan.get("entrapment") else ())


def run_group(q, idx, s, env, ident0, meta, removed, patterns, cenvs, digest) -> bool:
    """run_pair for an extended plan (G-V09 extended). The reference pair runs first, alternating as in run_pair, then
    every cell in plan order rotated by queue index, all on one staged copy, each synced and pre-warmed. A failed
    reference arm ends the attempt before any cell. A failed cell is recorded in its arm and the other cells still run
    (a wall-cap stop of one arm must not hide the next), but the group counts as done only when every arm is ok, so
    the next launch re-runs it whole (pair_done). run_pair itself stays untouched: it measures the plain plans."""
    root = Path(q["root"])
    pair_run = time.strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex()
    ref = list(TOOLS) if idx % 2 == 0 else list(reversed(TOOLS))
    names = list(cells(q))
    k = idx % len(names) if names else 0
    order = ref + names[k:] + names[:k]
    rec = {"kind": "pair", "id": s["id"], "sample": sample_record(s), "pair_run": pair_run, "order": order,
           "node": hostname(), "plan": q["plan"], "harness_sha256": q["harness_sha256"],
           "measure_sha256": meta.get("measure"), "runtime": meta.get("runtime"), "identity": ident0, "label": meta["label"],
           "provenance": meta["provenance"], "env_removed": removed, "env_keys": sorted(env),
           "ld_library_path": env.get("LD_LIBRARY_PATH"), "threads": q["threads"], "cells": cells(q),
           "cells_meta": meta.get("cells", {}), "entrapment": bool(q.get("entrapment")), "cells_failed": [],
           "started": now_iso(), "arms": {}, "status": "running"}
    for old in (root / "runs" / s["id"]).glob("*/*/*.mzML"):
        old.unlink()
    sd = root / "stage" / ("%s-%s" % (s["id"], pair_run))
    err = None
    write_json(root / "records" / ("%s.pair.json" % s["id"]), rec)
    say("group %s %s order %s" % (s["id"], pair_run, " -> ".join(order)))
    try:
        staged, rec["stage"] = stage_tdf(q, s, pair_run)
        rec["gate"] = load_gate(q, patterns)
        nb = rec["neighbour_before"] = neighbour(s["raw"])
        for tool in ref:
            rec["arms"][tool] = {}
            adir = root / "runs" / s["id"] / pair_run / tool
            run_arm(q, tool, staged, adir, env, ident0, rec["arms"][tool], s, nb)
            rec["arms"][tool]["cpu"] = time_cpu(adir / "time.log")
        for name in order[len(ref):]:
            a = rec["arms"][name] = {}
            try:
                run_cell(q, name, staged, root / "runs" / s["id"] / pair_run / name, cenvs[name], env, ident0, a, digest)
                a["status"] = "ok"
            except Exception as x:          # a crash inside one cell is that cell's failure, like a guard (review 2026-09-16)
                if isinstance(x, Abort) and x.queue:
                    raise
                g, msg = (x.guard, x.message) if isinstance(x, Abort) else ("CRASH", "%s: %s" % (type(x).__name__, x))
                a.update(status="failed", guard=g, message=msg)
                rec["cells_failed"].append(name)
                say("cell %s %s failed [%s] %s" % (s["id"], name, g, msg))
        noop_check(rec)
        rec["status"] = "ok"
    except Abort as a:
        rec.update(status="failed", guard=a.guard, message=a.message)
        err = a
    except Exception as x:
        rec.update(status="failed", guard="CRASH", message="%s: %s" % (type(x).__name__, x))
        err = x
    except BaseException as x:
        rec.update(status="failed", guard="KILLED", message="%s during the group" % type(x).__name__)
        err = x
    finally:
        remove_tree(sd)
        if sd.exists():
            rec.update(status="failed", cleanup="G-V14 staged copy not deleted: %s" % sd)
            rec.setdefault("guard", "G-V14")
            rec.setdefault("message", "staged copy not deleted: %s" % sd)
        rec["ended"] = now_iso()
        write_json(root / "records" / ("%s.pair.json" % s["id"]), rec)
        say("group %s %s%s %s" % (s["id"], rec["status"], " cells failed %s" % rec["cells_failed"] if rec["cells_failed"] else "",
                                  "" if rec["status"] == "ok" else "[%s] %s" % (rec.get("guard"), rec.get("message"))))
    if sd.exists():
        die_queue("G-V14", "staged copy not deleted: %s" % sd)
    if err is not None and (not isinstance(err, Abort) or err.queue):
        raise err
    return rec["status"] == "ok" and not rec["cells_failed"]


def search_done(rec, pair, ctx: dict) -> bool:
    """`cells` is the extended plans' fourth measurement hash; a plain plan has none on either side."""
    m = (rec or {}).get("measure_sha256") or {}
    return bool(rec and pair) and rec.get("status") == "ok" and rec.get("pair_run") == pair.get("pair_run") \
        and rec.get("tools_sha256") == ctx["tools_sha"] and m.get("search") == ctx["measure"]["search"] \
        and m.get("score") == ctx["measure"]["score"] and m.get("cells") == ctx["measure"].get("cells") \
        and rec.get("peptides", 0) > 0


def pair_done(rec, s, ctx: dict, root: Path) -> bool:
    """G-V11: a record is trusted only if it describes THIS build, JDK feature version, measurement code, thread
    count, cells and input, every arm finished ok, and every output it still has to feed a search is the very file it
    verified. An old mzML is never adopted. `ctx`: ident, tools_sha, measure, threads of the running queue (plus
    tools, engines and cells for an extended plan)."""
    ready = ready_arms(rec, s, ctx, root)
    return ready is not None and ready == list(ctx.get("tools", TOOLS))      # a failed cell is never ready


def ready_arms(rec, s, ctx: dict, root: Path):
    """None if the record is not of this build/code/threads/cells/input; else the arms (in plan order) that finished
    ok and whose output either fed every search already or is still the verified file."""
    ident = (rec or {}).get("identity") or {}
    m = (rec or {}).get("measure_sha256") or {}
    if not rec or rec.get("status") != "ok" or build_identity(ident) != build_identity(ctx["ident"]) \
            or java_major(ident) != java_major(ctx["ident"]) or rec.get("threads") != ctx["threads"] \
            or m.get("pair") != ctx["measure"]["pair"] or m.get("cells") != ctx["measure"].get("cells") \
            or rec.get("cells") != ctx.get("cells") \
            or rec["sample"].get("pin") != s["pin"] or rec["sample"].get("raw_sha256") != sample_record(s)["raw_sha256"]:
        return None
    ready = []
    for tool in ctx.get("tools", TOOLS):
        a = rec["arms"].get(tool) or {}
        o = a.get("output")
        if a.get("status", "ok") != "ok" or not o or o["count"] <= 0 or o["mtime"] <= a["start_epoch"]:
            continue
        if not all(search_done(read_json(rec_path(root, s["id"], tool, e)), rec, ctx) for e in ctx.get("engines", ENGINES)):
            p = Path(o["path"])
            if not p.is_file() or p.stat().st_size != o["size"] or p.stat().st_mtime != o["mtime"]:
                continue
        ready.append(tool)
    return ready


def rescore(root, samples: list, ctx: dict) -> int:
    """G-V11 (review F3): a search whose engine run is current but whose peptide rule changed is re-counted from
    its kept result TSV. The engine is not re-run (its mzML may be gone); the record keeps the old counts."""
    n = 0
    for s in samples:
        pair = read_json(rec_path(root, s["id"], "pair"))
        for tool in ctx.get("tools", TOOLS):
            for e in ENGINES:
                p = rec_path(root, s["id"], tool, e)
                r = read_json(p)
                m = (r or {}).get("measure_sha256") or {}
                if not (r and pair and r.get("status") == "ok" and r.get("pair_run") == pair.get("pair_run")
                        and r.get("tools_sha256") == ctx["tools_sha"] and m.get("search") == ctx["measure"]["search"]
                        and m.get("cells") == ctx["measure"].get("cells")
                        and m.get("score") != ctx["measure"]["score"] and Path(r.get("result_tsv") or "/nonexistent").is_file()):
                    continue
                keep = {k: r[k] for k in ("peptides", "target_peptides", "diag_decoy_peptides_in_set", "diag_distinct_keys") if k in r}
                r.update(rescored={"at": now_iso(), "score_sha256_before": m.get("score"), "counts_before": keep},
                         measure_sha256=dict(m, score=ctx["measure"]["score"]))
                try:
                    r.update((sage_peptides if e == "sage" else msf_peptides)(Path(r["result_tsv"])))
                    if r["peptides"] <= 0:
                        die("G-V10", "0 peptides at 1%% after re-counting %s" % r["result_tsv"])
                except Abort as a:
                    r.update(status="failed", guard=a.guard, message=a.message)
                write_json(p, r)
                if "cells" in ctx["measure"] and r["status"] == "ok":      # the split follows the new count
                    add_split(root, s["id"], tool, e, ctx)
                say("search %s %s %s re-counted: %s -> %s peptides" % (s["id"], tool, e, keep.get("peptides"), r.get("peptides")))
                n += 1
    return n


def sweep_outputs(root, samples: list, ctx: dict) -> list:
    """Delete each extractor mzML whose two searches are done (review F9: a runner killed between the second ok
    record and the unlink left it behind for good). Returns every mzML/mzBIN still under runs/."""
    for s in samples:
        pair = read_json(rec_path(root, s["id"], "pair"))
        if not pair or pair.get("status") != "ok":
            continue
        for tool in ctx.get("tools", TOOLS):
            o = (pair["arms"].get(tool) or {}).get("output")
            if o and all(search_done(read_json(rec_path(root, s["id"], tool, e)), pair, ctx)
                         for e in ctx.get("engines", ENGINES)):
                Path(o["path"]).unlink(missing_ok=True)
    return leftovers(root)


def _node_run(q: dict, root: Path) -> int:
    (root / ("runner-%s.pid" % q["nonce"])).write_text("%d\n" % os.getpid())
    try:
        Path(q["jnatmp"]).mkdir(parents=True, exist_ok=True)
        tempfile.NamedTemporaryFile(dir=q["jnatmp"]).close()
    except OSError as x:
        die_queue("G-V15", "jnatmp %s not writable: %s" % (q["jnatmp"], x))
    mem_available_kb()
    remove_tree(root / "stage")                           # a killed runner's staged raw
    if (root / "stage").exists():
        die_queue("G-V14", "leftover staged copies could not be deleted: %s" % (root / "stage"))
    env, removed = arm_env(q)
    runtime = preflight(q, env)
    ext = extended(q)
    cenvs = {n: cell_env(q, n) for n in cells(q)}
    ident0 = identity(q, env)
    meta = arm_meta(env, ident0)
    if cells(q):
        meta["cells"] = cells_meta(q, cenvs, ident0)
    tools = install_tools(q)
    ctx = {"ident": ident0, "tools_sha": tools["sha256"], "measure": measure_sha256(ext), "threads": q["threads"]}
    if ext:
        ctx.update(tools=list(q_tools(q)), engines=list(q_engines(q)), cells=cells(q))
    digest = load_module(tools["paths"]["digest"], "semantic_digest_runlocal").digest if cells(q) else None
    meta.update(measure=ctx["measure"], runtime=runtime)
    patterns = busy_patterns(env, cenvs)
    say("QUEUE_START plan %s node %s cores %s load %.1f label %s binary %s jar %s java %s harness %s measure %s "
        "samples %d removed %s" % (q["plan"], hostname(), os.cpu_count(), load1(), meta["label"],
                                   ident0["binary_sha256"][:16], ident0["jar_sha256"][:16], runtime["java"]["version"],
                                   q["harness_sha256"][:16], "/".join(v[:8] for v in ctx["measure"].values()),
                                   len(q["samples"]), removed)
        + ("".join(" cell %s %s %s" % (n, meta["cells"][n]["label"], ident0["cells"][n]["binary_sha256"][:16])
                   for n in cells(q)) + (" entrapment" if q.get("entrapment") else "") if ext else ""))
    n = rescore(root, q["samples"], ctx)
    if n:
        say("RESCORED %d search cell(s) from their kept result TSVs (peptide rule changed)" % n)
    sweep_outputs(root, q["samples"], ctx)
    failed = 0
    for i, s in enumerate(q["samples"]):             # phase 1: timed pairs, one at a time, no searches
        if pair_done(read_json(rec_path(root, s["id"], "pair")), s, ctx, root):
            say("pair %s already done (record verified): skipped" % s["id"])
            continue
        if ext:
            failed += not run_group(q, i, s, env, ident0, meta, removed, patterns, cenvs, digest)
        else:
            failed += not run_pair(q, i, s, env, ident0, meta, removed, patterns)
    say("PHASE1_DONE failed %d" % failed)
    pairs = {s["id"]: read_json(rec_path(root, s["id"], "pair")) for s in q["samples"]}
    engines = ctx.get("engines", ENGINES)

    def pending(s, tool, e):
        return not search_done(read_json(rec_path(root, s["id"], tool, e)), pairs[s["id"]], ctx)

    def one_search(s, tool, e):
        if e == "entrap":
            return run_entrap(q, s, tool, pairs[s["id"]], tools, env, ctx)
        ok = run_search(q, s, tool, e, pairs[s["id"]], tools, env, ctx)
        return add_split(root, s["id"], tool, e, ctx) if ok and ext else ok

    def unit(u):                                      # -> number of failed search cells
        s, tool = u
        # a cell's own libraries run its re-encode, never an engine: every search runs in the reference arm's env
        oks = [one_search(s, tool, e) if pending(s, tool, e) else True for e in engines]
        if all(oks):                                  # every engine succeeded: the mzML goes
            Path(pairs[s["id"]]["arms"][tool]["output"]["path"]).unlink(missing_ok=True)
        return oks.count(False)

    if ext:        # every ok arm of a current group is searched, also when another cell of the group failed
        units = [(s, t) for s in q["samples"] for t in (ready_arms(pairs[s["id"]], s, ctx, root) or [])
                 if any(pending(s, t, e) for e in engines)]
    else:
        units = [(s, t) for s in q["samples"] if pair_done(pairs[s["id"]], s, ctx, root)
                 for t in TOOLS if any(pending(s, t, e) for e in ENGINES)]
    rest, msf_ok = [], False
    for u in units:      # alone until one MSFragger search succeeded: a failed first one built no .pepindex (F8)
        if not msf_ok and "msfragger" in engines and pending(u[0], u[1], "msfragger"):
            failed += unit(u)
            msf_ok = not pending(u[0], u[1], "msfragger")
        else:
            rest.append(u)
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=q["search_workers"])
    try:
        failed += sum(ex.map(unit, rest))
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
    left = sweep_outputs(root, q["samples"], ctx)
    say("QUEUE_DONE failed %d mzml_left %d%s" % (failed, len(left), (" " + " ".join(left[:6])) if left else ""))
    (root / ("QUEUE_DONE-%s" % q["nonce"])).write_text("failed %d\n" % failed)
    return 0 if failed == 0 else 1


def load_plan(name: str, reg_path=REG) -> tuple:
    reg = _registry(reg_path)
    plan = reg.get(name)
    if not isinstance(plan, dict):
        die("G-V01", "no plan section %r in %s" % (name, reg_path))
    check_extended(name, plan)
    tk = plan_tool_keys(plan)
    if set(plan) - OPTIONAL_PLAN_KEYS != PLAN_KEYS or not isinstance(plan["tools"], dict) or set(plan["tools"]) != set(tk):
        die("G-V01", "plan %s: unknown keys %s, missing keys %s (tools need exactly %s)"
            % (name, sorted(set(plan) - PLAN_KEYS - OPTIONAL_PLAN_KEYS), sorted(PLAN_KEYS - set(plan)), tk))
    seen = {}
    for node, qd in plan["queues"].items():
        if not isinstance(qd, dict) or set(qd) - {"search_workers", "samples"} or not qd.get("samples"):
            die("G-V01", "queue %s: needs `samples` (and optionally `search_workers`) only" % node)
        for sid in qd["samples"]:
            if sid in seen:
                die("G-V01", "sample %s is in queues %s and %s" % (sid, seen[sid], node))
            seen[sid] = node
            e = (reg.get("samples") or {}).get(sid)
            if not e:
                die("G-V01", "sample %s not in samples.yaml" % sid)
            pin = e.get("pin") if isinstance(e.get("pin"), dict) else {}
            miss = [k for k in SAMPLE_KEYS if e.get(k) in (None, "")] + ["pin." + k for k in PIN_KEYS if pin.get(k) in (None, "")]
            if miss or not str(e["raw"]).endswith(".d"):
                die("G-V01", "sample %s: missing %s, or raw is not a .d" % (sid, miss))
    db = plan["search_db_sha256"]
    if not isinstance(db, dict) or set(db) != set(db_keys(plan)) or not all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in db.values()):
        die("G-V01", "plan %s: search_db_sha256 needs exactly %s as sha256 hex" % (name, db_keys(plan)))
    raws, pins = {}, {}
    for sid in seen:              # review F12: a row pasted twice under two ids counts twice in every total
        e = reg["samples"][sid]
        for tag, table, key in (("raw path", raws, os.path.normpath(str(e["raw"]))),
                                ("pin", pins, json.dumps(e["pin"], sort_keys=True))):
            if key in table:
                die("G-V01", "samples %s and %s share one %s: a duplicated row" % (table[key], sid, tag))
            table[key] = sid
    if type(plan["n_samples"]) is not int or plan["n_samples"] != len(seen):
        die("G-V01", "plan %s lists %d samples but n_samples is %r: a dropped or added file"
            % (name, len(seen), plan["n_samples"]))
    return plan, reg


def check_extended(name: str, plan: dict) -> None:
    """G-V01 for the optional keys: `entrapment` a boolean; `cells` a mapping of names to exactly CELL_KEYS (plus
    differs_from naming another cell of the same kind). A cell name is a path component and a record key. `engines`
    a non-empty list of ENGINES names in ENGINES order, without repeats (the entrapment search has its own key)."""
    if "entrapment" in plan and not isinstance(plan["entrapment"], bool):
        die("G-V01", "plan %s: entrapment must be true or false, not %r" % (name, plan["entrapment"]))
    eng = plan.get("engines")
    if "engines" in plan and (not isinstance(eng, list) or not eng or [e for e in ENGINES if e in eng] != eng):
        die("G-V01", "plan %s: engines must be a non-empty list of %s in that order without repeats, not %r"
            % (name, list(ENGINES), eng))
    if "cells" not in plan:
        return
    cs = plan["cells"]
    if not isinstance(cs, dict) or not cs:
        die("G-V01", "plan %s: cells must be a non-empty mapping of cell name to its settings" % name)
    for n, c in cs.items():
        if not isinstance(n, str) or not re.fullmatch(CELL_NAME, n) or n in TOOLS + ENGINES + ("entrap", "pair", "search"):
            die("G-V01", "plan %s: cell name %r must match %s and not be a reserved name" % (name, n, CELL_NAME))
        if not isinstance(c, dict) or not CELL_KEYS <= set(c) <= CELL_KEYS | {"differs_from"}:
            die("G-V01", "cell %s: needs exactly %s (and optionally differs_from), got %s"
                % (n, sorted(CELL_KEYS), sorted(c) if isinstance(c, dict) else c))
        if c["kind"] not in CELL_KINDS:
            die("G-V01", "cell %s: unknown kind %r (known: %s)" % (n, c["kind"], sorted(CELL_KINDS)))
        if not isinstance(c["arm"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", c["arm"]):
            die("G-V01", "cell %s: arm %r is not a directory name under spx_root" % (n, c["arm"]))
        if not isinstance(c["args"], list) or not all(isinstance(a, str) for a in c["args"]) \
                or set(c["args"]) & {"-in", "-out", "-threads", "-ini"}:
            die("G-V01", "cell %s: args must be a list of strings without -in/-out/-threads/-ini (the harness sets "
                         "those): %r" % (n, c["args"]))
        if type(c["wall_cap_h"]) not in (int, float) or not 0 < c["wall_cap_h"] <= 72:
            die("G-V01", "cell %s: wall_cap_h must be a number in (0, 72], got %r" % (n, c["wall_cap_h"]))
        ref = c.get("differs_from", n)
        if "differs_from" in c and (ref == n or ref not in cs or not isinstance(cs[ref], dict)
                                    or cs[ref].get("kind") != c["kind"]):
            die("G-V01", "cell %s: differs_from %r must name another cell of kind %s" % (n, ref, c["kind"]))


def resolve_queue(name: str, plan: dict, reg: dict, node: str) -> dict:
    if node not in plan["queues"]:
        die("G-V01", "plan %s has no queue for node %s" % (name, node))
    qd = plan["queues"][node]
    q = {k: plan[k] for k in PLAN_KEYS if k != "queues"}
    q.update({k: plan[k] for k in OPTIONAL_PLAN_KEYS if k in plan})
    q.update(plan=name, node=node, nonce=time.strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex(),
             root=node_root(plan, node), lock=lock_path(plan), harness_sha256=sha256(SELF),
             search_workers=int(qd.get("search_workers", 1)),
             samples=[dict({k: reg["samples"][sid][k] for k in SAMPLE_KEYS}, id=sid,
                           label=reg["samples"][sid].get("label", sid)) for sid in qd["samples"]])
    return q


def cmd_status(args) -> int:
    plan, _ = load_plan(args.plan)
    cols = ["pair"] + ["%s.%s" % (t, e) for t in q_tools(plan) for e in q_engines(plan)]
    wd = max([15] + [len(c) + 1 for c in cols])
    for node in [args.node] if args.node else list(plan["queues"]):
        s = remote(node, "node-status", {"root": node_root(plan, node), "lock": lock_path(plan)})
        print("\n== %s (host %s) load %.1f  lock %s  stage leftovers %s"
              % (node, s["host"], s["load1"], "HELD " + s["lock_info"] if s["lock_held"] else "free", s["stage_left"] or "none"))
        recs = {(r["id"], "pair" if r["kind"] == "pair" else "%s.%s" % (r["tool"], r["engine"])): r for r in s["records"]}
        print("%-10s " % "sample" + " ".join("%-*s" % (wd, c) for c in cols))
        for sid in plan["queues"][node]["samples"]:
            pair, row = recs.get((sid, "pair")), []
            for c in cols:
                r = recs.get((sid, c))
                if r is None:
                    row.append("-")
                elif r["status"] != "ok":
                    row.append("%s %s" % (r["status"], r.get("guard", "")))
                elif c == "pair":
                    row.append("ok" if not r.get("cells_failed") else "ok, %d failed" % len(r["cells_failed"]))
                else:
                    row.append("ok %s" % r["peptides"] if pair and r["pair_run"] == pair["pair_run"] else "stale")
            fl = group_flags(pair) if pair else "-"
            print("%-10s " % sid + " ".join("%-*s" % (wd, c) for c in row) + ("" if fl == "-" else "  " + fl))
            for n in (pair or {}).get("cells_failed") or []:
                a = pair["arms"][n]
                print("  cell %s FAILED [%s] %s" % (n, a.get("guard"), a.get("message")))
        if s.get("mzml_left"):
            print("  mzML/mzBIN under runs/: %d (%s)" % (len(s["mzml_left"]), ", ".join(s["mzml_left"][:4])))
        for line in s["log_tail"][-6:]:
            print("  | " + line)
    return 0


def table_guards(okp: list, oks: list, reg: dict, plan: dict) -> None:
    """G-V13 over the ok pair/group and search records of one table."""
    one = lambda xs: len({json.dumps(x, sort_keys=True) for x in xs}) <= 1
    if not one(build_identity(p["identity"]) for p in okp) or not one(p["label"] for p in okp):
        die("G-V13", "records come from more than one binary/lib/jar: one table, one build")
    if not one({n: m.get("label") for n, m in (p.get("cells_meta") or {}).items()} for p in okp):
        die("G-V13", "cell records carry more than one tool label: one table, one build")
    if not one(java_major(p["identity"]) for p in okp):
        die("G-V13", "pair records ran on different Java feature versions: %s" % sorted({str(java_major(p["identity"])) for p in okp}))
    if any(not (p.get("measure_sha256") or {}).get("pair") for p in okp) or not one(p["measure_sha256"] for p in okp) \
            or not one(p.get("threads") for p in okp):
        die("G-V13", "pair records measured by different harness code or thread counts (or without measurement hashes)")
    if not one(r["tools_sha256"] for r in oks):
        die("G-V13", "search records used different engines, configs or FASTAs")
    if any(not (r.get("measure_sha256") or {}).get("search") for r in oks) or not one(r["measure_sha256"] for r in oks):
        die("G-V13", "search records run or counted by different harness code (or without measurement hashes)")
    other = sorted({r["engine"] for r in oks} - set(q_engines(plan)))
    if other:
        die("G-V13", "search records of %s, which the plan does not run: its `engines`/`entrapment` changed after the run"
            % other)
    for p in okp:
        arms = [a for a in p["arms"].values() if a.get("status", "ok") == "ok"]
        if {a["host"] for a in p["arms"].values() if "host" in a} != {p["node"]}:
            die("G-V13", "pair %s: arms on %s, record node %s" % (p["id"], sorted(a["host"] for a in p["arms"].values()), p["node"]))
        e = reg["samples"].get(p["id"]) or {}
        if e.get("pin") != p["sample"]["pin"] or p["sample"].get("raw_sha256") != hashlib.sha256(str(e.get("raw")).encode()).hexdigest():
            die("G-V13", "pair %s: record pin or raw path differs from samples.yaml" % p["id"])
        if any(a["output"]["count"] <= 0 or a["peak_rss_kb"] <= 0 for a in arms):
            die("G-V13", "pair %s: ok record with a spectrum count or RSS <= 0" % p["id"])
        # a group of a plan without cells records `cells: {}`; the plan has no key (None): both mean no cells
        if (p.get("cells") or {}) != (plan.get("cells") or {}) or bool(p.get("entrapment")) != bool(plan.get("entrapment")):
            die("G-V13", "pair %s: record cells or entrapment differ from the plan" % p["id"])
    for r in oks:
        if r.get("peptides", 0) <= 0:
            die("G-V13", "search %s %s %s: ok record with %s peptides" % (r["id"], r["tool"], r["engine"], r.get("peptides")))


def render_table(name, plan, reg, recs, source="scratch") -> tuple:
    pairs = {r["id"]: r for r in recs if r["kind"] == "pair"}
    srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r["kind"] == "search"}
    okp = [p for p in pairs.values() if p["status"] == "ok"]
    oks = [r for r in srch.values() if r["status"] == "ok"]
    table_guards(okp, oks, reg, plan)

    def verdict(r):
        return "running" if r["status"] == "running" else "FAILED %s" % r.get("guard")

    def arm(sid, tool):
        p = pairs.get(sid)
        if not p:
            return None, "pending"
        return (p["arms"][tool], None) if p["status"] == "ok" else (None, verdict(p))

    def search(sid, tool, eng):
        p, r = pairs.get(sid), srch.get((sid, tool, eng))
        if not p or p["status"] != "ok":
            return None, "-"
        if not r or r["pair_run"] != p["pair_run"]:
            return None, "pending"
        return (r, None) if r["status"] == "ok" else (None, verdict(r))

    ov = search_overlaps(recs)
    fmt = lambda x, f: f(x[0]) if x[0] else x[1]
    gb = lambda a: "%.1f" % (a["peak_rss_kb"] / 1e6)
    ratio = lambda a, b: "%.2f" % (b[0]["peptides"] / a[0]["peptides"]) if a[0] and b[0] else "-"
    label = okp[0]["label"] if okp else "extractor"
    dtl = Path(plan["diatracer_jar"]).stem
    names = {"dt": dtl, "spx": label}
    swall = lambda sid, t, g, x: fmt(x, lambda r: hms(r["steps"]["engine"]["wall_s"]) + ("†" if (sid, t, g) in ov else ""))
    ids = [sid for sid in reg["samples"] if any(sid in qd["samples"] for qd in plan["queues"].values())]
    lines, full = [], []
    for sid in ids:
        e, p = reg["samples"][sid], pairs.get(sid)
        d, x = arm(sid, "dt"), arm(sid, "spx")
        S = {(t, g): search(sid, t, g) for t in TOOLS for g in ENGINES}
        flag = pair_flags(p, names) if p else "-"
        pep = lambda k: fmt(S[k], lambda r: "{:,}".format(r["peptides"]))
        lines.append("| " + " | ".join([
            str(e.get("label", sid)), e["scheme"], "%.1f" % e["acq_min"], p["node"] if p else "-", flag,
            fmt(d, lambda a: hms(a["wall_s"])), fmt(d, gb), fmt(x, lambda a: hms(a["wall_s"])), fmt(x, gb),
            fmt(d, lambda a: "{:,}".format(a["output"]["count"])), fmt(x, lambda a: "{:,}".format(a["output"]["count"])),
            pep(("dt", "sage")), pep(("spx", "sage")), ratio(S["dt", "sage"], S["spx", "sage"]),
            pep(("dt", "msfragger")), pep(("spx", "msfragger")), ratio(S["dt", "msfragger"], S["spx", "msfragger"]),
            swall(sid, "dt", "sage", S["dt", "sage"]) + " / " + swall(sid, "spx", "sage", S["spx", "sage"]),
            swall(sid, "dt", "msfragger", S["dt", "msfragger"]) + " / " + swall(sid, "spx", "msfragger", S["spx", "msfragger"])])
            + " |")
        if d[0] and x[0] and all(v[0] for v in S.values()):
            full.append({"scheme": e["scheme"], "contended": flag != "-", "dw": d[0]["wall_s"], "xw": x[0]["wall_s"],
                         "dr": d[0]["peak_rss_kb"], "xr": x[0]["peak_rss_kb"],
                         **{"%s_%s" % (t, g): S[t, g][0]["peptides"] for t, g in S},
                         **{"%s_sage_target" % t: S[t, "sage"][0].get("target_peptides") or 0 for t in TOOLS}})
    groups = {}
    for f in full:
        groups.setdefault(f["scheme"], []).append(f)
    summary = []
    for g, fs in list(groups.items()) + ([("**corpus**", full)] if full else []):
        tot = lambda k: sum(f[k] for f in fs)
        med = lambda a, b, rows: statistics.median(f[b] / f[a] for f in rows)
        clean = [f for f in fs if not f["contended"]]
        summary.append("| %s | %d | %d/%d | %s | %s | %.2f | %s | %.1f | %.1f | {:,} | {:,} | %.2f | %.2f | {:,} | {:,} | %.2f | %.2f |".format(
            tot("dt_sage"), tot("spx_sage"), tot("dt_msfragger"), tot("spx_msfragger"))
            % (g, len(fs), len(fs) - len(clean), len(fs), hms(tot("dw")), hms(tot("xw")), med("dw", "xw", fs),
               "%.2f" % med("dw", "xw", clean) if clean else "-",
               statistics.median(f["dr"] for f in fs) / 1e6, statistics.median(f["xr"] for f in fs) / 1e6,
               tot("spx_sage") / tot("dt_sage"), med("dt_sage", "spx_sage", fs),
               tot("spx_msfragger") / tot("dt_msfragger"), med("dt_msfragger", "spx_msfragger", fs)))
    ident = okp[0]["identity"] if okp else {}
    prov = [l for l in (okp[0]["provenance"] if okp else []) if l.startswith(("git=", "built=", "openms="))]
    tsha = oks[0]["tools_sha256"] if oks else {}
    sh16 = lambda k: (tsha.get(k) or "?")[:16]
    workers = sorted({r["workers"] for r in oks})
    local = {}
    for p in okp:
        for dep, h in (p["identity"].get("deps_sha256") or {}).items():
            if not dep.startswith("/ceph/"):
                local.setdefault(os.path.basename(dep), set()).add(h)
    local_diff = sorted(k for k, v in local.items() if len(v) > 1)
    tgt = lambda t: "%s %s of %s" % (names[t], "{:,}".format(sum(f["%s_sage_target" % t] for f in full)),
                                     "{:,}".format(sum(f["%s_sage" % t] for f in full)))
    pm = okp[0]["measure_sha256"] if okp else {}
    sm = oks[0]["measure_sha256"] if oks else {}
    H = {"dtl": dtl, "label": label, "now": now_iso(), "name": name, "source": source, "full": len(full), "ids": len(ids),
         "contended": sum(1 for p in okp if pair_flags(p, names) != "-"), "bin": ident.get("binary_sha256", "?")[:16],
         "lib": ", ".join("%s `%s`" % (k, v[:12]) for k, v in sorted(ident.get("lib_sha256", {}).items())) or "-",
         "ndeps": len(build_identity(ident)["deps_sha256"]) if ident else 0, "prov": ", ".join(prov) or "-",
         "threads": plan["threads"], "strip": ", ".join([p + "*" for p in STRIP_PREFIX] + sorted(STRIP_EXACT)),
         "jar": ident.get("jar_sha256", "?")[:16], "dtparams": " ".join(DT_PARAMS),
         "javas": ", ".join(sorted({"%s %s" % (p["node"], (p["identity"].get("java") or {}).get("version")) for p in okp})) or "-",
         "localdiff": (" Node-local system libraries that differ between nodes (recorded, not compared): %s."
                       % ", ".join(local_diff)) if local_diff else "",
         "mpair": str(pm.get("pair"))[:12], "msearch": str(sm.get("search"))[:12], "mscore": str(sm.get("score"))[:12],
         "wait": plan["load_wait_min"], "memfloor": round(MEM_FLOOR * 100), "minread": round(SAGE_MIN_READ * 100),
         "sage": sh16("sage"), "sage_config": sh16("sage_config"), "sage_fasta": sh16("sage_fasta"),
         "msf": sh16("msfragger_jar"), "msf_params": sh16("msfragger_params"), "msf_db": sh16("msfragger_db"),
         "workers": "/".join(map(str, workers)) or "?", "tgt_dt": tgt("dt"), "tgt_spx": tgt("spx")}
    head = """# Corpus benchmark: %(dtl)s vs %(label)s

Generated %(now)s by `harness/corpus.py table` (plan `%(name)s`, records from %(source)s). **n = 1 per cell. No
entrapment in this run** (option for later: Sage with `sage_entrap.json` plus `bench/entrapment.py`, charge strata
mandatory). %(full)d of %(ids)d rows complete; %(contended)d pairs flagged (load gate before the pair, or contention
during an arm).

- **%(label)s**: SPX_BIN sha256 `%(bin)s`, lib %(lib)s, %(ndeps)d ceph-resident libraries pinned by sha256, %(prov)s.
  Invocation `-in <staged .d> -out pseudo.mzML -threads %(threads)s`, defaults only, glibc malloc (%(strip)s and the
  inherited LD_LIBRARY_PATH unset before the arm's env.sh).
- **%(dtl)s**: jar sha256 `%(jar)s`; `java -Xmx400G -Djna.tmpdir -Djava.io.tmpdir=<jnatmp> -jar ... -t %(threads)s
  %(dtparams)s`, run from its directory with `LC_ALL=C LD_LIBRARY_PATH=./ext/bruker`. JDK: %(javas)s.%(localdiff)s
- **Measurement code** (one value across all rows, G-V13): pair `%(mpair)s`, search `%(msearch)s`, peptide rule
  `%(mscore)s`.
- **Timing**: per row both extractors ran back to back on the node shown (from the record's hostname), on a node-local
  staged copy, order alternating by queue index. Before each arm, outside its timed window, the node-local filesystem
  was synced and the input pre-warmed with `cat`. Wall and peak RSS from GNU `time -v`; compare walls within a row only.
- **RSS GB = `time -v` "Maximum resident set size (kbytes)" / 1e6.** GNU time's kbytes are KiB, so one unit here is
  1.024e9 bytes; multiply by 0.9537 to compare with the GiB of docs/HELA-TABLE.md and docs/TNBC-TABLE.md.
- **Load flags**: `gate:` the 1-min load before the pair stayed above 24 (>= 200 cores) or 12 for %(wait)s min and the
  pair ran anyway; `during <tool>:` the foreign CPU during that arm (busy CPU minus the runner's own process tree,
  highest 60-s mean) exceeded the same threshold, or MemAvailable fell below %(memfloor)d%% of MemTotal. The summary
  counts flagged rows and gives the median wall ratio of unflagged rows separately.
- **Searches**: Sage sha256 `%(sage)s` (config `%(sage_config)s`, FASTA `%(sage_fasta)s`, native decoys); MSFragger jar
  `%(msf)s` (params `%(msf_params)s`, database `%(msf_db)s`). diaTracer mzML is patched with the selected ion m/z
  before Sage; both tools' mzML pass `fix_mzml_cvparams.py` before MSFragger. Every search had to read the output:
  the patch wrote a selected ion into every diaTracer spectrum, MSFragger's `Scans` equal the spectrumList count, and
  Sage searched at least %(minread)d%% of it (its log gives a lower bound, over spectra with >= min_peaks peaks). Search
  walls are the engine step only, up to %(workers)s concurrent searches per node; `†` marks an engine step that
  overlapped another search on the same node. Indicative.
- **Peptides at 1%%** (rule of `$SPX/tools/bench_table.py`, which produced docs/TNBC-TABLE.md; hela_table.py behind
  docs/HELA-TABLE.md has the same functions): Sage = unique `peptide` strings with `rank == 1` and
  `peptide_q <= 0.01`, **target+decoy** (decoy rows are not removed, as in the source; with `report_psms 1` the rank
  filter keeps every row). Target-only peptides (label 1, the historical drivers' rule) over complete rows: %(tgt_dt)s,
  %(tgt_spx)s. MSFragger = best `hyperscore` per (`peptide`, `modification_info`), sorted descending, deepest prefix
  with decoy/target <= 1%%, decoy = every entry of `proteins` split on `,;@` starts with `rev_`. Ratios are ours /
  diaTracer.
- `FAILED G-Vxx` = a guard refused the cell (never a zero); `pending` = no current record; `-` = no pair.

| sample | scheme | acq min | node | load flags | %(dtl)s wall | %(dtl)s RSS GB (kB/1e6) | %(label)s wall | %(label)s RSS GB (kB/1e6) | spectra %(dtl)s | spectra %(label)s | Sage %(dtl)s | Sage %(label)s | Sage ratio | MSFragger %(dtl)s | MSFragger %(label)s | MSFragger ratio | Sage wall %(dtl)s / %(label)s | MSFragger wall %(dtl)s / %(label)s |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
""" % H
    tail = """
## Per scheme and corpus (complete rows only)

| scheme | n | flagged | %(dtl)s wall total | %(label)s wall total | median wall ratio (ours/dT) | median wall ratio, unflagged rows | %(dtl)s median RSS GB | %(label)s median RSS GB | Sage %(dtl)s total | Sage %(label)s total | Sage ratio of totals | Sage median ratio | MSFragger %(dtl)s total | MSFragger %(label)s total | MSFragger ratio of totals | MSFragger median ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
""" % H
    return head + "\n".join(lines) + "\n" + tail + "\n".join(summary) + "\n", len(ids) - len(full), len(ids)


def render_cells_table(name, plan, reg, recs, source="scratch") -> tuple:
    """`table` for an extended plan: one row per (sample, arm) with ratios against diaTracer, the per-charge split,
    entrapment by stratum, cell output statistics, and totals per arm over complete groups (every arm and search ok)."""
    pairs = {r["id"]: r for r in recs if r["kind"] == "pair"}
    srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r["kind"] == "search"}
    okp = [p for p in pairs.values() if p["status"] == "ok"]
    oks = [r for r in srch.values() if r["status"] == "ok"]
    table_guards(okp, oks, reg, plan)
    tools, engines = list(q_tools(plan)), list(q_engines(plan))
    label = okp[0]["label"] if okp else "extractor"
    dtl = Path(plan["diatracer_jar"]).stem
    names = dict({"dt": dtl, "spx": label}, **{n: n for n in cells(plan)})
    ids = [sid for sid in reg["samples"] if any(sid in qd["samples"] for qd in plan["queues"].values())]
    verdict = lambda r: "running" if r["status"] == "running" else "FAILED %s" % r.get("guard")
    fmt = lambda x, f: f(x[0]) if x[0] else x[1]
    num = lambda v: "{:,}".format(v) if v is not None else "-"
    pct = lambda v: "%.2f" % v if v is not None else "-"

    def arm(sid, t):
        p = pairs.get(sid)
        if not p:
            return None, "pending"
        if p["status"] != "ok":
            return None, verdict(p)
        a = p["arms"].get(t) or {}
        return (a, None) if a.get("status", "ok") == "ok" and a.get("output") else (None, "FAILED %s" % a.get("guard"))

    def search(sid, t, e):
        p, r = pairs.get(sid), srch.get((sid, t, e))
        if not arm(sid, t)[0]:
            return None, "-"
        if not r or r["pair_run"] != p["pair_run"]:
            return None, "pending"
        if r["status"] == "ok" and ("entrapment" if e == "entrap" else "by_charge") not in r:
            return None, "pending"          # stopped between the search and its split: the next launch re-runs it
        return (r, None) if r["status"] == "ok" else (None, verdict(r))

    def flags(p, t):
        out, g, a = [], p.get("gate") or {}, p["arms"].get(t) or {}
        if g.get("contended"):
            out.append("gate: load %.1f > %.0f%s" % (g["load"], g["load_max"], ", busy" if g.get("busy") else ""))
        if a and (a.get("status", "ok") == "ok" or "during" in a):
            du = a.get("during") or {"contended": True, "why": ["contention not measured"]}
            if du.get("contended"):
                out.append("during: " + "; ".join(du.get("why") or ["?"]))
        return "; ".join(out + [f for f in [noop_flag(a)] if f]) or "-"

    main, charge, entrap, cellrows, full = [], [], [], [], {}
    for sid in ids:
        e, p = reg["samples"][sid], pairs.get(sid)
        S = {(t, g): search(sid, t, g) for t in tools for g in engines}
        SG = lambda t_, g: S.get((t_, g), (None, "-"))          # an engine the plan does not run (`engines`): "-"
        A = {t: arm(sid, t) for t in tools}
        complete = all(A[t][0] for t in tools) and all(v[0] for v in S.values())
        for t in tools:
            a = A[t]
            ratio = lambda g: "%.2f" % (SG(t, g)[0]["peptides"] / SG("dt", g)[0]["peptides"]) \
                if t != "dt" and SG(t, g)[0] and SG("dt", g)[0] else "-"
            swall = lambda g: fmt(SG(t, g), lambda r: hms(r["steps"]["engine"]["wall_s"]))
            cores = lambda x: "%.1f" % (x["cpu"]["cpu_s"] / x["wall_s"]) if (x.get("cpu") or {}).get("cpu_s") is not None and x["wall_s"] > 0 else "-"
            main.append("| " + " | ".join([
                str(e.get("label", sid)), "%.1f" % e["acq_min"], p["node"] if p else "-", names[t], flags(p, t) if p else "-",
                fmt(a, lambda x: hms(x["wall_s"])), fmt(a, lambda x: "%.1f" % (x["peak_rss_kb"] / 1e6)), fmt(a, cores),
                fmt(a, lambda x: num(x["output"]["count"])),
                fmt(SG(t, "sage"), lambda r: num(r["peptides"])), fmt(SG(t, "sage"), lambda r: num(r.get("target_peptides"))),
                ratio("sage"), fmt(SG(t, "msfragger"), lambda r: num(r["peptides"])), ratio("msfragger"),
                swall("sage"), swall("msfragger")]) + " |")
            bc = lambda g, z, k="peptides": fmt(SG(t, g), lambda r: num(((r.get("by_charge") or {}).get(z) or {}).get(k)))
            charge.append("| " + " | ".join([str(e.get("label", sid)), names[t], bc("sage", "z1"), bc("sage", "z2p"),
                                             bc("sage", "z1", "target_peptides"), bc("sage", "z2p", "target_peptides"),
                                             bc("msfragger", "z1"), bc("msfragger", "z2p")]) + " |")
            if plan.get("entrapment"):
                r, v = S[t, "entrap"]
                for st, _, _ in STRATA:
                    x = (r or {}).get("entrapment", {}).get(st) or {}
                    ci = x.get("ci_pct") or [None, None]
                    entrap.append("| " + " | ".join([str(e.get("label", sid)), names[t], st] + (
                        [num(x.get("accepted")), num(x.get("target")), num(x.get("entrap")), pct(x.get("raw_pct")),
                         pct(x.get("fdr_pct")), "%s-%s" % (pct(ci[0]), pct(ci[1]))] if r else [v] * 6)) + " |")
            if t in cells(plan):
                c, x = plan["cells"][t], p["arms"].get(t) if p else None
                st = (x or {}).get("spectra_stats") or {}
                n = st.get("spectra") or 0
                cellrows.append("| " + " | ".join([
                    str(e.get("label", sid)), t, c["arm"], "`%s`" % (" ".join(c["args"]) or "defaults"),
                    fmt(a, lambda y: num(y["output"]["count"])),
                    ", ".join("z%s %s" % (z, num(k)) for z, k in sorted(st.get("charges", {}).items())) or "-",
                    "%.1f%%" % (100.0 * st["im_zero"] / n) if n else "-", num(st.get("im_missing")) if n else "-",
                    "%s / %s" % (st.get("peaks_min", "-"), st.get("peaks_median", "-")) if n else "-",
                    "%s (%.1f%%)" % (num(st["unsorted"]), 100.0 * st["unsorted"] / n) if n and "unsorted" in st else "-",
                    fmt(a, lambda y: hms(y["reencode"]["wall_s"])),
                    fmt(a, lambda y: "%d / %d" % (y["spectra_stats"]["numpress_terms"], y["reencoded_stats"]["numpress_terms"])),
                    fmt(a, lambda y: "`%s` / `%s`" % (y["digests"]["semantic"][:12], y["digests"]["content"][:12])),
                    (noop_flag(x or {}) or ("differs from %s" % c["differs_from"] if (x or {}).get("noop") else "-"))
                    if c.get("differs_from") else "-"]) + " |")
        if complete:
            full[sid] = {"flagged": any(flags(p, t) != "-" for t in tools), "arms": {t: A[t][0] for t in tools},
                         "search": {k: v[0] for k, v in S.items()}}
    summary = []
    tot = lambda f: sum(f(g) for g in full.values())
    ratio2 = lambda a, b: "%.2f" % (a / b) if b else "-"
    # a total over an engine the plan does not run is None: num() and ratio2() print "-"
    sm = lambda t_, g, f: tot(lambda x: f(x["search"][t_, g])) if g in engines else None
    pep = lambda r: r["peptides"]
    s_z2p = lambda r: r["by_charge"]["z2p"]["target_peptides"]
    m_z2p = lambda r: r["by_charge"]["z2p"]["peptides"]
    for t in tools:
        if not full:
            break
        sage, msf = sm(t, "sage", pep), sm(t, "msfragger", pep)
        s_z2, m_z2 = sm(t, "sage", s_z2p), sm(t, "msfragger", m_z2p)
        d_s, d_m = sm("dt", "sage", pep), sm("dt", "msfragger", pep)
        d_sz2, d_mz2 = sm("dt", "sage", s_z2p), sm("dt", "msfragger", m_z2p)
        rows = [g["arms"][t] for g in full.values()]
        summary.append("| %s | %d | %d/%d | %s | %.1f | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            names[t], len(full), sum(g["flagged"] for g in full.values()), len(full), hms(sum(a["wall_s"] for a in rows)),
            statistics.median(a["peak_rss_kb"] for a in rows) / 1e6, num(sum(a["output"]["count"] for a in rows)),
            ratio2(sage, d_s), num(s_z2), ratio2(s_z2, d_sz2), num(msf), ratio2(msf, d_m), num(m_z2), ratio2(m_z2, d_mz2)))
    ident = okp[0]["identity"] if okp else {}
    cm = okp[0].get("cells_meta", {}) if okp else {}
    tsha = oks[0]["tools_sha256"] if oks else {}
    pm = okp[0]["measure_sha256"] if okp else {}
    sh = lambda v: (v or "?")[:16]
    cell_lines = "".join(
        "\n- **%s** (%s, arm `%s`): %s; binary sha256 `%s`, %s sha256 `%s`, %d lib files, %d ceph-resident libraries; "
        "%s; `-in <staged .d> -out <cell dir> -threads %s%s`, wall cap %s h, killed when MemAvailable stays < %d%% for %d "
        "samples; data tree sha256 `%s`, env.sh sha256 `%s`; a private TMPDIR in the cell directory."
        % (n, c["kind"], c["arm"], (cm.get(n) or {}).get("label", "?"), sh(((ident.get("cells") or {}).get(n) or {}).get("binary_sha256")),
           REENCODE[0], sh(((ident.get("cells") or {}).get(n) or {}).get("reencode_sha256")),
           len(((ident.get("cells") or {}).get(n) or {}).get("lib_sha256") or {}),
           len(build_identity(ident).get("cells", {}).get(n, {}).get("deps_sha256", {})) if ident.get("cells") else 0,
           ", ".join(l for l in (cm.get(n) or {}).get("provenance", []) if l.startswith(("git_sha=", "published=", "compiler=")))
           or "no git_sha/published line",
           plan["threads"], "".join(" " + x for x in c["args"]), c["wall_cap_h"], round(MEM_FLOOR * 100), MEM_FLOOR_SAMPLES,
           sh(((ident.get("cells") or {}).get(n) or {}).get("data_tree_sha256")),
           sh(((ident.get("cells") or {}).get(n) or {}).get("env_sha256")))
        for n, c in cells(plan).items())
    head = """# Extractor comparison: %(dtl)s, %(label)s and %(cells)s

Generated %(now)s by `harness/corpus.py table` (plan `%(name)s`, records from %(source)s). **n = 1 per cell.** %(full)d of
%(ids)d samples complete (every arm and every search ok).

- **%(label)s**: SPX_BIN sha256 `%(bin)s`; `-in <staged .d> -out pseudo.mzML -threads %(threads)s`, defaults only.
- **%(dtl)s**: jar sha256 `%(jar)s`; the corpus-v3 invocation (`-Xmx400G`, every option passed: `%(dtparams)s`).%(cell_lines)s
- **Order and timing**: per sample, one staged copy, the reference pair first (order alternating by queue index), then
  the cells in plan order (rotated by queue index); every arm synced and pre-warmed outside its timed window; wall,
  peak RSS and CPU from GNU `time -v` (CPU cores = (user + system) / wall). RSS GB = kbytes / 1e6. Compare walls
  within one sample only. A failed cell does not stop the next one; a group with a failed cell re-runs whole.
- **Re-encode** (cells, before any search, outside the timed window): `%(reencode)s -in pseudo_spectra.mzML -out
  reencoded.mzML %(reargs)s` from the cell's own build. Checked: no numpress term (MS:1002312/13/14, MS:1002746/47/48),
  an m/z array in every spectrum and every one sorted, the same spectra, the same RT, selected ion m/z, charge, 1/K0
  and isolation target values, the same m/z values per spectrum (raw numpress decoded bit-identically to OpenMS), a
  selected ion m/z in every spectrum. Searches read the re-encoded file; no selected-ion patch for cells.
- **No-op check** (G-V18): a cell with `differs_from` is flagged when its order-independent content digest (each
  spectrum block without id/index/spectrumRef/dataProcessingRef, sorted) equals that cell's. The spectrum-list digest
  (bench/semantic_digest.py) is shown beside it; diaWeaver's final RT sort is unstable, so that digest can differ
  between two runs of one arm. One-sided: an unflagged cell differs in content, which run-to-run variation of the
  tool also produces; it does not prove the settings made the difference.
- **Searches**: Sage `%(sage)s` (config `%(sage_config)s`, FASTA `%(sage_fasta)s`), MSFragger `%(msf)s` (params
  `%(msf_params)s`, database `%(msf_db)s`); diaTracer patched before Sage; `fix_mzml_cvparams.py` before MSFragger for
  every arm; the corpus-v3 read checks (patched = spectra, MSFragger Scans = spectra, Sage >= %(minread)d%% of them).
- **Peptides at 1%%**: the corpus-v3 rules. Sage = distinct peptides with rank 1 and peptide_q <= 0.01,
  **target+decoy** (target-only beside it); MSFragger = best hyperscore per (peptide, modification_info), deepest
  prefix with decoy/target <= 1%%, targets. Ratios are arm / %(dtl)s.
- **Per charge**: each counted peptide in the stratum of its best counted PSM (Sage: highest
  sage_discriminant_score; MSFragger: the best-hyperscore PSM of its key); z1 + z2p equals the count (checked).
%(engines_line)s%(entrap_line)s- **Measurement code**: pair `%(mpair)s`, search `%(msearch)s`, peptide rule `%(mscore)s`, cells `%(mcells)s`.
- `FAILED G-Vxx` = a guard refused the cell (never a zero); `pending` = no current record; `-` = no arm or search.

| sample | acq min | node | arm | flags | wall | RSS GB | CPU cores | spectra | Sage | Sage target | Sage vs dT | MSFragger | MSFragger vs dT | Sage wall | MSFragger wall |
|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
""" % {"dtl": dtl, "label": label, "cells": ", ".join(cells(plan)) or "no cells", "now": now_iso(), "name": name,
       "source": source, "full": len(full), "ids": len(ids), "bin": sh(ident.get("binary_sha256")), "threads": plan["threads"],
       "jar": sh(ident.get("jar_sha256")), "dtparams": " ".join(DT_PARAMS), "cell_lines": cell_lines,
       "reencode": REENCODE[0], "reargs": " ".join(REENCODE[1]), "minread": round(SAGE_MIN_READ * 100),
       "sage": sh(tsha.get("sage")), "sage_config": sh(tsha.get("sage_config")), "sage_fasta": sh(tsha.get("sage_fasta")),
       "msf": sh(tsha.get("msfragger_jar")), "msf_params": sh(tsha.get("msfragger_params")), "msf_db": sh(tsha.get("msfragger_db")),
       "entrap_line": ("- **Entrapment**: Sage with `%s` (sha256 `%s`, FASTA `%s`), estimator `bench/entrapment.py` (sha256 `%s`): "
                       "peptide-hypothesis ratio, est. FDR = (entrapment / ratio) / target, 95%% bootstrap CI. Strata as for "
                       "the peptides (each peptide in the stratum of its best non-decoy PSM), scored by the estimator itself; "
                       "z1 + z2p equals all (checked). Never quote the `all` row without the strata.\n"
                       % (Path(plan["tools"]["sage_entrap"]).name, sh(tsha.get("sage_entrap")), sh(tsha.get(ENTRAP_DB)),
                          sh(tsha.get("entrapment")))) if plan.get("entrapment") else "",
       "engines_line": ("- **Engines**: this plan runs %s only (plan `engines`); the columns of an engine it does not run "
                        "print `-` (its tools stay installed and pinned, never run).\n" % " and ".join(plan["engines"]))
                       if "engines" in plan else "",
       "mpair": str(pm.get("pair"))[:12], "msearch": str(pm.get("search"))[:12], "mscore": str(pm.get("score"))[:12],
       "mcells": str(pm.get("cells"))[:12]}
    parts = [head + "\n".join(main) + "\n",
             "\n## Peptides by precursor charge\n\n| sample | arm | Sage z=1 | Sage z>=2 | Sage target z=1 | Sage target z>=2 "
             "| MSFragger z=1 | MSFragger z>=2 |\n|---|---|---:|---:|---:|---:|---:|---:|\n" + "\n".join(charge) + "\n"]
    if plan.get("entrapment"):
        parts.append("\n## Entrapment by charge stratum (Sage, nominal peptide_q <= 0.01)\n\n| sample | arm | stratum | accepted "
                     "| target | entrapment | raw % | est. FDR % | 95% CI |\n|---|---|---|---:|---:|---:|---:|---:|---:|\n"
                     + "\n".join(entrap) + "\n")
    if cells(plan):
        parts.append("\n## Cell outputs (before the re-encode unless noted)\n\n| sample | cell | cell arm | args | spectra "
                     "| charges | 1/K0 = 0 | 1/K0 missing | peaks per spectrum (min / median) | unsorted peak lists | re-encode wall "
                     "| numpress terms (raw / re-encoded) | spectrum-list / content digest (re-encoded) | no-op check |\n"
                     "|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|---|\n" + "\n".join(cellrows) + "\n")
    parts.append("\n## Per arm, complete samples only\n\n| arm | n | flagged | wall total | median RSS GB | spectra | Sage vs dT "
                 "| Sage target z>=2 | Sage target z>=2 vs dT | MSFragger | MSFragger vs dT | MSFragger z>=2 "
                 "| MSFragger z>=2 vs dT |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
                 + "\n".join(summary) + "\n")
    return "".join(parts), len(ids) - len(full), len(ids)

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
