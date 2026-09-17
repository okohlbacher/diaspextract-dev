# Review brief: DIAspeXtract 1.3.2 documentation release (README rewrite)

Review only. Do not modify, create or delete any file. Report findings as a ranked list.

## Scope
Repository: the current directory (a checkout of DIAspeXtract, HEAD is 72f6d31, clean tree).
Files under review: README.md, assets/pipeline.svg, assets/algorithm.svg, assets/streaming.svg, the `## v1.3.2`
section at the top of CHANGELOG.md, CITATION.cff, CMakeLists.txt (version). The README deliberately has NO
performance, benchmark, determinism or test sections any more (they live in CONTRIBUTING.md and docs/); do not
ask for them back.
Ground truth you must check them against: src/diaspextract.cpp (option registrations, `spx:` userParams, main()'s
`-threads` handling), src/*.h, test/test_diaspextract.py (the end-to-end checks), tests/ (unit tests, golden values),
CMakeLists.txt (ctest names), .github/workflows/tests.yml and build.yml, patches/, scripts/check_option_tokens.py,
docs/BASELINE.md, docs/REFERENCE-COMPARISON-2026-09-08.md, docs/HELA-TABLE.md, the `## v1.3.1` and `## v1.3.0`
sections of CHANGELOG.md.

## Domain invariants
- Every option and default named in README.md must be one the tool registers with exactly that default
  (registerIntOption_/registerDoubleOption_/registerStringOption_/registerFlag_ in src/diaspextract.cpp).
  `-threads` is special: TOPP prints default 1, but main() scans argv and uses every core when `-threads` is absent.
- The spectrum list of the tool's output is byte-identical across thread counts and tile counts for a fixed binary
  and band count; the README must not claim more (it is NOT identical across code changes or band counts).
- "Changes output" in the option tables means the option moves the spectrum list; an option marked otherwise must
  really be output-neutral (the help text in src says which).
- The sixteen `spx:` userParams listed must be exactly the ones the source stamps (note `spx:pearson_G`).
- Public documentation must not name the comparison tool (it is "the reference implementation"), must not carry
  cohort labels (dataset A..F wording is fine), specimen identifiers, or user home paths.
- The three SVG diagrams are text; every number and stage in them is a claim about the code.

## What to attack, in order
1. Any option, default, number, file name, test count or userParam in README.md that disagrees with the source,
   the tests or the docs. Give file:line for both the claim and the evidence.
2. Any statement in the "How it works" section or in the diagrams that misdescribes the algorithm's order or
   mechanism (load → MS1 traces/precursors → window loop per isolation window × 600-s cell → gate → assembly →
   per-tile sort and write). In particular: is the gate really |ΔRT| ≤ gate:delta_rt AND |ΔIM| ≤ gate:delta_im AND
   Pearson ≥ gate:min_correlation over ≥ gate:min_correlation_points? Is corr_power applied to intensity after
   the max_fragments cut or before? Are boundary fragments carried between tiles? Is one window always admitted?
3. Remaining development-process content: dated chronology, references to earlier builds, internal reviews,
   cluster nodes, or falsification narratives that a user of the software does not need. Quote each.
4. The CHANGELOG v1.3.2 entry: is every claim in it true (59 registered options? three diagrams? the -threads
   statement? "binary differs only in its version string"?).
5. Explanations of options a user would find unclear or misleading, and places where the README does not say
   which option to change for a goal (memory, time, sensitivity, FDR).

## Budget
Be economical: read only what you need to check a claim. At most 12 findings. Do not explore the tree broadly.

## Output format
Ranked list, most severe first. For each: severity (blocker / should-fix / nit), file:line of the claim, the
evidence (file:line or quoted help text), a one-line fix. Then a short verdict: would you tag this as a release?
If something is fine, say so briefly rather than padding.
