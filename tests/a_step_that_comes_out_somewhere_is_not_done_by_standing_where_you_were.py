"""A step whose words say it comes OUT on a map cannot end on a bare
{"map"} for that map when the plan's own earlier steps put the party there.

The exit rule (author validate, 2026-09-05) read the run's record: a bare
{"map": M} with words like exit / other side is refused when the run has
already stood on M.  Run 16's leg 6 was written in Viridian City -- "reach
Route 2" then "go through Viridian Forest and exit to the NORTH side of
Route 2", both {"map":"ROUTE_2"} -- and passed, because Route 2 had not
been stood on yet.  By the second step it had: the party walked back out
the forest's south gate, the step counted as done with nothing crossed, and
the next step looked for Pewter City from the wrong half of the road
(2026-09-07).  The plan's own order puts the party on that map first, and
the rule now reads the plan as well as the record.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import author as A

_real = A.visited_regions
A.visited_regions = lambda *a, **k: set()      # a run that has stood nowhere
try:
    plan = {"goal": "Reach Pewter City", "subgoals": [
        {"id": "reach_route_2", "goal_text": "Travel north from Viridian City to Route 2",
         "done_when": {"map": "ROUTE_2"}},
        {"id": "enter_viridian_forest", "goal_text": "Enter the Viridian Forest from Route 2",
         "done_when": {"map": "VIRIDIAN_FOREST"}},
        {"id": "exit_viridian_forest",
         "goal_text": "Navigate through Viridian Forest and exit to the north side of Route 2",
         "done_when": {"map": "ROUTE_2"}},
        {"id": "reach_pewter_city", "goal_text": "Travel north from Route 2 to reach Pewter City",
         "done_when": {"map": "PEWTER_CITY"}}]}
    probs = A.validate(plan) or []
    hit = [p for p in probs if "exit_viridian_forest" in p and "comes OUT" in p]
    ck("the exit step is refused although the run has never stood on Route 2", bool(hit))
    ck("...and told to write new_part", any('{"new_part": "ROUTE_2"}' in p for p in hit))
    ck("the first Route 2 step, which only arrives, is not refused",
       not any("reach_route_2" in p and "comes OUT" in p for p in probs))
    # a BUILDING is entered, not come out on: "exit the cave and enter the
    # Center" must not become a part of the Center never stood on (run 16)
    plan3 = {"goal": "Exit Mt. Moon and reach Cerulean City", "subgoals": [
        {"id": "reach_route_4", "goal_text": "Reach Route 4", "done_when": {"map": "ROUTE_4"}},
        {"id": "reach_mt_moon_exit_center",
         "goal_text": "Find the exit of the cave and enter the Mt. Moon Pokemon Center",
         "done_when": {"map": "MT_MOON_POKECENTER"}}]}
    A.visited_regions = lambda *a, **k: {"MT_MOON_POKECENTER|0,3", "ROUTE_4|4,4"}
    probs3 = A.validate(plan3) or []
    ck("a step that ENTERS a building is not asked for a new part of it",
       not any("reach_mt_moon_exit_center" in p and "comes OUT" in p for p in probs3))
    A.visited_regions = lambda *a, **k: set()
    plan2 = {"goal": "g", "subgoals": [
        {"id": "exit_forest", "goal_text": "Exit the forest onto Route 2",
         "done_when": {"map": "ROUTE_2"}}]}
    probs2 = A.validate(plan2) or []
    ck("with no earlier step and no record on that map, a bare map still passes",
       not any("comes OUT" in p for p in probs2))
finally:
    A.visited_regions = _real

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
