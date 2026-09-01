#!/bin/bash
# Run-to-run variance: re-search ONE existing mzML (S30 corr_power=2) 3x per engine. Isolates engine
# nondeterminism (same input/config). Sage expected deterministic (sigma~0 => n=1 justified); MSFragger
# multithreaded (measure sigma). No re-extraction.
set -u
MZ=/scratch/kohlbach/prof/q2k2/pseudo.mzML
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
DEISO=/scratch/kohlbach/bench/sage_deiso.json
MSF=/scratch/agxt-liver/work/fp-tools/MSFragger-4.4.1.jar
PARAMS=/scratch/kohlbach/prof/msf_gate/msfragger.params
FIXCV=/scratch/kohlbach/bench/fix_mzml_cvparams.py; SCORE=/scratch/kohlbach/prof/msf_gate/score_msf_td.py
OUT=/scratch/kohlbach/prof/replicate.out; : > $OUT
sagepep(){ awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{p[$2]=1}END{n=0;for(x in p)n++;print n}' "$1"; }
R=/scratch/kohlbach/prof/rep; mkdir -p $R
echo "=== Sage x3 (deiso, same mzML) ===" >> $OUT
for i in 1 2 3; do d=$R/sage$i; mkdir -p $d
  $SAGE $DEISO -o $d --disable-telemetry-i-dont-want-to-improve-sage $MZ > $d/sage.log 2>&1
  echo "  sage_rep$i: $(sagepep $d/results.sage.tsv)" >> $OUT
done
# MSFragger: fix once, run engine 3x into separate dirs
FX=$R/fixed.mzML; [ -s $FX ] || python3 $FIXCV $MZ $FX > $R/fix.log 2>&1
echo "=== MSFragger x3 (same fixed.mzML) ===" >> $OUT
for i in 1 2 3; do d=$R/msf$i; mkdir -p $d; cp $FX $d/fixed.mzML
  ( cd $d && java -Xmx220G -jar $MSF $PARAMS $d/fixed.mzML > $d/engine.log 2>&1 )
  t=$d/fixed.tsv; [ -s "$t" ] || t=$(ls $d/*.tsv 2>/dev/null|head -1)
  printf "  msf_rep%d: " $i >> $OUT; python3 $SCORE "$t" "$t" 2>/dev/null | grep -oE "[0-9]+ target peptides" | head -1 >> $OUT
done
echo "REPLICATE_DONE" >> $OUT
