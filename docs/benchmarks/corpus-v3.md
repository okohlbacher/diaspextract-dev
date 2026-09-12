# Corpus benchmark: diaTracer-2.2.1 vs DIAspeXtractor 1.2.0

Generated 2026-09-12T10:01:06+0200 by `harness/corpus.py table` (plan `corpus_v3`, records from ceph). **n = 1 per cell. No
entrapment in this run** (option for later: Sage with `sage_entrap.json` plus `bench/entrapment.py`, charge strata
mandatory). 49 of 49 rows complete; 29 pairs flagged (load gate before the pair, or contention
during an arm).

- **DIAspeXtractor 1.2.0**: SPX_BIN sha256 `ec6ae270e2331ba5`, lib libOpenMS.so `82aa6e1f8255`, libOpenSwathAlgo.so `228b5fe5c751`, 12 ceph-resident libraries pinned by sha256, git=91a1b28, built=2026-09-11T08:06:34+02:00, openms=3.6.0-pre-exported-20260911.
  Invocation `-in <staged .d> -out pseudo.mzML -threads 100`, defaults only, glibc malloc (SPEXTRACTOR_*, DIASPEXTRACTOR_*, MALLOC_*, OMP_*, GOMP_*, KMP_*, TCMALLOC_*, GLIBC_TUNABLES, JAVA_TOOL_OPTIONS, JDK_JAVA_OPTIONS, LD_PRELOAD, _JAVA_OPTIONS and the
  inherited LD_LIBRARY_PATH unset before the arm's env.sh).
- **diaTracer-2.2.1**: jar sha256 `bfa50ee17cc25755`; `java -Xmx400G -Djna.tmpdir -Djava.io.tmpdir=<jnatmp> -jar ... -t 100
  -mC 0.3 -dI 0.01 -dR 3 -rM 500 -mF 1 -mO 0.1 -r 0`, run from its directory with `LC_ALL=C LD_LIBRARY_PATH=./ext/bruker`. JDK: data 21.0.12, ibminode05 21.0.12, spock 21.0.12. Node-local system libraries that differ between nodes (recorded, not compared): ld-linux-x86-64.so.2, libc.so.6, libdl.so.2, libm.so.6, libpthread.so.0, librt.so.1.
- **Measurement code** (one value across all rows, G-V13): pair `050e2e2aa650`, search `064af71b2bfe`, peptide rule
  `4fe0a1cecefb`.
- **Timing**: per row both extractors ran back to back on the node shown (from the record's hostname), on a node-local
  staged copy, order alternating by queue index. Before each arm, outside its timed window, the node-local filesystem
  was synced and the input pre-warmed with `cat`. Wall and peak RSS from GNU `time -v`; compare walls within a row only.
- **RSS GB = `time -v` "Maximum resident set size (kbytes)" / 1e6.** GNU time's kbytes are KiB, so one unit here is
  1.024e9 bytes; multiply by 0.9537 to compare with the GiB of docs/HELA-TABLE.md and docs/TNBC-TABLE.md.
- **Load flags**: `gate:` the 1-min load before the pair stayed above 24 (>= 200 cores) or 12 for 20 min and the
  pair ran anyway; `during <tool>:` the foreign CPU during that arm (busy CPU minus the runner's own process tree,
  highest 60-s mean) exceeded the same threshold, or MemAvailable fell below 5% of MemTotal. The summary
  counts flagged rows and gives the median wall ratio of unflagged rows separately.
- **Searches**: Sage sha256 `d3820543a31bfa2a` (config `f21a6b26e0f01c3d`, FASTA `29e2a2f54f18e7ea`, native decoys); MSFragger jar
  `56b15a35060e1aa3` (params `fc4789590760dd32`, database `4fa1ea7e234e43bd`). diaTracer mzML is patched with the selected ion m/z
  before Sage; both tools' mzML pass `fix_mzml_cvparams.py` before MSFragger. Every search had to read the output:
  the patch wrote a selected ion into every diaTracer spectrum, MSFragger's `Scans` equal the spectrumList count, and
  Sage searched at least 50% of it (its log gives a lower bound, over spectra with >= min_peaks peaks). Search
  walls are the engine step only, up to 1/2 concurrent searches per node; `†` marks an engine step that
  overlapped another search on the same node. Indicative.
- **Peptides at 1%** (rule of `$SPX/tools/bench_table.py`, which produced docs/TNBC-TABLE.md; hela_table.py behind
  docs/HELA-TABLE.md has the same functions): Sage = unique `peptide` strings with `rank == 1` and
  `peptide_q <= 0.01`, **target+decoy** (decoy rows are not removed, as in the source; with `report_psms 1` the rank
  filter keeps every row). Target-only peptides (label 1, the historical drivers' rule) over complete rows: diaTracer-2.2.1 724,162 of 731,037,
  DIAspeXtractor 1.2.0 824,803 of 833,178. MSFragger = best `hyperscore` per (`peptide`, `modification_info`), sorted descending, deepest prefix
  with decoy/target <= 1%, decoy = every entry of `proteins` split on `,;@` starts with `rev_`. Ratios are ours /
  diaTracer.
- `FAILED G-Vxx` = a guard refused the cell (never a zero); `pending` = no current record; `-` = no pair.

| sample | scheme | acq min | node | load flags | diaTracer-2.2.1 wall | diaTracer-2.2.1 RSS GB (kB/1e6) | DIAspeXtractor 1.2.0 wall | DIAspeXtractor 1.2.0 RSS GB (kB/1e6) | spectra diaTracer-2.2.1 | spectra DIAspeXtractor 1.2.0 | Sage diaTracer-2.2.1 | Sage DIAspeXtractor 1.2.0 | Sage ratio | MSFragger diaTracer-2.2.1 | MSFragger DIAspeXtractor 1.2.0 | MSFragger ratio | Sage wall diaTracer-2.2.1 / DIAspeXtractor 1.2.0 | MSFragger wall diaTracer-2.2.1 / DIAspeXtractor 1.2.0 |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | in-house | 31.0 | ibminode05 | gate: load 41.7 > 12; during diaTracer-2.2.1: foreign CPU 45.0 cores > 12; during DIAspeXtractor 1.2.0: foreign CPU 47.7 cores > 12 | 12:04 | 160.1 | 7:11 | 32.2 | 872,430 | 725,591 | 10,329 | 11,851 | 1.15 | 13,666 | 12,070 | 0.88 | 2:04 / 1:24 | 6:25 / 5:19 |
| B | in-house | 31.0 | ibminode05 | gate: load 41.1 > 12; during DIAspeXtractor 1.2.0: foreign CPU 43.6 cores > 12; during diaTracer-2.2.1: foreign CPU 45.7 cores > 12 | 10:13 | 166.5 | 4:08 | 23.3 | 717,924 | 445,412 | 9,038 | 10,711 | 1.19 | 10,606 | 10,214 | 0.96 | 1:53 / 0:52 | 5:28 / 3:17 |
| C | in-house | 31.0 | ibminode05 | gate: load 39.7 > 12; during diaTracer-2.2.1: foreign CPU 44.1 cores > 12; during DIAspeXtractor 1.2.0: foreign CPU 42.0 cores > 12 | 10:39 | 162.8 | 4:45 | 26.2 | 780,767 | 574,373 | 11,510 | 12,820 | 1.11 | 14,289 | 12,673 | 0.89 | 2:03 / 1:12 | 5:49 / 4:20 |
| D | in-house | 31.0 | spock | during diaTracer-2.2.1: foreign CPU 31.4 cores > 24 | 6:57 | 179.4 | 2:44 | 22.1 | 700,434 | 496,722 | 11,626 | 12,918 | 1.11 | 13,932 | 12,402 | 0.89 | 1:42† / 1:24† | 4:20† / 3:16† |
| E | in-house | 31.0 | ibminode05 | gate: load 42.7 > 12; during DIAspeXtractor 1.2.0: foreign CPU 42.8 cores > 12; during diaTracer-2.2.1: foreign CPU 42.9 cores > 12 | 7:50 | 141.8 | 2:43 | 17.7 | 593,601 | 390,478 | 10,109 | 11,826 | 1.17 | 11,879 | 10,889 | 0.92 | 1:34 / 0:50 | 4:11 / 3:03 |
| F | in-house | 31.0 | ibminode05 | gate: load 53.6 > 12; during diaTracer-2.2.1: foreign CPU 50.6 cores > 12; during DIAspeXtractor 1.2.0: foreign CPU 45.4 cores > 12 | 8:44 | 158.4 | 3:11 | 20.0 | 649,903 | 442,936 | 10,195 | 11,652 | 1.14 | 12,738 | 11,216 | 0.88 | 1:44 / 0:51 | 4:38 / 3:21 |
| HeLa_31 | HeLa 25pc 100ng | 120.0 | spock | during diaTracer-2.2.1: foreign CPU 37.5 cores > 24 | 5:17 | 165.5 | 5:35 | 11.9 | 425,061 | 753,360 | 13,724 | 16,780 | 1.22 | 15,871 | 13,257 | 0.84 | 1:16† / 1:30† | 2:55† / 4:06† |
| HeLa_32 | HeLa 25pc 100ng | 120.0 | spock | during diaTracer-2.2.1: foreign CPU 29.9 cores > 24; during DIAspeXtractor 1.2.0: foreign CPU 27.5 cores > 24 | 4:57 | 193.8 | 5:21 | 11.1 | 382,348 | 693,625 | 13,186 | 16,077 | 1.22 | 15,526 | 13,131 | 0.85 | 1:08† / 1:27† | 2:38† / 3:39† |
| HeLa_33 | HeLa 25pc 100ng | 120.0 | spock | during DIAspeXtractor 1.2.0: foreign CPU 29.4 cores > 24; during diaTracer-2.2.1: foreign CPU 33.5 cores > 24 | 5:00 | 206.0 | 5:31 | 11.5 | 392,553 | 696,971 | 13,414 | 16,265 | 1.21 | 14,966 | 12,843 | 0.86 | 1:11† / 1:21† | 2:49† / 3:30† |
| HeLa_19 | HeLa 25pc 10ng | 120.0 | spock | - | 1:39 | 92.7 | 2:21 | 6.7 | 46,964 | 84,088 | 5,993 | 5,115 | 0.85 | 6,363 | 3,019 | 0.47 | 0:28† / 0:20† | 0:36† / 0:41† |
| HeLa_20 | HeLa 25pc 10ng | 120.0 | spock | during diaTracer-2.2.1: foreign CPU 27.6 cores > 24 | 1:42 | 121.0 | 2:23 | 6.5 | 44,754 | 81,596 | 6,109 | 4,821 | 0.79 | 6,041 | 2,852 | 0.47 | 0:26† / 0:21† | 0:35† / 0:36† |
| HeLa_21 | HeLa 25pc 10ng | 120.0 | spock | during diaTracer-2.2.1: foreign CPU 28.6 cores > 24 | 1:43 | 100.6 | 2:20 | 6.5 | 41,669 | 75,854 | 5,143 | 4,401 | 0.86 | 6,218 | 2,638 | 0.42 | 0:24† / 0:20† | 0:34† / 0:36† |
| HeLa_25 | HeLa 25pc 50ng | 120.0 | data | gate: load 44.6 > 24; during diaTracer-2.2.1: foreign CPU 45.5 cores > 24; during DIAspeXtractor 1.2.0: foreign CPU 52.5 cores > 24 | 3:44 | 125.9 | 4:09 | 9.2 | 247,133 | 472,112 | 11,331 | 12,861 | 1.14 | 12,661 | 9,800 | 0.77 | 1:17† / 0:58† | 1:56 / 2:28† |
| HeLa_26 | HeLa 25pc 50ng | 120.0 | data | gate: load 41.6 > 24; during DIAspeXtractor 1.2.0: foreign CPU 48.1 cores > 24; during diaTracer-2.2.1: foreign CPU 51.9 cores > 24 | 3:38 | 172.7 | 4:00 | 8.7 | 219,615 | 420,947 | 11,118 | 12,230 | 1.10 | 12,164 | 9,530 | 0.78 | 0:47† / 0:56† | 1:36† / 2:07† |
| HeLa_27 | HeLa 25pc 50ng | 120.0 | data | - | 3:16 | 126.5 | 3:50 | 8.6 | 227,198 | 432,865 | 10,790 | 12,202 | 1.13 | 12,027 | 9,433 | 0.78 | 0:54† / 0:56† | 1:32† / 2:04† |
| HeLa_34 | HeLa py3 100ng | 120.0 | ibminode05 | gate: load 58.1 > 12; during DIAspeXtractor 1.2.0: foreign CPU 45.5 cores > 12; during diaTracer-2.2.1: foreign CPU 47.5 cores > 12 | 6:01 | 148.1 | 2:13 | 8.0 | 609,204 | 866,609 | 20,302 | 22,751 | 1.12 | 29,921 | 17,967 | 0.60 | 1:25 / 1:02 | 4:31 / 3:55 |
| HeLa_35 | HeLa py3 100ng | 120.0 | ibminode05 | gate: load 40.7 > 12; during diaTracer-2.2.1: foreign CPU 45.6 cores > 12 | 5:50 | 121.7 | 1:37 | 8.2 | 610,021 | 874,265 | 28,359 | 23,026 | 0.81 | 30,000 | 17,646 | 0.59 | 1:31 / 1:03 | 4:25 / 3:54 |
| HeLa_36 | HeLa py3 100ng | 120.0 | ibminode05 | - | 4:59 | 122.1 | 1:37 | 8.1 | 618,967 | 870,853 | 20,520 | 23,112 | 1.13 | 30,137 | 17,650 | 0.59 | 1:29 / 1:01 | 4:40 / 4:17 |
| HeLa_22 | HeLa py3 10ng | 120.0 | ibminode05 | - | 1:43 | 134.3 | 0:29 | 4.5 | 62,784 | 61,342 | 9,186 | 4,423 | 0.48 | 8,116 | 2,850 | 0.35 | 0:16 / 0:10 | 0:43 / 0:31 |
| HeLa_23 | HeLa py3 10ng | 120.0 | ibminode05 | - | 1:43 | 116.1 | 0:29 | 4.1 | 63,771 | 61,613 | 9,182 | 4,314 | 0.47 | 8,256 | 2,801 | 0.34 | 0:16 / 0:11 | 0:42 / 0:37 |
| HeLa_24 | HeLa py3 10ng | 120.0 | ibminode05 | - | 1:42 | 127.6 | 0:29 | 5.0 | 62,709 | 62,231 | 9,175 | 4,308 | 0.47 | 7,577 | 2,857 | 0.38 | 0:16 / 0:11 | 0:45 / 0:40 |
| HeLa_28 | HeLa py3 50ng | 120.0 | ibminode05 | - | 3:24 | 208.7 | 1:01 | 7.0 | 377,131 | 522,521 | 17,050 | 17,793 | 1.04 | 23,707 | 12,777 | 0.54 | 0:58 / 0:35 | 2:51 / 2:19 |
| HeLa_29 | HeLa py3 50ng | 120.0 | ibminode05 | - | 3:10 | 103.5 | 1:00 | 6.7 | 354,268 | 488,231 | 22,777 | 16,816 | 0.74 | 23,631 | 11,866 | 0.50 | 0:56 / 0:34 | 2:36 / 2:30 |
| HeLa_30 | HeLa py3 50ng | 120.0 | ibminode05 | - | 3:09 | 185.8 | 0:58 | 6.7 | 361,772 | 498,911 | 22,554 | 16,701 | 0.74 | 23,479 | 12,047 | 0.51 | 0:57 / 0:34 | 2:49 / 2:20 |
| HeLa_2450 | HeLa Evosep 60SPD | 21.0 | spock | during diaTracer-2.2.1: foreign CPU 24.4 cores > 24 | 1:37 | 81.3 | 0:32 | 9.0 | 250,633 | 261,418 | 22,974 | 21,390 | 0.93 | 25,420 | 19,947 | 0.78 | 1:12† / 1:07† | 1:47† / 1:44† |
| HeLa_2451 | HeLa Evosep 60SPD | 21.0 | spock | during DIAspeXtractor 1.2.0: foreign CPU 34.8 cores > 24 | 1:35 | 99.8 | 0:32 | 8.9 | 247,874 | 255,571 | 22,741 | 20,903 | 0.92 | 24,402 | 19,467 | 0.80 | 1:16† / 1:19† | 1:50† / 1:50† |
| HeLa_2452 | HeLa Evosep 60SPD | 21.0 | spock | during diaTracer-2.2.1: foreign CPU 25.8 cores > 24 | 1:44 | 85.2 | 0:32 | 9.1 | 252,496 | 262,426 | 15,836 | 21,234 | 1.34 | 25,212 | 20,062 | 0.80 | 1:02† / 1:05† | 1:51† / 1:46† |
| HeLa_2731 | HeLa Evosep 100SPD | 11.5 | spock | - | 1:15 | 58.8 | 0:19 | 7.6 | 180,949 | 131,364 | 15,938 | 12,647 | 0.79 | 17,666 | 11,569 | 0.65 | 0:43† / 0:32† | 1:19† / 1:04† |
| HeLa_2732 | HeLa Evosep 100SPD | 11.5 | spock | - | 1:11 | 46.0 | 0:18 | 7.3 | 170,297 | 124,148 | 10,394 | 12,298 | 1.18 | 16,723 | 11,410 | 0.68 | 0:36† / 0:34† | 1:18† / 1:02† |
| HeLa_2735 | HeLa Evosep 100SPD | 11.5 | spock | - | 1:20 | 63.8 | 0:17 | 7.3 | 169,021 | 123,232 | 15,140 | 12,316 | 0.81 | 16,754 | 11,319 | 0.68 | 0:52† / 0:49† | 1:13† / 1:03† |
| HeLa_2737 | HeLa Evosep 200SPD | 5.6 | spock | - | 1:02 | 48.9 | 0:16 | 5.7 | 118,427 | 80,203 | 7,194 | 6,594 | 0.92 | 8,834 | 6,181 | 0.70 | 0:46† / 0:36† | 1:01† / 0:51† |
| HeLa_2738 | HeLa Evosep 200SPD | 5.6 | spock | - | 1:01 | 43.7 | 0:16 | 5.8 | 124,304 | 79,961 | 4,928 | 6,601 | 1.34 | 9,028 | 5,940 | 0.66 | 0:41† / 0:34† | 1:07† / 0:48† |
| HeLa_2740 | HeLa Evosep 200SPD | 5.6 | spock | during DIAspeXtractor 1.2.0: foreign CPU 43.8 cores > 24 | 0:59 | 37.2 | 0:15 | 5.5 | 117,388 | 75,026 | 7,391 | 6,652 | 0.90 | 9,032 | 6,066 | 0.67 | 0:35† / 0:25† | 1:04† / 0:46† |
| TNBC_001 | TNBC | 130.0 | spock | - | 17:22 | 361.4 | 7:18 | 19.3 | 2,303,274 | 2,577,532 | 14,764 | 19,808 | 1.34 | 19,516 | 19,079 | 0.98 | 4:59 / 5:20† | 13:00 / 13:45† |
| TNBC_002 | TNBC | 130.0 | data | gate: load 75.5 > 24; during diaTracer-2.2.1: foreign CPU 122.4 cores > 24; during DIAspeXtractor 1.2.0: foreign CPU 67.5 cores > 24 | 23:58 | 368.8 | 9:56 | 21.2 | 2,813,130 | 3,057,516 | 21,588 | 28,646 | 1.33 | 26,947 | 26,643 | 0.99 | 6:15 / 7:49† | 16:31 / 16:24† |
| TNBC_003 | TNBC | 130.0 | spock | - | 22:35 | 358.5 | 9:34 | 22.3 | 2,929,877 | 3,107,165 | 20,417 | 27,072 | 1.33 | 25,983 | 25,331 | 0.97 | 7:02† / 6:01† | 17:28† / 16:53† |
| TNBC_005 | TNBC | 130.0 | data | gate: load 99.0 > 24; during DIAspeXtractor 1.2.0: foreign CPU 60.6 cores > 24; during diaTracer-2.2.1: foreign CPU 113.2 cores > 24 | 22:42 | 373.9 | 8:35 | 20.4 | 2,670,021 | 2,924,707 | 26,057 | 34,340 | 1.32 | 32,492 | 32,387 | 1.00 | 6:39† / 6:38† | 16:06† / 15:22† |
| TNBC_006 | TNBC | 130.0 | spock | during diaTracer-2.2.1: foreign CPU 33.6 cores > 24 | 23:27 | 375.0 | 9:42 | 22.5 | 3,086,644 | 3,219,289 | 18,916 | 27,479 | 1.45 | 25,046 | 26,343 | 1.05 | 7:07† / 6:19† | 17:39† / 17:48† |
| TNBC_007 | TNBC | 130.0 | data | gate: load 112.0 > 24; during diaTracer-2.2.1: foreign CPU 121.4 cores > 24; during DIAspeXtractor 1.2.0: foreign CPU 121.4 cores > 24 | 26:00 | 284.9 | 10:35 | 22.1 | 2,954,733 | 3,088,381 | 19,801 | 25,873 | 1.31 | 25,745 | 24,479 | 0.95 | 7:00† / 7:03† | 16:44† / 16:17† |
| TNBC_008 | TNBC | 130.0 | spock | - | 24:32 | 396.8 | 9:49 | 22.3 | 3,022,795 | 3,083,625 | 17,887 | 24,925 | 1.39 | 22,948 | 23,814 | 1.04 | 6:50† / 6:43† | 17:08† / 16:28† |
| TNBC_009 | TNBC | 130.0 | data | gate: load 68.9 > 24; during DIAspeXtractor 1.2.0: foreign CPU 115.1 cores > 24; during diaTracer-2.2.1: foreign CPU 140.2 cores > 24 | 24:15 | 314.5 | 9:53 | 21.1 | 2,788,798 | 3,010,923 | 18,920 | 29,510 | 1.56 | 28,390 | 27,806 | 0.98 | 6:42† / 6:41† | 15:59† / 16:35† |
| TNBC_010 | TNBC | 130.0 | spock | - | 18:23 | 356.2 | 7:31 | 19.8 | 2,525,130 | 2,708,911 | 16,465 | 25,821 | 1.57 | 25,100 | 24,656 | 0.98 | 5:37† / 4:54† | 14:00† / 14:35† |
| TNBC_011 | TNBC | 130.0 | data | gate: load 76.7 > 24; during diaTracer-2.2.1: foreign CPU 100.4 cores > 24; during DIAspeXtractor 1.2.0: foreign CPU 54.5 cores > 24 | 22:55 | 332.8 | 9:32 | 21.1 | 2,669,029 | 2,766,623 | 14,195 | 20,538 | 1.45 | 20,066 | 19,277 | 0.96 | 6:13† / 6:22† | 16:42† / 15:17† |
| TNBC_012 | TNBC | 130.0 | spock | - | 21:12 | 383.5 | 8:34 | 21.1 | 2,773,761 | 2,935,686 | 17,891 | 27,268 | 1.52 | 27,309 | 26,747 | 0.98 | 6:05† / 6:04† | 16:07† / 15:57† |
| TNBC_013 | TNBC | 130.0 | data | gate: load 82.8 > 24; during DIAspeXtractor 1.2.0: foreign CPU 112.5 cores > 24; during diaTracer-2.2.1: foreign CPU 92.4 cores > 24 | 19:17 | 338.9 | 7:37 | 19.2 | 2,257,594 | 2,465,175 | 14,826 | 18,949 | 1.28 | 19,533 | 17,383 | 0.89 | 5:11† / 5:45† | 13:51† / 13:02† |
| TNBC_014 | TNBC | 130.0 | spock | - | 19:28 | 307.9 | 7:33 | 19.8 | 2,632,299 | 2,889,797 | 25,425 | 32,957 | 1.30 | 31,933 | 31,371 | 0.98 | 6:08† / 5:43† | 14:46† / 15:35† |
| TNBC_015 | TNBC | 130.0 | data | gate: load 142.6 > 24; during diaTracer-2.2.1: foreign CPU 122.4 cores > 24; during DIAspeXtractor 1.2.0: foreign CPU 111.3 cores > 24 | 22:38 | 373.7 | 8:25 | 20.1 | 2,600,681 | 2,608,439 | 17,563 | 22,307 | 1.27 | 22,431 | 21,267 | 0.95 | 5:59† / 5:30† | 14:58† / 13:42† |
| TNBC_017 | TNBC | 130.0 | spock | during diaTracer-2.2.1: foreign CPU 27.5 cores > 24 | 21:47 | 371.7 | 8:11 | 20.4 | 2,702,215 | 2,784,175 | 17,174 | 22,788 | 1.33 | 21,809 | 21,252 | 0.97 | 6:06† / 5:06† | 15:17† / 14:34† |
| TNBC_018 | TNBC | 130.0 | data | gate: load 39.1 > 24; during DIAspeXtractor 1.2.0: foreign CPU 64.9 cores > 24; during diaTracer-2.2.1: foreign CPU 144.3 cores > 24 | 21:10 | 373.2 | 8:10 | 20.3 | 2,455,193 | 2,697,156 | 13,892 | 18,488 | 1.33 | 17,649 | 16,183 | 0.92 | 5:49† / 5:08† | 13:26† / 14:21† |

## Per scheme and corpus (complete rows only)

| scheme | n | flagged | diaTracer-2.2.1 wall total | DIAspeXtractor 1.2.0 wall total | median wall ratio (ours/dT) | median wall ratio, unflagged rows | diaTracer-2.2.1 median RSS GB | DIAspeXtractor 1.2.0 median RSS GB | Sage diaTracer-2.2.1 total | Sage DIAspeXtractor 1.2.0 total | Sage ratio of totals | Sage median ratio | MSFragger diaTracer-2.2.1 total | MSFragger DIAspeXtractor 1.2.0 total | MSFragger ratio of totals | MSFragger median ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| in-house | 6 | 6/6 | 56:26 | 24:43 | 0.40 | - | 161.4 | 22.7 | 62,807 | 71,778 | 1.14 | 1.15 | 77,110 | 69,464 | 0.90 | 0.89 |
| HeLa 25pc 100ng | 3 | 3/3 | 15:14 | 16:27 | 1.08 | - | 193.8 | 11.5 | 40,324 | 49,122 | 1.22 | 1.22 | 46,363 | 39,231 | 0.85 | 0.85 |
| HeLa 25pc 10ng | 3 | 2/3 | 5:04 | 7:04 | 1.41 | 1.42 | 100.6 | 6.5 | 17,245 | 14,337 | 0.83 | 0.85 | 18,622 | 8,509 | 0.46 | 0.47 |
| HeLa 25pc 50ng | 3 | 2/3 | 10:38 | 12:00 | 1.11 | 1.18 | 126.5 | 8.7 | 33,239 | 37,293 | 1.12 | 1.13 | 36,852 | 28,763 | 0.78 | 0.78 |
| HeLa py3 100ng | 3 | 2/3 | 16:50 | 5:27 | 0.32 | 0.32 | 122.1 | 8.1 | 69,181 | 68,889 | 1.00 | 1.12 | 90,058 | 53,263 | 0.59 | 0.59 |
| HeLa py3 10ng | 3 | 0/3 | 5:07 | 1:27 | 0.28 | 0.28 | 127.6 | 4.5 | 27,543 | 13,045 | 0.47 | 0.47 | 23,949 | 8,508 | 0.36 | 0.35 |
| HeLa py3 50ng | 3 | 0/3 | 9:43 | 2:59 | 0.31 | 0.31 | 185.8 | 6.7 | 62,381 | 51,310 | 0.82 | 0.74 | 70,817 | 36,690 | 0.52 | 0.51 |
| HeLa Evosep 60SPD | 3 | 3/3 | 4:56 | 1:37 | 0.33 | - | 85.2 | 9.0 | 61,551 | 63,527 | 1.03 | 0.93 | 75,034 | 59,476 | 0.79 | 0.80 |
| HeLa Evosep 100SPD | 3 | 0/3 | 3:46 | 0:54 | 0.25 | 0.25 | 58.8 | 7.3 | 41,472 | 37,261 | 0.90 | 0.81 | 51,143 | 34,298 | 0.67 | 0.68 |
| HeLa Evosep 200SPD | 3 | 1/3 | 3:02 | 0:46 | 0.25 | 0.26 | 43.7 | 5.7 | 19,513 | 19,847 | 1.02 | 0.92 | 26,894 | 18,187 | 0.68 | 0.67 |
| TNBC | 16 | 10/16 | 5:51:40 | 2:20:55 | 0.41 | 0.41 | 365.1 | 20.8 | 295,781 | 406,769 | 1.38 | 1.33 | 392,897 | 384,018 | 0.98 | 0.98 |
| **corpus** | 49 | 29/49 | 8:02:27 | 3:34:19 | 0.39 | 0.31 | 162.8 | 11.1 | 731,037 | 833,178 | 1.14 | 1.15 | 909,739 | 740,407 | 0.81 | 0.84 |
