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
# What the run is FOR, in the player's own words. It is the only thing the
# outline pass is given, so it decides what the model thinks the game is —
# "Become the Champion" produces a list of badges and the errands between
# them. Overridable so the framing itself can be tested.
GOAL="${RED_GOAL:-Become the Champion}"
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
  # ...and RETIRE it. Copying alone left the save in place, so the game
  # auto-loaded it and bootstrap's new_game hit CONTINUE instead: a "fresh"
  # chain woke up on Route 6 wearing three badges and set about authoring
  # "Obtain a starter Pokemon" for a party holding an L43 Venusaur. The
  # copy above is the only thing that makes this safe — take it first.
  rm -f "$SAVE" "$SAVE.bak"
  # obs.json is the LIVE world snapshot and outlives the process that wrote
  # it. Left in place it lies twice about a world that no longer exists:
  # fresh_run.sh takes its existence as "the game is up" (so the wait for
  # the new process returns at once), and campaign.sh's already-met check
  # falls back to it — a three-badge obs certifies the Brock, Misty and
  # Surge legs complete on a badgeless new game. Same false-completion
  # class as the stale-flag resume teleport.
  rm -f run/explored.json run/last_state.json run/obs.json \
        run/status.txt run/heartbeat
  # the reorder budget belongs to a chain, not to the directory
  : > run/outline_reorders
  echo "archived ${ts}.pre-discovery; ledgers cleared"
fi

if [ -s plans/outline.txt ]; then
  echo "keeping existing plans/outline.txt"
else
  # a new outline invalidates every leg plan written for the old one
  rm -f plans/leg_[0-9]*.json plans/outline.notes
  echo "--- authoring the outline"
  echo "goal: $GOAL"
  python planner/author.py --outline --goal "$GOAL" \
      --out plans/outline.txt --model "$MODEL"
fi

# The outline is re-read EVERY iteration: a stuck leg may pull a later
# leg forward (the model reordering its own outline on play evidence), and
# the loop must see the new order at once.
while :; do
  mapfile -t LEGS < plans/outline.txt
  done_legs=$(cat "$PROGRESS" 2>/dev/null || echo 0)
  i=$((done_legs + 1))
  if [ "$i" -gt "${#LEGS[@]}" ]; then
    echo "=== OUTLINE CHAIN COMPLETE: all ${#LEGS[@]} legs ==="
    exit 0
  fi
  leg="${LEGS[$((i - 1))]}"
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
    # A leg can exhaust its attempts long after its aim was achieved (the
    # fossil leg failed three rewrites HOLDING the fossil). Whether the
    # objective is in fact done is the model's judgment to make; the chain
    # only asks, and only moves on if the answer is yes.
    if python planner/author.py --check-done --goal "$goal" \
        --start "$(python planner/state_text.py)" \
        --observed run/explored.json --model "$MODEL"; then
      echo "=== leg $i/${#LEGS[@]} judged already accomplished: $leg ==="
      echo "$i" > "$PROGRESS"
      continue
    fi
    # Or the leg is stuck because a LATER leg of the model's own outline
    # has to happen first (Surge's gym behind a CUT bush, with "Obtain
    # the HM for Cut" two legs later). The model names the blocking leg
    # and the harness pulls it forward — choose-only, bounded.
    if [ "$(cat run/outline_reorders 2>/dev/null | wc -l)" -lt 8 ] \
        && blocker=$(python planner/author.py --check-blocker \
            --goal "$goal" --outline-path plans/outline.txt --leg "$i" \
            --start "$(python planner/state_text.py)" \
            --journal run/executor_log.jsonl --model "$MODEL"); then
      echo "=== leg $i stuck behind leg $blocker: pulling it forward ==="
      python - "$i" "$blocker" <<'PY'
import sys
i, b = int(sys.argv[1]), int(sys.argv[2])
lines = [l for l in open('plans/outline.txt').read().splitlines()
         if l.strip()]
mv = lines.pop(b - 1)
lines.insert(i - 1, mv)
open('plans/outline.txt', 'w').write('\n'.join(lines) + '\n')
print('pulled forward:', mv)
PY
      echo "$i<-$blocker" >> run/outline_reorders
      n=$i
      while [ "$n" -le "${#LEGS[@]}" ]; do
        rm -f "$(printf 'plans/leg_%02d' "$n")".json \
              "$(printf 'plans/leg_%02d' "$n")".v*.json
        n=$((n + 1))
      done
      continue
    fi
    echo "=== chain stopped at leg $i/${#LEGS[@]}: $leg ===" >&2
    exit 1
  fi
  echo "$i" > "$PROGRESS"
  echo "=== leg $i/${#LEGS[@]} complete: $leg ==="
done
