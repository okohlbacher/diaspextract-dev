#!/usr/bin/env python3
# Isotope-AWARE collapse oracle (de-confounded). Within each (z, rt_bin, im_bin) cell, single-link
# emitted spectra whose sorted m/z gaps are ~ k*1.00335/z into one isotope-family. This collapses
# LEAKY de-isotoping (M and M+1 both emitted) that oracle1's same-m/z binning could not. Reports
# families (= emission if we keep 1 per isotope-family) and identified-peptide collision (a family
# holding >=2 distinct peptides => chimera => a peptide at risk). Valid because it does NOT need the
# guessed flag: it measures removable isotope redundancy and its peptide cost directly.
import math, bisect
from collections import defaultdict
COORDS="/scratch/kohlbach/prof/det4/precursor_coords.tsv"
SAGE  ="/scratch/kohlbach/prof/det4/results.sage.tsv"
ISO=1.0033548
BASELINE=1528113; DIATRACER=700434

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

def run(ppm, RTW, IMT):
    cell=defaultdict(list)
    for i in range(N):
        cell[(z[i], int(rt[i]//RTW), int(im[i]//IMT))].append(i)
    F=0; hit=0; chim=0; sp_hit=0
    pep_fams=defaultdict(int)   # peptide -> count of families it appears in
    pep_chim=set()
    for k,mem in cell.items():
        zz=k[0]
        if zz<=0:
            # unknown charge: each its own family (can't isotope-link)
            for i in mem:
                F+=1
                if i in idpep: hit+=1; sp_hit+=1
            continue
        d=ISO/zz
        mem.sort(key=lambda i: mz[i])
        # single-link consecutive if gap within ppm of k*d (k=1..3)
        fam=[mem[0]]; fams=[]
        for a,b in zip(mem, mem[1:]):
            gap=mz[b]-mz[a]
            linked=False
            for kk in (1,2,3):
                tgt=kk*d
                if abs(gap-tgt)<=tgt*ppm*1e-6 or abs(gap-tgt)<=0.01:
                    linked=True; break
            if linked: fam.append(b)
            else: fams.append(fam); fam=[b]
        fams.append(fam)
        for fm in fams:
            F+=1
            peps=set(idpep[i] for i in fm if i in idpep)
            if peps:
                hit+=1; sp_hit+=len(fm)
                if len(peps)>=2:
                    chim+=1
                    for p in peps: pep_chim.add(p)
                for p in peps: pep_fams[p]+=1
    # peptides whose every family is chimeric-lost: approximate with pep_chim minus those with a pure family
    pure_peps=set(p for p,c in pep_fams.items() if c>0) - pep_chim  # appear somewhere; some may still be pure
    P=len(pep_fams)
    print(f"--- isotope-aware, ppm={ppm} rt<={RTW}s im<={IMT} ---")
    print(f"  isotope-families (emit 1/family) = {F:>9}  ({BASELINE/F:.2f}x vs baseline; vs 700k: {'<=700k' if F<=DIATRACER else 'ABOVE'})")
    print(f"  spectra in hit-families={sp_hit}  identified-region redundancy={sp_hit/max(hit,1):.2f}")
    print(f"  chimeric families={chim}  peptides sharing a family with another={len(pep_chim)} ({100*len(pep_chim)/n_pep:.2f}%)\n")

print(f"N={N} identified peptides={n_pep}  baseline={BASELINE} diaTracer={DIATRACER}\n")
for ppm,rtw,imt in [(20,3.6,0.02),(20,1.4,0.02),(15,3.6,0.015)]:
    run(ppm,rtw,imt)
