import csv, glob, os, sys
print("%-46s %10s %10s %8s" % ("run", "spec_q pep", "pep_q pep", "delta"))
paths = sys.argv[1:]
for d in paths:
    if not os.path.exists(d): print("%-46s MISSING" % d); continue
    sp, pp = set(), set()
    for x in csv.DictReader(open(d), delimiter="\t"):
        pep = x.get("peptide", "")
        if float(x.get("spectrum_q", 1)) <= 0.01: sp.add(pep)
        if float(x.get("peptide_q", 1)) <= 0.01: pp.add(pep)
    n = "/".join(d.split("/")[-3:-1])
    dl = 100.0*(len(pp)-len(sp))/max(len(sp),1)
    print("%-46s %10d %10d %+7.1f%%" % (n, len(sp), len(pp), dl))
