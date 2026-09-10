# Adversarial review: cell grid, step 3a -- the band partition from the acquisition's m/z range

Scope: commit 1641a00 (`git show 1641a00`; parent 731cef5). Files: src/TdfLoad.h
(`loadTdfAcqRange`), src/spextractor.cpp (`TofAxis::acq_lo/acq_hi`, `loadTofAxis`, the mzPeak
axis path, the option `trace:band_edges`, the `wbands` block that logs both edge sets and picks
one, the `spx:band_edges` stamp), src/MzPeakStreamLoad.h (`MzPeakExactMz::acq_lo/acq_hi` read
from the embedded/sidecar tdf before the temp file is removed).

Context: the integer detector traces each isolation window in flight-time BANDS (uniform in
[tlo, thi]; `bnd[b] = tlo + b * (thi - tlo + 1) / nb`; a band seeds in its own core and may extend
anywhere; each band has its own `visited`, so band membership of a seed affects the output).
Until now tlo/thi were the window's resident peaks' extremes -- data-dependent, and a streaming
reader that holds only a tile's frames cannot reproduce them. Step 3a offers a run-level
alternative from metadata: tlo = 0, thi = max over the window's frozen frame table of
`tofOf(MzAcqRangeUpper, b_f)`. The judged plan (docs/reviews/2026-09-10-tiled-reader-plan/judge.md,
STEP 3a) calls this a G-class re-pin: the digest moves by a few bins at the top, gated on
Sage + MSFragger + entrapment on both benchmark acquisitions (running now). The default stays
`slab` until that gate; the change is the OPTION plus the logged pair.

Attack:
1. Is `thi_acq` a SUPERSET bound for every peak's bin in every frame of the window, under the
   calibration model (`TdfMzCalibration::mzToTof(mz, b)`: does a larger b give a larger or a
   smaller tof for fixed mz; is max over the frozen table's b values the right extremum; what if
   a picked peak's m/z exceeds MzAcqRangeUpper -- can the picker produce one; what does the
   per-cell superset assert ("cell bins outside the window's band edges") do then)? Is tlo = 0
   always <= every bin (tofOf clamps to 0)?
2. The metadata read: GlobalMetadata Values are TEXT; `atof`; keys missing (older tdfs) -> the
   option refuses with a message -- is the refusal reachable before any long work? The mzPeak
   path reads the range from the gunzipped temp tdf -- before `std::remove`? Sidecar tdf via
   SPEXTRACTOR_MZPEAK_TDF? A `.d` whose analysis.tdf lacks GlobalMetadata rows?
3. Identity at `slab`: is the default path byte-identical to the parent (the `[tof]` log line
   changed shape; `wbands` picks the slab pair; `frozen.at(k).b` is read inside the parallel loop
   -- read-only? `tofOf` on the frozen b per frame per window = 4,797 x 24 calls, negligible?).
4. The science gate design (scratchpad chain_step3a.sh, mirrored below): D at 600 slab vs
   acquisition on the same build with Sage, entrapment and MSFragger, set overlap; TNBC 009 at
   600 acquisition against the recorded slab arm (Sage 29,066; entrapment 27,238/201 = 1.08%;
   MSFragger 27,952). Is comparing TNBC against a RECORDED arm (a different binary, cell1/grid1)
   sound for a change this small, or must the slab arm be re-run on this build? What should the
   acceptance rule be (the release rule is entrapment <= base + 0.3 points and both engines
   within the run-to-run spread)?
5. What the streaming reader (3b) will need beyond this: `wbands` is still filled from the
   resident slabs' `toTof` pass; under `acquisition` the slab extremes are only logged -- can the
   block run without any slab (the frozen tables and the axis alone)? Does anything else in the
   window body still read the slab's extremes?

Report: numbered findings with severity, file:line, failure scenario, fix; then the attack lines
found sound.
