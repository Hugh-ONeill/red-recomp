#!/usr/bin/env python3
"""Coming out somewhere is not standing where you already were.

2026-09-06. The plan for "Exit Victory Road to reach the Indigo Plateau"
had a step "Navigate through the exit of Victory Road to reach Route 23"
ending on {"map": "ROUTE_23"}. The run had walked INTO the cave from Route
23's south half, so stepping back out the door it came in by satisfied the
step, the plan believed it was through the cave, and the last step tried to
walk north into the Plateau from a half of Route 23 that does not touch it
(user: "hooked on trying to get to indigo plateau without going through
victory road, or thinking its already gotten through somehow when it
hasnt, barely even entered victory road that round").

new_part exists for exactly this — "come OUT somewhere new on a map you
have already been on" — and the author did not reach for it. Now a BARE
map condition on a map the run has stood on, whose own words say it comes
out of somewhere, is refused with the choice spelled out: new_part for a
part never stood on, or keep map and stop saying exit. Which is the
author's; a step that says "return to Route 23" is left alone, and so is
a map the run has never stood on.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                   # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

A.visited_regions = lambda: {"ROUTE_23|10,104", "ROUTE_23|4,31",
                             "VICTORY_ROAD_1F|5,9", "VICTORY_ROAD_1F|14,0"}

def plan(dw, text, sid="exit_victory_road"):
    return {"goal": "Exit Victory Road to reach the Indigo Plateau",
            "subgoals": [
                {"id": "reach_1f", "goal_text": "Go to Victory Road 1F",
                 "done_when": {"map": "VICTORY_ROAD_1F"}},
                {"id": sid, "goal_text": text, "done_when": dict(dw)},
                {"id": "plateau", "goal_text": "Enter the Indigo Plateau",
                 "done_when": {"map": "INDIGO_PLATEAU"}}]}

def mine(probs):
    return [p for p in probs if "its words say it comes OUT somewhere" in p]

t = mine(A.validate(plan({"map": "ROUTE_23"},
                         "Navigate through the exit of Victory Road to reach Route 23")))
ck("the incident's own step is refused", len(t) == 1)
ck("...naming the parts already stood on", t and "ROUTE_23|10,104" in t[0] and "ROUTE_23|4,31" in t[0])
ck("...saying what satisfies it as written", t and "walking back out the door you came in by satisfies it" in t[0])
ck("...and offering both ways out, choosing neither",
   t and '{"new_part": "ROUTE_23"}' in t[0] and 'keep {"map"}' in t[0]
   and "the far side" in t[0])
ck("the step id alone can carry the word", len(mine(A.validate(plan({"map": "ROUTE_23"}, "Reach Route 23", sid="leave_cave")))) == 1)
ck("a step that just goes back to a known map is left alone",
   not mine(A.validate(plan({"map": "ROUTE_23"}, "Return to Route 23 and heal", sid="back"))))
ck("a map never stood on is left alone",
   not mine(A.validate(plan({"map": "INDIGO_PLATEAU"}, "Exit the cave onto the Indigo Plateau"))))
p2 = plan({"new_part": "ROUTE_23"}, "Exit Victory Road onto Route 23")
r2 = A.validate(p2)
ck("new_part answers it", not mine(r2))
ck("...and freezes into map plus the parts already stood on",
   p2["subgoals"][1]["done_when"].get("map") == "ROUTE_23"
   and set(p2["subgoals"][1]["done_when"].get("not_area") or []) == {"ROUTE_23|10,104", "ROUTE_23|4,31"})
ck("a map paired with player_at is not a bare map",
   not mine(A.validate(plan({"map": "ROUTE_23", "player_at": {"x": 10, "y": 3, "radius": 3}},
                            "Exit Victory Road to reach Route 23"))))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
