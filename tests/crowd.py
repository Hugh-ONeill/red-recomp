#!/usr/bin/env python3
"""Thirty-six of a thing is one thing — and people never are.

The Rocket Game Corner has thirty-six slot machines. The ledger's kind
order is fixed (fixtures before people, always), so the page read:

    1. explore — press SLOT_MACHINE_18 here (fixture); 31 thing(s) here
       are untouched
    2..22. SLOT_MACHINE_18, _19, _2, _21, _22, _24, _25, _26, ...
    … and 28 more thing(s) not shown: 8 touched, 9 unreachable,
      10 unspoken, 1 untouched

Every person in the room was off the end of the page, including the Rocket
standing in front of the way down to the hideout, and item 1 sent the run
to press machine number twenty-two. Pressing it cannot teach what the first
twenty-one did not.

Two rules come out of that, and the second bounds the first:
  * a crowd of the same fixture reads as ONE line, folded before the page
    is cut, and among things equally untouched the rarer name goes first;
  * a crowd is only ever FURNITURE. ROUTE3_COOLTRAINER_F1 and F2 are two
    trainers who say different things, not one trainer seen twice.

No game, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import ledger as L            # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class Ex:
    searched: dict = {}
    visits: dict = {}

    def _where(self, o):
        return "GAME_CORNER|8,5"


OBS = {"map": {"id": "GAME_CORNER", "region": "8,5", "warps": []},
       "party": []}


def C(key, kind, status, **kw):
    return L.Candidate(key=key, kind=kind, status=status, reachable=True, **kw)


def casino(machines=36, people=6):
    out = [C(f"SLOT_MACHINE_{n}", "fixture", "untouched", x=n % 20, y=10)
           for n in range(1, machines + 1)]
    out += [C(n, "npc", "unspoken", x=2, y=6) for n in
            ["GAMECORNER_BEAUTY1", "GAMECORNER_ROCKET",
             "GAMECORNER_GENTLEMAN", "GAMECORNER_GAMBLER1",
             "GAMECORNER_GAMBLER2", "GAMECORNER_CLERK"][:people]]
    out += [C("15,17", "door", "taken", n=1, dest="CELADON_CITY|2,1"),
            C("16,17", "door", "taken", n=1, dest="CELADON_CITY|2,1")]
    return out


def main():
    print("the room with thirty-six of one thing:")
    cands = casino()
    line = L.plan_explore(Ex(), OBS, cands, target="map:ROCKET_HIDEOUT_B1F")
    check("item 1 offers a person, not the twenty-second machine",
          "SLOT_MACHINE" not in line, line)
    page = L.render([C("explore", "op", "op", note=line)] + cands,
                    Ex(), OBS, target="map:ROCKET_HIDEOUT_B1F", limit=20)
    check("the machines read as one line",
          page.count("SLOT_MACHINE_") <= 4
          and "36 x SLOT_MACHINE" in page, page[:400])
    for who in ["GAMECORNER_ROCKET", "GAMECORNER_CLERK",
                "GAMECORNER_GENTLEMAN"]:
        check(f"...so {who} is on the page", who in page)
    check("...and nothing is reported as cut",
          "not shown" not in page, page[-300:])
    check("both doors are still there",
          "door (15,17)" in page and "door (16,17)" in page)

    print("\nwhat is not a crowd:")
    trainers = [C(f"ROUTE3_COOLTRAINER_F{n}", "trainer", "unspoken",
                  x=n, y=4) for n in range(1, 7)]
    page = L.render(trainers, Ex(), OBS, target="flag:X", limit=20)
    check("six numbered trainers are six people, each on its own line",
          all(f"ROUTE3_COOLTRAINER_F{n}" in page for n in range(1, 7))
          and " x ROUTE3_COOLTRAINER_F" not in page, page[:300])
    three = casino(machines=3, people=2)
    page = L.render(three, Ex(), OBS, target="flag:X", limit=20)
    check("three of a fixture is not a crowd either",
          all(f"SLOT_MACHINE_{n}" in page for n in (1, 2, 3))
          and " x SLOT_MACHINE" not in page, page[:300])

    print("\nthe goal still leads:")
    line = L.plan_explore(Ex(), OBS, casino(), target="flag:SOME_SWITCH")
    check("a flag goal is offered the machines, crowd or not",
          "SLOT_MACHINE" in line, line)

    print("\n" + "-" * 60)
    if FAILS:
        print(f"THE FURNITURE IS STILL BURYING THE ROOM: {len(FAILS)} case(s)")
        return 1
    print("a crowd of furniture reads as one thing; people never do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
