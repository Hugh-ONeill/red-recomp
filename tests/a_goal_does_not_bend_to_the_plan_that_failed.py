#!/usr/bin/env python3
"""A restatement is refused when it names the very place this leg has just
failed to reach.

Leg 9 was "Retrieve the S.S. Ticket from Bill", which is right. Its plan
sent the party SOUTH to Vermilion, which is wrong, because Bill is north
of Cerulean, and the leg failed on travel_to_vermilion, enter_ss_anne and
reach_ss_anne_1f one after another. The wording rung then restated the
objective as "Retrieve the S.S. Ticket from the captain of the S.S.
Anne", on a flat and false claim about the game, and the new leg was
circular: the captain's room is on a ship you cannot board without the
ticket. A whole attempt of evidence said "not from here" and the answer
was to move the goal to where the plan had been heading (2026-09-14,
user: "*especially* it should not then, with a whole leg of evidence
saying 'this cant be done from this position', rewriting the goal to suit
the failed plan").

Mechanical and this-leg only: the targets of steps that ended without
success since this plan started, as the journal already records them,
against the words of the restatement. It says nothing about whether the
restatement is true, only that a place the leg has just proved it cannot
reach is not evidence for rewording the leg towards it.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                        # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

def journal(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for r in rows:
        f.write(json.dumps(r) + "\n")
    f.close()
    return f.name

LEG9 = [
    {"kind": "plan_start", "goal": "Retrieve the S.S. Ticket from Bill"},
    {"kind": "escalate_context", "subgoal": "travel_to_vermilion", "target": "map:VERMILION_CITY"},
    {"kind": "escalate_end", "subgoal": "travel_to_vermilion", "success": False},
    {"kind": "subgoal_failed_continuing", "subgoal": "travel_to_vermilion"},
    {"kind": "escalate_context", "subgoal": "enter_ss_anne", "target": "map:SS_ANNE_BOW"},
    {"kind": "escalate_end", "subgoal": "enter_ss_anne", "success": False},
    {"kind": "escalate_context", "subgoal": "talk_to_bill", "target": "item:S_S_TICKET"},
    {"kind": "escalate_end", "subgoal": "talk_to_bill", "success": False},
]
J = journal(LEG9)

ck("the reword that follows the failed plan is caught",
   A._reword_points_at_what_failed(
       "Retrieve the S.S. Ticket from the captain of the S.S. Anne", J) == "SS_ANNE")
ck("...through the prose's own punctuation, S.S. Anne for SS_ANNE",
   A._reword_points_at_what_failed("something on the S.S. Anne", J) == "SS_ANNE")
ck("...and a plainly named place too",
   A._reword_points_at_what_failed("Reach Vermilion City another way", J) == "VERMILION_CITY")
ck("the wording that was already there is untouched",
   A._reword_points_at_what_failed("Retrieve the S.S. Ticket from Bill", J) is None)
ck("a restatement about somewhere else entirely is untouched",
   A._reword_points_at_what_failed("Catch a PIKACHU in the Viridian Forest", J) is None)
ck("an ITEM target is not a place and cannot trigger it",
   A._reword_points_at_what_failed("Get the S_S_TICKET", J) is None)

# only this leg counts: the same failures behind an older plan_start do not
OLD = [{"kind": "plan_start", "goal": "old"},
       {"kind": "escalate_context", "subgoal": "x", "target": "map:SS_ANNE_BOW"},
       {"kind": "escalate_end", "subgoal": "x", "success": False},
       {"kind": "plan_start", "goal": "Retrieve the S.S. Ticket from Bill"},
       {"kind": "escalate_context", "subgoal": "y", "target": "map:ROUTE_25"},
       {"kind": "escalate_end", "subgoal": "y", "success": True}]
ck("a failure from an earlier plan is not this leg's evidence",
   A._reword_points_at_what_failed("board the S.S. Anne", journal(OLD)) is None)
ck("...and a step that SUCCEEDED is not a failure",
   A._reword_points_at_what_failed("walk Route 25", journal(OLD)) is None)

ck("no journal, no verdict", A._reword_points_at_what_failed("anything", None) is None
   and A._reword_points_at_what_failed("", J) is None)
ck("a journal that is not there says nothing",
   A._reword_points_at_what_failed("the S.S. Anne", "/nonexistent/x.jsonl") is None)

src = (ROOT / "planner" / "author.py").read_text()
ck("check_wording asks it before it asks anything of the model",
   "_at = _reword_points_at_what_failed(new, journal)" in src
   and src.index("_at = _reword_points_at_what_failed") < src.index("if check_already_done(new, start, model"))
ck("...and says why, and that the wording stands",
   "just failed trying to reach it" in src and "the wording stands" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
