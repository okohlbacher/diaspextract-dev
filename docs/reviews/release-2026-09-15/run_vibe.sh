#!/bin/bash
# Manual vibe dispatch for the 1.3.0 rename review. Why not dispatch.sh: vibe 2.25.3 in -p mode asks
# "Allow bash?" for every tool call unless --auto-approve is given (--trust only trusts the directory),
# and with stdin at /dev/null the approval is cancelled -> zero output (two runs, 2026-09-15). It also
# cd'ed into a guessed path when the brief did not name the worktree, so the brief gets the path prepended.
# PID-based completion, watchdog (no timeout(1) on macOS), worktree cleanliness check, worktree removed.
set -u
REPO="/Users/kohlbach/Projects/OpenMS/New Tools/DIAspeXtractor/diaspextractor"
R=/private/tmp/claude-501/-Users-kohlbach-Claude-OpenMS---DIAtracer/e4677b2f-9916-478b-9db2-706d8e88d289/scratchpad/rename13/review
W=/private/tmp/advrev-vibe-1300
LIMIT=${1:-2400}
git -C "$REPO" worktree remove --force "$W" 2>/dev/null; rm -rf "$W"
git -C "$REPO" worktree add --detach "$W" HEAD >/dev/null 2>&1 || { echo "worktree add failed"; exit 2; }
{ printf 'Your working directory (already current, do not cd anywhere else; every relative path below is relative to it) is: %s\n\n' "$W"; cat "$R/BRIEF.md"; } > "$R/BRIEF-vibe.md"
BRIEF_TEXT=$(cat "$R/BRIEF-vibe.md")
cd "$W" || exit 2
vibe -p "$BRIEF_TEXT" --output text --trust --auto-approve --max-turns 80 </dev/null >"$R/vibe.md" 2>"$R/vibe.err" &
pid=$!
( sleep "$LIMIT"; kill -TERM "$pid" 2>/dev/null ) & wd=$!
wait "$pid"; rc=$?
kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
echo "vibe rc=$rc bytes=$(wc -c < "$R/vibe.md" | tr -d ' ') err_bytes=$(wc -c < "$R/vibe.err" | tr -d ' ')"
DIRTY=$(git -C "$W" status --porcelain)
if [ -n "$DIRTY" ]; then echo "! vibe MUTATED its worktree:"; echo "$DIRTY"; else echo "vibe left its worktree clean"; fi
cd /; git -C "$REPO" worktree remove --force "$W" && echo "worktree removed"
