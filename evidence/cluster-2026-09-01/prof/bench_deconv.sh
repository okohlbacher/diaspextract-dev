#!/bin/bash
set -u
IN=/scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
BIN=/scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
CFG=/scratch/kohlbach/bench/sage_deiso.json
D=/scratch/kohlbach/prof/deconv; mkdir -p $D
echo "[deconv] extract (gate + greedy deconvolution) ..."
$BIN -in "$IN" -out $D/pseudo.mzML -threads 90 -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 -assembly:require_isotope_support -assembly:deconvolve > $D/extract.log 2>&1
grep -E "pseudo-MS2 spectra to|Elapsed" $D/extract.log | tail -2
echo "[deconv] search ..."
$SAGE $CFG -o $D --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $D/sage.log 2>&1
awk -F'\t' 'NR>1 && $8==1 && $38<=0.01 {p[$2]=1; n++} END{k=0; for(x in p)k++; print "  deconv: PSMs="n"  peptides="k}' $D/results.sage.tsv
echo "BENCH_DECONV_DONE"
