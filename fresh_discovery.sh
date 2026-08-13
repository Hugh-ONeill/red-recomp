#!/usr/bin/env bash
# Outline-first clean-room chain: the MODEL writes the playthrough outline
# (best-of-3 drafts at ~20 objectives, choose-only merge, consensus
# confirm, constrained review), then each objective becomes a leg authored
# AT THE MOMENT IT STARTS — with the walked graph and journal in front of
# the audit pass — and campaign.sh runs it under the usual evidence-driven
# replan loop. The leg STRUCTURE is the model's own; ours was the seeding
# (DONE.md 2026-08-13c).
#
# Luck is paid once and banked: outline.txt, leg plans, ledgers, and the
# save all persist, and run/outline_leg records how far the chain got, so
# a restart re-rolls nothing that already worked. Doubts the outline
# passes recorded about their own product (plans/outline.notes) are handed
# back to the leg author as its own words when that leg comes up.
#
# Usage: fresh_discovery.sh [attempts-per-leg]   (default 4)
set -euo pipefail
cd "$(dirname "$0")"
ATTEMPTS="${1:-4}"
MODEL="${RED_MODEL:-gemma4:31b-it-q4_K_M}"
SAVE="$HOME/.local/share/love/pokemon-love2d/saves/red/slot1.lua"

# Match real processes only: -f over full cmdlines also matches ANCESTOR
# shells whose command text merely mentions these names (a launcher that
# ran "git add planner/executor.py" earlier in the same compound command
# blocked its own chain twice).
if pgrep -x love >/dev/null \
    || pgrep -f '^python[0-9.]* planner/executor\.py' >/dev/null; then
  echo "a run is still live — stop it first" >&2; exit 1
fi

PROGRESS=run/outline_leg
done_legs=$(cat "$PROGRESS" 2>/dev/null || echo 0)

# A truly fresh chain archives the previous world — ledgers, journal, and
# the save itself — before anything is authored, so no plan is written
# with a previous world's graph in front of it. A mid-chain restart
# (done_legs > 0) keeps everything: that world is this world.
if [ "$done_legs" = 0 ]; then
  ts=$(date +%H%M%S)
  [ -f run/explored.json ] && cp run/explored.json "run/explored.${ts}.pre-discovery.bak.json"
  [ -f run/executor_log.jsonl ] && mv run/executor_log.jsonl "run/executor_log.${ts}.pre-discovery.jsonl"
  [ -f "$SAVE" ] && cp "$SAVE" "run/slot1.${ts}.pre-discovery.lua"
  rm -f run/explored.json run/last_state.json
  echo "archived ${ts}.pre-discovery; ledgers cleared"
fi

if [ -s plans/outline.txt ]; then
  echo "keeping existing plans/outline.txt"
else
  # a new outline invalidates every leg plan written for the old one
  rm -f plans/leg_[0-9]*.json plans/outline.notes
  echo "--- authoring the outline"
  python planner/author.py --outline --goal "Become the Champion" \
      --out plans/outline.txt --model "$MODEL"
fi

mapfile -t LEGS < plans/outline.txt
echo "=== outline: ${#LEGS[@]} legs, starting at leg $((done_legs + 1)) ==="

i=0
for leg in "${LEGS[@]}"; do
  i=$((i + 1))
  [ "$i" -le "$done_legs" ] && continue
  plan=$(printf 'plans/leg_%02d.json' "$i")

  # the outline's own doubt about this leg rides along in the goal string
  goal="$leg"
  note=$(awk -F'\t' -v L="$leg" '$1==L{print $2; exit}' \
      plans/outline.notes 2>/dev/null || true)
  [ -n "$note" ] && goal="$leg (a doubt you recorded when outlining: $note)"

  if [ -s "$plan" ]; then
    echo "=== leg $i/${#LEGS[@]}: keeping existing $plan"
  else
    echo "=== leg $i/${#LEGS[@]}: authoring — $goal"
    aargs=(--goal "$goal" --out "$plan" --model "$MODEL")
    if [ "$i" -gt 1 ]; then
      aargs+=(--start "$(python planner/state_text.py)")
      [ -s run/explored.json ] && aargs+=(--observed run/explored.json)
      [ -s run/executor_log.jsonl ] && aargs+=(--journal run/executor_log.jsonl)
    fi
    python planner/author.py "${aargs[@]}"
  fi

  cont=0; [ "$i" -gt 1 ] && cont=1
  if ! env RED_HEADED="${RED_HEADED:-1}" RED_SPEED="${RED_SPEED:-200}" \
      RED_CONTINUE=$cont ./campaign.sh "$ATTEMPTS" "$plan" -- --escalate; then
    echo "=== chain stopped at leg $i/${#LEGS[@]}: $leg ===" >&2
    exit 1
  fi
  echo "$i" > "$PROGRESS"
  echo "=== leg $i/${#LEGS[@]} complete: $leg ==="
done

echo "=== OUTLINE CHAIN COMPLETE: all ${#LEGS[@]} legs ==="
