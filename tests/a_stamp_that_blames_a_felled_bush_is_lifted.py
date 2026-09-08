#!/usr/bin/env python3
"""A hop stamp that blames a bush is void while that bush is down.

A stamp says "this leg would not land in THIS world state", and the world
state it compares is badges, flags and bag kinds — a cut bush changes none
of them. So the model cut the Route 9 bush by hand, and `go` still refused
with the stamp's own words naming the bush now lying felled beside it (run
16, 2026-09-08; user: "go should just route through the bush no?"). A felled
bush is not on the map's object list; when a stamp's reason names one that no
longer stands, the stamp goes, and go routes. Synthetic: a bare executor.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


WHY = ("no path — the ground you have SEEN and can walk from here is 9 cell(s) and the closest it comes "
       "to 6,2 is 4,8. At the EDGE of that ground stand: CUT_TREE (a bush CUT clears) at (5,8) — that is "
       "what is beside the boundary")


def bare():
    ex = E.Executor.__new__(E.Executor)
    ex.explored = {"ROUTE_9|0,8": {"walk:ROUTE_9|6,2": {"to": "ROUTE_9|6,2", "n": 1,
                                                        "blocked_at": [4, 166, 17], "blocked_why": WHY},
                                   "west": {"to": "CERULEAN_CITY|26,7", "n": 4}}}
    ex._save_memory = lambda: None
    ex.log = lambda *a, **k: None
    return ex


def obs(mid, bushes):
    return {"map": {"id": mid, "objects": [{"name": "CUT_TREE", "x": x, "y": y} for x, y in bushes]
                    + [{"name": "ROUTE9_CAMPER", "x": 20, "y": 4}]}}


ex = bare()
ck("the bush still standing, the stamp stays", ex._lift_bush_stamps("ROUTE_9|0,8", obs("ROUTE_9", [(5, 8)])) == 0
   and "blocked_at" in ex.explored["ROUTE_9|0,8"]["walk:ROUTE_9|6,2"])
ck("the bush felled, the stamp is lifted", ex._lift_bush_stamps("ROUTE_9|0,8", obs("ROUTE_9", [])) == 1
   and "blocked_at" not in ex.explored["ROUTE_9|0,8"]["walk:ROUTE_9|6,2"])
ck("...and the reason is kept for the record", ex.explored["ROUTE_9|0,8"]["walk:ROUTE_9|6,2"].get("blocked_why") == WHY)
ex = bare()
ck("standing on another map says nothing about this one's bushes",
   ex._lift_bush_stamps("CERULEAN_CITY|26,7", obs("CERULEAN_CITY", [])) == 0
   and "blocked_at" in ex.explored["ROUTE_9|0,8"]["walk:ROUTE_9|6,2"])
ex = bare()
ex.explored["ROUTE_9|0,8"]["walk:ROUTE_9|6,2"]["blocked_why"] = "a fight started 12 cell(s) short"
ck("a stamp that blames no bush is left alone", ex._lift_bush_stamps("ROUTE_9|0,8", obs("ROUTE_9", [])) == 0)

src = (ROOT / "planner" / "executor.py").read_text()
i = src.index("def _go_step(")
j = src.find("path = self._route(here, t)", i)
ck("go lifts such stamps before it routes", 0 < src.find("self._lift_bush_stamps(here, obs)", i) < j)
sys.exit(1 if fails else 0)
