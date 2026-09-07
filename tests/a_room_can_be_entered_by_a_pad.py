#!/usr/bin/env python3
"""A floor's other room can be entered by a warp pad (2026-09-04).

The "more than one room" sentence told the model such rooms are entered from
another floor "by stairs that land inside them or by a hole that drops you in".
In Silph Co the way into the President's room is a warp pad, and 11F's lift
landing has the pad at (3,2) on it, seen and unreachable. The sentence now names
a pad as one of the ways, in general terms — which building uses which is not
said. User: "the thing we need to watch out for is regression towards checking
the 11th floor repeatedly despite not being able to access the president".

Source-shape test."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "planner" / "ledger.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
# the block's literals are wrapped differently as it changes (2026-09-07: it
# grew an unseen-ground branch); join adjacent literals and read the words
import re
flat = re.sub(r'"\s*\n\s*"', "", src)
ck("a warp pad is named among the ways into a floor's other room",
   "or by a WARP PAD whose twin stands inside them" in flat)
ck("...as a thing the page names when it is on screen",
   "a pad is one of the things this page names when it is on screen" in flat)
ck("...without naming any building's mechanism", "Silph" not in src[src.index("THIS MAP HOLDS MORE THAN ONE ROOM"): src.index("THIS MAP HOLDS MORE THAN ONE ROOM") + 1200])
ck("the shrug at the end stays", "Which of those this is, this ledger does not know" in flat)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok   " if ok else "FAIL ") + n)
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
