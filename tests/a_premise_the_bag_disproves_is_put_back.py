#!/usr/bin/env python3
"""A premise the bag disproves is put back to the model.

"[missing] 'Rescue Mr. Fuji from the Pokemon Tower': The player has obtained
the Silph Scope and reached the top of the tower, but must actually rescue Mr.
Fuji" — inserted with no SILPH_SCOPE in the bag, so the new leg walked into
the same ghost (2026-09-04). The deed may be right; the premise is a claim the
record refutes. The done-judge already refuses a claim the bag disproves in
the SENTENCE (_item_not_held); this reads the missing rung's REASON the same
way and turns the proposal down with the fact, so the model answers again —
the same deed without the premise, or the deed that gets the thing.

Synthetic: no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
A.ENGINE_ITEMS |= {"SILPH_SCOPE", "POKE_FLUTE", "BICYCLE"}
START = ("standing in LAVENDER_TOWN with GYARADOS L32 ... BOULDERBADGE, CASCADEBADGE, THUNDERBADGE, 28562 money, "
         "and BICYCLE x1, DOME_FOSSIL x1, ESCAPE_ROPE x1, HM_CUT x1, POKE_BALL x8, POTION x4, TOWN_MAP x1")
WHY = ("The player has obtained the Silph Scope and reached the top of the tower, but must actually rescue "
       "Mr. Fuji from the Pokemon Tower before he will give the Flute")
ck("a reason claiming an item the bag lacks names the item",
   A._premise_item_not_held(WHY, START) == "SILPH_SCOPE", A._premise_item_not_held(WHY, START))
ck("an item the bag holds is not a false premise",
   A._premise_item_not_held("The player has obtained the Bicycle and can ride.", START) is None)
ck("needing a thing is not claiming to hold it",
   A._premise_item_not_held("The player needs the Silph Scope to see the ghost.", START) is None)
ck("no item named, nothing", A._premise_item_not_held("The tower must be climbed first.", START) is None)
src = (ROOT / "planner" / "author.py").read_text()
ck("the missing rung turns such a proposal down with the fact, and asks again",
   "_ph_item = _premise_item_not_held(_why, start)" in src
   and "its reason says you hold " in src and "turned_down.append((ins, f\"your reason said you have {_ph_item}; " in src)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
