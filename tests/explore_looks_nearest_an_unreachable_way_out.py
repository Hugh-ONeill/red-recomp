#!/usr/bin/env python3
"""When a floor has unseen ground AND a way out no walk reaches, explore
looks at the unseen ground nearest that way first.

Mt Moon, 2026-08-29 (user: "if something is unreachable it should still
try to explore near there"). Goal-blind still: the preference is for the
floor's own untaken way out, never the objective. The sweep takes
toward_x/toward_y and orders frontier spots by distance to that cell; the
deed passes the first unreachable untaken door; the words say so.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import candidates as C, untried as U, ledger as L   # noqa: E402
sh = (ROOT / "harness" / "shim.lua").read_text()
ex = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
sw = sh[sh.index("function OPS.sweep(G, c)"):sh.index("\nfunction OPS.overlay")]
ck("the sweep orders spots by distance to toward_x/y when given",
   "local tx, ty = tonumber(c.toward_x), tonumber(c.toward_y)" in sw
   and "local da = math.abs(a.x - tx) + math.abs(a.y - ty)" in sw
   and "spots taken nearest (%d,%d) first" in sw)
ck("the deed passes the first unreachable untaken door",
   '_st["toward_x"], _st["toward_y"] = (' in ex and "a way out never " in ex)
e2 = C.make(frontier={U.HERE: []})
o = C.obs(e2, ["5,7"])
o["map"]["warps"][0]["reachable"] = False
o["map"]["frontier"] = [{"x": 20, "y": 3, "d": 2}, {"x": 6, "y": 8, "d": 9}]
o["map"]["seen"] = {"n": 30, "frontier_n": 2}
cands = L.build(e2, o, target="map:CERULEAN_CITY", want_explore=False)
words = L.plan_explore(e2, o, cands, target="map:CERULEAN_CITY")
ck("the words say the sweep looks nearest the untaken way out",
   "walk to the unseen ground nearest door (5,7)" in words and "no walk from here reaches" in words)
o2 = C.obs(e2, [])
o2["map"]["frontier"] = [{"x": 20, "y": 3, "d": 2}]; o2["map"]["seen"] = {"n": 30, "frontier_n": 1}
w2 = L.plan_explore(e2, o2, L.build(e2, o2, target="map:X", want_explore=False), target="map:X")
ck("...and the plain nearest-edge words stay when no such way exists", "nearest edge of the ground you have seen, (20,3)" in w2)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
