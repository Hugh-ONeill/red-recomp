#!/usr/bin/env python3
"""A hole coming into view is reported as a hole (footprint leftover (d)).

sweep's came_into_view called every warp entry "a doorway" and knew nothing
of the script-declared drop cells that are in no warp table (the Mansion's
three) — so a way DOWN that a player sees as a gap in the floor was either
mislabelled or unreported until the next observation listed it. Guards:
warps are labelled by their look (hole / pad / doorway, the same engine
tests the observation uses, asked only AT warp cells), the script holes are
watched too, the hole line says it is one-way, until:"door" also stops at a
hole, and the model's vocabulary lists "hole".
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
sw = sh[sh.index("function OPS.sweep(G, c)"):]
sw = sw[:sw.index("\nfunction OPS.overlay")]
checks = []
def ck(name, ok): checks.append((name, bool(ok)))
ck("sweep watches the script-declared drop cells as well as the warp table",
   'MS.get(map0)' in sw and "script_holes[hx .. \",\" .. hy] = true" in sw
   and "if warps[k] or script_holes[k] then" in sw)
ck("a warp is labelled by its look, asked only at warp cells",
   "local function way_look(x, y)" in sw
   and "ow.map:warpPadOrHoleAt(x, y)" in sw and "isDoorTileCell(x, y)" in sw)
ck("a boulder hole is reported as a HOLE that takes a boulder; a plain drop as a one-way exit",
   'kind = "hole"' in sw and 'text = ("a HOLE in the floor at " .. lab' in sw
   and "a BOULDER shoved onto it falls" in sw
   and 'text = ("a one-way DROP at " .. lab .. " — an exit like a doorway "' in sw
   and "no climbing" in sw)
ck("adjacent same-destination drop cells are ONE drop (the doorway rule), reported once",
   "local function drop_groups(cells)" in sh and "local gids = drop_groups(_hcells)" in sw
   and "if look == \"hole\" and gids[k] and reported[gids[k]] then" in sw
   and '" — ONE drop, " .. #tiles .. " tiles wide"' in sw)
ck("...the observation stamps the group id and never the destination",
   'hh.drop = _gid[hh.x .. "," .. hh.y]' in sh and "dest stays here" in sh)
ck("the split is data (the boulder-hole list), not a map name",
   "local bh_set = {}" in sw and "_v2.boulder_holes" in sw
   and "G.data.field.seafoam" in sw and 'if bh_set[k] then' in sw
   and "MANSION" not in sw)
ck("the observation flags a drop that is also a boulder hole",
   'if _bhs[_h.x .. "," .. _h.y] then _h.boulder = true end' in sh)
# the ledger's head splits the same way
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import candidates as C, untried as U, ledger as L   # noqa: E402
_ex = C.make(frontier={U.HERE: []})
_o = C.obs(_ex, ["1,0"])
_o["map"]["holes"] = [{"x": 16, "y": 14, "reachable": True, "drop": 1},
                      {"x": 17, "y": 14, "reachable": True, "drop": 1},
                      {"x": 23, "y": 15, "reachable": True, "boulder": True, "drop": 2}]
_pg = L.render(L.build(_ex, _o, target="flag:X"), _ex, _o, target="flag:X")
ck("the ledger says ONE-WAY DROP, names the boulder hole, and calls the rest exits",
   "2 ONE-WAY DROP(S) IN IT" in _pg and "(23,15) is also a HOLE" in _pg
   and "the rest are exits like a doorway" in _pg and "floor below" not in _pg)
ck("...and folds the two tiles of one drop into one label",
   "(16,14)+(17,14)" in _pg and "ONE drop wider than one cell" in _pg)
ck("a pad is a pad, a door a doorway",
   "a warp pad at (%d,%d)" in sw and "a doorway at (%d,%d)" in sw)
ck("until:door also stops at a hole",
   'if wants.door and t.kind == "hole" then return true end' in sw)
ck("the model's vocabulary lists hole among the until kinds",
   '"until":"door"|"person"|"item"|"sign"|"hole"|"map_change"' in ex)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
