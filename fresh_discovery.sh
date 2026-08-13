#!/usr/bin/env bash
# A clean-room run: new game, empty ledgers, and goals that name an
# OBJECTIVE and nothing else.
#
# Every previous chain handed the model the route in its goal string —
# "Get the Boulder Badge from Brock in Pewter City", "Travel from Pewter
# City through Mt Moon and reach Cerulean City" — which names the town, the
# gym leader and the mountain before the model has walked a step. These
# goals name only what winning looks like. Where Brock is, that a forest
# lies between, that a parcel opens the road north: the model's own
# knowledge of Red supplies all of it, or the run discovers it in play.
#
# Authoring happens AFTER the ledgers are cleared, so no plan is written
# with a previous world's graph or journal in front of it.
#
# Usage: fresh_discovery.sh [attempts]   (default 5)
set -euo pipefail
cd "$(dirname "$0")"
ATTEMPTS="${1:-5}"
MODEL="${RED_MODEL:-gemma4:31b-it-q4_K_M}"

pgrep -f 'executor.py|love' >/dev/null && {
  echo "a run is still live — stop it first" >&2; exit 1; }

ts=$(date +%H%M%S)
[ -f run/explored.json ] && cp run/explored.json "run/explored.${ts}.pre-discovery.bak.json"
[ -f run/executor_log.jsonl ] && mv run/executor_log.jsonl "run/executor_log.${ts}.pre-discovery.jsonl"
rm -f run/explored.json run/last_state.json
echo "archived ${ts}.pre-discovery; ledgers cleared"

# One goal per badge. No place names, no NPC names, no badge names — the
# model picks which badge is "first" and where it lives.
author () {   # author <out> <goal> <start-or-empty>
  local out="$1" goal="$2" start="${3:-}"
  [ -s "$out" ] && { echo "keeping existing $out"; return; }
  echo "--- authoring $out: $goal"
  if [ -n "$start" ]; then
    python planner/author.py --goal "$goal" --start "$start" \
        --out "$out" --model "$MODEL"
  else
    python planner/author.py --goal "$goal" --out "$out" --model "$MODEL"
  fi
}

# The first leg gets no --start at all, so NEW_GAME_START describes only
# where the player is standing, not what to do about it.
author plans/discovery_1.json "Win your first Gym Badge"
author plans/discovery_2.json "Win your second Gym Badge" \
       "having won one Gym Badge, with the party that won it"
author plans/discovery_3.json "Win your third Gym Badge" \
       "having won two Gym Badges, with the party that won them"

exec env RED_HEADED="${RED_HEADED:-1}" RED_SPEED="${RED_SPEED:-200}" \
    ./campaign.sh "$ATTEMPTS" \
    plans/discovery_1.json plans/discovery_2.json plans/discovery_3.json \
    -- --escalate
