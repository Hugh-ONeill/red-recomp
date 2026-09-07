#!/usr/bin/env python3
"""A step that waits on a trainer's flag is told which place sets it.

Run 16, 2026-09-07: the inserted S.S. Anne leg's first step was named
clear_ss_anne_2f_rooms and ended on EVENT_BEAT_SS_ANNE_10_TRAINER_2, a B1F
cabin sailor's flag. All four 2F cabin trainers were already beaten, the
rival was beaten, the run stood in the captain's cabin and left it, then
took the 2F cabin doors 26 times looking for a fight that was on another
floor (user: "can we tell how often its visiting the same doors"). Two
readers now say what the flag means: the validator refuses a step whose
name and flag disagree about the floor and lists the events of the place
the name means; the executor prints, under DONE_WHEN, which place sets the
flag and how many of that place's trainer events are set.
"""
import sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A     # noqa: E402
import executor as E   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

probs = []
A._check_pred({"flag": "EVENT_BEAT_SS_ANNE_10_TRAINER_2"}, "subgoal[0]", "clear_ss_anne_2f_rooms", probs)
ck("the validator refuses a 2F step ended on a B1F cabin's flag", len(probs) == 1, probs)
ck("...naming where the flag is set", probs and "set by beating a trainer in SS_ANNE_B1F_ROOMS" in probs[0], probs)
ck("...and listing the 2F cabins' own events, verbatim",
   probs and all(f"EVENT_BEAT_SS_ANNE_9_TRAINER_{i}" in probs[0] for i in range(4)) and "SS_ANNE_2F_ROOMS" in probs[0], probs)
probs2 = []
A._check_pred({"flag": "EVENT_BEAT_SS_ANNE_10_TRAINER_2"}, "subgoal[0]", "clear_b1f_rooms", probs2)
ck("a step named for the right floor passes", probs2 == [], probs2)
probs3 = []
A._check_pred({"flag": "EVENT_BEAT_SS_ANNE_10_TRAINER_2"}, "subgoal[0]", "clear_trainers", probs3)
ck("a step naming no floor passes", probs3 == [], probs3)

fake = types.SimpleNamespace(_trainer_event_map=E.Executor._trainer_event_map)
obs = {"flags": [f"EVENT_BEAT_SS_ANNE_10_TRAINER_{i}" for i in (0, 1, 3, 4, 5)]}
w = E.Executor._condition_place_words(fake, "Defeat all trainers in the 2F rooms",
                                      {"flag": "EVENT_BEAT_SS_ANNE_10_TRAINER_2"}, obs)
ck("the executor says which place sets the flag",
   "EVENT_BEAT_SS_ANNE_10_TRAINER_2 is set by beating one particular trainer in SS_ANNE_B1F_ROOMS" in w, w)
ck("...how many of that place's trainer events are set, and this one's state",
   "6 trainer event(s), 5 already set, and this one is not" in w, w)
ck("...and that the step's words name another floor",
   "This step's words say 2F; the condition is set in SS_ANNE_B1F_ROOMS" in w, w)
w2 = E.Executor._condition_place_words(fake, "Clear the B1F cabins", {"flag": "EVENT_BEAT_SS_ANNE_10_TRAINER_2"}, obs)
ck("no disagreement is claimed when the floors agree", "words say" not in w2 and "set by beating" in w2, w2)
ck("a flag that is not a trainer's says nothing", E.Executor._condition_place_words(fake, "x", {"flag": "EVENT_GOT_HM01"}) == "")
src = (ROOT / "planner" / "executor.py").read_text()
ck("the prompt passes the observation so the counts are live",
   'f"{self._words_vs_condition(goal, done, obs)}"' in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:300])
sys.exit(1 if bad else 0)
