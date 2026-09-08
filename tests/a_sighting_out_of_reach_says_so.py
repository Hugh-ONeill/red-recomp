#!/usr/bin/env python3
"""A sweep's sighting that no walk from here reaches says so, and does not
stop a door-hunting sweep.

Route 16's north-west pocket, run 16 (2026-09-08): the sweep saw the gate's
south-west doors and four Bikers across the tree line, reported "a doorway at
(17,10)" like any doorway, and stopped for it. The model took that doorway
for the house it was after, walked at it twice, and was told a Biker stood by
it (user: "it only ever occasionally gets to the west side then doesnt
explore"). Seen is not reached: a thing on screen that no walk from here
reaches (nor any cell beside it) carries " — across ground no walk from here
reaches", and `until: door` does not fire on it; a map edge still does.
Source-anchored: the shim is Lua.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sh = (ROOT / "harness" / "shim.lua").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = sh.index("local function came_into_view()")
j = sh.index("local function fired(things)", i)
civ = sh[i:j]
ck("the sweep asks the reach fill about what came into view", "local rc = seen_reach(G)" in civ)
ck("a thing is near when it or a cell beside it is reachable",
   'if rc[x .. "," .. y] then return true end' in civ and "for _, d in pairs(DIRS) do" in civ)
ck("a far sighting is marked and says so",
   "t.far = true" in civ and 't.text .. " — across ground no walk from here reaches"' in civ)
ck("a map edge is never 'far' (it is a side, not a spot)", 'if t.x and t.kind ~= "way" and not near(t.x, t.y) then' in civ)
k = sh.index("local function fired(things)")
fired = sh[k:k + 800]
ck("a door-hunting sweep does not stop for a far door", "if wants[t.kind] and not t.far then return true end" in fired)
ck("...nor for a far person", 'if wants.person and t.kind == "trainer" and not t.far then return true end' in fired)
ck("...but a map edge still stops it", 'if wants.door and t.kind == "way" then return true end' in fired)
ck("anything_new still fires on a far sighting (it is news)", "if wants.anything_new then return true end" in fired)
sys.exit(1 if fails else 0)
