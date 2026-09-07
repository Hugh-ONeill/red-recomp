#!/usr/bin/env python3
"""A bush on a building's door is cleared by the party's own move, not by a
witnessed deed.

Run 16, 2026-09-07: Vermilion Gym's door record read "12,19 (CUT_TREE is
standing there)", and the held-building rule refused every Surge plan, ten
rounds over two authorings, for lacking "the deed that moves them" — while
Gloom knew CUT. Cutting a bush sets no event; walking through is its only
witness. Now: with the move known the step stands; without it the refusal
names the deed, a step ending on knows_move.
"""
import json, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

rec = {"visits": {"VERMILION_CITY|18,0": 3},
       "door_dests": {"VERMILION_CITY": {"12,19": "VERMILION_GYM"}},
       "shut_doors": {"VERMILION_CITY|18,0": ["12,19 (CUT_TREE is standing there)"]}}
tmp = Path(tempfile.mkdtemp()) / "explored.json"; tmp.write_text(json.dumps(rec))
plan = {"subgoals": [{"id": "enter_vermilion_gym", "goal_text": "Enter the gym", "done_when": {"map": "VERMILION_GYM"}},
                     {"id": "beat_surge", "goal_text": "Defeat Lt. Surge", "done_when": {"badge": "THUNDERBADGE"}}]}
knows = [{"species": "GLOOM", "moves": [{"id": "ABSORB"}, {"id": "CUT"}]}]
lacks = [{"species": "GLOOM", "moves": [{"id": "ABSORB"}, {"id": "BIDE"}]}]
ck("with CUT known, entering the bush-held gym is a plain step",
   A.held_step_problems(plan, observed=str(tmp), party=knows) == [], A.held_step_problems(plan, observed=str(tmp), party=knows))
p2 = A.held_step_problems(plan, observed=str(tmp), party=lacks)
ck("without it, the refusal names the move as the deed",
   len(p2) == 1 and "a CUT_TREE stands on its door" in p2[0] and '{"knows_move": "CUT"}' in p2[0], p2)
rec2 = dict(rec); rec2["shut_doors"] = {"VERMILION_CITY|18,0": ["12,19 (SAFFRONCITY_ROCKET8 is standing there)"]}
tmp2 = tmp.with_name("e2.json"); tmp2.write_text(json.dumps(rec2))
p3 = A.held_step_problems(plan, observed=str(tmp2), party=knows)
ck("a person on the door is still a guard, move or no move",
   len(p3) == 1 and "the deed that moves them" in p3[0], p3)
ck("the party reader sees the status screen's moves",
   A._party_knows("CUT", knows) and not A._party_knows("CUT", lacks) and not A._party_knows("CUT", []))
ck("the live record: someone knows CUT now", A._party_knows("CUT"))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:400])
sys.exit(1 if bad else 0)
