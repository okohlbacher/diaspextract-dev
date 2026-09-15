# Own review notes (before the reviewer outputs), 2026-09-15

Evidence collected in this session, keyed to the brief's questions.

Q1 incomplete renames: the rename slice's 187-hit inventory was re-checked by category; every living-file hit
is one of the deliberate mentions. No URL, cluster path or quoted command was renamed wrongly: the only
`diaspextract` URLs are the three intended repository links; /ceph/ibmi/abi/oliver/spextract untouched.
Q2 guard: simulated (guard_sim in the session log): SPEXTRACTOR_DET, DIASPEXTRACTOR_DET, both -> refused with
one message per variable naming DIASPEXTRACT_<rest>; c22's assertions cannot pass on the generic wording alone
(a log naming SPEXTRACTOR_OTHER fails the SPEXTRACTOR_DET assertion); SPEXTRACTOR_=1 -> "DIASPEXTRACT_";
an entry without '=' -> whole name; DIASPEXTRACT_DET, DIASPEXTRACTX, SPEXTRACTOR, DIASPEXTRACTORX_Y,
XSPEXTRACTOR_DET -> accepted. Exit code ILLEGAL_PARAMETERS before TOPPBase runs (main() line 4838).
Q3 CMake: `if(DEFINED ${_old})` inside foreach is the documented CMake form (variable name in _old); the
rename slice proved both -D names FATAL_ERROR at CMakeLists.txt:35. Version-drift regex matches line 65.
Q4 patches: 86 changed lines, 72 `+` body + 14 `#` header, 0 changed `@@`/context lines, line counts
673/198/27/146 unchanged; the rename slice applied and reverse-checked all four on the pinned bd4b895.
Q5 CI: TOPPBase::printUsage_ prints `invert(tool_name_) << " -- " << tool_description_`; Colorizer is
isatty-gated (Colorizer.cpp:18,87,158) so a redirected --help carries no escapes and `^DIAspeXtract `
matches "DIAspeXtract -- Extracts ...". The version sed extracts 1.3.0 from CMakeLists.txt:2. BUT no CI job
has run on the branch: billing block (DOCS-AUDIT.md section 7).
Q6 export: exercised for real into a throwaway clone: EXPORT VERIFIED (DOCS-AUDIT.md section 8); the (e)
summary miscounts renames (D6).
Q7 CHANGELOG: D1 (spx: stamps carry no tool name), D3 (.gitignore), D4 (stale -D names note missing);
the rest verified true.
Q8 README: D2 (older names taken), D5 (1.2.0 run stamps sixteen); 16/16 table rows match; links ok.
Q9 output-changing hunks: none (rename-aware diff of src/, CMakeLists.txt, patches/ against v1.2.1 leaves
only the version bump, the CMake foreach and the guard loop).
Q10 harness/scripts: STRIP_PREFIX with the live prefix is intended (env.sh decides; the arm_probe fixture
still aborts G-V03); bench.py guard conservative (matches the e2e suite and verify scripts by path, as the
old pattern did); sync_cluster.sh and the txn harness fixture agree on every renamed path (37/37);
epd_patch_markers is case-insensitive on "spextract", which DIAspeXtract contains.
