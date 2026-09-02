"""Only a thing that can walk off is disproved by being gone (2026-09-02).

`_sweep_blockers` exists for a real case: the Snorlax on Route 16 was woken
and walked away, and its entry sat on the ways-that-turned-you-back list
saying the road was still fenced by it. When none of the things the fence
record NAMED is on the map any more, the record has expired.

The names are pulled out of the fence sentence by SHAPE, so
"the walk was fenced — WATER at (0,24) — a walk will not cross water;
nobody in the party knows SURF" yields WATER and SURF. Neither is ever an
entry in map.objects: terrain is not a person and a move is not a thing. So
"none of them is on the map any more" was TRUE the first time the party
stood there again, and every water-fenced seam cleared itself on sight.

Live cost, found while the run ping-ponged between Vermilion and Route 6:
ROUTE_6|0,3 north (turned back 9x), ROUTE_11|9,0 east, PALLET_TOWN south and
VIRIDIAN_CITY north had all been swept away, so the never-crossed roads list
said WHY IS NOT RECORDED about roads whose refusal was on file, and the
turned-back list showed three rows when it held nine.

A name the run has never once seen as an object anywhere is not evidence of
anything by its absence."""
import sys
from pathlib import Path
sys.path.insert(0, "planner")
import executor as E

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

HERE = "ROUTE_6|0,3"
WATER_FENCE = ("the walk was fenced — WATER at (0,24) — a walk will not "
               "cross water; nobody in the party knows SURF")
BODY_FENCE = "the walk was fenced — ROUTE12_SNORLAX at (0,60)"
BUSH_FENCE = "the walk was fenced — CUT_TREE (a bush CUT clears) at (14,4)"


def fake(what, objects_now, seen=("CUT_TREE", "ROUTE12_SNORLAX")):
    ex = object.__new__(E.Executor)
    ex.blockers = {"k": {"where": HERE, "key": "north", "what": what,
                         "cleared": False, "n": 9}}
    ex.sightings = {"SOMEWHERE|0,0": list(seen)}
    ex.touched = {}
    ex._where = lambda obs: HERE
    ex.log = lambda *a, **k: None
    obs = {"map": {"objects": [{"name": n} for n in objects_now]}}
    ex._sweep_blockers(obs)
    return ex.blockers["k"].get("cleared")


ck("a water fence is NOT cleared just by standing there again",
   not fake(WATER_FENCE, ["SOME_NPC"]))
ck("...not even when the map has no objects at all",
   not fake(WATER_FENCE, []))
ck("a body that walked off still clears its fence",
   fake(BODY_FENCE, ["SOME_NPC"]))
ck("...and a body still standing there does not",
   not fake(BODY_FENCE, ["ROUTE12_SNORLAX"]))
ck("a bush the run has felled still clears its fence",
   fake(BUSH_FENCE, ["SOME_NPC"]))
ck("...and a bush still standing does not",
   not fake(BUSH_FENCE, ["CUT_TREE"]))
ck("a body the run has only ever TOUCHED counts as a thing it has seen",
   fake(BODY_FENCE, ["SOME_NPC"], seen=()) is False)

ex = object.__new__(E.Executor)
ex.blockers = {"k": {"where": HERE, "key": "north", "what": BODY_FENCE,
                     "cleared": False}}
ex.sightings = {}
ex.touched = {"ROUTE_12|0,61": ["ROUTE12_SNORLAX"]}
ex._where = lambda obs: HERE
ex.log = lambda *a, **k: None
ex._sweep_blockers({"map": {"objects": []}})
ck("...so touched alone is enough vocabulary to sweep on",
   ex.blockers["k"].get("cleared"))

src = Path("planner/executor.py").read_text()
ck("the vocabulary is the run's own sightings and touches",
   'getattr(self, "sightings", None)' in src
   and 'getattr(self, "touched", None)' in src
   and "named = [n for n in named if n in _objs]" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok  " if ok else "  FAIL") + "  " + n)
print(f"\n{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
