#!/usr/bin/env python3
"""A crossing that started and stopped short is still a crossing across
the water (2026-09-05).

The shim refuses a `cross` in three different sentences, and the seam
hop's ride retry matched two of them:

  1. "the N seam of M (to D) cannot be walked to from here — no walkable
     path reaches it."                          -- the BFS, before a step
  2. "...cannot be reached over the ground you have SEEN..."   -- ditto
  3. "couldn't reach east edge gap (99,5), stuck at (46,6) — 54 cell(s)
     of walking still to do"          -- the walk that RAN and fell short

Route 20 is split by water and its two halves are joined by nothing else,
so its east seam to Route 19 fails in the third sentence every time: the
walk goes as far as the shore and stops. With only 1 and 2 matched, `go
FUCHSIA_CITY` out of the Seafoam door walked three legs, hit the water,
and gave up — on the same morning the intra-map walk hop beside it got
its ride (ef31d1f) and the door hop had had one since 17cbbf3. The model
then crossed by hand, riding, two rounds later, which is the proof the
ride was available all along. One wording apart, in the harness.

WATER IS THE GUARD, because sentence 3 is also what a LEDGE and a plain
wall say, and SURF answers neither. That is the same condition the door
hop's gate has always carried.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def should_ride_seam(*, landed_short, is_door, edge_surf, already_rode,
                     knows_surf, has_water, detail):
    """The gate as _walk_route applies it to a seam hop."""
    return bool(landed_short and not is_door and not edge_surf
                and not already_rode and knows_surf
                and ("cannot be walked to" in detail
                     or "cannot be reached over the ground" in detail
                     or ("couldn't reach" in detail and has_water)))

# the verdict Route 20's east seam actually returned, twice, at dt 121 and 157
SHORT = ("couldn't reach east edge gap (99,5), stuck at (46,6) — 54 cell(s) "
         "of walking still to do — 1 LEDGE tile(s) lie along that line, and "
         "a ledge is a ONE-WAY drop: it can be hopped down, never climbed")
BFS = ("the east seam of ROUTE_20 (to ROUTE_19) cannot be walked to from "
       "here — no walkable path reaches it.")
SEEN = ("the east seam of ROUTE_20 (to ROUTE_19) cannot be reached over the "
        "ground you have SEEN — the search stopped where your footprint ends")
BASE = dict(landed_short=True, is_door=False, edge_surf=False,
            already_rode=False, knows_surf=True, has_water=True, detail=SHORT)

ck("the walk that stopped short at Route 20's water is ridden",
   should_ride_seam(**BASE))
ck("...and a dry floor saying the same words is not",
   not should_ride_seam(**{**BASE, "has_water": False}))
ck("the BFS refusal still rides, as it has since 2026-08-28",
   should_ride_seam(**{**BASE, "detail": BFS}))
ck("...and the footprint refusal too",
   should_ride_seam(**{**BASE, "detail": SEEN}))
ck("a hop that landed is left alone",
   not should_ride_seam(**{**BASE, "landed_short": False}))
ck("a door hop is not this rule (it has its own, three lines up)",
   not should_ride_seam(**{**BASE, "is_door": True}))
ck("an edge already known as a ride was crossed riding to begin with",
   not should_ride_seam(**{**BASE, "edge_surf": True}))
ck("it never rides twice for one hop",
   not should_ride_seam(**{**BASE, "already_rode": True}))
ck("no SURF, no ride",
   not should_ride_seam(**{**BASE, "knows_surf": False}))
ck("a seam a person is standing in is not a swim",
   not should_ride_seam(**{**BASE,
                           "detail": "somebody is standing in the gap"}))

src = (ROOT / "planner/executor.py").read_text()
j = src.index("_surfed_retry = True")
gate = src[j - 900:j]
ck("the gate carries all three wordings",
   '"cannot be walked to" in _det' in gate
   and '"cannot be reached over the ground" in _det' in gate
   and '"couldn\'t reach" in _det' in gate)
ck("...and the third one only where there is water",
   'get("water")' in gate)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
