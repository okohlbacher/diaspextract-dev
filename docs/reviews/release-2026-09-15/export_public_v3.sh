#!/bin/bash
# export_public_v3.sh -- populate the PUBLIC clone from the DEV repository's tracked files.
#
#   export_public_v3.sh --version X.Y.Z --name NAME --src DEV --dst PUBLIC [--date YYYY-MM-DD]
#                       [--keep PREFIX]... [--prev OLDNAME]... [--dry-run]
#
# What it does, in order:
#   (a) refuses a dirty or unpushed (ahead-of-origin) --src or --dst; refuses before touching --dst;
#   (b) copies exactly `git ls-files` of --src minus the fixed-string patterns in --src/.export-private
#       (grep -v -F -f semantics: a pattern matches anywhere in the path) into --dst, removes --dst files
#       that are no longer exported, preserves --dst's .git and its public-only paths (--keep, default
#       assets/), and stages the explicit paths it added, changed or removed (no `git add -A`, no commit);
#   (c) verifies in --dst that the CMake project name/VERSION, the CITATION.cff title/version, the source
#       #define NAME_VERSION, the TOPPBase name, the executable target, the README title, the CHANGELOG's
#       first heading and build.yml's name gate all carry --name / --version (--date: CITATION.cff and
#       the CHANGELOG heading carry the release date too);
#   (d) greps the exported tree for scrub residuals (cohort labels S08/S23/S26/S30/S33/S36 word-bounded
#       with `_` NOT a boundary, the reference implementation's name, specimen IDs FKL/K25423/QKL
#       word-bounded with `_` a boundary, /Users/kohlbach, AGXT/PH1/liver word-bounded, docs/reviews,
#       docs/benchmarks); then two informational scans that gate nothing: internal-development mentions,
#       and every --prev OLDNAME (as OLDNAME, oldname and OLDNAME_) so a rename leftover is read, not missed;
#   (e) prints a file-list diff summary (added / modified / removed / unchanged / preserved; a rename counts
#       as one removal plus one addition).
#
# Exit status: 0 = export done and every check passed; 1 = export done but one or more checks FAILED
# (the failures are listed, --dst is left in the exported state for inspection: undo it with
# `git -C DST reset -q --hard && git -C DST clean -fdq`); 2 = refused or usage error, --dst untouched.
#
# No `set -e`: every step checks its own status, so a failing grep can neither abort the script
# silently nor pass a residual through with exit 0 (both happened with the v1 script).

set -u
set -o pipefail
LC_ALL=C; export LC_ALL

VERSION=""; NAME=""; SRC=""; DST=""; DATE=""; DRY=0
KEEP=("assets/")
PREV=()

usage() { sed -n '2,25p' "$0" >&2; exit 2; }
die()   { printf 'REFUSED: %s\n' "$*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version) [ $# -ge 2 ] || usage; VERSION=$2; shift 2 ;;
    --name)    [ $# -ge 2 ] || usage; NAME=$2; shift 2 ;;
    --src)     [ $# -ge 2 ] || usage; SRC=$2; shift 2 ;;
    --dst)     [ $# -ge 2 ] || usage; DST=$2; shift 2 ;;
    --date)    [ $# -ge 2 ] || usage; DATE=$2; shift 2 ;;
    --keep)    [ $# -ge 2 ] || usage; KEEP+=("$2"); shift 2 ;;
    --prev)    [ $# -ge 2 ] || usage; PREV+=("$2"); shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) usage ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage ;;
  esac
done
[ -n "$VERSION" ] && [ -n "$NAME" ] && [ -n "$SRC" ] && [ -n "$DST" ] || usage
printf '%s' "$VERSION" | grep -q -E '^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.]+)?$' || die "--version '$VERSION' is not X.Y.Z"
printf '%s' "$NAME" | grep -q -E '^[A-Za-z][A-Za-z0-9]*$' || die "--name '$NAME' must be alphanumeric"
if [ -n "$DATE" ]; then printf '%s' "$DATE" | grep -q -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' || die "--date '$DATE' is not YYYY-MM-DD"; fi
for p in "${PREV[@]}"; do printf '%s' "$p" | grep -q -E '^[A-Za-z][A-Za-z0-9]*$' || die "--prev '$p' must be alphanumeric"; [ "$p" != "$NAME" ] || die "--prev '$p' is the current name"; done
LOWER=$(printf '%s' "$NAME" | tr 'A-Z' 'a-z')
UPPER=$(printf '%s' "$NAME" | tr 'a-z' 'A-Z')

# ---------------------------------------------------------------- (a) preconditions: nothing is touched yet
repo_root() { git -C "$1" rev-parse --show-toplevel 2>/dev/null; }
SRC_ROOT=$(repo_root "$SRC") || die "--src '$SRC' is not inside a git work tree"
DST_ROOT=$(repo_root "$DST") || die "--dst '$DST' is not inside a git work tree"
SRC_ABS=$(cd "$SRC" && pwd -P) || die "--src '$SRC' unreadable"
DST_ABS=$(cd "$DST" && pwd -P) || die "--dst '$DST' unreadable"
[ "$SRC_ROOT" = "$SRC_ABS" ] || die "--src must be the root of its work tree ($SRC_ROOT)"
[ "$DST_ROOT" = "$DST_ABS" ] || die "--dst must be the root of its work tree ($DST_ROOT)"
[ "$SRC_ABS" != "$DST_ABS" ] || die "--src and --dst are the same tree"
[ -s "$SRC_ABS/.export-private" ] || die "$SRC_ABS/.export-private is missing or empty"
command -v rsync >/dev/null || die "rsync not found"

# dirty: tracked-file changes in src (untracked files never ship, `git ls-files` decides); anything at all in dst.
if [ -n "$(git -C "$SRC_ABS" status --porcelain --untracked-files=no)" ]; then
  git -C "$SRC_ABS" status --short --untracked-files=no >&2; die "--src has uncommitted changes to tracked files"
fi
if [ -n "$(git -C "$DST_ABS" status --porcelain)" ]; then
  git -C "$DST_ABS" status --short >&2; die "--dst is not clean (uncommitted or untracked files)"
fi
# ahead of origin: HEAD must be reachable from a remote-tracking ref of `origin` (a detached HEAD is fine).
pushed_ref() { git -C "$1" branch -r --contains HEAD 2>/dev/null | grep -v -- '->' | sed 's/^[* ]*//' | grep -m1 '^origin/'; }
SRC_REF=$(pushed_ref "$SRC_ABS") || die "--src HEAD $(git -C "$SRC_ABS" rev-parse --short HEAD) is not on any origin/* ref (unpushed)"
DST_REF=$(pushed_ref "$DST_ABS") || die "--dst HEAD $(git -C "$DST_ABS" rev-parse --short HEAD) is not on any origin/* ref (unpushed)"
SRC_SHA=$(git -C "$SRC_ABS" rev-parse HEAD); DST_SHA=$(git -C "$DST_ABS" rev-parse HEAD)

WORK=$(mktemp -d "${TMPDIR:-/tmp}/export_public.XXXXXX") || die "mktemp failed"
printf '== export %s %s: %s @ %s (%s) -> %s @ %s (%s)\n   work dir %s\n' \
  "$NAME" "$VERSION" "$SRC_ABS" "${SRC_SHA:0:9}" "$SRC_REF" "$DST_ABS" "${DST_SHA:0:9}" "$DST_REF" "$WORK"

# ---------------------------------------------------------------- (b) the export list
grep -v -E '^[[:space:]]*$' "$SRC_ABS/.export-private" > "$WORK/private.txt"
NBLANK=$(grep -c -E '^[[:space:]]*$' "$SRC_ABS/.export-private"); [ "$NBLANK" = 0 ] || printf 'warning: %s blank line(s) in .export-private ignored (a blank -F pattern would exclude everything)\n' "$NBLANK"
git -C "$SRC_ABS" ls-files | sort > "$WORK/all.txt" || die "git ls-files failed in --src"
[ -s "$WORK/all.txt" ] || die "--src tracks no files"
grep -v -F -f "$WORK/private.txt" "$WORK/all.txt" > "$WORK/export.txt"; rc=$?
[ $rc -le 1 ] || die "grep over the export list failed (rc=$rc)"
[ -s "$WORK/export.txt" ] || die ".export-private excludes every tracked file"
comm -23 "$WORK/all.txt" "$WORK/export.txt" > "$WORK/excluded.txt"
if grep -q '[[:space:]]' "$WORK/export.txt"; then grep '[[:space:]]' "$WORK/export.txt" >&2; die "exported path with whitespace"; fi
grep -q -x '\.export-private' "$WORK/export.txt" && die ".export-private itself would be exported: it must list itself"
if grep -q -E '^docs/(reviews|benchmarks)/' "$WORK/export.txt"; then grep -E '^docs/(reviews|benchmarks)/' "$WORK/export.txt" >&2; die "docs/reviews or docs/benchmarks in the export list"; fi

KEEP_RE=""; for k in "${KEEP[@]}"; do KEEP_RE="${KEEP_RE:+$KEEP_RE|}^$(printf '%s' "$k" | sed 's/[][\.*^$/]/\\&/g')"; done
git -C "$DST_ABS" ls-files | sort > "$WORK/dst_before.txt" || die "git ls-files failed in --dst"
grep -E "$KEEP_RE" "$WORK/dst_before.txt" > "$WORK/preserved.txt"
grep -v -E "$KEEP_RE" "$WORK/dst_before.txt" | comm -23 - "$WORK/export.txt" > "$WORK/remove.txt"
comm -13 "$WORK/dst_before.txt" "$WORK/export.txt" > "$WORK/added.txt"

printf '   tracked in src %s, excluded by .export-private %s, exported %s; dst tracked before %s, preserved (dst-only) %s, to remove %s, to add %s\n' \
  "$(wc -l < "$WORK/all.txt" | tr -d ' ')" "$(wc -l < "$WORK/excluded.txt" | tr -d ' ')" "$(wc -l < "$WORK/export.txt" | tr -d ' ')" \
  "$(wc -l < "$WORK/dst_before.txt" | tr -d ' ')" "$(wc -l < "$WORK/preserved.txt" | tr -d ' ')" "$(wc -l < "$WORK/remove.txt" | tr -d ' ')" "$(wc -l < "$WORK/added.txt" | tr -d ' ')"
if [ "$DRY" = 1 ]; then
  echo "== dry run: would remove"; sed 's/^/   /' "$WORK/remove.txt"
  echo "== dry run: would add";    sed 's/^/   /' "$WORK/added.txt"
  echo "== dry run: preserved";    sed 's/^/   /' "$WORK/preserved.txt"
  echo "== dry run: lists in $WORK (nothing written to --dst)"; exit 0
fi

# ---------------------------------------------------------------- (b) copy, remove, stage explicit paths
if ! rsync -a --files-from="$WORK/export.txt" "$SRC_ABS/" "$DST_ABS/"; then die "rsync failed; --dst may be partially written (git -C '$DST_ABS' reset -q --hard)"; fi
if [ -s "$WORK/remove.txt" ]; then
  if ! tr '\n' '\0' < "$WORK/remove.txt" | xargs -0 -r git -C "$DST_ABS" rm -q --; then die "git rm of stale files failed"; fi
fi
if ! tr '\n' '\0' < "$WORK/export.txt" | xargs -0 -r git -C "$DST_ABS" add --; then die "git add of the exported files failed"; fi

FAILS=()
fail() { FAILS+=("$*"); printf 'FAIL: %s\n' "$*"; }
ok()   { printf '  ok: %s\n' "$*"; }
check_grep() { # label file pattern
  if [ ! -f "$DST_ABS/$2" ]; then fail "$1: $2 missing"; return; fi
  if grep -q -E -- "$3" "$DST_ABS/$2"; then ok "$1 ($2)"; else fail "$1: $2 lacks /$3/ -- has: $(grep -n -E -m3 -- "$4" "$DST_ABS/$2" | tr '\n' ';')"; fi
}

# ---------------------------------------------------------------- (c) version and name fields in dst
echo "== version and name fields ($NAME $VERSION${DATE:+ $DATE})"
V_RE=$(printf '%s' "$VERSION" | sed 's/\./\\./g')
check_grep "CMake project"     CMakeLists.txt "^project\($NAME VERSION $V_RE LANGUAGES" '^project\('
check_grep "CMake executable"  CMakeLists.txt "^add_executable\($LOWER src/$LOWER\.cpp\)" '^add_executable\('
check_grep "CITATION title"    CITATION.cff   "^title: $NAME\$" '^title:'
check_grep "CITATION version"  CITATION.cff   "^version: $V_RE\$" '^version:'
check_grep "source #define"    "src/$LOWER.cpp" "^#define ${UPPER}_VERSION \"$V_RE\"\$" '^#define [A-Z_]*VERSION'
check_grep "TOPPBase name"     "src/$LOWER.cpp" "TOPPBase\(\"$NAME\"," 'TOPPBase\("'
check_grep "README title"      README.md      "^# $NAME\$" '^# '
check_grep "build.yml name gate" .github/workflows/build.yml "project\($NAME VERSION" 'project\('   # unconditional: a missing workflow is a FAIL, like every other field
if [ -f "$DST_ABS/CHANGELOG.md" ]; then
  H=$(grep -m1 '^## ' "$DST_ABS/CHANGELOG.md")
  if printf '%s' "$H" | grep -q -E "^## v$V_RE( |\$)"; then ok "CHANGELOG first heading: $H"; else fail "CHANGELOG first heading is '$H', want '## v$VERSION ...'"; fi
  if [ -n "$DATE" ]; then printf '%s' "$H" | grep -q -F -- "$DATE" && ok "CHANGELOG heading carries $DATE" || fail "CHANGELOG heading '$H' lacks $DATE"; fi
else fail "CHANGELOG.md missing"; fi
if [ -n "$DATE" ]; then check_grep "CITATION date-released" CITATION.cff "^date-released: \"?$DATE\"?\$" '^date-released:'
else printf '  info: %s\n' "$(grep -m1 '^date-released:' "$DST_ABS/CITATION.cff" 2>/dev/null || echo 'CITATION.cff has no date-released')"; fi
# every remaining old-name spelling in the sources is a rename leftover, not a scrub matter: report it, do not gate on it here.

# ---------------------------------------------------------------- (d) scrub residuals in the exported tree
echo "== scrub residuals (must be empty)"
cat "$WORK/export.txt" "$WORK/preserved.txt" | sort -u > "$WORK/tree.txt"
grep -v -E -i '\.(png|jpe?g|gif|ico|pdf|gz|tgz|zip|tar|bz2|xz|7z|woff2?|ttf|otf|parquet|mzpeak|bin|o|a|so|dylib|dll|exe)$' "$WORK/tree.txt" > "$WORK/textfiles.txt"
scan() { # label grep-flags pattern  (files come from textfiles.txt; -a: a stray binary byte must not hide a line)
  local out; out="$WORK/hits_$(printf '%s' "$1" | tr -c 'A-Za-z0-9' '_').txt"
  ( cd "$DST_ABS" && tr '\n' '\0' < "$WORK/textfiles.txt" | xargs -0 -r grep -a -n -H $2 -E -- "$3" ) > "$out" 2>"$out.err"
  local rc=$?
  if [ -s "$out.err" ]; then fail "$1: grep reported errors: $(head -3 "$out.err" | tr '\n' ';')"; fi
  if [ -s "$out" ]; then fail "$1: $(wc -l < "$out" | tr -d ' ') hit(s)"; sed 's/^/     /' "$out"
  elif [ $rc -eq 1 ] || [ $rc -eq 123 ]; then ok "$1"       # 1: no match (single xargs batch); 123: some batch had no match
  elif [ $rc -eq 0 ]; then fail "$1: grep rc 0 but no output (?)"
  else fail "$1: grep rc $rc"; fi
}
scan "cohort labels S08/S23/S26/S30/S33/S36 (word-bounded, _ is not a boundary)" "" '(^|[^A-Za-z0-9_])S(08|23|26|30|33|36)([^A-Za-z0-9_]|$)'
scan "reference implementation named" "-i" 'dia[-_ ]?tracer'
scan "specimen IDs FKL/K25423/QKL (word-bounded, _ is a boundary)" "" '(^|[^A-Za-z0-9])(FKL|K25423|QKL)([^A-Za-z0-9]|$)'   # an ID must not appear at all; the bound only stops a longer token that happens to contain one
scan "local paths /Users/kohlbach" "" '/Users/kohlbach'
scan "cohort project AGXT/PH1/liver (word-bounded)" "-i" '(^|[^A-Za-z0-9_])(AGXT|PH1|liver)([^A-Za-z0-9_]|$)'
scan "private directories docs/reviews, docs/benchmarks" "" 'docs/reviews|docs/benchmarks'
scan "K562 study (user decision 2026-09-23: no K562 result in any public file)" "-i" 'k[-_ ]?562|charkow'
# 1.6.0 review (2026-10-01): the K562 data sets also travel under their accession and study name, and the tuning
# campaign's candidate/branch names and harness sample keys are private jargon no scan above catches
scan "K562 accession/study name (PXD041421, MultiPro)" "-i" 'PXD041421|multi[-_ ]?pro([^a-z]|$)'
scan "internal candidate and branch names (rc-a/rc-b, tune/, tuning campaign)" "-i" '(^|[^A-Za-z0-9_])rc-[ab]([^A-Za-z0-9_]|$)|tune/|tuning campaign'
scan "harness sample keys (HeLa_NN, TNBC_NNN, CAD_NNNN)" "" '(HeLa|TNBC|CAD)_[0-9]'
echo "== internal-development mentions (informational, not a gate)"
( cd "$DST_ABS" && tr '\n' '\0' < "$WORK/textfiles.txt" | xargs -0 -r grep -a -n -H -i -E -- 'codex|(^|[^A-Za-z0-9_])(kimi|vibe)([^A-Za-z0-9_]|$)|adversarial|ibminode|/ceph/|/scratch/kohlbach|\[adv-fix\]' ) 2>/dev/null | sed 's/^/     /' | head -40
echo "   (end of informational scan)"
# The previous names are not a scrub matter (the migration sections and the history line mention them on purpose),
# but a rename leftover elsewhere would pass every gate above: list where each --prev name still occurs, per file.
if [ ${#PREV[@]} -gt 0 ]; then
  PREV_RE=""
  for p in "${PREV[@]}"; do
    PREV_RE="${PREV_RE:+$PREV_RE|}$p|$(printf '%s' "$p" | tr 'A-Z' 'a-z')|$(printf '%s' "$p" | tr 'a-z' 'A-Z')_"
  done
  echo "== previous names (informational, not a gate): /$PREV_RE/ -- every hit must be a deliberate mention"
  ( cd "$DST_ABS" && tr '\n' '\0' < "$WORK/textfiles.txt" | xargs -0 -r grep -a -c -H -E -- "$PREV_RE" ) 2>/dev/null | grep -v ':0$' | sort -t: -k2,2nr > "$WORK/hits_prev.txt"
  NPH=0; while IFS=: read -r _ n; do NPH=$((NPH + n)); done < "$WORK/hits_prev.txt"
  printf '   %s line(s) in %s file(s)\n' "$NPH" "$(wc -l < "$WORK/hits_prev.txt" | tr -d ' ')"
  sed 's/^/     /' "$WORK/hits_prev.txt" | head -40
  echo "   (end of previous-name scan)"
fi

# ---------------------------------------------------------------- (e) file-list diff summary
echo "== file-list diff (staged in --dst, nothing committed)"
git -C "$DST_ABS" diff --cached --name-status --no-renames > "$WORK/staged.txt"   # --no-renames: an R entry would count in no bucket below
NA=$(grep -c '^A' "$WORK/staged.txt"); NM=$(grep -c '^M' "$WORK/staged.txt"); ND=$(grep -c '^D' "$WORK/staged.txt"); NT=$(grep -c '^T' "$WORK/staged.txt")
NO=$(grep -c -v '^[AMDT]' "$WORK/staged.txt"); [ "$NO" = 0 ] || fail "$NO staged entr(y/ies) of a status other than A/M/D/T: $(grep -v '^[AMDT]' "$WORK/staged.txt" | head -3 | tr '\n' ';')"
NE=$(wc -l < "$WORK/export.txt" | tr -d ' '); NP=$(wc -l < "$WORK/preserved.txt" | tr -d ' ')
printf '   exported %s + preserved dst-only %s = %s files in the public tree; added %s, modified %s, type-changed %s, removed %s, unchanged %s\n' \
  "$NE" "$NP" "$((NE + NP))" "$NA" "$NM" "$NT" "$ND" "$((NE - NA - NM - NT))"
if [ -s "$WORK/staged.txt" ]; then sed 's/^/   /' "$WORK/staged.txt" | head -80; [ "$(wc -l < "$WORK/staged.txt")" -gt 80 ] && echo "   ... ($(wc -l < "$WORK/staged.txt" | tr -d ' ') entries, full list in $WORK/staged.txt)"; else echo "   (no change: the export reproduces --dst HEAD exactly)"; fi
git -C "$DST_ABS" diff --cached --stat | tail -1 | sed 's/^/   /'
if [ -n "$(git -C "$DST_ABS" status --porcelain)" ] && [ ! -s "$WORK/staged.txt" ]; then fail "dst has unstaged changes although nothing was staged"; git -C "$DST_ABS" status --short | head; fi
echo "   excluded by .export-private ($(wc -l < "$WORK/excluded.txt" | tr -d ' ') paths): $WORK/excluded.txt; preserved: $(tr '\n' ' ' < "$WORK/preserved.txt")"

if [ ${#FAILS[@]} -eq 0 ]; then
  printf 'EXPORT VERIFIED: %s %s from %s (%s) into %s; review `git -C %s status`, then commit with a summarising message.\n' "$NAME" "$VERSION" "${SRC_SHA:0:9}" "$SRC_REF" "$DST_ABS" "$DST_ABS"
  rm -rf "$WORK"; exit 0
fi
printf 'EXPORT FAILED: %s check(s) did not pass (lists kept in %s):\n' "${#FAILS[@]}" "$WORK"
for f in "${FAILS[@]}"; do printf '   - %s\n' "$f"; done
exit 1
