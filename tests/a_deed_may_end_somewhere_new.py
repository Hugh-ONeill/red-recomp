"""Two rules shut a leg out between them.

"A PLACE YOU HAVE ALREADY STOOD IN WITNESSES NOTHING" refuses a finish line
that holds before the plan takes a step, and tells the author, in these
words: "End on what the objective CHANGES, or on a place the run has never
reached." The DEED rule then refused a place of ANY kind, so the second half
of that sentence was a door painted on a wall.

"Clear Rock Tunnel" is the leg that fell through the gap (2026-08-30). Kanto
writes no flag for coming out of that tunnel; there is no item in it and no
badge; ROUTE_10 lies on BOTH sides, so the near side is already stood in. The
only thing the deed leaves is that the party is standing somewhere it has
never stood. Five authoring rounds, every one refused, and the leg could not
be written at all — which then sent it back to the ladder to be moved or
voided, twice.

Arriving somewhere new IS a change the world can witness. That is why the
travel exemption on the sibling rule exists; this is the same fact reached
from the other side.
"""
import sys, json, tempfile, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

_real_visited = A.visited_maps
_real_regions = A.visited_regions
A.visited_maps = lambda: {"ROUTE_10", "ROCK_TUNNEL_1F", "VERMILION_CITY"}
A.visited_regions = lambda: {"ROUTE_10|0,4", "ROCK_TUNNEL_1F|14,2",
                             "VERMILION_CITY|18,0"}
try:
    def plan(goal, dw, **extra):
        return {"goal": goal, "subgoals": [
            {"id": "a", "goal_text": "step", "done_when": dw}]}
    def probs(*a, **k):
        return [p for p in A.validate(plan(*a, **k))]

    p = probs("Clear Rock Tunnel", {"map": "ROUTE_10"})
    ck("a deed ending where the run already stood is still refused", bool(p), p)
    ck("...and the refusal names the place", p and "ROUTE_10" in p[0], p)

    ck("a deed MAY end on a place the run has never stood in",
       not probs("Clear Rock Tunnel", {"map": "LAVENDER_TOWN"}),
       probs("Clear Rock Tunnel", {"map": "LAVENDER_TOWN"}))
    # AN AREA IS A REGION. ROUTE_10 lies on BOTH sides of Rock Tunnel, so
    # judging the far side by its map name matched the near side and
    # refused the only condition that can express "the side I have never
    # been" — the same ROUTE_4-on-both-sides trap observed_text has warned
    # about from the start.
    ck("the far side of a two-sided map is somewhere new",
       not probs("Clear Rock Tunnel", {"area": "ROUTE_10|11,60"}),
       probs("Clear Rock Tunnel", {"area": "ROUTE_10|11,60"}))
    ck("...while the side already stood in is still refused",
       any("ALREADY stood in" in x
           for x in probs("Clear Rock Tunnel", {"area": "ROUTE_10|0,4"})))
    ck("...and a bare map name is judged by the map, as before",
       any("ALREADY stood in" in x
           for x in probs("Clear Rock Tunnel", {"map": "ROUTE_10"})))

    # the deed rule must still bite where it was written to bite: a place
    # already stood in, and a radius around a tile
    q = probs("Push the boulders in the Seafoam Islands",
              {"player_at": {"x": 3, "y": 14, "radius": 2}})
    ck("a deed ending on standing-near-a-tile is still refused", bool(q), q)
    ck("...saying standing somewhere is not the deed done",
       q and any("not the deed done" in x for x in q), q)

    # ...and a real leftover still passes, as before
    ck("a deed ending on an item is untouched",
       not probs("Retrieve the Gold Teeth", {"has_item": {"GOLD_TEETH": 1}}))
finally:
    A.visited_maps = _real_visited
    A.visited_regions = _real_regions

src = (ROOT / "planner" / "author.py").read_text()
ck("the two rules now agree in one place",
   "_new_place = bool(_pl) and bool(_vm) and not (_pl <= _vm)" in src
   and "if keys and not _new_place and keys <= {" in src)
ck("the sibling rule still promises exactly this",
   "or on a place the run has never reached." in src)
ck("an area is compared against the regions walked",
   "def visited_regions()" in src
   and "_place_names(dw0, exact=True)" in src
   and "_place_names(dw, exact=True)" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:220])
sys.exit(1 if bad else 0)
