#!/usr/bin/env python3
"""A cut bush says which side it opened and that it grows back when you leave.

Three rounds running: "use CUT to clear the bush at (5,8) ... then cross
west" — the bush on Route 9 blocks the way EAST, the party faced east to cut
it, and crossing west off the map regrows it (the engine's rule, like the
original: a cut tree comes back whenever its map is re-entered). The round
said "GLOOM hacked away with CUT!" and nothing more, the ledger said the bush
"regrows when the game reloads" — read as a process restart — and the next
plan opened "I have already cleared the bush on Route 9" (2026-09-03).

Two engine facts now ride the cut's own result line: how long the bush stays
down, and which side lies past it (the way the party faced to cut). The ledger
row for a regrown bush says the same rule in the same words. Nothing says
where to go.

Synthetic: no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402
import ledger as L                                     # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
e = object.__new__(E.Executor)

obs = {"map": {"id": "ROUTE_9"}, "player": {"x": 4, "y": 8, "facing": "right"}}
note = e._cut_aftermath({"move": "CUT", "x": 5, "y": 8}, obs)
ck("the cut names its bush and its map", "bush at (5,8)" in note and "ROUTE_9" in note, note)
ck("...says it grows back when the map is left and re-entered",
   "grows back the moment you leave its map and come back" in note, note)
ck("...and which side lies past it, from the way the party faced",
   "past it is the EAST side" in note, note)
ck("...without saying where to go",
   not any(w in note.lower() for w in ("you should", "go east", "head east", "celadon")), note)
obs2 = {"map": {"id": "CERULEAN_CITY"}, "player": {"facing": "up"}}
ck("facing up reads as the NORTH side",
   "NORTH side" in e._cut_aftermath({"move": "CUT", "x": 19, "y": 28}, obs2))
ck("no facing, no side claimed",
   "side" not in e._cut_aftermath({"move": "CUT", "x": 1, "y": 1}, {"map": {"id": "X"}}))
ck("STRENGTH and SURF say nothing here",
   e._cut_aftermath({"move": "STRENGTH", "x": 1, "y": 1}, obs) == ""
   and e._cut_aftermath({"move": "SURF"}, obs) == "")

# the row's words, as the module holds them (the source splits the literal)
_tables = [v for v in vars(L).values() if isinstance(v, dict)
           and isinstance(v.get("recut"), str)]
recut = str(_tables[0]["recut"]) if _tables else ""
ck("the ledger's regrown-bush row states the engine's rule, not a reload",
   "grows back the moment you leave its map and come back" in recut
   and "game reloads" not in recut, recut)
src = (ROOT / "planner" / "executor.py").read_text()
ck("the cut's own result line carries it",
   "+ self._cut_aftermath(step, obs))" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
