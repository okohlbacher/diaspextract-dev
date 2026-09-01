#!/usr/bin/env python3
"""Search-side sweep on EXISTING pseudo-spectra (no re-extraction; Sage = 44 s/run).

Rationale per config:
  charge15      - we assert 1+ on 15.6% and 5+ on 1.6% of spectra, but Sage searches only [2,4]
                  => ~17% of our spectra (168k) may be discarded outright.
  chimera       - our fan-out is 6.45; spectra are demonstrably chimeric, Sage's chimera mode off.
  deisotope     - we never de-isotope MS2, so fragment isotope peaks inflate our ~202 "fragments";
                  Sage deisotope=false means it never collapses them either.
  psms5         - report_psms=1 keeps only the top PSM per spectrum; with chimeric spectra that
                  discards real second-ranked peptides.
  iso_m1        - isotope_errors [-1,2] widens the monoisotope-error rescue (F6) further.
  mmp3          - min_matched_peaks 4 -> 3 (our spectra are sparser than diaTracer's).
  fragchg3      - max_fragment_charge 2 -> 3.
  ftol10        - our fragments were shown accurate; tightening may cut noise matches.
  ptol30        - looser precursor tolerance in case of IM-dependent m/z drift.
"""
import json
import subprocess
import sys
import os
import csv

BASE = "/scratch/kohlbach/bench/sage.json"
MZML = sys.argv[1] if len(sys.argv) > 1 else "/scratch/kohlbach/bench/out/snr1_n10/pseudo.mzML"
SAGE = "/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage"
OUTROOT = "/scratch/kohlbach/bench/sagesweep"

VARIANTS = {
    "base":        {},
    "charge15":    {"precursor_charge": [1, 5]},
    "chimera":     {"chimera": True},
    "deisotope":   {"deisotope": True},
    "psms5":       {"report_psms": 5},
    "iso_m1":      {"isotope_errors": [-1, 2]},
    "mmp3":        {"min_matched_peaks": 3},
    "fragchg3":    {"max_fragment_charge": 3},
    "ftol10":      {"fragment_tol": {"ppm": [-10.0, 10.0]}},
    "ptol30":      {"precursor_tol": {"ppm": [-30.0, 30.0]}},
    # combinations of the individually-plausible ones
    "chim_psms5":  {"chimera": True, "report_psms": 5},
    "chg15_deiso": {"precursor_charge": [1, 5], "deisotope": True},
    "combo":       {"precursor_charge": [1, 5], "chimera": True, "report_psms": 5,
                    "deisotope": True, "isotope_errors": [-1, 2]},
}


def peptides(tsv):
    if not os.path.exists(tsv):
        return None
    q = [x for x in csv.DictReader(open(tsv), delimiter="\t")
         if float(x.get("spectrum_q", "1")) <= 0.01]
    peps = set(x["peptide"] for x in q)
    prot = set(p for x in q for p in x.get("proteins", "").split(";")
               if p and not p.startswith("rev_"))
    return len(q), len(peps), len(prot)


base_cfg = json.load(open(BASE))
os.makedirs(OUTROOT, exist_ok=True)
results = []
for name, patch in VARIANTS.items():
    cfg = json.loads(json.dumps(base_cfg))
    cfg.update(patch)
    od = os.path.join(OUTROOT, name)
    os.makedirs(od, exist_ok=True)
    cfgp = os.path.join(od, "sage.json")
    json.dump(cfg, open(cfgp, "w"), indent=2)
    r = subprocess.run([SAGE, cfgp, "-o", od,
                        "--disable-telemetry-i-dont-want-to-improve-sage", MZML],
                       capture_output=True, text=True)
    res = peptides(os.path.join(od, "results.sage.tsv"))
    if res:
        psms, peps, prot = res
        results.append((name, psms, peps, prot))
        print("%-14s PSMs=%7d PEPTIDES=%7d proteins=%6d" % (name, psms, peps, prot), flush=True)
    else:
        print("%-14s FAILED  %s" % (name, r.stderr[-200:].replace("\n", " ")), flush=True)

print("\n=== RANKED BY PEPTIDES ===")
for n, ps, pe, pr in sorted(results, key=lambda x: -x[2]):
    base_pe = dict((r[0], r[2]) for r in results).get("base", 0)
    print("%-14s PEPTIDES=%7d  (%+d vs base)  PSMs=%7d proteins=%6d" %
          (n, pe, pe - base_pe, ps, pr))
