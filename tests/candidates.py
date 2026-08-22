#!/usr/bin/env python3
"""The ledger must agree with the two definitions of UNTRIED, must not
refuse what it offers, and must not name what the run has not walked.

Runs tests/untried.py's synthetic worlds through planner/ledger.build and
checks, per world, that the ledger's untried exits equal `_untried_exits`
(the law from tests/untried.py: two implementations, one is wrong — the
ledger is a THIRD, and it is held to the same rule). Then a handful of
ledger-specific worlds:

  * the door you came in by is on the ledger, offered, and NOT untried;
  * a door never walked shows no destination (frontage words at most);
  * a taken door shows its walked destination and count;
  * lookup() finds every key it rendered and returns None for a coordinate
    that is not here — the only thing the guard may refuse on this ground;
  * an interact by x,y is always on-ledger (a tile press);
  * render() numbers what build() ranked and says how many it cut.

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
import untried as U           # noqa: E402  (its fixture and its cases)


def make(**kw):
    """untried.py's fixture plus the ledger's other readers, all empty."""
    ex = U.make(**kw)
    ex._tried_objs = {}
    ex._inert_objs = {}
    ex._touch_mark = {}
    ex.dead_ends = {}
    ex._arrived = None
    ex._came_from = None
    return ex


def obs(ex, warps, conns=None, objects=None, mark_flags=1, region="0,0",
        dests=None):
    o = U.obs_for(ex, warps, conns, mark_flags)
    if dests:
        for w in o["map"]["warps"]:
            w["dest"] = dests.get(f"{w['x']},{w['y']}", w["dest"])
    o["map"]["region"] = region
    o["map"]["objects"] = objects or []
    return o


FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    print("untried.py's worlds, through the ledger:")
    for name, fn in U.CASES:
        ex, o, want = fn()
        for attr, val in (("_tried_objs", {}), ("_inert_objs", {}),
                          ("_touch_mark", {}), ("dead_ends", {}),
                          ("_arrived", None), ("_came_from", None)):
            if not hasattr(ex, attr):
                setattr(ex, attr, val)
        cands = L.build(ex, o, target="flag:X")
        got = L.untried_keys(cands)
        live = U.keys_of(ex._untried_exits(o))
        check(name, got == live and got == want,
              f"ledger {sorted(got)}  _untried_exits {sorted(live)}  want {sorted(want)}")
        # nothing rendered is refused: every door/seam key looks itself up
        for c in cands:
            if c.kind == "door":
                x, y = c.key.split(",")
                check(f"    lookup finds door {c.key}",
                      L.lookup(cands, {"op": "use_warp", "x": int(x), "y": int(y)}) is c)
            elif c.kind == "seam":
                check(f"    lookup finds seam {c.key}",
                      L.lookup(cands, {"op": "cross", "dir": c.key}) is c)

    print("\nledger-specific rules:")
    # --- came-in-by: on the ledger, offered, not untried --------------
    ex = make(explored={U.HERE: {"1,1": {"to": "OUT|0,0", "n": 0}}},
              frontier={U.HERE: ["1,1", "2,2"]})
    ex._arrived = (U.HERE, (1, 1))
    ex._came_from = "OUT|0,0"
    o = obs(ex, ["1,1", "2,2"], dests={"1,1": "OUT", "2,2": "ELSE"})
    cands = L.build(ex, o, target="flag:X")
    door = L.lookup(cands, {"op": "use_warp", "x": 1, "y": 1})
    check("the arrival door is on the ledger", door is not None)
    check("...offered (never refused for being back-tracking)", door.offer)
    check("...and not untried", door.status == "came_in_by",
          f"status={door.status}")
    check("...while the other door IS untried",
          L.lookup(cands, {"op": "use_warp", "x": 2, "y": 2}).status == "untried")
    check("the ledger's untried set still matches _untried_exits",
          L.untried_keys(cands) == U.keys_of(ex._untried_exits(o)))
    # its twin tile is the same door
    ex2 = make(explored={U.HERE: {"1,1": {"to": "OUT|0,0", "n": 0}}},
               frontier={U.HERE: ["1,1", "1,2"]})
    ex2._arrived = (U.HERE, (1, 1))
    ex2._came_from = "OUT|0,0"
    o2 = obs(ex2, ["1,1", "1,2"], dests={"1,1": "OUT", "1,2": "OUT"})
    c2 = L.build(ex2, o2, target="flag:X")
    check("the arrival door's twin tile is the same door, not untried",
          L.lookup(c2, {"op": "use_warp", "x": 1, "y": 2}).status == "came_in_by")

    # --- an unwalked door names no destination ------------------------
    ex = make(frontier={U.HERE: ["3,3", "4,4"]})
    o = obs(ex, ["3,3", "4,4"], dests={"3,3": "SECRET_CAVE_1F",
                                       "4,4": "PEWTER_MART"})
    cands = L.build(ex, o, target="flag:X")
    text = L.render(cands, ex, o, target="flag:X")
    check("an unwalked door does not name its destination",
          "SECRET_CAVE" not in text, text)
    check("...but a building that looks like what it is gets its frontage",
          "POKEMART" in text, text)
    check("...and reads UNKNOWN", "(3,3) -> UNKNOWN" in text, text)

    # --- a taken door shows the walked destination and count ----------
    ex = make(explored={U.HERE: {"3,3": {"to": "CAVE|0,0", "n": 4}}},
              frontier={U.HERE: ["3,3"]})
    o = obs(ex, ["3,3"], dests={"3,3": "CAVE"})
    cands = L.build(ex, o, target="flag:X")
    text = L.render(cands, ex, o, target="flag:X")
    check("a walked door names where the run came out, and how often",
          "-> CAVE|0,0" in text and "taken 4x" in text, text)

    # --- lookup: off-ledger is None; a tile press is always on ---------
    check("a coordinate that is not a door here is OFF-LEDGER",
          L.lookup(cands, {"op": "use_warp", "x": 9, "y": 9}) is None)
    check("a direction this map does not have is OFF-LEDGER",
          L.lookup(cands, {"op": "cross", "dir": "west"}) is None)
    check("an interact by x,y is always on-ledger (a tile press)",
          L.lookup(cands, {"op": "interact", "x": 5, "y": 5}) is not None)
    check("an op with no place (buy) is never refused on this ground",
          L.lookup(cands, {"op": "buy", "item": "POTION"}) is not None)

    # --- things: untouched / touched / inert / unspoken ---------------
    ex = make(frontier={U.HERE: []})
    ex._tried_objs = {U.HERE: {"CLERK"}}
    o = obs(ex, [], objects=[
        {"name": "CLERK", "kind": "npc", "x": 1, "y": 1, "reachable": True},
        {"name": "KID", "kind": "npc", "x": 2, "y": 1, "reachable": True},
        {"name": "BALL", "kind": "item", "x": 3, "y": 1, "reachable": True},
        {"name": "FAR_SIGN", "kind": "sign", "x": 9, "y": 9, "reachable": False},
    ])
    cands = L.build(ex, o, target="flag:X",
                    outcomes={"CLERK": {"n": 4, "last": "Okay! Say hi to PROF.OAK for me!"}})
    st = {c.key: c for c in cands}
    check("a person spoken to is 'touched' with its count and last words",
          st["CLERK"].status == "touched" and st["CLERK"].n == 4
          and "Say hi" in st["CLERK"].note)
    check("a person never spoken to is 'unspoken'", st["KID"].status == "unspoken")
    check("an item never taken is 'untouched'", st["BALL"].status == "untouched")
    check("a sign you cannot walk to is 'unreachable'",
          st["FAR_SIGN"].status == "unreachable")
    check("untouched things rank above touched ones",
          cands.index(st["BALL"]) < cands.index(st["CLERK"]))
    check("explore is entry 1 and would press the untouched item first",
          cands[0].key == "explore" and "press BALL" in cands[0].note,
          cands[0].note)
    text = L.render(cands, ex, o, target="flag:X")
    check("render numbers the entries and quotes the last words",
          " 1. explore" in text and "Say hi to PROF.OAK" in text, text)

    # --- explore plans a walk when nothing here is untried ------------
    ex = make(explored={U.HERE: {"north": {"to": "NEXT|0,0", "n": 2}},
                        "NEXT|0,0": {"south": {"to": U.HERE, "n": 2}}},
              frontier={U.HERE: ["north"], "NEXT|0,0": ["south", "7,7"]})
    o = obs(ex, [], ["north"])
    cands = L.build(ex, o, target="flag:X")
    check("with nothing untried here, explore names the nearest area that has one",
          "NEXT|0,0" in cands[0].note and "walk north" in cands[0].note,
          cands[0].note)

    # --- THE IDEAL: a fully worked area says so, and explore leaves it ---
    # Route 1's shape from the live leg-2 journal: two seams, both taken
    # (the run ping-ponged south/north between worked areas), two people
    # spoken to, a sign read. Pallet to the south is worked too; Viridian
    # to the north still has an untried door and an unpressed thing.
    R1, PAL, VIR = "ROUTE_1|10,0", "PALLET_TOWN|10,0", "VIRIDIAN_CITY|17,0"
    ex = make(explored={R1: {"south": {"to": PAL, "n": 4},
                             "north": {"to": VIR, "n": 4}},
                        PAL: {"north": {"to": R1, "n": 4}},
                        VIR: {"south": {"to": R1, "n": 4}}},
              frontier={R1: ["south", "north"], PAL: ["north"],
                        VIR: ["south", "32,7"]})
    ex.visits = {R1: 9, PAL: 5, VIR: 6}
    ex.map_doors = {}
    ex.searched = {"*": {PAL: True}}
    ex.sightings = {VIR: ["VIRIDIANCITY_OLD_MAN", "TEXT_VIRIDIANCITY_SIGN"]}
    ex._tried_objs = {R1: {"ROUTE1_YOUNGSTER1", "ROUTE1_YOUNGSTER2",
                           "TEXT_ROUTE1_SIGN"},
                      VIR: {"TEXT_VIRIDIANCITY_SIGN"}}
    o = {"map": {"id": "ROUTE_1", "region": "10,0", "warps": [],
                 "connections": {"south": "PALLET_TOWN", "north": "VIRIDIAN_CITY"},
                 "objects": [
                     {"name": "ROUTE1_YOUNGSTER1", "kind": "npc", "x": 5, "y": 24, "reachable": True},
                     {"name": "ROUTE1_YOUNGSTER2", "kind": "npc", "x": 11, "y": 15, "reachable": True},
                     {"name": "TEXT_ROUTE1_SIGN", "kind": "sign", "x": 9, "y": 27, "reachable": True}]},
         "player": {"x": 10, "y": 0}, **U.world(1)}
    cands = L.build(ex, o, target="flag:X",
                    outcomes={"south": {"n": 4, "last": "crossed and came straight back"},
                              "north": {"n": 4, "last": "crossed and came straight back"}})
    check("a worked area is recognised as fully worked", L.fully_worked(cands))
    text = L.render(cands, ex, o, target="flag:X")
    check("...and the header says so", "FULLY WORKED" in text, text)
    st = {c.key: c for c in cands}
    check("the seam back into worked ground says nothing new lies that way",
          "fully worked" in st["south"].beyond and "nothing new" in st["south"].beyond,
          st["south"].beyond)
    check("the seam toward ground with something left says what is left there",
          "1 exit(s) never taken" in st["north"].beyond
          and "1 thing(s) never pressed" in st["north"].beyond, st["north"].beyond)
    check("...and that clause is never cut behind a long quote",
          "never pressed (VIRIDIANCITY_OLD_MAN)" in text, text)
    check("explore leaves: it names the nearest ground with something and the first leg",
          "FULLY WORKED" in cands[0].note and VIR in cands[0].note
          and "walk north" in cands[0].note, cands[0].note)
    check("nothing here is offered as untried", L.untried_keys(cands) == set())

    # --- the badge-house shape: front door twins are came-in-by, the back
    # door to the same map is NOT (arrival tile ± 1 only) ------------------
    HOUSE = "CERULEAN_BADGE_HOUSE|2,0"
    ex = make(explored={}, frontier={HOUSE: ["2,7", "3,7", "2,0"]})
    ex.visits = {HOUSE: 1, "CERULEAN_CITY|20,0": 5}
    ex._arrived = (HOUSE, (2, 7))
    ex._came_from = "CERULEAN_CITY|20,0"
    o = obs(ex, ["2,7", "3,7", "2,0"], region="2,0",
            dests={"2,7": "CERULEAN_CITY", "3,7": "CERULEAN_CITY",
                   "2,0": "CERULEAN_CITY"})
    o["map"]["id"] = "CERULEAN_BADGE_HOUSE"
    cands = L.build(ex, o, target="flag:X")
    st = {c.key: c for c in cands}
    check("the arrival tile is the door you came in by", st["2,7"].status == "came_in_by")
    # the twin tile is not a second entry any more: adjacent tiles with one
    # destination are ONE door, folded into the arrival tile's line
    check("its twin tile is folded into it as the same door",
          "3,7" not in st and st["2,7"].twins == ["3,7"],
          f"twins={st['2,7'].twins} keys={sorted(st)}")
    check("the BACK door to the same map is untried, not came-in-by",
          st["2,0"].status == "untried", st["2,0"].status)
    # outdoors: arrival one tile in front of the door still counts
    ex._arrived = (HOUSE, (2, 8))
    cands = L.build(ex, o, target="flag:X")
    check("a door adjacent to the arrival tile counts (you stand in front of it)",
          {c.key: c for c in cands}["2,7"].status == "came_in_by")

    # --- a regrown bush is not a fresh way on ------------------------------
    ex = make(frontier={U.HERE: []})
    ex._cut_bushes = {"TESTMAP": ["5,5"]}
    o = U.obs_for(ex, [])
    o["map"]["objects"] = [{"name": "CUT_TREE", "kind": "cut_tree",
                            "x": 5, "y": 5, "reachable": True}]
    o["party"] = [{"species": "F", "moves": [{"id": "CUT"}]}]
    cands = L.build(ex, o, target="flag:X")
    bush = next(c for c in cands if c.kind == "cut_tree")
    check("a bush cut before reads recut, not cuttable",
          bush.status == "recut", bush.status)
    check("...and a room whose only lure is a regrown bush is fully worked",
          L.fully_worked(cands))
    ex._cut_bushes = {}
    cands = L.build(ex, o, target="flag:X")
    bush = next(c for c in cands if c.kind == "cut_tree")
    check("a bush never cut is still a way on",
          bush.status == "cuttable", bush.status)

    # --- bushes ------------------------------------------------------------
    ex = make(frontier={U.HERE: []})
    o = obs(ex, [], objects=[
        {"name": "CUT_TREE", "kind": "cut_tree", "x": 4, "y": 4, "reachable": True}])
    cands = L.build(ex, o, target="flag:X")
    check("a bush is not 'never pressed'; without CUT it is 'bush'",
          {c.key: c for c in cands}["CUT_TREE"].status == "bush")
    check("...and does not keep the area from reading fully worked",
          L.fully_worked(cands))
    check("...and explore does not try to press it",
          "press" not in cands[0].note, cands[0].note)
    o["party"] = [{"species": "X", "moves": [{"id": "CUT", "pp": 30}]}]
    cands = L.build(ex, o, target="flag:X")
    check("with CUT known it is 'cuttable' and explore would cut it",
          {c.key: c for c in cands}["CUT_TREE"].status == "cuttable"
          and "CUT the bush at (4,4)" in cands[0].note, cands[0].note)

    # --- exits are never cut by the render cap ---------------------------
    ex = make(frontier={U.HERE: [f"{i},{i}" for i in range(1, 6)]})
    many = [{"name": f"NPC{i}", "kind": "npc", "x": i, "y": 9, "reachable": True}
            for i in range(30)]
    o = obs(ex, [f"{i},{i}" for i in range(1, 6)], objects=many)
    cands = L.build(ex, o, target="flag:X")
    text = L.render(cands, ex, o, target="flag:X", limit=10)
    check("every door is rendered even under a small cap",
          all(f"door ({i},{i})" in text for i in range(1, 6)), text)
    check("...and the cut is reported as things, not exits",
          "more thing(s) not shown" in text, text)

    # --- switches: a room of pressed trash cans is not fully worked ------
    ex = make(frontier={U.HERE: []})
    ex._tried_objs = {U.HERE: {"TRASH_CAN_1", "TRASH_CAN_2", "PC"}}
    o = obs(ex, [], objects=[
        {"name": "TRASH_CAN_1", "kind": "fixture", "x": 1, "y": 1, "reachable": True},
        {"name": "TRASH_CAN_2", "kind": "fixture", "x": 3, "y": 1, "reachable": True},
        {"name": "PC", "kind": "fixture", "x": 5, "y": 1, "reachable": True}])
    cands = L.build(ex, o, target="flag:X")
    check("a room of pressed switches is NOT fully worked", not L.fully_worked(cands))
    text = L.render(cands, ex, o, target="flag:X")
    check("...the header says the fixtures can be pressed again",
          "can be pressed AGAIN" in text and "TRASH_CAN_1" in text, text)
    check("...and each can's entry says so too", "a fixture; it can be pressed again" in text)
    ex._tried_objs = {U.HERE: {"PC"}}
    o = obs(ex, [], objects=[{"name": "PC", "kind": "fixture", "x": 5, "y": 1, "reachable": True}])
    check("a PC alone does not keep a room open (it is a service, not a switch)",
          L.fully_worked(L.build(ex, o, target="flag:X")))

    # --- explore never reaches for what cannot be walked to --------------
    ex = make(explored={U.HERE: {"1,1": {"to": "GATE|0,0", "n": 2}}},
              frontier={U.HERE: ["1,1"], "GATE|0,0": ["9,9"]})
    ex.visits = {U.HERE: 3, "GATE|0,0": 1}
    o = obs(ex, ["1,1"], objects=[
        {"name": "HP_UP", "kind": "item", "x": 13, "y": 45, "reachable": False}])
    cands = L.build(ex, o, target="map:PEWTER_CITY")
    st = {c.key: c for c in cands}
    check("an unreachable item is still listed as never pressed",
          st["HP_UP"].status == "untouched" and not st["HP_UP"].reachable)
    check("...but ranks below the walked door with something beyond it",
          cands.index(st["1,1"]) < cands.index(st["HP_UP"]))
    check("...and explore does not try to press it",
          "HP_UP" not in cands[0].note, cands[0].note)

    print(f"\n{'-' * 60}")
    if FAILS:
        print(f"LEDGER BROKEN: {len(FAILS)} check(s) failed")
        return 1
    print("the ledger agrees with both definitions and keeps the claim rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
