"""An explore walk under a map goal prefers ground toward the goal, and
says when the ground it chose lies away from it.

Run 15's journal (autopsy, 2026-09-06): under a map goal the remote
explore picker ranked walked areas by distance from HERE, and the walk went
AWAY from the goal on the printed map 66 times and toward it once -- Route
4 to Pewter's museum under CERULEAN_CITY 47 times, Route 10 to Route 9
under LAVENDER_TOWN, Route 23 to Route 22 under INDIGO_PLATEAU, Route 20 to
Route 15 under CINNABAR_ISLAND.  Each time the model read "now at
PEWTER_CITY", wrote "I need to go back east", and walked back -- its
judgment right every time, and nothing on the page said the walk had gone
the wrong way on a map any player holds in their hand.

The printed map is manual tier.  It says nothing about what an area holds
or whether a road is open -- only which way, along the roads the box
lists, an area lies from the place the goal names.  So: toward before away,
distance still deciding among areas level with the goal, the area you are
in still first -- and the words say which way the walk went.
"""
import sys
from pathlib import Path
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

import executor as E
import ledger as L


class Fake:
    """An executor-shaped nothing: the helper must find the printed map
    through the executor MODULE, not through this object."""


# the four away-walks the autopsy counted, each read as AWAY
for here, there, goal in [
        ("ROUTE_4|3,5", "PEWTER_CITY|10,10", "map:CERULEAN_CITY"),
        ("ROUTE_10|3,5", "ROUTE_9|0,8", "map:LAVENDER_TOWN"),
        ("ROUTE_23|4,31", "ROUTE_22|1,1", "map:INDIGO_PLATEAU"),
        ("ROUTE_20|52,2", "ROUTE_15|1,1", "map:CINNABAR_ISLAND")]:
    ck(f"{here.split('|')[0]} -> {there.split('|')[0]} under {goal} is AWAY",
       L.goalward_tier(Fake(), there, here, goal) == 2)

# the mountain off Route 4 is level with it: same doorstep, same distance
ck("Mt Moon from Route 4 under CERULEAN is level, not away",
   L.goalward_tier(Fake(), "MT_MOON_1F|3,5", "ROUTE_4|3,5",
                   "map:CERULEAN_CITY") == 1)
ck("Route 4 from Pewter under CERULEAN is toward",
   L.goalward_tier(Fake(), "ROUTE_4|3,5", "PEWTER_CITY|1,1",
                   "map:CERULEAN_CITY") == 0)
ck("a badge goal has no direction on the printed map",
   L.goalward_tier(Fake(), "PEWTER_CITY|1,1", "ROUTE_4|3,5",
                   "badge:CASCADE") == 1)
ck("a map the printed map does not know is level, not a guess",
   L.goalward_tier(Fake(), "NOWHERE|1,1", "ROUTE_4|3,5",
                   "map:CERULEAN_CITY") == 1)

# a place's gates sit where the place does: the forest's north gate is off
# Route 2, not in Viridian City (it read as the city, two legs from Pewter,
# and explore walked back to the city instead of on to the gate, run 16)
ck("the forest's gates stand on Route 2",
   E._doorstep("VIRIDIAN_FOREST_NORTH_GATE") == "ROUTE_2"
   and E._doorstep("VIRIDIAN_FOREST_SOUTH_GATE") == "ROUTE_2")
ck("...so from Route 2 under PEWTER the gate is level and the city is away",
   L.goalward_tier(Fake(), "VIRIDIAN_FOREST_NORTH_GATE|5,0", "ROUTE_2|3,43",
                   "map:PEWTER_CITY") == 1
   and L.goalward_tier(Fake(), "VIRIDIAN_CITY|17,0", "ROUTE_2|3,43",
                       "map:PEWTER_CITY") == 2)

# the words
ck("away is said as away, naming the goal",
   "AWAY from CERULEAN_CITY" in L.goalward_words(2, "map:CERULEAN_CITY"))
ck("toward is said as toward",
   "toward CERULEAN_CITY" in L.goalward_words(0, "map:CERULEAN_CITY"))
ck("level says nothing", L.goalward_words(1, "map:CERULEAN_CITY") == "")
ck("no map goal, nothing said", L.goalward_words(2, "badge:CASCADE") == "")

# the deed and the page rank by it, in the same place in both tuples
src_e = Path("planner/executor.py").read_text()
src_l = Path("planner/ledger.py").read_text()
ck("the executor's remote picker ranks by it after the area you are in",
   "r = (_pri, _stale, _local, _goal, len(path), _way_here," in src_e
   and "_goal = ledger.goalward_tier(self, region, here, target)" in src_e)
ck("the page's ranking carries the same term after the same one",
   "r = (_pri, _local, _goal, len(path), 0 if (left or _unr) else 1," in src_l
   and "_goal = goalward_tier(ex, region, here, target)" in src_l)
ck("the explore trace says which way the walk went",
   "+ ledger.goalward_words(_goalward, target)" in src_e)
ck("the journal keeps it for the meter", "goalward=_goalward" in src_e)
ck("the page's nearest-area line says it too",
   "goalward_words(goalward_tier(ex, region, here, target)," in src_l)
ck("...and so does each other area it lists",
   "goalward_words(goalward_tier(ex, _reg2, here," in src_l)

# the ranking itself, on the tuple the deed builds: an away area two legs
# off loses to a level one four legs off, and a toward one wins outright
def tup(goal, legs):
    return (0, 0, 1, goal, legs, 0, -3, "x")
ck("level at 4 legs outranks away at 2",
   tup(1, 4) < tup(2, 2))
ck("toward at 5 legs outranks level at 1",
   tup(0, 5) < tup(1, 1))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
