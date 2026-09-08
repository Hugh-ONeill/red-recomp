#!/usr/bin/env python3
"""A doorway is named with the building it is set in, and with a door of that
same building the run has taken.

Route 16, run 16 (2026-09-08): the sweep reported "a doorway at (17,10)" and
the model took the gate's south-west door for the Fly house, whose own door
at (7,5) was two sweeps further west (user: "should we have it recognize
'building' from the sprites or something?"). A player sees a house with a
door in it, and sees that two doorways sit in one long building. The
footprints come from the engine's block grids (planner/engine_buildings.py);
the shim tags each warp row with its building; the sweep says "a doorway at
(7,5) in a small house"; the ledger's door row says the same and, when
another door of that building has been taken, names where it led.
Recognition, not a peek: an untaken door on a building never entered stays
unnamed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "planner"))
import candidates as C   # noqa: E402
import untried as U      # noqa: E402
import ledger as L       # noqa: E402

fails = []


def ck(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"\n      {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# the generator, on the engine's own data (skipped where gen1recomp is absent)
try:
    import engine_buildings as B
    have = (B.G / "maps.lua").exists()
except Exception:
    have = False
if have:
    BL = B.buildings()
    r16 = BL.get("ROUTE_16") or []
    fly = [b for b in r16 if any(x == 7 and y == 5 for x, y, _ in b["doors"])]
    gate = [b for b in r16 if len(b["doors"]) == 8]
    ck("the Fly house is a small house of its own", fly and B.size_word(fly[0]["w"], fly[0]["h"], fly[0].get("flat")) == "small house", fly)
    ck("the gate's eight doors sit in one building", len(gate) == 1 and all(d == "ROUTE_16_GATE_1F" for _, _, d in gate[0]["doors"]), gate)
    ck("...a large flat-roofed one", gate and "flat-roofed" in B.size_word(gate[0]["w"], gate[0]["h"], gate[0].get("flat")))
    cel = BL.get("CELADON_CITY") or []
    mansion = [b for b in cel if any((x, y) == (24, 9) for x, y, _ in b["doors"])]
    center = [b for b in cel if any((x, y) == (41, 9) for x, y, _ in b["doors"])]
    ck("Celadon's Mansion and Center, wall to wall, are two buildings", mansion and center and mansion[0] is not center[0])
    pal = BL.get("PALLET_TOWN") or []
    ck("Pallet's three buildings are three", len(pal) == 3)
    ck("a cave mouth in rock is no building", not any(d == "CERULEAN_CAVE_1F" for b in BL.get("CERULEAN_CITY", []) for _, _, d in b["doors"]))
else:
    print("skip generator checks: gen1recomp data not present")

# the shim side, source-anchored (Lua)
sh = (ROOT / "harness" / "shim.lua").read_text()
ck("the shim carries the building table", "local BUILDINGS = {" in sh and "ROUTE_16 = {" in sh)
ck("warp rows are tagged with their building", "if d == wk then w.bld = i end" in sh and "m.buildings = _bl" in sh)
ck("the sweep names the building a doorway is set in", 'text = text .. " in a " .. b.look' in sh)
ck("...and the same building's other doorway when it has been on screen", "the same building as the doorway at (%s)" in sh)

# the ledger side
ex = C.make(explored={U.HERE: {"24,4": {"to": "ROUTE_16_GATE_1F|0,2", "n": 4}}},
            frontier={U.HERE: ["17,10", "24,4", "7,5"]})
o = C.obs(ex, ["17,10", "24,4", "7,5"])
o["map"]["buildings"] = [{"x0": 18, "y0": 2, "x1": 23, "y1": 11, "look": "large flat-roofed building", "doors": ["17,10", "24,4"]},
                         {"x0": 6, "y0": 4, "x1": 9, "y1": 5, "look": "small house", "doors": ["7,5"]}]
for w in o["map"]["warps"]:
    w["bld"] = 1 if f"{w['x']},{w['y']}" in ("17,10", "24,4") else 2
cands = L.build(ex, o, target="map:ROUTE_16_FLY_HOUSE")
d17 = next((c for c in cands if c.key == "17,10"), None)
d7 = next((c for c in cands if c.key == "7,5"), None)
d24 = next((c for c in cands if c.key == "24,4"), None)
ck("an untaken door's row says what it is set in", d17 is not None and "in a large flat-roofed building" in d17.label(), getattr(d17, "label", lambda: None)())
ck("...and names the taken door of the same building and where it led",
   d17 is not None and "the same building as door (24,4), which you have taken — it is ROUTE_16_GATE_1F" in (d17.note or ""), getattr(d17, "note", None))
ck("the house door says house", d7 is not None and "in a small house" in d7.label(), getattr(d7, "label", lambda: None)())
ck("a house with no taken door names nothing beyond itself", d7 is not None and "same building" not in (d7.note or ""), getattr(d7, "note", None))
ck("a taken door does not repeat its own building's story", d24 is not None and "same building" not in (d24.note or ""), getattr(d24, "note", None))
sys.exit(1 if fails else 0)
