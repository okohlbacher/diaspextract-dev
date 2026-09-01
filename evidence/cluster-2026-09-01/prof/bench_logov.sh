#!/bin/bash
# Gate-statistic sweep: gate + gate:coelution=logoverlap (no zero-padding, AlphaDIA-style) at three
# min_correlation operating points. Rejects chance-aligned sparse noise at SCORING without removing
# shared true fragments (unlike the falsified competitive/apex/subtraction family). vs gated 9,989 & diaTracer 11,517.
set -u
IN=/scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
BIN=/scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
CFG=/scratch/kohlbach/bench/sage_deiso.json
COMMON="-threads 100 -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 -assembly:require_isotope_support -gate:coelution logoverlap"
run () {
  local NAME=$1 MC=$2
  local D=/scratch/kohlbach/prof/$NAME; mkdir -p $D
  echo "[$NAME] extract (logoverlap min_correlation=$MC) ..."
  $BIN -in "$IN" -out $D/pseudo.mzML $COMMON -gate:min_correlation $MC > $D/extract.log 2>&1
  grep -E "pseudo-MS2 spectra to|Elapsed" $D/extract.log | tail -2
  $SAGE $CFG -o $D --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $D/sage.log 2>&1
  awk -F'\t' 'NR>1 && $8==1 && $38<=0.01 {p[$2]=1; n++} END{k=0; for(x in p)k++; print "  '"$NAME"' (mc='"$MC"'): PSMs="n"  peptides="k}' $D/results.sage.tsv
}
echo "=== baseline: gated 9,989 (Pearson mc=0.3) | diaTracer 11,517 ==="
run logov010 0.10
run logov020 0.20
run logov030 0.30
echo "BENCH_LOGOV_DONE"
