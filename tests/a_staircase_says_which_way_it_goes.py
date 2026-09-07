#!/usr/bin/env python3
"""A staircase on the page says which way it is drawn.

Run 16, 2026-09-07: the plan's step was "find the stairs to the upper deck",
every staircase read "stairs/ladder", and the model opened the S.S. Anne's
cabin doors hunting one (user: "it wants to find stairs that go up but
doesnt currently have the language to express that exact desire ... the
actual tiles often show what they are"). planner/engine_warp_looks.py
surveys every warp of every map by the tile the engine reads for its cell
(the cell's bottom-left tile, Map:cellTile) against the floor it leads to;
a tile whose warps all climb is the ascending drawing, all descend the
descending one, in every tileset that has stairs; caves draw ladders. The
shim carries that table and the ledger says "stairs up (2,12)". The label
still never says where a way goes: the direction is what the tile shows.
"""
import re
import sys
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L   # noqa: E402
import engine_warp_looks as W   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

table, by = W.table()
ck("the ship's two staircases are told apart: 57 climbs, 55 descends",
   table.get(("SHIP", 57)) == "stairs_up" and table.get(("SHIP", 55)) == "stairs_down", table)
ck("cave ladders likewise: 26 up, 24 down",
   table.get(("CAVERN", 26)) == "ladder_up" and table.get(("CAVERN", 24)) == "ladder_down")
ck("every tileset with stairs has both directions or a hand note",
   all(table.get((ts, t)) for ts, t in [("GATE", 26), ("GATE", 28), ("LOBBY", 26), ("LOBBY", 28),
                                        ("MANSION", 26), ("MANSION", 28), ("FACILITY", 27), ("FACILITY", 19),
                                        ("CEMETERY", 19), ("CEMETERY", 27), ("MUSEUM", 26), ("MUSEUM", 28)]))
ck("a tile whose warps lead both ways is not labelled (Saffron's pads, Seafoam's current)",
   ("FACILITY", 32) not in table and ("CAVERN", 20) not in table)
ck("a single warp is not a drawing settled (plain floor under a landing)",
   ("FACILITY", 1) not in table)
ck("the survey's evidence is one-way for every labelled tile",
   all((by[k]["up"] == 0) != (by[k]["down"] == 0)
       for k in table if k in by and k not in W.HAND and table[k] != "lift"))   # lifts have no floor to lead to
txt = (ROOT / "planner" / "engine_warp_looks.txt").read_text()
ck("the text table matches the generator",
   all(f"{ts}\t{t}\t{look}\n" in txt for (ts, t), look in table.items()) and len(txt.splitlines()) == len(table))

sh = (ROOT / "harness" / "shim.lua").read_text()
m = re.search(r"local WARP_LOOKS = \{(.*?)\n      \}", sh, re.S)
ck("the shim carries the table", bool(m))
if m:
    ck("...and it is the generator's table, verbatim per tileset",
       all(f'[{t}] = "{look}"' in m.group(1) for (ts, t), look in table.items())
       and 'SHIP         = { [55] = "stairs_down", [57] = "stairs_up" }' in m.group(1))
ck("warp_look answers from it, by the tile the engine reads for the cell",
   "local _wl = WARP_LOOKS[md and md.tileset]" in sh and "_wl[lm:cellTile(x, y)]" in sh
   and "STAIR_TILES" not in sh)

ck("the ledger says the direction in words",
   L.Candidate(key="2,12", kind="door", look="stairs_up").label() == "stairs up (2,12)"
   and L.Candidate(key="2,4", kind="door", look="stairs_down").label() == "stairs down (2,4)"
   and L.Candidate(key="5,7", kind="door", look="ladder_down").label() == "ladder down (5,7)")
ck("...and stays 'stairs/ladder' when the drawing does not settle it",
   L.Candidate(key="1,1", kind="door", look="stairs").label() == "stairs/ladder (1,1)")
ck("a door is still a door", L.Candidate(key="9,11", kind="door").label() == "door (9,11)")

ck("the elevator door is known by its tile (Silph's 88, Celadon's and the car's 56)",
   table.get(("FACILITY", 88)) == "lift" and table.get(("LOBBY", 56)) == "lift")
ck("...and the hideout's mat-drawn entry is not called one",
   ("FACILITY", 66) not in table and ("FACILITY", 82) not in table)
ck("the drawing is consulted before the engine's door-animation list",
   sh.index("local _wl0 = WARP_LOOKS[md and md.tileset]") < sh.index("if lm and lm.isDoorTileCell and lm:isDoorTileCell(x, y) then"))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:300])
sys.exit(1 if bad else 0)
