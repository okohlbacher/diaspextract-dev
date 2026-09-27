The two files differ in many ways, but none of the differences makes ProSE read the wrong precursor. The 611.85 ppm median in the log is not a real precursor error: it is computed without correcting for isotope error. The actual problem with the diaTracer spectra is poor target/decoy separation in scoring.

All files I created are under `/scratch/kohlbach/prose_diag/mzml_structdiff/`. The scripts are `mzml_struct.py`, `pass2.py`, `pass3.py`, `join_idxml.py` and `iso_err.py`. The results are in `{orig,patched,ours}.json`, `{orig,patched,ours}.spectra.tsv` (one row per spectrum), `pass2.json`, `pass3.json`, `join_idxml.json` and `iso_err.json`. The scans are streaming line scans in pure Python (the node has no numpy). They decode every binary array and check every index offset.

## Structural differences
"dt" is diaTracer, "orig" is `HeLa_22_diatracer.mzML`, "patched" is `patched.mzML`, "ours" is `pseudo.mzML`.

| Item | orig | patched | ours | Could it confuse a reader? |
|---|---|---|---|---|
| Spectra (spectrumList count) | 62,784 (62784) | 62,784 | 53,720 ("0000053720") | |
| Distinct `id=` values | 62,784, no duplicates | same | 53,720, no duplicates | No. The "ids may repeat" idea is **refuted** |
| ID format | `frame=N` with N = index+1 for every spectrum. N is not a frame number (spectrum 0 is at 83.1 min) | same | `spectrum=N` with N = index | YES for format-aware readers: dt declares **MS:1000768 Thermo nativeID format**. `SpectrumNativeIDParser.cpp:99-104` applies regex `scan=(\d+)` to it, which cannot match `frame=N`. `frame=` also looks like Bruker TDF but does not mean a frame |
| Spectrum title | `HeLa_22.d.N.N.z`, N and z consistent in 62,784/62,784 | same | absent | |
| `scan spectrumRef` | equals id in all | same | absent | |
| Sorted by RT | **NO**: 10,431 decreases, first at index 3 (83.13, 83.13, 86.72, 84.46 min) | same | yes | ProSE sorts after loading (`ProSEAlgorithm.cpp:1575`), so file order no longer holds |
| Distinct RT values | 1,742, up to 277 spectra per RT | same | 1,896, up to 89 per RT | `sortSpectra` uses unstable `std::sort` (`MSExperiment.cpp:794`), so the order of spectra with equal RT is not preserved |
| RT unit | minute (UO:0000031), 0.064–118.9 | same | second (UO:0000010), 0.38–7199 | OpenMS converts minutes to seconds (`MzMLHandler.cpp:2197-2200`) |
| ms level | 2 for all | same | 2 for all | |
| Precursors / selectedIons / isolationWindows / scans per spectrum | exactly 1 each | same | exactly 1 each | none has more than one |
| selected ion m/z (MS:1000744) | **absent** | present in all; equals isolation target exactly (0.0 ppm, 62,784/62,784) | present; equals target exactly (53,720/53,720) | For OpenMS the patch changes nothing: precursor m/z is taken from the isolation target (`MzMLHandler.cpp:2034-2037`) and only overwritten by a differing selected ion (1670-1690) |
| Isolation window offsets | ±0.004–0.024 m/z (median 0.012) | same | the DIA window: median 12.6/12.4, up to 25 m/z | ProSE does not read isolation offsets (grep finds no use) |
| Precursor inside its isolation window | n/a | True 62,784/62,784 | True 53,720/53,720 | |
| Charge state | present in all: z1 593, z2 50,091, z3 8,578, z4 3,522 | same | present in all: z1 882, z2 46,767, z3 5,611, z4 361, z5 99 | outside ProSE's 2–4 range: dt 593, ours 981 |
| Neutral mass outside 500–5000 | n/a | 112 | 245 | |
| Peak intensity (MS:1000042) | present in all | same | absent | |
| Ion mobility location | on `<scan>`, no unit attributes | same | on `<selectedIon>`, unit Vs/cm² | OpenMS stores scan-level IM only on the spectrum (`MzMLHandler.cpp:2152-2181`). Selected-ion IM goes to both precursor and spectrum (1762-1767). dt precursors therefore have no drift time |
| Array encoding | m/z and intensity both 64-bit, zlib | same | m/z 64-bit, intensity 32-bit, uncompressed | |
| `defaultArrayLength` / `arrayLength` / `encodedLength` vs decoded | all match | all match | all match | |
| Peaks per spectrum | min 4, median 298, p95 500, **max 500 (capped)** | same | min 3, median 396, p95 896, max 1522 | |
| **Peak order** | **sorted by intensity, descending, in all 62,784**; m/z ascending in only 28 | same | m/z ascending in all | Fixed by `sortSpectra(true)` (`ProSEAlgorithm.cpp:1575`, `MSExperiment.cpp:796-802`). Any reader that assumes m/z order breaks |
| Duplicate m/z peaks within a spectrum | **1,213,717 of 18.48M peaks (6.6%), in 59,983 spectra (96%)** | same | 37,806 of 21.6M (0.17%) | candidate scoring distortion (not tested) |
| Zero-intensity peaks | 483,183 (2.6%), in 46,965 spectra | same | 0 | ThresholdMower removes them (`ProSEAlgorithm.cpp:319-320`) |
| Spectra sharing an exact (RT, m/z, z) | **37,046 (59%)** in 18,255 groups; 17,641 groups also share the same IM; peak lists differ in every group | same | 2,275 in 1,080 groups; IM always differs | |
| Distinct (m/z, z) | 23,891 for 62,784 spectra; one exact m/z recurs at 25 RTs spanning 11–78 min | same | 51,108 | |
| mzML `version` attribute | missing | missing | 1.1.0 | OpenMS warns "No version attribute" (`MzMLHandler.cpp:1064-1066`) |
| **Index offsets** | valid: 62,784/62,784 point to the right `<spectrum id>` | **STALE: 62,783/62,784 wrong**; `indexListOffset` 410,282,276 points into base64 (file is 424,230,413 bytes) | valid 53,720/53,720 | Breaks any index-driven reader. OpenMS SAX loading ignores the index (`MzMLHandler.cpp:714`, 1417), so ProSE is not affected |

Other file checks:
- **`patched.mzML`:** it is the original plus exactly 62,784 injected MS:1000744 lines and a trailing newline. The index was never rewritten, which is why the offsets are stale.
- **`fixed.mzML` (the MSFragger input):** it is byte-identical to the original (both md5 `a2c946b8…`), so `fix_mzml_cvparams.py` changed nothing here.

## Do diaTracer precursors agree with ours?
I matched each dt precursor to one of ours with the same z, RT within ±15 s and 1/K0 within ±0.02. 43,646 of 62,784 matched:
- **Isotope step between the two:** same isotope 29,821 (68%); dt one isotope heavier 7,983 (18%); dt two isotopes heavier 2,819; dt one or two isotopes lighter 2,017 and 903.
- **m/z agreement on the same isotope:** dt minus ours has a median of −3.0 ppm (IQR −7.8 to +0.6, p5–p95 −18 to +23).

There is no systematic m/z offset.

## What ProSE actually read
I joined the ProSE idXML to the spectrum tables by `spectrum_reference`:
- **dt:** all 35,554 PSMs resolve to a spectrum, with MZ equal to the selected ion m/z, RT equal to 60 × minutes, and hit charge equal to the spectrum charge in all cases. The annotated `precursor_mz_error_ppm` is ≤25 ppm for 35,531 of them (median 10.97 ppm).
- **ours:** all 44,266 PSMs resolve the same way, with median 6.75 ppm.

**Why the log says 611.85 ppm.** The log summary computes `getPPM(pid.getMZ(), seq.getMZ(z))` with no isotope correction (`ProSEAlgorithm.cpp:2258-2262`). Rebuilding that number from the idXML (annotated error + isotope_error × 1.0033548/z) gives 617 ppm for dt (log: 611.85) and 9.53 ppm for ours (log: 9.52). The median is driven by the share of top hits that ProSE placed on a non-zero isotope:

| Top hits | isotope −1 / 0 / +1 / +2 | Share not at 0 | Targets / decoys |
|---|---|---|---|
| dt | 8,732 / 14,868 / 6,319 / 5,635 | 58% | 21,557 / 13,997 |
| ours | 6,119 / 29,735 / 4,527 / 3,885 | 33% | 36,745 / 7,521 |

My own top-hit target/decoy count at 1% gives 233 PSMs for dt and 18,658 for ours. That is only a sanity check, not ProSE's FDR.

**The command in the context is incomplete.** `engine.time` shows every run (spx closed, dt closed, dt iso) also passed `-Search:precursor:isotope_error_min -1 -Search:precursor:isotope_error_max 2`. The "iso" run added `-Search:precursor:isotopes -1 0 1 2`, which is a different parameter: `precursor:isotopes` defaults to {0,1} at `ProSEAlgorithm.cpp:86`, while `isotope_error_min/max` default to 0/2 at `FragmentIndex.cpp:2170-2171`. The two dt idXMLs differ only in the date on line 22.

**`scan_index` is not a file index.** It equals the file position for only 7,246 of 44,266 PSMs on ours and 1 of 35,554 on dt, because of the RT sort and unstable ordering of equal-RT spectra. Only `spectrum_reference` (the native ID) is safe for joining. This does not cause a mismatch inside ProSE: preprocessing, scoring and post-processing all run on the same in-place object (`ProSEAlgorithm.cpp:1306`, 1415, 1434).

## Conclusion
The file structure does not corrupt the precursor ProSE sees; the loss happens in scoring, where dt top hits separate poorly from decoys. The structural features I flag as candidates for that, **none of them tested yet**:
- 6.6% exact-duplicate fragment peaks, in 96% of spectra
- the hard 500-peak cap
- 59% of spectra sharing an exact (RT, m/z, z) with another spectrum
- a wider fragment error on dt (median 10.13 vs 6.04 ppm in the logs)

Separately, `patched.mzML`'s stale index will break any reader that seeks by the index. Fixing it means rewriting the index with the correct offsets (or dropping it).