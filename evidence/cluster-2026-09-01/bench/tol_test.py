import json,subprocess,csv,os
SAGE="/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage"
BASE=json.load(open("/scratch/kohlbach/bench/sage.json"))
MZML="/scratch/kohlbach/bench/out/snr1_n10/pseudo.mzML"
OUT="/scratch/kohlbach/bench/toltest"; os.makedirs(OUT,exist_ok=True)
# our frag median +9, prec +5.7. Test recentering + widening + deiso (the confirmed win).
V={
 "base":{},
 "deiso":{"deisotope":True},
 "frecenter_deiso":{"deisotope":True,"fragment_tol":{"ppm":[-2.0,20.0]},"precursor_tol":{"ppm":[-10.0,20.0]}},
 "fwide_deiso":{"deisotope":True,"fragment_tol":{"ppm":[-30.0,30.0]},"precursor_tol":{"ppm":[-30.0,30.0]}},
 "frecenter2_deiso":{"deisotope":True,"fragment_tol":{"ppm":[0.0,20.0]},"precursor_tol":{"ppm":[-5.0,20.0]}},
 "both_shift_deiso":{"deisotope":True,"fragment_tol":{"ppm":[-11.0,29.0]},"precursor_tol":{"ppm":[-14.0,26.0]}},
}
def peps(f):
    if not os.path.exists(f): return None
    q=[x for x in csv.DictReader(open(f),delimiter="\t") if float(x.get("spectrum_q","1"))<=0.01]
    pe=set(x["peptide"] for x in q);pr=set(p for x in q for p in x.get("proteins","").split(";") if p and not p.startswith("rev_"))
    return len(q),len(pe),len(pr)
res=[]
for n,patch in V.items():
    c=json.loads(json.dumps(BASE)); c.update(patch)
    od=OUT+"/"+n; os.makedirs(od,exist_ok=True); json.dump(c,open(od+"/s.json","w"))
    subprocess.run([SAGE,od+"/s.json","-o",od,"--disable-telemetry-i-dont-want-to-improve-sage",MZML],capture_output=True)
    r=peps(od+"/results.sage.tsv")
    if r: res.append((n,)+r); print("%-20s PSMs=%d PEPTIDES=%d proteins=%d"%(n,r[0],r[1],r[2]),flush=True)
print("\n=== vs base ===")
b=dict((x[0],x[2]) for x in res).get("base",0)
for n,ps,pe,pr in sorted(res,key=lambda x:-x[2]): print("%-20s %+d peptides"%(n,pe-b))
