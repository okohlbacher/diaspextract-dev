#!/usr/bin/env python3
# Count target(human) peptides at a COMMON empirical entrapment FDR (codex's endpoint), instead of at
# each arm's own nominal 1% peptide_q. Empirical FDR = entrap/(target+entrap) among peptides ranked by
# peptide_q. Finds max target count with empirical FDR <= threshold. Peptide-level (best q per sequence).
import sys, csv
def cols(path):
    with open(path) as f:
        h = f.readline().rstrip("\n").split("\t")
    return {c:i for i,c in enumerate(h)}
def load(path):
    ci = cols(path)
    pep_i = ci.get("peptide"); prot_i = ci.get("proteins"); q_i = ci.get("peptide_q"); lbl_i = ci.get("label")
    best = {}  # peptide -> (q, is_entrap)
    with open(path) as f:
        r = csv.reader(f, delimiter="\t"); next(r)
        for row in r:
            if lbl_i is not None and row[lbl_i] != "1": continue   # target strand only
            pep = row[pep_i]; q = float(row[q_i]); ent = "ENTRAP_" in row[prot_i]
            if pep not in best or q < best[pep][0]: best[pep] = (q, ent)
    return sorted(best.values())   # by q asc
def count_at(vals, thr):
    t = e = 0; bestT = 0
    for q, ent in vals:
        if ent: e += 1
        else: t += 1
        fdr = e/(t+e) if (t+e) else 0
        if fdr <= thr: bestT = t
    return bestT
if __name__ == "__main__":
    thr = float(sys.argv[1]);
    print(f"target(human) peptides at empirical entrapment FDR <= {thr:.1%}:")
    for name, path in (a.split("=") for a in sys.argv[2:]):
        try:
            v = load(path); print(f"  {name:10s} {count_at(v, thr)}   (peptides ranked {len(v)})")
        except Exception as ex:
            print(f"  {name:10s} ERR {ex}")
