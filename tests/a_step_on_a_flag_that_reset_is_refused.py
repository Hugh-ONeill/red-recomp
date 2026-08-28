#!/usr/bin/env python3
"""The author may not write a step waiting on a flag that fired and is
not set now, and its observed block says so beside the flag.

Victory Road, 2026-08-28: twelve rewrites of "Navigate the Victory Road"
opened on EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH, fired on 1F and cleared
on leaving it; the observed block said only "fired in VICTORY_ROAD_1F|5,9".
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A          # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
F = "EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH"
A.fired_flags = lambda: [F, "EVENT_BEAT_VICTORY_ROAD_1_TRAINER_0"]
A._flag_site = lambda f: "VICTORY_ROAD_1F|5,9" if f == F else ""
A._live_flags = lambda: {"EVENT_BEAT_VICTORY_ROAD_1_TRAINER_0"}
plan = {"goal": "Navigate the Victory Road", "subgoals": [
    {"id": "solve_1f_puzzle", "done_when": {"flag": F}, "steps": []},
    {"id": "reach_2f", "done_when": {"map": "VICTORY_ROAD_2F"}, "steps": []}]}
probs = " || ".join(A.validate(plan))
ck("a FIRST step on a fired-and-cleared flag is refused",
   "solve_1f_puzzle" in probs and "fired earlier in this run" in probs and "in VICTORY_ROAD_1F|5,9" in probs
   and "NOT set now" in probs)
ck("...with the boulder-switch rule", "kept only while the boulder sits on the switch" in probs)
ck("...and told what to end on instead", "a map you could not stand in before" in probs)
A._live_flags = lambda: {F, "EVENT_BEAT_VICTORY_ROAD_1_TRAINER_0"}
probs2 = " || ".join(A.validate(plan))
ck("a flag still SET is not that problem (the last-subgoal rule is another matter)", "NOT set now" not in probs2)
A._live_flags = lambda: None
ck("with no snapshot at all, nothing is claimed", "NOT set now" not in " || ".join(A.validate(plan)))
ck("the observed row says it beside the flag", "NOT set now" in A._fired_row_note(F, set())
   and "kept only while" in A._fired_row_note(F, set()))
ck("...and nothing beside a flag still set", A._fired_row_note(F, {F}) == "")
ck("...and no rule for a plain event", "kept only while" not in A._fired_row_note("EVENT_GOT_TM34", set())
   and "NOT set now" in A._fired_row_note("EVENT_GOT_TM34", set()))
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
