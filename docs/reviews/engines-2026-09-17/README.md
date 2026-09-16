# Review: `engines` plan option (harness/corpus.py, 2026-09-17)

Commit under review: **2d2f93d** (`harness/corpus.py: optional plan key engines (Sage-only plans), G-V01/G-V13`),
written for the PXD029836 three-arm benchmark (plan `dwv_pxd029836`: diaTracer / DIAspeXtract 1.3.0 / diaWeaver
defaults on three public HeLa files, Sage only). Fix commit: the one that adds this directory.

| reviewer | invocation | result |
|---|---|---|
| kimi 0.42.0 | `dispatch.sh kimi brief.md kimi.md 2400` (worktree, left clean) | rc 0, 513 s, 6.6 KB, 5 findings (all LOW) |
| vibe 2.25.3 (mistral-medium-3.5) | `dispatch.sh vibe brief.md vibe.md 2400` (worktree, left clean) | rc 0, 115 s, 2.7 KB, 1 finding (MEDIUM, theoretical) |
| codex | not run: out of credit until 2026-09-17 17:41 | **review incomplete by this reviewer** |

The brief (`brief.md`) is self-contained: the commit diff, the functions it interacts with, the invariants and seven
questions. Both CLIs had updates available and were not upgraded (kimi 0.43.1, vibe 2.25.4).

## Findings and dispositions

| # | who | sev | finding | verdict | disposition |
|---|---|---|---|---|---|
| 1 | kimi 4, vibe 1 | LOW / MEDIUM | `engines: [sage, msfragger]` (a no-op spelling) makes a plan extended; on a finished plain plan every pair record fails `ready_arms` (no cells hash) and the whole plan re-runs | CONFIRMED by reading `ready_arms`/`measure_sha256` (a re-run, never a wrong number) | FIXED: G-V01 refuses naming both engines ("omit the key"); selftest refusal case; mutation E15 killed |
| 2 | kimi 5 | LOW | an ok search record killed before its charge split is "done" forever and renders `pending` forever | REFUTED: `run_search` writes only the search/score hashes, `add_split` adds the cells hash, `search_done` requires it for an extended plan, so such a search re-runs | none |
| 3 | kimi 1 | LOW | the table legend of a Sage-only plan still names the MSFragger jar/params/db and the fix/Scans steps | CONFIRMED, cosmetic; the engines line of the same legend says the tools never ran | OPEN (follow-up) |
| 4 | kimi 2 | LOW | `status` has no column for ok records of an engine the plan no longer runs (they vanish there; `table` refuses them, G-V13) | CONFIRMED, theoretical (needs `engines` edited after a run) | OPEN (follow-up) |
| 5 | kimi 3 | LOW | `rescore` iterates `ENGINES`, so it re-counts such stale records | CONFIRMED, theoretical; it cannot start an engine | OPEN (follow-up) |

Answers with no finding (both reviewers): no path runs, waits for or counts MSFragger in a Sage-only plan; plans
without `engines` are unchanged (the `or {}` normalisation only merges `None` with `{}`; the new G-V13 engine check
passes for every record a key-less plan can hold); `extended()` via `engines` alone is safe in every caller; the G-V01
check is complete; `sm()`/`ratio2()`/`num()` never confuse a real 0 with a missing engine.

## Proof around the review

- selftest 284/284 at 2d2f93d and at the fix (the fix turns one accepted list into a refusal).
- `mutate_d944dff1.txt`: 13/13 mutations killed on the reviewed file (control 284/284); `mutate_fb75a37a.txt`: the
  control, E1, E2 and the new E15 on the fixed file (E3-E14 target code the fix does not touch).
- `scripts/diff_render.py`: the 0d8532d harness and this one render byte-identical tables and dry-runs for plans
  without `engines`; `dry-run --local` of corpus_v3 (3 nodes), corpus_v3_selftest_v130 and dwv_stage1 byte-identical.
- measurement hashes unchanged: pair 3215b73e, search 064af71b, score 4fe0a1ce, cells c586f871.
