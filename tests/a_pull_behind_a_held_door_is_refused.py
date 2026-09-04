#!/usr/bin/env python3
"""A pull behind a held door is refused (2026-09-04).

The Rescue leg was judged stuck behind "Defeat the Silph Co. guards to reach
the President" — "the Silph Scope is obtained from the President of Silph",
the model's fact and wrong — and the pull went through, because the existing
guard reads only the circle drawn by the stuck leg's own plan, which aimed at
the tower. The record held both halves anyway: door_dests says SAFFRON_CITY
18,21 leads into SILPH_CO_1F, and shut_doors says the last time the run stood
there "SAFFRONCITY_ROCKET8 is standing there" — spoken to, unmoved. A leg that
happens behind a door somebody is standing on is not what moves them. The rule
refuses only what the record shows: a place with any door not so held, or
never seen, or already stood in, is left to the model.

Synthetic: a walked record, no model."""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

REC = {"visits": {"SAFFRON_CITY|12,0": 10, "CELADON_CITY|2,1": 30, "GAME_CORNER|8,5": 3},
       "door_dests": {"SAFFRON_CITY": {"18,21": "SILPH_CO_1F", "34,3": "SAFFRON_GYM", "26,3": "FIGHTING_DOJO", "9,29": "SAFFRON_POKECENTER"},
                      "GAME_CORNER": {"17,4": "ROCKET_HIDEOUT_B1F"}},
       "shut_doors": {"SAFFRON_CITY|12,0": ["18,21 (SAFFRONCITY_ROCKET8 is standing there)",
                                            "34,3 (SAFFRONCITY_ROCKET3 is standing there)"]}}
with tempfile.TemporaryDirectory() as d:
    obs = Path(d) / "explored.json"; obs.write_text(json.dumps(REC))
    got = A.pull_into_held("Defeat the Silph Co. guards to reach the President", obs)
    ck("a pull into Silph Co, whose one known door a Rocket stands on, is named",
       got is not None and "SILPH_CO_1F" in got and "SAFFRONCITY_ROCKET8 is standing there" in got, got)
    got = A.pull_into_held("Defeat Sabrina at the Saffron Gym", obs)
    ck("...the Gym likewise", got is not None and "SAFFRON_GYM" in got and "ROCKET3" in got, got)
    got = A.pull_into_held("Clear the Rocket Hideout", obs)
    ck("a building never stood in whose door nobody holds is left to the model", got is None, got)
    got = A.pull_into_held("Defeat the Karate Master in the Fighting Dojo", obs)
    ck("...and one whose door is plain open too", got is None, got)
    got = A.pull_into_held("Reach Saffron City", obs)
    ck("a place already stood in is not refused by this rule", got is None, got)
    got = A.pull_into_held("Retrieve the Ethereal Bike from the Department Store", obs)
    ck("a leg naming no map the engine knows is left to the model", got is None, got)
    ck("a missing record refuses nothing", A.pull_into_held("Defeat the Silph Co. guards", Path(d) / "none.json") is None)
    ck("no record at all refuses nothing", A.pull_into_held("Defeat the Silph Co. guards", None) is None)

src = (ROOT / "planner" / "author.py").read_text()
ck("the blocker rung asks it after the circular-pull guard",
   "_held = pull_into_held(text, observed) if observed else None" in src
   and "A leg behind a held \"\n              f\"door is not what moves them: name what does, or another \"\n              f\"blocker\"" in src)
bad = [c for c in checks if not c[1]]
for n, ok, dd in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(dd)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
