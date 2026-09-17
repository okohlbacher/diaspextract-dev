#!/usr/bin/env bash
# One reviewer, isolated in its own detached worktree of the reviewed SHA; PID wait; the worktree must stay clean.
# usage: run_reviewer.sh codex|kimi|vibe BRIEF OUTDIR SHA WTROOT
set -uo pipefail
CLI=$1; BRIEF=$2; OUT=$3; SHA=$4; WTROOT=$5
REPO="/Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextract"
WT="$WTROOT/wt-$CLI"
git -C "$REPO" worktree add --detach "$WT" "$SHA" >/dev/null 2>&1 || { echo "rc=90 worktree add failed" > "$OUT/$CLI.status"; exit 90; }
PROMPT=$(cat "$BRIEF")
t0=$(date +%s)
(
  cd "$WT" || exit 91
  case "$CLI" in
    codex) codex exec --skip-git-repo-check -s read-only -c model_reasoning_effort=high --color never \
             -o "$OUT/codex.md" "$PROMPT" </dev/null >"$OUT/codex.transcript" 2>&1 ;;
    kimi)  kimi -p "$PROMPT" --output-format text </dev/null >"$OUT/kimi.md" 2>"$OUT/kimi.err" ;;
    vibe)  vibe -p "$PROMPT" --output text --auto-approve --workdir "$WT" </dev/null >"$OUT/vibe.md" 2>"$OUT/vibe.err" ;;
  esac
) &
pid=$!
wait "$pid"; rc=$?
t1=$(date +%s)
DIRTY=$(git -C "$WT" status --porcelain)
bytes=$(wc -c < "$OUT/$CLI.md" 2>/dev/null | tr -d ' ')
echo "rc=$rc elapsed=$((t1 - t0))s bytes=${bytes:-0} worktree_dirty=$([ -n "$DIRTY" ] && echo YES || echo no)" > "$OUT/$CLI.status"
if [ -n "$DIRTY" ]; then
  printf '%s\n' "$DIRTY" > "$OUT/$CLI.worktree-dirty.txt"
  git -C "$WT" diff > "$OUT/$CLI.worktree-dirty.diff" 2>/dev/null
fi
git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1
echo "done $CLI $(cat "$OUT/$CLI.status")"
