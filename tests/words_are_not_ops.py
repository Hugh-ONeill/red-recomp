#!/usr/bin/env python3
"""A deed the words named and no op did is said, not assumed.

Round 3, standing in Cerulean: "travel east to Route 9 and use CUT to clear
the bush blocking the path west" — macro [cross east]. Round 4, on Route 9:
"I have just used CUT to clear the bush blocking the way west on Route 9. I
will now cross west into Cerulean City" — and it did, into the city it had
just left, while the bush at (5,8) stood untouched. No field_move was sent in
either round, or in the eight before them. The echo had written "→ new
ground" on round 3's plan, true of the crossing and read as true of the cut
(2026-09-03; user: "its pingponging and thinking its already cut the tree
when it hasnt because its *there*").

The page was honest about the bush — "stands here ... To clear one:
field_move" — but honest at the END of the feedback, and nothing said the
plain thing: you named CUT, nothing was cut. The sibling of "a border is not
a journey": that one reads the prose for a PLACE the round did not reach,
this one reads it for a DEED the round did not do, and both say so where the
results are, not in the dead zone.

Synthetic: no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
e = object.__new__(E.Executor)

R3 = ("I need to reach Celadon City. My only remaining option is to travel "
      "east to Route 9 and use CUT to clear the bush blocking the path west.")
R4 = ("I have just used CUT to clear the bush blocking the way west on Route "
      "9. I will now cross west into Cerulean City.")
CROSSED = ["cross(dir=east): ok (crossed — now on ROUTE_9 at (0,8))"]

got = e._deeds_named_not_done([{"op": "cross", "dir": "east"}], R3, CROSSED)
ck("CUT named, no field_move among the ops: named as not done",
   got == [("CUT", False)], got)
note = e._deed_note([{"op": "cross", "dir": "east"}], R3, CROSSED)
ck("...and the note says nothing was cut, and how a cut happens",
   "no CUT happened this round" in note and "nothing was cut" in note
   and '"op":"field_move"' in note and "no field_move was among your ops" in note,
   note)
got = e._deeds_named_not_done([{"op": "cross", "dir": "west"}], R4,
                              ["cross(dir=west): ok (crossed — now on CERULEAN_CITY at (39,16))"])
ck("'I have just used CUT' with no cut in the round is caught the same way",
   got == [("CUT", False)], got)

sent = [{"op": "cross", "dir": "east"}, {"op": "field_move", "move": "CUT", "x": 5, "y": 8}]
got = e._deeds_named_not_done(sent, R3, CROSSED)
ck("a field_move written but cut off by the map change is 'sent, not run'",
   got == [("CUT", True)], got)
ck("...and the note says so", "never run" in e._deed_note(sent, R3, CROSSED))

ran = CROSSED + ["field_move(move=CUT,x=5,y=8): ok — the bush at (5,8) is gone"]
ck("a cut that RAN is not reported", e._deeds_named_not_done(sent, R3, ran) == [])
failed = CROSSED + ["field_move(move=CUT): could not reach the bush"]
ck("a cut that ran and failed is left to its own failure line",
   e._deeds_named_not_done(sent, R3, failed) == [])

ck("lowercase prose ('the path is cut off') names no move",
   e._deeds_named_not_done([{"op": "cross", "dir": "east"}],
                           "the path south is cut off by the guard", CROSSED) == [])
ck("no plan text, no note", e._deed_note([], "", CROSSED) == "")
ck("SURF done by a surfing cross is not reported",
   e._deeds_named_not_done([{"op": "cross", "dir": "west", "surf": True}],
                           "use SURF to go west",
                           ["cross(dir=west,surf=True): ok (swam)"]) == [])
ck("SURF named and never mounted is",
   e._deeds_named_not_done([{"op": "walk_to", "x": 1, "y": 1}], "I will SURF west",
                           ["walk_to(1,1): ok"]) == [("SURF", False)])

src = (ROOT / "planner" / "executor.py").read_text()
ck("the note joins the round's feedback right after the results",
   "_deed = self._deed_note(macro, self._plan_said, trace)" in src
   and src.index("_deed = self._deed_note(") < src.index("if _trunc_note:\n                trace = list(trace) + [_trunc_note]"))
ck("the echo's verdict carries which named deed was not done",
   "no \" + \" or \".join(" in src and "was done that round)" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
