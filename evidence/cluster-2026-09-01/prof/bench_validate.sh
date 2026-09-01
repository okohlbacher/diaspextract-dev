#!/bin/bash
# PRE-REGISTERED multi-file generalisation test (codex + vibe demand). Frozen params: corr_power=2,
# im_weight_sigma=0.005 (NO retuning). Files S08, S23 (untouched; S30 was the tuning file). Configs:
# base / corr_k2 / stack. Screen on Sage + entrapment at COMMON EMPIRICAL FDR; MSFragger = guardrail.
# SHIP stack if stack >= corr_k2 on BOTH files (Sage @ common empirical FDR) with no material regression
# AND corr_k2/stack beat base on both. Fallback: corr_k2 alone if stack doesn't separate. Resumable.
set -u
S08=/scratch/kohlbach/rawd/FKL4341-S08-A-3_K30454-19-3_QKL29021A9_Slot1-12_1_1305.d
S23=/scratch/kohlbach/rawd/FKL4341-S23-A-8_K253-09-2_QKL29026AF_Slot1-17_1_1320.d
BIN=/scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
DEISO=/scratch/kohlbach/bench/sage_deiso.json; ENTRAP=/scratch/kohlbach/bench/sage_entrap.json
MSF=/scratch/agxt-liver/work/fp-tools/MSFragger-4.4.1.jar
PARAMS=/scratch/kohlbach/prof/msf_gate/msfragger.params
FIXCV=/scratch/kohlbach/bench/fix_mzml_cvparams.py; SCORE=/scratch/kohlbach/prof/msf_gate/score_msf_td.py
CFDR=/scratch/kohlbach/prof/score_common_fdr.py
COMMON="-threads 100 -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 -assembly:require_isotope_support -perf:stream_load"
OUT=/scratch/kohlbach/prof/validate_cmp.out; : > $OUT
sagepep(){ awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{p[$2]=1}END{n=0;for(x in p)n++;print n}' "$1"; }
run () {
  local tag=$1 dfile=$2 name=$3; shift 3; local D=/scratch/kohlbach/prof/val_${tag}_${name}; mkdir -p $D
  echo "[$tag/$name] extract ($*) ..." >> $OUT
  if [ ! -s $D/pseudo.mzML ]; then $BIN -in "$dfile" -out $D/pseudo.mzML $COMMON "$@" > $D/extract.log 2>&1; fi
  [ -s $D/results.sage.tsv ] || $SAGE $DEISO -o $D --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $D/sage.log 2>&1
  local pep=$(sagepep $D/results.sage.tsv)
  local De=/scratch/kohlbach/prof/entrap_val_${tag}_${name}; mkdir -p $De
  [ -s $De/results.sage.tsv ] || $SAGE $ENTRAP -o $De --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $De/sage.log 2>&1
  local eline=$(awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{if($3~/ENTRAP_/)e[$2]=1;else t[$2]=1}END{nt=0;ne=0;for(x in t)nt++;for(x in e)ne++;printf "target=%d entrap=%d frac=%.2f%%",nt,ne,100*ne/(nt+ne)}' $De/results.sage.tsv)
  local M=/scratch/kohlbach/prof/msf_val_${tag}_${name}; mkdir -p $M
  [ -s $M/fixed.mzML ] || python3 $FIXCV $D/pseudo.mzML $M/fixed.mzML >>$M/fix.log 2>&1
  [ -s $M/fixed.tsv ] || ( cd $M && java -Xmx220G -jar $MSF $PARAMS $M/fixed.mzML > $M/engine.log 2>&1 )
  local mtsv=$M/fixed.tsv; [ -s "$mtsv" ] || mtsv=$(ls $M/*.tsv 2>/dev/null|head -1)
  local msf=$(python3 $SCORE "$mtsv" "$mtsv" 2>/dev/null | head -1)
  printf "  %-12s Sage=%-6s entrap[%s] MSFragger[%s]\n" "$tag/$name" "$pep" "$eline" "$msf" >> $OUT
}
echo "=== PRE-REGISTERED generalisation test: S08 + S23, frozen corr_power=2 / im 0.005 ===" >> $OUT
for pair in "s08 $S08" "s23 $S23"; do
  set -- $pair; tag=$1; df=$2
  run $tag $df base
  run $tag $df k2    -assembly:corr_power 2
  run $tag $df stack -assembly:corr_power 2 -assembly:im_weight_sigma 0.005
done
echo "=== common empirical-FDR (targets @ <=1% and <=2%) ===" >> $OUT
for thr in 0.01 0.02; do
  python3 $CFDR $thr \
    s08_base=/scratch/kohlbach/prof/entrap_val_s08_base/results.sage.tsv \
    s08_k2=/scratch/kohlbach/prof/entrap_val_s08_k2/results.sage.tsv \
    s08_stack=/scratch/kohlbach/prof/entrap_val_s08_stack/results.sage.tsv \
    s23_base=/scratch/kohlbach/prof/entrap_val_s23_base/results.sage.tsv \
    s23_k2=/scratch/kohlbach/prof/entrap_val_s23_k2/results.sage.tsv \
    s23_stack=/scratch/kohlbach/prof/entrap_val_s23_stack/results.sage.tsv >> $OUT 2>&1
done
echo "VALIDATE_DONE" >> $OUT
