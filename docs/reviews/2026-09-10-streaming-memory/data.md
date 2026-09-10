# Measured: where the memory and the time go (dataset D, 30 min, 24 windows)

The same binary and the same input in every arm, each digest-checked against the pinned
output, with `SPEXTRACTOR_LEDGER` sampling live bytes per data structure every 250 ms next to
the process RSS, the glibc arena figures and a phase marker.

* **resident** = the whole run is loaded up front and the tile loop slices it (the shape
  shipped before today).
* **stream** = pass 1 reads MS1 only; pass 2 calls the Bruker loader once per tile over a
  retention-time range, so a tile's peaks are the only MS2 data resident.

```
=== 2026-09-10T08:06:47+02:00 instr2 on spock ===
git=906e758+ledger-fix
binary_sha256=1674183e8e62f4b1d1cf99967aa1dde9525a46399edfc97ae9046862269ab686
node spock, 224 cores, MemAvailable 1006 GB, load 21.67, 33.71, 25.51
```

| arm | source | tiles | wall | peak RSS | major faults | output |
|---|---|---:|---:|---:|---:|---|
| `resident_1tile` | resident | 1 | 2:33.63 | 47.2 GB | 563 | identical |
| `stream_1tile` | stream | 1 | 2:26.67 | 41.1 GB | 551 | identical |
| `stream_3tiles` | stream | 3 | 2:57.14 | 31.8 GB | 580 | identical |
| `stream_6tiles` | stream | 6 | 2:48.05 | 31.8 GB | 598 | identical |

**How to read the ledger.** `sum_mb` is what the charges account for; `unattributed_mb` is
`RSS - sum`, i.e. the allocator's retained free list plus anything not charged (the picker's
per-thread buffers, OpenMS's own transients inside the loader, and the frame-table vectors, all
small individually). `glibc free` is `mallinfo2().fordblks` -- memory the program returned to the
allocator and the allocator kept. The charges are TOUCHED bytes, not capacity: `PeakSlab`
deliberately over-reserves 2.5x and untouched pages cost address space, not residency.

**The single most important row.** In the 6-tile streaming arm the process peak is no longer the
window loop; it is the MS1 pass, at t ~ 9 s, before a single MS2 frame has been read. That is why
the 3-tile and 6-tile arms have the same peak: the MS2 side is already below the MS1 floor, and
tiling it further changes nothing until pass 1 is tiled too.

## resident_1tile  (`defaults`)

### phases (wall s | % of total | CPU s | parallelism | RSS at end)
```
  [perf] phase breakdown (wall s | % of total | CPU s | par x | RSS MB at end)
  [perf] LOAD(stream)               27.1   17.7%     1485.3   54.9x     40540
  [perf] MS1_TRACE                  14.6    9.5%      221.6   15.2x     34080
  [perf] PRECURSOR_INFER             4.0    2.6%       62.0   15.7x     14880
  [perf] SORT(canonical)             0.5    0.3%        1.4    2.6x     22074
  [perf] WRITE(mzML)                 3.1    2.0%      162.6   53.1x      3050  (summed)
  [perf] WINDOW_LOOP                97.4   63.6%     6101.3   62.6x     21531
  [perf] TOTAL(measured)           146.7   95.8%  (unattributed 6.5 s)
```

### the tile loop
```
  [tile] 1 tile(s) of up to 3 cell(s): [-inf,inf)
  [tile] coverage: 710356 precursor-window pairs owned exactly once over 1 tile(s)
  [tile] 1/1: 611850 spectra written [t=150s] [RSS 22781504 kB, peak 47244608 kB] [malloc arena=25649 MB mmap=438 MB free=19799 MB]
```

### admission
```
  Parallelism: 24 windows x 12 m/z bands = 288 trace units; 100 worker threads over one task pool; up to 24 windows in flight (memory-bounded)
  All windows done (admission high-water 24 of 24 allowed concurrent windows). [t=151s] [RSS 22048648 kB, peak 47244608 kB] [malloc arena=25308 MB mmap=0 MB free=23722 MB]
```

### the three heaviest windows (prep | trace | split | score | emit)
```
    window 9/24 641.57000000000005-663.330000000000041: prep 2.127585054 s | trace 31.174576415999997 s | split 2.324567563 s | score 7.415384454 s | emit 4.359491e-03 s | spectra 18588 [t=98s]
    window 8/24 581.850000000000023-602.830000000000041: prep 1.684314828 s | trace 29.853241484000005 s | split 3.693312947 s | score 6.942902352 s | emit 3.904694e-03 s | spectra 19746 [t=97s]
    window 7/24 601.830000000000041-622.360000000000014: prep 1.852871489 s | trace 28.776510441999996 s | split 4.482451335 s | score 5.909417003 s | emit 8.144653999999999e-03 s | spectra 18729 [t=96s
  digest 8c1b047f3f70066c (expected 8c1b047f3f70066c: MATCH)
```

### the ledger: live bytes per structure
```

  === ledger.tsv  (153 s sampled, 555 rows)
  peak RSS          46272 MB at t=   26.6 s  phase=start   (charged 26629 MB, unattributed 19643 MB, glibc free 11687 MB)
  peak charged      26629 MB at t=   26.6 s  phase=start   (RSS 46272 MB)

  per structure: peak, when, and how long it is above 5% of the peak RSS
    ms1_map      peak    13830 MB at t=   10.3 (start     )     13830 MB at the RSS peak   above 5% of peak RSS for   46.4 s (30.3%)
    slab         peak    11997 MB at t=   28.4 (start     )     11802 MB at the RSS peak   above 5% of peak RSS for  111.6 s (72.8%)
    parent       peak     5593 MB at t=   93.1 (tile1     )         0 MB at the RSS peak   above 5% of peak RSS for   59.6 s (38.9%)
    band_arena   peak     4126 MB at t=   83.2 (tile1     )         0 MB at the RSS peak   above 5% of peak RSS for   52.5 s (34.2%)
    scratch      peak     3842 MB at t=    6.2 (start     )       996 MB at the RSS peak   above 5% of peak RSS for    6.6 s ( 4.3%)
    spectra      peak     3475 MB at t=  146.1 (tile1     )         0 MB at the RSS peak   above 5% of peak RSS for   20.2 s (13.2%)
    prep         peak     2395 MB at t=   73.4 (tile1     )         0 MB at the RSS peak   above 5% of peak RSS for    3.3 s ( 2.2%)
    wstore       peak     2291 MB at t=  125.3 (tile1     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    frag_aux     peak     1619 MB at t=   91.0 (tile1     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    ms1_trace    peak      533 MB at t=   48.9 (start     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    precursor    peak      133 MB at t=   53.6 (start     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    writer       peak       23 MB at t=  150.3 (write1    )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)

  phases
    start           54.1 s   RSS      17 ->   14880 MB  (peak   46272)   top: ms1_map 13830, slab 11997, scratch 3842
    tile1           92.4 s   RSS   16310 ->   22437 MB  (peak   41992)   top: slab 11997, parent 5593, band_arena 4126
    write1           5.8 s   RSS   22157 ->    3050 MB  (peak   22247)   top: spectra 3475, scratch 669, writer 23
    end              0.0 s   RSS    3050 ->    3050 MB  (peak    3050)   top: scratch 669, writer 23

  per tile (read | loop | write), RSS peak and the charged peak
    tile   1: read   92.4s rss<=  41992 charged<=  23591 | writ    5.8s rss<=  22247 charged<=   4145
```


## stream_1tile  (`defaults`)

### phases (wall s | % of total | CPU s | parallelism | RSS at end)
```
  [perf] phase breakdown (wall s | % of total | CPU s | par x | RSS MB at end)
  [perf] LOAD(stream)               10.2    7.0%      682.7   66.8x     27922
  [perf] MS1_TRACE                  13.9    9.5%      201.5   14.5x     19671
  [perf] PRECURSOR_INFER             3.7    2.5%       57.9   15.8x      2299
  [perf] LOAD(tile)                 17.4   11.9%      801.7   46.0x     24956
  [perf] SORT(canonical)             0.5    0.4%        1.6    2.9x     21442
  [perf] WRITE(mzML)                 2.8    1.9%      141.7   50.0x      2993  (summed)
  [perf] WINDOW_LOOP               110.2   75.4%     6935.4   62.9x     20457
  [perf] TOTAL(measured)           158.8  108.7%  (unattributed -12.7 s)
```

### the tile loop
```
  [tile] 1 tile(s) of up to 3 cell(s): [-inf,inf)
  [tile] 1/1 [-inf,inf) read: 24 windows, frames delivered 32210 padded 0 absent-windows 0, 1258053975 peaks, 17.399128613000002 s [RSS 25698024 kB, peak 31876908 kB] [malloc arena=21489 MB mmap=23355 M
  [tile] coverage: 710356 precursor-window pairs owned exactly once over 1 tile(s)
  [tile] 1/1: 611850 spectra written [t=143s] [RSS 22093056 kB, peak 41086576 kB] [malloc arena=23830 MB mmap=438 MB free=17975 MB]
```

### admission
```
  Parallelism: 24 windows x 12 m/z bands = 288 trace units; 100 worker threads over one task pool; up to 24 windows in flight (memory-bounded)
  All windows done (admission high-water 24 of 24 allowed concurrent windows). [t=144s] [RSS 20948108 kB, peak 41086576 kB] [malloc arena=23014 MB mmap=0 MB free=21423 MB]
```

### the three heaviest windows (prep | trace | split | score | emit)
```
    window 9/24 662.330000000000041-685.289999999999964: prep 2.213158622 s | trace 34.885821047 s | split 6.154045008 s | score 1.624495215 s | emit 8.004112000000001e-03 s | spectra 18231 [t=97s]
    window 8/24 601.830000000000041-622.360000000000014: prep 2.986589653 s | trace 31.254988012999998 s | split 1.167266875 s | score 6.741955088 s | emit 0.012075607 s | spectra 18729 [t=94s]
    window 7/24 621.360000000000014-642.57000000000005: prep 2.830163611 s | trace 30.789696742 s | split 1.580820252 s | score 5.880370376 s | emit 7.422433000000001e-03 s | spectra 17562 [t=93s]
  digest 8c1b047f3f70066c (expected 8c1b047f3f70066c: MATCH)
```

### the ledger: live bytes per structure
```

  === ledger.tsv  (146 s sampled, 524 rows)
  peak RSS          40299 MB at t=   88.6 s  phase=loop1   (charged 22394 MB, unattributed 17905 MB, glibc free 12943 MB)
  peak charged      23035 MB at t=   80.8 s  phase=loop1   (RSS 39670 MB)

  per structure: peak, when, and how long it is above 5% of the peak RSS
    ms1_map      peak    13830 MB at t=   11.5 (start     )         0 MB at the RSS peak   above 5% of peak RSS for   25.1 s (17.2%)
    slab         peak    11997 MB at t=   51.5 (loop1     )      8812 MB at the RSS peak   above 5% of peak RSS for   86.6 s (59.2%)
    parent       peak     5401 MB at t=   92.8 (loop1     )      4979 MB at the RSS peak   above 5% of peak RSS for   62.8 s (42.9%)
    band_arena   peak     4220 MB at t=   92.5 (loop1     )      3251 MB at the RSS peak   above 5% of peak RSS for   53.3 s (36.5%)
    scratch      peak     3842 MB at t=    6.3 (start     )       669 MB at the RSS peak   above 5% of peak RSS for    6.4 s ( 4.4%)
    spectra      peak     3475 MB at t=  139.3 (loop1     )       433 MB at the RSS peak   above 5% of peak RSS for   19.0 s (13.0%)
    wstore       peak     2444 MB at t=  121.1 (loop1     )      1061 MB at the RSS peak   above 5% of peak RSS for    2.0 s ( 1.3%)
    prep         peak     2418 MB at t=   72.4 (loop1     )      1856 MB at the RSS peak   above 5% of peak RSS for   20.4 s (13.9%)
    frag_aux     peak     1011 MB at t=   87.8 (loop1     )      1011 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    ms1_trace    peak      533 MB at t=   29.3 (start     )       184 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    precursor    peak      133 MB at t=   34.0 (start     )       133 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    writer       peak       23 MB at t=  143.3 (write1    )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)

  phases
    start           34.0 s   RSS      17 ->    2299 MB  (peak   31347)   top: ms1_map 13830, scratch 3842, ms1_trace 533
    tile1           17.0 s   RSS    5934 ->   26568 MB  (peak   28816)   top: slab 11976, scratch 1225, ms1_trace 184
    loop1           88.6 s   RSS   24956 ->   21842 MB  (peak   40299)   top: slab 11997, parent 5401, band_arena 4220
    write1           5.6 s   RSS   21507 ->    2992 MB  (peak   21573)   top: spectra 3475, scratch 669, writer 23
    end              0.0 s   RSS    2993 ->    2993 MB  (peak    2993)   top: scratch 669, writer 23

  per tile (read | loop | write), RSS peak and the charged peak
    tile   1: read   17.0s rss<=  28816 charged<=  13117 | loop   88.6s rss<=  40299 charged<=  23035 | writ    5.6s rss<=  21573 charged<=   4145
```


## stream_3tiles  (`-tile:cells_per_tile 1`)

### phases (wall s | % of total | CPU s | parallelism | RSS at end)
```
  [perf] phase breakdown (wall s | % of total | CPU s | par x | RSS MB at end)
  [perf] LOAD(stream)               10.2    5.8%      683.6   67.0x     27321
  [perf] MS1_TRACE                  14.7    8.3%      211.2   14.3x     20727
  [perf] PRECURSOR_INFER             3.7    2.1%       60.9   16.3x      2379
  [perf] LOAD(tile)                 15.0    8.5%      825.4   55.0x     24819  (summed)
  [perf] SORT(canonical)             0.4    0.2%        2.5    6.1x     20183  (summed)
  [perf] WRITE(mzML)                 2.9    1.6%      144.3   50.1x      2897  (summed)
  [perf] WINDOW_LOOP               140.0   79.2%     6179.6   44.2x     20026
  [perf] TOTAL(measured)           186.9  105.8%  (unattributed -10.3 s)
```

### the tile loop
```
  [tile] 3 tile(s) of up to 1 cell(s): [-inf,602.046097000000032) [602.046097000000032,1203.231939000000011) [1203.231939000000011,inf)
  [tile] 1/3 [-inf,602.046097000000032) read: 24 windows, frames delivered 10416 padded 0 absent-windows 0, 96046271 peaks, 1.601277691999997 s [RSS 9492936 kB, peak 31801756 kB] [malloc arena=22690 MB
  [tile] window 866.409999999999968-900.960000000000036 tile 1: carried in 0, carrying out 34900 fragments (1831 KB)
  [tile] window 986.019999999999982-1046.519999999999982 tile 1: carried in 0, carrying out 32873 fragments (1683 KB)
  [tile] window 807.419999999999959-835.42999999999995 tile 1: carried in 0, carrying out 37262 fragments (1973 KB)
  [tile] window 834.42999999999995-867.409999999999968 tile 1: carried in 0, carrying out 36066 fragments (1898 KB)
  [tile] window 707.32000000000005-730.370000000000005 tile 1: carried in 0, carrying out 37548 fragments (2024 KB)
  [tile] window 939.92999999999995-987.019999999999982 tile 1: carried in 0, carrying out 35395 fragments (1808 KB)
  [tile] window 899.960000000000036-940.92999999999995 tile 1: carried in 0, carrying out 32389 fragments (1702 KB)
  [tile] window 754.870000000000005-780.909999999999968 tile 1: carried in 0, carrying out 36078 fragments (1936 KB)
  [tile] window 779.909999999999968-808.419999999999959 tile 1: carried in 0, carrying out 41312 fragments (2214 KB)
  [tile] window 1045.519999999999982-1135.059999999999945 tile 1: carried in 0, carrying out 34004 fragments (1774 KB)
  [tile] window 729.370000000000005-755.870000000000005 tile 1: carried in 0, carrying out 40774 fragments (2215 KB)
  [tile] window 1134.059999999999945-1400.619999999999891 tile 1: carried in 0, carrying out 41931 fragments (2252 KB)
  [tile] window 544.789999999999964-564.629999999999996 tile 1: carried in 0, carrying out 45529 fragments (2570 KB)
  [tile] window 563.629999999999996-582.850000000000023 tile 1: carried in 0, carrying out 46814 fragments (2580 KB)
  [tile] window 662.330000000000041-685.289999999999964 tile 1: carried in 0, carrying out 51112 fragments (2711 KB)
  [tile] window 523.299999999999955-545.789999999999964 tile 1: carried in 0, carrying out 52737 fragments (2986 KB)
  [tile] window 641.57000000000005-663.330000000000041 tile 1: carried in 0, carrying out 49745 fragments (2650 KB)
  [tile] window 684.289999999999964-708.32000000000005 tile 1: carried in 0, carrying out 55072 fragments (2837 KB)
  [tile] window 621.360000000000014-642.57000000000005 tile 1: carried in 0, carrying out 48939 fragments (2598 KB)
  [tile] window 581.850000000000023-602.830000000000041 tile 1: carried in 0, carrying out 49183 fragments (2700 KB)
  [tile] window 601.830000000000041-622.360000000000014 tile 1: carried in 0, carrying out 45428 fragments (2481 KB)
  [tile] window 499.589999999999975-524.299999999999955 tile 1: carried in 0, carrying out 53413 fragments (3084 KB)
  [tile] window 467.800000000000011-500.589999999999975 tile 1: carried in 0, carrying out 60992 fragments (3601 KB)
  [tile] window 327.519999999999982-468.800000000000011 tile 1: carried in 0, carrying out 163971 fragments (10144 KB)
  [tile] 1/3: 51036 spectra written [t=49s] [RSS 12075092 kB, peak 31801756 kB] [malloc arena=22519 MB mmap=118 MB free=20485 MB]
  [tile] 2/3 [602.046097000000032,1203.231939000000011) read: 24 windows, frames delivered 10416 padded 0 absent-windows 0, 606052484 peaks, 7.167527595999999 s [RSS 20670792 kB, peak 31801756 kB] [mall
  [tile] window 1134.059999999999945-1400.619999999999891 tile 2: carried in 41931, carrying out 88450 fragments (5400 KB)
  [tile] window 544.789999999999964-564.629999999999996 tile 2: carried in 45529, carrying out 50222 fragments (2874 KB)
  [tile] window 523.299999999999955-545.789999999999964 tile 2: carried in 52737, carrying out 50326 fragments (2881 KB)
  [tile] window 499.589999999999975-524.299999999999955 tile 2: carried in 53413, carrying out 43300 fragments (2535 KB)
  [tile] window 1045.519999999999982-1135.059999999999945 tile 2: carried in 34004, carrying out 88135 fragments (5207 KB)
  [tile] window 939.92999999999995-987.019999999999982 tile 2: carried in 35395, carrying out 100087 fragments (5988 KB)
  [tile] window 563.629999999999996-582.850000000000023 tile 2: carried in 46814, carrying out 46885 fragments (2768 KB)
  [tile] window 986.019999999999982-1046.519999999999982 tile 2: carried in 32873, carrying out 95099 fragments (5612 KB)
  [tile] window 621.360000000000014-642.57000000000005 tile 2: carried in 48939, carrying out 77302 fragments (4542 KB)
  [tile] window 601.830000000000041-622.360000000000014 tile 2: carried in 45428, carrying out 65134 fragments (3831 KB)
  [tile] window 581.850000000000023-602.830000000000041 tile 2: carried in 49183, carrying out 60461 fragments (3568 KB)
  [tile] window 467.800000000000011-500.589999999999975 tile 2: carried in 60992, carrying out 45438 fragments (2669 KB)
  [tile] window 641.57000000000005-663.330000000000041 tile 2: carried in 49745, carrying out 86684 fragments (5219 KB)
  [tile] window 662.330000000000041-685.289999999999964 tile 2: carried in 51112, carrying out 94170 fragments (5615 KB)
  [tile] window 684.289999999999964-708.32000000000005 tile 2: carried in 55072, carrying out 101409 fragments (6100 KB)
  [tile] window 866.409999999999968-900.960000000000036 tile 2: carried in 34900, carrying out 104212 fragments (6117 KB)
  [tile] window 899.960000000000036-940.92999999999995 tile 2: carried in 32389, carrying out 103004 fragments (6202 KB)
  [tile] window 807.419999999999959-835.42999999999995 tile 2: carried in 37262, carrying out 102279 fragments (6165 KB)
  [tile] window 779.909999999999968-808.419999999999959 tile 2: carried in 41312, carrying out 106989 fragments (6509 KB)
  [tile] window 707.32000000000005-730.370000000000005 tile 2: carried in 37548, carrying out 106743 fragments (6440 KB)
  [tile] window 834.42999999999995-867.409999999999968 tile 2: carried in 36066, carrying out 106371 fragments (6482 KB)
  [tile] window 754.870000000000005-780.909999999999968 tile 2: carried in 36078, carrying out 100043 fragments (6112 KB)
  [tile] window 729.370000000000005-755.870000000000005 tile 2: carried in 40774, carrying out 106773 fragments (6543 KB)
  [tile] window 327.519999999999982-468.800000000000011 tile 2: carried in 163971, carrying out 88634 fragments (5605 KB)
  [tile] 2/3: 338193 spectra written [t=120s] [RSS 20185276 kB, peak 31801756 kB] [malloc arena=22661 MB mmap=118 MB free=17967 MB]
  [tile] 3/3 [1203.231939000000011,inf) read: 24 windows, frames delivered 11378 padded 0 absent-windows 0, 555955220 peaks, 6.245428363000002 s [RSS 25415232 kB, peak 31801756 kB] [malloc arena=22390 M
  [tile] coverage: 710356 precursor-window pairs owned exactly once over 3 tile(s)
  [tile] 3/3: 222621 spectra written [t=174s] [RSS 20668296 kB, peak 31801756 kB] [malloc arena=22092 MB mmap=0 MB free=18650 MB]
```

### admission
```
  Parallelism: 24 windows x 12 m/z bands = 288 trace units; 100 worker threads over one task pool; up to 24 windows in flight (memory-bounded)
  All windows done (admission high-water 24 of 24 allowed concurrent windows). [t=175s] [RSS 20506696 kB, peak 31801756 kB] [malloc arena=21924 MB mmap=0 MB free=20328 MB]
```

### the three heaviest windows (prep | trace | split | score | emit)
```
    window 9/24 779.909999999999968-808.419999999999959: prep 0.130549389 s | trace 1.602102379 s | split 0.110666278 s | score 0.027988016 s | emit 5.25274e-04 s | spectra 1314 [t=38s]
    window 9/24 641.57000000000005-663.330000000000041: prep 0.731221684 s | trace 10.459311966000001 s | split 0.811075655 s | score 0.409029937 s | emit 1.806031e-03 s | spectra 6807 [t=139s]
    window 9/24 621.360000000000014-642.57000000000005: prep 1.430992606 s | trace 16.408743567999998 s | split 1.471624768 s | score 0.505513853 s | emit 2.111422e-03 s | spectra 9936 [t=76s]
  digest 8c1b047f3f70066c (expected 8c1b047f3f70066c: MATCH)
```

### the ledger: live bytes per structure
```

  === ledger.tsv  (177 s sampled, 655 rows)
  peak RSS          30920 MB at t=    9.5 s  phase=start   (charged 13897 MB, unattributed 17023 MB, glibc free 6302 MB)
  peak charged      13897 MB at t=    8.6 s  phase=start   (RSS 28860 MB)

  per structure: peak, when, and how long it is above 5% of the peak RSS
    ms1_map      peak    13830 MB at t=   11.4 (start     )     10508 MB at the RSS peak   above 5% of peak RSS for   25.1 s (14.2%)
    slab         peak     5779 MB at t=   56.3 (loop2     )         0 MB at the RSS peak   above 5% of peak RSS for   78.3 s (44.3%)
    scratch      peak     3842 MB at t=    6.0 (start     )      3388 MB at the RSS peak   above 5% of peak RSS for    6.2 s ( 3.5%)
    prep         peak     2371 MB at t=   59.9 (loop2     )         0 MB at the RSS peak   above 5% of peak RSS for   40.8 s (23.1%)
    spectra      peak     1965 MB at t=  118.0 (loop2     )         0 MB at the RSS peak   above 5% of peak RSS for    1.9 s ( 1.1%)
    parent       peak     1130 MB at t=   73.3 (loop2     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    wstore       peak     1093 MB at t=  160.1 (loop3     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    band_arena   peak      605 MB at t=  108.1 (loop2     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    ms1_trace    peak      533 MB at t=   30.2 (start     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    frag_aux     peak      351 MB at t=   90.6 (loop2     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    carry        peak      166 MB at t=  120.4 (tile3     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    precursor    peak      133 MB at t=   32.8 (start     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    writer       peak       23 MB at t=  174.5 (write3    )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)

  phases
    start           34.7 s   RSS      17 ->    2379 MB  (peak   30920)   top: ms1_map 13830, scratch 3842, ms1_trace 533
    tile1            1.3 s   RSS    5429 ->    9513 MB  (peak    9513)   top: slab 860, scratch 415, ms1_trace 184
    loop1           12.1 s   RSS    9545 ->   11934 MB  (peak   11934)   top: slab 915, prep 325, parent 304
    write1           0.0 s   RSS   11774 ->   11774 MB  (peak   11774)   top: spectra 268, scratch 209, ms1_trace 184
    tile2            6.9 s   RSS   12001 ->   20931 MB  (peak   21642)   top: slab 5650, scratch 1241, ms1_trace 184
    loop2           62.0 s   RSS   20186 ->   19694 MB  (peak   28086)   top: slab 5779, prep 2371, spectra 1965
    write2           1.6 s   RSS   19710 ->   19607 MB  (peak   19712)   top: spectra 1965, scratch 681, ms1_trace 184
    tile3            5.9 s   RSS   19569 ->   26374 MB  (peak   26374)   top: slab 4985, scratch 681, ms1_trace 184
    loop3           46.6 s   RSS   24819 ->   20177 MB  (peak   28186)   top: slab 5302, prep 2156, spectra 1240
    write3           3.1 s   RSS   20183 ->    2937 MB  (peak   20183)   top: spectra 1240, scratch 250, carry 166
    end              0.0 s   RSS    2897 ->    2897 MB  (peak    2897)   top: scratch 250, writer 23

  per tile (read | loop | write), RSS peak and the charged peak
    tile   1: read    1.3s rss<=   9513 charged<=   1419 | loop   12.1s rss<=  11934 charged<=   1872 | writ    0.0s rss<=  11774 charged<=    796
    tile   2: read    6.9s rss<=  21642 charged<=   6742 | loop   62.0s rss<=  28086 charged<=   9574 | writ    1.6s rss<=  19712 charged<=   3058
    tile   3: read    5.9s rss<=  26374 charged<=   6095 | loop   46.6s rss<=  28186 charged<=   8805 | writ    3.1s rss<=  20183 charged<=   1673
```


## stream_6tiles  (`-tile:rt_sec 300 -tile:cells_per_tile 1`)

### phases (wall s | % of total | CPU s | parallelism | RSS at end)
```
  [perf] phase breakdown (wall s | % of total | CPU s | par x | RSS MB at end)
  [perf] LOAD(stream)               10.4    6.2%      689.5   66.4x     27459
  [perf] MS1_TRACE                  14.0    8.4%      214.0   15.3x     20359
  [perf] PRECURSOR_INFER             4.1    2.5%       69.7   16.9x      2457
  [perf] LOAD(tile)                 14.0    8.4%      845.0   60.4x     21279  (summed)
  [perf] SORT(canonical)             0.5    0.3%        3.5    7.6x     19622  (summed)
  [perf] WRITE(mzML)                 2.7    1.6%      131.2   48.1x      2947  (summed)
  [perf] WINDOW_LOOP               130.8   78.1%     5528.9   42.3x     19622
  [perf] TOTAL(measured)           176.5  105.3%  (unattributed -9.0 s)
```

### the tile loop
```
  [tile] 6 tile(s) of up to 1 cell(s): [-inf,301.443799000000013) [301.443799000000013,602.046097000000032) [602.046097000000032,902.646286000000032) [902.646286000000032,1203.231939000000011) [1203.231
  [tile] 1/6 [-inf,301.443799000000013) read: 24 windows, frames delivered 5208 padded 0 absent-windows 0, 12986293 peaks, 0.232122679999996 s [RSS 3382072 kB, peak 31762600 kB] [malloc arena=22532 MB m
  [tile] window 621.360000000000014-642.57000000000005 tile 1: carried in 0, carrying out 7690 fragments (340 KB)
  [tile] window 563.629999999999996-582.850000000000023 tile 1: carried in 0, carrying out 5082 fragments (223 KB)
  [tile] window 601.830000000000041-622.360000000000014 tile 1: carried in 0, carrying out 5843 fragments (258 KB)
  [tile] window 581.850000000000023-602.830000000000041 tile 1: carried in 0, carrying out 5500 fragments (242 KB)
  [tile] window 544.789999999999964-564.629999999999996 tile 1: carried in 0, carrying out 4739 fragments (209 KB)
  [tile] window 523.299999999999955-545.789999999999964 tile 1: carried in 0, carrying out 4863 fragments (216 KB)
  [tile] window 499.589999999999975-524.299999999999955 tile 1: carried in 0, carrying out 4723 fragments (210 KB)
  [tile] window 641.57000000000005-663.330000000000041 tile 1: carried in 0, carrying out 8473 fragments (376 KB)
  [tile] window 662.330000000000041-685.289999999999964 tile 1: carried in 0, carrying out 9608 fragments (427 KB)
  [tile] window 707.32000000000005-730.370000000000005 tile 1: carried in 0, carrying out 5814 fragments (260 KB)
  [tile] window 807.419999999999959-835.42999999999995 tile 1: carried in 0, carrying out 6550 fragments (295 KB)
  [tile] window 729.370000000000005-755.870000000000005 tile 1: carried in 0, carrying out 6093 fragments (274 KB)
  [tile] window 467.800000000000011-500.589999999999975 tile 1: carried in 0, carrying out 5197 fragments (236 KB)
  [tile] window 754.870000000000005-780.909999999999968 tile 1: carried in 0, carrying out 6067 fragments (274 KB)
  [tile] window 779.909999999999968-808.419999999999959 tile 1: carried in 0, carrying out 6384 fragments (288 KB)
  [tile] window 866.409999999999968-900.960000000000036 tile 1: carried in 0, carrying out 6982 fragments (317 KB)
  [tile] window 834.42999999999995-867.409999999999968 tile 1: carried in 0, carrying out 6928 fragments (316 KB)
  [tile] window 899.960000000000036-940.92999999999995 tile 1: carried in 0, carrying out 7424 fragments (340 KB)
  [tile] window 939.92999999999995-987.019999999999982 tile 1: carried in 0, carrying out 10241 fragments (469 KB)
  [tile] window 684.289999999999964-708.32000000000005 tile 1: carried in 0, carrying out 13201 fragments (595 KB)
  [tile] window 986.019999999999982-1046.519999999999982 tile 1: carried in 0, carrying out 10455 fragments (481 KB)
  [tile] window 1045.519999999999982-1135.059999999999945 tile 1: carried in 0, carrying out 11094 fragments (519 KB)
  [tile] window 1134.059999999999945-1400.619999999999891 tile 1: carried in 0, carrying out 11545 fragments (561 KB)
  [tile] window 327.519999999999982-468.800000000000011 tile 1: carried in 0, carrying out 11633 fragments (582 KB)
  [tile] 1/6: 642 spectra written [t=36s] [RSS 4610484 kB, peak 31762600 kB] [malloc arena=22253 MB mmap=129 MB free=20831 MB]
  [tile] 2/6 [301.443799000000013,602.046097000000032) read: 24 windows, frames delivered 5208 padded 0 absent-windows 0, 83059978 peaks, 1.420451710000002 s [RSS 9863708 kB, peak 31762600 kB] [malloc a
  [tile] window 807.419999999999959-835.42999999999995 tile 2: carried in 6550, carrying out 37259 fragments (1973 KB)
  [tile] window 986.019999999999982-1046.519999999999982 tile 2: carried in 10455, carrying out 32878 fragments (1684 KB)
  [tile] window 939.92999999999995-987.019999999999982 tile 2: carried in 10241, carrying out 35394 fragments (1808 KB)
  [tile] window 866.409999999999968-900.960000000000036 tile 2: carried in 6982, carrying out 34900 fragments (1831 KB)
  [tile] window 834.42999999999995-867.409999999999968 tile 2: carried in 6928, carrying out 36061 fragments (1898 KB)
  [tile] window 707.32000000000005-730.370000000000005 tile 2: carried in 5814, carrying out 37551 fragments (2025 KB)
  [tile] window 1045.519999999999982-1135.059999999999945 tile 2: carried in 11094, carrying out 34008 fragments (1774 KB)
  [tile] window 729.370000000000005-755.870000000000005 tile 2: carried in 6093, carrying out 40775 fragments (2214 KB)
  [tile] window 899.960000000000036-940.92999999999995 tile 2: carried in 7424, carrying out 32390 fragments (1702 KB)
  [tile] window 779.909999999999968-808.419999999999959 tile 2: carried in 6384, carrying out 41312 fragments (2214 KB)
  [tile] window 754.870000000000005-780.909999999999968 tile 2: carried in 6067, carrying out 36076 fragments (1936 KB)
  [tile] window 1134.059999999999945-1400.619999999999891 tile 2: carried in 11545, carrying out 41889 fragments (2247 KB)
  [tile] window 563.629999999999996-582.850000000000023 tile 2: carried in 5082, carrying out 46814 fragments (2580 KB)
  [tile] window 544.789999999999964-564.629999999999996 tile 2: carried in 4739, carrying out 45529 fragments (2570 KB)
  [tile] window 662.330000000000041-685.289999999999964 tile 2: carried in 9608, carrying out 51115 fragments (2711 KB)
  [tile] window 581.850000000000023-602.830000000000041 tile 2: carried in 5500, carrying out 49183 fragments (2700 KB)
  [tile] window 523.299999999999955-545.789999999999964 tile 2: carried in 4863, carrying out 52742 fragments (2986 KB)
  [tile] window 684.289999999999964-708.32000000000005 tile 2: carried in 13201, carrying out 55085 fragments (2838 KB)
  [tile] window 601.830000000000041-622.360000000000014 tile 2: carried in 5843, carrying out 45427 fragments (2481 KB)
  [tile] window 641.57000000000005-663.330000000000041 tile 2: carried in 8473, carrying out 49745 fragments (2650 KB)
  [tile] window 621.360000000000014-642.57000000000005 tile 2: carried in 7690, carrying out 48940 fragments (2598 KB)
  [tile] window 499.589999999999975-524.299999999999955 tile 2: carried in 4723, carrying out 53410 fragments (3084 KB)
  [tile] window 467.800000000000011-500.589999999999975 tile 2: carried in 5197, carrying out 60998 fragments (3601 KB)
  [tile] window 327.519999999999982-468.800000000000011 tile 2: carried in 11633, carrying out 163952 fragments (10143 KB)
  [tile] 2/6: 50398 spectra written [t=51s] [RSS 12254672 kB, peak 31762600 kB] [malloc arena=22314 MB mmap=129 MB free=20283 MB]
  [tile] 3/6 [602.046097000000032,902.646286000000032) read: 24 windows, frames delivered 5208 padded 0 absent-windows 0, 233943119 peaks, 2.424832658 s [RSS 16015500 kB, peak 31762600 kB] [malloc arena
  [tile] window 986.019999999999982-1046.519999999999982 tile 3: carried in 32878, carrying out 56237 fragments (3090 KB)
  [tile] window 939.92999999999995-987.019999999999982 tile 3: carried in 35394, carrying out 64665 fragments (3552 KB)
  [tile] window 1045.519999999999982-1135.059999999999945 tile 3: carried in 34008, carrying out 52681 fragments (2892 KB)
  [tile] window 1134.059999999999945-1400.619999999999891 tile 3: carried in 41889, carrying out 67855 fragments (4021 KB)
  [tile] window 684.289999999999964-708.32000000000005 tile 3: carried in 55085, carrying out 82706 fragments (4735 KB)
  [tile] window 544.789999999999964-564.629999999999996 tile 3: carried in 45529, carrying out 55291 fragments (3227 KB)
  [tile] window 866.409999999999968-900.960000000000036 tile 3: carried in 34900, carrying out 59875 fragments (3397 KB)
  [tile] window 523.299999999999955-545.789999999999964 tile 3: carried in 52742, carrying out 54603 fragments (3141 KB)
  [tile] window 641.57000000000005-663.330000000000041 tile 3: carried in 49745, carrying out 74101 fragments (4309 KB)
  [tile] window 807.419999999999959-835.42999999999995 tile 3: carried in 37259, carrying out 65904 fragments (3781 KB)
  [tile] window 899.960000000000036-940.92999999999995 tile 3: carried in 32390, carrying out 56214 fragments (3187 KB)
  [tile] window 662.330000000000041-685.289999999999964 tile 3: carried in 51115, carrying out 83058 fragments (4750 KB)
  [tile] window 834.42999999999995-867.409999999999968 tile 3: carried in 36061, carrying out 62988 fragments (3624 KB)
  [tile] window 563.629999999999996-582.850000000000023 tile 3: carried in 46814, carrying out 56237 fragments (3301 KB)
  [tile] window 621.360000000000014-642.57000000000005 tile 3: carried in 48940, carrying out 72351 fragments (4235 KB)
  [tile] window 581.850000000000023-602.830000000000041 tile 3: carried in 49183, carrying out 56926 fragments (3373 KB)
  [tile] window 779.909999999999968-808.419999999999959 tile 3: carried in 41312, carrying out 77833 fragments (4444 KB)
  [tile] window 499.589999999999975-524.299999999999955 tile 3: carried in 53410, carrying out 56039 fragments (3261 KB)
  [tile] window 601.830000000000041-622.360000000000014 tile 3: carried in 45427, carrying out 57922 fragments (3369 KB)
  [tile] window 467.800000000000011-500.589999999999975 tile 3: carried in 60998, carrying out 72531 fragments (4264 KB)
  [tile] window 754.870000000000005-780.909999999999968 tile 3: carried in 36076, carrying out 69701 fragments (4049 KB)
  [tile] window 707.32000000000005-730.370000000000005 tile 3: carried in 37551, carrying out 76202 fragments (4440 KB)
  [tile] window 729.370000000000005-755.870000000000005 tile 3: carried in 40775, carrying out 89112 fragments (5163 KB)
  [tile] window 327.519999999999982-468.800000000000011 tile 3: carried in 163952, carrying out 139781 fragments (8663 KB)
  [tile] 3/6: 151962 spectra written [t=83s] [RSS 16533068 kB, peak 31762600 kB] [malloc arena=22354 MB mmap=129 MB free=19203 MB]
  [tile] 4/6 [902.646286000000032,1203.231939000000011) read: 24 windows, frames delivered 5208 padded 0 absent-windows 0, 372109365 peaks, 3.707208335999994 s [RSS 20299748 kB, peak 31762600 kB] [mallo
  [tile] window 523.299999999999955-545.789999999999964 tile 4: carried in 54603, carrying out 50421 fragments (2901 KB)
  [tile] window 499.589999999999975-524.299999999999955 tile 4: carried in 56039, carrying out 42979 fragments (2513 KB)
  [tile] window 467.800000000000011-500.589999999999975 tile 4: carried in 72531, carrying out 45725 fragments (2696 KB)
  [tile] window 544.789999999999964-564.629999999999996 tile 4: carried in 55291, carrying out 50263 fragments (2878 KB)
  [tile] window 563.629999999999996-582.850000000000023 tile 4: carried in 56237, carrying out 46888 fragments (2752 KB)
  [tile] window 581.850000000000023-602.830000000000041 tile 4: carried in 56926, carrying out 60510 fragments (3566 KB)
  [tile] window 1134.059999999999945-1400.619999999999891 tile 4: carried in 67855, carrying out 88708 fragments (5439 KB)
  [tile] window 601.830000000000041-622.360000000000014 tile 4: carried in 57922, carrying out 65131 fragments (3839 KB)
  [tile] window 641.57000000000005-663.330000000000041 tile 4: carried in 74101, carrying out 86813 fragments (5226 KB)
  [tile] window 1045.519999999999982-1135.059999999999945 tile 4: carried in 52681, carrying out 88119 fragments (5211 KB)
  [tile] window 621.360000000000014-642.57000000000005 tile 4: carried in 72351, carrying out 77125 fragments (4536 KB)
  [tile] window 939.92999999999995-987.019999999999982 tile 4: carried in 64665, carrying out 99984 fragments (5977 KB)
  [tile] window 986.019999999999982-1046.519999999999982 tile 4: carried in 56237, carrying out 95362 fragments (5633 KB)
  [tile] window 662.330000000000041-685.289999999999964 tile 4: carried in 83058, carrying out 94285 fragments (5627 KB)
  [tile] window 684.289999999999964-708.32000000000005 tile 4: carried in 82706, carrying out 101436 fragments (6103 KB)
  [tile] window 807.419999999999959-835.42999999999995 tile 4: carried in 65904, carrying out 102663 fragments (6208 KB)
  [tile] window 899.960000000000036-940.92999999999995 tile 4: carried in 56214, carrying out 103207 fragments (6228 KB)
  [tile] window 834.42999999999995-867.409999999999968 tile 4: carried in 62988, carrying out 106445 fragments (6482 KB)
  [tile] window 866.409999999999968-900.960000000000036 tile 4: carried in 59875, carrying out 104103 fragments (6116 KB)
  [tile] window 779.909999999999968-808.419999999999959 tile 4: carried in 77833, carrying out 107019 fragments (6526 KB)
  [tile] window 707.32000000000005-730.370000000000005 tile 4: carried in 76202, carrying out 106768 fragments (6442 KB)
  [tile] window 327.519999999999982-468.800000000000011 tile 4: carried in 139781, carrying out 88786 fragments (5626 KB)
  [tile] window 729.370000000000005-755.870000000000005 tile 4: carried in 89112, carrying out 106552 fragments (6520 KB)
  [tile] window 754.870000000000005-780.909999999999968 tile 4: carried in 69701, carrying out 100241 fragments (6119 KB)
  [tile] 4/6: 185752 spectra written [t=113s] [RSS 19218748 kB, peak 31762600 kB] [malloc arena=22301 MB mmap=129 MB free=18737 MB]
  [tile] 5/6 [1203.231939000000011,1503.815769000000046) read: 24 windows, frames delivered 5208 padded 0 absent-windows 0, 363831426 peaks, 3.904080511999993 s [RSS 22498596 kB, peak 31762600 kB] [mall
  [tile] window 499.589999999999975-524.299999999999955 tile 5: carried in 42979, carrying out 21856 fragments (1193 KB)
  [tile] window 467.800000000000011-500.589999999999975 tile 5: carried in 45725, carrying out 23240 fragments (1264 KB)
  [tile] window 523.299999999999955-545.789999999999964 tile 5: carried in 50421, carrying out 23207 fragments (1282 KB)
  [tile] window 544.789999999999964-564.629999999999996 tile 5: carried in 50263, carrying out 22266 fragments (1221 KB)
  [tile] window 563.629999999999996-582.850000000000023 tile 5: carried in 46888, carrying out 45904 fragments (2438 KB)
  [tile] window 581.850000000000023-602.830000000000041 tile 5: carried in 60510, carrying out 32657 fragments (1841 KB)
  [tile] window 601.830000000000041-622.360000000000014 tile 5: carried in
```

### admission
```
  Parallelism: 24 windows x 12 m/z bands = 288 trace units; 100 worker threads over one task pool; up to 24 windows in flight (memory-bounded)
  All windows done (admission high-water 24 of 24 allowed concurrent windows). [t=166s] [RSS 20093532 kB, peak 31762600 kB] [malloc arena=22047 MB mmap=12 MB free=20457 MB]
```

### the three heaviest windows (prep | trace | split | score | emit)
```
    window 9/24 899.960000000000036-940.92999999999995: prep 0.093865113 s | trace 1.557048818 s | split 0.084914371 s | score 0.010970734 s | emit 3.68506e-04 s | spectra 787 [t=39s]
    window 9/24 662.330000000000041-685.289999999999964: prep 0.1524431 s | trace 2.300488128 s | split 0.239617659 s | score 0.087051014 s | emit 7.38238e-04 s | spectra 1909 [t=152s]
    window 9/24 662.330000000000041-685.289999999999964: prep 0.015911567 s | trace 0.174223662 s | split 0.03214415 s | score 1.02024e-04 s | emit 6.61e-07 s | spectra 0 [t=35s]
  digest 8fde0944fa48607e (expected 8fde0944fa48607e: MATCH)
```

### the ledger: live bytes per structure
```

  === ledger.tsv  (168 s sampled, 624 rows)
  peak RSS          31031 MB at t=    9.1 s  phase=start   (charged 13897 MB, unattributed 17134 MB, glibc free 5633 MB)
  peak charged      13897 MB at t=    8.8 s  phase=start   (RSS 29161 MB)

  per structure: peak, when, and how long it is above 5% of the peak RSS
    ms1_map      peak    13830 MB at t=   11.7 (start     )     10508 MB at the RSS peak   above 5% of peak RSS for   24.7 s (14.7%)
    scratch      peak     3842 MB at t=    6.1 (start     )      3388 MB at the RSS peak   above 5% of peak RSS for    6.2 s ( 3.7%)
    slab         peak     3548 MB at t=   86.4 (loop4     )         0 MB at the RSS peak   above 5% of peak RSS for   57.8 s (34.5%)
    prep         peak     1456 MB at t=   88.2 (loop4     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    spectra      peak     1097 MB at t=  112.5 (write4    )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    wstore       peak      887 MB at t=  141.0 (loop5     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    parent       peak      836 MB at t=  140.8 (loop5     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    ms1_trace    peak      533 MB at t=   29.8 (start     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    band_arena   peak      486 MB at t=  134.8 (loop5     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    frag_aux     peak      264 MB at t=  111.7 (loop4     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    carry        peak      168 MB at t=  113.5 (tile5     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    precursor    peak      133 MB at t=   32.7 (start     )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)
    writer       peak       23 MB at t=  167.4 (write6    )         0 MB at the RSS peak   above 5% of peak RSS for    0.0 s ( 0.0%)

  phases
    start           34.8 s   RSS      17 ->    2457 MB  (peak   31031)   top: ms1_map 13830, scratch 3842, ms1_trace 533
    tile1            0.0 s   RSS    3302 ->    3302 MB  (peak    3302)   top: ms1_trace 184, precursor 133, slab 119
    loop1            0.8 s   RSS    4120 ->    4481 MB  (peak    4481)   top: ms1_trace 184, precursor 133, parent 70
    tile2            1.3 s   RSS    5097 ->    9833 MB  (peak    9833)   top: slab 771, scratch 511, ms1_trace 184
    loop2           12.6 s   RSS    9808 ->   12109 MB  (peak   12109)   top: slab 792, spectra 266, prep 259
    write2           0.0 s   RSS   11961 ->   11961 MB  (peak   11961)   top: spectra 266, scratch 196, ms1_trace 184
    tile3            2.1 s   RSS   12514 ->   16217 MB  (peak   16217)   top: slab 2013, scratch 885, ms1_trace 184
    loop3           28.4 s   RSS   15640 ->   16132 MB  (peak   17835)   top: slab 2231, spectra 871, prep 819
    write3           0.5 s   RSS   16142 ->   16145 MB  (peak   16145)   top: spectra 871, scratch 340, ms1_trace 184
    tile4            3.3 s   RSS   16202 ->   20743 MB  (peak   20743)   top: slab 3144, scratch 906, ms1_trace 184
    loop4           25.8 s   RSS   19823 ->   19158 MB  (peak   22072)   top: slab 3548, prep 1456, spectra 1046
    write4           0.8 s   RSS   18766 ->   18760 MB  (peak   18768)   top: spectra 1097, scratch 348, ms1_trace 184
    tile5            3.6 s   RSS   18693 ->   22813 MB  (peak   22813)   top: slab 3208, scratch 624, ms1_trace 184
    loop5           28.9 s   RSS   21971 ->   19622 MB  (peak   23463)   top: slab 3469, prep 1424, wstore 887
    write5           0.5 s   RSS   19627 ->   19627 MB  (peak   19627)   top: spectra 878, scratch 250, ms1_trace 184
    tile6            2.1 s   RSS   19674 ->   21798 MB  (peak   21798)   top: slab 1764, scratch 513, ms1_trace 184
    loop6           15.6 s   RSS   21563 ->   19626 MB  (peak   21589)   top: slab 1832, prep 699, spectra 369
    write6           2.0 s   RSS   19622 ->    2947 MB  (peak   19622)   top: spectra 369, scratch 276, carry 136
    end              0.0 s   RSS    2947 ->    2947 MB  (peak    2947)   top: scratch 276, writer 23

  per tile (read | loop | write), RSS peak and the charged peak
    tile   1: read    0.0s rss<=   3302 charged<=    460 | loop    0.8s rss<=   4481 charged<=    510
    tile   2: read    1.3s rss<=   9833 charged<=   1298 | loop   12.6s rss<=  12109 charged<=   1586 | writ    0.0s rss<=  11961 charged<=    793
    tile   3: read    2.1s rss<=  16217 charged<=   2765 | loop   28.4s rss<=  17835 charged<=   3798 | writ    0.5s rss<=  16145 charged<=   1624
    tile   4: read    3.3s rss<=  20743 charged<=   4276 | loop   25.8s rss<=  22072 charged<=   6016 | writ    0.8s rss<=  18768 charged<=   1912
    tile   5: read    3.6s rss<=  22813 charged<=   4334 | loop   28.9s rss<=  23463 charged<=   6028 | writ    0.5s rss<=  19627 charged<=   1630
    tile   6: read    2.1s rss<=  21798 charged<=   2640 | loop   15.6s rss<=  21589 charged<=   3505 | writ    2.0s rss<=  19622 charged<=    804
INSTR2_RESULT PASS
INSTR2_DONE 08:18
```


## Late addition: what density-balanced cell grouping is actually worth (measured, 2026-09-10)

The brief suggests grouping cells by cumulative peak count instead of by time, since any grouping
reproduces the same output. Measured directly from the acquisition's own frame table
(`Frames.NumPeaks`, 16,105 MS2 frames, 1.545e9 raw MS2 peaks on dataset D), the raw peaks per cell
are:

| pitch | cells | share of the run's peaks, cell by cell |
|---|---:|---|
| 600 s | 3 | 7%, 50%, 43% |
| 300 s | 6 | 1%, 6%, 19%, 30%, 29%, 14% |

and the best adjacent grouping against the equal-time one:

| tiles | equal-time densest tile | balanced densest tile | gain |
|---:|---:|---:|---:|
| 3 (from 6 cells) | 50% of the run | 43% | **13%** |
| 2 (from 6 cells) | 74% | 57% | **23%** |
| 6 (from 6 cells) | 30% | 30% | 0 (one cell each: nothing to group) |

**So the balancing idea is real but small, and the measurement says why: the imbalance is WITHIN
the cells, not between the groups.** At pitch 300 one cell alone carries 30% of the run's peaks,
so no grouping of those cells can put less than 30% in the densest tile. Cutting finer cells would
help the memory but changes the science (it is the cut-line set; pitch 300 vs 600 was measured at
Sage 13,836 vs 13,490 with entrapment 1.38% vs 1.30%).

That leaves the memory question pointing somewhere else: at a fixed cell grid, the only ways below
"one cell's peaks resident" are to shard the WINDOW dimension (re-reading the tile per shard: the
loader decodes each frame once and slices it to every window of its group, so a shard costs a full
re-decode), to spill slabs, or to reduce the bytes per peak. Reviewers should weigh those against
each other rather than assuming the grouping fixes it.
