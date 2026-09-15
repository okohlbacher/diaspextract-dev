# Fix pass on the v1.3.0 review, 2026-09-15

Review status: **COMPLETE minus codex** (kimi 0.42.0 + vibe 2.25.3 + the synthesising session; codex out of
credit until 2026-09-17 17:41, not run). Fix commit: `16e5908` on `rename/diaspextract-1.3.0` (parent `d02ec71`,
the reviewed tree). Record commit: the one that adds this file.

Build inputs (`src/`, `patches/`, `CMakeLists.txt`, `scripts/sync_cluster.sh`, `tests/test_dnoise_ms1.cpp`,
`tests/test_tdf_load.cpp`) and `test/test_diaspextract.py` are byte-identical to `d02ec71` (`git diff --stat
d02ec71 HEAD -- <those>` is empty), so the cluster gates of the `v1.3.0rc1` arm stand: binary sha256
`9e11fe96a21c703a6b86883ecb372722affb28b84fc7699647e1da4eeda97514`, libOpenMS `3868c6d078b0d84c...`, digests
`e43672a0` / `8c1b047f` (dataset D) and `3aafd0b5` / `bff54a1f` (run 009), e2e 26/26, guard G1-G5, harness
release smoke `failed 0` and guard test 39/39, deploy-transaction harness 37/37, rebuild identity. Only docs,
CI and private harness files changed, so the re-gate is CI on the new head (last section).

## Dispositions

| # | finding | disposition | where |
|---|---|---|---|
| 1 | GitHub Actions billing block | NOT FIXABLE IN THE TREE: an account state (Billing & plans) for the user; re-checked by the push of the fix commits (last section) | -- |
| 2 | CHANGELOG: `spx:` stamps' tool name | APPLIED: "the software entry and the data-processing step that references it" | CHANGELOG.md:7-8 |
| 3 | "Nothing else in the tree changed" | APPLIED: "Apart from this rename and one `.gitignore` line (`docs/**/*.log`), nothing the release carries changed since 1.2.1; only the private development records grew" | CHANGELOG.md:12-14 |
| 4 | "(they sit inside the spectrum digest)" | APPLIED: the `spx_*` precursor userParams sit inside the digest; the run stamps sit in the header, which the bench tools read | CHANGELOG.md:43-45 |
| 5 | "The older names were taken by other tools" | APPLIED: "speXtract and SpeXtractor were taken by other tools; 1.3.0 only drops the '-or'" | README.md:6-7 |
| 6 | stale `-D` names silently accepted | APPLIED in the "Both old prefixes are refused" bullet: only the two `_TESTS_ONLY` names are refused at configure time; `-DDIASPEXTRACTOR_WITH_MZPEAK` / `-DDIASPEXTRACTOR_VERSION` are unused cache entries; `-DMZPEAK_ROOT` is the switch | CHANGELOG.md:32-34 |
| 7 | "A 1.2.0 run at the defaults stamps sixteen" | APPLIED: "A run at the defaults stamps sixteen" | README.md:148 |
| 8 | `.gitignore` `docs/**/*.log` | KEPT and named in the sentence of finding 3 (the export tooling and this record's `.err`/`.txt` names rely on it) | CHANGELOG.md:13 |
| 9 | export summary counts no `R` entries | APPLIED: `--no-renames` (a rename is one D plus one A) and a FAIL on any staged status other than A/M/D/T | export_public_v3.sh, step (e) |
| 10 | build.yml name gate conditional on the file | APPLIED: unconditional `check_grep` (a missing workflow is a FAIL like every other field) | export_public_v3.sh, step (c) |
| 11 | no scan for the retired spellings | APPLIED: `--prev OLDNAME` (repeatable) adds an informational per-file count of `OLDNAME` / `oldname` / `OLDNAME_` in the exported tree | export_public_v3.sh, step (d) |
| 12 | `FKL\|K25423\|QKL` unbounded; `xargs` without `-r` | APPLIED: word-bounded with `_` a boundary (an ID must not appear at all; the bound only stops a longer token that contains one); `xargs -0 -r` on all four xargs | export_public_v3.sh, steps (b) and (d) |
| 13 | build.yml version grep, unescaped dots | APPLIED: `VE=${V//./\\.}`, used by both Version greps (tested: `1x3y0` no longer matches) | .github/workflows/build.yml:123-127 |
| 14 | bench2.py ignores an old-prefix export | APPLIED: `refuse_old_prefixes()` runs before every subcommand, G-B00 naming each variable and its `DIASPEXTRACT_` name; probed: `DIASPEXTRACTOR_REGISTRY` and `SPEXTRACTOR_BENCH_ROOT` refused (rc 2), `DIASPEXTRACT_REGISTRY` passes the guard; `selftest` output identical before and after (it aborts G-B02 on the sample name `dataset A`, a pre-existing scrub artefact independent of the rename) | harness/bench2.py:115-128, 2789 |
| 15 | dnoise_table.py label regex also matches the bare 1.1.0 label | REJECTED: intended (the code comment says so, those are this tool's 1.1.0 runs), harmless, and the finding itself asks for nothing | -- |
| 16 | README lacks the three libOpenMS variables | APPLIED: a paragraph under "OpenMS patches" written from the patch's own code (`ALLOW_CHORD_FALLBACK=1` exactly; `LOAD_BATCH` default 256, frame order unchanged; `SDK_PARALLEL` any value, serial by default under the SDK converter) | README.md:87-93 |
| 17 | e2e suite passes the caller's `DIASPEXTRACT_*` through | APPLIED as the documented alternative: CONTRIBUTING tells to run it from a shell with no `DIASPEXTRACT_*` set (CI: `env -i`; the cluster verify script starts clean, its line 43). The suite itself is untouched, so the deployed copy stays cmp-identical to the repo's and the e2e gate is not re-run | CONTRIBUTING.md:42-45 |
| -- | vibe H-1, H-2, L-4, Q9 aside | REFUTED in FINDINGS.md; nothing to apply | -- |

Also applied, from the cluster e2e slice's report rather than a review finding: `harness/CORPUS.md`'s sentence
that the measurement hashes "are still `050e2e2a` / `064af71b` / `4fe0a1ce`" now has a dated paragraph after
it -- the pair hash is `3215b73e` since the rename (`STRIP_PREFIX` sits inside the measured function), search
and rule unchanged, re-proved on `v1.3.0rc1` (selftest 135/135, guardtest 39/39, smoke records reproduced).

Record housekeeping: `options_from_source.tsv` renamed `.txt` (the `*.tsv` ignore rule would have kept it out
of the commit); the fixed export script is saved here as `export_public_v3.sh` so the next release does not
recover it from a deleted scratchpad again (the v1.2.x copy was lost that way).

## For the release record, from the cluster e2e slice

The v1.2.0 cluster tree on ibminode05 differed from pin `bd4b895` + the v1.2.0 patches by ONE comment line in
`BrukerTimsFile.cpp` (`scripts/sync_cluster.sh)` in the tree against `scripts/apply_openms_patches.sh)` in the
patch, rewritten by `91a1b28` after the 09-11 tree edit). Comment only, no code effect; the first 1.3.0 tree
rename refused on it and restored cleanly, the second asserted the replacement, and the tree now equals pin +
the repo's HEAD patches byte for byte (8 files, sha256-asserted; `rename_tree_dx.log`). The `v1.3.0rc1` arm
was built from that tree by `scripts/sync_cluster.sh` (DEPLOY COMMITTED, provenance git `d02ec71`), and a
second deploy from the same commit reproduced the binary and libOpenMS sha256 exactly -- provided `cmake .`
is not re-run in between (the OpenMS date stamp, `3.6.0-pre-exported-20260915`, is fixed at configure time).

## Re-gate

Only docs, CI files and private harness files changed between `d02ec71` and the final head, so the cluster
gates (1, 2, 3, 5) carry over unchanged and gate 4 (CI on all legs) has to be green on the final head. The run
ids and their outcome are in the fix slice's report, and `gh run list -R okohlbacher/diaspextractor-dev
--branch rename/diaspextract-1.3.0` lists them; at the time this record was committed the previous runs
(34960964688, 34960974667 at `d02ec71`) had been refused by the account billing block before their first step.
