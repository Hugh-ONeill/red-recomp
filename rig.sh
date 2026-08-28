#!/usr/bin/env bash
# The rig's own list of what it started. Sourced, never run.
#
# WHY THIS EXISTS. stop_all.sh used to find things to kill with a regex over
# `ps -eo pid,args` — "executor.py --bootstrap|love \.|campaign(\.run)?\.sh|
# fresh_run\.sh|fresh_discovery\.sh|xvfb-run" — which is a pattern kill
# across the whole box. Our own rule, written after a local Showdown server
# belonging to something else was killed by exactly this shape, is to kill
# only PIDs we started. A pattern cannot tell our `love .` from anyone
# else's, and `xvfb-run` on its own is a machine-wide match.
#
# So every launcher registers what it starts, and stop_all takes down that
# list and nothing else.
#
# A PID ALONE IS NOT AN IDENTITY. PIDs are reused, and a registry entry
# outlives the process it names — kill a stale one and you have killed a
# stranger, which is the very thing this is here to prevent. Each entry
# carries the process's START TIME from /proc, which together with the PID
# is unique for as long as the machine is up.

RIG_PIDS="${RIG_PIDS:-run/rig.pids}"

rig_starttime() {   # rig_starttime <pid> -> jiffies since boot, or fail
  [ -r "/proc/$1/stat" ] || return 1
  # a process's comm can contain spaces AND parentheses, so field counting
  # from the left is wrong; everything after the LAST ')' is fixed-width,
  # and starttime (field 22) is the 20th of those.
  sed 's/.*) //' "/proc/$1/stat" 2>/dev/null | awk '{print $20}'
}

rig_register() {    # rig_register <kind> [pid]   (pid<0 means "its group")
  local kind="$1" pid="${2:-$$}" probe st
  probe="${pid#-}"
  st=$(rig_starttime "$probe") || return 0
  [ -n "$st" ] || return 0
  mkdir -p "$(dirname "$RIG_PIDS")"
  printf '%s\t%s\t%s\n' "$pid" "$st" "$kind" >> "$RIG_PIDS"
}

rig_state() {       # rig_state <pid> -> R/S/D/Z/T..., or fail
  [ -r "/proc/$1/stat" ] || return 1
  sed 's/.*) //' "/proc/$1/stat" 2>/dev/null | awk '{print $1}'
}
rig_alive() {       # rig_alive <pid> <starttime> — same process, still here?
  # A ZOMBIE IS GONE: it has exited and only waits on its parent to reap
  # it; /proc still answers for it, so start time alone said "alive" and
  # stop_all refused ALL CLEAR over a corpse (2026-08-28).
  local probe="${1#-}" now
  now=$(rig_starttime "$probe") || return 1
  [ "$now" = "$2" ] || return 1
  [ "$(rig_state "$probe")" != "Z" ]
}
