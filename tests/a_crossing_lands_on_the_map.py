#!/usr/bin/env python3
"""A crossing is not finished until the party stands on the map.

Cerulean, 2026-08-29 (user watching the run ping-pong Route 4 <-> Cerulean):
`cross east` returned "crossed — now on CERULEAN_CITY at (-1,19)" — the
engine slides the player in from off the edge, so for a few frames cellX is
negative. An observation taken there floods the seen ground from a cell on
no map: nothing reachable, frontier 0, and the page reads "EVERYTHING YOU
CAN REACH HERE IS DONE" about a city with 20 unlooked-at spots — so explore
walked the party straight back out, every time.
"""
import sys
from pathlib import Path
sh = (Path(__file__).resolve().parents[1] / "harness" / "shim.lua").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
cr = sh[sh.index("function OPS.cross(G, c)"):]
cr = cr[:cr.index("\n-- ------------------------------------------------------------ shop/bag UI")]
ck("cross waits for an in-bounds, still cell before reporting where it landed",
   "local function land_settled()" in cr and "local function crossed_at()\n    land_settled()" in cr
   and "if still >= 6 then return end" in cr)
ck("...judging in-bounds against the map's own dimensions",
   "local W2, H2 = seen_dims(G, ow.map)" in cr
   and "and (W2 <= 0 or x < W2) and (H2 <= 0 or y < H2)" in cr)
ck("the footprint is never painted from off the edge",
   "if p.cellX < 0 or p.cellY < 0 then return end" in sh)
ck("...and the seen flood refuses to start there",
   "if not (sx and sy) and (p.cellX < 0 or p.cellY < 0) then return {}, {} end" in sh)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
