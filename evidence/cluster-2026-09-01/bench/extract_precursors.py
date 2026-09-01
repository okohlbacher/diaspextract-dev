#!/usr/bin/env python3
# Stream an mzML and emit per-MS2-spectrum: rt<TAB>precursor_mz<TAB>charge<TAB>npeaks
# Memory-bounded (clears each spectrum element). Usage: extract_precursors.py in.mzML out.tsv
import sys, xml.etree.ElementTree as ET

def local(tag): return tag.rsplit('}', 1)[-1]

def main(inp, outp):
    n = 0
    with open(outp, 'w') as w:
        for event, elem in ET.iterparse(inp, events=('end',)):
            if local(elem.tag) != 'spectrum':
                continue
            mslevel = rt = mz = mz827 = charge = None
            npeaks = elem.get('defaultArrayLength')
            # spectrum-level cvParams (ms level) + nested scan/precursor
            for cv in elem.iter():
                lt = local(cv.tag)
                if lt != 'cvParam':
                    continue
                acc = cv.get('accession'); val = cv.get('value')
                if acc == 'MS:1000511': mslevel = val
                elif acc == 'MS:1000016': rt = val
                elif acc == 'MS:1000744': mz = val               # selected ion m/z (our tool)
                elif acc == 'MS:1000827': mz827 = val            # isolation target (diaTracer's precursor m/z)
                elif acc == 'MS:1000041': charge = val
            if mslevel == '2':
                pm = mz if mz is not None else mz827             # prefer selected-ion, fall back to isolation target
                w.write(f"{rt}\t{pm}\t{charge}\t{npeaks}\n")
                n += 1
                if n % 100000 == 0:
                    sys.stderr.write(f"  {n} MS2...\n"); sys.stderr.flush()
            elem.clear()
    sys.stderr.write(f"done: {n} MS2 spectra\n")

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
