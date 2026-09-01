#!/usr/bin/env python3
"""CALIBRATION DIAGNOSTIC: is our m/z (and IM) systematically miscalibrated vs diaTracer?

Uses Sage's per-PSM precursor_ppm / fragment_ppm (observed - theoretical, in ppm) on the
1%-FDR target PSMs. If OUR distribution is shifted off zero or much wider than diaTracer's,
calibration is the problem — and it would push real peptides outside Sage's +/-20 ppm window,
explaining the 73.6% ABSENT diaTracer-only peptides. Also bins precursor_ppm by m/z and by
ion mobility to detect an IM-dependent mass error (the MaxDIA f(1/K0) recalibration finding).
"""
import csv
import sys
import statistics as st
import collections


def load(tsv):
    rows = []
    for x in csv.DictReader(open(tsv), delimiter="\t"):
        try:
            if float(x.get("spectrum_q", "1")) > 0.01:
                continue
            rows.append({
                "pppm": float(x["precursor_ppm"]),
                "fppm": float(x["fragment_ppm"]),
                "mz": float(x["expmass"]) / max(int(x["charge"]), 1) + 1.00728,
                "z": int(x["charge"]),
                "im": float(x.get("ion_mobility", "0") or 0),
            })
        except (ValueError, KeyError):
            pass
    return rows


def summ(vals, name):
    vals = [v for v in vals if v == v]
    vals.sort()
    n = len(vals)
    if n == 0:
        return
    med = vals[n // 2]
    mean = sum(vals) / n
    p05, p95 = vals[int(0.05 * n)], vals[int(0.95 * n)]
    iqr = vals[int(0.75 * n)] - vals[int(0.25 * n)]
    print("  %-14s n=%6d  median=%+6.2f mean=%+6.2f  p05=%+6.2f p95=%+6.2f  IQR=%5.2f" %
          (name, n, med, mean, p05, p95, iqr))


for tag, tsv in (("OURS", sys.argv[1]), ("diaTracer", sys.argv[2])):
    r = load(tsv)
    print("=== %s (%d PSMs @1%%) ===" % (tag, len(r)))
    summ([x["pppm"] for x in r], "precursor_ppm")
    summ([x["fppm"] for x in r], "fragment_ppm")
    # precursor ppm vs m/z (calibration slope)
    print("  precursor_ppm by m/z bin:")
    bym = collections.defaultdict(list)
    for x in r:
        bym[int(x["mz"] // 150) * 150].append(x["pppm"])
    for k in sorted(bym):
        v = sorted(bym[k])
        if len(v) > 20:
            print("     m/z %4d-%4d : median %+6.2f ppm (n=%d)" % (k, k + 150, v[len(v) // 2], len(v)))
    # precursor ppm vs ion mobility (IM-dependent mass error)
    if any(x["im"] for x in r):
        print("  precursor_ppm by ion-mobility bin:")
        byi = collections.defaultdict(list)
        for x in r:
            if x["im"]:
                byi[round(x["im"], 1)].append(x["pppm"])
        for k in sorted(byi):
            v = sorted(byi[k])
            if len(v) > 20:
                print("     1/K0 ~%.1f : median %+6.2f ppm (n=%d)" % (k, v[len(v) // 2], len(v)))
    print()
