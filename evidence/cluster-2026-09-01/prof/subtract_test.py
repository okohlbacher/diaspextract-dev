#!/usr/bin/env python3
# Explore SUBTRACTING adjacent (same-cycle, different-precursor) spectra to remove shared interferents.
# Decisive question: do TRUE b/y ions have LOWER neighbour-sharing than the OTHER (interferent) peaks?
# If yes, subtracting high-sharing peaks purifies; then does our top-150 coverage rise toward diaTracer?
# Controls: random-removal baseline + true-ion false-removal rate.
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
ours=best(DET4_TSV);dt=best(DT_TSV);MISS={p:v for p,v in dt.items() if p not in ours}
det=Idx(DET4_MZML)
CM=[]
for i,line in enumerate(open(COORDS)):
    a=line.split("\t");CM.append((float(a[0]),int(a[1]) if a[1] and a[1]!='0' else 0,float(a[2]),float(a[3]),i))
CM.sort();cmz=[c[0] for c in CM]
def near(mz,rt,win):
    tol=mz*20e-6;lo=bisect.bisect_left(cmz,mz-tol);hi=bisect.bisect_right(cmz,mz+tol)
    return [CM[k] for k in range(lo,hi) if abs(CM[k][2]-rt)<=win]
def match(mzl,ion):
    t=ion*FRAG_PPM*1e-6;k=bisect.bisect_left(mzl,ion-t);return k<len(mzl) and mzl[k]<=ion+t
def cov(pk,ions):
    if not pk:return 0.0
    mzl=[p[0] for p in pk];return sum(1 for ion in ions if match(mzl,ion))/len(ions)
def top150(pk):return sorted(sorted(pk,key=lambda x:-x[1])[:150])

sh_true=[];sh_other=[];raw150=[];sub150=[];rnd150=[];raw500=[];falserem=[]
import itertools
cnt=0
for p,v in MISS.items():
    res,nt=parse(p);calc=v["calc"];z=v["z"];rt=v["rt"]*60.0;mzp=(calc+z*PROTON)/z
    cand=[c for c in near(mzp,rt,30.0) if c[1]==z and abs(c[0]*z-z*PROTON-calc)<0.05]
    if not cand:continue
    ions=by_ions(res,nt,min(2,z))
    # best-member (highest raw coverage)
    S=None;bc=-1;bi=None
    for c in cand:
        pk=det.pk(c[4])
        cc=cov(pk,ions)
        if cc>bc:bc=cc;S=pk;bi=c[4]
    if not S:continue
    # same-cycle, different-precursor neighbours (co-isolators) for the sharing background
    nb=[c for c in near(mzp,rt,0.7) if c[4]!=bi]
    nbpk=[]
    for c in nb[:12]:
        q=det.pk(c[4])
        if q:nbpk.append([x[0] for x in q])
    if not nbpk:continue
    # per-peak sharing count among neighbours
    def sharing(m):
        s=0
        for mzl in nbpk:
            if match(mzl,m):s+=1
        return s
    truem=set()
    for i,(m,inten) in enumerate(S):
        sc=sharing(m)
        istrue=any(match([m],ion) for ion in ions)
        (sh_true if istrue else sh_other).append(sc)
        if istrue:truem.add(i)
    # subtract peaks shared in >=2 neighbours
    Ssub=[(m,inten) for (m,inten) in S if sharing(m)<2]
    # false removal of true ions
    remtrue=sum(1 for i,(m,inten) in enumerate(S) if sharing(m)>=2 and any(match([m],ion) for ion in ions))
    tt=sum(1 for ion in ions if match([x[0] for x in S],ion))
    if tt:falserem.append(remtrue/tt)
    # random removal control: drop same number of random peaks
    ndrop=len(S)-len(Ssub)
    import hashlib
    seed=int(hashlib.md5(p.encode()).hexdigest(),16)
    keepidx=sorted(range(len(S)),key=lambda i:(seed*(i+1))%97)[:len(S)-ndrop]
    Srnd=[S[i] for i in sorted(keepidx)]
    raw150.append(cov(top150(S),ions));sub150.append(cov(top150(Ssub),ions));rnd150.append(cov(top150(Srnd),ions))
    raw500.append(cov(S,ions))
    cnt+=1
    if cnt>=1200:break
def m(x):return st.median(x) if x else float('nan')
print(f"n MISS analysed: {cnt}")
print(f"\n=== DISCRIMINATION: neighbour-sharing of TRUE b/y peaks vs OTHER (interferent) peaks ===")
print(f"  TRUE  peaks: median sharing {m(sh_true):.2f}  mean {sum(sh_true)/max(len(sh_true),1):.2f}  (n={len(sh_true)})")
print(f"  OTHER peaks: median sharing {m(sh_other):.2f}  mean {sum(sh_other)/max(len(sh_other),1):.2f}  (n={len(sh_other)})")
frac_true_shared=sum(1 for s in sh_true if s>=2)/max(len(sh_true),1)
frac_other_shared=sum(1 for s in sh_other if s>=2)/max(len(sh_other),1)
print(f"  fraction shared(>=2 neighbours): TRUE {frac_true_shared:.1%}  OTHER {frac_other_shared:.1%}")
print(f"\n=== TOP-150 coverage (what Sage scores) ===")
print(f"  raw (no subtraction) : {m(raw150):.3f}")
print(f"  after SUBTRACT(>=2)  : {m(sub150):.3f}   [random-removal control: {m(rnd150):.3f}]")
print(f"  (reference: raw-500 {m(raw500):.3f}; diaTracer top-150 ~0.208)")
print(f"  true-ion false-removal rate by subtraction: {m(falserem):.3f}")
