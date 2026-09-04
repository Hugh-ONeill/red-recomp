#!/usr/bin/env python3
"""The condition is the step (2026-09-04).

The rewrite wrote "Use the elevator to leave the Rocket Hideout B4F" over the
condition {"map":"ROCKET_HIDEOUT_ELEVATOR"}. Standing on B2F beside a lift door
listed as never taken, the run took the stairs down to hunt "the elevator at
(24,15)" on B4F, three rounds running (user: "the damn goal text messes it up
by telling it that the elevator is on b4f"). Both halves are the plan's own
words; when the words name a floor the condition does not, the page says which
half counts. It never says where a door leads.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
e = object.__new__(E.Executor)
w = e._words_vs_condition("Use the elevator to leave the Rocket Hideout B4F", {"map": "ROCKET_HIDEOUT_ELEVATOR"})
ck("a floor in the words that the condition does not name is called out", "THE CONDITION IS THE STEP" in w and "(B4F)" in w, w)
ck("...saying any floor's door into the map counts", "whichever floor's door you take into it" in w, w)
ck("...and that the floor was the plan-writer's guess", "plan-writer's guess" in w, w)
ck("...without naming any door or where it leads", "24,19" not in w and "B2F" not in w, w)
ck("a floor the condition itself names is not stray", e._words_vs_condition("Climb to B4F", {"map": "ROCKET_HIDEOUT_B4F"}) == "")
ck("a rooftop word against a mart floor is stray", "(ROOFTOP)" in e._words_vs_condition("Buy water on the rooftop", {"map": "CELADON_MART_5F"}))
ck("an area condition is read by its map", "(B4F)" in e._words_vs_condition("the lift on B4F", {"area": "ROCKET_HIDEOUT_ELEVATOR|0,1"}))
ck("no floor word, nothing said", e._words_vs_condition("Enter the Pokemon Tower", {"map": "POKEMON_TOWER_1F"}) == "")
ck("a non-map condition says nothing", e._words_vs_condition("Get the Scope on B4F", {"has_item": {"SILPH_SCOPE": 1}}) == "")
ck("junk is tolerated", e._words_vs_condition(None, None) == "" and e._words_vs_condition("x", {"map": 7}) == "")
src = (ROOT / "planner" / "executor.py").read_text()
ck("it rides the step statement at the top of the prompt",
   'user = (f"SUBGOAL: {goal}\\nDONE_WHEN: {json.dumps(done)}"\n                    f"{self._words_vs_condition(goal, done)}"' in src)
bad = [x for x in checks if not x[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
