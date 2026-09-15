#!/usr/bin/env python3
"""Corpus mode: diaTracer-2.2.1 vs our extractor on every registered file, Sage + MSFragger.

One queue per node. Per sample, on that node, back to back: stage the raw .d into a fresh
node-local directory, pre-warm it, run both extractors under /usr/bin/time -v (order alternating by
queue index), verify both outputs. After every pair of the queue: search each output with Sage and
MSFragger, count peptides, delete the mzML once both engines succeeded. Records are the only source
of truth for `status` and `table`. Usage and the peptide-count rule: harness/CORPUS.md.

    corpus.py selftest                                   # offline, every guard fires at least once
    corpus.py pin      --node data [--plan corpus_v3]    # print registry pins read from the raw .d
    corpus.py dry-run  --node data [--plan corpus_v3]    # print every command per cell, run nothing
    corpus.py launch   --node data [--plan corpus_v3]    # start that node's queue (setsid nohup)
    corpus.py status   [--node data] [--plan corpus_v3] # read records; re-invoke to wait
    corpus.py collect  --node data [--plan corpus_v3]    # copy logs/TSVs/records to ceph
    corpus.py table    [--plan corpus_v3] [--source scratch|ceph]
    corpus.py guardtest --node data [--show]             # selftest plans only: faults injected on the REAL
                                                         # node (real raw, arm, jar, engines); detached
    corpus.py preflight [--node data] [--plan corpus_v3] # G-V15/G-V12 on every queue node before T0
    corpus.py purge    --node data [--plan corpus_v3]    # after the run: delete leftover mzML/mzBIN

Guards ABORT (a queue-level abort stops the queue; a cell-level abort fails that cell, which then
renders as FAILED, never as a number). Each id is triggered by --selftest.

  G-V01 registry/plan: unknown sample, missing field or pin, sample in two queues, bad plan key,
        duplicate YAML key, two samples sharing a raw path or pin, sample count != n_samples
  G-V02 identity: the raw .d (ceph) or its staged copy does not match the registry pin; the raw's
        acquisition length differs from the registry acq_min
  G-V03 arm: env.sh missing/failing, SPX_BIN unset/outside the arm dir, env.sh itself exports a
        probe/allocator/OpenMP/JVM-option variable, provenance missing or its binary_sha256 differs,
        tool label unresolvable, a library unresolved or resolved from a node-local build tree
  G-V04 binary drift: SPX_BIN, the arm's lib/**, its resolved libraries, the diaTracer jar or Bruker
        library, or the JDK changed across an arm
  G-V05 exclusivity: another corpus queue holds the node lock, or our tools already run (launch)
  G-V06 contention: before each pair, 1-min load above 24 (>=200 cores) / 12, or our tools running ->
        wait up to load_wait_min, then run and FLAG the row; during each arm, foreign CPU (60-s mean)
        above the same threshold or MemAvailable below 5% -> FLAG (the only guard that flags)
  G-V07 staging: scratch root on ceph, arm input outside the 0700 stage root, staging copy failed,
        or the ceph neighbour _diatracer.mzML changed during the diaTracer arm
  G-V08 arm result: exit!=0, signal, unparseable time log, output missing/stale/unterminated,
        spectrumList count <=0, or the tool's own count line missing/different
  G-V09 pair: a failed arm stops the pair; the other arm is never (re)run in that attempt
  G-V10 search: patch count != spectra, fix incomplete, Sage without "finished in" or searching less
        than half of the spectra, MSFragger without "TOTAL TIME" or with Scans != spectra, exit!=0,
        result TSV missing/header-only/columns missing, 0 peptides
  G-V11 resume: a record counts only with equal build identity, measurement code, threads, pin,
        verified fresh output and (searches) the same pair_run, tool sha256s and search/score code
  G-V12 search inputs: run-local tool copies differ from an earlier launch, a FASTA differs from the
        plan pin or changed during the run
  G-V13 table: mixed builds/JDK versions/measurement code/search inputs, pair arms on two hosts, ok
        record with count <=0, record pin or raw differs from the registry
  G-V14 retention/collect: staged copy not deleted, collect/purge while the queue runs, destination
        not a corpus_v3* results dir, collected tree not private
  G-V15 node environment: root under /home, jnatmp not writable, MemAvailable or /proc unreadable,
        python < 3.9, TIME not GNU time -v, no java
"""
from __future__ import annotations

import argparse, base64, concurrent.futures, fcntl, hashlib, inspect, json, os, re, shlex, shutil, signal
import socket, sqlite3, statistics, subprocess, sys, tempfile, threading, time, urllib.parse
from pathlib import Path

SELF = Path(globals().get("__file__", "corpus.py")).resolve()   # no __file__ under `python3 -` on a node
HERE, REPO = SELF.parent, SELF.parent.parent
REG = HERE / "samples.yaml"
TIME = "/usr/bin/time"              # GNU time; the selftest points this at a stand-in
POLL_S = 60.0                       # load-gate poll interval
LOCK_RETRY_S = 5.0                  # a `status` probe flocks the node lock for microseconds: retry, then G-V05
MON_S = 10.0                        # contention sampling interval during an arm (G-V06)
MON_WINDOW_S = 60.0                 # foreign CPU judged as a 60-s mean, like the gate's 1-min load
MEM_FLOOR = 0.05                    # MemAvailable below this fraction of MemTotal during an arm flags the row
SAGE_MIN_READ = 0.5                 # Sage must search at least this fraction of the written spectra (G-V10)
CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
# Variables the tools must not inherit (review F4): probes, allocator and OpenMP knobs, JVM options
# (_JAVA_OPTIONS overrides an explicit -Xmx). The caller's LD_LIBRARY_PATH is dropped before env.sh runs.
# The three tool prefixes: DIASPEXTRACT_ is the live one, the other two are the renamed-away prefixes the tool refuses.
STRIP_PREFIX = ("SPEXTRACTOR_", "DIASPEXTRACTOR_", "DIASPEXTRACT_", "MALLOC_", "OMP_", "GOMP_", "KMP_", "TCMALLOC_")
STRIP_EXACT = frozenset({"LD_PRELOAD", "GLIBC_TUNABLES", "_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS"})
INHERIT_DROP = frozenset({"LD_LIBRARY_PATH"})
LIB_ROOTS = ("/ceph/", "/lib/", "/lib64/", "/usr/lib/", "/usr/lib64/")   # where a measured library may resolve
TOOLS = ("dt", "spx")
ENGINES = ("sage", "msfragger")
DT_PARAMS = ["-mC", "0.3", "-dI", "0.01", "-dR", "3", "-rM", "500", "-mF", "1", "-mO", "0.1", "-r", "0"]
SAGE_TELEMETRY = "--disable-telemetry-i-dont-want-to-improve-sage"
PIN_KEYS = ("tdf_bytes", "tdf_bin_bytes", "acq_datetime", "instrument_serial")
SAMPLE_KEYS = ("raw", "scheme", "acq_min", "database", "pin")
PLAN_KEYS = {"arm", "spx_root", "diatracer_dir", "diatracer_jar", "jnatmp", "scratch_root",
             "results_ceph", "report", "threads", "load_wait_min", "tools", "queues",
             "search_db_sha256", "n_samples"}
DB_KEYS = ("sage_fasta", "msfragger_db")
TOOL_KEYS = ("sage", "sage_config", "msfragger_jar", "msfragger_params", "patch", "fix")
# Busy check (memory pgrep-self-match): bracketed, case-correct, matching paths not words. The
# extractor pattern is added from SPX_BIN's basename; "spextracto[r] -in" also matches pre-rename
# builds, e.g. a gate chain of another session.
BUSY_FIXED = [r"diaTracer-2\.2\.[1]\.jar", r"MSFragger-4\.4\.[1]\.jar", r"/sag[e] ", r"spextracto[r] -in"]


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


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def write_json(path: Path, obj) -> None:
    """Atomic: a reader sees the old record or the new one, never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, allow_nan=False))
    os.replace(tmp, path)


def read_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def hostname() -> str:
    return socket.gethostname().split(".")[0]


def load1() -> float:
    return os.getloadavg()[0]


def mem_available_kb(path="/proc/meminfo") -> int:
    try:
        for line in open(path):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    except OSError:
        pass
    die_queue("G-V15", "MemAvailable unreadable from /proc/meminfo")


def ps_top() -> list:
    r = subprocess.run(["ps", "-eo", "pcpu,user,comm", "--sort=-pcpu"], capture_output=True, text=True)
    return r.stdout.splitlines()[:6] if r.returncode == 0 else ["ps failed: " + r.stderr.strip()[:80]]


def hms(sec) -> str:
    sec = int(round(sec))
    return "%d:%02d:%02d" % (sec // 3600, sec // 60 % 60, sec % 60) if sec >= 3600 else "%d:%02d" % (sec // 60, sec % 60)


# ------------------------------------------------------------------------------- result parsing
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


def arm_env(q: dict) -> tuple:
    """The arm's env.sh on top of a caller environment with every allocator/probe/OpenMP/JVM-option variable
    and the inherited LD_LIBRARY_PATH removed: defaults only, glibc malloc (bench.py v1 preloaded tcmalloc;
    critique C7; review F4)."""
    env_sh = Path(q["spx_root"]) / q["arm"] / "env.sh"
    if not env_sh.is_file():
        die_queue("G-V03", "arm env.sh missing: %s" % env_sh)
    removed = sorted(k for k in os.environ if strip_var(k) or k in INHERIT_DROP)
    base = {k: v for k, v in os.environ.items() if not (strip_var(k) or k in INHERIT_DROP)}
    r = subprocess.run(["bash", "-c", 'source "$1" >&2 && env -0', "_", str(env_sh)], env=base, capture_output=True)
    if r.returncode != 0:
        die_queue("G-V03", "sourcing %s failed: %s" % (env_sh, r.stderr.decode(errors="replace")[-300:]))
    env = dict(kv.split("=", 1) for kv in r.stdout.decode(errors="replace").split("\0") if "=" in kv)
    bad = sorted(k for k in env if strip_var(k))
    if bad:
        die_queue("G-V03", "%s itself exports %s: a configured arm, not the defaults" % (env_sh, bad))
    b, arm_dir = env.get("SPX_BIN", ""), os.path.realpath(env_sh.parent)
    if not b or not os.path.isfile(b) or not os.access(b, os.X_OK):
        die_queue("G-V03", "SPX_BIN unset or not an executable file: %r" % b)
    if not os.path.realpath(b).startswith(arm_dir + os.sep):
        die_queue("G-V03", "SPX_BIN %s is outside the arm directory %s (never a dev build tree)" % (b, arm_dir))
    env.update(LC_ALL="C", TMPDIR=q["jnatmp"])
    return env, removed


def ldd_deps(env: dict, arm_dir: str) -> dict:
    """Shared objects SPX_BIN resolves under the arm environment (DT_NEEDED closure) outside the arm directory,
    with sha256 (review F6): $SPX/lib and another project's conda env sit on LD_LIBRARY_PATH, and the binary's
    RUNPATH points into a node-local OpenMS build tree that only LD_LIBRARY_PATH overrides."""
    try:
        r = subprocess.run(["ldd", env["SPX_BIN"]], env=env, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        if sys.platform.startswith("linux"):
            die_queue("G-V15", "ldd not found: the extractor's libraries cannot be pinned")
        return {}
    out = r.stdout + r.stderr
    if "not a dynamic executable" in out:          # a script (guardtest/selftest wrapper arm) resolves nothing
        return {}
    if r.returncode != 0 or "not found" in out:
        die_queue("G-V03", "ldd %s failed or left libraries unresolved: %s" % (env["SPX_BIN"], out.strip()[-400:]))
    found = re.findall(r"=>\s+(/\S+)\s+\(0x", out) + re.findall(r"^\s*(/\S+)\s+\(0x", out, re.M)
    deps = {}
    for p in sorted({os.path.realpath(x) for x in found}):
        if p.startswith(arm_dir + os.sep):
            continue                                    # hashed as the arm's lib/**
        if not p.startswith(LIB_ROOTS):
            die_queue("G-V03", "SPX_BIN resolves %s outside the arm, /ceph and the system library directories "
                               "(a node-local build tree?)" % p)
        deps[p] = sha256(p)
    return deps


_JAVA_VERSIONS = {}


def java_info(env: dict) -> dict:
    """The JDK both diaTracer and MSFragger run on: resolved path, sha256 of java and libjvm, version (G-V04/G-V13)."""
    j = shutil.which("java", path=env.get("PATH"))
    if not j:
        die_queue("G-V15", "no java on PATH")
    real = os.path.realpath(j)
    h = sha256(real)
    if (real, h) not in _JAVA_VERSIONS:
        r = subprocess.run([j, "-version"], env=env, capture_output=True, text=True, timeout=300,
                           stdin=subprocess.DEVNULL)
        m = re.search(r'version "([^"]+)"', r.stderr + r.stdout)
        if r.returncode != 0 or not m:
            die_queue("G-V15", "java -version failed: %s" % (r.stderr + r.stdout).strip()[-200:])
        _JAVA_VERSIONS[(real, h)] = m.group(1)
    v = _JAVA_VERSIONS[(real, h)]
    jvm = Path(real).parent.parent / "lib" / "server" / "libjvm.so"
    return {"path": real, "sha256": h, "libjvm_sha256": sha256(jvm) if jvm.is_file() else None, "version": v,
            "major": int(v.split(".")[1] if v.startswith("1.") else re.split(r"[.+_-]", v)[0])}


def identity(q: dict, env: dict) -> dict:
    arm = os.path.realpath(Path(q["spx_root"]) / q["arm"])
    dt = Path(q["diatracer_dir"])
    tree = lambda d: {str(p.relative_to(d)): sha256(p) for p in sorted(d.rglob("*")) if p.is_file()} if d.is_dir() else {}
    return {"binary": env["SPX_BIN"], "binary_sha256": sha256(env["SPX_BIN"]), "lib_sha256": tree(Path(arm) / "lib"),
            "deps_sha256": ldd_deps(env, arm), "jar": q["diatracer_jar"],
            "jar_sha256": sha256(dt / q["diatracer_jar"]), "bruker_sha256": tree(dt / "ext" / "bruker"),
            "java": java_info(env)}


def build_identity(ident: dict) -> dict:
    """What must match across records (G-V11 resume, G-V13 table): the build and every ceph-resident library it
    loads. Node-local system libraries and the JDK's files may differ between nodes: recorded, and compared
    within a queue only (G-V04). The JDK feature version is compared on its own (java_major)."""
    return {"binary_sha256": ident.get("binary_sha256"), "lib_sha256": ident.get("lib_sha256"),
            "deps_sha256": {p: h for p, h in (ident.get("deps_sha256") or {}).items() if p.startswith("/ceph/")},
            "jar_sha256": ident.get("jar_sha256"), "bruker_sha256": ident.get("bruker_sha256")}


def java_major(ident: dict):
    return (ident.get("java") or {}).get("major")


def check_identity(q: dict, env: dict, ident0: dict, when: str) -> None:
    now = identity(q, env)
    if now != ident0:
        die_queue("G-V04", "binary/lib/jar changed %s (republished under a running queue?)" % when)


def arm_meta(env: dict, ident0: dict) -> dict:
    """Tool label from the binary itself; provenance from the publish step. Nothing hard-coded."""
    prov = Path(env["SPX_BIN"] + ".provenance")
    if not prov.is_file():
        die_queue("G-V03", "provenance missing: %s" % prov)
    lines = prov.read_text().splitlines()
    ps = [x.split("=", 1)[1] for x in lines if x.startswith("binary_sha256=")]
    if not ps or ps[0] != ident0["binary_sha256"]:
        die_queue("G-V03", "provenance binary_sha256 %s != sha256(SPX_BIN) %s" % (ps[:1], ident0["binary_sha256"][:16]))
    r = subprocess.run([env["SPX_BIN"], "--help"], env=env, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=300)
    name = re.search(r"^(\S+) -- ", r.stdout + r.stderr, re.M)
    ver = re.search(r"^Version: (\S+)", r.stdout + r.stderr, re.M)
    if not (name and ver):
        die_queue("G-V03", "tool label unresolvable from %s --help" % env["SPX_BIN"])
    return {"label": "%s %s" % (name.group(1), ver.group(1)), "provenance": lines}


def tool_dest(q: dict) -> dict:
    t, d = q["tools"], Path(q["root"]) / "tools"
    return {"sage": d / "sage" / "sage", **{k: d / Path(t[k]).name for k in TOOL_KEYS if k != "sage"}}


def install_tools(q: dict) -> dict:
    """Run-local copies: a sync_cluster.sh overwriting $SPX/tools mid-run cannot reach them
    (critique S7). A copy that differs from its source aborts: resumed cells would mix versions."""
    dest = tool_dest(q)
    for k, d in dest.items():
        src = Path(q["tools"][k])
        if not src.is_file():
            die_queue("G-V12", "tool missing: %s" % src)
        if d.exists() and sha256(d) != sha256(src):
            die_queue("G-V12", "run-local %s differs from %s: tools changed since an earlier launch" % (d, src))
        if not d.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, d)
    paths = {k: str(v) for k, v in dest.items()}
    paths.update(search_dbs(dest["sage_config"], dest["msfragger_params"]))
    shas = {k: sha256(v) for k, v in paths.items()}
    check_db_pins(q, shas)
    return {"paths": paths, "sha256": shas}


def check_fasta(tools: dict) -> None:
    for k in DB_KEYS:
        if sha256(tools["paths"][k]) != tools["sha256"][k]:
            die_queue("G-V12", "%s changed during the run: %s" % (k, tools["paths"][k]))


def search_dbs(sage_config, msfragger_params) -> dict:
    try:
        fasta = json.loads(Path(sage_config).read_text())["database"]["fasta"]
    except (OSError, ValueError, KeyError, TypeError) as x:
        die_queue("G-V12", "sage config %s has no database.fasta: %s" % (sage_config, x))
    m = re.search(r"^database_name\s*=\s*(\S+)", Path(msfragger_params).read_text(), re.M)
    if not m:
        die_queue("G-V12", "msfragger.params has no database_name")
    return {"sage_fasta": fasta, "msfragger_db": m.group(1)}


def check_db_pins(q: dict, shas: dict) -> None:
    """The databases are node-local files: one byte of difference on one node would otherwise surface only when
    the table refuses mixed search inputs after the whole run (review F5)."""
    for k in DB_KEYS:
        if shas.get(k) != q["search_db_sha256"].get(k):
            die_queue("G-V12", "%s sha256 %s differs from the plan pin %s" % (k, str(shas.get(k))[:16],
                                                                             str(q["search_db_sha256"].get(k))[:16]))


def preflight(q: dict, env: dict, version_info=None) -> dict:
    """G-V15/G-V12 before anything is staged (review F5): what this node would measure with. `launch` runs it
    through node-busy, the queue again at its start, and `preflight` on every queue node before T0."""
    v = tuple(version_info or sys.version_info)[:3]
    if v < (3, 9):
        die_queue("G-V15", "python %s < 3.9 on this node" % ".".join(map(str, v)))
    with tempfile.TemporaryDirectory() as td:
        tl = Path(td) / "t.time"
        try:
            rc = subprocess.run([TIME, "-v", "-o", str(tl), "true"], capture_output=True, timeout=60).returncode
            t = parse_time_log(tl, "G-V15")
        except (OSError, subprocess.SubprocessError, Abort) as x:
            die_queue("G-V15", "%s is not a working GNU time -v: %s" % (TIME, x))
        if rc != 0 or t["exit_status"] != 0:
            die_queue("G-V15", "%s -v true: rc %s exit %s" % (TIME, rc, t["exit_status"]))
    if sys.platform.startswith("linux") and proc_snapshot() is None:
        die_queue("G-V15", "/proc unreadable: contention during an arm cannot be measured")
    dbs = search_dbs(q["tools"]["sage_config"], q["tools"]["msfragger_params"])
    for k, p in dbs.items():
        if not os.path.isfile(p):
            die_queue("G-V12", "%s missing on this node: %s" % (k, p))
    shas = {k: sha256(p) for k, p in dbs.items()}
    check_db_pins(q, shas)
    j = java_info(env)
    return {"python": ".".join(map(str, v)), "time": TIME, "java": {k: j[k] for k in ("path", "version", "major")},
            "search_db": {k: {"path": dbs[k], "sha256": shas[k]} for k in DB_KEYS}}


# ------------------------------------------------------------------------------- node: gate, staging
def busy_patterns(env: dict) -> list:
    base = os.path.basename(env["SPX_BIN"])
    return BUSY_FIXED + [base[:-1].replace(".", r"\.") + "[" + base[-1] + "] -in"]


def busy(patterns: list) -> list:
    hits = []
    for p in patterns:
        r = subprocess.run(["pgrep", "-f", p], capture_output=True, text=True)
        pids = [x for x in r.stdout.split() if x.isdigit() and int(x) != os.getpid()]
        if pids:
            hits.append("%s: %s" % (p, ",".join(pids)))
    return hits


def proc_snapshot() -> dict | None:
    """System-wide busy CPU ticks, the ticks of this runner's own process tree, and MemAvailable. Ours sums
    utime+stime+cutime+cstime over every live member: a reaped child stays counted in its parent's cutime, so
    the tool's CPU is not lost when it exits between two samples. Linux only (None elsewhere or on error)."""
    try:
        with open("/proc/stat") as f:
            v = f.readline().split()
        busy = sum(int(v[i]) for i in (1, 2, 3, 6, 7, 8))          # user nice system irq softirq steal
        kids, cpu = {}, {}
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open("/proc/%s/stat" % d) as f:
                    s = f.read()
            except OSError:
                continue
            x = s[s.rindex(")") + 2:].split()                        # from field 3 (state) on
            kids.setdefault(int(x[1]), []).append(int(d))
            cpu[int(d)] = sum(int(y) for y in x[11:15])
        ours, stack, seen = 0, [os.getpid()], set()
        while stack:
            p = stack.pop()
            if p not in seen:
                seen.add(p)
                ours += cpu.get(p, 0)
                stack += kids.get(p, [])
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                if k in ("MemAvailable", "MemTotal"):
                    mem[k] = int(rest.split()[0])
        return {"t": time.monotonic(), "busy": busy, "ours": ours, "memavail_kb": mem["MemAvailable"],
                "memtotal_kb": mem["MemTotal"]}
    except (OSError, ValueError, IndexError, KeyError):
        return None


def contention(snaps: list, lmax: float) -> dict:
    """G-V06 during one arm (review F2): foreign CPU = busy ticks minus this runner's tree, judged as its highest
    60-s mean (the whole arm when shorter), and the lowest MemAvailable. Unmeasured counts as contended."""
    iv = [(a["t"], b["t"], max(0, (b["busy"] - a["busy"]) - (b["ours"] - a["ours"])) / CLK_TCK)
          for a, b in zip(snaps, snaps[1:]) if b["t"] > a["t"]]
    if not iv:
        return {"measured": False, "samples": len(snaps), "contended": True, "why": ["contention not measured"]}
    t0, t1 = iv[0][0], iv[-1][1]
    win = min(MON_WINDOW_S, t1 - t0)

    def mean_in(lo, hi):              # time-weighted: an interval counts by its overlap with [lo, hi]
        return sum(c * max(0.0, min(b, hi) - max(a, lo)) / (b - a) for a, b, c in iv) / (hi - lo)
    peak = max([mean_in(b - win, b) for _, b, _ in iv if b - t0 >= win - 1e-9] +
               [mean_in(a, a + win) for a, _, _ in iv if t1 - a >= win - 1e-9])
    mem_min, mem_tot = min(s["memavail_kb"] for s in snaps), snaps[0]["memtotal_kb"]
    why = (["foreign CPU %.1f cores > %.0f" % (peak, lmax)] if peak > lmax else []) + \
          (["MemAvailable %.1f%% of total" % (100.0 * mem_min / mem_tot)] if mem_min < MEM_FLOOR * mem_tot else [])
    return {"measured": True, "samples": len(snaps), "seconds": round(t1 - t0, 1), "load_max": lmax,
            "foreign_cores_mean": round(sum(x[2] for x in iv) / (t1 - t0), 1), "foreign_cores_peak60": round(peak, 1),
            "memavail_min_kb": mem_min, "memtotal_kb": mem_tot, "contended": bool(why), "why": why}


class ArmMonitor:
    """Samples proc_snapshot() at the start, every MON_S seconds while the arm runs, and at the end."""

    def __init__(self, lmax: float):
        self.lmax, self.snaps, self.stop, self.thread = lmax, [], threading.Event(), None

    def take(self):
        s = proc_snapshot()
        if s:
            self.snaps.append(s)

    def loop(self):
        while not self.stop.wait(MON_S):
            self.take()

    def __enter__(self):
        self.take()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join()
        self.take()
        return False

    def summary(self) -> dict:
        return contention(self.snaps, self.lmax)


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


def rec_path(root, sid: str, *k) -> Path:
    return Path(root) / "records" / (".".join((sid,) + k) + ".json")


def search_done(rec, pair, ctx: dict) -> bool:
    m = (rec or {}).get("measure_sha256") or {}
    return bool(rec and pair) and rec.get("status") == "ok" and rec.get("pair_run") == pair.get("pair_run") \
        and rec.get("tools_sha256") == ctx["tools_sha"] and m.get("search") == ctx["measure"]["search"] \
        and m.get("score") == ctx["measure"]["score"] and rec.get("peptides", 0) > 0


def pair_done(rec, s, ctx: dict, root: Path) -> bool:
    """G-V11: a record is trusted only if it describes THIS build, JDK feature version, measurement code, thread
    count and input, and every output it still has to feed a search is the very file it verified. An old mzML is
    never adopted. `ctx`: ident, tools_sha, measure, threads of the running queue."""
    ident = (rec or {}).get("identity") or {}
    if not rec or rec.get("status") != "ok" or build_identity(ident) != build_identity(ctx["ident"]) \
            or java_major(ident) != java_major(ctx["ident"]) or rec.get("threads") != ctx["threads"] \
            or (rec.get("measure_sha256") or {}).get("pair") != ctx["measure"]["pair"] \
            or rec["sample"].get("pin") != s["pin"] or rec["sample"].get("raw_sha256") != sample_record(s)["raw_sha256"]:
        return False
    for tool in TOOLS:
        a = rec["arms"].get(tool) or {}
        o = a.get("output")
        if not o or o["count"] <= 0 or o["mtime"] <= a["start_epoch"]:
            return False
        if all(search_done(read_json(rec_path(root, s["id"], tool, e)), rec, ctx) for e in ENGINES):
            continue
        p = Path(o["path"])
        if not p.is_file() or p.stat().st_size != o["size"] or p.stat().st_mtime != o["mtime"]:
            return False
    return True


# ------------------------------------------------------------------------------- node: searches
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


def rescore(root, samples: list, ctx: dict) -> int:
    """G-V11 (review F3): a search whose engine run is current but whose peptide rule changed is re-counted from
    its kept result TSV. The engine is not re-run (its mzML may be gone); the record keeps the old counts."""
    n = 0
    for s in samples:
        pair = read_json(rec_path(root, s["id"], "pair"))
        for tool in TOOLS:
            for e in ENGINES:
                p = rec_path(root, s["id"], tool, e)
                r = read_json(p)
                m = (r or {}).get("measure_sha256") or {}
                if not (r and pair and r.get("status") == "ok" and r.get("pair_run") == pair.get("pair_run")
                        and r.get("tools_sha256") == ctx["tools_sha"] and m.get("search") == ctx["measure"]["search"]
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
                say("search %s %s %s re-counted: %s -> %s peptides" % (s["id"], tool, e, keep.get("peptides"), r.get("peptides")))
                n += 1
    return n


def leftovers(root) -> list:
    runs = Path(root) / "runs"
    return sorted(str(p.relative_to(root)) for p in list(runs.rglob("*.mzML")) + list(runs.rglob("*.mzBIN*"))) \
        if runs.is_dir() else []


def sweep_outputs(root, samples: list, ctx: dict) -> list:
    """Delete each extractor mzML whose two searches are done (review F9: a runner killed between the second ok
    record and the unlink left it behind for good). Returns every mzML/mzBIN still under runs/."""
    for s in samples:
        pair = read_json(rec_path(root, s["id"], "pair"))
        if not pair or pair.get("status") != "ok":
            continue
        for tool in TOOLS:
            o = (pair["arms"].get(tool) or {}).get("output")
            if o and all(search_done(read_json(rec_path(root, s["id"], tool, e)), pair, ctx) for e in ENGINES):
                Path(o["path"]).unlink(missing_ok=True)
    return leftovers(root)


# ------------------------------------------------------------------------------- node: queue
def lock_state(lock: str) -> tuple:
    """Read-only probe. SHARED: two probes (status + collect) must not see each other as a queue; a
    queue's exclusive lock still conflicts, and a runner starting during a probe retries (LOCK_RETRY_S)."""
    if not os.path.exists(lock):
        return False, ""
    with open(lock, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            f.seek(0)
            return True, f.read().strip()
        fcntl.flock(f, fcntl.LOCK_UN)
        f.seek(0)
        return False, f.read().strip()


def node_root_checked(q: dict) -> Path:
    root = Path(q["root"])
    real = (str(root), os.path.realpath(str(root)))
    if any(r.startswith("/home/") for r in real):
        die_queue("G-V15", "root %s is under /home: quota exhaustion kills jobs silently" % root)
    if any(r.startswith("/ceph/") for r in real):
        die_queue("G-V07", "root %s is on ceph: staged inputs and outputs must be node-local" % root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)     # umask 0022 made it 0755: in-house mzMLs and logs readable on a shared node
    return root


def with_node_lock(q: dict, what: str, fn) -> int:
    lockf = open(q["lock"], "a+")
    try:
        deadline = time.monotonic() + LOCK_RETRY_S
        while True:
            try:
                fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    die_queue("G-V05", "another corpus queue holds %s" % q["lock"])
                time.sleep(0.2)
        lockf.seek(0)
        lockf.truncate()
        lockf.write("pid %d %s plan %s nonce %s\n" % (os.getpid(), what, q["plan"], q["nonce"]))
        lockf.flush()
        return fn()
    finally:
        lockf.close()


def node_run(q: dict) -> int:
    root = node_root_checked(q)
    return with_node_lock(q, "queue", lambda: _node_run(q, root))


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
    ident0 = identity(q, env)
    meta = arm_meta(env, ident0)
    tools = install_tools(q)
    ctx = {"ident": ident0, "tools_sha": tools["sha256"], "measure": measure_sha256(), "threads": q["threads"]}
    meta.update(measure=ctx["measure"], runtime=runtime)
    patterns = busy_patterns(env)
    say("QUEUE_START plan %s node %s cores %s load %.1f label %s binary %s jar %s java %s harness %s measure %s "
        "samples %d removed %s" % (q["plan"], hostname(), os.cpu_count(), load1(), meta["label"],
                                   ident0["binary_sha256"][:16], ident0["jar_sha256"][:16], runtime["java"]["version"],
                                   q["harness_sha256"][:16], "/".join(v[:8] for v in ctx["measure"].values()),
                                   len(q["samples"]), removed))
    n = rescore(root, q["samples"], ctx)
    if n:
        say("RESCORED %d search cell(s) from their kept result TSVs (peptide rule changed)" % n)
    sweep_outputs(root, q["samples"], ctx)
    failed = 0
    for i, s in enumerate(q["samples"]):             # phase 1: timed pairs, one at a time, no searches
        if pair_done(read_json(rec_path(root, s["id"], "pair")), s, ctx, root):
            say("pair %s already done (record verified): skipped" % s["id"])
            continue
        failed += not run_pair(q, i, s, env, ident0, meta, removed, patterns)
    say("PHASE1_DONE failed %d" % failed)
    pairs = {s["id"]: read_json(rec_path(root, s["id"], "pair")) for s in q["samples"]}

    def pending(s, tool, e):
        return not search_done(read_json(rec_path(root, s["id"], tool, e)), pairs[s["id"]], ctx)

    def unit(u):                                      # -> number of failed search cells
        s, tool = u
        oks = [run_search(q, s, tool, e, pairs[s["id"]], tools, env, ctx) if pending(s, tool, e) else True
               for e in ENGINES]
        if all(oks):                                  # both engines succeeded: the mzML goes
            Path(pairs[s["id"]]["arms"][tool]["output"]["path"]).unlink(missing_ok=True)
        return oks.count(False)

    units = [(s, t) for s in q["samples"] if pair_done(pairs[s["id"]], s, ctx, root)
             for t in TOOLS if any(pending(s, t, e) for e in ENGINES)]
    rest, msf_ok = [], False
    for u in units:      # alone until one MSFragger search succeeded: a failed first one built no .pepindex (F8)
        if not msf_ok and pending(u[0], u[1], "msfragger"):
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


def dry_run(q: dict) -> None:
    import shlex
    env = None
    try:
        env = arm_env(q)[0]
        spx = env["SPX_BIN"]
    except Abort as a:
        print("# NOTE: a launch would ABORT now: %s" % a)
        spx = "$SPX_BIN"
    if env:
        try:
            pre = preflight(q, env)
            print("# preflight: python %s, %s is GNU time, java %s (%s), both databases match the plan pins"
                  % (pre["python"], pre["time"], pre["java"]["version"], pre["java"]["path"]))
        except Abort as a:
            print("# NOTE: a launch would ABORT now: %s" % a)
    root, tp = Path(q["root"]), {k: str(v) for k, v in tool_dest(q).items()}
    j = lambda argv: shlex.join(str(x) for x in argv)
    print("# plan %s node %s root %s search_workers %s load gate: 1-min load <= 24 (>=200 cores) else 12, wait %s min "
          "then flag; during each arm, foreign CPU (60-s mean) above the same threshold or MemAvailable < %d%% flags"
          % (q["plan"], q["node"], root, q["search_workers"], q["load_wait_min"], round(MEM_FLOOR * 100)))
    print("# env: unset %s %s and the inherited LD_LIBRARY_PATH; source %s/%s/env.sh; LC_ALL=C TMPDIR=%s"
          % (" ".join(p + "*" for p in STRIP_PREFIX), " ".join(sorted(STRIP_EXACT)), q["spx_root"], q["arm"], q["jnatmp"]))
    for i, s in enumerate(q["samples"]):
        order = list(TOOLS) if i % 2 == 0 else list(reversed(TOOLS))
        d = root / "stage" / ("%s-<pair_run>" % s["id"])
        staged, pdir = d / (s["id"] + ".d"), root / "runs" / s["id"] / "<pair_run>"
        print("\n## %s  %s  order %s" % (s["id"], s["scheme"], " -> ".join(order)))
        print("# copy data only, folders 0700 (no modes/ACLs/xattrs), neutral name; pin + acq_min check on the raw, "
              "pin check on the copy\ncopy %s %s" % (shlex.quote(s["raw"]), shlex.quote(str(staged))))
        print("# load gate")
        for tool in order:
            a = pdir / tool
            print("sync -f %s; %s >/dev/null   # before each arm, outside its timed window"
                  % (root, j(["cat", staged / "analysis.tdf", staged / "analysis.tdf_bin"])))
            if tool == "dt":
                print("(cd %s && LD_LIBRARY_PATH=./ext/bruker %s >%s 2>&1)"
                      % (q["diatracer_dir"], j(cmd_dt(q, staged, a, a / "time.log")), a / "dt.log"))
            else:
                print("(cd %s && %s >e.log 2>&1)" % (a, j(cmd_spx(q, spx, staged, a / "pseudo.mzML", a / "time.log"))))
        print("rm -rf %s" % d)
    print("\n# phase 2 (after every pair of this queue; MSFragger units alone until one MSFragger search succeeded)\n"
          "# checks: patched == spectra; Sage 'finished in' and '- search:' covering %d-100%% of the spectra; "
          "MSFragger 'TOTAL TIME' and Scans == spectra; peptides > 0" % round(SAGE_MIN_READ * 100))
    for s in q["samples"]:
        pdir = root / "runs" / s["id"] / "<pair_run>"
        for tool in TOOLS:
            mz = pdir / tool / ("pseudo.mzML" if tool == "spx" else s["id"] + "_diatracer.mzML")
            sd = pdir / "search" / ("%s_sage" % tool)
            inp = mz
            if tool == "dt":
                inp = sd / "patched.mzML"
                print("(cd %s && %s)" % (sd, j(cmd_patch(tp, mz, inp, sd / "patch.time"))))
            print("(cd %s && %s)" % (sd, j(cmd_sage(tp, inp, sd, sd / "engine.time"))))
            sd = pdir / "search" / ("%s_msfragger" % tool)
            print("(cd %s && %s && ln -s fixed.mzML in.mzML && %s)"
                  % (sd, j(cmd_fix(tp, mz, sd / "fixed.mzML", sd / "fix.time")), j(cmd_msf(tp, sd / "engine.time"))))
            print("rm -f %s   # only after both engines succeeded" % mz)


def node_status(o: dict) -> dict:
    root = Path(o["root"])
    out = {"host": hostname(), "load1": load1(),
           "records": [json.loads(p.read_text()) for p in sorted((root / "records").glob("*.json"))]}
    if o.get("records_only"):
        return out
    held, info = lock_state(o["lock"])
    log = root / "runner.log"
    pid = done = None
    marker = root / ("%s-%s" % (o.get("done_prefix", "QUEUE_DONE"), o.get("nonce")))
    if o.get("nonce") and (root / ("runner-%s.pid" % o["nonce"])).exists():
        pid = int((root / ("runner-%s.pid" % o["nonce"])).read_text())
    if o.get("nonce") and marker.exists():
        done = marker.read_text().strip()
    out.update(lock_held=held, lock_info=info, pid=pid, done=done,
               log_tail=log.read_bytes()[-4000:].decode(errors="replace").splitlines()[-12:] if log.exists() else [],
               stage_left=sorted(p.name for p in (root / "stage").glob("*")) if (root / "stage").is_dir() else [],
               mzml_left=leftovers(root))
    if o.get("guardtest"):
        res = sorted((root / "guardtest").glob("*/RESULTS.txt"), key=lambda p: p.stat().st_mtime)
        out["guardtest"] = {"path": str(res[-1]), "text": res[-1].read_text()} if res else None
    return out


def node_busy(q: dict) -> dict:
    held, info = lock_state(q["lock"])
    b, pre, err, eg = [], None, None, None
    try:
        env = arm_env(q)[0]
        b = busy(busy_patterns(env))
        pre = preflight(q, env)
    except Abort as a:
        err, eg = a.message, a.guard
    return {"host": hostname(), "load1": load1(), "cores": os.cpu_count(), "busy": b, "preflight": pre,
            "lock_held": held, "lock_info": info, "error": err, "error_guard": eg}


def node_pin(o: dict) -> dict:
    out = {}
    for sid, raw in o["raws"].items():
        try:
            out[sid] = fingerprint(Path(raw), with_acq=True)
        except (Abort, sqlite3.Error, OSError) as x:
            out[sid] = {"error": str(x)}
    return out


def node_collect(o: dict) -> dict:
    held, info = lock_state(o["lock"])
    if held:
        die("G-V14", "a queue still holds the node lock (%s): collect after QUEUE_DONE" % info)
    dest = Path(o["dest"])
    if not dest.parent.name.startswith("corpus_v3") or (dest.parent / "env.sh").exists():
        die("G-V14", "refusing to write %s: not a corpus_v3* results directory" % dest)
    shutil.copytree(o["root"], dest, symlinks=True, dirs_exist_ok=True,       # queue-*.json carry the raw paths
                    ignore=shutil.ignore_patterns("stage", "tools", "queue-*.json", "*.mzML", "*.mzBIN*", "*.tmp*"))
    opened = []           # private (review F10): with POSIX ACLs, chmod lowers the mask, which bounds every named entry
    for p in [dest] + list(dest.rglob("*")):
        if not p.is_symlink():
            os.chmod(p, p.stat().st_mode & ~0o077)
            if p.stat().st_mode & 0o077:
                opened.append(str(p))
    if opened:
        die("G-V14", "collected paths still group/other-accessible: %s" % opened[:3])
    return {"dest": str(dest), "files": sum(1 for p in dest.rglob("*") if p.is_file())}


def node_purge(o: dict) -> dict:
    """After the run: mzMLs kept for failed searches (in-house outputs must not linger) and mzBIN leftovers."""
    held, info = lock_state(o["lock"])
    if held:
        die("G-V14", "a queue still holds the node lock (%s): purge after QUEUE_DONE" % info)
    root = Path(o["root"])
    gone = leftovers(root)
    for rel in gone:
        (root / rel).unlink(missing_ok=True)
    return {"removed": gone, "left": leftovers(root)}


def node_main(argv: list) -> int:
    cmd = argv[0]
    try:
        if cmd in ("node-run", "node-guardtest"):         # node-run|node-guardtest --queue PATH
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # finally-blocks clean the stage
            return (node_run if cmd == "node-run" else node_guardtest)(json.loads(Path(argv[2]).read_text()))
        obj = json.loads(base64.b64decode(argv[1]))
        if cmd == "node-dryrun":
            dry_run(obj)
            return 0
        fn = {"node-status": node_status, "node-busy": node_busy, "node-pin": node_pin, "node-collect": node_collect,
              "node-purge": node_purge}[cmd]
        print("@@JSON " + json.dumps(fn(obj)))
        return 0
    except Abort as a:
        if cmd in ("node-run", "node-guardtest"):
            say("QUEUE_ABORTED %s" % a)
        else:
            print("@@JSON " + json.dumps({"abort": a.message, "guard": a.guard}))
        return 2
    except Exception as x:            # review F5: a crash still ends with a marker line, not only a traceback
        if cmd not in ("node-run", "node-guardtest"):
            raise
        import traceback
        say("QUEUE_ABORTED [CRASH] %s: %s\n%s" % (type(x).__name__, x, traceback.format_exc()))
        return 2
    except BaseException as x:
        if cmd in ("node-run", "node-guardtest"):
            say("QUEUE_ABORTED [KILLED] %s" % type(x).__name__)
        raise


# ------------------------------------------------------------------------------- node: guard test on a real node
# `corpus.py guardtest --node data` proves the guards on the node itself: the real raw file (staged as
# in a queue), the plan's real arm, jar, Sage, MSFragger and FASTAs, and the production queue code
# (_node_run). Each fault enters through a fixture built under <root>/guardtest/<nonce>/fixtures,
# never through a branch in the production code and never by touching a published arm or tool:
# a wrapper arm around the real extractor, a diaTracer directory without its Bruker library, a Sage
# wrapper, a java wrapper on PATH.
GT_SPX = r'''#!/usr/bin/env python3
# corpus.py guardtest fixture arm "@MODE@": wraps the plan arm's real extractor (never a published arm).
import os, resource, signal, subprocess, sys, time
REAL, MODE = @REAL@, "@MODE@"
if "-in" not in sys.argv:
    os.execv(REAL, [REAL] + sys.argv[1:])
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "invocations.log"), "a") as f:
    f.write("%d %.3f %s\n" % (os.getpid(), time.time(), " ".join(sys.argv[1:])))
if MODE == "sigbus":      # a republish under the mapping: killed by signal 7, GNU time prints exit status 0
    p = subprocess.Popen([REAL] + sys.argv[1:])
    time.sleep(5)
    p.kill()
    p.wait()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    signal.signal(signal.SIGBUS, signal.SIG_DFL)
    os.kill(os.getpid(), signal.SIGBUS)
    time.sleep(60)
rc = subprocess.call([REAL] + sys.argv[1:])
if MODE == "stale":       # exit 0, but the output predates the arm
    out = sys.argv[sys.argv.index("-out") + 1]
    if os.path.exists(out):
        os.utime(out, (time.time() - 3600,) * 2)
elif MODE == "drift":     # the binary changes while its arm runs
    with open(os.path.abspath(__file__), "a") as f:
        f.write("# republished %f\n" % time.time())
sys.exit(rc)
'''
GT_SAGE = r'''#!/usr/bin/env python3
# corpus.py guardtest fixture: the real Sage, then every peptide_q set to 1.0 (rows, but 0 peptides at 1%)
import csv, os, subprocess, sys
REAL = @REAL@
rc = subprocess.call([REAL] + sys.argv[1:])
out = os.path.join(sys.argv[sys.argv.index("-o") + 1], "results.sage.tsv")
if rc == 0 and os.path.exists(out):
    with open(out, newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    iq = rows[0].index("peptide_q")
    for r in rows[1:]:
        r[iq] = "1.0"
    with open(out, "w", newline="") as f:
        csv.writer(f, delimiter="\t", lineterminator="\n").writerows(rows)
sys.exit(rc)
'''
GT_JAVA = r'''#!/usr/bin/env python3
# corpus.py guardtest fixture: java; for MSFragger only, the "TOTAL TIME" line is dropped from its output
import os, subprocess, sys
REAL, JAR = @REAL@, @JAR@
if not any(a.endswith(JAR) for a in sys.argv[1:]):
    os.execv(REAL, [REAL] + sys.argv[1:])
p = subprocess.Popen([REAL] + sys.argv[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for line in p.stdout:
    if b"TOTAL TIME" not in line:
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
sys.exit(p.wait())
'''


def _gt_arm(fx: Path, q: dict, real: str, mode: str, good_prov: bool) -> None:
    arm = fx / "arms" / mode
    b = arm / "bin" / os.path.basename(real)
    _exe(b, GT_SPX.replace("@REAL@", repr(real)).replace("@MODE@", mode))
    (arm / "lib").mkdir()
    (arm / "env.sh").write_text("source %s\nexport SPX_BIN=%s\n" % (
        shlex.quote(str(Path(q["spx_root"]) / q["arm"] / "env.sh")), shlex.quote(str(b))))
    lines = [x for x in Path(real + ".provenance").read_text().splitlines() if not x.startswith("binary_sha256=")]
    (arm / "bin" / (b.name + ".provenance")).write_text(
        "\n".join(lines + ["binary_sha256=%s" % sha256(b if good_prov else real), "guardtest_fixture=%s" % mode]) + "\n")


def node_guardtest(q: dict) -> int:
    root = node_root_checked(q)
    return with_node_lock(q, "guardtest", lambda: _guardtest(q, root))


def _guardtest(q: dict, root: Path) -> int:
    if "selftest" not in q["plan"]:
        die_queue("G-V01", "guardtest runs for a selftest plan only, never beside a real queue (plan %s)" % q["plan"])
    (root / ("runner-%s.pid" % q["nonce"])).write_text("%d\n" % os.getpid())
    gt, s = root / "guardtest" / q["nonce"], q["samples"][0]
    fx = gt / "fixtures"
    fx.mkdir(mode=0o700, parents=True)
    C = Cases(echo=lambda r: say("GT %s %-6s %s  %s" % r), width=160)
    env = arm_env(q)[0]
    real = env["SPX_BIN"]
    say("GUARDTEST_START plan %s node %s sample %s arm %s binary %s load %.1f"
        % (q["plan"], hostname(), s["id"], q["arm"], real, load1()))
    made = []

    def scen(name, **kw):
        sq = dict(q, root=str(gt / name), nonce="%s-%s" % (q["nonce"], name), load_wait_min=0, **kw)
        Path(sq["root"]).mkdir(mode=0o700)
        made.append(sq)
        say("GT scenario %s" % name)
        try:
            return sq, _node_run(sq, Path(sq["root"]))
        except Exception as x:         # an Abort is an expected outcome for some scenarios
            return sq, x

    def pair(sq, sid=None):
        return _records(sq).get((sid or s["id"], "pair")) or {}

    def stage_clean(sq):
        st = Path(sq["root"]) / "stage"
        return not st.exists() or not any(st.iterdir())

    def block(name, fn):
        try:
            fn()
        except Exception as x:
            C.check("GT", "%s completed" % name, False, "crashed: %s: %s" % (type(x).__name__, x))

    def gt0():      # real records of the main run on this node
        main = read_json(root / "records" / ("%s.pair.json" % s["id"]))
        C.check("G-V11", "GT0 the main run left an ok pair record here", bool(main) and main.get("status") == "ok",
                "run `launch` first" if not main else main.get("status"))
        if not (main and main.get("status") == "ok"):
            return
        ctx0 = {"ident": identity(q, env), "tools_sha": install_tools(q)["sha256"], "measure": measure_sha256(),
                "threads": q["threads"]}
        C.check("G-V11", "GT0 record of the current build, JDK, code and threads is trusted (a relaunch skips it)",
                pair_done(main, s, ctx0, root))
        for what, mut in (("binary", {"binary_sha256": "0" * 64}), ("lib", {"lib_sha256": {}}), ("jar", {"jar_sha256": "0" * 64}),
                          ("ceph library", {"deps_sha256": {**ctx0["ident"]["deps_sha256"], "/ceph/gt0/libx.so": "0" * 64}})):
            C.check("G-V11", "GT0 %s sha256 changed: the same record is NOT adopted" % what,
                    not pair_done(main, s, dict(ctx0, ident=dict(ctx0["ident"], **mut)), root))
        C.check("G-V11", "GT0 measurement code changed: the same record is NOT adopted",
                not pair_done(main, s, dict(ctx0, measure=dict(ctx0["measure"], pair="0" * 64)), root))
        recs = [json.loads(p.read_text()) for p in sorted((root / "records").glob("%s.*.json" % s["id"]))]
        other = [dict(json.loads(json.dumps(r)), id=s["id"] + "_rebuilt") for r in recs]
        for r in other:
            if r["kind"] == "pair":
                r["identity"]["binary_sha256"] = "0" * 64
        base = {"diatracer_jar": q["diatracer_jar"], "threads": q["threads"], "load_wait_min": q["load_wait_min"]}
        reg_t = {"samples": {s["id"]: s, s["id"] + "_rebuilt": s}}
        v = C.ok("G-V13", "GT0 table renders the real records",
                 lambda: render_table(q["plan"], dict(base, queues={q["node"]: {"samples": [s["id"]]}}), reg_t, recs))
        C.check("G-V13", "GT0 real row complete (no pending/FAILED cell)", bool(v) and v[1] == 0, v and v[1:])
        C.abort("G-V13", "GT0 table refuses the real records mixed with another binary's",
                lambda: render_table(q["plan"], dict(base, queues={q["node"]: {"samples": [s["id"], s["id"] + "_rebuilt"]}}),
                                     reg_t, recs + other), "more than one")

    def gt1():      # dt first, dt fails: the extractor arm must never run
        dtfx = fx / "diatracer_without_bruker_lib"
        (dtfx / "ext" / "bruker").mkdir(parents=True)
        shutil.copyfile(Path(q["diatracer_dir"]) / q["diatracer_jar"], dtfx / q["diatracer_jar"])
        q1, r1 = scen("gt1_dt_first_arm_fails", diatracer_dir=str(dtfx), load_max=1e9, samples=[s])
        p = pair(q1)
        C.check("G-V08", "GT1 diaTracer without its Bruker library: the pair fails (%s)" % p.get("message", "")[:70],
                p.get("status") == "failed" and p.get("guard") == "G-V08", p.get("message"))
        C.check("G-V09", "GT1 diaTracer ran first and failed: the extractor arm never ran",
                list(p.get("arms", {})) == ["dt"] and not list(Path(q1["root"]).glob("runs/*/*/spx")), list(p.get("arms", {})))
        C.check("G-V06", "GT1 gate NOT flagged with load_max raised to 1e9",
                bool(p.get("gate")) and p["gate"]["contended"] == bool(p["gate"]["busy"]) and p["gate"]["load_max"] == 1e9, p.get("gate"))
        C.check("G-V14", "GT1 staged copy deleted", stage_clean(q1))
        C.check("G-V08", "GT1 queue reports its failed cell", r1 == 1, r1)

    dummy = dict(s, id=s["id"] + "_pin_mismatch", pin=dict(s["pin"], instrument_serial="not-%s" % s["pin"]["instrument_serial"]))
    fa = dict(spx_root=str(fx / "arms"), samples=[dummy, s], load_max=0.0)    # index 1: the extractor arm runs first
    for mode in ("sigbus", "stale", "drift", "badprov"):
        _gt_arm(fx, q, real, mode, good_prov=mode != "badprov")

    def gt2():
        q2, r2 = scen("gt2_spx_first_sigbus", arm="sigbus", **fa)
        p, d = pair(q2), pair(q2, dummy["id"])
        C.check("G-V02", "GT2 real ceph raw against a wrong pin: refused before staging",
                d.get("guard") == "G-V02" and not d.get("arms") and "registry pin" in d.get("message", ""), d.get("message"))
        C.check("G-V08", "GT2 extractor killed by SIGBUS (time: 'terminated by signal %d', exit status 0): the arm fails"
                % signal.SIGBUS, p.get("guard") == "G-V08" and "exit=0 signal=%d" % signal.SIGBUS in p.get("message", ""),
                p.get("message"))
        inv = fx / "arms" / "sigbus" / "bin" / "invocations.log"
        n = len(inv.read_text().splitlines()) if inv.is_file() else 0
        C.check("G-V09", "GT2 extractor ran first, once (%d), and failed: diaTracer never ran" % n,
                list(p.get("arms", {})) == ["spx"] and not list(Path(q2["root"]).glob("runs/*/*/dt")) and n == 1, list(p.get("arms", {})))
        g = p.get("gate") or {}
        C.check("G-V06", "GT2 gate flagged contended with the threshold lowered to 0 (load %s)" % g.get("load"),
                g.get("contended") is True and g.get("load_max") == 0.0, g)
        C.check("G-V14", "GT2 staged copies deleted", stage_clean(q2))

    def gt3():
        q3, r3 = scen("gt3_stale_output", arm="stale", **fa)
        p = pair(q3)
        C.check("G-V08", "GT3 exit 0 but output mtime before the arm start: the arm fails",
                p.get("guard") == "G-V08" and "stale" in p.get("message", ""), p.get("message"))
        C.check("G-V09", "GT3 diaTracer never ran after the failed first arm", list(p.get("arms", {})) == ["spx"], list(p.get("arms", {})))
        C.check("G-V14", "GT3 staged copies deleted", stage_clean(q3))

    def gt4():
        q4, r4 = scen("gt4_binary_changed_during_arm", arm="drift", **fa)
        p = pair(q4)
        C.check("G-V04", "GT4 SPX_BIN sha256 changed during the arm: the queue aborts",
                isinstance(r4, Abort) and r4.guard == "G-V04" and r4.queue, r4)
        C.check("G-V04", "GT4 the pair record names G-V04", p.get("guard") == "G-V04", p.get("message"))
        C.check("G-V14", "GT4 staged copies deleted after the abort", stage_clean(q4) and not (Path(q4["root"]) / ("QUEUE_DONE-%s" % q4["nonce"])).exists())

    def gt5():
        q5, r5 = scen("gt5_provenance_mismatch", arm="badprov", spx_root=str(fx / "arms"), samples=[s])
        C.check("G-V03", "GT5 provenance binary_sha256 != sha256(SPX_BIN): refused before any pair",
                isinstance(r5, Abort) and r5.guard == "G-V03" and "provenance" in r5.message and not _records(q5), r5)

    def gt6():      # a real pair, then every search fails in a way that once produced a table zero
        sage_w = fx / "tools" / "sage" / "sage"
        _exe(sage_w, GT_SAGE.replace("@REAL@", repr(q["tools"]["sage"])))
        java = shutil.which("java", path=env.get("PATH"))
        _exe(fx / "bin" / "java", GT_JAVA.replace("@REAL@", repr(java)).replace("@JAR@", repr(Path(q["tools"]["msfragger_jar"]).name)))
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = str(fx / "bin") + os.pathsep + old
        try:
            q6, r6 = scen("gt6_search_faults", tools=dict(q["tools"], sage=str(sage_w)), load_max=0.0, search_workers=1, samples=[s])
        finally:
            os.environ["PATH"] = old
        R = _records(q6)
        p = R.get((s["id"], "pair")) or {}
        arms = p.get("arms", {})
        C.check("G-V08", "GT6 real pair: both arms ok, spectrumList counts equal the tools' own lines",
                p.get("status") == "ok" and all(arms[t]["output"]["count"] == arms[t]["log_count"] > 0 and arms[t]["peak_rss_kb"] > 0
                                                for t in TOOLS), {t: (arms[t]["output"]["count"], arms[t]["wall_s"]) for t in arms})
        g = p.get("gate") or {}
        C.check("G-V06", "GT6 gate flagged contended with the threshold lowered to 0", g.get("contended") is True and g.get("load_max") == 0.0, g)
        for t in TOOLS:
            rs, rm = R.get((s["id"], t + ".sage")) or {}, R.get((s["id"], t + ".msfragger")) or {}
            tsv = Path(rs.get("result_tsv") or "/nonexistent")
            rows = sum(1 for _ in open(tsv, "rb")) - 1 if tsv.is_file() else 0
            fin = tsv.is_file() and b"finished in" in (tsv.parent / "sage.log").read_bytes()
            C.check("G-V10", "GT6 %s Sage finished with %d rows but 0 peptides at 1%%: the cell fails" % (t, rows),
                    rs.get("guard") == "G-V10" and "0 peptides" in rs.get("message", "") and rows > 0 and fin, rs.get("message"))
            C.check("G-V10", "GT6 %s MSFragger log without 'TOTAL TIME': the cell fails" % t,
                    rm.get("guard") == "G-V10" and "TOTAL TIME" in rm.get("message", ""), rm.get("message"))
            C.check("G-V14", "GT6 %s mzML kept after its failed searches (re-runnable)" % t,
                    bool(arms.get(t)) and Path(arms[t]["output"]["path"]).is_file())
        done = Path(q6["root"]) / ("QUEUE_DONE-%s" % q6["nonce"])
        C.check("G-V10", "GT6 queue reports 4 failed cells", r6 == 1 and done.is_file() and done.read_text().strip() == "failed 4", r6)

    for name, fn in (("GT0", gt0), ("GT1", gt1), ("GT2", gt2), ("GT3", gt3), ("GT4", gt4), ("GT5", gt5), ("GT6", gt6)):
        block(name, fn)
    C.abort("G-V05", "GT7 a second queue on this node while the lock is held",
            lambda: node_run(dict(q, root=str(gt / "gt7_second_queue"), nonce=q["nonce"] + "-gt7")), "holds")
    C.abort("G-V14", "GT8 collect while the node lock is held",
            lambda: node_collect({"root": str(root), "lock": q["lock"], "dest": str(Path(q["results_ceph"]) / q["node"])}), "still holds")
    for sq in made:                                    # retention: no run-local tool copies, mzML or jar copies left
        remove_tree(Path(sq["root"]) / "tools")
    for junk in list(gt.rglob("*.mzML")) + list(gt.rglob("*.mzBIN*")):
        junk.unlink()
    remove_tree(fx / "diatracer_without_bruker_lib")
    C.check("G-V14", "GT no staged raw, mzML or mzBIN left under the guardtest root",
            not list(gt.glob("*/stage/*")) and not list(gt.rglob("*.mzML")) and not list(gt.rglob("*.mzBIN*")))
    nfail = sum(1 for r in C.results if r[0] == "FAIL")
    txt = "\n".join("%-4s %-6s %s  %s" % r for r in C.results)
    (gt / "RESULTS.txt").write_text("guardtest %s on %s, plan %s, sample %s, arm %s\n\n%s\n\n%d/%d cases pass\n"
                                    % (q["nonce"], hostname(), q["plan"], s["id"], q["arm"], txt, len(C.results) - nfail, len(C.results)))
    say("GUARDTEST_DONE pass %d fail %d results %s" % (len(C.results) - nfail, nfail, gt / "RESULTS.txt"))
    (root / ("GUARDTEST_DONE-%s" % q["nonce"])).write_text("pass %d fail %d\n" % (len(C.results) - nfail, nfail))
    return 0 if nfail == 0 else 1


# ------------------------------------------------------------------------------- local: plan and transport
def _registry(path) -> dict:
    """PyYAML's safe_load keeps the LAST of two duplicate keys without a word (review F12): refuse them."""
    import yaml

    class Unique(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        seen = set()
        for k, _ in node.value:
            key = loader.construct_object(k, deep=deep)
            if key in seen:
                die("G-V01", "%s line %d: duplicate key %r (YAML would silently keep the last one)"
                    % (path, k.start_mark.line + 1, key))
            seen.add(key)
        return loader.construct_mapping(node, deep=deep)

    Unique.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(Path(path).read_text(), Loader=Unique)


def load_plan(name: str, reg_path=REG) -> tuple:
    reg = _registry(reg_path)
    plan = reg.get(name)
    if not isinstance(plan, dict):
        die("G-V01", "no plan section %r in %s" % (name, reg_path))
    if set(plan) != PLAN_KEYS or not isinstance(plan["tools"], dict) or set(plan["tools"]) != set(TOOL_KEYS):
        die("G-V01", "plan %s: unknown keys %s, missing keys %s (tools need exactly %s)"
            % (name, sorted(set(plan) - PLAN_KEYS), sorted(PLAN_KEYS - set(plan)), TOOL_KEYS))
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
    if not isinstance(db, dict) or set(db) != set(DB_KEYS) or not all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in db.values()):
        die("G-V01", "plan %s: search_db_sha256 needs exactly %s as sha256 hex" % (name, DB_KEYS))
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


def lock_path(plan: dict) -> str:
    return str(Path(plan["scratch_root"]).parent / ".corpus-queue.lock")   # node-wide: one queue per node


def node_root(plan: dict, node: str, key="scratch_root") -> str:
    return "%s/%s" % (plan[key].rstrip("/"), node)


def resolve_queue(name: str, plan: dict, reg: dict, node: str) -> dict:
    if node not in plan["queues"]:
        die("G-V01", "plan %s has no queue for node %s" % (name, node))
    qd = plan["queues"][node]
    q = {k: plan[k] for k in PLAN_KEYS if k != "queues"}
    q.update(plan=name, node=node, nonce=time.strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex(),
             root=node_root(plan, node), lock=lock_path(plan), harness_sha256=sha256(SELF),
             search_workers=int(qd.get("search_workers", 1)),
             samples=[dict({k: reg["samples"][sid][k] for k in SAMPLE_KEYS}, id=sid,
                           label=reg["samples"][sid].get("label", sid)) for sid in qd["samples"]])
    return q


SSH = ["ssh", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15"]


def ssh(node: str, command: str) -> str:
    r = subprocess.run(SSH + [node, command], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        sys.exit("ssh %s failed (rc %d): %s" % (node, r.returncode, r.stderr[-400:]))
    return r.stdout


def remote(node: str, cmd: str, obj, want_json=True):
    """Runs THIS file on the node from stdin (`python3 -`): read-only commands never meet version skew."""
    arg = base64.b64encode(json.dumps(obj).encode()).decode()
    r = subprocess.run(SSH + [node, "python3", "-", cmd, arg], input=SELF.read_bytes(), capture_output=True)
    out = r.stdout.decode(errors="replace")
    if not want_json:
        if r.returncode != 0:
            sys.exit("remote %s on %s failed (rc %d): %s" % (cmd, node, r.returncode, r.stderr.decode(errors="replace")[-600:]))
        return out
    for line in reversed(out.splitlines()):
        if line.startswith("@@JSON "):
            res = json.loads(line[7:])
            if isinstance(res, dict) and set(res) == {"abort", "guard"}:
                die(res["guard"], "%s: %s" % (node, res["abort"]))
            return res
    sys.exit("remote %s on %s failed (rc %d): %s" % (cmd, node, r.returncode, r.stderr.decode(errors="replace")[-600:]))


def check_launch(b: dict, node: str) -> None:
    if b.get("error"):
        die(b["error_guard"], "%s: %s" % (node, b["error"]))
    if b["lock_held"]:
        die("G-V05", "%s: a corpus queue already holds the node lock (%s)" % (node, b["lock_info"]))
    if b["busy"]:
        die("G-V05", "%s: our tools are already running there: %s" % (node, b["busy"]))


# ------------------------------------------------------------------------------- local: commands
def cmd_pin(args) -> int:
    reg = _registry(REG)
    ids = args.ids.split(",") if args.ids else [sid for sid, e in reg["samples"].items() if e.get("raw")]
    res = remote(args.node, "node-pin", {"raws": {sid: reg["samples"][sid]["raw"] for sid in ids}})
    for sid in ids:
        fp = res[sid]
        if "error" in fp:
            print("  # %s: ERROR %s" % (sid, fp["error"]))
            continue
        miss = [k for k in PIN_KEYS if fp.get(k) in (None, "")]
        print("  %s:  # acq_min %.1f%s\n    pin: %s" % (sid, fp["acq_min"], "  MISSING %s" % miss if miss else "",
                                                     json.dumps({k: fp[k] for k in PIN_KEYS})))
    return 0


def cmd_dry_run(args) -> int:
    plan, reg = load_plan(args.plan)
    q = resolve_queue(args.plan, plan, reg, args.node)
    if args.local:
        dry_run(q)
    else:
        sys.stdout.write(remote(args.node, "node-dryrun", q, want_json=False))
    return 0


def launch_detached(q: dict, entry: str, done_prefix: str, ok_done: str) -> int:
    root, n = q["root"], q["node"]
    script = "%s/harness/corpus-%s.py" % (root, q["harness_sha256"][:12])   # content-named: never overwritten
    qpath = "%s/queue-%s.json" % (root, q["nonce"])
    qr = shlex.quote(root)
    ssh(n, "mkdir -p %s/harness && chmod 700 %s %s/harness" % (qr, qr, qr))   # private root (in-house outputs)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "q.json").write_text(json.dumps(q, indent=1))
        for src, dst in ((SELF, "%s.part-%s" % (script, q["nonce"])), (Path(td) / "q.json", qpath)):
            if subprocess.run(["scp", "-q", "-o", "ConnectTimeout=20", str(src), "%s:%s" % (n, dst)]).returncode:
                sys.exit("scp to %s failed" % n)
    ssh(n, "mv -n %s.part-%s %s; rm -f %s.part-%s" % (script, q["nonce"], script, script, q["nonce"]))
    # one redirected simple command: nothing that outlives it holds the ssh channel (ssh-background-launch-shape)
    ssh(n, "setsid nohup python3 %s %s --queue %s </dev/null >>%s/runner.log 2>&1 &" % (script, entry, qpath, root))
    s = {}
    for _ in range(20):
        time.sleep(2)
        s = remote(n, "node-status", {"root": root, "lock": q["lock"], "nonce": q["nonce"], "records_only": False,
                                      "done_prefix": done_prefix})
        if s["pid"]:
            break
    if s.get("pid") and s["lock_held"] and q["nonce"] in s["lock_info"]:
        print("LAUNCH_OK %s pid %s nonce %s log %s/runner.log" % (s["host"], s["pid"], q["nonce"], root))
        return 0
    print("\n".join(s.get("log_tail", [])))
    if s.get("done"):                      # e.g. a resume with every cell already verified
        print("LAUNCH_FINISHED %s nonce %s: %s" % (n, q["nonce"], s["done"]))
        return 0 if s["done"] == ok_done else 1
    print("LAUNCH_NOT_RUNNING %s nonce %s: the runner exited or never started (log above)" % (n, q["nonce"]))
    return 7


def cmd_launch(args) -> int:
    plan, reg = load_plan(args.plan)
    q = resolve_queue(args.plan, plan, reg, args.node)
    check_launch(remote(args.node, "node-busy", q), args.node)
    return launch_detached(q, "node-run", "QUEUE_DONE", "failed 0")


def cmd_guardtest(args) -> int:
    """Faults injected on the REAL node against the real raw file, arm, jar and search tools (see
    node_guardtest). Selftest plans only; detached like a queue, read back with --show."""
    plan, reg = load_plan(args.plan)
    if "selftest" not in args.plan:
        die("G-V01", "guardtest runs for a *selftest* plan only (got %s)" % args.plan)
    q = resolve_queue(args.plan, plan, reg, args.node)
    if args.show:
        s = remote(args.node, "node-status", {"root": q["root"], "lock": q["lock"], "records_only": False, "guardtest": True})
        print("== %s lock %s" % (args.node, "HELD " + s["lock_info"] if s["lock_held"] else "free"))
        print("\n".join("  | " + x for x in s["log_tail"]))
        g = s.get("guardtest")
        print("\n%s\n%s" % (g["path"], g["text"]) if g else "\nno guardtest RESULTS.txt yet")
        return 0 if g and re.search(r"^(\d+)/\1 cases pass$", g["text"], re.M) and not s["lock_held"] else 1
    check_launch(remote(args.node, "node-busy", q), args.node)
    return launch_detached(q, "node-guardtest", "GUARDTEST_DONE", "fail 0")


def cmd_status(args) -> int:
    plan, _ = load_plan(args.plan)
    cols = ["pair"] + ["%s.%s" % (t, e) for t in TOOLS for e in ENGINES]
    for node in [args.node] if args.node else list(plan["queues"]):
        s = remote(node, "node-status", {"root": node_root(plan, node), "lock": lock_path(plan)})
        print("\n== %s (host %s) load %.1f  lock %s  stage leftovers %s"
              % (node, s["host"], s["load1"], "HELD " + s["lock_info"] if s["lock_held"] else "free", s["stage_left"] or "none"))
        recs = {(r["id"], "pair" if r["kind"] == "pair" else "%s.%s" % (r["tool"], r["engine"])): r for r in s["records"]}
        print("%-10s " % "sample" + " ".join("%-15s" % c for c in cols))
        for sid in plan["queues"][node]["samples"]:
            pair, cells = recs.get((sid, "pair")), []
            for c in cols:
                r = recs.get((sid, c))
                if r is None:
                    cells.append("-")
                elif r["status"] != "ok":
                    cells.append("%s %s" % (r["status"], r.get("guard", "")))
                elif c == "pair":
                    cells.append("ok")
                else:
                    cells.append("ok %s" % r["peptides"] if pair and r["pair_run"] == pair["pair_run"] else "stale")
            fl = pair_flags(pair) if pair else "-"
            print("%-10s " % sid + " ".join("%-15s" % c for c in cells) + ("" if fl == "-" else "  " + fl))
        if s.get("mzml_left"):
            print("  mzML/mzBIN under runs/: %d (%s)" % (len(s["mzml_left"]), ", ".join(s["mzml_left"][:4])))
        for line in s["log_tail"][-6:]:
            print("  | " + line)
    return 0


def cmd_collect(args) -> int:
    plan, _ = load_plan(args.plan)
    r = remote(args.node, "node-collect", {"root": node_root(plan, args.node), "lock": lock_path(plan),
                                           "dest": node_root(plan, args.node, "results_ceph")})
    print("COLLECTED %s files -> %s" % (r["files"], r["dest"]))
    return 0


def cmd_purge(args) -> int:
    plan, _ = load_plan(args.plan)
    r = remote(args.node, "node-purge", {"root": node_root(plan, args.node), "lock": lock_path(plan)})
    print("PURGED %d file(s) on %s; %d left" % (len(r["removed"]), args.node, len(r["left"])))
    return 0 if not r["left"] else 1


def cmd_preflight(args) -> int:
    """Before T0, on every queue node of the plan (or one): python, GNU time, java, database pins, our tools
    running, queue lock. The JDK feature version must agree across nodes, or the table refuses after the run."""
    plan, reg = load_plan(args.plan)
    majors, bad = {}, 0
    for node in [args.node] if args.node else list(plan["queues"]):
        b = remote(node, "node-busy", resolve_queue(args.plan, plan, reg, node))
        print("== %s (host %s) load %.1f cores %s lock %s busy %s" % (node, b["host"], b["load1"], b["cores"],
              "HELD " + b["lock_info"] if b["lock_held"] else "free", b["busy"] or "none"))
        if b.get("error"):
            print("   ABORT [%s] %s" % (b["error_guard"], b["error"]))
            bad += 1
            continue
        pre = b["preflight"]
        print("   python %s, %s is GNU time, java %s (%s), sage_fasta %s, msfragger_db %s" % (
            pre["python"], pre["time"], pre["java"]["version"], pre["java"]["path"],
            pre["search_db"]["sage_fasta"]["sha256"][:16], pre["search_db"]["msfragger_db"]["sha256"][:16]))
        majors[node] = pre["java"]["major"]
        bad += bool(b["busy"] or b["lock_held"])
    if len(set(majors.values())) > 1:
        die("G-V15", "Java feature versions differ across nodes: %s" % majors)
    print("PREFLIGHT_OK" if not bad else "PREFLIGHT_FAILED %d node(s)" % bad)
    return 0 if not bad else 2


def cmd_table(args) -> int:
    plan, reg = load_plan(args.plan)
    recs = []
    for node, qd in plan["queues"].items():
        key = "scratch_root" if args.source == "scratch" else "results_ceph"
        got = remote(node, "node-status", {"root": node_root(plan, node, key), "records_only": True})["records"]
        recs += [r for r in got if r["id"] in qd["samples"]]
    md, incomplete, total = render_table(args.plan, plan, reg, recs, args.source)
    out = Path(args.out) if args.out else REPO / plan["report"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print("wrote %s: %d of %d rows incomplete" % (out, incomplete, total))
    return 3 if incomplete else 0


# ------------------------------------------------------------------------------- local: table
def pair_flags(p: dict, names=None) -> str:
    """G-V06 flags of one pair record: the gate before the pair and the contention measured during each arm."""
    names = names or {t: t for t in TOOLS}
    out, g = [], p.get("gate") or {}
    if g.get("contended"):
        out.append("gate: load %.1f > %.0f%s" % (g["load"], g["load_max"], ", busy" if g.get("busy") else ""))
    for t in p.get("order") or TOOLS:
        a = (p.get("arms") or {}).get(t)
        if a is None or (p.get("status") != "ok" and "during" not in a):
            continue
        du = a.get("during") or {"contended": True, "why": ["contention not measured"]}
        if du.get("contended"):
            out.append("during %s: %s" % (names[t], "; ".join(du.get("why") or ["?"])))
    return "; ".join(out) or "-"


def search_overlaps(recs: list) -> set:
    """(id, tool, engine) of every search whose engine step overlapped another search's engine step on its node."""
    steps = [(r["node"], (r["id"], r["tool"], r["engine"]), st["start_epoch"], st["end_epoch"])
             for r in recs if r["kind"] == "search" for st in [(r.get("steps") or {}).get("engine") or {}]
             if st.get("start_epoch") is not None and st.get("end_epoch") is not None]
    return {k1 for n1, k1, a1, b1 in steps for n2, k2, a2, b2 in steps if k1 != k2 and n1 == n2 and a1 < b2 and a2 < b1}


def render_table(name, plan, reg, recs, source="scratch") -> tuple:
    pairs = {r["id"]: r for r in recs if r["kind"] == "pair"}
    srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r["kind"] == "search"}
    okp = [p for p in pairs.values() if p["status"] == "ok"]
    oks = [r for r in srch.values() if r["status"] == "ok"]
    one = lambda xs: len({json.dumps(x, sort_keys=True) for x in xs}) <= 1
    if not one(build_identity(p["identity"]) for p in okp) or not one(p["label"] for p in okp):
        die("G-V13", "records come from more than one binary/lib/jar: one table, one build")
    if not one(java_major(p["identity"]) for p in okp):
        die("G-V13", "pair records ran on different Java feature versions: %s" % sorted({str(java_major(p["identity"])) for p in okp}))
    if any(not (p.get("measure_sha256") or {}).get("pair") for p in okp) or not one(p["measure_sha256"] for p in okp) \
            or not one(p.get("threads") for p in okp):
        die("G-V13", "pair records measured by different harness code or thread counts (or without measurement hashes)")
    if not one(r["tools_sha256"] for r in oks):
        die("G-V13", "search records used different engines, configs or FASTAs")
    if any(not (r.get("measure_sha256") or {}).get("search") for r in oks) or not one(r["measure_sha256"] for r in oks):
        die("G-V13", "search records run or counted by different harness code (or without measurement hashes)")
    for p in okp:
        if {a["host"] for a in p["arms"].values()} != {p["node"]}:
            die("G-V13", "pair %s: arms on %s, record node %s" % (p["id"], sorted(a["host"] for a in p["arms"].values()), p["node"]))
        e = reg["samples"].get(p["id"]) or {}
        if e.get("pin") != p["sample"]["pin"] or p["sample"].get("raw_sha256") != hashlib.sha256(str(e.get("raw")).encode()).hexdigest():
            die("G-V13", "pair %s: record pin or raw path differs from samples.yaml" % p["id"])
        if any(a["output"]["count"] <= 0 or a["peak_rss_kb"] <= 0 for a in p["arms"].values()):
            die("G-V13", "pair %s: ok record with a spectrum count or RSS <= 0" % p["id"])
    for r in oks:
        if r.get("peptides", 0) <= 0:
            die("G-V13", "search %s %s %s: ok record with %s peptides" % (r["id"], r["tool"], r["engine"], r.get("peptides")))

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


# ------------------------------------------------------------------------------- measurement code identity
# G-V11/G-V13 (review F3): a record counts only for the code that measured it. Function sources (comments included)
# and the constants they use, captured at import: a selftest monkeypatch of a global cannot change them. A change to
# `pair` re-runs pairs; to `search` re-runs searches (and pairs whose mzML is gone); to `score` only re-counts kept TSVs.
MEASURED = {
    "pair": (DT_PARAMS, STRIP_PREFIX, sorted(STRIP_EXACT), sorted(INHERIT_DROP), LIB_ROOTS, MON_S, MON_WINDOW_S, MEM_FLOOR,
             arm_env, strip_var, stage, fingerprint, check_pin, neighbour, load_max, load_gate, proc_snapshot, contention,
             ArmMonitor, flush_io, prewarm, cmd_dt, cmd_spx, run_logged, run_arm, run_pair, parse_time_log, check_exit,
             verify_mzml, log_count),
    "search": (SAGE_TELEMETRY, SAGE_MIN_READ, cmd_patch, cmd_sage, cmd_fix, cmd_msf, run_logged, run_search,
               engine_spectra, parse_time_log, check_exit, log_count),
    "score": (sage_peptides, msf_peptides),
}


def measure_sha256() -> dict:
    out = {}
    for part, items in MEASURED.items():
        h = hashlib.sha256()
        for x in items:
            h.update((inspect.getsource(x) if callable(x) else repr(x)).encode())
        out[part] = h.hexdigest()
    return out


# ------------------------------------------------------------------------------- selftest
FAKE_HEAD = r'''#!/usr/bin/env python3
import os, re, shutil, sys, time
def arg(k):
    return sys.argv[sys.argv.index(k) + 1]
def hit(var, s):
    v = os.environ.get(var)
    return bool(v) and all(p in s for p in v.split("&"))
def count(path):
    return int(re.search(r'count="(\d+)"', open(path).read()).group(1))
def mzml(path, n, pad=False):
    c = ("%010d" % n) if pad else str(n)
    with open(path, "w") as f:
        f.write('<?xml version="1.0"?>\n<indexedmzML><mzML><run><spectrumList count="%s">\n<spectrum/>\n'
                '</spectrumList></run></mzML>\n<indexListOffset>1</indexListOffset></indexedmzML>\n' % c)
'''
FAKE_TIME = r'''#!/bin/bash
[ "$1" = -v ] && [ "$2" = -o ] || exit 99
out=$3; shift 3
"$@"; rc=$?; st=$rc
{ echo "Command being timed: \"$*\""
  echo "Elapsed (wall clock) time (h:mm:ss or m:ss): 1:02.50"
  echo "Maximum resident set size (kbytes): 2500000"
  if [ $rc -gt 128 ]; then echo "Command terminated by signal $((rc - 128))"; st=0; fi   # as GNU time reports it
  if [ -n "${FAKE_SIGNAL_FOR:-}" ] && [[ "$*" == *"$FAKE_SIGNAL_FOR"* ]]; then echo "Command terminated by signal 7"; fi
  echo "Exit status: $st"; } > "$out"
exit $rc
'''
FAKE_SPX = FAKE_HEAD + r'''
if "--help" in sys.argv:
    print("DIAspeXtract -- Extracts pseudo-MS/MS spectra\nVersion: 9.9.9")
    sys.exit(0)
inp, out = arg("-in"), arg("-out")
with open(os.environ["FAKE_ENVDUMP"], "a") as f:
    f.write("\n".join(sorted(os.environ)) + "\n")
mzml(out, 42, pad=True)
print("Wrote %d pseudo-spectra" % (41 if hit("FAKE_SPX_MISCOUNT", inp) else 42))
'''
FAKE_JAVA = FAKE_HEAD + r'''
if "-version" in sys.argv:
    sys.stderr.write('openjdk version "21.0.12" 2026-07-21\n')
    sys.exit(0)
jar = arg("-jar")
if "diaTracer" in jar:
    d = arg("-d")
    if hit("FAKE_DT_FAIL", d):
        sys.exit(1)
    if not [f for f in os.listdir("ext/bruker") if f.endswith(".so")]:     # cwd-relative, like the real jar
        print("JNA could not load native Bruker library")
        sys.exit(1)
    mzml(os.environ["FAKE_NEIGHBOUR"] if hit("FAKE_DT_CEPH", d) else d[:-2] + "_diatracer.mzML", 17)
    print("Writing mzML file...17 scans")
else:
    t0 = time.time()
    time.sleep(float(os.environ.get("FAKE_MSF_SLEEP", "0")))
    with open("in.tsv", "w") as f:
        f.write("scannum\tpeptide\tproteins\tmodification_info\thyperscore\n")
        f.write("".join("%d\tPEP%d\tsp|P%d|X_HUMAN desc, with comma\t\t%d\n" % (i, i, i, 200 - i) for i in range(150)))
        f.write("0\tREVPEP\trev_sp|Q1|Y_HUMAN decoy\t\t1\n")
    open("in_uncalibrated.mzBIN", "w").write("x")
    with open(os.environ["FAKE_MSF_TIMES"], "a") as f:
        f.write("%f %f\n" % (t0, time.time()))
    n = count("in.mzML")
    print("in.mzML: Scans = %d; MS2 ITMS = false" % (n - 1 if hit("FAKE_MSF_SCANS_SHORT", os.getcwd()) else n))
    if not hit("FAKE_MSF_NOTOTAL", os.getcwd()):
        print("TOTAL TIME 0.1 MIN")
'''
FAKE_SAGE = FAKE_HEAD + r'''
odir, mz = arg("-o"), sys.argv[-1]
assert os.path.exists(mz), mz
zero = hit("FAKE_SAGE_ZERO", mz)
rows = "".join("%d\tPEPTIDE%d\tsp|P%d|X\t1\tf.mzML\t%d\t1\t1\t%s\n" % (i, i, i, i, "0.5" if zero else "0.001") for i in range(30))
if not zero:
    rows += "99\tDECOYPEP\trev_sp|P1|X\t1\tf.mzML\t99\t1\t-1\t0.001\n"
with open(os.path.join(odir, "results.sage.tsv"), "w") as f:
    f.write("psm_id\tpeptide\tproteins\tnum_proteins\tfilename\tscannr\trank\tlabel\tpeptide_q\n" + rows)
n = count(mz)
print("[INFO sage] - search:       999 ms (%d spectra/s)" % (n // 3 if hit("FAKE_SAGE_SHORT", mz) else n))
print("[INFO sage] finished in 1s")
'''
FAKE_PATCH = FAKE_HEAD + r'''
shutil.copy(sys.argv[1], sys.argv[2])
n = count(sys.argv[1])
print("patched %d precursor(s) -> %s" % (0 if hit("FAKE_PATCH_ZERO", sys.argv[1]) else n - 1 if hit("FAKE_PATCH_SHORT", sys.argv[1])
                                         else n, sys.argv[2]))
'''
FAKE_FIX = FAKE_HEAD + r'''
shutil.copy(sys.argv[1], sys.argv[2])
sys.stderr.write("done: 9 lines, 3 valueless cvParams patched -> %s\n" % sys.argv[2])
'''


class Cases:
    """Asserts THE guard id (and message fragment) fired; every abort path has a positive control."""

    def __init__(self, echo=None, width=84):
        self.results, self.fired, self.echo, self.width = [], set(), echo, width

    def _add(self, row):
        self.results.append(row)
        if self.echo:
            self.echo(row)

    def abort(self, guard, name, fn, match=None):
        try:
            fn()
        except Abort as a:
            if a.guard != guard or (match and match.lower() not in a.message.lower()):
                self._add(("FAIL", guard, name, "wrong guard/check: [%s] %s" % (a.guard, a.message[:70])))
            else:
                self._add(("PASS", guard, name, a.message.splitlines()[0][:self.width]))
                self.fired.add(guard)
            return
        except Exception as x:
            self._add(("FAIL", guard, name, "crashed instead of aborting: %s: %s" % (type(x).__name__, x)))
            return
        self._add(("FAIL", guard, name, "guard did NOT fire"))

    def ok(self, guard, name, fn):
        try:
            v = fn()
        except Exception as x:
            self._add(("FAIL", guard, name, "false positive or crash: %s: %s" % (type(x).__name__, x)))
            return None
        self._add(("PASS", guard, name, "no false positive"))
        return v

    def check(self, guard, name, cond, detail=""):
        self._add(("PASS" if cond else "FAIL", guard, name, str(detail)[:self.width]))
        if cond:
            self.fired.add(guard)


def _exe(p: Path, txt: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt)
    p.chmod(0o755)


def _raw(base: Path, sid: str) -> Path:
    d = base / ("run_%s.d" % sid)
    d.mkdir(parents=True)
    con = sqlite3.connect(str(d / "analysis.tdf"))
    con.execute("create table GlobalMetadata (Key text, Value text)")
    con.executemany("insert into GlobalMetadata values (?, ?)",
                    [("AcquisitionDateTime", "2020-05-05T15:37:55+02:00"), ("InstrumentSerialNumber", "1854399.140")])
    con.execute("create table Frames (Id integer, Time real)")
    con.executemany("insert into Frames values (?, ?)", [(1, 0.5), (2, 1860.5)])
    con.commit()
    con.close()
    (d / "analysis.tdf_bin").write_bytes(b"\0" * (1000 + ord(sid)))
    (d / "run.m").mkdir()                              # real .d: read-only method folder
    (d / "run.m" / "method.xml").write_text("<m/>")
    os.chmod(d / "run.m", 0o555)
    return d


def _prov(arm: Path, binary="fakespx") -> None:
    (arm / "bin" / (binary + ".provenance")).write_text(
        "git=abc1234\nbuilt=2026-09-10\nbinary_sha256=%s\n" % sha256(arm / "bin" / binary))


def _world(w: Path) -> None:
    _exe(w / "bin" / "time", FAKE_TIME)
    _exe(w / "bin" / "java", FAKE_JAVA)
    spx = w / "ceph" / "spx"
    for arm, body in (("arm", FAKE_SPX), ("arm_nohelp", FAKE_HEAD)):
        _exe(spx / arm / "bin" / "fakespx", body)
        (spx / arm / "lib").mkdir()
        (spx / arm / "lib" / "libOpenMS.so").write_bytes(b"lib")
        (spx / arm / "lib" / "sub").mkdir()                         # identity must recurse (review F6)
        (spx / arm / "lib" / "sub" / "libdep.so").write_bytes(b"dep")
        (spx / arm / "env.sh").write_text("export SPX_BIN=%s\n" % (spx / arm / "bin" / "fakespx"))
        _prov(spx / arm)
    (spx / "arm_probe").mkdir()
    (spx / "arm_probe" / "env.sh").write_text("export SPX_BIN=%s\nexport DIASPEXTRACT_DET=1\n" % (spx / "arm" / "bin" / "fakespx"))
    (spx / "arm_omp").mkdir()
    (spx / "arm_omp" / "env.sh").write_text("export SPX_BIN=%s\nexport OMP_NUM_THREADS=8\n" % (spx / "arm" / "bin" / "fakespx"))
    (spx / "arm_outside").mkdir()
    (spx / "arm_outside" / "env.sh").write_text("export SPX_BIN=%s\n" % (spx / "arm" / "bin" / "fakespx"))
    shutil.copytree(spx / "arm", spx / "arm_badprov")
    (spx / "arm_badprov" / "env.sh").write_text("export SPX_BIN=%s\n" % (spx / "arm_badprov" / "bin" / "fakespx"))
    (spx / "arm_badprov" / "bin" / "fakespx.provenance").write_text("binary_sha256=00ff\n")
    (spx / "diatracer" / "ext" / "bruker").mkdir(parents=True)
    (spx / "diatracer" / "ext" / "bruker" / "libtimsdata-2-21-0-4.so").write_bytes(b"so")
    (spx / "diatracer" / "diaTracer-2.2.1.jar").write_bytes(b"jar")
    t = spx / "tools"
    _exe(t / "sage" / "sage", FAKE_SAGE)
    _exe(t / "patch_diatracer_precursor.py", FAKE_PATCH)
    _exe(t / "fix_mzml_cvparams.py", FAKE_FIX)
    (w / "bench").mkdir()
    (w / "bench" / "human.fasta").write_text(">sp|P1|X\nPEPTIDEK\n")
    (w / "bench" / "human_decoy.fasta").write_text(">sp|P1|X\nPEPTIDEK\n>rev_sp|P1|X decoy\nKEDITPEP\n")
    (t / "sage_deiso.json").write_text(json.dumps({"database": {"fasta": str(w / "bench" / "human.fasta")}}))
    (t / "msfragger.params").write_text("database_name = %s\nnum_threads = 100\n" % (w / "bench" / "human_decoy.fasta"))
    (t / "MSFragger-4.4.1.jar").write_bytes(b"msf")
    for sid in "ABCDEFGH":
        _raw(w / "ceph" / "raw", sid)
    (w / "ceph" / "raw" / "run_A_diatracer.mzML").write_text("stale reference output")
    os.utime(w / "ceph" / "raw" / "run_A_diatracer.mzML", (1.6e9, 1.6e9))


def _queue(w: Path, ids: str, root="r1", **kw) -> dict:
    spx, raws = w / "ceph" / "spx", w / "ceph" / "raw"
    q = {"plan": "selftest", "node": "local", "nonce": os.urandom(3).hex(), "harness_sha256": sha256(SELF),
         "root": str(w / "scratch" / "kohlbach" / "corpus_v3_selftest" / root),
         "lock": str(w / "scratch" / "kohlbach" / ".corpus-queue.lock"), "search_workers": 2,
         "arm": "arm", "spx_root": str(spx), "diatracer_dir": str(spx / "diatracer"), "diatracer_jar": "diaTracer-2.2.1.jar",
         "jnatmp": str(w / "scratch" / "kohlbach" / "jnatmp"), "scratch_root": str(w / "scratch" / "kohlbach" / "corpus_v3_selftest"),
         "results_ceph": str(spx / "corpus_v3_selftest"), "report": "x.md", "threads": 100, "load_wait_min": 0.0,
         "n_samples": len(ids), "search_db_sha256": {"sage_fasta": sha256(w / "bench" / "human.fasta"),
                                                    "msfragger_db": sha256(w / "bench" / "human_decoy.fasta")},
         "tools": {"sage": str(spx / "tools" / "sage" / "sage"), "sage_config": str(spx / "tools" / "sage_deiso.json"),
                   "msfragger_jar": str(spx / "tools" / "MSFragger-4.4.1.jar"),
                   "msfragger_params": str(spx / "tools" / "msfragger.params"),
                   "patch": str(spx / "tools" / "patch_diatracer_precursor.py"), "fix": str(spx / "tools" / "fix_mzml_cvparams.py")},
         "samples": [{"id": sid, "raw": str(raws / ("run_%s.d" % sid)), "scheme": "HeLa test" if sid < "E" else "TNBC test",
                      "acq_min": 31.0, "database": "human", "label": sid, "pin": fingerprint(raws / ("run_%s.d" % sid))}
                     for sid in ids]}
    q.update(kw)
    return q


def _records(q: dict) -> dict:
    return {(r["id"], "pair" if r["kind"] == "pair" else "%s.%s" % (r["tool"], r["engine"])): r
            for r in node_status({"root": q["root"], "records_only": True})["records"]}


def _reg(q: dict) -> tuple:
    plan = {"queues": {"local": {"samples": [s["id"] for s in q["samples"]]}}, "diatracer_jar": q["diatracer_jar"],
            "threads": 100, "load_wait_min": 0}
    return plan, {"samples": {s["id"]: s for s in q["samples"]}}


def selftest(args=None) -> int:
    import contextlib, io
    C = Cases()

    def rt(q, recs, what):           # a guard firing inside a table render is a FAIL line, never a crashed selftest
        return C.ok("G-V13", "table renders: %s" % what, lambda: render_table("selftest", *_reg(q), recs)) or ("", -1, -1)
    saved = {k: globals()[k] for k in ("TIME", "POLL_S", "LOCK_RETRY_S", "MON_S", "load1", "mem_available_kb", "proc_snapshot")}
    env_saved = dict(os.environ)
    td = tempfile.mkdtemp(prefix="corpus-selftest-")
    w = Path(td)
    try:
        _world(w)
        def fake_snapshot():          # our tree at 4 cores; FAKE_FOREIGN_CORES more on the node
            t, f = time.monotonic(), float(os.environ.get("FAKE_FOREIGN_CORES", "0"))
            return {"t": t, "busy": int((4 + f) * CLK_TCK * t), "ours": int(4 * CLK_TCK * t),
                    "memavail_kb": 900, "memtotal_kb": 1000}
        globals().update(TIME=str(w / "bin" / "time"), POLL_S=0.01, LOCK_RETRY_S=0.3, MON_S=0.02, load1=lambda: 0.5,
                         mem_available_kb=lambda *a: 1000, proc_snapshot=fake_snapshot)
        os.environ.update(PATH=str(w / "bin") + os.pathsep + os.environ["PATH"], FAKE_ENVDUMP=str(w / "envdump.txt"),
                          FAKE_MSF_TIMES=str(w / "msf_times.log"), FAKE_MSF_SLEEP="0.3",
                          FAKE_NEIGHBOUR=str(w / "ceph" / "raw" / "run_A_diatracer.mzML"),
                          SPEXTRACTOR_PROBE="1", DIASPEXTRACTOR_PROBE="1", DIASPEXTRACT_PROBE="1", MALLOC_ARENA_MAX="2", LD_PRELOAD="",
                          GLIBC_TUNABLES="glibc.malloc.arena_max=2", OMP_NUM_THREADS="3", _JAVA_OPTIONS="-Xmx64m",
                          LD_LIBRARY_PATH="/nonexistent/inherited")
        neigh0 = neighbour(str(w / "ceph" / "raw" / "run_A.d"))

        # ---- G-V01 registry / plan
        import yaml
        q1 = _queue(w, "AB")
        plan = {k: q1[k] for k in PLAN_KEYS if k != "queues"}
        plan["queues"] = {"n1": {"samples": ["A"], "search_workers": 2}, "n2": {"samples": ["B"]}}
        reg = {"samples": {s["id"]: {k: s[k] for k in SAMPLE_KEYS} for s in q1["samples"]}, "sp": plan}

        def plan_file(mut):
            r = json.loads(json.dumps(reg))
            mut(r)
            p = w / ("reg%s.yaml" % os.urandom(2).hex())
            p.write_text(yaml.safe_dump(r))
            return p
        good = plan_file(lambda r: None)
        C.ok("G-V01", "valid plan loads", lambda: load_plan("sp", good))
        C.abort("G-V01", "sample in two queues", lambda: load_plan("sp", plan_file(
            lambda r: r["sp"]["queues"]["n2"]["samples"].append("A"))), "in queues")
        C.abort("G-V01", "unknown sample id", lambda: load_plan("sp", plan_file(
            lambda r: r["sp"]["queues"]["n2"]["samples"].append("ZZ"))), "not in samples.yaml")
        C.abort("G-V01", "pin key missing", lambda: load_plan("sp", plan_file(
            lambda r: r["samples"]["A"]["pin"].pop("acq_datetime"))), "pin.acq_datetime")
        C.abort("G-V01", "plan key typo", lambda: load_plan("sp", plan_file(
            lambda r: r["sp"].update(basline=1))), "unknown keys")
        C.abort("G-V01", "node without a queue", lambda: resolve_queue("sp", *load_plan("sp", good), "n9"), "no queue")
        dup = w / "dup.yaml"
        dup.write_text("samples:\n  A: {raw: /x/a.d}\n  A: {raw: /x/b.d}\n")
        C.abort("G-V01", "duplicate YAML key (safe_load keeps the last)", lambda: load_plan("sp", dup), "duplicate key")
        C.abort("G-V01", "two sample ids with one raw path", lambda: load_plan("sp", plan_file(
            lambda r: r["samples"]["B"].update(raw=r["samples"]["A"]["raw"]))), "share one raw")
        C.abort("G-V01", "sample count differs from n_samples", lambda: load_plan("sp", plan_file(
            lambda r: r["sp"].update(n_samples=3))), "n_samples")

        # ---- G-V02 identity
        fa = fingerprint(w / "ceph" / "raw" / "run_A.d", with_acq=True)
        C.check("G-V02", "acq_min read from Frames", fa["acq_min"] == 31.0, fa)
        C.abort("G-V02", "pin of another file", lambda: check_pin(fa, q1["samples"][1]["pin"], "raw A"), "tdf_bin_bytes")
        C.ok("G-V02", "own pin matches", lambda: check_pin(fa, q1["samples"][0]["pin"], "raw A"))
        C.abort("G-V02", "registry acq_min differs from the raw's Frames", lambda: stage(
            q1, dict(q1["samples"][0], acq_min=30.0), "t0"), "acq_min")
        remove_tree(Path(q1["root"]) / "stage")

        # ---- G-V03 arm environment
        env = C.ok("G-V03", "arm env builds", lambda: arm_env(q1)[0])
        C.check("G-V03", "probe/allocator/OpenMP/JVM-option variables stripped", env and not any(strip_var(k) for k in env)
                and env["LC_ALL"] == "C" and not {"GLIBC_TUNABLES", "OMP_NUM_THREADS", "_JAVA_OPTIONS"} & set(env),
                sorted(k for k in (env or {}) if strip_var(k)))
        C.check("G-V03", "inherited LD_LIBRARY_PATH dropped before env.sh", bool(env) and "LD_LIBRARY_PATH" not in env,
                (env or {}).get("LD_LIBRARY_PATH"))
        C.abort("G-V03", "env.sh missing", lambda: arm_env(dict(q1, arm="nope")), "env.sh missing")
        C.abort("G-V03", "env.sh exports a probe", lambda: arm_env(dict(q1, arm="arm_probe")), "itself exports")
        C.abort("G-V03", "env.sh exports an OpenMP knob", lambda: arm_env(dict(q1, arm="arm_omp")), "itself exports")
        C.abort("G-V03", "SPX_BIN outside the arm", lambda: arm_env(dict(q1, arm="arm_outside")), "outside the arm")
        qb = dict(q1, arm="arm_badprov")
        C.abort("G-V03", "provenance sha mismatch", lambda: arm_meta(arm_env(qb)[0], identity(qb, arm_env(qb)[0])), "provenance")
        qn = dict(q1, arm="arm_nohelp")
        C.abort("G-V03", "label unresolvable", lambda: arm_meta(arm_env(qn)[0], identity(qn, arm_env(qn)[0])), "label")
        C.check("G-V03", "label read from --help", arm_meta(env, identity(q1, env))["label"] == "DIAspeXtract 9.9.9")

        # ---- G-V04 binary drift
        ident0 = identity(q1, env)
        jar = w / "ceph" / "spx" / "diatracer" / "diaTracer-2.2.1.jar"
        jar.write_bytes(b"jar2")
        C.abort("G-V04", "jar changed across an arm", lambda: check_identity(q1, env, ident0, "during dt"), "changed")
        jar.write_bytes(b"jar")
        C.ok("G-V04", "unchanged identity", lambda: check_identity(q1, env, ident0, "during dt"))
        for what, f in (("Bruker library", w / "ceph" / "spx" / "diatracer" / "ext" / "bruker" / "libtimsdata-2-21-0-4.so"),
                        ("arm lib subdirectory", w / "ceph" / "spx" / "arm" / "lib" / "sub" / "libdep.so"),
                        ("JDK (java)", w / "bin" / "java")):
            orig_b = f.read_bytes()
            f.write_bytes(orig_b + b"\n# changed\n")
            C.abort("G-V04", "%s changed across an arm" % what, lambda: check_identity(q1, env, ident0, "during dt"), "changed")
            f.write_bytes(orig_b)
        cdep, ldep = "/ceph/x/lib/libgomp.so.1", "/usr/lib/x86_64-linux-gnu/libc.so.6"
        bid = lambda c, l: build_identity(dict(ident0, deps_sha256={cdep: c, ldep: l}))
        C.check("G-V11", "a node-local library difference keeps the build identity, a ceph one does not",
                bid("a", "a") == bid("a", "b") and bid("a", "a") != bid("b", "a"))
        C.check("G-V04", "identity carries the JDK version", ident0["java"]["major"] == 21, ident0.get("java"))

        # ---- G-V15 node environment
        C.abort("G-V15", "root under /home", lambda: node_run(dict(q1, root="/home/nobody/corpus")), "/home")
        C.abort("G-V15", "MemAvailable unreadable", lambda: saved["mem_available_kb"](str(w / "no_meminfo")), "MemAvailable")
        C.abort("G-V15", "jnatmp not writable", lambda: node_run(dict(q1, root=str(w / "scratch" / "kohlbach" / "v15"),
                                                                        jnatmp=str(w / "bench" / "human.fasta" / "x"))), "jnatmp")
        C.abort("G-V15", "python < 3.9 (cancel_futures)", lambda: preflight(q1, env, version_info=(3, 8, 10)), "python")
        _exe(w / "bin" / "notgnutime", "#!/bin/bash\nshift 3; exec \"$@\"\n")
        globals()["TIME"] = str(w / "bin" / "notgnutime")
        C.abort("G-V15", "TIME is not GNU time -v", lambda: preflight(q1, env), "GNU time")
        globals()["TIME"] = str(w / "bin" / "time")
        C.abort("G-V12", "a database differs from the plan pin", lambda: preflight(
            dict(q1, search_db_sha256=dict(q1["search_db_sha256"], msfragger_db="0" * 64)), env), "plan pin")
        pre = C.ok("G-V15", "preflight passes on the fake node", lambda: preflight(q1, env))
        C.check("G-V15", "preflight reads the JDK feature version", bool(pre) and pre["java"]["major"] == 21, pre and pre["java"])
        if sys.platform.startswith("linux"):
            C.check("G-V06", "proc_snapshot reads /proc on this Linux host", saved["proc_snapshot"]() is not None)
        qf = w / "crash-queue.json"
        qf.write_text(json.dumps({"plan": "crash"}))
        old_term, buf = signal.getsignal(signal.SIGTERM), io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                crc = node_main(["node-run", "--queue", str(qf)])
        except Exception as x:
            crc = "raised %s" % type(x).__name__
        finally:
            signal.signal(signal.SIGTERM, old_term)
        C.check("G-V15", "a crashing queue still ends with QUEUE_ABORTED, not only a traceback",
                crc == 2 and "QUEUE_ABORTED [CRASH]" in buf.getvalue(), crc)

        # ---- G-V08 result parsing units
        bad = w / "bad.log"
        bad.write_text("Command being timed: x\n")
        C.abort("G-V08", "time log unparseable", lambda: parse_time_log(bad, "G-V08"), "unparseable")
        mz = w / "u.mzML"
        mz.write_text('<spectrumList count="0000000042">\n</spectrumList></mzML>\n')
        C.check("G-V08", "zero-padded count parsed as integer", verify_mzml(mz, 0)["count"] == 42)
        C.abort("G-V08", "stale output", lambda: verify_mzml(mz, time.time() + 100), "stale")
        mz.write_text('<spectrumList count="42">\n')
        C.abort("G-V08", "unterminated output", lambda: verify_mzml(mz, 0), "not terminated")
        mz.write_text('<spectrumList count="0000">\n</mzML>\n')
        C.abort("G-V08", "count zero", lambda: verify_mzml(mz, 0), "count")
        C.abort("G-V07", "arm input outside the stage root", lambda: run_arm(
            q1, "spx", w / "ceph" / "raw" / "run_A.d", w / "armtmp", env, ident0, {}, q1["samples"][0], neigh0), "stage root")

        # ---- G-V10 counting units
        hdr = w / "hdr.tsv"
        hdr.write_text("psm_id\tpeptide\n1\tPEP\n")
        C.abort("G-V10", "Sage TSV without required columns", lambda: sage_peptides(hdr), "lacks")
        C.abort("G-V10", "MSFragger TSV without required columns", lambda: msf_peptides(hdr), "lacks")

        # ---- G-V06 load gate (flags, does not abort)
        g = load_gate(dict(q1, load_wait_min=0.0005), [])
        C.check("G-V06", "quiet node passes the gate", not g["contended"], g)
        globals()["load1"] = lambda: 99.0
        g = load_gate(dict(q1, load_wait_min=0.0005), [])
        C.check("G-V06", "loaded node flagged after the wait", g["contended"] and g["load"] == 99.0, g)
        globals()["load1"] = lambda: 0.5
        snap = lambda t, busy, ours, mem=900: {"t": t, "busy": busy, "ours": ours, "memavail_kb": mem, "memtotal_kb": 1000}
        k = CLK_TCK
        c = contention([snap(0, 0, 0), snap(30, 30 * k * 54, 30 * k * 4), snap(60, 60 * k * 54, 60 * k * 4)], 24.0)
        C.check("G-V06", "50 foreign cores during an arm flag it", c["contended"] and c["foreign_cores_peak60"] == 50.0, c)
        c = contention([snap(0, 0, 0), snap(30, 30 * k * 104, 30 * k * 104), snap(60, 60 * k * 104, 60 * k * 104)], 24.0)
        C.check("G-V06", "the arm's own 104 cores are never foreign", not c["contended"] and c["foreign_cores_peak60"] == 0.0, c)
        c = contention([snap(0, 0, 0), snap(10, 10 * k * 100, 0), snap(70, 10 * k * 100, 0), snap(130, 10 * k * 100, 0)], 24.0)
        C.check("G-V06", "a 10-s burst of 100 cores at the arm start counts as its 60-s mean (16.7)",
                not c["contended"] and c["foreign_cores_peak60"] == 16.7, c)
        c = contention([snap(0, 0, 0), snap(120, 0, 0, mem=10)], 24.0)
        C.check("G-V06", "MemAvailable below 5% during an arm flags it", c["contended"] and "MemAvailable" in c["why"][0], c)
        c = contention([snap(0, 0, 0)], 24.0)
        C.check("G-V06", "an unmeasured arm counts as contended", c["contended"] and not c["measured"], c)

        # ---- G-V07 node-local root; read-only method folder is staged and removable
        C.abort("G-V07", "root on ceph", lambda: node_run(dict(q1, root="/ceph/nobody/corpus")), "on ceph")
        staged, st = stage(q1, q1["samples"][0], "t1")
        C.check("G-V02", "staged copy matches its pin", st["fingerprint"] == q1["samples"][0]["pin"])
        remove_tree(Path(st["dir"]))
        C.check("G-V14", "staged copy with a r-x folder is deletable", not Path(st["dir"]).exists())

        # ---- run 1: happy queue, 2 samples, 2 search workers
        rc = C.ok("G-V11", "happy queue runs", lambda: node_run(q1))
        R = _records(q1)
        C.check("G-V08", "both pairs ok, rc 0", rc == 0 and all(R[s, "pair"]["status"] == "ok" for s in "AB"), rc)
        C.check("G-V09", "order alternates by queue index",
                R["A", "pair"]["order"] == ["dt", "spx"] and R["B", "pair"]["order"] == ["spx", "dt"])
        C.check("G-V10", "4 searches per sample ok (Sage 31, MSFragger 150)",
                all(R[s, "%s.%s" % (t, e)]["peptides"] == (31 if e == "sage" else 150) for s in "AB" for t in TOOLS for e in ENGINES))
        C.check("G-V14", "staged raw deleted", not any((Path(q1["root"]) / "stage").iterdir()))
        C.check("G-V14", "mzML deleted after both engines", not list(Path(q1["root"]).glob("runs/*/*/*/*.mzML")))
        C.check("G-V07", "ceph neighbour untouched", neighbour(str(w / "ceph" / "raw" / "run_A.d")) == neigh0)
        dump = (w / "envdump.txt").read_text().split()
        C.check("G-V03", "tool env had no probe/allocator variables",
                not any(strip_var(k) for k in dump)
                and {"SPEXTRACTOR_PROBE", "DIASPEXTRACTOR_PROBE", "DIASPEXTRACT_PROBE"} <= set(R["A", "pair"]["env_removed"]))
        spans = sorted(tuple(map(float, l.split())) for l in (w / "msf_times.log").read_text().splitlines())
        C.check("G-V10", "first MSFragger ran alone", len(spans) == 4 and all(spans[0][1] <= s[0] for s in spans[1:]), spans[:2])
        runs1 = {s: R[s, "pair"]["pair_run"] for s in "AB"}
        pa = R["A", "pair"]
        C.check("G-V06", "quiet arms not flagged; contention measured during each arm",
                all(pa["arms"][t]["during"]["measured"] and not pa["arms"][t]["during"]["contended"] for t in TOOLS),
                pa["arms"]["dt"].get("during"))
        C.check("G-V07", "records carry no raw path or basename (neutral staged name)",
                "run_A" not in json.dumps(pa) and pa["stage"]["name"] == "A.d" and "raw" not in pa["sample"], pa["stage"].get("name"))
        C.check("G-V08", "each arm synced and pre-warmed outside its timed window",
                all(isinstance(pa["arms"][t].get("sync_s"), float) and isinstance(pa["arms"][t].get("prewarm_s"), float) for t in TOOLS))
        C.check("G-V02", "acquisition length read from the raw", pa["stage"]["acq_min_read"] == 31.0)
        C.check("G-V10", "engines read every spectrum: patch 17/17, Sage 17, MSFragger Scans 42/42",
                R["A", "dt.sage"]["patched"] == 17 and R["A", "dt.sage"]["engine_spectra"] == 17
                and R["A", "spx.msfragger"]["engine_spectra"] == 42 == R["A", "spx.msfragger"]["mzml_count"])
        C.check("G-V10", "Sage target-only peptides recorded beside target+decoy",
                R["A", "dt.sage"]["peptides"] == 31 and R["A", "dt.sage"]["target_peptides"] == 30)
        ov = search_overlaps(list(R.values()))
        md1 = rt(q1, list(R.values()), "run 1")[0]
        C.check("G-V13", "overlapping searches are marked, the lone first MSFragger unit is not",
                len(ov) >= 2 and not {("A", "dt", "sage"), ("A", "dt", "msfragger")} & ov and "†" in md1, sorted(ov))

        # ---- run 2: resume changes nothing
        node_run(dict(q1, nonce="resume"))
        R = _records(q1)
        C.check("G-V11", "resume skips verified pairs and searches",
                {s: R[s, "pair"]["pair_run"] for s in "AB"} == runs1 and len((w / "msf_times.log").read_text().splitlines()) == 4)

        # ---- review F9: an output whose two searches are done, left behind by a killed runner, is swept
        left = Path(R["A", "pair"]["arms"]["dt"]["output"]["path"])
        left.write_text("left behind between the second ok record and the unlink")
        node_run(dict(q1, nonce="sweep"))
        C.check("G-V14", "a finished output left behind is deleted by the next launch", not left.exists())

        # ---- review F3: records count only for the code (and thread count) that measured them
        ctx1 = {"ident": identity(q1, env), "tools_sha": install_tools(q1)["sha256"], "measure": measure_sha256(), "threads": 100}
        C.check("G-V11", "a pair record of another thread count is not adopted",
                pair_done(R["A", "pair"], q1["samples"][0], ctx1, Path(q1["root"]))
                and not pair_done(R["A", "pair"], q1["samples"][0], dict(ctx1, threads=99), Path(q1["root"])))
        rb = read_json(rec_path(q1["root"], "B", "pair"))
        rb["measure_sha256"]["pair"] = "0" * 64
        write_json(rec_path(q1["root"], "B", "pair"), rb)
        ra = read_json(rec_path(q1["root"], "A", "dt", "sage"))
        ra["measure_sha256"]["score"], ra["peptides"] = "0" * 64, 7
        write_json(rec_path(q1["root"], "A", "dt", "sage"), ra)
        n_msf = len((w / "msf_times.log").read_text().splitlines())
        node_run(dict(q1, nonce="measure"))
        R = _records(q1)
        C.check("G-V11", "a pair measured by other code re-runs; the other pair is kept",
                R["B", "pair"]["pair_run"] != runs1["B"] and R["A", "pair"]["pair_run"] == runs1["A"])
        C.check("G-V11", "a search counted by another rule is re-counted from its TSV; no engine re-runs for it",
                R["A", "dt.sage"]["peptides"] == 31 and bool(R["A", "dt.sage"].get("rescored"))
                and len((w / "msf_times.log").read_text().splitlines()) == n_msf + 2, R["A", "dt.sage"].get("rescored"))
        ra2, pa2 = R["A", "dt.sage"], R["A", "pair"]
        C.check("G-V11", "a search record of another peptide rule is not done (if its TSV is gone, nothing re-counts it)",
                search_done(ra2, pa2, ctx1)
                and not search_done(dict(ra2, measure_sha256=dict(ra2["measure_sha256"], score="0" * 64)), pa2, ctx1))
        runs1 = {s: R[s, "pair"]["pair_run"] for s in "AB"}

        # ---- table
        plan_t, reg_t = _reg(q1)
        md, inc, tot = rt(q1, list(R.values()), "after resume and re-count")
        C.check("G-V13", "table renders complete rows, no zero cells",
                inc == 0 and tot == 2 and "DIAspeXtract 9.9.9" in md and "| 0 |" not in md and "**corpus** | 2 |" in md, (inc, tot))
        C.check("G-V13", "table names the rules: target+decoy with target-only totals, KiB, unflagged-row ratio",
                all(x in md for x in ("**target+decoy**", "Target-only peptides", "KiB", "unflagged rows", "Measurement code")))
        (w / "table.md").write_text(md)

        def mutated(fn):
            recs = json.loads(json.dumps(list(R.values())))
            fn({(r["id"], r.get("tool", "pair"), r.get("engine", "pair")): r for r in recs})
            return lambda: render_table("selftest", plan_t, reg_t, recs)
        C.abort("G-V13", "two binaries in one table", mutated(lambda m: m["B", "pair", "pair"]["identity"].update(binary_sha256="x")), "more than one")
        C.abort("G-V13", "ok search with 0 peptides", mutated(lambda m: m["A", "spx", "sage"].update(peptides=0)), "0 peptides")
        C.abort("G-V13", "pair arms on two hosts", mutated(lambda m: m["A", "pair", "pair"]["arms"]["dt"].update(host="elsewhere")), "arms on")
        C.abort("G-V13", "record pin differs from registry", mutated(lambda m: m["A", "pair", "pair"]["sample"]["pin"].update(tdf_bytes=1)), "pin")
        C.abort("G-V13", "pairs measured by different harness code", mutated(
            lambda m: m["B", "pair", "pair"]["measure_sha256"].update(pair="x")), "harness code")
        C.abort("G-V13", "searches counted by different rules", mutated(
            lambda m: m["B", "spx", "msfragger"]["measure_sha256"].update(score="x")), "harness code")
        C.abort("G-V13", "two JDK feature versions", mutated(
            lambda m: m["B", "pair", "pair"]["identity"]["java"].update(major=11)), "Java feature")

        # ---- run 3: first-arm failure and a wrong pin, next to done samples
        os.environ["FAKE_DT_FAIL"] = "/C.d"
        q3 = _queue(w, "ABCD")
        q3["samples"][3]["pin"]["instrument_serial"] = "WRONG"
        rc = node_run(q3)
        del os.environ["FAKE_DT_FAIL"]
        R = _records(q3)
        C.check("G-V08", "failed dt arm fails the pair", rc == 1 and R["C", "pair"]["guard"] == "G-V08", R["C", "pair"].get("message"))
        C.check("G-V09", "the other arm never ran", list(R["C", "pair"]["arms"]) == ["dt"]
                and not list(Path(q3["root"]).glob("runs/C/*/spx")))
        C.check("G-V02", "wrong pin fails the pair", R["D", "pair"]["guard"] == "G-V02", R["D", "pair"].get("message"))
        C.check("G-V11", "done samples untouched", {s: R[s, "pair"]["pair_run"] for s in "AB"} == runs1)
        md, inc, tot = rt(q3, list(R.values()), "failed rows")
        C.check("G-V13", "failed rows render FAILED, never 0", inc == 2 and "FAILED G-V08" in md and "FAILED G-V02" in md, inc)

        # ---- run 4: search failures, signal, miscount
        os.environ.update(FAKE_SAGE_ZERO="/runs/E/", FAKE_PATCH_ZERO="/runs/F/", FAKE_MSF_NOTOTAL="/runs/F/",
                          FAKE_SIGNAL_FOR="/G.d", FAKE_SPX_MISCOUNT="/H.d", FAKE_PATCH_SHORT="/runs/E/",
                          FAKE_MSF_SCANS_SHORT="/runs/E/&dt_msfragger", FAKE_SAGE_SHORT="/runs/F/&/spx/")
        q4 = _queue(w, "EFGH", root="r4", search_workers=1)
        node_run(q4)
        for k in ("FAKE_SAGE_ZERO", "FAKE_PATCH_ZERO", "FAKE_MSF_NOTOTAL", "FAKE_SIGNAL_FOR", "FAKE_SPX_MISCOUNT",
                  "FAKE_PATCH_SHORT", "FAKE_MSF_SCANS_SHORT", "FAKE_SAGE_SHORT"):
            del os.environ[k]
        R = _records(q4)
        msg = lambda k: (R[k].get("guard"), R[k].get("message", ""))
        C.check("G-V10", "0 peptides fails the cell", msg(("E", "spx.sage"))[0] == "G-V10" and "0 peptides" in msg(("E", "spx.sage"))[1])
        C.check("G-V10", "unpatched reference fails Sage", "no selected ion" in msg(("F", "dt.sage"))[1])
        C.check("G-V10", "MSFragger without TOTAL TIME fails", "TOTAL TIME" in msg(("F", "spx.msfragger"))[1])
        C.check("G-V08", "signal with exit 0 fails the arm", "signal=7" in msg(("G", "pair"))[1])
        C.check("G-V08", "log count != spectrumList count", "log count" in msg(("H", "pair"))[1])
        C.check("G-V10", "patch short of the spectrum count fails the Sage cell", "patched 16 of 17" in msg(("E", "dt.sage"))[1],
                msg(("E", "dt.sage")))
        C.check("G-V10", "MSFragger Scans short of the spectrum count fails the cell", "Scans = 16 of 17" in msg(("E", "dt.msfragger"))[1],
                msg(("E", "dt.msfragger")))
        C.check("G-V10", "Sage searching a third of the spectra fails the cell", "14 spectra of 42" in msg(("F", "spx.sage"))[1],
                msg(("F", "spx.sage")))
        C.check("G-V14", "mzML kept while a search failed", Path(R["E", "pair"]["arms"]["spx"]["output"]["path"]).is_file())
        pe = Path(R["E", "pair"]["arms"]["spx"]["output"]["path"])
        with open(pe, "ab") as f:
            f.write(b" ")
        tools4, env4 = install_tools(q4), arm_env(q4)[0]
        run_search(q4, q4["samples"][0], "spx", "sage", R["E", "pair"], tools4, env4)
        C.check("G-V11", "changed extractor output refused", _records(q4)["E", "spx.sage"]["guard"] == "G-V11")
        node_run(dict(q4, nonce="resume4"))
        R2 = _records(q4)
        C.check("G-V11", "changed output re-runs the pair", R2["E", "pair"]["pair_run"] != R["E", "pair"]["pair_run"])
        C.check("G-V11", "failed searches re-run on a kept output", R2["F", "pair"]["pair_run"] == R["F", "pair"]["pair_run"]
                and all(R2["F", c]["status"] == "ok" for c in ("dt.sage", "dt.msfragger", "spx.msfragger")))
        C.check("G-V11", "every cell ok after resume", all(r["status"] == "ok" for r in R2.values()) and len(R2) == 20, len(R2))

        # ---- review F8: a failed first MSFragger built no .pepindex, so the next MSFragger unit also runs alone
        os.environ.update(FAKE_MSF_NOTOTAL="/runs/A/&dt_msfragger", FAKE_MSF_TIMES=str(w / "msf_times7.log"))
        q7 = _queue(w, "AB", root="r7", search_workers=2)
        node_run(q7)
        os.environ["FAKE_MSF_TIMES"] = str(w / "msf_times.log")
        del os.environ["FAKE_MSF_NOTOTAL"]
        sp7 = sorted(tuple(map(float, l.split())) for l in (w / "msf_times7.log").read_text().splitlines())
        R7 = _records(q7)
        C.check("G-V10", "after a failed first MSFragger the next MSFragger still runs alone",
                R7["A", "dt.msfragger"]["status"] == "failed" and len(sp7) == 4 and sp7[0][1] <= sp7[1][0]
                and sp7[1][1] <= min(sp7[2][0], sp7[3][0]), sp7)
        st7 = node_status({"root": q7["root"], "lock": q7["lock"]})
        C.check("G-V14", "status lists the mzML kept for the failed search",
                any(x.endswith("A_diatracer.mzML") for x in st7["mzml_left"]), st7["mzml_left"])
        pr = node_purge({"root": q7["root"], "lock": q7["lock"]})
        C.check("G-V14", "purge deletes the kept mzMLs after the run", bool(pr["removed"]) and not pr["left"], pr)

        # ---- review F2: contention that starts after the gate flags the row
        os.environ["FAKE_FOREIGN_CORES"] = "50"
        q9 = _queue(w, "A", root="r9")
        node_run(q9)
        del os.environ["FAKE_FOREIGN_CORES"]
        R9 = _records(q9)
        md9 = rt(q9, list(R9.values()), "contended during arms")[0]
        g9 = R9["A", "pair"]["gate"]         # its load is quiet; `busy` may see a parallel selftest's fake MSFragger
        C.check("G-V06", "50 foreign cores during both arms flag the row although the gate load was quiet",
                g9["load"] <= g9["load_max"] and all(R9["A", "pair"]["arms"][t]["during"]["contended"] for t in TOOLS)
                and "during diaTracer-2.2.1: foreign CPU" in md9 and "during DIAspeXtract 9.9.9: foreign CPU" in md9
                and "| 1/1 |" in md9, R9["A", "pair"]["arms"]["dt"].get("during"))

        # ---- run 5: a new binary re-runs everything
        fake = w / "ceph" / "spx" / "arm" / "bin" / "fakespx"
        fake.write_text(fake.read_text() + "# rebuilt\n")
        _prov(w / "ceph" / "spx" / "arm")
        node_run(dict(q1, nonce="newbin"))
        R = _records(q1)
        C.check("G-V11", "new binary re-runs pairs and searches", all(R[s, "pair"]["pair_run"] != runs1[s] for s in "AB")
                and all(R[s, c]["pair_run"] == R[s, "pair"]["pair_run"] and R[s, c]["status"] == "ok"
                        for s in "AB" for c in ("dt.sage", "spx.msfragger")))
        C.check("G-V14", "queue root is private (0700)", (os.stat(q1["root"]).st_mode & 0o777) == 0o700,
                oct(os.stat(q1["root"]).st_mode & 0o777))

        # ---- run 5b: the node guard test itself, on the fake world (same code as on a real node)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            grc = node_guardtest(dict(q1, nonce="gt", plan="selftest"))
        gfail = [l.split(" GT ", 1)[1] for l in buf.getvalue().splitlines() if " GT FAIL " in l]
        C.check("GT", "node guardtest passes on the fake world", grc == 0 and not gfail and "GUARDTEST_DONE" in buf.getvalue(),
                gfail[:2] or buf.getvalue()[-160:])
        C.abort("G-V01", "guardtest refused for a non-selftest plan", lambda: _guardtest(dict(q1, plan="corpus_v3"), Path(q1["root"])),
                "selftest plan only")

        # ---- SIGTERM during an arm (the node-run handler raises SystemExit): failed/KILLED, stage cleaned
        orig_run_logged, env1 = globals()["run_logged"], arm_env(q1)[0]
        globals()["run_logged"] = lambda *a, **k: sys.exit(143)
        try:
            run_pair(q1, 0, q1["samples"][0], env1, identity(q1, env1), {"label": "x", "provenance": []}, [], [])
        except SystemExit:
            pass
        finally:
            globals()["run_logged"] = orig_run_logged
        rk = read_json(Path(q1["root"]) / "records" / "A.pair.json")
        C.check("G-V14", "SIGTERM mid-arm: record failed KILLED, stage deleted", rk["status"] == "failed" and rk["guard"] == "KILLED"
                and not any((Path(q1["root"]) / "stage").iterdir()), (rk["status"], rk.get("guard")))
        node_run(dict(q1, nonce="after-kill"))          # the killed attempt re-runs whole on the next launch
        C.check("G-V11", "killed pair re-runs on the next launch", _records(q1)["A", "pair"]["status"] == "ok")

        # ---- G-V07 diaTracer writing beside the ceph raw
        os.environ["FAKE_DT_CEPH"] = "/A.d"
        C.abort("G-V07", "ceph neighbour overwritten", lambda: node_run(_queue(w, "A", root="r6")), "neighbour")
        del os.environ["FAKE_DT_CEPH"]
        C.check("G-V14", "stage cleaned after a queue abort", not any((w / "scratch" / "kohlbach" / "corpus_v3_selftest" / "r6" / "stage").iterdir()))

        # ---- G-V12 search inputs
        cfg = Path(q1["tools"]["sage_config"])
        orig = cfg.read_text()
        cfg.write_text(orig + " ")
        C.abort("G-V12", "tool source changed since launch", lambda: install_tools(q1), "differs")
        cfg.write_text(orig)
        tools1 = install_tools(q1)
        fasta = w / "bench" / "human.fasta"
        fasta.write_text(fasta.read_text() + ">sp|P2|Y\nAAAK\n")
        C.abort("G-V12", "FASTA changed during the run", lambda: check_fasta(tools1), "changed during")

        # ---- G-V05 exclusivity
        lf = open(q1["lock"], "a+")
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        C.abort("G-V05", "node lock held by another queue", lambda: node_run(dict(q1, nonce="second")), "holds")
        # ---- G-V14 collect
        C.abort("G-V14", "collect while the queue runs", lambda: node_collect(
            {"root": q1["root"], "lock": q1["lock"], "dest": q1["results_ceph"] + "/local"}), "still holds")
        lf.close()
        sh = open(q1["lock"], "a+")
        fcntl.flock(sh, fcntl.LOCK_SH | fcntl.LOCK_NB)             # another status/collect probe in flight
        C.check("G-V05", "a concurrent read-only probe is not mistaken for a queue", lock_state(q1["lock"])[0] is False)
        import threading
        threading.Timer(0.1, sh.close).start()                       # the probe ends inside the retry window
        C.ok("G-V05", "a runner starting during a probe waits it out", lambda: with_node_lock(
            dict(q1, nonce="probe"), "queue", lambda: 0))
        C.abort("G-V14", "collect into a non-results dir", lambda: node_collect(
            {"root": q1["root"], "lock": q1["lock"], "dest": str(w / "ceph" / "spx" / "arm" / "local")}), "not a corpus_v3")
        (Path(q1["root"]) / "queue-selftest.json").write_text(json.dumps({"samples": [{"raw": "/ceph/raw/run_A.d"}]}))
        res = C.ok("G-V14", "collect copies records, not mzML/stage/tools", lambda: node_collect(
            {"root": q1["root"], "lock": q1["lock"], "dest": q1["results_ceph"] + "/local"}))
        dest = Path(q1["results_ceph"]) / "local"
        C.check("G-V14", "collected tree has records and no mzML", res and (dest / "records").is_dir()
                and not list(dest.rglob("*.mzML")) and not (dest / "tools").exists())
        C.check("G-V14", "collected tree is private and carries no queue file (raw paths)",
                not list(dest.glob("queue-*.json"))
                and all((p.lstat().st_mode & 0o077) == 0 for p in [dest] + list(dest.rglob("*")) if not p.is_symlink()))
        C.abort("G-V05", "launch refused when our tools run", lambda: check_launch(
            {"error": None, "lock_held": False, "busy": ["MSFragger-4\\.4\\.[1]\\.jar: 123"]}, "n1"), "already running")
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "MSFragger-4.4.1.jar"])
        try:
            time.sleep(0.3)
            C.check("G-V05", "bracketed pgrep sees a running MSFragger", any(str(sleeper.pid) in h for h in busy(BUSY_FIXED)))
        finally:
            sleeper.kill()

        # ---- dry-run prints every command
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            dry_run(q3)
        out = buf.getvalue()
        want = ["-Xmx400G", " ".join(DT_PARAMS), "-threads 100", "-Xmx200G", SAGE_TELEMETRY, "LD_LIBRARY_PATH=./ext/bruker",
                "patch_diatracer_precursor.py", "fix_mzml_cvparams.py", "copy data only", "rm -rf", "cat "]
        C.check("DRY", "dry-run prints every command", all(x in out for x in want) and out.count("## ") == 4,
                [x for x in want if x not in out])
    finally:
        globals().update(saved)
        os.environ.clear()
        os.environ.update(env_saved)
    missing = sorted({"G-V%02d" % i for i in range(1, 16)} - C.fired)
    if missing:
        C.results.append(("FAIL", "ALL", "every guard fired at least once", "never fired: %s" % missing))
    width = max(len(r[2]) for r in C.results)
    for st, g, name, detail in C.results:
        print("%-4s %-6s %-*s  %s" % (st, g, width, name, detail))
    nfail = sum(1 for r in C.results if r[0] == "FAIL")
    print("\n%d/%d cases pass%s" % (len(C.results) - nfail, len(C.results),
                                    ", %d FAIL (world kept for inspection: %s)" % (nfail, td) if nfail else ""))
    if not nfail:
        remove_tree(Path(td))
    return 1 if nfail else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1].startswith("node-"):
        return node_main(sys.argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    for name in ("pin", "dry-run", "launch", "status", "collect", "table", "guardtest", "preflight", "purge"):
        p = sub.add_parser(name)
        p.add_argument("--plan", default="corpus_v3_selftest" if name == "guardtest" else "corpus_v3")
        p.add_argument("--node", required=name in ("pin", "dry-run", "launch", "collect", "guardtest", "purge"))
        if name == "guardtest":
            p.add_argument("--show", action="store_true", help="print the latest RESULTS.txt instead of launching")
        if name == "pin":
            p.add_argument("--ids", help="comma-separated sample ids (default: every sample with a raw path)")
        if name == "dry-run":
            p.add_argument("--local", action="store_true", help="print here, without ssh (SPX_BIN may be unresolved)")
        if name == "table":
            p.add_argument("--source", choices=("scratch", "ceph"), default="scratch")
            p.add_argument("--out", help="default: the plan's report path under the repository")
    args = ap.parse_args()
    fn = {"selftest": selftest, "pin": cmd_pin, "dry-run": cmd_dry_run, "launch": cmd_launch,
          "status": cmd_status, "collect": cmd_collect, "table": cmd_table, "guardtest": cmd_guardtest,
          "preflight": cmd_preflight, "purge": cmd_purge}[args.cmd]
    try:
        return fn(args)
    except Abort as a:
        print("\nABORT %s\n" % a, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
