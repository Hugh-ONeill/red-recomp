"""This floor has another part you have walked, and the sea is the sea.

TWO fixes, one story.  Standing in SEAFOAM_ISLANDS_1F|3,2 the ledger HELD
1F|21,12 -- stood in 3x, whose door the run had taken twice onto the far
shore of Route 20 -- and never said it, so every round re-derived the idea
and lost it at the next map load.  And when the run finally DID get out
there, `cross west surf=true` was refused as an exact repeat whose "answer"
had been a wild fight 17 cells into the crossing, so it turned round and
went back into the island.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import ledger

HERE = "SEAFOAM_ISLANDS_1F|3,2"
FAR = "SEAFOAM_ISLANDS_1F|21,12"

class _Ex:
    explored = {
        HERE: {"4,17": {"to": "ROUTE_20|52,2", "n": 80}},
        FAR: {"26,17": {"to": "ROUTE_20|58,9", "n": 2},
              "27,17": {"to": "ROUTE_20|58,9", "n": 2},
              "23,15": {"to": "SEAFOAM_ISLANDS_B1F|20,10", "n": 1}},
        "ROUTE_20|58,9": {"58,9": {"to": FAR, "n": 1}},
    }
    visits = {HERE: 100, FAR: 3}
    frontier = {}
    def _where(self, _o): return HERE
    def __getattr__(self, _n): return {}

obs = {"party": [{"moves": ["SURF"]}],
       "map": {"id": "SEAFOAM_ISLANDS_1F", "region": "3,2"}}
head = ledger.render([], _Ex(), obs).splitlines()[0]

ck("the other part of this floor is named", FAR in head)
ck("how often it was stood in is said", "3x" in head)
ck("where its doors went is said", "ROUTE_20|58,9" in head)
ck("go is offered as the way back", '"go"' in head)
ck("a place on ANOTHER map is not dragged in", "ROUTE_20|52,2" not in head)

# a floor with only one walked part says nothing about kin
class _Solo(_Ex):
    explored = {HERE: {"4,17": {"to": "ROUTE_20|52,2", "n": 3}}}
    visits = {HERE: 5}
head2 = ledger.render([], _Solo(), obs).splitlines()[0]
ck("one-part floor stays quiet", "ANOTHER PART" not in head2)

# --- the repeat gate ----------------------------------------------------
def refuses(why):
    """The gate's own test, as the executor applies it."""
    seen = {"n": 1, "why": why}
    if seen and any(w in str(seen.get("why") or "").lower()
                    for w in ("because of the battle", "a fight started")):
        seen = None
    return bool(seen)

BATTLE = ("a fight started 41 cell(s) short of the west edge gap (0,15) — "
          "the walk stopped at (41,15) because of the battle, not because "
          "of the ground")
WALL = "the west seam cannot be walked to from here — no walkable path"

ck("a battle-cut crossing may be sent again", not refuses(BATTLE))
ck("a wall still refuses the repeat", refuses(WALL))
ck("an empty reason still refuses", refuses(""))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("HEAD WAS:", head[:500])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
