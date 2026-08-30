"""A condition true of almost everywhere cannot witness anything.

"Clear Rock Tunnel" was finally authorable (the deed rule learned that a
place the run has never reached is a change the world can witness) and the
plan it produced ended on {"not_area": "ROUTE_10|0,0"}. That reads "you are
not standing in that one region", which is true in every room in Kanto but
one. The campaign reported the leg complete on attempt 1, from Vermilion
City, having fired no event, gained no item and entered no new place
(2026-08-30). Same family as has_item with a count of 0.

not_area exists for one job and its own comment in the executor says so:
"A PART OF A MAP OTHER THAN THE ONE YOU KNOW... Pair it with 'map'". The
pair is the ONLY door out of the split-route class — ROUTE_10 lies on both
sides of Rock Tunnel and {"map": "ROUTE_10"} alone is satisfied by the side
you started on — so it must keep working.

And the region excluded has to be one the run has stood in. You cannot leave
somewhere you have never been: ROUTE_10|0,0 was a guess at a name, not the
region the party actually stands in on Route 10, so it excluded nothing.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

_m, _r = A.visited_maps, A.visited_regions
A.visited_maps = lambda: {"ROUTE_10", "VERMILION_CITY"}
A.visited_regions = lambda: {"ROUTE_10|0,4", "VERMILION_CITY|18,0"}
try:
    def v(dw, goal="Clear Rock Tunnel"):
        return A.validate({"goal": goal, "subgoals": [
            {"id": "a", "goal_text": "t", "done_when": dw}]})

    p = v({"not_area": "ROUTE_10|0,0"})
    ck("not_area alone is refused", bool(p), p)
    ck("...saying it holds where you stand right now",
       p and "holds where you are standing right now" in p[0], p)
    ck("...and showing the pairing that means something",
       p and '{"map": "THAT_MAP", "not_area": "THAT_MAP|x,y"}' in p[0]
   and "in a part other than the one I know" in p[0], p)

    q = v({"map": "ROUTE_10", "not_area": "ROUTE_10|0,0"})
    ck("excluding a region never stood in is refused", bool(q), q)
    ck("...because the exclusion excludes nothing",
       q and "excludes nothing" in q[0], q)

    ck("THE PAIR STILL WORKS — it is the only way to say 'the far side'",
       not v({"map": "ROUTE_10", "not_area": "ROUTE_10|0,4"}),
       v({"map": "ROUTE_10", "not_area": "ROUTE_10|0,4"}))
    ck("...and is not refused as a place already stood in",
       not any("ALREADY stood in" in x
               for x in v({"map": "ROUTE_10", "not_area": "ROUTE_10|0,4"})))

    # a mid-plan not_area is judged the same way: a step that is already
    # true is a step that runs no ops
    ck("a middle subgoal is checked too",
       any("not_area alone" in x for x in A.validate({
           "goal": "Clear Rock Tunnel", "subgoals": [
               {"id": "a", "goal_text": "t",
                "done_when": {"not_area": "ROUTE_10|0,0"}},
               {"id": "b", "goal_text": "t",
                "done_when": {"map": "LAVENDER_TOWN"}}]})))
    # ...and nothing else is disturbed
    ck("a plain map condition is untouched",
       not v({"map": "LAVENDER_TOWN"}))
finally:
    A.visited_maps, A.visited_regions = _m, _r

ex = (ROOT / "planner" / "executor.py").read_text()
ck("the pairing this quotes is the executor's own instruction",
   "Pair it with \"map\"" in ex or 'Pair it with "map"' in ex)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:220])
sys.exit(1 if bad else 0)
