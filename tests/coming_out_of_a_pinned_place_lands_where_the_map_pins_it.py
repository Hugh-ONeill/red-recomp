#!/usr/bin/env python3
"""A step that comes out of a place the Town Map pins to a road cannot end on
a road with no doorway into it.

Run 16, 2026-09-07: "Travel through Rock Tunnel from the north side of Route
10 to its south side" was planned with its exit step ending on ROUTE_11,
then on ROUTE_12. The first plan finished the moment the run stepped east
out of Vermilion onto Route 11 (the objective-met-early rule read the last
step's condition), and the ladder found the leg undone. The run holds the
Town Map, which draws ROCK TUNNEL on ROUTE 10; planner/map_doors.json is
that drawing, written once before for the Diglett's Cave / Rock Tunnel
swap. The exit rule now refuses the road with no doorway and names the one
with it. What lies past that road stays unsaid.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

A.holding_town_map = lambda: True        # the run has the map for this test
pe = A._printed_entrances("ROCK_TUNNEL_B1F")
ck("Rock Tunnel, any floor, is pinned to Route 10", pe and pe[0] == "ROCK TUNNEL" and pe[1] == {"ROUTE_10"}, pe)
pe2 = A._printed_entrances("DIGLETTS_CAVE")
ck("Diglett's Cave has doorways on Routes 2 and 11", pe2 and pe2[1] == {"ROUTE_2", "ROUTE_11"}, pe2)
ck("an unlabelled interior is unknown", A._printed_entrances("VERMILION_GYM") is None)
g = "Travel through Rock Tunnel from the north side of Route 10 to its south side"
def plan(exit_map):
    return {"goal": g, "subgoals": [
        {"id": "north_route_10", "goal_text": "Reach the north side of Route 10", "done_when": {"map": "ROUTE_10"}},
        {"id": "enter_tunnel", "goal_text": "Enter Rock Tunnel", "done_when": {"map": "ROCK_TUNNEL_1F"}},
        {"id": "exit_rock_tunnel_south", "goal_text": "Exit Rock Tunnel onto the south side", "done_when": {"map": exit_map}}]}
p12 = [p for p in A.validate(plan("ROUTE_12")) if "exit_rock_tunnel_south" in p]
ck("exiting the tunnel onto Route 12 is refused, naming Route 10",
   len(p12) == 1 and "the printed map pins ROCK TUNNEL to ROUTE_10" in p12[0] and "no doorway on ROUTE_12" in p12[0], p12)
ck("...with the new_part form for the far side", p12 and '{"new_part": "ROUTE_10"}' in p12[0])
p11 = [p for p in A.validate(plan("ROUTE_11")) if "exit_rock_tunnel_south" in p]
ck("...and onto Route 11 likewise", len(p11) == 1 and "ROUTE_11 leads into it" in p11[0], p11)
p10 = [p for p in A.validate(plan("ROUTE_10")) if "printed map pins" in p]
ck("onto Route 10 the pin rule is silent (the exit rule's own new_part advice takes over)", p10 == [], p10)
ck("nothing names what lies past the road", all("LAVENDER" not in p for p in p12 + p11))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:300])
sys.exit(1 if bad else 0)
