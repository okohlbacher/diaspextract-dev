#!/usr/bin/env python3
# Apply the CORRECTED entrapment estimator (peptide ratio + bootstrap CI) to EXISTING entrap TSVs, no re-search.
import sys; sys.path.insert(0, "/scratch/kohlbach/harness"); sys.path.insert(0, "/scratch/kohlbach/prof")
from entrapment import peptide_ratio, score
fa = "/scratch/kohlbach/bench/human_entrap.fasta"
r = peptide_ratio(fa)
print(f"peptide-hypothesis ratio = {r:.4f} (1/r = {1/r:.3f})\n")
print(f"{'arm':14s} {'target':>7s} {'entrap':>6s} {'raw%':>6s} {'FDR%':>6s} {'FDR 95% CI':>16s}")
for spec in sys.argv[1:]:
    name, tsv = spec.split("=", 1)
    try:
        tot, nt, ne, raw, fdr, lo, hi = score(tsv, "ENTRAP_", r)
        print(f"{name:14s} {nt:7d} {ne:6d} {raw:5.2f}% {fdr:5.2f}% {lo:6.2f}-{hi:.2f}%")
    except Exception as e:
        print(f"{name:14s} ERR {e}")
