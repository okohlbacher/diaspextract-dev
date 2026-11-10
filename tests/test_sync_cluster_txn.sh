#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2034,SC2086  # checks are single-quoted strings eval'd by ok(); fixture paths are mktemp dirs
# Transaction harness for scripts/sync_cluster.sh (stage-2 review, codex #3 / kimi #3). It runs the real script
# against a fake node through ssh/scp shims and never contacts a host: it aborts unless the shims come first on
# PATH and no real cluster path survives the substitution into its copy of the script.
# The fake node keeps what makes a deploy transaction hard on the real one: make decides by mtime, the Makefile
# generator relinks libOpenMS.so (which compiles the calibration header) before the tool compiles, a compile
# reads its inputs long before the build writes the binary, and the unit tests compile against whichever copy of
# a header the include path reaches first (each fake test fails unless it sees the staged copy).
#   bash tests/test_sync_cluster_txn.sh                              # scripts/sync_cluster.sh of this checkout
#   SYNC_SCRIPT=/tmp/mutant.sh bash tests/test_sync_cluster_txn.sh   # any other copy; a broken one must FAIL
# Needs git, make, ar and a C++ compiler; shims date -Is and sha256sum where the host lacks them (macOS).
set -uo pipefail
export LC_ALL=C   # deterministic sort; quiets perl's shasum on hosts whose locale is unset or invalid
HERE=$(cd "$(dirname "$0")/.." && pwd)
SCRIPT=${SYNC_SCRIPT:-$HERE/scripts/sync_cluster.sh}
[ -f "$SCRIPT" ] || { echo "ABORT: no $SCRIPT"; exit 99; }
V=$(mktemp -d "${TMPDIR:-/tmp}/sync_txn.XXXXXX") || exit 99
mkdir -p "$V/shim" "$V/ver"
PASS=0; FAIL=0
ok() { if eval "$2"; then echo "  ok   $1"; PASS=$((PASS+1)); else echo "  FAIL $1   [$2]"; FAIL=$((FAIL+1)); fi; }

cat > "$V/shim/ssh" <<'EOF'
#!/usr/bin/env bash
# ssh [opts] HOST CMD -> CMD, run here: the node paths in the script under test were rewritten into the fake node
while [ $# -gt 0 ]; do case $1 in -o) shift 2;; -*) shift;; *) break;; esac; done
shift
exec bash -c "$*"
EOF
cat > "$V/shim/scp" <<'EOF'
#!/usr/bin/env bash
# scp [-q] SRC... HOST:DIR -> cp; TORN=<name> then corrupts that file in DIR (a torn upload)
a=(); for x in "$@"; do [ "$x" = -q ] || a+=("$x"); done
n=${#a[@]}; dst=${a[n-1]}; dst=${dst#*:}; unset "a[n-1]"
cp "${a[@]}" "$dst" || exit 1
if [ -n "${TORN:-}" ] && [ -d "$dst" ] && [ -e "$dst/$TORN" ]; then printf 'x' >> "$dst/$TORN"; fi
EOF
chmod +x "$V/shim/ssh" "$V/shim/scp"
ln -s "$BASH" "$V/shim/bash"   # the "node" runs the transaction under the harness's own bash
if ! date -Is > /dev/null 2>&1; then   # BSD date
  printf '#!/usr/bin/env bash\nif [ "${1:-}" = -Is ]; then exec %s +%%Y-%%m-%%dT%%H:%%M:%%S%%z; fi\nexec %s "$@"\n' \
    "$(command -v date)" "$(command -v date)" > "$V/shim/date"
  chmod +x "$V/shim/date"
fi
if ! command -v sha256sum > /dev/null; then
  printf '#!/usr/bin/env bash\nexec shasum -a 256 "$@"\n' > "$V/shim/sha256sum"; chmod +x "$V/shim/sha256sum"
fi
export PATH=$V/shim:$PATH
for t in ssh scp bash; do
  [ "$(command -v $t)" = "$V/shim/$t" ] || { echo "ABORT: the $t shim is not first on PATH"; exit 99; }
done

set_flags() {  # yes|no: whether the tool's include path reaches a sqlite3.h (on the cluster: OpenMS's bundled SQLite)
  local sq=""; [ "$1" = yes ] && sq="-I$SQ "
  printf 'CXX_INCLUDES = -I%s/src/openms/extern/SQLiteCpp/include %s-I%s/src/openms/include -isystem %s/contrib/include\nCXX_FLAGS = -std=c++17 -O0\n' \
    "$O" "$sq" "$O" "$R" > $O/build/src/topp/CMakeFiles/diaspextract.dir/flags.make
}
mk_node() {
  N=$1; R=$N/scratch; TOOLS=$N/ceph/tools; TESTS=$N/ceph/tests; O=$R/OpenMS; PROV=$O/build/bin/diaspextract.provenance
  SQ=$O/src/openms/extern/SQLiteCpp/sqlite3
  mkdir -p $O/src/topp $O/src/openms/include/OpenMS/FORMAT $O/src/openms/include/OpenMS/KERNEL \
           $O/src/openms/source/FORMAT $O/src/openms/source/FEATUREFINDER $O/build/bin $O/build/lib \
           $O/build/src/topp/CMakeFiles/diaspextract.dir $SQ $TOOLS
  printf 'CMAKE_CXX_COMPILER:FILEPATH=%s\nCF_OPENMS_PACKAGE_VERSION_FULLSTRING:INTERNAL=3.5.0-fake\n' "$(command -v c++)" > $O/build/CMakeCache.txt
  set_flags yes
  printf '#include <OpenMS/FORMAT/TdfMzCalibration.h>\n' > $O/src/openms/source/FORMAT/BrukerTimsFile.cpp
  printf '// DIAspeXtract lock\n' > $O/src/openms/source/FEATUREFINDER/ElutionPeakDetection.cpp
  printf 'MassTrace(MassTrace &&) = default;\n' > $O/src/openms/include/OpenMS/KERNEL/MassTrace.h
  printf '0\n' > $O/slow
  # the bundled SQLite: its header in the tool's include path, the static library libOpenMS.so is linked from
  printf 'int fake_sqlite3_version();\n' > $SQ/sqlite3.h
  printf 'int fake_sqlite3_version() { return 3049002; }\n' > $V/fake_sqlite3.cpp
  { c++ -c $V/fake_sqlite3.cpp -o $V/fake_sqlite3.o && ar rcs $O/build/lib/libsqlite3.a $V/fake_sqlite3.o; } || { echo "ABORT: cannot build the fake SQLite"; exit 99; }
  # real make/mtime semantics; like CMake's Makefile generator, libOpenMS relinks before the tool compiles, and
  # the tool's compile reads its inputs before the (slow) rest of the build writes the binary. A failing compile
  # takes a second after the relink, as a real one does: make with 1 s timestamps (macOS make 3.81) would
  # otherwise see a header restored in the same second as no newer than the lib. And a successful build returns a
  # second after it wrote the binary: the next deploy would otherwise promote in that second, and make 3.81 would
  # call the tree up to date and do nothing.
  printf '%b\n' \
   'I=../src/openms/include/OpenMS/FORMAT/TdfMzCalibration.h' 'T=../src/topp' \
   'diaspextract: bin/diaspextract' \
   'lib/libOpenMS.so: $(I) ../src/openms/source/FORMAT/BrukerTimsFile.cpp' '\tcat $^ > $@' \
   'bin/diaspextract: lib/libOpenMS.so $(T)/diaspextract.cpp $(T)/TdfLoad.h $(T)/MzPeakStreamLoad.h $(T)/DnoiseMs1.h $(T)/NoImsPath.h $(T)/PortableMath.h' \
   '\tcat $^ > $@.part' \
   '\ttouch ../building; sleep $$(cat ../slow); rm -f ../building' \
   '\tif grep -q BREAK_BUILD $(T)/diaspextract.cpp; then sleep 1; echo "error: forced compile failure" >&2; exit 1; fi' \
   '\tmv -f $@.part $@' '\tsleep 1' '.PHONY: diaspextract' > $O/build/Makefile
}
install_script() {  # path-substituted copy; refuses if any real cluster path survives
  sed -e "s#/scratch/kohlbach#$R#g" -e "s#/ceph/ibmi/abi/oliver/spextract#$N/ceph#g" "$1" > "$2"
  if grep -n '/scratch/kohlbach\|/ceph/ibmi' "$2"; then echo "ABORT: real path survived in $2"; exit 98; fi
}
SHIPPED="test/test_diaspextract.py tests/calibration_golden.json bench/semantic_digest.py bench/mzml_specdiff.py bench/tile_concat.py bench/launch.sh"
mk_repo() {
  mkdir -p $1/src $1/tests $1/test $1/bench $1/scripts
  git -C $1 init -q && git -C $1 config user.email t@t && git -C $1 config user.name t && git -C $1 config commit.gpgsign false
  install_script "$2" $1/scripts/sync_cluster.sh
}
set_version() {  # repo tag calib dnoise_ok tdf_ok [cpp extra]
  local D=$1
  printf '// diaspextract %s\n%s\n' "$2" "${6:-}" > $D/src/diaspextract.cpp
  printf '#define CALIB_TAG "%s"\n' "$3" > $D/src/TdfMzCalibration.h
  printf '#define TDF_OK %s // TdfLoad %s\n' "$5" "$2" > $D/src/TdfLoad.h
  printf '// MzPeakStreamLoad %s\n' "$2" > $D/src/MzPeakStreamLoad.h
  printf '#define DNOISE_OK %s // %s\n' "$4" "$2" > $D/src/DnoiseMs1.h
  printf '// NoImsPath %s\n' "$2" > $D/src/NoImsPath.h
  printf '// PortableMath %s\n' "$2" > $D/src/PortableMath.h
  # both include forms the real tests may use; each test fails unless it compiled against the staged headers
  printf '#include "DnoiseMs1.h"\n#include <OpenMS/FORMAT/TdfMzCalibration.h>\n#include <cstring>\nint main() { return DNOISE_OK && !std::strcmp(CALIB_TAG, "%s") ? 0 : 1; } // %s\n' "$3" "$2" > $D/tests/test_dnoise_ms1.cpp
  printf '#include "TdfLoad.h"\n#include "../src/TdfMzCalibration.h"\n#include <sqlite3.h>\n#include <cstring>\nint main() { return TDF_OK && fake_sqlite3_version() == 3049002 && !std::strcmp(CALIB_TAG, "%s") ? 0 : 1; } // %s\n' "$3" "$2" > $D/tests/test_tdf_load.cpp
  for f in $SHIPPED; do printf '# %s %s\n' "$f" "$2" > $D/$f; done
  git -C $D add src tests test bench scripts && git -C $D commit -qm "$2"
  mkdir -p $V/ver/$2 && (cd $D && cp -R src tests test bench $V/ver/$2/) && git -C $D rev-parse --short HEAD > $V/ver/$2/REV
}
deploy() { local repo=$1 out=$2; shift 2; (cd "$repo" && bash scripts/sync_cluster.sh fakenode "$@") > "$out" 2>&1; echo $?; }
mt()   { stat -c %y "$1" 2> /dev/null || stat -f %Fm "$1"; }
snap() { (cd "$N" && find . \( -type f -o -type d \) ! -name '.deploy.stage.*.log' ! -name 'build_sync_*.log' | LC_ALL=C sort |
         while read -r f; do if [ -d "$f" ]; then echo "D $f"; else printf '%s %s %s\n' "$(shasum -a 256 "$f" | cut -c1-16)" "$(mt "$f")" "$f"; fi; done); }
same() { cmp -s "$1" "$2"; }
shaf() { shasum -a 256 "$1" | cut -d' ' -f1; }
pv()   { sed -n "s/^$1=//p" "$2"; }
tree_is() { local W=$V/ver/$1
  same $W/src/diaspextract.cpp $O/src/topp/diaspextract.cpp && same $W/src/TdfMzCalibration.h $O/src/openms/include/OpenMS/FORMAT/TdfMzCalibration.h &&
  same $W/src/TdfLoad.h $O/src/topp/TdfLoad.h && same $W/src/MzPeakStreamLoad.h $O/src/topp/MzPeakStreamLoad.h && same $W/src/DnoiseMs1.h $O/src/topp/DnoiseMs1.h &&
  same $W/src/NoImsPath.h $O/src/topp/NoImsPath.h && same $W/src/PortableMath.h $O/src/topp/PortableMath.h; }
ship_is() { local W=$V/ver/$1 f; for f in test/test_diaspextract.py bench/semantic_digest.py bench/mzml_specdiff.py bench/tile_concat.py bench/launch.sh; do same $W/$f "$TOOLS/$(basename $f)" || return 1; done
  same $W/tests/calibration_golden.json $TESTS/calibration_golden.json && same $W/tests/test_dnoise_ms1.cpp $R/diaspextract_unit/test_dnoise_ms1.cpp &&
  same $W/tests/test_tdf_load.cpp $R/diaspextract_unit/test_tdf_load.cpp && [ -e $R/diaspextract_unit/test_dnoise_ms1.log ] && [ -e $R/diaspextract_unit/test_tdf_load.log ]; }
prov_is() { local W=$V/ver/$1 P=${2:-$PROV}
  [ "$(pv src_sha256 $P)" = "$(shaf $W/src/diaspextract.cpp)" ] && [ "$(pv calibration_header_sha256 $P)" = "$(shaf $W/src/TdfMzCalibration.h)" ] &&
  [ "$(pv tool_headers_sha256 $P)" = "$(cat $W/src/TdfLoad.h $W/src/MzPeakStreamLoad.h $W/src/DnoiseMs1.h $W/src/NoImsPath.h $W/src/PortableMath.h | shasum -a 256 | cut -d' ' -f1)" ] &&
  [ "$(pv git $P)" = "$(cat $W/REV)" ]; }
ut_is() { [ "$(pv dnoise_unit_test $PROV)" = passed ] && [ "$(pv tdf_load_unit_test $PROV)" = "$1" ]; }
prov_truthful() { [ -e $PROV ] && [ "$(pv binary_sha256 $PROV)" = "$(shaf $O/build/bin/diaspextract)" ] && [ "$(pv libopenms_sha256 $PROV)" = "$(shaf $O/build/lib/libOpenMS.so)" ]; }
clean() { [ ! -e $R/.deploy.lock ] && [ -z "$(find $R -maxdepth 1 -type d -name '.deploy.stage.*')" ]; }
records() { grep -c '^src_sha256=' $R/deploys.log 2> /dev/null || echo 0; }
wait_for()  { local i=0; while [ ! -e "$1" ] && [ $i -lt 600 ]; do sleep 0.1; i=$((i+1)); done; [ -e "$1" ]; }
wait_gone() { local i=0; while [ -e "$1" ] && [ $i -lt 600 ]; do sleep 0.1; i=$((i+1)); done; [ ! -e "$1" ]; }

echo "== $SCRIPT"
mk_node $V/node; mk_repo $V/repoA "$SCRIPT"
set_version $V/repoA v0 c0 1 1
rc=$(deploy $V/repoA $V/s0.out)
ok "S0 first deploy commits (rc $rc)" '[ $rc = 0 ] && tree_is v0 && ship_is v0 && prov_is v0 && prov_truthful && ut_is passed && clean && [ $(records) = 1 ]'
set_version $V/repoA v1 c1 1 1
rc=$(deploy $V/repoA $V/s1.out)
ok "S1 success: inputs, tools, provenance all v1; old cpp kept as .bak (rc $rc)" '[ $rc = 0 ] && tree_is v1 && ship_is v1 && prov_is v1 && prov_truthful && same $V/ver/v0/src/diaspextract.cpp $O/src/topp/diaspextract.cpp.bak && clean && [ $(records) = 2 ]'
ok "S1 both unit tests passed against the staged v1 headers while the tree still held v0's" 'ut_is passed && grep -q "^tdf_load_unit_test=passed" $V/s1.out'
ok "S1 build tree is up to date after commit" '(cd $O/build && make -q bin/diaspextract)'
ok "S1 transaction log reached the caller" 'grep -q "DEPLOY COMMITTED" $V/s1.out'

sleep 1; S=$(snap); set_version $V/repoA v2 c2 0 1
rc=$(deploy $V/repoA $V/s2.out)
ok "S2 dnoise unit-test failure: rc 2, node byte- AND mtime-identical, nothing promoted" '[ $rc = 2 ] && [ "$S" = "$(snap)" ] && grep -q "test_dnoise_ms1 unit test FAILED.*nothing promoted" $V/s2.out'
S=$(snap); set_version $V/repoA v2b c2 1 0
rc=$(deploy $V/repoA $V/s2b.out)
ok "S2b tdf_load unit-test failure: rc 2, node byte- AND mtime-identical, nothing promoted" '[ $rc = 2 ] && [ "$S" = "$(snap)" ] && grep -q "test_tdf_load unit test FAILED.*nothing promoted" $V/s2b.out'

cp $PROV $V/prov_v1; lib_v1=$(shaf $O/build/lib/libOpenMS.so)
set_version $V/repoA v3 c3 1 1 BREAK_BUILD
rc=$(deploy $V/repoA $V/s3.out)
ok "S3 build failure (calibration changed): rc 2, every input restored, tools untouched" '[ $rc = 2 ] && tree_is v1 && ship_is v1 && clean && [ $(records) = 2 ]'
ok "S3 failed build had relinked libOpenMS.so (the fixture reproduces the cluster logs)" '[ "$(shaf $O/build/lib/libOpenMS.so)" != "$lib_v1" ]'
ok "S3 provenance fail-closed: absent, parked as .stale == v1 provenance" '[ ! -e $PROV ] && same $PROV.stale $V/prov_v1 && grep -q FAIL-CLOSED $V/s3.out'
ok "S3 restored calibration header is newer than the lib the failed build relinked (next make relinks it)" '! (cd $O/build && make -q lib/libOpenMS.so)'
(cd $O/build && make diaspextract > /dev/null 2>&1)
ok "S3 recovery: make on the restored tree reproduces the v1 binary and lib the parked provenance names" '[ "$(shaf $O/build/lib/libOpenMS.so)" = "$(pv libopenms_sha256 $PROV.stale)" ] && [ "$(shaf $O/build/bin/diaspextract)" = "$(pv binary_sha256 $PROV.stale)" ]'
mv $PROV.stale $PROV

set_version $V/repoA v4 c1 1 1 BREAK_BUILD
rc=$(deploy $V/repoA $V/s3b.out)
ok "S3b build failure (calibration unchanged): rc 2, inputs restored, provenance restored and truthful" '[ $rc = 2 ] && tree_is v1 && same $PROV $V/prov_v1 && prov_truthful && [ ! -e $PROV.stale ] && clean'

mkdir $R/.deploy.lock && echo "someone else" > $R/.deploy.lock/owner
S=$(snap); set_version $V/repoA v5 c5 1 1
rc=$(deploy $V/repoA $V/s4.out)
ok "S4 lock held: rc 1, REFUSED, node byte- and mtime-identical (no stage left)" '[ $rc = 1 ] && grep -q "REFUSED: another deploy holds" $V/s4.out && [ "$S" = "$(snap)" ]'
rm -rf $R/.deploy.lock

printf '4\n' > $O/slow
git clone -q $V/repoA $V/repoB && git -C $V/repoB config user.email t@t && git -C $V/repoB config user.name t && git -C $V/repoB config commit.gpgsign false
set_version $V/repoA v6 c6 1 1; set_version $V/repoB v7 c7 1 1
( deploy $V/repoA $V/s5a.out > $V/s5a.rc ) &
wait_for $O/building
rcb=$(deploy $V/repoB $V/s5b.out); wait; rca=$(cat $V/s5a.rc)
ok "S5 concurrent: B refused while A builds (rcA $rca, rcB $rcb)" '[ $rca = 0 ] && [ $rcb = 1 ] && grep -q "REFUSED: another deploy holds" $V/s5b.out'
ok "S5 tree, tools and provenance are exactly A (v6); no byte of B (v7) anywhere on the node" 'tree_is v6 && ship_is v6 && prov_is v6 && prov_truthful && clean && [ -z "$(grep -rl v7 $N --exclude="*.log" --exclude=libsqlite3.a)" ]'
printf '0\n' > $O/slow

cp $O/src/openms/source/FORMAT/BrukerTimsFile.cpp $V/bruker.keep; printf 'unpatched\n' > $O/src/openms/source/FORMAT/BrukerTimsFile.cpp
S=$(snap); set_version $V/repoA v8 c8 1 1
rc=$(deploy $V/repoA $V/s6.out)
ok "S6 calibration patch missing: rc 1, node unchanged" '[ $rc = 1 ] && grep -q "no calibration patch" $V/s6.out && [ "$S" = "$(snap)" ]'
cp $V/bruker.keep $O/src/openms/source/FORMAT/BrukerTimsFile.cpp; (cd $O/build && make diaspextract > /dev/null 2>&1)

S=$(snap); set_version $V/repoA v9 c9 1 1
rc=$(TORN=TdfLoad.h deploy $V/repoA $V/s7.out)
ok "S7 torn upload: rc 1, node unchanged" '[ $rc = 1 ] && grep -q "staged files differ" $V/s7.out && [ "$S" = "$(snap)" ]'

printf '4\n' > $O/slow; set_version $V/repoA v10 c10 1 1
( deploy $V/repoA $V/s8.out > $V/s8.rc ) &
wait_for $O/building; printf '// intruder outside the lock\n' > $O/src/topp/TdfLoad.h; wait; rc=$(cat $V/s8.rc)
ok "S8 lockless writer during build: rc 2, inputs back to v6, no provenance recorded for the mixed binary" '[ $rc = 2 ] && grep -q "changed during the build" $V/s8.out && tree_is v6 && [ ! -e $PROV ] && [ -e $PROV.stale ] && clean'

# S9 needs a truthful provenance to lose: rebuild the restored v6 tree, which reproduces what the parked one names
(cd $O/build && make diaspextract > /dev/null 2>&1); mv $PROV.stale $PROV
ok "S9 setup: the restored tree rebuilds to the parked v6 provenance" 'prov_is v6 && prov_truthful'
set_version $V/repoA v11 c6 1 1
( deploy $V/repoA $V/s9.out > $V/s9.rc ) &
wait_for $O/building && kill -TERM "$(sed -n 's/^.* pid \([0-9][0-9]*\) .*$/\1/p' $R/.deploy.lock/owner)"
wait; rc=$(cat $V/s9.rc); wait_gone $O/building; sleep 0.5   # a make the transaction abandoned would finish here
ok "S9 SIGTERM to the transaction mid-build: it lets make finish, then rolls back every input (rc $rc)" '[ $rc = 143 ] && tree_is v6 && grep -q "ROLLED BACK" $V/s9.out && ! grep -q "DEPLOY COMMITTED" $V/s9.out && clean'
ok "S9 after the killed build no provenance names a binary it does not describe" '[ ! -e $PROV ] || prov_truthful'
printf '0\n' > $O/slow

set_flags no; set_version $V/repoA v12 c12 1 0
rc=$(deploy $V/repoA $V/s10.out)
ok "S10 no sqlite3.h in the tool include dirs: test_tdf_load skipped, deploy commits and the provenance says so (rc $rc)" '[ $rc = 0 ] && tree_is v12 && prov_is v12 && prov_truthful && ut_is "skipped(no sqlite3.h in the tool include dirs)" && grep -q "tdf_load unit test SKIPPED" $V/s10.out && grep -q skipped $R/diaspextract_unit/test_tdf_load.log && clean'
set_flags yes; mv $O/build/lib/libsqlite3.a $V/libsqlite3.a.keep; set_version $V/repoA v13 c13 1 1
rc=$(deploy $V/repoA $V/s10b.out)
ok "S10b no bundled libsqlite3.a: skipped, commits, provenance names the missing library (rc $rc)" '[ $rc = 0 ] && tree_is v13 && prov_truthful && ut_is "skipped(no $O/build/lib/libsqlite3.a)" && clean'
mv $V/libsqlite3.a.keep $O/build/lib/libsqlite3.a

S=$(snap); git -C $V/repoA rm -q tests/test_tdf_load.cpp && git -C $V/repoA commit -qm "drop test_tdf_load"
rc=$(deploy $V/repoA $V/s11.out)
ok "S11 a build input missing from the checkout: rc 1, REFUSED before anything reaches the node" '[ $rc = 1 ] && grep -q "REFUSED: tests/test_tdf_load.cpp does not exist" $V/s11.out && [ "$S" = "$(snap)" ]'

set_version $V/repoA v14 c14 1 1; printf '// uncommitted\n' >> $V/repoA/src/TdfLoad.h
S=$(snap); rc=$(deploy $V/repoA $V/s12.out)
ok "S12 uncommitted build input: rc 1, REFUSED naming the file, node unchanged" '[ $rc = 1 ] && grep -q "src/TdfLoad.h" $V/s12.out && grep -q -- "--allow-dirty" $V/s12.out && [ "$S" = "$(snap)" ]'
rc=$(deploy $V/repoA $V/s12b.out --allow-dirty)
ok "S12b node argument + --allow-dirty: commits the working-tree bytes as <rev>+dirty (rc $rc)" '[ $rc = 0 ] && same $V/repoA/src/TdfLoad.h $O/src/topp/TdfLoad.h && [ "$(pv git $PROV)" = "$(cat $V/ver/v14/REV)+dirty" ] && prov_truthful && ut_is passed && clean'

# Stage-3 review (deploy-1) F1/F2/F9: the commit point, a verified rollback, a stale or interrupted lock.
reset_node() {  # drop whatever the previous scenario left (lock, stage, provenance debris), then commit version $1 (calibration $2)
  chmod u+w $O/src/topp; rm -rf $R/.deploy.lock $PROV.tmp $PROV.stale; [ -f $PROV ] || rm -rf $PROV
  find $R -maxdepth 1 -type d -name '.deploy.stage.*' -exec rm -rf {} +
  set_version $V/repoA $1 $2 1 1; local rc; rc=$(deploy $V/repoA $V/reset_$1.out); [ $rc = 0 ] && tree_is $1 && prov_truthful && clean; }
ok "S4b setup: a clean committed v15" 'reset_node v15 c15'
sh -c 'exit 0' & DEAD=$!; wait $DEAD
mkdir $R/.deploy.lock && echo "$R/.deploy.stage.dead00 pid $DEAD 2026-09-10T00:00:00+0200" > $R/.deploy.lock/owner
S=$(snap); set_version $V/repoA v16 c16 1 1; rc=$(deploy $V/repoA $V/s4b.out)
ok "S4b lock left by a dead pid: rc 1, node unchanged, the refusal says the owner is not running" '[ $rc = 1 ] && [ "$S" = "$(snap)" ] && grep -q "is NOT running" $V/s4b.out'
rm -rf $R/.deploy.lock
# a touch that stalls once the flag exists: the flag goes up mid-build, so only the rollback's touch stalls
REAL_TOUCH=$(command -v touch)
printf '#!/usr/bin/env bash\nif [ -e %s/slow_touch ]; then : > %s/slow_touch.hit; sleep 1; fi\nexec %s "$@"\n' "$V" "$V" "$REAL_TOUCH" > $V/shim/touch; chmod +x $V/shim/touch
printf '3\n' > $O/slow; set_version $V/repoA v17 c15 1 1 BREAK_BUILD
( deploy $V/repoA $V/s9b.out > $V/s9b.rc ) &
wait_for $O/building; PID=$(sed -n 's/^.* pid \([0-9][0-9]*\) .*$/\1/p' $R/.deploy.lock/owner); : > $V/slow_touch
wait_for $V/slow_touch.hit && kill -TERM "$PID"
wait; rc=$(cat $V/s9b.rc); rm -f $V/shim/touch $V/slow_touch $V/slow_touch.hit; printf '0\n' > $O/slow
ok "S9b a TERM during the rollback: every input restored, provenance truthful, lock released (rc $rc)" '[ $rc = 2 ] && tree_is v15 && prov_is v15 && prov_truthful && grep -q "ROLLED BACK" $V/s9b.out && clean'

ok "S13 setup: a clean committed v18" 'reset_node v18 c18'
cp $PROV $V/prov_v18
printf '3\n' > $O/slow; set_version $V/repoA v19 c19 1 1
( deploy $V/repoA $V/s13.out > $V/s13.rc ) &
wait_for $O/building && mkdir -p $PROV/diaspextract.provenance.tmp   # the old provenance is parked: a directory in its place fails the rename
wait; rc=$(cat $V/s13.rc); printf '0\n' > $O/slow
ok "S13 a failed provenance rename is never reported as a commit (rc $rc)" '[ $rc != 0 ] && ! grep -q "^COMMITTED (binary + provenance)" $V/s13.out'
ok "S13 it rolls back like a failed build: inputs v18, no provenance.tmp, old provenance parked, clean" 'tree_is v18 && grep -q "ROLLED BACK" $V/s13.out && [ ! -e $PROV.tmp ] && same $PROV.stale $V/prov_v18 && clean'

ok "S14 setup: a clean committed v20" 'reset_node v20 c20'
cp $PROV $V/prov_v20
printf '3\n' > $O/slow; set_version $V/repoA v21 c20 1 1 BREAK_BUILD   # calibration unchanged: the failed build leaves lib and binary as they were
( deploy $V/repoA $V/s14.out > $V/s14.rc ) &
wait_for $O/building && chmod a-w $O/src/topp   # four of the five restores now fail with EACCES
wait; rc=$(cat $V/s14.rc); chmod u+w $O/src/topp; printf '0\n' > $O/slow
ST=$(find $R -maxdepth 1 -type d -name '.deploy.stage.*' | head -1)
ok "S14 a failed rollback rename is not reported as a complete rollback (rc $rc)" '[ $rc = 2 ] && ! grep -q "ROLLED BACK every" $V/s14.out && grep -q "rollback incomplete" $V/s14.out'
ok "S14 the unrestored backups, the parked provenance and the lock are kept" '[ -e $R/.deploy.lock ] && [ -n "$ST" ] && same $ST/bak/diaspextract.cpp $V/ver/v20/src/diaspextract.cpp && same $ST/prov.prev $V/prov_v20'
ok "S14 no provenance is put back over a tree that still holds the failed deploy's source" '[ ! -e $PROV ] || [ "$(pv src_sha256 $PROV)" = "$(shaf $O/src/topp/diaspextract.cpp)" ]'

echo "== $PASS passed, $FAIL failed"
if [ "$FAIL" = 0 ]; then rm -rf "$V"; else echo "   fixture kept for inspection: $V"; fi
[ "$FAIL" = 0 ]
