#!/bin/bash
# Re-run only the parts the ssh drop killed: entrapment FDR (baseline vs imw005) + MSFragger imw005.
# nohup-safe; writes a DONE marker.
set -u
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
ENTRAP=/scratch/kohlbach/bench/sage_entrap.json
OUT=/scratch/kohlbach/prof/confirm2.out; : > $OUT
echo "=== ENTRAPMENT FDR (target peptides + raw entrap fraction @ nominal 1%) ===" >> $OUT
entrap () {
  local N=$1 MZ=$2 D=/scratch/kohlbach/prof/entrap_$1; mkdir -p $D
  $SAGE $ENTRAP -o $D --disable-telemetry-i-dont-want-to-improve-sage "$MZ" > $D/sage.log 2>&1
  awk -F'\t' 'NR>1 && $8==1 && $38<=0.01 { if($3 ~ /ENTRAP_/) e[$2]=1; else t[$2]=1 } END{nt=0;ne=0;for(x in t)nt++;for(x in e)ne++; printf "  %-9s target=%d  entrap=%d  raw_entrap_frac=%.2f%%\n","'"$N"'",nt,ne,100*ne/(nt+ne)}' $D/results.sage.tsv >> $OUT
}
entrap baseline /scratch/kohlbach/prof/gate/pseudo.mzML
entrap imw005   /scratch/kohlbach/prof/imw005/pseudo.mzML
echo "=== MSFragger on imw005 (baseline MSFragger was 11,138) ===" >> $OUT
M=/scratch/kohlbach/prof/msf_imw005; mkdir -p $M
python3 /scratch/kohlbach/bench/fix_mzml_cvparams.py /scratch/kohlbach/prof/imw005/pseudo.mzML $M/fixed.mzML >> $OUT 2>&1
( cd $M && java -Xmx220G -jar /scratch/agxt-liver/work/fp-tools/MSFragger-4.4.1.jar /scratch/kohlbach/prof/msf_gate/msfragger.params $M/fixed.mzML > $M/engine.log 2>&1 )
tsv=$M/fixed.tsv; [ -s "$tsv" ] || tsv=$(ls $M/*.tsv 2>/dev/null | head -1)
python3 /scratch/kohlbach/prof/msf_gate/score_msf_td.py "$tsv" "$tsv" 2>/dev/null | head -1 >> $OUT
echo "CONFIRM2_DONE" >> $OUT
