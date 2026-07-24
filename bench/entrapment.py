#!/usr/bin/env python3
"""Entrapment FDR across arms -- the measurement this project has never made.

WHY THIS EXISTS. Every "1% FDR" number quoted in this project, ours and diaTracer's, is NOMINAL:
it is Sage's target-decoy estimate computed from ITS OWN decoys, per run. All three adversarial
reviewers (codex, vibe, kimi) independently made the same point, and `bench/fdrcheck.py` then
confirmed it on data already on disk: the min_correlation sweep's "+7.7% peptides" was the q<=0.01
SCORE THRESHOLD sliding down as decoys were deleted, not new signal. A nominal FDR cannot detect
that, because the thing that moved IS the nominal FDR's own calibration.

Entrapment measures the ERROR RATE DIRECTLY. A foreign proteome is concatenated to the human
target database; the sample is human liver, so ANY peptide identified from the foreign proteome is
a known false positive, counted rather than modelled. This is the accepted validation when the
search space or the scoring changes (Wen, Freestone, Noble, Kall, Nesvizhskii, Nat Methods 2025).

WHAT IT SETTLES. Run over the min_correlation arms it answers, without ambiguity:
  * does the observed error rate at nominal 1% RISE as the gate tightens?  -> the gain was
    recalibration, and the nominal axis everyone optimised is not 1%
  * does it stay flat while peptides rise?                                 -> the gain is real
It equally applies to the diaTracer arm, which bounds how much of the 3,036-peptide "coverage gap"
is diaTracer's own FDR edge rather than peptides we genuinely lose.

ESTIMATOR. With target and entrapment databases of comparable size an incorrect match is equally
likely to land in either, so FP ~ 2 x n_entrap and FDR ~ 2 * n_entrap / n_total. `--ratio` corrects
for unequal database sizes. Both the RAW entrapment fraction and the corrected FDR are printed --
never the corrected number alone, because the correction embeds the equal-likelihood assumption
and that assumption is exactly what a reader should be able to check.
"""
import argparse, csv, os, subprocess, sys, json
from pathlib import Path


def build_entrapment(target_fa, foreign_fa, out_fa, tag="ENTRAP_"):
    """Concatenate a foreign proteome, prefixing every foreign accession."""
    n_t = n_e = 0
    with open(out_fa, "w") as out:
        with open(target_fa) as f:
            for line in f:
                if line.startswith(">"):
                    n_t += 1
                out.write(line)
        with open(foreign_fa) as f:
            for line in f:
                if line.startswith(">"):
                    n_e += 1
                    out.write(">" + tag + line[1:])
                else:
                    out.write(line)
    return n_t, n_e


def score(tsv, tag, ratio, q_field="peptide_q", q_cut=0.01):
    """Observed entrapment rate among peptides accepted at NOMINAL q_cut."""
    best = {}
    with open(tsv) as f:
        for x in csv.DictReader(f, delimiter="\t"):
            try:
                s = float(x["sage_discriminant_score"])
                q = float(x[q_field])
                prots = [p for p in x["proteins"].split(";") if p]
            except (ValueError, KeyError):
                continue
            if not prots or all(p.startswith("rev_") for p in prots):
                continue                      # decoys are Sage's model, not our measurement
            pep = x["peptide"]
            if pep not in best or s > best[pep][0]:
                # entrapment iff EVERY protein is foreign; a peptide shared with a human protein
                # is not evidence of error (shared tryptic peptides exist between proteomes)
                ent = all(p.startswith(tag) or p.startswith("rev_" + tag) for p in prots)
                best[pep] = (s, q, ent)
    acc = [(s, q, e) for s, q, e in best.values() if q <= q_cut]
    n_e = sum(1 for _, _, e in acc if e)
    n_t = len(acc) - n_e
    raw = 100.0 * n_e / max(len(acc), 1)
    fdr = 100.0 * (n_e / ratio) * 2.0 / max(len(acc), 1) if ratio > 0 else float("nan")
    return len(acc), n_t, n_e, raw, fdr


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="human FASTA (targets only, no decoys)")
    ap.add_argument("--foreign", required=True, help="foreign proteome FASTA (entrapment)")
    ap.add_argument("--sage", required=True, help="sage binary")
    ap.add_argument("--config", required=True, help="sage config json (its fasta is overridden)")
    ap.add_argument("--out", required=True, help="working dir for the entrapment FASTA + results")
    ap.add_argument("--arm", action="append", required=True, metavar="NAME=DIR",
                    help="arm name and the directory holding its pseudo.mzML (repeatable)")
    ap.add_argument("--tag", default="ENTRAP_")
    ap.add_argument("--q-cut", type=float, default=0.01)
    a = ap.parse_args()

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    fa = out / "target_entrap.fasta"
    if not fa.exists():
        n_t, n_e = build_entrapment(a.target, a.foreign, fa, a.tag)
        print("[db] %d target + %d entrapment proteins -> %s" % (n_t, n_e, fa), flush=True)
    else:
        n_t = sum(1 for l in open(a.target) if l.startswith(">"))
        n_e = sum(1 for l in open(a.foreign) if l.startswith(">"))
        print("[db] reusing %s (%d target + %d entrapment)" % (fa, n_t, n_e), flush=True)
    ratio = n_e / max(n_t, 1)
    print("[db] entrapment/target protein ratio %.3f" % ratio, flush=True)

    cfg = json.load(open(a.config))
    cfg["database"]["fasta"] = str(fa)
    cfg_path = out / "sage_entrap.json"
    json.dump(cfg, open(cfg_path, "w"), indent=2)

    rows = []
    for spec in a.arm:
        name, d = spec.split("=", 1)
        mzml = Path(d) / "pseudo.mzML"
        if not mzml.exists():
            # diaTracer and other reference arms are a bare mzML path, not a run directory
            mzml = Path(d)
        if not mzml.exists():
            print("[skip] %s: no mzML at %s" % (name, d)); continue
        odir = out / name; odir.mkdir(exist_ok=True)
        tsv = odir / "results.sage.tsv"
        if not tsv.exists():
            print("[run] %s ..." % name, flush=True)
            subprocess.run([a.sage, str(cfg_path), "-o", str(odir),
                            "--disable-telemetry-i-dont-want-to-improve-sage", str(mzml)],
                           stdout=open(odir / "sage.log", "w"), stderr=subprocess.STDOUT)
        if not tsv.exists():
            print("[fail] %s: sage produced no tsv" % name); continue
        rows.append((name,) + score(str(tsv), a.tag, ratio, q_cut=a.q_cut))

    print("\n=== ENTRAPMENT FDR at nominal peptide_q <= %.3f ===" % a.q_cut)
    print("%-10s %10s %10s %9s %12s %12s" % ("arm", "accepted", "target", "entrap",
                                             "raw entrap%", "est. FDR%"))
    for n, tot, nt, ne, raw, fdr in rows:
        print("%-10s %10d %10d %9d %11.2f%% %11.2f%%" % (n, tot, nt, ne, raw, fdr))
    print("\nREAD: nominal FDR is 1%% BY CONSTRUCTION in every row -- that is the point. If est. FDR%%")
    print("      RISES as the gate tightens, the extra peptides are errors and the 'gain' was")
    print("      recalibration. If it stays flat while accepted counts rise, the gain is real.")


if __name__ == "__main__":
    sys.exit(main())
