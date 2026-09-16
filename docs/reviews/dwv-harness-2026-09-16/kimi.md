• Review of the inline diff only; nothing was run or modified. Findings are grouped by your questions, with the important ones first.

  ---

  ## 1. Plain plans unchanged — one real difference, plus a clean bill otherwise

  I walked every changed function against the old behavior for a plan without `cells`/`entrapment`:

  - `identity`/`build_identity`/`ldd_deps`: plain plans get no `cells` key (`cells(q)` is `{}`, falsy); `tree_sha256` is the old lambda verbatim; `ldd_deps` defaults `binary` to `SPX_BIN`. Only error-message text changed. OK.
  - `busy_patterns(env, {})`: `extra` is empty for plain; same list as before. OK.
  - `search_done`/`ready_arms`: old records have no `cells` in `measure_sha256`, plain `ctx["measure"]` has none either → `None == None`. The old `pair_done` accept/reject logic maps exactly onto `ready_arms == TOOLS` (the `continue`-vs-append inversion is correct: all-searches-done skips the file check, same as old `continue`). OK.
  - `rescore`/`sweep_outputs`/`preflight`/`install_tools`/`check_db_pins`/`tool_dest`: all use `ctx.get("tools", TOOLS)` / `db_keys(q)` / `plan_tool_keys(q)`, which collapse to the old constants for plain plans. OK.
  - `table_guards`: the `arms` filter (`status ok`) and the `"host" in a` filter are no-ops for plain ok-pairs, since `run_arm` always sets `host` and both arms are ok. OK.
  - `cmd_status`: `q_tools(plan)==TOOLS`, `cells_failed` absent on plain records, `group_flags` reduces to `pair_flags`. Byte-identical output. OK.
  - `measure_sha256(False)`: iterates `MEASURED` directly; selftest pins `PAIR_MEASURE_1_3_0`. OK.

  **Finding 1.1 (nit, does not bite this run):** `load_plan` — a registry plan carrying `entrapment: false` previously died at G-V01 ("unknown keys"); now `set(plan) - OPTIONAL_PLAN_KEYS` subtracts it and `check_extended` accepts a bool, so it silently loads as a plain plan. A stray/typo'd key is now accepted instead of refused. Everything else about plain plans is byte-equivalent as far as I can tell.

  ## 2. `mzml_scan` — mostly sound; two parsing caveats

  The state machine is correct for the verified OpenMS writer conventions (cvParam per line, `<binary>` on one line, `<spectrumList` doesn't match `b"<spectrum "`). Numpress terms are counted anywhere (incl. outside spectra) — conservative, fine. The `<binaryDataArray` reset of `arr` before each `<binary>` check is right; intensity arrays can't be mistaken for m/z.

  **Finding 2.1 (nit, theoretical): first-occurrence of `PREC_CV`.** MS:1002815 is the only one of the five that can legitimately appear twice (scan level and selectedIon). OpenMS writes `<scanList>` before `<precursorList>`, so the scan-level value wins. For G-V17 this is harmless (before/after compare identically either way), but the `im_zero`/`im_missing` cell statistics and the digest would silently use the scan-level value if the two ever differ. diaWeaver on the default .d path writes 0 anyway, so nothing bites here; worth one comment line, not code.

  **Finding 2.2 (nit, theoretical):** a self-closing `<spectrum .../>` would set `inside=True` and never see `</spectrum>`, merging all subsequent precursor cvParams into one phantom spectrum and undercounting silently. OpenMS never writes child-less spectra (and FileFilter removes empty ones), so this can't occur on the guarded path. The `n_decl = -1` fallback for a missing `defaultArrayLength` also silently poisons `peaks_total`/`peaks_median` rather than refusing — same category.

  On the two digest questions: two files with identical spectra but different precursor *strings* (`"0.90"` vs `"0.9"`) get the same digest via `repr(float(...))` — good; two files with identical precursor values but different *peaks* get the same `prec_digest` — by design (see 3). The `ids_re` strip is applied to the opening line and to lines containing `spectrumRef`; in real OpenMS output `id=`/`index=` appear nowhere else inside a spectrum, so the conditional is odd but not wrong.

  ## 3. `reencode` / G-V17 — fail-closed except for two gaps, one of which matters indirectly

  What is checked and closed: truncated arrays (`length_mismatch`), numpress-labelled arrays (`undecoded` + `numpress_terms`), unsorted m/z, count changes (three independent counts compared), RT/precursor drift (`prec_digest`), missing MS:1000744, tool failure, stale/unterminated output, and the raw file is kept on any failure. A zlib array *not* labelled MS:1000574 either trips `length_mismatch`/`unsorted` or raises — see 5 for what happens then.

  **Finding 3.1 (should-fix, theoretical for this run): peak data is never compared across the re-encode.** `before = mzml_scan(src)` runs with `decode=False`, so no `content_digest` exists for the raw file; only `prec_digest` (five metadata values) and spectrum count are compared. A FileFilter that reorders `fragment_trace_id`/`intensity` independently of m/z, or corrupts intensities, passes G-V17 cleanly and feeds Sage a plausible wrong file. The tool is sha-pinned and trusted, so this is a defense-in-depth gap, not an expected failure — but the guard's docstring ("the same spectra") overclaims.

  **Finding 3.2 (nit):** a spectrum with no m/z array at all passes G-V17 (no array → nothing decoded, count/precursor fine). Sage will then fail → G-V10 refusal, so it degrades to a refusal one stage later. Acceptable, but a one-line `missing_mz` tally would make it fail at the right guard.

  ## 4. `run_capped` / G-V16 — kill semantics are right; the exposure is the shared node, not the kill

  - Session kill: `start_new_session=True` + `killpg(SIGKILL)` covers GNU time and diaWeaver; `ProcessLookupError` handled; the `BaseException` path kills and reaps before re-raising, so a runner SIGTERM (SystemExit) cannot leave the tool running. The only escape is a runner SIGKILL — then the orphan keeps running and the next launch's busy gate *waits 20 min and proceeds contended* (load_gate never aborts after `load_wait_min`). Contention is measured and flagged, so the numbers come out flagged, not silently wrong. Acceptable, worth knowing.
  - Ordering: `stopped` is checked **before** `parse_time_log`/`check_exit` — correct, since a killed run's time log may be absent or report signal-with-exit-0. The race where the tool finishes cleanly just as the cap fires records it as killed (fail-safe direction). Fine.
  - **Finding 4.1 (should-fix, could bite this run): the memory floor fires on *node* MemAvailable, not on the cell's own usage.** On a shared 224-core node, another tenant (or the earlier `-Xmx400G` diaTracer arm's page-cache pressure) can push MemAvailable under 5% at hour 11 of a 12-h cell; the healthy cell is SIGKILLed, G-V16 aborts, and because `pair_done` requires every arm ready, the **whole ~26 h group re-runs** — pair included. It fails safe, but the expected cost of a false positive is a full day, and on this node the trigger is not under your control. A retry-once or a "floor sustained for N minutes" rule would keep the guard without the hair trigger.

  ## 5. `run_group` — non-Abort exceptions break the stated semantics (the main correctness finding)

  The per-cell `try` in `run_group` catches only `Abort`. But the new cell path raises plenty of non-Abort exceptions:

  - `mzml_scan(dst, decode=True)`: `zlib.error` (corrupt zlib array), `binascii.Error` (bad base64), `ValueError` from `array.frombytes` (byte length not a multiple of 4/8 — exactly what a subtly truncated array produces), `ValueError` from `float(prec[k])`/`float(im)`.
  - `int(row[iz])` in the charge-split functions.

  Any of these propagates past the cell loop into `run_group`'s outer `except Exception` → the group is recorded `failed/CRASH`, **the remaining cells never run**, and the whole group re-runs next launch. That directly contradicts the documented "a failed cell does not stop the next one", and it converts what should be a clean G-V17 cell failure into a group crash after (potentially) 12 h of compute. Same shape in `add_split`: only `Abort` is caught, so a `ValueError` from `sage_by_charge`/`msf_by_charge` propagates through `one_search`/`unit` and kills the phase-2 loop mid-queue.

  Concrete failing input: FileFilter writes a well-terminated mzML whose first m/z `<binary>` base64-decodes to 30 bytes with `defaultArrayLength="4"` — `array.array("d").frombytes` raises `ValueError` → group CRASH, `dwv_pickim` unrun.

  **Severity: should-fix** (wrap the cell body so unexpected exceptions become a failed cell with `guard="CRASH"`). It produces refusals, not wrong numbers, but on this run it costs a day and silently skips the second cell, which is precisely the failure mode the extended plan was built to tolerate.

  ## 6. No-op flag (G-V18) — can only false-negative, never false-positive

  - Two runs of the *same* arm: the digest is order-independent (sorted block hashes) and strips id/index/spectrumRef, so the unstable RT sort and `scan=N` renumbering are invisible to it — **provided diaWeaver's peak content itself is deterministic**. With `-threads 100`, if trace-id assignment or centroiding is thread-order-dependent, `dwv_default` and `dwv_pickim` differ by noise even when the flags are no-ops → `content_equal` false → a real no-op is **never flagged**. The check is sound in the flagging direction (two genuinely different arms colliding requires a sha256 collision), but a negative result ("differs") proves nothing if the tool is nondeterministic. The report text should say this explicitly; currently it only explains the digest, not its one-sidedness. Nit.
  - `noop_check` itself: KeyError-safe on the ok paths, the "reference cell failed → flagged, computed=False" branch is right.

  ## 7. Identity/provenance — `share/OpenMS` is unguarded (the main provenance gap)

  **Finding 7.1 (should-fix, realistic on a multi-launch run):** `cells_identity` hashes the binary, FileFilter, `lib/**`, and the ldd closure of both. It does **not** hash `share/OpenMS` — the 258 data files diaWeaver reads at runtime via `OPENMS_DATA_PATH`. `cell_provenance` only verifies `sha256_published:` entries for the binary/FileFilter/lib against current hashes; the `share_OpenMS_tree_sha256=` line in PROVENANCE is *never checked against anything*. `build_identity` doesn't carry it either, and `table_guards` compares only cell labels, not `cells_meta["openms_data_path"]`. Consequences, all invisible to G-V03/G-V04/G-V11/G-V13:

  - someone edits/adds a file under `share/OpenMS` on ceph between the two launches of this run (or before a resume) → different results, all guards green;
  - `env.sh` itself is not hashed: an edit repointing `OPENMS_DATA_PATH` (or adding a non-stripped variable) changes what the tool reads with no guard noticing.

  The fix is mechanical (hash the tree like `lib/`, compare to the PROVENANCE line, include in `build_identity`). Would it bite *this* run? Only if the arm tree is touched between launches — but the tree is on shared ceph, the run spans ~26 h plus any resume, and the PROVENANCE file already carries the value, so the publisher anticipated this exact check.

  ## 8. Counting rules — consistent, with one caught divergence

  - `sage_by_charge` vs `sage_peptides`: same filter (`rank=="1"`, `peptide_q<=0.01`), same distinct-peptide set. One genuine divergence: if a peptide has *both* a target and a decoy qualifying row and the decoy row has the higher discriminant score, `sage_peptides` counts it in `target_peptides` while `sage_by_charge` (one best row per peptide) does not. This **is** caught — `add_split` checks both `peptides` and `target_peptides` against the record and dies G-V19. Fail-closed, so the rules are "consistent or abort". Ties in best-score keep the first row in file order — deterministic per file, same as the reference rule's set semantics allow.
  - `msf_by_charge` vs `msf_peptides`: the key function, the `rev_` decoy test, and crucially the ordering are replicated exactly — `sorted(best.values(), reverse=True)` on `(hs, dec)` tuples equals `key=lambda v: (v[0], v[1]), reverse=True`, including the decoy-first tie-break; `cut = i+1` at the last `d/t<=0.01` index counts the same targets as `acc = t`. I could not construct a divergent input.
  - `entrap_strata` vs `score()`: same decoy skip, same best-PSM selection (`strictly greater`, file order), strata TSVs carry the verbatim joined line so `score()` re-parses identically; the partition and `target>0` checks are enforced; selftest verifies `all` against `score()` on the whole TSV. The only unguarded parse is `int(row[iz])` — a non-integer charge raises uncaught → see 5 (CRASH, not a wrong number).

  ## 9. Resume logic — sound, with one table-crash window

  - A search record cannot be *adopted* without its split: `search_done` requires `m["cells"] == ctx`, and only `add_split` writes that key. A group with a failed cell is never `pair_done` and the failed cell is never in `ready_arms`; ok arms are still searched, and on the whole-group re-run their stale records are superseded by `pair_run`. The `entrapment`-config change case (`rec["cells"] != ctx["cells"]`) re-runs the group, as the selftest pins.
  - **Finding 9.1 (should-fix, bites only if the table is rendered mid-crash):** a crash (or kill) between `run_search` writing its ok record and `add_split` leaves a record that is `ok` with no `by_charge` and no `cells` hash. Resume handles it (re-runs the search; mzML was not deleted because `unit()` died before the unlink). But `render_cells_table`: `complete` only checks `status == "ok"`, and the per-arm summary does `g["search"][t, "sage"]["by_charge"]["z2p"]["target_peptides"]` — **KeyError** if *all* ok search records lack the split (with a mix, `table_guards`' `one(measure_sha256)` aborts first; with a uniform crash window it passes, ≤1 distinct value). Given this run will likely have the table rendered at least once mid-flight, gate `complete` on `"by_charge" in r` for sage/msf records.
  - `rescore` iterates `ENGINES` only — entrapment records are never re-counted from TSV; if the score hash changes they're simply re-run whole (mzML is kept because `sweep_outputs` now requires entrap done too). Consistent, just note the asymmetry.

  ## 10. `stage_tdf` — clean, with one environmental leak (below)

  0700 on stage root, attempt dir and the `.d`; only the two files copied; pin/acq checks identical to `stage()`; deletion in `finally` covers failure and SIGTERM (`BaseException`), with the G-V14 escalation afterward; nothing written beside the raw; messages carry `s["id"]`, never the raw path. Nothing missed in the function itself.

  **Finding 10.1 (should-fix, can bite this run): `TMPDIR` is mode 0755.** `cell_env` sets `TMPDIR=q["jnatmp"]`, and the published `jnatmp` is `/scratch/kohlbach/jnatmp`, mode 0755. G-V15 checks that jnatmp is *writable* but never that it's *private*. Anything diaWeaver/FileFilter write through TMPDIR (OpenMS tools do use it on some code paths) lands world-readable on a shared node — patient-derived data outside the 0700 perimeter that every other rule enforces. Either chmod 0700 in preflight for extended plans or give cells a per-run 0700 tmpdir under `q["root"]`.

  ## 11. Table — no unguarded numbers; two robustness nits

  Every number traces to a guarded record (ok pair arm, ok search, `spectra_stats` from the G-V17 path); dt denominators are `>0` by G-V10/G-V13 so the ratios can't divide by zero. Nits:

  - `s_z2 / d_sz2 if d_sz2 else float("nan")` renders the literal string `nan` in a markdown table — a plausible-looking non-number; render `-` instead. Nit.
  - `arm()` returns `"FAILED None"` for a missing arm dict — cosmetic. Nit.
  - The KeyError window is Finding 9.1.

  ## 12. Anything else that could produce a plausible wrong number

  Nothing beyond the above rose to that bar. The genuinely dangerous class for a 26-h run is not wrong numbers but *expensive refusals*: Finding 5 (exception kills the second cell and the group), Finding 4.1 (neighbor-triggered memory kill forces a full re-run), and Finding 10.1 (privacy, not numeric). One small addition: the busy gate proceeds after `load_wait_min` even with a *previous runner's orphaned diaWeaver* matched by `busy_patterns` — the contention is flagged, so the number is marked, not wrong, but on this run 20 min of waiting then running alongside a zombie is a realistic scenario after any SIGKILLed attempt.

  ## Summary

  | # | Finding | Severity | Bites this run? |
  |---|---------|----------|-----------------|
  | 5 | Non-Abort exceptions in a cell/split crash the whole group; second cell skipped | should-fix | On malformed FileFilter output or odd TSV cell — low probability, day cost |
  | 7.1 | `share/OpenMS` and `env.sh` unpinned; `share_OpenMS_tree_sha256` never verified | should-fix | If the ceph arm tree is touched between launches/resume |
  | 10.1 | Cell TMPDIR (`jnatmp`) is 0755, not checked private | should-fix | If the fork writes temp files via TMPDIR |
  | 4.1 | Node-wide memory floor can be tripped by neighbors; full group re-runs | should-fix | Plausible on the shared 224-core node |
  | 9.1 | Ok search record without `by_charge` → KeyError in the summary | should-fix | Only if table rendered inside the crash window |
  | 3.1 | G-V17 never compares peak data across the re-encode | should-fix | Theoretical (pinned FileFilter) |
  | 1.1 | `entrapment: false` on a plain plan now accepted | nit | No |
  | 2.1/2.2 | MS:1002815 first-occurrence; self-closing spectrum; `n_decl=-1` | nit | No / theoretical |
  | 6 | G-V18 can only false-negative under tool nondeterminism | nit | Say so in the report |
  | 11 | `nan` rendered in summary; `FAILED None` | nit | Cosmetic |

  Everything else I probed — kill ordering in `run_capped`, resume/adoption invariants, counting-rule equivalence (including the MSFragger tie-break), staging hygiene, guard coverage of the re-encode — behaves as intended. The three measurement hashes being pinned plus the compat selftest block make the plain-plan claim well supported; I found no plain-plan divergence other than 1.1.

