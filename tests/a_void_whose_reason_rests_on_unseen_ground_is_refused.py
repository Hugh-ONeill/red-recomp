#!/usr/bin/env python3
"""A VOID whose reason rests on ground never stood in is refused (2026-09-04).

The third void of a Scope leg in one day came with a plan that aimed only at
walked ground (Celadon and its Mansion), so the guard on the plan's places was
silent — and the reason was "it is obtained from the President of Silph Co. in
Saffron City": a building the run has never stood in, whose one known door its
own record shows held by a Rocket. What is in a place never entered is not in
the record either way. The other answers stay the model's, and a reason about
walked ground is still its call.

Synthetic: plans and a walked record in a temp dir, no model."""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
GOAL = "Obtain the Silph Scope from Celadon City"
with tempfile.TemporaryDirectory() as d:
    d = Path(d); (d / "plans").mkdir()
    (d / "plans" / "leg_27_obtain_the_silph_scope_from_celadon_city.v2.json").write_text(json.dumps(
        {"goal": GOAL, "subgoals": [{"id": "travel_to_celadon", "done_when": {"map": "CELADON_CITY"}},
                                    {"id": "enter_celadon_mansion", "done_when": {"map": "CELADON_MANSION_1F"}},
                                    {"id": "reach_mansion_roof", "done_when": {"map": "CELADON_MANSION_ROOF"}},
                                    {"id": "obtain_silph_scope", "done_when": {"has_item": {"SILPH_SCOPE": 1}}}]}))
    observed = d / "explored.json"
    observed.write_text(json.dumps({"visits": {"CELADON_CITY|2,1": 30, "CELADON_MANSION_1F|4,0": 3, "CELADON_MANSION_ROOF|6,1": 1,
                                               "SAFFRON_CITY|12,0": 10, "LAVENDER_TOWN|6,0": 60, "MR_FUJIS_HOUSE|2,1": 4}}))
    ck("a plan on walked ground alone does not refuse the void", A.void_refused_why(GOAL, observed, d / "plans") == "")
    why = "The Silph Scope is not obtainable in Celadon City; it is obtained from the President of Silph Co. in Saffron City."
    got = A.void_refused_why(GOAL, observed, d / "plans", why=why)
    ck("...but a reason resting on Silph Co, never stood in, refuses it", "SILPH_CO" in got and "never stood in" in got, got)
    ck("...and says the wording stands", "wording stands" in got, got)
    got2 = A.void_refused_why(GOAL, observed, d / "plans", why="The Silph Scope is obtained from Mr. Fuji in Lavender Town, not from Celadon City.")
    ck("a reason about places the run has walked is left to the model", got2 == "", got2)
    ck("no reason, no verdict from this branch", A.void_refused_why(GOAL, observed, d / "plans", why="") == "")
    ck("a reason naming no map the engine knows is left to the model",
       A.void_refused_why(GOAL, observed, d / "plans", why="There is no such item in this game.") == "")
    got3 = A.void_refused_why(GOAL, d / "none.json", d / "plans", why=why)
    ck("with no walked record at all, the plan-ground rule speaks first, as before", "aims at" in got3, got3)
# ...but a reason that names events the game itself recorded is not a guess
import os as _os
with tempfile.TemporaryDirectory() as d2:
    d2 = Path(d2); (d2 / "plans").mkdir(); (d2 / "run").mkdir()
    (d2 / "plans" / "leg_27_x.json").write_text(json.dumps(
        {"goal": GOAL, "subgoals": [{"id": "s", "done_when": {"map": "ROUTE_17"}}]}))
    (d2 / "explored.json").write_text(json.dumps({"visits": {"CELADON_CITY|2,1": 3}}))
    (d2 / "run/obs.json").write_text(json.dumps(
        {"flags": ["EVENT_BEAT_ROUTE12_SNORLAX", "EVENT_BEAT_ROUTE16_SNORLAX"]}))
    _cwd = _os.getcwd()
    try:
        _os.chdir(d2)
        _fired = ("The run has already triggered EVENT_BEAT_ROUTE16_SNORLAX and "
                  "EVENT_BEAT_ROUTE12_SNORLAX, meaning both Snorlax have been woken.")
        ck("a reason naming flags that actually fired is not refused",
           A.void_refused_why(GOAL, d2 / "explored.json", d2 / "plans", why=_fired) == "")
        ck("...while a flag that never fired is still no evidence",
           A.void_refused_why(GOAL, d2 / "explored.json", d2 / "plans",
                              why="EVENT_BEAT_BLAINE means it is done.") != "")
    finally:
        _os.chdir(_cwd)

src = (ROOT / "planner" / "author.py").read_text()
ck("the wording rung hands the model's reason to the guard", "_no = void_refused_why(goal, observed, why=why)" in src)
bad = [c for c in checks if not c[1]]
for n, ok, dd in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(dd)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
