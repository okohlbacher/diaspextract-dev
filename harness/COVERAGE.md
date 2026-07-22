# Measured guard coverage (mutation testing)

**Not a claim — a measurement.** Produced by `mutate.py`, which disables each `die("G-…")`
call in turn and reruns the module's selftest.

```
KILLED    selftest failed  -> the guard is genuinely exercised
SURVIVED  selftest passed  -> the guard can be deleted and nothing notices
```

Reproduce:

```bash
python3 mutate.py bench2.py   --json /tmp/mut_bench.json
python3 mutate.py collate2.py --json /tmp/mut_collate.json
```

## Why this file exists

Two harness generations shipped guards that were documented, "tested", and inert.

v1 had six such guards; an external review classified them as theatre. v2 replaced them,
added a 64/88-case selftest, reported **64 passed, 0 FAILED** — and reproduced the same
failure. Disabling the content-digest comparison at `bench2.py:1387` (the guard for
**FAILURE 1**, the cross-sample comparison that was actually published as a wrong result)
left the suite fully green.

The selftest case for that guard *reimplements the comparison in its own body and calls
`die()` itself*. The production code is never reached.

**A passing selftest is not evidence a guard works.** The only acceptance criterion is:
delete the guard, and the suite must fail.

## Measured, 2026-07-22

| module | sites | KILLED | coverage | pure theatre |
|---|---|---|---|---|
| `bench2.py` | 120 | 34 | **28%** | G-B00, ~~G-B13~~ (fixed) |
| `collate2.py` | 65 | 30 | **46%** | G-C00, G-C10 |
| **total** | **185** | **64** | **35%** | |

**121 of 185 guard sites are unverified claims.** The harness is NOT adoptable as the sole
sanctioned benchmarking path in this state. `bench.py` v1 remains in use, with its
limitations known rather than disguised.

### Guards whose every site survived

| guard | what it claims | assessment |
|---|---|---|
| `G-B00` | pyyaml missing → abort | **acceptable untested.** Fires at import; the real failure mode is a loud `ImportError`. Not domain logic. |
| `G-C00` | pyarrow/pyteomics missing → abort | same. |
| `G-B13` | raw `.d` missing / retargeted | **was theatre — now 2/6**, both message-pinned. Sites 567–586 (post-run retarget detection) remain unverified. |
| `G-C10` | produce stage carries no acquisition window table | **REAL GAP.** This is the guard replacing v1's hardcoded `WINDOWS_S23` applied to every sample (FAILURE 8). Lines 1382, 1530, 2126 all survive. |

## The subtler defect: same-id fallthrough

`expect_abort` originally matched on **guard id alone**. Mutation showed that disabling
`raw not found` at `bench2.py:426` still left its assertion green — a *sibling*
`die("G-B13")` further down fired instead, reporting an unrelated condition
(`raw member analysis.tdf changed`). The suite could not tell the two apart.

So a SURVIVED site is ambiguous:

* genuinely untested, **or**
* tested, but masked by a sibling sharing its id — in which case that specific check can be
  deleted, detection of a distinct condition is lost, and the suite stays green.

**Same-id fallthrough is itself a theatre mechanism.** `expect_abort` now takes `match=`,
which pins an assertion to the message and makes each site independently killable. It
immediately caught a wrong assumption in the first test written against it: a plain file
does not abort with "not a directory" (no such check exists) but falls through to
`contains no files` at `:447`.

**Every new guard test must pass `match=`.** Without it the test cannot distinguish which
check fired, and coverage numbers overstate protection.

## Gate

```bash
python3 mutate.py bench2.py --critical critical_guards.txt
```

Exits 3 if any listed guard survives. The critical set is guards covering failures that
have **already happened in this project**, held to 100% mutation coverage; everything else
is reported but not gated. Claiming protection everywhere and verifying it nowhere is what
produced two generations of theatre.

**The gate currently FAILS.** That is the accurate status, and it stays visible until the
listed guards are genuinely killed.

## Instrument limitations

* `mutate.py` replaces the `die()` **call**, not the detection logic. A guard whose
  condition is wrong but whose `die()` is reachable still shows KILLED.
* One mutant at a time; interacting guards are not tested jointly.
* Requires a green baseline — otherwise every mutant appears KILLED and the sweep reports
  perfect coverage. `mutate.py` aborts rather than reporting that.
* The AST extractor must match this interpreter (`python3` here is **3.7.4**, which has
  neither `ast.Constant` for strings nor `Call.end_lineno`). Matching only `ast.Constant`
  silently found **zero** sites — an instrument reporting perfect coverage because it
  measured nothing. `mutate.py` now cross-checks against a raw `die("G-` count and refuses
  to report if the two disagree.
* `collate2.py` is not yet patched with `match=` support; its coverage figure carries the
  same-id ambiguity described above.
