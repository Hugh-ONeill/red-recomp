#!/usr/bin/env python3
"""A return to look again, with nothing changed, is said so (2026-09-05).

"I will return to the 11th floor to see if the situation has changed or if I
can now access the boardroom" — with the same badges, the same event flags and
the same kinds in the bag as the last time it stood there (user: "unless theyve
done something to change something theres no reason to look again"). The
blockers ledger has said this for recorded blockers since August; a walled lift
landing is not a blocker row. Now the world mark is remembered per region at
every settle, and a plan whose words set out to look again at a map whose mark
has not moved is told that nothing about the run has changed since. Where the
change would come from is not said.

Synthetic: no game, no model."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
e = object.__new__(E.Executor)
e._mark_now = [4, 191, 20]
e._region_mark = {"SILPH_CO_11F|9,0": [4, 191, 20], "SILPH_CO_10F|8,0": [4, 190, 20], "SILPH_CO_7F|16,0": [4, 191, 20]}
e.visits = {"SILPH_CO_11F|9,0": 6, "SILPH_CO_10F|8,0": 3, "SILPH_CO_7F|16,0": 1}
e.door_dests = {"SILPH_CO_10F": {"9,0": "SILPH_CO_11F"}}
obs = {"map": {"id": "SILPH_CO_10F"}}
plan = "I am on the 10th floor. The President is on the 11th floor, but the door was previously blocked. I will return to the 11th floor to see if the situation has changed."
w = e._unchanged_return_note([{"op": "elevator", "floor": "11F"}], plan, obs)
ck("a lift ride back to look again, with the same mark, is said so", "NOTHING ABOUT YOU HAS CHANGED since you last stood on SILPH_CO_11F (stood there 6x)" in w, w)
ck("...in the mark's own terms", "the same badges, the same event flags, the same kinds in the bag" in w, w)
ck("...and ends on deed, not return", "a deed, not a return" in w, w)
ck("...without saying what the deed is", "CARD_KEY" not in w and "pad" not in w.lower(), w)
ck("a door the run has walked to that floor counts as a destination too", "SILPH_CO_11F" in e._unchanged_return_note([{"op": "use_warp", "x": 9, "y": 0}], plan, obs))
ck("a go to a region counts", "SILPH_CO_11F" in e._unchanged_return_note([{"op": "go", "to": "SILPH_CO_11F|9,0"}], plan, obs))
e2 = object.__new__(E.Executor); e2._mark_now = [4, 193, 20]; e2._region_mark = e._region_mark; e2.visits = e.visits; e2.door_dests = e.door_dests
ck("when the mark has moved since, nothing is said", e2._unchanged_return_note([{"op": "elevator", "floor": "11F"}], plan, obs) == "")
ck("a plan that is not looking again says nothing", e._unchanged_return_note([{"op": "elevator", "floor": "11F"}], "I will ride to the 11th floor and take the pad.", obs) == "")
ck("a return to a floor never stood on says nothing", e._unchanged_return_note([{"op": "elevator", "floor": "6F"}], plan, obs) == "")
ck("the floor underfoot is not a return", e._unchanged_return_note([{"op": "elevator", "floor": "10F"}], plan, obs) == "")
e3 = object.__new__(E.Executor)
ck("an executor from before the marks does not die of it", e3._unchanged_return_note([{"op": "go", "to": "X"}], plan, obs) == "")
src = (ROOT / "planner" / "executor.py").read_text()
ck("the mark is remembered per region at every settle and persisted",
   "self._region_mark[_hr] = list(self._mark_now)" in src and '"region_mark": getattr(self, "_region_mark", {})' in src and 'self._region_mark = data.get("region_mark") or {}' in src)
ck("the note rides the round's feedback", "_ret = self._unchanged_return_note(macro, self._plan_said, _obs_now)" in src)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
