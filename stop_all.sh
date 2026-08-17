#!/usr/bin/env bash
# Tear the rig down and VERIFY it is down.
#
# Three separate campaigns this session were contaminated by an executor that
# outlived its game: `pgrep -f ... | while read p; do kill $p; done` aborts the
# pipeline when pgrep exits non-zero, so a missed process looked like success.
# Kill by PID list, re-read, escalate to -9, and only then report clear.
#
# KILL ONLY WHAT WE STARTED. The version before this one found its victims
# with a regex over every process on the box — `love \.`, `xvfb-run`,
# `campaign(\.run)?\.sh` — which is a pattern kill by another name, and the
# rule against those was written after one took down a local server that
# belonged to something else entirely. Now the launchers register what they
# start (rig.sh -> run/rig.pids, PID plus its /proc start time so a reused
# PID can never be mistaken for ours) and this kills that list.
#
# The pattern survives as a REPORT ONLY. Losing "verify it is down" would be
# a worse bug than the one being fixed, so anything matching the old regex
# and still running is printed with its full command line — and left alone.
# `--force` kills those too, which is the old behaviour, now something you
# have to ask for by name.
set -uo pipefail
cd "$(dirname "$0")"
# shellcheck source=rig.sh
. ./rig.sh

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

ancestors() {   # this script and everything that launched it, never killed
  local p=$$
  while [ "$p" -gt 1 ]; do
    echo "$p"
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
    [ -z "$p" ] && break
  done
}

registered() {  # live entries from the registry, as signal targets
  local skip pid st kind
  skip=$(ancestors | tr '\n' '|' | sed 's/|$//')
  [ -f "$RIG_PIDS" ] || return 0
  while IFS=$'\t' read -r pid st kind; do
    [ -n "${pid:-}" ] || continue
    rig_alive "$pid" "$st" || continue
    echo "${pid#-}" | grep -qE "^(${skip})$" && continue
    echo "$pid $kind"
  done < "$RIG_PIDS" | sort -u
}

strays() {      # NOT killed by default: reported, so a miss is still visible
  local skip
  skip=$(ancestors | tr '\n' '|' | sed 's/|$//')
  ps -eo pid,args \
    | grep -E "executor\.py --bootstrap|love \.|campaign(\.run)?\.sh|fresh_run\.sh|fresh_discovery\.sh|xvfb-run" \
    | grep -v grep \
    | grep -vE "shell-snapshots|stop_all\.sh" \
    | awk '{print $1}' \
    | grep -vE "^(${skip})$"
}

for sig in TERM TERM KILL; do
  list=$(registered)
  [ -z "$list" ] && break
  echo "sending SIG$sig to: $(echo "$list" | tr '\n' ' ')"
  while read -r pid kind; do
    [ -n "${pid:-}" ] || continue
    # a negative pid is a process GROUP the rig created with setsid
    kill -"$sig" "$pid" 2>/dev/null || true
  done <<< "$list"
  sleep 3
done

# prune entries whose process is gone, so the registry does not grow a tail
# of dead PIDs that a later reuse could turn into a stranger
if [ -f "$RIG_PIDS" ]; then
  keep=$(while IFS=$'\t' read -r pid st kind; do
           [ -n "${pid:-}" ] || continue
           rig_alive "$pid" "$st" && printf '%s\t%s\t%s\n' "$pid" "$st" "$kind"
         done < "$RIG_PIDS")
  printf '%s' "${keep:+$keep$'\n'}" > "$RIG_PIDS"
fi

left=$(registered)
if [ -n "$left" ]; then
  echo "!! REGISTERED AND STILL RUNNING: $(echo "$left" | tr '\n' ' ')" >&2
  exit 1
fi

others=$(strays)
if [ -n "$others" ]; then
  if [ "$FORCE" = 1 ]; then
    echo "--force: killing unregistered matches too"
    for p in $others; do kill -KILL "$p" 2>/dev/null || true; done
    sleep 2
    others=$(strays)
  fi
fi
if [ -n "$others" ]; then
  echo "-- nothing of ours is running, but these LOOK like rig processes" >&2
  echo "   and were NOT started by anything that registered, so they are" >&2
  echo "   left alone. Check them, then --force if they really are ours:" >&2
  # >&2 BEFORE 2>/dev/null, or stdout is pointed at an already-redirected
  # fd 2 and the whole listing goes to /dev/null — which is what the first
  # version of this line did, printing the warning and then nothing to
  # check.
  ps -o pid,args -p "$(echo "$others" | tr '\n' ',' | sed 's/,$//')" \
     >&2 2>/dev/null
  exit 2
fi
echo "ALL CLEAR — no registered executor, game, or campaign loop running"
