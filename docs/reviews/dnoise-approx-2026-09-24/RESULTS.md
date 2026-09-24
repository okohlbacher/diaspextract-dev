# dnoise:ms1 above 100 ms AccumulationTime: approximate instead of refuse (2026-09-24)

User decision 2026-09-24: take option 2 (approximate raw counts), no refusal, no warning. Commit 9b009ce, rc arm
`v1.4.1dn1` (binary 2ac455bf..., unit suites passed on the node, verify_publish e2e 30/30).

| Check | Result |
|---|---|
| Gate D (`gate_D_140_final.sh v1.4.1dn1 9b009ce 2ac455bf...`, ibminode05) | all PASS: R1 8c1b047f, R2 e43672a0, R3/R3a/R3b/R3c 9e2b075f (= 1.4.1), R4/R5/R5b exit 6, R6 mzPeak 394,523; stage dir removed |
| PXD029836 run 1414 (2,616 MS1 frames at 166.007 ms), released v1.4.1 defaults | exit 6: "AccumulationTime 166.007 ms exceeds 100 ms" (the old refusal) |
| same, v1.4.1dn1 defaults | exit 0, 0:11.89, 2.8 GB; dnoise kept 14,475,014 of 357,008,039 MS1 points (4.05 %); 81,556 spectra |
| same, v1.4.1dn1 `-dnoise:ms1 false` | exit 0, 0:14.15, 4.6 GB; 129,592 spectra |
| ground truth: dnoise v0.1.0 binary on 1414 (reads raw counts), then v1.4.1dn1 `-dnoise:ms1 false` | 81,661 spectra; MS1 picked 4,074,301 vs 4,074,470 approximate (+0.004 %); spectra -0.13 % |

Unit tests: 125 / 166 ms / corr 0.5 accepted; nearest candidate at 166 ms (raw 1 and 2 give 1, 2 taken); every value
below 2^20 at corr 0.8, 100/166, 0.5 recovers a raw count that corrects back to it. The tie-break check was falsified
by flipping `<` to `<=` (fails at line 876). Scripts: data:/scratch/kohlbach/dn166.sh, dn166ref.sh; outputs in
data:/scratch/kohlbach/dn166/. Not released; no CLI review yet (for the next release).
