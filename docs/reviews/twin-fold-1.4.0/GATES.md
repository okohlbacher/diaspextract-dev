# 1.4.0rc1 gates (2026-09-21), arm v1.4.0rc1 = git 798f53f, binary sha256 fdc801e7…4ba10

`scripts/sync_cluster.sh ibminode05` (both unit suites passed) → `verify_publish_dia13.sh v1.4.0rc1 1.4.0 798f53f` with
`REPO_E2E` = test/test_diaspextract.py at 798f53f: guards G1–G5 PASS, **e2e 28/28** (the twin selftest, 12b, 15b among
them), `VERIFY_DONE`. Then, on ibminode05 (spock carried foreign load), the drivers in this directory:

**Dataset D** (`gate_D_140.sh`, -threads 100 unless noted):

| arm | args | want | digest | spectra | verdict |
|---|---|---|---|---|---|
| R1 | `-dnoise:ms1 false -assembly:twin_im_tolerance -1` | 8c1b047f | 8c1b047f3f70066c | 611,850 | PASS |
| R2 | `-assembly:twin_im_tolerance -1` (header: 17 spx: stamps) | e43672a0 | e43672a0d74b355a | 496,722 | PASS |
| R3 | defaults (the fold at 0.005), 3 tiles | — (sets the pin) | **9e2b075f**15b1c38a | 394,523 | PASS |
| R3a | `-tile:cells_per_tile 0` (one tile) | 9e2b075f | 9e2b075f15b1c38a | 394,523 | PASS |
| R3b | `-tile:cells_per_tile 2` | 9e2b075f | 9e2b075f15b1c38a | 394,523 | PASS |
| R3c | -threads 8 | 9e2b075f | 9e2b075f15b1c38a | 394,523 | PASS |
| R4, R5, R5b | old-prefix environment variables | refused | — | — | PASS |
| R6 | mzPeak output | — | — | 394,523 | PASS |

**TNBC 009** (`gate_T_140.sh`): S1 (`-dnoise:ms1 false`, fold off) `bff54a1f0885e005` == pin, 3,285,827 spectra, PASS;
S2 (fold off) `3aafd0b5edad9cc7` == pin, 3,010,923, PASS; S3 (defaults, 13 tiles) **`0dd997b9`134fda39**, 2,459,532
spectra, exit 0, no error line, tiles and header PASS; S3a (one tile) `0dd997b9134fda39` == S3, PASS. The run marked S3
FAIL: the 1.3.1 TNBC driver had no "no pin" branch (the D driver has one), so the arm that sets the new pin was compared
with the literal `-`. The copy here is fixed; S3 was not re-run, because S3a already reproduces its digest.

**PXD029836 run 1418** (`oracle_1418.sh`): fold off == the v1.3.1 extraction the study priced (semantic digest
`182986d1…`, identical); fold on == `bench/twin_merge.py --im=0.005` applied to that extraction, **802,099 of 802,099
spectra and 259,262,486 of 259,262,486 fragments identical** (mzml_specdiff.py), 250,573 spectra folded. Searched: Sage
50,691, MSFragger 45,367 (the priced `merge_tight` arm exactly). Entrapment at 0.005: 0.98 % [0.87, 1.09] against the
baseline's 0.98 % [0.87, 1.09], +0.01 points.

New pins at the 1.4.0 defaults: dataset D **9e2b075f** (394,523 spectra, −20.6 % vs e43672a0), TNBC 009 **0dd997b9**
(2,459,532, −18.3 % vs 3aafd0b5). The 1.3 pins remain the fold-off reference.
