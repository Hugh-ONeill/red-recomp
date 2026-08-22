#!/usr/bin/env python3
"""A pad the run has ridden is a way ONTO a map no walk can reach into.

Silph 5F's Card Key pocket is entered only by arriving on the pad at
(9,15) — a warp cell separates the two bands of its map, and walking
toward it teleports you away before you ever cross it. The one ride the
run made (9F's (17,15), taken once) was filed against the MAIN region by
the pre-seam flood, so its record taught nothing; the model spent a night
of attempts circling 3F/2F/5F while the key sat sighted-but-unreachable
(user: "i dont think its going to be able to solve it without that").

Two pieces, both here:

  _pad_arrivals(map)          — every WALKED doorway landing on the map,
                                one entry per doorway, least-ridden first
                                (the worn doors land on ground walk_to has
                                already failed from; the ride made once is
                                the one the flood may have mislabelled).
  _pad_recross_for_target(..) — ride the walked pair again, walk off the
                                far side; one shot per target per attempt,
                                capped at three arrivals, and a shot only
                                counts if something was actually ridden.

And the record that makes the next run smarter: an intra-map pad ride now
keeps its LANDING CELL (e["land"]) the same way cross-map doors do — the
label is the flood's inference, the cell is the walk.

No game, no model, no ledger on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))

import executor as E          # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def bare(explored=None):
    ex = object.__new__(E.Executor)
    ex.explored = explored or {}
    return ex


# The live ledger's Silph shape the night the key was stuck, verbatim
# counts: every arrival onto 5F the run had ever walked.
SILPH = {
    "SILPH_CO_3F|20,0": {"3,3": {"to": "SILPH_CO_5F|20,0", "n": 10},
                         "3,15": {"n": 13, "to": "SILPH_CO_5F|1,10"}},
    "SILPH_CO_4F|20,0": {"26,0": {"n": 7, "to": "SILPH_CO_5F|20,0"}},
    "SILPH_CO_6F|14,0": {"14,0": {"n": 2, "to": "SILPH_CO_5F|20,0"}},
    "SILPH_CO_7F|18,13": {"21,15": {"to": "SILPH_CO_5F|20,0", "n": 1}},
    "SILPH_CO_9F|14,0": {"17,15": {"n": 1, "to": "SILPH_CO_5F|20,0"}},
    "SILPH_CO_ELEVATOR|0,1": {
        "lift:SILPH_CO_5F": {"n": 14, "to": "SILPH_CO_5F|20,0"},
        "1,3": {"to": "SILPH_CO_5F|20,0", "n": 0}},
    "SILPH_CO_5F|20,0": {"9,15": {"to": "SILPH_CO_9F|14,0", "n": 2},
                         "walk:SILPH_CO_5F|1,10": {"n": 3, "intra": True,
                                                   "to": "SILPH_CO_5F|1,10"}},
}


def obs5f(region="20,0", x=1, y=10):
    return {"map": {"id": "SILPH_CO_5F", "region": region,
                    "player": {"x": x, "y": y}, "warps": []},
            "badges": [], "flags": ["f"], "bag": {}}


def main():
    print("the candidate list:")
    ex = bare(SILPH)
    got = ex._pad_arrivals("SILPH_CO_5F")
    check("every walked arrival onto the map is offered, nothing else",
          {(r, k) for _n, r, k in got}
          == {("SILPH_CO_3F|20,0", "3,3"), ("SILPH_CO_3F|20,0", "3,15"),
              ("SILPH_CO_4F|20,0", "26,0"), ("SILPH_CO_6F|14,0", "14,0"),
              ("SILPH_CO_7F|18,13", "21,15"),
              ("SILPH_CO_9F|14,0", "17,15")}, got)
    check("the ride made once outranks every worn door",
          [r for _n, r, _k in got[:2]]
          == ["SILPH_CO_7F|18,13", "SILPH_CO_9F|14,0"], got[:2])
    check("the lift is not an arrival (it lands door-to-door)",
          not any("lift" in k for _n, _r, k in got), got)
    check("a door never walked (n=0) is not a candidate",
          not any(k == "1,3" for _n, _r, k in got), got)
    check("an intra-map walk is not an arrival",
          not any(k.startswith("walk:") for _n, _r, k in got), got)

    ex = bare({"A|0,0": {"3,7": {"to": "B|0,0", "n": 2},
                         "4,7": {"to": "B|0,0", "n": 5},
                         "9,9": {"to": "B|0,0", "n": 1, "shut": True}}})
    got = ex._pad_arrivals("B")
    check("twin tiles fold to one doorway, counts combined, "
          "most-walked tile speaks",
          got == [(7, "A|0,0", "4,7")], got)
    check("a shut door is not an arrival", len(got) == 1, got)

    print("the ride:")
    # A scripted world: standing in main 5F, target 21,16 in the pocket.
    # 7F's door (tried first) lands in main again; 9F's pad sets you down
    # on the pocket side and the walk finishes.
    POCKET = obs5f("16,16", 9, 15)
    MAIN = obs5f("20,0", 1, 10)
    AT_9F = {"map": {"id": "SILPH_CO_9F", "region": "14,0",
                     "player": {"x": 17, "y": 15}, "warps": []}}

    def rig(routes, rides, walk_ok_from):
        """routes: {dest_region: path or None}; rides: {(x,y): landing obs};
        walk_ok_from: set of regions walk_to succeeds from."""
        ex = bare({k: dict(v) for k, v in SILPH.items()})
        world = {"obs": MAIN}
        calls, notes, logs = [], [], []
        ex.b = type("B", (), {"obs": staticmethod(lambda: world["obs"])})()
        ex.settle = lambda: world["obs"]
        ex._route = lambda frm, to: routes.get(to, None)

        def _wr(sg, path):
            mid, reg = path[-1][1].split("|")
            world["obs"] = {"map": {"id": mid, "region": reg,
                                    "player": {"x": 0, "y": 0},
                                    "warps": []}}
            return world["obs"]
        ex._walk_route = _wr
        ex.note_transition = lambda *a, **k: notes.append(k)
        ex.log = lambda ev, **k: logs.append((ev, k))

        def send(op, **kw):
            calls.append((op, kw))
            if op == "use_warp":
                land = rides.get((kw["x"], kw["y"]))
                if land is not None:
                    world["obs"] = land
                return {"result": {"ok": land is not None,
                                   "detail": "warped map->"
                                   + (land or {}).get("map", {}).get("id",
                                                                     "")}}
            if op == "walk_to":
                here = E.Executor._where(world["obs"])
                if here in walk_ok_from:
                    m = dict(world["obs"]["map"],
                             player={"x": kw["x"], "y": kw["y"]})
                    world["obs"] = dict(world["obs"], map=m)
                    return {"result": {"ok": True, "detail": "walked"}}
                return {"result": {"ok": False, "detail":
                        ("no path — the ground you can walk from here is "
                         "5 cell(s) and the closest it comes to "
                         f"{kw['x']},{kw['y']} is {kw['x']},"
                         f"{int(kw['y']) - 1}")}}
            return {"result": {"ok": True}}
        ex._send_safe = send
        return ex, calls, notes, logs

    routes = {"SILPH_CO_7F|18,13": [("27,3", "SILPH_CO_7F|18,13")],
              "SILPH_CO_9F|14,0": [("9,15", "SILPH_CO_9F|14,0")]}
    rides = {(21, 15): MAIN, (17, 15): POCKET,
             (3, 3): MAIN, (3, 15): MAIN, (26, 0): MAIN, (14, 0): MAIN}
    ex, calls, notes, logs = rig(routes, rides,
                                 walk_ok_from={"SILPH_CO_5F|16,16"})
    o = ex._pad_recross_for_target(MAIN, {"id": "t"}, 21, 16)
    check("the ride made once gets its turn and the walk finishes",
          o is not None and E.Executor._where(o) == "SILPH_CO_5F|16,16"
          and o["map"]["player"] == {"x": 21, "y": 16}, o)
    check("the doorway that lands on walked ground was tried and passed "
          "over", ("use_warp", {"x": 21, "y": 15}) in calls
          and calls.index(("use_warp", {"x": 21, "y": 15}))
          < calls.index(("use_warp", {"x": 17, "y": 15})), calls)
    check("every ride is recorded as a transition", len(notes) == 2, notes)
    check("the ledger hears the verdict",
          any(ev == "pad_recrossed" and k.get("reached") for ev, k in logs),
          logs)
    check("one shot per target per attempt",
          ex._pad_recross_for_target(MAIN, {"id": "t"}, 21, 16) is None)

    # nothing routable: not a shot spent — retryable from other ground
    ex, calls, notes, logs = rig({}, rides, set())
    o = ex._pad_recross_for_target(MAIN, {"id": "t"}, 21, 16)
    check("no walked way to any doorway spends nothing",
          o is None and ex._last_pad_rides == 0
          and (("SILPH_CO_5F", 21, 16)
               not in getattr(ex, "_pad_recrossed", set())), calls)

    # a ride that lands off-map is a miss, not a landing to walk from
    ex, calls, notes, logs = rig(routes, {(21, 15): AT_9F, (17, 15): POCKET},
                                 walk_ok_from={"SILPH_CO_5F|16,16"})
    o = ex._pad_recross_for_target(MAIN, {"id": "t"}, 21, 16)
    check("a ride that lands elsewhere is logged and passed over",
          o is not None
          and any(ev == "pad_recross_missed" for ev, k in logs), logs)

    # three arrivals is the cap
    ex, calls, notes, logs = rig(
        {r: [("x", r)] for r in
         ("SILPH_CO_3F|20,0", "SILPH_CO_4F|20,0", "SILPH_CO_6F|14,0",
          "SILPH_CO_7F|18,13", "SILPH_CO_9F|14,0")}, rides, set())
    o = ex._pad_recross_for_target(MAIN, {"id": "t"}, 21, 16)
    check("three arrivals is a fair try, and the count is told",
          o is None and ex._last_pad_rides == 3,
          (ex._last_pad_rides,
           [c for c in calls if c[0] == "use_warp"]))

    # A SOLID TARGET CANNOT BE STOOD ON: the ball occupies its own tile,
    # so walk_to to that exact cell fails even from inside the pocket the
    # ride just entered — beside it IS arrival (watched live: the recall
    # rode 9F's pad onto the Card Key's side and walked back out)
    POCKETB = dict(POCKET, map=dict(
        POCKET["map"],
        objects=[{"x": 21, "y": 16, "name": "ITEM_SILPH_CO_5F_21_16"}]))
    ex, calls, notes, logs = rig(routes, {**rides, (17, 15): POCKETB},
                                 walk_ok_from=set())
    o = ex._pad_recross_for_target(MAIN, {"id": "t"}, 21, 16)
    check("landing beside a thing on the target tile counts as arrival",
          o is not None and E.Executor._where(o) == "SILPH_CO_5F|16,16"
          and ex._last_pad_adjacent, (o, ex._last_pad_rides))
    check("...but bare adjacency with nothing on the tile does not",
          E.Executor._thing_at(POCKETB, 21, 16)
          and not E.Executor._thing_at(POCKET, 21, 16))

    # a caller whose op IS the question sends a probe: an item ball's
    # tile is solid, you stand beside it and press, so "did the walk
    # finish" is the wrong question and the op itself is the right one
    ex, calls, notes, logs = rig(routes, rides, walk_ok_from=set())
    hits = []

    def probe():
        here = E.Executor._where(ex.b.obs())
        hits.append(here)
        if here == "SILPH_CO_5F|16,16":
            return True, None, "you stood beside it and pressed"
        return False, None, ""
    o = ex._pad_recross_for_target(MAIN, {"id": "t"}, 21, 16, probe=probe)
    check("the probe is asked at every landing and its verdict rules",
          o is not None
          and hits == ["SILPH_CO_5F|20,0", "SILPH_CO_5F|16,16"]
          and ex._last_pad_detail == "you stood beside it and pressed",
          (hits, o))
    check("no walk_to is sent when the probe owns the question",
          not any(c[0] == "walk_to" for c in calls), calls)

    print("the name:")
    C = E.Executor._item_name_coords
    check("a map-qualified name yields its coordinates",
          C("ITEM_SILPH_CO_5F_21_16") == (21, 16))
    check("a map id ending in a number does not eat a coordinate",
          C("ITEM_ROUTE_12_5_89") == (5, 89))
    check("the bare shape older plans still carry resolves too",
          C("ITEM_21_16") == (21, 16))
    check("a non-item name yields nothing",
          C("SILPHCO2F_SCIENTIST1") == (None, None)
          and C("") == (None, None))

    print("the record:")
    # The intra-map branch keeps the landing cell now, like the cross-map
    # write always did: ride Silph 3F's (23,11) pad, land at (27,15), and
    # the edge remembers WHERE — the one fact that tells its sides apart.
    ex = bare({})
    for attr, val in (("visits", {}), ("_faint_at", None),
                      ("_entered_by", {}), ("_intra_prev", None),
                      ("door_dests", {}), ("frontier", {})):
        setattr(ex, attr, val)
    ex.log = lambda *a, **k: None
    ex._save_memory = lambda: None
    ex._count_visit = lambda r: None
    before = {"map": {"id": "SILPH_CO_3F", "region": "20,0",
                      "player": {"x": 23, "y": 11},
                      "warps": [{"x": 23, "y": 11, "dest": "SILPH_CO_3F",
                                 "reachable": True}]}}
    after = {"map": {"id": "SILPH_CO_3F", "region": "20,0",
                     "player": {"x": 27, "y": 15}, "warps": []},
             "result": {}}
    ex.note_transition(before, {"x": 23, "y": 11}, after,
                       op_detail="warped map->SILPH_CO_3F")
    e = ex.explored.get("SILPH_CO_3F|20,0", {}).get("23,11") or {}
    check("an intra-map pad ride keeps its landing cell",
          e.get("land") == "27,15" and e.get("n") == 1, e)

    print(f"\n{'-' * 60}")
    if FAILS:
        print(f"A PAD ARRIVAL IS BEING WASTED: {len(FAILS)} case(s)")
        return 1
    print("a walked pad is a way onto ground no walk can reach, "
          "and the harness now rides it by recall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
