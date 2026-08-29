#!/usr/bin/env python3
"""A door no walk from here reaches says which stood-in part of the floor
reaches it, or that none does.

Mt Moon B2F, 2026-08-29 (user watching): "stairs/ladder (5,7) -> UNKNOWN —
you cannot walk to it from where you stand" and nothing more, while the
shim had flooded the seen ground from every other part of B2F the run had
stood in for the head's unreached-ground line. The run climbed back up the
same ladder five times looking for a way none of those parts had. Recall
only; where an unwalked way starts is still not claimed.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import candidates as C, untried as U, ledger as L   # noqa: E402
sh = (ROOT / "harness" / "shim.lua").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
ck("the shim floods each stood-in part and stamps which reach an unreachable door",
   'w.from[#w.from + 1] = m.id .. "|" .. name' in sh and "w.stood_parts = nparts" in sh)
ex = C.make(frontier={U.HERE: []})
o = C.obs(ex, ["5,7", "9,9"])
o["map"]["warps"][0].update({"reachable": False, "from": ["MT_MOON_B2F|20,5"], "stood_parts": 3})
o["map"]["warps"][1].update({"reachable": False, "stood_parts": 3})
cands = {c.key: c for c in L.build(ex, o, target="map:CERULEAN_CITY")}
ck("a part that reaches it is named", "the ground you stood on in MT_MOON_B2F|20,5 DOES reach it" in cands["5,7"].note)
ck("none reaching it is said, with what that means",
   "nor does any of the 3 other part(s) of this floor you have stood in" in cands["9,9"].note
   and "unseen ground on this floor, or another floor" in cands["9,9"].note)
o2 = C.obs(ex, ["5,7"], objects=[{"name": "MTMOONB2F_DOME_FOSSIL", "kind": "npc", "x": 6, "y": 8, "reachable": True}])
o2["map"]["warps"][0]["reachable"] = False
c2 = {c.key: c for c in L.build(ex, o2, target="map:CERULEAN_CITY")}["5,7"]
ck("the nearest thing on your side is named with its kind, distance and press count",
   "MTMOONB2F_DOME_FOSSIL (a fossil, NEVER pressed) stands 2 cell(s) from it" in c2.note
   and "not a claim it is what stops you" in c2.note)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
