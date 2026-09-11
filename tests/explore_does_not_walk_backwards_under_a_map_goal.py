#!/usr/bin/env python3
"""When nothing untried lies toward the goal, that is the answer.

Under a map goal the remote picker ranks areas toward the goal before
areas away from it, on the printed map.  When the areas level with the
goal have nothing left, the best remaining candidate is AWAY -- and the
picker walked to it, because it had no way to say "there is nothing that
way".

Standing on ROUTE_23, one leg from Victory Road, under INDIGO_PLATEAU:
before the doorstep fix it walked 39 legs to the Rocket Hideout lift;
after it, 4 legs to ROUTE_2.  Both backwards, for the same reason (user,
2026-09-11: "if its got a target map explore shouldnt be directing it away
from that").

The WALK is refused and nothing else is.  Every area is still listed with
the printed map's word for which way it lies, and go still takes the party
anywhere it has walked.  What stops is the harness choosing to go
backwards on its own.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "planner" / "executor.py").read_text()

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

blk = SRC.split("NOTHING UNTRIED LIES TOWARD THE GOAL IS AN ANSWER", 1)[1][:2200]
import re                                               # noqa: E402
# the message is built from adjacent f-string literals, so a sentence can
# straddle a boundary in the SOURCE while reading as one line to the model
flat = re.sub(r"\s+", " ", re.sub(r'"\s*f?"', "", blk))

ck("it fires only under a map goal",
   'str(target or "").startswith("map:")' in blk)
ck("...and only when the best candidate is the away tier",
   "best[0][3] == 2" in blk)
ck("...and only when there is a candidate at all",
   "best is not None" in blk)
ck("it refuses the walk rather than taking it",
   "return False, [" in blk)
ck("the refusal names the goal", "nothing untried lies toward {_g}" in flat)
ck("...and says where the nearest away area is, and how far back",
   "the nearest is {best[1]}" in flat and "leg(s) back" in flat)
ck("...and that the printed map is what says so",
   "AWAY from it on the printed map" in flat)
ck("...and hands the choice back rather than pointing",
   "The way on is something here you have not done" in flat)
ck("go is still offered for a place it has walked",
   "still takes you anywhere you have walked" in flat)
ck("the refusal is logged for the meter",
   'self.log("explore_refused_away"' in blk)

# it must sit BEFORE the fallbacks that would walk anyway
ck("it comes before the ride-chance fallback",
   SRC.index("explore_refused_away") < SRC.index("_rc = self._ride_chance"))

# and the ranking it reads is the one that was already there
ck("the away tier is the same term the key ranks by",
   "r = (_pri, _stale, _local, _goal, len(path), _way_here," in SRC)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
