#!/usr/bin/env python3
"""A condition on the PC's storage screen is refused, and a deposit has a
witness of its own.

Run 16, leg 32 (2026-09-08): the review wrote "deposit_pokemon" with
done_when {"screen":"BoxMenu"}. pc_deposit drives the box and BACKS OUT, and
`menu` refuses to enter storage by index, so no op leaves a BoxMenu on
screen — the condition can never be true when it is tested. The run
deposited DODUO in round 3, the step stayed open, and it kept depositing:
NIDORINA, then EEVEE, ten rounds down to a party of two. The author's guard
listed the PC's screens as the ones an op leaves open; that was true before
the pc_* ops existed. Now those screens are refused like the bag's, and
{"pc_holds":N} says what a deposit changes — party_size is a floor and could
not.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import author as A                                            # noqa: E402
from executor import pred_holds                               # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


plan = {"goal": "a party Pokemon knows SURF", "subgoals": [
    {"id": "deposit_pokemon", "goal_text": "Deposit a Pokemon into the PC",
     "done_when": {"screen": "BoxMenu"}, "escalation_rounds": 4}]}
probs = A.validate(plan)
ck("screen BoxMenu is refused", any("BoxMenu" in p and "inside of one op" in p for p in probs), probs)
ck("...and the refusal names the deposit's own witness", any("pc_holds" in p for p in probs), probs)
plan2 = {"goal": "store the fossil", "subgoals": [
    {"id": "store", "goal_text": "Store the DOME_FOSSIL in the PC",
     "done_when": {"screen": "PlayerPC"}, "escalation_rounds": 4}]}
probs2 = A.validate(plan2)
ck("screen PlayerPC is refused too", any("PlayerPC" in p and "inside of one op" in p for p in probs2), probs2)
plan3 = {"goal": "a party Pokemon knows SURF", "subgoals": [
    {"id": "deposit_pokemon", "goal_text": "Deposit a Pokemon into the PC",
     "done_when": {"pc_holds": 1}, "escalation_rounds": 4}]}
probs3 = A.validate(plan3)
ck("pc_holds is a condition the author may write", not any("pc_holds" in p for p in probs3), probs3)
ck("...typed as an int", A._SHAPES.get("pc_holds") == "int")
ck("the screen predicate no longer advertises the PC's screens as its example",
   "for the Pokemon storage in a PC" not in A.PREDICATES["screen"]
   and "never true" in A.PREDICATES["screen"])

# the executor judges pc_holds from the box's own list
empty = {"mode": "overworld", "party": [{"species": "GLOOM"}], "pc_mons": []}
one = {"mode": "overworld", "party": [{"species": "GLOOM"}],
       "pc_mons": [{"species": "DODUO", "box": 1, "index": 1}]}
ck("pc_holds 1 is false of an empty box", not pred_holds({"pc_holds": 1}, empty))
ck("pc_holds 1 is true once one is stored", pred_holds({"pc_holds": 1}, one))
ck("pc_holds 2 is false with one stored", not pred_holds({"pc_holds": 2}, one))
sys.exit(1 if fails else 0)
