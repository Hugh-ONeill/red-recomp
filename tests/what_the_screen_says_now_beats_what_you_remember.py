#!/usr/bin/env python3
"""What the screen says now beats what you remember (2026-09-05).

Standing on Silph 11F's pad with the President three tiles off and the page
listing him REACHABLE for the first time — the landing fix (86bb548) having
just opened his alcove — the plan read "the President is visible but
unreachable ... I will use the 'go' command to return to SILPH_CO_11F|9,0",
the one part of the floor he cannot be reached from, and it left. The claim
came from its own earlier rounds, when it was true. When the plan's words call
a thing unreachable and THIS observation marks that thing reachable, the round
says so. Nothing about where to stand or what to press.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
e = object.__new__(E.Executor)
obs = {"mode": "overworld", "map": {"id": "SILPH_CO_11F", "objects": [
    {"name": "SILPHCO11F_SILPH_PRESIDENT", "x": 7, "y": 5, "reachable": True},
    {"name": "SILPHCO11F_BEAUTY", "x": 10, "y": 5, "reachable": True},
    {"name": "SILPHCO11F_ROCKET2", "x": 15, "y": 9, "reachable": False}]}}
plan = ("I am currently in a part of the 11th floor where the President is visible but unreachable. "
        "I will use the 'go' command to return to that specific area.")
w = e._reachable_disagreement_note(plan, obs)
ck("the plan's 'unreachable' is answered by this round's page",
   "your plan calls SILPHCO11F_SILPH_PRESIDENT unreachable" in w, w)
ck("...saying a walk reaches him now", "a walk reaches it" in w, w)
ck("...and that it was true when written", "was true when you wrote it" in w, w)
ck("...and what leaving costs", "Leaving this spot gives it up" in w, w)
ck("...without saying where to stand or what to press", "7,5" not in w and "walk_to" not in w and "interact" not in w, w)
ck("a thing the page also calls unreachable is not contradicted",
   e._reachable_disagreement_note("ROCKET2 is unreachable from here.", obs) == "")
ck("a plan with no unreachable claim says nothing",
   e._reachable_disagreement_note("I will walk to the President and speak with him.", obs) == "")
ck("an unreachable claim about something else says nothing",
   e._reachable_disagreement_note("The staircase is unreachable from here.", obs) == "")
ck("a bag/menu observation is not judged",
   e._reachable_disagreement_note(plan, {"mode": "ui", "map": {"objects": []}}) == "")
ck("a short name like PC is not matched loosely",
   e._reachable_disagreement_note("The PC is unreachable.", {"mode": "overworld", "map": {"objects": [{"name": "PC", "reachable": True}]}}) == "")
e2 = object.__new__(E.Executor)
ck("junk is tolerated", e2._reachable_disagreement_note(None, None) == "")
src = (ROOT / "planner" / "executor.py").read_text()
ck("the note rides the round's feedback",
   "_reach = self._reachable_disagreement_note(self._plan_said, _obs_now)" in src
   and "for _n in (_held, _spoke, _ret, _reach):" in src)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
