#!/usr/bin/env python3
# Peptide-level target-decoy FDR on raw MSFragger tsv (lowercase cols). Best hyperscore per distinct
# (peptide + mods), sort desc, walk, accept the deepest set with decoy/target <= 1%. Decoy = every
# protein carries the rev_ prefix. Same procedure for baseline and gated => the delta is valid.
import csv, sys
def score(tsv):
    best={}
    sample=None
    with open(tsv) as f:
        rd=csv.DictReader(f, delimiter='\t')
        for x in rd:
            key=x['peptide']+'|'+(x.get('modification_info') or '')
            try: sc=float(x['hyperscore'])
            except (KeyError,ValueError): continue
            prot=(x.get('proteins') or '')
            if sample is None: sample=prot
            # MSFragger tsv `proteins` = primary protein header (e.g. "rev_sp|..|.. decoy").
            # Decoy = the field starts with the rev_ prefix.
            dec = prot.lstrip().startswith('rev_')
            if key not in best or sc>best[key][0]:
                best[key]=(sc,dec)
    rows=sorted(best.values(), key=lambda r:-r[0])
    nt=nd=0; acc=0
    for sc,dec in rows:
        if dec: nd+=1
        else:   nt+=1
        if nt>0 and nd/nt<=0.01: acc=nt
    return acc, len(rows), sample

for name,tsv in [("baseline",sys.argv[1]),("gated",sys.argv[2])]:
    pep,total,samp=score(tsv)
    print(f"{name:9s}: {pep} target peptides @1% FDR   (distinct pep+mod keys: {total})   proteins-sample: {samp[:60]}")
