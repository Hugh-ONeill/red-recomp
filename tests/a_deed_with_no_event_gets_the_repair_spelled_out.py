#!/usr/bin/env python3
"""A step ending on an event the game does not keep is told the two edits
that work, with the next step's condition quoted.

Run 16, 2026-09-07: "Defeat Lt. Surge" could not be planned. Every draft had
"cut the tree in front of the gym" ending on EVENT_CUT_VERMILION_GYM or
EVENT_CUT_GYM_TREE; each round the validator said the name was wrong and
listed kinds of witness in the abstract, and each round the author renamed
the event. The leg went to the ladder, which pulled the training leg ahead
of it. A cut tree sets no event in this game; the step after ("enter the
gym", {"map": "VERMILION_GYM"}) already witnesses it. Now the refusal says
so, mechanically: remove the step, or give it exactly that condition.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

plan = {"subgoals": [
    {"id": "go_to_gym", "goal_text": "Walk to the Vermilion gym", "done_when": {"map": "VERMILION_CITY"}},
    {"id": "cut_gym_tree", "goal_text": "Cut the tree in front of the gym", "done_when": {"flag": "EVENT_CUT_GYM_TREE"}},
    {"id": "enter_vermilion_gym", "goal_text": "Enter the gym", "done_when": {"map": "VERMILION_GYM"}},
    {"id": "beat_surge", "goal_text": "Defeat Lt. Surge", "done_when": {"badge": "THUNDERBADGE"}}]}
probs = A.validate(plan)
cut = [p for p in probs if "cut_gym_tree" in p and "is not an event this game defines" in p]
ck("the invented cut event is refused", len(cut) == 1, probs)
ck("...and told the game keeps no such event at all",
   cut and "The game keeps NO event for this: nothing in its list begins with EVENT_CUT_GYM" in cut[0], cut)
ck("...with the two edits that work", cut and "REMOVE subgoal[1] (cut_gym_tree)" in cut[0]
   and 'give subgoal[1] exactly the condition of the step after it: {"map": "VERMILION_GYM"}' in cut[0], cut)
ck("...and no further name-guessing", cut and "Do not spell another event name." in cut[0])
# a guess inside a real series keeps its list and gets no such clause
plan2 = {"subgoals": [{"id": "clear", "goal_text": "Beat the ship's trainers", "done_when": {"flag": "EVENT_BEAT_SS_ANNE_N_TRAINER_N"}},
                      {"id": "hm", "goal_text": "Get HM01", "done_when": {"has_item": {"HM_CUT": 1}}}]}
probs2 = A.validate(plan2)
ser = [p for p in probs2 if "is not an event this game defines" in p]
ck("a guess inside a real series still gets its members, not the removal clause",
   ser and "Did you mean" in ser[0] and "keeps NO event" not in ser[0], ser)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:400])
sys.exit(1 if bad else 0)
