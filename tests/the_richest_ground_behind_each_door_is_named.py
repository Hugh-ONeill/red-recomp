#!/usr/bin/env python3
"""The 'other ground' list names the MOST there is behind each door.

Route 4, 2026-08-29 (user: "its pingponging between pewter and rt4"): the
run said "I have already explored all reachable ground on Route 4 and in
Mt. Moon" while the ledger held MT_MOON_B2F|20,5 with 11 spots of ground
never on screen and two ways out never taken. The list is deduped one per
FIRST LEG and `found` is sorted by distance, so the slot behind the
mountain's door went to its nearest example — 1F's unpressed items — and
the mountain read as picked over. The leg is the choice being made; what
is worth the walk is decided by what is back there.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import candidates as C, untried as U, ledger as L   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
HERE = U.HERE
M1, B1, B2, PEW, R3 = ("MT_MOON_1F|3,2", "MT_MOON_B1F|4,4", "MT_MOON_B2F|20,5",
                       "PEWTER_CITY|4,2", "ROUTE_3|1,1")
ex = C.make(explored={HERE: {"18,5": {"to": M1, "n": 3}, "south": {"to": R3, "n": 2}},
                      M1: {"18,5": {"to": HERE, "n": 3}, "5,5": {"to": B1, "n": 1}},
                      B1: {"5,5": {"to": M1, "n": 1}, "21,17": {"to": B2, "n": 1}},
                      B2: {"21,17": {"to": B1, "n": 1}},
                      R3: {"north": {"to": HERE, "n": 2}, "west": {"to": PEW, "n": 2}},
                      PEW: {"east": {"to": R3, "n": 2}}},
            frontier={HERE: [], M1: [], B1: [], B2: [], R3: [], PEW: ["1,1", "2,2", "3,3", "4,4"]})
ex.region_seen = {B2: 11, PEW: 7}
ex.unreached_at = {B2: ["5,7", "15,27"]}
ex.sightings = {M1: ["ITEM_A", "ITEM_B"]}
ex.visits = {HERE: 21, M1: 7, B1: 2, B2: 1, R3: 5, PEW: 4}
o = C.obs(ex, [])
t = L.plan_explore(ex, o, L.build(ex, o, target="map:CERULEAN_CITY", want_explore=False),
                   target="map:CERULEAN_CITY")
_tail = t.split("Other ground")[-1]
ck("the mountain's deepest unfinished floor is the one named, not its nearest one",
   "MT_MOON_B2F|20,5 (3 leg(s)" in _tail and "MT_MOON_1F|3,2 (1 leg(s)" not in _tail, _tail[:300])
ck("...with what is actually there",
   "11 spot(s) of ground never on screen" in t
   and "2 way(s) out never taken that no walk reached from there" in t, t[-300:])
ck("...still one line per first leg, and still the model's call",
   t.count("first door (18,5)") == 1 and "which of these is worth the walk is yours" in t)
src = (ROOT / "planner" / "ledger.py").read_text()
ck("the pick behind each leg is by how much is there, not by distance",
   "if _fk0 not in _by_leg or _n0 > _by_leg[_fk0][0]:" in src
   and "key=lambda kv: -kv[1][0]" in src)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:220])
sys.exit(1 if bad else 0)
