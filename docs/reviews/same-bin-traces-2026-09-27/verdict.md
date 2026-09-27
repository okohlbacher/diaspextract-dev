**The leading explanation holds, and my attempt to refute it failed.** The integer detector does not trace a grid with one cell per (frame, TOF bin). It traces picked peaks, and one (frame, bin) often holds 2–3 peaks from the same ion at different 1/K0.

**My check:** I used the Bruker SDK to read the raw frames of 300 random exact-duplicate pairs and summed the signal at bin ±2 over both traces' frames. For all 400 pairs looked up, the SDK's m/z at that bin equals the exported m/z, so the bin is the raw TOF index. A single frame at 10 ng is just a few scattered ion hits and cannot separate anything, which is why I summed over frames. If a pair were two ions about 0.008 apart, the summed mobility peak would be wider, or show a second maximum, compared with one trace of equal signal. It does neither:
- **Peak width (FWHM, pair vs single trace), by signal level:** 0.0041/0.0041, 0.0062/0.0062, 0.0088/0.0077, 0.0103/0.0113, 0.0134/0.0124, 0.0155/0.0165.
- **Second-maximum rate:** the same as for single traces.

The check has power only for the strong pairs: the top signal level holds 42% of pairs, and there the peak is 0.0155 wide, well above the picker's 0.01 box.

**1. Mechanism (`src/diaspextract.cpp`)**
- **The picker slices one ion.** `pickIMCluster` gets a total 1/K0 span limit equal to `gate:delta_im` = 0.01 (:3696; `PeakPickerIM.cpp` :1119/:1153). It also stops growing at the first m/z-sorted neighbour that fails that limit. The slices round to the same bin (:964).
- **The tracer claims peaks, not cells.** Each trace takes one peak per frame. Same-bin candidates tie exactly, because the distance is computed from the bin. The tie goes to slab order, not to the nearer 1/K0 (:1151), and a taken winner counts as a miss (:1153). Peaks are marked taken one by one (:1216) and there is no minimum trace length (:2308). So the leftover slices become their own traces.
- **Nothing merges them.** The gate (:3160) admits both. `assembleOne_` (:3259) never merges equal bins. Only the twin fold does (10 ppm, :5164), and only in folded spectra: none of those have duplicates, against 44% of unfolded spectra.

| Mechanism | Share of duplicate groups | Evidence |
|---|---|---|
| 1/K0 slices in one (frame, bin): parallel traces (85%) or leftover pieces (13.5%) | ~98–99% | Audit's split of 2,147 pairs. With the gate fixed at 0.01, a picker box of 0.005/0.01/0.02/0.03 gives 0.311/0.175/0.074/0.048% duplicate peaks |
| Valley-split children keep the apex bin (:1322) | ~1% directly; also multiplies pairs (−14% with splitting off) | Identical 1/K0 in 1% of pairs; run h |
| Band edges: seeding is limited to the band (:1166), extension is not, and each band has its own taken set (:1110) | ~0.1% (30 groups) | `trace_bands` 1 vs 12 |
| Tile cuts / RT cells (:4944–4960) | 0–0.2% | One tile: identical output. No RT cut: −73 groups. No enrichment near cuts |
| Window groups, twin fold | 0 (the fold removes duplicates) | Without the fold, 50.6% of spectra have them |

**2. One ion split, not two ions.**
- In 72% of duplicate groups, another peak sits within 20 ppm in the same spectrum; about 1% would by chance.
- The rate follows the picker box, and the pair spacing matches it: 0.008 at defaults, 0.011 under the 1.4 gate.
- In 165 of 165 same-frame pairs the intensities differ, so these are two separate peaks in one cell.
- The smaller member has 1 point in 55% of pairs.
- The raw check above finds no second ion.

It is still inference that no pair consists of the same fragment (y1/y2) from two different peptides; the fewer duplicates below 200 Th suggest such pairs are rare.

**3. Fix.** The real fix belongs in the tracer. When a trace takes a bin in a frame, it should take and sum every free peak in that bin within its 1/K0 tolerance. It should skip taken peaks instead of counting a miss, and break ties by 1/K0 distance. The picker's box should also be separated from the gate. That makes your "one trace per bin" hold, per 1/K0 neighbourhood.

It does change other outputs:
- fewer MS2 traces (5.4% of picked MS2 peaks share a (frame, bin));
- stronger, fuller elution profiles, which changes correlations and admissions (the 1-point pieces that pass only through the faint-precursor rules disappear);
- different fragment-cap ranking and new digests, so it needs benchmarking on both engines plus entrapment.

The backlog's merge at assembly is right as a guard, because a spectrum must never carry two peaks at one m/z (ProSE loses ~5%). It should match by bin or ppm, not by exact m/z: the near-ties are the same bin under a different calibration temperature step (Δ ≤ 1.1e-5 Th). On its own it only hides the problem: the split pieces still compete in the gate and the cap.

**4. Other things this uncovered**
- **Tie rule (:1151):** OpenMS tracing float centroids almost never saw exact ties. On the integer grid they are systematic, so a trace can lose its own slice. This is a porting defect.
- **MS1 goes through the same picker with the 0.01 box** (:3705). MS1 traces are probably split the same way. The earlier finding of duplicate claims on one monoisotope may share this cause; that is speculation and I have not checked it.
- **Bands are not a clean partition.** The band count changes the output (30 groups).
- **The twin fold has been hiding this since 1.4.0.**
- **The backlog blames the TOF-bin export.** The export only makes the collision exact; a float export would give near-duplicates instead.
- **Gate dump:** it rounds precursor m/z to 6 digits, so targets at 1,000 or above are lost, and its fate column ignores the faint-precursor rules.

Everything is in `/scratch/kohlbach/dup_diag/verify/` on ibminode05:
- `rawmob.py`, `rawmob_w2.tsv` (single frame)
- `rawxim.py`, `rawxim.tsv` (summed over frames, with the single-trace controls)