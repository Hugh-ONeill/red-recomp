#!/usr/bin/env python3
"""The paper hop count comes with what a map cannot say.

User, 2026-08-29: "having the town map is actually probably bad for the
model, it gives it false hope of saffron". The TOWN MAP is a real item and
its layout is a real fact — withholding it would be hiding — but quoted
bare as "N leg(s) from X" it reads as a route, and the shortest paper line
runs through gates shut for most of the game. So the number now carries
the map's own limit, plus the ways THIS RUN has been turned back at, from
its own blockers ledger (evidence, never what lifts them). With no map in
the bag nothing of this is said: the line already credits only walking.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
E.PRINTED_MAP_HELD = True      # the module gate _note sets from the bag
ex = E.Executor.__new__(E.Executor)
ex._drift = {}
ex.blockers = {"SAFFRON|18,9": {"where": "ROUTE_7|18,2", "key": "18,9", "n": 4,
                                "what": "Oh wait there, the road's closed",
                                "cleared": False},
               "OLD|1,1": {"where": "OLD|1,1", "key": "1,1", "n": 1,
                           "what": "a rock in the way", "cleared": True}}
ex._cur_target = "map:CELADON_CITY"
ex._holding_town_map = lambda obs: True
ex._target_key = lambda sg: "map:CELADON_CITY"
ex._walked_map_links = lambda: {}
obs = {"map": {"id": "ROUTE_7"}}
note, _ = ex._goal_drift({"id": "x"}, obs)
ck("the paper distance is still given", "leg(s) from CELADON_CITY" in note)
ck("...with what a map cannot say", "draws the LAYOUT, not which roads are open" in note
   and "a number on paper is not a route you have walked" in note)
ck("...and the ways this run has been turned back at, most-hit first",
   "Ways that have turned you back so far: ROUTE_7|18,2 18,9" in note
   and "the road's closed" in note)
ck("a cleared blocker is not listed", "a rock in the way" not in note)
ex._holding_town_map = lambda obs: False
ex._drift = {}
note2, _ = ex._goal_drift({"id": "y"}, obs)
ck("with no map in the bag none of it is said",
   "carry no TOWN MAP" in note2 and "draws the LAYOUT" not in note2)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
