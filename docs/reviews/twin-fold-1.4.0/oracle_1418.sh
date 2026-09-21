#!/bin/bash
# [v1.4.0 oracle 2026-09-21] The in-tool fold against the transformation that was priced, on PXD029836 run 1418:
#   OFF  -assembly:twin_im_tolerance -1 must reproduce the v1.3.1 spectra exactly (semantic digest of the kept
#        /scratch/kohlbach/isodup_pxd1418/pseudo.mzML, the extraction every arm of the study filtered);
#   ON   the defaults (0.005) must equal bench/twin_merge.py applied to that v1.3.1 file (--im=0.005 --drt=1.5),
#        spectrum for spectrum (mzml_specdiff.py: ids differ by construction, content must not).
#   then ON on both engines and under entrapment (the default had entrapment scored only at 0.01 before).
# Usage: oracle_1418.sh ARM
set -u
ARM=${1:?usage: oracle_1418.sh ARM}
A=/ceph/ibmi/abi/oliver/spextract/$ARM; S=/scratch/kohlbach/isodup_pxd1418; W=/scratch/kohlbach/${ARM}_oracle_1418
RAW=/ceph/ibmi/abi/data/PXD029836/raw_d/HeLa_P1_SDS_triplicate_dilution_series/20211103_PRO2_LS_01_MA_HeLa_200_SDC_NS_RE2_1_1418.d
T=/ceph/ibmi/abi/oliver/spextract/tools
[ -e "$W" ] && { echo "REFUSED: $W exists"; echo ORACLE_DONE; exit 6; }
mkdir -p "$W" && cd "$W" || exit 9
for v in $(compgen -e); do case $v in SPEXTRACTOR_*|DIASPEXTRACTOR_*|DIASPEXTRACT_*) unset "$v";; esac; done
source $A/env.sh
echo "=== $ARM oracle 1418 $(date -Is) node $(hostname) load1 $(cut -d' ' -f1 /proc/loadavg)"
$SPX_BIN --help 2>&1 | grep -a -m1 "^Version"
$SPX_BIN -in "$RAW" -out $W/off.mzML -threads 100 -assembly:twin_im_tolerance -1 > off.log 2>&1; echo "off rc=$? $(grep -a -o 'Wrote [0-9]* pseudo' off.log)"
$SPX_BIN -in "$RAW" -out $W/on.mzML -threads 100 > on.log 2>&1; echo "on rc=$? $(grep -a -o 'Wrote [0-9]* pseudo' on.log) | $(grep -a -o '\[twins\] [0-9]* spectra folded[^(]*' on.log | tail -1)"
python3 $S/twin_merge2.py $S/iso.tsv $S/pseudo.mzML $W/offline.mzML --im=0.005 --drt=1.5 > offline.log 2>&1; echo "offline rc=$? $(tail -1 offline.log)"
echo "--- OFF vs v1.3.1 (semantic digest)"
python3 $T/semantic_digest.py $W/off.mzML $S/pseudo.mzML; offd=$?
echo "--- ON vs the offline fold (per spectrum)"
python3 $T/mzml_specdiff.py $W/on.mzML $W/offline.mzML > specdiff.txt 2>&1; cat specdiff.txt
ident=$(awk '$1=="identical"{print $2}' specdiff.txt); tot=$(awk '/^spectra compared:/{print $3}' specdiff.txt)
echo "=== VERDICT off_identical_to_v131=$([ $offd -eq 0 ] && echo PASS || echo FAIL) on_equals_offline=$([ -n "$ident" ] && [ "$ident" = "$tot" ] && echo PASS || echo FAIL) ($ident of $tot identical)"
rm -f $W/off.mzML
echo "--- ON searched on both engines (the harness's pinned closed configs, corpus-v3 counting) and against entrapment"
bash $S/arm_search.sh tool005_$ARM $W/on.mzML
grep "^tool005_$ARM" $S/arms/counts.tsv | tail -1
$T/sage/sage $T/sage_entrap.json -o $W/entrap_on --disable-telemetry-i-dont-want-to-improve-sage $W/on.mzML > entrap.log 2>&1; echo "entrap sage rc=$?"
python3 $S/entrap_score.py $T/human_entrap.fasta full=$S/arms/entrap_full/results.sage.tsv tool005=$W/entrap_on/results.sage.tsv
echo ORACLE_DONE
