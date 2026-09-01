#!/bin/bash
cd /scratch/kohlbach/diatracer
/usr/bin/time -v java -Xmx400G -jar /scratch/kohlbach/diatracer/diaTracer-2.2.1.jar -d /scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d > /scratch/kohlbach/prof/dt_time/dt.log 2>&1
echo "=== EXIT $? ==="
grep -iE "Elapsed .wall|Percent of CPU|Maximum resident|System time" /scratch/kohlbach/prof/dt_time/dt.log
ls -la /scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d/*diatracer*.mzML /scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d/../*S30*diatracer.mzML 2>/dev/null | awk "{print $5, $9}" | head -3
echo DT_TIME_DONE
