You are an adversarial reviewer for speXtract (repo: /Users/kohlbach/Claude/speXtract; C++ tool src/DIAPseudoSpectra.cpp,
loader patch patches/openms-brukertims-mz-calibration.patch, new src/MzPeakStreamLoad.h). Read ONLY what you need; write
nothing. Modify nothing.

REVIEW TARGET: docs/BACKLOG-ANALYSIS-2026-09-02.md -- a consolidation of every open issue in the project into tables
(A runtime, B determinism, C identification quality, D mzPeak, E engineering) with status, root cause, fix, cost, and a
4-week plan. Sources it consolidates: docs/BACKLOG.md, docs/RUNTIME-PLAN-2026-09-02.md, docs/PROJECT-REVIEW-2026-09-01.md,
docs/BENCHMARK-MATRIX-2026-09-01.md, docs/dataset D-BASELINE.md (long; read the last ~150 lines), docs/RECALL-UPSTREAM-SCOPE-2026-07-26.md,
docs/WINDOW-LOOP-AUDIT.md (sections 3-6), docs/RUNTIME-QUALITY-ASSESSMENT-2026-07-27.md, docs/ROADMAP-2026-07-23.md (sections 1.4, 5).

Answer these, decisively, with file:line or doc-section citations, most damaging first:
1. INVENTORY: which open issues in the source docs are MISSING from the analysis, and which listed items are duplicates or
   already closed? Be specific (doc + section).
2. STATUS: which "MEASURED/CONFIRMED" labels are not actually supported by the cited evidence, and which HYPOTHESIS items
   already have a measurement somewhere in docs/?
3. ROOT CAUSES: for each row where you disagree with the stated root cause, say what the evidence actually supports. In
   particular attack A1 (MS1 path = 425 s serial floor; is the arithmetic right given the [perf] tables quoted in
   RUNTIME-PLAN?), B2 (loader batch 64 vs 256 changes spectra: are the stated exclusions valid? what would you test?),
   C1 (MSFragger gap attribution), C2 (residual ppm is "ours"), D1 (two-point transform costs 12% peptides -- could
   something else in the mzPeak path explain it, e.g. IM calibration differences, band assignment, RT units?).
4. PLAN: is the ordering right? Name the single highest-value item that is mis-ranked, and anything that should be cut.
   Consider effort/gain honestly; note any step that lacks a pre-registered falsifier or a gate.
5. THE THING EVERYBODY MISSED: one issue not in any doc that the code or the numbers imply.

Format: numbered findings, each with severity (blocker / major / minor), one-paragraph rationale, and the concrete
correction to the document. Under 1,500 words. No praise, no summary of the document.
