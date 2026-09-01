#!/usr/bin/env python3
"""Decompose our MS1 mass error against DIA-NN truth.

Median error is -1.8 to -3.5 ppm (diaTracer: -0.75), but the SPREAD is the problem:
IQR [-5.93,+0.67], strongly left-skewed. A constant recalibration would remove the median
and leave the spread untouched.

Why the spread matters causally, not cosmetically: mass imprecision forces
trace:mass_error_ppm to run loose, a loose m/z tolerance merges co-eluting species into one
mass trace, and merged traces are exactly what ms1split (+36.7%) patches downstream. If the
spread is STRUCTURED (predictable from m/z, intensity, RT or IM) it can be corrected, the
tracing tolerance tightened, and the merge attacked at its cause.

Prints the error against each candidate variable. A term that flattens the residual is a
correction worth implementing; one that does not is noise, and recalibration is cosmetic.
"""
import sys, bisect, collections, csv, numpy as np, pyarrow.parquet as pq

REPORT, PREFIX = sys.argv[1], sys.argv[2]
PPM_WIN, D_RT, D_IM = 25.0, 0.30, 0.05

r = pq.read_table(REPORT, columns=["Precursor.Mz", "RT", "IM", "Q.Value"]).to_pandas()
r = r[r["Q.Value"] <= 0.01].reset_index(drop=True)

tr = []
with open(PREFIX + ".traces.tsv") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        tr.append((float(row["mz"]), float(row["rt"]), float(row["im"]), float(row["intensity"])))
tr = np.array(tr, dtype=float)
print(f"[data] {len(r)} truth precursors, {len(tr)} MS1 traces", flush=True)

RTB = 0.1
idx = collections.defaultdict(list)
for i, row in enumerate(tr):
    idx[int(row[1] / 60.0 / RTB)].append(i)
keys = {}
for k in idx:
    idx[k] = sorted(idx[k], key=lambda i: tr[i][0])
    keys[k] = [tr[i][0] for i in idx[k]]

rec = []
for _, p in r.iterrows():
    mz, rt, im = p["Precursor.Mz"], p["RT"], p["IM"]
    tol = mz * PPM_WIN * 1e-6
    best, bd = None, 1e18
    for b in (int(rt / RTB) - 1, int(rt / RTB), int(rt / RTB) + 1):
        if b not in idx: continue
        lo = bisect.bisect_left(keys[b], mz - tol)
        hi = bisect.bisect_right(keys[b], mz + tol)
        for i in idx[b][lo:hi]:
            t = tr[i]
            if abs(t[1] / 60.0 - rt) > D_RT or abs(t[2] - im) > D_IM: continue
            dd = abs(t[0] - mz)
            if dd < bd: bd, best = dd, t
    if best is not None and best[3] > 0:
        rec.append(((best[0] - mz) / mz * 1e6, mz, np.log10(best[3]), rt, best[2]))

a = np.array(rec)
if not len(a):
    print("no matches"); sys.exit(1)
d = a[:, 0]
skew = float(((d - d.mean()) ** 3).mean() / d.std() ** 3)
print(f"[match] n={len(a)}  median {np.median(d):+.2f} ppm  "
      f"IQR [{np.percentile(d,25):+.2f},{np.percentile(d,75):+.2f}]  "
      f"MAD {np.median(np.abs(d-np.median(d))):.2f}  skew {skew:+.2f}\n")

def profile(name, x, nbin=8):
    qs = np.quantile(x, np.linspace(0, 1, nbin + 1))
    print(f"--- error vs {name} ---")
    print(f"{'bin':>19s} {'n':>7s} {'median ppm':>11s} {'IQR width':>10s}")
    for i in range(nbin):
        m = (x >= qs[i]) & ((x <= qs[i+1]) if i == nbin-1 else (x < qs[i+1]))
        if m.sum() < 50: continue
        dd = d[m]
        print(f"{qs[i]:9.3f}-{qs[i+1]:<9.3f} {m.sum():7d} {np.median(dd):+11.2f} "
              f"{np.percentile(dd,75)-np.percentile(dd,25):10.2f}")
    print()

profile("m/z",             a[:, 1])
profile("log10 intensity", a[:, 2])
profile("RT (min)",        a[:, 3])
profile("ion mobility",    a[:, 4])

# How much spread would each single-variable correction actually remove? A term that does not
# shrink the residual MAD is not worth implementing, however clean its trend looks.
print("--- residual MAD after removing a per-bin median (8 bins) ---")
base = np.median(np.abs(d - np.median(d)))
print(f"{'uncorrected':>18s}  MAD {base:.2f} ppm")
for name, col in (("m/z", 1), ("log10 intensity", 2), ("RT", 3), ("ion mobility", 4)):
    x = a[:, col]
    qs = np.quantile(x, np.linspace(0, 1, 9))
    res = d.copy()
    for i in range(8):
        m = (x >= qs[i]) & ((x <= qs[i+1]) if i == 7 else (x < qs[i+1]))
        if m.sum() > 10: res[m] = d[m] - np.median(d[m])
    mad = np.median(np.abs(res - np.median(res)))
    print(f"{name:>18s}  MAD {mad:.2f} ppm   ({100*(1-mad/base):+.1f}% vs uncorrected)")
