**Answer: one TOF bin can produce several traces because a (frame, bin) cell of the grid can hold more than one peak.** The picker splits one ion's mobility peak into 2–3 centroids per frame, each with its own 1/K0. They all round to the same bin. The integer detector marks peaks as used, not grid cells, and a trace takes at most one peak per frame. So the leftover centroids in the same (frame, bin) start their own traces. The ±0.01 1/K0 gate then passes two of them to the same precursor, and both are written out with the same bin and calibration factor, which gives the exact duplicate.

**How it happens, step by step (file:line):**
1. **Picker.** `src/diaspextract.cpp:3696-3697` gives the OpenMS picker (`pickIMCluster`, `PeakPickerIM.cpp:992ff`) an IM box of 0.01 (`gate:delta_im`) and 15 ppm. A cluster grows along m/z-sorted neighbours and stops at the first neighbour that would make the box wider than that. A fragment's mobility peak is usually wider than 0.01, so one ion comes out as several centroids at almost the same m/z. `compactifyInto` (:776) keeps each centroid with its own 1/K0, and the TOF conversion rounds them all to the same bin.
2. **Detector.** "Used" is one bit per peak (:1110), not per (frame, bin) cell. `best()` returns one peak per frame, filtered by 1/K0 around the trace's running centre (:1147). If the closest peak is already taken, it counts as a miss and no other peak is tried (:1153). With `ms2_min_length_sec 0` and `ms2_chrom_peak_snr 1` (:2307-2308), every leftover centroid above noise becomes a valid trace, usually of 1–3 points.
3. **Gate.** The ±`delta_im` window around the precursor (:3160) lets in two traces up to 0.02 apart. The faint-precursor rules (shrinkage and short traces, both starting at 1 point) also let in the 1-point pieces.
4. **Output.** `assembleOne_` (:3259) does not merge peaks. Only the twin fold merges peaks within 10 ppm (:2064), and only in folded spectra.

**Controlled reruns** (rc5, HeLa_22, 48 threads, all exit 0). "Excess" means duplicate peaks beyond the first in each group. "Near" means sorted neighbours 0 < Δ < 1e-4 Th in the same spectrum.

| variant | spectra | peaks | spectra w/ exact dup | exact groups | excess / peaks | near spectra / pairs |
|---|---|---|---|---|---|---|
| a defaults | 53,720 | 21.63M | 8,180 (15.2%) | 34,620 | 0.175% | 4,826 / 15,764 |
| b1 `cells_per_tile 0` | same counts as a | | | | | |
| b2 `tile:rt_sec -1` (no RT cut) | 53,758 | 21.57M | 8,223 | 34,547 | 0.175% | 4,835 / 15,651 |
| c `trace_bands 1` (1 is valid) | 53,720 | 21.63M | 8,174 | 34,590 | 0.175% | 4,826 / 15,764 |
| d no twin fold | 107,720 | 26.46M | 54,533 (50.6%) | 268,800 | 1.10% | 31,561 / 113,724 |
| e 1.4 gate | 35,954 | 1.32M | 1,228 (3.4%) | 2,097 | 0.160% | 386 / 540 |
| f `delta_im 0.005` (picker, tracer and gate) | 61,133 | 18.58M | 8,942 | 31,399 | 0.180% | 4,813 / 13,162 |
| g `fragment_delta_im 0.005` (gate only) | 53,190 | 13.58M | 4,766 (9.0%) | 11,751 | 0.092% | 3,056 / 6,446 |
| h `ms2_split_valleys 0` | 53,410 | 20.79M | 7,213 | 28,661 | 0.151% | 3,690 / 10,811 |
| i `ms2_min_length_sec 3` | 53,564 | 10.21M | 7,872 | 28,987 | 0.299% | 5,061 / 15,857 |
| l picker/tracer 0.005, gate 0.01 | 62,150 | 27.66M | 11,732 (18.9%) | 75,754 | 0.311% | 6,558 / 30,927 |
| j picker/tracer 0.02, gate 0.01 | 37,654 | 12.82M | 3,436 (9.1%) | 8,973 | 0.074% | 2,329 / 5,481 |
| k picker/tracer 0.03, gate 0.01 | 31,789 | 9.62M | 2,174 (6.8%) | 4,488 | 0.048% | 1,619 / 3,280 |

- **Main driver:** with the gate held at 0.01, the duplicate rate follows the picker/tracer IM box: 0.311% → 0.175% → 0.074% → 0.048% of peaks (l → a → j → k). Narrowing only the gate (g) halves it, because the two members sit at different 1/K0.
- **Minor contributors:** tiles contribute nothing (b1), RT cells about 0.2% (b2), bands about 0.1% (c), and valley splitting about 17% (h).
- **The fold hides most of it:** without the fold (d), half of all spectra have duplicates.
- **Stricter gate, same rate:** the 1.4 gate (e) keeps the same per-peak rate; it just emits far fewer peaks.
- **Near ties are the same effect:** they are all Δ ≤ 1.1e-5 Th (median 1e-6 Th). That is the same bin with apex frames in different temperature steps (Frames.T1 steps about every 3.8 s), so they are not neighbouring bins.
- **Same ion, not a coincidence:** 72% of exact groups have another distinct m/z within 20 ppm in the same spectrum. By chance you would expect about 1%, so one ion is split into several traces.
- **Near-tie count differs from yours:** I get 4,826 near-tie spectra where you had 3,862. My definition probably differs from the one you used; the exact counts reproduce yours exactly (8,180 / 34,620 / 37,806, 11 equal-intensity groups).

**Per-pair separation from the gate dump.** Defaults: 150 targets. 124 matched (the rest lost to 6-digit rounding of precursor m/z ≥ 1000 in the dump), 529 groups, 377 resolved, 412 pairs. 1.4 gate: 80 targets, 85 groups, all resolved.

| | defaults (412 pairs) | 1.4 gate (85 pairs) |
|---|---|---|
| same apex frame | 40% | 41% |
| other frame of the same cycle (~0.1 s; each window is acquired in 2 back-to-back frames) | 25% | 35% |
| 1 cycle apart (~3.4 s) | 28% | 24% |
| ≥ 2 cycles apart | 7% | 0% |
| \|Δ1/K0\| ≥ 0.002 | 89% | 93% |
| \|Δ1/K0\| q25 / q50 / q90 / max | 0.004 / 0.008 / 0.014 / 0.019 | 0.008 / 0.011 / 0.015 / 0.019 |
| same frame and \|Δ1/K0\| < 0.002 (separated in neither) | 3% | 1% |
| smaller member's points | 1 point in 55%, median 3 | ≥ 3, median 8 |
| overlap with precursor, median | 1 | 3 |
| plain-Pearson fate of members | 356 `np`, 335 `overlap`, 70 `kept` | all `kept` |

**Direct proof of more than one peak per (frame, bin):** every same-apex-frame pair (165 of 165, and 35 of 35 under the 1.4 gate) has different apex intensities. Two different peaks therefore sit in one (frame, bin) cell; 152 of the 165 are at least 0.002 apart in 1/K0.

**What the pairs look like:**
- **Defaults:** mostly a full trace plus a 1–3-point piece of the same ion, separated in 1/K0 and eluting in the same cycle. These pieces get through only via the faint-precursor rules (`np`/`overlap` fate under plain Pearson).
- **1.4 gate:** two parallel full traces of one ion about 0.011 1/K0 apart, which is the picker's box width.

So the pairs are separated in 1/K0, not in RT. Only about 3% are separated in neither.

**Two points are inference, not measured:**
- That the several centroids come from one ion split by the 0.01 box, rather than from different co-isolated ions. The dose response, the spacing of about 0.01, the neighbouring bins and co-elution all point that way, but some identical fragments from different peptides (y1/y2, for example) may be mixed in.
- That the 1–3-cycle pairs are pieces left by the "taken counts as a miss" rule or by valley splitting. The dump has no frame spans, so I couldn't check this directly.

Everything is in `/scratch/kohlbach/dup_diag/experiments/` on ibminode05:
- `chain.log`, `chain2.log`, `chain3.log`
- `<variant>/{out.mzML,count.txt,dups.tsv}`
- `dump150/{targets.tsv,gate.tsv,pairs.tsv}` and `dump_e/…` (1.4 gate)
- `tools/` (the counter and the target, dump and pair-statistics scripts)