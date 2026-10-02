#!/bin/bash
# scalfix/review chain on ibminode06 (2026-10-01): the digest gate of the fixed arm, then the team-of-one admission
# runs (fixed arm must COMPLETE with the HeLa_22 reference digest; the unfixed arms are expected to TIME OUT).
#   usage: review_chain.sh <new arm> <old arm>     marker: $R/chain.DONE
set -u
NEW=${1:?new arm}; OLD=${2:?old arm}
TOP=/ceph/ibmi/abi/oliver/spextract/tune-2026-09-29; R=$TOP/scalfix/review; TL=$R/tools
echo "chain start $(date -Is) node $(hostname -s) new $NEW old $OLD" > $R/chain.info
bash $TL/gate.sh "$NEW" 1
echo "gate done $(date -Is)" >> $R/chain.info
# fixed arm: pipeline solo fallback (team of one under a 4-thread request) and the barrier path at one thread
bash $TL/repro.sh "$NEW" new_lim1_cap1 4 2400 OMP_THREAD_LIMIT=1 -- -perf:max_concurrent_windows 1
bash $TL/repro.sh "$NEW" new_t1_cap1   1 2400 -- -perf:max_concurrent_windows 1
# unfixed arms: the same two configurations, expected to hang at the second admission (hard limit 900 s)
bash $TL/repro.sh "$OLD"   old_lim1_cap1  4 900 OMP_THREAD_LIMIT=1 -- -perf:max_concurrent_windows 1
bash $TL/repro.sh rc-b-1   rcb1_t1_cap1   1 900 -- -perf:max_concurrent_windows 1
echo "chain end $(date -Is)" >> $R/chain.info
touch $R/chain.DONE
