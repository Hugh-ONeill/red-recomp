#!/usr/bin/env bash
# Tear the whole rig down and VERIFY it is down.
#
# Three separate campaigns this session were contaminated by an executor that
# outlived its game: `pgrep -f ... | while read p; do kill $p; done` aborts the
# pipeline when pgrep exits non-zero, so a missed process looked like success.
# Kill by PID list, re-read, escalate to -9, and only then report clear.
set -uo pipefail
cd "$(dirname "$0")"

pids() {   # executors, games, loops — never anything else
  ps -eo pid,args \
    | grep -E "executor\.py --bootstrap|love \.|campaign(\.run)?\.sh|fresh_run\.sh|xvfb-run" \
    | grep -v grep | awk '{print $1}'
}

for sig in TERM TERM KILL; do
  list=$(pids)
  [ -z "$list" ] && break
  echo "sending SIG$sig to: $(echo "$list" | tr '\n' ' ')"
  for p in $list; do kill -"$sig" "$p" 2>/dev/null || true; done
  sleep 3
done

left=$(pids)
if [ -n "$left" ]; then
  echo "!! STILL RUNNING: $(echo "$left" | tr '\n' ' ')" >&2
  ps -o pid,args -p $(echo "$left" | tr '\n' ',' | sed 's/,$//') 2>/dev/null >&2
  exit 1
fi
echo "ALL CLEAR — no executor, game, or campaign loop running"
