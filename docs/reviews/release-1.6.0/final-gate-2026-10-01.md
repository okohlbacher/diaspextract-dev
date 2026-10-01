# DIAspeXtract 1.6.0 release gate: final binary v1.6.0rc3 (release-1.6.0 81a0c32), 2026-10-01

All times are CEST on the cluster (the laptop clock was UTC+8, so local commit dates read 2026-10-02). Everything ran
on ibminode05, one extraction at a time. No push, tag, export or GitHub release happened in this step.

**Verdict.** The final arm is **v1.6.0rc3**: binary `98d1780af471897eeb4bb59918a67f896266a517478f19de9869b35014b1207a`,
git 81a0c32 (src 338983d0 = f661c11's file). Its defaults reproduce rc2's digests on all five public pins, so the 43-run
corpus measured on the rc2 binary (`corpus_v3_rc160_public`, arm `tune-v1.6.0rc2`) carries over and does not need a
re-run. Dataset D gate 21/21 PASS. Harness smoke QUEUE_DONE failed 0, guardtest 39/39.

| step | where, when | result |
|---|---|---|
| why a new build | | The rc2 review committed f661c11 after e53b357 (`src/diaspextract.cpp` 5616dd70 -> 338983d0, `test/test_diaspextract.py` b63d1a08 -> 4554a76c). 81a0c32 adds only the review records. The calibration header (cb155f66) and the tool headers (9f805fc1) are unchanged. |
| `make -n diaspextract` pre-check | before the sync | Byte-identical to rc2's pre-check log (9,706 bytes, `rel160/rc2/make_n_pre.log`). Nothing in the tree was out of date, and no build or extraction was running. |
| `scripts/sync_cluster.sh ibminode05` | worktree `tune-wt/release-1.6.0` at 81a0c32, clean; built 18:24:25 | DEPLOY COMMITTED. Both unit tests (dnoise, tdf_load) passed. Binary **98d1780a**. libOpenMS.so is still **1b9d8be5** (on disk and in the provenance). No reconfigure. Of the shipped tools only `test_diaspextract.py` changed (-> 4554a76c); the other six are byte-identical, so the corpus queues on the other five nodes saw no tool change. |
| `verify_publish_dia13.sh v1.6.0rc3 1.6.0 81a0c32 98d1780a...` (REPO_E2E = `test/test_diaspextract.py` at 81a0c32, 4554a76c, cmp-identical to the deployed suite) | 18:25:22 | **VERIFY_DONE**. e2e **30/30**. Guards G1-G5 PASS. Library gate: 5 DIASPEXTRACT_ strings, 0 old names. `--help` and ini report 1.6.0. Published `/ceph/ibmi/abi/oliver/spextract/v1.6.0rc3`; the binary, libOpenMS and ldd were checked from the arm. |
| carry-over chain `idchain_rc3.sh` | 18:26:36-18:45:45 | **CARRY_DONE fails 0**, 11 rows + 2 header checks. See below. |
| dataset D gate `gate_D_160rc2.sh` | 18:45:50-19:40:49 | **21/21 PASS**: 8 reset rows, 2 header comparisons with the v1.5.0 arm, 7 rows at the defaults, 3 refusal rows, mzPeak. Started by a node-side waiter only after CARRY_DONE fails 0. |
| harness smoke `corpus_v3_selftest_v160final` | 19:41:59-19:46:30 | PREFLIGHT_OK, LAUNCH_OK, **QUEUE_DONE failed 0 mzml_left 0**, lock free, 33 files collected to ceph, table 1 of 1 rows complete, 0 flagged. |
| harness guardtest | 19:47:05-19:53:09 | **GUARDTEST_DONE pass 39 fail 0**. `guardtest --show`: 39/39 cases pass, lock free, exit 0. |

## Carry-over (published arm v1.6.0rc3, 100 threads)

Driver: `/ceph/ibmi/abi/oliver/spextract/tune-2026-09-29/rel160rc3/tools/idchain_rc3.sh` (sha256 643d7528), the shape of
rel160rc2's `rc2fix_gate.sh` through `rel160/tools/tunerun_panel.sh` (per-node heavy lock, semantic digest, mzML deleted
after its stamps). Log and TSV: `rel160rc3/carry_ibminode05.{log,tsv}`. The pins are the rel160-comb-2 digests, which
the v1.6.0rc2 arm reproduced on HeLa_22 and K562 (`rel160rc2/id_ibminode05.log`).

| row | arm | sample | want | result | spectra | wall | peak RSS GB |
|---|---|---|---|---|---:|---:|---:|
| def_HeLa_22 | rc3 | HeLa_22 | 3e71fa24 | PASS | 52,123 | 0:22 | 5.2 |
| rc2_HeLa_22 | v1.6.0rc2 | HeLa_22 | 3e71fa24 | PASS | 52,123 | 0:22 | 5.2 |
| HDRDEF | | | rc3 stamps == rc2 stamps | PASS (29 spx: stamps, name and value) | | | |
| def_HeLa_19 | rc3 | HeLa_19 | d2d5923f | PASS | 85,999 | 1:23 | 7.1 |
| def_HeLa_2737 | rc3 | HeLa_2737 | 1a70447b | PASS | 90,246 | 0:17 | 5.8 |
| def_K562 | rc3 | MP_K562_N_9905 | faac3d99 | PASS | 1,033,462 | 3:32 | 31.1 |
| def_TNBC_009 | rc3 | TNBC_009 | a9e8c416 | PASS | 2,661,776 | 6:58 | 29.5 |
| reset_HeLa_22 | rc3, CHANGELOG six-option reset | HeLa_22 | 2b01bef4 (1.5.0) | PASS | 53,715 | 0:22 | 5.3 |
| v150_HeLa_22 | v1.5.0 | HeLa_22 | 2b01bef4 | PASS | 53,715 | 0:29 | 4.5 |
| HDRRESET | | | reset stamps == v1.5.0 stamps | PASS (24 spx: stamps, name and value) | | | |
| reset_K562 | rc3, six-option reset | MP_K562_N_9905 | 5b383304 (1.5.0) | PASS | 1,022,349 | 3:11 | 29.9 |

The review fixes are output-neutral at the defaults on every pin. Under the documented reset, the header now equals
1.5.0's (on rc2 it differed in `spx:twin_merge`; the finding fixed in f661c11).

## Dataset D gate

**Driver.** `ibminode05:/scratch/kohlbach/gate_D_160rc2.sh` (sha256 0a1b474d; copy in `/scratch/kohlbach/rel160/rc3/`)
was derived from `gate_D_160rc1b.sh` by asserted replacements (`rel160/rc3/derive_160rc2.py`, sha256 a00715da). The
derivation asserts the row list, the four NOT_ERR uses, the output dir and the RESET lines.

- `$RESET6` is the CHANGELOG's reset sentence verbatim: `-assembly:im_weight_sigma 0 -assembly:foreign_precursor_weight 1
  -assembly:fragment_fuse_ppm 0 -charge:mono_profile_check false -charge:iso_im_tolerance 0.05 -trace:min_length_sec 3`.
- `$RESET` is `$RESET6 -assembly:twin_rt_frames -1`, so every 1.6.0 default is at its 1.5.0 value. It is part of
  `$GATE_OFF` and of the R2c and R7o rows.
- All 16 rows of the rc1 run 1 are back (the rc1b driver ran only the default rows). New rows:
  - R2e: `$RESET6` alone, must give 50b38ed9;
  - R2v: the published v1.5.0 arm (687d724b, identity checked against its provenance) at its defaults;
  - HDR_R2d / HDR_R2e: every `spx:` header stamp, name and value, of R2d and R2e must equal R2v's;
  - R3d: `DIASPEXTRACT_PIPE_TILES=1` (the per-tile barrier instead of pipelined tiles) must equal R3.
- The default rows carry no pin: R3 and R7b set the 1.6.0 pins on D. `WANT_KEYS` is 29 at the defaults (rc1's 27 plus
  `spx:iso_im_tolerance` and `spx:ms1_min_length`) and 24 on the reset rows and R2v.
- The NOT_ERR exclusion of the `[foreign]` statistics line is kept. No other line counted as an error on any row.
- Each row also logs the per-run settings D measured (`[isotol]`, `[minlen]`, `[twins] twin_rt_frames`) and the `[pipe]` mode.
- Gate log: `ibminode05:/scratch/kohlbach/rel160/rc3/gate_D_160rc2_v1.6.0rc3.log`. Row logs and headers are in
  `/scratch/kohlbach/v1.6.0rc3_gate_D` (0700).

**Patient data.** Only `analysis.tdf` and `analysis.tdf_bin` were staged (6,257,684,480 bytes, cmp/size-checked), into
a 0700 directory inside the 0700 gate directory. The stage was removed before DRIVER_DONE ("stage dir removed: yes").
Afterwards no mzML, mzPeak, tdf or .d remains under the gate directory (1.4 MB of logs and headers), and nothing left
the cluster.

| row | arguments | want | digest | spectra | wall | peak RSS GB | verdict |
|---|---|---|---|---:|---:|---:|---|
| R1 | dnoise off, fold off, `$GATE_OFF` | 8c1b047f | 8c1b047f | 611,850 | 2:41 | 31.0 | PASS |
| R2 | fold off, `$GATE_OFF`; header, 24 stamps | e43672a0 | e43672a0 | 496,722 | 2:15 | 28.5 | PASS |
| R2b | `$GATE_OFF` (the 1.4.x defaults) | 9e2b075f | 9e2b075f | 394,523 | 2:12 | 28.0 | PASS |
| R2c | merges off, `$RESET` (the rc5 candidate) | 6498e613 | 6498e613 | 405,941 | 2:22 | 29.0 | PASS |
| **R2d** | **`$RESET` = the 1.5.0 defaults; header, 24 stamps** | 50b38ed9 | **50b38ed9** | 405,931 | 2:14 | 27.9 | **PASS** |
| **R2e** | **`$RESET6`, the CHANGELOG sentence; header, 24 stamps** | 50b38ed9 | **50b38ed9** | 405,931 | 2:13 | 27.2 | **PASS** |
| R2v | the v1.5.0 arm at its defaults; header, 24 stamps | 50b38ed9 | 50b38ed9 | 405,931 | 2:59 | 21.5 | PASS |
| HDR_R2d | R2d's spx: stamps == R2v's | | 24/24 identical | | | | PASS |
| HDR_R2e | R2e's spx: stamps == R2v's | | 24/24 identical | | | | PASS |
| R7o | `-gate:adaptive auto $RESET` | 8affc3ae | 8affc3ae | 394,514 | 2:11 | 27.5 | PASS |
| **R3** | **the 1.6.0 defaults; header, 29 stamps** | (sets the pin) | **3b2ea767** | **489,435** | 2:27 | 26.8 | **PASS** |
| R3a | one tile | == R3 | 3b2ea767 | 489,435 | 2:55 | 37.1 | PASS |
| R3b | two cells per tile | == R3 | 3b2ea767 | 489,435 | 2:35 | 35.0 | PASS |
| R3c | 8 threads | == R3 | 3b2ea767 | 489,435 | 13:45 | 19.3 | PASS |
| R3d | `DIASPEXTRACT_PIPE_TILES=1` (`[pipe] off: a barrier after every tile`) | == R3 | 3b2ea767 | 489,435 | 3:00 | 22.1 | PASS |
| R7b | 1.6.0 defaults, explicit plain gate | (sets the pin) | 23ad7444 | 433,157 | 2:18 | 28.7 | PASS |
| R7 | 1.6.0 defaults, `-gate:adaptive auto` | == R7b | 23ad7444 | 433,157 | 2:15 | 27.5 | PASS |
| R4 / R5 / R5b | old-prefix environment (SPEXTRACTOR_, DIASPEXTRACTOR_, both) | refused | exit 6 after 24 ms, nothing written, every variable named | | | | PASS |
| R6 | `-out out.mzpeak` | one-tile warning, output | exit 0, warning 1, 2,932,323,965 bytes, 489,435 spectra | | 3:28 | 38.8 | PASS |

R2d and R2e differ by one byte in the mzML: the header's parameter list records `assembly:twin_rt_frames` -1 or 0. Their
`spx:` stamps are identical, so the CHANGELOG sentence alone gives the 1.5.0 spectra and header on D.

**1.6.0 pins on dataset D** (they replace rc1's 3bc037d1 / a2adbd99, which predate the three per-run defaults):

| pin | digest | value |
|---|---|---|
| defaults | `3b2ea7670a09bef6` | 489,435 spectra, 29 spx: stamps; one tile, two cells per tile, 8 threads and serial tiles all agree |
| plain gate at the defaults (R7b == R7 auto) | `23ad7444a1605b71` | 433,157 spectra |

**What D measured.**
- `[isotol]`: 1/K0 tolerance 0.010 (t* 0.009, clamped).
- `[minlen]`: median MS1 FWHM 2.59 s = 1.87 cycles at a 1.383-s cycle, giving `trace:min_length_sec` 1.04 s (at least 2 MS1 points).
- `[twins]`: `twin_rt_frames` 2 (median FWHM 2.00 cycles). 11,497 same-monoisotope pairs at nearby frames were joined
  and 0 were left apart at a cell edge; 208 clusters are chained beyond the tolerance (the known limitation in the CHANGELOG).

The 1.6.0 defaults write 20.6 % more spectra than 1.5.0 on D (489,435 against 405,931; rc1 without the per-run settings
wrote 381,540). There is no search on D, so this says nothing about peptides.

**Speed and memory against rc1 (informational, one run each).** Every 100-thread row is faster: R2d 2:14 against 3:02,
and R3 2:27 against 3:02, with 28 % more spectra. Peak RSS is higher at 100 threads: R2d 27.9 GB against 21.6 GB, and
R3 26.8 against 21.4. This is the pipelined tiles: R3d with the per-tile barrier takes 3:00 and 22.1 GB. One tile is
unchanged (R3a 37.1 against 37.2). At 8 threads R3c takes 13:45 (rc1 11:26) for the 28 % more spectra.

## Harness smoke and guardtest

**Plan.** `corpus_v3_selftest_v160final` is a clone of `corpus_v3_selftest_v160rc1`, made by asserted replacements
(checked with the harness's `load_plan`: only arm, scratch_root, results_ceph, report and queues differ). It uses arm
`v1.6.0rc3`, queue ibminode05, scratch `/scratch/kohlbach/corpus_v3_selftest_v160final`, results
`/ceph/ibmi/abi/oliver/spextract/corpus_v3_selftest_v160final`, and the report `harness/corpus-v3-selftest-v160final.md`.
It is a local addition to the gitignored `harness/samples.yaml`; the file was backed up first to the session scratchpad
(`samples.yaml.bak-v160final-002718`, f8baa0f5). Java on ibminode05 is the system 21.0.12.1. The published arm needs no
harness alias here; one would be needed only for kim/dax, as `tune-v1.6.0rc2` was made.

| HeLa_22 | spectra | Sage | MSFragger | wall | peak RSS GB |
|---|---:|---:|---:|---|---:|
| v1.6.0rc3, this smoke (ibminode05) | 52,123 | 9,256 | 7,748 | 0:22 | 5.3 |
| v1.6.0rc1 smoke (ibminode06; before the three per-run defaults) | 52,484 | 9,259 | 7,743 | 0:29 | 4.4 |
| 1.5.0 final smoke (spock) | 53,715 | 8,837 | 7,211 | 0:27 | 4.6 |
| reference implementation, this smoke | 62,784 | 9,186 | 8,116 | 1:42 | 136.1 |

The spectrum count equals the carry-over's def_HeLa_22 (52,123). On HeLa py3 10 ng, what changed since rc1 (the F3 cap key, the three per-run
defaults, the scaling levers and the fixes) moves peptides by less than 0.1 %, as the CHANGELOG's screen says for HeLa py3. Against 1.5.0: Sage +4.7 %, MSFragger +7.4 %.
Target-only Sage peptides: 9,168 of 9,256.

**guardtest.** GUARDTEST_DONE pass 39 fail 0 (`ibminode05:/scratch/kohlbach/corpus_v3_selftest_v160final/ibminode05/guardtest/20261002-014705-02b3e3/RESULTS.txt`).
`guardtest --show` exits 0 with the lock free. No staged raw data, mzML or mzBIN is left under the plan's scratch root.

## Concurrent work, untouched

The 43-run corpus `corpus_v3_rc160_public` ran on spock, data, kim, dax and ibminode06 with arm `tune-v1.6.0rc2` the whole
time. Nothing here touched those nodes, their queues or that arm. The sync rewrote only `tools/test_diaspextract.py` among
the shipped tools on ceph, and the harness does not use it.

## Not done here

No push, tag, export or GitHub release. The release arm `v1.6.0` should come from this same build, in the 1.5.0 shape:
`REPO_E2E=<test/test_diaspextract.py at 81a0c32> verify_publish_dia13.sh v1.6.0 1.6.0 81a0c32 98d1780af471897eeb4bb59918a67f896266a517478f19de9869b35014b1207a`.
That holds while two conditions are true:

- no build input changes after 81a0c32 (docs-only commits such as this record do not count);
- the ibminode05 build tree still holds 98d1780a, which verify step 1 checks.

If a build input does change, re-sync without reconfiguring. Then re-run `idchain_rc3.sh` (on a new arm) and
`gate_D_160rc2.sh`, with R3 pinned to 3b2ea767 and R7b to 23ad7444.
