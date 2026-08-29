#!/usr/bin/env python3
"""Over a mod's 3D world pass the footprint overlay draws only the inset.

The tile overlay maps cells into flat tile space; under the Dramatic Shape
voxel diorama that space does not exist on screen. While a world pipeline
owns the world pass (engine Pipelines.worldPipeline), tiles are skipped and
the inset (the whole-map hud in the corner) is drawn instead; OFF stays off.
"""
import sys
from pathlib import Path
sh = (Path(__file__).resolve().parents[1] / "harness" / "shim.lua").read_text()
o = sh[sh.index("local function draw_seen_overlay()"):]
o = o[:o.index("local function overlay_install")]
checks = [
    ("the overlay asks the engine which pipeline owns the world pass",
     'pcall(require, "src.render.Pipelines")' in o and "pcall(P.worldPipeline)" in o),
    ("tiles are skipped over a diorama", 'if overlay_wants("tiles") and not diorama then' in o),
    ("the inset is drawn over a diorama unless the overlay is off",
     'if overlay_wants("inset") or (diorama and overlay_mode ~= "off") then' in o),
]
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
