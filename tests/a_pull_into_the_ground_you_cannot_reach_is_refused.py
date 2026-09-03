#!/usr/bin/env python3
"""A leg that happens where you cannot stand does not get you there.

"Obtain Fresh Water" failed seven times on go_to_celadon_city — the Route 5
guard is thirsty and Celadon is the far side of him. Asked what has to
happen first, the model named "Retrieve the Ethereal Bike from the
Department Store" and the confirm step let it through: the thing it
"provides" (the bike) is not the thing the stuck leg is for (the water), so
the item circle inside confirm_blocker saw nothing wrong. The pull put in
front of the stuck leg a leg whose own first step is go_to_celadon_city
(2026-09-02, leg 23 pulled from 28), and the run was pointed at the one
place it could not reach, twice over.

The circle here is drawn in GROUND, not things, and the harness holds both
halves without knowing any geography: the stuck plan's done_when clauses
say where it meant to stand, the walked record says it never did, and the
outline names where the other leg happens, in the engine's own map ids.
Where the candidate leg names no map at all (the bike leg calls its shop
"the Department Store") the rule stays silent: it refuses only what it can
read, and the model's word decides the rest.

Synthetic: a plan file, a walked record, no model.
"""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    plan = d / "leg_24_obtain_fresh_water.json"
    plan.write_text(json.dumps({"goal": "Obtain Fresh Water", "subgoals": [
        {"id": "go_to_celadon_city", "done_when": {"map": "CELADON_CITY"}},
        {"id": "enter_celadon_mart", "done_when": {"map": "CELADON_MART_1F"}},
        {"id": "go_to_mart_floor_5", "done_when": {"map": "CELADON_MART_5F"}},
        {"id": "buy_fresh_water", "done_when": {"has_item": {"FRESH_WATER": 1}}},
    ]}))
    observed = d / "explored.json"
    observed.write_text(json.dumps({"visits": {
        "CERULEAN_CITY|20,0": 191, "ROUTE_5|6,0": 9, "LAVENDER_TOWN|1,1": 0}}))

    un = A.plan_places_unreached(plan, observed)
    ck("the plan's aims the run never stood in are read off it",
       un == {"CELADON_CITY", "CELADON_MART_1F", "CELADON_MART_5F"}, un)
    ck("a zero-visit entry counts as never stood in",
       "LAVENDER_TOWN" not in {r.split("|")[0] for r, n in
                               json.loads(observed.read_text())["visits"].items()
                               if n})

    got = A.pull_into_unreached("Retrieve the Gold Teeth from Celadon City",
                                plan, observed)
    ck("a pull into the city the stuck plan could not reach is named",
       got == "CELADON_CITY", got)
    got = A.pull_into_unreached("Obtain Fresh Water from the Celadon Mart",
                                plan, observed)
    ck("...and so is a pull into a ROOM of it", got is not None
       and got.startswith("CELADON"), got)
    got = A.pull_into_unreached("Reach Lavender Town", plan, observed)
    ck("a pull to somewhere ELSE is not refused by this rule", got is None, got)
    got = A.pull_into_unreached(
        "Retrieve the Ethereal Bike from the Department Store", plan, observed)
    ck("a leg that names no map the engine knows is left to the model",
       got is None, got)
    got = A.pull_into_unreached("Reach Celadon City", d / "no_such_plan.json",
                                observed)
    ck("no plan yet (a leg never authored) means no verdict", got is None, got)

    # once the run HAS stood in Celadon the same pull is no longer circular
    observed.write_text(json.dumps({"visits": {"CELADON_CITY|3,3": 1}}))
    got = A.pull_into_unreached("Retrieve the Gold Teeth from Celadon City",
                                plan, observed)
    ck("standing there once lifts it", got is None, got)

src = (ROOT / "planner" / "author.py").read_text()
ck("check_blocker asks before the confirm step",
   "pull_into_unreached(text, plan, observed)" in src
   and src.index("pull_into_unreached(text, plan, observed)")
   < src.index("if not confirm_blocker(goal, n, text, gap, start, journal, model,"))
ck("...and the refusal says which place, and why that is circular",
   "the very \"\n              f\"place this leg's own plan could not reach" in src)
ck("the chain hands over the stuck leg's plan",
   '--plan "$plan"' in (ROOT / "fresh_discovery.sh").read_text())

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
sys.exit(1 if bad else 0)
