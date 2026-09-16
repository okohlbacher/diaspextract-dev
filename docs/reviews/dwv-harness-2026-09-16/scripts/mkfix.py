#!/usr/bin/env python3
"""Re-encode guard fixtures from the first spectra of a PUBLIC HeLa diaTracer mzML (PXD017703). Review aid, not a
benchmark; stdlib only.

fx_dwv.mzML is diaWeaver-shaped: written by the fork's own FileConverter with -lossy_compression (numpress linear m/z,
slof intensity, both +zlib) from an MGF whose peak lists are shuffled in 2 of 3 spectra (the MGF reader keeps the
order), then given what diaWeaver writes and an MGF cannot carry: 1/K0 (MS:1002815, 0 in 3 of 4 spectra), real
isolation offsets, and two per-peak float arrays (fragment_trace_id as zlib float32 whose value encodes the peak's m/z
rank, fragment_window_id as numpress slof+zlib zeros). RT ties in pairs.
Variants: res_numpress (numpress kept), res_unsorted (plain arrays, peaks unsorted), res_drop (spectra dropped),
res_zero (no spectra), fx_dwv_shuf (the same spectra in another order with other ids), fx_dwv_shift (one m/z moved).
"""
import base64, math, os, random, re, struct, subprocess, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mzml_arrays as MA

SRC, OUT, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
ARM = "/ceph/ibmi/abi/oliver/spextract/diaweaver-7ed1169"
P = lambda n: os.path.join(OUT, n)


def arm(tool, *args):
    r = subprocess.run(["env", "-i", "HOME=" + os.environ["HOME"], "PATH=/usr/bin:/bin", "LC_ALL=C", "TMPDIR=" + OUT,
                        "bash", "-c", 'source "$1/env.sh" && shift && exec "$@"', "_", ARM, tool] + list(args),
                       capture_output=True, text=True)
    with open(P("tools.log"), "a") as f:
        f.write("$ %s %s\nrc=%d\n%s%s\n" % (tool, " ".join(args), r.returncode, r.stdout[-1500:], r.stderr[-1500:]))
    if r.returncode:
        sys.exit("%s %s failed rc %d: %s" % (tool, args, r.returncode, r.stderr[-500:]))


# ---- A: the first N spectra with >= 30 peaks
acc_re, val_re = re.compile(r'accession="(MS:\d+)"'), re.compile(r'\bvalue="([^"]*)"')
specs, cur, arr_acc = [], None, set()
with open(SRC) as f:
    for line in f:
        if "<spectrum " in line:
            cur, arr_acc = {}, set()
            continue
        if cur is None:
            continue
        if "<binaryDataArray " in line:
            arr_acc = set()
        elif "<cvParam" in line:
            a, v = acc_re.search(line), val_re.search(line)
            a = a.group(1) if a else ""
            arr_acc.add(a)
            if a == "MS:1000016":
                assert "UO:0000031" in line
                cur["rt"] = round(float(v.group(1)) * 60.0, 3)
            elif a == "MS:1000827":
                cur["mz"] = float(v.group(1))
            elif a == "MS:1000041":
                cur["z"] = int(v.group(1))
            elif a == "MS:1002815" and "im" not in cur:
                cur["im"] = float(v.group(1))
        elif "<binary>" in line:
            raw = zlib.decompress(base64.b64decode(line.split("<binary>")[1].split("</binary>")[0]))
            vals = list(struct.unpack("<%dd" % (len(raw) // 8), raw))
            cur["mzs" if "MS:1000514" in arr_acc else "ints"] = vals
        elif "</spectrum>" in line:
            if "z" in cur and len(cur.get("mzs", [])) >= 30 and len(cur["mzs"]) == len(cur.get("ints", [])):
                specs.append(cur)
            cur = None
            if len(specs) >= N:
                break
rnd = random.Random(20260916)
for i, s in enumerate(specs):
    pk = sorted(zip(s["mzs"], s["ints"]), key=lambda p: -p[1])[:500]       # diaWeaver caps at 500 peaks
    pk.sort()
    if i % 3:
        rnd.shuffle(pk)
    s["pk"] = pk
    if i % 2:
        s["rt"] = specs[i - 1]["rt"]                                          # RT ties in pairs
    s["im_w"] = float("%.15g" % s.get("im", 0.8)) if i % 4 == 0 else 0.0   # OpenMS writes 15 digits
    s["lo"], s["hi"] = round(5 + (i % 7) * 1.5, 4), round(6 + (i % 5) * 2.25, 4)
print("spectra", len(specs), "charges", sorted({s["z"] for s in specs}))

# ---- B: MGF -> OpenMS mzML (numpress and plain)
with open(P("fx.mgf"), "w") as f:
    for i, s in enumerate(specs):
        f.write("BEGIN IONS\nTITLE=fx%d\nPEPMASS=%r\nCHARGE=%d+\nRTINSECONDS=%r\n" % (i, s["mz"], s["z"], s["rt"]))
        f.write("".join("%r %r\n" % p for p in s["pk"]))
        f.write("END IONS\n")
arm("FileConverter", "-in", P("fx.mgf"), "-out", P("np_raw.mzML"), "-lossy_compression")
arm("FileConverter", "-in", P("fx.mgf"), "-out", P("plain_raw.mzML"))


# ---- C: add what diaWeaver writes
def slof_zeros(n):
    fp = 1.0
    return zlib.compress(struct.pack(">d", fp) + struct.pack("<%dH" % n, *([0] * n)))


def float_array(name, payload, n, accs):
    b = base64.b64encode(payload).decode()
    return ('\t\t\t\t\t\t<binaryDataArray arrayLength="%d" encodedLength="%d">\n' % (n, len(b))
            + "".join('\t\t\t\t\t\t\t<cvParam cvRef="MS" accession="%s" name="%s" />\n' % a for a in accs)
            + '\t\t\t\t\t\t\t<cvParam cvRef="MS" accession="MS:1000786" name="non-standard data array" value="%s" />\n' % name
            + "\t\t\t\t\t\t\t<binary>%s</binary>\n\t\t\t\t\t\t</binaryDataArray>\n" % b)


def inject(pin, pout, order=None, shift_first=False, plain=False):
    k, s, in_iso, mz_file = -1, None, False, None
    ids = order or list(range(len(specs)))
    with open(pin) as f:
        lines = f.readlines()
    # spectrum blocks, so that `order` can permute them
    head, blocks, tail, blk = [], [], [], None
    for line in lines:
        st = line.lstrip()
        if st.startswith("<indexedmzML") or st.startswith("<?xml") and head:
            continue
        if blk is None and "<spectrum " in line:
            blk = [line]
            continue
        if blk is not None:
            blk.append(line)
            if "</spectrum>" in line:
                blocks.append(blk)
                blk = None
            continue
        (tail if blocks else head).append(line)
        if st.startswith("</mzML>"):
            break
    assert len(blocks) == len(specs), (len(blocks), len(specs))
    out = list(head)
    for pos, k in enumerate(ids):
        s, blk = specs[k], blocks[k]
        mz_file, accs = None, set()
        for line in blk:
            st = line.lstrip()
            if st.startswith("<spectrum "):
                line = re.sub(r'index="\d+"', 'index="%d"' % pos, line)
                line = re.sub(r'id="[^"]*"', 'id="scan=%d"' % (pos + 1), line)
            if 'accession="MS:1000828"' in line or 'accession="MS:1000829"' in line:
                continue
            if "<binaryDataArray " in line:
                accs = set()
            if "<cvParam" in line:
                a = acc_re.search(line)
                accs.add(a.group(1) if a else "")
            if 'accession="MS:1000827"' in line:
                assert abs(float(val_re.search(line).group(1)) - s["mz"]) < 1e-6
                out.append(line)
                ind = line[:len(line) - len(st)]
                out.append('%s<cvParam cvRef="MS" accession="MS:1000828" name="isolation window lower offset" value="%s" '
                           'unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS" />\n' % (ind, "%.15g" % s["lo"]))
                out.append('%s<cvParam cvRef="MS" accession="MS:1000829" name="isolation window upper offset" value="%s" '
                           'unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS" />\n' % (ind, "%.15g" % s["hi"]))
                continue
            if st.startswith("<selectedIon>"):
                out.append(line)
                out.append('\t\t\t\t\t\t\t\t<cvParam cvRef="MS" accession="MS:1002815" name="inverse reduced ion mobility" '
                           'value="%s" unitAccession="MS:1002814" unitName="volt-second per square centimeter" '
                           'unitCvRef="MS" />\n' % ("%.15g" % s["im_w"]))
                continue
            if st.startswith("<binaryDataArrayList"):
                line = line.replace('count="2"', 'count="4"')
            if "<binary>" in line and "MS:1000514" in accs:
                raw = base64.b64decode(line.split("<binary>")[1].split("</binary>")[0])
                if "MS:1000574" in accs or "MS:1002746" in accs:
                    raw = zlib.decompress(raw)
                mz_file = MA.decode_linear(raw) if "MS:1002746" in accs else list(struct.unpack("<%dd" % (len(raw) // 8), raw))
                want = [p[0] for p in s["pk"]]
                assert len(mz_file) == len(want) and max(abs(a - b) for a, b in zip(mz_file, want)) < 1e-3, \
                    "OpenMS did not keep the MGF peak order in spectrum %d" % k
                if shift_first and pos == 0:
                    assert "MS:1002746" not in accs
                    mz_file[0] += 0.5
                    line = line.split("<binary>")[0] + "<binary>" + base64.b64encode(
                        struct.pack("<%dd" % len(mz_file), *mz_file)).decode() + "</binary>" + line.split("</binary>")[1]
            if st.startswith("</binaryDataArrayList>"):
                n = len(mz_file)
                rank = {j: r for r, j in enumerate(sorted(range(n), key=lambda j: mz_file[j]))}
                tid = [float(100000 * (k + 1) + rank[j]) for j in range(n)]
                out.append(float_array("fragment_trace_id", zlib.compress(struct.pack("<%df" % n, *tid)), n,
                                       [("MS:1000521", "32-bit float"), ("MS:1000574", "zlib compression")]))
                out.append(float_array("fragment_window_id", zlib.compress(struct.pack("<%df" % n, *([0.0] * n))), n,
                                       [("MS:1000521", "32-bit float"), ("MS:1000574", "zlib compression")]) if plain else
                           float_array("fragment_window_id", slof_zeros(n), n,
                                       [("MS:1000521", "32-bit float"),
                                        ("MS:1002748", "MS-Numpress short logged float compression followed by zlib compression")]))
            out.append(line)
        assert mz_file is not None
    out += tail
    with open(pout, "w") as f:
        f.write("".join(out))


inject(P("np_raw.mzML"), P("fx_dwv.mzML"))
inject(P("plain_raw.mzML"), P("res_unsorted.mzML"), plain=True)
perm = list(range(len(specs)))
random.Random(5).shuffle(perm)
inject(P("np_raw.mzML"), P("fx_dwv_shuf.mzML"), order=perm)
inject(P("plain_raw.mzML"), P("fx_dwv_shift.mzML"), shift_first=True, plain=True)

# ---- D: re-encoded variants
arm("FileConverter", "-in", P("fx_dwv.mzML"), "-out", P("res_numpress.mzML"), "-lossy_compression")
rts = sorted(s["rt"] for s in specs)
arm("FileFilter", "-in", P("fx_dwv.mzML"), "-out", P("res_drop.mzML"), "-sort", "-rt", ":%r" % rts[len(rts) // 2])
arm("FileFilter", "-in", P("fx_dwv.mzML"), "-out", P("res_zero.mzML"), "-sort", "-rt", "0:1")
arm("FileFilter", "-in", P("fx_dwv.mzML"), "-out", P("good.mzML"), "-sort")
txt = open(P("good.mzML")).read()
i = txt.index('accession="MS:1000041"')
j = txt.index('value="', i) + len('value="')
z = int(txt[j:txt.index('"', j)])
with open(P("res_charge.mzML"), "w") as f:
    f.write(txt[:j] + str(z + 1) + txt[txt.index('"', j):])
print("fixtures written")
