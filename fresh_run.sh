#!/usr/bin/env bash
# One-shot executor run against a FRESH game process. new_game from a
# mid-session game lands in a ui state bootstrap can't clear, so a
# bootstrapped run must own its own process start-to-finish.
# Usage: fresh_run.sh <plan...> [extra executor args...]
# NOTE: pass --escalate yourself for authoring runs; a bare invocation is
# a REPLAY run (macros only — a failed subgoal fails the plan). Multiple
# plan files chain in order (executor.py plans nargs='+'); --continue
# resumes the on-disk save instead of new_game.
set -euo pipefail
cd "$(dirname "$0")"
# RED_HEADED=1 opens a real window (run.sh --headed) and RED_SPEED sets the
# clock: 200x is a blur to watch, 10-20x is followable by eye.
setsid ./run.sh ${RED_HEADED:+--headed} "${RED_SPEED:-200}" &
GAME_PID=$!
# kill the whole process group: xvfb-run's cleanup does not reliably reach
# love, which otherwise survives as an orphan on the dead Xvfb display
trap 'kill -- -"$GAME_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do [ -f run/obs.json ] && break; sleep 1; done
[ -f run/obs.json ] || { echo "game did not come up" >&2; exit 1; }
# THE MODEL-AUTHORED SPEC IS THE ONE THAT PLAYS. battle_policy's own
# header says the hand-seeded DEFAULT_SPEC "exists for spine/oracle
# validation only; the record run requires a model-authored spec" — and
# nothing ever passed --policy-spec, so every battle of the record run was
# fought on the seed. plans/policy_model_v1.json had been sitting there
# authored and live-evaluated (6/6 rival, 3/3 badge, 0 blackouts, beating
# the typed_v0 baseline on oracle agreement 47 to 36) and never once used.
# Newest by version, overridable, and silent if there is none.
POLICY="${RED_POLICY:-$(ls -1 plans/policy_model_v*.json 2>/dev/null \
        | sort -V | tail -1 || true)}"
pol=()
if [ -n "$POLICY" ] && [ -s "$POLICY" ]; then
  pol=(--policy-spec "$POLICY")
  echo "[policy] $POLICY"
fi
python planner/executor.py --bootstrap "$@" "${pol[@]}"
