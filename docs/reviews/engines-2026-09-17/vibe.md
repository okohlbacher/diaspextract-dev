## Adversarial review findings

---

### Answers to the seven questions

1. **No.** All phase-2 paths (`pending`, `unit`, `ready_arms`, `pair_done`, `sweep_outputs`, `rescore`, `add_split`) guard on `ctx.get("engines", ENGINES)`; the MSFragger-first serial phase explicitly skips when `"msfragger" not in engines`; `status`/`table`/`dry_run` use `q_engines(plan)`. No Sage-only plan runs, waits for, requires, or counts MSFragger.
2. **No.** Plain plans use `q_engines(plan) == ENGINES` (default), `extended()` remains `False`, `table_guards` normalises `None` to `{}` for cells, and the new G‑V13 engine check passes because records’ engines are a subset of the plan’s (both run). No change for `corpus_v3` or `dwv_stage1`.
3. **No.** `run_group` runs only the reference pair when `cells(q)` is empty; phase 2 iterates only `ctx.get("engines", ENGINES)`; `noop_check`, `render_cells_table`, and `guardtest` all key on `cells(q)` or `engines` and behave correctly for a plan with `engines` but no cells/entrapment.
4. **No silently wrong number.** Resume: old records lack the `cells` measurement hash (plain plan had `extended=False`, new plan has `extended=True`), so `search_done` → `False` and searches re-run. Table: G‑V13’s new `other = {r["engine"]} - set(q_engines(plan))` refuses mixed records. No stale adoption.
5. **Yes, complete.** G‑V01’s list comprehension `[e for e in ENGINES if e in eng]` enforces non-empty list, subset of `ENGINES`, in `ENGINES` order, without repeats. Catches: string, empty list, unknown engine, repeat, wrong order, `entrap`, `null`, YAML booleans. No value passes that later breaks.
6. **No.** `sm(t,g,f)` returns `None` iff `g not in engines`; `ratio2(a,b)` returns `"-"` when `b` is `None` (falsy), and `num(v)` returns `"-"` for `None`. In every summary-row call, numerator and denominator are for the *same* engine, so both are `None` or both are numbers; `ratio2(None, None)` → `"-"`, never `None/number`.

---

### Additional findings (ranked)

| # | Severity | Location | Failing input | Bites on real data |
|---|---|---|---|---|
| 1 | **MEDIUM** | `extended(q)` definition (`corpus.py:502–504`) | Plan with `engines: ["sage", "msfragger"]` (no `cells`, no `entrapment`) | **No (theoretical)** |
| | | | | Adding this key makes the plan *extended*, so `measure_sha256(True)` adds a `cells` hash; old plain records (no `cells` hash) fail `search_done` and re-run. By design, but unexpected if one adds a semantically equivalent `engines` key to a plain plan. |

---
**No HIGH-severity issues found.**  
Q1–Q6: all fine. Q7: one theoretical MEDIUM that would not bite in practice (the user requests `[sage]`, not the full list).
