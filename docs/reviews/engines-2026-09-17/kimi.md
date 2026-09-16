• # Adversarial review: `engines` plan option (2d2f93d7e9c7)

  ## Findings

  **1. LOW — Table legend asserts the MSFragger pipeline ran when it never did.**
  Location: `render_cells_table`, the `head` "**Searches**" bullet (the `%(msf)s` / `%(msf_params)s` / `%(msf_db)s` shas plus "diaTracer patched before Sage; `fix_mzml_cvparams.py` before MSFragger for every arm; … MSFragger `Scans` = spectra").
  Concrete input: `table --plan dwv_pxd029836` renders a legend naming the MSFragger jar/params/db shas (taken from `oks[0]["tools_sha256"]`, i.e. the installed-but-unused run-local copies) and stating the fix step and `Scans` check happened for every arm. Only the separate `engines_line` ("its tools stay installed and pinned, never run") contradicts it. No wrong number, but a published table contains assertions about steps that did not run.
  Bites on real data: no (cosmetic/interpretive; `engines_line` mitigates).

  **2. LOW — `status` silently drops records of a dropped engine instead of marking them stale.**
  Location: `cmd_status` — `cols` is built from `q_engines(plan)`, so records of an engine no longer in the plan match no column and vanish entirely (no "stale" marker, since the lookup is per-column).
  Concrete input: run a plan with both engines to completion, edit to `engines: [sage]`, run `status`: the ok `*.msfragger` records are invisible; `table` then aborts with G-V13 naming `['msfragger']` but not the record files to remove, and there is no in-harness archive/exclude path. The refusal is correct (invariant 3); the invisibility makes remediation guesswork.
  Bites on real data: theoretical (requires editing `engines` after the run; dwv_pxd029836 starts Sage-only).

  **3. LOW — `rescore` iterates hardcoded `ENGINES`, not the plan's engines.**
  Location: `rescore` (`for e in ENGINES`).
  Concrete input: plan narrowed to `[sage]` with leftover ok MSFragger records on disk, then a peptide-rule change → `rescore` re-counts and rewrites the MSFragger records that `table` will refuse anyway. It cannot *launch* MSFragger (it only mutates existing records), so invariant 2 holds; the cost is wasted work and mutated stale records.
  Bites on real data: theoretical.

  **4. LOW — `engines: [sage, msfragger]` is accepted and silently converts a plain plan to extended, invalidating all its records.**
  Location: `extended()` (`or "engines" in q`) plus `check_extended` accepting the full list.
  Concrete input: `corpus_v3` completed; add `engines: [sage, msfragger]` (a spelling that looks like an explicit no-op); relaunch → `measure_sha256(True)` gains the cells hash, every pair record fails `ready_arms` (`m.get("cells")` None ≠ `c586f871`), and the entire extraction phase re-runs — not just searches. This is documented ("The key makes a plan extended") and it is a re-run, not a wrong number, but the full-list spelling is a trap.
  Bites on real data: theoretical for the stated plan (dwv_pxd029836 is `[sage]` from the start).

  **5. LOW (pre-existing, surfaced while checking Q1/Q4) — an ok search record without `by_charge` is "done" forever but renders `pending` forever.**
  Location: `search_done` (no `by_charge` requirement) vs `render_cells_table.search` (renders such a record as `pending`, comment claims "the next launch re-runs it").
  Concrete input: runner killed between `run_search`'s ok record write and `add_split` (Sage-only plan included): `pending()` is False, so the search is never re-run; `unit`/`sweep_outputs` delete the mzML because all configured engines are "done"; the table shows `pending` permanently with the data gone. Not introduced or worsened by this commit (same path exists in dwv_stage1), but the engines change adds a second table type that relies on it.
  Bites on real data: theoretical (narrow crash window; `add_split` is local TSV parsing).

  ## Per-question summary where no finding

  1. **No path runs/waits/counts MSFragger for `[sage]`.** Phase-2 units, `pending`, `ready_arms`, `pair_done`, `sweep_outputs`, and output deletion all follow `ctx["engines"]` (= `q_engines`); the MSFragger-first serial phase is gated on `"msfragger" in engines`; `add_split` only runs per executed engine; `status` columns, `table` (via `SG`/None) and `dry_run` (explicit gates) follow the plan. Sole exception is `rescore`'s hardcoded `ENGINES` (finding 3), which cannot start or wait for anything.
  2. **Plans without `engines` are unaffected.** `q_engines` and `extended()` reduce to the old definitions when the key is absent; the new G-V13 subset check passes for any records a key-less plan could legitimately hold (`{sage, msfragger[, entrap]}`); the `or {}` normalisation only merges `None` with `{}` (both mean "no cells") — a genuine cell-dict mismatch still refuses, and the byte-identical differential proof covers the `SG` refactor.
  3. **`extended()` via `engines` alone is safe in every caller.** `run_group` guards the empty rotation (`k = idx % len(names) if names else 0`), `noop_check` iterates nothing, `render_cells_table` renders the "no cells" shape (selftested end to end), `guardtest` refuses as documented.
  4. **Resume/staleness outcomes are refusal or re-run, never a silent number.** Narrowing: stale ok records of the dropped engine → G-V13 refusal; pending searches of it are abandoned and the mzML is deleted once the configured engines succeed (per design). Widening: the outputs are already deleted → `ready_arms` fails → the group re-runs whole (expensive with 16-h caps, but correct). Only `status` invisibility (finding 2) is silent, and it hides rather than misreports.
  5. **G-V01 is complete.** `[e for e in ENGINES if e in eng] != eng` enforces membership, ENGINES order, and no repeats in one comparison; a string, `[]`, null, booleans (`on`/`yes`), nested lists, `[Sage]`, `[sage, sage]`, `[msfragger, sage]`, and `entrap` are all refused (selftested). Note the accepted full list is finding 4.
  6. **No zero-vs-missing confusion.** `num(0)` → `"0"` vs `num(None)` → `"-"`; a real zero numerator gives `ratio2` `"0.00"`; totals over complete rows cannot be 0 (G-V13 refuses ok records with peptides ≤ 0, and `full` requires every arm/search ok), so `ratio2`'s falsy-denominator branch is only reachable for the None (engine-not-run) case.

  Verdict: no HIGH or MEDIUM findings. Invariants 1–4 hold; the dwv_stage1 adoption path (identical measure hashes, `cells` compared as dicts) is intact. Findings 1–3 are worth a follow-up commit; 4 is a documentation trap; 5 is pre-existing.

