#!/usr/bin/env python3
"""A wild encounter is not a script tile.

Victory Road 3F, 2026-09-06. grind paced a pocket, fought three wilds, and
the re-run answered "FAILED — boxed in on floor to pace — every neighbour of
this cell is a wall, a warp or a person" on open cave floor (user: "not
really true here though?"). Three of those and the strike rule refused
grind for the whole region under every level target the plan had.

The cause was two rules meeting. walk() files the cell it just stepped
onto as a SCRIPT TILE when something other than the overworld is on the
stack and it is not a battle — meant for trainers that walk up and signs
that open on their own. The engine pushes a BattleTransition (the wipe)
before the battle state, and for those frames the top is neither, so every
cell where a fight began became a script tile. grind keeps off script
tiles when it picks spawning ground, and since yesterday its step-off does
too — so after a few fights in a small pocket every neighbour was one.

Now walk() asks the engine whether the thing on top is its BattleTransition
and files nothing for a fight beginning. Fixture-driven probes could not
reproduce this at the test speed because the wipe was already a battle by
the time the step settled; the live run at its own pace caught it every
time, which is why this is pinned to the source and the incident.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SHIM = (ROOT / "harness/shim.lua").read_text()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

i = SHIM.index("local function walk(G, dir, steps)")
w = SHIM[i:i + 5000]
ck("walk() still files a script tile for a non-battle screen after a step",
   "local t = trigger_cells(G)" in w and "t[k] = (t[k] or 0) + 1" in w)
ck("...but asks the engine whether the screen is its battle wipe",
   'pcall(require, "src.render.BattleTransition")' in w
   and "getmetatable(top) == BT" in w)
ck("...and files nothing for a fight beginning",
   "and not (top.enemy or top.kind) and not _wipe" in w)
ck("grind keeps off script tiles as before, so the fix had to be at the source",
   'for k in pairs(trigger_cells(G)) do warp_at[k] = true end' in SHIM)
ck("the incident is on the record where the rule lives", "not really true here though?" in w)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
