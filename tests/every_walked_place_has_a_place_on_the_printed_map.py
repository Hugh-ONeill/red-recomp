#!/usr/bin/env python3
"""A place the printed map cannot position scores LEVEL with every goal.

goalward_tier ranks by hops between doorsteps on the town map the game
hands you.  A map with no doorstep on it returns None hops, which reads as
level -- never away -- so it can win a ranking on sheer count of untouched
things, from anywhere, under any goal.

Under the goal INDIGO_PLATEAU, standing on ROUTE_23 one leg from Victory
Road, explore walked the party 39 legs to the Rocket Hideout lift.  Twice
in one leg (2026-09-11, user: "it ended up 'go'ing to the rocket hideout
again").

Two faults did it.  A walk between two parts of one floor is keyed
"walk:<MAP>|x,y", which carries a comma, so the door test matched it and a
map became its own doorstep.  And a building entered at one part only --
Silph's 9F to 11F, the Safari Zone's quadrants -- had its parts point at
each other for ever.

Both answers come from the run's OWN walked doors, never the ROM's warp
table: it knows where a building stands because it walked in.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                    # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))


class _Ref:
    def __init__(self, explored): self.explored = explored


ATLAS = {
    # entered from the street
    "CELADON_CITY|1,1": {"28,19": {"n": 3, "to": "GAME_CORNER|17,4"}},
    # the lift, reached only from inside
    "GAME_CORNER|17,4": {"21,2": {"n": 1, "to": "ROCKET_HIDEOUT_B1F|10,17"}},
    # an intra-floor walk: NOT a door, though its key carries a comma
    "ROCKET_HIDEOUT_B1F|10,17": {
        "walk:ROCKET_HIDEOUT_B1F|24,17": {"n": 1, "to": "ROCKET_HIDEOUT_B1F|24,17"}},
    # a building entered at one part only: 9F and 10F face each other
    "SAFFRON_CITY|1,1": {"10,4": {"n": 2, "to": "SILPH_CO_1F|1,1"}},
    "SILPH_CO_1F|1,1": {"3,3": {"n": 1, "to": "SILPH_CO_9F|1,1"}},
    "SILPH_CO_9F|1,1": {"5,5": {"n": 1, "to": "SILPH_CO_10F|1,1"}},
    "SILPH_CO_10F|1,1": {"5,5": {"n": 1, "to": "SILPH_CO_9F|1,1"}},
}
E._WALKED_REF[0] = _Ref(ATLAS)

# ---- a walk between parts of one floor is not a door -------------------
ck("an intra-floor walk does not place a map on itself",
   E._doorstep("ROCKET_HIDEOUT_B1F") != "ROCKET_HIDEOUT_B1F",
   E._doorstep("ROCKET_HIDEOUT_B1F"))
ck("...it follows the real doors out to the street",
   E._doorstep("ROCKET_HIDEOUT_B1F") == "CELADON_CITY",
   E._doorstep("ROCKET_HIDEOUT_B1F"))

# ---- a building is placed by whichever part opens outside ---------------
ck("a floor whose doors all face siblings is still placed",
   E._doorstep("SILPH_CO_10F") == "SAFFRON_CITY", E._doorstep("SILPH_CO_10F"))
ck("...and so is the sibling facing it back",
   E._doorstep("SILPH_CO_9F") == "SAFFRON_CITY", E._doorstep("SILPH_CO_9F"))
ck("...through the part that does open on the street",
   E._doorstep("SILPH_CO_1F") == "SAFFRON_CITY")

# ---- and the ranking can now see them -----------------------------------
import ledger as L                                      # noqa: E402
ck("the hideout now reads AWAY from the Plateau, not level",
   L.goalward_tier(E, "ROCKET_HIDEOUT_B1F|10,17", "ROUTE_23|10,104",
                   "map:INDIGO_PLATEAU") == 2)
ck("...where before it read level and could win on count",
   E.static_hops(E._doorstep("ROCKET_HIDEOUT_B1F"),
                 E._doorstep("INDIGO_PLATEAU")) is not None)

# ---- nothing invented for a place never walked into ---------------------
ck("a map with no walked door into it places nowhere, rather than guessing",
   E._doorstep("WARDENS_HOUSE") == "WARDENS_HOUSE")
ck("a map the printed map already draws is left alone",
   E._doorstep("ROUTE_23") == "ROUTE_23"
   and E._doorstep("CELADON_CITY") == "CELADON_CITY")

# ---- the source says where it will and will not look --------------------
SRC = (ROOT / "planner" / "executor.py").read_text()
ck("intra-floor and lift keys are skipped by name",
   'str(k).startswith(("walk:", "lift:"))' in SRC)
ck("a door from a map to itself places nothing",
   "if hit[0] == map_id:" in SRC and "a door from itself places nothing" in SRC)
ck("the sibling rule reads the run's atlas, not the ROM",
   '_graph = getattr(_WALKED_REF[0], "explored", None) or {}' in SRC
   and "warps" not in SRC.split("A BUILDING IS PLACED BY", 1)[1][:1600])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d)[:90] + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
