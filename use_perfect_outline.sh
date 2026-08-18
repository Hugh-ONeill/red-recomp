#!/usr/bin/env bash
# Stage the hand-written "perfect outline" (plans/outline.perfect.txt) as
# the chain's outline, so a fresh run walks the game in an order that never
# blocks on a later leg — the harness ops (CUT, the Flute, SURF, STRENGTH,
# FLY, the Safari game, Silph, the teleporter gym) get exercised and their
# blockers fixed, instead of the run failing on outline order (user idea,
# 2026-08-18: "give it a perfect outline and bugfix all the blockers on the
# way"). A TEST FIXTURE: the outline is normally the model's own product;
# this one is ours, and a run on it says nothing about outline authoring.
#
# Only stages files. It does NOT touch the running chain and does NOT
# launch anything. Stop the chain first, then start it as usual:
#   rm -f run/outline_leg      # fresh world; the outline is already banked
#   setsid nohup systemd-inhibit --what=sleep:idle --mode=block \
#     --why="red-recomp chain" ./fresh_discovery.sh 4 >> run/chain.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")"
ts=$(date +%H%M%S)
for f in outline.txt outline.authored outline.upkeep outline.stages outline.notes; do
  [ -e "plans/$f" ] && mv "plans/$f" "plans/${f%.*}.$ts.prePerfect.${f##*.}" \
    && echo "archived plans/$f -> plans/${f%.*}.$ts.prePerfect.${f##*.}"
done
cp plans/outline.perfect.txt plans/outline.txt
cp plans/outline.perfect.txt plans/outline.authored     # the fresh-chain block restores from this
cp plans/outline.perfect.upkeep plans/outline.upkeep
# leg plans are keyed by number+slug and a matching one is reused: move
# the old outline's plans aside rather than let a stale one match
mkdir -p "plans/legs.$ts.prePerfect"
mv plans/leg_[0-9]*.json "plans/legs.$ts.prePerfect/" 2>/dev/null || true
rm -f plans/outline.done
echo "staged: $(wc -l < plans/outline.txt) legs, $(wc -l < plans/outline.upkeep) upkeep"
echo "next: stop the chain, rm -f run/outline_leg, relaunch fresh_discovery.sh"
