#!/usr/bin/env python3
# Supported-side peak-count probe. Among the 924k supported spectra (guessed already gated), rank by
# emitted peak count; drop the lowest to reach 700,434 total; measure peptides lost + the identify
# rate by peak-count bin. Tells us if peak count can safely cut the last 924k->700k.
from collections import defaultdict
NPK="/scratch/kohlbach/prof/det4/npeaks.tsv"
GUE="/scratch/kohlbach/prof/stamp/guessed.tsv"
SAGE="/scratch/kohlbach/prof/det4/results.sage.tsv"
TARGET=700434

npk={}
for line in open(NPK):
    a=line.split("\t");  npk[int(a[0])]=int(a[1])
g={}
for line in open(GUE):
    a=line.split("\t");  g[int(a[0])]=int(a[1])
idpep={}
with open(SAGE) as f:
    h=f.readline().rstrip("\n").split("\t"); ci={n:i for i,n in enumerate(h)}
    for line in f:
        c=line.rstrip("\n").split("\t")
        if c[ci["label"]]!="1" or c[ci["rank"]]!="1": continue
        try:
            if float(c[ci["peptide_q"]])>0.01: continue
        except ValueError: continue
        idpep[int(c[ci["scannr"]].split("=")[1])]=c[ci["peptide"]]

sup=[(npk[i],i) for i in npk if g.get(i,0)==0]
sup.sort()
drop_n=len(sup)-TARGET
dropped=set(i for _,i in sup[:drop_n])
cut_thr=sup[drop_n][0] if 0<=drop_n<len(sup) else None

pep_specs=defaultdict(list)
for i,pep in idpep.items():
    if g.get(i,0)==0: pep_specs[pep].append(i)
sup_peps=set(pep_specs)
lost={p for p,s in pep_specs.items() if all(x in dropped for x in s)}

print(f"supported spectra={len(sup)}  drop lowest-peakcount {drop_n} -> {len(sup)-drop_n} (target {TARGET})")
print(f"peak-count threshold at the cut = {cut_thr} (drop spectra with fewer peaks than this)")
print(f"supported peptides={len(sup_peps)}  LOST by the drop={len(lost)} ({100*len(lost)/len(sup_peps):.2f}%)")

# identify rate by peak-count bin among supported
bins=[(0,50),(50,100),(100,200),(200,350),(350,499),(499,10000)]
print("\npeak-count bin | supported spectra | identify rate")
idset=set(i for i in idpep if g.get(i,0)==0)
for lo,hi in bins:
    tot=sum(1 for n,i in sup if lo<=n<hi)
    idc=sum(1 for n,i in sup if lo<=n<hi and i in idset)
    print(f"  [{lo:4d},{hi:5d}) | {tot:8d} | {100*idc/max(tot,1):.2f}%")
