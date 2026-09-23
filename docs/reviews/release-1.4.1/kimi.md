• Now let me verify the remaining details: count of task loops, the CI workflow change, the patch-application script, and a sweep for non-public strings.

• All checks done. Findings first, then the verified items.

  ## Findings

  **1. `scripts/apply_openms_patches.sh:4` — stale build-requirement comment. Severity: low. Mildly misleading.**
  The script header still says "WITHOUT the calibration and MassTrace patches the tool does not build". Since 1.4.1 the build also stops without the fifth patch: `src/diaspextract.cpp:2219` declares `getDocumentationURL() const override`, which fails to compile against unpatched TOPPBase headers. The README (`README.md:106`) says this correctly ("the build stops without the first, third and fifth"); only the script's comment lags. The file is exported. Not part of the reviewed diff, but it contradicts a claim in it.

  **2. `CHANGELOG.md:13` — "`-write_cwl` still needs an OpenMS built with `-DENABLE_TDL=ON`". Severity: none / informational.**
  Not misleading, but note this sentence is asserted from OpenMS upstream behaviour (the CWL path is TDL-conditional), and the e2e exercises only `-write_ctd` (12d). Nothing in this repo can falsify it; it's consistent with upstream.

  **3. `CHANGELOG.md:20` — "`DIASPEXTRACT_TASK_THROW`, a test-only switch". Severity: trivial. Not materially misleading.**
  The switch is compiled into the shipped binary (`src/diaspextract.cpp:121-128`), not test-only by construction — any user can set it. "Test-only" describes intent (e2e falsifier), which the surrounding sentence makes clear. Cosmetic at most.

  ## Verified — no action needed

  - **Fifth patch, both TOPPBase call sites.** `patches/openms-topp-external.patch` makes `TOPPBase::getDocumentationURL()` virtual (TOPPBase.h) and guards the `ToolHandler::getTypes` lookup with `official_` in `writeToolDescription_()` (TOPPBase.cpp, covers `-write_ctd`/`-write_cwl`/`-write_nested_cwl`). The tool-side override at `src/diaspextract.cpp:2217-2219` returns the repository URL, matching `CITATION.cff:8`. The ABI warning in `CHANGELOG.md:13-14` matches the patch header verbatim.
  - **`-write_ctd` behaviour.** The old failure message ("Requested tool 'DIAspeXtract' does not exist!") matches the patch header; 12d (`test/test_diaspextract.py:466-477`) pins the `--help` line and the CTD `docurl`.
  - **PerfLoad guard.** `patches/openms-brukertims-mz-calibration.patch` now returns early when all five counters are zero — exactly the claim at `CHANGELOG.md:15-16`.
  - **Six contained task loops, counted.** Wrapped loops at `src/diaspextract.cpp:1237, 2469, 2544, 2589, 4662, 4845` — six, all allocating. The three other taskloops (966, 1034, 1940) are pure compute over pre-sized storage (no allocation, nothing to throw), so "the six task loops that allocate" is the correct set.
  - **`DIASPEXTRACT_TASK_THROW` sites.** Exactly two: `ms1_band` (MS1 band tracing) and `assemble` (per-window assembly), as the entry says; 12e tests both and asserts a clean non-zero exit, not a signal.
  - **"The spectra are unchanged."** Consistent with the exported diff: the only behavioural changes are exception plumbing (identical happy path), the env-gated fault injector, a stderr-print guard, and the docurl override — none touches the spectrum path. The dataset-D gate run itself is external verification I can't re-run from the repo; the phrasing matches how earlier public entries report such gates, and it names no private path.
  - **Omissions.** None material. The only other exported changes since v1.4.0 are the four→five comment updates in `.github/workflows/build.yml` and `patches/openms.lock`, and the version bumps — all release mechanics. Non-exported work (harness/corpus.py killed-cell accounting, backlog triage, review records) is correctly absent from the entry.
  - **README.** The table has five rows matching the five `.patch` files in `patches/`; "applies five patches" (`README.md:94`), "The five OpenMS patches" heading and `patches/` description (`README.md:275`) all agree. Build instructions otherwise unchanged and still accurate (the script globs `patches/*.patch`).
  - **Version truth.** `CMakeLists.txt:2` 1.4.1 ✓, `src/diaspextract.cpp:65` fallback "1.4.1" ✓, `CITATION.cff:14-15` 1.4.1 / 2026-09-23 ✓, `CHANGELOG.md:3` "v1.4.1 — 2026-09-23" ✓.
  - **Privacy sweep.** No occurrence of the reference tool's name, cohort labels, specimen IDs, `/Users` paths, or K562 anywhere in the exported diff (grep over all changed exported files came back empty); even the private docs only ever say "the reference implementation". The v1.4.1 entry mentions only PXD029836 (public) and "dataset D", which is already public vocabulary from the 1.3.1 entry.

  The release is clean to tag; the only fix worth considering before tagging is the one-line comment refresh in `scripts/apply_openms_patches.sh:4`.

