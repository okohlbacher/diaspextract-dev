#!/usr/bin/env python3
"""The harness's G-V17 path on REAL diaWeaver spectra (public HeLa PXD017703 run 2731, smoke intermediate, first N
complete spectra), put through diaWeaver's own final step (reload + numpress store) by the arm's FileConverter.
Review aid, not a benchmark.  usage: realtest.py CORPUS_PY INTERMEDIATE WORKDIR N"""
import base64, importlib.util, json, re, shutil, struct, subprocess, sys, time, zlib
from pathlib import Path

H, SRC, W, N = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3]).resolve(), int(sys.argv[4])
spec = importlib.util.spec_from_file_location("corpus", H)
C = importlib.util.module_from_spec(spec)
sys.modules["corpus"] = C
spec.loader.exec_module(C)
ARM = "/ceph/ibmi/abi/oliver/spextract/diaweaver-7ed1169"
W.mkdir(mode=0o700, parents=True)
out = {}

# 1. the intermediate as diaWeaver wrote it (unsorted by design, per the code reading)
t = time.time()
inter = C.mzml_scan(SRC, decode=True)
out["intermediate"] = {k: inter[k] for k in ("spectra", "unsorted", "undecoded", "length_mismatch", "missing_mz",
                                             "bad_values", "im_zero", "im_missing", "charges", "peaks_min", "peaks_median",
                                             "numpress_terms")}
out["intermediate_scan_s"] = round(time.time() - t, 1)

# 2. the first N complete spectra as a terminated plain mzML
cut = W / "cut.mzML"
with open(SRC, "rb") as f, open(cut, "wb") as g:
    k, blk = 0, None
    for line in f:
        if blk is None and b"<spectrum " not in line:
            if line.lstrip().startswith(b"<indexedmzML"):
                continue
            g.write(re.sub(rb'<spectrumList count="\d+"', b'<spectrumList count="%d"' % N, line) if b"<spectrumList" in line else line)
            continue
        if b"<spectrum " in line:
            blk = [line]
            continue
        blk.append(line)
        if b"</spectrum>" in line:
            g.write(b"".join(blk))
            blk, k = None, k + 1
            if k == N:
                break
    g.write(b"\t\t</spectrumList>\n\t</run>\n</mzML>\n")


def arm(tool, *args):
    r = subprocess.run(["env", "-i", "HOME=/nonexistent", "PATH=/usr/bin:/bin", "LC_ALL=C", "TMPDIR=" + str(W),
                        "bash", "-c", 'source "$1/env.sh" && shift && exec "$@"', "_", ARM, tool] + list(args),
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit("%s failed: %s" % (tool, r.stderr[-400:]))


# 3. diaWeaver's final step: reload (sorts peaks) and store with numpress (FileConverter -lossy_compression)
final = W / "run" / "pseudo_spectra.mzML"
final.parent.mkdir()
t0 = time.time() - 1
arm("FileConverter", "-in", str(cut), "-out", str(final), "-lossy_compression")
fin = C.mzml_scan(final, decode=True)
out["final_like"] = {k: fin[k] for k in ("spectra", "unsorted", "undecoded", "numpress_terms", "missing_mz", "bad_values")}
kinds = {}
for line in open(final, "rb"):
    for a in re.findall(rb'accession="(MS:100(?:0514|0515|0786|0521|0522|0523|0574|0576|2746|2747|2748|2312|2313|2314))"', line):
        kinds[a.decode()] = kinds.get(a.decode(), 0) + 1
out["final_like_array_terms"] = kinds

# 4. the harness re-encode with the real FileFilter
q = {"spx_root": "/ceph/ibmi/abi/oliver/spextract", "jnatmp": str(W), "root": str(W),
     "cells": {"dwv_default": {"kind": "dwv", "arm": "diaweaver-7ed1169", "args": [], "wall_cap_h": 12}}}
cenv = C.cell_env(q, "dwv_default")
rec = {"raw_output": C.verify_mzml(final, t0)}
digest = C.load_module("/ceph/ibmi/abi/oliver/spextract/tools/semantic_digest.py", "sd").digest
keep = W / "final_copy.mzML"
shutil.copyfile(final, keep)
try:
    C.reencode(q, "dwv_default", cenv, final, final.parent, rec, digest)
    out["reencode"] = "PASS"
except C.Abort as a:
    out["reencode"] = "ABORT [%s] %s" % (a.guard, a.message)
if "reencoded_stats" in rec:
    out["reencoded"] = {k: rec["reencoded_stats"][k] for k in ("spectra", "unsorted", "undecoded", "numpress_terms",
                                                                "missing_mz", "bad_values", "missing_selected_ion")}
    out["peak_digest_equal"] = rec["spectra_stats"]["peak_digest"] == rec["reencoded_stats"]["peak_digest"]
    out["prec_digest_equal"] = rec["spectra_stats"]["prec_digest"] == rec["reencoded_stats"]["prec_digest"]


# 5. integer trace ids still attached to their peaks: per spectrum id, sorted (m/z, trace_id) of the numpress file == re-encode
def pairs(path):
    res, cur, accs, arrs = {}, None, set(), {}
    for line in open(path, "rb"):
        if b"<spectrum " in line:
            cur, arrs = re.search(rb'id="([^"]*)"', line).group(1), {}
        if b"<binaryDataArray " in line or b"<binaryDataArray>" in line:
            accs, name = set(), None
        for a in re.findall(rb'accession="(MS:\d+)"', line):
            accs.add(a)
        m = re.search(rb'value="(fragment_trace_id)"', line)
        if m:
            accs.add(b"trace")
        if b"<binary>" in line:
            raw = base64.b64decode(line.split(b"<binary>")[1].split(b"</binary>")[0])
            if b"MS:1000574" in accs or b"MS:1002746" in accs or b"MS:1002748" in accs:
                raw = zlib.decompress(raw)
            if b"MS:1000514" in accs:
                arrs["mz"] = C.numpress_linear(raw) if b"MS:1002746" in accs else list(struct.unpack("<%dd" % (len(raw) // 8), raw))
            elif b"trace" in accs:
                arrs["tid"] = ("int64", list(struct.unpack("<%dq" % (len(raw) // 8), raw))) if b"MS:1000522" in accs else \
                    ("other", sorted(accs))
        if b"</spectrum>" in line:
            if "tid" in arrs and arrs["tid"][0] == "int64":
                res[cur] = sorted(zip(arrs["mz"], arrs["tid"][1]))
            else:
                res[cur] = ("no int64 trace array", arrs.get("tid"))
    return res


a, b = pairs(keep), pairs(final.parent / "reencoded.mzML") if (final.parent / "reencoded.mzML").exists() else {}
out["trace_pairs"] = {"spectra_before": len(a), "spectra_after": len(b),
                      "equal": sum(1 for k in a if b.get(k) == a[k]),
                      "sample_after": str(next(iter(b.values())))[:160] if b else None}
print(json.dumps(out, indent=1))
