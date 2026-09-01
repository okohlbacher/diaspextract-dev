#!/usr/bin/env python3
# Refined subtraction test (apex-assignment). For each peak in our target spectrum S (precursor A at
# RT_A), reconstruct its pseudo-XIC across neighbouring same-mobility spectra and find its APEX RT.
# A peak belongs to A iff its apex is at RT_A; a peak apexing elsewhere is an interferent bleeding
# into A and should be removed. Decisive: do TRUE b/y ions apex at RT_A while OTHER (interferent)
# peaks apex elsewhere? Then does keeping only apex-aligned peaks raise our top-150 coverage?
import base64,struct,csv,sys,bisect,re,zlib,statistics as st
DET4_MZML="/scratch/kohlbach/prof/det4/pseudo.mzML";DET4_TSV="/scratch/kohlbach/prof/det4/results.sage.tsv"
DT_TSV="/scratch/kohlbach/dt_s30/results.sage.tsv";COORDS="/scratch/kohlbach/prof/det4/precursor_coords.tsv"
FRAG_PPM=25.0;PROTON=1.00727646;H2O=18.0105646;CYCLE=1.385
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
def by_ions(res,nt,mz):
    ions=[];n=len(res);cb=nt
    for k in range(n-1):
        cb+=res[k]
        for z in range(1,mz+1):ions.append((cb+z*PROTON)/z)
    cy=H2O
    for k in range(n-1):
        cy+=res[n-1-k]
        for z in range(1,mz+1):ions.append((cy+z*PROTON)/z)
    return sorted(ions)
def decode(block):
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
    return sorted(zip(arr['mz'],arr.get('int',[1.0]*len(arr['mz']))))
class Idx:
    def __init__(s,p):
        s.f=open(p,'rb');s.f.seek(0,2);s.size=s.f.tell();s.f.seek(s.size-4000)
        o=int(re.search(r'<indexListOffset>(\d+)',s.f.read().decode('ascii','ignore')).group(1))
        s.f.seek(o);idx=s.f.read(s.size-o).decode('ascii','ignore')
        s.off={a:int(b) for a,b in re.findall(r'<offset idRef="([^"]+)">(\d+)</offset>',idx)}
    def pk(s,i):
        o=s.off.get(f"spectrum={i}")
        if o is None:return None
        s.f.seek(o);buf=s.f.read(300000);e=buf.find(b'</spectrum>')
        while e<0:
            m=s.f.read(300000)
            if not m:break
            buf+=m;e=buf.find(b'</spectrum>')
        return decode(buf[:e].decode('ascii','ignore'))
def best(tsv):
    b={}
    for x in csv.DictReader(open(tsv),delimiter="\t"):
        if x["label"]!="1":continue
        try:
            if float(x["peptide_q"])>0.01:continue
        except:continue
        s=float(x["sage_discriminant_score"]);p=x["peptide"]
        if p in b and b[p]["s"]>=s:continue
        b[p]={"s":s,"z":int(x["charge"]),"calc":float(x["calcmass"]),"rt":float(x["rt"])}
    return b
print("[load]",flush=True)
ours=best(DET4_TSV);dt=best(DT_TSV);MISS={p:v for p,v in dt.items() if p not in ours}
det=Idx(DET4_MZML)
# coords + IM-bin index for neighbour lookup
CM=[]
for i,line in enumerate(open(COORDS)):
    a=line.split("\t");CM.append((float(a[0]),int(a[1]) if a[1] and a[1]!='0' else 0,float(a[2]),float(a[3]),i))
imbin={}
for c in CM:
    imbin.setdefault(round(c[3]/0.01),[]).append((c[2],c[0],c[4]))  # bin-> (rt, mz, idx)
cmz=sorted([c[0] for c in CM])
CM.sort()
def near_mzrt(mz,rt,win):  # our right-mass candidate lookup by mz+rt
    tol=mz*20e-6;lo=bisect.bisect_left(cmz,mz-tol);hi=bisect.bisect_right(cmz,mz+tol)
    out=[]
    for k in range(lo,hi):
        m,z,r,im,idx=CM[k]
        if abs(r-rt)<=win:out.append((m,z,r,im,idx))
    return out
def match(mzl,ion):
    t=ion*FRAG_PPM*1e-6;k=bisect.bisect_left(mzl,ion-t);return k<len(mzl) and mzl[k]<=ion+t
def cov(pk,ions):
    if not pk:return 0.0
    mzl=[p[0] for p in pk];return sum(1 for ion in ions if match(mzl,ion))/len(ions)
def top150(pk):return sorted(sorted(pk,key=lambda x:-x[1])[:150])
def peak_int(pk,m):  # intensity of a peak at m in a decoded spectrum, else 0
    mzl=[p[0] for p in pk];t=m*FRAG_PPM*1e-6;k=bisect.bisect_left(mzl,m-t)
    return pk[k][1] if (k<len(mzl) and mzl[k]<=m+t) else 0.0

al_true=[];al_other=[];raw150=[];apex150=[];falserem=[];cnt=0
for p,v in MISS.items():
    res,nt=parse(p);calc=v["calc"];z=v["z"];rt=v["rt"]*60.0;mzp=(calc+z*PROTON)/z
    cand=[c for c in near_mzrt(mzp,rt,30.0) if c[1]==z and abs(c[0]*z-z*PROTON-calc)<0.05]
    if not cand:continue
    ions=by_ions(res,nt,min(2,z));IM_A=cand[0][3]
    S=None;bc=-1
    for c in cand:
        pk=det.pk(c[4])
        cc=cov(pk,ions)
        if cc>bc:bc=cc;S=pk
    if not S:continue
    # neighbour spectra at same mobility, RT within +-6 cycles -> build fragment pseudo-XICs
    neigh=[]
    for db in (-1,0,1):
        for (r,mz2,idx) in imbin.get(round(IM_A/0.01)+db,[]):
            if abs(r-rt)<=6*CYCLE: neigh.append((r,idx))
    neigh=sorted(set(neigh))[:80]
    npk={idx:det.pk(idx) for (r,idx) in neigh}
    # for each peak in S, apex RT of its pseudo-XIC across neighbours
    keep=[]
    for (m,inten) in S:
        prof=[(r, peak_int(npk[idx],m)) for (r,idx) in neigh if npk.get(idx)]
        if not prof:continue
        apex_rt=max(prof,key=lambda x:x[1])[0]
        aligned = abs(apex_rt-rt)<=1.5*CYCLE
        istrue=any(match([m],ion) for ion in ions)
        (al_true if istrue else al_other).append(1 if aligned else 0)
        if aligned:keep.append((m,inten))
    raw150.append(cov(top150(S),ions));apex150.append(cov(top150(keep),ions))
    tt=sum(1 for ion in ions if match([x[0] for x in S],ion))
    kt=sum(1 for ion in ions if match([x[0] for x in keep],ion))
    if tt:falserem.append((tt-kt)/tt)
    cnt+=1
    if cnt>=400:break
def m(x):return st.median(x) if x else float('nan')
def r(x):return sum(x)/max(len(x),1)
print(f"n MISS analysed: {cnt}")
print(f"\n=== APEX ALIGNMENT: is the peak's pseudo-XIC apex at THIS precursor's RT? ===")
print(f"  TRUE b/y peaks apex-aligned:  {r(al_true):.1%}  (n={len(al_true)})")
print(f"  OTHER (interferent) aligned:  {r(al_other):.1%}  (n={len(al_other)})")
print(f"\n=== TOP-150 coverage after keeping ONLY apex-aligned peaks ===")
print(f"  raw            : {m(raw150):.3f}")
print(f"  apex-filtered  : {m(apex150):.3f}   (diaTracer top-150 ~0.208; our raw-500 ~0.19)")
print(f"  true-ion false-removal by apex filter: {m(falserem):.3f}")
