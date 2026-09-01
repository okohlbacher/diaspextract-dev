import csv, re
PROTON=1.00727646; H2O=18.0105646
AA={'G':57.02146,'A':71.03711,'S':87.03203,'P':97.05276,'V':99.06841,'T':101.04768,
    'C':103.00919+57.02146,'L':113.08406,'I':113.08406,'N':114.04293,'D':115.02694,
    'Q':128.05858,'K':128.09496,'E':129.04259,'M':131.04049,'H':137.05891,'F':147.06841,
    'R':156.10111,'Y':163.06333,'W':186.07931}
def parse(pep):
    res=[]; nterm=0.0; i=0
    while i<len(pep):
        ch=pep[i]
        if ch=='[':
            j=pep.index(']',i); val=float(pep[i+1:j].replace('+',''));
            if res: res[-1]+=val
            else: nterm+=val
            i=j+1
        elif ch=='-': i+=1
        elif ch in AA: res.append(AA[ch]); i+=1
        else: i+=1
    return res, nterm
def pmass(res,nt): return sum(res)+H2O+nt
seen=0; mism=0; shown=0; chars=set()
with open("/scratch/kohlbach/dt_s30/results.sage.tsv") as f:
    for x in csv.DictReader(f,delimiter="\t"):
        if x["label"]!="1" or float(x["peptide_q"])>0.01: continue
        p=x["peptide"]; calc=float(x["calcmass"])
        for c in p:
            if c not in AA and c not in "[]+-.0123456789": chars.add(c)
        res,nt=parse(p); my=pmass(res,nt); seen+=1
        if abs(my-calc)>0.02:
            mism+=1
            if shown<12:
                print(f"  MISM my={my:.4f} calc={calc:.4f} diff={my-calc:+.4f}  {p}")
                shown+=1
        if seen>=3000: break
print(f"seen {seen} mismatch {mism}")
print("unexpected chars in peptides:", sorted(chars))
