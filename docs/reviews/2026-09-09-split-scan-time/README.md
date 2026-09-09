Adversarial review of d85c2b4 (valley splitter scan time), 2026-09-09.

- codex.md — Codex / GPT-6 (gpt-6-astra): patch and plumbing correct; two defects fixed in 86444a5
  (upper-median gap estimator, ceil on an exact ratio); EPD's valley decisions are parent-global;
  a fixed point count is not a fixed time span.
- kimi.md — Kimi Code: same mechanics; should-fix taken in 3755121 (one run-wide scan time,
  warning when none); notes: MassTraceDetection's whole-trace min_sample_rate gate (MS1 default
  0.5) is a second tile-instability channel on the OpenMS-detector path; traces with <= 4 real
  points inside a tile are split unsmoothed (SavitzkyGolayFilter.h:94).
- Vibe: no answer -- ~/.vibe/config.toml has the bash tool at permission "ask" and every tool call
  was cancelled headless (see the memory note); not a model failure.

Disagreement, settled against the source (ElutionPeakDetection.cpp:255-300 at bd4b895): Kimi held
that minima acceptance is local (the ratio and min_dist tests are); Codex held that the DECISION is
parent-global -- and it is: when a valley fails, the loop keeps the taller maximum and advances the
other, so which maxima are compared at a later valley depends on maxima farther away. A fixed
scan time makes the smoothing local, not the decision; tile invariance needs bounded parents.
