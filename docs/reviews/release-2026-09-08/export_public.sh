#!/bin/bash
# Export the dev checkout's TRACKED files into the public clone, excluding the raw review transcripts,
# preserving the public-only assets/, then verify the scrub and the version fields. No commit here.
set -euo pipefail
DEV=/Users/kohlbach/Claude/speXtractor
PUB="$(dirname "$0")/public"
cd "$DEV"
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "REFUSED: dev tree is dirty"; exit 1; }
# .export-private lists what stays in the private repository: internal working documents,
# cluster-only tooling and finished-investigation instruments. Everything else ships.
git ls-files | grep -v -F -f .export-private > "$PUB/.export-list"
rsync -a --delete --files-from="$PUB/.export-list" --exclude='.git' "$DEV/" "$PUB/"
# --delete with --files-from does not remove files absent from the list; do that explicitly, keeping assets/.
cd "$PUB"
git ls-files | grep -v '^assets/' | sort > /tmp/pub_tracked.txt
sort .export-list > /tmp/exp_sorted.txt
comm -23 /tmp/pub_tracked.txt /tmp/exp_sorted.txt | while read -r f; do git rm -q "$f"; echo "removed $f"; done
rm -f .export-list
echo "== files shipped ==";  wc -l < "$PUB/.export-list"
echo "== residual identifiers in the export (must be empty) =="
git ls-files | xargs grep -n -E -i 'diatracer|dataset D-BASELINE|/Users/kohlbach|\bAGXT\b|\bPH1\b|agxt-liver|FKL[0-9]+|K[0-9]{5}-[0-9]+-[0-9]+|QKL[0-9]+' || echo "  none"
echo "== word-bounded cohort labels (must be empty) =="
git ls-files | xargs grep -n -E '(^|[^A-Za-z0-9])S(08|23|26|30|33|36)([^0-9A-Za-z]|$)' || echo "  none"
echo "== internal-development mentions (must be empty) =="
git ls-files | xargs grep -n -i -E 'codex|\bkimi\b|\bvibe\b|adversarial|ibminode|/scratch/|/ceph/|\[adv-fix\]' || echo "  none"
echo "== version fields =="
grep -n "project(" CMakeLists.txt; grep -n "^version\|^date-released" CITATION.cff; grep -n "SPEXTRACTOR_VERSION \"" src/spextractor.cpp; grep -n "^## " CHANGELOG.md | head -3
echo "== status =="
git status --short | wc -l; git diff --stat HEAD | tail -1
