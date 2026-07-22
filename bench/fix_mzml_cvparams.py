#!/usr/bin/env python3
"""Add value="" to valueless cvParams so MSFragger can read an OpenMS-written mzML.

OpenMS emits cvParams with no `value` attribute for terms that carry no value --
`instrument model`, `centroid spectrum`, `m/z array`, `32-bit float`, and others. That is
LEGAL: in the mzML schema `value` is optional.

MSFragger's reader (batmass-io) calls String.trim() on getValue() without a null check, so it
reports `Scans = 0` and rejects the whole file as corrupted. diaTracer writes value="" on every
cvParam, which is why its files read.

So this is an interoperability defect in OUR output, not in the benchmark: an OpenMS-written
mzML cannot be searched with one of the two most widely used engines. The proper fix belongs in
the writer; this streaming pass unblocks measurement in the meantime. Symmetrically, diaTracer's
mzML needs patching before SAGE can read it (missing selected ion m/z) -- both tools ship files
that one major engine rejects.

Single pass, no XML parsing: the files are 5-19 GB.
"""
import re, sys

# a cvParam element that has no value= attribute
PAT = re.compile(r'(<cvParam\b(?:(?!value=)[^>])*?)(/?>)')

def fix(inp, out):
    n = 0
    with open(inp, "r", encoding="utf-8", errors="replace") as f, \
         open(out, "w", encoding="utf-8") as g:
        for line in f:
            if "<cvParam" in line and "value=" not in line:
                line, k = PAT.subn(r'\1 value=""\2', line)
                n += k
            g.write(line)
    return n

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: %s IN.mzML OUT.mzML" % sys.argv[0])
    print("added value=\"\" to %d cvParams -> %s" % (fix(sys.argv[1], sys.argv[2]), sys.argv[2]))
