#!/usr/bin/env python3
# De-confound the recall diagnosis + project the MS2-deisotoping win, per the adversarial review:
#  - decode BOTH m/z and intensity;
#  - our spectrum = BEST-member of our multi-spectrum family (highest ladder coverage = oracle upper
#    bound, plus a peptide-blind highest-precursor-intensity pick) instead of first-match;
#  - dt DECOY floor (was never computed);
#  - coverage on the intensity TOP-150 (what Sage scores), not raw 500;
#  - DEISOTOPED-envelope coverage (fix #1 projection): collapse 1.0034/z-spaced peaks to monoisotope,
#    then measure ladder coverage and how many cap slots free up.
import base64,struct,csv,sys,bisect,re,zlib,statistics as st
DET4_MZML="/scratch/kohlbach/prof/det4/pseudo.mzML";DET4_TSV="/scratch/kohlbach/prof/det4/results.sage.tsv"
DT_MZML="/scratch/kohlbach/dt_s30/patched.mzML";DT_TSV="/scratch/kohlbach/dt_s30/results.sage.tsv"
COORDS="/scratch/kohlbach/prof/det4/precursor_coords.tsv"
FRAG_PPM=25.0;PROTON=1.00727646;H2O=18.0105646;ISO=1.0033548
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
def decode(block):  # -> list of (mz, inten)
    arr={}
    for bda in re.finditer(r'<binaryDataArray.*?</binaryDataArray>',block,re.S):
        b=bda.group(0);hdr=b[:b.find('<binary>')]
        kind='mz' if 'm/z array' in hdr else ('int' if 'intensity array' in hdr else None)
        if kind is None:continue
        bits=64 if '64-bit float' in hdr else 32;comp=('MS:1000574' in hdr) or ('zlib compression' in hdr)
        mm=re.search(r'<binary>([A-Za-z0-9+/=\s]*)</binary>',b)
        if not mm:continue
        raw=base64.b64decode(''.join(mm.group(1).split()))
        if comp:raw=zlib.decompress(raw)
        per=bits//8;arr[kind]=struct.unpack(('<%dd' if bits==64 else '<%df')%(len(raw)//per),raw)
    if 'mz' not in arr:return None
    pk=list(zip(arr['mz'],arr.get('int',[1.0]*len(arr['mz']))))
    pk.sort();return pk
class Idx:
    def __init__(s,p):
        s.f=open(p,'rb');s.f.seek(0,2);s.size=s.f.tell();s.f.seek(s.size-4000)
        o=int(re.search(r'<indexListOffset>(\d+)',s.f.read().decode('ascii','ignore')).group(1))
        s.f.seek(o);idx=s.f.read(s.size-o).decode('ascii','ignore')
        s.off={a:int(b) for a,b in re.findall(r'<offset idRef="([^"]+)">(\d+)</offset>',idx)}
    def pk(s,sid):
        o=s.off.get(sid)
        if o is None:return None
        s.f.seek(o);buf=s.f.read(300000);e=buf.find(b'</spectrum>')
        while e<0:
            m=s.f.read(300000)
            if not m:break
            buf+=m;e=buf.find(b'</spectrum>')
        return decode(buf[:e].decode('ascii','ignore'))
def seq_collect(path,needed):
    out={};buf=b''
    f=open(path,'rb');START=re.compile(rb'<spectrum [^>]*id="([^"]+)"')
    while True:
        ch=f.read(8<<20)
        if not ch:break
        buf+=ch
        while True:
            si=buf.find(b'<spectrum ')
            if si<0:
                if len(buf)>1<<20:buf=buf[-1000:]
                break
            ei=buf.find(b'</spectrum>',si)
            if ei<0:
                buf=buf[si:];break
            blk=buf[si:ei+11];buf=buf[ei+11:]
            m=START.search(blk)
            if m and m.group(1).decode() in needed:out[m.group(1).decode()]=decode(blk.decode('ascii','ignore'))
    return out
def covf(pk,ions,off=0.0):
    if not pk:return 0.0
    mz=[p[0] for p in pk];h=0
    for ion in ions:
        t=ion*FRAG_PPM*1e-6;k=bisect.bisect_left(mz,ion+off-t)
        if k<len(mz) and mz[k]<=ion+off+t:h+=1
    return h/len(ions)
def top150(pk):
    return sorted(sorted(pk,key=lambda x:-x[1])[:150])
def deisotope(pk):  # collapse peaks that have a more-intense peak ISO/z lower (z=1,2) within 12 ppm
    if not pk:return pk
    mz=[p[0] for p in pk];keep=[]
    for i,(m,inten) in enumerate(pk):
        iso=False
        for z in (1,2):
            lo=m-ISO/z; t=lo*12e-6
            k=bisect.bisect_left(mz,lo-t)
            while k<len(mz) and mz[k]<=lo+t:
                if pk[k][1]>=inten*0.5: iso=True;break
                k+=1
            if iso:break
        if not iso:keep.append((m,inten))
    return keep
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
ours=best(DET4_TSV);dt=best(DT_TSV)
MISS={p:v for p,v in dt.items() if p not in ours}
det=Idx(DET4_MZML)
CM=[]
for i,line in enumerate(open(COORDS)):
    a=line.split("\t");CM.append((float(a[0]),int(a[1]) if a[1] and a[1]!='0' else 0,float(a[2]),float(a[3]),i))
CM.sort();cmz=[c[0] for c in CM]
def near(mz,rt,win):
    tol=mz*20e-6;lo=bisect.bisect_left(cmz,mz-tol);hi=bisect.bisect_right(cmz,mz+tol)
    return [CM[k] for k in range(lo,hi) if abs(CM[k][2]-rt)<=win]
need={dt[p]["scan"] for p in MISS}
print(f"[dt seq-decode] {len(need)} spectra ...",flush=True)
dtpk=seq_collect(DT_MZML,need)
# analysis on MISS with our right-mass BEST member
raw_o=[];raw_d=[];t150_o=[];t150_d=[];dei_o=[];dei_d=[];dfloor=[];freed=[]
for p,v in MISS.items():
    res,nt=parse(p);calc=v["calc"];z=v["z"];rt=v["rt"]*60.0;mzp=(calc+z*PROTON)/z
    cand=[c for c in near(mzp,rt,30.0) if c[1]==z and abs(c[0]*z-z*PROTON-calc)<0.05]
    if not cand:continue
    ions=by_ions(res,nt,min(2,z))
    # best-member = our candidate spectrum with highest raw coverage (oracle upper bound)
    ospk=None;bc=-1
    for c in cand:
        pk=det.pk(f"spectrum={c[4]}")
        cc=covf(pk,ions)
        if cc>bc:bc=cc;ospk=pk
    dpk=dtpk.get(v["scan"])
    if ospk is None or not dpk:continue
    raw_o.append(covf(ospk,ions));raw_d.append(covf(dpk,ions))
    t150_o.append(covf(top150(ospk),ions));t150_d.append(covf(top150(dpk),ions))
    od=deisotope(ospk);dd=deisotope(dpk)
    dei_o.append(covf(od,ions));dei_d.append(covf(dd,ions))
    dfloor.append(covf(dpk,ions,off=13.0))
    freed.append(1-len(od)/max(len(ospk),1))
def m(x):return st.median(x) if x else float('nan')
n=len(raw_o)
print(f"\n=== DE-CONFOUNDED (MISS, our BEST-member spectrum, n={n}) ===")
print(f"{'metric':22s} {'OURS':>8} {'diaTracer':>10} {'dt-decoy-floor':>14}")
print(f"{'raw-500 coverage':22s} {m(raw_o):8.3f} {m(raw_d):10.3f} {m(dfloor):14.3f}")
print(f"{'top-150 coverage':22s} {m(t150_o):8.3f} {m(t150_d):10.3f}   (what Sage scores)")
print(f"{'deisotoped coverage':22s} {m(dei_o):8.3f} {m(dei_d):10.3f}   (fix #1 projection)")
print(f"median cap slots freed by our deisotoping: {m(freed):.1%}")
print(f"floor-subtracted gap raw:  ours {m(raw_o)-m(dfloor):.3f} vs dt {m(raw_d)-m(dfloor):.3f}")
