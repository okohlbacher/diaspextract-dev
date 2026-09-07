#!/bin/bash
# launch.sh TAG WORKDIR CMD [ARGS...] -- start a long job and RETURN, without holding the ssh channel.
#
# Why this exists [2026-09-07]. Launching with
#     ssh HOST 'cd DIR && setsid CMD > log 2>&1 </dev/null & ...'
# blocks ssh for the ENTIRE job. The `&` binds to the whole AND-list, so bash forks a subshell to
# run it; the redirections apply only to the inner command, so that subshell keeps sshd's stdout and
# stderr pipes and waits. sshd closes a non-PTY channel only when the LAST writer of those pipes
# closes them. Measured on spock with a 6 s payload: 7.0-7.3 s held vs 0.8-1.0 s released.
#
# The invariant is NOT "avoid cd &&". It is: no process that outlives the foreground command may
# still hold the session's stdout/stderr. Bash only avoids leaving one when the backgrounded unit
# reduces to a SINGLE REDIRECTED SIMPLE COMMAND it can exec in place. So `true && setsid ... &`
# also holds, and so do `( ... ) &` and `{ ...; } &`. That rules out the obvious "fixes":
#   cd DIR; setsid ... &          -> a missing DIR silently runs the job in quota-limited $HOME
#   { cd DIR && setsid ...; } &   -> releases, but buries a failed cd in a remote log
# Hence: one simple command, with the cd guarded INSIDE the payload.
set -u
LDIR=${LAUNCH_DIR:-/scratch/kohlbach/launch}
[ $# -ge 3 ] || { echo "usage: launch.sh TAG WORKDIR CMD [ARGS...]" >&2; exit 2; }
TAG=$1; WD=$2; shift 2
case $TAG in */*|"") echo "LAUNCH_FAIL: TAG must not be empty or contain '/'" >&2; exit 3;; esac
mkdir -p "$LDIR" || { echo "LAUNCH_FAIL $TAG: cannot mkdir $LDIR" >&2; exit 4; }
LOG=$LDIR/$TAG.log; ST=$LDIR/$TAG.pid
[ -e "$ST" ] && { echo "LAUNCH_FAIL $TAG: $ST exists (duplicate launch; rm it only after checking)" >&2; exit 5; }
[ -d "$WD" ] || { echo "LAUNCH_FAIL $TAG: workdir $WD missing" >&2; exit 6; }
# ONE redirected simple command -> bash execs it in place, nothing survives holding the pipes.
# The payload stamps its own pid, so the confirmation below is specific to THIS launch (pgrep is
# not: it counts other runs of the same version, and once reported 3 for one job and 1 for a job
# that had already exited).
setsid bash -c 'cd "$1" || exit 9; echo $$ > "$2"; shift 2; exec "$@"' _ "$WD" "$ST" "$@" \
    > "$LOG" 2>&1 < /dev/null &
for _ in $(seq 1 20); do [ -s "$ST" ] && break; sleep 0.5; done
PID=$(cat "$ST" 2>/dev/null || true)
if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
  echo "LAUNCH_OK $TAG pid=$PID host=$(hostname) log=$LOG"
else
  echo "LAUNCH_FAIL $TAG: not running after 10 s" >&2; sed -n 1,20p "$LOG" >&2; exit 7
fi
