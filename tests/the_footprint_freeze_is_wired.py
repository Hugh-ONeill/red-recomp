#!/usr/bin/env python3
"""The freeze is wired into the flood, the viewport scan, and persistence.

Guards that the pure decision (tested in
the_footprint_freezes_offscreen_state.py) is actually consulted by
seen_reach, that walkability is snapshotted for every in-view cell, that
an off-screen switch's live position is dropped, and that the frozen data
persists in a shim-only sidecar (seen.json keeps its Python-parsed form).
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "harness" / "shim.lua").read_text()
checks = []
def ck(name, ok): checks.append((name, bool(ok)))
ck("seen_reach consults the freeze decision",
   "seen_wall_since_view(ow.map, WT" in sh and "and not hidden_open(nx, ny, nk) then" in sh)
ck("the viewport scan snapshots on-foot walkability per in-view cell",
   "local wt = WALK_of(map.id)" in sh and "if wt[k] ~= wcell then wt[k] = wcell" in sh)
ck("an off-screen switch's live position is dropped",
   "AN OFF-SCREEN SWITCH'S POSITION IS NOT KNOWN" in sh and "e.open_now = nil" in sh)
ck("the freeze rides a shim-only sidecar, not seen.json",
   'WALK_FILE = BRIDGE .. "/seen_walk.json"' in sh and "seen.json keeps its list-of-cells" in sh)
ck("the sidecar is written and loaded",
   sh.count("WALK_FILE") >= 3 and "load(wbody" in sh)
# seen.json's own writer is untouched (still a list of cell keys the Python side parses)
ck("seen.json still writes a bare cell list",
   '("  [%q] = { %s },\\n"):format(mid, table.concat(cells, ","))' in sh)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
