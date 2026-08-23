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
# Tell stop_all.sh what this rig started, so it never has to guess
# from a process-name pattern (rig.sh).
# shellcheck source=rig.sh
. ./rig.sh
rig_register chain
ATTEMPTS="${1:-4}"
MODEL="${RED_MODEL:-gemma4:31b-it-q4_K_M}"
# WHO WRITES AND WHO PLAYS NEED NOT BE THE SAME MODEL. The escalation
# model is judged on ops it composes in front of the game; the author is
# judged on sentences written about a world it cannot see, and the two
# have come apart — qwen3.8 plays a richer game than it writes (its
# missing-step rung answered "Travel to the Johto Region" about an island
# one seam west of the party). RED_AUTHOR_MODEL splits them; unset, the
# playing model writes, which is the old behaviour exactly.
AUTHOR_MODEL="${RED_AUTHOR_MODEL:-$MODEL}"
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
  # THE DEED LEDGER IS WORLD STATE, and it was the one piece of it that
  # survived. plans/outline.done is a list of things this run has DONE,
  # rendered to the model as "ALSO ACCOMPLISHED, though it was never on
  # your list" — and it is kept beside the outline, which a fresh chain
  # deliberately preserves, so it rode across the archive line with it.
  # Run 7 started a brand new game and was handed seven accomplishments
  # from three dead worlds: the Pokedex it does not have, the parcel it
  # has not delivered, a Pidgey it never caught, a rival it never beat.
  # The recognise pass that writes this file is careful to record only
  # what it can point at — "the item is in the bag, the badge is earned,
  # the event has fired" — which is exactly why keeping it past the world
  # it pointed at turns it into a list of lies.
  # Archived rather than deleted: it is the record of what those runs did.
  [ -f plans/outline.done ] \
    && mv plans/outline.done "plans/outline.done.${ts}.pre-discovery"
  # THE OUTLINE IS BANKED LUCK; THE EDITS TO IT ARE WORLD STATE. Same
  # split as the deed ledger, one level up, and it took nine chains to
  # show. outline.txt is deliberately kept across a fresh chain — an
  # authoring pass is expensive and re-rolling it throws away a good list
  # — but the reorder, insert, pull and skip rungs REWRITE THAT FILE IN
  # PLACE from play evidence, and the play that justified each edit
  # happened in a world that has since been deleted. Nothing ever put it
  # back, so the edits stacked: by run 9 the list carried "Register the
  # PC system" at position 3, an objective the model plans against
  # EVENT_MET_BILL, eleven places before Bill is reachable, and
  # "Exit Rock Tunnel" ahead of the city you reach on the way to it. Every
  # fresh chain inherited both and burned attempts on them.
  # So: keep the outline AS AUTHORED, and drop a chain's edits with the
  # world that earned them. The drifted copy is archived, not discarded —
  # what the model chose to reorder is worth reading.
  if [ -s plans/outline.authored ]; then
    if ! cmp -s plans/outline.authored plans/outline.txt; then
      cp plans/outline.txt "plans/outline.${ts}.drifted.txt" 2>/dev/null
      cp plans/outline.authored plans/outline.txt
      echo "outline restored as authored; this chain's edits archived as" \
           "outline.${ts}.drifted.txt"
    fi
  fi
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
  # .prev goes with it: the ledger is now written tmp+rename with the last
  # good copy kept beside it, and a fresh chain that cleared the live file
  # but left the fallback would load a previous chain's whole walked map
  # and call it this one's.
  rm -f run/explored.json run/explored.json.prev run/explored.json.tmp \
        run/last_state.json run/obs.json \
        run/status.txt run/heartbeat
  # these budgets belong to a chain, not to the directory
  : > run/outline_reorders
  rm -f run/outline_skips run/outline_inserts run/outline_rewordings \
        run/outline_void \
        run/leg_audit_redo run/outline_upkeep_missed \
        run/outline_pushes \
        run/outline_pulls run/outline_pulls_failed
  echo "archived ${ts}.pre-discovery; ledgers cleared"
fi

if [ -s plans/outline.txt ]; then
  echo "keeping existing plans/outline.txt"
else
  # a new outline invalidates every leg plan written for the old one —
  # and its upkeep sidecar, which names legs by wording this outline may
  # not use. A stale one would mark the wrong legs non-fatal.
  rm -f plans/leg_[0-9]*.json plans/outline.notes plans/outline.done \
        plans/outline.upkeep plans/outline.stages
  echo "--- authoring the outline"
  echo "goal: $GOAL"
  python planner/author.py --outline --goal "$GOAL" \
      --out plans/outline.txt --model "$AUTHOR_MODEL"
  # ...and bank it, untouched, so the fresh-chain block above can put the
  # list back the way the model wrote it after a chain has reordered it.
  # Taken HERE, at the only moment the file is known to be pristine.
  cp plans/outline.txt plans/outline.authored
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
          --start "$st" --observed run/explored.json --model "$AUTHOR_MODEL") \
      && [ -n "$got" ]; then
    nums=$(printf '%s\n' "$got" | cut -f1 | tr '\n' ' ')
    if python planner/skip_legs.py $nums; then
      printf '%s\n' "$got" >> run/outline_skips
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
      --start "$st" --model "$AUTHOR_MODEL" || true
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
    aargs=(--goal "$goal" --out "$plan" --model "$AUTHOR_MODEL")
    if [ "$i" -gt 1 ]; then
      aargs+=(--start "$(python planner/state_text.py)")
      [ -s run/explored.json ] && aargs+=(--observed run/explored.json)
      [ -s run/executor_log.jsonl ] && aargs+=(--journal run/executor_log.jsonl)
    fi
    # AN UNAUTHORABLE LEG MUST NOT KILL THE RUN. author.py exits non-zero
    # when no draft validates, and under `set -e` that took the whole chain
    # down — twice in one session on the drink leg, whose last subgoal had
    # no legal shape left (see validate()'s "a plan may simply end"). A leg
    # nobody can write a plan for is exactly what the later rung is for:
    # push it and carry on, the same answer the ladder gives for a leg that
    # is right but not yet.
    if ! python planner/author.py "${aargs[@]}"; then
      echo "!! authoring failed for leg $i ($goal) — pushing it later"
      _after=$(( i + 2 ))
      [ "$_after" -gt "${#LEGS[@]}" ] && _after=${#LEGS[@]}
      if python planner/push_leg.py "$i" "$_after"; then
        continue
      fi
      # push refused (already deferred twice): leave the order alone and
      # step over this one rather than stopping everything.
      echo "!! could not push leg $i — skipping it for now"
      echo "$i" >> run/outline_unauthored
      echo "$i" > "$PROGRESS"
      continue
    fi
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
        --observed run/explored.json --model "$AUTHOR_MODEL"; then
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
    # A LEG THAT WAS PUSHED AWAY MUST NOT BE PULLED STRAIGHT BACK. The
    # two rungs disagree by design — "later" moves a stuck leg down the
    # list, "blocker" pulls a needed one up — and with two legs that need
    # each other they trade places for ever: HM02 was pushed 29->38, the
    # FLY leg then named it as its blocker and pulled it back to 29, and
    # round again. If this leg has already been pushed, the pull rung is
    # not asked (2026-08-19).
    pushed_before=$(grep -Fc "$leg" run/outline_pushes 2>/dev/null) || pushed_before=0
    if [ "$pushed_before" -gt 0 ]; then
      echo "    (not asking the blocker rung: this leg has been pushed" \
           "before — pulling it back is the loop that costs the run)"
    fi
    if [ "$pushed_before" = 0 ] \
        && [ "$(cat run/outline_reorders 2>/dev/null | wc -l)" -lt 8 ] \
        && blocker=$(python planner/author.py --check-blocker \
            --goal "$goal" --outline-path plans/outline.txt --leg "$i" \
            --start "$(python planner/state_text.py)" \
            --observed run/explored.json \
            --journal run/executor_log.jsonl --model "$AUTHOR_MODEL"); then
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
    # BOUNDED PER LEG, NOT PER CHAIN. A global cap of 4 was spent by leg
    # 36, so leg 40 stalled for 40+ plan versions without the model ever
    # being ASKED whether a step was missing — the one rung its own
    # Seafoam evidence could answer was silently skipped. ONE ask per
    # leg (user, 2026-08-23), with a chain-wide ceiling so a runaway
    # still cannot happen. An insert renumbers the legs below it, so a
    # leg that stalls again after something was placed in front of it
    # keeps its one ask — BUT THE BUDGET FOLLOWS THE OBJECTIVE, NOT THE
    # SLOT. Keyed by number, an insert renumbered the stuck leg and handed
    # it a fresh ask every time: Cinnabar asked at 40, was pushed to 41 by
    # its own answer, and asked again at 41 (2026-08-23). The objective is
    # what has the question, so the objective is what spends the ask.
    _ins_leg=$(grep -Fc "LEG=$leg|" run/outline_inserts 2>/dev/null || true)
    if [ "$(cat run/outline_inserts 2>/dev/null | wc -l)" -lt 12 ] \
        && [ "${_ins_leg:-0}" -lt 1 ] \
        && missing=$(python planner/author.py --check-missing \
            --goal "$goal" --outline-path plans/outline.txt --leg "$i" \
            --start "$(python planner/state_text.py)" --model "$AUTHOR_MODEL"); then
      echo "=== leg $i needs something first: $missing ==="
      python planner/insert_leg.py "$i" "$missing"
      echo "LEG=$leg|$missing" >> run/outline_inserts
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
    if [ "$(cat run/outline_rewordings 2>/dev/null | wc -l)" -lt 3 ]; then
      set +e
      said=$(python planner/author.py --check-wording \
          --goal "$goal" --outline-path plans/outline.txt --leg "$i" \
          --start "$(python planner/state_text.py)" \
          --observed run/explored.json \
          --journal run/executor_log.jsonl --model "$AUTHOR_MODEL")
      wrc=$?
      set -e
      if [ $wrc = 0 ] && [ -n "$said" ]; then
        python planner/reword_leg.py "$i" "$said"
        continue
      fi
      # EXIT 4: the restatement the model gave names something the run has
      # ALREADY DONE. Both halves of that came from the model — what the
      # objective means, and that the meaning is satisfied — so the leg is
      # SPENT, not stuck, and stopping the chain on it throws away the
      # answer while keeping the problem. This is the case that killed two
      # runs: leg 7 "Reach Vermilion City" one night, leg 3 "Retrieve the
      # Pokemon from the Poke Mart" the next. A leg that is genuinely
      # blocked reaches the exit below unchanged.
      if [ $wrc = 4 ]; then
        echo "=== leg $i/${#LEGS[@]} is done under another name — " \
             "crossing it off: $leg ===" >&2
        echo "$leg" >> run/outline_skips
        echo "$i" > "$PROGRESS"
        sweep_ahead "$i"
        continue
      fi
      # EXIT 5: VOID — the model says the sentence describes nothing that
      # is there ("there is no Pokemon to retrieve"). Its verdict, its
      # reason (run/outline_void); the line is crossed off the same way a
      # done-under-another-name is, and the objectives after it stand.
      # The first live case halted the chain on exactly this answer.
      if [ $wrc = 5 ]; then
        echo "=== leg $i/${#LEGS[@]} is VOID by the model's own account — " \
             "crossing it off: $leg ===" >&2
        echo "$leg" >> run/outline_skips
        echo "$i" > "$PROGRESS"
        sweep_ahead "$i"
        continue
      fi
    fi
    # RIGHT, BUT NOT YET. Every rung above asks whether something ELSE
    # must happen first; none can say "this one, later". An outline's
    # ordering mistakes are almost all TOO EARLY — a model writing a
    # playthrough puts a thing down when it thinks of it — and a merely
    # premature objective could until now only be reworded, skipped or
    # fatal. Live case: "the party holds a WATER or GRASS type" sat before
    # Vermilion, where wild water Pokemon need a rod nobody has yet, and
    # the upkeep rule saved the chain by dropping it for good. Deferring
    # beats dropping. Bounded twice over: six pushes per chain, and no
    # objective put off more than twice (author.py refuses the third).
    # grep -c prints "0" AND exits 1 when the file exists with no match.
    # A bare `|| echo 0` yields TWO lines; piping that through `head -1`
    # yields SIGPIPE on the echo, which under `set -o pipefail` + `set -e`
    # KILLED THE WHOLE CHAIN (exit 141, mid-ladder, leg 5). No pipe: the
    # substitution already captures grep's "0", and the `||` only has to
    # stop the non-zero status from tripping set -e.
    pushed=$(grep -Fc "$leg" run/outline_pushes 2>/dev/null) || pushed=0
    if [ "$(cat run/outline_pushes 2>/dev/null | wc -l)" -lt 6 ] \
        && at=$(python planner/author.py --check-later \
            --goal "$leg" --outline-path plans/outline.txt --leg "$i" \
            --pushed "$pushed" \
            --start "$(python planner/state_text.py)" \
            --journal run/executor_log.jsonl --model "$AUTHOR_MODEL"); then
      # PROGRESS is deliberately NOT advanced: the objective that was next
      # has slid into this position, and that is the one to run now.
      python planner/push_leg.py "$i" "$at"
      continue
    fi
    # AN UPKEEP LEG NEVER STOPS THE CHAIN. The upkeep round adds
    # objectives the story beats take for granted — catch something to
    # soak hits, get a type that covers the next gym — and those are
    # conditions the world may simply not offer in four attempts: the
    # species does not appear, the grass is the wrong grass, the balls run
    # out. A run that cannot train should still play on; a run that stops
    # has failed at the one thing it exists to do. So the whole ladder
    # still runs on an upkeep leg — it gets its attempts, its rewrites and
    # its rungs — and only the LAST step differs: it is left behind rather
    # than fatal, and the sweep can still recognise it later if the run
    # picks the thing up in passing. Critical legs keep exiting 1.
    if grep -Fxq "$leg" plans/outline.upkeep 2>/dev/null; then
      echo "=== leg $i/${#LEGS[@]} not achieved, and it is UPKEEP — " \
           "playing on: $leg ===" >&2
      echo "$leg" >> run/outline_upkeep_missed
      echo "$i" > "$PROGRESS"
      continue
    fi
    echo "=== chain stopped at leg $i/${#LEGS[@]}: $leg ===" >&2
    exit 1
  fi
  # THE PLAN MEETING ITS CONDITIONS IS NOT THE OBJECTIVE HAPPENING. The
  # ladder audits a leg that FAILS and never audited one that succeeded:
  # campaign.sh returning 0 means only that the subgoals met their own
  # DONE_WHENs, and PROGRESS was written on the strength of that. Leg 11
  # closed as "Obtain the Secret Key from the Rocket Hideout" with no
  # SECRET_KEY in the bag, and leg 12 as "Clear out the Pokemon Tower"
  # with no POKE_FLUTE. Both counted. So the progress figure was a count
  # of plans satisfied, not of objectives achieved — and the gained-delta
  # that would have shown it was only ever printed on the failure path.
  #
  # BOUNDED AT ONE REDO, AND IT MUST NEVER BLOCK. The claim run is set off
  # once and finishes the game unattended, with no chance to edit code
  # mid-run, so a gate that can refuse a leg forever is worse than a leg
  # counted generously. One rejection buys a fresh plan and one more
  # cycle; a second accepts and moves on, loudly and in writing. Keyed by
  # objective TEXT, because positions shift under the reorder rungs.
  gained=$(python planner/leg_delta.py diff run/leg_start.json \
      2>/dev/null || true)
  [ -n "$gained" ] && echo "    gained: $gained"
  redone=0
  grep -Fxq "$leg" run/leg_audit_redo 2>/dev/null && redone=1
  # ASK, EVEN THE SECOND TIME. The `&&` here used to short-circuit on the
  # redo pass, so a leg that had failed its audit once was counted with the
  # judge never consulted again — printed as "still unconfirmed" whether or
  # not it was. The drink leg's second plan SUCCEEDED (Saffron entered,
  # EVENT_GAVE_GUARDS_DRINK fired, a clean ALL PLANS COMPLETE) and was
  # filed as unconfirmed anyway; the same path had banked the opposite lie
  # an hour earlier. One judge call, and the log says which happened.
  confirmed=1
  python planner/author.py --check-done --goal "$goal" \
      --start "$(python planner/state_text.py)" --gained "$gained" \
      --observed run/explored.json --model "$AUTHOR_MODEL" || confirmed=0
  if [ "$redone" = 0 ] && [ "$confirmed" = 0 ]; then
    printf '%s\n' "$leg" >> run/leg_audit_redo
    echo "=== leg $i: the plan met its conditions but the objective is "
    echo "    NOT confirmed — authoring a new plan and running it once more"
    # the plan proved too weak to mean its own objective: every version of
    # it goes aside so a fresh one is written. Archived, never deleted.
    mkdir -p plans/archive; astamp=$(date +%H%M%S)
    for f in $(python planner/find_plan.py "$leg" 2>/dev/null || true); do
      base="${f%.json}"; base="${base%%.v[0-9]*}"
      for g in "$base".json "$base".v*.json; do
        [ -e "$g" ] && mv -f "$g" "plans/archive/${astamp}-weak-$(basename "$g")"
      done
    done
    sweep_ahead "$i"
    continue
  fi
  if [ "$redone" = 1 ]; then
    if [ "$confirmed" = 1 ]; then
      echo "    (confirmed on the second plan)"
    else
      echo "    (objective still unconfirmed after a second plan —" \
           "counting it and moving on)"
      # the legs the run walked past without proof, in one place, so
      # "known-bad in the world" is a list and not a memory
      printf '%s\n' "$leg" >> run/leg_unconfirmed
    fi
  fi
  echo "$i" > "$PROGRESS"
  echo "=== leg $i/${#LEGS[@]} complete: $leg ==="
  sweep_ahead "$i"
done
