#!/usr/bin/env python3
"""Inspect mzML binary arrays (stdlib only): compression terms, m/z sortedness, precursor cvParams.

Smoke-check helper for the diaWeaver re-encode option test on a synthetic file; the harness guard
(slice harness) is the real check on production output.
Usage: mzml_arrays.py FILE [--dump]   -> prints one JSON object.
"""
import base64, json, math, struct, sys, zlib, hashlib
import xml.etree.ElementTree as ET

NS = '{http://psi.hupo.org/ms/mzml}'
NUMPRESS_LINEAR = {'MS:1002312', 'MS:1002746'}          # linear, linear+zlib
NUMPRESS_ANY = {'MS:1002312', 'MS:1002313', 'MS:1002314', 'MS:1002746', 'MS:1002747', 'MS:1002748'}
ZLIB = {'MS:1000574', 'MS:1002746', 'MS:1002747', 'MS:1002748'}
PREC_TERMS = ('MS:1000744', 'MS:1000827', 'MS:1002815', 'MS:1000041', 'MS:1000828', 'MS:1000829')


def _decode_int(data, st):
    """Port of MSNumpress decodeInt; st = [di, half]."""
    di, half = st
    head = (data[di] >> 4) if half == 0 else (data[di] & 0xF)
    if half == 1:
        di += 1
    half = 1 - half
    res = 0
    if head <= 8:
        n = head
    else:
        n = head - 8
        for i in range(n):
            res |= (0xF0000000 >> (4 * i))
    if n != 8:
        for i in range(n, 8):
            if half == 0:
                hb = data[di] >> 4
            else:
                hb = data[di] & 0xF
                di += 1
            res |= hb << ((i - n) * 4)
            half = 1 - half
    st[0], st[1] = di, half
    return res - (1 << 32) if res & 0x80000000 else res


def decode_linear(data):
    n = len(data)
    if n <= 8:
        return []
    fp = struct.unpack('>d', data[:8])[0]
    i1 = struct.unpack('<i', data[8:12])[0] & 0xFFFFFFFF
    out = [i1 / fp]
    if n == 12:
        return out
    i2 = struct.unpack('<i', data[12:16])[0] & 0xFFFFFFFF
    out.append(i2 / fp)
    ints = [0, i1, i2]
    st = [16, 0]
    while st[0] < n:
        if st[0] == n - 1 and st[1] == 1 and (data[st[0]] & 0xF) == 0:
            break
        ints[0], ints[1] = ints[1], ints[2]
        diff = _decode_int(data, st)
        y = ints[1] + (ints[1] - ints[0]) + diff
        out.append(y / fp)
        ints[2] = y
    return out


def decode_slof(data):
    if len(data) < 8:
        return []
    fp = struct.unpack('>d', data[:8])[0]
    xs = struct.unpack('<%dH' % ((len(data) - 8) // 2), data[8:8 + 2 * ((len(data) - 8) // 2)])
    return [math.exp(x / fp) - 1 for x in xs]


def decode_array(bda):
    accs = {c.get('accession') for c in bda.iter(NS + 'cvParam')}
    raw = base64.b64decode((bda.find(NS + 'binary').text or '').strip())
    if accs & ZLIB:
        raw = zlib.decompress(raw) if raw else raw
    if accs & NUMPRESS_LINEAR:
        return accs, decode_linear(raw)
    if accs & {'MS:1002314', 'MS:1002748'}:
        return accs, decode_slof(raw)
    if accs & NUMPRESS_ANY:
        return accs, None  # pic not handled
    if 'MS:1000523' in accs:
        return accs, list(struct.unpack('<%dd' % (len(raw) // 8), raw))
    return accs, list(struct.unpack('<%df' % (len(raw) // 4), raw))


def main():
    path = sys.argv[1]
    dump = '--dump' in sys.argv
    r = {'file': path, 'spectra': 0, 'peaks': 0, 'unsorted_spectra': 0, 'mz_undecodable': 0,
         'numpress_terms': {}, 'zlib_arrays': 0, 'no_compression_arrays': 0,
         'arrays_total': 0, 'precursor_terms': {t: 0 for t in PREC_TERMS}, 'spectra_dump': []}
    h = hashlib.sha256()
    for _, el in ET.iterparse(path, events=('end',)):
        if el.tag != NS + 'spectrum':
            continue
        r['spectra'] += 1
        for pre in el.iter(NS + 'precursor'):
            for c in pre.iter(NS + 'cvParam'):
                a = c.get('accession')
                if a in r['precursor_terms']:
                    r['precursor_terms'][a] += 1
        mz = None
        inten = None
        extra = {}
        for bda in el.iter(NS + 'binaryDataArray'):
            accs, vals = decode_array(bda)
            r['arrays_total'] += 1
            for a in accs & NUMPRESS_ANY:
                r['numpress_terms'][a] = r['numpress_terms'].get(a, 0) + 1
            if 'MS:1000574' in accs:
                r['zlib_arrays'] += 1
            if 'MS:1000576' in accs:
                r['no_compression_arrays'] += 1
            if 'MS:1000514' in accs:
                mz = vals
            elif 'MS:1000515' in accs:
                inten = vals
            else:
                names = [c.get('value') or c.get('name') for c in bda.iter(NS + 'cvParam')
                         if c.get('accession') in ('MS:1000786', 'MS:1003008', 'MS:1002893')]
                names += [u.get('name') for u in bda.iter(NS + 'userParam')]
                extra[(names or ['?'])[0]] = vals
        if mz is None:
            r['mz_undecodable'] += 1
        else:
            r['peaks'] += len(mz)
            if any(mz[i] > mz[i + 1] for i in range(len(mz) - 1)):
                r['unsorted_spectra'] += 1
            h.update(el.get('id', '').encode())
            h.update(json.dumps(sorted(round(x, 3) for x in mz)).encode())
            if dump:
                rec = {'id': el.get('id'), 'mz': [round(x, 5) for x in mz]}
                if inten is not None:
                    rec['int'] = [round(x, 1) for x in inten]
                for k, v in extra.items():
                    rec[k] = None if v is None else [round(x, 3) for x in v]
                r['spectra_dump'].append(rec)
        el.clear()
    r['sorted_mz_content_sha256'] = h.hexdigest()[:16]
    if not dump:
        del r['spectra_dump']
    print(json.dumps(r, indent=1))


if __name__ == '__main__':
    main()
