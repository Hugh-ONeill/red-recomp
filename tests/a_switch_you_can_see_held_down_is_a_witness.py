#!/usr/bin/env python3
"""A switch you can see held down is a witness that its way is open.

Victory Road 3F, 2026-09-06, the first leg of the relaunch. The model had
pushed the boulder onto the switch at (3,5); the page said, from the
boulder visibly on the switch, "THAT WAY IS OPEN RIGHT NOW" about the
barrier at (6,10); and sweep(until=map_change) answered "swept 0 step(s)
... nothing more to see from ground you can reach" (user: "sweep should
have swept the rest of the map").

Both were true of their own rules. The footprint freeze snapshots a cell's
passability only while it is ON SCREEN, so the barrier — eight rows below
the switch — stayed a WALL in the sidecar until the run walked back to look,
and the sweep's flood would not cross it. The freeze is right about a
shutter flipped from somewhere else on the floor (the Mansion), because
nothing the player can see says what it did. A boulder switch is different:
the game's rule ties the boulder on the switch to the barrier open, and the
boulder IS on the screen. That is a witness, and the page was already
citing it.

So while the switch is in view, the barrier block's live passability is
written into the snapshot as if seen, and every flood, walk and sweep
follows. It reads the BLOCK, never the boulder: the game keeps the barrier
in an event flag, re-applies it on every floor entry, and returns the
boulders to their starts, so on 2F and 3F the way stays open with the
boulder back where it began, while 1F's flag is cleared by entering 2F or
the Plateau lobby and Route 23 clears all of 2F's and 3F's (story.lua,
route_23.lua; the user saw both, 2026-09-06). Only cells the run has
already SEEN are touched: the unseen gate is never lifted by this.
"""
from __future__ import annotations
import re, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SHIM = (ROOT / "harness/shim.lua").read_text()
checks = []
def ck(name, cond): checks.append((name, bool(cond)))

ck("the witness is a pure function of the map, the player, the view data and the two masks",
   "local function switch_witness(map, px, py, view, t, wt)" in SHIM)
ck("...keyed on the SWITCH being on screen, not the barrier",
   "sx >= px - VIEW_L and sx <= px + VIEW_R" in SHIM
   and "sy >= py - VIEW_U and sy <= py + VIEW_D" in SHIM)
ck("...writing the barrier BLOCK's four cells", "local x, y = bx * 2 + dx, by * 2 + dy" in SHIM)
ck("...only where the run has already seen", "if t[k] then\n            local wcell" in SHIM)
ck("...into the same snapshot the freeze reads", "if wt[k] ~= wcell then wt[k] = wcell; dirty = true end" in SHIM)
ck("the painter calls it after the viewport, with the game's own switch table",
   'MS.get(map.id) or nil\n    if view and switch_witness(map, p.cellX, p.cellY, view, t, wt) then' in SHIM)
ck("the viewport snapshot itself is unchanged",
   "if wt[k] ~= wcell then wt[k] = wcell; seen_dirty = true end" in SHIM)

if shutil.which("luajit"):
    m = re.search(r"local function switch_witness\(map, px, py, view, t, wt\).*?\nend\n", SHIM, re.S)
    ck("the witness extracts", bool(m))
    lua = r'''
local os = require("os")
VIEW_L, VIEW_R, VIEW_U, VIEW_D = 4, 5, 4, 4
''' + m.group(0) + r'''
local ok = true
local function ck(name, got, want)
  if got ~= want then ok = false; print("FAIL " .. name .. " got=" .. tostring(got))
  else print("ok   " .. name) end
end
-- Victory Road 3F as it stood: switch cell (3,5), barrier block (3,5) -> cells 6..7 x 10..11
local view = { boulder_switches = { { 3, 5, 3, 5, 1, 2 } } }
local open = { ["6,10"] = true, ["7,10"] = true, ["6,11"] = false, ["7,11"] = false }
local map = { isWalkableCell = function(self, x, y) return open[x .. "," .. y] == true end }
local t  = { ["6,10"] = true, ["7,10"] = true, ["7,11"] = true }          -- (6,11) never on screen
local wt = { ["6,10"] = false, ["7,10"] = false, ["7,11"] = false }        -- all walls at last view
local d = switch_witness(map, 3, 2, view, t, wt)                           -- player at (3,2): switch in view
ck("a switch in view writes its barrier's live state", d, true)
ck("...the opened cells are open now", wt["6,10"] == true and wt["7,10"] == true, true)
ck("...a barrier cell that is still solid stays a wall", wt["7,11"], false)
ck("...and a cell never on screen is not invented", wt["6,11"], nil)
-- the flag was cleared elsewhere (Route 23) and the floor re-entered: the
-- block is solid again although nothing about the boulder says so
open["6,10"], open["7,10"] = false, false
d = switch_witness(map, 3, 2, view, t, wt)
ck("a barrier shut again by a reset is written shut, from the block not the boulder",
   d and wt["6,10"] == false and wt["7,10"] == false, true)
-- the switch is off screen: nothing is claimed
open["6,10"], open["7,10"] = true, true
d = switch_witness(map, 20, 20, view, t, wt)
ck("a switch off screen says nothing", d, false)
ck("...and the snapshot is untouched", wt["6,10"], false)
ck("no switch data, no claim", switch_witness(map, 3, 2, nil, t, wt), false)
os.exit(ok and 0 or 1)
'''
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as f:
        f.write(lua); path = f.name
    r = subprocess.run(["luajit", path], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        ck("luajit: " + line[5:], line.startswith("ok"))
    ck("luajit run exits clean", r.returncode == 0)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
