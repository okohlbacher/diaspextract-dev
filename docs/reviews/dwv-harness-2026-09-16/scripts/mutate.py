#!/usr/bin/env python3
"""Mutation proof for the review fixes: each fix reverted alone in a scratch copy; that copy's selftest must fail."""
import concurrent.futures, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path("/Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract")
SRC = (REPO / "harness" / "corpus.py").read_text()
M = [
    ("F1 content digest keeps dataProcessingRef", r'''rb'\s(?:id|index|spectrumRef|dataProcessingRef)="[^"]*"')''',
     r'''rb'\s(?:id|index|spectrumRef)="[^"]*"')'''),
    ("F2 run_group catches only Abort", "            except Exception as x:          # a crash inside one cell",
     "            except Abort as x:          # a crash inside one cell"),
    ("F3 add_split catches only Abort", "    except Exception as x:\n        if isinstance(x, Abort) and x.queue:\n            raise\n"
     "        g, msg = (x.guard, x.message) if isinstance(x, Abort) else (\"CRASH\", \"%s: %s\" % (type(x).__name__, x))\n"
     "        r.update(", "    except Abort as x:\n        if isinstance(x, Abort) and x.queue:\n            raise\n"
     "        g, msg = (x.guard, x.message) if isinstance(x, Abort) else (\"CRASH\", \"%s: %s\" % (type(x).__name__, x))\n"
     "        r.update("),
    ("F4 provenance data tree not checked", '    if len(data) != 1 or data[0] != cid["data_tree_sha256"]:', "    if False:"),
    ("F4 OPENMS_DATA_PATH not checked",
     '    if not data or os.path.realpath(data) != os.path.join(arm_dir, CELL_KINDS[c["kind"]]["data"]):', "    if False:"),
    ("F4 build identity without data tree/env.sh",
     '"data_tree_sha256": c.get("data_tree_sha256"), "env_sha256": c.get("env_sha256")}', "}"),
    ("F4 env.sh not hashed", '"env_sha256": sha256(Path(q["spx_root"]) / c["arm"] / "env.sh")}', '"env_sha256": None}'),
    ("F5 memory floor on one sample", "elif low >= MEM_FLOOR_SAMPLES:", "elif low >= 1:"),
    ("F6 cell TMPDIR is jnatmp", "    cenv = dict(cenv, TMPDIR=str(tmp))\n", "    cenv = dict(cenv)\n"),
    ("F7 no peak m/z comparison", '    if not after["peak_digest"] or after["peak_digest"] != before["peak_digest"]:', "    if False:"),
    ("F7 raw not decoded", "before, after = mzml_scan(src, decode=True), mzml_scan(dst, decode=True)",
     "before, after = mzml_scan(src), mzml_scan(dst, decode=True)"),
    ("F8 missing m/z array not checked", 'or after["missing_mz"] or after["bad_values"]:', 'or after["bad_values"]:'),
    ("F8 bad precursor value not checked", 'after["length_mismatch"] or after["missing_mz"] or after["bad_values"]:',
     'after["length_mismatch"] or after["missing_mz"]:'),
    ("F8 undecodable raw not refused", '    if before["undecoded"] or before["missing_mz"] or before["bad_values"]:', "    if False:"),
    ("F8 mzml_scan lets decode errors escape", "except (ValueError, IndexError, zlib.error, binascii.Error):", "except ():"),
    ("F9 table: split-less search not pending",
     '        if r["status"] == "ok" and ("entrapment" if e == "entrap" else "by_charge") not in r:', "        if False:"),
    ("F10 staged files keep umask mode", "            os.chmod(dst / f, 0o600)\n", ""),
    ("F11 non-integer charge crashes", "        return int(v)\n    except ValueError:", "        return int(v)\n    except KeyError:"),
    ("F12 numpress sign", "(res - (1 << 32) if res & 0x80000000 else res)", "res"),
    ("F12 numpress padding", "if di == n - 1 and half == 1 and data[di] & 0xF == 0:", "if False:"),
    ("F12 numpress leading ones",
     "(head - 8, (0xFFFFFFFF << (32 - 4 * (head - 8))) & 0xFFFFFFFF)", "(head - 8, 0)"),
    ("F13 import-time getsource (breaks python3 -)", "#@NUMPRESS_LINEAR@\n" + "'" * 3 + "       # the harness's own",
     "#@NUMPRESS_LINEAR@\n" + "'" * 3 + " + inspect.getsource(numpress_linear)       # the harness's own"),
]


def run(item):
    name, a, b = item
    n = SRC.count(a)
    if n != 1:
        return name, "BAD MUTATION (%d matches)" % n, ""
    td = Path(tempfile.mkdtemp(prefix="mut-"))
    (td / "harness").mkdir()
    (td / "harness" / "corpus.py").write_text(SRC.replace(a, b))
    os.symlink(REPO / "bench", td / "bench")
    r = subprocess.run([sys.executable, str(td / "harness" / "corpus.py"), "selftest"], capture_output=True, text=True)
    tail = [l for l in r.stdout.splitlines() if l.startswith("FAIL") or "cases pass" in l]
    shutil.rmtree(td, ignore_errors=True)
    return name, "KILLED" if r.returncode != 0 else "SURVIVED", " | ".join(x[:110] for x in tail[:3])


with concurrent.futures.ThreadPoolExecutor(4) as ex:
    res = list(ex.map(run, M))
for name, verdict, tail in res:
    print("%-9s %-48s %s" % (verdict, name, tail))
print("%d/%d mutations killed" % (sum(v == "KILLED" for _, v, _ in res), len(res)))
