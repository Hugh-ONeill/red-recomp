"""A route with one hop down is still a route you walked.

_route skips hops stamped blocked in THIS world state -- right -- and the
page then said "no walked route from here is known", the harness denying
its own record.  Leg 42's chain out of Seafoam is eight walked hops and ONE
of them (B3F|1,0 --25,14--> B2F|23,10, the swim across B3F) carried the
stamp, so the model was told it had never found a way to ground it had
crossed twice that day.  `go`'s own refusal has worded this honestly all
along: "or a hop on it has failed in this world state".
"""
import json
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

MARK = [6, 305, 17]
CHAIN = [
    ("ROUTE_20|52,2", "48,5", "SEAFOAM_ISLANDS_1F|3,2"),
    ("SEAFOAM_ISLANDS_1F|3,2", "7,5", "SEAFOAM_ISLANDS_B1F|11,0"),
    ("SEAFOAM_ISLANDS_B1F|11,0", "13,7", "SEAFOAM_ISLANDS_B2F|11,4"),
    ("SEAFOAM_ISLANDS_B2F|11,4", "5,13", "SEAFOAM_ISLANDS_B3F|1,0"),
    ("SEAFOAM_ISLANDS_B3F|1,0", "25,14", "SEAFOAM_ISLANDS_B2F|23,10"),
    ("SEAFOAM_ISLANDS_B2F|23,10", "25,11", "SEAFOAM_ISLANDS_B1F|20,10"),
    ("SEAFOAM_ISLANDS_B1F|20,10", "23,15", "SEAFOAM_ISLANDS_1F|21,12"),
    ("SEAFOAM_ISLANDS_1F|21,12", "26,17", "ROUTE_20|58,9"),
]

def build(block_hop=None):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = {}
    for src, key, dst in CHAIN:
        e = {"n": 2, "to": dst}
        if key == block_hop:
            e["blocked_at"] = MARK
        ex.explored.setdefault(src, {})[key] = e
    ex.visits = {r: 2 for r, _, _ in CHAIN}
    ex.visits["ROUTE_20|58,9"] = 2
    ex._mark_now = MARK
    ex._bad_seam = set()
    return ex

FRM, TO = "ROUTE_20|52,2", "ROUTE_20|58,9"

ex = build()
ck("the whole chain routes when nothing is stamped",
   len(ex._route(FRM, TO) or []) == 8)

ex = build(block_hop="25,14")
ck("one stamped hop kills the live route", ex._route(FRM, TO) is None)
ck("and ignore_blocked still finds it",
   len(ex._route(FRM, TO, ignore_blocked=True) or []) == 8)

# the page must say which of the two it is
import ledger
obs = {"party": [{"moves": ["SURF"]}],
       "map": {"id": "ROUTE_20", "region": "52,2"}}
ex = build(block_hop="25,14")
ex.sightings = {TO: ["ROUTE20_SWIMMER4"]}
ex.frontier, ex.shut_doors, ex.dead_ends, ex.map_doors = {}, {}, {}, {}
ex._where = lambda _o: FRM

stuck = ledger.Candidate(key="ROUTE20_SWIMMER4", kind="npc",
                         status="unreachable", reachable=False)

try:
    page = ledger.render([stuck], ex, obs)
except Exception as e:                               # pragma: no cover
    page = "RENDER FAILED: %r" % (e,)
head = page.splitlines()[0] if page else ""
ck("the page no longer denies the record",
   "no walked route from here is known" not in head)
ck("it says a route was walked", "HAVE walked a route there" in head)
ck("it says a hop would not land", "would not land" in head)
ck("it still refuses to replay it", "not being replayed" in head)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("HEAD WAS:", head[:600])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
