#!/usr/bin/env python3
"""Adjacent warp tiles with one destination are ONE door, everywhere.

The Safari rest house rendered as "3. door (2,7) -> ... taken 1x" and
"4. door (3,7) -> ... taken 7x" — two numbered entries, two counts, one
doorway (user, 2026-08-22: "when warps are next to each other like that
and lead to the same area then they are functionally the same warp").

The relation lives in ONE place, Executor._door_groups, and both halves
of it are load-bearing:

  ADJACENT — the trashed house's two doors to the same city sit either
  side of a fence, seven tiles apart; they stay separate.
  SAME DESTINATION — CELADON_MANSION has an up-stair NEXT TO a down-stair
  and SEAFOAM B3F has neighbouring ladders to different floors (the only
  three adjacent different-destination pairs in the whole game, checked
  against every map); they stay separate.

And it is applied by every reader (untried.py's law): the ledger's
candidate list, _untried_exits, and _frontier_left — the last through
door_dests, the internal record of each sighted doorway's destination,
which is never printed (the claim rule forbids SAYING where a door goes,
not knowing which two tiles are one door).

No game, no model, no ledger on disk.
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
from candidates import make, obs   # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def W(x, y, dest, reachable=True):
    return {"x": x, "y": y, "dest": dest, "reachable": reachable}


def main():
    G = E.Executor._door_groups

    print("the relation:")
    g = G([W(2, 7, "A"), W(3, 7, "A")])
    check("an adjacent same-dest pair is one group",
          g["2,7"] == ("2,7", "3,7") and g["3,7"] == ("2,7", "3,7"), g)
    g = G([W(15, 47, "A"), W(16, 47, "A"), W(17, 47, "A"), W(18, 47, "A")])
    check("a four-tile door groups transitively (Viridian Forest south)",
          g["15,47"] == ("15,47", "16,47", "17,47", "18,47"), g)
    g = G([W(6, 1, "CELADON_MANSION_2F"), W(7, 1, "CELADON_MANSION_ROOF")])
    check("adjacent stairs to DIFFERENT floors stay separate (Celadon)",
          g["6,1"] == ("6,1",) and g["7,1"] == ("7,1",), g)
    g = G([W(27, 9, "CERULEAN_CITY"), W(27, 11, "CERULEAN_CITY")])
    check("same dest but NOT adjacent stays separate (the fence)",
          g["27,9"] == ("27,9",) and g["27,11"] == ("27,11",), g)
    g = G([W(2, 7, None), W(3, 7, None)])
    check("no destination knowledge folds nothing",
          g["2,7"] == ("2,7",), g)

    ex = make()
    tw = ex._twin_keys(
        {"map": {"warps": [W(15, 47, "A"), W(16, 47, "A"),
                           W(17, 47, "A"), W(18, 47, "A")]}},
        {"x": 16, "y": 47})
    check("_twin_keys names every other tile of the doorway",
          sorted(tw) == ["15,47", "17,47", "18,47"], tw)

    print("the ledger:")
    HERE = "SAFARI_ZONE_NORTH_REST_HOUSE|0,1"
    ex = make(explored={HERE: {"2,7": {"n": 1, "to": "SAFARI_ZONE_WEST|20,0"},
                               "3,7": {"n": 7, "to": "SAFARI_ZONE_WEST|20,0"}}},
              frontier={HERE: ["2,7", "3,7"]})
    ex.visits = {HERE: 8, "SAFARI_ZONE_WEST|20,0": 8}
    ex._arrived = (HERE, (3, 7))
    ex._came_from = "SAFARI_ZONE_WEST|20,0"
    o = obs(ex, ["2,7", "3,7"], region="0,1",
            dests={"2,7": "SAFARI_ZONE_WEST", "3,7": "SAFARI_ZONE_WEST"})
    o["map"]["id"] = "SAFARI_ZONE_NORTH_REST_HOUSE"
    cands = L.build(ex, o, target="flag:X")
    doors = [c for c in cands if c.kind == "door"]
    check("the rest house's two tiles are ONE line", len(doors) == 1,
          [c.key for c in doors])
    d = doors[0]
    check("the most-walked tile speaks for it", d.key == "3,7", d.key)
    check("the counts combine", d.n == 8, d.n)
    check("the label shows every tile it spans",
          d.label() == "door (3,7)+(2,7) — ONE doorway, two tiles wide", d.label())
    check("it is the door you came in by", d.status == "came_in_by",
          d.status)
    check("a use_warp at EITHER tile is on-ledger",
          L.lookup(cands, {"op": "use_warp", "x": 2, "y": 7}) is d
          and L.lookup(cands, {"op": "use_warp", "x": 3, "y": 7}) is d)

    # one tile walked, its twin never: the doorway is TAKEN, not untried
    ex = make(explored={U.HERE: {"3,7": {"n": 2, "to": "B|0,0"}}},
              frontier={U.HERE: ["3,7", "4,7"]})
    o = U.obs_for(ex, ["3,7", "4,7"])
    cands = L.build(ex, o, target="flag:X")
    check("a walked door's twin is not a fresh exit",
          L.untried_keys(cands) == set(),
          L.untried_keys(cands))
    check("...and _untried_exits agrees",
          U.keys_of(ex._untried_exits(o)) == set(),
          ex._untried_exits(o))

    # neither tile walked: one untried entry, both definitions
    ex = make(frontier={U.HERE: ["3,7", "4,7"]})
    o = U.obs_for(ex, ["3,7", "4,7"])
    cands = L.build(ex, o, target="flag:X")
    check("an unwalked doorway is ONE untried exit",
          L.untried_keys(cands) == {"3,7"}, L.untried_keys(cands))
    check("...and _untried_exits agrees",
          U.keys_of(ex._untried_exits(o)) == {"3,7"},
          ex._untried_exits(o))

    print("the blocked-doorways reader:")
    # two unreachable, untaken twin tiles with a person near: ONE entry,
    # keyed by the joined span the renderer prints as "(3,7+4,7)"
    ex = make(frontier={U.HERE: []})
    o = U.obs_for(ex, [])
    o["map"]["warps"] = [
        {"x": 3, "y": 7, "dest": "SOMEWHERE", "reachable": False},
        {"x": 4, "y": 7, "dest": "SOMEWHERE", "reachable": False}]
    o["map"]["objects"] = [{"x": 3, "y": 6, "name": "GUARD",
                            "reachable": True}]
    got = ex._unopened_doors(o)
    check("a blocked double door is one doorway",
          [(k, who) for k, _d, who in got] == [("3,7+4,7", "GUARD")], got)
    # ...and a doorway with one tile still reachable is not blocked at all
    o["map"]["warps"][1]["reachable"] = True
    got = ex._unopened_doors(o)
    check("a doorway with an open twin tile is not listed as blocked",
          got == [], got)

    print("the shim's labels (the same code the game runs):")
    lua_src = (ROOT / "harness/shim.lua").read_text()
    import re as _re
    m = _re.search(r"(local function doorway_labels\(ws\).*?\nend\n)",
                   lua_src, _re.S)
    check("doorway_labels found in the shim", bool(m))
    if m:
        import subprocess
        script = m.group(1) + """
local function eq(got, want)
  if #got ~= #want then return false end
  for i = 1, #want do if got[i] ~= want[i] then return false end end
  return true
end
local W = function(x, y, d) return { x = x, y = y, dest = d } end
assert(eq(doorway_labels({ W(14,8,"LAST_MAP"), W(14,9,"LAST_MAP") }),
          { "(14,8)+(14,9)" }), "gate pair folds")
assert(eq(doorway_labels({ W(6,1,"CELADON_MANSION_2F"),
                           W(7,1,"CELADON_MANSION_ROOF") }),
          { "(6,1)", "(7,1)" }), "adjacent stairs stay separate")
assert(eq(doorway_labels({ W(27,9,"CERULEAN_CITY"),
                           W(27,11,"CERULEAN_CITY") }),
          { "(27,11)", "(27,9)" }), "the fence pair stays separate")
print("lua-ok")
"""
        r = subprocess.run(["lua", "-e", script], capture_output=True,
                           text=True)
        check("the shim folds and separates the same way",
              r.returncode == 0 and "lua-ok" in r.stdout,
              (r.stdout + r.stderr)[:200])

    print("the remote reader:")
    ex = make(explored={U.HERE: {"3,7": {"n": 2, "to": "B|0,0"}}},
              frontier={U.HERE: ["3,7", "4,7"]})
    ex.door_dests = {"TESTMAP": {"3,7": "B", "4,7": "B"}}
    check("_frontier_left folds the walked door's twin away",
          ex._frontier_left(U.HERE) == [], ex._frontier_left(U.HERE))
    ex = make(frontier={U.HERE: ["3,7", "4,7"]})
    ex.door_dests = {"TESTMAP": {"3,7": "B", "4,7": "B"}}
    check("an unwalked doorway counts once",
          ex._frontier_left(U.HERE) == ["3,7"], ex._frontier_left(U.HERE))
    ex = make(frontier={U.HERE: ["3,7", "4,7"]})
    ex.door_dests = {"TESTMAP": {"3,7": "B", "4,7": "C"}}
    check("different destinations stay two exits (Celadon shape)",
          sorted(ex._frontier_left(U.HERE)) == ["3,7", "4,7"],
          ex._frontier_left(U.HERE))
    ex = make(frontier={U.HERE: ["3,7", "4,7"]})
    ex.door_dests = {}
    check("no recorded destinations, no folding",
          sorted(ex._frontier_left(U.HERE)) == ["3,7", "4,7"],
          ex._frontier_left(U.HERE))

    print(f"\n{'-' * 60}")
    if FAILS:
        print(f"A DOORWAY IS BEING MISCOUNTED: {len(FAILS)} case(s)")
        return 1
    print("a doorway is one door in every reader, and the three real "
          "different-destination neighbours stay separate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
