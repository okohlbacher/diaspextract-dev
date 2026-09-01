#!/bin/bash
# Full diaTracer comparison, both engines. Our best = gate + im_weight 0.005 (imw005). Resumable.
set -u
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
ENTRAP=/scratch/kohlbach/bench/sage_entrap.json
MSF=/scratch/agxt-liver/work/fp-tools/MSFragger-4.4.1.jar
PARAMS=/scratch/kohlbach/prof/msf_gate/msfragger.params
OUT=/scratch/kohlbach/prof/full_cmp.out; : > $OUT
sagepep(){ awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{p[$2]=1}END{n=0;for(x in p)n++;print n}' "$1"; }
entrap(){ local N=$1 MZ=$2 D=/scratch/kohlbach/prof/entrap_$1; mkdir -p $D
  [ -s $D/results.sage.tsv ] || $SAGE $ENTRAP -o $D --disable-telemetry-i-dont-want-to-improve-sage "$MZ" > $D/sage.log 2>&1
  awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{if($3~/ENTRAP_/)e[$2]=1;else t[$2]=1}END{nt=0;ne=0;for(x in t)nt++;for(x in e)ne++;printf "  entrap %-9s target=%d entrap=%d frac=%.2f%%\n","'"$N"'",nt,ne,100*ne/(nt+ne)}' $D/results.sage.tsv >> $OUT
}
msf(){ local N=$1 MZ=$2 M=/scratch/kohlbach/prof/msf_$1; mkdir -p $M
  [ -s $M/fixed.mzML ] || python3 /scratch/kohlbach/bench/fix_mzml_cvparams.py "$MZ" $M/fixed.mzML >>$M/fix.log 2>&1
  local tsv=$M/fixed.tsv
  [ -s "$tsv" ] || ( cd $M && java -Xmx220G -jar $MSF $PARAMS $M/fixed.mzML > $M/engine.log 2>&1 )
  [ -s "$tsv" ] || tsv=$(ls $M/*.tsv 2>/dev/null|head -1)
  printf "  MSFragger %-9s " "$N" >> $OUT
  python3 /scratch/kohlbach/prof/msf_gate/score_msf_td.py "$tsv" "$tsv" 2>/dev/null | head -1 >> $OUT
}
echo "=== SAGE (nominal 1% peptide_q) ===" >> $OUT
echo "  ours-best(imw005)=$(sagepep /scratch/kohlbach/prof/imw005/results.sage.tsv)  baseline-gate=9989  diaTracer=11517" >> $OUT
echo "=== ENTRAPMENT FDR (Sage) ===" >> $OUT
entrap baseline /scratch/kohlbach/prof/gate/pseudo.mzML
entrap imw005   /scratch/kohlbach/prof/imw005/pseudo.mzML
echo "=== MSFragger (target-decoy 1% peptide FDR) ===" >> $OUT
msf imw005 /scratch/kohlbach/prof/imw005/pseudo.mzML
msf dt     /scratch/kohlbach/dt_s30/patched.mzML
echo "  (baseline-gate MSFragger = 11,033 from msf_gate)" >> $OUT
echo "FULL_DONE" >> $OUT
