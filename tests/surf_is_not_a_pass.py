"""Surfing is not a general pass through the map.

Collision.canMove reads `mover.surfing` TWICE: it lets a rider enter water,
and it swaps the tile-pair list from LAND to WATER (src/world/Collision.lua
`pairBlocked`). The land list is what makes a cave a maze — CAVERN's
elevation pairs — so a swim flood run with surfing set for the whole walk
went straight through Victory Road's ledges on a floor with NO WATER, and
the ledger then told the run its stairs were reachable "but the WATER does:
a party Pokemon knows SURF" (user, 2026-08-24: "it thinks it needs to surf
but it needs to use strength").

You ride only when you are ON water or stepping ONTO it.
"""
import re
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
shim = (ROOT / "harness" / "shim.lua").read_text()
GAME = pathlib.Path("/home/wiz/Developer/gen1recomp")

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


i = shim.find("local probe = setmetatable({ cellX = cur.x")
block = shim[max(0, i - 1400):i + 300]

ck("the swim flood exists", i > 0)
ck("surfing is gated on a water cell", "isWaterCell(cur.x, cur.y)" in block)
ck("...or on stepping onto one", "isWaterCell(nx, ny)" in block)
ck("the probe no longer rides unconditionally",
   "surfing = surf or nil" not in block)
ck("it says why the land rules matter", "tile-pair" in block.lower())

# the engine really does swap the list on that flag — if this stops being
# true the gate above is unnecessary and the comment is wrong
coll = (GAME / "src" / "world" / "Collision.lua").read_text()
ck("Collision still swaps land/water pairs on `surfing`",
   re.search(r"mover\.surfing and tilePairs\.water or tilePairs\.land", coll)
   is not None)
ck("...and still lets a rider enter water",
   "mover.surfing and map:isWaterCell" in coll)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
