"""A loop count the plan cannot wipe (2026-08-26).

`visits` in the escalation loop is a LOCAL, so re-authoring a subgoal resets
it — and this run re-authors often. It crossed ROUTE_7 <-> CELADON_CITY four
times, was told "This is visit #4 to ROUTE_7 during this subgoal ... the trips
between here and there have bought nothing", and then a fresh subgoal started
the count at zero and it did it again. Earlier the same day three straight
`cross west` out of Saffron straddled go_to_fuchsia_city -> cross_safari_zone,
so the note only fired on the third.

The world mark is the honest clock: nothing about those trips changed because
the plan was rewritten. Reported only — the round BUDGET still counts per
subgoal, so a new step is never charged for the last one's wandering."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()

ck("a world-clocked counter exists on the executor",
   "self._world_visits: dict = {}" in src
   and 'self._world_mark_seen: str = ""' in src)
ck("...reset when the world mark moves, not when the plan does",
   "if _wm != self._world_mark_seen:" in src
   and "self._world_visits = {}" in src)
ck("...bumped on the same transition as the local counter",
   src.index("visits[sig1[0]] = visits.get(sig1[0], 0) + 1")
   < src.index("self._world_visits[sig1[0]] = \\"))

i = src.find("_wv = self._world_visits.get(sig1[0], 0)")
ck("the note reports it", i > 0)
blk = src[i:i + 900]
ck("...only when it is the bigger number", "if _wv > visits[sig1[0]]" in blk)
ck("...and says why the two differ",
   "since anything about the world " in blk
   and "re-authoring the plan did not " in blk)
ck("the per-subgoal count is still said first",
   'f"during this subgoal"' in blk)
ck("the world-mark sentence is unchanged",
   "The world mark is what it was on visit #1" in blk)

# the BUDGET must still be the local count
j = src.find("spent += 1   # back on a map already visited: circling")
ck("the round budget still uses the per-subgoal count", j > 0)
ck("...and is not keyed on the world counter",
   "_world_visits" not in src[max(0, j - 400):j + 200])

ck("it commands nothing",
   not re.search(r"(?i)(do not|you should|stop |go back)",
                 " ".join(re.findall(r'"([^"]*)"', blk))))

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
