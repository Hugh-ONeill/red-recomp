"""Water is a tileset fact before it is a tile fact (2026-08-26).

Map:isWaterCell says so in its own comment — "Tileset membership in
water_tilesets.asm is checked by the caller" — and no caller in shim.lua ever
did. SILPH_CO_11F is tileset INTERIOR, which is NOT in field.waterTilesets, and
two of its solid decorative tiles carry ids that are water ids elsewhere. The
unwalkable test already in real_water passed them, the page said "THIS FLOOR
HAS WATER: 2 cell(s), the nearest at (7,4) ... nobody in the party knows SURF",
and the run concluded the SILPH PRESIDENT was across a lake and left the floor
to go and find SURF — with the boardroom door a few steps south (user,
2026-08-26).

The engine's own gate is OverworldState:tilesetHasWater()."""
import sys, re
from pathlib import Path

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

lua = Path("harness/shim.lua").read_text()

ck("the tileset gate exists", "local function tileset_has_water(G, map)" in lua)
g = lua[lua.find("local function tileset_has_water"):][:900]
ck("...reading the engine's own waterTilesets list",
   "G.data.field" in g and "waterTilesets" in g)
ck("...memoised per tileset name", "_WATER_TS[ts]" in g)
ck("...and false when the tileset is unknown",
   "if not ts then return false end" in g)

r = lua[lua.find("local function real_water(G, map, x, y)"):][:500]
ck("real_water asks the tileset FIRST",
   r.index("tileset_has_water(G, map)") < r.index("map:isWaterCell(x, y)"))
ck("...and still requires the cell to be unwalkable",
   "map:isWalkableCell(x, y) then return false end" in r)

# every model-visible claim goes through it
raw = [l for l in lua.splitlines()
       if "isWaterCell" in l and "real_water" not in l
       and "tileset_has_water" not in l and not l.lstrip().startswith("--")]
ck("no model-visible water claim calls isWaterCell raw",
   all(("afloat" in l or "p.surfing" in l
        or "if map.isWaterCell and map:inBounds(wx, wy)" in l
        or "and map:isWaterCell(wx, wy) then" in l
        or "if not (map and map.isWaterCell and map:isWaterCell(x, y))" in l)
       for l in raw))
ck("the surfing encounter mirror is deliberately untouched",
   any("p.surfing" in l for l in raw))

for site in ("this = real_water(G, map, cx, cy)",        # the sketch
             "elseif lm and real_water(G, lm, cx, cy)",  # the frontier
             "if surf and (real_water(G, ow.map, cur.x, cur.y)",  # swim flood
             "if d2 and real_water(G, ow.map, x + d2[1], y + d2[2])",
             "if real_water(G, ow.map, a[1], a[2])",     # interact approach
             "and real_water(G, map, xx, yy) then"):  # grind note (seen-mask first)
    ck(f"gated: {site[:44]}", site in lua)

ck("the floor-water counter skips an indoor tileset entirely",
   "if map.isWaterCell and tileset_has_water(G, map) then" in lua)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
