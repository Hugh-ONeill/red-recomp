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
ck("...and the op for a step that cannot come true as written", '"skip"' in t)
ck("the events still set are listed after it", "EVENT_BEAT_VICTORY_ROAD_1_TRAINER_0 (fired in" in t)
obs2 = dict(obs); obs2["flags"] = ["EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH"]
ck("a target flag that IS set gets no such note", "HAS FIRED ONCE ALREADY" not in ex._fired_text(obs2, sg))
sg2 = {"id": "x", "done_when": {"flag": "EVENT_NEVER_SEEN"}}
ck("a target flag that never fired gets none either", "HAS FIRED ONCE ALREADY" not in ex._fired_text(obs, sg2))
obs3 = {"map": {"id": "VICTORY_ROAD_1F", "region": "14,0"}, "flags": []}
t3 = ex._fired_text(obs3, sg)
ck("on the switch's own floor the note says what setting it again would take, and that its work is walked",
   "HAS FIRED ONCE ALREADY" in t3 and "any other floor" not in t3 and "putting a boulder back on the switch" in t3
   and "ground you have walked since" in t3)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
