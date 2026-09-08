#!/usr/bin/env python3
"""A walk the Safari clock ended is not booked as the door's own outcome, and
a sweep in the Safari Zone says where the clock stands.

Run 16 (2026-09-08), first Safari attempt: three doors read "-> UNKNOWN —
trying it said: 'PA: Ding-dong! Time's up! PA: Your SAFARI GAME is over!'" —
a door that says time's up reads as a shut one — because the walk toward each
had been cut by the clock and the recorder booked the PA's line against the
door. The same rule the stamps and seams already follow (_walk_cut_by_the_world)
now guards the outcome ledger. And a sweep that spent 143 of the 500 steps said
nothing about the clock; it now ends with the steps and balls left.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"\n      {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


src = (ROOT / "planner" / "executor.py").read_text()
i = src.index("def _record_outcome(self, pre_obs, op: str, step: dict, note: str):")
blk = src[i:i + 3000]
ck("the recorder asks whether the world cut the walk before booking anything",
   "if self._walk_cut_by_the_world(note) or \"time's up\" in str(note).lower()" in blk)
ck("...and books nothing when it did", '"outcome_not_the_doors"' in blk and blk.index('"outcome_not_the_doors"') < blk.index("book = self._outcomes.setdefault"))

# functionally, on a bare instance
ex = E.Executor.__new__(E.Executor)
ex._outcomes, ex._gone, ex._cur_target = {}, {}, "map:X"
ex.log = lambda *a, **k: None
pre = {"map": {"id": "SAFARI_ZONE_NORTH", "region": "2,1"}, "player": {"x": 3, "y": 3}}
try:
    ex._record_outcome(pre, "use_warp", {"x": 35, "y": 3},
                       "use_warp(x=35,y=3): FAILED — couldn't reach the door at (35,3) — the SAFARI GAME ended on the way (PA: Ding-dong! Time's up!)")
    ck("a clock-ended walk books nothing", ex._outcomes == {}, ex._outcomes)
except Exception as e:                       # the bare instance may lack a later ledger
    ck("a clock-ended walk books nothing (returned before any ledger was touched)", ex._outcomes == {}, f"{e}: {ex._outcomes}")

sh = (ROOT / "harness" / "shim.lua").read_text()
j = sh.index('local detail = ("swept %d step(s)%s, %d cell(s) newly on screen; %s — stopped: %s")')
ck("a sweep in the Safari Zone says where the clock stands",
   'detail = detail .. (" — SAFARI clock now: %d step(s) left, %d SAFARI BALL(s)")' in sh[j:j + 1500]
   and "if safari_running(G) then" in sh[j:j + 1500])
sys.exit(1 if fails else 0)
