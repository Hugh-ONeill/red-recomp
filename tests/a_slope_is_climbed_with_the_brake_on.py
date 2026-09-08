#!/usr/bin/env python3
"""walk_to on a slope map holds the brake, so the road cannot roll back what
each step gained; and cross carries the walk's own reason when it fails.

Route 17 rolls the bike one cell south on every poll that finds no d-pad
held. walk_to released the d-pad between cells — settle_slide waits for the
player to stand still, and on the slope the player is never still with
nothing held — so every cell a held step gained rolled straight back down.
Run 16 (2026-09-08): three walks to the north gap from the bottom of the
road came back "stuck at (10,143)", the start cell, and the run took the
long way round Kanto. The game's own mask treats a held A or B like a held
direction (the Route 17 sign: "Press the A or B Button to stay in place");
B does nothing else in the overworld, so walk_to holds it through the walk.

MEASURED, not argued (tools/cycling_road_probe.py, a copy of the Fuchsia
checkpoint under the test identity, speed 200): with this shim one
`cross north` from ROUTE_17 (10,143) rode all 143 rows and landed on
ROUTE_16 (3,17) in 0.3s; the previous shim, same probe, same save, came back
"couldn't reach north edge gap (3,0), stuck at (10,143)" after 4.2s.
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


ck("walk_to is a wrapper round its body", "local function walk_to_body(G, c)" in sh and "function OPS.walk_to(G, c)" in sh)
w = sh[sh.index("function OPS.walk_to(G, c)"):sh.index("local function yield_ground(G)")]
ck("the brake is decided by the slope map list and the bike", ".slopeMaps" in w and 'if mm == mid and (G.save or {}).onBike then _brake = true end' in w)
ck("it is held as state only — no press edge that could close a box", 'if _brake then G.input.state["b"] = true end' in w and 'pressQueue' not in w)
ck("...and let go on the way out, whatever the body returned", 'local ok, why = walk_to_body(G, c)\n  if _brake then G.input.state["b"] = false end\n  return ok, why' in w)
body = sh[sh.index("local function walk_to_body(G, c)"):sh.index("function OPS.walk_to(G, c)")]
ck("the body re-holds it at every step, since a tap elsewhere releases state", 'G.input.state["b"] = true       -- the brake, re-held (see OPS.walk_to)' in body)
ck("the reason is written where the next reader will look", "A SLOPE IS CLIMBED WITH THE BRAKE ON" in sh and "settle_slide waits for the player to stand still" in sh)
c = sh[sh.index("function OPS.cross(G, c)"):]
c = c[:c.index("\nfunction OPS.", 10)]
ck("cross keeps walk_to's own words when the gap walk fails", "local _wok, _w = OPS.walk_to(G, { x = ex, y = ey, surf = c.surf," in c and 'if not _wok and _w then _wwhy = tostring(_w) end' in c)
ck("...and says them in the stuck message", '_wwhy and (" — the walk itself said: " .. _wwhy) or ""' in c)
ck("the probe that measured it is kept", (ROOT / "tools" / "cycling_road_probe.py").exists())
ck("a landing on a slope waits for the roll to stop before it is reported", "A SLOPE IS NOT SETTLED UNTIL THE ROLL STOPS" in c and "_patience = 1500" in c)
ck("a crossing says where it began and which gap it took", '(" (from %s (%s,%s)%s)"):format(tostring(startMap), tostring(sx0),' in c and "via the gap at (" in c)
sys.exit(1 if fails else 0)
