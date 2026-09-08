#!/usr/bin/env python3
"""A floor with no unseen edge and every shown doorway taken says so, as a
floor: a door not listed has never been on screen here.

Rocket Hideout B3F, run 16 (2026-09-07): every part of the floor read "THIS
AREA IS FULLY WORKED", both doorways were taken, no seen ground ended at
unseen ground — and the model, holding the Lift Key, walked B3F's parts for
two attempts looking for an elevator door it had inferred onto this floor
from a Rocket's line (user: "went back down to b3f because its still
convinced itself theres an elevator there"). Nothing on the page said it of
the FLOOR. The record can, without saying where the door is instead.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "ledger.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

i = src.find('"\\nTHIS FLOOR HAS SHOWN ALL IT WILL FROM WHERE YOU CAN STAND')   # the string, not the comment above it
ck("the sentence exists in the pass note", i > 0)
blk = src[max(0, i - 3000):i + 600]
ck("...gated on no unseen edge on this map", "_fmap0 == 0" in blk)
ck("...on every shown doorway taken, twin tiles folded, the arrival door counted",
   "_unused0 = [k for k in _known0" in blk and "_arr0.add(" in blk and "_grp0.get(k, (k,))" in blk)
ck("...on no doorway of it being unreachable from where you stand", "not _unr0" in blk)
ck("...and it says what the record says, not where the door is",
   "A door that is not listed " in blk and "above has never been on screen on this floor." in blk
   and "elevator" not in src[i:src.find("on this floor.\")", i)].lower())   # the sentence itself names no door

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
