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
  # these budgets belong to a chain, not to the directory
  : > run/outline_reorders
  rm -f run/outline_skips run/outline_inserts run/outline_rewordings \
        run/outline_pulls run/outline_pulls_failed
  echo "archived ${ts}.pre-discovery; ledgers cleared"
fi

if [ -s plans/outline.txt ]; then
  echo "keeping existing plans/outline.txt"
else
  # a new outline invalidates every leg plan written for the old one
  rm -f plans/leg_[0-9]*.json plans/outline.notes plans/outline.done
  echo "--- authoring the outline"
  echo "goal: $GOAL"
  python planner/author.py --outline --goal "$GOAL" \
      --out plans/outline.txt --model "$MODEL"
fi


# WORK ALREADY FINISHED, CROSSED OFF BEFORE IT IS EVER ATTEMPTED. The
# chain's only record of progress is a high-water mark, so an objective
# satisfied out of order stays on the list and is eventually walked in
# full — four attempts, a rewrite apiece, half an hour — before the
# exhaustion gate thinks to ask whether it was needed. This asks first.
#
# It runs at the END OF EVERY LEG, won or lost, and in the lost case it
# runs BEFORE the reorder rung, so what that rung is choosing among is a
# list of real outstanding work. Leg 11 exhausted holding the SILPH SCOPE
# with "Retrieve the Silph Scope from Team Rocket" still sitting at 17.
#
# The judgment is the model's, twice over (a sweep of the remaining list,
# then a yes/no on each objective it names, refused outright for any that
# names a map the run has never stood on). The harness only crosses off.
sweep_ahead() {
  local at="$1" st got nums n
  st=$(python planner/state_text.py)
  if [ "$(cat run/outline_skips 2>/dev/null | wc -l)" -lt 8 ] \
      && got=$(python planner/author.py --check-already-done \
          --goal "$leg" --outline-path plans/outline.txt --leg "$at" \
          --start "$st" --observed run/explored.json --model "$MODEL") \
      && [ -n "$got" ]; then
    nums=$(printf '%s\n' "$got" | cut -f1 | tr '\n' ' ')
    if python planner/skip_legs.py $nums; then
      printf '%s\n' "$got" >> run/outline_skips
      # positions after this leg have shifted, so their plans name the
      # wrong objective now — the cleanup the reorder rung already does
    fi
  fi
  # ...AND THE WORK IT NEVER THOUGHT TO LIST. The sweep above can only
  # cross off objectives that were written down. The Silph Scope came out
  # of the hideout during a leg that named the wrong key, so no line
  # anywhere said so: the run held a thing that opens the Pokemon Tower
  # and had no way to think of it as an accomplishment, only as an item.
  # Nothing is ever scheduled from outline.done — it is recognition, and
  # it says what each deed opens, which is what makes the next objective
  # thinkable.
  python planner/author.py --recognize-done \
      --goal "$leg" --outline-path plans/outline.txt \
      --start "$st" --model "$MODEL" || true
}

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
  # A PLAN BELONGS TO AN OBJECTIVE, NOT TO A SLOT. Plans were addressed by
  # outline position, so any rearrangement left every plan from the shift
  # onward naming the wrong objective — and the rungs "fixed" that by
  # deleting them, one pull-forward taking all eleven leg_11 rewrites with
  # it. But pulling a leg ahead only says THAT ONE was misordered against
  # the others (user, 2026-08-15): the rest kept their order, their work
  # and their evidence, and a pull is exactly the move that would have
  # been right for the Silph Scope leg had the sweep not already crossed
  # it off. find_plan asks each plan which objective it was written for,
  # and takes the highest rewrite of the one that matches — so a reorder
  # invalidates nothing, and RESUMING FROM THE LATEST REWRITE (ten
  # restarts once meant ten fresh trips to the day care for a Charizard
  # already in the party) comes free rather than by version-sorting names.
  # A reworded objective matches nothing and is authored fresh, which is
  # right: that leg really is a different one now.
  plan=$(python planner/find_plan.py "$leg" 2>/dev/null || true)
  if [ -z "$plan" ]; then
    # first time this objective has been planned. The position in the
    # name is only where it was written, never how it is found again.
    slug=$(printf '%s' "$leg" | tr '[:upper:]' '[:lower:]' \
           | tr -cs 'a-z0-9' '_' | cut -c1-40)
    plan=$(printf 'plans/leg_%02d_%s.json' "$i" "${slug%_}")
  fi

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

  # WHAT THIS LEG GAINS IS THE EVIDENCE FOR WHETHER IT IS DONE. Snapshot
  # before it runs so a failed leg can still be judged on what it actually
  # achieved — the fossil leg walked out of Mt Moon HOLDING the fossil and
  # failed three rewrites anyway, and a fused objective ("the parcel from
  # Bill", two errands welded together) can only be settled this way.
  # ...and snapshot ONCE PER LEG, not once per process. This ran on every
  # chain start, so restarting mid-leg reset the baseline: leg 11 was
  # judged NOT_DONE on evidence reading "gained a HYPER_POTION and beat one
  # trainer" while the SILPH SCOPE and LIFT KEY — won in an earlier attempt
  # of the same leg — sat in the bag unmentioned. The stamp records which
  # leg the baseline belongs to; a genuinely new leg re-takes it.
  if [ "$(cat run/leg_start.leg 2>/dev/null || echo '')" != "$i" ]; then
    python planner/leg_delta.py snap run/leg_start.json 2>/dev/null || true
    echo "$i" > run/leg_start.leg
  else
    echo "=== leg $i: keeping the baseline taken when this leg began ==="
  fi

  cont=0; [ "$i" -gt 1 ] && cont=1
  if ! env RED_HEADED="${RED_HEADED:-1}" RED_SPEED="${RED_SPEED:-200}" \
      RED_CONTINUE=$cont ./campaign.sh "$ATTEMPTS" "$plan" -- --escalate; then
    # A leg can exhaust its attempts long after its aim was achieved (the
    # fossil leg failed three rewrites HOLDING the fossil). Whether the
    # objective is in fact done is the model's judgment to make; the chain
    # only asks, and only moves on if the answer is yes.
    gained=$(python planner/leg_delta.py diff run/leg_start.json \
        2>/dev/null || true)
    [ -n "$gained" ] && echo "    gained: $gained"
    if python planner/author.py --check-done --goal "$goal" \
        --start "$(python planner/state_text.py)" \
        --gained "$gained" \
        --observed run/explored.json --model "$MODEL"; then
      echo "=== leg $i/${#LEGS[@]} judged already accomplished: $leg ==="
      echo "$i" > "$PROGRESS"
      sweep_ahead "$i"
      continue
    fi
    sweep_ahead "$i"
    # A PULL THAT DID NOT UNSTICK ANYTHING GOES HOME. This leg may itself
    # be one that was moved here, and it has now failed in its new slot
    # too — so the move bought nothing and cost the leg it displaced.
    # Leaving it costs the run twice over, and the reorder budget gets
    # spent defending the mistake. Bounded hard at two: an undo hands the
    # same leg back to the same ladder, and the point is to get out of
    # the loop, not to walk round it.
    if [ "$(cat run/outline_pulls_failed 2>/dev/null | wc -l)" -lt 2 ] \
        && python planner/pull_leg.py undo "$i"; then
      continue
    fi
    # Or the leg is stuck because a LATER leg of the model's own outline
    # has to happen first (Surge's gym behind a CUT bush, with "Obtain
    # the HM for Cut" two legs later). The model names the blocking leg
    # and the harness pulls it forward — choose-only, bounded, and now
    # gated: a leg is not pulled if it is already done, not pulled twice
    # if the first pull failed, and not pulled from far down the list
    # unless it can say what it provides that the stuck leg needs.
    if [ "$(cat run/outline_reorders 2>/dev/null | wc -l)" -lt 8 ] \
        && blocker=$(python planner/author.py --check-blocker \
            --goal "$goal" --outline-path plans/outline.txt --leg "$i" \
            --start "$(python planner/state_text.py)" \
            --observed run/explored.json \
            --journal run/executor_log.jsonl --model "$MODEL"); then
      echo "=== leg $i stuck behind leg $blocker: pulling it forward ==="
      python planner/pull_leg.py pull "$i" "$blocker"
      echo "$i<-$blocker" >> run/outline_reorders
      continue
    fi
    # NOTHING ELSE WORKED: IS THE PLAN MISSING A STEP? A leg can be
    # unreachable because a deed nobody wrote down has to happen first —
    # the parcel before the mart will sell, Cut before Surge's gym. The
    # run holds the evidence: the events it HAS recorded and the
    # objectives it has not reached. Bounded like the reorders, and the
    # model names the deed; the harness only places it.
    if [ "$(cat run/outline_inserts 2>/dev/null | wc -l)" -lt 4 ] \
        && missing=$(python planner/author.py --check-missing \
            --goal "$goal" --outline-path plans/outline.txt --leg "$i" \
            --start "$(python planner/state_text.py)" --model "$MODEL"); then
      echo "=== leg $i needs something first: $missing ==="
      python planner/insert_leg.py "$i" "$missing"
      echo "$i:$missing" >> run/outline_inserts
      continue
    fi
    # LAST RUNG: IS THE OBJECTIVE ITSELF WRONG? The chain halted at
    # "Obtain the Secret Key from the Rocket Hideout" — an item that is
    # not in that dungeon, written before the run had been near it, with
    # the hideout cleared and both its real key items in the bag. The
    # three rungs above ask whether the work is done, blocked, or missing
    # a step; none asks whether the sentence describes anything.
    #
    # A person playing does not fix their whole plan at the start with no
    # way to change their mind when something is plainly not working
    # (user, 2026-08-15). Holding the model to a line it wrote before it
    # had been anywhere is not rigour. THE MODEL NOTICES AND THE MODEL
    # REWRITES: the harness detects nothing and proposes no wording, it
    # asks once and applies an answer it did not shape. The restatement
    # still has to clear the already-done check, which is what stops a
    # hard leg being reworded into one that is finished.
    if [ "$(cat run/outline_rewordings 2>/dev/null | wc -l)" -lt 3 ] \
        && said=$(python planner/author.py --check-wording \
            --goal "$goal" --outline-path plans/outline.txt --leg "$i" \
            --start "$(python planner/state_text.py)" \
            --observed run/explored.json \
            --journal run/executor_log.jsonl --model "$MODEL"); then
      python planner/reword_leg.py "$i" "$said"
      continue
    fi
    echo "=== chain stopped at leg $i/${#LEGS[@]}: $leg ===" >&2
    exit 1
  fi
  echo "$i" > "$PROGRESS"
  echo "=== leg $i/${#LEGS[@]} complete: $leg ==="
  sweep_ahead "$i"
done
