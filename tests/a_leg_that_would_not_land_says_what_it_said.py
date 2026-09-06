"""A `go` refused for a leg that would not land quotes what that leg said.

Run 15 stamped 315 edges blocked-for-now and `go` was refused over and over
with "one leg of it would not land the last time it was tried in this world
state" -- Route 9's three walk edges 48 times between them, the Mansion's
B1F door, Seafoam B3F's swim, Route 23 -- and the refusal never said what
the leg had said (autopsy, 2026-09-06).  The walk's own result had named it
the moment it failed: a ledge at the edge of the ground, a scientist beside
the boundary, Lorelei standing on the tile.  The stamp kept the world mark
and threw the reason away.  A road that will not land because someone
stands on it and one that will not land because it was walked DOWN a ledge
are two different things to do next, and the record knew which.

So every stamp keeps the leg's own words, and the refusal -- executor `go`,
the prewalk, and the ledger's head -- quotes them, dated by how many times
the leg had landed before.  Nothing inferred.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E
import ledger as L

MARK = [6, 305, 17]
WHY = ("couldn't reach (0,8): the ground you can walk from here is 40 "
       "cell(s) and the closest it comes to 0,8 is 4,7. At the EDGE of that "
       "ground stand: a LEDGE along 3 cell(s) at 3,7 4,8 5,8 — its high "
       "side is beyond you")
CHAIN = [
    ("ROUTE_10|3,5", "west", "ROUTE_9|50,6"),
    ("ROUTE_9|50,6", "walk:ROUTE_9|0,8", "ROUTE_9|0,8"),
    ("ROUTE_9|0,8", "west", "CERULEAN_CITY|39,20"),
]


def build(why=WHY):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = {}
    for src, key, dst in CHAIN:
        e = {"n": 3, "to": dst}
        if key.startswith("walk:"):
            e["blocked_at"] = MARK
            if why is not None:
                e["blocked_why"] = why
        ex.explored.setdefault(src, {})[key] = e
    ex.visits = {r: 2 for r, _, _ in CHAIN}
    ex.visits["CERULEAN_CITY|39,20"] = 2
    ex._mark_now = MARK
    ex._bad_seam = set()
    return ex


HERE, THERE = "ROUTE_10|3,5", "CERULEAN_CITY|39,20"
ex = build()
ck("the stamped walk kills the live route", ex._route(HERE, THERE) is None)
found = ex._blocked_hop(HERE, [THERE])
ck("the down leg is the walk across Route 9",
   found is not None and found[3] == "walk:ROUTE_9|0,8")
words = ex._blocked_words("ROUTE_9|50,6", "walk:ROUTE_9|0,8", "ROUTE_9|0,8")
ck("the refusal quotes what the leg said", "a LEDGE along 3 cell(s)" in words)
ck("...under a heading that says whose words they are",
   "WHAT THAT LEG SAID when it refused" in words)
ck("...dated by how often it had landed", "had landed 3 time(s) before" in words)

ex = build(why=None)
words = ex._blocked_words("ROUTE_9|50,6", "walk:ROUTE_9|0,8", "ROUTE_9|0,8")
ck("a stamp from before today has no words and none are invented",
   "WHAT THAT LEG SAID" not in words and "had landed 3 time(s)" in words)
ck("an edge that is not on the record says nothing",
   ex._blocked_words("NOWHERE|1,1", "x", "NOWHERE|2,2") == "")

# the ledger head names the leg and quotes it. The head speaks when a
# thing on THIS floor sits in ground the run has stood in before but no
# live route reaches: Route 9's west pocket, seen from its east side.
ex = build()
R_EAST, R_WEST = "ROUTE_9|50,6", "ROUTE_9|0,8"
obs = {"map": {"id": "ROUTE_9", "region": "50,6", "warps": [],
               "objects": []}, "party": []}
ex.sightings = {R_WEST: ["ROUTE9_CUT_TREE_5_8"]}
ex.frontier, ex.shut_doors, ex.dead_ends, ex.map_doors = {}, {}, {}, {}
ex._where = lambda _o: R_EAST
stuck = L.Candidate(key="ROUTE9_CUT_TREE_5_8", kind="cut_tree",
                    status="unreachable", reachable=False)
try:
    page = L.render([stuck], ex, obs)
except Exception as e:                               # pragma: no cover
    page = "RENDER FAILED: %r" % (e,)
head = page.splitlines()[0] if page else ""
ck("the head still says a hop would not land", "would not land" in head)
ck("the head names the leg",
   "ROUTE_9|50,6 --walk:ROUTE_9|0,8--> ROUTE_9|0,8" in head)
ck("the head quotes what it said", "a LEDGE along 3 cell(s)" in head)

# every stamp keeps the reason, and both `go` refusals read it back
src = Path("planner/executor.py").read_text()
ck("the walk stamp keeps the walk's words",
   '_wrec["blocked_why"] = (' in src
   and 'str(_wdet)[:self.WHY_BUDGET] if _wdet else' in src)
ck("the door stamp keeps the hop's words",
   'rec["blocked_why"] = str(_last_det or "")[' in src)
ck("the lift stamp keeps what the lift did",
   '_lrec["blocked_why"] = (' in src)
ck("the walk stamp's journal row carries the reason",
   'self.log("walk_edge_blocked",' in src
   and 'why=_wrec["blocked_why"][:200]' in src)
ck("`go` reads it back", "+ self._blocked_words(_src, _k, _dst)], []" in src)
ck("the prewalk reads it back",
   "+ self._blocked_words(_s2, _k2, _d2))" in src)

# the shim names a ledge at the edge of the ground, so the words exist
lua = Path("harness/shim.lua").read_text()
ck("the no-path detail names a ledge at the boundary",
   'a LEDGE along %d cell(s) at %s%s' in lua
   and "hopped down and never" in lua)
ck("...listed with what stands at the edge, under its 'not the cause' rule",
   lua.index('a LEDGE along %d cell(s)') <
   lua.index("that is what is beside the boundary, not a claim"))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("HEAD WAS:", head[:900])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
