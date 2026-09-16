#!/usr/bin/env python3
"""Mutation proof for the `engines` plan option: each new check broken alone in a scratch copy; that copy's selftest
must fail (KILLED). The unmutated control must pass (SURVIVED). Sequential: parallel selftests share busy patterns."""
import os, shutil, stat, subprocess, sys, tempfile
from pathlib import Path

NEW = Path(sys.argv[1])
BENCH = Path("/Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract/bench")
SRC = NEW.read_text()
M = [
    ("CONTROL (no mutation)", None, None),
    ("E1 engines value not validated",
     '    if "engines" in plan and (not isinstance(eng, list) or not eng or [e for e in ENGINES if e in eng] != eng):',
     "    if False:"),
    ("E2 validation accepts repeats and any order",
     "or [e for e in ENGINES if e in eng] != eng):", "or set(eng) - set(ENGINES)):"),
    ("E3 q_engines ignores the plan", 'return tuple(q.get("engines") or ENGINES) + (("entrap",)', 'return ENGINES + (("entrap",)'),
    ("E4 engines do not make a plan extended", 'return bool(cells(q) or q.get("entrapment") or "engines" in q)',
     'return bool(cells(q) or q.get("entrapment"))'),
    ("E5 MSFragger-first serial phase in a Sage-only plan",
     'if not msf_ok and "msfragger" in engines and pending(u[0], u[1], "msfragger"):',
     'if not msf_ok and pending(u[0], u[1], "msfragger"):'),
    ("E6 dry-run prints MSFragger for a Sage-only plan", '            if "msfragger" in q_engines(q):\n', "            if True:\n"),
    ("E7 dry-run omits the engines note", '"; engines %s only (plan `engines`)" % ", ".join(q["engines"])', '""'),
    ("E8 table accepts records of engines the plan does not run", "    if other:\n        die(\"G-V13\"",
     "    if False:\n        die(\"G-V13\""),
    ("E9 table indexes a missing engine", 'SG = lambda t_, g: S.get((t_, g), (None, "-"))', "SG = lambda t_, g: S[t_, g]"),
    ("E10 totals over a missing engine", 'tot(lambda x: f(x["search"][t_, g])) if g in engines else None',
     'tot(lambda x: f(x["search"][t_, g])) if True else None'),
    ("E11 table omits the engines line", '                       if "engines" in plan else "",', '                       if False else "",'),
    ("E12 measured cell code edited (cells hash moves)", '"""G-V18 (flags): a cell with `differs_from`',
     '"""G-V18 (flag): a cell with `differs_from`'),
    ("E14 table compares a group's cells {} with the plan's None",
     '        if (p.get("cells") or {}) != (plan.get("cells") or {}) or bool(p.get("entrapment"))',
     '        if p.get("cells") != plan.get("cells") or bool(p.get("entrapment"))'),
    ("E15 full engines list accepted (plain plan re-runs whole)", "    if eng == list(ENGINES):", "    if False:"),
]
ONLY = sys.argv[2].split(",") if len(sys.argv) > 2 else None
M = [m for m in M if ONLY is None or m[0].split()[0] in ONLY]


def rmtree(p):
    for d, ds, fs in os.walk(p):
        os.chmod(d, stat.S_IRWXU)
    shutil.rmtree(p, ignore_errors=True)


for name, a, b in M:
    if a is not None and SRC.count(a) != 1:
        print("%-60s BAD MUTATION (%d matches)" % (name, SRC.count(a)), flush=True)
        continue
    td = Path(tempfile.mkdtemp(prefix="mut-eng-"))
    (td / "harness").mkdir()
    (td / "harness" / "corpus.py").write_text(SRC if a is None else SRC.replace(a, b))
    os.symlink(BENCH, td / "bench")
    tmp = td / "tmp"
    tmp.mkdir()
    r = subprocess.run([sys.executable, str(td / "harness" / "corpus.py"), "selftest"], capture_output=True, text=True,
                       env=dict(os.environ, TMPDIR=str(tmp)))
    tail = [l for l in r.stdout.splitlines() if l.startswith("FAIL") or "cases pass" in l]
    rmtree(td)
    verdict = "SURVIVED" if r.returncode == 0 else "KILLED"
    print("%-60s %-8s %s" % (name, verdict, " | ".join(" ".join(x.split())[:120] for x in tail[:3])), flush=True)
print("MUTATE_DONE", flush=True)
