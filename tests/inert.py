#!/usr/bin/env python3
"""A named thing is inert wherever you pressed it from.

ROUTE12_SNORLAX was pressed NINETEEN times. Every press said "A sleeping
POKéMON blocks the way!" and changed nothing, and it never once read as
inert — it kept its full rank as a live lead, and the model kept pressing
it while the POKé FLUTE sat in the bag. The engine is explicit that
pressing can never work (src/inventory/ItemEffects.lua: "standing next to
a not-yet-beaten Snorlax: this is the ONLY way Snorlax wakes -- using the
flute from the item-use menu, never just talking to it").

The cause was the snapshot inertness is keyed on: it carries the PLAYER'S
TILE, and interact walks to the thing itself, so one step sideways between
presses made a dead lead look fresh. Position out; everything else that
makes a thing worth another word — a flag fired, a level gained, a bag
slot freed, HP changed — stays in.

No game, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))

import executor as E          # noqa: E402
import ledger as L            # noqa: E402
import untried as U           # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def obs(x=10, y=61, flags=1, bag=None, hp=50, level=30):
    return {"map": {"id": "ROUTE_12", "region": "10,21", "warps": []},
            "player": {"x": x, "y": y}, "mode": "overworld",
            "party": [{"level": level, "hp": hp, "max_hp": 100}],
            "flags": ["f"] * flags, "bag": bag or {"POKE_FLUTE": 1}}


S = E.Executor._snapshot_anywhere


def main():
    print("one step sideways is not a changed world:")
    check("pressing from the next cell over is the same snapshot",
          S(obs(10, 61)) == S(obs(9, 61)))
    check("...and the plain snapshot still tells them apart (walks use it)",
          E.Executor._snapshot(obs(10, 61))
          != E.Executor._snapshot(obs(9, 61)))

    print("\nbut a changed world still is one:")
    check("an event firing makes it worth another word",
          S(obs(flags=1)) != S(obs(flags=2)))
    check("a level gained does too", S(obs(level=30)) != S(obs(level=31)))
    check("so does a bag slot freed",
          S(obs(bag={"POKE_FLUTE": 1}))
          != S(obs(bag={"POKE_FLUTE": 1, "NUGGET": 1})))
    check("and so does HP", S(obs(hp=50)) != S(obs(hp=100)))

    print("\nthe Snorlax, nineteen presses in:")
    from candidates import make, obs as cobs      # the ledger's fixture
    ex = make(frontier={U.HERE: []})
    snor = {"name": "ROUTE12_SNORLAX", "kind": "npc", "x": 10, "y": 62,
            "reachable": True}
    was = cobs(ex, [], objects=[snor])
    was["player"] = {"x": 10, "y": 61}
    ex._tried_objs = {U.HERE: {"ROUTE12_SNORLAX"}}
    ex._inert_objs = {U.HERE: {"ROUTE12_SNORLAX": S(was)}}
    now = cobs(ex, [], objects=[snor])
    now["player"] = {"x": 9, "y": 62}          # pressed again, one cell over
    sn = {c.key: c for c in
          L.build(ex, now, target="flag:X", want_explore=False)
          }.get("ROUTE12_SNORLAX")
    check("reads as inert from a different cell",
          sn is not None and sn.status == "inert", sn and sn.status)
    check("...and says why",
          sn is not None and "did not change" in (sn.note or ""),
          sn and sn.note)
    moved = cobs(ex, [], objects=[snor], mark_flags=2)
    moved["player"] = {"x": 9, "y": 62}
    sn2 = {c.key: c for c in
           L.build(ex, moved, target="flag:X", want_explore=False)
           }.get("ROUTE12_SNORLAX")
    check("...but an event since makes it worth another word",
          sn2 is not None and sn2.status != "inert", sn2 and sn2.status)

    print("\n" + "-" * 60)
    if FAILS:
        print(f"A DEAD LEAD STILL LOOKS FRESH: {len(FAILS)} case(s)")
        return 1
    print("a thing that does nothing does nothing wherever you stand")
    return 0


if __name__ == "__main__":
    sys.exit(main())
