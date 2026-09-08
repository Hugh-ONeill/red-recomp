#!/usr/bin/env python3
"""A go with no walked way names the one map where the chain breaks, and
how its two parts could be joined.

Run 16, 2026-09-08: from Celadon the run had walked every road to Vermilion
the long way round — Lavender, Rock Tunnel, Route 9, Cerulean, the
underground path — and `go VERMILION_CITY` said "no walked way" eight rounds
running (user: "how would there not be a walked path between here and
vermillion?"). Route 9 was three walked parts, walked once eastward over its
ledges: the record held west-to-middle and middle-to-east, never middle-to-
west, and the router reverses seams between maps but not walks inside one.
Now the refusal says where the record breaks and how to close it; whether
the ground can be walked that way is for the walk to find out.
"""
import sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E   # noqa: E402
src = (ROOT / "planner" / "executor.py").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

explored = {
    "CELADON_CITY|2,1": {"east": {"to": "ROUTE_7|0,2", "n": 1}},
    "ROUTE_7|0,2": {"5,3": {"to": "LAVENDER_TOWN|6,0", "n": 1}},            # stand-in for the underground path
    "LAVENDER_TOWN|6,0": {"north": {"to": "ROUTE_10|14,52", "n": 1}},
    "ROUTE_10|14,52": {"8,53": {"to": "ROUTE_10|0,4", "n": 1}},              # stand-in for the tunnel
    "ROUTE_10|0,4": {"west": {"to": "ROUTE_9|50,6", "n": 1}},
    "ROUTE_9|50,6": {"walk:ROUTE_9|6,2": {"to": "ROUTE_9|6,2", "n": 1}},
    "ROUTE_9|6,2": {"walk:ROUTE_9|50,6": {"to": "ROUTE_9|50,6", "n": 2}},   # middle-to-west never walked
    "ROUTE_9|0,8": {"walk:ROUTE_9|6,2": {"to": "ROUTE_9|6,2", "n": 1}, "west": {"to": "CERULEAN_CITY|26,7", "n": 4}},
    "CERULEAN_CITY|26,7": {"south": {"to": "ROUTE_5|4,4", "n": 1}},
    "ROUTE_5|4,4": {"south": {"to": "ROUTE_6|4,4", "n": 1}},
    "ROUTE_6|4,4": {"south": {"to": "VERMILION_CITY|18,0", "n": 1}},
    "VERMILION_CITY|18,0": {},
}
fake = types.SimpleNamespace(explored=explored, _bad_seam=set())
fake._edges_of = lambda r: E.Executor._edges_of(fake, r)
gap = E.Executor._route_gap(fake, "CELADON_CITY|2,1", "VERMILION_CITY")
ck("the break is found on Route 9, between the middle part and the west end",
   gap == ("ROUTE_9", "ROUTE_9|6,2", "ROUTE_9|0,8"), gap)
explored["ROUTE_9|6,2"]["walk:ROUTE_9|0,8"] = {"to": "ROUTE_9|0,8", "n": 1}
ck("once that walk is made, there is no gap", E.Executor._route_gap(fake, "CELADON_CITY|2,1", "VERMILION_CITY") is None)
ck("the go refusal carries the note with the two ops that would join the parts",
   "The chain breaks inside {_gm}" in src and '{"op":"go","to":"' in src and "is how they join, if the " in src)
ck("the router's edge rule is one method now", "edges = self._edges_of" in src and "def _edges_of(self, region: str) -> dict:" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:300])
sys.exit(1 if bad else 0)
