# Pre-tag review, DIAspeXtract 1.4.1 (2026-09-23)

Reviewed commit 6cc0893 against v1.4.0 (brief.md). Reviewers: kimi (kimi.md), vibe (vibe.md).
**Incomplete:** codex was not run -- out of usage until 2026-09-27.

| # | Source | Finding | Verdict | Action |
|---|---|---|---|---|
| 1 | kimi | `scripts/apply_openms_patches.sh:4` says only the calibration and MassTrace patches are needed to build; since 1.4.1 the `getDocumentationURL() const override` needs the TOPP-external patch too | confirmed (README:106 already right) | comment fixed |
| 2 | kimi | `-write_cwl` needs ENABLE_TDL is asserted from upstream, not tested | informational | none (backlog item exists) |
| 3 | kimi | "test-only switch": `DIASPEXTRACT_TASK_THROW` is compiled into the shipped binary | cosmetic, accepted | reworded "a switch meant for the tests" |
| - | vibe | no findings | - | - |

Both reviewers independently verified: six contained task loops (1237, 2469, 2544, 2589, 4662, 4845), two injection
sites, five patches everywhere, version fields 1.4.1 / 2026-09-23, no private term in the exported diff.
Own checks: grep of the exported diff for private terms (only hit: the public repo URL); export dry run adds exactly
`patches/openms-topp-external.patch`, removes nothing.
