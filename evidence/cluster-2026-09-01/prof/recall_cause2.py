#!/usr/bin/env python3
# v2: diaTracer's patched.mzML has STALE byte offsets (patched after indexing), so decode dt spectra
# by a SEQUENTIAL pass (Sage reads it fine sequentially too). Our mzML index is valid (unpatched).
# Separates: (1) precursor mass/charge correctness; (2) b/y ladder ours vs diaTracer (same method,
# fair); (3) peak counts; (4) missing-ion recovery from our adjacent spectra. Inline SHARED positive
# control + decoy-ladder chance floor.
import base64, struct, csv, sys, bisect, re, zlib, statistics as st
DET4_MZML="/scratch/kohlbach/prof/det4/pseudo.mzML"; DET4_TSV="/scratch/kohlbach/prof/det4/results.sage.tsv"
DT_MZML="/scratch/kohlbach/dt_s30/patched.mzML";     DT_TSV="/scratch/kohlbach/dt_s30/results.sage.tsv"
COORDS="/scratch/kohlbach/prof/det4/precursor_coords.tsv"
FRAG_PPM=25.0; PROTON=1.00727646; H2O=18.0105646; CYCLE=1.385
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
def decode_mz(block):
    for bda in re.finditer(r'<binaryDataArray.*?</binaryDataArray>',block,re.S):
        b=bda.group(0)
        if 'm/z array' not in b:continue
        hdr=b[:b.find('<binary>')];bits=64 if '64-bit float' in hdr else 32
        comp=('MS:1000574' in hdr) or ('zlib compression' in hdr)
        mm=re.search(r'<binary>([A-Za-z0-9+/=\s]*)</binary>',b)
        if not mm:return None
        raw=base64.b64decode(''.join(mm.group(1).split()))
        if comp:raw=zlib.decompress(raw)
        per=bits//8;return sorted(struct.unpack(('<%dd' if bits==64 else '<%df')%(len(raw)//per),raw))
    return None
class Idx:  # index-seek (valid for our unpatched mzML)
    def __init__(s,p):
        s.f=open(p,'rb');s.f.seek(0,2);s.size=s.f.tell();s.f.seek(s.size-4000)
        o=int(re.search(r'<indexListOffset>(\d+)',s.f.read().decode('ascii','ignore')).group(1))
        s.f.seek(o);idx=s.f.read(s.size-o).decode('ascii','ignore')
        s.off={a:int(b) for a,b in re.findall(r'<offset idRef="([^"]+)">(\d+)</offset>',idx)}
    def mz(s,sid):
        o=s.off.get(sid)
        if o is None:return None
        s.f.seek(o);buf=s.f.read(300000);e=buf.find(b'</spectrum>')
        while e<0:
            m=s.f.read(300000)
            if not m:break
            buf+=m;e=buf.find(b'</spectrum>')
        return decode_mz(buf[:e].decode('ascii','ignore'))
def seq_collect(path, needed):
    # one sequential pass: id->sorted mz for ids in `needed`
    out={};buf=b'';want=False;cid=None
    f=open(path,'rb')
    START=re.compile(rb'<spectrum [^>]*id="([^"]+)"')
    while True:
        chunk=f.read(8<<20)
        if not chunk: break
        buf+=chunk
        while True:
            si=buf.find(b'<spectrum ')
            if si<0:
                if len(buf)>1<<20: buf=buf[-1000:]
                break
            ei=buf.find(b'</spectrum>', si)
            if ei<0:
                buf=buf[si:]; break
            block=buf[si:ei+11]; buf=buf[ei+11:]
            m=START.search(block)
            if m:
                sid=m.group(1).decode()
                if sid in needed:
                    out[sid]=decode_mz(block.decode('ascii','ignore'))
    return out
def best(tsv):
    b={}
    for x in csv.DictReader(open(tsv),delimiter="\t"):
        if x["label"]!="1":continue
        try:
            if float(x["peptide_q"])>0.01:continue
        except:continue
        s=float(x["sage_discriminant_score"]);p=x["peptide"]
        if p in b and b[p]["s"]>=s:continue
        b[p]={"s":s,"z":int(x["charge"]),"scan":x["scannr"],"calc":float(x["calcmass"]),"rt":float(x["rt"])}
    return b
def cov(mz,ions,off=0.0):
    if not mz:return 0
    h=0
    for ion in ions:
        t=ion*FRAG_PPM*1e-6;k=bisect.bisect_left(mz,ion+off-t)
        if k<len(mz) and mz[k]<=ion+off+t:h+=1
    return h

print("[load] sage",flush=True)
ours=best(DET4_TSV);dt=best(DT_TSV)
MISS={p:v for p,v in dt.items() if p not in ours}
SHARED=[p for p in dt if p in ours]
print(f"[sets] dt {len(dt)} ours {len(ours)} MISS {len(MISS)} SHARED {len(SHARED)}",flush=True)
det=Idx(DET4_MZML)
tm=det.mz("spectrum=100000");print(f"[selftest ours-decode] {len(tm) if tm else None} peaks",flush=True)
# coords for our-spectrum lookup
CM=[]
for i,line in enumerate(open(COORDS)):
    a=line.split("\t");CM.append((float(a[0]),int(a[1]) if a[1] and a[1]!='0' else 0,float(a[2]),float(a[3]),i))
CM.sort();cmz=[c[0] for c in CM]
def near(mz,rt,win):
    tol=mz*20e-6;lo=bisect.bisect_left(cmz,mz-tol);hi=bisect.bisect_right(cmz,mz+tol)
    return [CM[k] for k in range(lo,hi) if abs(CM[k][2]-rt)<=win]
# sequential dt decode for all needed dt scans (MISS + SHARED-sample)
shared_ctrl=SHARED[:600]
need={dt[p]["scan"] for p in MISS} | {dt[p]["scan"] for p in shared_ctrl}
print(f"[dt seq-decode] collecting {len(need)} dt spectra in one pass ...",flush=True)
dtpk=seq_collect(DT_MZML, need)
print(f"[dt seq-decode] got {len(dtpk)} / {len(need)}",flush=True)

# POSITIVE CONTROL (SHARED): our cov (our scan) and dt cov (dt scan) should both be high
oc_s=[];dc_s=[]
for p in shared_ctrl:
    ions=by_ions(*parse(p),min(2,dt[p]["z"]))
    om=det.mz(ours[p]["scan"]); dm=dtpk.get(dt[p]["scan"])
    if om:oc_s.append(cov(om,ions)/len(ions))
    if dm:dc_s.append(cov(dm,ions)/len(ions))
print(f"[POS CONTROL shared] OUR cov {st.median(oc_s):.3f} (n={len(oc_s)})  dt cov {st.median(dc_s):.3f} (n={len(dc_s)})",flush=True)

# MISS analysis
n_emit=n_right=n_noright=n_wz=0
ocov=[];dcov=[];onp=[];dnp=[];ch=[];gain=[];push=0
for p,v in MISS.items():
    res,nt=parse(p);calc=v["calc"];z=v["z"];rt=v["rt"]*60.0;mzp=(calc+z*PROTON)/z
    cand=near(mzp,rt,30.0)
    if not cand:continue
    n_emit+=1
    right=next((c for c in cand if c[1]==z and abs(c[0]*z-z*PROTON-calc)<0.05),None)
    if right is None:
        n_noright+=1
        if any(c[1]!=z for c in cand):n_wz+=1
        continue
    n_right+=1
    ions=by_ions(res,nt,min(2,z));T=len(ions)
    om=det.mz(f"spectrum={right[4]}");dm=dtpk.get(v["scan"])
    oc=cov(om,ions)/T; dc=cov(dm,ions)/T if dm else float('nan')
    ocov.append(oc);
    if dm:dcov.append(dc)
    ch.append(cov(om,ions,off=13.0)/T)
    if om:onp.append(len(om))
    if dm:dnp.append(len(dm))
    # adjacent completion (our neighbours +-2 cycles)
    if om:
        unm=[ion for ion in ions if cov(om,[ion])==0]
        adj=near(mzp,rt,2*CYCLE);ap=set()
        for c in adj:
            if c[4]==right[4] or c[1]!=z:continue
            am=det.mz(f"spectrum={c[4]}")
            if am:ap.update(am)
        ap=sorted(ap);rec=sum(1 for ion in unm if cov(ap,[ion])>0) if ap else 0
        if unm:gain.append(rec/len(unm))
        if dm and oc<dc and (cov(om,ions)+rec)/T>=dc:push+=1
def med(x):return st.median(x) if x else float('nan')
print(f"\n[emit] {n_emit}/{len(MISS)} MISS emitted near coord")
print(f"[precursor mass] RIGHT mass+charge: {n_right} ({100*n_right/max(n_emit,1):.1f}%)  NO right mass: {n_noright} ({100*n_noright/max(n_emit,1):.1f}%), of which wrong-charge {n_wz}")
print(f"[ladder cov MISS] OURS {med(ocov):.3f}  diaTracer {med(dcov):.3f}  decoy-chance {med(ch):.3f}   (SHARED ref: ours {med(oc_s):.3f})")
print(f"[peak count MISS] OURS {med(onp):.0f}  diaTracer {med(dnp):.0f}")
print(f"[adjacent completion] median missing-ion recovery from our +-2cyc neighbours: {med(gain):.3f}; would lift ours>=dt in {push} cases")
