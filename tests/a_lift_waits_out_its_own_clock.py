#!/usr/bin/env python3
"""The lift sits out the arrival announcement instead of handing the model
a box to press B at.

A Silph ride ends in ElevatorShake's "pa" phase, which holds while the
arrival chime plays and then pops itself (src/world/ElevatorShake.lua's
.musicLoop). The op's wait loop could come out the far side while that phase
still ran, and the step-out below is gated on the overworld being on top, so
the op answered "you are still IN the car; a screen is STILL up that would
not close (phase=pa)". The model then spent a whole round tapping B at a
clock — "ran but had NO visible effect" every time — and walked out the
round after (user, 2026-09-09: "is it still actually having the b-press
elevator issue or are we just still telling it that"). Now the op waits for
the clock before it reports, and if a timed state somehow survives that, the
words say it is a clock rather than inviting a keypress.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = sh.index("function OPS.elevator")
blk = sh[i:sh.index("-- CHOOSE WHO GOES OUT FIRST", i)]
ck("the op drains a timed state before it gives up", "A TIMED STATE IS NOT A STUCK BOX: SIT IT OUT." in blk and "for _ = 1, 900 do" in blk and "if not _is_fade(G.stack:top()) then break end" in blk)
ck("...before the step-out, which is gated on the overworld", blk.index("for _ = 1, 900 do") < blk.index("AND THEN WALK OUT"))
ck("the old would-not-close verdict is gone from what the model is TOLD",
   'A screen is STILL up that would not close ("' not in blk and '. A screen is still up ("' in blk)
ck("a surviving timed state is named as a clock, not a box", "it is a CLOCK, not a box" in blk and "clears itself, so the next op lands" in blk)
ck("...and no longer asks for a B press", '{\\"op\\":\\"tap\\",\\"btn\\":\\"b\\"} "\n              .. "before walking out"' not in blk)
sys.exit(1 if fails else 0)
