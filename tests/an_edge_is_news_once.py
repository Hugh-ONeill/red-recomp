#!/usr/bin/env python3
"""An edge is news once.

`until:door` counts a map's edge as a way out — a seam never taken is
door-class — and the sweep fired on it every time one more cell of an edge
already on screen came into view. In Celadon five sweeps asked for a door and
stopped on "this map's edge to the east" or "to the west", a side the run had
seen the round before, a round each, while the Game Corner's door never came
into view (2026-09-04). A side is reported the FIRST time any cell of it is on
screen; extending along a known edge is not a sighting.

Source-level: the shim's sweep is not unit-runnable here; tests/contract.py
boots it.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
shim = (ROOT / "harness" / "shim.lua").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
ck("the sweep remembers which sides were already on screen before this step",
   "local edge_before = {}" in shim and "for k, v in pairs(before or {}) do" in shim
   and "if by == H - 1 then edge_before.south = true end" in shim)
ck("...and reports an edge only when it is new",
   "if edge[d] and not edge_before[d] then" in shim)
ck("until:door still counts a NEW edge as a way out",
   'if wants.door and t.kind == "way" then return true end' in shim)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
