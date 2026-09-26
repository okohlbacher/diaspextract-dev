# 1.5.0 final-arm candidate: v1.5.0rc5 (release-1.5.0 e71b085), 2026-09-26

| step | where | result |
|---|---|---|
| sync_cluster.sh ibminode05 | e71b085 | DEPLOY COMMITTED 10:34, binary 8a451cbbc58ed3c9825e822d4f7c5d9a006839aed321fe0238ba117bf9bfff76, dnoise + tdf_load unit tests passed |
| verify_publish_dia13.sh v1.5.0rc5 1.5.0 e71b085 8a451cbb… (REPO_E2E /scratch/kohlbach/e2e15, suite 4713d992) | ibminode05 | VERIFY_DONE, e2e 30/30, guards G1-G5 PASS, Version: 1.5.0 |
| gate D (gate_D_150.sh, WANT_KEYS=23) | ibminode05 10:36-11:15 | all PASS: R1 8c1b047f, R2 e43672a0 (23 stamps), R2b 9e2b075f, R3 = R3a = R3b = R3c = 6498e613 (405,941 spectra), R4/R5/R5b refusals, R6 mzPeak; see gate-D-2026-09-26.md |
| harness smoke corpus_v3_selftest_v150 | data 15:05-15:09 | HeLa_22: 53,720 spectra, Sage 8,755 (0.95x), MSFragger 7,149 (0.88x) -- identical to the rc3b acceptance row; QUEUE_DONE failed 0 (diaTracer arm load-flagged) |
| harness guardtest | data 15:10-15:17 | 39/39 cases pass |

Still open before tagging: the codex review (usage limit until 2026-09-27 18:40), the full 49-run corpus on rc3b (spock
share), the release decision (rc3b defaults), the docs review of the exported files. Any further src change re-runs this table.
