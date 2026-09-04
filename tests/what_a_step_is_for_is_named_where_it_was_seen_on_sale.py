#!/usr/bin/env python3
"""What a step is for is named where the run has seen it on sale (2026-09-04).

The step was "Buy Fresh Water" (has_item FRESH_WATER). The shops line further
down the same page opened with "CELADON_MART_ROOF (VENDING MACHINES, pressed
and picked from, not bought at), 2 walked leg(s) away: FRESH_WATER, SODA_POP,
LEMONADE" — and the run rode the lift to 3F to search the TV Game Shop (user:
"so it literally has the information that fresh water comes from the vending
machines on the roof"). Two facts the harness held on one page and never put
side by side. Now a line at the top of the carried/shops section names the
step's item, the shelf the run read it on, the walk and the op. It is silent
when the bag already holds it, when no read shelf lists it, and about whether
it is worth the money. And "not bought at" is gone: a machine is pressed and a
row picked.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

def fresh():
    e = object.__new__(E.Executor)
    e._shelves = {"CELADON_MART_ROOF": ["FRESH_WATER", "SODA_POP", "LEMONADE"],
                  "CERULEAN_MART": ["POKE_BALL", "POTION", "REPEL"]}
    e._shelf_machine = {"CELADON_MART_ROOF"}
    e._shelf_reads = {"CELADON_MART_ROOF": {"n": 3, "moved": False}, "CERULEAN_MART": {"n": 12, "moved": False}}
    e.explored = {"CELADON_MART_ROOF|2,1": {}, "CERULEAN_MART|0,2": {}, "CELADON_MART_5F|1,1": {}}
    e._where = lambda o: "CELADON_MART_5F|1,1"
    e._route = lambda a, b: (["x", "y"] if b.startswith("CELADON_MART_ROOF") else None)
    e.log = lambda *a, **k: None
    return e

sg = {"id": "buy_fresh_water", "done_when": {"has_item": {"FRESH_WATER": 1}}}
obs = {"map": {"id": "CELADON_MART_5F"}, "bag": {"POTION": 4}}
e = fresh()
w = e._goal_on_a_shelf_words(sg, obs)
ck("the step's item is named with the shelf it was read on", "FRESH_WATER: CELADON_MART_ROOF" in w, w)
ck("...a machine says how a row is picked", '{"op":"menu","index":N} picks the row' in w, w)
ck("...how often it was read and how far it is", "read 3x" in w and "2 walked leg(s) away" in w, w)
ck("...and the walk, as an op", '{"op":"go","to":"CELADON_MART_ROOF"}' in w, w)
ck("...without claiming it is the only place or worth it", "Nothing here says it is the only place" in w, w)
ck("a shelf that does not list it is not named", "CERULEAN_MART" not in w, w)
ck("held already = silent", e._goal_on_a_shelf_words(sg, {"bag": {"FRESH_WATER": 1}}) == "")
ck("no has_item = silent", e._goal_on_a_shelf_words({"done_when": {"map": "X"}}, obs) == "")
ck("never seen on sale = silent", e._goal_on_a_shelf_words({"done_when": {"has_item": {"POKE_FLUTE": 1}}}, obs) == "")
w2 = e._goal_on_a_shelf_words({"done_when": {"has_item": {"POTION": 9}}}, obs)
ck("a counter says the buy op with the item", 'a counter — {"op":"buy","item":"POTION","count":1}' in w2, w2)
ck("...and a shelf with no walked route says so, without a go", "no walked route from here" in w2 and '"op":"go"' not in w2, w2)
e3 = object.__new__(E.Executor)
ck("an executor from before the shelf store does not die of it", e3._goal_on_a_shelf_words(sg, obs) == "")

src = (ROOT / "planner" / "executor.py").read_text()
ck("the line rides the top of the carried/shops section",
   "_rs_line = (self._building_directory_words(obs)\n                        + self._goal_on_a_shelf_words(sg, obs) + _rs_line)" in src)
ck("'not bought at' is gone from the shops line", '"not bought at)" if _sm in _mach' not in src)
ck("...a machine on the shops line says how a row is picked",
   'VENDING MACHINES — no clerk: press one, then "\n                           "{\\"op\\":\\"menu\\",\\"index\\":N} picks the row' in src)

bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:400]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
