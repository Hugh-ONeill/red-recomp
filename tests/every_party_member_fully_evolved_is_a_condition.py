#!/usr/bin/env python3
"""'every party member is fully evolved' is a condition a plan can be held
to, judged from the engine's own evolution table, and the upkeep author
knows the kind exists.

User, 2026-09-08: "it would be neat if towards the end it would have
something along the lines of 'all pokemon on the team are fully evolved'".
Until now the upkeep round's list of holdable states was levels, party
count, named species, type, dex count and a known move — evolution appeared
nowhere, so maintenance legs were level curves and catches. Now:
party_fully_evolved is judged from planner/engine_evolutions.txt (generated
by tools/gen_engine_evolutions.py from pokemon.lua); a TRADE evolution does
not count against a member, since no trade is available to this run; the
page names WHO still has a way to go and never WHICH way; the upkeep prompt
lists the kind and says an evolved form is a named species too.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
from executor import (pred_holds, fully_evolved, not_fully_evolved,   # noqa: E402
                      EVOLUTIONS, choose_battle_policy, Executor)
import author as A                                                    # noqa: E402

fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def party(*species):
    return {"mode": "overworld", "party": [{"species": s, "level": 30} for s in species], "bag": {}}


ck("the evolution table is loaded from the engine's data", len(EVOLUTIONS) > 50 and ("ITEM", "NIDOQUEEN", "MOON_STONE") in EVOLUTIONS.get("NIDORINA", []))
ck("a final form is fully evolved", fully_evolved("CHARIZARD") and fully_evolved("GYARADOS"))
ck("a stone evolver is not", not fully_evolved("NIDORINA") and not fully_evolved("EEVEE") and not fully_evolved("GLOOM"))
ck("a level evolver is not", not fully_evolved("DODUO"))
ck("a trade-only evolver counts as done here", fully_evolved("KADABRA") and fully_evolved("HAUNTER"))
ck("the predicate holds for an all-final party", pred_holds({"party_fully_evolved": True}, party("CHARIZARD", "GYARADOS", "ALAKAZAM")))
ck("...and not while anyone has a way to go", not pred_holds({"party_fully_evolved": True}, party("CHARIZARD", "NIDORINA")))
ck("...naming who, in party order", not_fully_evolved(party("GYARADOS", "NIDORINA", "GLOOM", "CHARIZARD", "EEVEE", "DODUO")) == ["NIDORINA", "GLOOM", "EEVEE", "DODUO"])
ck("the target key carries it", Executor._target_key({"done_when": {"party_fully_evolved": True}}) == "party_fully_evolved:True")
ck("its wild battles are fought, not fled", choose_battle_policy({"done_when": {"party_fully_evolved": True}})[0] == "default")
ck("the author may write it", not any("party_fully_evolved" in p for p in A.validate({"goal": "g", "subgoals": [{"id": "evolve_all", "goal_text": "Evolve every party member", "done_when": {"party_fully_evolved": True}, "escalation_rounds": 4}]})))
ck("...typed as a bool", A._SHAPES.get("party_fully_evolved") == "bool")
ck("the upkeep prompt lists the kind", "every party member is fully evolved (a state for late in the run)" in A.OUTLINE_UPKEEP_SYS)
ck("...says an evolved form is a named species too", "including\n    the EVOLVED form of one you already have" in A.OUTLINE_UPKEEP_SYS)
ck("...and names evolving beside catching and training", "the catching, the training, the evolving and the type\ncoverage" in A.OUTLINE_UPKEEP_SYS)
ex = (ROOT / "planner" / "executor.py").read_text()
ck("the page head names who is not yet there and never which way", 'NOT YET THERE: {\', \'.join(_left)}' in ex and "Which member takes which is " in ex)
ck("the leg sits before Victory Road in the hand outline", (ROOT / "plans" / "outline.perfect.txt").read_text().index("every party member is fully evolved") < (ROOT / "plans" / "outline.perfect.txt").read_text().index("Navigate the Victory Road"))
ck("...and in the upkeep list", "every party member is fully evolved" in (ROOT / "plans" / "outline.perfect.upkeep").read_text())
sys.exit(1 if fails else 0)
