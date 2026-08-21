#!/usr/bin/env python3
"""A crossing made at another cell of the seam is not the plain one.

Route 13's west crossing always lands on Route 14 row 6 — a four-cell
corridor with a STAY trainer parked in the one tile out of it. Ignoring
people, that map is 486 cells and reaches its own west edge; from the nook
the BFS walks 4. The uncork exists for exactly this: step back out, cross
again at another cell of the same edge, and see where you land. It works —
skip=1 lands in ROUTE_14|5,4, the main body.

Two things then threw the answer away.

  * _recross_for_target asked "is the tile I was sent to reachable from
    here?", got no, and stepped back out to try skip=2 — which landed in
    the nook again. Getting off a pocket is progress whether or not it is
    the whole answer.
  * the landing was filed under the BARE direction, so
    "ROUTE_13|50,0 --west--> ROUTE_14|5,4" went into the graph while every
    plain cross west still lands in the nook. The walk refuted it and filed
    it in bad_seam: the one crossing that works, learned and then deleted.

No game, no model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))

import executor as E          # noqa: E402
import untried as U           # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


NOOK = "ROUTE_14|16,6"
MAIN = "ROUTE_14|5,4"
R13 = "ROUTE_13|50,0"


def ex_with(explored=None):
    ex = U.make(explored=explored or {})
    ex.visits = {}
    ex.atlas = {}
    ex.flag_sites = {}
    ex.hints_at = {}
    ex.sightings = {}
    ex.searched = {}
    ex._known_flags = None
    ex.log = lambda *a, **k: None
    ex._save_memory = lambda: None
    ex._count_visit = lambda r: None
    for attr, val in (("_cur_target", None), ("_entered_by", {}),
                      ("shut_doors", {}), ("_bad_seam", set()),
                      ("_spent", {}), ("map_doors", {}),
                      ("_last_visit_region", None), ("touched", {}),
                      ("seen_far", {}), ("dead_ends", {}),
                      ("contested", {}), ("_battle_regions", set()),
                      ("_faint_at", None), ("_no_cross", {}),
                      ("_no_cross_at", {}), ("_exit_tries", {}),
                      ("_arrived", None), ("_came_from", None),
                      ("_tried_objs", {}), ("_inert_objs", {}),
                      ("_touch_mark", {}), ("frontier", {}),
                      ("_stuck_in", {}), ("hints", {}), ("blockers", {}),
                      ("_offered", {}), ("_cut_bushes", {}),
                      ("_shelves", {}), ("flag_sites", {})):
        if not hasattr(ex, attr):
            setattr(ex, attr, val)
    return ex


def obs_at(region, mapid=None):
    m, r = region.split("|")
    return {"map": {"id": mapid or m, "region": r}, "player": {"x": 0, "y": 0},
            "mode": "overworld", "party": [], "flags": [], "bag": {}}


def main():
    print("the crossing that works gets its own name:")
    ex = ex_with()
    ex.note_transition(obs_at(R13), {"dir": "west", "skip": 1},
                       obs_at(MAIN))
    keys = list((ex.explored.get(R13) or {}).keys())
    check("a skipped cross is not filed as the plain direction",
          "west" not in keys, keys)
    check("...it is filed under the cell that produced it",
          keys == ["west#skip1"], keys)
    check("...and it still points where it landed",
          (ex.explored[R13]["west#skip1"] or {}).get("to") == MAIN,
          ex.explored.get(R13))

    ex.note_transition(obs_at(R13), {"dir": "west"}, obs_at(NOOK))
    check("the plain cross keeps its own entry, landing in the nook",
          (ex.explored[R13].get("west") or {}).get("to") == NOOK,
          ex.explored.get(R13))
    check("...so both landings of one seam are known at once",
          sorted(ex.explored[R13]) == ["west", "west#skip1"],
          sorted(ex.explored[R13]))

    print("\nand the router can reproduce it:")
    ex = ex_with(explored={R13: {"west#skip1": {"n": 1, "to": MAIN},
                                 "west": {"n": 5, "to": NOOK}},
                           NOOK: {"east": {"n": 5, "to": R13}}})
    ex.visits = {R13: 5, NOOK: 5, MAIN: 1}
    ex._mark_now = None
    path = ex._route(NOOK, MAIN)
    check("a route out of the nook to the main body exists",
          bool(path), path)
    check("...and it goes by the skip key, not the bare direction",
          path and path[-1][0] == "west#skip1", path)
    check("a door key is still a door key",
          E._is_door_key("18,5") and not E._is_door_key("west#skip1"))

    print("\n" + "-" * 60)
    if FAILS:
        print(f"THE SEAM CELL IS STILL BEING LOST: {len(FAILS)} case(s)")
        return 1
    print("both landings of a seam are kept, and the good one is walkable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
