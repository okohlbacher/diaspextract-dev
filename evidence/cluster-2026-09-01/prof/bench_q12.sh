#!/bin/bash
# Q1 (gate:variance_support) + Q2 (assembly:corr_power) arms. Both engines, entrapment. Resumable, nohup-safe.
# Baselines: gate 9,989 Sage / imw005 10,394 / diaTracer 11,517 (Sage); MSFragger gate 11,033 / dt (see full_cmp).
set -u
IN=/scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
BIN=/scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
DEISO=/scratch/kohlbach/bench/sage_deiso.json; ENTRAP=/scratch/kohlbach/bench/sage_entrap.json
MSF=/scratch/agxt-liver/work/fp-tools/MSFragger-4.4.1.jar
PARAMS=/scratch/kohlbach/prof/msf_gate/msfragger.params
FIXCV=/scratch/kohlbach/bench/fix_mzml_cvparams.py
SCORE=/scratch/kohlbach/prof/msf_gate/score_msf_td.py
# gate COMMON (NO native aggregation) -- matches the gate/imw005 baseline extraction
COMMON="-threads 100 -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 -assembly:require_isotope_support -perf:stream_load"
OUT=/scratch/kohlbach/prof/q12_cmp.out; : > $OUT

sagepep(){ awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{p[$2]=1}END{n=0;for(x in p)n++;print n}' "$1"; }
run () {
  local NAME=$1; shift; local D=/scratch/kohlbach/prof/$NAME; mkdir -p $D
  echo "[$NAME] extract ($*) ..." >> $OUT
  if [ ! -s $D/pseudo.mzML ]; then $BIN -in "$IN" -out $D/pseudo.mzML $COMMON "$@" > $D/extract.log 2>&1; fi
  local nsp=$(grep -oE "pseudo-MS2 spectra to|Wrote [0-9]+ " $D/extract.log | tail -1)
  # Sage deiso (nominal 1% peptide_q)
  [ -s $D/results.sage.tsv ] || $SAGE $DEISO -o $D --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $D/sage.log 2>&1
  local pep=$(sagepep $D/results.sage.tsv)
  # Sage entrapment
  local De=/scratch/kohlbach/prof/entrap_$NAME; mkdir -p $De
  [ -s $De/results.sage.tsv ] || $SAGE $ENTRAP -o $De --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $De/sage.log 2>&1
  local eline=$(awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{if($3~/ENTRAP_/)e[$2]=1;else t[$2]=1}END{nt=0;ne=0;for(x in t)nt++;for(x in e)ne++;printf "target=%d entrap=%d frac=%.2f%%",nt,ne,100*ne/(nt+ne)}' $De/results.sage.tsv)
  # MSFragger (cvParam-fix -> engine -> target-decoy scorer)
  local M=/scratch/kohlbach/prof/msf_$NAME; mkdir -p $M
  [ -s $M/fixed.mzML ] || python3 $FIXCV $D/pseudo.mzML $M/fixed.mzML >>$M/fix.log 2>&1
  [ -s $M/fixed.tsv ] || ( cd $M && java -Xmx220G -jar $MSF $PARAMS $M/fixed.mzML > $M/engine.log 2>&1 )
  local mtsv=$M/fixed.tsv; [ -s "$mtsv" ] || mtsv=$(ls $M/*.tsv 2>/dev/null|head -1)
  local msf=$(python3 $SCORE "$mtsv" "$mtsv" 2>/dev/null | head -1)
  printf "  %-12s Sage=%-6s  entrap[%s]  MSFragger[%s]\n" "$NAME" "$pep" "$eline" "$msf" >> $OUT
}

echo "=== Q1/Q2 arms (baselines: gate Sage 9,989 / imw005 10,394 / diaTracer 11,517 ; MSFragger gate 11,033) ===" >> $OUT
# base = determinism/control (default-off flags must reproduce gate 9,989). q2k1 = decisive Q2 (emit-only).
# q2k2 = dose-response. q1 = empirical go/no-go for the review's DROP (predicted faint-tail collapse @0.3).
run base
run q2k1 -assembly:corr_power 1
run q2k2 -assembly:corr_power 2
run q1   -gate:variance_support
echo "Q12_DONE" >> $OUT
