#!/usr/bin/env python3
"""A count the region's own reading contradicts ranks behind fresh ground.

A region's unseen-spot count is kept positive while its map still has
unseen ground anywhere (the pocket rule of 2026-08-29, for Mt Moon 1F's
mis-named ladder pocket). So every closed pocket on the way to Rock Tunnel
— Route 9's two, Route 10's north half, the Center, B1F's walked pocket —
advertised spots that lie in another part of its map, explore walked the
party into each to sweep, found nothing, and the dry-walk rule caught up
two rounds later, per pocket (2026-09-03, leg 24).

The raw reading from INSIDE a region is a fact about that region. It is
kept as frontier_here beside the kept count; explore ranks a region whose
own reading was zero behind fresh ground of its tier, not last (the
mis-named pocket stays ahead of nothing at all, and the dry-walk rule
still finishes the demotion); the unwalked-ground list says so per row.

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

e = object.__new__(E.Executor)
e.region_seen = {"ROCK_TUNNEL_B1F|26,2": 11, "ROCK_TUNNEL_1F|4,2": 13, "ROUTE_9|50,6": 6}
e.frontier_here = {"ROCK_TUNNEL_B1F|26,2": 0, "ROUTE_9|50,6": 3}
ck("a kept count with a zero reading from inside is dry from within",
   e._dry_from_within("ROCK_TUNNEL_B1F|26,2"))
ck("a region never stood in is not (nothing is known from inside it)",
   not e._dry_from_within("ROCK_TUNNEL_1F|4,2"))
ck("a region whose own reading was positive is not",
   not e._dry_from_within("ROUTE_9|50,6"))
ck("a region with no count at all is not",
   not e._dry_from_within("PALLET_TOWN|10,0"))
e2 = object.__new__(E.Executor)
ck("an executor from before the ledger existed does not die of it",
   not e2._dry_from_within("ROCK_TUNNEL_B1F|26,2"))

src = (ROOT / "planner" / "executor.py").read_text()
ck("the reading from inside is stamped beside the kept count",
   'self.frontier_here[here] = int(_sn.get("frontier_n") or 0)' in src
   and src.index('self.frontier_here[here] = int(_sn.get("frontier_n") or 0)')
   < src.index("if _fn_new == 0 and _fn_old > 0 and _fn_map > 0:"))
ck("...and persisted",
   '"frontier_here": getattr(self, "frontier_here", {})' in src
   and 'self.frontier_here = data.get("frontier_here", {}) or {}' in src)
ck("explore ranks it behind fresh ground of its tier, before distance",
   "r = (_pri, _stale, _local, len(path), _way_here," in src
   and "and self._dry_from_within(region)) else 0)" in src)
ck("...only when the count is all the region has to offer",
   "if (unseen and not left and not unpressed and not _unr" in src)
ck("the unwalked-ground list says so per row",
   "none of it reachable from where you last" in src)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
sys.exit(1 if bad else 0)
