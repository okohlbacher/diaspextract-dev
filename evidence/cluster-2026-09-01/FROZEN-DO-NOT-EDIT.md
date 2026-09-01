# FROZEN EVIDENCE SNAPSHOT — DO NOT EDIT OR EXECUTE
Byte-for-byte copy of /scratch/kohlbach/{prof,harness,bench} small files as of 2026-09-01.
It preserves WHAT PRODUCED THE HISTORICAL NUMBERS, including known-superseded code:
- bench/joint_bench.py here LACKS the MSFragger lowercase-column fix the live bench/joint_bench.py has
  (functional 6-line divergence in the metric-defining script — adjudicated at canonicalisation, step 03)
- bench/charge_im.py and bench/truthset.py here are v1; corrected versions live in scripts/
- prof/entrap_apply.py here still imports from /scratch (the live bench/ copy is fixed)
These scripts reference /scratch paths and are NOT a runnable bundle. The live, maintained versions
are in bench/, harness/, scripts/ at the repo root. Step 03 adjudicates which version produced which
frozen number before any canonicalisation.
