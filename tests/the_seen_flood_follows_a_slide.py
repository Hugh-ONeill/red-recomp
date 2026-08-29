#!/usr/bin/env python3
"""Arrow tiles: the seen-only flood follows the slide, and a slide onto
ground never on screen is a frontier spot of its own kind.

Footprint leftover (c). warp_reach and both walkers followed
spinner_landing; seen_reach expanded FROM an arrow as if it were floor and
never followed it, so a spinner floor (Rocket Hideout B3F) read reachable
where no walk stands and unreachable where the slide puts you. Guards:
the seen flood consults spinner_landing, reaches the arrow without
expanding from it, queues a SEEN landing, and files an UNSEEN landing as a
frontier entry with slide=true on the arrow; the observation carries the
flag; the walker may aim AT an arrow (stepping on is the act) and reports
where the slide put you; sweep and walk_to let a slide finish before
reading the world; the ledger's row and explore's words say ARROW.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
sh = (ROOT / "harness" / "shim.lua").read_text()
import candidates as C   # noqa: E402
import untried as U      # noqa: E402
import ledger as L       # noqa: E402
checks = []
def ck(name, ok): checks.append((name, bool(ok)))

sr = sh[sh.index("seen_reach = function(G, sx, sy, surf)"):]
sr = sr[:sr.index("\nend\n") + 5]
ck("seen_reach consults spinner_landing on every accepted step",
   "local lx2, ly2 = spinner_landing(G, ow.map, nx, ny)" in sr)
ck("...the arrow is reached but not expanded from; a SEEN landing is queued",
   "dist[nk] = dist[ck] + 1\n            local lk2 = key(lx2, ly2)" in sr
   and "dist[lk2] = dist[ck] + 2\n                q[#q + 1] = { x = lx2, y = ly2 }" in sr)
ck("...the landing honors the freeze too",
   "not hidden_open(lx2, ly2, lk2)" in sr)
ck("...an UNSEEN landing files the arrow as a slide frontier spot",
   "front[#front + 1] = { x = nx, y = ny, d = dist[ck] + 1,\n"
   "                                    slide = true }" in sr)
ck("the observation carries the slide flag",
   "fl[i] = { x = f.x, y = f.y, d = f.d, slide = f.slide or nil }" in sh)
ck("the walker may aim AT an arrow (stepping on is the act)",
   "if nx == tx and ny == ty then return first end\n"
   "            if sx == tx and sy == ty then return first end" in sh)
ck("walk_to reports where the slide put you, once, instead of re-pathing",
   "stepped onto the arrow tile at (%d,%d) and were " in sh
   and "local _arrow = spinner_landing(G, ow.map, c.x, c.y) ~= nil" in sh)
ck("sweep and walk_to let a slide finish (position held still) before reading the world",
   "local function settle_slide(G)" in sh and "if still >= 12 then return end" in sh
   and sh.count("settle_slide(G)") >= 5)

# the ledger side: an arrow frontier row and explore's words
ex = C.make(frontier={U.HERE: []})
o = C.obs(ex, ["1,0"])
o["map"]["frontier"] = [{"x": 9, "y": 4, "d": 3, "slide": True},
                        {"x": 2, "y": 2, "d": 5}]
o["map"]["seen"] = {"n": 30, "frontier_n": 2}
cands = L.build(ex, o, target="flag:X")
fr = [c for c in cands if c.kind == "frontier"]
ck("an arrow frontier row is minted with look=arrow and says ARROW",
   fr and fr[0].key == "9,4" and getattr(fr[0], "look", "") == "arrow"
   and "ARROW" in fr[0].note and "carries you" in fr[0].note)
page = L.render(cands, ex, o, target="flag:X")
ck("...its row label names the arrow",
   "arrow tile (9,4) slides onto unseen ground" in page)
ck("...and explore's words step onto the arrow",
   "step onto the ARROW tile at (9,4)" in page)
ck("a plain spot keeps the plain words",
   [c for c in fr if c.key == "2,2" and getattr(c, "look", "door") != "arrow"
    and "stands there" in c.note])

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
