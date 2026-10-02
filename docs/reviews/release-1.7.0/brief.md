# Adversarial review: DIAspeXtract 1.7.0 release candidate ("ponytail" simplification pass)

Review only. Do NOT modify, create or delete any file. Report findings as text.

## Scope (frozen)
Repository at HEAD cea89fe (branch ponytail-170). Review the diff `git diff 31bbab1..HEAD` (31bbab1 = released 1.6.1).
78 files, +1541 / -7729. Main parts:
- src/diaspextract.cpp: removed option modes (R1 -gate:coelution logoverlap, R2 -gate:variance_support, R3 -charge:scoring
  envelope, R4 -charge:mono_averagine_guard/_select, R5 -charge:mono_profile_check true (v1) + its two parameters,
  R6 -charge:iso_partner closest, R7 -assembly:cap_rank corr_inten/umpire, R8 -assembly:fragment_fuse_mode linkage,
  R9 -assembly:require_isotope_support + -assembly:default_charge, R10 -trace:split_scan_time trace, R11 -trace:mz_estimator
  mean/median, R12 -trace:band_edges slab + env DIASPEXTRACT_TILE_RESIDENT); removed debug env probes (GATE_DUMP, LEDGER,
  OUTER_VERIFY, MS1_HIST, MS1_ASYNC worker thread, LOAD_TRIM, PICK_BATCH(_MS1), Z1_DIAG, MS1_TRIM, MS1_CONVERT_SERIAL,
  SPEC_BATCH, MIN_ISOTOPES, LOAD_ONLY) and log-only timers; dead code and duplication removed (commit d7dac2e); every option
  help text rewritten (34184f9).
- src/*.h (except TdfMzCalibration.h), tests/, CMakeLists.txt: boilerplate and comments (398ea84).
- bench/, scripts/, .github/: 46 concluded study scripts deleted, CI text (370387b); check_option_tokens.py extended.
- Docs: README.md rewritten with a mermaid flow chart, new docs/options.md, CONTRIBUTING.md, CHANGELOG v1.7.0 section.

## Invariants (what must hold)
1. At the default options the output spectrum list AND every `spx:` userParam in the mzML header are byte-identical to
   1.6.1. The same holds under every option that still exists (e.g. gate:anchor_rescue, assembly:frag_intensity core|sum,
   assembly:post_fusion_cap, assembly:twin_rt_match bin|ppm, gate:adaptive auto|off, trace:detector openms,
   perf:stream_load false, dnoise:ms1 false, charge:min_charge 2, tile:cells_per_tile 0, tile:rt_sec -1,
   DIASPEXTRACT_PIPE_TILES=1, compat values such as charge:mono_profile_check false, trace:im_slice_merge -1).
2. Removed code must have been reachable ONLY through a removed option value or a removed env variable.
3. No change to floating-point evaluation order, reductions, sort comparators/tie-breaks, OpenMP scheduling/chunking,
   or sampling on any kept path. Re-indents must be whitespace-only (check with git diff -w).
4. Inputs that ran under 1.6.1 with kept options must still run (no new refusal), and refusals must still refuse.
5. Public text (everything not in .export-private) must not name in-house data ("dataset D/A/B", cohort labels
   S08/S23/S26/S30/S33/S36), the comparison tool diaTracer, K562/PXD041421 results, or docs/reviews.
A public identity gate already ran on a cluster build of cea89fe's source (3ad8ce9, same C++): defaults on five public
runs reproduce the 1.6.0 digests and all 29 spx: stamps; the 1.5.0 six-option reset reproduces its digests; kept options
are being compared on one run. So focus on what that gate CANNOT see: paths it does not exercise (mzML / mzPeak input,
openms fallback when calibration is missing, error and refusal paths, other thread counts, -perf:trace_bands 0,
native_ms1_neighbors, tile edge cases, Windows/macOS compile of headers), and the docs.

## Questions (attack these; I am least sure of 2, 3 and 6)
1. Does any R1-R12 removal change behaviour at the defaults or under a kept option? Look hard at R4 (v2-B lost
   `!v.guard_stop && mono == leftmost_mz`), R9 (charge-less precursors are now always dropped; was anything between
   marking and dropping reading the defaulted charge?), R12 (band edges, frame tables, the mzML/mzPeak paths), R11 (openms
   detector fragment m/z), R3 (inferPrecursors_/monoPositionPass_ un-nesting: whitespace only?).
2. C3 refactors in d7dac2e: toTraceAt/makeSpan merged with an offset parameter; procKb_ replacing three /proc parsers;
   coRank_ reuse in parallelSortTotal_; option-global initial values set to the registered defaults; M-11 merged
   !streamed blocks with firstprivate(spicker); M-15 lower_bound; M-17 removal of the post-load tdf retry loop;
   taskErr_ consolidating several named criticals. Any semantic change, including on error/fallback paths?
3. Error and fallback paths: any input that ran before and now stops, or stopped before and now runs? (M-17, R12 refusal
   texts now naming trace:detector integer, absorbAll_ serial branch turned into a throw.)
4. Docs vs code: README.md, docs/options.md, CHANGELOG.md v1.7.0, CONTRIBUTING.md. Wrong defaults, wrong behaviour claims,
   claims the code does not support, the mermaid chart's stage order/numbers, the Migrating section (an old 1.6.1 ini is
   refused with "Unknown (or deprecated) Parameter ..." then "Parameters ... are invalid"; a removed CLI option gives
   "Unknown option(s)").
5. Public-text leaks in exported files (git ls-files minus .export-private).
6. CI: does anything in .github/workflows, scripts/check_option_tokens.py, test/test_diaspextract.py or tests/ break,
   reference a deleted file, or silently stop checking something it used to check?

## Output
For each finding: severity (blocker / should-fix / note), file:line, the concrete failing input or scenario, and whether it
would bite on real data or is theoretical. Rank by severity. If something is fine, say so in one line rather than padding.
