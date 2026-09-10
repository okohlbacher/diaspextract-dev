# MS1 tracing: what it holds, why it is the TNBC floor, and what lowers it (2026-09-10)

A three-stage analysis (modeller, designer, adversarial verifier) built a byte-level model of MS1
tracing from `detectTraces_` and the OpenMS `MassTraceDetection` / `ElutionPeakDetection` source actually
built, and fitted it to the repaired ledger of TNBC 009 at 13 tiles and dataset D. The full output,
including the component table with source lines, is `ms1-tracing-model-full.txt` beside this file.

## The phase, in order

On TNBC 009 at 13 tiles, times in seconds:

1. **Load end (38.5 s).** The picked MS1 map holds 45,617 MiB: 2.392e9 centroids at 20 B each. A trim
   at the load end leaves no resident free list.
2. **Band distribution (59.5-61.2 s).** The map is copied into 48 m/z bands with a 3.03% halo, 46,997 MiB
   of 260 KB pieces, releasing each source spectrum as it goes. About 13.8 GiB of the map's freed chunks
   are never re-carved, roughly 10.4 GiB of them resident. They sit in the wrong thread's arena or the
   wrong size class.
3. **Band detection (61.2-81.5 s, all 48 bands at once).** Each band's `MassTraceDetection` copies every
   peak above 100 into a private work map (about 7.7 GiB over all bands), collects apices above 300
   (about 1.8 GiB, memory-mapped outside the arena), and builds trace payloads (about 4.7 GiB). Each
   band's 979 MiB piece is freed only when that band returns, and freed pieces stay resident until a trim.
4. **The peak (74.7 s), closed to 0.3 GiB.** 68,666 MiB = 0.4 base + 29,451 charged partition (30 bands
   still running) + 10,548 uncharged in-use + ~25.2 GiB resident free list + ~3.1 GiB memory-mapped.
5. **After detection (84.4 s).** 54.4 GiB of free list, about 51 GiB of it resident, held until the
   phase-end trim returns 95% of it in 4.9 s.

**Why TNBC's floor is MS1 tracing and D's is the load.** The partition-phase peak is about 1.5 times the
MS1 map. The load peak is about 0.8 times the map plus a run-length-independent 20-24 GiB of staging.
The two curves cross at a map of about 31 GiB, roughly an 80-minute gradient at TNBC's density
(estimate). D (13.8 GiB map) sits below the crossing and TNBC (44.5 GiB) above it.

**The model's two unknowns are now measured, and it passes.** `SPEXTRACTOR_MS1_HIST` on TNBC counts
358,460,745 picked MS1 peaks at or above 100 (15.0%; model estimate 17%) and 59,908,030 at or above 300
(2.5%; model 50-80 M). `SPEXTRACTOR_MS1_TRIM` returned 11.9-12.8 GB right after distribution
(model: about 10.4 GiB resident, less re-touch), and the process peak moved to the load, as predicted.

## What lowers it, ranked, with the verifier's verdict on each

| rank | option | class | verdict | predicted effect on TNBC 009 (13 tiles) |
|---:|---|---|---|---|
| 1 | **Prune MS1 centroids at or below `trace:noise_threshold_int` (100) at the picker flush** | D, with conditions | partly | map 45,617 → ~6,840 MiB (measured N100); pass 1 ~28-38 GiB; the window loop (51.7 GiB) binds, run peak ~52 GB |
| 2 | One trim per tile in the window loop | D | holds | loop 51.7 → ~20-25 GiB; only useful after rank 1 |
| 3 | Trim after band distribution (`SPEXTRACTOR_MS1_TRIM`), plus one after the last band | D | holds / partly | **measured: 68.94 → 65.94 GB**, load binds; after-last-band trim takes POST from 65.0 to ~16 GiB |
| 4 | Load knobs: MS1-only picker batch + in-flush trim | D | partly | **measured on D (−5.1 GB); with rank 3 on TNBC 62.22 GB** |
| 5 | `MassTraceDetection` reading band ranges from the kept map, no partition copy (OpenMS patch) | D | holds | partition phase ~50-55 GiB; only with an OpenMS rebuild |
| 6 | MS1 peaks at 16 B (IM float into `Peak1D` padding, OpenMS kernel patch) | D | partly | −20% of every map-proportional row; larger code surface than first listed |
| 7 | MS1 tracing per RT cell during the load | S | class only | pass 1 ~25-35 GiB; ~3% of MS1 traces cut at 12 edges |
| 8 | MS1 through the integer detector | S | class only | memory parity with 7; highest science risk |
| — | Bounded band concurrency; streaming the partition from a kept map; releasing tracer intermediates early | D | hold | dominated: ≤ 3 GiB, or +20-130 s of wall |
| — | dnoise stage 1 on raw points | S | class only | memory value beyond rank 1 is only the raw staging (≤ 3.5 GiB); judge on science |

**Rank 1 is output-identical only if both conditions are coded, not left to the digest:**

- **Band edges from the unpruned spectra.** The edges are quantiles of a stride-97 m/z sample of the
  whole map, and edge changes are visible at the 1e-4 level.
- **Every band spectrum that exists today must still exist.** A band spectrum is inserted when any peak,
  sub-threshold included, falls in its range, and the tracer counts it as a scan. *(Corrected the same day:
  this condition was first written as a per-frame 48-bit band mask built at flush. That mask cannot be
  built there: the edges are quantiles of the whole run's sample, known only after the last flush. The
  buildable form is a witness chain: keep, besides every survivor, each frame's first and last peak and the
  fewest sub-threshold peaks that leave no relative m/z gap wider than the band halo h = 20 x ppm x 1e-6.
  Every band range is at least 2h/(1-h) wide, so a range that held any peak still holds one, whatever the
  edges. Brute force: 0 mismatches in 360,968 band checks, 37,119 without the witnesses.)*

The prune predicate must be intensity ≤ threshold as a double, the exact complement of the tracer's
`> noise_threshold_int_`. Nothing else reads the map's peaks: every other reader takes retention times
only, and no MS1 spectrum reaches any output. So rank 1 removes nothing the tracer can see, and it is not
a faint-signal change. It also makes the 16 s serial pass at `ms1_map.sortSpectra()` removable: that call
is an `isSorted()` scan of 2.39e9 peaks, not a re-sort, because the picker already sorts each spectrum.

**Corrections the verifier made:**

- The first band returns at 62.08 s, not 65.4 s.
- The load knobs' effect on TNBC is an extrapolation until measured there; the all-levers arm now
  measures it at 62.22 GB.
- At least 5.4 GiB of the TNBC load row lies outside the glibc arena and is unexplained. glibc's
  memory-mapped total reads 0 at 37 s, so it is not glibc mappings. Only an hblkhd + smaps_rollup
  sampler column would settle it.
