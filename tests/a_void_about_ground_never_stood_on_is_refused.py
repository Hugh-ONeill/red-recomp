#!/usr/bin/env python3
"""A void about ground never stood on is refused.

VOID is the model's verdict that a sentence describes nothing that is there:
the phantom HM08, the Pokemon to retrieve from a mart. It was given twice in
one day about the Silph Scope, in opposite directions — "obtained from the
president of Silph Co. in Saffron", then "obtained from Mr. Fuji in Lavender
Town, not from Celadon City" — each time striking a leg whose own fresh plan
aimed at GAME_CORNER and ROCKET_HIDEOUT, maps the run had never stood in
(2026-09-04). Nothing in the record can say what is NOT in a place never
entered; same rule as the done-judge's _never_stood_in. The other answers
(stands, reword, done under another name) stay the model's.

Synthetic: a plans dir and a walked record in a temp dir, no model.
"""
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
GOAL = "Obtain the Silph Scope from Celadon City"

with tempfile.TemporaryDirectory() as d:
    d = Path(d); (d / "plans").mkdir()
    (d / "plans" / "leg_27_obtain_the_silph_scope_from_celadon_city.json").write_text(json.dumps(
        {"goal": GOAL, "subgoals": [{"id": "go_to_celadon", "done_when": {"map": "CELADON_CITY"}},
                                    {"id": "enter_game_corner", "done_when": {"map": "GAME_CORNER"}}]}))
    (d / "plans" / "leg_27_obtain_the_silph_scope_from_celadon_city.v1.json").write_text(json.dumps(
        {"goal": GOAL, "subgoals": [{"id": "exit_tower", "done_when": {"map": "LAVENDER_TOWN"}},
                                    {"id": "travel_to_celadon", "done_when": {"map": "CELADON_CITY"}},
                                    {"id": "enter_game_corner", "done_when": {"map": "GAME_CORNER"}},
                                    {"id": "enter_rocket_hideout", "done_when": {"map": "ROCKET_HIDEOUT_B1F"}},
                                    {"id": "descend_to_b4f", "done_when": {"map": "ROCKET_HIDEOUT_B4F"}},
                                    {"id": "defeat_rocket_boss", "done_when": {"has_item": {"SILPH_SCOPE": 1}}}]}))
    (d / "plans" / "leg_03_other.json").write_text(json.dumps({"goal": "Reach Pewter City", "subgoals": [{"id": "x", "done_when": {"map": "PEWTER_CITY"}}]}))
    observed = d / "explored.json"
    observed.write_text(json.dumps({"visits": {"LAVENDER_TOWN|6,0": 60, "CELADON_CITY|2,1": 3}}))

    best = A.plan_path_for(GOAL, d / "plans")
    ck("the leg's highest-versioned plan is found by its goal", best is not None and best.name.endswith(".v1.json"), best)
    ck("a doubt appended to the goal does not hide it",
       A.plan_path_for(GOAL + " (a doubt you recorded when outlining: x)", d / "plans") == best)
    ck("another leg's plan is never taken", A.plan_path_for("Reach Viridian City", d / "plans") is None)

    why = A.void_refused_why(GOAL, observed, d / "plans")
    ck("a VOID of a leg whose plan aims at ground never stood in is refused",
       "GAME_CORNER" in why and "ROCKET_HIDEOUT_B1F" in why and "never stood in" in why, why)
    ck("...and Celadon, stood in, is not among the reasons", "CELADON_CITY" not in why.split("aims at")[1].split("—")[0])
    ck("...and it does not say where the thing is", "Rocket" not in why.replace("ROCKET_HIDEOUT", ""))
    observed.write_text(json.dumps({"visits": {"LAVENDER_TOWN|6,0": 60, "CELADON_CITY|2,1": 3, "GAME_CORNER|1,1": 2,
                                                "ROCKET_HIDEOUT_B1F|1,1": 1, "ROCKET_HIDEOUT_B4F|1,1": 1}}))
    ck("once every aimed-at map has been stood in, the VOID is the model's to give",
       A.void_refused_why(GOAL, observed, d / "plans") == "")
    ck("a leg with no plan yet is the model's to void", A.void_refused_why("Reach Viridian City", observed, d / "plans") == "")

src = (ROOT / "planner" / "author.py").read_text()
ck("the wording rung asks before it accepts a VOID",
   '_no = void_refused_why(goal, observed, why=why)' in src
   and src.index('_no = void_refused_why(goal, observed, why=why)') < src.index('WORDING_SAYS_VOID[0] = True'))
ck("...and says why, with the model's own reason kept", '[wording] VOID refused ({why}): {_no}' in src)

# --- a void undoes the insert that produced the leg ---
with tempfile.TemporaryDirectory() as d2:
    ins = Path(d2) / "outline_inserts"
    ins.write_text("LEG=Cleanse the Pokemon Tower|Speak with Mr. Fuji\n"
                   "LEG=Retrieve the Pokemon Flute from Mr. Fuji|Obtain the Silph Scope from Celadon City\n")
    freed = A.refund_insert_for("Obtain the Silph Scope from Celadon City", ins)
    ck("voiding an inserted leg refunds the ask to the leg it was inserted for",
       freed == ["Retrieve the Pokemon Flute from Mr. Fuji"], freed)
    ck("...and the other rows stand", ins.read_text() == "LEG=Cleanse the Pokemon Tower|Speak with Mr. Fuji\n")
    ck("voiding a leg nobody inserted refunds nothing", A.refund_insert_for("Reach Fuchsia City", ins) == [])
src2 = (ROOT / "planner" / "author.py").read_text()
ck("the wording rung refunds on the VOID it accepts", "for _dep in refund_insert_for(goal):" in src2)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
