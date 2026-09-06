#!/usr/bin/env python3
"""A door you did not ask for is not the one you asked for.

Victory Road 1F, 2026-09-06. `go` put the party on 1F standing on the
entrance mat it came in by. walk_to(1,1) failed honestly — the barrier was
shut. Then use_warp(1,1) answered "ok (map->ROUTE_23, moved, warped)", and
the party stood outside on Route 23 (user: "shunted it out the door to rt
23 for some reason").

Three things went wrong in a row:

  yield_ground   the retry backs off a tile so a pinned NPC can move, and
                 checks that the cell it steps to is not a warp. Standing
                 ON a bottom-row door, "down" is off the map, so not a
                 warp — and a blocked press toward the edge is exactly how
                 an edge door fires. It walked the party out.
  use_warp       saw the map change under an attempt that never reached
                 its door and called it "warped" — a success for the door
                 it was asked for.
  note_transition filed the landing against the door the op AIMED at, so
                 the ledger said the 1F ladder at (1,1) leads to Route 23,
                 three times, against door_dests' own VICTORY_ROAD_2F.

Now: on a warp tile a yield is only a step that lands on walkable ground;
an attempt whose map changed without reaching its door is a failure that
says which door did NOT fire and where the party is; and a door edge whose
destination contradicts the door's own table is refused at the source and
dropped from the file on load.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                 # noqa: E402
SHIM = (ROOT / "harness/shim.lua").read_text()
EXEC = (ROOT / "planner/executor.py").read_text()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

yg = SHIM[SHIM.index("local function yield_ground(G)"):SHIM.index("local function yield_ground(G)") + 2400]
ck("yield_ground knows when it stands on a door", "local on_warp = is_warp(p.cellX, p.cellY)" in yg)
ck("...and on one only steps where the engine says a step lands",
   "ow.map:inBounds(nx, ny)" in yg and "Collision.canMove(ow.map, ow.entities, p, dir)" in yg
   and "if safe and walk(G, dir, 1) then" in yg)
ck("...off a door it yields as before", "if on_warp then" in yg)

uw = SHIM[SHIM.index("function OPS.use_warp"):SHIM.index("function OPS.use_warp") + 30000]
ck("a crossing mid-walk is no longer a success",
   'return false, ("couldn\'t reach (%d,%d): the walk toward it crossed a "' in uw
   and "(door unknown)" in uw)
ck("a map change under an attempt that reached no door is not 'warped'",
   "if ok or (ow.map and ow.map.id) ~= startMap then" not in uw
   and "if _nowmap ~= startMap then" in uw
   and "carried through a DIFFERENT door (door " in uw)
ck("...and says nothing about where the asked door leads",
   uw.count("says nothing about where (%d,%d) leads") == 2)

# --- the ledger repair, on the incident's own data -------------------------
explored = {
    "VICTORY_ROAD_1F|5,9": {"8,17": {"to": "ROUTE_23|4,31", "n": 7},
                            "9,17": {"to": "ROUTE_23|4,31", "n": 7},
                            "1,1": {"to": "ROUTE_23|4,31", "n": 3},
                            "walk:VICTORY_ROAD_1F|14,0": {"to": "VICTORY_ROAD_1F|14,0", "n": 2}},
    "VICTORY_ROAD_1F|14,0": {"1,1": {"to": "VICTORY_ROAD_2F|1,5", "n": 4}},
    "CELADON_MART_ELEVATOR|1,1": {"lift:CELADON_MART_5F": {"to": "CELADON_MART_5F|2,2", "n": 3}},
    "DIGLETTS_CAVE|5,5": {"3,3": {"to": "ROUTE_2|1,1", "n": 1}},
}
dd = {"VICTORY_ROAD_1F": {"8,17": "ROUTE_23", "9,17": "ROUTE_23", "1,1": "VICTORY_ROAD_2F"},
      "DIGLETTS_CAVE": {"3,3": "LAST_MAP"}}
n = E.drop_edges_contradicting_doors(explored, dd)
ck("the poisoned ladder edge is dropped, and only it", n == 1 and "1,1" not in explored["VICTORY_ROAD_1F|5,9"])
ck("the honest edges stay", explored["VICTORY_ROAD_1F|5,9"]["8,17"]["n"] == 7
   and explored["VICTORY_ROAD_1F|14,0"]["1,1"]["to"] == "VICTORY_ROAD_2F|1,5")
ck("walk and lift edges are not doors", "walk:VICTORY_ROAD_1F|14,0" in explored["VICTORY_ROAD_1F|5,9"]
   and "lift:CELADON_MART_5F" in explored["CELADON_MART_ELEVATOR|1,1"])
ck("a LAST_MAP door has no one answer and is left alone", "3,3" in explored["DIGLETTS_CAVE|5,5"])
ck("running it again drops nothing", E.drop_edges_contradicting_doors(explored, dd) == 0)
ck("an edge with a skip suffix is judged by its door",
   E.drop_edges_contradicting_doors({"R|0,0": {"4,4#skip2": {"to": "B|1,1"}}}, {"R": {"4,4": "C"}}) == 1)
ck("the loader runs it", "_nd = drop_edges_contradicting_doors(self.explored, self.door_dests)" in EXEC)
ck("and note_transition refuses such a landing at the source",
   'self.log("transition_dropped_contradicts_door"' in EXEC
   and 'and "," in str(key) and str(dst).split("|")[0] != str(_known)' in EXEC)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
