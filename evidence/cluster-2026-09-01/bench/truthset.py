#!/usr/bin/env python3
"""DIA-NN-anchored truth set for pseudo-spectra.

Measures what the Sage-conditioned benchmark structurally cannot:
  RECALL  - of DIA-NN precursors present, how many do we emit a spectrum for?
            (denominator independent of whether Sage identifies our output)
  PURITY  - of an emitted spectrum's intensity, how much belongs to its OWN
            assigned precursor vs a CO-ISOLATED one vs neither?  Model-free:
            fragment m/z come from DIA-NN's library, not from a search score.

CAVEAT baked into the output: unmatched spectra are reported as UNEXPLAINED,
never as noise.  DIA-NN is library-limited (tryptic, Ox-M/acetyl, z2-4) and is
structurally blind to the non-canonical species this tool exists to find.
Calling its complement "noise" would define our target class out of existence.
"""
import sys, collections, numpy as np, pyarrow.parquet as pq
from pyteomics import mzml

REPORT, LIB, SPECTRA, TAG = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
N_CYCLES   = int(sys.argv[5]) if len(sys.argv) > 5 else 200
PPM_PREC, PPM_FRAG = 20.0, 20.0
D_RT, D_IM = 0.30, 0.05          # min, 1/K0
DECOY_SHIFT = 11.003             # Da; random-match background probe

# ---- DIA-NN truth ---------------------------------------------------------
r = pq.read_table(REPORT, columns=["Precursor.Id","Stripped.Sequence","Precursor.Mz",
      "Precursor.Charge","RT","RT.Start","RT.Stop","IM","Q.Value"]).to_pandas()
r = r[r["Q.Value"] <= 0.01].reset_index(drop=True)
lib = pq.read_table(LIB, columns=["Precursor.Id","Product.Mz","Relative.Intensity",
      "Fragment.Type","Decoy"]).to_pandas()
lib = lib[lib["Decoy"] == 0]
frags = collections.defaultdict(list)
for pid, mz, ri in zip(lib["Precursor.Id"], lib["Product.Mz"], lib["Relative.Intensity"]):
    frags[pid].append(mz)
frags = {k: np.sort(np.array(v)) for k, v in frags.items()}
print(f"[truth] {len(r)} precursors q<=1%, {len(frags)} with fragments", flush=True)

# ---- cycle grid + density stratification ----------------------------------
rt_lo, rt_hi = r["RT.Start"].min(), r["RT.Stop"].max()
NB = 400
edges = np.linspace(rt_lo, rt_hi, NB + 1)
dens = np.zeros(NB, int)
for a, b in zip(r["RT.Start"], r["RT.Stop"]):
    dens[max(0,np.searchsorted(edges,a)-1):np.searchsorted(edges,b)] += 1
# even spread over the DENSITY range: decile-stratified, not RT-uniform
order = np.argsort(dens); per = max(1, N_CYCLES // 10)
sel = np.sort(np.concatenate([order[i*NB//10:(i+1)*NB//10][
        np.linspace(0, max(0,(NB//10)-1), per).astype(int)] for i in range(10)]))
print(f"[strat] {len(sel)} bins, density {dens[sel].min()}-{dens[sel].max()} "
      f"(global {dens.min()}-{dens.max()})", flush=True)
keep = [(edges[i], edges[i+1]) for i in sel]
def in_sel(rt): return any(a <= rt <= b for a, b in keep)

# precursor index: RT bin -> precursors whose elution window covers it.
# Without this the co-isolation lookup is O(n_spectra * 43k) and never finishes.
P = r.to_dict("records")
RTBIN = 0.1
pidx = collections.defaultdict(list)
for i, p in enumerate(P):
    for b in range(int((p["RT.Start"]-D_RT)/RTBIN), int((p["RT.Stop"]+D_RT)/RTBIN)+1):
        pidx[b].append(i)
print(f"[index] {len(pidx)} RT bins, mean occupancy "
      f"{np.mean([len(v) for v in pidx.values()]):.0f}", flush=True)

def hits(arr, mz, ppm):
    if len(arr) == 0: return False
    i = np.searchsorted(arr, mz)
    for j in (i-1, i):
        if 0 <= j < len(arr) and abs(arr[j]-mz)/mz*1e6 <= ppm: return True
    return False

stat = collections.Counter(); nco=[]; own_f=[]; oth_f=[]; une_f=[]; dec_f=[]
zc = collections.Counter(); matched_pids=set(); n_spec=0
for s in mzml.read(SPECTRA):
    if s.get("ms level") != 2: continue
    pre = s["precursorList"]["precursor"][0]
    ion = pre["selectedIonList"]["selectedIon"][0]
    pmz = float(ion["selected ion m/z"]); z = int(ion.get("charge state", 0) or 0)
    rt  = float(s["scanList"]["scan"][0]["scan start time"])
    im  = float(s["scanList"]["scan"][0].get("inverse reduced ion mobility", -1))
    if not in_sel(rt): continue
    n_spec += 1
    mzs, ints = s["m/z array"], s["intensity array"]
    if len(mzs) == 0: continue
    # window = precursors physically co-isolated with this one
    iso = pre.get("isolationWindow", {})
    tgt = float(iso.get("isolation window target m/z", pmz))
    lo  = tgt - float(iso.get("isolation window lower offset", 12.5))
    hi  = tgt + float(iso.get("isolation window upper offset", 12.5))
    co = [P[i] for i in pidx.get(int(rt/RTBIN), ())
          if lo <= P[i]["Precursor.Mz"] <= hi
          and (im < 0 or abs(P[i]["IM"]-im) <= D_IM)]
    # own = the precursor this spectrum claims
    best = min((p for p in co if abs(p["Precursor.Mz"]-pmz)/pmz*1e6 <= PPM_PREC),
               key=lambda p: abs(p["Precursor.Mz"]-pmz), default=None)
    nco.append(len(co))
    if best is None:
        stat["unexplained_precursor"] += 1; continue
    matched_pids.add(best["Precursor.Id"])
    if z: zc[(z, best["Precursor.Charge"])] += 1
    fo = frags.get(best["Precursor.Id"], np.array([]))
    fo_dec = fo + DECOY_SHIFT
    others = np.sort(np.concatenate([frags[p["Precursor.Id"]] for p in co
              if p["Precursor.Id"] != best["Precursor.Id"] and p["Precursor.Id"] in frags]
              or [np.array([])]))
    tot = ints.sum() or 1.0
    io = ib = iu = idc = 0.0
    for mz, it in zip(mzs, ints):
        if   hits(fo, mz, PPM_FRAG):     io += it
        elif hits(others, mz, PPM_FRAG): ib += it
        else:                            iu += it
        if hits(fo_dec, mz, PPM_FRAG):   idc += it
    own_f.append(io/tot); oth_f.append(ib/tot); une_f.append(iu/tot); dec_f.append(idc/tot)
    stat["pure" if io/tot>=0.5 and ib/tot<0.1 else
         "chimeric" if ib/tot>=0.1 else "low_signal"] += 1

# recall over the stratified cycles
present = {p["Precursor.Id"] for p in P if in_sel(p["RT"])}
o,b,u,d = map(np.array,(own_f,oth_f,une_f,dec_f))
print(f"\n===== {TAG} =====")
print(f"spectra in selected cycles : {n_spec}")
print(f"RECALL  {len(matched_pids & present)}/{len(present)} = "
      f"{100*len(matched_pids&present)/max(1,len(present)):.1f}%  of DIA-NN precursors")
print(f"class   {dict(stat)}")
if nco:
    n=np.array(nco)
    print(f"CO-ISOLATED DIA-NN precursors per spectrum: mean {n.mean():.1f} "
          f"median {np.median(n):.0f} p90 {np.percentile(n,90):.0f} max {n.max()} "
          f"| {100*(n<=1).mean():.1f}% singleton")
if len(o):
    print(f"intensity  OWN {o.mean()*100:.1f}%  CO-ISOLATED {b.mean()*100:.1f}%  "
          f"UNEXPLAINED {u.mean()*100:.1f}%   [decoy background {d.mean()*100:.1f}%]")
    print(f"OWN corrected for random matching: {(o.mean()-d.mean())*100:.1f}%")
if zc:
    agree = sum(v for (a,bq),v in zc.items() if a==bq); tot=sum(zc.values())
    print(f"CHARGE agreement {agree}/{tot} = {100*agree/tot:.1f}%")
    print(f"  top confusions: {sorted(((v,f'ours{a}->true{bq}') for (a,bq),v in zc.items() if a!=bq), reverse=True)[:4]}")
