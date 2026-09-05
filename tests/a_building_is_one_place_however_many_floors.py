#!/usr/bin/env python3
"""A building is one place, however many floors it has.

explore's destination picker breaks ties by locality before distance, and
it measured locality by MAP NAME. A floor is its own map in this game, so
POKEMON_MANSION_1F, _2F, _3F and _B1F are four foreign countries, and only
the single floor whose door had been taken from where you stand counted as
near.

Live, 2026-09-05: working the Pokemon Mansion for a way into Blaine's gym,
the picker rated the third floor no closer than a shop across the street
(user: "the explore thing is weird though it really should prefer routing
it within the same building if at all sensible"). The party was walked out
of the building it was searching, repeatedly, and walked itself back in.

This reads the NAME and nothing else — the floor suffix the game itself
writes — and claims nothing about what is on any floor. Two buildings that
shared a name would share it on the printed map too.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                  # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

for region, want in [
        ("POKEMON_MANSION_1F|1,1", "POKEMON_MANSION"),
        ("POKEMON_MANSION_2F|6,1", "POKEMON_MANSION"),
        ("POKEMON_MANSION_B1F|1,1", "POKEMON_MANSION"),
        ("SEAFOAM_ISLANDS_B3F|1,0", "SEAFOAM_ISLANDS"),
        ("SILPH_CO_11F|5,5", "SILPH_CO"),
        ("SILPH_CO_ELEVATOR|0,0", "SILPH_CO"),
        ("CELADON_MART_ROOF|1,1", "CELADON_MART")]:
    ck(f"{region.split('|')[0]} is {want}", E._building(region) == want)

ck("a route keeps its own name", E._building("ROUTE_20|44,2") == "ROUTE_20")
ck("...and so does a town",
   E._building("CINNABAR_ISLAND|10,0") == "CINNABAR_ISLAND")
ck("a shop is not the house next door",
   E._building("CINNABAR_MART|0,2") != E._building("POKEMON_MANSION_1F|1,1"))

def local(here, region, rooms=()):
    """the picker's _local, as _explore_step computes it"""
    return 0 if (E._building(region) == E._building(here)
                 or region in rooms) else 1

HERE = "POKEMON_MANSION_1F|1,1"
ck("the floor above is near", local(HERE, "POKEMON_MANSION_2F|6,1") == 0)
ck("...and two floors up, which no door from here reaches",
   local(HERE, "POKEMON_MANSION_3F|5,8") == 0)
ck("...and the basement, never stood on",
   local(HERE, "POKEMON_MANSION_B1F|1,1") == 0)
ck("the shop across the street is not",
   local(HERE, "CINNABAR_MART|0,2") == 1)
ck("...and neither is the island it stands on",
   local(HERE, "CINNABAR_ISLAND|10,0") == 1)
ck("...unless its door was taken from here, which is the older rule",
   local(HERE, "CINNABAR_ISLAND|10,0",
         rooms={"CINNABAR_ISLAND|10,0"}) == 0)

src = (ROOT / "planner/executor.py").read_text()
ck("the picker measures locality by building",
   "_here_b, _reg_b = _building(here), _building(region)" in src
   and "_local = 0 if (_reg_b == _here_b or region in _rooms) else 1" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
