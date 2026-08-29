#!/usr/bin/env python3
"""For a map goal, unseen ground ranks with an untried exit when explore
picks where to walk — in the words and in the deed.

Route 4, 2026-08-29 (user watching): the remote picker put an area with an
UNTRIED EXIT (tier 0) above one with only UNSEEN GROUND (tier 1), distance
deciding only within a tier — so the Pewter museum's one untried door at 3
legs beat Mt Moon's 63 unseen spots at 1 leg and explore walked the party
back to Pewter with the way through the mountain sitting in ground nobody
had looked at. plan_explore (the words) ranked by distance alone, so the
page and the walk disagreed as well. Under the footprint unseen ground is
where unseen exits live: one tier with untried exits, distance decides.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import candidates as C, untried as U, ledger as L   # noqa: E402
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
HERE = U.HERE
MOON, TOWN, HALL, MUSEUM = "MOON|1,1", "TOWN|0,0", "HALL|0,0", "MUSEUM|0,1"
ex = C.make(explored={HERE: {"5,5": {"to": MOON, "n": 3}, "north": {"to": TOWN, "n": 2}},
                      TOWN: {"3,3": {"to": HALL, "n": 1}}, HALL: {"7,7": {"to": MUSEUM, "n": 1}},
                      MOON: {"5,5": {"to": HERE, "n": 3}}},
            frontier={HERE: [], MOON: [], MUSEUM: ["9,9"], TOWN: [], HALL: []})
ex.region_seen = {MOON: 63}; ex.sightings = {}
ex.visits = {HERE: 5, MOON: 25, TOWN: 3, HALL: 1, MUSEUM: 1}
o = C.obs(ex, [])
cands = L.build(ex, o, target="map:CERULEAN_CITY", want_explore=False)
txt = L.plan_explore(ex, o, cands, target="map:CERULEAN_CITY")
ck("the words name the unseen mountain at 1 leg before the museum's untried door at 3",
   "never tried is MOON|1,1" in txt and "63 spot(s)" in txt)
src = (ROOT / "planner" / "executor.py").read_text()
ck("the deed tiers unseen ground with an untried exit for a map goal",
   "_pri = (0 if (left or unseen) else 1) if _map_goal else 0" in src)
lsrc = (ROOT / "planner" / "ledger.py").read_text()
ck("...and the words carry the same tier", 'if str(target or "").startswith("map:") else 0)' in lsrc
   and "r = (_pri, len(path), -(len(left) + len(things) + unseen), region)" in lsrc)
ex._dry_walks = {MOON: 2}
txt2 = L.plan_explore(ex, o, L.build(ex, o, target="map:CERULEAN_CITY", want_explore=False), target="map:CERULEAN_CITY")
ck("two dry walks to an area rank it last (the museum's ticket desk)", "never tried is MUSEUM|0,1" in txt2)
ck("...the deed keeps the same rule and says it", "_pri = 3" in src and "ranks LAST for explore from " in src
   and '"dry_walks": getattr(self, "_dry_walks", {})' in src)
ck("a pocket's zero does not erase a region's unseen ground while the map still has some",
   "if _fn_new == 0 and _fn_old > 0 and _fn_map > 0:" in src
   and "frontier_map_n = fmap" in (ROOT / "harness" / "shim.lua").read_text())
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
