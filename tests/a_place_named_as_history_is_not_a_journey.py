#!/usr/bin/env python3
"""A place named as where you have been is not a journey, and a first visit gets no trip back.

The party took Rock Tunnel's untaken ladder into a B1F region it had never
stood on — the new ground the whole leg hinged on — and the round's feedback
met it with "You said Route 10, and the ground you have walked reaches it from
here in 4 legs ... go ROUTE_10 walks the whole way in ONE round". The prose
had named Route 10 as HISTORY: "my previous attempts to exit via Route 10 were
blocked". The next round was that go, back out (2026-09-03; user: "it got to
a new region but then went back").

The note exists to save rounds on a journey the model DECLARED. Two limits
keep it that: no note on a round that put the party on ground it had never
stood on, and a place counts only in a sentence that says where the model is
going — an intent word present, no history word beside it.

Synthetic: no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

def make(here, visits_here, hops):
    e = object.__new__(E.Executor)
    e.explored = {"ROUTE_10|0,4": {}, "ROCK_TUNNEL_B1F|2,2": {}, here: {}}
    e.visits = {here: visits_here, "ROUTE_10|0,4": 40}
    e.settle = lambda: {"map": {"id": here.split("|")[0], "region": here.split("|")[1]}}
    e._where = lambda obs: here
    e._route = lambda a, b: (["x"] * hops) if b.startswith("ROUTE_10") else None
    return e

HIST = ("I am currently in Rock Tunnel 1F. I need to reach Lavender Town. I will first take the "
        "newly reachable stairs at (17,11), as my previous attempts to exit via Route 10 were "
        "blocked by bushes. I'll see where these stairs lead first.")
GOING = "I will return to Route 10 and then cross south into Lavender Town."

e = make("ROCK_TUNNEL_B1F|2,2", 1, 4)
ck("a first visit to a region gets no trip back, whatever the prose",
   e._go_would_have([{"op": "use_warp", "x": 17, "y": 11}], GOING) == "")
e = make("ROCK_TUNNEL_B1F|2,2", 3, 4)
ck("a place named only as history is not a journey",
   e._go_would_have([{"op": "cross", "dir": "west"}], HIST) == "")
note = e._go_would_have([{"op": "cross", "dir": "west"}], GOING)
ck("a place named as where it is going still earns the note",
   "You said Route 10" in note and '"to":"ROUTE_10"' in note, note)
ck("a going-sentence with a history word beside the place does not",
   e._go_would_have([{"op": "cross", "dir": "west"}],
                    "I will go back to Route 10, where I already cut the bushes.") == "")
ck("prose with no intent word at all names no journey",
   e._go_would_have([{"op": "cross", "dir": "west"}],
                    "Route 10 lies to the west of here.") == "")

src = (ROOT / "planner" / "executor.py").read_text()
ck("the first-visit rule reads the visits ledger for where the party stands",
   "if _v is not None and int(_v.get(here, 0) or 0) <= 1:\n            return \"\"" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
