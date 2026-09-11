### Adversarial Review: Corpus Harness (`harness/corpus.py`)

---

### 1. Resume bug: mzML files may linger after searches complete on a resumed queue

- **severity**: high
- **location**: `corpus.py:763-764` (units list) and `corpus.py:755-760` (`unit` function)
- **failure scenario**:
  1. Run 1: phase 1 completes for sample `S`, both searches for tool `dt` succeed and `unit` deletes `dt`'s mzML.
  2. Run 1 is interrupted (e.g., `SIGKILL`) *after* the mzML delete in `unit` but *before* the `unit` function returns (unlikely but possible with signal delivery timing).
     → Search records for `S.dt.sage` and `S.dt.msfragger` are already written (done in `finally` of `run_search` before `unit` deletes the mzML).
     → The mzML remains on disk (delete was interrupted).
  3. Run 2 (resume): `pair_done` returns `True` because outputs exist and are unchanged.
     → `pending(S, "dt", "sage")` and `pending(S, "dt", "msfragger")` are both `False` (records exist, status ok, tools_sha matches).
     → `any(pending(...))` is `False`, so `(S, "dt")` is **excluded** from `units`.
     → `unit` is never called for `(S, "dt")`; the mzML is **never deleted** and lingers indefinitely.
- **evidence**:
  ```python
  units = [(s, t) for s in q["samples"] if pair_done(...) for t in TOOLS if any(pending(s, t, e) for e in ENGINES)]
  ```
  `any(pending(...))` is `False` when all searches are already done, so the unit is skipped; the only place that deletes the mzML (`unit`, line 760) is never invoked.
- **fix**:
  1. Extend the `units` list to include **all** tools where `pair_done` is `True` (not just those with pending searches).
  2. In `unit()`, add an early exit for tools whose searches are all already done:
     ```python
     if all(not pending(s, tool, e) for e in ENGINES):
         Path(pairs[s["id"]]["arms"][tool]["output"]["path"]).unlink(missing_ok=True)
         return 0
     ```
  This ensures the mzML is always deleted after both searches succeed, even across resume boundaries.
- **confidence**: high

---

---

### 2. RSS unit label does not match actual unit (minor inconsistency with historical tables)

- **severity**: low
- **location**: `corpus.py:1418` (`gb = lambda a: "%.1f" % (a["peak_rss_kb"] / 1e6)`), `corpus.py:1488` (table header)
- **failure scenario**:
  The harness divides `peak_rss_kb` by `1e6` and labels the result **"GB"**. However, GNU `time -v` reports in **KiB** (1024-byte units) on Linux, so the correct conversion to GB (gigabytes, 10⁹ bytes) would be `kib * 1024 / 1e9 = kib / 976562.5`.
  The harness’s division by `1e6` yields values **~2.4 % lower** than true GB.
  This is **inconsistent** with the historical `bench_table.py` (which divides KiB by `1048576` and labels "GB", i.e., GiB labeled as GB) and with `bench/dnoise_table.py` (which divides by `1e6`).
- **evidence**:
  The harness’s docstring (`corpus.py:1475`) and CORPUS.md explicitly state **“RSS in GB = kB / 1e6”**, treating `time -v`’s units as kB (1000-byte). This is **intentional per decision D9** and was verified against proof-run numbers (e.g., `41807312 / 1e6 = 41.8 GB` matches the table).
- **fix**: None required; this is a known, documented decision. The label should be clarified to **"RSS (GB, from kB/1e6)"** in the table header to avoid confusion with GiB.
- **confidence**: high

---

---
---
---

## Checklist of categories examined and found **clean**

1. **Wrong pairing** – Every record stores `id`, `node`, `tool`, `pair_run`, `binary_sha256`, `jar_sha256`, `label`; the table renders from these fields. No misattribution found.
2. **Skipped or duplicated arms** – Resume logic (`pair_done`, `search_done`) is robust; a failed first arm stops the pair without re-running the other (G-V09). Duplication is prevented by atomic record writes and guard checks.
3. **Stale outputs/records** – `verify_mzml` enforces `mtime > start_epoch`, integer `spectrumList count`; `pair_done` refuses outputs with mismatched size/mtime or stale timestamps (G-V08, G-V11).
4. **Peptide counting** – `sage_peptides` and `msf_peptides` are **line-for-line ports** of `bench_table.py`’s `sage_peps`/`msf_peps` (the source of TNBC-TABLE.md and HELA-TABLE.md). Decoy rule (Sage: `rank == 1` + `peptide_q <= 0.01`; MSFragger: best `hyperscore` per `(peptide, modification_info)` with `all(p.startswith("rev_"))`) matches the historical code.
5. **Unit errors (RSS)** – The kB/1e6 decision is intentional (D9) and consistent within the harness. The only issue is the **low-severity** label mismatch noted above.
6. **RSS/wall mis-attribution** – Both measured under GNU `time -v`; wall parsed from `h:mm:ss`/`m:ss`; RSS read from `Maximum resident set size (kbytes)`. No mis-attribution found.
7. **Load contamination** – Load gate (G-V06) flags when 1-min load exceeds thresholds (24 for ≥200 cores, 12 otherwise) **or** our tools are running. Contended rows are explicitly flagged in the table.
8. **Deletion of wrong file/retention** – Staged raws are deleted in `finally` (G-V14); mzMLs deleted **after both searches succeed** (per design); collect excludes `stage/`, `tools/`, `*.mzML`, `*.mzBIN*`. The **only gap** is the resume bug (Finding 1).
9. **Patient-derived data** – Staged in-house raws (patient-derived) are **deleted after each pair** (G-V14); records/TSVs contain only peptide sequences and metadata, not raw spectra. Labels use dataset letters (A–F), not specimen IDs. Node-local roots are `0700` (G-V15). No lingering patient data found.
10. **Guards passing where they must abort** – All guards G-V01 to G-V15 are implemented with `die`/`die_queue` and tested in the 85-case selftest and 37-case guardtest. No guard fires only in selftest.
11. **Reporting "done" while cells missing** – The table omits incomplete rows from per-scheme/corpus totals; pending/failed cells render as `pending`/`FAILED G-Vxx`, never as 0 or missing numbers (G-V13). `QUEUE_DONE` counts failed cells explicitly.
