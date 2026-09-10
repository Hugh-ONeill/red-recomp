#!/usr/bin/env python3
"""A doorway the WATER reaches is marked ridable, even though the doorway
itself stands on dry land.

The by_water flag asked whether the swum flood covers the warp's OWN cell.
A ladder or a door never sits in water, so the flood stopped at the shore
and the flag never fired. Seafoam B3F reported sixteen water-frontier spots,
one chain running down x=25 as far as (25,13), one cell from the ladder at
(25,14) — and every ladder on that floor came back "you cannot walk to it"
with nothing said about the water, so the run planned a long walk back
through another region instead (2026-09-10; user: "the ladder is reachable
just over water"). The item side has always asked the right question: you
stand BESIDE a thing to use it. Warps ask it now too, and the ledger's own
sentence — no walk from here reaches it, but the WATER does — becomes true
when it is.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
lg = (ROOT / "planner" / "ledger.py").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = sh.index("A LADDER STANDS ON DRY LAND")
blk = sh[i - 400:i + 2600]
step = sh[sh.index("local function swim_step_to"):sh.index("local function swim_step_to") + 2000]
ck("the flag still needs the walk to have failed", 'by_water = (not reach[w.x .. "," .. w.y])' in blk)
ck("...and now asks whether the party can come ashore onto it", "and swim_step_to(w.x, w.y)" in blk)
ck("bare adjacency is not enough: the engine is asked to make the step",
   "Collision.canMove(ow.map, ow.entities, probe, dn)" in step)
ck("...and the probe surfs only where the cell is water, since the flood walks ashore",
   "surfing = real_water(G, ow.map, fx, fy)" in step)
ck("...stepping FROM the water cell onto this one", "local fx, fy = x - sd[2], y - sd[3]" in step and "if sc[fx .. \",\" .. fy] then" in step)
ck("...over four directions spelled in place, since DIRS is declared later in the file",
   '{ "up", 0, -1 }, { "down", 0, 1 },' in step and "pairs(DIRS)" not in step)
ck("...keeping the own-cell case, for a mat that sits in water", 'if sc[x .. "," .. y] then return true end' in step)
ck("the swum flood is still gated on a party Pokemon knowing SURF", "party_knows_surf() and warp_reach(G, nil, true)" in sh)
ck("the ledger already has the words for it", 'no walk from here reaches it, but the WATER does' in lg)
ck("the reason is written where the next reader will look", "you stand\n                              -- BESIDE a thing to use it" in sh)
sys.exit(1 if fails else 0)
