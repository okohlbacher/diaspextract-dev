#!/usr/bin/env python3
# Does envelope-quality (averagine-cos x isotope-XIC-corr x evidence) separate identifying from
# non-identifying SUPPORTED precursors well enough to cut 924k->700k at neutral peptides? Rank
# supported spectra by env_quality desc, keep the top 700,434, measure peptides lost. Compare to the
# peak-count probe (-7.27%). Also the identify rate by env_quality bin.
from collections import defaultdict
STAMP="/scratch/kohlbach/prof/envq/stamps.tsv"        # index<TAB>guessed<TAB>envq
SAGE ="/scratch/kohlbach/prof/det4/results.sage.tsv"
TARGET=700434

guessed={}; envq={}
for line in open(STAMP):
    a=line.rstrip("\n").split("\t")
    if len(a)<3: continue
    i=int(a[0]); guessed[i]=int(a[1]); envq[i]=float(a[2])
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

sup=[(envq[i], i) for i in envq if guessed.get(i,0)==0]     # supported spectra with their quality
sup.sort(reverse=True)                                       # highest quality first
keep=set(i for _,i in sup[:TARGET])                          # keep top-quality up to 700434
thr=sup[TARGET][0] if TARGET<len(sup) else 0.0

pep_specs=defaultdict(list)
for i,pep in idpep.items():
    if guessed.get(i,0)==0: pep_specs[pep].append(i)
sup_peps=set(pep_specs)
lost={p for p,s in pep_specs.items() if all(x not in keep for x in s)}

print(f"supported spectra={len(sup)}  keep top-quality {min(TARGET,len(sup))} -> total emission {min(TARGET,len(sup))} (target {TARGET})")
print(f"env_quality threshold at the cut = {thr:.4f}")
print(f"supported peptides={len(sup_peps)}  LOST={len(lost)} ({100*len(lost)/len(sup_peps):.2f}%)   [peak-count probe lost 7.27%]")
print(f"env_quality==0 among supported (no shape scored): {sum(1 for q,_ in sup if q==0.0)} ({100*sum(1 for q,_ in sup if q==0.0)/len(sup):.1f}%)")

idset=set(i for i in idpep if guessed.get(i,0)==0)
print("\nenv_quality bin | supported spectra | identify rate")
for lo,hi in [(-0.001,0.0001),(0.0001,0.1),(0.1,0.3),(0.3,0.5),(0.5,0.7),(0.7,0.9),(0.9,1.01)]:
    tot=sum(1 for q,i in sup if lo<q<=hi)
    idc=sum(1 for q,i in sup if lo<q<=hi and i in idset)
    print(f"  ({lo:.3f},{hi:.3f}] | {tot:8d} | {100*idc/max(tot,1):.2f}%")
