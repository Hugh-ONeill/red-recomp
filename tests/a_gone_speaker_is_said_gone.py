"""What a vanished speaker said is marked as such (2026-08-26).

The sightings ledger learned in 08-25 that "a thing that is gone is not still
seen" and logs sighting_gone. `hints` never learned it, so ROUTE12_SNORLAX's
"A sleeping POKéMON blocks the way!" went on being served under "WHAT YOU WERE
TOLD ELSEWHERE — this game explains its own gates out loud" for legs after
EVENT_BEAT_ROUTE12_SNORLAX fired and the Snorlax was gone from the map (user:
"stale snorlax blocker too i think").

The line is KEPT — a ledger keeps its observations — and marked with the other
observation that bears on it: you have stood there since and it was not there.
"""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
import executor as E

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()

ck("absent speakers are remembered per region",
   "self._gone: dict = {}" in src
   and "self._gone.setdefault(here, set()).update(gone)" in src)
ck("...written from the same block that already detects them",
   src.index('self.log("sighting_gone", area=here') <
   src.index("self._gone.setdefault(here, set()).update(gone)"))
ck("...and survive a restart",
   'data.get("gone") or {}' in src and '"gone": {r: sorted(v)' in src)

def ex_with(gone, at):
    ex = E.Executor.__new__(E.Executor)
    ex._gone, ex.hints_at = gone, at
    return ex

LINE = "ROUTE12_SNORLAX: A sleeping POKéMON blocks the way!"
obs = {"flags": list(range(244))}

got = ex_with({"ROUTE_12|0,61": {"ROUTE12_SNORLAX"}},
              {"ROUTE_12|0,61": {LINE: 101}})._dated("ROUTE_12|0,61", LINE, obs)
ck("the line is still served in full", LINE in got)
ck("...still dated", "said before 143 event(s)" in got)
ck("...and marked gone, naming the speaker and the place",
   "ROUTE12_SNORLAX is NOT THERE ANY MORE" in got
   and "you have stood in ROUTE_12|0,61 since" in got)

other = ex_with({"ROUTE_12|0,61": {"ROUTE12_SNORLAX"}},
                {"ROUTE_12|0,61": {LINE: 101}})._dated(
                    "ROUTE_12|0,61", "SOMEONE_ELSE: hello there", obs)
ck("another speaker in the same region is untouched",
   "NOT THERE" not in other)

none = ex_with({}, {})._dated("R|0,0", "GUARD: the road's closed", obs)
ck("with nothing recorded the line is exactly as before",
   none == "GUARD: the road's closed")

# an undated line still gets the mark
undated = ex_with({"R|0,0": {"GUARD"}}, {})._dated(
    "R|0,0", "GUARD: the road's closed", obs)
ck("an undated line still says the speaker is gone",
   "NOT THERE ANY MORE" in undated and "said before" not in undated)

ck("it draws no conclusion for the model",
   not re.search(r"(?i)(so you can|the way is open|ignore|no longer blocks)",
                 got))

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
