#!/bin/bash
/usr/bin/time -v /scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra -in /scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d -out /scratch/kohlbach/prof/det4/pseudo.mzML -threads 100 -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 > /scratch/kohlbach/prof/det4/extract.log 2>&1
grep -iE "Elapsed .wall|Percent of CPU" /scratch/kohlbach/prof/det4/extract.log
grep -m1 -oE "<spectrumList count=\"[0-9]+\"" /scratch/kohlbach/prof/det4/pseudo.mzML
/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage /scratch/kohlbach/bench/sage_deiso.json -o /scratch/kohlbach/prof/det4 --disable-telemetry-i-dont-want-to-improve-sage /scratch/kohlbach/prof/det4/pseudo.mzML > /scratch/kohlbach/prof/det4/sage.log 2>&1
grep -oE "discovered [0-9]+ target peptides" /scratch/kohlbach/prof/det4/sage.log | tail -1
echo DET4_DONE
