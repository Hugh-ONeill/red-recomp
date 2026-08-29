#!/usr/bin/env python3
"""cross(skip=N) crosses at a cell that IS open when the Nth is not.

Pallet Town, 2026-08-29: the replayed hop north#skip1 wanted the second
seam cell while a wandering girl stood on it; one cell qualified, nothing
was returned, and the op said "cannot be walked to from here — no walkable
path reaches it" about a seam its own diagnostic put 0 cells away — the
strong verdict that mints no_cross proofs, about a seam crossed twice that
day. Now the finder remembers the cells it passed over, crosses at the
last one when the asked-for one is missing, and the crossing says which.
"""
import sys
from pathlib import Path
sh = (Path(__file__).resolve().parents[1] / "harness" / "shim.lua").read_text()
b = sh[sh.index("local function bfs_to_edge(G, dir, skip, surf, blind)"):]
b = b[:b.index("\nlocal OPS = {}")]
checks = [
    ("the finder remembers qualifying cells it skipped", "fb_x, fb_y = x, y" in b),
    ("...and returns the last one with a why when the asked-for one is missing",
     "you asked for seam cell #%d and only %d of that " in b
     and b.index("if fb_x then") < b.index('return nil, nil, ("BFS from %d,%d walked')),
    ("the crossing says which cell it used", '.. ((ex and bfs_why) and (" — " .. tostring(bfs_why)) or "")' in sh),
]
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
