import json, csv, itertools
c=json.load(open("/scratch/kohlbach/bench/sage_deiso.json"))["database"]
print("static_mods:", c.get("static_mods"))
print("variable_mods:", c.get("variable_mods"))
print("decoy_tag:", c.get("decoy_tag"), " generate_decoys:", c.get("generate_decoys"))
print("--- sample identified peptides (seq, z, calcmass, expmass) ---")
with open("/scratch/kohlbach/dt_s30/results.sage.tsv") as f:
    rd=csv.DictReader(f, delimiter="\t"); n=0
    for x in rd:
        if x["label"]!="1" or float(x["peptide_q"])>0.01: continue
        print(f"  {x['peptide']:35s} z={x['charge']} calcmass={x['calcmass']} expmass={x['expmass']}")
        n+=1
        if n>=6: break
# encoding of our mzML binaryDataArray
print("--- our mzML binary encoding (first 2 binaryDataArray cvParams) ---")
import re
buf=[]; c2=0
with open("/scratch/kohlbach/prof/det4/pseudo.mzML") as f:
    grab=False
    for line in f:
        if "<binaryDataArray" in line: grab=True
        if grab and ("float" in line or "compression" in line or "MS:100052" in line or "MS:1000574" in line):
            m=re.findall(r'name="[^"]*"', line)
            if m: print("   ", m[0])
        if "</binaryDataArray>" in line:
            c2+=1
            if c2>=2: break
