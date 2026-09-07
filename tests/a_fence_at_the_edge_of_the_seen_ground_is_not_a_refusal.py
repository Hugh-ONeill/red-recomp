"""A seam walk that stopped where the looking stopped has not been fenced.

Run 16, Viridian City (2026-09-07): `cross north` failed with the shim's
honest verdict -- "cannot be reached over the ground you have SEEN -- the
search stopped where your footprint ends, NOT at a proven wall" -- and
then, like every no-path answer, listed what stood at the edge of the
ground it could search: a CUT_TREE at (14,4).  The recorder matched that
list and wrote the seam down as "the walk was fenced -- CUT_TREE", the
blockers ledger printed it as a way that turned the run back, and the model
spent rounds looking for a way around a tree that was never in the way
(user: "the tree isnt in the way though").  The road north was simply not
on screen yet.

A footprint edge is untried ground, not a refusal: the recorder skips it,
the journal backfill skips it, and a stored fence whose every failed
crossing stopped at the footprint is dropped at boot.
"""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E

FOOT = ("cross(dir=north): FAILED — the north seam of VIRIDIAN_CITY (to ROUTE_2) "
        "cannot be reached over the ground you have SEEN — the search stopped where "
        "your footprint ends, NOT at a proven wall: ground you have never looked at "
        "may hold the way. explore walks toward it. BFS from 0,17 walked 524 cells; "
        "closest to the up edge was 6,4, still 4 cells short. Things standing at its "
        "edge: CUT_TREE (a bush CUT clears) at 14,4. That is what is beside the boundary")
WALL = ("cross(dir=north): FAILED — couldn't reach north edge gap (17,0), stuck at "
        "(17,3). Right where the walk stopped: CUT_TREE (a bush CUT clears) at 17,2")

ck("the footprint verdict is recognised", E._footprint_ended(FOOT))
ck("a proven wall is not", not E._footprint_ended(WALL))

def fresh():
    ex = E.Executor.__new__(E.Executor)
    ex.blockers = {}; ex.explored = {}; ex._outcomes = {}; ex._cur_target = "map:ROUTE_2"
    ex.hints = {}; ex.logf = open(Path(tempfile.mkdtemp(
        dir="/tmp/claude-1000/-home-wiz/b5fe8565-91da-4233-b62f-8b773e98e750/scratchpad")) / "log.jsonl", "a")
    ex.t0 = 0
    ex._where = lambda o: "VIRIDIAN_CITY|17,0"
    return ex

pre = {"map": {"id": "VIRIDIAN_CITY", "region": "17,0"}}
ex = fresh()
try:
    ex._record_outcome(pre, "cross", {"dir": "north"}, FOOT)
except Exception as e:                                   # pragma: no cover
    print("record raised:", e)
ck("a walk that stopped at the footprint writes no blocker", not ex.blockers)

ex = fresh()
try:
    ex._record_outcome(pre, "cross", {"dir": "north"}, WALL)
except Exception as e:                                   # pragma: no cover
    print("record raised:", e)
ck("a walk that died against a bush still does",
   any("the walk was fenced" in (b.get("what") or "") for b in ex.blockers.values()))

# the boot scrub: a stored fence whose journal says footprint goes; one with a wall stays
tmp = Path(tempfile.mkdtemp(dir="/tmp/claude-1000/-home-wiz/"
                            "b5fe8565-91da-4233-b62f-8b773e98e750/scratchpad"))
(tmp / "executor_log.jsonl").write_text(
    json.dumps({"kind": "escalate_feedback", "at": "VIRIDIAN_CITY|17,0", "trace": [FOOT]}) + "\n"
    + json.dumps({"kind": "escalate_feedback", "at": "ROUTE_9|0,8", "trace": [WALL.replace("north", "east")]}) + "\n")
ex = fresh()
ex.blockers = {
    "VIRIDIAN_CITY|17,0|north": {"where": "VIRIDIAN_CITY|17,0", "key": "north", "kind": "seam",
                                 "what": "the walk was fenced — CUT_TREE (a bush CUT clears) at 14,4"},
    "ROUTE_9|0,8|east": {"where": "ROUTE_9|0,8", "key": "east", "kind": "seam",
                         "what": "the walk was fenced — CUT_TREE (a bush CUT clears) at 17,2"}}
_run = E.RUN
E.RUN = tmp
try:
    ex._scrub_footprint_fences()
finally:
    E.RUN = _run
ck("the footprint fence is scrubbed at boot", "VIRIDIAN_CITY|17,0|north" not in ex.blockers)
ck("...and the real wall keeps its record", "ROUTE_9|0,8|east" in ex.blockers)

src = Path("planner/executor.py").read_text()
ck("the journal backfill applies the same rule",
   'and not _footprint_ended(_t):' in src)
ck("the scrub runs when the memory is loaded",
   "self._scrub_footprint_fences()" in src.split("BACKFILL THE BLOCKERS FROM THE JOURNAL")[0])

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
