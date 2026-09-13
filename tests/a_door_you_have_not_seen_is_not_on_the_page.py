#!/usr/bin/env python3
"""The page showed a door and the ops said it did not exist yet.

Run 17, Route 25 (2026-09-13). The observation published

    buildings: [{"look":"small house","x0":44,"y0":1,"x1":47,"y1":3,
                 "doors":["45,3"]}]        warps: []

— a door, on a road where NOTHING had been on screen. The run did the
only sensible thing with it: use_warp(45,3), and got "couldn't reach the
warp tile ((45,3) has NEVER BEEN ON SCREEN — you only know ground that has
been on screen)". Viridian's (29,19) cost four rounds of exactly the same
exchange earlier in the same run.

Warps have been filtered through the seen-mask since the mask existed.
This list was handed over whole, straight off the static BUILDINGS table,
which is every building on the map whether the player has looked that way
or not — x-ray, and then contradicted by the op that would use it.

A building is kept once ANY of its footprint has been on screen, because
you can see a house across the street. Its doors are kept one at a time,
because making out a doorway is a nearer thing than seeing a roof. A
building with no door yet still belongs on the page: that is what a player
sees, and it is a reason to walk closer.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

SH = (ROOT / "harness" / "shim.lua").read_text()
blk = SH.split("local _bl = BUILDINGS[m.id]", 1)[1][:1600]

ck("the list is no longer handed over whole",
   "m.buildings = _bl" not in SH)
ck("a building is kept only once part of it has been on screen",
   "if seen(x, y) then any = true break end" in blk
   and "if any then" in blk)
ck("...across its whole footprint, not just one corner",
   "for x = b.x0" in blk and "for y = b.y0" in blk)
ck("a door is kept only if that cell has been on screen",
   "if dx and seen(tonumber(dx), tonumber(dy)) then" in blk)
ck("...and a building with no door yet is still listed",
   "doors = ds" in blk and "ds = {}" in blk)
ck("a map with nothing seen publishes no buildings at all",
   "m.buildings = (#kept > 0) and kept or nil" in blk)
ck("the warp-to-building link follows the KEPT list, not the raw one",
   "for i, b in ipairs(kept) do" in blk)

# the same mask the warps go through, so the two can never disagree again
ck("warps are still filtered by the same mask", "m.warps = keep_xy(m.warps)" in SH)
ck("...and `seen` is that mask",
   "return x ~= nil and y ~= nil and mask[x .. \",\" .. y] == true" in SH)

# the ops that refused it are unchanged: they were right
ck("a walk still refuses ground never on screen",
   "has NEVER BEEN ON SCREEN" in SH)

ck("the file still compiles",
   __import__("subprocess").run(
       ["luac", "-p", str(ROOT / "harness" / "shim.lua")]).returncode == 0)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
