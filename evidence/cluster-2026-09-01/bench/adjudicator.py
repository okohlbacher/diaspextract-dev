#!/usr/bin/env python3
"""THE ADJUDICATOR: are diaTracer-only peptides ABSENT from our spectra, or present-but-subthreshold?

Re-search our existing pseudo.mzML at loose FDR (dump all target PSMs), take diaTracer's
1%-FDR peptides, and ask what fraction appear in OUR data at ANY score. Split by charge —
the workflow's key prediction is that the MISSING population is specifically higher-charge and
ABSENT (precursor never hypothesized), not merely low-scoring.

Reports the delta-to-threshold distribution so 'present at any score' is not confused with
'recoverable' (a PSM far below threshold is present but unrecoverable).
"""
import subprocess
import json
import csv
import os
import sys
import collections

SAGE = "/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage"
BASE = "/scratch/kohlbach/bench/sage.json"
OURS_MZML = "/scratch/kohlbach/bench/out/snr1_n10/pseudo.mzML"
DIA_MZML = "/scratch/kohlbach/bench/out/diatracer_s08/pseudo.mzML"  # may not exist; fall back below
OUT = "/scratch/kohlbach/bench/adjud"
os.makedirs(OUT, exist_ok=True)


def run_loose(mzml, tag):
    cfg = json.load(open(BASE))
    cfg["report_psms"] = 1
    od = os.path.join(OUT, tag)
    os.makedirs(od, exist_ok=True)
    json.dump(cfg, open(od + "/sage.json", "w"))
    subprocess.run([SAGE, od + "/sage.json", "-o", od,
                    "--disable-telemetry-i-dont-want-to-improve-sage", mzml],
                   capture_output=True, text=True)
    return od + "/results.sage.tsv"


def load(tsv, qmax=1.0):
    """return {peptide: (min_q, charge)} over rows with spectrum_q <= qmax"""
    best = {}
    for x in csv.DictReader(open(tsv), delimiter="\t"):
        q = float(x.get("spectrum_q", "1"))
        if q > qmax:
            continue
        pep = x["peptide"]
        z = x.get("charge", "0")
        if pep not in best or q < best[pep][0]:
            best[pep] = (q, z)
    return best


# our diaTracer reference peptides @1% (from the earlier diaTracer search)
DIA_TSV = "/scratch/kohlbach/bench/s08/diatracer/results.sage.tsv"  # confirmed exists
if not os.path.exists(DIA_TSV):
    # find any diatracer sage result
    import glob
    cands = glob.glob("/scratch/kohlbach/bench/**/diatracer*/results.sage.tsv", recursive=True)
    cands += glob.glob("/scratch/kohlbach/bench/**/*dia*/*results.sage.tsv", recursive=True)
    DIA_TSV = cands[0] if cands else None

print("dia tsv:", DIA_TSV)
ours_tsv = run_loose(OURS_MZML, "ours_loose")
ours_all = load(ours_tsv, qmax=1.0)      # every target PSM at any q
ours_1pct = set(p for p, (q, z) in ours_all.items() if q <= 0.01)
print("ours: %d peptides@1%%, %d present at ANY q" % (len(ours_1pct), len(ours_all)))

if DIA_TSV and os.path.exists(DIA_TSV):
    dia_1pct = load(DIA_TSV, qmax=0.01)
    dia_only = set(dia_1pct) - ours_1pct
    print("diaTracer peptides@1%%: %d ; diaTracer-only (we miss @1%%): %d" % (len(dia_1pct), len(dia_only)))

    present = {p: ours_all[p] for p in dia_only if p in ours_all}
    absent = dia_only - set(present)
    print("\n=== ADJUDICATION of the %d diaTracer-only peptides ===" % len(dia_only))
    print("  present in ours at ANY score : %6d (%.1f%%)" % (len(present), 100.0 * len(present) / max(len(dia_only), 1)))
    print("  ABSENT from ours entirely    : %6d (%.1f%%)" % (len(absent), 100.0 * len(absent) / max(len(dia_only), 1)))

    # delta-to-threshold: how close are the present ones to being recovered?
    bins = collections.Counter()
    for p, (q, z) in present.items():
        if q <= 0.01:
            bins["already@1%"] += 1
        elif q <= 0.05:
            bins["0.01-0.05 (near)"] += 1
        elif q <= 0.20:
            bins["0.05-0.20"] += 1
        else:
            bins[">0.20 (deep)"] += 1
    print("  present-but-subthreshold, by q distance to 1%%:")
    for k in ("already@1%", "0.01-0.05 (near)", "0.05-0.20", ">0.20 (deep)"):
        print("     %-18s %6d" % (k, bins.get(k, 0)))

    # charge split of dia-only (diaTracer charge from its own @1%)
    zc = collections.Counter(z for (q, z) in dia_1pct.values() if False)  # placeholder
    z_present = collections.Counter(z for p, (q, z) in present.items())
    z_dia = collections.Counter(dia_1pct[p][1] for p in dia_only)
    print("\n  diaTracer-only charge distribution (diaTracer's charge):", dict(sorted(z_dia.items())))
    print("  of those, present-in-ours charge (our charge):          ", dict(sorted(z_present.items())))
    print("\n  VERDICT LOGIC:")
    print("   - present near-threshold high  -> scoring/emit track (rewrite deprioritized)")
    print("   - absent high AND skewed to 3+/4+ -> precursor-inference rewrite mandatory")
else:
    print("!! diaTracer sage TSV not found; cannot adjudicate. Present-at-any-q =", len(ours_all))
