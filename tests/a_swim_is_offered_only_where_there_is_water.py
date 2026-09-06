#!/usr/bin/env python3
"""A swim is offered only where there is water.

Victory Road 3F, 2026-09-06. The page said "the WATER you can ride from
here has 4 spot(s) where its seen ground ends, the nearest at (1,10) —
explore rides to the nearest and sweeps from there", explore rode, and the
walk answered "nothing here is water to surf on". Victory Road has no
water. The same exchange stands 44 times in this run's journal.

The water frontier is the swim flood's frontier minus the walk flood's: the
spots only a swim reaches. The swim flood marked its probe `surfing` on
EVERY step, and the engine's Collision gives a surfing mover the water
tile-pair list in place of the land one (pairBlocked) — the cave's
elevation ledges, which stop a walker, do not stop a "surfer". So the probe
walked over the ledges onto ground no walk reaches, and that ground was
reported as across the water. The mount search in walk_to uses the real
player and real water and could find none, so the two halves of the harness
contradicted each other about the same floor, every round.

A surfer is on water. The probe is surfing only for a step that leaves or
lands on a water cell; a land-to-land step is judged by the land rules.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SHIM = (ROOT / "harness/shim.lua").read_text()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

i = SHIM.index("seen_reach = function(G, sx, sy, surf)")
body = SHIM[i:i + 12000]
ck("the probe is surfing only when the step touches water",
   "local _wet = (surf or p.surfing)\n          and (real_water(G, ow.map, nx, ny)\n"
   "               or real_water(G, ow.map, cur.x, cur.y))" in body
   and "surfing = _wet and true or nil" in body)
ck("...and never for every step", "surfing = (surf or p.surfing) and true or nil" not in body)
ck("real water is the engine's own test, never a walkable tile",
   "if not (map and map.isWaterCell and map:isWaterCell(x, y)) then return false end" in SHIM
   and "if map.isWalkableCell and map:isWalkableCell(x, y) then return false end" in SHIM)
ck("the water frontier is still the swim flood's frontier minus the walk flood's",
   "if not onfoot[f.x .. \",\" .. f.y] then front_water[#front_water + 1] = f end" in SHIM)
ck("the incident is on the record where the rule lives",
   "Victory Road 3F, a floor with no water at all" in body)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
