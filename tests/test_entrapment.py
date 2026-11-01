#!/usr/bin/env python3
"""Self-checks for the corrected entrapment estimator (bench/entrapment.py).

Guards its two corrections: peptide-hypothesis ratio (not protein ratio) and foreign-ONLY entrapment counting.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench"))
from entrapment import _bootstrap_fdr, peptide_ratio, digest_rule
import tempfile

def main():
    ratio = 0.6805
    lo, hi = _bootstrap_fdr([0] * 990 + [1] * 10, ratio)
    assert 0.0 < lo < hi < 10.0, (lo, hi)
    # corrected FDR = (n_entrap/ratio)/n_target -> ~1.5% here; the CI must bracket it
    point = 100.0 * (10 / ratio) / 990
    assert lo <= point <= hi, f"CI [{lo:.3f},{hi:.3f}] must bracket point estimate {point:.3f}"
    lo0, hi0 = _bootstrap_fdr([], ratio)
    assert lo0 != lo0 and hi0 != hi0, "empty input must yield NaN CI, not a number"
    lo_d, hi_d = _bootstrap_fdr([0] * 990 + [1] * 10, ratio)
    assert (lo, hi) == (lo_d, hi_d), "bootstrap must be deterministic (fixed seed)"
    # the peptide ratio digests as the search does: after E, a target without E is one peptide, a foreign one two
    with tempfile.NamedTemporaryFile("w", suffix=".fasta", delete=False) as f:
        f.write(">t\nAAAAAAKAAAAAAK\n>ENTRAP_f\nAAAAAAEAAAAAAE\n")
    gluc = digest_rule({"database": {"enzyme": {"cleave_at": "E", "restrict": ""}}})
    r_try, r_glu = peptide_ratio(f.name), peptide_ratio(f.name, rule=gluc)
    os.unlink(f.name)
    assert (r_try, r_glu) == (0.5, 2.0), f"peptide ratio trypsin {r_try} (want 0.5), cleave after E {r_glu} (want 2.0)"
    print(f"OK entrapment: point {point:.3f}%, CI [{lo:.3f}, {hi:.3f}], deterministic, NaN on empty; ratio follows the enzyme")
    return 0

if __name__ == "__main__":
    sys.exit(main())
