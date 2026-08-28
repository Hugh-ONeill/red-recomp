#!/usr/bin/env python3
"""A building the static tables do not know is placed by its name, or by a
door the run has walked through — never by a door it has only looked at.

CINNABAR_LAB is not a gym, a mart, a center or a gate, and CINNABAR_ISLAND
does not end in _CITY, so _doorstep could not place it; "HOW FAR OFF YOU
ARE" told a run that had stood beside the lab's door "nothing you have
walked joins ROUTE_14 to CINNABAR_LAB" (2026-08-28). The first fix read
the engine's warp table (door_dests) and named the door before the run
had gone through it; the ledger hides where an untaken door leads on
purpose (user: "it wouldn't know the lab is the lab until walking inside
though, right?"). A player has the building's NAME, and the doors they
have walked.
"""
from __future__ import annotations
import sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
def graph(g): E._WALKED_REF[0] = types.SimpleNamespace(explored=g)
graph({})
ck("the lab is placed on the island by its name", E._doorstep("CINNABAR_LAB") == "CINNABAR_ISLAND")
ck("...and so is the gym", E._doorstep("CINNABAR_GYM") == "CINNABAR_ISLAND")
ck("a city name still places as before", E._doorstep("CELADON_GYM") == "CELADON_CITY" and E._doorstep("PEWTER_GYM") == "PEWTER_CITY")
ck("a map the town map draws is itself", E._doorstep("ROUTE_20") == "ROUTE_20")
ck("a building whose name carries no place, and no walked door, stays itself",
   E._doorstep("POKEMON_MANSION_1F") == "POKEMON_MANSION_1F")
graph({"CINNABAR_ISLAND|1,0": {"2,3": {"to": "POKEMON_MANSION_1F|1,1", "n": 0}}})
ck("a door only LOOKED at (n=0) places nothing", E._walked_door_into("POKEMON_MANSION_1F") is None
   and E._doorstep("POKEMON_MANSION_1F") == "POKEMON_MANSION_1F")
graph({"CINNABAR_ISLAND|1,0": {"2,3": {"to": "POKEMON_MANSION_1F|1,1", "n": 1}}})
ck("a door walked through places the building", E._doorstep("POKEMON_MANSION_1F") == "CINNABAR_ISLAND"
   and E._walked_door_into("POKEMON_MANSION_1F") == ("CINNABAR_ISLAND", "2,3"))
# stairs run both ways: a floor whose only walked door is from the floor above, and vice versa
graph({"POKEMON_MANSION_1F|1,1": {"5,10": {"to": "POKEMON_MANSION_2F|10,1", "n": 2}},
       "POKEMON_MANSION_2F|10,1": {"5,10": {"to": "POKEMON_MANSION_1F|1,1", "n": 2}}})
ck("two floors that only lead to each other resolve without recursing forever",
   E._doorstep("POKEMON_MANSION_2F") in ("POKEMON_MANSION_2F", "POKEMON_MANSION_1F"))
graph({"CINNABAR_ISLAND|1,0": {"2,3": {"to": "POKEMON_MANSION_1F|1,1", "n": 1}},
       "POKEMON_MANSION_1F|1,1": {"5,10": {"to": "POKEMON_MANSION_2F|10,1", "n": 2}},
       "POKEMON_MANSION_2F|10,1": {"5,10": {"to": "POKEMON_MANSION_1F|1,1", "n": 2}}})
ck("...and a floor reached from a building entered off the street places on the street",
   E._doorstep("POKEMON_MANSION_2F") == "CINNABAR_ISLAND")
ck("a door from the street is preferred over one from another floor",
   E._walked_door_into("POKEMON_MANSION_1F") == ("CINNABAR_ISLAND", "2,3"))
src = (ROOT / "planner/executor.py").read_text()
ck("the executor registers itself as the graph's owner", "_WALKED_REF[0] = self" in src)
d = src[src.index("def _doorstep("):src.index("def _doorstep(") + 1800]
ck("the engine's warp table is not consulted by _doorstep", "_SEEN_DOORS_REF" not in src and "door_dests" not in d)
ck("the distance note says name or walked door, nothing about a door merely seen",
   "going by its name" in src and "and you have walked through it" in src)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
