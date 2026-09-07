#!/usr/bin/env bash
# Put the run back to a leg boundary, so the legs after it play again on the
# harness as it stands now.
#
#   ./replay_from.sh run/saves/leg_06_reach_pewter_city.20260907-073012
#
# The executor writes a checkpoint after every completed leg (run/saves/,
# executor.checkpoint_leg): the game's save, the run's memory
# (explored.json), the footprint (seen.json, seen_walk.json), the outline as
# it stood and the chain's own state files, with meta.json naming the leg
# and the harness revision. This restores one of them and sets
# run/outline_leg to that leg, so the chain's next launch starts the leg
# after it — same ground, same outline, whatever harness is current — and
# the meter reads the two journals side by side (user, 2026-09-07: "is
# there a way to reset its progress at boundaries so we can get clean
# splits for the fixed runs?").
#
# The journal being written is archived, not overwritten: the legs already
# played stay measurable under the harness that played them.
#
# Only stages files. Stop the chain first (./stop_all.sh), then run this,
# then launch fresh_discovery.sh as usual. It does NOT clear the leg plans:
# a plan written for a leg is reused, which is the cleaner measurement
# (same plan, different harness). Move plans/leg_NN_*.json aside yourself
# if a re-authoring is what you want to measure.
set -euo pipefail
cd "$(dirname "$0")"

src="${1:-}"
if [ -z "$src" ] || [ ! -f "$src/meta.json" ]; then
  echo "usage: $0 run/saves/<checkpoint dir>   (one with a meta.json)" >&2
  ls -d run/saves/*/ 2>/dev/null | sed 's/^/  /' >&2 || true
  exit 2
fi
if pgrep -f "^bash .*fresh_discovery\.sh" >/dev/null 2>&1 \
   || pgrep -f "planner/executor\.py" >/dev/null 2>&1; then
  echo "the chain (or an executor) is running; stop it first (./stop_all.sh)" >&2
  exit 1
fi

leg=$(python3 -c "import json,sys; print(json.load(open('$src/meta.json'))['leg'])")
# a checkpoint after a COMPLETED leg resumes at the leg after it; one after
# a failed attempt resumes ON that leg (its progress counter is the leg before)
complete=$(python3 -c "import json,sys; print('1' if json.load(open('$src/meta.json')).get('complete', True) else '0')")
resume_at=$leg
[ "$complete" = 1 ] || resume_at=$((leg - 1))
rev=$(python3 -c "import json,sys; print(json.load(open('$src/meta.json')).get('rev','?'))")
SAVE="${RED_SAVE:-$HOME/.local/share/love/pokemon-love2d/saves/red/slot1.lua}"
ts=$(date +%Y%m%d-%H%M%S)

# the journal so far keeps its own harness's record
if [ -s run/executor_log.jsonl ]; then
  mv run/executor_log.jsonl "run/executor_log.$ts.pre-replay.jsonl"
  echo "archived the journal as run/executor_log.$ts.pre-replay.jsonl"
fi
# the live state files are archived too, in case the replay is regretted
mkdir -p "run/saves/pre-replay.$ts"
[ -f "$SAVE" ] && cp "$SAVE" "run/saves/pre-replay.$ts/slot1.lua"
for f in run/explored.json run/seen.json run/seen_walk.json plans/outline.txt plans/outline.done run/outline_leg; do
  [ -f "$f" ] && cp "$f" "run/saves/pre-replay.$ts/$(basename "$f")"
done

# restore the checkpoint
mkdir -p "$(dirname "$SAVE")"
if [ -f "$src/slot1.lua" ]; then
  cp "$src/slot1.lua" "$SAVE"; rm -f "$SAVE.bak"
  echo "restored the save from leg $leg"
else
  echo "no slot1.lua in $src — the save is left as it is" >&2
fi
for f in "$src"/*; do
  b=$(basename "$f")
  case "$b" in
    meta.json|slot1.lua) ;;
    explored.json|seen.json|seen_walk.json) cp "$f" "run/$b" ;;
    outline.txt|outline.done) cp "$f" "plans/$b" ;;
    outline_*|leg_unconfirmed) cp "$f" "run/$b" ;;
  esac
done
# state files the checkpoint did not have did not exist then either
for f in run/outline_skips run/outline_inserts run/outline_void run/outline_wording_asked \
         run/outline_pushes run/outline_pullbacks run/outline_pulls run/outline_pulls_failed \
         run/outline_replays run/outline_rewordings run/leg_unconfirmed plans/outline.done; do
  [ -f "$src/$(basename "$f")" ] || rm -f "$f"
done
rm -f run/last_state.json run/obs.json run/status.txt run/heartbeat run/attempt_yield run/attempt_start.json
echo "$resume_at" > run/outline_leg
echo "run/outline_leg = $resume_at (the chain resumes at leg $((resume_at + 1))$([ "$complete" = 1 ] || echo ' — the checkpointed attempt of that leg had not completed it')); checkpoint was taken on harness $rev, this tree is $(git rev-parse --short HEAD 2>/dev/null || echo '?')"
echo "next: launch fresh_discovery.sh as usual; compare with"
echo "  planner/arc.py --legs 60 run/executor_log.$ts.pre-replay.jsonl run/executor_log.jsonl"
