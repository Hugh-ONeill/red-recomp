#!/usr/bin/env python3
"""An area holding a way out never taken that no walk reached is unfinished
business for explore — in the deed and in the words.

Mt Moon B2F, 2026-08-29 (user: "if something is unreachable it should still
try to explore near there and the only way it can get through is picking up
a fossil"). note_frontier builds a region's exits from `warps if reachable`,
so the fossil pocket — which holds the ladder (5,7) to the mountain's exit
and the fossils standing in its corridor — counted as having NOTHING LEFT
and ranked below empty pockets. Now those ways are remembered per region
(unreached_at, persisted, dropped once walked), count as unfinished, and
weigh double in the ranking; the trace and item 1 say what they are.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import candidates as C, untried as U, ledger as L   # noqa: E402
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok): checks.append((n, bool(ok)))
ck("unreachable untaken ways are remembered per region and persisted",
   "_unr = sorted(f\"{w.get('x')},{w.get('y')}\"" in src
   and '"unreached_at": getattr(self, "unreached_at", {})' in src
   and 'self.unreached_at = data.get("unreached_at", {}) or {}' in src)
ck("...and dropped once that way has been walked",
   "_unr = [k for k in _unr if k not in _taken_now]" in src)
ck("the deed counts them as something left, and says so in the trace",
   "if not (left or unpressed or unseen or _unr):" in src
   and "way(s) out never taken that no walk reached when you " in src)
FOSSIL, EMPTY = "B2F|20,5", "B2F|27,5"
ex = C.make(explored={U.HERE: {"9,9": {"to": FOSSIL, "n": 1}, "8,8": {"to": EMPTY, "n": 1}},
                      FOSSIL: {"9,9": {"to": U.HERE, "n": 1}}, EMPTY: {"8,8": {"to": U.HERE, "n": 1}}},
            frontier={U.HERE: [], FOSSIL: [], EMPTY: []})
ex.region_seen = {EMPTY: 4}; ex.sightings = {}
ex.unreached_at = {FOSSIL: ["5,7"]}
ex.visits = {U.HERE: 3, FOSSIL: 2, EMPTY: 2}
o = C.obs(ex, [])
words = L.plan_explore(ex, o, L.build(ex, o, target="map:CERULEAN_CITY", want_explore=False),
                       target="map:CERULEAN_CITY")
ck("the words pick the pocket holding the unreachable way over an empty one with unseen ground",
   f"never tried is {FOSSIL}" in words)
ck("...and say what is there", "look for the way to 5,7" in words
   and "a way out never taken that no walk reached" in words)
ex.explored[FOSSIL]["5,7"] = {"to": "B1F|1,1", "n": 1}     # now walked
w2 = L.plan_explore(ex, o, L.build(ex, o, target="map:CERULEAN_CITY", want_explore=False),
                    target="map:CERULEAN_CITY")
ck("a way once walked stops counting", f"never tried is {EMPTY}" in w2)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
