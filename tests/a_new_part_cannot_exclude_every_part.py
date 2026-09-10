#!/usr/bin/env python3
"""new_part cannot demand a part when every known one is excluded.

`new_part` freezes into the map plus a not_area of every part the run has
stood in, which is right while some part is still unwalked. Once the run has
stood on all of them the condition can only be met by ground nobody has
seen, and the step spends its rounds proving it: Route 20, 2026-09-10, four
parts walked, all four excluded, a leg asking for a fifth while the deed it
named had already been done four times (user: "i think its used the 'new
area rt 20' but theres no new area to find"). The refusal does not claim a
fifth cannot exist — unseen ground may hold one — it says what IS known, and
refuses to offer a cheaper
witness, because a part you can already stand on is true before the step
runs — the very thing new_part exists to prevent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

src = (ROOT / "planner" / "author.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


walked = sorted(r for r in A.visited_regions() if str(r).split("|")[0] == "ROUTE_20")
ck("this run has walked several parts of ROUTE_20 to test against", len(walked) >= 2)
ck("excluding all of them is refused", A.new_part_exhausted({"map": "ROUTE_20", "not_area": walked}, "ROUTE_20") != "")
ck("...naming how many and which", "you have stood on all " in A.new_part_exhausted({"map": "ROUTE_20", "not_area": walked}, "ROUTE_20"))
_msg = A.new_part_exhausted({"map": "ROUTE_20", "not_area": walked}, "ROUTE_20")
ck("...and offering NO weaker witness to replace it", "Do NOT weaken it to a part " in _msg and '{"area"' not in _msg)
ck("...naming the two honest readings instead", "ground nobody has seen" in _msg and "ALREADY HAPPENED" in _msg)
ck("leaving one part allowed is fine", A.new_part_exhausted({"map": "ROUTE_20", "not_area": walked[:-1]}, "ROUTE_20") == "")
ck("no exclusions at all is fine", A.new_part_exhausted({"map": "ROUTE_20"}, "ROUTE_20") == "")
ck("a map with nothing walked is fine", A.new_part_exhausted({"map": "NOWHERE_AT_ALL", "not_area": ["NOWHERE_AT_ALL|1,1"]}, "NOWHERE_AT_ALL") == "")
ck("validate runs it on the frozen form", "_npe = new_part_exhausted(dw, str(dw.get(\"map\")))" in src)
plan = {"goal": "x", "subgoals": [{"id": "reach_west_exit", "goal_text": "Reach the west exit",
        "done_when": {"map": "ROUTE_20", "not_area": walked}, "escalation_rounds": 4}]}
ck("...so a plan written that way is refused", any("you have NOT stood on" in p for p in A.validate(plan)))
sys.exit(1 if fails else 0)
