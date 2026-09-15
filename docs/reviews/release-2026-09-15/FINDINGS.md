# Adversarial review of the v1.3.0 rename branch -- findings, 2026-09-15

**Status: COMPLETE minus codex.** Codex is out of credit until 2026-09-17 17:41, so the review ran with
kimi and vibe only; every finding below was verified against the tree by the synthesising session before it
was accepted, and the two reviewers' disagreements are recorded, not merged. The fix pass of 2026-09-15
applied or dispositioned every finding: see FIXES.md next to this file (which finding went where, the
rejections with their reasons, the re-gate). Codex did not review this branch; if its credit returns before
the tag, run it on the final head and append to this record.

| what | value |
|---|---|
| tree | `rename/diaspextract-1.3.0` at `d02ec71` (base `0120485`; v1.2.1 = `62b53ea`), clean, also on `origin/rename/diaspextract-1.3.0` |
| scope | `git diff 0120485 HEAD -- . ':(exclude)docs/reviews'` (62 files, +526/-441) plus `scratchpad/release/export_public_v3.sh` |
| brief | PROMPT.md (kimi); PROMPT-vibe.md (the same brief with the worktree path prepended) |
| kimi-code 0.42.0 | `dispatch.sh kimi`, isolated worktree, 13:03-13:20, worktree clean, 16,344 B (kimi.md; stderr transcript kimi.err) |
| vibe 2.25.3 | run 1 via `dispatch.sh`: 0 bytes (vibe_run1-dispatch.err); run 2 by hand with `--output json`: no assistant turn, the first `bash` call sat on an "Allow bash?" approval that `/dev/null` cancelled, and it `cd`-ed into a guessed path because the brief did not name the worktree (vibe_run2-transcript.json); run 3 via run_vibe.sh with `--auto-approve` and the path in the brief: 13:10-13:19, worktree clean, 6,618 B (vibe.md; stderr empty) |
| codex | NOT RUN (credit) |
| CLI versions | check-versions.sh: kimi 0.42.0 -> 0.43.1 and vibe 2.25.3 -> 2.25.4 available; not upgraded. The skill's reference.md is stale for vibe >= 2.25: `--trust` no longer auto-approves tool calls in `-p` mode, `--auto-approve`/`--yolo` exist and are required headless |

## Findings, most severe first

Verdict = what the synthesising session established in the tree (CONFIRMED / REFUTED / DESIGN = intended
behaviour). D-ids are from DOCS-AUDIT.md, K from kimi, V from vibe, O own.

| # | sev | source | file:line | finding | verdict | proposed fix |
|---|---|---|---|---|---|---|
| 1 | HIGH (release gate) | O (D7) | GitHub Actions, dev repo | Both workflows at d02ec71 (tests: push; full build: workflow_dispatch) FAILED with every job "not started because recent account payments have failed"; the same block stopped the 09-14 scheduled build. No CI job has executed on this branch; build.yml also fires on `push: tags: ['v*']` | CONFIRMED (gh run view 34960964688 / 34960974667) | fix the GitHub billing state, then re-run `tests` and `full build` on the final SHA; the Ship phase must not tag while gate 4 is unmet |
| 2 | MEDIUM | O (D1), V (M-3), K (2, as LOW) | CHANGELOG.md:6-7 | "the software entry and the `spx:` run stamps' tool name": none of the sixteen `spx:` stamps (src 4155-4171) carries the tool name; the name reaches the mzML only through the software / dataProcessing entry of `getProcessingInfo_` (src 4147) | CONFIRMED | "The name reaches only the mzML header (the software entry and the data-processing step that references it) and the ini section" |
| 3 | MEDIUM (kimi) / LOW (own) | K (1), O (D3) | CHANGELOG.md:12 | "Nothing else in the tree changed between 1.2.1 and this release": `git log 62b53ea..HEAD` also holds f6007fe (docs/benchmarks/corpus-v3.md), 0120485 + bb9ee04 (BACKLOG) and the `.gitignore` widening in d02ec71. Disagreement on weight: kimi rates it MEDIUM as a one-command-falsifiable public claim; the session rates it LOW because the three files are private (the public 1.2.1 -> 1.3.0 export differs only by the rename and `.gitignore`) | CONFIRMED | "Apart from this rename and one `.gitignore` line, nothing the release carries changed since 1.2.1; the private records grew" |
| 4 | LOW | K (3) | CHANGELOG.md:39-40 | "the `spx:` run stamps and the `spx_guessed` / `spx_n_isotopes` precursor userParams (they sit inside the spectrum digest)": the run stamps are `<run>` userParams written before `<spectrumList>` (MzMLHandler.cpp:5028-5045) and `bench/semantic_digest.py` hashes from `<spectrumList` on, so only the precursor userParams are inside the digest -- and lines 6-8 of the same section say the header is excluded | CONFIRMED | "... precursor userParams (the `spx_*` userParams sit inside the spectrum digest; the bench tools read the stamps)" |
| 5 | LOW | O (D2), K (4) | README.md:6-7 | "The older names were taken by other tools" now covers DIAspeXtractor, which was renamed at the user's request (BACKLOG 916-925, "dropping the -or"); only speXtract and SpeXtractor collided (BACKLOG 966-968) | CONFIRMED | "speXtract and SpeXtractor were taken by other tools; 1.3.0 drops the '-or'" |
| 6 | LOW | O (D4) | CHANGELOG.md, "Migrating from 1.2.x" | the 1.2.0 template's warning that other stale `-D` names are silently accepted is missing: `-DDIASPEXTRACTOR_WITH_MZPEAK=ON` from a 1.2.x build script configures a build without mzPeak and says nothing | CONFIRMED (CMakeLists.txt refuses only the two `_TESTS_ONLY` names) | add to the "Both old prefixes are refused" bullet: only the two `_TESTS_ONLY` names are refused at configure time; `-DDIASPEXTRACTOR_WITH_MZPEAK` / `-DDIASPEXTRACTOR_VERSION` are unused cache entries; `-DMZPEAK_ROOT` is the switch |
| 7 | LOW | O (D5) | README.md:140 | "A 1.2.0 run at the defaults stamps sixteen" in a 1.3.0 README (the count is right: 16 stamps) | CONFIRMED | "A run at the defaults stamps sixteen" |
| 8 | LOW | K (5) | .gitignore (d02ec71) | `docs/reviews/**/*.log` -> `docs/**/*.log`: the one change in the branch that is neither rename nor guard (made for the export tooling; it also ignores this record's dispatch logs, which is why they are saved as .err/.txt) | CONFIRMED as an observation | keep, and name it in the CHANGELOG sentence of finding 3; or drop it from the release |
| 9 | LOW | O (D6) | export_public_v3.sh:179-182 (scratchpad/release) | the (e) summary counts `R` entries of `git diff --cached --name-status` in no bucket: on this tree it prints "added 0, modified 42, removed 0, unchanged 37" against its own plan line "to remove 2, to add 2" | CONFIRMED (export run into a throwaway clone, export_public_v3-dryclone.txt) | `--no-renames`, or count `^R` as one add + one remove |
| 10 | LOW | K (8a) | export_public_v3.sh:142 | the build.yml name-gate check is conditional on the file existing (`[ -f ... ] &&`), so a renamed or dropped workflow exports "VERIFIED" without that gate; every other field check is unconditional | CONFIRMED | make it unconditional (a missing build.yml is a FAIL) |
| 11 | LOW | K (8b) | export_public_v3.sh, step (d) | no scan, not even informational, for the retired spellings `DIAspeXtractor` / `diaspextractor` / `DIASPEXTRACTOR_` in the exported tree, so an unintended leftover passes silently (today: only the deliberate mentions) | CONFIRMED | add an informational scan for the previous release's names, printed like the codex/kimi scan |
| 12 | LOW | K (8c, 8d) | export_public_v3.sh:168, 158 | `FKL|K25423|QKL` is an unbounded substring match (a future token containing it fails a clean tree); `xargs` without `-r` on an empty list | CONFIRMED, theoretical (0 hits; 79 files) | word-bound the specimen scan; `xargs -0 -r` (GNU) or guard on an empty textfiles.txt |
| 13 | LOW | K (9) | .github/workflows/build.yml:124 | `grep -q "^Version: $V"` leaves the dots of 1.3.0 unescaped (matches 1x3y0); only the tool's own Version line exists in help.txt | CONFIRMED, theoretical | escape: `grep -q "^Version: ${V//./\\.}"` |
| 14 | LOW | K (7) | harness/bench2.py:597, 1371 (private) | a stale `DIASPEXTRACTOR_REGISTRY` / `DIASPEXTRACTOR_BENCH_ROOT` export is silently ignored (falls back to samples.yaml / the registry default); the Python harness has no fail-closed guard for old prefixes, unlike the tool | CONFIRMED (design gap; bench2 selftest is failing independently of the rename) | refuse in `load_registry` / `bench_root_from` when an old-prefix twin is set |
| 15 | LOW | K (6) | bench/dnoise_table.py:36-38, 100-104 (private) | the label regex `(?:dia)?spextract(?:or)?` also matches the bare 1.1.0 label `spextract`, a parse change beyond the rename (harmless: those are this tool's runs too); the selftest sample deliberately pairs one line per label | CONFIRMED, intended | none required; `(?:diaspextract|diaspextractor|spextractor)` if the 1.1.0 label must stay unmatched |
| 16 | LOW | K (10) | README.md | the three libOpenMS variables (`DIASPEXTRACT_ALLOW_CHORD_FALLBACK`, `_SDK_PARALLEL`, `_LOAD_BATCH`) are named in the CHANGELOG table and the patch but nowhere in the README (pre-existing at base) | CONFIRMED, pre-existing | a sentence under "OpenMS patches" |
| 17 | INFO | K (Q2 note) | test/test_diaspextract.py | the suite passes the caller's environment minus the two old prefixes into every run, so a caller-side `DIASPEXTRACT_*` probe leaks into all 25 checks (as `DIASPEXTRACTOR_*` did in 1.2.x) | CONFIRMED, pre-existing | strip `DIASPEXTRACT_` too in `c22`'s env, or document that the suite runs in a clean environment (CI does: `env -i`) |
| -- | -- | V (H-1) | harness/corpus.py:77 | "STRIP_PREFIX strips the live `DIASPEXTRACT_` prefix, so an arm's env.sh cannot set `DIASPEXTRACT_DET`" | **REFUTED**: `arm_env` (corpus.py:308-323) strips the CALLER's environment, then sources env.sh on top, and aborts G-V03 if env.sh itself exports a stripped name -- the corpus benchmark measures the defaults by design, the `arm_probe` selftest fixture with `DIASPEXTRACT_DET=1` must abort, and the live prefix was stripped before this branch too (`DIASPEXTRACTOR_` on 09-11). kimi's Q10 reaches the same conclusion | none |
| -- | -- | V (H-2) | harness/bench.py:180 | "the running-extractor guard omits the 1.2.x binary name `diaspextractor`" | **REFUTED**: `"diaspextract" in l` is a substring test and matches `.../bin/diaspextractor -in ...` (proven); the ceph root `/ceph/ibmi/abi/oliver/spextract` still does not match. kimi's Q10 agrees | none |
| -- | -- | V (L-4) | CMakeLists.txt:33-38 | `if(DEFINED ${_old})` "redundant but works" | not a defect; both old `-D` names FATAL_ERROR (rename slice) | none |
| -- | -- | V (Q9 aside) | src/diaspextract.cpp, old guard | "the old guard's `DIA%.*s` message was broken" | REFUTED: `"DIA" + SPEXTRACTOR_X` was exactly the 1.2.x name | none |

## Disagreements (kept, not merged)

- Vibe's two HIGHs (H-1, H-2) are wrong on the code; kimi and the session agree they are not defects. Vibe
  read the STRIP_PREFIX comment and the guard's string literal without following `arm_env` or testing the
  substring. Its confirmed finding (M-3) duplicates finding 2.
- Finding 3's severity: kimi MEDIUM, session LOW (see the row). Finding 2's severity: vibe and session
  MEDIUM, kimi LOW. Both are one-sentence CHANGELOG edits either way.

## Q1-Q10, consolidated (evidence in own-review-notes.md, DOCS-AUDIT.md, kimi.md, vibe.md)

- **Q1 incomplete renames**: none in any living file; no URL, cluster path or quoted command wrongly rewritten (all three reviewers).
- **Q2 guard**: correct on every probed edge -- simulated: the three e2e cases refuse with one message per variable naming `DIASPEXTRACT_<rest>`; c22 cannot pass on the generic wording (a log naming a different variable fails it); `SPEXTRACTOR_=1`, an entry without `=`, `DIASPEXTRACT_DET`, `DIASPEXTRACTX`, `SPEXTRACTOR`, `DIASPEXTRACTORX_Y`, `XSPEXTRACTOR_DET` behave; exit `ILLEGAL_PARAMETERS` (= 6 at the pin, kimi) before TOPPBase runs.
- **Q3 CMake**: `if(DEFINED ${_old})` is the right form, a stale cache entry (even `=OFF`) triggers it, the drift regex matches source line 65, no old target name in the MZPEAK/install blocks.
- **Q4 patches**: 86 changed lines in the four patch files = 72 `+` body + 14 `#` header, 0 context/`@@` lines, line counts 673/198/27/146 unchanged; the rename slice applied and reverse-checked them on bd4b895; the three getenv names agree between patch and CHANGELOG (README: finding 16).
- **Q5 CI**: `printUsage_` prints `invert(tool_name_) << " -- " << description` and Colorizer is isatty-gated, so a redirected `--help` reads `DIAspeXtract -- Extracts ...` and `^DIAspeXtract ` matches only the new header; the version sed extracts 1.3.0; no old names in either workflow. But nothing has run (finding 1).
- **Q6 export**: run for real into a throwaway clone -- EXPORT VERIFIED, 79 + 3 files, all field checks and scrub scans pass; latent gaps are findings 9-12; `.export-private` needs no change.
- **Q7 CHANGELOG**: findings 2, 3, 4, 6; every migration-table cell, the check count (25 / 26), the redirect claim, the digest pins and the older-names line verified.
- **Q8 README**: findings 5, 7, 16; the 16 option rows match the registrations (flags unchanged and unclaimed); every command, path and URL is post-rename; the 8 relative links resolve inside the export; no badges.
- **Q9 output-changing hunks**: none -- the rename-aware diff of src/, CMakeLists.txt and patches/ against v1.2.1 leaves only the version bump, the CMake foreach and the guard loop; no register/setValid/setMin/setMax line changed.
- **Q10 harness/scripts**: STRIP_PREFIX with the live prefix is the design (G-V03); bench.py's guard catches all three binaries and not the ceph root; sync_cluster.sh and its harness agree on every node-side name (37/37); `epd_patch_markers` is case-insensitive on `spextract`, which `DIAspeXtract` contains; bench2's stale-name hole is finding 14.

## What the Ship phase has to know from this review

1. Gate 4 (CI on all legs) is unmet because of the GitHub billing block (finding 1); the branch is already on
   `origin/rename/diaspextract-1.3.0` (pushed by the CI slice), so the export script's "unpushed" precondition is
   satisfied, but the tag push will trigger another blocked full build until billing is fixed.
2. Findings 2-7 are one-line edits to CHANGELOG.md and README.md; none touches a build input (src/, patches/,
   CMakeLists.txt, the four tool headers, the two unit tests), so applying them keeps the rc-arm binary sha256
   valid for gate 5. Apply them BEFORE the export (the export copies these files).
3. The public clone `scratchpad/release/public` is dirty (`assets/logo.svg` title/aria-label -> DIAspeXtract,
   uncommitted); the export refuses a dirty dst, so commit that file first.
4. The three repository links (README:45, CHANGELOG:25, CITATION.cff:8) 404 until the GitHub repositories are
   renamed; rename before pushing the export and creating the release.
5. This record is untracked: `git add docs/reviews/release-2026-09-15` (explicit path) when the Ship phase
   commits; the `.err`/`.txt` names keep the transcripts out of the new `docs/**/*.log` ignore rule.
