#!/usr/bin/env python3
"""The dead-end advice does not offer a PC or a sign as the thing that might
open a way.

When an area looks finished the page says not to call it a dead end while
untouched things remain, because "picking an item up or moving it can open a
way that is shut". That is true of items, people and switches. It is false
of the two fixtures a player tells apart at a glance: a PC stores and a sign
reads. Silph 11F could not walk back to its lift, this fired, and the run
pressed the beauty and the PC before leaving (2026-09-09; user: "make the
pc-in-a-dead-end suggestion smarter, it can't do anything there"). They are
still named, because a PC is the answer to a full bag, but never as a way
out; and when they are ALL that is left, the page says the way on is not in
this room.
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


i = ex.index("A COMPUTER IS NOT A LEVER.")
blk = ex[i:i + 3000]
ck("storage and signs are split off from the openers",
   'str(n) == "PC" or str(n).endswith("_PC")' in blk and 'str(n).startswith("TEXT_")' in blk
   and "_open = [n for n in live if n not in _talk]" in blk)
ck("the obstacle claim is made only about the openers", "may " in blk and "_open[:6]" in blk)
ck("...and a PC or sign is still named, as what it is", "a computer stores and a sign reads: neither " in blk)
ck("when only those are left, the room is called finished", "The way on is not in this room." in blk and "neither is what is stopping you" in blk)
_said = blk[blk.index("trace.append"):]      # the words the model reads, not the comment
ck("...without telling it where to go instead", not any(w in _said for w in ("11F", "lift", "go to", "elevator")))
ck("the reason is written where the next reader will look", "A PC stores" in blk or "a PC stores" in blk)
sys.exit(1 if fails else 0)
