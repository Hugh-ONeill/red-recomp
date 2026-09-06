#!/usr/bin/env python3
"""A key item is not stuck in the bag: the PC takes it.

2026-09-05, Cinnabar. The bag stood at 18 of 20 kinds and twelve of them
were key items or HMs — BICYCLE, CARD_KEY, GOOD_ROD, HM_CUT, HM_STRENGTH,
HM_SURF, LIFT_KEY, OLD_ROD, POKE_FLUTE, SILPH_SCOPE, S_S_TICKET, TOWN_MAP.
The bag line ended "What may go at all (key items can be neither sold nor
tossed):" and listed the other six. So the run was carrying a six-slot bag
and, to make room, tossed TMs and then three RARE_CANDYs on a leg judged on
party levels; it stored a key item exactly never (user: "how can we handle
its key-item holding habit?").

"Neither sold nor tossed" is true, and the sentence it sat in was false:
the Pokemon Center's PC takes key items and HMs (PlayerPC.lua's DEPOSIT
ITEM list leaves out badges and nothing else; IsKeyItem only skips the
how-many prompt), the shim's store_item already drives that list, and the
op doc's own example is HM_CUT. What was missing was the one true sentence.

Now both bag lines say it, the op doc says it, and nothing says WHICH key
item to store — whether the S.S. Ticket still has a use ahead is the
model's to know.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                              # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

BAG = {"BICYCLE": 1, "CARD_KEY": 1, "ESCAPE_ROPE": 4, "FULL_RESTORE": 1,
       "GOOD_ROD": 1, "HM_CUT": 1, "HM_STRENGTH": 1, "HM_SURF": 1,
       "LIFT_KEY": 1, "MASTER_BALL": 1, "MAX_POTION": 1, "MOON_STONE": 2,
       "OLD_ROD": 1, "POKE_BALL": 16, "POKE_FLUTE": 1, "SILPH_SCOPE": 1,
       "S_S_TICKET": 1, "TOWN_MAP": 1, "TM_BLIZZARD": 1, "RARE_CANDY": 3}
KEYS = ["BICYCLE", "CARD_KEY", "GOOD_ROD", "HM_CUT", "HM_STRENGTH", "HM_SURF",
        "LIFT_KEY", "OLD_ROD", "POKE_FLUTE", "SILPH_SCOPE", "S_S_TICKET",
        "TOWN_MAP"]

def bare():
    ex = object.__new__(E.Executor)
    ex.plan = {"subgoals": []}
    ex.visits = {"CINNABAR_POKECENTER|0,3": 1}
    ex.explored = {}
    ex._route = lambda a, b: [1]
    return ex

obs = {"bag": BAG, "key_items": KEYS,
       "map": {"id": "POKEMON_MANSION_B1F", "region": "0,0", "objects": []}}
t = bare()._bag_line(obs, {"id": "t", "done_when": {"map": "X"}})

ck("the full bag speaks", bool(t))
ck("the false sentence is gone",
   "can be neither sold nor tossed" not in t and "What may go at all" not in t)
how = t.split("WHAT MAY GO, AND HOW.")[1]
free, pc = how.split("KEY ITEMS AND HMs")
ck("what may be tossed or sold names only the non-key kinds",
   "RARE_CANDY" in free and "TM_BLIZZARD" in free
   and not any(k in free for k in KEYS))
ck("key items and HMs are named as what the PC takes",
   all(k in pc for k in KEYS))
ck("...with the game's own refusal quoted, so toss/sell is not implied",
   "too important to toss" in pc)
ck("...and the arithmetic of what they cost", "12 of your 20 kinds" in pc)
ck("...and no word on which to store", "yours to know" in pc
   and "store the" not in pc.lower() and "S_S_TICKET is spent" not in pc)
ck("the PC path is the one already introduced above it",
   t.index("STORING") < t.index("WHAT MAY GO, AND HOW."))

# the same bag, the ≥18 pressure line
p = bare()._bag_pressure_line(obs)
ck("the pressure line names the store-only kinds",
   "KEY ITEMS AND HMs" in p and "STORING is the one way those 12 go" in p
   and all(k in p.split("KEY ITEMS AND HMs")[1].split(")")[0] for k in KEYS))

# a bag of nothing but key items
obs2 = {"bag": {k: 1 for k in KEYS} | {"X_" + str(i): 1 for i in range(8)},
        "key_items": KEYS + ["X_" + str(i) for i in range(8)],
        "map": {"id": "ROUTE_1", "region": "0,0", "objects": []}}
t2 = bare()._bag_line(obs2, {"id": "t", "done_when": {"map": "X"}})
ck("a bag of only key items says the free list is empty, and still names the PC",
   "nothing that is not a key item" in t2 and "PC TAKES them" in t2)

# no key items at all
obs3 = {"bag": {"POTION": 3, **{f"TM_{i}": 1 for i in range(19)}}, "key_items": [],
        "map": {"id": "ROUTE_1", "region": "0,0", "objects": []}}
t3 = bare()._bag_line(obs3, {"id": "t", "done_when": {"map": "X"}})
ck("with no key items the clause says so and invents none", "you carry none" in t3)

# the op doc
src = (ROOT / "planner/executor.py").read_text()
ck("the store_item doc says key items and HMs go in",
   "key items and HMs go in too, and it is the ONE place the\ngame lets those go" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
