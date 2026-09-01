#!/bin/bash
set -u
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
CFG=/scratch/kohlbach/bench/sage_chimera.json
run () {  # name mzml outdir
  local N=$1 MZ=$2 D=$3; mkdir -p $D
  $SAGE $CFG -o $D --disable-telemetry-i-dont-want-to-improve-sage "$MZ" > $D/sage.log 2>&1
  awk -F'\t' 'NR>1 && $8==1 && $38<=0.01 {p[$2]=1;n++} END{k=0;for(x in p)k++; print "  '"$N"': PSMs="n" peptides="k}' $D/results.sage.tsv
}
echo "=== chimera:true report_psms:5 re-search (existing spectra; baselines: ours 9,989 / diaTracer 11,517) ==="
run "ours-gated-chimera" /scratch/kohlbach/prof/gate/pseudo.mzML   /scratch/kohlbach/prof/chim_ours
run "diaTracer-chimera"  /scratch/kohlbach/dt_s30/patched.mzML      /scratch/kohlbach/prof/chim_dt
echo "CHIM_DONE"
