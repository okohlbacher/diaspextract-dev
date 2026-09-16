#!/bin/bash
# Functional smoke of the published diaWeaver arm on a PUBLIC HeLa diaPASEF .d (PXD017703, 100SPD, run 2731),
# staged as analysis.tdf + analysis.tdf_bin only (the dwv_stage1 staging rule). NOT a benchmark: it checks that the
# tool accepts a tdf-only .d, writes the log lines the harness waits for, and yields a real output file for the
# re-encode guard test. Bounded: 45 min, 32 threads, nice 10; the whole process group is killed at the bound.
set -u
umask 077
D=/scratch/kohlbach/dwv_review/smoke
RAW=/ceph/ibmi/abi/oliver/benchmark/PXD017703/raw/100SPD_py8/20200505_Evosep_100SPD_SG06-16_MLHeLa_100ng_py8_S2-C1_1_2731.d
ARM=/ceph/ibmi/abi/oliver/spextract/diaweaver-7ed1169
mkdir -p "$D/hela2731.d" "$D/out" || exit 9
echo "start $(date -Is) host $(hostname) load $(cut -d' ' -f1 /proc/loadavg)" > "$D/smoke.status"
cp "$RAW/analysis.tdf" "$RAW/analysis.tdf_bin" "$D/hela2731.d/" || { echo "copy failed" >> "$D/smoke.status"; exit 8; }
cat "$D/hela2731.d/analysis.tdf" "$D/hela2731.d/analysis.tdf_bin" > /dev/null
echo "staged $(date -Is) files $(ls "$D/hela2731.d" | tr '\n' ' ')" >> "$D/smoke.status"
cd "$D/out" || exit 9
env -i HOME="$HOME" PATH=/usr/bin:/bin LC_ALL=C TMPDIR="$D" bash -c '
  source "$1/env.sh" || exit 7
  exec timeout -s TERM -k 30 2700 /usr/bin/time -v -o "$2/time.log" nice -n 10 "$DWV_BIN" -in "$2/hela2731.d" -out "$2/out" -threads 32
' _ "$ARM" "$D" > "$D/dwv.log" 2>&1
rc=$?
echo "end $(date -Is) rc=$rc" >> "$D/smoke.status"
ls -la "$D/out" >> "$D/smoke.status"
ls -la "$D" >> "$D/smoke.status"
