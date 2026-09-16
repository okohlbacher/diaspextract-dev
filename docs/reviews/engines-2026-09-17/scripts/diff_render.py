#!/usr/bin/env python3
"""Differential check: the 0d8532d harness (orig) and the engines harness (new) render identical tables and dry-runs for
plans WITHOUT `engines` (plain and extended), on records produced by the orig harness in a selftest-style fake world."""
import contextlib, importlib.util, io, json, os, re, shutil, stat, sys, tempfile, time
from pathlib import Path

HW = Path(__file__).resolve().parent


def load(p, n):
    spec = importlib.util.spec_from_file_location(n, str(p))
    m = importlib.util.module_from_spec(spec)
    sys.modules[n] = m
    spec.loader.exec_module(m)
    return m


O = load(HW / "orig" / "harness" / "corpus.py", "corpus_orig")
N = load(HW / "new" / "harness" / "corpus.py", "corpus_new")
td = tempfile.mkdtemp(prefix="diffrender-")
w = Path(td)
env0 = dict(os.environ)
try:
    O._world(w)

    def fake_snapshot():
        t = time.monotonic()
        return {"t": t, "busy": int(4 * O.CLK_TCK * t), "ours": int(4 * O.CLK_TCK * t), "memavail_kb": 900, "memtotal_kb": 1000}
    patch = dict(TIME=str(w / "bin" / "time"), POLL_S=0.01, LOCK_RETRY_S=0.3, MON_S=0.02, load1=lambda: 0.5,
                 mem_available_kb=lambda *a: 1000, proc_snapshot=fake_snapshot)
    O.__dict__.update(patch)
    N.__dict__.update(patch)
    os.environ.update(PATH=str(w / "bin") + os.pathsep + os.environ["PATH"], FAKE_ENVDUMP=str(w / "envdump.txt"),
                      FAKE_MSF_TIMES=str(w / "msf_times.log"), FAKE_MSF_SLEEP="0",
                      FAKE_NEIGHBOUR=str(w / "ceph" / "raw" / "run_A_diatracer.mzML"))
    q1 = O._queue(w, "AB")
    assert O.node_run(q1) == 0
    xt = O._dwv_world(w)
    xq = O._xqueue(w, "AB", "x1", xt)
    assert O.node_run(xq) == 0
    x1 = O._xqueue(w, "C", "x2", xt, cells_={"dwv_default": O.DWV_CELLS["dwv_default"]})
    x1["entrapment"] = False                    # the entrapment key present but off, one cell
    assert O.node_run(x1) == 0
    mask = lambda s: re.sub(r"Generated \S+", "Generated <t>", s)
    res = []

    def cmp(what, fo, fn):
        a, b = fo(), fn()
        a = mask(a[0]) if isinstance(a, tuple) else mask(a)
        b = mask(b[0]) if isinstance(b, tuple) else mask(b)
        res.append((what, a == b, len(a)))
        if a != b:
            (HW / ("diff_%s.orig" % what)).write_text(a)
            (HW / ("diff_%s.new" % what)).write_text(b)

    R1, RX, RC = [list(O._records(q).values()) for q in (q1, xq, x1)]
    cmp("plain_table", lambda: O.render_table("s", *O._reg(q1), R1), lambda: N.render_table("s", *N._reg(q1), R1))
    cmp("ext_table", lambda: O.render_cells_table("x", *O._xreg(xq), RX), lambda: N.render_cells_table("x", *N._xreg(xq), RX))
    cmp("ext1_table", lambda: O.render_cells_table("x", *O._xreg(x1), RC), lambda: N.render_cells_table("x", *N._xreg(x1), RC))
    part = [r for r in RX if not (r["id"] == "A" and r.get("engine") == "msfragger") and not (r["id"] == "B" and r["kind"] == "pair")]
    cmp("ext_table_partial", lambda: O.render_cells_table("x", *O._xreg(xq), part),
        lambda: N.render_cells_table("x", *N._xreg(xq), part))
    for nm, q in (("plain", q1), ("ext", xq), ("ext1", x1)):
        def dr(M, q=q):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                M.dry_run(q)
            return buf.getvalue()
        cmp("dryrun_%s" % nm, lambda: dr(O), lambda: dr(N))
    for what, ok, n in res:
        print("%-20s %s (%d chars)" % (what, "IDENTICAL" if ok else "DIFFERS", n))
    print("DIFF_DONE", "all identical" if all(ok for _, ok, _ in res) else "DIFFERENCES")
finally:
    os.environ.clear()
    os.environ.update(env0)
    for d, _, _ in os.walk(td):
        os.chmod(d, stat.S_IRWXU)
    shutil.rmtree(td, ignore_errors=True)
