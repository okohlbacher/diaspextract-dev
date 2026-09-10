# Why more tiles still leave a large footprint (2026-09-10)

The question: splitting the run into more RT tiles shrinks each tile's work, so why does peak memory barely
move? Measured with the same binary (`instr_tnbc2`, d7cc14d), 100 threads, `SPEXTRACTOR_LEDGER` on. At a
fixed pitch the output does not depend on the tile count, and every arm below reproduced its pitch's digest.
Memory is therefore compared at identical output.

## The answer

Three things stack, and only the smallest of them shrinks with the tile width.

1. **Pass 1 is the whole run's MS1, and tiling never touches it.** It loads, picks, band-copies and traces
   every MS1 frame before the first tile exists. On unfiltered TNBC 009 it peaks at about 68 GB, 84 s into
   the run. From 4 tiles up, the process peak is pass 1 or level with it.
2. **The tile loop's RSS follows the allocator, not the tile.** At every tile boundary the tool's counted
   live data is 1-4 GiB, yet RSS climbs tile after tile toward the size of the glibc arena pass 1 left
   behind. glibc keeps memory it has freed. Each tile's allocations land in those free chunks and
   re-dirty their pages, and nothing trims between tiles (the only in-loop trim runs when there is one
   tile). On unfiltered TNBC at 13 tiles the loop climbs to 51 GiB with 3-8 GiB live.
3. **A base that no tile count removes:** thread stacks, libraries, per-thread encoders and uncounted
   transients. It is about 3 GiB at the end of a run.

**Once MS1 is small, tile count becomes a strong lever.** On dnoise-filtered input, pass 1 is a few GB, the
arena it leaves is small, and TNBC 009 falls from 97.8 GB at one tile to 24.9 GB at 13, with identical output.

## Tile count at identical output

Peak is `/usr/bin/time -v` (GB). "Ledger peak" is the sampled maximum (MiB), with the counted live bytes and
glibc's free list at that instant.

**TNBC 009, original file (spock; digest `bff54a1f` in every arm)**

| tiles | peak | wall | ledger peak | phase | counted live | glibc free |
|---:|---:|---:|---:|---|---:|---:|
| 1 | 107.21 GB | 9:41 | 104,657 at 360 s | tile loop | 82,035 | 34,359 |
| 2 | 78.10 GB | 9:46 | 76,438 at 444 s | tile loop, tile 2 | 38,175 | 40,456 |
| 4 | 69.12 GB | 9:52 | 67,551 at 487 s | tile loop, tile 3 | 25,496 | 43,338 |
| 7 | 68.79 GB | 9:55 | 67,271 at 98 s | pass 1 | 28,472 | 27,588 |
| 13 | 69.52 GB | 9:26 | 67,950 at 84 s | pass 1 | 32,394 | 24,388 |
| 13, repeat | 69.22 GB | 10:20 | 67,630 at 90 s | pass 1 | 30,457 | 25,855 |

**TNBC 009, dnoise MS1-only input (data; digest `3aafd0b5` at pitch 600)**

| tiles | peak | wall | ledger peak | phase | counted live | glibc free |
|---:|---:|---:|---:|---|---:|---:|
| 1 | 97.84 GB | 8:51 | 95,320 at 256 s | tile loop | 79,616 | 14,389 |
| 4 | 48.72 GB | 11:03 | 47,747 at 305 s | tile loop | 30,349 | 11,255 |
| 13 | 24.94 GB | 8:14 | 24,396 at 308 s | tile loop | 6,845 | 12,277 |
| 13, repeat | 25.40 GB | 11:48 | 25,007 at 418 s | tile loop | 7,246 | 12,601 |
| 25 (pitch 300, `d9668c1c`) | 20.40 GB | 11:07 | 20,027 at 504 s | tile loop | 4,154 | 12,483 |

**Dataset D, dnoise MS1-only input (ibminode05; digest `e43672a0` at pitch 600)**

| tiles | peak | wall | ledger peak | phase | counted live | glibc free |
|---:|---:|---:|---:|---|---:|---:|
| 1 | 36.91 GB | 3:06 | 36,110 at 85 s | tile loop | 21,988 | 5,006 |
| 2 | 29.32 GB | 3:33 | 28,601 at 59 s | tile loop | 12,185 | 4,513 |
| 3 | 21.41 GB | 3:32 | 20,918 at 74 s | tile loop | 9,540 | 6,000 |
| 3, repeat | 21.54 GB | 3:31 | | | | |
| 6 (pitch 300, `81a762ee`) | 14.55 GB | 3:27 | 14,205 at 165 s | tile loop | 4,215 | 6,260 |

Wall on `data` ran at load 120-270 from other users and is not comparable between arms.

Read together, the three tables give the answer. On the original TNBC file, counted live data at the loop's
peak halves with each doubling of tiles (82 → 38 → 25 GiB), but from 4 tiles on the peak is fixed at the
pass-1 floor of about 68 GB. On the filtered inputs the peak keeps falling, but more slowly than the live
data: from 13 to 25 tiles on TNBC, live data drops 40% while the peak drops 18%, because about 12.5 GiB of
free list sits under every peak.

## The ratchet at tile boundaries

RSS at the end of each tile's write (GB), next to glibc's arena size. Counted live data at these instants is
1-4 GiB.

| tile | TNBC original, 13 tiles: RSS / arena | TNBC filtered, 13 tiles: RSS / arena | D filtered, 6 tiles: RSS / arena |
|---:|---|---|---|
| 1 | 15.6 / 59.5 | 11.7 / 16.4 | 3.0 / 4.1 |
| 2 | 24.2 / 58.3 | 15.8 / 17.0 | 5.8 / 5.7 |
| 3 | 31.5 / 57.8 | 17.1 / 17.3 | 7.9 / 7.7 |
| 4 | 36.2 / 57.6 | 17.9 / 17.3 | 9.2 / 9.0 |
| 5 | 39.9 / 57.6 | 18.1 / 17.1 | 9.5 / 9.2 |
| 6 | 42.2 / 57.6 | 18.6 / 17.5 | 8.8 / 8.6 |
| 7-13 | 44.1 → 48.6 / 57.2 → 56.9 | 18.5 → 19.2 / 17.2 → 17.8 | |

On the original file the arena stays at the size pass 1 grew it to, and RSS approaches it: 48.6 GB of a
56.9 GB arena after 12 tiles. On the filtered file pass 1 leaves a 16 GB arena, and the loop's RSS settles
just above it. On D the arena is small after pass 1 and grows inside the loop, with RSS tracking it.

## The allocator arms

Dataset D, dnoise MS1-only input, pitch 300, 6 tiles; digest `81a762ee` in every arm. Ledger columns are MiB
at the peak.

| glibc setting | peak | wall | counted live | untracked | of which free list | boundary RSS, tiles 1-6 (GB) |
|---|---:|---:|---:|---:|---:|---|
| none (control) | 14.48 GB | 3:35 | 5,904 | 8,302 | 3,953 | 3.0 5.8 7.9 9.2 9.5 8.8 |
| none (control, repeat) | 14.73 GB | 3:27 | 5,830 | 8,602 | 4,936 | 2.9 5.9 8.2 9.2 9.5 8.4 |
| `MALLOC_ARENA_MAX=8` | 15.29 GB | 4:12 | 5,917 | 8,984 | 4,284 | 2.3 5.1 9.1 11.5 11.8 11.2 |
| `MALLOC_ARENA_MAX=2` | 14.82 GB | 6:45 | 5,720 | 8,832 | 2,636 | 2.4 4.8 8.4 10.5 11.6 11.3 |
| `MALLOC_TRIM_THRESHOLD_=64 MiB`, `MALLOC_TOP_PAD_=0` | **11.28 GB** | 3:48 | 5,925 | **5,148** | 1,694 | **1.7 2.7 3.0 3.1 3.2 2.9** |

At 3 tiles, `MALLOC_ARENA_MAX=8` gave 20.75 GB against 21.41 and 21.54 GB, 17% slower.

- **Fewer arenas do not help.** Memory one thread frees is not the problem; with 2 arenas the free list
  shrinks but the untracked total does not, and the run takes 88% longer.
- **Returning free heap tops does help.** An eager trim threshold keeps every arena at about 2.3 GB instead
  of letting it grow to 9 GB. Boundary RSS stays at 1.7-3.2 GB, and the peak falls 22% for 6% wall. What
  is left at the peak is the tile's own work.

## Established and inferred

Established, by the tables above:
- Output does not depend on the tile count at a fixed pitch; every arm reproduced its digest.
- The tool's counted live data at the loop's peak scales with tile width on all three inputs.
- On unfiltered TNBC, pass 1 sets or matches the peak from 4 tiles up.
- The loop's RSS at tile boundaries climbs toward the arena size while live data stays at 1-4 GiB.
- No trim runs between tiles when there is more than one tile (`spextractor.cpp`, the single in-loop trim is
  guarded by `tiles.size() == 1`).
- Eager return of heap tops removes most of the boundary RSS and 22% of the peak on filtered D.

Inferred: that the retained memory is mostly free chunks re-dirtied by later tiles, rather than live memory
the ledger does not count. The trim-threshold arm makes this likely; a per-tile `malloc_trim` is the direct
test.

## The loop re-uses pass 1's pages: trimming off

TNBC 009, original file, 13 tiles, on `data` back to back (digest `bff54a1f` in both). `perf:malloc_trim
false` switches off the phase-boundary trims, so pass 1's free list stays resident into the loop.

| tile | trims on (default): boundary RSS (GB) | trims off: boundary RSS (GB) | arena (GB) |
|---:|---:|---:|---:|
| 1 | 15.3 | 63.6 | 59.9 / 61.0 |
| 4 | 35.6 | 60.9 | 57.6 / 58.4 |
| 7 | 44.4 | 60.0 | 57.1 / 57.5 |
| 10 | 47.9 | 60.0 | 56.8 / 57.4 |
| 13 | 48.6 | 58.6 | 56.5 / 57.3 |

| | peak | ledger peak | loop maximum |
|---|---:|---:|---:|
| trims on | 68.98 GB | 67,448 MiB at 126 s, pass 1 | 51,405 MiB |
| trims off | 72.78 GB | 71,178 MiB at 90 s, pass 1 | 64,158 MiB |

**With trims off, the loop's RSS never climbs.** It holds at 60-64 GB from the first tile to the last, inside
memory pass 1 already dirtied, while the counted live data per tile is the same 3-8 GiB as with trims on. The
loop needs no new pages. With trims on, the phase trim returns those pages (RSS 4.0 GB entering tile 1),
and each tile's allocations fault them back in, one tile's worth at a time, until RSS is back at 49 GB.
So the retained memory is re-dirtied free chunks of the pass-1 arena, not live data the ledger misses: the
loop's ceiling is set by pass 1, not by the tile width. Trimming only at the phase boundaries costs 3.7 GiB
of pass-1 peak when switched off, and buys a loop that starts low and ends almost where it would have been.

A second control closed the pair at 67.24 GB (ledger 65,784 MiB, pass 1), with the same climb to 49.4 GB.
The same chain also ran `SPEXTRACTOR_LOAD_ONLY=1`, which stops after the MS1 load, before MS1 tracing. It peaked
at 65.71 GB (ledger 64,469 MiB at 53 s: 44,168 counted, 8,923 free). The load alone is 95-97% of the tiled
pass-1 peak; tracing adds the last 1-3 GiB.

## A trim between tiles

`SPEXTRACTOR_TILE_TRIM=1` (a probe added with this work) calls `malloc_trim(0)` after each tile's spectra are
written. Dataset D, dnoise MS1-only input, pitch 300, 6 tiles, on the build that also carries the MS1 prune; digest
`81a762ee` both ways.

| | peak | wall | ledger peak | counted live | glibc free |
|---|---:|---:|---:|---:|---:|
| no trim between tiles | 14.80 GB | 3:36 | 14,529 MiB, tile 5 | 4,999 | 5,166 |
| trim between tiles | 13.97 GB | 3:39 | 13,695 MiB, tile 4 | 5,668 | 4,399 |

Each trim takes 0.4-0.8 s and drops RSS to about 3 GB (tile 4: 8,861 → 3,304 MB). The next tile then grows RSS
back to 10-14 GB, with only 5-6 GiB of it counted. So the between-tile trim takes 0.8 GB (−5.6%) off this peak;
the eager `MALLOC_TRIM_THRESHOLD_` arm took 3.2 GB, because it acts inside the tile as well. On this input the
growth that sets the peak happens *within* a tile.

The two inputs fail differently:
- **Unfiltered TNBC:** retention accumulates *across* tiles. Boundary RSS climbs 15.5 → 49.4 GB with 2-4 GiB
  live, so a trim between tiles is the matching fix. It stays hidden while pass 1 sets the peak.
- **Filtered D:** the tile's own churn inside one tile sets the peak. There, only an allocator that returns memory
  continuously (the trim threshold) or less churn in the window loop helps.

The per-tile trim on TNBC, unfiltered and with dnoise, is measured on the final build below ("The trims on TNBC").

## Returning memory continuously: an eager trim threshold

`MALLOC_TRIM_THRESHOLD_=67108864 MALLOC_TOP_PAD_=0` makes glibc return a heap's free top as soon as it exceeds
64 MiB, on every free, instead of keeping it for reuse. Zero code, identical output in every arm. TNBC 009 at 13
tiles on `data`, each pair back to back (load 100-160 from other users, so wall differences of a few percent are
indicative only).

| input | setting | peak | wall | ledger peak | glibc free at the peak | arena after pass 1 | boundary RSS, tiles 1 → 12 (GB) |
|---|---|---:|---:|---|---:|---:|---|
| original | default | 68.74 GB | 11:14 | 67,231 MiB, pass 1 | 25,238 MiB | 59.7 GB | 15.5 → 50.0 |
| original | eager trim | **58.95 GB** | 11:48 | 57,681 MiB, pass 1 | 2,899 MiB | 33.3 GB | 13.7 → 33.5 |
| dnoise input | default | 25.22 GB | 8:59 | 24,737 MiB, tile 7 | 12,637 MiB | 16.1 GB | 11.5 → 19.7 |
| dnoise input | eager trim | **21.45 GB** | 9:19 | 21,038 MiB, tile 7 | 8,861 MiB | 12.7 GB | 9.2 → 14.4 |

Dataset D, dnoise input, 6 tiles (earlier section): 14.48-14.73 GB → 11.28 GB.

This arm tests the mechanism from the other side.
- **The ceiling follows the pass-1 arena.** Returning heap tops continuously keeps pass 1 from growing the arena
  to 60 GB; it stops at 33 GB. The loop's boundary RSS then climbs to that lower ceiling, 33.5 GB instead of
  50.0 GB, with the same live data per tile.
- **Pass 1's free list mostly goes.** On the original file it falls from 25.2 GiB to 2.9 GiB at the pass-1 peak.
  What remains is live MS1 data: 43.1 GiB of map and band copy, which is what the prune removes.
- **The price is small:** 3-6% wall across the three inputs, measured on loaded nodes.

It is the most effective output-identical memory lever measured in this analysis: 14-22% of the peak at every
tile count and input tried. Unlike the prune, it needs no code, and it helps whatever sets the peak. It needs a
wall measurement on a quiet node before it could become a default (for instance `mallopt` at startup).

## The trims on TNBC, on the final build (arm `dnoise_s2b`)

TNBC 009 at 13 tiles, prune on (the default). `SPEXTRACTOR_TILE_TRIM=1` runs `malloc_trim(0)` after each tile. Every
arm writes its pin. The trimmed arms ran back to back on `data`; the untrimmed references are the same build on
`spock`, so compare across the two only roughly (docs/reviews/2026-09-10-dnoise-port/final-matrix.md).

| dnoise | setting | node | peak | wall | ledger peak, phase | glibc free at the peak | MS1 load |
|---|---|---|---:|---:|---|---:|---:|
| off | no trim | spock | 31.97 GB | 10:25 | 31,332 MiB, tile 9 | 18,174 MiB | 58.5 s |
| off | trim between tiles | data | 29.08 GB | 10:19 | 28,558 MiB, pass 1 | 18,262 MiB | 56.5 s |
| on | no trim | spock | 25.17 GB | 10:46 | 24,734 MiB, tile 7 | 11,353 MiB | 68.4 s |
| on | trim between tiles | data | 21.07 GB | 9:57 | 20,718 MiB, tile 7 | 11,363 MiB | 34.3 s |
| on | eager trim threshold | data | 20.73 GB | 10:17 | 20,413 MiB, tile 7 | 7,528 MiB | 96.3 s |

- **Unfiltered, prune on: the trim between tiles removes the ratchet.** Without it, tile 9 set the peak at 31.3 GiB.
  With it, the loop stays below pass 1, which now sets the peak at 28.6 GiB, so pass 1 is the remaining lever.
- **Filtered: the two trims end within 0.35 GB of each other,** about 4 GB under the untrimmed run, and both leave
  tile 7 as the peak. On TNBC, unlike D, most of the retention builds up across tiles, so the cheap trim gets most of
  the gain.
- **The eager threshold nearly triples the MS1 load here** (34.3 → 96.3 s back to back, wall +3%). Returning heap
  tops on every free makes the loader fault its staging back in, as plan step 0a measured.

## What this means

- A per-tile `malloc_trim` should come with any tiled default. It cannot change output. On the final build it takes
  about 4 GB off TNBC 009, with or without dnoise, and 0.5 GB off D.
- With MS1 reduced, whether by dnoise, now the default, or by the exact prune, the tile count is the largest memory
  lever at identical output. The shipped default is still one tile (`tile:cells_per_tile 0`). On the final build:
  - TNBC 009 (`data`, back to back): 99.70 GB and 9:42 at one tile, against 21.07 GB and 9:57 at 13 tiles with a
    trim between tiles;
  - D (ibminode05): 37.44 GB and 3:15 at one tile, against 22.48 GB and 3:41 at 3 tiles.
- The tile default is the user's decision. The wall cost measured so far is 3% on TNBC and 13% on D, both on
  shared nodes.
