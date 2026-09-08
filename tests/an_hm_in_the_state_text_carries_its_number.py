#!/usr/bin/env python3
"""An HM in the ladder's state text carries its number: "HM_FLY (HM02)".

The outline says "Retrieve the HM02"; the bag said "HM_FLY x1"; the done-judge
read the two against each other and twice refused a leg that was done, then
passed it on the third look with the words "HM_FLY (HM02)" (run 16,
2026-09-08, the Fly-leg replay). An HM is handed over by a person who names
both — "HM02 ... FLY" — so both names are the player's. TMs are left alone:
the page reads them by number until booted, and that rule lives elsewhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
import state_text as S   # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"\n      {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


t = S.bag_text({"HM_FLY": 1, "HM_CUT": 1, "TM_SWIFT": 1, "POTION": 3})
ck("an HM carries its number", "HM_FLY (HM02) x1" in t and "HM_CUT (HM01) x1" in t, t)
ck("a TM is left as it is", "TM_SWIFT x1" in t and "(TM39)" not in t, t)
ck("an ordinary item is untouched", "POTION x3" in t, t)
ck("an empty bag is still an empty bag", S.bag_text({}) == "an empty bag")
sys.exit(1 if fails else 0)
