#!/usr/bin/env python3
# Emission-ceiling oracle. Cluster all emitted spectra into coordinate-features (charge, m/z ppm,
# RT window, IM tol) and decompose the 1.53M emission into hit-features (contain >=1 identified
# spectrum) vs noise-features (never identify). Tells us whether feature-collapse alone reaches
# 700k, and which lever (collapse redundancy vs drop noise) buys what. Peptide-neutrality via the
# chimeric-feature rate. ponytail: grid-bin (slight over-count => conservative/pessimistic F).
import math, sys
from collections import defaultdict

COORDS = "/scratch/kohlbach/prof/det4/precursor_coords.tsv"
SAGE   = "/scratch/kohlbach/prof/det4/results.sage.tsv"
DIATRACER = 700434
BASELINE  = 1528113

# 1. coords: row i (0-indexed) == spectrum index i
mz=[]; z=[]; rt=[]; im=[]
with open(COORDS) as f:
    for line in f:
        a=line.rstrip("\n").split("\t")
        if len(a)<4 or a[0]=="": continue
        mz.append(float(a[0])); z.append(a[1] if a[1] else "0")
        rt.append(float(a[2]) if a[2] else 0.0); im.append(float(a[3]) if a[3] else 0.0)
N=len(mz)

# 2. identified spectra: spectrum index -> peptide (target, peptide_q<=0.01, rank1)
idpep={}
with open(SAGE) as f:
    h=f.readline().rstrip("\n").split("\t"); ci={n:i for i,n in enumerate(h)}
    L,Q,S,P,R = ci["label"],ci["peptide_q"],ci["scannr"],ci["peptide"],ci["rank"]
    for line in f:
        c=line.rstrip("\n").split("\t")
        if c[L]!="1": continue
        if c[R]!="1": continue
        try:
            if float(c[Q])>0.01: continue
        except ValueError: continue
        idx=int(c[S].split("=")[1])
        idpep[idx]=c[P]
n_id=len(idpep); n_pep=len(set(idpep.values()))
print(f"N spectra={N}  identified(target,q<=.01,rank1)={n_id}  unique peptides={n_pep}  redundancy={n_id/n_pep:.2f}")
print(f"baseline emission={BASELINE}  diaTracer={DIATRACER}\n")

def run(ppm, rt_win, im_tol):
    lstep=math.log(1.0+ppm*1e-6)
    feat=defaultdict(list)
    for i in range(N):
        key=(z[i], int(math.log(mz[i])/lstep), int(rt[i]//rt_win), int(im[i]/im_tol))
        feat[key].append(i)
    F=len(feat)
    hit=noise=sp_hit=sp_noise=chimeric=0
    pep_feats=defaultdict(set)
    for key,mem in feat.items():
        peps=set(idpep[i] for i in mem if i in idpep)
        if peps:
            hit+=1; sp_hit+=len(mem)
            if len(peps)>=2: chimeric+=1
            for p in peps: pep_feats[p].add(key)
        else:
            noise+=1; sp_noise+=len(mem)
    chim_keys=set()
    for key,mem in feat.items():
        peps=set(idpep[i] for i in mem if i in idpep)
        if len(peps)>=2: chim_keys.add(key)
    pep_at_risk=sum(1 for p,ks in pep_feats.items() if ks<=chim_keys)
    print(f"--- ppm={ppm} rt_win={rt_win}s im_tol={im_tol} ---")
    print(f"  F_total (collapse ALL to 1/feat) = {F:>9}   ({BASELINE/F:.2f}x compression; vs 700k: {'<=700k OK' if F<=DIATRACER else 'ABOVE 700k'})")
    print(f"  hit-features={hit:>8}  noise-features={noise:>9}  ({100*noise/F:.1f}% of features never identify)")
    print(f"  spectra in hit-features  ={sp_hit:>9}   ({100*sp_hit/BASELINE:.1f}% of emission)")
    print(f"  spectra in noise-features={sp_noise:>9}   ({100*sp_noise/BASELINE:.1f}% of emission)")
    print(f"  => drop noise, keep hit as-is     : emit {sp_hit:>9}")
    print(f"  => drop noise + collapse hit to 1 : emit {hit:>9}")
    print(f"  peptide-neutrality: chimeric hit-features={chimeric} ({100*chimeric/max(hit,1):.2f}% of hit-features); peptides only-in-chimeric={pep_at_risk} ({100*pep_at_risk/n_pep:.2f}% of peptides)\n")

for ppm,rtw,imt in [(20,1.4,0.02),(20,3.6,0.02),(20,7.0,0.02),(20,3.6,0.01),(10,1.4,0.01)]:
    run(ppm,rtw,imt)
