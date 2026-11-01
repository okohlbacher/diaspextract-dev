#!/usr/bin/env python3
"""Baseline mode: extractors and DIA-NN on registered runs, across a thread-count axis (parallel efficiency), as Slurm
jobs on exclusive whole nodes (BinAC2).

A plan (a section of harness/samples.yaml, e.g. `baseline_v1`) becomes one Slurm job per sample (`job_unit: sample`) or
per (sample, cell, threads) (`job_unit: cell`), each `sbatch --exclusive --nodes=1 --mem=0`. A job stages its sample
once into the node-local $TMPDIR (0700), runs its (cell, threads, repeat) units back to back under GNU `time -v`, with
the pre-warm, syncfs and /proc contention sampler of harness/corpus.py (the load gate only records: the node is
exclusive), then searches (Sage + MSFragger: corpus.run_search, its read checks and peptide rules) the output of each
cell's `search_at` thread count. DIA-NN is its own search: its report is counted at every thread count. Records go
straight to <results>/records on Lustre (shared by all jobs of the plan: resume across jobs); logs are copied to
<results>/runs when the job ends. `submit-corpus` runs a corpus.py plan the same way: one job per sample, corpus
node-run semantics (DIAspeXtract vs diaTracer back to back, then searches). Usage, keys, metrics: harness/BASELINE.md.

    baseline.py selftest                                     # offline, fake tools; every guard fires, E(p) known answer
    baseline.py dry-run   [--plan baseline_v1] [--sample S]  # sbatch scripts + every command, nothing contacted
    baseline.py preflight [--plan baseline_v1]               # read-only checks on the cluster login node (ssh)
    baseline.py submit    [--plan baseline_v1] [--sample S] [--cell C]   # sbatch the jobs
    baseline.py status    [--plan baseline_v1]               # squeue + record counts
    baseline.py fetch     [--plan baseline_v1] --dest DIR    # scp <results>/records -> DIR/records
    baseline.py table     [--plan baseline_v1] [--source remote|DIR] [--out PREFIX]   # PREFIX.json + PREFIX.md
    baseline.py submit-corpus --corpus-plan P [--plan baseline_v1] [--sample S]      # corpus pairs, one job per sample
    baseline.py corpus-table  --corpus-plan P [--plan baseline_v1] [--source remote|DIR] [--out F]

Pinning: none. No taskset/numactl/OMP_PLACES; the OS schedules freely (records carry logical CPUs, physical cores,
NUMA nodes, CPU model, affinity). Stdlib only on the nodes, except pyarrow for DIA-NN's report.parquet (preflight).
"""
from __future__ import annotations

import argparse, base64, hashlib, json, os, re, shlex, shutil, statistics, subprocess, sys, tempfile, time
from pathlib import Path

SELF = Path(globals().get("__file__", "baseline.py")).resolve()   # no __file__ under `python3 -` on a node
HERE = SELF.parent
if "corpus" not in sys.modules:                                    # remote(): the bootstrap pre-loads it
    sys.path.insert(0, str(HERE))
import corpus as c  # noqa: E402  (the harness: staging, gate, time, sampler, searches, peptide rules)

Abort, die, die_queue, say = c.Abort, c.die, c.die_queue, c.say
REG = HERE / "samples.yaml"
DEFAULT_PLAN = "baseline_v1"
KINDS = {"diaspextract": {"env"}, "diatracer": {"dir", "jar"}, "diann": {"bin"}, "cmd": {"exe", "cmd", "out"}}
CELL_OPTIONAL = {"diaspextract": {"args"}, "diatracer": set(), "diann": {"args", "env"}, "cmd": {"input", "count", "env", "pre", "post"}}
CELL_COMMON = {"kind", "search_at", "threads", "wall_cap_h", "engines", "sage_config", "msfragger_params"}
RESERVED_ARGS = {"diaspextract": {"-in", "-out", "-threads", "-ini"},
                 "diann": {"--f", "--fasta", "--out", "--out-lib", "--temp", "--threads", "--lib"}}
PLAN_KEYS = {"cluster", "results", "threads", "repeats", "samples", "n_samples", "search_db_sha256", "tools", "cells"}
OPTIONAL_PLAN_KEYS = {"engines", "raw_map"}
CLUSTER_KEYS = {"host", "partition", "walltime", "python", "job_unit"}
CLUSTER_OPTIONAL = {"cpus", "path", "sbatch_args"}
RESERVED_CELLS = {"dt", "sage", "msfragger", "entrap", "stage", "search"}
WALL_CAP_H = 24.0
JAVA_MIN = 11                                      # diaTracer 2.2.1 and MSFragger 4.4.1; BinAC2's system java is 1.8
# DIA-NN 2.0 library-free, from /ceph/ibmi/abi/oliver/results/diann-bench-2.0 (lib/autogen.log.txt + logs/A_r1.log),
# in one call: in-silico digest + deep-learning prediction + search of the run, 1% q, no MBR (single run).
DIANN_ARGS = ["--fasta-search", "--predictor", "--gen-spec-lib", "--cut", "K*,R*", "--missed-cleavages", "1",
              "--min-pep-len", "7", "--max-pep-len", "30", "--min-pr-charge", "2", "--max-pr-charge", "4",
              "--min-pr-mz", "350", "--max-pr-mz", "1200", "--min-fr-mz", "200", "--max-fr-mz", "1800", "--unimod4",
              "--met-excision", "--var-mods", "0", "--mass-acc", "15", "--mass-acc-ms1", "15", "--qvalue", "0.01",
              "--pg-level", "1"]
DIANN_COLS = ("Precursor.Id", "Stripped.Sequence", "Protein.Group", "Q.Value", "Lib.Q.Value", "PG.Q.Value")
DIANN_KEEP = re.compile(r"^(report\.(parquet|tsv|stats\.tsv|log\.txt|manifest\.txt)|time\.log|diann\.log)$")
Q_MAX = 0.01
COPY_IGNORE = ("stage", "tools", "tmp", "*.mzML", "*.mzBIN*", "*.tmp*", "*.d", "*.speclib", "*.mgf", "*.mzXML", "*.ms1",
               "*.ser", "*_Peak", "*.fasta")             # raw-derived and intermediate files never leave the node
# Guards that baseline.py raises itself; the corpus ids it reuses (G-V02/03/06/07/08/10/12/14/15) keep their meaning.
GUARDS = {
    "G-B01": "plan/registry: unknown or missing key, bad cluster section, bad cell, bad thread axis, search_at not on "
             "the axis, sample unknown/duplicated/without a cell, raw not covered by raw_map, n_samples mismatch; at "
             "job start: p above the CPUs the job may use, corpus.py copy differs",
    "G-B02": "cell tool unresolvable: binary/jar/Bruker library missing or not executable, cmd env.sh failing or "
             "exporting a stripped variable, java older than %d; preflight: no pyarrow for a DIA-NN cell" % JAVA_MIN,
    "G-B03": "tool drift: a file of the cell's tool (binary, lib/, jar, ext/bruker, DIA-NN dir, java) changed across a run",
    "G-B04": "run output: DIA-NN report missing/stale/columns missing/0 precursors at 1%; cmd count line missing or != "
             "spectrumList count",
    "G-B05": "run stopped: wall cap passed or available memory under the floor (the tool's session is killed)",
    "G-B06": "table: one cell with two tool builds, mixed harness code, one sample measured on two CPU models, an ok "
             "record with wall/RSS/spectra <= 0",
    "G-B07": "job environment: $TMPDIR unset, missing, or not node-local (under /pfs, /home, /ceph); results dir not "
             "an absolute path",
}
SELFTEST_GUARDS = set(GUARDS) | {"G-V02", "G-V03", "G-V06", "G-V08", "G-V10", "G-V12", "G-V14"}


# ------------------------------------------------------------------------------- plan
def axis_ok(v) -> bool:
    return (isinstance(v, list) and v and all(type(p) is int and p > 0 for p in v)
            and v == sorted(set(v)))


def cell_input(cell: dict) -> str:
    return cell.get("input", "mzml") if cell["kind"] == "cmd" else "d"


def sample_input(raw: str) -> str:
    return "d" if raw.endswith(".d") else "mzml" if raw.endswith(".mzML") else "?"


def validate_cell(n, cell, plan) -> None:
    if not isinstance(n, str) or not re.fullmatch(c.CELL_NAME, n) or n in RESERVED_CELLS:
        die("G-B01", "cell name %r must match %s and not be one of %s" % (n, c.CELL_NAME, sorted(RESERVED_CELLS)))
    if not isinstance(cell, dict) or cell.get("kind") not in KINDS:
        die("G-B01", "cell %s: kind must be one of %s" % (n, sorted(KINDS)))
    k = cell["kind"]
    need, allowed = KINDS[k] | {"kind", "search_at"}, KINDS[k] | CELL_COMMON | CELL_OPTIONAL[k]
    if not need <= set(cell) <= allowed:
        die("G-B01", "cell %s (%s): needs %s, allows %s, got %s" % (n, k, sorted(need), sorted(allowed), sorted(cell)))
    axis = cell.get("threads", plan.get("threads"))
    if not axis_ok(axis):
        die("G-B01", "cell %s: threads must be a non-empty ascending list of distinct positive ints, not %r" % (n, axis))
    if cell["search_at"] not in axis:
        die("G-B01", "cell %s: search_at %r is not on its thread axis %s" % (n, cell["search_at"], axis))
    cap = cell.get("wall_cap_h", WALL_CAP_H)
    if type(cap) not in (int, float) or not 0 < cap <= 72:
        die("G-B01", "cell %s: wall_cap_h must be a number in (0, 72], got %r" % (n, cap))
    args = cell.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args) or set(args) & RESERVED_ARGS.get(k, set()):
        die("G-B01", "cell %s: args must be strings without %s (the harness sets those): %r"
            % (n, sorted(RESERVED_ARGS.get(k, ())), args))
    eng = cell.get("engines", plan.get("engines", list(c.ENGINES)))
    if not isinstance(eng, list) or not eng or [e for e in c.ENGINES if e in eng] != eng \
            or not set(eng) <= set(plan.get("engines", c.ENGINES)):
        die("G-B01", "cell %s: engines must be a non-empty, ordered subset of the plan's engines, not %r" % (n, eng))
    for key in ("pre", "post"):
        if key in cell and not (isinstance(cell[key], list) and cell[key] and all(isinstance(x, str) for x in cell[key])):
            die("G-B01", "cell %s: %s must be a non-empty list of command templates" % (n, key))
    for key in ("env", "dir", "bin", "exe", "sage_config", "msfragger_params"):
        if key in cell and not (isinstance(cell[key], str) and cell[key].startswith("/")):
            die("G-B01", "cell %s: %s must be an absolute path, not %r" % (n, key, cell.get(key)))
    if k == "diaspextract" and not cell["env"].endswith("/env.sh"):
        die("G-B01", "cell %s: env must name an arm's env.sh (it exports SPX_BIN): %r" % (n, cell["env"]))
    if k == "cmd":
        allt = " ".join([cell["cmd"] if isinstance(cell["cmd"], str) else ""] + list(cell.get("pre", [])) + list(cell.get("post", [])))
        if not isinstance(cell["cmd"], str) or "{in}" not in allt or "{out}" not in allt \
                or not ("{threads}" in allt or "{cpulist}" in cell["cmd"]):
            die("G-B01", "cell %s: cmd (with pre/post) must use {in}, {out} and {threads} (or {cpulist}): %r" % (n, cell["cmd"]))
        if not (isinstance(cell["out"], str) and re.fullmatch(r"[A-Za-z0-9._-]+\.mzML", cell["out"])):
            die("G-B01", "cell %s: out must be a plain *.mzML file name (written into the run dir): %r" % (n, cell["out"]))
        if cell.get("input", "mzml") not in ("d", "mzml"):
            die("G-B01", "cell %s: input must be d or mzml, not %r" % (n, cell.get("input")))
        if "count" in cell:
            try:
                ok = re.compile(cell["count"]).groups == 1
            except (re.error, TypeError):
                ok = False
            if not ok:
                die("G-B01", "cell %s: count must be a regex with one group (the tool's spectrum count)" % n)


def validate_cluster(name: str, cl) -> None:
    if not isinstance(cl, dict) or not CLUSTER_KEYS <= set(cl) <= CLUSTER_KEYS | CLUSTER_OPTIONAL:
        die("G-B01", "plan %s: cluster needs %s, allows %s" % (name, sorted(CLUSTER_KEYS), sorted(CLUSTER_OPTIONAL)))
    if cl["job_unit"] not in ("sample", "cell"):
        die("G-B01", "plan %s: cluster.job_unit must be sample or cell, not %r" % (name, cl["job_unit"]))
    if not (isinstance(cl["walltime"], str) and re.fullmatch(r"(\d+-)?\d+:\d\d:\d\d", cl["walltime"])):
        die("G-B01", "plan %s: cluster.walltime must be [D-]H:MM:SS, not %r" % (name, cl["walltime"]))
    if "cpus" in cl and (type(cl["cpus"]) is not int or cl["cpus"] < 1):
        die("G-B01", "plan %s: cluster.cpus must be a positive int" % name)
    for k in ("path", "sbatch_args"):
        if k in cl and not (isinstance(cl[k], list) and all(isinstance(x, str) for x in cl[k])):
            die("G-B01", "plan %s: cluster.%s must be a list of strings" % (name, k))
    bad = [a for a in cl.get("sbatch_args", []) if a.split("=")[0] in
           ("--exclusive", "--nodes", "-N", "--mem", "--partition", "-p", "--time", "-t", "--output", "-o", "--job-name", "-J")]
    if bad:
        die("G-B01", "plan %s: cluster.sbatch_args %s are set by the harness" % (name, bad))


def map_raw(raw: str, raw_map) -> str | None:
    if not raw_map:
        return raw
    hits = [a for a in raw_map if raw.startswith(a)]
    if not hits:
        return None
    a = max(hits, key=len)                             # the most specific prefix wins
    return raw_map[a] + raw[len(a):]


def validate_plan(name: str, plan, reg: dict) -> None:
    """G-B01 (the corpus G-V01 rules where they apply: duplicate YAML keys are refused by corpus._registry)."""
    if not isinstance(plan, dict):
        die("G-B01", "no plan section %r in the registry" % name)
    if not PLAN_KEYS <= set(plan) <= PLAN_KEYS | OPTIONAL_PLAN_KEYS:
        die("G-B01", "plan %s: unknown keys %s, missing keys %s" % (name, sorted(set(plan) - PLAN_KEYS - OPTIONAL_PLAN_KEYS),
                                                                   sorted(PLAN_KEYS - set(plan))))
    validate_cluster(name, plan["cluster"])
    if not (isinstance(plan["results"], str) and plan["results"].startswith("/")):
        die("G-B01", "plan %s: results must be an absolute path on the cluster" % name)
    rm = plan.get("raw_map")
    if "raw_map" in plan and not (isinstance(rm, dict) and rm and all(isinstance(k, str) and isinstance(v, str)
                                                                       and k.startswith("/") and v.startswith("/")
                                                                       for k, v in rm.items())):
        die("G-B01", "plan %s: raw_map must map absolute path prefixes to absolute path prefixes" % name)
    if not isinstance(plan["tools"], dict) or set(plan["tools"]) != set(c.TOOL_KEYS):
        die("G-B01", "plan %s: tools needs exactly %s" % (name, list(c.TOOL_KEYS)))
    db = plan["search_db_sha256"]
    if not isinstance(db, dict) or set(db) != set(c.DB_KEYS) or not all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in db.values()):
        die("G-B01", "plan %s: search_db_sha256 needs exactly %s as sha256 hex" % (name, list(c.DB_KEYS)))
    eng = plan.get("engines", list(c.ENGINES))
    if not isinstance(eng, list) or not eng or [e for e in c.ENGINES if e in eng] != eng:
        die("G-B01", "plan %s: engines must be a non-empty list of %s in that order, not %r" % (name, list(c.ENGINES), eng))
    if not axis_ok(plan["threads"]):
        die("G-B01", "plan %s: threads must be a non-empty ascending list of distinct positive ints" % name)
    if type(plan["repeats"]) is not int or plan["repeats"] < 1:
        die("G-B01", "plan %s: repeats must be an int >= 1, not %r" % (name, plan["repeats"]))
    if not isinstance(plan["cells"], dict) or not plan["cells"]:
        die("G-B01", "plan %s: cells must be a non-empty mapping" % name)
    for n, cell in plan["cells"].items():
        validate_cell(n, cell, plan)
    if sum(cell["kind"] == "diatracer" for cell in plan["cells"].values()) > 1:
        die("G-B01", "plan %s: at most one diatracer cell (its searches are recorded under the corpus name dt)" % name)
    ss = plan["samples"]
    if not isinstance(ss, list) or not ss:
        die("G-B01", "plan %s: samples must be a non-empty list of sample ids" % name)
    seen, raws = set(), {}
    for sid in ss:
        if sid in seen:
            die("G-B01", "sample %s is listed twice" % sid)
        seen.add(sid)
        e = (reg.get("samples") or {}).get(sid)
        if not isinstance(e, dict):
            die("G-B01", "sample %s not in samples.yaml" % sid)
        kind = sample_input(str(e.get("raw", "")))
        pin = e.get("pin") if isinstance(e.get("pin"), dict) else {}
        if kind == "d":
            miss = [k for k in c.SAMPLE_KEYS if e.get(k) in (None, "")] + ["pin." + k for k in c.PIN_KEYS if pin.get(k) in (None, "")]
        elif kind == "mzml":
            miss = [k for k in ("raw", "scheme", "pin") if e.get(k) in (None, "")] + \
                   ([] if type(pin.get("bytes")) is int and re.fullmatch(r"[0-9a-f]{64}", str(pin.get("sha256"))) else ["pin.bytes/sha256"])
        else:
            miss = ["raw (.d or .mzML)"]
        if miss:
            die("G-B01", "sample %s: missing or bad %s" % (sid, miss))
        if not any(cell_input(cell) == kind for cell in plan["cells"].values()):
            die("G-B01", "sample %s (%s input): no cell of the plan reads it" % (sid, kind))
        if map_raw(str(e["raw"]), rm) is None:
            die("G-B01", "sample %s: raw %s is under no raw_map prefix" % (sid, e["raw"]))
        key = os.path.normpath(str(e["raw"]))
        if key in raws:
            die("G-B01", "samples %s and %s share one raw path" % (raws[key], sid))
        raws[key] = sid
    if type(plan["n_samples"]) is not int or plan["n_samples"] != len(seen):
        die("G-B01", "plan %s lists %d samples but n_samples is %r" % (name, len(seen), plan["n_samples"]))


def load_plan(name: str, reg_path=REG) -> tuple:
    reg = c._registry(reg_path)                       # refuses duplicate YAML keys (corpus G-V01)
    plan = reg.get(name)
    validate_plan(name, plan, reg)
    return plan, reg


def norm_cells(plan: dict) -> dict:
    out = {}
    for n, cell in plan["cells"].items():
        x = dict(cell)
        x.setdefault("threads", list(plan["threads"]))
        x.setdefault("wall_cap_h", WALL_CAP_H)
        x.setdefault("args", [])
        x.setdefault("engines", list(plan.get("engines", c.ENGINES)))
        if x["kind"] == "cmd":
            x.setdefault("input", "mzml")
        out[n] = x
    return out


def nonce() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex()


def resolve(name: str, plan: dict, reg: dict) -> dict:
    """The queue a job runs (all samples; jobs() narrows it). root/lock/jnatmp are set on the node, in $TMPDIR."""
    q = {k: plan[k] for k in ("threads", "repeats", "search_db_sha256", "tools", "results", "cluster")}
    corpus_file = Path(c.SELF)
    q.update(plan=name, nonce=nonce(), root=None, lock=None, jnatmp=None, load_wait_min=0, only=None,
             engines=list(plan.get("engines", c.ENGINES)), cells=norm_cells(plan), harness_sha256=c.sha256(SELF),
             corpus_sha256=c.sha256(corpus_file) if corpus_file.is_file() else None,
             samples=[dict({k: reg["samples"][sid][k] for k in ("scheme", "pin", "acq_min", "database")
                            if k in reg["samples"][sid]}, id=sid, label=reg["samples"][sid].get("label", sid),
                           raw=map_raw(reg["samples"][sid]["raw"], plan.get("raw_map")))
                      for sid in plan["samples"]])
    return q


def jobs(q: dict) -> list:
    """(job name, queue) per Slurm job: one per sample, or one per (sample, cell, threads)."""
    out = []
    for s in q["samples"]:
        if q["cluster"]["job_unit"] == "sample":
            out.append(("bl-%s-%s" % (q["plan"], s["id"]), dict(q, samples=[s], nonce=nonce())))
            continue
        for n, cell in q["cells"].items():
            if cell_input(cell) == sample_input(s["raw"]):
                for p in cell["threads"]:
                    out.append(("bl-%s-%s-%s-p%d" % (q["plan"], s["id"], n, p),       # only its own cell's tool
                                dict(q, samples=[s], nonce=nonce(), cells={n: cell}, only={"cell": n, "threads": p})))
    return out


def corpus_q(q: dict) -> dict:
    """The keys corpus functions read (install_tools, preflight, run_search, load_gate, stage_tdf). No `cells` key:
    corpus.plan_tool_keys would then ask for its own cell tools."""
    return {"root": q["root"], "tools": q["tools"], "search_db_sha256": q["search_db_sha256"], "search_workers": 1,
            "jnatmp": q["jnatmp"], "load_wait_min": q["load_wait_min"], "load_max": q.get("load_max")}


def units(q: dict, s: dict) -> list:
    """(cell, threads, repeat) in run order: repeat 0 ascending threads, repeat 1 descending, ...; at each thread
    step the cell order flips, so no cell always runs first after staging. A cell job keeps its own units only."""
    names = [n for n, cell in q["cells"].items() if cell_input(cell) == sample_input(s["raw"])]
    ps = sorted({p for n in names for p in q["cells"][n]["threads"]})
    out, only = [], q.get("only")
    for rep in range(q["repeats"]):
        for i, p in enumerate(ps if rep % 2 == 0 else ps[::-1]):
            for n in (names if (i + rep) % 2 == 0 else names[::-1]):
                if p in q["cells"][n]["threads"] and (not only or (only["cell"], only["threads"]) == (n, p)):
                    out.append((n, p, rep))
    return out


# ------------------------------------------------------------------------------- node: cell tools
def clean_env(q: dict, env_sh=None) -> dict:
    """corpus.arm_env's rule for a tool without SPX_BIN: probe/allocator/OpenMP/JVM variables and the inherited
    LD_LIBRARY_PATH removed; an env.sh that exports one of them is refused."""
    base = {k: v for k, v in os.environ.items() if not (c.strip_var(k) or k in c.INHERIT_DROP)}
    if env_sh:
        r = subprocess.run(["bash", "-c", 'source "$1" >&2 && env -0', "_", str(env_sh)], env=base, capture_output=True)
        if r.returncode != 0:
            die_queue("G-B02", "sourcing %s failed: %s" % (env_sh, r.stderr.decode(errors="replace")[-300:]))
        base = dict(kv.split("=", 1) for kv in r.stdout.decode(errors="replace").split("\0") if "=" in kv)
        bad = sorted(k for k in base if c.strip_var(k))
        if bad:
            die_queue("G-B02", "%s exports %s: defaults only" % (env_sh, bad))
    base.update(LC_ALL="C", TMPDIR=q["jnatmp"])
    return base


def stat_ident(files) -> dict:
    out = {}
    for f in files:
        try:
            st = os.stat(f)
            out[str(f)] = [st.st_size, st.st_mtime_ns]
        except OSError:
            out[str(f)] = None
    return out


def tree_files(d: Path) -> list:
    return sorted(str(p) for p in Path(d).rglob("*") if p.is_file()) if Path(d).is_dir() else []


def executable(p) -> bool:
    return bool(p) and os.path.isfile(p) and os.access(p, os.X_OK)


def cell_tool(q: dict, name: str) -> dict:
    """What a cell runs and what may not change while it runs (G-B03: sizes + mtimes, cheap enough before and after
    every run; sha256 of the main file once, for the records and the table's one-build rule)."""
    cell = q["cells"][name]
    k = cell["kind"]
    t = {"kind": k, "provenance": None, "deps": {}, "java": None}
    if k == "diaspextract":
        envp = Path(cell["env"])
        env, removed = c.arm_env({"spx_root": str(envp.parent.parent), "arm": envp.parent.name, "jnatmp": q["jnatmp"]})
        arm = os.path.realpath(envp.parent)
        t.update(env=env, exe=env["SPX_BIN"], removed=removed, files=[env["SPX_BIN"]] + tree_files(Path(arm) / "lib"))
        t["sha256"] = c.sha256(t["exe"])
        meta = c.arm_meta(env, {"binary_sha256": t["sha256"]})       # G-V03: provenance + label from --help
        t.update(label=meta["label"], provenance=meta["provenance"], deps=c.ldd_deps(env, arm, t["exe"]))
        t["files"] += sorted(t["deps"])
    elif k == "diatracer":
        env = clean_env(q)
        d = Path(cell["dir"])
        jar, bruker = d / cell["jar"], tree_files(d / "ext" / "bruker")
        if not jar.is_file() or not [f for f in bruker if f.endswith(".so")]:
            die_queue("G-B02", "cell %s: %s or a Bruker library under %s missing" % (name, jar, d / "ext" / "bruker"))
        t["java"] = c.java_info(env)
        t.update(env=env, exe=str(jar), label=cell["jar"], files=[str(jar)] + bruker + [t["java"]["path"]])
        t["sha256"] = c.sha256(jar)
    elif k == "diann":
        env, exe = clean_env(q, cell.get("env")), cell["bin"]
        if not executable(exe):
            die_queue("G-B02", "cell %s: DIA-NN binary missing or not executable: %s" % (name, exe))
        t.update(env=env, exe=exe, label="DIA-NN (%s)" % Path(exe).parent.name,
                 files=tree_files(Path(exe).parent) + ([cell["env"]] if cell.get("env") else []))
        t["sha256"] = c.sha256(exe)
    else:
        env, exe = clean_env(q, cell.get("env")), cell["exe"]
        if not (executable(exe) or (exe.endswith(".jar") and os.path.isfile(exe))):
            die_queue("G-B02", "cell %s: exe missing or not executable: %s" % (name, exe))
        t.update(env=env, exe=exe, label=Path(exe).name, files=[exe] + ([cell["env"]] if cell.get("env") else []))
        t["sha256"] = c.sha256(exe)
    t["stat"] = stat_ident(t["files"])
    return t


def check_drift(t: dict, name: str, when: str) -> None:
    if stat_ident(t["files"]) != t["stat"]:
        die_queue("G-B03", "cell %s: a tool file changed %s (republished under a running queue?)" % (name, when))


def bracket(base: str) -> str:
    return base[:-1].replace(".", r"\.") + "[" + base[-1] + "]"


def busy_patterns(cts: dict) -> list:
    pats = list(c.BUSY_FIXED)
    for t in cts.values():
        if t["kind"] == "diaspextract":
            pats.append(c.bracketed(t["exe"]))
        elif t["kind"] in ("diann", "cmd") and Path(t["exe"]).name not in ("java", "python3", "bash"):
            pats.append(bracket(Path(t["exe"]).name))
    return sorted(set(pats), key=pats.index)


def tool_record(t: dict) -> dict:
    return {k: t[k] for k in ("kind", "exe", "sha256", "label", "provenance", "deps", "java") if k in t}


# ------------------------------------------------------------------------------- node: commands
def build(q: dict, name: str, t: dict, staged: Path, adir: Path, p: int, fasta: str) -> tuple:
    """(argv, cwd, env, output, log) of one timed run; the corpus builders for the corpus tools."""
    cell, tl = q["cells"][name], adir / "time.log"
    k = cell["kind"]
    if k == "diaspextract":
        out = adir / "pseudo.mzML"
        return c.cmd_spx({"threads": p}, t["exe"], staged, out, tl) + cell["args"], adir, t["env"], out, adir / "e.log"
    if k == "diatracer":
        argv = c.cmd_dt({"jnatmp": q["jnatmp"], "diatracer_jar": cell["jar"], "threads": p}, staged, adir, tl)
        return (argv, cell["dir"], dict(t["env"], LD_LIBRARY_PATH="./ext/bruker"),
                staged.with_name(staged.name[:-2] + "_diatracer.mzML"), adir / "dt.log")
    if k == "diann":
        out = adir / "report.parquet"
        argv = [c.TIME, "-v", "-o", str(tl), t["exe"], "--f", str(staged), "--fasta", fasta, "--out", str(out),
                "--out-lib", str(adir / "lib.parquet"), "--temp", str(adir / "tmp"), "--threads", str(p)]
        return argv + DIANN_ARGS + cell["args"], adir, t["env"], out, adir / "diann.log"
    out = adir / cell["out"]
    return [c.TIME, "-v", "-o", str(tl)] + fill(cell["cmd"], staged, out, p, adir, t["exe"]), adir, t["env"], out, adir / "cmd.log"


def cpulist(p: int) -> str:
    """For tools without a thread option (Dear-DIA: hardware_concurrency + TBB affinity): the first p CPUs of the job
    that are the first hyperthread sibling of their core (one per physical core while p <= cores), then the rest."""
    cpus = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else list(range(os.cpu_count() or 1))
    def first(x):
        try:
            return int(re.split(r"[,-]", Path("/sys/devices/system/cpu/cpu%d/topology/thread_siblings_list" % x).read_text())[0]) == x
        except (OSError, ValueError):
            return True
    order = [x for x in cpus if first(x)] + [x for x in cpus if not first(x)]
    return ",".join(map(str, order[:p]))


def fill(template: str, staged, out, p: int, adir, exe: str) -> list:
    """A cmd template as argv: {in} {out} {threads} {dir} {exe} {cpulist}, substituted per shell token."""
    sub = {"{in}": str(staged), "{out}": str(out), "{threads}": str(p), "{dir}": str(adir), "{exe}": exe}
    toks = []
    for tok in shlex.split(template):
        if "{cpulist}" in tok:
            tok = tok.replace("{cpulist}", cpulist(p))
        for a, b in sub.items():
            tok = tok.replace(a, b)
        toks.append(tok)
    return toks


def untimed(q, name, key, t, staged, out, p, adir, rec) -> None:
    """A cmd cell's `pre` (input adapters) or `post` (output to one mzML) steps, outside the timed window. Every
    absolute file named in them is hashed into the record."""
    cell = q["cells"][name]
    for i, tpl in enumerate(cell.get(key, [])):
        argv = fill(tpl, staged, out, p, adir, t["exe"])
        t0 = time.time()
        rc = c.run_logged(argv, adir, t["env"], adir / ("%s%d.log" % (key, i)))
        rec.setdefault(key, []).append({"cmd": argv, "rc": rc, "wall_s": round(time.time() - t0, 1),
                                        "files_sha256": {a: c.sha256(a) for a in argv if a.startswith("/") and os.path.isfile(a)
                                                         and not a.startswith(str(adir)) and not a.startswith(str(staged.parent))}})
        if rc != 0:
            die("G-B04", "%s: %s step %d failed (rc %d): %s" % (name, key, i, rc, " ".join(argv)[:200]))


def diann_counts(report: Path) -> dict:
    """The DIA-NN rule (BASELINE.md): precursors = distinct Precursor.Id with Q.Value <= 0.01 and Lib.Q.Value <= 0.01
    (decoy rows dropped when a Decoy column exists); peptides = distinct Stripped.Sequence of those; protein groups =
    distinct Protein.Group of those with PG.Q.Value <= 0.01."""
    if report.suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError:
            die("G-B04", "pyarrow missing: %s cannot be read on this node" % report.name)
        f = pq.ParquetFile(str(report))
        names = f.schema_arrow.names
        miss = [k for k in DIANN_COLS if k not in names]
        if miss:
            die("G-B04", "%s lacks columns %s" % (report.name, miss))
        cols = list(DIANN_COLS) + (["Decoy"] if "Decoy" in names else [])
        d = f.read(columns=cols).to_pydict()
        rows = (dict(zip(cols, v)) for v in zip(*(d[k] for k in cols)))
    else:
        import csv
        fh = open(report, newline="")
        r = csv.DictReader(fh, delimiter="\t")
        miss = [k for k in DIANN_COLS if k not in (r.fieldnames or [])]
        if miss:
            fh.close()
            die("G-B04", "%s lacks columns %s" % (report.name, miss))
        rows = r
    prec, pep, pg, n = set(), set(), set(), 0
    try:
        for row in rows:
            n += 1
            if str(row.get("Decoy", 0)) not in ("0", "0.0", "False", "false", ""):
                continue
            if float(row["Q.Value"]) <= Q_MAX and float(row["Lib.Q.Value"]) <= Q_MAX:
                prec.add(row["Precursor.Id"])
                pep.add(row["Stripped.Sequence"])
                if float(row["PG.Q.Value"]) <= Q_MAX:
                    pg.add(row["Protein.Group"])
    finally:
        if report.suffix != ".parquet":
            fh.close()
    return {"precursors": len(prec), "peptides": len(pep), "protein_groups": len(pg), "report_rows": n}


def verify(q, name, t, out: Path, adir: Path, log: Path, t0: float) -> dict:
    k = q["cells"][name]["kind"]
    if k == "diann":
        rep = out if out.is_file() else out.with_suffix(".tsv")
        if not rep.is_file() or rep.stat().st_mtime <= t0:
            die("G-B04", "DIA-NN report missing or stale: %s" % out)
        res = {"report": str(rep), "report_bytes": rep.stat().st_size}
        res.update(diann_counts(rep))
        if res["precursors"] <= 0:
            die("G-B04", "DIA-NN: 0 precursors at 1%% q in %s" % rep.name)
        stats = adir / "report.stats.tsv"
        if stats.is_file():                            # DIA-NN's own count, a diagnostic beside ours
            lines = stats.read_text(errors="replace").splitlines()
            if len(lines) >= 2:
                row = dict(zip(lines[0].split("\t"), lines[1].split("\t")))
                res["diag_stats_precursors"] = row.get("Precursors.Identified")
                res["diag_stats_proteins"] = row.get("Proteins.Identified")
        return {"diann": res}
    o = c.verify_mzml(out, t0)                         # G-V08: fresh, terminated, integer count > 0
    if k == "diatracer":
        moved = adir / out.name
        os.replace(out, moved)                         # same filesystem: mtime kept
        o["path"] = str(moved)
        n = c.log_count(log, rb"Writing mzML file\.\.\.(\d+) scans")
    elif k == "diaspextract":
        n = c.log_count(log, rb"Wrote (\d+) pseudo")
    else:
        pat = q["cells"][name].get("count")
        n = c.log_count(log, pat.encode()) if pat else o["count"]
        if n != o["count"]:
            die("G-B04", "%s: count line %s != spectrumList count %s" % (name, n, o["count"]))
    if n != o["count"]:
        die("G-V08", "%s: log count %s != spectrumList count %s" % (name, n, o["count"]))
    return {"output": o, "log_count": n}


# ------------------------------------------------------------------------------- node: staging and runs
def stage_input(q: dict, s: dict, tag: str) -> tuple:
    if sample_input(s["raw"]) == "d":
        return c.stage_tdf({"root": q["root"]}, s, tag)   # 0700, analysis.tdf + tdf_bin, pins on raw and copy
    sroot = Path(q["root"]) / "stage"
    sroot.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(sroot, 0o700)
    d = sroot / ("%s-%s" % (s["id"], tag))
    d.mkdir(mode=0o700)
    raw, pin = Path(s["raw"]), s["pin"]
    if not raw.is_file() or raw.stat().st_size != pin["bytes"]:
        die("G-V02", "raw of %s missing or its size differs from the pin" % s["id"])
    dst, t0 = d / ("%s.mzML" % s["id"]), time.monotonic()
    try:
        shutil.copyfile(raw, dst)
        os.chmod(dst, 0o600)
    except OSError as x:
        die("G-V07", "staging copy of %s failed: %s" % (s["id"], x.strerror or type(x).__name__))
    if c.sha256(dst) != pin["sha256"]:
        die("G-V02", "staged copy of %s differs from its sha256 pin" % s["id"])
    return dst, {"dir": str(d), "name": dst.name, "copy_s": round(time.monotonic() - t0, 1)}


def prewarm(staged: Path) -> float:
    if staged.suffix == ".d":
        return c.prewarm(staged)
    t0 = time.monotonic()
    subprocess.run(["cat", str(staged)], stdout=subprocess.DEVNULL, check=True)
    return round(time.monotonic() - t0, 1)


def rpath(root: Path, sid: str, name: str, p: int, rep: int) -> Path:
    return root / "records" / ("%s.%s.p%d.r%d.json" % (sid, name, p, rep))


def search_tool(q: dict, name: str) -> str:
    """corpus.run_search patches diaTracer output for Sage only when the tool is called `dt`."""
    return "dt" if q["cells"][name]["kind"] == "diatracer" else name


def keeps_output(q: dict, name: str, p: int, rep: int) -> bool:
    cell = q["cells"][name]
    return cell["kind"] != "diann" and rep == 0 and p == cell["search_at"]


def searches_done(q: dict, root: Path, sid: str, name: str, run_id: str) -> bool:
    for e in q["cells"][name]["engines"]:
        r = c.read_json(root / "records" / ("%s.%s.%s.json" % (sid, search_tool(q, name), e)))
        if not (r and r.get("status") == "ok" and r.get("pair_run") == run_id):
            return False
    return True


# environment variables that differ between jobs of one plan and do not configure a tool: left out of the done-key
VOLATILE_ENV = re.compile(r"^(SLURM\w*|SLURMD_\w+|PMIX?_\w+|OMPI_\w+|SSH_\w+|XDG_\w+|BASH_FUNC_\S+|TMPDIR|TMP|TEMP|PWD|OLDPWD"
                          r"|SHLVL|_|HOSTNAME|HOST|DISPLAY|TERM\w*|KRB5CCNAME|LS_COLORS|MAIL|ENVIRONMENT|CUDA_VISIBLE_DEVICES"
                          r"|GPU_DEVICE_ORDINAL|ROCR_VISIBLE_DEVICES)$")


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def cell_key(cell: dict) -> str:
    """The plan's definition of a cell as it shapes one run: args, command templates (cmd, pre, post), env file, inputs,
    search settings. Not its thread axis or wall cap, which add or bound runs without changing one."""
    return _digest({k: v for k, v in cell.items() if k not in ("threads", "wall_cap_h")})


def done_key(q: dict, name: str, s: dict, t: dict) -> str:
    """What a finished run must share with the queue to be reused: the cell definition, the tool's environment (the
    per-job paths written as placeholders, job-scoped variables left out) and the sample (pin, scheme, raw path's
    sha256). Tool build, harness and corpus code are compared separately."""
    subs = [(str(q[k]), "{%s}" % k) for k in ("jnatmp", "root") if q.get(k)]
    def norm(v):
        for a, b in subs:
            v = v.replace(a, b)
        return v
    env = {k: norm(v) for k, v in t["env"].items() if not VOLATILE_ENV.match(k)}
    return _digest({"cell": cell_key(q["cells"][name]), "env": env, "sample": c.sample_record(s)})


def run_done(q: dict, root: Path, s: dict, name: str, p: int, rep: int, t: dict) -> bool:
    """Resume: an ok record of the same tool build, harness and corpus code, cell definition, tool environment and
    sample (done_key); a kept output still the verified file (or its searches done)."""
    r = c.read_json(rpath(root, s["id"], name, p, rep))
    if not (r and r.get("status") == "ok" and r["tool"]["sha256"] == t["sha256"]
            and r.get("harness_sha256") == q["harness_sha256"] and r.get("corpus_sha256") == q["corpus_sha256"]
            and r.get("done_key") == done_key(q, name, s, t)):
        return False
    if not keeps_output(q, name, p, rep) or searches_done(q, root, s["id"], name, r["run_id"]):
        return True
    o, mz = r["output"], Path(r["output"]["path"])
    return mz.is_file() and mz.stat().st_size == o["size"] and mz.stat().st_mtime == o["mtime"]


def node_facts() -> dict:
    """Logical CPUs, the CPUs this job may use (affinity), physical cores and CPU model (/proc/cpuinfo), NUMA nodes,
    and the Slurm job. Physical cores = distinct (physical id, core id); SMT = threads beyond them."""
    phys, model = None, None
    try:
        blocks = [dict(x.split(":", 1) for x in b.splitlines() if ":" in x)
                  for b in Path("/proc/cpuinfo").read_text().split("\n\n") if b.strip()]
        blocks = [{k.strip(): v.strip() for k, v in b.items()} for b in blocks]
        ids = {(b.get("physical id"), b.get("core id")) for b in blocks if "core id" in b}
        phys, model = (len(ids) or None), next((b["model name"] for b in blocks if "model name" in b), None)
    except OSError:
        pass
    numa = len(list(Path("/sys/devices/system/node").glob("node[0-9]*"))) if Path("/sys/devices/system/node").is_dir() else None
    aff = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    return {"host": c.hostname(), "cores": os.cpu_count(), "affinity_cpus": aff, "physical_cores": phys,
            "cpu_model": model, "numa_nodes": numa, "pinning": "none",
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"), "slurm_partition": os.environ.get("SLURM_JOB_PARTITION")}


def check_java(info: dict) -> dict:
    if (info.get("major") or 0) < JAVA_MIN:
        die_queue("G-B02", "java %s at %s is older than %d (diaTracer, MSFragger): put a JDK first on cluster.path"
                  % (info.get("version"), info.get("path"), JAVA_MIN))
    return info


def run_one(q, s, name, p, rep, seq, staged: Path, t: dict, patterns, fasta, facts) -> bool:
    root = Path(q["root"])
    for old in (root / "runs" / s["id"]).glob("%s-p%d-r%d-*" % (name, p, rep)):
        c.remove_tree(old)                             # a superseded attempt of this unit
    run_id = "%s-p%d-r%d-%s" % (name, p, rep, time.strftime("%Y%m%d-%H%M%S-") + os.urandom(2).hex())
    adir = root / "runs" / s["id"] / run_id
    adir.mkdir(parents=True)
    path = rpath(root, s["id"], name, p, rep)
    rec = dict(facts, kind="baseline_run", id=s["id"], sample=c.sample_record(s), cell=name, cell_kind=t["kind"],
               threads=p, rep=rep, seq=seq, run_id=run_id, plan=q["plan"], harness_sha256=q["harness_sha256"],
               corpus_sha256=q["corpus_sha256"], tool=tool_record(t), env_keys=sorted(t["env"]),
               cell_sha256=cell_key(q["cells"][name]), done_key=done_key(q, name, s, t),
               search_at=q["cells"][name]["search_at"], started=c.now_iso(), status="running")
    c.write_json(path, rec)
    out, err = None, None
    try:
        if not str(staged).startswith(str(root / "stage") + os.sep):
            die("G-V07", "run input outside the stage root: %s" % staged)
        rec["gate"] = c.load_gate(corpus_q(q), patterns)
        check_drift(t, name, "before the run")
        argv, cwd, env, out, log = build(q, name, t, staged, adir, p, fasta)
        if t["kind"] == "diann":
            (adir / "tmp").mkdir()
        untimed(q, name, "pre", t, staged, out, p, adir, rec)
        rec.update(cmd=[str(a) for a in argv], cwd=str(cwd), sync_s=c.flush_io(root), prewarm_s=prewarm(staged),
                   ps_top=c.ps_top(), load_before=c.load1(), memavail_before_kb=c.mem_available_kb(), start=c.now_iso())
        with c.ArmMonitor(c.load_max(corpus_q(q))) as mon:
            t0 = time.time()
            rc, why = c.run_capped([str(a) for a in argv], cwd, env, log, q["cells"][name]["wall_cap_h"] * 3600)
        rec.update(end=c.now_iso(), start_epoch=t0, time_rc=rc, during=mon.summary(), load_after=c.load1(),
                   memavail_after_kb=c.mem_available_kb())
        check_drift(t, name, "during the run")
        if why:
            die("G-B05", "%s stopped: %s" % (name, why))
        rec.update(c.parse_time_log(adir / "time.log", "G-V08"))
        c.check_exit(rec, rc, "G-V08", name)
        rec.update(c.time_cpu(adir / "time.log"))
        rec["cpu_util"] = round(rec["cpu_s"] / (rec["wall_s"] * p), 4) if rec.get("cpu_s") is not None and rec["wall_s"] > 0 else None
        untimed(q, name, "post", t, staged, out, p, adir, rec)
        rec.update(verify(q, name, t, out, adir, log, t0))
        rec["contended"] = bool(rec["gate"]["contended"] or rec["during"]["contended"])
        rec["status"] = "ok"
    except Abort as a:
        rec.update(status="failed", guard=a.guard, message=a.message)
        err = a
    except Exception as x:
        rec.update(status="failed", guard="CRASH", message="%s: %s" % (type(x).__name__, x))
    except BaseException as x:
        rec.update(status="failed", guard="KILLED", message="%s during the run" % type(x).__name__)
        err = x
    finally:
        if out is not None and out.parent == staged.parent and out.exists():
            out.unlink()                               # a diaTracer output left beside the staged input
        if t["kind"] == "diann":                       # the predicted library and temp files: GBs per run
            for f in adir.iterdir():
                if not DIANN_KEEP.match(f.name):
                    c.remove_tree(f) if f.is_dir() else f.unlink()
        elif not (rec["status"] == "ok" and keeps_output(q, name, p, rep)):
            for f in list(adir.glob("*.mzML")) + list(adir.glob("*.mzBIN*")):
                f.unlink()
        rec["ended"] = c.now_iso()
        c.write_json(path, rec)
        say("run %s %s p=%d r=%d %s" % (s["id"], name, p, rep, "ok wall %.1f s" % rec["wall_s"] if rec["status"] == "ok"
                                        else "%s [%s] %s" % (rec["status"], rec.get("guard"), rec.get("message"))))
    if err is not None and (not isinstance(err, Abort) or err.queue):
        raise err
    return rec["status"] == "ok"


def run_sample(q, s, cts, patterns, fasta, facts) -> int:
    """Phase 1 for one sample: stage once, every unit back to back, stage deleted in `finally`. Returns failures."""
    root = Path(q["root"])
    todo = [(seq, u) for seq, u in enumerate(units(q, s)) if not run_done(q, root, s, u[0], u[1], u[2], cts[u[0]])]
    if not todo:
        say("sample %s: every run already done" % s["id"])
        return 0
    tag = time.strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex()
    sd, failed = root / "stage" / ("%s-%s" % (s["id"], tag)), 0
    srec = {"kind": "baseline_stage", "id": s["id"], "sample": c.sample_record(s), "node": c.hostname(),
            "started": c.now_iso(), "status": "running"}
    try:
        staged, srec["stage"] = stage_input(q, s, tag)
        srec["status"] = "ok"
        c.write_json(root / "records" / ("%s.stage.json" % s["id"]), srec)
        for seq, (name, p, rep) in todo:
            failed += not run_one(q, s, name, p, rep, seq, staged, cts[name], patterns, fasta, facts)
    except Abort as a:
        if a.queue:
            raise
        srec.update(status="failed", guard=a.guard, message=a.message)
        failed += len(todo)
        say("sample %s: stage failed [%s] %s" % (s["id"], a.guard, a.message))
    finally:
        c.remove_tree(sd)                              # raw-derived data must not linger
        if sd.exists():
            srec.update(status="failed", guard="G-V14", message="staged copy not deleted: %s" % sd)
        srec["ended"] = c.now_iso()
        c.write_json(root / "records" / ("%s.stage.json" % s["id"]), srec)
    if sd.exists():
        die_queue("G-V14", "staged copy not deleted: %s" % sd)
    return failed


def cell_tools(q: dict, name: str, tools: dict, root: Path) -> dict:
    """A cell's own Sage config / MSFragger params (e.g. Orbitrap tolerances), copied run-local beside the plan's. The
    databases they name must be the plan's pinned ones (G-V12)."""
    cell = q["cells"][name]
    over = {k: cell[k] for k in ("sage_config", "msfragger_params") if cell.get(k)}
    if not over:
        return tools
    paths, shas = dict(tools["paths"]), dict(tools["sha256"])
    for k, src in over.items():
        if not os.path.isfile(src):
            die_queue("G-V12", "cell %s: %s missing: %s" % (name, k, src))
        d = root / "tools" / name / Path(src).name
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists() and c.sha256(d) != c.sha256(src):
            die_queue("G-V12", "run-local %s differs from %s" % (d, src))
        shutil.copy2(src, d)
        paths[k], shas[k] = str(d), c.sha256(d)
    for k, p in c.search_dbs(paths["sage_config"], paths["msfragger_params"]).items():
        if c.sha256(p) != q["search_db_sha256"][k]:
            die_queue("G-V12", "cell %s: %s %s differs from the plan pin" % (name, k, p))
    return {"paths": paths, "sha256": shas}


def node_run(q: dict) -> int:
    root = c.node_root_checked(q)                      # 0700; refuses /home and /ceph roots
    return c.with_node_lock(q, "baseline", lambda: _node_run(q, root))   # the corpus node lock: one queue per node


def _node_run(q: dict, root: Path) -> int:
    (root / ("runner-%s.pid" % q["nonce"])).write_text("%d\n" % os.getpid())
    if q.get("corpus_sha256") and c.sha256(c.SELF) != q["corpus_sha256"]:
        die_queue("G-B01", "corpus.py beside this runner differs from the one the queue was resolved with")
    try:
        Path(q["jnatmp"]).mkdir(parents=True, exist_ok=True)
        tempfile.NamedTemporaryFile(dir=q["jnatmp"]).close()
    except OSError as x:
        die_queue("G-V15", "jnatmp %s not writable: %s" % (q["jnatmp"], x))
    c.mem_available_kb()
    c.remove_tree(root / "stage")                      # a killed runner's staged copy
    facts = node_facts()
    mine = {s["id"]: units(q, s) for s in q["samples"]}
    big = sorted({p for u in mine.values() for _, p, _ in u if p > (facts["affinity_cpus"] or 0)})
    if big:
        die_queue("G-B01", "thread counts %s exceed the %s CPUs this job may use on %s" % (big, facts["affinity_cpus"], facts["host"]))
    cq = corpus_q(dict(q, root=str(root)))
    base = clean_env(q)
    pre = c.preflight(cq, base)                        # G-V15 python/time/proc/java, G-V12 database pins
    if "msfragger" in q["engines"] or any(x["kind"] == "diatracer" for x in q["cells"].values()):
        check_java(c.java_info(base))
    tools = c.install_tools(cq)                        # run-local Sage/MSFragger/patch/fix copies (G-V12)
    cts = {n: cell_tool(q, n) for n in q["cells"]}
    patterns = busy_patterns(cts)
    fasta = tools["paths"]["sage_fasta"]               # the corpus human FASTA (target only), pinned; DIA-NN's FASTA
    say("QUEUE_START plan %s host %s job %s nonce %s units %d cells %s python %s java %s" % (
        q["plan"], facts["host"], facts["slurm_job_id"], q["nonce"], sum(map(len, mine.values())), ",".join(q["cells"]),
        pre["python"], pre["java"]["version"]))
    failed = sum(run_sample(q, s, cts, patterns, fasta, facts) for s in q["samples"])
    # phase 2: searches, after every timed run of the queue (never inside a timed window)
    ctx = {"measure": {"search": q["corpus_sha256"], "score": q["corpus_sha256"]}, "ident": {"java": c.java_info(base)}}
    for s in q["samples"]:
        for name, cell in q["cells"].items():
            if cell["kind"] == "diann" or (name, cell["search_at"], 0) not in mine[s["id"]]:
                continue                               # DIA-NN is its own search; another job owns that unit
            r0 = c.read_json(rpath(root, s["id"], name, cell["search_at"], 0))
            if not (r0 and r0.get("status") == "ok"):
                failed += len(q["engines"])
                continue
            st, ctools = search_tool(q, name), cell_tools(q, name, tools, root)
            pair = {"pair_run": r0["run_id"], "arms": {st: {"output": r0["output"]}}}
            for e in cell["engines"]:
                sr = c.read_json(root / "records" / ("%s.%s.%s.json" % (s["id"], st, e)))
                if sr and sr.get("status") == "ok" and sr.get("pair_run") == r0["run_id"] and sr.get("tools_sha256") == ctools["sha256"]:
                    continue
                failed += not c.run_search(cq, s, st, e, pair, ctools, base, ctx)
            if searches_done(q, root, s["id"], name, r0["run_id"]):
                Path(r0["output"]["path"]).unlink(missing_ok=True)
    left = sorted(str(p.relative_to(root)) for p in (root / "runs").rglob("*.mzML")) if (root / "runs").is_dir() else []
    msg = "failed %d mzml_left %d" % (failed, len(left))
    (root / ("QUEUE_DONE-%s" % q["nonce"])).write_text(msg + "\n")
    say("QUEUE_DONE " + msg)
    return 0 if failed == 0 else 1


# ------------------------------------------------------------------------------- node: Slurm job, read-only commands
def job_env_root(spec: dict) -> Path:
    """G-B07: the job works in the node-local $TMPDIR (BinAC2: /scratch/<jobid>, cleaned when the job ends)."""
    tmp = os.environ.get("TMPDIR", "")
    real = os.path.realpath(tmp) if tmp else ""
    if not tmp or not os.path.isdir(tmp) or any(x.startswith(("/pfs/", "/home/", "/ceph/")) for x in (tmp, real)):
        die_queue("G-B07", "TMPDIR %r is unset, missing or not node-local: staging needs the node's own disk" % tmp)
    if not str(spec.get("results", "")).startswith("/"):
        die_queue("G-B07", "results %r is not an absolute path" % spec.get("results"))
    return Path(tmp)


def job_main(spec: dict) -> int:
    """One Slurm job: a baseline queue (mode baseline) or a corpus.py queue (mode corpus) with root, lock and jnatmp
    in $TMPDIR, records written straight to <results>/records (a symlink), logs copied out at the end."""
    tmp = job_env_root(spec)
    os.environ["PATH"] = os.pathsep.join(spec.get("path", []) + [os.environ.get("PATH", "")])
    res = Path(spec["results"])
    (res / "records").mkdir(parents=True, exist_ok=True)
    q = dict(spec["q"])
    root = tmp / ("job-%s" % q["nonce"])
    q.update(root=str(root), lock=str(tmp / ".queue.lock"), jnatmp=str(tmp / "jnatmp"), load_wait_min=0)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not (root / "records").exists():
        os.symlink(str(res / "records"), str(root / "records"))
    say("JOB_START mode %s job %s host %s root %s results %s" % (spec["mode"], os.environ.get("SLURM_JOB_ID"),
                                                                c.hostname(), root, res))
    rc = 2
    try:
        rc = (node_run if spec["mode"] == "baseline" else c.node_run)(q)
    finally:                                           # logs, time logs, TSVs, DIA-NN reports; never raw or mzML
        (root / "records").unlink()
        shutil.copytree(str(root), str(res / "runs"), symlinks=True, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(*COPY_IGNORE))
        say("JOB_DONE rc %s, logs copied to %s" % (rc, res / "runs"))
    return rc


def node_busy(q: dict) -> dict:
    """preflight, read-only, on the cluster's login node (same filesystems as the compute nodes)."""
    out = {"load1": c.load1(), "error": None, "error_guard": None, "cells": {}, "preflight": None, "pyarrow": None,
           "python": sys.version.split()[0], "results_exists": os.path.isdir(q["results"])}
    out.update(node_facts())
    try:
        os.environ["PATH"] = os.pathsep.join(q["cluster"].get("path", []) + [os.environ.get("PATH", "")])
        with tempfile.TemporaryDirectory() as td:
            q = dict(q, root=td, jnatmp=td)
            base = clean_env(q)
            for n in q["cells"]:
                t = cell_tool(q, n)
                out["cells"][n] = {"kind": t["kind"], "label": t["label"], "exe": t["exe"], "sha256": t["sha256"],
                                   "files": len(t["files"])}
            if any(cell["kind"] == "diann" for cell in q["cells"].values()):
                try:
                    import pyarrow
                    out["pyarrow"] = pyarrow.__version__
                except ImportError:
                    die_queue("G-B02", "no pyarrow for %s: DIA-NN's report.parquet cannot be counted" % sys.executable)
            out["preflight"] = c.preflight(corpus_q(q), base)
            if "msfragger" in q["engines"] or any(x["kind"] == "diatracer" for x in q["cells"].values()):
                check_java(c.java_info(base))
            for s in q["samples"]:                     # the inputs exist and match their pins (read-only)
                if sample_input(s["raw"]) == "d":
                    c.check_pin(c.fingerprint(Path(s["raw"]), what="raw of %s" % s["id"]), s["pin"], "raw of %s" % s["id"])
                elif not os.path.isfile(s["raw"]) or os.path.getsize(s["raw"]) != s["pin"]["bytes"]:
                    die("G-V02", "raw of %s missing or its size differs from the pin" % s["id"])
    except Abort as a:
        out.update(error=a.message, error_guard=a.guard)
    return out


def node_records(o: dict) -> list:
    d = Path(o["root"]) / "records"
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.is_dir() else []


def node_main(argv: list) -> int:
    cmd = argv[0]
    try:
        if cmd == "job":                               # job --spec PATH (the sbatch script's only command)
            import signal
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # walltime/scancel: finally-blocks still run
            return job_main(json.loads(Path(argv[2]).read_text()))
        obj = json.loads(base64.b64decode(argv[1]))
        fn = {"node-busy": node_busy, "node-records": node_records}[cmd]
        print("@@JSON " + json.dumps(fn(obj)))
        return 0
    except Abort as a:
        if cmd == "job":
            say("QUEUE_ABORTED %s" % a)
        else:
            print("@@JSON " + json.dumps({"abort": a.message, "guard": a.guard}))
        return 2
    except Exception as x:
        if cmd != "job":
            raise
        import traceback
        say("QUEUE_ABORTED [CRASH] %s: %s\n%s" % (type(x).__name__, x, traceback.format_exc()))
        return 2
    except BaseException as x:
        if cmd == "job":
            say("QUEUE_ABORTED [KILLED] %s" % type(x).__name__)
        raise


# ------------------------------------------------------------------------------- table
def scaling(walls: dict, p0: int, phys=None) -> list:
    """walls {p: [wall_s per repeat]} -> one row per p. T(p) is the median wall over repeats; with p0 the smallest
    thread count of the cell's axis: S(p) = T(p0)/T(p), E(p) = T(p0)*p0 / (T(p)*p). No T(p0), no S/E. With the node's
    physical core count: smt = p > phys, and E_phys(p) = T(p0)*min(p0,phys) / (T(p)*min(p,phys)), the efficiency per
    physical core in use (SMT threads beyond the cores add no denominator)."""
    t0 = statistics.median(walls[p0]) if walls.get(p0) else None
    rows = []
    for p in sorted(walls):
        w = walls[p]
        t = statistics.median(w)
        rows.append({"p": p, "n": len(w), "wall_s": round(t, 2), "wall_min_s": min(w), "wall_max_s": max(w),
                     "spread": round((max(w) - min(w)) / t, 4) if len(w) > 1 and t > 0 else None,
                     "speedup": round(t0 / t, 4) if t0 and t > 0 else None,
                     "efficiency": round(t0 * p0 / (t * p), 4) if t0 and t > 0 else None,
                     "smt": p > phys if phys else None,
                     "efficiency_physical": round(t0 * min(p0, phys) / (t * min(p, phys)), 4) if t0 and t > 0 and phys else None})
    return rows


def render(name: str, plan: dict, reg: dict, recs: list) -> tuple:
    """-> (summary dict, markdown, complete). G-B06 refuses records that cannot share one table."""
    cells = norm_cells(plan)
    engines = list(plan.get("engines", c.ENGINES))
    runs = {(r["id"], r["cell"], r["threads"], r["rep"]): r for r in recs if r.get("kind") == "baseline_run"}
    for k, r in list(runs.items()):                   # measured under another cell definition or sample pin: not this plan's
        e = reg["samples"].get(r["id"], {})
        if r.get("status") == "ok" and r["cell"] in cells and (
                r.get("cell_sha256") != cell_key(cells[r["cell"]])
                or (r.get("sample") or {}).get("pin") != e.get("pin")
                or (r.get("sample") or {}).get("raw_sha256") != hashlib.sha256(
                    (map_raw(e["raw"], plan.get("raw_map")) or "").encode()).hexdigest()):
            runs[k] = dict(r, status="stale", guard="G-B06", message="measured under another cell definition or sample")
    srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r.get("kind") == "search"}
    stages = {r["id"]: r for r in recs if r.get("kind") == "baseline_stage"}
    ok = [r for r in runs.values() if r.get("status") == "ok"]
    for n in cells:
        shas = {r["tool"]["sha256"] for r in ok if r["cell"] == n}
        if len(shas) > 1:
            die("G-B06", "cell %s: records of %d tool builds %s" % (n, len(shas), sorted(x[:12] for x in shas)))
    code = {(r.get("harness_sha256"), r.get("corpus_sha256")) for r in ok}
    if len(code) > 1:
        die("G-B06", "records of %d harness/corpus code versions: re-run or table them separately" % len(code))
    for sid in {r["id"] for r in ok}:                 # job_unit cell spreads a sample over nodes of one type
        models = {(r.get("cpu_model"), r.get("physical_cores"), r.get("cores")) for r in ok if r["id"] == sid}
        if len(models) > 1:
            die("G-B06", "sample %s measured on %d CPU models/core counts %s: scaling needs one node type"
                % (sid, len(models), sorted(map(str, models))))
    for r in ok:
        if r["wall_s"] <= 0 or r.get("peak_rss_kb", 0) <= 0 or ("output" in r and r["output"]["count"] <= 0):
            die("G-B06", "ok record %s with wall/RSS/spectra <= 0" % r["run_id"])
    order = list(plan["samples"])
    out = {"plan": name, "generated": c.now_iso(), "q_max": Q_MAX, "engines": engines, "repeats": plan["repeats"],
           "pinning": "none", "cells": {n: {"kind": x["kind"], "threads": x["threads"], "search_at": x["search_at"],
                                            "label": next((r["tool"]["label"] for r in ok if r["cell"] == n), None),
                                            "sha256": next((r["tool"]["sha256"] for r in ok if r["cell"] == n), None)}
                                        for n, x in cells.items()},
           "code": sorted(list(x) for x in code), "rows": [], "per_tool": {}, "missing": []}
    for sid in order:
        e = reg["samples"][sid]
        for n, cell in cells.items():
            if cell_input(cell) != sample_input(e["raw"]):
                continue
            row = {"sample": sid, "label": e.get("label", sid), "scheme": e.get("scheme"), "cell": n,
                   "kind": cell["kind"], "nodes": [], "cores": None, "physical_cores": None, "cpu_model": None,
                   "contended": False, "ids": {}, "scaling": []}
            walls, rss, util = {}, {}, {}
            for p in cell["threads"]:
                for rep in range(plan["repeats"]):
                    r = runs.get((sid, n, p, rep))
                    if not (r and r.get("status") == "ok"):
                        out["missing"].append("%s %s p=%d r=%d %s" % (sid, n, p, rep, "[%s] %s" % (r.get("guard"), r.get("message"))
                                                                     if r else (("stage [%s]" % stages[sid].get("guard"))
                                                                                if stages.get(sid, {}).get("status") == "failed" else "not run")))
                        continue
                    row.update(cores=r["cores"], physical_cores=r.get("physical_cores"), cpu_model=r.get("cpu_model"),
                               numa_nodes=r.get("numa_nodes"))
                    if r["host"] not in row["nodes"]:
                        row["nodes"].append(r["host"])
                    row["contended"] |= bool(r.get("contended"))
                    walls.setdefault(p, []).append(r["wall_s"])
                    rss.setdefault(p, []).append(r["peak_rss_kb"])
                    if r.get("cpu_util") is not None:
                        util.setdefault(p, []).append(r["cpu_util"])
            for x in scaling(walls, cell["threads"][0], row["physical_cores"]) if walls else []:
                x["rss_gb"] = round(statistics.median(rss[x["p"]]) / 1e6, 2)
                x["rss_max_gb"] = round(max(rss[x["p"]]) / 1e6, 2)
                x["cpu_util"] = round(statistics.median(util[x["p"]]), 4) if util.get(x["p"]) else None
                x["contended"] = any(runs[(sid, n, x["p"], k)].get("contended") for k in range(plan["repeats"])
                                     if runs.get((sid, n, x["p"], k), {}).get("status") == "ok")
                row["scaling"].append(x)
            r0 = runs.get((sid, n, cell["search_at"], 0))
            if r0 and r0.get("status") == "ok":
                if cell["kind"] == "diann":
                    row["ids"] = {k: r0["diann"][k] for k in ("precursors", "peptides", "protein_groups")}
                    pr = [runs[(sid, n, p, k)]["diann"]["precursors"] for p in cell["threads"] for k in range(plan["repeats"])
                          if runs.get((sid, n, p, k), {}).get("status") == "ok"]
                    row["ids"]["precursors_range_over_runs"] = [min(pr), max(pr)]
                else:
                    row["ids"]["spectra"] = r0["output"]["count"]
                    for eng in cell["engines"]:
                        sr = srch.get((sid, search_tool({"cells": cells}, n), eng))
                        if sr and sr.get("status") == "ok" and sr.get("pair_run") == r0["run_id"]:
                            row["ids"][eng + "_peptides"] = sr["peptides"]
                            if eng == "sage":
                                row["ids"]["sage_target_peptides"] = sr.get("target_peptides")
                        else:
                            out["missing"].append("%s %s search %s %s" % (sid, n, eng, "[%s] %s" % (sr.get("guard"), sr.get("message"))
                                                                         if sr else "not run"))
            out["rows"].append(row)
    for n, cell in cells.items():                      # per tool: sums over the samples that have every p
        rows = [r for r in out["rows"] if r["cell"] == n]
        full = [r for r in rows if [x["p"] for x in r["scaling"]] == cell["threads"]]
        tot = {cell["threads"][i]: [sum(r["scaling"][i]["wall_s"] for r in full)] for i in range(len(cell["threads"]))} if full else {}
        ids = {}
        for r in rows:
            for k, v in r["ids"].items():
                if isinstance(v, int):
                    ids[k] = ids.get(k, 0) + v
        out["per_tool"][n] = {"samples": len(rows), "samples_all_p": len(full), "ids_sum": ids,
                              "scaling_sum_wall": scaling(tot, cell["threads"][0], full[0]["physical_cores"]) if tot else []}
    return out, markdown(out), not out["missing"]


def _n(v, fmt="{:,}"):
    return "-" if v is None else fmt.format(v)


def markdown(o: dict) -> str:
    L = ["# Baseline %s" % o["plan"], "",
         "Generated %s. Exclusive Slurm nodes, thread pinning: none. T(p) = median wall over %d repeat(s); "
         "S(p) = T(p0)/T(p); E(p) = T(p0)*p0/(T(p)*p), p0 = smallest thread count of the cell; E_phys(p) uses "
         "min(p, physical cores) instead of p; SMT = p above the physical cores. CPU util = (user+sys)/(wall*p). "
         "`*` = contended (G-V06). DIA-NN wall is end to end (in-silico library prediction + search); extractor wall "
         "excludes the search." % (o["generated"], o["repeats"]), "",
         "| cell | kind | tool | sha256 | threads | search at |", "|---|---|---|---|---|---|"]
    for n, x in o["cells"].items():
        L.append("| %s | %s | %s | %s | %s | %s |" % (n, x["kind"], x["label"] or "-", (x["sha256"] or "-")[:12],
                                                  ", ".join(map(str, x["threads"])), x["search_at"]))
    L += ["", "## Identifications (1% q)", "",
          "| sample | cell | nodes | spectra | Sage peptides | MSFragger peptides | DIA-NN precursors | DIA-NN peptides | DIA-NN protein groups |",
          "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in o["rows"]:
        i = r["ids"]
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["label"], r["cell"], ", ".join(r["nodes"]) or "-", _n(i.get("spectra")), _n(i.get("sage_peptides")),
            _n(i.get("msfragger_peptides")), _n(i.get("precursors")), _n(i.get("peptides")), _n(i.get("protein_groups"))))
    L += ["", "## Scaling", "", "| sample | cell | p | SMT | wall | RSS GB | CPU util | S(p) | E(p) | E_phys(p) | n | spread |",
          "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in o["rows"]:
        for x in r["scaling"]:
            L.append("| %s | %s | %d | %s | %s%s | %s | %s | %s | %s | %s | %d | %s |" % (
                r["label"], r["cell"], x["p"], {True: "yes", False: "no"}.get(x["smt"], "-"), c.hms(x["wall_s"]),
                "*" if x["contended"] else "", _n(x["rss_gb"], "{:.1f}"), _n(x["cpu_util"], "{:.2f}"),
                _n(x["speedup"], "{:.2f}"), _n(x["efficiency"], "{:.2f}"), _n(x["efficiency_physical"], "{:.2f}"), x["n"],
                _n(x["spread"], "{:.1%}")))
    L += ["", "## Per tool (sum of T(p) over samples with every p)", "",
          "| cell | samples | p | sum wall | S(p) | E(p) | E_phys(p) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for n, t in o["per_tool"].items():
        for x in t["scaling_sum_wall"]:
            L.append("| %s | %d | %d | %s | %s | %s | %s |" % (n, t["samples_all_p"], x["p"], c.hms(x["wall_s"]),
                                                             _n(x["speedup"], "{:.2f}"), _n(x["efficiency"], "{:.2f}"),
                                                             _n(x["efficiency_physical"], "{:.2f}")))
    if o["missing"]:
        L += ["", "## Missing (%d)" % len(o["missing"]), ""] + ["- " + m for m in o["missing"]]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------------- local commands (laptop side)
def remote(host: str, python: str, cmd: str, obj):
    """This file and corpus.py over stdin (`<python> -`) on the cluster's login node: read-only, never a stale copy."""
    b64 = lambda p: base64.b64encode(Path(p).read_bytes()).decode()
    boot = ("import base64, sys, types\n"
            "m = types.ModuleType('corpus')\n"
            "exec(compile(base64.b64decode('%s'), 'corpus.py', 'exec'), m.__dict__)\n"
            "sys.modules['corpus'] = m\n"
            "sys.argv = ['baseline.py'] + sys.argv[1:]\n"
            "exec(compile(base64.b64decode('%s'), 'baseline.py', 'exec'), {'__name__': '__main__'})\n"
            % (b64(c.SELF), b64(SELF)))
    arg = base64.b64encode(json.dumps(obj).encode()).decode()
    r = subprocess.run(c.SSH + [host, python, "-", cmd, arg], input=boot.encode(), capture_output=True)
    for line in reversed(r.stdout.decode(errors="replace").splitlines()):
        if line.startswith("@@JSON "):
            res = json.loads(line[7:])
            if isinstance(res, dict) and set(res) == {"abort", "guard"}:
                die(res["guard"], "%s: %s" % (host, res["abort"]))
            return res
    sys.exit("remote %s on %s failed (rc %d): %s" % (cmd, host, r.returncode, r.stderr.decode(errors="replace")[-600:]))


def sbatch_script(name: str, cl: dict, results: str, hdir: str, spec: str) -> str:
    """One exclusive whole node per job; --mem=0 = all of its memory; output beside the job's spec."""
    lines = ["#!/bin/bash", "#SBATCH --partition=%s" % cl["partition"], "#SBATCH --nodes=1", "#SBATCH --exclusive",
             "#SBATCH --mem=0", "#SBATCH --time=%s" % cl["walltime"], "#SBATCH --job-name=%s" % name,
             "#SBATCH --output=%s/jobs/%%x-%%j.out" % results]
    lines += ["#SBATCH --cpus-per-task=%d" % cl["cpus"]] if cl.get("cpus") else []
    lines += ["#SBATCH %s" % a for a in cl.get("sbatch_args", [])]
    lines += ["set -u", "exec %s %s/baseline.py job --spec %s" % (shlex.quote(cl["python"]), hdir, spec)]
    return "\n".join(lines) + "\n"


def harness_dir(results: str) -> str:
    return "%s/harness/%s" % (results, c.sha256(SELF)[:8] + c.sha256(c.SELF)[:8])   # content-named, never overwritten


def submit(cl: dict, results: str, specs: list, dry: bool, out=print) -> int:
    """specs: [(job name, spec dict)]. Copies baseline.py + corpus.py (content-named) and each spec + sbatch script to
    <results>, then `sbatch` each over ssh. Each job skips units already ok in <results>/records (resume)."""
    hdir = harness_dir(results)
    scripts = [(name, "%s/jobs/%s.json" % (results, name), "%s/jobs/%s.sbatch" % (results, name), spec)
               for name, spec in specs]
    if dry:
        for name, sp, sb, spec in scripts:
            out("== job %s\n%s" % (name, sbatch_script(name, cl, results, hdir, sp)))
        return 0
    h = cl["host"]
    c.ssh(h, "mkdir -p %s %s/jobs %s/records && chmod 700 %s" % (shlex.quote(hdir), results, results, results))
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        shutil.copy(SELF, t / "baseline.py")
        shutil.copy(c.SELF, t / "corpus.py")
        for name, sp, sb, spec in scripts:
            (t / Path(sp).name).write_text(json.dumps(spec, indent=1))
            (t / Path(sb).name).write_text(sbatch_script(name, cl, results, hdir, sp))
        if subprocess.run(["scp", "-q", "-o", "ConnectTimeout=20", str(t / "baseline.py"), str(t / "corpus.py"),
                           "%s:%s/" % (h, hdir)]).returncode:
            sys.exit("scp of the harness to %s failed" % h)
        files = [str(t / Path(x).name) for _, sp, sb, _ in scripts for x in (sp, sb)]
        if subprocess.run(["scp", "-q", "-o", "ConnectTimeout=20"] + files + ["%s:%s/jobs/" % (h, results)]).returncode:
            sys.exit("scp of the job files to %s failed" % h)
    ids = c.ssh(h, " && ".join("sbatch --parsable %s" % shlex.quote(sb) for _, _, sb, _ in scripts)).split()
    for (name, _, _, _), jid in zip(scripts, ids):
        out("SUBMITTED %s job %s" % (name, jid))
    return 0 if len(ids) == len(scripts) else 1


def dry_run(q: dict, out=print) -> None:
    """Every command of a job, in run order, with symbolic tool paths (env.sh is sourced only on the node)."""
    root = Path("$TMPDIR/job-%s" % q["nonce"])
    q = dict(q, root=str(root), jnatmp="$TMPDIR/jnatmp")       # set by job_main on the node
    out("-- plan %s nonce %s repeats %d engines %s only %s pinning none" % (
        q["plan"], q["nonce"], q["repeats"], ",".join(q["engines"]), q.get("only") or "all units"))
    fasta = "<sage_fasta: database.fasta of %s, sha256 %s...>" % (Path(q["tools"]["sage_config"]).name,
                                                                q["search_db_sha256"]["sage_fasta"][:12])
    for s in q["samples"]:
        mine = units(q, s)
        staged = root / "stage" / ("%s-<tag>" % s["id"]) / (s["id"] + (".d" if sample_input(s["raw"]) == "d" else ".mzML"))
        out("-- sample %s (%s): stage %s -> %s" % (s["id"], s.get("scheme"), s["raw"], staged))
        for seq, (n, p, rep) in enumerate(mine):
            cell = q["cells"][n]
            exe = {"diaspextract": "$SPX_BIN(%s)" % cell.get("env"), "diatracer": "%s/%s" % (cell.get("dir"), cell.get("jar")),
                   "diann": cell.get("bin"), "cmd": cell.get("exe")}[cell["kind"]]
            t = {"kind": cell["kind"], "exe": exe, "env": {}}
            argv, cwd, _, o, _ = build(q, n, t, staged, root / "runs" / s["id"] / ("%s-p%d-r%d-<stamp>" % (n, p, rep)), p, fasta)
            out("[%02d] %s p=%d r=%d%s  cd %s && %s" % (seq, n, p, rep, "  (output kept for search)"
                                                      if keeps_output(q, n, p, rep) else "", cwd, shlex.join(map(str, argv))))
        tp = {k: str(root / "tools" / ("sage/sage" if k == "sage" else Path(v).name)) for k, v in q["tools"].items()}
        for n, cell in q["cells"].items():
            if cell["kind"] == "diann" or (n, cell["search_at"], 0) not in mine:
                continue
            st = search_tool(q, n)
            sdir = root / "runs" / s["id"] / ("%s-p%d-r0-<stamp>" % (n, cell["search_at"])) / "search"
            mz = sdir.parent / ("%s_diatracer.mzML" % s["id"] if st == "dt" else "pseudo.mzML" if cell["kind"] == "diaspextract" else cell["out"])
            if "sage" in cell["engines"]:
                inp = mz
                if st == "dt":
                    inp = sdir / "dt_sage" / "patched.mzML"
                    out("[search] %s sage: %s" % (n, shlex.join(c.cmd_patch(tp, mz, inp, "patch.time"))))
                out("[search] %s sage: cd %s && %s" % (n, sdir / ("%s_sage" % st), shlex.join(c.cmd_sage(tp, inp, sdir / ("%s_sage" % st), "engine.time"))))
            if "msfragger" in cell["engines"]:
                d = sdir / ("%s_msfragger" % st)
                out("[search] %s msfragger: cd %s && %s && ln -s fixed.mzML in.mzML && %s" % (
                    n, d, shlex.join(c.cmd_fix(tp, mz, d / "fixed.mzML", "fix.time")), shlex.join(c.cmd_msf(tp, "engine.time"))))


def plan_jobs(args, plan, reg) -> list:
    q = resolve(args.plan, plan, reg)
    out = []
    for name, jq in jobs(q):
        s = jq["samples"][0]
        if (args.sample and s["id"] != args.sample) or (getattr(args, "cell", None) and (jq.get("only") or {}).get("cell") not in (None, args.cell)):
            continue
        if getattr(args, "cell", None) and not jq.get("only"):
            jq = dict(jq, cells={args.cell: jq["cells"][args.cell]})
        out.append((name, {"mode": "baseline", "results": plan["results"], "path": plan["cluster"].get("path", []), "q": jq}))
    return out


def cmd_dry_run(args) -> int:
    plan, reg = load_plan(args.plan, args.registry)
    for name, spec in plan_jobs(args, plan, reg):
        print("== job %s" % name)
        print(sbatch_script(name, plan["cluster"], plan["results"], harness_dir(plan["results"]),
                            "%s/jobs/%s.json" % (plan["results"], name)).rstrip())
        dry_run(spec["q"])
    return 0


def cmd_submit(args) -> int:
    plan, reg = load_plan(args.plan, args.registry)
    return submit(plan["cluster"], plan["results"], plan_jobs(args, plan, reg), False)


def corpus_specs(args, plan, reg) -> tuple:
    """A corpus.py plan (its arm, diaTracer, tools: cluster paths) as one job per sample; the baseline plan gives the
    cluster, raw_map and results root. corpus.load_plan's G-V01 rules apply unchanged."""
    cplan, creg = c.load_plan(args.corpus_plan, args.registry)
    results = "%s/corpus-%s" % (plan["results"].rstrip("/"), args.corpus_plan)
    specs = []
    for node in cplan["queues"]:
        q = c.resolve_queue(args.corpus_plan, cplan, creg, node)
        for s in q["samples"]:
            if args.sample and s["id"] != args.sample:
                continue
            raw = map_raw(s["raw"], plan.get("raw_map"))
            if raw is None:
                die("G-B01", "sample %s: raw %s is under no raw_map prefix" % (s["id"], s["raw"]))
            jq = dict(q, samples=[dict(s, raw=raw)], nonce=nonce(), node="slurm")
            specs.append(("cp-%s-%s" % (args.corpus_plan, s["id"]),
                          {"mode": "corpus", "results": results, "path": plan["cluster"].get("path", []), "q": jq}))
    return cplan, creg, results, specs


def cmd_submit_corpus(args) -> int:
    plan, reg = load_plan(args.plan, args.registry)
    _, _, results, specs = corpus_specs(args, plan, reg)
    return submit(plan["cluster"], results, specs, args.dry)


def cmd_preflight(args) -> int:
    plan, reg = load_plan(args.plan, args.registry)
    q = resolve(args.plan, plan, reg)
    cl = plan["cluster"]
    b = remote(cl["host"], cl["python"], "node-busy", q)
    print("== %s (host %s, python %s %s) cpus %s affinity %s physical %s numa %s model %s; results dir %s" % (
        cl["host"], b["host"], cl["python"], b["python"], b["cores"], b["affinity_cpus"], b["physical_cores"],
        b["numa_nodes"], b["cpu_model"], "exists" if b["results_exists"] else "missing (submit creates it)"))
    for n, x in b["cells"].items():
        print("   cell %s (%s): %s, %s, sha256 %s, %d files watched" % (n, x["kind"], x["label"], x["exe"], x["sha256"][:16], x["files"]))
    if b["pyarrow"]:
        print("   pyarrow %s" % b["pyarrow"])
    if b["preflight"]:
        pre = b["preflight"]
        print("   python %s, %s is GNU time, java %s, sage_fasta %s, msfragger_db %s" % (
            pre["python"], pre["time"], pre["java"]["version"], pre["search_db"]["sage_fasta"]["sha256"][:16],
            pre["search_db"]["msfragger_db"]["sha256"][:16]))
    if b["error"]:
        print("   ABORT [%s] %s" % (b["error_guard"], b["error"]))
    print("PREFLIGHT_OK (login node; compute nodes share its filesystems)" if not b["error"] else "PREFLIGHT_FAILED")
    return 0 if not b["error"] else 2


def cmd_status(args) -> int:
    plan, reg = load_plan(args.plan, args.registry)
    cl = plan["cluster"]
    print(c.ssh(cl["host"], "squeue --me -h -o '%%i %%j %%T %%M %%N %%r' | grep -E ' (bl|cp)-%s' || echo 'no queued or running jobs'"
                % re.escape(args.plan)).rstrip())
    count = {}
    for r in remote(cl["host"], cl["python"], "node-records", {"root": plan["results"]}):
        k = "%s %s" % (r.get("kind"), r.get("status"))
        count[k] = count.get(k, 0) + 1
    print("records: %s" % (count or "none"))
    return 0


def cmd_fetch(args) -> int:
    plan, _ = load_plan(args.plan, args.registry)
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    src = plan["results"] if not args.corpus_plan else "%s/corpus-%s" % (plan["results"].rstrip("/"), args.corpus_plan)
    rc = subprocess.run(["scp", "-rq", "-o", "ConnectTimeout=20", "%s:%s/records" % (plan["cluster"]["host"], src), str(dest)]).returncode
    print("fetched %s:%s/records -> %s/records (rc %d)" % (plan["cluster"]["host"], src, dest, rc))
    return rc


def records_from(args, plan, root) -> list:
    if args.source == "remote":
        return remote(plan["cluster"]["host"], plan["cluster"]["python"], "node-records", {"root": root})
    return node_records({"root": args.source})


def cmd_table(args) -> int:
    plan, reg = load_plan(args.plan, args.registry)
    obj, md, complete = render(args.plan, plan, reg, records_from(args, plan, plan["results"]))
    if args.out:
        c.write_json(Path(args.out + ".json"), obj)
        Path(args.out + ".md").write_text(md)
        print("wrote %s.json and %s.md" % (args.out, args.out))
    else:
        print(md)
    if not complete:
        print("TABLE_INCOMPLETE %d missing" % len(obj["missing"]))
    return 0 if complete else 3


def mapped_registry(reg: dict, raw_map) -> dict:
    """The registry with every sample raw passed through the plan's raw_map, as corpus_specs gave it to the jobs: the
    records hold sha256(mapped raw), so corpus.table_guards' G-V13 raw check compares like with like. A raw under no
    prefix stays as written (its records cannot match it, so G-V13 still aborts); a different raw still aborts."""
    out = dict(reg, samples={})
    for sid, e in (reg.get("samples") or {}).items():
        raw = map_raw(str(e.get("raw")), raw_map) if isinstance(e, dict) and e.get("raw") is not None else None
        out["samples"][sid] = dict(e, raw=raw) if raw is not None else e
    return out


def cmd_corpus_table(args) -> int:
    """corpus.py's own table (render_table / render_cells_table, G-V13) over the records of the corpus jobs."""
    plan, _ = load_plan(args.plan, args.registry)
    cplan, creg = c.load_plan(args.corpus_plan, args.registry)
    recs = records_from(args, plan, "%s/corpus-%s" % (plan["results"].rstrip("/"), args.corpus_plan))
    md, incomplete, total = (c.render_cells_table if c.extended(cplan) else c.render_table)(
        args.corpus_plan, cplan, mapped_registry(creg, plan.get("raw_map")), recs, "slurm")
    if args.out:
        Path(args.out).write_text(md)
        print("wrote %s: %d of %d rows incomplete" % (args.out, incomplete, total))
    else:
        print(md)
    return 3 if incomplete else 0


# ------------------------------------------------------------------------------- selftest
FAKE_BTIME = r'''#!/usr/bin/env python3
# GNU time -v stand-in: wall = 100 + 800/p s, user = 0.9 * wall * p, RSS = 1e6 + 1e5 * p kB (p from -threads/-t/--threads)
import subprocess, sys
assert sys.argv[1:3] == ["-v", "-o"], sys.argv
out, cmd = sys.argv[3], sys.argv[4:]
rc = subprocess.call(cmd)
p = 1
for i, a in enumerate(cmd[:-1]):
    if a in ("-threads", "-t", "--threads"):
        p = int(cmd[i + 1])
wall = 100 + 800.0 / p
with open(out, "w") as f:
    f.write('Command being timed: "%s"\n' % " ".join(cmd))
    f.write("User time (seconds): %.2f\nSystem time (seconds): 0.00\nPercent of CPU this job got: %d%%\n" % (0.9 * wall * p, 90 * p))
    f.write("Elapsed (wall clock) time (h:mm:ss or m:ss): %d:%05.2f\n" % (wall // 60, wall % 60))
    f.write("Maximum resident set size (kbytes): %d\n" % (1000000 + 100000 * p))
    if rc < 0:
        f.write("Command terminated by signal %d\n" % -rc)
    f.write("Exit status: %d\n" % (0 if rc < 0 else rc))
sys.exit(0 if rc < 0 else rc)
'''
FAKE_DIANN = c.FAKE_HEAD + r'''
out, tmp = arg("--out"), arg("--temp")
d = os.path.dirname(out)
assert os.path.isdir(tmp) and os.path.isfile(arg("--fasta")) and arg("--f").endswith(".d")
open(os.path.join(tmp, "x.quant"), "w").write("q")
open(arg("--out-lib"), "w").write("predicted library")
if hit("FAKE_DIANN_DRIFT", d):
    open(sys.argv[0], "a").write("\n# drift\n")
q = "0.5" if hit("FAKE_DIANN_ZERO", d) else "0.001"
if not hit("FAKE_DIANN_NOREPORT", d):
    rows = [("A2", "PEPA", "P1", q, "0.001", "0.001", "0"), ("A3", "PEPA", "P1", q, "0.002", "0.001", "0"),
            ("B2", "PEPB", "P2", q, "0.001", "0.05", "0"), ("C2", "PEPC", "P3", "0.02", "0.001", "0.001", "0"),
            ("D2", "PEPD", "P4", q, "0.5", "0.001", "0"), ("X2", "XEPA", "rev_P1", q, "0.001", "0.001", "1"),
            ("E2", "PEPE", "P5", q, "0.001", "0.001", "0")]
    with open(out[:-len(".parquet")] + ".tsv", "w") as f:
        f.write("Precursor.Id\tStripped.Sequence\tProtein.Group\tQ.Value\tLib.Q.Value\tPG.Q.Value\tDecoy\n")
        f.write("".join("\t".join(r) + "\n" for r in rows))
    with open(os.path.join(d, "report.stats.tsv"), "w") as f:
        f.write("File.Name\tPrecursors.Identified\tProteins.Identified\nx\t4\t2\n")
print("Finished")
'''
FAKE_CMD = c.FAKE_HEAD + r'''
inp, out = arg("--in"), arg("--out")
assert os.path.exists(inp), inp
time.sleep(float(os.environ.get("FAKE_CMD_SLEEP", "0")))
mzml(out, 23)
print("Wrote %d spectra" % (22 if hit("FAKE_CMD_MISCOUNT", out) else 23))
'''


def selftest(args=None) -> int:
    C = c.Cases(echo=lambda r: print("%-4s %-6s %-58s %s" % r))
    saved = {k: getattr(c, k) for k in ("TIME", "POLL_S", "LOCK_RETRY_S", "MON_S", "load1", "mem_available_kb",
                                        "proc_snapshot", "remove_tree", "busy")}
    env_saved = dict(os.environ)
    w = Path(tempfile.mkdtemp(prefix="baseline-selftest-"))
    try:
        c._world(w)                                    # corpus fakes: arms, java/diaTracer/MSFragger, Sage, raws A..H
        c._exe(w / "bin" / "btime", FAKE_BTIME)
        c._exe(w / "opt" / "diann" / "diann-linux", FAKE_DIANN)
        (w / "opt" / "diann" / "libtimsdata.so").write_bytes(b"so")
        c._exe(w / "opt" / "umpire" / "umpire", FAKE_CMD)

        def snap():
            t, f = time.monotonic(), float(os.environ.get("FAKE_FOREIGN_CORES", "0"))
            return {"t": t, "busy": int((4 + f) * c.CLK_TCK * t), "ours": int(4 * c.CLK_TCK * t),
                    "memavail_kb": 900, "memtotal_kb": 1000}
        for k, v in dict(TIME=str(w / "bin" / "btime"), POLL_S=0.01, LOCK_RETRY_S=0.3, MON_S=0.02, load1=lambda: 0.5,
                         mem_available_kb=lambda *a: 1000, proc_snapshot=snap,
                         busy=lambda pats: []).items():      # the host's own processes must not flag the selftest
            setattr(c, k, v)
        os.environ.update(PATH=str(w / "bin") + os.pathsep + os.environ["PATH"], FAKE_ENVDUMP=str(w / "envdump.txt"),
                          FAKE_MSF_TIMES=str(w / "msf_times.log"), FAKE_NEIGHBOUR=str(w / "neighbour.mzML"),
                          OMP_NUM_THREADS="3", MALLOC_ARENA_MAX="2", DIASPEXTRACT_PROBE="1", LD_LIBRARY_PATH="/nonexistent")
        spx, raws = w / "ceph" / "spx", w / "ceph" / "raw"

        # ---- E(p) and S(p): a known answer, with repeats (median) and spread
        sc = {x["p"]: x for x in scaling({8: [800.0, 820.0, 780.0], 16: [420.0], 32: [250.0, 250.0]}, 8, 16)}
        C.check("G-B06", "S/E known answer: S(16)=800/420, E(16)=800*8/(420*16), E(32)=0.8, spread(8)=40/800",
                sc[16]["speedup"] == round(800 / 420, 4) and sc[16]["efficiency"] == round(800 * 8 / (420 * 16), 4)
                and sc[32]["speedup"] == 3.2 and sc[32]["efficiency"] == 0.8 and sc[8]["efficiency"] == 1.0
                and sc[8]["spread"] == 0.05 and sc[16]["spread"] is None, sc)
        C.check("G-B06", "SMT: 16 physical cores -> p=32 is SMT, E_phys(32)=800*8/(250*16)=1.6, E_phys(16)=E(16)",
                sc[32]["smt"] and not sc[16]["smt"] and sc[32]["efficiency_physical"] == 1.6
                and sc[16]["efficiency_physical"] == sc[16]["efficiency"], sc[32])
        C.check("G-B06", "no T(p0): S and E are None, never rebased on another p",
                all(x["speedup"] is None and x["efficiency"] is None for x in scaling({16: [1.0], 32: [0.6]}, 8)))

        # ---- G-B01 plan / registry
        reg = {"samples": {sid: {"raw": str(raws / ("run_%s.d" % sid)), "scheme": "test", "acq_min": 31.0,
                                 "database": "human", "label": sid, "pin": c.fingerprint(raws / ("run_%s.d" % sid))}
                           for sid in "ABCDEFGH"}}
        mz = w / "ceph" / "orbi.mzML"
        mz.write_text('<mzML><run><spectrumList count="5"></spectrumList></run></mzML>\n')
        reg["samples"]["O"] = {"raw": str(mz), "scheme": "orbi", "pin": {"bytes": mz.stat().st_size, "sha256": c.sha256(mz)}}
        cells = {"spx": {"kind": "diaspextract", "env": str(spx / "arm" / "env.sh"), "search_at": 2},
                 "diatracer": {"kind": "diatracer", "dir": str(spx / "diatracer"), "jar": "diaTracer-2.2.1.jar", "search_at": 2},
                 "diann": {"kind": "diann", "bin": str(w / "opt" / "diann" / "diann-linux"), "search_at": 2},
                 "umpire": {"kind": "cmd", "exe": str(w / "opt" / "umpire" / "umpire"), "input": "d",
                            "cmd": "{exe} --in {in} --out {out} --threads {threads}", "out": "pseudo.mzML",
                            "count": r"Wrote (\d+) spectra", "search_at": 2}}
        plan = {"cluster": {"host": "binac2j", "partition": "compute", "walltime": "12:00:00", "python": sys.executable,
                            "job_unit": "sample", "cpus": 128, "sbatch_args": ["--constraint=eth"]},
                "results": str(w / "pfs" / "results" / "bt"), "raw_map": {str(raws) + "/": str(raws) + "/"},
                "threads": [1, 2], "repeats": 2,
                "n_samples": 1, "search_db_sha256": {"sage_fasta": c.sha256(w / "bench" / "human.fasta"),
                                                     "msfragger_db": c.sha256(w / "bench" / "human_decoy.fasta")},
                "tools": {"sage": str(spx / "tools" / "sage" / "sage"), "sage_config": str(spx / "tools" / "sage_deiso.json"),
                          "msfragger_jar": str(spx / "tools" / "MSFragger-4.4.1.jar"),
                          "msfragger_params": str(spx / "tools" / "msfragger.params"),
                          "patch": str(spx / "tools" / "patch_diatracer_precursor.py"),
                          "fix": str(spx / "tools" / "fix_mzml_cvparams.py")},
                "cells": cells, "samples": ["A"]}

        def mut(f):
            p = json.loads(json.dumps(plan))
            f(p)
            return lambda: validate_plan("bt", p, reg)
        C.ok("G-B01", "valid plan", lambda: validate_plan("bt", plan, reg))
        for name, f, m in (
                ("plan key typo", lambda p: p.update(repeat=1), "unknown keys"),
                ("thread axis not ascending", lambda p: p.update(threads=[16, 8]), "ascending"),
                ("thread axis with a zero", lambda p: p.update(threads=[0, 8]), "ascending"),
                ("search_at not on the axis", lambda p: p["cells"]["spx"].update(search_at=3), "search_at"),
                ("cell axis override drops search_at", lambda p: p["cells"]["diann"].update(threads=[1]), "search_at"),
                ("repeats 0", lambda p: p.update(repeats=0), "repeats"),
                ("unknown cell kind", lambda p: p["cells"]["spx"].update(kind="spectronaut"), "kind"),
                ("cell key typo", lambda p: p["cells"]["diann"].update(bins="/x"), "allows"),
                ("reserved cell name", lambda p: p["cells"].update(dt=p["cells"].pop("diatracer")), "cell name"),
                ("two diatracer cells", lambda p: p["cells"].update(dt2=dict(p["cells"]["diatracer"])), "at most one"),
                ("cmd template without {threads}", lambda p: p["cells"]["umpire"].update(cmd="x {in} {out}"), "{threads}"),
                ("cmd template without {out} anywhere", lambda p: p["cells"]["umpire"].update(cmd="x {in} {threads}"), "{out}"),
                ("cmd out not an mzML name", lambda p: p["cells"]["umpire"].update(out="../x.mzML"), "out must"),
                ("cmd count without a group", lambda p: p["cells"]["umpire"].update(count="Wrote"), "one group"),
                ("diann args set --threads", lambda p: p["cells"]["diann"].update(args=["--threads", "4"]), "args"),
                ("diaspextract env not env.sh", lambda p: p["cells"]["spx"].update(env="/x/arm"), "env.sh"),
                ("relative tool path", lambda p: p["cells"]["diann"].update(bin="diann-linux"), "absolute"),
                ("unknown sample", lambda p: p["samples"].append("ZZ"), "not in samples.yaml"),
                ("sample listed twice", lambda p: (p["samples"].append("A"), p.update(n_samples=2)), "twice"),
                ("raw under no raw_map prefix", lambda p: p.update(raw_map={"/pfs/x/": "/pfs/y/"}), "raw_map"),
                ("cluster key missing", lambda p: p["cluster"].pop("python"), "cluster needs"),
                ("cluster job_unit typo", lambda p: p["cluster"].update(job_unit="node"), "job_unit"),
                ("walltime not H:MM:SS", lambda p: p["cluster"].update(walltime="12h"), "walltime"),
                ("sbatch_args set --mem", lambda p: p["cluster"].update(sbatch_args=["--mem=10G"]), "set by the harness"),
                ("results relative", lambda p: p.update(results="results/bt"), "absolute"),
                ("n_samples mismatch", lambda p: p.update(n_samples=2), "n_samples"),
                ("mzML sample no cell reads", lambda p: (p["samples"].append("O"), p.update(n_samples=2), p.pop("raw_map")), "no cell"),
                ("engines both spelled out of order", lambda p: p.update(engines=["msfragger", "sage"]), "engines"),
                ("wall cap 0", lambda p: p["cells"]["umpire"].update(wall_cap_h=0), "wall_cap_h")):
            C.abort("G-B01", name, mut(f), m)
        C.abort("G-B01", "two samples share one raw path", lambda: validate_plan("bt", dict(plan, n_samples=2, samples=["A", "B"]),
                {"samples": dict(reg["samples"], B=dict(reg["samples"]["A"]))}), "share one raw")
        q0 = dict(resolve("bt", plan, reg), root="/tmp/x", jnatmp="/tmp/x")
        C.check("G-B01", "unit order: rep 0 ascending, rep 1 descending, cell order flips per step",
                [(n, p, r) for n, p, r in units(q0, q0["samples"][0])][:5] ==
                [("spx", 1, 0), ("diatracer", 1, 0), ("diann", 1, 0), ("umpire", 1, 0), ("umpire", 2, 0)]
                and [p for _, p, r in units(q0, q0["samples"][0]) if r == 1] == [2] * 4 + [1] * 4, units(q0, q0["samples"][0])[:5])
        lines = []
        C.ok("G-B01", "dry-run prints every command", lambda: dry_run(q0, lines.append))
        C.check("G-B01", "dry-run: 16 runs + 3 Sage + 3 MSFragger lines, diaTracer patched",
                sum(bool(re.match(r"\[\d+\] ", x)) for x in lines) == 16
                and sum(x.startswith("[search]") and "msfragger" in x for x in lines) == 3
                and any("patch_diatracer_precursor" in x for x in lines), len(lines))

        def q_for(rootname, **kw):
            q = resolve("bt", plan, reg)
            q.update(root=str(w / "scratch" / rootname), lock=str(w / "scratch" / ".lock"), jnatmp=str(w / "scratch" / "jnatmp"),
                     load_max=1e9)
            for k, v in kw.items():
                if k == "cells":
                    q["cells"] = v
                else:
                    q[k] = v
            return q

        # ---- the full queue: 4 cells x 2 p x 2 repeats, searches on 3 outputs
        # the job path: $TMPDIR root, records straight to <results>/records, logs copied out
        (w / "tmpjob").mkdir()
        os.environ["TMPDIR"] = str(w / "tmpjob")
        (name0, q), = jobs(q0)
        q = dict(q, load_max=1e9)
        spec = {"mode": "baseline", "results": plan["results"], "path": [], "q": q}
        C.check("G-B01", "full job exits 0", job_main(spec) == 0 and name0 == "bl-bt-A")
        root = w / "tmpjob" / ("job-%s" % q["nonce"])
        q = dict(q, root=str(root), lock=str(w / "tmpjob" / ".queue.lock"), jnatmp=str(w / "tmpjob" / "jnatmp"))
        res = Path(plan["results"])
        recs = node_records({"root": plan["results"]})
        C.check("G-V14", "job: records on the results side, logs copied, no mzML/stage/tools copied out",
                (res / "runs" / "runs" / "A").is_dir() and list((res / "runs").rglob("time.log"))
                and not list(res.rglob("*.mzML")) and not list(res.rglob("stage")) and not list(res.rglob("tools"))
                and not (root / "records").exists(), len(recs))
        runs = [r for r in recs if r["kind"] == "baseline_run"]
        C.check("G-B01", "16 ok run records, 6 ok searches", sum(r["status"] == "ok" for r in runs) == 16
                and sum(r["kind"] == "search" and r["status"] == "ok" for r in recs) == 6,
                [(r.get("run_id"), r.get("guard"), r.get("message")) for r in recs if r["status"] != "ok"])
        dump = Path(os.environ["FAKE_ENVDUMP"]).read_text().split()
        C.check("G-B01", "tools ran without OMP_/MALLOC_/DIASPEXTRACT_ and inherited LD_LIBRARY_PATH",
                dump and not {"OMP_NUM_THREADS", "MALLOC_ARENA_MAX", "DIASPEXTRACT_PROBE", "LD_LIBRARY_PATH"} & set(dump))
        C.check("G-V14", "stage removed, no mzML left after both searches",
                not list((root / "stage").glob("*")) and not list((root / "runs").rglob("*.mzML")))
        dn = [r for r in runs if r["cell"] == "diann"]
        C.check("G-B04", "DIA-NN rule: 4 precursors, 3 peptides, 2 protein groups; library and temp deleted",
                all(r["diann"]["precursors"] == 4 and r["diann"]["peptides"] == 3 and r["diann"]["protein_groups"] == 2 for r in dn)
                and not list((root / "runs").rglob("lib.parquet")) and not list((root / "runs").rglob("tmp")), dn[0].get("diann"))
        C.check("G-B06", "cpu_util = (user+sys)/(wall*p) = 0.9", all(r["cpu_util"] == 0.9 for r in runs))
        obj, md, complete = render("bt", plan, reg, recs)
        rows = {x["cell"]: x for x in obj["rows"]}
        C.check("G-B06", "end to end: T(1)=900 s, T(2)=500 s -> S(2)=1.8, E(2)=0.9 for every cell",
                complete and all(rows[n]["scaling"][1]["speedup"] == 1.8 and rows[n]["scaling"][1]["efficiency"] == 0.9
                                 and rows[n]["scaling"][0]["n"] == 2 for n in cells), obj["missing"][:3])
        C.check("G-V10", "Sage + MSFragger peptides on the search_at output of every mzML cell",
                all(rows[n]["ids"].get("sage_peptides", 0) > 0 and rows[n]["ids"].get("msfragger_peptides", 0) > 0
                    for n in ("spx", "diatracer", "umpire")) and rows["spx"]["ids"]["spectra"] == 42, rows["spx"]["ids"])
        C.check("G-B06", "markdown has the scaling and identification tables", "| A | spx | 2 | - | 8:20 |" in md
                and "## Identifications" in md and "## Per tool" in md, [x for x in md.splitlines() if x.startswith("| A | spx | 2")])
        pats = busy_patterns({n: cell_tool(q, n) for n in q["cells"]})
        C.check("G-B01", "busy patterns: corpus fixed + bracketed extractor + DIA-NN + cmd exe, none self-matching",
                pats[:len(c.BUSY_FIXED)] == c.BUSY_FIXED and "fakesp[x] -in" in pats and "diann-linu[x]" in pats
                and "umpir[e]" in pats, pats)
        before = {r["run_id"] for r in runs}
        C.check("G-B01", "resume: a second job re-runs nothing", job_main(dict(spec, q=dict(spec["q"], nonce="n2"))) == 0
                and {r["run_id"] for r in node_records({"root": plan["results"]}) if r["kind"] == "baseline_run"} == before)
        # a plan edit after the runs (here the umpire cell's count regex): the table must not show the old numbers as
        # this plan's, and a resubmitted job re-runs that cell's units, and only those
        count_b = r"Wrote\s+(\d+) spectra"
        plan_b = json.loads(json.dumps(plan))
        plan_b["cells"]["umpire"]["count"] = count_b
        obj_b, _, complete_b = render("bt", plan_b, reg, node_records({"root": plan["results"]}))
        C.check("G-B06", "render: records of a changed cell definition are stale, not tabled",
                not complete_b and sum("umpire" in m and "another cell definition" in m for m in obj_b["missing"]) == 4
                and not any("spx" in m for m in obj_b["missing"]), obj_b["missing"][:5])
        def rerun(nonce, count):
            qb = dict(spec["q"], nonce=nonce, cells=dict(spec["q"]["cells"], umpire=dict(spec["q"]["cells"]["umpire"], count=count)))
            rc = job_main(dict(spec, q=qb))
            now = {r["run_id"]: r["cell"] for r in node_records({"root": plan["results"]}) if r["kind"] == "baseline_run"}
            return rc, now
        rc_b, now_b = rerun("n3", count_b)
        C.check("G-B01", "resume after a cell edit: that cell's 4 units re-run, the others reused",
                rc_b == 0 and sorted(set(now_b) - before) == sorted(k for k, v in now_b.items() if v == "umpire")
                and len(set(now_b) - before) == 4, sorted(set(now_b) - before))
        rc_c, now_c = rerun("n4", spec["q"]["cells"]["umpire"]["count"])   # and back: the records match the plan again
        C.check("G-B01", "resume after reverting the edit re-runs the 4 units again",
                rc_c == 0 and len(set(now_c) - set(now_b)) == 4 and render("bt", plan, reg, node_records({"root": plan["results"]}))[2])
        cj = jobs(dict(q0, cluster=dict(q0["cluster"], job_unit="cell")))
        C.check("G-B01", "job_unit cell: one job per (sample, cell, threads)", len(cj) == 8
                and cj[0][0] == "bl-bt-A-spx-p1" and cj[0][1]["only"] == {"cell": "spx", "threads": 1}
                and list(cj[0][1]["cells"]) == ["spx"], [x[0] for x in cj])
        (w / "tmpjob2").mkdir()
        os.environ["TMPDIR"] = str(w / "tmpjob2")
        uj = next(jq for nm, jq in cj if nm == "bl-bt-A-umpire-p2")
        res2 = str(w / "pfs" / "results" / "bt_cell")
        C.check("G-B01", "a cell job runs its own units and the searches of its search_at unit only",
                job_main({"mode": "baseline", "results": res2, "path": [], "q": dict(uj, load_max=1e9)}) == 0
                and sorted((r["kind"], r.get("threads"), r.get("rep"), r.get("engine")) for r in node_records({"root": res2}))
                == [("baseline_run", 2, 0, None), ("baseline_run", 2, 1, None), ("baseline_stage", None, None, None),
                    ("search", None, None, "msfragger"), ("search", None, None, "sage")])
        sb = sbatch_script("bl-bt-A", plan["cluster"], "/pfs/r", "/pfs/r/harness/x", "/pfs/r/jobs/bl-bt-A.json")
        C.check("G-B01", "sbatch: exclusive whole node, all memory, partition, walltime, cpus, extra args, one exec",
                all(x in sb.splitlines() for x in ("#SBATCH --exclusive", "#SBATCH --nodes=1", "#SBATCH --mem=0",
                                                   "#SBATCH --partition=compute", "#SBATCH --time=12:00:00",
                                                   "#SBATCH --cpus-per-task=128", "#SBATCH --constraint=eth",
                                                   "#SBATCH --output=/pfs/r/jobs/%x-%j.out"))
                and sb.splitlines()[-1].startswith("exec ") and "job --spec /pfs/r/jobs/bl-bt-A.json" in sb, sb)
        os.environ["TMPDIR"] = "/pfs/10/work/x"
        C.abort("G-B07", "TMPDIR on Lustre, not node-local", lambda: job_main(spec), "not node-local")
        os.environ.pop("TMPDIR")
        C.abort("G-B07", "TMPDIR unset", lambda: job_main(spec), "unset")
        os.environ["TMPDIR"] = str(w / "tmpjob")
        C.abort("G-B07", "results not absolute", lambda: job_main(dict(spec, results="rel/results")), "absolute")
        C.abort("G-B02", "java 1.8 (BinAC2's system java) refused", lambda: check_java({"major": 8, "version": "1.8.0_504"}), "older than")
        # corpus pairing as one job: corpus.py's own queue code, records under <results>/records
        (w / "tmpjob3").mkdir()
        os.environ["TMPDIR"] = str(w / "tmpjob3")
        cq = c._queue(w, "B", root="unused", load_max=1e9)
        res3 = str(w / "pfs" / "results" / "corpus-x")
        rc3 = job_main({"mode": "corpus", "results": res3, "path": [], "q": dict(cq, nonce="cp1")})
        kinds = sorted((r["kind"], r.get("tool"), r.get("engine"), r["status"]) for r in node_records({"root": res3}))
        C.check("G-B01", "corpus job: the pair and four searches ok, via corpus.node_run", rc3 == 0 and kinds ==
                [("pair", None, None, "ok")] + [("search", t, e, "ok") for t in ("dt", "spx") for e in ("msfragger", "sage")], kinds)
        # corpus-table: the records hold the raw after raw_map, samples.yaml the raw before it (G-V13 raw check)
        rec3 = node_records({"root": res3})
        cpl3, creg3 = c._reg(cq)
        rawB = creg3["samples"]["B"]["raw"]
        rm3 = {"/samples/raw/": str(Path(rawB).parent) + "/"}
        yreg = lambda raw: dict(creg3, samples=dict(creg3["samples"], B=dict(creg3["samples"]["B"], raw=raw)))
        C.ok("G-V13", "corpus-table: samples.yaml raw mapped by raw_map matches the records",
             lambda: c.render_table("x", cpl3, mapped_registry(yreg("/samples/raw/" + Path(rawB).name), rm3), rec3))
        C.abort("G-V13", "corpus-table: unmapped samples.yaml raw is refused (the bug)",
                lambda: c.render_table("x", cpl3, yreg("/samples/raw/" + Path(rawB).name), rec3), "raw path")
        C.abort("G-V13", "corpus-table: a different raw, mapped, still aborts",
                lambda: c.render_table("x", cpl3, mapped_registry(yreg("/samples/raw/run_C.d"), rm3), rec3), "raw path")
        C.abort("G-V13", "corpus-table: a raw under no raw_map prefix still aborts",
                lambda: c.render_table("x", cpl3, mapped_registry(yreg("/elsewhere/" + Path(rawB).name), rm3), rec3), "raw path")

        # ---- G-B06 table refusals and the incomplete table
        def tamper(f):
            rr = json.loads(json.dumps(recs))
            f(rr)
            return lambda: render("bt", plan, reg, rr)
        first = lambda rr, cell: next(r for r in rr if r.get("kind") == "baseline_run" and r["cell"] == cell)
        C.abort("G-B06", "one cell, two tool builds", tamper(lambda rr: first(rr, "spx")["tool"].update(sha256="ff" * 32)), "builds")
        C.abort("G-B06", "mixed harness code", tamper(lambda rr: first(rr, "diann").update(harness_sha256="x")), "code")
        C.abort("G-B06", "one sample on two CPU models", tamper(lambda rr: first(rr, "umpire").update(cpu_model="other")), "one node type")
        C.abort("G-B06", "ok record with wall 0", tamper(lambda rr: first(rr, "umpire").update(wall_s=0)), "<= 0")
        rr = [r for r in recs if not (r.get("kind") == "baseline_run" and r["cell"] == "spx" and r["threads"] == 1 and r["rep"] == 1)]
        o2, _, comp2 = render("bt", plan, reg, rr)
        C.check("G-B06", "a missing run makes the table incomplete (exit 3), never a silent n=1", not comp2
                and any("spx p=1 r=1" in m for m in o2["missing"]), o2["missing"])

        # ---- cell-level failures (the queue goes on) and queue-level aborts
        def one(rootname, cell, pin=None, env=None, **kw):
            q = q_for(rootname, cells={cell: q0["cells"][cell]}, repeats=1, **kw)
            q["samples"] = [dict(q0["samples"][0], **({"pin": pin} if pin else {}))]
            os.environ.update(env or {})
            try:
                rc = node_run(q)
            finally:
                for k in env or {}:
                    os.environ.pop(k, None)
            return rc, {(r.get("cell") or r.get("tool") or r["kind"], r.get("threads", r.get("engine"))): r
                       for r in node_records({"root": q["root"]})}

        def failed_with(guard, name, res, key, match):
            rc, rs = res
            r = rs.get(key, {})
            C.check(guard, name, rc == 1 and r.get("status") == "failed" and r.get("guard") == guard
                    and match.lower() in r.get("message", "").lower(), "rc %s %s %s" % (rc, r.get("guard"), r.get("message")))
        failed_with("G-B04", "DIA-NN: 0 precursors at 1% q", one("zero", "diann", env={"FAKE_DIANN_ZERO": "/diann-p1"}),
                    ("diann", 1), "0 precursors")
        failed_with("G-B04", "DIA-NN: no report", one("norep", "diann", env={"FAKE_DIANN_NOREPORT": "/diann-p2"}),
                    ("diann", 2), "missing or stale")
        failed_with("G-B04", "cmd count line != spectrumList count", one("cmdcount", "umpire", env={"FAKE_CMD_MISCOUNT": "umpire-p1"}),
                    ("umpire", 1), "count line")
        failed_with("G-V08", "diaspextract count line != spectrumList count",
                    one("spxcount", "spx", env={"FAKE_SPX_MISCOUNT": "/A.d"}), ("spx", 1), "log count")
        capped = dict(q0["cells"]["umpire"], wall_cap_h=0.0001)
        os.environ["FAKE_CMD_SLEEP"] = "3"
        qc = q_for("cap", cells={"umpire": capped}, repeats=1)
        qc["samples"] = q0["samples"][:1]
        rc = node_run(qc)
        os.environ.pop("FAKE_CMD_SLEEP")
        rs = {(r.get("cell"), r.get("threads")): r for r in node_records({"root": qc["root"]})}
        C.check("G-B05", "wall cap passed: session killed, run failed", rc == 1 and rs[("umpire", 1)].get("guard") == "G-B05",
                rs[("umpire", 1)].get("message"))
        rc, rs = one("pin", "umpire", pin=dict(q0["samples"][0]["pin"], tdf_bytes=1))
        C.check("G-V02", "raw differs from its pin: stage record failed, no run", rc == 1
                and rs[("baseline_stage", None)]["guard"] == "G-V02" and not any(k[0] == "umpire" for k in rs), rs.keys())
        rc, rs = one("sagezero", "umpire", env={"FAKE_SAGE_ZERO": "umpire-p2"})
        C.check("G-V10", "Sage 0 peptides: that search failed, the runs and MSFragger ok", rc == 1
                and rs[("umpire", "sage")].get("guard") == "G-V10" and rs[("umpire", "msfragger")]["status"] == "ok"
                and rs[("umpire", 2)]["status"] == "ok", rs.get(("umpire", "sage"), {}).get("message"))
        os.environ["FAKE_FOREIGN_CORES"] = "100"
        rc, rs = one("contended", "umpire", load_max=12)
        os.environ.pop("FAKE_FOREIGN_CORES")
        C.check("G-V06", "foreign CPU above the gate threshold during a run: flagged, not failed", rc == 0
                and rs[("umpire", 1)]["contended"] and rs[("umpire", 1)]["during"]["contended"], rs[("umpire", 1)].get("during"))
        C.check("G-B01", "raw_map: the longest matching prefix wins",
                map_raw("/c/raw/100SPD/x.d", {"/c/raw/": "/p/a/", "/c/raw/100SPD/": "/p/b/"}) == "/p/b/x.d"
                and map_raw("/c/raw/y.d", {"/c/raw/": "/p/a/", "/c/raw/100SPD/": "/p/b/"}) == "/p/a/y.d"
                and map_raw("/d/z.d", {"/c/": "/p/"}) is None)
        wide = w / "msf_wide.params"
        wide.write_text((spx / "tools" / "msfragger.params").read_text() + "precursor_mass_lower = -100\n")
        adapter = dict(q0["cells"]["umpire"], cmd="{exe} --in {dir}/in.copy --out {dir}/raw.mzML --threads {threads}",
                       pre=["/bin/cp -R {in} {dir}/in.copy"], post=["/bin/cp {dir}/raw.mzML {out}"], count=r"Wrote (\d+) spectra",
                       engines=["msfragger"], msfragger_params=str(wide))
        qa = q_for("adapt", cells={"ms2pep": adapter}, repeats=1)
        rs = {(r.get("cell") or r.get("tool") or r["kind"], r.get("threads", r.get("engine"))): r
              for r in [None] if node_run(qa) is not None for r in node_records({"root": qa["root"]})}
        ra = rs.get(("ms2pep", 2), {})
        C.check("G-B04", "cmd pre/post run untimed and are recorded; per-cell engines and MSFragger params",
                ra.get("status") == "ok" and len(ra.get("pre", [])) == 1 and len(ra.get("post", [])) == 1
                and ("ms2pep", "msfragger") in rs and ("ms2pep", "sage") not in rs
                and rs[("ms2pep", "msfragger")]["tools_sha256"]["msfragger_params"] == c.sha256(wide)
                and rs[("ms2pep", "msfragger")]["status"] == "ok", sorted(map(str, rs)))
        badpost = dict(adapter, post=["/bin/cp {dir}/nonexistent {out}"])
        qb = q_for("badpost", cells={"ms2pep": badpost}, repeats=1)
        node_run(qb)
        rb = {(r.get("cell"), r.get("threads")): r for r in node_records({"root": qb["root"]})}
        C.check("G-B04", "a failing post step fails the run", rb[("ms2pep", 1)].get("guard") == "G-B04"
                and "post step" in rb[("ms2pep", 1)].get("message", ""), rb[("ms2pep", 1)].get("message"))
        other_db = w / "msf_otherdb.params"
        other_db.write_text("database_name = %s\n" % (w / "bench" / "human.fasta"))
        C.abort("G-V12", "a cell's MSFragger params naming another database",
                lambda: node_run(q_for("otherdb", cells={"ms2pep": dict(adapter, msfragger_params=str(other_db))}, repeats=1)),
                "differs from the plan pin")
        C.abort("G-B01", "cell engines outside the plan's", mut(lambda p: (p.update(engines=["sage"]), p["cells"]["spx"].update(engines=["msfragger"]))), "engines")
        drift = w / "opt" / "diann2"
        shutil.copytree(w / "opt" / "diann", drift)
        qd = q_for("drift", cells={"diann": dict(q0["cells"]["diann"], bin=str(drift / "diann-linux"))}, repeats=1)
        qd["samples"] = q0["samples"][:1]
        os.environ["FAKE_DIANN_DRIFT"] = "/diann-p1"
        C.abort("G-B03", "a tool file changes during a run", lambda: node_run(qd), "changed during")
        os.environ.pop("FAKE_DIANN_DRIFT")
        C.abort("G-B02", "DIA-NN binary missing", lambda: node_run(q_for("nobin", cells={"diann": dict(q0["cells"]["diann"], bin="/nonexistent/diann")})), "missing")
        (w / "badenv.sh").write_text("export OMP_NUM_THREADS=4\n")
        C.abort("G-B02", "cmd env.sh exports OMP_NUM_THREADS", lambda: node_run(q_for("badenv", cells={"umpire": dict(q0["cells"]["umpire"], env=str(w / "badenv.sh"))})), "exports")
        C.abort("G-V03", "diaspextract arm env.sh exports OMP_NUM_THREADS",
                lambda: node_run(q_for("omp", cells={"spx": dict(q0["cells"]["spx"], env=str(spx / "arm_omp" / "env.sh"))})), "exports")
        C.abort("G-B01", "thread count above the job's CPUs", lambda: node_run(q_for("cores", cells={"umpire": dict(q0["cells"]["umpire"], threads=[10 ** 6], search_at=10 ** 6)})), "exceed")
        C.abort("G-B01", "corpus.py differs from the resolved one", lambda: node_run(q_for("corpus", corpus_sha256="00" * 32)), "corpus.py")
        C.abort("G-V12", "search database differs from the plan pin", lambda: node_run(q_for("db", search_db_sha256=dict(q0["search_db_sha256"], sage_fasta="00" * 32))), "plan pin")
        c.remove_tree = lambda p: None
        try:
            C.abort("G-V14", "staged copy not deleted", lambda: node_run(q_for("keep", cells={"umpire": q0["cells"]["umpire"]}, repeats=1)), "not deleted")
        finally:
            c.remove_tree = saved["remove_tree"]
    finally:
        for k, v in saved.items():
            setattr(c, k, v)
        os.environ.clear()
        os.environ.update(env_saved)
        c.remove_tree(w)
    fails = [r for r in C.results if r[0] != "PASS"]
    never = sorted(SELFTEST_GUARDS - C.fired)
    print("SELFTEST %s: %d checks, %d failed, guards never fired: %s" % (
        "OK" if not fails and not never else "FAILED", len(C.results), len(fails), never or "none"))
    return 0 if not fails and not never else 1


# ------------------------------------------------------------------------------- main
def main() -> int:
    if len(sys.argv) > 1 and (sys.argv[1].startswith("node-") or sys.argv[1] == "job"):
        return node_main(sys.argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("selftest", "dry-run", "preflight", "submit", "status", "fetch", "table", "submit-corpus", "corpus-table"):
        p = sub.add_parser(name)
        if name == "selftest":
            continue
        p.add_argument("--plan", default=DEFAULT_PLAN)
        p.add_argument("--registry", default=str(REG))
        if name in ("dry-run", "submit", "submit-corpus"):
            p.add_argument("--sample")
        if name in ("dry-run", "submit"):
            p.add_argument("--cell")
        if name in ("submit-corpus", "corpus-table", "fetch"):
            p.add_argument("--corpus-plan", required=name != "fetch")
        if name == "submit-corpus":
            p.add_argument("--dry", action="store_true", help="print the sbatch scripts, submit nothing")
        if name == "fetch":
            p.add_argument("--dest", required=True)
        if name in ("table", "corpus-table"):
            p.add_argument("--source", default="remote", help="remote (read on the login node) or a local dir holding records/")
            p.add_argument("--out", help="table: OUT.json + OUT.md; corpus-table: OUT")
    a = ap.parse_args()
    fn = {"selftest": selftest, "dry-run": cmd_dry_run, "preflight": cmd_preflight, "submit": cmd_submit,
          "status": cmd_status, "fetch": cmd_fetch, "table": cmd_table, "submit-corpus": cmd_submit_corpus,
          "corpus-table": cmd_corpus_table}[a.cmd]
    try:
        return fn(a)
    except Abort as x:
        print("ABORT %s" % x, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
