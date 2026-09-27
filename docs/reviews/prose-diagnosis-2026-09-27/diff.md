**The precursor mass and the PSM-to-spectrum mapping are both correct. The 611.85 ppm in the ProSE log is a summary artifact, not a real mass error.** The actual cause is fragment scoring. Almost every diaTracer spectrum contains the same fragment m/z value twice. ProSE's peak matcher (`MatchedIterator`, used by HyperScore) treats the second copy as having overshot and gets stuck on it. After that, no theoretical ion at a higher m/z can match. Removing the exact duplicates and rerunning the original ProSE command raises the 1%-FDR target PSMs from 233 to 11,051 and unique target peptides from 197 to 6,126, about 31x.

All peptide counts here use my own measure: unique target sequences at 1% target-decoy FDR on PSMs. On the baseline that gives 197 (diaTracer) and 6,505 (ours), not your 187 and 5,758.

**(a) Same spectrum?** Yes.
- PeptideIdentification m/z, RT (minutes converted to seconds) and ion mobility equal the referenced spectrum's selected ion m/z, scan start time and 1/K0. There are 0 mismatches out of 35,554 (diaTracer) and 0 out of 44,266 (ours).
- diaTracer's `frame=N` ids are unique: no duplicates among 62,784 spectra.
- `scan_index` is ProSE's position after sorting by RT, not the mzML index. That does not matter, because the reference, m/z and RT all come from the same spectrum object (`ProSEAlgorithm.cpp:444-450`).

**(b) Which mass gives about 0 ppm?** Neither, and both give the same number, because the PeptideIdentification m/z and the spectrum's precursor are identical.
- My recomputed theoretical m/z agrees with the reported `precursor_mz_error_ppm` to within 0.008 ppm.
- After isotope correction, high-scoring diaTracer targets sit at a median of −8.8 ppm (5th–95th percentile −16.8 to −0.5). Sage sees the same offset independently on those spectra: −9.7 ppm median.
- This is a constant offset in diaTracer's precursor m/z, well inside the ±25 ppm window. Only 1 of Sage's 19,822 PSMs would fall outside it. Ours sits at −3.4 ppm.

**(c) Error histograms**

| Group | Isotope-corrected error | Isotope error |
|---|---|---|
| diaTracer, 233 targets at 1% FDR | 167 of 233 between −15 and −5 ppm (constant offset) | 0: 162, −1: 63, +1: 4, +2: 4 |
| diaTracer, all 13,997 decoys | flat, about 1,030–1,630 per 5-ppm bin | spread evenly: −1: 3,486, 0: 4,546, +1: 3,153, +2: 2,812 |
| Ours, 18,658 targets at 1% FDR | median −3.4 ppm | 0: 85%, −1: 10% |

- Raw errors cluster at isotope multiples, which follows from how ProSE builds its search windows.
- There is no charge mis-assignment: the hit charge equals the spectrum charge in 100% of PSMs.
- **The 611.85 ppm is reproduced exactly** (611.857) as the median absolute error over all top hits, decoys and random hits included, with no isotope correction (`ProSEAlgorithm.cpp:2255-2262`). Restricted to isotope-0 hits it is 10.19 ppm.
- The statistic jumps to hundreds of ppm whenever more than half the top hits have a non-zero isotope error. On diaTracer that is 58%, because most hits are random. It still reads 436.5 ppm after the fix, when 11,051 PSMs pass 1% FDR, so it tells you nothing about mass accuracy.

**(d) Control (ours):** the log's 9.52 ppm is reproduced (9.522), or 5.74 ppm for isotope-0 hits only.

**Root-cause evidence**
- **diaTracer peak arrays:**
  - All 62,784 spectra list peaks by descending intensity, not by m/z.
  - 59,725 spectra (95.1%) contain a non-zero exact-duplicate m/z. The first duplicate sits at a median m/z of 298.
  - 1.21M of 18.5M peaks are duplicates, and 483k peaks have zero intensity.
  - In ours, 8,180 spectra (15.2%) have duplicates, 0.2% of peaks.
- **The code:** `MatchedIterator.h:232` only moves on if the next peak is strictly closer (`if (diff > d)`), and the distance is a float (`PpmTrait`, around line 292). An exact duplicate is equally close, so the matcher steps back and stops at the first copy for every later theoretical ion. It is called from `HyperScore.cpp:137`, which ProSE uses at `ProSEAlgorithm.cpp:969`.
- **Simulation** on Sage's 1% PSMs (19,822 diaTracer, 29,385 ours):

| Input | Plain matching | This matcher | After de-duplication | Matches lost |
|---|---|---|---|---|
| diaTracer | 9 ions (median) | 1 | 9 | 89.5% |
| Ours | 9 | 8 | 9 | 11.7% |

- **ProSE's own output:** when its top hit is Sage's peptide, it matched a median of 2 ions (`num_matched_peaks`) where 9 are present in the raw spectrum. Ours: 8 of 9.
- **Rerun experiment**, exact original command at 32 threads, which reproduces the original output bit for bit (35,554 PSMs, 611.85 ppm):
  - De-duplicated diaTracer: 11,051 target PSMs at 1% FDR (111 decoys), 6,126 unique target peptides. ProSE agrees with Sage's peptide on 16,608 of 19,822 spectra, up from 6,262.
  - Sorting the peaks alone gives no gain (218), and dropping zeros alone changes nothing, because ProSE already removes zero-intensity peaks.
- **Ours de-duplicated:** 1% target PSMs 18,658 → 20,912 (+12%), peptides 6,505 → 6,916 (+6.3%). Our output is hit by the same bug, just less.

**Secondary findings**
1. **Isotope-error sign looks inverted.** In ProSE's convention, +k means the observed mass is lighter than theoretical (`FragmentIndex.cpp:1489-1490`, `ProSEAlgorithm.cpp:512-518`). The usual mis-pick (observed heavier) is therefore −k.
   - Sage finds diaTracer precursors heavier by 2 isotopes in 2,067 of its 1% PSMs (10.4%). ProSE cannot reach those with −1..2.
   - ProSE's +1 and +2 slots yield almost nothing: 129 and 132 of 11,051 PSMs.
   - The comment at `FragmentIndex.cpp:2165-2168` says the [0, +2] default targets upward mis-picks, which contradicts the code's own sign. This is my inference, not tested.
2. **`-Search:precursor:isotopes` does nothing in ProSE.** It is stored at `ProSEAlgorithm.cpp:257` and never read; the search uses `isotope_error_min`/`isotope_error_max`. That explains why changing it had no effect.
3. **The original command differs from the one in the brief.** Per `dt/prose_closed/engine.time`, it passed `-Search:precursor:isotope_error_min -1 -Search:precursor:isotope_error_max 2`.

Everything is in `/scratch/kohlbach/prose_diag/psm_forensics/`:
- Scripts: `forensics.py`, `frag_check.py`, `sim_matched.py`, `make_variant.py`, `dedup_generic.py`, `dupstats.py`
- Results: `dt.json`, `spx.json`, `dt_frag.json`, `spx_frag.json`, `dt_sim.json`, `spx_sim.json`, `v_*.json`, `*_tophits.tsv`, `*_fragcheck.tsv`
- Reruns: `var/nozero_dedup.mzML`, `var/spx_dedup.mzML`, `var/prose_*/{out.idXML,run.log}` (`run.log` in each rerun folder)