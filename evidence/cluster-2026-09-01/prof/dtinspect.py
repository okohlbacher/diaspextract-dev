import base64,struct,csv,bisect,re,zlib
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
            (res.__setitem__(-1,res[-1]+v) if res else None)
            if not res: nt+=v
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
# raw block dump for a dt spectrum
f=open("/scratch/kohlbach/dt_s30/patched.mzML","rb");f.seek(0,2);size=f.tell();f.seek(size-4000)
off=int(re.search(r'<indexListOffset>(\d+)',f.read().decode('ascii','ignore')).group(1))
f.seek(off);idx=f.read(size-off).decode('ascii','ignore')
offs={a:int(b) for a,b in re.findall(r'<offset idRef="([^"]+)">(\d+)</offset>',idx)}
# pick a SHARED peptide's dt scan
dt={}
for x in csv.DictReader(open("/scratch/kohlbach/dt_s30/results.sage.tsv"),delimiter="\t"):
    if x["label"]!="1" or float(x["peptide_q"])>0.01:continue
    dt[x["peptide"]]=x
ourpep=set()
for x in csv.DictReader(open("/scratch/kohlbach/prof/det4/results.sage.tsv"),delimiter="\t"):
    if x["label"]!="1" or float(x["peptide_q"])>0.01:continue
    ourpep.add(x["peptide"])
p=next(pp for pp in dt if pp in ourpep and float(dt[pp]["matched_peaks"])>15)
x=dt[p];sid=x["scannr"]
print("peptide",p,"z",x["charge"],"scan",sid,"Sage matched_peaks",x["matched_peaks"],"frag_ppm",x.get("fragment_ppm"))
o=offs[sid];f.seek(o);buf=f.read(400000);e=buf.find(b'</spectrum>')
block=buf[:e].decode('ascii','ignore')
print("--- binaryDataArray cvParams (headers only) ---")
for bda in re.finditer(r'<binaryDataArray.*?</binaryDataArray>',block,re.S):
    b=bda.group(0);hdr=b[:b.find('<binary>')]
    names=re.findall(r'name="([^"]+)"',hdr)
    print("  arrays:",names)
    bits=64 if '64-bit float' in hdr else 32;comp=('MS:1000574' in hdr) or ('zlib compression' in hdr)
    mm=re.search(r'<binary>([A-Za-z0-9+/=\s]*)</binary>',b);raw=base64.b64decode(''.join(mm.group(1).split()))
    if comp:raw=zlib.decompress(raw)
    per=bits//8;vals=struct.unpack(('<%dd' if bits==64 else '<%df')%(len(raw)//per),raw)
    print(f"    bits={bits} comp={comp} n={len(vals)} min={min(vals):.3f} max={max(vals):.3f} first5={[round(v,3) for v in vals[:5]]}")
    if 'm/z array' in names:
        mz=sorted(vals);ions=by_ions(*parse(p),min(2,int(x["charge"])))
        h=0
        for ion in ions:
            t=ion*FRAG_PPM*1e-6;k=bisect.bisect_left(mz,ion-t)
            if k<len(mz) and mz[k]<=ion+t:h+=1
        print(f"    -> my b/y match: {h}/{len(ions)} (Sage said matched_peaks={x['matched_peaks']})")
