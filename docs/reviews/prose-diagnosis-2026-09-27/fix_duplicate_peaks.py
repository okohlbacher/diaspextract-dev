#!/usr/bin/env python3
"""Merge exact-duplicate fragment m/z values inside each spectrum of an mzML file (streaming).

Why: OpenMS MatchedIterator (DATASTRUCTURES/MatchedIterator.h:228-242), which HyperScore uses to
pair theoretical with experimental peaks (HyperScore.cpp:137), only steps forward while the
distance strictly shrinks. Two experimental peaks with the same m/z are equally distant from every
theoretical ion, so the iterator stops on the first of them and never gets past it again: no
theoretical ion above that m/z can match. diaTracer 2.2.1 pseudo-MS/MS spectra carry many exact
duplicate fragment m/z values, which leaves ProSE's scores close to random.

Spectra without duplicates are copied byte for byte. In a spectrum with duplicates each group of
equal m/z (compared at the stored precision) becomes one peak: intensity = max of the group
(default) or the sum (--merge sum); every other per-peak array takes the value of the kept peak;
peak order is kept; arrays are re-encoded with their own precision and compression;
defaultArrayLength / arrayLength / encodedLength and the spectrum-level total ion current and base
peak cvParams are updated. An indexedmzML input gets a fresh index and SHA-1 fileChecksum (offsets
move); a plain mzML stays plain. The output is re-read and checked before the script exits 0.

usage: fix_duplicate_peaks.py IN.mzML OUT.mzML [--merge max|sum]
"""
import argparse
import base64
import hashlib
import re
import struct
import sys
import zlib

PREC = {b'MS:1000521': 'f', b'MS:1000523': 'd', b'MS:1000519': 'i', b'MS:1000522': 'q'}
NUMPRESS = {b'MS:1002312', b'MS:1002313', b'MS:1002314', b'MS:1002746', b'MS:1002747', b'MS:1002748'}
ZLIB, MZ, INTENSITY = b'MS:1000574', b'MS:1000514', b'MS:1000515'
TIC, BP_MZ, BP_INT = b'MS:1000285', b'MS:1000504', b'MS:1000505'
ACC = re.compile(rb'accession="([^"]+)"')
ID = re.compile(rb'\sid="([^"]*)"')
BIN = re.compile(rb'<binary>([^<]*)</binary>')
VALUE = re.compile(rb'(\svalue=")[^"]*(")')


def attr(name):
    return re.compile(rb'(\s' + name + rb'=")\d+(")')


DAL, ARRLEN, ENCLEN = attr(b'defaultArrayLength'), attr(b'arrayLength'), attr(b'encodedLength')


def set_attr(rx, line, n):
    return rx.sub(lambda m: m.group(1) + str(n).encode() + m.group(2), line, count=1)


def find_arrays(lines):
    """[(start, end, accessions, binary_line_index)] for each binaryDataArray of a spectrum."""
    arrays, cur = [], None
    for i, ln in enumerate(lines):
        if b'<binaryDataArray ' in ln or b'<binaryDataArray>' in ln:
            cur = [i, None, set(), None]
        if cur is None:
            continue
        cur[2].update(ACC.findall(ln))
        if b'<binary>' in ln or b'<binary/>' in ln:
            cur[3] = i
        if b'</binaryDataArray>' in ln:
            cur[1] = i
            arrays.append(cur)
            cur = None
    return arrays


def decode(line, accs):
    m = BIN.search(line)
    raw = base64.b64decode(m.group(1)) if m else b''
    if ZLIB in accs:
        raw = zlib.decompress(raw) if raw else raw
    fmt = next(PREC[a] for a in accs if a in PREC)
    return list(struct.unpack('<%d%s' % (len(raw) // struct.calcsize(fmt), fmt), raw))


def encode(values, accs):
    fmt = next(PREC[a] for a in accs if a in PREC)
    raw = struct.pack('<%d%s' % (len(values), fmt), *values)
    if ZLIB in accs:
        raw = zlib.compress(raw)
    return base64.b64encode(raw)


def process(lines, merge, st):
    """Return the spectrum's lines with duplicate m/z merged (unchanged if there are none)."""
    st['spectra'] += 1
    arrays = find_arrays(lines)
    kinds = {}
    for a in arrays:
        if a[2] & NUMPRESS or a[3] is None or not any(p in a[2] for p in PREC):
            st['skipped_undecodable'] += 1
            return lines
        if MZ in a[2]:
            kinds['mz'] = a
        elif INTENSITY in a[2]:
            kinds['int'] = a
    if 'mz' not in kinds:
        return lines
    values = [decode(lines[a[3]], a[2]) for a in arrays]
    mz = values[arrays.index(kinds['mz'])]
    n = len(mz)
    st['peaks_in'] += n
    if len(set(mz)) == n:
        return lines
    if any(len(v) != n for v in values):
        st['skipped_length_mismatch'] += 1
        return lines
    inten = values[arrays.index(kinds['int'])] if 'int' in kinds else [0.0] * n
    groups = {}
    for i, x in enumerate(mz):
        groups.setdefault(x, []).append(i)
    keep, new_int = [], {}
    for idx in groups.values():
        if len(idx) == 1:
            keep.append(idx[0])
            continue
        st['dup_groups'] += 1
        st['dup_groups_equal_intensity'] += len({inten[i] for i in idx}) == 1
        st['max_group'] = max(st['max_group'], len(idx))
        if merge == 'max':
            keep.append(max(idx, key=lambda i: (inten[i], -i)))
        else:
            keep.append(idx[0])
            new_int[idx[0]] = sum(inten[i] for i in idx)
    keep.sort()
    m = len(keep)
    st['spectra_changed'] += 1
    st['peaks_removed'] += n - m
    out = list(lines)
    new_values = []
    for a, v in zip(arrays, values):
        nv = [new_int.get(i, v[i]) if a is kinds.get('int') else v[i] for i in keep]
        new_values.append(nv)
        b64 = encode(nv, a[2])
        out[a[3]] = BIN.sub(lambda _m: b'<binary>' + b64 + b'</binary>', out[a[3]], count=1)
        out[a[0]] = set_attr(ENCLEN, out[a[0]], len(b64))
        out[a[0]] = set_attr(ARRLEN, out[a[0]], m)
    out[0] = set_attr(DAL, out[0], m)
    if 'int' in kinds:  # spectrum-level summary cvParams (they precede scanList/precursorList)
        ni, nm = new_values[arrays.index(kinds['int'])], new_values[arrays.index(kinds['mz'])]
        top = max(range(m), key=lambda i: ni[i]) if m else None
        repl = {TIC: repr(float(sum(ni)))}
        if top is not None:
            repl[BP_INT], repl[BP_MZ] = repr(float(ni[top])), repr(float(nm[top]))
        for i in range(arrays[0][0]):
            if b'<scanList' in out[i] or b'<precursorList' in out[i]:
                break
            acc = ACC.search(out[i])
            if acc and acc.group(1) in repl:
                v = repl[acc.group(1)].encode()
                out[i] = VALUE.sub(lambda _m: _m.group(1) + v + _m.group(2), out[i], count=1)
    return out


def rewrite(inp, outp, merge):
    st = dict(spectra=0, spectra_changed=0, peaks_in=0, peaks_removed=0, dup_groups=0,
              dup_groups_equal_intensity=0, max_group=0, skipped_undecodable=0,
              skipped_length_mismatch=0)
    offsets = {b'spectrum': [], b'chromatogram': []}
    sha, pos, indexed, buf = hashlib.sha1(), 0, False, None
    with open(inp, 'rb') as fin, open(outp, 'wb') as fout:
        def w(b):
            nonlocal pos
            fout.write(b)
            sha.update(b)
            pos += len(b)

        for ln in fin:
            if buf is not None:
                buf.append(ln)
                if b'</spectrum>' in ln:
                    for x in process(buf, merge, st):
                        w(x)
                    buf = None
                continue
            if b'<indexedmzML' in ln:
                indexed = True
            for tag in (b'spectrum', b'chromatogram'):
                k = ln.find(b'<' + tag + b' ')
                if k >= 0:
                    offsets[tag].append((ID.search(ln, k).group(1), pos + k))
            if b'<spectrum ' in ln:
                if b'</spectrum>' in ln:
                    for x in process([ln], merge, st):
                        w(x)
                else:
                    buf = [ln]
                continue
            if indexed and b'</mzML>' in ln:
                k = ln.index(b'</mzML>') + len(b'</mzML>')
                w(ln[:k] + b'\n')
                names = [t for t in (b'spectrum', b'chromatogram') if offsets[t]]
                ilo = pos
                w(b'<indexList count="%d">\n' % len(names))
                for t in names:
                    w(b'  <index name="' + t + b'">\n')
                    for sid, off in offsets[t]:
                        w(b'    <offset idRef="' + sid + b'">%d</offset>\n' % off)
                    w(b'  </index>\n')
                w(b'</indexList>\n<indexListOffset>%d</indexListOffset>\n<fileChecksum>' % ilo)
                fout.write(sha.hexdigest().encode() + b'</fileChecksum>\n</indexedmzML>\n')
                break  # drop the input's (now stale) index
            w(ln)
    return st, indexed


def check(path, indexed):
    """Re-read the output: no duplicate m/z left; index offsets and checksum valid."""
    dups, n, offs = 0, 0, []
    with open(path, 'rb') as f:
        buf = None
        for ln in f:
            if b'<spectrum ' in ln:
                buf = [ln]
            elif buf is not None:
                buf.append(ln)
            if buf is not None and b'</spectrum>' in ln:
                n += 1
                arrays = find_arrays(buf)
                a = next((a for a in arrays if MZ in a[2]), None)
                if a is not None and a[3] is not None and not a[2] & NUMPRESS:
                    mz = decode(buf[a[3]], a[2])
                    dups += len(mz) != len(set(mz))
                buf = None
    problems = []
    if dups:
        problems.append('%d spectra still hold duplicate m/z' % dups)
    if indexed:
        data = open(path, 'rb').read()
        k = data.rindex(b'<fileChecksum>') + len(b'<fileChecksum>')
        if hashlib.sha1(data[:k]).hexdigest().encode() != data[k:k + 40]:
            problems.append('fileChecksum mismatch')
        ilo = int(re.search(rb'<indexListOffset>(\d+)</indexListOffset>', data[k - 200:]).group(1))
        if not data.startswith(b'<indexList', ilo):
            problems.append('indexListOffset does not point at <indexList')
        for sid, off in re.findall(rb'<offset idRef="([^"]*)">(\d+)</offset>', data[ilo:]):
            off = int(off)
            head = data[off:off + 400]
            if not (head.startswith(b'<spectrum ') or head.startswith(b'<chromatogram ')) \
                    or ID.search(head).group(1) != sid:
                problems.append('bad offset for %s' % sid.decode())
                break
    return n, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('inp')
    ap.add_argument('out')
    ap.add_argument('--merge', choices=('max', 'sum'), default='max')
    a = ap.parse_args()
    st, indexed = rewrite(a.inp, a.out, a.merge)
    n, problems = check(a.out, indexed)
    st['checked_spectra'] = n
    print(' '.join('%s=%s' % kv for kv in st.items()), file=sys.stderr)
    if problems or n != st['spectra']:
        sys.exit('CHECK FAILED: %s (spectra in %d, out %d)' % ('; '.join(problems), st['spectra'], n))


if __name__ == '__main__':
    main()
