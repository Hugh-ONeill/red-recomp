#!/usr/bin/env python3
"""A regrown bush the party cannot walk to is not "across the only way out".

Route 16's north strip, west part, the Fly house a few steps away (run 16,
2026-09-08). The page's bush row read: "CUT_TREE (cut_tree at 34,9) — you
cannot walk to it from where you stand — you cut this one before and it grew
back — and it is across the only way out of the ground you can reach from
here now". The bush stood on the OTHER part of the route, and "the only way
out" had never been checked: the flag behind the clause (`opens`) says only
that walkable ground lies past the bush that no walk from here reaches. The
model walked back through the gate to cut it three times (user: "the tree is
nowhere near blocking it but it only ever occasionally gets to the west side
then doesnt explore"). And the door row beside it said the door's "way in is
ground you have not stood on" while the record held four takings of that
door from the other part. Both rows now say what is known and no more.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "planner"))
import candidates as C   # noqa: E402
import untried as U      # noqa: E402
import ledger as L       # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"\n      {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


OTHER = f"{U.MAP}|27,10"


def world(reachable_bush, took_before=True):
    ex = C.make(explored={OTHER: {"24,4": {"to": "GATE|0,2", "n": 4}} if took_before else {},
                          U.HERE: {}},
                frontier={U.HERE: ["24,4"], OTHER: ["24,4"]})
    ex.visits[OTHER] = 4
    ex._cut_bushes = {U.MAP: ["34,9"]}
    o = C.obs(ex, ["24,4"], objects=[{"name": "CUT_TREE", "kind": "cut_tree", "x": 34, "y": 9,
                                       "reachable": reachable_bush, "opens": True}])
    w = o["map"]["warps"][0]
    w["reachable"] = False
    w["from"] = []
    w["stood_parts"] = 1
    return ex, o


ex, o = world(reachable_bush=False)
cands = L.build(ex, o, target="map:ROUTE_16_FLY_HOUSE")
bush = next((c for c in cands if str(c.key).startswith("CUT_TREE")), None)
ck("the bush row exists", bush is not None)
if bush:
    ck("a bush out of reach is not 'across the only way out'", "only way out" not in (bush.note or ""), bush.note)
    ck("...it is said to stand in a part no walk reaches, so not in your way",
       "not in your way" in (bush.note or "") and "grew back" in (bush.note or ""), bush.note)
door = next((c for c in cands if c.key == "24,4"), None)
ck("the door row exists", door is not None)
if door:
    ck("a door the record shows taken from another part is not 'ground you have not stood on'",
       "ground you have not stood on" not in (door.note or ""), door.note)
    ck("...it names the part that took it and how often",
       f"from {OTHER} you took this door 4 time(s)" in (door.note or ""), door.note)
    ck("...and the regrown bush on this floor, as what may have shut it",
       "grown back, CUT_TREE at (34,9)" in (door.note or ""), door.note)

ex, o = world(reachable_bush=True)
cands = L.build(ex, o, target="map:ROUTE_16_FLY_HOUSE")
bush = next((c for c in cands if str(c.key).startswith("CUT_TREE")), None)
ck("a reachable regrown bush says the ground past it waits on the cut",
   bush is not None and "until it is cut again" in (bush.note or ""), getattr(bush, "note", None))

ex, o = world(reachable_bush=False, took_before=False)
cands = L.build(ex, o, target="map:ROUTE_16_FLY_HOUSE")
door = next((c for c in cands if c.key == "24,4"), None)
ck("with no taking on record the old sentence stands",
   door is not None and "ground you have not stood on" in (door.note or ""), getattr(door, "note", None))
sys.exit(1 if fails else 0)
