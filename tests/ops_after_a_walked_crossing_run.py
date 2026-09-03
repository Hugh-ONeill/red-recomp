#!/usr/bin/env python3
"""Ops after a crossing onto ground you have walked run; blind ones are cut.

"cross east, CUT the bush at (5,8), cross west" was a one-op round for ever:
the map-change rule cut everything after the crossing, the cut never
happened, and the next round began "I have just used CUT" — three rounds
running on 2026-09-03, with the deed note and the echo verdict both saying
otherwise. The rule exists against ops written BLIND for a map never seen.
Route 9 had been walked forty times and (5,8) was a bush off the run's own
ledger: recall, not authoring, the same distinction that already let a
trailing `go` ride along.

So the cut follows the walked graph. A cross or use_warp whose landing the
graph knows from where the party will be standing is a change onto walked
ground and the ops after it run there; a crossing the graph cannot place, or
an explore, ends the macro as before. And the deed note reads the FULL macro,
so it can never again say "no field_move was among your ops" two lines above
a truncation note listing the field_move that was not run.

Synthetic: a walked graph, no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

e = object.__new__(E.Executor)
e.explored = {
    "CERULEAN_CITY|26,7": {"east": {"to": "ROUTE_9|0,8", "n": 68},
                           "25,25": {"to": "CERULEAN_MART|0,2", "n": 27}},
    "ROUTE_9|0,8": {"west": {"to": "CERULEAN_CITY|26,7", "n": 3},
                    "east": {"to": "ROUTE_10|0,4", "n": 12}},
    "ROUTE_10|0,4": {},
}
e.visits = {"CERULEAN_CITY|26,7": 191, "ROUTE_9|0,8": 40, "ROUTE_10|0,4": 5,
            "CERULEAN_MART|0,2": 27}
HERE = "CERULEAN_CITY|26,7"

plan = [{"op": "cross", "dir": "east"},
        {"op": "field_move", "move": "CUT", "x": 5, "y": 8},
        {"op": "cross", "dir": "west"}]
ck("cross east onto Route 9 (walked), cut, cross west back: nothing is cut off",
   e._macro_cut_index(plan, HERE) is None)
ck("a door the graph knows behaves the same",
   e._macro_cut_index([{"op": "use_warp", "x": 25, "y": 25},
                       {"op": "buy", "item": "POTION", "count": 1}], HERE) is None)
ck("a crossing the graph cannot place ends the macro there",
   e._macro_cut_index([{"op": "cross", "dir": "north"},
                       {"op": "walk_to", "x": 1, "y": 1}], HERE) == 0)
ck("...and so does a landing never visited",
   (lambda: (e.visits.pop("ROUTE_9|0,8"),
             e._macro_cut_index(plan, HERE))[1])() == 0)
e.visits["ROUTE_9|0,8"] = 40
ck("explore ends the macro: it lands who knows where",
   e._macro_cut_index([{"op": "explore"}, {"op": "interact", "name": "X"}], HERE) == 0)
ck("a second crossing is judged from where the first one lands",
   e._macro_cut_index([{"op": "cross", "dir": "east"},
                       {"op": "cross", "dir": "east"},
                       {"op": "walk_to", "x": 3, "y": 3}], HERE) is None
   and e._macro_cut_index([{"op": "cross", "dir": "east"},
                           {"op": "cross", "dir": "south"},
                           {"op": "walk_to", "x": 3, "y": 3}], HERE) == 1)
ck("a trailing go still rides along",
   e._macro_cut_index([{"op": "cross", "dir": "north"}, {"op": "go", "to": "X"}], HERE) is None)
ck("a map-changing op that is LAST cuts nothing",
   e._macro_cut_index([{"op": "walk_to", "x": 1, "y": 1}, {"op": "cross", "dir": "north"}], HERE) is None)
ck("no map change, no cut",
   e._macro_cut_index([{"op": "interact", "name": "A"}, {"op": "walk_to", "x": 1, "y": 1}], HERE) is None)
ck("standing nowhere the graph knows, every crossing is blind",
   e._macro_cut_index(plan, "NOWHERE|0,0") == 0)

src = (ROOT / "planner" / "executor.py").read_text()
ck("the site asks the graph", "cut = self._macro_cut_index(macro, self._where(start))" in src)
ck("the full macro is kept for the deed note and the verdict",
   "_macro_full = list(macro)" in src
   and "_deed = self._deed_note(_macro_full, self._plan_said, trace)" in src
   and "_macro_full, self._plan_said, trace)" in src)
ck("the truncation note states the new rule",
   "onto ground you have never walked" in src
   and "Ops after a crossing or door onto \"\n                        f\"ground you HAVE walked do run" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
