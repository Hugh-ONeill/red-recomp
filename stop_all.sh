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

# ---- LET IT SAVE FIRST. Both of the executor's save points sit at the END
# of an attempt, so a SIGTERM partway through one reached neither: run 11
# launched seven attempts and wrote three saves, and the four missing ones
# are exactly the attempts stopped to land a fix. One was carrying the
# Pokedex and the delivered parcel and the next attempt started before
# both. executor.py now saves between ops when asked to stop (see
# _install_stop_handler), but only if it is still holding a live game and
# nothing is about to start another attempt behind it.
#
# So the order is: silence the LOOPS, ask the EXECUTOR to stop and let it
# write, and only then tear down the game. Signalling them all at once —
# which is what the sweep below does — kills love out from under the save.
# EVERYTHING BENEATH WHAT REGISTERED, SNAPSHOTTED BEFORE THE FIRST SIGNAL.
# A loop killed with a child still running leaves that child to PID 1 —
# planner/author.py went on talking to ollama for a whole leg after the
# chain it belonged to was gone (2026-08-28), and nothing here could see it
# because only the loops and the executor ever register. The process tree
# is the record of what we started; read it while it still exists.
_PSTREE=$(mktemp)
ps -eo pid=,ppid= > "$_PSTREE"
descendants() {   # descendants <pid>... -> "pid depth", every live descendant
  local frontier="$*" depth=0 seen="" next p c
  while [ -n "$frontier" ]; do
    depth=$((depth + 1)); next=""
    for p in $frontier; do
      for c in $(awk -v P="$p" '$2 == P {print $1}' "$_PSTREE"); do
        case " $seen " in *" $c "*) continue ;; esac
        seen="$seen $c"; next="$next $c"
        echo "$c $depth"
      done
    done
    frontier="$next"
  done
}
_skip=$(ancestors | tr '\n' '|' | sed 's/|$//')
OURS=$(descendants $(registered | awk '{print $1}' | sed 's/^-//' | sort -u) \
       | grep -vE "^(${_skip}) " || true)
# ...and the inhibitor that wraps the chain (systemd-inhibit is the chain's
# PARENT, so no registration and no descent reaches it); killed last.
INHIBITOR=""
for _c in $(registered | awk '$2=="chain"{print $1}'); do
  _pp=$(ps -o ppid= -p "$_c" 2>/dev/null | tr -d ' ')
  [ -n "$_pp" ] && ps -o args= -p "$_pp" 2>/dev/null | grep -q "systemd-inhibit" \
    && ! echo "$_pp" | grep -qE "^(${_skip})$" && INHIBITOR="$INHIBITOR $_pp"
done
rm -f "$_PSTREE"

loops=$(registered | awk '$2=="chain" || $2=="campaign" || $2=="run" {print $1}')
if [ -n "$loops" ]; then
  echo "quieting the loops so nothing starts another attempt: $(echo $loops)"
  for p in $loops; do kill -TERM "$p" 2>/dev/null || true; done
fi
execs=$(registered | awk '$2=="executor"{print $1}')
if [ -n "$execs" ]; then
  echo "asking the executor to stop and save: $(echo $execs)"
  for p in $execs; do kill -TERM "$p" 2>/dev/null || true; done
  # 25s was not enough: most of an escalation's wall clock is inside a
  # model call, and the handler cannot run until that returns. Wait out a
  # slow generation rather than SIGKILLing a run mid-attempt.
  for _ in $(seq 1 90); do
    [ -z "$(registered | awk '$2=="executor"{print $1}')" ] && break
    sleep 1
  done
  left=$(registered | awk '$2=="executor"{print $1}')
  [ -n "$left" ] && echo "   (still running after 90s; the sweep will take it)"
fi

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
# CHILDREN OF OURS THAT NEVER REGISTERED, deepest first — the orphan class.
ours_left() {
  echo "$OURS" | while read -r pid depth; do
    [ -n "${pid:-}" ] || continue
    kill -0 "$pid" 2>/dev/null && [ "$(rig_state "$pid")" != "Z" ] && echo "$pid $depth"
  done | sort -k2,2nr
}
left=$(ours_left)
if [ -n "$left" ]; then
  echo "stopping children of ours that never registered (deepest first):"
  ps -o pid,args -p "$(echo "$left" | awk '{print $1}' | tr '\n' ',' | sed 's/,$//')" 2>/dev/null | sed 's/^/   /'
  for sig in TERM KILL; do
    left=$(ours_left)
    [ -z "$left" ] && break
    echo "$left" | while read -r pid depth; do kill -"$sig" "$pid" 2>/dev/null || true; done
    sleep 3
  done
fi
for _p in $INHIBITOR; do
  if kill -0 "$_p" 2>/dev/null; then
    echo "releasing the sleep inhibitor: $_p"
    kill -TERM "$_p" 2>/dev/null || true
  fi
done

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
left=$(ours_left)
if [ -n "$left" ]; then
  echo "!! OF OURS AND STILL RUNNING (children of what registered): $(echo "$left" | awk '{print $1}' | tr '\n' ' ')" >&2
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
