**Root cause: diaTracer spectra contain many peaks with exactly the same m/z, and an upstream OpenMS iterator stops matching at the first such pair.** After that pair, ProSE's scoring cannot match any fragment ion further up the spectrum. The 611.85 ppm "Precursor error" in the log is not a precursor m/z problem. It is a side effect of near-random matches plus a log statistic that ignores isotope offsets. I confirmed the cause with a rerun: removing the duplicate peaks from the diaTracer file takes ProSE from 186 to 5,858 target peptides at 1% FDR.

One correction to the brief: both existing ProSE runs already used `-Search:precursor:isotope_error_min -1 -Search:precursor:isotope_error_max 2` (see `engine.time`). The runs differed only in `precursor:isotopes`, which ProSE never reads.

Everything I created is in `/scratch/kohlbach/prose_diag/source-audit/`. The OpenMS tree was not modified. All paths below are relative to `/scratch/kohlbach/OpenMS/src/openms/`.

## Mechanisms, ranked

**1. Duplicate m/z peaks stall the matching iterator (confirmed, main cause)**
- **The bug** is in `include/OpenMS/DATASTRUCTURES/MatchedIterator.h:220-250` (`advanceTarget_`).
  - Line 232 only moves forward when the distance gets strictly smaller: `if (diff > d)`.
  - When two neighbouring peaks have the same m/z, the distance is equal, so line 238 steps back and stops.
  - The iterator never gets past that pair. Every later theoretical ion is compared against that one peak and fails.
- **Who is affected:**
  - HyperScore uses this iterator (`source/ANALYSIS/ID/HyperScore.cpp:137`).
  - So does the alignment that produces ProSE's fragment annotations and fragment errors (`include/OpenMS/COMPARISON/SpectrumAlignment.h:286`, called at `ProSEAlgorithm.cpp:488-493`).
  - This is upstream code; the only local patches are to the MzMLHandler writer.
- **ProSE's preprocessing does not remove the duplicates** (`ProSEAlgorithm.cpp:315-359`). In my emulation, 296 of 300 Sage-identified diaTracer spectra still contained at least one exact pair afterwards.
- **The fragment index makes it worse.** It counts every peak separately (`FragmentIndex.cpp:1380-1401`), so duplicates inflate candidate counts. Random candidates pass the 5-ion gate (`FragmentIndex.cpp:1447-1461`). Candidates that end up with zero matched ions are dropped (`ProSEAlgorithm.cpp:971`), which is why about 27k spectra got no match at all.
- **Evidence:**

| Measure | diaTracer (patched) | Ours (`pseudo.mzML`) |
|---|---|---|
| Exact-duplicate peaks | 1,213,717 of 18,483,111 (6.6%) | 37,806 of 21,630,500 (0.17%) |
| Median matched ions (ProSE), same peptide as Sage | 2 (Sage: 8) | 8 (Sage: 8) |
| Median matched ions, all ProSE top hits | 1 | 6 |
| ProSE top peptide agrees with Sage (1% FDR PSMs) | 31.6% | 86.7% |

  - The example annotations show the pattern: in frame=17892, Sage matches 16 ions but ProSE matches only b2 (244.13) and y2 (276.16). In most examples ProSE matched only ions below about 340 m/z.
  - Python emulation of ProSE preprocessing plus this iterator gives a median of 1 matched ion on diaTracer spectra. Correct nearest-peak matching gives 7, and removing duplicates restores 7.
- **Decisive rerun** (`dedup_mzml.py` keeps the highest intensity per m/z; same command, `-threads 32`):

| | Original diaTracer | Deduplicated diaTracer | Ours | Ours deduplicated |
|---|---|---|---|---|
| Matched spectra | 35,554 | 50,806 | 44,266 | 44,845 |
| Target peptides, 1% FDR | 186 | 5,858 | 5,653 | 5,967 |
| Agreement with Sage | 31.6% | 83.6% | 86.7% | — |

  My 186 and 5,653 reproduce your 187 and 5,758 closely. Our own file also loses about 5% of peptides to this bug.
- **Fix options:**
  - Change line 232 to advance on ties.
  - Merge equal-m/z peaks in `preprocessSpectra_`.
  - Workaround for now: deduplicate the input (`dedup_mzml.py`).

**2. The "Precursor error: median" line is misleading (confirmed, reporting artifact)**
- It is computed at `ProSEAlgorithm.cpp:2255-2263` and `2305-2312`, as the absolute error of `pid.getMZ()` against the peptide m/z at the reported charge, with no isotope correction. The PSM annotation at lines 509-521 does correct for it.
- It runs at line 1554, before any FDR filter. `FDR:PSM` defaults to 0 (line 174) and was not set, so decoys and random hits are included.
- Any hit matched at a non-zero isotope offset adds roughly 300-1000 ppm. The median jumps into that range once more than half the top hits are off-isotope:

| | Top hits at non-zero isotope offset | Logged median | Isotope-corrected median |
|---|---|---|---|
| diaTracer original | 58.2% (20,686 / 35,554) | 611.85 ppm | 10.97 ppm |
| diaTracer deduplicated | 51.8% | 436.50 ppm | 10.64 ppm |
| Ours | 32.8% | 9.52 ppm | 6.75 ppm |

- The "recommended 2390 ppm" tolerance it prints is equally meaningless.

**3. Isotope settings: one parameter does nothing, the other has the opposite sign to Sage's (confirmed, costs about 10%)**
- `precursor:isotopes` is never read (`ProSEAlgorithm.cpp:86-87, 257`; `FragmentIndex.cpp:2207-2208`). That is why changing it changed nothing.
- The active settings are `isotope_error_min/max`. The fragment index searches theoretical mass = observed + iso × 1.00336 (`FragmentIndex.cpp:1487-1490`).
- So ProSE's -1..2 covers a precursor picked one isotope too high, but not two too high. The code comment at `FragmentIndex.cpp:2166-2171` claims positive values handle high picks; the sign is inverted.
- Sage (setting -1..2, but opposite sign) found 2,067 of its 19,822 diaTracer PSMs (10.4%) two isotopes high; on ours that is 345 (1.2%). ProSE matched 0 of those 2,067 even after deduplication. Sage's one-high PSMs are found by ProSE at iso -1 (4,044 of 4,286).
- ProSE's iso +1 and +2 windows are essentially random: 50-53% of those hits are targets.
- **Fix:** set `isotope_error_min -2` (or -3) and `isotope_error_max 0` or 1.

**4. Precursor charge from the file overrides min/max charge (confirmed, not a differentiator)**
- If the file gives a charge, only that charge is searched and min/max charge are ignored (`FragmentIndex.cpp:2055-2065`; `ProSEAlgorithm.cpp:458-466`). Examples: 11 charge-1 PSMs on diaTracer, 25 charge-5 PSMs on ours despite max 4.
- Both files carry a charge state on every spectrum, so this does not explain the gap.

**5. Checked and ruled out**
- **Native-ID or RT collisions:** ProSE maps results by position in the RT-sorted spectrum list (loaded and sorted at `ProSEAlgorithm.cpp:2027-2036`; `scan_index` at 445). There is no map keyed by ID or RT. IDs are unique in both files (62,784 distinct in diaTracer).
- **Selected ion vs isolation window target:** the target sets the m/z first (`MzMLHandler.cpp:2034-2038`). The selected ion overrides it only if different (1670-1695); `getPrecursorMZSelectedIon` defaults to true (`PeakFileOptions.h:249`). In the patched file both values are equal, and the original file yields the same value, so patching does not matter to ProSE.
- **Fields ProSE does not read:** possible charge states (stored at `MzMLHandler.cpp:1719-1728`), isolation window offsets (2051-2080), `getUnchargedMass`.
- **Ion mobility on `<scan>` vs `<selectedIon>`:** both set the spectrum drift time (`MzMLHandler.cpp:2152-2184` and 1730-1767). ProSE uses it only as an output annotation (`ProSEAlgorithm.cpp:452-456`).
- **RT in minutes:** converted to seconds (`MzMLHandler.cpp:2195-2203`) and used only for sorting and output.
- **Unsorted m/z arrays:** 62,756 of the diaTracer spectra are unsorted in the file, but ProSE sorts them at `ProSEAlgorithm.cpp:2036`, 342 and 357.
- **Zero-intensity peaks:** 483,183 of them, removed by the threshold filter (default 0.05).
- **Array lengths:** no mismatches. No NaN values.
- **Other filters:** window filter, top-400 filter and deisotoping keep 7-8 matched ions in emulation, so they are not the cause.
- **Stale index:** the index in `patched.mzML` still points into the unpatched file (`indexListOffset` 410,282,276 in a 424,230,413-byte file). It is harmless for ProSE, which reads the XML sequentially, but could break index-based readers.

**Minor observation (not a cause):** Sage's signed precursor error on diaTracer has a median of -9.7 ppm (1st percentile -19.4) versus -3.1 on ours. That is still inside ±25 ppm; only 0.9% of PSMs fall outside ±20 ppm.

## Files
- **Scripts:** `psm_stats.py`, `join.py`, `sage_iso.py`, `peak_stats.py`, `weird.py`, `arrlen.py`, `sim_pre.py`, `sim_full.py`, `sim_mi.py`, `cmp_annot.py`, `pep_fdr.py`, `dedup_mzml.py`, `sim_pre_lib.py`, `sim_full_lib.py`
- **Deduplicated inputs:** `dt_dedup.mzML`, `spx_dedup.mzML`
- **Rerun outputs:** `prose_dedup/` and `prose_spx_dedup/`, each with `out.idXML`, `run.log`, `engine.time`
- **`fc.log`:** `build/bin/FileConverter` dates from Jul 18 and crashes on start with `UnregisteredParameter`, so it cannot be used for round-trip checks.