#!/usr/bin/env python3
"""Words are not the bag (2026-09-05).

The plan said "I have the CARD KEY (LIFT_KEY) in my bag" three rounds running
and pressed Silph Co's shutters with it; the bag held LIFT_KEY and no CARD_KEY,
and the doors kept saying "Darn! It needs a CARD KEY!" (user: "it thinks the
liftkey and cardkey are the same sometimes"). Two notes now ride the round's
feedback: a claim to hold a thing the bag lacks is put beside the bag, and words
on the screen that name an item the bag lacks are too — each naming the held
item of the same kind as a DIFFERENT item. Where the missing one is, nothing
says.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
e = object.__new__(E.Executor)
obs = {"mode": "overworld", "bag": {"LIFT_KEY": 1, "OLD_ROD": 1, "POTION": 4}}
w = e._held_claim_note("I have the CARD KEY (LIFT_KEY) in my bag. I will interact with the shut door at (10,8).", obs)
ck("a claim to hold the Card Key is put beside a bag without one", "your plan speaks of holding CARD_KEY; the bag holds no CARD_KEY" in w, w)
ck("...and the key it does hold is named a different item", "the KEY you do hold, LIFT_KEY, is a DIFFERENT item" in w, w)
ck("a claim to hold what it holds says nothing", e._held_claim_note("I have the LIFT_KEY in my bag.", obs) == "")
ck("a sentence with no holding verb says nothing", e._held_claim_note("The door needs a CARD KEY.", obs) == "")
ck("a rod of another kind is the same shape", "the ROD you do hold, OLD_ROD" in e._held_claim_note("I have the GOOD ROD.", obs))
ck("a bag behind a menu is unreadable: silent", e._held_claim_note("I have the CARD KEY.", {"mode": "ui", "bag": {}}) == "")
ck("nothing about where the missing item is", "SILPH" not in w and "5F" not in w, w)
tr = ['interact(name=DOOR_SILPH_CO_10F_10_8,answer=yes): the world did not change, but it SPOKE — it said: "Darn! It needs a CARD KEY!"',
      "walk_to(10,9): ok"]
v = e._spoken_item_note(tr, obs)
ck("what the door said is put beside the bag", "something here spoke of CARD_KEY, which you do not hold" in v, v)
ck("...naming the lift key as a different item", "LIFT_KEY in your bag is a DIFFERENT item" in v, v)
ck("words naming a held item say nothing", e._spoken_item_note(['x: it said: "Here is a POTION for you"'], obs) == "")
ck("no speech, no note", e._spoken_item_note(["walk_to(1,1): ok"], obs) == "")
src = (ROOT / "planner" / "executor.py").read_text()
ck("both notes ride the round's feedback after the shelf note",
   "_held = self._held_claim_note(self._plan_said, _obs_now)" in src and "_spoke = self._spoken_item_note(trace, _obs_now)" in src)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
