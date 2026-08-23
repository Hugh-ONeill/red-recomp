"""Say WHICH leg is down, not that the way was never walked.

A stamped hop makes _route return nothing, and both `go` refusals then said
only "no walked way ... is known".  Seafoam's two halves join through ONE
swim (B3F|1,0 --25,14--> B2F|23,10); it failed once, took the stamp, and
every route between the island's halves went dark at once -- six walked hops
refused as if never walked, while the model was told it had never found a
way there.  Which leg is down is a fact about the run's own record.
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

def build(stamped=None):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = {}
    for src, key, dst in CHAIN:
        e = {"n": 2, "to": dst}
        if key == stamped:
            e["blocked_at"] = MARK
        ex.explored.setdefault(src, {})[key] = e
    ex._mark_now = MARK
    ex._bad_seam = set()
    return ex

ex = build()
ck("clean chain routes end to end", len(ex._route(HERE, THERE) or []) == 6)
ck("nothing to report when nothing is stamped",
   ex._blocked_hop(HERE, [THERE]) is None)

ex = build(stamped="25,14")
ck("the stamped hop kills the live route", ex._route(HERE, THERE) is None)
found = ex._blocked_hop(HERE, [THERE])
ck("the down leg is identified", found is not None)
if found:
    t, path, src, key, dst = found
    ck("it names the right target", t == THERE)
    ck("it names the right leg", key == "25,14")
    ck("it names the leg's source", src == "SEAFOAM_ISLANDS_B3F|1,0")
    ck("it names the leg's destination", dst == "SEAFOAM_ISLANDS_B2F|23,10")
    ck("it reports the full length", len(path) == 6)

# a genuinely unwalked target is still reported as unwalked
ex = build(stamped="25,14")
ck("an unconnected place reports nothing to replay",
   ex._blocked_hop(HERE, ["CINNABAR_ISLAND|0,0"]) is None)

# a stamp on a hop of a route we never had is not invented either
ex = build()
del ex.explored["SEAFOAM_ISLANDS_B2F|23,10"]
ck("a broken chain has no hop to name",
   ex._blocked_hop(HERE, [THERE]) is None)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
