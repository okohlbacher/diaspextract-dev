#!/bin/bash
# Validate the IM-weighting win: (1) sigma=0.007 refine; (2) ENTRAPMENT FDR baseline vs imw005 (is
# +4.1% real or FDR inflation?); (3) MSFragger on imw005 (both-engines policy).
set -u
IN=/scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
BIN=/scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
DEISO=/scratch/kohlbach/bench/sage_deiso.json
ENTRAP=/scratch/kohlbach/bench/sage_entrap.json
COMMON="-threads 100 -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 -assembly:require_isotope_support"

echo "=== (1) sigma=0.007 (baselines: gated 9,989 / imw005 10,394 / diaTracer 11,517) ==="
D=/scratch/kohlbach/prof/imw007; mkdir -p $D
$BIN -in "$IN" -out $D/pseudo.mzML $COMMON -assembly:im_weight_sigma 0.007 > $D/extract.log 2>&1
$SAGE $DEISO -o $D --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $D/sage.log 2>&1
awk -F'\t' 'NR>1 && $8==1 && $38<=0.01 {p[$2]=1} END{k=0;for(x in p)k++;print "  imw007: peptides="k}' $D/results.sage.tsv

echo "=== (2) ENTRAPMENT FDR (target peptides + raw entrap fraction @ nominal 1%) ==="
entrap () {
  local N=$1 MZ=$2 D=/scratch/kohlbach/prof/entrap_$1; mkdir -p $D
  $SAGE $ENTRAP -o $D --disable-telemetry-i-dont-want-to-improve-sage "$MZ" > $D/sage.log 2>&1
  awk -F'\t' 'NR>1 && $8==1 && $38<=0.01 { if($3 ~ /ENTRAP_/) e[$2]=1; else t[$2]=1 } END{nt=0;ne=0;for(x in t)nt++;for(x in e)ne++; printf "  %-9s target=%d  entrap=%d  raw_entrap_frac=%.2f%%\n","'"$N"'",nt,ne,100*ne/(nt+ne)}' $D/results.sage.tsv
}
entrap baseline /scratch/kohlbach/prof/gate/pseudo.mzML
entrap imw005   /scratch/kohlbach/prof/imw005/pseudo.mzML

echo "=== (3) MSFragger on imw005 (baseline MSFragger was 11,138) ==="
M=/scratch/kohlbach/prof/msf_imw005; mkdir -p $M
python3 /scratch/kohlbach/bench/fix_mzml_cvparams.py /scratch/kohlbach/prof/imw005/pseudo.mzML $M/fixed.mzML
( cd $M && java -Xmx220G -jar /scratch/agxt-liver/work/fp-tools/MSFragger-4.4.1.jar /scratch/kohlbach/prof/msf_gate/msfragger.params $M/fixed.mzML > $M/engine.log 2>&1 )
tsv=$M/fixed.tsv; [ -s "$tsv" ] || tsv=$(ls $M/*.tsv 2>/dev/null | head -1)
python3 /scratch/kohlbach/prof/msf_gate/score_msf_td.py "$tsv" "$tsv" 2>/dev/null | head -1
echo "CONFIRM_DONE"
