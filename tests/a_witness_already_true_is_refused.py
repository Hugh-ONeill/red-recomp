#!/usr/bin/env python3
"""A plan whose objective is true before it starts is refused at authoring
(2026-09-04).

The bag leg's plan ended on {"has_item":{"POTION":3}} — meant as "sold one,
three left", true with four in the bag — so the executor's objective-met-early
rule finished the plan at step one and check-done found the bag still full.
Twice. The chain caught it afterwards, at the cost of both attempts. Now the
author and the review evaluate the objective's witness against the current
observation and hand the same-round feedback back: write a condition only the
deed makes true. Silent whenever the witness cannot be read off the screen.

Synthetic: a plan and an observation, no model."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

OBS = {"mode": "overworld", "bag": {"POTION": 4, "REPEL": 2, "LIFT_KEY": 1},
       "flags": ["EVENT_FOUND_ROCKET_HIDEOUT"], "badges": ["BOULDERBADGE"], "map": {"id": "ROCKET_HIDEOUT_B4F"}}
plan = {"goal": "Clear space in the bag", "subgoals": [
    {"id": "go_to_saffron_mart", "done_when": {"map": "SAFFRON_MART"}},
    {"id": "sell_potion", "done_when": {"has_item": {"POTION": 3}}}]}
probs = A.witness_already_true_problems(plan, OBS)
ck("the bag leg's witness, true with four Potions, is a problem", len(probs) == 1 and "ALREADY HOLDS" in probs[0], probs)
ck("...that names the other-direction predicates", "lacks_item" in probs[0] and "bag_kinds_below" in probs[0], probs)
plan2 = {"subgoals": [{"id": "free_a_slot", "done_when": {"bag_kinds_below": 3}}]}
ck("a witness the deed makes true passes", A.witness_already_true_problems(plan2, OBS) == [])
plan3 = {"subgoals": [{"id": "x", "done_when": {"lacks_item": ["REPEL"]}}]}
ck("lacks_item on a held kind passes", A.witness_already_true_problems(plan3, OBS) == [])
ck("...and on a kind not held is a problem", A.witness_already_true_problems({"subgoals": [{"id": "x", "done_when": {"lacks_item": "NUGGET"}}]}, OBS) != [])
ck("an objective on a flag already set is a problem", A.witness_already_true_problems({"subgoals": [{"id": "x", "done_when": {"flag": "EVENT_FOUND_ROCKET_HIDEOUT"}}]}, OBS) != [])
ck("...a flag not set passes", A.witness_already_true_problems({"subgoals": [{"id": "x", "done_when": {"flag": "EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI"}}]}, OBS) == [])
ck("a map the run stands on is a problem", A.witness_already_true_problems({"subgoals": [{"id": "x", "done_when": {"map": "ROCKET_HIDEOUT_B4F"}}]}, OBS) != [])
hidden = dict(OBS); hidden["mode"] = "dialog"; hidden["map"] = None
ck("a bag behind a box is unreadable: silent", A.witness_already_true_problems(plan, hidden) == [])
ck("a map behind a box is unreadable: silent", A.witness_already_true_problems({"subgoals": [{"id": "x", "done_when": {"map": "SAFFRON_MART"}}]}, hidden) == [])
ck("an unknown key is left to the model", A.witness_already_true_problems({"subgoals": [{"id": "x", "done_when": {"party_healthy": True}}]}, OBS) == [])
ck("no observation, no verdict", A.witness_already_true_problems(plan, {}) == [])
ck("any_of: one true branch is true", A.witness_holds_now({"any_of": [{"flag": "NOPE"}, {"has_item": {"POTION": 1}}]}, OBS) is True)
ck("any_of: an unreadable branch and no true one is unknown", A.witness_holds_now({"any_of": [{"screen": "ShopMenu"}, {"flag": "NOPE"}]}, OBS) is None)
ck("the vocabulary carries both predicates", "lacks_item" in A.PREDICATES and "bag_kinds_below" in A.PREDICATES and "lacks_item" in A.VALID_KEYS)
ok_plan = {"goal": "g", "subgoals": [{"id": "a", "goal_text": "free a slot", "done_when": {"bag_kinds_below": 20}},
                                     {"id": "b", "goal_text": "sell", "done_when": {"lacks_item": ["REPEL"]}}]}
v = A.validate(ok_plan)
ck("validate accepts well-formed uses", not [p for p in v if "bag_kinds_below" in p or "lacks_item" in p], v)
bad_plan = {"goal": "g", "subgoals": [{"id": "a", "goal_text": "x", "done_when": {"bag_kinds_below": "lots"}},
                                      {"id": "b", "goal_text": "y", "done_when": {"lacks_item": 7}}]}
v2 = A.validate(bad_plan)
ck("...and rejects bad shapes", any("bag_kinds_below" in p for p in v2) and any("lacks_item" in p for p in v2), v2)
src = (ROOT / "planner" / "author.py").read_text()
ck("the author asks it in the same round as validation", "probs = validate(plan) or witness_already_true_problems(plan)" in src)
ck("...and so does the review", "probs = validate(revised) or witness_already_true_problems(revised)" in src)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
