#!/usr/bin/env python3
"""Coming out onto a part is not proof it is the FAR side, and the repair
for "which parts have I stood on" is new_part, not a list written by hand.

The rule exists for Rock Tunnel, where the run really had come out onto the
far side and then excluded it. Seafoam is the other shape: the islands' 1F
door (4,17) lands on ROUTE_20|52,2 three times over, and 52,2 is walk-joined
to 44,2 where the run went in — one side of the water, two region names. The
author was told "that part IS the far side: end on it", which is the one
answer that cannot be right, and every plan for the leg was refused, five
rounds running, twice (2026-09-09). A far side is a part no walk from the
way in reaches. And when the author does mean "any part I have not stood
on", freeze_new_parts already does the bookkeeping from the run's record, so
the refusal names it instead of inviting another hand-written exclusion.
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


EX = {
    "ROUTE_20|44,2": {"walk:ROUTE_20|52,2": {"to": "ROUTE_20|52,2"},
                      "48,5": {"to": "SEAFOAM_ISLANDS_1F|3,2"}},
    "ROUTE_20|52,2": {"walk:ROUTE_20|44,2": {"to": "ROUTE_20|44,2"}},
    "SEAFOAM_ISLANDS_1F|3,2": {"4,17": {"to": "ROUTE_20|52,2"}},
    "ROUTE_20|9,9": {},
}
ck("two parts joined by a walk are one side", A._walk_joined("ROUTE_20|52,2", "ROUTE_20|44,2", EX))
ck("...in either direction", A._walk_joined("ROUTE_20|44,2", "ROUTE_20|52,2", EX))
ck("a part no walk reaches is not", not A._walk_joined("ROUTE_20|9,9", "ROUTE_20|44,2", EX))
ck("a part is joined to itself", A._walk_joined("ROUTE_20|44,2", "ROUTE_20|44,2", EX))
ck("a door does not join two sides", not A._walk_joined("SEAFOAM_ISLANDS_1F|3,2", "ROUTE_20|44,2", EX))
ck("nothing is joined to nothing", not A._walk_joined("", "ROUTE_20|44,2", EX))
ck("the rule drops an excluded part that is walk-joined to the way in",
   "_bad_ex = [pt for pt in _bad_ex" in src and "if not any(_walk_joined(pt, w) for w in _in_parts if w)]" in src)
ck("the refusal offers new_part instead of another hand-written list",
   'do not list the parts yourself' in src and '{"new_part": "' in src
   and "filled in from the " in src)
ck("the reason is written where the next reader will look", "UNLESS IT IS STILL THE NEAR SIDE" in src)
sys.exit(1 if fails else 0)
