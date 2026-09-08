#!/usr/bin/env python3
"""A go leg that lands somewhere other than its target re-plans from where
it landed, whatever map that is.

Run 16 (2026-09-08): a go from Route 17's foot to Fuchsia lost its first leg
— the crossing meant to leave Route 17 for Route 18 came back on Route 17 at
(4,17), having started from Route 16 — and the walk was abandoned with the
rest of the way to Fuchsia still walked ground under its feet, because the
re-plan asked that the landing at least be on the target's MAP. The route
is built from walked edges only, so re-planning from any landing is as safe
as the first plan was; the guard that stays is against re-sending the
identical leg from the identical spot.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ex = (ROOT / "planner" / "executor.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = ex.index("    def _walk_route(self, sg, path, _replans=0):")
w = ex[i:i + 40000]
ck("the re-plan no longer requires the landing to share the target's map", "if self._where(o) != nxt and _final and _replans < 2:" in w and "_rest = self._route(self._where(o), _final)" in w)
ck("...and the same-map clause is gone", 'and str(nxt).split("|")[0]\n                    == str(self._where(o)).split("|")[0]' not in w)
ck("the identical-leg guard stays", 'not (self._where(o) == self._where(pre)\n                                 and _rest[0][0] == key)' in w)
ck("the reason is written where the next reader will look", "REPLAN FROM WHEREVER THE LEG PUT YOU" in w)
sys.exit(1 if fails else 0)
