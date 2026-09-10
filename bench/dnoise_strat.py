#!/usr/bin/env python3
"""Where did the peptides go? Compare a treatment's Sage peptide set against a control's, stratified by the
CONTROL's own evidence for each peptide: abundance (summed intensity of its best pseudo-spectrum,
ms2_intensity), charge, retention time and hyperscore.

Written for the dnoise evaluation (2026-09-10): the tool's identification deficit is at low abundance, and a
filter keyed on mobility occupancy removes low-count points first, so the loss must be read by stratum, not
as one count. Peptide sets use the same definition as the gate's peps(): rank 1, peptide_q <= 0.01, unique
peptide string, decoys NOT excluded (so totals match the recorded gate numbers); decoys are reported apart.
Standard library only, so it runs on any node.

usage: dnoise_strat.py CONTROL/results.sage.tsv TREATMENT/results.sage.tsv
       dnoise_strat.py --selftest
"""
import csv, math, os, sys, tempfile

csv.field_size_limit(1 << 30)
NEED = {"peptide", "rank", "peptide_q", "charge", "rt", "hyperscore"}


def best_by_peptide(path):
    """peptide -> its best-scoring rank-1 PSM at peptide_q <= 0.01."""
    best, decoys = {}, set()
    with open(path, newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        miss = NEED - set(r.fieldnames or [])
        if miss:
            sys.exit(f"{path}: missing columns {sorted(miss)}")
        for row in r:
            if row["rank"] != "1" or float(row["peptide_q"]) > 0.01:
                continue
            pep = row["peptide"]
            if row.get("label") == "-1":
                decoys.add(pep)
            hs = float(row["hyperscore"])
            cur = best.get(pep)
            if cur is None or hs > cur["hs"]:
                best[pep] = {"hs": hs, "z": row["charge"], "rt": float(row["rt"]),
                             "int": float(row.get("ms2_intensity") or "nan")}
    return best, decoys


def quantile_edges(values, k):
    v = sorted(x for x in values if not math.isnan(x))
    return [v[min(len(v) - 1, int(len(v) * i / k))] for i in range(1, k)] if v else []


def bucket(x, edges):
    for i, e in enumerate(edges):
        if x < e:
            return i
    return len(edges)


def table(title, ctrl, lost, key, labels):
    print(f"\n{title}")
    print(f"  {'stratum':<22}{'control':>9}{'lost':>8}{'lost %':>9}")
    groups = {}
    for pep, ev in ctrl.items():
        g = key(ev)
        n, l = groups.get(g, (0, 0))
        groups[g] = (n + 1, l + (pep in lost))
    for g in sorted(groups, key=lambda x: (str(type(x)), x)):
        n, l = groups[g]
        print(f"  {labels(g):<22}{n:>9}{l:>8}{100.0 * l / n:>8.1f}%")


def report(ctrl_path, trt_path):
    ctrl, cdec = best_by_peptide(ctrl_path)
    trt, tdec = best_by_peptide(trt_path)
    lost = set(ctrl) - set(trt)
    gained = set(trt) - set(ctrl)
    print(f"control {len(ctrl)} peptides ({len(cdec)} decoy), treatment {len(trt)} ({len(tdec)} decoy)")
    print(f"common {len(set(ctrl) & set(trt))}, lost {len(lost)} ({100.0 * len(lost) / max(1, len(ctrl)):.2f}%), "
          f"gained {len(gained)} ({100.0 * len(gained) / max(1, len(ctrl)):.2f}%), net {len(trt) - len(ctrl):+d}")
    ie = quantile_edges([e["int"] for e in ctrl.values()], 5)
    table("by the control's abundance (ms2_intensity quintile, Q1 = faintest)", ctrl, lost,
          lambda e: bucket(e["int"], ie) if not math.isnan(e["int"]) else -1,
          lambda g: "no intensity" if g == -1 else f"Q{g + 1}")
    he = quantile_edges([e["hs"] for e in ctrl.values()], 5)
    table("by the control's hyperscore quintile (Q1 = weakest)", ctrl, lost, lambda e: bucket(e["hs"], he),
          lambda g: f"Q{g + 1}")
    table("by charge", ctrl, lost, lambda e: int(e["z"]), lambda g: f"z={g}")
    rts = [e["rt"] for e in ctrl.values()]
    lo, hi = min(rts), max(rts)
    table("by retention time (tenths of the control's RT range)", ctrl, lost,
          lambda e: min(9, int(10 * (e["rt"] - lo) / max(1e-9, hi - lo))),
          lambda g: f"{lo + g * (hi - lo) / 10:7.0f}-{lo + (g + 1) * (hi - lo) / 10:.0f}")
    if gained:
        gi = [trt[p]["int"] for p in gained]
        print(f"\ngained peptides by the CONTROL's intensity quintile edges: "
              + ", ".join(f"Q{q + 1} {sum(1 for x in gi if not math.isnan(x) and bucket(x, ie) == q)}" for q in range(5)))


def selftest():
    hdr = "psm_id\tpeptide\trank\tlabel\tpeptide_q\tcharge\trt\thyperscore\tms2_intensity\n"
    d = tempfile.mkdtemp()
    c, t = os.path.join(d, "c.tsv"), os.path.join(d, "t.tsv")
    rows_c = [f"{i}\tPEP{i}\t1\t1\t0.001\t{2 + i % 2}\t{i * 10.0}\t{20 + i}\t{100.0 * (i + 1)}\n" for i in range(10)]
    rows_c.append("99\tPEP0\t1\t1\t0.001\t2\t5.0\t19\t50\n")      # a weaker PSM of PEP0: must not win
    rows_c.append("98\tWEAK\t1\t1\t0.5\t2\t5.0\t19\t50\n")        # above q: must not count
    rows_t = [f"{i}\tPEP{i}\t1\t1\t0.001\t2\t{i * 10.0}\t30\t1\n" for i in range(3, 10)] + ["50\tNEW\t1\t1\t0.001\t2\t1\t30\t1\n"]
    open(c, "w").write(hdr + "".join(rows_c)); open(t, "w").write(hdr + "".join(rows_t))
    ctrl, _ = best_by_peptide(c); trt, _ = best_by_peptide(t)
    assert len(ctrl) == 10 and "WEAK" not in ctrl and ctrl["PEP0"]["hs"] == 20, ctrl.get("PEP0")
    assert set(ctrl) - set(trt) == {"PEP0", "PEP1", "PEP2"} and set(trt) - set(ctrl) == {"NEW"}
    e = quantile_edges([x["int"] for x in ctrl.values()], 5)
    assert bucket(ctrl["PEP0"]["int"], e) == 0 and bucket(ctrl["PEP9"]["int"], e) == 4, e
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    elif len(sys.argv) == 3:
        report(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
