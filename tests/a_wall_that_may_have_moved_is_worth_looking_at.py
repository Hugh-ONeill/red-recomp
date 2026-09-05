#!/usr/bin/env python3
"""A wall that may have moved is a lead the run can follow.

2026-09-05, live in the Pokemon Mansion. The model flipped a switch, then
tried the stairs in the upper left of 2F, and the harness said:

  use_warp(x=6,y=1): FAILED — couldn't reach the warp tile (no path — the
  ground you have SEEN and can walk from here is 202 cell(s) and the
  closest it comes to 6,1 is 10,1 ... 2 cell(s) that were WALLS the last
  time they were on screen were not routed into — if one has opened since,
  seeing it again is what lifts that)

The stairs were reachable (user: "its also reading the warp as unreachable
on the 2f when it is reachable, its the way up to the 3rd floor that
actually leads somewhere, in the upper left"). The Mansion is a building
whose switches move its walls, and a cell frozen shut at last view fell
between the harness's two categories:

  routing will not cross it   — the footprint rule, and it is right: open
                                NOW proves nothing until it has been SEEN
                                open, or a run walks through walls it has
                                only guessed about
  a sweep will not aim at it  — a sweep aims at ground never on screen, and
                                this ground HAS been on screen

So the refusal named the remedy — see it again — and there was no way to
do that. Now the reachability walk collects the cell you can STAND on
beside each frozen wall, explore walks to the nearest when there is no
unseen ground and no water left, and the page says it.

WHAT IS NOT CLAIMED: that any of them has opened. Live collision is not
consulted, because "is it open now" is exactly the thing the run has to
find out by looking. The page says so in as many words.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import ledger                                        # noqa: E402
import candidates as C                               # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

SHIM = (ROOT / "harness/shim.lua").read_text()
EXEC = (ROOT / "planner/executor.py").read_text()
LED = (ROOT / "planner/ledger.py").read_text()

# --- the shim collects them, and collects the right thing ------------
ck("the reachability walk collects frozen walls",
   "local stale, stale_at = {}, {}" in SHIM)
ck("...keyed by the cell you can stand on, not the wall",
   "stale[#stale + 1] = { x = cur.x, y = cur.y, d = dist[ck]," in SHIM)
ck("...naming the wall it is beside, so the page can say which",
   "wx = nx, wy = ny }" in SHIM)
ck("...nearest first, like the frontier",
   "table.sort(stale, nearest_first)" in SHIM)
ck("...and handed back with the rest",
   "return dist, front, stale" in SHIM)
ck("the observation carries them", "m.frontier_stale = sl" in SHIM
   and "m.seen.frontier_stale_n = #stale" in SHIM)
ck("LIVE COLLISION IS NOT CONSULTED — whether it opened is what looking is "
   "for", "if hidden_open(nx, ny, nk) and not stale_at[ck] then" in SHIM)

# --- explore goes and looks, after the ground nobody has seen at all ---
i = EXEC.index('step="stale"')
ck("explore has a rung for it", 'step="stale"' in EXEC)
ck("...that walks to the stand-point", '{"op": "walk_to", "x": int(_s0.get("x")),' in EXEC)
ck("...and is ranked after unseen ground and after the water",
   EXEC.index('step="sweep"') < i and EXEC.index('step="ride"') < i)
ck("...and obeys no_sweep like the other looking rungs",
   '_fs and not _params.get("no_sweep")' in EXEC)
ck("...and says why it went, in the trace",
   "a cell that was a WALL the " in EXEC
   and "standing there is " in EXEC)

# --- the page says it, so the model can act without being walked ------
def head(m_extra):
    ex = C.make()
    ex._where = lambda o: "POKEMON_MANSION_2F|6,1"
    ex._explore_trips = {}
    obs = {"map": dict({"id": "POKEMON_MANSION_2F", "region": "6,1",
                        "warps": []}, **m_extra),
           "player": {"x": 10, "y": 1}, "party": [], "bag": {}}
    return ledger.render([], ex, obs, "map:POKEMON_MANSION_3F")

t = head({"frontier_stale": [{"x": 10, "y": 1, "d": 3, "wx": 9, "wy": 1},
                             {"x": 12, "y": 4, "d": 6, "wx": 12, "wy": 3}]})
ck("the page says how many there are", "2 CELL(S) HERE WERE WALLS" in t)
ck("...and where to stand to settle the nearest", "(10,1)" in t and "(9,1)" in t)
ck("...and why somewhere may read unreachable that is not",
   "may read unreachable that is not" in t)
ck("...and claims nothing about whether one has opened",
   "Whether any of them has opened is not known here" in t)
ck("nothing is said when there are none",
   "WERE WALLS THE LAST TIME" not in head({}))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
