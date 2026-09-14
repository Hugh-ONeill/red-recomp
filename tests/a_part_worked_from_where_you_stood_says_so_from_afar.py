#!/usr/bin/env python3
"""A part the run stood in with nothing reachable left says so from afar,
and is not ranked for its unseen ground until the world changes.

The unseen count is the map's pocket rule: kept positive for every part
while the MAP has unseen ground anywhere, so a floor with chambers not yet
found keeps some part of it offered. Read raw, it made every remote row
say "MT_MOON_B2F|23,21 still has 6 spot(s) of ground in there never on
screen" and explore's row 1 send the party there "to sweep", while the
atlas held frontier_here = 0 for that part and the local page there said
EVERYTHING YOU CAN REACH HERE IS DONE. Two B2F parts, eleven walks between
them (2026-09-14, user: "does the bot have info of whats exhausted
without being in the area anymore? it seems like it gets to the different
areas of b2f and only once there realizes its been worked").

One relation now, Executor._unseen_there(region) -> (count to rank by,
verdict), read by the explore picker and by every ledger row: "done" when
the run stood there, nothing reachable was left, and the world mark has
not moved since (ranks 0, and the row says everything reachable was done);
"changed" when the mark has moved since (the count stands, said with that
caveat, so one more look is allowed); "" otherwise.
"""
from __future__ import annotations
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402
import ledger as L                                        # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

B2F = "MT_MOON_B2F|23,21"
def ex(frontier_here=0, visited=True, mark_then=(1, 29, 4), mark_now=(1, 29, 4), unseen=6):
    o = types.SimpleNamespace(
        region_seen={B2F: unseen}, frontier_here={B2F: frontier_here},
        visits={B2F: 7} if visited else {}, _region_mark={B2F: list(mark_then)},
        _mark_now=list(mark_now), unreached_at={B2F: ["21,17"]},
        sightings={}, _tried_objs={}, _gone={})
    o._unseen_there = types.MethodType(E.Executor._unseen_there, o)
    o._frontier_left = lambda r: []
    o._taken_here = lambda r: {}
    return o

# ---- the relation ------------------------------------------------------------
ck("stood there, nothing reachable left, nothing since: done, ranks 0",
   ex()._unseen_there(B2F) == (0, "done"))
ck("...but with the world mark moved since, the count stands with a caveat",
   ex(mark_now=(1, 31, 4))._unseen_there(B2F) == (6, "changed"))
ck("a part with reachable frontier left keeps its count",
   ex(frontier_here=3)._unseen_there(B2F) == (6, ""))
ck("a part never stood in keeps its count: the pocket rule is for it",
   ex(visited=False)._unseen_there(B2F) == (6, ""))
ck("no unseen ground: nothing either way", ex(unseen=0)._unseen_there(B2F) == (0, ""))
ck("no mark on record for the visit: the count stands",
   (lambda o: (o._region_mark.clear(), o._unseen_there(B2F))[1])(ex()) == (6, "changed"))

# ---- the remote row carries the verdict --------------------------------------
parts = L._left_parts(ex(), B2F)
ck("the exit row says everything reachable there was done",
   any("none of them reachable from where you last stood" in p and
       "everything you could reach there was done" in p for p in parts), parts)
ck("...and still counts the way out no walk reached",
   any("1 way(s) out of it never taken that no walk reached" in p for p in parts), parts)
parts = L._left_parts(ex(mark_now=(1, 31, 4)), B2F)
ck("with the world changed since, it says so instead of promising ground",
   any("things have happened since" in p for p in parts), parts)
parts = L._left_parts(ex(frontier_here=3), B2F)
ck("a part with reachable frontier reads as before",
   any(p == "6 spot(s) of ground in there never on screen" for p in parts), parts)

# ---- and the two rankings read the same relation ----------------------------
src_e = (ROOT / "planner" / "executor.py").read_text()
src_l = (ROOT / "planner" / "ledger.py").read_text()
ck("the explore picker ranks by it", "unseen = self._unseen_there(region)[0]" in src_e)
ck("explore's row-1 list ranks by it", "ex._unseen_there(region)[0]" in src_l)
ck("_left_parts reads its verdict", "ex._unseen_there(region)[1]" in src_l)
ck("no other ranking reads the raw count for a remote region",
   src_e.count("region_seen\", None) or {})\n                         .get(region") == 0)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
