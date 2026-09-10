# dnoise, the MS1 prune and tiling on the final build (2026-09-10, arm `dnoise_s2b`)

Every combination on the build that ships: dnoise MS1 on or off, the MS1 prune on or off, the tiled layout
(`-tile:cells_per_tile 1`) against the shipped single tile, and the two allocator levers from data6-tile-count.md.
The build is `dnoise_s2b`, binary 2d9aa6c4, with the stage-1 review fixes. All runs use 100 threads at pitch 600, and
every run's digest is shown.

## Dataset D (ibminode05, back to back, load 40-95 from other users)

| dnoise | prune | tiles | extra | peak | wall | ledger peak, phase | counted live | glibc free | MS1 map | MS1 load | digest |
|---|---|---:|---|---:|---:|---|---:|---:|---:|---:|---|
| off | off | 3 | | 31.99 GB | 4:15 | 31,310 MiB, pass 1 | 14,744 | 6,089 | 13,830 MiB | 27.5 s | `8c1b047f` |
| off | on | 3 | | 25.90 GB | 4:13 | 25,312 MiB, tile 2 | 9,443 | 9,032 | 2,671 MiB | 29.9 s | `8c1b047f` |
| on | off | 3 | | 22.62 GB | 3:38 | 22,032 MiB, tile 2 | 9,589 | 6,529 | 830 MiB | 14.7 s | `e43672a0` |
| **on** | **on** | 3 | | **22.48 GB** | **3:41** | 21,967 MiB, tile 2 | 9,747 | 6,080 | 650 MiB | 15.0 s | `e43672a0` |
| off | on | 1 | | 38.57 GB | 3:45 | 37,736 MiB, tile 1 | 21,668 | 8,667 | 2,671 MiB | 29.3 s | `8c1b047f` |
| on | on | 1 (shipped default) | | 37.44 GB | 3:15 | 36,515 MiB, tile 1 | 21,493 | 4,886 | 650 MiB | 15.2 s | `e43672a0` |
| on | on | 3 | trim between tiles | 21.99 GB | 3:47 | 21,497 MiB, tile 2 | 9,080 | 5,098 | 650 MiB | 17.4 s | `e43672a0` |
| on | on | 3 | eager trim threshold | 18.14 GB | 4:06 | 17,770 MiB, tile 2 | 9,110 | 1,816 | 650 MiB | 25.1 s | `e43672a0` |

MS1 map is the ledger's peak for the picked MS1 map (20 B per centroid). MS1 load is `[perf] LOAD(stream)` wall.

On D:
- **The defaults take the tiled peak from 32.0 to 22.5 GB (−30%) and the wall from 4:15 to 3:41 (−13%).** The MS1
  load halves (27.5 → 15.0 s), because the picker sees an eighth of the points.
- **The prune alone takes 6.1 GB off with identical output.** After dnoise it adds only 0.14 GB: the tile loop, not
  MS1, sets D's peak once either has acted.
- **At the shipped single tile, dnoise and the prune barely matter (38.6 → 37.4 GB).** The one tile's window loop sets
  the peak. Tiling (3 tiles) takes it to 22.5 GB for about 13% more wall (3:15 → 3:41).
- **A trim between tiles takes 0.5 GB; the eager trim threshold takes 4.3 GB (−19%) for about 11% wall.** On D the
  growth happens inside a tile, where only continuous trimming acts (data6-tile-count.md).

## TNBC 009

Two sets, each back to back on a node shared with other users: the 13-tile 2x2 on `spock`, and the single tile and
the trims on `data`. Compare memory within a node only; walls are indicative.

| node | dnoise | prune | tiles | extra | peak | wall | ledger peak, phase | counted live | glibc free | MS1 map | MS1 load | digest |
|---|---|---|---:|---|---:|---:|---|---:|---:|---:|---:|---|
| spock | off | off | 13 | | 69.11 GB | 9:33 | 67,537 MiB, pass 1 | 30,450 | 26,722 | 45,617 MiB | 42.7 s | `bff54a1f` |
| spock | off | on | 13 | | 31.97 GB | 10:25 | 31,332 MiB, tile 9 | 7,257 | 18,174 | 7,078 MiB | 58.5 s | `bff54a1f` |
| spock | on | off | 13 | | 26.20 GB | 11:41 | 25,752 MiB, tile 7 | 7,297 | 12,730 | 5,901 MiB | 65.0 s | `3aafd0b5` |
| spock | **on** | **on** | 13 | | **25.17 GB** | 10:46 | 24,734 MiB, tile 7 | 7,017 | 11,353 | 3,430 MiB | 68.4 s | `3aafd0b5` |
| data | off | on | 1 | | 103.01 GB | 10:48 | 100,548 MiB, tile 1 | 85,440 | 18,102 | 7,078 MiB | 55.7 s | `bff54a1f` |
| data | on | on | 1 (shipped default) | | 99.70 GB | 9:42 | 97,539 MiB, tile 1 | 88,161 | 11,003 | 3,430 MiB | 37.0 s | `3aafd0b5` |
| data | off | on | 13 | trim between tiles | 29.08 GB | 10:19 | 28,558 MiB, pass 1 | 0 | 18,262 | 7,078 MiB | 56.5 s | `bff54a1f` |
| data | on | on | 13 | trim between tiles | 21.07 GB | 9:57 | 20,718 MiB, tile 7 | 6,717 | 11,363 | 3,430 MiB | 34.3 s | `3aafd0b5` |
| data | on | on | 13 | eager trim threshold | 20.73 GB | 10:17 | 20,413 MiB, tile 7 | 7,083 | 7,528 | 3,430 MiB | 96.3 s | `3aafd0b5` |

At the pass-1 peak of the trimmed dnoise-off arm nothing is counted: MS1 tracing's working memory is not in the
ledger.

On TNBC 009:
- **The defaults at 13 tiles take the peak from 69.1 to 25.2 GB (−64%).** The wall does not follow a pattern on
  `spock`: the arm with neither feature was the fastest there (9:33), yet on `data` dnoise shortened the wall at one
  tile (10:48 → 9:42) and at 13 tiles (10:19 → 9:57). The MS1 load behaves the same way: slower with dnoise on
  `spock` (58.5 → 68.4 s), faster on `data` (55.7 → 37.0 s).
- **The prune alone takes 37.1 GB off (−54%) with identical output.** The MS1 map shrinks 6.4x and the peak moves
  from pass 1 into the tile loop.
- **dnoise alone takes 42.9 GB off, and changes the output (the new pin).** It cuts the picked MS1 centroids 7.7x
  (2,391,660,683 → 309,395,291). With dnoise on, the prune still takes 1.0 GB, against 0.14 GB on D: 43% of TNBC's
  filtered centroids are at or below 100, so the map still shrinks from 5,901 to 3,430 MiB.
- **At the shipped single tile, the peak is 99.7 GB with dnoise and 103.0 GB without.** The tile's window loop sets
  it (slab 30.5 GiB and parent records 27.6 GiB at the peak); MS1 hardly matters there. 13 tiles with a trim between
  tiles take it to 21.1 GB (−79%) for 15 s more wall (+2.6%). With dnoise off: 103.0 → 29.1 GB, and the tiled run
  was faster (10:48 → 10:19).
- **The two trims at 13 tiles.** They give 21.07 GB (between tiles) and 20.73 GB (eager threshold) with dnoise.
  Without a trim the peak is 25.2 GB, measured on `spock`, so the comparison is only rough. With dnoise off, the
  between-tile trim takes the peak back to pass 1 (28.6 GiB), down from tile 9 (31.3 GiB). The eager threshold
  nearly triples the MS1 load (34.3 → 96.3 s, back to back) for 0.3 GB more.

## Across both files

- **The new defaults (dnoise on, prune on) against the old ones at the same tiling:** D 32.0 → 22.5 GB at 3 tiles;
  TNBC 009 69.1 → 25.2 GB at 13 tiles.
- **The tile count is now the largest lever at identical output:**
  - D: 37.4 → 22.5 GB from 1 to 3 tiles, +13% wall.
  - TNBC 009: 99.7 → 21.1 GB from 1 to 13 tiles with a trim between tiles, +3% wall.
- **A trim between tiles** takes 0.5 GB off D and about 4 GB off TNBC 009.
- **The eager trim threshold** takes 4.3 GB off D and about 4.4 GB off TNBC 009, but slows the MS1 load.
- **Left to the user; this work changes none of them:**
  - the tile default (`tile:cells_per_tile 0`, one tile);
  - a per-tile `malloc_trim`;
  - the eager threshold (via `mallopt` at startup).
