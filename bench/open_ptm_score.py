#!/usr/bin/env python3
"""Delta-mass-BIN-level, entrapment-controlled scoring of open-search output — the metric the
2026-09-01 review demanded (red-team: 'the flagship number is denominated in a debased currency').

A target-peptide count treats a -1.003 Da isotope miscall as a discovery; PTM-site discovery is the
tool's raison d'etre. This scorer assigns every rank-1 PSM's delta = expmass - calcmass to a bin and
scores each CLASS separately with the corrected entrapment estimator (peptide-hypothesis ratio +
class-level empirical FDR walk):
  unmod     |delta| <= tol                      (not a PTM discovery; reported separately)
  artifact  +-k * 1.0033548, k=1..3             (phantom-mod load; LOWER is better)
  known     curated Unimod-common list          (real PTM discoveries)
  other     any other delta (rounded-Da label)  (novel/unknown mass shifts -- open search's point)
Discovery unit: (peptide, bin). Reports targets at a matched empirical-FDR grid, per class, plus the
top bins. The deamidation (+0.9840) vs iso+1 (+1.0034) pair is 19 mDa apart -- separable only while
precursor mass error << 19 mDa; both bins are reported explicitly so the ambiguity is visible.
"""
import sys, os, csv, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entrapment import peptide_ratio

ISO = 1.0033548
KNOWN = [  # (delta, name) — curated common Unimod deltas
    (15.9949, "Oxidation"), (31.9898, "Dioxidation"), (47.9847, "Trioxidation"),
    (42.0106, "Acetyl"), (79.9663, "Phospho"), (0.9840, "Deamidation"),
    (14.0157, "Methyl"), (28.0313, "Dimethyl"), (42.0470, "Trimethyl"),
    (27.9949, "Formyl"), (43.0058, "Carbamyl"), (57.0215, "Carbamidomethyl(offtarget)"),
    (-17.0265, "PyroGlu(Q)"), (-18.0106, "Dehydration/PyroGlu(E)"), (-2.0157, "Didehydro"),
    (21.9819, "Cation:Na"), (37.9559, "Cation:K"), (114.0429, "GG(ubiquitin)"),
    (119.0041, "Cysteinylation"), (105.0578, "?105"), (100.0160, "Succinyl"),
    (26.0157, "Acetaldehyde"), (52.9115, "Cation:Fe"), (12.0000, "Formaldehyde-adduct(+CH0?)"),
    (-48.0034, "Met->Ala/loss"), (203.0794, "HexNAc"),
]
def classify(d, tol):
    if abs(d) <= tol: return ("unmod", "0")
    # [v2] near-zero mass-error tail is NOT a modification and NOT an isotope: its own class.
    if abs(d) < 0.9: return ("nearzero", "masserr")
    # [v2] isotope/envelope grid extended to k=9: the +-4..+-9 integer ladders dominated v1's
    # "other" top bins for both tools -- envelope artifacts, not discoveries.
    for k in range(1, 10):
        for sg in (1, -1):
            if abs(d - sg * k * ISO) <= tol: return ("artifact", f"iso{'+' if sg>0 else '-'}{k}")
    best = min(KNOWN, key=lambda kn: abs(d - kn[0]))
    if abs(d - best[0]) <= tol: return ("known", best[1])
    return ("other", f"{d:+.0f}Da")

def load(tsv, tol, tag="ENTRAP_"):
    best = {}  # (peptide, bin) -> (score, ent, cls)
    with open(tsv) as f:
        for x in csv.DictReader(f, delimiter="\t"):
            try:
                if int(x["rank"]) != 1 or x.get("label") not in (None, "1"): continue
                prots = [p for p in x["proteins"].split(";") if p]
                if not prots or all(p.startswith("rev_") for p in prots): continue
                s = float(x["sage_discriminant_score"])
                d = float(x["expmass"]) - float(x["calcmass"])
            except (ValueError, KeyError):
                continue
            cls, b = classify(d, tol)
            ent = all(p.startswith(tag) or p.startswith("rev_" + tag) for p in prots)
            key = (x["peptide"], b)
            if key not in best or s > best[key][0]: best[key] = (s, ent, cls, b)
    return best

def walk(items, ratio, grid):
    """items: [(score, ent)] one class. Return {fdr: max targets} + curve support counts."""
    items = sorted(items, key=lambda v: -v[0])
    out = {g: 0 for g in grid}; t = e = 0
    for s, ent in items:
        if ent: e += 1
        else: t += 1
        fdr = 100.0 * (e / ratio) / max(t, 1)
        for g in grid:
            if fdr <= g and t > out[g]: out[g] = t
    return out, len(items)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fasta", default="/scratch/kohlbach/bench/human_entrap.fasta")
    ap.add_argument("--tol", type=float, default=0.008)
    ap.add_argument("arms", nargs="+", help="name=tsv")
    a = ap.parse_args()
    r = peptide_ratio(a.fasta)
    grid = (0.5, 1.0, 2.0, 3.0)
    print(f"peptide ratio={r:.4f}  bin tol=+-{a.tol} Da  grid={grid}%\n")
    for spec in a.arms:
        name, tsv = spec.split("=", 1)
        best = load(tsv, a.tol)
        print(f"=== {name} ===  ({len(best)} (peptide,bin) units)")
        for cls in ("unmod", "known", "other", "artifact", "nearzero"):
            items = [(s, e) for (s, e, c, b) in best.values() if c == cls]
            out, n = walk(items, r, grid)
            row = "  ".join(f"@{g}%:{out[g]:>6}" for g in grid)
            print(f"  {cls:9s} {row}   (units {n})")
        # [v2] per-BIN FDR walks for the top bins: pooled class FDR lets junk bins ride the
        # aggregate score distribution; a defensible per-bin discovery count needs a per-bin walk.
        from collections import defaultdict
        binitems = defaultdict(list)
        for (pep, b), (sc, e, c, bb) in best.items():
            if c in ("known", "other"): binitems[f"{c}:{b}"].append((sc, e))
        ranked = sorted(binitems.items(), key=lambda kv: -len(kv[1]))[:18]
        print("  per-bin walks (targets @1% bin-FDR / @2% | units, raw entrap frac):")
        for b, items in ranked:
            out, n = walk(items, r, grid)
            ef = 100.0 * sum(1 for _, e in items if e) / n
            print(f"    {b:28s} @1%:{out[1.0]:>5}  @2%:{out[2.0]:>5}   ({n} units, {ef:.1f}% entrap)")
        print()
