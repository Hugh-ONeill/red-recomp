"""A bush that grew back is not a contradiction (2026-08-26).

Gen 1 regrows a cut tree every time you re-enter the map, so a road the run has
walked twenty times is walled again on arrival. `go LAVENDER_TOWN` stops at
ROUTE_9|0,8 on EVERY trip — reported twice by the user on the same day, the
second time after the WHAT-STOPPED-IT fix had already made the reason visible.
Seeing the reason does not remove the toll: every trip still costs a round.

Replaying a walked route is what `go` IS, and that route was walked with this
bush down. Cutting it back down is replay, not a decision — the room sweep
already fells bushes unasked. Only a bush the refusal itself names, only with
CUT in the party, and only once per route."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

src = Path("planner/executor.py").read_text()
i = src.find("A BUSH THAT GREW BACK IS NOT A CONTRADICTION")
ck("the regrowth retry exists", i > 0)
blk = src[i:i + 2400]

ck("...taken from the refusal's OWN words, with coordinates",
   "CUT_TREE" in blk and "a bush CUT clears" in blk
   and "(\\d+),(\\d+)" in blk and "_last_det" in blk)
ck("...only when a party Pokemon knows CUT",
   '"CUT" in [str(mv.get("id")' in blk and "(o or {}).get(\"party\")" in blk)
ck("...only once per route", "_replans < 1" in blk
   and "_replans + 1" in blk)
ck("it uses the field move, not a press",
   'self._send_safe("field_move", move="CUT"' in blk)
ck("it is recorded either way",
   'self.log("route_cut_regrowth"' in blk and "ok=bool(_cok)" in blk)
ck("...and only re-routes when the cut actually worked",
   "if _cok:" in blk and "_rest3 = self._route(" in blk)
ck("a failed cut falls through to the old handling",
   src.index("A hop that fails to land even after the passage retry",
             i) > i)
ck("it never cuts something the refusal did not name",
   "_cut_at = None" in blk)

# and it sits BEFORE the edge-voiding, so a regrown bush never voids a road
ck("the retry runs before the edge is blamed",
   src.index("route_cut_regrowth") <
   src.index("CONTRADICTS the recorded edge"))

import ast
try:
    ast.parse(src); ck("executor.py parses", True)
except SyntaxError as e:
    ck(f"executor.py parses ({e})", False)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
