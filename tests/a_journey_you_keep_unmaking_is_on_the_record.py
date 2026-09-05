#!/usr/bin/env python3
"""A journey the run keeps making and unmaking is on the page.

2026-09-05, live, with the party afloat on Route 20 and Cinnabar the goal.
Five rounds in ten minutes ran this exact cycle:

  the model writes {"op":"explore","until":"map_change"}
  explore's picker walks it three or four legs to Route 15, Route 18 or
     the Fuchsia mart, for their unseen ground
  the model reads the new position and writes "I am on Route 15, I need to
     go back to Route 20", and walks itself back
  ...and the next round is the first round again.

Its judgment was right every time. The harness overrode it every time. And
nothing anywhere on the page said that the round before had been the same
round: the model re-derives the whole situation from the page each round,
the walked graph knows WHERE it went but not that it had bounced, and the
journal that records the bounce is read by us and never by it. That is the
hiding class — the harness knowing something and not saying it — and the
user's call on it (2026-09-05: "do the loop note thing too").

What is owed is the RECORD, not a rule. explore stays offered, no trip is
refused, and nothing here says the loop is wrong: a second attempt at a
journey is sometimes exactly right. What the model could not do before was
see that it was on its second attempt.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import ledger                                   # noqa: E402
import candidates as C                          # noqa: E402

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

HERE = "ROUTE_20|44,2"
OBS = {"map": {"id": "ROUTE_20", "region": "44,2", "warps": []},
       "player": {"x": 44, "y": 2}, "party": [], "bag": {}}

def head_with(trips, target="map:CINNABAR_ISLAND", key_target=None):
    ex = C.make()
    ex._where = lambda o: HERE
    ex._cur_target = target
    ex._explore_trips = {((key_target if key_target is not None else target),
                          HERE): list(trips)}
    return ledger.render([], ex, OBS, target)

FIVE = ["FUCHSIA_MART|0,2", "ROUTE_18_GATE_1F|0,3", "ROUTE_15_GATE_1F|0,3",
        "ROUTE_15_GATE_1F|0,3", "ROUTE_15|14,8"]

t = head_with(FIVE)
ck("the round trips are said at all", "WALKED YOU AWAY FROM HERE" in t)
ck("...with how many there were", "5 TIMES" in t)
ck("...and where they went", "ROUTE_18_GATE_1F|0,3" in t
   and "FUCHSIA_MART|0,2" in t)
ck("a place walked to twice is named once", t.count("ROUTE_15_GATE_1F|0,3") == 1)
ck("it says the journeys ended where they began",
   "back where it started" in t)
ck("it refuses nothing and says so", "explore is still offered" in t)
ck("...and leaves the reading to the model", "yours to read" in t)
ck("it does not tell it what to do",
   "you should" not in t.lower() and "you must" not in t.lower())

ck("one trip is not a pattern and is not nagged about",
   "WALKED YOU AWAY FROM HERE" not in head_with(FIVE[:1]))
ck("two is", "WALKED YOU AWAY FROM HERE" in head_with(FIVE[:2]))
ck("no trips, nothing said",
   "WALKED YOU AWAY FROM HERE" not in head_with([]))

# the record is per STEP: a new objective is a new question, and the trips
# another step made from this spot are not this step's history
ck("trips belong to the step that made them",
   "WALKED YOU AWAY FROM HERE" not in
   head_with(FIVE, target="map:CINNABAR_LAB", key_target="map:CINNABAR_ISLAND"))

src = (ROOT / "planner/executor.py").read_text()
i = src.index('step="walk"')
ck("explore records the trip where it makes it",
   "_explore_trips" in src[i - 1400:i])
ck("...keyed by the step and the place it left from",
   '_trips.setdefault((self._cur_target or "", here), [])' in src)
ck("...and bounded, because a page is a budget",
   "del _leg[:-8]" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
