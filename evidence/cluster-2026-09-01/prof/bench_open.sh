#!/bin/bash
# OPEN/BLIND-search re-baseline: speXtract (corr_power=2 default) vs diaTracer on S30, -150/+500 Da open
# search (empty variable_mods so every shift lands in the delta-mass dimension). The differentiator test:
# does speXtract's open-search output show the SAME clean delta-mass structure as diaTracer, or phantom
# isotope/charge artifacts? human.fasta for the histogram; human_entrap.fasta for open-search FDR. Resumable.
set -u
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
OPEN=/scratch/kohlbach/bench/sage_open.json
HUMAN=/scratch/kohlbach/bench/human.fasta
ENTRAP=/scratch/kohlbach/bench/human_entrap.fasta
SPX=/scratch/kohlbach/prof/q2k2/pseudo.mzML        # speXtract corr_power=2 (the new default output)
DT=/scratch/kohlbach/dt_s30/patched.mzML            # diaTracer reference
DELTA=/scratch/kohlbach/prof/open_delta.py
OUT=/scratch/kohlbach/prof/open_cmp.out; : > $OUT
mkcfg(){ python3 -c "import json;d=json.load(open('$OPEN'));d['database']['fasta']='$1';import json as j;j.dump(d,open('$2','w'))"; }
mkcfg $HUMAN  /scratch/kohlbach/prof/open_human.json
mkcfg $ENTRAP /scratch/kohlbach/prof/open_entrap.json
run(){ local name=$1 mz=$2 cfg=$3; local D=/scratch/kohlbach/prof/open_$name; mkdir -p $D
  echo "[$name] open search ..." >> $OUT
  [ -s $D/results.sage.tsv ] || $SAGE $cfg -o $D --disable-telemetry-i-dont-want-to-improve-sage $mz > $D/sage.log 2>&1
  local psm=$(awk -F'\t' 'NR>1{n++}END{print n}' $D/results.sage.tsv)
  echo "  $name: $psm rows" >> $OUT
}
run spx_human  $SPX open_human.json
run dt_human   $DT  open_human.json
echo "=== DELTA-MASS DIAGNOSTIC (human.fasta, 1% FDR) ===" >> $OUT
python3 $DELTA spx=/scratch/kohlbach/prof/open_spx_human/results.sage.tsv \
               dt=/scratch/kohlbach/prof/open_dt_human/results.sage.tsv >> $OUT 2>&1
run spx_entrap $SPX open_entrap.json
run dt_entrap  $DT  open_entrap.json
echo "=== OPEN-SEARCH ENTRAPMENT FDR ===" >> $OUT
python3 /scratch/kohlbach/prof/entrap_apply.py \
  spx_open=/scratch/kohlbach/prof/open_spx_entrap/results.sage.tsv \
  dt_open=/scratch/kohlbach/prof/open_dt_entrap/results.sage.tsv >> $OUT 2>&1
echo "OPEN_DONE" >> $OUT
