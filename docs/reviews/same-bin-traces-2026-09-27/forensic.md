**Answer: the integer detector does not trace on a (frame, TOF bin) grid. It traces *picked peaks*, and the IM picker leaves several picked peaks at the same bin in one frame, differing only in 1/K0.** The detector takes one peak per frame, so each of those mobility slices becomes its own trace, and every one of them carries the same apex bin. Nearly all the duplicates come from this. Band edges, tile cuts and windows add almost nothing.

**Evidence.** I ran the rc5 arm once with the gate dump and once as an instrumented copy built in my diag folder, both on ibminode05 with 48 threads. The binary arrays of both outputs are identical to the published `pseudo.mzML` (md5 `b5e54ca8…`), so the diagnostics changed nothing. I reproduced the observation exactly: 8,180/53,720 spectra, 37,806 extra peaks.
- **Picked MS2 peaks:** of 267.7M above noise, 14.5M (5.4%) share their (frame, bin) with another picked peak. 5.55M (2.1%) have a same-bin neighbour within 0.02 1/K0, so both can pass the ±0.01 gate.
- **Emitted fragments for 400 random duplicate spectra** (2,147 exact-duplicate pairs before the fragment cap; 1,492 of 1,748 groups reach the output):

| Share | What the pair looks like | Δ1/K0 (median) |
|---|---|---|
| 85.1% | Parallel: points in the same frames, but from different picked peaks. 63% sit either side of the precursor's 1/K0 | 0.0084 |
| 13.5% | Separate traces with no shared frame (interleaved, or 0–1 frame apart) | ≈0.008 |
| 1.1% | Valley-split children (identical 1/K0, disjoint frames) | 0 |
| 0.3% | Share one equal-intensity point at different 1/K0 (unclear) | — |
| 0 | Tile-cut pairs, re-seeds after ≥6 missed frames, band-edge pairs | — |

- **Exact vs near-equal m/z:** the exported m/z depends only on (bin, calibration factor of the apex frame). That factor changes only 1,846 times over 68,469 frames. So two same-bin traces print identical m/z when their apex frames share a factor (65% of exact pairs have different apex frames), and differ by less than 1e-4 Th when a factor step falls between them. The near-ties are the same effect.

**How it happens (file:line in `src/diaspextract.cpp`):**
1. **The picker splits one ion.** `pickIMCluster` is called at :1765, :1867 and :3911, set up at :3693–3698 with a 0.01 1/K0 tolerance (the `gate:delta_im` value) and 15 ppm. In OpenMS `PeakPickerIM.cpp` :1107–1165, a cluster's 1/K0 range may not exceed 0.01, and growth stops at the first m/z neighbour that fails. A mobility peak wider than 0.01 therefore becomes two or more centroids with nearly the same m/z. Rounding (:790 to 1e-5, then :964/:707 to the nearest bin) puts them on the same bin.
2. **The detector keeps the slices apart.** Every peak above 10 is a seed (:1036, SNR 1). Each trace takes one peak per frame: the closest in m/z within ±0.01 1/K0 of its running centre. If that peak is already taken it counts as a miss; the next one is not tried (:1153). "Taken" is tracked per picked peak (:1110, :1216), and single-point traces are valid (min length 0 at :2308, sample rate 0.5). So the leftover slice seeds a second trace, and each trace keeps its apex bin (:1226, :1234).
3. **Valley splits:** children take the bin of their apex (:1322). Same bin, different RT segment.
4. **Assembly keeps both:** the 1/K0 window (:3160) and RT gate (:3168) admit both slices, and nothing merges equal bins before `frags.emplace_back` (:3259).

**The other paths you asked about:**
- **Bands:** the fragment path has no halo and no core filter. A band only seeds in its own range (:1166) but can extend anywhere, and each band keeps its own "taken" set (:1110). A trace within about ±7 bins of one of the 11 edges can be traced by two bands. The "CORE" comment (:2630) belongs to the other detector used for MS1 (`detectTraces_`) and tests the float centroid, not the bin. Real but rare: 3 of the 14 equal-intensity groups in the output sit at the 523.8356 edge (bin 168,067).
- **Windows:** fragment traces are kept per window key (m/z range plus window group) and never mixed. This scheme acquires each m/z window in two groups, which yields two spectra for one precursor. The twin fold (`mergeTwins_`, :2062–2148) then merges peaks within 10 ppm, so it removes duplicates and cannot create them.
- **Tiles:** each tile reads exactly its own frames (checked :4632–4634). A trace crossing a 600-s cut exists twice: the carried pre-cut piece (:4944–4960, :5084) and the re-traced post-cut piece, same bin, never de-duplicated. The carry list is cleared per tile (:5184–5188). This only affects precursors near the 11 cuts and none turned up in the sample.

**Ranking:**
1. Picker IM slicing plus one-peak-per-frame tracing: about 99% of pairs. Most likely one ion cut into mobility slices; two different ions within one bin (≤6 ppm), in the same frames and within ±0.01 1/K0 can't be ruled out pair by pair.
2. Valley-split children: 1.1%, one ion split in time.
3. Band-edge double tracing: rare, one ion traced twice.
4. Tile cut plus carry: possible, 0 in the sample.
5. Re-seed after a gap: 0 in the sample. Window groups and the twin fold cannot cause it.

**Possible fixes (not tested, effect on peptide IDs unknown):** before tracing, merge same-bin picked peaks within the 1/K0 tolerance in each frame, summing their intensities. Or merge equal-bin fragments in `assembleOne_`.

Everything is in `/scratch/kohlbach/dup_diag/audit/`:
- `scan_dups.py`, `targets.txt`, `spectra.json`
- `gate_dump.tsv`, `run.log`
- `build/diaspextract_diag.cpp`, `build/diaspextract_diag`
- `emit.tsv`, `run_diag.log` (the `[dupdiag]` lines)
- `classify.py`, `classify_emit2.py`