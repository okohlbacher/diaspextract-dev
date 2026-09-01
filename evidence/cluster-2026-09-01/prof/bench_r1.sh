#!/bin/bash
# R1 timing: dynamic team apportionment. Wait for an idle node, run our best config (gate + IM 0.005),
# measure wall, and verify OUTPUT-IDENTICAL to imw005 (R1 is pure parallelism -> byte-identical mzML).
set -u
OUT=/scratch/kohlbach/prof/r1_timing.out; : > $OUT
echo "[wait] for idle node ..." >> $OUT
for i in $(seq 1 240); do
  pgrep -f "DIAPseudoSpectra|/sage |MSFragger|bench_native" >/dev/null || break
  sleep 15
done
IN=/scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
BIN=/scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra
D=/scratch/kohlbach/prof/r1; mkdir -p $D
echo "[r1] extract (gate + IM 0.005, dynamic p_team) ..." >> $OUT
/usr/bin/time -v $BIN -in "$IN" -out $D/pseudo.mzML -threads 100 -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 -assembly:require_isotope_support -assembly:im_weight_sigma 0.005 > $D/extract.log 2>&1
grep -E "took [0-9:]+ m \(wall|Percent of CPU|pseudo-MS2 spectra to" $D/extract.log | tail -3 >> $OUT
echo "[verify] spectra vs imw005 (expect identical 924255) + md5:" >> $OUT
ns=$(grep -oE "Wrote [0-9]+" $D/extract.log | grep -oE "[0-9]+" | head -1)
echo "  r1 spectra=$ns  (imw005=924255)" >> $OUT
echo "  r1 mzML md5:    $(md5sum $D/pseudo.mzML | cut -d" " -f1)" >> $OUT
echo "  imw005 md5:     $(md5sum /scratch/kohlbach/prof/imw005/pseudo.mzML | cut -d" " -f1)" >> $OUT
echo "R1_DONE (baseline wall: imw005 19:30; gate 19:38)" >> $OUT
