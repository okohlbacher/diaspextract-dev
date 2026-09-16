#!/usr/bin/env python3
"""G-V16/G-V17/G-V18 on the node, against real OpenMS-written files (mkfix.py) and the published diaWeaver arm.
Calls corpus.py's own functions; faults enter through a wrapper arm in the work dir. Review aid, not a benchmark.
usage: gtest.py CORPUS_PY FIXTURE_DIR WORK_DIR"""
import importlib.util, json, os, shutil, signal, subprocess, sys, time
from pathlib import Path

H, FX, W = (Path(a).resolve() for a in sys.argv[1:4])
spec = importlib.util.spec_from_file_location("corpus", H)
C = importlib.util.module_from_spec(spec)
sys.modules["corpus"] = C
spec.loader.exec_module(C)
print("corpus.py", C.sha256(H)[:12])
SPX, ARM = "/ceph/ibmi/abi/oliver/spextract", "diaweaver-7ed1169"
RES = []


def case(name, fn, guard=None, frag=None):
    try:
        out = fn()
        ok = guard is None
        RES.append((ok, name, "passed" if ok else "NO ABORT (wanted %s: %s)" % (guard, frag)))
        return out
    except C.Abort as a:
        ok = guard is not None and a.guard == guard and (frag is None or frag in a.message)
        RES.append((ok, name, "[%s] %s" % (a.guard, a.message[:160])))
    except Exception as x:
        RES.append((False, name, "CRASH %s: %s" % (type(x).__name__, str(x)[:200])))


def check(name, cond, detail=""):
    RES.append((bool(cond), name, str(detail)[:300]))


W.mkdir(mode=0o700, parents=True)
(W / "tmp").mkdir()
root = W / "root"
root.mkdir(mode=0o700)
q = {"spx_root": SPX, "jnatmp": str(W / "tmp"), "root": str(root), "threads": 16, "load_wait_min": 0,
     "cells": {"dwv_default": {"kind": "dwv", "arm": ARM, "args": [], "wall_cap_h": 12}}}
cenv = C.cell_env(q, "dwv_default")
cid = C.cells_identity(q)["dwv_default"]
case("G-V03 real arm: provenance lists binary, FileFilter, lib/**", lambda: C.cell_provenance(q, "dwv_default", cenv, cid))
check("G-V03 real arm label", C.tool_label(cenv["DWV_BIN"], cenv).startswith("diaWeaver 3.6.0-pre-diaWeaver-2"),
      C.tool_label(cenv["DWV_BIN"], cenv))
digest = C.load_module(SPX + "/tools/semantic_digest.py", "sd").digest
real_ff = str(Path(cenv["DWV_BIN"]).parent / "FileFilter")
real_fc = str(Path(cenv["DWV_BIN"]).parent / "FileConverter")

fake = W / "fakearm" / "bin"
fake.mkdir(parents=True)
(fake / "FileFilter").write_text(r'''#!/bin/bash
# wrapper re-encode tool: argv = -in SRC -out DST <REENCODE options>
case "$VARIANT" in
  numpress) exec "$REAL_FC" -in "$2" -out "$4" -lossy_compression ;;
  copy) exec cp "$VFILE" "$4" ;;
  half) head -c $(( $(stat -c %s "$VFILE") / 2 )) "$VFILE" > "$4"; exit 0 ;;
  fail) exit 1 ;;
  none) exit 0 ;;
  *) exec "$REAL_FF" "$@" ;;
esac
''')
(fake / "diaWeaver").write_text(r'''#!/bin/bash
# wrapper cell tool: argv = -in STAGED -out DIR -threads N
out="$4/pseudo_spectra.mzML"
case "$DVAR" in
  ok) cp "$VFILE" "$out"; echo "Finished processing all windows. Wrote $VCOUNT pseudo spectra."; echo "Done. Output (numpress compressed): $out" ;;
  nofile) echo "Finished processing all windows. Wrote 5 pseudo spectra."; echo "Done. Output (numpress compressed): $out" ;;
  zero) cp "$VFILE" "$out"; echo "Finished processing all windows. Wrote 0 pseudo spectra."; echo "No pseudo spectra were generated." ;;
  exit3) echo "Finished processing all windows. Wrote 5 pseudo spectra."; exit 3 ;;
  slow) exec -a dwvslowmarker sleep 3600 ;;
  miscount) cp "$VFILE" "$out"; echo "Finished processing all windows. Wrote $((VCOUNT + 1)) pseudo spectra."; echo "Done. Output (numpress compressed): $out" ;;
  nodone) cp "$VFILE" "$out"; echo "Finished processing all windows. Wrote $VCOUNT pseudo spectra." ;;
  *) exit 99 ;;
esac
''')
for f in fake.iterdir():
    f.chmod(0o755)

# ---- mzml_scan on the real files
raw = C.mzml_scan(FX / "fx_dwv.mzML", decode=True)
n = raw["spectra"]
check("scan raw fixture: every m/z array numpress (undecoded == spectra), 3 numpress terms per spectrum",
      raw["numpress_terms"] == 3 * n and raw["undecoded"] == (0 if "peak_digest" in raw else n) and n > 100, {k: raw[k] for k in ("spectra", "undecoded", "numpress_terms")})
check("scan raw fixture: 1/K0 = 0 in 3 of 4, charges tallied, >= 30 peaks",
      raw["im_zero"] == n - (n + 3) // 4 and sum(raw["charges"].values()) == n and raw["peaks_median"] >= 30 and raw["im_missing"] == 0,
      {k: raw[k] for k in ("im_zero", "im_missing", "charges", "peaks_median")})
uns = C.mzml_scan(FX / "res_unsorted.mzML", decode=True)
check("scan plain unsorted file: 2 of 3 spectra unsorted, all decoded, lengths ok",
      uns["unsorted"] == n - (n + 2) // 3 and uns["undecoded"] == 0 and uns["length_mismatch"] == 0,
      {k: uns[k] for k in ("spectra", "unsorted", "undecoded", "length_mismatch")})
check("scan: prec digest equal for the numpress and the plain file (same precursors)", raw["prec_digest"] == uns["prec_digest"])
if "peak_digest" in raw:
    check("scan raw fixture (fixed harness): numpress m/z decoded, 160 of 240 unsorted, peaks digest present",
          raw["undecoded"] == 0 and raw["unsorted"] == n - (n + 2) // 3 and raw["peak_digest"] and raw["missing_mz"] == 0,
          {k: raw.get(k) for k in ("undecoded", "unsorted", "missing_mz", "peaks_min")})


def reenc(name, variant=None, vfile=None, src=FX / "fx_dwv.mzML"):
    adir = W / "re" / name
    adir.mkdir(parents=True)
    s = adir / "pseudo_spectra.mzML"
    t0 = time.time() - 1
    shutil.copyfile(src, s)
    rec = {"raw_output": C.verify_mzml(s, t0)}
    env = dict(cenv)
    if variant:
        env.update(DWV_BIN=str(fake / "diaWeaver"), VARIANT=variant, VFILE=str(vfile or ""), REAL_FF=real_ff,
                   REAL_FC=real_fc)
    C.reencode(q, "dwv_default", env, s, adir, rec, digest)
    return rec


good = case("G-V17 harness re-encode (real FileFilter -sort) on the numpress/unsorted fixture: passes", lambda: reenc("good"))
if good:
    a = good["reencoded_stats"]
    if "peak_digest" in a:
        check("  (fixed harness) raw and re-encoded m/z identical per spectrum (peak digest), raw unsorted 160",
              a["peak_digest"] == good["spectra_stats"]["peak_digest"] and good["spectra_stats"]["unsorted"] == 160,
              good["spectra_stats"].get("unsorted"))
    check("  re-encoded: 0 numpress, 0 unsorted, 0 undecoded, 0 length mismatch, same count, raw deleted",
          a["numpress_terms"] == 0 and a["unsorted"] == 0 and a["undecoded"] == 0 and a["length_mismatch"] == 0
          and good["output"]["count"] == n and not (W / "re" / "good" / "pseudo_spectra.mzML").exists(), a)
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "mzml_arrays.py"), good["output"]["path"], "--dump"],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    follows = all(sp.get("fragment_trace_id") and sp["fragment_trace_id"] == sorted(sp["fragment_trace_id"])
                  and len(sp["fragment_trace_id"]) == len(sp["mz"]) for sp in d["spectra_dump"])
    check("  independent parser: 0 unsorted, no numpress, float arrays moved with their peaks (trace ids ascend with m/z)",
          d["unsorted_spectra"] == 0 and not d["numpress_terms"] and d["spectra"] == n and follows,
          {k: d[k] for k in ("spectra", "unsorted_spectra", "numpress_terms", "zlib_arrays", "no_compression_arrays")})
    wid = {x for sp in d["spectra_dump"] for x in (sp.get("fragment_window_id") or [None])}
    check("  slof float array (fragment_window_id) decoded to zeros", wid == {0.0}, wid)
case("G-V17 un-fixed file passed off as the re-encode (numpress, unsorted)", lambda: reenc("unfixed", "copy", FX / "fx_dwv.mzML"),
     "G-V17", "numpress term")
case("G-V17 numpress residue (FileConverter -lossy_compression)", lambda: reenc("np", "numpress"), "G-V17", "numpress term")
case("G-V17 unsorted plain arrays", lambda: reenc("uns", "copy", FX / "res_unsorted.mzML"), "G-V17", "not m/z-sorted")
case("G-V17 spectra dropped", lambda: reenc("drop", "copy", FX / "res_drop.mzML"), "G-V17", "changed the spectrum count")
case("G-V17 a charge changed", lambda: reenc("charge", "copy", FX / "res_charge.mzML"), "G-V17", "changed RT, selected ion m/z, charge")
case("G-V17 zero spectra", lambda: reenc("zero", "copy", FX / "res_zero.mzML"), "G-V17", "count missing or <= 0")
case("G-V17 truncated output", lambda: reenc("half", "half", FX / "fx_dwv.mzML"), "G-V17", "not terminated")
case("G-V17 tool exit 1", lambda: reenc("fail", "fail"), "G-V17", "failed")
case("G-V17 tool wrote nothing", lambda: reenc("none", "none"), "G-V17", "output missing")
pl = case("G-V17 harness re-encode of a plain unsorted input: passes", lambda: reenc("plain", src=FX / "res_unsorted.mzML"))
shuf = case("G-V18 input: same spectra, other order and ids: re-encode passes", lambda: reenc("shuf", src=FX / "fx_dwv_shuf.mzML"))
shift = case("G-V18 input: one m/z moved: re-encode passes", lambda: reenc("shift", src=FX / "fx_dwv_shift.mzML"))
if good and shuf:
    rec = {"cells": {"a": {}, "b": {"differs_from": "a"}}, "arms": {"a": dict(good, status="ok"), "b": dict(shuf, status="ok")}}
    C.noop_check(rec)
    nz = rec["arms"]["b"]["noop"]
    check("G-V18 real files: same content in another order and ids is flagged (content equal, list digest not)",
          nz["flag"] and nz["content_equal"] and not nz["semantic_equal"], nz)
if pl and shift:
    rec = {"cells": {"a": {}, "b": {"differs_from": "a"}}, "arms": {"a": dict(pl, status="ok"), "b": dict(shift, status="ok")}}
    C.noop_check(rec)
    nz = rec["arms"]["b"]["noop"]
    check("G-V18 real files: one moved m/z is not flagged", not nz["flag"] and not nz["content_equal"], nz)

# ---- G-V16 through run_cell (identity check stubbed: not under test here)
C.check_identity = lambda *a, **k: None
staged = root / "stage" / "X-run" / "X.d"
staged.mkdir(parents=True)
(staged / "analysis.tdf").write_bytes(b"tdf")
(staged / "analysis.tdf_bin").write_bytes(b"bin")


def cell(name, dvar, vfile=None, count=None, cap_h=12, snap=None):
    qq = dict(q, cells={"dwv_default": dict(q["cells"]["dwv_default"], wall_cap_h=cap_h)})
    env = dict(cenv, DWV_BIN=str(fake / "diaWeaver"), DVAR=dvar, VFILE=str(vfile or ""), VCOUNT=str(count or 0),
               REAL_FF=real_ff, REAL_FC=real_fc)
    rec = {}
    old = C.proc_snapshot
    if snap:
        C.proc_snapshot = snap
    try:
        t = time.time()
        C.run_cell(qq, "dwv_default", staged, root / "runs" / name, env, env, {}, rec, digest)
        return rec
    finally:
        C.proc_snapshot = old
        rec["_elapsed"] = round(time.time() - t, 1)


okc = case("G-V16 cell ok (wrapper writes the numpress fixture), re-encoded by the real FileFilter",
           lambda: cell("ok", "ok", FX / "fx_dwv.mzML", n))
if okc:
    check("  cell record: log count, CPU, cap, not stopped, output is reencoded.mzML",
          okc["log_count"] == n and okc["stopped"] is None and okc["output"]["path"].endswith("reencoded.mzML")
          and okc["cpu"]["cpu_s"] is not None, {k: okc.get(k) for k in ("log_count", "stopped", "cpu", "wall_s")})
case("G-V16 no pseudo_spectra.mzML", lambda: cell("nofile", "nofile"), "G-V16", "wrote no pseudo_spectra.mzML")
case("G-V16 zero spectra (OpenMS file with count 0, no Done line)", lambda: cell("zero", "zero", FX / "res_zero.mzML"),
     "G-V16", "count missing or <= 0")
case("G-V16 exit 3", lambda: cell("exit3", "exit3"), "G-V16", "rc=3")
case("G-V16 log count differs", lambda: cell("miscount", "miscount", FX / "fx_dwv.mzML", n), "G-V16", "log count")
case("G-V16 no Done line", lambda: cell("nodone", "nodone", FX / "fx_dwv.mzML", n), "G-V16", "final rewrite")
case("G-V16 wall cap (7 s)", lambda: cell("slow", "slow", cap_h=0.002), "G-V16", "wall cap")
time.sleep(1)
left = subprocess.run(["pgrep", "-f", "dwvslowmarke[r]"], capture_output=True, text=True).stdout.split()
check("G-V16 wall cap: the tool's session is gone", not left, left)
low = lambda: {"t": time.monotonic(), "busy": 0, "ours": 0, "memavail_kb": 10, "memtotal_kb": 1000}
case("G-V16 memory floor", lambda: cell("mem", "slow", snap=low), "G-V16", "MemAvailable 1.0%")
time.sleep(1)
left = subprocess.run(["pgrep", "-f", "dwvslowmarke[r]"], capture_output=True, text=True).stdout.split()
check("G-V16 memory floor: the tool's session is gone", not left, left)

# ---- SIGTERM to a runner inside run_capped (the node-run handler): the tool's session must die with it
child = subprocess.Popen([sys.executable, "-c", r'''
import importlib.util, signal, sys, os
spec = importlib.util.spec_from_file_location("corpus", sys.argv[1]); C = importlib.util.module_from_spec(spec)
sys.modules["corpus"] = C; spec.loader.exec_module(C)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
env = dict(os.environ, DVAR="slow")
C.run_capped([sys.argv[2], "-in", "x", "-out", sys.argv[3], "-threads", "1"], sys.argv[3], env, C.Path(sys.argv[3]) / "log", 3600)
''', str(H), str(fake / "diaWeaver"), str(W)], env=dict(os.environ))
time.sleep(3)
before = subprocess.run(["pgrep", "-f", "dwvslowmarke[r]"], capture_output=True, text=True).stdout.split()
child.send_signal(signal.SIGTERM)
rc = child.wait(timeout=60)
time.sleep(1)
after = subprocess.run(["pgrep", "-f", "dwvslowmarke[r]"], capture_output=True, text=True).stdout.split()
check("G-V16 SIGTERM to the runner: tool was running, runner exits 143, session gone", before and rc == 143 and not after,
      (before, rc, after))
subprocess.run(["pkill", "-9", "-f", "dwvslowmarke[r]"])

bad = [r for r in RES if not r[0]]
for ok, name, detail in RES:
    print("%s  %-100s %s" % ("PASS" if ok else "FAIL", name[:100], detail))
print("%d/%d cases pass" % (len(RES) - len(bad), len(RES)))
