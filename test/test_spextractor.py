#!/usr/bin/env python3
"""End-to-end checks on a synthetic input. No framework, no fixtures: one file, plain asserts.

Verification on this project has been whole-file cluster benchmarks, which catch regressions in
aggregate but cannot say WHY a number moved, and cannot run before a commit. These are the smallest
checks that fail if the things most likely to break do break:

  1. isotope ownership   one z=2 envelope (M, M+1, M+2) must yield ONE precursor at the mono, not
                         three, and the M+1/M+2 peaks must not reseed precursors of their own
  2. min_charge          a supported z=1 envelope is emitted at the default (1) and dropped at 2, while a
                         z=2 envelope is unaffected either way
  3. parameter bounds    a negative count must be REJECTED, not wrapped through Size into an
                         empty-but-successful run
  4. determinism         the same input at 1 and 4 threads must give byte-identical spectrum data
  5. trace extension     one missing cycle must leave ONE trace and its gapped fragment in the
                         spectrum; seven missing cycles must give TWO traces. Every version of the
                         integer detector that lost 92% of the peptides passed checks 1-4.
  ... 14. writer           count, id="spectrum=K", index="K" and the <indexList> offsets agree

These exercise the default (OpenMS) detector only. `trace:detector=integer` refuses to run
without the vendor flight-time calibration, which a synthetic mzML cannot carry, so it is judged on
real data in the benchmark harness and not here.

Usage: test_spextractor.py /path/to/spextractor [workdir]
Exit status is 0 only if every check passes.
"""
import base64, hashlib, os, re, struct, subprocess, sys, tempfile

ISO = 1.0033548
PROTON = 1.007276


def b64f(vals, double=True):
    fmt = "<%d%s" % (len(vals), "d" if double else "f")
    return base64.b64encode(struct.pack(fmt, *vals)).decode()


def spectrum(idx, ms_level, rt, peaks, im, prec=None, group=0):
    """One mzML spectrum. `peaks` is [(mz, intensity)], `im` one 1/K0 per peak."""
    mz = b64f([p[0] for p in peaks])
    inten = b64f([p[1] for p in peaks], double=False)
    imarr = b64f(im)
    pre = ""
    if prec:
        target, lo, hi = prec
        pre = f"""<precursorList count="1"><precursor><isolationWindow>
<cvParam cvRef="MS" accession="MS:1000827" name="isolation window target m/z" value="{target}" unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS"/>
<cvParam cvRef="MS" accession="MS:1000828" name="isolation window lower offset" value="{target-lo}" unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS"/>
<cvParam cvRef="MS" accession="MS:1000829" name="isolation window upper offset" value="{hi-target}" unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS"/>
</isolationWindow><activation><cvParam cvRef="MS" accession="MS:1000044" name="dissociation method"/></activation></precursor></precursorList>"""
    # "frame=<N>" is the vendor key frameIdOf() parses; without it every frame is unmappable and
    # the integer detector falls back, which is how all 8 checks silently ran on the OTHER detector.
    return f"""<spectrum id="frame={idx + 1} windowGroup={group} scan=0" index="{idx}" defaultArrayLength="{len(peaks)}">
<cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum"/>
<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="{ms_level}"/>
<cvParam cvRef="MS" accession="MS:1000294" name="mass spectrum"/>
<scanList count="1"><cvParam cvRef="MS" accession="MS:1000795" name="no combination"/>
<scan><cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="{rt}" unitAccession="UO:0000010" unitName="second" unitCvRef="UO"/></scan></scanList>
{pre}
<binaryDataArrayList count="3">
<binaryDataArray encodedLength="{len(mz)}"><cvParam cvRef="MS" accession="MS:1000514" name="m/z array" unitAccession="MS:1000040" unitName="m/z" unitCvRef="MS"/><cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/><cvParam cvRef="MS" accession="MS:1000576" name="no compression"/><binary>{mz}</binary></binaryDataArray>
<binaryDataArray encodedLength="{len(inten)}"><cvParam cvRef="MS" accession="MS:1000515" name="intensity array" unitAccession="MS:1000131" unitName="number of counts" unitCvRef="MS"/><cvParam cvRef="MS" accession="MS:1000521" name="32-bit float"/><cvParam cvRef="MS" accession="MS:1000576" name="no compression"/><binary>{inten}</binary></binaryDataArray>
<binaryDataArray arrayLength="{len(im)}" encodedLength="{len(imarr)}"><cvParam cvRef="MS" accession="MS:1002816" name="mean inverse reduced ion mobility array" unitAccession="MS:1002814" unitName="volt-second per square centimeter" unitCvRef="MS"/><cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/><cvParam cvRef="MS" accession="MS:1000576" name="no compression"/><binary>{imarr}</binary></binaryDataArray>
</binaryDataArrayList></spectrum>"""


def synth(path, n_cycles=14, cycle_s=1.4, gap_cycles=(), groups=None, z1_shift=0, drop_ms2=None):
    """Two precursors that co-elute in one isolation window: a z=2 envelope and a z=1 envelope.

    Both are given a 3-peak isotope envelope so `require_isotope_support` keeps them, matching
    fragments that co-elute with the precursor, and a distinct ion mobility.

    `gap_cycles`: cycles in which the z=2 precursor AND its first fragment are ABSENT. This is
    the input that separates a correct trace-extension rule from a wrong one: OpenMS tolerates up
    to five consecutive missing frames before it ends a trace, so one gap must still give ONE
    trace, and seven consecutive gaps must give TWO. Every version of the integer detector that
    lost 92% of peptides passed the other checks in this file; none would have passed this.

    `groups`: two WindowGroup ids; the MS2 frames then alternate between them by cycle,
    which is how one diaPASEF scheme (PXD017703 "py3") acquires the SAME m/z window twice per
    cycle with shifted ion-mobility slices. They must become two windows, not one.

    `z1_shift`: cycles by which the z=1 precursor's elution apex is moved (negative = earlier),
    so the two precursors can be owned by different tiles. `drop_ms2`: (lo, hi) in seconds; MS2
    frames with lo <= rt < hi are omitted (a window with no frames in one tile).
    """
    win = (600.0, 590.0, 620.0)                    # target, lo, hi
    z2_mono, z2_im = 601.3, 0.90                   # a doubly-charged precursor
    z1_mono, z1_im = 610.6, 1.20                   # a singly-charged one
    z2_frags = [(233.11, 0.7), (348.19, 1.0), (461.27, 0.55)]
    z1_frags = [(288.14, 0.8), (401.22, 0.9)]
    specs, idx = [], 0
    for c in range(n_cycles):
        rt = 1.0 + c * cycle_s
        shape = 1.0 - abs(c - n_cycles / 2.0) / (n_cycles / 2.0 + 1.0)   # a triangular elution
        amp = max(shape, 0.05)
        shape1 = 1.0 - abs(c - (n_cycles / 2.0 + z1_shift)) / (n_cycles / 2.0 + 1.0)
        amp1 = max(shape1, 0.05)
        ms1, ms1_im = [], []
        gap = c in gap_cycles
        for k, rel in enumerate((1.0, 0.55, 0.20)):                      # averagine-ish envelope
            if not gap:
                ms1.append((z2_mono + k * ISO / 2.0, 6.0e5 * amp * rel)); ms1_im.append(z2_im)
            ms1.append((z1_mono + k * ISO / 1.0, 4.0e5 * amp1 * rel)); ms1_im.append(z1_im)
        order = sorted(range(len(ms1)), key=lambda i: ms1[i][0])
        specs.append(spectrum(idx, 1, rt, [ms1[i] for i in order], [ms1_im[i] for i in order])); idx += 1
        if drop_ms2 and drop_ms2[0] <= rt < drop_ms2[1]: continue
        ms2, ms2_im = [], []
        for fi, (mz, rel) in enumerate(z2_frags):
            if gap and fi == 0: continue                                   # first fragment gapped too
            ms2.append((mz, 2.0e5 * amp * rel)); ms2_im.append(z2_im)
        for mz, rel in z1_frags: ms2.append((mz, 1.5e5 * amp1 * rel)); ms2_im.append(z1_im)
        order = sorted(range(len(ms2)), key=lambda i: ms2[i][0])
        specs.append(spectrum(idx, 2, rt, [ms2[i] for i in order], [ms2_im[i] for i in order],
                              prec=win, group=groups[c % 2] if groups else 0)); idx += 1
    body = "\n".join(specs)
    open(path, "w").write(f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<indexedmzML xmlns="http://psi.hupo.org/ms/mzml"><mzML version="1.1.0" id="spextractor_test">
<cvList count="1"><cv id="MS" fullName="Proteomics Standards Initiative Mass Spectrometry Ontology" URI="https://raw.githubusercontent.com/HUPO-PSI/psi-ms-CV/master/psi-ms.obo"/></cvList>
<fileDescription><fileContent><cvParam cvRef="MS" accession="MS:1000580" name="MSn spectrum"/></fileContent></fileDescription>
<softwareList count="1"><software id="so_test" version="0"><cvParam cvRef="MS" accession="MS:1000799" name="custom unreleased software tool" value="spextractor-test"/></software></softwareList>
<instrumentConfigurationList count="1"><instrumentConfiguration id="ic_test"><cvParam cvRef="MS" accession="MS:1000031" name="instrument model"/></instrumentConfiguration></instrumentConfigurationList>
<dataProcessingList count="1"><dataProcessing id="dp_test"><processingMethod order="0" softwareRef="so_test"><cvParam cvRef="MS" accession="MS:1000544" name="Conversion to mzML"/></processingMethod></dataProcessing></dataProcessingList>
<run id="run_test" defaultInstrumentConfigurationRef="ic_test">
<spectrumList count="{len(specs)}" defaultDataProcessingRef="dp_test">
{body}
</spectrumList></run></mzML></indexedmzML>
""")
    return z2_mono, z1_mono


def synth_tdf(path, n_frames):
    """A minimal analysis.tdf: the real dataset D MzCalibration row plus a Frames table.

    The calibration constants are the measured dataset D ones from tests/calibration_golden.json, not
    invented numbers -- an invented row would either fail isSupported() or silently define a
    different mass scale. T1 is given a small per-frame spread so the per-frame factor is actually
    exercised rather than collapsing to the reference.
    """
    import sqlite3, json, os
    g = json.load(open(os.path.join(os.path.dirname(__file__), "..", "tests",
                                    "calibration_golden.json")))[0]
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE MzCalibration (Id INTEGER, ModelType INTEGER, DigitizerTimebase REAL,"
               " DigitizerDelay REAL, C0 REAL, C1 REAL, C2 REAL, T1 REAL, dC1 REAL, dC2 REAL,"
               " C3 REAL, C4 REAL)")
    db.execute("INSERT INTO MzCalibration VALUES (1,?,?,?,?,?,?,?,?,0,0,0)",
               (g["model_type"], g["timebase"], g["delay"], g["C0"], g["C1"], g["C2"],
                g["T1_ref"], g["dC1"]))
    # Real tdfs reference the calibration row per frame (Frames.MzCalibration); mirror that, since
    # the loader selects the row the frames reference rather than "the only row".
    db.execute("CREATE TABLE Frames (Id INTEGER, T1 REAL, MzCalibration INTEGER)")
    db.executemany("INSERT INTO Frames VALUES (?,?,1)",
                   [(i + 1, g["T1_ref"] + 0.03 * (i % 3)) for i in range(n_frames)])
    db.commit(); db.close()
    return path


def run(binary, inp, out, extra=(), threads=1, expect_fail=False, env=None):
    cmd = [binary, "-in", inp, "-out", out, "-threads", str(threads),
           "-assembly:min_fragments", "2", "-assembly:require_isotope_support", "true",
           "-trace:ms2_min_length_sec", "0", "-trace:ms1_split_valleys", "0",
           "-trace:ms2_split_valleys", "0"] + list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if expect_fail:
        assert r.returncode != 0, "expected a non-zero exit, got success:\n" + r.stdout[-800:]
        return r
    assert r.returncode == 0, "run failed:\n" + (r.stdout + r.stderr)[-2000:]
    return r


def precursors(mzml):
    """(mz, charge) of every emitted spectrum."""
    out, mz = [], None
    for line in open(mzml, errors="replace"):
        if "selected ion m/z" in line: mz = float(re.search(r'value="([^"]+)"', line).group(1))
        elif "charge state" in line and mz is not None:
            out.append((mz, int(re.search(r'value="([^"]+)"', line).group(1)))); mz = None
    return out


def peaks_of(mzml, prec_mz, tol=0.02):
    """m/z list of the first spectrum whose selected ion is within tol of prec_mz."""
    want, arr, prec = False, None, 8
    for line in open(mzml, errors="replace"):
        if "<spectrum " in line: want = False
        elif "selected ion m/z" in line:
            v = float(re.search(r'value="([^"]+)"', line).group(1)); want = abs(v - prec_mz) < tol
        elif want and 'name="m/z array"' in line: arr = "mz"
        elif want and 'name="intensity array"' in line: arr = "it"
        elif want and 'name="64-bit float"' in line: prec = 8
        elif want and 'name="32-bit float"' in line: prec = 4
        elif want and arr == "mz" and "<binary>" in line:
            b = line[line.find("<binary>") + 8: line.find("</binary>")]
            raw = base64.b64decode(b)
            return list(struct.unpack(f"<{len(raw)//prec}{'d' if prec == 8 else 'f'}", raw))
    return []


def ms1_traces_near(tsv, mz, tol=0.02):
    """(n_xic, ...) of every MS1 trace in a diag:dump_ms1_tsv dump near an m/z."""
    out = []
    with open(tsv) as f:
        hdr = next(f).rstrip("\n").split("\t")
        for line in f:
            q = dict(zip(hdr, line.rstrip("\n").split("\t")))
            if abs(float(q["mz"]) - mz) < tol: out.append(int(q["n_xic"]))
    return out


def digest(mzml):
    """Hash the spectrum data only -- the header carries a wall-clock stamp and parameters."""
    h, on, done = hashlib.sha256(), False, False
    for line in open(mzml, "rb"):
        if b"<spectrumList" in line:
            on = True
            line = re.sub(rb'count="0+(\d)', rb'count="\1', line, count=1)   # a tiled run's zero-padded count
        if on: h.update(line)
        if b"</spectrumList>" in line: done = True; break
    assert on and done, f"{mzml}: no complete <spectrumList> -- the empty hash would compare equal to another empty hash"
    return h.hexdigest()


def main():
    if len(sys.argv) < 2: sys.exit(__doc__)
    binary = sys.argv[1]
    work = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="spextractor_test_")
    os.makedirs(work, exist_ok=True)
    inp = os.path.join(work, "synth.mzML")
    z2_mono, z1_mono = synth(inp)
    print(f"synthetic input: {inp}  (z=2 mono {z2_mono}, z=1 mono {z1_mono})")
    fails = []

    def check(name, fn):
        try:
            fn(); print(f"  PASS  {name}")
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}"); fails.append(name)

    # 1 + 2: the default drops the z=1 envelope and keeps one precursor per envelope
    out_def = os.path.join(work, "default.mzML")
    run(binary, inp, out_def)
    pd = precursors(out_def)

    def c1():
        z2 = [p for p in pd if p[1] == 2]
        assert z2, f"no z=2 precursor emitted; got {pd}"
        assert all(abs(m - z2_mono) < 0.02 for m, _ in z2), \
            f"a z=2 precursor is not at the monoisotope {z2_mono}: {z2} -- an M+1/M+2 peak reseeded"
    check("isotope ownership: one z=2 precursor, at the mono", c1)

    # [2026-09-08] The default is min_charge 1: singly charged calls are emitted, because on a 2-hour
    # tryptic acquisition they are 14-20% of the Sage peptides and physically 1+ by ion mobility.
    # The synthetic fixture is far too small for the mobility veto to fit a trend line, so the veto
    # is inert here and the z=1 envelope must come through untouched.
    def c2():
        assert [p for p in pd if p[1] == 1], \
            f"charge:min_charge=1 is the default but no z=1 precursor was emitted: {pd}"
    check("min_charge default 1 emits the z=1 envelope", c2)

    out_z2 = os.path.join(work, "z2only.mzML")
    run(binary, inp, out_z2, extra=["-charge:min_charge", "2"])
    p2 = precursors(out_z2)

    def c3():
        assert not [p for p in p2 if p[1] == 1], f"charge:min_charge=2 must drop the z=1 envelope: {p2}"
        assert len([p for p in p2 if p[1] == 2]) == len([p for p in pd if p[1] == 2]), \
            "raising min_charge changed the z=2 result"
    check("min_charge 2 drops it and leaves z=2 alone", c3)

    # 3: a negative count must be rejected, not wrapped through Size
    def c4():
        run(binary, inp, os.path.join(work, "bad.mzML"),
            extra=["-assembly:min_fragments", "-1"], expect_fail=True)
    check("a negative min_fragments is rejected", c4)

    def c5():
        run(binary, inp, os.path.join(work, "bad2.mzML"),
            extra=["-gate:delta_rt", "-5"], expect_fail=True)
    check("a negative gate:delta_rt is rejected", c5)

    # 4: determinism across thread counts for a fixed binary
    out_t4 = os.path.join(work, "t4.mzML")
    run(binary, inp, out_t4, threads=4)

    def c6():
        a, b = digest(out_def), digest(out_t4)
        assert a == b, f"spectrum data differs between 1 and 4 threads:\n  {a}\n  {b}"
    check("byte-identical at 1 vs 4 threads", c6)

    # 5: trace extension across gaps -- the check every broken integer detector would have failed
    # 20 cycles, so that after a seven-cycle gap BOTH halves are long enough to pass the MS1
    # minimum trace length (a 3-frame remnant is correctly dropped by OpenMS, which is not the
    # behaviour under test here).
    for label, gaps, want_traces in (("one missing cycle -> ONE trace", (10,), 1),
                                     ("seven missing cycles -> TWO traces", tuple(range(7, 14)), 2)):
        inp_g = os.path.join(work, f"gap{len(gaps)}.mzML")
        synth(inp_g, n_cycles=20, gap_cycles=gaps)
        out_g = os.path.join(work, f"gap{len(gaps)}.out.mzML")
        dump = os.path.join(work, f"gap{len(gaps)}")
        run(binary, inp_g, out_g, extra=["-diag:dump_ms1_tsv", dump])

        def cg(label=label, want=want_traces, dump=dump, out_g=out_g, gaps=gaps):
            tr = ms1_traces_near(dump + ".traces.tsv", z2_mono)
            assert len(tr) == want, f"expected {want} MS1 trace(s) at {z2_mono} with gaps {gaps}, got {len(tr)} (n_xic {tr})"
            if want == 1:
                assert tr[0] >= 20 - len(gaps) - 1, f"the surviving trace is too short: n_xic {tr[0]}"
                # the gapped FRAGMENT must still reach the z=2 spectrum: a rule that ends a trace at
                # its first gap drops it, which is how 92% of the peptides went missing
                pk = peaks_of(out_g, z2_mono)
                assert any(abs(m - 233.11) < 0.02 for m in pk), f"gapped fragment 233.11 missing from the z=2 spectrum: {pk}"
        check(f"trace extension: {label}", cg)

    # 9 + 10: the SHIPPED detector, and the calibration failing closed.
    # Until 2026-09-04 every check above ran on spx:detector=openms -- the fallback -- because the
    # synthetic nativeIDs carried no "frame=" key and there was no tdf, so the integer detector
    # (the default since that morning) was never once exercised by the suite.
    def detector_of(path):
        import re
        m = re.search(r'spx:detector"[^>]*value="([a-z]+)"', open(path, encoding="utf-8",
                                                                  errors="replace").read())
        return m.group(1) if m else None

    def c9():
        tdf = synth_tdf(os.path.join(work, "analysis.tdf"), n_frames=64)
        out_i = os.path.join(work, "integer.mzML")
        env = dict(os.environ, SPEXTRACTOR_MZPEAK_TDF=tdf)
        run(binary, inp, out_i, env=env)
        got = detector_of(out_i)
        assert got == "integer", (
            f"the SHIPPED default detector did not run: spx:detector={got}. With a parseable "
            f"frame= nativeID and a valid tdf there is nothing left to fall back for.")
    check("the shipped detector (integer) actually runs", c9)

    def c10():
        # No tdf: the integer detector cannot calibrate, and must SAY so rather than invent one.
        out_f = os.path.join(work, "fallback.mzML")
        r = run(binary, inp, out_f, extra=("-trace:detector", "integer"))
        assert detector_of(out_f) == "openms", "no calibration available, yet integer still ran"
        assert "alling back" in (r.stdout + r.stderr), \
            "fell back to the OpenMS detector without warning -- a silent detector switch"
    check("no calibration -> falls back to openms, loudly", c10)

    # 11: one isolation m/z acquired in two window groups (ion-mobility slices) is two windows.
    def c11():
        import re
        n_win = lambda r: int(re.search(r"Split into MS1 \+ (\d+) windows", r.stdout).group(1))
        inp_s = os.path.join(work, "shared.mzML")
        synth(inp_s, groups=(1, 9))
        r1 = run(binary, inp, os.path.join(work, "one_slice.mzML"))
        r2 = run(binary, inp_s, os.path.join(work, "two_slices.mzML"))
        assert n_win(r1) == 1, f"the plain input should be ONE window, got {n_win(r1)}"
        assert n_win(r2) == 2, (
            f"two ion-mobility slices of one m/z window were routed to {n_win(r2)} window(s); keyed by "
            f"m/z alone they collapse into one whose frames are not in retention-time order")
    check("one m/z window in two IM slices -> two windows", c11)

    # 12: the MS1 arena compaction walks kept spans in OFFSET order. The vector is sorted by m/z after
    #     its spans were appended in detection order, and the previous container-order walk overwrote
    #     spans it had not copied yet (~1% of precursor XICs, deterministic). The selftest's fixture
    #     presents traces in an order that defeats that walk.
    def c12():
        r = run(binary, inp, os.path.join(work, "selftest_arena.mzML"), extra=("-diag:selftest_arena",))
        assert "[arena] selftest passed" in (r.stdout + r.stderr), \
            "arena selftest did not report success:\n" + (r.stdout + r.stderr)[-1500:]
    check("MS1 arena compaction survives container order != offset order", c12)

    # 13: the concurrency cap is enforced. It used to be computed, logged and never checked: the
    #     only bound was a byte budget that over-booked every window, so nothing ever throttled.
    def c13():
        import re
        hw = lambda r: int(re.search(r"admission high-water (\d+) of (\d+)", r.stdout).group(1))
        cap = lambda r: int(re.search(r"admission high-water (\d+) of (\d+)", r.stdout).group(2))
        r1 = run(binary, inp, os.path.join(work, "cap1.mzML"), extra=("-perf:max_concurrent_windows", "1"), threads=4)
        assert cap(r1) == 1 and hw(r1) <= 1, f"cap 1 admitted {hw(r1)} windows at once"
        rN = run(binary, inp, os.path.join(work, "capN.mzML"), threads=4)
        assert digest(os.path.join(work, "cap1.mzML")) == digest(os.path.join(work, "capN.mzML")), \
            "the concurrency cap changed the output; results must be written to index-addressed slots"
    check("the concurrency cap bounds admitted windows and does not change output", c13)

    # 14: the writer's invariants. The parallel writer shipped an EMPTY <indexList> for a release
    #     (count="0", one dummy entry) and nothing here looked; the streaming writer (TileWriter) now
    #     owns the count, the ids and the index, so all three are checked on the default output:
    #     declared count == spectra, id="spectrum=K" and index="K" are the rank from 0, and every
    #     index offset lands on its own <spectrum.
    def c14():
        import re
        data = open(out_def, "rb").read()
        n_decl = int(re.search(rb'<spectrumList count="(\d+)"', data).group(1))
        specs = [(m.start(), m.group(1), m.group(2)) for m in re.finditer(rb'<spectrum id="([^"]*)" index="(\d+)"', data)]
        assert n_decl == len(specs) > 0, f"spectrumList count={n_decl} but {len(specs)} <spectrum> elements"
        for k, (_, sid, idx) in enumerate(specs):
            assert int(idx) == k and sid == b"spectrum=%d" % k, f"spectrum {k}: id={sid!r} index={idx!r}"
        offs = re.findall(rb'<offset idRef="([^"]*)">(\d+)</offset>', data)
        assert len(offs) == len(specs), f"indexList has {len(offs)} offsets for {len(specs)} spectra"
        for k, (ref, off) in enumerate(offs):
            assert ref == b"spectrum=%d" % k and int(off) == specs[k][0], \
                f"index entry {k}: {ref!r} at {off!r}, spectrum starts at {specs[k][0]}"
        # OpenMS records the offset one byte early (at the newline before the tag); accept that.
        ilo = int(re.search(rb'<indexListOffset>(\d+)</indexListOffset>', data).group(1))
        assert data[ilo:ilo + 16].lstrip().startswith(b"<indexList"), f"indexListOffset {ilo} does not point at <indexList"
    check("count, ids, index and indexList agree", c14)

    # 15: the cell grid (tile:rt_sec) is thread-invariant: each cell is traced on its own slice with
    #     its own seeds/visited, band stores are absorbed in a fixed order, and the band count is
    #     explicit -- so 1 and 4 threads must give byte-identical spectra at a pitch that cuts the
    #     fixture into two cells (14 cycles of 1.4 s; pitch 10 s = 7 frames -> 2 cells).
    def c15():
        import re
        # the cells exist only on the integer detector: without the tdf the tool falls back to
        # openms and clears the grid AFTER logging it (the first version of this check passed vacuously)
        tdf = synth_tdf(os.path.join(work, "analysis.tdf"), n_frames=64)
        env = dict(os.environ, SPEXTRACTOR_MZPEAK_TDF=tdf)
        r1 = run(binary, inp, os.path.join(work, "cell1.mzML"), extra=("-tile:rt_sec", "10"), threads=1, env=env)
        r4 = run(binary, inp, os.path.join(work, "cell4.mzML"), extra=("-tile:rt_sec", "10"), threads=4, env=env)
        m = re.search(r"\[cell\] pitch [0-9.]+ s = (\d+) MS1 frames .*?: (\d+) cells", r1.stdout + r1.stderr)
        assert m and int(m.group(2)) >= 2, "the fixture was not cut into >= 2 cells:\n" + (r1.stdout + r1.stderr)[-800:]
        assert detector_of(os.path.join(work, "cell1.mzML")) == "integer", "cells need the integer detector; it did not run"
        hdr = open(os.path.join(work, "cell1.mzML"), encoding="utf-8", errors="replace").read(200000)
        mb = re.search(r'spx:tile_boundaries"[^>]*value="([^"]*)"', hdr)
        assert mb and mb.group(1) not in ("", "none"), "the header records no cut lines"
        assert digest(os.path.join(work, "cell1.mzML")) == digest(os.path.join(work, "cell4.mzML")), \
            "tile:rt_sec output differs between 1 and 4 threads"
    check("the cell grid is thread-invariant", c15)

    # 16-18: the TILE loop. A longer fixture (26 cycles of 1.4 s) with the z=1 precursor's apex
    #     moved 6 cycles earlier: pitch 10 s (7 frames) cuts it at 10.8 / 20.6 / 30.4 s, one cell per
    #     tile gives four tiles; z=1 (rt 10.8) is owned by tile 2 and z=2 (rt 19.2) by tile 3, so two
    #     tiles emit and two write nothing. z=2's fragments crest just BEFORE the 20.6-s cut, so its
    #     spectrum in tile 3 depends on fragments CARRIED from tile 2.
    def tiled_fixture(name, **kw):
        path = os.path.join(work, name)
        synth(path, n_cycles=26, z1_shift=-6, **kw)
        return path
    def invariants(path, label):
        import re
        data = open(path, "rb").read()
        n_decl = int(re.search(rb'<spectrumList count="(\d+)"', data).group(1))
        specs = [(m.start(), m.group(1), m.group(2)) for m in re.finditer(rb'<spectrum id="([^"]*)" index="(\d+)"', data)]
        assert n_decl == len(specs) > 0, f"{label}: spectrumList count={n_decl} but {len(specs)} <spectrum> elements"
        for k, (_, sid, idx) in enumerate(specs):
            assert int(idx) == k and sid == b"spectrum=%d" % k, f"{label} spectrum {k}: id={sid!r} index={idx!r}"
        offs = re.findall(rb'<offset idRef="([^"]*)">(\d+)</offset>', data)
        assert len(offs) == len(specs), f"{label}: indexList has {len(offs)} offsets for {len(specs)} spectra"
        for k, (ref, off) in enumerate(offs):
            assert ref == b"spectrum=%d" % k and int(off) == specs[k][0], f"{label} index entry {k}: {ref!r} at {off!r}, spectrum at {specs[k][0]}"
        ilo = int(re.search(rb'<indexListOffset>(\d+)</indexListOffset>', data).group(1))
        assert data[ilo:ilo + 16].lstrip().startswith(b"<indexList"), f"{label}: indexListOffset {ilo} does not point at <indexList"
        return len(specs), re.search(rb'<spectrumList count="([^"]*)"', data).group(1)

    # 16: tile-count x thread invariance, two non-empty blocks, the count/index invariants on the
    #     tiled file, the exact (unpadded) count on the one-tile file
    def c16():
        import re
        tdf = synth_tdf(os.path.join(work, "analysis.tdf"), n_frames=64)
        env = dict(os.environ, SPEXTRACTOR_MZPEAK_TDF=tdf)
        inp_t = tiled_fixture("tiles.mzML")
        one = os.path.join(work, "tiles_one.mzML")
        run(binary, inp_t, one, extra=("-tile:rt_sec", "10"), threads=4, env=env)
        n_one, cnt_one = invariants(one, "one-tile file")
        assert cnt_one == str(n_one).encode(), f"one-tile count is not exact: {cnt_one!r}"
        outs = []
        for thr in (1, 4):
            o = os.path.join(work, f"tiles{thr}.mzML")
            r = run(binary, inp_t, o, extra=("-tile:rt_sec", "10", "-tile:cells_per_tile", "1"), threads=thr, env=env)
            log = r.stdout + r.stderr
            m = re.search(r"\[tile\] (\d+) tile\(s\) of up to 1 cell", log)
            assert m and int(m.group(1)) >= 3, "the fixture did not run as >= 3 tiles:\n" + log[-800:]
            written = [int(x) for x in re.findall(r"\[tile\] \d+/\d+: (\d+) spectra written", log)]
            assert sum(1 for w in written if w > 0) >= 2, f"fewer than two tiles wrote spectra: {written}"
            assert "coverage:" in log, "no coverage line"
            outs.append(o)
        hdr = open(outs[0], encoding="utf-8", errors="replace").read(200000)
        mt = re.search(r'spx:tiles"[^>]*value="(\d+)"', hdr)
        assert mt and int(mt.group(1)) >= 3, "the header does not record the tile count"
        d1 = digest(one)
        for o in outs:
            assert digest(o) == d1, f"tiled output {os.path.basename(o)} differs from the one-tile run"
        n_t, cnt_t = invariants(outs[1], "tiled file")
        assert n_t == n_one
    check("the tile loop is tile-count- and thread-invariant", c16)

    # 17: the carry is load-bearing: the same tiled run WITHOUT the carry (a test-only switch)
    #     must differ from the one-tile run, and the normal run must report carried fragments
    def c17():
        import re
        tdf = synth_tdf(os.path.join(work, "analysis.tdf"), n_frames=64)
        env = dict(os.environ, SPEXTRACTOR_MZPEAK_TDF=tdf)
        inp_t = os.path.join(work, "tiles.mzML"); one = os.path.join(work, "tiles_one.mzML")
        assert os.path.exists(inp_t) and os.path.exists(one), "check 16 must run first"
        r = run(binary, inp_t, os.path.join(work, "tiles_c.mzML"), extra=("-tile:rt_sec", "10", "-tile:cells_per_tile", "1"), threads=2, env=env)
        carried = [int(x) for x in re.findall(r"carried in (\d+)", r.stdout + r.stderr)]
        assert carried and max(carried) > 0, "no tile reported carried-in fragments:\n" + (r.stdout + r.stderr)[-800:]
        env_nc = dict(env, SPEXTRACTOR_TILE_NO_CARRY="1")
        nc = os.path.join(work, "tiles_nocarry.mzML")
        run(binary, inp_t, nc, extra=("-tile:rt_sec", "10", "-tile:cells_per_tile", "1"), threads=2, env=env_nc)
        assert digest(nc) != digest(one), "switching the carry off changed nothing: the fixture does not exercise it"
    check("the boundary carry is load-bearing", c17)

    # 18: a window with NO frames in a middle tile (its MS2 frames in [20.6, 30.4) dropped): the
    #     empty-slab branch runs, the tile scores with carried fragments only, and the tiled run
    #     still equals the one-tile run of the same file
    def c18():
        import re
        tdf = synth_tdf(os.path.join(work, "analysis.tdf"), n_frames=64)
        env = dict(os.environ, SPEXTRACTOR_MZPEAK_TDF=tdf)
        inp_e = tiled_fixture("tiles_empty.mzML", drop_ms2=(20.6, 30.4))
        one = os.path.join(work, "tiles_empty_one.mzML")
        run(binary, inp_e, one, extra=("-tile:rt_sec", "10"), threads=2, env=env)
        t = os.path.join(work, "tiles_empty_t.mzML")
        r = run(binary, inp_e, t, extra=("-tile:rt_sec", "10", "-tile:cells_per_tile", "1"), threads=2, env=env)
        assert "no frames in the tile" in (r.stdout + r.stderr), "the empty-slab branch did not run:\n" + (r.stdout + r.stderr)[-800:]
        assert digest(t) == digest(one), "the tiled run of a window with an empty tile differs from the one-tile run"
        invariants(t, "empty-tile file")
    check("a window with no frames in a tile", c18)

    total = 6 + 2 + 2 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 1
    print(f"\n{total - len(fails)}/{total} checks passed" + (f"; FAILED: {', '.join(fails)}" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
