## Findings

---

**H-1. harness/corpus.py:77** — STRIP_PREFIX strips the LIVE prefix DIASPEXTRACT_
`STRIP_PREFIX = ("SPEXTRACTOR_", "DIASPEXTRACTOR_", "DIASPEXTRACT_", ...)`
The comment on line 76 even states "DIASPEXTRACT_ is the live one", yet it is included. This causes the harness to strip DIASPEXTRACT_DET, DIASPEXTRACT_LEDGER, etc. from the environment, so the tool cannot read its own variables.
**Scenario:** a benchmark arm sets `DIASPEXTRACT_DET=1` in env.sh → corpus.py strips it → tool sees no variable → no [det] lines → the run appears to succeed without diagnostics.
**HIGH. Would bite: every DIASPEXTRACT_* variable is removed, breaking diagnostics and any future DIASPEXTRACT_ feature.**

---

**H-2. harness/bench.py:180** — running-extractor guard omits the 1.2.x binary name "diaspextractor"
`if ("diaspextract" in l or "spextractor" in l) ...`
The comment on line 175 explicitly lists the three names: diaspextract (now), **diaspextractor** (1.2.x), spextractor (2.0.0), but the check is missing "diaspextractor".
**Scenario:** a 1.2.x `diaspextractor` process is still running on the node → bench.py does not detect it → a new 1.3.0 `diaspextract` starts → both contend for cores and memory, corrupting the benchmark.
**HIGH. Would bite: silent contention on any node that still has a 1.2.x process running.**

---
---
---

**M-3. CHANGELOG.md:7-8** — "the name reaches ... the `spx:` run stamps' tool name" is inaccurate
There is **no** spx: userParam that carries a tool name. The tool name only appears in the mzML `<software>` entry written by TOPPBase (the first argument to the TOPPBase constructor). The spx: stamps record calibration, detector, tiling, dnoise, etc., but never the tool's name.
**Scenario:** none (misleading but harmless).
**MEDIUM (documentation). Would not bite in practice; the output is correct.**

---
---
---

**L-4. CMakeLists.txt:33-38** — redundant foreach loop syntax, but works
`foreach(_old SPEXTRACTOR_TESTS_ONLY DIASPEXTRACTOR_TESTS_ONLY)` then `if(DEFINED ${_old})`. In CMake ≥3.16 `DEFINED` is an operator: `if(DEFINED SPEXTRACTOR_TESTS_ONLY)` is the idiom, but the indirection `${_old}` is also valid and the two-argument `DEFINED` operator variant works. A stale cache entry from 1.2.x will trigger the FATAL_ERROR as required.
**Low. Theoretical: the syntax is correct.**

---

## Answers to Q1–Q10

**Q1. Incomplete renames.**
None found. All DIAspeXtractor / diaspextractor / DIASPEXTRACTOR_ mentions in living files are deliberate (guard, migration table, CMakeLists.txt comments, harness STRIP_PREFIX, bench.py guard, dnoise_table.py label regex, CHANGELOG history). The reverse (new name where old should be) also clean: every CMake target, executable, namespace, #define, TOPPBase name, README command and repo URL uses the new names.

**Q2. The fail-closed guard.**
(a) No false negatives: SPEXTRACTOR_ and DIASPEXTRACTOR_ prefixes are refused; DIASPEXTRACT_ prefixes are accepted. (b) No false positives: the strncmp lengths (12, 15) match the prefix lengths, and the `%.*s` uses correct precision/string pairs; empty environ entries are skipped by strncmp; a bare prefix with no `=` (e.g., `SPEXTRACTOR_=1`) works (m=0, second `%.*s` prints nothing, message is still clear). It prints before TOPPBase and exits ILLEGAL_PARAMETERS (6). Check 22's regex `(?<![A-Z])SPEXTRACTOR_DET\b` matches the guard's printed variable name, not the generic `SPEXTRACTOR_*` text, so it verifies the specific variable was named and refused.

**Q3. CMake option handling.**
`if(DEFINED ${_old})` is valid CMake: `${_old}` expands to the variable name, and `DEFINED` checks if that name is in the cache. A stale CMakeCache from 1.2.x will trigger the FATAL_ERROR as intended. The version-drift check regex `^#define DIASPEXTRACT_VERSION "` matches the source line and `_spx_fallback` captures the whole line; the MATCHES check against `"${PROJECT_VERSION}"` succeeds. No MZPEAK or install() references use old names.

**Q4. Patch hunks.**
Every patch modifies **only** `+` (added) lines and `#` comment header lines. No context line (space-prefixed) or `@@` hunk header changed. The three getenv names (DIASPEXTRACT_ALLOW_CHORD_FALLBACK, DIASPEXTRACT_SDK_PARALLEL, DIASPEXTRACT_LOAD_BATCH) in the calibration patch match CHANGELOG and README.

**Q5. CI gates.**
`grep -q '^DIAspeXtract '` matches TOPPBase's `<name> -- <description>` header. The sed on `project(DIAspeXtract VERSION` extracts the number. No paths use old names in either workflow. tests.yml's `-DDIASPEXTRACT_TESTS_ONLY=ON` is correct. build.yml's e2e/patch-check steps use the new names.

**Q6. The export script.**
With `--name DIAspeXtract --version 1.3.0 --date 2026-09-15` every (c) check passes against this tree (CMakeLists.txt line 2 and 65-68, CITATION.cff, src/diaspextract.cpp #define and TOPPBase call, README line 1, build.yml, CHANGELOG heading). Scrub (d) word-boundary regexes are correct; xargs exit-code logic 0/1/123 handled. No new private file in the diff; .export-private already covers all necessary exclusions.

**Q7. The CHANGELOG v1.3.0 section.**
All statements true except: "the spx: run stamps' tool name" — no such stamp exists (spx: userParams carry calibration, detector, etc., never the tool name); the tool name reaches only the mzML `<software>` entry and the ini section. "Nothing else in the tree changed between 1.2.1 and this release" holds (git log 62b53ea..HEAD is bb9ee04 BACKLOG entry + 4f25921 rename + d02ec71 docs; .gitignore change doesn't affect build outputs). Check count is 25 (26 with mzPeak) — matches test/test_diaspextract.py. Migration table, URLs, dates all correct.

**Q8. README correctness.**
History paragraph accurate. Every command, path, binary, repo URL correct. Options table defaults match register*Option_ calls. Tests section count (25; 26) and bullet about refused prefixes correct. No links to non-exported files.

**Q9. Anything that changes output.**
Only one: the guard's functional scope widened (SPEXTRACTOR_ only → SPEXTRACTOR_ + DIASPEXTRACTOR_). This **refuses** runs, it does not change any spectrum; the old guard's broken `DIA%.*s` message is also fixed. No algorithm, default, or condition changed. The spx: stamps and digests are untouched.

**Q10. The harness and scripts.**
corpus.py STRIP_PREFIX **incorrectly** strips the live DIASPEXTRACT_ prefix — breaks tool's own variables. bench.py's guard **omits** "diaspextractor" (1.2.x) — fails to detect a running 1.2.x binary. sync_cluster.sh and its test fixture are mutually consistent; epd_patch_markers count unchanged.
