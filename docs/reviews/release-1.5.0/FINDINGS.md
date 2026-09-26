# 1.5.0 code review: findings and dispositions (2026-09-26)

Brief: brief.md (self-contained: `git diff v1.4.1..main -- src tests` + the rc2/rc3b defaults). Reviewers: kimi 2.0.2
(kimi.md, 3 high / 4 medium / 5 low), vibe 2.25.5 mistral-medium-3.5 (vibe.md, 14 items); **codex NOT RUN** (usage limit
until 2026-09-27 18:40, codex.md) -- the review is incomplete until codex has run on the same brief. Both CLIs refused
the first dispatch from a non-git cwd; re-run from inside the dev repo.

| id | finding | verdict | action |
|---|---|---|---|
| kimi H1 | faint classification `touched.size() <= N` is a step function on the window grid: tile invariance unproven | open, testable | the 1.5.0 dataset D gate (gate_D_150.sh R3 vs R3a one tile / R3b two cells / R3c 8 threads) is the proof; runs on ibminode05 after the corpus share |
| kimi H2 | Section B drops `auto` from the valid strings | refuted | stale context of the rc2 diff; the release branch is cut from main, `setValidStrings_` has {off, faint, auto} |
| kimi H3 / vibe 2 | no synthetic-trace tests for the gate modes | confirmed, deferred | the gate lives inside assembleOne_; extracting the three formulas into a testable header is a separate change (BACKLOG); coverage today = e2e 30 checks + gate D digests |
| kimi M1 | auto rule counts MS1 trace points, the gate counts window frames | confirmed by design | documented in the help/README ("MS1 points"); auto is off by default and its threshold was calibrated on that statistic |
| kimi M2 | NaN passes `c < min_corr` | confirmed, fixed | `if (!(c >= min_corr))` rejects NaN; no change for finite scores (digest-neutral) |
| kimi M3 | shrinkage silently replaces gate:min_correlation_points | confirmed, documented | help + README: "replaces gate:min_correlation_points with gate:shrink_min_points" |
| kimi M4 | cap_rank "raw r" is the logoverlap score under gate:coelution logoverlap | confirmed, documented | help + README say "raw co-elution score before shrinkage (Pearson, or the logoverlap score)" |
| kimi L1 / vibe 3 | umpire help says r^2, code max(r,0)^2 | confirmed, fixed | help text |
| kimi L2 | gate dump's rt fate uses delta_rt, not the faint window | confirmed, fixed | `g_drt` |
| kimi L3 | only spx:gate_adaptive stamped; shrinkage/colocation/short_traces/cap_rank/faint invisible in the header | confirmed, fixed | five stamps added (spx:gate_faint, spx:gate_shrinkage, spx:gate_colocation, spx:gate_short_traces, spx:cap_rank): 23 spx: keys; the digest ignores the header (pins unaffected); gate driver takes WANT_KEYS |
| kimi L4 | [pspan] n==0 bin | cosmetic | none (unreachable) |
| kimi L5 / vibe 6 | shrink_prior_r "0 = no co-elution" misleads at default 0.6 | confirmed, fixed | help + README reworded |
| vibe 1 | gate:adaptive help omits auto | confirmed, fixed | help text |
| vibe 4 | Fisher variance degenerate at overlap <= 3 | by design | prior-dominated at 1-3 points; that is why the mode is confined to faint precursors (adaptive); documented in shrink_min_points |
| vibe 5 | cap partial_sort not stable -> nondeterministic | refuted | the comparator breaks ties on m/z then index (src: "Ties break on m/z, then index") |
| vibe 7 | concentric score never exceeds min_corr | by design | short traces rank as borderline evidence |
| vibe 8-14, kimi "found fine" | dnoise recoverPoint, auto rule serial, pspan atomics, dump mutex, zero-length spans, ln(1+I) at 0, hot loop, digest with modes off | fine | none |

Code changes from this review are on branch release-1.5.0 (help strings, NaN guard, dump fate, five header stamps); the
rc3b arm (a4f4cda) predates them, so the final arm must re-run the dataset D gate (WANT_KEYS=23) and the harness smoke.
