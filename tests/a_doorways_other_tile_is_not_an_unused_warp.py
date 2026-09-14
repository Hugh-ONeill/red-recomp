#!/usr/bin/env python3
"""The other tile of a doorway you came in by is not an unused warp.

The page has two halves. The ledger folds a doorway's tiles into one row,
keyed by the most-walked tile: "door (4,7), two tiles wide -> ROUTE_2|3,43
-- the door you came in by; taken". The observation (model_view) listed
every warp tile on its own and looked walked_to up per TILE, so in the
forest's south gate (4,7) said where it led and (5,7), the same opening,
said nothing. Read together: "I see a warp at (5,7) that I haven't used
yet; I will use it to proceed toward the forest" -- and the run walked
back out onto Route 2 (2026-09-14, user: "its still seeing the warp it
came in from as unused ... doesnt it already know where it goes?"). The
same gate and the same tile cost a round on 2026-08-29 and 2026-09-07;
three rewordings of the ledger row could not fix what the other half of
the page kept saying.

Now model_view groups tiles with the relation the ledger uses
(_door_groups: orthogonally adjacent, same destination), gives every tile
of a walked doorway the doorway's destination, and says the width as a
count. No tile is hidden -- either is the same use_warp -- and no extra
coordinate is written for the model to take as another door.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

GATE = {"id": "VIRIDIAN_FOREST_SOUTH_GATE", "region": "5,0",
        "warps": [{"x": 4, "y": 7, "dest": "ROUTE_2", "reachable": True},
                  {"x": 5, "y": 7, "dest": "ROUTE_2", "reachable": True},
                  {"x": 4, "y": 0, "dest": "VIRIDIAN_FOREST", "reachable": True},
                  {"x": 5, "y": 0, "dest": "VIRIDIAN_FOREST", "reachable": True}]}
WALKED = {("VIRIDIAN_FOREST_SOUTH_GATE", "4,7"): "ROUTE_2|3,43"}   # landed on 4,7 only

def view(m, walked=WALKED):
    o = E.model_view({"map": dict(m), "party": []},
                     walked_dest=lambda mid, k: walked.get((mid, k)))
    return {f"{w['x']},{w['y']}": w for w in o["map"]["warps"]}

ws = view(GATE)
ck("every tile is still listed", sorted(ws) == ["4,0", "4,7", "5,0", "5,7"], sorted(ws))
ck("the engine's destination is stripped from all of them",
   not any("dest" in w for w in ws.values()))
ck("the tile you landed on says where it leads",
   ws["4,7"].get("walked_to") == "ROUTE_2|3,43")
ck("...AND SO DOES THE OTHER TILE OF THE SAME DOORWAY -- this is the fix",
   ws["5,7"].get("walked_to") == "ROUTE_2|3,43", ws["5,7"])
ck("the north doorway, never walked, still says nothing about where it leads",
   "walked_to" not in ws["4,0"] and "walked_to" not in ws["5,0"])
ck("each tile of a two-tile doorway says the doorway is two tiles",
   all(ws[k].get("doorway_tiles") == 2 for k in ws), ws)
ck("...as a count, never as another coordinate",
   all(isinstance(ws[k]["doorway_tiles"], int) for k in ws))

# ---- what does not fold ----------------------------------------------------
STAIRS = {"id": "CELADON_MANSION_2F", "region": "1,1",
          "warps": [{"x": 6, "y": 1, "dest": "CELADON_MANSION_1F"},
                    {"x": 7, "y": 1, "dest": "CELADON_MANSION_3F"},
                    {"x": 2, "y": 9, "dest": "CELADON_MANSION_ROOF"}]}
ws2 = view(STAIRS, {("CELADON_MANSION_2F", "6,1"): "CELADON_MANSION_1F|1,1"})
ck("adjacent tiles to DIFFERENT places are separate doors",
   "doorway_tiles" not in ws2["6,1"] and "doorway_tiles" not in ws2["7,1"])
ck("...and one's destination is not lent to the other",
   ws2["6,1"].get("walked_to") == "CELADON_MANSION_1F|1,1"
   and "walked_to" not in ws2["7,1"])
ck("a lone door carries no width", "doorway_tiles" not in ws2["2,9"])

ck("the relation is the ledger's own (_door_groups), not a second one",
   "Executor._door_groups(_mm.get(\"warps\")" in (ROOT / "planner" / "executor.py").read_text())

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
