#!/usr/bin/env python3
"""A boulder is not a person.

The shim's object classifier ends in `npc`: item, then trainer, then sign,
then everybody else. A Strength boulder carries a sprite, a text and no
trainerClass, so all twenty-five of them in this game — Victory Road's
switches, Seafoam's waterfall stoppers, the one parked on the Warden's
RARE_CANDY — were listed to the model as people, "never spoken to",
competing with the room's actual inhabitants for item 1 and for the page
(user: "boulders may register as npcs?").

You cannot speak to a rock, and pressing A at one does nothing. It is the
same shape as CUT_TREE, which the shim already keeps apart: a thing in the
way that exactly one field move moves. Three facts about moving it are in
the engine and none are guessable from outside — STRENGTH has to be
switched on from the party menu, the game switches it off again on every
map load, and the first shove only arms the push — so the harness owns the
mechanics and the model owns the direction.

No game, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))

import ledger as L            # noqa: E402
import untried as U           # noqa: E402
from candidates import make, obs as cobs   # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


ROCK = {"name": "VICTORYROAD1F_BOULDER1", "kind": "boulder",
        "x": 8, "y": 4, "reachable": True}
PERSON = {"name": "VICTORYROAD1F_COOLTRAINER_M1", "kind": "npc",
          "x": 3, "y": 9, "reachable": True}


def board(objects, moves=()):
    ex = make(frontier={U.HERE: []})
    o = cobs(ex, [], objects=list(objects))
    o["party"] = [{"level": 40, "hp": 100, "max_hp": 100,
                   "moves": [{"id": m} for m in moves]}]
    return ex, o


def by_key(cands):
    return {c.key: c for c in cands}


def main():
    print("with nobody who knows STRENGTH:")
    ex, o = board([ROCK, PERSON])
    cands = L.build(ex, o, target="flag:X", want_explore=False)
    rock = by_key(cands)["VICTORYROAD1F_BOULDER1"]
    check("it is not filed as a person", rock.kind == "boulder", rock.kind)
    check("...and never as 'never spoken to'", rock.status == "boulder",
          rock.status)
    page = L.render(cands, ex, o, target="flag:X")
    check("...the page says what it is and what moves it",
          "BOULDER" in page and "STRENGTH" in page, page[:300])
    check("...and says nobody can move it yet",
          "nobody in the party knows STRENGTH" in page, page[:400])
    check("the actual person is still a person",
          by_key(cands)["VICTORYROAD1F_COOLTRAINER_M1"].status == "unspoken")

    print("\nwith STRENGTH in the party:")
    ex, o = board([ROCK, PERSON], moves=("STRENGTH",))
    cands = L.build(ex, o, target="flag:X", want_explore=False)
    rock = by_key(cands)["VICTORYROAD1F_BOULDER1"]
    check("it becomes a live lead", rock.status == "pushable", rock.status)
    check("...ranked with the ways on, not with the furniture",
          L.STATUS_RANK["pushable"] == L.STATUS_RANK["cuttable"] == 0)
    page = L.render(cands, ex, o, target="flag:X")
    check("...and the page names the op and that STRENGTH must be on here",
          '"op":"push"' in page and "every map load" in page
          or "map load" in page, page[:600])

    print("\nexplore does not pick a direction for you:")
    ex, o = board([ROCK], moves=("STRENGTH",))
    cands = L.build(ex, o, target="flag:X", want_explore=True)
    check("item 1 does not offer to push it",
          "push" not in (cands[0].note or "").lower(), cands[0].note)
    check("...but the room is not signed off as finished either",
          not L.fully_worked(cands), [c.status for c in cands])

    print("\nan unreachable boulder is just unreachable:")
    ex, o = board([dict(ROCK, reachable=False)], moves=("STRENGTH",))
    cands = L.build(ex, o, target="flag:X", want_explore=False)
    check("no push is offered for a rock no walk reaches",
          by_key(cands)["VICTORYROAD1F_BOULDER1"].status == "unreachable")

    print("\n" + "-" * 60)
    if FAILS:
        print(f"A ROCK IS STILL BEING TALKED TO: {len(FAILS)} case(s)")
        return 1
    print("a boulder reads as a boulder, and the direction stays the model's")
    return 0


if __name__ == "__main__":
    sys.exit(main())
