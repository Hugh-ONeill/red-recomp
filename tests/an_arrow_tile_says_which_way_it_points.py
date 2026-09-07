#!/usr/bin/env python3
"""An arrow tile says which way it points, and is never a warp pad.

Rocket Hideout, run 16 (2026-09-07; user: "its also important to distinguish
between the warp pads here and warp pads in saffron since the warps here are
specifically directional pads that you can visually see what direction they
spin you to and dont ever warp you out of the area youre in"). The engine
keeps the two apart already: warp pads are a tile table (FACILITY 32 is
Silph's and Saffron's teleporter), spinners are field data with moves. The
page named a spinner "arrow tile (x,y) slides onto unseen ground" with no
direction, though the arrow is drawn on the tile. Now the frontier entry
carries the spinner's first move as a compass word, the label and the note
say it, and the step reply says the arrow slid you across this floor.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import ledger as L   # noqa: E402
sh = (ROOT / "harness" / "shim.lua").read_text()
lg = (ROOT / "planner" / "ledger.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the shim reads a spinner's first move as a compass word",
   "local function spinner_dir(G, map, x, y)" in sh and 'words = { up = "north", down = "south", left = "west", right = "east" }' in sh)
ck("...and the frontier entry carries it", "dir = spinner_dir(G, ow.map, nx, ny) }" in sh and "dir = f.dir or nil }" in sh)
ck("the step reply says the way it pointed and that it slid across this floor",
   '", pointing " .. _sd' in sh and "an arrow slides you across this floor the " in sh)
c = L.Candidate(key="14,9", kind="frontier", look="arrow"); c.arrow_dir = "east"
ck("the label names the direction", c.label() == "arrow tile (14,9) pointing EAST slides onto unseen ground", c.label())
c2 = L.Candidate(key="3,3", kind="frontier", look="arrow")
ck("...and stays honest without one", c2.label() == "arrow tile (3,3) slides onto unseen ground", c2.label())
ck("the note calls it a slide across this floor, not a warp", "slides you that way across this" in lg)
ck("a warp pad keeps its own word", 'return f"warp pad ({_key}){_tw}"' in lg)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
