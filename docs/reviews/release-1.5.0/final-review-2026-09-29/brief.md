Review only — do not modify any file, do not run builds, do not commit.

SCOPE. Repository DIAspeXtract (an OpenMS TOPP tool that extracts pseudo-MS/MS spectra from Bruker diaPASEF data).
HEAD is 109ae2e (branch release-1.5.0), the 1.5.0 release candidate; the last release is tag v1.4.1. Uncommitted: none
that matter (untracked harness/*.md reports only). Files in scope:
  - CHANGELOG.md, section "## v1.5.0 — 2026-09-29"
  - README.md (pipeline description steps 3-4 and the option tables for trace:, gate:, assembly:)
  - src/diaspextract.cpp: everything that changed in `git diff v1.4.1..HEAD -- src/diaspextract.cpp`, with the focus on
    the same-bin merge (commits 5cbc478 and cade28f): the merge inside toTof() (option trace:im_slice_merge) and the
    assembly-time guard (option assembly:merge_same_bin), plus the tiling fix e71b085 (tile_drt).

DOMAIN INVARIANTS (the release relies on these):
 1. Output must be bit-for-bit deterministic across thread counts and tile layouts: the same input and options give the
    same semantic digest with -threads 8 and 100, and with -tile:cells_per_tile 0, 1, 2. Anything order-dependent
    (unordered containers, parallel accumulation order, ties broken by pointer or thread order) breaks this.
 2. With -trace:im_slice_merge -1 -assembly:merge_same_bin false the output must be byte-identical to the build without
    the merge (and with the gate modes also off, to 1.4.1). A code path that changes anything when both are off is a bug.
 3. The integer detector works on (frame, TOF bin) peaks; a TOF bin is one m/z. After the merge, no spectrum may carry two
    fragments with the same TOF bin (exact m/z for the OpenMS detector). Intensities are summed only over members that
    belong to the same ion (1/K0 within the link distance, group span <= 2x link; in assembly: RT-overlapping the strongest
    member); the reported m/z is the strongest member's; the max_fragments cap key must not be inflated by merging.
 4. Memory ledger accounting (ledAdd_/LC_SLAB) must match the bytes actually held after the slab is rewritten.
 5. The CHANGELOG and README must state option names and defaults exactly as registered in the code, and the recipe that
    reproduces 1.4.1 output must switch off EVERY output-changing default added since v1.4.1.

QUESTIONS (answer each; the first three are where we are least sure):
 1. toTof() merge: can the regrouping (sort by (imq, idx), single linkage with span cap, writing each group at its first
    member's slab position, rewriting frame_off, resize) ever reorder or drop a peak that belongs to another frame or bin,
    or depend on the input order in a way that breaks invariant 1? What happens at the span cap boundary (exactly 2x)?
 2. Assembly guard: are "RT-overlapping the strongest member" and "the best cap key" computed so that ties are broken
    deterministically? Can the guard change a spectrum when no two fragments share a bin (invariant 2)?
 3. Is there any path (tiles, boundary carries between cells, the OpenMS detector, MS1) where two same-bin fragments
    survive both merges? Is that acceptable as documented?
 4. Ledger: is ledAdd_(LC_SLAB, bytes()-before) correct when the slab shrinks (negative delta) and under concurrency?
 5. Are the CHANGELOG 1.5.0 entries accurate against the diff (every user-visible change present, no unsupported claim)?
    Are the README defaults right (e.g. "top 500", 0.015, true)?
 6. Anything else that would make you block the release.

FORMAT. For every finding: file:line, the concrete failing input or scenario, severity (blocker / fix-before-tag /
minor), and "would this bite on real data, or is it theoretical?". If something is fine, say so briefly rather than
padding. No style comments.
