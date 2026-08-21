#!/usr/bin/env python3
"""One room, several names — and the frontier step must not be fooled.

A region's fingerprint is minted from the ground the party can walk, so a
room that MERGES mid-run (the fossil lifted off the corridor it blocked, a
boulder pushed, a tree cut) ends up carrying two names painted over one
component. `pred_holds("area")` and `_route` have consulted AREA_ALIASES
since the day that first bit; the two arrival checks did not, and on
2026-08-20 the run paid for it in a single leg:

  * explore walked the party two legs to MT_MOON_1F|2,2 — the name the
    world had stopped minting — landed in MT_MOON_1F|3,2, the same room,
    and reported "the walk did not arrive";
  * the hop it gave up on was the pocket's ONLY exit, so it was blocked
    for the current world mark;
  * the next round said "nothing untried anywhere you can walk to over
    walked ground — something you have done must be undone", with an
    untried ladder four walked hops away.

Every check here is one of those steps. No game, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))

import executor as E          # noqa: E402
import ledger as L            # noqa: E402
import untried as U           # noqa: E402
from explore_step import bare, obs, check, FAILS, SG   # noqa: E402

MAP = U.MAP
HERE = U.HERE                      # TESTMAP|0,0
LIVE = f"{MAP}|9,9"                # the name the world mints now
GHOST = f"{MAP}|8,8"               # the same room, minted earlier


def alias(*pairs):
    E.AREA_ALIASES.clear()
    for a, b in pairs:
        E.AREA_ALIASES.setdefault(a, set()).add(b)
        E.AREA_ALIASES.setdefault(b, set()).add(a)


def main():
    print("one room, two names:")
    alias((LIVE, GHOST))
    check("aliases are the same place", E.Executor._same_area(LIVE, GHOST))
    check("...and it is not a free-for-all",
          not E.Executor._same_area(LIVE, f"{MAP}|1,1"))
    check("a name is itself", E.Executor._same_area(LIVE, LIVE))

    print("\nthe walk that landed where it was sent:")
    ex = bare(explored={HERE: {"north": {"to": LIVE, "n": 3}},
                        LIVE: {"south": {"to": HERE, "n": 3}}},
              frontier={HERE: ["north"], GHOST: ["south", "7,7"]})
    ex.visits = {HERE: 4, GHOST: 3}
    ex._cur_target = "flag:X"
    o_here = obs(MAP, "0,0", conns=["north"])
    o_live = obs(MAP, "9,9", warps=["7,7"], conns=["south"])
    ex.settle = lambda: o_live         # we land under the LIVE name
    done, tr, cl = ex._explore_step(SG, o_here)
    check("a landing under the room's other name is an arrival",
          not any("did not arrive" in t for t in tr), str(tr))
    check("...so the step still expands on arrival",
          ex.ran == [{"op": "use_warp", "x": 7, "y": 7}], str(ex.ran))

    print("\nthe name the world still mints:")
    # both names carry the same frontier; only the live one is stood in
    ex = bare(explored={HERE: {"north": {"to": LIVE, "n": 3}},
                        LIVE: {"south": {"to": HERE, "n": 3}},
                        GHOST: {"south": {"to": HERE, "n": 3}}},
              frontier={HERE: ["north"], LIVE: ["south", "7,7"],
                        GHOST: ["south", "7,7"]})
    ex.visits = {HERE: 4, LIVE: 40, GHOST: 3}
    ex._cur_target = "flag:X"
    ex.settle = lambda: obs(MAP, "9,9", warps=["7,7"], conns=["south"])
    ex._explore_step(SG, obs(MAP, "0,0", conns=["north"]))
    check("the frontier walk aims at the name that has been stood in most",
          ex.walked and ex.walked[0][-1][1] == LIVE, str(ex.walked))

    print("\nwhat a map goal is made of:")
    NEAR = f"{MAP}|1,1"            # near, people never spoken to, no exits
    FAR = f"{MAP}|2,2"             # further, an exit never taken
    alias()
    ex = bare(explored={HERE: {"north": {"to": NEAR, "n": 3}},
                        NEAR: {"south": {"to": HERE, "n": 3},
                               "east": {"to": FAR, "n": 1}},
                        FAR: {"west": {"to": NEAR, "n": 1}}},
              frontier={HERE: ["north"], NEAR: ["south", "east"],
                        FAR: ["west", "7,7"]})
    ex.visits = {HERE: 4, NEAR: 3, FAR: 1}
    ex.sightings = {NEAR: ["A", "B", "C"]}
    ex._cur_target = "map:SOMEWHERE"
    ex.settle = lambda: obs(MAP, "2,2", warps=["7,7"], conns=["west"])
    ex._explore_step(SG, obs(MAP, "0,0", conns=["north"]))
    check("a map goal walks to the area with a way out, not the nearer "
          "one with only people in it",
          ex.walked and ex.walked[0][-1][1] == FAR, str(ex.walked))

    print("\nthe road that is shut only for now:")
    ex = bare(explored={HERE: {"north": {"to": LIVE, "n": 3,
                                         "blocked_at": [0, 1, 0]}},
                        LIVE: {"south": {"to": HERE, "n": 3}}},
              frontier={HERE: ["north"], LIVE: ["south", "7,7"]})
    ex.visits = {HERE: 4, LIVE: 3}
    ex._mark_now = [0, 1, 0]
    ex._cur_target = "flag:X"
    o_here = obs(MAP, "0,0", conns=["north"])
    ex.settle = lambda: o_here
    done, tr, cl = ex._explore_step(SG, o_here)
    check("a hop that refused you this turn is not a world with no roads",
          any("RIGHT NOW" in t for t in tr) and
          not any("must be undone" in t for t in tr), str(tr))
    check("...and it names the area it cannot get to",
          any(LIVE in t for t in tr), str(tr))

    print("\nwhat item 1 offers when the goal is a map:")
    cands = [
        L.Candidate(key="KID", kind="npc", status="unspoken", reachable=True),
        L.Candidate(key="4,4", kind="door", status="taken", reachable=True,
                    n=2, dest=f"{MAP}|3,3"),
        L.Candidate(key="5,5", kind="door", status="came_in_by",
                    reachable=True, n=31, dest=f"{MAP}|4,4"),
    ]
    o = obs(MAP, "0,0")
    line = L.plan_explore(bare(), o, cands, target="map:SOMEWHERE")
    check("a map goal is offered a way out before a person",
          "least-used" in line and "4,4" in line, line)
    line = L.plan_explore(bare(), o, cands, target="flag:X")
    check("...and a flag goal still hears about the person first",
          "KID" in line, line)

    print("\na wall is not an unopened door:")
    cands = [
        L.Candidate(key="east", kind="seam", status="untried", reachable=True,
                    note="FAILED — the east seam cannot be walked to from "
                         "here — no walkable path reaches it"),
        L.Candidate(key="4,4", kind="door", status="taken", reachable=True,
                    n=1, dest=f"{MAP}|3,3"),
        L.Candidate(key="5,5", kind="door", status="came_in_by",
                    reachable=True, n=15, dest=f"{MAP}|4,4"),
    ]
    line = L.plan_explore(bare(), obs(MAP, "0,0"), cands, target="flag:X")
    check("the least-used walked door outranks a crossing proven shut",
          "least-used" in line and "4,4" in line, line)

    print("\n" + "-" * 60)
    if FAILS:
        print(f"GHOST REGIONS STILL FOOL THE FRONTIER: {len(FAILS)} case(s)")
        return 1
    print("one room answers to one name, and the frontier step follows the goal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
