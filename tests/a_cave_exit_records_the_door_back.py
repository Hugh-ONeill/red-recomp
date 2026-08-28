#!/usr/bin/env python3
"""Coming out of a cave records the outdoor door as the way back in.

A cave or tunnel exit lands the party one tile BESIDE the outdoor door
(Seafoam's west door: door at ROUTE_20 (58,9), landing (58,10)), and the
arrival recorder only wrote the reverse edge when the landing tile WAS a
doorway. So the outdoor side of every such exit stayed unrecorded until
the run happened to walk in through it, and `go FUCHSIA_CITY` from
Cinnabar said "no walked way" over a chain walked an hour before
(2026-08-28). Landing outdoors from an indoor map, a doorway one step
away that leads back to the map you left is the door you came out of.
Also: the edge's `land` (where a door put you) was read from map.player,
a key that does not exist, and no edge ever carried one.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import executor as E          # noqa: E402
import candidates as C        # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))

def fresh():
    ex = C.make()
    ex.explored = {}
    for name, val in (("_cur_target", None), ("_faint_at", None), ("_entered_map", {}),
                      ("_bad_seam", set()), ("_arrived", None), ("_came_from", None),
                      ("_reversals", 0), ("_entered_by", {})):
        if not hasattr(ex, name):
            setattr(ex, name, val)
    ex.log = lambda *a, **k: None          # no journal file in a fixture
    ex._save_memory = lambda *a, **k: None
    ex.blockers = {}
    ex._clear_blocker = lambda *a, **k: None
    return ex

before = {"map": {"id": "SEAFOAM_ISLANDS_1F", "region": "21,12", "outdoor": False,
                  "warps": [{"x": 26, "y": 17, "dest": "ROUTE_20", "returns": True}]},
          "player": {"x": 26, "y": 16}}
after = {"map": {"id": "ROUTE_20", "region": "58,9", "outdoor": True,
                 "warps": [{"x": 58, "y": 9, "dest": "SEAFOAM_ISLANDS_1F"}]},
         "player": {"x": 58, "y": 10}}
ex = fresh()
ex.note_transition(before, {"op": "use_warp", "x": 26, "y": 17}, after)
back = (ex.explored.get("ROUTE_20|58,9") or {}).get("58,9") or {}
ck("landing beside the outdoor door records it as the way back",
   back.get("to") == "SEAFOAM_ISLANDS_1F|21,12" and back.get("n") == 0)
fwd = (ex.explored.get("SEAFOAM_ISLANDS_1F|21,12") or {}).get("26,17") or {}
ck("...the exit itself is recorded as taken", fwd.get("to") == "ROUTE_20|58,9" and fwd.get("n") == 1)
ck("...and the edge now carries where the door put you", fwd.get("land") == "58,10")

# beside-the-door only holds for landing OUTDOORS from INDOORS
after_in = {"map": {"id": "SEAFOAM_ISLANDS_B1F", "region": "20,10", "outdoor": False,
                    "warps": [{"x": 23, "y": 15, "dest": "SEAFOAM_ISLANDS_1F"}]},
            "player": {"x": 23, "y": 16}}
ex = fresh()
ex.note_transition(before, {"op": "use_warp", "x": 26, "y": 17}, after_in)
ck("indoors, a doorway one step away is not assumed to be the way back",
   "23,15" not in (ex.explored.get("SEAFOAM_ISLANDS_B1F|20,10") or {}))
# a doorway beside the landing that leads somewhere ELSE is not it either
after_other = {"map": {"id": "ROUTE_20", "region": "58,9", "outdoor": True,
                       "warps": [{"x": 58, "y": 9, "dest": "CINNABAR_LAB"}]},
               "player": {"x": 58, "y": 10}}
ex = fresh()
ex.note_transition(before, {"op": "use_warp", "x": 26, "y": 17}, after_other)
ck("...nor one that leads somewhere else", "58,9" not in (ex.explored.get("ROUTE_20|58,9") or {}))
# landing ON the door still works as before
after_on = {"map": {"id": "ROUTE_20", "region": "58,9", "outdoor": True,
                    "warps": [{"x": 58, "y": 9, "dest": "SEAFOAM_ISLANDS_1F"}]},
            "player": {"x": 58, "y": 9}}
ex = fresh()
ex.note_transition(before, {"op": "use_warp", "x": 26, "y": 17}, after_on)
ck("landing on the door records it as before",
   ((ex.explored.get("ROUTE_20|58,9") or {}).get("58,9") or {}).get("to") == "SEAFOAM_ISLANDS_1F|21,12")

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
