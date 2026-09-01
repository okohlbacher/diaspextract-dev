#!/bin/bash
# Gated benchmark: re-extract S30 with the isotope-support gate ON, identical Sage search, then
# report FDR-recalibrated peptides + emission. Confirms the projected 924k / -0.78% for real.
set -u
BL=/scratch/kohlbach/prof/build_gate.log
echo "[wait] build ..."; for i in $(seq 1 120); do grep -q BUILD_EXIT "$BL" 2>/dev/null && break; sleep 5; done
grep BUILD_EXIT "$BL" || { echo "[abort] build didn't finish"; tail -5 "$BL"; exit 2; }
grep -q "BUILD_EXIT=0" "$BL" || { echo "[abort] build FAILED"; tail -15 "$BL"; exit 2; }
echo "  build OK"

D=/scratch/kohlbach/prof/gate; mkdir -p $D
IN=/scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
echo "[extract] gated ..."
/usr/bin/time -v /scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra -in "$IN" -out $D/pseudo.mzML -threads 100 \
  -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 \
  -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 \
  -assembly:require_isotope_support > $D/extract.log 2>&1
echo "[extract done]"; grep -E "require_isotope_support: dropped|pseudo-MS2 spectra to|Elapsed .wall clock" $D/extract.log | tail -4

echo "[search] Sage (identical config) ..."
/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage /scratch/kohlbach/bench/sage_deiso.json \
  -o $D --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $D/sage.log 2>&1
echo "[search done]"

echo ""; echo "===== GATED RESULT (S30) ====="
awk -F'\t' 'NR>1 && $8==1 && $38<=0.01 {pep[$2]=1; psm++} END{n=0; for(k in pep)n++;
  print "emission (identified target PSMs @1% peptide_q):", psm; print "unique peptides:", n}' $D/results.sage.tsv
echo "baseline (det4): 1528113 spectra, 113130 PSMs, 10036 peptides | diaTracer: 700434 spectra"
echo "GATE_RUN_DONE"
