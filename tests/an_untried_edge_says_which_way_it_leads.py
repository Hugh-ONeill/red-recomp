#!/usr/bin/env python3
"""An untried edge is offered without saying which way the map says it goes.

The goalward note -- read off the printed map the game hands you -- is
attached to AREAS: "GAME_CORNER ... AWAY from INDIGO_PLATEAU on the
printed map".  It was never attached to the EXIT being offered inside one.

So on ROUTE_23, under the goal INDIGO_PLATEAU, item 1 read "explore walks
there to take the south edge (never taken)".  South is ROUTE_22, the way
it came in, and the printed map says so.  The run walked back down the
route it had to climb (2026-09-11, user: "its backtracking because its
allready been through here").

Same source and same words as the area note.  The printed map says which
way an edge leads and nothing about what is there or whether the road is
open.  Whether to take it stays the model's.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L                                      # noqa: E402
import executor as E                                    # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

# the real printed-map table: ROUTE_23 runs north to the Plateau, south to 22
ck("the printed map joins ROUTE_23 to both",
   (E.MAP_EDGES.get("ROUTE_23") or {}) ==
   {"north": "INDIGO_PLATEAU", "south": "ROUTE_22"},
   E.MAP_EDGES.get("ROUTE_23"))

# the tier reader is what the area note already uses
class _Ex:
    def __init__(self): self.explored = {}
ex = _Ex()
ex.__class__.__module__ = "executor"

away = L.goalward_tier(ex, "ROUTE_22", "ROUTE_23", "map:INDIGO_PLATEAU")
toward = L.goalward_tier(ex, "INDIGO_PLATEAU", "ROUTE_23", "map:INDIGO_PLATEAU")
ck("south of ROUTE_23 reads as away from the Plateau", away == 2, away)
ck("north reads as toward it", toward == 0, toward)
ck("...and without a map goal nothing is claimed",
   L.goalward_tier(ex, "ROUTE_22", "ROUTE_23", "item:POTION") == 1)

ck("the words for away name the goal and the source",
   L.goalward_words(2, "map:INDIGO_PLATEAU", short=True)
   == ", AWAY from INDIGO_PLATEAU on the printed map")
ck("...and level-with-it says nothing at all",
   L.goalward_words(1, "map:INDIGO_PLATEAU", short=True) == "")

# and the edge phrasing now asks
SRC = (ROOT / "planner" / "ledger.py").read_text()
blk = SRC.split("WHICH WAY THE PRINTED MAP SAYS THAT EDGE GOES", 1)[1][:2600]
ck("an edge is scored by where the printed map sends it",
   "edge_tier(ex, region, k, target)" in blk)
ck("...and annotated with the same short words as an area",
   "goalward_words(" in blk and "short=True" in blk)
ck("a door is left alone — only seams have a printed direction",
   'return f"door ({k})"' in blk)
ck("the edge is still named as an edge", 'f"the {k} edge"' in blk)
_reader = SRC.split("def edge_tier(", 1)[1][:1600]
ck("the executor module is reached through the object, not by name",
   "type(ex).__module__" in _reader)
ck("...and a missing table returns level, not an exception",
   "except Exception:" in _reader and "return 1" in _reader)

# ---- and the RANKING stops treating an away-edge as business -----------
ck("the edge reader is shared by the words and the ranking",
   SRC.count("def edge_tier(") == 1
   and SRC.count("edge_tier(ex, region, k, target)") >= 2)
_rank = SRC.split("AN UNTRIED EXIT THAT LEADS AWAY IS NOT A REASON", 1)[1][:1400]
ck("away-edges are dropped from what makes an area worth walking to",
   "_fwd = [k for k in left if edge_tier(ex, region, k, target) != 2]" in _rank)
ck("...from the has-something flag", "0 if (_fwd or things or unseen or _unr) else 1" in _rank)
ck("...and from the count that breaks ties",
   "-(len(_fwd) + len(things) + unseen + len(_unr))" in _rank)
ck("the area's own goalward tier still leads the key",
   "_pri, _local, _goal, len(path)," in _rank)
ck("away-edges are still LISTED, not hidden",
   'what.append("take " + " or ".join(_word(k)' in SRC
   and "for k in sorted(left)[:3]" in SRC)

# a door still counts as business: it has no printed direction
ck("a door is never dropped from the ranking",
   L.edge_tier(ex, "ROUTE_23|4,31", "8,17", "map:INDIGO_PLATEAU") == 1)
ck("...nor is an edge toward the goal",
   L.edge_tier(ex, "ROUTE_23|4,31", "north", "map:INDIGO_PLATEAU") == 0)
ck("...and a south edge under that goal is the one that is dropped",
   L.edge_tier(ex, "ROUTE_23|4,31", "south", "map:INDIGO_PLATEAU") == 2)
ck("with no map goal every edge counts",
   L.edge_tier(ex, "ROUTE_23|4,31", "south", "item:POTION") == 1)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d)[:90] + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
