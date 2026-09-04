#!/usr/bin/env python3
"""A step into a held building, with no deed before it, is refused (2026-09-04).

The Scope leg's rewrite, written on Hideout B4F with the LIFT_KEY in hand, was:
use the lift to leave, walk to Saffron, enter SILPH_CO_1F, reach 11F, take the
Scope from the President. Three rounds later the run stood at the Silph Co
door with SAFFRONCITY_ROCKET8 on the doorstep — as its own record already said
— having walked out of the one building that holds the Scope. The same record
that now refuses a pull behind a held door refuses a plan step into one,
unless an earlier step does a deed that could be what moves them.

Synthetic: a walked record and plans, no model."""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

REC = {"visits": {"SAFFRON_CITY|12,0": 10, "CELADON_CITY|2,1": 30, "ROCKET_HIDEOUT_B4F|17,1": 5},
       "door_dests": {"CELADON_CITY": {"12,27": "CELADON_GYM"}, "SAFFRON_CITY": {"18,21": "SILPH_CO_1F", "34,3": "SAFFRON_GYM", "26,3": "FIGHTING_DOJO"},
                      "GAME_CORNER": {"17,4": "ROCKET_HIDEOUT_B1F"}},
       "shut_doors": {"CELADON_CITY|2,1": ["12,27 (None is standing there)"], "SAFFRON_CITY|12,0": ["18,21 (SAFFRONCITY_ROCKET8 is standing there)",
                                            "34,3 (SAFFRONCITY_ROCKET3 is standing there)"]}}
SILPH = {"subgoals": [
    {"id": "exit_rocket_hideout", "done_when": {"map": "ROCKET_HIDEOUT_ELEVATOR"}},
    {"id": "reach_saffron_city", "done_when": {"map": "SAFFRON_CITY"}},
    {"id": "enter_silph_co", "done_when": {"map": "SILPH_CO_1F"}},
    {"id": "reach_silph_co_11f", "done_when": {"map": "SILPH_CO_11F"}},
    {"id": "obtain_silph_scope", "done_when": {"has_item": {"SILPH_SCOPE": 1}}}]}
with tempfile.TemporaryDirectory() as d:
    obs = Path(d) / "explored.json"; obs.write_text(json.dumps(REC))
    p = A.held_step_problems(SILPH, obs)
    ck("the Silph Co step is a problem, in the record's words",
       len(p) == 1 and "enter_silph_co" in p[0] and "SAFFRONCITY_ROCKET8 is standing there" in p[0], p)
    ck("...and the later floors, reached only through it, are not doubled up", len(p) == 1, p)
    ck("the lift step, into a map with no known door, is left alone", "exit_rocket_hideout" not in (p[0] if p else ""))
    after_deed = {"subgoals": [
        {"id": "rescue_fuji", "done_when": {"flag": "EVENT_RESCUED_MR_FUJI"}},
        {"id": "enter_silph_co", "done_when": {"map": "SILPH_CO_1F"}}]}
    ck("a step into the held building AFTER a deed is the model's call", A.held_step_problems(after_deed, obs) == [])
    gym = {"subgoals": [{"id": "gym", "done_when": {"area": "SAFFRON_GYM|0,0"}}]}
    ck("an area predicate is read the same way", A.held_step_problems(gym, obs) != [])
    gym = {"subgoals": [{"id": "gym", "done_when": {"map": "CELADON_GYM"}}]}
    ck("a door blocked by nobody — a bush's '(None is standing there)' — is not a held door", A.held_step_problems(gym, obs) == [], A.held_step_problems(gym, obs))
    dojo = {"subgoals": [{"id": "dojo", "done_when": {"map": "FIGHTING_DOJO"}}]}
    ck("a building whose door nobody holds passes", A.held_step_problems(dojo, obs) == [])
    hideout = {"subgoals": [{"id": "h", "done_when": {"map": "ROCKET_HIDEOUT_B1F"}}]}
    ck("...and one with an open known door", A.held_step_problems(hideout, obs) == [])
    ck("a place already stood in passes", A.held_step_problems({"subgoals": [{"id": "s", "done_when": {"map": "SAFFRON_CITY"}}]}, obs) == [])
    ck("no record, no refusal", A.held_step_problems(SILPH, Path(d) / "none.json") == [])
    ck("the pull guard still answers through the same core",
       "SILPH_CO_1F" in (A.pull_into_held("Defeat the Silph Co. guards", obs) or ""))
src = (ROOT / "planner" / "author.py").read_text()
ck("author, review and the drafts pick all ask it",
   "or held_step_problems(plan))" in src and "or held_step_problems(revised))" in src
   and "if not (validate(p2) or held_step_problems(p2))" in src)
bad = [c for c in checks if not c[1]]
for n, ok, dd in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(dd)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
