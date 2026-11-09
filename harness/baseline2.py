#!/usr/bin/env python3
"""baseline2.py: the BinAC2 (Slurm) baseline benchmark under the paper rules of harness/corpus2.py. baseline.py,
corpus.py and corpus2.py stay frozen; this file imports them and changes only what the paper rules need.

How: baseline.py is imported and its module global `c` (corpus.py) is rebound to corpus2, so every staging, gate,
time, sampler, search and count call baseline.py makes goes through corpus2. The functions listed in OVERRIDES are
replaced in baseline.py's namespace by the ones below (baseline.py's functions look their callees up there at call
time). Everything else, the Slurm job design, CLI, unit order, resume, the G-B01..G-B07 guards, is baseline.py's code.

Differences against baseline.py:
  - Counts: corpus2's COUNT_RULE (Sage target-only, MSFragger TDC cut after complete equal-score groups) through
    corpus2.run_search, plus corpus2.add_split (per-charge split, G-V19) on every Sage/MSFragger search.
  - Entrapment (plan key `entrapment: true`): corpus2.run_entrap for Sage (`entrap`) and MSFragger (`entrap_msf`) on
    every mzML cell, Wen et al. lower and combined upper bound per charge stratum with r per stratum and bootstrap CIs.
    The plan's tools then need sage_entrap, entrapment (+ msfragger_entrap_params with MSFragger), its
    search_db_sha256 entrap_fasta (+ entrap_msf_db). A cell with its own sage_config/msfragger_params must set
    `entrapment: false` (the entrapment configs are the plan's).
  - Engine pins: plan key `engine_sha256` {sage, msfragger_jar} is REQUIRED (one key per engine the plan runs);
    corpus2.install_tools refuses a run-local engine copy that differs (G-V12); search records carry engine_version,
    run records engine_versions.
  - Measurement hashes: search records carry corpus2's search/score/cells hashes (corpus2.measure_sha256); run
    records carry measure_sha256.run (this harness's run code + corpus2's pair code). Resume of a search needs them.
  - Cell kind `diaumpire` (DIA-UMPIRE SE 2.2.8, mzML input only): `jar`, `params`, `sha256: {jar, params}`, optional
    `java_args`, `env`. Timed: `java -Djava.io.tmpdir=<jnatmp> [java_args] -jar <jar> run.mzML diaumpire_se.params`
    under GNU time, with the pinned params copied run-local and `Thread = p` set per thread count. run.mzML is a hard
    link to the staged input. After the timed window (untimed) its run_Q1/Q2/Q3.mgf become one pseudo.mzML
    (mgf_to_mzml, below), checked by spectrum counts; the searches read that mzML.
  - `manifest`: corpus2.build_manifest over figure records. Baseline records are per (cell, threads, repeat), which
    make_figures.py cannot read, so `manifest --records DIR` also writes DIR/records/ in corpus2's layout:
    <id>.pair.json (the diaspextract cell as arm `spx`, the diatracer cell as `dt`, both at search_at, repeat 0) and
    <id>.<spx|dt>.<sage|msfragger|entrap|entrap_msf>.json. Load it with make_figures.py --records DIR --manifest F.
  - Guards: G-B08 DIA-UMPIRE pins/params, G-B09 DIA-UMPIRE output and the MGF conversion, G-B10 records of another
    counting/entrapment rule (table) and figure export refusals. Usage: harness/BASELINE.md "baseline2.py".

    baseline2.py selftest | dry-run | preflight | submit | status | fetch | table | submit-corpus | corpus-table
    baseline2.py manifest [--plan P[,P2]] [--source remote|DIR] --out FILE [--records DIR] [--spx CELL]
"""
from __future__ import annotations

import argparse, array, base64, functools, hashlib, inspect, json, os, re, shutil, subprocess, sys, tempfile, time, types, zlib
from pathlib import Path
from xml.sax.saxutils import quoteattr

SELF = Path(globals().get("__file__", "baseline2.py")).resolve()
HERE = SELF.parent
if "corpus2" not in sys.modules:                                   # remote(): the bootstrap pre-loads all three
    sys.path.insert(0, str(HERE))
import corpus2 as c  # noqa: E402
import baseline as b  # noqa: E402

Abort, die, die_queue, say = c.Abort, c.die, c.die_queue, c.say
b.c, b.Abort, b.die, b.die_queue, b.say = c, c.Abort, c.die, c.die_queue, c.say    # baseline.py now runs on corpus2
B = dict(vars(b))                                                  # baseline.py's own functions, before the overrides

UMP_KEYS, UMP_OPTIONAL = {"jar", "params", "sha256"}, {"env", "java_args"}
UMP_PARAMS, UMP_INPUT = "diaumpire_se.params", "run.mzML"
UMP_KEEP = re.compile(r"^(time\.log|umpire\.log|%s|pseudo\.mzML)$" % re.escape(UMP_PARAMS))
THREAD_LINE = re.compile(r"^Thread\s*=.*$", re.M)
ENTRAP_ENGINES = {"sage": "entrap", "msfragger": "entrap_msf"}
b.KINDS = dict(b.KINDS, diaumpire=UMP_KEYS)
b.CELL_OPTIONAL = dict(b.CELL_OPTIONAL, diaumpire=UMP_OPTIONAL)
b.CELL_COMMON = b.CELL_COMMON | {"entrapment"}
b.PLAN_KEYS = b.PLAN_KEYS | {"engine_sha256"}
b.OPTIONAL_PLAN_KEYS = b.OPTIONAL_PLAN_KEYS | {"entrapment"}
b.RESERVED_CELLS = b.RESERVED_CELLS | {"entrap_msf", "pair", "spx"}
b.COPY_IGNORE = b.COPY_IGNORE + ("*FS", "*_Q[123]*")              # DIA-UMPIRE's raw-derived intermediates
GUARDS = dict(b.GUARDS, **{
    "G-B08": "DIA-UMPIRE tool: jar or params sha256 differs from the cell's pin, params without exactly one `Thread =` line",
    "G-B09": "DIA-UMPIRE output: a Q1/Q2/Q3 MGF missing or stale, an MGF line that is not a peak, key or block marker, "
             "PEPMASS/RTINSECONDS missing, a charge that is not one positive integer, 0 spectra, or the converted mzML's "
             "spectrum count/peak order/precursors differing from the MGFs",
    "G-B10": "table/manifest: an ok search record of another counting or entrapment rule; figure export without one "
             "diaspextract and one diatracer cell, with different search_at, run code or two plans sharing a sample",
})
SELFTEST_GUARDS = set(GUARDS) | {"G-V02", "G-V03", "G-V06", "G-V08", "G-V10", "G-V12", "G-V13", "G-V14", "G-V19"}
# The run code this file measures with (measure_sha256.run of every run record). Update on purpose only: an edit
# that moves it means new figure records carry another run hash than older ones (manifest refuses the mix).
RUN_MEASURE_PIN = "2559def3cc03"


def harness_sha() -> str:
    """baseline.py + baseline2.py: both run every unit."""
    return hashlib.sha256((c.sha256(b.SELF) + c.sha256(SELF)).encode()).hexdigest()


# ------------------------------------------------------------------------------- plan
def entrap_engines(eng, on: bool) -> list:
    return [ENTRAP_ENGINES[e] for e in eng if on]


def cell_engines(cell: dict) -> list:
    """The searches of one mzML cell: its engines, then the entrapment search of each when entrapment is on."""
    return list(cell["engines"]) + entrap_engines(cell["engines"], cell.get("entrapment"))


def cell_input(cell: dict) -> str:
    return "mzml" if cell["kind"] == "diaumpire" else B["cell_input"](cell)


def validate_cell(n, cell, plan) -> None:
    B["validate_cell"](n, cell, plan)
    if "entrapment" in cell and not isinstance(cell["entrapment"], bool):
        die("G-B01", "cell %s: entrapment must be true or false" % n)
    if cell["kind"] != "diaumpire":
        return
    for k in ("jar", "params"):
        if not (isinstance(cell[k], str) and cell[k].startswith("/")):
            die("G-B01", "cell %s: %s must be an absolute path, not %r" % (n, k, cell[k]))
    pin = cell["sha256"]
    if not (isinstance(pin, dict) and set(pin) == {"jar", "params"} and all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in pin.values())):
        die("G-B01", "cell %s: sha256 needs exactly jar and params as sha256 hex" % n)
    ja = cell.get("java_args", [])
    if not (isinstance(ja, list) and all(isinstance(a, str) for a in ja)) \
            or any(a in ("-jar", "-cp", "-classpath") or a.startswith("-Djava.io.tmpdir") for a in ja):
        die("G-B01", "cell %s: java_args must be strings without -jar/-cp/-Djava.io.tmpdir (the harness sets those): %r" % (n, ja))


def validate_plan(name: str, plan, reg: dict) -> None:
    """baseline.py's G-B01 on the plan's core keys, then the paper keys: entrapment, engine_sha256, and the tools and
    database pins corpus2 needs for them (corpus2.plan_tool_keys / db_keys)."""
    if not isinstance(plan, dict):
        die("G-B01", "no plan section %r in the registry" % name)
    ent, eng = plan.get("entrapment", False), plan.get("engines", list(c.ENGINES))
    view = {"entrapment": ent, "engines": eng if isinstance(eng, list) else None}   # no `cells`: corpus2 would add digest
    core = dict(plan)
    if isinstance(plan.get("tools"), dict):
        want = c.plan_tool_keys(view)
        if set(plan["tools"]) != set(want):
            die("G-B01", "plan %s: tools needs exactly %s (entrapment %s)" % (name, list(want), ent))
        core["tools"] = {k: plan["tools"][k] for k in c.TOOL_KEYS}
    db = plan.get("search_db_sha256")
    if isinstance(db, dict):
        want = c.db_keys(view)
        if set(db) != set(want) or not all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in db.values()):
            die("G-B01", "plan %s: search_db_sha256 needs exactly %s as sha256 hex" % (name, list(want)))
        core["search_db_sha256"] = {k: db[k] for k in c.DB_KEYS}
    B["validate_plan"](name, core, reg)
    if not isinstance(ent, bool):
        die("G-B01", "plan %s: entrapment must be true or false, not %r" % (name, ent))
    pins, want = plan["engine_sha256"], {"sage": "sage", "msfragger": "msfragger_jar"}
    if not (isinstance(pins, dict) and set(pins) == {want[e] for e in eng}
            and all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in pins.values())):
        die("G-B01", "plan %s: engine_sha256 needs exactly %s as sha256 hex" % (name, sorted(want[e] for e in eng)))
    for n, cell in plan["cells"].items():
        if cell.get("entrapment", ent) and (cell.get("sage_config") or cell.get("msfragger_params")):
            die("G-B01", "cell %s: its own sage_config/msfragger_params with entrapment on: the entrapment configs "
                         "are the plan's; set entrapment: false for this cell" % n)


def norm_cells(plan: dict) -> dict:
    out = B["norm_cells"](plan)
    for x in out.values():
        x.setdefault("entrapment", plan.get("entrapment", False))
        if x["kind"] == "diaumpire":
            x.setdefault("java_args", [])
    return out


def resolve(name: str, plan: dict, reg: dict) -> dict:
    q = B["resolve"](name, plan, reg)
    q.update(harness_sha256=harness_sha(), entrapment=plan.get("entrapment", False), engine_sha256=plan["engine_sha256"])
    return q


def corpus_q(q: dict) -> dict:
    """corpus2 reads entrapment, engines and engine_sha256 too (tool keys, database pins, engine pins)."""
    return dict(B["corpus_q"](q), entrapment=q.get("entrapment", False), engines=list(q["engines"]),
                engine_sha256=q.get("engine_sha256"))


# ------------------------------------------------------------------------------- node: DIA-UMPIRE
def umpire_params(src: str, p: int) -> str:
    text = Path(src).read_text()
    if len(THREAD_LINE.findall(text)) != 1:
        die_queue("G-B08", "%s needs exactly one `Thread =` line (DIA-UMPIRE's thread count)" % src)
    return THREAD_LINE.sub("Thread = %d" % p, text)


def cell_tool(q: dict, name: str) -> dict:
    cell = q["cells"][name]
    if cell["kind"] != "diaumpire":
        return B["cell_tool"](q, name)
    env = b.clean_env(q, cell.get("env"))
    for k in ("jar", "params"):
        if not os.path.isfile(cell[k]):
            die_queue("G-B02", "cell %s: DIA-UMPIRE %s missing: %s" % (name, k, cell[k]))
        if c.sha256(cell[k]) != cell["sha256"][k]:
            die_queue("G-B08", "cell %s: %s sha256 %s differs from the pin %s" % (name, k, c.sha256(cell[k])[:16], cell["sha256"][k][:16]))
    umpire_params(cell["params"], 1)
    t = {"kind": "diaumpire", "provenance": None, "deps": {}, "env": env, "exe": cell["jar"], "label": "DIA-Umpire SE (%s)"
         % Path(cell["jar"]).name, "sha256": c.sha256(cell["jar"]), "params_sha256": cell["sha256"]["params"],
         "java": b.check_java(c.java_info(env))}
    t["files"] = [cell["jar"], cell["params"], t["java"]["path"]] + ([cell["env"]] if cell.get("env") else [])
    t["stat"] = b.stat_ident(t["files"])
    return t


def tool_record(t: dict) -> dict:
    return dict(B["tool_record"](t), **({"params_sha256": t["params_sha256"]} if "params_sha256" in t else {}))


def busy_patterns(cts: dict) -> list:
    return B["busy_patterns"](cts) + [b.bracket(Path(t["exe"]).name) for t in cts.values() if t["kind"] == "diaumpire"]


def build(q: dict, name: str, t: dict, staged: Path, adir: Path, p: int, fasta: str) -> tuple:
    cell = q["cells"][name]
    if cell["kind"] != "diaumpire":
        return B["build"](q, name, t, staged, adir, p, fasta)
    java = (t.get("java") or {}).get("path") or "java"
    argv = [c.TIME, "-v", "-o", str(adir / "time.log"), java, "-Djava.io.tmpdir=" + q["jnatmp"]] + cell["java_args"] + \
        ["-jar", cell["jar"], str(adir / UMP_INPUT), str(adir / UMP_PARAMS)]
    return argv, adir, t["env"], adir / "pseudo.mzML", adir / "umpire.log"


def untimed(q, name, key, t, staged, out, p, adir, rec) -> None:
    """DIA-UMPIRE's pre step (untimed): the staged input hard-linked as run.mzML (DIA-UMPIRE writes its MGFs beside
    its input), the pinned params copied with Thread = p. Its post step, the MGF conversion, runs in verify."""
    if q["cells"][name]["kind"] != "diaumpire":
        return B["untimed"](q, name, key, t, staged, out, p, adir, rec)
    if key != "pre":
        return None
    cell = q["cells"][name]
    if c.sha256(cell["params"]) != cell["sha256"]["params"]:
        die_queue("G-B08", "cell %s: params changed since the queue started: %s" % (name, cell["params"]))
    link = adir / UMP_INPUT
    try:
        os.link(staged, link)                          # same $TMPDIR filesystem: no copy
    except OSError:
        shutil.copyfile(staged, link)                  # ponytail: a copy only where hard links fail
    (adir / UMP_PARAMS).write_text(umpire_params(cell["params"], p))
    rec["pre"] = [{"input": str(link), "params_sha256": c.sha256(adir / UMP_PARAMS), "thread_param": p}]
    return None


def mgf_count(path: Path) -> int:
    with open(path, "rb") as f:
        return sum(line.strip() == b"BEGIN IONS" for line in f)


def mgf_blocks(path: Path):
    """(params, [(mz, intensity)]) per BEGIN IONS ... END IONS block. Refused (G-B09): a key outside a block (global
    parameters), a line that is neither key, peak nor marker, a block left open."""
    blk = None
    with open(path, errors="replace") as f:
        for i, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line[0] in "#;!":
                continue
            if line == "BEGIN IONS" and blk is None:
                blk = ({}, [])
            elif line == "END IONS" and blk is not None:
                yield blk
                blk = None
            elif blk is not None and "=" in line and not line[0].isdigit():
                k, v = line.split("=", 1)
                blk[0][k.strip().upper()] = v.strip()
            elif blk is not None:
                xs = line.split()
                try:
                    blk[1].append((float(xs[0]), float(xs[1])))
                except (ValueError, IndexError):
                    die("G-B09", "%s line %d: not a peak line: %r" % (path.name, i, line[:60]))
            else:
                die("G-B09", "%s line %d: %r outside a BEGIN IONS block" % (path.name, i, line[:60]))
    if blk is not None:
        die("G-B09", "%s: a block is not closed by END IONS" % path.name)


def b64(vals) -> bytes:
    a = array.array("d", vals)
    if sys.byteorder != "little":
        a.byteswap()
    return base64.b64encode(zlib.compress(a.tobytes()))


MZML_HEAD = '''<?xml version="1.0" encoding="utf-8"?>
<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0">
<cvList count="2">
<cv id="MS" fullName="Proteomics Standards Initiative Mass Spectrometry Ontology" URI="https://raw.githubusercontent.com/HUPO-PSI/psi-ms-CV/master/psi-ms.obo"/>
<cv id="UO" fullName="Unit Ontology" URI="https://raw.githubusercontent.com/bio-ontology-research-group/unit-ontology/master/unit.obo"/>
</cvList>
<fileDescription><fileContent>
<cvParam cvRef="MS" accession="MS:1000580" name="MSn spectrum" value=""/>
</fileContent></fileDescription>
<softwareList count="1"><software id="baseline2_mgf_to_mzml" version="1">
<cvParam cvRef="MS" accession="MS:1000799" name="custom unreleased software tool" value="baseline2.py mgf_to_mzml"/>
</software></softwareList>
<instrumentConfigurationList count="1"><instrumentConfiguration id="IC1">
<cvParam cvRef="MS" accession="MS:1000031" name="instrument model" value=""/>
</instrumentConfiguration></instrumentConfigurationList>
<dataProcessingList count="1"><dataProcessing id="mgf_conversion"><processingMethod order="0" softwareRef="baseline2_mgf_to_mzml">
<cvParam cvRef="MS" accession="MS:1000544" name="Conversion to mzML" value=""/>
</processingMethod></dataProcessing></dataProcessingList>
<run id="run" defaultInstrumentConfigurationRef="IC1">
<spectrumList count="%d" defaultDataProcessingRef="mgf_conversion">
'''


def mgf_to_mzml(mgfs: list, out: Path) -> dict:
    """MGF blocks -> MS2 spectra of one mzML, in file order (Q1, Q2, Q3), scan numbers 1..N unique across the files.
    Peaks sorted by m/z, intensity <= 0 dropped; PEPMASS -> selected ion and isolation target (its intensity, if
    given, -> peak intensity); CHARGE (one positive integer, `2+` or `2`) -> charge state, none if absent;
    RTINSECONDS (negative -> 0) -> scan start time in seconds; TITLE -> spectrum title (Q level prefixed). Each
    cvParam on its own line and value="" on valueless ones, so fix_mzml_cvparams.py and corpus2.mzml_scan read it.
    Arrays are 64-bit float, zlib. Every MGF must parse (G-B09); the count written must equal the BEGIN IONS count."""
    per = {Path(m).name: mgf_count(Path(m)) for m in mgfs}
    total, n, dropped, peaks = sum(per.values()), 0, 0, 0
    if total <= 0:
        die("G-B09", "DIA-UMPIRE wrote 0 spectra in %s" % sorted(per))
    with open(out, "w") as f:
        f.write(MZML_HEAD % total)
        for m in mgfs:
            ql = re.search(r"_(Q\d)\.mgf$", str(m))
            for prm, pk in mgf_blocks(Path(m)):
                try:
                    pm = prm["PEPMASS"].split()
                    mz, rt = float(pm[0]), max(0.0, float(prm["RTINSECONDS"]))
                    pi = float(pm[1]) if len(pm) > 1 else None
                except (KeyError, ValueError, IndexError):
                    die("G-B09", "%s spectrum %d: PEPMASS or RTINSECONDS missing or not a number" % (Path(m).name, n + 1))
                z = prm.get("CHARGE")
                if z is not None and not re.fullmatch(r"[1-9]\d*\+?", z):
                    die("G-B09", "%s spectrum %d: CHARGE %r is not one positive charge" % (Path(m).name, n + 1, z))
                keep = sorted(x for x in pk if x[1] > 0)
                dropped += len(pk) - len(keep)
                peaks += len(keep)
                mzb, inb = b64([x[0] for x in keep]), b64([x[1] for x in keep])
                cv = lambda acc, nm, v="", unit="": '<cvParam cvRef="MS" accession="%s" name="%s" value=%s%s/>\n' % (
                    acc, nm, quoteattr(str(v)), unit)
                mzu = ' unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"'
                f.write('<spectrum index="%d" id="scan=%d" defaultArrayLength="%d">\n' % (n, n + 1, len(keep)))
                f.write(cv("MS:1000511", "ms level", 2) + cv("MS:1000580", "MSn spectrum") + cv("MS:1000127", "centroid spectrum"))
                f.write(cv("MS:1000796", "spectrum title", "%s:%s" % (ql.group(1) if ql else Path(m).stem, prm.get("TITLE", ""))))
                f.write('<scanList count="1">\n' + cv("MS:1000795", "no combination") + "<scan>\n")
                f.write(cv("MS:1000016", "scan start time", repr(rt), ' unitCvRef="UO" unitAccession="UO:0000010" unitName="second"'))
                f.write('</scan>\n</scanList>\n<precursorList count="1">\n<precursor>\n<isolationWindow>\n')
                f.write(cv("MS:1000827", "isolation window target m/z", repr(mz), mzu))
                f.write('</isolationWindow>\n<selectedIonList count="1">\n<selectedIon>\n')
                f.write(cv("MS:1000744", "selected ion m/z", repr(mz), mzu))
                if z is not None:
                    f.write(cv("MS:1000041", "charge state", int(z.rstrip("+"))))
                if pi is not None:
                    f.write(cv("MS:1000042", "peak intensity", repr(pi), ' unitCvRef="MS" unitAccession="MS:1000131" unitName="number of detector counts"'))
                f.write('</selectedIon>\n</selectedIonList>\n<activation>\n' + cv("MS:1000133", "collision-induced dissociation"))
                f.write('</activation>\n</precursor>\n</precursorList>\n<binaryDataArrayList count="2">\n')
                for data, acc, nm, unit in ((mzb, "MS:1000514", "m/z array", mzu),
                                            (inb, "MS:1000515", "intensity array", ' unitCvRef="MS" unitAccession="MS:1000131" unitName="number of detector counts"')):
                    f.write('<binaryDataArray encodedLength="%d">\n' % len(data) + cv("MS:1000523", "64-bit float")
                            + cv("MS:1000574", "zlib compression") + cv(acc, nm, "", unit))
                    f.write("<binary>%s</binary>\n</binaryDataArray>\n" % data.decode())
                f.write("</binaryDataArrayList>\n</spectrum>\n")
                n += 1
        f.write("</spectrumList>\n</run>\n</mzML>\n")
    if n != total:
        die("G-B09", "converted %d spectra but the MGFs hold %d BEGIN IONS" % (n, total))
    return {"spectra": n, "per_file": per, "peaks": peaks, "dropped_nonpositive": dropped}


def verify(q, name, t, out: Path, adir: Path, log: Path, t0: float) -> dict:
    """DIA-UMPIRE (untimed, after the run): Q1..Q3 fresh, converted, and the mzML checked against the MGFs (count via
    verify_mzml and mzml_scan, sorted and decodable m/z arrays, a selected ion on every spectrum). Only logs, the
    params and pseudo.mzML stay in the run dir."""
    if q["cells"][name]["kind"] != "diaumpire":
        return B["verify"](q, name, t, out, adir, log, t0)
    try:
        mgfs = [adir / ("%s_Q%d.mgf" % (UMP_INPUT[:-5], i)) for i in (1, 2, 3)]
        for m in mgfs:
            if not m.is_file() or m.stat().st_mtime <= t0:
                die("G-B09", "%s: %s missing or stale" % (name, m.name))
        conv = mgf_to_mzml(mgfs, out)
        o = c.verify_mzml(out, t0)
        sc = c.mzml_scan(out, decode=True)
        bad = {k: sc[k] for k in ("unsorted", "undecoded", "length_mismatch", "missing_mz", "bad_values", "missing_selected_ion") if sc[k]}
        if not o["count"] == sc["spectra"] == conv["spectra"] or sc["peaks_total"] != conv["peaks"] or bad:
            die("G-B09", "%s: mzML count %s / scanned %s / MGF %s spectra, peaks %s vs %s, %s" % (
                name, o["count"], sc["spectra"], conv["spectra"], sc["peaks_total"], conv["peaks"], bad or "ok"))
        thr = re.findall(r"^Thread\s*=\s*(\d+)", (adir / UMP_PARAMS).read_text(), re.M)
        return {"output": o, "log_count": conv["spectra"], "mgf": conv, "umpire_threads": int(thr[0]),
                "charges": sc["charges"]}
    finally:
        for f in adir.iterdir():
            if not UMP_KEEP.match(f.name):
                c.remove_tree(f) if f.is_dir() else f.unlink()


# ------------------------------------------------------------------------------- node: searches under corpus2
@functools.lru_cache(maxsize=None)
def measure() -> dict:
    """corpus2's measurement hashes (search/score/cells as its extended plans) + `run`: the code that times and
    verifies a baseline unit (baseline.py's, this file's overrides, corpus2's pair code)."""
    m = c.measure_sha256(True)
    h = hashlib.sha256(m["pair"].encode())
    for fn in (B["run_one"], B["run_sample"], B["stage_input"], B["prewarm"], B["check_drift"], B["clean_env"], B["fill"],
               B["cpulist"], B["diann_counts"], B["build"], B["verify"], B["untimed"], B["cell_tool"], B["DIANN_ARGS"],
               build, verify, untimed, cell_tool, umpire_params, mgf_count, mgf_blocks, mgf_to_mzml, b64, MZML_HEAD):
        h.update((inspect.getsource(fn) if callable(fn) else repr(fn)).encode())
    return dict(m, run=h.hexdigest())


def searches_done(q: dict, root: Path, sid: str, name: str, run_id: str) -> bool:
    m = measure()
    for e in cell_engines(q["cells"][name]):
        r = c.read_json(root / "records" / ("%s.%s.%s.json" % (sid, b.search_tool(q, name), e)))
        rm = (r or {}).get("measure_sha256") or {}
        if not (r and r.get("status") == "ok" and r.get("pair_run") == run_id and all(rm.get(k) == m[k] for k in ("search", "score", "cells"))):
            return False
    return True


def cell_tools(q: dict, name: str, tools: dict, root: Path) -> dict:
    return dict(B["cell_tools"](q, name, tools, root), versions=tools["versions"])


def _node_run(q: dict, root: Path) -> int:
    """baseline.py's _node_run with corpus2's searches: target-only counts + per-charge split, entrapment searches,
    engine pins, measurement hashes in every record."""
    (root / ("runner-%s.pid" % q["nonce"])).write_text("%d\n" % os.getpid())
    if q.get("corpus_sha256") and c.sha256(c.SELF) != q["corpus_sha256"]:
        die_queue("G-B01", "corpus2.py beside this runner differs from the one the queue was resolved with")
    if q.get("harness_sha256") != harness_sha():
        die_queue("G-B01", "baseline.py/baseline2.py beside this runner differ from the ones the queue was resolved with")
    try:
        Path(q["jnatmp"]).mkdir(parents=True, exist_ok=True)
        tempfile.NamedTemporaryFile(dir=q["jnatmp"]).close()
    except OSError as x:
        die_queue("G-V15", "jnatmp %s not writable: %s" % (q["jnatmp"], x))
    c.mem_available_kb()
    c.remove_tree(root / "stage")
    mine = {s["id"]: b.units(q, s) for s in q["samples"]}
    facts = b.node_facts()
    big = sorted({p for u in mine.values() for _, p, _ in u if p > (facts["affinity_cpus"] or 0)})
    if big:
        die_queue("G-B01", "thread counts %s exceed the %s CPUs this job may use on %s" % (big, facts["affinity_cpus"], facts["host"]))
    cq = corpus_q(dict(q, root=str(root)))
    base = b.clean_env(q)
    pre = c.preflight(cq, base)
    if "msfragger" in q["engines"] or any(x["kind"] in ("diatracer", "diaumpire") for x in q["cells"].values()):
        b.check_java(c.java_info(base))
    tools = c.install_tools(cq)                        # G-V12: run-local copies, database AND engine pins, versions
    m = measure()
    facts.update(measure_sha256={"run": m["run"]}, engine_versions=tools["versions"])   # run_one copies facts into each record
    cts = {n: cell_tool(q, n) for n in q["cells"]}
    patterns = busy_patterns(cts)
    fasta = tools["paths"]["sage_fasta"]
    say("QUEUE_START plan %s host %s job %s nonce %s units %d cells %s python %s java %s run %s search %s score %s%s" % (
        q["plan"], facts["host"], facts["slurm_job_id"], q["nonce"], sum(map(len, mine.values())), ",".join(q["cells"]),
        pre["python"], pre["java"]["version"], m["run"][:8], m["search"][:8], m["score"][:8],
        " entrapment" if q.get("entrapment") else ""))
    failed = sum(b.run_sample(q, s, cts, patterns, fasta, facts) for s in q["samples"])
    ctx = {"measure": m, "ident": {"java": c.java_info(base)}}
    # ponytail: no corpus2.rescore (re-counting kept TSVs after a COUNT_RULE change): a new score hash re-runs the search
    for s in q["samples"]:
        for name, cell in q["cells"].items():
            if cell["kind"] == "diann" or (name, cell["search_at"], 0) not in mine[s["id"]]:
                continue
            engines = cell_engines(cell)
            r0 = c.read_json(b.rpath(root, s["id"], name, cell["search_at"], 0))
            if not (r0 and r0.get("status") == "ok"):
                failed += len(engines)
                continue
            st, ctools = b.search_tool(q, name), cell_tools(q, name, tools, root)
            pair, sctx = {"pair_run": r0["run_id"], "arms": {st: {"output": r0["output"]}}}, {"tools_sha": ctools["sha256"], "measure": m}
            for e in engines:
                if c.search_done(c.read_json(root / "records" / ("%s.%s.%s.json" % (s["id"], st, e))), pair, sctx):
                    continue
                if e.startswith("entrap"):
                    ok = c.run_entrap(cq, s, st, pair, ctools, base, ctx, "sage" if e == "entrap" else "msfragger")
                else:
                    ok = c.run_search(cq, s, st, e, pair, ctools, base, ctx) and c.add_split(root, s["id"], st, e, ctx)
                failed += not ok
            if searches_done(q, root, s["id"], name, r0["run_id"]):
                Path(r0["output"]["path"]).unlink(missing_ok=True)
    left = sorted(str(p.relative_to(root)) for p in (root / "runs").rglob("*.mzML")) if (root / "runs").is_dir() else []
    msg = "failed %d mzml_left %d" % (failed, len(left))
    (root / ("QUEUE_DONE-%s" % q["nonce"])).write_text(msg + "\n")
    say("QUEUE_DONE " + msg)
    return 0 if failed == 0 else 1


# ------------------------------------------------------------------------------- table and figure records
def rule_guard(recs: list) -> None:
    """G-B10: an ok search record counted by another rule (corpus.py's target+decoy, an older entrapment estimator)
    never enters a corpus2 table or figure."""
    for r in recs:
        if r.get("kind") != "search" or r.get("status") != "ok":
            continue
        if r.get("count_rule") != c.COUNT_RULE:
            die("G-B10", "%s %s %s: counted by rule %r, not corpus2's" % (r["id"], r["tool"], r["engine"], r.get("count_rule")))
        if str(r["engine"]).startswith("entrap") and (r.get("entrapment") or {}).get("rule") != c.ENTRAP_RULE:
            die("G-B10", "%s %s %s: entrapment by another estimator" % (r["id"], r["tool"], r["engine"]))


def render(name: str, plan: dict, reg: dict, recs: list) -> tuple:
    """baseline.py's table (G-B06) on corpus2 records, plus the entrapment bounds of each mzML cell; a missing
    entrapment search makes the table incomplete like a missing search."""
    rule_guard(recs)
    out, _, _ = B["render"](name, plan, reg, recs)
    cells = norm_cells(plan)
    runs = {(r["id"], r["cell"], r["threads"], r["rep"]): r for r in recs if r.get("kind") == "baseline_run"}
    srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r.get("kind") == "search"}
    out.update(count_rule=c.COUNT_RULE, entrap_rule=c.ENTRAP_RULE, entrapment=[])
    for row in out["rows"]:
        cell = cells[row["cell"]]
        r0 = runs.get((row["sample"], row["cell"], cell["search_at"], 0))
        if cell["kind"] == "diann" or not (r0 and r0.get("status") == "ok"):
            continue
        for e in entrap_engines(cell["engines"], cell["entrapment"]):
            sr = srch.get((row["sample"], b.search_tool({"cells": cells}, row["cell"]), e))
            if not (sr and sr.get("status") == "ok" and sr.get("pair_run") == r0["run_id"]):
                out["missing"].append("%s %s search %s %s" % (row["sample"], row["cell"], e, "[%s] %s" % (
                    sr.get("guard"), sr.get("message")) if sr else "not run"))
                continue
            en = sr["entrapment"]
            row["ids"][e + "_upper_pct"] = en["all"]["upper_pct"]
            for st in ("all", "z1", "z2p"):
                out["entrapment"].append(dict(en[st], sample=row["label"], cell=row["cell"], search=e, stratum=st,
                                              ratio=en["ratios"][st]))
    return out, markdown(out), not out["missing"]


def markdown(o: dict) -> str:
    md = B["markdown"](o)
    if "count_rule" not in o:                          # baseline.py's render calls this before render() adds them
        return md
    pct = lambda v: "-" if v is None else "%.2f" % v
    L = ["", "## Rules", "", "- Peptides: `%s`" % o["count_rule"], "- Entrapment: `%s`" % o["entrap_rule"], ""]
    if o["entrapment"]:
        L += ["## Entrapment (1 % FDR by each engine's own rule)", "",
              "| sample | cell | search | stratum | accepted | target | entrapment | r | lower % | lower 95% CI | upper % | upper 95% CI |",
              "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for x in o["entrapment"]:
            L.append("| %s | %s | %s | %s | %d | %d | %d | %.4f | %s | %s-%s | %s | %s-%s |" % (
                x["sample"], x["cell"], x["search"], x["stratum"], x["accepted"], x["target"], x["entrap"], x["ratio"],
                pct(x["lower_pct"]), pct(x["lower_ci_pct"][0]), pct(x["lower_ci_pct"][1]), pct(x["upper_pct"]),
                pct(x["upper_ci_pct"][0]), pct(x["upper_ci_pct"][1])))
    return md + "\n".join(L) + "\n"


def figure_records(name: str, plan: dict, reg: dict, recs: list, spx=None) -> dict:
    """{file name: record} in corpus2's layout for make_figures.py. Per sample: the `search_at` repeat-0 runs of the
    diaspextract cell (`spx`) and the diatracer cell (`dt`) become one pair record (pair_run "<spx run>+<dt run>",
    status failed if either run failed, so a failure cannot vanish from the figures); their search records are
    renamed to the tool names spx/dt with that pair_run (the cell's run id kept as cell_run). Samples not yet run
    are left out (make_figures.py --samples finds them)."""
    out_tab, _, _ = render(name, plan, reg, recs)     # every table guard first (G-B06, G-B10)
    cells = norm_cells(plan)
    spxs = [n for n, x in cells.items() if x["kind"] == "diaspextract" and (spx is None or n == spx)]
    dts = [n for n, x in cells.items() if x["kind"] == "diatracer"]
    if len(spxs) != 1 or len(dts) != 1:
        die("G-B10", "plan %s: figure records need one diaspextract cell (--spx to pick) and one diatracer cell, not %s / %s"
            % (name, spxs, dts))
    (sn, sc), (dn, dc) = (spxs[0], cells[spxs[0]]), (dts[0], cells[dts[0]])
    if sc["search_at"] != dc["search_at"] or sc["engines"] != dc["engines"] or sc["entrapment"] != dc["entrapment"]:
        die("G-B10", "plan %s: cells %s and %s differ in search_at, engines or entrapment: not one pair" % (name, sn, dn))
    runs = {(r["id"], r["cell"], r["threads"], r["rep"]): r for r in recs if r.get("kind") == "baseline_run"}
    srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r.get("kind") == "search"}
    arm_keys = ("status", "guard", "message", "host", "threads", "run_id", "start_epoch", "wall_s", "peak_rss_kb", "cpu_s",
                "cpu_util", "output", "during", "gate", "contended", "tool", "cmd")
    out = {}
    for sid in plan["samples"]:
        rs, rd = runs.get((sid, sn, sc["search_at"], 0)), runs.get((sid, dn, dc["search_at"], 0))
        if not (rs and rd):
            continue
        ok = rs.get("status") == "ok" and rd.get("status") == "ok"
        if ok and rs["measure_sha256"]["run"] != rd["measure_sha256"]["run"]:
            die("G-B10", "sample %s: the spx and dt runs were measured by different run code" % sid)
        pr = "%s+%s" % (rs["run_id"], rd["run_id"])
        out["%s.pair.json" % sid] = {
            "kind": "pair", "id": sid, "sample": rs["sample"], "pair_run": pr, "threads": sc["search_at"],
            "label": rs.get("tool", {}).get("label"), "status": "ok" if ok else "failed",
            "guard": None if ok else (rs if rs.get("status") != "ok" else rd).get("guard"),
            "message": None if ok else (rs if rs.get("status") != "ok" else rd).get("message"),
            "measure_sha256": {"pair": rs.get("measure_sha256", {}).get("run")}, "gate": {"contended": bool(rs.get("gate", {}).get("contended") or rd.get("gate", {}).get("contended"))},
            "arms": {"spx": {k: rs.get(k) for k in arm_keys}, "dt": {k: rd.get(k) for k in arm_keys}},
            "source": "baseline2", "plan": name, "cells": {"spx": sn, "dt": dn}, "harness_sha256": rs.get("harness_sha256"),
            "corpus_sha256": rs.get("corpus_sha256"), "engine_versions": rs.get("engine_versions")}
        for tool, cn, r0 in (("spx", sn, rs), ("dt", dn, rd)):
            for e in cell_engines(cells[cn]):
                sr = srch.get((sid, b.search_tool({"cells": cells}, cn), e))
                if sr and sr.get("pair_run") == r0["run_id"]:
                    out["%s.%s.%s.json" % (sid, tool, e)] = dict(sr, tool=tool, pair_run=pr, cell=cn, cell_run=r0["run_id"])
    return out


def cmd_manifest(args) -> int:
    plans, fig = args.plan.split(","), {}
    for name in plans:
        plan, reg = b.load_plan(name, args.registry)
        got = figure_records(name, plan, reg, b.records_from(args, plan, plan["results"]), args.spx)
        clash = sorted(set(got) & set(fig))
        if clash:
            die("G-B10", "plans %s share sample records %s" % (plans, clash[:3]))
        fig.update(got)
    m = c.build_manifest(list(fig.values()), plans)   # G-V13: one label, one code, one tool set per scheme
    Path(args.out).write_text(json.dumps(m, indent=1, sort_keys=True))
    if args.records:
        for fn, r in fig.items():
            c.write_json(Path(args.records) / "records" / fn, r)
    print("wrote %s: %d samples, %d schemes%s" % (args.out, len(m["samples"]), len(m["tools_sha256_by_scheme"]),
                                                  ", %d figure records under %s/records" % (len(fig), args.records) if args.records else ""))
    return 0


# ------------------------------------------------------------------------------- laptop side: shipping four files
def files() -> list:
    return [b.SELF, SELF, Path(b.c.SELF).parent / "corpus.py", c.SELF]


def remote(host: str, python: str, cmd: str, obj):
    """baseline2.py, baseline.py, corpus.py and corpus2.py over stdin on the login node (read-only)."""
    enc = lambda p: base64.b64encode(Path(p).read_bytes()).decode()
    boot = "import base64, sys, types\n" + "".join(
        "m = types.ModuleType(%r)\nexec(compile(base64.b64decode('%s'), %r, 'exec'), m.__dict__)\nsys.modules[%r] = m\n"
        % (mod, enc(HERE / (mod + ".py")), mod + ".py", mod) for mod in ("corpus", "corpus2", "baseline")) + \
        "sys.argv = ['baseline2.py'] + sys.argv[1:]\nexec(compile(base64.b64decode('%s'), 'baseline2.py', 'exec'), {'__name__': '__main__'})\n" % enc(SELF)
    arg = base64.b64encode(json.dumps(obj).encode()).decode()
    r = subprocess.run(c.SSH + [host, python, "-", cmd, arg], input=boot.encode(), capture_output=True)
    for line in reversed(r.stdout.decode(errors="replace").splitlines()):
        if line.startswith("@@JSON "):
            res = json.loads(line[7:])
            if isinstance(res, dict) and set(res) == {"abort", "guard"}:
                die(res["guard"], "%s: %s" % (host, res["abort"]))
            return res
    sys.exit("remote %s on %s failed (rc %d): %s" % (cmd, host, r.returncode, r.stderr.decode(errors="replace")[-600:]))


def sbatch_script(name, cl, results, hdir, spec) -> str:
    return B["sbatch_script"](name, cl, results, hdir, spec).replace("/baseline.py job --spec", "/baseline2.py job --spec")


def harness_dir(results: str) -> str:
    return "%s/harness/b2-%s" % (results, harness_sha()[:8] + c.sha256(c.SELF)[:8])


def submit(cl: dict, results: str, specs: list, dry: bool, out=print) -> int:
    """baseline.py's submit, shipping all four files to the content-named harness dir."""
    hdir = harness_dir(results)
    scripts = [(name, "%s/jobs/%s.json" % (results, name), "%s/jobs/%s.sbatch" % (results, name), spec) for name, spec in specs]
    if dry:
        for name, sp, sb, spec in scripts:
            out("== job %s\n%s" % (name, sbatch_script(name, cl, results, hdir, sp)))
        return 0
    h = cl["host"]
    c.ssh(h, "mkdir -p %s %s/jobs %s/records && chmod 700 %s" % (b.shlex.quote(hdir), results, results, results))
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        for name, sp, sb, spec in scripts:
            (t / Path(sp).name).write_text(json.dumps(spec, indent=1))
            (t / Path(sb).name).write_text(sbatch_script(name, cl, results, hdir, sp))
        if subprocess.run(["scp", "-q", "-o", "ConnectTimeout=20"] + [str(p) for p in files()] + ["%s:%s/" % (h, hdir)]).returncode:
            sys.exit("scp of the harness to %s failed" % h)
        jf = [str(t / Path(x).name) for _, sp, sb, _ in scripts for x in (sp, sb)]
        if subprocess.run(["scp", "-q", "-o", "ConnectTimeout=20"] + jf + ["%s:%s/jobs/" % (h, results)]).returncode:
            sys.exit("scp of the job files to %s failed" % h)
    ids = c.ssh(h, " && ".join("sbatch --parsable %s" % b.shlex.quote(sb) for _, _, sb, _ in scripts)).split()
    for (name, _, _, _), jid in zip(scripts, ids):
        out("SUBMITTED %s job %s" % (name, jid))
    return 0 if len(ids) == len(scripts) else 1


def dry_run(q: dict, out=print) -> None:
    """baseline.py's dry run (its cmd/diann/extractor lines), then the DIA-UMPIRE units and the corpus2 searches."""
    lines = []
    plain = dict(q, cells={n: x for n, x in q["cells"].items() if x["kind"] != "diaumpire"})
    if plain["cells"]:
        B["dry_run"](plain, lines.append)
    for x in lines:
        if not x.startswith("[search]"):
            out(x)
    root = Path("$TMPDIR/job-%s" % q["nonce"])
    q = dict(q, root=str(root), jnatmp="$TMPDIR/jnatmp")
    # ponytail: search lines show the plan's configs; a cell's own sage_config/msfragger_params is copied run-local on the node
    tp = {k: str(root / "tools" / ("sage/sage" if k == "sage" else Path(v).name)) for k, v in q["tools"].items()}
    for s in q["samples"]:
        mine = b.units(q, s)
        staged = root / "stage" / ("%s-<tag>" % s["id"]) / (s["id"] + (".d" if b.sample_input(s["raw"]) == "d" else ".mzML"))
        for seq, (n, p, rep) in enumerate(mine):
            if q["cells"][n]["kind"] == "diaumpire":
                adir = root / "runs" / s["id"] / ("%s-p%d-r%d-<stamp>" % (n, p, rep))
                argv = build(q, n, {"env": {}}, staged, adir, p, "")[0]
                out("[%02d] %s p=%d r=%d  ln %s %s/%s; %s with Thread = %d; %s; then Q1..Q3.mgf -> pseudo.mzML" % (
                    seq, n, p, rep, staged, adir, UMP_INPUT, q["cells"][n]["params"], p, b.shlex.join(map(str, argv))))
        for n, cell in q["cells"].items():
            if cell["kind"] == "diann" or (n, cell["search_at"], 0) not in mine:
                continue
            st = b.search_tool(q, n)
            sdir = root / "runs" / s["id"] / ("%s-p%d-r0-<stamp>" % (n, cell["search_at"])) / "search"
            mz = sdir.parent / {"diatracer": "%s_diatracer.mzML" % s["id"], "diaspextract": "pseudo.mzML",
                                "diaumpire": "pseudo.mzML"}.get(cell["kind"], cell.get("out", ""))
            for e in cell_engines(cell):
                d = sdir / ("%s_%s" % (st, e))
                tpe = dict(tp, sage_config=tp.get("sage_entrap"), msfragger_params=tp.get(c.ENTRAP_MSF_KEY)) if e.startswith("entrap") else tp
                inp = d / "patched.mzML" if st == "dt" else mz
                patch = "%s && " % b.shlex.join(c.cmd_patch(tp, mz, inp, "patch.time")) if st == "dt" else ""
                if e in ("sage", "entrap"):
                    out("[search] %s %s: cd %s && %s%s" % (n, e, d, patch, b.shlex.join(c.cmd_sage(tpe, inp, d, "engine.time"))))
                else:
                    out("[search] %s %s: cd %s && %s && ln -s fixed.mzML in.mzML && %s" % (
                        n, e, d, b.shlex.join(c.cmd_fix(tp, mz, d / "fixed.mzML", "fix.time")), b.shlex.join(c.cmd_msf(tpe, "engine.time"))))


OVERRIDES = ("cell_input", "validate_cell", "validate_plan", "norm_cells", "resolve", "corpus_q", "cell_tool", "tool_record",
             "busy_patterns", "build", "untimed", "verify", "searches_done", "cell_tools", "_node_run", "render", "markdown",
             "remote", "sbatch_script", "harness_dir", "submit", "dry_run")
for _k in OVERRIDES:
    setattr(b, _k, globals()[_k])


# ------------------------------------------------------------------------------- selftest
FAKE_UMPIRE = c.FAKE_HEAD + r'''
i = sys.argv.index("-jar")
jar, mz, params = sys.argv[i + 1], sys.argv[i + 2], sys.argv[i + 3]
assert os.path.isfile(mz) and os.path.isfile(params) and any(a.startswith("-Djava.io.tmpdir=") for a in sys.argv), sys.argv
th = re.findall(r"^Thread\s*=\s*(\d+)\s*$", open(params).read(), re.M)
assert len(th) == 1, th
time.sleep(float(os.environ.get("FAKE_UMP_SLEEP", "0")))
if hit("FAKE_UMP_DRIFT", mz):
    open(jar, "ab").write(b"x")
base = mz[:-len(".mzML")]
for qn, n in ((1, 5), (2, 4), (3, 3)):
    if qn == 3 and hit("FAKE_UMP_NOQ3", mz):
        continue
    with open("%s_Q%d.mgf" % (base, qn), "w") as f:
        for k in range(n):
            f.write("BEGIN IONS\nPEPMASS=%.4f 1000\n" % (400 + 10 * qn + k))
            if not (qn == 2 and k == 0):
                f.write("CHARGE=%s\n" % ("2+ and 3+" if hit("FAKE_UMP_BADZ", mz) else "%d+" % (2 + k % 2)))
            f.write("RTINSECONDS=%.2f\nTITLE=run.%d.%d.2\n300.5 10\n200.25 20\n250.0 0\n" % (-1.0 if (qn, k) == (1, 0) else 60.0 * k, qn, k))
            if hit("FAKE_UMP_BADMGF", mz) and qn == 2:
                f.write("abc def\n")
            f.write("END IONS\n\n")
print("DIA-Umpire SE: Thread = %s, done" % th[0])
'''
JAVA_WRAP = '''#!/usr/bin/env python3
import os, sys
if any(a.endswith("DIA_Umpire_SE-2.2.8.jar") for a in sys.argv):
    os.execv(sys.executable, [sys.executable, %r] + sys.argv[1:])
os.execv(%r, [%r] + sys.argv[1:])
'''


def _figures_module():
    """output/paper-jpr/figures/make_figures.py, imported with stub matplotlib modules when matplotlib is absent
    (load() and the estimator functions draw nothing)."""
    import importlib.util
    p = HERE.parent.parent.parent / "output" / "paper-jpr" / "figures" / "make_figures.py"
    if not p.is_file():
        return None
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        mpl = types.ModuleType("matplotlib")
        mpl.use = lambda *a, **k: None
        mpl.pyplot, mpl.ticker = types.ModuleType("matplotlib.pyplot"), types.ModuleType("matplotlib.ticker")
        sys.modules.update({"matplotlib": mpl, "matplotlib.pyplot": mpl.pyplot, "matplotlib.ticker": mpl.ticker})
    spec = importlib.util.spec_from_file_location("make_figures_selftest", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def selftest(args=None) -> int:
    C = c.Cases(echo=lambda r: print("%-4s %-6s %-58s %s" % r))
    saved = {k: getattr(c, k) for k in ("TIME", "POLL_S", "LOCK_RETRY_S", "MON_S", "load1", "mem_available_kb",
                                        "proc_snapshot", "remove_tree", "busy")}
    env_saved = dict(os.environ)
    w = Path(tempfile.mkdtemp(prefix="baseline2-selftest-"))
    try:
        c._world(w)                                    # corpus2 fakes: arms, java/diaTracer/MSFragger, Sage, raws A..H
        xt = c._dwv_world(w)                           # entrapment.py (repo copy), sage_entrap, msfragger_entrap params
        xt.pop("digest", None)
        spx, raws = w / "ceph" / "spx", w / "ceph" / "raw"
        # the corpus2 fakes read the FIRST count="..." of a file; a schema-valid mzML has cvList count first
        for f in (w / "bin" / "java", spx / "tools" / "sage" / "sage", spx / "tools" / "patch_diatracer_precursor.py"):
            f.write_text(f.read_text().replace("""re.search(r'count="(\\d+)"'""", """re.search(r'<spectrumList count="(\\d+)"'"""))
        os.replace(w / "bin" / "java", w / "bin" / "java_c2")
        c._exe(w / "opt" / "umpire" / "fake_umpire.py", FAKE_UMPIRE)
        c._exe(w / "bin" / "java", JAVA_WRAP % (str(w / "opt" / "umpire" / "fake_umpire.py"), str(w / "bin" / "java_c2"), str(w / "bin" / "java_c2")))
        c._exe(w / "bin" / "btime", b.FAKE_BTIME)
        c._exe(w / "opt" / "diann" / "diann-linux", b.FAKE_DIANN)
        (w / "opt" / "diann" / "libtimsdata.so").write_bytes(b"so")
        jar, prm = w / "opt" / "umpire" / "DIA_Umpire_SE-2.2.8.jar", w / "opt" / "umpire" / "diaumpire_se.params"
        jar.write_bytes(b"umpire jar")
        prm.write_text("# DIA-Umpire SE\nThread = 6\nRPmax = 25\n")

        def snap():
            t, f = time.monotonic(), float(os.environ.get("FAKE_FOREIGN_CORES", "0"))
            return {"t": t, "busy": int((4 + f) * c.CLK_TCK * t), "ours": int(4 * c.CLK_TCK * t),
                    "memavail_kb": 900, "memtotal_kb": 1000}
        for k, v in dict(TIME=str(w / "bin" / "btime"), POLL_S=0.01, LOCK_RETRY_S=0.3, MON_S=0.02, load1=lambda: 0.5,
                         mem_available_kb=lambda *a: 1000, proc_snapshot=snap, busy=lambda pats: []).items():
            setattr(c, k, v)
        os.environ.update(PATH=str(w / "bin") + os.pathsep + os.environ["PATH"], FAKE_ENVDUMP=str(w / "envdump.txt"),
                          FAKE_MSF_TIMES=str(w / "msf_times.log"), FAKE_NEIGHBOUR=str(w / "neighbour.mzML"),
                          OMP_NUM_THREADS="3", MALLOC_ARENA_MAX="2", LD_LIBRARY_PATH="/nonexistent")

        # ---- known answers: corpus2's rules, reused (the counting code itself is corpus2's, not copied)
        ranked = [(1000 - i, False) for i in range(199)] + [(50, False), (50, False), (50, True), (50, True), (50, True)] \
            + [(40 - i * 0.1, False) for i in range(100)]
        C.check("KNOWN", "tdc_cut: 199 T, a tie group 2T+3D (1.49%), 100 T -> cut 304; never inside the tie",
                c.tdc_cut(ranked) == 304 and c.tdc_cut(ranked[:204]) == 199, (c.tdc_cut(ranked), c.tdc_cut(ranked[:204])))
        st = w / "known_sage.tsv"
        st.write_text("peptide\trank\tpeptide_q\tlabel\tproteins\n" + "".join(
            "P%d\t1\t0.001\t1\tsp|X\n" % i for i in range(5)) + "P0\t1\t0.002\t1\tsp|X\nD1\t1\t0.001\t-1\trev_sp|X\n"
            "P9\t2\t0.001\t1\tsp|X\nP8\t1\t0.5\t1\tsp|X\n")
        sp = c.sage_peptides(st)
        C.check("KNOWN", "Sage target-only: 5 distinct targets (decoy, rank 2, q 0.5 out), 1 decoy as diagnostic",
                sp["peptides"] == 5 and sp["diag_decoy_peptides_in_set"] == 1 and sp["count_rule"] == c.COUNT_RULE, sp)
        mt = w / "known_msf.tsv"
        mt.write_text("peptide\tproteins\tmodification_info\thyperscore\tcharge\n" + "".join(
            "T%d\tsp|P%d\t\t%d\t2\n" % (i, i, 1000 - i) for i in range(199)) + "U1\tsp|U\t\t50\t2\nU2\tsp|U\t\t50\t2\n"
            + "".join("R%d\trev_sp|R%d\t\t50\t2\n" % (i, i) for i in range(3)))
        C.check("KNOWN", "MSFragger: the tie group at 50 is not split -> 199 peptides (a split would give 201)",
                c.msf_peptides(mt)["peptides"] == 199, c.msf_peptides(mt))
        eb = c.entrap_bounds([True] * 3 + [False] * 30, 0.5)
        mf = _figures_module()
        C.check("KNOWN", "Wen bounds: lower 3/33, combined upper 3(1+1/r)/33 (r=0.5), CIs around them",
                eb["lower_pct"] == round(100 * 3 / 33, 4) and eb["upper_pct"] == round(100 * 3 * 3 / 33, 4)
                and eb["lower_ci_pct"][0] <= eb["lower_pct"] <= eb["lower_ci_pct"][1]
                and eb["upper_ci_pct"][0] <= eb["upper_pct"] <= eb["upper_ci_pct"][1], eb)
        en = {"ratio": 0.5, "ratios": {"all": 0.5}, "all": eb}
        C.check("KNOWN", "make_figures.py draws the same lower/upper bound as the harness records",
                mf is not None and round(mf.lower_fdp(en, "all"), 4) == eb["lower_pct"]
                and round(mf.combined_fdp(en, "all"), 4) == eb["upper_pct"], "make_figures.py %s" % ("found" if mf else "NOT found"))
        C.check("KNOWN", "measurement code: search/score are corpus2's (PAIR_MEASURE_CORPUS2); run code pinned",
                {k: measure()[k][:12] for k in ("search", "score")} == {k: c.PAIR_MEASURE_CORPUS2[k] for k in ("search", "score")}
                and measure()["run"][:12] == RUN_MEASURE_PIN, {k: v[:12] for k, v in measure().items()})

        # ---- the MGF -> mzML converter
        md = w / "mgf"
        md.mkdir()
        (md / "run_Q1.mgf").write_text("BEGIN IONS\nPEPMASS=500.25 77\nCHARGE=2+\nRTINSECONDS=-3\nTITLE=a&b\n300 5\n100 0\n200 7\nEND IONS\n"
                                       "\nBEGIN IONS\nPEPMASS=600.5\nRTINSECONDS=12.5\n150 1\nEND IONS\n")
        (md / "run_Q2.mgf").write_text("BEGIN IONS\nPEPMASS=700\nCHARGE=3\nRTINSECONDS=20\n410.5 3 1+\n400 2\nEND IONS\n")
        cv = mgf_to_mzml([md / "run_Q1.mgf", md / "run_Q2.mgf"], md / "o.mzML")
        sc = c.mzml_scan(md / "o.mzML", decode=True)
        txt = (md / "o.mzML").read_text()
        C.check("G-B09", "converter: 3 spectra, scans 1..3, peaks sorted, intensity 0 dropped, RT -3 -> 0, charges 2/3/none",
                cv["spectra"] == 3 and cv["per_file"] == {"run_Q1.mgf": 2, "run_Q2.mgf": 1} and cv["dropped_nonpositive"] == 1
                and sc["spectra"] == 3 and sc["unsorted"] == 0 and sc["undecoded"] == 0 and sc["missing_selected_ion"] == 0
                and sc["peaks_total"] == 5 == cv["peaks"] and sc["charges"] == {"2": 1, "3": 1, "none": 1}
                and all('id="scan=%d"' % i in txt for i in (1, 2, 3)) and 'value="0.0" unitCvRef="UO"' in txt
                and 'value="Q1:a&amp;b"' in txt and c.verify_mzml(md / "o.mzML", 0)["count"] == 3, (cv, sc.get("charges")))
        C.check("G-B09", "converter output: every cvParam has a value (fix_mzml_cvparams.py has nothing to add)",
                not [x for x in re.findall(r"<cvParam\b[^>]*?/?>", txt) if "value=" not in x])
        (md / "bad.mgf").write_text("BEGIN IONS\nPEPMASS=500\nRTINSECONDS=1\n1 2\nnot a peak\nEND IONS\n")
        C.abort("G-B09", "converter: a line that is no peak", lambda: mgf_to_mzml([md / "bad.mgf"], md / "x.mzML"), "not a peak")
        (md / "glob.mgf").write_text("CHARGE=2+\nBEGIN IONS\nPEPMASS=500\nRTINSECONDS=1\n1 2\nEND IONS\n")
        C.abort("G-B09", "converter: a global MGF parameter is refused", lambda: mgf_to_mzml([md / "glob.mgf"], md / "x.mzML"), "outside")
        (md / "open.mgf").write_text("BEGIN IONS\nPEPMASS=500\nRTINSECONDS=1\n1 2\n")
        C.abort("G-B09", "converter: a block without END IONS", lambda: mgf_to_mzml([md / "open.mgf"], md / "x.mzML"), "not closed")
        (md / "nopm.mgf").write_text("BEGIN IONS\nRTINSECONDS=1\n1 2\nEND IONS\n")
        C.abort("G-B09", "converter: no PEPMASS", lambda: mgf_to_mzml([md / "nopm.mgf"], md / "x.mzML"), "PEPMASS")
        (md / "empty.mgf").write_text("\n")
        C.abort("G-B09", "converter: 0 spectra is refused, never a zero", lambda: mgf_to_mzml([md / "empty.mgf"], md / "x.mzML"), "0 spectra")

        # ---- plan: A (.d: spx, dt, DIA-NN) and O (.mzML: DIA-UMPIRE), entrapment on, both engines pinned
        omz = raws / "orbi_O.mzML"
        omz.write_text('<mzML><run><spectrumList count="5"></spectrumList></run></mzML>\n')
        reg = {"samples": {sid: {"raw": str(raws / ("run_%s.d" % sid)), "scheme": "HeLa test", "acq_min": 31.0,
                                 "database": "human", "label": sid, "pin": c.fingerprint(raws / ("run_%s.d" % sid))}
                           for sid in "ABCDEFGH"}}
        reg["samples"]["O"] = {"raw": str(omz), "scheme": "HeLa test", "label": "O", "pin": {"bytes": omz.stat().st_size, "sha256": c.sha256(omz)}}
        ump = {"kind": "diaumpire", "jar": str(jar), "params": str(prm), "search_at": 2, "java_args": ["-Xmx2g"],
               "sha256": {"jar": c.sha256(jar), "params": c.sha256(prm)}}
        cells = {"spx": None, "diatracer": {"kind": "diatracer", "dir": str(spx / "diatracer"), "jar": "diaTracer-2.2.1.jar", "search_at": 2},
                 "diann": {"kind": "diann", "bin": str(w / "opt" / "diann" / "diann-linux"), "search_at": 2}, "ump": ump}
        cells["spx_rev"] = cells.pop("spx") or {"kind": "diaspextract", "env": str(spx / "arm" / "env.sh"), "search_at": 2}
        tools = {"sage": str(spx / "tools" / "sage" / "sage"), "sage_config": str(spx / "tools" / "sage_deiso.json"),
                 "msfragger_jar": str(spx / "tools" / "MSFragger-4.4.1.jar"), "msfragger_params": str(spx / "tools" / "msfragger.params"),
                 "patch": str(spx / "tools" / "patch_diatracer_precursor.py"), "fix": str(spx / "tools" / "fix_mzml_cvparams.py"), **xt}
        plan = {"cluster": {"host": "binac2j", "partition": "compute", "walltime": "12:00:00", "python": sys.executable,
                            "job_unit": "sample", "cpus": 128},
                "results": str(w / "pfs" / "results" / "b2"), "raw_map": {str(raws) + "/": str(raws) + "/"},
                "threads": [1, 2], "repeats": 1, "n_samples": 2, "entrapment": True,
                "search_db_sha256": {"sage_fasta": c.sha256(w / "bench" / "human.fasta"), "msfragger_db": c.sha256(w / "bench" / "human_decoy.fasta"),
                                     "entrap_fasta": c.sha256(w / "bench" / "human_entrap.fasta"),
                                     "entrap_msf_db": c.sha256(w / "bench" / "human_entrap_decoy.fasta")},
                "engine_sha256": {"sage": c.sha256(spx / "tools" / "sage" / "sage"), "msfragger_jar": c.sha256(spx / "tools" / "MSFragger-4.4.1.jar")},
                "tools": tools, "cells": cells, "samples": ["A", "O"]}

        def mut(f):
            p = json.loads(json.dumps(plan))
            f(p)
            return lambda: b.validate_plan("b2", p, reg)
        C.ok("G-B01", "valid paper plan (entrapment, engine pins, DIA-UMPIRE cell)", lambda: b.validate_plan("b2", plan, reg))
        C.ok("G-B01", "a Sage-only plan without entrapment: one engine pin, no entrapment tools",
             mut(lambda p: (p.update(engines=["sage"], entrapment=False, engine_sha256={"sage": p["engine_sha256"]["sage"]}),
                            [p["tools"].pop(k) for k in ("sage_entrap", "entrapment", c.ENTRAP_MSF_KEY)],
                            [p["search_db_sha256"].pop(k) for k in ("entrap_fasta", "entrap_msf_db")])))
        for nm, f, m in (
                ("plan key typo", lambda p: p.update(repeat=1), "unknown keys"),
                ("thread axis not ascending", lambda p: p.update(threads=[2, 1]), "ascending"),
                ("search_at off the axis", lambda p: p["cells"]["ump"].update(search_at=3), "search_at"),
                ("engine_sha256 missing", lambda p: p.pop("engine_sha256"), "missing keys"),
                ("engine_sha256 without the MSFragger pin", lambda p: p["engine_sha256"].pop("msfragger_jar"), "engine_sha256"),
                ("engine_sha256 not hex", lambda p: p["engine_sha256"].update(sage="x"), "engine_sha256"),
                ("entrapment not a boolean", lambda p: p.update(entrapment="yes"), "true or false"),
                ("entrapment without msfragger_entrap_params", lambda p: p["tools"].pop(c.ENTRAP_MSF_KEY), "tools needs"),
                ("entrapment without entrap_msf_db pin", lambda p: p["search_db_sha256"].pop("entrap_msf_db"), "search_db_sha256"),
                ("DIA-UMPIRE sha256 pin missing", lambda p: p["cells"]["ump"].pop("sha256"), "needs"),
                ("DIA-UMPIRE sha256 without params", lambda p: p["cells"]["ump"]["sha256"].pop("params"), "sha256 needs"),
                ("DIA-UMPIRE relative params", lambda p: p["cells"]["ump"].update(params="diaumpire_se.params"), "absolute"),
                ("DIA-UMPIRE java_args set -jar", lambda p: p["cells"]["ump"].update(java_args=["-jar", "x.jar"]), "java_args"),
                ("DIA-UMPIRE cell key typo", lambda p: p["cells"]["ump"].update(args=["x"]), "allows"),
                ("reserved cell name spx", lambda p: p["cells"].update(spx=p["cells"].pop("spx_rev")), "cell name"),
                ("own sage_config with entrapment on", lambda p: p["cells"]["spx_rev"].update(sage_config="/x/sage.json"), "entrapment: false"),
                ("mzML sample no cell reads", lambda p: p["cells"].pop("ump"), "no cell")):
            C.abort("G-B01", nm, mut(f), m)
        C.ok("G-B01", "own sage_config allowed with entrapment: false for that cell", mut(lambda p: p["cells"]["spx_rev"].update(
            sage_config=str(spx / "tools" / "sage_deiso.json"), entrapment=False)))
        sce = {x["p"]: x for x in b.scaling({8: [800.0], 16: [420.0], 32: [250.0]}, 8, 16)}
        C.check("G-B06", "S/E known answer (baseline.py's scaling): S(16)=800/420, E(32)=0.8, E_phys(32)=1.6",
                sce[16]["speedup"] == round(800 / 420, 4) and sce[32]["efficiency"] == 0.8 and sce[32]["efficiency_physical"] == 1.6, sce)
        q0 = dict(b.resolve("b2", plan, reg), root="/tmp/x", jnatmp="/tmp/x")
        lines = []
        C.ok("G-B01", "dry-run prints every command", lambda: b.dry_run(q0, lines.append))
        C.check("G-B01", "dry-run: 6 + 2 runs, DIA-UMPIRE with Thread = p, 3 cells x 4 searches incl. entrap/entrap_msf",
                sum(bool(re.match(r"\[\d+\] ", x)) for x in lines) == 8 and sum("Thread = 2" in x for x in lines) == 1
                and sum(x.startswith("[search]") for x in lines) == 12 and sum("entrap_msf:" in x for x in lines) == 3
                and any("sage_entrap.json" in x for x in lines), [x for x in lines if "ump" in x][:2])
        sb = b.sbatch_script("bl-b2-A", plan["cluster"], "/pfs/r", harness_dir("/pfs/r"), "/pfs/r/jobs/bl-b2-A.json")
        C.check("G-B01", "sbatch runs baseline2.py from a content-named b2- harness dir; four files shipped",
                "/harness/b2-" in sb and "/baseline2.py job --spec /pfs/r/jobs/bl-b2-A.json" in sb and "#SBATCH --exclusive" in sb
                and [p.name for p in files()] == ["baseline.py", "baseline2.py", "corpus.py", "corpus2.py"]
                and all(p.is_file() for p in files()), sb.splitlines()[-1])

        # ---- the full plan as Slurm jobs: records on the results side
        (w / "tmpjob").mkdir()
        os.environ["TMPDIR"] = str(w / "tmpjob")
        jl = b.jobs(q0)
        rcs = [b.job_main({"mode": "baseline", "results": plan["results"], "path": [], "q": dict(jq, load_max=1e9)}) for _, jq in jl]
        recs = b.node_records({"root": plan["results"]})
        runs = {(r["cell"], r["id"], r["threads"]): r for r in recs if r["kind"] == "baseline_run"}
        srch = {(r["id"], r["tool"], r["engine"]): r for r in recs if r["kind"] == "search"}
        C.check("G-B01", "two jobs exit 0: 8 ok runs, 12 ok searches (Sage, MSFragger, entrap, entrap_msf x 3 cells)",
                rcs == [0, 0] and [x[0] for x in jl] == ["bl-b2-A", "bl-b2-O"] and sum(r["status"] == "ok" for r in runs.values()) == 8
                and len(srch) == 12 and all(r["status"] == "ok" for r in srch.values()),
                [(k, r.get("guard"), r.get("message")) for k, r in list(runs.items()) + list(srch.items()) if r["status"] != "ok"][:3])
        res = Path(plan["results"])
        C.check("G-V14", "no mzML, MGF, stage or tools copied out; no mzML left in the job roots",
                not list(res.rglob("*.mzML")) and not list(res.rglob("*.mgf")) and not list(res.rglob("stage"))
                and not list(res.rglob("tools")) and not list((w / "tmpjob").rglob("runs/**/*.mzML")))
        u2 = runs.get(("ump", "O", 2), {})
        C.check("G-B09", "DIA-UMPIRE unit: Thread = p in its params, 12 spectra = 5+4+3 MGF blocks, 1/12 without charge",
                u2.get("umpire_threads") == 2 and runs[("ump", "O", 1)].get("umpire_threads") == 1
                and u2.get("output", {}).get("count") == 12 and u2.get("mgf", {}).get("per_file") == {
                    "run_Q1.mgf": 5, "run_Q2.mgf": 4, "run_Q3.mgf": 3} and u2.get("charges", {}).get("none") == 1
                and u2["tool"]["params_sha256"] == c.sha256(prm) and u2["tool"]["label"] == "DIA-Umpire SE (DIA_Umpire_SE-2.2.8.jar)"
                and u2["cmd"][4:6] == [os.path.realpath(w / "bin" / "java"), "-Djava.io.tmpdir=" + str(w / "tmpjob" / "jnatmp")],
                {k: u2.get(k) for k in ("umpire_threads", "mgf", "charges", "message")})
        C.check("G-B09", "DIA-UMPIRE run dir keeps logs, params and nothing raw-derived",
                sorted(p.name for p in (res / "runs" / "runs" / "O").glob("ump-p1-*/*")) == ["diaumpire_se.params", "time.log", "umpire.log"],
                sorted(p.name for p in (res / "runs" / "runs" / "O").glob("ump-p1-*/*")))
        C.check("G-V10", "target-only counts: Sage 30 (the passing decoy a diagnostic), MSFragger 150, per-charge split",
                all(srch[(s, t, "sage")]["peptides"] == 30 and srch[(s, t, "sage")]["diag_decoy_peptides_in_set"] == 1
                    and srch[(s, t, "msfragger")]["peptides"] == 150 and srch[(s, t, "sage")]["by_charge"]["z2p"]["peptides"] == 24
                    for s, t in (("A", "spx_rev"), ("A", "dt"), ("O", "ump"))), srch[("O", "ump", "sage")].get("message"))
        ea, em = srch[("O", "ump", "entrap")]["entrapment"], srch[("A", "dt", "entrap_msf")]["entrapment"]
        C.check("G-V19", "entrapment (corpus2 fakes): Sage 3 of 33 lower bound, r per stratum; MSFragger 150 accepted, "
                         "3 entrapment; z1 + z2p = all", ea["all"]["lower_pct"] == round(100 * 3 / 33, 4)
                and ea["ratios"] == {k: ea["ratio"] for k in ("all", "z1", "z2p")} and em["all"]["accepted"] == 150
                and em["all"]["entrap"] == 3 and all(x["z1"]["accepted"] + x["z2p"]["accepted"] == x["all"]["accepted"] for x in (ea, em)), ea["all"])
        C.check("G-V12", "engine versions and pins: every search record has tools_sha256 sage/msfragger_jar = the plan pins",
                all(r["tools_sha256"]["sage"] == plan["engine_sha256"]["sage"] and r["tools_sha256"]["msfragger_jar"]
                    == plan["engine_sha256"]["msfragger_jar"] and "engine_version" in r for r in srch.values())
                and srch[("A", "dt", "msfragger")]["engine_version"] == "MSFragger 4.4.1"
                and all(r.get("engine_versions", {}).get("msfragger") == "MSFragger 4.4.1" for r in runs.values()))
        C.check("G-V10", "measurement hashes: run records carry run, searches search/score/cells = corpus2's",
                all(r["measure_sha256"] == {"run": measure()["run"]} for r in runs.values())
                and all(r["measure_sha256"]["search"] == measure()["search"] and r["measure_sha256"]["cells"] == measure()["cells"]
                        for r in srch.values()))
        obj, mdt, complete = b.render("b2", plan, reg, recs)
        rows = {(x["sample"], x["cell"]): x for x in obj["rows"]}
        C.check("G-B06", "table complete: E(2) = 0.9 for spx/dt/DIA-NN, target-only ids, entrapment rows and rules",
                complete and all(rows[("A", n)]["scaling"][1]["efficiency"] == 0.9 for n in ("spx_rev", "diatracer", "diann"))
                and rows[("O", "ump")]["ids"]["sage_peptides"] == 30 and rows[("O", "ump")]["ids"]["spectra"] == 12
                and len(obj["entrapment"]) == 3 * 3 * 2 and "## Entrapment" in mdt and c.COUNT_RULE in mdt, obj["missing"][:3])
        before = {r["run_id"] for r in runs.values()}
        rc2 = b.job_main({"mode": "baseline", "results": plan["results"], "path": [], "q": dict(jl[1][1], nonce="again", load_max=1e9)})
        C.check("G-B01", "resume: a second O job re-runs nothing (runs and searches current)", rc2 == 0 and before ==
                {r["run_id"] for r in b.node_records({"root": plan["results"]}) if r["kind"] == "baseline_run"})

        # ---- table refusals
        def tamper(f):
            rr = json.loads(json.dumps(recs))
            f(rr)
            return lambda: b.render("b2", plan, reg, rr)
        first = lambda rr, k: next(r for r in rr if r.get("kind") == k[0] and r.get(k[1]) == k[2])
        C.abort("G-B06", "one cell, two tool builds", tamper(lambda rr: first(rr, ("baseline_run", "cell", "ump"))["tool"].update(sha256="ff" * 32)), "builds")
        C.abort("G-B10", "a search counted by corpus.py's target+decoy rule is refused",
                tamper(lambda rr: first(rr, ("search", "engine", "sage")).pop("count_rule")), "counted by rule")
        C.abort("G-B10", "an entrapment record of the old estimator is refused",
                tamper(lambda rr: first(rr, ("search", "engine", "entrap"))["entrapment"].update(rule="corpus-v3")), "estimator")
        rr = [r for r in recs if not (r.get("kind") == "search" and r["engine"] == "entrap_msf" and r["tool"] == "ump")]
        C.check("G-B06", "a missing entrapment search makes the table incomplete", not b.render("b2", plan, reg, rr)[2]
                and any("ump search entrap_msf" in m for m in b.render("b2", plan, reg, rr)[0]["missing"]))

        # ---- figure records + manifest, read back by make_figures.py's own loader
        fd = w / "fig"
        ns = argparse.Namespace(plan="b2", registry=None, source=plan["results"], out=str(w / "manifest.json"), records=str(fd), spx=None)
        reg_file = w / "samples.yaml"
        reg_file.write_text(json.dumps(dict(reg, b2=plan)))        # JSON is YAML: the real loader path
        ns.registry = str(reg_file)
        try:
            import yaml  # noqa: F401
            have_yaml = True
        except ImportError:
            have_yaml = False
        if have_yaml:
            C.ok("G-V13", "manifest subcommand over the plan's records", lambda: cmd_manifest(ns))
        else:                                                        # selftest needs no YAML: the same steps by hand
            fig0 = figure_records("b2", plan, reg, recs)
            Path(ns.out).write_text(json.dumps(c.build_manifest(list(fig0.values()), ["b2"])))
            for fn, r in fig0.items():
                c.write_json(fd / "records" / fn, r)
        man = json.loads(Path(ns.out).read_text())
        fnames = sorted(p.name for p in (fd / "records").glob("*.json"))
        C.check("G-V13", "figure records: A.pair + spx/dt x {sage, msfragger, entrap, entrap_msf}; manifest label/hashes",
                fnames == sorted(["A.pair.json"] + ["A.%s.%s.json" % (t, e) for t in ("spx", "dt")
                                                     for e in ("sage", "msfragger", "entrap", "entrap_msf")])
                and man["label"] == runs[("spx_rev", "A", 2)]["tool"]["label"] and man["measure_sha256"]["pair"] == measure()["run"]
                and man["measure_sha256"]["search"] == measure()["search"] and man["count_rule"] == c.COUNT_RULE, fnames)
        loaded = None
        if mf is not None:
            try:
                loaded = mf.load([str(fd)], None, False, ["sage", "msfragger"], None, ["A"], (), man)
            except SystemExit as x:
                loaded = "make_figures.py refused: %s" % x
        ok_l = isinstance(loaded, tuple)
        C.check("G-V13", "make_figures.py load(): manifest checked, pair + 4 searches + 4 entrapment cells, same numbers",
                ok_l and loaded[0]["A"]["arms"]["spx"]["wall_s"] == runs[("spx_rev", "A", 2)]["wall_s"]
                and loaded[1][("A", "spx", "sage")]["peptides"] == 30 and loaded[1][("A", "dt", "msfragger")]["peptides"] == 150
                and set(loaded[2]) == {("A", t, e) for t in ("spx", "dt") for e in ("sage", "msfragger")}
                and round(mf.combined_fdp(loaded[2][("A", "spx", "sage")], "all"), 4)
                == srch[("A", "spx_rev", "entrap")]["entrapment"]["all"]["upper_pct"], loaded if not ok_l else "ok")
        bad = json.loads(json.dumps(man))
        bad["measure_sha256"]["score"] = "0" * 64
        try:
            mf.load([str(fd)], None, False, ["sage", "msfragger"], None, ["A"], (), bad)
            refused = False
        except SystemExit:
            refused = mf is not None
        C.check("G-V13", "make_figures.py refuses the figure records under another counting code (manifest score)", refused)
        bad_rec = json.loads(json.dumps(recs))
        next(r for r in bad_rec if r.get("kind") == "search" and r["tool"] == "dt" and r["engine"] == "sage")["tools_sha256"]["sage_config"] = "0" * 64
        C.abort("G-V13", "manifest refused when spx and dt searches used different configs",
                lambda: c.build_manifest(list(figure_records("b2", plan, reg, bad_rec).values()), ["b2"]), "records disagree")
        C.abort("G-B10", "figure records without a diatracer cell", lambda: figure_records(
            "b2", dict(plan, cells={k: v for k, v in plan["cells"].items() if k != "diatracer"}), reg,
            [r for r in recs if r.get("cell") != "diatracer"]), "one diatracer")
        C.abort("G-B10", "figure records: --spx names no diaspextract cell", lambda: figure_records("b2", plan, reg, recs, "ump"), "diaspextract")

        # ---- unit-level failures (the queue goes on) and queue-level aborts
        def q_for(rootname, **kw):
            q = b.resolve("b2", plan, reg)
            q.update(root=str(w / "scratch" / rootname), lock=str(w / "scratch" / ".lock"), jnatmp=str(w / "scratch" / "jnatmp"), load_max=1e9)
            q.update(kw)
            return q

        def one(rootname, cell, sid="O", env=None, cellkw=None, **kw):
            q = q_for(rootname, cells={cell: dict(q0["cells"][cell], **(cellkw or {}))}, **kw)
            q["samples"] = [s for s in q0["samples"] if s["id"] == sid]
            os.environ.update(env or {})
            try:
                rc = b.node_run(q)
            finally:
                for k in env or {}:
                    os.environ.pop(k, None)
            return rc, {(r.get("cell") or r.get("tool") or r["kind"], r.get("threads", r.get("engine"))): r
                        for r in b.node_records({"root": q["root"]})}

        def failed_with(guard, nm, res, key, match):
            rc, rs = res
            r = rs.get(key, {})
            C.check(guard, nm, rc == 1 and r.get("status") == "failed" and r.get("guard") == guard
                    and match.lower() in r.get("message", "").lower(), "rc %s %s %s" % (rc, r.get("guard"), r.get("message")))
        failed_with("G-B09", "DIA-UMPIRE wrote no Q3 MGF", one("noq3", "ump", env={"FAKE_UMP_NOQ3": "ump-p1"}), ("ump", 1), "Q3.mgf missing")
        failed_with("G-B09", "DIA-UMPIRE MGF with a broken peak line", one("badmgf", "ump", env={"FAKE_UMP_BADMGF": "ump-p2"}), ("ump", 2), "not a peak")
        failed_with("G-B09", "DIA-UMPIRE MGF with two charges", one("badz", "ump", env={"FAKE_UMP_BADZ": "ump-p1"}), ("ump", 1), "one positive")
        failed_with("G-B04", "DIA-NN: 0 precursors at 1% q", one("zero", "diann", sid="A", env={"FAKE_DIANN_ZERO": "/diann-p1"}), ("diann", 1), "0 precursors")
        failed_with("G-V08", "diaspextract count line != spectrumList count", one("spxcount", "spx_rev", sid="A", env={"FAKE_SPX_MISCOUNT": "/A.d"}),
                    ("spx_rev", 1), "log count")
        failed_with("G-B05", "DIA-UMPIRE past its wall cap: killed", one("cap", "ump", env={"FAKE_UMP_SLEEP": "3"}, cellkw={"wall_cap_h": 0.0001}),
                    ("ump", 1), "stopped")
        rc, rs = one("sagezero", "ump", env={"FAKE_SAGE_ZERO": "ump-p2"})
        C.check("G-V10", "Sage 0 peptides on the DIA-UMPIRE output: that search failed, MSFragger ok", rc == 1
                and rs[("ump", "sage")].get("guard") == "G-V10" and rs[("ump", "msfragger")]["status"] == "ok", rs.get(("ump", "sage"), {}).get("message"))
        omz.write_text(omz.read_text() + " ")
        rc, rs = one("pin", "ump")
        omz.write_text(omz.read_text()[:-1])
        C.check("G-V02", "mzML raw differs from its pin: stage failed, no run", rc == 1
                and rs[("baseline_stage", None)]["guard"] == "G-V02" and not any(k[0] == "ump" for k in rs), sorted(map(str, rs)))
        os.environ["FAKE_FOREIGN_CORES"] = "100"
        rc, rs = one("contended", "ump", load_max=12)
        os.environ.pop("FAKE_FOREIGN_CORES")
        C.check("G-V06", "foreign CPU during a DIA-UMPIRE run: flagged, not failed", rc == 0 and rs[("ump", 1)]["contended"])
        C.abort("G-V12", "Sage copy differs from the plan's engine pin", lambda: one("pinsage", "ump", engine_sha256=dict(
            plan["engine_sha256"], sage="00" * 32)), "engine sage")
        C.abort("G-B08", "DIA-UMPIRE jar differs from its pin", lambda: one("pinjar", "ump", cellkw={"sha256": dict(ump["sha256"], jar="00" * 32)}), "jar sha256")
        p0 = w / "opt" / "umpire" / "nothread.params"
        p0.write_text("RPmax = 25\n")
        C.abort("G-B08", "DIA-UMPIRE params without a Thread line", lambda: one("nothr", "ump", cellkw={
            "params": str(p0), "sha256": dict(ump["sha256"], params=c.sha256(p0))}), "exactly one")
        p2 = w / "opt" / "umpire" / "twothreads.params"
        p2.write_text("Thread = 4\nThread = 8\n")
        C.abort("G-B08", "DIA-UMPIRE params with two Thread lines", lambda: one("twothr", "ump", cellkw={
            "params": str(p2), "sha256": dict(ump["sha256"], params=c.sha256(p2))}), "exactly one")
        C.abort("G-B02", "DIA-UMPIRE jar missing", lambda: one("nojar", "ump", cellkw={"jar": str(w / "nonexistent.jar")}), "missing")
        C.abort("G-B02", "java 1.8 (BinAC2's system java) refused", lambda: b.check_java({"major": 8, "version": "1.8.0_504"}), "older than")
        dj = w / "opt" / "umpire2"
        shutil.copytree(w / "opt" / "umpire", dj)
        C.abort("G-B03", "the DIA-UMPIRE jar changes during a run", lambda: one("drift", "ump", env={"FAKE_UMP_DRIFT": "ump-p1"}, cellkw={
            "jar": str(dj / jar.name), "sha256": dict(ump["sha256"], jar=c.sha256(dj / jar.name))}), "changed during")
        C.abort("G-V03", "diaspextract arm env.sh exports OMP_NUM_THREADS", lambda: one("omp", "spx_rev", sid="A", cellkw={
            "env": str(spx / "arm_omp" / "env.sh")}), "exports")
        C.abort("G-B01", "thread count above the job's CPUs", lambda: one("cores", "ump", cellkw={"threads": [10 ** 6], "search_at": 10 ** 6}), "exceed")
        C.abort("G-B01", "corpus2.py differs from the resolved one", lambda: one("c2", "ump", corpus_sha256="00" * 32), "corpus2.py")
        C.abort("G-B01", "baseline.py/baseline2.py differ from the resolved ones", lambda: one("h2", "ump", harness_sha256="00" * 32), "baseline2.py")
        os.environ["TMPDIR"] = "/pfs/10/work/x"
        C.abort("G-B07", "TMPDIR on Lustre, not node-local", lambda: b.job_main({"mode": "baseline", "results": plan["results"], "path": [], "q": q0}), "node-local")
        os.environ["TMPDIR"] = str(w / "tmpjob")
        c.remove_tree = lambda p: None
        try:
            C.abort("G-V14", "staged copy not deleted", lambda: one("keep", "ump"), "not deleted")
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
    n_ok = len(C.results) - len(fails)
    print("SELFTEST %s: %d checks, %d failed, guards never fired: %s" % (
        "OK" if not fails and not never else "FAILED", len(C.results), len(fails), never or "none"))
    print("%d/%d" % (n_ok, len(C.results)))
    return 0 if not fails and not never else 1


# ------------------------------------------------------------------------------- main
def main() -> int:
    if len(sys.argv) > 1 and (sys.argv[1].startswith("node-") or sys.argv[1] == "job"):
        return b.node_main(sys.argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("selftest", "dry-run", "preflight", "submit", "status", "fetch", "table", "submit-corpus", "corpus-table", "manifest"):
        p = sub.add_parser(name)
        if name == "selftest":
            continue
        p.add_argument("--plan", default=b.DEFAULT_PLAN, help="manifest: comma-separated plans" if name == "manifest" else None)
        p.add_argument("--registry", default=str(b.REG))
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
        if name in ("table", "corpus-table", "manifest"):
            p.add_argument("--source", default="remote", help="remote (read on the login node) or a local dir holding records/")
            p.add_argument("--out", required=name == "manifest", help="table: OUT.json + OUT.md; corpus-table/manifest: OUT")
        if name == "manifest":
            p.add_argument("--records", help="also write the figure records (corpus2 layout) to DIR/records/")
            p.add_argument("--spx", help="the diaspextract cell that is arm spx (default: the plan's only one)")
    a = ap.parse_args()
    fn = {"selftest": selftest, "dry-run": b.cmd_dry_run, "preflight": b.cmd_preflight, "submit": b.cmd_submit,
          "status": b.cmd_status, "fetch": b.cmd_fetch, "table": b.cmd_table, "submit-corpus": b.cmd_submit_corpus,
          "corpus-table": b.cmd_corpus_table, "manifest": cmd_manifest}[a.cmd]
    try:
        return fn(a)
    except Abort as x:
        print("ABORT %s" % x, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
