#!/bin/bash
cd /scratch/kohlbach/diatracer
export LD_LIBRARY_PATH=/scratch/kohlbach/diatracer/ext/bruker:$LD_LIBRARY_PATH
/usr/bin/time -v java -Xmx400G -Djna.library.path=/scratch/kohlbach/diatracer/ext/bruker -jar /scratch/kohlbach/diatracer/diaTracer-2.2.1.jar -d /scratch/kohlbach/rawd/FKL4341-S30-A-10_K25423-16-1_QKL29028AV_Slot1-19_1_1326.d > /scratch/kohlbach/prof/dt_time/dt2.log 2>&1
echo "EXIT $?"; grep -iE "Elapsed .wall|Percent of CPU|Maximum resident" /scratch/kohlbach/prof/dt_time/dt2.log
echo DT2_DONE
