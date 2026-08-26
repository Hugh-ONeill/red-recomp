"""Exit 0 when an attempt of the last plan in the journal ended on a departure
the run made by its own decision (backtrack_skipped after left_target_on_purpose),
else 1. The chain asks the missing-step question early on that fact
(2026-08-25: v6-v9 of the tower leg each re-marched the party back from
Celadon to Lavender while every escalation of it had said "need the Silph
Scope" and walked to the Rocket Hideout)."""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "run/executor_log.jsonl")
try:
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
except (OSError, ValueError):
    sys.exit(1)
starts = [i for i, r in enumerate(recs) if r.get("kind") == "plan_start"]
if not starts:
    sys.exit(1)
# every attempt of the plan for this objective, not only the last: the
# departure is evidence about the LEG, whichever attempt made it
goal = recs[starts[-1]].get("goal")
first = next(i for i in starts if recs[i].get("goal") == goal)
seg = recs[first:]
kinds = {r.get("kind") for r in seg}
if "backtrack_skipped" in kinds and "left_target_on_purpose" in kinds:
    for r in reversed(seg):
        if r.get("kind") == "left_target_on_purpose":
            print(f"departed: {r.get('left_from')} -> {r.get('now')} during "
                  f"{r.get('subgoal')}")
            break
    sys.exit(0)
sys.exit(1)
