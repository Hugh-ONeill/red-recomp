#!/usr/bin/env python3
"""A map change made by a script — an interact, a menu — sets the same
arrival facts a door does, so the door you are standing in front of reads
"the door you came in by".

The Safari gate's attendant warps you into the Center after you pay, by way
of an interact. Only doors and seams went through note_transition, so nothing
remembered where the run came from, and the Center's south door — the one the
party arrived in front of, leading back to the gate — read "never taken from
here" and was tried (run 16, 2026-09-08; user: "should the door be 'untried'
if its the door we came in from?"). No edge is written for a script warp
(nothing a walk can replay was taken); the arrival facts are.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402
import ledger as L     # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"\n      {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


src = (ROOT / "planner" / "executor.py").read_text()
i = src.index('chg.append(f"map->{after[0]}")')
blk = src[i:i + 2600]
ck("a map change after a non-door op sets where you came from and where you arrived",
   "self._came_from = self._where(pre_obs)" in blk and "self._arrived = (self._where(obs), (_ap[\"x\"], _ap[\"y\"]))" in blk)
ck("...but not for the ops note_transition already covers",
   'if op not in ("use_warp", "cross", "go", "explore", "sweep",' in blk)
ck("...and the journal says a script moved you", '"script_transition"' in blk)

# with those facts set, the ledger's rule recognises the door in front of you
ex = E.Executor.__new__(E.Executor)
ex.explored = {}
ex._arrived = ("SAFARI_ZONE_CENTER|22,10", (14, 26))
ex._came_from = "SAFARI_ZONE_GATE|0,0"
ck("the door beside the arrival cell, leading back where you came from, is the door you came in by",
   L._came_in_by(ex, {}, "SAFARI_ZONE_CENTER|22,10", "14,25", "SAFARI_ZONE_GATE") is True)
ck("a door elsewhere is not", L._came_in_by(ex, {}, "SAFARI_ZONE_CENTER|22,10", "0,10", "SAFARI_ZONE_WEST") is False)
sys.exit(1 if fails else 0)
