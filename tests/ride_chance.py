"""One replay of a walked route whose only broken leg is a swim.

A blocked_at stamp makes _route refuse the whole chain -- right for a road
something really shut.  But Seafoam's two halves join through ONE swim
(B3F|1,0 --25,14--> B2F|23,10), and what broke it was US: `go` replays door
hops on foot, the walk could not reach a tile across water, and the edge took
the stamp.  Six walked hops went dark on that; route_ride never fired once in
four attempts, because the ride lives inside _walk_route and _route refuses
before any hop runs.  This hands the route back ONCE per edge per world mark
so the leg can be re-walked riding, which is how it was walked to begin with.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

MARK = [6, 305, 17]
CHAIN = [
    ("SEAFOAM_ISLANDS_1F|3,2", "7,5", "SEAFOAM_ISLANDS_B1F|11,0"),
    ("SEAFOAM_ISLANDS_B1F|11,0", "13,7", "SEAFOAM_ISLANDS_B2F|11,4"),
    ("SEAFOAM_ISLANDS_B2F|11,4", "5,13", "SEAFOAM_ISLANDS_B3F|1,0"),
    ("SEAFOAM_ISLANDS_B3F|1,0", "25,14", "SEAFOAM_ISLANDS_B2F|23,10"),
    ("SEAFOAM_ISLANDS_B2F|23,10", "25,11", "SEAFOAM_ISLANDS_B1F|20,10"),
    ("SEAFOAM_ISLANDS_B1F|20,10", "23,15", "SEAFOAM_ISLANDS_1F|21,12"),
]
HERE, THERE = "SEAFOAM_ISLANDS_1F|3,2", "SEAFOAM_ISLANDS_1F|21,12"

class FakeBridge:
    def __init__(self, obs): self._o = obs
    def obs(self): return self._o

def build(stamped="25,14", *, surf=True, water=True):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = {}
    for src, key, dst in CHAIN:
        e = {"n": 2, "to": dst}
        if key == stamped:
            e["blocked_at"] = MARK
        ex.explored.setdefault(src, {})[key] = e
    ex._mark_now = MARK
    ex._bad_seam = set()
    ex._ride_tried = set()
    ex.log = lambda *a, **k: None
    party = [{"moves": ["SURF"] if surf else ["TACKLE"]}]
    m = {"id": "SEAFOAM_ISLANDS_B3F"}
    if water:
        m["water"] = {"cells": 120}
    ex.b = FakeBridge({"party": party, "map": m})
    return ex

ex = build()
ck("the stamped chain has no live route", ex._route(HERE, THERE) is None)
first = ex._ride_chance(HERE, [THERE])
ck("a ridden replay is offered once", first is not None)
if first:
    ck("it offers the full walked route", len(first[1]) == 6)
    ck("it aims at the right place", first[0] == THERE)
ck("it is NOT offered a second time at the same mark",
   ex._ride_chance(HERE, [THERE]) is None)

# when the mark moves the stamp no longer applies at all: the route is
# simply live again, and nothing needs offering
ex._mark_now = [7, 306, 18]
ck("a moved world mark makes the route live again",
   len(ex._route(HERE, THERE) or []) == 6)
ck("and then there is nothing to offer",
   ex._ride_chance(HERE, [THERE]) is None)

# guards
ck("no SURF, no ride", build(surf=False)._ride_chance(HERE, [THERE]) is None)
ck("a dry floor is never ridden",
   build(water=False)._ride_chance(HERE, [THERE]) is None)
ck("nothing stamped, nothing to offer",
   build(stamped=None)._ride_chance(HERE, [THERE]) is None)

# a seam hop (no comma in the key) is not a swim we can ride
ex = E.Executor.__new__(E.Executor)
ex.explored = {HERE: {"west": {"n": 2, "to": THERE, "blocked_at": MARK}}}
ex._mark_now, ex._bad_seam, ex._ride_tried = MARK, set(), set()
ex.log = lambda *a, **k: None
ex.b = FakeBridge({"party": [{"moves": ["SURF"]}],
                   "map": {"id": "X", "water": {"cells": 9}}})
ck("a stamped SEAM is not offered a ride",
   ex._ride_chance(HERE, [THERE]) is None)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
