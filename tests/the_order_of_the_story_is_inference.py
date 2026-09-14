#!/usr/bin/env python3
"""A DONE verdict that rests on where a deed sits in the story is inference.

check-done crossed off "Deliver the OAKS_PARCEL to Professor Oak" with the
reason "the player has already battled the rival in Oak's lab, which occurs
after the parcel has been delivered" (2026-09-14). It does not: that fight
is the first thing in the game. But the shape is the problem, not the
fact: a deed is shown by its own trace -- the item, the event, the place
-- and never by a remembered sequence of what comes after what. _inferred
already refuses hedges (implies, likely, presumably) and game lore (in
Pokemon Red, typically); it now refuses story order too.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                       # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("'which occurs after' is inference",
   A._inferred("The player has already battled the rival in Oak's lab, "
               "which occurs after the parcel has been delivered."))
ck("'this only happens once' is inference",
   A._inferred("Team Rocket was beaten, and this only happens once the "
               "Silph Scope is held"))
ck("'that comes before' is inference",
   A._inferred("Brock is beaten, and that comes before Mt Moon"))
ck("a fact about the bag is not", not A._inferred("the parcel is no longer in the bag"))
ck("a fact about an event is not",
   not A._inferred("EVENT_OAK_GOT_PARCEL fired after the clerk spoke"))
ck("a fact about the place is not",
   not A._inferred("the party stands in CERULEAN_CITY, visited twice"))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
