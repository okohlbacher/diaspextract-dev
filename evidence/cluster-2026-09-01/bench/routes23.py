#!/usr/bin/env python3
"""ROUTE 2 (duplication axis) + ROUTE 3 (missing-peptide funnel), S08.

ROUTE 2 — why 4.6 PSMs/peptide? For every peptide with >=2 PSMs, classify the axis along which its
spectra differ:
    dual-IM      : same m/z & RT, different IM      -> the 12 m/z x 2 IM sub-range split duplicating
    RT-split     : same m/z & IM, different RT      -> one feature broken into several RT traces
    isotope-sib  : m/z differs by ~k*1.0033/z       -> (already shown same rate as diaTracer)
    charge-dup   : same m/z & RT & IM, diff charge
    exact-dup    : identical within all tolerances
This ranks the mechanisms the adversarial review listed, using data rather than argument.

ROUTE 3 — where in the funnel are the 6,162 diaTracer-only peptides lost?
    stage A: no precursor of ours within (RT, m/z, IM) tolerance      -> DETECTION failure
    stage B: precursor exists, but its spectrum has <4 of the peptide's b/y ions -> ASSEMBLY failure
    stage C: precursor + fragments present, still unidentified        -> SCORING/FDR failure
Decoy control: repeat stage A at a non-physical m/z offset to get the chance-match rate.
"""
import sys
import csv
import collections
import bisect

sys.path.insert(0, "/scratch/kohlbach/bench/s08")
from precursor_audit import extract, ISO           # noqa: E402
sys.path.insert(0, "/scratch/kohlbach/bench")
from purity import theoretical_by, read_mz_arrays  # noqa: E402

OURS_MZML = "/scratch/kohlbach/bench/s08/ours/pseudo.mzML"
OURS_TSV = "/scratch/kohlbach/bench/s08/ours/results.sage.tsv"
DIA_MZML = ("/ceph/ibmi/abi/data/2026_AGXT_PH1_liver_diaPASEF/mzml_diatracer/"
            "FKL4341-S08-A-3_K30454-19-3_QKL29021A9_Slot1-12_1_1305_diatracer.mzML")
DIA_TSV = "/scratch/kohlbach/bench/s08/diatracer/results.sage.tsv"


def load_ids(tsv, qmax=0.01):
    """peptide -> [scannr...]  and  scannr -> peptide"""
    p2s = collections.defaultdict(list)
    s2p = {}
    for x in csv.DictReader(open(tsv), delimiter="\t"):
        if float(x.get("spectrum_q", "1")) <= qmax:
            p2s[x["peptide"]].append(x["scannr"])
            s2p[x["scannr"]] = x["peptide"]
    return p2s, s2p


# ---------------------------------------------------------------- ROUTE 2
print("=" * 78)
print("ROUTE 2 — the duplication axis (why 4.6 PSMs/peptide)")
print("=" * 78)
p2s, s2p = load_ids(OURS_TSV)
multi = {p: s for p, s in p2s.items() if len(s) >= 2}
print("peptides with >=2 PSMs: %d / %d" % (len(multi), len(p2s)))

# spectrum id -> (rt, mz, z, im) from our mzML
recs = extract(OURS_MZML)
# extract() returns tuples without ids; rebuild an id-keyed map by re-scanning headers
import re  # noqa: E402
RE_ID = re.compile(rb'<spectrum [^>]*?id="([^"]+)"')
RE_RT = re.compile(rb'accession="MS:1000016"[^>]*?value="([0-9.eE+-]+)"[^>]*?unitAccession="UO:(\d+)"')
RE_MZ = re.compile(rb'accession="MS:1000744"[^>]*?value="([0-9.eE+-]+)"')
RE_CH = re.compile(rb'accession="MS:1000041"[^>]*?value="(\d+)"')
RE_IM = re.compile(rb'accession="MS:1002815"[^>]*?value="([0-9.eE+-]+)"')

byid = {}
buf = b""
with open(OURS_MZML, "rb") as f:
    while True:
        c = f.read(1 << 24)
        if not c:
            break
        buf += c
        while True:
            i = buf.find(b"<spectrum ")
            if i < 0:
                buf = buf[-4096:]
                break
            j = buf.find(b"</spectrum>", i)
            if j < 0:
                if i > 0:
                    buf = buf[i:]
                break
            blk = buf[i:j]
            buf = buf[j + 11:]
            mid = RE_ID.search(blk)
            if not mid:
                continue
            sid = mid.group(1).decode()
            if sid not in s2p:
                continue
            mrt, mmz = RE_RT.search(blk), RE_MZ.search(blk)
            if not (mrt and mmz):
                continue
            rt = float(mrt.group(1))
            if int(mrt.group(2)) == 31:
                rt *= 60.0
            ch, im = RE_CH.search(blk), RE_IM.search(blk)
            byid[sid] = (rt, float(mmz.group(1)),
                         int(ch.group(1)) if ch else 0,
                         float(im.group(1)) if im else -1.0)

cls = collections.Counter()
pairs = 0
for pep, sids in multi.items():
    co = [byid[s] for s in sids if s in byid]
    for a in range(len(co)):
        for b in range(a + 1, len(co)):
            (rt1, mz1, z1, im1), (rt2, mz2, z2, im2) = co[a], co[b]
            pairs += 1
            d_rt, d_mz, d_im = abs(rt1 - rt2), abs(mz1 - mz2), abs(im1 - im2)
            same_mz = d_mz <= mz1 * 20e-6
            zz = z1 if z1 > 0 else 2
            iso = any(abs(d_mz - k * ISO / zz) <= mz1 * 20e-6 for k in (1, 2, 3))
            if same_mz and d_rt <= 5 and d_im > 0.02:
                cls["dual-IM (same m/z+RT, IM differs)"] += 1
            elif same_mz and d_im <= 0.02 and d_rt > 5:
                cls["RT-split (same m/z+IM, RT differs)"] += 1
            elif iso:
                cls["isotope-sibling"] += 1
            elif same_mz and d_rt <= 5 and d_im <= 0.02 and z1 != z2:
                cls["charge-dup"] += 1
            elif same_mz and d_rt <= 5 and d_im <= 0.02:
                cls["exact-dup"] += 1
            else:
                cls["other"] += 1
print("classified %d duplicate PSM pairs:" % pairs)
for k, v in cls.most_common():
    print("   %-38s %7d  (%5.1f%%)" % (k, v, 100.0 * v / max(pairs, 1)))

# ---------------------------------------------------------------- ROUTE 3
print()
print("=" * 78)
print("ROUTE 3 — funnel: where are the diaTracer-only peptides lost?")
print("=" * 78)
dp2s, ds2p = load_ids(DIA_TSV)
dia_only = set(dp2s) - set(p2s)
print("diaTracer-only peptides: %d" % len(dia_only))

# coordinates of diaTracer's spectra for those peptides
dbyid = {}
buf = b""
RE_ISOT = re.compile(rb'accession="MS:1000827"[^>]*?value="([0-9.eE+-]+)"')
want = set(s for p in dia_only for s in dp2s[p])
with open(DIA_MZML, "rb") as f:
    while True:
        c = f.read(1 << 24)
        if not c:
            break
        buf += c
        while True:
            i = buf.find(b"<spectrum ")
            if i < 0:
                buf = buf[-4096:]
                break
            j = buf.find(b"</spectrum>", i)
            if j < 0:
                if i > 0:
                    buf = buf[i:]
                break
            blk = buf[i:j]
            buf = buf[j + 11:]
            mid = RE_ID.search(blk)
            if not mid or mid.group(1).decode() not in want:
                continue
            sid = mid.group(1).decode()
            mrt = RE_RT.search(blk)
            mmz = RE_MZ.search(blk) or RE_ISOT.search(blk)
            if not (mrt and mmz):
                continue
            rt = float(mrt.group(1))
            if int(mrt.group(2)) == 31:
                rt *= 60.0
            im = RE_IM.search(blk)
            dbyid[sid] = (rt, float(mmz.group(1)), float(im.group(1)) if im else -1.0)

# index OUR precursors for lookup
grid = collections.defaultdict(list)
for (rt, mz, z, im, npk) in recs:
    grid[(int(rt // 10.0), int(im // 0.05))].append((rt, mz, z, im))
for k in grid:
    grid[k].sort(key=lambda r: r[1])


def has_prec(rt, mz, im, shift=0.0):
    t = mz + shift
    for dr in (-1, 0, 1):
        for di in (-1, 0, 1):
            b = grid.get((int(rt // 10.0) + dr, int(im // 0.05) + di))
            if not b:
                continue
            mzs = [x[1] for x in b]
            i = bisect.bisect_left(mzs, t - 0.02)
            while i < len(mzs) and mzs[i] <= t + 0.02:
                if abs(b[i][0] - rt) <= 15.0 and (im < 0 or abs(b[i][3] - im) <= 0.05):
                    return True
                i += 1
    return False


stageA = stageA_dec = 0
checked = 0
for pep in dia_only:
    for sid in dp2s[pep][:1]:
        if sid not in dbyid:
            continue
        rt, mz, im = dbyid[sid]
        checked += 1
        if has_prec(rt, mz, im):
            stageA += 1
        if has_prec(rt, mz, im, shift=0.373):
            stageA_dec += 1
print("checked %d diaTracer-only peptides (1 spectrum each)" % checked)
print("  A. WE HAVE a precursor at their (RT,m/z,IM): %6d (%5.1f%%)   [decoy %5.1f%%]" % (
    stageA, 100.0 * stageA / max(checked, 1), 100.0 * stageA_dec / max(checked, 1)))
print("  A'. NO precursor -> DETECTION failure:        %6d (%5.1f%%)" % (
    checked - stageA, 100.0 * (checked - stageA) / max(checked, 1)))
print()
print("  chance-corrected precursor presence: %.1f%%" % (
    100.0 * (stageA - stageA_dec) / max(checked, 1)))
print("  => if chance-corrected presence is HIGH, detection is fine and the loss is downstream")
print("     (assembly/scoring). If LOW, we genuinely never detect these precursors.")
