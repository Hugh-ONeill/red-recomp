#!/usr/bin/env python3
"""Explore finishes the area it is in — this map, and the rooms whose doors
it took from here — before walking to another map.

Cerulean, 2026-08-29 (user: "its entered all the houses but not fully
explored all the houses"; "so the trashed house was simply entered for a
second and then not looked at further since it couldnt see the exit from
the start"; "we really want the bot to search the whole area its in before
moving on so this crap doesnt keep happening"). CERULEAN_TRASHED_HOUSE
stood at visits 2, unseen 8, with the city's only way south behind those
eight spots, while the picker walked the party back to Route 4's untried
seam one leg the other way — the city's own ground on foot being finished,
and a room off it not counting as "here".
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import candidates as C, untried as U, ledger as L   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
HOUSE, AWAY = "TRASHED_HOUSE|3,0", "ROUTE_4|63,10"
ex = C.make(explored={U.HERE: {"27,11": {"to": HOUSE, "n": 2},
                               "west": {"to": AWAY, "n": 14}},
                      HOUSE: {"2,7": {"to": U.HERE, "n": 2}},
                      AWAY: {"east": {"to": U.HERE, "n": 14}}},
            frontier={U.HERE: [], HOUSE: [], AWAY: ["south"]})
ex.region_seen = {HOUSE: 8, AWAY: 5}; ex.sightings = {}
ex.visits = {U.HERE: 42, HOUSE: 2, AWAY: 15}
o = C.obs(ex, [])
words = L.plan_explore(ex, o, L.build(ex, o, target="map:VERMILION_CITY", want_explore=False),
                       target="map:VERMILION_CITY")
ck("the room off this area is chosen over an untried seam one leg the other way",
   f"never tried is {HOUSE}" in words, words[:200])
src = (ROOT / "planner" / "executor.py").read_text()
ck("the deed ranks locality above distance, and a room means a DOOR not a seam",
   "_local = 0 if (region.split(\"|\")[0] == here.split(\"|\")[0]" in src
   and 'if str(k)[:1].isdigit() and (e or {}).get("to")}' in src
   and "r = (_pri, _stale, _local, len(path), _way_here," in src)
ck("...and the trace says why it went there",
   "a room off the area you are in, its door taken from " in src)
lsrc = (ROOT / "planner" / "ledger.py").read_text()
ck("the words carry the same order", "r = (_pri, _local, len(path), 0 if (left or _unr) else 1," in lsrc)
# and a far map still wins when nothing local is left
ex.region_seen = {AWAY: 5}
w2 = L.plan_explore(ex, o, L.build(ex, o, target="map:VERMILION_CITY", want_explore=False),
                    target="map:VERMILION_CITY")
ck("with nothing left in this area, a remote one is still chosen", f"never tried is {AWAY}" in w2)
# the door row itself says the room behind it is half unlooked-at
_o2 = C.obs(ex, ["27,11"], dests={"27,11": "TRASHED"})
ex.region_seen = {HOUSE: 8}
_c = {c.key: c for c in L.build(ex, _o2, target="map:VERMILION_CITY")}
ck("a door already taken says the ground never on screen behind it",
   "8 spot(s) of ground in there never on screen" in (_c.get("27,11").beyond or ""),
   (_c.get("27,11").beyond or ""))
bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
