#!/usr/bin/env python3
# Diagnostics before trusting recall_cause: (1) are diaTracer scan ids found in the mzML index?
# (2) POSITIVE CONTROL: for SHARED peptides we identified, does OUR spectrum show high ladder
# coverage (it must)? (3) concrete examples. Reuses the machinery from recall_cause.
import importlib.util, sys
spec=importlib.util.spec_from_file_location("rc","/scratch/kohlbach/prof/recall_cause.py")
# recall_cause runs analysis on import; instead re-implement the minimal bits here.
import base64,struct,csv,bisect,re,zlib,statistics as st
PROTON=1.00727646;H2O=18.0105646;FRAG_PPM=25.0
AA={'G':57.02146,'A':71.03711,'S':87.03203,'P':97.05276,'V':99.06841,'T':101.04768,'C':103.00919,
'L':113.08406,'I':113.08406,'N':114.04293,'D':115.02694,'Q':128.05858,'K':128.09496,'E':129.04259,
'M':131.04049,'H':137.05891,'F':147.06841,'R':156.10111,'Y':163.06333,'W':186.07931}
def parse(pep):
    res=[];nt=0.0;i=0
    while i<len(pep):
        c=pep[i]
        if c=='[':
            j=pep.index(']',i);v=float(pep[i+1:j].replace('+',''))
            if res:res[-1]+=v
            else:nt+=v
            i=j+1
        elif c=='-':i+=1
        elif c in AA:res.append(AA[c]);i+=1
        else:i+=1
    return res,nt
def by_ions(res,nt,maxz):
    ions=[];n=len(res);cb=nt
    for k in range(n-1):
        cb+=res[k]
        for z in range(1,maxz+1):ions.append((cb+z*PROTON)/z)
    cy=H2O
    for k in range(n-1):
        cy+=res[n-1-k]
        for z in range(1,maxz+1):ions.append((cy+z*PROTON)/z)
    return sorted(ions)
class MzML:
    def __init__(s,p):
        s.f=open(p,'rb');s.f.seek(0,2);s.size=s.f.tell();s.f.seek(max(0,s.size-4000))
        t=s.f.read().decode('ascii','ignore');o=int(re.search(r'<indexListOffset>(\d+)',t).group(1))
        s.f.seek(o);idx=s.f.read(s.size-o).decode('ascii','ignore')
        s.offset={a:int(b) for a,b in re.findall(r'<offset idRef="([^"]+)">(\d+)</offset>',idx)}
    def peaks(s,sid):
        o=s.offset.get(sid)
        if o is None:return None
        s.f.seek(o);buf=s.f.read(300000);e=buf.find(b'</spectrum>')
        while e<0:
            m=s.f.read(300000)
            if not m:break
            buf+=m;e=buf.find(b'</spectrum>')
        block=buf[:e].decode('ascii','ignore');mz=None
        for bda in re.finditer(r'<binaryDataArray.*?</binaryDataArray>',block,re.S):
            b=bda.group(0)
            if 'm/z array' not in b:continue
            hdr=b[:b.find('<binary>')];bits=64 if '64-bit float' in hdr else 32
            comp=('MS:1000574' in hdr) or ('zlib compression' in hdr)
            mm=re.search(r'<binary>([A-Za-z0-9+/=\s]*)</binary>',b)
            if not mm:continue
            raw=base64.b64decode(''.join(mm.group(1).split()))
            if comp:raw=zlib.decompress(raw)
            per=bits//8;mz=struct.unpack(('<%dd' if bits==64 else '<%df')%(len(raw)//per),raw)
        return sorted(mz) if mz else None
def cov(mz,ions,off=0.0):
    if not mz:return 0
    h=0
    for ion in ions:
        t=ion*FRAG_PPM*1e-6;k=bisect.bisect_left(mz,ion+off-t)
        if k<len(mz) and mz[k]<=ion+off+t:h+=1
    return h
def best(tsv):
    b={}
    for x in csv.DictReader(open(tsv),delimiter="\t"):
        if x["label"]!="1":continue
        try:
            if float(x["peptide_q"])>0.01:continue
        except:continue
        s=float(x["sage_discriminant_score"]);p=x["peptide"]
        if p in b and b[p]["s"]>=s:continue
        b[p]={"s":s,"z":int(x["charge"]),"scan":x["scannr"],"calc":float(x["calcmass"]),
              "rt":float(x["rt"]),"mp":int(x["matched_peaks"])}
    return b
ours=best("/scratch/kohlbach/prof/det4/results.sage.tsv");dt=best("/scratch/kohlbach/dt_s30/results.sage.tsv")
det=MzML("/scratch/kohlbach/prof/det4/pseudo.mzML");dtm=MzML("/scratch/kohlbach/dt_s30/patched.mzML")
# 1. dt scan found rate
found=sum(1 for p,v in dt.items() if v["scan"] in dtm.offset)
print(f"dt scans found in dt mzML index: {found}/{len(dt)}")
print("sample dt offset keys:",list(dtm.offset)[:3],"| sample dt scan:",next(iter(dt.values()))["scan"])
# 2. POSITIVE CONTROL: SHARED peptides -> our spectrum via OUR scan; ladder cov should be high and ~ track matched_peaks
shared=[p for p in dt if p in ours]
print(f"\nPOSITIVE CONTROL on {min(30,len(shared))} SHARED peptides (our own identifying spectrum):")
oc=[];dc=[];mpr=[]
for p in shared[:400]:
    v=ours[p];res,nt=parse(p);ions=by_ions(res,nt,min(2,v["z"]))
    omz=det.peaks(v["scan"])              # OUR identifying scan for this peptide
    if not omz:continue
    c=cov(omz,ions);oc.append(c/len(ions));mpr.append((c,v["mp"]))
    dv=dt[p];dmz=dtm.peaks(dv["scan"])
    if dmz:dc.append(cov(dmz,by_ions(*parse(p),min(2,dv["z"]))) /len(ions))
print(f"  OUR ladder cov median {st.median(oc):.3f} (n={len(oc)})   dt ladder cov median {st.median(dc):.3f}")
print(f"  our matched-ions vs Sage matched_peaks (should track): sample {mpr[:6]}")
