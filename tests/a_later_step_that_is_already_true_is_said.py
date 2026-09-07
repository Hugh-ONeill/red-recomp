"""When a later step of the plan already holds where the party stands, the
page says so, and says that skip is how the plan moves on.

Run 16 (2026-09-07): the Vermilion plan went Route 5 -> Saffron City ->
Route 6 -> Vermilion.  The party found the Underground Path and came up on
Route 6 with the Saffron step still in play, and nothing on the page said
the step after it was already true.  It walked back north to work on
Saffron, a thirsty guard, and the attempt died on Route 24.  The skip op
existed the whole time; the model could not know it applied.

The plan's own conditions are read against the screen; whether the step in
play is still needed is the model's call.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

ex = E.Executor.__new__(E.Executor)
ex.plan = {"subgoals": [
    {"id": "travel_to_route_5", "done_when": {"map": "ROUTE_5"}},
    {"id": "travel_to_saffron_city", "done_when": {"map": "SAFFRON_CITY"}},
    {"id": "travel_to_route_6", "done_when": {"map": "ROUTE_6"}},
    {"id": "reach_vermilion", "done_when": {"map": "VERMILION_CITY"}}]}
on_route_6 = {"mode": "overworld", "map": {"id": "ROUTE_6", "region": "1,0"}}
later = ex._later_steps_true({"id": "travel_to_saffron_city"}, on_route_6)
ck("standing on Route 6 while the Saffron step is in play, the Route 6 step is named",
   [i for i, _ in later] == ["travel_to_route_6"])
ck("...and Vermilion, not yet stood on, is not",
   not any(i == "reach_vermilion" for i, _ in later))
ck("steps BEFORE the one in play are not listed",
   not any(i == "travel_to_route_5" for i, _ in later))
ck("nothing later holds on Route 5",
   ex._later_steps_true({"id": "travel_to_saffron_city"},
                        {"mode": "overworld", "map": {"id": "ROUTE_5", "region": "1,0"}}) == [])
ck("a step id the plan does not hold says nothing",
   ex._later_steps_true({"id": "nope"}, on_route_6) == [])

src = Path("planner/executor.py").read_text()
ck("the round's page carries it, with skip as the way on",
   "LATER STEPS OF THIS PLAN THAT ARE ALREADY TRUE WHERE" in src
   and '{\\"op\\":\\"skip\\"} ends' in src
   and "_later = self._later_steps_true(sg, cur)" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
