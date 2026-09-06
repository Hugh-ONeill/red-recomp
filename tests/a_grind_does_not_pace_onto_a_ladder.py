#!/usr/bin/env python3
"""A grind does not pace onto a ladder, and a cave floor is ground.

Victory Road 2F, 2026-09-06, the pocket where the 3F ladder lands. Three
grinds in a row read "grind() earned 0 exp: ok (map->VICTORY_ROAD_3F,
moved, encounter)" (user: "grinds are producing 0 exp for some reason").
The pacer keeps off warps when it steps between spawning cells, but on an
ISOLATED spawning cell it steps off and back on to roll the encounter, and
that step-off used bare collision. In that pocket the only neighbour is
the ladder: it stepped on, the floor changed, and the grind returned
"encounter" with nothing fought.

And when a grind there did fight, the re-run answered "FAILED — no the
floor anywhere on the ground you have seen of this map", because the scan
for "does this map have any spawning ground" tested for grass alone, which
a cave floor never is, and the noun was "the floor".

Now the step-off refuses a warp cell like every other pace step, the scan
counts cave floor as ground, and the refusal reads as a sentence.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SHIM = (ROOT / "harness/shim.lua").read_text()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

g = SHIM[SHIM.index("function OPS.grind"):SHIM.index("function OPS.grind") + 14000]
ck("the pace between spawning cells still keeps off warps",
   "return map:isWalkableCell(x, y) and not warp_at[x .. \",\" .. y]" in g)
ck("the isolated-cell step-off now keeps off warps too",
   "and not warp_at[(p.cellX + d[1]) .. \",\" .. (p.cellY + d[2])] then\n          walk(G, dn, 1)" in g)
ck("...and the incident is on the record beside it", "grinds are producing 0 exp" in g)
ck("boxed in is explained, not just declared",
   "every neighbour of " in g and "rolls an encounter" in g)
ck("the any-ground scan counts a cave floor as ground",
   "if _gm[xx .. \",\" .. yy] and (anywhere and enc_cell(xx, yy)" in g)
ck("the noun reads as a sentence in every refusal",
   'anywhere and "floor to pace"' in g and '"the floor"' not in g.split("local ground =")[1][:120])

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
