## ProSE diaTracer bisection: result

**Only one kind of edit restores ProSE's IDs on the diaTracer file: removing exact-duplicate fragment m/z values inside each spectrum.** Every metadata edit gives a PSM set identical to the unedited file.

No edit to the file brings the logged "Precursor error" back to about 10 ppm. That number depends on the isotope search window, not on the data. The real, isotope-corrected precursor error is 10.6–11.0 ppm in every diaTracer run, so the precursor m/z was never wrong.

On the full file, removing duplicates takes diaTracer from **187 to 5,962** target peptides at 1% FDR. That puts ProSE at 0.655 of Sage on diaTracer and 0.664 of Sage on our file.

### Setup
- **Node:** ibminode05, load 0.3–5 before each launch. All ProSE runs were sequential at `-threads 32`, about 12 s per subset run and 16–25 s per full run. All files are in `/scratch/kohlbach/prose_diag/isolate/`.
- **ProSE command:** the one in `engine.time`, with `-threads 32`. It includes `-Search:precursor:isotope_error_min -1 -Search:precursor:isotope_error_max 2`, which the original runs used but the brief's command leaves out.
- **Counting (`count_idxml.py`):** best score per sequence as written (with modifications), decoy only where `target_decoy` is `decoy`, targets counted up to the last rank with decoys/targets ≤ 1%. On the existing outputs it reproduces **187 and 5,758 exactly**.
- **Subset:** retention time 40–55 min in both files, 12,737 diaTracer spectra and 10,487 of ours. Built with `python3 mzml_edit.py SRC sub/NAME.mzML --rt-lo 40 --rt-hi 55 --index stale|fresh|none [--edit E]...`, streaming and stdlib only.
- **Duplicates in the subset:**
  - diaTracer: 261,208 of 4,006,428 peaks (6.5%), in 12,160 spectra.
  - Ours: 5,551 of 4,341,761 peaks, in 1,399 spectra.
  - (`dup_nature.py`) 68% of diaTracer's duplicate groups have identical intensity, and the first duplicate sits at a median 3.4% into the m/z-sorted peak list (10th–90th percentile 0.4–18.5%).

### Subset bisection (one edit each)
"Log prec" is ProSE's logged median/MAD; "annot" is the median absolute isotope-corrected error from the idXML.

| Variant | Matched spectra | 1% PSMs | 1% peptides | Log prec (ppm) | Log frag (ppm) | Annot (ppm) |
|---|---|---|---|---|---|---|
| dt_base (patched, unedited) | 7,130 | 39 | 34 | 651.10/630.08 | 10.38 | 10.93 |
| 17 edits (listed below) | 7,130 | 39 | 34 | 651.10/630.08 | 10.38 | 10.93 |
| dt_dedup_max (keep highest intensity) | 10,419 | 2,041 | **1,060** | 488.59/476.31 | 8.28 | 10.62 |
| dt_dedup_sum (sum intensities) | 10,417 | 1,975 | 1,057 | 467.31/455.70 | 8.30 | 10.66 |
| dt_jitter (all peaks kept; k-th repeat moved +2k ppm) | 10,794 | 2,069 | 1,082 | 486.09/473.87 | 8.23 | 10.65 |
| dt_meta_all_dedup (all metadata edits + dedup) | identical to dedup_max (same PSM hash) | | | | | |
| spx_base (ours) | 8,689 | 3,727 | 1,153 | 9.53/7.53 | 6.02 | 6.62 |
| spx_dedup_max | 8,804 | 4,090 | 1,217 | 9.31/7.27 | 5.91 | 6.54 |
| spx_jitter | 8,814 | 4,088 | 1,217 | 9.35/7.32 | 5.90 | 6.55 |
| spx_inject_dup1 (one exact duplicate at m/z rank n/3) | 8,659 | 3,302 | 1,115 | 9.79/7.86 | 6.24 | 6.71 |
| spx_inject_dup15 (duplicate every 15th peak) | 5,221 | 354 | **269** | 20.75/20.06 | 9.59 | 8.44 |

- **The 17 edits with no effect:** each gives an md5-identical sorted (MZ, score, sequence, charge) set, hash `7886e948…`, the same as the unedited subset.
  - `reenc` (the re-encoded file is byte-identical, md5 `53a41af0…`)
  - `dt_orig` (subset of the unpatched original)
  - `idx_fresh` and `idx_none`
  - `id_scan` (ids frame=N to scan=N)
  - `rt_sec`
  - `im_to_si` and `im_drop`
  - `iso_dia` (isolation offsets ±12.5)
  - `drop_pint` (peak intensity), `drop_cv` (MSn spectrum / positive scan), `drop_dpref`, `drop_title`
  - `rt_sort`
  - `meta_all` (all of these, plus RT sort, no index)
  - `mzsort`
  - `dropzero`
- **Why this points at ties:** the jitter variant removes no peaks and still restores IDs, so the cause is the exact m/z tie itself, not the extra peaks. Injecting duplicates into our file reproduces the collapse (1,153 → 269 peptides).
- **The mechanism** matches the earlier source audit:
  - `MatchedIterator.h:232` advances only when the distance strictly improves (`if (diff > d)`).
  - `HyperScore.cpp:137` builds the iterator with the experimental spectrum as the target.
  - So the first exact duplicate stops all matching of theoretical ions above it.

### Full files
| Run | Isotope range | Matched spectra | 1% PSMs | **1% peptides** | Log prec | Log frag | Annot | Off-isotope share |
|---|---|---|---|---|---|---|---|---|
| dt patched, unedited | -1..2 | 35,554 | 233 | 187 | 611.85/592.41 | 10.13 | 10.97 | 58.2% |
| dt original (no patch, valid index) | -1..2 | same as patched (same PSM hash) | | | | | | |
| **dt patched + dedup_max** | -1..2 | 50,806 | 11,051 | **5,962** | 436.50/426.12 | 8.27 | 10.64 | 51.8% |
| dt original + dedup_max | -1..2 | identical to the row above | | | | | | |
| dt patched + jitter | -1..2 | 52,609 | 11,059 | 5,926 | 456.83/445.79 | 8.23 | 10.68 | 52.2% |
| ours, unedited | -1..2 | 44,266 | 18,658 | 5,758 | 9.52/7.34 | 6.04 | 6.75 | 32.8% |
| ours + dedup_max | -1..2 | 44,845 | 20,912 | 6,068 | 9.32/7.11 | 5.89 | 6.69 | 32.2% |
| *Parameter check:* dt unedited | 0..0 | 27,381 | 178 | 176 | **10.68**/4.88 | 9.78 | 10.68 | 0 |
| *Parameter check:* dt + dedup | 0..0 | 45,402 | 9,010 | **6,280** | **10.54**/4.30 | 8.37 | 10.54 | 0 |
| *Parameter check:* dt + dedup | -2..1 | 50,762 | 13,303 | 6,045 | 465.75/454.87 | 8.15 | 10.67 | 52.4% |
| *Parameter check:* ours unedited | 0..0 | 41,139 | 17,777 | 5,831 | 6.61/3.93 | 6.09 | 6.61 | 0 |
| *Parameter check:* ours + dedup | 0..0 | 41,807 | 19,570 | 6,129 | 6.58/3.90 | 5.95 | 6.58 | 0 |

- **Reproducibility:** the 32-thread unedited diaTracer run has the same PSM hash (`05145f08…`) as the original 100-thread run, and the unpatched original gives the same hash. The selected-ion patch and the stale index make no difference to ProSE.
- **Against Sage and MSFragger** (from `/scratch/kohlbach/snp/report_hela.md:19-21`):

| Input | ProSE (fixed) | Sage | MSFragger | ProSE / Sage | ProSE / MSFragger |
|---|---|---|---|---|---|
| diaTracer | 5,962 | 9,096 | 8,118 | 0.655 | 0.734 |
| diaTracer, isotope 0..0 | 6,280 | 9,096 | 8,118 | 0.690 | — |
| Ours, unedited | 5,758 | 8,677 | 7,149 | 0.664 | 0.805 |

- **The ~10 ppm is controlled by a parameter, not the file:**
  - With isotope 0..0, the log shows 10.68 ppm on the unfixed file while peptides stay at 176.
  - With -1..2 it shows 436.5 ppm on the fixed file, even though 5,962 peptides pass.
  - Only isotope 0..0 plus dedup gives both about 10 ppm and normal counts (10.54 ppm, 6,280 peptides).
  - The logged median jumps once more than half the top hits sit on a non-zero isotope: 51.8–58.2% on diaTracer versus 32.8% on ours.

### Things to note (inferences, not tested)
- **Our own ProSE numbers are also low** because of the same bug: 5,758 → 6,068 peptides (+5.4%) after dedup.
- **Other diaTracer runs in `report_hela.md`:** the ProSE diaTracer column shows the same collapse in every HeLa run (140–1,158 peptides). I only tested HeLa_22.
- **Near-duplicates might also stall the matcher:** because it compares distances as `float`, two peaks closer than float precision could count as a tie. Our full file has 15,764 adjacent pairs 1.25e-4 Th apart or closer; diaTracer has 0. This is untested.
- **Fix options:** deduplicate the input before ProSE (`mzml_edit.py --edit dedup_max`), or make `MatchedIterator` advance on ties upstream. The OpenMS tree was not modified.

Everything is in `/scratch/kohlbach/prose_diag/isolate/` (5.3 GB, most of it the edited mzML copies in `sub/`, 3.9 GB):
- `mzml_edit.py`
- `count_idxml.py`
- `dup_nature.py`
- `run_all.sh`
- `run_full.sh`
- `variants_subset.txt`
- `variants_full.txt`
- `variants_full2.txt`
- `results_subset.jsonl`
- `results_full.jsonl`
- `results_full2.jsonl`
- `progress_{subset,full,full2}.log`
- `sub/*.mzML` and `sub/*.json` (edit summaries)
- `runs/<name>/{out.idXML,run.log,engine.time}`
- `test/` (smoke-test files)