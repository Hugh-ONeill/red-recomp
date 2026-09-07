#!/usr/bin/env bash
# Stage a chosen outline as the chain's outline.
#
#   ./use_outline.sh plans/candidates/outline.20260906-135851.txt
#
# The hand-pick's last step (user, 2026-09-06: draw several, "hand-picking
# the most viable-looking plan structure"). use_perfect_outline.sh did this
# for one hardwired file; this does it for any outline, and carries the
# sidecars draw_outlines.sh landed beside it — .upkeep (which legs are
# non-fatal), .stages (the chapter each leg belongs to), .notes (the
# author's own doubts, handed to whoever writes each leg's plan).
#
# Only stages files. It does NOT touch a running chain and does NOT launch
# anything. Stop the chain first if one is up, then:
#   rm -f run/outline_leg      # fresh world; the outline is already banked
#   (RED_NUM_CTX=32768 setsid nohup systemd-inhibit --mode=block \
#     --what=sleep:idle --why="red-recomp chain" ./fresh_discovery.sh 4 \
#     >> run/chain.log 2>&1 < /dev/null &)
set -euo pipefail
cd "$(dirname "$0")"

src="${1:-}"
if [ -z "$src" ] || [ ! -s "$src" ]; then
  echo "usage: $0 plans/candidates/outline.<stamp>.txt" >&2
  exit 2
fi
case "$src" in
  *.txt) base="${src%.txt}" ;;
  *) echo "the outline should be the .txt file; its sidecars are found beside it" >&2; exit 2 ;;
esac

# the chain's own process is "bash ./fresh_discovery.sh N"; matching the bare
# name caught the shell that was about to launch it (its command line named
# the script too) and refused a staging that was fine
if [ -f run/outline_leg ] && pgrep -f "^bash .*fresh_discovery\.sh" >/dev/null 2>&1; then
  echo "a chain looks live (run/outline_leg exists and fresh_discovery.sh is running); stop it first" >&2
  exit 1
fi

ts=$(date +%Y%m%d-%H%M%S)
mkdir -p plans/archive
for f in outline.txt outline.authored outline.upkeep outline.stages outline.notes outline.done; do
  if [ -e "plans/$f" ]; then
    mv "plans/$f" "plans/archive/$ts-prePick-$f"
    echo "archived plans/$f -> plans/archive/$ts-prePick-$f"
  fi
done

cp "$src" plans/outline.txt
cp "$src" plans/outline.authored      # the fresh-chain block restores from this
for side in upkeep stages notes; do
  if [ -s "$base.$side" ]; then
    cp "$base.$side" "plans/outline.$side"
    echo "staged plans/outline.$side ($(wc -l < "$base.$side") lines)"
  else
    echo "no $side sidecar beside $src (fine: the chain runs without one)"
  fi
done

# leg plans are keyed by number+slug and a matching one is reused: move the
# old outline's plans aside rather than let a stale one match
mkdir -p "plans/legs.$ts.prePick"
n=$(ls plans/leg_[0-9]*.json 2>/dev/null | wc -l)
if [ "$n" -gt 0 ]; then
  mv plans/leg_[0-9]*.json "plans/legs.$ts.prePick/"
  echo "moved $n old leg plan(s) to plans/legs.$ts.prePick/"
else
  rmdir "plans/legs.$ts.prePick"
fi

echo "staged: $(wc -l < plans/outline.txt) legs from $src"
echo "next: rm -f run/outline_leg, then launch fresh_discovery.sh as usual"
