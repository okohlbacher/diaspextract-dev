# ProSE on diaTracer spectra: diagnosis (2026-09-27)

**Verdict (confirmed by two independent interventions):** exact duplicate fragment m/z values stall OpenMS
`MatchedIterator` (`include/OpenMS/DATASTRUCTURES/MatchedIterator.h`, `advanceTarget_`, the `if (diff > d)` walk): at two
equal target values the distance ties, the iterator steps back and never passes the first duplicate, so HyperScore (and
SpectrumAlignment) ignore every peak above it. diaTracer 2.2.1 spectra carry 6.6 % duplicate peaks (95.5 % of spectra,
67 % of groups with equal intensity: copies emitted twice); ProSE then scores near-random hits.
The precursor m/z was never wrong: the logged "Precursor error: median 612 ppm" is an unfiltered, not isotope-corrected
median over all top hits (isotope-corrected: 10.96 ppm).

| HeLa_22 (10 ng) | ProSE peptides at 1 % |
|---|---|
| diaTracer, unedited | 187 |
| diaTracer, duplicates merged (data fix) | 5,962 |
| diaTracer, unedited, fixed iterator (code fix, LD_PRELOAD shim) | 5,945 |
| DIAspeXtract, unedited / merged / fixed iterator | 5,758 / 6,068 / 6,128 |

Secondary findings:
- **DIAspeXtract also emits exact duplicates** (15.2 % of spectra, 37,806 peaks; different intensities, i.e. distinct
  signals landing on one m/z: fragment m/z is exported from the integer TOF bin, src/diaspextract.cpp:3259) plus float
  near-ties < 1e-4 Th; costs ProSE ~5 %. Backlog item "Emitted fragments with identical m/z".
- ProSE's `precursor:isotopes` is never read; `isotope_error_min/max` has the opposite sign to Sage's (ProSE -2..1 ==
  Sage -1..2). diaTracer reports the M+1 peak as precursor for 26.2 % of its 1 % PSMs (ours 10.4 %).
- Every other metadata difference (ids, RT units, IM location, isolation offsets, index, patch) has no effect (17 edits,
  identical PSM hashes). diaTracer mzML conformance faults without effect: no `version` on `<mzML>`, no `<fileChecksum>`,
  "Thermo nativeID format" declared with `frame=N` ids.

Files: `fix_duplicate_peaks.py` (streaming, stdlib; merges equal-m/z peaks, rewrites index + SHA-1, verifies),
`MatchedIterator.h.diff` (proposed upstream fix), and the five agent reports (source audit, mzML diff, PSM forensics,
bisection, verification). Cluster originals: ibminode05:/scratch/kohlbach/prose_diag/.

## Upstream issue draft (OpenMS) — not filed
Title: "MatchedIterator never advances past equal target values: HyperScore/SpectrumAlignment ignore all peaks above the
first duplicate m/z". Repro: ref={0,1,2,3,4,5,6,7,13}, target={-0.01,2.5,2.5,3.5,7,11}, tol 0.5 → only 0,2,3 (expected
0,2,3,4,7). Impact: ProSE 187 vs 5,962 peptides on diaTracer output (PXD017703 run 22). Also affected: PScore, AScore,
QC FragmentMassError, QC PSMExplainedIonCurrent. Proposed fix in `MatchedIterator.h.diff` (existing test outputs unchanged);
plus isotope-corrected, FDR-filtered precursor-error diagnostics in ProSE and an equal-m/z merge/warning in preprocessing.
