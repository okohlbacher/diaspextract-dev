# The sub-threshold MS1 prune, and how it interacts with dnoise (2026-09-10)

The MS1 tracer (OpenMS `MassTraceDetection`) only uses peaks with intensity above `trace:noise_threshold_int`
(100). On unfiltered data, 81% of dataset D's picked MS1 centroids and 85% of TNBC 009's are at or below it, and the
tool holds all of them through pass 1: in the picked map, then again in the 48-band copy. This change drops them at
load without changing a byte of output (`perf:ms1_prune`, default true), and measures what that buys with and
without dnoise.

## Why a plain filter would change the output, and what the prune keeps instead

Two things downstream of the map read peaks the tracer never uses.
- **Band edges.** They are quantiles of a stride-97 m/z sample over every spectrum. Sampling a pruned map moves
  them.
- **Band spectra.** A band spectrum exists whenever any peak, of any intensity, falls in the band's range. The
  tracer counts every spectrum it receives as a scan, so a band spectrum that disappears changes trace validity
  and termination.

The earlier plan asked for a per-frame band mask built at flush time. That cannot be built: the edges come from
the whole run's sample, known only after the last flush. The prune instead:
1. takes the stride-97 m/z sample from the sorted, unpruned spectrum at flush and hands it to the tracer's band
   builder;
2. keeps every peak the tracer would use (`(double)intensity > noise`, the tracer's own test), each spectrum's
   first and last peak, and the fewest sub-threshold "witnesses" that leave no relative m/z gap wider than the band
   halo h = 20 x ppm x 1e-6.

Every band range is at least 2h/(1-h) of its lower edge wide, so a range that held any peak still holds a kept
one, whatever the edges turn out to be. Band membership, spectrum counts and the tracer's input are unchanged.
The argument never refers to the input, so it holds after dnoise too.

Evidence:
- A brute force over 360,968 band checks gave 0 mismatches with witnesses and 37,119 without.
- e2e check 19 uses a synthetic MS1 trace whose validity depends on frames holding only sub-threshold peaks. Prune
  on and off give the same output at 1, 2 and 48 bands. The no-witness negative control changes the MS1 traces
  (6 → 7) and precursors (2 → 3), so the fixture is sensitive.

## Identity gates on real data

Same build (stage 1, `cc39a66+dirty`), ibminode05, 100 threads, 3 tiles at pitch 600, `SPEXTRACTOR_DET` on.

| input | prune off | prune on | [det] and [ms1-edges] lines |
|---|---|---|---|
| dataset D, original | `8c1b047f` (the pin) | `8c1b047f` | 245 vs 245, identical multiset |
| dataset D, dnoise MS1-only input | `e43672a0` | `e43672a0` | edges hash equal |

| TNBC 009, original (stage-2 build `dnoise_s2a`, dnoise off, on `data`) | `bff54a1f` (the pin) | `bff54a1f` | 1,125 vs 1,125, identical multiset; edges hash equal |

On TNBC 009 the prune keeps 352,251,824 survivors plus 18,885,330 witnesses (5.4% of the survivors) of 2,391,660,683
picked centroids, and drops 6,208,921 at exactly 100.0.
- **Map:** 45,617 → 7,078 MiB.
- **Band copy:** 46,997 → 7,422 MiB.
- **Peak:** 69.33 → **34.46 GB (−50%)**. By ledger that is 67,812 MiB during MS1 tracing against 33,946 MiB during
  the load.

The peak stays in pass 1, now at the load: the raw MS1 staging (3.9 GiB) and the picker's temporaries on the
unpruned points remain.

## What it keeps, and what that buys on D

| D, 3 tiles | prune off | prune on | dnoise input, prune off | dnoise input, prune on |
|---|---:|---:|---:|---:|
| picked MS1 centroids | 725,116,915 | 725,116,915 | 43,546,607 | 43,546,607 |
| kept (survivors + witnesses) | all | 136,680,735 + 3,400,432 | all | 33,697,680 + 432,786 |
| centroids at exactly 100.0 (pruned) | | 3,540,330 | | 175,214 |
| MS1 map (ledger peak) | 13,830 MiB | 2,671 MiB | 830 MiB | 650 MiB |
| band copy (ledger peak) | 14,161 MiB | 2,720 MiB | 895 MiB | 708 MiB |
| raw MS1 staging (ledger `scratch`) | 4,802 MiB | 4,802 MiB | 1,381 MiB | 1,381 MiB |
| pass-1 peak (ledger) | 31,171 MiB | 22,994 MiB | 4,077 MiB | 3,932 MiB |
| run peak (ledger), phase | 31,171 MiB, pass 1 | 25,951 MiB, tile loop | 21,175 MiB, tile loop | 21,143 MiB, tile loop |
| peak (`time -v`) | 31.82 GB | **26.49 GB** | 21.60 GB | 21.64 GB |
| wall (node at load 60-100) | 5:12 | 5:02 | 4:12 | 4:24 |

Witnesses are 2.5% of the survivors on the original file and 1.3% on the filtered one. The map and band copy shrink
5.2x.

- **Prune alone takes 5.3 GB (−17%) off D's peak with identical output.** Pass 1 falls from 31.2 to 23.0 GiB. What
  remains of it is the raw MS1 staging (4.8 GiB, the picker's input before the prune can act) and the picker's
  temporaries. The run peak moves into the tile loop, whose retention is analysed in data6-tile-count.md.
- **After dnoise the prune buys almost nothing on D:** 180 MiB of map and 190 MiB of band copy, and no change to
  the peak. The tile loop sets that peak.

## The interaction, stated plainly

The two act at different points and remove different things.
- **dnoise** removes raw points before picking. Everything downstream shrinks: the picker's input and
  temporaries, the map, the band copy, and the tracer's own work maps above the threshold. It also changes what is
  traced, so it changes output. After dnoise, only 22% of D's picked centroids are at or below 100 (43% on TNBC),
  against 81% (85%) before.
- **The prune** removes picked centroids the tracer cannot see. Only the map and the band copy shrink; the tracer's
  work, the raw staging and the output are unchanged.

So the prune is the output-preserving way to take most of the MS1 map, and dnoise takes more but changes the
science. Together, the prune adds little on D and more on TNBC, where more sub-threshold centroids survive dnoise.
Once either has shrunk pass 1, the tile loop and its allocator retention set the peak.

## On the final build, with dnoise inside the tool (arm `dnoise_s2b`)

The same four combinations, now with dnoise in the tool instead of a filtered input file. One cell per tile (D 3
tiles on ibminode05, TNBC 009 13 tiles on `spock`), each set back to back. Every arm writes its pin
(docs/reviews/2026-09-10-dnoise-port/final-matrix.md).

| | D, prune off | D, prune on | TNBC 009, prune off | TNBC 009, prune on |
|---|---:|---:|---:|---:|
| dnoise off: MS1 map | 13,830 MiB | 2,671 MiB | 45,617 MiB | 7,078 MiB |
| dnoise off: peak | 31.99 GB | **25.90 GB** | 69.11 GB | **31.97 GB** |
| dnoise on: MS1 map | 830 MiB | 650 MiB | 5,901 MiB | 3,430 MiB |
| dnoise on: peak | 22.62 GB | **22.48 GB** | 26.20 GB | **25.17 GB** |

- **With dnoise off, the prune takes 6.1 GB off D (−19%) and 37.1 GB off TNBC 009 (−54%)** at identical output.
- **After dnoise it takes 0.14 GB off D and 1.0 GB off TNBC 009.** TNBC keeps more sub-threshold centroids through
  dnoise (43% of 309 M picked, against 22% on D), so its map still shrinks by 42%.
- **In-tool dnoise peaks about 0.9 GB above the filtered-input rows** of the table above (22.48 against 21.64 GB on
  D). Those rows came from an earlier build on a different day, and the difference is not attributed.
