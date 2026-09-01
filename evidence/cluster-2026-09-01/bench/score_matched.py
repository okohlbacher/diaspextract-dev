import csv, sys
sp, pp = set(), set()
for x in csv.DictReader(open(sys.argv[1]), delimiter="\t"):
    if float(x.get("spectrum_q", 1)) <= 0.01: sp.add(x["peptide"])
    if float(x.get("peptide_q", 1)) <= 0.01: pp.add(x["peptide"])
print("[%-4s %-6s] spec_q=%5d PEP_Q=%5d  %ss" % (sys.argv[2], sys.argv[3], len(sp), len(pp), sys.argv[4]))
