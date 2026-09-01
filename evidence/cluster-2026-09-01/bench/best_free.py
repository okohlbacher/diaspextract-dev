import json,subprocess,csv,os
SAGE="/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage"
BASE=json.load(open("/scratch/kohlbach/bench/sage.json"))
MZML="/scratch/kohlbach/bench/out/snr1_n10/pseudo.mzML"
OUT="/scratch/kohlbach/bench/bestfree"; os.makedirs(OUT,exist_ok=True)
V={
 "base":{},
 "best_20":{"deisotope":True,"isotope_errors":[-1,2]},
 "best_25":{"deisotope":True,"isotope_errors":[-1,2],"fragment_tol":{"ppm":[-25.,25.]},"precursor_tol":{"ppm":[-25.,25.]}},
 "best_30":{"deisotope":True,"isotope_errors":[-1,2],"fragment_tol":{"ppm":[-30.,30.]},"precursor_tol":{"ppm":[-30.,30.]}},
}
def peps(f):
    if not os.path.exists(f): return None
    q=[x for x in csv.DictReader(open(f),delimiter="\t") if float(x.get("spectrum_q","1"))<=0.01]
    pe=set(x["peptide"] for x in q);pr=set(p for x in q for p in x.get("proteins","").split(";") if p and not p.startswith("rev_"))
    return len(q),len(pe),len(pr)
for n,patch in V.items():
    c=json.loads(json.dumps(BASE)); c.update(patch)
    od=OUT+"/"+n; os.makedirs(od,exist_ok=True); json.dump(c,open(od+"/s.json","w"))
    subprocess.run([SAGE,od+"/s.json","-o",od,"--disable-telemetry-i-dont-want-to-improve-sage",MZML],capture_output=True)
    r=peps(od+"/results.sage.tsv")
    if r: print("%-10s PSMs=%d PEPTIDES=%d proteins=%d"%(n,r[0],r[1],r[2]),flush=True)
