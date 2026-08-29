#!/usr/bin/env python3
"""A tile's EXISTENCE is known once seen, but its PASSABILITY only as of
the last time it was on screen (user, 2026-08-28: "if an area is already
seen but can update like the mansion shutter doors we dont have it set so
that the bot has to see it updated to know that its actually updated").

seen_reach freezes the change: it will not route through an off-screen
seen tile that was a wall at last view but is walkable now. This extracts
the real decision function `seen_wall_since_view` from harness/shim.lua
and exercises every branch in luajit — no game needed, deterministic.
"""
from __future__ import annotations
import re, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

if not shutil.which("luajit"):
    print("ok   (skipped: no luajit)"); sys.exit(0)

src = (ROOT / "harness" / "shim.lua").read_text()
m = re.search(r"seen_wall_since_view = function.*?\nend\n", src, re.S)
if not m:
    print("FAIL could not extract seen_wall_since_view from shim.lua"); sys.exit(1)
fn = m.group(0)

lua = fn + r'''
-- a stub map whose live on-foot walkability is a lookup we control
local function stubmap(walk)
  return { isWalkableCell = function(self, x, y) return walk[x..","..y] == true end }
end
local VL,VR,VU,VD = 4,5,4,4
local rpx, rpy = 20, 20              -- player far from the tiles under test
local ok = true
local function ck(name, got, want)
  if got ~= want then ok = false; print("FAIL "..name.." got="..tostring(got)) 
  else print("ok   "..name) end
end
-- an ON-SCREEN tile is always live (never frozen), even if it was a wall
ck("on-screen tile is live, not frozen",
   seen_wall_since_view(stubmap({["20,20"]=true}), {["20,20"]=false},
                        rpx, rpy, 20, 20, "20,20", VL,VR,VU,VD), false)
-- OFF-SCREEN, was a wall at last view, walkable now -> HIDE the change
ck("off-screen wall-since-seen that opened is hidden",
   seen_wall_since_view(stubmap({["40,40"]=true}), {["40,40"]=false},
                        rpx, rpy, 40, 40, "40,40", VL,VR,VU,VD), true)
-- OFF-SCREEN, was a wall, still a wall -> nothing to hide (live blocks it)
ck("off-screen wall that stayed a wall is not flagged",
   seen_wall_since_view(stubmap({["40,40"]=false}), {["40,40"]=false},
                        rpx, rpy, 40, 40, "40,40", VL,VR,VU,VD), false)
-- OFF-SCREEN, was OPEN at last view -> governed by live, not frozen
ck("off-screen tile last seen open is not frozen",
   seen_wall_since_view(stubmap({["40,40"]=true}), {["40,40"]=true},
                        rpx, rpy, 40, 40, "40,40", VL,VR,VU,VD), false)
-- OFF-SCREEN, never snapshotted (old run, nil) -> no claim, live governs
ck("a tile never snapshotted makes no claim",
   seen_wall_since_view(stubmap({["40,40"]=true}), {},
                        rpx, rpy, 40, 40, "40,40", VL,VR,VU,VD), false)
-- the viewport box edges count as on-screen
ck("the far edge of the view box is on-screen",
   seen_wall_since_view(stubmap({["25,24"]=true}), {["25,24"]=false},
                        rpx, rpy, 25, 24, "25,24", VL,VR,VU,VD), false)
ck("one past the view box is off-screen",
   seen_wall_since_view(stubmap({["26,20"]=true}), {["26,20"]=false},
                        rpx, rpy, 26, 20, "26,20", VL,VR,VU,VD), true)
os.exit(ok and 0 or 1)
'''
with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as f:
    f.write("local os = require('os')\n" + lua)
    path = f.name
r = subprocess.run(["luajit", path], capture_output=True, text=True)
sys.stdout.write(r.stdout)
if r.returncode != 0:
    sys.stderr.write(r.stderr)
sys.exit(r.returncode)
