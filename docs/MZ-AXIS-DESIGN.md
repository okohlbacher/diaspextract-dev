# A global discrete m/z axis: design

**Origin.** User proposal, 2026-09-03: a TOF instrument measures integer flight times, so m/z is
discrete at the source. Define one global m/z axis and a spectrum becomes a vector of intensities.
This follows the global RT axis (already landed) and applies the same idea to the other dimension.

**Status.** Design + implementation on branch `mz-axis` in a separate worktree. To be reintegrated
and measured against the current head on memory, runtime and parallel occupancy.

## 1. What is already discrete, and what is thrown away

The compact peak store is *already* on a uniform integer m/z grid:

    constexpr double MZ_Q = 1e5;                  // m/z quantum = 1e-5 Da
    f.mzq.push_back((uint32_t)llround(mz * MZ_Q));

10 bytes per peak: `uint32` m/z index, `float` intensity, `uint16` mobility. 0.007 ppm at m/z 1400
against a 20 ppm trace tolerance, so the quantisation is 2,800x finer than anything downstream.

And then `materializeWindow()` throws it away:

    p.setMZ((double)f.mzq[i] / MZ_Q);

because the next stage is OpenMS `MassTraceDetection`, which takes a `PeakMap` of `double` m/z. So
every peak is converted back to a double, re-sorted, and matched by a parts-per-million tolerance
with a binary search per comparison -- on data that arrived as integers. That conversion is the
boundary this design removes.

## 2. Two candidate axes

| axis | index | size | spacing | every real peak lands exactly on one? |
|---|---|---|---|---|
| **uniform** | `round(mz * 1e5)` | ~1.7e8 values over m/z 100-1700 | 1e-5 Da (0.007 ppm at 1400) | yes, by construction of the compact store |
| **native TOF** | the instrument's flight-time bin | ~5e5 per frame | ~0.006 Da at m/z 600, widening with m/z | yes, for Bruker; recoverable as `round((sqrt(mz) - c0)/c1)` (already done in `MzPeakStreamLoad.h`, 2.5e-5 ppm against the vendor SDK) |

The native TOF axis is the more interesting one: it is ~340x smaller, and two peaks of the same ion
in different frames carry the SAME index, so "same ion" becomes integer equality rather than a
tolerance. Its drawback is that it exists only for TOF data with a recoverable calibration, and the
per-frame temperature correction means the index-to-m/z map is frame-dependent (the reason the exact
calibration recovery mattered: the archive's two-point transform is ~7 ppm off and cost 12% of
identifications).

**Decision: the working axis is the UNIFORM one, with the TOF axis as an input-side accelerator.**
The uniform axis works for every input (including non-Bruker mzML), is already what the compact
store holds, and is fine enough that quantisation cannot change a tolerance decision. The native TOF
index is what the *loader* can exploit to avoid a double round-trip, not what the algorithm should
depend on. This keeps one code path instead of two, which is the whole reason the compact store was
chosen over per-vendor readers in the first place.

## 3. The data structures

```cpp
/// The m/z axis is global, uniform and integer: index i means m/z = i / MZ_Q. Stored nowhere,
/// because it is an affine function of the index -- unlike the RT axis, which has to be a table.
using MzIdx = uint32_t;                       // m/z * 1e5, so <= 1.7e8 for m/z 1700
inline double mzOf(MzIdx i) { return (double)i / MZ_Q; }
inline MzIdx  idxOf(double mz) { return (MzIdx)llround(mz * MZ_Q); }
/// A tolerance in ppm becomes a tolerance in index units, exactly:
inline MzIdx  ppmSpan(MzIdx i, double ppm) { return (MzIdx)((double)i * ppm * 1e-6 + 0.5); }
```

A frame is what `CompactFrame` already is. A **peak** never becomes a `Peak1D` again:

```cpp
/// One window's peaks, frame-major, in index space. Replaces the materialised PeakMap.
struct PeakSlab
{
  vector<uint32_t> frame_off;   ///< size F+1; frame f owns [frame_off[f], frame_off[f+1])
  vector<MzIdx>    mz;          ///< ascending within each frame (the loader already sorts)
  vector<float>    inten;
  vector<uint16_t> imq;         ///< the same uint16 mobility quantum as the compact store
  vector<uint32_t> rt_index;    ///< size F: each frame's index on the GLOBAL RT axis
};
```

Per-peak cost is unchanged at 10 bytes, but the ~20 B/peak `Peak1D` + `FloatDataArray`
materialisation disappears, along with its per-`MSSpectrum` overhead. On S08 that materialisation is
the largest single per-window allocation.

A **trace** keeps the shape it has after the RT-axis change, with m/z now an index too:

```cpp
struct Trace
{
  MzIdx    mz;          ///< reported m/z as an index (apex peak's, per trace:mz_estimator)
  uint32_t rt;          ///< apex frame, on the global RT axis
  uint16_t imq;
  float    intensity;
  vector<uint32_t> xi;  ///< frame indices, ascending  (already landed)
  vector<float>    xv;
};
```

`double mz`, `double rt`, `double im` per trace become 4+4+2 bytes. At 6.4 M MS1 traces and ~8.5 M
fragment traces per window this is worth having, but it is not the point: the point is what it does
to the loops.

## 4. What the integer axis buys in the loops

**Trace detection becomes bucketing, not searching.** The current detector accepts a peak if it is
within `mass_error_ppm` of the trace's running centroid, which costs a binary search per candidate
and makes the cost superlinear in peaks per band (measured: 4 bands 18:25 wall / 163 GB against 12
bands 12:53 / 103 GB on S30). On an integer axis, peaks of one ion across frames differ by at most
`ppmSpan(mz, tol)` index units, so:

  * bucket peaks by `mz >> SHIFT` with `1 << SHIFT` chosen just above the largest tolerance span;
  * a trace's candidates are in its own bucket and the two neighbours -- O(1), no search;
  * the running centroid stays a `double` internally, so the acceptance decision is unchanged.

**Fragment-to-precursor m/z tests become integer comparisons.** The scorer excludes the precursor
peak (`fabs(f.mz - pc.mono_mz) < 0.01`) and optionally its isotopes; assembly dedups at 10 ppm.
These become integer differences against a precomputed span.

**Banding can be made exact, or provably not.** The band edges become index cut points and the halo
becomes an exact index count. Whether that makes banding exact depends on whether a trace's total
index span is boundable -- the drifting-centroid question raised in the banding review. If it is
not, the honest outcome is a bound enforced by construction (cap a trace's span in index units), and
banding becomes exact *by definition of the detector* rather than by hope.

## 5. Refactoring run, in order, each step compiling and testable

1. **Axis primitives + `Trace` in index space.** Mechanical; `mzOf`/`idxOf` at every boundary.
   Output must be byte-identical: the values are the same doubles, just reconstructed.
2. **`PeakSlab` and a slab-based window materialiser**, used only by a new detector; the OpenMS
   path stays live behind `trace:detector=openms|integer` so the two can be A/B'd on the same build.
3. **The integer-axis detector**: bucket, extend, split. This is the step that changes results, so
   it is gated and compared on identified peptides with both engines, never on a digest.
4. **Scorer and assembly in index space**, removing the remaining double comparisons.
5. **Banding on index cut points**, with the span bound made explicit.

Steps 1, 2, 4 are output-neutral and can be verified by the semantic digest. Step 3 is a new
algorithm and must clear the both-engines rule. Step 5 depends on the banding review's verdict.

## 6. How it will be measured on reintegration

Against the current head, on S30 and S08, 100 threads, same node:

| metric | why |
|---|---|
| wall time | the headline; diaTracer is 9:46 on S08 against our 22:39 |
| peak RSS | 152 GB is the number that forces the memory admission gate |
| window-loop parallel speedup | occupancy; 67.9x of 100 before the task pool |
| stage breakdown | whether the gain is where the design predicts (trace, 47%) |
| Sage + MSFragger peptides | steps 1/2/4 must not move them at all; step 3 must not lose them |
| entrapment FDR | any peptide gain must not be bought with false positives |

**Falsifier for the whole design:** if steps 1, 2 and 4 land byte-identical but neither runtime nor
peak memory improves by more than the ~2% replicate spread, then the double conversions were never
the cost and the remaining time is genuinely in the detector's arithmetic -- in which case step 3 is
the only thing worth doing, and it should be judged on its own.
