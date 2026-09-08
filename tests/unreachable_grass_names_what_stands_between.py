#!/usr/bin/env python3
"""A grind refused for unreachable grass names what stands between.

"This map HAS grass, but none of it is reachable from where you stand — the
nearest lies at (35,5) ... the walking to do is toward there" — with the
regrown bush at (34,9) across the only way (Route 16, run 16, 2026-09-08).
The walk refusals already list what stands at the edge of the reachable
ground; the grind refusal now gives the same list. Source-anchored (Lua).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sh = (ROOT / "harness" / "shim.lua").read_text()
fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


i = sh.index('return false, ("this map HAS " .. ground .. ", but none of it is "')
blk = sh[i - 600:i + 900]
ck("the refusal asks what stands between the reachable ground and the grass", "local _bb = bushes_blocking(G, ngx, ngy, _rc2)" in blk)
ck("...off a fresh reach fill", "local _rc2 = seen_reach(G) or {}" in blk)
ck("...and names it, nearest first", 'Standing between the ground you can reach and "' in blk and 'table.concat(_bb, ", ")' in blk)
sys.exit(1 if fails else 0)
