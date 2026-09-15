# Docs audit for v1.3.0 (the rename release), 2026-09-15

Tree audited: branch `rename/diaspextract-1.3.0` at `d02ec71` (base `0120485`; previous release `62b53ea` = v1.2.1).
Same shape as the v2.0.0 (2026-09-08) and v1.2.0 (2026-09-11) audits: README against the tool's registered
defaults (flags included), CHANGELOG against `git log <last release>..HEAD`, CITATION.cff, links, badges, and
the completeness of the migration section. Every number below was produced by a command in this session; the
option inventory is `options_from_source.txt` next to this file (a `.tsv` name would fall under the `*.tsv`
ignore rule; 62 registrations parsed from
`src/diaspextract.cpp`, columns: line, name, kind, default).

## 1. README "Options worth knowing" vs `registerOptionsAndFlags_` -- 16/16 rows match

| README row (line) | README default | source default (line) | |
|---|---|---|---|
| `-threads` (118) | all cores; explicit `-threads 1` honoured | TOPPBase's own option; `main_` at 3146-3154 substitutes `hardware_concurrency()` only when `-threads` is absent from the command line | matches the prose |
| `-out_type` (119) | follows the extension | `""` (2121) | ok |
| `-trace:detector` (120) | `integer` | `"integer"` (2159) | ok |
| `-charge:min_charge` (121) | 1 | 1 (2217) | ok |
| `-charge:im_charge_veto` (122) | `true` | `"true"` (2221) | ok |
| `-charge:im_veto_band` (123) | 2.5 | 2.5 (2224) | ok |
| `-assembly:require_isotope_support` (124) | `true` | `"true"` (2226) | ok |
| `-perf:malloc_trim` (125) | `true` | `"true"` (2175) | ok |
| `-perf:stream_load` (126) | `true` | `"true"` (2188) | ok |
| `-perf:ms1_trace_bands` (127) | 48 | 48 (2199) | ok |
| `-dnoise:ms1` (128) | `true` | `"true"` (2235) | ok |
| `-perf:ms1_prune` (129) | `true` | `"true"` (2200) | ok |
| `-trace:max_span_sec` (130) | 120 | 120.0 (2168) | ok |
| `-trace:band_edges` (131) | `acquisition` | `"acquisition"` (2149) | ok |
| `-tile:cells_per_tile` (132) | 1 | 1 (2151) | ok |
| `-tile:rt_sec` (133) | 600 | 600.0 (2148) | ok |

**Flags.** The three `registerFlag_` calls (`diag:selftest_arena` 2166, `gate:variance_support` 2198,
`charge:mono_averagine_select` 2231) are unchanged since v1.2.1 and the README makes no claim about them
(they are `--helphelp` material). A defaults audit that skipped flags would have missed nothing here because
nothing moved: `git diff -M 62b53ea HEAD -- src/ CMakeLists.txt | grep -E 'register.*_\(|setValidStrings_|setMin|setMax'`
is empty. The only non-rename lines in src/, CMakeLists.txt and patches/ between v1.2.1 and HEAD are the
version bump (1.2.1 -> 1.3.0 in both places), the CMake `foreach` over the two old option names, and the
two-prefix guard loop in `main()` (27 added lines, listed in the session log; none touches an option, a
condition or a default).

**Other README numbers that name a default**: the sixteen `spx:` stamps at line 140 are the sixteen
`setMetaValue("spx:...")` calls at src 4155-4171 (the mzPeak alternative at 4152 replaces 4155, never adds);
the e2e count "Twenty-five ... (twenty-six in a build that writes mzPeak)" at 226 is 24 unconditional
`check(` call sites plus the two-iteration loop at test/test_diaspextract.py:392 minus nothing, plus the
mzPeak-conditional `c18b` at 593 = 25 / 26, the same numbers as CONTRIBUTING.md:36 and CHANGELOG v1.3.0.

## 2. CHANGELOG v1.3.0 vs `git log 62b53ea..HEAD`

Five commits: `f6007fe` (docs/benchmarks/corpus-v3.md, private), `0120485` and `bb9ee04` (docs/BACKLOG.md,
private), `4f25921` (the rename of code, build, CI, patches, scripts, harness; version 1.3.0), `d02ec71`
(docs, CHANGELOG, CITATION, .gitignore). So "Nothing else in the tree changed between 1.2.1 and this release"
is true of every exported file except `.gitignore` (`docs/reviews/**/*.log` -> `docs/**/*.log`, a
housekeeping change made for the export tooling) -- see finding D3. The migration table's cells were checked
one by one against CMakeLists.txt, src/diaspextract.cpp, the patches, CITATION.cff and the README (all
consistent). "e2e check 22 now sets one of each, and both at once" matches `c22` (three refusal runs, then
the accept run). The "Older names, for the record" line agrees with the v1.2.0 and v1.2.1 sections and with
docs/BASELINE.md's naming note.

## 3. CITATION.cff

`title: DIAspeXtract`, `repository-code: https://github.com/okohlbacher/diaspextract`, `version: 1.3.0`,
`date-released: "2026-09-15"`; consistent with `project(DIAspeXtract VERSION 1.3.0)` and
`#define DIASPEXTRACT_VERSION "1.3.0"`. The export script's field checks (c) passed on all eleven fields
(export_public_v3-dryclone.txt).

## 4. Links and badges

- Absolute URLs in exported files: 6. OpenMS (NOTICE:9, README:49), dnoise (NOTICE:19), and three that name
  the renamed repository `okohlbacher/diaspextract` (README:45, CHANGELOG:25, CITATION.cff:8). Today
  `gh api repos/okohlbacher/diaspextract` and `.../diaspextract-dev` return 404; `okohlbacher/diaspextractor`
  (public) and `okohlbacher/diaspextractor-dev` (private) exist. The three links become valid the moment the
  Ship phase renames the GitHub repositories (GitHub then redirects the old names), so the docs are correct
  for the release and wrong for the ~minutes between the push and the rename -- the Ship phase must rename
  the repositories BEFORE the public export is pushed and the release is created.
- Relative markdown links in the 79 exported files: 8, every target exists and is itself exported
  (README -> docs/BASELINE.md, docs/MZ-AXIS-DESIGN.md, docs/charge-inference.md, CHANGELOG.md, CITATION.cff,
  NOTICE; CONTRIBUTING -> docs/BASELINE.md; PR template -> none). No exported document links into
  docs/reviews, docs/benchmarks, harness/ or docs/BACKLOG.md.
- Badges: the README carries none, so there is no workflow-badge URL to update for the repository rename.

## 5. Migration section completeness against the v1.2.0 template

Present: executable + CMake target, TOPP name (ini section and mzML software entry, regenerate ini files),
environment prefix incl. the three libOpenMS variables, CMake names, namespace, sources, repositories with
the redirect and `git remote set-url`, both old prefixes refused (+ both old `-D` options), no alias
(+ the `ln -s` hint), patches carry the new names / re-patch from a pristine pin, the unchanged list, the
older-names line. Absent, and present in the template: the note that OTHER stale `-D` names are silently
accepted (a 1.2.x build script passing `-DDIASPEXTRACTOR_WITH_MZPEAK=ON` still configures a build WITHOUT
mzPeak and says nothing; `-DMZPEAK_ROOT` is the switch) -- finding D4. Not applicable this time: "reported
version", "the output file during a run", "defaults that changed", "removed options".

## 6. Version strings outside the CHANGELOG

CMakeLists.txt:2, src/diaspextract.cpp:65, CITATION.cff:14 say 1.3.0. README:5-7 name 1.2.0/1.2.1/1.3.0
correctly in the history paragraph. README:140 still reads "A 1.2.0 run at the defaults stamps sixteen" --
true, but a 1.3.0 README should not date its own header description to a previous release (finding D5).

## 7. CI

GitHub Actions on the dev repository: `tests` (push) and `full build` (workflow_dispatch) both ran at
`d02ec71` on 2026-09-15 11:00 UTC and both FAILED with every job "not started because recent account payments
have failed or your spending limit needs to be increased" (the same block stopped the 2026-09-14 scheduled
full build at `0120485`). This is a billing block, not a code failure, and no CI job has executed on this
branch. `build.yml` also runs on `push: tags: ['v*']`, so the `v1.3.0` tag push will trigger another blocked
run until billing is fixed. Gate 4 ("CI on all legs") therefore cannot be met from this tree today.

## 8. The public export, exercised

`export_public_v3.sh --version 1.3.0 --name DIAspeXtract --date 2026-09-15` was run for real into a
throwaway clone of `okohlbacher/diaspextractor` (it stages, never commits; the clone was discarded):
`EXPORT VERIFIED`, rc 0; 309 tracked, 230 excluded, 79 exported + 3 preserved logo assets = 82 public files;
every version/name field ok; every scrub scan empty; the informational scan empty. Git shows the result as
42 modified + 2 renames (src, test). The script's summary line counts the renames in no bucket ("added 0,
modified 42, removed 0, unchanged 37" against its own plan line "to remove 2, to add 2") -- finding D6.

## Findings from the docs audit (the reviewer findings are in FINDINGS.md, with these merged in)

| id | severity | where | what | proposed fix |
|---|---|---|---|---|
| D1 | MEDIUM | CHANGELOG.md:6-7 | "the software entry and the `spx:` run stamps' tool name": none of the sixteen `spx:` stamps (src 4155-4171) carries the tool name; the name reaches the mzML only through the software / dataProcessing entry that `getProcessingInfo_` (src 4147) writes | "The name reaches only the mzML header (the software entry and the data-processing step that references it) and the ini section" |
| D2 | LOW | README.md:6-7 | "The older names were taken by other tools" now covers DIAspeXtractor, which was renamed at the user's request (docs/BACKLOG.md 916-925: "dropping the -or"), not because it was taken | "speXtract and SpeXtractor were taken by other tools; the '-or' was dropped in 1.3.0" |
| D3 | LOW | CHANGELOG.md:12 | "Nothing else in the tree changed between 1.2.1 and this release" -- `.gitignore` changed too (`docs/**/*.log`) | "Nothing else that the release carries changed ..." or name the .gitignore line |
| D4 | LOW | CHANGELOG.md, Migrating from 1.2.x | the template's warning that other stale `-D` names are silently accepted is missing: `-DDIASPEXTRACTOR_WITH_MZPEAK=ON` from a 1.2.x build script configures a build without mzPeak and says nothing | add one sentence to the "Both old prefixes are refused" bullet: only the two `_TESTS_ONLY` names are refused at configure time; `DIASPEXTRACTOR_WITH_MZPEAK` / `DIASPEXTRACTOR_VERSION` passed as `-D` are unused cache entries; use `-DMZPEAK_ROOT` |
| D5 | LOW | README.md:140 | "A 1.2.0 run at the defaults stamps sixteen" in a 1.3.0 README | "A run at the defaults stamps sixteen" |
| D6 | LOW | export_public_v3.sh:179-182 (scratchpad/release) | the (e) summary ignores `R` entries of `git diff --cached --name-status`, so renamed files are reported as neither added nor removed and "unchanged" is over-counted by the rename count | `git diff --cached --name-status --no-renames`, or count `^R` as one add and one remove |
| D7 | HIGH (release gate, not a docs defect) | GitHub Actions, dev repo | both workflows at d02ec71 never started (billing); gate 4 cannot pass; the v1.3.0 tag push triggers build.yml | fix billing on the GitHub account, re-run `tests` (push) and `full build` (workflow_dispatch) on d02ec71 (or the final SHA) before the Ship phase tags |
