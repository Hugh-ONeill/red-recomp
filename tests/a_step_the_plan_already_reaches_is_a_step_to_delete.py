#!/usr/bin/env python3
"""A step whose map an earlier step of the SAME plan already ends on is
told to be removed, and told that renaming it is not the repair.

"Travel through Rock Tunnel" was authored fifteen times across three
drafts and every one was refused on this line, because the model believes
the tunnel comes out on Route 11 and so wrote both `traverse_rock_tunnel`
and `exit_rock_tunnel` ending on ROUTE_11. Every retry changed only the
step's NAME: exit_rock_tunnel, then reach_route_11, then exit_to_route_11.
The leg could not be authored at all and was pushed twice (2026-09-14).

The two repairs the message offered belong to the other half of this
rule, where the RUN's own feet have already been on that map: write
new_part, or keep map and reword the goal_text. Neither fits here.
new_part is actively wrong, because the run has not stood on that map at
all and it would freeze to an empty exclusion. When the duplicate is with
the plan's own earlier step, the repair is to delete the step. Same shape
as the no-such-event message: name the edits that work, and say that
renaming is not one of them.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import author as A                                        # noqa: E402
from pinned_world import pinned                           # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

def out(plan, walked, here="VERMILION_CITY|18,0"):
    with pinned(explored={r: {} for r in walked}, visits={r: 3 for r in walked},
                obs={"map": {"id": here.split("|")[0], "region": here.split("|")[1]},
                     "party": [{"species": "PIKACHU", "level": 25}], "flags": []}):
        return [p for p in A.validate(json.loads(json.dumps(plan))) if "comes OUT" in p]

TUNNEL = {"goal": "Travel through Rock Tunnel", "subgoals": [
    {"id": "enter_rock_tunnel", "goal_text": "Enter the tunnel",
     "done_when": {"map": "ROCK_TUNNEL_1F"}},
    {"id": "traverse_rock_tunnel", "goal_text": "Cross the tunnel",
     "done_when": {"map": "ROUTE_11"}},
    {"id": "exit_rock_tunnel", "goal_text": "Exit out onto Route 11",
     "done_when": {"map": "ROUTE_11"}}]}

p = out(TUNNEL, ["VERMILION_CITY|18,0"])
ck("the duplicate ending is still refused", len(p) == 1, p)
t = p[0] if p else ""
ck("...naming the earlier step that already reaches it",
   "an earlier step of this plan (traverse_rock_tunnel) already ends on ROUTE_11" in t, t)
ck("...and saying the step marks nothing new",
   "marks nothing the step before it has not already marked" in t, t)
ck("REMOVING it is offered first", "REMOVE subgoal[2] (exit_rock_tunnel)" in t, t)
ck("...with the other real edit: the two steps name the same map",
   "change the MAP one of them ends on" in t, t)
ck("renaming is ruled out in words",
   "Do not rename this step" in t and "not what it is called" in t, t)
ck("new_part is NOT offered here: the run has never stood on that map",
   "new_part" not in t, t)

# the other half of the rule is untouched: the RUN has stood there
STOOD = {"goal": "Exit the Seafoam Islands", "subgoals": [
    {"id": "cross", "goal_text": "Cross the islands", "done_when": {"map": "SEAFOAM_ISLANDS_B4F"}},
    {"id": "exit_west", "goal_text": "Come out onto Route 20", "done_when": {"map": "ROUTE_20"}}]}
p2 = out(STOOD, ["ROUTE_20|1,1", "VERMILION_CITY|18,0"])
t2 = p2[0] if p2 else ""
ck("a map the RUN has stood on still gets the new_part advice",
   "new_part" in t2 and "this run has already stood on ROUTE_20" in t2, t2)
ck("...and is not told to delete the step", "REMOVE subgoal" not in t2, t2)

# ...but a plan that GOES somewhere in between means the far side, and keeps
# the new_part advice: arrive on Route 2, cross the forest, come out on Route 2
FOREST = {"goal": "Reach Pewter City", "subgoals": [
    {"id": "reach_route_2", "goal_text": "Walk north to Route 2", "done_when": {"map": "ROUTE_2"}},
    {"id": "cross_forest", "goal_text": "Cross Viridian Forest", "done_when": {"map": "VIRIDIAN_FOREST"}},
    {"id": "exit_forest", "goal_text": "Come out onto Route 2", "done_when": {"map": "ROUTE_2"}}]}
p3 = out(FOREST, ["VERMILION_CITY|18,0"])
t3 = p3[0] if p3 else ""
ck("a step the plan LEFT the map between is the far side, not a duplicate",
   'new_part": "ROUTE_2"' in t3 and "REMOVE subgoal" not in t3, t3)

# nothing to say when the maps differ
OK_PLAN = {"goal": "Travel through Rock Tunnel", "subgoals": [
    {"id": "enter_rock_tunnel", "goal_text": "Enter the tunnel", "done_when": {"map": "ROCK_TUNNEL_1F"}},
    {"id": "exit_rock_tunnel", "goal_text": "Come out the far side", "done_when": {"new_part": "ROUTE_10"}}]}
ck("a plan whose steps end in different places is left alone",
   out(OK_PLAN, ["VERMILION_CITY|18,0"]) == [])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
