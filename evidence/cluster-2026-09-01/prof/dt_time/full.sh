#!/bin/bash
cd /scratch/kohlbach/diatracer
export LD_LIBRARY_PATH=/scratch/kohlbach/diatracer/ext/bruker
/usr/bin/time -v java -Xmx400G -Djna.tmpdir=/scratch/kohlbach/jnatmp -Djava.io.tmpdir=/scratch/kohlbach/jnatmp -Djna.library.path=/scratch/kohlbach/diatracer/ext/bruker   -jar /scratch/kohlbach/diatracer/diaTracer-2.2.1.jar -d /scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d -t 100 -w /scratch/kohlbach/prof/dt_time/wd_full -mC 0.3 -dI 0.01 -dR 3 -rM 500 -mF 1 -mO 0.1 -r 0   > /scratch/kohlbach/prof/dt_time/full.log 2>&1
echo "=== EXIT $? ==="
grep -iE "Elapsed .wall|Percent of CPU|Maximum resident" /scratch/kohlbach/prof/dt_time/full.log
ls -la /scratch/kohlbach/prof/dt_time/wd_full/*.mzML 2>/dev/null | awk "{print $5, $9}"
grep -m1 -oE "<spectrumList count=\"[0-9]+\"" /scratch/kohlbach/prof/dt_time/wd_full/*.mzML 2>/dev/null | head -1
echo DT_FULL_DONE
