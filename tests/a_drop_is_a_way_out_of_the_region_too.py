#!/usr/bin/env python3
"""The frontier is the other half of "a drop is a way out".

Drops became rows on the page you see while standing on the floor.  Every
REMOTE ranking asks a different thing: self.frontier, which lists the ways
out of a region, and which is built from the warp table.  A hole is in no
warp table.

So POKEMON_MANSION_3F|1,1 held ['25,14', '6,1'], both already taken, with
three drop cells on that floor and none of them in the list.  From
anywhere else the floor read as having nothing left, the whole building
read as near finished, and explore walked the run out to Route 20, which
did have untried ground (user, 2026-09-10: "it tries to explore but that
shunts it out to rt20 because the mansion is near fully worked until you
get to the basement").

One drop, one key, at its first tile: the same key the ledger's row
carries, so what the ranking counts and what the page offers are the same
thing.  Synthetic: no game.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

HERE = "POKEMON_MANSION_3F|1,1"


def note(holes, warps=None, taken=()):
    ex = E.Executor.__new__(E.Executor)
    ex.frontier, ex.unreached_at, ex.shut_doors = {}, {}, {}
    ex.explored, ex.visits = {}, {}
    for _a in ("map_doors", "map_seen", "map_holes", "door_dests",
               "seen_far", "sightings", "_tried_objs", "_cut_bushes"):
        setattr(ex, _a, {})
    ex._where = lambda o: HERE
    ex._sealed = lambda h: set()
    ex._taken_here = lambda h: {k: {} for k in taken}
    ex._unopened_doors = lambda o: []
    ex._rebuild_area_aliases = lambda: None
    ex._save_memory = lambda: None
    obs = {"map": {"id": "POKEMON_MANSION_3F", "region": "1,1",
                   "connections": {},
                   "warps": warps if warps is not None
                   else [{"x": 6, "y": 1, "reachable": True},
                         {"x": 25, "y": 14, "reachable": True}],
                   "holes": holes}}
    ex.note_frontier(obs)
    return ex


def hole(x, y, grp, reach):
    return {"x": x, "y": y, "drop": grp, "reachable": reach}


HOLES = [hole(16, 14, 1, True), hole(17, 14, 1, True),
         hole(19, 14, 2, True)]

ex = note(HOLES)
fr = ex.frontier.get(HERE) or []

ck("the doorways are still ways out", "6,1" in fr and "25,14" in fr)
ck("...and so are the drops", "16,14" in fr and "19,14" in fr, fr)
ck("one drop is ONE way out, not one per tile",
   "17,14" not in fr and len(fr) == 4, fr)

# ---- a drop no walk reaches goes where an unreachable doorway goes ------
ex2 = note([hole(16, 14, 1, False), hole(17, 14, 1, False),
            hole(19, 14, 2, True)])
fr2 = ex2.frontier.get(HERE) or []
ck("an unreachable drop stays out of the frontier", "16,14" not in fr2, fr2)
ck("...and is remembered as a way out no walk reaches",
   "16,14" in (ex2.unreached_at.get(HERE) or []), ex2.unreached_at)
ck("...while the reachable one is still a way out", "19,14" in fr2)

# ---- taken drops are not un-listed; the "left" test subtracts them ------
ex3 = note(HOLES, taken=("16,14",))
ck("a drop already taken stays a way out of the region",
   "16,14" in (ex3.frontier.get(HERE) or []))
ck("...and is not counted as one no walk reaches",
   "16,14" not in (ex3.unreached_at.get(HERE) or []))

# ---- a floor with no holes is untouched by any of this -----------------
ex4 = note([])
ck("no holes, no change", sorted(ex4.frontier.get(HERE) or []) == ["25,14", "6,1"])
ck("...and nothing recorded as unreached", not ex4.unreached_at)

# ---- and the frontier still never shrinks ------------------------------
ex5 = note(HOLES)
ex5.frontier[HERE] = sorted(set(ex5.frontier[HERE]) | {"99,99"})
ex5.note_frontier({"map": {"id": "POKEMON_MANSION_3F", "region": "1,1",
                       "connections": {}, "warps": [], "holes": []}})
ck("a way out seen once is never unseen",
   "99,99" in ex5.frontier[HERE] and "16,14" in ex5.frontier[HERE])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d) + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
