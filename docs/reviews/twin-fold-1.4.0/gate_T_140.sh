#!/bin/bash
# [v1.4.0 gate 2026-09-21] Derived from gate_T_131.sh by asserted replacements, for the twin fold
# (assembly:twin_im_tolerance, default 0.005). S1/S2 run with the fold OFF and must reproduce the 1.3.x pins: nothing
# else changed. S3 runs the new defaults (no pin: it sets one); S3a (one tile) must reproduce S3's digest: the fold keeps tile-grouping and thread invariance. Header: 17 spx: stamps.
# [v1.3.1 gate 2026-09-17] Derived from gate_T_130.sh by asserted replacements (derive_131.py), for the negative-C2
# fix (1.3.1): identical arms and pins; no out.mzML is kept by default (the 3aafd0b5 reference is
# /scratch/kohlbach/v1.3.0rc1_gate_T/S2/out.mzML), but one whose digest DIFFERS is; every mzML arm asserts the
# spx:mz_calibration stamp tdf_table_modeltype1; the informational RSS/walls are v1.3.0rc1's on this node (spock carries
# foreign load: walls are not comparable).
# [v1.3.0 release gate 2026-09-15] TNBC 009 gates on the PUBLISHED arm $1 (commit $2, binary sha256 $3; read only), spock, -threads 100 under
# /usr/bin/time -v, back to back:
#   S1 -dnoise:ms1 false (bff54a1f)
#   S2 no extra arguments (3aafd0b5): tiles 13:1:12, header software name DIAspeXtract (no old-name token) with spx: stamps; peak RSS against
#      v1.2.0 S2 on this node (21105728 kB, S1 9:19 / S2 8:36, 2026-09-11 08:24-08:35). S2's out.mzML is KEPT by default:
#      no retained 3aafd0b5 reference exists anywhere (the 1.2.0 drivers deleted theirs), and a DIFFERS needs one to specdiff against.
# Derived 2026-09-15 from the 1.2.0 TNBC driver (spock, the v1.2.0 gate's driver.sh) by asserted replacements (derive_130.py);
# arm, git rev and binary sha256 are arguments. Every mzML arm also records its output size in bytes (1.2.0 audit, README disk row). Digest: the deployed semantic_digest.py after a byte comparison with the repo's
# bench/semantic_digest.py (uploaded to /scratch/kohlbach/<arm>_gate_ref); every out.mzML is deleted after digesting unless its arm is in KEEP_MZML.
set -u
ARM=${1:?usage: gate_T_130.sh ARM GIT BINARY_SHA256   (e.g. v1.3.1rc1 2b9ade4 <sha256 from the provenance>)}
WANT_GIT=${2:?git rev the provenance must carry}; WANT_BIN=${3:?binary sha256 the provenance must carry}
[[ $WANT_BIN =~ ^[0-9a-f]{64}$ ]] || { echo "REFUSED: WANT_BIN [$WANT_BIN] is not a sha256"; exit 2; }
G=/scratch/kohlbach/${ARM}_gate_T
A=/ceph/ibmi/abi/oliver/spextract/$ARM
BIN=$A/bin/diaspextract
P=$A/bin/diaspextract.provenance
KEEP_MZML=${KEEP_MZML:-}   # arm names whose out.mzML is kept (the 3aafd0b5 reference exists: v1.3.0rc1_gate_T/S2; a DIFFERS output is kept anyway)
REPO_DIGEST=/scratch/kohlbach/${ARM}_gate_ref/semantic_digest.repo.py
WANT_TOOL=${WANT_TOOL:-16561042aa1f75f98a967d28a98b07c03555d7b65e53c37d7f9586dd273f23a7}   # bench/semantic_digest.py at 91a1b28; the cmp is the real check
REF_S2_KB=21073004   # v1.3.0rc1 S2 on spock, 2026-09-15
source /ceph/ibmi/abi/oliver/spextract/env.sh
T=$SPX/tools
for v in $(compgen -e); do case $v in SPEXTRACTOR_*|DIASPEXTRACTOR_*|DIASPEXTRACT_*) unset "$v";; esac; done
unset OPENMS_BRUKER_SDK_PATH MALLOC_ARENA_MAX MALLOC_TRIM_THRESHOLD_ MALLOC_MMAP_THRESHOLD_ MALLOC_TOP_PAD_ GLIBC_TUNABLES
BASE_LD=${LD_LIBRARY_PATH:-}
echo "=== $ARM gate TNBC $(date -Is) node $(hostname) load1 $(cut -d' ' -f1 /proc/loadavg) nproc $(nproc)"
fin() { echo "DRIVER_DONE $(date -Is)"; exit "$1"; }
[ -e $G ] && { echo "REFUSED: $G exists"; fin 6; }
mkdir -p $G && cp "$0" $G/driver.sh
grep -E "src_sha256|calibration_header_sha256|tool_headers_sha256|binary_sha256|libopenms_sha256|git=|built=|epd_patch_markers|masstrace_move_markers|dnoise_unit_test|tdf_load_unit_test" $P | sed 's/^/  /'
grep -qx "binary_sha256=$(sha256sum $BIN | cut -d' ' -f1)" $P || { echo "REFUSED: $BIN != provenance binary_sha256"; fin 6; }
grep -qx "libopenms_sha256=$(sha256sum $A/lib/libOpenMS.so | cut -d' ' -f1)" $P || { echo "REFUSED: $A/lib/libOpenMS.so != provenance"; fin 6; }
grep -qx "git=$WANT_GIT" $P || { echo "REFUSED: $P git != $WANT_GIT"; fin 6; }
grep -qx "binary_sha256=$WANT_BIN" $P || { echo "REFUSED: $P binary_sha256 != $WANT_BIN"; fin 6; }
{ grep -qx "dnoise_unit_test=passed" $P && grep -qx "tdf_load_unit_test=passed" $P; } || { echo "REFUSED: $A unit tests not passed"; fin 6; }
grep -qx "export SPX_BIN=$A/bin/diaspextract" $A/env.sh || { echo "REFUSED: $A/env.sh does not export SPX_BIN=$A/bin/diaspextract"; fin 6; }
sha256sum $BIN $A/lib/libOpenMS.so $A/lib/libOpenSwathAlgo.so | sed 's/^/  /'
LD_LIBRARY_PATH=$A/lib:$BASE_LD ldd $BIN | grep -E "libOpenMS|libOpenSwathAlgo|not found" | sed 's/^[[:space:]]*/  ldd /'
cmp -s $T/semantic_digest.py $REPO_DIGEST || { echo "REFUSED: $T/semantic_digest.py differs from the repo's bench/semantic_digest.py ($REPO_DIGEST)"; fin 6; }
TS=$(sha256sum $T/semantic_digest.py | cut -d' ' -f1)
[ "$TS" = "$WANT_TOOL" ] || { echo "REFUSED: $T/semantic_digest.py $TS != $WANT_TOOL"; fin 6; }
echo "  $T/semantic_digest.py == repo bench/semantic_digest.py (cmp), sha256 $TS"
IN=/ceph/ibmi/abi/oliver/benchmark/PXD047793/raw/4223_TIMS2_009_2_Slot2-9_1_2883.d
[ -e "$IN/analysis.tdf" ] || { echo "REFUSED: no $IN/analysis.tdf"; fin 6; }
t0=$(date +%s); cat "$IN/analysis.tdf_bin" "$IN/analysis.tdf" > /dev/null; echo "  pre-warm read of TNBC 009: $(( $(date +%s) - t0 )) s"
MARK='error|refus|exception|invalid value|invalid parameter|runs without MS1 denoising|never reached the filter|reached the filter twice'
SUMMARY=()
V=$G/values.tsv
wsec() { awk -F: '{ if (NF==3) printf "%.2f", $1*3600+$2*60+$3; else if (NF==2) printf "%.2f", $1*60+$2; else printf "NA" }' <<< "$1"; }
stampre='spx:tile[a-z_]*"[^>]*value="[^"]*"'
arm() {   # name want tile-spec(TILES:CELLS_PER_TILE:TILE_TRIMS, - = report only) check(-|header) "env assignments" tool-args...
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
  grep -a -E "\[perf\] (LOAD|WINDOW_LOOP|TOTAL)|\[ms1-prune\] picked|\[stream\] frame-by-frame|streaming load failed|resident source takes over|Split into MS1|\[tile\] [0-9]+ tile\(s\)|\[tile\] coverage|Wrote [0-9]+ pseudo" e.log | cut -c1-420 | sed 's/^/  /'
  local nerr; nerr=$(grep -a -h -v "Command being timed" e.log t.log | grep -a -i -c -E "$MARK")
  grep -a -h -v "Command being timed" e.log t.log | grep -a -i -E "$MARK" | head -5 | cut -c1-420 | sed 's/^/  ERR /'
  local cal=NONE ncal=0 d=NONE ok=1 tok=- hok=- stamps="" n="" mzml_bytes=0
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
      if [ -n "$off" ] && [ "$dian" -ge 1 ] && [ "$oldn" -eq 0 ] && [ "$nkeys" -eq 17 ]; then hok=PASS; else hok=FAIL; ok=0; fi
      echo "  header evidence (DIAspeXtract named, no old-name token, spx: stamps present): $hok"
    fi
    d=$(python3 $T/semantic_digest.py "$W/out.mzML" | cut -c1-16)
    if [ "$want" = "-" ]; then echo "  digest $d (no pin)"; else echo "  digest $d $([ "${d:0:8}" = "$want" ] && echo "== $want PASS" || echo "!= $want FAIL")"; [ "${d:0:8}" = "$want" ] || ok=0; fi   # [1.4.0] the D driver's no-pin branch, missing here: S3 of the 2026-09-21 run was marked FAIL for "!= -" alone
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
  echo "  VERDICT $name want=$want digest=$d spectra=$n bytes=$mzml_bytes exit=$rc err_lines=$nerr peak_kb=$kb wall=$wall tiles=$tok header=$hok $v"
  printf -v "DIG_$name" '%s' "$d"
  SUMMARY+=("$name want=$want digest=$d spectra=$n bytes=$mzml_bytes exit=$rc err_lines=$nerr peak_kb=$kb wall=$wall tiles=$tok header=$hok $v")
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$want" "$d" "$rc" "$nerr" "${kb:-NA}" "${ws:-NA}" "$tok" "$v" >> $V
  cd $G
}

arm S1 bff54a1f 13:1:12 -      "" -dnoise:ms1 false -assembly:twin_im_tolerance -1
arm S2 3aafd0b5 13:1:12 header "" -assembly:twin_im_tolerance -1
arm S3 -        13:1:12 header ""
arm S3a "${DIG_S3:0:8}" - - "" -tile:cells_per_tile 0

echo "=== S2 peak RSS $(date -Is)"
awk -F'\t' -v ref=$REF_S2_KB '$1=="S2" { printf "  S2 peak %s kB (%.2f GB) vs v1.3.0rc1 S2 on spock %d kB (%.2f GB): %+.2f%%\n", $6, $6/1e6, ref, ref/1e6, 100*($6-ref)/ref }' $V
echo "=== reference (v1.3.0rc1 on this node, 2026-09-15 13:12-13:33, informational; foreign load differs): S1 28525076 kB 8:56.40; S2 21073004 kB 8:19.10"
echo "=== SUMMARY"
for s in "${SUMMARY[@]}"; do echo "  $s"; done
echo "DRIVER_DONE $(date -Is)"
