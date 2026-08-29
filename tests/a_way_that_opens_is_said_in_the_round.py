#!/usr/bin/env python3
"""When an op makes an unreachable way reachable, the round says which.

Mt Moon B2F, 2026-08-29 (user: "what could it have seen at the fossils
that it picked up the fossil but didnt continue on to the unseen/unwalked
ground"): the run pressed the DOME FOSSIL, answered yes and walked back to
1F IN THE SAME MACRO — written before the fossil was taken — so the ladder
(5,7) that had just become walkable was never on any page. The fossils
stand in that floor's neck; the observation carries every way's reachable
flag before and after. Say which flipped; what to do about it stays the
model's.
"""
import sys
from pathlib import Path
ex = (Path(__file__).resolve().parents[1] / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
ck("the round compares the ways' reachable flags before and after the op",
   "_was = {f\"{w.get('x')},{w.get('y')}\"" in ex
   and "_opened = sorted(_was & _now)" in ex)
ck("...only on the same map (after a warp the comparison means nothing)",
   '_pm.get("id") and _pm.get("id") == _nm.get("id")' in ex)
ck("...and says which way opened, in the round's own words",
   'AND THAT OPENED A WAY: ' in ex
   and "can now be walked to from where you " in ex and "it could not before" in ex)
ck("...and journals it", 'self.log("way_opened", subgoal=sg.get("id"), op=op,' in ex)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
