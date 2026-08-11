#!/usr/bin/env bash
# Evidence-driven replanning loop: run the chain, and when a leg fails,
# have the MODEL rewrite that leg using what the run actually walked, then
# resume from the last save instead of starting the whole route again.
#
# Nothing here authors game knowledge. On failure it hands the model three
# things it earned in play — the exploration graph (run/explored.json), the
# proven-unreachable ledger, and where the party currently stands — and asks
# it to audit its own plan. That is why a leg can be rewritten mid-campaign
# and the claim stays model-authored.
#
# Usage: campaign.sh <attempts> <plan1> [plan2 ...] [-- extra executor args]
set -euo pipefail
cd "$(dirname "$0")"

ATTEMPTS="${1:?usage: campaign.sh <attempts> <plan...> [-- extra args]}"; shift
PLANS=(); EXTRA=()
while [ $# -gt 0 ]; do
  [ "$1" = "--" ] && { shift; EXTRA=("$@"); break; }
  PLANS+=("$1"); shift
done
[ ${#PLANS[@]} -gt 0 ] || { echo "no plans given" >&2; exit 1; }

MODEL="${RED_MODEL:-gemma4:31b-it-q4_K_M}"
LOG=run/campaign.log
: > "$LOG"

# Description of where the party actually is, for the re-author's --start.
state_text() {
  python - <<'PY'
import json
try:
    o = json.load(open("run/obs.json"))
except Exception:
    print("a brand new game"); raise SystemExit
m = (o.get("map") or {}).get("id")
party = ", ".join(f"{p.get('species')} L{p.get('level')}"
                  for p in (o.get("party") or []))
badges = ", ".join(o.get("badges") or []) or "no badges"
bag = ", ".join(f"{k} x{v}" for k, v in (o.get("bag") or {}).items()) or "an empty bag"
print(f"standing in {m} with {party or 'no party'}, {badges}, and {bag}")
PY
}

first=1
for attempt in $(seq 1 "$ATTEMPTS"); do
  echo "=== attempt $attempt/$ATTEMPTS: ${PLANS[*]} ===" | tee -a "$LOG"

  # attempt 1 starts a new game; every later attempt resumes the save the
  # last successful leg wrote (--save-after-each), so work already done is
  # never repeated
  cont=()
  [ $first = 1 ] || cont=(--continue)
  set +e
  ./fresh_run.sh "${PLANS[@]}" "${cont[@]}" --save-after-each \
      --run-id "campaign${attempt}" --model "$MODEL" "${EXTRA[@]}" \
      2>&1 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
  set -e
  first=0

  if grep -q "RESULT: ALL PLANS COMPLETE" "$LOG"; then
    echo "=== campaign finished on attempt $attempt ===" | tee -a "$LOG"
    exit 0
  fi

  # which leg died, and what was it trying to do
  failed_plan=$(grep "===== PLAN:" "$LOG" | tail -1 | sed 's/.*PLAN: //; s/ =====//')
  [ -n "$failed_plan" ] || { echo "no failed plan identified" >&2; exit 1; }
  echo "--- rewriting plans/$failed_plan from evidence ---" | tee -a "$LOG"

  # Is this leg's OBJECTIVE already met? A plan can fail on a subgoal it
  # cannot satisfy (buy 5 Potions on an empty wallet) long after its real
  # aim is achieved. Re-authoring "Get the Boulder Badge" while wearing the
  # Boulder Badge burned two of three attempts on a solved problem — drop
  # the leg and get on with the route instead.
  if python - "plans/$failed_plan" run/obs.json <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
obs = json.load(open(sys.argv[2]))
last = (plan.get("subgoals") or [{}])[-1].get("done_when") or {}
ok = False
if "badge" in last:
    ok = last["badge"] in (obs.get("badges") or [])
elif "map" in last:
    ok = last["map"] == (obs.get("map") or {}).get("id")
elif "flag" in last:
    ok = bool((obs.get("flags") or {}).get(last["flag"]))
sys.exit(0 if ok else 1)
PY
  then
    echo "--- $failed_plan's objective is already met; moving on ---" \
        | tee -a "$LOG"
    keep=(); seen=0
    for p in "${PLANS[@]}"; do
      [ "$(basename "$p")" = "$failed_plan" ] && { seen=1; continue; }
      [ $seen = 1 ] && keep+=("$p")
    done
    if [ ${#keep[@]} -eq 0 ]; then
      echo "=== nothing left to run ===" | tee -a "$LOG"; exit 0
    fi
    PLANS=("${keep[@]}")
    echo "--- resuming with: ${PLANS[*]} ---" | tee -a "$LOG"
    continue
  fi

  goal=$(python - "plans/$failed_plan" <<'PY'
import json, sys
print(json.load(open(sys.argv[1])).get("goal", "continue the route"))
PY
)
  start=$(state_text)
  echo "    goal:  $goal"  | tee -a "$LOG"
  echo "    start: $start" | tee -a "$LOG"

  # NEVER rewrite the input plan in place. A killed campaign left a
  # DEGRADED plan behind under the original name (its audit dropped the
  # nerd flag, the one condition retreating cannot satisfy) and the next
  # launch silently ran the worse plan. Rewrites go to their own file and
  # the original is left untouched.
  base="${failed_plan%.json}"; base="${base%%.v[0-9]*}"
  rewritten="plans/${base}.v${attempt}.json"
  python planner/author.py --goal "$goal" --start "$start" \
      --out "$rewritten" --model "$MODEL" \
      --observed run/explored.json 2>&1 | tee -a "$LOG"
  if [ ! -s "$rewritten" ]; then
    echo "!! re-author produced nothing; keeping plans/$failed_plan" \
        | tee -a "$LOG"
    rewritten="plans/$failed_plan"
  fi

  # resume from the failed leg onward; earlier legs already succeeded and
  # their save is what --continue picks up
  keep=(); seen=0
  for p in "${PLANS[@]}"; do
    if [ "$(basename "$p")" = "$failed_plan" ]; then
      seen=1; keep+=("$rewritten"); continue
    fi
    [ $seen = 1 ] && keep+=("$p")
  done
  PLANS=("${keep[@]}")
  echo "--- resuming with: ${PLANS[*]} ---" | tee -a "$LOG"
done

echo "=== campaign exhausted $ATTEMPTS attempts ===" | tee -a "$LOG"
exit 1
