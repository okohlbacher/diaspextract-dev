#!/bin/bash
# scalfix/review (2026-10-01): one HeLa_22 extraction with a hard time limit, for the team-of-one admission hang.
# Same staging and per-node heavy lock as tools/tunerun.sh; the tool runs under timeout(1) INSIDE /usr/bin/time.
#   usage: repro.sh <arm name> <label> <threads> <timeout s> [VAR=val ...] -- [tool options ...]
# Writes $TOP/scalfix/review/repro/<label>/{e.log,time.log,run.info,verdict}; verdict is one line:
#   COMPLETED <digest> <spectra> MATCH|DIFF  |  TIMEOUT windows_done=<n> last='<last log line>'  |  FAILED rc=<rc>
set -u
ARMN=${1:?arm}; LAB=${2:?label}; TH=${3:?threads}; TO=${4:?timeout}; shift 4
envs=(); while [ $# -gt 0 ] && [ "$1" != "--" ]; do envs+=("$1"); shift; done; [ "${1:-}" = "--" ] && shift
TOP=/ceph/ibmi/abi/oliver/spextract/tune-2026-09-29
ARM=$TOP/arms/$ARMN/env.sh; REFD=4ca0a8d0fbfea6e7c22c0d308338497b4f5cda5f3b9f6438aa48fb4e47c13abd
RES=$TOP/scalfix/review/repro/$LAB; T=/scratch/kohlbach/tune; ST=$T/stage/HeLa_22.d; O=$T/scalfix-review/repro/$LAB
[ -e "$RES" ] && { echo "REFUSED: $RES exists"; exit 2; }
[ -f "$ARM" ] || { echo "REFUSED: no $ARM"; exit 2; }
[ -s "$ST/analysis.tdf" ] && [ -s "$ST/analysis.tdf_bin" ] || { echo "REFUSED: HeLa_22 not staged at $ST (run tunerun.sh once)"; exit 2; }
mkdir -p "$RES"; rm -rf "$O"; mkdir -p "$O"
exec 9>$T/.heavy.lock; flock 9
echo "node $(hostname -s) arm $ARMN threads $TH timeout $TO env '${envs[*]-}' args '$*' load_before $(cut -d' ' -f1-3 /proc/loadavg) start $(date -Is)" > "$RES/run.info"
cat $ST/analysis.tdf $ST/analysis.tdf_bin > /dev/null
( unset LD_PRELOAD OMP_NUM_THREADS GOMP_CPU_AFFINITY; source "$ARM"; export LC_ALL=C
  cd "$O" && env ${envs[@]+"${envs[@]}"} /usr/bin/time -v -o time.log timeout -k 30 "$TO" "$SPX_BIN" -in $ST -out pseudo.mzML -threads $TH "$@" > e.log 2>&1 ); rc=$?
flock -u 9; exec 9>&-
echo "exit $rc end $(date -Is)" >> "$RES/run.info"
cp "$O/e.log" "$O/time.log" "$RES/" 2>/dev/null
nwin=$(grep -a -c '^  window [0-9]*/' "$O/e.log")
if [ $rc = 0 ]; then
  cnt=$(grep -a -m1 -o 'spectrumList count="[0-9]*"' "$O/pseudo.mzML" | grep -o '[0-9]*' | sed 's/^0*//')
  dg=$(python3 /ceph/ibmi/abi/oliver/spextract/tools/semantic_digest.py "$O/pseudo.mzML" | grep -o '[0-9a-f]\{16,\}' | head -1)
  v=DIFF; [ "$dg" = "$REFD" ] && v=MATCH
  echo "COMPLETED $dg $cnt $v windows_done=$nwin" > "$RES/verdict"
elif [ $rc = 124 ] || [ $rc = 137 ]; then
  echo "TIMEOUT rc=$rc windows_done=$nwin last='$(grep -a -v '^\s*$' "$O/e.log" | tail -1 | cut -c1-200)'" > "$RES/verdict"
else
  echo "FAILED rc=$rc windows_done=$nwin" > "$RES/verdict"
fi
rm -f "$O/pseudo.mzML"
cat "$RES/verdict"
