#!/usr/bin/env python3
"""An objective that says to go THROUGH a place is not done while every
walked way out of that place lands on the same ground.

"Travel through Rock Tunnel" was crossed off twice before it ever ran.
First on "the run has previously exited Rock Tunnel to Route 10,
indicating the tunnel has been traversed"; once "indicating" was refused
as a hedge, it came back reworded as "as evidenced by the walk record and
the current location" and crossed the leg off again (2026-09-14). Both
were true about exiting and false about traversing: what it had come out
onto was ROUTE_10|0,4, the very part it went in from. Coming back out the
way you came in is not going through, and no amount of tightening the
language would have caught the second wording, because it named facts.

The ledger settles it with no knowledge of the game: take every edge the
run has walked from any part of that place to anywhere outside it, and if
they all land on ONE region it has used one mouth. Nothing here says
where the other mouth is, or that there is one.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))
import author as A                                        # noqa: E402
from pinned_world import pinned                           # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

ONE_MOUTH = {                                   # in from Route 10, back out to it
    "ROCK_TUNNEL_1F|14,2": {"15,3": {"to": "ROUTE_10|0,4"},
                            "37,3": {"to": "ROCK_TUNNEL_B1F|26,2"}},
    "ROCK_TUNNEL_B1F|26,2": {"33,25": {"to": "ROCK_TUNNEL_1F|14,2"},
                             "27,3": {"to": "ROCK_TUNNEL_1F|4,2"}},
    "ROCK_TUNNEL_1F|4,2": {"5,3": {"to": "ROCK_TUNNEL_B1F|26,2"}},
    "ROUTE_10|0,4": {"8,17": {"to": "ROCK_TUNNEL_1F|14,2"}},
}
TWO_MOUTHS = dict(ONE_MOUTH)
TWO_MOUTHS["ROCK_TUNNEL_1F|4,2"] = {"5,3": {"to": "ROCK_TUNNEL_B1F|26,2"},
                                    "9,1": {"to": "ROUTE_10|11,40"}}

def through(goal, world):
    with pinned(explored=world):
        return A._not_through_yet(goal, "run/explored.json")

# ---- one mouth ---------------------------------------------------------------
ck("a tunnel entered and left by the same mouth is not gone through",
   (through("Travel through Rock Tunnel", ONE_MOUTH) or "").startswith("ROCK_TUNNEL"))
ck("...and it says which ground every way out lands on",
   "ROUTE_10|0,4" in (through("Travel through Rock Tunnel", ONE_MOUTH) or ""))
ck("floors of the place count as the place, not as ways out of it",
   "ROCK_TUNNEL_B1F" not in (through("Travel through Rock Tunnel", ONE_MOUTH) or ""))

# ---- two mouths --------------------------------------------------------------
ck("once a second mouth is walked, the objective is the model's to judge",
   through("Travel through Rock Tunnel", TWO_MOUTHS) is None)

# ---- what it leaves alone ----------------------------------------------------
ck("an objective with no THROUGH in it is untouched",
   through("Reach Lavender Town", ONE_MOUTH) is None
   and through("Exit Rock Tunnel", ONE_MOUTH) is None)
ck("across and traverse count as through",
   through("Traverse Rock Tunnel", ONE_MOUTH) is not None
   and through("Travel across Rock Tunnel", ONE_MOUTH) is not None)
ck("a place the objective does not name is not judged",
   through("Travel through Mt Moon", ONE_MOUTH) is None)
ck("no record at all says nothing", A._not_through_yet("Travel through Rock Tunnel", None) is None)

# ---- both judges ask it -------------------------------------------------------
src = (ROOT / "planner" / "author.py").read_text()
ck("check_done asks it", "_through = _not_through_yet(goal, observed)" in src)
ck("check_already_done asks it", "_through = _not_through_yet(deed, observed)" in src)
ck("...and both say a way through has two ends",
   src.count("one mouth used, and a way") == 2)
ck("the harness says nothing about where the other mouth is",
   not any(w in src[src.index("def _not_through_yet"):src.index("def _not_through_yet") + 2600].lower()
           for w in ("lavender", "south", "the far side is")))

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
