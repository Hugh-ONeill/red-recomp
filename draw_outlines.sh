#!/usr/bin/env bash
# Draw N playthrough outlines for a HAND pick.
#
# The chain authors ONE outline, only when plans/outline.txt is missing, and
# then plays it. One pass is already several drafts merged by the model, but
# the pass itself is high-variance — run 15's outline had "Reach Pewter
# City" after Brock, HM03 at the Cinnabar gym, and two Poke Flute legs — and
# nothing let a person see two passes side by side before committing a
# week of play to one (user, 2026-09-06: "having it run through a couple
# times and hand-picking the most viable-looking plan structure").
#
# So: run the full outline author N times (drafts -> merge -> badge check ->
# upkeep -> review -> dedupe -> stages), land each pass's outline, notes,
# upkeep and stages TOGETHER in plans/candidates/ (the author writes upkeep
# and stages to fixed paths, so passes would otherwise clobber each other),
# time each pass, and put the results side by side with
# planner/compare_outlines.py. The comparison is OUR judge for OUR choice,
# offline; the model never sees it.
#
# Touches nothing the chain reads: not plans/outline.txt, not
# outline.authored, not the leg plans. Staging the pick is a separate step
# (use_perfect_outline.sh is the shape of it).
#
#   ./draw_outlines.sh 3                 # three passes, then the table
#   RED_GOAL="..." ./draw_outlines.sh 1  # one pass under another goal
set -euo pipefail
cd "$(dirname "$0")"

N="${1:-3}"
MODEL="${RED_MODEL:-gemma4:31b-it-q4_K_M}"
AUTHOR_MODEL="${RED_AUTHOR_MODEL:-$MODEL}"
GOAL="${RED_GOAL:-Become the Champion}"
# the author reads its window from this; the chain runs at 32k on the R9700
export RED_NUM_CTX="${RED_NUM_CTX:-32768}"

mkdir -p plans/candidates

# the author writes these two to fixed paths; keep the live ones (if any)
# out of its way and put them back whatever happens
stash=$(mktemp -d)
for f in outline.upkeep outline.stages; do
  [ -e "plans/$f" ] && mv "plans/$f" "$stash/$f"
done
restore() {
  for f in outline.upkeep outline.stages; do
    [ -e "$stash/$f" ] && mv -f "$stash/$f" "plans/$f"
  done
  rmdir "$stash" 2>/dev/null || true
}
trap restore EXIT

made=()
for i in $(seq 1 "$N"); do
  ts=$(date +%Y%m%d-%H%M%S)
  out="plans/candidates/outline.$ts.txt"
  base="${out%.txt}"
  echo "=== draw $i/$N -> $out"
  echo "    model $AUTHOR_MODEL, num_ctx $RED_NUM_CTX, goal: $GOAL"
  t0=$(date +%s)
  rc=0
  python planner/author.py --outline --goal "$GOAL" --out "$out" \
      --model "$AUTHOR_MODEL" > "$base.log" 2>&1 || rc=$?
  t1=$(date +%s)
  # the fixed-path sidecars belong to THIS pass
  for f in upkeep stages; do
    [ -e "plans/outline.$f" ] && mv "plans/outline.$f" "$base.$f"
  done
  if [ "$rc" -ne 0 ] || [ ! -s "$out" ]; then
    echo "    draw $i FAILED (rc=$rc) after $((t1 - t0))s; see $base.log"
    continue
  fi
  echo "$((t1 - t0))" > "$base.seconds"
  echo "    $(wc -l < "$out") legs in $((t1 - t0))s" \
       "($(grep -c '^\[outline\] draft' "$base.log" || true) drafts drawn)"
  made+=("$out")
done

if [ "${#made[@]}" -gt 0 ]; then
  python3 planner/compare_outlines.py "${made[@]}"
else
  echo "no outline was drawn"
  exit 1
fi
