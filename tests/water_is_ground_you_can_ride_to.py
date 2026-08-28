#!/usr/bin/env python3
"""The frontier across the water is counted, ridden to, and never called
"done".

Route 23 is mostly water past its first guard. The seen-ground fill
probed every step with surfing=nil, so the frontier read empty on foot,
the page said EVERYTHING YOU CAN REACH HERE IS DONE, and explore walked
six legs back to Route 21's leftovers with the whole unseen north a swim
away (user, 2026-08-28: "sweep brought it back to rt 21 instead of
continuing up victory road").
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import ledger as L            # noqa: E402
import untried as U           # noqa: E402
import candidates as C        # noqa: E402

checks = []
def ck(name, ok): checks.append((name, bool(ok)))
lua = (ROOT / "harness/shim.lua").read_text()
ck("seen_reach takes a surf flag", "seen_reach = function(G, sx, sy, surf)" in lua)
ck("...and the probe surfs when the party is surfing or asked to",
   "surfing = (surf or p.surfing) and true or nil" in lua)
ck("the observation carries the frontier across the water, apart from the foot frontier",
   "m.frontier_water = fw" in lua and "m.seen.frontier_water_n = #front_water" in lua)
ck("...only when someone knows SURF and the party is not already on the water",
   "if seen_reach and _knows and _p and not _p.surfing then" in lua)
src = (ROOT / "planner/executor.py").read_text()
i = src.index('_fw = _m.get("frontier_water") or []')
blk = src[i:i + 1200]
ck("explore rides to the nearest water-frontier spot and sweeps before leaving the map",
   '"surf": True' in blk and '{"op": "sweep"}' in blk and 'step="ride"' in blk)
ck("...and only when SURF is known", 'self._knows_move(obs, "SURF")' in blk)
ck("...and before the fully-worked walk-elsewhere branch", i < src.index("this area is fully worked, so you were walked"))

ex = C.make(explored={U.HERE: {"1,1": {"to": "OUT|0,0", "n": 1}}})
o = C.obs(ex, ["1,1"])
o["map"]["frontier"] = []
o["map"]["frontier_water"] = [{"x": 8, "y": 40, "d": 12}]
o["map"]["seen"] = {"n": 400, "frontier_n": 0, "frontier_water_n": 5}
o["party"] = [{"species": "LAPRAS", "level": 48, "moves": ["SURF", "ICE_BEAM"]}]
text = L.render(L.build(ex, o, target="map:VICTORY_ROAD_1F"), ex, o, target="map:VICTORY_ROAD_1F")
ck("with water ahead, the page says done ON FOOT and names the water frontier",
   "ON FOOT" in text and "5 spot(s)" in text and "(8,40)" in text and "explore rides" in text)
ck("...item 1 rides the water", "1. explore — ride the water" in text)
ck("...and no longer says everything reachable is done or the area is fully worked",
   "EVERYTHING YOU CAN REACH HERE IS DONE" not in text and "NOTHING HERE IS UNTRIED OR UNPRESSED" not in text
   and "FULLY WORKED and so is everywhere" not in text)
o["party"] = [{"species": "PIDGEOT", "level": 50, "moves": ["FLY"]}]
text = L.render(L.build(ex, o, target="map:VICTORY_ROAD_1F"), ex, o, target="map:VICTORY_ROAD_1F")
ck("without SURF the water frontier is not offered", "ON FOOT" not in text and "ride the water" not in text)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
