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
# Workdir first, so a bad workdir cannot leave a reservation behind and poison the tag.
[ -d "$WD" ] || { echo "LAUNCH_FAIL $TAG: workdir $WD missing" >&2; exit 6; }
# Reserve the tag ATOMICALLY (O_EXCL, via noclobber) BEFORE forking. A bare `[ -e "$ST" ]` test is a
# TOCTOU race: the stamp is written by the payload only after fork+exec, so two simultaneous launches
# both passed the test and both started -- measured, they printed the SAME pid while a second,
# untracked payload ran alongside. The payload overwrites this empty file with its real pid, so the
# `[ -s "$ST" ]` poll below keeps its meaning. Two branches, because a one-liner would report an
# unwritable LAUNCH_DIR as a duplicate launch.
if ! ( set -C; : > "$ST" ) 2>/dev/null; then
  if [ -e "$ST" ]; then
    P=$(cat "$ST" 2>/dev/null || true)
    if [ -z "${P:-}" ]; then
      # Reserved but not yet stamped: another launch is between the reservation and the payload's
      # first instruction. Saying "stale, rm it" here would talk an operator into deleting a LIVE
      # reservation -- which is what the pre-atomic version effectively did.
      echo "LAUNCH_FAIL $TAG: another launch is in flight (reserved moments ago, not yet stamped). Retry in a few seconds; only rm '$ST' if you are certain no launch is in progress." >&2
    elif kill -0 "$P" 2>/dev/null; then
      echo "LAUNCH_FAIL $TAG: already RUNNING as pid $P on $(hostname); watch $LOG" >&2
    else
      echo "LAUNCH_FAIL $TAG: stale state $ST (pid $P is gone; see $LOG). If that run is finished: rm '$ST' and relaunch." >&2
    fi
    exit 5
  fi
  echo "LAUNCH_FAIL $TAG: cannot create $ST in $LDIR" >&2; exit 4
fi
# ONE redirected simple command -> bash execs it in place, nothing survives holding the pipes.
# The payload stamps its own pid, so the confirmation below is specific to THIS launch (pgrep is
# not: it counts other runs of the same version, and once reported 3 for one job and 1 for a job
# that had already exited).
printf '=== %s %s on %s ===\n' "$(date -Is)" "$TAG" "$(hostname)" >> "$LOG"
# Append, never truncate: a relaunch of the same tag must not destroy the evidence from the run that
# made you relaunch.
setsid bash -c 'cd "$1" || exit 9; echo $$ > "$2"; shift 2; exec "$@"' _ "$WD" "$ST" "$@" \
    >> "$LOG" 2>&1 < /dev/null &
STAMPED=no
for _ in $(seq 1 20); do [ -s "$ST" ] && { STAMPED=yes; break; }; sleep 0.5; done
PID=$(cat "$ST" 2>/dev/null || true)
if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
  echo "LAUNCH_OK $TAG pid=$PID host=$(hostname) log=$LOG"
elif [ "$STAMPED" = yes ]; then
  # Started and already finished. NOT a launch failure -- a short payload is legitimate, and
  # baseline_run.sh's own REFUSED guard exits in milliseconds, so treating this as a failure would
  # mark every refused arm as unlaunchable. The tag must stay reusable, so the stamp is set aside.
  echo "LAUNCH_EXITED $TAG: payload started (pid=$PID) and exited within the confirmation window; log=$LOG" >&2
  SURV=$(pgrep -s "$PID" 2>/dev/null | tr '\n' ' ')
  [ -n "$SURV" ] && echo "  WARNING: session $PID still has processes: $SURV" >&2
  tail -n 20 "$LOG" 2>/dev/null >&2; mv -f "$ST" "$ST.exited"; exit 8
else
  echo "LAUNCH_FAIL $TAG: payload never started (cd or exec failed); log=$LOG" >&2
  tail -n 20 "$LOG" 2>/dev/null >&2; rm -f "$ST"; exit 7
fi
