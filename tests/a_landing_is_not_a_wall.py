#!/usr/bin/env python3
"""A warp entry on plain floor is crossed, not treated as a wall (2026-09-05).

The engine fires a warp on arrival only when the cell is a warp TILE
(Warp.onArrive -> Map:isWarpTileCell, the tileset's warpTiles/doorTiles).
Anything else is a LANDING: plain floor some other warp points at, and stepping
on it does nothing. warp_look has known this since the Silph 16,10 case; the
reachability floods and the walker did not, and blocked routing through EVERY
warp entry. On SILPH_CO_11F the President's alcove is entered across (5,5) —
tile 31, ordinary floor with a warp entry on it — so the room sealed, he read
"you cannot walk to it from where you stand" on all 53 pages the run took
there, and the leg could not be finished while a player walks straight in
(user: "from physically manipulating the player to that location, it is without
a doubt 100% reachable"). A cell that WOULD fire still stops a route: a door is
an endpoint, not a corridor.

Source-shape test against the shim (its floods run only in the game)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
lua = (ROOT / "harness" / "shim.lua").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("there is one predicate for whether a warp entry seals a route",
   lua.count("local function warp_seals(G, x, y)") == 1)
ck("...it asks the engine whether the cell is a warp TILE",
   "if map:isWarpTileCell(x, y) then return true end" in lua)
ck("...and whether the extra check would fire it in any direction",
   "pcall(WarpM.extraCheck, map, carpets, x, y, dn)" in lua and "if okc and fires then return true end" in lua)
ck("...defaulting to sealing when the engine cannot be asked",
   "if not (map and map.isWarpTileCell) then return true end" in lua)
ck("both reachability floods consult it",
   lua.count("if warp_seals(G, w.x, w.y) then THROUGH[key(w.x, w.y)] = true end") == 2)
ck("...and so does the walker's block list",
   "if not (w.x == tx and w.y == ty) and warp_seals(G, w.x, w.y) then" in lua)
ck("it is defined before its first use (a Lua local is not visible earlier)",
   lua.index("local function warp_seals(G, x, y)") < lua.index("if warp_seals(G, w.x, w.y) then"))
ck("the reason is recorded where the next reader will find it",
   "A LANDING IS NOT A WAY OUT" in lua and "the President's alcove is entered" in lua)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
