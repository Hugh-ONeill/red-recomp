#!/usr/bin/env python3
"""Only volunteer an event that is still true of THIS world.

An escalation stuck on a flag is shown the events this run has watched
fire — author.py already settles that principle ("the only flags the
PROMPT volunteers are the ones this run has watched fire") and the leg
author has always had them. The escalation, which is the thing deciding
what to do next while a flag refuses to set, was shown none: `EVENT_` did
not appear once in a 5,570-character prompt, while the run's own history
held EVENT_ROUTE22_RIVAL_WANTS_BATTLE and the flag it was waiting on was
gated on beating exactly that rival.

THE TRAP, found minutes after the first version shipped. `flag_sites` is
persisted memory and THE SAVE CAN ROLL BACK UNDER IT. An attempt that
reloads an earlier save leaves the ledger holding events the current world
has never seen — measured live at five of ten, including EVENT_GOT_POKEDEX
and EVENT_OAK_GOT_PARCEL recorded as fired while the save had neither.
Volunteering those tells the run it holds a Pokedex it does not have,
which is the deed-ledger bug wearing a different hat.

So the LIVE OBSERVATION is the authority on what is set; the ledger only
supplies where it happened.

Synthetic: no game, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

LEDGER = {
    "EVENT_GOT_STARTER": "OAKS_LAB|4,1",
    "EVENT_GOT_OAKS_PARCEL": "VIRIDIAN_MART|0,2",
    "EVENT_GOT_POKEDEX": "OAKS_LAB|4,1",
    "EVENT_ROUTE22_RIVAL_WANTS_BATTLE": "OAKS_LAB|4,1",
}
FLAG_SG = {"done_when": {"flag": "EVENT_GOT_POKEBALLS_FROM_OAK"}}


def ex():
    e = object.__new__(E.Executor)
    e.flag_sites = dict(LEDGER)
    return e


def main():
    fails = []

    def check(name, obs, sg, want_in, want_out):
        txt = ex()._fired_text(obs, sg)
        ok = all(w in txt for w in want_in) and all(w not in txt
                                                    for w in want_out)
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"          {txt[:200]!r}")
            fails.append(name)

    # the world agrees with the ledger
    full = {"flags": list(LEDGER)}
    check("events still true are volunteered", full, FLAG_SG,
          ["EVENT_GOT_POKEDEX", "EVENT_ROUTE22_RIVAL_WANTS_BATTLE",
           "fired in OAKS_LAB|4,1"], [])

    # THE ROLLBACK. The save lost three of them; the ledger did not.
    rolled = {"flags": ["EVENT_GOT_STARTER", "EVENT_GOT_OAKS_PARCEL"]}
    check("an event the SAVE has rolled back is not volunteered", rolled,
          FLAG_SG, ["EVENT_GOT_OAKS_PARCEL"],
          ["EVENT_GOT_POKEDEX", "EVENT_ROUTE22_RIVAL_WANTS_BATTLE"])

    # nothing survives the rollback -> say nothing at all
    check("a world that shares no event with the ledger gets no block",
          {"flags": []}, FLAG_SG, [], ["EVENT_", "WATCHED FIRE"])

    # and it is only for subgoals actually waiting on a flag: space in this
    # prompt is the budget
    for name, dw in (("a map goal", {"map": "PEWTER_CITY"}),
                     ("a party goal", {"party_size": 3}),
                     ("a screen goal", {"screen": "BoxMenu"})):
        txt = ex()._fired_text(full, {"done_when": dw})
        ok = txt == ""
        print(f"  {'ok  ' if ok else 'FAIL'}  {name} gets no event block")
        if not ok:
            fails.append(name)

    # ...including inside an any_of, where a flag hides one level down
    txt = ex()._fired_text(full, {"done_when": {"any_of": [
        {"map": "PEWTER_CITY"}, {"flag": "EVENT_GOT_POKEDEX"}]}})
    ok = "EVENT_GOT_POKEDEX" in txt
    print(f"  {'ok  ' if ok else 'FAIL'}  a flag inside an any_of still "
          f"counts as waiting on one")
    if not ok:
        fails.append("any_of")

    print(f"\n{'-' * 60}")
    if fails:
        print(f"STALE OR MISSING EVENTS: {len(fails)} case(s)")
        return 1
    print("only events still true of this world are volunteered (8 checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
