#!/usr/bin/env python3
"""Leaving a building to the place you came in from is a real step.

Run 16, 2026-09-07: "a party Pokemon knows CUT" could not be planned. Every
draft opened with "exit the S.S. Anne" ending on {"map": "VERMILION_CITY"},
and the validator refused it fifteen rounds running as a condition "TRUE the
moment you stand on any part you already know" — while the run stood on the
ship's second deck, three doors in from the city. The leg was pushed; so
was the Spearow trade before it. The refusal was written for Mt Moon, whose
far exit lands on a route already stood on from the near side, and it
cannot tell that case from the plain meaning of "leave". Now the run's own
door record settles it: if the run walked INTO this place FROM that map
within a few doors, and the step's words name no far side, leaving to it is
witnessed by reaching it.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner"))
import author as A   # noqa: E402
checks = []
def ck(n, ok): checks.append((n, bool(ok)))

ship = {"VERMILION_CITY|18,0": {"18,31": {"to": "VERMILION_DOCK|14,0"}},
        "VERMILION_DOCK|14,0": {"14,2": {"to": "SS_ANNE_1F|26,0"}, "14,0": {"to": "VERMILION_CITY|18,0"}},
        "SS_ANNE_1F|26,0": {"2,6": {"to": "SS_ANNE_2F|2,4"}, "37,15": {"to": "SS_ANNE_B1F|7,3"}},
        "SS_ANNE_2F|2,4": {"2,12": {"to": "SS_ANNE_3F|2,2"}}}
ck("three doors in from the city, the ship came from the city",
   A._came_from("SS_ANNE_2F", "VERMILION_CITY", ship))
ck("...and so did its first deck", A._came_from("SS_ANNE_1F", "VERMILION_CITY", ship))
ck("a place never walked into from there is not 'come from'",
   not A._came_from("SS_ANNE_2F", "CERULEAN_CITY", ship))
ck("the hop limit holds (four doors is not 'a few')",
   not A._came_from("SS_ANNE_3F", "VERMILION_CITY", ship, hops=2))
ck("far-side words keep the old refusal alive",
   A._SIDE.search("exit onto the east side of Route 4") and A._SIDE.search("come out the other side")
   and not A._SIDE.search("exit the S.S. Anne to Vermilion City"))
src = (ROOT / "planner" / "author.py").read_text()
ck("the exit rule consults both",
   "and not (_came_from(_from5, _m5) and not _SIDE.search(_w5))" in src)

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
