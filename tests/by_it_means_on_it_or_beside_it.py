#!/usr/bin/env python3
""""Standing by" a doorway means on it or beside it (2026-09-05).

The warp-blocker radius was 2 — a room away. Silph 11F's warp is at (5,5) and
the PRESIDENT stands at (7,5), two cells off and in nobody's way, so every
use_warp(5,5) came back "somebody is standing by it: SILPHCO11F_SILPH_PRESIDENT".
The executor filed that as a door held against the run, and the one man the leg
exists to speak to became the guard barring the only way to himself (user: "its
saying it cant reach him from there, where it very much can ... i cant tell you
how frustrating it is to see it stand there and then leave"). A person blocks a
doorway by standing ON it or on the tile you step through; further off is
scenery. The doorstep case this guard exists for — Saffron's Rockets one tile
below a door — is distance 1 and still caught.

Source-shape test against the shim (its walker runs only in the game)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
lua = (ROOT / "harness" / "shim.lua").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ck("the blocker radius is on-it-or-beside-it, not a room away",
   "+ math.abs((npc.cellY or -99) - t.y) <= 1" in lua
   and "+ math.abs((npc.cellY or -99) - t.y) <= 2" not in lua)
ck("...and it says why in the run's own case",
   "the one man the leg exists to speak to" in lua and "PRESIDENT" in lua)
ck("the message it guards is unchanged",
   'return false, "couldn\'t reach the warp tile — somebody is standing by "' in lua)
ck("a wanderer is still distinguished from a posted guard", '_mv == "WALK" and " (who wanders)"' in lua)

# the executor still records a doorstep holder, which is the distance-1 case
src = (ROOT / "planner" / "executor.py").read_text()
ck("the executor's doorstep blocker still keys off that message",
   'somebody is standing by it: ' in src and '"(who wanders)" not in note' in src)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
