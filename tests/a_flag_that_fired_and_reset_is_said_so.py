#!/usr/bin/env python3
"""A flag target that fired once and is not set now is said so, with the
boulder-switch reset rule when that is what it is.

Victory Road: EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH fired at 1F|5,9, the
run climbed to 2F, and the plan's step on that flag sent it back down
after an event the game clears on leaving the floor (2026-08-28, user:
"it's fired but it resets").
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import candidates as C        # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
ex = C.make()
ex.flag_sites = {"EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH": "VICTORY_ROAD_1F|5,9",
                 "EVENT_BEAT_VICTORY_ROAD_1_TRAINER_0": "VICTORY_ROAD_1F|14,0"}
obs = {"map": {"id": "VICTORY_ROAD_2F", "region": "1,5"}, "flags": ["EVENT_BEAT_VICTORY_ROAD_1_TRAINER_0"]}
sg = {"id": "solve_1f_puzzle", "done_when": {"flag": "EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH"}}
t = ex._fired_text(obs, sg)
ck("the target flag is said to have fired, and where", "HAS FIRED ONCE ALREADY — in VICTORY_ROAD_1F|5,9" in t)
ck("...and to be unset now", "it is NOT set now" in t)
ck("...with the boulder-switch reset rule, from another floor", "cannot be true from any other floor" in t)
ck("...and the contracts of skip and push, neither chosen for it", '"skip"' in t and '"push"' in t)
ck("the events still set are listed after it", "EVENT_BEAT_VICTORY_ROAD_1_TRAINER_0 (fired in" in t)
obs2 = dict(obs); obs2["flags"] = ["EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH"]
ck("a target flag that IS set gets no such note", "HAS FIRED ONCE ALREADY" not in ex._fired_text(obs2, sg))
sg2 = {"id": "x", "done_when": {"flag": "EVENT_NEVER_SEEN"}}
ck("a target flag that never fired gets none either", "HAS FIRED ONCE ALREADY" not in ex._fired_text(obs, sg2))
obs3 = {"map": {"id": "VICTORY_ROAD_1F", "region": "14,0", "objects": [
    {"kind": "boulder", "name": "B1", "x": 14, "y": 2}, {"kind": "boulder", "name": "B2", "x": 2, "y": 10}]}, "flags": []}
ex.boulder_start = {"VICTORY_ROAD_1F": ["14,2", "2,10"]}
t3 = ex._fired_text(obs3, sg)
ck("on the switch's own floor the note says the way is shut again and what sets it again",
   "HAS FIRED ONCE ALREADY" in t3 and "any other floor" not in t3 and "shut again now" in t3
   and "set again by a boulder on the switch" in t3)
ck("...and where the boulders stand against where they started",
   "stand where they stood when you first came in: (14,2), (2,10)" in t3)
ex.boulder_start = {"VICTORY_ROAD_1F": ["14,2", "5,15"]}
ck("...or that one has moved", "when you first came in they stood at (14,2), (5,15)" in ex._fired_text(obs3, sg))
ck("no inference about walked ground rides on it", "walked since" not in t3 and "walked through" not in t3)
src = (ROOT / "planner" / "executor.py").read_text()
ck("the note stands on the round-1 page too, not only in feedback",
   "memory += self._reset_flag_note(start, sg)" in src)
ck("...and is logged when rendered", 'self.log("reset_flag_note"' in src)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
