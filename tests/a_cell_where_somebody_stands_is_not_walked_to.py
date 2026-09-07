#!/usr/bin/env python3
"""A walk_to that names a cell where a named thing stands puts you beside it
and says who, rather than riding a doorway.

Game Corner, run 16 (2026-09-07): walk_to(9,5) named the Rocket's own cell.
The shim answered "no path", and the executor's fallback rode the front
door out and back in — "a pad you have ridden before was ridden again" —
twice in two attempts, then reported the tile "occupied by the thing lying"
there. The page's own rule says you never walk onto a person and standing
beside them is the whole of reaching them. Now the executor checks the
target cell against the map's objects first, walks to a free neighbour,
and says who stands there and how to press them.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

i = src.find('if "no path" in _d0:')
blk = src[i:i + 3200]
ck("the no-path branch first asks whether a named thing stands on the target cell",
   "_occ = next((o for o in (((_pre or {}).get(\"map\") or {}).get(\"objects\") or [])" in blk
   and blk.find("_occ = next(") < blk.find("_here = self._where(_pre)"))
ck("...walks to a free neighbour", "for _dx, _dy in ((0, 1), (0, -1), (-1, 0), (1, 0)):" in blk)
ck("...and says who stands there and how to press them",
   "that cell is where " in blk and "you never walk onto a {_who}" in blk and '"} is how it is pressed.' in blk)
j = src.find("is how it is pressed", i)
ck("...and rides no doorway for it", src.find("continue", j) < src.find("_pad_recross_for_target", i))
ck("the doorway fallback's own words no longer call every way in a pad",
   src.count("door or a pad) was used again") == 3)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
