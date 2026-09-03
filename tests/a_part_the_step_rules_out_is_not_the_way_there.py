#!/usr/bin/env python3
"""A part the step rules out is not the way there.

{"map": "ROUTE_10", "not_area": "ROUTE_10|0,4"} asks for a part of Route 10
other than the north half — the split-route shape the author finally wrote
for "Reach Lavender Town". The target key is still "map:ROUTE_10", and the
known-way line routed to any walked region of that map: standing in Rock
Tunnel's far chamber, one ladder from the unexplored B1F, the party read
"THE KNOWN WAY TO ROUTE_10 FROM HERE: take the door at (5,3) ... go ROUTE_10
walks the whole of it ... an untried exit that leads somewhere else is not
progress toward this goal" — and went back out, twice in one attempt
(2026-09-03). The one route the step cannot use was the one on offer.

Now the ruled-out parts are skipped when the route is chosen, and when
nothing else on that map has been walked the line says so: the only parts
you have walked are the ones ruled out, a part never stood on is what is
asked, and no walked route reaches one.

Synthetic: no game, no model.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                   # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

R = E.Executor._ruled_out_parts
ck("a step with not_area names the part it rules out",
   R({"done_when": {"map": "ROUTE_10", "not_area": "ROUTE_10|0,4"}}) == {"ROUTE_10|0,4"})
ck("...and a list of them",
   R({"done_when": {"map": "X", "not_area": ["X|1,1", "X|2,2"]}}) == {"X|1,1", "X|2,2"})
ck("a plain map step rules nothing out", R({"done_when": {"map": "ROUTE_10"}}) == set())
ck("no step, nothing", R(None) == set() and R({}) == set())

src = (ROOT / "planner" / "executor.py").read_text()
i0 = src.index("_excl = self._ruled_out_parts(sg)")
i1 = src.index("THE ONLY PART(S) OF {want_map} YOU HAVE WALKED")
i2 = src.index('f"\\nTHE KNOWN WAY TO {want_map} FROM HERE: take {step} "')
ck("the map branch skips the ruled-out parts before choosing a route",
   i0 < i1 < i2 and "if region in _excl:\n                    _skipped.append(region)\n                    continue" in src)
ck("...and says so when nothing else on that map was walked",
   "ARE THE ONES THIS STEP RULES OUT" in src and "would only walk you back into" in src)
ck("...without saying where the other part is entered",
   "ROCK_TUNNEL" not in src[i1:i1+900])

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
sys.exit(1 if bad else 0)
