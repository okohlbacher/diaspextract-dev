**Verdict: CONFIRMED.** Exact duplicate fragment m/z values in the diaTracer spectra cause the collapse. They stall OpenMS `MatchedIterator`, so HyperScore only sees the part of each spectrum below the first duplicate. The precursor m/z is not wrong. I tried to break the claim in four ways and it held each time; along the way I corrected four details of the earlier report (listed at the end of section 3).

## 1. Code path, and whether it predicts the symptoms
All paths are relative to `/scratch/kohlbach/OpenMS/src/openms`.

- **Preprocessing keeps duplicates.** `ProSEAlgorithm.cpp:315-358` (`preprocessSpectra_`) sorts, deisotopes, runs WindowMower and NLargest(400), but never merges equal m/z. After it, 52,393 of the 52,729 diaTracer spectra that get scored still hold at least one exact duplicate (99.4%).
- **Scoring.** `:890` gets candidates from `querySpectrum`, `:969` calls `HyperScore::computeWithDetail`, and `:971` drops every candidate with `score == 0`.
- **The iterator.** `HyperScore.cpp:137` builds `MatchedIterator<PeakSpectrum,PpmTrait>(theo, exp, tol)`, so the experimental spectrum is the target. `MatchedIterator.h:220-256` (`advanceTarget_`) walks forward only while `if (diff > d)` holds (`:232`); otherwise it does `--it_tgt_; break;` (`:236-239`).
  - At two equal target values the second distance equals the first, so the iterator steps back onto the first.
  - Every later theoretical ion restarts there, hits the same tie, and steps back again. The iterator never passes the first duplicate.
  - The distances are `float` (`:228`, and `PpmTrait` at `:292-295`), so two distinct peaks whose distances round to the same float also tie.
- **Minimal test** (`mi_test`, using the vectors from `MatchedIterator_test.cpp`):
  - Stock iterator, target `{-0.01, 2.5, 3.5, 7, 11}`: `0→-0.01 2→2.5 3→2.5 4→3.5 7→7`.
  - Stock iterator, same target with 2.5 doubled: `0→-0.01 2→2.5 3→2.5` only. With tolerance 0 it finds nothing, so even the exact 7→7 match is lost.
  - Patched iterator: output identical to stock on the original vectors, and all pairs restored with the duplicate.
- **What the stall predicts, measured with an LD_PRELOAD probe** that re-runs every HyperScore call with both iterators (1,585,096 candidate scorings on unedited diaTracer):

| | Stock iterator | Fixed iterator |
|---|---|---|
| Scorings whose score differs | 1,528,633 (96.4%) | — |
| Matched fragment ions, total | 360,235 | 4,257,094 |
| Scorings with score 0 | 82.5% | 2.1% |

  - 83.8% of the intensity in the affected spectra sits above the first duplicate pair.
  - Top hits look close to random: median matched ions is 1 (5 when fixed), median score target/decoy is 0.39/0.28 (4.72/3.26 fixed), and 39.4% of top hits are decoys.
- **The "612 ppm" is predicted too.** `logSearchDiagnostics_` (`ProSEAlgorithm.cpp:2255-2263, 2307-2310`) takes the median of |ppm| over every top hit, with no FDR filter and no isotope correction.
  - With close-to-random hits spread over isotope errors -1..2, only 41.8% of top hits sit at isotope 0. The median therefore falls into the off-isotope group, whose median offset is 838 ppm.
  - My own recomputation from the idXML gives 611.86 ppm (the log says 611.85). The isotope-corrected median is 10.96 ppm, and the 233 PSMs that pass 1% FDR have an uncorrected median of 11.05 ppm.

## 2. Re-run of the decisive pair
Fresh directory, my own streaming dedup script, my own counting script, full files, `-threads 32`, run one after another (node load 0.5 at start, about 32 by the end, from other users).

| Run | Matched spectra | 1% PSMs | 1% peptides | Log prec (ppm) |
|---|---|---|---|---|
| dt unedited | 35,554 | 233 | **187** | 611.85 |
| dt + dedup | 50,806 | 11,051 | **5,962** | 436.50 |
| dt unedited + fixed iterator (shim) | 52,673 | 11,057 | **5,945** | 457.57 |
| dt + dedup + fixed iterator | identical to dt + dedup: 0 of 1,293,459 scorings differ | | | |
| ours unedited | 44,266 | 18,658 | 5,758 | 9.52 |
| ours + dedup | 44,845 | 20,912 | 6,068 | 9.32 |
| ours unedited + fixed iterator | 44,920 | 21,671 | 6,128 | 9.13 |
| ours + dedup + fixed iterator | 44,879 | 21,718 | 6,130 | 9.11 |

- **The shim is faithful.** In stock mode it gives the same hash over all hits as the stock run (`982f35ab…`), and so does the original 100-thread run.
- **Two independent interventions agree:** changing only the data (dedup) and changing only the code (fixed iterator) both bring diaTracer from 187 to about 5,950 peptides.

## 3. Control on our file
- **The script has no side effects.** In the 45,540 of our spectra that had no duplicates, all 37,369 top hits are identical between the unedited and deduplicated runs, with 0 differences.
- **But our aggregate numbers do change,** because our file has the defect too, in a smaller dose:
  - 8,180 of 53,720 spectra (15.2%) contain exact duplicates, 37,806 peaks in total. Only 11 of the 34,620 duplicate groups have equal intensities, so these are different signals landing on the same m/z. That points at our emitter.
  - Dedup gives +5.4% peptides (5,758 → 6,068).
- **The near-duplicate hypothesis is now tested, and it holds for our file.** On our deduplicated file, stock and fixed iterators still differ in 58,748 of 1,275,618 scorings. All of these are in spectra without exact duplicates; 3,862 spectra have adjacent peaks less than 1e-4 Th apart. The fix adds another +62 peptides (+1.0%) and +806 PSMs on top of dedup. diaTracer has none of these.

Four points where the earlier report is incomplete or the brief is wrong:
- **diaTracer spectrum ids are unique** (62,784 distinct), so the "repeating ids" idea in the brief is wrong.
- **A second consumer of the iterator is broken in the same tool.** `SpectrumAlignment.h:286` also uses `MatchedIterator`, called from `ProSEAlgorithm.cpp:488-493`. It produces the fragment annotations, fragment error and matched ion current, which are also Percolator features (`:721`). This is why the shim run logs "Fragment error median=0.00": the shim fixes HyperScore but not SpectrumAlignment. A fixed header plus a rebuild covers both.
- **Duplicates are also counted twice in candidate selection** (`FragmentIndex.cpp:1380-1403`, `queryPeaks`). The effect is negligible: 5,945 with duplicates kept versus 5,962 deduplicated.
- **diaTracer does have a real precursor quirk, but it is not the cause.** 26.2% of its 1% FDR PSMs have isotope error -1, meaning the reported precursor is the M+1 peak; ours is 10.4%. Its isotope-corrected error is 9.6 ppm versus our 5.4 ppm. This is why the logged median stays at 436–458 ppm even after the fix.

## 4. Whose bug
Both, but mainly OpenMS's.

- **OpenMS bug.** `MatchedIterator` only requires sorted input (`:36`), and sorted input with ties breaks it silently.
  - The same template is used in `PScore.cpp:170`, `AScore.cpp:331`, `SpectrumAlignment.h:286`, `QC/FragmentMassError.cpp:135` and `QC/PSMExplainedIonCurrent.cpp:120`, so all of these are exposed.
  - OpenMS's own `FileInfo -c` already reports "Error: Duplicate peak m/z" (`src/topp/FileInfo.cpp:1777-1786`), yet nothing warns or repairs at search time.
- **diaTracer: a data-quality defect, not a spec violation.**
  - 95.5% of its spectra and 6.57% of its peaks are duplicates; 66.9% of the groups have equal intensities, so these look like copies emitted twice.
  - The mzML 1.1 XSD sets no ordering or uniqueness rule on array values (`BinaryDataArrayType`, `mzML_1_10.xsd:783`). Ids satisfy `KEY_SPECTRUM_ID` (`:920-928`). I did not read the prose specification document ([HUPO-PSI mzML 1.1.0 spec](https://github.com/HUPO-PSI/mzML/blob/master/specification_document/mzML1.1.0_specificationDocument.doc); [psidev.info/mzML](https://www.psidev.info/mzML)).
- **Real diaTracer conformance faults that have no effect on ProSE:**
  - `<mzML>` lacks the required `version` attribute (XSD `:26`).
  - The indexed file lacks `<fileChecksum>`, which is required (`mzML_idx_1_10.xsd:1185`).
  - It declares "Thermo nativeID format" but uses `frame=N` ids.
  - Its detector terms use `accession="UNKNOWN"`.

## 5. Recommendations
**Workaround for the benchmark:** run `/scratch/kohlbach/prose_diag/verify/fix_duplicate_peaks.py IN OUT [--merge max|sum]` on every ProSE input, ours included, so the comparison stays fair.
- It streams and uses only the standard library. Spectra without duplicates are copied byte for byte.
- It rewrites the index and the SHA-1 checksum, then re-reads the output and exits non-zero if the check fails.
- It took 49 s on the diaTracer file and 17 s on ours.
- It fully restores diaTracer. On ours about 1% of peptides (the float near-ties) stay lost until OpenMS is fixed. `hs_shim.so` with `HS_SHIM_MODE=fixed` recovers them, but it does not fix SpectrumAlignment.
- Separately, our emitter should not write exact or near-duplicate fragments.

**Upstream issue (OpenMS):**
- **Title:** "MatchedIterator never advances past equal target values: HyperScore/SpectrumAlignment ignore all peaks above the first duplicate m/z (ProSE 187 vs 5,962 peptides)"
- **Reproduction:**
  - `ref={0,1,2,3,4,5,6,7,13}`, `target={-0.01,2.5,2.5,3.5,7,11}`, tolerance 0.5: yields only `0,2,3`.
  - ProSE on diaTracer 2.2.1 output for PXD017703 HeLa run 22: 187 peptides; after merging duplicates 5,962 (Sage 9,096, MSFragger 8,118).
- **Expected:** `0→-0.01, 2→2.5, 3→2.5, 4→3.5, 7→7`, and ProSE counts that do not depend on duplicate peaks.
- **Actual:** after the first repeated target value the iterator yields no pairs at all, even an exact 7→7. There is no warning.
- **Proposed change** (`MatchedIterator.h:227-247`; full diff in `verify/MatchedIterator.h.diff`): keep walking on ties, keep the first element with the smallest distance, and stop only when the distance gets strictly worse. The existing test outputs are unchanged, including "smaller value wins a tie".
```cpp
float diff = std::numeric_limits<float>::max();
CONT_IT best = it_tgt_;
do {
  auto d = TRAIT::getDiffAbsolute(*it_ref_, *it_tgt_);
  if (d < diff) { diff = d; best = it_tgt_; }
  else if (d > diff) break;          // ties keep walking
  ++it_tgt_;
} while (it_tgt_ != tgt_end_);
it_tgt_ = best;
```
- **Also proposed:**
  - A test section for duplicate targets and for float-tied targets.
  - Isotope-correct the `logSearchDiagnostics_` precursor error (as `:2428-2437` already does) and restrict it to FDR-passing hits.
  - Optionally merge equal m/z in `preprocessSpectra_` and warn when duplicates are present.

All files are in `/scratch/kohlbach/prose_diag/verify/`:
- `fix_duplicate_peaks.py`
- `tally.py`
- `conf_iso.py`
- `compare_runs.py`
- `gen_patch.py`
- `MatchedIterator.h.patched`
- `MatchedIterator.h.diff`
- `MatchedIteratorFixed.h`
- `hs_shim.cpp` and `hs_shim.so`
- `mi_test.cpp` and `mi_test`
- `run_verify.sh`
- `results_all.jsonl`
- `conf_iso.jsonl`
- `progress.log`
- `runs/*/{out.idXML,run.log,engine.time}` (the shim statistics are in `engine.time`)
- `mzml/{dt_patched_dedup,spx_dedup}.mzML`