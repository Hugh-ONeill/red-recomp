#!/usr/bin/env python3
"""A building the static tables do not know is placed by a door the run
has seen, so the distance note can say how far it is.

CINNABAR_LAB is not a gym, a mart, a center or a gate, and CINNABAR_ISLAND
does not end in _CITY, so _doorstep could not place it; the walked-links
distance came back None and "HOW FAR OFF YOU ARE" told a run that had
stood beside the lab's door "nothing you have walked joins ROUTE_14 to
CINNABAR_LAB" (2026-08-28, user: "running around east kanto looking for
cinnabar which it's already been to"). The run's own door_dests held
CINNABAR_ISLAND (6,9) -> CINNABAR_LAB the whole time.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
E._SEEN_DOORS_REF[0] = {}
ck("without a seen door the lab resolves to nothing better than itself", E._doorstep("CINNABAR_LAB") == "CINNABAR_LAB")
E._SEEN_DOORS_REF[0] = {"CINNABAR_ISLAND": {"6,9": "CINNABAR_LAB", "11,11": "CINNABAR_POKECENTER"}}
ck("a door seen on the island places the lab on the island", E._doorstep("CINNABAR_LAB") == "CINNABAR_ISLAND")
ck("the static rules still come first", E._doorstep("CELADON_GYM") == "CELADON_CITY")
ck("...and a gym on an island or in a town is placed by its name too",
   E._doorstep("CINNABAR_GYM") == "CINNABAR_ISLAND" and E._doorstep("PEWTER_GYM") == "PEWTER_CITY")
ck("a map the town map draws is itself", E._doorstep("ROUTE_20") == "ROUTE_20")
E._SEEN_DOORS_REF[0] = {"CINNABAR_LAB": {"2,7": "CINNABAR_LAB_TRADE_ROOM"}, "CINNABAR_ISLAND": {"6,9": "CINNABAR_LAB"}}
ck("a room inside a building climbs out through the building to the island", E._doorstep("CINNABAR_LAB_TRADE_ROOM") == "CINNABAR_ISLAND")
src = (ROOT / "planner/executor.py").read_text()
ck("the executor points the reference at its door_dests on init and on load", src.count("_SEEN_DOORS_REF[0] = self.door_dests") == 2)
ck("the distance note keeps the target's own name and names the door",
   'f"{d} leg(s) from {want_raw}{_door_of}' in src and "stands on {want_map}, " in src)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
