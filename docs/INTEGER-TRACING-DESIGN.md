# Trace detection on integer arrays

**Why now.** After the scoring gate was fixed (parallel arrays, 2026-09-03) the window loop is
**90.9% trace detection** and 4.8% scoring. Everything else is rounding. Tracing is the tool.

**What it runs on today.** `materializeWindow()` rebuilds an OpenMS `PeakMap` from the compact store:
`Peak1D` (double m/z + float intensity) plus a parallel `FloatDataArray` of mobility, wrapped in an
`MSSpectrum` per frame -- ~20 B/peak against the store's 10 B, plus per-spectrum object overhead,
and every m/z is a double that was an integer twice over (a TOF bin, then a 1e-5 Da store index).
`MassTraceDetection` then matches by a ppm tolerance on those doubles.

**Goal.** Reimplement the SAME tracing semantics on integer arrays, with all three axes integer:

| axis | today | here |
|---|---|---|
| retention time | `double` per peak, per spectrum | `uint32` frame index on the global RT axis |
| m/z | `double`, twice-derived | `uint32` flight-time bin (`TofAxis`) |
| ion mobility | `double` 1/K0, from a `uint16` quantum | `uint16` TIMS scan index |

## 1. The mobility axis, derived without the vendor table

Within one frame the distinct 1/K0 values ARE the scans, so ranking them recovers the scan index
exactly: collect a frame's distinct mobility values (about a thousand), sort descending (1/K0 falls
as scan number rises), and a peak's rank is its scan. No TIMS calibration table is needed to say
that two peaks came from the same scan -- and comparing scans is what the gate actually wants,
because the calibrated value drifts frame to frame while the scan does not.

Tolerance conversion: `gate:delta_im` in 1/K0 becomes a scan count per frame, from that frame's own
ranked values. It is not a constant across frames, and pretending it is would be the same mistake as
a fixed ppm halo.

## 2. The data structure

```cpp
struct PeakSlab                    // one window, frame-major, 10 B/peak, no OpenMS objects
{
  vector<uint32_t> frame_off;      // F+1: frame f owns [frame_off[f], frame_off[f+1])
  vector<uint32_t> rt_index;       // F: frame -> global RT axis
  vector<double>   b;              // F: calibration factor, for export only
  vector<uint32_t> tof;            // ascending within a frame
  vector<float>    inten;
  vector<uint16_t> scan;           // TIMS scan index
};
```

Ascending `tof` within a frame is what makes extension a binary search over ~50k values rather than
a scan, and it comes free: the loader already sorts by m/z, which is monotone in TOF.

## 3. The algorithm, kept faithful to the current one

`MassTraceDetection` is: seed on the most intense unused peak; extend in both RT directions taking
the closest unused peak within the mass tolerance of a RUNNING centroid; stop a direction when the
hit rate over visited frames falls below `min_sample_rate`; emit if the length is in range. That is
what is reimplemented -- not a new algorithm -- so the comparison is about data structures, not
about science.

```
  order = peak indices sorted by intensity DESC          // seeding order, as today
  used  = bitset over peaks
  for seed in order:
      if used[seed] or inten[seed] < snr * noise: continue
      centroid = tof[seed]; sum = inten*tof; wsum = inten
      for dir in (+1, -1):
          misses = 0; visited = 0
          for f = frame(seed)+dir, stepping by dir:
              span = tofSpan(centroid, b[f], mass_ppm)        // integer, per frame
              k = closest unused peak in frame f with |tof-centroid| <= span
                                       and |scan - scan(seed)| <= scanTol(f)
              visited++
              if none: misses++; if hits/visited < min_sample_rate: break
              else: take it, update centroid, used[k] = true
      emit if length in [min_trace_length, max_trace_length]
```

Every inner step is: one binary search in a sorted `uint32` array, then a short linear walk over
candidates in the tolerance window. No doubles are compared, no objects are constructed, and the
peak arrays are touched at 10 B/peak instead of 20 B plus indirection.

**Valley splitting is NOT reimplemented.** `ElutionPeakDetection` runs afterwards on the traces this
produces, exactly as it does now, so that stage's behaviour is unchanged and out of scope.

## 4. What this is expected to buy, and what would falsify it

Trace detection is 3,869 s of 4,256 s of window-elapsed time on S30.

| source of gain | mechanism | estimate |
|---|---|---|
| no `PeakMap` materialisation | 20 B/peak + object overhead -> 10 B/peak, and the conversion loop disappears | memory: −1 to −2 GB per in-flight window |
| integer comparison | `uint32` difference instead of a ppm test on doubles | small; the loop is not ALU-bound |
| **cache** | a frame's peaks are three contiguous arrays instead of `Peak1D` + a parallel array behind an `MSSpectrum` | **the term that should dominate** |
| no double conversion | the store's integers are used as integers | one pass over 1.2e9 peaks removed |

**Estimate: 30-50% off trace detection, i.e. S30 from 7:04 to roughly 5:00-6:00**, with peak memory
down by the materialisation. Stated as a range because the split between bandwidth and the
detector's own arithmetic has not been isolated -- the same uncertainty that made me underestimate
the scoring gate by a factor of five, in the conservative direction.

**Falsifier:** if trace detection does not fall by at least 15%, the cost was never the data
structure and is in the extension search itself -- in which case the lever is the search (bucketing
by tof, or capping candidates per frame), not the layout, and this refactor should be reverted
rather than kept for tidiness.

**Output.** Faithful, but not bit-identical: the seeding order among equal intensities and the
closest-peak tie-breaks will differ. Judged on identified peptides with both engines.

## 5. Risks, stated before the review

1. **`min_sample_rate` semantics.** OpenMS computes the hit rate over the frames it has visited in
   that direction. Reimplementing it subtly differently changes which traces survive, and it is the
   one MS2 trace-validity lever this project has found to matter.
2. **Seeding order.** OpenMS sorts by intensity; ties are broken by whatever the sort does. Ours
   must be deterministic, or runs will not reproduce.
3. **The `used` marking is the parallelism hazard.** It is what makes tracing sequential within a
   band; bands are independent, so the parallel structure is unchanged, but a shared `used` across
   bands would be a race.
4. **The mobility rank assumes a frame's distinct 1/K0 values are its scans.** If a converter has
   already merged or re-binned mobility, the rank is not the scan. This must be checked on real data
   before it is trusted, not assumed.
