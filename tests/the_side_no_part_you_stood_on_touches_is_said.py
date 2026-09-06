#!/usr/bin/env python3
"""The side no part you have stood on touches is said to be out of reach
from here.

Route 23, 2026-09-06. The head said the printed map's road runs north to
the Indigo Plateau and that the north side had never been on screen; the
same page said both halves of Route 23 the run knew were fully worked; and
the run spent an attempt surfing the pond to "uncover the northern
boundary", then let explore walk it back to Route 22 three times. Every
fact was there. The conclusion the run's own record supports was not: when
every part of this map you have stood on is fully seen and a side has never
been on screen, nothing you can walk or swim to from any of them reaches
that side, so the way to it starts somewhere else. Where, is not said —
the door into Victory Road is the model's to remember.

Said only when it is true of the record: any unseen ground, water frontier
or wall that may have moved on this part, or any other part with ground
never on screen, and the sentence stays off.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import ledger                                        # noqa: E402
import candidates as C                               # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def page(seen=None, region_seen=None, visits=None, sides_unseen=("north",)):
    ex = C.make()
    ex._where = lambda o: "ROUTE_23|10,104"
    ex._explore_trips = {}
    ex.visits = visits if visits is not None else {"ROUTE_23|10,104": 16, "ROUTE_23|4,31": 8}
    ex.region_seen = region_seen if region_seen is not None else {"ROUTE_23|10,104": 0, "ROUTE_23|4,31": 0}
    obs = {"map": {"id": "ROUTE_23", "region": "10,104", "warps": [],
                   "sides": ["south"], "sides_unseen": list(sides_unseen),
                   "seen": dict(seen or {})},
           "player": {"x": 10, "y": 104}, "party": [], "bag": {}}
    return ledger.render([], ex, obs, "map:INDIGO_PLATEAU")

KEY = "NO PART OF THIS MAP YOU HAVE STOOD ON TOUCHES ITS NORTH SIDE"
t = page()
ck("with both known parts fully seen and the north never on screen, it is said", KEY in t)
ck("...counting the parts and naming them",
   "you have stood on 2 part(s) of it (ROUTE_23|10,104, ROUTE_23|4,31)" in t)
ck("...and saying where the way must start without saying where it is",
   "starts somewhere else" in t and "VICTORY_ROAD" not in t.split(KEY)[1][:400])
ck("unseen ground still reachable here keeps it off", KEY not in page(seen={"frontier_n": 3}))
ck("water still to ride here keeps it off", KEY not in page(seen={"frontier_water_n": 2}))
ck("a wall that may have moved here keeps it off", KEY not in page(seen={"frontier_stale_n": 1}))
ck("another part with ground never on screen keeps it off",
   KEY not in page(region_seen={"ROUTE_23|10,104": 0, "ROUTE_23|4,31": 5}))
ck("a map with every side seen has nothing to say", KEY not in page(sides_unseen=()))
ck("the record's own regions count, not a guess",
   "you have stood on 1 part(s)" in page(visits={"ROUTE_23|10,104": 1}, region_seen={}))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
