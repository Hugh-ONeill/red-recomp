#!/usr/bin/env python3
"""When the run has already come out of a place onto the far side, that part
is the exit step's witness, and no rule may steer the plan away from it.

Rock Tunnel, run 16 (2026-09-07): during a 23-minute attempt the run climbed
the tunnel's far ladder (1F 15,33) onto ROUTE_10|14,52 twice, then went back
in because its plan demanded Route 12. The next plan was written with the
exit step ending on ROUTE_10 with not_area excluding BOTH parts stood on,
including 14,52 — the exit rule had listed that part among "already stood
on", so the author excluded it, and the condition asked for a third part of
Route 10. A refused "exit onto ROUTE_12" had also come back inside an any_of
and passed. Now: a plain {"map"} exit step is told which part it already
came out onto and to end on that area; a not_area excluding it is refused
the same way; and any_of alternatives are read by the pin rule.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

explored = {"ROCK_TUNNEL_1F|24,16": {"15,33": {"to": "ROUTE_10|14,52", "n": 2}, "37,17": {"to": "ROCK_TUNNEL_B1F|2,2", "n": 3}},
            "ROCK_TUNNEL_1F|14,2": {"15,3": {"to": "ROUTE_10|0,4", "n": 1}},      # walked back out the entrance too
            "ROUTE_10|0,4": {"8,17": {"to": "ROCK_TUNNEL_1F|14,2", "n": 3}},       # ...which is the side it went IN from
            "ROUTE_9|50,6": {"east": {"to": "ROUTE_10|0,4", "n": 1}}}
A._load_explored = lambda: explored
A.holding_town_map = lambda: True
A.visited_regions = lambda *a, **k: {"ROUTE_10|0,4", "ROUTE_10|14,52", "ROCK_TUNNEL_1F|24,16", "ROCK_TUNNEL_B1F|2,2"}
A._map_now = lambda *a, **k: "ROCK_TUNNEL_B1F"
co = A._came_out_onto("ROCK_TUNNEL_B1F", "ROUTE_10", explored)
ck("the record knows the far side was reached from inside, by which door, from which floor — and the side it went in from is not it",
   co == [("ROUTE_10|14,52", "15,33", 2, "ROCK_TUNNEL_1F")], co)
p0 = [p for p in A.validate({"goal": g if 'g' in dir() else "Travel through Rock Tunnel to its south side", "subgoals": [
    {"id": "enter_rock_tunnel", "goal_text": "Enter the Rock Tunnel from Route 10", "done_when": {"map": "ROCK_TUNNEL_1F"}},
    {"id": "traverse_rock_tunnel", "goal_text": "Navigate through the Rock Tunnel to the south exit", "done_when": {"map": "ROUTE_10"}},
    {"id": "reach_south_side", "goal_text": "Be on the south side of Route 10", "done_when": {"map": "ROUTE_10", "not_area": ["ROUTE_10|0,4", "ROUTE_10|14,52"]}}]}) if "reach_south_side" in p]
ck("an exclusion two steps past the tunnel is still caught, and names the far side only",
   len(p0) == 1 and "excludes ROUTE_10|14,52" in p0[0] and "ROUTE_10|0,4, which" not in p0[0], p0)
g = "Travel through Rock Tunnel from the north side of Route 10 to its south side"
def plan(last):
    return {"goal": g, "subgoals": [{"id": "descend_to_b1f", "goal_text": "Go down to B1F", "done_when": {"map": "ROCK_TUNNEL_B1F"}},
                                     {"id": "exit_rock_tunnel_south", "goal_text": "Exit Rock Tunnel onto the south side of Route 10", "done_when": last}]}
def exit_probs(last):
    return [p for p in A.validate(plan(last)) if "exit_rock_tunnel_south" in p]
p1 = exit_probs({"map": "ROUTE_10"})
ck("a plain map exit is told the part it already came out onto, by the door's own floor",
   len(p1) == 1 and "ALREADY come out of ROCK_TUNNEL_1F onto ROUTE_10|14,52 (its door at 15,33, 2x)" in p1[0]
   and 'end on {"area": "ROUTE_10|14,52"}' in p1[0] and "new_part" not in p1[0], p1)
p2 = exit_probs({"map": "ROUTE_10", "not_area": ["ROUTE_10|0,4", "ROUTE_10|14,52"]})
ck("excluding the far side is refused, naming it as the witness",
   len(p2) == 1 and "excludes ROUTE_10|14,52" in p2[0] and 'end on {"area": "ROUTE_10|14,52"}' in p2[0], p2)
p3 = exit_probs({"any_of": [{"map": "ROUTE_12"}, {"map": "ROUTE_10", "not_area": ["ROUTE_10|14,52"]}]})
ck("any_of alternatives are read: the Route 12 leg is pinned away and the exclusion refused",
   len(p3) == 2 and any("no doorway on ROUTE_12" in p for p in p3) and any("excludes ROUTE_10|14,52" in p for p in p3), p3)
p4 = exit_probs({"area": "ROUTE_10|14,52"})
ck("ending on that part passes", p4 == [], p4)
ck("nothing names what lies past Route 10", all("LAVENDER" not in p for p in p1 + p2 + p3))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:400])
sys.exit(1 if bad else 0)
