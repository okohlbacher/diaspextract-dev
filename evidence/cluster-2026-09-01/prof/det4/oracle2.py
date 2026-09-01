#!/usr/bin/env python3
# Simulate the "require >=1 isotope partner" precursor quality gate on EXISTING emission, from
# coords alone. For each emitted spectrum, is there a co-eluting (rt), co-mobile (im), same-charge
# partner at +/- 1.00335/z (M+1 or M-1) within ppm? yes => isotope-supported (survives gate);
# no => singleton (dropped). Report emission after gate AND identified-peptide retention.
# This is a geometric PROXY for the tool's `guessed` flag: it tells us what an isotope-support gate
# would cost in peptides, using existing data (no re-run). ponytail: 3x3 rt/im neighbourhood + bisect.
import math, bisect
from collections import defaultdict

COORDS="/scratch/kohlbach/prof/det4/precursor_coords.tsv"
SAGE  ="/scratch/kohlbach/prof/det4/results.sage.tsv"
ISO=1.0033548

mz=[]; z=[]; rt=[]; im=[]
with open(COORDS) as f:
    for line in f:
        a=line.rstrip("\n").split("\t")
        if len(a)<4 or a[0]=="": continue
        mz.append(float(a[0])); z.append(int(a[1]) if a[1] and a[1]!="0" else 0)
        rt.append(float(a[2]) if a[2] else 0.0); im.append(float(a[3]) if a[3] else 0.0)
N=len(mz)

idpep={}
with open(SAGE) as f:
    h=f.readline().rstrip("\n").split("\t"); ci={n:i for i,n in enumerate(h)}
    L,Q,S,P,R=ci["label"],ci["peptide_q"],ci["scannr"],ci["peptide"],ci["rank"]
    for line in f:
        c=line.rstrip("\n").split("\t")
        if c[L]!="1" or c[R]!="1": continue
        try:
            if float(c[Q])>0.01: continue
        except ValueError: continue
        idpep[int(c[S].split("=")[1])]=c[P]
n_pep=len(set(idpep.values()))

def gate(ppm, RTW, IMT):
    # cell = (z, rt_bin, im_bin) -> sorted list of mz ; check own + 3x3 neighbours
    cell=defaultdict(list)
    for i in range(N):
        cell[(z[i], int(rt[i]//RTW), int(im[i]//IMT))].append(mz[i])
    for k in cell: cell[k].sort()
    def has_partner(i):
        zz=z[i]
        if zz<=0: return False
        d=ISO/zz
        rb=int(rt[i]//RTW); ib=int(im[i]//IMT)
        for tgt in (mz[i]+d, mz[i]-d):
            lo=tgt*(1-ppm*1e-6); hi=tgt*(1+ppm*1e-6)
            for drb in (-1,0,1):
                for dib in (-1,0,1):
                    lst=cell.get((zz,rb+drb,ib+dib))
                    if not lst: continue
                    p=bisect.bisect_left(lst,lo)
                    if p<len(lst) and lst[p]<=hi: return True
        return False
    supported=0; id_kept=0; peps=set()
    for i in range(N):
        if has_partner(i):
            supported+=1
            if i in idpep: id_kept+=1; peps.add(idpep[i])
    print(f"--- gate: require M+-1 partner within ppm={ppm}, rt<={RTW}s, im<={IMT} ---")
    print(f"  emission after gate = {supported:>9}  ({100*supported/N:.1f}% kept; {N-supported} singletons dropped)  vs 700k")
    print(f"  identified spectra kept = {id_kept}/{len(idpep)} ({100*id_kept/len(idpep):.1f}%)")
    print(f"  peptides retained = {len(peps)}/{n_pep} ({100*len(peps)/n_pep:.2f}%)  => peptide loss {100*(1-len(peps)/n_pep):.2f}%\n")

print(f"N={N}  identified peptides={n_pep}\n")
for ppm,rtw,imt in [(20,3.6,0.02),(20,7.0,0.02),(30,7.0,0.03)]:
    gate(ppm,rtw,imt)
