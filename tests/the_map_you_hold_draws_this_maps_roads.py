#!/usr/bin/env python3
"""The map you hold draws this map's roads, whether or not you have looked that way.

On Route 7 the head read "no edge of this map has been on screen yet (north,
west, east never looked at)"; the model went for the gate east, was told the
guard was thirsty, and wrote "the way to Celadon City is blocked by a thirsty
guard" — with Celadon one seam WEST, drawn on the TOWN MAP in its bag and never
mentioned for the map it stood on (2026-09-04). The footprint lists a seam
only once its side has been on screen, which is right for ground; the printed
map is a held item and its layout is the holder's to read. Which roads are
OPEN stays what walking finds.

Synthetic: no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L                                     # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
EDGES = {"ROUTE_7": {"east": "SAFFRON_CITY", "west": "CELADON_CITY"},
         "ROUTE_8": {"west": "SAFFRON_CITY", "east": "LAVENDER_TOWN"}}
w = L.printed_roads_words("ROUTE_7", [], ["north", "west", "east"], EDGES)
ck("every road the map draws is named, with its side",
   "east -> SAFFRON_CITY" in w and "west -> CELADON_CITY" in w, w)
ck("a side never on screen says so", "west -> CELADON_CITY (that side never on screen)" in w, w)
w2 = L.printed_roads_words("ROUTE_7", ["east"], ["west"], EDGES)
ck("a seen side says seen", "east -> SAFFRON_CITY (seen)" in w2 and "west -> CELADON_CITY (that side never on screen)" in w2, w2)
ck("the layout caveat rides along", "draws the LAYOUT, not which roads are open" in w)
ck("no road on the map, no words", L.printed_roads_words("OAKS_LAB", [], [], EDGES) == "")
ck("it never says which way to go", not any(t in w.lower() for t in ("go west", "head", "take the", "you should")))
src = (ROOT / "planner" / "ledger.py").read_text()
ck("the head line carries it only while the map is held",
   "ex._holding_town_map(obs)" in src and "printed_roads_words(m.get(\"id\"), sides, _unseen_sides," in src)
ck("...finding MAP_EDGES through the executor object, not by module name (it runs as __main__)",
   "_sys.modules.get(type(ex).__module__)" in src and '_sys.modules.get("executor")' not in src)
# end to end on a bare executor: the head line renders the roads
import executor as E
ex = object.__new__(E.Executor); ex.visits = {"ROUTE_7|0,2": 1}
E.MAP_EDGES.setdefault("ROUTE_7", {"east": "SAFFRON_CITY", "west": "CELADON_CITY"})
obs = {"bag": {"TOWN_MAP": 1}, "map": {"id": "ROUTE_7", "region": "0,2", "connections": {},
       "sides_unseen": ["north", "west", "east"], "seen_unreached": {}}, "mode": "overworld"}
try:
    out = L.render([], ex, obs, "map:SAFFRON_CITY")
except Exception as exc:
    out = f"render raised {exc!r}"
ck("...and renders in a real head line", "The printed map you hold draws this map's roads" in out
   and "west -> CELADON_CITY (that side never on screen)" in out, out[:300])
bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
