Here are the adversarial findings, grouped by severity and whether they would bite on the 26‑h run.

---

## **BLOCKER (would bite on this run or violate critical constraints)**

| # | Function/line | Concrete failing input | Why it bites | Fix urgency |
|---|---------------|------------------------|--------------|-------------|
| **1** | `ready_arms` (corpus.py:931–950) | Plain plan record where all searches for a tool are done and its mzML was deleted by `sweep_outputs` | File check is **inverted**: it runs only when NOT all searches are done. Thus a deleted file passes, `pair_done` returns True, and the next run tries to read the missing mzML → crash. | **MUST FIX** |
| **2** | `stage_tdf` (corpus.py:1027–1050) | Any staged copy on a system with default umask | `shutil.copyfile` does **not** set file mode; `analysis.tdf` and `analysis.tdf_bin` end up with `0644`, readable by group/others in a `0700` directory → **violates patient-data rule**. | **MUST FIX** |
| **3** | `cells_identity`/`build_identity` (corpus.py:487–501) | A change to any file in `share/OpenMS` (OPENMS_DATA_PATH, 258 data files read at run time) | These files are **not hashed** in cell identity, so a different OpenMS data set can change cell output without any guard noticing → wrong numbers. | **MUST FIX** |
| **4** | `run_group` (corpus.py:1095–1099) | A `ValueError` or `zlib.error` raised in `mzml_scan` inside `run_cell` | Only `Abort` is caught as a cell failure; any other exception **fails the entire group** and prevents the other cell from running → violates "a failed cell does not stop the next one". | **MUST FIX** |
| **5** | `msf_by_charge` vs `msf_peptides` (corpus.py:1609–1643) | Tie in hyperscore at the 1% FDR boundary with decoy and target | `msf_by_charge` sorts by `(hyperscore, decoy)`; `msf_peptides` sorts by `hyperscore` only → **different tie-break** can cause the charge split to **not sum to the main count** (G-V19 check would fire, but only after 26 h). | **MUST FIX** |
| **6** | `mzml_scan` (corpus.py:1054–1086) | A diaWeaver output with an array labelled `MS:1000574` (zlib compression, the numpress fallback) | The code only decompresses `MS:1002312` (numpress linear) and marks any array with a numpress CV as `undecoded`; **MS:1000574 is neither**, so it tries to decode as plain base64 → decode fails → re-encode check fails (G-V17). But FileFilter can produce such arrays if numpress is enabled; and diaWeaver can produce them as fallback. | **MUST FIX** |

---

## **SHOULD-FIX (would bite on some inputs; will bite on this run only in edge cases)**

| # | Function/line | Failing input | Severity | Bites now? |
|---|---------------|---------------|----------|------------|
| **7** | `mzml_scan` (corpus.py:1072–1086) | Same as #6 but in the general case | Doesn’t handle zlib-compressed arrays (`MS:1000574`) even though FileFilter can output them if numpress is turned on. | Theoretical (FileFilter defaults to no numpress), but the code is fragile. |
| **8** | `ready_arms`/`pair_done` (corpus.py:931–950) | Old plain plan record from before this change | The new `ready_arms` uses `ctx.get("tools", TOOLS)` and `ctx.get("engines", ENGINES)`. For old records with `measure_sha256` lacking `"cells"`, this is handled, but the **file check inversion** (#1) is the real problem. |
| **9** | `rescore` (corpus.py:1703–1720) | Extended plan with entrapment and a changed peptide rule | Uses hard-coded `ENGINES` instead of `ctx.get("engines", ENGINES)` → **entrapment searches are never rescored**. | Theoretical (rescore is rarely used), but a latent bug. |
| **10** | `render_cells_table` (corpus.py:2956–3011) | A search record that somehow lacks `by_charge` | Accesses `r.get("by_charge") or {}` → renders `0` for charge counts while showing the main count. **Inconsistent table**. | Theoretical (add_split is supposed to run), but possible after a crash. |
| **11** | `noop_check` (corpus.py:1103–1112) | Two cells with identical m/z/intensity but different precursor metadata | Content digest equals but spectra differ. | Theoretical (content digest includes spectrum block minus id/index; precursor metadata is in the block, so this should not happen). |

---

## **NIT (theoretical, cosmetic, or pre-existing)**

| # | Function/line | Issue | Severity |
|---|---------------|-------|----------|
| **12** | `mzml_scan` | Only validates m/z arrays, not intensity arrays; assumes `<binary>...</binary>` on one line. | OK for OpenMS/diaWeaver (per facts), but brittle. |
| **13** | `mzml_scan` | Takes **first** occurrence of each PREC_CV accession. If a spectrum carries the same accession at scan and selectedIon level with different values, only the first is captured. | diaWeaver doesn’t do this per facts; OK for this run. |
| **14** | `run_capped` | No timeout on `p.wait()` after kill. | SIGKILL cannot be caught; not a real issue. |
| **15** | `sage_peptides` vs `sage_by_charge` | `sage_peptides` takes first PSM; `sage_by_charge` takes highest `sage_discriminant_score`. | Both count the same peptide → totals still match. Charge may differ but is not checked. Pre-existing. |

---

---

## **Critical answers to the numbered questions**

1. **Plain plans unchanged**
   **BLOCKER**: `ready_arms` inverts the file-existence check (checks when NOT all searches are done instead of when they are). This would cause `pair_done` to accept stale/deleted mzMLs for plain plans after `sweep_outputs` removed them → crash on next run.

2. **`mzml_scan`**
   **BLOCKER**: Cannot decode zlib-compressed arrays (`MS:1000574`); diaWeaver can produce these as a numpress fallback → re-encode check fails. Also, taking the first PREC_CV occurrence is safe for diaWeaver per facts.

3. **`reencode` / G‑V17**
   **SHOULD-FIX**: All explicit checks fail closed, but the underlying `mzml_scan` cannot handle `MS:1000574` (zlib) → a file with such arrays passes as `undecoded` and fails G‑V17. The check itself is correct.

4. **`run_capped` / G‑V16**
   **OK**: Process is killed with SIGKILL on wall cap or memory floor; runner SIGTERM also kills the child first. The `stopped` check is ordered after `kill_session`, which is correct. The only gap is non-Abort exceptions in the caller (#4).

5. **`run_group` exception handling**
   **BLOCKER**: Only `Abort` is caught as a cell failure; `ValueError`, `zlib.error`, etc. propagate to the group level → the other cell **does not run**, violating the design goal.

6. **No-op flag (G‑V18)**
   **OK**: Content digest is order-independent and includes spectrum blocks minus id/index. Two runs of the same arm will have the same content digest (diaWeaver’s unstable RT sort is handled by sorting the block hashes). Collision probability is negligible.

7. **Identity/provenance (G‑V03/G‑V04/G‑V11/G‑V13)**
   **BLOCKER**: `share/OpenMS` (258 data files) is **not hashed** in `cells_identity` → changes there go undetected. `OPENMS_DATA_PATH` is set, but its contents are not pinned.

8. **Counting rules**
   **BLOCKER**: `msf_by_charge` sorts by `(hyperscore, decoy)`; `msf_peptides` sorts by `hyperscore` only → tie-break differs → charge split may not sum to the main count, firing G‑V19 after 26 h. `sage_by_charge` vs `sage_peptides` is cosmetic (same peptide count).

9. **Resume logic**
   **SHOULD-FIX**: `rescore` hard-codes `ENGINES` → entrapment searches are never rescored. A crash between `run_search` writing its record and `add_split` can leave a record without `by_charge`, but the table handles it gracefully.

10. **Patient-data staging (`stage_tdf`)**
    **BLOCKER**: Copied files retain default permissions (`0644`) → **readable by group/others** in a `0700` directory → violates patient-data constraint.

11. **Table (`render_cells_table`)**
    **OK**: No KeyError/ZeroDivision on real inputs; all accesses are guarded with `.get()` defaults. The only risk is a record without `by_charge` (see #9).

12. **Anything else**
    **BLOCKER**: File permissions (#10) and OPENMS_DATA_PATH (#7) would both bite on this run and violate hard constraints. The `mzml_scan` zlib gap (#6) would bite if diaWeaver falls back to `MS:1000574`.

---

## **What must be fixed before the 26‑h run**

1. **`ready_arms`**: Move the file-existence check **inside** the `if all(search_done(...))` branch (invert the condition).
2. **`stage_tdf`**: After `shutil.copyfile`, do `os.chmod(dst / f, 0o600)` for each copied file.
3. **`cells_identity`**: Add `share/OpenMS` to the hashed tree.
4. **`run_group` cell loop**: Catch `BaseException` (not just `Abort`) and convert non-queue, non-Abort exceptions to cell failures.
5. **`msf_by_charge`**: Change sort to `key=lambda v: -v[0]` (or keep `(v[0], v[1])` but ensure consistency with `msf_peptides`).
6. **`mzml_scan`**: Add decompression for `MS:1000574` (and any other zlib CVs) alongside `MS:1002312`.

Without fixes **1, 2, 3, 4, 6**, the 26‑h run can produce wrong numbers or violate patient-data constraints.
