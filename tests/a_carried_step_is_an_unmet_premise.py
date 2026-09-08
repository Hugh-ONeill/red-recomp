#!/usr/bin/env python3
"""An earlier step carried unmet is said as an unmet premise under the steps
written after it.

Run 16, 2026-09-07, "Receive the BIKE_VOUCHER from the Pokemon Fan Club
chairman in Vermilion City": the first step, travel_to_vermilion, failed and
was carried; the steps after it were written for someone standing in
Vermilion, and the run hunted the Fan Club through Lavender and Celadon for
thirteen rounds. The carry is deliberate; the silence about it was not. The
prompt now says which step was carried, what it asked for, and where the
party actually stands.
"""
import sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

plan = {"subgoals": [{"id": "travel_to_vermilion", "done_when": {"map": "VERMILION_CITY"}},
                     {"id": "enter_fan_club", "done_when": {"map": "POKEMON_FAN_CLUB"}},
                     {"id": "get_bike_voucher", "done_when": {"has_item": {"BIKE_VOUCHER": 1}}}]}
fake = types.SimpleNamespace(plan=plan, _carried_ids=["travel_to_vermilion"], _where=lambda o: "LAVENDER_TOWN|6,0")
obs = {"map": {"id": "LAVENDER_TOWN"}}
note = E.Executor._carried_premise_note(fake, plan["subgoals"][1], obs)
ck("a later step is told the carried step's place was not reached and where the party stands",
   "PREMISE UNMET" in note and "travel_to_vermilion asked to be in VERMILION_CITY and was NOT achieved" in note
   and "you stand in LAVENDER_TOWN" in note and "written for someone standing in VERMILION_CITY" in note, note)
ck("the carried step itself gets no note about itself",
   E.Executor._carried_premise_note(fake, plan["subgoals"][0], obs) == "")
fake2 = types.SimpleNamespace(plan=plan, _carried_ids=[], _where=lambda o: "LAVENDER_TOWN|6,0")
ck("nothing is said when nothing was carried", E.Executor._carried_premise_note(fake2, plan["subgoals"][1], obs) == "")
ck("...nor when the party did reach that place after all",
   E.Executor._carried_premise_note(fake, plan["subgoals"][1], {"map": {"id": "VERMILION_CITY"}}) == "")
ck("the escalation prompt carries the note under DONE_WHEN",
   'f"{self._words_vs_condition(goal, done, obs)}"\n                    f"{self._carried_premise_note(sg, obs)}"' in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:300])
sys.exit(1 if bad else 0)
