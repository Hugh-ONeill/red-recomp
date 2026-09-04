#!/usr/bin/env python3
"""A counter you have read is answered in your own word.

At the Route 7 gate, told "Gee, I'm thirsty", the model wrote "I need FRESH
WATER. I will travel back to the nearest mart (Cerulean Mart) to purchase it"
and spent a 17-leg go on a shelf the same page listed, at 15% depth, as "read
12x, the same list every time" (2026-09-04). The author's shelf rule refuses a
PLAN that ends on such a buy; the walker was never told, in the word it had
used, that the counter it was walking to does not have the thing.

Now the round that puts the party at a read counter says: "You said
FRESH_WATER, and the counter here has never listed it in 12 reading(s) — it
sells POKE_BALL, ... Nothing here says where it IS sold; only that it is not
sold here." Sibling of words-are-not-ops. Synthetic: no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
e = object.__new__(E.Executor)
e._shelves = {"CERULEAN_MART": ["POKE_BALL", "POTION", "REPEL", "ANTIDOTE"]}
e._shelf_reads = {"CERULEAN_MART": {"n": 12, "moved": False}}
E._ITEM_IDS |= {"FRESH_WATER", "POKE_BALL", "POTION", "REPEL", "ANTIDOTE"}
at_mart = {"map": {"id": "CERULEAN_MART"}}
PLAN = ("The guard is thirsty. I need to provide him with FRESH WATER. I will travel "
        "back to the nearest mart (Cerulean Mart) to purchase it.")
note = e._shelf_note(PLAN, at_mart)
ck("an item named in the prose that the read shelf lacks is answered",
   "You said FRESH_WATER" in note and "never listed it in 12 reading(s)" in note, note)
ck("...with the shelf itself", "it sells POKE_BALL, POTION, REPEL, ANTIDOTE" in note)
ck("...and without saying where it is sold", "Nothing here says where it IS sold" in note)
ck("an item the shelf HAS draws no note", e._shelf_note("I will buy a POTION here.", at_mart) == "")
ck("a counter never read draws no note",
   e._shelf_note(PLAN, {"map": {"id": "VERMILION_MART"}}) == "")
ck("outside any shop, nothing", e._shelf_note(PLAN, {"map": {"id": "ROUTE_7"}}) == "")
ck("prose naming no item, nothing", e._shelf_note("I will walk south.", at_mart) == "")
src = (ROOT / "planner" / "executor.py").read_text()
ck("wired into the round's feedback beside the deed note",
   "_shelf = self._shelf_note(self._plan_said, self.settle() or obs)" in src)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
