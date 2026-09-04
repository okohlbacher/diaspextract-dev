# The trace struct has one degree of freedom per point, and stores three

**Origin.** User, 2026-09-04: a trace is contiguous by definition, so it needs only its entry point
on the RT axis and its intensities -- not a coordinate per point. Same for the flight-time bin.

## 1. What is stored today, and why it is wrong

```cpp
struct Trace {                       // src/DIAPseudoSpectra.cpp:243
  double mz, rt, im, intensity;      //  32 B  per trace, all DERIVABLE from what follows
  uint32_t tof; double b;            //  16 B  per trace (b is the apex FRAME's factor: derivable)
  vector<uint32_t> xi;               //   4 B  per point: frame index      <- redundant
  vector<float>    xv;               //   4 B  per point: intensity        <- the only payload
  vector<uint32_t> xt;               //   4 B  per point: flight-time bin  <- redundant
};                                   // 120 B struct + 3 malloc headers + 12 B/point
```

Measured: 35.6 GB peak, the largest structure in the integer path. A trace point has ONE degree of
freedom -- its intensity -- because the frame is implied by position and the bin is the trace's.
`xi` and `xt` encode information that is either constant along the trace (the bin, within
tolerance) or arithmetic on the position (the frame). The doubles are caches of things a few
instructions recompute.

## 2. "Contiguous" needs one refinement, and it decides the design

Two facts from the data (S30):

* **33,553 frames, 17,343 distinct RTs, 1,343 MS1 frames, 24 windows.** A window's CONSECUTIVE
  frames are ~13 apart on the GLOBAL RT axis, because the MS1 frame and the other windows' frames
  interleave in every cycle. So a trace is NOT contiguous on the global axis. It IS contiguous in
  its own window's frame sequence (`PeakSlab::rt_index`, window-local index 0..F-1), and for MS1
  traces in the MS1 map's sequence. **The entry point must be window-local**, and `rt_index[]`
  maps it to the global axis when a global RT is needed.
* **Traces have gaps.** The detector, following OpenMS, tolerates up to 5 consecutive missing
  frames and accepts a trace if points/frames >= 0.5 over its span. So "contiguous" means "a span
  with holes", and the holes must be representable. **Dense over the span, zero = missing.** By
  the sample-rate rule at most half the entries are padding, so the worst case is 8 B per real
  point of intensity storage against 12 B per point today, and the typical case (few gaps) is ~4.
  Every consumer already skips zero intensities (the scorer's `overlap` counts only non-zero
  precursor slots; `mean`/`invnorm` sums are unaffected by zeros), so the semantics are unchanged.

## 3. The redesigned trace

```cpp
struct Trace
{
  uint32_t frame0;     // first frame, WINDOW-LOCAL (MS1: index in the MS1 map)
  uint32_t off;        // offset of this trace's intensities in the window's arena
  uint32_t tof;        // the trace's flight-time bin (apex peak's, or centroid, per estimator)
  uint16_t len;        // frames spanned (traces are < 65k frames; the gradient is 1,400)
  uint16_t apex;       // offset of the apex within the span
  uint16_t imq;        // quantised mobility centroid
};                     // 18 B per trace, no allocation per trace
// per window:  vector<float> arena;   // all traces' intensities, 4 B per spanned frame
```

Everything the old struct cached is an accessor over the slab and the arena:

| old field | now | cost |
|---|---|---|
| `rt` | `rtAxis()[sl.rt_index[frame0 + apex]]` | two loads |
| `mz` | `tofAxis().mzOf(tof, sl.b[frame0 + apex])` | one calibration call, only at gate/export time |
| `im` | `IM_LO + imq / IM_Q` | one multiply |
| `intensity` | `arena[off + apex]` | one load |
| `b` | `sl.b[frame0 + apex]` | one load |
| `xi[i]` | `frame0 + i` | arithmetic |
| `xt[i]` | not needed: the bin is per trace; the apex's measured bin IS `tof` | -- |
| `xv[i]` | `arena[off + i]` | one load |

**Bytes.** ~7.5e6 traces per window, ~10.7 points per trace measured, call it 14 spanned frames
with gaps: today 120 + 48 + 12x10.7 = ~296 B/trace; redesigned 18 + 4x14 = 74 B/trace. **4x
smaller, and 3 mallocs per trace become 0** (the arena grows by append inside one band task, then
is concatenated per window). The measured 35.6 GB becomes ~9 GB.

## 4. What it does to the consumers -- the part that makes this more than a compaction

* **`FragGrid` disappears.** Its job was to resample every fragment onto a common per-window RT
  grid as CSR `(slot, intensity)` pairs. With dense window-local traces the grid IS the window's
  frame sequence and the CSR IS the arena: `flat[k]` = `arena[off + k]`, slot = `frame0 + k`.
  No union, no `slot_of_frame`, no copy: 1.7 GB and one pass over every point gone. `mean` and
  `invnorm` stay as two per-trace doubles computed once. The precursor-to-fragment nearest-frame
  table (`nearest_slot`) stays, now indexed by window-local frame -- ~1,400 entries.
* **The scorer's inner loop becomes a contiguous walk** `for k in [0,len)` reading
  `pdense[frame0 + k]` and `arena[off + k]`: two sequential streams, no gather through a slot
  index. Skipping `arena == 0` preserves `overlap` exactly.
* **`xicCorr` (isotope partners)** is an overlap of two `[frame0, frame0+len)` intervals and an
  aligned dot product -- no merge of index lists.
* **`atrousLevels` / FWHM** read `rtAxis()[rt_index[frame0 + i]]` where they read `rtAt(i)`.
* **Valley splitting** (`splitIntegerTraces`) builds its `MassTrace` from `(rt_index, arena)` and
  the split traces come back as spans of the parent: a child is `(frame0 + a, len b-a, same tof)`
  -- it can be represented WITHOUT copying intensities, as a sub-span of the parent's arena range.
  This removes the post-split re-conversion copy.
* **The OpenMS detector path** produces `MassTrace` objects whose peaks are the map's spectra;
  `toTrace()` finds `frame0` as the index of the first peak's RT in the map's spectrum sequence
  (the map is RT-sorted, so a binary search over ~1,400 RTs) and writes intensities into the
  arena with zeros for gaps. Both detectors then produce the SAME structure.
* **Precursor inference and assembly** read `mz`/`rt`/`im`/`intensity` through accessors that take
  the slab; the hot fragment gate already uses SoA arrays (`frag_rt`, `frag_im`), which become
  per-window arrays filled once from the accessors.

## 5. What could go wrong, and how to know

| risk | symptom | check |
|---|---|---|
| `len` overflows uint16 | a trace spanning > 65,535 frames: impossible on a 1,400-frame gradient, but assert it | `assert(len < 65536)` at construction, abort not truncate |
| a consumer relied on per-point bins (`xt`) | export m/z of split traces reverts to a centroid | the apex bin is `tof`; the ONLY consumer of per-point bins was `splitIntegerTraces` giving EPD per-peak m/z, and EPD ignores per-peak m/z (it splits on RT/intensity; SNR filter off) -- so `toTrace()` after a split must take the apex bin from the PARENT's slab lookup, not from the MassTrace |
| zero-padding changes a statistic | `mean`/`invnorm`/`overlap`/sample-rate differ | zeros contribute nothing to sums; `overlap` tests non-zero; the sample-rate test is done in the detector before the span is built -- verify by digest against the current integer output on S30 (the integer path is not gated on bit-identity, but THIS change should be, because it is meant to be pure representation) |
| MS1 traces need the MS1 map's frame sequence, not a window's | wrong `rt` for precursors | one `PeakSlab`-like frame table for the MS1 map (`rt_index` only) |
| arena growth reallocates while tasks hold offsets | offsets stay valid (they are indices, not pointers) but concurrent appends race | each BAND task appends to its OWN arena; the window concatenates them after the band tasks join, rebasing `off` -- one add per trace |

**Falsifier for the whole redesign:** the spectrum digest of the integer path on S30 must be
IDENTICAL before and after (this is pure representation; any difference is a bug), AND the
`traces` ledger line must fall from 35.6 GB to under 12 GB. A digest match with no memory drop
means the arithmetic in section 3 is wrong; a memory drop with a digest change means a consumer
was not as zero-tolerant as section 4 claims.
