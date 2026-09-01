#!/usr/bin/env python3
# kimi's decisive test: are the peptides GAINED by reweighting entrapment-ENRICHED (buying yield with
# risk = red flag) or neutral/depleted (borderline-faint recovery = clean)? Compares entrapment fraction
# WITHIN the gained set vs the base rate. Pure post-processing on the entrap TSVs.
import sys, csv
def load(path):
    with open(path) as f:
        h = f.readline().rstrip("\n").split("\t"); ci = {c:i for i,c in enumerate(h)}
    pep_i, prot_i, q_i, lbl_i = ci["peptide"], ci["proteins"], ci["peptide_q"], ci.get("label")
    tgt = {}  # peptide -> is_entrap (best q<=0.01, target strand)
    with open(path) as f:
        r = csv.reader(f, delimiter="\t"); next(r)
        for row in r:
            if lbl_i is not None and row[lbl_i] != "1": continue
            if float(row[q_i]) > 0.01: continue
            pep = row[pep_i]; ent = "ENTRAP_" in row[prot_i]
            tgt[pep] = ent
    return tgt
def frac(s):
    if not s: return 0.0, 0, 0
    e = sum(1 for v in s.values() if v); return 100*e/len(s), e, len(s)
if __name__ == "__main__":
    base = load(sys.argv[1]); arm = load(sys.argv[2]); name = sys.argv[3]
    bf, be, bn = frac(base)
    gained = {p: arm[p] for p in arm if p not in base}
    lost   = {p: base[p] for p in base if p not in arm}
    gf, ge, gn = frac(gained); lf, le, ln = frac(lost)
    print(f"{name}: base rate {bf:.2f}% ({be}/{bn}) | GAINED {gf:.2f}% ({ge}/{gn}) | lost {lf:.2f}% ({le}/{ln}) | net {gn-ln:+d}")
    verdict = "RED FLAG (gained entrap-enriched)" if gf > bf*1.5 else ("CLEAN (gained not enriched)" if gf <= bf*1.15 else "borderline")
    print(f"   -> {verdict}")
