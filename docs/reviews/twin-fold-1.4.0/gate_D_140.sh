#!/bin/bash
# [v1.4.0 gate 2026-09-21] Derived from gate_D_131.sh by asserted replacements, for the twin fold
# (assembly:twin_im_tolerance, default 0.005). R1/R2 run with the fold OFF and must reproduce the 1.3.x pins: nothing
# else changed. R3 runs the new defaults (no pin: it sets one); R3a (one tile), R3b (two cells per tile) and R3c
# (8 threads) must reproduce R3's digest: the fold keeps tile-grouping and thread invariance. Header: 17 spx: stamps.
# [v1.3.1 gate 2026-09-17] Derived from gate_D_130.sh by asserted replacements (derive_131.py), for the negative-C2
# fix (1.3.1): identical arms and pins; dataset D (patient data) is STAGED -- only analysis.tdf and analysis.tdf_bin,
# same basename -- into a 0700 directory inside the 0700 gate dir and removed before DRIVER_DONE (and on any exit);
# an out.mzML whose digest DIFFERS is kept (the v1.3.0rc1 references: /scratch/kohlbach/v1.3.0rc1_gate_D/R{1,2});
# every mzML arm asserts the spx:mz_calibration stamp tdf_table_modeltype1; the informational walls are v1.3.0rc1's.
# [v1.3.0 release gate 2026-09-15] Gates for DIAspeXtract on the PUBLISHED arm $1 (commit $2, binary sha256 $3; read only),
# dataset D on ibminode05 at -threads 100 under /usr/bin/time -v, back to back:
#   R1 -dnoise:ms1 false (8c1b047f)
#   R2 no extra arguments (e43672a0): header software name DIAspeXtract, no old-name token ([Ss]pe[Xx]tractor, so
#      SpeXtractor and DIAspeXtractor alike), 16 spx: stamps; tiles 3:1:2
#   R4 SPEXTRACTOR_DET=1, R5 DIASPEXTRACTOR_DET=1, R5b both old prefixes at once: refused before anything (nonzero exit,
#      message naming EVERY set variable and its DIASPEXTRACT_ name, no [det]
#      line, nothing written)
#   R6 -out <W>/out.mzpeak: exit 0 with the one-tile warning (V3-01) and an output file; no digest
# Derived 2026-09-15 from the 1.2.0 driver (ibminode05:/scratch/kohlbach/gate_D_120.sh) by asserted replacements
# (derive_130.py); the arm, its git rev and binary sha256 are arguments, so the rc and the final arm run the same file.
# Two corrections carried from the 1.2.0 audit (M9):
#   - the one-tile warning is written by writeLogWarn_, i.e. to STDERR; the RC driver grepped e.log (stdout) alone and
#     scored a real PASS as FAIL. It is grepped over e.log AND t.log here.
#   - every mzML arm records its output size in bytes, so the README's disk row can be checked against a measurement.
# Digest: the deployed semantic_digest.py after a byte comparison with the repo's bench/semantic_digest.py (uploaded to
# /scratch/kohlbach/<arm>_gate_ref); every out.mzML is deleted after digesting unless its arm is listed in KEEP_MZML.
set -u
ARM=${1:?usage: gate_D_130.sh ARM GIT BINARY_SHA256   (e.g. v1.3.1rc1 2b9ade4 <sha256 from the provenance>)}
WANT_GIT=${2:?git rev the provenance must carry}; WANT_BIN=${3:?binary sha256 the provenance must carry}
[[ $WANT_BIN =~ ^[0-9a-f]{64}$ ]] || { echo "REFUSED: WANT_BIN [$WANT_BIN] is not a sha256"; exit 2; }
G=/scratch/kohlbach/${ARM}_gate_D
A=/ceph/ibmi/abi/oliver/spextract/$ARM
BIN=$A/bin/diaspextract
P=$A/bin/diaspextract.provenance
KEEP_MZML=${KEEP_MZML:-}   # arm names whose out.mzML is kept (the e43672a0 reference exists on data: agxt_semi/S30/spx/pseudo.mzML)
REPO_DIGEST=/scratch/kohlbach/${ARM}_gate_ref/semantic_digest.repo.py
WANT_TOOL=${WANT_TOOL:-16561042aa1f75f98a967d28a98b07c03555d7b65e53c37d7f9586dd273f23a7}   # bench/semantic_digest.py at 91a1b28; override if the
                                                                                            # rename touched it (the cmp with the uploaded repo copy is the real check)
source /ceph/ibmi/abi/oliver/spextract/env.sh
T=$SPX/tools
for v in $(compgen -e); do case $v in SPEXTRACTOR_*|DIASPEXTRACTOR_*|DIASPEXTRACT_*) unset "$v";; esac; done
unset OPENMS_BRUKER_SDK_PATH MALLOC_ARENA_MAX MALLOC_TRIM_THRESHOLD_ MALLOC_MMAP_THRESHOLD_ MALLOC_TOP_PAD_ GLIBC_TUNABLES
BASE_LD=${LD_LIBRARY_PATH:-}
echo "=== $ARM gate D $(date -Is) node $(hostname) load1 $(cut -d' ' -f1 /proc/loadavg) nproc $(nproc)"
fin() { [ -z "${ST:-}" ] || rm -rf "$ST"; echo "DRIVER_DONE $(date -Is)"; exit "$1"; }
[ -e $G ] && { echo "REFUSED: $G exists"; fin 6; }
mkdir -p -m 0700 $G && chmod 0700 $G && cp "$0" $G/driver.sh
grep -E "src_sha256|calibration_header_sha256|tool_headers_sha256|binary_sha256|libopenms_sha256|git=|built=|epd_patch_markers|masstrace_move_markers|dnoise_unit_test|tdf_load_unit_test" $P | sed 's/^/  /'
grep -qx "binary_sha256=$(sha256sum $BIN | cut -d' ' -f1)" $P || { echo "REFUSED: $BIN != provenance binary_sha256"; fin 6; }
grep -qx "libopenms_sha256=$(sha256sum $A/lib/libOpenMS.so | cut -d' ' -f1)" $P || { echo "REFUSED: $A/lib/libOpenMS.so != provenance"; fin 6; }
grep -qx "git=$WANT_GIT" $P || { echo "REFUSED: $P git != $WANT_GIT"; fin 6; }
grep -qx "binary_sha256=$WANT_BIN" $P || { echo "REFUSED: $P binary_sha256 != $WANT_BIN"; fin 6; }
{ grep -qx "dnoise_unit_test=passed" $P && grep -qx "tdf_load_unit_test=passed" $P; } || { echo "REFUSED: $A unit tests not passed"; fin 6; }
grep -qx "export SPX_BIN=$A/bin/diaspextract" $A/env.sh || { echo "REFUSED: $A/env.sh does not export SPX_BIN=$A/bin/diaspextract"; fin 6; }
sha256sum $BIN $A/lib/libOpenMS.so $A/lib/libOpenSwathAlgo.so | sed 's/^/  /'
LD_LIBRARY_PATH=$A/lib:$BASE_LD ldd $BIN | grep -E "libOpenMS|libOpenSwathAlgo|not found" | sed 's/^[[:space:]]*/  ldd /'
strings $A/lib/libOpenMS.so > $G/libstrings.txt
LS_NEW=$(grep -c 'DIASPEXTRACT_' $G/libstrings.txt); LS_DIAOLD=$(grep -c 'DIASPEXTRACTOR_' $G/libstrings.txt); LS_OLD=$(grep -c -E '(^|[^A])SPEXTRACTOR_' $G/libstrings.txt); LS_NS=$(grep -c 'diaspextract' $G/libstrings.txt); LS_NSOLD=$(grep -c 'diaspextractor' $G/libstrings.txt); rm -f $G/libstrings.txt
echo "  libOpenMS.so strings: DIASPEXTRACT_ $LS_NEW, old DIASPEXTRACTOR_ $LS_DIAOLD, old SPEXTRACTOR_ $LS_OLD, diaspextract tokens $LS_NS (diaspextractor $LS_NSOLD)"
{ [ "$LS_NEW" -ge 3 ] && [ "$LS_DIAOLD" -eq 0 ] && [ "$LS_OLD" -eq 0 ] && [ "$LS_NSOLD" -eq 0 ] && [ "$LS_NS" -ge 1 ]; } || { echo "REFUSED: $A/lib/libOpenMS.so does not carry the renamed getenv names / namespace only"; fin 6; }
LD_LIBRARY_PATH=$A/lib:$BASE_LD $BIN --help 2>&1 | head -3 | cut -c1-200 | sed 's/^/  help| /'
cmp -s $T/semantic_digest.py $REPO_DIGEST || { echo "REFUSED: $T/semantic_digest.py differs from the repo's bench/semantic_digest.py ($REPO_DIGEST)"; fin 6; }
TS=$(sha256sum $T/semantic_digest.py | cut -d' ' -f1)
[ "$TS" = "$WANT_TOOL" ] || { echo "REFUSED: $T/semantic_digest.py $TS != $WANT_TOOL"; fin 6; }
echo "  $T/semantic_digest.py == repo bench/semantic_digest.py (cmp), sha256 $TS"
SRC=/ceph/ibmi/abi/data/2026_AGXT_PH1_liver_diaPASEF/raw_d/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d
[ -e "$SRC/analysis.tdf" ] && [ -e "$SRC/analysis.tdf_bin" ] || { echo "REFUSED: dataset D's analysis.tdf/analysis.tdf_bin not found"; fin 6; }
# [1.3.1] patient data: only the two files every arm reads, in a 0700 directory, removed before DRIVER_DONE and on any exit
ST=$G/stage
mkdir -m 0700 "$ST" || { echo "REFUSED: cannot create the stage dir"; ST=""; fin 6; }
trap '[ -z "${ST:-}" ] || rm -rf "$ST"' EXIT
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
IN=$ST/$(basename "$SRC")
t0=$(date +%s)
{ mkdir -m 0700 "$IN" && cp "$SRC/analysis.tdf" "$SRC/analysis.tdf_bin" "$IN/"; } || { echo "REFUSED: staging dataset D failed"; fin 6; }
cmp -s "$SRC/analysis.tdf" "$IN/analysis.tdf" && [ "$(stat -c %s "$SRC/analysis.tdf_bin")" = "$(stat -c %s "$IN/analysis.tdf_bin")" ] || { echo "REFUSED: the staged copy differs from the source"; fin 6; }
echo "  staged dataset D: analysis.tdf (cmp equal) + analysis.tdf_bin (size equal), $(du -sb "$IN" | cut -f1) bytes, dir mode $(stat -c %a "$ST")/$(stat -c %a "$IN"), $(ls -A "$IN" | wc -l) files, $(( $(date +%s) - t0 )) s (the copy is the pre-warm read)"
MARK='error|refus|exception|invalid value|invalid parameter|runs without MS1 denoising|never reached the filter|reached the filter twice'
SUMMARY=()
V=$G/values.tsv
wsec() { awk -F: '{ if (NF==3) printf "%.2f", $1*3600+$2*60+$3; else if (NF==2) printf "%.2f", $1*60+$2; else printf "NA" }' <<< "$1"; }
stampre='spx:tile[a-z_]*"[^>]*value="[^"]*"'

arm() {   # name want(- = no pin) tile-spec(TILES:CELLS_PER_TILE:TILE_TRIMS, - = report only) check(-|header|det) "env assignments" tool-args...
  local name=$1 want=$2 spec=$3 chk=$4 ev=$5; shift 5
  local W=$G/$name
  [ -e "$W" ] && { echo "REFUSED: $W exists"; SUMMARY+=("$name REFUSED"); return 1; }
  mkdir -p "$W" && cd "$W" || return 9
  echo "--- $name $(date -Is) load1 $(cut -d' ' -f1 /proc/loadavg) MemAvailable $(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo) GB threads ${ARM_THREADS:-100} env [$ev] args [$*]"
  env LD_LIBRARY_PATH="$A/lib:$BASE_LD" $ev /usr/bin/time -v $BIN -in "$IN" -out "$W/out.mzML" -threads ${ARM_THREADS:-100} "$@" > e.log 2> t.log; local rc=$?
  echo "  diaspextract exit $rc (load1 after $(cut -d' ' -f1 /proc/loadavg))"
  grep -a -E "Maximum resident|Elapsed \(wall|Exit status|signal" t.log | sed 's/^[[:space:]]*/  /'
  local kb wall ws; kb=$(grep -a "Maximum resident" t.log | grep -o '[0-9]*$'); wall=$(grep -a "Elapsed (wall" t.log | awk '{print $NF}'); ws=$(wsec "$wall")
  grep -a "\[dnoise\]" e.log | cut -c1-520 | sed 's/^/  /'
  grep -a -E "\[perf\] (LOAD|WINDOW_LOOP|TOTAL)|\[ms1-prune\] picked|\[stream\] frame-by-frame|streaming load failed|resident source takes over|Split into MS1|\[tile\] [0-9]+ tile\(s\)|\[tile\] [0-9]+/[0-9]+: [0-9]+ spectra written|\[tile\] coverage|\[trim\]|Wrote [0-9]+ pseudo" e.log | cut -c1-420 | sed 's/^/  /'
  local nerr; nerr=$(grep -a -h -v "Command being timed" e.log t.log | grep -a -i -c -E "$MARK")
  grep -a -h -v "Command being timed" e.log t.log | grep -a -i -E "$MARK" | head -5 | cut -c1-420 | sed 's/^/  ERR /'
  local cal=NONE ncal=0 d=NONE ok=1 tok=- hok=- dok=- stamps="" n="" mzml_bytes=0
  [ "$rc" -eq 0 ] || ok=0
  [ "$nerr" -eq 0 ] || ok=0
  if [ -s "$W/out.mzML" ]; then
    stamps=$(head -c 8000000 "$W/out.mzML" | grep -a -o "$stampre" | sed -E 's/"[^>]*value="([^"]*)"$/=\1/')
    [ -n "$stamps" ] || stamps=$(grep -a -o "$stampre" "$W/out.mzML" | sed -E 's/"[^>]*value="([^"]*)"$/=\1/')
    printf '%s\n' "$stamps" | cut -c1-300 | sed 's/^/  stamp /'
    if [ "$chk" = header ]; then
      local off sw dian oldn nkeys keys
      off=$(head -c 8000000 "$W/out.mzML" | grep -a -b -o -m1 '<spectrumList' | head -1 | cut -d: -f1)
      head -c "${off:-0}" "$W/out.mzML" > "$W/header.xml"
      sw=$(grep -a -o 'accession="MS:1000799"[^>]*value="[^"]*"' "$W/header.xml" | sed 's/.*value="//; s/"$//' | sort | uniq -c | tr -s ' ' | tr '\n' ';')
      dian=$(grep -a -c 'value="DIAspeXtract"' "$W/header.xml")
      oldn=$(grep -a -o -E '[Ss]pe[Xx]tractor' "$W/header.xml" | wc -l)
      nkeys=$(grep -a -o 'name="spx:[A-Za-z0-9_]*"' "$W/header.xml" | sort -u | wc -l)
      keys=$(grep -a -o 'name="spx:[A-Za-z0-9_]*"' "$W/header.xml" | sed 's/^name="//; s/"$//' | sort -u | tr '\n' ' ')
      echo "  header: ${off:-NA} bytes before <spectrumList; software cvParam MS:1000799 [$sw]; value=\"DIAspeXtract\" lines $dian; old tool-name tokens $oldn; spx: keys $nkeys [$keys]"
      grep -a -o -E '.{0,60}[Ss]pe[Xx]tractor.{0,60}' "$W/header.xml" | head -3 | sed 's/^/  OLD /'
      if [ -n "$off" ] && [ "$dian" -ge 1 ] && [ "$oldn" -eq 0 ] && [ "$nkeys" -eq 17 ]; then hok=PASS; else hok=FAIL; ok=0; fi
      echo "  header evidence (DIAspeXtract named, no old-name token, exactly 17 spx: stamps): $hok"
    fi
    d=$(python3 $T/semantic_digest.py "$W/out.mzML" | cut -c1-16)
    if [ "$want" = "-" ]; then echo "  digest $d (no pin)"; else echo "  digest $d $([ "${d:0:8}" = "$want" ] && echo "== $want PASS" || echo "!= $want FAIL")"; [ "${d:0:8}" = "$want" ] || ok=0; fi
    n=$(grep -a -o -m1 '<spectrumList count="[0-9]*"' "$W/out.mzML" | sed 's/[^0-9]//g; s/^0*//')
    mzml_bytes=$(stat -c %s "$W/out.mzML")
    echo "  spectra $n; mzML $mzml_bytes bytes"
    # [1.3.1] the m/z model the loader used: the header stamp must name the MzCalibration table model
    cal=$(head -c 8000000 "$W/out.mzML" | grep -a -o 'spx:mz_calibration"[^>]*value="[^"]*"' | head -1 | sed 's/.*value="//; s/"$//')
    ncal=$(cat e.log t.log | grep -a -c 'TOF m/z calibration: TDF MzCalibration table model')
    echo "  calibration: stamp spx:mz_calibration=[$cal]; loader lines 'TOF m/z calibration: TDF MzCalibration table model' $ncal"
    [ "$cal" = tdf_table_modeltype1 ] || { echo "  calibration stamp is not tdf_table_modeltype1: FAIL"; ok=0; }
  else
    echo "  digest NONE: no output FAIL"; ok=0
  fi
  if [ "$want" != "-" ] && [ -s "$W/out.mzML" ] && [ "${d:0:8}" != "$want" ]; then
    echo "  kept $W/out.mzML: its digest DIFFERS (mzml_specdiff.py against the v1.3.0rc1 reference)"
  else
    case " $KEEP_MZML " in *" $name "*) echo "  kept $W/out.mzML (KEEP_MZML)";;
      *) rm -f "$W/out.mzML" "$W"/out.mzML.part*;; esac
  fi
  if [ "$chk" = det ]; then
    local ndet; ndet=$(grep -a -c '\[det\]' e.log)
    grep -a '\[det\]' e.log | head -4 | cut -c1-240 | sed 's/^/  /'
    if [ "$ndet" -gt 0 ]; then dok=PASS; else dok=FAIL; ok=0; fi
    echo "  [det] lines $ndet: $dok"
  fi
  local st sc sr lt ntr
  st=$(printf '%s\n' "$stamps" | sed -n 's/^spx:tiles=//p' | head -1)
  sc=$(printf '%s\n' "$stamps" | sed -n 's/^spx:tile_cells_per_tile=//p' | head -1)
  sr=$(printf '%s\n' "$stamps" | sed -n 's/^spx:tile_rt_sec=//p' | head -1)
  lt=$(grep -a -o -m1 '\[tile\] [0-9]* tile(s) of up to [0-9]* cell(s)' e.log | sed 's/^\[tile\] //')
  ntr=$(grep -a -c '\[trim\] tile [0-9]*/[0-9]*:' e.log)
  echo "  tiles: stamp tiles=[$st] cells_per_tile=[$sc] rt_sec=[$sr]; plan line [$lt]; [trim] lines between tiles $ntr"
  if [ "$spec" != "-" ]; then
    local wt wc wtr; IFS=: read -r wt wc wtr <<< "$spec"
    if [ "$st" = "$wt" ] && [ "$sc" = "$wc" ] && awk -v r="$sr" 'BEGIN{exit !(r != "" && r+0 == 600)}' && [ "${lt%% *}" = "$wt" ] && [ "$ntr" = "$wtr" ]; then tok=PASS; else tok=FAIL; ok=0; fi
    echo "  tile evidence want tiles=$wt cells_per_tile=$wc rt_sec=600 trims-between-tiles=$wtr: $tok"
  fi
  local v; [ $ok -eq 1 ] && v=PASS || v=FAIL
  echo "  VERDICT $name want=$want digest=$d spectra=$n bytes=$mzml_bytes exit=$rc err_lines=$nerr peak_kb=$kb wall=$wall tiles=$tok header=$hok det=$dok $v"
  printf -v "DIG_$name" '%s' "$d"
  SUMMARY+=("$name want=$want digest=$d spectra=$n bytes=$mzml_bytes exit=$rc err_lines=$nerr peak_kb=$kb wall=$wall tiles=$tok header=$hok det=$dok $v")
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$want" "$d" "$rc" "$nerr" "${kb:-NA}" "${ws:-NA}" "$tok" "$v" >> $V
  cd $G
}

refused_env() {   # name "env assignments": the binary must refuse before doing anything
  local name=$1 ev=$2
  local W=$G/$name
  [ -e "$W" ] && { echo "REFUSED: $W exists"; SUMMARY+=("$name REFUSED"); return 1; }
  mkdir -p "$W" && cd "$W" || return 9
  echo "--- $name $(date -Is) load1 $(cut -d' ' -f1 /proc/loadavg) env [$ev] args [-in D -out $W/out.mzML -threads 100]: must be refused before anything"
  local t0; t0=$(date +%s%N)
  env LD_LIBRARY_PATH="$A/lib:$BASE_LD" $ev $BIN -in "$IN" -out "$W/out.mzML" -threads 100 > e.log 2>&1; local rc=$?
  local ms=$(( ($(date +%s%N) - t0) / 1000000 ))
  echo "  diaspextract exit $rc after $ms ms"
  head -8 e.log | cut -c1-400 | sed 's/^/  | /'
  local ok=1 outs named=absent ndet
  outs=$(ls -A "$W" | grep -v -x 'e\.log' | tr '\n' ' ')
  [ "$rc" -ne 0 ] || ok=0
  [ -z "$outs" ] || ok=0
  named=present; local a v n
  for a in $ev; do v=${a%%=*}; n=DIASPEXTRACT_${v#*_}   # both old prefixes end at the first underscore
    case $v in DIA*) grep -a -q "$v" e.log || named=absent;; *) grep -a -q -E "(^|[^A])$v" e.log || named=absent;; esac
    grep -a -q "$n" e.log || named=absent
  done
  [ "$named" = present ] || ok=0
  ndet=$(grep -a -c '\[det\]' e.log); [ "$ndet" -eq 0 ] || ok=0
  local v; [ $ok -eq 1 ] && v=PASS || v=FAIL
  echo "  VERDICT $name exit=$rc outputs=[$outs] message(each variable + its DIASPEXTRACT_ name)=$named det_lines=$ndet ms=$ms $v"
  SUMMARY+=("$name exit=$rc outputs=[$outs] message=$named det_lines=$ndet ms=$ms $v")
  cd $G
}

mzpeak() {   # name: -out <W>/out.mzpeak at the defaults
  local name=$1
  local W=$G/$name
  [ -e "$W" ] && { echo "REFUSED: $W exists"; SUMMARY+=("$name REFUSED"); return 1; }
  mkdir -p "$W" && cd "$W" || return 9
  echo "--- $name $(date -Is) load1 $(cut -d' ' -f1 /proc/loadavg) MemAvailable $(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo) GB args [-out $W/out.mzpeak]"
  env LD_LIBRARY_PATH="$A/lib:$BASE_LD" /usr/bin/time -v $BIN -in "$IN" -out "$W/out.mzpeak" -threads 100 > e.log 2> t.log; local rc=$?
  echo "  diaspextract exit $rc (load1 after $(cut -d' ' -f1 /proc/loadavg))"
  grep -a -E "Maximum resident|Elapsed \(wall|Exit status|signal" t.log | sed 's/^[[:space:]]*/  /'
  local kb wall; kb=$(grep -a "Maximum resident" t.log | grep -o '[0-9]*$'); wall=$(grep -a "Elapsed (wall" t.log | awk '{print $NF}')
  grep -a -i -E "\[tile\]|mzpeak|Wrote [0-9]+|\[perf\] (LOAD|WINDOW_LOOP|TOTAL)|warn" e.log | cut -c1-420 | head -20 | sed 's/^/  /'
  local nerr warn sz=0 nw
  nerr=$(grep -a -h -v "Command being timed" e.log t.log | grep -a -i -c -E "$MARK")
  grep -a -h -v "Command being timed" e.log t.log | grep -a -i -E "$MARK" | head -5 | cut -c1-420 | sed 's/^/  ERR /'
  warn=$(cat e.log t.log | grep -a -c '\[tile\] mzPeak output is written in one piece')   # writeLogWarn_ -> stderr (t.log)
  [ -e "$W/out.mzpeak" ] && sz=$(du -sb "$W/out.mzpeak" | cut -f1)
  nw=$(grep -a -o -m1 'Wrote [0-9]* pseudo' e.log | grep -o '[0-9]*')
  local ok=1; [ "$rc" -eq 0 ] || ok=0; [ "$warn" -ge 1 ] || ok=0; [ "$sz" -gt 0 ] || ok=0; [ "$nerr" -eq 0 ] || ok=0
  echo "  one-tile warning lines $warn (e.log+t.log); output $sz bytes; Wrote $nw (the mzML arms write 496722); no digest (mzPeak)"
  rm -rf "$W/out.mzpeak" "$W"/out.mzpeak.*
  local v; [ $ok -eq 1 ] && v=PASS || v=FAIL
  echo "  VERDICT $name exit=$rc warning=$warn bytes=$sz spectra=$nw err_lines=$nerr peak_kb=$kb wall=$wall $v"
  SUMMARY+=("$name exit=$rc warning=$warn bytes=$sz spectra=$nw err_lines=$nerr peak_kb=$kb wall=$wall $v")
  cd $G
}

arm R1 8c1b047f 3:1:2 -      "" -dnoise:ms1 false -assembly:twin_im_tolerance -1
arm R2 e43672a0 3:1:2 header "" -assembly:twin_im_tolerance -1
arm R3 -        3:1:2 header ""
arm R3a "${DIG_R3:0:8}" - - "" -tile:cells_per_tile 0
arm R3b "${DIG_R3:0:8}" - - "" -tile:cells_per_tile 2
ARM_THREADS=8 arm R3c "${DIG_R3:0:8}" - - ""
refused_env R4 "SPEXTRACTOR_DET=1"
refused_env R5 "DIASPEXTRACTOR_DET=1"
refused_env R5b "SPEXTRACTOR_LEDGER=x DIASPEXTRACTOR_TILE_RESIDENT=1"
mzpeak R6

echo "=== reference (v1.3.0rc1 on this node, 2026-09-15 13:13-13:25, D read from ceph then; informational): R1 25463192 kB 3:44.35; R2 21992852 kB 3:19.24; R6 37340076 kB 3:16.21"
echo "=== SUMMARY"
for s in "${SUMMARY[@]}"; do echo "  $s"; done
rm -rf "$ST"; echo "  stage dir removed: $([ -e "$ST" ] && echo NO || echo yes)"; ST=""
echo "DRIVER_DONE $(date -Is)"
