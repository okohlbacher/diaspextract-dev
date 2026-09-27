**Why one TOF bin gives two traces in DIAspeXtract 1.5.0 (HeLa_22 output forensics)**

**Answer.** The premise doesn't hold: the grid the detector works on is three-dimensional (frame × TOF bin × 1/K0), not frame × bin. After `PeakPickerIM::pickIMCluster`, a single frame can hold two or more picked peaks in the same TOF bin at different 1/K0. `detectTracesInteger_` takes at most one peak per frame per trace (src/diaspextract.cpp:1133-1157, where equal-m/z ties go to "first of equals"). The peak left over in that bin seeds its own trace later. Because `trace:ms2_min_length_sec` is 0, a one-point trace counts as valid. Both traces then sit inside the precursor's ±0.01 1/K0 gate, and both export as `mzOf(bin, b[apex frame])`. When the two apex frames share a T1 value the m/z is bit-identical; when their T1 differs you get a near-tie.

**The data**
- Parsing reproduces the brief's counts: 34,620 exact-duplicate groups, 72,426 peaks (37,806 excess), 8,180 spectra.
- Near-ties (adjacent peaks 0 < Δ < 1e-4 Th): 15,764 pairs in 4,826 spectra by my definition. That differs from the brief's 3,862, which probably used another definition.
- 95.7% of fragments reproduce as `tofToMz(integer bin, b)` for one of the 1,847 distinct frame factors (90% bit-exact). This recovers each peak's bin.
- T1 stays constant over about 37 frames on average, so "exact" means same bin and same T1, not necessarily the same frame. "Near-tie" means same bin, different T1.
- Only 11 exact groups have equal intensities. The min/max intensity ratio has a median of 0.43.
- Duplicate peaks are strong ones: median intensity rank is the top 6.6% of their spectrum, against 50% for random fragments.

**What does not explain it (task 2)**
- **Band edges:** 0.237% of duplicate groups lie within 50 bins of one of the 11 edges, against 0.235% of all fragments. The 5× enrichment within 2 bins amounts to about 5 groups. Cross-band double claims are negligible.
- **Tile cuts:** spectra within 5, 10, 20 or 60 s of a cut have 14.9, 14.5, 14.3 and 14.6% duplicates, against 15.2% elsewhere. No effect.
- **Fragment m/z:** close to uniform. There is mild enrichment at 800–1200 Th (1.3–1.5×) and depletion below 200 Th. Duplicates fall inside the precursor's own isolation window twice as often as all fragments (12.3% vs 6.7%).
- **Isolation-window m/z position:** mild trend, 11.9% at the lower edge to 18.1% near the upper edge.
- **1/K0 edge:** precursors within 0.01 of an edge of the window's two ion-mobility slices have 1.8% duplicates, against 32% for those farther away. This is entirely the twin fold, not the edge. Those precursors are seen in both window groups, emitted twice, and 90% get folded, which fuses the duplicates. Among unfolded spectra the room to the edge has no effect.

**The discriminating pattern (task 4)**
- **Fold status:** all 34,620 groups and all near-ties are in unfolded spectra. Folded spectra, identified by fused off-grid peaks (35,117 spectra), have 0%. Unfolded spectra (18,603) have 44.0% with exact duplicates and 25.9% with near-ties. The 15.2% overall rate is diluted by the fold.
- **Fragment count:** within unfolded spectra, the rate scales with peaks per spectrum: 7.8% below 100, 51.8% at 100–249, 74.6% at 250–399, 92.1% at 400–500. That is about one duplicate group per 100 emitted peaks.
- **No real effect from anything else:**
  - Charge (unfolded): 39.8, 43.6, 48.2 and 49.7% for z = 1–4.
  - `spx_n_isotopes`: weak, 42.9% at 2 and 49–55% at 4–5.
  - RT: flat, 41–46%.
  - `spx_guessed` is 0 for every spectrum.
  - The output carries no marker for the faint gate, so it cannot be inferred.

**Recurrence (task 3)** Mostly the pairs are unique per spectrum, not one bad pair shared by many precursors.
- The 34,620 groups form 25,133 distinct (window, m/z) keys:
  - 75.2% of keys occur in one spectrum only.
  - 17.4% occur in 2, 6.7% in 3–5, 0.7% in more than 5; the maximum is 14.
- Recurring keys span a median of 3.5 s of RT (90th percentile 6.9 s); 40.7% of them fall in one MS1 frame.
- The same m/z value appears in a median of 3 neighbouring spectra (same window, ±10 s), but as a duplicate there in only 0.89 on average. The individual traces are shared among nearby precursors; the pairing mostly is not.

**Direct evidence from the gate dump** (40 unfolded targets; the 48-thread rerun reproduced the reference m/z and intensities exactly). I looked at the 104 exact and 32 near-tie pairs where the candidate set equals the emitted set.
- **Two traces at one printed m/z, differing in 1/K0:**
  - The exact pairs differ by a median |Δ1/K0| of 0.0087 (quartiles 0.004–0.0115); 29% differ by more than 0.01.
  - Only 1% have identical 1/K0. Valley-split siblings would inherit the parent's 1/K0 (`setCentroidIM`, :1307), so they account for about 1% of exact and 6% of near-tie pairs.
- **Apex frames of the exact pairs:**
  - same frame 39%;
  - the window group's second frame in the same cycle, 0.105 s later, 32% (each group is acquired in two consecutive frames per cycle);
  - one cycle apart 24%.
- **Same frame, same bin, different 1/K0** means the picked slab holds two peaks at one (frame, bin). Cross-band double claims are excluded by the band-edge null result above.
- **Near-tie apex frames** are one cycle apart in 78% of pairs, which is why their T1 differs.
- **Trace lengths:** the smaller trace has one point in 54% of exact pairs and at most two in 79%. The larger has a median of 5 points.
- **Admission:** these short traces get past the correlation gate through the concentric short-trace rule (`short_min_points` 1) and the Fisher shrinkage (from 1 point). That last step is inferred from the settings; the dump's own "fate" column does not model those rules.

Everything is in `/scratch/kohlbach/dup_diag/forensics/`:
- `parse.py`, `analyze.py`, `analyze2.py`, `analyze3.py`, `gdan.py`, `gdan2.py` and their `.log` files
- `frags.npz`, `recovered.npz`, `spec_feat.npz`, `groups.npz`
- `gd/targets.txt`, `gd/gate.tsv` (3.3M rows), `gd/e.log`
- `gd/pseudo.mzML`: the rerun output, 500 MB, safe to delete