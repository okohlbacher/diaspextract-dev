#!/usr/bin/env python3
# Why don't our emitted spectra for missed (low-abundance) peptides identify? For each peptide
# diaTracer finds and we miss, locate OUR emitted spectrum at that coordinate and diaTracer's, and
# separate causes: (1) wrong precursor mass (charge/mono) -> Sage searches the wrong mass;
# (2) poor b/y ladder / few peaks -> fragment content; (3) missing true ions recoverable from OUR
# ADJACENT spectra -> completion potential. Decoy-ladder chance control + self-tests included.
import base64, struct, csv, sys, bisect, re, zlib, statistics as st

DET4_MZML="/scratch/kohlbach/prof/det4/pseudo.mzML"; DET4_TSV="/scratch/kohlbach/prof/det4/results.sage.tsv"
DT_MZML="/scratch/kohlbach/dt_s30/patched.mzML";     DT_TSV="/scratch/kohlbach/dt_s30/results.sage.tsv"
COORDS="/scratch/kohlbach/prof/det4/precursor_coords.tsv"
FRAG_PPM=25.0; PROTON=1.00727646; H2O=18.0105646; CYCLE=1.385
AA={'G':57.02146,'A':71.03711,'S':87.03203,'P':97.05276,'V':99.06841,'T':101.04768,
    'C':103.00919,'L':113.08406,'I':113.08406,'N':114.04293,'D':115.02694,
    'Q':128.05858,'K':128.09496,'E':129.04259,'M':131.04049,'H':137.05891,'F':147.06841,
    'R':156.10111,'Y':163.06333,'W':186.07931}
def parse(pep):
    res=[]; nterm=0.0; i=0
    while i<len(pep):
        ch=pep[i]
        if ch=='[':
            j=pep.index(']',i); v=float(pep[i+1:j].replace('+',''))
            if res: res[-1]+=v
            else: nterm+=v
            i=j+1
        elif ch=='-': i+=1
        elif ch in AA: res.append(AA[ch]); i+=1
        else: i+=1
    return res,nterm
def pmass(res,nt): return sum(res)+H2O+nt
def by_ions(res,nt,maxz):
    ions=[]; n=len(res); cb=nt
    for k in range(n-1):
        cb+=res[k]
        for z in range(1,maxz+1): ions.append((cb+z*PROTON)/z)
    cy=H2O
    for k in range(n-1):
        cy+=res[n-1-k]
        for z in range(1,maxz+1): ions.append((cy+z*PROTON)/z)
    return sorted(ions)
class MzML:
    def __init__(self,path):
        self.f=open(path,'rb'); self.f.seek(0,2); self.size=self.f.tell()
        self.f.seek(max(0,self.size-4000)); tail=self.f.read().decode('ascii','ignore')
        m=re.search(r'<indexListOffset>(\d+)</indexListOffset>',tail) or sys.exit("ABORT no index "+path)
        off=int(m.group(1)); self.f.seek(off); idx=self.f.read(self.size-off).decode('ascii','ignore')
        self.offset={a:int(b) for a,b in re.findall(r'<offset idRef="([^"]+)">(\d+)</offset>', idx)}
    def peaks(self, sid):
        off=self.offset.get(sid)
        if off is None: return None,-1
        self.f.seek(off); buf=self.f.read(300_000); e=buf.find(b'</spectrum>')
        while e<0:
            more=self.f.read(300_000)
            if not more: break
            buf+=more; e=buf.find(b'</spectrum>')
        block=buf[:e].decode('ascii','ignore')
        dal=re.search(r'defaultArrayLength="(\d+)"',block); dal=int(dal.group(1)) if dal else -1
        mz=None
        for bda in re.finditer(r'<binaryDataArray.*?</binaryDataArray>', block, re.S):
            b=bda.group(0)
            if 'm/z array' not in b: continue
            hdr=b[:b.find('<binary>')]   # only the cvParams, NOT the base64 payload (which can contain "zlib" by chance)
            bits=64 if '64-bit float' in hdr else 32
            comp = ('MS:1000574' in hdr) or ('zlib compression' in hdr)
            mm=re.search(r'<binary>([A-Za-z0-9+/=\s]*)</binary>', b)
            if not mm: continue
            raw=base64.b64decode(''.join(mm.group(1).split()))
            if comp: raw=zlib.decompress(raw)
            per=bits//8
            mz=struct.unpack(('<%dd' if bits==64 else '<%df')%(len(raw)//per), raw)
        return (sorted(mz) if mz else None), dal
def best_per_pep(tsv):
    best={}
    with open(tsv) as f:
        for x in csv.DictReader(f,delimiter="\t"):
            if x["label"]!="1": continue
            try:
                if float(x["peptide_q"])>0.01: continue
            except: continue
            s=float(x["sage_discriminant_score"]); p=x["peptide"]
            if p in best and best[p]["s"]>=s: continue
            best[p]={"s":s,"z":int(x["charge"]),"scan":x["scannr"],"calcmass":float(x["calcmass"]),"rt":float(x["rt"])}
    return best

print("[load] sage",flush=True)
ours=best_per_pep(DET4_TSV); dt=best_per_pep(DT_TSV)
MISS={p:v for p,v in dt.items() if p not in ours}
print(f"[sets] dt {len(dt)} ours {len(ours)} MISS {len(MISS)}",flush=True)
bad=sum(1 for p,v in list(MISS.items())[:2000] if abs(pmass(*parse(p))-v["calcmass"])>0.02)
print(f"[selftest mass] {bad}/2000 mismatch",flush=True)
if bad>40: sys.exit("ABORT mass machinery")
print("[load] coords",flush=True)
CM=[]
for i,line in enumerate(open(COORDS)):
    a=line.split("\t"); CM.append((float(a[0]), int(a[1]) if a[1] and a[1]!='0' else 0, float(a[2]), float(a[3]), i))
CM.sort(); cmz=[c[0] for c in CM]
det=MzML(DET4_MZML); dtm=MzML(DT_MZML)
tmz,tdal=det.peaks("spectrum=100000")
print(f"[selftest decode] spectrum=100000 peaks {len(tmz) if tmz else None} vs dal {tdal}",flush=True)
if not tmz or len(tmz)!=tdal: sys.exit("ABORT decoder(ours)")
_k=next(iter(dtm.offset)); _m,_d=dtm.peaks(_k)
print(f"[selftest decode dt] {_k} peaks {len(_m) if _m else None} vs dal {_d}",flush=True)
if not _m or len(_m)!=_d: sys.exit("ABORT decoder(diaTracer)")

def near(mz, rt_sec, rt_win):
    tol=mz*20e-6; lo=bisect.bisect_left(cmz,mz-tol); hi=bisect.bisect_right(cmz,mz+tol); out=[]
    for k in range(lo,hi):
        m,z,rt,im,idx=CM[k]
        if abs(rt-rt_sec)<=rt_win: out.append((m,z,rt,im,idx))
    return out
def matchcov(mz, ions, off=0.0):
    if not mz: return 0
    h=0
    for ion in ions:
        t=ion*FRAG_PPM*1e-6; k=bisect.bisect_left(mz,ion+off-t)
        if k<len(mz) and mz[k]<=ion+off+t: h+=1
    return h

n_emit=n_right=n_noright=n_wz=n_wmono=0
ourcov=[]; dtcov=[]; ournp=[]; dtnp=[]; chance=[]; gain=[]; ratio_lt=0; comp_push=0
for p,v in MISS.items():
    res,nt=parse(p); calc=v["calcmass"]; z=v["z"]; rt_sec=v["rt"]*60.0; mzp=(calc+z*PROTON)/z
    cand=near(mzp, rt_sec, 30.0)
    if not cand: continue
    n_emit+=1
    right=None
    for (m,zz,rt,im,idx) in cand:
        if zz==z and abs(m*zz-zz*PROTON-calc)<0.05: right=(m,zz,rt,im,idx); break
    if right is None:
        n_noright+=1
        if any(zz!=z for (m,zz,rt,im,idx) in cand): n_wz+=1
        if any(zz==z and 0.5<abs(m*zz-zz*PROTON-calc)<3.5 for (m,zz,rt,im,idx) in cand): n_wmono+=1
        continue
    n_right+=1
    ions=by_ions(res,nt,min(2,z)); T=len(ions)
    omz,odal=det.peaks(f"spectrum={right[4]}")
    dmz,ddal=dtm.peaks(v["scan"])
    oc=matchcov(omz,ions)/T if T else 0; dc=matchcov(dmz,ions)/T if T else 0
    ch=matchcov(omz,ions,off=13.0)/T if T else 0   # decoy: shift ions +13 Da (chance floor)
    ourcov.append(oc); dtcov.append(dc); chance.append(ch)
    if omz: ournp.append(len(omz))
    if dmz: dtnp.append(len(dmz))
    if oc<dc: ratio_lt+=1
    # adjacent completion: unmatched true ions -> present in our adjacent spectra (+-2 cycles)?
    if omz:
        unmatched=[ion for ion in ions if matchcov(omz,[ion])==0]
        adj=near(mzp, rt_sec, 2*CYCLE)
        adjpk=set()
        for (m,zz,rt,im,idx) in adj:
            if idx==right[4] or zz!=z: continue
            amz,_=det.peaks(f"spectrum={idx}")
            if amz: adjpk.update(amz)
        adjpk=sorted(adjpk)
        rec=sum(1 for ion in unmatched if matchcov(adjpk,[ion])>0) if adjpk else 0
        if unmatched: gain.append(rec/len(unmatched))
        # would completion push coverage from our<dt to >=dt?
        if oc<dc and T and (matchcov(omz,ions)+rec)/T>=dc: comp_push+=1

def med(x): return st.median(x) if x else float('nan')
print(f"\n[emit] {n_emit}/{len(MISS)} MISS have a spectrum near coord",flush=True)
print(f"[precursor mass] RIGHT mass+charge present: {n_right} ({100*n_right/max(n_emit,1):.1f}%)   NO right mass: {n_noright} ({100*n_noright/max(n_emit,1):.1f}%)")
print(f"   no-right-mass breakdown: wrong-charge present {n_wz}, off-by-isotope present {n_wmono}")
print(f"\n[ladder coverage] (b/y matched fraction, right-mass spectra, n={len(ourcov)})")
print(f"   OURS  median {med(ourcov):.3f}   diaTracer median {med(dtcov):.3f}   decoy-chance median {med(chance):.3f}")
print(f"   our coverage < diaTracer in {ratio_lt}/{len(ourcov)} ({100*ratio_lt/max(len(ourcov),1):.1f}%)")
print(f"[peak count] OURS median {med(ournp):.0f}   diaTracer median {med(dtnp):.0f}")
print(f"[adjacent completion] median fraction of missing ions present in our +/-2-cycle neighbours: {med(gain):.3f}")
print(f"   MISS where completion would lift our coverage to >= diaTracer: {comp_push} ({100*comp_push/max(len(ourcov),1):.1f}%)")
