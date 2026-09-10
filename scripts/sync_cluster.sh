#!/bin/bash
# shellcheck disable=SC2086,SC2029  # INPUTS/SHIP are path lists split on purpose; the ssh commands expand locally on purpose
# Deploy src/spextractor.cpp to the cluster OpenMS tree, rebuild, record provenance.
# The ONLY sanctioned deploy path (2026-09-01 review, hardened per kimi F7/F8/F11 + codex #17-22; made a
# transaction 2026-09-10 per codex #3 / kimi #3 of the stage-2 review):
#   usage: scripts/sync_cluster.sh [node, default ibminode05] [--allow-dirty]
#   - refuses staged OR unstaged dirt (git status --porcelain), --allow-dirty to override
#   - every file is uploaded into a fresh mktemp stage dir: NOTHING shared is written before the remote lock
#   - under the lock, one node-side script: staged-bytes check, patch check, both unit tests (from the stage),
#     backup of every build input, promotion by rename, build, provenance hashed on the node
#   - any failure before the commit restores EVERY build input (touched, so make recompiles whatever the
#     failed build compiled against them); the old provenance comes back only if bin/spextractor AND
#     libOpenMS.so still match it (a failed build relinks libOpenMS.so first), else it is parked as .stale
#   - suite and bench tools ship only after a committed build; every deploy appended to deploys.log
#   - the node-side script writes only to its log: a dropped ssh channel cannot SIGPIPE it half-way
# tests/test_sync_cluster_txn.sh runs this script against a fake node (CI does, on Linux); run it after any change.
set -euo pipefail
cd "$(dirname "$0")/.."
NODE=${1:-ibminode05}
R=/scratch/kohlbach
TOOLS=/ceph/ibmi/abi/oliver/spextract/tools
TESTS=/ceph/ibmi/abi/oliver/spextract/tests
INPUTS="src/spextractor.cpp src/TdfMzCalibration.h src/TdfLoad.h src/MzPeakStreamLoad.h src/DnoiseMs1.h tests/test_dnoise_ms1.cpp tests/test_tdf_load.cpp"
# The e2e suite, its golden file (check 9 reads ../tests/calibration_golden.json), the gate chains'
# digest/diff tools and the remote launcher: each drifted once when it did not travel with the source.
SHIP="test/test_spextractor.py tests/calibration_golden.json bench/semantic_digest.py bench/mzml_specdiff.py bench/tile_concat.py bench/ledger_report.py bench/launch.sh"
for f in $INPUTS $SHIP; do [ -f "$f" ] || { echo "REFUSED: $f does not exist - nothing changed" >&2; exit 1; }; done
DIRT=$(git status --porcelain -- $INPUTS); DIRTY=""
if [ -n "$DIRT" ]; then
  [ "${2:-}" = "--allow-dirty" ] || { printf 'REFUSED: build inputs have staged or unstaged changes. Commit first, or pass --allow-dirty.\n%s\n' "$DIRT" >&2; exit 1; }
  DIRTY="+dirty"
fi
GITREV="$(git rev-parse --short HEAD)${DIRTY}"
TMP=$(mktemp -d); STAGE=""; HANDED=0
trap 'rm -rf "$TMP"; [ -z "$STAGE" ] || [ "$HANDED" = 1 ] || ssh "$NODE" "rm -rf $STAGE" || true' EXIT
shasum -a 256 $INPUTS $SHIP | sed 's#  .*/#  #' > "$TMP/SHA256SUMS"
cat > "$TMP/txn.sh" <<'TXN'
#!/bin/bash
# shellcheck disable=SC2086,SC2013  # FL, BUILD_INPUTS, PROMOTED and CXX_INCLUDES are word lists split on purpose
# Node-side deploy transaction written by scripts/sync_cluster.sh. Args: STAGE GITREV R TOOLS TESTS.
set -euo pipefail
S=$1; GITREV=$2; R=$3; TOOLS=$4; TESTS=$5
OMS=$R/OpenMS; BUILD=$OMS/build; TOPP=$OMS/src/topp; UT=$R/spextractor_unit; U=$S/unit
LOCK=$R/.deploy.lock; PROV=$BUILD/bin/spextractor.provenance
BUILD_INPUTS="spextractor.cpp TdfMzCalibration.h TdfLoad.h MzPeakStreamLoad.h DnoiseMs1.h"
# The calibration model is header-only and lives in this repo; the OpenMS patch includes it from the
# library's include dir. The tool's other headers live next to its source (a hand copy once drifted).
dest() { if [ "$1" = TdfMzCalibration.h ]; then echo "$OMS/src/openms/include/OpenMS/FORMAT/$1"; else echo "$TOPP/$1"; fi; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
finish() {
  rc=$?; set +e; trap '' HUP INT TERM   # a second signal must not abort the rollback half-way and strand the lock
  # The rename is the commit point, not the flag: a failed mv, or a signal between the two, leaves $PROV.tmp behind.
  if [ -e "$PROV.tmp" ]; then COMMITTED=0; rm -f "$PROV.tmp"; fi
  if [ "$COMMITTED" != 1 ]; then
    UNDONE=""
    for f in $PROMOTED; do
      d=$(dest "$f")
      if [ -e "$S/bak/$f" ]; then { mv -f "$S/bak/$f" "$d" && touch "$d"; } || UNDONE="$UNDONE $f"; else rm -f "$d" || UNDONE="$UNDONE $f"; fi
    done
    # every backed-up input must hold its backup's bytes again (a directory in a file's place swallows the mv)
    if [ -n "$PROMOTED" ] && [ -z "$UNDONE" ] && ! sha256sum -c --quiet "$S/restore.sha256"; then UNDONE=" (restore.sha256)"; fi
    if [ -n "$UNDONE" ]; then
      echo "FAIL-CLOSED: rollback incomplete for:$UNDONE; there is NO provenance. Kept the stage $S (bak/, prov.prev)" \
           "and the lock $LOCK: put the backups back by hand, then rm -rf $S and rmdir $LOCK."
      exit "$rc"
    fi
    [ -z "$PROMOTED" ] || echo "ROLLED BACK every promoted build input:$PROMOTED"
    if [ -e "$S/prov.prev" ]; then
      if grep -qx "binary_sha256=$(sha "$BUILD/bin/spextractor")" "$S/prov.prev" &&
         grep -qx "libopenms_sha256=$(sha "$BUILD/lib/libOpenMS.so")" "$S/prov.prev"; then
        mv -f "$S/prov.prev" "$PROV"; echo "bin/spextractor, libOpenMS.so and provenance unchanged"
      else
        mv -f "$S/prov.prev" "$PROV.stale"
        echo "FAIL-CLOSED: the failed build changed bin/spextractor or libOpenMS.so; there is NO provenance" \
             "(old one parked at $PROV.stale). Run make spextractor on the restored tree, or deploy again."
      fi
    fi
  elif [ "$rc" != 0 ]; then
    echo "COMMITTED (binary + provenance), but a post-commit step failed (rc $rc): suite/tools may be stale"
  fi
  rm -rf "$S"; rm -f "$LOCK/owner"; rmdir "$LOCK"
  exit "$rc"
}
trap 'rm -rf "$S"' EXIT
if ! mkdir "$LOCK" 2>/dev/null; then
  OWNER=$(cat "$LOCK/owner" 2>/dev/null || echo 'owner unknown'); OPID=$(sed -n 's/^.* pid \([0-9][0-9]*\) .*$/\1/p' "$LOCK/owner" 2>/dev/null || true)
  # a SIGKILLed, OOM-killed or rebooted transaction leaves the lock, and its stage holds what a recovery needs (bak/, prov.prev)
  if [ -n "$OPID" ] && ! kill -0 "$OPID" 2>/dev/null; then OWNER="$OWNER; that pid is NOT running: a killed deploy left the lock and its stage"; fi
  echo "REFUSED: another deploy holds $LOCK ($OWNER) - nothing changed"; exit 1
fi
COMMITTED=0; PROMOTED=""
trap finish EXIT
# Without these, a signal runs finish at once, while make is still writing bin/spextractor and libOpenMS.so, so
# the provenance check reads a binary the build then replaces. A trapped signal waits for the running command.
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
echo "$S pid $$ $(date -Is)" > "$LOCK/owner" || true
cd "$S"
sha256sum -c --quiet SHA256SUMS || { echo "REFUSED: staged files differ from the local ones - nothing changed"; exit 1; }
# Refuse a tree that has lost the calibration patch: it would build fine, silently revert masses to the
# -5..-11 ppm chord, and record a clean-looking provenance [kimi review].
grep -q TdfMzCalibration "$OMS/src/openms/source/FORMAT/BrukerTimsFile.cpp" || {
  echo "REFUSED: the cluster OpenMS tree has no calibration patch applied - nothing changed"
  echo "  run: scripts/apply_openms_patches.sh $OMS   (on the node)"; exit 1; }
# Both unit tests with the tool's own compiler and flags (test_dnoise_ms1 pins D's FMA-sensitive gate boxes),
# BEFORE anything is promoted. They compile in a copy of the repo layout made from the hash-checked staged files
# ($U/src, $U/tests, and $U/inc/OpenMS/FORMAT for the calibration header under the name the OpenMS patch installs):
# the very bytes renamed into the tree below and re-verified after the build. No tree header can stand in for
# them -- until the promotion the tree still holds the previous deploy's copies.
CXX=$(sed -n 's/^CMAKE_CXX_COMPILER:[A-Z]*=//p' "$BUILD/CMakeCache.txt")
FLAGS_MAKE=$BUILD/src/topp/CMakeFiles/spextractor.dir/flags.make
FL=$(sed -n 's/^CXX_FLAGS = //p' "$FLAGS_MAKE")
if [ -z "$CXX" ] || [ -z "$FL" ]; then
  echo "unit tests FAILED: no compiler [$CXX] or flags [$FL] in $BUILD - nothing promoted, tree unchanged"; exit 2
fi
mkdir -p "$U/src" "$U/tests" "$U/inc/OpenMS/FORMAT"
for f in $BUILD_INPUTS; do cp -p "$f" "$U/src/"; done
cp -p TdfMzCalibration.h "$U/inc/OpenMS/FORMAT/"
cp -p test_dnoise_ms1.cpp test_tdf_load.cpp "$U/tests/"
unit_failed() { cat "$U/$1.log"; echo "$1 unit test FAILED (compiler [$CXX] flags [$FL]) - nothing promoted, tree unchanged"; exit 2; }
# TMPDIR: whatever a test writes stays in the stage, which finish removes.
{ "$CXX" $FL -I"$U/src" -I"$U/inc" "$U/tests/test_dnoise_ms1.cpp" -o "$U/test_dnoise_ms1" &&
  TMPDIR=$U "$U/test_dnoise_ms1"; } > "$U/test_dnoise_ms1.log" 2>&1 || unit_failed test_dnoise_ms1
cat "$U/test_dnoise_ms1.log"
# test_tdf_load also needs SQLite: the sqlite3.h the tool compiles against (the first of its include dirs that has
# one; on the cluster OpenMS's bundled SQLite) and the static library libOpenMS.so is linked from, which is where
# the tool's sqlite3_* symbols come from. A node without either skips the test, and the provenance says so.
SQL_INC=""
for i in $(sed -n 's/^CXX_INCLUDES = //p' "$FLAGS_MAKE"); do
  if [ -z "$SQL_INC" ] && [ -f "${i#-I}/sqlite3.h" ]; then SQL_INC=${i#-I}; fi
done
SQL_LIB=$BUILD/lib/libsqlite3.a
if [ -z "$SQL_INC" ]; then
  TDF_UT="skipped(no sqlite3.h in the tool include dirs)"
elif [ ! -f "$SQL_LIB" ]; then
  TDF_UT="skipped(no $SQL_LIB)"
else
  { "$CXX" $FL -I"$U/src" -I"$U/inc" -I"$SQL_INC" "$U/tests/test_tdf_load.cpp" "$SQL_LIB" -lpthread -ldl -lm -o "$U/test_tdf_load" &&
    TMPDIR=$U "$U/test_tdf_load"; } > "$U/test_tdf_load.log" 2>&1 || unit_failed test_tdf_load
  cat "$U/test_tdf_load.log"; TDF_UT=passed
fi
if [ "$TDF_UT" != passed ]; then echo "tdf_load unit test SKIPPED: $TDF_UT" | tee "$U/test_tdf_load.log"; fi
mkdir "$S/bak"
for f in $BUILD_INPUTS; do d=$(dest "$f"); if [ -e "$d" ]; then cp -p "$d" "$S/bak/$f"; printf '%s  %s\n' "$(sha "$S/bak/$f")" "$d"; fi; done > "$S/restore.sha256"
for f in $BUILD_INPUTS; do printf '%s  %s\n' "$(awk -v f="$f" '$2 == f {print $1}' SHA256SUMS)" "$(dest "$f")"; done > promoted.sha256
# No provenance while the tree is in flux: a hard kill from here on leaves none rather than a stale one.
if [ -e "$PROV" ]; then mv -f "$PROV" "$S/prov.prev"; fi
for f in $BUILD_INPUTS; do
  PROMOTED="$PROMOTED $f"
  # rename within one filesystem; touch so the file is newer than every object of any earlier build
  d=$(dest "$f"); mv -f "$S/$f" "$d"; touch "$d"
done
BLOG=$R/build_sync_$(date +%Y%m%d-%H%M%S).log
if ! (cd "$BUILD" && make spextractor -j32) > "$BLOG" 2>&1 < /dev/null; then
  tail -n 20 "$BLOG"; echo "BUILD FAILED ($BLOG)"; exit 2
fi
# A writer outside the lock (a hand copy, a patch script) during the build would make the provenance a lie.
sha256sum -c --quiet promoted.sha256 || { echo "REFUSED: a build input changed during the build"; exit 2; }
cd "$BUILD"
HDRS_SHA=$(cat "$TOPP/TdfLoad.h" "$TOPP/MzPeakStreamLoad.h" "$TOPP/DnoiseMs1.h" | sha256sum | cut -d' ' -f1)
OMSVER=$(grep -m1 CF_OPENMS_PACKAGE_VERSION_FULLSTRING CMakeCache.txt | cut -d= -f2)
EPD=$OMS/src/openms/source/FEATUREFINDER/ElutionPeakDetection.cpp
printf 'src_sha256=%s\ncalibration_header_sha256=%s\ntool_headers_sha256=%s\ngit=%s\nbuilt=%s\nbinary_sha256=%s\nopenms=%s\nepd_sha256=%s\nepd_patch_markers=%s\nmasstrace_move_markers=%s\nlibopenms_sha256=%s\ndnoise_unit_test=passed\ntdf_load_unit_test=%s\n' \
  "$(sha "$TOPP/spextractor.cpp")" "$(sha "$(dest TdfMzCalibration.h)")" "$HDRS_SHA" "$GITREV" "$(date -Is)" \
  "$(sha bin/spextractor)" "$OMSVER" "$(sha "$EPD")" "$(grep -c 'SpeXtractor\|lock' "$EPD" || true)" \
  "$(grep -c 'MassTrace(MassTrace &&)' "$OMS/src/openms/include/OpenMS/KERNEL/MassTrace.h" || true)" \
  "$(sha lib/libOpenMS.so)" "$TDF_UT" > "$PROV.tmp"
COMMITTED=1; mv -f "$PROV.tmp" "$PROV"          # the commit point
cat "$PROV" >> "$R/deploys.log"; cat "$PROV"
if [ -e "$S/bak/spextractor.cpp" ]; then mv -f "$S/bak/spextractor.cpp" "$TOPP/spextractor.cpp.bak"; fi
mkdir -p "$UT" "$TESTS"
cp "$U/tests/test_dnoise_ms1.cpp" "$U/test_dnoise_ms1.log" "$U/tests/test_tdf_load.cpp" "$U/test_tdf_load.log" "$UT/"
cp "$S/test_spextractor.py" "$S/semantic_digest.py" "$S/mzml_specdiff.py" "$S/tile_concat.py" "$S/ledger_report.py" "$S/launch.sh" "$TOOLS/"
cp "$S/calibration_golden.json" "$TESTS/"
# 771 explicitly, not chmod +x: the tools dir carries a default ACL (default:group::rwx, other:---), so a file
# created by a redirect or a python write lands 0660 with NO exec bit regardless of umask -- which is how
# three drivers silently lost theirs on 2026-09-07.
chmod 771 "$TOOLS/launch.sh"
echo "DEPLOY COMMITTED"
TXN
STAGE=$(ssh "$NODE" "mktemp -d $R/.deploy.stage.XXXXXX")
case "$STAGE" in "$R"/.deploy.stage.??????) ;; *) echo "REFUSED: unexpected stage dir [$STAGE]" >&2; STAGE=""; exit 1;; esac
scp -q $INPUTS $SHIP "$TMP/SHA256SUMS" "$TMP/txn.sh" "$NODE:$STAGE/"
HANDED=1
echo "node-side transaction log: $NODE:$STAGE.log"
ssh "$NODE" "bash $STAGE/txn.sh $STAGE $GITREV $R $TOOLS $TESTS > $STAGE.log 2>&1 < /dev/null; rc=\$?; cat $STAGE.log; exit \$rc"
