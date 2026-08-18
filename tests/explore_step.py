#!/usr/bin/env python3
"""`explore` picks what the ledger ranks first, and the reply parser keeps
the model's plan.

No game, no model. The executor's _run_traced / _walk_route / settle are
stubbed on a bare object so only the DECISION is under test:

  * a thing here never pressed  -> explore presses it (items before people)
  * nothing unpressed, an exit here never taken -> explore takes it
  * fully worked here, a neighbour with something left, a walked route
    -> explore walks there and expands once on arrival
  * nothing anywhere -> explore says so and runs nothing

and _parse_macro:
  * {"plan": ..., "ops": [...]} -> (ops, plan)
  * a bare array                -> (ops, "")
  * prose around either         -> still parsed
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


def bare(**kw):
    ex = U.make(**kw)
    for attr, val in (("_tried_objs", {}), ("_inert_objs", {}),
                      ("_touch_mark", {}), ("dead_ends", {}),
                      ("_arrived", None), ("_came_from", None),
                      ("_outcomes", {}), ("_cur_target", "flag:X"),
                      ("sightings", {}), ("map_doors", {}),
                      ("searched", {})):
        setattr(ex, attr, val)
    ex.ran = []
    ex.walked = []

    def _run_traced(sg, macro, ignore_done=False):
        ex.ran.extend(macro)
        return False, [f"{m['op']}: ok" for m in macro], list(macro)

    def _walk_route(sg, path):
        ex.walked.append(path)
        return path[-1][1]

    ex._run_traced = _run_traced
    ex._walk_route = _walk_route
    ex.log = lambda *a, **k: None
    return ex


def obs(map_id, region, warps=(), conns=(), objects=()):
    return {"map": {"id": map_id, "region": region,
                    "warps": [{"x": int(k.split(",")[0]),
                               "y": int(k.split(",")[1]),
                               "dest": "X", "reachable": True} for k in warps],
                    "connections": {d: "X" for d in conns},
                    "objects": list(objects)},
            "player": {"x": 0, "y": 0}, **U.world(1)}


SG = {"id": "t", "done_when": {"flag": "NEVER"}}


def main():
    print("explore's choice:")
    # 1) presses the unpressed thing, items first
    ex = bare(frontier={U.HERE: ["1,1"]})
    o = obs(U.MAP, "0,0", warps=["1,1"], objects=[
        {"name": "KID", "kind": "npc", "x": 2, "y": 2, "reachable": True},
        {"name": "BALL", "kind": "item", "x": 3, "y": 3, "reachable": True}])
    ex.settle = lambda: o
    done, tr, cl = ex._explore_step(SG, o)
    check("presses the unpressed item before the person or the door",
          ex.ran == [{"op": "interact", "name": "BALL"}], str(ex.ran))
    check("...and the trace says why", any("never pressed" in t for t in tr), str(tr))

    # 2) nothing unpressed here -> the untried exit
    ex = bare(frontier={U.HERE: ["1,1"]})
    ex._tried_objs = {U.HERE: {"KID"}}
    o = obs(U.MAP, "0,0", warps=["1,1"], objects=[
        {"name": "KID", "kind": "npc", "x": 2, "y": 2, "reachable": True}])
    ex.settle = lambda: o
    ex._explore_step(SG, o)
    check("takes the exit never taken when everything here is pressed",
          ex.ran == [{"op": "use_warp", "x": 1, "y": 1}], str(ex.ran))

    # 3) fully worked here -> walk to the neighbour that has something, expand once
    NEXT = f"{U.MAP}|9,9"
    ex = bare(explored={U.HERE: {"north": {"to": NEXT, "n": 3}},
                        NEXT: {"south": {"to": U.HERE, "n": 3}}},
              frontier={U.HERE: ["north"], NEXT: ["south", "7,7"]})
    ex.visits = {U.HERE: 4, NEXT: 3}
    o_here = obs(U.MAP, "0,0", conns=["north"])
    o_next = obs(U.MAP, "9,9", warps=["7,7"], conns=["south"])
    ex.settle = lambda: o_next          # after the walk we stand in NEXT
    done, tr, cl = ex._explore_step(SG, o_here)
    check("fully worked here: walks over walked ground to the area with something",
          ex.walked and ex.walked[0][0] == ("north", NEXT), str(ex.walked))
    check("...and expands once on arrival (takes the untried door there)",
          ex.ran == [{"op": "use_warp", "x": 7, "y": 7}], str(ex.ran))
    check("...saying so", any("fully worked" in t and NEXT in t for t in tr), str(tr))

    # 4) nothing anywhere
    ex = bare(explored={U.HERE: {"north": {"to": NEXT, "n": 3}},
                        NEXT: {"south": {"to": U.HERE, "n": 3}}},
              frontier={U.HERE: ["north"], NEXT: ["south"]})
    o_here = obs(U.MAP, "0,0", conns=["north"])
    ex.settle = lambda: o_here
    done, tr, cl = ex._explore_step(SG, o_here)
    check("with nothing untried anywhere it runs nothing and says so",
          ex.ran == [] and not ex.walked and any("nothing untried" in t for t in tr),
          str((ex.ran, ex.walked, tr)))

    print("\ngo, the way you know:")
    NEXT = f"{U.MAP}|9,9"
    ex = bare(explored={U.HERE: {"north": {"to": NEXT, "n": 3}},
                        NEXT: {"south": {"to": U.HERE, "n": 3}}},
              frontier={U.HERE: ["north"], NEXT: ["south"]})
    ex.visits = {U.HERE: 4, NEXT: 3}
    o_here = obs(U.MAP, "0,0", conns=["north"])
    o_next = obs(U.MAP, "9,9", conns=["south"])
    ex.settle = lambda: o_next
    done, tr, cl = ex._go_step(SG, o_here, {"op": "go", "to": NEXT})
    check("walks the walked route to a named area",
          ex.walked and ex.walked[0][0] == ("north", NEXT) and cl == [{"op": "go", "to": NEXT}],
          str((ex.walked, cl)))
    check("...and says where it got to", any("now at " + NEXT in t for t in tr), str(tr))
    ex = bare(explored={U.HERE: {"north": {"to": NEXT, "n": 3}}},
              frontier={U.HERE: ["north"]})
    ex.visits = {U.HERE: 4, NEXT: 1}
    ex.settle = lambda: o_next
    done, tr, cl = ex._go_step(SG, o_here, {"op": "go", "to": U.MAP})
    check("a bare map id picks the nearest walked area of that map",
          ex.walked and ex.walked[0][0] == ("north", NEXT), str(ex.walked))
    ex = bare(explored={}, frontier={U.HERE: ["north"]})
    ex.visits = {U.HERE: 4}
    ex.settle = lambda: o_here
    done, tr, cl = ex._go_step(SG, o_here, {"op": "go", "to": "CELADON_CITY"})
    check("an unwalked place is refused by name, nothing walked",
          not ex.walked and any("not anywhere you have walked" in t for t in tr), str(tr))
    ex = bare(explored={}, frontier={U.HERE: ["north"], NEXT: ["south"]})
    ex.visits = {U.HERE: 4, NEXT: 1}
    ex.settle = lambda: o_here
    done, tr, cl = ex._go_step(SG, o_here, {"op": "go", "to": NEXT})
    check("a walked place with no walked route says so, nothing walked",
          not ex.walked and any("no walked way" in t for t in tr), str(tr))
    done, tr, cl = ex._go_step(SG, o_here, {"op": "go", "to": U.HERE})
    check("already there is said, nothing walked",
          not ex.walked and any("already in" in t for t in tr), str(tr))

    print("\nthe blockers ledger:")
    NEXT = f"{U.MAP}|9,9"
    ex = bare(explored={U.HERE: {"north": {"to": NEXT, "n": 3}},
                        NEXT: {"south": {"to": U.HERE, "n": 3}}},
              frontier={U.HERE: ["north"], NEXT: ["south", "7,7"]})
    ex.visits = {U.HERE: 4, NEXT: 3}
    ex.blockers = {}
    ex._save_memory = lambda: None
    o_here = obs(U.MAP, "0,0", conns=["north"])
    ex._note_blocker(NEXT, "7,7", "door", 'it said: "I\'m thirsty"')
    ex._note_blocker(NEXT, "7,7", "door", "")
    ex._note_blocker("FAR|1,1", "3,3", "door", "a GHOST appeared in the way")
    b = ex.blockers[f"{NEXT}|7,7"]
    check("a shut way is recorded once, bumped, words kept",
          b["n"] == 2 and "thirsty" in b["what"] and len(ex.blockers) == 2, str(ex.blockers))
    txt = ex.blockers_text(o_here)
    check("rendered nearest first (routed 1 leg before no-route)",
          txt.index(NEXT) < txt.index("FAR|1,1") and "nothing named yet" in txt, txt)
    lines = ex._declare_blockers(
        [{"where": NEXT, "lifts": {"has_item": {"FRESH_WATER": 1}}}], o_here)
    check("the model's lifting condition is taken by area and echoed",
          b["lifts"] == {"has_item": {"FRESH_WATER": 1}} and lines and "lifts it" in lines[0],
          str((b, lines)))
    txt = ex.blockers_text(o_here)
    check("...and rendered as 'not yet' when it does not hold", "not yet" in txt, txt)
    o_held = dict(o_here); o_held["bag"] = {"FRESH_WATER": 1}
    txt = ex.blockers_text(o_held)
    check("...and 'HOLDS NOW' when it does", "HOLDS NOW" in txt, txt)
    ex._clear_blocker(NEXT, "7,7", "it opened")
    txt = ex.blockers_text(o_here)
    check("a cleared way leaves the list", NEXT not in txt and "FAR|1,1" in txt, txt)
    lines = ex._declare_blockers([{"where": "FAR|1,1", "cleared": True}], o_here)
    check("the model can declare one dealt with", ex.blockers["FAR|1,1|3,3"]["cleared"]
          and ex.blockers_text(o_here) == "", str(lines))
    E.Executor._last_decls = []
    ops, plan = E.Executor._parse_macro(
        '{"plan":"x","ops":[{"op":"wait"}],"blockers":[{"where":"A|1,1","lifts":{"flag":"F"}}]}')
    check("the reply parser keeps the blockers key",
          E.Executor._last_decls == [{"where": "A|1,1", "lifts": {"flag": "F"}}],
          str(E.Executor._last_decls))

    print("\nthe reply parser:")
    ops, plan = E.Executor._parse_macro(
        'Sure. {"plan":"go north to Route 2, the gate is that way","ops":'
        '[{"op":"cross","dir":"north"}]} done')
    check("object form: ops and plan", ops == [{"op": "cross", "dir": "north"}]
          and plan.startswith("go north"), str((ops, plan)))
    ops, plan = E.Executor._parse_macro('[{"op":"interact","name":"CLERK"}] trailing')
    check("bare array still parses, no plan", ops == [{"op": "interact", "name": "CLERK"}]
          and plan == "", str((ops, plan)))
    ops, plan = E.Executor._parse_macro('{"op":"cross","dir":"west"}')
    check("a single op object is one op", ops == [{"op": "cross", "dir": "west"}], str(ops))
    ops, plan = E.Executor._parse_macro('{"plan":"[think] first", "ops":[{"op":"wait"}]}')
    check("a plan containing '[' does not fool the array path",
          ops == [{"op": "wait"}] and plan == "[think] first", str((ops, plan)))
    ops, plan = E.Executor._parse_macro('nothing here')
    check("no JSON at all -> no ops", ops in (None, []) , str(ops))

    print(f"\n{'-' * 60}")
    if FAILS:
        print(f"BROKEN: {len(FAILS)} check(s) failed")
        return 1
    print("explore chooses what the ledger ranks first; the parser keeps the plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
