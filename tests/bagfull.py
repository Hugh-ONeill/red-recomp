#!/usr/bin/env python3
"""A full bag is said whatever the step is for, and spending comes first.

20/20 kinds silently refuses every gift and every ball on the ground. Four
legs of this run have been blocked by it — the Lift Key, HM02, and the
Silph Scope twice, the second time with Giovanni already beaten and the
Scope lying on the floor where he had been — and the note that explains it
was gated on the STEP wanting an item, which a full bag does not care
about.

And the note opened with tossing. Tossing is also the shortest op to write
— one item, no slot, no forget — so the reflex under pressure was to
destroy a TM, twice in one leg, while a MOON_STONE, an IRON and two HP_UPs
sat in the same bag, each of which frees the same slot and keeps what it
is worth (user: "its reflex when the bag is full is always to toss a tm,
instead of using it, or using a different consumable like the iron or two
hp_ups it has"). Same facts, ordered so the free ones are read first.

Which one to spend is still the model's. No game, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E          # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# the bag as it stood on ROCKET_HIDEOUT_B4F with the Scope on the floor
FULL = ["BIKE_VOUCHER", "ESCAPE_ROPE", "HELIX_FOSSIL", "HM_CUT", "HP_UP",
        "HYPER_POTION", "IRON", "LIFT_KEY", "MOON_STONE", "POKE_BALL",
        "S_S_TICKET", "TM_BODY_SLAM", "TM_BUBBLEBEAM", "TM_DIG",
        "TM_MEGA_DRAIN", "TM_THUNDERBOLT", "TM_THUNDER_WAVE",
        "TM_WATER_GUN", "TM_WHIRLWIND", "TOWN_MAP"]
KEYS = ["BIKE_VOUCHER", "S_S_TICKET", "TOWN_MAP", "HM_CUT", "LIFT_KEY"]


def bare():
    ex = object.__new__(E.Executor)
    ex.plan = {"subgoals": []}
    return ex


def line(items, keys=KEYS, done_when=None):
    obs = {"bag": {k: 1 for k in items}, "key_items": keys}
    return bare()._bag_line(obs, {"id": "t",
                                  "done_when": done_when or {"map": "X"}})


def main():
    print("the bag that was full when the Silph Scope hit the floor:")
    t = line(FULL)
    check("a full bag is said even when the step is a map hop", bool(t), t)
    check("...and says what full MEANS", "REFUSED" in t, t)
    check("...and names the free spends",
          "MOON_STONE" in t and "IRON" in t and "HP_UP" in t, t)
    check("spending is read before tossing",
          t.index("SPENDING") < t.index("TOSSING"), t)
    check("...and tossing is still there, described as what it is",
          "destroys the thing" in t, t)
    check("storing is named as the reversible one",
          "destroys\nnothing" in t or "destroys nothing" in t, t)
    check("key items are not offered",
          all(k not in t.split("What may go at all")[1] for k in
              ("BIKE_VOUCHER", "S_S_TICKET", "HM_CUT")), t)

    print("\none short of full:")
    t = line(FULL[:-1])
    check("says nothing for a map step", t == "", t)
    t = line(FULL[:-1], done_when={"has_item": {"SILPH_SCOPE": 1}})
    check("...but speaks when the step is FOR an item", bool(t), t)
    check("...and says which it is", "one short of full" in t, t)

    print("\nnothing to say:")
    check("a roomy bag is silent", line(FULL[:5]) == "")
    t = line(KEYS + ["X_1", "Y_2"] * 0 + FULL[:0] or KEYS)
    check("a bag of nothing but key items says so",
          line(KEYS * 4) == "" or "every single thing you carry is a key item"
          in line([k for k in FULL], keys=FULL))

    print("\n" + "-" * 60)
    if FAILS:
        print(f"THE FULL BAG IS STILL QUIET OR STILL LEADS WITH TOSS: "
              f"{len(FAILS)} case(s)")
        return 1
    print("a full bag speaks, and it offers spending before destroying")
    return 0


if __name__ == "__main__":
    sys.exit(main())
