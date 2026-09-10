#!/usr/bin/env python3
"""cross mounts before stepping onto a seam whose far side is water.

Cinnabar's east edge is dry land looking at Route 20's open sea: every
landing cell there is water, passable only while surfing. The model did the
right thing — walk_to with surf to the shore, then cross east with surf —
but the walk did not need to ride to move along its own shore, so it
arrived on foot, and surf= on the cross was read as permission for the
landing rather than an instruction to be afloat. The step went off the edge
and the game refused: "stepped right at gap (19,13) but no map change",
nine rounds of it, until a sweep widened the footprint and broke the lock
(2026-09-10; user: "the east seam of cinnabar is a map boundary with land on
the cinnabar and water on the rt20 side"). Now the op gets on the water
first, the way walk_to and grind already do. WHICH seam is still the
model's; being afloat to take it is mechanics.
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


i = sh.index("A SEAM WHOSE FAR SIDE IS WATER")
blk = sh[i:i + 2200]
ck("it fires only when the landing needs surf and the party is on foot",
   "if not p.surfing and landing_ok(G, dir, p.cellX, p.cellY, true)" in blk
   and "and not landing_ok(G, dir, p.cellX, p.cellY, false) then" in blk)
ck("a party with no SURF is told the seam is water, not walked at it",
   "nothing in the party knows SURF" in blk and "cannot be crossed on " in blk)
ck("otherwise it rides on with the game's own field move", 'OPS.field_move(G, { move = "SURF", x = _wx, y = _wy })' in blk)
ck("...at the cell across the seam", "local _wx, _wy = p.cellX + _d[1], p.cellY + _d[2]" in blk)
ck("a mount that did not take is said, with the reason", "getting on it here did not work" in blk)
ck("the step-off loop still follows", blk.index("for _ = 1, 8 do") > blk.index("OPS.field_move"))
ck("both helpers it uses are defined before it",
   sh.index("local function landing_ok") < i and sh.index("local DIRS =") < i)
ck("the reason is written where the next reader will look", "crossed from the water" in blk)
sys.exit(1 if fails else 0)
