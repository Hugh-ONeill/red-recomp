#!/usr/bin/env python3
"""A PC with no Pokemon in it is said to be empty.

The boxed roster was printed only when there was one; with nothing deposited
the page said nothing about the PC, and a party that could not learn FLY set
off for the Center "to check the PC for a compatible Pokemon" (run 16,
2026-09-08; user: "shouldnt it know that theres nobody in the pc?"). The
player put nothing in, so the player knows the box is empty. Source-anchored
on the page builder, beside the roster line.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "planner" / "executor.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = src.index('_boxed = [m for m in ((obs or {}).get("pc_mons") or [])')
blk = src[i:i + 2500]
ck("an empty box is said when the observation carries the roster",
   'if not _boxed and "pc_mons" in (obs or {}):' in blk)
ck("...in the player's own terms", "IN PC STORAGE: no Pokemon — you have deposited none" in blk)
ck("...and a box with Pokemon still lists them", "IN PC STORAGE (yours, not in the party" in blk)
sys.exit(1 if fails else 0)
