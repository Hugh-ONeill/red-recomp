#!/usr/bin/env python3
"""A step whose condition already holds is not escalated.

Steps before the resume point were honoured when their condition held; a step
reached in the ordinary flow went straight to the model and was checked only
after its first round's ops. "clear_tower_ghost" — done_when the tower
rival's flag, fired hours earlier on 2F — cost a round of inference and a
page that said the flag was still to do, and the model wrote "I need to reach
the top floor of the Pokemon Tower to defeat the Rival" (2026-09-04; user:
"but the rival is already beaten"). A condition that already holds is a step
already done, at entry.

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
e = object.__new__(E.Executor)
e.settle = lambda: {"mode": "overworld", "flags": ["EVENT_BEAT_POKEMON_TOWER_RIVAL"],
                    "map": {"id": "CELADON_MART_1F", "region": "1,1"}, "bag": {"POTION": 2}}
ck("a fired flag holds at entry",
   e._already_holds({"id": "clear_tower_ghost", "done_when": {"flag": "EVENT_BEAT_POKEMON_TOWER_RIVAL"}}))
ck("a flag not yet fired does not",
   not e._already_holds({"id": "x", "done_when": {"flag": "EVENT_GOT_POKE_FLUTE"}}))
ck("the map you stand on holds", e._already_holds({"id": "y", "done_when": {"map": "CELADON_MART_1F"}}))
ck("a map you do not stand on does not", not e._already_holds({"id": "y", "done_when": {"map": "LAVENDER_TOWN"}}))
ck("an item in the bag holds", e._already_holds({"id": "z", "done_when": {"has_item": {"POTION": 1}}}))
ck("no condition, nothing to honour", not e._already_holds({"id": "q"}) and not e._already_holds({"id": "q", "done_when": {}}))
src = (ROOT / "planner" / "executor.py").read_text()
ck("the step entry honours it before replay or escalation",
   src.index("if self._already_holds(sg):") < src.index('ok = self.run_subgoal(sg) if sg.get("macro") else False')
   and 'self.log("subgoal_prior_done", subgoal=sg["id"], when="entry")' in src)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
