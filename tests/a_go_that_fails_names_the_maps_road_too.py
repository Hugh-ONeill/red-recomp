#!/usr/bin/env python3
"""A go that fails names the printed map's road beside the record's break.

Run 16 (2026-09-08), Lavender Town, Vermilion the goal: the refusal named
the one map where the walked chain broke — Route 9, fifteen legs back the
way the run had come — and handed over the ops that join it. The model did
as it was told: to Route 9, east again, back to Lavender, the same refusal.
The printed map in its bag drew Vermilion three legs south the whole time
(user: "once it gets to lavender town it tries to 'go' to vermillion city
which brings it right back to rt 9 again"). One way named is a pointer; two
ways named with their lengths is a choice. Synthetic: a bare executor with
a small record.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "planner"))

import executor as E                                   # noqa: E402

fails = []


def ck(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def bare(explored, region_seen=None, no_cross=None):
    ex = E.Executor.__new__(E.Executor)
    ex.explored = explored
    ex.frontier = {}
    ex.region_seen = region_seen or {}
    ex._no_cross = no_cross or {}
    ex._no_cross_at = {}
    ex._mark_now = None
    return ex


# the record as it stood: Lavender reached from the north, Route 12 south of
# it walked into, never across; Route 9 walked eastward only
REC = {
    "LAVENDER_TOWN|6,0": {"north": {"to": "ROUTE_10|14,52", "n": 1},
                          "south": {"to": "ROUTE_12|8,0", "n": 1}},
    "ROUTE_12|8,0": {"north": {"to": "LAVENDER_TOWN|6,0", "n": 1},
                     "10,15": {"to": "ROUTE_12_GATE_1F|3,0", "n": 1}},
    "ROUTE_12_GATE_1F|3,0": {"4,0": {"to": "ROUTE_12|8,0", "n": 1}},
    "ROUTE_9|0,8": {"west": {"to": "CERULEAN_CITY|26,7", "n": 4},
                    "walk:ROUTE_9|6,2": {"to": "ROUTE_9|6,2", "n": 1}},
    "ROUTE_9|6,2": {"east": {"to": "ROUTE_10|0,4", "n": 2}},
    "CERULEAN_CITY|26,7": {"south": {"to": "ROUTE_5|1,0", "n": 6}},
    "ROUTE_5|1,0": {"south": {"to": "VERMILION_CITY|18,0", "n": 1}},
}
E.PRINTED_MAP_HELD = True
gap = ("ROUTE_9", "ROUTE_9|6,2", "ROUTE_9|0,8")

ex = bare(REC, region_seen={"ROUTE_12|8,0": 3})
note = ex._printed_road_note("ROUTE_12|8,0", "VERMILION_CITY", gap)
ck("the map's road is drawn leg by leg", "ROUTE_12 --west--> ROUTE_11 --west--> VERMILION_CITY" in note)
ck("...with its length", "(2 leg(s))" in note)
ck("the first leg the record has never seen crossed is named", "this map's west edge to ROUTE_11, has never been crossed" in note)
ck("unseen ground on this floor is said to maybe hold the way", "ground never on screen (3 spot(s))" in note)
ck("the op that takes a printed road is the cross, one seam at a time", '{"op":"cross","dir":"west"}' in note)

ex = bare(REC)
note = ex._printed_road_note("LAVENDER_TOWN|6,0", "VERMILION_CITY", gap)
ck("from Lavender the road runs south", "LAVENDER_TOWN --south--> ROUTE_12 --west--> ROUTE_11 --west--> VERMILION_CITY (3 leg(s))" in note)
ck("Lavender's south edge IS walked, so the first uncrossed leg is Route 12's",
   "Its leg ROUTE_12 --west--> ROUTE_11 has never been crossed" in note)

ex = bare(REC, no_cross={"ROUTE_12|8,0": {"west"}})
note = ex._printed_road_note("ROUTE_12|8,0", "VERMILION_CITY", gap)
ck("a seam proven uncrossable from this part says so, and that another part may reach it",
   "proven uncrossable from THIS part of ROUTE_12" in note and "another part of ROUTE_12 may reach it" in note)

ex = bare(REC)
note = ex._printed_road_note("ROUTE_12_GATE_1F|3,0", "VERMILION_CITY", gap)
ck("from inside a gate (on no road's door list) the road is read from the door you walked out of", "ROUTE_12 --west--> ROUTE_11" in note)

E.PRINTED_MAP_HELD = False
ck("no printed map in the bag, no road named", ex._printed_road_note("ROUTE_12|8,0", "VERMILION_CITY", gap) == "")
E.PRINTED_MAP_HELD = True

src = (ROOT / "planner" / "executor.py").read_text()
ck("the go refusal carries the note", "+ _note_b + _note_g + _note_m], []" in src)
sys.exit(1 if fails else 0)
