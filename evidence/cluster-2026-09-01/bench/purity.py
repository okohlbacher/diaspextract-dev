#!/usr/bin/env python3
"""FRAGMENT PURITY + TURNOVER — the metric that makes 'swap bad fragments for good' measurable.

The whole thesis is that we must SWAP bad fragments for good ones at ~constant count (adding and
removing are both falsified). Nothing measured the swap. This does.

purity   = for spectra whose peptide is identified @1% FDR, the fraction of EMITTED fragments that
           match a theoretical b/y ion of the winning peptide within tol ppm.
turnover = Jaccard overlap of the emitted fragment m/z set vs a baseline run, per matched spectrum.

Usage: purity.py <pseudo.mzML> <results.sage.tsv> [baseline_pseudo.mzML]
"""
import re
import sys
import csv
import collections

PROTON = 1.00727646
H2O = 18.0105646
AA = {'G':57.02146,'A':71.03711,'S':87.03203,'P':97.05276,'V':99.06841,'T':101.04768,
      'C':103.00919,'L':113.08406,'I':113.08406,'N':114.04293,'D':115.02694,'Q':128.05858,
      'K':128.09496,'E':129.04259,'M':131.04049,'H':137.05891,'F':147.06841,'R':156.10111,
      'Y':163.06333,'W':186.07931}
FIXED_C = 57.02146  # carbamidomethyl, matches the Sage config


def strip_mods(pep):
    """Sage peptide strings carry mods like M[+15.9949]; return (sequence, {idx: mass})."""
    seq, mods, i = [], {}, 0
    for m in re.finditer(r'([A-Z])(\[[+-][0-9.]+\])?|(\[[+-][0-9.]+\])', pep):
        if m.group(1):
            seq.append(m.group(1))
            if m.group(2):
                mods[len(seq) - 1] = float(m.group(2)[1:-1])
            i += 1
        elif m.group(3):  # n-term
            mods[-1] = float(m.group(3)[1:-1])
    return ''.join(seq), mods


def theoretical_by(pep, max_charge=2):
    seq, mods = strip_mods(pep)
    if not seq:
        return []
    res = []
    for i, a in enumerate(seq):
        m = AA.get(a, 0.0) + (FIXED_C if a == 'C' else 0.0) + mods.get(i, 0.0)
        res.append(m)
    nterm = mods.get(-1, 0.0)
    out = []
    # b ions
    run = nterm
    for i in range(len(res) - 1):
        run += res[i]
        for z in range(1, max_charge + 1):
            out.append((run + z * PROTON) / z)
    # y ions
    run = H2O
    for i in range(len(res) - 1, 0, -1):
        run += res[i]
        for z in range(1, max_charge + 1):
            out.append((run + z * PROTON) / z)
    return sorted(out)


RE_SPEC = re.compile(rb'<spectrum [^>]*?index="(\d+)"')
RE_ID = re.compile(rb'<spectrum [^>]*?id="([^"]+)"')


def read_mz_arrays(path, wanted_ids=None):
    """Stream mzML, return {spectrum_id: [m/z...]} decoding base64 m/z arrays."""
    import base64
    import zlib
    import struct
    out = {}
    buf = b""
    CH = 1 << 24
    with open(path, "rb") as f:
        while True:
            c = f.read(CH)
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
                sid = mid.group(1).decode() if mid else None
                if wanted_ids is not None and sid not in wanted_ids:
                    continue
                # first binaryDataArray with MS:1000514 (m/z array)
                for bda in blk.split(b"<binaryDataArray")[1:]:
                    if b"MS:1000514" not in bda:
                        continue
                    b64 = re.search(rb"<binary>([^<]*)</binary>", bda)
                    if not b64:
                        break
                    raw = base64.b64decode(b64.group(1))
                    if b"MS:1000574" in bda:  # zlib
                        raw = zlib.decompress(raw)
                    n = len(raw) // (8 if b"MS:1000523" in bda else 4)
                    fmt = "<%dd" % n if b"MS:1000523" in bda else "<%df" % n
                    out[sid] = list(struct.unpack(fmt, raw[:n * (8 if b"MS:1000523" in bda else 4)]))
                    break
    return out


if __name__ == "__main__":
    mzml, tsv = sys.argv[1], sys.argv[2]
    base_mzml = sys.argv[3] if len(sys.argv) > 3 else None
    TOL = 20e-6

    ids = {}
    for x in csv.DictReader(open(tsv), delimiter="\t"):
        if float(x.get("spectrum_q", "1")) <= 0.01:
            ids[x["scannr"]] = x["peptide"]
    print("identified spectra @1%%: %d" % len(ids))

    spec = read_mz_arrays(mzml, set(ids))
    print("matched spectra in mzML: %d" % len(spec))

    purities, nfrags = [], []
    for sid, pep in ids.items():
        mzs = spec.get(sid)
        if not mzs:
            continue
        th = theoretical_by(pep)
        if not th:
            continue
        import bisect
        hit = 0
        for m in mzs:
            k = bisect.bisect_left(th, m)
            ok = False
            for kk in (k - 1, k):
                if 0 <= kk < len(th) and abs(th[kk] - m) <= m * TOL:
                    ok = True
                    break
            hit += ok
        purities.append(hit / max(len(mzs), 1))
        nfrags.append(len(mzs))

    purities.sort()
    nfrags.sort()
    if purities:
        n = len(purities)
        print("PURITY  n=%d  median=%.3f  mean=%.3f  IQR=[%.3f,%.3f]" % (
            n, purities[n // 2], sum(purities) / n, purities[n // 4], purities[3 * n // 4]))
        print("FRAGS/SPEC (identified only)  median=%d  IQR=[%d,%d]" % (
            nfrags[n // 2], nfrags[n // 4], nfrags[3 * n // 4]))
        print("EXPLAINED IONS/SPEC median=%.1f" % (purities[n // 2] * nfrags[n // 2]))

    if base_mzml:
        base = read_mz_arrays(base_mzml, set(ids))
        jac = []
        for sid in ids:
            a, b = spec.get(sid), base.get(sid)
            if not a or not b:
                continue
            sa = set(round(x, 2) for x in a)
            sb = set(round(x, 2) for x in b)
            if sa or sb:
                jac.append(len(sa & sb) / len(sa | sb))
        if jac:
            jac.sort()
            print("TURNOVER (Jaccard vs baseline) median=%.3f  (1.0 = identical fragment sets)" % jac[len(jac) // 2])
