## Pre-release documentation review: DIAspeXtract 1.4.0

### Severity 1 — reader misled

**README.md:239 vs src/diaspextract.cpp:2234** — **assembly:twin_im_tolerance description inconsistent with code help**
- README: "24 % fewer spectra for 0.2 % of the peptides on both engines, entrapment FDR unchanged" on a "HeLa run"
- Code help: "-23.8% spectra for -0.21% Sage / -0.18% MSFragger peptides on PXD029836", plus missing details: "peaks within 10 ppm fused", "Twins come from two seeds that resolve to one monoisotope, or from one precursor in the overlap of two isolation windows", and "CHANGES OUTPUT"
- **Impact**: Numbers differ, dataset reference differs, critical implementation details omitted. User would be misled about the exact behavior and magnitude.

**README.md:234 vs src/diaspextract.cpp:2231** — **assembly:max_fragments extra text not in code**
- README adds "keep it at or above `min_fragments`"
- Code help: "(applied before the twin fold, see assembly:twin_im_tolerance)"
- **Impact**: Extra phrase in README is not in code and could confuse.

**CHANGELOG.md:7-19 vs src/diaspextract.cpp:2234** — **Fold description omits key implementation details**
- CHANGELOG: does not mention "peaks within 10 ppm fused" or that folded spectrum can exceed max_fragments
- Code help: explicitly states both
- **Impact**: User misses critical detail about fragment fusion.

**CHANGELOG.md:7-19** — **Missing "CHANGES OUTPUT" marker**
- Code help explicitly marks it as changing output
- CHANGELOG describes it but doesn't use the standard marker
- **Impact**: User might not realize default output changed.

### Severity 2 — references to non-public data or paths

**README.md:277** — **bench/ directory referenced but in .export-private**
- README layout section lists `bench/` as part of the repo layout
- .export-private line 46 lists `bench/` as non-exported
- **Impact**: Public docs reference a directory that won't exist in the public repo.

**CHANGELOG.md:26,29** — **bench/ scripts referenced but directory non-exported**
- Mentions `bench/iso_frontier.py`, `bench/twin_merge.py`, etc.
- bench/ is in .export-private
- **Impact**: Users of public repo can't find these tools.

**docs/SAME-POSITION-DUPLICATION-2026-09-20.md:22-27,69,74,97,117,157,166,174,183** — **Multiple bench/ references**
- Throughout the document references to bench/*.py scripts
- bench/ is non-exported
- **Impact**: Most severe — entire document is public but full of non-exported path references.

**docs/SAME-POSITION-DUPLICATION-2026-09-20.md:22-23** — **harness references**
- "harness's pinned closed configs" and "benchmark harness"
- harness/ is in .export-private (lines 23, 46)
- **Impact**: References to non-exported test infrastructure.

**CHANGELOG.md:388** — **harness reference**
- Mentions harness in context of log stream parsing
- harness/ is non-exported
- **Impact**: Reference to non-exported infrastructure.

**CHANGELOG.md and README.md** — **Internal dataset labels**
- CHANGELOG.md:65,240,243, etc.: "dataset D", "run 009", "TNBC 009"
- These appear to be internal specimen/dataset identifiers
- **Impact**: If these are considered specimen IDs per the brief, they violate the rule.

### Severity 3 — cosmetic / minor

**README.md:239** — **Missing "CHANGES OUTPUT" in option table**
- assembly:twin_im_tolerance changes output but README doesn't mark it
- Code help and CHANGELOG both indicate it changes output
- **Impact**: Cosmetic inconsistency.

**README.md:239** — **"HeLa run" vs code's "PXD029836"**
- README uses generic "HeLa run" while code uses specific public dataset identifier
- **Impact**: Cosmetic inconsistency in dataset reference.

### Severity 4 — checked and fine

**Version truth**
- CMakeLists.txt:2: `project(DIAspeXtract VERSION 1.4.0`
- src/diaspextract.cpp:65: `#define DIASPEXTRACT_VERSION "1.4.0"`
- CITATION.cff:14: `version: 1.4.0`
- CITATION.cff:15: `date-released: "2026-09-23"`
- CHANGELOG.md:3: `## v1.4.0 — 2026-09-23`
- **Status**: All consistent.

**K562 references**
- No occurrences in README.md, CHANGELOG.md, CITATION.cff, or docs/SAME-POSITION-DUPLICATION-2026-09-20.md
- Commit 50a3b41 explicitly removed all K562 references from public docs
- **Status**: Clean.

**Reference tool name**
- "reference implementation" appears in CHANGELOG and docs but appears to be a generic description, not a specific tool name
- **Status**: Appears acceptable (generic term, not a proper name).

**PXD identifiers**
- PXD029836, PXD047793 are public ProteomeXchange dataset identifiers
- **Status**: Public data, fine to reference.

---

### Ranked findings (most severe first)

1. **docs/SAME-POSITION-DUPLICATION-2026-09-20.md:22-27,69,74,97,117,157,166,174,183** — Multiple `bench/` script references. bench/ is in .export-private. **SEVERE: reader misled, non-public path**
2. **CHANGELOG.md:26,29** — bench/ tools listed. **SEVERE: reader misled, non-public path**
3. **README.md:239** — assembly:twin_im_tolerance: wrong numbers (24% vs 23.8%), wrong dataset (HeLa vs PXD029836), missing fusion detail. **SEVERE: reader misled**
4. **docs/SAME-POSITION-DUPLICATION-2026-09-20.md:22-23** — harness references. harness/ is in .export-private. **HIGH: non-public path**
5. **CHANGELOG.md:388** — harness reference. **HIGH: non-public path**
6. **README.md:277** — bench/ in layout. **HIGH: non-public path**
7. **CHANGELOG.md:7-19** — Fold description omits "peaks within 10 ppm fused" and "can exceed max_fragments". **MEDIUM: reader misled**
8. **CHANGELOG.md:7-19** — Missing "CHANGES OUTPUT" marker. **MEDIUM: inconsistent**
9. **README.md:234** — assembly:max_fragments: extra "keep it at or above min_fragments" not in code. **MEDIUM: inconsistent**
10. **CHANGELOG.md, README.md** — Internal dataset labels ("dataset D", "TNBC 009"). **MEDIUM: potential specimen ID leak**
11. **README.md:239** — Missing "CHANGES OUTPUT" mark. **LOW: cosmetic**
12. **README.md:239** — "HeLa run" vs code's "PXD029836". **LOW: cosmetic**

---

### Summary by category

**1. Option defaults/meanings vs code**: 3 findings (severe to medium)
**2. CHANGELOG claims vs code/log**: 3 findings (medium to low)
**3. Fold description consistency**: 5 findings (severe to low)
**4. Non-public information**: 6 findings (severe to medium)
**5. Version truth**: All consistent — FINE
