Adversarial review of 8779a0b (per-cell detection, step 2 of the cell-atomic grid), 2026-09-09.

- codex.md -- Codex / GPT-6: detection exactness and rebase sound; fixes: the splitter's in.size()<2 guard, a total fragment sort, the odd-pitch remainder rule, the auto band count; the tiled reader's contract.
- refutation-judge.md -- four-lens refutation workflow + judge: sound-with-fixes; M1 record the gate, M2 freeze band edges/nb at run level before the tiled reader (assert the superset), M3 the probe is not G1; S1-S5.
- kimi.md -- Kimi Code (when it lands).

Fixes applied in the follow-up commit: S3 (guard), S4 (total sort), remainder rule, S1 (no grid without the integer detector), S2 (%.17g stamps), M2 partial (per-cell superset assert, perf:trace_bands=0 refused under cells), a tool-written window file for the probe, e2e check 15 (thread invariance at pitch > 0).
