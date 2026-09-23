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
Extended plans (optional plan keys `cells`, `entrapment`; harness/CORPUS.md "Extra cells"):
  G-V16 cell result: exit!=0, signal, wall cap passed or MemAvailable under the floor for MEM_FLOOR_SAMPLES
        samples (the tool's session is killed), unparseable time log, output missing/stale/unterminated, count
        <=0, the tool's count line missing/different, its finalisation line missing (the tools get a private
        TMPDIR; a crash inside a cell fails that cell as CRASH)
  G-V17 re-encode: tool failed, a numpress term left, a spectrum without an m/z array or not m/z-sorted or
        undecodable, a precursor value not a number, raw m/z arrays undecodable, spectrum count changed,
        RT/selected ion/charge/1/K0/isolation target values changed, any spectrum's m/z values changed, a
        spectrum without MS:1000744
  G-V18 no-op cell (FLAG): a cell's content digest equals the one of the cell it must differ from, or the
        check could not run
  G-V19 charge strata: a result TSV without charge/score columns or with a non-integer charge, a split that
        does not add up to the cell's count, an entrapment FASTA without ENTRAP_ peptides, 0 target peptides
        in the entrapment search
  (G-V03 for cells also: OPENMS_DATA_PATH not the arm's data tree, the provenance's data tree hash differs)
  Optional plan key `engines` (a subset of sage/msfragger, e.g. a Sage-only plan; it makes a plan extended):
  G-V01 refuses a value that is not a non-empty, strict subset list of those names in that order; G-V13 refuses
  a table whose ok search records name an engine (or the entrapment search) the plan does not run.
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

# ---- Extended plans: optional plan keys `cells` (extra extractors run after the reference pair, on the same staged
# copy) and `entrapment` (a third search per output). A plan without either is the two-extractor pair above: the same
# functions run and measure it, and its three measurement hashes do not move (selftest pins them). `engines` (a subset
# of ENGINES) restricts which searches run; it changes no measured function, only which search cells exist.
OPTIONAL_PLAN_KEYS = {"cells", "entrapment", "engines"}
CELL_KEYS = {"kind", "arm", "args", "wall_cap_h"}                 # plus optional differs_from
CELL_NAME = r"[a-z][a-z0-9_]{0,23}"
# One kind so far: diaWeaver (alhigaylan/diaWeaver, branch diaWeaver-2). Its env.sh exports `bin` and points
# OPENMS_DATA_PATH at the arm's `data` tree (the files the tool reads at run time); the arm's `prov` file lists
# `sha256_published:` for every published file and `<data_prov>=` for the data tree; the tool writes ONE
# <out dir>/pseudo_spectra.mzML, logs "Wrote N pseudo spectra." and, after its RT sort and numpress rewrite, "Done. Output".
CELL_KINDS = {"dwv": {"bin": "DWV_BIN", "prov": "PROVENANCE", "out": "pseudo_spectra.mzML", "log": "dwv.log",
                      "count": rb"Wrote (\d+) pseudo spectra", "done": b"Done. Output",
                      "data": "share/OpenMS", "data_prov": "share_OpenMS_tree_sha256"}}
# Re-encode of a cell output before any search (G-V17). The ONLY place these option strings live. The fork's FileFilter
# (7ed1169, src/topp/FileFilter.cpp:417/430-447/1011-1013): `-sort` = sortSpectra(true), spectra by RT and every peak
# list by m/z with its data arrays; numpress defaults to none, zlib to false, m/z to 64 bit. It sits beside the cell bin.
REENCODE = ("FileFilter", ("-sort",))
NUMPRESS_CV = (b"MS:1002312", b"MS:1002313", b"MS:1002314", b"MS:1002746", b"MS:1002747", b"MS:1002748")
NUMPRESS_LINEAR = (b"MS:1002312", b"MS:1002746")    # linear, linear + zlib: diaWeaver's m/z encoding, decoded by mzml_scan
MEM_FLOOR_SAMPLES = 3     # a cell is killed only when MemAvailable stays under MEM_FLOOR for this many MON_S samples
PREC_CV = (b"MS:1000016", b"MS:1000744", b"MS:1000041", b"MS:1002815", b"MS:1000827")   # RT, sel. m/z, z, 1/K0, target
CELL_TOOL_KEYS = ("digest",)                        # bench/semantic_digest.py, for plans with cells
ENTRAP_TOOL_KEYS = ("sage_entrap", "entrapment")    # Sage config naming the target+entrapment FASTA; bench/entrapment.py
ENTRAP_DB, ENTRAP_TAG = "entrap_fasta", "ENTRAP_"
STRATA = (("all", 0, 999), ("z1", 1, 1), ("z2p", 2, 999))   # charge strata (inclusive); z1 + z2p must partition all
# What an extended plan stages (patient-data rule of the diaWeaver stage): the two files every extractor reads. A raw
# .d also carries sample and acquisition metadata (SampleInfo.xml, HyStar files, method folders) that no arm needs.
STAGE_FILES = ("analysis.tdf", "analysis.tdf_bin")


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


def ldd_deps(env: dict, arm_dir: str, binary=None) -> dict:
    """Shared objects SPX_BIN (or `binary`) resolves under the arm environment (DT_NEEDED closure) outside the arm
    directory, with sha256 (review F6): $SPX/lib and another project's conda env sit on LD_LIBRARY_PATH, and the
    binary's RUNPATH points into a node-local OpenMS build tree that only LD_LIBRARY_PATH overrides."""
    binary = binary or env["SPX_BIN"]
    try:
        r = subprocess.run(["ldd", binary], env=env, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        if sys.platform.startswith("linux"):
            die_queue("G-V15", "ldd not found: the extractor's libraries cannot be pinned")
        return {}
    out = r.stdout + r.stderr
    if "not a dynamic executable" in out:          # a script (guardtest/selftest wrapper arm) resolves nothing
        return {}
    if r.returncode != 0 or "not found" in out:
        die_queue("G-V03", "ldd %s failed or left libraries unresolved: %s" % (binary, out.strip()[-400:]))
    found = re.findall(r"=>\s+(/\S+)\s+\(0x", out) + re.findall(r"^\s*(/\S+)\s+\(0x", out, re.M)
    deps = {}
    for p in sorted({os.path.realpath(x) for x in found}):
        if p.startswith(arm_dir + os.sep):
            continue                                    # hashed as the arm's lib/**
        if not p.startswith(LIB_ROOTS):
            die_queue("G-V03", "%s resolves %s outside the arm, /ceph and the system library directories "
                               "(a node-local build tree?)" % (os.path.basename(binary), p))
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


def tree_sha256(d: Path) -> dict:
    return {str(p.relative_to(d)): sha256(p) for p in sorted(d.rglob("*")) if p.is_file()} if d.is_dir() else {}


def identity(q: dict, env: dict) -> dict:
    arm = os.path.realpath(Path(q["spx_root"]) / q["arm"])
    dt = Path(q["diatracer_dir"])
    out = {"binary": env["SPX_BIN"], "binary_sha256": sha256(env["SPX_BIN"]), "lib_sha256": tree_sha256(Path(arm) / "lib"),
           "deps_sha256": ldd_deps(env, arm), "jar": q["diatracer_jar"],
           "jar_sha256": sha256(dt / q["diatracer_jar"]), "bruker_sha256": tree_sha256(dt / "ext" / "bruker"),
           "java": java_info(env)}
    if cells(q):
        out["cells"] = cells_identity(q)
    return out


def build_identity(ident: dict) -> dict:
    """What must match across records (G-V11 resume, G-V13 table): the build and every ceph-resident library it
    loads, and for an extended plan each cell's build (binary, lib/**, re-encode tool, ceph libraries). Node-local
    system libraries and the JDK's files may differ between nodes: recorded, and compared within a queue only
    (G-V04). The JDK feature version is compared on its own (java_major)."""
    ceph = lambda deps: {p: h for p, h in (deps or {}).items() if p.startswith("/ceph/")}
    out = {"binary_sha256": ident.get("binary_sha256"), "lib_sha256": ident.get("lib_sha256"),
           "deps_sha256": ceph(ident.get("deps_sha256")),
           "jar_sha256": ident.get("jar_sha256"), "bruker_sha256": ident.get("bruker_sha256")}
    if ident.get("cells"):
        out["cells"] = {n: {"binary_sha256": c["binary_sha256"], "lib_sha256": c["lib_sha256"],
                            "reencode_sha256": c["reencode_sha256"], "deps_sha256": ceph(c["deps_sha256"]),
                            "data_tree_sha256": c.get("data_tree_sha256"), "env_sha256": c.get("env_sha256")}
                        for n, c in ident["cells"].items()}
    return out


def java_major(ident: dict):
    return (ident.get("java") or {}).get("major")


def check_identity(q: dict, env: dict, ident0: dict, when: str) -> None:
    now = identity(q, env)
    if now != ident0:
        die_queue("G-V04", "binary/lib/jar changed %s (republished under a running queue?)" % when)


def tool_label(binary: str, env: dict) -> str:
    r = subprocess.run([binary, "--help"], env=env, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=300)
    name = re.search(r"^(\S+) -- ", r.stdout + r.stderr, re.M)
    ver = re.search(r"^Version: (\S+)", r.stdout + r.stderr, re.M)
    if not (name and ver):
        die_queue("G-V03", "tool label unresolvable from %s --help" % binary)
    return "%s %s" % (name.group(1), ver.group(1))


def arm_meta(env: dict, ident0: dict) -> dict:
    """Tool label from the binary itself; provenance from the publish step. Nothing hard-coded."""
    prov = Path(env["SPX_BIN"] + ".provenance")
    if not prov.is_file():
        die_queue("G-V03", "provenance missing: %s" % prov)
    lines = prov.read_text().splitlines()
    ps = [x.split("=", 1)[1] for x in lines if x.startswith("binary_sha256=")]
    if not ps or ps[0] != ident0["binary_sha256"]:
        die_queue("G-V03", "provenance binary_sha256 %s != sha256(SPX_BIN) %s" % (ps[:1], ident0["binary_sha256"][:16]))
    return {"label": tool_label(env["SPX_BIN"], env), "provenance": lines}


# ------------------------------------------------------------------------------- node: extra cells (extended plans)
def cells(q: dict) -> dict:
    return q.get("cells") or {}


def extended(q: dict) -> bool:
    """`engines` makes a plan extended too: the plain queue (run_pair, phase 2) always runs both engines."""
    return bool(cells(q) or q.get("entrapment") or "engines" in q)


def q_tools(q: dict) -> tuple:
    return TOOLS + tuple(cells(q))


def q_engines(q: dict) -> tuple:
    return tuple(q.get("engines") or ENGINES) + (("entrap",) if q.get("entrapment") else ())


def cell_env(q: dict, name: str) -> dict:
    """A cell's env.sh on the base arm_env uses (G-V03): the same variables stripped, the kind's binary variable
    set, executable and inside the cell arm, with the re-encode tool beside it."""
    c = q["cells"][name]
    var = CELL_KINDS[c["kind"]]["bin"]
    env_sh = Path(q["spx_root"]) / c["arm"] / "env.sh"
    if not env_sh.is_file():
        die_queue("G-V03", "cell %s: env.sh missing: %s" % (name, env_sh))
    base = {k: v for k, v in os.environ.items() if not (strip_var(k) or k in INHERIT_DROP)}
    r = subprocess.run(["bash", "-c", 'source "$1" >&2 && env -0', "_", str(env_sh)], env=base, capture_output=True)
    if r.returncode != 0:
        die_queue("G-V03", "cell %s: sourcing %s failed: %s" % (name, env_sh, r.stderr.decode(errors="replace")[-300:]))
    env = dict(kv.split("=", 1) for kv in r.stdout.decode(errors="replace").split("\0") if "=" in kv)
    bad = sorted(k for k in env if strip_var(k))
    if bad:
        die_queue("G-V03", "cell %s: %s itself exports %s: a configured arm, not the defaults" % (name, env_sh, bad))
    arm_dir = os.path.realpath(env_sh.parent)
    for what, b in ((var, env.get(var, "")), (REENCODE[0], str(Path(env.get(var) or "/nonexistent").parent / REENCODE[0]))):
        if not b or not os.path.isfile(b) or not os.access(b, os.X_OK):
            die_queue("G-V03", "cell %s: %s unset or not an executable file: %r" % (name, what, b))
        if not os.path.realpath(b).startswith(arm_dir + os.sep):
            die_queue("G-V03", "cell %s: %s %s is outside the cell arm %s" % (name, what, b, arm_dir))
    data = env.get("OPENMS_DATA_PATH", "")
    if not data or os.path.realpath(data) != os.path.join(arm_dir, CELL_KINDS[c["kind"]]["data"]):
        die_queue("G-V03", "cell %s: OPENMS_DATA_PATH %r is not the cell arm's %s: the tool would read unpinned data files"
                  % (name, data, CELL_KINDS[c["kind"]]["data"]))
    env.update(LC_ALL="C", TMPDIR=q["jnatmp"])      # run_cell gives the tools a private per-cell TMPDIR
    return env


def data_tree_sha256(d: Path):
    """The publish step's `cd d && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum` (byte order):
    the value an arm's provenance records for its run-time data tree."""
    if not d.is_dir():
        return None
    files = sorted(b"./" + str(p.relative_to(d)).encode() for p in d.rglob("*") if p.is_file() and not p.is_symlink())
    return hashlib.sha256(b"".join(b"%s  %s\n" % (sha256(d / f[2:].decode()).encode(), f) for f in files)).hexdigest()


def cells_identity(q: dict) -> dict:
    """G-V04/G-V11/G-V13 for the cells: binary, re-encode tool, the arm's lib/**, the libraries both resolve, the
    run-time data tree (OPENMS_DATA_PATH) and the env.sh that sets it all."""
    by_arm, out = {}, {}
    for name, c in cells(q).items():
        if c["arm"] not in by_arm:
            env = cell_env(q, name)
            b = env[CELL_KINDS[c["kind"]]["bin"]]
            tool = str(Path(b).parent / REENCODE[0])
            arm = os.path.realpath(Path(q["spx_root"]) / c["arm"])
            by_arm[c["arm"]] = {"binary": b, "binary_sha256": sha256(b), "reencode_sha256": sha256(tool),
                                "lib_sha256": tree_sha256(Path(arm) / "lib"),
                                "deps_sha256": dict(ldd_deps(env, arm, b), **ldd_deps(env, arm, tool)),
                                "data_tree_sha256": data_tree_sha256(Path(arm) / CELL_KINDS[c["kind"]]["data"]),
                                "env_sha256": sha256(Path(q["spx_root"]) / c["arm"] / "env.sh")}
        out[name] = by_arm[c["arm"]]
    return out


def cell_provenance(q: dict, name: str, cenv: dict, cid: dict) -> list:
    """G-V03: the cell arm's provenance file lists, under `sha256_published:`, the binary, the re-encode tool and every
    lib/** file of the arm, each with the sha256 the file has now."""
    c = q["cells"][name]
    kind = CELL_KINDS[c["kind"]]
    arm = os.path.realpath(Path(q["spx_root"]) / c["arm"])
    prov = Path(arm) / kind["prov"]
    if not prov.is_file():
        die_queue("G-V03", "cell %s: provenance missing: %s" % (name, prov))
    lines = prov.read_text().splitlines()
    listed, block = {}, False
    for line in lines:
        if not line[:1].isspace():
            block = line.strip() == "sha256_published:"
        elif block:
            m = re.fullmatch(r"\s+([0-9a-f]{64})\s+(\S+)\s*", line)
            if m:
                listed[m.group(2)] = m.group(1)
    b = os.path.realpath(cenv[kind["bin"]])
    want = dict({os.path.relpath(b, arm): cid["binary_sha256"],
                 os.path.relpath(os.path.join(os.path.dirname(b), REENCODE[0]), arm): cid["reencode_sha256"]},
                **{"lib/" + k: v for k, v in cid["lib_sha256"].items()})
    bad = sorted(k for k, v in want.items() if listed.get(k) != v)
    if bad:
        die_queue("G-V03", "cell %s: %s sha256_published omits or differs from %s" % (name, prov, bad[:4]))
    key = kind["data_prov"] + "="
    data = [x[len(key):].strip() for x in lines if x.startswith(key)]
    if len(data) != 1 or data[0] != cid["data_tree_sha256"]:
        die_queue("G-V03", "cell %s: %s %s %s, the data tree in use (%s) is %s"
                  % (name, prov, key, data or "missing", kind["data"], cid["data_tree_sha256"]))
    return lines


def cells_meta(q: dict, cenvs: dict, ident0: dict) -> dict:
    """G-V03 per cell: provenance listing the files in use, label from the binary's --help."""
    out = {}
    for name, c in cells(q).items():
        env, var = cenvs[name], CELL_KINDS[c["kind"]]["bin"]
        out[name] = {"label": tool_label(env[var], env), "bin_var": var,
                     "provenance": cell_provenance(q, name, env, ident0["cells"][name]),
                     "openms_data_path": env.get("OPENMS_DATA_PATH"), "ld_library_path": env.get("LD_LIBRARY_PATH")}
    return out


def tool_dest(q: dict) -> dict:
    t, d = q["tools"], Path(q["root"]) / "tools"
    return {"sage": d / "sage" / "sage", **{k: d / Path(t[k]).name for k in plan_tool_keys(q) if k != "sage"}}


def plan_tool_keys(plan: dict) -> tuple:
    return TOOL_KEYS + (CELL_TOOL_KEYS if plan.get("cells") else ()) + (ENTRAP_TOOL_KEYS if plan.get("entrapment") else ())


def db_keys(plan: dict) -> tuple:
    return DB_KEYS + ((ENTRAP_DB,) if plan.get("entrapment") else ())


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
    paths.update(search_dbs(dest["sage_config"], dest["msfragger_params"], dest.get("sage_entrap")))
    shas = {k: sha256(v) for k, v in paths.items()}
    check_db_pins(q, shas)
    return {"paths": paths, "sha256": shas}


def check_fasta(tools: dict) -> None:
    for k in [k for k in DB_KEYS + (ENTRAP_DB,) if k in tools["paths"]]:
        if sha256(tools["paths"][k]) != tools["sha256"][k]:
            die_queue("G-V12", "%s changed during the run: %s" % (k, tools["paths"][k]))


def search_dbs(sage_config, msfragger_params, sage_entrap=None) -> dict:
    def fasta(cfg):
        try:
            return json.loads(Path(cfg).read_text())["database"]["fasta"]
        except (OSError, ValueError, KeyError, TypeError) as x:
            die_queue("G-V12", "sage config %s has no database.fasta: %s" % (cfg, x))
    m = re.search(r"^database_name\s*=\s*(\S+)", Path(msfragger_params).read_text(), re.M)
    if not m:
        die_queue("G-V12", "msfragger.params has no database_name")
    out = {"sage_fasta": fasta(sage_config), "msfragger_db": m.group(1)}
    if sage_entrap:
        out[ENTRAP_DB] = fasta(sage_entrap)
    return out


def check_db_pins(q: dict, shas: dict) -> None:
    """The databases are node-local files: one byte of difference on one node would otherwise surface only when
    the table refuses mixed search inputs after the whole run (review F5)."""
    for k in db_keys(q):
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
    dbs = search_dbs(q["tools"]["sage_config"], q["tools"]["msfragger_params"], q["tools"].get("sage_entrap"))
    for k, p in dbs.items():
        if not os.path.isfile(p):
            die_queue("G-V12", "%s missing on this node: %s" % (k, p))
    shas = {k: sha256(p) for k, p in dbs.items()}
    check_db_pins(q, shas)
    j = java_info(env)
    return {"python": ".".join(map(str, v)), "time": TIME, "java": {k: j[k] for k in ("path", "version", "major")},
            "search_db": {k: {"path": dbs[k], "sha256": shas[k]} for k in db_keys(q)}}


# ------------------------------------------------------------------------------- node: gate, staging
def bracketed(binary: str) -> str:
    base = os.path.basename(binary)
    return base[:-1].replace(".", r"\.") + "[" + base[-1] + "] -in"


def busy_patterns(env: dict, cenvs=None) -> list:
    """`cenvs` (extended plans): the cells' binaries are ours too."""
    extra = sorted({bracketed(e[v]) for e in (cenvs or {}).values() for v in e if v in {k["bin"] for k in CELL_KINDS.values()}})
    return BUSY_FIXED + [bracketed(env["SPX_BIN"])] + extra


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


def stage_tdf(q: dict, s: dict, pair_run: str) -> tuple:
    """stage() for an extended plan: the same fresh 0700 directory, neutral name and pin checks (G-V02, G-V07), but
    only STAGE_FILES are copied."""
    sroot = Path(q["root"]) / "stage"
    sroot.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(sroot, 0o700)
    d = sroot / ("%s-%s" % (s["id"], pair_run))
    d.mkdir(mode=0o700)
    raw = Path(s["raw"])
    fp_raw = fingerprint(raw, with_acq=True, what="raw of %s" % s["id"])
    check_pin(fp_raw, s["pin"], "raw of %s" % s["id"])
    if round(fp_raw["acq_min"], 1) != round(float(s["acq_min"]), 1):
        die("G-V02", "raw of %s: acquisition %.1f min, registry acq_min %s" % (s["id"], fp_raw["acq_min"], s["acq_min"]))
    dst = d / (s["id"] + ".d")
    t0 = time.monotonic()
    try:
        dst.mkdir(mode=0o700)
        for f in STAGE_FILES:
            shutil.copyfile(raw / f, dst / f)
            os.chmod(dst / f, 0o600)
    except OSError as x:
        die("G-V07", "staging copy of %s failed: %s" % (s["id"], x.strerror or type(x).__name__))
    secs = time.monotonic() - t0
    fp = fingerprint(dst, what="staged copy of %s" % s["id"])
    check_pin(fp, s["pin"], "staged copy of %s" % s["id"])
    return dst, {"dir": str(d), "name": dst.name, "copy_s": round(secs, 1), "fingerprint": fp,
                 "acq_min_read": fp_raw["acq_min"], "files": sorted(x.name for x in dst.iterdir())}


def kill_session(pid: int) -> None:
    """Kill a cell's session so that its CPU stays in this runner's process tree, which the contention measure
    (G-V06) subtracts as our own. The leader is the GNU time wrapper: its children die first, it reaps them and exits,
    and only then does the rest of the group go. Killing the group in one signal orphaned the tool to init, whose reap
    took the tool's entire CPU out of our tree in one sample and booked it as foreign: 16,220 and 12,034 "foreign"
    cores on a 128-core node for the two diaWeaver cells G-V16 stopped (2026-09-17, -19). The leader is NOT reaped
    here -- Popen.wait() must reap it, or it reports the killed cell as exit 0. Linux /proc; elsewhere the group kill."""
    kids = []
    try:
        for d in os.listdir("/proc"):
            if d.isdigit() and int(d) != pid:
                try:
                    with open("/proc/%s/stat" % d) as f:
                        st = f.read()
                    if int(st[st.rindex(")") + 2:].split()[3]) == pid:      # field 6, the session id
                        kids.append(int(d))
                except (OSError, ValueError, IndexError):
                    continue
    except OSError:
        pass
    for k in kids:
        try:
            os.kill(k, signal.SIGKILL)
        except ProcessLookupError:
            pass
    t_end = time.monotonic() + 30
    while kids and time.monotonic() < t_end:                              # the leader reaps them and exits
        try:
            with open("/proc/%d/stat" % pid) as f:
                st = f.read()
            if st[st.rindex(")") + 2:].split()[0] in ("Z", "X"):
                break
        except (OSError, ValueError, IndexError):
            break
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def arc_evictable_kb(path="/proc/spl/kstat/zfs/arcstats") -> int:
    """The ZFS ARC above its own floor, in kB; 0 where there is no ZFS.

    Linux does NOT count the ARC in MemAvailable, but ZFS evicts it under memory pressure down to `c_min`. Where
    /scratch is ZFS the ARC grows to `c_max` (half of RAM by default), and MemAvailable then understates what a job
    can actually get by that much: on a 2,268 GB node the ARC sat at 1,135 GB with MemAvailable at 1,058 GB, and
    G-V16 killed a cell holding 939 GB -- 41% of the machine -- as if the node were full (2026-09-19, user
    approved the change). The floor below therefore asks for MemAvailable PLUS the evictable ARC, so the guard
    still stops a runaway arm but measures what the node can really give.
    """
    size = cmin = None
    try:
        for line in open(path):
            f = line.split()
            if len(f) == 3 and f[0] == "size":
                size = int(f[2])
            elif len(f) == 3 and f[0] == "c_min":
                cmin = int(f[2])
    except OSError:
        return 0
    return (size - cmin) // 1024 if size is not None and cmin is not None and size > cmin else 0


def run_capped(argv, cwd, env, log: Path, cap_s: float) -> tuple:
    """run_logged with a wall cap and a node memory floor (G-V16). The tool runs in its own session, and the whole
    session is killed when the cap passes, when available memory (MemAvailable plus the evictable ZFS ARC, which the
    kernel leaves out of MemAvailable) stays below MEM_FLOOR of MemTotal for MEM_FLOOR_SAMPLES consecutive samples
    (a runaway arm must not take a shared node down; a neighbour's transient dip must not cost a 12-h cell), or when
    the runner itself is stopped. Returns (returncode, reason stopped or None)."""
    t0, why, low = time.monotonic(), None, 0
    with open(log, "wb") as f:
        p = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=f, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            while p.poll() is None:
                m = proc_snapshot()
                arc = arc_evictable_kb()                     # ZFS cache the kernel omits from MemAvailable
                avail = (m["memavail_kb"] + arc) if m else 0
                low = low + 1 if m and avail < MEM_FLOOR * m["memtotal_kb"] else 0
                if time.monotonic() - t0 > cap_s:
                    why = "wall cap %.0f s exceeded" % cap_s
                elif low >= MEM_FLOOR_SAMPLES:
                    why = ("available memory %.1f%% of total in %d consecutive samples "
                           "(MemAvailable %.0f GB + evictable ZFS ARC %.0f GB)" % (
                               100.0 * avail / m["memtotal_kb"], low,
                               m["memavail_kb"] / 1048576.0, arc / 1048576.0))
                if why:
                    kill_session(p.pid)
                    break
                try:
                    p.wait(timeout=MON_S)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            kill_session(p.pid)
            p.wait()
            raise
        p.wait()
    return p.returncode, why


def time_cpu(path: Path) -> dict:
    """CPU seconds and occupancy from a GNU time -v log (user + system over wall)."""
    txt = path.read_text(errors="replace") if path.exists() else ""
    u = re.search(r"User time \(seconds\): ([\d.]+)", txt)
    k = re.search(r"System time \(seconds\): ([\d.]+)", txt)
    c = re.search(r"Percent of CPU this job got: (\d+)%", txt)
    return {"cpu_s": round(float(u.group(1)) + float(k.group(1)), 2) if u and k else None,
            "cpu_pct": int(c.group(1)) if c else None}


def numpress_linear(data: bytes) -> list:
    """MS-Numpress linear prediction decoding (MSNumpress decodeLinear), stdlib only: an 8-byte big-endian fixed point,
    two little-endian unsigned 4-byte ints, then half-byte-coded second-order residuals. Bit-identical to what the
    fork's FileFilter decodes (240 real diaWeaver-shaped spectra, review 2026-09-16). Corrupt input raises."""
    import struct
    n = len(data)
    if n < 8 or 8 < n < 12 or 12 < n < 16:
        raise ValueError("numpress linear: corrupt length %d" % n)
    fp = struct.unpack(">d", data[:8])[0]
    ints, out = [0, 0, 0], []
    for k, off in ((1, 8), (2, 12)):
        if n > off:
            ints[k] = int.from_bytes(data[off:off + 4], "little")
            out.append(ints[k] / fp)
    di, half = 16, 0
    while di < n:
        if di == n - 1 and half == 1 and data[di] & 0xF == 0:
            break                                       # the padding half-byte of an odd count
        if half == 0:
            head = data[di] >> 4
        else:
            head = data[di] & 0xF
            di += 1
        half = 1 - half
        m, res = (head, 0) if head <= 8 else (head - 8, (0xFFFFFFFF << (32 - 4 * (head - 8))) & 0xFFFFFFFF)
        for i in range(8 - m):                          # value half-bytes, least significant first
            if half == 0:
                hb = data[di] >> 4
            else:
                hb = data[di] & 0xF
                di += 1
            res |= hb << (4 * i)
            half = 1 - half
        ints[0], ints[1] = ints[1], ints[2]
        ints[2] = 2 * ints[1] - ints[0] + (res - (1 << 32) if res & 0x80000000 else res)
        out.append(ints[2] / fp)
    return out


def mzml_scan(path: Path, decode=False) -> dict:
    """One pass over an mzML (G-V17, G-V18): spectra, numpress terms anywhere, per-spectrum RT and precursor values
    (a digest of the sorted tuples: order may change, values may not), charge and 1/K0 tallies, peaks. With `decode`,
    each m/z array (plain, zlib, MS-Numpress linear with or without zlib; 32/64 bit) is read and its order checked,
    and two order-independent digests are built. `peak_digest`: each spectrum's precursor values and sorted m/z
    values (the numpress decode is bit-identical to OpenMS's, so a raw and a re-encoded file compare exactly).
    `content_digest`: every spectrum block without its id/index/spectrumRef/dataProcessingRef (OpenMS puts
    dataProcessingRef on whichever spectrum comes first, and diaWeaver's unstable RT sort decides which one that is).
    Block digests are sorted and hashed again, so two runs of one arm that differ only in order and ids do not
    differ in these digests. An m/z array that cannot be decoded counts as `undecoded`, a precursor value that is not
    a number as `bad_values`, a spectrum without an m/z array as `missing_mz`; none of them raises."""
    import array, binascii, zlib
    acc_re, val_re = re.compile(rb'\saccession="(MS:\d+)"'), re.compile(rb'\svalue="([^"]*)"')
    ids_re = re.compile(rb'\s(?:id|index|spectrumRef|dataProcessingRef)="[^"]*"')
    out = {"spectra": 0, "numpress_terms": 0, "unsorted": 0, "undecoded": 0, "length_mismatch": 0, "missing_mz": 0,
           "bad_values": 0, "missing_selected_ion": 0, "im_zero": 0, "im_missing": 0, "charges": {}}
    keys, blocks, pkeys, peaks = [], [], [], array.array("l")
    inside, h, prec, arr, n_decl, mzs, seen = False, None, {}, {}, 0, None, False

    def fl(v):
        if v in (None, ""):
            return ""
        try:
            return repr(float(v))
        except ValueError:
            out["bad_values"] += 1
            return "?" + v
    with open(path, "rb") as f:
        for line in f:
            if b"<cvParam" in line:
                a = acc_re.search(line)
                acc = a.group(1) if a else b""
                if acc in NUMPRESS_CV:
                    out["numpress_terms"] += 1
                if inside:
                    if acc in PREC_CV and acc not in prec:
                        v = val_re.search(line)
                        prec[acc] = v.group(1).decode(errors="replace") if v else ""
                    arr[acc] = True
            if not inside:
                if b"<spectrum " in line or line.lstrip().startswith(b"<spectrum>"):
                    inside, prec, arr, mzs, seen = True, {}, {}, None, False
                    m = re.search(rb'defaultArrayLength="(\d+)"', line)
                    n_decl = int(m.group(1)) if m else -1
                    h = hashlib.sha256(ids_re.sub(b"", line)) if decode else None
                continue
            if h is not None:
                h.update(ids_re.sub(b"", line) if b"spectrumRef" in line or b"dataProcessingRef" in line else line)
            if b"<binaryDataArray " in line or b"<binaryDataArray>" in line:
                arr = {}
            elif b"<binary>" in line and b"MS:1000514" in arr:
                seen = True
                if not decode:
                    continue
                values = None
                try:
                    raw = base64.b64decode(line.split(b"<binary>", 1)[1].split(b"</binary>", 1)[0], validate=True)
                    if b"MS:1000574" in arr or b"MS:1002746" in arr:
                        raw = zlib.decompress(raw)
                    if any(t in arr for t in NUMPRESS_LINEAR):
                        values = numpress_linear(raw)
                    elif not any(t in arr for t in NUMPRESS_CV) and (b"MS:1000523" in arr or b"MS:1000521" in arr):
                        mz = array.array("d" if b"MS:1000523" in arr else "f")
                        mz.frombytes(raw)
                        if sys.byteorder != "little":
                            mz.byteswap()
                        values = mz.tolist()
                except (ValueError, IndexError, zlib.error, binascii.Error):
                    values = None
                if values is None:
                    out["undecoded"] += 1
                    continue
                mzs = values
                out["unsorted"] += values != sorted(values)
                out["length_mismatch"] += len(values) != n_decl
            elif b"</spectrum>" in line:
                inside = False
                out["spectra"] += 1
                peaks.append(n_decl)
                vals = {k: fl(prec.get(k)) for k in PREC_CV}
                key = "|".join(vals[k] for k in PREC_CV)
                keys.append(key)
                out["missing_mz"] += not seen
                out["missing_selected_ion"] += not vals[b"MS:1000744"]
                z = prec.get(b"MS:1000041") or "none"
                out["charges"][z] = out["charges"].get(z, 0) + 1
                im = vals[b"MS:1002815"]
                out["im_missing"] += not im
                out["im_zero"] += im == repr(0.0)
                if decode and mzs is not None:
                    pkeys.append(hashlib.sha256(key.encode() + array.array("d", sorted(mzs)).tobytes()).digest())
                if h is not None:
                    blocks.append(h.digest())
    keys.sort()
    out["prec_digest"] = hashlib.sha256("\n".join(keys).encode()).hexdigest()
    out["peaks_total"] = sum(peaks)
    out["peaks_median"] = statistics.median(peaks) if peaks else 0
    out["peaks_min"] = min(peaks) if peaks else 0
    if decode:
        blocks.sort()
        pkeys.sort()
        out["content_digest"] = hashlib.sha256(b"".join(blocks)).hexdigest()
        out["peak_digest"] = hashlib.sha256(b"".join(pkeys)).hexdigest() \
            if len(pkeys) == out["spectra"] and not out["undecoded"] else None
    return out


def reencode(q, name, cenv, src: Path, adir: Path, rec: dict, digest) -> None:
    """G-V17: the cell output rewritten by REENCODE before any search (Sage 0.14 drops a numpress m/z array; diaWeaver
    writes peaks unsorted). The rewrite must carry no numpress term, an m/z array in every spectrum, m/z-sorted peaks,
    the same spectra with the same RT/precursor values and the same m/z values (both files decoded), and a selected
    ion m/z in every spectrum (no selected-ion patch for cells). The raw scan's unsorted count is the measurement of
    diaWeaver's own peak order. The original is deleted once the rewrite passed; `rec["output"]` is the rewrite, the
    file every search reads."""
    tool = str(Path(cenv[CELL_KINDS[q["cells"][name]["kind"]]["bin"]]).parent / REENCODE[0])
    dst, tl = adir / "reencoded.mzML", adir / "reencode.time"
    argv = cmd_reencode(tool, src, dst, tl)
    t0 = time.time()
    rc = run_logged(argv, adir, cenv, adir / "reencode.log")
    t = parse_time_log(tl, "G-V17")
    rec["reencode"] = dict(t, cmd=argv, time_rc=rc, cpu=time_cpu(tl))
    check_exit(t, rc, "G-V17", "re-encode of %s" % name)
    try:
        o = verify_mzml(dst, t0)
    except Abort as a:
        die("G-V17", a.message)
    before, after = mzml_scan(src, decode=True), mzml_scan(dst, decode=True)
    rec.update(spectra_stats=before, reencoded_stats=after)
    if after["numpress_terms"]:
        die("G-V17", "%d numpress term(s) remain after the re-encode of %s" % (after["numpress_terms"], name))
    if after["unsorted"] or after["undecoded"] or after["length_mismatch"] or after["missing_mz"] or after["bad_values"]:
        die("G-V17", "re-encoded %s: %d spectra not m/z-sorted, %d m/z arrays undecodable, %d with a length mismatch, "
            "%d without an m/z array, %d precursor values not a number" % (name, after["unsorted"], after["undecoded"],
                                                                          after["length_mismatch"], after["missing_mz"],
                                                                          after["bad_values"]))
    if before["undecoded"] or before["missing_mz"] or before["bad_values"]:
        die("G-V17", "raw output of %s: %d m/z arrays undecodable, %d spectra without one, %d precursor values not a "
            "number: its peaks cannot be compared with the re-encode" % (name, before["undecoded"], before["missing_mz"],
                                                                          before["bad_values"]))
    counts = {before["spectra"], after["spectra"], o["count"], rec["raw_output"]["count"]}
    if len(counts) != 1:
        die("G-V17", "re-encode of %s changed the spectrum count: %d -> %d (spectrumList %d -> %d)"
            % (name, before["spectra"], after["spectra"], rec["raw_output"]["count"], o["count"]))
    if after["prec_digest"] != before["prec_digest"]:
        die("G-V17", "re-encode of %s changed RT, selected ion m/z, charge, 1/K0 or isolation target values" % name)
    if not after["peak_digest"] or after["peak_digest"] != before["peak_digest"]:
        die("G-V17", "re-encode of %s changed the m/z values of at least one spectrum" % name)
    if after["missing_selected_ion"]:
        die("G-V17", "%d spectra of %s carry no selected ion m/z (MS:1000744)" % (after["missing_selected_ion"], name))
    try:
        sem = digest(str(dst))
    except SystemExit as x:              # semantic_digest.py exits on a file without a complete spectrum list
        die("G-V17", "spectrum-list digest of re-encoded %s: %s" % (name, x))
    rec.update(output=o, digests={"semantic": sem, "content": after["content_digest"]})
    src.unlink()


def run_cell(q, name, staged: Path, adir: Path, cenv, env, ident0, rec: dict, digest) -> None:
    """One extra cell, timed like run_arm (G-V16 in place of G-V08), then re-encoded outside its timed window. Both
    tools get a private TMPDIR inside the (0700) cell directory, emptied afterwards: the shared jnatmp is not private,
    and anything a tool spills there is patient-derived."""
    c = q["cells"][name]
    kind = CELL_KINDS[c["kind"]]
    adir.mkdir(parents=True)
    tmp = adir / "tmp"
    tmp.mkdir(mode=0o700)
    cenv = dict(cenv, TMPDIR=str(tmp))
    try:
        tl, log, out = adir / "time.log", adir / kind["log"], adir / kind["out"]
        argv = cmd_dwv(q, cenv[kind["bin"]], staged, adir, tl, c["args"])
        if not str(staged).startswith(str(Path(q["root"]) / "stage") + os.sep):
            die("G-V07", "cell input outside the stage root: %s" % staged)
        check_identity(q, env, ident0, "before the %s cell" % name)
        rec.update(tool=name, kind=c["kind"], arm=c["arm"], cmd=argv, cwd=str(adir), tmpdir=str(tmp), host=hostname(),
                   cores=os.cpu_count(), wall_cap_s=c["wall_cap_h"] * 3600, sync_s=flush_io(q["root"]),
                   prewarm_s=prewarm(staged))
        rec.update(ps_top=ps_top(), load_before=load1(), memavail_before_kb=mem_available_kb(), start=now_iso())
        with ArmMonitor(load_max(q)) as mon:
            t0 = time.time()
            rc, stopped = run_capped(argv, adir, cenv, log, c["wall_cap_h"] * 3600)
        rec.update(end=now_iso(), start_epoch=t0, time_rc=rc, stopped=stopped, during=mon.summary(), load_after=load1(),
                   memavail_after_kb=mem_available_kb())
        check_identity(q, env, ident0, "during the %s cell" % name)
        if stopped:
            die("G-V16", "%s killed: %s" % (name, stopped))
        rec.update(parse_time_log(tl, "G-V16"), cpu=time_cpu(tl))
        check_exit(rec, rc, "G-V16", name)
        if not out.is_file():
            die("G-V16", "%s wrote no %s" % (name, kind["out"]))
        try:
            o = verify_mzml(out, t0)
        except Abort as a:
            die("G-V16", a.message)
        n = log_count(log, kind["count"])
        rec.update(raw_output=o, log_count=n)
        if n != o["count"]:
            die("G-V16", "%s: log count %s != spectrumList count %s" % (name, n, o["count"]))
        if kind["done"] not in log.read_bytes():
            die("G-V16", "%s log lacks %r: the final rewrite did not finish" % (name, kind["done"].decode()))
        reencode(q, name, cenv, out, adir, rec, digest)
    finally:
        rec["tmp_files"] = sum(1 for p in tmp.rglob("*") if not p.is_dir()) if tmp.is_dir() else None
        remove_tree(tmp)


def noop_check(rec: dict) -> None:
    """G-V18 (flags): a cell with `differs_from` must differ from that cell in content (order-independent digest; the
    spectrum-list digest and count are recorded beside it). Not computable (either cell failed) counts as flagged.
    One-sided: equal content is a no-op for certain, but "differs" also results when the tool's output varies from run
    to run, so it does not prove that the settings made the difference."""
    for name, c in (rec.get("cells") or {}).items():
        ref = c.get("differs_from")
        a, b = rec["arms"].get(name) or {}, rec["arms"].get(ref) or {}
        if not ref or a.get("status") != "ok":
            continue
        if b.get("status") != "ok":
            a["noop"] = {"vs": ref, "computed": False, "flag": True, "why": "%s did not finish" % ref}
            continue
        same = a["digests"]["content"] == b["digests"]["content"]
        a["noop"] = {"vs": ref, "computed": True, "flag": same, "content_equal": same,
                     "semantic_equal": a["digests"]["semantic"] == b["digests"]["semantic"],
                     "count_equal": a["output"]["count"] == b["output"]["count"]}


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


def rec_path(root, sid: str, *k) -> Path:
    return Path(root) / "records" / (".".join((sid,) + k) + ".json")


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


def load_module(path, name: str):
    """A run-local bench tool (bench/entrapment.py, bench/semantic_digest.py) imported as a module: the same code
    the historical drivers ran, pinned by G-V12 like every other run-local tool."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tsv_iter(tsv: Path, need: set, guard: str):
    """Header first, then the rows, streamed (a TNBC result TSV holds millions of PSMs)."""
    import csv
    with open(tsv, newline="") as f:
        r = csv.reader(f, delimiter="\t")
        h = next(r, None)
        if not h or not need <= set(h):
            die(guard, "%s lacks columns %s" % (tsv.name, sorted(need - set(h or []))))
        yield h
        yield from r


def tsv_charge(v: str, tsv: Path) -> int:
    """G-V19: a charge cell of a result TSV that is not an integer refuses the split instead of crashing the queue."""
    try:
        return int(v)
    except ValueError:
        die("G-V19", "%s: charge %r is not an integer" % (tsv.name, v))


def entrap_strata(tsv: Path, est, fasta: str) -> dict:
    """G-V19: bench/entrapment.py's own estimator (peptide-hypothesis ratio, score() with its bootstrap CI) per charge
    stratum. score() takes each non-decoy peptide's best PSM by sage_discriminant_score; the same choice puts the
    peptide in the stratum of that PSM's charge, and each stratum is scored by score() on a TSV of those rows, so
    z1 + z2p partition the whole-run numbers exactly (checked)."""
    ratio = est.peptide_ratio(fasta, ENTRAP_TAG)
    if not ratio > 0:
        die("G-V19", "the entrapment FASTA has no %s peptides (ratio %s): no entrapment to measure" % (ENTRAP_TAG, ratio))
    rows = tsv_iter(tsv, {"peptide", "proteins", "charge", "peptide_q", "sage_discriminant_score"}, "G-V19")
    h = next(rows)
    ip, ipr, iz, iq, isc = (h.index(k) for k in ("peptide", "proteins", "charge", "peptide_q", "sage_discriminant_score"))
    best = {}                        # peptide -> (score, charge, line): one joined line per peptide, not a parsed row
    for row in rows:
        try:
            sc, _ = float(row[isc]), float(row[iq])
        except ValueError:
            continue
        prots = [x for x in row[ipr].split(";") if x]
        if not prots or all(x.startswith("rev_") for x in prots):
            continue
        if row[ip] not in best or sc > best[row[ip]][0]:
            best[row[ip]] = (sc, tsv_charge(row[iz], tsv), "\t".join(row))
    out = {"ratio": ratio, "fasta": fasta}
    with tempfile.TemporaryDirectory() as td:
        for name, lo, hi in STRATA:
            part = Path(td) / (name + ".tsv")
            with open(part, "w") as f:
                f.write("\t".join(h) + "\n" + "".join(line + "\n" for _, z, line in best.values() if lo <= z <= hi))
            acc, nt, ne, raw, fdr, lo_ci, hi_ci = est.score(str(part), ENTRAP_TAG, ratio)
            fin = lambda v: round(v, 4) if v == v else None          # an empty stratum's CI is NaN
            out[name] = {"accepted": acc, "target": nt, "entrap": ne, "raw_pct": fin(raw), "fdr_pct": fin(fdr),
                         "ci_pct": [fin(lo_ci), fin(hi_ci)]}
    for k in ("accepted", "target", "entrap"):
        if out["z1"][k] + out["z2p"][k] != out["all"][k]:
            die("G-V19", "charge strata do not partition the run: %s z1 %d + z2p %d != %d"
                % (k, out["z1"][k], out["z2p"][k], out["all"][k]))
    if out["all"]["target"] <= 0:
        die("G-V19", "0 target peptides accepted in the entrapment search: a failed search, never a result")
    return out


def run_entrap(q, s, tool, pair, tools, env, ctx) -> bool:
    """The entrapment search of one output (engine `entrap`): Sage with the plan's entrapment config on the same input
    the Sage cell reads (diaTracer patched, cells re-encoded), the same read checks as run_search (G-V10), then
    entrap_strata (G-V19)."""
    root, tp = Path(q["root"]), tools["paths"]
    o = pair["arms"][tool]["output"]
    mz = Path(o["path"])
    sdir = root / "runs" / s["id"] / pair["pair_run"] / "search" / ("%s_entrap" % tool)
    rec = {"kind": "search", "id": s["id"], "tool": tool, "engine": "entrap", "pair_run": pair["pair_run"],
           "node": hostname(), "tools_sha256": tools["sha256"], "workers": q["search_workers"],
           "measure_sha256": {k: ctx["measure"].get(k) for k in ("search", "score", "cells")},
           "java": (ctx["ident"].get("java") or {}).get("version"), "started": now_iso(), "steps": {}, "status": "running"}
    err = None
    write_json(rec_path(root, s["id"], tool, "entrap"), rec)

    def step(name, argv, log):
        tl = Path(argv[3])
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
        n_out = rec["mzml_count"] = o["count"]
        inp = mz
        if tool == "dt":
            inp = sdir / "patched.mzML"
            step("patch", cmd_patch(tp, mz, inp, sdir / "patch.time"), "patch.log")
            rec["patched"] = log_count(sdir / "patch.log", rb"patched (\d+) precursor")
            if rec["patched"] != n_out:
                die("G-V10", "patch_diatracer_precursor.py patched %s of %d spectra" % (rec["patched"], n_out))
        log = step("engine", cmd_sage(dict(tp, sage_config=tp["sage_entrap"]), inp, sdir, sdir / "engine.time"), "sage.log")
        if b"finished in" not in log:
            die("G-V10", "Sage (entrapment) log lacks 'finished in'")
        rec["engine_spectra"] = engine_spectra(log, "sage")
        if rec["engine_spectra"] is None or not SAGE_MIN_READ * n_out <= rec["engine_spectra"] <= n_out:
            die("G-V10", "Sage (entrapment) searched >= %s spectra of %d written" % (rec["engine_spectra"], n_out))
        tsv = sdir / "results.sage.tsv"
        if not tsv.is_file():
            die("G-V10", "result TSV missing: %s" % tsv)
        est = load_module(tp["entrapment"], "entrapment_runlocal")
        rec.update(entrapment=entrap_strata(tsv, est, tp[ENTRAP_DB]), result_tsv=str(tsv))
        rec["peptides"] = rec["entrapment"]["all"]["target"]
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
        write_json(rec_path(root, s["id"], tool, "entrap"), rec)
        say("search %s %s entrap %s" % (s["id"], tool, "ok %d target peptides" % rec["peptides"] if rec["status"] == "ok"
                                        else "%s [%s] %s" % (rec["status"], rec.get("guard"), rec.get("message"))))
    if err is not None and (not isinstance(err, Abort) or err.queue):
        raise err
    return rec["status"] == "ok"


def sage_by_charge(tsv: Path) -> dict:
    """The corpus-v3 Sage count (sage_peptides: rank 1, peptide_q <= 0.01, target+decoy), each counted peptide put in
    the stratum of its best counted PSM (highest sage_discriminant_score)."""
    rows = tsv_iter(tsv, {"peptide", "rank", "peptide_q", "label", "charge", "sage_discriminant_score"}, "G-V19")
    h = next(rows)
    ip, ir, iq, il, iz, isc = (h.index(k) for k in ("peptide", "rank", "peptide_q", "label", "charge", "sage_discriminant_score"))
    best = {}
    for row in rows:
        if row[ir] == "1" and float(row[iq]) <= 0.01:
            sc = float(row[isc])
            if row[ip] not in best or sc > best[row[ip]][0]:
                best[row[ip]] = (sc, tsv_charge(row[iz], tsv), row[il] != "-1")
    return {name: {"peptides": sum(1 for _, z, _ in best.values() if lo <= z <= hi),
                   "target_peptides": sum(1 for _, z, t in best.values() if t and lo <= z <= hi)}
            for name, lo, hi in STRATA}


def msf_by_charge(tsv: Path) -> dict:
    """The corpus-v3 MSFragger count (msf_peptides: best hyperscore per key, deepest prefix with decoy/target <= 1%),
    each accepted key put in the stratum of its best PSM. Keys are ordered exactly as msf_peptides orders them."""
    rows = tsv_iter(tsv, {"peptide", "hyperscore", "charge"}, "G-V19")
    col = {k: i for i, k in enumerate(next(rows))}
    get = lambda row, k: row[col[k]] if col.get(k, len(row)) < len(row) else ""
    best = {}
    for row in rows:
        key = (get(row, "peptide"), get(row, "modification_info") or get(row, "assigned_modifications"))
        prots = [x for x in re.split(r"[,;@]", (get(row, "proteins") or get(row, "protein"))) if x]
        dec = all(x.startswith("rev_") for x in prots)
        hs = float(get(row, "hyperscore"))
        if key not in best or hs > best[key][0]:
            best[key] = (hs, dec, tsv_charge(get(row, "charge"), tsv))
    t = d = cut = 0
    ranked = sorted(best.values(), key=lambda v: (v[0], v[1]), reverse=True)
    for i, (hs, dec, z) in enumerate(ranked):
        d, t = d + dec, t + (not dec)
        if t and d / t <= 0.01:
            cut = i + 1
    return {name: {"peptides": sum(1 for _, dec, z in ranked[:cut] if not dec and lo <= z <= hi)} for name, lo, hi in STRATA}


def add_split(root, sid: str, tool: str, engine: str, ctx: dict) -> bool:
    """Per-charge split of a finished Sage or MSFragger cell (extended plans), written into its record with the cells
    hash. The split must add up to the cell's own count (G-V19). A crash (a charge that is not an integer, a missing
    TSV) fails this search cell, never the queue."""
    p = rec_path(root, sid, tool, engine)
    r = read_json(p)
    try:
        by = (sage_by_charge if engine == "sage" else msf_by_charge)(Path(r["result_tsv"]))
        for k in [k for k in ("peptides", "target_peptides") if k in by["all"]]:
            if by["z1"][k] + by["z2p"][k] != by["all"][k] or by["all"][k] != r[k]:
                die("G-V19", "%s %s: charge split %s z1 %d + z2p %d, all %d, counted %d"
                    % (tool, engine, k, by["z1"][k], by["z2p"][k], by["all"][k], r[k]))
        r["by_charge"] = by
        r["measure_sha256"] = dict(r["measure_sha256"], cells=ctx["measure"]["cells"])
    except Exception as x:
        if isinstance(x, Abort) and x.queue:
            raise
        g, msg = (x.guard, x.message) if isinstance(x, Abort) else ("CRASH", "%s: %s" % (type(x).__name__, x))
        r.update(status="failed", guard=g, message=msg)
        say("search %s %s %s split failed [%s] %s" % (sid, tool, engine, g, msg))
    write_json(p, r)
    return r["status"] == "ok"


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
        for tool in ctx.get("tools", TOOLS):
            o = (pair["arms"].get(tool) or {}).get("output")
            if o and all(search_done(read_json(rec_path(root, s["id"], tool, e)), pair, ctx)
                         for e in ctx.get("engines", ENGINES)):
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
    cenvs = {}
    for n in cells(q):
        try:
            cenvs[n] = cell_env(q, n)
        except Abort as a:
            print("# NOTE: a launch would ABORT now: %s" % a)
    root, tp = Path(q["root"]), {k: str(v) for k, v in tool_dest(q).items()}
    j = lambda argv: shlex.join(str(x) for x in argv)
    print("# plan %s node %s root %s search_workers %s load gate: 1-min load <= 24 (>=200 cores) else 12, wait %s min "
          "then flag; during each arm, foreign CPU (60-s mean) above the same threshold or MemAvailable < %d%% flags"
          % (q["plan"], q["node"], root, q["search_workers"], q["load_wait_min"], round(MEM_FLOOR * 100)))
    print("# env: unset %s %s and the inherited LD_LIBRARY_PATH; source %s/%s/env.sh; LC_ALL=C TMPDIR=%s"
          % (" ".join(p + "*" for p in STRIP_PREFIX), " ".join(sorted(STRIP_EXACT)), q["spx_root"], q["arm"], q["jnatmp"]))
    if extended(q):
        print("# extended plan: cells %s (each: the same env rules on <spx_root>/<cell arm>/env.sh), entrapment %s; "
              "measurement hashes pair/search/score/cells%s" % (", ".join("%s=%s" % (n, c["arm"]) for n, c in cells(q).items())
                                                                 or "none", "on" if q.get("entrapment") else "off",
                                                                 "; engines %s only (plan `engines`)" % ", ".join(q["engines"])
                                                                 if "engines" in q else ""))
    names = list(cells(q))
    for i, s in enumerate(q["samples"]):
        order = list(TOOLS) if i % 2 == 0 else list(reversed(TOOLS))
        k = i % len(names) if names else 0
        extra = names[k:] + names[:k]
        d = root / "stage" / ("%s-<pair_run>" % s["id"])
        staged, pdir = d / (s["id"] + ".d"), root / "runs" / s["id"] / "<pair_run>"
        print("\n## %s  %s  order %s" % (s["id"], s["scheme"], " -> ".join(order + extra)))
        if extended(q):
            print("# copy %s only into a fresh 0700 directory, neutral name; pin + acq_min check on the raw, pin check on "
                  "the copy\ncopy %s/{%s} %s" % (" + ".join(STAGE_FILES), shlex.quote(s["raw"]), ",".join(STAGE_FILES),
                                                shlex.quote(str(staged))))
        else:
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
        for name in extra:
            c, a = q["cells"][name], pdir / name
            kind = CELL_KINDS[c["kind"]]
            b = cenvs[name][kind["bin"]] if name in cenvs else "$" + kind["bin"]
            print("sync -f %s; %s >/dev/null   # before each arm, outside its timed window"
                  % (root, j(["cat", staged / "analysis.tdf", staged / "analysis.tdf_bin"])))
            print("(cd %s && TMPDIR=%s %s >%s 2>&1)   # own session, private 0700 TMPDIR (removed after), killed after %s h "
                  "or when MemAvailable stays < %d%% for %d samples (G-V16)"
                  % (a, a / "tmp", j(cmd_dwv(q, b, staged, a, a / "time.log", c["args"])), kind["log"], c["wall_cap_h"],
                     round(MEM_FLOOR * 100), MEM_FLOOR_SAMPLES))
            print("(cd %s && %s >reencode.log 2>&1 && rm %s)   # G-V17 (both files decoded): no numpress term, an m/z array "
                  "in every spectrum, m/z-sorted, same spectra, RT/precursor and m/z values, MS:1000744 everywhere; the raw "
                  "file's unsorted peak lists recorded" % (a, j(cmd_reencode(
                      os.path.join(os.path.dirname(b), REENCODE[0]), a / kind["out"], a / "reencoded.mzML",
                      a / "reencode.time")), kind["out"]))
            if c.get("differs_from"):
                print("# G-V18: flag %s if its content digest equals %s's" % (name, c["differs_from"]))
        print("rm -rf %s" % d)
    print("\n# phase 2 (after every pair of this queue; MSFragger units alone until one MSFragger search succeeded)\n"
          "# checks: patched == spectra; Sage 'finished in' and '- search:' covering %d-100%% of the spectra; "
          "MSFragger 'TOTAL TIME' and Scans == spectra; peptides > 0" % round(SAGE_MIN_READ * 100))
    for s in q["samples"]:
        pdir = root / "runs" / s["id"] / "<pair_run>"
        for tool in q_tools(q):
            mz = pdir / tool / {"spx": "pseudo.mzML", "dt": s["id"] + "_diatracer.mzML"}.get(tool, "reencoded.mzML")
            sd = pdir / "search" / ("%s_sage" % tool)
            inp = mz
            if "sage" in q_engines(q):
                if tool == "dt":
                    inp = sd / "patched.mzML"
                    print("(cd %s && %s)" % (sd, j(cmd_patch(tp, mz, inp, sd / "patch.time"))))
                print("(cd %s && %s)" % (sd, j(cmd_sage(tp, inp, sd, sd / "engine.time"))))
            sd = pdir / "search" / ("%s_msfragger" % tool)
            if "msfragger" in q_engines(q):
                print("(cd %s && %s && ln -s fixed.mzML in.mzML && %s)"
                      % (sd, j(cmd_fix(tp, mz, sd / "fixed.mzML", sd / "fix.time")), j(cmd_msf(tp, sd / "engine.time"))))
            if not extended(q):
                print("rm -f %s   # only after both engines succeeded" % mz)
                continue
            print("# G-V19: each Sage/MSFragger count split by the charge of its best PSM (z1, z2p)")
            if q.get("entrapment"):
                sd = pdir / "search" / ("%s_entrap" % tool)
                inp = mz
                if tool == "dt":
                    inp = sd / "patched.mzML"
                    print("(cd %s && %s)" % (sd, j(cmd_patch(tp, mz, inp, sd / "patch.time"))))
                print("(cd %s && %s)   # then entrapment.py peptide_ratio + score() per stratum %s (G-V19)"
                      % (sd, j(cmd_sage(dict(tp, sage_config=tp["sage_entrap"]), inp, sd, sd / "engine.time")),
                         "/".join(n for n, _, _ in STRATA)))
            print("rm -f %s   # only after every engine succeeded" % mz)


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
        cenvs = {n: cell_env(q, n) for n in cells(q)}
        b = busy(busy_patterns(env, cenvs))
        pre = preflight(q, env)
        if cells(q):              # G-V03 for every cell before a launch: provenance, label, libraries
            ident = {"cells": cells_identity(q)}
            pre["cells"] = {n: {"label": m["label"], "arm": q["cells"][n]["arm"],
                                "binary_sha256": ident["cells"][n]["binary_sha256"],
                                "reencode_sha256": ident["cells"][n]["reencode_sha256"]}
                            for n, m in cells_meta(q, cenvs, ident).items()}
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
    if extended(q):
        die_queue("G-V01", "guardtest covers the two-extractor pair only; plan %s has cells or entrapment" % q["plan"])
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
    a non-empty list of ENGINES names in ENGINES order, without repeats, and not all of them (the default; the key
    makes a plan extended); the entrapment search has its own key."""
    if "entrapment" in plan and not isinstance(plan["entrapment"], bool):
        die("G-V01", "plan %s: entrapment must be true or false, not %r" % (name, plan["entrapment"]))
    eng = plan.get("engines")
    if "engines" in plan and (not isinstance(eng, list) or not eng or [e for e in ENGINES if e in eng] != eng):
        die("G-V01", "plan %s: engines must be a non-empty list of %s in that order without repeats, not %r"
            % (name, list(ENGINES), eng))
    if eng == list(ENGINES):          # review 2026-09-17 (kimi 4, vibe 1): a no-op spelling that re-runs a plain plan whole
        die("G-V01", "plan %s: engines %r names every engine, the default: omit the key (it makes a plan extended, so a "
                     "finished plain plan would re-run every pair)" % (name, eng))
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


def lock_path(plan: dict) -> str:
    return str(Path(plan["scratch_root"]).parent / ".corpus-queue.lock")   # node-wide: one queue per node


def node_root(plan: dict, node: str, key="scratch_root") -> str:
    return "%s/%s" % (plan[key].rstrip("/"), node)


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
        for n, c in (pre.get("cells") or {}).items():
            print("   cell %s: %s, arm %s, binary %s, %s %s" % (n, c["label"], c["arm"], c["binary_sha256"][:16],
                                                           REENCODE[0], c["reencode_sha256"][:16]))
        if ENTRAP_DB in pre["search_db"]:
            print("   entrap_fasta %s" % pre["search_db"][ENTRAP_DB]["sha256"][:16])
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
    md, incomplete, total = (render_cells_table if extended(plan) else render_table)(args.plan, plan, reg, recs, args.source)
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
            out.append("during %s: %s" % (names.get(t, t), "; ".join(du.get("why") or ["?"])))
    return "; ".join(out) or "-"


def noop_flag(a: dict) -> str:
    nz = a.get("noop") or {}
    if not nz.get("flag"):
        return ""
    return "no-op: content equal to %s" % nz["vs"] if nz.get("computed") else "no-op check impossible: %s" % nz.get("why")


def group_flags(p: dict, names=None) -> str:
    """pair_flags plus the G-V18 no-op flags of an extended group."""
    out = [f for f in [pair_flags(p, names)] if f != "-"]
    out += ["%s %s" % (n, noop_flag(a)) for n, a in (p.get("arms") or {}).items() if noop_flag(a)]
    return "; ".join(out) or "-"


def search_overlaps(recs: list) -> set:
    """(id, tool, engine) of every search whose engine step overlapped another search's engine step on its node."""
    steps = [(r["node"], (r["id"], r["tool"], r["engine"]), st["start_epoch"], st["end_epoch"])
             for r in recs if r["kind"] == "search" for st in [(r.get("steps") or {}).get("engine") or {}]
             if st.get("start_epoch") is not None and st.get("end_epoch") is not None]
    return {k1 for n1, k1, a1, b1 in steps for n2, k2, a2, b2 in steps if k1 != k2 and n1 == n2 and a1 < b2 and a2 < b1}


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


# Extended plans only (plan keys `cells`, `entrapment`): the group runner, the cells, the re-encode, the entrapment search
# and the per-charge split. A change here re-runs the groups and searches of extended plans and nothing else.
MEASURED_CELLS = (sorted(CELL_KINDS.items()), REENCODE, NUMPRESS_CV, NUMPRESS_LINEAR, MEM_FLOOR_SAMPLES, PREC_CV, ENTRAP_TAG,
                  STRATA, STAGE_FILES, stage_tdf, cell_env, cmd_dwv, cmd_reencode, kill_session, run_capped, time_cpu,
                  numpress_linear, mzml_scan, reencode, run_cell, noop_check, run_group,
                  load_module, tsv_iter, tsv_charge, entrap_strata, run_entrap, sage_by_charge, msf_by_charge, add_split)
# The two-extractor pair as of DIAspeXtract 1.3.0 (CORPUS.md). selftest asserts these: an edit to a measured function
# must change them here on purpose, knowing that every record of a plain plan then re-runs.
PAIR_MEASURE_1_3_0 = {"pair": "3215b73e62ae", "search": "064af71b2bfe", "score": "4fe0a1cecefb"}
# The extended-plan code the reviewed harness (0d8532d) measured dwv_stage1 with; dwv_pxd029836 reuses it. Same rule:
# an edit that moves it re-runs every group and search of an extended plan, so change it here on purpose only.
# Moved c586f8716617 -> 4c23e6ab6354 on 2026-09-19 (user approved): run_capped's memory floor now counts the
# evictable ZFS ARC, which the kernel leaves out of MemAvailable. It had killed a diaWeaver cell holding 939 GB of
# a 2,268 GB node whose ARC held 1,135 GB. Only extended plans re-run, and every existing cell record is a failure.
# Moved 4c23e6ab6354 -> 196c420d07ce on 2026-09-23 (user asked for the fix): kill_session kills the time wrapper's
# children first, so a killed cell's CPU stays in the runner's tree instead of reading as 12-16k "foreign" cores. The
# kill itself is unchanged (the whole session still goes). Existing extended-plan tables still render; resuming one re-runs.
CELLS_MEASURE_DWV = "196c420d07ce"


def measure_sha256(extended=False) -> dict:
    parts = dict(MEASURED, cells=MEASURED_CELLS) if extended else MEASURED
    out = {}
    for part, items in parts.items():
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
  echo "User time (seconds): 100.00"; echo "System time (seconds): 25.00"; echo "Percent of CPU this job got: 200%"
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
        f.write("scannum\tpeptide\tproteins\tmodification_info\thyperscore\tcharge\n")
        f.write("".join("%d\tPEP%d\tsp|P%d|X_HUMAN desc, with comma\t\t%d\t%d\n" % (i, i, i, 200 - i, 1 if i % 10 == 0 else 2)
                        for i in range(150)))
        f.write("0\tREVPEP\trev_sp|Q1|Y_HUMAN decoy\t\t1\t2\n")
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
time.sleep(float(os.environ.get("FAKE_SAGE_SLEEP", "0")))     # lets concurrent searches overlap (search_overlaps)
zero = hit("FAKE_SAGE_ZERO", mz)
badz = hit("FAKE_SAGE_BADZ", mz)
rows = "".join("%d\tPEPTIDE%d\tsp|P%d|X\t1\tf.mzML\t%d\t1\t1\t%s\t%s\t%.2f\n"
               % (i, i, i, i, "0.5" if zero else "0.001", "x" if badz and i == 3 else 1 if i % 5 == 0 else 2, 1 - i / 100)
               for i in range(30))
if not zero:
    rows += "99\tDECOYPEP\trev_sp|P1|X\t1\tf.mzML\t99\t1\t-1\t0.001\t2\t0.1\n"
if "entrap" in sys.argv[1]:           # the entrapment config: foreign-proteome hits (one at z=1), and a weaker duplicate
    rows += "".join("%d\tENTRAPPEP%d\tENTRAP_sp|A%d|ARATH\t1\tf.mzML\t%d\t1\t1\t0.001\t%d\t0.5\n"
                    % (200 + i, i, i, 200 + i, 1 if i == 0 else 2) for i in range(3))
    rows += "300\tPEPTIDE1\tsp|P1|X\t1\tf.mzML\t300\t1\t1\t0.001\t1\t0.01\n"
hdr = "psm_id\tpeptide\tproteins\tnum_proteins\tfilename\tscannr\trank\tlabel\tpeptide_q\tcharge\tsage_discriminant_score\n"
if hit("FAKE_SAGE_NOCHARGE", mz):
    hdr = hdr.replace("\tcharge\t", "\tz\t")
with open(os.path.join(odir, "results.sage.tsv"), "w") as f:
    f.write(hdr + rows)
n = count(mz)
print("[INFO sage] - search:       999 ms (%d spectra/s)" % (n // 3 if hit("FAKE_SAGE_SHORT", mz) else n))
print("[INFO sage] finished in 1s")
'''
# Extended plans: a diaWeaver and a FileFilter that write and read real base64 arrays. The diaWeaver fake writes its m/z
# arrays as real MS-Numpress linear + zlib (the encoder below is MSNumpress encodeLinear; the FileFilter fake decodes
# them with the harness's own numpress_linear) and labels its plain intensity arrays as numpress slof, writes peaks
# unsorted, and orders its spectra by a fixed shuffle (equal RTs in pairs) like the real tool's unstable RT sort;
# ms1_centroid args shift every m/z. The FileFilter fake puts dataProcessingRef on its first spectrum, as OpenMS does.
FAKE_MZML_LIB = r'''
import base64, random, struct, zlib
def np_encode(vals, fp=100000.0):
    out = bytearray(struct.pack(">d", fp))
    ints = [0, 0, 0]
    for k in range(min(2, len(vals))):
        ints[k + 1] = int(vals[k] * fp + 0.5)
        out += (ints[k + 1] & 0xFFFFFFFF).to_bytes(4, "little")
    hb = []
    for v in vals[2:]:
        ints[0], ints[1] = ints[1], ints[2]
        ints[2] = int(v * fp + 0.5)
        x = (ints[2] - 2 * ints[1] + ints[0]) & 0xFFFFFFFF
        nib = [(x >> (4 * i)) & 0xF for i in range(8)]
        top = nib[::-1]
        if top[0] == 0:
            l = next((i for i in range(8) if top[i]), 8)
            hb += [l] + nib[:8 - l]
        elif top[0] == 0xF:
            l = next((i for i in range(8) if top[i] != 0xF), 7)
            hb += [l + 8] + nib[:8 - l]
        else:
            hb += [0] + nib
    if len(hb) % 2:
        hb.append(0)
    out += bytes((hb[i] << 4) | hb[i + 1] for i in range(0, len(hb), 2))
    return zlib.compress(bytes(out))
def write_mzml(path, specs, numpress=False, dp_first=False, mz_acc=None, drop_mz=(), badz=()):
    with open(path, "w") as f:
        f.write('<?xml version="1.0"?>\n<indexedmzML><mzML><run>\n<spectrumList count="%d">\n' % len(specs))
        for i, s in enumerate(specs):
            enc = lambda fmt, v: base64.b64encode(struct.pack("<%d%s" % (len(v), fmt), *v)).decode()
            f.write('<spectrum id="scan=%d" index="%d" defaultArrayLength="%d"%s>\n'
                    % (s["id"], i, len(s["mz"]), ' dataProcessingRef="dp_sp_0"' if dp_first and i == 0 else ""))
            f.write(' <scanList count="1"><scan>\n  <cvParam cvRef="MS" accession="MS:1000016" name="scan start time" '
                    'value="%r" unitAccession="UO:0000010"/>\n </scan></scanList>\n' % s["rt"])
            f.write(' <precursorList count="1"><precursor>\n  <isolationWindow>\n   <cvParam cvRef="MS" accession="MS:1000827" '
                    'name="isolation window target m/z" value="%r"/>\n  </isolationWindow>\n  <selectedIonList count="1">'
                    '<selectedIon>\n' % s["sel"])
            if s["sel_ok"]:
                f.write('   <cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="%r"/>\n' % s["sel"])
            f.write('   <cvParam cvRef="MS" accession="MS:1000041" name="charge state" value="%s"/>\n'
                    % ("x" if i in badz else s["z"]))
            f.write('   <cvParam cvRef="MS" accession="MS:1002815" name="inverse reduced ion mobility" value="%r" '
                    'unitAccession="MS:1002814"/>\n  </selectedIon></selectedIonList>\n </precursor></precursorList>\n' % s["im"])
            f.write(' <binaryDataArrayList count="2">\n')
            if i not in drop_mz:
                payload = base64.b64encode(np_encode(s["mz"])).decode() if numpress else enc("d", s["mz"])
                f.write('  <binaryDataArray encodedLength="0">\n   <cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/>\n'
                        '   <cvParam cvRef="MS" accession="%s" name="c"/>\n   <cvParam cvRef="MS" accession="MS:1000514" '
                        'name="m/z array"/>\n   <binary>%s</binary>\n  </binaryDataArray>\n'
                        % (mz_acc or ("MS:1002746" if numpress else "MS:1000576"), payload))
            f.write('  <binaryDataArray encodedLength="0">\n   <cvParam cvRef="MS" accession="MS:1000521" name="32-bit float"/>\n'
                    '   <cvParam cvRef="MS" accession="%s" name="c"/>\n   <cvParam cvRef="MS" accession="MS:1000515" '
                    'name="intensity array"/>\n   <binary>%s</binary>\n  </binaryDataArray>\n </binaryDataArrayList>\n'
                    '</spectrum>\n' % ("MS:1002748" if numpress else "MS:1000576", enc("f", s["inten"])))
        f.write('</spectrumList></run></mzML>\n<indexListOffset>1</indexListOffset></indexedmzML>\n')
def read_mzml(path):
    specs, cur, kind, accs = [], None, None, set()
    for line in open(path):
        if "<spectrum " in line:
            cur = {"mz": [], "inten": [], "sel_ok": False, "id": int(re.search(r'id="scan=(\d+)"', line).group(1))}
        if "<binaryDataArray" in line:
            accs = set()
        m = re.search(r'accession="(MS:\d+)"(?:[^>]*?value="([^"]*)")?', line)
        if cur is not None and m:
            a, v = m.groups()
            accs.add(a)
            if a == "MS:1000016": cur["rt"] = float(v)
            elif a == "MS:1000827": cur["sel"] = float(v)
            elif a == "MS:1000744": cur["sel_ok"] = True
            elif a == "MS:1000041": cur["z"] = int(v)
            elif a == "MS:1002815": cur["im"] = float(v)
            elif a in ("MS:1000514", "MS:1000515"): kind = a
        if "<binary>" in line:
            raw = base64.b64decode(line.split("<binary>")[1].split("</binary>")[0])
            if kind == "MS:1000514" and "MS:1002746" in accs:
                cur["mz"] = numpress_linear(zlib.decompress(raw))
            else:
                mz = kind == "MS:1000514"
                cur["mz" if mz else "inten"] = list(struct.unpack("<%d%s" % (len(raw) // (8 if mz else 4), "d" if mz else "f"), raw))
        if "</spectrum>" in line:
            specs.append(cur)
            cur = None
    return specs
#@NUMPRESS_LINEAR@
'''       # the harness's own decoder is pasted in by _fake() at selftest time: a node runs this file from stdin, where
          # inspect.getsource cannot work, so nothing at import may need it
FAKE_DWV = FAKE_HEAD + FAKE_MZML_LIB + r'''
if "--help" in sys.argv:
    print("diaWeaver -- Extract pseudo spectra from DIA data\nVersion: 3.5.0-pre-fake")
    sys.exit(0)
line = " ".join(sys.argv)
out = os.path.join(arg("-out"), "pseudo_spectra.mzML")
mode = lambda p: "%o" % (os.stat(p).st_mode & 0o777)
with open(os.path.join(arg("-out"), "staged_files.txt"), "w") as f:
    f.write("".join("%s %s\n" % (x, mode(os.path.join(arg("-in"), x))) for x in sorted(os.listdir(arg("-in")))))
tmpd = os.environ["TMPDIR"]
with open(os.path.join(arg("-out"), "tmpdir.txt"), "w") as f:
    f.write("%s %s\n" % (tmpd, mode(tmpd)))
open(os.path.join(tmpd, "dwv.tmp"), "w").write("spill")
if hit("FAKE_DWV_FAIL", line):
    sys.exit(3)
if hit("FAKE_DWV_SLOW", line):
    time.sleep(30)
if hit("FAKE_DWV_NAP", line):
    time.sleep(1)
shift = 0.25 if "-bruker:ms1_centroid_mz_ppm" in sys.argv else 0.0
n = 0 if hit("FAKE_DWV_ZERO", line) else 12
specs = [{"rt": 60.0 + i // 2, "sel": 400.0 + 10 * i, "sel_ok": not hit("FAKE_DWV_NO744", line), "z": 2 + i % 3,
          "im": 0.0 if i % 4 else 0.9, "mz": [300.0 + 7.5 * ((i * 7 + k * 13) % 40) + shift for k in range(8)],
          "inten": [float(1000 + 10 * k) for k in range(8)]} for i in range(n)]
random.Random(7).shuffle(specs)
if hit("FAKE_DWV_ALTORDER", line):
    specs.reverse()
for i, sp in enumerate(specs):
    sp["id"] = i + 1
pic = hit("FAKE_DWV_PIC", line)
if not hit("FAKE_DWV_NOOUT", line):
    write_mzml(out, specs, numpress=not pic, mz_acc="MS:1002313" if pic else None)
print("Finished processing all windows. Wrote %d pseudo spectra." % (n + 1 if hit("FAKE_DWV_MISCOUNT", line) else n))
if not hit("FAKE_DWV_NODONE", line):
    print("Done. Output (numpress compressed): %s" % out)
'''
FAKE_FILEFILTER = FAKE_HEAD + FAKE_MZML_LIB + r'''
src, dst = arg("-in"), arg("-out")
assert sys.argv[5:] == ["-sort"], sys.argv
open(os.path.join(os.environ["TMPDIR"], "ff.tmp"), "w").write("spill")
if hit("FAKE_FF_FAIL", src):
    sys.exit(1)
specs = sorted(read_mzml(src), key=lambda sp: sp["rt"])
for sp in specs:
    if not hit("FAKE_FF_NOSORT", src):
        o = sorted(range(len(sp["mz"])), key=lambda k: sp["mz"][k])
        sp["mz"], sp["inten"] = [sp["mz"][k] for k in o], [sp["inten"][k] for k in o]
if hit("FAKE_FF_DROP", src):
    specs = specs[1:]
if hit("FAKE_FF_CHARGE", src):
    specs[0]["z"] += 1
if hit("FAKE_FF_SHIFT", src):
    specs[0]["mz"][-1] += 0.5
write_mzml(dst, specs, numpress=hit("FAKE_FF_NUMPRESS", src), dp_first=True,
           drop_mz=(0,) if hit("FAKE_FF_NOMZ", src) else (), badz=(0,) if hit("FAKE_FF_BADZ", src) else ())
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


def _bench_tool(name: str):
    """The real bench tool the extended selftest imports: the repository copy, else the cluster deployment point."""
    for d in (REPO / "bench", Path("/ceph/ibmi/abi/oliver/spextract/tools")):
        if (d / name).is_file():
            return d / name
    return None


def _dwv_world(w: Path) -> dict:
    spx, t = w / "ceph" / "spx", w / "ceph" / "spx" / "tools"
    for arm in ("dwv", "dwv_noff", "dwv_badprov", "dwv_omp", "dwv_badshare", "dwv_nodata"):
        a = spx / arm
        _exe(a / "bin" / "diaWeaver", _fake(FAKE_DWV))
        if arm != "dwv_noff":
            _exe(a / "bin" / "FileFilter", _fake(FAKE_FILEFILTER))
        (a / "lib").mkdir()
        (a / "lib" / "libOpenMS.so").write_bytes(b"fork " + arm.encode())
        (a / "share" / "OpenMS" / "CHEMISTRY").mkdir(parents=True)          # the run-time data tree (OPENMS_DATA_PATH)
        (a / "share" / "OpenMS" / "CHEMISTRY" / "Elements.xml").write_text("<elements/>")
        (a / "share" / "OpenMS" / "CV").mkdir()
        (a / "share" / "OpenMS" / "CV" / "psi-ms.obo").write_text("format-version: 1.2")
        (a / "env.sh").write_text("export DWV_BIN=%s\nexport OPENMS_DATA_PATH=%s\n%s" % (
            a / "bin" / "diaWeaver", (a / "share") if arm == "dwv_nodata" else (a / "share" / "OpenMS"),
            "export OMP_NUM_THREADS=4\n" if arm == "dwv_omp" else ""))
        files = [f for f in ("bin/diaWeaver", "bin/FileFilter", "lib/libOpenMS.so") if (a / f).is_file()]
        (a / "PROVENANCE").write_text("arm=%s\ngit_sha=7ed11696fa71b3ac0b8c1a9f62fa2a2cbb39c0a8\nsha256_published:\n%s"
                                      "share_OpenMS_files=2\nshare_OpenMS_tree_sha256=%s\npublished=2026-09-16T22:09:20+02:00\n" % (
                                          arm, "".join("  %s  %s\n" % ("0" * 64 if arm == "dwv_badprov" and f == "lib/libOpenMS.so"
                                                                        else sha256(a / f), f) for f in files),
                                          "f" * 64 if arm == "dwv_badshare" else data_tree_sha256(a / "share" / "OpenMS")))
    (spx / "dwv_outside").mkdir()
    (spx / "dwv_outside" / "env.sh").write_text("export DWV_BIN=%s\n" % (spx / "dwv" / "bin" / "diaWeaver"))
    tools = {}
    for key, name in (("digest", "semantic_digest.py"), ("entrapment", "entrapment.py")):
        src = _bench_tool(name)
        if src:
            shutil.copyfile(src, t / name)
            tools[key] = str(t / name)
    (w / "bench" / "human_entrap.fasta").write_text(">sp|P1|X\nPEPTIDEKAAAGGGLLLKMMMSTTTR\n>ENTRAP_sp|A1|ARATH\nWWWYYYHHHKFFFLLLIIIR\n")
    (w / "bench" / "no_entrap.fasta").write_text(">sp|P1|X\nPEPTIDEKAAAGGGLLLKMMMSTTTR\n")
    (t / "sage_entrap.json").write_text(json.dumps({"database": {"fasta": str(w / "bench" / "human_entrap.fasta")}}))
    tools["sage_entrap"] = str(t / "sage_entrap.json")
    return tools


DWV_CELLS = {"dwv_default": {"kind": "dwv", "arm": "dwv", "args": [], "wall_cap_h": 1},
             "dwv_pickim": {"kind": "dwv", "arm": "dwv", "args": ["-bruker:ms1_centroid_mz_ppm", "0", "-bruker:ms1_centroid_im_pct", "0"],
                            "wall_cap_h": 1, "differs_from": "dwv_default"}}


def _xqueue(w: Path, ids: str, root: str, xtools: dict, cells_=None, **kw) -> dict:
    q = _queue(w, ids, root=root, **kw)
    q.update(tools=dict(q["tools"], **xtools), entrapment=True, cells=json.loads(json.dumps(cells_ or DWV_CELLS)),
             search_db_sha256=dict(q["search_db_sha256"], entrap_fasta=sha256(w / "bench" / "human_entrap.fasta")))
    return q


def _xreg(q: dict) -> tuple:
    plan, reg = _reg(q)
    plan.update(cells=q["cells"], entrapment=q["entrapment"], tools=q["tools"])
    return plan, reg


def _fake(txt: str) -> str:
    return txt.replace("#@NUMPRESS_LINEAR@", inspect.getsource(numpress_linear))


def _np_refuses(data: bytes) -> None:
    try:
        numpress_linear(data)
    except (ValueError, IndexError):
        die("G-V17", "numpress array undecodable (as mzml_scan counts it)")


def _selftest_extended(C, w: Path, q1: dict, q3: dict) -> None:
    """Extended plans (cells, re-encode, no-op flag, entrapment, charge split) and the pair-compatibility claim."""
    import contextlib, io, yaml
    spx = w / "ceph" / "spx"
    xt = _dwv_world(w)
    if set(xt) != {"digest", "entrapment", "sage_entrap"}:
        C.check("G-V19", "selftest finds bench/entrapment.py and bench/semantic_digest.py", False,
                "run it from the repository (or where /ceph/.../tools holds them)")
        return
    os.environ["FAKE_MSF_SLEEP"] = "0"

    # ---- the two-extractor pair is unchanged
    m0, mx = measure_sha256(), measure_sha256(True)
    C.check("COMPAT", "pair/search/score measurement code is the 1.3.0 code (PAIR_MEASURE_1_3_0; update on purpose only)",
            {k: v[:12] for k, v in m0.items()} == PAIR_MEASURE_1_3_0, {k: v[:12] for k, v in m0.items()})
    C.check("COMPAT", "an extended plan adds a fourth hash (cells) and keeps the other three",
            set(mx) == {"pair", "search", "score", "cells"} and {k: mx[k] for k in m0} == m0)
    C.check("COMPAT", "the cells measurement code is the dwv_stage1 code (CELLS_MEASURE_DWV; update on purpose only)",
            mx["cells"][:12] == CELLS_MEASURE_DWV, mx["cells"][:12])
    plan_p = {k: q1[k] for k in PLAN_KEYS if k != "queues"}
    plan_p["queues"] = {"n1": {"samples": ["A"]}}
    qp = resolve_queue("pp", plan_p, {"samples": {s["id"]: s for s in q1["samples"]}}, "n1")
    C.check("COMPAT", "a plain plan resolves without cells/entrapment: TOOLS, ENGINES, run_pair",
            not extended(qp) and not set(qp) & OPTIONAL_PLAN_KEYS and q_tools(qp) == TOOLS and q_engines(qp) == ENGINES
            and plan_tool_keys(qp) == TOOL_KEYS and db_keys(qp) == DB_KEYS)
    rp = _records(q1)
    C.check("COMPAT", "plain records carry no cells, cells hash or charge split",
            all("cells" not in r and "cells" not in (r.get("measure_sha256") or {}) and "by_charge" not in r for r in rp.values()))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dry_run(q3)
    C.check("COMPAT", "plain dry-run prints nothing of the extended plans",
            not any(x in buf.getvalue() for x in ("extended plan", "G-V17", "reencoded", "entrap", "dwv", "tdf_bin only")))
    C.check("COMPAT", "plain pairs stage the whole .d as before", "files" not in rp["A", "pair"]["stage"])
    mdp = render_table("selftest", *_reg(q1), list(rp.values()))[0]
    C.check("COMPAT", "plain table renders without the extended sections",
            "Peptides by precursor charge" not in mdp and "Entrapment by charge" not in mdp and "Cell outputs" not in mdp)
    C.check("COMPAT", "plain identity carries no cells", "cells" not in build_identity(identity(q1, arm_env(q1)[0])))
    r = subprocess.run([sys.executable, "-", "node-status", base64.b64encode(json.dumps(
        {"root": str(w / "stdin-root"), "records_only": True}).encode()).decode()], input=SELF.read_bytes(),
        capture_output=True, cwd=str(w))
    C.check("COMPAT", "the module imports and serves a node command from stdin (`python3 -`, as remote() runs it)",
            r.returncode == 0 and b"@@JSON " in r.stdout, r.stderr.decode(errors="replace")[-120:])

    # ---- G-V01 extended plan validation
    xq = _xqueue(w, "AB", "x1", xt)
    xplan = {k: xq[k] for k in (PLAN_KEYS | OPTIONAL_PLAN_KEYS) - {"queues"} if k in xq}
    xplan["queues"] = {"n1": {"samples": ["A", "B"]}}
    samples = {s["id"]: {k: s[k] for k in SAMPLE_KEYS} for s in xq["samples"]}

    def pf(pl):
        f = w / ("xreg%s.yaml" % os.urandom(3).hex())
        f.write_text(yaml.safe_dump({"samples": samples, "xp": pl}))
        return f
    C.ok("G-V01", "extended plan (two cells, entrapment) loads", lambda: load_plan("xp", pf(xplan)))
    for what, mut, frag in (
            ("a cell named like a reference arm", lambda pl: pl["cells"].update(dt=pl["cells"]["dwv_default"]), "reserved"),
            ("a cell name with a path separator", lambda pl: pl["cells"].update({"../x": pl["cells"]["dwv_default"]}), "reserved"),
            ("an unknown cell kind", lambda pl: pl["cells"]["dwv_default"].update(kind="weaver"), "unknown kind"),
            ("a cell without wall_cap_h", lambda pl: pl["cells"]["dwv_default"].pop("wall_cap_h"), "needs exactly"),
            ("a cell with an unknown key", lambda pl: pl["cells"]["dwv_default"].update(ram_gb=10), "needs exactly"),
            ("wall_cap_h 0", lambda pl: pl["cells"]["dwv_default"].update(wall_cap_h=0), "wall_cap_h"),
            ("wall_cap_h given as a boolean", lambda pl: pl["cells"]["dwv_default"].update(wall_cap_h=True), "wall_cap_h"),
            ("cell args setting -threads", lambda pl: pl["cells"]["dwv_default"].update(args=["-threads", "8"]), "harness sets"),
            ("cell args not a list of strings", lambda pl: pl["cells"]["dwv_default"].update(args="-x 1"), "list of strings"),
            ("differs_from an unknown cell", lambda pl: pl["cells"]["dwv_pickim"].update(differs_from="dwv_x"), "differs_from"),
            ("differs_from itself", lambda pl: pl["cells"]["dwv_pickim"].update(differs_from="dwv_pickim"), "differs_from"),
            ("a cell arm with a path separator", lambda pl: pl["cells"]["dwv_default"].update(arm="../v1.3.0"), "directory name"),
            ("entrapment: yes (a string)", lambda pl: pl.update(entrapment="yes"), "true or false"),
            ("entrapment without its tools", lambda pl: pl["tools"].pop("sage_entrap"), "tools need exactly"),
            ("cells without the digest tool", lambda pl: pl["tools"].pop("digest"), "tools need exactly"),
            ("entrapment without an entrap_fasta pin", lambda pl: pl["search_db_sha256"].pop("entrap_fasta"), "search_db_sha256"),
            ("empty cells", lambda pl: pl.update(cells={}), "non-empty"),
            ("engines: sage (a string, not a list)", lambda pl: pl.update(engines="sage"), "engines must be"),
            ("engines: [] (no engine)", lambda pl: pl.update(engines=[]), "engines must be"),
            ("engines naming an unknown engine", lambda pl: pl.update(engines=["sage", "comet"]), "engines must be"),
            ("engines with a repeat", lambda pl: pl.update(engines=["sage", "sage"]), "engines must be"),
            ("engines out of ENGINES order", lambda pl: pl.update(engines=["msfragger", "sage"]), "engines must be"),
            ("engines naming the entrapment search", lambda pl: pl.update(engines=["sage", "entrap"]), "engines must be"),
            ("engines: null", lambda pl: pl.update(engines=None), "engines must be"),
            ("engines naming every engine (the default: omit the key)", lambda pl: pl.update(engines=["sage", "msfragger"]),
             "omit the key")):
        pl = json.loads(json.dumps(xplan))
        mut(pl)
        C.abort("G-V01", "extended plan refused: %s" % what, lambda pl=pl: load_plan("xp", pf(pl)), frag)
    for eng in (["sage"], ["msfragger"]):
        C.ok("G-V01", "extended plan with engines %s loads" % eng, lambda eng=eng: load_plan("xp", pf(dict(xplan, engines=eng))))
    qe = resolve_queue("xp", *load_plan("xp", pf(dict(xplan, engines=["sage"]))), "n1")
    C.check("G-V01", "engines reach the queue: Sage and the entrapment search only", q_engines(qe) == ("sage", "entrap")
            and extended(qe) and q_engines(dict(qe, engines=None)) == ENGINES + ("entrap",), q_engines(qe))
    qpe = resolve_queue("pe", dict(plan_p, engines=["sage"]), {"samples": {s["id"]: s for s in q1["samples"]}}, "n1")
    C.check("G-V01", "engines alone make a plan extended (the plain queue always runs both engines), nothing else added",
            extended(qpe) and q_tools(qpe) == TOOLS and q_engines(qpe) == ("sage",) and plan_tool_keys(qpe) == TOOL_KEYS
            and db_keys(qpe) == DB_KEYS and not cells(qpe))
    C.abort("G-V01", "guardtest refused for an extended plan", lambda: _guardtest(dict(xq, plan="x_selftest"), Path(xq["root"])),
            "two-extractor pair only")

    # ---- G-V03 / G-V04 / G-V11 cell arms and identity
    one = lambda arm: dict(xq, cells={"c1": dict(DWV_CELLS["dwv_default"], arm=arm)})
    C.abort("G-V03", "cell env.sh missing", lambda: cell_env(one("nope"), "c1"), "env.sh missing")
    C.abort("G-V03", "cell env.sh exports an OpenMP knob", lambda: cell_env(one("dwv_omp"), "c1"), "itself exports")
    C.abort("G-V03", "DWV_BIN outside the cell arm", lambda: cell_env(one("dwv_outside"), "c1"), "outside the cell arm")
    C.abort("G-V03", "no FileFilter beside DWV_BIN", lambda: cell_env(one("dwv_noff"), "c1"), "FileFilter")
    qb = one("dwv_badprov")
    C.abort("G-V03", "cell provenance lists another sha256 for a lib file",
            lambda: cells_meta(qb, {"c1": cell_env(qb, "c1")}, {"cells": cells_identity(qb)}), "lib/libOpenMS.so")
    (spx / "dwv_unlisted" / "lib").mkdir(parents=True)
    for f in ("bin", "share", "env.sh", "PROVENANCE"):
        (shutil.copytree if f in ("bin", "share") else shutil.copyfile)(spx / "dwv" / f, spx / "dwv_unlisted" / f)
    (spx / "dwv_unlisted" / "lib" / "libOpenMS.so").write_bytes(b"fork dwv")
    (spx / "dwv_unlisted" / "lib" / "libextra.so").write_bytes(b"not published")
    (spx / "dwv_unlisted" / "env.sh").write_text("export DWV_BIN=%s\nexport OPENMS_DATA_PATH=%s\n" % (
        spx / "dwv_unlisted" / "bin" / "diaWeaver", spx / "dwv_unlisted" / "share" / "OpenMS"))
    qu = one("dwv_unlisted")
    C.abort("G-V03", "a lib file the provenance does not list",
            lambda: cells_meta(qu, {"c1": cell_env(qu, "c1")}, {"cells": cells_identity(qu)}), "lib/libextra.so")
    qn = one("dwv_noprov")
    shutil.copytree(spx / "dwv", spx / "dwv_noprov")
    (spx / "dwv_noprov" / "PROVENANCE").unlink()
    (spx / "dwv_noprov" / "env.sh").write_text("export DWV_BIN=%s\nexport OPENMS_DATA_PATH=%s\n" % (
        spx / "dwv_noprov" / "bin" / "diaWeaver", spx / "dwv_noprov" / "share" / "OpenMS"))
    C.abort("G-V03", "cell arm without PROVENANCE",
            lambda: cells_meta(qn, {"c1": cell_env(qn, "c1")}, {"cells": cells_identity(qn)}), "provenance missing")
    qs = one("dwv_badshare")
    C.abort("G-V03", "cell provenance records another data tree (share/OpenMS) than the one in use",
            lambda: cells_meta(qs, {"c1": cell_env(qs, "c1")}, {"cells": cells_identity(qs)}), "share_OpenMS_tree_sha256")
    C.abort("G-V03", "cell OPENMS_DATA_PATH is not the arm's share/OpenMS", lambda: cell_env(one("dwv_nodata"), "c1"),
            "OPENMS_DATA_PATH")
    C.check("G-V03", "the data tree hash follows the publish step's find|sort|sha256sum formula",
            data_tree_sha256(spx / "dwv" / "share" / "OpenMS") == hashlib.sha256(b"".join(
                b"%s  ./%s\n" % (sha256(spx / "dwv" / "share" / "OpenMS" / r).encode(), r.encode())
                for r in ("CHEMISTRY/Elements.xml", "CV/psi-ms.obo"))).hexdigest())
    cenvs = {n: cell_env(xq, n) for n in xq["cells"]}
    cm = C.ok("G-V03", "cell provenance and label resolve", lambda: cells_meta(xq, cenvs, {"cells": cells_identity(xq)}))
    ce = cenvs["dwv_default"]
    C.check("G-V03", "cell label from --help; cell env stripped like the arm's",
            bool(cm) and cm["dwv_default"]["label"] == "diaWeaver 3.5.0-pre-fake" and not any(strip_var(k) for k in ce)
            and "LD_LIBRARY_PATH" not in ce and ce["LC_ALL"] == "C", cm and cm["dwv_default"]["label"])
    envx = arm_env(xq)[0]
    C.check("G-V05", "busy patterns include the cell binary", r"diaWeave[r] -in" in busy_patterns(envx, cenvs))
    ix = identity(xq, envx)
    C.check("G-V11", "extended build identity carries each cell's build",
            set(build_identity(ix).get("cells", {})) == {"dwv_default", "dwv_pickim"})
    for what, f in (("diaWeaver binary", spx / "dwv" / "bin" / "diaWeaver"), ("FileFilter", spx / "dwv" / "bin" / "FileFilter"),
                    ("cell arm lib", spx / "dwv" / "lib" / "libOpenMS.so"),
                    ("cell data file (OPENMS_DATA_PATH)", spx / "dwv" / "share" / "OpenMS" / "CV" / "psi-ms.obo"),
                    ("cell env.sh", spx / "dwv" / "env.sh")):
        orig = f.read_bytes()
        f.write_bytes(orig + b"\n# changed\n")
        C.abort("G-V04", "%s changed across an arm" % what, lambda: check_identity(xq, envx, ix, "during dwv_default"), "changed")
        C.check("G-V11", "%s changed: build identity differs" % what, build_identity(identity(xq, envx)) != build_identity(ix))
        f.write_bytes(orig)

    # ---- extended happy queue: 2 samples, 2 cells, entrapment
    rc = C.ok("G-V16", "extended queue runs", lambda: node_run(xq))
    R = _records(xq)
    tx, ex = list(q_tools(xq)), list(q_engines(xq))
    C.check("G-V16", "both groups ok, every arm ok, rc 0",
            rc == 0 and all(R[s, "pair"]["status"] == "ok" and not R[s, "pair"]["cells_failed"]
                            and all(R[s, "pair"]["arms"][t].get("status", "ok") == "ok" for t in tx) for s in "AB"), rc)
    C.check("G-V09", "reference pair first (alternating), then the cells rotated by queue index",
            R["A", "pair"]["order"] == ["dt", "spx", "dwv_default", "dwv_pickim"]
            and R["B", "pair"]["order"] == ["spx", "dt", "dwv_pickim", "dwv_default"], [R[s, "pair"]["order"] for s in "AB"])
    a = R["A", "pair"]["arms"]["dwv_default"]
    C.check("G-V17", "cell output re-encoded: numpress 24 -> 0, peaks sorted, 12 spectra kept, raw file deleted",
            a["spectra_stats"]["numpress_terms"] == 24 and a["reencoded_stats"]["numpress_terms"] == 0
            and a["reencoded_stats"]["unsorted"] == 0 and a["output"]["count"] == a["raw_output"]["count"] == 12
            and a["output"]["path"].endswith("/reencoded.mzML") and not Path(a["raw_output"]["path"]).exists(), a.get("reencoded_stats"))
    C.check("G-V07", "an extended plan stages analysis.tdf + analysis.tdf_bin only (the raw also has a method folder)",
            R["A", "pair"]["stage"]["files"] == list(STAGE_FILES) and (w / "ceph" / "raw" / "run_A.d" / "run.m").is_dir()
            and (Path(a["cwd"]) / "staged_files.txt").read_text().splitlines() == ["%s 600" % f for f in STAGE_FILES]
            and R["A", "pair"]["stage"]["fingerprint"] == xq["samples"][0]["pin"],
            (R["A", "pair"]["stage"].get("files"), (Path(a["cwd"]) / "staged_files.txt").read_text()))
    tdl = (Path(a["cwd"]) / "tmpdir.txt").read_text().split()
    C.check("G-V14", "cells get a private TMPDIR (0700) inside the cell directory, emptied afterwards; both tools wrote there",
            tdl == [str(Path(a["cwd"]) / "tmp"), "700"] and a["tmpdir"] == tdl[0] and a["tmp_files"] == 2
            and not Path(tdl[0]).exists(), (tdl, a.get("tmp_files")))
    C.check("G-V17", "raw diaWeaver peak order measured: numpress m/z decoded, 12 of 12 unsorted, same m/z after the re-encode",
            a["spectra_stats"]["undecoded"] == 0 and a["spectra_stats"]["unsorted"] == 12
            and a["spectra_stats"]["peak_digest"] is not None
            and a["spectra_stats"]["peak_digest"] == a["reencoded_stats"]["peak_digest"], a.get("spectra_stats"))
    C.check("G-V16", "every arm timed with CPU; the cell's cap recorded and not hit",
            all(R["A", "pair"]["arms"][t]["cpu"]["cpu_s"] == 125.0 for t in tx) and a["wall_cap_s"] == 3600
            and a["stopped"] is None and a["log_count"] == 12)
    C.check("G-V17", "cell statistics: charges 2/3/4, 1/K0 = 0 in 9 of 12, 8 peaks",
            a["spectra_stats"]["charges"] == {"2": 4, "3": 4, "4": 4} and a["spectra_stats"]["im_zero"] == 9
            and a["spectra_stats"]["peaks_median"] == 8, a["spectra_stats"])
    nz = R["A", "pair"]["arms"]["dwv_pickim"].get("noop") or {}
    C.check("G-V18", "a cell that differs from its reference is not flagged",
            nz.get("computed") and not nz.get("flag") and not nz.get("content_equal"), nz)
    C.check("G-V10", "every arm searched by Sage, MSFragger and the entrapment search (24 cells ok)",
            all(R[s, "%s.%s" % (t, e)]["status"] == "ok" for s in "AB" for t in tx for e in ex))
    ss, ms, es = R["A", "dwv_default.sage"], R["A", "dwv_default.msfragger"], R["A", "dt.entrap"]
    C.check("G-V19", "charge split adds up: Sage z1 6 + z2p 25 (targets 6 + 24), MSFragger 15 + 135",
            ss["by_charge"]["z1"] == {"peptides": 6, "target_peptides": 6}
            and ss["by_charge"]["z2p"] == {"peptides": 25, "target_peptides": 24}
            and ms["by_charge"]["z1"]["peptides"] == 15 and ms["by_charge"]["z2p"]["peptides"] == 135
            and ss["measure_sha256"]["cells"] == mx["cells"], (ss.get("by_charge"), ms.get("by_charge")))
    en = es.get("entrapment") or {}
    C.check("G-V19", "entrapment by stratum on the patched diaTracer file: all 30 + 3, z1 6 + 1, z2p 24 + 2",
            es["patched"] == 17 and en["all"]["target"] == 30 and en["all"]["entrap"] == 3 and en["z1"]["target"] == 6
            and en["z1"]["entrap"] == 1 and en["z2p"]["target"] == 24 and en["z2p"]["entrap"] == 2 and es["peptides"] == 30, en)
    est = load_module(xt["entrapment"], "entrapment_selftest")
    whole = est.score(es["result_tsv"], ENTRAP_TAG, en["ratio"])
    C.check("G-V19", "the `all` stratum equals bench/entrapment.py score() on the whole TSV",
            (whole[0], whole[1], whole[2]) == (en["all"]["accepted"], en["all"]["target"], en["all"]["entrap"]), whole[:3])
    C.check("G-V11", "records carry the four measurement hashes", R["A", "pair"]["measure_sha256"] == mx
            and all(R["A", "%s.entrap" % t]["measure_sha256"]["cells"] == mx["cells"] for t in tx))
    C.check("G-V14", "no mzML and no staged copy left after the extended queue",
            not list(Path(xq["root"]).rglob("*.mzML")) and not any((Path(xq["root"]) / "stage").iterdir()))
    md, inc, tot = C.ok("G-V13", "extended table renders", lambda: render_cells_table("x", *_xreg(xq), list(R.values())))
    mainrows = [l for l in md.split("\n## ")[0].splitlines() if l.startswith("| A ") or l.startswith("| B ")]
    C.check("G-V13", "extended table: 2 of 2 complete, 8 arm rows, all sections, no zero in the main rows",
            inc == 0 and tot == 2 and len(mainrows) == 8 and not any("| 0 |" in l for l in mainrows)
            and all(x in md for x in ("## Peptides by precursor charge", "## Entrapment by charge stratum", "## Cell outputs",
                                      "## Per arm, complete samples only", "FileFilter -in pseudo_spectra.mzML",
                                      "diaWeaver 3.5.0-pre-fake", "| A | dwv_default | z1 |")), (inc, tot, len(mainrows)))
    ctxx = {"ident": ix, "tools_sha": install_tools(xq)["sha256"], "measure": mx, "threads": 100,
            "tools": tx, "engines": ex, "cells": xq["cells"]}
    bad = json.loads(json.dumps(R["A", "pair"]))
    bad["arms"]["dwv_pickim"]["status"] = "failed"
    C.check("G-V11", "a record whose cell failed is never adopted, even if it lists an output",
            pair_done(R["A", "pair"], xq["samples"][0], ctxx, Path(xq["root"]))
            and not pair_done(bad, xq["samples"][0], ctxx, Path(xq["root"]))
            and "dwv_pickim" not in (ready_arms(bad, xq["samples"][0], ctxx, Path(xq["root"])) or []))
    n_msf = len((w / "msf_times.log").read_text().splitlines())
    node_run(dict(xq, nonce="xresume"))
    R2 = _records(xq)
    C.check("G-V11", "extended resume skips verified groups and searches",
            all(R2[s, "pair"]["pair_run"] == R[s, "pair"]["pair_run"] for s in "AB")
            and len((w / "msf_times.log").read_text().splitlines()) == n_msf)
    recs = list(R.values())

    def mutated(fn, plan=None):
        rr = json.loads(json.dumps(recs))
        fn({(r["id"], r.get("tool", "pair"), r.get("engine", "pair")): r for r in rr})
        return lambda: render_cells_table("x", plan or _xreg(xq)[0], _xreg(xq)[1], rr)
    C.abort("G-V13", "extended table refuses two diaWeaver builds", mutated(
        lambda m: m["B", "pair", "pair"]["identity"]["cells"]["dwv_default"].update(binary_sha256="x")), "more than one")
    C.abort("G-V13", "extended table refuses two cell labels", mutated(
        lambda m: m["B", "pair", "pair"]["cells_meta"]["dwv_default"].update(label="diaWeaver 9")), "tool label")
    C.abort("G-V13", "extended table refuses records of other cell settings", mutated(
        lambda m: None, dict(_xreg(xq)[0], cells=dict(xq["cells"], dwv_default=dict(DWV_CELLS["dwv_default"], wall_cap_h=2)))),
        "differ from the plan")
    C.abort("G-V13", "extended table refuses an ok cell with 0 spectra", mutated(
        lambda m: m["A", "pair", "pair"]["arms"]["dwv_pickim"]["output"].update(count=0)), "count")

    def no_split(m):                                # killed between a search and its split
        for k, r in m.items():
            if k[2] in ENGINES:
                r.pop("by_charge", None)
    mdp2 = C.ok("G-V13", "extended table renders when ok searches lack their charge split", mutated(no_split))
    C.check("G-V13", "  those searches render as pending and no sample counts as complete",
            bool(mdp2) and mdp2[1] == 2 and "| pending |" in mdp2[0], mdp2 and mdp2[1])
    rq = read_json(rec_path(xq["root"], "A", "spx", "sage"))
    write_json(rec_path(xq["root"], "A", "spx", "sage"), dict(rq, peptides=rq["peptides"] + 1))
    C.check("G-V19", "a charge split that does not add up to the count fails the cell",
            not add_split(xq["root"], "A", "spx", "sage", {"measure": mx})
            and read_json(rec_path(xq["root"], "A", "spx", "sage"))["guard"] == "G-V19")
    write_json(rec_path(xq["root"], "A", "spx", "sage"), dict(rq, status="ok", result_tsv=str(w / "gone.tsv")))
    C.check("G-V19", "a crash in the split (result TSV gone) fails that search cell as CRASH, never the queue",
            not add_split(xq["root"], "A", "spx", "sage", {"measure": mx})
            and read_json(rec_path(xq["root"], "A", "spx", "sage"))["guard"] == "CRASH")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dry_run(xq)
    out = buf.getvalue()
    want = ("order dt -> spx -> dwv_default -> dwv_pickim", "analysis.tdf + analysis.tdf_bin only", "bin/diaWeaver -in", "-threads 100 -bruker:ms1_centroid_mz_ppm 0",
            "FileFilter -in", "reencoded.mzML' -sort >reencode.log", "G-V16", "G-V18: flag dwv_pickim", "sage_entrap.json",
            "dwv_pickim_msfragger", "G-V19")
    C.check("DRY", "extended dry-run prints the cells, re-encode, no-op and entrapment steps",
            all(x in out for x in want), [x for x in want if x not in out])

    # ---- G-V18: a cell equal in content is flagged although its order and ids differ
    xn = _xqueue(w, "C", "x2", xt, cells_={"dwv_a": dict(DWV_CELLS["dwv_default"]),
                                           "dwv_b": dict(DWV_CELLS["dwv_default"], differs_from="dwv_a")})
    os.environ["FAKE_DWV_ALTORDER"] = "/dwv_b"        # another order: the re-encode's first spectrum (dataProcessingRef) differs
    node_run(xn)
    del os.environ["FAKE_DWV_ALTORDER"]
    RN = _records(xn)
    nb = RN["C", "pair"]["arms"]["dwv_b"].get("noop") or {}
    C.check("G-V18", "no-op cell flagged: content digest equal, spectrum-list digest not (order, ids, dataProcessingRef differ)",
            nb.get("flag") is True and nb.get("content_equal") and not nb.get("semantic_equal"), nb)
    mdn = render_cells_table("x", *_xreg(xn), list(RN.values()))[0]
    C.check("G-V18", "the no-op flag reaches the status flags and the table",
            "no-op: content equal to dwv_a" in group_flags(RN["C", "pair"]) and "no-op: content equal to dwv_a" in mdn)

    # ---- G-V16: cell failures, the other cell still runs, the group re-runs whole
    mine = re.escape(str(spx / "dwv" / "bin" / "diaWeave")) + "[r] -in"      # this world's tool only (parallel selftests)
    capped = {n: dict(c, wall_cap_h=0.0005) for n, c in DWV_CELLS.items()}
    fails = {"FAKE_DWV_FAIL": "/C.d&/dwv_default", "FAKE_DWV_MISCOUNT": "/D.d", "FAKE_DWV_NODONE": "/E.d",
             "FAKE_DWV_NOOUT": "/F.d", "FAKE_DWV_ZERO": "/G.d", "FAKE_DWV_SLOW": "/H.d"}
    os.environ.update(fails)
    for sid in "IJK":
        if not (w / "ceph" / "raw" / ("run_%s.d" % sid)).exists():
            _raw(w / "ceph" / "raw", sid)
    xf = _xqueue(w, "CDEFGHI", "x3", xt, cells_=capped)
    real_scan = mzml_scan

    def crashing_scan(path, decode=False):          # a non-guard exception inside one cell (sample I, dwv_default)
        if "/runs/I/" in str(path) and "/dwv_default/" in str(path):
            raise ValueError("injected crash")
        return real_scan(path, decode)
    globals()["mzml_scan"] = crashing_scan
    try:
        rcf = node_run(xf)
    finally:
        globals()["mzml_scan"] = real_scan
    for k in fails:
        del os.environ[k]
    RF = _records(xf)
    cell = lambda sid, n: RF[sid, "pair"]["arms"].get(n) or {}
    msg = lambda sid, n: "[%s] %s" % (cell(sid, n).get("guard"), cell(sid, n).get("message", ""))
    C.check("G-V16", "a failing cell (exit 3) fails alone: the next cell ran, the group is ok with cells_failed",
            cell("C", "dwv_default").get("guard") == "G-V16" and "rc=3" in msg("C", "dwv_default")
            and cell("C", "dwv_pickim").get("status") == "ok" and RF["C", "pair"]["status"] == "ok"
            and RF["C", "pair"]["cells_failed"] == ["dwv_default"], msg("C", "dwv_default"))
    C.check("G-V18", "no-op check impossible when the reference cell failed: flagged",
            (cell("C", "dwv_pickim").get("noop") or {}).get("flag") is True
            and "impossible" in group_flags(RF["C", "pair"]), cell("C", "dwv_pickim").get("noop"))
    C.check("G-V10", "the ok arms of a group with a failed cell are searched, the failed cell is not",
            (RF.get(("C", "dwv_pickim.entrap")) or {}).get("status") == "ok"
            and (RF.get(("C", "dt.msfragger")) or {}).get("status") == "ok" and ("C", "dwv_default.sage") not in RF)
    for sid, frag, what in (("D", "log count", "tool count line differs"), ("E", "final rewrite", "no finalisation line"),
                            ("F", "wrote no pseudo_spectra.mzML", "no output file"), ("G", "count missing or <= 0", "0 spectra"),
                            ("H", "wall cap", "wall cap passed: session killed")):
        C.check("G-V16", "cell %s (both cells of %s)" % (what, sid),
                all(cell(sid, n).get("guard") == "G-V16" and frag in cell(sid, n).get("message", "") for n in capped)
                and RF[sid, "pair"]["cells_failed"] == list(RF[sid, "pair"]["order"][2:]), msg(sid, "dwv_default"))
    C.check("G-V16", "a crash inside one cell (no guard) fails that cell only: CRASH recorded, the next cell ran ok",
            cell("I", "dwv_default").get("guard") == "CRASH" and "injected crash" in msg("I", "dwv_default")
            and cell("I", "dwv_pickim").get("status") == "ok" and RF["I", "pair"]["status"] == "ok"
            and RF["I", "pair"]["cells_failed"] == ["dwv_default"]
            and (RF.get(("I", "dt.sage")) or {}).get("status") == "ok", msg("I", "dwv_default"))
    C.check("G-V16", "the killed cell tool is gone", not busy([mine]))
    C.check("G-V14", "raw cell output kept after a failed cell (re-runnable), listed for purge",
            any(x.endswith("dwv_default/pseudo_spectra.mzML") for x in leftovers(xf["root"])) and rcf == 1)
    mdf = render_cells_table("x", *_xreg(xf), list(RF.values()))[0]
    C.check("G-V13", "failed cells render FAILED G-V16, never a number", mdf.count("FAILED G-V16") >= 5)
    runs_f = {sid: RF[sid, "pair"]["pair_run"] for sid in "CDEFGH"}
    node_run(dict(xf, nonce="xrerun"))
    RF2 = _records(xf)
    C.check("G-V11", "a group with a failed cell re-runs whole on the next launch (same plan), now ok",
            all(RF2[sid, "pair"]["pair_run"] != runs_f[sid] and not RF2[sid, "pair"]["cells_failed"] for sid in "CDEFGH"))
    runs_f = {sid: RF2[sid, "pair"]["pair_run"] for sid in "CDEFGH"}
    node_run(dict(xf, nonce="xsame"))
    C.check("G-V11", "a complete group of the same plan is skipped", all(
        _records(xf)[sid, "pair"]["pair_run"] == runs_f[sid] for sid in "CD"))
    xf["cells"] = {n: dict(c, wall_cap_h=1) for n, c in capped.items()}
    node_run(dict(xf, nonce="xsettings"))
    RF3 = _records(xf)
    C.check("G-V11", "a complete group of other cell settings is not adopted: it re-runs",
            all(RF3[sid, "pair"]["pair_run"] != runs_f[sid] and RF3[sid, "pair"]["status"] == "ok" for sid in "CD"))
    os.environ.update(FAKE_MEMAVAIL="10", FAKE_DWV_SLOW="/A.d")
    xm = _xqueue(w, "A", "x4", xt)
    node_run(xm)
    del os.environ["FAKE_MEMAVAIL"], os.environ["FAKE_DWV_SLOW"]
    RM = _records(xm)
    fake_snap, seen = globals()["proc_snapshot"], {}

    def blip():                                     # under the floor in every other sample of each caller
        k = threading.get_ident()
        seen[k] = seen.get(k, 0) + 1
        return dict(fake_snap(), memavail_kb=10 if seen[k] % 2 else 900)
    xb = _xqueue(w, "A", "x6", xt)
    os.environ["FAKE_DWV_NAP"] = "/A.d"
    globals()["proc_snapshot"] = blip
    try:
        node_run(xb)
    finally:
        globals()["proc_snapshot"] = fake_snap
        del os.environ["FAKE_DWV_NAP"]
    RB = _records(xb)
    C.check("G-V16", "MemAvailable under the floor in every other sample only: no kill (the floor must hold %d samples)"
            % MEM_FLOOR_SAMPLES, all(RB["A", "pair"]["arms"][n].get("status") == "ok" and RB["A", "pair"]["arms"][n]["stopped"]
                                     is None for n in DWV_CELLS) and max(seen.values()) > 2 * MEM_FLOOR_SAMPLES,
            [RB["A", "pair"]["arms"][n].get("message") for n in DWV_CELLS])
    C.check("G-V16", "available memory under the floor: the cell session is killed; the reference arms are flagged",
            all("available memory 1.0%" in RM["A", "pair"]["arms"][n].get("message", "") for n in DWV_CELLS)
            and "during" in group_flags(RM["A", "pair"]) and not busy([mine]),
            RM["A", "pair"]["arms"]["dwv_default"].get("message"))
    # a killed cell's CPU stays in the runner's tree (2026-09-23): with one group SIGKILL the tool was orphaned to init
    # and its whole CPU left the tree at once, which the contention measure booked as foreign. Linux /proc only.
    if sys.platform.startswith("linux") and os.path.exists("/usr/bin/time"):   # the real GNU time: TIME may be a stand-in here
        _k = Path(tempfile.mkdtemp())
        _burn = ["/usr/bin/time", "-v", "-o", str(_k / "t.log"), sys.executable, "-c", "while True: pass"]
        _o0 = proc_snapshot()["ours"]
        _rc, _why = run_capped(_burn, _k, dict(os.environ), _k / "burn.log", 4.0)
        _grew = (proc_snapshot()["ours"] - _o0) / CLK_TCK
        C.check("G-V06", "a killed cell's CPU stays in the runner's process tree (the wrapper reaps the tool before it dies)",
                _why is not None and _grew >= 1.0, "rc %s, stopped %r, own-tree CPU grew %.2f s over a 4-s burn" % (_rc, _why, _grew))
    # the floor counts the evictable ZFS ARC, which the kernel omits from MemAvailable (2026-09-19)
    _arc = Path(tempfile.mkdtemp()) / "arcstats"
    _arc.write_text("name type data\nsize                            4    1218567890123\nc_min                           4    76025168896\n")
    C.check("G-V16", "the floor adds the evictable ZFS ARC (size - c_min), and is 0 without ZFS",
            arc_evictable_kb(str(_arc)) == (1218567890123 - 76025168896) // 1024
            and arc_evictable_kb(str(_arc.parent / "absent")) == 0,
            arc_evictable_kb(str(_arc)))

    # ---- G-V17: the re-encode checks
    ff = {"FAKE_FF_NUMPRESS": "/runs/A/", "FAKE_FF_NOSORT": "/runs/B/", "FAKE_FF_DROP": "/runs/C/",
          "FAKE_FF_CHARGE": "/runs/D/", "FAKE_DWV_NO744": "/E.d", "FAKE_FF_FAIL": "/runs/F/", "FAKE_SAGE_NOCHARGE": "/runs/F/",
          "FAKE_FF_NOMZ": "/runs/G/", "FAKE_FF_SHIFT": "/runs/H/", "FAKE_FF_BADZ": "/runs/I/", "FAKE_DWV_PIC": "/J.d",
          "FAKE_SAGE_BADZ": "/runs/K/"}
    os.environ.update(ff)
    xr = _xqueue(w, "ABCDEFGHIJK", "x5", xt, cells_={"dwv_default": DWV_CELLS["dwv_default"]})
    node_run(xr)
    for k in ff:
        del os.environ[k]
    RR = _records(xr)
    for sid, frag, what in (("A", "numpress term", "numpress left"), ("B", "not m/z-sorted", "peaks unsorted"),
                            ("C", "changed the spectrum count", "a spectrum dropped"),
                            ("D", "changed RT, selected ion m/z, charge", "a charge changed"),
                            ("E", "carry no selected ion m/z", "no selected ion m/z"), ("F", "failed: time rc=1", "the tool failed"),
                            ("G", "1 without an m/z array", "a spectrum lost its m/z array"),
                            ("H", "changed the m/z values", "one peak m/z changed (still sorted, same precursors)"),
                            ("I", "1 precursor values not a number", "a charge that is not a number"),
                            ("J", "cannot be compared", "raw m/z arrays in a numpress kind the harness does not decode")):
        c = RR[sid, "pair"]["arms"]["dwv_default"]
        C.check("G-V17", "re-encode refused: %s" % what, c.get("guard") == "G-V17" and frag in c.get("message", ""), c.get("message"))
    C.check("G-V17", "the raw output is kept when the re-encode fails",
            Path(RR["A", "pair"]["arms"]["dwv_default"]["raw_output"]["path"]).is_file())
    C.check("G-V19", "a Sage TSV without a charge column fails the split and the entrapment search",
            RR["F", "spx.sage"]["guard"] == "G-V19" and RR["F", "spx.entrap"]["guard"] == "G-V19"
            and "charge" in RR["F", "spx.entrap"]["message"], (RR["F", "spx.sage"].get("message"), RR["F", "spx.entrap"].get("message")))
    C.check("G-V19", "a charge that is not an integer refuses the split and the entrapment search; the other searches ran",
            RR["K", "spx.sage"]["guard"] == "G-V19" and "not an integer" in RR["K", "spx.sage"]["message"]
            and RR["K", "spx.msfragger"]["status"] == "ok" and RR["K", "dt.entrap"]["guard"] == "G-V19",
            (RR["K", "spx.sage"].get("message"), RR["K", "dt.entrap"].get("message")))
    purge = node_purge({"root": xr["root"], "lock": xr["lock"]})
    C.check("G-V14", "purge removes the kept cell outputs", bool(purge["removed"]) and not purge["left"], purge)

    # ---- G-V19 units
    tsv = Path(es["result_tsv"])
    C.abort("G-V19", "entrapment FASTA without ENTRAP_ peptides", lambda: entrap_strata(
        tsv, est, str(w / "bench" / "no_entrap.fasta")), "no ENTRAP_")
    C.abort("G-V19", "MSFragger TSV without a charge column", lambda: msf_by_charge(w / "hdr.tsv"), "lacks columns")
    C.check("G-V19", "MSFragger split keeps msf_peptides' count", msf_by_charge(Path(ms["result_tsv"]))["all"]["peptides"]
            == msf_peptides(Path(ms["result_tsv"]))["peptides"] == 150)

    # ---- G-V17 units: the numpress decoder against the fork's own encoder output, and the fake encoder
    import zlib
    vec = zlib.decompress(base64.b64decode("eJxzVPxSxwAEq9gXmtTFdTMzTYldXHBm3QYOvpM5sZY1e1oLnCcqF3GdEi18+C572YaVW+f/5dz7eopAJt+PdQ"
                                           "DLQxrC"))
    C.check("G-V17", "numpress_linear decodes a vector written by the fork's FileConverter exactly as its FileFilter does",
            [repr(v) for v in numpress_linear(vec)] == [
                "1500.7512352320298", "101.07120069482333", "1999.9990005965826", "250.2500004249164", "250.2500004249164",
                "3.500000849832838", "874.441100635505", "874.4410003552301", "1200.0", "612.318070335565",
                "612.318080533559", "1.0"])
    ns = {}
    exec(_fake(FAKE_MZML_LIB), ns)
    vals = [100.0, 99.5, 1500.25, 1500.25, 3.75, 1999.99999, 0.0, 250.125]
    C.check("G-V17", "numpress_linear inverts the fake's encoder (large, negative and zero residuals)",
            numpress_linear(zlib.decompress(ns["np_encode"](vals))) == [int(v * 1e5 + 0.5) / 1e5 for v in vals])
    gm = w / "garbage.mzML"
    ns["write_mzml"](str(gm), [{"id": 1, "rt": 1.0, "sel": 500.0, "sel_ok": True, "z": 2, "im": 0.0, "mz": [100.0, 200.0],
                                "inten": [1.0, 2.0]}])
    txt = gm.read_text()
    gm.write_text(txt.replace(txt.split("<binary>")[1].split("</binary>")[0], base64.b64encode(b"x" * 30).decode(), 1))
    sc = C.ok("G-V17", "mzml_scan on an m/z array of 30 bytes (not a multiple of 8): no crash", lambda: mzml_scan(gm, decode=True))
    C.check("G-V17", "  counted as undecodable, no peak digest", bool(sc) and sc["undecoded"] == 1 and sc["peak_digest"] is None,
            sc and {k: sc[k] for k in ("undecoded", "peak_digest")})
    for what, junk in (("9 bytes", b"\0" * 9), ("a cut residual", vec[:-3])):
        C.abort("G-V17", "a corrupt numpress array is not decoded (%s)" % what, lambda junk=junk: _np_refuses(junk),
                "undecodable")

    # ---- plan key `engines`: a Sage-only plan with one cell and no entrapment (the dwv_pxd029836 shape)
    so = _xqueue(w, "AB", "x7", xt, cells_={"dwv_default": DWV_CELLS["dwv_default"]})
    so.pop("entrapment")
    so.update(engines=["sage"], tools={k: v for k, v in so["tools"].items() if k not in ENTRAP_TOOL_KEYS},
              search_db_sha256={k: v for k, v in so["search_db_sha256"].items() if k != ENTRAP_DB})
    n_msf = len((w / "msf_times.log").read_text().splitlines())
    os.environ["FAKE_SAGE_SLEEP"] = "0.4"
    try:
        rcs = node_run(so)
    finally:
        del os.environ["FAKE_SAGE_SLEEP"]
    RS = _records(so)
    ts = list(q_tools(so))
    C.check("G-V10", "Sage-only plan: every arm searched by Sage and split by charge; no MSFragger run, record or fix step",
            rcs == 0 and ts == ["dt", "spx", "dwv_default"]
            and all(RS[s, "%s.sage" % t]["status"] == "ok" and "by_charge" in RS[s, "%s.sage" % t] for s in "AB" for t in ts)
            and sorted(k[1] for k in RS if k[0] == "A") == ["dt.sage", "dwv_default.sage", "pair", "spx.sage"]
            and len((w / "msf_times.log").read_text().splitlines()) == n_msf
            and not list(Path(so["root"]).rglob("*_msfragger")) and not list(Path(so["root"]).rglob("*_entrap")),
            (rcs, sorted(k[1] for k in RS)))
    C.check("G-V10", "Sage-only plan: the searches run concurrently (search_workers 2): no MSFragger-first serial phase",
            len(search_overlaps(list(RS.values()))) >= 2, sorted(search_overlaps(list(RS.values()))))
    C.check("G-V14", "Sage-only plan: each output deleted once its only engine succeeded; no staged copy left",
            not list(Path(so["root"]).rglob("*.mzML")) and not any((Path(so["root"]) / "stage").iterdir()))
    starts = {k: r["started"] for k, r in RS.items()}
    node_run(dict(so, nonce="sresume"))
    C.check("G-V11", "Sage-only resume: groups and Sage searches verified and skipped (the outputs are gone)",
            {k: r["started"] for k, r in _records(so).items()} == starts)
    splan, sreg = _reg(so)
    splan.update(cells=so["cells"], tools=so["tools"], engines=["sage"])
    md, inc, tot = C.ok("G-V13", "Sage-only table renders", lambda: render_cells_table("s", splan, sreg, list(RS.values()))) \
        or ("", -1, -1)
    cols = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
    sec = {x.split("\n", 1)[0]: x for x in md.split("\n## ")}
    mrows = [cols(l) for l in md.split("\n## ")[0].splitlines() if l.startswith(("| A ", "| B "))]
    crows = [cols(l) for l in sec.get("Peptides by precursor charge", "").splitlines() if l.startswith(("| A ", "| B "))]
    srows = [cols(l) for l in sec.get("Per arm, complete samples only", "").splitlines()[4:] if l.startswith("| ")]
    C.check("G-V13", "Sage-only table: 2/2 complete; 6 arm rows with Sage numbers and ratios, MSFragger `-`; per-charge "
                     "and per-arm rows likewise; the engines line; no entrapment section",
            inc == 0 and tot == 2 and len(mrows) == 6 and len(crows) == 6 and len(srows) == 3
            and all(r[9] not in ("-", "0") and (r[11] == "-") == (r[3] == "diaTracer-2.2.1")
                    and r[12] == r[13] == r[15] == "-" and r[14] != "-" for r in mrows)
            and all(r[2] != "-" and r[6] == r[7] == "-" for r in crows)
            and all(r[9] == r[10] == r[11] == r[12] == "-" and r[7] != "-" for r in srows)
            and "this plan runs sage only" in md and "## Entrapment" not in md,
            (inc, tot, mrows[:1], crows[:1], srows[:1]))
    for what, eng in (("an MSFragger record (engines narrowed after the run)", "msfragger"),
                      ("an entrapment record of a plan without entrapment", "entrap")):
        more = json.loads(json.dumps(list(RS.values()))) + [dict(json.loads(json.dumps(RS["A", "spx.sage"])), engine=eng)]
        C.abort("G-V13", "Sage-only table refuses %s" % what, lambda more=more: render_cells_table("s", splan, sreg, more),
                "does not run")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dry_run(so)
    out = buf.getvalue()
    C.check("DRY", "Sage-only dry-run: engines named, a Sage command for every arm, no MSFragger or fix command",
            "engines sage only" in out and all("%s_sage" % t in out for t in ts) and "patched.mzML" in out
            and "_msfragger" not in out and "fix_mzml_cvparams" not in out and "MSFragger-4.4.1.jar" not in out, out[-300:])
    se = _queue(w, "C", root="x8", engines=["sage"])
    rce = node_run(se)
    RE = _records(se)
    C.check("G-V10", "engines alone (no cells, no entrapment): the group runner runs the pair, then Sage only",
            rce == 0 and RE["C", "pair"]["status"] == "ok" and "cells_failed" in RE["C", "pair"]
            and sorted(RE["C", "pair"]["arms"]) == ["dt", "spx"] and sorted(k[1] for k in RE) == ["dt.sage", "pair", "spx.sage"],
            sorted(k[1] for k in RE))
    eplan, ereg = _reg(se)
    eplan.update(tools=se["tools"], engines=["sage"])
    mde = C.ok("G-V13", "Sage-only table without cells renders (the group's `cells: {}` equals the plan's absent key)",
               lambda: render_cells_table("e", eplan, ereg, list(RE.values())))
    C.check("G-V13", "  complete, two arm rows with Sage numbers, no cell section",
            bool(mde) and mde[1] == 0 and "no cells" in mde[0] and "## Cell outputs" not in mde[0]
            and len([l for l in mde[0].split("\n## ")[0].splitlines() if l.startswith("| C ")]) == 2, mde and mde[1])
    C.abort("G-V13", "  but not against a plan that names a cell", lambda: render_cells_table(
        "e", dict(eplan, cells={"dwv_default": DWV_CELLS["dwv_default"]}), ereg, list(RE.values())), "differ from the plan")
    os.environ["FAKE_MSF_SLEEP"] = "0.3"


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
                    "memavail_kb": int(os.environ.get("FAKE_MEMAVAIL", "900")), "memtotal_kb": 1000}
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

        # ---- extended plans (cells, re-encode, no-op flag, entrapment, charge split) and pair compatibility
        try:
            _selftest_extended(C, w, q1, q3)
        except Exception as x:               # a crash is a FAIL line, never a silently shorter selftest
            import traceback
            C.check("EXT", "extended selftest completed", False, "crashed: %s: %s %s" % (
                type(x).__name__, x, traceback.format_exc().strip().splitlines()[-3][-60:]))
    finally:
        globals().update(saved)
        os.environ.clear()
        os.environ.update(env_saved)
    missing = sorted({"G-V%02d" % i for i in range(1, 20)} - C.fired)
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
