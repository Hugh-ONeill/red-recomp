#!/usr/bin/env python3
"""A road never crossed says what the run's own record shows of its side.

The run stood on Route 10's north half forty times cutting four bushes for
a way south to Lavender that is not there. Its record held every fact: the
map is 72 rows tall, the looked-at ground ended at row 32, the south row
had never been on screen, and its one walked part had no southward
crossing. The road's line said "stood in ROUTE_10 40x, never once reached
LAVENDER_TOWN" and a caveat that a map can be split — and the author's copy
of the block carried a hand-written answer ("Route 10's south end is past
Rock Tunnel"), which is the one kind of sentence this harness may not
write, and which did not help either (2026-09-03).

Now the caveat is made specific from the mask and the walked graph, on
both pages, for every such road: whether that side has ever been on
screen, how far short of it the looked-at ground ends, whether any
crossing from a walked part ever used it. Where to go instead is not said.

Synthetic: a mask file and a walked graph in a temp dir, no game.
"""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A                                            # noqa: E402

checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))

A.MAP_EDGES = {"ROUTE_10": {"west": "ROUTE_9", "south": "LAVENDER_TOWN"},
               "ROUTE_9": {"east": "ROUTE_10", "west": "CERULEAN_CITY"}}
A._MAP_DIMS = {"ROUTE_10": (20, 72), "ROUTE_9": (60, 18)}

with tempfile.TemporaryDirectory() as d:
    mask = Path(d) / "seen.json"
    r10 = ", ".join(f'"{x},{y}"' for x in range(20) for y in range(0, 33))
    r9 = ", ".join(f'"{x},{y}"' for x in range(60) for y in range(18))
    mask.write_text('return {\n  ["ROUTE_10"] = { ' + r10 + ' },\n'
                    '  ["ROUTE_9"] = { ' + r9 + ' },\n}\n')
    explored = {"ROUTE_10|0,4": {"west": {"to": "ROUTE_9|0,8"}, "11,19": {"to": "ROCK_TUNNEL_1F|14,2"}},
                "ROUTE_9|0,8": {"east": {"to": "ROUTE_10|0,4"}, "west#skip1": {"to": "CERULEAN_CITY|26,7"}}}
    visits = {"ROUTE_10|0,4": 40, "ROUTE_9|0,8": 44}

    w = A.road_side_words("ROUTE_10", "LAVENDER_TOWN", explored, visits, path=mask)
    ck("a side never on screen says so", "that side of ROUTE_10 has never been on screen" in w, w)
    ck("...and how far short of it the looked-at ground ends", "ends 39 row(s) short of it" in w, w)
    ck("...and that no crossing from a walked part used it",
       "no crossing of yours has used it from the one part of ROUTE_10 you have stood on" in w, w)
    ck("...without naming where the other part is entered",
       "ROCK_TUNNEL" not in w and "Rock Tunnel" not in w, w)
    ck("a road seen and crossed adds nothing",
       A.road_side_words("ROUTE_9", "ROUTE_10", explored, visits, path=mask) == "")
    w2 = A.road_side_words("ROUTE_9", "CERULEAN_CITY", explored, visits, path=mask)
    ck("a seam crossing recorded under a skip variant counts as used", w2 == "", w2)
    ck("a road the printed map does not draw says nothing",
       A.road_side_words("ROUTE_10", "PALLET_TOWN", explored, visits, path=mask) == "")
    ck("no mask, no claim",
       A.road_side_words("ROUTE_10", "LAVENDER_TOWN", explored, visits,
                         path=Path(d) / "missing.json") == "")
    ck("columns for an east/west side",
       "column(s)" in A.road_side_words(
           "ROUTE_9", "CERULEAN_CITY", {"ROUTE_9|0,8": {}}, {"ROUTE_9|0,8": 3},
           path=Path(d) / "half.json")
       if Path(d, "half.json").write_text(
           'return {\n  ["ROUTE_9"] = { ' + ", ".join(f'"{x},{y}"' for x in range(20, 60) for y in range(18)) + ' },\n}\n') else False)

src_a = (ROOT / "planner" / "author.py").read_text()
src_e = (ROOT / "planner" / "executor.py").read_text()
ck("the author's road line carries it", "side = road_side_words(m, nb, d.get(\"explored\") or {}," in src_a)
ck("the walker's road line carries it", "side = _a.road_side_words(m, nb, self.explored or {}," in src_e)
ck("the hand-written answer is gone from the author's brief",
   "Route 10's south end is past Rock Tunnel, so standing" not in src_a)
ck("...and the caveat says where the specific fact now lives",
   "where the run's own record says that side has never been" in src_a)

bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:300])
sys.exit(1 if bad else 0)
