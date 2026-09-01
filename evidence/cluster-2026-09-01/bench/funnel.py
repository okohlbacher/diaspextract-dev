#!/usr/bin/env python3
"""Attribute precursor loss to a stage.

Measured recall is 74.3% vs diaTracer's 84.4%, but that single number cannot say
WHERE a precursor dies. Three stages, each independently fixable by different code:

  A  MS1 TRACE      is there any MS1 trace at the precursor's (m/z, RT, IM)?
                    failure => detectTraces_ sensitivity (noise/snr/min_length)
  B  HYPOTHESIS     did inferPrecursors_ turn that trace into a precursor with the
                    right mono m/z?  and with the right CHARGE?
                    failure => isotope/charge inference
  C  SPECTRUM       did the window loop emit a spectrum for it?  (measured separately)
                    failure => assembly/scoring

A precursor is "seen" at stage A if a trace sits at the mono m/z OR at the +1/+2
isotope m/z — a trace on the wrong isotope still proves the ion was detected, and
distinguishes "invisible" from "misassigned".
"""
import sys, collections, numpy as np, pyarrow.parquet as pq

REPORT, PREFIX = sys.argv[1], sys.argv[2]
PPM   = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
D_RT  = float(sys.argv[4]) if len(sys.argv) > 4 else 0.10
D_IM  = float(sys.argv[5]) if len(sys.argv) > 5 else 0.02
ISO_N = int(sys.argv[6])   if len(sys.argv) > 6 else 1   # isotopes accepted for "detected"
PROTON, NEUTRON = 1.007276, 1.003355

r = pq.read_table(REPORT, columns=["Precursor.Id","Precursor.Mz","Precursor.Charge",
      "RT","RT.Start","RT.Stop","IM","Q.Value"]).to_pandas()
r = r[r["Q.Value"] <= 0.01].reset_index(drop=True)
print(f"[truth] {len(r)} precursors q<=1%  |  tol {PPM}ppm {D_RT}min {D_IM} 1/K0, isotopes={ISO_N}", flush=True)

def load(path, cols):
    import csv
    out = []
    with open(path) as f:
        rd = csv.DictReader(f, delimiter="\t")
        for row in rd: out.append(tuple(float(row[c]) for c in cols))
    return np.array(out, dtype=float)

tr = load(PREFIX + ".traces.tsv",     ["mz","rt","im"])
pc = load(PREFIX + ".precursors.tsv", ["mono_mz","charge","rt","im"])
print(f"[ours]  {len(tr)} MS1 traces, {len(pc)} precursor hypotheses", flush=True)

# RT-bucketed m/z-sorted index; RT in the dumps is SECONDS, DIA-NN reports MINUTES
bkeys = {}
def build(arr, rt_col):
    idx = collections.defaultdict(list)
    for i, row in enumerate(arr):
        idx[int(row[rt_col] / 60.0 / D_RT)].append(i)
    kk = {}
    for k in idx:
        idx[k] = sorted(idx[k], key=lambda i: arr[i][0])
        kk[k] = [arr[i][0] for i in idx[k]]     # m/z keys for bisect
    bkeys[id(arr)] = kk
    return idx
ti, pi = build(tr, 1), build(pc, 2)

import bisect
def near(arr, idx, mz, rt_min, im, ppm=PPM, want_charge=None):
    """any row within ppm of mz, in an RT bucket covering rt_min, and within D_IM."""
    tol = mz * ppm * 1e-6
    for b in (int(rt_min/D_RT)-1, int(rt_min/D_RT), int(rt_min/D_RT)+1):
        bucket = idx.get(b)
        if not bucket: continue
        keys = bkeys[id(arr)].get(b)
        lo = bisect.bisect_left(keys, mz - tol)
        hi = bisect.bisect_right(keys, mz + tol)
        for i in bucket[lo:hi]:
            row = arr[i]
            rt_i = row[1 if arr is tr else 2] / 60.0
            im_i = row[2 if arr is tr else 3]
            if abs(rt_i - rt_min) > D_RT or abs(im_i - im) > D_IM: continue
            if want_charge is not None and int(row[1]) != want_charge: continue
            return True
    return False

# --- pass 0: estimate systematic offsets from loose matches -------------------
def loose_match(arr, idx, mz, rt_min, im, ppm, drt, dim):
    """nearest row within a loose box; returns (dppm, drt, dim) or None."""
    best = None; bd = 1e18
    tol = mz * ppm * 1e-6
    for b in (int(rt_min/D_RT)-1, int(rt_min/D_RT), int(rt_min/D_RT)+1):
        bucket = idx.get(b)
        if not bucket: continue
        keys = bkeys[id(arr)].get(b)
        lo = bisect.bisect_left(keys, mz - tol); hi = bisect.bisect_right(keys, mz + tol)
        for i in bucket[lo:hi]:
            row = arr[i]
            rt_i = row[1 if arr is tr else 2] / 60.0
            im_i = row[2 if arr is tr else 3]
            if abs(rt_i - rt_min) > drt or abs(im_i - im) > dim: continue
            d = abs(row[0]-mz)/mz*1e6
            if d < bd: bd = d; best = ((row[0]-mz)/mz*1e6, rt_i - rt_min, im_i - im)
    return best

dp, dr, di = [], [], []
for _, p in r.iterrows():
    m = loose_match(tr, ti, p["Precursor.Mz"], p["RT"], p["IM"], 25.0, 0.30, 0.05)
    if m: dp.append(m[0]); dr.append(m[1]); di.append(m[2])
OFF_PPM = float(np.median(dp)) if dp else 0.0
OFF_RT  = float(np.median(dr)) if dr else 0.0
OFF_IM  = float(np.median(di)) if di else 0.0
print(f"[calib] n={len(dp)}  systematic offsets: {OFF_PPM:+.2f} ppm, {OFF_RT:+.3f} min, {OFF_IM:+.4f} 1/K0", flush=True)
print(f"[calib] residual spread (IQR): ppm [{np.percentile(dp,25):+.2f},{np.percentile(dp,75):+.2f}] "
      f"rt [{np.percentile(dr,25):+.3f},{np.percentile(dr,75):+.3f}] "
      f"im [{np.percentile(di,25):+.4f},{np.percentile(di,75):+.4f}]", flush=True)

st = collections.Counter(); stD = collections.Counter()
DEC = 11.003
for _, p in r.iterrows():
    mz, z, rt, im = p["Precursor.Mz"], int(p["Precursor.Charge"]), p["RT"], p["IM"]
    mz = mz * (1.0 + OFF_PPM * 1e-6); rt = rt + OFF_RT; im = im + OFF_IM
    # accepting mono OR +1 OR +2 triples the chance of a hit; ISO_N=1 demands the mono.
    iso = [mz + k*NEUTRON/z for k in range(ISO_N)]
    has_trace = any(near(tr, ti, m, rt, im) for m in iso)
    has_mono  = near(pc, pi, mz, rt, im)
    has_zmono = near(pc, pi, mz, rt, im, want_charge=z)
    if   not has_trace: st["A_no_ms1_trace"] += 1
    elif not has_mono:  st["B_trace_but_no_hypothesis"] += 1
    elif not has_zmono: st["B_hypothesis_wrong_charge"] += 1
    else:               st["C_correct_hypothesis"] += 1
    # DECOY FLOOR: the 97.8% ceiling was quoted with no chance control. With 2.5M MS1 traces a
    # 20 ppm x 0.3 min x 0.05 1/K0 box may contain a trace by accident. Ask the same three
    # questions of a precursor that is not there; the gap is the only part that is evidence.
    dmz = mz + DEC
    d_iso = [dmz + k*NEUTRON/z for k in range(ISO_N)]
    d_trace = any(near(tr, ti, m, rt, im) for m in d_iso)
    d_mono  = near(pc, pi, dmz, rt, im)
    d_zmono = near(pc, pi, dmz, rt, im, want_charge=z)
    if   not d_trace: stD["A_no_ms1_trace"] += 1
    elif not d_mono:  stD["B_trace_but_no_hypothesis"] += 1
    elif not d_zmono: stD["B_hypothesis_wrong_charge"] += 1
    else:             stD["C_correct_hypothesis"] += 1

n = sum(st.values())
print(f"\n===== MS1 FUNNEL, {n} DIA-NN precursors =====")
for k in ("A_no_ms1_trace","B_trace_but_no_hypothesis","B_hypothesis_wrong_charge","C_correct_hypothesis"):
    print(f"  {k:28s} {st[k]:7d}  {100*st[k]/n:5.1f}%")
seen = n - st["A_no_ms1_trace"]
nD = sum(stD.values()) or 1
seenD = nD - stD["A_no_ms1_trace"]
print(f"\n--- DECOY FLOOR (truth m/z shifted +{DEC} Da; chance matching only) ---")
for k in ("A_no_ms1_trace","B_trace_but_no_hypothesis","B_hypothesis_wrong_charge","C_correct_hypothesis"):
    print(f"  {k:28s} {stD[k]:7d}  {100*stD[k]/nD:5.1f}%")
print(f"\nMS1 detection ceiling   : {100*seen/n:.1f}% observed, {100*seenD/nD:.1f}% decoy floor  =>  {100*(seen/n - seenD/nD)/(1 - seenD/nD):.1f}% chance-corrected")
print(f"correct-hypothesis rate : {100*st['C_correct_hypothesis']/n:.1f}% observed, {100*stD['C_correct_hypothesis']/nD:.1f}% decoy floor")
print(f"survives charge inference: {100*st['C_correct_hypothesis']/n:.1f}%")
print(f"lost in inference, not detection: {100*(st['B_trace_but_no_hypothesis']+st['B_hypothesis_wrong_charge'])/n:.1f}%")
