#!/usr/bin/env python3
"""Crossing a leg off for ever asks the record first, all four ways.

Four guards were written together, each after a leg was wrongly judged
finished: _never_stood_in for places, _badge_not_earned for badges,
_item_not_held for items, _levels_not_reached for levels.  check_done got
all four.  check_already_done -- the rung that crosses a leg off the
OUTLINE, which nothing brings back -- got two.

Leg 41, "Retrieve the Secret Key from the Pokemon Mansion", was crossed
off on the reason "The CARD_KEY is present in the bag, which is the Secret
Key retrieved from the mansion basement".  Those are two different items
and one of them was not held.  The run walked on toward Cinnabar Gym with
nothing to open it (2026-09-10).

Which facts satisfy which objective is still the model's to say.  What is
refused is a claim the bag disproves, which is the same thing this file
has said about places and badges since August.  No game, no model: the
model is a stub that says DONE to everything, so anything that comes back
refused was refused by the record.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                     # noqa: E402
import brock_probe                                     # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

SAID = '{"why": "the CARD_KEY is present in the bag, which is the Secret Key", "done": true}'
brock_probe.chat = lambda msgs, model, **kw: SAID

START = ("BAG: BICYCLE, CARD_KEY, DOME_FOSSIL, ESCAPE_ROPE, HM_CUT, HM_FLY, "
         "HM_STRENGTH, HM_SURF, LIFT_KEY, MASTER_BALL, MOON_STONE, OLD_ROD, "
         "POKE_FLUTE, SILPH_SCOPE, S_S_TICKET, TOWN_MAP  "
         "BADGES: BOULDERBADGE, CASCADEBADGE, MARSHBADGE, RAINBOWBADGE, "
         "SOULBADGE, THUNDERBADGE  "
         "PARTY: GYARADOS L45, CHARIZARD L56, GLOOM L41, EEVEE L40, "
         "DODRIO L41, NIDORINA L41")


def done(deed):
    return A.check_already_done(deed, START, "stub")


# ---- the leg that was lost ---------------------------------------------
ck("an item objective is refused while the bag lacks the item",
   not done("Retrieve the Secret Key from the Pokemon Mansion"))
ck("...and the guard names the item, not the one in the reason",
   A._item_not_held("Retrieve the Secret Key from the Pokemon Mansion",
                    START) == "SECRET_KEY")

# ---- and the ones it must not refuse ------------------------------------
ck("an item objective already satisfied is still crossed off",
   done("Retrieve the Card Key from Silph Co."))
ck("a deed that SPENDS the item is left to the model",
   done("Give the Gold Teeth to the Warden"))
ck("...including the ones that spell spending another way",
   done("Exchange the Bike Voucher for a Bicycle"))
ck("an objective naming no item is untouched by this",
   done("Reach Cinnabar Island"))

# ---- the rest of the family still guards this rung ---------------------
ck("a badge objective is refused while the badge is not worn",
   not done("Defeat Blaine for the Volcano Badge"))
ck("...and one that is worn passes", done("Defeat Erika for the Rainbow Badge"))
ck("a level bar the party misses is refused",
   not done("Raise every party member to at least level 60"))

# ---- the same guards its sibling has ------------------------------------
SRC = (ROOT / "planner" / "author.py").read_text()
blk = SRC.split("def check_already_done", 1)[1].split("\ndef ", 1)[0]
for g in ("_never_stood_in", "_badge_not_earned",
          "_item_not_held", "_levels_not_reached"):
    ck(f"check_already_done asks {g}", g in blk)
ck("...and refuses before it asks the model",
   blk.index("_item_not_held") < blk.index("brock_probe.chat"))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n + (("  [" + str(d) + "]") if (d and not ok) else ""))
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
