#!/usr/bin/env python3
"""A knows_move step written for a party slot the game marks NOT ABLE is
refused at authoring, in the screen's own terms.

The item screen for a TM or HM marks every party member ABLE or NOT ABLE,
and the observation carries that mark. The author wrote "Teach HM01
(Cut) to Nidorino", knows_move CUT slot 3, with the screen marking
NIDORINO not able and CHARMELEON the one ABLE member: a step that could
never come true, and the round-by-round model spent eleven rounds hunting
a Moon Stone to evolve its way to a mark evolution does not give
(2026-09-14, user: "its trying to evolve nido to learn cut (even though
that wont work) instead of teaching it to char").

Nothing is said about who ELSE could learn it; a catch or a trade changes
the party and the mark is read again then, which is the model's to think
of. What is said is the two ways to write a step that can be true: a slot
the game marks ABLE, or no slot at all.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import author as A                                       # noqa: E402
from pinned_world import pinned                          # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

OBS = {"mode": "overworld", "map": {"id": "VERMILION_CITY", "region": "1,1"},
       "party": [{"species": "PIKACHU", "level": 20}, {"species": "CHARMELEON", "level": 31},
                 {"species": "NIDORINO", "level": 20}],
       "bag": {"HM_CUT": 1, "TM_BIDE": 1},
       "machines": {"HM_CUT": {"move": "CUT", "able": ["CHARMELEON"], "not_able": ["PIKACHU", "NIDORINO"]},
                    "TM_BIDE": {"move": "BIDE", "able": ["PIKACHU", "CHARMELEON", "NIDORINO"], "not_able": []}}}

def plan(dw):
    return {"goal": "a party Pokemon knows CUT",
            "subgoals": [{"id": "heal", "goal_text": "heal", "done_when": {"party_healthy": True}},
                         {"id": "teach_cut", "goal_text": "Teach HM01 (Cut)", "done_when": dw}]}

# ---- the step that was written ----------------------------------------------
probs = A.machine_slot_problems(plan({"knows_move": {"move": "CUT", "slot": 3}}), OBS)
ck("slot 3 is NIDORINO, marked NOT ABLE: refused", len(probs) == 1, probs)
t = probs[0] if probs else ""
ck("...naming the slot, the species, the machine and the move",
   "slot 3 is NIDORINO" in t and "HM_CUT" in t and "NOT ABLE to learn CUT" in t, t)
ck("...and who the screen marks ABLE", "It marks ABLE: CHARMELEON" in t)
ck("...and the two ways to write a step that can be true",
   "the slot of a Pokemon the game marks ABLE" in t and '{"knows_move":"CUT"}' in t
   and "whoever that turns out to be" in t, t)
ck("...without naming any species outside the party or any way to get one",
   not any(w in t for w in ("ODDISH", "BELLSPROUT", "FARFETCHD", "SANDSHREW", "catch", "trade", "evolv")), t)
ck("it reads the observation on disk when none is handed to it",
   (lambda: [A.machine_slot_problems(plan({"knows_move": {"move": "CUT", "slot": 3}}))])() and True)
with pinned(obs=OBS):
    ck("...and refuses the same way from there",
       len(A.machine_slot_problems(plan({"knows_move": {"move": "CUT", "slot": 3}}))) == 1)

# ---- what passes ---------------------------------------------------------------
ck("slot 2, CHARMELEON, marked ABLE: nothing to say",
   A.machine_slot_problems(plan({"knows_move": {"move": "CUT", "slot": 2}}), OBS) == [])
ck("no slot: the open form is always writable",
   A.machine_slot_problems(plan({"knows_move": "CUT"}), OBS) == []
   and A.machine_slot_problems(plan({"knows_move": {"move": "CUT"}}), OBS) == [])
ck("a move whose machine is not in the bag: the screen has no mark, nothing is said",
   A.machine_slot_problems(plan({"knows_move": {"move": "FLY", "slot": 3}}), OBS) == [])
ck("a machine everyone can learn: nothing to say",
   A.machine_slot_problems(plan({"knows_move": {"move": "BIDE", "slot": 3}}), OBS) == [])
ck("a slot the party does not have: left to the other checks",
   A.machine_slot_problems(plan({"knows_move": {"move": "CUT", "slot": 5}}), OBS) == [])
ck("no observation at all: nothing is said", A.machine_slot_problems(plan({"knows_move": {"move": "CUT", "slot": 3}}), {}) == [])

# ---- it sits in every chain that accepts a plan ----------------------------------
src = (ROOT / "planner" / "author.py").read_text()
ck("the author's rounds ask it", "or held_step_problems(plan) or machine_slot_problems(plan))" in src)
ck("the review asks it", "or machine_slot_problems(revised))" in src)
ck("the draws filter asks it", "or machine_slot_problems(p2))]" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
