#!/usr/bin/env python3
"""Are our precursors ISOTOPE SIBLINGS of each other? (the 4.6 PSMs/peptide mechanism)

If isotope inference fails, M / M+1 / M+2 of ONE peptide each become an independent precursor at the
same RT+IM separated by 1.0033/z. Count how many of our precursors have a sibling at +-k*1.0033/z
within tight RT+IM. Decoy control: the same test at a NON-isotopic offset.
"""
import sys, collections, bisect
sys.path.insert(0,"/scratch/kohlbach/bench/s08")
from precursor_audit import extract
ISO=1.0033548

def sibfrac(recs, offs, label):
    # bucket by (rt,im) so siblings must co-localise
    g=collections.defaultdict(list)
    for r in recs: g[(int(r[0]//4.0), int(r[3]//0.01))].append(r)
    for k in g: g[k].sort(key=lambda r:r[1])
    hits=0
    for (rt,mz,z,im,npk) in recs:
        zz = z if z>0 else 2
        found=False
        for dr in (-1,0,1):
            for di in (-1,0,1):
                b=g.get((int(rt//4.0)+dr,int(im//0.01)+di))
                if not b: continue
                mzs=[x[1] for x in b]
                for k in offs:
                    t=mz+k*ISO/zz
                    i=bisect.bisect_left(mzs,t-0.01)
                    while i<len(mzs) and mzs[i]<=t+0.01:
                        if abs(mzs[i]-mz)>1e-6 and abs(b[i][0]-rt)<=4.0 and abs(b[i][3]-im)<=0.02:
                            found=True; break
                        i+=1
                    if found: break
                if found: break
            if found: break
        hits+=found
    print("  %-28s %7d / %7d = %5.1f%%"%(label,hits,len(recs),100.0*hits/max(len(recs),1)))
    return hits

for tag,path in (("OURS","/scratch/kohlbach/bench/s08/ours/pseudo.mzML"),
                 ("diaTracer","/ceph/ibmi/abi/data/2026_AGXT_PH1_liver_diaPASEF/mzml_diatracer/FKL4341-S08-A-3_K30454-19-3_QKL29021A9_Slot1-12_1_1305_diatracer.mzML")):
    r=extract(path)
    print("=== %s (n=%d) ==="%(tag,len(r)))
    sibfrac(r,(-2,-1,1,2),"has isotope sibling")
    sibfrac(r,(-2.37,2.37),"DECOY (non-isotopic offset)")
