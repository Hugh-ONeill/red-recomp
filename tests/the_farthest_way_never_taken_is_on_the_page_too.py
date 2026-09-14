#!/usr/bin/env python3
"""The places-with-ways-never-taken list shows the nearest few AND the
farthest, because nearest-first buries the only way on.

The list is ranked by walked distance, which is mechanical and fair, and
on the day the run came out of the far mouth of Rock Tunnel it buried the
one region that could open new map. ROUTE_10|14,52 held six spots of
unseen ground and a WEST edge never crossed, six legs away through the
tunnel; every slot went to ground one or two legs off, and the far mouth
never reached the page at all. So Route 10 read as a single place already
explored, and the run set out for Lavender the long way round, twice
(2026-09-14, user: "its not quite connecting that south rt10 is on the
other side of rock tunnel, because it wanted to explore on rt10, ended up
in rock tunnel, and immediately walked back out").

Keeping the nearest is right; keeping only the nearest is what hides a
long way on. Both ends are shown, each said for what it is, and which is
worth the walk stays the model's.
"""
from __future__ import annotations
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import executor as E                                      # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

line = types.MethodType(E.Executor._elsewhere_line, types.SimpleNamespace())

def row(reg, legs, ways=1, routable=True):
    return ((not routable, legs, -ways, reg), f"{reg} [{legs} leg(s)]")

NEAR = [row(f"NEAR_{c}", n) for c, n in zip("ABCDE", (1, 1, 2, 2, 2))]
FAR = row("ROUTE_10|14,52", 6)
MID = row("MID", 4)

out = line(NEAR + [MID, FAR])
ck("the nearest five are still shown", all(f"NEAR_{c}" in out for c in "ABCDE"), out)
ck("...and the farthest is shown too, which nearest-first had dropped",
   "ROUTE_10|14,52" in out, out)
ck("...under its own heading", "AND THE FARTHEST, which nothing nearer will lead you to" in out)
ck("...farthest first within that half",
   out.index("ROUTE_10|14,52") < out.index("MID [4"), out)
ck("...and it refuses to say which is worth it",
   "which of these is worth the walk is yours" in out
   and not any(w in out.lower() for w in ("you should", "go to the", "take the far")))
ck("the distance is on every entry, so the cost is visible",
   out.count("leg(s)]") == 7, out)

ck("a short list says nothing about a farthest", "AND THE FARTHEST" not in line(NEAR[:3]))
ck("...and is otherwise unchanged",
   line(NEAR[:3]).startswith("\nPlaces you have already been that still have "
                             "ways you have NEVER taken: NEAR_A"))
ck("nothing to say about nowhere", line([]) == "")
ck("the hint that followed the list still follows it",
   line(NEAR[:2], near_hint=" (a hint)").endswith(" (a hint)"))

# a place no walk reaches is not offered as the farthest: it is not a way on
UNREACHED = row("NO_ROUTE", 99, routable=False)
out2 = line(NEAR + [MID, UNREACHED])
ck("an unroutable place is never the farthest",
   "AND THE FARTHEST" in out2 and "NO_ROUTE" not in out2.split("AND THE FARTHEST")[1], out2)

src = (ROOT / "planner" / "executor.py").read_text()
ck("both pages render it through the one method",
   src.count("self._elsewhere_line(elsewhere, near_hint)") == 2
   and src.count('"you have NEVER taken: "') == 1)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
