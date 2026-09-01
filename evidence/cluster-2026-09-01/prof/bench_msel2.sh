#!/bin/bash
# mono-guard: does the averagine guard on leftward isotope steps kill the -1.003 Da open-search artefact?
# Controls (mono_guard=0, from prof/q2k2 + open_spx_*): closed Sage 10,802 | open 160,248 PSMs,
# isotope-shift 8.20%, -1 bin 7,616 | open entrap 8,887 targets @1.29% FDR. diaTracer: 9,989 @1.07%, 3.46%.
set -u
IN=/scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
BIN=/scratch/kohlbach/OpenMS/build/bin/DIAPseudoSpectra
SAGE=/scratch/kohlbach/bench/sage-v0.14.7-x86_64-unknown-linux-gnu/sage
DEISO=/scratch/kohlbach/bench/sage_deiso.json
COMMON="-threads 100 -trace:ms2_chrom_peak_snr 1.0 -trace:ms2_noise_threshold_int 10 -trace:ms2_min_length_sec 0 -trace:ms2_split_valleys 7.0 -trace:ms1_split_valleys 7.0 -charge:scoring count -perf:trace_bands 12 -assembly:require_isotope_support -perf:stream_load -assembly:corr_power 2"
OUT=/scratch/kohlbach/prof/msel2_cmp.out; : > $OUT
sagepep(){ awk -F'\t' 'NR>1 && $8==1 && $38<=0.01{p[$2]=1}END{n=0;for(x in p)n++;print n}' "$1"; }
run(){ local name=$1 g=$2; shift 2; local D=/scratch/kohlbach/prof/mono_$name; mkdir -p $D
  echo "[$name] mono_averagine_guard=$g ..." >> $OUT
  [ -s $D/pseudo.mzML ] || $BIN -in "$IN" -out $D/pseudo.mzML $COMMON -charge:mono_averagine_guard $g "$@" > $D/extract.log 2>&1
  echo "  emission: $(grep -oE 'Wrote [0-9]+' $D/extract.log | tail -1)" >> $OUT
  # CLOSED search (regression guard)
  [ -s $D/results.sage.tsv ] || $SAGE $DEISO -o $D --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $D/sage.log 2>&1
  echo "  closed Sage: $(sagepep $D/results.sage.tsv)   (control 10,802)" >> $OUT
  # OPEN search: delta-mass diagnostic (human) + entrapment FDR
  local H=/scratch/kohlbach/prof/openmono_${name}_human;  mkdir -p $H
  local E=/scratch/kohlbach/prof/openmono_${name}_entrap; mkdir -p $E
  [ -s $H/results.sage.tsv ] || $SAGE /scratch/kohlbach/prof/open_human.json  -o $H --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $H/sage.log 2>&1
  [ -s $E/results.sage.tsv ] || $SAGE /scratch/kohlbach/prof/open_entrap.json -o $E --disable-telemetry-i-dont-want-to-improve-sage $D/pseudo.mzML > $E/sage.log 2>&1
  python3 /scratch/kohlbach/prof/open_delta.py "$name"=$H/results.sage.tsv >> $OUT 2>&1
  python3 /scratch/kohlbach/prof/entrap_apply.py "open_$name"=$E/results.sage.tsv 2>/dev/null | tail -2 >> $OUT
}
run msel2 0 -charge:mono_averagine_select
echo "MSEL2_DONE" >> $OUT
