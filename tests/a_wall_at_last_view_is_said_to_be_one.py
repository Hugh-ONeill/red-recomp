#!/usr/bin/env python3
"""A wall at last view is said to be one (2026-09-04).

The Game Corner's hidden staircase at (17,4) was a wall when the room was last
on screen; the poster's switch opened it (EVENT_FOUND_ROCKET_HIDEOUT set, on
the model's own recall and ops), and use_warp(17,4) from across the room was
told "nothing can stand ON 17,4" — the words for a tile nobody can ever stand
on, about a tile the observation was listing as a reachable door. The freeze
rule is right: an off-screen tile that was a wall at last view is not routed
into until it is seen again, whatever it is now. The reason given was false,
and it named no way out. Now the refusal says the rule and what lifts it.

Source-shape test against the shim (its walker runs only in the game)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
lua = (ROOT / "harness" / "shim.lua").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

ck("both walkers count the cells the freeze kept them out of",
   lua.count("local gate_unseen, gate_frozen = 0, 0") == 2
   and lua.count('if g == "frozen" then gate_frozen = gate_frozen + 1 end') == 2)
ck("a frozen target is asked about directly",
   'local tgt_frozen = gate and gate(tx, ty, key(tx, ty)) == "frozen"' in lua)
ck("...and is said to be a wall at last view, not a thing nothing can stand on",
   "was a WALL the last time it was on screen and \"\n      .. \"has not been on screen since; ground that was a wall is not \"\n      .. \"routed into until it is SEEN again, whatever it is now. \"" in lua)
ck("...with looking named as what lifts it, from the cell beside it when there is one",
   'From (%d,%d), beside it, it is on screen: walk there and "\n                .. "try again' in lua
   and 'or "Walk toward it until it is on screen, then try again"' in lua)
ck("the never-standable sentence is now only for a target that is not frozen",
   'elseif best == 1 and bx and by then\n    said = said .. (", which is RIGHT BESIDE it — nothing can stand ON "' in lua)
ck("frozen cells along the way are counted for the model, at both walkers",
   lua.count("were not routed into") == 2 and "seeing it \"\n      .. \"again is what lifts that" in lua)
ck("the freeze rule itself is unchanged: on-screen tiles live, a wall-at-last-view frozen",
   "if (WT or {})[nk] ~= false then return false end" in lua)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok   " if ok else "FAIL ") + n)
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
