#!/bin/bash
# Test diaTracer's UPSTREAM signal enhancement (pre-centroiding neighbour aggregation, already coded).
# 2 arms on top of the gate: native_ms1_neighbors alone, and stacked with im_weight 0.005 (our best).
# vs gate baseline 9,989 / imw005 10,394 / diaTracer 11,517. Sage + entrapment. Resumable, nohup-safe.
set -u
IN=/scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
BIN=/scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
DEISO=/scratch/kohlbach/bench/sage_deiso.json; ENTRAP=/scratch/kohlbach/bench/sage_entrap.json
COMMON="-threads 100 -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 -assembly:require_isotope_support -perf:stream_load -trace:native_ms1_neighbors 1"
OUT=/scratch/kohlbach/prof/native_cmp.out; : > $OUT
run () {
  local NAME=$1; shift; local D=/scratch/kohlbach/prof/$NAME; mkdir -p $D
  echo "[$NAME] extract ($*) ..." >> $OUT
  $BIN -in "$IN" -out $D/pseudo.mzML $COMMON "$@" > $D/extract.log 2>&1
  grep -E "pseudo-MS2 spectra to|native.*neighbor|streaming|Broken|error|Exception" $D/extract.log | tail -3 >> $OUT
  $SAGE $DEISO -o $D --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $D/sage.log 2>&1
  local pep=$(awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{p[$2]=1}END{n=0;for(x in p)n++;print n}' $D/results.sage.tsv)
  local De=/scratch/kohlbach/prof/entrap_$NAME; mkdir -p $De
  $SAGE $ENTRAP -o $De --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $De/sage.log 2>&1
  awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{if($3~/ENTRAP_/)e[$2]=1;else t[$2]=1}END{nt=0;ne=0;for(x in t)nt++;for(x in e)ne++;printf "  '"$NAME"': Sage_pep=%s  entrap_target=%d  entrap_frac=%.2f%%\n","'"$pep"'",nt,100*ne/(nt+ne)}' $De/results.sage.tsv >> $OUT
}
echo "=== native pre-centroiding aggregation (baselines: gate 9,989 / imw005 10,394 / diaTracer 11,517) ===" >> $OUT
run nat_ms1        # gate + native_ms1_neighbors 1
run nat_ms1_imw -assembly:im_weight_sigma 0.005   # + im_weight
echo "NATIVE_DONE" >> $OUT
