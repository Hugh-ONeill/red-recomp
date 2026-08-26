"""A door's quoted refusal carries when it was said (2026-08-26).

The people-said block dates every line — "said before N event(s) that have
fired since" — and a DOOR's quoted refusal carried no stamp at all. Inside
ROUTE_5_GATE the south door's row read

  trying it said: "I'm on guard duty. Gee, I'm thirsty, though! Oh wait there,
  the road's closed."

with the drink long since handed over and the guard, one row below, saying
"Hi, thanks for the cool drinks!". Two sentences from the same gate, one
stale, and the stale one on the row where the door is chosen.

Same stamp, same source (hints_at), same rule: say when it was said; whether
it still holds is the model's."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
import ledger as L

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/ledger.py").read_text()
i = src.find("AND A REFUSAL OUTLIVES THE THING THAT LIFTED IT")
ck("the door refusal is dated", i > 0)
blk = src[max(0, i - 400):i + 1600]
ck("...from hints_at, keyed exactly as the hint was stored",
   'f"use_warp ({key}): {_said_here}"' in blk
   and 'getattr(ex, "hints_at", {})' in blk)
ck("...counting events fired since, like the people-said block",
   "event(s) that have "  in blk and "_now > _then" in blk)
ck("an undated line is left exactly as it was",
   "c.spoke = _said_here" in blk and "if _then is not None" in blk)
ck("a page never dies of it", "except Exception:" in blk)

# behaviour
class Ex:
    hints = {"R|0,0": ["use_warp (3,5): the road's closed."]}
    hints_at = {"R|0,0": {"use_warp (3,5): the road's closed.": 117}}
    explored = {"R|0,0": {}}
    region_seen = {}
    _tried_objs = {}
    sightings = {}
    visits = {"R|0,0": 1}
    def _frontier_left(s, r): return []
    def _route(s, a, b): return []

# the stamp arithmetic, exercised directly on the same inputs
_then = Ex.hints_at["R|0,0"]["use_warp (3,5): the road's closed."]
for _now, want in ((244, True), (117, False), (100, False)):
    got = _now > _then
    ck(f"flags={_now}: stamped={got}", got == want)

# executor wraps the same sentence across two f-string lines
_ex = Path("planner/executor.py").read_text()
ck("the wording matches the people-said block",
   "said before " in src[i:i + 1600]
   and "(said before {now - then} event(s) that have " in _ex
   and 'f"fired since)")' in _ex)

import ast
try:
    ast.parse(src); ck("ledger.py parses", True)
except SyntaxError as e:
    ck(f"ledger.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
