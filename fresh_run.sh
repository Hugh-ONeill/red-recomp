#!/usr/bin/env bash
# One-shot executor run against a FRESH game process. new_game from a
# mid-session game lands in a ui state bootstrap can't clear, so a
# bootstrapped run must own its own process start-to-finish.
# Usage: fresh_run.sh <plan> [extra executor args...]
set -euo pipefail
PLAN="$1"; shift
cd "$(dirname "$0")"
setsid ./run.sh 200 &
GAME_PID=$!
# kill the whole process group: xvfb-run's cleanup does not reliably reach
# love, which otherwise survives as an orphan on the dead Xvfb display
trap 'kill -- -"$GAME_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do [ -f run/obs.json ] && break; sleep 1; done
[ -f run/obs.json ] || { echo "game did not come up" >&2; exit 1; }
python planner/executor.py "$PLAN" --bootstrap --escalate "$@"
