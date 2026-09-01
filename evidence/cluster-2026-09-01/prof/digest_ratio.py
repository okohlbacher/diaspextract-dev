#!/usr/bin/env python3
# Peptide-HYPOTHESIS ratio for the entrapment FDR correction (codex #12: the estimator used the PROTEIN
# ratio, which is wrong -- false matches distribute over the PEPTIDE search space, not proteins). In-silico
# tryptic digest matching Sage: cleave after K/R not before P, <=2 missed cleavages, len 7-35, peptide
# monoisotopic mass 500-5000. target = non-ENTRAP_ entries; entrap = ENTRAP_ entries. A peptide shared with
# any target protein is NOT entrapment (matches entrapment.py's "foreign iff EVERY protein foreign"), so
# the entrapment candidate space = peptides UNIQUE to the foreign proteome.
import sys
AA = {'G':57.02146,'A':71.03711,'S':87.03203,'P':97.05276,'V':99.06841,'T':101.04768,'C':103.00919,
      'L':113.08406,'I':113.08406,'N':114.04293,'D':115.02694,'Q':128.05858,'K':128.09496,'E':129.04259,
      'M':131.04049,'H':137.05891,'F':147.06841,'R':156.10111,'Y':163.06333,'W':186.07931}
H2O = 18.010565
def mass(pep):
    m = H2O
    for a in pep:
        if a not in AA: return -1.0
        m += AA[a]
    return m
def digest(seq, mc=2):
    # cut sites: after K/R unless next is P
    cuts = [0]
    for i in range(len(seq)-1):
        if seq[i] in 'KR' and seq[i+1] != 'P': cuts.append(i+1)
    cuts.append(len(seq))
    peps = set()
    n = len(cuts)-1
    for i in range(n):
        for j in range(i+1, min(i+2+mc, n+1)):
            p = seq[cuts[i]:cuts[j]]
            L = len(p)
            if 7 <= L <= 35:
                m = mass(p)
                if 500.0 <= m <= 5000.0:
                    peps.add(p)
    return peps
def read(path):
    tgt, ent = set(), set()
    acc_ent = False; seq = []
    def flush():
        if seq:
            s = "".join(seq)
            (ent if acc_ent else tgt).update(digest(s))
    with open(path) as f:
        for line in f:
            if line.startswith(">"):
                flush(); seq = []
                acc_ent = line[1:].startswith("ENTRAP_")
            else:
                seq.append(line.strip())
        flush()
    return tgt, ent
if __name__ == "__main__":
    tgt, ent = read(sys.argv[1])
    ent_only = ent - tgt          # foreign-unique = entrapment candidate space
    shared = len(ent & tgt)
    r_pep = len(ent_only) / max(len(tgt), 1)
    print(f"target peptides:        {len(tgt)}")
    print(f"entrapment peptides:    {len(ent)}  (foreign-unique {len(ent_only)}, shared-with-target {shared})")
    print(f"PEPTIDE-hypothesis ratio (foreign-unique/target): {r_pep:.4f}")
    print(f"  (protein ratio was 0.800; FDR correction factor 1/ratio = {1/r_pep:.3f} vs protein 1.250)")
