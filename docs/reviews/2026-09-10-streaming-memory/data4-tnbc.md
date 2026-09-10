# TNBC 009 re-measured with the repaired ledger (2026-09-10, chain `tnbcled`)

Binary `4258d16` (`instr_ledger2`), spock, 100 threads, load 23-34. PXD047793 run 009: a two-hour
diaPASEF acquisition, 13 cells at pitch 600. **Both arms reproduce the pin `bff54a1f`.**

| arm | wall | peak (`/usr/bin/time`) | process peak (ledger) |
|---|---:|---:|---|
| 1 tile | 10:00.62 | 109.12 GB | 106,699 MiB at 373.8 s, window loop |
| 13 tiles | 9:12.61 | **70.24 GB** | **68,666 MiB at 74.7 s, MS1 partition** |

Tiling takes 35.6% off the peak and 8.0% off the wall on this file. Walls here are faster than the
step-3b gate's (13:49 / 11:33) because that gate ran on a different node under different load; only
same-chain pairs compare.

## 1. On the long file the floor is MS1 TRACING, not the load staging

Pass 1 by sub-phase, RSS high-water in MiB (LOAD = until the load ends; PARTITION = while the MS1
band partition is live; POST = the rest of pass 1):

| arm | LOAD | PARTITION | POST |
|---|---:|---:|---:|
| 1 tile | 64,381 at 62.4 s | 66,030 at 105.5 s | 63,679 |
| 13 tiles | 64,186 at 35.1 s | **68,666 at 74.7 s** | 65,030 |

This is the **reverse of dataset D**, where the partition phase sat 8.4 GiB BELOW the load peak at
the default batch. On the two-hour file the partition phase is 2-4 GiB ABOVE it. So the two staging
levers that pay on D -- the picker flush batch (−3.0 GB) and the narrower picker scratch (R2) --
lower a peak that is not the process peak here. On TNBC at 13 tiles they are worth roughly nothing
until the partition phase comes down.

**What the partition-phase peak is made of**, at the 13-tile peak instant (t=74.7 s):

| component | MiB |
|---|---:|
| charged: the MS1 band partition (`band_arena`) | 29,451 |
| glibc free list | 28,605 |
| live but uncharged (mostly MassTraceDetection's internal copy of each band) | 10,610 |
| **RSS** | **68,666** |

**42% of the long file's tiled peak is free list.** It is the drained MS1 map, released spectrum by
spectrum during distribution and not reused by the partition or by MassTraceDetection. That makes a
trim INSIDE MS1 tracing -- after distribution, between band detections -- the lead candidate for the
two-hour file: D-class, a few lines, one arm. Its ceiling is the 28.6 GiB on the free list, less
whatever the next bands re-touch. **This is a hypothesis with a measured ceiling, not a result.**

## 2. Tiling cuts the scorer's scan by 91% on the long file

| arm | fragment visits | RT-gate survivors | visits per precursor | loop CPU | loop wall | loop parallelism |
|---|---:|---:|---:|---:|---:|---:|
| 1 tile | 12.016e12 | 13,857,222,667 | 2,856,665 | 30,663 s | 437.9 s | 70.0x |
| 13 tiles | 1.120e12 | 13,857,222,667 | 266,247 | 20,319 s | 414.6 s | 49.0x |

Visits fall 90.7% with identical survivors. This MEASURES on TNBC what the verifiers could only infer
from the step-3b gate log, which carried no score-gate line. It also explains why tiling pays more on
the long file than on D: a precursor is tested against every fragment of its window over the whole
run, so the untiled scan grows with run length squared. D at one tile scans 856,873 fragments per
precursor; TNBC scans 2,856,665. Loop CPU falls 33.7% here against 9.7% on D. The attribution caveat
from D still applies: there is no per-stage CPU counter, so the CPU fall is consistent with the scan
cut rather than proven to be caused by it.

## 3. The 13-tile window loop accumulates free list tile over tile

Window-loop RSS maximum per tile, MiB:

`15,480 · 23,878 · 30,674 · 35,250 · 39,849 · 43,549 · 45,877 · 47,601 · 49,034 · 50,640 · 51,614 · 51,738 · 50,545`

At tile 12 the ledger charges only 6,033 MiB while glibc holds 52,414 MiB free. The loop never trims
between tiles, so each tile's arenas stay resident. A per-tile trim would flatten this curve. It is
worth nothing on today's process peak, because the partition phase (68.7 GiB) is higher, and it
becomes the binding constraint as soon as pass 1 falls below ~52 GiB.

## Survivor fraction

0.115% of visits survive the RT gate at one tile (867 visits per survivor), 1.24% at 13 tiles.
