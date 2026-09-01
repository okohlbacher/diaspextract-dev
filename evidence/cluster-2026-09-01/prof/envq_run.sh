#!/bin/bash
# Re-extract S30 (default, no gate) with the env_quality stamp, then analyze whether env_quality can
# cut the supported side 924k->700k at neutral peptides. Deterministic => joins to det4 search by index.
set -u
D=/scratch/kohlbach/prof/envq; mkdir -p $D
IN=/scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
echo "[extract] with env_quality stamp (default flags) ..."
/usr/bin/time -v /scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra -in "$IN" -out $D/pseudo.mzML -threads 100 \
  -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 \
  -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 \
  > $D/extract.log 2>&1
echo "[extract done]"; grep -E "pseudo-MS2 spectra to|Elapsed .wall clock" $D/extract.log | tail -2
NS=$(grep -c "<spectrum " $D/pseudo.mzML); echo "  spectra: $NS (expect 1528113)"

echo "[extract stamps] index, spx_guessed, spx_envq ..."
awk '
  /<spectrum /        { if(match($0,/index="[0-9]+"/)){s=substr($0,RSTART,RLENGTH); gsub(/[^0-9]/,"",s); idx=s} g=""; q="" }
  /name="spx_guessed"/{ if(match($0,/value="[0-9]+"/)){v=substr($0,RSTART,RLENGTH); gsub(/[^0-9]/,"",v); g=v} }
  /name="spx_envq"/   { if(match($0,/value="[0-9.eE+-]+"/)){v=substr($0,RSTART,RLENGTH); gsub(/value="|"/,"",v); q=v}; if(g!=""){print idx"\t"g"\t"q} }
' $D/pseudo.mzML > $D/stamps.tsv
echo "  stamps.tsv rows: $(wc -l < $D/stamps.tsv)"; head -3 $D/stamps.tsv

echo ""; echo "===== SUPPORTED-SIDE env_quality ANALYSIS ====="
python3 $D/supported_envq.py
echo "ENVQ_DONE"
