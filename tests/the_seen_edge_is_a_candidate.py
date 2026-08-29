#!/usr/bin/env python3
"""A spot where seen ground ends is a ledger CANDIDATE, not just head text.

Footprint leftover (b). The frontier reached the model only as a head
sentence, so the one thing the footprint calls unfinished never competed
with the doors in the ranked, numbered list — and position is the budget.
The trap that deferred this: a frontier cell vanishes the moment the
ground past it comes on screen, so a STORED door-style status would mean
nothing. The design under test: rows are minted fresh from THIS
observation's map.frontier on every build — status "unlooked" is computed,
never remembered — and they disappear with the frontier itself. Ranking:
coverage beats untried doors among equally fresh rows (the same order
explore's own deed follows: sweep first), but a thing that answers the
goal still beats coverage. untried_keys stays doors/seams only (the law
with _untried_exits); fully_worked is False while an unlooked spot stands.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))
sys.path.insert(0, str(ROOT / "tests"))

import candidates as C        # noqa: E402  (its fixture helpers)
import untried as U           # noqa: E402
import ledger as L            # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    ex = C.make(frontier={U.HERE: []})
    o = C.obs(ex, ["1,0", "5,5"])
    o["map"]["frontier"] = [
        {"x": 14, "y": 3, "d": 2}, {"x": 22, "y": 17, "d": 9},
        {"x": 2, "y": 9, "d": 11}, {"x": 30, "y": 1, "d": 14},
        {"x": 31, "y": 2, "d": 15}, {"x": 8, "y": 8, "d": 20}]
    o["map"]["seen"] = {"n": 40, "frontier_n": 6}
    o["map"]["frontier_water"] = [{"x": 40, "y": 12, "d": 7}]
    cands = L.build(ex, o, target="flag:X")
    fr = [c for c in cands if c.kind == "frontier"]

    check("frontier spots become candidates, capped, nearest first",
          len(fr) == 5 and fr[0].key == "14,3"
          and all(c.status == "unlooked" for c in fr),
          f"{[(c.key, c.status) for c in fr]}")
    check("...capped at 4 on foot + 2 by water",
          len([c for c in fr if not c.by_water]) == 4
          and len([c for c in fr if c.by_water]) == 1)
    doors = [c for c in cands if c.kind == "door" and c.status == "untried"]
    check("coverage outranks an untried door (explore's own deed order)",
          doors and cands.index(fr[0]) < cands.index(doors[0]))
    check("the water spot carries the swim contract",
          any(c.by_water and "SURF" in c.note and '"surf":true' in c.note
              for c in fr))
    check("untried_keys stays doors/seams only (the _untried_exits law)",
          "14,3" not in L.untried_keys(cands))
    check("a walk at a frontier spot is on-ledger (permissive op)",
          L.lookup(cands, {"op": "walk_to", "x": 14, "y": 3}) is not None)

    # a thing that answers the goal still beats coverage
    o2 = C.obs(ex, ["1,0"], objects=[{"name": "ITEM_5_5", "kind": "item",
                                      "x": 5, "y": 5, "reachable": True}])
    o2["map"]["frontier"] = [{"x": 14, "y": 3, "d": 2}]
    c2 = L.build(ex, o2, target="item:POTION")
    _it = [c for c in c2 if c.kind == "item"]
    _fr2 = [c for c in c2 if c.kind == "frontier"]
    check("a goal-answering thing still outranks coverage",
          _it and _fr2 and c2.index(_it[0]) < c2.index(_fr2[0]))

    # the rows vanish with the frontier — nothing is remembered
    o3 = C.obs(ex, ["1,0", "5,5"])
    c3 = L.build(ex, o3, target="flag:X")
    check("no frontier in the observation, no frontier rows (never stored)",
          not [c for c in c3 if c.kind == "frontier"])

    check("an unlooked spot keeps a floor from reading fully worked",
          not L.fully_worked([L.Candidate(key="1,1", kind="frontier",
                                          status="unlooked")])
          and L.fully_worked([]))
    check("...but a WATER spot alone leaves 'done ON FOOT' sayable",
          L.fully_worked([L.Candidate(key="8,40", kind="frontier",
                                      status="unlooked", by_water=True)]))

    page = L.render(cands, ex, o, target="flag:X")
    check("the row is numbered, named, and says never-on-screen",
          "seen ground ends at (14,3)" in page
          and "NEVER BEEN ON SCREEN" in page
          and "(frontier at" not in page,
          page[:400])
    exsrc = (ROOT / "planner" / "executor.py").read_text()
    check("the OFF-LEDGER message does not offer frontier coords as things",
          '("door", "seam", "op",\n                                           "frontier")' in exsrc)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
